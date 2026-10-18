"""予想ボードのTier（A/B/C/D）の自動仮配置。

**これはたたき台を作るためのもので、最終判断は画面上で手で動かす前提。**

点数を足して順位で切るのではなく、**その馬の「推定レベル」を今回のクラスと比べる**。
こうすると閾値の意味がそのまま日本語になり、内訳も説明できる。

    推定レベル = 実績レベル（戦ってきた相手）+ 適性補正（ペース・コース）
    1走の値    = クラス×着順 と「倒した相手（その相手との秒差）」を混ぜたもの
    margin     = 推定レベル − 今回のクラスのレベル

    B/C/D … margin の閾値で決まる（1頭ずつ決まる）
    A     … **そのレースで2位以下を離しているか**で決まる（レース全体を見ないと決まらない）

段の境目は「何%の馬をそこに入れるか」ではなく、**実測でどれだけ走る層か**で引いている:

    A … 勝率30%以上（実測40.8%）
    B … 勝率20%前後（実測20.2%）
    C … 複勝率30%前後（実測27.8%）
    D … それ未満（実測 勝率3.2%・複勝率11.8%）

**回収率は盤で扱わない。** どの段も100%に届かないので、段の名前を「期待値あり」に
すると「買えば得」と読めてしまう。妙味は、映像や展開を見て手で動かすところで拾う。

**Aだけ決め方が違う**のは、閾値ではどう線を引いてもAの勝率が20%程度で頭打ちに
なったから（1レースで最上位の1頭だけを選んでも21%が天井だった）。着順とクラスしか
材料にしていないので、絶対的な強さの精度はそこまでしか出ない。いっぽう「同じレースの
中でどれだけ抜けているか」は相対の話なので、同じ材料でももっと効く。実測で勝率は
33.4%になり、1番人気（約33%）と並んだ。「倒した相手」を入れてからは40.8%。
そのかわり**Aは95%のレースで出ない**。

**倒した相手**: クラスと着順だけだと、同じGII勝ちでも相手が弱いのか世代トップなのかが
分からない。そこで1走ごとに、そのレースの上位5頭（自分を除く）の強さと、その馬との
タイム差から「この走から読める自分のレベル」を出し、クラス×着順の値と混ぜる。
例: ローズS（GII）で2着エンネ（フローラS 2着・オークス4番人気）に0.5秒差で勝った走は、
相手が強いぶん、ただのGII勝ちより高くなる。負けた走も「誰に何秒負けたか」で読む。
実測（2024年以降9,300レース）で、margin の順と着順の順位相関が 0.319 → 0.401、
レース内で margin 1番の馬の勝率が 21.1% → 23.6% に上がった。

実績レベルが主軸で、適性は最大でも±0.9段ぶんしか動かさない。「未勝利しか勝って
いない馬」が適性だけでGIIのAに来ることはなく、実績が拮抗している馬どうしでだけ
適性が順番を入れ替える。

改善の余地（次のフェーズ以降）:
- 斤量・騎手・馬体重の増減・休み明けを見ていない
- 相手の強さはクラス×着順と人気だけで見ている（相手の「倒した相手」までは追わない）
- 閾値は過去レースでの回収率で較正した暫定値（README参照）
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace

from keiba_analysis.racing import horse_stats, pace
from keiba_analysis.shared.race_name import modern_class

# クラスの序列。1段＝クラス1つぶん。DBの class_condition / grade から引く。
# grade が入っているレースの class_condition は実測で100%「オープン」系なので、
# grade を先に見て、無ければ class_condition を見れば1本の序列になる。
CLASS_LEVEL: dict[str, float] = {
    "新馬": 0.0, "未勝利": 0.0, "1勝クラス": 1.0, "2勝クラス": 2.0,
    "3勝クラス": 3.0, "オープン": 4.0,
}
GRADE_LEVEL: dict[str, float] = {
    "L": 4.5, "GIII": 5.0, "GII": 6.0, "GI": 7.0,
    "JGIII": 5.0, "JGII": 6.0, "JGI": 7.0,
}

# 1走の「そのレベルで何ができたか」。勝ったなら1つ上のクラス相当とみなす。
WIN_BONUS = 1.0
PLACE_BONUS = 0.5          # 2〜3着
TOP_SHARE = 0.3            # 上位30%以内なら「通用した」（±0）
# それ以外は、そのレベルでは通用しなかった。クラス2段ぶん引く。
# −1.5だった頃は「GIで17着（7.0−1.5=5.5）」が「オープンを勝った馬（5.0）」より
# 高くなり、格上に出て負け続けるだけでレベルが積み上がっていた。
# −3.0にすると「GIで大敗（4.0）」が「3勝クラスを勝った（4.0）」と並ぶ。
BEATEN_PENALTY = -3.0

RECENT_RUNS = 5            # 実績レベルを見る直近の走数
# そのうち上位何走を採るか。2走だと「2走だけ良くて3走は壊滅」を拾いすぎたので3走にした。
BEST_RUNS = 3

# --- 倒した相手 -------------------------------------------------------------------
# 過去走のレースで、自分を除く上位何頭を「相手」として見るか。
OPPONENTS = 5
# 相手の強さ = 相手自身の直近5走の上位3走の平均。1走の値はクラス×着順（run_value）に、
# **その走での人気**を足したもの。「GIで4番人気」は市場がその馬をGI上位とみていた証拠。
# 1番人気で +POPULARITY_WEIGHT/2、最低人気で −POPULARITY_WEIGHT/2（段）。
POPULARITY_WEIGHT = 3.0
# 秒差を段に直す係数。**1,000mあたり1秒の差が何段か**（距離で割ってそろえる）。
# 2000mで0.5秒差 → 1,000mあたり0.25秒 → 1段。
SEC_TO_LEVEL = 4.0
# 1走の値 = (1−w) × クラス×着順 + w × 相手から読んだ値（相手ごとの値の中央値）。
# 中央値にするのは、相手の1頭が大敗続きで実績が極端に低い、などで壊れないため。
OPPONENT_WEIGHT = 0.75
# 3つの係数は、2024年以降9,300レースを当時の材料だけで採点し直した格子探索で決めた
# （k=1〜8・w=0.25〜1・人気0〜4。この辺りは平らで、どれを選んでも順位相関0.39〜0.40）。

# 適性補正の効き幅（段）。合計で最大±0.9段＝クラス1段より少し弱い。
PACE_WEIGHT = 0.5
COURSE_WEIGHT = 0.4

# 出走が少ない馬の複勝率を平均に寄せる強さ。3走の「複勝率100%」を真に受けないため。
PRIOR_RATE = 0.33          # 全体のおおよその複勝率（3着内なので約1/3）
PRIOR_WEIGHT = 4.0         # 仮想的に何走ぶん足すか
FULL_FIT_RATE = 0.66       # この複勝率で補正が最大（PRIOR_RATE の倍）

NEIGHBOUR_DISTANCE_M = 200  # コース適性で「近い距離」とみなす幅

# B/C/Dは「推定レベルと今回のクラスの差」で決まる。**Aはここでは決まらない**
# （下の「抜けた馬」の判定を参照）。
#
# 線は「何%の馬をそこに入れるか」ではなく、**実測でどれだけ走る層か**で引いている。
# 2024年以降9,300レースの実測で B=勝率20%前後 / C=複勝率30%前後 になる位置。
# 「倒した相手」を入れて尺度が変わったので、Bの線を0.5→0.75に引き直した。
# Cの線は−1.0のまま。−0.5側へ寄せると新馬戦の未出走馬の山（−0.5）が線に乗ってしまう。
TIER_THRESHOLDS = (("B", 0.75), ("C", -1.0))
LOWEST_TIER = "D"
TIERS = ("A", "B", "C", "D")

# --- A（抜けた馬）の判定 ---------------------------------------------------------
# Aは閾値では決まらない。「そのレースで2位以下をどれだけ離しているか」で決める。
#
# 閾値でAを決めていた頃は、どんなに線を上げてもAの勝率が20%程度で頭打ちだった
# （1レースで最上位の1頭だけを選んでも21%が天井）。着順とクラスしか材料にしていない
# ので、絶対的な強さの精度はそこまでしか出ない。いっぽう「同じレースの中でどれだけ
# 抜けているか」は相対の話なので、材料が同じでももっと効く。
#
# margin の高い順に並べ、上から見て最初に STANDOUT_GAP 以上の差が空くところで切り、
# それより上のうち margin が STANDOUT_FLOOR 以上の馬をAにする。
# 差が空かなければAなし。**95%のレースはAが出ない**（2024年以降9,300レースの実測）。
STANDOUT_GAP = 2.0       # 2位以下をクラス2つぶん離していること
STANDOUT_FLOOR = 0.5     # かつ、今回のクラスより半段上のレベルであること
MAX_STANDOUT = 3         # 4頭以上が横並びなら「抜けている」とは言えない

# 段の意味は**実測のヒット率**で言い切る。「期待値あり」とは書かない
# （回収率はどの段も100%に届かないので、買えば得と読める書き方にしないため）。
# 盤の段の呼び名（2文字）。競馬の言葉に寄せて、見出しを1行に収める。
# 長いほうの説明（TIER_MEANINGS）は、盤ではツールチップに回す。
TIER_SHORT = {"A": "軸", "B": "相手", "C": "押さえ", "D": "消し"}

TIER_MEANINGS = {
    "A": "2位以下を離している（単勝の軸）",
    "B": "勝率20%前後（単勝の相手）",
    "C": "複勝率30%前後（3着内の候補）",
    "D": "印を持たない",
}

# 2024年以降の実測（9,298レース。当時の材料だけで採点し直したもの。「倒した相手」込み）。
# **盤では回収率を扱わない**ので、ここに残すのは勝率と複勝率だけ。
# 買えば得かどうか（妙味）は、映像や展開を見て手で動かすところの仕事にしている。
CALIBRATION = {
    "A": {"starts": 622, "win": 0.408, "top3": 0.740, "popularity": 1.5},
    "B": {"starts": 11551, "win": 0.202, "top3": 0.475, "popularity": 3.1},
    "C": {"starts": 51932, "win": 0.091, "top3": 0.278, "popularity": 6.2},
    "D": {"starts": 63826, "win": 0.032, "top3": 0.118, "popularity": 9.8},
}
# Aが出たレースの割合と、出たときの頭数（同じ実測から）
A_RACE_SHARE = 497 / 9298
A_FIELD_SIZES = {1: 391, 2: 86, 3: 20}

CALIBRATION_NOTE = (
    "2024年以降の9,298レース（127,931頭）で答え合わせをすると、"
    "**勝率は A 40.8% / B 20.2% / C 9.1% / D 3.2%**、"
    "**複勝率は 74% / 48% / 28% / 12%** と分かれました。"
    "段の狙いどおり、Aは勝率30%以上・Bは勝率20%前後・Cは複勝率30%前後です。"
    "**Aはそのレースで抜けている馬だけ**なので、出るのは5%のレースだけ（出たときは1〜3頭）。"
    "平均人気は A 1.5番 / B 3.1番 / C 6.2番 / D 9.8番で、上の段ほど人気馬が集まります。"
)

# 過去走がまったく無い馬を、今回のクラスの何段下とみなすか。
# **レースの顔ぶれで変える**。実測（2024年以降3,000レース）では、
# 同じ「未出走」でも走り方がまったく違うため:
#   全頭が未出走のレース … 複勝率 22.4%（経験馬の平均22.7%とほぼ同じ）
#   経験馬と混走         … 複勝率 12.4%（1勝クラス以上なら10.8%）
#
# 経験馬と混走している未出走馬は実測でD相当。いっぽう全頭が未出走のレース
# （新馬戦）は、そもそも馬を見分ける材料がゼロで、複勝率22.4%は
# 「誰かは3着以内に入る」という算数の結果でしかない。ここで全頭をDに落とすと
# 盤が真っ白になって使えないので、まとめてCに置く。
#
# どちらも**段の境界のちょうど上ではなく、段の内側**に落とす。
# 以前は決め打ちの2.0がC/Dの境界と一致していて、全体の19%が同じ値で線の上に
# 乗っており、閾値を0.1動かすだけで数千頭が一斉に段を移る状態だった。
UNRACED_GAP_MAIDEN = 0.5   # 全頭が未出走 → margin -0.5（Cの真ん中）
UNRACED_GAP_MIXED = 2.5    # 経験馬がいる → margin -2.5（Dの内側）
# 未出走馬は適性の材料も無いので補正が必ず0になり、margin はこの値ちょうどに揃う。
# だからこそ「境界から離す」ことが効く（散ってくれないので線に乗ると全員が動く）。

_PACE_LABEL = {pace.HIGH: "ハイ", pace.MIDDLE: "ミドル", pace.SLOW: "スロー"}


@dataclass(frozen=True)
class TierScore:
    """1頭ぶんのTierと、その内訳（マーカーのツールチップに出す）。"""

    tier: str
    experience: float       # 実績レベル（戦ってきた相手）
    pace_fit: float         # 0=苦手 0.5=並 1=得意
    course_fit: float
    adjust: float           # 適性による補正（段）
    level: float            # 推定レベル = experience + adjust
    margin: float           # level − 今回のクラスのレベル
    runs: int               # 実績レベルに使えた走数
    explanation: str


def lane_summary() -> str:
    """盤の下に出す1行（`A 軸（勝率32%）／ B 相手（勝率20%）／ …`）。

    見出しを「A 軸」の2語に絞ったぶん、数字はここで補う。
    実測（CALIBRATION）から組み立てるので、数字を手で書かずに済む。
    A/B は勝率、C は複勝率で決めている段なので、出す数字もそれに合わせる。
    """
    parts = []
    for key in TIERS:
        row = CALIBRATION.get(key) or {}
        if key == "D" or not row.get("starts"):
            parts.append(f"{key} {TIER_SHORT[key]}")
        elif key == "C":
            parts.append(f"{key} {TIER_SHORT[key]}（複勝{row['top3']:.0%}）")
        else:
            parts.append(f"{key} {TIER_SHORT[key]}（勝率{row['win']:.0%}）")
    return " ／ ".join(parts)


def race_level(race: dict) -> float | None:
    """そのレースのクラスのレベル。分からなければ None。

    `past_runs.class_short()` と同じ順で見る: ①グレード ②クラス条件 ③レース名。
    枠順確定前のレースは、レース名がそのまま条件になっているもの（`3歳以上1勝クラス`
    `2歳新馬` など）で `class_condition` が空のまま入っていることがあるので、
    最後にレース名から拾う。
    """
    grade = (race.get("grade") or "").strip()
    if grade in GRADE_LEVEL:
        return GRADE_LEVEL[grade]
    # 出馬表由来は全角数字（`１勝クラス`）なので、既存コードと同じくNFKCでそろえる。
    # 2022年以前の旧呼称（`1000万下`）は今の呼称（`2勝クラス`）に読み替える
    text = modern_class(unicodedata.normalize("NFKC", race.get("class_condition") or ""))
    for name, level in CLASS_LEVEL.items():
        if text.startswith(name):
            return level
    if not text:
        name_text = unicodedata.normalize("NFKC", race.get("race_name") or "")
        for name, level in CLASS_LEVEL.items():
            if name in name_text:
                return level
    return None


def run_value(run: dict) -> float | None:
    """1走の「そのレベルで何ができたか」。着順やクラスが分からない走は None。"""
    level = race_level(run)
    position, field = run.get("finish_position"), run.get("n_runners") or 0
    if level is None or not position:
        return None
    if position == 1:
        return level + WIN_BONUS
    if position <= 3:
        return level + PLACE_BONUS
    # 「上位◯%」だけで見る。以前あった「5着以内」の絶対ルールは、
    # 8頭立ての5着でも「通用した」になってしまうので外した。
    if field and position <= field * TOP_SHARE:
        return level
    return level + BEATEN_PENALTY


@dataclass(frozen=True)
class Opponent:
    """1走のなかの相手1頭（説明文に出す）。"""

    name: str
    strength: float          # 相手の強さ（段）
    gap_sec: float           # 自分のタイム − 相手のタイム（マイナスなら先着）


def opponent_strength(runs: list[dict]) -> float | None:
    """相手の強さ。相手自身の直近5走から、クラス×着順＋その走での人気の上位3走の平均。

    相手の「倒した相手」までは追わない（どこまでも再帰すると重く、説明もできなくなる）。
    """
    values = []
    for run in runs[:RECENT_RUNS]:
        value = run_value(run)
        if value is None:
            continue
        pop, field = run.get("popularity"), run.get("n_runners") or 0
        if pop and field >= 2:
            value += POPULARITY_WEIGHT * (0.5 - (pop - 1) / (field - 1))
        values.append(value)
    if not values:
        return None
    best = sorted(values, reverse=True)[:BEST_RUNS]
    return sum(best) / len(best)


def read_run(
    run: dict, field: list[dict], opponent_runs: dict[str, list[dict]],
) -> tuple[float | None, list[Opponent]]:
    """1走の値と、そこで比べた相手。

    `field` はそのレースの上位の馬（馬ID・馬名・着順・タイム）。自分を除いた上位5頭の
    それぞれについて「相手の強さ − 秒差（1,000mあたり）× SEC_TO_LEVEL」を出し、
    その中央値をクラス×着順の値と混ぜる。相手が読めなければクラス×着順の値のまま。
    """
    value = run_value(run)
    if value is None:
        return None, []
    time_sec, distance = run.get("time_sec"), run.get("distance_m")
    if not time_sec or not distance:
        return value, []
    others = sorted(
        (o for o in field if o.get("horse_id") != run.get("horse_id") and o.get("time_sec")),
        key=lambda o: o.get("finish_position") or 99,
    )[:OPPONENTS]
    readings, opponents = [], []
    for other in others:
        strength = opponent_strength(opponent_runs.get(other["horse_id"], []))
        if strength is None:
            continue
        gap = time_sec - other["time_sec"]
        readings.append(strength - SEC_TO_LEVEL * gap * 1000 / distance)
        opponents.append(Opponent(other.get("horse_name") or "", strength, gap))
    if not readings:
        return value, []
    readings.sort()
    mid = len(readings) // 2
    median = readings[mid] if len(readings) % 2 else (readings[mid - 1] + readings[mid]) / 2
    return (1 - OPPONENT_WEIGHT) * value + OPPONENT_WEIGHT * median, opponents


def _experience(
    runs: list[dict],
    fields: dict[str, list[dict]] | None,
    opponent_runs: dict[str, list[dict]] | None,
) -> tuple[float | None, int, tuple[dict, Opponent] | None]:
    """実績レベル・使えた走数・説明に出す「いちばん効いた走で、いちばん強かった相手」。"""
    read = []
    for run in runs[:RECENT_RUNS]:
        field = (fields or {}).get(run.get("race_id"), [])
        value, opponents = read_run(run, field, opponent_runs or {})
        if value is not None:
            read.append((value, run, opponents))
    if not read:
        return None, 0, None
    best = sorted(read, key=lambda item: -item[0])[:BEST_RUNS]
    headline = next(
        ((run, max(opponents, key=lambda o: o.strength)) for _, run, opponents in best if opponents),
        None,
    )
    return sum(v for v, _, _ in best) / len(best), len(read), headline


def experience_level(
    runs: list[dict],
    fields: dict[str, list[dict]] | None = None,
    opponent_runs: dict[str, list[dict]] | None = None,
) -> tuple[float | None, int]:
    """実績レベルと、それに使えた走数。

    直近5走のうち**上位3走の平均**を採る。1走の大敗や展開負けで評価が壊れないように
    するためで、逆に「1走だけ格上で好走した」は拾いたいので最大値そのままにはしない。
    `fields`（レースID → 上位の馬）と `opponent_runs`（相手の馬ID → 直近の走）を渡すと、
    1走ごとの値に「倒した相手」が入る。渡さなければクラス×着順だけで見る。
    """
    level, n_runs, _ = _experience(runs, fields, opponent_runs)
    return level, n_runs


def shrunk_rate(top3: int, starts: int) -> float:
    """出走が少ないほど全体平均に寄せた複勝率。"""
    return (top3 + PRIOR_WEIGHT * PRIOR_RATE) / (starts + PRIOR_WEIGHT)


def _fit(rate: float) -> float:
    """複勝率を 0（苦手）〜0.5（並）〜1（得意）の適性に直す。"""
    return max(0.0, min(1.0, rate / FULL_FIT_RATE))


def pace_fit(stats_runs: list[dict], today_pace: str | None) -> float:
    """今日の想定ペースでの複勝率から出した適性。材料が無ければ並（0.5）。"""
    label = _PACE_LABEL.get(today_pace or "")
    if label is None:
        return 0.5
    bucket = next((b for b in horse_stats.summarize_pace(stats_runs) if b.label == label), None)
    if bucket is None:
        return 0.5
    return _fit(shrunk_rate(bucket.top3, bucket.starts))


def _top3_rate(runs: list[dict]) -> float:
    finishes = [r["finish_position"] for r in runs if r.get("finish_position")]
    return shrunk_rate(sum(1 for p in finishes if p <= 3), len(finishes))


def course_fit(runs: list[dict], race: dict) -> float:
    """同じ競馬場の複勝率と、±200mの距離の複勝率の平均から出した適性。"""
    venue, distance = race.get("venue_code"), race.get("distance_m")
    same_venue = [r for r in runs if venue and r.get("venue_code") == venue]
    near = [
        r for r in runs
        if distance and r.get("distance_m")
        and abs(r["distance_m"] - distance) <= NEIGHBOUR_DISTANCE_M
    ]
    return _fit((_top3_rate(same_venue) + _top3_rate(near)) / 2)


def tier_of(margin: float) -> str:
    """推定レベルと今回のクラスの差から、**B/C/D**を決める。

    Aはこの関数では決まらない（レース全体を見ないと「抜けている」が判定できない）。
    `standouts` が選んだ馬だけを、あとからAに上げる。
    """
    for tier, threshold in TIER_THRESHOLDS:
        if margin >= threshold:
            return tier
    return LOWEST_TIER


def standout_cut(margins: list[tuple[str, float]]) -> tuple[set[str], float]:
    """そのレースで「抜けている」馬のIDと、**その集団が次の馬につけている差**。

    `margins` は (馬ID, margin) の一覧（順不同）。
    上から見て最初に `STANDOUT_GAP` 以上の差が空くところで切り、それより上のうち
    `STANDOUT_FLOOR` 以上の馬を返す。差が空かないレースでは空を返す。

    差は**切れ目の差**で、集団の全員に同じ値を返す。
    「集団に入ったが `STANDOUT_FLOOR` に届かずAにならなかった馬」との距離ではない
    （その馬との距離を返すと、基準の2.0段より小さい数字が説明に出てしまう）。
    """
    ranked = sorted(margins, key=lambda pair: -pair[1])
    cut = next(
        (
            k for k in range(1, min(MAX_STANDOUT, len(ranked) - 1) + 1)
            if ranked[k - 1][1] - ranked[k][1] >= STANDOUT_GAP
        ),
        None,
    )
    if cut is None:
        return set(), 0.0
    chosen = {horse_id for horse_id, margin in ranked[:cut] if margin >= STANDOUT_FLOOR}
    return chosen, ranked[cut - 1][1] - ranked[cut][1]


def standouts(margins: list[tuple[str, float]]) -> set[str]:
    """そのレースで「抜けている」馬のID。いなければ空。"""
    return standout_cut(margins)[0]


def _explain(score_parts: dict) -> str:
    """マーカーのツールチップに出す1行。"""
    def word(fit: float) -> str:
        return "得意" if fit >= 0.65 else "苦手" if fit <= 0.35 else "並"

    if not score_parts["runs"]:
        if score_parts.get("all_unraced"):
            return (
                "このレースは**全頭が未出走**なので、馬を見分ける材料がありません"
                "（全馬を同じ段に置いています）"
            )
        return (
            "過去走がまだ手元にありません。"
            "経験馬と混走している未出走馬は、実測で複勝率12%ほどです"
        )
    text = (
        f"実績レベル {score_parts['experience']:.1f}"
        f"（直近{score_parts['runs']}走の良いほうから）"
    )
    headline = score_parts.get("headline")
    if headline:
        run, other = headline
        verb = "先着" if other.gap_sec < 0 else "同タイム" if other.gap_sec == 0 else "負け"
        gap = "" if other.gap_sec == 0 else f"{abs(other.gap_sec):.1f}秒"
        text += (
            f"／倒した相手: {run.get('race_name') or '前の走'}で"
            f"{other.name}（強さ{other.strength:.1f}）に{gap}{verb}"
        )
    return text + (
        f"／ペース適性 {word(score_parts['pace_fit'])}"
        f"／コース適性 {word(score_parts['course_fit'])}"
        f"／今回のクラスとの差 {score_parts['margin']:+.1f}段"
    )


def score_horse(
    race: dict,
    runs: list[dict],
    stats_runs: list[dict],
    today_pace: str | None,
    base_level: float,
    all_unraced: bool = False,
    fields: dict[str, list[dict]] | None = None,
    opponent_runs: dict[str, list[dict]] | None = None,
) -> TierScore:
    """1頭ぶんのTierと内訳。

    `all_unraced` は「そのレースの全頭が未出走か」。未出走馬の置き場所だけが
    これで変わる（同じ未出走でも、新馬戦と混走では実測がまるで違うため）。
    """
    experience, n_runs, headline = _experience(runs, fields, opponent_runs)
    if experience is None:
        gap = UNRACED_GAP_MAIDEN if all_unraced else UNRACED_GAP_MIXED
        experience = base_level - gap
    p_fit = pace_fit(stats_runs, today_pace)
    c_fit = course_fit(runs, race)
    adjust = (p_fit - 0.5) * 2 * PACE_WEIGHT + (c_fit - 0.5) * 2 * COURSE_WEIGHT
    level = experience + adjust
    margin = level - base_level
    parts = {
        "experience": experience, "pace_fit": p_fit, "course_fit": c_fit,
        "margin": margin, "runs": n_runs, "all_unraced": all_unraced, "headline": headline,
    }
    return TierScore(
        tier=tier_of(margin), experience=experience, pace_fit=p_fit, course_fit=c_fit,
        adjust=adjust, level=level, margin=margin, runs=n_runs, explanation=_explain(parts),
    )


def assign(
    race: dict,
    entries: list[dict],
    past_runs: dict[str, list[dict]],
    stats_runs: dict[str, list[dict]],
    today_pace: str | None,
    fields: dict[str, list[dict]] | None = None,
    opponent_runs: dict[str, list[dict]] | None = None,
) -> dict[str, TierScore]:
    """出走各馬のTier。馬ID -> TierScore。

    `past_runs` は `data.get_past_runs_for_horses`（同じ馬場の直近10走）、
    `stats_runs` は `data.get_runs_for_stats`（同じ馬場の全走）の返り値を想定。
    `fields` は過去走のレースID → その上位の馬（`data.get_top_finishers`）、
    `opponent_runs` はその馬たちの直近の走（`data.get_class_runs`）。
    無ければ「倒した相手」は入らず、クラス×着順だけで見る。
    """
    base = race_level(race)
    if base is None:
        return {}
    # 未出走馬の置き場所はレース全体を見ないと決まらない（Aと同じ事情）。
    # 経験馬が1頭もいなければ「新馬戦」として扱う。
    horse_ids = [e.get("horse_id") for e in entries if e.get("horse_id")]
    all_unraced = not any(
        experience_level(past_runs.get(horse_id, []))[0] is not None
        for horse_id in horse_ids
    )
    scores = {}
    for horse_id in horse_ids:
        scores[horse_id] = score_horse(
            race, past_runs.get(horse_id, []), stats_runs.get(horse_id, []),
            today_pace, base, all_unraced=all_unraced,
            fields=fields, opponent_runs=opponent_runs,
        )
    # Aは1頭ずつでは決まらない。全馬の margin がそろってから「抜けている馬」を選ぶ。
    # Aを分けた「切れ目」の差は、Aが2頭以上でも全員に同じ値を出す
    # （その差でまとめてAになったので、馬ごとに違う数字を出すと誤解を招く）。
    chosen, gap = standout_cut([(horse_id, s.margin) for horse_id, s in scores.items()])
    for horse_id in chosen:
        score = scores[horse_id]
        scores[horse_id] = replace(
            score, tier="A",
            explanation=f"{score.explanation}／**次の馬に{gap:.1f}段の差**",
        )
    return scores
