"""区間ラップを「前後は200mごと・中間だけ平均」の6点にまとめる。

200mごとのラップは、距離の違うレースを重ねると区間数も横軸の長さも変わってしまい、
形を見比べにくい。そこで**中間だけを平均**して距離差を吸収し、
**テンの2Fと上がり3Fは200mごとのまま**残す。値は1Fあたりの秒なので縦軸も共通。

    200m ─ 400m ─ 中間(平均) ─ 残600m ─ 残400m ─ 残200m
    └─ 前2F は200mずつ ─┘        └─ 上り3F は200mずつ ─┘

    200m / 400m     … スタートからの到達距離（0〜200m、200〜400m）
    中間            … 前2Fと上り3Fを除いた区間の平均
    残600m / 残400m / 残200m … ゴールまでの残り距離（上り3Fを200mずつ）

**最初の区間が100mのレース**（1300・1500・1700・1900・2100・2500m。1150mは150m）は、
400m地点が区間の途中に来る。その場合は**距離で按分**して400m地点の時間を出すので、
どのレースも同じ「スタート〜400m」を前2Fとして扱える。

レース全体のラップにも、個別推定ラップ（lap_estimate.py）にも同じ関数を使う。
推定できなかった区間（None）が混ざる区分は、その区分ごと None にして線を切る。
"""

from __future__ import annotations

OPENING_M = 400  # 前2F
CLOSING_M = 600  # 上り3F
FURLONG_M = 200

OPENING_LABELS = ("200m", "400m")                 # スタートからの到達距離
MIDDLE = "中間"
CLOSING_LABELS = ("残600m", "残400m", "残200m")    # ゴールまでの残り距離
PHASE_LABELS = (*OPENING_LABELS, MIDDLE, *CLOSING_LABELS)


def phase_ranges(distance_m: float) -> list[tuple[str, float, float]]:
    """区分の (名前, 開始m, 終了m) を進行順に返す。

    前半は200mずつ2つ、後半（上り3F）は200mずつ3つ、その間が「中間」。
    1000m戦のように前後で埋まってしまうレースは中間を作らない（5点になる）。
    """
    if not distance_m or distance_m <= CLOSING_M:
        return []
    closing_start = float(distance_m - CLOSING_M)

    ranges = []
    for i, name in enumerate(OPENING_LABELS):
        start, end = float(FURLONG_M * i), float(FURLONG_M * (i + 1))
        if end > closing_start:  # 上り3Fと重なる区分は作らない
            break
        ranges.append((name, start, end))

    opening_end = ranges[-1][2] if ranges else 0.0
    if closing_start - opening_end > 1e-9:
        ranges.append((MIDDLE, opening_end, closing_start))

    for i, name in enumerate(CLOSING_LABELS):
        start = closing_start + FURLONG_M * i
        end = min(start + FURLONG_M, float(distance_m))
        if end - start > 1e-9:
            ranges.append((name, start, end))
    return ranges


def _phase_seconds(
    values: list[float | None], distances: list[float], start: float, end: float
) -> float | None:
    """区分 [start, end) の所要時間。区間が境界をまたぐときは距離で按分する。"""
    total = 0.0
    previous = 0.0
    for value, boundary in zip(values, distances, strict=True):
        overlap = min(boundary, end) - max(previous, start)
        if overlap > 1e-9:
            if value is None:
                return None  # 推定できなかった区間を含む区分は出さない
            length = boundary - previous
            total += value * (overlap / length) if length > 0 else 0.0
        previous = boundary
    return total


def phase_paces(
    values: list[float | None], distances: list[float], distance_m: float
) -> dict[str, float | None]:
    """区分ごとの**1Fあたりの秒**（区分の所要時間 ÷ 区分の距離/200m）。

    values: 区間ラップ（Noneを含みうる）／distances: 各区間の終わりの累計距離
    """
    if not values or len(values) != len(distances) or not distance_m:
        return {}
    # ラップがレース距離ぶん揃っていないデータは区分できない
    # （実データでは必ず一致する。壊れた入力で中途半端な値を出さないためのガード）
    if abs(distances[-1] - distance_m) > 1:
        return {}
    paces: dict[str, float | None] = {}
    for name, start, end in phase_ranges(distance_m):
        seconds = _phase_seconds(values, distances, start, end)
        furlongs = (end - start) / FURLONG_M
        paces[name] = round(seconds / furlongs, 2) if seconds is not None and furlongs > 0 else None
    return paces


# 画面の「このグラフについて」に出す説明（lap_estimate.EXPLANATION と並べて使う）
EXPLANATION = f"""
#### 横軸の区分について（前後200m＋中間平均）

距離の違うレースを重ねて見比べられるように、**中間だけを平均**して距離差を吸収し、
**テンの2Fと上がり3Fは200mごとのまま**出しています。
縦軸は**1Fあたり（200mあたり）の秒**なので、どの区分も同じ尺度で比べられます。

| 区分 | 範囲 |
|---|---|
| {OPENING_LABELS[0]} | スタート〜200m |
| {OPENING_LABELS[1]} | 200m〜400m |
| {MIDDLE} | 400m 〜 残り{CLOSING_M}m（**その間のラップの平均**） |
| {CLOSING_LABELS[0]} | 残り{CLOSING_M}m〜残り400m |
| {CLOSING_LABELS[1]} | 残り400m〜残り200m |
| {CLOSING_LABELS[2]} | 残り200m〜ゴール |

- 中間以外は**その区間のラップそのもの**です（平均していません）。
- **最初の区間が100mのレース**（1500m・1700m・2500mなど）は、200m・400m地点が区間の途中に来るので、
  **距離で按分**しています。どのレースも同じ「スタート〜200m」「200〜400m」で比べられます。
- 1000m戦のように中間が取れないレースは5点になります。
- 200mごとの細かいラップを最後まで見たいときは、グラフの上の「見せ方」を切り替えてください。
"""
