"""コース形状の模式図（SVG）を自前で描く。

トラックを **ホームストレッチ（下）＋向正面（上）＋左右2つのコーナー** とし、
コーナーは**4つの1/4楕円（1角・2角・3角・4角）**に分ける。角ごとの横の張り出しを
`course_data.TrackShape` で変えることで、**競馬場ごとに違う形**になる
（中山は小回りで4角が急、東京は大きく緩い、新潟外回りは平たい、など）。

形の決め方:
- ホームストレッチが一周に占める割合は**公式の数値どおり**（`straight_m / lap_m`）
- トラックの高さは、周長が1になるように解いて決める（`_track_height`）
- 向正面の長さと位置は4つの角の張り出しから決まる

輪郭は点列（ポリライン）として持ち、SVGのpathとして描くとともに、
**スタート位置は点列を逆向きにたどって**求める（どんな形でも距離から正しく出せる）。

出典の数値はJRA公式「コース紹介」のコースデータ。図そのものは自前で描いており、
他サイトの画像は使っていない（形は公式図の特徴を数値で言い表した近似）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from keiba_analysis.racing.course_data import (
    COURSES,
    UPHILL_FINISH_VENUES,
    VENUE_DIRECTION,
    CourseSpec,
    TrackShape,
    shape_for,
)

WIDTH, HEIGHT = 330, 230
SURFACE_COLORS = {"turf": "#3f9c6d", "dirt": "#b07d4b", "jump": "#7a5aa8"}
SURFACE_LABELS = {"turf": "芝", "dirt": "ダート", "jump": "障害"}


def select_course(venue_code: str, surface: str, distance_m: int | None, course_detail: str | None) -> tuple[str, CourseSpec] | None:
    """競馬場・馬場・距離・コース表記から、使うコース（内回り/外回り等）を選ぶ。"""
    candidates = {loop: spec for (v, s, loop), spec in COURSES.items() if v == venue_code and s == surface}
    if not candidates:
        return None

    detail = course_detail or ""
    # 新潟の芝1000mは直線コースしかない
    if "straight" in candidates and distance_m == 1000:
        return "straight", candidates["straight"]
    if "" in candidates:
        return "", candidates[""]

    turning = {k: v for k, v in candidates.items() if k in ("inner", "outer")}
    if not turning:
        return None
    if "外" in detail and "outer" in turning:
        return "outer", turning["outer"]
    if "内" in detail and "inner" in turning:
        return "inner", turning["inner"]
    # コース表記が無ければ、その距離が行われるコースを発走距離の一覧から選ぶ
    for loop, spec in turning.items():
        if distance_m in spec.distances:
            return loop, spec
    loop = "inner" if "inner" in turning else next(iter(turning))
    return loop, turning[loop]


POINTS_PER_CORNER = 24  # 1/4楕円を何点で近似するか（多いほど滑らか）


def _quarter_perimeter(alpha: float, height: float = 1.0) -> float:
    """1/4楕円（横半径alpha・縦半径height）の弧長。

    楕円の周長はラマヌジャンの近似式を使い、その1/4を返す。
    """
    a, b = alpha, height
    perimeter = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
    return perimeter / 4


def _track_height(spec: CourseSpec, shape: TrackShape) -> float:
    """周長が1になるときのトラックの高さの半分（b）。

    周長 = ホーム直線 + 向正面 + 4つの角の弧長 で、
      ホーム直線 S = straight_m / lap_m（公式の数値どおり）
      向正面     B = S + b(α1 - α2 - α3 + α4)   ← 角の張り出しの差だけ横にずれる
      角の弧長   = b × Σ(1/4楕円の弧長)
    なので b について1次式になり、そのまま解ける。
    """
    a1, a2, a3, a4 = shape.corner_bulge
    straight = spec.straight_m / spec.lap_m
    arcs = sum(
        _quarter_perimeter(alpha, height)
        for alpha, height in zip(shape.corner_bulge, _corner_heights(shape), strict=True)
    )
    denominator = (a1 - a2 - a3 + a4) + arcs
    return (1 - 2 * straight) / denominator


def _corner_heights(shape: TrackShape) -> tuple[float, float, float, float]:
    """各コーナーの縦の長さ（トラックの高さの半分に対する倍率）。

    コーナーの頂点がホームストレッチ寄り（apex>0）だと、手前の角（1角・4角）が短く急になり、
    奥の角（2角・3角）が長く緩やかに回り込む。
    """
    near, far = shape.apex
    return (1 - near, 1 + near, 1 + far, 1 - far)


def _quarter_points(
    x0: float, y0: float, x1: float, y1: float,
    from_apex: bool = False, steps: int = POINTS_PER_CORNER,
) -> list[tuple[float, float]]:
    """(x0,y0) から (x1,y1) への1/4楕円の点列（始点は含めない）。

    直線とコーナーのいちばん外側（頂点）は、接線の向きをそろえないと折れ目ができる。
    from_apex=False: 直線 → 頂点（始点で水平・終点で垂直）
    from_apex=True : 頂点 → 直線（始点で垂直・終点で水平）
    """
    points = []
    for i in range(1, steps + 1):
        t = (i / steps) * (math.pi / 2)
        if from_apex:
            x = x0 + (x1 - x0) * (1 - math.cos(t))
            y = y0 + (y1 - y0) * math.sin(t)
        else:
            x = x0 + (x1 - x0) * math.sin(t)
            y = y0 + (y1 - y0) * (1 - math.cos(t))
        points.append((x, y))
    return points


@dataclass(frozen=True)
class Outline:
    """トラックの輪郭（点列）と、目印になる区間の位置。"""

    points: list[tuple[float, float]]
    home_start: int  # ホームストレッチの始点（points[home_start] → points[home_start+1]）
    back_start: int  # 向正面の始点（points[back_start] → points[back_start+1]）


def build_outline(spec: CourseSpec, shape: TrackShape) -> Outline:
    """正規化した輪郭（周長1）の点列と、ホームストレッチが始まる位置を返す。

    点列は**進行方向の順**で、先頭がゴール地点。
    ゴール → 1角 → 2角 → 向正面 → 3角 → 4角 → ホームストレッチ → （ゴールへ戻る）

    画面では時計回り（右回り）になるように組む。左回りは呼び出し側で左右を反転する。
    """
    a1, a2, a3, a4 = shape.corner_bulge
    b = _track_height(spec, shape)
    straight = spec.straight_m / spec.lap_m
    back = straight + b * (a1 - a2 - a3 + a4)
    near_apex, far_apex = shape.apex

    bottom, top = b, -b  # 画面のy（下向きが正）
    near_y = bottom - b * (1 - near_apex)  # 1〜2角のいちばん外側の高さ
    far_y = top + b * (1 + far_apex)       # 3〜4角のいちばん外側の高さ
    goal = (0.0, bottom)
    points = [goal]
    # 1角: ゴールから左へ回り込み、いちばん外側（左端）へ
    points += _quarter_points(0.0, bottom, -a1 * b, near_y)
    # 2角: 左端から向正面へ
    back_start_x = -a1 * b + a2 * b
    points += _quarter_points(-a1 * b, near_y, back_start_x, top, from_apex=True)
    # 向正面（右へ進む）
    back_end_x = back_start_x + back
    points.append((back_end_x, top))
    # 3角: 向正面からいちばん外側（右端）へ
    points += _quarter_points(back_end_x, top, back_end_x + a3 * b, far_y)
    # 4角: 右端からホームストレッチへ
    points += _quarter_points(
        back_end_x + a3 * b, far_y, back_end_x + a3 * b - a4 * b, bottom, from_apex=True
    )
    home_start = len(points) - 1
    # ホームストレッチ（左へ進んでゴールへ）
    points.append(goal)
    return Outline(points=points, home_start=home_start, back_start=2 * POINTS_PER_CORNER)


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def point_before_goal(points: list[tuple[float, float]], back_distance: float) -> tuple[float, float]:
    """ゴール（点列の先頭）から、進行方向と逆に back_distance だけ戻った座標。

    1周を超える距離（周長より長いレース）は、1周ぶんを引いてから戻る。
    """
    perimeter = polyline_length(points)
    if perimeter <= 0:
        return points[0]
    remaining = back_distance % perimeter
    # 点列の終点（＝ゴール）から先頭へ向かって逆向きにたどる
    for i in range(len(points) - 1, 0, -1):
        segment = math.dist(points[i - 1], points[i])
        if remaining <= segment or segment == 0:
            ratio = (remaining / segment) if segment else 0.0
            x = points[i][0] + (points[i - 1][0] - points[i][0]) * ratio
            y = points[i][1] + (points[i - 1][1] - points[i][1]) * ratio
            return x, y
        remaining -= segment
    return points[0]


def fit_points(
    points: list[tuple[float, float]], width: float, height: float, cx: float, cy: float
) -> list[tuple[float, float]]:
    """輪郭を描画の枠（width × height）に収まるよう拡大・縮小して中央へ置く。"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    scale = min(width / span_x if span_x else width, height / span_y if span_y else height)
    mid_x, mid_y = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [(cx + (x - mid_x) * scale, cy + (y - mid_y) * scale) for x, y in points]


def mirror_x(points: list[tuple[float, float]], axis: float) -> list[tuple[float, float]]:
    """左右を反転する（左回りのコースを描くのに使う）。"""
    return [(2 * axis - x, y) for x, y in points]


def _path_d(points: list[tuple[float, float]]) -> str:
    head = f"M {points[0][0]:.1f} {points[0][1]:.1f}"
    rest = " ".join(f"L {x:.1f} {y:.1f}" for x, y in points[1:])
    return f"{head} {rest}"


def _straight_course_svg(spec: CourseSpec, distance_m: int | None, color: str, title: str) -> str:
    """新潟の芝1000mのような直線コースの図。"""
    x0, x1, y = 40, WIDTH - 40, 95
    return f"""
<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="コース図" class="course-svg">
  <line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{color}" stroke-width="14" stroke-linecap="round" opacity="0.85"/>
  <line x1="{x1}" y1="{y - 16}" x2="{x1}" y2="{y + 16}" stroke="#d93a3a" stroke-width="3"/>
  <circle cx="{x0}" cy="{y}" r="6" fill="#1b1b1b"/>
  <text x="{x0}" y="{y - 24}" class="cm-label" text-anchor="middle">スタート</text>
  <text x="{x1}" y="{y - 24}" class="cm-label" text-anchor="middle">ゴール</text>
  <text x="{WIDTH / 2}" y="{y + 44}" class="cm-title" text-anchor="middle">{title}</text>
  <text x="{WIDTH / 2}" y="{HEIGHT - 16}" class="cm-note" text-anchor="middle">コーナーの無い直線だけのコース</text>
</svg>"""


def render_course_svg(
    venue_code: str,
    venue_name: str,
    surface: str | None,
    distance_m: int | None,
    direction: str | None,
    course_detail: str | None = None,
) -> str | None:
    """コース模式図のSVGを返す。データが無い組み合わせ（障害など）は None。"""
    if not surface or surface not in ("turf", "dirt"):
        return None
    selected = select_course(venue_code, surface, distance_m, course_detail)
    if selected is None:
        return None
    loop, spec = selected

    color = SURFACE_COLORS.get(surface, "#3f9c6d")
    loop_label = {"inner": "内回り", "outer": "外回り", "straight": "直線"}.get(loop, "")
    notes = [f"1周{spec.lap_m:,.1f}m", f"直線{spec.straight_m:,.1f}m", f"高低差{spec.elevation_m}m"]
    caption = " ／ ".join(notes)

    title = f"{venue_name} {SURFACE_LABELS.get(surface, '')}{loop_label} {distance_m or ''}m".strip()
    if spec.is_straight_course:
        return _straight_course_svg(spec, distance_m, color, title)

    clockwise = (direction or VENUE_DIRECTION.get(venue_code, "right")) == "right"
    cx, cy = WIDTH / 2, 100
    outline = build_outline(spec, shape_for(venue_code, loop))
    points = fit_points(outline.points, WIDTH - 74, HEIGHT - 96, cx, cy)
    if not clockwise:  # 左回りは左右を反転する（コーナーの順番はそのまま）
        points = mirror_x(points, cx)

    goal_x, goal_y = points[0]
    perimeter_px = polyline_length(points)
    start_x, start_y = point_before_goal(points, (distance_m or 0) / spec.lap_m * perimeter_px)

    # 進行方向の矢印（向正面の真ん中に置く）
    bx0, by0 = points[outline.back_start]
    bx1, by1 = points[outline.back_start + 1]
    mid_x, mid_y = (bx0 + bx1) / 2, (by0 + by1) / 2
    tip = 1 if bx1 > bx0 else -1
    arrow = (
        f"{mid_x - tip * 7:.1f} {mid_y - 9:.1f} {mid_x + tip * 7:.1f} {mid_y:.1f} "
        f"{mid_x - tip * 7:.1f} {mid_y + 9:.1f}"
    )

    # ラベルが図からはみ出さないよう、端では寄せ方を変える
    finish_anchor = "start" if clockwise else "end"
    finish_label_x = goal_x + (6 if clockwise else -6)
    start_anchor = "middle"
    # 下側（ホームストレッチ側）のスタートは、ラベルを下に出す
    # （上に出すと中央のタイトル・注記と重なるため）
    start_label_x, start_label_y = start_x, (start_y + 22 if start_y > cy else start_y - 12)
    if start_x < 45:
        start_anchor, start_label_x, start_label_y = "start", start_x + 8, start_y + 4
    elif start_x > WIDTH - 45:
        start_anchor, start_label_x, start_label_y = "end", start_x - 8, start_y + 4

    uphill = "ゴール前に上り坂" if venue_code in UPHILL_FINISH_VENUES else "ゴール前は平坦"
    home = points[outline.home_start:]

    return f"""
<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{title} のコース図" class="course-svg">
  <path d="{_path_d(points)} Z" fill="none" stroke="{color}" stroke-width="13" stroke-linejoin="round" stroke-linecap="round" opacity="0.30"/>
  <path d="{_path_d(home)}" fill="none" stroke="{color}" stroke-width="13" stroke-linecap="round"/>
  <polygon points="{arrow}" fill="{color}"/>
  <line x1="{goal_x:.1f}" y1="{goal_y - 15:.1f}" x2="{goal_x:.1f}" y2="{goal_y + 15:.1f}" stroke="#d93a3a" stroke-width="3"/>
  <text x="{finish_label_x:.1f}" y="{goal_y + 28:.1f}" class="cm-label" text-anchor="{finish_anchor}">ゴール</text>
  <circle cx="{start_x:.1f}" cy="{start_y:.1f}" r="6" fill="#1b1b1b"/>
  <text x="{start_label_x:.1f}" y="{start_label_y:.1f}" class="cm-label" text-anchor="{start_anchor}">スタート</text>
  <text x="{cx}" y="{cy + 4}" class="cm-title" text-anchor="middle">{title}</text>
  <text x="{cx}" y="{cy + 22}" class="cm-note" text-anchor="middle">{'右回り' if clockwise else '左回り'} ／ {uphill}</text>
  <text x="{cx}" y="{HEIGHT - 10}" class="cm-note" text-anchor="middle">{caption}</text>
</svg>"""


# コーナーの「真ん中あたり」を表す点列上の位置（build_outline の並びに対応）。
# 0=ゴール / 1〜24=1角 / 25〜48=2角 / 49=向正面の終わり / 50〜73=3角 / 74〜97=4角 / 98=ゴール
_CORNER_POINT_INDEX = {
    1: POINTS_PER_CORNER // 2,
    2: POINTS_PER_CORNER + POINTS_PER_CORNER // 2,
    3: 2 * POINTS_PER_CORNER + 1 + POINTS_PER_CORNER // 2,
    4: 3 * POINTS_PER_CORNER + 1 + POINTS_PER_CORNER // 2,
}


def corner_distances(
    venue_code: str,
    surface: str | None,
    distance_m: int | None,
    course_detail: str | None,
    n_corners: int,
) -> dict[int, float]:
    """通過したコーナーごとの「スタートからの距離(m)」を返す。

    n_corners は結果ページの通過順の個数（2なら3・4角、4なら1〜4角）。
    netkeibaの通過順は**後ろのコーナーから順に**埋まるので、その個数ぶんだけ
    4角→3角→2角→1角の順に割り当てる。

    位置はコース図と同じ輪郭（build_outline）から逆算した**近似**で、
    数十m程度のずれはありうる。レース距離の外に出るコーナーは返さない。
    """
    if not surface or not distance_m or n_corners <= 0:
        return {}
    selected = select_course(venue_code, surface, distance_m, course_detail)
    if selected is None:
        return {}
    loop, spec = selected
    if spec.is_straight_course:
        return {}

    points = build_outline(spec, shape_for(venue_code, loop)).points
    cumulative = [0.0]
    for i in range(1, len(points)):
        cumulative.append(cumulative[-1] + math.dist(points[i - 1], points[i]))
    scale = spec.lap_m / cumulative[-1]
    # ゴールを0とした、進行方向に測った位置（m）
    forward = [value * scale for value in cumulative]
    start = (spec.lap_m - (distance_m % spec.lap_m)) % spec.lap_m

    result: dict[int, float] = {}
    for corner in [4, 3, 2, 1][:n_corners]:
        from_start = (forward[_CORNER_POINT_INDEX[corner]] - start) % spec.lap_m
        if 0 < from_start < distance_m:
            result[corner] = from_start
    return result
