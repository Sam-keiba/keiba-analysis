"""評価指標を、手で計算できる小さなダミーで確かめる。"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from eval import evaluate


@pytest.fixture
def df():
    # R1: 予測1位 a が1着（単勝2.0）。R2: 予測1位 d は3着、勝ったのは e（単勝3.0）
    return pd.DataFrame([
        ("R1", "a", 0.5, 1, 2.0, "2025-01-05"),
        ("R1", "b", 0.3, 2, 4.0, "2025-01-05"),
        ("R1", "c", 0.2, 3, 8.0, "2025-01-05"),
        ("R2", "d", 0.6, 3, 1.5, "2026-02-01"),
        ("R2", "e", 0.4, 1, 3.0, "2026-02-01"),
    ], columns=["race_id", "horse_id", "p_win", "finish", "odds", "race_date"])


def test_hit_and_place_rate(df):
    assert evaluate.hit_rate(df) == 0.5
    assert evaluate.place_rate(df) == 1.0


def test_logloss_and_brier(df):
    assert evaluate.logloss(df) == pytest.approx((-math.log(0.5) - math.log(0.4)) / 2)
    # R1: 0.25 + 0.09 + 0.04 = 0.38 / R2: 0.36 + 0.36 = 0.72
    assert evaluate.brier(df) == pytest.approx((0.38 + 0.72) / 2)


def test_probabilities_are_normalized_within_race(df):
    scaled = df.assign(p_win=df["p_win"] * df["race_id"].map({"R1": 3.0, "R2": 0.5}))
    assert evaluate.logloss(scaled) == pytest.approx(evaluate.logloss(df))
    assert evaluate.brier(scaled) == pytest.approx(evaluate.brier(df))


def test_dead_heat_splits_the_win():
    heat = pd.DataFrame([("R", "x", 0.5, 1, 2.0), ("R", "y", 0.5, 1, 2.0)],
                        columns=["race_id", "horse_id", "p_win", "finish", "odds"])
    assert evaluate.logloss(heat) == pytest.approx(-math.log(0.5))
    assert evaluate.brier(heat) == pytest.approx(0.0)


def test_roi_top(df):
    result = evaluate.roi_top(df, n_boot=200)
    assert result["roi"] == pytest.approx(1.0)      # 200円買って a の 200円
    assert result["bets"] == 2
    assert result["ci_low"] <= result["roi"] <= result["ci_high"]


def test_roi_ev_threshold(df):
    # p×odds: a 1.0（超えない）, b 1.2, c 1.6, d 0.9, e 1.2 → b・c・e を買い、e の300円
    ev = evaluate.roi_ev(df, 1.0, n_boot=200)
    assert ev["bets"] == 3 and ev["roi"] == pytest.approx(1.0)
    ev = evaluate.roi_ev(df, 1.3, n_boot=200)   # c だけ（3着）
    assert ev["bets"] == 1 and ev["roi"] == 0.0


def test_top_pick_tie_breaks_by_odds():
    tie = pd.DataFrame([("R", "x", 0.5, 2, 5.0), ("R", "y", 0.5, 1, 3.0)],
                       columns=["race_id", "horse_id", "p_win", "finish", "odds"])
    assert evaluate.top_picks(tie)["horse_id"].tolist() == ["y"]


def test_calibration_table(df):
    table = evaluate.calibration_table(df).set_index("bin")
    assert table["n"].sum() == 5
    row = table.loc["(0.4, 0.6]"]                # a（1着）と d（3着）
    assert row["n"] == 2 and row["win_rate"] == 0.5 and row["mean_pred"] == pytest.approx(0.55)


def test_bootstrap_is_reproducible(df):
    per_race = evaluate._payouts_top(df)
    assert evaluate.bootstrap_roi(per_race, 500, seed=1) == evaluate.bootstrap_roi(per_race, 500, seed=1)


def test_fixed_split_is_by_date(df):
    train, test = evaluate.split_fixed(df)
    assert set(train["race_id"]) == {"R1"} and set(test["race_id"]) == {"R2"}


def test_walk_forward_splits_are_ordered_and_disjoint():
    dates = pd.Series(["2023-01-05", "2026-01-10", "2026-05-03", "2026-10-12"])
    splits = list(evaluate.walk_forward_splits(dates))
    assert [test for _, test in splits] == [
        ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"),
        ("2026-07-01", "2026-09-30"), ("2026-10-01", "2026-12-31"),
    ]
    for (train_start, train_end), (test_start, _) in splits:
        assert train_start == "2023-01-01" and train_end < test_start


def test_walk_forward_runs_fit_predict(df):
    seen = []

    def fit_predict(train, test):
        seen.append((train["race_date"].max(), test["race_date"].min()))
        return test["p_win"]

    table = evaluate.walk_forward(df, fit_predict, n_boot=50)
    assert len(table) == 1 and table.loc[0, "hit_rate"] == 0.0     # R2 は予測1位 d が3着
    assert all(train_max < test_min for train_max, test_min in seen)


def test_rank_correlation_sign():
    perfect = pd.DataFrame({"race_id": ["R"] * 3, "score": [3.0, 2.0, 1.0], "finish": [1, 2, 3]})
    assert evaluate.rank_correlation(perfect, "score")["per_race"] == pytest.approx(1.0)


def test_rank_correlation_counts_undecidable_races():
    # R2 は全頭同じスコア（新馬戦のように見分けられない）
    two = pd.DataFrame({"race_id": ["R1"] * 3 + ["R2"] * 3,
                        "score": [3.0, 2.0, 1.0, 0.0, 0.0, 0.0], "finish": [1, 2, 3, 3, 2, 1]})
    corr = evaluate.rank_correlation(two, "score")
    assert corr["per_race"] == pytest.approx(1.0)          # R2 を除く
    assert corr["per_race_all"] == pytest.approx(0.5)      # R2 を0で数える
    assert corr["per_race_legacy"] == pytest.approx(0.0)   # R2 は馬番順＝着順の逆で −1
