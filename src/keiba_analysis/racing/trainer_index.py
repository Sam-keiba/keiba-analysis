"""厩舎AEI・CPI。**式は `shared.sire_index` のものをそのまま使う**（新しい式は作らない）。

`trainer_data.trainer_horse_years` が、`HorseYear` の `sire` 欄に調教師IDを入れた行を返すので、
`sire_index.aei` / `cpi` にそのまま渡せば厩舎版になる。

- **分母は種牡馬と同じ**: 全出走馬の1頭平均賞金（`sire_index.field_by_year(sire_index.horse_years(conn))`）。
  厩舎ごとに分けた行から分母を作ると、年の途中で転厩した馬が2回数えられてずれるので使わない
- **厩舎AEI**: 直近10世代の馬が、この厩舎にいた間に稼いだ賞金（障害込み）
- **厩舎CPI**: その馬たちの母が産んだ**他の厩舎の馬**（平地）の稼ぎ。入ってくる馬の質の目安
  （種牡馬CPIの「別の種牡馬との間の産駒」を「別の厩舎の馬」に置き換えたもの）
- **AEI / CPI**: CPIが平地だけなので、割るほうのAEIも平地にそろえる（種牡馬分析と同じ）
"""

from __future__ import annotations

from dataclasses import dataclass

from keiba_analysis.shared.sire_index import FieldYear, HorseYear, IndexResult, aei, cpi


@dataclass(frozen=True)
class TrainerIndex:
    aei: IndexResult           # 障害込み
    flat_aei: IndexResult      # 平地のみ（AEI / CPI の分子）
    cpi: IndexResult

    @property
    def ratio(self) -> float | None:
        if self.flat_aei.value is None or not self.cpi.value:
            return None
        return self.flat_aei.value / self.cpi.value


def trainer_index(rows: list[HorseYear], trainer_id: str, *, first_crop: int, last_crop: int,
                  field: dict[int, FieldYear], flat_field: dict[int, FieldYear]) -> TrainerIndex:
    """直近10世代（`first_crop`〜`last_crop` 年生）の厩舎AEI・CPI。

    `rows` は `trainer_data.trainer_horse_years`。この厩舎の行は世代で絞り、それ以外の行
    （CPIの兄弟の候補）はそのまま残して `sire_index` の関数に渡す。
    """
    picked = [r for r in rows if r.sire != trainer_id
              or (r.crop is not None and first_crop <= r.crop <= last_crop)]
    return TrainerIndex(
        aei=aei(picked, trainer_id, field=field),
        flat_aei=aei(picked, trainer_id, flat_only=True, field=flat_field),
        cpi=cpi(picked, trainer_id, field=flat_field),
    )
