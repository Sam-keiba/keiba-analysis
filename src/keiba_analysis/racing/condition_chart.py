"""条件分析・馬券検証の横棒グラフのVega-Lite定義。

系列は1つだけなので色は1色（凡例なし。見出しが名前の代わり）。出走の少ない区分は薄く描く。
回収率では100%の位置に細い基準線を引く。`$schema` は書かない（他のグラフと同じ理由）。
"""

from __future__ import annotations

from keiba_analysis.owner.sire_chart import AEI_COLOR, BAR_HEIGHT, THIN_OPACITY

REFERENCE_COLOR = "#5c645c"


def build_metric_bar_spec(rows: list[dict], title: str, *, reference: float | None = None) -> dict:
    """`rows` は `label`, `value`（％）, `note`（棒の右の文字）, `thin`, `detail`（ツールチップ）を持つ行。"""
    order = [r["label"] for r in rows]
    y = {"field": "label", "type": "ordinal", "title": None, "sort": order,
         "axis": {"labelFontSize": 12, "domain": False, "ticks": False, "labelLimit": 200}}
    x = {"field": "value", "type": "quantitative", "title": title, "scale": {"domainMin": 0}}
    opacity = {"condition": {"test": "datum.thin", "value": THIN_OPACITY}, "value": 1}
    tooltip = [
        {"field": "label", "type": "nominal", "title": "区分"},
        {"field": "value", "type": "quantitative", "title": title, "format": ".1f"},
        {"field": "detail", "type": "nominal", "title": "内訳"},
    ]
    layers: list[dict] = [
        {"mark": {"type": "bar", "color": AEI_COLOR, "height": {"band": 0.7}, "cornerRadiusEnd": 4},
         "encoding": {"y": y, "x": x, "opacity": opacity, "tooltip": tooltip}},
        {"mark": {"type": "text", "align": "left", "dx": 5, "fontSize": 11, "color": REFERENCE_COLOR},
         "encoding": {"y": y, "x": {"field": "value", "type": "quantitative"},
                      "text": {"field": "note", "type": "nominal"}, "opacity": opacity}},
    ]
    if reference is not None:
        layers.append({"data": {"values": [{"reference": reference}]},
                       "mark": {"type": "rule", "color": REFERENCE_COLOR, "strokeDash": [4, 4]},
                       "encoding": {"x": {"field": "reference", "type": "quantitative"}}})
    return {
        "height": {"step": BAR_HEIGHT},
        "autosize": {"type": "fit-x", "contains": "padding"},
        "data": {"values": rows},
        "layer": layers,
    }
