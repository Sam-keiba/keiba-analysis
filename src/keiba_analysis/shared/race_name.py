"""レース名・クラス名の表記を、1995〜2022年（Target由来）と2023年以降（スクレイピング由来）でそろえる。

DBは2023年以降をnetkeiba／JRA公式から、1995〜2022年をTargetの書き出しから作っている
（`races.source` が 'scrape' / 'target'）。Target由来の行には次の違いがある。

- **レース名がTargetの略称で、末尾に付記が付く。** 格（`皐月賞G1` `関屋記念HG3` `〜S(L)`）、
  旧クラスの金額（`箕面特別500` `仲秋S1600`）、条件（`元町S・3勝` `未勝利・牝`）、
  指定の印（`未勝利*`）。格もクラスも別の列にあるので、表示では落とす
- **クラスが旧呼称のまま。** 2019年夏の改称前の `500万下` `1000万下` `1600万下`、
  それより前の `900万下` `1500万下`、新馬戦ができる前の `未出走` が残っている

落とす付記は**明示したものだけ**にして、2023年以降のレース名を壊さないようにする。

DBには keiba-data が付記を落として正式名に寄せた `races.race_name_plain` もある
（`スプリンG1` → `スプリンターズS`）。表示は `display_race_name` でこちらを優先し、
`clean_race_name` はこの列を持たない dict のための控えとして残す。
クラシックの判定（`is_classic`）は元の `race_name` の部分一致で足りる。
"""

from __future__ import annotations

import re

# クラシック（この6競走への出走で「クラシックに出た」とみなす）。
# 2023年以降は「第93回東京優駿」、Target由来は「東京優駿G1」なので、**含むかどうか**で見て、
# トライアル（GII・GIII）を拾わないように格もGIに限る
CLASSIC_RACES: tuple[str, ...] = ("皐月賞", "東京優駿", "菊花賞", "桜花賞", "優駿牝馬", "秋華賞")

# 旧クラス名 → 今のクラス名（収得賞金の区切りが同じ段どうしを対応させる）
LEGACY_CLASSES: dict[str, str] = {
    "500万下": "1勝クラス",
    "900万下": "2勝クラス",
    "1000万下": "2勝クラス",
    "1500万下": "3勝クラス",
    "1600万下": "3勝クラス",
    "未出走": "新馬",
}

# Target由来のレース名の末尾に付く付記。外側から順に何度でも落とす
_TARGET_SUFFIXES = (
    re.compile(r"\*$"),                                # 指定の印
    re.compile(r"・(?:牝|父|市|若|九|重|[1-3]勝)$"),   # 条件（牝馬限定・父内国産・市場取引馬・重賞…）
    re.compile(r"(?<=\D)(?:500|900|1000|1500|1600)$"),  # 旧クラスの金額（名前の後ろに付いたものだけ）
    re.compile(r"H?J?G[123]$"),                        # 格（Hはハンデ戦の印）
    re.compile(r"H?\(L\)$"),                           # リステッド
)


def clean_race_name(name: str | None) -> str:
    """Target略称の末尾の付記（格・旧クラスの金額・条件・指定の印）を落とす。

    `皐月賞G1` → `皐月賞`、`南武特H1000` → `南武特H`、`元町S・3勝` → `元町S`。
    2023年以降のレース名（`第84回皐月賞` `3歳以上1勝クラス`）はそのまま返る。
    """
    text = (name or "").strip()
    changed = True
    while changed and text:
        changed = False
        for pattern in _TARGET_SUFFIXES:
            stripped = pattern.sub("", text)
            if stripped != text and stripped:
                text, changed = stripped, True
    return text


def display_race_name(run: dict) -> str:
    """表示用のレース名。`race_name_plain`（keiba-data が付記を落とし、今の名前に寄せたもの）が
    あればそれを、無ければ `race_name` から付記だけ落とす（`race_name_plain` を持たない dict 用）。
    """
    return run.get("race_name_plain") or clean_race_name(run.get("race_name"))


def is_classic(race_name: str | None, grade: str | None) -> bool:
    """クラシック6競走か。GIで、名前に6競走のどれかを含むもの。"""
    return grade == "GI" and any(name in (race_name or "") for name in CLASSIC_RACES)


def classic_sql(name_column: str = "ra.race_name", grade_column: str = "ra.grade") -> str:
    """`is_classic` と同じ条件のSQL（集計クエリに埋め込む）。"""
    names = " OR ".join(f"{name_column} LIKE '%{name}%'" for name in CLASSIC_RACES)
    return f"({grade_column} = 'GI' AND ({names}))"


def modern_class(condition: str | None) -> str:
    """クラス条件の先頭の旧呼称を今の呼称に置きかえる（`500万下 牝` → `1勝クラス 牝`）。

    今の呼称や、知らない呼称はそのまま返す。
    """
    text = condition or ""
    for old, new in LEGACY_CLASSES.items():
        if text.startswith(old):
            return new + text[len(old):]
    return text
