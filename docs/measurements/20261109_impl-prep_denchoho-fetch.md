# 実装前調査：電子帳簿保存法と記録の保存 — 取得と比較の実測

- 作成日：2026-11-09
- 作業の群（title1）：`impl-prep`（実装前の追加調査）。トピック：`denchoho`
- 種類：実測（スクリプトを実行して得た結果。条文や資料の**内容**の整理は公開資料の情報 `docs/public-sources/20261109_impl-prep_denchoho-requirements.md`）
- 実行環境：Windows 11、`C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8`（標準ライブラリのみ）

## 0. 根拠（再実行の方法）

| スクリプト | 何をするか | 出力 |
|---|---|---|
| `scripts/IMPL_denchoho_laws.py` | e-Gov 法令API v2 の `/law_data/{law_id}?asof=...` で、電子帳簿保存法（410AC0000000025）・同施行規則（410M50000040043）・所得税法（340AC0000000033）・所得税法施行規則（340M50000040011）を複数の時点で取得し、指定した条・附則を取り出す。隣り合う時点の差分、`/law_revisions` の版の一覧、所得税法施行規則の本則の正規表現検索（条番号の確認用）も出す | `scripts/results/IMPL_denchoho_laws/`（`<略称>_<asof>.txt`、`diff_*.diff`、`grep_*.txt`、`index_*.txt`、`revisions_*.json`、`fetch_log.json`） |
| `scripts/IMPL_denchoho_nta.py <stage>` | 国税庁サイトの電子帳簿保存法関係のページ・PDF・docx・xlsx を段階（`discover` → `pages` → `docs` → `samples` → `docs2`）ごとに取得。HTML は本文とリンクをテキスト化、docx・xlsx は zip の中の XML から文字だけを取り出す（展開・マクロ実行はしない）。PDF はテキスト化せず保存だけ（Read ツールの pages 指定で読んだ） | `scripts/results/IMPL_denchoho_nta/<stage>/`（`*.txt`、`*.links.tsv`、`fetch_log.json`） |

- 取得したもの（信頼できないデータ）は実行ごとに新しいディレクトリへ置いた。`.work/` は git 管理外なので、検証するときはスクリプトを再実行する（版・SHA-256 は下の表と `fetch_log.json` で照合できる）。
  - 法令：最終実行 `.work/downloads/20261109-150823_denchoho_laws/`（JSON 24 個）。それ以前の `20261109-145202_denchoho_laws/`（asof 2027-01-01 なし）と `20261109-145338_denchoho_laws/`（施行規則第5条なし）は、asof と条を足す前の実行。結果ファイル（`scripts/results/IMPL_denchoho_laws/`）は最終実行で上書きした
  - 国税庁：`.work/downloads/20261109-145606_denchoho_nta_discover/`、`20261109-145634_denchoho_nta_pages/`、`20261109-145723_denchoho_nta_docs/`、`20261109-145826_denchoho_nta_samples/`、`20261109-152013_denchoho_nta_docs2/`
- リクエストの間は 1.5 秒。User-Agent は `okura-gov-research/0.1`。送ったのは URL だけ（個人の情報は送っていない）。

## 1. e-Gov 法令API：時点ごとの版（`scripts/results/IMPL_denchoho_laws/fetch_log.json`、取得 2026-11-09 15:08）

| 略称 | asof | law_revision_id | 版の施行日 | 状態 | JSON の SHA-256（先頭16桁） |
|---|---|---|---|---|---|
| 電帳法 | 2021-12-31 | 410AC0000000025_20200401_502AC0000000008 | 2020-04-01 | PreviousEnforced | f9e97b2fcc0dff83 |
| 電帳法 | 2022-01-01 | 410AC0000000025_20220101_503AC0000000011 | 2022-01-01 | PreviousEnforced | 9b39bb906435d30a |
| 電帳法 | 2023-12-31・2024-01-01 | 410AC0000000025_20220401_502AC0000000008 | 2022-04-01 | PreviousEnforced | 30e7cc2c0947eaaf |
| 電帳法 | 2025-12-31・2026-11-09・2026-12-31 | 410AC0000000025_20250401_507AC0000000013 | 2025-04-01 | CurrentEnforced | 81885682cdf2beae |
| 電帳法 | 2027-01-01 | 410AC0000000025_20270101_507AC0000000013 | 2027-01-01 | **UnEnforced** | e3da96443d6cd7d8 |
| 電帳法施行規則 | 2021-12-31 | 410M50000040043_20210401_503M60000040025 | 2021-04-01 | PreviousEnforced | 1743d408c4174f5c |
| 電帳法施行規則 | 2022-01-01 | 410M50000040043_20220101_503M60000040025 | 2022-01-01 | PreviousEnforced | 8c2f069bde01fcce |
| 電帳法施行規則 | 2023-12-31 | 410M50000040043_20220401_504M60000040028 | 2022-04-01 | PreviousEnforced | f06131450c2e719c |
| 電帳法施行規則 | 2024-01-01 | 410M50000040043_20240101_505M60000040022 | 2024-01-01 | PreviousEnforced | e28b37677115730e |
| 電帳法施行規則 | 2025-12-31・2026-11-09・2026-12-31 | 410M50000040043_20250401_507M60000040028 | 2025-04-01 | CurrentEnforced | 15786f1ae7140c2a |
| 電帳法施行規則 | 2027-01-01 | 410M50000040043_20270101_507M60000040028 | 2027-01-01 | **UnEnforced** | 5138459ca02073b7 |
| 所得税法 | 2025-12-31 | 340AC0000000033_20251218_507AC0000000013 | 2025-12-18 | PreviousEnforced | 84a2235cb4437184 |
| 所得税法 | 2026-11-09 | 340AC0000000033_20261001_507AC0000000070 | 2026-10-01 | CurrentEnforced | 94c4a7ad83726cde |
| 所得税法 | 2026-12-31 | 340AC0000000033_20261201_508AC0000000012 | 2026-12-01 | UnEnforced | 47792299f0fb5a74 |
| 所得税法施行規則 | 2025-12-31 | 340M50000040011_20251201_507M60000040018 | 2025-12-01 | PreviousEnforced | 16358c775e2d1dcc |
| 所得税法施行規則 | 2026-11-09 | 340M50000040011_20261001_507M60000040018 | 2026-10-01 | CurrentEnforced | 8721699516ac8202 |
| 所得税法施行規則 | 2026-12-31 | 340M50000040011_20261211_508M60000040017 | 2026-12-11 | UnEnforced | 9ba37bf34afed1f9 |

- `/law_revisions`（`revisions_denchou.json`、`revisions_denchou-ki.json`）にも、電帳法・同施行規則それぞれに施行日 2027-01-01・状態 `UnEnforced` の版（令和7年法律第13号、令和7年財務省令第28号）があった。asof に 2026-12-31 を指定してもこの版は返らず、2027-01-01 を指定して初めて返った。
- 2023-12-31 と 2024-01-01 の電帳法（法律）は同じ版（JSON の SHA-256 も一致）。`revisions_denchou.json` の版の一覧にも、令和5年の法律による版は無い（2024-01-01 の変更は施行規則の版だけに現れる）。

## 2. 差分の実測（取り出した条だけの比較。`diff_<略称>_<asof1>_vs_<asof2>.diff`）

| 比較 | 結果 |
|---|---|
| 施行規則 2021-12-31 → 2022-01-01 | 条の構成が入れ替わる。2022-01-01 版で第4条が「電子取引の取引情報に係る電磁的記録の保存」になり、第1項第2号に「保存を行う者又はその者を直接監督する者に関する情報を確認することができるようにしておくこと」が付く。第2条第1項（法第4条第1項の財務省令で定める帳簿＝正規の簿記によらない帳簿）もこの版から現れる |
| 施行規則 2022-01-01 → 2023-12-31 | タイムスタンプの認定主体が「一般財団法人日本データ通信協会」から「総務大臣が認定する時刻認証業務」へ（第2条第6項第2号ロ）。第4条の文言は変わらない |
| 施行規則 2023-12-31 → 2024-01-01 | 第4条第1項の検索要件の免除が「売上高が**千万円**以下…（ダウンロードの求めに応じる場合）」から「売上高が**五千万円**以下…又は出力書面（日付・取引先ごとに整理）の提示等に応じる場合で、ダウンロードの求めに応じるとき」へ。第1項第2号の「保存を行う者…に関する情報」の要件が削られる。第3項に「相当の理由」による猶予が加わる。第2条第6項の号番号が1つずつ繰り上がる（旧第3号「入力を行う者…に関する情報」の削除） |
| 施行規則 2024-01-01 → 2025-12-31 | 第2条第9項第1号の「第二条第十五項」→「第二条第十六項」（番号法の項ずれ）だけ。**第4条は同じ** |
| 施行規則 2025-12-31 → 2026-11-09 → 2026-12-31 | 差分なし（同じ版） |
| 施行規則 2026-12-31 → 2027-01-01 | 第5条の項が組み替わり（旧第5項→第4項など）、第5条第5項に法第8条第5項の財務省令で定める要件（特定電子計算機処理システム等）が入る。第4条第1項は「以下この項及び第三項**並びに次条第五項第一号**において同じ。」の追加だけ |
| 電帳法 2026-12-31 → 2027-01-01 | 第8条第5項（重加算税の10%加重）に、要件を満たす「特定電磁的記録」を加重の対象から除く括弧書きが入る。第7条は同じ |
| 所得税法 2025-12-31 → 2026-11-09 | 取り出した条（120・143・148・232。指定した 231_2 はどの時点の本則にも無く、出力は「見つからない」）のうち、第120条第4項第2号の「社会保険診療報酬支払基金」→「医療情報基盤・診療報酬審査支払機構」だけ。第148条・第232条は同じ |
| 所得税法 2026-11-09 → 2026-12-31 | 取り出した条に差分なし |
| 所得税法施行規則 2025-12-31 → 2026-11-09 → 2026-12-31 | 第63条・第102条に差分なし（差分は源泉徴収関係の別の条だけ） |

→ 令和7年分（2025年中）と令和8年分（2026年中）に行う電子取引・作成受領する帳簿書類について、取り出した範囲の条文は同じ（施行規則第4条は 2024-01-01 版の文言、所得税法施行規則第63条・第102条も同じ）。

## 3. 条番号の確認（`grep_shotoku-ki_2026-11-09.txt`、`grep_shotoku_2026-11-09.txt`）

- 所得税法施行規則の本則を「七年間」「五年間」「保存しなければならない」「帳簿を備え」「雑所得を生ずべき業務」で検索し、帳簿書類の保存期間を定める条が第63条（青色申告者の帳簿書類の整理保存）と第102条（事業所得等に係る取引に関する帳簿の記録の方法及び帳簿書類の保存）であることを、見出しと本文で確認した（他の該当条は金融機関・源泉徴収関係）。
- 所得税法の本則で「帳簿」「雑所得を生ずべき業務」「保存しなければならない」に当たる条のうち、個人の記帳・保存義務を定めるのは第148条と第232条（見出しで確認）。第120条第6項（収支内訳書の添付）も「雑所得を生ずべき業務」で当たった。

## 4. 国税庁サイトの取得（`scripts/results/IMPL_denchoho_nta/*/fetch_log.json`、取得 2026-11-09）

| key | URL | HTTP | バイト | Last-Modified | SHA-256 |
|---|---|---|---|---|---|
| robots | https://www.nta.go.jp/robots.txt | 200 | 853 | 2026-03-18 | a5f4e421e5bb2b20563fa568d7ee4d7c6a41afa72ef8bb96cd35510ebe6d8528 |
| jirei-index | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/index.htm | 200 | 4733 | 2024-06-28 | 5614fc64a1a68809ae674f07c57c7c78db6cdbded4993cb3b10014aaad1df297 |
| tokusetsu-index | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/tokusetsu/index.htm | 200 | 7112 | 2026-10-13 | be3334466490328576dcd01c37d0c62c990f34f1bb92d0d059dee4fbe302977b |
| qa-index | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/4-3.htm | 200 | 6055 | 2026-07-10 | d446346f54669276113e0235ade0e509c734d7909bc0eda3eb32bd7379bd350c |
| hourei-tsutatsu | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/03.htm | 200 | 7773 | 2026-04-06 | e32d9b442b17e21ca43010102d6b1b819abb8fa1978aa7cd5f0c8d09bd172d4f |
| pamphlet | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/08.htm | 200 | 6793 | 2026-06-26 | fd744d027707e2dec2c9420726b39cf3d6020553e602edfe013755f438e3f634 |
| tokusetsu-01（電子取引関係） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/tokusetsu/01.htm | 200 | 9880 | 2026-07-03 | eb2ec1ce784d220456f2ba46dc4bfe1a70a72b04fdda30dcb24bb86a36076e2c |
| tokusetsu-02（電子帳簿・電子書類関係） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/tokusetsu/02.htm | 200 | 10367 | 2026-06-26 | d581534ebdb4a66a758c760e9061ca4d9bfde0e9a0754ec2acd3e45c49222181 |
| qa-dentori-r0807（一問一答【電子取引関係】令和8年7月、PDF） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/pdf/0026007-006_05.pdf | 200 | 1716744 | 2026-07-10 | 5068fb54a2600a278e1da8d685daad39044c0257d09629b6a153c2186141e911 |
| qa-dentori-r0807-diff（同 変更箇所下線あり） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/pdf/0026007-006_06.pdf | 200 | 1727800 | 2026-07-10 | e53c593218d0f873d95507269bf416c8e5e92ce562c8e61099fcde17888e589e |
| qa-chobo-r0807（一問一答【帳簿書類関係】令和8年7月、PDF） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/pdf/0026007-006_01.pdf | 200 | 2944775 | 2026-07-10 | 5a60ec280067d34bcede082ce180c29971afefab8d1222d36331daa274fd2618 |
| tsutatsu-r0706（取扱通達、令和7年6月27日付改正分まで、PDF） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/pdf/0025006-066.pdf | 200 | 491781 | 2025-06-27 | dceaaf0acfd0c1974b3b9047077360d7f63c8cf38e408467acd88666785f82af |
| tsutatsu-kaisetsu-r0706（取扱通達解説、PDF） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/2506/pdf/01-4.pdf | 200 | 842261 | 2025-06-27 | efd7edb0464af88e77b3e495121bd8276face4766f8bccb8a615b6bd5a783917 |
| pamph-dentori-r0611（令和6年11月、PDF） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0024011-003_01.pdf | 200 | 626415 | 2024-11-29 | c25bc2898b9b0a1a71bce6cdc9955a5c9ebf6c6a474375e18e22c20f8de8c9af |
| pamph-dentori-check-r0611（チェックシート、PDF） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0024011-003_02.pdf | 200 | 367405 | 2024-11-29 | 113cb5c9d46874b8e1dda36dee0df92621aad509a38b11c4ac04ef2168307c7b |
| pamph-r7kaisei（令和7年4月、PDF） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/pdf/0025003-097_01.pdf | 200 | 608179 | 2025-04-02 | 671da822d2a7d8724d4dbc81b30e1dac00574ce5996903a2c920e9a2c0930e6d |
| samples-page（各種規程等のサンプル） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/0021006-031.htm | 200 | 4715 | 2026-07-10 | 677fa6476dfd7c83bfccb865101ebe3cbc3aa76273d727c49bd085679d46a705 |
| kitei-kojin（事務処理規程・個人事業者の例、docx） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/word/0021006-031_e.docx | 200 | 17911 | 2024-01-18 | 3a17d85060f1c60ff2b740cf62a17d0dd25eaafd96c3167050d5acd0a60f7684 |
| kitei-hojin（同・法人の例、docx） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/word/0021006-031_d.docx | 200 | 24833 | 2026-07-10 | ed5421413216bb26b6f48b89af1b38b1a0022fb1b34fd0fd77f7be47e277c3f1 |
| sakuinbo（索引簿の作成例、xlsx） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/excel/0021006-031_c.xlsx | 200 | 10403 | 2024-01-18 | ebf39cce4e385f7dba8ed75f91d145153612c99c1053f65a7dec0483f04ac52d |
| pamph-chobo-r0507（帳簿・書類のデータ保存、令和5年7月、PDF） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0023006-085_02.pdf | 200 | 733200 | 2024-01-18 | e8ba06ebf554fecec950eb46b26d77a93b2e59fd17dcc4b8395939a9f5931793 |
| pamph-r0806（令和8年6月、PDF） | https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0026006-122.pdf | 200 | 965128 | 2026-06-26 | b13bcf821f6b641566f3e9650558fd180118f42c51d0513b9289b309057a15a9 |

- robots.txt（2026-11-09 取得）は `User-agent: *` に対して `/service_publication/` と各国税局の `service_publication/` だけを禁止している。取得した URL はどれも禁止の対象外。
- docx からの取り出し（`samples/kitei-kojin.txt`）：本文は「電子取引データの訂正及び削除の防止に関する事務処理規程」（個人事業者の例）。一問一答【電子取引関係】問33 の本文ページ 22（PDF 34 ページ）に載っている同じ題の規程と、段落の文言が一致することを目視で確認した。xlsx（`samples/sakuinbo.txt`）：シート1枚、見出し行 A3:E3 が「連番・日付・金額・取引先・備考」、例の行が3行。A1 は「索引簿（サンプル）サクインボ」と出た（「サクインボ」はふりがなの要素 `rPh` の文字を一緒に拾ったもの。取り出し方の限界）。
- `qa-dentori-r0807-diff`（変更箇所下線あり）は取得したが、令和8年7月版での変更箇所の洗い出しはしていない。
- `tsutatsu-kaisetsu-r0706`（取扱通達解説）は取得したが、読んでいない。

## 5. PDF を読んだ範囲（Read ツールの pages 指定）

| 資料 | 読んだページ（PDF のページ番号） | 対応する本文ページ |
|---|---|---|
| 一問一答【電子取引関係】令和8年7月 | 1–31、34–51、54–56、67–72、74–78 | 目次、問1–問59、問64–問69、問88–問96、問98–問102 |
| 一問一答【帳簿書類関係】令和8年7月 | 2–5、9–20 | 目次、問1–問12 |
| 取扱通達（令和7年6月27日付改正分まで） | 1–10、16–25 | 用語、目次、2-1〜4-15、4-34〜8-12 |
| 令和6年1月以降の電子取引データの保存方法（令和6年11月） | 1–2（全ページ） | |
| 電子取引データ保存要件チェックシート（令和6年11月） | 1（全ページ） | |
| はじめませんか、帳簿・書類のデータ保存（令和5年7月） | 1–2（全ページ） | |
| 電子帳簿等保存制度を活用して…（令和8年6月） | 1–2（全ページ） | |

## 訂正の記録

この文書は 2026-11-09 の独立検証で訂正された。訂正の内容と根拠は実測 `docs/measurements/20261109_impl-prep_denchoho-verification.md` §2 を参照。

- 訂正した節：§2（「所得税法 2025-12-31 → 2026-11-09」の行）
