"""種牡馬のAEI（アーニングインデックス）とCPI（コンパラブルインデックス）を手元のDBから計算する。

定義はJBISのFAQによる（https://www.jbis.or.jp/help/faq/ 、2026-10-02 に確認）:

    AEI = (産駒の収得賞金 ÷ 産駒の出走頭数)
          ÷ (産駒が出走した期間の全出走馬収得賞金 ÷ 産駒が出走した期間の総出走頭数)
    CPI = (兄弟の総収得賞金 ÷ 兄弟の出走頭数) ÷ (同じ分母)

1.00が平均で、大きいほどよく稼いでいる。CPIは「総合、中央、地方でそれぞれ計算します。（平地のみ）」。
日本繋養の種牡馬の産駒が海外のみで出走した場合は、賞金・頭数ともカウントしない。

JRA公式の種牡馬リーディングのE・Iを読む `keiba_data.sire_data` と違い、ここは**レース結果から**
計算するので、1995年以降の好きな期間・好きな種牡馬で出せる（リーディング上位100頭に限られない）。

## 決めたこと（FAQに書かれていないところ）

- **賞金**: `results.prize_man_yen`（本賞金＋付加賞）。FAQの別の項に「JBISでは本賞金＋付加賞金で
  表示」とある。`target_horses.earned_prize_man_yen` はクラス分けに使う収得賞金（本賞金の3割ほど）で、
  ここでいう収得賞金とは別物なので使わない
- **出走頭数**: その年に出走した馬の数。同じ馬は1頭。競走中止は出走に数え、取消・除外は数えない
- **期間**: **年ごと**に計算する（JRA公式のE・Iと同じ区切りで、2024年の上位種牡馬を±0.1以内で再現できた）。
  何年かをまとめるときは `Σ賞金 ÷ Σ頭数`（年をまたいで走った馬は年の数だけ数える）を、
  「年ごとの全馬1頭平均を、その年の頭数で重み付けした平均」で割る（`keiba_data.sire_data` と同じ流儀）
- **障害**: AEIは既定で障害も含める（JRA公式のE・Iと同じ）。`flat_only=True` で平地だけ。
  CPIはFAQどおり平地だけで、分母も平地の全出走馬にする
- **兄弟（CPI）**: その種牡馬の産駒の母（`horses.dam_key`＝母の繁殖登録番号）が、**別の種牡馬との間に
  産んだ馬**だけ。本馬と全兄弟は除く（「その種牡馬に付けられた繁殖牝馬の質」を測るため）。
  父が分からない馬は全兄弟かどうか判断できないので除く。1頭の母に産駒が何頭いても兄弟は1回だけ数える。
  兄弟の走は期間で切らず、それぞれ走った年の全馬平均と比べる。`since` / `until` は
  「どの年に走った産駒の母を対象にするか」に効く

## 世代別（`crop_cpi_aei`）

産駒を**生年**で区切って、世代ごとに上と同じ式で計算する（新しい式は作らない）。

- **累計AEI**: その世代の産駒の、デビューから現時点までの全走（現役馬も含む）。全世代を
  `combine_crops` で合算すると、通算AEIと同じ値になる
- **CPI**: その世代の産駒の母が、別の種牡馬との間に産んだ馬（平地）。兄弟の走は世代で切らない。
  同じ母が何世代にも産駒を持つと兄弟が重なって数えられるので、合算しても通算CPIとは一致しない
- **is_partial**: 3歳シーズン（生年＋3年の12月31日）が終わっていない世代。値は変えず、
  画面で「まだ動く」世代を薄く描くための目印

## 出せないもの

- **地方・総合**: DBはJRAのレースしか持っていない（地方の賞金も、地方の全出走馬も無い）。
  `scope="local"` / `"total"` は値を出さず、理由を返す。中央の値は「中央のみ」と明示して使うこと
- **1995〜2002年**: 1996年より前に生まれた馬は父・母が分からないので、分子が欠けて低く出る。
  父（CPIは母）が分かる出走馬が98%に満たない年を含むときは、結果の `notes` に書く
- 海外の出走はDBに入っていないので、海外のみで走った産駒は自然に数えられない（FAQの規則と同じ結果）

## 名寄せ

種牡馬は名前ではなく名寄せキー（`horses.sire_key`。カナと英字の表記ゆれを keiba-data が
繁殖登録番号でつないだもの）で数える。キーの無い数十頭の父は `'name:' + 父名` で代える。
名前から引くときは `sire_runs.sire_key` を通す。母は `horses.dam_key`（繁殖登録番号そのもの。
同名の別馬がいるので名前では束ねない）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from keiba_analysis.shared.sire_runs import sire_key

# これ未満の頭数では値が跳ねるので出さない（`keiba_data.sire_data.MIN_FIELD_HORSES` と同じ）
MIN_HORSES = 20
# 父（CPIは母）が分かる出走馬がこの割合に満たない年は、値が低く出ると注記する
COVERAGE_WARNING = 0.98
# 出走に数えない（取消・除外）
NOT_STARTED = ("取消", "除外")

SCOPE_CENTRAL, SCOPE_LOCAL, SCOPE_TOTAL = "central", "local", "total"
NO_LOCAL_DATA = "地方競馬のデータがDBに無い（JRAのレースだけ）ので、地方・総合は算出できない"


@dataclass(frozen=True)
class HorseYear:
    """ある馬のある年の成績（計算の材料。1頭1年1行）。"""

    horse_id: str
    year: int
    sire: str | None          # 父の名寄せキー（キーが無ければ 'name:父名'、父不明は None）
    dam_no: str | None        # 母の繁殖登録番号（兄弟をたどる鍵）
    prize: float = 0.0        # 本賞金＋付加賞（万円）
    prize_flat: float = 0.0   # うち平地
    ran: bool = True          # その年に出走したか（取消・除外だけなら False）
    ran_flat: bool = True     # その年に平地を出走したか
    crop: int | None = None   # 生年（世代）。`birth_date` が無ければ「その年 − 馬齢」


@dataclass(frozen=True)
class FieldYear:
    """ある年の全出走馬の合計（分母の材料）。"""

    prize: float
    horses: int
    with_sire: int            # うち父が分かる馬
    with_dam: int             # うち母（繁殖登録番号）が分かる馬

    @property
    def per_horse(self) -> float | None:
        return self.prize / self.horses if self.horses else None


@dataclass(frozen=True)
class IndexResult:
    """AEI・CPIの結果。出せないときは `value` が None で、`reason` に理由が入る。"""

    value: float | None
    horses: int = 0                 # 頭数（年をまたいで走った馬は年の数だけ数える）
    distinct_horses: int = 0        # 頭数（同じ馬は1頭）
    prize_man_yen: float = 0.0      # 賞金の合計（万円）
    field_per_horse: float | None = None   # 分母（全出走馬の1頭平均賞金。年ごとの加重平均）
    reason: str | None = None
    notes: tuple[str, ...] = ()


_HORSE_YEARS_SQL = """
    SELECT e.horse_id AS horse_id,
           CAST(substr(ra.race_date, 1, 4) AS INTEGER) AS year,
           COALESCE(h.sire_key, 'name:' || NULLIF(h.sire, '')) AS sire,
           NULLIF(h.dam_key, '') AS dam_no,
           COALESCE(CAST(substr(NULLIF(h.birth_date, ''), 1, 4) AS INTEGER),
                    CAST(substr(ra.race_date, 1, 4) AS INTEGER) - MAX(e.age)) AS crop,
           SUM(CASE WHEN {started} THEN COALESCE(re.prize_man_yen, 0) ELSE 0 END) AS prize,
           SUM(CASE WHEN {started} AND {flat} THEN COALESCE(re.prize_man_yen, 0) ELSE 0 END)
                                                                           AS prize_flat,
           MAX(CASE WHEN {started} THEN 1 ELSE 0 END)                    AS ran,
           MAX(CASE WHEN {started} AND {flat} THEN 1 ELSE 0 END)       AS ran_flat
      FROM entries e NOT INDEXED
      JOIN races   ra ON ra.race_id = e.race_id
      JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
      JOIN horses  h  ON h.horse_id = e.horse_id
  GROUP BY e.horse_id, year
    HAVING ran = 1
""".format(
    started="COALESCE(re.finish_status, '') NOT IN ({})".format(
        ", ".join(f"'{s}'" for s in NOT_STARTED)),
    flat="COALESCE(ra.surface, '') <> 'jump'",
)


def horse_years(conn: sqlite3.Connection) -> list[HorseYear]:
    """全出走馬の「1頭1年1行」。AEI・CPIの材料（全種牡馬ぶんの計算に1回引けば足りる）。

    `entries` は NOT INDEXED で頭から読む（`sire_runs.local_stats` と同じ理由）。
    """
    return [
        HorseYear(
            horse_id=r["horse_id"], year=r["year"], sire=r["sire"], dam_no=r["dam_no"],
            prize=r["prize"] or 0.0, prize_flat=r["prize_flat"] or 0.0,
            ran=bool(r["ran"]), ran_flat=bool(r["ran_flat"]), crop=r["crop"],
        )
        for r in conn.execute(_HORSE_YEARS_SQL)
    ]


# --- 純粋関数（材料を受け取って計算するだけ） --------------------------------------------

def _year(value: int | str | None) -> int | None:
    """`2023` でも `'2023-01-01'` でも年にする。計算が年ごとなので、年より細かくは切れない。"""
    if value is None:
        return None
    return int(str(value)[:4])


def _in_period(year: int, since: int | None, until: int | None) -> bool:
    return (since is None or year >= since) and (until is None or year <= until)


def _ran(row: HorseYear, flat_only: bool) -> bool:
    return row.ran_flat if flat_only else row.ran


def _prize(row: HorseYear, flat_only: bool) -> float:
    return row.prize_flat if flat_only else row.prize


def field_by_year(rows: list[HorseYear], *, flat_only: bool = False) -> dict[int, FieldYear]:
    """年ごとの全出走馬の合計（AEI・CPIの分母）。"""
    sums: dict[int, list] = {}
    for row in rows:
        if not _ran(row, flat_only):
            continue
        total = sums.setdefault(row.year, [0.0, 0, 0, 0])
        total[0] += _prize(row, flat_only)
        total[1] += 1
        total[2] += row.sire is not None
        total[3] += row.dam_no is not None
    return {year: FieldYear(*total) for year, total in sums.items()}


def _coverage_notes(years: set[int], field: dict[int, FieldYear], attr: str, what: str) -> tuple[str, ...]:
    notes = []
    for year in sorted(years):
        f = field.get(year)
        if f and f.horses and getattr(f, attr) / f.horses < COVERAGE_WARNING:
            share = getattr(f, attr) / f.horses
            notes.append(f"{year}年は{what}が分かる出走馬が{share:.0%}しかなく、値が低めに出る")
    return tuple(notes)


def _index(picked: list[HorseYear], field: dict[int, FieldYear], *, flat_only: bool,
           min_horses: int, notes: tuple[str, ...], empty_reason: str) -> IndexResult:
    """選んだ「1頭1年」の行から指数を出す。分母は年ごとの全馬平均をその年の頭数で重み付けする。"""
    if not picked:
        return IndexResult(None, reason=empty_reason, notes=notes)
    horses = len(picked)
    distinct = len({r.horse_id for r in picked})
    prize = sum(_prize(r, flat_only) for r in picked)
    per_horse = [field[r.year].per_horse if r.year in field else None for r in picked]
    if any(p is None for p in per_horse):
        return IndexResult(None, horses, distinct, prize,
                           reason="分母（その年の全出走馬）が無い年がある", notes=notes)
    denominator = sum(per_horse) / horses
    base = dict(horses=horses, distinct_horses=distinct, prize_man_yen=prize,
                field_per_horse=denominator, notes=notes)
    if not denominator:
        return IndexResult(None, reason="分母（全出走馬の1頭平均賞金）が0", **base)
    if distinct < min_horses:
        return IndexResult(None, reason=f"出走頭数が{min_horses}頭未満（{distinct}頭）", **base)
    return IndexResult((prize / horses) / denominator, **base)


def sire_group(conn: sqlite3.Connection, sire_name: str) -> str:
    """種牡馬名を `HorseYear.sire` と同じ形（名寄せキー、無ければ 'name:父名'）にする。"""
    return sire_key(conn, sire_name) or f"name:{sire_name}"


def aei(rows: list[HorseYear], sire: str, *,
        since: int | str | None = None, until: int | str | None = None,
        flat_only: bool = False, min_horses: int = MIN_HORSES,
        field: dict[int, FieldYear] | None = None, crop: int | None = None) -> IndexResult:
    """AEI（中央）。`sire` はその種牡馬の名寄せキー（名前からは `sire_group` で作る）。

    `since` / `until` は年（`2023` か `'2023-01-01'`。年より細かくは切れない）。両端を含む。
    `field` は `field_by_year(rows, flat_only=...)` の結果を渡すと、全種牡馬ぶん回すときに速い。
    `crop` を渡すと、その年に生まれた産駒（世代）だけにする。
    """
    since, until = _year(since), _year(until)
    field = field if field is not None else field_by_year(rows, flat_only=flat_only)
    picked = [r for r in rows if r.sire == sire and _ran(r, flat_only)
              and _in_period(r.year, since, until) and (crop is None or r.crop == crop)]
    years = {r.year for r in picked}
    return _index(picked, field, flat_only=flat_only, min_horses=min_horses,
                  notes=_coverage_notes(years, field, "with_sire", "父"),
                  empty_reason="期間内に出走した産駒がいない")


def yearly_aei(rows: list[HorseYear], sire: str, *,
               flat_only: bool = False, min_horses: int = MIN_HORSES,
               field: dict[int, FieldYear] | None = None) -> dict[int, IndexResult]:
    """年ごとのAEI `{年: 結果}`（産駒が走った年だけ）。JRA公式のE・Iと同じ区切り。"""
    field = field if field is not None else field_by_year(rows, flat_only=flat_only)
    years = sorted({r.year for r in rows if r.sire == sire and _ran(r, flat_only)})
    return {
        year: aei(rows, sire, since=year, until=year, flat_only=flat_only,
                  min_horses=min_horses, field=field)
        for year in years
    }


def cpi(rows: list[HorseYear], sire: str, *,
        since: int | str | None = None, until: int | str | None = None,
        min_horses: int = MIN_HORSES, field: dict[int, FieldYear] | None = None,
        crop: int | None = None) -> IndexResult:
    """CPI（中央・平地のみ）。産駒の母が**別の種牡馬との間に産んだ馬**の稼ぎで測る。

    1. 期間内に出走した産駒の母（繁殖登録番号）を集める
    2. その母の産駒のうち、父が別の種牡馬の馬（＝半兄弟）を兄弟とする（父が分からない馬は除く）
    3. 兄弟の平地の全走を、走った年の全馬平均（平地）と比べる
    `field` は `field_by_year(rows, flat_only=True)` の結果。`crop` を渡すと、1の産駒を
    その年に生まれた世代に絞る（兄弟は世代で絞らない）。
    """
    since, until = _year(since), _year(until)
    field = field if field is not None else field_by_year(rows, flat_only=True)
    progeny = [r for r in rows if r.sire == sire and r.ran and _in_period(r.year, since, until)
               and (crop is None or r.crop == crop)]
    mares = {r.dam_no for r in progeny if r.dam_no}
    if not progeny:
        return IndexResult(None, reason="期間内に出走した産駒がいない")
    notes = _coverage_notes({r.year for r in progeny}, field, "with_dam", "母")
    if not mares:
        return IndexResult(None, reason="産駒の母（繁殖登録番号）が分からない", notes=notes)
    siblings = [r for r in rows if r.dam_no in mares and r.sire is not None
                and r.sire != sire and r.ran_flat]
    return _index(siblings, field, flat_only=True, min_horses=min_horses, notes=notes,
                  empty_reason="産駒の母に、別の種牡馬との間の産駒（平地を走った馬）がいない")


# --- 世代（産駒の生年）ごと --------------------------------------------------------------

@dataclass(frozen=True)
class CropIndex:
    """ある世代（同じ年に生まれた産駒）の累計AEIとCPI。出せない値は None で、理由が入る。

    累計AEIは**現役馬も含めた現時点までの累計**（通算AEIと同じ式を、その世代の産駒だけで計算）。
    CPIはその世代の産駒の母が、別の種牡馬との間に産んだ馬（平地）の稼ぎ（通算CPIと同じ定義）。
    `*_denominator` は「Σ その年の全出走馬の1頭平均賞金」（のべ頭数ぶん）で、世代を合算するときに使う。
    """

    crop_year: int
    cum_aei: float | None
    aei_starters: int               # のべ出走頭数（AEIの母数）
    aei_horses: int                 # 実頭数
    aei_prize_man_yen: float
    aei_denominator: float | None
    cpi: float | None
    cpi_siblings: int               # 兄弟の出走頭数（実頭数。CPIの母数）
    cpi_starters: int               # 兄弟ののべ出走頭数
    cpi_prize_man_yen: float
    cpi_denominator: float | None
    is_partial: bool                # 3歳シーズンが終わっていない世代（値は動く。画面で薄く描く目印）
    aei_reason: str | None = None
    cpi_reason: str | None = None
    notes: tuple[str, ...] = ()


def _denominator(result: IndexResult) -> float | None:
    if result.field_per_horse is None:
        return None
    return result.field_per_horse * result.horses


def is_partial_crop(crop_year: int, as_of: str) -> bool:
    """3歳シーズン（生年＋3年の12月31日）が終わっていない世代か。`as_of` は 'YYYY-MM-DD'。"""
    return as_of < f"{crop_year + 3}-12-31"


def crop_cpi_aei(rows: list[HorseYear], sire: str, *, as_of: str,
                 since: int | str | None = None, until: int | str | None = None,
                 flat_only: bool = False, min_horses: int = MIN_HORSES,
                 field: dict[int, FieldYear] | None = None,
                 flat_field: dict[int, FieldYear] | None = None) -> list[CropIndex]:
    """世代（産駒の生年）ごとの累計AEIとCPI。産駒が走った世代だけを古い順に返す。

    `since` / `until` は**世代**（生年）を絞る（`2015` か `'2015-01-01'`、両端を含む）。
    累計AEIの期間は切らない（デビューから現時点まで）。既定は障害込みで、画面の通算AEIと同じ。
    `as_of` はDBの最終レース日で、`is_partial` の判定にだけ使う。
    世代を合算するときは `combine_crops` を使う（のべ頭数で単純に重み付けすると、年ごとに
    分母が違うぶんずれる）。
    """
    since, until = _year(since), _year(until)
    field = field if field is not None else field_by_year(rows, flat_only=flat_only)
    flat_field = flat_field if flat_field is not None else field_by_year(rows, flat_only=True)
    # 何度も全行をなめないよう、その種牡馬の産駒と、その母の産駒（兄弟の候補）を先に取り出す
    mine = [r for r in rows if r.sire == sire]
    mares = {r.dam_no for r in mine if r.dam_no}
    family = mine + [r for r in rows if r.dam_no in mares and r.sire != sire]
    crops = sorted({r.crop for r in mine if r.crop is not None and _ran(r, flat_only)
                    and _in_period(r.crop, since, until)})
    out = []
    for crop in crops:
        a = aei(mine, sire, flat_only=flat_only, min_horses=min_horses, field=field, crop=crop)
        c = cpi(family, sire, min_horses=min_horses, field=flat_field, crop=crop)
        out.append(CropIndex(
            crop_year=crop, cum_aei=a.value, aei_starters=a.horses, aei_horses=a.distinct_horses,
            aei_prize_man_yen=a.prize_man_yen, aei_denominator=_denominator(a),
            cpi=c.value, cpi_siblings=c.distinct_horses, cpi_starters=c.horses,
            cpi_prize_man_yen=c.prize_man_yen, cpi_denominator=_denominator(c),
            is_partial=is_partial_crop(crop, as_of),
            aei_reason=a.reason, cpi_reason=c.reason,
            notes=tuple(dict.fromkeys((*a.notes, *c.notes))),
        ))
    return out


def combine_crops(crops: list[CropIndex]) -> tuple[float | None, float | None]:
    """世代を合算した (AEI, CPI)。Σ賞金 ÷ Σ分母で、値の出ない世代（頭数不足など）も材料は足す。

    AEIは、全世代を足すと**通算AEI（`aei`）と同じ値**になる。各世代の累計AEIを
    `aei_denominator` で重み付けした平均と同じこと。のべ出走頭数で重み付けすると、
    走った年によって分母（全馬の1頭平均賞金）が違うぶんずれる。
    CPIは通算CPI（`cpi`）とは一致しない。同じ母が何世代にも産駒を持つと、その兄弟が
    世代の数だけ数えられるため（通算CPIは母ごとに1回）。
    """
    def ratio(prize: float, denominator: float) -> float | None:
        return prize / denominator if denominator else None

    return (
        ratio(sum(c.aei_prize_man_yen for c in crops if c.aei_denominator),
              sum(c.aei_denominator or 0 for c in crops)),
        ratio(sum(c.cpi_prize_man_yen for c in crops if c.cpi_denominator),
              sum(c.cpi_denominator or 0 for c in crops)),
    )


# --- DBから一気に（画面用の便利関数） -----------------------------------------------------

def _unavailable(scope: str) -> IndexResult | None:
    if scope == SCOPE_CENTRAL:
        return None
    if scope in (SCOPE_LOCAL, SCOPE_TOTAL):
        return IndexResult(None, reason=NO_LOCAL_DATA)
    raise ValueError(f"scope は {SCOPE_CENTRAL!r} / {SCOPE_LOCAL!r} / {SCOPE_TOTAL!r} のどれか: {scope!r}")


def sire_aei(conn: sqlite3.Connection, sire_name: str, *, scope: str = SCOPE_CENTRAL,
             since: int | str | None = None, until: int | str | None = None,
             flat_only: bool = False, min_horses: int = MIN_HORSES,
             rows: list[HorseYear] | None = None) -> IndexResult:
    """その種牡馬のAEI。`rows` に `horse_years(conn)` を渡すと引き直さない（全体で数秒かかる）。"""
    if (missing := _unavailable(scope)) is not None:
        return missing
    rows = rows if rows is not None else horse_years(conn)
    return aei(rows, sire_group(conn, sire_name), since=since, until=until,
               flat_only=flat_only, min_horses=min_horses)


def sire_cpi(conn: sqlite3.Connection, sire_name: str, *, scope: str = SCOPE_CENTRAL,
             since: int | str | None = None, until: int | str | None = None,
             min_horses: int = MIN_HORSES, rows: list[HorseYear] | None = None) -> IndexResult:
    """その種牡馬のCPI（平地のみ）。`rows` は `sire_aei` と同じ。"""
    if (missing := _unavailable(scope)) is not None:
        return missing
    rows = rows if rows is not None else horse_years(conn)
    return cpi(rows, sire_group(conn, sire_name), since=since, until=until, min_horses=min_horses)


def last_race_date(conn: sqlite3.Connection) -> str | None:
    """結果の入っている最後のレースの日付（世代の `is_partial` の判定に使う）。"""
    row = conn.execute(
        "SELECT MAX(ra.race_date) FROM races ra "
        "WHERE EXISTS (SELECT 1 FROM results re WHERE re.race_id = ra.race_id)"
    ).fetchone()
    return row[0] if row else None


def sire_crop_cpi_aei(conn: sqlite3.Connection, sire_name: str, *,
                      since: int | str | None = None, until: int | str | None = None,
                      flat_only: bool = False, min_horses: int = MIN_HORSES,
                      rows: list[HorseYear] | None = None) -> list[CropIndex]:
    """その種牡馬の世代別の累計AEIとCPI（中央のみ）。`rows` は `sire_aei` と同じ。"""
    rows = rows if rows is not None else horse_years(conn)
    return crop_cpi_aei(rows, sire_group(conn, sire_name), as_of=last_race_date(conn) or "",
                        since=since, until=until, flat_only=flat_only, min_horses=min_horses)
