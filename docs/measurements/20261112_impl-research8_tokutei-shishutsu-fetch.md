# 実測：特定支出控除（所得税法第57条の2）と減免の条文・国税庁の資料の取得と検証（impl-research8）

- 実施日：2026-11-12。公開資料の情報：`docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md`。
- Python：`C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8`（標準ライブラリだけ）。リポジトリのルートで実行。

## 1. 条文（e-Gov 法令API v2）

| 手順 | コマンド | 結果 |
|---|---|---|
| 取得 | `scripts/IMPL8_tokutei-shishutsu_egov.py fetch` | `.work/downloads/20261112-151051_IMPL8_tokutei-shishutsu_egov/`（16 件、全部 200）。取得の記録 `scripts/results/IMPL8_tokutei-shishutsu_egov/fetch_log_20261112-151051.json`（URL・law_revision_id・改正法令・施行日・状態・SHA-256・バイト数） |
| 取り出し | `scripts/IMPL8_tokutei-shishutsu_egov.py extract .work/downloads/20261112-151051_IMPL8_tokutei-shishutsu_egov` | `scripts/results/IMPL8_tokutei-shishutsu_egov/`：`<略称>_<asof>.txt`（指定した条）、`grep_<略称>_<asof>.txt`（「特定支出」を含む条・附則）、`sames.json`（版の間の SHA-256） |

`sames.json` の版の間の違い：所得税法 第28条・第120条（第57条の2 は同じ）、施行令 第167条の3〜第167条の5 は同じ、措置法 第29条の4（条が入れ替わる）、地方税法 第32条・第313条（下の §3）。

## 2. 国税庁の資料

| 手順 | コマンド | 結果 |
|---|---|---|
| 取得（set nta） | `scripts/IMPL8_tokutei-shishutsu_web.py nta` | TA No.1415・所得税基本通達の目次。`scripts/results/IMPL8_tokutei-shishutsu_web/nta/`（`fetch_log_20261112-151556.json`） |
| 取得（set nta2） | `scripts/IMPL8_tokutei-shishutsu_web.py nta2` | 手引きの説明 038.pdf・明細書 039.pdf・証明書の様式の一覧・個人課税課情報 第4号・質疑応答事例 04/32。`.work/downloads/20261112-151625_IMPL8_tokutei-shishutsu_web_nta2/` |
| 取得（set nta3） | `scripts/IMPL8_tokutei-shishutsu_web.py nta3` | 情報の別冊2（解説編）・別冊3（質疑応答編）の PDF。`.work/downloads/<ts>_IMPL8_tokutei-shishutsu_web_nta3/` |
| PDF の文字 | `scripts/IMPL8_tokutei-shishutsu_pdftext.py tebiki038=<038.pdf> yoshiki039=<039.pdf> joho02=<02.pdf> joho03=<03.pdf>` | `scripts/results/IMPL8_tokutei-shishutsu_pdftext/<名前>_text.tsv`・`summary.json`（SHA-256・暗号・頁数・ToUnicode の有無） |

- robots.txt は各ホストで確かめた（取得の記録の `robots`）。リクエストの間は 1.5 秒。
- 手引きの説明（038.pdf、17頁）はフォントの多くに ToUnicode がなく、文字を取り出せなかった（`summary.json`：Type0 フォント 46 のうち 29 に ToUnicode がない）。明細書（039.pdf）・情報の別冊（02・03）は取り出せた。

## 3. 検証

`scripts/IMPL8_tokutei-shishutsu_verify.py`（ネットワークを使わない。結果 `scripts/results/IMPL8_tokutei-shishutsu_verify/checks.json`）。2026-11-12 の実行で 16 件すべて OK：

1. 所法57の2 の本文が asof 2025-12-31 と 2026-12-31 で同じ。
2. 第1項：給与所得控除額の二分の一を超える部分を、第28条第4項にかかわらず第2項の残額から控除する。
3. 第2項第7号の 65万円。第3項の申告書等への記載・添付の要件。キャリアコンサルタントの証明の範囲。
4. 所令167の3 の通勤費（航空機を除く・定期乗車券の価額の合計額が上限）、転居費（転任の日以後1年以内）。所規36の5③ の寝台料金 6,600円。
5. 措法29の4：asof 2025-12-31 は未払賃金の特例（旧条）、asof 2026-12-31 の第3項は所法57の2① の読替え。
6. 措法41の3の11④五 の「給与所得控除後の給与等の金額」の定義。
7. 地法313⑪ が令和8年度分・令和9年度分で同じ文言（版の間で違うのは第12項だけ：`diff` で確かめた）。313②「計算の例」、32⑪、323（減免）。
8. 明細書の「(赤字の場合は０)」の文字が ⑰ の欄の位置にある（y の差 2.4）。

## 4. 取れなかったもの

- 地方税法施行規則（第313条第11項の「総務省令で定める必要な書類」）は取得していない。
- 明細書の ⑱ の計算式の文字（フォントの対応がなく文字化けした）。
- 令和8年分の明細書の様式（未公表）。
