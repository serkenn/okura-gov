# 実装前の追加調査（misc）：資料の取得、条文の版ごとの取り出しと全文の走査、年齢の判定式の照合

- 作成日：2026-11-09
- 種別：実測（measurements）。公開資料を取得した記録、e-Gov 法令API v2 で条文を版ごとに取り出して本則の全文を機械的に走査した記録、年齢の判定式を国税庁の生年月日の範囲と全日付で照合した記録。
- 対象：`HANDOFF.md` D14 の令和7年分・令和8年分。トピック misc（年齢の判定・親族の範囲・扶養の所属・源泉徴収の区分）。
- 取得した資料の中身（原文の引用）は `docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md` に書いた。本書は「どう取得し、何が機械的に確かめられたか」だけを書く。

## 1. スクリプトと実行方法

| スクリプト | 内容 | 出力 |
|---|---|---|
| `scripts/IMPL_misc_fetch.py` | 国税庁・裁判所の公開資料（HTML・PDF）を取得し、ステータス・ヘッダ・SHA-256・タイトルを記録する。HTML は本文とリンクを抜き出し、生年月日の範囲・親族の範囲・甲欄乙欄などの該当行を拾う。PDF は解析しない | `scripts/results/IMPL_misc_fetch/<set>_<ts>.json` |
| `scripts/IMPL_misc_egov.py` | e-Gov 法令API v2 で所得税法・同施行令を3つの版（2025-12-31、2026-11-09、2026-12-31）、所得税法施行規則・地方税法・地方税法施行令を 2026-11-09 の版で取得し、指定した条を取り出す。本則の全文を行（項・号の単位）ごとに正規表現で走査する。キーワード検索API で「年少扶養親族」を検索する | `scripts/results/IMPL_misc_egov/` |
| `scripts/IMPL_misc_age_check.py` | 年齢の判定式を3つ（A・B・L、下記）実装し、1940-01-01〜2016-12-31 の全日付について、国税庁の資料の生年月日の範囲と区分が一致するかを数える。ネットワークに接続しない | `scripts/results/IMPL_misc_age_check/result.json`・`result.md` |

実行（Windows。pyenv の python.bat シムは使わない）：

```
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/IMPL_misc_fetch.py robots
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/IMPL_misc_fetch.py birth kinship courts gensen
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/IMPL_misc_fetch.py followup tebiki_yogo
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/IMPL_misc_fetch.py hotei
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/IMPL_misc_fetch.py hotei_form
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/IMPL_misc_egov.py
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/IMPL_misc_age_check.py
```

- 環境：Python 3.11.9（Windows）。標準ライブラリだけ（`urllib`、`json`、`html.parser`、`hashlib`、`difflib`、`datetime`、`calendar`）。サードパーティのライブラリ・ツールは使っていない（OSS の安全確認の対象なし）。
- e-Gov の使い方は `scripts/R1_egov_articles.py`・`scripts/R4_fetch_laws.py` のコードを写した（import はしていない）。HTML の抜き出しは `scripts/R3_fetch.py` のコードを写した。
- ダウンロードしたものは、セット・実行ごとに新しい空のディレクトリ `.work/downloads/<YYYYMMDD-HHMMSS>_IMPL_misc_<set>/`（e-Gov は `..._IMPL_misc_egov/`）に置いた。その中ではインタプリタ・ツールを実行していない。HTML から抜き出したテキストは別の新しいディレクトリ `.work/text/<ts>_IMPL_misc_<set>/` に置いた。PDF は Claude Code の Read ツール（ページ指定）で画像・テキストとして読んだ。
- User-Agent は `okura-gov-research/0.1`。リクエストの間は 1.5 秒あけた。個人の情報は送っていない。官報は取得していない。
- 取得の前に robots.txt を取得した（§2.1）。

## 2. 公開資料の取得（IMPL_misc_fetch.py）

### 2.1 robots.txt（`robots_20261109-145459.json`）

| サイト | 結果 |
|---|---|
| https://www.nta.go.jp/robots.txt | `User-agent: *` の Disallow は `/service_publication/` と各国税局の `/service_publication/` だけ。今回取得したパスは含まれない |
| https://www.courts.go.jp/robots.txt | `User-agent: *` の Disallow は各裁判所の `.../kozisotatu/index.html` と `/about/sonota/kensin/giketsunoyoushi/index.html` だけ。`/hanrei/`・`/assets/hanrei/` は含まれない |
| https://laws.e-gov.go.jp/robots.txt | HTTP 200 だが中身は HTML（アプリのページ）で、robots.txt の書式ではなかった。API の利用は既存の R1・R4 と同じ方法 |

### 2.2 取得した資料（すべて取得日 2026-11-09。SHA-256 は先頭16桁。全桁は JSON にある）

| セット・ID | URL | HTTP | バイト | SHA-256（先頭） | Last-Modified |
|---|---|---|---|---|---|
| birth/form_r07_fuyo | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_01.pdf | 200 | 764,201 | 1d3e1ebea76a108b | 2024-09-24 |
| birth/form_r08_fuyo | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_01.pdf | 200 | 1,177,114 | 15bae0d3fbca3dde | 2025-09-03 |
| birth/form_r08_fuyo_kisai | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_02.pdf | 200（**中身は「指定されたページを表示できませんでした」の HTML**。実質的に存在しない URL） | 2,007 | 700138cae1f347c2 | — |
| birth/form_page_1648_01 | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/annai/1648_01.htm | 200 | 15,013 | 578e964143bde65d | 2026-10-16 |
| birth/form_page_1648_73 | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/annai/1648_73.htm | 200 | 13,885 | 6560c1d1e04c3613 | 2026-10-16 |
| birth/tebiki2025_yogo_y13 | https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y13.htm | 200 | 8,579 | 83cc42e4c5640660 | 2025-12-24 |
| birth/nencho2026_105 | https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/105.pdf | 200 | 1,063,580 | 9460af44b13c8651 | 2026-09-24 |
| birth/nencho2025_105 | https://www.nta.go.jp/publication/pamph/gensen/nencho2025/pdf/105.pdf | 200 | 1,077,260 | f69eda756f726c1a | 2025-09-03 |
| followup/nencho2026_106 | https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/106.pdf | 200 | 891,035 | ee4ae06f99998f5f | 2026-08-31 |
| followup/nencho2025_106 | https://www.nta.go.jp/publication/pamph/gensen/nencho2025/pdf/106.pdf | 200 | 5,109,936 | 82d223b7bdcd521e | 2025-08-29 |
| followup/tebiki2026_yogo_y13 | https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2026/03/order3/yogo/3-3_y13.htm | 200（**「指定されたページを表示できませんでした」**。令和8年分の確定申告の手引きの用語ページは取得日時点で無い） | 2,007 | 700138cae1f347c2 | — |
| tebiki_yogo/tebiki2025_yogo_y01〜y20（y13 を除く19件） | https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_yNN.htm | すべて 200 | 7,162〜8,941 | JSON 参照 | 2025-12-24 |
| kinship/ta_1180 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1180.htm | 200 | 23,283 | c92803d8c75aa5c7 | 2026-09-09 |
| kinship/ta_1180_qa | https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1180_qa.htm | 200 | 22,492 | 02839cb155836ab2 | 2026-09-09 |
| kinship/ta_yogo_senmon | https://www.nta.go.jp/taxes/shiraberu/taxanswer/yogo/senmon.htm | 200 | 21,839 | e0d5142e9eabe61f | 2026-09-16 |
| kinship/kokugai_index | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/kokugai/index.htm | 200 | 10,081 | 65d6cab24c19c3f6 | 2026-03-27 |
| kinship/kokugai_qa_pdf | https://www.nta.go.jp/publication/pamph/pdf/0022009-107_02.pdf | 200 | 712,232 | d8e5bc32f793e7ba | 2026-08-31 |
| courts/hanrei_62674 | https://www.courts.go.jp/hanrei/62674/detail2/index.html | 200 | 55,982 | d5f1d9fba2efa6a7 | 2026-05-21 |
| followup/hanrei_62674_pdf | https://www.courts.go.jp/assets/hanrei/hanrei-pdf-62674.pdf | 200 | 6,618 | db1ab6887ca692aa | 2025-09-09 |
| followup/shitsugi_shotoku_05_64 | https://www.nta.go.jp/law/shitsugi/shotoku/05/64.htm | 200 | 4,567 | acefc1183804bb5a | 2025-12-03 |
| followup/shitsugi_shotoku_05_67 | https://www.nta.go.jp/law/shitsugi/shotoku/05/67.htm | 200 | 5,104 | aaa28b7e20889acf | 2025-12-03 |
| followup/shitsugi_gensen_03_09 | https://www.nta.go.jp/law/shitsugi/gensen/03/09.htm | 200 | 5,187 | 90f8cca9bc805fba | 2025-12-03 |
| gensen/ta_2511 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2511.htm | 200 | 19,026 | 55ead732325f9016 | 2026-09-10 |
| gensen/ta_2514 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2514.htm | 200 | 14,141 | 3cacee7456baa1a7 | 2026-09-10 |
| gensen/ta_2520 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2520.htm | 200 | 16,511 | ca76da2d36442be0 | 2026-09-10 |
| gensen/ta_1900 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1900.htm | 200 | 17,785 | 68ad70cadf7276e2 | 2026-09-09 |
| gensen/ta_1177 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1177.htm | 200 | 19,476 | f75c20fcbf5ef8fb | 2026-09-09 |
| hotei/hotei_tebiki2026_02 | https://www.nta.go.jp/publication/pamph/hotei/tebiki2026/PDF/02.pdf | 200 | 6,694,769 | 15960b2fe6c35fe1 | 2026-10-01 |
| hotei/hotei_tebiki2025_02 | https://www.nta.go.jp/publication/pamph/hotei/tebiki2025/PDF/02.pdf | 200 | 6,001,136 | ffd159f901f27116 | 2025-09-01 |
| hotei_form/chousho_r08_jukyusha | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/hotei/pdf/r08/0026009-129.pdf | 200 | 134,427 | cb701f7f2ed4a713 | 2026-09-28 |
| hotei_form/chousho_r08_kisai | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/hotei/pdf/r08/kisai_chousho01.pdf | 200 | 241,782 | 76e9642ac58e12eb | 2026-10-08 |

- 取得はしたが本書・public-sources で使っていないもの：`form_r07_fuyo_1`（簡易対応様式）、`form_r07_fuyo_kisai`、`shinkokusyo_index`、`nencho2026_304`、`kokugai_leaf_pdf`、`zeigakuhyo2026_all`、`nencho2026_103`（public-sources §5.2 で R3 の取得と SHA-256 が同じことだけに使った）、`form_r08_kiso_tokutei`、`form_r07_kiso_tokutei`、`hotei_page_23100051`。記録は JSON にある。
- 「HTTP 200 なのに中身はエラーページ」が2件あった（`2026bun_02.pdf`、`tebiki/2026/...`）。国税庁のサイトは存在しない URL に 200 とエラーページを返すことがある。取得の成否はステータスだけでなくタイトル・サイズで判定する必要がある。

### 2.3 HTML から機械的に拾えた行（`matches` フィールド）

- `tebiki2025_yogo_y13`（◆控除対象扶養親族）の `birth_range` に「扶養親族のうち、平成22年1月1日以前に生まれた方（年齢が16歳以上の方）」ほか4行。
- `tebiki2025_yogo_y10`（◆特定扶養親族）・`y11`（◆老人扶養親族）の `birth_range` に範囲の行。
- `ta_1180`・`ta_yogo_senmon`・`shitsugi_shotoku_05_67` の `kinship` に「6親等内の血族及び3親等内の姻族」「民法第725条」などの行。
- `ta_2511`・`ta_2514`・`ta_2520` の `kou_otsu` に「甲欄」「乙欄」「丙欄」の行。
- 引用した文言は public-sources に書いた。行の全体は `.work/text/<ts>_IMPL_misc_<set>/<id>.txt` にある（git 管理外。再実行で作り直せる）。

## 3. 条文の取り出しと全文の走査（IMPL_misc_egov.py、実行 20261109-145946）

### 3.1 取得した版（すべて HTTP 200、エラー 0 件）

| 法令 | 法令ID | asof | 返った版（law_revision_id） | その版の改正法令・施行日 | 状態 |
|---|---|---|---|---|---|
| 所得税法 | 340AC0000000033 | 2025-12-31 | 340AC0000000033_20251218_507AC0000000013 | 令和7年法律第13号・2025-12-18 | PreviousEnforced |
| 所得税法 | 同 | 2026-11-09 | 340AC0000000033_20261001_507AC0000000070 | 令和7年法律第70号・2026-10-01 | CurrentEnforced |
| 所得税法 | 同 | 2026-12-31 | 340AC0000000033_20261201_508AC0000000012 | 令和8年法律第12号・2026-12-01 | UnEnforced |
| 所得税法施行令 | 340CO0000000096 | 2025-12-31 | 340CO0000000096_20251201_507CO0000000120 | 令和7年政令第120号・2025-12-01 | PreviousEnforced |
| 所得税法施行令 | 同 | 2026-11-09 | 340CO0000000096_20260522_508CO0000000093 | 令和8年政令第93号・2026-05-22 | CurrentEnforced |
| 所得税法施行令 | 同 | 2026-12-31 | 340CO0000000096_20261201_508CO0000000093 | 令和8年政令第93号・2026-12-01 | UnEnforced |
| 所得税法施行規則 | 340M50000040011 | 2026-11-09 | 340M50000040011_20261001_507M60000040018 | 令和7年財務省令第18号・2026-10-01 | CurrentEnforced |
| 地方税法 | 325AC0000000226 | 2026-11-09 | 325AC0000000226_20261101_508AC0000000002 | 令和8年法律第2号・2026-11-01 | CurrentEnforced |
| 地方税法施行令 | 325CO0000000245 | 2026-11-09 | 325CO0000000245_20261101_508CO0000000083 | 令和8年政令第83号・2026-11-01 | CurrentEnforced |

- 2026-12-31 の版は未施行（UnEnforced）。取得日以後に新しい改正法令が公布されれば変わりうる。
- 取り出した条：所得税法 第2条第1項第30号〜第34号の5、第83条の2、第84条、第84条の2、第85条、第121条、第185条、第190条、第194条、第195条、第195条の3。所得税法施行令 第217条の2、第217条の3、第218条、第218条の2、第219条、第220条と、見出しに「源泉控除対象親族」を含む条（2026-11-09・2026-12-31 の版では第318条）。

### 3.2 版の間の差分

| 比較 | 結果 |
|---|---|
| 所得税法施行令 第218条・第218条の2・第219条・第220条（3つの版） | 3つの版の本文を連結した SHA-256 がすべて `337b49872ee286ec…` で**同じ**（差分なし）。この値は `IMPL_misc_egov.py` では計算していない。`shotoku-rei_asof<版>.txt` の「## Num=218」「## Num=218_2」「## Num=219」「## Num=220」の節（見出し行を含む）をこの順に連結した文字列の SHA-256 で、`scripts/IMPL_misc_verify.py hash` で再現できる（`scripts/results/IMPL_misc_verify/hash_218_220.json`） |
| 所得税法施行令 2025-12-31 → 2026-11-09 | 「（特定親族特別控除を適用しない場合）」が第217条の3 → 第217条の2 に移った（本文は同じ）。2025-12-31 の版の第217条の2 は「（特定公益信託の要件等）」 |
| 所得税法施行令 2026-11-09 → 2026-12-31 | 取り出した条に差分なし（diff ファイルは空） |
| 所得税法 2025-12-31 → 2026-11-09 | 第2条第1項第34号の5（源泉控除対象親族）が加わった。第185条・第194条・第195条の「控除対象扶養親族」が「源泉控除対象親族」になった。第84条・第84条の2・第85条は同じ |
| 所得税法 2026-11-09 → 2026-12-31 | 第2条第1項第32号・第33号・第34号の金額だけが変わった（勤労学生 85万→89万、同一生計配偶者・扶養親族 58万→62万。差分ファイル `shotoku_diff_2026-11-09_vs_2026-12-31.diff`）。第84条・第84条の2・第85条は同じ |

### 3.3 本則の全文の走査（`scan.json`・`scan.md`）

行＝項・号・イロハの1単位。件数は「その正規表現に合った行の数」。

| 正規表現（キー） | 所得税法（3版とも） | 所得税法施行令（3版とも） | 所得税法施行規則 | 地方税法 | 地方税法施行令 |
|---|---|---|---|---|---|
| `民法`（minpo） | 3行：第151条の6（2行）、第161条。いずれも相続・組合契約に関する参照で、親族の定義ではない | 7行：第2条の3、第281条、第281条の2、第304条、第340条。いずれも証券・組合・登記に関する参照 | 3行：第49条、第96条の2、第97条 | 13行（第9条、第10条、第14条の9、第14条の20、第18条、第20条の5、第20条の7、第20条の8、第74条の3、第466条） | 2行（第6条の19） |
| `年少扶養親族`（nensho） | 0 | 0 | 0 | 0 | 0 |
| `居住者として[^。]*適用を受けている場合`（applied_as_resident） | 5行：**第83条の2第2項第1号〜第3号、第84条の2第2項第1号・第2号だけ**。第84条（扶養控除）には無い | 0 | 0 | 0 | 0 |
| `扶養親族(とされ｜に該当する者｜に該当するもの)｜特定親族とされ｜同一生計配偶者又は扶養親族`（fuyo_status） | 7行（第79条、第85条、第187条、第194条、第203条の3、第203条の6） | 7行（第11条の2、第205条、第218条、第220条） | 3行 | 7行 | 11行（第7条の2の2、第7条の3の3、第7条の13、第46条の2の2、第46条の3、第47条の3、第48条の6） |

- キーワード検索API（`/keyword?keyword=年少扶養親族&asof=2026-11-09`）は HTTP 404・`{"message":"取得結果が０件です。"}`（`keyword_0.json`）。**「年少扶養親族」は e-Gov に収録された法令の本文（asof 2026-11-09）に出てこない**。
- 走査は正規表現の文字列一致なので、言い換えた書き方（例：「〜の控除を受ける者」）は拾えない。拾えなかったことは「その趣旨の規定が無い」ことの証明にはならない。第84条については条文を直接読んで確かめた（public-sources §4）。

## 4. 年齢の判定式の照合（IMPL_misc_age_check.py）

### 4.1 比べた式

- 式A：`Y − 生まれた年 + (1月1日生まれなら1)`。作成コーナーの `jsGetAge` と同じ式（`docs/measurements/20261109_sakusei-corner_client-analysis.md`）。
- 式B：`Y − 生まれた年`（誕生日の当日に1つ増えるとみなした場合の12月31日の満年齢）。
- 式L：法文から組んだ式。年齢は出生の日から起算し（年齢計算ニ関スル法律第1項）、民法第143条を準用する（同第2項）。n 歳に達するのは、n 年目の起算日に応当する日の前日の終了時。応当する日がないとき（2月29日生まれで平年）はその月の末日の終了時（民法第143条第2項ただし書）。判定日の終了時までに達した最大の n を年齢とする。条文の出典：`docs/public-sources/20261109_R1-laws_social-insurance-age-records.md` §3。

### 4.2 結果（`result.md`）

- 1940-01-01〜2016-12-31 の 28,125 日、2025年・2026年の12月31日の終了時について、**式Aと式Lの不一致は0件**。
- 国税庁の資料の生年月日の範囲（18行。令和7年分8行・令和8年分10行。令和8年分の16歳未満は扶養控除等申告書と法定調書の手引きの2つの出典で別の行にした。出典は public-sources §1）との照合：

| 式 | 不一致 |
|---|---|
| 式A | 全18行で **0件** |
| 式L | 全18行で **0件** |
| 式B | 全18行で1〜2件。不一致はすべて**1月1日生まれ**（例：令和7年分の特定扶養親族で 2003-01-01・2007-01-01、令和8年分の16歳以上で 2011-01-01） |

- 判定日が書かれていない区分（源泉徴収票の「未成年者」欄。令和7年分「平成20年1月3日以後に生まれた方」、令和8年分「平成21年1月3日以後に生まれた方」）を式Lで照合した：

| 判定日の候補 | 令和7年分の不一致 | 令和8年分の不一致 |
|---|---|---|
| その年の12月31日の終了時 | 1件（2008-01-02） | 1件（2009-01-02） |
| 翌年1月1日の終了時 | **0件** | **0件** |

- 例（式A＝式L）：2007-01-01 生まれは令和7年分で19歳（式Bでは18歳）、2003-01-01 生まれは令和7年分で23歳（式Bでは22歳）、2004-02-29 生まれは令和8年分で22歳。

### 4.3 再現性

- `result.json`・`result.md` は実行日時を含まず、同じスクリプトなら同じ内容になる。2026-11-09 の最後の実行での SHA-256：`result.json` 4d15192c7ccf3d7cc56ac91aac5696bc186e09d21cfeab1b4c43d41b3d72aa0d、`result.md` fbceb0f2167ce8cc008413cba77fbd8f260e4de1b33e86d1e3b961385fca5ba7。
- 国税庁の範囲はスクリプトの `RANGES`・`RANGES_OTHER_DATE` に和暦の表記のまま書き、スクリプトの中で西暦に直している（平成＝1988＋年、昭和＝1925＋年）。資料の読み取りの誤りは、この表と public-sources §1 の引用を見比べて確かめられる。

## 5. 分からなかったこと・この実測の限界

- PDF（扶養控除等申告書・年末調整のしかた・法定調書の手引き・国外居住親族Q&A・判決）は人が読んだ。スクリプトでは中身を確かめていない。令和8年分の扶養控除等申告書（`2026bun_01.pdf`）の表面は解像度が低く、「平23.1.1以前生」「平16.1.2生～平20.1.1生」「昭32.1.1以前生」「平23.1.2以後生」の読み取りは、同じ値を書いた年末調整のしかた（105.pdf、106.pdf）・法定調書の手引き（02.pdf）と照らして確かめた。
- 源泉徴収票の「㉖ 未成年者から勤労学生までの各欄」の欄の名前は、手引き（02.pdf）の図では小さく読み取れなかった。様式そのもの（`chousho_r08_jukyusha`。テキストを持つ PDF）を Read ツールで読み、「未成年者」「外国人」「死亡退職」「災害者」「乙欄」「本人が障害者（特別・その他）」「寡婦」「ひとり親」「勤労学生」の欄があることを確かめた（public-sources §5.4）。
- e-Gov のキーワード検索の対象が「本文の全文」か、附則・別表を含むかは、API の説明で確認していない。

## 訂正の記録

この文書は 2026-11-09 の独立検証で訂正された。訂正の内容と根拠は実測 `docs/measurements/20261109_impl-prep_misc-verification.md`（§2）を参照。

訂正した節：§2.2 の注、§3.2 の表。
