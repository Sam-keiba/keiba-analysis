"""ペース記号（S/M/H）の暫定判定。"""

from keiba_analysis.racing import pace


def test_high_pace_when_the_first_3f_is_faster():
    assert pace.classify(34.5, 36.3) == "H"   # 前半が1.8秒速い
    assert pace.classify(35.0, 36.0) == "H"   # ちょうどしきい値（1.0秒）


def test_slow_pace_when_the_first_3f_is_slower():
    assert pace.classify(36.3, 34.5) == "S"
    assert pace.classify(36.0, 35.0) == "S"   # ちょうどしきい値


def test_middle_pace_inside_the_threshold():
    assert pace.classify(35.5, 36.4) == "M"   # 差0.9秒はミドル
    assert pace.classify(36.4, 35.5) == "M"
    assert pace.classify(35.0, 35.0) == "M"


def test_no_laps_means_no_mark():
    assert pace.classify(None, 34.5) is None
    assert pace.classify(36.3, None) is None
    assert pace.classify(None, None) is None


def test_classify_run_reads_the_past_run_row():
    assert pace.classify_run({"race_first_3f": 34.5, "race_last_3f": 36.3}) == "H"
    assert pace.classify_run({}) is None       # 障害戦などラップが無い走


def test_description_is_shown_as_a_tooltip():
    text = pace.description(34.5, 36.3)
    assert "34.5" in text and "36.3" in text
    assert "ハイペース" in text
    assert "暫定判定" in text                   # 暫定であることが分かる
    assert "判定できません" in pace.description(None, None)
