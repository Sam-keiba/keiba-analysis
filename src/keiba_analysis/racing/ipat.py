"""買い目を「IPAT投票」用の形にそろえる（変換と検証）。送り方はアダプターとして分ける。

競馬新聞が受け持つのは、買い目を **開催（場・回・日目）・レース番号・式別・馬番・金額** の
明細に直し、IPATへ持っていけるかを確かめるところまで。

- IPATへ買い目を渡す方法（連動の仕様）は**公開されていない**ので、ここでは作らない。
  送り方は `IpatSender` の形だけ決めておき、今は手で入力するための一覧を返す
  `ManualSender` だけを用意する。仕様が分かったら、送り方のクラスを足して差し替える。
- 暗証番号・P-ARS番号・加入者番号は受け取らない・持たない・ログに出さない。
  ログインと「投票」ボタンは、JRAの画面で利用者が自分で行う。
- 画面・通信の解析、画面の自動操作、投票の自動実行はしない。

買い目のまとまり（`{bet, combos, amount, kind}`）は、フォーメーション・ながし・BOXでも
**1点ずつにばらす**。IPAT側のまとめ入力の形が分からないため、確実な1点ずつの形にしておく。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from keiba_data.race_id import decode_race_id
from keiba_data.scrapers import jra_odds

# 馬券は100円単位（1点100円から）
UNIT_YEN = 100
# 枠番は1〜8
MAX_FRAME = 8
# JRA IPAT の入口（公式）。ここへは**買い目を渡さず**、開くだけ
IPAT_URL = "https://www.ipat.jra.go.jp/"


@dataclass(frozen=True)
class BetSpec:
    """式別1つ。単勝から3連単まで同じ作りで持つ（足すときはここに1行増やす）。"""

    key: str          # 買い目で使う名前（tansho など）
    label: str        # 「3連単」
    legs: int         # 1点の頭数（単勝1・馬連2・3連単3）
    ordered: bool     # 着順どおりか（馬単・3連単）
    by_frame: bool    # 馬番ではなく枠番か（枠連）


BET_SPECS: dict[str, BetSpec] = {
    b.key: BetSpec(b.key, b.label, b.legs, b.ordered, b.by_frame) for b in jra_odds.BET_TYPES
}


@dataclass(frozen=True)
class IpatLine:
    """明細の1行（1点）。"""

    bet: str
    label: str
    numbers: tuple[int, ...]   # 馬番（枠連は枠番）。馬単・3連単は着順どおり、それ以外は小さい順
    amount: int                # この1点の金額（円）
    ordered: bool = False

    @property
    def combo_text(self) -> str:
        """「1-12」「12→7→1」。着順のある式別は矢印でつなぐ。"""
        return ("→" if self.ordered else "-").join(str(n) for n in self.numbers)


@dataclass
class IpatTicket:
    """1レースぶんの、IPATへ持っていく買い目。`errors` が空のときだけ送れる。"""

    race_id: str
    race_date: str | None
    venue_code: str
    venue_name: str
    kaiji: int
    nichime: int
    race_no: int
    post_time: str | None
    lines: list[IpatLine] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def points(self) -> int:
        return len(self.lines)

    @property
    def total(self) -> int:
        return sum(line.amount for line in self.lines)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.lines)

    @property
    def race_label(self) -> str:
        """「東京11R」。"""
        return f"{self.venue_name}{self.race_no}R"

    def to_dict(self) -> dict:
        """画面（コンポーネント）へ渡す形。"""
        return {
            "raceId": self.race_id, "raceDate": self.race_date,
            "venueCode": self.venue_code, "venueName": self.venue_name,
            "kaiji": self.kaiji, "nichime": self.nichime, "raceNo": self.race_no,
            "postTime": self.post_time, "raceLabel": self.race_label,
            "lines": [
                {"bet": l.bet, "label": l.label, "numbers": list(l.numbers),
                 "combo": l.combo_text, "amount": l.amount}
                for l in self.lines
            ],
            "points": self.points, "total": self.total,
            "ok": self.ok, "errors": list(self.errors), "warnings": list(self.warnings),
        }


def build_ticket(race: dict, entries: list[dict], groups: list[dict], now: datetime) -> IpatTicket:
    """買い目のまとまりを、1点ずつの明細に直して確かめる。

    - `race`: `race_id`・`race_date`（"YYYY-MM-DD"）・`post_time`（"HH:MM"）・`is_finished`
    - `entries`: 出馬表（`umaban`・`waku`）。馬番・枠番の範囲を確かめるのに使う
    - `groups`: 買い目（`{bet, combos, amount}`）
    - `now`: いまの日本時間（発走前かの判定。テストで差し替えられるよう引数にする）
    だめなところは例外にせず `errors` に理由を積む（画面に出すため）。
    """
    info = decode_race_id(race["race_id"])
    ticket = IpatTicket(
        race_id=info.race_id, race_date=race.get("race_date"),
        venue_code=info.venue_code, venue_name=info.venue_name,
        kaiji=info.kaiji, nichime=info.nichime, race_no=info.race_no,
        post_time=race.get("post_time"),
    )
    _check_time(ticket, race, now)

    numbers = {int(e["umaban"]) for e in entries if e.get("umaban") is not None}
    frames = {int(e["waku"]) for e in entries if e.get("waku") is not None}
    if not numbers:
        ticket.errors.append("馬番がまだ決まっていません（枠順の確定後に使えます）。")

    for group in groups or []:
        spec = BET_SPECS.get(str(group.get("bet")))
        if spec is None:
            ticket.errors.append(f"知らない式別です: {group.get('bet')}")
            continue
        amount = _amount(group.get("amount"))
        if amount is None:
            ticket.errors.append(f"{spec.label}: 金額は{UNIT_YEN}円以上・{UNIT_YEN}円単位にしてください。")
            continue
        for combo in group.get("combos") or []:
            line, error = _line(spec, str(combo), amount, frames if spec.by_frame else numbers)
            if error:
                ticket.errors.append(error)
            else:
                ticket.lines.append(line)

    if not ticket.lines and not ticket.errors:
        ticket.errors.append("買い目がありません。")
    return ticket


def _check_time(ticket: IpatTicket, race: dict, now: datetime) -> None:
    """発走前か。発売の締切（発走の何分前か）は公開情報で確かめられないので、発走時刻だけで見る。"""
    if race.get("is_finished"):
        ticket.errors.append("このレースは結果が確定しています。")
        return
    start = _start(race.get("race_date"), race.get("post_time"))
    if start is None:
        ticket.warnings.append("発走時刻が分からないため、発走前かどうかを確かめていません。")
        return
    if now >= start:
        ticket.errors.append(f"発走時刻（{race.get('post_time')}）を過ぎています。")
    else:
        ticket.warnings.append("発売の締切は発走より前です。締切の時刻はIPATの画面で確かめてください。")


def _start(race_date: str | None, post_time: str | None) -> datetime | None:
    try:
        day = date.fromisoformat(str(race_date))
        hour, minute = (int(x) for x in str(post_time).split(":")[:2])
        return datetime(day.year, day.month, day.day, hour, minute)
    except (TypeError, ValueError):
        return None


def _amount(value) -> int | None:
    """100円以上・100円単位の整数なら円を、そうでなければ None。"""
    try:
        yen = int(value)
    except (TypeError, ValueError):
        return None
    if yen != value and not (isinstance(value, str) and value.strip() == str(yen)):
        return None                       # 小数などは受けない
    if yen < UNIT_YEN or yen % UNIT_YEN:
        return None
    return yen


def _line(spec: BetSpec, combo: str, amount: int, allowed: set[int]) -> tuple[IpatLine | None, str | None]:
    """組み合わせ1つを明細1行に。だめなら (None, 理由)。"""
    try:
        picked = [int(x) for x in combo.split("-")]
    except ValueError:
        return None, f"{spec.label} {combo}: 馬番が読めません。"
    if len(picked) != spec.legs:
        return None, f"{spec.label} {combo}: {spec.legs}頭で選んでください。"
    what = "枠番" if spec.by_frame else "馬番"
    upper = MAX_FRAME if spec.by_frame else max(allowed, default=0)
    for n in picked:
        if not 1 <= n <= upper or (allowed and n not in allowed):
            return None, f"{spec.label} {combo}: {what}{n}はこのレースにありません。"
    # 同じ馬は2度選べない（枠連は同じ枠どうし＝ゾロ目があるので除く）
    if not spec.by_frame and len(set(picked)) != len(picked):
        return None, f"{spec.label} {combo}: 同じ{what}が重なっています。"
    numbers = tuple(picked if spec.ordered else sorted(picked))
    return IpatLine(spec.key, spec.label, numbers, amount, spec.ordered), None


# --- 送り方（アダプター） ----------------------------------------------------------------


@dataclass(frozen=True)
class SendResult:
    """送り方の結果。`url` は開くページ（買い目は載せない）、`lines` は画面に出す一覧。"""

    mode: str                       # "manual"（手で入力）など
    ok: bool
    message: str
    url: str | None = None
    lines: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"mode": self.mode, "ok": self.ok, "message": self.message,
                "url": self.url, "lines": list(self.lines)}


class IpatSender(Protocol):
    """IPATへの送り方。仕様が分かったら、これを満たすクラスを足して差し替える。"""

    mode: str

    def prepare(self, ticket: IpatTicket) -> SendResult: ...


class ManualSender:
    """IPATの画面で手で入力するための一覧を作り、IPATの入口を開くだけ（買い目は送らない）。

    連動の仕様が公開されていないための代わり。ログイン・入力・投票は利用者が自分で行う。
    """

    mode = "manual"

    def prepare(self, ticket: IpatTicket) -> SendResult:
        if not ticket.ok:
            return SendResult(self.mode, False, "買い目に直すところがあります。", None, ())
        head = f"{ticket.race_label}（{ticket.race_date or ''} {ticket.post_time or ''}発走）".replace("（ ", "（")
        lines = tuple(
            f"{line.label} {line.combo_text} {line.amount:,}円" for line in ticket.lines
        )
        return SendResult(
            self.mode, True,
            f"{head} の買い目 {ticket.points}点・合計{ticket.total:,}円を、IPATの画面で入力してください。",
            IPAT_URL, lines,
        )


def default_sender() -> IpatSender:
    """いま使う送り方。連動の仕様が分かるまでは手で入力する形。"""
    return ManualSender()
