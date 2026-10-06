"""開催の勝ちタイム一覧（コース図の下）。"""

from keiba_analysis.racing import meeting
from keiba_analysis.shared.style import RUNNING_STYLE_COLORS


def row(race_date="2026-09-20", race_no=11, **kwargs):
    base = {
        "race_date": race_date, "race_no": race_no, "surface": "turf",
        "distance_m": 1600, "course_detail": "外 C", "class_condition": "2勝クラス",
        "grade": None, "race_name": "テスト特別", "n_runners": 16,
        "going": "良", "cushion_value": 8.6, "dirt_moisture_goal": None,
        "time_sec": 92.6, "first_3f": 34.2, "last_3f": 34.5,
        "winner_corner": "1-1-1-1",
    }
    base.update(kwargs)
    return base


# --- 日ごとのまとめ -----------------------------------------------------------------


def test_races_are_grouped_by_day_newest_first():
    rows = [row("2026-09-20", 11), row("2026-09-20", 9), row("2026-09-19", 10)]
    days = meeting.group_by_day(rows)
    assert [d[0] for d in days] == ["9/20(日)", "9/19(土)"]
    assert [len(d[2]) for d in days] == [2, 1]


def test_the_day_heading_carries_the_hardness_of_the_track():
    """クッション値は日ごとの値なので、行ではなく日の見出しに出す。"""
    days = meeting.group_by_day([row(cushion_value=8.6)])
    assert days[0][1] == "ク8.6"
    dirt = meeting.group_by_day([
        row(surface="dirt", cushion_value=None, dirt_moisture_goal=7.7)
    ])
    assert dirt[0][1] == "含水7.7%"


def test_day_label_falls_back_to_the_raw_text():
    assert meeting.day_label({"race_date": "こわれた日付"}) == "こわれた日付"


# --- 1行の中身 ---------------------------------------------------------------------


def test_course_label_keeps_the_inner_outer_loop():
    """内回り・外回りで時計が違うので、距離だけにしない。"""
    assert meeting.course_label(row()) == "1600外"
    assert meeting.course_label(row(course_detail=None)) == "1600"
    assert meeting.course_label(row(distance_m=None)) == meeting.DASH


def test_split_label():
    assert meeting.split_label(row()) == "34.2-34.5"
    assert meeting.split_label(row(first_3f=None)) == ""


def test_the_table_shows_the_time_and_the_going_per_race():
    html = meeting.render_meeting([row(), row(race_no=9, going="稍重")])
    assert "1:32.6" in html                       # 92.6秒 → 1:32.6
    assert "34.2-34.5" in html
    assert "良" in html and "稍重" in html          # 馬場状態はレースごと
    assert "2勝" in html                           # クラスは短縮表記


def test_the_race_name_is_shown():
    """名前の付いたレースはレベルが伝わるので出す（余った幅をここが受け持つ）。"""
    html = meeting.render_meeting([row(race_name="道頓堀ステークス")])
    assert "道頓堀ステークス" in html


def test_the_winning_style_is_coloured():
    html = meeting.render_meeting([row(winner_corner="1-1-1-1")])
    assert "逃げ" in html and RUNNING_STYLE_COLORS["逃げ"] in html
    assert "勝ち馬の通過順位 1-1-1-1（16頭）" in html


def test_the_style_is_a_dash_until_the_result_is_imported():
    """`keiba jra` はラップしか入れていなかったので、通過順位が無い日がある。"""
    html = meeting.render_meeting([row(winner_corner=None)])
    assert "逃げ" not in html and "追込" not in html


def test_nothing_is_drawn_without_any_race():
    assert meeting.render_meeting([]) == ""
    assert meeting.group_by_day([]) == []


def test_race_names_are_escaped():
    html = meeting.render_meeting([row(race_name="<script>x</script>")])
    assert "<script>" not in html


# --- 取り込み直す日 -----------------------------------------------------------------


def test_days_without_a_winner_are_listed_newest_first():
    rows = [
        row("2026-09-20", 11, winner_corner=None),
        row("2026-09-20", 9, winner_corner=None),      # 同じ日は1つにまとめる
        row("2026-09-19", 10, winner_corner=None),
        row("2026-09-13", 11, winner_corner="3-3-3-3", winner_umaban=4),
    ]
    assert meeting.days_without_winner(rows) == ["2026-09-20", "2026-09-19"]


def test_no_days_to_fetch_when_every_winner_is_known():
    assert meeting.days_without_winner([row(winner_umaban=4)]) == []


def test_a_day_without_the_winner_number_is_fetched_again():
    """勝ち馬の馬番・馬名・上りは 2026-10 に足した列なので、古い取り込みの日は取り込み直す。"""
    assert meeting.days_without_winner([row(winner_umaban=None)]) == ["2026-09-20"]


# --- 日ごとのタブ -------------------------------------------------------------------


def _days(dates):
    return meeting.split_days([row(race_date=d) for d in dates])


def test_each_day_gets_its_own_tab():
    """タブは日ごと。開催週と前週を1つの表に混ぜない。

    馬場は日で変わるので、日をまたいで時計を見比べてしまわないようにする。
    """
    days = _days(["2026-09-26", "2026-09-20", "2026-09-19"])
    assert [label for label, _ in days] == ["9/26(土)", "9/20(日)", "9/19(土)"]
    assert [len(d) for _, d in days] == [1, 1, 1]


def test_the_newest_day_comes_first():
    """既定で開くのはいちばん左＝いちばん新しい日。"""
    assert [label for label, _ in _days(["2026-09-20", "2026-09-13"])] == \
        ["9/20(日)", "9/13(日)"]


def test_the_races_of_a_day_stay_together():
    """同じ日のレースは1つのタブにまとまる。"""
    days = _days(["2026-09-20", "2026-09-20", "2026-09-19"])
    assert [label for label, _ in days] == ["9/20(日)", "9/19(土)"]
    assert [len(d) for _, d in days] == [2, 1]


def test_one_day_and_no_day_do_not_break():
    assert [label for label, _ in _days(["2026-09-26"])] == ["9/26(土)"]
    assert meeting.split_days([]) == []


def test_the_splits_have_no_brackets():
    """前半3F-後半3F はカッコ無しで出す。"""
    assert meeting.split_label(row()) == "34.2-34.5"
    # 日付の見出し「9/20(日)」のカッコは別物なので、前後3Fのマスだけを見る
    cell = meeting.render_meeting([row()]).split("<td class='mt-split'>")[1].split("</td>")[0]
    assert cell == "34.2-34.5"


# --- 詳細（JRA結果ページへのリンク） ---------------------------------------------------


def test_each_race_links_to_the_jra_result_page():
    html = meeting.render_meeting([row(jra_cname="pw01sde01/DC")])
    cell = html.split("<td class='mt-detail'>")[1].split("</td>")[0]
    assert "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde01/DC" in cell
    assert "<svg" in cell


def test_a_race_without_a_token_shows_no_icon():
    html = meeting.render_meeting([row()])              # jra_cname 無し
    cell = html.split("<td class='mt-detail'>")[1].split("</td>")[0]
    assert cell == ""


def test_every_column_has_a_heading():
    """持ちタイムと同じく、見出し行に列名を出す（列を足したら見出しも足すこと）。"""
    html = meeting.render_meeting([row()])
    head = html.split("<thead>")[1].split("</thead>")[0]
    body = html.split("<tbody>")[1].split("</tr>")[0]
    assert head.count("<th") == body.count("<td") == 14
    for label in ("R", "馬番", "馬名", "タイム", "上り", "前後3F", "ペース", "脚質", "馬場", "ク"):
        assert f">{label}</th>" in head


def test_the_winner_last_3f_and_the_pace_are_shown():
    """持ちタイムと同じく、上り（勝ち馬）とペース記号を出す。"""
    html = meeting.render_meeting([row(winner_last_3f=33.48, first_3f=36.0, last_3f=34.0)])
    cell = html.split("<td class='mt-num'>")[1].split("</td>")[0]
    assert cell == "33.5"
    pace = html.split("<td class='mt-pace'>")[1].split("</td>")[0]
    assert "pg-pace" in pace and ">S<" in pace          # 前半が遅い＝スロー


def test_the_winner_last_3f_is_a_dash_without_results():
    """JRAのラップだけ取り込んだレース（馬ごとの結果がまだ無い）は「—」。"""
    html = meeting.render_meeting([row()])
    assert html.split("<td class='mt-num'>")[1].split("</td>")[0] == "—"


def test_the_hardness_is_a_column_like_the_best_times():
    html = meeting.render_meeting([row(cushion_value=8.6)])
    assert html.split("<td class='mt-hard'>")[1].split("</td>")[0] == "8.6"
    dirt = meeting.render_meeting([row(surface="dirt", cushion_value=None, dirt_moisture_goal=7.7)])
    assert ">含水</th>" in dirt and "<td class='mt-hard'>7.7</td>" in dirt


def test_the_winner_number_and_name_are_shown():
    """持ちタイムと同じく、馬番（枠の色）と馬名を出す。開催の表では勝ち馬。"""
    html = meeting.render_meeting([row(winner_umaban=7, winner_waku=4, winner_name="ジョスラン")])
    cell = html.split("<td class='mt-waku'>")[1].split("</td>")[0]
    assert ">7</span>" in cell and "background:" in cell
    assert "ジョスラン" in html.split("<td class='mt-horse'>")[1].split("</td>")[0]


def test_the_winner_is_a_dash_without_results():
    html = meeting.render_meeting([row()])
    assert html.split("<td class='mt-waku'>")[1].split("</td>")[0] == "—"
    assert html.split("<td class='mt-horse'>")[1].split("</td>")[0] == "<div>—</div>"
