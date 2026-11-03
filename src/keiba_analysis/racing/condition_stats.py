"""条件を組み合わせた成績集計（競馬分析の「条件分析」タブ）。Streamlitに依存しない。

全150万走が対象になるので、Pythonに行を持ってこず**SQLで集計する**。率の定義は
`trainer_stats.Record` と同じ（テストで一致を確かめている）。

## 数え方

- **出走**: 取消・除外以外。中止・降着も、状態も着順も空の走（1995〜2020年に318走。タイムはある）も出走に含める
- **単勝回収率**: 勝った走の `results.win_odds` の合計 ÷ オッズの分かる出走数。全期間で出せる
- **複勝回収率**: `payouts` の複勝 ÷ 複勝が発売されたレースの出走数。**2023年以降だけ**
- **回収率の95%区間**: レースごとの合計を1単位にした比の推定量の標準誤差（線形化）から出す。
  同じレースの馬は結果が連動するので、馬ごとには数えない

## 発走前に分かるか

人気と単勝オッズは**確定値**で、発走前には分からない。`Filters.uses_final_odds` と
`axes_use_final_odds` で判定し、画面に注意を出す。
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, fields

from keiba_analysis.shared.race_name import LEGACY_CLASSES
from keiba_analysis.shared.sire_runs import MIN_RUNS

PAYOUT_START = "2023-01-01"     # payouts はこの日以降だけにある
NOT_STARTED = ("取消", "除外")
MAX_AXES = 2
UNKNOWN = "不明"

SURFACE_LABELS = {"turf": "芝", "dirt": "ダート", "jump": "障害"}
CLASSES = ("新馬", "未勝利", "1勝クラス", "2勝クラス", "3勝クラス", "オープン", "400万下")
FLAT_RACE = "平場"              # grade が空のレース
GRADES = ("GI", "GII", "GIII", "L", "JGI", "JGII", "JGIII", FLAT_RACE)
GOINGS = ("良", "稍重", "重", "不良")
SEXES = ("牡", "牝", "セ")

_J_VENUE = "JOIN venues v ON v.venue_code = ra.venue_code"
_J_HORSE = "LEFT JOIN horses h ON h.horse_id = e.horse_id"
_J_STALLION = "LEFT JOIN stallions st ON st.sire_key = h.sire_key"
_J_JOCKEY = "LEFT JOIN jockeys j ON j.jockey_id = e.jockey_id"
_J_TRAINER = "LEFT JOIN trainers t ON t.trainer_id = e.trainer_id"
# JOIN の順番は上の並び（st は h に、ほかは e / ra に依存する）
_JOIN_ORDER = (_J_VENUE, _J_HORSE, _J_STALLION, _J_JOCKEY, _J_TRAINER)


def _class_sql() -> str:
    """クラスの区分。旧呼称を今の呼称にし、「牝」などの付記を落とす（`race_name.modern_class` と同じ対応）。"""
    whens = [f"WHEN ra.class_condition LIKE '{old}%' THEN '{new}'" for old, new in LEGACY_CLASSES.items()]
    whens += [f"WHEN ra.class_condition LIKE '{name}%' THEN '{name}'" for name in CLASSES]
    return "CASE " + " ".join(whens) + " ELSE ra.class_condition END"


def _bands_sql(column: str, bands: tuple[tuple[str, float], ...], last: str) -> tuple[str, str]:
    """上限つきの帯の (ラベルのSQL, 並び順のSQL)。`bands` は (ラベル, この値未満)。NULL は NULL のまま。"""
    labels = " ".join(f"WHEN {column} < {upper} THEN '{label}'" for label, upper in bands)
    orders = " ".join(f"WHEN {column} < {upper} THEN {i}" for i, (_, upper) in enumerate(bands))
    guard = f"WHEN {column} IS NULL THEN NULL"
    return f"CASE {guard} {labels} ELSE '{last}' END", f"CASE {guard} {orders} ELSE {len(bands)} END"


_CLASS = _class_sql()
_SURFACE = ("CASE ra.surface " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in SURFACE_LABELS.items())
            + " ELSE ra.surface END")
_GOING = ("CASE ra.surface WHEN 'dirt' THEN ra.going_dirt ELSE ra.going_turf END")
_GRADE = f"COALESCE(NULLIF(ra.grade, ''), '{FLAT_RACE}')"
_DISTANCE_BAND = _bands_sql("ra.distance_m", (("〜1200m", 1201), ("1201〜1400m", 1401), ("1401〜1600m", 1601),
                                              ("1601〜1800m", 1801), ("1801〜2000m", 2001),
                                              ("2001〜2400m", 2401)), "2401m〜")
_ODDS_BAND = _bands_sql("res.win_odds", (("〜1.9倍", 2), ("2〜2.9倍", 3), ("3〜4.9倍", 5), ("5〜9.9倍", 10),
                                         ("10〜19.9倍", 20), ("20〜49.9倍", 50), ("50〜99.9倍", 100)), "100倍〜")
_FIELD_BAND = _bands_sql("ra.n_runners", (("〜8頭", 9), ("9〜12頭", 13), ("13〜16頭", 17)), "17頭〜")


def _in_order(values: tuple[str, ...], expr: str) -> str:
    """決まった順に並べるSQL（知らない値は最後）。"""
    whens = " ".join(f"WHEN '{v}' THEN {i}" for i, v in enumerate(values))
    return f"CASE {expr} {whens} ELSE {len(values)} END"


@dataclass(frozen=True)
class Axis:
    """集計の切り口。`key_sql` で束ね（同名の別人を混ぜない）、`label_sql` を見出しにする。

    SQLはこのファイルの固定の文字列だけで、画面から受け取った値は入らない。
    """
    key: str
    label: str
    key_sql: str
    label_sql: str
    order_sql: str
    joins: tuple[str, ...] = ()
    many: bool = False            # 区分が多い軸（騎手など）。出走の多い順に並べる
    final_odds: bool = False      # 確定オッズから決まる軸


def _simple(key: str, label: str, expr: str, order: str | None = None, *, final_odds: bool = False) -> Axis:
    return Axis(key, label, expr, expr, order or expr, final_odds=final_odds)


AXES: dict[str, Axis] = {a.key: a for a in (
    _simple("year", "年", "substr(ra.race_date, 1, 4)"),
    Axis("venue", "競馬場", "ra.venue_code", "v.venue_name", "ra.venue_code", (_J_VENUE,)),
    _simple("surface", "馬場種別", _SURFACE, _in_order(tuple(SURFACE_LABELS), "ra.surface")),
    _simple("distance_band", "距離帯", _DISTANCE_BAND[0], _DISTANCE_BAND[1]),
    _simple("distance", "距離", "ra.distance_m"),
    _simple("going", "馬場状態", _GOING, _in_order(GOINGS, _GOING)),
    _simple("class", "クラス", _CLASS, _in_order(CLASSES, _CLASS)),
    _simple("grade", "グレード", _GRADE, _in_order(GRADES, _GRADE)),
    _simple("field", "頭数", _FIELD_BAND[0], _FIELD_BAND[1]),
    _simple("waku", "枠番", "e.waku"),
    _simple("umaban", "馬番", "e.umaban"),
    _simple("popularity", "人気", "res.popularity", final_odds=True),
    _simple("odds_band", "単勝オッズ", _ODDS_BAND[0], _ODDS_BAND[1], final_odds=True),
    _simple("sex", "性別", "e.sex", _in_order(SEXES, "e.sex")),
    _simple("age", "年齢", "e.age"),
    Axis("jockey", "騎手", "e.jockey_id", "j.jockey_name", "e.jockey_id", (_J_JOCKEY,), many=True),
    Axis("trainer", "調教師", "e.trainer_id", "COALESCE(t.full_name, t.trainer_name)", "e.trainer_id",
         (_J_TRAINER,), many=True),
    Axis("sire", "種牡馬", "COALESCE(h.sire_key, h.sire)", "COALESCE(st.name, h.sire)",
         "COALESCE(h.sire_key, h.sire)", (_J_HORSE, _J_STALLION), many=True),
)}


@dataclass(frozen=True)
class Filters:
    """絞り込み。空のタプル・None は「絞らない」。frozen なのでキャッシュのキーに使える。"""
    start: str | None = None      # 'YYYY-MM-DD'
    end: str | None = None
    venues: tuple[str, ...] = ()
    surfaces: tuple[str, ...] = ()
    distance_min: int | None = None
    distance_max: int | None = None
    goings: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    grades: tuple[str, ...] = ()
    field_min: int | None = None
    field_max: int | None = None
    wakus: tuple[int, ...] = ()
    umaban_min: int | None = None
    umaban_max: int | None = None
    popularity_min: int | None = None
    popularity_max: int | None = None
    odds_min: float | None = None
    odds_max: float | None = None
    sexes: tuple[str, ...] = ()
    age_min: int | None = None
    age_max: int | None = None
    jockey_ids: tuple[str, ...] = ()
    trainer_ids: tuple[str, ...] = ()
    sire_keys: tuple[str, ...] = ()

    @property
    def uses_final_odds(self) -> bool:
        return any(v is not None for v in (self.popularity_min, self.popularity_max, self.odds_min, self.odds_max))

    def with_start_at_least(self, start: str) -> Filters:
        """開始日を `start` 以降にそろえた写し。"""
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        values["start"] = max(self.start, start) if self.start else start
        return Filters(**values)


def axes_use_final_odds(axes: tuple[str, ...]) -> bool:
    return any(AXES[a].final_odds for a in axes)


def build_where(filters: Filters) -> tuple[str, list]:
    """WHERE句とパラメータ。列はこの中で固定し、値はすべてパラメータで渡す。"""
    marks = ", ".join("?" for _ in NOT_STARTED)
    clauses = [f"COALESCE(res.finish_status, '') NOT IN ({marks})"]
    params: list = list(NOT_STARTED)

    def ranged(expr: str, low, high) -> None:
        if low is not None:
            clauses.append(f"{expr} >= ?")
            params.append(low)
        if high is not None:
            clauses.append(f"{expr} <= ?")
            params.append(high)

    def within(expr: str, values: tuple) -> None:
        if values:
            clauses.append(f"{expr} IN ({', '.join('?' for _ in values)})")
            params.extend(values)

    ranged("ra.race_date", filters.start, filters.end)
    within("ra.venue_code", filters.venues)
    within("ra.surface", filters.surfaces)
    ranged("ra.distance_m", filters.distance_min, filters.distance_max)
    within(_GOING, filters.goings)
    within(_CLASS, filters.classes)
    within(_GRADE, filters.grades)
    ranged("ra.n_runners", filters.field_min, filters.field_max)
    within("e.waku", filters.wakus)
    ranged("e.umaban", filters.umaban_min, filters.umaban_max)
    ranged("res.popularity", filters.popularity_min, filters.popularity_max)
    ranged("res.win_odds", filters.odds_min, filters.odds_max)
    within("e.sex", filters.sexes)
    ranged("e.age", filters.age_min, filters.age_max)
    within("e.jockey_id", filters.jockey_ids)
    within("e.trainer_id", filters.trainer_ids)
    within("h.sire_key", filters.sire_keys)
    return " AND ".join(clauses), params


def from_clause(filters: Filters, joins: tuple[str, ...] = ()) -> str:
    """結果・出馬・レースをつなぐFROM句。馬の表は要るときだけつなぐ（遅くなるので）。"""
    needed = set(joins)
    if filters.sire_keys:
        needed.add(_J_HORSE)
    extra = " ".join(j for j in _JOIN_ORDER if j in needed)
    return ("FROM results res"
            " JOIN entries e ON e.race_id = res.race_id AND e.umaban = res.umaban"
            f" JOIN races ra ON ra.race_id = res.race_id {extra}")


@dataclass(frozen=True)
class Ratio:
    """回収率（1.0＝100%）とその95%区間。`races` は計算に使ったレース数（区分内で重複しない）。"""
    bets: int = 0
    returned: float = 0.0
    races: int = 0
    sum_xx: float = 0.0
    sum_yy: float = 0.0
    sum_xy: float = 0.0

    @property
    def value(self) -> float | None:
        return self.returned / self.bets if self.bets else None

    @property
    def interval(self) -> tuple[float, float] | None:
        """比の推定量の線形化によるレース単位の95%区間。下限は0で止める。"""
        if self.races < 2 or not self.bets:
            return None
        roi = self.returned / self.bets
        residual = self.sum_yy - 2 * roi * self.sum_xy + roi * roi * self.sum_xx
        half = 1.96 * math.sqrt(max(residual, 0.0) * self.races / (self.races - 1)) / self.bets
        return max(roi - half, 0.0), roi + half


@dataclass(frozen=True)
class Stat:
    """ある区分の成績。率はすべて出走を分母にする（`trainer_stats.Record` と同じ）。"""
    label: str
    label2: str | None
    starts: int
    wins: int
    top2: int
    top3: int
    win_roi: Ratio
    place_roi: Ratio

    def _rate(self, n: int) -> float | None:
        return n / self.starts if self.starts else None

    @property
    def win_rate(self) -> float | None:
        return self._rate(self.wins)

    @property
    def top2_rate(self) -> float | None:
        return self._rate(self.top2)

    @property
    def top3_rate(self) -> float | None:
        return self._rate(self.top3)

    @property
    def is_thin(self) -> bool:
        return self.starts < MIN_RUNS


def _axis_columns(axes: tuple[Axis, ...]) -> str:
    """内側のSELECTの軸の列。軸が足りない分は NULL で埋めて、外側を1通りに書く。"""
    parts = []
    for i in range(MAX_AXES):
        if i < len(axes):
            a = axes[i]
            parts.append(f"{a.key_sql} AS k{i}, {a.label_sql} AS l{i}, {a.order_sql} AS o{i}")
        else:
            parts.append(f"NULL AS k{i}, NULL AS l{i}, NULL AS o{i}")
    return ", ".join(parts)


def aggregate(conn: sqlite3.Connection, filters: Filters, axes: tuple[str, ...] = ()) -> list[Stat]:
    """`axes`（`AXES` のキー。2つまで）ごとの成績。`axes` が空なら全体の1行（該当なしなら空）。

    並びは軸の自然な順。区分の多い軸（騎手など）が先頭なら出走の多い順。
    """
    if len(axes) > MAX_AXES:
        raise ValueError(f"集計軸は{MAX_AXES}つまで: {axes}")
    chosen = tuple(AXES[a] for a in axes)
    joins = tuple(j for a in chosen for j in a.joins)
    where, params = build_where(filters)
    sold = ("(ra.race_date >= ? AND EXISTS (SELECT 1 FROM payouts ps"
            " WHERE ps.race_id = res.race_id AND ps.bet_type = '複勝'))")
    sql = f"""
    WITH by_race AS (
      SELECT {_axis_columns(chosen)}, COUNT(*) AS starts,
        COALESCE(SUM(res.finish_position = 1), 0) AS wins,
        COALESCE(SUM(res.finish_position <= 2), 0) AS top2,
        COALESCE(SUM(res.finish_position <= 3), 0) AS top3,
        SUM(res.win_odds > 0) AS wx,
        SUM(CASE WHEN res.finish_position = 1 AND res.win_odds > 0 THEN res.win_odds ELSE 0 END) AS wy,
        SUM({sold}) AS px,
        COALESCE(SUM(pl.payout_yen), 0) / 100.0 AS py
      {from_clause(filters, joins)}
      LEFT JOIN payouts pl ON ra.race_date >= ? AND pl.race_id = res.race_id
        AND pl.bet_type = '複勝' AND pl.combination = CAST(res.umaban AS TEXT)
      WHERE {where}
      GROUP BY k0, k1, res.race_id
    )
    SELECT MIN(l0) AS l0, MIN(l1) AS l1, MIN(o0) AS o0, MIN(o1) AS o1,
      SUM(starts) AS starts, SUM(wins) AS wins, SUM(top2) AS top2, SUM(top3) AS top3,
      SUM(wx) AS wx, SUM(wy) AS wy, SUM(wx > 0) AS wn, SUM(wx * wx) AS wxx, SUM(wy * wy) AS wyy, SUM(wx * wy) AS wxy,
      SUM(px) AS px, SUM(py) AS py, SUM(px > 0) AS pn, SUM(px * px) AS pxx, SUM(py * py) AS pyy, SUM(px * py) AS pxy
    FROM by_race GROUP BY k0, k1
    """
    rows = [dict(zip(("l0", "l1", "o0", "o1", "starts", "wins", "top2", "top3", "wx", "wy", "wn", "wxx", "wyy", "wxy",
                      "px", "py", "pn", "pxx", "pyy", "pxy"), r))
            for r in conn.execute(sql, [PAYOUT_START, PAYOUT_START, *params])]
    if chosen and chosen[0].many:
        rows.sort(key=lambda r: (-r["starts"], _order_key(r["o1"])))
    else:
        rows.sort(key=lambda r: (_order_key(r["o0"]), _order_key(r["o1"])))
    return [Stat(
        label=_label(r["l0"]) if chosen else "全体",
        label2=_label(r["l1"]) if len(chosen) > 1 else None,
        starts=r["starts"], wins=r["wins"], top2=r["top2"], top3=r["top3"],
        win_roi=Ratio(r["wx"] or 0, r["wy"] or 0.0, r["wn"] or 0, r["wxx"] or 0.0, r["wyy"] or 0.0, r["wxy"] or 0.0),
        place_roi=Ratio(r["px"] or 0, r["py"] or 0.0, r["pn"] or 0, r["pxx"] or 0.0, r["pyy"] or 0.0, r["pxy"] or 0.0),
    ) for r in rows]


def _label(value) -> str:
    return UNKNOWN if value is None else str(value)


def _order_key(value) -> tuple:
    """NULL（不明）は最後。数と文字が混ざっても比べられるようにする。"""
    if value is None:
        return (2, 0, "")
    return (0, value, "") if isinstance(value, (int, float)) else (1, 0, str(value))


def total(conn: sqlite3.Connection, filters: Filters) -> Stat | None:
    """条件に合う走の全体の成績。該当なしなら None。"""
    rows = aggregate(conn, filters)
    return rows[0] if rows else None


def matching_runs(conn: sqlite3.Connection, filters: Filters, limit: int = 200) -> list[dict]:
    """条件に合う走を新しい順に。"""
    where, params = build_where(filters)
    joins = (_J_VENUE, _J_HORSE, _J_JOCKEY)
    sql = f"""
    SELECT ra.race_date, v.venue_name, ra.race_no, COALESCE(ra.race_name_plain, ra.race_name) AS race_name,
      {_SURFACE} AS surface, ra.distance_m, {_GOING} AS going, {_CLASS} AS class_name,
      e.waku, e.umaban, h.horse_name, j.jockey_name, res.popularity, res.win_odds,
      res.finish_position, res.finish_status
    {from_clause(filters, joins)}
    WHERE {where}
    ORDER BY ra.race_date DESC, ra.race_id DESC, e.umaban
    LIMIT ?
    """
    cursor = conn.execute(sql, [*params, limit])
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def date_range(conn: sqlite3.Connection) -> tuple[str, str]:
    """結果のあるレースの (最初の日, 最後の日)。"""
    row = conn.execute("SELECT MIN(race_date), MAX(race_date) FROM races").fetchone()
    return row[0], row[1]


def venues(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in conn.execute("SELECT venue_code, venue_name FROM venues ORDER BY venue_code")]


def _choice_rows(cursor) -> list[tuple[str, str]]:
    return [(r[0], f"{r[1]}（{r[2]:,}走）") for r in cursor]


def jockey_choices(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(騎手ID, 見出し)。出走の多い順。同名の別人は走数で見分ける。"""
    return _choice_rows(conn.execute(
        "SELECT e.jockey_id, COALESCE(j.jockey_name, e.jockey_id), COUNT(*) AS n FROM entries e"
        " LEFT JOIN jockeys j ON j.jockey_id = e.jockey_id WHERE e.jockey_id IS NOT NULL"
        " GROUP BY e.jockey_id ORDER BY n DESC"))


def trainer_choices(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(調教師ID, 見出し)。出走の多い順。"""
    return _choice_rows(conn.execute(
        "SELECT e.trainer_id, COALESCE(t.full_name, t.trainer_name, e.trainer_id), COUNT(*) AS n FROM entries e"
        " LEFT JOIN trainers t ON t.trainer_id = e.trainer_id WHERE e.trainer_id IS NOT NULL"
        " GROUP BY e.trainer_id ORDER BY n DESC"))


def sire_choices(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(名寄せキー, 見出し)。産駒の出走の多い順。"""
    return _choice_rows(conn.execute(
        "SELECT h.sire_key, st.name, COUNT(*) AS n FROM entries e JOIN horses h ON h.horse_id = e.horse_id"
        " JOIN stallions st ON st.sire_key = h.sire_key GROUP BY h.sire_key ORDER BY n DESC"))
