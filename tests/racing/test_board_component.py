"""予想ボードのカスタムコンポーネント（素のHTML+JS）。

**押したらどうなるか**は、JavaScriptCore（jsc）に最小のDOM
（`fixtures/mini_dom.js`）を噛ませて実際に動かして確かめる
（自動保存・馬名から馬柱へのジャンプ・丸で消す／戻す・✎でコメント）。
本当のドラッグの手触りだけは画面を開いて見る。
"""

import json
import pathlib
import re
import subprocess

import pytest

COMPONENT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "keiba_analysis" / "racing" / "board_component" / "index.html"
)
JSC = pathlib.Path(
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
)


MINI_DOM = pathlib.Path(__file__).parent / "fixtures" / "mini_dom.js"
needs_jsc = pytest.mark.skipif(not JSC.exists(), reason="JavaScriptCore（jsc）が無い環境ではスキップ")

RACE_ID = "202606040611"
OTHER_RACE_ID = "202606040612"


def _marker(horse_id: str, name: str, umaban: int, tier: str = "B", **kwargs) -> dict:
    base = {
        "horse_id": horse_id, "umaban": umaban, "waku": 1, "horse_name": name,
        "tier": tier, "position": 0.5, "lane_offset": 0.5, "comment": "",
        "is_manual": False, "is_excluded": False, "color": "#fff", "text_color": "#000",
        "style": "先行", "has_position": True, "explanation": "説明", "margin": 0.5,
        "lane_rows": 1,
    }
    return {**base, **kwargs}


def _payload(race_id: str = RACE_ID) -> dict:
    return {
        "race_id": race_id,
        "lanes": [{"key": k, "label": k, "meaning": k} for k in ("A", "B", "C", "D")],
        "axis": {"left": "Save runner", "right": "FrontRunner"},
        "markers": [_marker("2021102800", "キャントウェイト", 1),
                    _marker("2021102801", "ロブチェン", 2, tier="C")],
        "lane_head": 56, "lane_height": 68, "version": "v1", "rev": 1,
    }


def run_board(script: str, scenario: str, tmp_path: pathlib.Path, payload=None):
    """最小のDOMで盤を動かし、シナリオの `answer` をJSONで受け取る。

    シナリオからは `NODES`・`render()`・`SENT`・`runTimers()`・`putInParent()` が使える。
    """
    body = (
        f"const PAYLOAD = {json.dumps(payload or _payload(), ensure_ascii=False)};\n"
        + MINI_DOM.read_text()
        + """
ensureIds(["root", "board", "status", "hint", "editor", "editor-head", "editor-why",
           "comment", "axis-left", "axis-right"]);
/** マーカーの中の要素を押して離す（動かさずに離す＝クリック）。 */
function tap(markerEl, inner) {
  markerEl.fire("pointerdown", {
    target: inner || markerEl, pointerId: 1, clientX: 10, clientY: 10,
    preventDefault: function () {},
  });
  markerEl.fire("pointerup", {});
}
/** 押して動かして離す（ドラッグ）。 */
function drag(markerEl) {
  markerEl.fire("pointerdown", {
    target: markerEl, pointerId: 1, clientX: 10, clientY: 10,
    preventDefault: function () {},
  });
  markerEl.fire("pointermove", { clientX: 200, clientY: 40 });
  markerEl.fire("pointerup", {});
}
function markerOf(name) {
  return NODES.board.find(function (c) {
    return (c.attrs["class"] || "").indexOf("marker") === 0
      && c.findAll(function (x) { return x._text === name; }).length;
  });
}
function statusText() { return NODES.status.text(); }
"""
        + "\n(function () {\n" + script + "\n})();\n"
        + scenario
        + "\nprint(JSON.stringify(answer));\n"
    )
    path = tmp_path / "board_scene.js"
    path.write_text(body)
    result = subprocess.run([str(JSC), str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def source() -> str:
    return COMPONENT.read_text()


@pytest.fixture(scope="module")
def script(source: str) -> str:
    return "\n".join(re.findall(r"<script>(.*?)</script>", source, re.S))


def test_the_component_file_is_where_app_py_looks_for_it():
    assert COMPONENT.is_file() and COMPONENT.name == "index.html"


def test_it_speaks_the_streamlit_component_protocol(script: str):
    """この4つのメッセージ名でStreamlitとやりとりする（1つでも欠けると盤が出ない）。"""
    for message in (
        "streamlit:componentReady",
        "streamlit:render",
        "streamlit:setComponentValue",
        "streamlit:setFrameHeight",
    ):
        assert message in script, message


def test_the_value_goes_back_from_one_place_only(script: str):
    """値を返す口は `save()` の1か所だけ（自動保存なので、ここから何度も呼ばれる）。"""
    assert script.count("streamlit:setComponentValue") == 1
    save = script.split("function save()")[1]
    assert "streamlit:setComponentValue" in save.split("function ")[0]


def test_a_half_written_board_is_not_overwritten_by_a_redraw(script: str):
    """自分の保存が返ってきただけの描画では、盤を作り直さないこと。

    作り直すと、コメント欄が閉じたり書きかけが消えたりする。
    """
    render_handler = script.split('event.data.type !== "streamlit:render"')[1]
    assert "waitingSave" in render_handler


def test_the_page_has_the_parts_the_board_needs(source: str):
    for element_id in ("board", "status", "editor", "comment", "axis-left", "axis-right"):
        assert f'id="{element_id}"' in source, element_id
    assert 'id="save"' not in source          # 保存ボタンは無い（自動保存）


def test_manual_and_automatic_placements_look_different(source: str):
    """手で動かした馬と、自動のままの馬を見分けられること（要望のひとつ）。"""
    assert ".marker.manual" in source
    assert "marker.is_manual" in source


@pytest.mark.skipif(not JSC.exists(), reason="JavaScriptCore（jsc）が無い環境ではスキップ")
def test_the_javascript_parses(script: str, tmp_path: pathlib.Path):
    """構文エラーを混ぜたまま気づかない、という事故を防ぐ。

    DOMもwindowも無いので実行はせず、関数で包んで**解析だけ**させる。
    """
    path = tmp_path / "board.js"
    path.write_text("(function(){\n" + script + "\n});\n")
    result = subprocess.run(
        [str(JSC), str(path)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_a_stale_redraw_cannot_roll_the_board_back(script: str):
    """保存した直後に「保存前の内容」で描き直されると、配置が巻き戻る。

    Streamlit は枠の高さが変わると引数を送り直すので、コメント欄を開け閉めした
    ときにこれが起きていた。同じ中身（version）の描画は無視して防ぐ。
    """
    render_handler = script.split('event.data.type !== "streamlit:render"')[1]
    assert "payload.version === appliedVersion" in render_handler
    assert "appliedVersion = payload.version" in render_handler


def test_horse_names_are_not_underlined(source: str):
    """マーカーに脚質の下線は引かない（盤が見づらくなるため）。脚質はツールチップに出す。"""
    assert "borderBottom" not in source
    assert "marker.style" in source          # ツールチップには残っている


def test_lane_height_comes_from_the_payload(script: str):
    """レーンの高さは段の数で変わるので、固定値にしない。

    描画にもドラッグの当たり判定にも同じ値を使わないと、掴んだ馬が別のレーンに落ちる。
    """
    assert "payload.lane_height" in script
    assert script.count("laneHeight") >= 4      # 描画・当たり判定・レーンの上端・offset


def test_the_press_is_split_by_where_you_pressed(script: str):
    """丸＝消す／戻す、✎＝コメント、馬名＝下の馬柱へ。ドラッグは配置の変更。"""
    assert 'from.closest(".dot")' in script and 'from.closest(".pen")' in script
    handler = script.split("function onUp()")[1]
    assert "toggleExcluded(marker)" in handler
    assert "select(marker)" in handler
    assert "jumpToGrid(marker)" in handler
    # 保存にも乗せる（消しただけの馬もDBに残すため）
    assert "is_excluded: m.is_excluded" in script




def test_an_older_redraw_is_thrown_away(script: str):
    """保存のときPythonは2回走り、1回目は「保存前」の内容を渡してくる。

    それがあとから届くと保存した内容が巻き戻る（消しが戻る症状）。
    番号が前より大きいときだけ描くことで、順番が入れ替わっても壊れないようにする。
    """
    handler = script.split('event.data.type !== "streamlit:render"')[1]
    assert "payload.rev <= appliedRev" in handler
    # 番号は中身の判定より**先に**進める（ここで戻ると中途半端な番号の描画を通してしまう）
    rev_update = handler.index("appliedRev = payload.rev")
    version_check = handler.index("payload.version === appliedVersion")
    assert rev_update < version_check


# --- CSSとPython側の見積もりが食い違わないこと ------------------------------------------
#
# マーカーの幅はブラウザでしか測れないので、Python側は MARKER_BASE_PX / MARKER_CHAR_PX で
# **見積もって**段を決めている。CSSだけ小さくすると盤が縮まず（見積もりが大きいまま）、
# 見積もりだけ小さくすると馬が重なる。両方そろっていることをここで押さえる。


def _rule(source: str, selector: str) -> str:
    """そのセレクタだけの宣言を取り出す（`.marker.dim .name` のような複合と混ぜない）。"""
    import re

    m = re.search(r"^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", source, re.M)
    assert m, f"セレクタが見つかりません: {selector}"
    return m.group(1)


def _px(source: str, selector: str, prop: str) -> float:
    import re

    m = re.search(rf"{prop}:\s*([\d.]+)px", _rule(source, selector))
    assert m, f"{prop} が {selector} に無い"
    return float(m.group(1))


def test_the_name_size_matches_the_python_estimate(source: str):
    """馬名の大きさ＝全角1文字ぶんの見積もり。ここがずれると段の数が合わなくなる。"""
    from keiba_analysis.racing import board

    assert _px(source, ".name", "font-size") == board.MARKER_CHAR_PX


def test_the_marker_padding_fits_the_python_estimate(source: str):
    """丸＋すき間＋左右の余白＋枠線が、MARKER_BASE_PX に収まっていること。"""
    import re

    from keiba_analysis.racing import board

    dot = _px(source, ".dot", "width")
    rule = _rule(source, ".marker")
    gap = float(re.search(r"gap:\s*([\d.]+)px", rule).group(1))
    pad = [float(x.rstrip("px")) for x in re.search(r"padding:\s*([^;]+);", rule).group(1).split()]
    border = 2  # 左右1pxずつ
    assert dot + gap + pad[1] + pad[3] + border <= board.MARKER_BASE_PX


def test_the_fallback_lane_height_matches_python(script: str):
    """Pythonから値が来なかったときの控え。ずれていると初回だけ高さが違う。"""
    from keiba_analysis.racing import board

    assert f"DEFAULT_LANE_HEIGHT = {board.MIN_LANE_HEIGHT_PX};" in script


# --- 盤の見た目 ---------------------------------------------------------------------


def test_the_lanes_are_not_washed_in_colour(source: str):
    """段の背景を全面に塗ると、主役の馬が沈む。段の見分けは左端の色帯だけに任せる。"""
    import re

    for tier in ("A", "B", "C", "D"):
        rule = re.search(r'\.lane\[data-tier="%s"\] \{([^}]*)\}' % tier, source)
        assert rule is None or "background" not in rule.group(1), tier
        assert f'.lane[data-tier="{tier}"]::before' in source        # 左端の色帯はある


def test_the_lane_heading_is_just_the_letter(source: str):
    """見出しは A/B/C/D だけ。意味はツールチップと盤の下の1行に置く。

    もとは「A Class」＋長い説明文が3行に折り返して窮屈だった。
    """
    head = source.split(".lane-head {")[1].split("}")[0]
    assert "white-space: nowrap" in head
    assert ".lane-key" in source
    assert ".lane-name" not in source           # 日本語の段名は見出しに描かない
    assert ".lane-meaning" not in source        # 長い説明も見出しに置かない


# --- D段の馬を最初から落として見せる ------------------------------------------------


def test_a_horse_in_the_bottom_lane_looks_dropped(source: str):
    """D段は「消し」なので、丸を押して消した馬と**同じ見た目**にする。

    同じ宣言を2か所に書くと、片方だけ直す事故が起きる。セレクタをまとめる。
    """
    import re

    rule = re.search(r"\.marker\.excluded, \.marker\.dim \{([^}]*)\}", source)
    assert rule, "excluded と dim が同じ宣言を共有していない"
    assert "background" in rule.group(1)
    assert re.search(r"\.marker\.excluded \.name, \.marker\.dim \.name \{", source)


def test_the_bottom_lane_look_is_not_saved(script: str):
    """D段にいるという事実から毎回決まる見た目なので、保存する値は汚さない。"""
    body = script.split("function applyLook")[1].split("\n  }")[0]
    assert 'classList.toggle("dim", marker.tier === "D")' in body
    assert "is_excluded =" not in body          # 保存する値を書き換えない


def test_the_look_is_decided_in_one_place_and_follows_the_drag(script: str):
    """段をまたいだときに呼ばないと、CからDへ落としても白地のままになる。"""
    assert script.count("function applyLook") == 1
    # 描くとき・ドラッグで段が変わったとき・丸を押したときの3か所から呼ぶ
    assert script.count("applyLook(marker)") >= 3
    moved = script.split("if (tier !== marker.tier) {")[1].split("}")[0]
    assert "applyLook(marker)" in moved


def test_a_hand_placed_horse_keeps_its_border_even_when_dropped(source: str):
    """D段がほぼ全部灰色になるので、ここが負けると「どれを自分で動かしたか」が消える。

    同じ強さのセレクタは後ろが勝つので、`.manual` を `.excluded` / `.dim` より後ろに置く。
    """
    assert source.index(".marker.excluded, .marker.dim") < source.index(".marker.manual {")


def test_the_long_meaning_moves_to_the_tooltip(script: str):
    """説明は消さずに、マウスを乗せたときだけ出す。"""
    assert 'querySelector(".lane-head").title' in script
    assert "lane.meaning" in script


def test_the_lane_width_comes_from_python(script: str):
    """見出しの幅はPython側（board.LANE_HEAD_PX）が唯一の出どころ。

    CSSに直書きすると、馬の重なりを見積もる盤幅（NOMINAL_FIELD_PX）だけが
    古い前提のまま取り残される。
    """
    assert "payload.lane_head" in script
    assert "laneHead" in script


def test_an_empty_lane_says_so(script: str):
    """段の高さは全段そろえてあるので、空の段はぽっかり空く。そこを情報に変える。"""
    assert "lane-empty" in script and "該当なし" in script


def test_a_horse_at_the_edge_is_nudged_back_inside(script: str):
    """馬は position を中心に置くので、端の馬は幅の半分だけ外へ出てしまう。

    見た目だけ内側へ寄せる。保存する値（marker.position）は動かさない
    （動かすと、開くたびに少しずつ内側へ寄っていく）。
    """
    assert "function keepInside" in script
    body = script.split("function keepInside")[1]
    assert "marker.position" not in body.split("\n  }")[0]


def test_a_crossed_out_horse_is_only_greyed_out(source: str):
    """取消線はやめ、灰色にするだけにする。"""
    assert "line-through" not in source
    assert ".marker.excluded" in source


def test_the_umaban_keeps_its_colour_when_crossed_out(source: str):
    """消した馬でも**馬番の丸は枠色のまま**にする（どの馬か分かるように）。"""
    excluded = [line for line in source.splitlines() if ".marker.excluded" in line]
    assert excluded, "消した馬の見た目の指定が無い"
    assert not any(".dot" in line for line in excluded), "丸に指定が当たっている"
    assert not any("opacity" in line for line in excluded), "全体を薄くすると丸まで薄くなる"
    assert any(".name" in line for line in excluded)        # 名前は落ち着かせる


def test_a_tiny_wobble_is_not_a_drag(script: str):
    """丸を押すときに指が1pxぶれただけで「手で置いた」扱いにしない。

    手で置いた馬は引き伸ばしの対象から外れて位置が固定されるので、
    押しただけのつもりで位置が固定されると分かりにくい。
    """
    assert "DRAG_THRESHOLD_PX" in script
    handler = script.split("function onMove(")[1]
    assert "DRAG_THRESHOLD_PX" in handler.split("moved = true")[0]


# --- 実際に動かして確かめる（自動保存とジャンプ） -------------------------------------------

OPEN_BOARD = """
render(PAYLOAD);
var keito = markerOf("キャントウェイト");
var robu = markerOf("ロブチェン");
"""


@needs_jsc
def test_dragging_saves_by_itself(script, tmp_path):
    """ドラッグし終わったら、保存ボタンを押さなくても保存が飛ぶ。"""
    answer = run_board(script, OPEN_BOARD + """
drag(keito);
var answer = { sent: SENT.length, status: statusText(),
               manual: SENT[0].markers.filter(function (m) { return m.is_manual; }).length };
""", tmp_path)
    assert answer["sent"] == 1
    assert answer["status"] == "保存中…"
    assert answer["manual"] == 1


@needs_jsc
def test_crossing_a_horse_out_saves_by_itself(script, tmp_path):
    """丸を押して消す／戻すも、そのつど保存する。"""
    answer = run_board(script, OPEN_BOARD + """
tap(keito, keito.querySelector(".dot"));
var first = SENT[SENT.length - 1].markers.filter(function (m) { return m.is_excluded; });
tap(keito, keito.querySelector(".dot"));
var back = SENT[SENT.length - 1].markers.filter(function (m) { return m.is_excluded; });
var answer = { sent: SENT.length, excluded: first.length, back: back.length,
               who: first.length ? first[0].horse_id : null };
""", tmp_path)
    assert answer["sent"] == 2
    assert answer["excluded"] == 1 and answer["who"] == "2021102800"
    assert answer["back"] == 0


@needs_jsc
def test_a_comment_is_saved_after_you_stop_typing(script, tmp_path):
    """コメントは1文字ごとには送らない（打ち終わりとフォーカスが外れたとき）。"""
    answer = run_board(script, OPEN_BOARD + """
tap(keito, keito.querySelector(".pen"));          // ✎でコメント欄
var opened = NODES.editor.attrs["class"].indexOf("open") >= 0;
var box = NODES.comment;
box.value = "выход";
box.fire("input", { target: box });
box.value = "この馬は買い";
box.fire("input", { target: box });
var duringTyping = SENT.length;                    // まだ送らない
runTimers();                                       // 打ち終わりを待つ
var answer = { opened: opened, duringTyping: duringTyping, sent: SENT.length,
               comment: (SENT[SENT.length - 1] || {}).markers
                 .filter(function (m) { return m.comment; })
                 .map(function (m) { return m.horse_id + ":" + m.comment; }),
               head: NODES["editor-head"].text() };
""", tmp_path)
    assert answer["opened"] is True
    assert answer["duringTyping"] == 0            # 打っている間は送らない
    assert answer["sent"] == 1
    assert answer["comment"] == ["2021102800:この馬は買い"]
    assert "キャントウェイト" in answer["head"]


@needs_jsc
def test_leaving_the_comment_box_saves_at_once(script, tmp_path):
    """欄から離れたら、待たずに保存する。"""
    answer = run_board(script, OPEN_BOARD + """
tap(keito, keito.querySelector(".pen"));
var box = NODES.comment;
box.value = "メモ";
box.fire("input", { target: box });
var before = SENT.length;
box.fire("blur", {});
var answer = { before: before, after: SENT.length, timers: runTimers() };
""", tmp_path)
    assert answer["before"] == 0
    assert answer["after"] == 1
    assert answer["timers"] == 0                  # 待ちは取り消されている（二重送信しない）


@needs_jsc
def test_the_board_is_not_rebuilt_when_the_save_comes_back(script, tmp_path):
    """自分の保存が返ってきただけの描画では、盤を作り直さない（書きかけを守る）。"""
    answer = run_board(script, OPEN_BOARD + """
keito.MARK = "同じ要素のまま";
tap(keito, keito.querySelector(".dot"));
// Streamlitは保存を受けたあと、**保存前**の中身に新しい番号を付けて送り返してくる
var echo = JSON.parse(JSON.stringify(PAYLOAD));
echo.rev = 2;
render(echo);
var again = markerOf("キャントウェイト");
var answer = { same: again.MARK === "同じ要素のまま", status: statusText(),
               stillExcluded: (again.attrs["class"] || "").indexOf("excluded") >= 0 };
""", tmp_path)
    assert answer["same"] is True                 # 作り直していない
    assert answer["status"] == "保存しました"
    assert answer["stillExcluded"] is True        # 消した見た目も残っている


@needs_jsc
def test_pressing_a_name_jumps_to_that_horse_in_the_grid(script, tmp_path):
    """馬名を押すと、同じページの馬柱のその馬の行へ飛ぶ（複数の馬で確かめる）。"""
    answer = run_board(script, """
// 馬柱の行を2頭ぶん置く（idは pg-<レースID>-<馬ID>）
var rowA = putInParent("pg-202606040611-2021102800", new Node("tr"));
var rowB = putInParent("pg-202606040611-2021102801", new Node("tr"));
render(PAYLOAD);
markerOf("キャントウェイト").fire("pointerdown", {
  target: markerOf("キャントウェイト").querySelector(".name"), pointerId: 1,
  clientX: 10, clientY: 10, preventDefault: function () {} });
markerOf("キャントウェイト").fire("pointerup", {});
var first = { a: !!rowA.scrolledIntoView, b: !!rowB.scrolledIntoView,
              markA: (rowA.attrs["class"] || "").indexOf("pg-jumped") >= 0 };
tap(markerOf("ロブチェン"), markerOf("ロブチェン").querySelector(".name"));
var answer = { first: first, b: !!rowB.scrolledIntoView,
               markB: (rowB.attrs["class"] || "").indexOf("pg-jumped") >= 0,
               sent: SENT.length };
""", tmp_path)
    assert answer["first"] == {"a": True, "b": False, "markA": True}   # 1頭目だけ飛ぶ
    assert answer["b"] is True and answer["markB"] is True             # 2頭目も正しく飛ぶ
    assert answer["sent"] == 0                    # 飛ぶだけ。保存はしない


@needs_jsc
def test_a_name_never_jumps_into_another_race(script, tmp_path):
    """**別のレースの馬柱しか出ていないときは、何もしない。**

    以前、馬名クリックで無関係なレースへ飛ぶ事故があったので、行のidに
    レースIDを入れて、一致しなければ飛ばないようにしてある。
    """
    answer = run_board(script, """
// 別のレース（202606040612）の馬柱だけが出ている
var other = putInParent("pg-202606040612-2021102800", new Node("tr"));
render(PAYLOAD);
tap(markerOf("キャントウェイト"), markerOf("キャントウェイト").querySelector(".name"));
var answer = { jumped: !!other.scrolledIntoView,
               marked: (other.attrs["class"] || "").indexOf("pg-jumped") >= 0 };
""", tmp_path)
    assert answer == {"jumped": False, "marked": False}


@needs_jsc
def test_the_grid_tab_is_opened_before_jumping(script, tmp_path):
    """オッズを見ているときは、馬柱のタブを開いてから飛ぶ。"""
    answer = run_board(script, """
var row = putInParent("pg-202606040611-2021102800", new Node("tr"));
row.offsetParent = null;                           // 馬柱のタブが閉じている
var tab = putInParent("tab-grid", new Node("button"));
tab.attrs["data-testid"] = "stTab";
tab.textContent = "馬柱（芝・直近10走）";
var odds = putInParent("tab-odds", new Node("button"));
odds.attrs["data-testid"] = "stTab";
odds.textContent = "オッズ";
render(PAYLOAD);
tap(markerOf("キャントウェイト"), markerOf("キャントウェイト").querySelector(".name"));
var answer = { gridTabClicked: !!tab.clicked, oddsTabClicked: !!odds.clicked,
               jumped: !!row.scrolledIntoView };
""", tmp_path)
    assert answer == {"gridTabClicked": True, "oddsTabClicked": False, "jumped": True}


# --- スマホ（payload.layout = "phone"） ----------------------------------------------


@needs_jsc
def test_the_phone_board_still_drags_and_saves(script, tmp_path):
    """スマホの寸法でも、回していないとき（横持ち・親が読めない）は今までどおり動かして保存できる。"""
    payload = {**_payload(), "layout": "phone", "reserve_px": 180}
    answer = run_board(script, OPEN_BOARD + """
drag(keito);
var answer = { sent: SENT.length,
               manual: SENT[0].markers.filter(function (m) { return m.is_manual; }).length };
""", tmp_path, payload=payload)
    assert answer == {"sent": 1, "manual": 1}


def test_the_phone_board_turns_the_pointer_back_when_rotated(script: str):
    """縦持ちで盤を90度回しているときは、押した位置を回転の逆で戻してから測る。"""
    move = script.split("function onMove(moveEvent)")[1].split("function onUp()")[0]
    assert "pointIn(moveEvent" in move                    # ドラッグの位置はこの1か所で測る
    point = script.split("function pointIn(event, el)")[1].split("\n  }\n")[0]
    assert "if (!rotated)" in point and "getBoundingClientRect" in point   # 回していなければ今までどおり
    assert "rotateScale" in point                         # 縮めているぶんも戻す


def test_the_phone_sizes_match_the_python_estimate(source: str):
    """スマホのマーカーの寸法が、board.PHONE の見積もりに収まること（PCと同じ考え方）。"""
    import re

    from keiba_analysis.racing import board

    name = re.search(r"body\.phone \.name \{\s*font-size:\s*([\d.]+)px", source)
    assert name and float(name.group(1)) == board.PHONE.marker_char
    dot = re.search(r"body\.phone \.dot \{\s*width:\s*([\d.]+)px", source)
    rule = re.search(r"body\.phone \.marker \{([^}]*)\}", source).group(1)
    gap = float(re.search(r"gap:\s*([\d.]+)px", rule).group(1))
    pad = [float(x.rstrip("px")) for x in re.search(r"padding:\s*([^;]+);", rule).group(1).split()]
    assert float(dot.group(1)) + gap + pad[1] + pad[3] + 4 <= board.PHONE.marker_base   # 枠線2px×2
