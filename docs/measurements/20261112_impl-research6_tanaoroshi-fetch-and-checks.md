# impl-research6：棚卸資産・家事消費等・貸倒れと様式の残る欄の一次情報の取得と照合（実測）

- 種類：実測。取得と照合のスクリプトと結果。中身の要約は `docs/public-sources/20261112_impl-research6_tanaoroshi-laws-and-nta.md`・
  `docs/public-sources/20261112_impl-research6_forms-tebiki.md`。
- 実施日：2026-11-12。実行は Python 3.11.9（`C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8`、標準ライブラリのみ）、リポジトリのルートで。
- ダウンロードしたものは取得ごとに新しい空のディレクトリ `.work/downloads/<ts>_IMPL6_tanaoroshi_*` に置き、その中では何も実行していない。

## 1. 取得

| スクリプト | 実行 | 出力 |
|---|---|---|
| `scripts/IMPL6_tanaoroshi_laws_egov.py` | `fetch` → `extract .work/downloads/20261112-095723_IMPL6_tanaoroshi_laws_egov` | `scripts/results/IMPL6_tanaoroshi_laws_egov/`（条文の写し・grep・sames.json・fetch_log） |
| `scripts/IMPL6_tanaoroshi_web_fetch.py` | `index`・`tsutatsu tebiki`・`pdf`・`kabu`（2回目以後の URL は `scripts/results/IMPL6_tanaoroshi_web_fetch/sets.json`） | `scripts/results/IMPL6_tanaoroshi_web_fetch/<set>/`（テキスト・リンク・fetch_log） |
| `scripts/IMPL6_tanaoroshi_pdftext.py` | `q7=… q11=… q13=… q15=… t003=… k037=… k034=…`（PDF のパス） | `scripts/results/IMPL6_tanaoroshi_pdftext/`（文字と位置の TSV。取り出しは IMPL4_web_pdftext.py を読み込んで使う） |

e-Gov 法令API v2（`/law_data`、asof の版）：

| 略称 | 版 | 状態 | law_revision_id | SHA-256（先頭16桁） |
|---|---|---|---|---|
| 所得税法 | 2025-12-31 | 200 | 340AC0000000033_20251218_507AC0000000013（PreviousEnforced） | 84a2235cb4437184 |
| 所得税法 | 2026-12-31 | 200 | 340AC0000000033_20261201_508AC0000000012（UnEnforced） | 47792299f0fb5a74 |
| 所得税法施行令 | 2025-12-31 | 200 | 340CO0000000096_20251201_507CO0000000120 | e972344f436ecd9b |
| 所得税法施行令 | 2026-12-31 | 200 | 340CO0000000096_20261201_508CO0000000093 | cd63914bb5962edf |
| 所得税法施行規則 | 2025-12-31 | 200 | 340M50000040011_20251201_507M60000040018 | 16358c775e2d1dcc |
| 所得税法施行規則 | 2026-12-31 | 200 | 340M50000040011_20261211_508M60000040017 | 9ba37bf34afed1f9 |

国税庁（HTTP 200。Last-Modified はサーバーの値）：

| set / id | 中身 | バイト | SHA-256（先頭16桁） | Last-Modified |
|---|---|---|---|---|
| tsutatsu/kihon_06_01 | 所基通39−1〜41の2−1 | 10,655 | a187fd5fffba917a | 2024-01-18 |
| tsutatsu/kihon_08_01・08_02・08_03 | 所基通47−1〜47−25 | 9,883・12,097・5,381 | 9e05e4c32069824f・c93e35924706c6ba・86316129db4a2dd7 | 2025-12-25・2025-11-25・2024-01-18 |
| tsutatsu/kihon_09_02 | 所基通51−10〜51−17 | 9,535 | b26e20744c0f2034 | 2026-10-02 |
| tebiki/t_3_2_01・t_3_3_13・t_3_4_29・t_3_5_01・t_3_6_02 | 手引き 手順2・3・4・5・6 | 15,304・15,879・8,775・13,871・25,957 | ed5db4670985a277・3a8904729a63b8e9・9757b9c56fd2acd4・73d9616d93a901d1・c6132a1a1a2ff91a | 2025-12-24 |
| pdf/tebiki_003_sonshitsu | 確定申告の手引き（損失申告用） | 1,485,553 | e3a89abd687f659d | 2025-12-12 |
| pdf/kakikata_034_shushi・kakikata_037_aoiro | 収支内訳書（一般用）・青色申告決算書（一般用）の書き方 | 1,527,542・2,576,092 | 5ac5dabb0eff0947・77c8ad203bbd04ef | 2025-12-12 |
| kabu/kabu_Q7・Q11・Q13・Q15 | 株式等の譲渡所得等の申告のしかた 記載例 | 1,116,851 ほか | edbb8ae9e5226717・ed6ad99ec7cff7b5・c90c16634f423438・a950cef68938cdbc | 2025-12-12 |

- `pdf/tebiki_002_guess`（`/tebiki/2025/pdf/002.pdf`）は 2,007 バイトのエラーページ（SHA-256 `700138cae1f347c2…`。既知のソフト404と同じ）。分離課税用の手引きの URL は見つからなかった。
- 記載例の PDF（kabu）は申告書の部分が画像で、文字の取り出しで第三表の「特例適用条文」の記入は取れなかった（Q13 の1頁を画像で見たが、第三表は載っていない）。

## 2. 照合

`scripts/IMPL6_tanaoroshi_verify.py`（ネットワークなし）→ `scripts/results/IMPL6_tanaoroshi_verify/checks.json`：

- docs に引用した原文の語句 22 件が、取得した写しに全部あった（`all_found: true`）。
- 版の比較（sames.json）：所得税法は指定した条（2・36・37・39・40・47・51・52・64）のうち第2条だけが 2025-12-31 と 2026-12-31 で違う。施行令（3・86・87・99〜104・140〜142）は同じ。
  → 令和7年分・令和8年分で同じ規則を当てる。
- 期限の曜日（仮説 H2-1・テストの境目）：2021-03-15 月曜、2021-03-16 火曜、2025-03-15 土曜（期限は 2025-03-17 月曜）、2026-03-15 日曜。

## 3. 単体の確かめ

`packages/core/tests/rules/income_kinds/test_inventory.py`（16 件、2026-11-12 に通った）：評価の方法の届出の期限と土日、変更の申請の3月15日と却下、特別な方法の承認の年、
要る方法の評価額がないとき、低価法と青色、業務の2つの方法、期末の棚卸しがないとき（c-入力）、判断（有しない）、期首（前年の期末・その年に開始・分からない）、
死亡の日の期末、家事消費の70%の境目と取得価額、貸倒れの条の当て方と所令180②二の上限。
