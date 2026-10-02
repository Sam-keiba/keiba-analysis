"""厩舎（調教師）分析のDB取得。**ここはSQLで行を取るだけ**で、率や順位の計算は `trainer_stats.py`。

調教師は `entries.trainer_id`（**レース当時の調教師**。全走で埋まっている）で数える。
`horses.trainer_name` は今の厩舎なので使わない（転厩した馬を取り違える）。

## 名前と所属

- `trainers.trainer_name` は**4文字で切れている**（「鈴木慎太」など）。同名の別人もいるので、
  鍵は必ず `trainer_id`。正式名・読み・生年月日・免許取得年は `trainers.full_name` などにあるが、
  **JRA調教師名鑑の現役だけ**（引退した調教師は空。そのときは4文字の名前で出す）
- 馬房数は `trainer_stalls`（JRAが毎年2〜3月に出す貸付馬房数。いちばん新しい発表を使う）
- `trainers.stable` は**今の**所属（美浦／栗東／地方／海外）。引退した調教師も美浦・栗東のまま
- 厩舎分析の母集団は、美浦・栗東の調教師（`JRA_STABLES`）

## 出走に数えるもの

取消・除外は数えない（`sire_index.NOT_STARTED` と同じ）。障害も含める（JRAの調教師リーディングと同じ）。
"""

from __future__ import annotations

import sqlite3

from keiba_analysis.owner.club_data import CLUB_BY_OWNER_NAME
from keiba_analysis.shared.race_name import classic_sql
from keiba_analysis.shared.sire_index import NOT_STARTED, HorseYear

JRA_STABLES = ("美浦", "栗東")

_STARTED = "COALESCE(re.finish_status, '') NOT IN ({})".format(
    ", ".join(f"'{s}'" for s in NOT_STARTED))
_JRA = "t.stable IN ({})".format(", ".join(f"'{s}'" for s in JRA_STABLES))
# 世代（生年）。生年が無い古い馬は「その年 − 馬齢」（`sire_index` と同じ）
_CROP = "COALESCE(CAST(substr(NULLIF(h.birth_date, ''), 1, 4) AS INTEGER), {year} - {age})"


# --- 調教師の一覧と基本情報 ---------------------------------------------------------------

def list_trainers(conn: sqlite3.Connection) -> list[dict]:
    """美浦・栗東の調教師（DBに出走がある人）。**最後に出走させた日が新しい順 → 出走数の多い順**。"""
    rows = conn.execute(
        f"""
        SELECT t.trainer_id, COALESCE(t.full_name, t.trainer_name) AS trainer_name,
               t.trainer_name AS short_name, t.kana, t.birth_date, t.license_year, t.stable,
               MIN(ra.race_date) AS first_date, MAX(ra.race_date) AS last_date,
               COUNT(*) AS starts
          FROM entries e
          JOIN trainers t ON t.trainer_id = e.trainer_id
          JOIN races ra ON ra.race_id = e.race_id
         WHERE {_JRA}
      GROUP BY t.trainer_id
        """
    )
    return sorted((dict(r) for r in rows),
                  key=lambda r: (r["last_date"][:7], r["starts"]), reverse=True)


def stalls(conn: sqlite3.Connection) -> tuple[str | None, dict[str, int]]:
    """いちばん新しい貸付馬房数の発表日と、調教師ID → 馬房数（技術調教師など馬房の無い人は入らない）。"""
    latest = conn.execute("SELECT MAX(effective_date) FROM trainer_stalls").fetchone()[0]
    if latest is None:
        return None, {}
    return latest, {r["trainer_id"]: r["stalls"] for r in conn.execute(
        "SELECT trainer_id, stalls FROM trainer_stalls WHERE effective_date = ?", (latest,))}


def as_of(conn: sqlite3.Connection) -> str | None:
    """DBの最終レース日（「〇〇現在」と、直近1年・3年の起点）。"""
    return conn.execute("SELECT MAX(race_date) FROM races").fetchone()[0]


def club_owner_ids(conn: sqlite3.Connection) -> dict[str, str]:
    """一口クラブの馬主ID → 表示名（`club_data.CLUBS` に載っているクラブだけ）。"""
    names = list(CLUB_BY_OWNER_NAME)
    marks = ", ".join("?" * len(names))
    return {
        r["owner_id"]: CLUB_BY_OWNER_NAME[r["owner_name"]][0]
        for r in conn.execute(
            f"SELECT owner_id, owner_name FROM owners WHERE owner_name IN ({marks})", names)
    }


# --- 全厩舎×年（年別推移・順位） -----------------------------------------------------------

_YEARS_SQL = f"""
    SELECT e.trainer_id,
           CAST(substr(ra.race_date, 1, 4) AS INTEGER) AS year,
           COUNT(*)                                   AS starts,
           SUM(re.finish_position = 1)                AS wins,
           SUM(re.finish_position = 2)                AS seconds,
           SUM(re.finish_position = 3)                AS thirds,
           SUM(COALESCE(re.prize_man_yen, 0))         AS prize_man_yen,
           COUNT(DISTINCT e.horse_id)                 AS horses
      FROM entries e NOT INDEXED
      JOIN trainers t ON t.trainer_id = e.trainer_id
      JOIN races   ra ON ra.race_id = e.race_id
      JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
     WHERE {_JRA} AND {_STARTED}
  GROUP BY e.trainer_id, year
"""


def all_trainer_years(conn: sqlite3.Connection) -> list[dict]:
    """全厩舎（美浦・栗東）×年の出走・勝利・2着・3着・賞金・頭数。実DBで3秒ほど。"""
    return [dict(r) for r in conn.execute(_YEARS_SQL)]


# --- 直近の各走（傾向・得意カテゴリ・牝馬指数の材料） ---------------------------------------

# 同じ馬の前後の走（日付・調教師・騎手）を窓関数で付ける。取消・除外は並びから外す。
# 窓は全期間で並べてから日付で切る（期間の最初の走にも、その前の走が付くように）
_WINDOW_RUNS_SQL = f"""
    WITH seq AS (
        SELECT e.horse_id, e.trainer_id, e.jockey_id, e.kinryo_mark, ra.race_date, ra.venue_code,
               ra.surface, ra.distance_m, ra.class_condition, ra.grade,
               re.finish_position, COALESCE(re.prize_man_yen, 0) AS prize_man_yen, re.win_odds,
               COALESCE(e.owner_id, e.owner_id_at_export)              AS owner_id,
               LAG(ra.race_date)  OVER w AS prev_date,
               LAG(e.trainer_id)  OVER w AS prev_trainer,
               LAG(e.jockey_id)   OVER w AS prev_jockey,
               LEAD(e.trainer_id) OVER w AS next_trainer
          FROM entries e NOT INDEXED
          JOIN races   ra ON ra.race_id = e.race_id
          JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
         WHERE {_STARTED}
        WINDOW w AS (PARTITION BY e.horse_id ORDER BY ra.race_date, ra.race_id)
    )
    SELECT s.*, h.sex
      FROM seq s
      JOIN trainers t ON t.trainer_id = s.trainer_id
      JOIN horses   h ON h.horse_id = s.horse_id
     WHERE s.race_date >= ? AND {_JRA}
"""


def window_runs(conn: sqlite3.Connection, since: str) -> list[dict]:
    """`since` 以降の全厩舎の各走（1行1走）と、その馬の前後の走。実DBで数秒。"""
    return [dict(r) for r in conn.execute(_WINDOW_RUNS_SQL, (since,))]


# --- 世代ごとの馬（勝ち上がり・クラシック・重賞・デビュー） ---------------------------------

_CROP_HORSES_SQL = f"""
    WITH r AS (
        SELECT e.horse_id, e.trainer_id, ra.race_date, e.age, ra.class_condition,
               re.finish_position, ra.surface, ra.grade, ra.race_name,
               ROW_NUMBER() OVER (PARTITION BY e.horse_id ORDER BY ra.race_date, ra.race_id) AS n
          FROM entries e NOT INDEXED
          JOIN races   ra ON ra.race_id = e.race_id
          JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
         WHERE {_STARTED}
    ),
    per_horse AS (
        SELECT horse_id,
               MIN(race_date)                                                 AS debut_date,
               MAX(CASE WHEN n = 1 THEN trainer_id END)                       AS debut_trainer,
               MAX(CASE WHEN n = 1 THEN age END)                              AS debut_age,
               MAX(CASE WHEN n = 1 THEN class_condition END)                  AS debut_class,
               MIN(CASE WHEN finish_position = 1 THEN n END)                  AS first_win_n,
               MAX(CASE WHEN {classic_sql("race_name", "grade")} THEN 1 ELSE 0 END) AS classic,
               MAX(CASE WHEN finish_position = 1 AND grade IN ('GI', 'GII', 'GIII')
                         AND COALESCE(surface, '') <> 'jump' THEN 1 ELSE 0 END) AS graded_winner,
               MAX(CASE WHEN age >= 3 THEN 1 ELSE 0 END)                      AS aged3,
               group_concat(DISTINCT trainer_id)                              AS trainers
          FROM r
      GROUP BY horse_id
    )
    SELECT p.*, h.sex, h.breeder,
           {_CROP.format(year="CAST(substr(p.debut_date, 1, 4) AS INTEGER)", age="p.debut_age")}
               AS crop
      FROM per_horse p
      JOIN horses h ON h.horse_id = p.horse_id
"""


def crop_horses(conn: sqlite3.Connection, first_crop: int, last_crop: int) -> list[dict]:
    """世代（生年）が範囲内の馬の要約（1頭1行）。`trainers` は走らせた調教師（カンマ区切り）。"""
    return [
        {**dict(r), "trainers": tuple((r["trainers"] or "").split(","))}
        for r in conn.execute(_CROP_HORSES_SQL)
        if r["crop"] is not None and first_crop <= r["crop"] <= last_crop
    ]


# --- AEI・CPIの材料（馬×年×厩舎） ----------------------------------------------------------

# `sire_index._HORSE_YEARS_SQL` と同じ集計を、**調教師ごとにも分けて**行う。
# 年の途中で転厩した馬は、各厩舎にいた間の走でそれぞれ1行になる
_TRAINER_HORSE_YEARS_SQL = f"""
    SELECT e.horse_id AS horse_id,
           CAST(substr(ra.race_date, 1, 4) AS INTEGER) AS year,
           e.trainer_id AS trainer_id,
           NULLIF(h.dam_key, '') AS dam_no,
           {_CROP.format(year="CAST(substr(ra.race_date, 1, 4) AS INTEGER)", age="MAX(e.age)")} AS crop,
           SUM(CASE WHEN {{started}} THEN COALESCE(re.prize_man_yen, 0) ELSE 0 END) AS prize,
           SUM(CASE WHEN {{started}} AND {{flat}} THEN COALESCE(re.prize_man_yen, 0) ELSE 0 END)
                                                                           AS prize_flat,
           MAX(CASE WHEN {{started}} THEN 1 ELSE 0 END)                    AS ran,
           MAX(CASE WHEN {{started}} AND {{flat}} THEN 1 ELSE 0 END)       AS ran_flat
      FROM entries e NOT INDEXED
      JOIN races   ra ON ra.race_id = e.race_id
      JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
      JOIN horses  h  ON h.horse_id = e.horse_id
  GROUP BY e.horse_id, year, e.trainer_id
    HAVING ran = 1
""".format(started=_STARTED, flat="COALESCE(ra.surface, '') <> 'jump'")


def trainer_horse_years(conn: sqlite3.Connection) -> list[HorseYear]:
    """厩舎AEI・CPIの材料。`HorseYear` の形で、**`sire` 欄に調教師ID**を入れて返す。

    `sire_index.aei` / `cpi` は `sire` 欄で絞って数えるので、ここに調教師を入れれば
    式を書き直さずに厩舎版になる（分母は種牡馬と同じ `horse_years` の全出走馬で別に作る）。
    """
    return [
        HorseYear(
            horse_id=r["horse_id"], year=r["year"], sire=r["trainer_id"], dam_no=r["dam_no"],
            prize=r["prize"] or 0.0, prize_flat=r["prize_flat"] or 0.0,
            ran=bool(r["ran"]), ran_flat=bool(r["ran_flat"]), crop=r["crop"],
        )
        for r in conn.execute(_TRAINER_HORSE_YEARS_SQL)
    ]


# --- 1厩舎ぶんの走（代表馬・重賞・最近の勝利／出走・クラブ馬） --------------------------------

_TRAINER_RUNS_SQL = f"""
    SELECT e.horse_id, h.horse_name, h.sex, h.breeder, e.age, e.trainer_id, e.jockey_id,
           j.jockey_name, COALESCE(e.owner_id, e.owner_id_at_export) AS owner_id,
           o.owner_name,
           ra.race_id, ra.race_date, ra.venue_code, v.venue_name, ra.race_no, ra.race_name,
           ra.race_name_plain, ra.grade, ra.surface, ra.distance_m, ra.class_condition,
           ra.n_runners,
           re.finish_position, re.finish_status, COALESCE(re.prize_man_yen, 0) AS prize_man_yen,
           re.win_odds, re.popularity
      FROM entries e
      JOIN horses  h  ON h.horse_id = e.horse_id
      JOIN races   ra ON ra.race_id = e.race_id
      JOIN venues  v  ON v.venue_code = ra.venue_code
      JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
 LEFT JOIN jockeys j  ON j.jockey_id = e.jockey_id
 LEFT JOIN owners  o  ON o.owner_id = COALESCE(e.owner_id, e.owner_id_at_export)
     WHERE e.trainer_id = ?
  ORDER BY ra.race_date DESC, ra.race_no DESC
"""


def trainer_runs(conn: sqlite3.Connection, trainer_id: str) -> list[dict]:
    """その厩舎の全走（新しい順）。取消・除外も入れる（`finish_status` で見分ける）。"""
    return [dict(r) for r in conn.execute(_TRAINER_RUNS_SQL, (trainer_id,))]


def latest_runs(conn: sqlite3.Connection, horse_ids: list[str]) -> dict[str, dict]:
    """馬ごとの**DB全体での**最後の走（現役クラブ馬の判定用。転厩していったかを見る）。"""
    out: dict[str, dict] = {}
    for i in range(0, len(horse_ids), 500):
        chunk = horse_ids[i:i + 500]
        marks = ", ".join("?" * len(chunk))
        for r in conn.execute(
            f"""
            SELECT e.horse_id, h.horse_name, h.sex, e.age, e.trainer_id,
                   COALESCE(e.owner_id, e.owner_id_at_export) AS owner_id,
                   ra.race_date, ra.class_condition, ra.grade, re.finish_position
              FROM entries e
              JOIN horses  h  ON h.horse_id = e.horse_id
              JOIN races   ra ON ra.race_id = e.race_id
              JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
             WHERE e.horse_id IN ({marks})
          ORDER BY ra.race_date, ra.race_id
            """,
            chunk,
        ):
            out[r["horse_id"]] = dict(r)          # 古い順に上書きするので、最後に残るのが最新
    return out
