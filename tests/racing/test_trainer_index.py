"""厩舎AEI・CPI（racing/trainer_index.py）。**sire_index の式そのもの**になっていることを確かめる。"""

import pytest

from keiba_analysis.racing import trainer_index as ti
from keiba_analysis.shared import sire_index as si
from keiba_analysis.shared.sire_index import HorseYear

T, U = "10001", "10002"


def hy(horse_id, year, group, prize, *, dam=None, crop=2020, flat=None):
    return HorseYear(horse_id=horse_id, year=year, sire=group, dam_no=dam, prize=prize,
                     prize_flat=prize if flat is None else flat, crop=crop)


def test_trainer_aei_equals_sire_aei_definition():
    """同じ行を「種牡馬の行」とみても「厩舎の行」とみても、AEIは同じ値になる。"""
    field_rows = [hy("A", 2024, "S", 400), hy("B", 2024, "S", 0), hy("C", 2024, "S2", 200)]
    trainer_rows = [hy("A", 2024, T, 400), hy("B", 2024, U, 0), hy("C", 2024, U, 200)]
    field = si.field_by_year(field_rows)
    flat = si.field_by_year(field_rows, flat_only=True)
    result = ti.trainer_index(trainer_rows, T, first_crop=2013, last_crop=2022, field=field,
                              flat_field=flat)
    # 全3頭の平均は 200、T の1頭は 400 → 2.00。min_horses の既定（20頭）未満なので値は出ず、材料だけ確かめる
    assert result.aei.value is None and result.aei.distinct_horses == 1
    direct = si.aei(trainer_rows, T, field=field, min_horses=1)
    assert direct.value == pytest.approx(2.0)
    assert (direct.prize_man_yen, direct.field_per_horse) == (result.aei.prize_man_yen,
                                                              result.aei.field_per_horse)


def test_trainer_index_with_enough_horses_and_cpi_from_other_stables():
    rows, field_rows = [], []
    for i in range(20):
        # T の馬（2020年生）は400、その母の別の子は U の厩舎で 100
        rows += [hy(f"T{i}", 2024, T, 400, dam=f"D{i}"), hy(f"S{i}", 2024, U, 100, dam=f"D{i}", crop=2019)]
        field_rows += [hy(f"T{i}", 2024, "s", 400, dam=f"D{i}"), hy(f"S{i}", 2024, "s", 100, dam=f"D{i}")]
    field = si.field_by_year(field_rows)
    flat = si.field_by_year(field_rows, flat_only=True)
    result = ti.trainer_index(rows, T, first_crop=2013, last_crop=2022, field=field, flat_field=flat)
    assert result.aei.value == pytest.approx(400 / 250)
    assert result.cpi.value == pytest.approx(100 / 250)
    assert result.ratio == pytest.approx(4.0)


def test_trainer_index_limits_own_horses_to_crop_range():
    rows = [hy(f"T{i}", 2024, T, 400, crop=2023) for i in range(20)]   # 範囲外の世代だけ
    field = si.field_by_year(rows)
    result = ti.trainer_index(rows, T, first_crop=2013, last_crop=2022, field=field, flat_field=field)
    assert result.aei.value is None and result.aei.distinct_horses == 0
