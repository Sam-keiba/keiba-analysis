"""コース図の下に出す「開催の勝ちタイム」の表。

前週と開催週の、そのレースより前に行われた同じ馬場種別のレースを、**日ごとのタブ**に分けて並べる。
馬場がどう出ているか（時計が速いか、前が残るか）を読むための材料。

クッション値・含水率は**日ごと**の値なので日の見出しに置き、馬場状態は雨で
日中に変わりうるので行ごとに出す。集計は data.get_meeting_results。
"""

from __future__ import annotations

from datetime import date
from html import escape

from keiba_analysis.racing.best_times import hardness_head, hardness_text
from keiba_analysis.racing.past_runs import class_short, cushion_label, jra_race_link, pace_mark
from keiba_analysis.racing.race_forecast import format_race_time
from keiba_analysis.racing.running_style import classify_run
from keiba_analysis.shared.style import RUNNING_STYLE_COLORS, waku_color

DASH = "—"
WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")


def day_label(row: dict) -> str:
    """`9/20(日)`。日をまたぐ区切りの見出しに使う。"""
    text = row.get("race_date") or ""
    try:
        when = date.fromisoformat(text)
    except ValueError:
        return text
    return f"{when.month}/{when.day}({WEEKDAYS[when.weekday()]})"


def group_by_day(rows: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """(日の見出し, その日の馬場の硬さ, その日のレース) を新しい日から順に返す。"""
    days: list[tuple[str, str, list[dict]]] = []
    for row in rows:
        label = day_label(row)
        if not days or days[-1][0] != label:
            days.append((label, cushion_label(row), []))
        days[-1][2].append(row)
    return days


def split_days(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """(日の見出し, その日のレース) を**新しい日から**順に返す。

    タブは**日ごと**に分ける。開催週と前週を1つの表に混ぜると、馬場が
    変わった日をまたいで時計を見比べてしまうため。
    レースは日付の新しい順に並んでいる前提（data.get_meeting_results の並び）。
    """
    return [(label, races) for label, _, races in group_by_day(rows)]


def course_label(row: dict) -> str:
    """`1600外`。距離だけだと内回り・外回りの時計を混ぜて見てしまうので、内外も出す。"""
    distance = row.get("distance_m")
    if not distance:
        return DASH
    detail = (row.get("course_detail") or "").split(" ")[0]
    return f"{distance}{detail}"


def split_label(row: dict) -> str:
    """`35.3-34.3`。前半3Fと後半3F。"""
    first, last = row.get("first_3f"), row.get("last_3f")
    if first is None or last is None:
        return ""
    return f"{first:.1f}-{last:.1f}"


def _style_cell(row: dict) -> str:
    """勝ち馬の脚質。通過順位が取り込めていなければ「—」。"""
    style = classify_run(row.get("winner_corner"), row.get("n_runners"))
    if style is None:
        return DASH
    color = RUNNING_STYLE_COLORS.get(style, "#6b716b")
    tooltip = escape(f"勝ち馬の通過順位 {row.get('winner_corner')}（{row.get('n_runners')}頭）")
    return f'<span style="color:{color};font-weight:700" title="{tooltip}">{escape(style)}</span>'


def _columns(surface: str | None) -> list[tuple[str, str]]:
    """表の列（td のクラス, 見出し）。持ちタイムの表と同じ見た目・同じ並びの考え方にそろえる。"""
    return [
        ("mt-no", "R"), ("mt-class", "クラス"), ("mt-course", "距離"), ("mt-going", "馬場"),
        ("mt-time", "タイム"), ("mt-split", "前後3F"), ("mt-pace", "ペース"), ("mt-waku", "馬番"),
        ("mt-style", "脚質"), ("mt-num", "上がり"), ("mt-detail", "映像"),
    ]


def _distance_text(row: dict) -> str:
    """`1400m`（資料の表記）。距離が無ければ「—」。"""
    distance = row.get("distance_m")
    return f"{distance}m" if distance else DASH


def _winner_badge(row: dict) -> str:
    """勝ち馬の馬番（枠の色の四角。持ちタイムの馬番と同じ見た目）。結果が無ければ「—」。"""
    number = row.get("winner_umaban")
    if number is None:
        return DASH
    background, color = waku_color(row.get("winner_waku"))
    return f'<span class="waku" style="background:{background};color:{color}">{escape(str(number))}</span>'


def _winner_last_3f(row: dict) -> str:
    """勝ち馬の上り3F。馬ごとの結果がまだ無いレース（JRAのラップだけ）は「—」。"""
    value = row.get("winner_last_3f")
    return DASH if value is None else f"{float(value):.1f}"


def _hardness_note(rows: list[dict]) -> str:
    """表の上に出す、その日のクッション値（ダートは含水率）。1日のうちは変わらないので列にはしない。"""
    name = "含水率" if rows[0].get("surface") == "dirt" else "クッション値"
    for row in rows:
        text = hardness_text(row)
        if text != DASH:
            unit = "%" if name == "含水率" else ""
            return f"<div class='mt-hardness'>{name} <b>{escape(text)}{unit}</b></div>"
    return ""


def render_meeting(rows: list[dict]) -> str:
    """開催の勝ちタイムの表（**持ちタイムの表と同じ見た目**: 見出し行に列名、薄い灰の見出し）。

    列は R・クラス・距離・馬場・タイム・前後3F・ペース・馬番（勝ち馬）・脚質（勝ち馬）・上がり（勝ち馬）・映像。
    レース名はマウスを乗せると出す。馬ごとの結果がまだ無いレース（JRAのラップだけ）は、
    勝ち馬の馬番・脚質・上がりが「—」になる。日ごとにタブで分けて渡される前提なので日の区切りの行は置かず、
    その日は変わらないクッション値（含水率）は、表の上に1行で出す。
    """
    if not rows:
        return ""
    columns = _columns(rows[0].get("surface"))
    note = _hardness_note(rows)
    head = "".join(f"<th class='{cls}'>{escape(label)}</th>" for cls, label in columns)
    lines = [
        f"{note}<div class='best-times-wrap meeting-wrap'><table class='best-times mt-table'>"
        f"<thead><tr>{head}</tr></thead><tbody>"
    ]
    for row in rows:
        name = escape(row.get("race_name") or "")
        # ペース記号は馬柱・持ちタイムと同じ判定（レース全体の前半3F・後半3F）
        pace = pace_mark({**row, "race_first_3f": row.get("first_3f"), "race_last_3f": row.get("last_3f")})
        lines.append(
            f"<tr title='{name}'>"
            f"<td class='mt-no'>{row.get('race_no') or DASH}R</td>"
            f"<td class='mt-class'>{escape(class_short(row))}</td>"
            # 距離は「1400m」。内回り・外回りはマウスを乗せると出す
            f"<td class='mt-course' title='{escape(course_label(row))}'>{escape(_distance_text(row))}</td>"
            f"<td class='mt-going'>{escape(row.get('going') or DASH)}</td>"
            f"<td class='mt-time'>{escape(format_race_time(row.get('time_sec')))}</td>"
            f"<td class='mt-split'>{escape(split_label(row))}</td>"
            f"<td class='mt-pace'>{pace or DASH}</td>"
            f"<td class='mt-waku'>{_winner_badge(row)}</td>"
            f"<td class='mt-style'>{_style_cell(row)}</td>"
            f"<td class='mt-num'>{escape(_winner_last_3f(row))}</td>"
            # いちばん右にJRA公式のレース結果ページ（レース映像）へのリンク
            f"<td class='mt-detail'>{jra_race_link(row, 'mt-link')}</td></tr>"
        )
    lines.append("</tbody></table></div>")
    return "".join(lines)


def render_meeting_cards(rows: list[dict]) -> str:
    """スマホの開催の勝ちタイム。表（`render_meeting`）と同じ中身を、1レース1枚のカード型で縦に並べる
    （docs/design_handoff/競馬新聞 Mobile.dc.html の winRows）。

    1行目: R ・クラス ・距離 ・レース名
    2行目: 勝ち馬の馬番・馬名 ／ タイム
    3行目: 馬場 ／ 硬さ ／ 脚質　　上り ／ 前後3F ペース
    """
    if not rows:
        return ""
    hardness = hardness_head(rows[0].get("surface"))
    lines = ["<div class='bt-cards mt-cards'>"]
    for row in rows:
        pace = pace_mark({**row, "race_first_3f": row.get("first_3f"), "race_last_3f": row.get("last_3f")})
        split = split_label(row) or DASH
        where = " ／ ".join([
            escape(row.get("going") or DASH), f"{hardness}{escape(hardness_text(row))}", _style_cell(row),
        ])
        lines.append(
            "<div class='mt-card'>"
            f"<div class='mt-card-head'><b class='mt-card-no'>{row.get('race_no') or DASH}R</b>"
            f"<b class='mt-card-class'>{escape(class_short(row))}</b>"
            f"<span class='mt-card-dist'>{_distance_text(row)}</span>"
            f"<span class='mt-card-race'>{escape(row.get('race_name') or '')}</span></div>"
            "<div class='bt-card'>"
            # 勝ち馬がまだ取り込めていないレースは、馬番の札を出さずに「—」1つだけ
            f"<b class='bt-card-name'>{_winner_badge(row) if row.get('winner_umaban') is not None else ''}"
            f"<span>{escape(row.get('winner_name') or DASH)}</span></b>"
            f"<b class='bt-card-time'>{escape(format_race_time(row.get('time_sec')))}</b>"
            f"<span class='bt-card-where'>{where}</span>"
            f"<span class='bt-card-run'>上{escape(_winner_last_3f(row))} ／ 前後3F {escape(split)} {pace}</span>"
            "</div></div>"
        )
    lines.append("</div>")
    return "".join(lines)


def days_without_winner(rows: list[dict]) -> list[str]:
    """勝ち馬の通過順位がまだ入っていない開催日（`YYYY-MM-DD`）。

    JRAから取り込み直す日を決めるのに使う。`keiba jra` はレース情報とラップしか
    入れていなかったため、古いDBでは当日・直近の開催で脚質が出せない。
    """
    missing = {
        row["race_date"] for row in rows
        # 勝ち馬の馬番も、JRAから取り込み直すと入る（2026-10 に足した列。古い取り込みには無い）
        if (not row.get("winner_corner") or row.get("winner_umaban") is None) and row.get("race_date")
    }
    return sorted(missing, reverse=True)
