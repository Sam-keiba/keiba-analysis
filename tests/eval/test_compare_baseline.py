"""STEP2 の部品（人気ベース・温度・条件付きロジット・同点の切り方）を合成データで確かめる。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eval import compare_baseline as cb
from eval import evaluate


def _synthetic(n_races: int, seed: int, utility) -> pd.DataFrame:
    """各レース10頭。効用 utility(x) のソフトマックスで勝ち馬を1頭引く。"""
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(n_races):
        x1, x2 = rng.normal(size=10), rng.normal(size=10)
        u = utility(x1, x2)
        p = np.exp(u - u.max())
        p /= p.sum()
        winner = rng.choice(10, p=p)
        for i in range(10):
            rows.append((f"R{r}", f"H{i}", x1[i], x2[i], 1 if i == winner else 2 + i))
    return pd.DataFrame(rows, columns=["race_id", "horse_id", "x1", "x2", "finish"])


def test_market_prob_sums_to_one():
    df = pd.DataFrame({"race_id": ["A", "A", "B", "B", "B"], "odds": [2.0, 4.0, 3.0, 3.0, 6.0]})
    p = cb.market_prob(df)
    assert p.groupby(df["race_id"]).sum().tolist() == pytest.approx([1.0, 1.0])
    assert p.iloc[0] == pytest.approx(2 / 3)


def test_fit_temperature_recovers_known_value():
    df = _synthetic(3000, seed=1, utility=lambda x1, _: x1 / 0.7).rename(columns={"x1": "margin"})
    assert cb.fit_temperature(df) == pytest.approx(0.7, rel=0.1)


def test_clogit_recovers_coefficients():
    df = _synthetic(4000, seed=2, utility=lambda x1, x2: 1.2 * x1 + 0.5 * x2)
    model = cb.fit_clogit(df, ["x1", "x2"])
    assert model["beta"] == pytest.approx([1.2, 0.5], abs=0.1)
    assert (model["se"] > 0).all()
    # 効かない特徴量の係数は0の近くに出る
    noise = cb.fit_clogit(df.assign(z=np.random.default_rng(3).normal(size=len(df))), ["x1", "z"])
    assert abs(noise["beta"][1]) < 3 * noise["se"][1]


def test_top_picks_tiebreak_column():
    tie = pd.DataFrame({"race_id": ["R", "R"], "horse_id": ["x", "y"], "p_win": [0.5, 0.5],
                        "finish": [2, 1], "odds": [5.0, 3.0], "tb": [0.1, 0.9]})
    assert evaluate.top_picks(tie)["horse_id"].tolist() == ["y"]          # 既定はオッズで切る
    assert evaluate.top_picks(tie, "tb")["horse_id"].tolist() == ["x"]    # 乱数の列で切る


def test_paired_diff_is_reproducible_and_signed():
    a = pd.Series([1.0, 2.0, 3.0], index=["R1", "R2", "R3"])
    b = pd.Series([0.5, 1.5, 2.5], index=["R1", "R2", "R3"])
    first = evaluate.paired_diff(a, b, 300, seed=4)
    assert first == evaluate.paired_diff(a, b, 300, seed=4)
    assert first["diff"] == pytest.approx(0.5) and first["ci_low"] == pytest.approx(0.5)


def test_class_group():
    assert cb.class_group("未勝利", None) == "新馬・未勝利"
    assert cb.class_group("2勝クラス", None) == "条件戦"
    assert cb.class_group("オープン", "L") == "重賞（L含む）"
    assert cb.class_group("オープン", None) == "オープン（重賞以外）"
