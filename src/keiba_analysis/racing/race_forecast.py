"""そのレースの「同条件の平均ラップ」と「本日の想定ラップ」。

レース見出しの下（コース図の右）に出すグラフのための計算。表示は race_chart.py。

- **平均ラップ** … 同じ場・馬場・距離・クラスで行われた過去レースの区間ごとの平均。
  同じ距離なら区間の切り方は同じなので、区間ごとに平均と標準偏差を出せる。
- **想定ラップ** … 平均ラップを出発点に、**本日のメンバー**（逃げ・先行の頭数、出走頭数）と
  **想定クッション値**で補正したもの。

## 補正の根拠（すべて手元のDBで実測した値）
| 効果 | 係数 | 材料 |
|---|---|---|
| クッション値 | −0.041秒/1F（+1.0硬くなると速くなる） | 芝4,058本（同場・同距離・同クラス・同馬場で調整） |
| 逃げ・先行の頭数 | −0.053秒（前半3F） | 5,262レース中4,579組 |
| 出走頭数 | −0.055秒（前半3F） | 同上 |
| 前後半のトレードオフ | 前半が1秒速いと上がりは0.33秒遅い | 相関 −0.31 |

**いちばん効くのは馬場状態**で、クッション値は良馬場の中ではほとんど効かない
（良馬場の芝4,579レースで相関 -0.06）。以前はクッション値に -0.041秒/F という大きな係数を
当てていたが、それは実際には馬場状態の代理だった。メンバーの補正の説明力は小さく、
あくまで「平均からどちら向きに振れそうか」の目安として使う。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

# --- 馬場（馬場状態・含水率・クッション値）の補正 -----------------------------
# 手元のDB（芝5,821・ダート6,058レース）で実測した「同条件の平均からのずれ」。
# **タイムを決めているのは馬場状態**で、クッション値は良馬場の中ではほとんど効かない
# （良馬場の芝4,579レースで 相関 -0.06、クッション1.0あたり0.008秒/F）。
# 以前は馬場状態を使わず、クッション値に -0.041秒/F という大きな係数を当てていたが、
# それは実際には「馬場状態の代理」だった。
GOING_EFFECTS = {
    "turf": {"良": -0.032, "稍重": 0.079, "重": 0.173, "不良": 0.356},
    "dirt": {"良": 0.035, "稍重": -0.011, "重": -0.124, "不良": -0.160},
}
# 含水率（%）。馬場状態を織り込んだあとに残る分。ダートだけわずかに効く（水が浮くと速い）。
MOISTURE_SEC_PER_PERCENT = {"turf": 0.0, "dirt": -0.005}
MOISTURE_REFERENCE = {"turf": 12.0, "dirt": 6.0}  # 実測の平均値
# クッション値。馬場状態を織り込んだあとに残る分（実測 -0.006秒/F）。
CUSHION_SEC_PER_FURLONG = -0.006  # クッション値+1.0あたり、1F（200m）あたりの秒
FRONT_RUNNER_SEC = -0.053  # 逃げ・先行1頭あたり、前半3Fの秒
FIELD_SIZE_SEC = -0.055  # 出走1頭あたり、前半3Fの秒
CLOSING_TRADE_OFF = -0.33  # 前半が1秒速いと上がり3Fは0.33秒遅い
FRONT_RUNNER_SHARE = 0.40  # 条件平均の「逃げ・先行の割合」（実測の中央値）

OPENING_SEGMENTS = 3  # 前半3F（最初の3区間）
CLOSING_SEGMENTS = 3  # 上がり3F（最後の3区間）

# --- 馬場差（当日・前の開催日の実測ラップから測る）---------------------------
# 「その日その馬場が、馬場状態まで織り込んだ想定よりどれだけ速いか」は、まだ日ごとに
# 0.08秒/F ほど散る。これを当日と前の開催日の実測から拾う。
# 下は手元のDBでの実測（馬場状態・含水率を補正したあとの残りで測り直した値）:
#   前日のずれ → 当日のずれ            : 相関+0.59 / 回帰係数0.60（n=1,078）
#   前週のずれ → 当日のずれ            : 相関+0.46 / 回帰係数0.46（n=865）
#   3週間以上空くと相関は+0.0（引き継がれない）
#   当日1〜5R＋前の開催日 → 同じ日の6R以降:
#       前日と組む場合 当日0.44・前日0.30／前週と組む場合 当日0.53・前週0.24
TODAY_SOLO_WEIGHTS = {1: 0.50, 2: 0.55}
TODAY_SOLO_WEIGHT = 0.60  # 3本以上
# 前の開催日との間隔ごとの重み:
#   (間隔の上限日, 前の開催日だけのときの重み, 当日の材料もあるときの重み, 当日にかける割合)
PREVIOUS_RULES = ((1, 0.60, 0.30, 0.73), (8, 0.46, 0.24, 0.88))
MAX_PREVIOUS_GAP_DAYS = PREVIOUS_RULES[-1][0]  # これより前の開催日は使わない


@dataclass(frozen=True)
class AverageLaps:
    """同条件の平均ラップ。"""

    laps: list[float]  # 区間ごとの平均
    deviations: list[float]  # 区間ごとの標準偏差（ばらつきの帯に使う）
    distances: list[float]  # 各区間の終わりの累計距離
    races: int  # 平均に使ったレース数
    cushion: float | None  # その条件の平均クッション値（芝のみ）
    field_size: float | None  # その条件の平均出走頭数

    @property
    def total(self) -> float:
        return sum(self.laps)

    @property
    def front_runners(self) -> float | None:
        """その条件で普通にいる「逃げ・先行の頭数」。平均頭数 × 実測の割合。"""
        return self.field_size * FRONT_RUNNER_SHARE if self.field_size else None


@dataclass(frozen=True)
class TrackBias:
    """当日・前の開催日の実測から測った馬場差（1Fあたりの秒。マイナス＝速い）。"""

    seconds_per_furlong: float
    today_races: int
    previous_races: int
    today_delta: float | None  # 当日のずれの平均（そのまま。重みをかける前）
    previous_delta: float | None
    previous_date: str | None = None  # 前の開催日（例: 前週の同じ開催）
    previous_gap_days: int = 1  # その開催日との間隔

    @property
    def has_material(self) -> bool:
        return bool(self.today_races or self.previous_races)


def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def previous_rule(gap_days: int) -> tuple[float, float, float] | None:
    """前の開催日との間隔に応じた重み。離れすぎていれば None（使わない）。"""
    for limit, solo, with_today, today_ratio in PREVIOUS_RULES:
        if gap_days <= limit:
            return solo, with_today, today_ratio
    return None


def track_bias(
    today_deltas: list[float],
    previous_deltas: list[float],
    previous_gap_days: int = 1,
    previous_date: str | None = None,
) -> TrackBias:
    """当日・前の開催日の「想定からのずれ」から馬場差を出す。

    deltas は1レースにつき1つで、**その馬場のそのレースの1Fあたり実測 − 期待値**
    （期待値＝同条件の平均＋馬場状態・含水率・クッションの補正）。
    当日のほうが当てになるので重く見る。前の開催日は間隔が開くほど軽く見る
    （前日0.60・前週0.46。3週間以上空くと引き継がれないので使わない）。
    """
    rule = previous_rule(previous_gap_days) if previous_deltas else None
    today = _mean(today_deltas)
    previous = _mean(previous_deltas) if rule else None

    if today is None and previous is None:
        bias = 0.0
    elif today is None:
        bias = rule[0] * previous
    else:
        weight = TODAY_SOLO_WEIGHTS.get(len(today_deltas), TODAY_SOLO_WEIGHT)
        if previous is None:
            bias = weight * today
        else:
            solo, with_today, today_ratio = rule
            bias = today_ratio * weight * today + with_today * previous
    return TrackBias(
        seconds_per_furlong=round(bias, 3),
        today_races=len(today_deltas),
        previous_races=len(previous_deltas) if previous is not None else 0,
        today_delta=round(today, 3) if today is not None else None,
        previous_delta=round(previous, 3) if previous is not None else None,
        previous_date=previous_date if previous is not None else None,
        previous_gap_days=previous_gap_days,
    )


def bias_delta(
    pace: float,
    baseline_pace: float,
    cushion: float | None = None,
    baseline_cushion: float | None = None,
    surface: str | None = None,
    going: str | None = None,
    moisture: float | None = None,
) -> float:
    """終わったレース1本ぶんの「馬場差」（1Fあたりの秒）。

    実測 − 条件平均 から、**馬場状態・含水率・クッション値で説明できるぶんを引く**。
    残りだけを馬場差として扱うので、想定ラップでこれらの補正と足しても二重にならない。
    """
    delta = pace - baseline_pace - going_delta(surface, going) - moisture_delta(surface, moisture)
    if cushion is not None and baseline_cushion is not None:
        delta -= CUSHION_SEC_PER_FURLONG * (cushion - baseline_cushion)
    return delta


def bias_from_races(today_races: list[dict], previous_races: list[dict]) -> TrackBias:
    """`data.get_track_bias_races()` が返した行から馬場差を出す。

    前の開催日は行に入っている `gap_days` で重みを変える（前日か前週かで効き方が違う）。
    """
    def deltas(races: list[dict]) -> list[float]:
        return [
            bias_delta(
                r["pace"], r["baseline_pace"], r.get("cushion_value"), r.get("baseline_cushion"),
                surface=r.get("surface"), going=r.get("going"), moisture=r.get("moisture"),
            )
            for r in races
            if r.get("pace") is not None and r.get("baseline_pace") is not None
        ]

    gap = int(previous_races[0].get("gap_days") or 1) if previous_races else 1
    previous_date = previous_races[0].get("race_date") if previous_races else None
    return track_bias(deltas(today_races), deltas(previous_races), gap, previous_date)


def format_race_time(seconds: float | None) -> str:
    """走破タイムの表記。`146.7` → `2:26.7`、60秒未満はそのまま `58.4`。"""
    if seconds is None:
        return "—"
    minutes, rest = divmod(round(seconds, 1), 60)
    return f"{int(minutes)}:{rest:04.1f}" if minutes else f"{rest:.1f}"


def three_furlong_split(laps: list[float]) -> tuple[float | None, float | None]:
    """(前半3F, 上がり3F)。区間が6つに満たないレースは出せないので None を返す。"""
    if len(laps) < OPENING_SEGMENTS + CLOSING_SEGMENTS:
        return None, None
    return (
        round(sum(laps[:OPENING_SEGMENTS]), 1),
        round(sum(laps[-CLOSING_SEGMENTS:]), 1),
    )


def time_label(laps: list[float]) -> str:
    """`2:26.7 (35.9-35.4)` の形。カッコの中は 前半3F-上がり3F。"""
    total = format_race_time(sum(laps)) if laps else "—"
    first, last = three_furlong_split(laps)
    if first is None or last is None:
        return total
    return f"{total} ({first:.1f}-{last:.1f})"


def _split(text: str | None) -> list[float]:
    if not text:
        return []
    try:
        return [float(x) for x in str(text).split("-")]
    except ValueError:
        return []


def average_laps(races: list[dict]) -> AverageLaps | None:
    """同条件の過去レースから、区間ごとの平均ラップを作る。

    同じ距離でも区間の数が違うデータ（壊れた行）は混ぜない。1本も無ければ None。
    """
    series: list[list[float]] = []
    distances: list[float] = []
    for race in races:
        laps = _split(race.get("race_laps"))
        lap_distances = _split(race.get("lap_distances"))
        if not laps or len(laps) != len(lap_distances):
            continue
        if not distances:
            distances = lap_distances
        if len(laps) != len(distances):
            continue  # 区間数が違うものは混ぜない
        series.append(laps)
    if not series:
        return None

    cushions = [r["cushion_value"] for r in races if r.get("cushion_value") is not None]
    sizes = [r["n_runners"] for r in races if r.get("n_runners")]
    return AverageLaps(
        laps=[round(statistics.mean(s[i] for s in series), 2) for i in range(len(distances))],
        deviations=[
            round(statistics.pstdev([s[i] for s in series]), 2) if len(series) > 1 else 0.0
            for i in range(len(distances))
        ],
        distances=distances,
        races=len(series),
        cushion=round(statistics.mean(cushions), 2) if cushions else None,
        field_size=round(statistics.mean(sizes), 1) if sizes else None,
    )


def opening_delta(
    average: AverageLaps, front_runners: int | None, field_size: int | None
) -> float:
    """本日のメンバーで、前半3Fが平均からどれだけ動くか（マイナス＝速くなる）。"""
    delta = 0.0
    if front_runners is not None and average.front_runners is not None:
        delta += FRONT_RUNNER_SEC * (front_runners - average.front_runners)
    if field_size and average.field_size:
        delta += FIELD_SIZE_SEC * (field_size - average.field_size)
    return delta


def cushion_delta(average: AverageLaps, cushion: float | None) -> float:
    """想定クッション値で、1区間（200m）あたり何秒動くか。芝で値があるときだけ効く。

    馬場状態を織り込んだあとに残る分だけなので、効き方は小さい（実測 -0.006秒/F）。
    """
    if cushion is None or average.cushion is None:
        return 0.0
    return CUSHION_SEC_PER_FURLONG * (cushion - average.cushion)


def going_delta(surface: str | None, going: str | None) -> float:
    """馬場状態（良/稍重/重/不良）で、1区間あたり何秒動くか。

    **想定タイムをいちばん大きく動かす要素**。芝は渋るほど遅く（重で+0.17秒/F）、
    ダートは水を含むほど速くなる（不良で-0.16秒/F）。条件平均は馬場状態を混ぜた
    平均なので、良馬場でも「良のぶんだけ速い」補正が入る。
    """
    return GOING_EFFECTS.get(surface or "", {}).get(going or "", 0.0)


def moisture_delta(surface: str | None, moisture: float | None) -> float:
    """含水率（%）で、1区間あたり何秒動くか。馬場状態のあとに残る分だけ。"""
    if moisture is None or surface not in MOISTURE_SEC_PER_PERCENT:
        return 0.0
    return MOISTURE_SEC_PER_PERCENT[surface] * (moisture - MOISTURE_REFERENCE[surface])


def track_delta(
    average: AverageLaps,
    surface: str | None,
    going: str | None,
    moisture: float | None,
    cushion: float | None,
) -> float:
    """馬場まわり（馬場状態・含水率・クッション値）の補正をまとめた秒/F。"""
    return (
        going_delta(surface, going)
        + moisture_delta(surface, moisture)
        + cushion_delta(average, cushion)
    )


def project_laps(
    average: AverageLaps,
    front_runners: int | None = None,
    field_size: int | None = None,
    cushion: float | None = None,
    bias: TrackBias | None = None,
    surface: str | None = None,
    going: str | None = None,
    moisture: float | None = None,
) -> list[float]:
    """本日の想定ラップ。

    - 前半3区間に「メンバーによる前半の変化」を均等に配分する
    - 上がり3区間に、その **−0.33倍**（前半が速いと上がりは遅い）を配分する
    - 全区間に、**馬場状態**・含水率・クッション値による変化と、
      **馬場差**（当日・前日の実測）を加える

    馬場差は「クッション補正でも説明できない残り」を測ったものなので、
    クッション補正と足しても二重にならない（呼び出し側が期待値から引いて渡す）。
    """
    opening = opening_delta(average, front_runners, field_size)
    closing = CLOSING_TRADE_OFF * opening
    per_furlong = track_delta(average, surface, going, moisture, cushion)
    if bias is not None:
        per_furlong += bias.seconds_per_furlong

    laps = list(average.laps)
    n = len(laps)
    for i in range(min(OPENING_SEGMENTS, n)):
        laps[i] += opening / OPENING_SEGMENTS
    for i in range(max(0, n - CLOSING_SEGMENTS), n):
        laps[i] += closing / CLOSING_SEGMENTS
    return [round(lap + per_furlong, 2) for lap in laps]


EXPLANATION = f"""
#### 平均ラップと想定ラップについて

- **平均ラップ（点線）** … 同じ競馬場・馬場・距離・クラスで行われた**過去レースの区間平均**です。
  薄い帯は区間ごとの**ばらつき（±1標準偏差）**で、ここに収まるのが普通くらいの目安です。
  同じ条件のレースが5本に満たないときは、**クラスの条件を外して**同じコースの平均を使います。
- **想定ラップ（実線）** … 平均ラップに、**本日のメンバー**と**想定クッション値**の補正を加えたものです。

| 補正 | 係数（手元のDBで実測） |
|---|---|
| **馬場状態** | 芝: 稍重 **+{GOING_EFFECTS["turf"]["稍重"]:.3f}** / 重 **+{GOING_EFFECTS["turf"]["重"]:.3f}** / 不良 **+{GOING_EFFECTS["turf"]["不良"]:.3f}** 秒/F（良は{GOING_EFFECTS["turf"]["良"]:.3f}）<br>ダート: 稍重 {GOING_EFFECTS["dirt"]["稍重"]:.3f} / 重 {GOING_EFFECTS["dirt"]["重"]:.3f} / 不良 {GOING_EFFECTS["dirt"]["不良"]:.3f} 秒/F（良は+{GOING_EFFECTS["dirt"]["良"]:.3f}） |
| 含水率 | ダートのみ 1%あたり **{MOISTURE_SEC_PER_PERCENT["dirt"]:.3f}秒/F**（芝は効きません） |
| クッション値 | 1.0硬くなるごとに **1Fあたり {abs(CUSHION_SEC_PER_FURLONG):.3f}秒速く**（芝のみ） |
| 逃げ・先行の頭数 | 1頭増えるごとに **前半3Fが {abs(FRONT_RUNNER_SEC):.3f}秒速く**（4,579組） |
| 出走頭数 | 1頭増えるごとに **前半3Fが {abs(FIELD_SIZE_SEC):.3f}秒速く**（同上） |
| 前後半のつり合い | 前半が1秒速いと **上がり3Fは{abs(CLOSING_TRADE_OFF):.2f}秒遅く**（相関 −0.31） |

#### 馬場差（当日・前日の実測ラップ）

当日すでに行われたレースと前日のレースの**実測ラップ**を、同じ条件の平均と比べて
「その日その馬場がどれだけ速いか（1Fあたり何秒か）」を測り、**全区間に一律で加えます**。

| 材料 | 重み（手元のDBで実測した回帰係数） |
|---|---|
| 当日（同じ場・同じ馬場・そのレースより前） | 3本以上で **{TODAY_SOLO_WEIGHT}**（1本なら0.50、2本なら0.55） |
| **前日**（同じ場・同じ馬場） | 当日の材料があれば **0.30**、無ければ **0.60** |
| **前週**（4〜8日前の同じ開催） | 当日の材料があれば **0.24**、無ければ **0.46** |

前日のずれと当日のずれの相関は**+0.59**、前週とでも**+0.46**あり、間隔が開くほど軽く見ます
（3週間以上空くと相関はほぼ0になるので使いません）。当日の序盤と組み合わせると、
その日の後半のずれのばらつきが **0.086秒/F → 0.064秒/F（26%減）** になります。
なお馬場差は「馬場状態・含水率・クッション値では説明できない残り」として測るので、
それらの補正と足しても二重にはなりません。

#### どれくらい当たるか（手元のDBでの実測）

「同条件の平均からのずれ」を当てにいったときの誤差（RMSE・秒/F、芝5,821／ダート6,058レース）:

| | 補正なし | 以前（クッションのみ） | 馬場状態＋含水率 | ＋馬場差 |
|---|---|---|---|---|
| 芝 | 0.142 | 0.138 | **0.124** | **0.110** |
| ダート | 0.121 | 0.121 | **0.107** | **0.094** |

2000mなら 0.124秒/F ≒ **1.2秒**のばらつきです。馬場状態を入れたことで、以前より
芝で11%・ダートで12%（馬場差と併用しても4〜5%）誤差が小さくなりました。

#### 限界
- 補正の**説明力は小さい**です（メンバーの補正を入れても、前半3Fのばらつきは0.67秒→0.64秒ほど）。
  「平均からどちら向きに振れそうか」の目安として見てください。
- 脚質は**通過順位から判定した暫定のもの**で、当日の枠順・展開・騎手の乗り方は考慮していません。
- **クッション値はJRAが当日発表**するもので、開催前は手元のDBに入りません。
  初期値はその条件の平均で、入力欄で変えると想定ラップが動きます。
- ダートにはクッション値が無いため、クッションの補正はかかりません。
- 馬場差は**全区間に一律**で足しています（内・外の伸び方や、前残り・差し決着といった傾向までは見ていません）。
- 当日・前日の結果がDBに無いときは馬場差を0として扱います（`uv run keiba update` で取り込めます）。
"""
