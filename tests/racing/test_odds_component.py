"""オッズのカスタムコンポーネント（券種タブ・馬選択・買い目）。

**押したらどうなるか**は、JavaScriptCore（jsc）に最小のDOM
（`fixtures/mini_dom.js`）を噛ませて**実際に動かして**確かめる。
「クリアを押したのにチェックが外れない」のようなバグは、ソースの字面を
見るだけのテストでは2回続けてすり抜けたので、操作の結果そのものを見る。

見た目（CSSの大きさ）とStreamlitとの約束ごとは、ソースから直に確かめる。
"""

import json
import pathlib
import re
import subprocess

import pytest

COMPONENT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "keiba_analysis" / "racing" / "odds_component" / "index.html"
)
JSC = pathlib.Path(
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
)
needs_jsc = pytest.mark.skipif(not JSC.exists(), reason="JavaScriptCore（jsc）が無い環境ではスキップ")


@pytest.fixture(scope="module")
def source() -> str:
    return COMPONENT.read_text()


@pytest.fixture(scope="module")
def script(source: str) -> str:
    return "\n".join(re.findall(r"<script>(.*?)</script>", source, re.S))


def take_function(script: str, name: str) -> str:
    """コンポーネントから関数を1つだけ切り出す（jscで動かすため）。

    関数はどれも同じ深さ（2字下げ）に書いてあるので、次の `  function ` の手前までを取る。
    """
    start = script.index(f"function {name}(")
    rest = script[start:]
    end = rest.find("\n  function ")
    return rest if end < 0 else rest[:end]


MINI_DOM = pathlib.Path(__file__).parent / "fixtures" / "mini_dom.js"


def _horse(number: int, name: str, odds: float) -> dict:
    waku = min(8, (number + 1) // 2)
    return {"number": number, "waku": waku, "bg": "#ffffff", "fg": "#1b1b1b",
            "name": name, "odds": odds, "pop": number}


def _bet(key: str, label: str, legs: int, table: dict, **kw) -> dict:
    return {"key": key, "label": label, "legs": legs,
            "ordered": kw.get("ordered", False), "ranged": kw.get("ranged", False),
            "byFrame": kw.get("byFrame", False), "color": kw.get("color", "#c0201a"),
            "odds": table, "count": len(table), "available": bool(table),
            "time": "12時31分現在オッズ" if table else None}


def _payload() -> dict:
    """16頭立てで単勝・馬連・ワイドが取り込み済み、という画面の材料。"""
    horses = [_horse(n, f"ウマ{n:02d}", 3.0 + n) for n in range(1, 17)]
    tansho = {str(h["number"]): [h["odds"], None] for h in horses}
    pairs = {f"{a}-{b}": [round(3.0 + a * b * 0.9, 1), None]
             for a in range(1, 17) for b in range(a + 1, 17)}
    # 馬単は着順どおり、3連単は数を絞って（取り込み済みに見えれば足りる）
    exacta = {f"{a}-{b}": [round(5.0 + a * b * 1.3, 1), None]
              for a in range(1, 17) for b in range(1, 17) if a != b}
    trifecta = {f"{a}-{b}-{c}": [round(9.0 + a * b * c * 0.7, 1), None]
                for a in range(1, 7) for b in range(1, 7) for c in range(1, 7)
                if len({a, b, c}) == 3}
    return {
        "betTypes": [
            _bet("tansho", "単勝", 1, tansho),
            _bet("fukusho", "複勝", 1, tansho, ranged=True, color="#f08300"),
            _bet("wakuren", "枠連", 2, {}, byFrame=True, color="#8a6d3b"),
            _bet("umaren", "馬連", 2, pairs, color="#2168c3"),
            _bet("wide", "ワイド", 2, pairs, ranged=True, color="#189a54"),
            _bet("umatan", "馬単", 2, exacta, ordered=True, color="#7a5aa8"),
            _bet("sanrenpuku", "3連複", 3, {}, color="#0f7b8a"),
            _bet("sanrentan", "3連単", 3, trifecta, ordered=True, color="#b03a6b"),
        ],
        "tabs": [
            {"key": "tansho", "label": "単勝・複勝", "bets": ["tansho", "fukusho"], "chip": "12:31現在"},
            {"key": "wakuren", "label": "枠連", "bets": ["wakuren"], "chip": "未取得"},
            {"key": "umaren", "label": "馬連", "bets": ["umaren"], "chip": "12:31現在"},
            {"key": "wide", "label": "ワイド", "bets": ["wide"], "chip": "12:31現在"},
            {"key": "umatan", "label": "馬単", "bets": ["umatan"], "chip": "12:31現在"},
            {"key": "sanrenpuku", "label": "3連複", "bets": ["sanrenpuku"], "chip": "未取得"},
            {"key": "sanrentan", "label": "3連単", "bets": ["sanrentan"], "chip": "12:31現在"},
        ],
        "horses": horses,
        "frames": [{"number": w, "bg": "#fff", "fg": "#000", "umaban": [w * 2 - 1, w * 2],
                    "name": f"{w * 2 - 1}・{w * 2}"} for w in range(1, 9)],
        "focus": None, "slip": [], "slipSavedAt": None,
        # 符号は2つ（version=全部 / drawVersion=買い目を除いたぶん）
        "version": "v1", "drawVersion": "d1",
    }


def run_component(script: str, scenario: str, tmp_path: pathlib.Path, payload=None):
    """最小のDOMでコンポーネントを動かし、シナリオの `answer` をJSONで受け取る。

    シナリオからは `NODES`（tabs/panel/slip）・`render()`・`press()`・`SENT` が使える。
    """
    body = (
        f"const PAYLOAD = {json.dumps(payload or _payload(), ensure_ascii=False)};\n"
        + MINI_DOM.read_text()
        + "\n(function () {\n" + script + "\n})();\n"
        + scenario
        + "\nprint(JSON.stringify(answer));\n"
    )
    path = tmp_path / "scene.js"
    path.write_text(body)
    result = subprocess.run([str(JSC), str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])


def run_js(body: str, script: str, tmp_path: pathlib.Path, *names: str) -> str:
    """コンポーネントの関数を取り出して動かす（既定は `combinations`）。"""
    functions = "\n".join(take_function(script, name) for name in (names or ("combinations",)))
    path = tmp_path / "combos.js"
    path.write_text(functions + "\n" + body)
    result = subprocess.run([str(JSC), str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _rule(source: str, selector: str) -> str:
    """そのセレクタだけの宣言を取り出す（board_componentのテストと同じ作り）。"""
    m = re.search(r"^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", source, re.M | re.S)
    assert m, f"セレクタが見つかりません: {selector}"
    return m.group(1)


def _px(source: str, selector: str, prop: str) -> float:
    m = re.search(rf"{prop}:\s*([\d.]+)px", _rule(source, selector))
    assert m, f"{prop} が {selector} に無い"
    return float(m.group(1))


# --- Streamlitとの約束ごと ---------------------------------------------------------------


def test_the_component_file_is_where_the_widget_looks_for_it():
    assert COMPONENT.is_file() and COMPONENT.name == "index.html"


def test_it_speaks_the_streamlit_component_protocol(script: str):
    for message in ("streamlit:componentReady", "streamlit:render", "streamlit:setFrameHeight"):
        assert message in script, message


def test_the_value_goes_back_only_from_one_place(script: str):
    """値を返すたびに画面が再実行されるので、返す口は1つに絞る。

    以前の予想印が「押すたびに飛ぶ」で使いものにならなかったので、
    **チェック・タブ・並べ替えでは返さない**（ブラウザの中だけで完結させる）。
    返すのは「更新マークを押した」「買い目が変わった」の2つだけ。
    """
    assert script.count("streamlit:setComponentValue") == 1
    assert take_function(script, "sendValue").count("streamlit:setComponentValue") == 1
    # 値を送る道はこの3つだけ（更新マーク・買い目の券種をまとめて更新・買い目の保存）
    senders = [name for name in ("requestFetch", "requestFetchMany", "saveSlip")
               if "sendValue(" in take_function(script, name)]
    assert senders == ["requestFetch", "requestFetchMany", "saveSlip"]
    assert script.count("sendValue(") == 4        # 定義1つ＋上の3か所


def test_choosing_a_horse_does_not_send_anything(script: str):
    """チェックを入れる・タブを変える・並べ替えるだけでは値を返さない。"""
    for name in ("drawSlots", "drawTabs", "drawSingle"):
        body = take_function(script, name)
        assert "sendValue(" not in body, name
        assert "requestFetch(" not in body, name


def test_the_amount_is_saved_when_the_input_is_finished(script: str):
    """金額は1文字ごとではなく、入力を終えたとき（change）にだけ保存する。"""
    body = take_function(script, "drawSlip")
    assert 'amount.addEventListener("change"' in body
    assert 'amount.addEventListener("input"' not in body


def test_the_height_is_sent_again_after_every_redraw(script: str):
    """点数や組み合わせの行数で高さが変わるので、描き直すたびに伝える。"""
    assert script.count("setHeight()") >= 4


def test_the_same_contents_are_not_drawn_again(script: str):
    """**押している最中にDOMを作り直さない**ための判定（クリックが消える原因だった）。

    Streamlitは高さを受け取るたびに `render` をコンポーネントへ送り返す。
    受けるたびに作り直していると「高さを送る→renderが返る→作り直す→高さを送る」の
    往復が止まらず、押した要素がその瞬間に別物へ差し替わってクリックが成立しない。
    予想ボードの盤と同じく、中身の符号（version）が同じなら描き直さない。
    """
    handler = script.split('event.data.type !== "streamlit:render"')[1]
    guard = handler.index("next.version === appliedVersion")
    block = handler[guard:handler.index("appliedVersion = next.version")]
    assert "return;" in block                      # 同じ中身なら、ここで打ち切る
    # 判定は**描く前**にあること（描いてから捨てたのでは意味が無い）
    for name in ("drawTabs()", "drawSlip()"):
        assert handler.index(name) > guard, name


def test_the_update_mark_comes_back_even_when_nothing_changed(script: str):
    """取り込んだのに中身が変わらないことがある（まだ発売されていない券種）。

    そのときも「取り込み中…」のままにしない。打ち切る側でも描き直して元に戻す。
    """
    handler = script.split('event.data.type !== "streamlit:render"')[1]
    guard = handler.index("next.version === appliedVersion")
    block = handler[guard:handler.index("appliedVersion = next.version")]
    assert "waitingFetch" in block and "drawPanel(false)" in block
    assert "waitingFetch = true;" in take_function(script, "requestFetch")


def test_the_same_height_is_not_sent_twice(script: str):
    """高さを送るとrenderが返ってくるので、変わっていないときは送らない。"""
    assert "if (!heightChanged(height, lastHeight)) return;" in script


# --- 購入の導線を作らない ---------------------------------------------------------------


def test_there_is_no_way_to_buy_anything(source: str):
    """スコープ外。買い目（買うつもりの控え）は作るが、**購入・投票はしない**。

    コメント（`<!-- … -->`）にはその方針そのものを書いてあるので、外して見る。
    """
    visible = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    for word in ("購入", "投票", "IPAT", "カート", "馬券を買"):
        assert word not in visible, word


def test_the_bet_slip_is_only_a_note_of_what_to_buy(source: str):
    """買い目は「何をどれだけ買うつもりか」の控え。金額は1点あたり。"""
    assert "買い目" in source
    assert "1点あたり" in source


# --- 画面の作り -------------------------------------------------------------------------


def test_the_tabs_come_from_python(script: str):
    """タブの並びと見出しはPython側（odds.tabs）で決める。

    単勝・複勝が1つのタブなので、券種（BET_TYPES）とタブは1対1ではない。
    """
    from keiba_analysis.racing import odds

    assert "(payload.tabs || []).forEach" in script
    assert odds.tabs()[0]["label"] == "単勝・複勝"


def test_one_tab_can_hold_two_bet_types(script: str):
    """単勝・複勝のページは、1つの表に両方の列を並べる。"""
    body = take_function(script, "drawSingle")
    assert "t.bets.map(bet)" in body
    assert '"選んだ馬を" + b.label + "へ"' in body


def test_the_column_heads_say_whether_the_order_matters(script: str):
    """馬単・3連単は「1着/2着/3着」、順序を見ない券種は「1頭目/2頭目」。"""
    assert '["1着", "2着", "3着"]' in script
    assert '["1頭目", "2頭目", "3頭目"]' in script


def test_each_column_can_be_filled_or_cleared(script: str):
    assert '"全通り"' in script and '"クリア"' in script


def test_the_list_can_be_sorted_by_odds_or_by_combination(script: str):
    assert '"オッズ順"' in script and '"組み合わせ順"' in script


def test_the_active_tab_is_marked_and_the_panel_fades(source: str):
    assert '.tab[aria-selected="true"]' in source
    assert "@keyframes panel-in" in source


def test_the_frame_colours_come_from_the_payload(source: str):
    """枠番の色はJRA公式の枠色（style.pyのWAKU_COLORS）を渡して使う。

    netkeibaの配色は取り込まない（構造だけをそろえる）。
    """
    assert "item.bg" in source and "item.fg" in source
    assert "#e2382f" not in source.split("<script>")[1]   # 色をJS側に埋め込まない


@needs_jsc
def test_the_javascript_parses(script: str, tmp_path: pathlib.Path):
    path = tmp_path / "odds.js"
    path.write_text("(function(){\n" + script + "\n});\n")
    result = subprocess.run([str(JSC), str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr or result.stdout


# --- 組み合わせの作り方（点数） -----------------------------------------------------------


@needs_jsc
@pytest.mark.parametrize(
    ("slots", "opts", "expected"),
    [
        # 馬連: 3×3 → 1-2 / 1-3 / 2-3 の3点（並べ方の違いは1つにまとめる）
        ([[1, 2, 3], [1, 2, 3]], {"ordered": False}, ["1-2", "1-3", "2-3"]),
        # 馬単: 同じ選び方でも着順が違えば別の組み合わせなので6点
        ([[1, 2, 3], [1, 2, 3]], {"ordered": True},
         ["1-2", "1-3", "2-1", "2-3", "3-1", "3-2"]),
        # 3連複: 3×3×3 → 1-2-3 の1点だけ
        ([[1, 2, 3], [1, 2, 3], [1, 2, 3]], {"ordered": False}, ["1-2-3"]),
        # 3連単: 同じ選び方で6点
        ([[1, 2, 3], [1, 2, 3], [1, 2, 3]], {"ordered": True},
         ["1-2-3", "1-3-2", "2-1-3", "2-3-1", "3-1-2", "3-2-1"]),
        # 軸1頭ながしの馬連（1頭 × 3頭）
        ([[1], [2, 3, 4]], {"ordered": False}, ["1-2", "1-3", "1-4"]),
        # 同じ馬が重なる組み合わせは捨てる
        ([[1], [1]], {"ordered": False}, []),
        # 枠連だけはゾロ目（同じ枠を両方に選ぶ）が作れる
        ([[1], [1]], {"ordered": False, "allowSame": True}, ["1-1"]),
        # 列が空なら0点
        ([[1, 2], []], {"ordered": False}, []),
    ],
)
def test_the_combinations_are_built_the_way_the_bet_type_works(
    slots, opts, expected, script, tmp_path
):
    out = run_js(
        f"print(JSON.stringify(combinations({json.dumps(slots)}, {json.dumps(opts)}).sort()));",
        script, tmp_path,
    )
    assert json.loads(out) == sorted(expected)


@needs_jsc
def test_a_full_field_gives_the_same_count_as_the_odds_page(script, tmp_path):
    """全通りを選んだときの点数が、JRAのオッズページの点数と合うこと（16頭立て）。"""
    field = list(range(1, 17))
    cases = {
        "umaren": ([field, field], {"ordered": False}, 120),
        "umatan": ([field, field], {"ordered": True}, 240),
        "sanrenpuku": ([field, field, field], {"ordered": False}, 560),
        "sanrentan": ([field, field, field], {"ordered": True}, 3360),
    }
    for name, (slots, opts, expected) in cases.items():
        out = run_js(
            f"print(combinations({json.dumps(slots)}, {json.dumps(opts)}).length);",
            script, tmp_path,
        )
        assert int(out) == expected, name


def test_the_tab_of_the_bet_type_just_fetched_is_opened(script: str):
    """取り込んだ直後は、その券種のタブへ移る（押した券種が見えないと分かりにくい）。

    同じ `focus` で何度も描き直されても、見ているタブを勝手に戻さないこと。
    """
    handler = script.split('event.data.type !== "streamlit:render"')[1]
    assert "payload.focus !== appliedFocus" in handler
    assert "appliedFocus = payload.focus" in handler


# --- 買い目の金額（1点あたり × 点数） -------------------------------------------------------


@needs_jsc
@pytest.mark.parametrize(
    ("groups", "points", "yen"),
    [
        # 1点あたり100円のフォーメーション3点 → 300円
        ([{"combos": ["1-2", "1-3", "1-4"], "amount": 100}], 3, 300),
        # 券種が違うまとまりも、点数と金額はそのまま足す
        ([{"combos": ["7"], "amount": 500}, {"combos": ["1-2", "1-3"], "amount": 100}], 3, 700),
        # 金額が空・0のまとまりは0円（点数には入る）
        ([{"combos": ["1-2"], "amount": None}, {"combos": ["3-4"], "amount": 0}], 2, 0),
        # マイナスや小数は切り捨てて0以上にそろえる
        ([{"combos": ["1-2"], "amount": -100}, {"combos": ["3-4"], "amount": 150.7}], 2, 150),
        ([], 0, 0),
    ],
)
def test_the_bet_slip_adds_up_by_the_point(groups, points, yen, script, tmp_path):
    out = run_js(
        f"print(JSON.stringify(slipTotals({json.dumps(groups)})));",
        script, tmp_path, "slipTotals",
    )
    assert json.loads(out) == {"points": points, "yen": yen}


@needs_jsc
def test_the_amount_is_written_with_commas(script, tmp_path):
    """合計は「12,300円」のように読める形で出す。"""
    out = run_js(
        "print([0, 300, 12300, 1234567].map(yenText).join('|'));",
        script, tmp_path, "yenText",
    )
    assert out == "0円|300円|12,300円|1,234,567円"



# --- 高さの伝え方 -------------------------------------------------------------------------


@needs_jsc
@pytest.mark.parametrize(
    ("next_height", "last", "expected"),
    [
        (600, None, True),      # 初回は必ず伝える
        (600, 600, False),      # 同じ高さは送り直さない（renderが返ってきてしまう）
        (601, 600, False),      # 1pxの揺れでは送らない
        (612, 600, True),       # 中身が増えて高くなったら伝える
        (560, 600, True),       # 低くなったときも伝える
    ],
)
def test_the_height_is_only_sent_when_it_really_changed(
    next_height, last, expected, script, tmp_path
):
    out = run_js(
        f"print(heightChanged({next_height}, {json.dumps(last)}));",
        script, tmp_path, "heightChanged",
    )
    assert out == ("true" if expected else "false")


# --- 押しやすさ・大きさ -------------------------------------------------------------------


def test_the_checkbox_is_big_enough_to_hit(source: str):
    """既定の13pxは小さくて押しにくかったので、まとめて大きくしている。"""
    assert _px(source, 'input[type="checkbox"]', "width") >= 17
    assert _px(source, 'input[type="checkbox"]', "height") >= 17


def test_the_columns_share_the_whole_width(source: str):
    """列は最大3つ（3連単）しか要らないので、余っている右の幅まで広げる。"""
    assert "flex: 1 1 0" in _rule(source, ".slot")
    assert _px(source, ".slot", "min-width") <= 220


def test_the_horse_name_is_not_cut_short_when_there_is_room(source: str):
    """列が広がったぶん、馬名は幅があるかぎり省略しない（狭いときだけ … で切る）。"""
    rule = _rule(source, ".slot label .nm")
    assert "max-width" not in rule
    assert "text-overflow: ellipsis" in rule


def test_the_rows_of_the_horse_list_are_taller(source: str):
    """行が詰まっていると押し間違える。1行30pxくらいにする。"""
    assert _px(source, ".slot label", "font-size") >= 13


def test_the_bet_slip_is_wide_enough_to_read(source: str):
    assert _px(source, ".slip", "max-width") >= 360


# --- 買い目の券種の見分け -----------------------------------------------------------------


def test_each_bet_type_is_marked_with_its_own_colour(script: str, source: str):
    """買い目に何券種か積んだとき、どれがどの券種かひと目で分かるようにする。

    色は**Pythonから渡す**（style.py の BET_TYPE_COLORS）。画面側には書かない。
    """
    body = take_function(script, "drawSlip")
    assert "(b && b.color)" in body                      # payloadの色を使う
    assert 'class: "bet"' in body                        # 券種名のバッジ
    assert "border-left-color:" in body                  # まとまりの左の帯
    assert "border-left: 4px solid" in _rule(source, ".g")


def test_the_bet_colours_are_not_written_into_the_component(script: str):
    """色の出どころはstyle.py1か所にする（枠色と同じ方針）。"""
    from keiba_analysis.shared.style import BET_TYPE_COLORS

    for color in BET_TYPE_COLORS.values():
        assert color not in script, color


def test_a_row_of_the_win_table_can_be_clicked_anywhere(script: str):
    """単勝・複勝の表は四角が小さいので、行のどこを押してもチェックが入る。"""
    body = take_function(script, "drawSingle")
    assert 'row.addEventListener("click"' in body
    assert "if (event.target === box) return;" in body   # 四角そのものは二重に反転させない


# --- 実際に動かして確かめる（押したらどうなるか） -------------------------------------------

# 馬連のタブを開いて、1頭目の列のチェックを何個か入れるところまで
OPEN_UMAREN = """
render(PAYLOAD);
NODES.tabs.children[2].click();                       // 馬連のタブ
var columns = NODES.panel.byClass("slot");
var boxes = columns[0].findAll(function (c) { return c.tagName === "input"; });
var boxes2 = columns[1].findAll(function (c) { return c.tagName === "input"; });
function count() { return NODES.panel.byClass("count")[0].text(); }
function checkedIn(column) {
  return column.findAll(function (c) { return c.tagName === "input" && c.checked; }).length;
}
"""


@needs_jsc
def test_clearing_a_column_unticks_the_boxes_on_screen(script, tmp_path):
    """**「クリア」で四角も外れること。**

    中身（選んだ番号）だけ消して画面の四角を触っていなかったため、
    「クリアを押しても消えない」ように見えていた（点数だけ0点になる）。
    """
    answer = run_component(script, OPEN_UMAREN + """
[1, 3, 5].forEach(function (i) { boxes[i].click(); });
var before = { ticked: checkedIn(columns[0]), count: count() };
press(columns[0], "クリア");
var answer = { before: before, ticked: checkedIn(columns[0]), count: count() };
""", tmp_path)
    assert answer["before"]["ticked"] == 3
    assert answer["ticked"] == 0            # 画面の四角が外れている
    assert answer["count"] == "0点"


@needs_jsc
def test_selecting_the_whole_column_ticks_every_box(script, tmp_path):
    """「全通り」も同じで、**画面の四角が全部付く**こと。"""
    answer = run_component(script, OPEN_UMAREN + """
press(columns[0], "全通り");
press(columns[1], "全通り");
var answer = { ticked: checkedIn(columns[0]), count: count() };
""", tmp_path)
    assert answer["ticked"] == 16
    assert answer["count"] == "120点"       # 16頭の馬連は全120点


@needs_jsc
def test_ticking_horses_updates_the_number_of_bets(script, tmp_path):
    """1頭目×3頭 → 3点。点数はそのまま画面に出る大事なところ。"""
    answer = run_component(script, OPEN_UMAREN + """
boxes[0].click();
[1, 2, 3].forEach(function (i) { boxes2[i].click(); });
var answer = { count: count() };
""", tmp_path)
    assert answer["count"] == "3点"


@needs_jsc
def test_adding_to_the_bet_slip_shows_it_on_the_right(script, tmp_path):
    """「買い目へ追加」で右に積まれ、点数と金額が出ること。"""
    answer = run_component(script, OPEN_UMAREN + """
boxes[0].click();
[1, 2].forEach(function (i) { boxes2[i].click(); });
press(NODES.panel, "買い目へ追加");
var answer = {
  bets: NODES.slip.byClass("bet").map(function (b) { return b.text(); }),
  points: NODES.slip.byClass("pts").map(function (p) { return p.text(); }),
  total: NODES.slip.byClass("slip-total")[0].text(),
  sent: SENT.length,
};
""", tmp_path)
    assert answer["bets"] == ["馬連"]
    assert answer["points"] == ["2点"]
    assert "2点" in answer["total"] and "200円" in answer["total"]
    assert answer["sent"] == 1              # 保存を1回だけ送る


@needs_jsc
def test_the_bet_slip_is_sorted_by_bet_type(script, tmp_path):
    """足した順に関係なく、買い目は**券種の並び**（単勝→複勝→…→3連単）にそろえる。"""
    answer = run_component(script, """
render(PAYLOAD);
// ワイド → 単勝 → 馬連 の順に足す
NODES.tabs.children[3].click();
var w = NODES.panel.byClass("slot");
w[0].findAll(function (c) { return c.tagName === "input"; })[0].click();
w[1].findAll(function (c) { return c.tagName === "input"; })[1].click();
press(NODES.panel, "買い目へ追加");

NODES.tabs.children[0].click();
NODES.panel.byClass("tick")[4].children[0].click();
press(NODES.panel, "選んだ馬を単勝へ");

NODES.tabs.children[2].click();
var u = NODES.panel.byClass("slot");
u[0].findAll(function (c) { return c.tagName === "input"; })[2].click();
u[1].findAll(function (c) { return c.tagName === "input"; })[3].click();
press(NODES.panel, "買い目へ追加");

var answer = {
  shown: NODES.slip.byClass("bet").map(function (b) { return b.text(); }),
  saved: SENT[SENT.length - 1].groups.map(function (g) { return g.bet; }),
};
""", tmp_path)
    assert answer["shown"] == ["単勝", "馬連", "ワイド"]
    # 保存する順も同じにそろえる（開き直したときに並びが変わらないように）
    assert answer["saved"] == ["tansho", "umaren", "wide"]


@needs_jsc
def test_two_of_the_same_bet_type_keep_the_order_they_were_added(script, tmp_path):
    """同じ券種の中は、足した順のまま隣り合わせる。"""
    answer = run_component(script, """
render(PAYLOAD);
NODES.panel.byClass("tick")[0].children[0].click();
press(NODES.panel, "選んだ馬を単勝へ");
press(NODES.panel, "選択をクリア");
NODES.panel.byClass("tick")[7].children[0].click();
press(NODES.panel, "選んだ馬を単勝へ");
var answer = {
  combos: NODES.slip.byClass("g").map(function (g) {
    return g.byClass("num").map(function (n) { return n.text(); }).join("");
  }),
};
""", tmp_path)
    assert answer["combos"] == ["1", "8"]


@needs_jsc
@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ([], []),
        (["wide"], ["wide"]),
        (["wide", "tansho", "umaren"], ["tansho", "umaren", "wide"]),
        # 知らない券種は捨てずに、いちばん後ろへ回す
        (["wide", "nonsense", "tansho"], ["tansho", "wide", "nonsense"]),
    ],
)
def test_the_sort_puts_the_bet_types_in_order(groups, expected, script, tmp_path):
    order = {"tansho": 0, "fukusho": 1, "wakuren": 2, "umaren": 3, "wide": 4}
    rows = json.dumps([{"bet": key} for key in groups])
    out = run_js(
        f"print(JSON.stringify(sortSlip({rows}, {json.dumps(order)})"
        ".map(function (g) { return g.bet; })));",
        script, tmp_path, "sortSlip",
    )
    assert json.loads(out) == expected


@needs_jsc
def test_moving_to_another_bet_type_clears_the_selection(script, tmp_path):
    """券種を移ったら、選びかけの馬は白紙に戻す（前の券種の選択を持ち越さない）。"""
    answer = run_component(script, """
render(PAYLOAD);
NODES.tabs.children[2].click();                       // 馬連
var columns = NODES.panel.byClass("slot");
[1, 3, 5].forEach(function (i) {
  columns[0].findAll(function (c) { return c.tagName === "input"; })[i].click();
});
var before = NODES.panel.byClass("count")[0].text();
NODES.tabs.children[3].click();                       // ワイドへ移る
var wide = {
  ticked: NODES.panel.findAll(function (c) { return c.tagName === "input" && c.checked; }).length,
  count: NODES.panel.byClass("count")[0].text(),
};
NODES.tabs.children[2].click();                       // 馬連へ戻る
var answer = {
  before: before, wide: wide,
  back: NODES.panel.findAll(function (c) { return c.tagName === "input" && c.checked; }).length,
  backCount: NODES.panel.byClass("count")[0].text(),
};
""", tmp_path)
    assert answer["before"] == "0点"          # 1頭目だけでは組み合わせにならない
    assert answer["wide"]["ticked"] == 0      # 移った先に選択が残っていない
    assert answer["wide"]["count"] == "0点"
    assert answer["back"] == 0                # 戻っても前の選択は消えている
    assert answer["backCount"] == "0点"


@needs_jsc
def test_the_bet_slip_survives_a_tab_change(script, tmp_path):
    """白紙に戻すのは**選びかけの馬だけ**。積んだ買い目は券種をまたいで残す。"""
    answer = run_component(script, """
render(PAYLOAD);
NODES.panel.byClass("tick")[2].children[0].click();
press(NODES.panel, "選んだ馬を単勝へ");
NODES.tabs.children[2].click();                       // 馬連へ移る
var answer = {
  bets: NODES.slip.byClass("bet").map(function (b) { return b.text(); }),
  ticked: NODES.panel.findAll(function (c) { return c.tagName === "input" && c.checked; }).length,
};
""", tmp_path)
    assert answer["bets"] == ["単勝"]          # 買い目は残る
    assert answer["ticked"] == 0               # 選びかけは消える


@needs_jsc
def test_the_add_button_sits_at_the_far_end_of_the_row(script, tmp_path):
    """点数の行は 点数 → 並べ替え → 「買い目へ追加」の順（追加は右端に離す）。"""
    answer = run_component(script, """
render(PAYLOAD);
NODES.tabs.children[2].click();
var row = NODES.panel.byClass("result-head")[0];
var answer = {
  order: row.children.map(function (c) { return c.attrs["class"] || c.tagName; }),
  labels: row.findAll(function (c) { return c.tagName === "button"; })
    .map(function (b) { return b.text(); }),
};
""", tmp_path)
    assert answer["order"] == ["count", "sorts", "mini go panel-add"]
    assert answer["labels"] == ["オッズ順", "組み合わせ順", "買い目へ追加"]


def test_the_buttons_are_big_enough_to_press(source: str):
    """「買い目へ追加」と並べ替えは押す回数が多いので、少し大きくする。"""
    assert _px(source, ".mini", "font-size") >= 12
    assert _px(source, ".result-head .mini", "font-size") >= 13
    assert "margin-left: auto" in _rule(source, ".result-head .mini.go")


# --- 買い方ごとの点数（ながし・ボックス） ---------------------------------------------------

PARTNERS = [1, 2, 3, 4, 5]


@needs_jsc
@pytest.mark.parametrize(
    ("bet", "axes", "legs", "opts", "expected"),
    [
        # 馬連 軸1頭ながし → 相手の数だけ
        ("馬連", [9], 2, {}, 5),
        # 馬単 軸1頭ながし（1着）→ 5点。マルチは1着と2着の両方で10点
        ("馬単 1着", [9], 2, {"ordered": True, "positions": [0]}, 5),
        ("馬単 マルチ", [9], 2, {"ordered": True, "positions": [0], "multi": True}, 10),
        # 3連複 軸1頭 → 相手から2頭（5C2）。軸2頭 → 相手から1頭
        ("3連複 軸1", [9], 3, {}, 10),
        ("3連複 軸2", [9, 7], 3, {}, 5),
        # 3連単 軸1頭（1着）→ 相手から2頭の並べ方（5P2）。マルチは軸の着順3通りで60点
        ("3連単 軸1 1着", [9], 3, {"ordered": True, "positions": [0]}, 20),
        ("3連単 軸1 マルチ", [9], 3, {"ordered": True, "positions": [0], "multi": True}, 60),
        # 3連単 軸2頭（1・2着）→ 5点。マルチは軸2頭の置き方6通りで30点
        ("3連単 軸2 1・2着", [9, 7], 3, {"ordered": True, "positions": [0, 1]}, 5),
        ("3連単 軸2 マルチ", [9, 7], 3, {"ordered": True, "positions": [0, 1], "multi": True}, 30),
    ],
)
def test_the_wheel_makes_the_same_number_of_bets_as_the_bookmaker(
    bet, axes, legs, opts, expected, script, tmp_path
):
    """ながしの点数（相手5頭）。JRAの買い方の点数と合うこと。"""
    out = run_js(
        f"print(nagashiCombos({json.dumps(axes)}, {json.dumps(PARTNERS)}, {legs},"
        f" {json.dumps(opts)}).length);",
        script, tmp_path, "combinations", "nagashiCombos", "orderedPlaces",
    )
    assert int(out) == expected, bet


@needs_jsc
@pytest.mark.parametrize(
    ("bet", "axes", "partners", "legs", "opts"),
    [
        ("軸だけ", [9], [], 2, {}),
        ("相手だけ", [], [1, 2], 2, {}),
        ("何も無い", [], [], 2, {}),
        # 3連単で軸3頭は「ながし」にならない（相手が入る場所が無い）
        ("軸が多すぎる", [9, 7, 8], [1, 2], 3, {"ordered": True, "positions": [0, 1, 2]}),
    ],
)
def test_a_wheel_without_both_sides_is_no_bet(bet, axes, partners, legs, opts, script, tmp_path):
    out = run_js(
        f"print(nagashiCombos({json.dumps(axes)}, {json.dumps(partners)}, {legs},"
        f" {json.dumps(opts)}).length);",
        script, tmp_path, "combinations", "nagashiCombos", "orderedPlaces",
    )
    assert int(out) == 0, bet


@needs_jsc
@pytest.mark.parametrize(
    ("bet", "numbers", "legs", "opts", "expected"),
    [
        ("馬連 4頭", [1, 2, 3, 4], 2, {}, 6),
        ("馬単 4頭", [1, 2, 3, 4], 2, {"ordered": True}, 12),
        ("3連複 5頭", [1, 2, 3, 4, 5], 3, {}, 10),
        ("3連単 5頭", [1, 2, 3, 4, 5], 3, {"ordered": True}, 60),
        ("1頭では組めない", [1], 2, {}, 0),
        ("選んでいない", [], 2, {}, 0),
    ],
)
def test_a_box_covers_every_combination_of_the_chosen_horses(
    bet, numbers, legs, opts, expected, script, tmp_path
):
    out = run_js(
        f"print(boxCombos({json.dumps(numbers)}, {legs}, {json.dumps(opts)}).length);",
        script, tmp_path, "combinations", "boxCombos",
    )
    assert int(out) == expected, bet


@needs_jsc
def test_the_wheel_keeps_the_axis_where_it_was_put(script, tmp_path):
    """軸の着順どおりに入ること（2着ながしなら、どの組み合わせも2着が軸）。"""
    out = run_js(
        "print(JSON.stringify(nagashiCombos([9], [1, 2], 2,"
        ' {ordered: true, positions: [1]})));',
        script, tmp_path, "combinations", "nagashiCombos", "orderedPlaces",
    )
    assert json.loads(out) == ["1-9", "2-9"]


@needs_jsc
def test_a_horse_chosen_on_both_sides_counts_as_the_axis(script, tmp_path):
    """同じ馬を軸と相手の両方に選んでも、二重には数えない（軸として扱う）。"""
    out = run_js(
        "print(nagashiCombos([3], [1, 2, 3, 4], 2, {}).length);",
        script, tmp_path, "combinations", "nagashiCombos", "orderedPlaces",
    )
    assert int(out) == 3        # 相手は 1・2・4 の3頭ぶん


# --- 買い方の切り替え（実際に押して確かめる） -----------------------------------------------

# 馬連のタブを開く（買い方のボタンはこの下に出る）
OPEN = """
render(PAYLOAD);
NODES.tabs.children[2].click();                       // 馬連
function count() { return NODES.panel.byClass("count")[0].text(); }
function columns() { return NODES.panel.byClass("slot"); }
function heads() {
  return columns().map(function (c) { return c.byClass("acts")[0] ? c.children[0].children[0].text() : ""; });
}
function tick(column, i) {
  column.findAll(function (c) { return c.tagName === "input"; })[i].click();
}
"""


@needs_jsc
def test_formation_is_the_default_way_to_choose(script, tmp_path):
    """既定は今までどおりフォーメーション（列が券種の頭数だけ出る）。"""
    answer = run_component(script, OPEN + """
var answer = {
  modes: NODES.panel.byClass("modes")[0].findAll(function (c) { return c.tagName === "button"; })
    .map(function (b) { return b.text(); }),
  pressed: NODES.panel.byClass("modes")[0].findAll(function (c) {
    return c.attrs["aria-pressed"] === "true";
  }).map(function (b) { return b.text(); }),
  columns: columns().length,
};
""", tmp_path)
    assert answer["modes"] == ["通常／フォーメーション", "ながし", "ボックス"]
    assert answer["pressed"] == ["通常／フォーメーション"]
    assert answer["columns"] == 2            # 馬連は1頭目・2頭目


@needs_jsc
def test_a_box_needs_only_one_column(script, tmp_path):
    """ボックスは列が1つ。4頭選ぶと馬連で6点。"""
    answer = run_component(script, OPEN + """
press(NODES.panel, "ボックス");
[0, 1, 2, 3].forEach(function (i) { tick(columns()[0], i); });
var answer = { columns: columns().length, count: count() };
""", tmp_path)
    assert answer["columns"] == 1
    assert answer["count"] == "6点"


@needs_jsc
def test_a_wheel_has_an_axis_and_the_rest(script, tmp_path):
    """ながしは軸と相手の2列。軸1頭＋相手3頭で3点。"""
    answer = run_component(script, OPEN + """
press(NODES.panel, "ながし");
tick(columns()[0], 8);                                 // 軸: 9番
[0, 1, 2].forEach(function (i) { tick(columns()[1], i); });
var answer = {
  columns: columns().length,
  heads: columns().map(function (c) { return c.children[0].children[0].text(); }),
  count: count(),
};
""", tmp_path)
    assert answer["heads"] == ["軸", "相手"]
    assert answer["count"] == "3点"


@needs_jsc
def test_the_axis_makes_room_for_the_newest_horse(script, tmp_path):
    """軸は上限まで。1頭のときに2頭目を押したら、古いほうが外れる。"""
    answer = run_component(script, OPEN + """
press(NODES.panel, "ながし");
tick(columns()[0], 8);
tick(columns()[0], 2);                                 // 2頭目を押す
var boxes = columns()[0].findAll(function (c) { return c.tagName === "input"; });
var answer = { ticked: boxes.filter(function (b) { return b.checked; }).length,
               third: boxes[2].checked, ninth: boxes[8].checked };
""", tmp_path)
    assert answer["ticked"] == 1
    assert answer["third"] is True and answer["ninth"] is False


@needs_jsc
def test_multi_doubles_an_exacta_wheel(script, tmp_path):
    """馬単のながしにマルチを入れると、軸の着順が入れ替わって倍になる。"""
    answer = run_component(script, """
render(PAYLOAD);
NODES.tabs.children[4].click();                        // 馬単
press(NODES.panel, "ながし");
function count() { return NODES.panel.byClass("count")[0].text(); }
function columns() { return NODES.panel.byClass("slot"); }
columns()[0].findAll(function (c) { return c.tagName === "input"; })[8].click();
[0, 1, 2].forEach(function (i) {
  columns()[1].findAll(function (c) { return c.tagName === "input"; })[i].click();
});
var before = count();
var multi = NODES.panel.byClass("multi")[0].children[0];
multi.click();
var answer = { before: before, after: count(),
               places: NODES.panel.byClass("opt")[0].findAll(function (c) {
                 return c.tagName === "button"; }).map(function (b) { return b.text(); }) };
""", tmp_path)
    assert answer["before"] == "3点"
    assert answer["after"] == "6点"
    assert answer["places"] == ["1着", "2着"]      # 馬単は軸の着順が2つ


@needs_jsc
def test_the_way_of_buying_is_written_on_the_bet_slip(script, tmp_path):
    """買い目には「ボックス」「ながし」と出る（あとで見て分かるように）。"""
    answer = run_component(script, OPEN + """
press(NODES.panel, "ボックス");
[0, 1, 2].forEach(function (i) { tick(columns()[0], i); });
press(NODES.panel, "買い目へ追加");
var answer = {
  kinds: NODES.slip.byClass("kind").map(function (k) { return k.text(); }),
  saved: SENT[SENT.length - 1].groups.map(function (g) { return g.kind; }),
};
""", tmp_path)
    assert answer["kinds"] == ["ボックス"]
    assert answer["saved"] == ["ボックス"]          # DBにも残す


@needs_jsc
def test_moving_tab_clears_every_way_of_buying(script, tmp_path):
    """券種を移ったら、3つの買い方の選択をすべて白紙に戻す。"""
    answer = run_component(script, OPEN + """
press(NODES.panel, "ボックス");
[0, 1, 2].forEach(function (i) { tick(columns()[0], i); });
NODES.tabs.children[3].click();                        // ワイドへ
NODES.tabs.children[2].click();                        // 馬連へ戻る
var answer = {
  mode: NODES.panel.byClass("modes")[0].findAll(function (c) {
    return c.attrs["aria-pressed"] === "true"; })[0].text(),
  ticked: NODES.panel.findAll(function (c) { return c.tagName === "input" && c.checked; }).length,
  count: count(),
};
""", tmp_path)
    assert answer["mode"] == "ボックス"       # 買い方そのものは覚えている
    assert answer["ticked"] == 0              # 選んだ馬は白紙
    assert answer["count"] == "0点"


@needs_jsc
def test_a_trifecta_can_be_wheeled_from_two_axes(script, tmp_path):
    """3連単は軸2頭も選べる。1・2着軸＋相手5頭で5点、マルチで30点。"""
    answer = run_component(script, """
render(PAYLOAD);
NODES.tabs.children[6].click();                        // 3連単
press(NODES.panel, "ながし");
function count() { return NODES.panel.byClass("count")[0].text(); }
function columns() { return NODES.panel.byClass("slot"); }
function opt(i) {
  return NODES.panel.byClass("opt")[i].findAll(function (c) { return c.tagName === "button"; });
}
var units = opt(0).map(function (b) { return b.text(); });
press(NODES.panel.byClass("opt")[0], "2頭");           // 軸2頭に切り替える
[8, 6].forEach(function (i) {
  columns()[0].findAll(function (c) { return c.tagName === "input"; })[i].click();
});
[0, 1, 2, 3, 4].forEach(function (i) {
  columns()[1].findAll(function (c) { return c.tagName === "input"; })[i].click();
});
var places = opt(1).map(function (b) { return b.text(); });
var before = count();
NODES.panel.byClass("multi")[0].children[0].click();
var answer = { units: units, places: places, before: before, after: count() };
""", tmp_path)
    assert answer["units"] == ["1頭", "2頭"]
    assert answer["places"] == ["1・2着", "1・3着", "2・3着"]
    assert answer["before"] == "5点"
    assert answer["after"] == "30点"


# --- 組み合わせを1点ずつ選ぶ ---------------------------------------------------------------

# 馬連で 1頭目=1番 × 2頭目=2,3,4番 → 3点の組み合わせが出た状態
THREE_COMBOS = OPEN + """
function rows() { return NODES.panel.byClass("combos")[0].findAll(function (c) {
  return c.tagName === "tr" && c.byClass("tick").length && c.children[0].children.length; }); }
function ticks() { return NODES.panel.byClass("combos")[0].findAll(function (c) {
  return c.tagName === "input"; }); }
function picked() { return NODES.panel.byClass("pick-count")[0].text(); }
function addLabel() {
  return NODES.panel.find(function (c) {
    return c.tagName === "button" && c.text().indexOf("買い目へ追加") === 0; }).text();
}
tick(columns()[0], 0);
[1, 2, 3].forEach(function (i) { tick(columns()[1], i); });
"""


@needs_jsc
def test_every_combination_starts_out_chosen(script, tmp_path):
    """出たばかりの組み合わせは全部選ばれている（そのまま押せば全部入る）。"""
    answer = run_component(script, THREE_COMBOS + """
var answer = { count: count(), picked: picked(), label: addLabel(),
               ticked: ticks().filter(function (b) { return b.checked; }).length };
""", tmp_path)
    assert answer["count"] == "3点"
    assert answer["picked"] == "選択 3/3点"
    assert answer["label"] == "買い目へ追加（3点）"
    assert answer["ticked"] == 3


@needs_jsc
def test_only_the_chosen_combinations_go_to_the_slip(script, tmp_path):
    """1点外して追加すると、買い目に入るのは残りだけ。"""
    answer = run_component(script, THREE_COMBOS + """
ticks()[1].click();                                    // 2番目の組み合わせを外す
var mid = { picked: picked(), label: addLabel() };
press(NODES.panel, "買い目へ追加");
var answer = { mid: mid,
  combos: SENT[SENT.length - 1].groups[0].combos,
  points: NODES.slip.byClass("pts")[0].text() };
""", tmp_path)
    assert answer["mid"]["picked"] == "選択 2/3点"
    assert answer["mid"]["label"] == "買い目へ追加（2点）"
    assert len(answer["combos"]) == 2
    assert answer["points"] == "2点"


@needs_jsc
def test_clearing_every_combination_stops_the_add(script, tmp_path):
    """全解除にすると押せなくなり、全選択で戻る。"""
    answer = run_component(script, THREE_COMBOS + """
press(NODES.panel.byClass("pick-line")[0], "全解除");
var off = { picked: picked(), ticked: ticks().filter(function (b) { return b.checked; }).length,
            disabled: !!NODES.panel.find(function (c) {
              return c.tagName === "button" && c.text().indexOf("買い目へ追加") === 0;
            }).attrs["disabled"] };
press(NODES.panel.byClass("pick-line")[0], "全選択");
var answer = { off: off, picked: picked(),
               ticked: ticks().filter(function (b) { return b.checked; }).length };
""", tmp_path)
    assert answer["off"] == {"picked": "選択 0/3点", "ticked": 0, "disabled": True}
    assert answer["picked"] == "選択 3/3点"
    assert answer["ticked"] == 3


@needs_jsc
def test_the_choice_survives_a_change_of_order(script, tmp_path):
    """並べ替えても、外したものは外れたまま。"""
    answer = run_component(script, THREE_COMBOS + """
ticks()[0].click();
press(NODES.panel, "組み合わせ順");
var answer = { picked: picked(),
               ticked: ticks().filter(function (b) { return b.checked; }).length };
""", tmp_path)
    assert answer["picked"] == "選択 2/3点"
    assert answer["ticked"] == 2


@needs_jsc
def test_choosing_other_horses_brings_every_combination_back(script, tmp_path):
    """馬を選び直して組み合わせが変わったら、全部選ばれた状態に戻す。"""
    answer = run_component(script, THREE_COMBOS + """
ticks()[0].click();
var before = picked();
tick(columns()[1], 4);                                 // 相手をもう1頭足す
var answer = { before: before, after: picked(), count: count() };
""", tmp_path)
    assert answer["before"] == "選択 2/3点"
    assert answer["count"] == "4点"
    assert answer["after"] == "選択 4/4点"


@needs_jsc
def test_a_box_can_also_be_chosen_one_by_one(script, tmp_path):
    """ボックスでも同じように1点ずつ選べる（表は3つの買い方で共通）。"""
    answer = run_component(script, OPEN + """
press(NODES.panel, "ボックス");
[0, 1, 2].forEach(function (i) { tick(columns()[0], i); });
var ticks = NODES.panel.byClass("combos")[0].findAll(function (c) { return c.tagName === "input"; });
ticks[0].click();
var picked = NODES.panel.byClass("pick-count")[0].text();     // 追加する前の選択
press(NODES.panel, "買い目へ追加");
var answer = { picked: picked,
               combos: SENT[SENT.length - 1].groups[0].combos.length,
               kind: NODES.slip.byClass("kind")[0].text() };
""", tmp_path)
    assert answer["picked"] == "選択 2/3点"
    assert answer["combos"] == 2
    assert answer["kind"] == "ボックス"


@needs_jsc
def test_adding_clears_the_choice_so_a_second_press_does_nothing(script, tmp_path):
    """追加したら選択を外す。**間違えて二度押しても同じ買い目が積まれない**ようにする。"""
    answer = run_component(script, THREE_COMBOS + """
press(NODES.panel, "買い目へ追加");
var add = NODES.panel.find(function (c) {
  return c.tagName === "button" && c.text().indexOf("買い目へ追加") === 0; });
var after = { picked: picked(), label: add.text(), disabled: !!add.attrs["disabled"],
              ticked: ticks().filter(function (b) { return b.checked; }).length,
              sent: SENT.length, groups: NODES.slip.byClass("g").length };
add.click();                                           // もう一度押してみる
var answer = { after: after, sent: SENT.length, groups: NODES.slip.byClass("g").length };
""", tmp_path)
    assert answer["after"]["picked"] == "選択 0/3点"
    assert answer["after"]["label"] == "買い目へ追加"     # 点数が消えて押せない
    assert answer["after"]["disabled"] is True
    assert answer["after"]["ticked"] == 0
    assert answer["sent"] == answer["after"]["sent"] == 1     # 保存は1回だけ
    assert answer["groups"] == answer["after"]["groups"] == 1  # 買い目も1つのまま


@needs_jsc
def test_choosing_another_horse_after_adding_brings_the_list_back(script, tmp_path):
    """追加したあとでも、馬を足せばまた全部選ばれた状態から選び直せる。"""
    answer = run_component(script, THREE_COMBOS + """
press(NODES.panel, "買い目へ追加");
tick(columns()[1], 4);                                 // 相手をもう1頭足す
var answer = { picked: picked(), count: count() };
""", tmp_path)
    assert answer["count"] == "4点"
    assert answer["picked"] == "選択 4/4点"


# --- 想定払戻金 ---------------------------------------------------------------------------


@needs_jsc
@pytest.mark.parametrize(
    ("odds", "amount", "expected"),
    [
        (15.6, 100, 1560),
        (32.0, 300, 9600),
        (7.7, 150, 1150),        # 1,155円 → 10円未満は切り捨て
        (15.6, 0, 0),            # 金額を入れていない
        (None, 100, 0),          # オッズが分からない（未取得・票数なし）
    ],
)
def test_the_payout_follows_the_odds_and_the_money(odds, amount, expected, script, tmp_path):
    """払戻は オッズ×金額 の10円未満切り捨て（JRAの払戻と同じ数え方）。"""
    out = run_js(
        f"print(payoutYen({json.dumps(odds)}, {amount}));", script, tmp_path, "payoutYen",
    )
    assert int(out) == expected


@needs_jsc
@pytest.mark.parametrize(
    ("name", "rows", "amount", "expected"),
    [
        ("1点なら幅にならない", [[15.6, None]], 100, {"min": 1560, "max": 1560}),
        ("複数点は幅で出す", [[15.6, None], [66.0, None]], 100, {"min": 1560, "max": 6600}),
        ("複勝・ワイドは下と上の両方を使う", [[3.0, 4.0]], 100, {"min": 300, "max": 400}),
        ("オッズが無い行は外す", [[None, None], [15.6, None]], 100, {"min": 1560, "max": 1560}),
        ("1つも分からなければ出さない", [[None, None]], 100, None),
        ("組み合わせが無ければ出さない", [], 100, None),
    ],
)
def test_the_group_shows_the_payout_as_a_range(name, rows, amount, expected, script, tmp_path):
    """当たるのは1点だけなので、まとまりでは足さずに幅で見せる。"""
    out = run_js(
        f"print(JSON.stringify(payoutRange({json.dumps(rows)}, {amount})));",
        script, tmp_path, "payoutYen", "payoutRange",
    )
    assert json.loads(out) == expected, name


@needs_jsc
def test_the_slip_shows_what_comes_back_if_it_hits(script, tmp_path):
    """まとまりごとに払戻の目安を出す。金額を変えたら出し直す。"""
    answer = run_component(script, THREE_COMBOS + """
press(NODES.panel, "買い目へ追加");
function payout() { return NODES.slip.byClass("g-payout")[0].text(); }
function odds() { return NODES.slip.byClass("g-combos")[0].byClass("o")
  .map(function (o) { return Number(o.text()); }); }
var before = { payout: payout(), odds: odds() };
var box = NODES.slip.byClass("g-money")[0].findAll(function (c) { return c.tagName === "input"; })[0];
box.value = "300";
box.fire("change");
var answer = { before: before, after: payout(), sub: NODES.slip.byClass("sub")[0].text() };
""", tmp_path)
    low, high = min(answer["before"]["odds"]), max(answer["before"]["odds"])
    assert answer["before"]["payout"] == f"払戻の目安 {int(low * 100) // 10 * 10:,}〜{int(high * 100) // 10 * 10:,}円"
    assert answer["after"] == f"払戻の目安 {int(low * 300) // 10 * 10:,}〜{int(high * 300) // 10 * 10:,}円"
    assert answer["sub"] == "900円"          # 3点 × 300円


@needs_jsc
def test_a_single_point_shows_one_payout(script, tmp_path):
    """1点のまとまりは幅ではなく1つの数字。"""
    answer = run_component(script, """
render(PAYLOAD);
NODES.panel.byClass("tick")[2].children[0].click();
press(NODES.panel, "選んだ馬を単勝へ");
var answer = { payout: NODES.slip.byClass("g-payout")[0].text(),
               odds: NODES.slip.byClass("o")[0].text() };
""", tmp_path)
    assert "〜" not in answer["payout"]
    assert answer["payout"] == f"払戻の目安 {int(float(answer['odds']) * 100) // 10 * 10:,}円"


@needs_jsc
def test_a_group_can_be_split_into_single_points(script, tmp_path):
    """「ばらす」で1点ずつに分かれる。点数と金額の合計は変わらない。"""
    answer = run_component(script, THREE_COMBOS + """
press(NODES.panel, "買い目へ追加");
var before = { groups: NODES.slip.byClass("g").length, total: NODES.slip.byClass("slip-total")[0].text() };
press(NODES.slip, "ばらす");
var answer = {
  before: before,
  groups: NODES.slip.byClass("g").length,
  points: NODES.slip.byClass("pts").map(function (p) { return p.text(); }),
  kinds: NODES.slip.byClass("kind").map(function (k) { return k.text(); }),
  total: NODES.slip.byClass("slip-total")[0].text(),
  saved: SENT[SENT.length - 1].groups.map(function (g) { return g.combos.length + ":" + g.kind; }),
  splits: NODES.slip.findAll(function (c) {
    return c.tagName === "button" && c.text() === "ばらす"; }).length,
};
""", tmp_path)
    assert answer["before"]["groups"] == 1
    assert answer["groups"] == 3
    assert answer["points"] == ["1点", "1点", "1点"]
    assert answer["kinds"] == ["通常", "通常", "通常"]
    assert answer["total"] == answer["before"]["total"]        # 3点 300円のまま
    assert answer["saved"] == ["1:通常", "1:通常", "1:通常"]
    assert answer["splits"] == 0        # 1点になったので「ばらす」は消える


@needs_jsc
def test_after_splitting_each_point_has_its_own_money(script, tmp_path):
    """ばらしたあとは、1つだけ金額を変えても他は変わらない。"""
    answer = run_component(script, THREE_COMBOS + """
press(NODES.panel, "買い目へ追加");
press(NODES.slip, "ばらす");
var money = NODES.slip.byClass("g-money");
var box = money[0].findAll(function (c) { return c.tagName === "input"; })[0];
box.value = "500";
box.fire("change");
var answer = {
  subs: NODES.slip.byClass("sub").map(function (s) { return s.text(); }),
  total: NODES.slip.byClass("slip-total")[0].text(),
};
""", tmp_path)
    assert answer["subs"] == ["500円", "100円", "100円"]
    assert "700円" in answer["total"] and "3点" in answer["total"]


@needs_jsc
def test_saving_the_money_does_not_rebuild_the_slip(script, tmp_path):
    """金額を直したあとに返ってくる**自分の保存**では、買い目を作り直さない。

    作り直すと、スクロールの位置が先頭へ戻って「勝手に上へ飛ぶ」ように見える。
    """
    answer = run_component(script, THREE_COMBOS + """
press(NODES.panel, "買い目へ追加");
var input = NODES.slip.byClass("g-money")[0].findAll(function (c) { return c.tagName === "input"; })[0];
input.MARK = "同じ要素のまま";
input.value = "500";
input.fire("change");
var saved = SENT[SENT.length - 1];
// Streamlitが保存を受けて、同じ中身をそのまま返してくる（買い目以外は変わらない）
var echo = JSON.parse(JSON.stringify(PAYLOAD));
echo.version = "v2";
echo.slip = saved.groups;
echo.slipSavedAt = "2026-09-27 00:41";
render(echo);
var again = NODES.slip.byClass("g-money")[0].findAll(function (c) { return c.tagName === "input"; })[0];
var answer = { same: again.MARK === "同じ要素のまま", value: again.value,
               sub: NODES.slip.byClass("sub")[0].text() };
""", tmp_path)
    assert answer["same"] is True          # 作り直していない
    assert answer["value"] == "500"
    assert answer["sub"] == "1,500円"       # 3点 × 500円


@needs_jsc
def test_new_odds_still_redraw_everything(script, tmp_path):
    """オッズを取り込み直したとき（買い目以外が変わったとき）は、これまでどおり描き直す。"""
    answer = run_component(script, THREE_COMBOS + """
var mark = NODES.panel.byClass("slot")[0];
mark.MARK = "古い列";
var next = JSON.parse(JSON.stringify(PAYLOAD));
next.version = "v2";
next.drawVersion = "d2";                    // 取り込み直してオッズが変わった
next.tabs[2].chip = "12:41現在";
render(next);
var answer = { rebuilt: NODES.panel.byClass("slot")[0].MARK === undefined };
""", tmp_path)
    assert answer["rebuilt"] is True


# --- 買い目の券種だけまとめて更新 ------------------------------------------------------------


@needs_jsc
def test_the_slip_can_refresh_only_the_bet_types_it_holds(script, tmp_path):
    """買い目に入れた券種だけを、1回でまとめて取り込み直せる。"""
    answer = run_component(script, OPEN + """
// 馬連を1つ、単勝を1つ買い目に入れる
tick(columns()[0], 0);
[1, 2].forEach(function (i) { tick(columns()[1], i); });
press(NODES.panel, "買い目へ追加");
NODES.tabs.children[0].click();                        // 単勝・複勝へ
NODES.panel.byClass("tick")[3].children[0].click();
press(NODES.panel, "選んだ馬を単勝へ");

var button = NODES.slip.find(function (c) {
  return c.tagName === "button" && c.text().indexOf("買い目の券種を更新") === 0; });
var label = button.text();
button.click();
var sent = SENT[SENT.length - 1];
var answer = { label: label, kind: sent.kind, bets: sent.bets,
               after: button.text(), disabled: !!button.attrs["disabled"] };
""", tmp_path)
    # 単勝と馬連の2券種＝2リクエスト（3秒間隔）
    assert answer["label"] == "買い目の券種を更新（2券種・約6秒）"
    assert answer["kind"] == "fetch"
    assert answer["bets"] == ["tansho", "umaren"]      # タブの並び順
    assert answer["after"] == "取り込み中…" and answer["disabled"] is True


@needs_jsc
def test_win_and_place_count_as_one_page(script, tmp_path):
    """単勝と複勝は同じページなので、両方あっても1券種ぶん。"""
    answer = run_component(script, """
render(PAYLOAD);
NODES.panel.byClass("tick")[0].children[0].click();
press(NODES.panel, "選んだ馬を単勝へ");
press(NODES.panel, "選んだ馬を複勝へ");
var button = NODES.slip.find(function (c) {
  return c.tagName === "button" && c.text().indexOf("買い目の券種を更新") === 0; });
button.click();
var answer = { bets: SENT[SENT.length - 1].bets,
               groups: NODES.slip.byClass("bet").map(function (b) { return b.text(); }) };
""", tmp_path)
    assert answer["groups"] == ["単勝", "複勝"]
    assert answer["bets"] == ["tansho"]


@needs_jsc
def test_there_is_nothing_to_refresh_without_a_slip(script, tmp_path):
    """買い目が空のときは、そのボタンを出さない。"""
    answer = run_component(script, OPEN + """
var answer = { buttons: NODES.slip.findAll(function (c) {
  return c.tagName === "button" && c.text().indexOf("買い目の券種を更新") === 0; }).length };
""", tmp_path)
    assert answer["buttons"] == 0


# --- 馬名 → 馬柱のその馬 ---------------------------------------------------------

JUMP = """
var payload = JSON.parse(JSON.stringify(PAYLOAD));
payload.raceId = "202606040611";
payload.horses.forEach(function (h) { h.horse_id = "H" + h.number; });
render(payload);
var rows = NODES.panel.findAll(function (c) { return c.tagName === "tr" && c.byClass("horse-jump").length; });
var row3 = rows[2];
var name3 = row3.byClass("horse-jump")[0];
var box3 = row3.findAll(function (c) { return c.tagName === "input"; })[0];
"""


@needs_jsc
def test_the_horse_name_jumps_to_the_grid_row(script, tmp_path):
    """単勝・複勝の表で馬名を押すと、馬柱のその馬の行へ飛ぶ（チェックは入れない）。"""
    answer = run_component(script, JUMP + """
var target = putInParent("pg-202606040611-H3", new Node("tr"));
row3.fire("click", { target: name3 });
var answer = { jumped: !!target.scrolledIntoView, checked: box3.checked,
               lit: (target.attrs["class"] || "").indexOf("pg-jumped") >= 0 };
""", tmp_path)
    assert answer == {"jumped": True, "checked": False, "lit": True}


@needs_jsc
def test_without_the_grid_the_name_selects_the_row(script, tmp_path):
    """馬柱が無い画面（スマホ・別のレース）では、今までどおり行を選ぶだけ。"""
    answer = run_component(script, JUMP + """
var other = putInParent("pg-202606040612-H3", new Node("tr"));   // 別のレースの馬柱の行
row3.fire("click", { target: name3 });
var answer = { jumped: !!other.scrolledIntoView, checked: box3.checked };
""", tmp_path)
    assert answer == {"jumped": False, "checked": True}


# --- スマホの下のバー（資料 Mobile.dc.html: 左「買い目へ追加」・右「買い目 N点 ▲」） -------------

PHONE = """
var P = JSON.parse(JSON.stringify(PAYLOAD)); P.layout = "phone";
render(P);
function bar() { return document.getElementById("phone-bar-add"); }
function slipBets() { return NODES.slip.byClass("bet").map(function (b) { return b.text(); }); }
"""


@needs_jsc
def test_phone_bar_adds_the_picked_horses_to_win_or_place(script, tmp_path):
    """単勝・複勝では、左半分を押すと「単勝へ」「複勝へ」を出し、選んだほうへ入れてシートを開く。"""
    answer = run_component(script, PHONE + """
var before = bar().text();
var boxes = NODES.panel.findAll(function (c) { return c.tagName === "input"; });
boxes[0].click(); boxes[2].click();
var picked = bar().text();
bar().click();
var choice = document.getElementById("phone-bar-choice");
var options = choice.findAll(function (c) { return c.tagName === "button"; }).map(function (b) { return b.text(); });
press(choice, "複勝へ");
var answer = {
  before: before, picked: picked, options: options, bets: slipBets(),
  open: NODES.body.classList.contains("sheet-open"), after: bar().text(),
};
""", tmp_path)
    assert answer["before"] == "買い目へ追加(0頭)"
    assert answer["picked"] == "買い目へ追加(2頭)"
    assert answer["options"] == ["単勝へ", "複勝へ"]
    assert answer["bets"] == ["複勝"]
    assert answer["open"] is True                     # 追加したら買い目シートを開く
    assert answer["after"] == "買い目へ追加(0頭)"     # 選んでいた馬は外れる


@needs_jsc
def test_phone_bar_adds_the_picked_combinations(script, tmp_path):
    """馬連などでは、左半分にパネルで選んだ点数が出て、押すとパネルの追加と同じく買い目に入る。"""
    answer = run_component(script, PHONE + """
NODES.tabs.children[2].click();                       // 馬連のタブ
var empty = bar().text();
var columns = NODES.panel.byClass("slot");
columns[0].findAll(function (c) { return c.tagName === "input"; })[0].click();
var second = columns[1].findAll(function (c) { return c.tagName === "input"; });
second[1].click(); second[2].click();
var picked = bar().text();
bar().click();
var answer = { empty: empty, picked: picked, bets: slipBets(), points: NODES.slip.byClass("pts").map(function (p) { return p.text(); }) };
""", tmp_path)
    assert answer["empty"] == "買い目へ追加(0点)"     # 馬連でも左半分を出す
    assert answer["picked"] == "買い目へ追加(2点)"
    assert answer["bets"] == ["馬連"] and answer["points"] == ["2点"]


# --- 取り込みボタン（淡緑のピル。進み具合は実際の取り込みに連動。資料 2026-10 夕方版） ------------


def _pill(script, tmp_path, progress=None, layout="pc", scenario=""):
    payload = _payload()
    payload["progress"] = progress
    payload["layout"] = layout
    return run_component(script, """
render(PAYLOAD);
function pill() { return NODES.panel.find(function (c) { return (c.attrs["class"] || "").indexOf("import-pill") === 0; }); }
""" + scenario, tmp_path, payload)


@needs_jsc
def test_the_import_pill_says_what_it_does(script, tmp_path):
    answer = _pill(script, tmp_path, scenario="var answer = { text: pill().text() };")
    assert answer["text"] == "↻ 全券種を取り込む（約21秒）"


@needs_jsc
def test_the_import_pill_fills_with_the_real_progress(script, tmp_path):
    answer = _pill(script, tmp_path, {"done": 2, "total": 7}, scenario="""
var b = pill();
var answer = { text: b.text(), disabled: b.attrs.disabled === "disabled", bg: b.style.background };
""")
    assert answer["text"] == "取り込み中… 29%"
    assert answer["disabled"] is True
    assert "29%" in answer["bg"]                    # 淡緑が左から29%まで濃くなる


@needs_jsc
def test_the_import_pill_says_when_it_finished(script, tmp_path):
    answer = _pill(script, tmp_path, {"finished": "12:34"}, scenario="var answer = { text: pill().text() };")
    assert answer["text"] == "✓ 取り込み済み 12:34現在"


@needs_jsc
def test_pressing_the_import_pill_asks_for_every_bet_type(script, tmp_path):
    answer = _pill(script, tmp_path, scenario="""
pill().click();
var answer = { sent: SENT.map(function (v) { return v.kind; }), bets: SENT[0] && SENT[0].bets, text: pill().text() };
""")
    assert answer["sent"] == ["fetch"]
    assert len(answer["bets"]) >= 2
    assert answer["text"] == "取り込み中… 0%"     # 押した直後（最初の進み具合が届くまで）


@needs_jsc
def test_the_phone_pill_is_short(script, tmp_path):
    answer = _pill(script, tmp_path, layout="phone", scenario="var answer = { text: pill().text() };")
    assert answer["text"] == "↻ 取り込む"
