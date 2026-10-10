"""オッズの画面に渡す材料（`dashboard/odds.py`）。"""

from keiba_analysis.racing import odds
from keiba_data.scrapers import jra_odds


def entry(umaban, waku, name, **kwargs):
    base = {"umaban": umaban, "waku": waku, "horse_name": name}
    base.update(kwargs)
    return base


ENTRIES = [
    entry(1, 1, "レッドモンレーヴ"), entry(2, 1, "アイサンサン"),
    entry(3, 2, "ウインマーベル"), entry(4, 2, "ナムラクレア"),
]
ODDS = {
    "tansho": [
        {"combo": "1", "odds_low": 33.8, "odds_high": None},
        {"combo": "2", "odds_low": 4.2, "odds_high": None},
        {"combo": "3", "odds_low": 4.2, "odds_high": None},
        {"combo": "4", "odds_low": 2.1, "odds_high": None},
    ],
    "umaren": [{"combo": "1-2", "odds_low": 41.3, "odds_high": None}],
    "wide": [{"combo": "1-2", "odds_low": 12.8, "odds_high": 15.1}],
}
UPDATES = {
    "tansho": {"odds_label": "12時31分現在オッズ", "n_combos": 4, "fetched_at": "2026-09-26 12:32"},
    "umaren": {"odds_label": "最終オッズ", "n_combos": 1, "fetched_at": "2026-09-26 12:32"},
}


# --- オッズの見せ方 ---------------------------------------------------------------------


def test_a_single_number_and_a_range_are_written_differently():
    assert odds.format_odds(33.8) == "33.8"
    assert odds.format_odds(12.8, 15.1) == "12.8 - 15.1"


def test_a_combination_nobody_bet_on_shows_a_dash():
    assert odds.format_odds(None) == odds.DASH


# --- 人気 -------------------------------------------------------------------------------


def test_the_lowest_odds_is_the_first_favourite():
    ranks = odds.popularity({"1": 33.8, "2": 4.2, "3": 4.2, "4": 2.1})
    assert ranks["4"] == 1
    assert ranks["1"] == 3


def test_the_same_odds_share_the_same_rank():
    """同じオッズの馬は同じ人気にする（JRAの単勝オッズは同値がよくある）。"""
    ranks = odds.popularity({"1": 33.8, "2": 4.2, "3": 4.2, "4": 2.1})
    assert ranks["2"] == ranks["3"] == 2


def test_a_horse_without_odds_has_no_rank():
    assert odds.popularity({"1": None, "2": 3.0}) == {"2": 1}


# --- 馬と枠 -----------------------------------------------------------------------------


def test_each_horse_carries_its_frame_colour_and_win_odds():
    horses = odds.horses(ENTRIES, {"1": [33.8, None], "4": [2.1, None]})
    first = horses[0]
    assert (first["number"], first["name"], first["odds"]) == (1, "レッドモンレーヴ", 33.8)
    assert first["bg"] == "#ffffff"                     # 1枠は白
    assert horses[3]["pop"] == 1                        # 4番がいちばん人気


def test_horses_are_in_umaban_order_and_skip_the_undrawn():
    horses = odds.horses([entry(3, 2, "ウインマーベル"), entry(None, None, "未確定")], {})
    assert [h["number"] for h in horses] == [3]


def test_frames_gather_the_horses_so_the_doubles_make_sense():
    """枠連は枠に2頭いればゾロ目が買えるので、枠ごとの馬番を持たせる。"""
    got = odds.frames(ENTRIES)
    assert [f["number"] for f in got] == [1, 2]
    assert got[0]["umaban"] == [1, 2] and got[0]["name"] == "1・2"
    assert got[1]["bg"] == "#2b2b2b"                    # 2枠は黒


# --- コンポーネントに渡す中身 -------------------------------------------------------------


def test_every_bet_type_gets_a_tab_even_before_it_is_fetched():
    payload = odds.build_payload(ENTRIES, ODDS, UPDATES)
    assert [b["key"] for b in payload["betTypes"]] == [b.key for b in jra_odds.BET_TYPES]
    ready = {b["key"]: b["available"] for b in payload["betTypes"]}
    assert ready["tansho"] and ready["umaren"]
    assert not ready["sanrentan"]                       # まだ取り込んでいない


def test_the_payload_says_how_each_bet_type_works():
    """券種ごとの違い（頭数・着順・幅・枠番）はコンポーネントで使うので全部渡す。"""
    payload = odds.build_payload(ENTRIES, ODDS, UPDATES)
    by_key = {b["key"]: b for b in payload["betTypes"]}
    assert by_key["sanrentan"]["legs"] == 3 and by_key["sanrentan"]["ordered"]
    assert by_key["wide"]["ranged"] and not by_key["wide"]["ordered"]
    assert by_key["wakuren"]["byFrame"]


def test_the_odds_are_passed_as_a_lookup_table():
    payload = odds.build_payload(ENTRIES, ODDS, UPDATES)
    by_key = {b["key"]: b for b in payload["betTypes"]}
    assert by_key["umaren"]["odds"]["1-2"] == [41.3, None]
    assert by_key["wide"]["odds"]["1-2"] == [12.8, 15.1]   # 幅は上限も渡す
    assert by_key["umaren"]["count"] == 1


def test_the_timestamp_of_each_bet_type_comes_along():
    payload = odds.build_payload(ENTRIES, ODDS, UPDATES)
    by_key = {b["key"]: b for b in payload["betTypes"]}
    assert by_key["tansho"]["time"] == "12時31分現在オッズ"
    assert by_key["sanrentan"]["time"] is None


# --- タブと更新マーク -------------------------------------------------------------------


def test_tansho_and_fukusho_share_one_tab():
    """単勝と複勝はJRAでも1ページなので、画面でも1つのタブにまとめる。"""
    assert [t["label"] for t in odds.tabs()] == [
        "単勝・複勝", "枠連", "馬連", "ワイド", "馬単", "3連複", "3連単",
    ]
    assert odds.tabs()[0]["bets"] == ["tansho", "fukusho"]
    assert odds.tabs()[2]["bets"] == ["umaren"]


def test_the_fetch_of_a_tab_covers_all_of_its_bet_types():
    """タブのキーで取り込む券種が決まる（単勝を押したら複勝も入る）。"""
    assert [b.key for b in odds.fetch_order()] == [
        "tansho", "wakuren", "umaren", "wide", "umatan", "sanrenpuku", "sanrentan",
    ]
    assert odds.keys_for("tansho") == ["tansho", "fukusho"]
    assert odds.keys_for("umaren") == ["umaren"]
    assert odds.keys_for("fukusho") == []       # 単勝のタブに入っているので単体では無い
    assert odds.keys_for(None) == []


def test_the_update_mark_says_when_the_odds_are_from():
    """券種ごとのボタンの代わりに、各ページの中に出す更新マークの文字。"""
    assert odds.update_chip("12時31分現在オッズ") == "12:31現在"
    assert odds.update_chip("最終オッズ") == "最終オッズ"      # 時刻が無いときはそのまま
    assert odds.update_chip(None) == "未取得"


def test_each_tab_carries_its_own_update_mark():
    marks = {t["key"]: t["chip"] for t in odds.tabs(UPDATES)}
    assert marks["tansho"] == "12:31現在"
    assert marks["umaren"] == "最終オッズ"
    assert marks["sanrentan"] == "未取得"


def test_the_time_is_shortened_for_the_update_mark():
    assert odds.short_time("12時31分現在オッズ") == "12:31"
    assert odds.short_time("9時5分現在オッズ") == "9:05"
    assert odds.short_time("最終オッズ") == "最終"
    assert odds.short_time(None) == odds.DASH


def test_the_freshly_fetched_bet_type_is_handed_over_so_its_tab_opens():
    """取り込んだ券種が見えないと、取り込めたのか分からない。"""
    assert odds.build_payload(ENTRIES, ODDS, UPDATES, focus="umaren")["focus"] == "umaren"
    assert odds.build_payload(ENTRIES, ODDS, UPDATES)["focus"] is None


# --- 券種の色（買い目の見分け） -------------------------------------------------------------


def test_every_bet_type_has_its_own_colour():
    """買い目に何券種か積んだとき、帯とバッジの色で見分けられるようにする。"""
    from keiba_analysis.shared.style import BET_TYPE_COLORS

    colors = {b["key"]: b["color"] for b in odds.build_payload(ENTRIES, ODDS, UPDATES)["betTypes"]}
    assert set(colors) == {b.key for b in jra_odds.BET_TYPES}
    assert len(set(colors.values())) == len(colors)      # 隣り合っても紛れないよう全部違う色
    assert colors["tansho"] == BET_TYPE_COLORS["tansho"]  # 色の出どころはstyle.py


# --- 中身の符号（同じ中身なら描き直さないための目印） -------------------------------------


def test_the_same_contents_get_the_same_version():
    a = odds.build_payload(ENTRIES, ODDS, UPDATES)
    b = odds.build_payload(ENTRIES, ODDS, UPDATES)
    assert a["version"] == b["version"]
    assert len(a["version"]) == 12


def test_a_changed_odds_changes_the_version():
    """点数も時刻も同じまま値だけ動くことがある（同じ分のうちに取り直したとき）。

    ここで見落とすと、取り込んだのに画面が変わらない。
    """
    moved = {**ODDS, "umaren": [{"combo": "1-2", "odds_low": 40.1, "odds_high": None}]}
    assert odds.build_payload(ENTRIES, moved, UPDATES)["version"] \
        != odds.build_payload(ENTRIES, ODDS, UPDATES)["version"]


def test_the_version_follows_the_time_the_focus_and_the_bet_slip():
    base = odds.build_payload(ENTRIES, ODDS, UPDATES)["version"]
    later = {**UPDATES, "umaren": {"odds_label": "12時41分現在オッズ"}}
    assert odds.build_payload(ENTRIES, ODDS, later)["version"] != base
    assert odds.build_payload(ENTRIES, ODDS, UPDATES, focus="wide")["version"] != base
    slip = [{"group": 1, "bet": "umaren", "combos": ["1-2"], "amount": 100}]
    assert odds.build_payload(
        ENTRIES, ODDS, UPDATES, slip=slip, slip_saved_at="2026-09-26 12:40"
    )["version"] != base


# --- 買い目 -----------------------------------------------------------------------------


def test_the_saved_bet_slip_is_handed_to_the_screen():
    """DBに残してある買い目を、そのまま画面へ渡す（開き直しても残るように）。"""
    slip = [{"group": 1, "bet": "umaren", "combos": ["1-2", "1-3"], "amount": 100}]
    payload = odds.build_payload(
        ENTRIES, ODDS, UPDATES, slip=slip, slip_saved_at="2026-09-26 12:40"
    )
    assert payload["slip"] == slip
    assert payload["slipSavedAt"] == "2026-09-26 12:40"


def test_a_race_without_a_bet_slip_gets_an_empty_one():
    payload = odds.build_payload(ENTRIES, ODDS, UPDATES)
    assert payload["slip"] == [] and payload["slipSavedAt"] is None


def test_the_draw_version_ignores_the_bet_slip():
    """買い目を保存しただけのときは、画面を作り直さずに済ませたい。

    金額を直すたびに作り直すと、入力した瞬間にスクロールが先頭へ戻ってしまう。
    """
    base = odds.build_payload(ENTRIES, ODDS, UPDATES)
    slip = [{"group": 1, "bet": "umaren", "combos": ["1-2"], "amount": 500}]
    with_slip = odds.build_payload(
        ENTRIES, ODDS, UPDATES, slip=slip, slip_saved_at="2026-09-27 00:41"
    )
    assert with_slip["drawVersion"] == base["drawVersion"]    # 買い目は数に入れない
    assert with_slip["version"] != base["version"]            # 全体の符号は変わる


def test_the_draw_version_follows_the_odds():
    base = odds.build_payload(ENTRIES, ODDS, UPDATES)["drawVersion"]
    moved = {**ODDS, "umaren": [{"combo": "1-2", "odds_low": 40.1, "odds_high": None}]}
    assert odds.build_payload(ENTRIES, moved, UPDATES)["drawVersion"] != base
    later = {**UPDATES, "umaren": {"odds_label": "12時41分現在オッズ"}}
    assert odds.build_payload(ENTRIES, ODDS, later)["drawVersion"] != base


def test_the_phone_layout_is_passed_to_the_component():
    """スマホ版は下部バーと買い目シートで出す（PCは今までどおり）。"""
    pc = odds.build_payload(ENTRIES, ODDS, UPDATES)
    assert pc["layout"] == "pc" and pc["reservePx"] == 0
    phone = odds.build_payload(ENTRIES, ODDS, UPDATES, layout="phone", reserve_px=180)
    assert phone["layout"] == "phone" and phone["reservePx"] == 180
    assert phone["drawVersion"] != pc["drawVersion"]          # 見た目が変わるので描き直す
    assert odds.build_payload(ENTRIES, ODDS, UPDATES, layout="tablet")["layout"] == "pc"


def test_the_phone_bar_and_sheet_exist_in_the_component():
    import pathlib

    source = (pathlib.Path(odds.__file__).parent / "odds_component" / "index.html").read_text()
    assert 'id: "phone-bar"' in source and "sheet-open" in source
    assert "phoneFrameHeight(content)" in source.split("function setHeight()")[1].split("}")[0]
    # 中ではスクロールさせない（ページ全体で動かす）。バーとシートは見えている範囲に合わせて動かす
    assert "function trackViewport()" in source and "overflow-y: auto; overflow-x: hidden" not in source


def test_the_payload_carries_the_ids_for_jumping_to_the_grid():
    entries = [{**e, "horse_id": f"H{i}"} for i, e in enumerate(ENTRIES)]
    payload = odds.build_payload(entries, ODDS, UPDATES, race_id="202606040611")
    assert payload["raceId"] == "202606040611"
    assert all(h["horse_id"] for h in payload["horses"])
