"""予想ボードのTier（A/B/C/D）の自動仮配置。"""

import pytest

from keiba_analysis.racing import tier


def race(grade=None, class_condition=None, venue_code="09", distance_m=2400):
    return {"grade": grade, "class_condition": class_condition,
            "venue_code": venue_code, "distance_m": distance_m}


def run(level_grade=None, level_class=None, finish=1, n_runners=16,
        venue_code="09", distance_m=2400):
    return {"grade": level_grade, "class_condition": level_class,
            "finish_position": finish, "n_runners": n_runners,
            "venue_code": venue_code, "distance_m": distance_m}


GII = race(grade="GII", class_condition="オープン")


# --- クラスの序列 -------------------------------------------------------------------


def test_grades_outrank_conditions():
    levels = [tier.race_level(race(grade=g)) for g in ("GI", "GII", "GIII", "L")]
    assert levels == sorted(levels, reverse=True)
    assert levels[-1] > tier.race_level(race(class_condition="オープン"))
    conditions = ["オープン", "3勝クラス", "2勝クラス", "1勝クラス", "未勝利", "新馬"]
    values = [tier.race_level(race(class_condition=c)) for c in conditions]
    assert values == sorted(values, reverse=True)


def test_full_width_digits_are_the_same_class():
    """出馬表由来は全角（`１勝クラス`）なので、そろえてから読む。"""
    assert tier.race_level(race(class_condition="１勝クラス")) == 1.0
    # 「牝」「見習騎手」などの付記が付いていても同じクラス
    assert tier.race_level(race(class_condition="1勝クラス 牝")) == 1.0


def test_old_class_names_read_as_the_current_ones():
    """2022年以前（Target由来）の旧呼称は、今のクラスと同じレベルで読む。"""
    assert tier.race_level(race(class_condition="500万下")) == 1.0
    assert tier.race_level(race(class_condition="1000万下 牝")) == 2.0
    assert tier.race_level(race(class_condition="900万下")) == 2.0
    assert tier.race_level(race(class_condition="1600万下")) == 3.0
    assert tier.race_level(race(class_condition="未出走")) == 0.0


def test_listed_spelled_out_is_the_same_as_l():
    """grade が「リステッド」と書かれたレースもある。L と同じに読む。"""
    assert tier.race_level(race(grade="リステッド")) == tier.race_level(race(grade="L"))


def test_unknown_class_has_no_level():
    assert tier.race_level(race()) is None
    assert tier.race_level(race(class_condition="謎の条件")) is None


def test_grade_wins_over_the_condition():
    """重賞は class_condition が「オープン」なので、grade を先に見る。"""
    assert tier.race_level(race(grade="GI", class_condition="オープン")) == 7.0


# --- 1走の値 -----------------------------------------------------------------------


def test_winning_counts_as_one_class_above():
    assert tier.run_value(run(level_class="2勝クラス", finish=1)) == 3.0


def test_placing_and_merely_coping():
    assert tier.run_value(run(level_class="2勝クラス", finish=3)) == 2.5
    # 18頭立ての5着は上位30%以内なので「通用した」
    assert tier.run_value(run(level_class="2勝クラス", finish=5, n_runners=18)) == 2.0


def test_coping_is_judged_by_the_size_of_the_field():
    """「5着以内」という頭数を見ない絶対ルールは持たない。

    8頭立ての5着を「通用した」にすると、少頭数で中位に沈んだ馬が過大評価される。
    """
    assert tier.run_value(run(level_class="2勝クラス", finish=5, n_runners=8)) < 2.0
    assert tier.run_value(run(level_class="2勝クラス", finish=2, n_runners=8)) == 2.5


def test_being_beaten_drops_the_horse_two_classes():
    """格上に出て負け続けただけでレベルが積み上がらないこと。

    減点が1.5段だった頃は「GIで大敗」が 5.5 になり、**オープンを勝った馬（5.0）や
    3勝クラスを勝った馬（4.0）より高かった**。これがAの水増しの主因だった。
    """
    beaten_in_g1 = tier.run_value(run(level_grade="GI", finish=18, n_runners=18))
    assert beaten_in_g1 == 4.0
    # 3勝クラスを勝った馬と並ぶところまで。それ以上にはしない
    assert beaten_in_g1 == tier.run_value(run(level_class="3勝クラス", finish=1))
    assert beaten_in_g1 < tier.run_value(run(level_class="オープン", finish=1))


def test_runs_without_a_finish_are_skipped():
    assert tier.run_value(run(level_class="2勝クラス", finish=None)) is None
    assert tier.run_value(run(finish=1)) is None          # クラスが分からない


# --- 実績レベル ---------------------------------------------------------------------


def climbing_winner():
    """条件戦を1つずつ勝ち上がって、前走でGIIを勝った馬（新しい順）。"""
    return [run(level_grade="GII", level_class="オープン", finish=1),   # 7.0
            run(level_class="2勝クラス", finish=1),                     # 3.0
            run(level_class="1勝クラス", finish=1),                     # 2.0
            run(level_class="新馬", finish=1)]                          # 1.0


def test_a_classic_winner_is_not_diluted_by_her_early_runs():
    """クラシック世代は、重賞勝ちが古い条件戦の走に薄められにくい。

    上位3走の単純平均だった頃は (7+3+2)/3 = 4.0 で、秋華賞ではDだった。
    古馬戦の集計（単純平均に近い）より、良い走を重く見る。
    """
    classic, used = tier.experience_level(climbing_winner(), gen="classic")
    old, _ = tier.experience_level(climbing_winner(), gen="old")
    assert used == 4
    assert classic > 4.0 and classic > old
    assert classic < 7.0                  # 1走だけの好走をそのまま信じはしない


def test_the_order_of_the_runs_does_not_matter():
    """走の新しさでは重みを変えない。

    新しい走ほど重くすると、重賞の前のトライアルを叩きで負けた馬が大きく下がり、
    重賞の盤がほぼDになった。
    """
    slumping = [run(level_class="2勝クラス", finish=16, n_runners=16),   # -1.0（前走）
                run(level_class="2勝クラス", finish=1), run(level_class="2勝クラス", finish=1)]
    recovered = [slumping[1], slumping[2], slumping[0]]
    for gen in ("classic", "old"):
        assert tier.experience_level(slumping, gen=gen)[0] == pytest.approx(
            tier.experience_level(recovered, gen=gen)[0])


def test_one_heavy_defeat_does_not_wreck_a_good_record():
    """負けは重く見ず、いいところで評価する。GIの好走が1走の大敗で崩れにくい。"""
    good = [run(level_grade="GI", finish=2, n_runners=18) for _ in range(3)]          # 7.5 ×3
    beaten = [run(level_grade="GII", finish=12, n_runners=12), *good]                 # 前走 3.0
    for gen in ("classic", "old"):
        drop = tier.experience_level(good, gen=gen)[0] - tier.experience_level(beaten, gen=gen)[0]
        assert 0 < drop < 0.5


def test_a_couple_of_good_runs_no_longer_hide_the_bad_ones():
    """「2走良くて3走大敗」は、3走とも勝っている馬には届かない。"""
    mixed = [run(level_class="2勝クラス", finish=1),                      # 3.0
             run(level_class="2勝クラス", finish=1),                      # 3.0
             run(level_class="2勝クラス", finish=15, n_runners=16),       # -1.0
             run(level_class="2勝クラス", finish=16, n_runners=16),       # -1.0
             run(level_class="2勝クラス", finish=14, n_runners=16)]       # -1.0
    solid = [run(level_class="2勝クラス", finish=1) for _ in range(5)]
    for gen in ("classic", "old"):
        assert tier.experience_level(mixed, gen=gen)[0] < tier.experience_level(solid, gen=gen)[0]


def test_the_generation_comes_from_the_age_condition():
    assert tier.generation({"age_condition": "3歳"}) == "classic"
    assert tier.generation({"age_condition": "２歳"}) == "classic"     # 全角でも同じ
    assert tier.generation({"age_condition": "3歳以上"}) == "old"
    assert tier.generation({"age_condition": "4歳以上"}) == "old"
    assert tier.generation({}) == "old"                                # 分からなければ古馬戦


def test_score_horse_uses_the_generation_of_todays_race():
    classic = tier.score_horse({**race(grade="GI"), "age_condition": "3歳"},
                               climbing_winner(), [], None, base_level=7.0)
    old = tier.score_horse({**race(grade="GI"), "age_condition": "3歳以上"},
                           climbing_winner(), [], None, base_level=7.0)
    assert classic.experience > old.experience


def test_running_in_a_big_race_without_coping_does_not_lift_the_horse():
    """GIに出ただけ（大敗）の馬がGI級に見えないこと。"""
    beaten = [run(level_grade="GI", finish=17, n_runners=18) for _ in range(3)]
    level, _ = tier.experience_level(beaten)
    assert level == pytest.approx(4.0)                   # GI(7.0) から2段下げる
    assert level < tier.race_level(race(grade="L"))      # リステッドでも足りない
    # 条件戦をきちんと勝ってきた馬に追い越されるところまで下げる
    assert level == tier.experience_level(
        [run(level_class="3勝クラス", finish=1) for _ in range(3)]
    )[0]
    assert level < tier.experience_level(
        [run(level_class="オープン", finish=1) for _ in range(3)]
    )[0]


def test_experience_without_any_usable_run():
    assert tier.experience_level([]) == (None, 0)


# --- 倒した相手 ---------------------------------------------------------------------


def timed(level_grade=None, level_class=None, finish=1, time_sec=120.0, horse_id="me",
          race_id="r1", distance_m=2000):
    return {**run(level_grade, level_class, finish), "time_sec": time_sec,
            "horse_id": horse_id, "race_id": race_id, "distance_m": distance_m}


def field_of(*others, me_time=120.0):
    """そのレースの上位（自分＋相手）。others は (馬ID, 着順, タイム)。"""
    rows = [{"horse_id": "me", "horse_name": "自分", "finish_position": 1, "time_sec": me_time}]
    rows += [{"horse_id": h, "horse_name": h, "finish_position": f, "time_sec": t}
             for h, f, t in others]
    return rows


GI_PLACER = [run(level_grade="GI", finish=2, n_runners=18)]          # 強さ 7.5
MAIDEN_LOSER = [run(level_class="未勝利", finish=12, n_runners=16)]   # 強さ -3.0


def test_beating_a_strong_horse_is_worth_more_than_beating_a_weak_one():
    """同じGII勝ちでも、GI好走馬に先着した走のほうが高い。"""
    me = timed(level_grade="GII")
    strong, _ = tier.read_run(me, field_of(("x", 2, 120.5)), {"x": GI_PLACER})
    weak, _ = tier.read_run(me, field_of(("x", 2, 120.5)), {"x": MAIDEN_LOSER})
    assert strong > tier.run_value(me) > weak


def test_a_bigger_margin_over_the_same_horse_is_worth_more():
    me = timed(level_grade="GII")
    close, _ = tier.read_run(me, field_of(("x", 2, 120.1)), {"x": GI_PLACER})
    clear, _ = tier.read_run(me, field_of(("x", 2, 121.0)), {"x": GI_PLACER})
    assert clear > close


def test_losing_narrowly_to_a_strong_horse_still_reads_well():
    """負けた走も「誰に何秒負けたか」で読む。GI好走馬にクビ差なら、ただの2着より高い。"""
    me = {**timed(level_grade="GII", finish=2), "time_sec": 120.1}
    field = [{"horse_id": "x", "horse_name": "x", "finish_position": 1, "time_sec": 120.0},
             {"horse_id": "me", "horse_name": "自分", "finish_position": 2, "time_sec": 120.1}]
    value, opponents = tier.read_run(me, field, {"x": GI_PLACER})
    assert value > tier.run_value(me)
    assert opponents[0].gap_sec > 0                      # 負け


def test_seconds_are_compared_per_1000m():
    """同じ0.5秒差でも、短い距離のほうが大きい差として読む。"""
    sprint = timed(level_grade="GII", distance_m=1200)
    stayer = timed(level_grade="GII", distance_m=3000)
    field, opps = field_of(("x", 2, 120.5)), {"x": GI_PLACER}
    assert tier.read_run(sprint, field, opps)[0] > tier.read_run(stayer, field, opps)[0]


def test_without_opponent_material_the_run_keeps_its_class_value():
    me = timed(level_class="2勝クラス")
    assert tier.read_run(me, [], {})[0] == tier.run_value(me)
    assert tier.read_run(me, field_of(("x", 2, 120.5)), {})[0] == tier.run_value(me)
    assert tier.read_run({**me, "time_sec": None}, field_of(("x", 2, 120.5)),
                         {"x": GI_PLACER})[0] == tier.run_value(me)
    # 相手を渡さなければ、実績レベルは今までどおりクラス×着順だけ
    assert tier.experience_level([me]) == (tier.run_value(me), 1)


def test_one_odd_opponent_does_not_wreck_the_reading():
    """相手5頭の中央値なので、1頭だけ極端に弱い相手がいても読みは崩れない。"""
    me = timed(level_grade="GII")
    others = [(f"x{i}", i + 2, 120.5) for i in range(5)]
    opps = {f"x{i}": GI_PLACER for i in range(5)}
    even, _ = tier.read_run(me, field_of(*others), opps)
    odd, _ = tier.read_run(me, field_of(*others), {**opps, "x4": MAIDEN_LOSER})
    assert odd == pytest.approx(even)


def test_only_the_top_five_others_are_opponents():
    me = timed(level_grade="GII")
    others = [(f"x{i}", i + 2, 120.5 + i * 0.1) for i in range(7)]
    _, opponents = tier.read_run(me, field_of(*others), {f"x{i}": GI_PLACER for i in range(7)})
    assert [o.name for o in opponents] == ["x0", "x1", "x2", "x3", "x4"]


def test_popularity_counts_towards_the_opponent_strength():
    """「GIで4番人気」は市場がGI上位とみていた証拠。人気薄より強いとみる。"""
    fancied = [{**run(level_grade="GI", finish=7, n_runners=18), "popularity": 1}]
    outsider = [{**run(level_grade="GI", finish=7, n_runners=18), "popularity": 18}]
    assert tier.opponent_strength(fancied) > tier.opponent_strength(outsider)
    assert tier.opponent_strength([]) is None


def test_the_explanation_names_the_strongest_horse_beaten():
    me = {**timed(level_grade="GII"), "race_name": "ローズS"}
    fields = {"r1": field_of(("エンネ", 2, 120.5), ("弱い馬", 3, 120.7))}
    opps = {"エンネ": GI_PLACER, "弱い馬": MAIDEN_LOSER}
    score = tier.score_horse(GII, [me], [], None, base_level=6.0,
                             fields=fields, opponent_runs=opps)
    assert "ローズSでエンネ" in score.explanation
    assert "0.5秒先着" in score.explanation


# --- 適性（出走が少ないときの扱い） ---------------------------------------------------


def test_small_samples_are_pulled_towards_the_average():
    """3走の複勝率100%を真に受けない。"""
    assert tier.shrunk_rate(3, 3) < 1.0
    assert tier.shrunk_rate(3, 3) < tier.shrunk_rate(30, 30)
    assert tier.shrunk_rate(0, 0) == pytest.approx(tier.PRIOR_RATE)   # 未出走は平均


def test_course_fit_reads_the_same_venue_and_a_nearby_distance():
    good = [run(level_class="2勝クラス", finish=1, venue_code="09", distance_m=2400)
            for _ in range(8)]
    bad = [run(level_class="2勝クラス", finish=12, venue_code="09", distance_m=2400)
           for _ in range(8)]
    assert tier.course_fit(good, GII) > tier.course_fit(bad, GII)
    # 別の場・離れた距離の走は材料にならない（平均寄りに戻る）
    elsewhere = [run(level_class="2勝クラス", finish=1, venue_code="05", distance_m=1200)
                 for _ in range(8)]
    assert tier.course_fit(elsewhere, GII) == pytest.approx(0.5, abs=0.02)


def test_pace_fit_is_neutral_without_material():
    assert tier.pace_fit([], "H") == 0.5
    assert tier.pace_fit([{"race_first_3f": 34.0, "race_last_3f": 36.0}], None) == 0.5


# --- Tierの切り方 -------------------------------------------------------------------


def test_tier_boundaries():
    """線は「実測でどれだけ走る層か」で引いてある（B=勝率20%前後 / C=複勝率30%前後）。"""
    assert tier.tier_of(0.85) == "B" and tier.tier_of(2.0) == "B"
    assert tier.tier_of(0.84) == "C" and tier.tier_of(-0.9) == "C"
    assert tier.tier_of(-0.91) == "D"


def test_a_is_never_decided_by_a_threshold():
    """Aは「そのレースで抜けているか」で決まるので、1頭だけ見ても決まらない。

    どれだけ margin が高くても、この関数はAを返さない。
    """
    assert tier.tier_of(99.0) == "B"
    assert "A" not in {name for name, _ in tier.TIER_THRESHOLDS}


# --- A（抜けた馬） -------------------------------------------------------------------


def test_a_horse_clear_of_the_field_is_the_only_a():
    picked = tier.standouts([("h1", 3.0), ("h2", 0.9), ("h3", 0.4)])
    assert picked == {"h1"}


def test_several_horses_can_be_clear_together():
    """抜けた集団が2頭・3頭のこともある（1頭に絞らない）。"""
    assert tier.standouts([("h1", 3.0), ("h2", 2.9), ("h3", 0.4)]) == {"h1", "h2"}
    assert tier.standouts(
        [("h1", 3.2), ("h2", 3.0), ("h3", 2.9), ("h4", 0.4)]
    ) == {"h1", "h2", "h3"}


def test_most_races_have_no_a_at_all():
    """これが普通の状態（実測で93%のレースはAなし）。差が空かなければ誰もAにしない。"""
    assert tier.standouts([("h1", 3.0), ("h2", 2.0), ("h3", 1.5)]) == set()
    assert tier.standouts([]) == set()
    assert tier.standouts([("h1", 5.0)]) == set()       # 1頭だけでは「抜けている」と言えない


def test_a_horse_clear_of_a_weak_field_still_needs_to_belong_here():
    """他が弱いだけの馬をAにしない。今回のクラスに通用するレベルであること。"""
    assert tier.standouts([("h1", 0.4), ("h2", -3.0)]) == set()
    assert tier.standouts([("h1", 0.5), ("h2", -3.0)]) == {"h1"}


def test_a_crowd_at_the_top_is_not_a_standout():
    """4頭以上が横並びなら「抜けている」とは言えない。"""
    crowd = [("h1", 3.0), ("h2", 3.0), ("h3", 3.0), ("h4", 3.0), ("h5", 0.0)]
    assert tier.standouts(crowd) == set()


def test_the_reported_gap_is_the_one_that_made_them_a():
    """説明に出す差は「切れ目の差」。基準（2.0段）より小さい数字が出てはいけない。

    集団に入ったが `STANDOUT_FLOOR` に届かなかった馬との距離を出してしまうと、
    「2.0段以上でAになる」はずなのに説明が「1.0段の差」になって辻褄が合わなくなる。
    """
    chosen, gap = tier.standout_cut(
        [("h1", 0.58), ("h2", 0.58), ("h3", -0.42), ("h4", -2.5)]
    )
    assert chosen == {"h1", "h2"}           # h3 は floor に届かないのでAにしない
    assert gap >= tier.STANDOUT_GAP         # 出す差は h3→h4 の切れ目のほう
    assert gap == pytest.approx(2.08)


def test_every_a_in_a_race_is_told_the_same_gap():
    """その差でまとめてAになったので、馬ごとに違う数字を出すと誤解を招く。"""
    entries = [{"horse_id": "h1"}, {"horse_id": "h2"}, {"horse_id": "h3"}]
    runs = {
        "h1": [run(level_grade="GI", finish=1)],                      # 8.0
        "h2": [run(level_grade="GI", finish=2)],                      # 7.5
        "h3": [run(level_class="未勝利", finish=12, n_runners=16)],    # -3.0
    }
    scores = tier.assign(race(class_condition="2勝クラス"), entries, runs, {}, None)
    assert scores["h1"].tier == "A" and scores["h2"].tier == "A"
    gaps = {s.explanation.split("次の馬に")[1] for s in scores.values() if s.tier == "A"}
    assert len(gaps) == 1                    # 2頭とも同じ差を出す


def test_a_is_decided_inside_the_race_only():
    """他のレースの馬をいくら足しても、そのレースのAの顔ぶれは変わらない。"""
    field = [("h1", 3.0), ("h2", 0.5), ("h3", 0.2)]
    assert tier.standouts(field) == {"h1"}
    assert tier.standouts(list(reversed(field))) == {"h1"}   # 並び順にも左右されない


def test_fitness_alone_cannot_lift_a_much_weaker_horse():
    """適性が最高でも、動くのは1段ぶんに満たない（実績が主軸）。"""
    weak = [run(level_class="未勝利", finish=1) for _ in range(5)]
    score = tier.score_horse(GII, weak, [], "H", base_level=6.0)
    assert score.adjust <= tier.PACE_WEIGHT + tier.COURSE_WEIGHT
    assert score.tier == "D"


def test_assign_covers_every_entry(monkeypatch):
    entries = [{"horse_id": "h1"}, {"horse_id": "h2"}]
    strong = [run(level_grade="GI", finish=1) for _ in range(3)]
    scores = tier.assign(GII, entries, {"h1": strong}, {}, "M")
    assert set(scores) == {"h1", "h2"}
    assert scores["h1"].tier == "A"                      # GI勝ち → GIIなら1段上
    assert scores["h2"].runs == 0                        # 過去走が無い馬も置く
    assert "過去走がまだ手元にありません" in scores["h2"].explanation


# --- 未出走馬（レースの顔ぶれで置き場所が変わる）----------------------------------------


def test_a_maiden_race_does_not_collapse_into_the_bottom_lane():
    """全頭が未出走なら、馬を見分ける材料がゼロ。全員を同じ段（C）に置く。

    ここで全頭をDに落とすと、新馬戦の盤が真っ白になって使いものにならない。
    """
    entries = [{"horse_id": f"h{i}"} for i in range(8)]
    scores = tier.assign(race(class_condition="新馬"), entries, {}, {}, None)
    assert {s.tier for s in scores.values()} == {"C"}
    assert all(s.runs == 0 for s in scores.values())


def test_a_maiden_among_experienced_horses_sits_in_the_bottom_lane():
    """経験馬と混走している未出走馬は、実測で複勝率12%ほど（D相当）。"""
    entries = [{"horse_id": "experienced"}, {"horse_id": "fresh"}]
    runs = {"experienced": [run(level_class="未勝利", finish=2)]}
    scores = tier.assign(race(class_condition="未勝利"), entries, runs, {}, None)
    assert scores["fresh"].tier == "D"
    assert scores["experienced"].tier != "D"


def test_the_unraced_pile_sits_well_inside_its_lane():
    """未出走馬は適性の材料も無いので補正が0になり、margin がこの値ちょうどに揃う。

    以前は決め打ちの2.0がC/Dの境界と一致していて、全体の19%が線の上に乗っていた。
    閾値を0.1動かすだけで数千頭が一斉に段を移る状態だったので、境界から離す。
    """
    lines = [threshold for _, threshold in tier.TIER_THRESHOLDS]
    for gap in (tier.UNRACED_GAP_MAIDEN, tier.UNRACED_GAP_MIXED):
        for line in lines:
            assert abs(-gap - line) >= 0.4, f"margin {-gap} が線 {line} に近すぎる"

    # 補正が入らない（＝必ずその値ちょうどに来る）ことも押さえる
    scores = tier.assign(race(class_condition="新馬"), [{"horse_id": "h1"}], {}, {}, None)
    assert scores["h1"].adjust == 0.0
    assert scores["h1"].margin == pytest.approx(-tier.UNRACED_GAP_MAIDEN)


def test_the_explanation_says_which_kind_of_unraced_it_is():
    maiden = tier.assign(race(class_condition="新馬"), [{"horse_id": "h1"}], {}, {}, None)
    assert "全頭が未出走" in maiden["h1"].explanation

    mixed = tier.assign(
        race(class_condition="未勝利"),
        [{"horse_id": "h1"}, {"horse_id": "h2"}],
        {"h2": [run(level_class="未勝利", finish=1)]}, {}, None,
    )
    assert "全頭が未出走" not in mixed["h1"].explanation
    assert "複勝率12%" in mixed["h1"].explanation


def test_assign_without_a_known_class():
    assert tier.assign(race(), [{"horse_id": "h1"}], {}, {}, "M") == {}


def test_explanation_mentions_every_part():
    strong = [run(level_grade="GIII", finish=1) for _ in range(3)]
    score = tier.score_horse(GII, strong, [], "M", base_level=6.0)
    for word in ("実績レベル", "ペース適性", "コース適性", "今回のクラスとの差"):
        assert word in score.explanation


# --- 較正（過去レースでの答え合わせ） -------------------------------------------------


def test_calibration_separates_the_tiers():
    """実測値がA>B>C>Dの順に並んでいること（並びが崩れたら判定が壊れている）。"""
    wins = [tier.CALIBRATION[t]["win"] for t in tier.TIERS]
    top3 = [tier.CALIBRATION[t]["top3"] for t in tier.TIERS]
    assert wins == sorted(wins, reverse=True)
    assert top3 == sorted(top3, reverse=True)
    assert wins[0] > wins[-1] * 3        # Aの勝率はDの3倍以上あった


def test_the_board_does_not_talk_about_returns():
    """盤は勝率・複勝率だけで語る。回収率はどの段も100%に届かないので持ち込まない。

    「期待値あり」「回収率◯%」と書くと「買えば得」と読めてしまう。
    妙味は、映像や展開を見て手で動かすところの仕事。
    """
    note = tier.CALIBRATION_NOTE
    assert "回収率" not in note and "期待値" not in note
    assert "勝率" in note and "複勝率" in note
    assert all("win_return" not in row for row in tier.CALIBRATION.values())


def test_the_tier_names_say_how_often_they_hit():
    """段の名前も実測のヒット率で言い切る（「期待値あり」とは書かない）。"""
    for name in ("B", "C"):
        meaning = tier.TIER_MEANINGS[name]
        assert "期待値" not in meaning, name
        assert "%" in meaning, name
    assert "勝率" in tier.TIER_MEANINGS["B"]
    assert "複勝率" in tier.TIER_MEANINGS["C"]


def test_calibration_note_warns_that_a_is_rare():
    """A段が空でも壊れていない、と分かる書き方にしておく。"""
    assert "抜けている馬だけ" in tier.CALIBRATION_NOTE
    assert tier.A_RACE_SHARE < 0.1                      # Aが出るのは1割未満のレース
    assert sum(tier.A_FIELD_SIZES.values()) > 0 and max(tier.A_FIELD_SIZES) <= tier.MAX_STANDOUT


# --- 枠順確定前（クラスがレース名にしか無い）------------------------------------------


def test_class_is_read_from_the_race_name_when_the_condition_is_missing():
    """枠順確定前は class_condition が空で入ることがある（レース名から拾う）。"""
    assert tier.race_level(race(class_condition=None)) is None      # 名前も無ければ分からない
    for name, level in (
        ("3歳以上1勝クラス", 1.0),
        ("3歳以上2勝クラス", 2.0),
        ("2歳新馬", 0.0),
        ("2歳未勝利", 0.0),
        ("3歳以上障害未勝利", 0.0),       # 障害でもクラスは読める
    ):
        assert tier.race_level({"race_name": name}) == level, name


def test_the_condition_wins_over_the_race_name():
    """ページから読めた条件のほうが正確なので、そちらを優先する。"""
    assert tier.race_level(
        {"race_name": "3歳以上1勝クラス", "class_condition": "オープン"}
    ) == 4.0


def test_a_named_race_without_a_class_is_still_unknown():
    """名前だけのレース（条件がどこにも無い）は、今までどおり判定しない。"""
    assert tier.race_level({"race_name": "サフラン賞"}) is None
