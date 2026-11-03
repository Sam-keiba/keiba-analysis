"""条件集計。いちばん大事なのは出走の数え方と、回収率の分母。"""

import pytest

from keiba_analysis.racing import condition_stats as cs
from keiba_analysis.racing.condition_stats import Filters, Ratio
from keiba_analysis.racing.trainer_stats import record


def _race(conn, race_id, *, date_="2025-04-05", venue="05", surface="turf", distance=1600, klass="1勝クラス",
          grade=None, runners=4, going="良"):
    conn.execute("INSERT OR IGNORE INTO venues (venue_code, venue_name) VALUES (?, ?)", (venue, f"場{venue}"))
    conn.execute(
        "INSERT INTO races (race_id, race_date, venue_code, kaiji, nichime, race_no, grade, surface, distance_m,"
        " class_condition, n_runners, going_turf, going_dirt, fetched_at, updated_at)"
        " VALUES (?, ?, ?, 1, 1, 1, ?, ?, ?, ?, ?, ?, ?, '', '')",
        (race_id, date_, venue, grade, surface, distance, klass, runners,
         going if surface != "dirt" else None, going if surface == "dirt" else None))


def _run(conn, race_id, umaban, *, finish=None, status=None, odds=None, pop=None, waku=None, horse=None,
         sex="牡", age=3, jockey=None, trainer=None):
    horse = horse or f"{race_id}H{umaban}"
    conn.execute("INSERT OR IGNORE INTO horses (horse_id, horse_name, sex, updated_at) VALUES (?, ?, ?, '')",
                 (horse, horse, sex))
    if jockey:
        conn.execute("INSERT OR IGNORE INTO jockeys (jockey_id, jockey_name, updated_at) VALUES (?, ?, '')",
                     (jockey, f"騎手{jockey}"))
    if trainer:
        conn.execute("INSERT OR IGNORE INTO trainers (trainer_id, trainer_name, updated_at) VALUES (?, ?, '')",
                     (trainer, f"師{trainer}"))
    conn.execute("INSERT INTO entries (race_id, umaban, waku, horse_id, sex, age, jockey_id, trainer_id)"
                 " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (race_id, umaban, waku or umaban, horse, sex, age, jockey, trainer))
    conn.execute("INSERT INTO results (race_id, umaban, horse_id, finish_position, finish_status, win_odds, popularity)"
                 " VALUES (?, ?, ?, ?, ?, ?, ?)", (race_id, umaban, horse, finish, status, odds, pop))


def _pay(conn, race_id, bet_type, combination, yen):
    conn.execute("INSERT INTO payouts (race_id, bet_type, combination, payout_yen) VALUES (?, ?, ?, ?)",
                 (race_id, bet_type, combination, yen))


@pytest.fixture
def seeded(conn):
    """R1: 2025年（払戻あり）。4頭＋取消・除外。R2: 2022年（払戻なし）。"""
    _race(conn, "R1")
    _run(conn, "R1", 1, finish=1, odds=3.0, pop=1, jockey="J1")
    _run(conn, "R1", 2, finish=2, odds=5.0, pop=2, jockey="J2")
    _run(conn, "R1", 3, finish=3, odds=10.0, pop=3, jockey="J1")
    _run(conn, "R1", 4, status="中止", odds=20.0, pop=4, jockey="J2")
    _run(conn, "R1", 5, status="取消", jockey="J1")
    _run(conn, "R1", 6, status="除外", jockey="J2")
    _pay(conn, "R1", "複勝", "1", 120)
    _pay(conn, "R1", "複勝", "2", 150)
    _pay(conn, "R1", "複勝", "3", 300)
    _race(conn, "R2", date_="2022-04-05", surface="dirt", klass="500万下 牝")
    _run(conn, "R2", 1, finish=1, odds=2.0, pop=1, jockey="J1", sex="牝")
    _run(conn, "R2", 2, finish=2, pop=None, jockey="J2", sex="牝")   # オッズなし
    conn.commit()
    return conn


def test_total_counts_stopped_runs_but_not_scratched(seeded):
    stat = cs.total(seeded, Filters())
    assert (stat.starts, stat.wins, stat.top2, stat.top3) == (6, 2, 4, 5)
    assert stat.win_rate == pytest.approx(2 / 6)


def test_run_without_status_or_position_counts_as_start(conn):
    _race(conn, "R9")
    _run(conn, "R9", 1, odds=3.0)
    assert cs.total(conn, Filters()).starts == 1


def test_win_roi_excludes_runs_without_odds_from_denominator(seeded):
    roi = cs.total(seeded, Filters()).win_roi
    assert roi.bets == 5
    assert roi.value == pytest.approx((3.0 + 2.0) / 5)


def test_place_roi_uses_only_races_with_payouts(seeded):
    roi = cs.total(seeded, Filters()).place_roi
    assert roi.bets == 4        # R1の出走のみ（中止を含む）。R2は払戻なし
    assert roi.value == pytest.approx((1.2 + 1.5 + 3.0) / 4)


def test_place_roi_missing_when_period_has_no_payouts(seeded):
    assert cs.total(seeded, Filters(end="2022-12-31")).place_roi.value is None


def test_matches_trainer_stats_record(seeded):
    rows = [dict(r) for r in seeded.execute("SELECT * FROM results")]
    expected = record("全", rows)
    stat = cs.total(seeded, Filters())
    assert (stat.starts, stat.wins, stat.top2, stat.top3) == (expected.starts, expected.wins, expected.top2, expected.top3)
    assert stat.win_roi.value == pytest.approx(expected.roi)


def test_axis_year_is_sorted_and_two_axes_cross(seeded):
    rows = cs.aggregate(seeded, Filters(), ("year",))
    assert [(r.label, r.starts) for r in rows] == [("2022", 2), ("2025", 4)]
    crossed = cs.aggregate(seeded, Filters(), ("year", "jockey"))
    assert [(r.label, r.label2, r.starts) for r in crossed] == [
        ("2022", "騎手J1", 1), ("2022", "騎手J2", 1), ("2025", "騎手J1", 2), ("2025", "騎手J2", 2)]


def test_legacy_class_is_grouped_with_modern_name(seeded):
    rows = cs.aggregate(seeded, Filters(), ("class",))
    assert [(r.label, r.starts) for r in rows] == [("1勝クラス", 6)]
    assert cs.total(seeded, Filters(classes=("1勝クラス",))).starts == 6


def test_going_reads_the_column_of_the_surface(conn):
    _race(conn, "T", surface="turf", going="重")
    _run(conn, "T", 1, finish=1)
    _race(conn, "D", surface="dirt", going="不良")
    _run(conn, "D", 1, finish=1)
    assert [(r.label, r.starts) for r in cs.aggregate(conn, Filters(), ("going",))] == [("重", 1), ("不良", 1)]
    assert cs.total(conn, Filters(goings=("不良",))).starts == 1


def test_null_axis_value_is_unknown(seeded):
    labels = [r.label for r in cs.aggregate(seeded, Filters(), ("popularity",))]
    assert labels[-1] == cs.UNKNOWN


def test_many_valued_axis_sorted_by_starts(conn):
    _race(conn, "R1")
    _run(conn, "R1", 1, jockey="J1")
    _run(conn, "R1", 2, jockey="J2")
    _run(conn, "R1", 3, jockey="J2")
    assert [r.label for r in cs.aggregate(conn, Filters(), ("jockey",))] == ["騎手J2", "騎手J1"]


def test_filters_narrow(seeded):
    assert cs.total(seeded, Filters(start="2023-01-01")).starts == 4
    assert cs.total(seeded, Filters(surfaces=("dirt",))).starts == 2
    assert cs.total(seeded, Filters(popularity_min=1, popularity_max=2)).starts == 3
    assert cs.total(seeded, Filters(odds_min=5.0, odds_max=10.0)).starts == 2
    assert cs.total(seeded, Filters(sexes=("牝",))).starts == 2
    assert cs.total(seeded, Filters(jockey_ids=("J1",))).starts == 3
    assert cs.total(seeded, Filters(wakus=(1, 2), umaban_min=2)).starts == 2
    assert cs.total(seeded, Filters(grades=(cs.FLAT_RACE,))).starts == 6
    assert cs.total(seeded, Filters(grades=("GI",))) is None


def test_filter_values_are_not_executed_as_sql(seeded):
    attack = "x'); DROP TABLE races; --"
    filters = Filters(jockey_ids=(attack,), venues=(attack,), classes=(attack,), start=attack)
    assert cs.total(seeded, filters) is None
    assert seeded.execute("SELECT COUNT(*) FROM races").fetchone()[0] == 2


def test_unknown_axis_is_rejected(seeded):
    with pytest.raises(KeyError):
        cs.aggregate(seeded, Filters(), ("1; DROP TABLE races",))
    with pytest.raises(ValueError):
        cs.aggregate(seeded, Filters(), ("year", "waku", "sex"))


def test_final_odds_flags():
    assert Filters(popularity_max=3).uses_final_odds
    assert Filters(odds_min=1.0).uses_final_odds
    assert not Filters(wakus=(1,)).uses_final_odds
    assert cs.axes_use_final_odds(("year", "popularity"))
    assert not cs.axes_use_final_odds(("year", "waku"))


def test_ratio_interval_by_hand():
    # 2レース。買い目 x=(1,1)、払戻 y=(0,2) → R=1、残差の2乗和=2、n/(n-1)=2 → 半幅=1.96*sqrt(4)/2
    ratio = Ratio(bets=2, returned=2.0, races=2, sum_xx=2.0, sum_yy=4.0, sum_xy=2.0)
    low, high = ratio.interval
    assert low == 0.0     # 1 - 1.96 は0で止める
    assert high == pytest.approx(1 + 1.96)
    assert Ratio(bets=1, returned=1.0, races=1).interval is None


def test_matching_runs_newest_first_and_limited(seeded):
    runs = cs.matching_runs(seeded, Filters(), limit=2)
    assert [r["race_date"] for r in runs] == ["2025-04-05", "2025-04-05"]
    assert runs[0]["umaban"] == 1 and runs[0]["jockey_name"] == "騎手J1"


def test_with_start_at_least():
    assert Filters().with_start_at_least("2023-01-01").start == "2023-01-01"
    assert Filters(start="2024-01-01").with_start_at_least("2023-01-01").start == "2024-01-01"
    assert Filters(start="2020-01-01", wakus=(1,)).with_start_at_least("2023-01-01").wakus == (1,)


def test_jockey_choices_most_starts_first(conn):
    _race(conn, "R1")
    _run(conn, "R1", 1, jockey="J1")
    _run(conn, "R1", 2, jockey="J2")
    _run(conn, "R1", 3, jockey="J2")
    assert cs.jockey_choices(conn) == [("J2", "騎手J2（2走）"), ("J1", "騎手J1（1走）")]


def test_trainer_choices(conn):
    _race(conn, "R1")
    _run(conn, "R1", 1, trainer="T1")
    assert cs.trainer_choices(conn) == [("T1", "師T1（1走）")]
