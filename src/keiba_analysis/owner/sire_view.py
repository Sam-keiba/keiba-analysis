"""種牡馬分析の表・ゲージ・レーダーチャートのHTML（と、この画面だけのCSS）。

グラフのうちAEI推移だけはVega-Lite（sire_chart.py）で、ここは
**HTML＋CSSとインラインSVG**で組む（馬柱・コース図と同じ流儀）。
Vega-Liteに極座標のレーダーが無いので、レーダーは course_map.py と同じく手でSVGを書く。

**出せない指標は「—」にして、なぜ出せないかをその場に書く。**
埋め合わせの推測値は作らない。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape

from keiba_data.sire_data import GRADES, Metric

# --- 色（style.py と同じ系統から選ぶ） -----------------------------------------------
ACCENT = "#1f7a50"          # 値を表す緑
ACCENT_SOFT = "#a8d5bd"
LOCAL_ACCENT = "#2168c3"       # 手元DB由来（集計範囲が違うので色を分ける）
LOCAL_ACCENT_SOFT = "#bcd4ee"
FIELD_COLOR = "#9aa09a"     # 全種牡馬平均
MUTED = "#c9cdc9"           # データが無いところ
DASH = "—"


@dataclass(frozen=True)
class RadarAxis:
    """レーダーの1軸。`metric` が None ＝ この軸はまだ出せない。

    `scope` は集計範囲（JRAリーディングは全期間、手元DBは `local_scope()` の範囲）。
    同じ絵の中で範囲が違うので、点の色を変えて凡例に出す。
    """

    label: str          # 「安定」
    basis: str          # 何で測っているか（「勝ち上がり率」）
    metric: Metric | None
    missing_reason: str = ""
    scope: str = "全期間"


# 元にした画面と同じ6軸。JRA公式のリーディングから出せるのは3軸だけなので、
# 残りは「データなし」として形だけ残す（後から埋められるように順番は変えない）
# (軸, リーディング由来のキー, 手元DB由来のキー, 測っているもの, 出せない理由)
# **リーディング由来は全期間・手元DB由来は手元のDBの範囲**なので、画面で必ず区別する
RADAR_LAYOUT: tuple[tuple[str, str, str, str, str], ...] = (
    ("安定", "win_rate", "", "勝ち上がり率", ""),
    ("健康", "starts_per_horse", "", "年間平均出走回数", ""),
    ("クラシック", "", "classic", "クラシック出走馬輩出率", ""),
    ("大物", "prize_per_horse", "", "1頭平均賞金", ""),
    ("投資", "", "", "クラブ馬回収率",
     "一口クラブの募集価格はどの公開サイトにも載っていない。"),
    ("堅実", "", "board", "掲示板入着率", ""),
)

# 「産駒傾向分析データ」で、どうしても出せない項目
MISSING_TRENDS: tuple[tuple[str, str], ...] = (
    ("平均募集価格（クラブ馬）", "一口クラブの募集価格はどの公開サイトにも載っていない"),
    ("クラブ馬回収率", "同上（募集価格が分からないと回収率が出せない）"),
)


def format_value(metric: Metric, value: float | None) -> str:
    """指標ごとの見せ方（割合は%、金額は万円、回数は小数1桁）。"""
    if value is None:
        return DASH
    if metric.key == "win_rate":
        return f"{value * 100:.1f}%"
    if metric.key == "starts_per_horse":
        return f"{value:.2f}回"
    if metric.key == "prize_per_horse":
        return f"{value / 10000:,.0f}万円"
    if metric.key == "n_horses":
        return f"{value:,.0f}頭"
    return f"{value:.2f}"


# --- ゲージ（産駒傾向分析データ） ---------------------------------------------------

def _gauge(metric: Metric) -> str:
    """1本のゲージ。全種牡馬の分布の中でどこにいるかを位置で見せる。

    バーの左右は「全種牡馬のいちばん低い／高い」ではなく**分布の中の順位**なので、
    真ん中が全種牡馬のまんなか（中央値）になる。
    """
    if metric.percentile is None:
        position = None
    else:
        position = max(2.0, min(98.0, metric.percentile * 100))
    value = format_value(metric, metric.value)
    field = format_value(metric, metric.field_value)
    ratio = metric.ratio_to_field
    ratio_text = f"全種牡馬平均の {ratio:.2f} 倍" if ratio else ""
    marker = (
        f'<span class="sg-marker" style="left:{position:.1f}%"></span>'
        if position is not None else ""
    )
    return f"""
<div class="sg-row">
  <div class="sg-head">
    <span class="sg-label">{escape(metric.label)}</span>
    <span class="sg-value">{escape(value)}</span>
    <span class="sg-field">全種牡馬平均 {escape(field)}{escape("／" + ratio_text if ratio_text else "")}</span>
  </div>
  <div class="sg-bar">
    <span class="sg-mid"></span>
    {marker}
  </div>
  <div class="sg-ends">
    <span>{escape(metric.low_label)}</span><span>{escape(metric.high_label)}</span>
  </div>
  <div class="sg-note">{escape(metric.description)}</div>
</div>"""


def render_gauges(metrics: list[Metric]) -> str:
    """産駒傾向分析データ（JRA公式の種牡馬リーディングから出せるぶん）。"""
    if not metrics:
        return '<div class="sire-empty">この種牡馬の成績がまだ取り込まれていません。</div>'
    return f'<div class="sire-gauges">{"".join(_gauge(m) for m in metrics)}</div>'


def render_missing_trends() -> str:
    """まだ出せない項目を、何が足りないかと一緒に並べる。"""
    items = "".join(
        f'<li><b>{escape(label)}</b>（{escape(reason)}）</li>' for label, reason in MISSING_TRENDS
    )
    return (
        '<div class="sire-missing"><div class="sm-title">まだ出せない項目</div>'
        f'<ul>{items}</ul>'
        '<div class="sm-note">いずれも「その種牡馬の産駒が1頭ずつ何をしたか」が要る指標です。'
        'JRA公式の種牡馬リーディングは年ごとの合計しか出していないため、'
        'ここでは数字を作らず空けてあります。</div></div>'
    )


# --- AEI・CPI分析表 ---------------------------------------------------------------

def render_aei_table(rows: list[tuple[str, str, str]]) -> str:
    """`(項目, 値, 説明)` を並べた表。値が `—` の行は薄く見せる。"""
    body = "".join(
        f'<tr class="{"sa-missing" if value == DASH else ""}">'
        f'<th>{escape(label)}</th><td class="sa-value">{escape(value)}</td>'
        f'<td class="sa-desc">{escape(note)}</td></tr>'
        for label, value, note in rows
    )
    return f'<table class="sire-aei"><tbody>{body}</tbody></table>'


# --- レーダーチャート ---------------------------------------------------------------

def _point(cx: float, cy: float, radius: float, index: int, n: int) -> tuple[float, float]:
    """真上から時計回りにn等分したi番目の点。"""
    angle = -math.pi / 2 + 2 * math.pi * index / n
    return cx + radius * math.cos(angle), cy + radius * math.sin(angle)


# レーダーの外側に置く軸ラベルのぶんの余白。左右は文字が横に伸びるので広く取る
RADAR_SIDE_PAD = 92
RADAR_TOP_PAD = 42


def render_radar(axes: list[RadarAxis], size: int = 300) -> str:
    """6軸のレーダー。**値が出せる軸だけ**を色付きの棒と点で描く。

    出せない軸まで結んで多角形にすると、無い数字をあるように見せてしまう。
    そこで多角形は「6軸ぜんぶ埋まったときだけ」描き、それまでは軸ごとの棒で出す。

    `size` は**多角形の直径**。軸ラベルは外側に出るので、viewBoxはその外に
    余白（`RADAR_SIDE_PAD` / `RADAR_TOP_PAD`）を足した大きさにする。
    左右のラベル（「クラシック」など）が切れないよう、横は縦より広く取る。
    """
    n = len(axes)
    radius = size / 2
    width = size + RADAR_SIDE_PAD * 2
    height = size + RADAR_TOP_PAD * 2
    cx, cy = width / 2, height / 2
    rings, spokes, bars, labels = [], [], [], []

    for grade in (3, 5, 7, 9):
        points = " ".join(
            f"{x:.1f},{y:.1f}" for x, y in
            (_point(cx, cy, radius * grade / GRADES, i, n) for i in range(n))
        )
        # 5段階目（＝全種牡馬のまんなか）だけ太い破線にして、基準線だと分かるようにする
        stroke = 1.4 if grade == 5 else 0.8
        color = FIELD_COLOR if grade == 5 else "#e3e6e3"
        dash = ' stroke-dasharray="4 3"' if grade == 5 else ""
        rings.append(
            f'<polygon points="{points}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}"{dash} />'
        )

    for i, axis in enumerate(axes):
        ex, ey = _point(cx, cy, radius, i, n)
        spokes.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
                      f'stroke="#e3e6e3" stroke-width="0.8" />')
        lx, ly = _point(cx, cy, radius + 22, i, n)
        anchor = "middle" if abs(lx - cx) < 4 else ("start" if lx > cx else "end")
        grade = axis.metric.grade if axis.metric else None
        if grade is None:
            labels.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" class="sr-label sr-off">'
                f'{escape(axis.label)}</text>'
                f'<text x="{lx:.1f}" y="{ly + 15:.1f}" text-anchor="{anchor}" class="sr-sub sr-off">'
                f'データなし</text>'
            )
            continue
        px, py = _point(cx, cy, radius * grade / GRADES, i, n)
        # リーディング由来（全期間）は緑、手元DB由来（1995年以降など）は青にする
        local = axis.scope != "全期間"
        bar_color = LOCAL_ACCENT_SOFT if local else ACCENT_SOFT
        dot_color = LOCAL_ACCENT if local else ACCENT
        bars.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{px:.1f}" y2="{py:.1f}" '
            f'stroke="{bar_color}" stroke-width="9" stroke-linecap="round" />'
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="{dot_color}" />'
        )
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" class="sr-label">'
            f'{escape(axis.label)}</text>'
            f'<text x="{lx:.1f}" y="{ly + 15:.1f}" text-anchor="{anchor}" class="sr-sub">'
            f'{grade} / {GRADES}</text>'
        )

    filled = [a for a in axes if a.metric is not None]
    polygon = ""
    if len(filled) == n:
        points = " ".join(
            f"{x:.1f},{y:.1f}" for x, y in (
                _point(cx, cy, radius * (a.metric.grade or 1) / GRADES, i, n)
                for i, a in enumerate(axes)
            )
        )
        polygon = (f'<polygon points="{points}" fill="{ACCENT}" fill-opacity="0.18" '
                   f'stroke="{ACCENT}" stroke-width="2" />')

    return (
        f'<div class="sire-radar"><svg viewBox="0 0 {width:.0f} {height:.0f}" width="100%" '
        f'role="img" aria-label="主要指標のレーダーチャート">'
        f'{"".join(rings)}{"".join(spokes)}{polygon}{"".join(bars)}{"".join(labels)}'
        f'</svg></div>'
    )


def render_radar_basis(axes: list[RadarAxis]) -> str:
    """レーダーの算出根拠。軸・何で測ったか・値・全種牡馬平均・段階を並べる。"""
    rows = []
    for axis in axes:
        metric = axis.metric
        if metric is None:
            rows.append(
                f'<tr class="sa-missing"><th>{escape(axis.label)}</th>'
                f'<td>{escape(axis.basis)}</td><td>{DASH}</td><td class="sa-value">{DASH}</td>'
                f'<td class="sa-value">{DASH}</td><td class="sa-value">{DASH}</td>'
                f'<td class="sa-desc">{escape(axis.missing_reason)}</td></tr>'
            )
            continue
        rows.append(
            f'<tr><th>{escape(axis.label)}</th><td>{escape(axis.basis)}</td>'
            f'<td>{escape(axis.scope)}</td>'
            f'<td class="sa-value">{escape(format_value(metric, metric.value))}</td>'
            f'<td class="sa-value">{escape(format_value(metric, metric.field_value))}</td>'
            f'<td class="sa-value"><b>{metric.grade}</b> / {GRADES}</td>'
            f'<td class="sa-desc">{escape(metric.description)}</td></tr>'
        )
    head = (
        "<tr><th>軸</th><th>測っているもの</th><th>集計範囲</th><th>この種牡馬</th>"
        "<th>全種牡馬平均</th><th>段階</th><th>説明</th></tr>"
    )
    return f'<table class="sire-basis"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


CSS = f"""
<style>
.sire-head {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
  border-bottom:2px solid {ACCENT}; padding-bottom:6px; margin-bottom:10px; }}
.sire-head .sh-name {{ font-size:24px; font-weight:700; }}
.sire-head .sh-fact {{ font-size:13px; color:#5c645c; }}
.sire-empty {{ padding:18px; background:#f6f7f6; border-radius:6px; color:#5c645c; }}

/* 産駒傾向のゲージ */
.sire-gauges {{ display:grid; gap:18px; }}
.sg-head {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
.sg-label {{ font-weight:700; font-size:14px; min-width:9em; }}
.sg-value {{ font-size:17px; font-weight:700; color:{ACCENT}; }}
.sg-field {{ font-size:12px; color:#6d756d; }}
.sg-bar {{ position:relative; height:12px; border-radius:6px; margin:6px 0 2px;
  background:linear-gradient(90deg,#eef1ee 0%, {ACCENT_SOFT} 100%); }}
.sg-mid {{ position:absolute; left:50%; top:-3px; width:2px; height:18px;
  background:{FIELD_COLOR}; }}
.sg-marker {{ position:absolute; top:-4px; width:14px; height:20px; margin-left:-7px;
  border-radius:4px; background:{ACCENT}; box-shadow:0 0 0 2px #fff; }}
.sg-ends {{ display:flex; justify-content:space-between; font-size:11px; color:#8a918a; }}
.sg-note {{ font-size:12px; color:#5c645c; margin-top:4px; line-height:1.6; }}

/* まだ出せない項目 */
.sire-missing {{ margin-top:18px; padding:12px 14px; background:#fafbfa;
  border:1px solid #e3e6e3; border-radius:6px; }}
.sire-missing .sm-title {{ font-weight:700; font-size:13px; color:#5c645c; }}
.sire-missing ul {{ margin:6px 0 6px 1.1em; padding:0; }}
.sire-missing li {{ font-size:12px; color:#5c645c; line-height:1.8; }}
.sire-missing .sm-note {{ font-size:12px; color:#6d756d; line-height:1.7; }}

/* AEI・CPI分析表／算出根拠 */
.sire-aei, .sire-basis {{ width:100%; border-collapse:collapse; font-size:13px; }}
.sire-aei th, .sire-basis th, .sire-aei td, .sire-basis td {{
  border-bottom:1px solid #e3e6e3; padding:8px 10px; text-align:left; vertical-align:top; }}
.sire-aei th, .sire-basis th {{ background:#f6f7f6; font-weight:700; white-space:nowrap; }}
.sire-basis thead th {{ text-align:left; }}
.sa-value {{ font-size:15px; font-weight:700; color:{ACCENT}; white-space:nowrap; }}
.sa-desc {{ font-size:12px; color:#5c645c; line-height:1.7; }}
.sa-missing td, .sa-missing th {{ color:#98a098; }}
.sa-missing .sa-value {{ color:{MUTED}; }}

/* 8つのタブ（分析サマリー／距離適性…）。`st.container(key="sire_tabs")` が付ける
   クラスで狙っているので、**sire_app.py のキーと対で直すこと**。
   競馬新聞の `.st-key-race_tabs` と同じ見え方にそろえる。 */
.st-key-sire_tabs [data-testid="stTab"] {{ padding: 10px 18px; border-top:3px solid transparent; }}
.st-key-sire_tabs [data-testid="stTab"] p {{ font-size:15px; font-weight:700; }}
.st-key-sire_tabs [data-testid="stTab"][aria-selected="true"] {{
  border-top-color:{ACCENT}; color:#1b1b1b; }}
.st-key-sire_tabs [data-testid="stTab"][aria-selected="true"] p {{ color:{ACCENT}; }}

/* レーダー */
.sire-radar {{ max-width:520px; margin:0 auto; }}
.sr-label {{ font-size:14px; font-weight:700; fill:#2b2b2b; }}
.sr-sub {{ font-size:11px; fill:#6d756d; }}
.sr-off {{ fill:#b4bab4; }}
</style>
"""


# --- 手元DBから出す表（距離適性・BMS相性・重賞実績・代表産駒） -----------------------

# 手元のDBに入っている最初の年（1995〜2022年はTarget、2023年以降はスクレイピング由来）
DATA_SINCE_YEAR = 1995


def local_scope(since: str | None = None) -> str:
    """手元DB由来の集計範囲の表記。`since`（'YYYY-MM-DD'）は `sire_runs` に渡したものと同じ値。"""
    year = int(since[:4]) if since else DATA_SINCE_YEAR
    return f"{year}年以降のJRA"


def local_note(since: str | None = None) -> str:
    """手元DB由来の表に添える注記。リーディング由来（全期間）と混ぜないための目印。"""
    return (
        f"この表は**手元のDBに入っている{local_scope(since)}のレース**だけを数えています"
        "（JRAリーディング由来の数字は全期間なので、そろいません）。"
    )


# 既定の範囲（`since` を渡さないとき）の表記
LOCAL_SCOPE = local_scope()
LOCAL_NOTE = local_note()


def _rate(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else DASH


def render_coverage(coverage, scope: str = LOCAL_SCOPE) -> str:
    """血統の取り込みがどこまで進んでいるかの帯。取り込み途中でも数字が読めるように。

    DB全体の数は `keiba pedigree` が父を埋める対象（2023年以降に走った馬）だけで数えている。
    """
    ratio = f"{coverage.ratio * 100:.0f}%" if coverage.ratio is not None else DASH
    more = "" if coverage.is_complete else (
        f'<span class="sc-more">2023年以降に走った馬では {coverage.known:,} / '
        f'{coverage.total:,}頭（{ratio}）の父が分かっています。'
        f'<code>uv run keiba pedigree</code> を実行すると増えます</span>'
    )
    return (
        f'<div class="sire-coverage">この種牡馬の産駒として分かっているのは'
        f'<b>{coverage.sire_horses:,}頭・{coverage.sire_runs:,}走</b>'
        f'（{escape(scope)}）{more}</div>'
    )


def render_tally_table(tallies, first_header: str = "区分") -> str:
    """区分ごとの成績の表（頭数・出走・1着・勝率・複勝率・掲示板率）。"""
    rows = []
    for t in tallies:
        cls = ' class="sa-missing"' if t.is_thin else ""
        rows.append(
            f"<tr{cls}><th>{escape(t.label)}</th>"
            f"<td>{t.horses:,}</td><td>{t.starts:,}</td><td>{t.wins:,}</td>"
            f"<td>{_rate(t.win_rate)}</td><td>{_rate(t.top3_rate)}</td>"
            f"<td>{_rate(t.top5_rate)}</td></tr>"
        )
    head = (f"<tr><th>{escape(first_header)}</th><th>頭数</th><th>出走</th><th>1着</th>"
            "<th>勝率</th><th>複勝率</th><th>掲示板率</th></tr>")
    return f'<table class="sire-basis"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


def render_graded_wins(wins: list[dict], venue_names: dict[str, str],
                       scope: str = LOCAL_SCOPE) -> str:
    """産駒が勝った重賞の一覧（新しい順）。"""
    if not wins:
        return f'<div class="sire-empty">{escape(scope)}に産駒が勝った重賞はありません。</div>'
    rows = []
    for w in wins:
        surface = {"turf": "芝", "dirt": "ダート", "jump": "障害"}.get(w["surface"] or "", "")
        course = f'{venue_names.get(w["venue_code"] or "", "")} {surface}{w["distance_m"] or ""}m'
        rows.append(
            f'<tr><td>{escape(w["race_date"])}</td>'
            f'<td><span class="sg-grade">{escape(w["grade"] or "")}</span></td>'
            f'<td>{escape(w["race_name"] or "")}</td>'
            f'<td><b>{escape(w["horse_name"] or "")}</b></td>'
            f'<td>{escape((w["sex"] or "") + str(w["age"] or ""))}</td>'
            f'<td>{escape(course)}</td></tr>'
        )
    head = "<tr><th>日付</th><th>格</th><th>レース名</th><th>馬名</th><th>性齢</th><th>コース</th></tr>"
    return f'<table class="sire-basis"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


def render_top_progeny(progeny: list[dict], scope: str = LOCAL_SCOPE) -> str:
    """獲得賞金の多い産駒。"""
    if not progeny:
        return f'<div class="sire-empty">{escape(scope)}に走った産駒がまだ分かっていません。</div>'
    rows = []
    for i, h in enumerate(progeny, 1):
        best = f'{h["best_grade"]} {h["best_win"]}' if h["best_grade"] else DASH
        rows.append(
            f'<tr><td>{i}</td><td><b>{escape(h["horse_name"] or "")}</b></td>'
            f'<td>{escape(h["sex"] or "")}</td>'
            f'<td>{escape(h["broodmare_sire"] or DASH)}</td>'
            f'<td>{h["starts"]}戦{h["wins"]}勝</td>'
            f'<td>{h["top3"]}</td>'
            f'<td class="sa-value">{h["prize_man_yen"]:,.0f}万円</td>'
            f'<td>{escape(best)}</td></tr>'
        )
    head = ("<tr><th>#</th><th>馬名</th><th>性</th><th>母の父</th><th>戦績</th>"
            "<th>3着内</th><th>獲得賞金</th><th>最高格の勝ち鞍</th></tr>")
    return f'<table class="sire-basis"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


LOCAL_CSS = f"""
<style>
.sire-coverage {{ font-size:12px; color:#5c645c; background:#f6f7f6; border-radius:6px;
  padding:8px 12px; margin-bottom:12px; }}
.sire-coverage .sc-more {{ display:block; color:#6d756d; margin-top:2px; }}
.sire-coverage code {{ background:#eceeec; padding:1px 5px; border-radius:3px; }}
.sg-grade {{ display:inline-block; background:{ACCENT}; color:#fff; border-radius:3px;
  padding:1px 6px; font-size:11px; font-weight:700; }}
</style>
"""


def render_local_table(metrics: list[Metric]) -> str:
    """手元DB由来の項目の表（この種牡馬／全産駒平均／全種牡馬の中の段階）。

    ゲージ（リーディング由来）と見た目を分けて、**集計範囲が違うことを取り違えない**ようにする。
    """
    rows = []
    for metric in metrics:
        value = _local_value(metric, metric.value)
        field = _local_value(metric, metric.field_value)
        grade = f"<b>{metric.grade}</b> / {GRADES}" if metric.grade else DASH
        cls = ' class="sa-missing"' if metric.value is None else ""
        rows.append(
            f'<tr{cls}><th>{escape(metric.label)}</th>'
            f'<td class="sa-value">{escape(value)}</td>'
            f'<td class="sa-value">{escape(field)}</td>'
            f'<td class="sa-value">{grade}</td>'
            f'<td class="sa-desc">{escape(metric.description)}</td></tr>'
        )
    head = ("<tr><th>項目</th><th>この種牡馬</th><th>全産駒平均</th>"
            "<th>段階</th><th>説明</th></tr>")
    return f'<table class="sire-basis"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


def _local_value(metric: Metric, value: float | None) -> str:
    """手元DB由来の項目の見せ方（単位は Metric.unit に入っている）。"""
    if value is None:
        return DASH
    if metric.unit.endswith("%"):
        return f"{value * 100:.1f}%"
    if metric.unit == "m":
        return f"{value:,.0f}m"
    if metric.unit == "kg":
        return f"{value:.0f}kg"
    return f"{value:.2f}"


# --- 血統クロス -------------------------------------------------------------------

def render_cross_table(rows, first_header: str = "祖先") -> str:
    """祖先別・クロス別の表。**持つ産駒と持たない産駒を並べて**出す。

    片方だけでは「持っていると走るのか」が読めないので、必ず対で見せる。
    いちばん右の「倍率」は 持つ複勝率 ÷ 持たない複勝率 で、1.00より上なら
    持っているほうが走っていることになる。
    """
    if not rows:
        return ('<div class="sire-empty">まだ並べられる祖先がありません'
                '（血統表の取り込みが進むと出てきます）。</div>')
    body = []
    for row in rows:
        mine, other = row.with_tally, row.without_tally
        lift = row.lift
        lift_class = "sc-up" if lift and lift > 1.05 else ("sc-down" if lift and lift < 0.95 else "")
        thin = ' class="sa-missing"' if mine.is_thin else ""
        country = f'<span class="sc-country">{escape(row.country)}</span>' if row.country else ""
        body.append(
            f"<tr{thin}><th>{escape(row.label)}{country}</th>"
            f"<td>{row.horses:,}</td>"
            f"<td>{mine.starts:,}</td><td>{_rate(mine.win_rate)}</td>"
            f"<td><b>{_rate(mine.top3_rate)}</b></td>"
            f"<td class='sc-other'>{other.starts:,}</td>"
            f"<td class='sc-other'>{_rate(other.win_rate)}</td>"
            f"<td class='sc-other'>{_rate(other.top3_rate)}</td>"
            f"<td class='sc-lift {lift_class}'>{f'{lift:.2f}' if lift else DASH}</td></tr>"
        )
    head = (
        f'<tr><th rowspan="2">{escape(first_header)}</th><th rowspan="2">頭数</th>'
        '<th colspan="3">持つ産駒</th><th colspan="3">持たない産駒</th>'
        '<th rowspan="2">倍率</th></tr>'
        "<tr><th>出走</th><th>勝率</th><th>複勝率</th>"
        "<th>出走</th><th>勝率</th><th>複勝率</th></tr>"
    )
    return f'<table class="sire-basis sire-cross"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


CROSS_CSS = f"""
<style>
.sire-cross th[colspan] {{ text-align:center; }}
.sire-cross .sc-other {{ color:#8a918a; }}
.sire-cross .sc-lift {{ font-weight:700; }}
.sire-cross .sc-up {{ color:{ACCENT}; }}
.sire-cross .sc-down {{ color:#c0201a; }}
.sc-country {{ display:inline-block; margin-left:5px; padding:0 4px; border-radius:3px;
  background:#eceeec; color:#6d756d; font-size:10px; font-weight:400; }}
</style>
"""


# --- 一口クラブ比較 ---------------------------------------------------------------

def render_club_summary(rows: list[dict], selected: str | None = None) -> str:
    """全クラブを並べた比較表。選んでいるクラブの行を目立たせる。

    **勝ち上がり率だけは頭数が分母**（1勝でもした馬 ÷ 出走した馬）。
    ほかの率は出走が分母なので、見出しにもそう書く。
    **芝率は障害を分母から外した「芝 ÷ (芝+ダート)」**で、成績の率ではなく
    「何を走らせているか」なので勝率群より前に置く。
    """
    if not rows:
        return '<div class="sire-empty">クラブがまだ見つかりません。</div>'
    body = []
    for i, row in enumerate(rows, 1):
        mark = ' class="cl-selected"' if row["owner_id"] == selected else ""
        body.append(
            f"<tr{mark}><td>{i}</td>"
            f'<th>{escape(row["label"])}'
            f'<span class="cl-group">{escape(row["group"])}</span></th>'
            f'<td>{row["horses"]:,}</td><td>{row["starts"]:,}</td>'
            f'<td class="cl-turf">{_rate(row.get("turf_rate"))}</td>'
            f'<td class="sa-value">{_rate(row["win_up_rate"])}</td>'
            f'<td>{_rate(row["win_rate"])}</td><td>{_rate(row["top3_rate"])}</td>'
            f'<td>{_rate(row["top5_rate"])}</td>'
            f'<td class="sa-value">{(row["prize_per_horse"] or 0):,.0f}万</td>'
            f'<td>{row["graded_winners"]:,}</td></tr>'
        )
    head = ("<tr><th>#</th><th>クラブ</th><th>頭数</th><th>出走</th><th>芝率</th>"
            "<th>勝ち上がり率</th><th>勝率</th><th>複勝率</th><th>掲示板率</th>"
            "<th>1頭平均賞金</th><th>重賞勝馬</th></tr>")
    return (f'<table class="sire-basis sire-club"><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


CLUB_CSS = f"""
<style>
.sire-club .cl-selected {{ background:#eef7f1; }}
.sire-club .cl-selected th {{ background:#dcefe4; }}
.sire-club .cl-turf {{ color:#189a54; font-weight:700; }}
.cl-group {{ display:inline-block; margin-left:6px; padding:0 5px; border-radius:3px;
  background:#eceeec; color:#6d756d; font-size:10px; font-weight:400; }}
.club-head {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
  border-bottom:2px solid {ACCENT}; padding-bottom:6px; margin-bottom:10px; }}
.club-head .ch-name {{ font-size:24px; font-weight:700; }}
.club-head .ch-fact {{ font-size:13px; color:#5c645c; }}
</style>
"""
