"""レース見出しの下のラップ図（race_chart.py）。"""

import pytest

from keiba_analysis.racing.race_chart import (
    AVERAGE_COLOR,
    build_race_lap_spec,
    build_rows,
)
from keiba_analysis.racing.race_forecast import average_laps, project_laps
from keiba_analysis.shared.style import SURFACE_BADGE
from tests.racing.test_race_forecast import RACES

AVERAGE = average_laps(RACES)
PROJECTED = project_laps(AVERAGE, front_runners=6, field_size=12, cushion=10.0)


def test_rows_carry_the_average_band_and_projection():
    rows = build_rows(AVERAGE, PROJECTED)
    assert len(rows) == len(AVERAGE.laps)
    first = rows[0]
    assert first["distance_m"] == 200
    assert first["average"] == pytest.approx(AVERAGE.laps[0])
    assert first["projected"] == pytest.approx(PROJECTED[0])
    # ばらつきの帯は 平均±標準偏差
    assert first["low"] == pytest.approx(AVERAGE.laps[0] - AVERAGE.deviations[0])
    assert first["high"] == pytest.approx(AVERAGE.laps[0] + AVERAGE.deviations[0])


def test_spec_has_band_dotted_average_and_solid_projection():
    spec = build_race_lap_spec(AVERAGE, PROJECTED, "turf")
    assert "$schema" not in spec                      # 理由は lap_chart の冒頭と同じ
    band, average_layer, projected_layer = spec["layer"]
    assert band["mark"]["type"] == "area"             # ばらつきの帯
    assert band["encoding"]["y2"]["field"] == "high"
    assert average_layer["mark"]["strokeDash"] == [4, 3]        # 平均は点線
    assert "strokeDash" not in projected_layer["mark"]          # 想定は実線
    # 色は凡例つきで指定する（平均＝灰青／想定＝馬場の色）
    scale = projected_layer["encoding"]["color"]["scale"]
    assert scale["range"] == [AVERAGE_COLOR, SURFACE_BADGE["turf"][0]]
    assert average_layer["encoding"]["color"]["datum"] != projected_layer["encoding"]["color"]["datum"]
    assert projected_layer["encoding"]["y"]["field"] == "projected"


def test_axis_is_reversed_like_the_other_lap_charts():
    spec = build_race_lap_spec(AVERAGE, PROJECTED, "dirt")
    y = spec["layer"][2]["encoding"]["y"]
    assert y["scale"]["reverse"] is True              # 上へ行くほど速い
    assert spec["layer"][2]["encoding"]["color"]["scale"]["range"][1] == SURFACE_BADGE["dirt"][0]
    assert spec["layer"][1]["encoding"]["x"]["field"] == "distance_m"


def test_compact_chart_leaves_the_y_title_to_the_page():
    """スマホは縦軸の見出しを画面側に横書きで出すので、軸からは外す（グラフを広く使う）。"""
    spec = build_race_lap_spec(AVERAGE, PROJECTED, "turf", compact=True)
    assert all(layer["encoding"]["y"].get("title") is None for layer in spec["layer"])
    # 凡例も画面側のHTMLで描く（グラフの中に場所を取らない）
    assert all(layer["encoding"].get("color", {}).get("legend") is None for layer in spec["layer"])
    pc = build_race_lap_spec(AVERAGE, PROJECTED, "turf")
    assert all(layer["encoding"]["y"].get("title") for layer in pc["layer"])
