# keiba-analysis

keiba-data の上に乗る分析層。`racing/`(レース展開・予想関連)、`owner/`(一口馬主・クラブ分析)、`shared/`(血統・種牡馬など両方から使われる分析)の3サブパッケージからなる。

## データの範囲

keiba-data のDBは **1995年以降のJRAのレース**を持っている。2023年以降はスクレイピング、1995〜2022年は Target の書き出しから作られていて、`races.source` / `horses.source` が `'scrape'` / `'target'` で見分けられる。

| 分析 | 範囲 | 注意 |
|---|---|---|
| 種牡馬(`shared/sire_runs.py`) | 全期間。`since="YYYY-MM-DD"` で絞れる | 1996年より前に生まれた馬は父が分からない。種牡馬・母父は名寄せキー(`horses.sire_key` / `broodmare_sire_key`)で束ねる |
| クラブ(`owner/club_data.py`) | 全期間。`since` で絞れる | 2022年以前はレース当時の馬主が無いので、Target 書き出し時点の馬主(`entries.owner_id_at_export`)で代用する(転売された馬はずれる) |
| AEI・CPI(`shared/sire_index.py`) | 中央のみ。年ごとに計算し、期間は年単位で指定 | 地方・総合はデータが無いので算出しない。1995〜2002年は父・母が分からない馬が多く、値が低めに出る |
| 血統クロス(`shared/sire_cross.py`) | 5代血統表の62マスがそろった馬だけ(2023年以降の馬すべてと、2022年以前の馬のうち手元のデータで組めた馬) | マスが欠けた馬は「持たない」側に誤って入るので外す |
| ラップ・払戻(`racing/`) | 2023年以降だけにある | 無い走は推定・描画から外す |

表示用のレース名は `races.race_name_plain`(付記なし・今の名前に寄せたもの)を使う(`shared/race_name.display_race_name`)。2022年以前のクラスは旧呼称(`500万下`)のままなので、判定では `race_name.modern_class` を通す。
