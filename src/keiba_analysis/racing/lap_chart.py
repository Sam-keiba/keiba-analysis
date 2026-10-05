"""ラップ推移グラフ（Vega-Lite）。直近何走を重ねるかは画面から選べる。

見せ方は2通り（画面のラジオで切り替える）:
- **200mごと** … 区間ラップをスタートからの距離に沿って描く（`build_lap_rows` / `build_lap_spec`）
- **前後200m＋中間平均** … 前2Fと上り3Fは200mごと、中間だけ平均して1Fあたりの秒で描く
  （`build_phase_rows` / `build_phase_spec`）。距離の違うレースも同じ横軸に重なる
  （区分の作り方は lap_phases.py）

- 横軸: スタートからの距離(m)。`race_laps.distance_m`（累計距離）をそのまま使う
- 縦軸: ラップタイム（秒）
- **複勝圏内（1〜3着）の走は太く濃く**、着外は細く薄く描く（`place_label`）
- **点線** = そのレース全体のラップ
- **実線** = その馬の個別推定ラップ。算出は次のフェーズなので、いまは値が無く描かれない
  （`build_lap_rows` に `estimated_laps` を渡せばそのまま実線で出る）
- レースごとに色を変え、凡例には「日付・競馬場・コース・レース名」を出す

コースの高低差・地形の背景は描かない（ラップの折れ線だけ）。

**Altairを使わずVega-Liteの定義（dict）を直接組む理由**:
Altair 6 は Vega-Lite v6 形式の定義を出すが、Streamlit 1.64 が同梱している
フロントエンドは v5 のため、そのまま渡すとブラウザ側で描画されず空になる。
`$schema` を書かない素の定義を `st.vega_lite_chart` に渡せば、Streamlit側の
バージョンで解釈されるので、どちらのバージョンでも表示できる。
"""

from __future__ import annotations

from keiba_analysis.racing.lap_estimate import EstimatedLaps, run_key, split_floats
from keiba_analysis.racing.lap_phases import PHASE_LABELS, phase_paces
from keiba_analysis.racing.past_runs import (
    DASH,
    SURFACE_SHORT,
    cushion_label,
    format_date_short,
    format_finish,
    short_race_label,
)

RACE_LAP_KIND = "レースラップ"
ESTIMATED_LAP_KIND = "個別推定ラップ"
# コーナー通過順を使えなかった走（上がり3Fだけで出した参考値）
REFERENCE_LAP_KIND = "個別推定ラップ（参考）"
X_TITLE = "スタートからの距離(m)"
Y_TITLE = "ラップタイム（秒）"
LEGEND_TITLE = "レース（開催・コース・レース名）"
# 走ごとの線の色（競馬新聞リデザインの5色。直近走から順に使い、足りなければ繰り返す）
LINE_COLORS = ["#e2382f", "#201f1d", "#2b4a6b", "#9a9795", "#b8892b"]

# 軸は全馬・全レースで固定する（馬同士を見比べられるように）
X_DOMAIN = [0, 3200]
Y_DOMAIN = [10, 14]
CHART_HEIGHT = 560
# グラフに重ねる走数の既定値（画面のスライダーで変えられる）。
# 1走あたりレースラップと個別推定の2本を描くので、多いと線が重なって読みにくくなる。
# その場合は走数を減らすか、レースラップの表示を切ってもらう。
DEFAULT_CHART_RUNS = 5
LINE_WIDTH = 3

# 複勝圏内（1〜3着）の走は**太く濃く**、着外は細く薄く描く。
# 線を見ただけで「good だった走」が分かるようにするためで、
# レースごとの色分け・点線／実線の区別とは**別の軸**として重ねる。
IN_MONEY = "複勝圏内"
OUT_OF_MONEY = "着外"
NO_FINISH = "着順なし"
PLACE_ORDER = [IN_MONEY, OUT_OF_MONEY, NO_FINISH]
PLACE_WIDTHS = [4.0, 1.5, 1.5]        # 線の太さ
PLACE_OPACITIES = [1.0, 0.45, 0.30]   # 濃さ（点にも同じだけ効く）

# レースラップ=点線 / 個別推定ラップ=実線 / 参考値=破線
LAP_KINDS = [RACE_LAP_KIND, ESTIMATED_LAP_KIND, REFERENCE_LAP_KIND]
DASH_PATTERNS = [[4, 3], [1, 0], [7, 3]]


def race_label(run: dict) -> str:
    """凡例に出す1行。例: 08/22 札幌 芝2000 3勝 オールスターJ第2戦

    凡例は4列を1段に収めるので幅が限られる。年・回り（右/左）は入れず、
    **着順とクッション値はグラフ内（線の右端）に出す**ぶん、
    ここには**レース名（クラス入り）**を入れる。
    """
    distance = run.get("distance_m")
    course = f'{SURFACE_SHORT.get(run.get("surface") or "", "")}{distance}' if distance else ""
    parts = [
        format_date_short(run.get("race_date")),
        (run.get("venue_name") or ""),
        course,
        short_race_label(run),
    ]
    return " ".join(p for p in parts if p and p != DASH).strip()


def finish_label(run: dict) -> str:
    """グラフ内（線の右端）に出す着順。括弧に会場と馬場の硬さを添える。

    例: `1着 (札幌 ク8.1)` / ダートは `1着 (札幌 含水5.2%)` /
    材料が無ければ `1着 (札幌)`・`1着`
    """
    finish = format_finish(run)
    if finish == DASH:
        return ""
    detail = " ".join(x for x in (run.get("venue_name") or "", cushion_label(run)) if x)
    return f"{finish} ({detail})" if detail else finish


def place_label(run: dict) -> str:
    """その走が複勝圏内（1〜3着）だったか。線の太さ・濃さを決めるのに使う。

    取消・中止・除外は着順が無いので「着順なし」（着外とは分けて、いちばん薄く描く）。
    """
    position = run.get("finish_position")
    if position is None:
        return NO_FINISH
    return IN_MONEY if int(position) <= 3 else OUT_OF_MONEY


def build_lap_rows(
    runs: list[dict],
    estimated_laps: dict[tuple[str, int | None], EstimatedLaps] | None = None,
    include_race_laps: bool = True,
) -> list[dict]:
    """グラフ用の行を作る。

    estimated_laps: (race_id, 馬番) -> 個別推定ラップ（lap_estimate.estimate_runs の戻り値）。
    区間数がレースラップと違う場合は、短い方に合わせて描く。
    推定できなかった区間（None）はそのまま渡して線を切る。
    include_race_laps=False にすると、レース全体のラップ（点線）を描かず、
    個別推定ラップだけを並べる（画面のチェックボックスから切り替える）。
    """
    estimated_laps = estimated_laps or {}
    rows: list[dict] = []

    for run in runs:
        laps = split_floats(run.get("race_laps"))
        distances = [int(d) for d in split_floats(run.get("lap_distances"))]
        if not laps or len(distances) != len(laps):
            continue  # ラップが無い（障害など）／距離と対応が取れない走は描かない

        label = race_label(run)
        finish = finish_label(run)
        name = run.get("race_name") or ""
        # 1走ぶんの線は、点線（レースラップ）も実線（個別推定）も同じ太さ・濃さにする
        place = place_label(run)
        if include_race_laps:
            for distance, lap in zip(distances, laps, strict=True):
                rows.append({
                    "race": label, "race_id": run.get("race_id"), "distance_m": distance,
                    "lap_sec": lap, "kind": RACE_LAP_KIND, "finish": finish, "name": name,
                    "place": place,
                })

        estimated = estimated_laps.get(run_key(run))
        if estimated:
            kind = REFERENCE_LAP_KIND if estimated.is_reference else ESTIMATED_LAP_KIND
            for distance, lap in zip(distances, estimated.values, strict=False):
                # 推定できなかった区間は None のまま入れる（その区間だけ線が切れる）
                rows.append({
                    "race": label, "race_id": run.get("race_id"), "distance_m": distance,
                    "lap_sec": lap, "kind": kind, "finish": finish, "name": name,
                    "place": place,
                })
    return rows


def build_goal_rows(rows: list[dict]) -> list[dict]:
    """レースごとのゴール地点（最終区間）を1点ずつ返す。

    レースによって距離が違うので、どこがゴールかを図の上で示すために使う。
    レースラップを非表示にしているときは、個別推定ラップの行からゴール地点を拾う
    （点線を消してもゴールの位置が分からなくならないように）。
    """
    kind = RACE_LAP_KIND if any(r["kind"] == RACE_LAP_KIND for r in rows) else None
    goals: dict[str, dict] = {}
    for row in rows:
        if kind is not None and row["kind"] != kind:
            continue
        if row["lap_sec"] is None:
            continue
        current = goals.get(row["race"])
        if current is None or row["distance_m"] > current["distance_m"]:
            finish = row.get("finish") or ""
            label = f"{row['distance_m']}m {finish}" if finish and finish != DASH else f"{row['distance_m']}m"
            goals[row["race"]] = {**row, "goal_label": label}
    return list(goals.values())


# スマホ（compact）のグラフ本体の高さ。凡例は高さに含めない（autosize が fit-x）ので、
# 凡例の行数が増えてもグラフは潰れない
COMPACT_CHART_HEIGHT = 300
# スマホは着外の線も読めるように、PCほど細く・薄くしない（色で見分けるため）
COMPACT_PLACE_WIDTHS = [4.0, 2.5, 2.5]
COMPACT_PLACE_OPACITIES = [1.0, 0.8, 0.8]
COMPACT_LEGEND_TITLE = "凡例（着順・日付・競馬場・コース・グレード・レース名）"


def _compact_y_axis(domain: list[float]) -> dict:
    """スマホの縦軸。見出しは画面側（グラフの上の小さな文字）に出すので、軸には付けない。
    目盛りは0.5秒ごと。"""
    low, high = domain
    values = [round(low + 0.5 * i, 1) for i in range(int((high - low) / 0.5) + 1)]
    return {"title": None, "values": values, "labelFontSize": 11, "format": ".1f"}


def _color(color_legend: bool, races: list[str], compact: bool = False) -> dict:
    """レースごとの色と凡例（200m版・3区分版で共通）。

    PCは下に小さく横並び。スマホ（compact）は横に並べると切れるので、下に1列で縦に並べる。
    """
    legend = {
        # 主役はグラフ本体なので、凡例は下に小さく・横並びで出す
        "orient": "bottom", "direction": "horizontal", "columns": 4,
        "symbolType": "stroke", "labelFontSize": 12, "titleFontSize": 11,
        "symbolSize": 80, "labelLimit": 215, "rowPadding": 2,
        "columnPadding": 10, "titlePadding": 4,
    }
    if compact:
        legend.update({
            "direction": "vertical", "columns": 1, "labelLimit": 360, "rowPadding": 6,
            "labelFontSize": 13, "symbolStrokeWidth": 4, "symbolSize": 200,
            "title": COMPACT_LEGEND_TITLE, "titleFontWeight": "normal", "titleColor": "#6b6865",
            "titlePadding": 8, "offset": 14,
        })
    return {
        "field": "race",
        "type": "nominal",
        "title": LEGEND_TITLE,
        "sort": races,
        "scale": {"range": LINE_COLORS},
        "legend": legend if color_legend else None,
    }


def _with_finish_in_legend(rows: list[dict]) -> list[dict]:
    """スマホ（compact）用。線の右端の着順ラベルを出さない代わりに、凡例の頭に着順を付ける。

    `finish` は「1着 (東京 ク10.1)」の形なので、頭の「1着」だけを使う。
    """
    out = []
    for row in rows:
        head = (row.get("finish") or "").split(" ")[0]
        out.append({**row, "race": f'{head} {row["race"]}' if head and head != DASH else row["race"]})
    return out


def _stroke_dash() -> dict:
    """レースラップ=点線 / 個別推定ラップ=実線 / 参考値=破線。"""
    return {
        "field": "kind",
        "type": "nominal",
        "title": "種別",
        "scale": {"domain": LAP_KINDS, "range": DASH_PATTERNS},
        # 点線・実線の凡例は線見本がうまく出ないので、グラフ下の説明文で補う
        "legend": None,
    }


def _place_emphasis(compact: bool = False) -> dict:
    """複勝圏内の走を太く濃く、着外を細く薄く（線の層だけに付ける）。

    レースごとの色（`color`）・種別の点線（`strokeDash`）とは別の軸なので、
    3つを重ねてもぶつからない。凡例はグラフ下の説明文で補う。
    スマホ（compact）は着外の線も色で見分けられるよう、差を小さくする。
    """
    widths = COMPACT_PLACE_WIDTHS if compact else PLACE_WIDTHS
    opacities = COMPACT_PLACE_OPACITIES if compact else PLACE_OPACITIES
    return {
        "strokeWidth": {
            "field": "place", "type": "nominal",
            "scale": {"domain": PLACE_ORDER, "range": widths},
            "legend": None,
        },
        "opacity": {
            "field": "place", "type": "nominal",
            "scale": {"domain": PLACE_ORDER, "range": opacities},
            "legend": None,
        },
    }


def _axes(color_legend: bool, races: list[str], compact: bool = False) -> dict:
    """レイヤー共通の軸・色の指定（軸は固定、色はレースごと）。"""
    return {
        "x": {
            "field": "distance_m",
            "type": "quantitative",
            "title": X_TITLE,
            "scale": {"domain": X_DOMAIN, "clamp": True, "nice": False},
        },
        "y": {
            "field": "lap_sec",
            "type": "quantitative",
            "title": Y_TITLE,
            # netkeibaの走行データと同じく、上へ行くほど速い（10秒側）向きにする
            "scale": {"domain": Y_DOMAIN, "clamp": True, "nice": False, "reverse": True},
            **({"axis": _compact_y_axis(Y_DOMAIN)} if compact else {}),
        },
        "color": _color(color_legend, races, compact),
    }


def build_lap_spec(rows: list[dict], height: int = CHART_HEIGHT, compact: bool = False) -> dict:
    """Vega-Liteの定義を組み立てる（`$schema` は付けない。理由はモジュール冒頭）。

    折れ線（ラップ）＋ゴールの◆＋ゴールの距離ラベル、の3層を重ねる。
    `compact=True`（スマホ）はゴールのラベルを出さず、着順は凡例の頭に付ける（幅が狭いため）。
    """
    if compact:
        rows = _with_finish_in_legend(rows)
        height = min(height, COMPACT_CHART_HEIGHT)
    races = list(dict.fromkeys(row["race"] for row in rows))
    goals = build_goal_rows(rows)

    line_layer = {
        "data": {"values": rows},
        # 太さは place で決めるので、markには置かない（encodingが勝つため紛らわしい）
        "mark": {"type": "line", "point": {"filled": True, "size": 28}},
        "encoding": {
            **_axes(color_legend=True, races=races, compact=compact),
            "strokeDash": _stroke_dash(),
            **_place_emphasis(compact),
            "tooltip": [
                {"field": "race", "type": "nominal", "title": "レース"},
                {"field": "finish", "type": "nominal", "title": "着順"},
                {"field": "kind", "type": "nominal", "title": "種別"},
                {"field": "distance_m", "type": "quantitative", "title": X_TITLE},
                {"field": "lap_sec", "type": "quantitative", "title": Y_TITLE, "format": ".1f"},
            ],
        },
    }
    goal_point_layer = {
        "data": {"values": goals},
        "mark": {"type": "point", "shape": "diamond", "filled": True, "size": 110},
        "encoding": {
            **_axes(color_legend=False, races=races),
            "tooltip": [
                {"field": "race", "type": "nominal", "title": "レース"},
                {"field": "goal_label", "type": "nominal", "title": "ゴール"},
            ],
        },
    }
    goal_label_layer = {
        "data": {"values": goals},
        "mark": {"type": "text", "align": "left", "dx": 8, "dy": -2, "fontSize": 10, "fontWeight": "bold"},
        "encoding": {
            **_axes(color_legend=False, races=races),
            "text": {"field": "goal_label", "type": "nominal"},
        },
    }
    if compact:
        return {
            "height": height,
            # 高さはグラフ本体だけ（凡例のぶんで潰れないように）
            "autosize": {"type": "fit-x", "contains": "padding"},
            "layer": [line_layer, goal_point_layer],
        }
    return {
        "height": height,
        "autosize": {"type": "fit", "contains": "padding"},
        "layer": [line_layer, goal_point_layer, goal_label_layer],
    }


# --- 3区分（前2F・中間・上り3F）版 -------------------------------------------

PHASE_X_TITLE = "レースの区分"
PHASE_Y_TITLE = "1Fあたりのラップ（秒）"
# 縦軸は10.5〜13.5秒に固定する（どの馬・どのレースでも同じ尺度で見比べられるように）。
# 実際の走りはほぼこの中に収まるので、上下を詰めて差を見やすくしている。
# DB全体では9.8〜15.1秒まで散るので、はみ出す値は clamp で軸の端に描く（数値はtooltipで見える）。
PHASE_Y_DOMAIN = [10.5, 13.5]
# 横に6点なので、200m版より少しだけ縦を詰める
PHASE_CHART_HEIGHT = 480


def build_phase_rows(
    runs: list[dict],
    estimated_laps: dict[tuple[str, int | None], EstimatedLaps] | None = None,
    include_race_laps: bool = True,
) -> list[dict]:
    """区分ごと（前後200m＋中間平均）のグラフ用の行を作る（1走あたり最大6点）。

    距離の違うレースも同じ横軸に重なるよう、値は**1Fあたりの秒**にする（lap_phases.py）。
    """
    estimated_laps = estimated_laps or {}
    rows: list[dict] = []

    for run in runs:
        laps = split_floats(run.get("race_laps"))
        distances = split_floats(run.get("lap_distances"))
        distance_m = run.get("distance_m")
        if not laps or len(distances) != len(laps) or not distance_m:
            continue

        label = race_label(run)
        series: list[tuple[str, list[float | None]]] = []
        if include_race_laps:
            series.append((RACE_LAP_KIND, list(laps)))
        estimated = estimated_laps.get(run_key(run))
        if estimated:
            kind = REFERENCE_LAP_KIND if estimated.is_reference else ESTIMATED_LAP_KIND
            series.append((kind, list(estimated.values)))

        finish = finish_label(run)
        name = run.get("race_name") or ""
        place = place_label(run)
        for kind, values in series:
            for phase, pace in phase_paces(values, distances, distance_m).items():
                rows.append({
                    "race": label, "race_id": run.get("race_id"), "phase": phase,
                    "pace_sec": pace, "kind": kind, "finish": finish, "name": name,
                    "place": place,
                })
    return rows


def build_finish_rows(rows: list[dict]) -> list[dict]:
    """レースごとに「線の右端」の点を1つ返す（着順をグラフ内に出すため）。

    個別推定ラップとレースラップの両方があるレースは、**推定の側**を選ぶ
    （同じレースに同じラベルが2つ出ないように）。
    欠損（値がNone）の点は選ばない。
    """
    order = {ESTIMATED_LAP_KIND: 0, REFERENCE_LAP_KIND: 1, RACE_LAP_KIND: 2}
    labels = list(PHASE_LABELS)
    ends: dict[str, dict] = {}
    for row in rows:
        if row.get("pace_sec") is None or not row.get("finish") or row["finish"] == DASH:
            continue
        current = ends.get(row["race"])
        rank = (order.get(row["kind"], 9), -labels.index(row["phase"]))
        if current is None or rank < current["_rank"]:
            ends[row["race"]] = {**row, "finish_label": row["finish"], "_rank": rank}
    rows_out = [{k: v for k, v in row.items() if k != "_rank"} for row in ends.values()]
    return _spread_labels(rows_out)


# ほぼ同じ高さで終わった走はラベルが重なるので、少しずつ下へずらす。
# ずらし量は秒（縦軸の値）で持つ: Vega-Liteのテキストには画素単位のずらしを
# データごとに指定できないため、**ラベルを描く高さそのもの**をずらす。
# 縦軸は4秒ぶんなので、0.12秒 ≒ 1行ぶんの高さになる。
LABEL_GAP_SEC = 0.12


def _spread_labels(rows: list[dict]) -> list[dict]:
    """重なる着順ラベル用に、描く高さ（`label_y`）をずらして持たせる。"""
    ordered = sorted(rows, key=lambda r: r["pace_sec"])
    previous = None
    for row in ordered:
        value = row["pace_sec"]
        if previous is not None and value - previous < LABEL_GAP_SEC:
            value = previous + LABEL_GAP_SEC   # 直前のラベルの1行ぶん下に置く
        row["label_y"] = round(value, 3)
        previous = value
    return ordered


def _phase_axes(rows: list[dict], races: list[str], color_legend: bool, compact: bool = False) -> dict:
    """3区分版の軸（層をまたいで同じものを使う）。

    スマホ（compact）は横に6つの区分が入りきるよう、目盛りの字を小さくし、間引かせない。
    """
    return {
        "x": {
            "field": "phase",
            "type": "ordinal",
            "title": PHASE_X_TITLE,
            "sort": list(PHASE_LABELS),
            "scale": {"padding": 0.35},
            # ラベルを横書きで出す（既定だと縦に回ってしまう）
            "axis": {"labelAngle": 0, "labelFontSize": 10 if compact else 12, "labelPadding": 6,
                     **({"labelOverlap": False} if compact else {})},
        },
        "y": {
            "field": "pace_sec",
            "type": "quantitative",
            "title": PHASE_Y_TITLE,
            # 200m版と同じく、上へ行くほど速い向きにする
            "scale": {"domain": PHASE_Y_DOMAIN, "clamp": True, "nice": False, "reverse": True},
            **({"axis": _compact_y_axis(PHASE_Y_DOMAIN)} if compact else {}),
        },
        "color": _color(color_legend, races, compact),
    }


def build_phase_spec(rows: list[dict], height: int = PHASE_CHART_HEIGHT, compact: bool = False) -> dict:
    """区分ごとのVega-Liteの定義（`$schema` は付けない。理由はモジュール冒頭）。

    折れ線の層と、線の右端に着順を出す層の2層。
    `compact=True`（スマホ）は線の右端の着順を出さず（グラフが細く潰れるため）、
    着順は凡例の頭に付ける。凡例は下に1列で縦に並べる。
    """
    if compact:
        rows = _with_finish_in_legend(rows)
        height = min(height, COMPACT_CHART_HEIGHT)
    races = list(dict.fromkeys(row["race"] for row in rows))
    line_layer = {
        "data": {"values": rows},
        # 太さは place で決めるので、markには置かない（encodingが勝つため紛らわしい）
        "mark": {"type": "line", "point": {"filled": True, "size": 60}},
        "encoding": {
            **_phase_axes(rows, races, color_legend=True, compact=compact),
            "strokeDash": _stroke_dash(),
            **_place_emphasis(compact),
            "tooltip": [
                {"field": "race", "type": "nominal", "title": "レース"},
                {"field": "finish", "type": "nominal", "title": "着順"},
                {"field": "name", "type": "nominal", "title": "レース名"},
                {"field": "kind", "type": "nominal", "title": "種別"},
                {"field": "phase", "type": "nominal", "title": PHASE_X_TITLE},
                {"field": "pace_sec", "type": "quantitative", "title": PHASE_Y_TITLE, "format": ".2f"},
            ],
        },
    }
    finish_layer = {
        "data": {"values": build_finish_rows(rows)},
        "mark": {
            "type": "text", "align": "left", "dx": 9, "dy": -1,
            "fontSize": 12, "fontWeight": "bold",
        },
        "encoding": {
            **_phase_axes(rows, races, color_legend=False),
            # 重なったラベルは label_y（少し下にずらした高さ）に描く
            "y": {
                "field": "label_y",
                "type": "quantitative",
                "title": PHASE_Y_TITLE,
                "scale": {"domain": PHASE_Y_DOMAIN, "clamp": True, "nice": False, "reverse": True},
            },
            "text": {"field": "finish_label", "type": "nominal"},
        },
    }
    if compact:
        return {
            "height": height,
            # 高さはグラフ本体だけ（凡例のぶんで潰れないように）
            "autosize": {"type": "fit-x", "contains": "padding"},
            "padding": {"left": 2, "top": 5, "right": 8, "bottom": 5},
            "layer": [line_layer],
        }
    return {
        "height": height,
        "autosize": {"type": "fit", "contains": "padding"},
        # 線の右端に着順を出すので、右側に文字ぶんの余白を空ける（切れないように）
        "padding": {"left": 5, "top": 5, "right": 95, "bottom": 5},
        "layer": [line_layer, finish_layer],
    }
