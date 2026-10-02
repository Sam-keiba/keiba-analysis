"""予想ボードのTier（A/B/C/D）の自動仮配置。

**これはたたき台を作るためのもので、最終判断は画面上で手で動かす前提。**

点数を足して順位で切るのではなく、**その馬の「推定レベル」を今回のクラスと比べる**。
こうすると閾値の意味がそのまま日本語になり、内訳も説明できる。

    推定レベル = 実績レベル（戦ってきた相手）+ 適性補正（ペース・コース）
    margin     = 推定レベル − 今回のクラスのレベル

    B/C/D … margin の閾値で決まる（1頭ずつ決まる）
    A     … **そのレースで2位以下を離しているか**で決まる（レース全体を見ないと決まらない）

段の境目は「何%の馬をそこに入れるか」ではなく、**実測でどれだけ走る層か**で引いている:

    A … 勝率30%以上（実測31.8%）
    B … 勝率20%前後（実測19.6%）
    C … 複勝率30%前後（実測29.4%）
    D … それ未満（実測 勝率4.0%・複勝率14.1%）

**回収率は盤で扱わない。** どの段も100%に届かないので、段の名前を「期待値あり」に
すると「買えば得」と読めてしまう。妙味は、映像や展開を見て手で動かすところで拾う。

**Aだけ決め方が違う**のは、閾値ではどう線を引いてもAの勝率が20%程度で頭打ちに
なったから（1レースで最上位の1頭だけを選んでも21%が天井だった）。着順とクラスしか
材料にしていないので、絶対的な強さの精度はそこまでしか出ない。いっぽう「同じレースの
中でどれだけ抜けているか」は相対の話なので、同じ材料でももっと効く。実測で勝率は
33.4%になり、1番人気（約33%）と並んだ。そのかわり**Aは93%のレースで出ない**。

実績レベルが主軸で、適性は最大でも±0.9段ぶんしか動かさない。「未勝利しか勝って
いない馬」が適性だけでGIIのAに来ることはなく、実績が拮抗している馬どうしでだけ
適性が順番を入れ替える。

改善の余地（次のフェーズ以降）:
- 斤量・騎手・馬体重の増減・休み明けを見ていない
- 相手レベルは着順だけで、着差やタイムを見ていない
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
# 2024年以降3,000レースの実測で B=勝率20%前後 / C=複勝率30%前後 になる位置。
# A（勝率33.4%）から下へ、勝率20% → 複勝率30% と段が落ちる形にそろえてある。
TIER_THRESHOLDS = (("B", 0.5), ("C", -1.0))
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
# 差が空かなければAなし。**94%のレースはAが出ない**（2024年以降4,000レースの実測）。
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

# 2024年以降の実測（tools/calibrate_tier.py。当時の材料だけで採点し直したもの）。
# **盤では回収率を扱わない**ので、ここに残すのは勝率と複勝率だけ。
# 買えば得かどうか（妙味）は、映像や展開を見て手で動かすところの仕事にしている。
CALIBRATION = {
    "A": {"starts": 355, "win": 0.318, "top3": 0.654, "popularity": 2.0},
    "B": {"starts": 3514, "win": 0.196, "top3": 0.480, "popularity": 3.0},
    "C": {"starts": 11836, "win": 0.100, "top3": 0.294, "popularity": 5.9},
    "D": {"starts": 25676, "win": 0.040, "top3": 0.141, "popularity": 9.2},
}
# Aが出たレースの割合と、出たときの頭数（同じ実測から）
A_RACE_SHARE = 234 / 3000
A_FIELD_SIZES = {1: 138, 2: 70, 3: 26}

CALIBRATION_NOTE = (
    "2024年以降の3,000レース（41,381頭）で答え合わせをすると、"
    "**勝率は A 31.8% / B 19.6% / C 10.0% / D 4.0%**、"
    "**複勝率は 65% / 48% / 29% / 14%** と分かれました。"
    "段の狙いどおり、Aは勝率30%以上・Bは勝率20%前後・Cは複勝率30%前後です。"
    "**Aはそのレースで抜けている馬だけ**なので、出るのは8%のレースだけ（出たときは1〜3頭）。"
    "平均人気は A 2.0番 / B 3.0番 / C 5.9番 / D 9.2番で、上の段ほど人気馬が集まります。"
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


def experience_level(runs: list[dict]) -> tuple[float | None, int]:
    """実績レベルと、それに使えた走数。

    直近5走のうち**上位3走の平均**を採る。1走の大敗や展開負けで評価が壊れないように
    するためで、逆に「1走だけ格上で好走した」は拾いたいので最大値そのままにはしない。
    """
    values = [v for v in (run_value(r) for r in runs[:RECENT_RUNS]) if v is not None]
    if not values:
        return None, 0
    best = sorted(values, reverse=True)[:BEST_RUNS]
    return sum(best) / len(best), len(values)


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
    return (
        f"実績レベル {score_parts['experience']:.1f}"
        f"（直近{score_parts['runs']}走の良いほうから）"
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
) -> TierScore:
    """1頭ぶんのTierと内訳。

    `all_unraced` は「そのレースの全頭が未出走か」。未出走馬の置き場所だけが
    これで変わる（同じ未出走でも、新馬戦と混走では実測がまるで違うため）。
    """
    experience, n_runs = experience_level(runs)
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
        "margin": margin, "runs": n_runs, "all_unraced": all_unraced,
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
) -> dict[str, TierScore]:
    """出走各馬のTier。馬ID -> TierScore。

    `past_runs` は `data.get_past_runs_for_horses`（同じ馬場の直近10走）、
    `stats_runs` は `data.get_runs_for_stats`（同じ馬場の全走）の返り値を想定。
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
