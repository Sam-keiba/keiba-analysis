"""レース見出しの下に出す「同条件の平均ラップ＋本日の想定ラップ」のVega-Lite定義。

計算は race_forecast.py。作りは他のグラフと同じで、**`$schema` は書かない**
（Altairを使わず素の定義を渡し、Streamlit同梱のVega-Liteの版に合わせる）。

- **点線＝同条件の平均ラップ**（薄い帯は区間ごとの±1標準偏差）
- **実線＝本日の想定ラップ**（メンバーと想定クッション値で補正したもの）
縦軸は他のラップグラフと同じく**上へ行くほど速い**向きにする。
"""

from __future__ import annotations

from keiba_analysis.racing.race_forecast import AverageLaps
from keiba_analysis.shared.style import SURFACE_BADGE

AVERAGE_KIND = "同条件の平均"
PROJECTED_KIND = "本日の想定"

X_TITLE = "スタートからの距離(m)"
Y_TITLE = "区間ラップ（秒）"
CHART_HEIGHT = 260
LINE_WIDTH = 2.5
AVERAGE_COLOR = "#8a93a8"   # 平均は落ち着いた灰青（想定＝馬場の色と見分けられるように）
BAND_OPACITY = 0.16
LEGEND_TITLE = "ラップ"


def build_rows(average: AverageLaps, projected: list[float]) -> list[dict]:
    """グラフ用の行（区間ごとに平均・想定・ばらつきの範囲）。"""
    rows = []
    for distance, mean, deviation, projection in zip(
        average.distances, average.laps, average.deviations, projected, strict=True
    ):
        rows.append({
            "distance_m": distance,
            "average": round(mean, 2),
            "projected": round(projection, 2),
            "low": round(mean - deviation, 2),
            "high": round(mean + deviation, 2),
        })
    return rows


def _axes(field: str) -> dict:
    return {
        "x": {"field": "distance_m", "type": "quantitative", "title": X_TITLE, "scale": {"nice": False}},
        "y": {
            "field": field,
            "type": "quantitative",
            "title": Y_TITLE,
            # 他のラップグラフと同じく、上へ行くほど速い
            "scale": {"zero": False, "nice": True, "reverse": True},
        },
    }


def build_race_lap_spec(
    average: AverageLaps, projected: list[float], surface: str | None = None, height: int = CHART_HEIGHT
) -> dict:
    """平均（点線＋ばらつきの帯）と想定（実線）を重ねた定義。

    2本が重なっても見分けられるよう、平均は灰青の点線、想定は馬場の色の実線にし、
    凡例を下に出す。
    """
    rows = build_rows(average, projected)
    color = SURFACE_BADGE.get(surface or "", ("#3f9c6d", ""))[0]
    legend = {
        "orient": "bottom", "direction": "horizontal", "labelFontSize": 11,
        "titleFontSize": 11, "symbolType": "stroke", "symbolSize": 90,
    }
    tooltip = [
        {"field": "distance_m", "type": "quantitative", "title": X_TITLE},
        {"field": "average", "type": "quantitative", "title": AVERAGE_KIND, "format": ".2f"},
        {"field": "projected", "type": "quantitative", "title": PROJECTED_KIND, "format": ".2f"},
    ]
    band_layer = {
        "mark": {"type": "area", "opacity": BAND_OPACITY, "color": AVERAGE_COLOR},
        "encoding": {
            "x": _axes("average")["x"],
            "y": {**_axes("low")["y"], "title": Y_TITLE},
            "y2": {"field": "high"},
        },
    }
    average_layer = {
        "mark": {"type": "line", "strokeDash": [4, 3], "strokeWidth": LINE_WIDTH,
                 "point": {"filled": True, "size": 22}},
        "encoding": {
            **_axes("average"),
            "color": {
                "datum": AVERAGE_KIND,
                "title": LEGEND_TITLE,
                "scale": {"domain": [AVERAGE_KIND, PROJECTED_KIND], "range": [AVERAGE_COLOR, color]},
                "legend": legend,
            },
            "tooltip": tooltip,
        },
    }
    projected_layer = {
        "mark": {"type": "line", "strokeWidth": LINE_WIDTH + 0.5, "point": {"filled": True, "size": 38}},
        "encoding": {
            **_axes("projected"),
            "color": {
                "datum": PROJECTED_KIND,
                "title": LEGEND_TITLE,
                "scale": {"domain": [AVERAGE_KIND, PROJECTED_KIND], "range": [AVERAGE_COLOR, color]},
                "legend": legend,
            },
            "tooltip": tooltip,
        },
    }
    return {
        "height": height,
        "autosize": {"type": "fit-x", "contains": "padding"},
        "data": {"values": rows},
        "layer": [band_layer, average_layer, projected_layer],
    }
