"""一口クラブごとの集計（どのクラブがどう走らせているか）。

`sire_runs.py` と同じ「1行1走」の形を使うので、距離別・年齢別・デビュー時期といった
集計関数は**そちらのものをそのまま使い回す**。ここにはクラブ固有のもの
（クラブの一覧・クラブどうしの比較・厩舎の使い方・種牡馬の使い方）だけを置く。

集計範囲も同じで**2023年以降のJRAのレースだけ**。

## 馬主の扱いで気をつけること

- **`entries.owner_id`（レース当時の馬主）で絞る。** `horses.owner_name` は
  JRA公式の「現在の馬主」なので、転売された馬で食い違う
  （Ｇ１レーシングで走った馬の `horses.owner_name` が個人名になっている、など）
- **`owners.owner_name` は10文字で切れている**（netkeibaのレース結果ページ由来）。
  `owner_id` が本当の鍵なので集計には困らないが、**表示名は `CLUBS` に手で持たせる**
"""

from __future__ import annotations

import sqlite3

from keiba_analysis.shared.sire_runs import Tally, runs_where

# 一口クラブの一覧。**(DBの馬主名, 表示名, 系列)**。
# DBの馬主名は10文字で切れていることがあるので、切れた形をそのまま書く。
# **ここを足し引きすればクラブが増やせる**（画面にもそう書いてある）。
CLUBS: tuple[tuple[str, str, str], ...] = (
    ("社台レースホース",        "社台レースホース",                     "社台"),
    ("サンデーレーシング",      "サンデーレーシング",                   "社台"),
    ("キャロットファーム",      "キャロットファーム",                   "社台"),
    ("シルクレーシング",        "シルクレーシング",                     "社台"),
    ("Ｇ１レーシング",          "G1レーシング",                         "社台"),
    ("サラブレッドクラブ・...", "サラブレッドクラブ・ラフィアン",       "ビッグレッド"),
    ("ウイン",                  "ウインレーシングクラブ",               "ビッグレッド"),
    ("ノルマンディーサラブ...", "ノルマンディーサラブレッドレーシング", "その他"),
    ("東京ホースレーシング",    "東京ホースレーシング",                 "その他"),
    ("ロードホースクラブ",      "ロードホースクラブ",                   "その他"),
    ("ヒダカ・ブリーダーズ...", "ヒダカ・ブリーダーズ・ユニオン",       "その他"),
    ("ライオンレースホース",    "ライオンレースホース",                 "その他"),
    ("ディアレストクラブ",      "ディアレストクラブ",                   "その他"),
    ("ターフ・スポート",        "ターファイトクラブ",                   "その他"),
    ("ＤＭＭドリームクラブ",    "DMMバヌーシー",                        "その他"),
    ("グリーンファーム",        "グリーンファーム（愛馬会）",           "その他"),
    ("京都ホースレーシング",    "京都サラブレッドクラブ",               "その他"),
    ("インゼルレーシング",      "インゼルサラブレッドクラブ",           "その他"),
    ("ローレルレーシング",      "ローレルクラブ",                       "その他"),
    ("広尾レース",              "広尾サラブレッド倶楽部",               "その他"),
    ("ＹＧＧホースクラブ",      "YGGホースクラブ",                      "その他"),
    ("友駿ホースクラブ",        "友駿ホースクラブ",                     "その他"),
    ("フィールドレーシング",    "フィールドレーシング",                 "その他"),
    ("Ｇリビエール・レーシ...", "Gリビエール・レーシング",              "その他"),
)

# 一口クラブかどうか判断がつかなかった馬主。分かったら上へ移す。
# 「スリーエイチレーシン...」「フォレストレーシング」「ＨｉｍＲｏｃｋＲａｃ...」
# 「ＣＨＥＶＡＬＡＴＴＡ...」「ウエスト．フォレスト...」「ＫＨレーシング」「ＴＮレーシング」
# タマモ・大樹ファーム・ノースヒルズ・ビッグレッドファームは個人／法人の馬主なので入れない。

CLUB_BY_OWNER_NAME = {db_name: (label, group) for db_name, label, group in CLUBS}
# 表に出す最低頭数（これ未満の調教師・種牡馬は並べても読めない）
MIN_HORSES = 2
TOP_TRAINERS = 20
TOP_SIRES = 20


def list_clubs(conn: sqlite3.Connection) -> list[dict]:
    """`CLUBS` のうち**実際にDBにいる**クラブを、産駒の多い順に返す。"""
    if not CLUBS:
        return []
    names = [name for name, _label, _group in CLUBS]
    marks = ", ".join("?" * len(names))
    rows = conn.execute(
        f"""
        SELECT o.owner_id, o.owner_name, COUNT(DISTINCT e.horse_id) AS horses
          FROM entries e JOIN owners o USING(owner_id)
         WHERE o.owner_name IN ({marks})
      GROUP BY o.owner_id
      ORDER BY horses DESC
        """,
        names,
    )
    clubs = []
    for row in rows:
        label, group = CLUB_BY_OWNER_NAME[row["owner_name"]]
        clubs.append({"owner_id": row["owner_id"], "owner_name": row["owner_name"],
                      "label": label, "group": group, "horses": row["horses"]})
    return clubs


def club_runs(conn: sqlite3.Connection, owner_id: str) -> list[dict]:
    """そのクラブの馬の全走（1行1走）。**レース当時の馬主**で絞る。"""
    return runs_where(conn, "e.owner_id = ?", (owner_id,))


# --- クラブどうしの比較 -------------------------------------------------------------

_SUMMARY_SQL = """
    SELECT e.owner_id, o.owner_name,
           COUNT(DISTINCT e.horse_id) AS horses,
           COUNT(*) AS starts,
           COUNT(DISTINCT CASE WHEN re.finish_position = 1 THEN e.horse_id END) AS winners,
           SUM(re.finish_position = 1) AS wins,
           SUM(re.finish_position <= 3) AS top3,
           SUM(re.finish_position <= 5) AS top5,
           SUM(ra.surface = 'turf') AS turf_starts,
           SUM(ra.surface = 'dirt') AS dirt_starts,
           SUM(ra.surface = 'jump') AS jump_starts,
           SUM(COALESCE(re.prize_man_yen, 0)) AS prize_man_yen,
           COUNT(DISTINCT CASE WHEN ra.grade IS NOT NULL AND re.finish_position = 1
                               THEN e.horse_id END) AS graded_winners
      FROM entries e
      JOIN owners  o  USING(owner_id)
      JOIN races   ra ON ra.race_id = e.race_id
      JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
     WHERE o.owner_name IN ({marks})
  GROUP BY e.owner_id
"""


def _turf_rate(turf: int | None, dirt: int | None) -> float | None:
    """芝の出走比率。**障害は分母から外す**（`sire_runs.turf_share` と同じ定義）。"""
    flat = (turf or 0) + (dirt or 0)
    return (turf or 0) / flat if flat else None


def club_summary(conn: sqlite3.Connection) -> list[dict]:
    """全クラブを並べて比べる（1クエリ）。

    **勝ち上がり率は「1勝でもした馬 ÷ 出走した馬」**（出走ではなく頭数が分母）。
    一口出資でいちばん効いてくる数字なので、率のうちこれだけ頭数ベースにしている。
    """
    names = [name for name, _label, _group in CLUBS]
    if not names:
        return []
    marks = ", ".join("?" * len(names))
    rows = []
    for row in conn.execute(_SUMMARY_SQL.format(marks=marks), names):
        label, group = CLUB_BY_OWNER_NAME[row["owner_name"]]
        horses, starts = row["horses"] or 0, row["starts"] or 0
        rows.append({
            "owner_id": row["owner_id"], "owner_name": row["owner_name"],
            "label": label, "group": group,
            "horses": horses, "starts": starts,
            "winners": row["winners"] or 0,
            "win_up_rate": (row["winners"] / horses) if horses else None,
            "win_rate": (row["wins"] / starts) if starts else None,
            "top3_rate": (row["top3"] / starts) if starts else None,
            "top5_rate": (row["top5"] / starts) if starts else None,
            "prize_per_horse": (row["prize_man_yen"] / horses) if horses else None,
            "graded_winners": row["graded_winners"] or 0,
            "turf_starts": row["turf_starts"] or 0,
            "dirt_starts": row["dirt_starts"] or 0,
            "jump_starts": row["jump_starts"] or 0,
            # 芝率は **障害を分母から外す**（sire_runs.turf_share と同じ定義にそろえる。
            # ここがずれると、クラブ比較とデビュー・成長・距離の数字が食い違う）
            "turf_rate": _turf_rate(row["turf_starts"], row["dirt_starts"]),
        })
    rows.sort(key=lambda r: -(r["prize_per_horse"] or 0))
    return rows


# --- クラブの中身（厩舎・種牡馬） ----------------------------------------------------

def _tally(label: str, runs: list[dict]) -> Tally:
    return Tally(
        label=label,
        horses=len({r["horse_id"] for r in runs}),
        starts=len(runs),
        wins=sum(1 for r in runs if r["finish_position"] == 1),
        top3=sum(1 for r in runs if (r["finish_position"] or 99) <= 3),
        top5=sum(1 for r in runs if (r["finish_position"] or 99) <= 5),
        prize_man_yen=sum(r["prize_man_yen"] or 0.0 for r in runs),
    )


def _grouped(runs: list[dict], key: str, *, min_horses: int, top: int) -> list[Tally]:
    """`key` の値ごとにまとめて、頭数の多い順に上位を返す。"""
    values = {r[key] for r in runs if r.get(key)}
    tallies = [_tally(value, [r for r in runs if r[key] == value]) for value in values]
    tallies = [t for t in tallies if t.horses >= min_horses]
    tallies.sort(key=lambda t: (-t.horses, -t.starts, t.label))
    return tallies[:top]


def by_trainer(runs: list[dict], *, min_horses: int = MIN_HORSES,
               top: int = TOP_TRAINERS) -> list[Tally]:
    """調教師ごとの成績（預けている頭数の多い順）。調教師は全走に入っている。"""
    return _grouped(runs, "trainer_name", min_horses=min_horses, top=top)


def by_stable(runs: list[dict]) -> list[Tally]:
    """美浦／栗東の内訳。東西どちらに預けるかはクラブの色が出る。"""
    return [_tally(stable, [r for r in runs if r["stable"] == stable])
            for stable in ("美浦", "栗東")]


def by_sire(runs: list[dict], *, min_horses: int = MIN_HORSES,
            top: int = TOP_SIRES) -> list[Tally]:
    """種牡馬ごとの成績（買っている頭数の多い順）。

    **父が分かっている馬だけ**が対象。血統の取り込み（`keiba pedigree` / `keiba bloodline`）
    が進むほど濃くなるので、画面では `sire_coverage` と一緒に出す。
    """
    return _grouped(runs, "sire", min_horses=min_horses, top=top)


def sire_coverage(runs: list[dict]) -> tuple[int, int]:
    """(父が分かっている頭数, そのクラブの頭数)。取り込みの進み具合の表示に使う。"""
    horses = {r["horse_id"] for r in runs}
    known = {r["horse_id"] for r in runs if r.get("sire")}
    return len(known), len(horses)
