"""コース模式図（SVG）の生成。"""

import math

import pytest

from keiba_analysis.racing.course_data import COURSES
from keiba_analysis.racing.course_map import render_course_svg, select_course


def test_selects_outer_course_from_detail():
    loop, spec = select_course("06", "turf", 2200, "外 C")
    assert loop == "outer"
    assert spec.lap_m == 1839.7


def test_selects_inner_course_from_detail():
    loop, spec = select_course("09", "turf", 2000, "内 B")
    assert loop == "inner"
    assert spec.lap_m == 1689.0


def test_selects_course_from_distance_when_detail_missing():
    """コース表記が無くても、その距離が行われる方のコースを選ぶ。"""
    loop, _ = select_course("09", "turf", 1800, None)  # 阪神芝1800mは外回り
    assert loop == "outer"
    loop, _ = select_course("08", "turf", 1100, None)  # 京都芝1100mは内回り
    assert loop == "inner"


def test_nakayama_turf_2200():
    svg = render_course_svg("06", "中山", "turf", 2200, "right", "外 C")
    assert svg is not None
    assert "中山 芝外回り 2200m" in svg
    assert "1周1,839.7m ／ 直線310.0m ／ 高低差5.3m" in svg
    assert "右回り ／ ゴール前に上り坂" in svg
    assert "スタート" in svg and "ゴール" in svg


def test_dirt_course_uses_dirt_data_and_color():
    svg = render_course_svg("06", "中山", "dirt", 1800, "right", None)
    assert "中山 ダート 1800m" in svg
    assert "1周1,493.0m" in svg
    assert "#b07d4b" in svg  # ダートの色


def test_tokyo_is_left_handed_and_flat_or_uphill():
    svg = render_course_svg("05", "東京", "turf", 2400, "left", None)
    assert "左回り" in svg
    assert "直線525.9m" in svg


def test_kokura_is_flat_finish():
    svg = render_course_svg("10", "小倉", "turf", 2000, "right", None)
    assert "ゴール前は平坦" in svg


def test_niigata_straight_course():
    svg = render_course_svg("04", "新潟", "turf", 1000, "straight", None)
    assert "新潟 芝直線 1000m" in svg
    assert "コーナーの無い直線だけのコース" in svg


def test_jump_course_has_no_diagram():
    assert render_course_svg("06", "中山", "jump", 2880, "right", None) is None
    assert render_course_svg("06", "中山", None, 2000, "right", None) is None


def test_start_marker_moves_with_distance():
    """距離が違えばスタート位置も変わる（ゴールから逆算しているか）。"""
    def start_point(distance: int) -> tuple[str, str]:
        svg = render_course_svg("06", "中山", "turf", distance, "right", "外")
        import re
        m = re.search(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg)
        return m.group(1), m.group(2)

    assert start_point(1200) != start_point(2200)


def test_start_of_one_lap_race_is_near_finish():
    """一周と同じ距離ならスタートはゴール地点とほぼ同じになる。"""
    import re

    spec = COURSES[("06", "turf", "outer")]
    svg = render_course_svg("06", "中山", "turf", int(spec.lap_m), "right", "外")
    circle = re.search(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg)
    finish = re.search(r'<line x1="([\d.]+)" y1="[\d.]+" x2="\1"', svg)
    assert finish is not None
    assert math.isclose(float(circle.group(1)), float(finish.group(1)), abs_tol=1.5)


@pytest.mark.parametrize("venue_code", sorted({v for v, _, _ in COURSES}))
def test_every_venue_has_a_diagram(venue_code):
    """データを入れた10場すべてで、芝・ダートとも図が描けること。"""
    for surface in ("turf", "dirt"):
        specs = [s for (v, sf, _), s in COURSES.items() if v == venue_code and sf == surface]
        if not specs:
            continue
        distance = specs[0].distances[0]
        svg = render_course_svg(venue_code, "テスト場", surface, distance, None, None)
        assert svg is not None and "<svg" in svg


# --- コースの形（競馬場ごとに違う） -------------------------------------------


@pytest.mark.parametrize("key", sorted(k for k in COURSES if not COURSES[k].is_straight_course))
def test_outline_keeps_the_official_straight_ratio(key):
    """描いた輪郭の「直線/一周」が、JRA公式の数値どおりになっていること。"""
    import math

    from keiba_analysis.racing.course_data import shape_for
    from keiba_analysis.racing.course_map import build_outline, polyline_length

    venue_code, _surface, loop = key
    spec = COURSES[key]
    outline = build_outline(spec, shape_for(venue_code, loop))
    perimeter = polyline_length(outline.points)
    home = math.dist(outline.points[outline.home_start], outline.points[outline.home_start + 1])
    assert home / perimeter == pytest.approx(spec.straight_m / spec.lap_m, rel=0.02)


def test_outline_is_closed():
    from keiba_analysis.racing.course_data import shape_for
    from keiba_analysis.racing.course_map import build_outline

    outline = build_outline(COURSES[("06", "turf", "outer")], shape_for("06", "outer"))
    assert outline.points[0] == outline.points[-1]     # ゴールへ戻って閉じている
    assert outline.home_start == len(outline.points) - 2


def _aspect(venue_code: str, surface: str, loop: str) -> float:
    """輪郭の縦横比（小さいほど平たい）。"""
    from keiba_analysis.racing.course_data import shape_for
    from keiba_analysis.racing.course_map import build_outline

    points = build_outline(COURSES[(venue_code, surface, loop)], shape_for(venue_code, loop)).points
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (max(ys) - min(ys)) / (max(xs) - min(xs))


def test_shapes_differ_between_venues():
    """直線の長い競馬場ほど平たく、小回りの競馬場ほど丸くなる。"""
    niigata = _aspect("04", "turf", "outer")   # 直線658.7m
    tokyo = _aspect("05", "turf", "")          # 直線525.9m
    nakayama = _aspect("06", "turf", "inner")  # 直線310.0m
    assert niigata < tokyo < nakayama


def test_outer_and_inner_loops_have_different_shapes():
    """同じ競馬場でも内回りと外回りで形が違う（中山の外回りは2〜3角が膨らむ）。"""
    from keiba_analysis.racing.course_data import shape_for

    assert shape_for("06", "inner").corner_bulge != shape_for("06", "outer").corner_bulge
    inner = render_course_svg("06", "中山", "turf", 2000, "right", "内")
    outer = render_course_svg("06", "中山", "turf", 2200, "right", "外")
    assert inner.split('<path d="')[1] != outer.split('<path d="')[1]


def test_dirt_reuses_the_venue_shape():
    from keiba_analysis.racing.course_data import shape_for

    assert shape_for("06", "") is shape_for("06", "inner")   # ダートは芝の内回りと同じ形


# --- コーナー位置（個別推定ラップで使う） -------------------------------------


def test_corner_distances_match_the_number_of_passings():
    """通過順の個数ぶんだけ、後ろのコーナーから位置を返す。"""
    from keiba_analysis.racing.course_map import corner_distances

    four = corner_distances("06", "dirt", 1800, None, 4)     # 中山ダ1800は4角すべて通る
    assert sorted(four) == [1, 2, 3, 4]
    assert all(0 < d < 1800 for d in four.values())
    assert four[1] < four[2] < four[3] < four[4]             # 進む順に遠くなる

    two = corner_distances("06", "dirt", 1200, None, 2)      # 中山ダ1200は3角・4角だけ
    assert sorted(two) == [3, 4]
    assert two[4] > two[3] > 0


def test_corner_distances_are_near_the_home_straight_for_the_last_corner():
    """4角はホームストレッチの入口なので、残り距離が直線距離に近くなる。"""
    from keiba_analysis.racing.course_data import COURSES
    from keiba_analysis.racing.course_map import corner_distances

    spec = COURSES[("06", "turf", "outer")]
    corners = corner_distances("06", "turf", 2200, "外", 4)
    remaining = 2200 - corners[4]
    assert spec.straight_m <= remaining <= spec.straight_m + 250


def test_no_corners_without_a_track():
    from keiba_analysis.racing.course_map import corner_distances

    assert corner_distances("04", "turf", 1000, None, 1) == {}   # 新潟芝1000mは直線競走
    assert corner_distances("06", "jump", 2880, None, 4) == {}   # 障害はコースデータなし
    assert corner_distances("06", "turf", 2000, None, 0) == {}
