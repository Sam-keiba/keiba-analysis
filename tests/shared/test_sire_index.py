"""AEI・CPIの計算（shared/sire_index.py）。

手計算できる小さなデータで確かめる。純粋関数は `HorseYear` を直接組み、
DBから材料を引くところ（`horse_years`）だけ小さなDBを組む。名前はすべて架空。
純粋関数の `sire` は名寄せキーだが、ここでは種牡馬名をそのままキーとして使う。
"""

import pytest

from keiba_analysis.shared import sire_index as si
from keiba_analysis.shared.sire_index import HorseYear

SIRE, OTHER, THIRD = "テストシャイア", "ベツノシャイア", "サンバンメ"


def hy(horse_id, year=2024, sire=SIRE, prize=0.0, *, dam=None, flat=None, ran=True, ran_flat=None):
    """1頭1年の行。`flat` を省くと全部平地の賞金とみなす。"""
    return HorseYear(horse_id=horse_id, year=year, sire=sire, dam_no=dam, prize=prize,
                     prize_flat=prize if flat is None else flat, ran=ran,
                     ran_flat=ran if ran_flat is None else ran_flat)


# --- AEI ---------------------------------------------------------------------------------

def test_aei_is_one_when_progeny_earn_like_everyone():
    rows = [hy("A", prize=100), hy("B", prize=300),
            hy("X", sire=OTHER, prize=100), hy("Y", sire=OTHER, prize=300)]
    result = si.aei(rows, SIRE, min_horses=1)
    assert result.value == pytest.approx(1.0)
    assert (result.horses, result.distinct_horses, result.prize_man_yen) == (2, 2, 400)
    assert result.field_per_horse == pytest.approx(200.0)


def test_aei_is_two_when_progeny_earn_double():
    # 全4頭の平均は (400+400+0+0)/4 = 200、産駒2頭の平均は 400 → 2.00
    rows = [hy("A", prize=400), hy("B", prize=400),
            hy("X", sire=OTHER, prize=0), hy("Y", sire=OTHER, prize=0)]
    assert si.aei(rows, SIRE, min_horses=1).value == pytest.approx(2.0)


def test_aei_over_years_weights_each_years_field():
    """年をまたぐときは、年ごとの全馬平均を産駒の頭数で重み付けした平均が分母。"""
    rows = [
        # 2023年: 全馬平均 100、産駒1頭が200
        hy("A", 2023, prize=200), hy("X", 2023, sire=OTHER, prize=0),
        # 2024年: 全馬平均 300、産駒2頭（A は2年目＝のべで数える）が 300 と 300
        hy("A", 2024, prize=300), hy("B", 2024, prize=300), hy("Y", 2024, sire=OTHER, prize=300),
    ]
    result = si.aei(rows, SIRE, min_horses=1)
    # 分子 = (200+300+300)/3、分母 = (100*1 + 300*2)/3
    assert result.value == pytest.approx((800 / 3) / (700 / 3))
    assert (result.horses, result.distinct_horses) == (3, 2)


def test_aei_period_is_inclusive_and_accepts_dates():
    rows = [hy("A", 2023, prize=200), hy("X", 2023, sire=OTHER, prize=0),
            hy("A", 2024, prize=100), hy("Y", 2024, sire=OTHER, prize=100)]
    assert si.aei(rows, SIRE, since=2024, min_horses=1).value == pytest.approx(1.0)
    assert si.aei(rows, SIRE, until="2023-12-31", min_horses=1).value == pytest.approx(2.0)


def test_yearly_aei_returns_each_year():
    rows = [hy("A", 2023, prize=200), hy("X", 2023, sire=OTHER, prize=0),
            hy("A", 2024, prize=100), hy("Y", 2024, sire=OTHER, prize=100)]
    yearly = si.yearly_aei(rows, SIRE, min_horses=1)
    assert {y: r.value for y, r in yearly.items()} == {2023: pytest.approx(2.0), 2024: pytest.approx(1.0)}


def test_flat_only_drops_jump_prize_and_jump_only_horses():
    rows = [
        hy("A", prize=500, flat=100),                          # 平地100＋障害400
        hy("J", prize=600, flat=0, ran_flat=False),            # 障害だけ
        hy("X", sire=OTHER, prize=100),
    ]
    flat = si.aei(rows, SIRE, flat_only=True, min_horses=1)
    assert (flat.distinct_horses, flat.prize_man_yen) == (1, 100)
    assert flat.value == pytest.approx(1.0)
    both = si.aei(rows, SIRE, min_horses=1)
    assert both.distinct_horses == 2


# --- 出せないとき（例外にせず、理由を返す） --------------------------------------------

def test_no_progeny_returns_none_with_a_reason():
    result = si.aei([hy("X", sire=OTHER, prize=100)], SIRE, min_horses=1)
    assert result.value is None and result.reason
    assert result.horses == 0


def test_zero_denominator_returns_none():
    result = si.aei([hy("A", prize=0), hy("X", sire=OTHER, prize=0)], SIRE, min_horses=1)
    assert result.value is None and "0" in result.reason
    assert result.distinct_horses == 1


def test_too_few_horses_returns_counts_but_no_value():
    rows = [hy("A", prize=100), hy("X", sire=OTHER, prize=100)]
    result = si.aei(rows, SIRE, min_horses=2)
    assert result.value is None and "2頭未満" in result.reason
    assert (result.distinct_horses, result.prize_man_yen) == (1, 100)


def test_low_sire_coverage_is_noted():
    rows = [hy("A", 1998, prize=100)] + [hy(f"U{i}", 1998, sire=None, prize=100) for i in range(3)]
    result = si.aei(rows, SIRE, min_horses=1)
    assert result.value == pytest.approx(1.0)
    assert result.notes and "1998年" in result.notes[0]


@pytest.mark.parametrize("scope", [si.SCOPE_LOCAL, si.SCOPE_TOTAL])
def test_local_and_total_are_not_available(conn, scope):
    for result in (si.sire_aei(conn, SIRE, scope=scope), si.sire_cpi(conn, SIRE, scope=scope)):
        assert result.value is None
        assert result.reason == si.NO_LOCAL_DATA


def test_unknown_scope_is_an_error(conn):
    with pytest.raises(ValueError):
        si.sire_aei(conn, SIRE, scope="overseas")


# --- CPI ---------------------------------------------------------------------------------

def _family():
    """母M1の産駒: 本馬A（SIRE）・全兄弟B（SIRE）・半兄弟C（OTHER）・半兄弟D（THIRD）。
    母M2の産駒: 本馬E（SIRE）・半兄弟F（OTHER）。関係ない馬Zで全馬平均を整える。"""
    return [
        hy("A", prize=900, dam="M1"), hy("B", prize=900, dam="M1"),
        hy("C", sire=OTHER, prize=400, dam="M1"), hy("D", sire=THIRD, prize=0, dam="M1"),
        hy("E", prize=0, dam="M2"), hy("F", sire=OTHER, prize=200, dam="M2"),
        hy("Z", sire=OTHER, prize=0, dam="M9"),
    ]


def test_cpi_uses_only_half_siblings_by_other_sires():
    result = si.cpi(_family(), SIRE, min_horses=1)
    # 兄弟は C・D・F（本馬と全兄弟Bは除く）: (400+0+200)/3 = 200
    # 全馬の平地平均: (900+900+400+0+0+200+0)/7 = 2400/7
    assert result.distinct_horses == 3
    assert result.value == pytest.approx(200 / (2400 / 7))


def test_cpi_counts_each_sibling_once_even_with_two_progeny_from_the_same_mare():
    """M1 には本馬が2頭（A・B）いるが、C・D は1回だけ数える。"""
    assert si.cpi(_family(), SIRE, min_horses=1).horses == 3


def test_cpi_is_flat_only():
    rows = _family() + [hy("G", sire=OTHER, prize=800, flat=0, dam="M2", ran_flat=False)]
    result = si.cpi(rows, SIRE, min_horses=1)
    assert result.distinct_horses == 3                   # 障害だけの G は入らない


def test_cpi_skips_siblings_without_a_known_sire():
    rows = _family() + [hy("U", sire=None, prize=5000, dam="M1")]
    assert si.cpi(rows, SIRE, min_horses=1).distinct_horses == 3


def test_cpi_period_chooses_which_mares_count():
    """`since` で対象の産駒（＝母）が変わる。兄弟の走は期間で切らない。"""
    rows = [
        hy("A", 2010, prize=0, dam="M1"), hy("C", 2008, sire=OTHER, prize=300, dam="M1"),
        hy("E", 2024, prize=0, dam="M2"), hy("F", 2020, sire=OTHER, prize=100, dam="M2"),
        hy("Z", 2008, sire=OTHER, prize=300, dam="M9"), hy("W", 2020, sire=OTHER, prize=100, dam="M9"),
        hy("V", 2010, sire=OTHER, prize=0, dam="M8"), hy("Q", 2024, sire=OTHER, prize=0, dam="M7"),
    ]
    recent = si.cpi(rows, SIRE, since=2020, min_horses=1)
    assert recent.distinct_horses == 1                   # M2 の F だけ（2020年に走った）
    # F は2020年の全馬平均 (100+100)/2 = 100 と比べる
    assert recent.value == pytest.approx(1.0)
    assert si.cpi(rows, SIRE, min_horses=1).distinct_horses == 2


def test_cpi_without_siblings_returns_none():
    rows = [hy("A", prize=100, dam="M1"), hy("X", sire=OTHER, prize=100, dam="M9")]
    result = si.cpi(rows, SIRE, min_horses=1)
    assert result.value is None and result.reason


def test_cpi_without_known_mares_returns_none():
    rows = [hy("A", prize=100), hy("X", sire=OTHER, prize=100)]
    assert "母" in si.cpi(rows, SIRE, min_horses=1).reason


# --- DBから材料を引く ------------------------------------------------------------------------

def _race(conn, race_id, date_, surface="turf"):
    conn.execute("INSERT OR IGNORE INTO venues (venue_code, venue_name) VALUES ('05', '東京')")
    conn.execute(
        "INSERT INTO races (race_id, race_date, venue_code, kaiji, nichime, race_no, surface,"
        " distance_m, fetched_at, updated_at) VALUES (?, ?, '05', 1, 1, 1, ?, 1600, '', '')",
        (race_id, date_, surface))


def _run(conn, race_id, horse_id, *, sire=SIRE, key=None, prize=None, status=None, umaban=1,
         dam=None):
    """`key` は名寄せキー。省くと父名から作る（`K:父名`）。"""
    conn.execute("INSERT OR IGNORE INTO horses (horse_id, horse_name, sire, sire_key, dam_key,"
                 " updated_at) VALUES (?, ?, ?, ?, ?, '')",
                 (horse_id, horse_id, sire, key or f"K:{sire}", dam))
    conn.execute("INSERT INTO entries (race_id, umaban, horse_id, age) VALUES (?, ?, ?, 3)",
                 (race_id, umaban, horse_id))
    conn.execute(
        "INSERT INTO results (race_id, umaban, horse_id, finish_position, finish_status,"
        " prize_man_yen) VALUES (?, ?, ?, ?, ?, ?)",
        (race_id, umaban, horse_id, None if status else umaban, status, prize))


@pytest.fixture
def seeded(conn):
    _race(conn, "R1", "2024-04-01")
    _race(conn, "R2", "2024-05-01", surface="jump")
    _race(conn, "R3", "2025-04-01")
    _run(conn, "R1", "A", prize=500.0, dam="M1")
    _run(conn, "R2", "A", prize=300.0, umaban=2, dam="M1")          # 障害
    _run(conn, "R1", "B", status="中止", umaban=3)                  # 中止は出走に数える
    _run(conn, "R1", "C", status="取消", umaban=4)                  # 取消は数えない
    _run(conn, "R1", "X", sire=OTHER, prize=200.0, umaban=5, dam="M1")
    _run(conn, "R3", "A", prize=100.0)
    conn.commit()
    return conn


def test_horse_years_groups_runs_by_horse_and_year(seeded):
    rows = {(r.horse_id, r.year): r for r in si.horse_years(seeded)}
    assert set(rows) == {("A", 2024), ("A", 2025), ("B", 2024), ("X", 2024)}   # C は取消だけ
    a = rows[("A", 2024)]
    assert (a.prize, a.prize_flat, a.ran, a.ran_flat) == (800.0, 500.0, True, True)
    assert a.dam_no == "M1"
    assert rows[("B", 2024)].prize == 0.0


def test_sire_aei_and_cpi_from_the_db(seeded):
    rows = si.horse_years(seeded)
    # 2024年: 全馬 (800+0+200)/3、産駒 A・B (800+0)/2
    result = si.sire_aei(seeded, SIRE, since=2024, until=2024, min_horses=1, rows=rows)
    assert result.value == pytest.approx(400 / (1000 / 3))
    cpi = si.sire_cpi(seeded, SIRE, min_horses=1, rows=rows)
    assert cpi.distinct_horses == 1                       # X（母M1・別の父）


def test_horse_years_use_the_sire_key(seeded):
    """英字表記の父でも、名寄せキーが同じなら同じ種牡馬として数える。"""
    _race(seeded, "R4", "2024-06-01")
    _run(seeded, "R4", "E", sire="Test Sire", key=f"K:{SIRE}", prize=900.0)
    seeded.commit()
    rows = si.horse_years(seeded)
    assert {r.sire for r in rows if r.horse_id == "E"} == {f"K:{SIRE}"}
    by_kana = si.sire_aei(seeded, SIRE, since=2024, until=2024, min_horses=1, rows=rows)
    by_english = si.sire_aei(seeded, "Test Sire", since=2024, until=2024, min_horses=1, rows=rows)
    assert by_kana.distinct_horses == 3                   # A・B・E
    assert by_english == by_kana


def test_sire_without_a_key_falls_back_to_the_name(seeded):
    seeded.execute("UPDATE horses SET sire_key = NULL WHERE sire = ?", (OTHER,))
    seeded.commit()
    rows = si.horse_years(seeded)
    assert {r.sire for r in rows if r.horse_id == "X"} == {f"name:{OTHER}"}
    assert si.sire_aei(seeded, OTHER, min_horses=1, rows=rows).distinct_horses == 1


# --- 世代（産駒の生年）ごと --------------------------------------------------------------

AS_OF = "2026-09-27"


def cy(horse_id, year, crop, sire=SIRE, prize=0.0, **kw):
    """生年つきの1頭1年の行。"""
    return HorseYear(**{**hy(horse_id, year, sire, prize, **kw).__dict__, "crop": crop})


def test_crops_are_returned_oldest_first_and_since_narrows_them():
    rows = [cy("A", 2024, 2021, prize=100), cy("B", 2024, 2020, prize=100),
            cy("X", 2024, 2020, sire=OTHER, prize=100)]
    assert [c.crop_year for c in si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, min_horses=1)] \
        == [2020, 2021]
    assert [c.crop_year for c in si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, since=2021,
                                                 min_horses=1)] == [2021]


def test_crop_aei_is_one_or_two_against_the_field():
    rows = [cy("A", 2024, 2021, prize=100), cy("B", 2024, 2020, prize=400),
            cy("X", 2024, 2020, sire=OTHER, prize=100), cy("Y", 2024, 2020, sire=OTHER, prize=200)]
    # 全4頭の平均は 200。2021年生まれ(A)は 100 → 0.5、2020年生まれ(B)は 400 → 2.0
    crops = {c.crop_year: c for c in si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, min_horses=1)}
    assert crops[2021].cum_aei == pytest.approx(0.5)
    assert crops[2020].cum_aei == pytest.approx(2.0)


def test_crop_aei_is_cumulative_and_weights_each_years_field():
    """年をまたいで走った世代はのべで数え、年ごとの全馬平均を頭数で重み付けする。"""
    rows = [
        cy("A", 2023, 2020, prize=200), cy("X", 2023, 2019, sire=OTHER, prize=0),     # 2023年平均 100
        cy("A", 2024, 2020, prize=300), cy("B", 2024, 2020, prize=300),
        cy("Y", 2024, 2019, sire=OTHER, prize=300),                                   # 2024年平均 300
    ]
    crop = si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, min_horses=1)[0]
    assert (crop.aei_starters, crop.aei_horses) == (3, 2)
    assert crop.aei_denominator == pytest.approx(100 + 300 + 300)
    assert crop.cum_aei == pytest.approx(800 / 700)


def test_combined_crops_match_the_lifetime_aei():
    """全世代を合算すると、通算AEI（`aei`）と同じ値になる。"""
    rows = [
        cy("A", 2022, 2019, prize=500), cy("A", 2023, 2019, prize=100),
        cy("B", 2023, 2020, prize=50), cy("B", 2024, 2020, prize=700),
        cy("C", 2024, 2021, prize=0),
        cy("X", 2022, 2018, sire=OTHER, prize=100), cy("Y", 2023, 2018, sire=OTHER, prize=300),
        cy("Z", 2024, 2019, sire=OTHER, prize=50),
    ]
    crops = si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, min_horses=1)
    lifetime = si.aei(rows, SIRE, min_horses=1).value
    assert si.combine_crops(crops)[0] == pytest.approx(lifetime)
    # のべ頭数で単純に重み付けすると、年ごとの分母が違うぶんずれる
    by_starts = sum(c.cum_aei * c.aei_starters for c in crops) / sum(c.aei_starters for c in crops)
    assert by_starts != pytest.approx(lifetime)


def test_combined_crops_keep_thin_crops_in_the_total():
    """頭数不足で値の出ない世代も、合算の材料には入れる（通算と一致させるため）。"""
    rows = [cy("A", 2024, 2020, prize=400), cy("B", 2024, 2021, prize=0),
            cy("X", 2024, 2019, sire=OTHER, prize=200)]
    crops = si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, min_horses=2)
    assert all(c.cum_aei is None and "2頭未満" in c.aei_reason for c in crops)
    assert crops[0].aei_horses == 1
    assert si.combine_crops(crops)[0] == pytest.approx(si.aei(rows, SIRE, min_horses=1).value)


def test_crop_cpi_uses_only_that_crops_mares():
    rows = [
        cy("A", 2024, 2020, dam="M1", prize=0), cy("B", 2024, 2021, dam="M2", prize=0),
        cy("C", 2024, 2018, sire=OTHER, dam="M1", prize=400),        # A の半兄
        cy("D", 2024, 2019, sire=OTHER, dam="M2", prize=0),          # B の半兄
        cy("E", 2024, 2019, dam="M1", prize=900),                    # A の全兄（数えない）
    ]
    crops = {c.crop_year: c for c in si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, min_horses=1)}
    assert crops[2020].cpi_siblings == 1                             # C だけ
    # 全馬の平地平均 (0+0+400+0+900)/5 = 260、C は 400
    assert crops[2020].cpi == pytest.approx(400 / 260)
    assert crops[2021].cpi == pytest.approx(0.0)


def test_crop_cpi_is_flat_only():
    rows = [cy("A", 2024, 2020, dam="M1"),
            cy("J", 2024, 2018, sire=OTHER, dam="M1", prize=900, flat=0, ran_flat=False),
            cy("C", 2024, 2018, sire=OTHER, dam="M1", prize=100)]
    crop = si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, min_horses=1)[0]
    assert crop.cpi_siblings == 1


def test_siblings_shared_by_two_crops_are_counted_in_both():
    """同じ母の産駒が2世代にいると、兄弟は両方の世代に入る（合算が通算CPIとずれる理由）。"""
    rows = [cy("A", 2024, 2020, dam="M1"), cy("B", 2024, 2021, dam="M1"),
            cy("C", 2024, 2017, sire=OTHER, dam="M1", prize=300),
            cy("X", 2024, 2017, sire=OTHER, dam="M9", prize=100)]
    crops = si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, min_horses=1)
    assert [c.cpi_siblings for c in crops] == [1, 1]
    assert si.cpi(rows, SIRE, min_horses=1).distinct_horses == 1


def test_crop_without_siblings_returns_none_with_a_reason():
    rows = [cy("A", 2024, 2020, dam="M1", prize=100), cy("X", 2024, 2018, sire=OTHER, prize=100)]
    crop = si.crop_cpi_aei(rows, SIRE, as_of=AS_OF, min_horses=1)[0]
    assert crop.cpi is None and crop.cpi_reason
    assert crop.cum_aei == pytest.approx(1.0)


@pytest.mark.parametrize(("crop_year", "as_of", "partial"), [
    (2023, "2026-09-27", True),        # 3歳の12月31日（2026-12-31）より前
    (2023, "2026-12-31", False),
    (2022, "2026-09-27", False),
])
def test_is_partial_until_the_end_of_the_three_year_old_season(crop_year, as_of, partial):
    assert si.is_partial_crop(crop_year, as_of) is partial


def test_horse_years_take_the_crop_from_the_birth_date(seeded):
    seeded.execute("UPDATE horses SET birth_date = '2020-04-01' WHERE horse_id = 'A'")
    seeded.execute("UPDATE entries SET age = 4 WHERE horse_id = 'X'")   # 生年なし → 2024 − 4
    seeded.commit()
    rows = {(r.horse_id, r.year): r for r in si.horse_years(seeded)}
    assert rows[("A", 2024)].crop == 2020
    assert rows[("X", 2024)].crop == 2020


def test_sire_crop_cpi_aei_from_the_db(seeded):
    seeded.execute("UPDATE horses SET birth_date = '2021-03-01' WHERE horse_id IN ('A', 'B')")
    seeded.commit()
    crops = si.sire_crop_cpi_aei(seeded, SIRE, min_horses=1)
    assert [c.crop_year for c in crops] == [2021]
    assert crops[0].aei_horses == 2
    assert crops[0].is_partial is False          # 結果の最後は2025-04-01 → 2024年末で3歳が終わる
