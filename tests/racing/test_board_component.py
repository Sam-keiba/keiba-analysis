"""予想ボードのカスタムコンポーネント（素のHTML+JS。2026-10 の 段×脚質のカード型）。

**押したらどうなるか**は、JavaScriptCore（jsc）に最小のDOM（`fixtures/mini_dom.js`）を噛ませて
実際に動かして確かめる（ドラッグで段と列が変わって自動保存・馬を押すと馬柱へ・馬柱の枠から盤へ）。
列の位置は最小のDOMの `rect` で置く。本当のドラッグの手触りだけは画面を開いて見る。
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


def _marker(horse_id: str, name: str, umaban: int, tier: str = "B", column: int = 1,
            order: float = 0.0, **kwargs) -> dict:
    base = {
        "horse_id": horse_id, "umaban": umaban, "waku": 1, "horse_name": name,
        "tier": tier, "column": column, "order": order, "position": 0.625, "lane_offset": None,
        "comment": "", "is_manual": False, "is_excluded": False, "color": "#fff", "text_color": "#000",
        "style": "先行", "explanation": "説明",
    }
    return {**base, **kwargs}


def _payload(layout: str = "pc", rev: int = 1) -> dict:
    return {
        "race_id": RACE_ID, "layout": layout, "rev": rev, "version": f"v{rev}",
        "lanes": [{"key": k, "label": k, "meaning": k} for k in ("A", "B", "C", "D")],
        "columns": ["逃げ", "先行", "差し", "追込"],
        "column_centers": [0.875, 0.625, 0.375, 0.125],
        "markers": [
            _marker("h1", "キャントウェイト", 1, "B", 1, 0.0),
            _marker("h2", "ロブチェン", 2, "B", 1, 1.0),
            _marker("h3", "アドマイヤテラ", 3, "C", 2, 0.0),
            _marker("h4", "シュガークン", 4, "D", 3, 0.0),
        ],
    }


HARNESS = """
ensureIds(["root", "board"]);
function chipOf(name) {
  return NODES.board.find(function (c) {
    return (c.attrs["class"] || "").indexOf("chip") === 0
      && c.findAll(function (x) { return x._text === name; }).length;
  });
}
function colOf(tier, col) {
  return NODES.board.find(function (c) {
    return (c.attrs["class"] || "").split(" ")[0] === "col" && c.dataset.tier === tier && c.dataset.col === String(col);
  });
}
/** 列の位置を置く（段ごとに縦に100px、列は右から 逃げ・先行・差し・追込 の順に横へ100px）。 */
function layOut() {
  ["A", "B", "C", "D"].forEach(function (tier, t) {
    for (var c = 0; c < 4; c++) {
      var col = colOf(tier, c);
      col.rect = { left: 400 - 100 * (c + 1), top: 100 * t, width: 90, height: 90 };
      col.children.forEach(function (chip, i) {
        chip.rect = { left: col.rect.left, top: col.rect.top + 20 * i, width: 90, height: 18 };
      });
    }
  });
}
/** 押して動かして (x, y) で離す（ドラッグ）。 */
function dragTo(chip, x, y) {
  chip.fire("pointerdown", { target: chip, pointerId: 1, clientX: 5, clientY: 5, preventDefault: function () {} });
  chip.fire("pointermove", { clientX: x, clientY: y });
  chip.fire("pointerup", {});
}
function tap(chip) {
  chip.fire("pointerdown", { target: chip, pointerId: 1, clientX: 5, clientY: 5, preventDefault: function () {} });
  chip.fire("pointerup", {});
}
function cls(node) { return node.attrs["class"] || ""; }
"""


def run_board(script: str, scenario: str, tmp_path: pathlib.Path, payload=None):
    """最小のDOMで盤を動かし、シナリオの `answer` をJSONで受け取る。"""
    body = (
        f"const PAYLOAD = {json.dumps(payload or _payload(), ensure_ascii=False)};\n"
        + MINI_DOM.read_text() + HARNESS
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
    assert COMPONENT.exists()


def test_it_speaks_the_streamlit_component_protocol(script: str):
    for message in ("streamlit:componentReady", "streamlit:setComponentValue", "streamlit:setFrameHeight"):
        assert message in script


@needs_jsc
def test_the_board_is_four_tier_cards_by_four_style_columns(script, tmp_path):
    """段ごとのカードに、脚質の4列（番号0＝逃げ）。馬は保存の列と並び順どおりに入る。"""
    answer = run_board(script, """
render(PAYLOAD);
var answer = {
  tiers: NODES.board.findAll(function (c) { return cls(c) === "tier"; }).map(function (t) { return t.dataset.tier; }),
  cols: NODES.board.findAll(function (c) { return cls(c).split(" ")[0] === "col"; }).length,
  b1: colOf("B", 1).children.map(function (c) { return c.dataset.horse; }),
  c2: colOf("C", 2).children.map(function (c) { return c.dataset.horse; }),
};
""", tmp_path)
    assert answer == {"tiers": ["A", "B", "C", "D"], "cols": 16, "b1": ["h1", "h2"], "c2": ["h3"]}


@needs_jsc
def test_the_d_tier_is_greyed_and_a_hand_placed_horse_has_a_green_border(script, tmp_path):
    payload = _payload()
    payload["markers"][0]["is_manual"] = True
    answer = run_board(script, """
render(PAYLOAD);
var answer = { d: cls(chipOf("シュガークン")), manual: cls(chipOf("キャントウェイト")), plain: cls(chipOf("ロブチェン")) };
""", tmp_path, payload)
    assert "dim" in answer["d"]
    assert "manual" in answer["manual"] and "manual" not in answer["plain"]


@needs_jsc
def test_dragging_to_another_tier_and_column_saves_by_itself(script, tmp_path):
    """C段の差しの馬を A段の逃げ（右端）へ。段・列（中心の値）・動かした印が保存に乗る。"""
    answer = run_board(script, """
render(PAYLOAD); layOut();
dragTo(chipOf("アドマイヤテラ"), 345, 40);          // A段・逃げ（left 300〜390, top 0〜90）
var saved = SENT[0].markers.filter(function (m) { return m.horse_id === "h3"; })[0];
var answer = { sent: SENT.length, tier: saved.tier, position: saved.position, manual: saved.is_manual,
               movedChip: cls(chipOf("アドマイヤテラ")),
               a0: colOf("A", 0).children.map(function (c) { return c.dataset.horse; }) };
""", tmp_path)
    assert answer["sent"] == 1
    assert answer["tier"] == "A" and answer["position"] == 0.875 and answer["manual"] is True
    assert answer["a0"] == ["h3"]
    assert "manual" in answer["movedChip"]


@needs_jsc
def test_dropping_between_two_horses_goes_between_them(script, tmp_path):
    """B段・先行の2頭の間に落とすと、その2頭の間の並び順になる（2頭の順番は変えない）。"""
    answer = run_board(script, """
render(PAYLOAD); layOut();
// B段・先行（left 200〜290, top 100〜190）。1頭目（top 100〜118）の下、2頭目（top 120〜138）の真ん中より上
dragTo(chipOf("アドマイヤテラ"), 245, 125);
var saved = SENT[0].markers.filter(function (m) { return m.horse_id === "h3"; })[0];
var answer = { order: saved.lane_offset, b1: colOf("B", 1).children.map(function (c) { return c.dataset.horse; }) };
""", tmp_path)
    assert answer["order"] == 0.5
    assert answer["b1"] == ["h1", "h3", "h2"]


@needs_jsc
def test_dropping_outside_the_board_changes_nothing(script, tmp_path):
    answer = run_board(script, """
render(PAYLOAD); layOut();
dragTo(chipOf("アドマイヤテラ"), 900, 900);
var answer = { sent: SENT.length, c2: colOf("C", 2).children.map(function (c) { return c.dataset.horse; }) };
""", tmp_path)
    assert answer == {"sent": 0, "c2": ["h3"]}


@needs_jsc
def test_a_tiny_wobble_is_a_press_not_a_drag(script, tmp_path):
    """押すときに指が少しぶれただけでは動かさない（押しただけ＝馬柱へ）。"""
    answer = run_board(script, """
var row = putInParent("pg-202606040611-h1", new Node("tr"));
render(PAYLOAD); layOut();
var chip = chipOf("キャントウェイト");
chip.fire("pointerdown", { target: chip, pointerId: 1, clientX: 5, clientY: 5, preventDefault: function () {} });
chip.fire("pointermove", { clientX: 7, clientY: 6 });
chip.fire("pointerup", {});
var answer = { sent: SENT.length, jumped: !!row.scrolledIntoView };
""", tmp_path)
    assert answer == {"sent": 0, "jumped": True}


@needs_jsc
def test_pressing_a_horse_jumps_to_that_horse_in_the_grid(script, tmp_path):
    answer = run_board(script, """
var rowA = putInParent("pg-202606040611-h1", new Node("tr"));
var rowB = putInParent("pg-202606040611-h2", new Node("tr"));
render(PAYLOAD);
tap(chipOf("ロブチェン"));
var answer = { a: !!rowA.scrolledIntoView, b: !!rowB.scrolledIntoView,
               mark: cls(rowB).indexOf("pg-jumped") >= 0, sent: SENT.length };
""", tmp_path)
    assert answer == {"a": False, "b": True, "mark": True, "sent": 0}


@needs_jsc
def test_a_horse_never_jumps_into_another_race(script, tmp_path):
    answer = run_board(script, """
var other = putInParent("pg-202606040612-h1", new Node("tr"));
render(PAYLOAD);
tap(chipOf("キャントウェイト"));
var answer = { jumped: !!other.scrolledIntoView };
""", tmp_path)
    assert answer == {"jumped": False}


@needs_jsc
def test_the_own_save_coming_back_does_not_redraw(script, tmp_path):
    """保存したあとに届く「保存前」の中身で描き直すと、配置が巻き戻る。"""
    answer = run_board(script, """
render(PAYLOAD); layOut();
dragTo(chipOf("アドマイヤテラ"), 345, 40);
var again = JSON.parse(JSON.stringify(PAYLOAD)); again.rev = 2;
render(again);                                      // 保存前の中身（h3 は C段のまま）
var answer = { a0: colOf("A", 0).children.map(function (c) { return c.dataset.horse; }) };
""", tmp_path)
    assert answer == {"a0": ["h3"]}


@needs_jsc
def test_an_older_redraw_is_thrown_away(script, tmp_path):
    answer = run_board(script, """
var newer = JSON.parse(JSON.stringify(PAYLOAD)); newer.rev = 5; newer.version = "v5";
newer.markers[2].tier = "A"; newer.markers[2].column = 0;
render(newer);
render(PAYLOAD);                                    // あとから届いた古い番号（rev 1）
var answer = { a0: colOf("A", 0).children.map(function (c) { return c.dataset.horse; }) };
""", tmp_path)
    assert answer == {"a0": ["h3"]}


@needs_jsc
def test_the_phone_squeezes_long_names_onto_one_line(script, tmp_path):
    """スマホは馬名を1行に収める（8文字は横97%、9文字以上は横92%）。"""
    payload = _payload(layout="phone")
    payload["markers"][0]["horse_name"] = "アイウエオカキク"          # 8文字
    payload["markers"][1]["horse_name"] = "アイウエオカキクケ"        # 9文字
    answer = run_board(script, """
render(PAYLOAD);
function nameOf(chip) { return chip.find(function (x) { return cls(x) === "name"; }); }
var answer = { eight: nameOf(chipOf("アイウエオカキク")).style.transform,
               nine: nameOf(chipOf("アイウエオカキクケ")).style.transform,
               short: nameOf(chipOf("アドマイヤテラ")).style.transform || "" };
""", tmp_path, payload)
    assert answer == {"eight": "scaleX(0.97)", "nine": "scaleX(0.92)", "short": ""}


BOARD_LINK = """
var parentClick = null;
parentDocument.addEventListener = function (type, fn) { if (type === "click") parentClick = fn; };
parentDocument.removeEventListener = function () {};
var tab = putInParent("tab-board", new Node("button"));
tab.attrs["data-testid"] = "stTab";
tab.textContent = "予想";
function linkTo(race, horse) {
  var link = new Node("span");
  link.attrs["class"] = "board-link";
  link.dataset = { race: race, horse: horse };
  return link;
}
render(PAYLOAD);
var keito = chipOf("キャントウェイト");
"""


@needs_jsc
def test_the_waku_opens_the_board_tab_and_lights_the_horse(script, tmp_path):
    """馬柱の枠を押すと「予想」のタブを開いて、その馬を光らせる。"""
    answer = run_board(script, BOARD_LINK + """
parentClick({ target: linkTo("202606040611", "h1"), preventDefault: function () {} });
var answer = { tab: !!tab.clicked, flash: cls(keito).indexOf("flash") >= 0 };
runTimers();
answer.after = cls(keito).indexOf("flash") >= 0;
""", tmp_path)
    assert answer == {"tab": True, "flash": True, "after": False}


@needs_jsc
def test_the_waku_of_another_race_does_nothing(script, tmp_path):
    answer = run_board(script, BOARD_LINK + """
parentClick({ target: linkTo("202606040612", "h1"), preventDefault: function () {} });
var answer = { tab: !!tab.clicked, flash: cls(keito).indexOf("flash") >= 0 };
""", tmp_path)
    assert answer == {"tab": False, "flash": False}
