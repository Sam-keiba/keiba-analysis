"""個別推定ラップ（その馬自身の区間ラップ）の算出。

公表されているラップは「その区間の先頭にいた馬」のもので、後方から差す馬は
まったく違うペースで走っている。ここでは**その馬自身の区間ラップ**を、
DBにある実測値（タイム・上がり3F・コーナー通過順位・レースラップ）から推定する。

## 考え方
その馬の「スタートからの累計時間」が分かる（または推定できる）地点＝**アンカー**を並べ、
アンカーとアンカーの間はレースラップの形に沿わせて時間を配分する。

| 地点 | 値 | 種別 |
|---|---|---|
| スタート(0m) | 0秒 | 実測（自明） |
| 各コーナー | 先頭の通過時刻 ＋ 隊列の広がり × 位置の割合 | 推定 |
| 残り600m | 自分のタイム − 上がり3F | **実測から確定** |
| ゴール | 自分のタイム | **実測** |

**位置の割合**は `(通過順位−1)/(頭数−1)`（0=先頭、1=最後方）で、頭数の違いを吸収する。
**隊列の広がり**（先頭と最後方の時間差）は、そのレースの全出走馬の
「残り600m地点での先頭との差（＝確定値）」から最小二乗で較正する（`calibrate_field_spread`）。
材料が足りないレースはDB全体の中央値 `DEFAULT_FIELD_SPREAD_SEC` を使う。

隊列は**序盤ほど時間的に広い**ので、スタート側ほど広がりを `EARLY_SPREAD_FACTOR` 倍する。
また**最初のコーナーが遠いレース**では、`SETTLE_DISTANCE_M`（400m）の地点にも
同じ位置取りのアンカーを置く（スタート直後に隊列は決まっているため）。

この作り方なので、**推定ラップの合計は必ず実際の走破タイムと一致**し、
**最後の3区間の合計は実測の上がり3Fと一致**する。

## 限界（画面にも同じ内容を出している）
- コーナーとコーナーの間にアンカーが無いため、**中盤の形はレースラップに近くなる**
- コーナーの位置はコース図と同じ近似（数十mのずれはありうる）
- 「位置→秒」は隊列の広がりが一定の形だと仮定した近似（コーナーごとの伸縮は見ていない）
- 内・外を回ったことによる距離ロス、不利、馬群の密度は考慮していない
- コーナー通過順が無い走は上がり3Fのアンカーだけで出すため**参考値**扱いにする
"""

from __future__ import annotations

from dataclasses import dataclass

from keiba_analysis.racing.course_map import corner_distances
from keiba_analysis.racing.running_style import parse_corner_positions

# 隊列の広がり＝残り600m地点での「先頭と最後方の時間差（秒）」。
# レースごとに実測から求める（calibrate_field_spread）が、材料が足りないときの既定値は
# DBの2025年以降5,741レースの中央値 1.7秒（p10=1.0 / p90=2.8）。
DEFAULT_FIELD_SPREAD_SEC = 1.7

# 序盤ほど隊列は時間的に広い（同じ位置取りでも先頭との差が大きい）。
# 残り600m地点で1.0になるよう、スタート側ほどこの倍率に近づける。
# netkeibaの馬柱の前半3F（19走）と突き合わせて決めた値で、1.3〜1.8では誤差がほぼ変わらない。
EARLY_SPREAD_FACTOR = 1.5

# ここまでには隊列が決まっているとみなす距離。最初のコーナーがこれより先でも、
# この地点で既にコーナーと同じ位置取りだったものとしてアンカーを置く。
SETTLE_DISTANCE_M = 400

ANCHOR_DISTANCE_M = 600  # 上がり3F＝残り600m
# 残り600mのアンカーに近すぎるコーナーは使わない（同じ地点を二重に固定しないため）
MIN_CORNER_GAP_M = 50

# ありえない区間ラップはその区間だけ欠損にする。
# 区間の長さは200mとは限らない（1500m・1700m・2500mなどは最初が100m、1150mは150m）ので、
# **200mあたりに直してから**判定する。
MIN_LAP_SEC = 8.0
MAX_LAP_SEC = 20.0
FURLONG_M = 200
MAX_MISSING_RATIO = 1 / 3  # 欠損がこれを超えたら、その走の推定は出さない


@dataclass(frozen=True)
class EstimatedLaps:
    """1走ぶんの推定結果。"""

    values: list[float | None]  # 区間ごとの推定ラップ（ありえない値はNone）
    is_reference: bool  # コーナー通過順を使えず、上がり3Fだけで出した参考値か

    @property
    def total(self) -> float:
        return sum(v for v in self.values if v is not None)


def split_floats(text: str | None) -> list[float]:
    """`12.3-11.2-12.8` を数値のリストにする。壊れていれば空リスト。"""
    if not text:
        return []
    values = []
    for part in str(text).split("-"):
        try:
            values.append(float(part))
        except ValueError:
            return []
    return values


def _cumulative(laps: list[float]) -> list[float]:
    """先頭の累計時間（先頭に0を置く）。"""
    total = 0.0
    result = [0.0]
    for lap in laps:
        total += lap
        result.append(total)
    return result


def _leader_time_at(bounds: list[float], cumulative: list[float], distance: float) -> float:
    """先頭がその地点を通過した時刻（区間の途中は線形で補間する）。"""
    for i in range(1, len(bounds)):
        if distance <= bounds[i] + 1e-9:
            low, high = bounds[i - 1], bounds[i]
            ratio = (distance - low) / (high - low) if high > low else 0.0
            return cumulative[i - 1] + (cumulative[i] - cumulative[i - 1]) * ratio
    return cumulative[-1]


def position_ratio(rank: int | None, n_runners: int | None) -> float:
    """隊列の中での位置（0=先頭、1=最後方）。頭数の違いを吸収するために割合で見る。"""
    if not rank or not n_runners or n_runners <= 1:
        return 0.0
    return max(0.0, min(1.0, (rank - 1) / (n_runners - 1)))


def calibrate_field_spread(
    field: list[dict], leader_time_at_600: float | None, n_runners: int | None
) -> float | None:
    """そのレースの**隊列の広がり**（残り600m地点での先頭〜最後方の秒差）を出す。

    出走各馬について
      差 = (自分のタイム − 上がり3F) − 先頭の残り600m地点の通過時刻   … 確定値
    を求め、**正規化した位置**（0=先頭〜1=最後方）との関係を原点を通る最小二乗で解く。
    頭数で割っているので、少頭数のレースと多頭数のレースを同じ尺度で扱える。
    材料が足りなければ None（呼び出し側で既定値を使う）。
    """
    if leader_time_at_600 is None:
        return None
    numerator = denominator = 0.0
    for row in field:
        time_sec, last_3f = row.get("time_sec"), row.get("last_3f")
        ranks = parse_corner_positions(row.get("corner_passing"))
        if time_sec is None or last_3f is None or not ranks:
            continue
        ratio = position_ratio(ranks[-1], n_runners)
        if ratio <= 0:
            continue
        gap = (time_sec - last_3f) - leader_time_at_600
        if gap < 0:  # 先頭より速いことはないので、材料から外す
            continue
        numerator += gap * ratio
        denominator += ratio * ratio
    if denominator <= 0:
        return None
    return numerator / denominator


def gap_at(spread: float, rank: int | None, n_runners: int | None, distance: float, closing_start: float) -> float:
    """その地点で先頭からどれだけ後ろにいたか（秒）。

    位置の割合 × 隊列の広がり × 序盤の係数。
    係数は残り600m地点（closing_start）で1.0、スタート側ほど EARLY_SPREAD_FACTOR に近づく。
    """
    ratio = position_ratio(rank, n_runners)
    if ratio <= 0:
        return 0.0
    early = 1.0
    if closing_start > 0:
        early = 1 + (EARLY_SPREAD_FACTOR - 1) * max(0.0, 1 - distance / closing_start)
    return spread * early * ratio


# --- 前半3Fの遅れ（その馬が先頭から何秒後ろで最初の3Fを走ったか）-----------------
# 以前は「隊列の広がり × 順位の割合 × 序盤は1.5倍」で出していたが、
#   - 隊列の広がりの較正が小頭数で暴れる（7頭立てで3.7秒、13〜18頭立てで1.2〜1.6秒）
#   - 序盤の広がりはペース次第（速い前半＝縦長、遅い前半＝凝縮）で1.5固定では合わない
# ため、最大1.8秒ずれる走があった。いまは**その馬自身の残り600m地点での実測差**を軸に、
# ペースと位置で補正して直接求める。係数はnetkeibaの馬柱に出ている前半3F 27走に
# 最小二乗で合わせたもの（1件抜き検証で 平均絶対誤差0.29秒・最大0.59秒）。
# 遅れ ＝ 0.49×(残り600m地点の実測差) ＋ 位置の割合×(1.25 ＋ 2.17×ペース差)
# 位置に比例させているので、**終始先頭の馬は遅れ0**になる（レースラップ＝先頭のラップ）。
EARLY_GAP_FROM_LATE = 0.49  # その馬の残り600m地点での実測差（先頭との秒差）
EARLY_GAP_POSITION = 1.25  # 位置の割合（0=先頭, 1=最後方）
EARLY_GAP_POSITION_PACE = 2.17  # 位置の割合 × ペース差（速い前半ほど隊列が縦長）
MAX_EARLY_GAP_SEC = 5.0  # 推定の上限（これ以上離れることは実質ない）


def own_gap_at_closing(run: dict, cumulative: list[float]) -> float | None:
    """その馬の**残り600m地点での先頭との差**（秒）。実測から確定する。

    自分のタイム − 上がり3F ＝ 残り600m地点の通過時刻。先頭のそれとの差を返す。
    """
    time_sec, last_3f = run.get("time_sec"), run.get("last_3f")
    distance_m = run.get("distance_m")
    if time_sec is None or last_3f is None or not distance_m or len(cumulative) < 4:
        return None
    leader = cumulative[-4]  # 残り3区間ぶん手前 ＝ 残り600m地点（区間が200mのとき）
    return max(0.0, (time_sec - last_3f) - leader)


def early_gap(run: dict, laps: list[float], bounds: list[float], cumulative: list[float]) -> float | None:
    """前半3F地点での先頭との差（秒）。材料が足りなければ None。"""
    ranks = parse_corner_positions(run.get("corner_passing"))
    distance_m = run.get("distance_m")
    late = own_gap_at_closing(run, cumulative)
    if not ranks or not distance_m or late is None or len(bounds) < 4 or not laps:
        return None
    early_distance = bounds[3]
    if early_distance <= 0 or early_distance >= distance_m:
        return None
    race_pace = sum(laps) * FURLONG_M / distance_m
    early_pace = sum(laps[:3]) * FURLONG_M / early_distance
    ratio = position_ratio(ranks[0], run.get("n_runners") or max(ranks))
    gap = EARLY_GAP_FROM_LATE * late + ratio * (
        EARLY_GAP_POSITION + EARLY_GAP_POSITION_PACE * (race_pace - early_pace)
    )
    return min(max(gap, 0.0), MAX_EARLY_GAP_SEC)


def corner_anchors(run: dict, bounds: list[float], cumulative: list[float], spread: float) -> list[tuple[float, float]]:
    """位置取りから作るアンカー（距離m, その馬の累計時間）。

    各コーナーの通過順位を使う。さらに、**最初のコーナーが SETTLE_DISTANCE_M より先**なら、
    その手前にも同じ位置取りのアンカーを置く（スタート直後に隊列は決まっているため。
    これを入れないと、後方の馬の前半が実際より速く出てしまう）。
    """
    ranks = parse_corner_positions(run.get("corner_passing"))
    distance_m = run.get("distance_m")
    if not ranks or not distance_m:
        return []
    positions = corner_distances(
        run.get("venue_code") or "", run.get("surface"), distance_m,
        run.get("course_detail"), len(ranks),
    )
    # 頭数はDBに必ず入っているが、欠けていたら通過順の最大値を下限として使う
    n_runners = run.get("n_runners") or max(ranks)
    closing_start = distance_m - ANCHOR_DISTANCE_M
    limit = closing_start - MIN_CORNER_GAP_M

    # 通過順は「後ろのコーナーから順に」埋まる（2つなら3角・4角）
    corner_numbers = [4, 3, 2, 1][: len(ranks)][::-1]
    passed = [
        (positions[corner], rank)
        for corner, rank in zip(corner_numbers, ranks, strict=True)
        if positions.get(corner) is not None and 0 < positions[corner] < limit
    ]
    if not passed:
        return []

    anchors = []
    first_distance, first_rank = passed[0]
    if first_distance > SETTLE_DISTANCE_M:
        anchors.append((
            float(SETTLE_DISTANCE_M),
            _leader_time_at(bounds, cumulative, SETTLE_DISTANCE_M)
            + gap_at(spread, first_rank, n_runners, SETTLE_DISTANCE_M, closing_start),
        ))
    for distance, rank in passed:
        anchors.append((
            distance,
            _leader_time_at(bounds, cumulative, distance)
            + gap_at(spread, rank, n_runners, distance, closing_start),
        ))
    return anchors


def build_anchors(
    run: dict, bounds: list[float], cumulative: list[float], spread: float,
    laps: list[float] | None = None,
) -> tuple[list[tuple[float, float]], bool]:
    """アンカーの一覧（距離順）と、参考値かどうかを返す。

    実測から決まるアンカー（スタート・残り600m・ゴール）と、**前半3F地点**
    （`early_gap` による推定）は必ず残し、コーナーのアンカーは、前後と矛盾する
    （時間が逆行する）ものだけ落とす。
    """
    distance_m, time_sec, last_3f = run["distance_m"], run["time_sec"], run.get("last_3f")
    laps = laps or []

    exact = [(0.0, 0.0)]
    # 前半3F地点は、実測（残り600m地点の差）とペース・位置から直接推定してアンカーにする
    gap = early_gap(run, laps, bounds, cumulative)
    if gap is not None and len(bounds) >= 4 and bounds[3] < distance_m - ANCHOR_DISTANCE_M:
        exact.append((float(bounds[3]), _leader_time_at(bounds, cumulative, bounds[3]) + gap))
    if last_3f is not None and distance_m > ANCHOR_DISTANCE_M:
        exact.append((float(distance_m - ANCHOR_DISTANCE_M), time_sec - last_3f))
    exact.append((float(distance_m), float(time_sec)))

    anchors = [exact[0], *exact[1:2]]      # スタートと前半3F（あれば）は必ず残す
    corners = corner_anchors(run, bounds, cumulative, spread)
    for distance, value in sorted(corners):
        if distance > anchors[-1][0] and value > anchors[-1][1] and value < exact[-1][1]:
            anchors.append((distance, value))
    used_corners = len(anchors) - len(exact[:2])
    for distance, value in exact[2:] if len(exact) > 2 else exact[1:]:
        if distance > anchors[-1][0] and value > anchors[-1][1]:
            anchors.append((distance, value))
    return anchors, used_corners == 0 and gap is None


def _guard(values: list[float], lengths: list[float]) -> list[float | None] | None:
    """ありえない区間ラップをNoneにする。欠損が多すぎる走は None を返す（推定しない）。

    判定は200mあたりに直した速さで行う（最初の区間が100mのレースの6〜7秒を
    「ありえない値」として捨ててしまわないように）。
    """
    guarded: list[float | None] = [
        v if length > 0 and MIN_LAP_SEC <= v * FURLONG_M / length <= MAX_LAP_SEC else None
        for v, length in zip(values, lengths, strict=True)
    ]
    missing = sum(1 for v in guarded if v is None)
    if not guarded or missing > len(guarded) * MAX_MISSING_RATIO:
        return None
    return guarded


def estimate_run(run: dict, spread: float = DEFAULT_FIELD_SPREAD_SEC) -> EstimatedLaps | None:
    """1走ぶんの個別推定ラップ。材料が足りない走（障害などラップが無い）は None。"""
    laps = split_floats(run.get("race_laps"))
    distances = [float(d) for d in split_floats(run.get("lap_distances"))]
    distance_m, time_sec = run.get("distance_m"), run.get("time_sec")
    if not laps or len(laps) != len(distances) or not distance_m or time_sec is None:
        return None

    bounds = [0.0, *distances]
    cumulative = _cumulative(laps)
    anchors, is_reference = build_anchors(run, bounds, cumulative, spread, laps)
    if len(anchors) < 2:
        return None

    # アンカーとアンカーの間は、レースラップの形に比例させて時間を配る
    values: list[float] = []
    previous = 0.0
    for bound in bounds[1:]:
        index = next((i for i in range(1, len(anchors)) if bound <= anchors[i][0] + 1e-9), len(anchors) - 1)
        (distance_a, time_a), (distance_b, time_b) = anchors[index - 1], anchors[index]
        leader_a = _leader_time_at(bounds, cumulative, distance_a)
        leader_b = _leader_time_at(bounds, cumulative, distance_b)
        ratio = (time_b - time_a) / (leader_b - leader_a) if leader_b > leader_a else 1.0
        current = time_a + ratio * (_leader_time_at(bounds, cumulative, bound) - leader_a)
        values.append(round(current - previous, 2))
        previous = current

    lengths = [bounds[i] - bounds[i - 1] for i in range(1, len(bounds))]
    guarded = _guard(values, lengths)
    if guarded is None:
        return None
    return EstimatedLaps(values=guarded, is_reference=is_reference)


def run_key(run: dict) -> tuple[str, int | None]:
    """推定値を引くためのキー（レースID, 馬番）。

    **レースIDだけでは足りない**: 馬柱には全出走馬の過去走が並ぶので、同じレースを
    2頭以上が走っていると（重賞ではよくある）、1頭目の推定が他の馬にも出てしまう。
    """
    return (run.get("race_id") or "", run.get("umaban"))


def estimate_runs(
    runs: list[dict], fields: dict[str, list[dict]] | None = None
) -> dict[tuple[str, int | None], EstimatedLaps]:
    """過去走のリストぶんまとめて推定する（(レースID, 馬番) -> 推定結果）。

    fields: レースID -> そのレースの全出走馬の {time_sec, last_3f, corner_passing}。
    渡されたレースは「隊列の広がり」をレースごとに較正する（同じレースの馬で使い回す）。
    """
    fields = fields or {}
    result: dict[tuple[str, int | None], EstimatedLaps] = {}
    spreads: dict[str, float] = {}
    for run in runs:
        key = run_key(run)
        race_id = key[0]
        if not race_id or key in result:
            continue
        if race_id not in spreads:
            laps = split_floats(run.get("race_laps"))
            distances = split_floats(run.get("lap_distances"))
            spread = DEFAULT_FIELD_SPREAD_SEC
            if laps and len(laps) == len(distances) and run.get("distance_m"):
                leader_at_600 = _leader_time_at(
                    [0.0, *distances], _cumulative(laps), run["distance_m"] - ANCHOR_DISTANCE_M
                )
                calibrated = calibrate_field_spread(
                    fields.get(race_id, []), leader_at_600, run.get("n_runners")
                )
                if calibrated is not None and calibrated > 0:
                    spread = calibrated
            spreads[race_id] = spread
        estimated = estimate_run(run, spreads[race_id])
        if estimated is not None:
            result[key] = estimated
    return result


# 画面（モーダルの「このグラフについて」）に出す説明。
# 算出ロジックと同じ場所に置いて、実装と説明がずれないようにする。
EXPLANATION = f"""
#### 個別推定ラップとは

公表されているラップタイムは、**その区間で先頭にいた馬**のものです。
後方から差す馬は、先頭とはまったく違うペースで走っているので、公表ラップを見ても
その馬がどう走ったかは分かりません。そこで、**その馬自身の区間ラップを推定**しています。

#### 出し方

その馬の「スタートからの累計時間」が分かる地点（アンカー）を並べ、
**アンカーとアンカーの間はレースラップの形に沿わせて**時間を配分しています。

| 地点 | 値 | 種別 |
|---|---|---|
| スタート | 0秒 | 実測 |
| **前半3F地点** | 先頭の通過時刻 ＋ 下の式で出した遅れ | **推定** |
| 各コーナー | 前半3F地点と残り600m地点の間を、通過順位で按分 | **推定** |
| 残り600m | 自分のタイム − 上がり3F | 実測から確定 |
| ゴール | 自分のタイム | 実測 |

**前半3Fの遅れ**（先頭から何秒後ろで最初の3Fを走ったか）は、次の3つから出します。

```
遅れ ＝ {EARLY_GAP_FROM_LATE} × その馬の残り600m地点での実測差
      ＋ 位置の割合 ×（{EARLY_GAP_POSITION} ＋ {EARLY_GAP_POSITION_PACE} × ペース差）
```

- **残り600m地点での実測差**（自分のタイム − 上がり3F − 先頭の通過時刻）は**実測から確定**する値で、
  ここが推定の軸です。
- **位置の割合**は `(通過順位−1)/(頭数−1)`（0=先頭、1=最後方）。終始先頭の馬は遅れ0になります。
- **ペース差**は「レース平均の1Fペース − 前半3Fの1Fペース」。前半が速いレースは隊列が縦長になり、
  同じ位置でも先頭との差が大きくなります。

係数はnetkeibaの馬柱に出ている前半3F **27走**に合わせたもので、
**1件抜き検証**（当てにいった走を学習から外す）で 平均絶対誤差 **0.29秒**・最大 **0.65秒**です。
以前の作り（レースごとに隊列の広がりを較正し、序盤は一律1.5倍）は同じ27走で
平均0.44秒・最大1.83秒で、特に**少頭数のレースで大きく外れて**いました。

この作り方なので、**推定ラップの合計は必ず実際の走破タイムと一致**し、
**最後の3区間の合計は実測の上がり3Fと一致**します。

#### 限界（ここは推定です）

- コーナーとコーナーの**間にはアンカーが無い**ため、**中盤の形はレースラップに近くなります**
- コーナーの位置は、コース図と同じ**自前の近似**（数十mのずれはありえます）
- 係数は**芝1800〜2600mの27走**に合わせたものです（短距離やダートでは確かめていません）
- 実測で確定しているのは**残り600m地点まで**で、そこから前は推定です
- **内・外を回った距離ロス、不利、馬群の密度**は考慮していません
- コーナー通過順が取れない走（直線競走や記録漏れ）は、上がり3Fのアンカーだけで出すため
  **参考値**（破線）として区別しています
- 区間ラップが {MIN_LAP_SEC:.0f}秒未満・{MAX_LAP_SEC:.0f}秒超になった区間は、
  推定に失敗したものとして**線を切って**います

実測ではなく**推定値**です。馬の走り方の傾向をつかむ目安として見てください。
"""
