"""画面の配色とCSS。

白基調（netkeibaのレースページのトーンを参考にした配色。素材やレイアウトの複製はしない）。
色の定数はここに集約し、表（table.py）とコース図（course_map.py）から使う。
"""

from __future__ import annotations

# JRA公式の枠番色（1白・2黒・3赤・4青・5黄・6緑・7橙・8桃）
WAKU_COLORS: dict[int, tuple[str, str]] = {  # 枠番 -> (背景色, 文字色)
    1: ("#ffffff", "#1b1b1b"),
    2: ("#2b2b2b", "#ffffff"),
    3: ("#e2382f", "#ffffff"),
    4: ("#2168c3", "#ffffff"),
    5: ("#f5d800", "#1b1b1b"),
    6: ("#189a54", "#ffffff"),
    7: ("#f08300", "#ffffff"),
    8: ("#f3a5b8", "#1b1b1b"),
}

# 券種の色（買い目の帯とバッジ。どれがどの券種かをひと目で見分けるためだけの色で、
# JRAやnetkeibaの配色とは関係が無い）。8券種が隣り合っても見分けられるよう、
# このファイルのほかの色と同じ系統から重ならないものを選んでいる。
BET_TYPE_COLORS = {
    "tansho": "#c0201a",      # 単勝 赤
    "fukusho": "#f08300",     # 複勝 橙
    "wakuren": "#8a6d3b",     # 枠連 金茶
    "umaren": "#2168c3",      # 馬連 青
    "wide": "#189a54",        # ワイド 緑
    "umatan": "#7a5aa8",      # 馬単 紫
    "sanrenpuku": "#0f7b8a",  # 3連複 青緑
    "sanrentan": "#b03a6b",   # 3連単 梅
}

# 脚質の色（逃げ→追込。暫定ロジックの表示用）
RUNNING_STYLE_COLORS = {
    "逃げ": "#e2382f",
    "先行": "#f08300",
    "差し": "#2168c3",
    "追込": "#189a54",
}

# 馬場の色
SURFACE_BADGE = {
    "turf": ("#189a54", "芝"),
    "dirt": ("#a5714a", "ダート"),
    "jump": ("#7a5aa8", "障害"),
}

# グレードのバッジ色
# グレードの色。G1=青 / G2=赤 / G3=緑（障害のJG1〜JG3も同じ）。リステッドは金茶。
GRADE_COLORS = {
    "GI": "#2168c3",
    "GII": "#d0021b",
    "GIII": "#189a54",
    "JGI": "#2168c3",
    "JGII": "#d0021b",
    "JGIII": "#189a54",
    "L": "#8a6d3b",
}

# 条件戦（グレードが無いレース）の色。クラスごとに分けず、まとめて灰色にする。
CONDITION_CLASS_COLOR = "#9aa09a"

# 過去走一覧の色分け（netkeibaの出馬表の考え方を参考にした独自の配色）
# クラス（グレードが無いレース）の左罫の色
CLASS_COLORS = {
    "オープン": "#b8860b",
    "L": "#b8860b",
    "3勝クラス": CONDITION_CLASS_COLOR,
    "2勝クラス": CONDITION_CLASS_COLOR,
    "1勝クラス": CONDITION_CLASS_COLOR,
    "未勝利": CONDITION_CLASS_COLOR,
    "新馬": CONDITION_CLASS_COLOR,
}
DEFAULT_CLASS_COLOR = "#c9cdc9"

# 着順の色（背景, 文字）。4着以下は色を付けない
FINISH_COLORS = {
    1: ("#fdecec", "#c0201a"),
    2: ("#eaf1fb", "#1b57a5"),
    3: ("#e9f7ef", "#127a42"),
}

# 好走した走のセルの背景色（netkeibaの馬柱と同じく、1〜3着はセルごと色を変える）
FINISH_CELL_COLORS = {1: "#fff8e1", 2: "#eef4fd", 3: "#eefaf1"}

# 上がり3Fがそのレースで最速だった走に付ける色
BEST_LAST_3F_COLOR = "#c0201a"

# 予想ボードの馬名から飛んできたとき、馬柱のその行に付ける色
JUMP_MARK_COLOR = "#e8a33d"
JUMP_MARK_BACKGROUND = "#fff7e6"

# 馬柱／オッズのタブ（レース画面のいちばん下）の大きさと、選択中の色
TAB_FONT_PX = 17
TAB_ACTIVE_COLOR = "#1b7f4b"

# ペース記号（H=ハイ / M=ミドル / S=スロー。判定は pace.py の暫定ロジック）
PACE_COLORS = {"H": "#c0201a", "M": "#9aa09a", "S": "#2168c3"}

# クッション値の区分（軟らかい→硬い。芝の色を濃くしていく）
# 複勝率のヒートマップ（クッション値 × 馬場状態）の階調。低い→高いの順。
# 画面のほかのグラフと同じ緑の系統でそろえている。
RATE_HEAT_COLORS = ("#eef5f0", "#a8d5bd", "#6fbf94", "#3f9c6d", "#1f7a50")
# 合計の行・列の下地（複勝率では塗らないので、色を持たない灰色にする）
TOTAL_CELL_COLOR = "#eceeec"

# 馬柱の列幅（px）。CSSとHTML（past_grid.py の <colgroup>）の両方から使う。
# 列幅は <col> で決めるのがいちばん強いので、そちらを正としてここを唯一の出どころにする。
GRID_MARK_PX = 50        # 予想印（左端。2026-10 の資料で足した列）
GRID_WAKU_PX = 30        # 枠
GRID_UMABAN_PX = 30      # 馬番
GRID_HORSE_PX = 200      # 馬情報（左端の固定列）
GRID_KINRYO_PX = 46      # 斤量（「57.5」の4文字と見出し「斤量」が収まる幅）
# 過去走1列。「18着 26/04/19 中山11R GIII」が1行目に収まる最小の幅
GRID_RUN_PX = 206
# 固定列（横スクロールしても貼り付く帯）の合計。貼り付ける位置もこの並びから出す。
GRID_STICKY_LEFT = {
    "mark": 0,
    "waku": GRID_MARK_PX,
    "umaban": GRID_MARK_PX + GRID_WAKU_PX,
    "horse": GRID_MARK_PX + GRID_WAKU_PX + GRID_UMABAN_PX,
    "kinryo": GRID_MARK_PX + GRID_WAKU_PX + GRID_UMABAN_PX + GRID_HORSE_PX,
}
GRID_FIXED_PX = GRID_STICKY_LEFT["kinryo"] + GRID_KINRYO_PX

# --- スマホ（iPhoneのSafariなど）で使う幅 ---
# 画面の幅は390px前後しかないので、固定の帯（枠・馬番・馬情報・斤量）を細くして、
# **過去走が1列ぶん見える**ようにする。236px + 176px = 412px で、前走がほぼ収まる。
MOBILE_MAX_PX = 640
MOBILE_GRID_MARK_PX = 34
MOBILE_GRID_WAKU_PX = 24
MOBILE_GRID_UMABAN_PX = 26
MOBILE_GRID_HORSE_PX = 150
MOBILE_GRID_KINRYO_PX = 36
MOBILE_GRID_RUN_PX = 176
MOBILE_STICKY_LEFT = {
    "mark": 0,
    "waku": MOBILE_GRID_MARK_PX,
    "umaban": MOBILE_GRID_MARK_PX + MOBILE_GRID_WAKU_PX,
    "horse": MOBILE_GRID_MARK_PX + MOBILE_GRID_WAKU_PX + MOBILE_GRID_UMABAN_PX,
    "kinryo": MOBILE_GRID_MARK_PX + MOBILE_GRID_WAKU_PX + MOBILE_GRID_UMABAN_PX + MOBILE_GRID_HORSE_PX,
}
# 馬情報の文字の幅（セルの左右のpaddingを引いたぶん）
MOBILE_HORSE_LINE_PX = MOBILE_GRID_HORSE_PX - 12

FONT_URL = "https://fonts.googleapis.com/css2?family=Zen+Maru+Gothic:wght@400;500;700&display=swap"

CSS = f"""
<style>
@import url('{FONT_URL}');

/* 本文のフォント。
   アイコン（data-testid="stIconMaterial"）はリガチャ方式で、Streamlit同梱の
   'Material Symbols Rounded' が当たっている。ここでクラス名の部分一致のような
   広い指定に !important を付けると、そのアイコンにも当たってしまい
   「arrow_drop_down」のような名前が文字として見えてしまう。
   そのため本文は継承に任せ、アイコンは下で明示的に元のフォントへ戻す。 */
html, body, .stApp {{
    font-family: 'Zen Maru Gothic', 'Hiragino Maru Gothic ProN', 'Yu Gothic', sans-serif;
}}
.stMarkdown, .stMarkdown *:not([data-testid="stIconMaterial"]),
.stSelectbox, .stTextInput, .stCaption, .stButton button, .stSubheader,
h1, h2, h3, h4, h5, h6, table, th, td, input, label {{
    font-family: inherit;
}}

/* アイコンはStreamlitのアイコンフォントのまま（リガチャ名が文字で出るのを防ぐ） */
[data-testid="stIconMaterial"], [data-testid="stIconMaterial"] *,
.material-symbols-rounded, .material-icons, span[class*="material-symbols"] {{
    font-family: 'Material Symbols Rounded' !important;
    font-feature-settings: 'liga';
}}
/* 馬柱を広く見せる（左端の馬情報＋過去走2走ぶんくらいが一度に見える幅） */
/* 上の余白は Streamlit のヘッダー（高さ3.75rem。右上のDeployボタンの帯）より
   大きくしておく。詰めすぎると、いちばん上の日付タブがヘッダーの下に隠れてしまう。 */
.block-container {{ padding-top: 4.2rem; padding-bottom: 3rem; max-width: 1500px; }}
body {{ color: #1b1b1b; }}

/* ダイアログ（馬名クリックのモーダル）が画面からはみ出さないようにする。
   中身は app.py 側で高さを決めたコンテナに入れてスクロールさせる。 */
[data-testid="stDialog"] [role="dialog"] {{ max-height: 92vh; }}

/* --- レース選択ナビ（日付／開催場／R。netkeibaのレースページの3段に寄せる） --- */
.race-nav {{ margin: 0 0 14px; }}
.race-nav a {{ text-decoration: none; color: #3d453d; }}
.nav-dates {{ display: flex; flex-wrap: wrap; gap: 6px; }}
/* 開催場ごとの段。場名を左に置き、Rのカードは折り返しても場名の右にそろえる */
.nav-races {{ display: flex; align-items: stretch; gap: 6px; margin-top: 8px; }}
/* 1開催＝1行に収める。狭い画面では折り返さず、その行だけ横スクロールする */
.nav-race-list {{ display: flex; flex-wrap: nowrap; overflow-x: auto; gap: 3px; flex: 1; }}
/* 開催場の名前（行の左に置く見出し。同じ日の複数場を上下に並べる） */
.nav-venue-label {{
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 50px; padding: 0 6px; border-radius: 6px; white-space: nowrap;
    background: #eef2ee; color: #3d453d; font-size: 12px; font-weight: 700;
}}
.nav-venue-label.is-active {{ background: #dcebdf; color: #0f7a41; }}

.nav-date {{
    padding: 6px 14px; border: 1px solid #d5dcd5; border-radius: 6px; background: #fff;
    font-size: 13px; font-weight: 700; white-space: nowrap;
}}
.nav-date:hover {{ background: #f0f6f2; }}
.nav-date.is-active {{
    color: #1b57a5; border-color: #2168c3; box-shadow: inset 0 -3px 0 #2168c3;
}}

.nav-venue {{
    min-width: 120px; padding: 8px 18px; border: 1px solid #d5dcd5; border-radius: 6px 6px 0 0;
    background: #eef2ee; font-size: 15px; font-weight: 700; text-align: center;
}}
.nav-venue:hover {{ background: #f0f6f2; }}
.nav-venue.is-active {{
    background: #fff; border-top: 3px solid #2168c3; border-bottom-color: #fff; color: #1b1b1b;
}}

/* Rタブは2行のカード（R番号＋クラス／馬場＋距離）にして、
   押す前から「芝かダートか」「どのクラスか」が分かるようにする */
.nav-race {{
    /* 12レース＋開催場の名前が1行に収まるよう幅を固定する（96px × 12 ＋ 余白 ≒ 1,230px）。
       これより狭い画面では、その開催の行だけ横スクロールする。 */
    box-sizing: border-box; width: 96px; min-width: 96px; padding: 4px 4px 3px;
    border: 1px solid #d5dcd5; border-radius: 5px; background: #fff;
    text-align: center; line-height: 1.25;
}}
.nav-race:hover {{ background: #f0f6f2; }}
.nav-race.is-active {{ background: #2168c3; border-color: #2168c3; color: #fff; }}
.nav-race .nav-race-top {{
    display: flex; align-items: center; justify-content: center; gap: 2px;
}}
.nav-race .nav-race-no {{ font-size: 13px; font-weight: 700; flex: none; }}
.nav-race .nav-class {{
    /* flex: none を付けないと、狭いカードの中で潰れて文字が切れる */
    display: inline-block; flex: none; min-width: 30px; height: 16px; line-height: 16px;
    padding: 0 4px; border-radius: 3px; color: #fff; font-size: 10px; font-weight: 700;
    white-space: nowrap;
}}
.nav-race .nav-course {{ display: block; font-size: 11px; font-weight: 700; }}
.nav-race .nav-time {{ display: block; font-size: 10px; color: #6b716b; }}
/* 選択中は青地なので、馬場の色より白のほうが読める */
.nav-race.is-active .nav-course {{ color: #fff !important; }}
.nav-race.is-active .nav-time {{ color: rgba(255,255,255,.85); }}

/* --- レース見出し --- */
.race-head {{
    border: 1px solid #e3e6e3;
    border-left: 6px solid #189a54;
    border-radius: 10px;
    padding: 14px 18px;
    background: #ffffff;
    box-shadow: 0 1px 3px rgba(0,0,0,.05);
}}
.race-head .rh-top {{ font-size: 14px; color: #6b716b; margin-bottom: 2px; }}
.race-head .rh-name {{ font-size: 25px; font-weight: 700; line-height: 1.35; margin: 2px 0 10px; }}
.race-head .rh-facts {{ display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }}
.race-head .rh-fact {{ font-size: 15px; white-space: normal; }}
.race-head .rh-fact b {{ font-weight: 700; }}
.race-head .rh-foot {{ margin-top: 10px; font-size: 13px; color: #6b716b; }}

.badge {{
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-size: 13px; font-weight: 700; color: #fff; white-space: nowrap;
}}
.badge-course {{ font-size: 15px; padding: 5px 14px; }}
.note {{
    display: inline-block; margin-top: 8px; padding: 6px 12px; border-radius: 8px;
    background: #fff7e0; border: 1px solid #f0dca8; font-size: 13px; color: #6b5a25;
}}

/* --- 馬柱の左端（固定列）に入る馬情報ブロック --- */
table.past-grid .he-line {{
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    font-size: 11px; color: #3d453d; line-height: 1.35;
    width: 188px;  /* 固定列の幅200px - 左右のpadding。理由は .pg-line と同じ */
}}
table.past-grid .he-line.he-sub {{ font-size: 10px; color: #6b716b; }}
table.past-grid .he-line.he-style {{ height: 20px; line-height: 20px; margin-top: 1px; }}
table.past-grid .he-line.he-name {{ font-size: 14px; font-weight: 700; color: #1b1b1b; line-height: 1.3; }}
table.past-grid .he-sexage {{ font-weight: 700; margin-right: 6px; }}
table.past-grid .he-status {{
    display: inline-block; margin-left: 6px; padding: 0 5px; border-radius: 3px;
    background: #fdecec; color: #c0201a; font-size: 10px; font-weight: 700; vertical-align: 2px;
}}
table.past-grid a.horse-link {{
    color: inherit; text-decoration: none; border-bottom: 1px dotted #b7c0b7; cursor: pointer;
}}
table.past-grid a.horse-link:hover {{ color: #0f7a41; border-bottom-color: #0f7a41; }}
table.past-grid tr.scratched td {{ color: #a6aaa6; text-decoration: line-through; }}
.waku {{
    display: inline-block; width: 18px; height: 18px; line-height: 18px; margin-right: 3px;
    border-radius: 4px; text-align: center; font-weight: 700; font-size: 11px;
    border: 1px solid #c9cdc9; vertical-align: 1px;
}}
.umaban {{
    display: inline-block; min-width: 18px; height: 18px; line-height: 18px; font-size: 11px;
    margin-right: 5px; padding: 0 2px; text-align: center; font-weight: 700;
    border: 1px solid #c9cdc9; border-radius: 4px; background: #fff; vertical-align: 1px;
}}

/* --- 脚質（暫定ロジックの簡易表示）。馬情報の最終行に大きめに出す --- */
.run-style {{ display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }}
.run-style .rs-bar {{ display: inline-flex; gap: 2px; }}
.run-style .rs-seg {{
    width: 11px; height: 14px; border-radius: 2px; background: #e3e6e3; display: inline-block;
}}
.run-style .rs-label {{ font-size: 14px; font-weight: 700; }}
.run-style .rs-mark {{ font-size: 10px; color: #9aa09a; }}

/* --- 馬柱（出走表＋過去走。左端の1列だけ固定して、右側だけ横スクロール） --- */
.past-grid-wrap {{ overflow-x: auto; margin-top: 8px; border: 1px solid #e3e6e3; border-radius: 8px; }}
/* 列幅は <col> で決める。table-layout: fixed のもとでは
   ①<col>の指定 → ②1行目のセルの指定 → ③残りを均等割り の順に効くので、
   ①に書けば中身にもセルにも左右されず、端数の割り振りも起きない。 */
table.past-grid col.pg-w-mark {{ width: {GRID_MARK_PX}px; }}
table.past-grid col.pg-w-waku {{ width: {GRID_WAKU_PX}px; }}
table.past-grid col.pg-w-umaban {{ width: {GRID_UMABAN_PX}px; }}
table.past-grid col.pg-w-horse {{ width: {GRID_HORSE_PX}px; }}
table.past-grid col.pg-w-kinryo {{ width: {GRID_KINRYO_PX}px; }}
table.past-grid col.pg-w-run {{ width: {GRID_RUN_PX}px; }}

/* table-layout: fixed は必須。これが無いとブラウザが**中身に合わせて**列幅を決めるので、
   td に width を書いても目安にしかならず、長い行を含む列だけ広がって列幅がばらつく。 */
table.past-grid {{
    border-collapse: separate; border-spacing: 0; font-size: 11px; table-layout: fixed;
}}
table.past-grid th {{
    background: #eef2ee; color: #3d453d; font-weight: 700; font-size: 11px;
    padding: 6px 8px; border-bottom: 2px solid #d5dcd5; white-space: nowrap; text-align: left;
}}
/* 列幅は1行目（ヘッダ）で決まるので、過去走の見出しにもセルと同じ幅を持たせる */
table.past-grid th.pg-run-head {{
    box-sizing: border-box; width: {GRID_RUN_PX}px; min-width: {GRID_RUN_PX}px;
    max-width: {GRID_RUN_PX}px;
}}
table.past-grid td {{
    /* padding・borderを含めた幅で計算する（列幅をきっちりそろえるため） */
    box-sizing: border-box;
    padding: 6px; border-bottom: 1px solid #edf0ed; border-left: 1px solid #f0f3f0;
    vertical-align: top;
    width: {GRID_RUN_PX}px; min-width: {GRID_RUN_PX}px; max-width: {GRID_RUN_PX}px;
    height: 133px; line-height: 1.5; overflow: hidden;
}}
/* 全セルを同じ7行構成にして、行の高さをそろえる（はみ出しは…で省略）。
   …で省略させるのは行のdiv側なので、ここにも幅を持たせる（セル幅と連動）。 */
table.past-grid .pg-line {{
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; height: 19px;
    /* セル幅206px − 左右のpadding12px − 左の色罫4px */
    width: 190px;
}}
table.past-grid .pg-best-3f {{ font-weight: 700; }}
table.past-grid tr:nth-child(even) td {{ background: #fafbfa; }}

/* 予想ボードの馬名から飛んできた馬の行を、しばらく光らせる（2.4秒でJS側が外す）。
   固定列は白い下地を持っているので、**固定列にも色を当てる**（当てないと光らない）。
   行の上下の帯は、横に長い行のどこを見ていても目印になるように。 */
table.past-grid tr.pg-jumped td {{
    box-shadow: inset 0 2px 0 0 {JUMP_MARK_COLOR}, inset 0 -2px 0 0 {JUMP_MARK_COLOR};
}}
table.past-grid tr.pg-jumped .pg-col-waku, table.past-grid tr.pg-jumped .pg-col-umaban,
table.past-grid tr.pg-jumped .pg-horse, table.past-grid tr.pg-jumped .pg-col-kinryo {{
    background: {JUMP_MARK_BACKGROUND};
}}

/* 左端の固定列（枠・馬番・馬情報・斤量）。ここだけ横スクロールしない。
   leftを積み上げて4列とも貼り付ける。積み上げの値は GRID_STICKY_LEFT が唯一の出どころで、
   引き算で書くと列を足したときに**静かにずれる**（実際にそうなっていた）。
   背景は必ず指定する（透けると裏の過去走が見えるため）。
   枠・馬番・斤量は行の高さの**縦中央**にそろえる（文字ブロックの馬情報・過去走だけ上寄せ）。 */
/* 予想印（左端）。押すと印を選ぶ（keiba-app の grid_marks 部品が受け持つ） */
table.past-grid .pg-col-mark {{
    position: sticky; left: {GRID_STICKY_LEFT["mark"]}px;
    z-index: 2; background: #fff; border-left: none;
    box-sizing: border-box; width: {GRID_MARK_PX}px; min-width: {GRID_MARK_PX}px;
    max-width: {GRID_MARK_PX}px;
    padding: 6px 3px; text-align: center; vertical-align: middle;
}}
table.past-grid .pg-col-waku {{
    position: sticky; left: {GRID_STICKY_LEFT["waku"]}px;
    z-index: 2; background: #fff; border-left: none;
    box-sizing: border-box; width: {GRID_WAKU_PX}px; min-width: {GRID_WAKU_PX}px;
    max-width: {GRID_WAKU_PX}px;
    padding: 6px 3px; text-align: center; vertical-align: middle; white-space: normal;
}}
table.past-grid .pg-col-umaban {{
    position: sticky; left: {GRID_STICKY_LEFT["umaban"]}px;
    z-index: 2; background: #fff; border-left: none;
    box-sizing: border-box; width: {GRID_UMABAN_PX}px; min-width: {GRID_UMABAN_PX}px;
    max-width: {GRID_UMABAN_PX}px;
    padding: 6px 3px; text-align: center; vertical-align: middle; white-space: normal;
}}
table.past-grid .pg-horse {{
    position: sticky; left: {GRID_STICKY_LEFT["horse"]}px;
    z-index: 2; background: #fff; border-left: none;
    box-sizing: border-box; width: {GRID_HORSE_PX}px; min-width: {GRID_HORSE_PX}px;
    max-width: {GRID_HORSE_PX}px;
    white-space: normal; vertical-align: top;
}}
/* 斤量。馬をまたいで縦に比べる数字なので、太めに大きく出す。
   固定列の右端なので、ここに影を置いて過去走との境目を示す。 */
table.past-grid .pg-col-kinryo {{
    position: sticky; left: {GRID_STICKY_LEFT["kinryo"]}px;
    z-index: 2; background: #fff; border-left: none;
    box-sizing: border-box; width: {GRID_KINRYO_PX}px; min-width: {GRID_KINRYO_PX}px;
    max-width: {GRID_KINRYO_PX}px;
    padding: 6px 4px; text-align: center; vertical-align: middle; white-space: nowrap;
    font-size: 13px; font-weight: 700; color: #1b1b1b;
    font-variant-numeric: tabular-nums;
    box-shadow: 2px 0 3px rgba(0,0,0,.06);
}}
/* 枠はnetkeibaと同じく、セルいっぱいの色ブロックにする */
table.past-grid td.pg-col-waku .waku {{
    display: block; width: 100%; height: 100px; line-height: 100px;
    margin: 0; border: none; border-radius: 3px; font-size: 13px;
    box-shadow: inset 0 0 0 1px rgba(0,0,0,.08);   /* 1枠（白）も輪郭が見えるように */
}}
table.past-grid tr:nth-child(even) .pg-col-mark,
table.past-grid tr:nth-child(even) .pg-col-waku,
table.past-grid tr:nth-child(even) .pg-col-umaban,
table.past-grid tr:nth-child(even) .pg-horse,
table.past-grid tr:nth-child(even) .pg-col-kinryo {{ background: #fafbfa; }}
table.past-grid th.pg-col-mark,
table.past-grid th.pg-col-waku,
table.past-grid th.pg-col-umaban,
table.past-grid th.pg-horse,
table.past-grid th.pg-col-kinryo {{ background: #eef2ee; z-index: 3; vertical-align: middle; }}

/* 右上の映像リンクを置くため、セルを位置の基準にする */
table.past-grid td.pg-run {{ border-left: 4px solid {DEFAULT_CLASS_COLOR}; position: relative; }}
/* JRA公式のレース結果ページへのリンク（セル右上の小さなフィルムのアイコン） */
table.past-grid .pg-movie {{
    position: absolute; top: 4px; right: 5px; z-index: 1;
    display: inline-flex; color: #4b524b; line-height: 0;
}}
table.past-grid .pg-movie:hover {{ color: #0f7a41; }}
/* 1行目だけは右上の映像アイコン（16px）を避けるので、ほかの行より22px短い。
   ここが列幅を決めている: 「18着 26/04/19 中山11R GIII」がぎりぎり収まる幅で、
   これ以上狭めるとグレードのバッジが切れる。 */
table.past-grid .pg-date {{ color: #6b716b; width: 168px; }}
table.past-grid .pg-race {{ font-weight: 700; }}
table.past-grid .pg-grade {{
    display: inline-block; margin-left: 3px; padding: 0 4px; border-radius: 3px;
    font-size: 10px; font-weight: 700; color: #fff; vertical-align: 1px;
}}
table.past-grid .pg-cond {{ font-weight: 700; }}
/* 着順はセルの中でいちばん目立たせる（1〜3着は色つきの枠で囲う） */
/* 着順は囲まず、色付きの文字だけにする。幅だけそろえて日付の位置を縦にそろえる */
table.past-grid .pg-finish {{
    display: inline-block; box-sizing: border-box; width: 34px;
    font-size: 13px; font-weight: 700; text-align: center;
}}
/* 1〜3着はセルごと色を変える（しま模様より優先させる） */
table.past-grid tr td.pg-1st {{ background: {FINISH_CELL_COLORS[1]}; }}
table.past-grid tr td.pg-2nd {{ background: {FINISH_CELL_COLORS[2]}; }}
table.past-grid tr td.pg-3rd {{ background: {FINISH_CELL_COLORS[3]}; }}
table.past-grid .pg-field {{ color: #6b716b; }}
table.past-grid .pg-time {{ font-weight: 700; font-variant-numeric: tabular-nums; }}
table.past-grid .pg-3f-label {{ color: #9aa09a; font-size: 10px; margin-right: 1px; }}
table.past-grid .pg-corner {{
    display: inline-block; margin: 0 3px; padding: 0 3px; border-radius: 3px;
    background: #eef2ee; color: #3d453d; font-weight: 700;
}}
table.past-grid .pg-corner-empty {{ background: transparent; font-weight: 400; color: #a6aaa6; }}
/* ペース記号のバッジ。**馬柱と持ちタイムで同じ見た目**にするため、
   表に紐づけず単独のクラスで指定する（past_runs.pace_mark が両方から呼ばれる）。 */
.pg-pace {{
    display: inline-block; min-width: 12px; padding: 0 3px; border-radius: 3px;
    color: #fff; font-size: 10px; font-weight: 700; text-align: center; vertical-align: 1px;
}}
/* 馬柱では上り3Fの右に続けて出すので、少し離す */
table.past-grid .pg-pace {{ margin-left: 3px; }}
table.past-grid .pg-rival {{ color: #4b524b; }}
table.past-grid .pg-rival-label {{
    display: inline-block; margin-right: 4px; padding: 0 4px; border-radius: 3px;
    background: #f2f4f2; color: #6b716b; font-size: 10px; font-weight: 700; vertical-align: 1px;
}}
table.past-grid .pg-diff {{ font-weight: 700; font-variant-numeric: tabular-nums; }}
table.past-grid .pg-none {{ color: #a6aaa6; }}
table.past-grid .pg-empty {{ color: #a6aaa6; }}
table.past-grid td.pg-empty {{ border-left-color: #eef0ee; }}

/* --- 過去走 --- */
.past-wrap {{ overflow-x: auto; }}
table.past-runs {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
table.past-runs th {{
    background: #eef2ee; color: #3d453d; font-weight: 700; font-size: 12px;
    padding: 6px 6px; border-bottom: 2px solid #d5dcd5; white-space: nowrap; text-align: left;
}}
table.past-runs td {{ padding: 7px 6px; border-bottom: 1px solid #edf0ed; vertical-align: top; }}
table.past-runs tr:nth-child(even) td {{ background: #fafbfa; }}
table.past-runs td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
table.past-runs td.nowrap {{ white-space: nowrap; }}
table.past-runs td.race {{ font-weight: 700; min-width: 7em; }}
table.past-runs tr.lap-row td {{
    padding: 2px 8px 9px; border-bottom: 1px solid #e4e9e4; font-size: 12px; color: #4b524b;
}}
table.past-runs tr.lap-row .lap-label {{
    display: inline-block; margin-right: 6px; padding: 1px 6px; border-radius: 4px;
    background: #eef2ee; color: #5a625a; font-size: 11px; font-weight: 700;
}}
table.past-runs tr.lap-row .laps {{ margin-right: 14px; font-variant-numeric: tabular-nums; }}
table.past-runs tr.lap-row .pending {{ color: #a6aaa6; }}
table.past-runs tr:nth-child(even) td {{ background: transparent; }}
table.past-runs tbody tr:nth-child(4n+1) td,
table.past-runs tbody tr:nth-child(4n+2) td {{ background: #fafbfa; }}
.past-caption {{ margin-top: 6px; font-size: 12px; color: #6b716b; }}
.past-empty {{
    padding: 10px 12px; border-radius: 8px; background: #fff7e0;
    border: 1px solid #f0dca8; font-size: 13px; color: #6b5a25;
}}

/* モーダル（馬名クリックで開く窓）は、傾向グラフ3つを横に並べるぶん広くする。
   Streamlitの st.dialog は small/large しか選べないので、ここで広げる。
   DOMが変わっても既定の幅に戻るだけで、グラフは狭い幅でも読める。 */
div[data-testid="stDialog"] div[role="dialog"] {{ width: 1120px; max-width: 95vw; }}

/* --- 想定タイム（同条件の平均ラップ／本日の想定ラップのグラフの上） --- */
.forecast-time {{
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 16px;
    margin: 2px 0 4px;
}}
.forecast-time .ft-label {{
    display: inline-block; margin-right: 6px; padding: 1px 7px; border-radius: 4px;
    background: #eef2ee; color: #5a625a; font-size: 11px; font-weight: 700; vertical-align: 2px;
}}
.forecast-time .ft-main {{
    font-size: 20px; font-weight: 700; color: #1b1b1b; font-variant-numeric: tabular-nums;
}}
.forecast-time .ft-sub {{
    font-size: 13px; color: #6b716b; font-variant-numeric: tabular-nums;
}}

/* --- コース図 --- */
.course-box {{
    border: 1px solid #e3e6e3; border-radius: 10px; background: #fcfdfc;
    padding: 6px 8px 2px; box-shadow: 0 1px 3px rgba(0,0,0,.04);
}}
.course-svg {{ width: 100%; height: auto; }}
.course-svg .cm-title {{ font-size: 13px; font-weight: 700; fill: #3d453d; }}
.course-svg .cm-note {{ font-size: 11px; fill: #6b716b; }}
.course-svg .cm-label {{ font-size: 11px; font-weight: 700; fill: #1b1b1b; }}
.course-svg text {{ font-family: 'Zen Maru Gothic', sans-serif; }}

/* --- 開催の勝ちタイム（コース図の下）。行数が多いので高さを決めてスクロールさせる --- */
.meeting-wrap {{
    max-height: 560px; overflow-y: auto; border: 1px solid #e3e6e3; border-radius: 8px;
}}
table.meeting {{ border-collapse: collapse; width: 100%; font-size: 11px; }}
table.meeting td {{ padding: 3px 4px; border-bottom: 1px solid #eef0ee; white-space: nowrap; }}
/* 日の区切り。クッション値（ダートは含水率）は日ごとの値なのでここに置く */
table.meeting tr.mt-day td {{
    position: sticky; top: 0; z-index: 1;
    background: #eef2ee; color: #3d453d; font-weight: 700; font-size: 11px; padding: 3px 6px;
}}
table.meeting .mt-no {{ width: 30px; text-align: right; color: #6b716b; }}
table.meeting .mt-course {{ width: 54px; font-weight: 700; }}
table.meeting .mt-class {{ width: 38px; color: #5a615a; }}
/* レース名は余った幅を受け持つ（長ければ…で省略）。列がばらけて読みにくくならないように */
table.meeting .mt-name {{ color: #5a615a; }}
table.meeting .mt-name div {{
    max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
table.meeting .mt-time {{ width: 46px; font-weight: 700; font-variant-numeric: tabular-nums; }}
table.meeting .mt-split {{ width: 62px; color: #5a615a; font-variant-numeric: tabular-nums; }}
table.meeting .mt-style {{ width: 32px; text-align: center; }}
table.meeting .mt-going {{ width: 26px; text-align: center; color: #5a615a; }}
/* いちばん右の詳細（JRA公式のレース結果ページへのリンク） */
table.meeting .mt-detail {{ width: 24px; text-align: center; }}
table.meeting .mt-link {{ display: inline-flex; color: #4b524b; line-height: 0; }}
table.meeting .mt-link:hover {{ color: #0f7a41; }}

/* --- 持ちタイム（コース図の下）。狭い左カラムに6列を収める --- */
/* 持ちタイムは開催の勝ちタイムの下に重ねるので、右の列が縦に伸びすぎないよう
   高さの上限を決めてスクロールさせる（開催の勝ちタイムと同じ考え方）。 */
.best-times-wrap {{ overflow-x: auto; max-height: 420px; overflow-y: auto; }}
table.best-times {{
    border-collapse: collapse; width: 100%; font-size: 11px; table-layout: fixed;
}}
/* 列の名前は**中央ぞろえ**。中身の寄せ（下の td.bt-… ）は見出しに効かせない */
table.best-times th {{
    background: #f2f4f2; color: #4a514a; font-weight: 700; font-size: 10px;
    padding: 3px 4px; border-bottom: 1px solid #d8dcd8; text-align: center; white-space: nowrap;
}}
table.best-times td {{
    padding: 3px 4px; border-bottom: 1px solid #eef0ee; white-space: nowrap;
}}
table.best-times tbody tr:nth-child(even) {{ background: #fafbfa; }}
table.best-times .bt-waku {{ width: 26px; padding-right: 0; }}
table.best-times .bt-waku .waku {{ margin-right: 0; }}
table.best-times .bt-name {{ width: 130px; padding-right: 8px; }}
/* 長い馬名は…で省略する（馬柱の .pg-line と同じ手。幅は列に合わせる） */
table.best-times .bt-name div {{ width: 100%; overflow: hidden; text-overflow: ellipsis; }}
table.best-times .bt-time {{ width: 48px; font-weight: 700; font-variant-numeric: tabular-nums; }}
/* レース全体の前半3F-後半3F（34.2-34.5）が収まる幅 */
table.best-times .bt-split {{ width: 64px; font-variant-numeric: tabular-nums; color: #5a615a; }}
table.best-times .bt-num {{ width: 34px; font-variant-numeric: tabular-nums; }}
table.best-times .bt-pace {{ width: 30px; }}
table.best-times td.bt-pace {{ text-align: center; }}
table.best-times .bt-style {{ width: 34px; }}
table.best-times td.bt-style {{ text-align: center; }}
/* 開催・馬場・馬場の硬さは別々の列にする（まとめると見比べにくい）。
   文字の列は中央にそろえて、行が波打たないようにする（数字の列はそのまま）。 */
table.best-times .bt-venue {{ width: 40px; color: #5a615a; }}
table.best-times .bt-going {{ width: 36px; color: #5a615a; }}
table.best-times td.bt-venue, table.best-times td.bt-going {{ text-align: center; }}
table.best-times .bt-hard {{ width: 44px; color: #5a615a; font-variant-numeric: tabular-nums; }}
/* 表の中身はすべて中央ぞろえ（開催の勝ちタイムと同じ） */
table.best-times th, table.best-times td {{ text-align: center !important; }}
table.best-times td.bt-name {{ text-align: left !important; }}
table.best-times .bt-finish {{ width: 34px; }}
table.best-times td.bt-finish {{ text-align: right; }}

/* --- 開催の勝ちタイム（持ちタイムと同じ表。列の幅だけここで決める）--------------------- */
/* 11列。右の列（約580px）にそのまま収まる幅にして、横スクロールを出さない（余白を詰める） */
table.mt-table {{ min-width: 0; }}
table.mt-table th, table.mt-table td {{ padding-left: 2px; padding-right: 2px; }}
.mt-hardness {{ margin: 0 0 6px; font-size: 13px; color: #5a615a; }}
.mt-hardness b {{ color: inherit; font-variant-numeric: tabular-nums; }}
table.mt-table .mt-no {{ width: 28px; text-align: right; color: #6b716b; }}
table.mt-table .mt-waku {{ width: 34px; text-align: center; }}
table.mt-table .mt-horse {{ width: 110px; }}
table.mt-table .mt-horse div {{ width: 100%; overflow: hidden; text-overflow: ellipsis; }}
table.mt-table .mt-course {{ width: 48px; font-weight: 700; }}
table.mt-table .mt-class {{ width: 36px; color: #5a615a; text-align: center; }}
/* レース名は余った幅を受け持つ（長ければ…で省略） */
table.mt-table .mt-name div {{ width: 100%; overflow: hidden; text-overflow: ellipsis; color: #5a615a; }}
table.mt-table .mt-time {{ width: 48px; font-weight: 700; font-variant-numeric: tabular-nums; }}
table.mt-table .mt-num {{ width: 40px; text-align: center; font-variant-numeric: tabular-nums; }}
table.mt-table .mt-split {{ width: 64px; font-variant-numeric: tabular-nums; color: #5a615a; }}
table.mt-table .mt-pace {{ width: 36px; text-align: center; }}
table.mt-table .mt-style {{ width: 34px; text-align: center; }}
table.mt-table .mt-going {{ width: 34px; text-align: center; color: #5a615a; }}
table.mt-table .mt-hard {{ width: 40px; color: #5a615a; font-variant-numeric: tabular-nums; }}
table.mt-table .mt-detail {{ width: 30px; text-align: center; }}
table.mt-table th, table.mt-table td {{ text-align: center !important; }}

/* --- 馬柱／オッズ のタブ（レース画面のいちばん下） ---------------------------------
   **セレクタはStreamlitが実際に出す印に合わせる。** 1.64は `data-testid="stTab"` /
   `stTabPanel` と、react-aria の `aria-selected` を出す（BaseWeb時代の印はもう出ない）。
   ここがずれると、CSSは黙って効かなくなる
   （テスト `test_the_tab_selectors_match_the_streamlit_we_have` で実物と突き合わせている）。

   `st.tabs` の切り替えは**ブラウザの中だけで起きる**（サーバーへ行かない）ので、
   押しても再読み込みが無い。表示が切り替わるたびにアニメーションが入り直るので、
   中身にフェードを当てるだけで切り替わりが分かる。 */
.stTabs [role="tablist"] {{
    gap: 4px; border-bottom: 2px solid #c9cfc9;
}}
.stTabs [data-testid="stTab"] {{
    padding: 6px 16px; color: #6b716b;
    border-radius: 7px 7px 0 0; background: #f4f6f4;
    border: 1px solid #e3e6e3; border-bottom: none;
    transition: background .12s, color .12s;
}}
/* タブの字はMarkdownとして描かれるので、中の p にも当てる */
.stTabs [data-testid="stTab"] p {{ font-size: 13px; font-weight: 700; }}
.stTabs [data-testid="stTab"]:hover {{ background: #fff; color: #1b1b1b; }}
.stTabs [data-testid="stTab"][aria-selected="true"] {{
    background: #fff; color: #1b1b1b; border-color: #c9cfc9;
}}
.stTabs [data-testid="stTabPanel"] {{
    padding-top: 10px; animation: keiba-tab-in .18s ease-out;
}}
@keyframes keiba-tab-in {{
    from {{ opacity: 0; transform: translateY(5px); }}
    to {{ opacity: 1; transform: none; }}
}}

/* 馬柱／オッズ（いちばん下）だけは大きく。どちらを見ているかがすぐ分かるように、
   選択中は白抜き＋上に太い帯を出す。`st.container(key="race_tabs")` が付ける
   クラスで狙っているので、**app.py のキーと対で直すこと**。
   持ちタイム（距離）や開催の勝ちタイム（週）のタブは上の小さいままにする。 */
.st-key-race_tabs [data-testid="stTab"] {{
    padding: 12px 26px; border-top: 3px solid transparent;
}}
.st-key-race_tabs [data-testid="stTab"] p {{ font-size: {TAB_FONT_PX}px; font-weight: 700; }}
.st-key-race_tabs [data-testid="stTab"][aria-selected="true"] {{
    border-top-color: {TAB_ACTIVE_COLOR}; color: #1b1b1b;
}}
.st-key-race_tabs [data-testid="stTab"][aria-selected="true"] p {{ color: {TAB_ACTIVE_COLOR}; }}
/* オッズの取り込みボタンは横に並べるので、文字を小さくして詰める */
[class*="st-key-odds_fetch_"] button {{ padding: 2px 6px; }}
[class*="st-key-odds_fetch_"] button p {{ font-size: 12px; }}

/* 馬柱の上に出す「横に流せます」の案内。ふだん（PC）は出さない */
.past-grid-hint {{ display: none; font-size: 12px; color: #6b716b; margin: 8px 0 -4px; }}

/* --- スマホ（iPhoneのSafariなど。{MOBILE_MAX_PX}px以下） -------------------------
   **ページ全体は横スクロールさせない**。長い表（馬柱）とレース選択の行は、
   その中だけを横に流す。指で押すものは44px角を目安にする。
   予想ボードとオッズ（指で動かす部品）は今回そのまま。 */
@media (max-width: {MOBILE_MAX_PX}px) {{
  .block-container {{ padding: 3rem 10px 2rem; max-width: 100%; }}

  /* 見出し（レース名・コース） */
  .race-head {{ padding: 10px 12px; }}
  .race-head .rh-name {{ font-size: 20px; margin: 2px 0 8px; }}
  .race-head .rh-fact {{ font-size: 13px; }}
  .race-head .rh-top, .race-head .rh-foot {{ font-size: 12px; }}
  .badge-course {{ font-size: 13px; padding: 4px 10px; }}

  /* レース選択ナビ。押しやすさを優先して、高さを確保する */
  .nav-date, .nav-venue {{ min-height: 44px; }}
  .nav-venue {{ min-width: 44px; font-size: 13px; }}
  .nav-race {{ width: 84px; min-width: 84px; }}

  /* 左右に並べている列（材料など）は縦に積む。横に2つ並べると読めない */
  [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  [data-testid="stColumn"] {{ min-width: 100% !important; flex-basis: 100% !important; }}

  /* 馬柱。固定の帯を細くして、過去走が1列ぶん見えるようにする。
     表の幅はHTML側に書いてあるので、ここでは**列の合計に合わせ直す**
     （インラインの指定より強くする必要があるので !important）。 */
  .past-grid-hint {{ display: block; }}
  .past-grid-wrap {{ -webkit-overflow-scrolling: touch; }}
  table.past-grid {{ width: auto !important; }}
  table.past-grid col.pg-w-mark {{ width: {MOBILE_GRID_MARK_PX}px; }}
  table.past-grid col.pg-w-waku {{ width: {MOBILE_GRID_WAKU_PX}px; }}
  table.past-grid col.pg-w-umaban {{ width: {MOBILE_GRID_UMABAN_PX}px; }}
  table.past-grid col.pg-w-horse {{ width: {MOBILE_GRID_HORSE_PX}px; }}
  table.past-grid col.pg-w-kinryo {{ width: {MOBILE_GRID_KINRYO_PX}px; }}
  table.past-grid col.pg-w-run {{ width: {MOBILE_GRID_RUN_PX}px; }}
  table.past-grid .pg-col-mark {{
      left: {MOBILE_STICKY_LEFT["mark"]}px; width: {MOBILE_GRID_MARK_PX}px;
      min-width: {MOBILE_GRID_MARK_PX}px; max-width: {MOBILE_GRID_MARK_PX}px;
  }}
  table.past-grid .pg-col-waku {{
      left: {MOBILE_STICKY_LEFT["waku"]}px; width: {MOBILE_GRID_WAKU_PX}px;
      min-width: {MOBILE_GRID_WAKU_PX}px; max-width: {MOBILE_GRID_WAKU_PX}px;
  }}
  table.past-grid .pg-col-umaban {{
      left: {MOBILE_STICKY_LEFT["umaban"]}px; width: {MOBILE_GRID_UMABAN_PX}px;
      min-width: {MOBILE_GRID_UMABAN_PX}px; max-width: {MOBILE_GRID_UMABAN_PX}px;
  }}
  table.past-grid .pg-horse {{
      left: {MOBILE_STICKY_LEFT["horse"]}px; width: {MOBILE_GRID_HORSE_PX}px;
      min-width: {MOBILE_GRID_HORSE_PX}px; max-width: {MOBILE_GRID_HORSE_PX}px;
  }}
  table.past-grid .pg-col-kinryo {{
      left: {MOBILE_STICKY_LEFT["kinryo"]}px; width: {MOBILE_GRID_KINRYO_PX}px;
      min-width: {MOBILE_GRID_KINRYO_PX}px; max-width: {MOBILE_GRID_KINRYO_PX}px;
  }}
  table.past-grid .he-line {{ width: {MOBILE_HORSE_LINE_PX}px; }}
  table.past-grid .he-line.he-name {{ font-size: 13px; }}
  table.past-grid th, table.past-grid td {{ padding: 4px 5px; }}

  /* 持ちタイム・開催の勝ちタイムの表も、中だけ横に流す */
  table.best-times, table.meeting-times {{ font-size: 11px; }}

  /* スマホの4つのタブ（新聞／予想／オッズ／データ）。画面の上に貼り付けて、
     どこを見ていてもすぐ移れるようにする。`st.container(key="phone_tabs")` が
     付けるクラスで狙っているので、**app.py のキーと対で直すこと**。 */
  .st-key-phone_tabs [data-testid="stTabs"] > div:first-child {{
      position: sticky; top: 0; z-index: 30; background: #fff;
      border-bottom: 1px solid #e3e6e3;
  }}
  .st-key-phone_tabs [data-testid="stTab"] {{
      flex: 1 1 0; justify-content: center; padding: 10px 4px; min-height: 44px;
      border-top: 3px solid transparent;
  }}
  .st-key-phone_tabs [data-testid="stTab"] p {{ font-size: 15px; font-weight: 700; }}
  .st-key-phone_tabs [data-testid="stTab"][aria-selected="true"] {{
      border-top-color: {TAB_ACTIVE_COLOR};
  }}
  .st-key-phone_tabs [data-testid="stTab"][aria-selected="true"] p {{ color: {TAB_ACTIVE_COLOR}; }}
}}

/* --- スマホを横向きにしたとき（予想ボードを広く使うため） ----------------------
   iOSのSafariでは**向きを変えさせられない**ので、横にしたときに縦を稼ぐだけ。
   ナビと見出しを詰めて、盤に高さを譲る。 */
@media (max-height: 500px) and (orientation: landscape) {{
  .block-container {{ padding-top: 2.2rem; padding-bottom: 1rem; }}
  .race-head {{ padding: 6px 12px; }}
  .race-head .rh-name {{ font-size: 17px; margin: 0 0 4px; }}
  .race-head .rh-top, .race-head .rh-foot, .race-nav .nav-dates {{ display: none; }}
  .st-key-phone_tabs [data-testid="stTab"] {{ padding: 6px 4px; min-height: 38px; }}
}}
</style>
"""


def waku_color(waku: int | None) -> tuple[str, str]:
    """枠番の (背景色, 文字色)。枠が無い・想定外の値のときは薄いグレー。"""
    return WAKU_COLORS.get(waku or 0, ("#eef0ee", "#6b716b"))
