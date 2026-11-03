"""馬券の検証。組み合わせの作り方と、母数から外すレースの扱い。"""

import numpy as np
import pytest

from keiba_analysis.racing import bet_backtest as bb
from keiba_analysis.racing.condition_stats import Filters
from tests.racing.test_condition_stats import _pay, _race, _run


def test_tickets_win_and_place():
    assert bb.tickets("単勝", [(10, 5), (2, 1)]) == {"2", "10"}
    assert bb.tickets("複勝", [(1, 1)]) == {"1"}


def test_tickets_sort_numerically_not_as_text():
    assert bb.tickets("馬連", [(10, 5), (2, 1)]) == {"2-10"}
    assert bb.tickets("ワイド", [(10, 5), (2, 1)]) == {"2-10"}


def test_tickets_ordered_types_have_both_orders():
    assert bb.tickets("馬単", [(1, 1), (2, 2)]) == {"1-2", "2-1"}
    assert len(bb.tickets("三連単", [(1, 1), (2, 2), (3, 3)])) == 6
    assert bb.tickets("三連複", [(3, 3), (1, 1), (2, 2)]) == {"1-2-3"}


def test_tickets_too_few_runners_is_empty():
    assert bb.tickets("馬連", [(1, 1)]) == set()
    assert bb.tickets("三連複", [(1, 1), (2, 2)]) == set()


def test_tickets_frame_pairs():
    assert bb.tickets("枠連", [(1, 1), (2, 1)]) == {"1-1"}
    assert bb.tickets("枠連", [(1, 1), (5, 3)]) == {"1-3"}
    assert bb.tickets("枠連", [(1, 1), (2, 1), (5, 3)]) == {"1-1", "1-3"}


def test_unknown_bet_type(conn):
    with pytest.raises(ValueError):
        bb.backtest(conn, Filters(), "WIN5")


@pytest.fixture
def seeded(conn):
    """2024年: R1は1番人気が勝つ、R2は負ける。2025年: R3は同着。2022年: R0は払戻が無い時期。"""
    _race(conn, "R0", date_="2022-01-05")
    _run(conn, "R0", 1, finish=1, odds=9.0, pop=1)
    _race(conn, "R1", date_="2024-01-06")
    _run(conn, "R1", 1, finish=1, odds=2.0, pop=1)
    _run(conn, "R1", 2, finish=2, odds=5.0, pop=2)
    _run(conn, "R1", 3, finish=3, odds=9.0, pop=3)
    _pay(conn, "R1", "単勝", "1", 200)
    _pay(conn, "R1", "複勝", "1", 110)
    _pay(conn, "R1", "複勝", "2", 150)
    _pay(conn, "R1", "複勝", "3", 200)
    _pay(conn, "R1", "馬連", "1-2", 700)
    _race(conn, "R2", date_="2024-02-03")
    _run(conn, "R2", 1, finish=3, odds=2.0, pop=1)
    _run(conn, "R2", 2, status="中止", odds=5.0, pop=2)
    _run(conn, "R2", 3, finish=1, odds=9.0, pop=3)
    _pay(conn, "R2", "単勝", "3", 900)
    _pay(conn, "R2", "馬連", "3-4", 1000)
    _race(conn, "R3", date_="2025-03-01")
    _run(conn, "R3", 1, finish=1, odds=2.0, pop=1)
    _run(conn, "R3", 2, finish=1, odds=5.0, pop=2)
    _pay(conn, "R3", "単勝", "1", 150)
    _pay(conn, "R3", "単勝", "2", 300)
    conn.commit()
    return conn


def test_win_bet_on_favourites(seeded):
    result = bb.backtest(seeded, Filters(popularity_max=1), "単勝", n_boot=50)
    assert (result.races, result.points, result.hit_races) == (3, 3, 2)
    assert result.returned_yen == 200 + 150    # R0（2022年）は入らない。同着は払戻の値を使う
    assert result.roi == pytest.approx(350 / 300)
    assert result.hit_rate == pytest.approx(2 / 3)
    assert [(y.year, y.races, y.returned_yen) for y in result.years] == [("2024", 2, 200), ("2025", 1, 150)]
    assert (result.first_date, result.last_date) == ("2024-01-06", "2025-03-01")


def test_stopped_horse_is_a_losing_ticket(seeded):
    result = bb.backtest(seeded, Filters(popularity_min=2, popularity_max=2), "単勝", n_boot=50)
    # 2番人気は R1（負け）・R2（中止）・R3（同着で300円）。中止も買ったまま外れる
    assert (result.races, result.points, result.hit_races, result.returned_yen) == (3, 3, 1, 300)


def test_box_counts_points_per_race(seeded):
    result = bb.backtest(seeded, Filters(popularity_max=2), "馬連", n_boot=50)
    # R1・R2 は 1-2 の1点ずつ。R1だけ当たる。R3は馬連の払戻が無いので発売なし扱い
    assert (result.races, result.points, result.hit_races, result.returned_yen) == (2, 2, 1, 700)
    assert result.skipped_not_sold == 1


def test_place_pays_every_selected_horse(seeded):
    result = bb.backtest(seeded, Filters(start="2024-01-01", end="2024-01-31"), "複勝", n_boot=50)
    assert (result.races, result.points, result.returned_yen) == (1, 3, 110 + 150 + 200)


def test_too_few_runners_and_point_limit_are_counted(seeded):
    few = bb.backtest(seeded, Filters(popularity_max=1, end="2024-01-31"), "馬連", n_boot=50)
    assert (few.races, few.skipped_too_few) == (0, 1)
    assert few.roi is None and few.hit_rate is None and few.interval is None
    over = bb.backtest(seeded, Filters(end="2024-01-31"), "馬単", max_points=5, n_boot=50, )
    assert over.skipped_not_sold == 1      # 馬単の払戻を入れていないレース
    limited = bb.backtest(seeded, Filters(end="2024-01-31"), "馬連", max_points=2, n_boot=50)
    assert (limited.races, limited.skipped_over_limit) == (0, 1)   # 3頭BOXは3点


def test_never_reads_before_payout_start(seeded):
    result = bb.backtest(seeded, Filters(end="2022-12-31"), "単勝", n_boot=50)
    assert result.races == 0 and result.skipped_not_sold == 0


def test_no_match(seeded):
    result = bb.backtest(seeded, Filters(grades=("GI",)), "単勝", n_boot=50)
    assert result.races == 0 and result.years == ()


def test_bootstrap_is_repeatable_and_contains_the_estimate():
    points = np.ones(200)
    returned = np.where(np.arange(200) % 4 == 0, 400.0, 0.0)
    first = bb.bootstrap_interval(points, returned, seed=1)
    assert first == bb.bootstrap_interval(points, returned, seed=1)
    assert first[0] < 1.0 < first[1]
    assert bb.bootstrap_interval(np.ones(1), np.ones(1)) is None
