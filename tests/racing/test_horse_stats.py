"""同一馬場種別の全成績の集計（horse_stats.py）。"""

import pytest

from keiba_analysis.racing import horse_stats
from keiba_analysis.racing.horse_stats import (
    CUSHION_LABELS,
    GOING_LABELS,
    MIN_SAMPLE,
    PACE_LABELS,
    summarize_hardness_going,
    summarize_pace,
    summarize_style,
    total_starts,
)


def run(finish=1, corner="3-3-3-3", n_runners=16, cushion=9.0, first_3f=36.0, last_3f=35.0,
        going="良", **kwargs):
    base = {
        "finish_position": finish, "corner_passing": corner, "n_runners": n_runners,
        "cushion_value": cushion, "race_first_3f": first_3f, "race_last_3f": last_3f,
        "going": going,
    }
    return {**base, **kwargs}


# --- ペース別 -----------------------------------------------------------------


def test_pace_buckets_are_always_in_order():
    buckets = summarize_pace([])
    assert [b.label for b in buckets] == list(PACE_LABELS)   # 走っていない区分も並べる
    assert all(b.starts == 0 and b.average_finish is None for b in buckets)


def test_pace_rate_and_average():
    """前半が速い（後半-前半が1.0秒以上）ならハイ、逆ならスロー。"""
    runs = [
        run(finish=1, first_3f=34.5, last_3f=36.5),   # ハイ
        run(finish=5, first_3f=34.5, last_3f=36.5),   # ハイ
        run(finish=3, first_3f=36.5, last_3f=34.5),   # スロー
        run(finish=8, first_3f=35.5, last_3f=35.6),   # ミドル
    ]
    high, middle, slow = summarize_pace(runs)
    assert (high.starts, high.wins, high.top3) == (2, 1, 1)
    assert high.rate == pytest.approx(0.5)
    assert high.average_finish == pytest.approx(3.0)
    assert (middle.starts, middle.top3) == (1, 0)
    assert (slow.starts, slow.top3) == (1, 1)


def test_runs_without_laps_are_not_counted():
    """ラップが無い走（障害など）はペース別の母数に入らない。"""
    buckets = summarize_pace([run(first_3f=None, last_3f=None)])
    assert sum(b.starts for b in buckets) == 0


# --- クッション値 × 馬場状態 ----------------------------------------------------


def test_cushion_bucket_boundaries():
    """区切りは 8.5 / 10.0。境界の値は上の区分に入る。

    馬場状態とのマス目にするので、細かく割ると1頭ぶんではどのマスも埋まらない。
    """
    assert horse_stats.hardness_label(8.4) == "〜8.5"
    assert horse_stats.hardness_label(8.5) == "8.5〜10.0"
    assert horse_stats.hardness_label(9.9) == "8.5〜10.0"
    assert horse_stats.hardness_label(10.0) == "10.0〜"
    assert horse_stats.hardness_label(None) is None


def test_the_grid_always_has_every_cell():
    """走っていないマスも残す（走っていないことが分かるように）。"""
    grid = summarize_hardness_going([])
    assert len(grid.cells) == len(GOING_LABELS) * len(CUSHION_LABELS) == 12
    assert all(cell.starts == 0 for cell in grid.cells.values())
    assert grid.total.starts == 0


def test_each_cell_holds_the_record_of_that_combination():
    runs = [
        run(finish=1, cushion=9.0, going="良"),
        run(finish=9, cushion=9.2, going="良"),
        run(finish=2, cushion=8.0, going="重"),
    ]
    grid = summarize_hardness_going(runs)
    good = grid.cells[("良", "8.5〜10.0")]
    assert (good.starts, good.wins, good.top3) == (2, 1, 1)
    assert good.rate == pytest.approx(0.5)
    assert good.average_finish == pytest.approx(5.0)
    assert grid.cells[("重", "〜8.5")].starts == 1
    assert grid.cells[("不良", "10.0〜")].starts == 0


def test_the_totals_are_the_sum_of_the_cells():
    """行・列の計がマスの数と食い違うと、表として読めなくなる。"""
    runs = [
        run(finish=1, cushion=8.0, going="良"),
        run(finish=4, cushion=9.0, going="良"),
        run(finish=2, cushion=9.0, going="重"),
        run(finish=3, cushion=10.5, going="重"),
    ]
    grid = summarize_hardness_going(runs)
    for going in GOING_LABELS:
        row = [grid.cells[(going, c)] for c in CUSHION_LABELS]
        assert grid.by_going[going].starts == sum(c.starts for c in row), going
        assert grid.by_going[going].top3 == sum(c.top3 for c in row), going
    for cushion in CUSHION_LABELS:
        column = [grid.cells[(g, cushion)] for g in GOING_LABELS]
        assert grid.by_hardness[cushion].starts == sum(c.starts for c in column), cushion
    assert grid.total.starts == 4 and grid.total.top3 == 3
    assert grid.by_going["良"].starts == 2 and grid.by_going["重"].top3 == 2


def test_runs_without_a_cushion_or_a_going_are_skipped():
    """ダートや未発表の日はクッション値が無いので集計しない。"""
    runs = [run(cushion=None), run(going=None), run(going="やや重")]   # 最後は想定外の表記
    grid = summarize_hardness_going(runs)
    assert grid.total.starts == 0
    assert all(cell.starts == 0 for cell in grid.cells.values())


# --- 脚質 ---------------------------------------------------------------------


def test_style_shares():
    runs = [
        run(corner="1-1-1-1", n_runners=16),          # 逃げ
        run(corner="14-14-13-12", n_runners=16),      # 追込
        run(corner="13-13-13-14", n_runners=16),      # 追込
    ]
    buckets = summarize_style(runs)
    shares = dict(horse_stats.style_shares(buckets))
    assert shares["追込"] == pytest.approx(2 / 3)
    assert shares["逃げ"] == pytest.approx(1 / 3)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_runs_without_corner_positions_are_skipped():
    assert horse_stats.style_shares(summarize_style([run(corner=None)])) == []


# --- 母数の扱い ---------------------------------------------------------------


def test_scratched_runs_are_not_counted():
    """着順が無い走（取消・中止）は母数に入れない。"""
    runs = [run(finish=None), run(finish=2)]
    assert total_starts(runs) == 1
    assert sum(b.starts for b in summarize_pace(runs)) == 1


def test_enough_flag_marks_small_samples():
    few = summarize_pace([run(first_3f=34.5, last_3f=36.5)])[0]
    assert few.starts == 1 and not few.enough
    enough = summarize_pace([run(first_3f=34.5, last_3f=36.5)] * MIN_SAMPLE)[0]
    assert enough.enough


# --- ダートは含水率で見る -----------------------------------------------------


def dirt_run(moisture=5.0, **kwargs):
    """ダートの1走（横軸は含水率。クッション値は芝でしか発表されない）。"""
    return run(cushion=None, dirt_moisture_goal=moisture, **kwargs)


@pytest.mark.parametrize(
    ("moisture", "label"),
    [(0.2, "〜4%"), (3.9, "〜4%"), (4.0, "4〜8%"), (7.9, "4〜8%"),
     (8.0, "8%〜"), (20.6, "8%〜")],
)
def test_the_dirt_moisture_falls_into_three_bands(moisture, label):
    """境目はその値を含む上の区分に入れる（クッション値と同じ考え方）。"""
    assert horse_stats.hardness_label(moisture, "dirt") == label


def test_the_bands_are_different_for_turf_and_dirt():
    assert horse_stats.hardness_labels("turf") == CUSHION_LABELS
    assert horse_stats.hardness_labels("dirt") == horse_stats.DIRT_MOISTURE_LABELS
    assert horse_stats.hardness_label(None, "dirt") is None


def test_dirt_reads_the_moisture_and_not_the_cushion():
    """ダートの走にクッション値が紛れていても、そちらは見ない。"""
    runs = [dirt_run(moisture=2.0, going="良", finish=1, cushion_value=9.0),
            dirt_run(moisture=9.0, going="重", finish=5)]
    grid = summarize_hardness_going(runs, "dirt")
    assert grid.surface == "dirt"
    assert grid.cells[("良", "〜4%")].starts == 1
    assert grid.cells[("重", "8%〜")].starts == 1
    assert grid.total.starts == 2
    assert grid.by_hardness["〜4%"].top3 == 1


def test_a_dirt_run_without_a_moisture_is_left_out():
    runs = [dirt_run(moisture=None), dirt_run(moisture=5.0)]
    grid = summarize_hardness_going(runs, "dirt")
    assert grid.total.starts == 1


def test_turf_is_unchanged_by_the_dirt_support():
    """芝はこれまでどおりクッション値で分ける。"""
    grid = summarize_hardness_going([run(cushion=9.0, going="良")], "turf")
    assert grid.cells[("良", "8.5〜10.0")].starts == 1
    assert set(grid.by_hardness) == set(CUSHION_LABELS)
