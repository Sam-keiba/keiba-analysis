"""馬券の検証（競馬分析の「馬券検証」タブ）。条件に合う馬を買い続けたときの回収率を出す。Streamlitに依存しない。

`payouts` を使うので**2023年以降だけ**。1レースの中で条件に合う馬を選び、1点100円で買う。

- 単勝・複勝 … 選んだ馬を1頭ずつ
- 枠連・馬連・ワイド・三連複 … 選んだ馬のBOX（順序なし）
- 馬単・三連単 … 選んだ馬のBOX（順序あり）

次のレースは母数に入れず、件数を結果に残す:

- その券種が発売されていない（払戻の行が無い。例: 8頭以下の枠連）
- 選んだ馬が足りず、1点も買えない
- 点数が `max_points` を超える

**返還は扱わない。** 選ぶのは取消・除外ではない馬だけなので、買った組み合わせに返還は起きない。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from itertools import combinations, permutations

import numpy as np

from keiba_analysis.racing.condition_stats import PAYOUT_START, Filters, build_where, from_clause
from keiba_analysis.shared.sire_runs import MIN_RUNS

BET_TYPES = ("単勝", "複勝", "枠連", "馬連", "ワイド", "馬単", "三連複", "三連単")
STAKE_YEN = 100
DEFAULT_MAX_POINTS = 100


def tickets(bet_type: str, runners: list[tuple[int, int]]) -> set[str]:
    """選んだ馬 `(馬番, 枠番)` から、買う組み合わせ（`payouts.combination` と同じ書式）を作る。"""
    numbers = sorted(umaban for umaban, _ in runners)
    if bet_type in ("単勝", "複勝"):
        return {str(n) for n in numbers}
    if bet_type == "枠連":
        # 同じ枠どうし（1-1）は、その枠に2頭選んだときだけ買える
        return {"-".join(str(w) for w in sorted(pair)) for pair in combinations((w for _, w in runners), 2)}
    if bet_type in ("馬連", "ワイド"):
        return {"-".join(map(str, c)) for c in combinations(numbers, 2)}
    if bet_type == "三連複":
        return {"-".join(map(str, c)) for c in combinations(numbers, 3)}
    if bet_type == "馬単":
        return {"-".join(map(str, c)) for c in permutations(numbers, 2)}
    if bet_type == "三連単":
        return {"-".join(map(str, c)) for c in permutations(numbers, 3)}
    raise ValueError(f"知らない券種: {bet_type}")


@dataclass(frozen=True)
class YearResult:
    year: str
    races: int
    points: int
    hit_races: int
    returned_yen: int

    @property
    def roi(self) -> float | None:
        return self.returned_yen / (self.points * STAKE_YEN) if self.points else None

    @property
    def is_thin(self) -> bool:
        return self.races < MIN_RUNS


@dataclass(frozen=True)
class BacktestResult:
    bet_type: str
    races: int                     # 実際に買ったレース
    points: int
    hit_races: int
    returned_yen: int
    interval: tuple[float, float] | None   # 回収率の95%区間（レース単位のブートストラップ）
    years: tuple[YearResult, ...]
    first_date: str | None
    last_date: str | None
    skipped_not_sold: int          # その券種の発売が無かったレース
    skipped_too_few: int           # 選んだ馬が足りなかったレース
    skipped_over_limit: int        # 点数の上限を超えたレース

    @property
    def stake_yen(self) -> int:
        return self.points * STAKE_YEN

    @property
    def roi(self) -> float | None:
        return self.returned_yen / self.stake_yen if self.points else None

    @property
    def hit_rate(self) -> float | None:
        """当たったレースの割合。"""
        return self.hit_races / self.races if self.races else None


def bootstrap_interval(points: np.ndarray, returned: np.ndarray, *, n_boot: int = 2000, seed: int = 0,
                       alpha: float = 0.05) -> tuple[float, float] | None:
    """回収率の95%区間。レースを復元抽出する。seed を固定して、同じ条件なら同じ値を返す。"""
    n = len(points)
    if n < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    rois = returned[idx].sum(axis=1) / (points[idx].sum(axis=1) * STAKE_YEN)
    low, high = np.quantile(rois, [alpha / 2, 1 - alpha / 2])
    return float(low), float(high)


def backtest(conn: sqlite3.Connection, filters: Filters, bet_type: str,
             *, max_points: int = DEFAULT_MAX_POINTS, n_boot: int = 2000, seed: int = 0) -> BacktestResult:
    """`filters` に合う馬を `bet_type` で買い続けた成績。開始日は `PAYOUT_START` 以降に切り上げる。"""
    if bet_type not in BET_TYPES:
        raise ValueError(f"知らない券種: {bet_type}")
    filters = filters.with_start_at_least(PAYOUT_START)
    where, params = build_where(filters)
    selected: dict[str, list[tuple[int, int]]] = {}
    dates: dict[str, str] = {}
    sql = (f"SELECT res.race_id, ra.race_date, e.umaban, e.waku {from_clause(filters)}"
           f" WHERE {where} ORDER BY ra.race_date, res.race_id")
    for race_id, race_date, umaban, waku in conn.execute(sql, params):
        selected.setdefault(race_id, []).append((umaban, waku))
        dates[race_id] = race_date

    payouts: dict[str, dict[str, int]] = {}
    if selected:
        first, last = min(dates.values()), max(dates.values())
        for race_id, combination, yen in conn.execute(
            "SELECT p.race_id, p.combination, p.payout_yen FROM payouts p JOIN races ra ON ra.race_id = p.race_id"
            " WHERE p.bet_type = ? AND ra.race_date BETWEEN ? AND ?", (bet_type, first, last)):
            payouts.setdefault(race_id, {})[combination] = yen

    not_sold = too_few = over_limit = 0
    bought: list[tuple[str, int, int]] = []   # (レース, 点数, 払戻)
    for race_id, runners in selected.items():
        race_payouts = payouts.get(race_id)
        if not race_payouts:
            not_sold += 1
            continue
        wanted = tickets(bet_type, runners)
        if not wanted:
            too_few += 1
            continue
        if len(wanted) > max_points:
            over_limit += 1
            continue
        bought.append((race_id, len(wanted), sum(race_payouts.get(t, 0) for t in wanted)))

    by_year: dict[str, list[tuple[int, int]]] = {}
    for race_id, points, returned in bought:
        by_year.setdefault(dates[race_id][:4], []).append((points, returned))
    years = tuple(
        YearResult(year, len(rows), sum(p for p, _ in rows), sum(r > 0 for _, r in rows), sum(r for _, r in rows))
        for year, rows in sorted(by_year.items())
    )
    point_array = np.array([p for _, p, _ in bought], dtype=float)
    return_array = np.array([r for _, _, r in bought], dtype=float)
    bought_dates = [dates[race_id] for race_id, _, _ in bought]
    return BacktestResult(
        bet_type=bet_type,
        races=len(bought),
        points=int(point_array.sum()),
        hit_races=int((return_array > 0).sum()),
        returned_yen=int(return_array.sum()),
        interval=bootstrap_interval(point_array, return_array, n_boot=n_boot, seed=seed),
        years=years,
        first_date=min(bought_dates) if bought_dates else None,
        last_date=max(bought_dates) if bought_dates else None,
        skipped_not_sold=not_sold,
        skipped_too_few=too_few,
        skipped_over_limit=over_limit,
    )
