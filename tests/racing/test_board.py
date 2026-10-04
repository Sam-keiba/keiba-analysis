"""予想ボードの配置づくり（縦=Tier、横=道中の隊列）。"""

import pytest

from keiba_analysis.racing import board
from keiba_analysis.racing.tier import TierScore


def run(corner="5-5-5-5", n_runners=16):
    return {"corner_passing": corner, "n_runners": n_runners}


def entry(horse_id, name="テスト馬", umaban=1, waku=1):
    return {"horse_id": horse_id, "horse_name": name, "umaban": umaban, "waku": waku}


def score(tier="B", margin=0.0):
    return TierScore(
        tier=tier, experience=5.0, pace_fit=0.5, course_fit=0.5, adjust=0.0,
        level=5.0, margin=margin, runs=3, explanation="テスト用",
    )


# --- 横軸（道中の隊列） ---------------------------------------------------------------


def test_front_runners_sit_on_the_right():
    """右端がFrontRunner（先行・逃げ）、左端がSave runner（後方待機）。"""
    front = board.horizontal_position([run("1-1-1-1")])
    back = board.horizontal_position([run("16-16-15-14")])
    assert front > back
    assert front == pytest.approx(1.0)        # 常に先頭なら右端
    assert back < 0.15


def test_position_is_the_average_of_the_recent_runs():
    mixed = board.horizontal_position([run("1-1-1-1"), run("16-16-16-16")])
    assert mixed == pytest.approx(0.5, abs=0.01)


def test_horses_without_a_corner_passing_have_no_position():
    assert board.horizontal_position([]) is None
    assert board.horizontal_position([run(corner=None)]) is None


def test_unraced_horses_are_placed_in_the_middle_and_flagged():
    """新馬は材料が無いので中央に置き、そうと分かるようにする。"""
    markers = board.build_markers([entry("h1")], {"h1": score()}, {"h1": []})
    assert markers[0]["position"] == board.NEUTRAL_POSITION
    assert markers[0]["has_position"] is False
    # 材料がある馬には立てない
    with_runs = board.build_markers([entry("h1")], {"h1": score()}, {"h1": [run()]})
    assert with_runs[0]["has_position"] is True


# --- 重なり回避 ---------------------------------------------------------------------


def test_horses_close_together_are_stacked_on_different_rows():
    """横が近い馬は段をずらす（マーカーが重なって読めなくなるため）。"""
    entries = [entry(f"h{i}", umaban=i) for i in range(1, 4)]
    runs = {f"h{i}": [run("8-8-8-8")] for i in range(1, 4)}   # 3頭とも同じ位置
    markers = board.build_markers(entries, {f"h{i}": score() for i in range(1, 4)}, runs)
    offsets = [m["lane_offset"] for m in markers]
    assert len(set(offsets)) == 3                      # 全部ちがう段


def test_horses_far_apart_can_share_a_row():
    entries = [entry("h1", umaban=1), entry("h2", umaban=2)]
    runs = {"h1": [run("1-1-1-1")], "h2": [run("16-16-16-16")]}
    markers = board.build_markers(entries, {"h1": score(), "h2": score()}, runs)
    assert markers[0]["lane_offset"] == markers[1]["lane_offset"]   # 離れているので同じ段


def test_stacking_is_per_lane():
    """段の割り振りはレーンごと（A の馬が B の段を埋めない）。"""
    entries = [entry("h1", umaban=1), entry("h2", umaban=2)]
    runs = {"h1": [run("8-8-8-8")], "h2": [run("8-8-8-8")]}
    markers = board.build_markers(entries, {"h1": score("A"), "h2": score("C")}, runs)
    assert markers[0]["lane_offset"] == markers[1]["lane_offset"]   # レーンが違えば同じ段でよい


# --- 保存済みの配置 -----------------------------------------------------------------


def test_saved_placement_wins_over_the_automatic_one():
    """手で動かした結果があれば、自動仮配置より優先する。"""
    saved = {"h1": {"tier": "A", "position": 0.1, "lane_offset": 0.9,
                    "comment": "映像で高評価", "is_manual": 1}}
    markers = board.build_markers(
        [entry("h1")], {"h1": score("D")}, {"h1": [run("1-1-1-1")]}, saved
    )
    marker = markers[0]
    assert (marker["tier"], marker["position"], marker["lane_offset"]) == ("A", 0.1, 0.9)
    assert marker["comment"] == "映像で高評価" and marker["is_manual"] is True


def test_horses_without_a_saved_row_keep_the_automatic_placement():
    saved = {"h1": {"tier": "A", "position": 0.1, "lane_offset": 0.9, "is_manual": 1}}
    markers = {
        m["horse_id"]: m for m in board.build_markers(
            [entry("h1"), entry("h2", umaban=2)],
            {"h1": score("D"), "h2": score("C")},
            {"h1": [run()], "h2": [run("1-1-1-1")]},
            saved,
        )
    }
    assert markers["h2"]["tier"] == "C" and markers["h2"]["is_manual"] is False
    assert markers["h2"]["lane_offset"] is not None      # 自動で段が決まる


# --- 盤に渡すデータ -----------------------------------------------------------------


def test_payload_carries_the_four_lanes_and_the_axis():
    payload = board.board_payload([entry("h1")], {"h1": score()}, {"h1": [run()]})
    assert [lane["key"] for lane in payload["lanes"]] == ["A", "B", "C", "D"]
    assert all(lane["meaning"] for lane in payload["lanes"])     # 各レーンの意味を常に出す
    assert payload["axis"] == {"left": board.AXIS_LEFT, "right": board.AXIS_RIGHT}


def test_the_board_holds_together_when_no_horse_is_an_a():
    """Aは7%のレースでしか出ないので、**A段が空なのが普通の状態**。

    空でも段は出す（「今日は抜けた馬がいない」という情報そのものになる）。
    """
    entries = [entry(f"h{i}", umaban=i) for i in range(1, 9)]
    scores = {f"h{i}": score(tier="B" if i < 5 else "C") for i in range(1, 9)}
    runs = {f"h{i}": [run()] for i in range(1, 9)}

    payload = board.board_payload(entries, scores, runs)
    assert [lane["key"] for lane in payload["lanes"]] == ["A", "B", "C", "D"]   # 段は畳まない
    assert not [m for m in payload["markers"] if m["tier"] == "A"]              # Aは空
    assert len(payload["markers"]) == 8                                         # 全馬は置かれる


def test_the_lane_wording_comes_from_the_tier_module():
    """同じ文言を2か所に置くと、片方だけ直す事故が起きる。"""
    from keiba_analysis.racing import tier as tier_module

    lanes = board.board_payload([entry("h1")], {"h1": score()}, {"h1": [run()]})["lanes"]
    labels = {lane["key"]: lane["label"] for lane in lanes}
    meanings = {lane["key"]: lane["meaning"] for lane in lanes}
    # 見出しは「軸／相手／押さえ／消し」の2語（1行に収まる）
    assert labels == tier_module.TIER_SHORT
    # 長い説明も渡す（盤ではツールチップに回す）
    assert meanings["A"] == tier_module.TIER_MEANINGS["A"]
    assert "離している" in meanings["A"]


def test_the_lane_head_width_is_shared_with_the_marker_spacing():
    """見出しの幅と「馬を置ける幅」を別々に持つと、片方だけ古い前提で残る。

    以前はCSSに104pxが直書きで、重なりの見積もり(NOMINAL_FIELD_PX)がそれを
    前提にしていた。見出しを細くしたとき、重なり計算だけ取り残される作りだった。
    """
    assert board.NOMINAL_FIELD_PX == board.NOMINAL_BOARD_PX - board.LANE_HEAD_PX
    payload = board.board_payload([entry("h1")], {"h1": score()}, {"h1": [run()]})
    assert payload["lane_head"] == board.LANE_HEAD_PX


def test_marker_carries_the_waku_colour_and_the_reason():
    markers = board.build_markers(
        [entry("h1", name="ロブチェン", umaban=3, waku=2)], {"h1": score()}, {"h1": [run()]}
    )
    marker = markers[0]
    assert marker["horse_name"] == "ロブチェン" and marker["umaban"] == 3
    assert marker["color"] == "#2b2b2b" and marker["text_color"] == "#ffffff"   # 2枠は黒
    assert marker["explanation"] == "テスト用"


def test_entries_without_a_horse_id_are_skipped():
    """出馬表に馬IDが無い行（取り込み途中）は盤に置かない。"""
    assert board.build_markers([{"horse_name": "名前だけ"}], {}, {}) == []


def test_horses_without_a_score_land_in_the_lowest_lane():
    markers = board.build_markers([entry("h1")], {}, {"h1": [run()]})
    assert markers[0]["tier"] == "D"


# --- 古い描画で配置が巻き戻らないようにする符号 ---------------------------------------


def _markers(**kwargs):
    base = {"horse_id": "h1", "tier": "B", "position": 0.5, "lane_offset": 0.5, "comment": ""}
    base.update(kwargs)
    return [base]


def test_version_changes_when_the_placement_changes():
    """保存の前後を見分けるための符号。中身が変われば必ず変わる。"""
    original = board.markers_version(_markers())
    assert board.markers_version(_markers(tier="A")) != original
    assert board.markers_version(_markers(position=0.9)) != original
    assert board.markers_version(_markers(lane_offset=0.2)) != original
    assert board.markers_version(_markers(comment="メモ")) != original


def test_version_is_stable_for_the_same_content():
    assert board.markers_version(_markers()) == board.markers_version(_markers())
    # 並び順が違っても同じ（馬IDでそろえてから作る）
    a = [{"horse_id": "h1", "tier": "A", "position": 0.1, "lane_offset": 0.5, "comment": ""},
         {"horse_id": "h2", "tier": "B", "position": 0.2, "lane_offset": 0.5, "comment": ""}]
    assert board.markers_version(a) == board.markers_version(list(reversed(a)))


def test_payload_carries_the_version():
    payload = board.board_payload([entry("h1")], {"h1": score()}, {"h1": [run()]})
    assert payload["version"] == board.markers_version(payload["markers"])


def test_a_hand_placed_horse_does_not_disturb_the_automatic_layout():
    """手で置いた馬は、自動配置に**影響させない**。

    以前は「手で置いた馬を自動配置の馬が避ける」作りにしていたが、それだと
    1頭置いただけでレーンの組み直しが起き、**他の馬まで動いて**しまった。
    他の馬が動かないことを優先し、自動配置は手を入れた情報を見ないで組む
    （置いた馬が移動先で重なることはあるが、置いた本人は場所を分かっている）。
    """
    entries = [entry("h1", umaban=1), entry("h2", umaban=2)]
    runs = {"h1": [run("8-8-8-8")], "h2": [run("8-8-8-8")]}      # 同じ横位置
    scores = {"h1": score(), "h2": score()}
    auto = {m["horse_id"]: m for m in board.build_markers(entries, scores, runs)}

    saved = {"h1": {"tier": "B", "position": 0.5, "lane_offset": 0.5, "is_manual": 1}}
    markers = {m["horse_id"]: m for m in board.build_markers(entries, scores, runs, saved)}

    assert markers["h1"]["lane_offset"] == 0.5                   # 置いた場所のまま
    assert markers["h2"]["lane_offset"] == auto["h2"]["lane_offset"]   # 他の馬は動かない
    assert markers["h2"]["position"] == auto["h2"]["position"]


# --- マーカーが重ならないこと -------------------------------------------------------


def _overlaps(markers: list[dict]) -> list[tuple[str, str]]:
    """同じレーン・同じ段で、横が近すぎて重なっている組を返す。"""
    bad = []
    for i, a in enumerate(markers):
        for b in markers[i + 1:]:
            if a["tier"] != b["tier"] or a["lane_offset"] != b["lane_offset"]:
                continue
            need = (board.marker_width(a["horse_name"]) + board.marker_width(b["horse_name"])) / 2
            if abs(a["position"] - b["position"]) < need:
                bad.append((a["horse_name"], b["horse_name"]))
    return bad


def test_markers_do_not_overlap_in_a_real_sized_field():
    """18頭立てでも、長い名前の馬どうしが重ならないこと。"""
    entries = [entry(f"h{i}", name="カフジエメンタール", umaban=i) for i in range(1, 19)]
    # 通過順位を少しずつ変えて、実際のレースのように横位置をばらけさせる
    runs = {f"h{i}": [run(f"{i}-{i}-{i}-{i}", n_runners=18)] for i in range(1, 19)}
    markers = board.build_markers(entries, {f"h{i}": score() for i in range(1, 19)}, runs)
    assert _overlaps(markers) == []


def test_a_pile_up_is_capped_instead_of_growing_forever():
    """全頭がぴったり同じ位置という極端な場合は、段の数で歯止めをかける。

    段を増やし続けると盤がどこまでも高くなるので、上限を超えたぶんは
    少し重なってもいちばん空いている段に置く（縦に伸ばし続けるよりまし）。
    """
    entries = [entry(f"h{i}", name="カフジエメンタール", umaban=i) for i in range(1, 17)]
    runs = {f"h{i}": [run("8-8-8-8")] for i in range(1, 17)}      # 16頭とも同じ横位置
    markers = board.build_markers(entries, {f"h{i}": score() for i in range(1, 17)}, runs)
    assert len({m["lane_offset"] for m in markers}) <= board.MAX_LANE_ROWS
    assert board.lane_height(markers) <= (
        board.MAX_LANE_ROWS * board.LANE_ROW_PX + board.LANE_PADDING_PX
    )


def test_unraced_horses_are_spread_instead_of_stacked():
    """新馬戦のように全頭に通過順位が無いとき、真ん中に積み上げない。

    1点に重ねると段がその頭数ぶん必要になり、盤がとても高くなってしまう。
    """
    entries = [entry(f"h{i}", name="テストウマ", umaban=i) for i in range(1, 16)]
    markers = board.build_markers(
        entries, {f"h{i}": score() for i in range(1, 16)}, {f"h{i}": [] for i in range(1, 16)}
    )
    positions = sorted(m["position"] for m in markers)
    assert positions[0] == board.UNKNOWN_BAND[0]
    assert positions[-1] == board.UNKNOWN_BAND[1]
    assert len(set(positions)) == 15                      # 全頭ちがう横位置
    assert all(not m["has_position"] for m in markers)    # 「材料なし」の印は残る
    assert board.lane_height(markers) < 250               # 縦に伸びすぎない


def test_a_single_unraced_horse_stays_in_the_middle():
    markers = board.build_markers([entry("h1")], {"h1": score()}, {"h1": []})
    assert markers[0]["position"] == board.NEUTRAL_POSITION


def test_long_names_need_more_room_than_short_ones():
    assert board.marker_width("カフジエメンタール") > board.marker_width("ピカラ")


def test_lane_height_grows_with_the_number_of_rows():
    """段を多く使うレーンでは、縦にも重ならないようレーンを高くする。"""
    crowded = [entry(f"h{i}", name="カフジエメンタール", umaban=i) for i in range(1, 6)]
    runs = {f"h{i}": [run("8-8-8-8")] for i in range(1, 6)}
    markers = board.build_markers(crowded, {f"h{i}": score() for i in range(1, 6)}, runs)
    tall = board.lane_height(markers)

    sparse = board.build_markers([entry("h1")], {"h1": score()}, {"h1": [run()]})
    assert tall > board.lane_height(sparse)
    assert board.lane_height(sparse) == board.MIN_LANE_HEIGHT_PX   # 少なければ最低の高さ
    # 段の間隔がマーカーの高さを下回らない（縦に重ならない）
    rows = len({m["lane_offset"] for m in markers})
    assert tall / rows >= board.LANE_ROW_PX - 4


def test_payload_carries_the_lane_height():
    payload = board.board_payload([entry("h1")], {"h1": score()}, {"h1": [run()]})
    assert payload["lane_height"] == board.lane_height(payload["markers"])


# --- そのレースの中で両端まで広げる ---------------------------------------------------


def _field(positions: list[str], name="テストウマ", n_runners=18):
    """通過順位を指定して、出走表と過去走を作る。

    n_runners は通過順位を0〜1に直すときの分母なので、頭数と切り離して渡す
    （3頭だけ並べたいときでも、通過順位が端に張り付かないように）。
    """
    entries = [entry(f"h{i}", name=name, umaban=i) for i in range(1, len(positions) + 1)]
    runs = {f"h{i}": [run(p, n_runners=n_runners)] for i, p in enumerate(positions, 1)}
    scores = {f"h{i}": score() for i in range(1, len(positions) + 1)}
    return entries, scores, runs


def test_the_front_and_back_horses_reach_both_edges():
    """いちばん前の馬が右端、いちばん後ろの馬が左端に来る。"""
    entries, scores, runs = _field(["4-4-4-4", "6-6-6-6", "8-8-8-8"])
    markers = {m["horse_id"]: m for m in board.build_markers(entries, scores, runs)}
    assert markers["h1"]["position"] > markers["h2"]["position"] > markers["h3"]["position"]
    # 中団どうしの3頭でも、端から端まで使う
    assert markers["h1"]["position"] > 0.9 and markers["h3"]["position"] < 0.1


def test_edge_markers_are_not_cut_off():
    """端に置いた馬の名前が切れないこと（盤ははみ出しを切るため）。"""
    entries, scores, runs = _field(["2-2-2-2", "9-9-9-9"], name="カフジエメンタール")
    markers = board.build_markers(entries, scores, runs)
    for marker in markers:
        half = board.marker_width(marker["horse_name"]) / 2
        assert marker["position"] - half >= 0, marker["horse_name"]
        assert marker["position"] + half <= 1, marker["horse_name"]


def test_hand_placed_horses_are_not_stretched():
    entries, scores, runs = _field(["2-2-2-2", "9-9-9-9"])
    saved = {"h1": {"tier": "B", "position": 0.42, "lane_offset": 0.5, "is_manual": 1}}
    markers = {m["horse_id"]: m for m in board.build_markers(entries, scores, runs, saved)}
    assert markers["h1"]["position"] == 0.42


def test_unraced_horses_keep_the_middle_band():
    """通過順位が無い馬は広げる対象にしない（前後関係が分からないため）。"""
    entries = [entry(f"h{i}", umaban=i) for i in range(1, 4)]
    runs = {"h1": [run("1-1-1-1", n_runners=3)], "h2": [], "h3": []}
    markers = {m["horse_id"]: m for m in board.build_markers(
        entries, {f"h{i}": score() for i in range(1, 4)}, runs
    )}
    assert markers["h2"]["position"] == board.UNKNOWN_BAND[0]
    assert markers["h3"]["position"] == board.UNKNOWN_BAND[1]


def test_stretching_is_skipped_when_it_cannot_be_done():
    # 材料のある馬が1頭だけ（比べる相手がいないので、もとの位置のまま）
    entries, scores, runs = _field(["5-5-5-5"])
    alone = board.build_markers(entries, scores, runs)[0]
    assert alone["position"] == board.horizontal_position(runs["h1"])

    # 全馬が同じ通過順位（割り算できない）
    entries, scores, runs = _field(["5-5-5-5", "5-5-5-5", "5-5-5-5"])
    markers = board.build_markers(entries, scores, runs)
    assert len({m["position"] for m in markers}) == 1      # 動かさない


def test_markers_still_do_not_overlap_after_stretching():
    entries, scores, runs = _field(
        [f"{i}-{i}-{i}-{i}" for i in range(1, 19)], name="カフジエメンタール"
    )
    assert _overlaps(board.build_markers(entries, scores, runs)) == []


# --- 消した馬 -----------------------------------------------------------------------


def test_markers_carry_whether_the_horse_is_crossed_out():
    saved = {"h1": {"tier": "B", "position": 0.5, "lane_offset": 0.5, "is_excluded": 1}}
    markers = {
        m["horse_id"]: m for m in board.build_markers(
            [entry("h1"), entry("h2", umaban=2)],
            {"h1": score(), "h2": score()},
            {"h1": [run()], "h2": [run()]},
            saved,
        )
    }
    assert markers["h1"]["is_excluded"] is True
    assert markers["h2"]["is_excluded"] is False


def test_crossing_a_horse_out_changes_the_version():
    """消した直後に「中身が同じ」と見なされると、盤が描き直されず表示が戻ってしまう。"""
    base = {"horse_id": "h1", "tier": "B", "position": 0.5, "lane_offset": 0.5, "comment": ""}
    assert board.markers_version([base]) != board.markers_version([{**base, "is_excluded": True}])


def test_the_payload_carries_a_revision_number():
    """描くたびに増える番号。古い描画があとから届いたときに捨てるのに使う。"""
    args = ([entry("h1")], {"h1": score()}, {"h1": [run()]})
    assert board.board_payload(*args, rev=7)["rev"] == 7
    assert board.board_payload(*args)["rev"] == 0          # 渡さなくても落ちない


def test_crossing_out_an_edge_horse_does_not_move_the_others():
    """端の馬（先頭・最後方）を消しても、他の馬の位置が動かないこと。

    横位置は「いちばん前を右端、いちばん後ろを左端」に引き伸ばして決めている。
    消した馬にも位置を保存していたころは、次に開いたときに
    「引き伸ばし済みの値」と「生の値」が混ざってもう一度引き伸ばされ、
    端の馬ほど基準になるので全馬が動いていた。
    """
    entries = [entry(f"h{i}", umaban=i) for i in range(1, 7)]
    runs = {f"h{i}": [run(f"{i*3}-{i*3}-{i*3}-{i*3}", n_runners=18)] for i in range(1, 7)}
    scores = {f"h{i}": score() for i in range(1, 7)}

    before = {m["horse_id"]: m for m in board.build_markers(entries, scores, runs)}
    order = sorted(before.values(), key=lambda m: m["position"])
    edges = (order[0]["horse_id"], order[-1]["horse_id"])

    # 「消しただけ」の馬は位置を保存しない（db.save_board と同じ扱い）
    saved = {
        horse: {"tier": None, "position": None, "lane_offset": None,
                "comment": None, "is_manual": 0, "is_excluded": 1}
        for horse in edges
    }
    after = {m["horse_id"]: m for m in board.build_markers(entries, scores, runs, saved)}

    for horse, marker in before.items():
        assert after[horse]["position"] == marker["position"], horse
    assert all(after[h]["is_excluded"] for h in edges)      # 消しの印は残る


# --- 1頭さわっても他の馬が動かないこと -------------------------------------------------


def _field_markers(saved=None, count=6):
    entries = [entry(f"h{i}", umaban=i) for i in range(1, count + 1)]
    runs = {f"h{i}": [run(f"{i*3}-{i*3}-{i*3}-{i*3}", n_runners=18)] for i in range(1, count + 1)}
    scores = {f"h{i}": score() for i in range(1, count + 1)}
    return {m["horse_id"]: m for m in board.build_markers(entries, scores, runs, saved)}


def test_placing_one_horse_by_hand_does_not_move_the_others():
    """引き伸ばしの基準は**全馬の生の位置**。手で置いた馬を基準から外すと、
    1頭動かしただけで最小値・最大値が変わり、他の馬が全部動いてしまう。
    """
    before = _field_markers()
    front = max(before.values(), key=lambda m: m["position"])
    saved = {front["horse_id"]: {"tier": "D", "position": 0.12, "lane_offset": 0.5,
                                 "comment": None, "is_manual": 1, "is_excluded": 0}}
    after = _field_markers(saved)

    for horse, marker in before.items():
        if horse == front["horse_id"]:
            continue
        assert after[horse]["position"] == marker["position"], horse
    assert after[front["horse_id"]]["position"] == 0.12      # 置いた場所は動かさない


def test_crossing_one_horse_out_does_not_move_the_others():
    before = _field_markers()
    front = max(before.values(), key=lambda m: m["position"])
    saved = {front["horse_id"]: {"tier": None, "position": None, "lane_offset": None,
                                 "comment": None, "is_manual": 0, "is_excluded": 1}}
    after = _field_markers(saved)
    for horse, marker in before.items():
        assert after[horse]["position"] == marker["position"], horse


def test_the_stretch_still_reaches_both_edges():
    """基準を変えても、引き伸ばし自体はこれまでどおり効くこと。"""
    markers = _field_markers()
    positions = sorted(m["position"] for m in markers.values())
    assert positions[-1] > 0.9 and positions[0] < 0.1
    for marker in markers.values():                 # 端でも名前が切れない
        half = board.marker_width(marker["horse_name"]) / 2
        assert 0 <= marker["position"] - half and marker["position"] + half <= 1


def test_the_basis_is_not_sent_to_the_board():
    """基準に使った生の位置は、コンポーネントに渡さない。"""
    payload = board.board_payload([entry("h1")], {"h1": score()}, {"h1": [run()]})
    assert all("_auto" not in m for m in payload["markers"])


def test_moving_a_horse_to_another_tier_does_not_move_the_others():
    """別のTierへ動かしても、元のレーンに残る馬の段が変わらないこと。

    レーンの顔ぶれを見て段を割り振っていたころは、1頭が抜けると残りが詰め直されて
    縦にずれていた（実測で1頭動かすとレーン内の1頭が 0.1667 → 0.5 に動いた）。
    """
    entries = [entry(f"h{i}", umaban=i) for i in range(1, 7)]
    runs = {f"h{i}": [run(f"{i*3}-{i*3}-{i*3}-{i*3}", n_runners=18)] for i in range(1, 7)}
    scores = {f"h{i}": score() for i in range(1, 7)}
    before = {m["horse_id"]: m for m in board.build_markers(entries, scores, runs)}

    saved = {"h1": {"tier": "D", "position": 0.4, "lane_offset": 0.5,
                    "comment": None, "is_manual": 1, "is_excluded": 0}}
    after = {m["horse_id"]: m for m in board.build_markers(entries, scores, runs, saved)}

    for horse, marker in before.items():
        if horse == "h1":
            continue
        assert after[horse]["lane_offset"] == marker["lane_offset"], horse
        assert after[horse]["position"] == marker["position"], horse
    assert (after["h1"]["tier"], after["h1"]["position"]) == ("D", 0.4)


def test_the_payload_carries_the_race_so_the_jump_cannot_go_astray():
    """盤の馬名から馬柱へ飛ぶとき、**このレースの行しか探さない**ための目印。"""
    markers = ([entry("h1")], {"h1": score()}, {"h1": [run()]})
    payload = board.board_payload(*markers, race_id="202606040611")
    assert payload["race_id"] == "202606040611"
    assert board.board_payload(*markers)["race_id"] is None


# --- スマホ（縦持ちで盤を90度回して出す） -------------------------------------------


def test_the_phone_layout_uses_its_own_measurements():
    entries = [entry("h1", name="カフジエメンタール"), entry("h2", name="ピカラ", umaban=2)]
    scores = {"h1": score(), "h2": score()}
    payload = board.board_payload(entries, scores, {"h1": [run()], "h2": [run()]}, layout="phone")
    assert payload["layout"] == "phone"
    assert payload["lane_head"] == board.PHONE.lane_head
    assert payload["lane_height"] >= board.PHONE.min_lane_height
    pc = board.board_payload(entries, scores, {"h1": [run()], "h2": [run()]})
    assert pc["layout"] == "pc" and pc["lane_head"] == board.LANE_HEAD_PX   # PCは今までどおり
    unknown = board.board_payload(entries, scores, {}, layout="tablet")
    assert unknown["layout"] == "pc"                                      # 知らない値はPC扱い


def test_phone_markers_do_not_overlap_on_the_phone_board():
    """スマホの盤（狭い）でも、18頭の長い名前が重ならないこと（スマホの寸法で見積もる）。"""
    entries = [entry(f"h{i}", name="カフジエメンタール", umaban=i) for i in range(1, 19)]
    runs = {f"h{i}": [run(f"{i}-{i}-{i}-{i}", n_runners=18)] for i in range(1, 19)}
    markers = board.build_markers(entries, {f"h{i}": score() for i in range(1, 19)}, runs,
                                  metrics=board.PHONE)
    bad = []
    for i, a in enumerate(markers):
        for b in markers[i + 1:]:
            if a["tier"] != b["tier"] or a["lane_offset"] != b["lane_offset"]:
                continue
            need = (board.marker_width(a["horse_name"], board.PHONE)
                    + board.marker_width(b["horse_name"], board.PHONE)) / 2
            if abs(a["position"] - b["position"]) < need:
                bad.append((a["horse_id"], b["horse_id"]))
    assert bad == [] or len({m["lane_offset"] for m in markers}) == board.MAX_LANE_ROWS
