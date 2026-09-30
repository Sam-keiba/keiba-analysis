"""オッズのStreamlitウィジェット（券種タブ＋馬選択の読み込み）。

`odds.py` は材料を作るだけにしてStreamlitに依存させたくないので、
コンポーネントの宣言はここに分けてある（`board_widget.py` と同じ理由）。

`app.py` の中に直接書くとテストから差し替えられない（AppTestは app.py を
別の名前空間で実行するため、`keiba.dashboard.app` の属性を差し替えても効かない）。

**値を返すのは2つの操作のときだけ**（券種の取り込み＝更新マーク、買い目の保存）。
チェックを入れても券種を変えても画面は再実行されないので、3,360点の3連単でも
さくさく選べる。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

COMPONENT_DIR = Path(__file__).parent / "odds_component"


@st.cache_resource
def component():
    """オッズのコンポーネント（素のHTML+JS。npmもビルドも要らない）。"""
    return components.declare_component("keiba_odds", path=str(COMPONENT_DIR))


def render(payload: dict, key: str) -> dict | None:
    """券種のタブ・オッズ・買い目を描く。

    返るのは画面からの求めだけ:
    - `{"kind": "fetch", "bet": "umaren", "at": …}` … その券種を取り込み直す
    - `{"kind": "slip", "groups": [...], "at": …}` … 買い目を保存する
    `at` は送った時刻で、同じ求めを2回実行しないための目印（`app.handle_odds_action`）。
    """
    return component()(payload=payload, key=key, default=None)
