"""コース図の下に出す「開催の勝ちタイム」の表。

前週と開催週の、そのレースより前に行われた同じ馬場種別のレースを、**日ごとのタブ**に分けて並べる。
馬場がどう出ているか（時計が速いか、前が残るか）を読むための材料。

クッション値・含水率は**日ごと**の値なので日の見出しに置き、馬場状態は雨で
日中に変わりうるので行ごとに出す。集計は data.get_meeting_results。
"""

from __future__ import annotations

from datetime import date
from html import escape

from keiba_analysis.past_runs import class_short, cushion_label, jra_race_link  # TODO(migration): past_runs.py not yet in keiba-analysis; currently slated for keiba-app. Needs resolution.
from keiba_analysis.racing.race_forecast import format_race_time
from keiba_analysis.racing.running_style import classify_run
from keiba_analysis.style import RUNNING_STYLE_COLORS  # TODO(migration): style.py not yet in keiba-analysis; currently slated for keiba-app. Needs resolution.

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


def render_meeting(rows: list[dict]) -> str:
    """開催の勝ちタイムの表（日ごとに区切る）。"""
    if not rows:
        return ""
    lines = ["<div class='meeting-wrap'><table class='meeting'>"]
    for label, hardness, races in group_by_day(rows):
        head = escape(label) + (f"　{escape(hardness)}" if hardness else "")
        lines.append(f"<tr class='mt-day'><td colspan='9'>{head}</td></tr>")
        for row in races:
            name = escape(row.get("race_name") or "")
            lines.append(
                f"<tr title='{name}'>"
                f"<td class='mt-no'>{row.get('race_no') or DASH}R</td>"
                f"<td class='mt-course'>{escape(course_label(row))}</td>"
                f"<td class='mt-class'>{escape(class_short(row))}</td>"
                f"<td class='mt-name'><div>{name}</div></td>"
                f"<td class='mt-time'>{escape(format_race_time(row.get('time_sec')))}</td>"
                f"<td class='mt-split'>{escape(split_label(row))}</td>"
                f"<td class='mt-style'>{_style_cell(row)}</td>"
                f"<td class='mt-going'>{escape(row.get('going') or DASH)}</td>"
                # いちばん右にJRA公式のレース結果ページ（レース映像）へのリンク
                f"<td class='mt-detail'>{jra_race_link(row, 'mt-link')}</td></tr>"
            )
    lines.append("</table></div>")
    return "".join(lines)


def days_without_winner(rows: list[dict]) -> list[str]:
    """勝ち馬の通過順位がまだ入っていない開催日（`YYYY-MM-DD`）。

    JRAから取り込み直す日を決めるのに使う。`keiba jra` はレース情報とラップしか
    入れていなかったため、古いDBでは当日・直近の開催で脚質が出せない。
    """
    missing = {
        row["race_date"] for row in rows
        if not row.get("winner_corner") and row.get("race_date")
    }
    return sorted(missing, reverse=True)
