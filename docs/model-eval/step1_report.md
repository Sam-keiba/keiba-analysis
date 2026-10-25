# STEP 1 報告：予想ボードのコード調査（2026-10-25）

コードは変更していない。tier.py は keiba-analysis 62e5f44 時点。

## 1. tier.py の処理の流れと定数

### 流れ
入口: `keiba-app/src/keiba_app/sections.py:575` の `tier.assign(...)`

1. 入力を集める（sections.py:564-578 / race_context.py:48）
   - `past_runs` … 出走馬の同じ馬場の全過去走（`get_past_runs_for_horses`。件数で切らない）
   - `stats_runs` … 同じ馬場の全走（`get_runs_for_stats`）
   - `fields` … 直近5走それぞれの上位6頭（`get_top_finishers`）
   - `opponent_runs` … その相手たちの直近5走（`get_class_runs`、`before`＝今回のレース日）
   - `today_pace` … 同じコース・同じクラスの過去レースの平均ラップから H/M/S（`today_pace_mark`, sections.py:529）
2. 1走の値
   - `run_value`（tier.py:307）: クラスのレベル＋着順ボーナス
   - `read_run`（tier.py:353）: 相手5頭の「強さ − 秒差×4（1,000mあたり）」の中央値と 0.25:0.75 で混ぜる
3. 実績レベル: `_experience`（tier.py:394）。直近5走を `exp((値−最高値)/τ)` で重みづけした平均。τ は世代で変わる（`generation`, tier.py:388）
4. 適性補正: `pace_fit`（tier.py:450）・`course_fit`（tier.py:466）の複勝率（縮小推定つき）を ±0.5段・±0.4段にして足す（tier.py:576）
5. margin = 実績レベル＋補正 − 今回のクラスのレベル（tier.py:578）
6. 段
   - B/C/D … `tier_of`（tier.py:478）が閾値で決める
   - A … `standout_cut`（tier.py:490）。上位3頭以内に2段以上の切れ目があり、かつ margin ≥ 0.5 の馬
   - 経験馬が1頭もいないレースは、未出走馬の置き場所を変える（tier.py:612）

### 定数一覧（すべて tier.py）
| 定数 | 行 | 値 |
|---|---|---|
| CLASS_LEVEL | 91-94 | 新馬/未勝利0 〜 OP4 |
| GRADE_LEVEL | 95-98 | L 4.5 / GIII 5 / GII 6 / GI 7（J も同じ） |
| WIN_BONUS | 101 | 1.0 |
| PLACE_BONUS | 102 | 0.5 |
| TOP_SHARE | 103 | 0.3 |
| BEATEN_PENALTY | 108 | −3.0 |
| RECENT_RUNS | 110 | 5 |
| BEST_RUNS | 113 | 3 |
| CLASSIC_AGES | 135 | ("2歳","3歳") |
| AGGREGATION | 136 | classic τ=1.0 / old τ=2.5 |
| OPPONENTS | 140 | 5 |
| POPULARITY_WEIGHT | 144 | 3.0 |
| SEC_TO_LEVEL | 147 | 4.0 |
| OPPONENT_WEIGHT | 150 | 0.75 |
| PACE_WEIGHT | 155 | 0.5 |
| COURSE_WEIGHT | 156 | 0.4 |
| PRIOR_RATE | 159 | 0.33 |
| PRIOR_WEIGHT | 160 | 4.0 |
| FULL_FIT_RATE | 161 | 0.66 |
| NEIGHBOUR_DISTANCE_M | 163 | 200 |
| TIER_THRESHOLDS | 172 | B 0.85 / C −0.9 |
| STANDOUT_GAP | 187 | 2.0 |
| STANDOUT_FLOOR | 188 | 0.5 |
| MAX_STANDOUT | 189 | 3 |
| UNRACED_GAP_MAIDEN | 240 | 0.5 |
| UNRACED_GAP_MIXED | 241 | 2.5 |

ファイル外でロジックに効くもの:
- `pace.PACE_DIFF_THRESHOLD_SEC = 1.0`（`keiba-analysis/src/keiba_analysis/racing/pace.py:22`）… H/M/S の判定
- `get_top_finishers` の `n=6`（`keiba-app/src/keiba_app/data.py:309`）、`get_class_runs` の `limit=5`（data.py:343）

表示にしか使わないもの: `CALIBRATION`（208-211）、`_explain` の得意/苦手の境目 0.65/0.35（523）

## 2. データの保管場所とスキーマ
保管場所: SQLite `keiba-data/data/keiba.db`（約2.1GB）。1995-01-05〜2026-10-18、109,752レース。

| テーブル | 単位 | 主なカラム |
|---|---|---|
| races | レース | race_id(12桁), race_date, venue_code, race_no, race_name, grade, surface(turf/dirt/jump), distance_m, going_turf/going_dirt, weather, post_time, age_condition, class_condition, n_runners, winner_* |
| results | 馬×レース | race_id, umaban, horse_id, finish_position, finish_status, time_sec, margin, corner_passing, last_3f, win_odds（確定単勝）, popularity（単勝人気）, prize_man_yen |
| entries | 馬×レース（確定済み） | waku, sex, age, kinryo, jockey_id, trainer_id, horse_weight, weight_diff |
| upcoming_races / upcoming_entries | これから走るレースの出馬表 | races/entries とほぼ同じ。horse_weight は当日発表 |
| odds | 券種×組み合わせ | race_id, bet_type, combo, odds_low/high。取得時点の列が無く、いつのオッズかは不明 |
| race_laps | ハロンごと | race_id, seq, distance_m, lap_sec |
| track_conditions | 開催場×日 | cushion_value, 含水率, going |
| horses | 馬 | horse_name, sire, dam, broodmare_sire, birth_date |
| target_races / target_runs | TARGET 取り込み | PCI, 上り順位, 決め手などの拡張項目（現行の tier では未使用） |

`odds_updates` の中身は未確認。

## 3. 12,627レースの期間と年ごとの数
実測の条件はコードに残っていない（過去の答え合わせスクリプトは一時フォルダにあり消えている）。
DB で照合すると「2023-01-01 〜 2026-10-16 の障害を除くレース」がちょうど 12,627（実際の最終日は 2026-10-12）。
着順のある出走数も 173,834 で docstring と一致する。条件はこれでほぼ確実だが、スクリプトそのものでは確認できていない。

| 年 | レース数 |
|---|---|
| 2023 | 3,329 |
| 2024 | 3,327 |
| 2025 | 3,335 |
| 2026（〜10/12） | 2,636 |

docstring の「2024年以降 9,300」は、同じ条件で 9,298。

## 4. 人気・オッズの使用箇所
- ロジックで人気を使うのは `opponent_strength`（tier.py:343-345）の1か所だけ
  - 相手の馬の過去走それぞれに `3.0 × (0.5 − (人気−1)/(頭数−1))` を足す。1番人気 +1.5段、最低人気 −1.5段
  - 評価する馬自身の人気・今回のレースの人気は使っていない
- win_odds（単勝オッズ）と odds テーブルは tier で一切使っていない
- `CALIBRATION` の popularity（208-211）は実測の平均人気の表示だけ

## 5. 将来の情報が混ざるリスクがある箇所
今回のレースの着順・オッズ・人気は特徴量に入っていない。ただし取得側に次の穴がある。

| 箇所 | 内容 | 本番（未来のレース） | 過去レースの答え合わせ |
|---|---|---|---|
| `get_condition_laps`（data.py:437）→ `today_pace_mark` | 日付で絞っていない。同じコース・同じクラスの全期間の平均ラップで、今回のレース自身や後のレースも入る | 実害なし | リークあり |
| race_context.py:48 `get_past_runs_for_horses` | `before` を渡していない | 実害なし | 結果確定済みのレースをアプリで開くと、そのレース自身の結果が直近走に入る |
| sections.py:565 `get_runs_for_stats` | 同じく `before` なし（ペース適性の材料） | 同上 | 同上 |
| `get_top_finishers`（data.py:308） | 日付の条件なし。ただし渡すのは過去走のレースIDだけ | 問題なし | 入口の past_runs が正しければ問題なし |
| `get_class_runs`（data.py:338） | `before`＝今回のレース日を渡している | 問題なし | 問題なし |

- `before` は `race_date < before` なので同じ日の前のレースも除かれる（安全側）
- 相手の人気（results.popularity）は確定時点のものだが、相手の過去走なので今回のレース前に分かる情報
- 不明: 過去の実測が `before` をどう渡し、ペース適性に何を使ったかは、スクリプトが残っていないので確認できない

## 次のSTEPへの注意点
- 答え合わせの基盤では、すべての取得に今回のレース日を基準にした `before` を必ず通す。`get_condition_laps` には日付の引数が無いので、評価用の新しいファイル側で日付つきのクエリを用意する（既存ファイルは変えない）
- 最初に現行ロジックで旧実測（順位相関 0.390、A 勝率 34.5% など）を再現する。リークを止めて数字がずれたら、旧実測にリークが混ざっていた疑いがある
