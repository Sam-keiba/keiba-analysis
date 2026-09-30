"""レースのペース（S＝スロー / M＝ミドル / H＝ハイ）の判定。

**これは暫定のロジックで、後日改善する予定。**（脚質＝running_style.py と同じ扱い）
いまは1レースの前半3Fと後半3Fの差だけを見て、次のように決めている。

    後半3F - 前半3F >= 1.0秒  → H（前半が速い＝ハイペース）
    前半3F - 後半3F >= 1.0秒  → S（前半が遅い＝スローペース）
    それ以外                  → M（ミドル）

前半3F・後半3Fは `race_laps`（JRA公表のレースラップ）の最初／最後の3区間の合計で、
netkeibaの結果ページのペース表記 `(36.3-34.5)` と一致する。

改善の余地（次のフェーズ以降）:
- 距離・馬場・クラスごとの基準タイムと比べていない（1200mと2500mを同じ尺度で見ている）
- 馬場状態（良/重）の影響を考慮していない
- netkeibaなどの公表するペース判定とは別物なので、画面にも「暫定」と書いている
"""

from __future__ import annotations

# 前後半3Fの差がこれ以上でハイ／スローとみなす（暫定値）
PACE_DIFF_THRESHOLD_SEC = 1.0

HIGH, MIDDLE, SLOW = "H", "M", "S"

PACE_NAMES = {HIGH: "ハイペース", MIDDLE: "ミドルペース", SLOW: "スローペース"}


def classify(first_3f: float | None, last_3f: float | None) -> str | None:
    """前半3F・後半3Fからペース記号を返す。どちらかが無ければ None（障害戦など）。"""
    if first_3f is None or last_3f is None:
        return None
    diff = last_3f - first_3f  # 正=前半のほうが速い
    if diff >= PACE_DIFF_THRESHOLD_SEC:
        return HIGH
    if -diff >= PACE_DIFF_THRESHOLD_SEC:
        return SLOW
    return MIDDLE


def description(first_3f: float | None, last_3f: float | None) -> str:
    """tooltipに出す説明。例: 「前半3F 36.3 - 後半3F 34.5（ハイペース・暫定判定）」"""
    mark = classify(first_3f, last_3f)
    if mark is None:
        return "ラップが無いためペースは判定できません"
    return f"前半3F {first_3f:.1f} - 後半3F {last_3f:.1f}（{PACE_NAMES[mark]}・暫定判定）"


def classify_run(run: dict) -> str | None:
    """過去走の1行（data.py が返すdict）からペース記号を返す。"""
    return classify(run.get("race_first_3f"), run.get("race_last_3f"))
