"""血統クロスの集計（dashboard/sire_cross.py）。

小さなDBを組んで、「持つ／持たない」の切り分けとクロス表記を確かめる。
集計は62マスそろった馬だけが対象なので、どの馬も `_fill` で残りのマスを埋める
（埋めたマスは `pedigree_horses` に無い番号なので、祖先の表には出てこない）。
"""

from itertools import product

import pytest

from keiba_analysis.shared import sire_cross as sc

SIRE = "キズナ"


def _race(conn, race_id, *, surface="turf"):
    conn.execute("INSERT OR IGNORE INTO venues (venue_code, venue_name) VALUES ('05', '東京')")
    conn.execute(
        "INSERT INTO races (race_id, race_date, venue_code, kaiji, nichime, race_no, surface,"
        " distance_m, fetched_at, updated_at) VALUES (?, '2025-04-05', '05', 1, 1, 1, ?, 1600, '', '')",
        (race_id, surface),
    )


def _horse(conn, horse_id, name, *, sex="牡", sire=SIRE, source="scrape", key=None):
    """`key` は名寄せキー。省くと父名から作る（`K:父名`）。"""
    conn.execute(
        "INSERT OR IGNORE INTO horses (horse_id, horse_name, sex, sire, updated_at, source, sire_key)"
        " VALUES (?, ?, ?, ?, '', ?, ?)", (horse_id, name, sex, sire, source, key or f"K:{sire}"))


def _run(conn, race_id, horse_id, *, finish=1, umaban=1):
    conn.execute("INSERT INTO entries (race_id, umaban, horse_id, age) VALUES (?, ?, ?, 3)",
                 (race_id, umaban, horse_id))
    conn.execute(
        "INSERT INTO results (race_id, umaban, horse_id, finish_position, prize_man_yen)"
        " VALUES (?, ?, ?, ?, 100.0)", (race_id, umaban, horse_id, finish))


def _ancestor(conn, horse_id, path, no, name, country=None, source="netkeiba"):
    conn.execute(
        "INSERT OR IGNORE INTO pedigree_horses (horse_no, name, country, updated_at)"
        " VALUES (?, ?, ?, '')", (no, name, country))
    conn.execute(
        "INSERT OR REPLACE INTO horse_ancestors (horse_id, path, generation, ancestor_no, source)"
        " VALUES (?, ?, ?, ?, ?)", (horse_id, path, len(path), no, source))


ALL_PATHS = ["".join(p) for n in range(1, 6) for p in product("fm", repeat=n)]   # 62マス


def _fill(conn, horse_id, *, source="netkeiba", leave_out=0):
    """まだ入っていないマスを、表に出ない祖先で埋める。`leave_out` マスだけ空けておく。"""
    for path in ALL_PATHS[leave_out:]:
        conn.execute(
            "INSERT OR IGNORE INTO horse_ancestors (horse_id, path, generation, ancestor_no, source)"
            " VALUES (?, ?, ?, 'unknown', ?)", (horse_id, path, len(path), source))


@pytest.fixture
def seeded(conn):
    """3頭。A と B は Sadler's Wells を持ち（Bは4代と5代のクロス）、C は持たない。"""
    for i, surface in enumerate(("turf", "dirt", "dirt"), start=1):
        _race(conn, f"R{i}", surface=surface)
    _horse(conn, "A", "ウマエー")
    _horse(conn, "B", "ウマビー", sex="牝")
    _horse(conn, "C", "ウマシー")
    _run(conn, "R1", "A", finish=1)
    _run(conn, "R2", "A", finish=5, umaban=2)
    _run(conn, "R1", "B", finish=2, umaban=3)
    _run(conn, "R1", "C", finish=8, umaban=4)
    _run(conn, "R3", "C", finish=9)
    # A: 5代に1箇所だけ / B: 4代と5代（＝4×5のクロス）/ C: 持たない（別の祖先だけ）
    _ancestor(conn, "A", "fffff", "sw", "Sadler's Wells", "米")
    _ancestor(conn, "B", "ffff", "sw", "Sadler's Wells", "米")
    _ancestor(conn, "B", "mmmmm", "sw", "Sadler's Wells", "米")
    _ancestor(conn, "C", "fffff", "nd", "Northern Dancer", "加")
    for horse_id in ("A", "B", "C"):
        _fill(conn, horse_id)
    conn.commit()
    return conn


def test_coverage_counts_only_horses_with_a_pedigree(seeded):
    _horse(seeded, "D", "ウマディー")       # 血統表が無い産駒
    seeded.execute("INSERT INTO entries (race_id, umaban, horse_id, age) VALUES ('R1', 9, 'D', 3)")
    seeded.execute(
        "INSERT INTO results (race_id, umaban, horse_id, finish_position) VALUES ('R1', 9, 'D', 3)")
    seeded.commit()
    coverage = sc.coverage(seeded, SIRE)
    assert (coverage.sire_horses, coverage.with_pedigree) == (4, 3)
    assert not coverage.is_complete


def test_ancestor_rows_split_haves_and_have_nots(seeded):
    rows = {r.ancestor: r for r in sc.ancestor_rows(seeded, SIRE, min_horses=1)}
    sadler = rows["Sadler's Wells"]
    assert sadler.horses == 2                       # A と B
    assert sadler.country == "米"
    assert sadler.with_tally.starts == 3            # Aの2走＋Bの1走
    assert sadler.without_tally.starts == 2         # Cの2走
    assert sadler.with_tally.wins == 1
    assert sadler.without_tally.wins == 0


def test_lift_compares_the_two_sides(seeded):
    sadler = next(r for r in sc.ancestor_rows(seeded, SIRE, min_horses=1)
                  if r.ancestor == "Sadler's Wells")
    # 持つ: 3走中2走が3着内(1着・2着) = 66.7% / 持たない: 0%
    assert sadler.with_tally.top3_rate == pytest.approx(2 / 3)
    assert sadler.without_tally.top3_rate == pytest.approx(0.0)
    assert sadler.lift is None                      # 比べる相手が0%なので倍率は出さない


def test_cross_rows_only_include_repeated_ancestors(seeded):
    rows = sc.cross_rows(seeded, SIRE, min_horses=1)
    assert [r.label for r in rows] == ["Sadler's Wells 4×5"]
    assert rows[0].horses == 1                      # Bだけ
    assert rows[0].cross == "4×5"


def test_cross_label_sorts_generations_ascending():
    assert sc.cross_label([5, 4]) == "4×5"
    assert sc.cross_label([5, 5, 4]) == "4×5×5"
    assert sc.cross_label([3]) == "3"


def test_filters_narrow_the_runs(seeded):
    turf = {r.ancestor: r for r in sc.ancestor_rows(seeded, SIRE, surface="turf", min_horses=1)}
    assert turf["Sadler's Wells"].with_tally.starts == 2     # AのR2(ダート)が落ちる
    assert turf["Sadler's Wells"].without_tally.starts == 1  # CのR3(ダート)も落ちる
    fillies = sc.ancestor_rows(seeded, SIRE, sex="牝", min_horses=1)
    assert {r.ancestor for r in fillies} == {"Sadler's Wells"}   # 牝はBだけ
    assert fillies[0].horses == 1


def test_min_horses_hides_thin_ancestors(seeded):
    assert sc.ancestor_rows(seeded, SIRE, min_horses=3) == []


def test_identical_ancestors_are_merged_into_one_row(seeded):
    """いつも一緒に現れる祖先は1行にまとめる（同じ成績を何度も繰り返さないため）。"""
    # A と B の両方に、Sadler's Wells と同じ位置関係で別の祖先を足す
    _ancestor(seeded, "A", "ffffm", "fp", "Flaming Page")
    _ancestor(seeded, "B", "fffm", "fp", "Flaming Page")
    _ancestor(seeded, "B", "mmmmf", "fp", "Flaming Page")
    seeded.commit()

    rows = sc.ancestor_rows(seeded, SIRE, min_horses=1)
    sadler = next(r for r in rows if "Sadler's Wells" in r.ancestors)
    assert set(sadler.ancestors) == {"Sadler's Wells", "Flaming Page"}
    assert "／" in sadler.label
    # まとめたので、同じ4頭を指す行が2つに分かれていない
    assert sum(1 for r in rows if "Flaming Page" in r.ancestors) == 1


def test_merged_label_shows_the_closest_ancestor_first(seeded):
    """代表は**いちばん近い代**に出てくる祖先（影響が大きく名前も知られている）。"""
    _ancestor(seeded, "A", "ff", "deep", "ディープインパクト")     # 2代目
    _ancestor(seeded, "B", "ff", "deep", "ディープインパクト")
    _ancestor(seeded, "A", "fmmmm", "far", "遠い祖先")            # 5代目（同じA・B）
    _ancestor(seeded, "B", "mffff", "far", "遠い祖先")
    seeded.commit()
    row = next(r for r in sc.ancestor_rows(seeded, SIRE, min_horses=1)
               if "ディープインパクト" in r.ancestors)
    assert row.ancestors[0] == "ディープインパクト"
    assert row.label.startswith("ディープインパクト")


def test_find_ancestor_searches_by_name(seeded):
    found = sc.find_ancestor(seeded, "Sadler")
    assert found == [{"name": "Sadler's Wells", "country": "米", "horses": 2}]
    assert sc.find_ancestor(seeded, "いない祖先") == []


def test_empty_when_the_sire_has_no_pedigree(seeded):
    assert sc.ancestor_rows(seeded, "いない種牡馬", min_horses=1) == []
    assert sc.cross_rows(seeded, "いない種牡馬", min_horses=1) == []


def test_full_cells_are_exactly_62():
    assert len(ALL_PATHS) == sc.FULL_CELLS == 62


def test_horses_with_missing_cells_are_left_out(seeded):
    """マスが欠けた馬（手元のデータで組んだ古い馬）は、持つ側にも持たない側にも入れない。"""
    _horse(seeded, "OLD", "ムカシウマ", source="target")
    _run(seeded, "R1", "OLD", finish=1, umaban=8)
    _ancestor(seeded, "OLD", "fffff", "sw", "Sadler's Wells", "米", source="local")
    _fill(seeded, "OLD", source="local", leave_out=1)      # 61マス
    seeded.commit()
    coverage = sc.coverage(seeded, SIRE)
    assert (coverage.sire_horses, coverage.with_pedigree) == (4, 3)
    rows = {r.ancestor: r for r in sc.ancestor_rows(seeded, SIRE, min_horses=1)}
    assert rows["Sadler's Wells"].horses == 2              # OLD は入らない
    assert rows["Sadler's Wells"].without_tally.starts == 2


def test_old_horses_with_a_full_local_pedigree_count(seeded):
    """手元のデータで組んだ血統表でも、62マスそろっていれば数える。"""
    _horse(seeded, "OLD", "ムカシウマ", source="target")
    _run(seeded, "R1", "OLD", finish=1, umaban=8)
    _ancestor(seeded, "OLD", "fffff", "sw", "Sadler's Wells", "米", source="local")
    _fill(seeded, "OLD", source="local")
    seeded.commit()
    coverage = sc.coverage(seeded, SIRE)
    assert (coverage.sire_horses, coverage.with_pedigree) == (4, 4)
    assert coverage.is_complete
    rows = {r.ancestor: r for r in sc.ancestor_rows(seeded, SIRE, min_horses=1)}
    assert rows["Sadler's Wells"].horses == 3


def test_progress_counts_only_netkeiba_pedigrees(seeded):
    """取り込みの進み具合は、2023年以降に走った馬のうち netkeiba の血統表がある馬で数える。"""
    _horse(seeded, "NEW", "アタラシイウマ")                # 2023年以降の馬・血統表まだ
    _run(seeded, "R1", "NEW", finish=5, umaban=7)
    _horse(seeded, "OLD", "ムカシウマ", source="target")   # 古い馬は分母に入らない
    _run(seeded, "R1", "OLD", finish=6, umaban=8)
    _fill(seeded, "OLD", source="local")
    seeded.commit()
    coverage = sc.coverage(seeded, SIRE)
    assert (coverage.known, coverage.total) == (3, 4)


def test_another_spelling_of_the_sire_is_included(seeded):
    """父が英字表記の産駒も、名寄せキーが同じなら同じ種牡馬として数える。"""
    _horse(seeded, "E", "エイジウマ", sire="Kizuna Test", key=f"K:{SIRE}")
    _run(seeded, "R2", "E", finish=1, umaban=6)
    _ancestor(seeded, "E", "fffff", "sw", "Sadler's Wells", "米")
    _fill(seeded, "E")
    seeded.commit()
    assert sc.coverage(seeded, SIRE).sire_horses == 4
    rows = {r.ancestor: r for r in sc.ancestor_rows(seeded, SIRE, min_horses=1)}
    assert rows["Sadler's Wells"].horses == 3              # A・B に E が加わる
