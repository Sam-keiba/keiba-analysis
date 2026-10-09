"""買い目 → IPAT投票用の明細（変換と検証）。"""

from datetime import datetime

import pytest

from keiba_analysis.racing import ipat

# 2026年 東京(05) 4回 2日目 11R
RACE = {"race_id": "202605040211", "race_date": "2026-10-10", "post_time": "15:45", "is_finished": 0}
# 12頭立て（枠は1〜6）
ENTRIES = [{"umaban": n, "waku": (n + 1) // 2} for n in range(1, 13)]
BEFORE = datetime(2026, 10, 10, 15, 0)


def build(groups, race=RACE, entries=ENTRIES, now=BEFORE):
    return ipat.build_ticket(race, entries, groups, now)


def test_the_race_is_split_into_venue_meeting_and_race_number():
    t = build([{"bet": "tansho", "combos": ["7"], "amount": 100}])
    assert (t.venue_code, t.venue_name, t.kaiji, t.nichime, t.race_no) == ("05", "東京", 4, 2, 11)
    assert t.race_label == "東京11R"
    assert t.ok and t.points == 1 and t.total == 100


@pytest.mark.parametrize(
    ("bet", "combo", "numbers", "text"),
    [
        ("tansho", "7", (7,), "7"),
        ("fukusho", "7", (7,), "7"),
        ("wakuren", "3-3", (3, 3), "3-3"),        # 枠連のゾロ目
        ("umaren", "12-1", (1, 12), "1-12"),       # 順序の無い式別は小さい順
        ("wide", "4-6", (4, 6), "4-6"),
        ("umatan", "12-1", (12, 1), "12→1"),       # 馬単は着順どおり
        ("sanrenpuku", "12-7-1", (1, 7, 12), "1-7-12"),
        ("sanrentan", "12-7-1", (12, 7, 1), "12→7→1"),
    ],
)
def test_every_bet_type_becomes_one_line(bet, combo, numbers, text):
    t = build([{"bet": bet, "combos": [combo], "amount": 300}])
    assert t.errors == []
    (line,) = t.lines
    assert line.bet == bet and line.numbers == numbers and line.combo_text == text and line.amount == 300


def test_a_formation_is_split_into_single_points():
    """フォーメーション・ながし・BOXは1点ずつにばらす。金額は1点あたりのまま。"""
    t = build([{"bet": "umaren", "kind": "ボックス", "combos": ["1-2", "1-3", "2-3"], "amount": 200}])
    assert [l.combo_text for l in t.lines] == ["1-2", "1-3", "2-3"]
    assert t.points == 3 and t.total == 600


def test_several_groups_add_up():
    t = build([
        {"bet": "tansho", "combos": ["1", "2"], "amount": 100},
        {"bet": "sanrentan", "combos": ["1-2-3"], "amount": 500},
    ])
    assert t.points == 3 and t.total == 700


@pytest.mark.parametrize("amount", [0, 50, 150, 99, -100, None, "abc", 150.5])
def test_money_must_be_in_hundreds(amount):
    t = build([{"bet": "tansho", "combos": ["1"], "amount": amount}])
    assert not t.ok
    assert any("100円単位" in e for e in t.errors)


@pytest.mark.parametrize(
    ("bet", "combo", "why"),
    [
        ("tansho", "13", "馬番13はこのレースにありません"),     # 12頭立て
        ("tansho", "0", "馬番0はこのレースにありません"),
        ("wakuren", "1-9", "枠番9はこのレースにありません"),
        ("wakuren", "1-7", "枠番7はこのレースにありません"),    # 12頭立ては6枠まで
        ("umaren", "5-5", "同じ馬番が重なっています"),
        ("umaren", "1", "2頭で選んでください"),
        ("sanrentan", "1-2", "3頭で選んでください"),
        ("umaren", "a-1", "馬番が読めません"),
    ],
)
def test_bad_numbers_are_reported(bet, combo, why):
    t = build([{"bet": bet, "combos": [combo], "amount": 100}])
    assert not t.ok
    assert any(why in e for e in t.errors), t.errors


def test_an_unknown_bet_type_is_reported():
    t = build([{"bet": "win5", "combos": ["1"], "amount": 100}])
    assert any("知らない式別" in e for e in t.errors)


def test_an_empty_slip_cannot_be_sent():
    t = build([])
    assert not t.ok and t.errors == ["買い目がありません。"]


def test_after_the_start_it_cannot_be_sent():
    t = build([{"bet": "tansho", "combos": ["1"], "amount": 100}], now=datetime(2026, 10, 10, 15, 45))
    assert not t.ok
    assert any("発走時刻（15:45）を過ぎています" in e for e in t.errors)


def test_a_finished_race_cannot_be_sent():
    t = build([{"bet": "tansho", "combos": ["1"], "amount": 100}], race={**RACE, "is_finished": 1})
    assert any("結果が確定" in e for e in t.errors)


def test_an_unknown_start_time_is_only_a_warning():
    """発走時刻が分からないときは止めずに、確かめていないことを知らせる。"""
    t = build([{"bet": "tansho", "combos": ["1"], "amount": 100}], race={**RACE, "post_time": None})
    assert t.ok
    assert any("発走時刻が分からない" in w for w in t.warnings)


def test_before_the_number_draw_it_cannot_be_sent():
    t = build([{"bet": "tansho", "combos": ["1"], "amount": 100}], entries=[{"umaban": None}])
    assert any("馬番がまだ決まっていません" in e for e in t.errors)


def test_the_ticket_goes_to_the_screen_as_a_dict():
    d = build([{"bet": "umatan", "combos": ["2-1"], "amount": 1200}]).to_dict()
    assert d["raceLabel"] == "東京11R" and d["ok"] is True
    assert d["lines"] == [{"bet": "umatan", "label": "馬単", "numbers": [2, 1], "combo": "2→1", "amount": 1200}]
    assert d["points"] == 1 and d["total"] == 1200


# --- 送り方 -----------------------------------------------------------------------------


def test_the_manual_sender_only_lists_the_bets_and_opens_ipat():
    """今の送り方は、手で入力する一覧とIPATの入口だけ（買い目はURLに載せない）。"""
    t = build([{"bet": "umaren", "combos": ["1-12"], "amount": 500}])
    result = ipat.default_sender().prepare(t)
    assert result.mode == "manual" and result.ok
    assert result.url == ipat.IPAT_URL
    assert "?" not in result.url                      # 買い目を載せない
    assert result.lines == ("馬連 1-12 500円",)
    assert "東京11R" in result.message and "1点" in result.message and "500円" in result.message


def test_the_manual_sender_refuses_a_ticket_with_errors():
    t = build([{"bet": "tansho", "combos": ["99"], "amount": 100}])
    result = ipat.ManualSender().prepare(t)
    assert not result.ok and result.url is None and result.lines == ()


def test_nothing_secret_is_asked_for():
    """暗証番号などを受け取る口を作らない（引数・項目の名前に出てこない）。"""
    import inspect
    source = inspect.getsource(ipat)
    for word in ("password", "pin", "pars", "p_ars", "subscriber"):
        assert f"{word}:" not in source.lower() and f"{word}=" not in source.lower()
