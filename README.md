# keiba-analysis

keiba-data の上に乗る分析層。`racing/`(レース展開・予想関連)、`owner/`(一口馬主・クラブ分析)、`shared/`(血統・種牡馬など両方から使われる分析)の3サブパッケージからなる。

Race_Pred からの切り出し作業中に生まれた未解決の依存関係が残っている(各ファイルの `# TODO(migration)` コメント参照): `style.py` と `past_runs.py` がまだ keiba-app 側に割り当てられたままで、一部の racing/owner モジュールがこれらに依存しているため単体では import できない。
