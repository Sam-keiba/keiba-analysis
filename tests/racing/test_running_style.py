"""脚質の暫定判定。"""

import pytest

from keiba_analysis.racing import running_style as rs


@pytest.mark.parametrize(
    ("corner", "n_runners", "expected"),
    [
        ("1-1-1-1", 16, "逃げ"),      # 常に先頭 → 0.00
        ("2-2-2-2", 16, "逃げ"),      # (2-1)/15 = 0.07 → 0.10以下なので逃げ
        ("3-3-3-3", 16, "先行"),      # 0.13
        ("6-6-5-5", 16, "先行"),      # ちょうど0.30 → 境界は先行に入る
        ("8-8-7-6", 16, "差し"),      # 0.48
        ("14-14-12-10", 16, "追込"),  # 0.73
        ("16-16-16-16", 16, "追込"),  # 1.00
    ],
)
def test_classify_run(corner, n_runners, expected):
    assert rs.classify_run(corner, n_runners) == expected


def test_threshold_boundaries_are_inclusive():
    # 正規化 0.10 ちょうどは逃げ、0.30 ちょうどは先行、0.60 ちょうどは差し
    assert rs.classify_run_from_value(0.10) == "逃げ"
    assert rs.classify_run_from_value(0.1001) == "先行"
    assert rs.classify_run_from_value(0.30) == "先行"
    assert rs.classify_run_from_value(0.60) == "差し"
    assert rs.classify_run_from_value(0.601) == "追込"


def test_no_material_returns_none():
    assert rs.classify_run(None, 16) is None
    assert rs.classify_run("", 16) is None
    assert rs.classify_run("5-5", None) is None
    assert rs.classify_run("5-5", 1) is None       # 頭数1では正規化できない
    assert rs.classify_run("-", 16) is None        # 数字が無い（障害・中止など）


def test_summarize_uses_most_frequent_style():
    runs = [
        {"corner_passing": "1-1-1-1", "n_runners": 16},   # 逃げ
        {"corner_passing": "1-1-2-1", "n_runners": 16},   # 逃げ
        {"corner_passing": "10-10-9-8", "n_runners": 16},  # 追込
    ]
    style = rs.summarize(runs)
    assert style.style == "逃げ"
    assert style.n_samples == 3
    assert 0 < style.average_position < 1
    assert style.index == 0


def test_summarize_tie_prefers_more_forward_style():
    runs = [
        {"corner_passing": "1-1-1-1", "n_runners": 16},     # 逃げ
        {"corner_passing": "12-12-12-12", "n_runners": 16},  # 追込
    ]
    assert rs.summarize(runs).style == "逃げ"


def test_summarize_ignores_runs_without_corner_data():
    runs = [
        {"corner_passing": None, "n_runners": 16},
        {"corner_passing": "8-8-7-6", "n_runners": 16},
    ]
    style = rs.summarize(runs)
    assert style.n_samples == 1
    assert style.style == "差し"


def test_summarize_without_any_material():
    assert rs.summarize([]) is None
    assert rs.summarize([{"corner_passing": None, "n_runners": None}]) is None


def test_summarize_limits_to_recent_runs():
    runs = [{"corner_passing": "1-1-1-1", "n_runners": 16}] * 3 + [
        {"corner_passing": "14-14-14-14", "n_runners": 16}
    ] * 5
    assert rs.summarize(runs, limit=3).n_samples == 3
    assert rs.summarize(runs, limit=3).style == "逃げ"


def test_summarize_many_skips_horses_without_material():
    result = rs.summarize_many({
        "A": [{"corner_passing": "1-1-1-1", "n_runners": 16}],
        "B": [],
    })
    assert set(result) == {"A"}
