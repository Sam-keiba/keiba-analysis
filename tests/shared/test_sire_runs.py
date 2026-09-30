"""種牡馬ごとの産駒成績の集計（dashboard/sire_runs.py）。

**手元DBの2023年以降のレースだけ**を数えるところを、小さなDBを組み立てて確かめる。
"""

import pytest

from keiba_analysis.shared import sire_runs as sr

SIRE, OTHER = "キズナ", "ロードカナロア"


def _race(conn, race_id, *, date_, surface="turf", distance=1600, grade=None,
          klass="1勝クラス", name="レース", venue="05", going="良"):
    conn.execute("INSERT OR IGNORE INTO venues (venue_code, venue_name) VALUES (?, ?)",
                 (venue, "東京"))
    conn.execute(
        "INSERT INTO races (race_id, race_date, venue_code, kaiji, nichime, race_no, race_name,"
        " grade, surface, distance_m, class_condition, going_turf, going_dirt, fetched_at,"
        " updated_at) VALUES (?, ?, ?, 1, 1, 1, ?, ?, ?, ?, ?, ?, ?, '', '')",
        (race_id, date_, venue, name, grade, surface, distance, klass, going, going),
    )


def _run(conn, race_id, horse_id, *, name, sire, sex="牡", age=3, finish=1, weight=480,
         prize=100.0, bms=None, breeder=None, umaban=1):
    conn.execute(
        "INSERT OR IGNORE INTO horses (horse_id, horse_name, sex, sire, broodmare_sire, breeder,"
        " updated_at) VALUES (?, ?, ?, ?, ?, ?, '')",
        (horse_id, name, sex, sire, bms, breeder),
    )
    conn.execute(
        "INSERT INTO entries (race_id, umaban, horse_id, age, horse_weight) VALUES (?, ?, ?, ?, ?)",
        (race_id, umaban, horse_id, age, weight),
    )
    conn.execute(
        "INSERT INTO results (race_id, umaban, horse_id, finish_position, prize_man_yen)"
        " VALUES (?, ?, ?, ?, ?)",
        (race_id, umaban, horse_id, finish, prize),
    )


@pytest.fixture
def seeded(conn):
    """キズナ産駒3頭ぶんの走と、比較用に別の種牡馬の産駒を1頭。"""
    _race(conn, "R1", date_="2024-06-15", klass="新馬", distance=1600)
    _race(conn, "R2", date_="2024-11-10", surface="dirt", distance=1800, going="重")
    _race(conn, "R3", date_="2025-04-20", grade="GI", name="第85回皐月賞", distance=2000)
    _race(conn, "R4", date_="2025-10-01", klass="新馬", distance=1400, venue="06")
    _run(conn, "R1", "H1", name="ウマイチ", sire=SIRE, age=2, finish=1, weight=470,
         prize=500.0, bms="キングカメハメハ", breeder="ノーザンファーム")
    _run(conn, "R2", "H1", name="ウマイチ", sire=SIRE, age=2, finish=8, weight=474, prize=0.0)
    _run(conn, "R3", "H1", name="ウマイチ", sire=SIRE, age=3, finish=5, prize=200.0)
    _run(conn, "R4", "H2", name="ウマニ", sire=SIRE, sex="セ", age=2, finish=3, weight=450,
         prize=50.0, bms="クロフネ", breeder="谷川牧場")
    _run(conn, "R3", "H3", name="ウマサン", sire=OTHER, age=3, finish=1, prize=900.0, umaban=2)
    conn.commit()
    return conn


def test_runs_where_lets_the_filter_be_swapped(seeded):
    """絞り込みを差し替えられる形になっていること（クラブ分析と共用しているため）。"""
    everyone = sr.runs_where(seeded, "1 = 1", ())
    assert len(everyone) == 5                    # キズナ産駒4走＋別の種牡馬1走
    assert sr.runs_where(seeded, "h.sire = ?", (SIRE,)) == sr.sire_runs(seeded, SIRE)
    # 調教師・馬主も1行1走の中に入っている（厩舎の使い方に要る）
    assert set(everyone[0]) >= {"owner_id", "trainer_name", "stable", "sire"}


def test_sire_runs_only_returns_that_sires_progeny(seeded):
    runs = sr.sire_runs(seeded, SIRE)
    assert len(runs) == 4
    assert {r["horse_name"] for r in runs} == {"ウマイチ", "ウマニ"}


def test_coverage_counts_progeny_and_the_whole_db(seeded):
    coverage = sr.coverage(seeded, sr.sire_runs(seeded, SIRE))
    assert (coverage.sire_horses, coverage.sire_runs) == (2, 4)
    assert (coverage.known, coverage.total) == (3, 3)      # 3頭とも父が入っている
    assert coverage.is_complete


def test_by_distance_splits_turf_and_dirt(seeded):
    runs = sr.sire_runs(seeded, SIRE)
    turf = {t.label: t for t in sr.by_distance(runs, "turf")}
    assert (turf["1600m"].starts, turf["1600m"].wins) == (1, 1)
    assert (turf["2000m"].starts, turf["2000m"].wins) == (1, 0)
    assert turf["2000m"].top5 == 1                          # 5着は掲示板に入る
    assert turf["〜1400m"].starts == 1                       # 1400mは「〜1400m」に入る
    dirt = {t.label: t for t in sr.by_distance(runs, "dirt")}
    assert dirt["1800m"].starts == 1 and dirt["1800m"].wins == 0


def test_by_surface_keeps_two_kinds_by_default(seeded):
    """既定は芝・ダートの2つ（距離適性・コース適性が左右2列に並べる作りのため）。"""
    assert [t.label for t in sr.by_surface(sr.sire_runs(seeded, SIRE))] == ["芝", "ダート"]


def test_by_surface_adds_jump_only_when_it_has_runs(seeded):
    runs = sr.sire_runs(seeded, SIRE)
    assert [t.label for t in sr.by_surface(runs, include_jump=True)] == ["芝", "ダート"]

    _race(seeded, "R9", date_="2025-05-05", surface="jump", distance=3000)
    _run(seeded, "R9", "H1", name="ウマイチ", sire=SIRE, finish=2)
    seeded.commit()
    jump = sr.by_surface(sr.sire_runs(seeded, SIRE), include_jump=True)
    assert [t.label for t in jump] == ["芝", "ダート", "障害"]
    assert jump[-1].starts == 1


def test_by_sex_and_gelding_rate(seeded):
    runs = sr.sire_runs(seeded, SIRE)
    by_sex = {t.label: t for t in sr.by_sex(runs)}
    assert by_sex["牡"].horses == 1 and by_sex["セ"].horses == 1 and by_sex["牝"].horses == 0
    assert sr.gelding_rate(runs) == pytest.approx(0.5)      # 2頭のうち1頭


def test_by_age_groups_five_and_over(seeded):
    by_age = {t.label: t for t in sr.by_age(sr.sire_runs(seeded, SIRE))}
    assert by_age["2歳"].starts == 3 and by_age["3歳"].starts == 1
    assert by_age["5歳以上"].starts == 0


def test_graded_wins_lists_only_wins_in_graded_races(seeded):
    runs = sr.sire_runs(seeded, SIRE)
    assert sr.graded_wins(runs) == []                       # 皐月賞は5着なので入らない


def test_top_progeny_is_ordered_by_prize(seeded):
    progeny = sr.top_progeny(sr.sire_runs(seeded, SIRE))
    assert [p["horse_name"] for p in progeny] == ["ウマイチ", "ウマニ"]
    assert progeny[0]["prize_man_yen"] == pytest.approx(700.0)
    assert (progeny[0]["starts"], progeny[0]["wins"], progeny[0]["top3"]) == (3, 1, 1)


def test_debut_metrics_use_the_maiden_race(seeded):
    runs = sr.sire_runs(seeded, SIRE)
    assert sr.debut_months(runs) == {6: 1, 10: 1}
    assert sr.early_debut_rate(runs) == pytest.approx(0.5)   # 6月デビューが1頭／2頭
    assert sr.debut_weight(runs) == pytest.approx(460.0)     # (470 + 450) / 2


def test_winning_distance_and_turf_share(seeded):
    runs = sr.sire_runs(seeded, SIRE)
    assert sr.winning_distance(runs, "turf") == pytest.approx(1600.0)
    assert sr.winning_distance(runs, "dirt") is None          # ダートは未勝利
    assert sr.turf_share(runs) == pytest.approx(0.75)         # 4走中3走が芝


def test_shadai_and_board_rate(seeded):
    runs = sr.sire_runs(seeded, SIRE)
    assert sr.shadai_rate(runs) == pytest.approx(0.5)         # ノーザンファームが1頭／2頭
    assert sr.board_rate(runs) == pytest.approx(0.75)         # 1着・5着・3着が掲示板


def test_classic_rate_matches_race_names_with_a_prefix(seeded):
    """DBのレース名は「第85回皐月賞」のように回数が付くので、後方一致で見る。"""
    runs = sr.sire_runs(seeded, SIRE)
    assert sr.classic_rate(runs) == pytest.approx(1.0)        # 3歳まで走ったのは1頭で、皐月賞に出た


def test_by_broodmare_sire_orders_by_progeny_count(seeded):
    tallies = sr.by_broodmare_sire(sr.sire_runs(seeded, SIRE))
    assert [t.label for t in tallies] == ["キングカメハメハ", "クロフネ"]
    assert tallies[0].starts == 3                             # 母の父は馬の属性なので全走に付く


def test_local_stats_covers_every_sire(seeded):
    everyone = sr.local_stats(seeded)
    assert set(everyone) == {SIRE, OTHER}
    assert sr.local_metric("turf_share", everyone[SIRE]) == pytest.approx(0.75)
    assert sr.local_metric("classic", everyone[SIRE]) == pytest.approx(1.0)
    assert sr.local_metric("gelding", everyone[SIRE]) == pytest.approx(0.5)
    assert sr.local_metric("shadai", everyone[SIRE]) == pytest.approx(0.5)


def test_local_field_merges_every_sire(seeded):
    everyone = sr.local_stats(seeded)
    # 全産駒5走のうち芝が4走（キズナ産駒3走＋ロードカナロア産駒1走）
    assert sr.local_field("turf_share", everyone) == pytest.approx(0.8)


def test_local_metric_is_none_without_material(seeded):
    assert sr.local_metric("turf_share", None) is None
    assert sr.local_metric("dirt_win_distance", sr.local_stats(seeded)[SIRE]) is None


def test_tally_marks_thin_buckets():
    thin = sr.Tally("1600m", horses=1, starts=sr.MIN_RUNS - 1, wins=1, top3=1, top5=1)
    thick = sr.Tally("1600m", horses=9, starts=sr.MIN_RUNS, wins=1, top3=1, top5=1)
    assert thin.is_thin and not thick.is_thin
    assert thick.win_rate == pytest.approx(1 / sr.MIN_RUNS)
    assert sr.Tally("なし").win_rate is None
