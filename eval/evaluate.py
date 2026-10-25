"""予想の答え合わせの指標・データ分割・ブートストラップ。

入力は1頭1行の DataFrame で、列は次のとおり:
    race_id, horse_id, p_win（予測勝率）, finish（着順。中止などは NaN）, odds（確定単勝オッズ）
分割には race_date（'YYYY-MM-DD'）も使う。

**分割は日付で切る。ランダム分割はしない**（未来のレースで学習して過去を当てることになるため）。
回収率はレース数が少ないと大きくぶれるので、レース単位のブートストラップで95%区間を付ける。
乱数は seed 引数で固定する。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import numpy as np
import pandas as pd

TRAIN_START, TRAIN_END = "2023-01-01", "2025-12-31"
TEST_START = "2026-01-01"
DEFAULT_BINS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.60, 1.0)
EPS = 1e-15


# --- データ分割 -------------------------------------------------------------------

def split_fixed(
    df: pd.DataFrame, train=(TRAIN_START, TRAIN_END), test_start: str = TEST_START,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """学習＝2023〜2025年、評価＝2026年以降。"""
    dates = df["race_date"]
    train_df = df[(dates >= train[0]) & (dates <= train[1])]
    test_df = df[dates >= test_start]
    return train_df, test_df


def walk_forward_splits(
    dates: pd.Series, first_test: str = TEST_START, train_start: str = TRAIN_START,
) -> Iterator[tuple[tuple[str, str], tuple[str, str]]]:
    """四半期ごとに学習期間を延ばし、直後の四半期を評価する。

    返すのは ((学習の開始, 学習の終わり), (評価の開始, 評価の終わり))。どれも両端を含む日付。
    評価期間にデータが1件も無い四半期で止まる。
    """
    last = pd.Timestamp(dates.max())
    start = pd.Timestamp(first_test)
    while start <= last:
        end = start + pd.offsets.QuarterEnd(0)
        train_end = start - pd.Timedelta(days=1)
        yield ((train_start, train_end.strftime("%Y-%m-%d")),
               (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        start = end + pd.Timedelta(days=1)


def walk_forward(
    df: pd.DataFrame,
    fit_predict: Callable[[pd.DataFrame, pd.DataFrame], pd.Series],
    first_test: str = TEST_START,
    **summary_kwargs,
) -> pd.DataFrame:
    """ウォークフォワードで回し、四半期ごとの指標を表にする。

    `fit_predict(train_df, test_df)` は test_df と同じ index の予測勝率（Series）を返すこと。
    """
    rows = []
    for (tr_s, tr_e), (te_s, te_e) in walk_forward_splits(df["race_date"], first_test):
        train_df = df[(df["race_date"] >= tr_s) & (df["race_date"] <= tr_e)]
        test_df = df[(df["race_date"] >= te_s) & (df["race_date"] <= te_e)].copy()
        if test_df.empty:
            continue
        test_df["p_win"] = fit_predict(train_df, test_df)
        rows.append({"test_start": te_s, "test_end": te_e, "train_end": tr_e,
                     **summary(test_df, **summary_kwargs)})
    return pd.DataFrame(rows)


# --- 前処理 -----------------------------------------------------------------------

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """レースの中で p_win の合計を1にし、勝ち（同着は1/k）の列 y を足す。"""
    out = df.copy()
    total = out.groupby("race_id")["p_win"].transform("sum")
    out["p"] = np.where(total > 0, out["p_win"] / total.where(total > 0, 1), 0.0)
    won = (out["finish"] == 1).astype(float)
    winners = won.groupby(out["race_id"]).transform("sum")
    out["y"] = np.where(winners > 0, won / winners.where(winners > 0, 1), 0.0)
    return out


def top_picks(df: pd.DataFrame) -> pd.DataFrame:
    """各レースの予測1位。同点はオッズの低い馬、次に horse_id（毎回同じ結果にするため）。"""
    ordered = df.assign(_odds=df["odds"].fillna(np.inf)).sort_values(
        ["race_id", "p_win", "_odds", "horse_id"], ascending=[True, False, True, True],
    )
    return ordered.groupby("race_id", sort=False).head(1).drop(columns="_odds")


# --- 指標 -------------------------------------------------------------------------

def hit_rate(df: pd.DataFrame) -> float:
    """予測1位が1着だった割合。"""
    return float((top_picks(df)["finish"] == 1).mean())


def place_rate(df: pd.DataFrame) -> float:
    """予測1位が3着以内だった割合。"""
    return float((top_picks(df)["finish"] <= 3).mean())


def _races_with_winner(df: pd.DataFrame) -> pd.DataFrame:
    norm = normalize(df)
    has_winner = norm.groupby("race_id")["y"].transform("sum") > 0
    return norm[has_winner]


def logloss(df: pd.DataFrame) -> float:
    """1着馬の正規化確率の −log の平均（同着は 1/k ずつ）。勝ち馬のいないレースは除く。"""
    norm = _races_with_winner(df)
    per_race = (-norm["y"] * np.log(np.clip(norm["p"], EPS, 1.0))).groupby(norm["race_id"]).sum()
    return float(per_race.mean())


def brier(df: pd.DataFrame) -> float:
    """レース内の全馬の (p − y)² の和の、レース平均。"""
    norm = _races_with_winner(df)
    per_race = ((norm["p"] - norm["y"]) ** 2).groupby(norm["race_id"]).sum()
    return float(per_race.mean())


def _payouts_top(df: pd.DataFrame) -> pd.DataFrame:
    """レースごとの (賭け金, 払戻)。予測1位の単勝を100円。"""
    top = top_picks(df)
    pay = np.where(top["finish"] == 1, top["odds"].fillna(0) * 100, 0.0)
    return pd.DataFrame({"race_id": top["race_id"].to_numpy(), "stake": 100.0, "payout": pay})


def _payouts_ev(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """レースごとの (賭け金, 払戻)。p × odds が閾値を超えた馬をすべて100円ずつ。

    p はレース内で正規化した確率。買う馬がいないレースも賭け金0で残す（ブートストラップで使う）。
    """
    norm = normalize(df)
    buy = norm["p"] * norm["odds"] > threshold
    stake = np.where(buy, 100.0, 0.0)
    payout = np.where(buy & (norm["finish"] == 1), norm["odds"].fillna(0) * 100, 0.0)
    per_race = pd.DataFrame({"race_id": norm["race_id"], "stake": stake, "payout": payout})
    return per_race.groupby("race_id", as_index=False).sum()


def _roi(per_race: pd.DataFrame) -> float:
    stake = per_race["stake"].sum()
    return float(per_race["payout"].sum() / stake) if stake else float("nan")


def bootstrap_roi(
    per_race: pd.DataFrame, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05,
) -> tuple[float, float]:
    """回収率の (下限, 上限)。レースを復元抽出する（同じレースの馬はまとめて動く）。"""
    stake = per_race["stake"].to_numpy()
    payout = per_race["payout"].to_numpy()
    n = len(stake)
    if n == 0 or stake.sum() == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    stakes = stake[idx].sum(axis=1)
    rois = np.divide(payout[idx].sum(axis=1), stakes, out=np.full(n_boot, np.nan), where=stakes > 0)
    low, high = np.nanquantile(rois, [alpha / 2, 1 - alpha / 2])
    return float(low), float(high)


def roi_top(df: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    """予測1位の単勝を毎回100円買ったときの回収率と95%区間。"""
    per_race = _payouts_top(df)
    low, high = bootstrap_roi(per_race, n_boot, seed)
    return {"roi": _roi(per_race), "ci_low": low, "ci_high": high, "bets": int(len(per_race))}


def roi_ev(df: pd.DataFrame, threshold: float, n_boot: int = 2000, seed: int = 0) -> dict:
    """期待値（予測勝率×オッズ）が閾値を超えた馬だけ買ったときの回収率と95%区間。"""
    per_race = _payouts_ev(df, threshold)
    low, high = bootstrap_roi(per_race, n_boot, seed)
    return {"roi": _roi(per_race), "ci_low": low, "ci_high": high,
            "bets": int((per_race["stake"] / 100).sum()), "threshold": threshold}


def calibration_table(df: pd.DataFrame, bins=DEFAULT_BINS) -> pd.DataFrame:
    """予測確率（正規化後）のビンごとの頭数・平均予測・実際の勝率。"""
    norm = normalize(df)
    cut = pd.cut(norm["p"], bins=list(bins), include_lowest=True)
    table = norm.groupby(cut, observed=False).agg(
        n=("p", "size"), mean_pred=("p", "mean"), win_rate=("y", "mean"),
    )
    table.index = table.index.astype(str)
    return table.reset_index(names="bin")


def summary(
    df: pd.DataFrame, ev_thresholds=(1.0, 1.2), n_boot: int = 2000, seed: int = 0,
) -> dict:
    """主な指標をまとめて1つの dict にする（表に並べる用）。"""
    top = roi_top(df, n_boot, seed)
    out = {
        "races": int(df["race_id"].nunique()),
        "hit_rate": hit_rate(df),
        "place_rate": place_rate(df),
        "logloss": logloss(df),
        "brier": brier(df),
        "roi_top": top["roi"], "roi_top_ci": (top["ci_low"], top["ci_high"]),
    }
    for threshold in ev_thresholds:
        ev = roi_ev(df, threshold, n_boot, seed)
        out[f"roi_ev{threshold}"] = ev["roi"]
        out[f"roi_ev{threshold}_ci"] = (ev["ci_low"], ev["ci_high"])
        out[f"roi_ev{threshold}_bets"] = ev["bets"]
    return out


# --- 順位相関 ---------------------------------------------------------------------

def _spearman(a: np.ndarray, b: np.ndarray, method: str = "average") -> float:
    """スピアマンの順位相関。同順位は既定で平均順位（`method="first"` なら並び順で切る）。

    ばらつきが無ければ NaN。
    """
    ra = pd.Series(a).rank(method=method).to_numpy()
    rb = pd.Series(b).rank(method=method).to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def rank_correlation(df: pd.DataFrame, score_col: str) -> dict:
    """スコアの順と着順の順位相関。スコアが高いほど着順が良い（小さい）とき正になる。

    - `per_race` … レースごとの相関の平均。全頭のスコアが同じレース（新馬戦など）は
      相関が出ないので除く
    - `per_race_all` … 同じく、ただし相関が出ないレースを0（見分けられない）として数える
    - `per_race_legacy` … 旧実測（0.390）の出し方。同点を並び順（馬番順）で切り、全レースを数える
    - `pooled` … 全頭をまとめた1本
    着順の無い馬（中止など）は除く。
    """
    valid = df.dropna(subset=["finish", score_col])
    groups = [g for _, g in valid.groupby("race_id") if len(g) >= 2]
    per_race = np.array([
        _spearman(-g[score_col].to_numpy(), g["finish"].to_numpy()) for g in groups
    ])
    legacy = np.array([
        _spearman(-g[score_col].to_numpy(), g["finish"].to_numpy(), method="first") for g in groups
    ])
    nan = float("nan")
    return {
        "per_race": float(np.nanmean(per_race)) if len(groups) else nan,
        "per_race_all": float(np.nan_to_num(per_race).mean()) if len(groups) else nan,
        "per_race_legacy": float(np.nan_to_num(legacy).mean()) if len(groups) else nan,
        "pooled": _spearman(-valid[score_col].to_numpy(), valid["finish"].to_numpy()),
    }
