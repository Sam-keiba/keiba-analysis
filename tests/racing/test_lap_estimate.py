"""個別推定ラップの算出（lap_estimate.py）。"""

import pytest

from keiba_analysis.racing.lap_estimate import (
    run_key,
    DEFAULT_FIELD_SPREAD_SEC,
    EARLY_SPREAD_FACTOR,
    SETTLE_DISTANCE_M,
    calibrate_field_spread,
    gap_at,
    estimate_run,
    estimate_runs,
    split_floats,
)

# 中山芝2000m（10区間）を想定したレース。先頭の合計＝119.5秒、上がり3F＝35.1秒
LAPS = [12.5, 11.0, 12.0, 12.2, 12.4, 12.3, 12.0, 11.8, 11.6, 11.7]
WINNER_TIME = round(sum(LAPS), 1)
RACE_LAST_3F = round(sum(LAPS[-3:]), 1)

RUN = {
    "race_id": "202606040411", "venue_code": "06", "surface": "turf",
    "distance_m": 2000, "course_detail": None, "n_runners": 16,
    "race_laps": "-".join(str(x) for x in LAPS),
    "lap_distances": "-".join(str(200 * i) for i in range(1, 11)),
    "time_sec": WINNER_TIME, "last_3f": RACE_LAST_3F, "corner_passing": "1-1-1-1",
}
CLOSER = {  # 後方から差した馬（通過順が後ろで、上がりが速い）
    **RUN, "corner_passing": "12-12-10-8", "time_sec": WINNER_TIME + 0.5, "last_3f": 34.5,
}


def test_split_floats():
    assert split_floats("12.3-11.2") == [12.3, 11.2]
    assert split_floats(None) == []
    assert split_floats("12.3-x") == []


def test_total_matches_the_actual_time():
    """推定ラップの合計は、実際の走破タイムと一致する（作り方からそうなる）。"""
    for run in (RUN, CLOSER):
        estimate = estimate_run(run)
        assert estimate is not None
        assert estimate.total == pytest.approx(run["time_sec"], abs=0.05)


def test_last_three_segments_match_the_measured_last_3f():
    """最後の3区間の合計は、実測の上がり3Fと一致する。"""
    estimate = estimate_run(CLOSER)
    assert sum(estimate.values[-3:]) == pytest.approx(CLOSER["last_3f"], abs=0.05)


def test_closer_runs_slower_early_and_faster_late_than_the_leader():
    """差す馬は、序盤が先頭のラップより遅く、最後は速くなる。"""
    estimate = estimate_run(CLOSER)
    assert estimate.values[0] > LAPS[0]      # 序盤は先頭より遅い
    assert estimate.values[-1] < LAPS[-1]    # 最後は先頭より速い
    assert not estimate.is_reference


def test_front_runner_is_close_to_the_race_lap():
    """終始先頭の馬は、レースラップとほぼ同じになる。"""
    estimate = estimate_run(RUN)
    assert all(abs(v - lap) < 0.15 for v, lap in zip(estimate.values, LAPS, strict=True))


def test_missing_corner_passing_is_a_reference_value():
    """コーナー通過順が無い走は、上がり3Fのアンカーだけで出す参考値になる。"""
    estimate = estimate_run({**CLOSER, "corner_passing": None})
    assert estimate is not None
    assert estimate.is_reference
    assert estimate.total == pytest.approx(CLOSER["time_sec"], abs=0.05)
    # 上がり3Fは実測どおりだが、序盤の遅れは表現されない
    assert sum(estimate.values[-3:]) == pytest.approx(CLOSER["last_3f"], abs=0.05)


def test_runs_without_laps_are_not_estimated():
    assert estimate_run({**RUN, "race_laps": None, "lap_distances": None}) is None
    assert estimate_run({**RUN, "race_laps": "12.0-11.0", "lap_distances": "200-400-600"}) is None
    assert estimate_run({**RUN, "time_sec": None}) is None


def test_impossible_segments_become_missing():
    """ありえない区間ラップ（8秒未満・20秒超）は、その区間だけ欠損にする。"""
    slow = {**RUN, "time_sec": 240.0, "last_3f": 60.0}      # 後半だけ極端に遅い
    estimate = estimate_run(slow)
    assert estimate is not None
    assert None in estimate.values                           # 線が切れる区間ができる
    assert all(v is None or 8.0 <= v <= 20.0 for v in estimate.values)


def test_runs_with_too_many_impossible_segments_are_dropped():
    """欠損が全区間の1/3を超えたら、その走は推定しない。"""
    absurd = {**RUN, "time_sec": 400.0, "last_3f": 120.0}
    assert estimate_run(absurd) is None


def test_calibrate_field_spread():
    """残り600mの差と『正規化した位置』から、隊列の広がり（先頭〜最後方の秒差）を求める。"""
    leader_at_600 = sum(LAPS[:-3])
    # 5頭立て。最後方（5番手＝位置1.0）が1.6秒後ろ、3番手（位置0.5）が0.8秒後ろ
    field = [
        {"time_sec": WINNER_TIME, "last_3f": RACE_LAST_3F, "corner_passing": "1-1-1-1"},
        {"time_sec": WINNER_TIME + 0.8, "last_3f": RACE_LAST_3F, "corner_passing": "3-3-3-3"},
        {"time_sec": WINNER_TIME + 1.6, "last_3f": RACE_LAST_3F, "corner_passing": "5-5-5-5"},
    ]
    assert calibrate_field_spread(field, leader_at_600, 5) == pytest.approx(1.6, abs=0.01)


def test_calibration_falls_back_to_the_default():
    assert calibrate_field_spread([], 100.0, 16) is None
    assert calibrate_field_spread([{"time_sec": None}], 100.0, 16) is None
    assert calibrate_field_spread([], None, 16) is None
    # 既定値はDB全体（2025年以降5,741レース）の中央値
    assert DEFAULT_FIELD_SPREAD_SEC == pytest.approx(1.7)


def test_gap_uses_the_position_ratio_so_field_size_matters():
    """同じ『5番手』でも、頭数が多いほど隊列の中では前寄り＝先頭との差は小さい。"""
    closing = 1400.0
    small = gap_at(2.0, 5, 6, closing, closing)     # 6頭の5番手＝位置0.8
    large = gap_at(2.0, 5, 18, closing, closing)    # 18頭の5番手＝位置0.24
    assert small > large
    assert gap_at(2.0, 1, 16, closing, closing) == 0.0        # 先頭は差0


def test_gap_is_wider_early_in_the_race():
    """同じ位置取りでも、序盤のほうが先頭との差は大きい。"""
    closing = 1400.0
    early = gap_at(2.0, 10, 16, 400.0, closing)
    late = gap_at(2.0, 10, 16, closing, closing)
    assert early > late
    assert early / late == pytest.approx(1 + (EARLY_SPREAD_FACTOR - 1) * (1 - 400 / closing), abs=0.01)


def test_estimate_runs_uses_per_race_calibration():
    """レースごとの較正が効くと、同じ走でも推定が変わる。"""
    wide = [  # 隊列が大きく広がったレース（最後方が3秒後ろ）
        {"time_sec": WINNER_TIME, "last_3f": RACE_LAST_3F, "corner_passing": "1-1-1-1"},
        {"time_sec": WINNER_TIME + 3.0, "last_3f": RACE_LAST_3F, "corner_passing": "16-16-16-16"},
    ]
    default = estimate_runs([CLOSER])[run_key(CLOSER)]
    calibrated = estimate_runs([CLOSER], {CLOSER["race_id"]: wide})[run_key(CLOSER)]
    assert default.values != calibrated.values
    assert calibrated.total == pytest.approx(CLOSER["time_sec"], abs=0.05)


def test_estimate_runs_skips_runs_without_material():
    result = estimate_runs([{**RUN, "race_laps": None, "lap_distances": None}])
    assert result == {}


# 1700m（100m始まり）: 区間は 100m / 200m×8
SHORT_FIRST = {
    **RUN, "distance_m": 1700, "venue_code": "06", "surface": "dirt", "n_runners": 16,
    "race_laps": "7.0-11.5-12.0-12.5-12.5-12.5-12.5-12.5-12.5",
    "lap_distances": "100-300-500-700-900-1100-1300-1500-1700",
    "time_sec": 105.5, "last_3f": 37.5, "corner_passing": "5-5-5-5",
}


def test_short_first_segment_is_not_treated_as_impossible():
    """最初の区間が100mのレース（1500m・1700m・2500mなど）でも欠損にしない。

    100mを6〜7秒で走るのは普通なので、200mあたりに直してから判定する。
    """
    estimate = estimate_run(SHORT_FIRST)
    assert estimate is not None
    assert estimate.values[0] is not None
    assert 6.0 < estimate.values[0] < 8.0          # 100m区間なので7秒前後
    assert None not in estimate.values
    assert estimate.total == pytest.approx(SHORT_FIRST["time_sec"], abs=0.05)


# --- 同じレースを複数の馬が走っている場合（馬柱で起きた不具合の回帰テスト） -----


def test_each_horse_of_the_same_race_gets_its_own_estimate():
    """同じレースでも、馬ごとに別の推定を返す。

    以前はレースIDだけをキーにしていたため、馬柱で同じレースを走った2頭目以降に
    1頭目（多くは勝ち馬）の推定がそのまま出てしまっていた。
    """
    leader = {**RUN, "umaban": 4}
    closer = {**CLOSER, "umaban": 12}
    result = estimate_runs([leader, closer])

    assert set(result) == {run_key(leader), run_key(closer)}
    first_3f = {key: sum(est.values[:3]) for key, est in result.items()}
    # 先行馬のほうが前半3Fは速く、後方から行く馬は遅い（同じレースでも中身が違う）
    assert first_3f[run_key(leader)] < first_3f[run_key(closer)] - 0.5


def test_the_same_horse_is_estimated_once():
    """同じ馬・同じレースが2回渡っても、1回だけ計算する。"""
    result = estimate_runs([RUN, dict(RUN)])
    assert len(result) == 1


# --- 前半3Fの遅れ（その馬が先頭から何秒後ろで最初の3Fを走ったか） ---------------


def _first_3f(run: dict) -> float:
    estimate = estimate_run(run)
    return sum(estimate.values[:3])


def test_early_gap_is_zero_for_the_front_runner():
    """終始先頭の馬は、前半3Fがレースラップそのもの（遅れ0）。"""
    assert _first_3f(RUN) == pytest.approx(sum(LAPS[:3]), abs=0.15)


def test_horses_further_back_are_further_behind():
    """同じレースなら、後ろにいた馬ほど前半3Fが遅い。"""
    mid = {**RUN, "corner_passing": "6-6-6-6", "time_sec": WINNER_TIME + 0.3, "last_3f": 34.8}
    back = {**RUN, "corner_passing": "14-14-12-10", "time_sec": WINNER_TIME + 0.3, "last_3f": 34.8}
    assert _first_3f(RUN) < _first_3f(mid) < _first_3f(back)


def test_a_bigger_gap_at_the_closing_point_means_a_bigger_early_gap():
    """残り600m地点で離れていた馬ほど、前半の遅れも大きい（実測を軸にしている）。"""
    # 上がりは同じで、走破タイムだけ違う＝残り600m地点で離れていた馬
    close = {**CLOSER, "time_sec": WINNER_TIME + 0.2, "last_3f": 34.5}
    far = {**CLOSER, "time_sec": WINNER_TIME + 2.0, "last_3f": 34.5}
    assert _first_3f(far) > _first_3f(close)


def test_a_fast_early_pace_strings_the_field_out():
    """前半が速いレースほど、同じ位置でも前半3Fの遅れが大きくなる。"""
    fast = [11.8, 10.9, 11.3, 12.4, 12.6, 12.6, 12.3, 12.1, 12.0, 12.0]   # 前半3F 34.0
    slow = [12.9, 12.3, 12.5, 12.4, 12.3, 12.0, 11.8, 11.6, 11.4, 11.5]   # 前半3F 37.7
    def run_with(laps):
        return {**CLOSER, "race_laps": "-".join(str(x) for x in laps),
                "time_sec": sum(laps) + 0.5, "last_3f": sum(laps[-3:]) - 0.5}
    fast_gap = _first_3f(run_with(fast)) - sum(fast[:3])
    slow_gap = _first_3f(run_with(slow)) - sum(slow[:3])
    assert fast_gap > slow_gap + 0.3


def test_early_gap_needs_the_measured_material():
    """タイム・上がり・通過順のどれかが欠けていれば、前半3Fの推定はしない。"""
    from keiba_analysis.racing.lap_estimate import early_gap, split_floats
    laps = split_floats(CLOSER["race_laps"])
    bounds = [0.0, *split_floats(CLOSER["lap_distances"])]
    cumulative = [sum(laps[: i + 1]) for i in range(len(laps))]
    assert early_gap(CLOSER, laps, bounds, cumulative) > 0
    assert early_gap({**CLOSER, "last_3f": None}, laps, bounds, cumulative) is None
    assert early_gap({**CLOSER, "corner_passing": None}, laps, bounds, cumulative) is None


def test_early_gap_is_capped():
    """材料が極端でも、前半3Fの遅れは上限を超えない（小頭数で暴れないように）。"""
    from keiba_analysis.racing.lap_estimate import MAX_EARLY_GAP_SEC, early_gap, split_floats
    laps = split_floats(CLOSER["race_laps"])
    bounds = [0.0, *split_floats(CLOSER["lap_distances"])]
    cumulative = [sum(laps[: i + 1]) for i in range(len(laps))]
    wild = {**CLOSER, "n_runners": 7, "corner_passing": "7-7-7-7",
            "time_sec": WINNER_TIME + 20.0, "last_3f": 40.0}
    assert early_gap(wild, laps, bounds, cumulative) <= MAX_EARLY_GAP_SEC
