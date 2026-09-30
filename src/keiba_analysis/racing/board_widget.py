"""予想ボードのStreamlitウィジェット（ドラッグできる盤の読み込み）。

`board.py` は配置の計算だけを持たせてStreamlitに依存させたくないので、
コンポーネントの宣言はここに分けてある。

`app.py` の中に直接書くとテストから差し替えられない（AppTestは app.py を
別の名前空間で実行するため、`keiba.dashboard.app` の属性を差し替えても効かない）。
モジュールの関数にしておくと、テストから `render` を差し替えて
保存や「自動配置に戻す」の流れを確かめられる。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

COMPONENT_DIR = Path(__file__).parent / "board_component"


@st.cache_resource
def component():
    """盤のコンポーネント（素のHTML+JS。npmもビルドも要らない）。"""
    return components.declare_component("keiba_board", path=str(COMPONENT_DIR))


def render(payload: dict, key: str) -> dict | None:
    """盤を描き、「保存」が押されていればその中身を返す（押されていなければ None）。

    `key` を変えると**別のウィジェットになり、前に返した保存の値は返ってこない**。
    「自動配置に戻す」で盤を作り直すのに使っている。
    """
    return component()(payload=payload, key=key, default=None)
