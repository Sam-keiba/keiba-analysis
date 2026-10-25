"""答え合わせ用の、リークなしのデータ取得層。

アプリ（keiba-app の data.py）と同じ材料を、**今回のレースの日より前の情報だけ**で作る。
keiba-analysis は keiba-app に依存しないので、data.py の SQL は import せず、
tier.py が使う列だけの軽い SQL をここに書き直してある（列の意味は data.py と同じ）。

日付の条件はすべて `race_date < before`。同じ日の前のレースも除く（安全側）。

data.py との対応:
    past_runs_for_horses … get_past_runs_for_horses（件数で切らない＝馬柱と同じ全走）
    runs_for_stats       … get_runs_for_stats
    top_finishers        … get_top_finishers
    class_runs           … get_class_runs
    condition_laps       … get_condition_laps（**data.py には日付の条件が無い**。ここで足した）
    today_pace           … sections.today_pace_mark
"""

from __future__ import annotations

import sqlite3
import unicodedata
from functools import lru_cache
from pathlib import Path

from keiba_analysis.racing import pace, race_forecast
from keiba_analysis.racing import tier as tier_module

DEFAULT_DB = Path(__file__).resolve().parents[2] / "keiba-data" / "data" / "keiba.db"

# data.py の MIN_CONDITION_RACES と同じ。クラスまで一致するレースがこれに満たなければクラスを外す
MIN_CONDITION_RACES = 5

# 出走していない（取消・除外）馬は出走表から外す。中止・失格は走ったので残す
NOT_STARTED = ("取消", "除外")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """読み取り専用で開く（答え合わせでDBを書き換えないため）。"""
    path = Path(db_path or DEFAULT_DB)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur: sqlite3.Cursor) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def _placeholders(items: list) -> str:
    return ", ".join("?" for _ in items)


# --- 今回のレース ---------------------------------------------------------------

def list_races(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """期間内の障害を除くレース（日付・場・R の順）。"""
    return _rows(conn.execute(
        """
        SELECT race_id, race_date FROM races
        WHERE race_date >= ? AND race_date <= ? AND surface != 'jump'
        ORDER BY race_date, venue_code, race_no
        """,
        (start, end),
    ))


def get_race(conn: sqlite3.Connection, race_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM races WHERE race_id = ?", (race_id,)).fetchone()
    return dict(row) if row else None


def get_entries(conn: sqlite3.Connection, race_id: str) -> list[dict]:
    """出走馬（取消・除外を除く）。着順・単勝オッズ・人気は**答え合わせにだけ**使う。"""
    return _rows(conn.execute(
        f"""
        SELECT race_id, umaban, horse_id, finish_position, finish_status, win_odds, popularity
        FROM results
        WHERE race_id = ? AND horse_id IS NOT NULL
          AND (finish_status IS NULL OR finish_status NOT IN ({_placeholders(list(NOT_STARTED))}))
        ORDER BY umaban
        """,
        (race_id, *NOT_STARTED),
    ))


# --- 過去の材料（どれも before が必須） ------------------------------------------

def past_runs_for_horses(
    conn: sqlite3.Connection, horse_ids: list[str], surface: str | None, before: str,
) -> dict[str, list[dict]]:
    """馬ID -> 同じ馬場の、before より前の全走（新しい順）。"""
    ids = [h for h in horse_ids if h]
    runs: dict[str, list[dict]] = {h: [] for h in ids}
    if not ids:
        return runs
    rows = conn.execute(
        f"""
        SELECT res.horse_id, ra.race_id, ra.race_date, ra.race_no, ra.venue_code, ra.race_name,
               ra.grade, ra.class_condition, ra.surface, ra.distance_m, ra.n_runners,
               res.finish_position, res.time_sec, res.popularity
        FROM results res JOIN races ra USING (race_id)
        WHERE res.horse_id IN ({_placeholders(ids)}) AND (? IS NULL OR ra.surface = ?)
              AND ra.race_date < ?
        ORDER BY res.horse_id, ra.race_date DESC, ra.race_no DESC
        """,
        [*ids, surface, surface, before],
    )
    for row in rows:
        runs[row["horse_id"]].append(dict(row))
    return runs


_RUNS_FOR_STATS_SQL = """
SELECT ra.race_id, ra.race_date, ra.surface, ra.distance_m, ra.n_runners,
       res.finish_position, res.finish_status, res.corner_passing, res.last_3f,
       (SELECT SUM(lap_sec) FROM race_laps l
          WHERE l.race_id = ra.race_id AND l.distance_m <= 600) AS race_first_3f,
       (SELECT SUM(lap_sec) FROM (SELECT lap_sec FROM race_laps l
          WHERE l.race_id = ra.race_id ORDER BY l.seq DESC LIMIT 3)) AS race_last_3f
FROM results res
JOIN races ra USING (race_id)
WHERE res.horse_id = ? AND (? IS NULL OR ra.surface = ?) AND ra.race_date < ?
ORDER BY ra.race_date DESC, ra.race_no DESC
"""


def runs_for_stats(
    conn: sqlite3.Connection, horse_id: str | None, surface: str | None, before: str,
) -> list[dict]:
    """その馬の同じ馬場の、before より前の全走（ペース適性の材料）。"""
    if not horse_id:
        return []
    return _rows(conn.execute(_RUNS_FOR_STATS_SQL, (horse_id, surface, surface, before)))


def top_finishers(
    conn: sqlite3.Connection, race_ids: list[str], n: int = 6,
) -> dict[str, list[dict]]:
    """レースID -> 上位n頭。渡すのは before で絞った過去走のレースIDだけにすること。"""
    ids = sorted({r for r in race_ids if r})
    field: dict[str, list[dict]] = {r: [] for r in ids}
    if not ids:
        return field
    rows = conn.execute(
        f"""
        SELECT res.race_id, res.horse_id, h.horse_name, res.finish_position, res.time_sec
        FROM results res LEFT JOIN horses h ON h.horse_id = res.horse_id
        WHERE res.race_id IN ({_placeholders(ids)})
          AND res.finish_position <= ? AND res.horse_id IS NOT NULL
        ORDER BY res.race_id, res.finish_position
        """,
        [*ids, n],
    )
    for row in rows:
        field[row["race_id"]].append(dict(row))
    return field


def class_runs(
    conn: sqlite3.Connection, horse_ids: list[str], surface: str | None, before: str,
    limit: int = 5,
) -> dict[str, list[dict]]:
    """馬ID -> before より前の直近の走（相手の強さの材料）。"""
    ids = sorted({h for h in horse_ids if h})
    runs: dict[str, list[dict]] = {h: [] for h in ids}
    if not ids:
        return runs
    rows = conn.execute(
        f"""
        SELECT * FROM (
          SELECT res.horse_id, ra.race_date, ra.race_name, ra.grade, ra.class_condition,
                 ra.n_runners, res.finish_position, res.popularity,
                 ROW_NUMBER() OVER (PARTITION BY res.horse_id
                                    ORDER BY ra.race_date DESC, ra.race_no DESC) AS nth
          FROM results res JOIN races ra USING (race_id)
          WHERE res.horse_id IN ({_placeholders(ids)}) AND (? IS NULL OR ra.surface = ?)
                AND ra.race_date < ?
        )
        WHERE nth <= ?
        ORDER BY horse_id, nth
        """,
        [*ids, surface, surface, before, limit],
    )
    for row in rows:
        runs[row["horse_id"]].append(dict(row))
    return runs


# --- 今日のペース ---------------------------------------------------------------

_CONDITION_LAPS_SQL = """
SELECT ra.race_id, ra.race_date, ra.class_condition, ra.n_runners,
       tc.cushion_value,
       (SELECT group_concat(lap_sec, '-')
          FROM (SELECT lap_sec FROM race_laps l WHERE l.race_id = ra.race_id ORDER BY l.seq)) AS race_laps,
       (SELECT group_concat(distance_m, '-')
          FROM (SELECT distance_m FROM race_laps l WHERE l.race_id = ra.race_id ORDER BY l.seq)) AS lap_distances
FROM races ra
LEFT JOIN track_conditions tc ON tc.venue_code = ra.venue_code AND tc.date = ra.race_date
WHERE ra.venue_code = ? AND ra.surface = ? AND ra.distance_m = ?
  AND EXISTS (SELECT 1 FROM race_laps l WHERE l.race_id = ra.race_id)
ORDER BY ra.race_date DESC
"""


@lru_cache(maxsize=4096)
def _course_laps(conn: sqlite3.Connection, venue: str, surface: str, distance: int) -> tuple[dict, ...]:
    """同じコースのラップのあるレース全部（新しい順）。同じコースを何度も引くのでプロセス内で覚える。

    答え合わせの間はDBが変わらない前提（読み取り専用で開いている）。
    """
    return tuple(_rows(conn.execute(_CONDITION_LAPS_SQL, (venue, surface, distance))))


def condition_laps(
    conn: sqlite3.Connection, venue: str | None, surface: str | None, distance: int | None,
    klass: str | None, before: str | None,
) -> tuple[list[dict], bool]:
    """同じコース・同じクラスの過去レースのラップ。戻り値は (レース, クラスまで一致したか)。

    data.py の get_condition_laps と同じ手順（クラス一致が5本未満ならクラスを外す）に、
    `before` の日付条件を足したもの。before=None なら data.py と同じく日付で絞らない
    （**リークあり**。旧実測の再現にだけ使う）。
    クラスは data.py と同じく `LIKE 'クラス%'`（前方一致）で比べる。
    """
    if not venue or not surface or not distance:
        return [], False
    rows = [r for r in _course_laps(conn, venue, surface, distance)
            if before is None or r["race_date"] < before]
    if klass:
        same = [r for r in rows if (r.get("class_condition") or "").startswith(klass)]
        if len(same) >= MIN_CONDITION_RACES:
            return same, True
    return rows, False


def today_pace(conn: sqlite3.Connection, race: dict, before: str | None) -> str | None:
    """今日の想定ラップから見たペース（H/M/S）。sections.today_pace_mark と同じ計算。"""
    klass = unicodedata.normalize("NFKC", race.get("class_condition") or "")
    races, _ = condition_laps(
        conn, race.get("venue_code"), race.get("surface"), race.get("distance_m"), klass, before,
    )
    average = race_forecast.average_laps(races)
    if average is None:
        return None
    first_3f, last_3f = race_forecast.three_furlong_split(average.laps)
    return pace.classify(first_3f, last_3f)


# --- 1レースぶんの入力 ------------------------------------------------------------

def build_inputs(conn: sqlite3.Connection, race_id: str, leak_free: bool = True) -> dict:
    """tier.assign に渡す材料を1レースぶん作る。

    過去走・全走・相手の走は、どちらのモードでも今回のレース日より前だけ。
    `leak_free=False` は**今日のペースだけ**日付で絞らない（アプリの get_condition_laps と同じ。
    旧実測の再現用）。
    """
    race = get_race(conn, race_id)
    if race is None:
        raise KeyError(race_id)
    before = race["race_date"]
    surface = race.get("surface")
    entries = get_entries(conn, race_id)
    horse_ids = [e["horse_id"] for e in entries]
    past_runs = past_runs_for_horses(conn, horse_ids, surface, before)
    stats_runs = {h: runs_for_stats(conn, h, surface, before) for h in horse_ids}
    fields = top_finishers(
        conn, [r["race_id"] for runs in past_runs.values() for r in runs[:tier_module.RECENT_RUNS]]
    )
    opponent_runs = class_runs(
        conn, [o["horse_id"] for field in fields.values() for o in field], surface, before,
    )
    return {
        "race": race,
        "entries": entries,
        "past_runs": past_runs,
        "stats_runs": stats_runs,
        "fields": fields,
        "opponent_runs": opponent_runs,
        "today_pace": today_pace(conn, race, before if leak_free else None),
    }


def assign(inputs: dict) -> dict:
    """build_inputs の材料で tier.assign を呼ぶ（既存のロジックをそのまま使う）。"""
    return tier_module.assign(
        inputs["race"], inputs["entries"], inputs["past_runs"], inputs["stats_runs"],
        inputs["today_pace"], fields=inputs["fields"], opponent_runs=inputs["opponent_runs"],
    )
