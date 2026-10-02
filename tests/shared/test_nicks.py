"""ニックス診断（shared/nicks.py）。手で組んだ産駒で、系統・遡り・平均比・AEI・適性評価を確かめる。名前はすべて架空。"""

import pytest

from keiba_analysis.shared import nicks as nk
from keiba_analysis.shared import sire_index as si
from keiba_analysis.shared.sire_index import HorseYear

# 祖先ID: 父系 SIRE の父=GS、その父=GGS、その父=GGGS。母父 BMS の父=BG、その父=BGG、その父=BGGG
SIRE = nk.Stallion("S1", "テストサイアー", ("Test Sire",))
OTHER = nk.Stallion("S2", "ベツノサイアー", ())         # SIRE と同じ父（GS）を持つ兄弟種牡馬
FAR = nk.Stallion("S3", "トオイサイアー", ())           # 同じ祖父（GGS）だけを共有
BMS = nk.Stallion("B1", "テストボーム", ("Test Bms II",))
BMS2 = nk.Stallion("B2", "ベツノボーム", ())            # BMS と同じ父（BG）
STALLIONS = [SIRE, OTHER, FAR, BMS, BMS2]
PAT = {"S1": ("GS", "GGS", "GGGS"), "S2": ("GS", "GGS", "GGGS"), "S3": ("XS", "GGS", "GGGS")}
MAT = {"B1": ("BG", "BGG", "BGGG"), "B2": ("BG", "BGG", "BGGG"), "B3": ("YG", "BGG", "BGGG")}


def foal(i, sire, bms, *, wins=0, top3=0, crop=2018, prize=0.0, graded=0):
    return nk.Foal(horse_id=f"{sire}-{bms}-{i}", horse_name=f"馬{sire}{bms}{i}", sex="牡", crop=crop,
                   sire=sire, bms=bms, paternal=PAT[sire], maternal=MAT[bms], starts=5, wins=wins,
                   top3=top3, prize_man_yen=prize, graded_wins=graded,
                   best_win="GII テスト記念" if graded else None)


def hy_rows(foals, prize_by_id):
    """1頭1年の行（2020年に走ったことにする）。"""
    return {f.horse_id: [HorseYear(f.horse_id, 2020, f.sire, None, prize=prize_by_id.get(f.horse_id, 0.0),
                                   prize_flat=prize_by_id.get(f.horse_id, 0.0))] for f in foals}


# --- 入力 ---------------------------------------------------------------------------------------

def test_resolve_stallion_handles_kana_english_and_variants():
    assert nk.resolve_stallion(STALLIONS, "テストサイアー") == [SIRE]
    assert nk.resolve_stallion(STALLIONS, "test sire") == [SIRE]           # 大文字小文字・空白
    assert nk.resolve_stallion(STALLIONS, "ＴＥＳＴ　ＢＭＳ Ⅱ") == [BMS]  # 全角・ローマ数字
    assert nk.resolve_stallion(STALLIONS, "ベツノ") == [OTHER, BMS2]         # 前方一致の候補
    assert nk.resolve_stallion(STALLIONS, "") == []


def test_crop_window_includes_partial_crops():
    assert nk.crop_window("2026-09-27") == (2015, 2024)
    assert nk.is_partial(2023, "2026-09-27") and not nk.is_partial(2022, "2026-09-27")


# --- 系統と遡り ---------------------------------------------------------------------------------

def test_line_root_and_name():
    foals = [foal(1, "S1", "B1")]
    assert nk.line_root(foals, "S1", "sire", 0) == "GS"
    assert nk.line_root(foals, "B1", "bms", 1) == "BGG"
    assert nk.line_name("サンデーサイレンス", 1) == "サンデーサイレンス系*"
    assert nk.line_name(None, 2) == "不明系**"


def test_choose_levels_climbs_until_enough_horses():
    # 父系統(GS) × 母父系統(BG) は 2頭だけ。父方を1代遡る(GGS)と FAR の産駒が入って 4頭
    foals = [foal(1, "S1", "B1"), foal(2, "S2", "B2"), foal(3, "S3", "B1"), foal(4, "S3", "B2")]
    roots_s, roots_b = ("GS", "GGS", "GGGS"), ("BG", "BGG", "BGGG")
    assert nk.choose_levels(foals, roots_s, roots_b, min_horses=2) == (0, 0)
    assert nk.choose_levels(foals, roots_s, roots_b, min_horses=4) == (1, 0)
    # どれでも足りなければ、いちばん頭数の多い遡り方
    assert nk.choose_levels(foals, roots_s, roots_b, min_horses=99) == (1, 0)


# --- 4パターンと平均比 --------------------------------------------------------------------------

def _diag(foals, prize, *, min_horses=2):
    rows = hy_rows(foals, prize)
    field = si.field_by_year([r for rs in rows.values() for r in rs])
    names = {"GS": "ソフ", "GGS": "ソソフ", "BG": "ボソフ", "BGG": "ボソソフ"}
    return nk.diagnose(foals, SIRE, BMS, rows_by_horse=rows, field=field, names=names,
                       crops=(2015, 2024), as_of="2026-09-27", min_horses=min_horses)


def test_diagnose_counts_bases_and_ratios():
    foals = ([foal(i, "S1", "B1", wins=1, top3=2) for i in range(2)]      # 父 × 母父: 2頭とも勝ち上がり
             + [foal(i, "S1", "B3") for i in range(2)]                     # 父 × 別系統の母父
             + [foal(i, "S2", "B2", wins=1) for i in range(2)]             # 兄弟種牡馬 × 同系統の母父
             + [foal(i, "S3", "B1") for i in range(2)])                    # 別系統の父 × 母父
    d = _diag(foals, {})
    p1, p2, p3, p4 = d.patterns
    assert (d.sire_line.name, d.bms_line.name) == ("ソフ系", "ボソフ系")
    assert [p.stats.horses for p in d.patterns] == [2, 2, 2, 4]
    # 1: 父 × 母父の勝ち上がり率 1.0 ÷ 父の全産駒(4頭中2頭) 0.5 = 2.0
    assert p1.base.horses == 4 and p1.ratios["win_rate"] == pytest.approx(2.0)
    # 母父平均比: 母父 B1 の全産駒(S1×B1 2頭 + S3×B1 2頭)の勝ち上がり率 0.5 と比べる
    assert p1.bms_base.horses == 4 and p1.bms_ratios["win_rate"] == pytest.approx(2.0)
    # 3・4の平均比の相手は父の系統(S1・S2 の産駒 6頭)
    assert p3.base.horses == 6 and p4.base_label == "ソフ系の全産駒"
    # 4: 系統 × 系統の4頭（S1×B1 と S2×B2）は全頭勝ち上がり 1.0 ÷ 父の系統 6頭中4頭
    assert p4.stats.horses == 4 and p4.ratios["win_rate"] == pytest.approx(1.0 / (4 / 6))
    assert p1.ratios["top3_per_horse"] == pytest.approx(2.0 / (4 / 4))
    assert not p1.thin and _diag(foals, {}, min_horses=3).patterns[0].thin


def test_pattern_aei_uses_sire_index_definition():
    foals = [foal(i, "S1", "B1") for i in range(20)] + [foal(i, "S2", "B3") for i in range(20)]
    prize = {f.horse_id: (300.0 if f.sire == "S1" else 100.0) for f in foals}
    d = _diag(foals, prize)
    # 全40頭の平均 200、父 × 母父の20頭は 300 → 1.5（sire_index.aei と同じ式・同じ分母）
    assert d.patterns[0].stats.aei.value == pytest.approx(1.5)
    direct = si.aei([HorseYear(f.horse_id, 2020, "x" if f.sire == "S1" else "y", None, prize=prize[f.horse_id],
                               prize_flat=prize[f.horse_id]) for f in foals], "x")
    assert direct.value == pytest.approx(d.patterns[0].stats.aei.value)


def test_young_share_and_missing_sire():
    foals = [foal(1, "S1", "B1", crop=2024), foal(2, "S1", "B1", crop=2018), foal(3, "S2", "B2")]
    assert _diag(foals, {}).young_share == pytest.approx(0.5)
    missing = nk.diagnose([foal(1, "S2", "B1")], SIRE, BMS, rows_by_horse={}, field={}, names={},
                          crops=(2015, 2024), as_of="2026-09-27")
    assert missing.patterns == [] and "テストサイアー" in missing.reason


# --- 適性評価・活躍馬 ---------------------------------------------------------------------------

def run(bms, surface, distance, pos, mff="BG"):
    return {"bms": bms, "surface": surface, "distance_m": distance, "finish_position": pos,
            "mff": mff, "mfff": "BGG", "mffff": "BGGG"}


def test_aptitude_compares_with_all_progeny():
    runs = [run("B1", "turf", 2000, 1), run("B1", "turf", 2000, 5),
            run("B9", "turf", 2000, 9), run("B9", "turf", 2000, 9), run("B1", "dirt", 1200, 2)]
    cells = {(c.surface, c.band): c for c in nk.aptitude(runs, lambda r: r["bms"] == "B1", thin_runs=2)}
    mid = cells[("turf", "中距離（1700〜2300m）")]
    assert (mid.top3, mid.starts, mid.base_top3, mid.base_starts) == (1, 2, 1, 4)
    assert mid.diff == pytest.approx(0.5 - 0.25) and not mid.thin
    assert cells[("dirt", "短距離（〜1600m）")].thin
    assert cells[("turf", "長距離（2400m〜）")].rate is None


def test_aptitude_target_falls_back_to_bms_line():
    foals = [foal(1, "S1", "B1"), foal(2, "S1", "B2"), foal(3, "S2", "B2")]
    d = _diag(foals, {}, min_horses=2)
    label, target = nk.aptitude_target(d, min_horses=2)
    assert "母父の系統" in label and target(run("B9", "turf", 2000, 1, mff="BG"))


def test_active_horses_put_graded_winners_first_with_nearest_pattern():
    foals = [foal(1, "S1", "B1", prize=100), foal(2, "S2", "B1", prize=50, graded=1),
             foal(3, "S1", "B2", prize=900), foal(4, "S3", "B3", prize=9999)]
    top = nk.active_horses(foals, _diag(foals, {}, min_horses=1))
    assert [(x["pattern"], x["foal"].horse_id) for x in top] == [(3, "S2-B1-2"), (2, "S1-B2-3"), (1, "S1-B1-1")]
