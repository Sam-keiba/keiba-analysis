"""血統クロス（インブリード）の集計。`horse_ancestors` と手元のレース結果から出す。

`sire_runs.py` と同じ作り（Streamlitに依存しない純粋な関数）。集計範囲も同じで
**2023年以降のJRAのレースだけ**。

## 何を出すか

1. **祖先別** — 5代血統表にその祖先を持つ産駒と、**持たない産駒**を並べて出す。
   片方だけでは「持っていると走るのか」が読めないので、必ず対で返す
2. **クロス別** — 同じ祖先が2箇所以上に出る馬をまとめる。表記は代数の小さい順で
   「4×5」（日本での一般的な書き方）

## 取り込み途中の扱い

血統表は1頭ずつ取り込むので、**入っている産駒だけで率を出すと母数が小さくなる**。
どの関数も「血統表が入っている頭数」を一緒に返し、画面で進み具合を出せるようにする。
持っていない産駒（`without`）も**血統表が入っている産駒だけ**を数える
（入っていない産駒を「持たない」側に混ぜると、答えそのものが狂うため）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from keiba_analysis.shared.sire_runs import Tally

# 表に出す最低頭数（これ未満の祖先・クロスは並べても読めない）
MIN_HORSES = 3
# まとめた祖先名を何頭ぶんまで並べるか（残りは「ほかN頭」にする）
MERGED_NAMES = 3
# 祖先別・クロス別に出す行数の上限
TOP_ANCESTORS = 30
TOP_CROSSES = 25

# その種牡馬の産駒のうち、血統表が入っている馬の「1走1行」。
# `horses.sire` で絞ったうえで、血統表がある馬だけに限る
_RUNS_SQL = """
    SELECT e.horse_id, h.horse_name, h.sex,
           ra.surface, re.finish_position, re.prize_man_yen
      FROM entries e
      JOIN horses  h  ON h.horse_id = e.horse_id
      JOIN races   ra ON ra.race_id = e.race_id
      JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
     WHERE h.sire = ?
       AND EXISTS (SELECT 1 FROM horse_ancestors a WHERE a.horse_id = e.horse_id)
"""

# その種牡馬の産駒が5代内に持つ祖先（1頭1祖先1行。同じ祖先が複数箇所なら代数を連ねる）
_ANCESTORS_SQL = """
    SELECT a.horse_id, p.name AS name, p.country AS country,
           GROUP_CONCAT(a.generation) AS generations,
           GROUP_CONCAT(a.path) AS paths
      FROM horse_ancestors a
      JOIN pedigree_horses p ON p.horse_no = a.ancestor_no
      JOIN horses h ON h.horse_id = a.horse_id
     WHERE h.sire = ?
  GROUP BY a.horse_id, a.ancestor_no
"""


@dataclass(frozen=True)
class Coverage:
    """血統表の取り込みがどこまで進んでいるか。"""

    sire_horses: int      # その種牡馬の産駒として分かっている頭数
    with_pedigree: int    # うち5代血統表が入っている頭数
    known: int            # 血統表が入っている馬（DB全体）
    total: int            # 出走した馬（DB全体）

    @property
    def is_complete(self) -> bool:
        return self.sire_horses > 0 and self.with_pedigree >= self.sire_horses


@dataclass(frozen=True)
class CrossRow:
    """1つの「祖先 × クロスの形」。`with_` と `without` を並べて見るための入れ物。"""

    label: str            # 「Sadler's Wells」「ノーザンダンサー 4×5」
    ancestor: str         # 代表にした祖先名（検索の絞り込みに使う）
    ancestors: tuple[str, ...]   # まったく同じ産駒を指す祖先（Caerleon・Flaming Page…）
    country: str | None
    cross: str | None     # 「4×5」。クロスでない（1箇所だけ）行はNone
    horses: int           # その条件に当てはまる産駒の頭数
    with_tally: Tally
    without_tally: Tally

    @property
    def lift(self) -> float | None:
        """持つ産駒の複勝率 ÷ 持たない産駒の複勝率。1.0より上なら「持つほうが走る」。"""
        mine, other = self.with_tally.top3_rate, self.without_tally.top3_rate
        return mine / other if mine is not None and other else None


def coverage(conn: sqlite3.Connection, sire_name: str) -> Coverage:
    """血統表の取り込みの進み具合（その種牡馬ぶんと、DB全体）。"""
    row = conn.execute(
        "SELECT COUNT(DISTINCT h.horse_id) AS horses, "
        "       COUNT(DISTINCT CASE WHEN EXISTS (SELECT 1 FROM horse_ancestors a "
        "              WHERE a.horse_id = h.horse_id) THEN h.horse_id END) AS with_ped "
        "  FROM horses h WHERE h.sire = ? "
        "   AND EXISTS (SELECT 1 FROM entries e WHERE e.horse_id = h.horse_id)",
        (sire_name,),
    ).fetchone()
    whole = conn.execute(
        "SELECT COUNT(*) AS total, "
        "       SUM(CASE WHEN EXISTS (SELECT 1 FROM horse_ancestors a "
        "                              WHERE a.horse_id = h.horse_id) THEN 1 ELSE 0 END) AS done "
        "  FROM horses h WHERE EXISTS (SELECT 1 FROM entries e WHERE e.horse_id = h.horse_id)"
    ).fetchone()
    return Coverage(
        sire_horses=row["horses"] or 0, with_pedigree=row["with_ped"] or 0,
        known=whole["done"] or 0, total=whole["total"] or 0,
    )


def cross_label(generations: list[int]) -> str:
    """代数から「4×5」を組む。**小さい順**（日本での一般的な書き方）。"""
    return "×".join(str(g) for g in sorted(generations))


def _runs_by_horse(conn: sqlite3.Connection, sire_name: str,
                   sex: str | None = None, surface: str | None = None) -> dict[str, list[dict]]:
    """血統表が入っている産駒の走を、馬ごとにまとめる。"""
    rows = [dict(r) for r in conn.execute(_RUNS_SQL, (sire_name,))]
    if sex:
        rows = [r for r in rows if r["sex"] == sex]
    if surface:
        rows = [r for r in rows if r["surface"] == surface]
    by_horse: dict[str, list[dict]] = {}
    for row in rows:
        by_horse.setdefault(row["horse_id"], []).append(row)
    return by_horse


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


def _merge_identical(groups: dict, order: dict) -> list[tuple[list, set[str]]]:
    """**まったく同じ産駒の集合を指す祖先をまとめる。**

    血統表では「Caerleon・Flaming Page・Foreseer」のように、いつも一緒に現れる祖先がある。
    別々の行にすると、同じ4頭の成績を何度も繰り返す表になって読めない。
    代表は**いちばん近い代に出てくるもの**（＝影響が大きく、名前も知られている）にする。
    """
    merged: dict[frozenset, list] = {}
    for key, horse_ids in groups.items():
        merged.setdefault(frozenset(horse_ids), []).append(key)
    out = []
    for horse_ids, keys in merged.items():
        keys.sort(key=lambda k: (order.get(k, 9), k[0]))
        out.append((keys, set(horse_ids)))
    return out


def _label(names: list[str], cross: str | None) -> str:
    """まとめた祖先の見出し。「Caerleon ／ Flaming Page ／ Foreseer」。"""
    shown = " ／ ".join(names[:MERGED_NAMES])
    if len(names) > MERGED_NAMES:
        shown += f" ほか{len(names) - MERGED_NAMES}頭"
    return f"{shown} {cross}" if cross else shown


def _rows(
    conn: sqlite3.Connection, sire_name: str, *, crosses_only: bool,
    sex: str | None, surface: str | None, min_horses: int, top: int,
) -> list[CrossRow]:
    """祖先別（`crosses_only=False`）／クロス別（True）の共通の組み立て。"""
    by_horse = _runs_by_horse(conn, sire_name, sex, surface)
    if not by_horse:
        return []
    all_runs = [run for runs in by_horse.values() for run in runs]

    # {(祖先名, 産国, クロス表記 or None): その条件に当てはまる馬のID}
    groups: dict[tuple[str, str | None, str | None], set[str]] = {}
    # 代表を選ぶための「いちばん近い代」
    closest: dict[tuple[str, str | None, str | None], int] = {}
    for row in conn.execute(_ANCESTORS_SQL, (sire_name,)):
        if row["horse_id"] not in by_horse:
            continue                      # 絞り込みで外れた馬・血統表が無い馬
        generations = [int(g) for g in row["generations"].split(",")]
        if crosses_only and len(generations) < 2:
            continue
        cross = cross_label(generations) if len(generations) >= 2 else None
        key = (row["name"], row["country"], cross if crosses_only else None)
        groups.setdefault(key, set()).add(row["horse_id"])
        closest[key] = min(closest.get(key, 9), min(generations))

    rows: list[CrossRow] = []
    for keys, horse_ids in _merge_identical(groups, closest):
        if len(horse_ids) < min_horses:
            continue
        with_runs = [r for r in all_runs if r["horse_id"] in horse_ids]
        without_runs = [r for r in all_runs if r["horse_id"] not in horse_ids]
        names = [k[0] for k in keys]
        rows.append(CrossRow(
            label=_label(names, keys[0][2]), ancestor=names[0], ancestors=tuple(names),
            country=keys[0][1], cross=keys[0][2], horses=len(horse_ids),
            with_tally=_tally("持つ", with_runs),
            without_tally=_tally("持たない", without_runs),
        ))
    rows.sort(key=lambda r: (-r.horses, -r.with_tally.starts, r.label))
    return rows[:top]


def ancestor_rows(
    conn: sqlite3.Connection, sire_name: str, *, sex: str | None = None,
    surface: str | None = None, min_horses: int = MIN_HORSES, top: int = TOP_ANCESTORS,
) -> list[CrossRow]:
    """5代血統表に出てくる祖先ごとの成績（持つ産駒 vs 持たない産駒）。"""
    return _rows(conn, sire_name, crosses_only=False, sex=sex, surface=surface,
                 min_horses=min_horses, top=top)


def cross_rows(
    conn: sqlite3.Connection, sire_name: str, *, sex: str | None = None,
    surface: str | None = None, min_horses: int = MIN_HORSES, top: int = TOP_CROSSES,
) -> list[CrossRow]:
    """クロス（同じ祖先が2箇所以上）ごとの成績。"""
    return _rows(conn, sire_name, crosses_only=True, sex=sex, surface=surface,
                 min_horses=min_horses, top=top)


def find_ancestor(conn: sqlite3.Connection, keyword: str, limit: int = 20) -> list[dict]:
    """祖先を名前で探す（画面の検索欄用）。何頭の馬が5代内に持っているかを添える。"""
    rows = conn.execute(
        "SELECT p.name, p.country, COUNT(DISTINCT a.horse_id) AS horses "
        "  FROM pedigree_horses p JOIN horse_ancestors a ON a.ancestor_no = p.horse_no "
        " WHERE p.name LIKE ? GROUP BY p.horse_no ORDER BY horses DESC LIMIT ?",
        (f"%{keyword}%", limit),
    )
    return [dict(r) for r in rows]
