"""一口クラブごとの集計（dashboard/club_data.py）。

いちばん大事なのは**レース当時の馬主（`entries.owner_id`）で絞ること**。
`horses.owner_name` はJRA公式の「現在の馬主」なので、転売された馬で食い違う。
2022年以前の走（Target由来）はレース当時の馬主が無いので、書き出し時点の馬主
（`entries.owner_id_at_export`。馬ごとの値を各走に写したもの）で代用する。
"""

import pytest

from keiba_analysis.owner import club_data as cd

CLUB = "キャロットファーム"        # CLUBS に載っているクラブ
OTHER = "サンデーレーシング"


def _race(conn, race_id, *, grade=None, surface="turf", distance=1600, klass="1勝クラス",
          date_="2025-04-05", source="scrape"):
    conn.execute("INSERT OR IGNORE INTO venues (venue_code, venue_name) VALUES ('05', '東京')")
    conn.execute(
        "INSERT INTO races (race_id, race_date, venue_code, kaiji, nichime, race_no, grade,"
        " surface, distance_m, class_condition, fetched_at, updated_at, source)"
        " VALUES (?, ?, '05', 1, 1, 1, ?, ?, ?, ?, '', '', ?)",
        (race_id, date_, grade, surface, distance, klass, source),
    )


def _master(conn, owner_id, owner_name, trainer_id="T1", trainer_name="矢作芳人", stable="栗東"):
    conn.execute("INSERT OR IGNORE INTO owners (owner_id, owner_name, updated_at)"
                 " VALUES (?, ?, '')", (owner_id, owner_name))
    conn.execute("INSERT OR IGNORE INTO trainers (trainer_id, trainer_name, stable, updated_at)"
                 " VALUES (?, ?, ?, '')", (trainer_id, trainer_name, stable))


def _run(conn, race_id, horse_id, owner_id, *, name="ウマ", sire=None, finish=1, umaban=1,
         trainer_id="T1", prize=100.0, now_owner=None, age=3, weight=480):
    conn.execute(
        "INSERT OR IGNORE INTO horses (horse_id, horse_name, sex, sire, owner_name, updated_at)"
        " VALUES (?, ?, '牡', ?, ?, '')", (horse_id, name, sire, now_owner))
    conn.execute(
        "INSERT INTO entries (race_id, umaban, horse_id, age, horse_weight, owner_id, trainer_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (race_id, umaban, horse_id, age, weight, owner_id, trainer_id))
    conn.execute(
        "INSERT INTO results (race_id, umaban, horse_id, finish_position, prize_man_yen)"
        " VALUES (?, ?, ?, ?, ?)", (race_id, umaban, horse_id, finish, prize))


@pytest.fixture
def seeded(conn):
    """キャロットの2頭とサンデーの1頭。キャロットの1頭は**いま別の馬主**に移っている。"""
    _master(conn, "O1", CLUB)
    _master(conn, "O2", OTHER, trainer_id="T2", trainer_name="木村哲也", stable="美浦")
    _race(conn, "R1", klass="新馬", date_="2025-06-14")
    _race(conn, "R2", grade="GI", date_="2025-10-19")
    # H1: キャロットで走ったが、いまの馬主は個人（horses.owner_name が違う）
    _run(conn, "R1", "H1", "O1", name="カロッタ", sire="キズナ", finish=1,
         now_owner="(株)よその馬主", weight=470, age=2)
    _run(conn, "R2", "H1", "O1", name="カロッタ", sire="キズナ", finish=5, umaban=2)
    _run(conn, "R1", "H2", "O1", name="カロツー", sire="キズナ", finish=8, umaban=3, age=2,
         weight=450, prize=0.0)
    _run(conn, "R2", "H3", "O2", name="サンデーコ", sire="エピファネイア", finish=1, umaban=4,
         trainer_id="T2", prize=900.0)
    conn.commit()
    return conn


def test_list_clubs_returns_only_clubs_present_in_the_db(seeded):
    clubs = cd.list_clubs(seeded)
    assert [c["label"] for c in clubs] == [CLUB, OTHER]   # 頭数の多い順
    assert clubs[0]["owner_id"] == "O1" and clubs[0]["horses"] == 2
    assert clubs[0]["group"] == "社台"


def test_list_clubs_ignores_owners_that_are_not_clubs(conn):
    _master(conn, "O9", "松本好雄")          # CLUBS に載っていない個人馬主
    _race(conn, "R9")
    _run(conn, "R9", "H9", "O9")
    conn.commit()
    assert cd.list_clubs(conn) == []


def test_club_runs_uses_the_owner_at_the_time_of_the_race(seeded):
    """**転売された馬も、そのクラブで走ったぶんは数える。** ここが狂うと全部狂う。"""
    runs = cd.club_runs(seeded, "O1")
    assert {r["horse_name"] for r in runs} == {"カロッタ", "カロツー"}
    assert len(runs) == 3
    # いまの馬主（horses.owner_name）は別なのに、ちゃんとキャロットの走として拾えている
    moved = [r for r in runs if r["horse_name"] == "カロッタ"]
    assert len(moved) == 2


def test_club_summary_counts_win_up_rate_by_horses(seeded):
    """勝ち上がり率は**頭数が分母**（1勝でもした馬 ÷ 出走した馬）。"""
    rows = {r["label"]: r for r in cd.club_summary(seeded)}
    carrot = rows[CLUB]
    assert (carrot["horses"], carrot["starts"]) == (2, 3)
    assert carrot["winners"] == 1                       # H1だけが勝っている
    assert carrot["win_up_rate"] == pytest.approx(0.5)  # 2頭中1頭
    assert carrot["win_rate"] == pytest.approx(1 / 3)   # 勝率は出走が分母
    assert carrot["prize_per_horse"] == pytest.approx(200.0 / 2)
    assert carrot["graded_winners"] == 0                # GIを勝ったのはサンデーの馬
    assert rows[OTHER]["graded_winners"] == 1


def test_club_summary_is_sorted_by_prize_per_horse(seeded):
    rows = cd.club_summary(seeded)
    assert [r["label"] for r in rows] == [OTHER, CLUB]   # 900万 > 100万


def test_club_summary_counts_starts_by_surface(seeded):
    seeded.execute("UPDATE races SET surface = 'dirt' WHERE race_id = 'R2'")
    seeded.commit()
    carrot = {r["label"]: r for r in cd.club_summary(seeded)}[CLUB]
    assert (carrot["turf_starts"], carrot["dirt_starts"], carrot["jump_starts"]) == (2, 1, 0)
    assert carrot["turf_rate"] == pytest.approx(2 / 3)


def test_turf_rate_excludes_jump_from_the_denominator(seeded):
    """芝率は「芝 ÷ (芝+ダート)」。**障害は分母に入れない**（sire_runs.turf_share と同じ定義）。"""
    _race(seeded, "R3", surface="jump", distance=3000)
    _run(seeded, "R3", "H1", "O1", name="カロッタ", sire="キズナ", finish=3, umaban=5)
    seeded.commit()
    carrot = {r["label"]: r for r in cd.club_summary(seeded)}[CLUB]
    assert carrot["jump_starts"] == 1
    assert carrot["turf_rate"] == pytest.approx(1.0)      # 芝3走・ダート0走・障害1走


def test_turf_rate_matches_sire_runs_turf_share(seeded):
    """2つの画面で数字が食い違わないこと（クラブ比較とデビュー・成長・距離）。"""
    from keiba_analysis.shared import sire_runs

    seeded.execute("UPDATE races SET surface = 'dirt' WHERE race_id = 'R2'")
    seeded.commit()
    carrot = {r["label"]: r for r in cd.club_summary(seeded)}[CLUB]
    runs = cd.club_runs(seeded, "O1")
    assert carrot["turf_rate"] == pytest.approx(sire_runs.turf_share(runs))


def test_turf_rate_is_none_without_flat_runs(conn):
    _master(conn, "O1", CLUB)
    _race(conn, "R1", surface="jump", distance=3000)
    _run(conn, "R1", "H1", "O1")
    conn.commit()
    assert {r["label"]: r for r in cd.club_summary(conn)}[CLUB]["turf_rate"] is None


def test_by_trainer_and_by_stable(seeded):
    runs = cd.club_runs(seeded, "O1")
    trainers = cd.by_trainer(runs, min_horses=1)
    assert [t.label for t in trainers] == ["矢作芳人"]
    assert (trainers[0].horses, trainers[0].starts) == (2, 3)
    stables = {t.label: t for t in cd.by_stable(runs)}
    assert stables["栗東"].starts == 3 and stables["美浦"].starts == 0


def test_by_sire_only_counts_horses_with_a_known_sire(seeded):
    runs = cd.club_runs(seeded, "O1")
    assert [t.label for t in cd.by_sire(runs, min_horses=1)] == ["キズナ"]
    assert cd.sire_coverage(runs) == (2, 2)


def test_sire_coverage_reports_the_missing_ones(seeded):
    seeded.execute("UPDATE horses SET sire = NULL WHERE horse_id = 'H2'")
    seeded.commit()
    runs = cd.club_runs(seeded, "O1")
    assert cd.sire_coverage(runs) == (1, 2)             # 2頭中1頭だけ父が分かっている
    assert cd.by_sire(runs, min_horses=2) == []         # 2頭そろう種牡馬はいない


def test_shared_aggregations_work_on_club_runs(seeded):
    """`sire_runs` の集計が、クラブの走にもそのまま使えること（形が同じなので）。"""
    from keiba_analysis.shared import sire_runs

    runs = cd.club_runs(seeded, "O1")
    assert sire_runs.debut_months(runs) == {6: 2}        # 2頭とも6月の新馬戦
    assert sire_runs.early_debut_rate(runs) == pytest.approx(1.0)
    assert sire_runs.debut_weight(runs) == pytest.approx(460.0)
    assert sire_runs.turf_share(runs) == pytest.approx(1.0)
    by_age = {t.label: t for t in sire_runs.by_age(runs)}
    assert by_age["2歳"].starts == 2 and by_age["3歳"].starts == 1


# --- 2022年以前（Target由来）の走 ---------------------------------------------------------

def _owner_at_export(conn, horse_id, owner_id):
    """書き出し時点の馬主。keiba-data と同じく、その馬の全走に同じ値を入れる。"""
    conn.execute("UPDATE entries SET owner_id_at_export = ? WHERE horse_id = ?",
                 (owner_id, horse_id))


@pytest.fixture
def with_old_runs(seeded):
    """2010年の走を足す。レース当時の馬主（entries.owner_id）は空。

    - H7: 書き出し時点の馬主がキャロット → キャロットの走として数える
    - H8: 書き出し時点の馬主が分からない（1996年より前に生まれた馬）→ どこにも入らない
    - H1: 2023年以降はキャロットで走ったが、書き出し時点の馬主はサンデー（転売の逆向き）。
          レース当時の馬主がある走は、そちらを優先する
    """
    _race(seeded, "T1", date_="2010-06-12", klass="新馬", source="target")
    _run(seeded, "T1", "H7", None, name="ムカシロット", sire="キズナ", finish=1, prize=500.0,
         age=2, weight=440)
    _run(seeded, "T1", "H8", None, name="フメイウマ", finish=2, umaban=2, prize=200.0, age=2)
    _owner_at_export(seeded, "H7", "O1")
    _owner_at_export(seeded, "H1", "O2")
    seeded.commit()
    return seeded


def test_club_runs_use_the_owner_at_export_for_old_runs(with_old_runs):
    runs = cd.club_runs(with_old_runs, "O1")
    assert {r["horse_name"] for r in runs} == {"カロッタ", "カロツー", "ムカシロット"}
    assert len(runs) == 4
    assert {r["owner_id"] for r in runs} == {"O1"}


def test_the_owner_at_the_race_wins_over_the_owner_at_export(with_old_runs):
    """書き出し時点の馬主はレース当時の馬主が無い走にだけ使う。"""
    assert "カロッタ" not in {r["horse_name"] for r in cd.club_runs(with_old_runs, "O2")}


def test_club_summary_and_list_include_old_runs(with_old_runs):
    carrot = {r["label"]: r for r in cd.club_summary(with_old_runs)}[CLUB]
    assert (carrot["horses"], carrot["starts"], carrot["winners"]) == (3, 4, 2)
    assert carrot["prize_per_horse"] == pytest.approx(700.0 / 3)
    clubs = {c["label"]: c for c in cd.list_clubs(with_old_runs)}
    assert clubs[CLUB]["horses"] == 3
    assert clubs[OTHER]["horses"] == 1                    # H1 はサンデーに入らない


def test_since_narrows_club_runs(with_old_runs):
    assert len(cd.club_runs(with_old_runs, "O1", since="2023-01-01")) == 3
    carrot = {r["label"]: r for r in cd.club_summary(with_old_runs, since="2023-01-01")}[CLUB]
    assert (carrot["horses"], carrot["starts"]) == (2, 3)
    clubs = {c["label"]: c for c in cd.list_clubs(with_old_runs, since="2023-01-01")}
    assert clubs[CLUB]["horses"] == 2
