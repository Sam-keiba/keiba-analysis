"""厩舎分析の集計（racing/trainer_stats.py）。手で組んだ行で、数え方と定義を確かめる。名前はすべて架空。"""

import pytest

from keiba_analysis.racing import trainer_stats as ts

T, U, V = "10001", "10002", "10003"     # 美浦・美浦・栗東の厩舎
STABLES = {T: "美浦", U: "美浦", V: "栗東"}


def run(horse, day, trainer=T, *, prev=None, prev_trainer=None, prev_jockey=None, next_trainer=None,
        jockey="J1", venue="05", surface="turf", distance=1600, pos=5, prize=0.0, sex="牡", owner="P1"):
    return {"horse_id": horse, "race_date": day, "trainer_id": trainer, "jockey_id": jockey,
            "venue_code": venue, "surface": surface, "distance_m": distance, "class_condition": None,
            "grade": None, "finish_position": pos, "prize_man_yen": prize, "win_odds": 10.0,
            "owner_id": owner, "prev_date": prev, "prev_trainer": prev_trainer,
            "prev_jockey": prev_jockey, "next_trainer": next_trainer, "sex": sex}


# --- 年別の順位 ------------------------------------------------------------------------------

def year_row(trainer, year, wins, prize, seconds=0):
    return {"trainer_id": trainer, "year": year, "starts": 10, "wins": wins, "seconds": seconds,
            "thirds": 0, "prize_man_yen": prize, "horses": 5}


def test_year_ranks_by_wins_then_seconds_and_prize_separately():
    rows = [year_row(T, 2025, 10, 100), year_row(U, 2025, 10, 900, seconds=3),
            year_row(V, 2025, 5, 5000)]
    ranks = ts.year_ranks(rows)
    assert ranks[(U, 2025)] == (1, 2, 3)        # 同じ勝利数なら2着の多いほうが上
    assert ranks[(T, 2025)] == (2, 3, 3)
    assert ranks[(V, 2025)] == (3, 1, 3)        # 賞金順位は別に付ける


def test_trainer_years_marks_current_year_partial_and_limits_years():
    rows = [year_row(T, y, 1, 10) for y in range(2019, 2027)]
    years = ts.trainer_years(rows, T, as_of="2026-09-27", last_n=5)
    assert [y.year for y in years] == [2022, 2023, 2024, 2025, 2026]
    assert [y.partial for y in years] == [False] * 4 + [True]
    assert sum(y.wins for y in ts.trainer_years(rows, T, as_of="2026-09-27", last_n=None)) == 8


# --- 直近の各走から ------------------------------------------------------------------------

def test_behavior_counts_followups_back_to_back_and_jockey_change():
    runs = [
        run("A", "2026-01-05"),                                                   # 前走なし
        run("A", "2026-01-12", prev="2026-01-05", prev_trainer=T, prev_jockey="J1"),   # 7日＝連闘
        run("A", "2026-03-01", prev="2026-01-12", prev_trainer=T, prev_jockey="J1", jockey="J2"),
        run("A", "2026-09-01", prev="2026-03-01", prev_trainer=T, prev_jockey="J2"),   # 184日＝続戦でない
    ]
    b = ts.behavior_by_trainer(runs, stables=STABLES, clubs=set(), as_of="2026-09-27")[T]
    assert b.followups == 2 and b.gaps == [7, 48]
    assert b.back_to_back == 1 and b.jockey_changes == 1
    assert ts.behavior_value("rotation", b) == pytest.approx(27.5)
    assert ts.behavior_value("back_to_back", b) == pytest.approx(0.5)


def test_transfers_are_counted_per_horse_on_both_sides():
    runs = [
        run("A", "2026-01-05", T, next_trainer=U),
        run("A", "2026-03-05", U, prev="2026-01-05", prev_trainer=T),
        run("B", "2026-02-05", T),
    ]
    beh = ts.behavior_by_trainer(runs, stables=STABLES, clubs=set(), as_of="2026-09-27")
    assert ts.behavior_value("transfer_out", beh[T]) == pytest.approx(0.5)    # A・Bのうち A
    assert ts.behavior_value("transfer_in", beh[U]) == pytest.approx(1.0)
    assert beh[U].followups == 0          # 前走が他厩舎なら続戦に入れない


def test_away_depends_on_stable_and_local_and_club_share():
    runs = [run("A", "2026-01-05", T, venue="09", owner="CLUB"),    # 美浦 → 阪神は遠征
            run("B", "2026-01-06", T, venue="04"),                  # 新潟はローカル
            run("C", "2026-01-07", V, venue="05")]                  # 栗東 → 東京は遠征
    beh = ts.behavior_by_trainer(runs, stables=STABLES, clubs={"CLUB"}, as_of="2026-09-27")
    assert ts.behavior_value("away", beh[T]) == pytest.approx(0.5)
    assert ts.behavior_value("local", beh[T]) == pytest.approx(0.5)
    assert ts.behavior_value("club_share", beh[T]) == pytest.approx(0.5)
    assert ts.behavior_value("away", beh[V]) == pytest.approx(1.0)


def test_last_year_counts_for_stable_size():
    runs = [run("A", "2025-01-05"), run("B", "2026-05-05"), run("B", "2026-06-05")]
    b = ts.behavior_by_trainer(runs, stables=STABLES, clubs=set(), as_of="2026-09-27")[T]
    assert ts.behavior_value("stable_size", b) == 1
    assert ts.behavior_value("starts_per_horse", b) == pytest.approx(2.0)


def test_filly_index_normalizes_by_each_sex_field():
    # 全体: 牝 (300+100)/2=200、牡 (400+0)/2=200。T の牝は300/200=1.5、牡は400/200=2.0 → -0.5
    runs = [run("F1", "2026-01-05", T, sex="牝", prize=300), run("M1", "2026-01-05", T, prize=400),
            run("F2", "2026-01-05", U, sex="牝", prize=100), run("M2", "2026-01-05", U, prize=0)]
    beh = ts.behavior_by_trainer(runs, stables=STABLES, clubs=set(), as_of="2026-09-27")
    field = ts.sex_field(beh)
    assert field == {"牝": pytest.approx(200), "牡セ": pytest.approx(200)}
    assert ts.filly_index(beh[T], field, min_each=1) == pytest.approx(-0.5)
    assert ts.filly_index(beh[T], field, min_each=2) is None


def test_category_grid_and_thin():
    runs = [run(f"H{i}", "2026-01-05", T, distance=1200, pos=1 if i < 3 else 9) for i in range(10)]
    runs += [run(f"U{i}", "2026-01-05", U, distance=1200, pos=2 if i < 1 else 9) for i in range(10)]
    beh = ts.behavior_by_trainer(runs, stables=STABLES, clubs=set(), as_of="2026-09-27")
    cell = ts.category_grid(T, beh)[0]
    assert (cell.surface, cell.label, cell.starts, cell.top3) == ("turf", "短距離", 10, 3)
    assert cell.field_rate == pytest.approx(4 / 20) and cell.lift == pytest.approx(0.3 / 0.2)
    assert cell.thin                      # 20走未満


# --- 世代から ------------------------------------------------------------------------------

def horse(hid, trainers, *, crop=2020, debut="2022-07-10", debut_trainer=None, first_win_n=None,
          classic=0, graded=0, breeder="ノーザンファーム"):
    return {"horse_id": hid, "trainers": tuple(trainers), "crop": crop, "debut_date": debut,
            "debut_trainer": debut_trainer or trainers[0], "debut_age": 2, "debut_class": "新馬",
            "first_win_n": first_win_n, "classic": classic, "graded_winner": graded, "aged3": 1,
            "sex": "牡", "breeder": breeder}


def test_crop_counts_attribute_transferred_horses_to_both():
    horses = [horse("A", [T, U], first_win_n=3, classic=1),
              horse("B", [T], debut="2023-01-20", breeder="個人牧場")]
    crops = ts.crops_by_trainer(horses)
    assert (crops[T].horses, crops[T].winners, crops[T].classic) == (2, 1, 1)
    assert crops[U].horses == 1 and crops[U].debuts == 0      # デビューは T
    assert crops[T].debuts == 2 and crops[T].early_debuts == 1
    assert crops[T].debut_days == [190, 384]                   # 2022-01-01 起点
    assert crops[T].starts_to_win == [3]
    assert ts.crop_value("shadai", crops[T]) == pytest.approx(0.5)


def test_crop_range_uses_finished_three_year_old_seasons():
    assert ts.crop_range("2026-09-27") == (2013, 2022)
    assert ts.crop_range("2026-12-31") == (2014, 2023)


# --- 分布の中の位置 ----------------------------------------------------------------------------

def test_percentile_counts_ties_as_half():
    assert ts.percentile([1, 2, 3, 4], 3) == pytest.approx(0.625)
    assert ts.percentile([], 3) is None and ts.percentile([1], None) is None


def test_trend_positions_use_only_eligible_trainers():
    runs = [run(f"T{i}", "2026-01-05", T, owner="CLUB" if i < 5 else "P") for i in range(10)]
    runs += [run(f"U{i}", "2026-01-05", U, owner="P") for i in range(10)]
    runs += [run("V0", "2026-01-05", V, owner="CLUB")]               # 1頭だけ → 母集団外
    beh = ts.behavior_by_trainer(runs, stables=STABLES, clubs={"CLUB"}, as_of="2026-09-27")
    club = next(p for p in ts.trend_positions(T, beh, {}, set(STABLES)) if p.spec.key == "club_share")
    assert club.value == pytest.approx(0.5) and club.n_trainers == 2
    assert club.median == pytest.approx(0.25) and club.percentile == pytest.approx(0.75)


# --- 区分ごとの成績（Phase 2 のタブ） ------------------------------------------------------------

def trun(horse, *, pos=5, odds=10.0, jockey="騎手A", owner="P1", owner_name="個人一郎", sex="牡", age=3,
         surface="turf", distance=1600, grade=None, cls="1勝クラス", venue=("05", "東京"),
         day="2026-01-05", status=None, prize=0.0):
    return {"horse_id": horse, "finish_position": pos, "finish_status": status, "win_odds": odds,
            "jockey_name": jockey, "jockey_id": jockey, "owner_id": owner, "owner_name": owner_name,
            "sex": sex, "age": age, "surface": surface, "distance_m": distance, "grade": grade,
            "class_condition": cls, "venue_code": venue[0], "venue_name": venue[1],
            "race_date": day, "prize_man_yen": prize}


def test_record_rates_and_win_return():
    runs = [trun("A", pos=1, odds=5.0), trun("A", pos=2), trun("B", pos=3, odds=None),
            trun("B", pos=None, status="取消")]
    rec = ts.record("全体", runs)
    assert (rec.starts, rec.wins, rec.top2, rec.top3, rec.horses) == (3, 1, 2, 3, 2)
    assert rec.roi == pytest.approx(5.0 / 2)       # オッズの無い走は回収率の分母から外す
    assert rec.to_tally().top3 == 3


def test_by_jockey_orders_by_rides():
    runs = [trun("A", jockey="騎手B")] + [trun("A", jockey="騎手A")] * 2
    assert [r.label for r in ts.by_jockey(runs)] == ["騎手A", "騎手B"]


def test_by_owner_uses_club_label_and_club_vs_others():
    clubs = {"C1": "テストクラブ"}
    runs = [trun("A", owner="C1", owner_name="テストクラ…"), trun("B"), trun("C")]
    owners = ts.by_owner(runs, clubs)
    assert [o.label for o in owners] == ["個人一郎", "テストクラブ"]
    assert [(r.label, r.horses) for r in ts.club_vs_others(runs, clubs)] == [("一口クラブ", 1), ("個人・法人", 2)]


def test_by_category_class_and_venue():
    runs = [trun("A", distance=1200), trun("B", surface="dirt", distance=1800),
            trun("C", surface="jump", distance=3000, cls="障害オープン"),
            trun("D", grade="GII", cls="オープン"), trun("E", cls="500万下", venue=("01", "札幌"))]
    assert [r.label for r in ts.by_category(runs)] == ["芝・短距離", "芝・マイル", "ダ・中距離", "障害"]
    assert [r.label for r in ts.by_class(runs)] == ["1勝クラス", "重賞", "障害"]
    assert [r.label for r in ts.by_venue(runs)] == ["札幌", "東京"]


def test_by_sex_and_age():
    runs = [trun("A", sex="牝", age=2), trun("B", sex="牝", age=7), trun("C", sex="セ", age=4)]
    assert [r.label for r in ts.by_sex(runs)] == ["牝", "セ"]
    ages = ts.by_sex_age(runs)
    assert [r.label for r in ages["牝"]] == ["2歳", "6歳以上"] and ages["牡"] == []


def test_runs_since():
    runs = [trun("A", day="2024-01-01"), trun("B", day="2026-01-01")]
    assert len(ts.runs_since(runs, "2025-01-01")) == 1 and len(ts.runs_since(runs, None)) == 2


# --- 名鑑・減量記号・馬房数を使うもの ------------------------------------------------------------

def test_apprentice_counts_only_apprentice_marks():
    runs = [dict(run("A", "2026-01-05"), kinryo_mark=m) for m in ("▲", "☆", "★", None)]
    b = ts.behavior_by_trainer(runs, stables=STABLES, clubs=set(), as_of="2026-09-27")[T]
    assert ts.behavior_value("apprentice", b) == pytest.approx(0.5)    # ★は見習いでない


def test_stalls_and_horses_per_stall():
    runs = [run(f"T{i}", "2026-05-05", T) for i in range(10)] + \
           [run(f"U{i}", "2026-05-05", U) for i in range(30)]
    beh = ts.behavior_by_trainer(runs, stables=STABLES, clubs=set(), as_of="2026-09-27")
    rows = {i.key: i for i in ts.indicators(T, beh, {}, set(STABLES), field_by_sex=ts.sex_field(beh),
                                            stalls={T: 20, U: 20})}
    assert rows["stalls"].value == 20 and rows["stalls"].average == pytest.approx(20)
    assert rows["horses_per_stall"].value == pytest.approx(0.5)
    assert rows["horses_per_stall"].average == pytest.approx(40 / 40)
    none = {i.key: i for i in ts.indicators(T, beh, {}, set(STABLES), field_by_sex={}, stalls={})}
    assert none["stalls"].value is None and none["horses_per_stall"].value is None
