"""コース図の下に出す「持ちタイム」のタブと表。

netkeibaの持ちタイムランキングと同じ考え方で、**その条件でのいちばん速い走**を
タイム順に並べる。距離が違うとタイムは比べられないので、**距離ごとにタブを分ける**。

タブは**そのレースの距離**を先頭に置き、あとは近い距離を**距離の昇順**で並べる
（例: ダ2000 ／ ダ1800 ／ ダ1900 ／ ダ2100）。
ダートは**100mきざみ**で距離が設定されているので前後200m以内をぜんぶ出し、
200mきざみが基本の芝は前後200mの2つだけにする。

どのタブも**全場ぶん**が対象（競馬場では絞らない）。どの競馬場で出した時計かは、
表の「場」の列に1走ずつ出る。レースの前後3Fとペース記号も並べて、
**どんな流れで出た時計か**が分かるようにする。

集計は data.get_best_times、色は style.py のものを使い回す。表は自前のHTMLで描く
（枠色を付けたい／馬名を…で省略したいので、Streamlitの表ウィジェットでは足りない）。
"""

from __future__ import annotations

from html import escape

from keiba_analysis.racing.past_runs import SURFACE_SHORT, pace_mark
from keiba_analysis.racing.race_forecast import format_race_time
from keiba_analysis.racing.running_style import classify_run
from keiba_analysis.shared.style import RUNNING_STYLE_COLORS, waku_color

PLACED_COLOR = "#189a54"

DASH = "—"
NEIGHBOUR_DISTANCE_M = 200  # 前後にいくつ離れた距離まで見るか


def neighbour_distances(
    surface: str, distance: int, available: list[int] | None = None
) -> list[int]:
    """タブに出す「近い距離」を昇順で返す（その距離自身は含まない）。

    **ダートは100mきざみ**（1700・1900・2100…）で距離が設定されているので、
    前後200m以内をぜんぶ出す。`available`（DBに実際にある距離。
    `data.get_nearby_distances` の結果）を渡すと、それをそのまま使う:
    - 福島ダ1150 のような**100mきざみに乗らない距離**も拾える
    - JRAに無い距離（ダ2200など）を空振りで引きに行かずに済む
    渡さないときは ±100 / ±200 の決め打ちにする（DBが要らないので、テストから呼べる）。

    芝と障害は200mきざみが基本なので、今までどおり ±200m の2つだけ。
    """
    if surface == "dirt":
        if available is not None:
            return sorted(
                d for d in available
                if d != distance and abs(d - distance) <= NEIGHBOUR_DISTANCE_M and d > 0
            )
        deltas = (-NEIGHBOUR_DISTANCE_M, -100, 100, NEIGHBOUR_DISTANCE_M)
    else:
        deltas = (-NEIGHBOUR_DISTANCE_M, NEIGHBOUR_DISTANCE_M)
    return [distance + delta for delta in deltas if distance + delta > 0]


def tab_conditions(
    race: dict, available: list[int] | None = None
) -> list[tuple[str, int]]:
    """タブの条件を (見出し, 距離) で返す。

    **そのレースの距離**を先頭に置き、あとは近い距離を距離の昇順で並べる。
    先頭を今日の距離にするのは、画面が最初に開くのがいちばん左のタブだから。
    `available` は `neighbour_distances` へそのまま渡す。
    距離や馬場が分からないレースでは空。

    競馬場では絞らない（どの競馬場の時計かは表の「場・馬場」の列に出る）。
    """
    surface, distance = race.get("surface"), race.get("distance_m")
    if not surface or not distance:
        return []
    short = SURFACE_SHORT.get(surface, "")
    distances = [distance, *neighbour_distances(surface, distance, available)]
    return [(f"{short}{d}", d) for d in distances]


def _waku_badge(entry: dict) -> str:
    background, color = waku_color(entry.get("waku"))
    label = escape(str(entry.get("umaban") or DASH))
    return f'<span class="waku" style="background:{background};color:{color}">{label}</span>'


def _finish_cell(row: dict) -> str:
    position = row.get("finish_position")
    if not position:
        return DASH
    text = f"{position}着"
    # 3着以内は緑の太字（docs/design_handoff の持ちタイム。着順ごとに色を変えない）
    if position > 3:
        return escape(text)
    return f'<span style="color:{PLACED_COLOR};font-weight:700">{escape(text)}</span>'


def _style_cell(row: dict) -> str:
    """その走の脚質。馬柱の左端に出す「その馬の脚質」（直近10走の多数決）とは別で、
    **この1走の通過順位**から決める。通過順位が無い走（障害・中止など）は「—」。
    """
    style = classify_run(row.get("corner_passing"), row.get("n_runners"))
    if style is None:
        return DASH
    color = RUNNING_STYLE_COLORS.get(style, "#6b716b")
    tooltip = escape(f"通過順位 {row.get('corner_passing')}（{row.get('n_runners')}頭）から判定")
    return f'<span style="color:{color};font-weight:700" title="{tooltip}">{escape(style)}</span>'


def splits_label(row: dict) -> str:
    """`34.2-34.5`。**レース全体**の前半3F-後半3F（その馬の上りとは別物）。

    キーが馬柱と同じ `race_first_3f` / `race_last_3f` なので、ペース記号
    （`past_runs.pace_mark`）もそのまま使える。ラップが手元に無い走は「—」。
    """
    first, last = row.get("race_first_3f"), row.get("race_last_3f")
    if first is None or last is None:
        return DASH
    return f"{first:.1f}-{last:.1f}"


def hardness_head(surface: str | None) -> str:
    """馬場の硬さの列の見出し。芝はクッション値（`ク`）、ダートは含水率。

    列が狭いので短く出す（`クッション` だと見出しだけで列がはみ出す）。
    """
    return "含水" if surface == "dirt" else "ク"


def hardness_text(row: dict) -> str:
    """馬場の硬さ（数字だけ）。見出しに単位を出すので `ク` や `%` は付けない。"""
    value = row.get("cushion_value")
    if (row.get("surface") or "") == "dirt":
        value = row.get("dirt_moisture_goal")
    return DASH if value is None else f"{value:.1f}"


def _row_title(row: dict) -> str:
    """行のマウスオーバー。列から外した日付はここに残す。"""
    date = (row.get("race_date") or "").replace("-", "/")
    return escape(f"{date} {row.get('venue_name') or ''}".strip())


def render_best_times(entries: list[dict], rows: list[dict], surface: str | None = None) -> str:
    """持ちタイムの表。記録がある馬だけを速い順に並べる。

    列は 馬番・馬名・着順・タイム・上り・前後3F・ペース・脚質・開催・馬場・硬さ。
    着順を前に置くのは「何着のときの時計か」を先に見たいから。
    **開催と馬場と硬さは別々のマス**にする（まとめると見比べにくいため）。
    `surface` は硬さの列の見出しを決めるのに使う（タブが馬場ごとなので混ざらない）。

    記録が無い馬は表に出さず、呼び出し側が `horses_without_record()` で名前を出す。
    """
    by_horse = {e.get("horse_id"): e for e in entries}
    if not rows:
        return ""
    lines = [
        # 列幅は table-layout: fixed で決まるので、見出し側にも同じクラスを付ける
        "<div class='best-times-wrap'><table class='best-times'>"
        "<thead><tr><th class='bt-waku'>馬番</th><th class='bt-name'>馬名</th>"
        "<th class='bt-finish'>着順</th><th class='bt-time'>タイム</th>"
        "<th class='bt-num'>上り</th><th class='bt-split'>前後3F</th>"
        "<th class='bt-pace'>ペース</th><th class='bt-style'>脚質</th>"
        "<th class='bt-venue'>開催</th><th class='bt-going'>馬場</th>"
        f"<th class='bt-hard'>{escape(hardness_head(surface))}</th>"
        "</tr></thead><tbody>"
    ]
    for row in rows:
        entry = by_horse.get(row.get("horse_id")) or {}
        name = escape(entry.get("horse_name") or DASH)
        # 上りは**その馬自身**の値。小数1桁にそろえる（生の値だと 33.599999… と出る）
        last_3f = row.get("last_3f")
        last_3f_text = DASH if last_3f is None else f"{float(last_3f):.1f}"
        lines.append(
            f"<tr title='{_row_title(row)}'><td class='bt-waku'>{_waku_badge(entry)}</td>"
            f"<td class='bt-name'><div title='{name}'>{name}</div></td>"
            f"<td class='bt-finish'>{_finish_cell(row)}</td>"
            f"<td class='bt-time'>{escape(format_race_time(row.get('time_sec')))}</td>"
            f"<td class='bt-num'>{last_3f_text}</td>"
            f"<td class='bt-split'>{escape(splits_label(row))}</td>"
            f"<td class='bt-pace'>{pace_mark(row) or DASH}</td>"
            f"<td class='bt-style'>{_style_cell(row)}</td>"
            f"<td class='bt-venue'>{escape(row.get('venue_name') or DASH)}</td>"
            f"<td class='bt-going'>{escape(row.get('going') or DASH)}</td>"
            f"<td class='bt-hard'>{escape(hardness_text(row))}</td></tr>"
        )
    lines.append("</tbody></table></div>")
    return "".join(lines)


def render_best_time_cards(entries: list[dict], rows: list[dict], surface: str | None = None) -> str:
    """スマホの持ちタイム。表（`render_best_times`）と同じ中身を、1頭1行のカード型で縦に並べる。

    1行目: 馬番・馬名 ／ タイム
    2行目: 開催 ／ 馬場 ／ 硬さ ／ 脚質　　着順 ／ 上り ／ 前後3F ペース
    """
    by_horse = {e.get("horse_id"): e for e in entries}
    if not rows:
        return ""
    hardness = "含水" if surface == "dirt" else "ク"
    lines = ["<div class='bt-cards'>"]
    for row in rows:
        entry = by_horse.get(row.get("horse_id")) or {}
        name = escape(entry.get("horse_name") or DASH)
        last_3f = row.get("last_3f")
        last_3f_text = DASH if last_3f is None else f"{float(last_3f):.1f}"
        where = " ／ ".join([
            escape(row.get("venue_name") or DASH), escape(row.get("going") or DASH),
            f"{hardness}{escape(hardness_text(row))}", _style_cell(row),
        ])
        lines.append(
            f"<div class='bt-card' title='{_row_title(row)}'>"
            f"<b class='bt-card-name'>{_waku_badge(entry)}<span>{name}</span></b>"
            f"<b class='bt-card-time'>{escape(format_race_time(row.get('time_sec')))}</b>"
            f"<span class='bt-card-where'>{where}</span>"
            f"<span class='bt-card-run'>{_finish_cell(row)} ／ 上{last_3f_text} ／ "
            f"前後3F {escape(splits_label(row))} {pace_mark(row) or ''}</span></div>"
        )
    lines.append("</div>")
    return "".join(lines)


def horses_without_record(entries: list[dict], rows: list[dict]) -> list[str]:
    """その条件での記録が無い馬の名前（馬番順）。"""
    recorded = {r.get("horse_id") for r in rows}
    return [
        e.get("horse_name") or DASH
        for e in entries
        if e.get("horse_id") not in recorded
    ]
