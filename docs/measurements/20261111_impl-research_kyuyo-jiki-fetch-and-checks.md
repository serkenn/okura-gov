# 実測：給与所得の収入すべき時期と死亡後に支給期の到来する給与の条文・通達の取得、引用の照合、年分の割当ての設例（impl-research kyuyo-jiki）

- 実施日：2026-11-11
- 種別：実測（スクリプトの実行と結果）。公開資料の内容のまとめは `docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md`。
- 実行環境：`C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8`（標準ライブラリだけ）。リポジトリのルートで実行。
- ダウンロードしたものは実行ごとに新しい空のディレクトリ `.work/downloads/<YYYYMMDD-HHMMSS>_<名前>/` に置き、その中では何も実行していない。PDF は Read ツールで目視した。

## 1. スクリプトと実行の記録

| スクリプト | 何をするか | 出力 | 実行（ダウンロード先） |
|---|---|---|---|
| `scripts/IMPL2_kyuyo-jiki_egov.py` | e-Gov 法令API v2：所得税法 第9条・第28条・第36条・第183条・第190条・第226条（asof 2025-12-31・2026-11-11・2026-12-31・2027-01-01）、相続税法 第3条（2025-12-31・2026-11-11） | `scripts/results/IMPL2_kyuyo-jiki_egov/` | 20261111-110516（`.work/downloads/20261111-110516_IMPL2_kyuyo-jiki_egov/`） |
| `scripts/IMPL2_kyuyo-jiki_nta.py` | 国税庁：`--robots`、組 `pages`（基本通達 5頁・相続税法基本通達・質疑応答事例2件・年末調整のしかたの目次2件）、`pdfs`（年末調整のしかた「Ⅱ 年末調整とは」令和7年分・令和8年分） | `scripts/results/IMPL2_kyuyo-jiki_nta/<組>/` | pages 20261111-110407、pdfs 20261111-110614 |
| `scripts/IMPL2_kyuyo-jiki_checks.py` | 引用の照合と、年分の割当ての設例（ネットワークなし） | `scripts/results/IMPL2_kyuyo-jiki_checks/checks.json` | 最後の実行の出力 |

- 入力として `scripts/IMPL2_tsukin_nta.py pages3` の `tebikihtml_2_3_4.txt`（法定調書の手引 令和8年分 HTML 版「支払金額」欄）も使う（実測 `docs/measurements/20261111_impl-research_tsukin-fetch-and-checks.md` §1）。
- 再実行の手順：`IMPL2_kyuyo-jiki_egov.py` → `IMPL2_kyuyo-jiki_nta.py --robots` → `IMPL2_kyuyo-jiki_nta.py pages pdfs` →（`IMPL2_tsukin_nta.py pages3`）→ `IMPL2_kyuyo-jiki_checks.py`。
- robots.txt：HTTP 200。組を足した後にもう一度判定し、すべての URL が許可（`scripts/results/IMPL2_kyuyo-jiki_nta/robots_check.json` の `all_allowed: true`、最後の判定 20261111-110613）。
- URL の出どころ：所得税基本通達のページは既存の目次の取得（`scripts/results/IMPL_jigyo_nta/ta_index/kihon_shotoku_index.links.json`）から、相続税法基本通達と質疑応答事例は Web 検索の結果から。

## 2. 取得結果

- e-Gov：すべて HTTP 200。law_revision_id は公開資料の情報 §0.1。生データの SHA-256 は `scripts/results/IMPL2_kyuyo-jiki_egov/fetch_log.json`（条ごとの本文の SHA-256 も `article_text_sha256` に記録）。
- 国税庁（すべて HTTP 200）：

| id | Last-Modified | SHA-256 の先頭16桁 |
|---|---|---|
| kihon_05_01 | 2025-11-25 | 6e42d433d5cc2383 |
| kihon_02_04 | 2025-12-25 | d76a85dbe547d975 |
| kihon_04_03 | 2025-11-25 | d7ce1f6b86197bff |
| kihon_28_01 | 2024-01-18 | 6e033afb9ee8fd0a |
| kihon_31_01 | 2024-01-18 | b659cb049b3cefd7 |
| kihon_32_01 | 2025-11-25 | fb9625f6710b048d |
| sokihon_01_03 | 2024-01-18 | 71625e7b6406d740 |
| shitsugi_hotei_7_05 | 2025-12-03 | f90d6ba96ba35e3e |
| shitsugi_hotei_7_16 | 2025-12-03 | 244681805372191f |
| nencho2025_103（PDF） | 2025-08-29 | 9fb3886c2b75515b |
| nencho2026_103（PDF） | 2026-08-31 | 84ddecde830d51ec |

- 目視した PDF：nencho2026_103 の全2頁（年末調整の対象・時期。未払の給与の記載はない）。nencho2025_103 は取得したが読んでいない。法定調書の手引 令和7年分（`tebiki2025_all`、通勤手当の取得で保存）の PDF 4頁（③支払金額）・5頁（⑥源泉徴収税額の注）。
- kihon_04_03（法第28条関係）は取得したが、本書の論点（時期）に関わる記載を探していない。

## 3. 照合（`scripts/results/IMPL2_kyuyo-jiki_checks/checks.json`）

### 3.1 Q 引用の照合

公開資料の情報が引く 22 の文（所法36①・183②・190一・9①十七、相続税法3①二、所基通36−9 の柱書・(1)・(3)・(4)、9−17 と注、183−1、181〜223共−1、190−1(1)・(4)、相基通3−33、質疑応答事例 7/05 の3文・7/16 の1文、手引 令和8年分 HTML の「支払金額」欄）が、取得した本文に空白・改行を除いてそのまま含まれるかを調べた。**22 件すべて一致**。

### 3.2 S 年分の割当ての設例（架空）

(a) 所基通36−9・9−17 の読みを関数にしたもの（`year_by_36_9`。法令の読みで、判定コアの仕様ではない）と、(b) 現在の判定コア（`packages/core/README.md` §6・`situation.py` の docstring：支払日の年、死亡の日以後の支払は対象外）に、10 の設例を当てた。**7 件で結果が違う**。

| 設例 | (a) 36−9・9−17 の読み | (b) 現在の判定コア |
|---|---|---|
| S1 12月分を翌年1月10日に支給（規程の支給日も1月10日） | 2026 | 2026 |
| S2 支給日 12月25日の給与が遅れて翌年1月5日に支払われた | 2025 | 2026 |
| S3 支給日 2026-12-25 の給与が未払 | 2026 | 記録なし（数えない） |
| S4 支給日の定めがなく 2026-12-30 に支払われた | 2026 | 2026 |
| S5 昇給差額。改訂で定めた支給日 2027-01-25 | 2027 | 2027 |
| S6 遡及改訂の差額で支給日の定めなし。改訂の効力 2026-12-01、支払 2027-01-15 | 2026 | 2027 |
| S7 2026-03-15 死亡、支給日 03-25 の給与（相続財産に算入） | 所得税を課さない | 対象外 |
| S8 同（相続財産に算入するか入力なし） | 未確定 | 対象外 |
| S9 2026-03-15 死亡、支給日 02-25 の給与が未払で 03-25 に遺族に支払 | 2026 | 対象外 |
| S10 2026-03-15 死亡、支給日 03-15（死亡日と同日） | 2026（同日は「死亡後」に当たらないとして計算） | 対象外 |

- S10 の (a) は、関数が「支給日が死亡日より後」を死亡後としたことによる。同日を死亡後とするかの一次情報はない（公開資料の情報 §4 の 1）。
- S7 の (b) の「対象外」は安全側の扱いで、値が誤っているわけではない（値を出していない）。違いの数え方は「結果の表示が違う」もの。
