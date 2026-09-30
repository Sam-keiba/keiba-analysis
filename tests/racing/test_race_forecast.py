"""同条件の平均ラップと、本日の想定ラップ（race_forecast.py）。"""

import pytest

from keiba_analysis.racing.race_forecast import (
    CLOSING_TRADE_OFF,
    CUSHION_SEC_PER_FURLONG,
    FRONT_RUNNER_SHARE,
    PREVIOUS_RULES,
    TODAY_SOLO_WEIGHT,
    TODAY_SOLO_WEIGHTS,
    average_laps,
    bias_delta,
    CUSHION_SEC_PER_FURLONG,
    format_race_time,
    going_delta,
    moisture_delta,
    three_furlong_split,
    time_label,
    bias_from_races,
    cushion_delta,
    opening_delta,
    project_laps,
    track_bias,
)

DISTANCES = "-".join(str(200 * i) for i in range(1, 11))  # 2000m＝10区間


def race(laps, cushion=9.2, n_runners=10):
    return {
        "race_laps": "-".join(str(x) for x in laps),
        "lap_distances": DISTANCES,
        "cushion_value": cushion,
        "n_runners": n_runners,
    }


RACES = [
    race([12.6, 11.2, 12.4, 12.2, 12.0, 11.9, 11.8, 11.7, 11.6, 12.0], cushion=9.0, n_runners=10),
    race([12.8, 11.6, 12.4, 12.4, 12.0, 12.1, 11.8, 11.7, 11.8, 12.2], cushion=9.4, n_runners=10),
]


def test_average_laps():
    average = average_laps(RACES)
    assert average.races == 2
    assert average.laps[0] == pytest.approx(12.7)
    assert average.laps[1] == pytest.approx(11.4)
    assert average.deviations[1] == pytest.approx(0.2, abs=0.01)   # ばらつきの帯に使う
    assert average.cushion == pytest.approx(9.2)
    assert average.field_size == pytest.approx(10.0)
    assert average.front_runners == pytest.approx(10.0 * FRONT_RUNNER_SHARE)
    assert average.total == pytest.approx(sum(average.laps))


def test_average_skips_broken_or_mismatched_rows():
    mixed = [*RACES, {"race_laps": "12.0-11.0", "lap_distances": "200-400"},  # 区間数が違う
             {"race_laps": None, "lap_distances": None}]
    assert average_laps(mixed).races == 2
    assert average_laps([]) is None


def test_more_front_runners_make_the_opening_faster():
    average = average_laps(RACES)
    many = project_laps(average, front_runners=8, field_size=10, cushion=average.cushion)
    few = project_laps(average, front_runners=1, field_size=10, cushion=average.cushion)
    assert sum(many[:3]) < sum(average.laps[:3]) < sum(few[:3])
    # 前半が速いぶん、上がりは遅くなる（前後半のつり合い）
    assert sum(many[-3:]) > sum(average.laps[-3:]) > sum(few[-3:])


def test_bigger_field_makes_the_opening_faster():
    average = average_laps(RACES)
    big = project_laps(average, front_runners=4, field_size=18, cushion=average.cushion)
    small = project_laps(average, front_runners=4, field_size=6, cushion=average.cushion)
    assert sum(big[:3]) < sum(small[:3])


def test_firmer_cushion_makes_every_segment_faster():
    average = average_laps(RACES)
    firm = project_laps(average, front_runners=4, field_size=10, cushion=10.5)
    soft = project_laps(average, front_runners=4, field_size=10, cushion=8.0)
    assert all(f < s for f, s in zip(firm, soft, strict=True))
    assert sum(firm) < sum(average.laps) < sum(soft)


def test_no_cushion_means_no_cushion_correction():
    """ダートはクッション値が無いので、その補正はかからない。"""
    dirt = average_laps([race(RACES[0]["race_laps"].split("-") and
                              [12.6, 11.2, 12.4, 12.2, 12.0, 11.9, 11.8, 11.7, 11.6, 12.0], cushion=None)])
    assert dirt.cushion is None
    assert cushion_delta(dirt, 10.5) == 0.0
    assert project_laps(dirt, front_runners=4, field_size=10, cushion=10.5) == pytest.approx(
        project_laps(dirt, front_runners=4, field_size=10), abs=0.01
    )


def test_unknown_members_leave_the_average_untouched():
    average = average_laps(RACES)
    assert opening_delta(average, None, None) == 0.0
    assert project_laps(average, cushion=average.cushion) == pytest.approx(average.laps, abs=0.01)


def test_total_stays_close_to_the_average():
    """前後半のつり合いが効くので、メンバー補正だけで合計が大きく動かない。"""
    average = average_laps(RACES)
    projected = project_laps(average, front_runners=8, field_size=16, cushion=average.cushion)
    opening = opening_delta(average, 8, 16)
    assert sum(projected) == pytest.approx(average.total + opening * (1 + CLOSING_TRADE_OFF), abs=0.05)


# --- 馬場差 -------------------------------------------------------------------


def test_today_only_uses_the_measured_slope():
    """当日3本以上だけなら、実測の回帰係数0.64をそのまま掛ける。"""
    bias = track_bias([-0.20, -0.10, -0.15], [])
    assert bias.today_delta == pytest.approx(-0.15)
    assert bias.seconds_per_furlong == pytest.approx(TODAY_SOLO_WEIGHT * -0.15, abs=0.001)
    assert (bias.today_races, bias.previous_races) == (3, 0)


def test_few_races_today_are_trusted_less():
    """1本・2本しかない日は重みを下げる（実測の回帰係数 0.50 / 0.60）。"""
    one = track_bias([-0.20], [])
    two = track_bias([-0.20, -0.20], [])
    many = track_bias([-0.20] * 4, [])
    assert one.seconds_per_furlong == pytest.approx(TODAY_SOLO_WEIGHTS[1] * -0.20, abs=0.001)
    assert two.seconds_per_furlong == pytest.approx(TODAY_SOLO_WEIGHTS[2] * -0.20, abs=0.001)
    assert abs(one.seconds_per_furlong) < abs(two.seconds_per_furlong) < abs(many.seconds_per_furlong)


def test_previous_day_only():
    bias = track_bias([], [-0.20, -0.10])
    assert bias.previous_delta == pytest.approx(-0.15)
    assert bias.seconds_per_furlong == pytest.approx(PREVIOUS_RULES[0][1] * -0.15, abs=0.001)


def test_a_week_old_meeting_counts_less():
    """前週の開催も効くが、前日より軽く見る（実測 0.60 → 0.46）。"""
    yesterday = track_bias([], [-0.20], previous_gap_days=1)
    last_week = track_bias([], [-0.20], previous_gap_days=7)
    assert abs(last_week.seconds_per_furlong) < abs(yesterday.seconds_per_furlong)
    assert last_week.seconds_per_furlong == pytest.approx(PREVIOUS_RULES[1][1] * -0.20, abs=0.001)
    assert last_week.previous_gap_days == 7

    # 3週間以上空いた開催は引き継がれないので使わない
    stale = track_bias([], [-0.20], previous_gap_days=22)
    assert stale.seconds_per_furlong == 0.0
    assert stale.previous_races == 0


def test_both_days_combine_as_measured():
    """両方あるときは 実測どおり 当日0.44＋前日0.30（前週なら 0.53＋0.24）。"""
    bias = track_bias([-0.20] * 3, [-0.10] * 2)
    solo, with_today, today_ratio = PREVIOUS_RULES[0][1:]
    expected = today_ratio * TODAY_SOLO_WEIGHT * -0.20 + with_today * -0.10
    assert bias.seconds_per_furlong == pytest.approx(expected, abs=0.001)
    assert bias.seconds_per_furlong == pytest.approx(0.44 * -0.20 + 0.30 * -0.10, abs=0.005)

    week = track_bias([-0.20] * 3, [-0.10] * 2, previous_gap_days=7)
    assert week.seconds_per_furlong == pytest.approx(0.53 * -0.20 + 0.24 * -0.10, abs=0.01)


def test_no_material_means_no_bias():
    bias = track_bias([], [])
    assert bias.seconds_per_furlong == 0.0
    assert not bias.has_material
    average = average_laps(RACES)
    assert project_laps(average, 4, 10, average.cushion, bias) == pytest.approx(
        project_laps(average, 4, 10, average.cushion), abs=0.001
    )


def test_fast_track_makes_every_segment_faster():
    average = average_laps(RACES)
    fast = project_laps(average, 4, 10, average.cushion, track_bias([-0.20] * 3, []))
    flat = project_laps(average, 4, 10, average.cushion)
    assert all(f < n for f, n in zip(fast, flat, strict=True))
    assert sum(flat) - sum(fast) == pytest.approx(abs(TODAY_SOLO_WEIGHT * -0.20) * len(flat), abs=0.05)


def test_bias_delta_removes_the_part_cushion_already_explains():
    """クッション値の差で説明できるぶんは馬場差に含めない（想定側と二重にしない）。"""
    # 条件平均より1.0硬い日に、ちょうどクッションぶんだけ速く走ったレース
    pace = 12.00 + CUSHION_SEC_PER_FURLONG
    assert bias_delta(pace, 12.00, cushion=10.4, baseline_cushion=9.4) == pytest.approx(0.0, abs=0.001)
    # クッション値が無ければ（ダート）、平均との差がそのまま馬場差になる
    assert bias_delta(11.90, 12.00) == pytest.approx(-0.10, abs=0.001)


def test_bias_from_races_skips_rows_without_a_baseline():
    rows = [
        {"pace": 11.90, "baseline_pace": 12.00, "cushion_value": None, "baseline_cushion": None},
        {"pace": 11.90, "baseline_pace": None},  # 比較対象が無い（初めての条件）
    ]
    bias = bias_from_races(rows, [])
    assert bias.today_races == 1
    assert bias.today_delta == pytest.approx(-0.10)


# --- 想定タイムの表記 ---------------------------------------------------------


def test_format_race_time():
    assert format_race_time(146.7) == "2:26.7"
    assert format_race_time(120.0) == "2:00.0"
    assert format_race_time(58.4) == "58.4"      # 60秒未満は分を付けない
    assert format_race_time(None) == "—"


def test_time_label_has_the_3f_split():
    """`2:23.9 (35.9-36.3)` の形。カッコの中は 前半3F-上がり3F。"""
    laps = [12.6, 11.3, 12.0, 12.1, 12.2, 12.0, 11.9, 11.8, 11.7, 11.9, 12.0, 12.4]
    assert three_furlong_split(laps) == (35.9, 36.3)
    assert time_label(laps) == "2:23.9 (35.9-36.3)"

    # 区間が6つに満たないレースは合計だけ
    assert three_furlong_split([12.0, 11.0]) == (None, None)
    assert time_label([12.0, 11.0]) == "23.0"
    assert time_label([]) == "—"


def test_time_label_reflects_the_corrections():
    """馬場差やクッションの補正は、そのまま想定タイムに効く。"""
    average = average_laps(RACES)
    flat = time_label(project_laps(average, 4, 10, average.cushion))
    fast = time_label(project_laps(average, 4, 10, average.cushion, track_bias([-0.20] * 3, [])))
    assert fast < flat     # 文字列だが同じ桁数なので、速いほうが小さい


# --- 馬場状態・含水率 ---------------------------------------------------------


def test_going_moves_the_projection_the_most():
    """馬場状態が想定タイムをいちばん大きく動かす（芝は渋るほど遅い）。"""
    average = average_laps(RACES)
    times = {
        going: sum(project_laps(average, 5, 14, None, None, "turf", going))
        for going in ("良", "稍重", "重", "不良")
    }
    assert times["良"] < times["稍重"] < times["重"] < times["不良"]
    # 2000m（10F）なら 良→重 で 2秒ほど遅くなる
    assert 1.5 < times["重"] - times["良"] < 2.5


def test_dirt_gets_faster_when_wet():
    """ダートは水を含むほど速くなる（芝と逆向き）。"""
    average = average_laps(RACES)
    good = sum(project_laps(average, 5, 14, None, None, "dirt", "良"))
    bad = sum(project_laps(average, 5, 14, None, None, "dirt", "不良"))
    assert bad < good
    # 含水率も同じ向き（ダートのみ）
    dry = sum(project_laps(average, 5, 14, None, None, "dirt", "良", moisture=2.0))
    wet = sum(project_laps(average, 5, 14, None, None, "dirt", "良", moisture=12.0))
    assert wet < dry
    # 芝の含水率は効かせない
    assert moisture_delta("turf", 18.0) == 0.0


def test_cushion_is_a_small_correction_now():
    """クッション値は馬場状態を入れたあとに残る分だけ（以前の-0.041は馬場状態の代理だった）。"""
    assert abs(CUSHION_SEC_PER_FURLONG) < 0.01
    average = average_laps(RACES)
    hard = sum(project_laps(average, 5, 14, 10.5, None, "turf", "良"))
    soft = sum(project_laps(average, 5, 14, 8.0, None, "turf", "良"))
    assert hard < soft
    assert soft - hard < 0.3          # 10F で0.3秒未満（馬場状態の1/5以下）


def test_bias_does_not_double_count_the_going():
    """馬場差は「馬場状態で説明できない残り」なので、重馬場でも0になる。"""
    # 重馬場で、ちょうど馬場状態ぶんだけ遅かったレース
    pace = 12.00 + going_delta("turf", "重")
    assert bias_delta(pace, 12.00, surface="turf", going="重") == pytest.approx(0.0, abs=0.001)
    # 馬場状態を渡さなければ、そのぶんがまるごと馬場差になる
    assert bias_delta(pace, 12.00) == pytest.approx(going_delta("turf", "重"), abs=0.001)
