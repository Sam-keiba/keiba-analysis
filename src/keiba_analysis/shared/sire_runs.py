"""種牡馬ごとの産駒成績を**手元のDB**から集計する（距離適性・BMS相性・代表産駒など）。

JRA公式の種牡馬リーディング（`sire_data.py`）は年ごとの合計しか出していないので、
距離・コース・性別・年齢といった内訳はここで作る。材料は `keiba pedigree` で埋めた
`horses.sire` と、もともとDBにある `entries` / `results` / `races`。

## 集計範囲がリーディングと違う

**2023年以降のJRAのレースだけ**（DBに入っている範囲）。リーディング由来の数字は
全期間なので、画面では必ず区別して出すこと（`sire_view.LOCAL_SCOPE` の注記）。
地方・海外の出走、2022年以前の出走は入らない。

## 母数

血統は1頭ずつ取り込むので、**取り込みの途中では産駒の一部しか集計できない**。
どの関数も「何頭ぶんか」を一緒に返し、画面で進み具合を出せるようにする。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# この走数に満たない区分は、画面で薄く描いて注意書きを添える
MIN_RUNS = 20
# 距離帯（上限・表示名）。芝・ダートで同じ区切りを使う
DISTANCE_BANDS: tuple[tuple[int, str], ...] = (
    (1400, "〜1400m"), (1600, "1600m"), (1800, "1800m"),
    (2000, "2000m"), (2200, "2200m"), (9999, "2400m〜"),
)
# 年齢の区分
AGE_BANDS: tuple[tuple[int, str], ...] = ((2, "2歳"), (3, "3歳"), (4, "4歳"), (99, "5歳以上"))
SURFACES: tuple[tuple[str, str], ...] = (("turf", "芝"), ("dirt", "ダート"))
SEX_ORDER: tuple[str, ...] = ("牡", "牝", "セ")
# クラシック（この6競走への出走で「クラシックに出た産駒」とみなす）。
# DBのレース名には「第93回東京優駿」のように回数が付くので、**後方一致**で見る
CLASSIC_RACES: tuple[str, ...] = ("皐月賞", "東京優駿", "菊花賞", "桜花賞", "優駿牝馬", "秋華賞")
# 社台グループの生産牧場（`breeder` の表記に含まれていれば社台グループとみなす）
SHADAI_FARMS: tuple[str, ...] = (
    "ノーザンファーム", "社台ファーム", "追分ファーム", "白老ファーム",
    "社台コーポレーション", "社台牧場",
)

# 集計の土台。**1行1走**で、馬・レース・結果をまとめて取る。
# この形にだけ依存する集計（距離別・年齢別・デビュー時期…）は、絞り込みを差し替えれば
# そのまま使い回せるので、**クラブ分析（club_data.py）とも共用する**。
_RUNS_SELECT = """
    SELECT e.horse_id, h.horse_name, h.sex, h.sire, h.broodmare_sire, h.breeder,
           e.age, e.horse_weight, e.owner_id,
           t.trainer_name, t.stable,
           ra.race_id, ra.race_date, ra.race_name, ra.grade, ra.surface, ra.distance_m,
           ra.venue_code, ra.class_condition,
           CASE WHEN ra.surface = 'dirt' THEN ra.going_dirt ELSE ra.going_turf END AS going,
           re.finish_position, re.prize_man_yen
      FROM entries e
      JOIN horses  h  ON h.horse_id = e.horse_id
      JOIN races   ra ON ra.race_id = e.race_id
      JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
 LEFT JOIN trainers t ON t.trainer_id = e.trainer_id
"""


@dataclass(frozen=True)
class Tally:
    """ある区分の成績。率はすべて**出走を分母**にする。"""

    label: str
    horses: int = 0          # その区分を走った産駒の頭数
    starts: int = 0
    wins: int = 0
    top3: int = 0
    top5: int = 0            # 掲示板（5着以内）
    prize_man_yen: float = 0.0

    def _rate(self, n: int) -> float | None:
        return n / self.starts if self.starts else None

    @property
    def win_rate(self) -> float | None:
        return self._rate(self.wins)

    @property
    def top3_rate(self) -> float | None:
        return self._rate(self.top3)

    @property
    def top5_rate(self) -> float | None:
        return self._rate(self.top5)

    @property
    def is_thin(self) -> bool:
        """材料が足りない区分か（画面で薄く描く）。"""
        return self.starts < MIN_RUNS


@dataclass(frozen=True)
class Coverage:
    """血統の取り込みがどこまで進んでいるか（画面の先頭に出す）。"""

    sire_horses: int      # この種牡馬の産駒として分かっている頭数
    sire_runs: int        # その産駒の走数
    known: int            # 父が分かっている馬（DB全体）
    total: int            # 出走した馬（DB全体）

    @property
    def ratio(self) -> float | None:
        return self.known / self.total if self.total else None

    @property
    def is_complete(self) -> bool:
        return self.total > 0 and self.known >= self.total


def _tally(rows: list[dict], label: str) -> Tally:
    return Tally(
        label=label,
        horses=len({r["horse_id"] for r in rows}),
        starts=len(rows),
        wins=sum(1 for r in rows if r["finish_position"] == 1),
        top3=sum(1 for r in rows if (r["finish_position"] or 99) <= 3),
        top5=sum(1 for r in rows if (r["finish_position"] or 99) <= 5),
        prize_man_yen=sum(r["prize_man_yen"] or 0.0 for r in rows),
    )


def runs_where(conn: sqlite3.Connection, where: str, params: tuple) -> list[dict]:
    """絞り込みを差し替えて「1行1走」を取る。

    種牡馬（`h.sire = ?`）でもクラブ（`e.owner_id = ?`）でも同じ形が返るので、
    この下の集計関数がそのまま両方で使える。数千走までなので、1回引いて
    Python側で切り分けるほうが読みやすく速い。
    """
    return [dict(r) for r in conn.execute(f"{_RUNS_SELECT} WHERE {where}", params)]


def sire_runs(conn: sqlite3.Connection, sire_name: str) -> list[dict]:
    """その種牡馬の産駒の全走（1行1走）。ほかの集計はこれを材料にする。"""
    return runs_where(conn, "h.sire = ?", (sire_name,))


def coverage(conn: sqlite3.Connection, runs: list[dict]) -> Coverage:
    """血統の取り込みの進み具合。"""
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "       SUM(CASE WHEN sire IS NOT NULL AND sire <> '' THEN 1 ELSE 0 END) AS known "
        "  FROM horses h WHERE EXISTS (SELECT 1 FROM entries e WHERE e.horse_id = h.horse_id)"
    ).fetchone()
    return Coverage(
        sire_horses=len({r["horse_id"] for r in runs}), sire_runs=len(runs),
        known=row["known"] or 0, total=row["total"] or 0,
    )


def _band(value: int | None, bands: tuple[tuple[int, str], ...]) -> str | None:
    if value is None:
        return None
    for limit, label in bands:
        if value <= limit:
            return label
    return bands[-1][1]


def by_distance(runs: list[dict], surface: str) -> list[Tally]:
    """距離帯ごとの成績（芝／ダートのどちらか）。"""
    picked = [r for r in runs if r["surface"] == surface]
    return [
        _tally([r for r in picked if _band(r["distance_m"], DISTANCE_BANDS) == label], label)
        for _limit, label in DISTANCE_BANDS
    ]


def by_sex(runs: list[dict]) -> list[Tally]:
    """性別ごとの成績。"""
    return [_tally([r for r in runs if r["sex"] == sex], sex) for sex in SEX_ORDER]


def by_age(runs: list[dict]) -> list[Tally]:
    """年齢ごとの成績（成長の傾向）。"""
    return [
        _tally([r for r in runs if _band(r["age"], AGE_BANDS) == label], label)
        for _limit, label in AGE_BANDS
    ]


def by_surface(runs: list[dict], *, include_jump: bool = False) -> list[Tally]:
    """芝・ダートごとの成績（出走比率もここから出す）。

    `include_jump=True` にすると障害も足す。ただし**1走も無ければ出さない**
    （ほとんどのクラブ・種牡馬に障害の出走は無く、空の行が並ぶと読みにくいため）。
    既定が芝・ダートの2つなのは、距離適性やコース適性が左右2列に並べる作りだから。
    """
    kinds = [*SURFACES, ("jump", "障害")] if include_jump else list(SURFACES)
    tallies = [_tally([r for r in runs if r["surface"] == key], label) for key, label in kinds]
    if include_jump and not tallies[-1].starts:
        tallies.pop()
    return tallies


def by_venue(runs: list[dict], surface: str, venue_names: dict[str, str]) -> list[Tally]:
    """競馬場ごとの成績（コース適性）。"""
    picked = [r for r in runs if r["surface"] == surface]
    codes = sorted({r["venue_code"] for r in picked if r["venue_code"]})
    return [
        _tally([r for r in picked if r["venue_code"] == code], venue_names.get(code, code))
        for code in codes
    ]


def by_going(runs: list[dict], surface: str) -> list[Tally]:
    """馬場状態ごとの成績。"""
    picked = [r for r in runs if r["surface"] == surface]
    return [
        _tally([r for r in picked if r["going"] == going], going)
        for going in ("良", "稍重", "重", "不良")
    ]


def by_broodmare_sire(runs: list[dict], top: int = 20) -> list[Tally]:
    """母の父ごとの成績（BMS相性）。産駒の頭数が多い順。"""
    names = {r["broodmare_sire"] for r in runs if r["broodmare_sire"]}
    tallies = [_tally([r for r in runs if r["broodmare_sire"] == name], name) for name in names]
    tallies.sort(key=lambda t: (-t.horses, -t.starts, t.label))
    return tallies[:top]


def graded_wins(runs: list[dict]) -> list[dict]:
    """産駒が勝った重賞の一覧（新しい順）。"""
    wins = [
        {"race_date": r["race_date"], "race_name": r["race_name"], "grade": r["grade"],
         "horse_name": r["horse_name"], "sex": r["sex"], "age": r["age"],
         "venue_code": r["venue_code"], "surface": r["surface"], "distance_m": r["distance_m"]}
        for r in runs if r["finish_position"] == 1 and r["grade"]
    ]
    wins.sort(key=lambda w: w["race_date"], reverse=True)
    return wins


def top_progeny(runs: list[dict], top: int = 20) -> list[dict]:
    """獲得賞金の多い産駒（代表産駒）。

    賞金はJRAの結果ページに載る**5着までの本賞金**なので、着外の走は0として足す
    （DBに入っていない＝0円というだけで、取りこぼしではない）。
    """
    horses: dict[str, dict] = {}
    for run in runs:
        horse = horses.setdefault(run["horse_id"], {
            "horse_id": run["horse_id"], "horse_name": run["horse_name"], "sex": run["sex"],
            "broodmare_sire": run["broodmare_sire"], "starts": 0, "wins": 0, "top3": 0,
            "prize_man_yen": 0.0, "best_grade": None, "best_win": None,
        })
        horse["starts"] += 1
        horse["prize_man_yen"] += run["prize_man_yen"] or 0.0
        if run["finish_position"] == 1:
            horse["wins"] += 1
            if run["grade"] and (horse["best_grade"] is None or
                                 _grade_rank(run["grade"]) < _grade_rank(horse["best_grade"])):
                horse["best_grade"], horse["best_win"] = run["grade"], run["race_name"]
        if (run["finish_position"] or 99) <= 3:
            horse["top3"] += 1
    ranked = sorted(horses.values(), key=lambda h: -h["prize_man_yen"])
    return ranked[:top]


_GRADE_ORDER = ("GI", "JGI", "GII", "JGII", "GIII", "JGIII", "L")


def _grade_rank(grade: str | None) -> int:
    """格の重さ（小さいほど格上）。並べ替えにだけ使う。"""
    return _GRADE_ORDER.index(grade) if grade in _GRADE_ORDER else len(_GRADE_ORDER)


# --- 分析サマリーの空欄を埋めるためのもの -------------------------------------------

def debut_runs(runs: list[dict]) -> list[dict]:
    """産駒ごとの**新馬戦**の走（デビュー時期・デビュー時馬体重に使う）。"""
    debuts = [r for r in runs if (r["class_condition"] or "").startswith("新馬")]
    by_horse: dict[str, dict] = {}
    for run in debuts:                      # 同じ馬が2回出ることは無いが、念のため古いほうを採る
        current = by_horse.get(run["horse_id"])
        if current is None or run["race_date"] < current["race_date"]:
            by_horse[run["horse_id"]] = run
    return sorted(by_horse.values(), key=lambda r: r["race_date"])


def debut_months(runs: list[dict]) -> dict[int, int]:
    """新馬戦に出た月ごとの頭数（6月〜翌5月の並びで見る）。"""
    months: dict[int, int] = {}
    for run in debut_runs(runs):
        month = int(run["race_date"][5:7])
        months[month] = months.get(month, 0) + 1
    return months


def early_debut_rate(runs: list[dict]) -> float | None:
    """2歳の夏（6〜8月）にデビューした産駒の割合。"""
    debuts = debut_runs(runs)
    if not debuts:
        return None
    early = sum(1 for r in debuts if 6 <= int(r["race_date"][5:7]) <= 8)
    return early / len(debuts)


def debut_weight(runs: list[dict]) -> float | None:
    """デビュー時の平均馬体重（馬格）。"""
    weights = [r["horse_weight"] for r in debut_runs(runs) if r["horse_weight"]]
    return sum(weights) / len(weights) if weights else None


def winning_distance(runs: list[dict], surface: str) -> float | None:
    """勝ったレースの平均距離（勝馬距離）。"""
    distances = [
        r["distance_m"] for r in runs
        if r["finish_position"] == 1 and r["surface"] == surface and r["distance_m"]
    ]
    return sum(distances) / len(distances) if distances else None


def turf_share(runs: list[dict]) -> float | None:
    """芝・ダート出走比率のうち**芝の割合**（障害は除く）。"""
    flat = [r for r in runs if r["surface"] in ("turf", "dirt")]
    if not flat:
        return None
    return sum(1 for r in flat if r["surface"] == "turf") / len(flat)


def _horse_rows(runs: list[dict]) -> list[dict]:
    """1頭1行にまとめる（性別・生産牧場は馬の属性なので、走で数えると偏る）。"""
    seen: dict[str, dict] = {}
    for run in runs:
        seen.setdefault(run["horse_id"], run)
    return list(seen.values())


def gelding_rate(runs: list[dict]) -> float | None:
    """セン馬率（産駒の頭数に対する割合）。"""
    horses = _horse_rows(runs)
    known = [h for h in horses if h["sex"]]
    return sum(1 for h in known if h["sex"] == "セ") / len(known) if known else None


def shadai_rate(runs: list[dict]) -> float | None:
    """社台グループの牧場で生産された産駒の割合。"""
    horses = [h for h in _horse_rows(runs) if h["breeder"]]
    if not horses:
        return None
    hit = sum(1 for h in horses if any(farm in h["breeder"] for farm in SHADAI_FARMS))
    return hit / len(horses)


def classic_rate(runs: list[dict]) -> float | None:
    """クラシック6競走に出走した産駒の割合（3歳まで走った産駒を分母にする）。"""
    horses = _horse_rows(runs)
    if not horses:
        return None
    ran = {
        r["horse_id"] for r in runs
        if any((r["race_name"] or "").endswith(name) for name in CLASSIC_RACES)
    }
    # 3歳以上まで走った産駒だけを分母にする（2歳のうちは出番が来ていないため）
    eligible = {r["horse_id"] for r in runs if (r["age"] or 0) >= 3}
    return len(ran & eligible) / len(eligible) if eligible else None


def board_rate(runs: list[dict]) -> float | None:
    """掲示板入着率（5着以内）。"""
    return _tally(runs, "全体").top5_rate


# --- 全種牡馬ぶんの集計（分析サマリーの空欄と、レーダーの段階付けに使う） -------------

# レーダーの段階付け・全産駒平均の母数に入れる最低頭数（これ未満の種牡馬は外す）
MIN_LOCAL_HORSES = 5

_SHADAI_LIKE = " OR ".join(f"h.breeder LIKE '%{farm}%'" for farm in SHADAI_FARMS)
_CLASSIC_LIKE = " OR ".join(f"ra.race_name LIKE '%{name}'" for name in CLASSIC_RACES)

# 種牡馬ごとに1行。走ベースの数と、`COUNT(DISTINCT ...)` による頭ベースの数を一度に取る
_LOCAL_STATS_SQL = f"""
    SELECT h.sire AS sire,
           COUNT(*)                                        AS starts,
           COUNT(DISTINCT e.horse_id)                      AS horses,
           SUM(re.finish_position = 1)                     AS wins,
           SUM(re.finish_position <= 3)                    AS top3,
           SUM(re.finish_position <= 5)                    AS top5,
           SUM(ra.surface = 'turf')                        AS turf_starts,
           SUM(ra.surface = 'dirt')                        AS dirt_starts,
           SUM(CASE WHEN re.finish_position = 1 AND ra.surface = 'turf'
                    THEN ra.distance_m END)                AS turf_win_distance,
           SUM(CASE WHEN re.finish_position = 1 AND ra.surface = 'turf'
                    THEN 1 END)                            AS turf_wins,
           SUM(CASE WHEN re.finish_position = 1 AND ra.surface = 'dirt'
                    THEN ra.distance_m END)                AS dirt_win_distance,
           SUM(CASE WHEN re.finish_position = 1 AND ra.surface = 'dirt'
                    THEN 1 END)                            AS dirt_wins,
           COUNT(DISTINCT CASE WHEN ra.class_condition LIKE '新馬%'
                               THEN e.horse_id END)        AS debuts,
           COUNT(DISTINCT CASE WHEN ra.class_condition LIKE '新馬%'
                          AND CAST(substr(ra.race_date, 6, 2) AS INTEGER) BETWEEN 6 AND 8
                               THEN e.horse_id END)        AS early_debuts,
           SUM(CASE WHEN ra.class_condition LIKE '新馬%'
                    THEN e.horse_weight END)               AS debut_weight,
           SUM(CASE WHEN ra.class_condition LIKE '新馬%' AND e.horse_weight IS NOT NULL
                    THEN 1 END)                            AS debut_weight_n,
           COUNT(DISTINCT CASE WHEN h.sex = 'セ' THEN e.horse_id END)     AS geldings,
           COUNT(DISTINCT CASE WHEN h.sex IS NOT NULL AND h.sex <> ''
                               THEN e.horse_id END)        AS sexed,
           COUNT(DISTINCT CASE WHEN {_SHADAI_LIKE} THEN e.horse_id END)   AS shadai,
           COUNT(DISTINCT CASE WHEN h.breeder IS NOT NULL AND h.breeder <> ''
                               THEN e.horse_id END)        AS bred,
           COUNT(DISTINCT CASE WHEN e.age >= 3 THEN e.horse_id END)       AS aged3,
           COUNT(DISTINCT CASE WHEN e.age >= 3 AND ({_CLASSIC_LIKE})
                               THEN e.horse_id END)        AS classic
      FROM entries e
      JOIN horses  h  ON h.horse_id = e.horse_id
      JOIN races   ra ON ra.race_id = e.race_id
      JOIN results re ON re.race_id = e.race_id AND re.umaban = e.umaban
     WHERE h.sire IS NOT NULL AND h.sire <> ''
  GROUP BY h.sire
"""


def _ratio(numerator, denominator) -> float | None:
    if not denominator:
        return None
    return (numerator or 0) / denominator


def local_stats(conn: sqlite3.Connection) -> dict[str, dict]:
    """種牡馬ごとの手元DB集計 `{種牡馬名: 各種の合計}`。1クエリで全種牡馬ぶんを取る。

    分析サマリーの「全産駒平均」と、レーダーの段階付け（全種牡馬の中での位置）に使う。
    """
    return {r["sire"]: dict(r) for r in conn.execute(_LOCAL_STATS_SQL)}


# 分析サマリーの「産駒の中身」に出す項目。(key, 見出し, 単位, 説明)
# 社台グループ率（`shadai`）は元にした画面と同じくAEI・CPIの表に置くので、ここには入れない
LOCAL_METRIC_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("turf_share", "芝・ダート出走比率", "芝%",
     "芝への出走が全体の何割か（障害は除く）。高いほど芝向きの産駒が多い。"),
    ("turf_win_distance", "勝馬距離（芝）", "m",
     "芝で勝ったレースの平均距離。短いほどスピード型、長いほどスタミナ型。"),
    ("dirt_win_distance", "勝馬距離（ダート）", "m",
     "ダートで勝ったレースの平均距離。"),
    ("early_debut", "新馬早期デビュー割合", "%",
     "2歳の夏（6〜8月）に新馬戦を使えた産駒の割合。仕上がりの早さと体質の丈夫さの目安で、"
     "一口出資では募集した年の秋にもう走れるかに効いてくる。"),
    ("debut_weight", "馬格（デビュー時馬体重）", "kg",
     "新馬戦に出たときの平均馬体重。大きいほど成長が早いか、もともと大型の産駒が多い。"),
    ("gelding", "セン馬率", "%",
     "去勢された産駒の割合。気性の難しさの目安になる（一口ではクラシックに出られなくなる）。"),
    ("board", "掲示板入着率", "%",
     "5着以内に入った走の割合。大穴は出なくても崩れにくいか（堅実さ）の目安。"),
    ("classic", "クラシック出走馬輩出率", "%",
     "3歳まで走った産駒のうち、クラシック6競走（皐月賞・ダービー・菊花賞・"
     "桜花賞・オークス・秋華賞）に出走した割合。"),
)


def local_metric(key: str, stats: dict | None) -> float | None:
    """種牡馬1頭ぶんの集計から、その項目の値を出す。材料が無ければNone。"""
    if not stats:
        return None
    if key == "turf_share":
        return _ratio(stats["turf_starts"], (stats["turf_starts"] or 0) + (stats["dirt_starts"] or 0))
    if key == "turf_win_distance":
        return _ratio(stats["turf_win_distance"], stats["turf_wins"])
    if key == "dirt_win_distance":
        return _ratio(stats["dirt_win_distance"], stats["dirt_wins"])
    if key == "early_debut":
        return _ratio(stats["early_debuts"], stats["debuts"])
    if key == "debut_weight":
        return _ratio(stats["debut_weight"], stats["debut_weight_n"])
    if key == "gelding":
        return _ratio(stats["geldings"], stats["sexed"])
    if key == "shadai":
        return _ratio(stats["shadai"], stats["bred"])
    if key == "board":
        return _ratio(stats["top5"], stats["starts"])
    if key == "classic":
        return _ratio(stats["classic"], stats["aged3"])
    return None


def local_field(key: str, everyone: dict[str, dict]) -> float | None:
    """全産駒をひとまとめにしたときの値（＝全種牡馬平均）。合計どうしの比で出す。"""
    if not everyone:
        return None
    merged: dict[str, int] = {}
    for stats in everyone.values():
        for column, value in stats.items():
            if isinstance(value, (int, float)):
                merged[column] = merged.get(column, 0) + value
    return local_metric(key, merged)


def local_percentile(key: str, value: float | None, everyone: dict[str, dict]) -> float | None:
    """全種牡馬の中で下から何割の位置にいるか（レーダーの段階付けに使う）。"""
    if value is None:
        return None
    others = [
        v for stats in everyone.values()
        if (stats["horses"] or 0) >= MIN_LOCAL_HORSES and (v := local_metric(key, stats)) is not None
    ]
    if not others:
        return None
    below = sum(1 for v in others if v < value)
    same = sum(1 for v in others if v == value)
    return (below + same / 2) / len(others)
