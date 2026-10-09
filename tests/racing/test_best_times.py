"""持ちタイム（コース図の下のタブと表）。"""

from keiba_analysis.shared.style import RUNNING_STYLE_COLORS

from keiba_analysis.racing.best_times import (
    horses_without_record,
    neighbour_distances,
    render_best_time_cards,
    render_best_times,
    tab_conditions,
)


RACE = {"surface": "turf", "distance_m": 2400, "venue_code": "09", "venue_name": "阪神"}

ENTRIES = [
    {"horse_id": "h1", "horse_name": "ロブチェン", "umaban": 3, "waku": 2},
    {"horse_id": "h2", "horse_name": "アルトラムス", "umaban": 7, "waku": 4},
    {"horse_id": "h3", "horse_name": "ミライヘノツバサ", "umaban": 11, "waku": 6},
]

ROWS = [
    {"horse_id": "h1", "time_sec": 142.7, "last_3f": 33.2, "finish_position": 1,
     "race_date": "2026-05-31", "venue_name": "東京", "going": "良", "surface": "turf",
     "cushion_value": 9.4, "corner_passing": "1-1-1-1", "n_runners": 18,
     "race_first_3f": 34.2, "race_last_3f": 34.5},
    {"horse_id": "h2", "time_sec": 143.1, "last_3f": 34.0, "finish_position": 5,
     "race_date": "2026-04-12", "venue_name": "阪神", "going": "稍重", "surface": "turf",
     "cushion_value": 8.1, "corner_passing": "14-14-13-12", "n_runners": 16,
     "race_first_3f": 36.1, "race_last_3f": 36.1},
]


DIRT = {"surface": "dirt", "distance_m": 2000, "venue_code": "09", "venue_name": "阪神"}


def test_todays_distance_comes_first_and_the_rest_go_by_distance():
    """画面は**いちばん左のタブ**を最初に開くので、今日の距離を先頭に置く。

    競馬場では絞らないので、見出しに場の名前も「（全場）」も付けない。
    """
    assert tab_conditions(RACE) == [
        ("芝2400", 2400),
        ("芝2200", 2200),
        ("芝2600", 2600),
    ]


def test_no_tab_is_tied_to_one_racecourse():
    """場を絞った持ちタイムは使わない。どの場の時計かは表の「場・馬場」の列に出る。"""
    labels = [label for label, _ in tab_conditions(DIRT, [1800, 1900, 2100])]
    assert not any("（全場）" in label for label in labels)
    assert not any("阪神" in label for label in labels)


def test_dirt_fans_out_in_100m_steps():
    """ダートは1700・1900・2100のように100mきざみで距離が決まっている。

    例のレース（阪神ダ2000）なら 1800・1900・2100 の時計も並べて見たい。
    """
    assert tab_conditions(DIRT) == [
        ("ダ2000", 2000),
        ("ダ1800", 1800),
        ("ダ1900", 1900),
        ("ダ2100", 2100),
        ("ダ2200", 2200),
    ]


def test_dirt_uses_the_distances_that_really_exist():
    """JRAにダ2200は無いので、決め打ちで作らずDBにある距離から作る。"""
    conditions = tab_conditions(DIRT, [1800, 1900, 2100])
    assert conditions == [
        ("ダ2000", 2000), ("ダ1800", 1800), ("ダ1900", 1900), ("ダ2100", 2100),
    ]


def test_a_distance_that_is_not_a_round_100_is_picked_up_too():
    """福島ダ1150 のような距離は、100mきざみの決め打ちでは拾えない。"""
    conditions = tab_conditions(
        {**DIRT, "distance_m": 1200}, [1000, 1150, 1300, 1400]
    )
    assert [label for label, _ in conditions] == [
        "ダ1200", "ダ1000", "ダ1150", "ダ1300", "ダ1400",
    ]


def test_turf_keeps_to_200m_steps():
    """芝は200mきざみが基本なので、実在する距離を渡しても前後200mの2つだけ。"""
    conditions = tab_conditions(RACE, [2200, 2300, 2500, 2600])
    assert [distance for _, distance in conditions] == [2400, 2200, 2600]


def test_distances_further_than_200m_away_are_left_out():
    assert neighbour_distances("dirt", 2000, [1700, 1800, 2100, 2300]) == [1800, 2100]


def test_short_races_do_not_ask_for_a_negative_distance():
    conditions = tab_conditions({**RACE, "distance_m": 1200, "surface": "dirt"})
    assert [distance for _, distance in conditions] == [1200, 1000, 1100, 1300, 1400]
    assert conditions[1][0] == "ダ1000"
    # 100m のレースなら、0m や マイナスの距離のタブは作らない
    assert all(distance > 0 for _, distance in tab_conditions({**DIRT, "distance_m": 100}))


def test_no_tabs_without_a_distance():
    assert tab_conditions({"surface": "turf", "distance_m": None}) == []
    assert tab_conditions({"surface": None, "distance_m": 2000}, [1800]) == []


def test_table_shows_the_time_in_minutes_and_keeps_the_given_order():
    html = render_best_times(ENTRIES, ROWS)
    assert "2:22.7" in html and "2:23.1" in html          # 142.7秒 → 2:22.7
    assert html.index("ロブチェン") < html.index("アルトラムス")
    assert "33.2" in html


def test_each_run_shows_the_style_it_was_won_with():
    """脚質はその1走の通過順位から決める（馬柱の「その馬の脚質」とは別物）。"""
    html = render_best_times(ENTRIES, ROWS)
    assert "逃げ" in html and "追込" in html               # 1-1-1-1 と 14-14-13-12
    assert "通過順位 1-1-1-1（18頭）から判定" in html       # 何から決めたかを残す
    assert RUNNING_STYLE_COLORS["逃げ"] in html


def test_runs_without_a_corner_passing_show_a_dash():
    """障害や中止など、通過順位が無い走は脚質を出さない。"""
    rows = [{**ROWS[0], "corner_passing": None}]
    html = render_best_times(ENTRIES, rows)
    assert "逃げ" not in html and "追込" not in html


def _cells(html: str, css_class: str) -> list[str]:
    """その列のマスの中身（タグを外したもの）を上から順に返す。"""
    import re

    return [re.sub(r"<[^>]+>", "", c)
            for c in re.findall(rf"<td class='{css_class}'>(.*?)</td>", html)]


def test_the_place_the_going_and_the_hardness_are_separate_columns():
    """場・馬場・馬場の硬さは別々の列にする（まとめると見比べにくい）。"""
    html = render_best_times(ENTRIES, ROWS, "turf")
    assert _cells(html, "bt-venue") == ["東京", "阪神"]
    assert _cells(html, "bt-going") == ["良", "稍重"]
    assert _cells(html, "bt-hard") == ["9.4", "8.1"]
    assert "東京 良 ク9.4" not in html          # 1つのマスにまとめない


def test_the_hardness_column_follows_the_surface():
    """芝はクッション値、ダートは含水率。見出しで単位が分かるので数字だけ出す。"""
    assert "<th class='bt-hard'>ク</th>" in render_best_times(ENTRIES, ROWS, "turf")

    dirt = [{**ROWS[0], "surface": "dirt", "going": "重", "dirt_moisture_goal": 8.5,
             "cushion_value": None}]
    html = render_best_times(ENTRIES, dirt, "dirt")
    assert "<th class='bt-hard'>含水</th>" in html
    assert _cells(html, "bt-hard") == ["8.5"]

    # 取り込めていない日は「—」。行は消さない
    bare = [{**ROWS[0], "cushion_value": None}]
    assert _cells(render_best_times(ENTRIES, bare, "turf"), "bt-hard") == ["—"]
    assert _cells(render_best_times(ENTRIES, bare, "turf"), "bt-venue") == ["東京"]


def test_the_columns_are_in_the_order_you_read_them():
    """左から 馬名・着順・タイム・前後3F・ペース・脚質・上り・開催・馬場・硬さ。

    着順を前に置くのは「何着のときの時計か」を先に見たいから。
    """
    import re

    html = render_best_times(ENTRIES, ROWS, "turf")
    heads = [re.sub(r"<[^>]+>", "", h)
             for h in re.findall(r"<th[^>]*>(.*?)</th>", html)]
    assert heads == ["馬名", "着順", "タイム", "前後3F", "ペース", "脚質", "上り",
                     "開催", "馬場", "ク"]


def test_the_cells_follow_the_same_order_as_the_headings():
    """見出しと中身がずれていないこと（並べ替えで取り違えやすい）。"""
    import re

    html = render_best_times(ENTRIES, ROWS, "turf")
    first_row = html.split("<tbody>")[1].split("</tr>")[0]
    cells = [re.sub(r"<[^>]+>", "", c)
             for c in re.findall(r"<td[^>]*>(.*?)</td>", first_row)]
    assert cells == ["ロブチェン", "1着", "2:22.7", "34.2-34.5",
                     "M", "逃げ", "33.2", "東京", "良", "9.4"]


def test_the_pace_of_the_race_is_shown_next_to_the_time():
    """同じ時計でも、前が速かったのか上がり勝負かで意味が違う。

    前後3F（レース全体）とペース記号を出す。上りは**その馬自身**のままで別物。
    """
    html = render_best_times(ENTRIES, ROWS, "turf")
    assert _cells(html, "bt-split") == ["34.2-34.5", "36.1-36.1"]
    assert _cells(html, "bt-pace") == ["M", "M"]
    assert _cells(html, "bt-num") == ["33.2", "34.0"]        # 上りは馬自身の値


def test_a_run_without_laps_leaves_the_pace_empty():
    """ラップが手元に無い走は、前後3Fもペースも出さない（行は残す）。"""
    rows = [{**ROWS[0], "race_first_3f": None, "race_last_3f": None}]
    html = render_best_times(ENTRIES, rows, "turf")
    assert _cells(html, "bt-split") == ["—"]
    assert _cells(html, "bt-pace") == ["—"]
    assert "2:22.7" in html                                   # タイムはそのまま出る


def test_the_date_is_kept_in_the_tooltip_only():
    """日付は列から外したが、いつの時計かは行のマウスオーバーで分かるようにする。"""
    import re

    html = render_best_times(ENTRIES, ROWS)
    cells = re.findall(r"<td[^>]*>(.*?)</td>", html)
    assert not any("05/31" in c for c in cells)           # どのマスにも日付は出さない
    assert "2026/05/31 東京" in html                       # title には残す


def test_waku_colour_and_finish_colour():
    html = render_best_times(ENTRIES, ROWS)
    assert 'class="waku" style="background:#000' not in html   # 2枠は白地に黒
    assert "bt-waku" not in html                                # 馬番の列は無い
    assert "1着" in html and "#189a54" in html                  # 3着以内は緑（資料どおり）
    assert "5着" in html                                        # 4着以下は色を付けない


def test_horses_without_a_record_are_listed_separately():
    html = render_best_times(ENTRIES, ROWS)
    assert "ミライヘノツバサ" not in html
    assert horses_without_record(ENTRIES, ROWS) == ["ミライヘノツバサ"]


def test_nothing_is_drawn_without_any_record():
    assert render_best_times(ENTRIES, []) == ""
    assert len(horses_without_record(ENTRIES, [])) == 3


def test_horse_names_are_escaped():
    entries = [{"horse_id": "h1", "horse_name": "<script>x</script>", "umaban": 1, "waku": 1}]
    html = render_best_times(entries, [ROWS[0]])
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_missing_values_do_not_break_the_row():
    rows = [{"horse_id": "h1", "time_sec": 142.7}]
    html = render_best_times(ENTRIES, rows)
    assert "2:22.7" in html


def test_the_last_3f_is_rounded_to_one_decimal():
    """生の値をそのまま出すと `33.599999999999994` のように見えてしまう。"""
    rows = [{**ROWS[0], "last_3f": 33.3 + 0.3}]
    assert _cells(render_best_times(ENTRIES, rows, "turf"), "bt-num") == ["33.6"]


# --- スマホのカード型 ------------------------------------------------------------


def test_cards_show_the_same_runs_in_the_same_order():
    html = render_best_time_cards(ENTRIES, ROWS)
    assert html.count("class='bt-card'") == len(ROWS)
    assert html.index("ロブチェン") < html.index("アルトラムス")
    assert "2:22.7" in html and "上33.2" in html
    assert "逃げ" in html                                   # その1走の脚質


def test_cards_follow_the_surface_for_the_hardness():
    assert "ク" in render_best_time_cards(ENTRIES, ROWS, "turf")
    assert "含水" in render_best_time_cards(ENTRIES, ROWS, "dirt")
    assert render_best_time_cards(ENTRIES, []) == ""
