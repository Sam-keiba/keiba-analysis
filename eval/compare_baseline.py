"""現行ロジック（tier.py の margin）が、人気だけの予想より情報を足しているかを測る（STEP2）。

    uv run python -m eval.compare_baseline

材料は STEP1 の採点結果（eval/out/legacy_*.csv の leak_free=True の行）。無ければ作り直す。
学習＝2023〜2025年、評価＝2026年（evaluate.split_fixed）。

**人気ベースは確定単勝オッズから作るので、発走前には分からない「市場の評価」＝上限の目安**として扱う。
実際に買える時点のオッズはこれより粗いので、人気ベースの数字は現実より少し良く出る。

並べる予想:
    market   … 確定単勝オッズの逆数を、レース内で合計1にしたもの
    current  … softmax(margin / T)。T は1つだけで、2023〜2025年の logloss が最小になる値
    random   … 1 / 頭数（参考）
    P / PM   … 条件付きロジット。P は log(market) だけ、PM はそれに margin を足したもの
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from eval import data_access, evaluate, reproduce_legacy

CSV = reproduce_legacy.OUT_DIR / "legacy_2023-01-01_2026-12-31.csv"
SUMMARY = reproduce_legacy.OUT_DIR / "step2_summary.md"
SEED = 0
N_BOOT = 2000


# --- 材料 -------------------------------------------------------------------------

def load(csv: Path = CSV, db_path: str | None = None) -> pd.DataFrame:
    """leak_free=True の採点結果に、区分用の class_condition・surface と、同点を切る乱数の列を足す。"""
    if not csv.exists():
        df = reproduce_legacy.run("2023-01-01", "2026-12-31", 8, db_path)
        csv.parent.mkdir(exist_ok=True)
        df.to_csv(csv, index=False)
    df = pd.read_csv(csv, dtype={"race_id": str, "horse_id": str})
    df = df[df["mode"] == "clean"].drop(columns="mode").reset_index(drop=True)
    conn = data_access.connect(db_path)
    races = pd.read_sql_query(
        "SELECT race_id, class_condition, surface FROM races WHERE race_date >= '2023-01-01'", conn,
    )
    conn.close()
    df = df.merge(races, on="race_id", how="left")
    df["n"] = df.groupby("race_id")["horse_id"].transform("size")
    # margin が同点の馬・ランダムの予測1位を、オッズを見ずに切るための乱数（seed 固定）
    df["tb"] = np.random.default_rng(SEED).random(len(df))
    return df


def market_prob(df: pd.DataFrame) -> pd.Series:
    """確定単勝オッズの逆数を、レース内で合計1にしたもの。"""
    inv = 1.0 / df["odds"]
    return inv / inv.groupby(df["race_id"]).transform("sum")


def softmax_by_race(race_id: pd.Series, score: pd.Series | np.ndarray) -> np.ndarray:
    """レース内のソフトマックス。"""
    s = pd.Series(np.asarray(score, dtype=float), index=race_id.index)
    s = s - s.groupby(race_id).transform("max")
    e = np.exp(s)
    return (e / e.groupby(race_id).transform("sum")).to_numpy()


# --- 現行ロジックの勝率化（温度は1つ） ----------------------------------------------

def _temperature_loss(df: pd.DataFrame, t: float) -> float:
    return evaluate.logloss(df.assign(p_win=softmax_by_race(df["race_id"], df["margin"] / t)))


def fit_temperature(train: pd.DataFrame, low: float = 0.05, high: float = 20.0) -> float:
    """softmax(margin / T) の logloss を最小にする T。log スケールの格子で粗く探し、黄金分割で詰める。"""
    grid = np.geomspace(low, high, 41)
    losses = [_temperature_loss(train, t) for t in grid]
    i = int(np.argmin(losses))
    a, b = np.log(grid[max(i - 1, 0)]), np.log(grid[min(i + 1, len(grid) - 1)])
    ratio = (np.sqrt(5) - 1) / 2
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = _temperature_loss(train, np.exp(c)), _temperature_loss(train, np.exp(d))
    for _ in range(40):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = _temperature_loss(train, np.exp(c))
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = _temperature_loss(train, np.exp(d))
    return float(np.exp((a + b) / 2))


# --- 条件付きロジット ---------------------------------------------------------------

def _design(df: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(特徴量の行列, レースの番号, 勝ち y)。勝ち馬のいないレースは除く。同着は 1/k。"""
    won = (df["finish"] == 1).astype(float)
    winners = won.groupby(df["race_id"]).transform("sum")
    keep = (winners > 0).to_numpy()
    sub = df[keep]
    y = (won[keep] / winners[keep]).to_numpy()
    codes = pd.factorize(sub["race_id"])[0]
    return sub[features].to_numpy(dtype=float), codes, y


def _race_probs(x: np.ndarray, codes: np.ndarray, beta: np.ndarray) -> np.ndarray:
    u = x @ beta
    n_races = codes.max() + 1
    umax = np.full(n_races, -np.inf)
    np.maximum.at(umax, codes, u)
    e = np.exp(u - umax[codes])
    return e / np.bincount(codes, weights=e, minlength=n_races)[codes]


def fit_clogit(df: pd.DataFrame, features: list[str], max_iter: int = 50) -> dict:
    """レース内で1頭を選ぶ条件付きロジットを、ニュートン法で学習する。

    返すのは係数・標準誤差（ヘッセ行列の逆から）・学習データの負の対数尤度（1レースあたり）。
    """
    x, codes, y = _design(df, features)
    n_races = codes.max() + 1
    k = x.shape[1]
    beta = np.zeros(k)

    def nll(b: np.ndarray) -> float:
        return float(-(y * np.log(np.clip(_race_probs(x, codes, b), 1e-300, 1))).sum())

    current = nll(beta)
    for _ in range(max_iter):
        p = _race_probs(x, codes, beta)
        # 1レースの y の合計は1なので、勾配は Σ(y − p)x、ヘッセ行列は −Σ_race [Σp xxᵀ − (Σp x)(Σp x)ᵀ]
        grad = ((y - p)[:, None] * x).sum(axis=0)
        mean_x = np.stack([np.bincount(codes, weights=p * x[:, j], minlength=n_races) for j in range(k)], axis=1)
        dx = x - mean_x[codes]
        info = (p[:, None, None] * dx[:, :, None] * dx[:, None, :]).sum(axis=0)
        step = np.linalg.solve(info, grad)
        scale = 1.0
        while scale > 1e-6:
            trial = beta + scale * step
            value = nll(trial)
            if value <= current:
                break
            scale /= 2
        beta, previous, current = trial, current, value
        if abs(previous - current) < 1e-9 * max(1.0, abs(current)):
            break
    p = _race_probs(x, codes, beta)
    mean_x = np.stack([np.bincount(codes, weights=p * x[:, j], minlength=n_races) for j in range(k)], axis=1)
    dx = x - mean_x[codes]
    info = (p[:, None, None] * dx[:, :, None] * dx[:, None, :]).sum(axis=0)
    se = np.sqrt(np.diag(np.linalg.inv(info)))
    return {"features": features, "beta": beta, "se": se, "nll_per_race": current / n_races}


def predict_clogit(df: pd.DataFrame, model: dict) -> np.ndarray:
    return softmax_by_race(df["race_id"], df[model["features"]].to_numpy(dtype=float) @ model["beta"])


# --- 区分 ---------------------------------------------------------------------------

def class_group(row_class: str | None, grade: str | None) -> str:
    if isinstance(grade, str) and grade:
        return "重賞（L含む）"
    text = row_class or ""
    if text.startswith(("新馬", "未勝利")):
        return "新馬・未勝利"
    if text.startswith(("1勝", "2勝", "3勝")):
        return "条件戦"
    return "オープン（重賞以外）"


def add_segments(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["seg_class"] = [class_group(c, g) for c, g in zip(out["class_condition"], out["grade"])]
    out["seg_gen"] = np.where(out["age_condition"].isin(["2歳", "3歳"]), "クラシック世代", "古馬")
    out["seg_surface"] = out["surface"].map({"turf": "芝", "dirt": "ダート"}).fillna("その他")
    return out


# --- 集計 ---------------------------------------------------------------------------

def predictor_row(df: pd.DataFrame, col: str, tiebreak: str | None) -> dict:
    frame = df.assign(p_win=df[col])
    s = evaluate.summary(frame, ev_thresholds=(), n_boot=N_BOOT, seed=SEED, tiebreak=tiebreak)
    s["rank_corr"] = evaluate.rank_correlation(frame, "p_win")["per_race_all"]
    return s


def tier_rows(test: pd.DataFrame) -> pd.DataFrame:
    """段ごとの頭数・勝率・複勝率・回収率（その段の全馬に単勝100円。95%区間はレース単位）。"""
    rows = []
    for key in ("A", "B", "C", "D"):
        part = test[test["tier"] == key]
        finished = part.dropna(subset=["finish"])
        per_race = pd.DataFrame({
            "race_id": part["race_id"], "stake": 100.0,
            "payout": np.where(part["finish"] == 1, part["odds"] * 100, 0.0),
        }).groupby("race_id", as_index=False).sum()
        low, high = evaluate.bootstrap_roi(per_race, N_BOOT, SEED)
        rows.append({
            "tier": key, "starts": len(finished),
            "win": (finished["finish"] == 1).mean(), "top3": (finished["finish"] <= 3).mean(),
            "roi": per_race["payout"].sum() / per_race["stake"].sum() if len(per_race) else np.nan,
            "ci": (low, high), "races": part["race_id"].nunique(),
        })
    return pd.DataFrame(rows)


def run(db_path: str | None = None) -> str:
    df = add_segments(load(db_path=db_path))
    df["p_market"] = market_prob(df)
    df["log_market"] = np.log(df["p_market"])
    df["p_random"] = 1.0 / df["n"]
    train, test = evaluate.split_fixed(df)
    train, test = train.copy(), test.copy()

    temperature = fit_temperature(train)
    for frame in (train, test):
        frame["p_current"] = softmax_by_race(frame["race_id"], frame["margin"] / temperature)
    model_p = fit_clogit(train, ["log_market"])
    model_pm = fit_clogit(train, ["log_market", "margin"])
    for frame in (train, test):
        frame["p_P"] = predict_clogit(frame, model_p)
        frame["p_PM"] = predict_clogit(frame, model_pm)

    out: list[str] = []
    out.append(f"学習 {train['race_id'].nunique():,} レース（{train['race_date'].min()}〜{train['race_date'].max()}）／"
               f"評価 {test['race_id'].nunique():,} レース（{test['race_date'].min()}〜{test['race_date'].max()}）")
    out.append("人気ベースは確定単勝オッズから作った「市場の評価」で、発走前には分からない上限の目安。\n")

    # A
    out.append(f"## A. 3つの予想（2026年）\n\ncurrent の温度 T = {temperature:.3f}（2023〜2025年の logloss 最小）\n")
    out.append("| 予想 | 的中率 | 複勝圏率 | logloss | Brier | 順位相関 | 予測1位の単勝回収率（95%区間） |")
    out.append("|---|---|---|---|---|---|---|")
    for name, col, tb in (("人気ベース（市場・上限の目安）", "p_market", None),
                          ("現行ロジック softmax(margin/T)", "p_current", "tb"),
                          ("ランダム（1/頭数）", "p_random", "tb"),
                          ("モデルP（人気のみ）", "p_P", None),
                          ("モデルPM（人気＋margin）", "p_PM", None)):
        r = predictor_row(test, col, tb)
        lo, hi = r["roi_top_ci"]
        out.append(f"| {name} | {r['hit_rate']:.1%} | {r['place_rate']:.1%} | {r['logloss']:.4f} | "
                   f"{r['brier']:.4f} | {r['rank_corr']:.3f} | {r['roi_top']:.1%}（{lo:.1%}〜{hi:.1%}） |")
    out.append("\n### 段ごと（2026年。その段の全馬に単勝100円）\n")
    out.append("| 段 | 頭数 | 勝率 | 複勝率 | 回収率（95%区間） |")
    out.append("|---|---|---|---|---|")
    for _, r in tier_rows(test).iterrows():
        out.append(f"| {r['tier']} | {r['starts']:,} | {r['win']:.1%} | {r['top3']:.1%} | "
                   f"{r['roi']:.1%}（{r['ci'][0]:.1%}〜{r['ci'][1]:.1%}） |")

    # B
    ll = {c: evaluate.logloss_by_race(test.assign(p_win=test[c])) for c in ("p_market", "p_current", "p_P", "p_PM")}
    br = {c: evaluate.brier_by_race(test.assign(p_win=test[c])) for c in ("p_market", "p_current", "p_P", "p_PM")}
    d_ll = evaluate.paired_diff(ll["p_PM"], ll["p_P"], N_BOOT, SEED)
    d_br = evaluate.paired_diff(br["p_PM"], br["p_P"], N_BOOT, SEED)
    bp, sp = model_p["beta"], model_p["se"]
    bpm, spm = model_pm["beta"], model_pm["se"]
    out.append("\n## B. 条件付きロジット（2023〜2025年で学習）\n")
    out.append("| モデル | log(人気ベース) の係数 | margin の係数 | 学習の logloss | 評価の logloss | 評価の Brier |")
    out.append("|---|---|---|---|---|---|")
    out.append(f"| P | {bp[0]:.3f}（±{1.96 * sp[0]:.3f}） | — | {model_p['nll_per_race']:.4f} | "
               f"{ll['p_P'].mean():.4f} | {br['p_P'].mean():.4f} |")
    out.append(f"| PM | {bpm[0]:.3f}（±{1.96 * spm[0]:.3f}） | {bpm[1]:.3f}（±{1.96 * spm[1]:.3f}） | "
               f"{model_pm['nll_per_race']:.4f} | {ll['p_PM'].mean():.4f} | {br['p_PM'].mean():.4f} |")
    out.append(f"\nmargin 1段あたりの勝つ見込みの倍率 exp(β) = {np.exp(bpm[1]):.3f}"
               f"（95%区間 {np.exp(bpm[1] - 1.96 * spm[1]):.3f}〜{np.exp(bpm[1] + 1.96 * spm[1]):.3f}）\n")
    out.append("| 差（2026年、PM − P。マイナスが改善） | 平均 | 95%区間 |")
    out.append("|---|---|---|")
    out.append(f"| logloss | {d_ll['diff']:+.5f} | {d_ll['ci_low']:+.5f} 〜 {d_ll['ci_high']:+.5f} |")
    out.append(f"| Brier | {d_br['diff']:+.5f} | {d_br['ci_low']:+.5f} 〜 {d_br['ci_high']:+.5f} |")
    improved = d_ll["ci_high"] < 0 and d_br["ci_high"] < 0
    out.append("\n**結論: " + (
        "margin は人気にない情報を足している（PM が P より logloss・Brier とも有意に良い）。**"
        if improved else
        "現行ロジックは人気に織り込み済みの情報しか持っていない（PM は P より有意に良くならない）。**"
    ))

    # C
    out.append("\n## C. 区分ごと（2026年。係数・温度は全体で学習した1組）\n")
    out.append("| 区分 | レース | 人気 | current | P | PM | current − 人気（95%区間） | PM − P（95%区間） |")
    out.append("|---|---|---|---|---|---|---|---|")
    seg_race = test.groupby("race_id")[["seg_class", "seg_gen", "seg_surface"]].first()
    for col in ("seg_class", "seg_gen", "seg_surface"):
        for value in sorted(seg_race[col].unique()):
            ids = seg_race.index[seg_race[col] == value]
            pick = {c: s.reindex(ids).dropna() for c, s in ll.items()}
            d1 = evaluate.paired_diff(pick["p_current"], pick["p_market"], N_BOOT, SEED)
            d2 = evaluate.paired_diff(pick["p_PM"], pick["p_P"], N_BOOT, SEED)
            out.append(
                f"| {value} | {len(ids):,} | {pick['p_market'].mean():.4f} | {pick['p_current'].mean():.4f} | "
                f"{pick['p_P'].mean():.4f} | {pick['p_PM'].mean():.4f} | "
                f"{d1['diff']:+.4f}（{d1['ci_low']:+.4f}〜{d1['ci_high']:+.4f}） | "
                f"{d2['diff']:+.5f}（{d2['ci_low']:+.5f}〜{d2['ci_high']:+.5f}） |"
            )
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    text = run(args.db)
    SUMMARY.parent.mkdir(exist_ok=True)
    SUMMARY.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\n保存: {SUMMARY}")


if __name__ == "__main__":
    main()
