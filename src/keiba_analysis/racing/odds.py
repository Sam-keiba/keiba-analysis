"""オッズの画面に渡す材料を作る（純粋な関数だけ。Streamlitに触らない）。

並びはnetkeibaのオッズページの構造にそろえる（券種ごとのタブ、軸ごとの縦並び、
フォーメーション形式の馬選択）が、色と字はこのアプリのもの（枠番の色など）を使う。

**買い目**（何をどれだけ買うつもりかの控え）は作るが、**購入・投票の機能は作らない。**
JRA-IPATのような投票の導線は、言葉も含めて一切置かない。

オッズそのものの読み取りは `scrapers/jra_odds.py`、DBからの取り出しは
`dashboard/data.py` の `get_odds` / `get_odds_updates`、買い目の保存は
`db.save_bet_slips` / `db.get_bet_slips`。
"""

from __future__ import annotations

import hashlib
import json
import re

from keiba_analysis.shared.style import BET_TYPE_COLORS, waku_color
from keiba_data.scrapers import jra_odds

DASH = "—"


def popularity(odds: dict[str, float | None]) -> dict[str, int]:
    """単勝オッズから人気（1番人気＝もっとも低いオッズ）を出す。同オッズは同じ人気。"""
    values = sorted({value for value in odds.values() if value is not None})
    rank = {value: i + 1 for i, value in enumerate(values)}
    return {combo: rank[value] for combo, value in odds.items() if value is not None}


def format_odds(low: float | None, high: float | None = None) -> str:
    """`32.2` / `5.3 - 7.0`（幅のある券種）/ `—`（票数なし）。"""
    if low is None:
        return DASH
    if high is None:
        return f"{low:.1f}"
    return f"{low:.1f} - {high:.1f}"


def frames(entries: list[dict]) -> list[dict]:
    """枠連のために、枠番ごとの馬番をまとめる（枠に2頭いればゾロ目が買える）。"""
    by_waku: dict[int, list[int]] = {}
    for entry in entries:
        waku, umaban = entry.get("waku"), entry.get("umaban")
        if waku is None or umaban is None:
            continue
        by_waku.setdefault(int(waku), []).append(int(umaban))
    out = []
    for waku in sorted(by_waku):
        background, ink = waku_color(waku)
        out.append({
            "number": waku, "bg": background, "fg": ink,
            "umaban": sorted(by_waku[waku]),
            "name": "・".join(str(n) for n in sorted(by_waku[waku])),
        })
    return out


def horses(entries: list[dict], tansho: dict[str, list]) -> list[dict]:
    """馬番ごとの 枠の色・馬名・単勝オッズ・人気。枠順確定前は空になる。"""
    win = {combo: values[0] for combo, values in tansho.items()}
    ranks = popularity(win)
    out = []
    for entry in entries:
        umaban = entry.get("umaban")
        if umaban is None:
            continue
        combo = str(int(umaban))
        background, ink = waku_color(entry.get("waku"))
        out.append({
            "number": int(umaban), "waku": entry.get("waku"),
            "bg": background, "fg": ink,
            "name": entry.get("horse_name") or "",
            "odds": win.get(combo),
            "pop": ranks.get(combo),
        })
    return sorted(out, key=lambda h: h["number"])


def _odds_map(rows: list[dict]) -> dict[str, list]:
    """`{"3-7": [低, 高]}`。票数なしは `[None, None]`。"""
    return {row["combo"]: [row.get("odds_low"), row.get("odds_high")] for row in rows}


def tabs(updates: dict[str, dict] | None = None) -> list[dict]:
    """画面のタブ。**単勝と複勝はJRAでも1ページ**なので1つにまとめる。

    `[{"key": "tansho", "label": "単勝・複勝", "bets": ["tansho", "fukusho"],
       "chip": "12:31現在"}, …]`

    `key` はそのタブの取り込みに使う券種（＝先頭の券種）。更新マークの文字
    （`chip`）は、そのタブが持つ券種のうち**いちばん新しい取り込み**から作る。
    """
    updates = updates or {}
    out = []
    for bet in fetch_order():
        keys = fetch_keys(bet)
        labels = [(updates.get(k) or {}).get("odds_label") for k in keys]
        out.append({
            "key": bet.key,
            "label": "単勝・複勝" if bet.key == "tansho" else bet.label,
            "bets": keys,
            "chip": update_chip(next((l for l in labels if l), None)),
        })
    return out


def build_payload(
    entries: list[dict], odds: dict[str, list[dict]], updates: dict[str, dict],
    focus: str | None = None, slip: list[dict] | None = None,
    slip_saved_at: str | None = None, read_only: bool = False,
    layout: str = "pc", reserve_px: int = 0,
) -> dict:
    """オッズのコンポーネントに渡す中身をまとめる。

    取り込んでいない券種もタブには出す（淡く出して「取り込めます」と伝える）。
    `focus` はいま取り込んだ券種で、コンポーネントはそのタブを開く
    （押した券種が見えないと、取り込めたのかどうか分かりにくいため）。
    `layout="phone"` はスマホ版の見た目（下部バー＋下から開く買い目シート）。
    `slip` はDBに保存してある買い目、`slip_saved_at` はその保存時刻
    （コンポーネントが「自分が出したばかりの保存より古い中身」を見分けるのに使う）。

    符号は2つ渡す: `version`（全部）と `drawVersion`（**買い目を除いた中身**）。
    買い目を保存しただけのときは `drawVersion` が変わらないので、画面側は
    タブや馬のリストを作り直さずに済む。
    """
    by_bet = {key: _odds_map(rows) for key, rows in odds.items()}
    bet_types = []
    for bet in jra_odds.BET_TYPES:
        table = by_bet.get(bet.key, {})
        update = updates.get(bet.key) or {}
        bet_types.append({
            "key": bet.key, "label": bet.label, "legs": bet.legs,
            "ordered": bet.ordered, "ranged": bet.ranged, "byFrame": bet.by_frame,
            "odds": table, "count": len(table),
            "available": bool(table),
            "time": update.get("odds_label"),
            # 買い目の帯とバッジの色（色はstyle.pyに集約し、画面側には書かない）
            "color": BET_TYPE_COLORS.get(bet.key, "#6b716b"),
        })
    payload = {
        "betTypes": bet_types,
        "tabs": tabs(updates),
        "horses": horses(entries, by_bet.get("tansho", {})),
        "frames": frames(entries),
        "focus": focus,
        # クラウド版では取り込みができないので、更新マーク（↻）を出さない
        "readOnly": bool(read_only),
        # スマホ版（"phone"）は、画面の高さに合わせて中でスクロールし、下部バーと買い目シートを出す。
        # reservePx は画面の高さのうち部品に使えない分（ヘッダー・タブバーなど）
        "layout": layout if layout in ("pc", "phone") else "pc",
        "reservePx": int(reserve_px),
    }
    # 買い目**以外**の符号。金額を直しただけのとき、画面を作り直さずに済ませるために使う
    # （作り直すと、入力した瞬間に買い目の枠が組み直されて上までスクロールしてしまう）
    payload["drawVersion"] = payload_version(payload)
    payload["slip"] = slip or []
    payload["slipSavedAt"] = slip_saved_at
    payload["version"] = payload_version(payload)
    return payload


def payload_version(payload: dict) -> str:
    """中身から作る短い符号。**同じ中身なら同じ値**になる。

    コンポーネントが「いま出ているものと同じ内容の描画」を見分けて捨てるために使う
    （予想ボードの `board.markers_version` と同じ役目）。

    これが無いと画面が固まったようになる。Streamlitは**高さを受け取るたびに
    `render` をコンポーネントへ送り返す**ので、受けるたびに作り直していると
    「高さを送る→描き直す→高さを送る」の往復が止まらず、押している最中の要素が
    差し替わってクリックが消えてしまう。

    オッズの値そのものも符号に入れる（同じ分のうちに取り直すと「12時31分現在」の
    表記が変わらないことがあり、点数や時刻だけでは変化を捉えられないため）。
    Streamlitはどのみちこれ全部をJSONにして送るので、費用はほとんど増えない。
    """
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(body.encode()).hexdigest()[:12]


def update_chip(label: str | None) -> str:
    """各券種のページに出す更新マークの文字。

    `12:31現在` / `最終オッズ`（レースが終わったあと）/ `未取得`。
    押すとその券種だけ取り込み直せる（券種ごとのボタンを並べる代わりの置き場所）。
    """
    if not label:
        return "未取得"
    short = short_time(label)
    # 時刻が読めないとき（「最終オッズ」など）はJRAの言い方をそのまま出す
    return f"{short}現在" if re.fullmatch(r"\d{1,2}:\d{2}", short) else label


def short_time(label: str | None) -> str:
    """「12時31分現在オッズ」→ `12:31`、「最終オッズ」→ `最終`。"""
    if not label:
        return DASH
    matched = re.search(r"(\d{1,2})時\s*(\d{1,2})分", label)
    if matched:
        return f"{int(matched.group(1))}:{int(matched.group(2)):02d}"
    return label.replace("オッズ", "") or DASH


def fetch_order() -> list[jra_odds.BetType]:
    """タブ（＝取り込みの単位）の並び。単勝と複勝は1ページで両方入るので単勝だけ出す。"""
    return [bet for bet in jra_odds.BET_TYPES if bet.key != "fukusho"]


def fetch_keys(bet: jra_odds.BetType) -> list[str]:
    """その更新マークで取り込む券種。単勝を押したら複勝も一緒に入る（同じページ）。"""
    return ["tansho", "fukusho"] if bet.key == "tansho" else [bet.key]


def keys_for(tab_key: str | None) -> list[str]:
    """タブのキー（画面から返ってくる）で取り込む券種。知らないキーなら空。"""
    bet = next((b for b in fetch_order() if b.key == tab_key), None)
    return fetch_keys(bet) if bet else []
