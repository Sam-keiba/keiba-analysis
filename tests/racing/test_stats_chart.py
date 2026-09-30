"""傾向グラフ（ペース別・クッション値×馬場状態・脚質）のVega-Lite定義。"""

import pytest

from keiba_analysis.racing.horse_stats import (
    CUSHION_LABELS,
    GOING_LABELS,
    PACE_LABELS,
    summarize_hardness_going,
    summarize_pace,
    summarize_style,
)
from keiba_analysis.racing.stats_chart import (
    DIM_OPACITY,
    NO_RUN,
    TOTAL_LABEL,
    build_hardness_going_spec,
    build_pace_spec,
    build_style_spec,
    bucket_rows,
    cell_rows,
    total_rows,
)
from keiba_analysis.shared.style import (
    PACE_COLORS,
    RATE_HEAT_COLORS,
    RUNNING_STYLE_COLORS,
    TOTAL_CELL_COLOR,
)


def run(finish=1, corner="3-3-3-3", cushion=9.0, first_3f=34.5, last_3f=36.5, going="良"):
    return {
        "finish_position": finish, "corner_passing": corner, "n_runners": 16,
        "cushion_value": cushion, "race_first_3f": first_3f, "race_last_3f": last_3f,
        "going": going,
    }


HIGH_PACE_RUNS = [run(finish=1), run(finish=2), run(finish=7)]   # 3走ともハイペース


def test_bucket_rows_carry_the_numbers_behind_the_bar():
    rows = {r["label"]: r for r in bucket_rows(summarize_pace(HIGH_PACE_RUNS))}
    assert rows["ハイ"]["rate"] == pytest.approx(66.7, abs=0.1)   # 3走中2走が3着内
    assert rows["ハイ"]["note"] == "2/3"
    assert rows["ミドル"]["note"] == "出走なし"


def test_small_samples_are_drawn_faintly():
    """出走が少ない区分は薄く描く（材料不足が分かるように）。"""
    rows = {r["label"]: r for r in bucket_rows(summarize_pace([run()]))}
    assert rows["ハイ"]["opacity"] == DIM_OPACITY
    rows = {r["label"]: r for r in bucket_rows(summarize_pace(HIGH_PACE_RUNS))}
    assert rows["ハイ"]["opacity"] == 1.0


def test_pace_spec_is_a_horizontal_bar_with_the_shared_colors():
    spec = build_pace_spec(summarize_pace(HIGH_PACE_RUNS))
    assert "$schema" not in spec                       # 理由は lap_chart の冒頭と同じ
    bar = spec["layer"][0]
    assert bar["mark"]["type"] == "bar"
    assert bar["encoding"]["y"]["field"] == "label"    # 横棒（区分が縦軸）
    assert bar["encoding"]["y"]["sort"] == list(PACE_LABELS)
    assert bar["encoding"]["x"]["field"] == "rate"
    assert bar["encoding"]["x"]["scale"]["domain"] == [0, 100]
    assert bar["encoding"]["color"]["scale"]["range"][0] == PACE_COLORS["H"]
    assert spec["layer"][1]["mark"]["type"] == "text"  # 棒の右の「2/3」


# --- クッション値 × 馬場状態 のヒートマップ --------------------------------------

GRID_RUNS = [
    run(finish=1, cushion=9.0, going="良"),
    run(finish=2, cushion=9.2, going="良"),
    run(finish=3, cushion=9.4, going="良"),
    run(finish=8, cushion=8.0, going="重"),
]


def _cells(spec):
    return {(r["going"], r["cushion"]): r for r in spec["layer"][0]["data"]["values"]}


def _totals(spec):
    return {(r["going"], r["cushion"]): r for r in spec["layer"][1]["data"]["values"]}


def test_the_heatmap_puts_the_cushion_across_and_the_going_down():
    spec = build_hardness_going_spec(summarize_hardness_going(GRID_RUNS))
    assert "$schema" not in spec                        # 理由は lap_chart の冒頭と同じ
    rect = spec["layer"][0]
    assert rect["mark"]["type"] == "rect"
    assert rect["encoding"]["x"]["sort"] == [*CUSHION_LABELS, TOTAL_LABEL]
    assert rect["encoding"]["y"]["sort"] == [*GOING_LABELS, TOTAL_LABEL]
    # 表のように読めるよう、クッション値の見出しは上に置く
    assert rect["encoding"]["x"]["axis"]["orient"] == "top"


def test_the_three_layers_do_not_share_one_colour_scale():
    """重ねたレイヤーで色の使い方が違うので、まとめさせない。

    マスは複勝率（量）で塗り、合計は一色、文字はマスごとの色をそのまま渡している。
    `resolve` を外すと Vega-Lite がスケールを1つにまとめようとして
    「Cannot read properties of null」で**描画そのものが落ちる**（実際に踏んだ）。
    """
    spec = build_hardness_going_spec(summarize_hardness_going(GRID_RUNS))
    assert spec["resolve"]["scale"]["color"] == "independent"
    assert spec["resolve"]["scale"]["opacity"] == "independent"


def test_the_colour_is_the_place_rate():
    spec = build_hardness_going_spec(summarize_hardness_going(GRID_RUNS))
    color = spec["layer"][0]["encoding"]["color"]
    assert color["field"] == "rate"
    assert color["scale"]["domain"] == [0, 100]
    assert color["scale"]["range"] == list(RATE_HEAT_COLORS)
    assert color["legend"]["orient"] == "bottom"        # 狭い列なので下に横並びで置く


def test_each_cell_shows_how_many_runs_are_behind_it():
    cells = _cells(build_hardness_going_spec(summarize_hardness_going(GRID_RUNS)))
    assert cells[("良", "8.5〜10.0")]["note"] == "3/3"
    assert cells[("良", "8.5〜10.0")]["rate"] == 100.0
    assert cells[("重", "〜8.5")]["note"] == "0/1"
    assert len(cells) == 12                             # 走っていないマスも残す


def test_a_cell_with_no_run_is_left_blank():
    """走っていないマスを0%で塗ると「複勝率0%」と読めてしまう。白く抜く。"""
    cells = _cells(build_hardness_going_spec(summarize_hardness_going(GRID_RUNS)))
    empty = cells[("不良", "10.0〜")]
    assert empty["note"] == NO_RUN
    assert empty["opacity"] == 0.0


def test_a_cell_with_few_runs_is_drawn_faintly():
    """1頭ぶんだとマスは疎になるので、材料が足りないマスが見分けられること。"""
    cells = _cells(build_hardness_going_spec(summarize_hardness_going(GRID_RUNS)))
    assert cells[("重", "〜8.5")]["opacity"] == DIM_OPACITY      # 1走だけ
    assert cells[("良", "8.5〜10.0")]["opacity"] == 1.0          # 3走


def test_dark_cells_get_white_text():
    cells = _cells(build_hardness_going_spec(summarize_hardness_going(GRID_RUNS)))
    assert cells[("良", "8.5〜10.0")]["ink"] == "#ffffff"        # 複勝率100%＝濃い
    assert cells[("重", "〜8.5")]["ink"] == "#1b1b1b"            # 0%＝薄い


def test_the_totals_sit_on_the_edges_and_are_not_coloured():
    """合計は複勝率で塗らない（マスと同じ色だと、どこまでが中身か分からなくなる）。"""
    spec = build_hardness_going_spec(summarize_hardness_going(GRID_RUNS))
    totals = _totals(spec)
    assert spec["layer"][1]["mark"]["color"] == TOTAL_CELL_COLOR
    assert "color" not in spec["layer"][1]["encoding"]
    assert totals[("良", TOTAL_LABEL)]["note"] == "3/3"          # 良の行の計
    assert totals[(TOTAL_LABEL, "8.5〜10.0")]["note"] == "3/3"   # その列の計
    assert totals[(TOTAL_LABEL, "〜8.5")]["note"] == "0/1"


def test_the_corner_of_the_totals_is_left_empty():
    """行の計とも列の計とも読めてしまうので、右下の角は出さない。"""
    totals = _totals(build_hardness_going_spec(summarize_hardness_going(GRID_RUNS)))
    assert (TOTAL_LABEL, TOTAL_LABEL) not in totals
    assert len(totals) == len(GOING_LABELS) + len(CUSHION_LABELS)


def test_the_numbers_are_drawn_over_both_the_cells_and_the_totals():
    spec = build_hardness_going_spec(summarize_hardness_going(GRID_RUNS))
    text = spec["layer"][2]
    assert text["mark"]["type"] == "text"
    assert text["encoding"]["text"]["field"] == "note"
    assert len(text["data"]["values"]) == 12 + len(GOING_LABELS) + len(CUSHION_LABELS)


def test_an_empty_grid_still_draws():
    """1走も無くても落ちない（画面側で出すかどうかを決める）。"""
    spec = build_hardness_going_spec(summarize_hardness_going([]))
    assert len(cell_rows(summarize_hardness_going([]))) == 12
    assert all(r["opacity"] == 0.0 for r in spec["layer"][0]["data"]["values"])
    assert all(r["note"] == NO_RUN for r in total_rows(summarize_hardness_going([])))


def test_style_spec_is_a_stacked_share_bar():
    runs = [run(corner="1-1-1-1"), run(corner="14-14-13-12"), run(corner="13-13-13-14")]
    spec = build_style_spec(summarize_style(runs))
    bar = spec["layer"][0]
    assert bar["mark"]["type"] == "bar"
    assert bar["encoding"]["x"]["stack"] == "zero"          # 積み上げ
    assert bar["encoding"]["x"]["scale"]["domain"] == [0, 100]
    values = {v["style"]: v["share"] for v in bar["data"]["values"]}
    assert values["追込"] == pytest.approx(66.7, abs=0.1)
    assert values["逃げ"] == pytest.approx(33.3, abs=0.1)
    assert "先行" not in values                              # 走っていない脚質は積まない
    assert bar["encoding"]["color"]["scale"]["range"][0] == RUNNING_STYLE_COLORS["逃げ"]

    # 積み上げは逃げ→先行→差し→追込の順（Vega-Liteのorderは数値で渡す）
    assert bar["encoding"]["order"]["field"] == "style_index"
    indexes = {v["style"]: v["style_index"] for v in bar["data"]["values"]}
    assert indexes["逃げ"] < indexes["追込"]
    # 割合のラベルは区画の真ん中に置く
    assert spec["layer"][1]["encoding"]["x"]["bandPosition"] == 0.5


def test_style_spec_without_any_run():
    spec = build_style_spec(summarize_style([]))
    assert spec["layer"][0]["data"]["values"] == []


# --- 3つ横並びに耐える作りか（モーダルの列は250px前後） -------------------------


def test_rate_axis_title_is_short():
    """狭い列に収まるよう、軸のタイトルは短い表記にする（ツールチップは元のまま）。"""
    spec = build_pace_spec(summarize_pace(HIGH_PACE_RUNS))
    axis_title = spec["layer"][0]["encoding"]["x"]["title"]
    assert axis_title == "複勝率（%）"
    tooltips = [t["title"] for t in spec["layer"][0]["encoding"]["tooltip"]]
    assert "複勝率（3着内率）" in tooltips        # 詳しい表記はツールチップに残す


def test_rate_chart_has_little_padding():
    """棒の右の「4/4」のための余白は、狭い列でも邪魔にならない幅にする。"""
    spec = build_pace_spec(summarize_pace(HIGH_PACE_RUNS))
    assert spec["padding"]["right"] <= 48
    text_layer = spec["layer"][1]["mark"]
    assert text_layer["fontSize"] <= 10


def test_style_legend_fits_one_row():
    spec = build_style_spec(summarize_style(HIGH_PACE_RUNS))
    legend = spec["layer"][0]["encoding"]["color"]["legend"]
    assert legend["columns"] == 4 and legend["labelFontSize"] <= 10


def test_style_labels_only_for_wide_segments():
    """狭い列で文字がはみ出さないよう、15%未満の区分にはラベルを出さない。"""
    # 逃げ1走・追込9走（逃げは10%なのでラベルを出さない）
    runs = [run(corner="1-1-1-1")] + [run(corner="12-12-10-8") for _ in range(9)]
    rows = build_style_spec(summarize_style(runs))["layer"][0]["data"]["values"]
    notes = {r["style"]: r["note"] for r in rows}
    assert notes["逃げ"] == ""            # 10%なのでラベル無し
    assert "追込" in notes["追込"]         # 90%なのでラベルを出す


def test_the_x_axis_says_what_it_measures():
    """横軸の見出しは馬場で変わる（芝＝クッション値／ダート＝含水率）。"""
    from keiba_analysis.racing.horse_stats import DIRT_MOISTURE_LABELS

    dirt_runs = [{"finish_position": 1, "going": "良", "dirt_moisture_goal": 2.0},
                 {"finish_position": 4, "going": "重", "dirt_moisture_goal": 9.0}]
    spec = build_hardness_going_spec(summarize_hardness_going(dirt_runs, "dirt"))
    rect = spec["layer"][0]
    assert rect["encoding"]["x"]["title"] == "含水率（ゴール前・%）"
    assert rect["encoding"]["x"]["sort"] == [*DIRT_MOISTURE_LABELS, TOTAL_LABEL]
    # マスはダートの区分で並ぶ（芝の区分が混ざらない）
    labels = {row["cushion"] for row in rect["data"]["values"]}
    assert labels == set(DIRT_MOISTURE_LABELS)

    turf = build_hardness_going_spec(summarize_hardness_going(GRID_RUNS, "turf"))
    assert turf["layer"][0]["encoding"]["x"]["title"] == "クッション値"
