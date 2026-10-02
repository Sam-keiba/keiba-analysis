"""厩舎分析のDB取得（racing/trainer_data.py）。小さなDBを組んで、SQLの数え方を確かめる。名前はすべて架空。"""

from keiba_analysis.racing import trainer_data as td

NOW = "2026-01-01 00:00:00"
T, U = "10001", "10002"


def _setup(conn):
    conn.execute("INSERT INTO jockeys (jockey_id, jockey_name, updated_at) VALUES ('J1', 'テスト騎手', ?)", (NOW,))
    conn.executemany("INSERT INTO trainers (trainer_id, trainer_name, stable, updated_at) VALUES (?, ?, ?, ?)",
                     [(T, "テスト一郎", "美浦", NOW), (U, "テスト二郎", "栗東", NOW)])
    conn.executemany("INSERT INTO horses (horse_id, horse_name, sex, birth_date, dam_key, updated_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     [("A", "エーホース", "牡", "2021-03-01", "D1", NOW),
                      ("B", "ビーホース", "牝", "2021-04-01", "D2", NOW)])
    races = [("R1", "2023-07-01", "05"), ("R2", "2023-08-01", "09"), ("R3", "2024-02-01", "06"),
             ("R4", "2024-03-01", "06")]
    conn.executemany("INSERT INTO races (race_id, race_date, venue_code, kaiji, nichime, race_no, "
                     "surface, distance_m, fetched_at, updated_at) "
                     "VALUES (?, ?, ?, 1, 1, 1, 'turf', 1600, ?, ?)",
                     [(r, d, v, NOW, NOW) for r, d, v in races])
    runs = [  # (レース, 馬番, 馬, 調教師, 着順, 賞金, 状態)
        ("R1", 1, "A", T, 1, 700, None),
        ("R2", 1, "A", T, 3, 200, None),
        ("R2", 2, "B", T, None, 0, "取消"),      # 取消は出走に数えない
        ("R3", 1, "A", U, 2, 300, None),         # 転厩（T → U）
        ("R4", 1, "B", T, 1, 500, None),
    ]
    for race, umaban, horse, trainer, pos, prize, status in runs:
        conn.execute("INSERT INTO entries (race_id, umaban, horse_id, age, jockey_id, trainer_id) "
                     "VALUES (?, ?, ?, 2, 'J1', ?)", (race, umaban, horse, trainer))
        conn.execute("INSERT INTO results (race_id, umaban, horse_id, finish_position, finish_status, "
                     "prize_man_yen) VALUES (?, ?, ?, ?, ?, ?)", (race, umaban, horse, pos, status, prize))
    conn.commit()


def test_years_exclude_scratched_and_split_by_trainer(conn):
    _setup(conn)
    rows = {(r["trainer_id"], r["year"]): r for r in td.all_trainer_years(conn)}
    assert (rows[(T, 2023)]["starts"], rows[(T, 2023)]["wins"], rows[(T, 2023)]["prize_man_yen"]) == (2, 1, 900)
    assert rows[(U, 2024)]["starts"] == 1 and rows[(T, 2024)]["wins"] == 1


def test_window_runs_carry_previous_and_next_trainer(conn):
    _setup(conn)
    runs = {(r["horse_id"], r["race_date"]): r for r in td.window_runs(conn, "2023-01-01")}
    assert runs[("A", "2023-08-01")]["prev_date"] == "2023-07-01"
    assert runs[("A", "2023-08-01")]["next_trainer"] == U
    assert runs[("A", "2024-02-01")]["prev_trainer"] == T
    # B の取消は並びから外れるので、R4 の前走は無い
    assert runs[("B", "2024-03-01")]["prev_date"] is None
    assert ("B", "2023-08-01") not in runs


def test_trainer_horse_years_split_by_trainer_and_carry_crop(conn):
    _setup(conn)
    rows = {(r.horse_id, r.year, r.sire): r for r in td.trainer_horse_years(conn)}
    assert rows[("A", 2023, T)].prize == 900 and rows[("A", 2023, T)].crop == 2021
    assert rows[("A", 2024, U)].prize == 300 and rows[("A", 2024, U)].dam_no == "D1"
    assert ("B", 2023, T) not in rows          # 取消だけの年は入らない


def test_crop_horses_summary(conn):
    _setup(conn)
    horses = {h["horse_id"]: h for h in td.crop_horses(conn, 2021, 2021)}
    assert set(horses["A"]["trainers"]) == {T, U}          # 走らせた厩舎（順は問わない）
    assert (horses["A"]["debut_trainer"], horses["A"]["first_win_n"]) == (T, 1)
    assert horses["B"]["debut_date"] == "2024-03-01"       # 取消はデビューに数えない
    assert td.crop_horses(conn, 2010, 2020) == []


def test_list_trainers_and_latest_runs(conn):
    _setup(conn)
    conn.execute("UPDATE trainers SET full_name = 'テスト 一郎太', kana = 'テスト イチロウタ' WHERE trainer_id = ?", (T,))
    trainers = td.list_trainers(conn)
    assert [t["trainer_id"] for t in trainers] == [T, U]
    assert trainers[0]["trainer_name"] == "テスト 一郎太" and trainers[0]["short_name"] == "テスト一郎"
    assert trainers[1]["trainer_name"] == "テスト二郎"          # 名鑑に無ければ4文字の名前
    latest = td.latest_runs(conn, ["A", "B"])
    assert latest["A"]["trainer_id"] == U and latest["B"]["race_date"] == "2024-03-01"


def test_stalls_use_latest_announcement(conn):
    _setup(conn)
    conn.executemany("INSERT INTO trainer_stalls (trainer_id, effective_date, stalls, stable, name_in_source, "
                     "updated_at) VALUES (?, ?, ?, '美浦', 'テスト 一郎', ?)",
                     [(T, "2025-03-01", 18, NOW), (T, "2026-03-04", 20, NOW)])
    assert td.stalls(conn) == ("2026-03-04", {T: 20})


def test_window_runs_carry_kinryo_mark(conn):
    _setup(conn)
    conn.execute("UPDATE entries SET kinryo_mark = '▲' WHERE race_id = 'R1'")
    runs = {r["race_date"]: r for r in td.window_runs(conn, "2023-01-01") if r["horse_id"] == "A"}
    assert runs["2023-07-01"]["kinryo_mark"] == "▲" and runs["2023-08-01"]["kinryo_mark"] is None
