"""種牡馬分析のAEI推移グラフ（Vega-Lite定義）。

ほかのグラフと同じく**`$schema` は書かない**（Altairを使わず素の定義を渡し、
Streamlit同梱のVega-Liteの版に合わせる。理由は lap_chart.py の先頭に書いてある）。

- **棒＝出走頭数**（右軸）。その年に何頭走らせたか＝母数の大きさ
- **折れ線＝E・I（AEI）**（左軸）。1.00が全種牡馬の平均なので、そこに破線を引く

母数が小さい年はE・Iが跳ねるので、棒と重ねて「何頭ぶんの数字か」を同時に見せる。
"""

from __future__ import annotations

from keiba_data.sire_data import SireYear
from keiba_analysis.style import SURFACE_BADGE  # TODO(migration): style.py not yet in keiba-analysis; currently slated for keiba-app. Needs resolution.

CHART_HEIGHT = 280
AEI_COLOR = "#1f7a50"        # 折れ線（緑。RATE_HEAT_COLORSと同じ系統）
HORSES_COLOR = "#c3cdd6"     # 棒（背景に退く灰青）
FIELD_LINE_COLOR = "#9aa09a"  # 全種牡馬平均（1.00）の基準線
AEI_TITLE = "E・I（AEI）"
HORSES_TITLE = "出走頭数"
FIELD_AVERAGE = 1.0


def build_rows(rows: list[SireYear]) -> list[dict]:
    """グラフ用の行。年は文字列にする（2022.5年のような目盛りを出させないため）。"""
    return [
        {
            "year": str(r.year),
            "aei": r.ei,
            "n_horses": r.n_horses,
            "n_winners": r.n_winners,
            "win_rate": round(r.win_rate * 100, 1) if r.win_rate is not None else None,
            "rank": r.rank,
        }
        for r in rows
    ]


def build_aei_spec(rows: list[SireYear], height: int = CHART_HEIGHT) -> dict:
    """AEI推移（折れ線）＋出走頭数（棒）を重ねた定義。左右で軸を分ける。"""
    values = build_rows(rows)
    x = {"field": "year", "type": "ordinal", "title": None, "axis": {"labelAngle": 0}}
    tooltip = [
        {"field": "year", "type": "ordinal", "title": "年度"},
        {"field": "aei", "type": "quantitative", "title": AEI_TITLE, "format": ".2f"},
        {"field": "n_horses", "type": "quantitative", "title": HORSES_TITLE},
        {"field": "n_winners", "type": "quantitative", "title": "勝馬頭数"},
        {"field": "win_rate", "type": "quantitative", "title": "勝ち上がり率(%)", "format": ".1f"},
        {"field": "rank", "type": "quantitative", "title": "リーディング順位"},
    ]
    bars = {
        "mark": {"type": "bar", "color": HORSES_COLOR, "size": 34},
        "encoding": {
            "x": x,
            "y": {
                "field": "n_horses", "type": "quantitative", "title": HORSES_TITLE,
                "axis": {"titleColor": "#7b8590", "grid": False},
            },
            "tooltip": tooltip,
        },
    }
    line = {
        "mark": {"type": "line", "color": AEI_COLOR, "strokeWidth": 2.5,
                 "point": {"filled": True, "size": 60, "color": AEI_COLOR}},
        "encoding": {
            "x": x,
            "y": {
                "field": "aei", "type": "quantitative", "title": AEI_TITLE,
                "scale": {"zero": True, "nice": True},
                "axis": {"titleColor": AEI_COLOR},
            },
            "tooltip": tooltip,
        },
    }
    labels = {
        "mark": {"type": "text", "dy": -14, "fontSize": 11, "color": AEI_COLOR, "fontWeight": "bold"},
        "encoding": {
            "x": x,
            "y": {"field": "aei", "type": "quantitative"},
            "text": {"field": "aei", "type": "quantitative", "format": ".2f"},
        },
    }
    # 全種牡馬平均（1.00）の目印。E・Iと同じ軸に置く
    field_line = {
        "data": {"values": [{"aei": FIELD_AVERAGE}]},
        "mark": {"type": "rule", "color": FIELD_LINE_COLOR, "strokeDash": [4, 3], "strokeWidth": 1.5},
        "encoding": {"y": {"field": "aei", "type": "quantitative"}},
    }
    return {
        "height": height,
        "autosize": {"type": "fit-x", "contains": "padding"},
        "data": {"values": values},
        # 棒（右軸・頭数）と折れ線（左軸・E・I）は単位が違うので、y軸を分ける
        "layer": [bars, field_line, line, labels],
        "resolve": {"scale": {"y": "independent"}},
    }


# --- 産駒の内訳（距離・性別・年齢・母の父・コース） ---------------------------------

BAR_HEIGHT = 30          # 1区分ぶんの高さ
THIN_OPACITY = 0.4       # 走数が足りない区分の薄さ
WIN_COLOR = "#c0201a"    # 勝率（複勝率の帯の中に重ねる）


def tally_rows(tallies: list, rate: str = "top3_rate") -> list[dict]:
    """`sire_runs.Tally` をグラフ用の行にする。`rate` は `top3_rate` か `win_rate`。"""
    return [
        {
            "label": t.label,
            "rate": round(getattr(t, rate) * 100, 1) if getattr(t, rate) is not None else None,
            "win_rate": round(t.win_rate * 100, 1) if t.win_rate is not None else None,
            "starts": t.starts,
            "wins": t.wins,
            "top3": t.top3,
            "horses": t.horses,
            "thin": t.is_thin,
            "note": f"{t.top3}/{t.starts}",
        }
        for t in tallies
    ]


def build_rate_bar_spec(
    tallies: list, title: str = "複勝率（％）", rate: str = "top3_rate", height: int | None = None,
) -> dict:
    """区分ごとの率を横棒で出す（距離帯・性別・年齢・母の父・競馬場で使い回す）。

    棒の右に「3着内/出走」を添え、**走数が足りない区分は薄く**描く
    （`stats_chart.py` のペース別グラフと同じ考え方）。
    """
    rows = tally_rows(tallies, rate)
    order = [r["label"] for r in rows]
    y = {"field": "label", "type": "ordinal", "title": None, "sort": order,
         "axis": {"labelFontSize": 12, "domain": False, "ticks": False}}
    tooltip = [
        {"field": "label", "type": "nominal", "title": "区分"},
        {"field": "horses", "type": "quantitative", "title": "頭数"},
        {"field": "starts", "type": "quantitative", "title": "出走"},
        {"field": "wins", "type": "quantitative", "title": "1着"},
        {"field": "top3", "type": "quantitative", "title": "3着内"},
        {"field": "rate", "type": "quantitative", "title": title, "format": ".1f"},
    ]
    opacity = {"condition": {"test": "datum.thin", "value": THIN_OPACITY}, "value": 1}
    bars = {
        "mark": {"type": "bar", "color": AEI_COLOR, "height": {"band": 0.7}},
        "encoding": {
            "y": y,
            "x": {"field": "rate", "type": "quantitative", "title": title,
                  "scale": {"domainMin": 0}},
            "opacity": opacity,
            "tooltip": tooltip,
        },
    }
    labels = {
        "mark": {"type": "text", "align": "left", "dx": 5, "fontSize": 11, "color": "#5c645c"},
        "encoding": {
            "y": y,
            "x": {"field": "rate", "type": "quantitative"},
            "text": {"field": "note", "type": "nominal"},
            "opacity": opacity,
        },
    }
    return {
        "height": height or {"step": BAR_HEIGHT},
        "autosize": {"type": "fit-x", "contains": "padding"},
        "data": {"values": rows},
        "layer": [bars, labels],
    }


def build_debut_month_spec(months: dict[int, int], height: int = 190) -> dict:
    """新馬戦に出た月ごとの頭数。**6月から翌5月**の順に並べる（2歳戦の始まりが6月）。"""
    order = [(6 + i - 1) % 12 + 1 for i in range(12)]
    rows = [{"month": f"{m}月", "horses": months.get(m, 0)} for m in order]
    return {
        "height": height,
        "autosize": {"type": "fit-x", "contains": "padding"},
        "data": {"values": rows},
        "mark": {"type": "bar", "color": AEI_COLOR},
        "encoding": {
            "x": {"field": "month", "type": "ordinal", "title": "デビューした月",
                  "sort": [r["month"] for r in rows], "axis": {"labelAngle": 0}},
            "y": {"field": "horses", "type": "quantitative", "title": "頭数"},
            "tooltip": [
                {"field": "month", "type": "nominal", "title": "月"},
                {"field": "horses", "type": "quantitative", "title": "頭数"},
            ],
        },
    }


# --- 芝・ダート比率（100%積み上げの横棒） ---------------------------------------------

SURFACE_ORDER: tuple[tuple[str, str], ...] = (
    ("turf_starts", "芝"), ("dirt_starts", "ダート"), ("jump_starts", "障害"),
)
SHARE_BAR_HEIGHT = 26      # 1本ぶんの高さ
SHARE_LABEL_MIN = 0.15     # この割合以上の区分にだけ帯の中へ文字を出す


def surface_share_rows(rows: list[dict], label_key: str = "label") -> list[dict]:
    """`club_summary` の行から、積み上げ用の「1行1区分」に開く。

    **障害は1走も無ければ出さない**（ほとんどのクラブに障害の出走は無く、
    凡例だけ増えて読みにくくなるため）。
    """
    has_jump = any(row.get("jump_starts") for row in rows)
    kinds = SURFACE_ORDER if has_jump else SURFACE_ORDER[:2]
    out: list[dict] = []
    for row in rows:
        total = sum(row.get(key) or 0 for key, _label in kinds)
        if not total:
            continue
        for index, (key, label) in enumerate(kinds):
            starts = row.get(key) or 0
            share = starts / total
            out.append({
                "club": row[label_key],
                "surface": label,
                # 積み上げの順（芝→ダート→障害）。Vega-Lite の order は数値で指定する
                "surface_index": index,
                "share": round(share * 100, 1),
                "starts": starts,
                "horses": row.get("horses"),
                # 狭い帯でも文字がはみ出さないよう、一定以上の区分だけラベルを出す
                "note": f"{label} {share:.0%}" if share >= SHARE_LABEL_MIN else "",
            })
    return out


def build_surface_share_spec(rows: list[dict], label_key: str = "label",
                             height: int | None = None) -> dict:
    """芝・ダート（・障害）の出走比率を、1行1本の100%積み上げ横棒で出す。

    並びは**芝の比率が高い順**。グラデーションになって、芝寄りのクラブと
    ダート寄りのクラブがひと目で分かる。色は競馬新聞と同じ `style.SURFACE_BADGE`。
    作りは `stats_chart.build_style_spec`（脚質の100%積み上げ）と同じ。
    """
    values = surface_share_rows(rows, label_key)
    if not values:
        return {"data": {"values": []}, "mark": "bar", "height": 1}
    order = [label for _key, label in SURFACE_ORDER
             if any(v["surface"] == label for v in values)]
    # 芝の割合が高い順に並べる（芝が無い行は最後）
    turf_share = {v["club"]: v["share"] for v in values if v["surface"] == "芝"}
    clubs = sorted({v["club"] for v in values}, key=lambda c: -turf_share.get(c, -1))

    y = {"field": "club", "type": "ordinal", "title": None, "sort": clubs,
         "axis": {"labelFontSize": 12, "labelLimit": 220, "domain": False, "ticks": False}}
    tooltip = [
        {"field": "club", "type": "nominal", "title": "クラブ"},
        {"field": "surface", "type": "nominal", "title": "馬場"},
        {"field": "share", "type": "quantitative", "title": "割合（%）", "format": ".1f"},
        {"field": "starts", "type": "quantitative", "title": "出走"},
        {"field": "horses", "type": "quantitative", "title": "頭数"},
    ]
    encoding = {
        "y": y,
        "x": {"field": "share", "type": "quantitative", "title": "出走の割合（%）",
              "stack": "zero", "scale": {"domain": [0, 100], "nice": False}},
        "order": {"field": "surface_index", "type": "quantitative"},
    }
    return {
        "height": height or {"step": SHARE_BAR_HEIGHT},
        "autosize": {"type": "fit-x", "contains": "padding"},
        "data": {"values": values},
        "layer": [
            {
                "mark": {"type": "bar"},
                "encoding": {
                    **encoding,
                    "color": {
                        "field": "surface", "type": "nominal", "title": "馬場",
                        "sort": order,
                        "scale": {"domain": order,
                                  "range": [SURFACE_BADGE[k][0] for k, label in
                                            (("turf", "芝"), ("dirt", "ダート"), ("jump", "障害"))
                                            if label in order]},
                        "legend": {"orient": "bottom", "direction": "horizontal",
                                   "labelFontSize": 11, "titleFontSize": 11,
                                   "symbolType": "square", "symbolSize": 80},
                    },
                    "tooltip": tooltip,
                },
            },
            {
                "mark": {"type": "text", "fontSize": 10, "color": "#ffffff", "fontWeight": "bold"},
                "encoding": {**encoding, "text": {"field": "note", "type": "nominal"}},
            },
        ],
    }
