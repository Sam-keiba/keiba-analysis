"""過去走の各項目を表示用の文字列に整える関数群。

ページ上の過去走ミニ一覧（past_grid.py）から使う。表示そのものは持たない。
"""

from __future__ import annotations

import re
import unicodedata
from html import escape
from urllib.parse import quote

from keiba_data import config

DASH = "—"

# JRA公式のレース結果ページへのリンクに出すフィルムのアイコン。
# 馬柱（past_grid.py）と開催の勝ちタイム（meeting.py）の両方から使う。
FILM_SVG = (
    '<svg viewBox="0 0 18 13" width="18" height="13" aria-hidden="true">'
    '<rect x="0.6" y="0.6" width="16.8" height="11.8" rx="2" fill="#ffffff" stroke="currentColor"'
    ' stroke-width="1.2"/>'
    '<path d="M4.4 1v11M13.6 1v11" stroke="currentColor" stroke-width="1.1"/>'
    '<path d="M7.2 3.9 11.2 6.5 7.2 9.1z" fill="currentColor"/>'
    "</svg>"
)
JRA_LINK_TITLE = "JRA公式のレース結果ページ（レース映像が見られます）"


def jra_race_link(row: dict, css_class: str) -> str:
    """JRA公式のレース結果ページへのリンク（フィルムのアイコン）。

    JRAの動画プレイヤーは**JRAのサイト以外から開くと再生できない**ので、直リンクはせず
    公式のレース結果ページへ飛ばし、そこの「レース映像」から見てもらう。
    リンクのトークン（`jra_cname`）が無いレースには何も出さない。
    """
    cname = row.get("jra_cname")
    if not cname:
        return ""
    href = config.JRA_RACE_PAGE_URL.format(cname=quote(str(cname), safe="/"))
    return (
        f'<a class="{css_class}" href="{escape(href)}" target="_blank" rel="noopener" '
        f'title="{JRA_LINK_TITLE}">{FILM_SVG}</a>'
    )

# クラスの短縮表記（表記ゆれは NFKC で正規化してから引く）。
# 出馬表ページ由来の値は全角（`１勝クラス`）で入っているため。
CLASS_SHORT = {
    "オープン": "OP",
    "3勝クラス": "3勝",
    "2勝クラス": "2勝",
    "1勝クラス": "1勝",
    "未勝利": "未勝",
    "新馬": "新馬",
}
_RACE_NUMBER_PREFIX = re.compile(r"^第\d+回")
# レース名の末尾に付くクラス・グレードの付記（クラスは別に出すので落とす）
_CLASS_SUFFIX = re.compile(r"\((?:OP|L|J?G[IV]+|[1-3]勝)\)\s*$")
NAME_LIMIT = 9  # 凡例に出すレース名の上限（これを超えたら…で省略）

SURFACE_SHORT = {"turf": "芝", "dirt": "ダ", "jump": "障"}
DIRECTION_SHORT = {"right": "右", "left": "左", "straight": "直"}

# --- 騎手名から名字を取り出すための表（暫定）---------------------------------
# DBの騎手名はnetkeibaの短縮名（最大4文字）で入っている。例: 横山典弘 / 佐々木大 / 岡部誠。
# 「名字2文字＋名前」が大多数なので先頭2文字を既定とし、そうでないものだけ表で持つ。
# 現役騎手が増えたら足りなくなる可能性があるので、後から見直す前提の暫定対応。
LONG_SURNAMES = ("佐々木", "五十嵐", "長谷川", "小野寺", "武士沢", "大久保", "小笠原")
ONE_CHAR_SURNAMES = ("森", "原", "幸", "伴", "黛", "泉", "京", "堀")


def format_date(value: str | None) -> str:
    """'2026-08-22' を '26/08/22' にする。"""
    if not value or len(value) != 10:
        return DASH
    return f"{value[2:4]}/{value[5:7]}/{value[8:10]}"


def class_short(run: dict) -> str:
    """クラスの短縮表記。重賞はグレード（`GII`）、平場は `1勝` `未勝` `新馬` `OP` など。

    1. `grade` があればそれ
    2. `class_condition`（全角が混ざるので NFKC 正規化。`牝`・`見習騎手` の付記は前方一致で落とす）
    3. どちらも無ければレース名から拾う（`2歳未勝利` → `未勝`）
    分からなければ空文字。
    """
    grade = run.get("grade")
    if grade:
        return grade
    condition = unicodedata.normalize("NFKC", run.get("class_condition") or "")
    name = unicodedata.normalize("NFKC", run.get("race_name") or "")
    for full, short in CLASS_SHORT.items():
        if condition.startswith(full) or (not condition and full in name):
            return short
    return ""


def short_race_label(run: dict) -> str:
    """凡例に出す「クラス＋レース名」。幅が限られるので短くする。

    - 条件戦（レース名がクラスそのもの。`3歳以上1勝クラス` `2歳未勝利`）は
      **クラスだけ**（`1勝` `未勝`）。DBの7割はこれなので、凡例がぐっと短くなる
    - 名前のあるレースは `クラス 名前`（`3勝 オールスターJ第2戦` / `GII 関西TVローズS`）。
      名前に付く `(3勝)` の付記と `第NN回` は落とし、長い名前は `…` で省略する
    """
    label = class_short(run)
    name = _CLASS_SUFFIX.sub("", _RACE_NUMBER_PREFIX.sub("", run.get("race_name") or "")).strip()
    if not name:
        return label
    normalized = unicodedata.normalize("NFKC", name)
    if any(word in normalized for word in CLASS_SHORT):  # 名前がクラスの言い回しそのもの
        return label or name
    if len(name) > NAME_LIMIT:
        name = name[: NAME_LIMIT - 1] + "…"
    return f"{label} {name}" if label else name


def format_date_short(value: str | None) -> str:
    """'2026-08-22' を '08/22' にする（凡例のように幅が無いところ用）。"""
    if not value or len(value) != 10:
        return DASH
    return f"{value[5:7]}/{value[8:10]}"


def format_condition(run: dict, with_course_setting: bool = False) -> str:
    """条件表記。

    with_course_setting=False: 「芝2000m 右 外」（グラフの凡例などで使う短い形）
    with_course_setting=True : 「芝2000m（右・外・Bコース）」（過去走テーブル用）
        使用コース（A/B/C）はJRA公式PDF由来の芝の設定。ダートや不明の場合は付けない。
    """
    course = (
        f"{SURFACE_SHORT.get(run.get('surface') or '', '')}{run['distance_m']}m"
        if run.get("distance_m")
        else DASH
    )
    details = [
        DIRECTION_SHORT.get(run.get("direction") or ""),
        run.get("course_detail") or "",
    ]
    if with_course_setting and run.get("surface") == "turf" and run.get("course_setting"):
        details.append(f"{run['course_setting']}コース")
    details = [d for d in details if d]
    if not details:
        return course
    if with_course_setting:
        return f"{course}（{'・'.join(details)}）"
    return " ".join([course, *details])


def short_jockey_name(name: str | None) -> str:
    """騎手名から名字だけを取り出す（過去走テーブル用）。

    カタカナ表記（外国人騎手）はそのまま返す。
    """
    name = (name or "").strip()
    if not name:
        return DASH
    if any("ァ" <= ch <= "ヶ" or ch in "ー・" for ch in name):
        return name
    for surname in LONG_SURNAMES:
        if name.startswith(surname):
            return surname
    if len(name) == 3 and name[0] in ONE_CHAR_SURNAMES:
        return name[0]
    return name[:2] if len(name) > 2 else name


def format_going(run: dict) -> str:
    """馬場状態とクッション値（ダートは含水率）をまとめる。

    使用コース（A/B/C）は条件表記（format_condition）側に出すので、ここには入れない。
    """
    surface = run.get("surface")
    if surface == "dirt":
        going = run.get("going_dirt")
        moisture = run.get("dirt_moisture_goal")
        extra = f"含水{moisture}%" if moisture is not None else None
    else:
        going = run.get("going_turf") or run.get("going_dirt")
        cushion = run.get("cushion_value")
        extra = f"ク{cushion}" if cushion is not None else None
    if going and extra:
        return f"{going}／{extra}"
    return going or extra or DASH


def pace_mark(run: dict) -> str:
    """ペース記号（S/M/H）の小さなバッジ。馬柱と持ちタイムで同じものを使う。

    判定は前半3F・後半3Fの差からの**暫定**なので、tooltipにもそう書く（pace.py 参照）。
    ラップが手元に無い走（`race_first_3f` が無い）は何も出さない。
    """
    from keiba_analysis.racing import pace
    from keiba_analysis.shared.style import PACE_COLORS

    mark = pace.classify_run(run)
    if mark is None:
        return ""
    tooltip = escape(pace.description(run.get("race_first_3f"), run.get("race_last_3f")))
    return (f'<span class="pg-pace" style="background:{PACE_COLORS[mark]}" '
            f'title="{tooltip}">{mark}</span>')


def cushion_label(run: dict) -> str:
    """馬場の硬さだけを短く返す（芝は `ク8.1`、ダートは `含水5.2%`）。

    グラフの凡例のように場所が無いところで使う。
    馬場状態（良/稍重）も一緒に出したいときは format_going を使う。
    """
    if run.get("surface") == "dirt":
        moisture = run.get("dirt_moisture_goal")
        return f"含水{moisture}%" if moisture is not None else ""
    cushion = run.get("cushion_value")
    return f"ク{cushion}" if cushion is not None else ""


def format_field_position(run: dict) -> str:
    """出走頭数と馬番を netkeiba の書き方（`15頭7番`）で返す。

    馬番が無い（枠順確定前のデータ等）場合は `15頭`、頭数も無ければ `—`。
    """
    n_runners, umaban = run.get("n_runners"), run.get("umaban")
    if not n_runners:
        return f"{umaban}番" if umaban else DASH
    return f"{n_runners}頭{umaban}番" if umaban else f"{n_runners}頭"


def format_finish(run: dict) -> str:
    """着順を短く返す（`1着`）。取消・除外・中止はその表記を出す。

    頭数・馬番は format_field_position 側に出すので、ここには含めない。
    """
    if run.get("finish_status") and run.get("finish_position") is None:
        return run["finish_status"]
    position = run.get("finish_position")
    if position is None:
        return DASH
    label = f"{position}着"
    return f"{label}({run['finish_status']})" if run.get("finish_status") else label


def format_popularity(run: dict) -> str:
    """単勝人気（`6人気`）。人気が無い（未確定・取消など）場合は空文字。"""
    popularity = run.get("popularity")
    return f"{popularity}人気" if popularity else ""


def format_first_3f(run: dict) -> str:
    """レースの前半3F（`36.3`）。ラップが無いレース（障害など）は「—」。"""
    value = run.get("race_first_3f")
    return f"{value:.1f}" if value is not None else DASH


def format_time_diff(run: dict) -> str:
    """勝ち馬とのタイム差（`+0.3`）。

    netkeibaの馬柱と同じく、**自分が勝ったレースでは2着馬との差**を出すので、
    その場合は負の値（`-0.2`）になる。同着は `0.0`。
    どちらかのタイムが無ければ「—」。
    """
    own, rival = run.get("time_sec"), run.get("rival_time_sec")
    if own is None or rival is None:
        return DASH
    diff = round(own - rival, 1)
    return "0.0" if diff == 0 else f"{diff:+.1f}"  # 同着に「+0.0」と出さない


def format_race_name(run: dict) -> str:
    name = run.get("race_name") or DASH
    return f"{name}({run['grade']})" if run.get("grade") else name


def format_weight(run: dict) -> str:
    weight = run.get("horse_weight")
    if not weight:
        return DASH
    diff = run.get("weight_diff")
    return f"{weight}({diff:+d})" if diff is not None else str(weight)
