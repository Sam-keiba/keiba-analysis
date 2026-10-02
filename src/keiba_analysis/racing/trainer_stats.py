"""厩舎（調教師）分析の集計。**行を受け取って数えるだけの純粋関数**（DBは `trainer_data.py`）。

「この厩舎の値」と「全厩舎の分布（平均・中央値・位置）」は、**同じ関数で全厩舎ぶんを一度に数えて**
出す。この厩舎だけ別の数え方になることがないようにするため。

## 定義（画面の注記にも書く）

- **母集団**: 美浦・栗東の厩舎のうち、その期間に `MIN_HORSES` 頭以上を出走させた厩舎
- **直近1年 / 直近3年**: DBの最終レース日から遡って365日 / 3年
- **直近10世代**: 3歳シーズン（生年＋3年の12月31日）が終わった世代のうち新しい10世代
  （`crop_range`）。その世代の馬のうち、**その厩舎で1走以上した馬**を数える（転厩馬は両方に入る）
- **続戦**: 同じ厩舎での前走から `ROTATION_MAX_DAYS` 日以内の出走。ローテ間隔・連闘・乗り替わりの分母
- **連闘**: 前走から `BACK_TO_BACK_DAYS` 日以内
- **遠征**: 美浦の厩舎は京都・阪神・中京、栗東の厩舎は東京・中山での出走の割合（`AWAY_VENUES`）。
  ローカルは札幌・函館・福島・新潟・小倉（`LOCAL_VENUES`）
- **転出**: 次の出走が他厩舎だった馬。**転入**: 前の出走が他厩舎だった馬（どちらも頭数の割合）
- **見習い騎手の起用**: 減量記号が ▲△☆◇ の騎手（見習い）が乗った出走の割合。★（見習いでない
  女性騎手の2kg減）は数えない
- **馬房数**: JRAの貸付馬房数（いちばん新しい発表）。**馬房あたり頭数**は直近1年に出走させた頭数 ÷ 馬房数
- **牝馬指数**: (牝馬の1頭平均賞金 ÷ 全出走牝馬の1頭平均賞金) − (牡・セン馬の同じ値)。
  1頭平均は「馬×年」の数で割る。性別ごとに賞金の水準が違うので、それぞれの平均で割ってから比べる
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from keiba_analysis.shared.race_name import modern_class
from keiba_analysis.shared.sire_runs import MIN_RUNS, SHADAI_FARMS, Tally

MIN_HORSES = 10            # 母集団に入れる最低頭数（その期間に出走させた管理馬）
ROTATION_MAX_DAYS = 91     # これ以内の前走を「続戦」とみる
BACK_TO_BACK_DAYS = 8      # これ以内を連闘とみる（土曜→翌週日曜の8日まで）
EARLY_DEBUT_MONTHS = (6, 7, 8)   # 2歳のこの月にデビューした馬を「早期デビュー」とする
ACTIVE_DAYS = 180          # 現役クラブ馬: 最後の出走がこの日数以内
CROPS = 10                 # 直近何世代を見るか
RECENT_YEARS = 5           # 年別推移に出す年数
THIN_RUNS = MIN_RUNS       # 出走がこれ未満の区分は薄く描く

EAST_VENUES = ("05", "06")               # 東京・中山
WEST_VENUES = ("07", "08", "09")         # 中京・京都・阪神
LOCAL_VENUES = ("01", "02", "03", "04", "10")   # 札幌・函館・福島・新潟・小倉
AWAY_VENUES = {"美浦": WEST_VENUES, "栗東": EAST_VENUES}
AWAY_LABEL = {"美浦": "関西遠征", "栗東": "関東遠征"}
APPRENTICE_MARKS = ("▲", "△", "☆", "◇")    # 見習い騎手の減量記号（★は見習いでない女性騎手）

# 得意カテゴリの格子（芝4区分・ダート2区分）。(馬場, 見出し, 下限m, 上限m)
CATEGORIES: tuple[tuple[str, str, int, int], ...] = (
    ("turf", "短距離", 0, 1400), ("turf", "マイル", 1401, 1799),
    ("turf", "中距離", 1800, 2299), ("turf", "長距離", 2300, 9999),
    ("dirt", "短距離", 0, 1400), ("dirt", "中距離", 1401, 9999),
)


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def shift_date(day: str, *, days: int = 0, years: int = 0) -> str:
    """'YYYY-MM-DD' を前後にずらす（直近1年・3年の起点に使う）。"""
    d = date.fromisoformat(day)
    if years:
        d = d.replace(year=d.year + years) if not (d.month == 2 and d.day == 29) \
            else d.replace(year=d.year + years, day=28)
    return (d + timedelta(days=days)).isoformat()


def crop_range(as_of: str, n: int = CROPS) -> tuple[int, int]:
    """直近 `n` 世代（3歳シーズンが終わった世代のうち新しい順）。as_of が2026-09なら2013〜2022。"""
    last = int(as_of[:4]) - 4 if as_of < f"{as_of[:4]}-12-31" else int(as_of[:4]) - 3
    return last - n + 1, last


def is_shadai(breeder: str | None) -> bool:
    return bool(breeder) and any(farm in breeder for farm in SHADAI_FARMS)


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


# --- 年別推移と順位 --------------------------------------------------------------------------

@dataclass(frozen=True)
class TrainerYear:
    """ある厩舎のある年。順位はその年に出走させた美浦・栗東の全厩舎の中。"""

    year: int
    starts: int
    wins: int
    prize_man_yen: float
    horses: int
    win_rank: int | None          # リーディング順位（勝利数 → 2着数 → 3着数 → 賞金の順）
    prize_rank: int | None        # 獲得賞金順位
    n_trainers: int               # その年に出走させた厩舎の数（順位の母数）
    partial: bool                 # 集計途中の年（DBの最終レース日の年）


def year_ranks(rows: list[dict]) -> dict[tuple[str, int], tuple[int, int, int]]:
    """全厩舎×年の行から `(調教師, 年) → (リーディング順位, 賞金順位, 厩舎数)`。"""
    by_year: dict[int, list[dict]] = {}
    for row in rows:
        by_year.setdefault(row["year"], []).append(row)
    ranks = {}
    for year, items in by_year.items():
        by_wins = sorted(items, key=lambda r: (-r["wins"], -r["seconds"], -r["thirds"],
                                               -r["prize_man_yen"], r["trainer_id"]))
        by_prize = sorted(items, key=lambda r: (-r["prize_man_yen"], -r["wins"], r["trainer_id"]))
        prize_rank = {r["trainer_id"]: i for i, r in enumerate(by_prize, 1)}
        for i, r in enumerate(by_wins, 1):
            ranks[(r["trainer_id"], year)] = (i, prize_rank[r["trainer_id"]], len(items))
    return ranks


def trainer_years(rows: list[dict], trainer_id: str, *, as_of: str,
                  last_n: int | None = RECENT_YEARS) -> list[TrainerYear]:
    """その厩舎の年別成績（古い順）。`last_n` 年まで（Noneなら全年）。出走の無い年は入らない。"""
    ranks = year_ranks(rows)
    current = int(as_of[:4])
    years = sorted((r for r in rows if r["trainer_id"] == trainer_id), key=lambda r: r["year"])
    if last_n:
        years = [r for r in years if r["year"] > current - last_n]
    out = []
    for r in years:
        win_rank, prize_rank, n = ranks[(trainer_id, r["year"])]
        out.append(TrainerYear(
            year=r["year"], starts=r["starts"], wins=r["wins"], prize_man_yen=r["prize_man_yen"],
            horses=r["horses"], win_rank=win_rank, prize_rank=prize_rank, n_trainers=n,
            partial=r["year"] == current,
        ))
    return out


# --- 直近の各走から数えるもの（傾向・牝馬指数・得意カテゴリ） --------------------------------

@dataclass
class Behavior:
    """1厩舎ぶんの数え上げ（直近3年の各走から）。率は `behavior_value` で出す。"""

    stable: str | None = None
    starts: int = 0
    horses: set = field(default_factory=set)
    club_horses: set = field(default_factory=set)
    starts_1y: int = 0
    horses_1y: set = field(default_factory=set)
    followups: int = 0                         # 続戦（同じ厩舎の前走から ROTATION_MAX_DAYS 日以内）
    gaps: list = field(default_factory=list)   # 続戦の間隔（日）
    back_to_back: int = 0
    jockey_changes: int = 0
    apprentice: int = 0                        # 見習い騎手が乗った出走
    away: int = 0                              # 関西／関東遠征
    local: int = 0
    transferred_out: set = field(default_factory=set)
    transferred_in: set = field(default_factory=set)
    # 牝馬指数の材料: {(馬, 年): 賞金} を性別ごとに
    prize_by_sex: dict = field(default_factory=lambda: {"牝": {}, "牡セ": {}})
    # 得意カテゴリ: {(馬場, 見出し): [出走, 勝利, 3着内]}
    categories: dict = field(default_factory=dict)


def _category(surface: str | None, distance: int | None) -> tuple[str, str] | None:
    for cat_surface, label, low, high in CATEGORIES:
        if surface == cat_surface and distance is not None and low <= distance <= high:
            return cat_surface, label
    return None


def behavior_by_trainer(runs: list[dict], *, stables: dict[str, str], clubs: set[str],
                        as_of: str) -> dict[str, Behavior]:
    """`trainer_data.window_runs` の各走を厩舎ごとに数える（全厩舎ぶんを1回で）。"""
    since_1y = shift_date(as_of, days=-365)
    out: dict[str, Behavior] = {}
    for run in runs:
        tid = run["trainer_id"]
        b = out.get(tid)
        if b is None:
            b = out[tid] = Behavior(stable=stables.get(tid))
        horse = run["horse_id"]
        b.starts += 1
        b.horses.add(horse)
        if run["owner_id"] in clubs:
            b.club_horses.add(horse)
        if run["race_date"] >= since_1y:
            b.starts_1y += 1
            b.horses_1y.add(horse)
        prev_date, prev_trainer = run["prev_date"], run["prev_trainer"]
        if prev_trainer is not None and prev_trainer != tid:
            b.transferred_in.add(horse)
        if run["next_trainer"] is not None and run["next_trainer"] != tid:
            b.transferred_out.add(horse)
        if prev_date and prev_trainer == tid:
            gap = _days(run["race_date"], prev_date)
            if gap <= ROTATION_MAX_DAYS:
                b.followups += 1
                b.gaps.append(gap)
                b.back_to_back += gap <= BACK_TO_BACK_DAYS
                b.jockey_changes += (run["jockey_id"] or "") != (run["prev_jockey"] or "")
        b.apprentice += run.get("kinryo_mark") in APPRENTICE_MARKS
        venue = run["venue_code"]
        b.away += venue in AWAY_VENUES.get(b.stable or "", ())
        b.local += venue in LOCAL_VENUES
        sex = "牝" if run["sex"] == "牝" else "牡セ"
        key = (horse, run["race_date"][:4])
        bucket = b.prize_by_sex[sex]
        bucket[key] = bucket.get(key, 0.0) + (run["prize_man_yen"] or 0.0)
        cat = _category(run["surface"], run["distance_m"])
        if cat:
            tally = b.categories.setdefault(cat, [0, 0, 0])
            tally[0] += 1
            tally[1] += run["finish_position"] == 1
            tally[2] += run["finish_position"] is not None and run["finish_position"] <= 3
    return out


def sex_field(behaviors: dict[str, Behavior]) -> dict[str, float | None]:
    """全出走馬の性別ごとの1頭平均賞金（「馬×年」1つあたり）。牝馬指数の分母。"""
    out = {}
    for sex in ("牝", "牡セ"):
        prize = sum(sum(b.prize_by_sex[sex].values()) for b in behaviors.values())
        count = sum(len(b.prize_by_sex[sex]) for b in behaviors.values())
        out[sex] = _ratio(prize, count)
    return out


def filly_index(b: Behavior, field_by_sex: dict[str, float | None],
                min_each: int = 5) -> float | None:
    """牝馬指数。牝馬・牡セン馬のどちらかが `min_each` 馬年に満たなければ出さない。"""
    parts = []
    for sex in ("牝", "牡セ"):
        items = b.prize_by_sex[sex]
        if len(items) < min_each or not field_by_sex.get(sex):
            return None
        parts.append(sum(items.values()) / len(items) / field_by_sex[sex])
    return parts[0] - parts[1]


# --- 世代から数えるもの（勝ち上がり・クラシック・重賞・デビュー・社台） ------------------------

@dataclass
class CropCounts:
    """1厩舎ぶんの、直近10世代の馬の数え上げ。"""

    horses: int = 0
    winners: int = 0
    classic: int = 0
    graded: int = 0
    shadai: int = 0
    bred: int = 0                                     # 生産牧場が分かる馬
    debuts: int = 0                                   # この厩舎でデビューした馬
    early_debuts: int = 0
    debut_days: list = field(default_factory=list)    # 2歳の1月1日からデビューまでの日数
    starts_to_win: list = field(default_factory=list)  # この厩舎でデビューし勝ち上がった馬の、初勝利までの出走数


def crops_by_trainer(horses: list[dict]) -> dict[str, CropCounts]:
    """`trainer_data.crop_horses` の馬を、走らせた厩舎ごとに数える（転厩馬は両方に入る）。"""
    out: dict[str, CropCounts] = {}
    for h in horses:
        for tid in h["trainers"]:
            if not tid:
                continue
            c = out.setdefault(tid, CropCounts())
            c.horses += 1
            c.winners += h["first_win_n"] is not None
            c.classic += bool(h["classic"])
            c.graded += bool(h["graded_winner"])
            if h["breeder"]:
                c.bred += 1
                c.shadai += is_shadai(h["breeder"])
        tid = h["debut_trainer"]
        if tid and h["debut_date"] and h["crop"]:
            c = out.setdefault(tid, CropCounts())
            c.debuts += 1
            debut = date.fromisoformat(h["debut_date"])
            c.debut_days.append((debut - date(h["crop"] + 2, 1, 1)).days)
            c.early_debuts += debut.year == h["crop"] + 2 and debut.month in EARLY_DEBUT_MONTHS
            if h["first_win_n"] is not None:
                c.starts_to_win.append(h["first_win_n"])
    return out


# --- 指標の値と分布 ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrendSpec:
    """傾向スライダー1本。`source` は値の出どころ（'behavior' か 'crop'）。"""

    key: str
    label: str
    low: str
    high: str
    unit: str
    description: str
    source: str


TRENDS: tuple[TrendSpec, ...] = (
    TrendSpec("club_share", "クラブ馬比率", "少ない", "多い", "%",
              "直近3年に出走させた管理馬のうち、一口クラブの馬の割合。", "behavior"),
    TrendSpec("debut_timing", "新馬デビュー時期", "早い", "遅い", "日",
              "この厩舎でデビューした馬の、2歳の1月1日からデビューまでの日数（中央値）。", "crop"),
    TrendSpec("early_debut", "2歳夏デビューの割合", "少ない", "多い", "%",
              "この厩舎でデビューした馬のうち、2歳の6〜8月にデビューした割合。", "crop"),
    TrendSpec("starts_to_win", "勝ち上がりまでの出走回数", "少ない", "多い", "走",
              "この厩舎でデビューして勝ち上がった馬の、初勝利までの出走回数（平均）。", "crop"),
    TrendSpec("rotation", "続戦時のローテ間隔", "短い", "長い", "日",
              f"同じ厩舎での前走から{ROTATION_MAX_DAYS}日以内に使ったときの間隔（中央値）。", "behavior"),
    TrendSpec("back_to_back", "連闘の割合", "少ない", "多い", "%",
              f"続戦のうち、前走から{BACK_TO_BACK_DAYS}日以内に使った割合。", "behavior"),
    TrendSpec("away", "東西の遠征", "少ない", "多い", "%",
              "美浦の厩舎は京都・阪神・中京、栗東の厩舎は東京・中山で走らせた割合"
              "（同じ所属の厩舎どうしで比べる）。", "behavior"),
    TrendSpec("local", "ローカル遠征", "少ない", "多い", "%",
              "札幌・函館・福島・新潟・小倉で走らせた割合。", "behavior"),
    TrendSpec("jockey_change", "騎手の乗り替わり", "少ない", "多い", "%",
              "続戦のうち、前走と騎手が変わった割合。", "behavior"),
    TrendSpec("apprentice", "見習い騎手の起用", "少ない", "多い", "%",
              "直近3年の出走のうち、見習い騎手（減量記号▲△☆◇）が乗った割合。", "behavior"),
    TrendSpec("transfer_out", "転出率（当厩舎→他厩舎）", "少ない", "多い", "%",
              "直近3年に走らせた馬のうち、次の出走が他厩舎だった馬の割合。", "behavior"),
    TrendSpec("transfer_in", "転入率（他厩舎→当厩舎）", "少ない", "多い", "%",
              "直近3年に走らせた馬のうち、前の出走が他厩舎だった馬の割合。", "behavior"),
)


def behavior_value(key: str, b: Behavior | None) -> float | None:
    if b is None:
        return None
    n = len(b.horses)
    if key == "club_share":
        return _ratio(len(b.club_horses), n)
    if key == "rotation":
        return float(statistics.median(b.gaps)) if b.gaps else None
    if key == "back_to_back":
        return _ratio(b.back_to_back, b.followups)
    if key == "jockey_change":
        return _ratio(b.jockey_changes, b.followups)
    if key == "away":
        return _ratio(b.away, b.starts) if b.stable in AWAY_VENUES else None
    if key == "local":
        return _ratio(b.local, b.starts)
    if key == "apprentice":
        return _ratio(b.apprentice, b.starts)
    if key == "transfer_out":
        return _ratio(len(b.transferred_out), n)
    if key == "transfer_in":
        return _ratio(len(b.transferred_in), n)
    if key == "stable_size":
        return float(len(b.horses_1y)) if b.horses_1y else None
    if key == "starts_per_horse":
        return _ratio(b.starts_1y, len(b.horses_1y))
    return None


def crop_value(key: str, c: CropCounts | None) -> float | None:
    if c is None:
        return None
    if key == "debut_timing":
        return float(statistics.median(c.debut_days)) if c.debut_days else None
    if key == "early_debut":
        return _ratio(c.early_debuts, c.debuts)
    if key == "starts_to_win":
        return _ratio(sum(c.starts_to_win), len(c.starts_to_win))
    if key == "win_rate":
        return _ratio(c.winners, c.horses)
    if key == "classic":
        return _ratio(c.classic, c.horses)
    if key == "graded":
        return _ratio(c.graded, c.horses)
    if key == "shadai":
        return _ratio(c.shadai, c.bred)
    return None


def eligible_behavior(behaviors: dict[str, Behavior], min_horses: int = MIN_HORSES) -> dict[str, Behavior]:
    """母集団（美浦・栗東で、直近3年に `min_horses` 頭以上を走らせた厩舎）。"""
    return {t: b for t, b in behaviors.items()
            if b.stable in AWAY_VENUES and len(b.horses) >= min_horses}


def eligible_crops(crops: dict[str, CropCounts], jra: set[str],
                   min_horses: int = MIN_HORSES) -> dict[str, CropCounts]:
    """母集団（美浦・栗東で、直近10世代の馬を `min_horses` 頭以上走らせた厩舎）。"""
    return {t: c for t, c in crops.items() if t in jra and c.horses >= min_horses}


def percentile(values: list[float], value: float | None) -> float | None:
    """`values` の中で `value` が下から何割か（0.0〜1.0。同じ値は半分ずつ数える）。"""
    if value is None or not values:
        return None
    below = sum(v < value for v in values)
    same = sum(v == value for v in values)
    return (below + same / 2) / len(values)


@dataclass(frozen=True)
class Position:
    """全厩舎の中での位置（傾向スライダー1本ぶん）。"""

    spec: TrendSpec
    value: float | None
    median: float | None
    percentile: float | None
    n_trainers: int


def trend_positions(trainer_id: str, behaviors: dict[str, Behavior],
                    crops: dict[str, CropCounts], jra: set[str],
                    min_horses: int = MIN_HORSES) -> list[Position]:
    """傾向スライダーの各項目。遠征だけは同じ所属（美浦／栗東）の厩舎どうしで比べる。"""
    pool_b = eligible_behavior(behaviors, min_horses)
    pool_c = eligible_crops(crops, jra, min_horses)
    mine_b, mine_c = behaviors.get(trainer_id), crops.get(trainer_id)
    out = []
    for spec in TRENDS:
        if spec.source == "behavior":
            value = behavior_value(spec.key, mine_b)
            pool = pool_b.values()
            if spec.key == "away" and mine_b is not None:
                pool = [b for b in pool if b.stable == mine_b.stable]
            values = [v for b in pool if (v := behavior_value(spec.key, b)) is not None]
        else:
            value = crop_value(spec.key, mine_c)
            values = [v for c in pool_c.values() if (v := crop_value(spec.key, c)) is not None]
        out.append(Position(spec, value, statistics.median(values) if values else None,
                            percentile(values, value), len(values)))
    return out


# --- 主要指標（表） --------------------------------------------------------------------------

@dataclass(frozen=True)
class Indicator:
    """主要指標の表の1行。`average` は全厩舎平均（母集団の合計どうしの比。頭数は1厩舎あたり）。"""

    key: str
    label: str
    value: float | None
    average: float | None
    unit: str
    description: str


def indicators(trainer_id: str, behaviors: dict[str, Behavior], crops: dict[str, CropCounts],
               jra: set[str], *, field_by_sex: dict[str, float | None], stalls: dict[str, int],
               min_horses: int = MIN_HORSES) -> list[Indicator]:
    """AEI・CPI以外の主要指標（AEI・CPIは `trainer_index`）。`stalls` は調教師ID → 貸付馬房数。"""
    pool_b = eligible_behavior(behaviors, min_horses)
    pool_c = eligible_crops(crops, jra, min_horses)
    b, c = behaviors.get(trainer_id), crops.get(trainer_id)

    def pooled_crop(attr: str, denominator: str = "horses") -> float | None:
        return _ratio(sum(getattr(x, attr) for x in pool_c.values()),
                      sum(getattr(x, denominator) for x in pool_c.values()))

    active = [x for x in pool_b.values() if x.horses_1y]
    with_stalls = {t: x for t, x in pool_b.items() if x.horses_1y and stalls.get(t)}
    mine_stalls = stalls.get(trainer_id)
    return [
        Indicator("stalls", "馬房数", float(mine_stalls) if mine_stalls else None,
                  _ratio(sum(stalls[t] for t in with_stalls), len(with_stalls)), "馬房",
                  "JRAが貸し付けている馬房の数（いちばん新しい発表）。成績などで毎年変わり、厩舎の規模を表す。"),
        Indicator("horses_per_stall", "馬房あたり頭数",
                  _ratio(len(b.horses_1y), mine_stalls) if b and mine_stalls else None,
                  _ratio(sum(len(x.horses_1y) for x in with_stalls.values()),
                         sum(stalls[t] for t in with_stalls)), "頭/馬房",
                  "直近1年に出走させた頭数 ÷ 馬房数。多いほど馬を入れ替えながら使っている。"),
        Indicator("starts_per_horse", "平均出走回数", behavior_value("starts_per_horse", b),
                  _ratio(sum(x.starts_1y for x in active), sum(len(x.horses_1y) for x in active)),
                  "走", "直近1年の、管理馬1頭あたりの出走回数。多いほどレースをよく使う。"),
        Indicator("win_rate", "勝ち上がり率", crop_value("win_rate", c), pooled_crop("winners"),
                  "%", "直近10世代でこの厩舎が走らせた馬のうち、JRAで1勝以上した馬の割合"
                  "（勝ったのが転厩先でも数える）。"),
        Indicator("classic", "クラシック出走馬輩出率", crop_value("classic", c), pooled_crop("classic"),
                  "%", "直近10世代でこの厩舎が走らせた馬のうち、クラシック（皐月賞・日本ダービー・"
                  "菊花賞・桜花賞・オークス・秋華賞）に出走した馬の割合。"),
        Indicator("graded", "重賞馬輩出率", crop_value("graded", c), pooled_crop("graded"),
                  "%", "直近10世代でこの厩舎が走らせた馬のうち、平地の重賞（GI〜GIII）を勝った馬の割合。"),
        Indicator("filly_index", "牝馬指数", filly_index(b, field_by_sex) if b else None, 0.0, "±",
                  "牝馬と牡・セン馬それぞれの稼ぎを、全出走馬の同じ性別の平均と比べた差（直近3年）。"
                  "0より上なら牝馬のほうが得意。"),
        Indicator("shadai", "社台グループ率", crop_value("shadai", c), pooled_crop("shadai", "bred"),
                  "%", "直近10世代でこの厩舎が走らせた馬のうち、社台グループの主要牧場の生産馬の割合。"),
    ]


# --- 得意カテゴリ ------------------------------------------------------------------------------

@dataclass(frozen=True)
class CategoryCell:
    surface: str
    label: str
    starts: int
    wins: int
    top3: int
    top3_rate: float | None
    field_rate: float | None      # 母集団の全厩舎の、同じ区分の複勝率
    thin: bool                    # 出走が THIN_RUNS 未満（率が跳ねやすい）

    @property
    def lift(self) -> float | None:
        """全厩舎の複勝率を1.00としたときの倍率（得意度）。"""
        return _ratio(self.top3_rate, self.field_rate) if self.top3_rate is not None else None


def category_grid(trainer_id: str, behaviors: dict[str, Behavior],
                  thin_runs: int = THIN_RUNS) -> list[CategoryCell]:
    """芝4区分・ダート2区分の複勝率と、全厩舎の同じ区分の複勝率（直近3年）。"""
    pool = eligible_behavior(behaviors)
    mine = behaviors.get(trainer_id)
    cells = []
    for surface, label, _low, _high in CATEGORIES:
        starts, wins, top3 = (mine.categories.get((surface, label), [0, 0, 0]) if mine else [0, 0, 0])
        field_starts = sum(b.categories.get((surface, label), [0, 0, 0])[0] for b in pool.values())
        field_top3 = sum(b.categories.get((surface, label), [0, 0, 0])[2] for b in pool.values())
        cells.append(CategoryCell(surface, label, starts, wins, top3, _ratio(top3, starts),
                                  _ratio(field_top3, field_starts), starts < thin_runs))
    return cells


# --- 1厩舎ぶんの走から（代表馬・重賞・最近・クラブ） ------------------------------------------

def _started(run: dict) -> bool:
    return (run.get("finish_status") or "") not in ("取消", "除外")


def representative_horses(runs: list[dict], top: int = 20) -> list[dict]:
    """この厩舎にいた間の賞金が多い馬（賞金・勝利・出走・いちばん格の高い勝ち鞍）。"""
    by_horse: dict[str, dict] = {}
    for run in runs:
        if not _started(run):
            continue
        h = by_horse.setdefault(run["horse_id"], {
            "horse_id": run["horse_id"], "horse_name": run["horse_name"], "sex": run["sex"],
            "starts": 0, "wins": 0, "prize_man_yen": 0.0, "best": None, "first": run["race_date"],
            "last": run["race_date"],
        })
        h["starts"] += 1
        h["prize_man_yen"] += run["prize_man_yen"] or 0.0
        h["first"], h["last"] = min(h["first"], run["race_date"]), max(h["last"], run["race_date"])
        if run["finish_position"] == 1:
            h["wins"] += 1
            if run["grade"] and (h["best"] is None or _grade_order(run["grade"]) < _grade_order(h["best"]["grade"])):
                h["best"] = run
    return sorted(by_horse.values(), key=lambda h: -h["prize_man_yen"])[:top]


GRADE_ORDER = ("GI", "GII", "GIII", "JGI", "JGII", "JGIII", "L")


def _grade_order(grade: str) -> int:
    return GRADE_ORDER.index(grade) if grade in GRADE_ORDER else len(GRADE_ORDER)


def graded_wins(runs: list[dict]) -> list[dict]:
    """重賞（GI〜GIII・障害重賞）の勝ち鞍（新しい順）。オープン特別（L）は入れない。"""
    return [r for r in runs if r["finish_position"] == 1 and r["grade"]
            and r["grade"] != "L" and _started(r)]


def recent_wins(runs: list[dict], n: int = 30) -> list[dict]:
    return [r for r in runs if r["finish_position"] == 1 and _started(r)][:n]


def recent_runs(runs: list[dict], n: int = 50) -> list[dict]:
    return runs[:n]


def club_breakdown(runs: list[dict], clubs: dict[str, str]) -> list[dict]:
    """クラブ別の通算（この厩舎にいた間）。頭数・出走・勝ち上がり率・1頭平均賞金。"""
    by_club: dict[str, dict] = {}
    for run in runs:
        label = clubs.get(run["owner_id"])
        if label is None or not _started(run):
            continue
        c = by_club.setdefault(label, {"club": label, "horses": set(), "winners": set(),
                                       "starts": 0, "prize_man_yen": 0.0})
        c["horses"].add(run["horse_id"])
        c["starts"] += 1
        c["prize_man_yen"] += run["prize_man_yen"] or 0.0
        if run["finish_position"] == 1:
            c["winners"].add(run["horse_id"])
    out = []
    for c in by_club.values():
        n = len(c["horses"])
        out.append({"club": c["club"], "horses": n, "starts": c["starts"],
                    "win_rate": _ratio(len(c["winners"]), n),
                    "prize_per_horse": _ratio(c["prize_man_yen"], n)})
    return sorted(out, key=lambda c: (-c["horses"], c["club"]))


def active_club_horses(runs: list[dict], latest: dict[str, dict], clubs: dict[str, str],
                       *, as_of: str, active_days: int = ACTIVE_DAYS) -> list[dict]:
    """現役のクラブ馬（最後の出走が `active_days` 日以内で、その走がこの厩舎・クラブの馬）。

    `latest` は馬 → その馬の**DB全体での**最後の走（転厩していったら外すため）。
    クラスは**直近に走ったクラス**（勝って上がった直後は1つ下に見える）。
    """
    since = shift_date(as_of, days=-active_days)
    trainer_id = runs[0]["trainer_id"] if runs else None
    out = []
    for horse_id in dict.fromkeys(r["horse_id"] for r in runs):
        last = latest.get(horse_id)
        if not last or last["trainer_id"] != trainer_id or last["race_date"] < since:
            continue
        club = clubs.get(last["owner_id"])
        if club is None:
            continue
        out.append({**last, "club": club})
    return out


# --- 区分ごとの成績（起用騎手・馬主・得意カテゴリ・性別のタブ） ---------------------------------

@dataclass(frozen=True)
class Record:
    """ある区分の成績。率はすべて**出走を分母**にする。単勝回収率は「勝った走の単勝オッズ×100 ÷ 出走×100」。

    単勝オッズが無い走（ごく一部）は、回収率の分母からも外す（`odds_starts`）。
    """

    label: str
    starts: int = 0
    wins: int = 0
    top2: int = 0
    top3: int = 0
    top5: int = 0
    horses: int = 0
    prize_man_yen: float = 0.0
    odds_starts: int = 0         # 単勝オッズが分かる出走
    win_return: float = 0.0      # 勝った走の単勝オッズの合計（100円あたり何倍か）

    def _rate(self, n: int) -> float | None:
        return n / self.starts if self.starts else None

    @property
    def win_rate(self) -> float | None:
        return self._rate(self.wins)

    @property
    def top2_rate(self) -> float | None:
        return self._rate(self.top2)

    @property
    def top3_rate(self) -> float | None:
        return self._rate(self.top3)

    @property
    def roi(self) -> float | None:
        """単勝回収率（1.0＝100%）。"""
        return self.win_return / self.odds_starts if self.odds_starts else None

    def is_thin(self, thin_runs: int = THIN_RUNS) -> bool:
        return self.starts < thin_runs

    def to_tally(self) -> Tally:
        """`sire_chart.build_rate_bar_spec` に渡せる形（`sire_runs.Tally`）。"""
        return Tally(label=self.label, horses=self.horses, starts=self.starts, wins=self.wins,
                     top3=self.top3, top5=self.top5, prize_man_yen=self.prize_man_yen)


def record(label: str, runs: list[dict]) -> Record:
    """走の束を1つの `Record` にまとめる（取消・除外は数えない）。"""
    started = [r for r in runs if _started(r)]
    pos = [r["finish_position"] for r in started]
    with_odds = [r for r in started if r.get("win_odds")]
    return Record(
        label=label, starts=len(started),
        wins=sum(p == 1 for p in pos), top2=sum(p is not None and p <= 2 for p in pos),
        top3=sum(p is not None and p <= 3 for p in pos), top5=sum(p is not None and p <= 5 for p in pos),
        horses=len({r["horse_id"] for r in started}),
        prize_man_yen=sum(r["prize_man_yen"] or 0.0 for r in started),
        odds_starts=len(with_odds),
        win_return=sum(r["win_odds"] for r in with_odds if r["finish_position"] == 1),
    )


def runs_since(runs: list[dict], since: str | None) -> list[dict]:
    """`since`（'YYYY-MM-DD'）以降の走。None なら全期間。"""
    return runs if since is None else [r for r in runs if r["race_date"] >= since]


def _grouped(runs: list[dict], key, order: list[str] | None = None) -> list[Record]:
    groups: dict[str, list[dict]] = {}
    for r in runs:
        label = key(r)
        if label is not None:
            groups.setdefault(label, []).append(r)
    labels = order if order is not None else list(groups)
    return [record(label, groups[label]) for label in labels if label in groups]


def by_jockey(runs: list[dict], top: int = 20) -> list[Record]:
    """起用した騎手ごと（乗せた回数の多い順に `top` 人）。"""
    records = _grouped(runs, lambda r: r.get("jockey_name") or r.get("jockey_id"))
    return sorted(records, key=lambda x: (-x.starts, x.label))[:top]


def by_owner(runs: list[dict], clubs: dict[str, str], top: int = 20) -> list[Record]:
    """馬主ごと（出走の多い順に `top`）。クラブは表示名、それ以外は `owners.owner_name`（10文字で切れる）。"""
    def label(r: dict) -> str | None:
        return clubs.get(r.get("owner_id")) or r.get("owner_name") or r.get("owner_id")
    records = _grouped(runs, label)
    return sorted(records, key=lambda x: (-x.horses, -x.starts, x.label))[:top]


def club_vs_others(runs: list[dict], clubs: dict[str, str]) -> list[Record]:
    """一口クラブの馬と、それ以外（個人・法人）の馬の比較。"""
    return _grouped(runs, lambda r: "一口クラブ" if r.get("owner_id") in clubs else "個人・法人",
                    ["一口クラブ", "個人・法人"])


def by_category(runs: list[dict]) -> list[Record]:
    """芝4区分・ダート2区分（得意カテゴリの格子と同じ区切り）。障害は別の1区分。"""
    def label(r: dict) -> str | None:
        if r["surface"] == "jump":
            return "障害"
        cat = _category(r["surface"], r["distance_m"])
        return f"{'芝' if cat[0] == 'turf' else 'ダ'}・{cat[1]}" if cat else None
    order = [f"{'芝' if s == 'turf' else 'ダ'}・{label}" for s, label, _l, _h in CATEGORIES] + ["障害"]
    return _grouped(runs, label, order)


CLASS_LABELS = ("新馬", "未勝利", "1勝クラス", "2勝クラス", "3勝クラス", "オープン特別", "重賞", "障害")


def race_class(run: dict) -> str | None:
    """レースの格（新馬〜3勝クラス・オープン特別・重賞・障害）。旧クラス名は今の呼称に寄せる。"""
    if run["surface"] == "jump":
        return "障害"
    if run.get("grade") in ("GI", "GII", "GIII"):
        return "重賞"
    text = modern_class(run.get("class_condition"))
    for label in CLASS_LABELS[:5]:
        if text.startswith(label):
            return label
    return "オープン特別" if text.startswith("オープン") else None


def by_class(runs: list[dict]) -> list[Record]:
    return _grouped(runs, race_class, list(CLASS_LABELS))


def by_venue(runs: list[dict]) -> list[Record]:
    """競馬場ごと（JRAの10場の番号順）。"""
    names = dict(sorted({(r["venue_code"], r["venue_name"]) for r in runs}))
    return _grouped(runs, lambda r: r["venue_name"], list(names.values()))


SEX_LABELS = ("牡", "牝", "セ")


def by_sex(runs: list[dict]) -> list[Record]:
    return _grouped(runs, lambda r: r.get("sex") if r.get("sex") in SEX_LABELS else None, list(SEX_LABELS))


AGE_LABELS = ("2歳", "3歳", "4歳", "5歳", "6歳以上")


def _age_label(age: int | None) -> str | None:
    if not age:
        return None
    return f"{age}歳" if age <= 5 else "6歳以上"


def by_sex_age(runs: list[dict]) -> dict[str, list[Record]]:
    """性別ごとの、年齢別の成績 `{性別: [2歳, 3歳, …]}`。"""
    return {sex: _grouped([r for r in runs if r.get("sex") == sex],
                          lambda r: _age_label(r.get("age")), list(AGE_LABELS))
            for sex in SEX_LABELS}
