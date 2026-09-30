"""脚質（逃げ・先行・差し・追込）の判定。

**これは暫定のロジックで、後日改善する予定。**
いまは過去走のコーナー通過順位だけを使い、次のように決めている。

1. 1走ごとに「平均通過順位」を出し、頭数で正規化する
   normalized = (平均通過順位 - 1) / (頭数 - 1)   → 0=常に先頭 / 1=常に最後方
2. 正規化した値を閾値で4つに分ける（THRESHOLDS）
3. 直近10走ぶんを分類し、いちばん多かった脚質をその馬の脚質とする
   （同数のときは、より前に行く脚質を採用する）

改善の余地（次のフェーズ以降）:
- 距離・コース・頭数の違いや、展開（ペース）の影響を考慮していない
- 新しい走ほど重く見る、といった重み付けをしていない
- コーナーが2つのレースと4つのレースを同じに扱っている
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

# 正規化した平均通過順位の閾値。これを超えると次の脚質になる（暫定値）。
# 旧ツール（legacy/keiba_old/config.py の RUNNING_STYLE_THRESHOLDS）と同じ値を使っている。
THRESHOLDS: dict[str, float] = {"逃げ": 0.10, "先行": 0.30, "差し": 0.60}
STYLES = ("逃げ", "先行", "差し", "追込")  # 前に行く順
SAMPLE_LIMIT = 10  # 判定に使う直近の走数


@dataclass(frozen=True)
class RunningStyle:
    """その馬の脚質と、判定に使った材料。"""

    style: str  # 逃げ / 先行 / 差し / 追込
    n_samples: int  # 判定に使った走数
    average_position: float  # 正規化した平均通過順位（0=先頭、1=最後方）

    @property
    def index(self) -> int:
        """前に行く順の位置（0=逃げ 〜 3=追込）。バー表示に使う。"""
        return STYLES.index(self.style)


def parse_corner_positions(corner_passing: str | None) -> list[int]:
    """"5-5-4-3" を [5, 5, 4, 3] にする。数字以外は捨てる。"""
    if not corner_passing:
        return []
    positions = []
    for part in corner_passing.split("-"):
        part = part.strip()
        if part.isdigit():
            positions.append(int(part))
    return positions


def normalized_position(corner_passing: str | None, n_runners: int | None) -> float | None:
    """1走ぶんの正規化した平均通過順位（0=常に先頭、1=常に最後方）。"""
    positions = parse_corner_positions(corner_passing)
    if not positions or not n_runners or n_runners <= 1:
        return None
    average = sum(positions) / len(positions)
    return max(0.0, min(1.0, (average - 1) / (n_runners - 1)))


def classify_run(corner_passing: str | None, n_runners: int | None) -> str | None:
    """1走ぶんの脚質。通過順位が無い（障害・中止など）場合は None。"""
    value = normalized_position(corner_passing, n_runners)
    if value is None:
        return None
    for style, threshold in THRESHOLDS.items():
        if value <= threshold:
            return style
    return "追込"


def summarize(runs: list[dict], limit: int = SAMPLE_LIMIT) -> RunningStyle | None:
    """直近の走から、その馬の脚質を決める。材料が無ければ None（新馬など）。"""
    values = []
    for run in runs[:limit]:
        value = normalized_position(run.get("corner_passing"), run.get("n_runners"))
        if value is not None:
            values.append(value)
    if not values:
        return None

    counts = Counter(classify_run_from_value(v) for v in values)
    best = max(counts.values())
    # 同数のときは、より前に行く脚質を採用する
    style = next(s for s in STYLES if counts.get(s, 0) == best)
    return RunningStyle(style=style, n_samples=len(values), average_position=sum(values) / len(values))


def classify_run_from_value(value: float) -> str:
    """正規化済みの値から脚質を決める（classify_run の内部用）。"""
    for style, threshold in THRESHOLDS.items():
        if value <= threshold:
            return style
    return "追込"


def summarize_many(runs_by_horse: dict[str, list[dict]], limit: int = SAMPLE_LIMIT) -> dict[str, RunningStyle]:
    """馬ID -> 脚質。材料が無い馬はキーごと入れない。"""
    result = {}
    for horse_id, runs in runs_by_horse.items():
        style = summarize(runs, limit)
        if style is not None:
            result[horse_id] = style
    return result
