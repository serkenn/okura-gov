# 実測：地法313⑪ の要件・必要書類、第一表の給与の区分、特定支出に関する明細書（KOB070）、第二表「特例適用条文等」の取得と検証（impl-research9）

- 実施日：2026-11-12。公開資料の情報：`docs/public-sources/20261112_impl-research9_tokutei-jumin-sources.md`。
- Python：`C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8`（標準ライブラリだけ）。リポジトリのルートで実行。
- ダウンロードは毎回新しい空のディレクトリ（`.work/downloads/<YYYYMMDD-HHMMSS>_<名前>/`）。中では何も実行していない（読むだけ）。リクエストの間は 1.5 秒、User-Agent `okura-gov-research/0.1`、robots.txt を確かめた。

## 1. 条文（e-Gov 法令API v2）

| 手順 | コマンド | 結果 |
|---|---|---|
| 法令名で law_id を探す | `scripts/IMPL9_tokutei-jumin_egov.py find 地方税法施行規則`（国税通則法も） | 地方税法施行規則 329M50000002023、国税通則法 337AC0000000066（`scripts/results/IMPL9_tokutei-jumin_egov/find_*.json`） |
| 取得 | `scripts/IMPL9_tokutei-jumin_egov.py fetch`（施行令は後から `fetch chihorei`） | `.work/downloads/20261112-164703_IMPL9_tokutei-jumin_egov/`（8件）・`20261112-164859_…`（2件）、全部 200。`fetch_log_*.json` |
| 取り出し | `scripts/IMPL9_tokutei-jumin_egov.py extract .work/downloads/20261112-164703_IMPL9_tokutei-jumin_egov .work/downloads/20261112-164859_IMPL9_tokutei-jumin_egov` | `scripts/results/IMPL9_tokutei-jumin_egov/`：`<略称>_<asof>.txt`（地方税法 32・313、所得税法 5・7・92・120・121、国税通則法 15・16）、`grep_<略称>_<asof>.txt`（地方税法：納税義務を負わない・所得税につき・特定支出、施行令：納税義務を負わない・特定支出、施行規則：特定支出・第三百十三条第十一項・第三十二条第十一項）、`sames.json` |

- `sames.json`：地方税法の第32条・第313条は版の間で違う（第12項だけ。第11項は同じ：検証 A6）、所得税法は第120条が違う、国税通則法は第15条が違う（引用した文言は両版にある：検証 A9・A10）。
- 所得税法の `## Num=92`（配当控除）は本文が空で出た（テキスト化の都合。確かめていない。結論に使っていない）。

## 2. 国税庁・e-Tax の資料

| 手順 | コマンド | 結果 |
|---|---|---|
| 手引き・記入要領・記載例・明細書 | `scripts/IMPL9_tokutei-jumin_web.py nta` | `.work/downloads/20261112-165125_IMPL9_tokutei-jumin_web_nta/`（5件、全部 200）。手引き 3-2_06 のテキスト `scripts/results/IMPL9_tokutei-jumin_web/nta/tebiki_2025_3_2_06.txt` |
| e-Tax 仕様のページ | `scripts/IMPL9_tokutei-jumin_web.py etax etax2` | `shiyo/index.htm`（200）、`shiyo/shiyo3.htm`（**404**）、`shiyo/ksk2/ksk2_shiyo3.htm`（仕様書一覧。200） |
| e-Tax 仕様書（CAB） | `scripts/IMPL9_tokutei-jumin_web.py etax3` | `.work/downloads/20261112-165213_IMPL9_tokutei-jumin_web_etax3/e-tax07.cab`（9,340,285 バイト）・`e-tax09.cab`（8,509,024 バイト） |
| PDF の文字 | `scripts/IMPL9_tokutei-jumin_pdftext.py kinyu001_1=<001-1.pdf> kinyuO1_1=<O1-1.pdf> kisairei_kyuyo=<kyuyo.pdf> yoshiki039=<039.pdf>`（パスは上の nta のダウンロード先） | `scripts/results/IMPL9_tokutei-jumin_pdftext/<名前>_text.tsv`・`summary.json`。処理は `IMPL8_tokutei-shishutsu_pdftext.py` をファイルのパスで読み込み、出力先だけを変えた |
| CAB の一覧 | `scripts/IMPL9_tokutei-jumin_cab.py list <e-tax07.cab> <e-tax09.cab>` | `list_e-tax07.tsv`（207 ファイル）・`list_e-tax09.tsv`（58 ファイル）。どちらも1フォルダ・MSZIP |
| CAB の展開 | `scripts/IMPL9_tokutei-jumin_cab.py extract <e-tax09.cab> 所得-申告`、`… extract <e-tax07.cab> 対象帳票一覧（申告）` | `.work/downloads/20261112-165312_IMPL9_tokutei-jumin_cab/`（46 件）・`20261112-165614_IMPL9_tokutei-jumin_cab/`（25 件）。展開した大きさは CFDATA の値と一致（一致しなければ止まる） |
| 語で探す | `scripts/IMPL9_tokutei-jumin_cab.py grep <展開先> 特定支出`、`… 所得金額調整控除 特例適用条文`、`… KOB070 特定支出` | `grep_20261112-165341.tsv`（KOB070 のシートだけ）・`grep_20261112-165551.tsv`・`grep_20261112-165619.tsv` |
| シートを TSV に | `scripts/IMPL9_tokutei-jumin_cab.py sheet <帳票フィールド仕様書(所得-申告)Ver7x.xlsx> field_Ver7x`、同 Ver23x → `field_Ver23x`、`<対象帳票一覧（申告）Ver7x.xlsx> taisho_Ver7x` | `.work/etax_spec_extract/IMPL9_tokutei-jumin_cab/field_Ver7x.tsv`・`field_Ver23x.tsv`・`taisho_Ver7x.tsv`（先頭行に元の xlsx の SHA-256） |

- CAB は標準ライブラリで読んだ（CFHEADER・CFFOLDER・CFFILE を解析し、MSZIP の各ブロック〔'CK'＋deflate〕を前のブロックの出力を辞書にして zlib で展開。xlsx は zipfile と ElementTree で読んだ）。
- 明細書 039.pdf の SHA-256 は impl-research8 の取得と同じ（`f4d2a144…`。検証 C6）。
- 記入要領 001-1.pdf・O1-1.pdf は大部分の文字が ToUnicode のないフォントで、文字にできなかった。

## 3. 検証

`scripts/IMPL9_tokutei-jumin_verify.py`（ネットワークを使わない。結果 `scripts/results/IMPL9_tokutei-jumin_verify/checks.json`）。2026-11-12 の実行で **37 件すべて OK**：

1. A1〜A6：地法313⑪・32⑪ の文言と申告書の条（両版）、313③ の「納税義務を負わないと認められたこと」、「納税義務を負わない」を含む条は 32・72の49の12・313・317の2 だけ、317の2① ただし書、313⑪・32⑪ が両版で同じ。
2. A7：地方税法施行令に「納税義務を負わない」「特定支出」を含む条がない（両版）。
3. A8〜A10：所法5①、所法120①「所得税の額の合計額が配当控除の額を超えるとき」、通則法15①（納税義務の定義）・15②一（暦年の終了の時）。
4. B1・B2：地方税法施行規則第1条の12 の本文（両版）、施行規則で「特定支出」を含む条はそれだけ。
5. C1〜C3・C7：手引き 3-2_06 の ㋔ の区分（所得金額調整控除 1・2・3）と ⑥ の区分（明細書の区分番号）の文言、Step3 の (1)・(2)、版（Last-Modified・SHA-256）。
6. C4〜C6・E1：明細書の【区分 n】の番号（1・256・2・4・8・16・32・64・128）、⑥ の区分へ書く注記、⑪ を第二表「特例適用条文等」に書く注記、SHA-256。
7. D1〜D5・E2：対象帳票一覧の KOB070 7.0、KOB070 の ⑪〜⑱ の項目名・XML タグ・⑫ の範囲 0≦x≦511・⑰⑱ の計算、KOA020 23.0 の給与の区分 2つ（1≦x≦3・1≦x≦511）、第二表「特例適用条文等」ABF00000。

## 4. Web 検索（探索だけ。根拠にしていない）

総務省の取扱通知・313⑪ の改正の説明を探すため、Web 検索を4回行った（2026-11-12。語：「地方税法の施行に関する取扱いについて 市町村税関係 特定支出控除 前年分の所得税につき納税義務を負わない」ほか）。
特定支出・313⑪ を説明した総務省の資料は見つからなかった（公開資料の情報 §2.3）。e-Tax の様式ID・手引きの URL を探すのにも使った（見つけた資料は上の表のとおりスクリプトで取得した）。

## 5. 取れなかったもの

- 総務省の取扱通知の全文・313⑪ の説明資料。
- 明細書 1面の下の8字（⑥ の区分へ書く欄の名前）と、記入要領 001-1.pdf の本文（ToUnicode のないフォント）。
- 手引きの説明 038.pdf（今回は取得していない。impl-research8 で文字にできなかった）。
