"""ラップ推移グラフ（モーダルの中身）。"""

from keiba_analysis.racing.lap_chart import (
    CHART_HEIGHT,
    DEFAULT_CHART_RUNS,
    IN_MONEY,
    NO_FINISH,
    OUT_OF_MONEY,
    PLACE_OPACITIES,
    PLACE_ORDER,
    PLACE_WIDTHS,
    ESTIMATED_LAP_KIND,
    LAP_KINDS,
    RACE_LAP_KIND,
    REFERENCE_LAP_KIND,
    X_DOMAIN,
    X_TITLE,
    Y_DOMAIN,
    Y_TITLE,
    PHASE_Y_DOMAIN,
    build_finish_rows,
    build_goal_rows,
    build_lap_rows,
    build_lap_spec,
    build_phase_rows,
    build_phase_spec,
    finish_label,
    place_label,
    race_label,
)
from keiba_analysis.racing.lap_phases import PHASE_LABELS
from keiba_analysis.racing.lap_estimate import EstimatedLaps, run_key

RUN = {
    "race_id": "202601010101", "race_date": "2026-08-22", "venue_name": "札幌", "race_no": 11,
    "race_name": "オールスターJ第2戦", "grade": None,
    "surface": "turf", "distance_m": 2000, "direction": "right", "course_detail": None,
    "race_laps": "12.8-10.9-12.0", "lap_distances": "200-400-600",
}
OTHER = {**RUN, "race_id": "202601010102", "race_date": "2026-06-06", "venue_name": "阪神",
         "race_name": "垂水S", "race_laps": "12.6-11.4", "lap_distances": "200-400"}


def test_race_laps_are_dotted_series_from_start():
    rows = build_lap_rows([RUN])
    assert [r["distance_m"] for r in rows] == [200, 400, 600]  # スタートからの距離
    assert [r["lap_sec"] for r in rows] == [12.8, 10.9, 12.0]
    assert {r["kind"] for r in rows} == {RACE_LAP_KIND}


def test_legend_label_has_venue_course_and_race_name():
    """凡例は開催・コース・クラス（＋名前のあるレースは名前）。"""
    run = {**RUN, "race_name": "STV賞(3勝)", "class_condition": "3勝クラス",
           "finish_position": 1, "cushion_value": 8.1}
    label = race_label(run)
    assert label == "08/22 札幌 芝2000 3勝 STV賞"
    assert "1着" not in label and "ク8.1" not in label   # この2つは線の右端に出す
    assert "右" not in label                              # 回りは入れない（幅の都合）
    assert all(r["race"] == race_label(RUN) for r in build_lap_rows([RUN]))


def test_legend_label_marks_graded_races_with_their_grade():
    """重賞はレース名にグレードが入っていないので、頭に付ける。"""
    run = {**RUN, "race_name": "第44回関西TVローズS", "grade": "GII", "class_condition": "オープン 牝"}
    assert race_label(run) == "08/22 札幌 芝2000 GII 関西TVローズS"


def test_legend_label_for_condition_races_is_just_the_class():
    """条件戦はレース名を出さず、何勝クラスかだけ分かればよい。"""
    run = {**RUN, "race_name": "3歳以上1勝クラス", "class_condition": "1勝クラス"}
    assert race_label(run) == "08/22 札幌 芝2000 1勝"


def test_legend_label_without_a_race_name():
    assert race_label({**RUN, "race_name": None}) == "08/22 札幌 芝2000"


def test_multiple_races_are_separate_series():
    rows = build_lap_rows([RUN, OTHER])
    assert len({r["race"] for r in rows}) == 2


def test_estimated_laps_are_added_as_solid_series():
    """推定ラップを渡すと、実線側の系列が増える。"""
    estimate = EstimatedLaps(values=[12.9, 11.2, 12.3], is_reference=False)
    rows = build_lap_rows([RUN], estimated_laps={run_key(RUN): estimate})
    estimated = [r for r in rows if r["kind"] == ESTIMATED_LAP_KIND]
    assert [r["lap_sec"] for r in estimated] == [12.9, 11.2, 12.3]
    assert [r["distance_m"] for r in estimated] == [200, 400, 600]


def test_missing_segments_break_the_line():
    """推定できなかった区間は None のまま渡して、その区間だけ線を切る。"""
    estimate = EstimatedLaps(values=[12.9, None, 12.3], is_reference=False)
    rows = build_lap_rows([RUN], estimated_laps={run_key(RUN): estimate})
    estimated = [r for r in rows if r["kind"] == ESTIMATED_LAP_KIND]
    assert [r["lap_sec"] for r in estimated] == [12.9, None, 12.3]


def test_reference_estimates_are_a_separate_series():
    """コーナー通過順を使えなかった走は、参考値として別の線種にする。"""
    estimate = EstimatedLaps(values=[12.9, 11.2, 12.3], is_reference=True)
    rows = build_lap_rows([RUN], estimated_laps={run_key(RUN): estimate})
    assert {r["kind"] for r in rows} == {RACE_LAP_KIND, REFERENCE_LAP_KIND}


def test_estimated_laps_not_given_means_no_solid_series():
    assert all(r["kind"] == RACE_LAP_KIND for r in build_lap_rows([RUN]))


def test_runs_without_laps_are_skipped():
    no_laps = {**RUN, "race_laps": None, "lap_distances": None}
    mismatched = {**RUN, "race_laps": "12.0-11.0", "lap_distances": "200-400-600"}
    assert build_lap_rows([no_laps]) == []
    assert build_lap_rows([mismatched]) == []
    assert build_lap_rows([]) == []


def test_chart_spec_encodings():
    spec = build_lap_spec(build_lap_rows([RUN, OTHER]))
    encoding = spec["layer"][0]["encoding"]
    assert encoding["x"]["field"] == "distance_m" and encoding["x"]["title"] == X_TITLE
    assert encoding["y"]["field"] == "lap_sec" and encoding["y"]["title"] == Y_TITLE
    assert encoding["color"]["field"] == "race"        # レースごとに色を変える
    assert encoding["strokeDash"]["field"] == "kind"
    # レースラップ=点線、個別推定ラップ=実線、参考値=破線
    scale = encoding["strokeDash"]["scale"]
    assert scale["domain"] == LAP_KINDS == [RACE_LAP_KIND, ESTIMATED_LAP_KIND, REFERENCE_LAP_KIND]
    assert scale["range"][0] != [1, 0] and scale["range"][1] == [1, 0]
    assert scale["range"][2] not in ([1, 0], scale["range"][0])
    assert spec["layer"][0]["mark"]["type"] == "line"
    assert spec["layer"][0]["data"]["values"]  # データは定義に直接埋め込む
    # 点線・実線の区別はグラフ下の説明文で伝えるので、凡例は出さない
    assert encoding["strokeDash"]["legend"] is None


def test_axes_are_fixed_for_every_horse():
    """どの馬でも同じ縮尺で見比べられるよう、軸を固定する。"""
    spec = build_lap_spec(build_lap_rows([RUN]))
    for layer in spec["layer"]:
        assert layer["encoding"]["x"]["scale"]["domain"] == X_DOMAIN == [0, 3200]
        assert layer["encoding"]["y"]["scale"]["domain"] == Y_DOMAIN == [10, 14]
        assert layer["encoding"]["x"]["scale"]["clamp"] is True
        assert layer["encoding"]["y"]["scale"]["clamp"] is True


def test_goal_rows_are_the_last_segment_of_each_race():
    goals = build_goal_rows(build_lap_rows([RUN, OTHER]))
    assert len(goals) == 2
    by_label = {g["goal_label"]: g for g in goals}
    assert by_label["600m"]["distance_m"] == 600   # RUNは600mが最終区間
    assert by_label["400m"]["distance_m"] == 400   # OTHERは400m
    assert all(g["kind"] == RACE_LAP_KIND for g in goals)  # 推定ラップ側は対象外


def test_goal_markers_are_layered_without_their_own_legend():
    spec = build_lap_spec(build_lap_rows([RUN]))
    assert len(spec["layer"]) == 3          # 折れ線・ゴールの点・ゴールのラベル
    point_layer, label_layer = spec["layer"][1], spec["layer"][2]
    assert point_layer["mark"]["shape"] == "diamond"
    assert label_layer["mark"]["type"] == "text"
    assert label_layer["encoding"]["text"]["field"] == "goal_label"
    # ゴールの層は凡例を出さない（凡例は折れ線の色だけ）
    assert point_layer["encoding"]["color"]["legend"] is None
    assert label_layer["encoding"]["color"]["legend"] is None


def test_chart_is_large_and_legend_is_small_and_horizontal():
    spec = build_lap_spec(build_lap_rows([RUN]))
    assert spec["height"] == CHART_HEIGHT == 560
    legend = spec["layer"][0]["encoding"]["color"]["legend"]
    assert legend["direction"] == "horizontal"   # 縦一列ではなく横並び
    assert legend["labelFontSize"] == 12 and legend["columns"] == 4   # 横に4走ぶん並べる


def test_faster_laps_are_at_the_top():
    """netkeibaと同じ向き（上=速い10秒側、下=遅い14秒側）にする。"""
    spec = build_lap_spec(build_lap_rows([RUN]))
    for layer in spec["layer"]:
        assert layer["encoding"]["y"]["scale"]["reverse"] is True


def test_spec_has_no_schema_version():
    """Streamlit同梱のVega-Liteのバージョンで解釈させるため、$schemaは付けない。

    Altairが出すVega-Lite v6の定義をStreamlit 1.64（v5同梱）に渡すと、
    ブラウザ側で描画されず空になる不具合があったため。
    """
    spec = build_lap_spec(build_lap_rows([RUN]))
    assert "$schema" not in spec
    assert all("$schema" not in layer for layer in spec["layer"])


def test_lines_are_thick_enough_to_read():
    """1走につき2本（レースラップ＋個別推定）重なるので、線は太めにする。

    太さは**走ごと**（複勝圏内か着外か）で決めるので、markには固定値を置かない。
    """
    spec = build_lap_spec(build_lap_rows([RUN]))
    mark = spec["layer"][0]["mark"]
    assert "strokeWidth" not in mark
    assert max(PLACE_WIDTHS) >= 3
    assert mark["point"]["size"] >= 24


def test_default_number_of_runs():
    """既定は5走（画面のスライダーで増やせる）。"""
    assert DEFAULT_CHART_RUNS == 5


def test_phase_axis_is_fixed_between_10_5_and_14_5():
    """縦軸は固定（馬やレースが変わっても同じ尺度で見比べられるように）。"""
    assert PHASE_Y_DOMAIN == [10.5, 14.5]
    spec = build_phase_spec(build_phase_rows([LONG]))
    assert spec["layer"][0]["encoding"]["y"]["scale"]["clamp"] is True


def test_race_laps_can_be_hidden():
    """レース全体のラップを消すと、個別推定ラップだけが残る。"""
    estimate = EstimatedLaps(values=[12.9, 11.2, 12.3], is_reference=False)
    rows = build_lap_rows([RUN], {("202601010101", None): estimate}, include_race_laps=False)
    assert {r["kind"] for r in rows} == {ESTIMATED_LAP_KIND}
    assert [r["lap_sec"] for r in rows] == [12.9, 11.2, 12.3]
    # 推定が無い走は、レースラップを消すと何も描かれない
    assert build_lap_rows([RUN], include_race_laps=False) == []


def test_goal_marker_survives_hiding_the_race_laps():
    """点線を消しても、ゴール地点の◆と距離ラベルは出す。"""
    estimate = EstimatedLaps(values=[12.9, 11.2, 12.3], is_reference=False)
    rows = build_lap_rows([RUN], {("202601010101", None): estimate}, include_race_laps=False)
    goals = build_goal_rows(rows)
    assert [g["goal_label"] for g in goals] == ["600m"]
    assert goals[0]["distance_m"] == 600


def test_goal_marker_ignores_missing_segments():
    """推定できなかった最終区間は、ゴール地点の候補にしない。"""
    estimate = EstimatedLaps(values=[12.9, 11.2, None], is_reference=False)
    rows = build_lap_rows([RUN], {("202601010101", None): estimate}, include_race_laps=False)
    goals = build_goal_rows(rows)
    assert goals[0]["distance_m"] == 400


# --- 3区分（前2F・中間・上り3F）版 -------------------------------------------

LONG = {  # 2000m（10区間）。距離の違うレースを重ねられるかの確認に使う
    **RUN, "race_id": "202601010103", "distance_m": 2000,
    "race_laps": "-".join(["12.0"] * 10), "lap_distances": "-".join(str(200 * i) for i in range(1, 11)),
}
SHORT = {  # 800m（4区間）。中間が取れる最小の距離
    **RUN, "race_id": "202601010104", "distance_m": 800,
    "race_laps": "12.0-12.0-12.0-12.0", "lap_distances": "200-400-600-800",
}


def test_phase_rows_cover_every_phase():
    estimate = EstimatedLaps(values=[12.0] * 4, is_reference=False)
    rows = build_phase_rows([SHORT], {("202601010104", None): estimate})
    # 800mは中間が取れないので、前2Fの200m×2と上り3Fの200m×3から入る分だけになる
    assert [r["phase"] for r in rows if r["kind"] == RACE_LAP_KIND] == ["200m", "残600m", "残400m", "残200m"]
    assert {r["kind"] for r in rows} == {RACE_LAP_KIND, ESTIMATED_LAP_KIND}

    rows = build_phase_rows([LONG])
    assert [r["phase"] for r in rows] == list(PHASE_LABELS)      # 2000mは6点
    assert all(r["pace_sec"] == 12.0 for r in rows)              # 1Fあたりの秒


def test_phase_rows_can_hide_the_race_laps():
    estimate = EstimatedLaps(values=[11.0] * 10, is_reference=False)
    rows = build_phase_rows([LONG], {("202601010103", None): estimate}, include_race_laps=False)
    assert {r["kind"] for r in rows} == {ESTIMATED_LAP_KIND}


def test_different_distances_share_the_same_x_axis():
    """距離が違っても同じ3区分に並ぶ（これが3区分表示の目的）。"""
    rows = build_phase_rows([SHORT, LONG])
    assert len({r["race"] for r in rows}) == 2
    assert {r["phase"] for r in rows} <= set(PHASE_LABELS)


def test_phase_spec_uses_an_ordinal_axis_in_order():
    spec = build_phase_spec(build_phase_rows([LONG]))
    encoding = spec["layer"][0]["encoding"]
    assert encoding["x"]["field"] == "phase" and encoding["x"]["type"] == "ordinal"
    assert encoding["x"]["sort"] == list(PHASE_LABELS)            # 前2F→中間→上り3F
    assert encoding["y"]["field"] == "pace_sec"
    assert encoding["y"]["scale"]["reverse"] is True              # 上へ行くほど速い
    assert encoding["y"]["scale"]["domain"] == PHASE_Y_DOMAIN
    assert encoding["color"]["field"] == "race"
    assert encoding["strokeDash"]["scale"]["domain"] == LAP_KINDS
    assert "strokeWidth" not in spec["layer"][0]["mark"]   # 太さは走ごと（下のテスト）
    assert "$schema" not in spec                                  # 理由は lap_chart の冒頭


def test_finish_rows_are_one_per_race_at_the_end_of_the_line():
    """着順はレースごとに1つだけ、線の右端に出す。"""
    estimate = EstimatedLaps(values=[11.0] * 10, is_reference=False)
    run = {**LONG, "finish_position": 3}
    rows = build_phase_rows([run], {("202601010103", None): estimate})
    finishes = build_finish_rows(rows)
    assert len(finishes) == 1                       # レースラップと推定で2つ出さない
    assert finishes[0]["finish_label"] == "3着 (札幌)"   # 括弧には会場（＋あればクッション値）
    assert finishes[0]["phase"] == PHASE_LABELS[-1]  # 右端（残200m）
    assert finishes[0]["kind"] == ESTIMATED_LAP_KIND  # 推定側の点を使う


def test_finish_rows_skip_missing_points_and_unknown_finishes():
    broken = EstimatedLaps(values=[11.0] * 9 + [None], is_reference=False)
    rows = build_phase_rows([{**LONG, "finish_position": 3}], {("202601010103", None): broken}, include_race_laps=False)
    assert build_finish_rows(rows)[0]["phase"] != PHASE_LABELS[-1]   # 欠損の点は選ばない

    rows = build_phase_rows([LONG])          # 着順が無い走（LONGは着順なし）
    assert build_finish_rows(rows) == []


def test_goal_label_includes_the_finish():
    """200m版は、ゴールの距離ラベルに着順を添える。"""
    rows = build_lap_rows([{**LONG, "finish_position": 1}])
    assert [g["goal_label"] for g in build_goal_rows(rows)] == ["2000m 1着 (札幌)"]
    assert [g["goal_label"] for g in build_goal_rows(build_lap_rows([LONG]))] == ["2000m"]  # 着順が無ければ距離だけ


def test_finish_label_adds_the_cushion_in_brackets():
    """グラフ内の着順には、馬場の硬さを括弧で添える。"""
    run = {**LONG, "finish_position": 1, "cushion_value": 8.1}      # LONGの会場は札幌
    assert finish_label(run) == "1着 (札幌 ク8.1)"
    assert finish_label({**run, "cushion_value": None}) == "1着 (札幌)"
    assert finish_label({**run, "venue_name": None}) == "1着 (ク8.1)"
    assert finish_label({**run, "surface": "dirt", "dirt_moisture_goal": 5.2}) == "1着 (札幌 含水5.2%)"
    assert finish_label({**LONG}) == ""        # 着順が分からない走は出さない

    rows = build_phase_rows([run], {("202601010103", None): EstimatedLaps(values=[11.0] * 10, is_reference=False)})
    assert build_finish_rows(rows)[0]["finish_label"] == "1着 (札幌 ク8.1)"


def test_goal_label_includes_the_finish_and_cushion():
    rows = build_lap_rows([{**LONG, "finish_position": 1, "cushion_value": 8.1}])
    assert [g["goal_label"] for g in build_goal_rows(rows)] == ["2000m 1着 (札幌 ク8.1)"]


def test_overlapping_finish_labels_are_spread_out():
    """同じくらいの高さで終わった走は、ラベルが重ならないよう少し下へずらす。"""
    same = EstimatedLaps(values=[11.0] * 10, is_reference=False)
    almost = EstimatedLaps(values=[11.0] * 9 + [11.03], is_reference=False)
    runs = [
        {**LONG, "race_id": "a", "finish_position": 1},
        {**LONG, "race_id": "b", "race_name": "別のレース", "finish_position": 2},
    ]
    rows = build_phase_rows(
        runs, {("a", None): same, ("b", None): almost}, include_race_laps=False
    )
    finishes = sorted(build_finish_rows(rows), key=lambda r: r["label_y"])
    assert finishes[0]["label_y"] == finishes[0]["pace_sec"]          # 1つ目はそのまま
    assert finishes[1]["label_y"] > finishes[1]["pace_sec"]           # 2つ目をずらす
    assert finishes[1]["label_y"] - finishes[0]["label_y"] >= 0.1     # 1行ぶん空く


def test_finish_labels_keep_their_place_when_far_apart():
    fast = EstimatedLaps(values=[11.0] * 10, is_reference=False)
    slow = EstimatedLaps(values=[13.0] * 10, is_reference=False)
    runs = [
        {**LONG, "race_id": "a", "finish_position": 1},
        {**LONG, "race_id": "b", "race_name": "別のレース", "finish_position": 9},
    ]
    rows = build_phase_rows(runs, {"a": fast, "b": slow}, include_race_laps=False)
    assert all(r["label_y"] == r["pace_sec"] for r in build_finish_rows(rows))


# --- 複勝圏内の走を太く濃く ---------------------------------------------------


def test_the_place_says_whether_the_run_was_in_the_money():
    """1〜3着は複勝圏内、4着以下は着外。着順が無い走（取消・中止）は分けて持つ。"""
    assert place_label({**RUN, "finish_position": 1}) == IN_MONEY
    assert place_label({**RUN, "finish_position": 3}) == IN_MONEY
    assert place_label({**RUN, "finish_position": 4}) == OUT_OF_MONEY
    assert place_label({**RUN, "finish_position": 18}) == OUT_OF_MONEY
    assert place_label(RUN) == NO_FINISH                                   # 着順が無い
    assert place_label({**RUN, "finish_status": "中止"}) == NO_FINISH


def test_both_lines_of_a_run_share_the_same_emphasis():
    """点線（レースラップ）も実線（個別推定）も、同じ走なら同じ太さ・濃さにする。"""
    run = {**RUN, "finish_position": 2}
    estimates = {run_key(run): EstimatedLaps(values=[12.7, 11.0, 12.1], is_reference=False)}
    rows = build_lap_rows([run], estimates)
    assert {r["place"] for r in rows} == {IN_MONEY}
    assert {r["kind"] for r in rows} == {RACE_LAP_KIND, ESTIMATED_LAP_KIND}
    # 3区分版も同じ（こちらは距離ぶんのラップがそろった走で見る）
    long_run = {**LONG, "finish_position": 2}
    long_estimates = {run_key(long_run): EstimatedLaps(values=[12.0] * 10, is_reference=False)}
    assert {r["place"] for r in build_phase_rows([long_run], long_estimates)} == {IN_MONEY}


def test_every_row_carries_the_emphasis():
    """1走ずつ着順が違っても、行ごとに正しく付く（レース全体のラップを消しても）。"""
    runs = [{**RUN, "finish_position": 1},
            {**OTHER, "finish_position": 9}]
    rows = build_lap_rows(runs, include_race_laps=False)
    by_race = {r["race_id"]: r["place"] for r in rows}
    assert by_race == {}
    rows = build_lap_rows(runs)
    assert {r["race_id"]: r["place"] for r in rows} == {
        "202601010101": IN_MONEY, "202601010102": OUT_OF_MONEY,
    }
    phase_rows = build_phase_rows([{**LONG, "finish_position": 1},
                                   {**SHORT, "finish_position": 9}])
    assert {r["race_id"]: r["place"] for r in phase_rows} == {
        "202601010103": IN_MONEY, "202601010104": OUT_OF_MONEY,
    }


def _line_encoding(spec: dict) -> dict:
    return spec["layer"][0]["encoding"]


def test_the_in_the_money_lines_are_thicker_and_darker():
    """複勝圏内のほうが太く・濃いこと（並びは domain と突き合わせて確かめる）。"""
    for spec in (build_lap_spec(build_lap_rows([{**RUN, "finish_position": 1}])),
                 build_phase_spec(build_phase_rows([{**LONG, "finish_position": 1}]))):
        encoding = _line_encoding(spec)
        for channel, values in (("strokeWidth", PLACE_WIDTHS), ("opacity", PLACE_OPACITIES)):
            assert encoding[channel]["field"] == "place"
            assert encoding[channel]["scale"]["domain"] == PLACE_ORDER
            assert encoding[channel]["scale"]["range"] == values
            assert encoding[channel]["legend"] is None
            in_money = values[PLACE_ORDER.index(IN_MONEY)]
            assert in_money > values[PLACE_ORDER.index(OUT_OF_MONEY)]


def test_the_colour_and_the_dashes_are_untouched():
    """レースごとの色分けと、点線／実線の区別はそのまま（太さ・濃さは別の軸）。"""
    spec = build_lap_spec(build_lap_rows([{**RUN, "finish_position": 5}]))
    encoding = _line_encoding(spec)
    assert encoding["color"]["field"] == "race"
    assert encoding["color"]["legend"] is not None                  # 凡例は残る
    assert encoding["strokeDash"]["field"] == "kind"
    assert encoding["strokeDash"]["scale"]["domain"] == LAP_KINDS


def test_the_goal_and_finish_layers_stay_solid():
    """ゴールの◆と右端の着順ラベルは薄くしない（読めなくなるため）。"""
    spec = build_lap_spec(build_lap_rows([{**RUN, "finish_position": 9}]))
    for layer in spec["layer"][1:]:
        assert "opacity" not in layer["encoding"]
        assert "strokeWidth" not in layer["encoding"]
    phase = build_phase_spec(build_phase_rows([{**LONG, "finish_position": 9}]))
    assert "opacity" not in phase["layer"][1]["encoding"]


def test_the_finish_is_in_the_tooltip():
    """なぜ太いのか分かるよう、着順をtooltipにも出す。"""
    for spec in (build_lap_spec(build_lap_rows([{**RUN, "finish_position": 1}])),
                 build_phase_spec(build_phase_rows([{**LONG, "finish_position": 1}]))):
        fields = [t["field"] for t in _line_encoding(spec)["tooltip"]]
        assert "finish" in fields
