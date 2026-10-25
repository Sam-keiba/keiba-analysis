"""現行ロジック（tier.py）で過去レースを採点し直し、旧実測の再現とリークの影響を測る。

    uv run python -m eval.reproduce_legacy --start 2025-01-01 --end 2025-01-31
    uv run python -m eval.reproduce_legacy --start 2023-01-01 --end 2026-12-31 --workers 8

2つのモードを並べる:
    leak   … 今日のペースだけ日付で絞らない（アプリの get_condition_laps と同じ。旧実測の再現）
    clean  … すべて今回のレース日より前の情報だけ（leak_free=True）
過去走・全走・相手の走は、どちらのモードでも今回のレース日より前だけ（data_access を参照）。

1頭1行の採点結果を eval/out/ に CSV で書き、集計表を標準出力に出す。
"""

from __future__ import annotations

import argparse
import time
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

from eval import data_access, evaluate

OUT_DIR = Path(__file__).resolve().parent / "out"

# 旧実測（tier.py の CALIBRATION・docstring。2023-01-01〜2026-10-12 の 12,627レース）
LEGACY = {
    "rank_corr": 0.390,
    "a_race_share": 856 / 12627,
    "A": {"starts": 1085, "win": 0.345, "top3": 0.674, "popularity": 1.9},
    "B": {"starts": 14974, "win": 0.200, "top3": 0.469, "popularity": 3.3},
    "C": {"starts": 70937, "win": 0.094, "top3": 0.285, "popularity": 6.0},
    "D": {"starts": 86838, "win": 0.030, "top3": 0.114, "popularity": 9.9},
}
LEGACY_END = "2026-10-16"   # 旧実測の時点で DB に入っていた最後の日の翌日の手前

_conn = None


def _init_worker(db_path: str | None) -> None:
    global _conn
    _conn = data_access.connect(db_path)


def score_race(race_id: str) -> list[dict]:
    """1レースを両モードで採点し、1頭1行の dict を返す。

    両モードの違いは今日のペースだけなので、材料は1回だけ作り、ペースだけ差し替える
    （`build_inputs(leak_free=False)` と同じ中身になる）。
    """
    inputs = data_access.build_inputs(_conn, race_id, leak_free=True)
    leak_inputs = {**inputs, "today_pace": data_access.today_pace(_conn, inputs["race"], None)}
    race = inputs["race"]
    rows = []
    for mode, ins in (("clean", inputs), ("leak", leak_inputs)):
        scores = data_access.assign(ins)
        for entry in ins["entries"]:
            score = scores.get(entry["horse_id"])
            rows.append({
                "mode": mode, "race_id": race_id, "race_date": race["race_date"],
                "age_condition": race.get("age_condition"), "grade": race.get("grade"),
                "horse_id": entry["horse_id"], "umaban": entry["umaban"],
                "finish": entry["finish_position"], "popularity": entry["popularity"],
                "odds": entry["win_odds"], "today_pace": ins["today_pace"],
                "margin": score.margin if score else None,
                "tier": score.tier if score else None,
            })
    return rows


def run(start: str, end: str, workers: int, db_path: str | None) -> pd.DataFrame:
    conn = data_access.connect(db_path)
    race_ids = [r["race_id"] for r in data_access.list_races(conn, start, end)]
    conn.close()
    began = time.perf_counter()
    rows: list[dict] = []
    with Pool(workers, initializer=_init_worker, initargs=(db_path,)) as pool:
        for i, race_rows in enumerate(pool.imap(score_race, race_ids, chunksize=8), 1):
            rows.extend(race_rows)
            if i % 500 == 0:
                print(f"  {i}/{len(race_ids)} レース（{time.perf_counter() - began:.0f}秒）", flush=True)
    elapsed = time.perf_counter() - began
    print(f"{len(race_ids)} レースを {elapsed:.0f}秒で採点（1レース {elapsed / max(len(race_ids), 1):.2f}秒・{workers}並列）")
    return pd.DataFrame(rows)


# --- 集計 -------------------------------------------------------------------------

def tier_table(df: pd.DataFrame) -> pd.DataFrame:
    """段ごとの頭数・勝率・複勝率・平均人気。分母は着順のある馬（旧実測と同じ定義）。"""
    finished = df.dropna(subset=["finish"])
    return finished.groupby("tier").agg(
        starts=("finish", "size"),
        win=("finish", lambda s: (s == 1).mean()),
        top3=("finish", lambda s: (s <= 3).mean()),
        popularity=("popularity", "mean"),
    ).reindex(["A", "B", "C", "D"])


def summarize(df: pd.DataFrame) -> dict:
    corr = evaluate.rank_correlation(df.dropna(subset=["margin"]), "margin")
    races = df["race_id"].nunique()
    a_races = df.loc[df["tier"] == "A", "race_id"].nunique()
    return {
        "races": races,
        "starts": int(df["finish"].notna().sum()),
        "rank_corr_per_race": corr["per_race"],
        "rank_corr_per_race_all": corr["per_race_all"],
        "rank_corr_legacy": corr["per_race_legacy"],
        "rank_corr_pooled": corr["pooled"],
        "a_race_share": a_races / races if races else float("nan"),
        "tiers": tier_table(df),
    }


def _fmt_pct(x: float) -> str:
    return "—" if pd.isna(x) else f"{x:.1%}"


def comparison_markdown(df: pd.DataFrame, label: str) -> str:
    """旧実測・leak・clean を並べた表（Markdown）。"""
    parts = {mode: summarize(df[df["mode"] == mode]) for mode in ("leak", "clean")}
    leak, clean = parts["leak"], parts["clean"]
    lines = [
        f"### {label}",
        "",
        "| 指標 | 旧実測 | リークあり (leak) | リークなし (clean) |",
        "|---|---|---|---|",
        f"| レース数 | 12,627 | {leak['races']:,} | {clean['races']:,} |",
        f"| 着順のある頭数 | 173,834 | {leak['starts']:,} | {clean['starts']:,} |",
        f"| 順位相関（旧方式: 同点は馬番順・全レース） | 0.390 | {leak['rank_corr_legacy']:.3f} | {clean['rank_corr_legacy']:.3f} |",
        f"| 順位相関（同点は平均順位・見分けられないレースは0） | — | {leak['rank_corr_per_race_all']:.3f} | {clean['rank_corr_per_race_all']:.3f} |",
        f"| 順位相関（同点は平均順位・見分けられないレースを除く） | — | {leak['rank_corr_per_race']:.3f} | {clean['rank_corr_per_race']:.3f} |",
        f"| 順位相関（全頭まとめて1本） | — | {leak['rank_corr_pooled']:.3f} | {clean['rank_corr_pooled']:.3f} |",
        f"| Aが出たレースの割合 | {LEGACY['a_race_share']:.1%} | {_fmt_pct(leak['a_race_share'])} | {_fmt_pct(clean['a_race_share'])} |",
    ]
    for key in ("A", "B", "C", "D"):
        old = LEGACY[key]
        lt, ct = leak["tiers"].loc[key], clean["tiers"].loc[key]
        lines += [
            f"| {key} 頭数 | {old['starts']:,} | {int(lt['starts'] or 0):,} | {int(ct['starts'] or 0):,} |",
            f"| {key} 勝率 | {old['win']:.1%} | {_fmt_pct(lt['win'])} | {_fmt_pct(ct['win'])} |",
            f"| {key} 複勝率 | {old['top3']:.1%} | {_fmt_pct(lt['top3'])} | {_fmt_pct(ct['top3'])} |",
            f"| {key} 平均人気 | {old['popularity']:.1f} | {lt['popularity']:.1f} | {ct['popularity']:.1f} |",
        ]
    return "\n".join(lines)


def pace_diff_markdown(df: pd.DataFrame) -> str:
    """両モードで今日のペースや段が変わった割合（リークがどこに効いたか）。"""
    wide = df.pivot_table(index=["race_id", "horse_id"], columns="mode",
                          values=["today_pace", "tier", "margin"], aggfunc="first")
    pace_changed = (wide[("today_pace", "leak")].fillna("") != wide[("today_pace", "clean")].fillna(""))
    races_changed = pace_changed.groupby(level="race_id").any()
    tier_changed = wide[("tier", "leak")] != wide[("tier", "clean")]
    margin_gap = (wide[("margin", "leak")] - wide[("margin", "clean")]).abs()
    return "\n".join([
        "| 差 | 値 |",
        "|---|---|",
        f"| 今日のペース（H/M/S）が変わったレース | {races_changed.sum():,} / {len(races_changed):,}（{races_changed.mean():.1%}） |",
        f"| 段が変わった馬 | {tier_changed.sum():,} / {len(tier_changed):,}（{tier_changed.mean():.2%}） |",
        f"| margin の差の平均（絶対値） | {margin_gap.mean():.4f} 段 |",
        f"| margin の差の最大 | {margin_gap.max():.3f} 段 |",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2099-12-31")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    df = run(args.start, args.end, args.workers, args.db)
    OUT_DIR.mkdir(exist_ok=True)
    csv = OUT_DIR / f"legacy_{args.start}_{args.end}.csv"
    df.to_csv(csv, index=False)
    print(f"採点結果: {csv}\n")

    print(comparison_markdown(df, f"{args.start} 〜 {df['race_date'].max()}（全期間）"), "\n")
    legacy_period = df[df["race_date"] <= LEGACY_END]
    if not legacy_period.empty and len(legacy_period) < len(df):
        print(comparison_markdown(legacy_period, f"{args.start} 〜 {LEGACY_END}（旧実測と同じ期間）"), "\n")
    print("### リークあり／なしの差\n")
    print(pace_diff_markdown(df))


if __name__ == "__main__":
    main()
