"""答え合わせの取得層が、今回のレース日より後（当日を含む）の情報を1件も入れないこと。"""

from __future__ import annotations

import random

import pytest

from eval import data_access

RACE_DATE = "2025-06-01"
NOW = "2025-01-01 00:00:00"
LAPS = (12.5, 11.0, 11.5, 12.0, 11.8, 11.6, 11.9, 12.2)   # 1600m（200mごと）


def _race_id(date: str, race_no: int) -> str:
    return f"{date[:4]}05{int(date[5:7]):02d}{int(date[8:]):02d}{race_no:02d}"


def _add_race(conn, date, race_no, horses, klass="1勝クラス", laps=LAPS):
    race_id = _race_id(date, race_no)
    conn.execute(
        """INSERT INTO races (race_id, race_date, venue_code, kaiji, nichime, race_no, race_name,
               surface, distance_m, age_condition, class_condition, n_runners, fetched_at, updated_at)
           VALUES (?, ?, '05', 1, 1, ?, ?, 'turf', 1600, '3歳以上', ?, ?, ?, ?)""",
        (race_id, date, race_no, f"{klass}", klass, len(horses), NOW, NOW),
    )
    for position, horse_id in enumerate(horses, 1):
        conn.execute("INSERT OR IGNORE INTO horses (horse_id, horse_name, updated_at) VALUES (?, ?, ?)",
                     (horse_id, horse_id, NOW))
        conn.execute("INSERT INTO entries (race_id, umaban, horse_id) VALUES (?, ?, ?)",
                     (race_id, position, horse_id))
        conn.execute(
            """INSERT INTO results (race_id, umaban, horse_id, finish_position, time_sec,
                   win_odds, popularity) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (race_id, position, horse_id, position, 95.0 + position * 0.2, 2.0 * position, position),
        )
    for seq, lap in enumerate(laps, 1):
        conn.execute("INSERT INTO race_laps (race_id, seq, distance_m, lap_sec) VALUES (?, ?, ?, ?)",
                     (race_id, seq, seq * 200, lap))
    return race_id


@pytest.fixture
def db(conn):
    # 過去（前日まで）・当日の前のレース・未来の3種類を混ぜる
    for i, date in enumerate(("2025-03-01", "2025-04-01", "2025-05-01", "2025-05-15", "2025-05-31")):
        _add_race(conn, date, 1, ["H1", "H2", "H3", "H4"])
    _add_race(conn, RACE_DATE, 1, ["H3", "H4"])          # 同じ日の前のレース（相手の H3・H4 が走る）
    target = _add_race(conn, RACE_DATE, 5, ["H1", "H2"])
    for date in ("2025-06-08", "2025-07-01", "2025-08-01", "2025-09-01", "2025-10-01"):
        _add_race(conn, date, 1, ["H1", "H2", "H3", "H4"], laps=tuple(x + 1 for x in LAPS))
    conn.commit()
    return conn, target


def _all_dates(inputs: dict) -> list[str]:
    dates = [r["race_date"] for runs in inputs["past_runs"].values() for r in runs]
    dates += [r["race_date"] for runs in inputs["stats_runs"].values() for r in runs]
    dates += [r["race_date"] for runs in inputs["opponent_runs"].values() for r in runs]
    return dates


def test_leak_free_inputs_have_no_same_day_or_future_rows(db):
    conn, target = db
    inputs = data_access.build_inputs(conn, target, leak_free=True)
    dates = _all_dates(inputs)
    assert dates, "材料が空だと検査にならない"
    assert all(d < RACE_DATE for d in dates)
    # 倒した相手は、過去走のレースのものだけ
    past_ids = {r["race_id"] for runs in inputs["past_runs"].values() for r in runs}
    assert set(inputs["fields"]) <= past_ids


def test_condition_laps_respects_before(db):
    conn, _ = db
    race = data_access.get_race(conn, _race_id(RACE_DATE, 5))
    rows, _ = data_access.condition_laps(conn, "05", "turf", 1600, "1勝クラス", race["race_date"])
    assert rows and all(r["race_date"] < RACE_DATE for r in rows)


def test_leak_mode_only_leaks_condition_laps(db):
    conn, target = db
    leak = data_access.build_inputs(conn, target, leak_free=False)
    assert all(d < RACE_DATE for d in _all_dates(leak))
    rows, _ = data_access.condition_laps(conn, "05", "turf", 1600, "1勝クラス", None)
    assert any(r["race_date"] >= RACE_DATE for r in rows)


def test_entries_exclude_scratched(db):
    conn, target = db
    conn.execute("UPDATE results SET finish_position = NULL, finish_status = '取消' "
                 "WHERE race_id = ? AND horse_id = 'H2'", (target,))
    assert [e["horse_id"] for e in data_access.get_entries(conn, target)] == ["H1"]


@pytest.mark.skipif(not data_access.DEFAULT_DB.exists(), reason="実DBが手元に無い")
def test_real_db_sample_has_no_leak():
    conn = data_access.connect()
    races = data_access.list_races(conn, "2025-01-01", "2025-12-31")
    for race in random.Random(0).sample(races, 20):
        inputs = data_access.build_inputs(conn, race["race_id"], leak_free=True)
        assert all(d < race["race_date"] for d in _all_dates(inputs)), race["race_id"]
        rows, _ = data_access.condition_laps(
            conn, inputs["race"]["venue_code"], inputs["race"]["surface"],
            inputs["race"]["distance_m"], inputs["race"]["class_condition"], race["race_date"])
        assert all(r["race_date"] < race["race_date"] for r in rows)
