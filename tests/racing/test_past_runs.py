"""過去走の表示用の文字列（racing/past_runs.py）。

2022年以前（Target由来）の走は、レース名が略称で末尾に格やクラスの付記が付き、
クラスも旧呼称（`500万下`）のまま入っている。2023年以降の走と同じ見た目になることを確かめる。
"""

import pytest

from keiba_analysis.racing import past_runs as pr


@pytest.mark.parametrize(("condition", "short"), [
    ("500万下", "1勝"),
    ("1000万下 牝", "2勝"),
    ("1600万下", "3勝"),
    ("未出走", "新馬"),
    ("1勝クラス", "1勝"),
])
def test_class_short_reads_old_class_names(condition, short):
    assert pr.class_short({"class_condition": condition, "race_name": ""}) == short


def test_format_race_name_does_not_repeat_the_grade():
    assert pr.format_race_name({"race_name": "皐月賞G1", "grade": "GI"}) == "皐月賞(GI)"
    assert pr.format_race_name({"race_name": "第84回皐月賞", "grade": "GI"}) == "第84回皐月賞(GI)"


def test_short_race_label_drops_target_suffixes():
    assert pr.short_race_label({"race_name": "皐月賞G1", "grade": "GI"}) == "GI 皐月賞"
    run = {"race_name": "テストS・3勝", "class_condition": "1600万下"}
    assert pr.short_race_label(run) == "3勝 テストS"
    # 名前がクラスそのもの（旧呼称）ならクラスだけ
    assert pr.short_race_label({"race_name": "500万下*", "class_condition": "500万下"}) == "1勝"


def test_format_weight_without_the_previous_weight():
    """2022年以前は初出走の増減が空（2023年以降は0）。空なら体重だけ出す。"""
    assert pr.format_weight({"horse_weight": 480, "weight_diff": None}) == "480"
    assert pr.format_weight({"horse_weight": 480, "weight_diff": 0}) == "480(+0)"


def test_race_name_plain_is_used_when_present():
    run = {"race_name": "スプリンG1", "race_name_plain": "スプリンターズS", "grade": "GI"}
    assert pr.format_race_name(run) == "スプリンターズS(GI)"
    assert pr.short_race_label(run) == "GI スプリンターズS"
