"""区間ラップを区分（前後200m＋中間平均）にまとめる（lap_phases.py）。"""

import pytest

from keiba_analysis.racing.lap_phases import (
    CLOSING_LABELS,
    MIDDLE,
    OPENING_LABELS,
    PHASE_LABELS,
    phase_paces,
    phase_ranges,
)

FIRST, SECOND = OPENING_LABELS
LAST_600, LAST_400, LAST_200 = CLOSING_LABELS


def boundaries(first: int, step: int, distance: int) -> list[float]:
    """累計距離の一覧（最初の区間だけ長さが違うコースに対応）。"""
    values = [float(first)]
    while values[-1] < distance:
        values.append(values[-1] + step)
    return values


def test_phase_ranges_for_a_normal_race():
    """前2Fは200mずつ、上り3Fも200mずつ、その間が中間。"""
    assert phase_ranges(2000) == [
        (FIRST, 0.0, 200.0), (SECOND, 200.0, 400.0), (MIDDLE, 400.0, 1400.0),
        (LAST_600, 1400.0, 1600.0), (LAST_400, 1600.0, 1800.0), (LAST_200, 1800.0, 2000.0),
    ]
    assert [name for name, _, _ in phase_ranges(2000)] == list(PHASE_LABELS)


def test_short_race_has_no_middle():
    """1000m戦は前2Fと上り3Fで埋まるので、中間を作らない（5点になる）。"""
    assert [name for name, _, _ in phase_ranges(1000)] == [FIRST, SECOND, LAST_600, LAST_400, LAST_200]
    assert phase_ranges(600) == []          # 600m以下のレースは区分できない


def test_only_the_middle_is_averaged():
    """中間以外は、その区間のラップそのものになる。"""
    laps = [12.4, 11.0, 13.0, 13.0, 13.0, 13.0, 13.0, 11.5, 11.2, 11.8]  # 2000m
    paces = phase_paces(laps, boundaries(200, 200, 2000), 2000)
    assert paces[FIRST] == pytest.approx(12.4)      # 1区間目そのもの
    assert paces[SECOND] == pytest.approx(11.0)     # 2区間目そのもの
    assert paces[MIDDLE] == pytest.approx(13.0)     # 400m〜1400mの平均
    assert paces[LAST_600] == pytest.approx(11.5)   # 上り3Fも200mずつそのまま
    assert paces[LAST_400] == pytest.approx(11.2)
    assert paces[LAST_200] == pytest.approx(11.8)


def test_middle_is_the_average_of_the_remaining_laps():
    """中間は、前2Fと上り3Fを除いたラップの平均。"""
    laps = [12.0, 12.0, 12.6, 13.0, 12.8, 13.2, 12.4, 11.0, 11.0, 11.0]  # 2000m
    middle_laps = laps[2:7]
    paces = phase_paces(laps, boundaries(200, 200, 2000), 2000)
    assert paces[MIDDLE] == pytest.approx(sum(middle_laps) / len(middle_laps), abs=0.01)


def test_first_segment_of_100m_is_split_by_distance():
    """1700mのように最初が100mのレースでも、200m・400m地点でそろえる。

    区間は 100m / 300m / 500m … なので、200m地点は2区間目の途中。
    200m区分 = 7.0（0-100m）+ 11.5×(100/200) = 12.75秒
    400m区分 = 11.5×(100/200) + 12.0×(100/200) = 11.75秒
    """
    laps = [7.0, 11.5, 12.0, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5]   # 1700m（100m始まり）
    distances = boundaries(100, 200, 1700)
    assert distances[:3] == [100.0, 300.0, 500.0]
    paces = phase_paces(laps, distances, 1700)
    assert paces[FIRST] == pytest.approx(12.75)
    assert paces[SECOND] == pytest.approx(11.75)
    # 区分の所要時間を足すと走破タイムに戻る
    total = sum(paces[name] * ((end - start) / 200) for name, start, end in phase_ranges(1700))
    assert total == pytest.approx(sum(laps), abs=0.05)


def test_2500m_race_also_starts_with_100m():
    laps = [7.2, 11.5, 12.1] + [12.0] * 10                          # 2500m（100m始まり）
    distances = boundaries(100, 200, 2500)
    paces = phase_paces(laps, distances, 2500)
    assert paces[FIRST] == pytest.approx(7.2 + 11.5 / 2)
    total = sum(paces[name] * ((end - start) / 200) for name, start, end in phase_ranges(2500))
    assert total == pytest.approx(sum(laps), abs=0.05)


def test_missing_segments_make_the_phase_missing():
    """推定できなかった区間（None）を含む区分だけを欠損にする。"""
    laps = [12.0, 12.0, 13.0, None, 13.0, 13.0, 13.0, 11.0, 11.0, 11.0]
    paces = phase_paces(laps, boundaries(200, 200, 2000), 2000)
    assert paces[FIRST] == pytest.approx(12.0)
    assert paces[MIDDLE] is None
    assert paces[LAST_200] == pytest.approx(11.0)


def test_broken_input_returns_nothing():
    assert phase_paces([], [], 2000) == {}
    assert phase_paces([12.0], [200.0, 400.0], 2000) == {}   # 数が合わない
    assert phase_paces([12.0], [200.0], None) == {}
    # ラップがレース距離ぶん揃っていない（600mぶんしか無いのに2000m戦）
    assert phase_paces([12.0, 12.0, 12.0], [200.0, 400.0, 600.0], 2000) == {}
