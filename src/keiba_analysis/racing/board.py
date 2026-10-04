"""予想ボードの配置づくり（縦=Tier A/B/C/D、横=道中の隊列）。

自動仮配置は**たたき台**で、保存済みの配置（手で動かした結果）があればそちらを優先する。
盤そのものの描画はコンポーネント側のJS（board_component/index.html）が行い、
ここは「どの馬をどこに置くか」だけを決めて素のdictで渡す。

横軸は `running_style.normalized_position`（0=先頭〜1=最後方）の平均をひっくり返した値で、
**左=Save runner（後方待機）／右=FrontRunner（先行・逃げ）**。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from keiba_analysis.racing import tier as tier_module
from keiba_analysis.racing.running_style import SAMPLE_LIMIT, classify_run, normalized_position
from keiba_analysis.shared.style import waku_color

# レーン（上から順に並べる）。段の呼び名も意味も tier.py を唯一の出どころにする
# （同じ文言を2か所に置いていて、片方だけ直す事故が起きやすかった）。
#
# 見出しは「A 軸」のように**英字＋2文字**だけにして1行に収める。
# 長い説明は `meaning` として持ち、盤ではマウスを乗せたときだけ出す。
LANE_LABELS = {"D": "ここから上げる馬を探す"}   # Dだけ盤での言い方を変える
LANES = tuple(
    (key, tier_module.TIER_SHORT[key], LANE_LABELS.get(key, tier_module.TIER_MEANINGS[key]))
    for key in tier_module.TIERS
)

AXIS_LEFT = "Save runner"
AXIS_RIGHT = "FrontRunner"

NEUTRAL_POSITION = 0.5      # 通過順位が無い馬（新馬など）は真ん中あたりに置く
# 通過順位が無い馬を並べる帯。全員を真ん中の1点に重ねると、新馬戦のように
# 全頭が未知のレースで縦に積み上がってしまうので、この幅に散らす。
# 端まで広げないのは「この馬は逃げる」と言っているように見せないため（枠線も点線にしてある）。
UNKNOWN_BAND = (0.25, 0.75)

# --- マーカーの重なりを避けるための見積もり -------------------------------------------
#
# 重なるかどうかは「マーカーの実際の幅」で決まり、それは馬名の長さで変わる。
# 幅を測れるのは描画するブラウザ側だけなので、ここでは**見積もり**で段を決める。
# 盤の幅は画面によって変わるが、狭めに見ておけば広い画面では余裕が出るだけで崩れない。
# レーン見出しの列の幅。**CSSと共通の値**で、payload でコンポーネントへ渡す。
# 以前はCSSに直書きした104pxと、下の盤幅の見積もりが別々に置かれていて、
# 見出しの幅を変えると重なりの計算だけ古い前提のまま取り残される作りだった。
LANE_HEAD_PX = 110
# 盤の外枠の見積もり。盤は全幅（.block-container は max-width 1500px）だが、
# **狭く見ておく**。実際の盤がこれより広いぶんには馬が離れるだけで崩れないが、
# 狭いと重なるため。手元の25レース（14頭以上）で測ると、見積もりを
# 1,180px→1,060px に下げても盤の高さは平均128px→134pxしか変わらないのに、
# 馬が重ならないブラウザ幅が1,280px→1,150pxまで下がる。高さの代償が小さいので安全側に寄せる。
NOMINAL_BOARD_PX = 1060
NOMINAL_FIELD_PX = NOMINAL_BOARD_PX - LANE_HEAD_PX   # 馬を置ける幅
MARKER_BASE_PX = 54         # 丸22px・すき間8px・左右の余白(6+14px)・枠線(2px×2)
MARKER_CHAR_PX = 14         # 全角1文字ぶん（**CSSの .name の font-size と同じ値**）

EDGE_MARGIN = 0.003         # 端のほんの少し内側に置く（丸めの誤差で切れないように）
MAX_LANE_ROWS = 8           # これ以上は段を増やさない（盤が縦に伸びすぎないための歯止め）
LANE_ROW_PX = 44            # 段の間隔（マーカーの高さ36px + すき間）
LANE_PADDING_PX = 18        # レーンの上下の余白
MIN_LANE_HEIGHT_PX = 170    # 段が少なくてもこれより低くしない（デザインの段の高さ）


@dataclass(frozen=True)
class Metrics:
    """盤の寸法の見積もり一式（PCとスマホで別）。**CSSの寸法と対で直すこと**。"""

    lane_head: int          # レーン見出しの列の幅
    nominal_board: int      # 盤の幅の見積もり（狭めに見る）
    marker_base: int        # マーカーの、馬名以外のぶんの幅
    marker_char: int        # 全角1文字ぶん（CSSの馬名の font-size）
    lane_row: int           # 段の間隔
    lane_padding: int       # レーンの上下の余白
    min_lane_height: int    # レーンの最低の高さ

    @property
    def field(self) -> int:
        return self.nominal_board - self.lane_head


PC = Metrics(
    lane_head=LANE_HEAD_PX, nominal_board=NOMINAL_BOARD_PX, marker_base=MARKER_BASE_PX,
    marker_char=MARKER_CHAR_PX, lane_row=LANE_ROW_PX, lane_padding=LANE_PADDING_PX,
    min_lane_height=MIN_LANE_HEIGHT_PX,
)
# スマホ（iPhone縦持ちで盤を90度回して横長に出す）。盤の幅＝画面の高さからヘッダーと
# タブバーを引いたぶんで、小さいiPhoneでも560px前後は取れる。マーカーは高さ28px、
# 馬番の四角22px・すき間6px・左右の余白(3+8px)・枠線(2px×2)・馬名12px。
PHONE = Metrics(
    lane_head=44, nominal_board=560, marker_base=44, marker_char=12,
    lane_row=32, lane_padding=8, min_lane_height=76,
)
LAYOUTS = {"pc": PC, "phone": PHONE}


def marker_width(name: str, metrics: Metrics = PC) -> float:
    """マーカーの幅を盤の横幅に対する割合で見積もる。"""
    return (metrics.marker_base + metrics.marker_char * len(name)) / metrics.field


def horizontal_position(runs: list[dict]) -> float | None:
    """その馬の普段の隊列位置。0=Save runner（後方）〜 1=FrontRunner（先行）。

    通過順位が1走も無い馬（新馬・障害だけの馬）は None。
    """
    values = [
        v for v in (
            normalized_position(r.get("corner_passing"), r.get("n_runners"))
            for r in runs[:SAMPLE_LIMIT]
        ) if v is not None
    ]
    if not values:
        return None
    return round(1.0 - sum(values) / len(values), 4)


def _running_style(runs: list[dict]) -> str | None:
    """直近の走から見たその馬の脚質（マーカーの色に使う）。"""
    styles = [
        s for s in (
            classify_run(r.get("corner_passing"), r.get("n_runners"))
            for r in runs[:SAMPLE_LIMIT]
        ) if s
    ]
    if not styles:
        return None
    return max(set(styles), key=styles.count)


def _row_order(count: int) -> list[int]:
    """段を使う順番。真ん中から外へ広げる（1段で済むなら真ん中に置きたい）。"""
    middle = (count - 1) / 2
    return sorted(range(count), key=lambda row: (abs(row - middle), row))


def _assign_rows(markers: list[dict], rows: int, force: bool = False, metrics: Metrics = PC) -> bool:
    """横が近い馬を別の段へ送る。全頭を `rows` 段に収められたら True。

    マーカーは中央ぞろえなので、隣り合う2頭は**幅の半分ずつ**離れていないと重なる。
    """
    placed: list[list[tuple[float, float]]] = [[] for _ in range(rows)]
    order = _row_order(rows)
    for marker in sorted(markers, key=lambda m: m["position"]):
        width = marker_width(marker["horse_name"], metrics)
        for row in order:
            if all(
                abs(marker["position"] - x) >= (width + other) / 2
                for x, other in placed[row]
            ):
                marker["_row"] = row
                placed[row].append((marker["position"], width))
                break
        else:
            if not force:
                return False
            # 段の上限まで来てもまだ入らない。いちばん空いている段に置く
            # （少し重なるが、盤がどこまでも高くなるよりはまし）
            row = min(range(rows), key=lambda r: len(placed[r]))
            marker["_row"] = row
            placed[row].append((marker["position"], width))
    return True


def _spread(markers: list[dict], metrics: Metrics = PC) -> int:
    """同じレーンの馬を段に振り分ける。使った段数を返す。

    段を増やすとレーンが高くなるので、**収まる中でいちばん少ない段数**を選ぶ。
    ここは**自動配置だけ**を相手にする（手で置いた馬は、あとから上書きされる）。
    """
    used = 1
    if markers:
        limit = min(MAX_LANE_ROWS, len(markers))
        for used in range(1, limit + 1):
            if _assign_rows(markers, used, force=used == limit, metrics=metrics):
                break
        for marker in markers:
            # 段の番号を、レーンの中の高さ（0〜1）に直す。段が1つなら真ん中。
            marker["lane_offset"] = round((marker.pop("_row") + 0.5) / used, 4)
    for marker in markers:
        marker["lane_rows"] = used      # レーンの高さを決めるのに使う
    return used


def build_markers(
    entries: list[dict],
    scores: dict[str, "tier_module.TierScore"],
    past_runs: dict[str, list[dict]],
    saved: dict[str, dict] | None = None,
    metrics: Metrics = PC,
) -> list[dict]:
    """盤に置く馬の一覧。

    **自動配置を先に最後まで組んでから、手を入れた馬だけを上書きする**。
    保存された値を混ぜたまま自動配置を計算すると、1頭さわっただけで
    レーンの顔ぶれや引き伸ばしの基準が変わり、**他の馬まで動いてしまう**。
    """
    saved = saved or {}
    markers = []
    for entry in entries:
        horse_id = entry.get("horse_id")
        if not horse_id:
            continue
        runs = past_runs.get(horse_id, [])
        score = scores.get(horse_id)
        auto_position = horizontal_position(runs)
        background, text = waku_color(entry.get("waku"))
        markers.append({
            "horse_id": horse_id,
            "umaban": entry.get("umaban"),
            "waku": entry.get("waku"),
            "horse_name": entry.get("horse_name") or "",
            "tier": score.tier if score else tier_module.LOWEST_TIER,
            "position": auto_position if auto_position is not None else NEUTRAL_POSITION,
            "lane_offset": None,
            # 引き伸ばしの基準に使う「引き伸ばす前の位置」。最後に落とすので画面には出ない
            "_auto": auto_position,
            "comment": "",
            "is_manual": False,
            "is_excluded": False,
            "color": background,
            "text_color": text,
            "style": _running_style(runs),
            # 通過順位が1走も無い馬は、横位置が「並」ではなく「材料が無い」ことを伝える
            "has_position": auto_position is not None,
            "explanation": score.explanation if score else "",
            "margin": round(score.margin, 2) if score else None,
        })

    # --- ここまでが自動配置。手を入れた情報はいっさい混ぜない ---
    _spread_unknown(markers)
    stretch_positions(markers, metrics)
    # 段の割り振りは**広げたあとの位置**で決める（広がるぶん段は少なくて済む）
    for key, *_ in LANES:
        _spread([m for m in markers if m["tier"] == key], metrics)

    # --- 手を入れた馬だけを上書きする ---
    for marker in markers:
        marker.pop("_auto", None)   # 基準に使っただけなので、画面には渡さない
        stored = saved.get(marker["horse_id"])
        if not stored:
            continue
        for key in ("tier", "position", "lane_offset"):
            if stored.get(key) is not None:
                marker[key] = stored[key]
        marker["comment"] = stored.get("comment") or ""
        marker["is_manual"] = bool(stored.get("is_manual"))
        marker["is_excluded"] = bool(stored.get("is_excluded"))
    return markers


def stretch_positions(markers: list[dict], metrics: Metrics = PC) -> None:
    """通過順位のある馬を、そのレースの中で両端まで広げる（その場で書き換える）。

    横位置のもとは「通過順位の平均」で、どの馬も中団あたりに寄るため、
    そのまま置くと盤の両端が余る（手元のDBで測ると軸の42〜91%しか使えていない）。
    レース1つを見るときに知りたいのは**そのメンバーの中での前後関係**なので、
    いちばん前の馬を右端・いちばん後ろの馬を左端にして、間を一次変換で割り振る。

    そのぶん、**横位置はこのレースの中だけの相対値**になる（別のレースの盤と
    横位置をそのまま見比べることはできない）。画面のキャプションにもそう書いてある。

    端はマーカーの幅の半分だけ内側に寄せる。マーカーは中心ぞろえで盤は
    はみ出しを切るので、端ぴったりに置くと名前が半分切れてしまう。
    """
    # 基準は**通過順位のある全馬**の「引き伸ばす前の位置」から作る。
    # 手で動かした馬や消した馬を基準から外すと、1頭さわっただけで最小値・最大値が
    # 変わり、**他の馬が全部動いてしまう**（実測で1頭動かすと10頭/11頭が動いた）。
    basis = [m for m in markers if m.get("_auto") is not None]
    if len(basis) < 2:
        return
    lowest = min(basis, key=lambda m: m["_auto"])
    highest = max(basis, key=lambda m: m["_auto"])
    span = highest["_auto"] - lowest["_auto"]
    if span <= 0:
        return                      # 全馬が同じ位置（割り算できない）

    low = marker_width(lowest["horse_name"], metrics) / 2 + EDGE_MARGIN
    high = 1.0 - marker_width(highest["horse_name"], metrics) / 2 - EDGE_MARGIN
    if low >= high:
        return                      # 名前が長すぎて広げる余地がない

    start = lowest["_auto"]
    for marker in basis:
        ratio = (marker["_auto"] - start) / span
        marker["position"] = round(low + (high - low) * ratio, 4)


def _spread_unknown(markers: list[dict]) -> None:
    """通過順位が無い馬（新馬など）を、真ん中あたりの帯に等間隔で並べる。

    全員を真ん中の1点に置くと、新馬戦のように全頭が未知のレースで縦に積み上がり、
    盤がとても高くなってしまう。横位置に意味は無いので、散らして見やすさを取る。
    """
    unknown = [
        m for m in markers
        if not m["has_position"] and m["position"] == NEUTRAL_POSITION
    ]
    if len(unknown) < 2:
        return
    low, high = UNKNOWN_BAND
    step = (high - low) / (len(unknown) - 1)
    for i, marker in enumerate(sorted(unknown, key=lambda m: m["umaban"] or 0)):
        marker["position"] = round(low + step * i, 4)


def lane_height(markers: list[dict], metrics: Metrics = PC) -> int:
    """レーン1つぶんの高さ（px）。段をいちばん多く使うレーンに合わせる。

    高さを全レーン共通にしておくと、コンポーネント側のドラッグの当たり判定
    （何段目のレーンに落としたか）が割り算1つで済む。
    """
    rows = max((m.get("lane_rows", 1) for m in markers), default=1)
    return max(metrics.min_lane_height, rows * metrics.lane_row + metrics.lane_padding)


def markers_version(markers: list[dict]) -> str:
    """配置とコメントから作る短い符号。中身が同じなら同じ値になる。

    コンポーネント側が「**いま画面に出ているものと同じ内容の描画**」を見分けて
    無視するために使う。保存した直後に、保存前の内容で描き直されて配置が戻る、
    という事故を防ぐためのもの。
    """
    parts = [
        f'{m["horse_id"]}:{m["tier"]}:{m["position"]}:{m["lane_offset"]}'
        f':{m["comment"]}:{int(bool(m.get("is_excluded")))}'
        for m in sorted(markers, key=lambda m: m["horse_id"])
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def board_payload(
    entries: list[dict],
    scores: dict[str, "tier_module.TierScore"],
    past_runs: dict[str, list[dict]],
    saved: dict[str, dict] | None = None,
    rev: int = 0,
    race_id: str | None = None,
    layout: str = "pc",
) -> dict:
    """コンポーネントに渡すデータ一式。

    `race_id` は、盤の馬名から馬柱のその馬へ飛ぶために渡す（別のレースへ飛ばないよう、
    行のidにもレースIDが入っている。`past_grid.grid_row_id`）。
    `rev` は**描くたびに増える番号**。保存のときはPythonが2回走り、1回目は
    「保存前」の内容を渡してしまうので、それが**あとから届いた**ときに
    巻き戻らないよう、コンポーネント側で古い番号の描画を捨てるのに使う。
    `layout` は `"pc"` か `"phone"`。寸法の見積もり（`Metrics`）と、コンポーネントの
    見た目（スマホは小さいマーカー・縦持ちでは90度回して横長に出す）が変わる。
    """
    metrics = LAYOUTS.get(layout, PC)
    markers = build_markers(entries, scores, past_runs, saved, metrics)
    return {
        "layout": layout if layout in LAYOUTS else "pc",
        # 馬名から馬柱へ飛ぶときに使う。**このレースの行しか探さない**ための目印
        "race_id": race_id,
        "lanes": [{"key": k, "label": label, "meaning": meaning} for k, label, meaning in LANES],
        "axis": {"left": AXIS_LEFT, "right": AXIS_RIGHT},
        "markers": markers,
        # 見出しの列の幅はここが唯一の出どころ（CSSに直書きしない）。
        # 馬を置ける幅の見積もり（NOMINAL_FIELD_PX）と必ず同じ前提になる。
        "lane_head": metrics.lane_head,
        "lane_height": lane_height(markers, metrics),
        "version": markers_version(markers),
        "rev": rev,
    }
