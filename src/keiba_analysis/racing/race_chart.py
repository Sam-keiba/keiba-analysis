"""レース見出しの下に出す「同条件の平均ラップ＋本日の想定ラップ」のVega-Lite定義。

計算は race_forecast.py。作りは他のグラフと同じで、**`$schema` は書かない**
（Altairを使わず素の定義を渡し、Streamlit同梱のVega-Liteの版に合わせる）。

- **破線＝同条件の平均ラップ**（薄い帯は区間ごとの±1標準偏差）
- **実線＝本日の想定ラップ**（メンバーと想定クッション値で補正したもの）
縦軸は他のラップグラフと同じく**上へ行くほど速い**向きにする。
"""

from __future__ import annotations

from keiba_analysis.racing.race_forecast import AverageLaps

AVERAGE_KIND = "同条件の平均"
PROJECTED_KIND = "本日の想定"

X_TITLE = "スタートからの距離(m)"
Y_TITLE = "区間ラップ（秒）"
CHART_HEIGHT = 260
LINE_WIDTH = 3              # 想定（実線）。平均は 2（docs/design_handoff のラップ想定）
AVERAGE_WIDTH = 2
PROJECTED_COLOR = "#1a7f4b"  # 想定はアクセントの緑（馬場の色にはしない。資料どおり）
AVERAGE_COLOR = "#6b6865"    # 平均は灰の破線
BAND_COLOR = "#201f1d"
BAND_OPACITY = 0.07


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


def _axes(field: str, compact: bool = False) -> dict:
    """軸。縦軸の見出しは画面側（グラフの上の小さな文字）に出すので、軸には付けない（PC・スマホとも）。"""
    return {
        "x": {"field": "distance_m", "type": "quantitative", "title": X_TITLE, "scale": {"nice": False}},
        "y": {
            "field": field,
            "type": "quantitative",
            "title": None,
            # 他のラップグラフと同じく、上へ行くほど速い
            "scale": {"zero": False, "nice": True, "reverse": True},
        },
    }


def projected_color(surface: str | None = None) -> str:
    """想定ラップ（実線）の色。凡例は画面側のHTMLで描くので、同じ色を使えるように出す。

    資料どおり馬場によらず緑（`surface` は前の呼び出し方のために受け取るだけ）。
    """
    return PROJECTED_COLOR


def build_race_lap_spec(
    average: AverageLaps, projected: list[float], surface: str | None = None, height: int = CHART_HEIGHT,
    compact: bool = False,
) -> dict:
    """平均（点線＋ばらつきの帯）と想定（実線）を重ねた定義。

    2本が重なっても見分けられるよう、平均は灰の破線（点なし）、想定は緑の実線（点あり）にする。
    凡例はグラフの外（画面側のHTML）に出すので、ここでは付けない（PC・スマホとも）。
    """
    rows = build_rows(average, projected)
    color = projected_color(surface)
    tooltip = [
        {"field": "distance_m", "type": "quantitative", "title": X_TITLE},
        {"field": "average", "type": "quantitative", "title": AVERAGE_KIND, "format": ".2f"},
        {"field": "projected", "type": "quantitative", "title": PROJECTED_KIND, "format": ".2f"},
    ]
    band_layer = {
        "mark": {"type": "area", "opacity": BAND_OPACITY, "color": BAND_COLOR},
        "encoding": {
            "x": _axes("average")["x"],
            "y": _axes("low", compact)["y"],
            "y2": {"field": "high"},
        },
    }
    average_layer = {
        "mark": {"type": "line", "strokeDash": [4, 4], "strokeWidth": AVERAGE_WIDTH},
        "encoding": {
            **_axes("average", compact),
            "color": {
                "datum": AVERAGE_KIND,
                "scale": {"domain": [AVERAGE_KIND, PROJECTED_KIND], "range": [AVERAGE_COLOR, color]},
                "legend": None,
            },
            "tooltip": tooltip,
        },
    }
    projected_layer = {
        "mark": {"type": "line", "strokeWidth": LINE_WIDTH, "point": {"filled": True, "size": 30}},
        "encoding": {
            **_axes("projected", compact),
            "color": {
                "datum": PROJECTED_KIND,
                "scale": {"domain": [AVERAGE_KIND, PROJECTED_KIND], "range": [AVERAGE_COLOR, color]},
                "legend": None,
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
