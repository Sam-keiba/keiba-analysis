"""その馬の「同一馬場種別の全成績」を条件別に集計する。

モーダルのラップ推移グラフが**直近5走**なのに対して、ここは
**芝なら芝の全走・ダートならダートの全走**が対象（`data.get_runs_for_stats`）。

3つの切り口で集計する。

- **ペース別** … レースの前後半3Fから決まるペース（pace.py の暫定判定）
- **馬場の硬さ × 馬場状態** … レース当日の**芝はクッション値・ダートは含水率**（どちらもJRA発表）と
  馬場状態のマス目。硬さ（クッション値・含水率）と水分（馬場状態）は別の軸なので、
  片方だけで見ると「同じ8.5〜10.0でも良と重が混ざる」ことになるため2次元で持つ
- **脚質の割合** … その走の脚質（running_style.py の暫定判定）

どれも出走数が少ないと当てになりにくいので、区分ごとに「材料が足りているか」
（`enough`）を持たせ、画面側で薄く描いたり注意書きを出したりできるようにする。
"""

from __future__ import annotations

from dataclasses import dataclass

from keiba_analysis.racing import pace
from keiba_analysis.racing.running_style import STYLES, classify_run

MIN_SAMPLE = 3   # この出走数に満たない区分は「参考」（画面では薄く描く）
SMALL_TOTAL = 5  # 全体がこれ未満なら「サンプルが少ない」と断る

# 芝のクッション値の区切り（小さいほど軟らかく、大きいほど硬い）。
# 馬場状態とのマス目にするので、細かく割ると1頭ぶんではどのマスも埋まらない。
# DBの芝6,137レースでは 〜8.5 が985本・8.5〜10.0 が4,170本・10.0〜 が1,057本。
CUSHION_EDGES = (8.5, 10.0)
CUSHION_LABELS = ("〜8.5", "8.5〜10.0", "10.0〜")

# ダートの含水率（ゴール前。JRA発表。高いほど水分が多い＝時計が速い）の区切り。
# 手元のDBのダート6,155レースでは中央値4.9%（良3.3 / 稍重8.3 / 重12.6 / 不良14.3）。
# 4%と8%で切ると 41% / 32% / 27% と偏りが小さい。
DIRT_MOISTURE_EDGES = (4.0, 8.0)
DIRT_MOISTURE_LABELS = ("〜4%", "4〜8%", "8%〜")

# 馬場状態（軽い順）。芝はこの4つしか出ない（DBの芝レースで実際に確認済み）。
GOING_LABELS = ("良", "稍重", "重", "不良")

PACE_LABELS = ("ハイ", "ミドル", "スロー")
_PACE_BY_MARK = {pace.HIGH: "ハイ", pace.MIDDLE: "ミドル", pace.SLOW: "スロー"}


@dataclass(frozen=True)
class Bucket:
    """1つの区分（例: 「ハイペース」）の成績。"""

    label: str
    starts: int  # 出走数（着順が分かる走のみ）
    wins: int
    top3: int
    average_finish: float | None

    @property
    def rate(self) -> float:
        """複勝率（3着内率）。出走が無ければ0。"""
        return self.top3 / self.starts if self.starts else 0.0

    @property
    def enough(self) -> bool:
        """傾向として読める程度の出走数があるか。"""
        return self.starts >= MIN_SAMPLE


def _bucket(label: str, runs: list[dict]) -> Bucket:
    """着順の分かる走から1区分ぶんの成績を作る。"""
    finishes = [r["finish_position"] for r in runs if r.get("finish_position")]
    return Bucket(
        label=label,
        starts=len(finishes),
        wins=sum(1 for f in finishes if f == 1),
        top3=sum(1 for f in finishes if f <= 3),
        average_finish=round(sum(finishes) / len(finishes), 1) if finishes else None,
    )


def total_starts(runs: list[dict]) -> int:
    """着順が分かる走の数（取消・中止は数えない）。"""
    return sum(1 for r in runs if r.get("finish_position"))


def hardness_field(surface: str | None) -> str:
    """馬場の硬さを持っている列の名前（芝＝クッション値／ダート＝含水率）。"""
    return "dirt_moisture_goal" if surface == "dirt" else "cushion_value"


def hardness_labels(surface: str | None) -> tuple[str, ...]:
    """横軸の区分（軟らかい／乾いている ほうから）。"""
    return DIRT_MOISTURE_LABELS if surface == "dirt" else CUSHION_LABELS


def hardness_edges(surface: str | None) -> tuple[float, ...]:
    return DIRT_MOISTURE_EDGES if surface == "dirt" else CUSHION_EDGES


def hardness_label(value: float | None, surface: str | None = "turf") -> str | None:
    """馬場の硬さが入る区分の名前。値が無ければ None。境目は上の区分に入れる。"""
    if value is None:
        return None
    labels = hardness_labels(surface)
    for edge, label in zip(hardness_edges(surface), labels, strict=False):
        if value < edge:
            return label
    return labels[-1]


def summarize_pace(runs: list[dict]) -> list[Bucket]:
    """ペース別の成績（ハイ・ミドル・スロー）。ラップが無い走は除く。"""
    grouped: dict[str, list[dict]] = {label: [] for label in PACE_LABELS}
    for run in runs:
        mark = pace.classify(run.get("race_first_3f"), run.get("race_last_3f"))
        if mark is not None:
            grouped[_PACE_BY_MARK[mark]].append(run)
    return [_bucket(label, grouped[label]) for label in PACE_LABELS]


@dataclass(frozen=True)
class Grid:
    """馬場の硬さ（横）× 馬場状態（縦）のマス目。

    横軸は芝ならクッション値、ダートなら含水率（`hardness_labels`）。
    合計（`by_going` / `by_hardness` / `total`）は**マスに入った走をそのまま足し直して**
    作るので、行・列の合計と各マスの数が必ず合う。
    1頭ぶんだとマスはかなり疎になる（芝52走の馬でも空のマスが出る）ので、
    合計の行と列を見れば片方の軸だけの傾向も読める。
    """

    cells: dict[tuple[str, str], Bucket]  # (馬場状態, 硬さの区分) -> 成績
    by_going: dict[str, Bucket]  # 行の計
    by_hardness: dict[str, Bucket]  # 列の計
    total: Bucket  # 全部の計
    surface: str | None = "turf"  # 横軸が何か（芝＝クッション値／ダート＝含水率）


def summarize_hardness_going(runs: list[dict], surface: str | None = "turf") -> Grid:
    """馬場の硬さ × 馬場状態のマス目（芝はクッション値、ダートは含水率）。

    その値が無い走（未発表の日）と、馬場状態が無い走は入れない。
    走っていないマスも `starts=0` で残す（走っていないことが分かるように）。
    """
    labels = hardness_labels(surface)
    field = hardness_field(surface)
    grouped: dict[tuple[str, str], list[dict]] = {
        (going, hardness): [] for going in GOING_LABELS for hardness in labels
    }
    for run in runs:
        hardness = hardness_label(run.get(field), surface)
        going = run.get("going")
        if hardness is None or going not in GOING_LABELS:
            continue
        grouped[(going, hardness)].append(run)

    return Grid(
        cells={key: _bucket(key[1], value) for key, value in grouped.items()},
        by_going={
            going: _bucket(going, [r for c in labels for r in grouped[(going, c)]])
            for going in GOING_LABELS
        },
        by_hardness={
            hardness: _bucket(
                hardness, [r for g in GOING_LABELS for r in grouped[(g, hardness)]]
            )
            for hardness in labels
        },
        total=_bucket("計", [r for runs_in_cell in grouped.values() for r in runs_in_cell]),
        surface=surface,
    )


def summarize_style(runs: list[dict]) -> list[Bucket]:
    """脚質ごとの走った回数（割合グラフ用）。通過順が無い走は除く。"""
    grouped: dict[str, list[dict]] = {style: [] for style in STYLES}
    for run in runs:
        style = classify_run(run.get("corner_passing"), run.get("n_runners"))
        if style is not None:
            grouped[style].append(run)
    return [_bucket(style, grouped[style]) for style in STYLES]


def style_shares(buckets: list[Bucket]) -> list[tuple[str, float]]:
    """脚質ごとの割合（合計1.0）。1走も無ければ空。"""
    total = sum(b.starts for b in buckets)
    if not total:
        return []
    return [(b.label, b.starts / total) for b in buckets]
