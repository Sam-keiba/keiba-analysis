"""傾向グラフ（ペース別・クッション値×馬場状態・脚質の割合）のVega-Lite定義。

集計は horse_stats.py、色は style.py のものを使い回す（画面全体で配色をそろえるため）。
ラップ推移グラフ（lap_chart.py）と同じく **`$schema` は書かない**
（Altairを使わず素の定義を渡すことで、Streamlit同梱のVega-Liteの版に合わせる）。

- ペース別 … **横棒で複勝率**。棒の右に「3着内3/7」を添える
- クッション値×馬場状態 … **マス目（ヒートマップ）**。色の濃さが複勝率で、
  マスの中の数字は「3着内/出走」。右端と下に合計の行・列を付ける
- 脚質 … **100%積み上げの横棒**。「普段どの脚質で走るか」がひと目で分かる形

出走数が少ない区分（horse_stats.MIN_SAMPLE 未満）は薄く描き、ラベルに出走数を出す。
"""

from __future__ import annotations

from keiba_analysis.racing.horse_stats import (
    hardness_labels,
    GOING_LABELS,
    MIN_SAMPLE,
    Bucket,
    Grid,
    style_shares,
)
from keiba_analysis.shared.style import (
    PACE_COLORS,
    RATE_HEAT_COLORS,
    RUNNING_STYLE_COLORS,
    TOTAL_CELL_COLOR,
)

RATE_TITLE = "複勝率（3着内率）"
RATE_AXIS_TITLE = "複勝率（%）"  # 3つ横並びの狭い列に収まるよう、軸だけ短くする
PACE_TITLE = "レースのペース"
CUSHION_TITLE = "クッション値"
DIRT_MOISTURE_TITLE = "含水率（ゴール前・%）"


def hardness_title(surface: str | None) -> str:
    """横軸の見出し。芝はクッション値、ダートは含水率。"""
    return DIRT_MOISTURE_TITLE if surface == "dirt" else CUSHION_TITLE
GOING_TITLE = "馬場状態"
STYLE_TITLE = "脚質"

BAR_HEIGHT = 34  # 1区分ぶんの高さ
DIM_OPACITY = 0.45  # 出走数が少ない区分の薄さ

# --- ヒートマップ -----------------------------------------------------------------
TOTAL_LABEL = "計"
CELL_HEIGHT = 30  # マス1つぶんの高さ
NO_RUN = "—"
# マスの中の文字の色。濃いマスは白抜き、走っていないマスは薄い灰色にする
INK_ON_DARK = "#ffffff"
INK_ON_LIGHT = "#1b1b1b"
INK_EMPTY = "#b3b8b3"
WHITE_TEXT_FROM = 50.0  # この複勝率（%）以上のマスは白抜きにする

# ペースの表示名 -> 色（style.PACE_COLORS は H/M/S のキー）
PACE_BAR_COLORS = {"ハイ": PACE_COLORS["H"], "ミドル": PACE_COLORS["M"], "スロー": PACE_COLORS["S"]}


def bucket_rows(buckets: list[Bucket]) -> list[dict]:
    """棒グラフ用の行。出走が無い区分も残す（走っていないことが分かるように）。"""
    rows = []
    for bucket in buckets:
        rows.append({
            "label": bucket.label,
            "rate": round(bucket.rate * 100, 1),
            "starts": bucket.starts,
            "top3": bucket.top3,
            "wins": bucket.wins,
            "average_finish": bucket.average_finish,
            "note": f"{bucket.top3}/{bucket.starts}" if bucket.starts else "出走なし",
            "opacity": 1.0 if bucket.enough else DIM_OPACITY,
        })
    return rows


def _rate_spec(rows: list[dict], order: list[str], colors: dict[str, str], axis_title: str) -> dict:
    """複勝率の横棒グラフ（ペース別・クッション値別で共通）。"""
    encoding = {
        "y": {
            "field": "label",
            "type": "ordinal",
            "title": axis_title,
            "sort": order,
            "axis": {"labelFontSize": 11, "labelPadding": 5, "titleFontSize": 11},
        },
        "x": {
            "field": "rate",
            "type": "quantitative",
            "title": RATE_AXIS_TITLE,
            "scale": {"domain": [0, 100], "nice": False},
        },
    }
    return {
        "height": {"step": BAR_HEIGHT},
        "autosize": {"type": "fit-x", "contains": "padding"},
        "padding": {"left": 5, "top": 5, "right": 44, "bottom": 5},
        "layer": [
            {
                "data": {"values": rows},
                "mark": {"type": "bar", "cornerRadiusEnd": 3, "height": {"band": 0.7}},
                "encoding": {
                    **encoding,
                    "color": {
                        "field": "label",
                        "type": "nominal",
                        "scale": {"domain": order, "range": [colors[name] for name in order]},
                        "legend": None,
                    },
                    # 出走数が少ない区分は薄く描く（材料が足りないことを示す）
                    "opacity": {"field": "opacity", "type": "quantitative", "scale": None},
                    "tooltip": [
                        {"field": "label", "type": "nominal", "title": axis_title},
                        {"field": "starts", "type": "quantitative", "title": "出走"},
                        {"field": "wins", "type": "quantitative", "title": "1着"},
                        {"field": "top3", "type": "quantitative", "title": "3着内"},
                        {"field": "rate", "type": "quantitative", "title": RATE_TITLE, "format": ".1f"},
                        {"field": "average_finish", "type": "quantitative", "title": "平均着順"},
                    ],
                },
            },
            {
                "data": {"values": rows},
                "mark": {"type": "text", "align": "left", "dx": 5, "fontSize": 10, "fontWeight": "bold"},
                "encoding": {**encoding, "text": {"field": "note", "type": "nominal"}},
            },
        ],
    }


def build_pace_spec(buckets: list[Bucket]) -> dict:
    """ペース別の複勝率。"""
    order = [b.label for b in buckets]
    return _rate_spec(bucket_rows(buckets), order, PACE_BAR_COLORS, PACE_TITLE)


def _cell_row(going: str, cushion: str, bucket: Bucket) -> dict:
    """マス1つぶんの行。走っていないマスは色を塗らず「—」にする。"""
    rate = round(bucket.rate * 100, 1)
    if not bucket.starts:
        ink = INK_EMPTY
    elif rate >= WHITE_TEXT_FROM:
        ink = INK_ON_DARK
    else:
        ink = INK_ON_LIGHT
    return {
        "going": going,
        "cushion": cushion,
        "rate": rate,
        "starts": bucket.starts,
        "wins": bucket.wins,
        "top3": bucket.top3,
        "average_finish": bucket.average_finish,
        "note": f"{bucket.top3}/{bucket.starts}" if bucket.starts else NO_RUN,
        # 走っていないマスは白く抜き、出走の少ないマスは薄く描く
        "opacity": 0.0 if not bucket.starts else (1.0 if bucket.enough else DIM_OPACITY),
        "ink": ink,
    }


def cell_rows(grid: Grid) -> list[dict]:
    """12マスぶんの行（走っていないマスも残す）。"""
    return [
        _cell_row(going, hardness, grid.cells[(going, hardness)])
        for going in GOING_LABELS
        for hardness in hardness_labels(grid.surface)
    ]


def total_rows(grid: Grid) -> list[dict]:
    """合計の行・列（右端の馬場状態ごとの計と、下の硬さの区分ごとの計）。

    右下の角（全部の計）は出さない。行の計と列の計のどちらとも読めてしまい、
    マス目の意味がぼやけるため。
    """
    rows = [
        {**_cell_row(going, TOTAL_LABEL, grid.by_going[going]), "is_total": True}
        for going in GOING_LABELS
    ]
    rows += [
        {**_cell_row(TOTAL_LABEL, hardness, grid.by_hardness[hardness]), "is_total": True}
        for hardness in hardness_labels(grid.surface)
    ]
    # 合計は複勝率で塗らないので、薄くもしない（下地は灰色一色）
    for row in rows:
        row["opacity"] = 1.0
        row["ink"] = INK_ON_LIGHT if row["starts"] else INK_EMPTY
    return rows


def build_hardness_going_spec(grid: Grid) -> dict:
    """馬場の硬さ（横）× 馬場状態（縦）の複勝率のマス目。

    横軸は**芝ならクッション値・ダートなら含水率**（`grid.surface` で決まる）。
    硬さと水分（馬場状態）は別の軸なので、片方だけで見ると
    「同じ8.5〜10.0でも良と重が混ざる」ことになる。両方を並べて見るための形。
    1頭ぶんだとマスは疎になるので、右端と下の**計**で片方の軸だけの傾向も読める。
    """
    cells, totals = cell_rows(grid), total_rows(grid)
    title = hardness_title(grid.surface)
    encoding = {
        "x": {
            "field": "cushion",
            "type": "ordinal",
            "title": title,
            "sort": [*hardness_labels(grid.surface), TOTAL_LABEL],
            # 表のように読めるよう、区分の見出しは上に置く
            "axis": {"orient": "top", "labelAngle": 0, "labelFontSize": 10,
                     "titleFontSize": 10, "domain": False, "ticks": False},
        },
        "y": {
            "field": "going",
            "type": "ordinal",
            "title": GOING_TITLE,
            "sort": [*GOING_LABELS, TOTAL_LABEL],
            "axis": {"labelFontSize": 10, "titleFontSize": 10, "labelPadding": 4,
                     "domain": False, "ticks": False},
        },
    }
    tooltip = [
        {"field": "going", "type": "nominal", "title": GOING_TITLE},
        {"field": "cushion", "type": "nominal", "title": title},
        {"field": "starts", "type": "quantitative", "title": "出走"},
        {"field": "wins", "type": "quantitative", "title": "1着"},
        {"field": "top3", "type": "quantitative", "title": "3着内"},
        {"field": "rate", "type": "quantitative", "title": RATE_TITLE, "format": ".1f"},
        {"field": "average_finish", "type": "quantitative", "title": "平均着順"},
    ]
    text_mark = {"type": "text", "fontSize": 10, "fontWeight": "bold"}
    return {
        "height": {"step": CELL_HEIGHT},
        "autosize": {"type": "fit-x", "contains": "padding"},
        "padding": {"left": 5, "top": 5, "right": 5, "bottom": 5},
        # 重ねた3つのレイヤーで色の使い方が違う（マスは複勝率で塗る／合計は一色／
        # 文字はマスごとの色をそのまま渡す）。まとめようとすると Vega-Lite が
        # 「Cannot read properties of null」で描画に失敗するので、別々に扱わせる。
        "resolve": {"scale": {"color": "independent", "opacity": "independent"}},
        "layer": [
            {   # マス目（複勝率で塗る）
                "data": {"values": cells},
                "mark": {"type": "rect", "stroke": "#ffffff", "strokeWidth": 1.5},
                "encoding": {
                    **encoding,
                    "color": {
                        "field": "rate",
                        "type": "quantitative",
                        "title": RATE_AXIS_TITLE,
                        "scale": {"domain": [0, 100], "range": list(RATE_HEAT_COLORS)},
                        "legend": {"orient": "bottom", "direction": "horizontal",
                                   "gradientLength": 96, "gradientThickness": 10,
                                   "titleFontSize": 10, "labelFontSize": 9},
                    },
                    "opacity": {"field": "opacity", "type": "quantitative", "scale": None},
                    "tooltip": tooltip,
                },
            },
            {   # 合計の行・列（複勝率では塗らない）
                "data": {"values": totals},
                "mark": {"type": "rect", "stroke": "#ffffff", "strokeWidth": 1.5,
                         "color": TOTAL_CELL_COLOR},
                "encoding": {**encoding, "tooltip": tooltip},
            },
            {   # マスの中の「3着内/出走」
                "data": {"values": [*cells, *totals]},
                "mark": text_mark,
                "encoding": {
                    **encoding,
                    "text": {"field": "note", "type": "nominal"},
                    "color": {"field": "ink", "type": "nominal", "scale": None},
                },
            },
        ],
    }


def build_style_spec(buckets: list[Bucket]) -> dict:
    """脚質の割合（100%積み上げの横棒）。"""
    shares = style_shares(buckets)
    starts = {b.label: b.starts for b in buckets}
    order = [b.label for b in buckets]
    rows = [
        {
            "style": label,
            # 積み上げの順（逃げ→先行→差し→追込）。Vega-Liteの order は数値で指定する
            "style_index": order.index(label),
            "share": round(share * 100, 1),
            "starts": starts[label],
            # 狭い列でも文字がはみ出さないよう、15%以上の区分だけラベルを出す
            "note": f"{label} {share:.0%}" if share >= 0.15 else "",
        }
        for label, share in shares
        if share > 0
    ]
    encoding = {
        "x": {
            "field": "share",
            "type": "quantitative",
            "title": "割合（%）",
            "stack": "zero",
            "scale": {"domain": [0, 100], "nice": False},
        },
        "color": {
            "field": "style",
            "type": "nominal",
            "title": STYLE_TITLE,
            "sort": order,
            "scale": {"domain": order, "range": [RUNNING_STYLE_COLORS[s] for s in order]},
            # 狭い列でも1行に収まるよう、4つ横並びの小さめの凡例にする
            "legend": {"orient": "bottom", "direction": "horizontal", "columns": 4,
                       "labelFontSize": 10, "titleFontSize": 10, "symbolType": "square",
                       "symbolSize": 70, "labelLimit": 40},
        },
        "order": {"field": "style_index", "type": "quantitative"},
    }
    return {
        "height": 64,
        "autosize": {"type": "fit-x", "contains": "padding"},
        "layer": [
            {
                "data": {"values": rows},
                "mark": {"type": "bar", "height": 38},
                "encoding": {
                    **encoding,
                    "tooltip": [
                        {"field": "style", "type": "nominal", "title": STYLE_TITLE},
                        {"field": "starts", "type": "quantitative", "title": "出走"},
                        {"field": "share", "type": "quantitative", "title": "割合（%）", "format": ".1f"},
                    ],
                },
            },
            {
                "data": {"values": rows},
                "mark": {"type": "text", "color": "#ffffff", "fontSize": 11, "fontWeight": "bold"},
                "encoding": {
                    **encoding,
                    # 積み上げた区画の**真ん中**に文字を置く（既定だと区画の端に出る）
                    "x": {**encoding["x"], "bandPosition": 0.5},
                    "color": {"value": "#ffffff"},
                    "text": {"field": "note", "type": "nominal"},
                },
            },
        ],
    }
