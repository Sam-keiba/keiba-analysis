"""レース名・クラス名の表記をそろえる関数（shared/race_name.py）。

1995〜2022年（Target由来）の略称・旧クラス名を、2023年以降の表記と同じに扱えることを確かめる。
2023年以降の名前を**壊さない**ことも同じくらい大事。
"""

import pytest

from keiba_analysis.shared import race_name as rn


@pytest.mark.parametrize(("raw", "expected"), [
    ("皐月賞G1", "皐月賞"),               # 格
    ("新潟記念HG3", "新潟記念"),           # ハンデ戦の印つきの格
    ("中山大障JG1", "中山大障"),           # 障害の格
    ("リステッドS(L)", "リステッドS"),     # リステッド
    ("テスト特H1000", "テスト特H"),       # 旧クラスの金額
    ("テスト賞500*", "テスト賞"),         # 金額と指定の印
    ("テストS・3勝", "テストS"),           # 条件
    ("テスト杯・重", "テスト杯"),
    ("未勝利・牝", "未勝利"),
    ("未勝利*", "未勝利"),
    ("500万下", "500万下"),               # 名前そのものがクラスなら残す
    ("1000万下*", "1000万下"),
])
def test_clean_race_name_drops_target_suffixes(raw, expected):
    assert rn.clean_race_name(raw) == expected


@pytest.mark.parametrize("name", [
    "第84回皐月賞", "第41回フェブラリーS", "3歳以上1勝クラス", "2歳未勝利", "テストS(3勝)",
])
def test_clean_race_name_keeps_recent_names(name):
    """2023年以降（スクレイピング由来）の名前はそのまま。"""
    assert rn.clean_race_name(name) == name


def test_clean_race_name_handles_empty():
    assert rn.clean_race_name(None) == ""
    assert rn.clean_race_name("") == ""


def test_is_classic_matches_both_name_styles():
    assert rn.is_classic("第84回皐月賞", "GI")
    assert rn.is_classic("皐月賞G1", "GI")
    assert rn.is_classic("東京優駿G1", "GI")


def test_is_classic_needs_grade_one():
    """トライアル（名前に競走名を含んでもGIでない）は数えない。"""
    assert not rn.is_classic("皐月賞トライアル", "GII")
    assert not rn.is_classic("皐月賞G1", None)
    assert not rn.is_classic("天皇賞(秋)", "GI")


@pytest.mark.parametrize(("old", "new"), [
    ("500万下", "1勝クラス"),
    ("500万下 牝", "1勝クラス 牝"),
    ("900万下", "2勝クラス"),
    ("1000万下", "2勝クラス"),
    ("1500万下", "3勝クラス"),
    ("1600万下 見習騎手", "3勝クラス 見習騎手"),
    ("未出走", "新馬"),
    ("1勝クラス", "1勝クラス"),            # 今の呼称はそのまま
    ("オープン", "オープン"),
    ("", ""),
])
def test_modern_class_reads_old_names_as_new(old, new):
    assert rn.modern_class(old) == new


def test_display_race_name_prefers_the_plain_name():
    """keiba-data の `race_name_plain`（略称を今の名前に寄せたもの）があればそれを使う。"""
    assert rn.display_race_name({"race_name": "スプリンG1", "race_name_plain": "スプリンターズS"}) \
        == "スプリンターズS"


def test_display_race_name_falls_back_to_cleaning():
    """`race_name_plain` を持たない dict（出馬表など）は、これまでどおり付記を落とす。"""
    assert rn.display_race_name({"race_name": "皐月賞G1"}) == "皐月賞"
    assert rn.display_race_name({"race_name": "皐月賞G1", "race_name_plain": None}) == "皐月賞"
