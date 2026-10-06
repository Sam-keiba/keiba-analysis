"""レース見出しの下のラップ図（race_chart.py）。"""

import pytest

from keiba_analysis.racing.race_chart import (
    AVERAGE_COLOR,
    PROJECTED_COLOR,
    build_race_lap_spec,
    build_rows,
)
from keiba_analysis.racing.race_forecast import average_laps, project_laps
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
    assert average_layer["mark"]["strokeDash"] == [4, 4]        # 平均は破線（点なし）
    assert "point" not in average_layer["mark"]
    assert "strokeDash" not in projected_layer["mark"]          # 想定は実線（点あり）
    assert projected_layer["mark"]["point"]
    # 色は資料どおり（平均＝灰／想定＝緑。馬場によらない）
    scale = projected_layer["encoding"]["color"]["scale"]
    assert scale["range"] == [AVERAGE_COLOR, PROJECTED_COLOR]
    assert average_layer["encoding"]["color"]["datum"] != projected_layer["encoding"]["color"]["datum"]
    assert projected_layer["encoding"]["y"]["field"] == "projected"


def test_axis_is_reversed_like_the_other_lap_charts():
    spec = build_race_lap_spec(AVERAGE, PROJECTED, "dirt")
    y = spec["layer"][2]["encoding"]["y"]
    assert y["scale"]["reverse"] is True              # 上へ行くほど速い
    assert spec["layer"][2]["encoding"]["color"]["scale"]["range"][1] == PROJECTED_COLOR
    assert spec["layer"][1]["encoding"]["x"]["field"] == "distance_m"


@pytest.mark.parametrize("compact", [True, False])
def test_chart_leaves_the_y_title_and_legend_to_the_page(compact):
    """縦軸の見出しと凡例は画面側に出すので、グラフには付けない（PC・スマホとも。資料どおり）。"""
    spec = build_race_lap_spec(AVERAGE, PROJECTED, "turf", compact=compact)
    assert all(layer["encoding"]["y"].get("title") is None for layer in spec["layer"])
    assert all(layer["encoding"].get("color", {}).get("legend") is None for layer in spec["layer"])
