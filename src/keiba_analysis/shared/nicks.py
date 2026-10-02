"""ニックス診断。「父」と「母父」の配合の相性を、**直近10世代の産駒の成績**から相対評価する。

DB取得（`foal_lines` など）と、行を受け取って数えるだけの純粋関数を分けてある。
ランクやニックスの合否は付けない。数値・頭数・信頼性の目安だけを返す。

## 4つの組み合わせ（上ほど本馬の血統に近い）

1. 父 × 母父
2. 父 × 母父の系統
3. 父の系統 × 母父
4. 父の系統 × 母父の系統

## 系統（系統マスタは作らず、5代血統表の祖先IDで束ねる）

- **父の系統** = 産駒の「父の父」（`horse_ancestors.path = 'ff'`）が、入力した父の父と同じ馬の産駒。
  例: キズナなら、ディープインパクトの息子たちの産駒全体（「ディープインパクト系」）
- **母父の系統** = 産駒の「母父の父」（`'mff'`）が、入力した母父の父と同じ馬の産駒
- 4の頭数が `min_horses` に満たないときは、父方・母方を1代ずつ遡る（`'fff'` / `'mfff'`、さらに
  `'ffff'` / `'mffff'`）。試す順は `LEVEL_ORDER`。1代遡った系統名には「*」、2代なら「**」を付ける。
  同じ遡り方を2・3にも使う。1（父 × 母父）は遡らない
- 系統名は祖の名前＋「系」。祖の名前は `pedigree_horses.name`（英字しか無い祖先は英字のまま）

## 指標と「平均比」

- **勝ち上がり率** = JRAで1勝以上した頭数 ÷ 出走した頭数
- **複勝回数** = 3着以内の回数 ÷ 出走した頭数（1頭あたり）
- **AEI** = `sire_index.aei` と同じ式・同じ分母（全出走馬の1頭平均賞金）。産駒の全期間（累計）
- **平均比** = その組み合わせの値 ÷ 比べる相手の値。相手は、1・2は**父の全産駒**、3・4は
  **父の系統の全産駒**（どちらも同じ10世代）
- **母父平均比** = その組み合わせの値 ÷ 母父（2・4は母父の系統）の全産駒（父を問わない）の値

## 世代

**直近10世代**（`crop_window`）＝今いちばん若い出走世代（2歳）から遡って10世代。集計途中の世代も
含める（その世代の馬は `is_partial`）。若い世代が多い配合は、AEIや勝ち上がり率が低く出やすい。

## 適性評価

直近5年の走のうち、父 × 母父（頭数が足りなければ父 × 母父の系統）の産駒について、
芝・ダート × 距離3区分（`APTITUDE_BANDS`）の3着以内率を、父の全産駒と比べる。障害は外す。

DBはJRAのレースだけなので、地方交流戦は含まれない（海外の出走も入っていない）。
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace

from keiba_analysis.shared.sire_index import FieldYear, HorseYear, IndexResult, NOT_STARTED, aei

MIN_HORSES = 30                    # これ未満の組み合わせは「参考」（薄く描く）
CROPS = 10
LEVEL_ORDER: tuple[tuple[int, int], ...] = ((0, 0), (1, 0), (0, 1), (1, 1), (2, 1), (1, 2), (2, 2))
PATERNAL_PATHS = ("ff", "fff", "ffff")       # 父の系統の祖（0代・1代・2代遡り）
MATERNAL_PATHS = ("mff", "mfff", "mffff")    # 母父の系統の祖
APTITUDE_YEARS = 5
APTITUDE_THIN_RUNS = 20
# (見出し, 下限m, 上限m)。1700m未満は短距離、2300m超は長距離に入れる（その間の距離は無い）
APTITUDE_BANDS: tuple[tuple[str, int, int], ...] = (
    ("短距離（〜1600m）", 0, 1699), ("中距離（1700〜2300m）", 1700, 2399), ("長距離（2400m〜）", 2400, 99999),
)
PATTERN_LABELS = ("父 × 母父", "父 × 母父の系統", "父の系統 × 母父", "父の系統 × 母父の系統")
GRADED = ("GI", "GII", "GIII")
_GROUP = "__nick__"                 # AEIを数えるときに、選んだ産駒の `sire` 欄へ入れる印

_STARTED = "COALESCE(re.finish_status, '') NOT IN ({})".format(
    ", ".join(f"'{s}'" for s in NOT_STARTED))


def crop_window(as_of: str, n: int = CROPS) -> tuple[int, int]:
    """直近 `n` 世代（いちばん若い出走世代＝2歳から遡る）。as_of が2026年なら2015〜2024年生。"""
    last = int(as_of[:4]) - 2
    return last - n + 1, last


def is_partial(crop: int, as_of: str) -> bool:
    """3歳シーズンが終わっていない世代（`sire_index.is_partial_crop` と同じ区切り）。"""
    return as_of < f"{crop + 3}-12-31"


# --- 入力の正規化 -------------------------------------------------------------------------------

def normalize_name(text: str) -> str:
    """表記の揺れを寄せる（全角・半角、大文字・小文字、空白、記号のII／2）。"""
    text = unicodedata.normalize("NFKC", text or "").strip().lower()
    text = text.replace("ⅱ", "ii").replace(" ", "").replace("'", "").replace("’", "").replace(".", "")
    return text


@dataclass(frozen=True)
class Stallion:
    key: str               # 名寄せキー（繁殖登録番号）
    name: str              # 代表名（`stallions.name`）
    aliases: tuple[str, ...]


def stallion_index(conn: sqlite3.Connection) -> list[Stallion]:
    """名寄せキーの付いた種牡馬すべて（代表名と別表記）。入力欄の候補と `resolve_stallion` に使う。"""
    aliases: dict[str, list[str]] = {}
    for key, name in conn.execute("SELECT sire_key, name FROM stallion_names"):
        aliases.setdefault(key, []).append(name)
    return [Stallion(key, name, tuple(sorted(set(aliases.get(key, [])) - {name})))
            for key, name in conn.execute("SELECT sire_key, name FROM stallions")]


def resolve_stallion(stallions: list[Stallion], text: str) -> list[Stallion]:
    """入力（カナでも英字でも）から種牡馬を探す。完全一致があればそれだけ、無ければ前方一致の候補。"""
    needle = normalize_name(text)
    if not needle:
        return []
    exact = [s for s in stallions if needle in {normalize_name(n) for n in (s.name, *s.aliases)}]
    if exact:
        return exact
    return [s for s in stallions
            if any(normalize_name(n).startswith(needle) for n in (s.name, *s.aliases))]


# --- DB取得 -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Foal:
    """産駒1頭。系統の判定に使う祖先IDと、成績の要約を持つ。"""

    horse_id: str
    horse_name: str
    sex: str | None
    crop: int
    sire: str | None                 # 父の名寄せキー
    bms: str | None                  # 母父の名寄せキー
    paternal: tuple                  # (父の父, その父, その父) の祖先ID
    maternal: tuple                  # (母父の父, その父, その父) の祖先ID
    starts: int = 0
    wins: int = 0
    top3: int = 0
    prize_man_yen: float = 0.0
    graded_wins: int = 0
    best_win: str | None = None      # いちばん格の高い勝ち鞍（「GI 日本ダービー」）


_FOALS_SQL = f"""
    WITH crop AS (
        SELECT h.horse_id, h.horse_name, h.sex,
               CAST(substr(h.birth_date, 1, 4) AS INTEGER) AS crop,
               h.sire_key, h.broodmare_sire_key
          FROM horses h
         WHERE CAST(substr(NULLIF(h.birth_date, ''), 1, 4) AS INTEGER) BETWEEN ? AND ?
    ),
    anc AS (
        SELECT a.horse_id,
               MAX(CASE WHEN a.path = 'ff'    THEN a.ancestor_no END) AS ff,
               MAX(CASE WHEN a.path = 'fff'   THEN a.ancestor_no END) AS fff,
               MAX(CASE WHEN a.path = 'ffff'  THEN a.ancestor_no END) AS ffff,
               MAX(CASE WHEN a.path = 'mff'   THEN a.ancestor_no END) AS mff,
               MAX(CASE WHEN a.path = 'mfff'  THEN a.ancestor_no END) AS mfff,
               MAX(CASE WHEN a.path = 'mffff' THEN a.ancestor_no END) AS mffff
          FROM horse_ancestors a
          JOIN crop c ON c.horse_id = a.horse_id
         WHERE a.path IN ('ff', 'fff', 'ffff', 'mff', 'mfff', 'mffff')
      GROUP BY a.horse_id
    ),
    perf AS (
        SELECT e.horse_id, COUNT(*) AS starts,
               SUM(re.finish_position = 1) AS wins,
               SUM(re.finish_position <= 3) AS top3,
               SUM(COALESCE(re.prize_man_yen, 0)) AS prize,
               SUM(re.finish_position = 1 AND ra.grade IN ('GI', 'GII', 'GIII')) AS graded_wins,
               MIN(CASE WHEN re.finish_position = 1 AND ra.grade IN ('GI', 'GII', 'GIII')
                        THEN CASE ra.grade WHEN 'GI' THEN 1 WHEN 'GII' THEN 2 ELSE 3 END
                             || ra.grade || ' ' || COALESCE(ra.race_name_plain, ra.race_name) END)
                                                                              AS best_win
          FROM entries e
          JOIN crop c     ON c.horse_id = e.horse_id
          JOIN races   ra ON ra.race_id = e.race_id
          JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
         WHERE {_STARTED}
      GROUP BY e.horse_id
    )
    SELECT c.*, anc.ff, anc.fff, anc.ffff, anc.mff, anc.mfff, anc.mffff,
           perf.starts, perf.wins, perf.top3, perf.prize, perf.graded_wins, perf.best_win
      FROM crop c
      JOIN perf ON perf.horse_id = c.horse_id
 LEFT JOIN anc  ON anc.horse_id = c.horse_id
"""


def foal_lines(conn: sqlite3.Connection, first_crop: int, last_crop: int) -> list[Foal]:
    """世代が範囲内で、JRAで1走以上した馬すべて（父・母父・系統の祖先ID・成績の要約）。"""
    return [
        Foal(
            horse_id=r["horse_id"], horse_name=r["horse_name"], sex=r["sex"], crop=r["crop"],
            sire=r["sire_key"], bms=r["broodmare_sire_key"],
            paternal=(r["ff"], r["fff"], r["ffff"]), maternal=(r["mff"], r["mfff"], r["mffff"]),
            starts=r["starts"] or 0, wins=r["wins"] or 0, top3=r["top3"] or 0,
            prize_man_yen=r["prize"] or 0.0, graded_wins=r["graded_wins"] or 0,
            best_win=r["best_win"][1:] if r["best_win"] else None,
        )
        for r in conn.execute(_FOALS_SQL, (first_crop, last_crop))
    ]


def ancestor_names(conn: sqlite3.Connection, ids: set[str]) -> dict[str, str]:
    """祖先ID → 名前（`pedigree_horses`。英字しか無い祖先は英字）。"""
    ids = [i for i in ids if i]
    out: dict[str, str] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ", ".join("?" * len(chunk))
        out.update(conn.execute(
            f"SELECT horse_no, name FROM pedigree_horses WHERE horse_no IN ({marks})", chunk).fetchall())
    return out


def aptitude_runs(conn: sqlite3.Connection, sire_key: str, since: str) -> list[dict]:
    """その父の産駒の、`since` 以降の走（芝・ダート、距離、着順、母父と母父の系統の祖先ID）。"""
    return [dict(r) for r in conn.execute(
        f"""
        SELECT e.horse_id, h.broodmare_sire_key AS bms, ra.surface, ra.distance_m, re.finish_position,
               (SELECT a.ancestor_no FROM horse_ancestors a
                 WHERE a.horse_id = e.horse_id AND a.path = 'mff')   AS mff,
               (SELECT a.ancestor_no FROM horse_ancestors a
                 WHERE a.horse_id = e.horse_id AND a.path = 'mfff')  AS mfff,
               (SELECT a.ancestor_no FROM horse_ancestors a
                 WHERE a.horse_id = e.horse_id AND a.path = 'mffff') AS mffff
          FROM entries e
          JOIN horses  h  ON h.horse_id = e.horse_id
          JOIN races   ra ON ra.race_id = e.race_id
          JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
         WHERE h.sire_key = ? AND ra.race_date >= ? AND {_STARTED}
           AND COALESCE(ra.surface, '') IN ('turf', 'dirt')
        """,
        (sire_key, since),
    )]


# --- 系統 ---------------------------------------------------------------------------------------

def _mode(values) -> str | None:
    counts = Counter(v for v in values if v)
    return counts.most_common(1)[0][0] if counts else None


@dataclass(frozen=True)
class Line:
    """系統。`level` は遡った代数（0＝父の父／母父の父が祖）。"""

    side: str                 # "sire"（父の系統）か "bms"（母父の系統）
    level: int
    root: str | None          # 祖の祖先ID
    name: str                 # 「ディープインパクト系*」

    @property
    def found(self) -> bool:
        return self.root is not None


def line_root(foals: list[Foal], key: str, side: str, level: int) -> str | None:
    """その種牡馬の産駒の血統表から、系統の祖のIDを決める（産駒の中でいちばん多いID）。"""
    if side == "sire":
        return _mode(f.paternal[level] for f in foals if f.sire == key)
    return _mode(f.maternal[level] for f in foals if f.bms == key)


def line_name(root_name: str | None, level: int) -> str:
    return f"{root_name or '不明'}系" + "*" * level


def in_line(foal: Foal, line: Line) -> bool:
    ids = foal.paternal if line.side == "sire" else foal.maternal
    return line.root is not None and ids[line.level] == line.root


# --- 指標 ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Stats:
    """産駒の束の成績。率は頭数が分母。"""

    horses: int
    winners: int
    top3: int
    aei: IndexResult

    @property
    def win_rate(self) -> float | None:
        return self.winners / self.horses if self.horses else None

    @property
    def top3_per_horse(self) -> float | None:
        return self.top3 / self.horses if self.horses else None

    def value(self, metric: str) -> float | None:
        if metric == "aei":
            return self.aei.value
        return getattr(self, metric)


METRICS = (("win_rate", "勝ち上がり率"), ("top3_per_horse", "1頭あたり複勝回数"), ("aei", "AEI"))


def group_aei(rows_by_horse: dict[str, list[HorseYear]], horse_ids: list[str],
              field: dict[int, FieldYear], min_horses: int) -> IndexResult:
    """選んだ産駒のAEI。`sire_index.aei` に、その産駒の行だけ `sire` 欄を印に替えて渡す（式は同じ）。"""
    picked = [replace(r, sire=_GROUP) for h in horse_ids for r in rows_by_horse.get(h, ())]
    return aei(picked, _GROUP, field=field, min_horses=min_horses)


def stats(foals: list[Foal], rows_by_horse: dict[str, list[HorseYear]],
          field: dict[int, FieldYear], aei_min_horses: int = 20) -> Stats:
    return Stats(
        horses=len(foals), winners=sum(f.wins > 0 for f in foals), top3=sum(f.top3 for f in foals),
        aei=group_aei(rows_by_horse, [f.horse_id for f in foals], field, aei_min_horses),
    )


def _ratio(value: float | None, base: float | None) -> float | None:
    return value / base if value is not None and base else None


# --- 4パターン ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Pattern:
    """4つの組み合わせの1つ。`ratios` は平均比、`bms_ratios` は母父平均比（指標ごと）。"""

    number: int
    label: str
    sire_side: str             # 「キズナ」か「ディープインパクト系」
    bms_side: str
    stats: Stats
    base_label: str            # 平均比の相手（「キズナの全産駒」）
    base: Stats
    bms_base_label: str
    bms_base: Stats
    ratios: dict
    bms_ratios: dict
    thin: bool                 # 頭数が min_horses 未満（参考）


@dataclass(frozen=True)
class Diagnosis:
    sire: Stallion
    bms: Stallion
    sire_line: Line
    bms_line: Line
    patterns: list[Pattern]
    crops: tuple[int, int]
    young_share: float | None   # 父 × 母父の産駒のうち、集計途中の世代の割合
    reason: str | None = None   # 診断できないときの理由


def choose_levels(foals: list[Foal], sire_roots: tuple, bms_roots: tuple,
                  min_horses: int = MIN_HORSES) -> tuple[int, int]:
    """パターン4（系統 × 系統）の頭数が `min_horses` 以上になる、いちばん浅い遡り方。

    どれでも足りなければ、いちばん頭数が多い遡り方を返す（結果は「参考」として薄く出る）。
    """
    best, best_n = (0, 0), -1
    for a, b in LEVEL_ORDER:
        if sire_roots[a] is None or bms_roots[b] is None:
            continue
        n = sum(1 for f in foals if f.paternal[a] == sire_roots[a] and f.maternal[b] == bms_roots[b])
        if n >= min_horses:
            return a, b
        if n > best_n:
            best, best_n = (a, b), n
    return best


def diagnose(foals: list[Foal], sire: Stallion, bms: Stallion, *,
             rows_by_horse: dict[str, list[HorseYear]], field: dict[int, FieldYear],
             names: dict[str, str], crops: tuple[int, int], as_of: str,
             min_horses: int = MIN_HORSES) -> Diagnosis:
    """4パターンの成績と平均比。`foals` は `foal_lines`、`names` は祖先ID → 名前。"""
    first, last = crops
    foals = [f for f in foals if first <= f.crop <= last]
    sire_roots = tuple(line_root(foals, sire.key, "sire", lv) for lv in range(3))
    bms_roots = tuple(line_root(foals, bms.key, "bms", lv) for lv in range(3))
    if not any(f.sire == sire.key for f in foals):
        return Diagnosis(sire, bms, Line("sire", 0, None, "—"), Line("bms", 0, None, "—"), [], crops,
                         None, reason=f"{sire.name}の産駒が直近{CROPS}世代にいません")
    if not any(f.bms == bms.key for f in foals):
        return Diagnosis(sire, bms, Line("sire", 0, None, "—"), Line("bms", 0, None, "—"), [], crops,
                         None, reason=f"{bms.name}を母父に持つ産駒が直近{CROPS}世代にいません")
    a, b = choose_levels(foals, sire_roots, bms_roots, min_horses)
    sire_line = Line("sire", a, sire_roots[a], line_name(names.get(sire_roots[a]), a))
    bms_line = Line("bms", b, bms_roots[b], line_name(names.get(bms_roots[b]), b))

    def pick(pred) -> list[Foal]:
        return [f for f in foals if pred(f)]

    by_sire = pick(lambda f: f.sire == sire.key)
    by_sire_line = pick(lambda f: in_line(f, sire_line))
    by_bms = pick(lambda f: f.bms == bms.key)
    by_bms_line = pick(lambda f: in_line(f, bms_line))

    def st(group: list[Foal]) -> Stats:
        return stats(group, rows_by_horse, field)

    bases = {"sire": st(by_sire), "sire_line": st(by_sire_line),
             "bms": st(by_bms), "bms_line": st(by_bms_line)}
    combos = (
        (sire.name, bms.name, by_sire, lambda f: f.bms == bms.key, "sire", "bms"),
        (sire.name, bms_line.name, by_sire, lambda f: in_line(f, bms_line), "sire", "bms_line"),
        (sire_line.name, bms.name, by_sire_line, lambda f: f.bms == bms.key, "sire_line", "bms"),
        (sire_line.name, bms_line.name, by_sire_line, lambda f: in_line(f, bms_line), "sire_line", "bms_line"),
    )
    base_labels = {"sire": f"{sire.name}の全産駒", "sire_line": f"{sire_line.name}の全産駒",
                   "bms": f"母父{bms.name}の全産駒", "bms_line": f"母父{bms_line.name}の全産駒"}
    patterns = []
    for i, (left, right, pool, pred, base_key, bms_key) in enumerate(combos):
        group = [f for f in pool if pred(f)]
        s = st(group)
        patterns.append(Pattern(
            number=i + 1, label=PATTERN_LABELS[i], sire_side=left, bms_side=right, stats=s,
            base_label=base_labels[base_key], base=bases[base_key],
            bms_base_label=base_labels[bms_key], bms_base=bases[bms_key],
            ratios={m: _ratio(s.value(m), bases[base_key].value(m)) for m, _ in METRICS},
            bms_ratios={m: _ratio(s.value(m), bases[bms_key].value(m)) for m, _ in METRICS},
            thin=s.horses < min_horses,
        ))
    exact = [f for f in by_sire if f.bms == bms.key]
    young = sum(is_partial(f.crop, as_of) for f in exact) / len(exact) if exact else None
    return Diagnosis(sire, bms, sire_line, bms_line, patterns, crops, young)


# --- 適性評価 -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class AptitudeCell:
    surface: str
    band: str
    starts: int
    top3: int
    base_starts: int
    base_top3: int
    thin: bool

    @property
    def rate(self) -> float | None:
        return self.top3 / self.starts if self.starts else None

    @property
    def base_rate(self) -> float | None:
        return self.base_top3 / self.base_starts if self.base_starts else None

    @property
    def diff(self) -> float | None:
        """父の全産駒との差（ポイント。0.05 ＝ 5ポイント高い）。"""
        if self.rate is None or self.base_rate is None:
            return None
        return self.rate - self.base_rate


def _band(distance: int | None) -> str | None:
    for label, low, high in APTITUDE_BANDS:
        if distance is not None and low <= distance <= high:
            return label
    return None


def aptitude(runs: list[dict], target, *, thin_runs: int = APTITUDE_THIN_RUNS) -> list[AptitudeCell]:
    """父の全産駒の走（`aptitude_runs`）のうち `target(run)` が真のものを、全産駒と比べる。"""
    cells = []
    for surface in ("turf", "dirt"):
        for label, _low, _high in APTITUDE_BANDS:
            base = [r for r in runs if r["surface"] == surface and _band(r["distance_m"]) == label]
            mine = [r for r in base if target(r)]
            top3 = lambda rs: sum(r["finish_position"] is not None and r["finish_position"] <= 3 for r in rs)
            cells.append(AptitudeCell(surface, label, len(mine), top3(mine), len(base), top3(base),
                                      len(mine) < thin_runs))
    return cells


def aptitude_target(diagnosis: Diagnosis, min_horses: int = MIN_HORSES):
    """適性評価の対象。父 × 母父が `min_horses` 頭以上ならそれ、足りなければ父 × 母父の系統。

    戻り値は (見出し, 走を選ぶ関数)。
    """
    exact = diagnosis.patterns[0] if diagnosis.patterns else None
    if exact and exact.stats.horses >= min_horses:
        key = diagnosis.bms.key
        return f"父 × 母父（{diagnosis.bms.name}）", lambda r: r["bms"] == key
    line = diagnosis.bms_line
    path = MATERNAL_PATHS[line.level]
    return f"父 × 母父の系統（{line.name}）", lambda r: r[path] == line.root


# --- 活躍馬 -------------------------------------------------------------------------------------

def active_horses(foals: list[Foal], diagnosis: Diagnosis, top: int = 50) -> list[dict]:
    """4パターンのどれかに入る産駒の活躍馬（重賞勝ち馬を先に、賞金の多い順）。

    `pattern` は、その馬が入るいちばん上（本馬に近い）の組み合わせの番号。
    """
    sire_key, bms_key = diagnosis.sire.key, diagnosis.bms.key
    checks = (
        lambda f: f.sire == sire_key and f.bms == bms_key,
        lambda f: f.sire == sire_key and in_line(f, diagnosis.bms_line),
        lambda f: in_line(f, diagnosis.sire_line) and f.bms == bms_key,
        lambda f: in_line(f, diagnosis.sire_line) and in_line(f, diagnosis.bms_line),
    )
    out = []
    for f in foals:
        number = next((i + 1 for i, check in enumerate(checks) if check(f)), None)
        if number is None or f.starts == 0:
            continue
        out.append({"pattern": number, "foal": f})
    out.sort(key=lambda x: (-(x["foal"].graded_wins > 0), -x["foal"].prize_man_yen))
    return out[:top]
