# 第2ラウンド（elderly-abroad）実測：条文・行政資料の取得と、文書の主張の機械的な検査

- 実施日：2026-11-09
- 種別：実測（measurements）。後日、同じスクリプトを実行して検証できるように、手順・出力のパス・版・SHA-256 を書く。
- この実測を根拠にする文書：公開資料の情報 `docs/public-sources/20261109_round2_elderly-abroad-laws.md`（［LW］）、`docs/public-sources/20261109_round2_elderly-abroad-guidance.md`（［GD］）、仮説 `docs/hypotheses/20261109_round2_elderly-abroad-model.md`。
- 環境：Windows 11、`C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8`（標準ライブラリのみ）。User-Agent `okura-gov-research/0.1`、リクエストの間は 1.5 秒。官報は取得していない。

## 1. スクリプトと実行の順序

| 順 | スクリプト | やること | 出力 |
|---|---|---|---|
| 1 | `scripts/R2X_elderly-abroad_web.py robots elderly abroad kenpo` | 国税庁・厚労省・日本年金機構・協会けんぽの HTML・PDF の取得。HTML はテキストとリンクを取り出す | `scripts/results/R2X_elderly-abroad_web/<set>_<ts>.json`、`.../text/<set>_<ts>/<ID>.txt`・`<ID>.links.json` |
| 2 | `scripts/R2X_elderly-abroad_laws.py` | e-Gov 法令API v2 で、所法・所令・所規・措法・措令・地法・地規・健保法・健保則の条文を時点ごとに取得。指定の条、キーワードを含む条（本則・附則）、版の差分 | `scripts/results/R2X_elderly-abroad_laws/articles_*`、`kwhits_*`、`diff_*`、`fetch_log.json` |
| 3 | `scripts/R2X_elderly-abroad_laws.py koukirei` | 高齢者医療確保法 第50条・第51条 | `articles_koukirei_2026-11-09.txt`、`fetch_log_koukirei.json` |
| 4 | `scripts/R2X_elderly-abroad_laws.py chiho-ki` | 地方税法施行規則（asof 2026-01-01 を足した3版） | `kwhits_chiho-ki_*`、`fetch_log_chiho-ki.json` |
| 5 | `scripts/R2X_elderly-abroad_checks.py` | 1〜4 の出力（テキスト）を読み、文書の主張を検査（ネットワークに接続しない） | `scripts/results/R2X_elderly-abroad_checks/checks.json`、`checks.md` |

- ダウンロードした生データは `.work/downloads/<ts>_R2X_elderly-abroad_<set>/`・`.work/downloads/<ts>_R2X_elderly-abroad_laws/` に置いた（実行ごとに新しい空のディレクトリ。中では何も実行していない。`.work/` はコミットしない）。PDF は Read ツールで人が読んだ。
- 記録の注意：2 は対象の条を足しながら3回実行した（20261109-173806、20261109-174242、20261109-175024）。`fetch_log.json` と `articles_*`・`diff_*`・`kwhits_*`（chiho-ki 以外）は最後の 20261109-175024 の実行のもの。chiho-ki は 4（20261109-175600）、koukirei は 3（20261109-175259）の出力。3回の実行で各版の law_revision_id は同じだった。

## 2. 取得の記録

### 2.1 e-Gov 法令API v2（`fetch_log.json`・`fetch_log_koukirei.json`・`fetch_log_chiho-ki.json`。SHA-256 は生の JSON の先頭16桁。全桁は各ログ）

| 略称 | asof | law_revision_id | 状態 | SHA-256（先頭16桁） | バイト |
|---|---|---|---|---|---|
| shotoku | 2025-12-31 | 340AC0000000033_20251218_507AC0000000013 | PreviousEnforced | 84a2235cb4437184 | 16,394,130 |
| shotoku | 2026-11-09 | 340AC0000000033_20261001_507AC0000000070 | CurrentEnforced | 94c4a7ad83726cde | 16,405,085 |
| shotoku | 2026-12-31 | 340AC0000000033_20261201_508AC0000000012 | UnEnforced | 47792299f0fb5a74 | 16,399,400 |
| shotoku-rei | 2025-12-31 | 340CO0000000096_20251201_507CO0000000120 | PreviousEnforced | e972344f436ecd9b | 3,591,986 |
| shotoku-rei | 2026-11-09 | 340CO0000000096_20260522_508CO0000000093 | CurrentEnforced | 9facf2e2768d602c | 3,613,582 |
| shotoku-rei | 2026-12-31 | 340CO0000000096_20261201_508CO0000000093 | UnEnforced | cd63914bb5962edf | 3,628,859 |
| shotoku-ki | 2025-12-31 | 340M50000040011_20251201_507M60000040018 | PreviousEnforced | 16358c775e2d1dcc | 2,326,379 |
| shotoku-ki | 2026-11-09 | 340M50000040011_20261001_507M60000040018 | CurrentEnforced | 8721699516ac8202 | 2,351,567 |
| shotoku-ki | 2026-12-31 | 340M50000040011_20261211_508M60000040017 | UnEnforced | 9ba37bf34afed1f9 | 2,356,623 |
| sochi | 2025-12-31 | 332AC0000000026_20251231_507AC1000000081 | PreviousEnforced | ef95d90f7bf57e18 | 14,344,538 |
| sochi | 2026-11-09 | 332AC0000000026_20261101_507AC0000000013 | CurrentEnforced | e6e6013bbc0608c6 | 14,512,569 |
| sochi | 2026-12-31 | 332AC0000000026_20261204_508AC0000000012 | UnEnforced（amendment_enforcement_date は null） | 763fce2df2b1e709 | 14,524,288 |
| sochi-rei | 2026-11-09 | 332CO0000000043_20261101_507CO0000000127 | CurrentEnforced | d0ad21a838fd3d2a | 13,874,873 |
| chiho | 2026-01-01 | 325AC0000000226_20260101_507AC0000000041 | PreviousEnforced | ba0a40e550be7762 | 12,431,689 |
| chiho | 2026-11-09 | 325AC0000000226_20261101_508AC0000000002 | CurrentEnforced | 3dd29e0078bf24e0 | 12,181,725 |
| chiho | 2027-01-01 | 325AC0000000226_20270101_508AC0000000002 | UnEnforced | ee21722ce5fd1561 | 12,224,062 |
| chiho-ki | 2026-01-01 | 329M50000002023_20260101_507M60000008116 | PreviousEnforced | 285e203a423a4fee | 4,510,007 |
| chiho-ki | 2026-11-09 | 329M50000002023_20261101_508M60000008045 | CurrentEnforced | 5ffb833bd3a3d7c4 | 4,187,088 |
| chiho-ki | 2027-01-01 | 329M50000002023_20270101_508M60000008089 | UnEnforced | e8d5c022315165a3 | 4,199,705 |
| kenpo | 2025-12-31 | 211AC0000000070_20251212_507AC0000000087 | PreviousEnforced | 9fa3c76cdce41f50 | 1,305,708 |
| kenpo | 2026-11-09 | 211AC0000000070_20261001_507AC0000000087 | CurrentEnforced | cf30a71b955ff7ce | 1,400,173 |
| kenpo-ki | 2025-12-31 | 215M10000008036_20251201_507M60000100118 | PreviousEnforced | 4da35489daa9facf | 1,386,386 |
| kenpo-ki | 2026-11-09 | 215M10000008036_20261001_508M60000100144 | CurrentEnforced | 955fb551d8f41a87 | 1,423,977 |
| koukirei | 2026-11-09 | 357AC0000000080_20261001_507AC0000000087 | CurrentEnforced | 54c58f6fd8b00317 | 1,064,676 |

### 2.2 行政資料（`scripts/results/R2X_elderly-abroad_web/<set>_20261109-173918.json`）

すべて HTTP 200（協会けんぽの robots.txt だけ 404）。「テキスト SHA-256」は取り出したテキストの先頭16桁（協会けんぽの HTML は取得ごとにスクリプトが変わるので、変化の検知はテキストの値で行う：［PS-K］§7-10 の既存の実測）。

| セット | ID | Last-Modified | 生データ SHA-256（先頭16桁） | バイト | テキスト SHA-256 |
|---|---|---|---|---|---|
| elderly | ta_1180 | 2026-09-09 | c92803d8c75aa5c7 | 23,283 | 449f2938072747d8 |
| elderly | ta_1180_qa | 2026-09-09 | 02839cb155836ab2 | 22,492 | 257e286ee749ad47 |
| elderly | ta_1182 | 2026-09-09 | 7d8798cf92be99aa | 18,127 | 6343e3fe33ce95d8 |
| elderly | shitsugi_shotoku_05_32 | 2025-12-03 | 2965b2556536016e | 4,595 | 423b0f40e51ddfdc |
| elderly | tebiki2025_yogo_y11 | 2025-12-24 | b0ec5aceb7d6f7ce | 7,497 | 620ded4061ff6ad8 |
| elderly | tebiki2025_yogo_y12 | 2025-12-24 | 01f0cf853cc5db67 | 7,621 | 6b793bb1dcfa7743 |
| elderly | tebiki2025_3_3_27 | 2025-12-24 | fe99421d6c179946 | 19,779 | bda66e2e3d234bae |
| elderly | sochiho_tsutatsu_toc | 2026-10-02 | fd1a8ce56f916aef | 77,279 | 09eb49314912b45c |
| elderly | kihon_tsutatsu_2_1 | 2024-01-18 | 6d7d6ba43294e00a | 6,682 | 345ceabc60791868 |
| elderly | kihon_tsutatsu_2_47 | 2026-10-02 | 52d60882df0b13f9 | 18,408 | 30d1e3031b6ab2d4 |
| elderly | nencho2026_105（PDF） | 2026-09-24 | 9460af44b13c8651 | 1,063,580 | — |
| elderly | nencho2025_105（PDF） | 2025-09-03 | f69eda756f726c1a | 1,077,260 | — |
| abroad | kokugai_index | 2026-03-27 | 65d6cab24c19c3f6 | 10,081 | c8cfffb363e05c6d |
| abroad | kokugai_sokin | 2026-03-27 | 15cfec2296cdaa52 | 11,486 | cfe638202799d522 |
| abroad | kokugai_qa_pdf（PDF） | 2026-08-31 | d8e5bc32f793e7ba | 712,232 | — |
| abroad | kokugai_leaf_pdf（PDF、未読） | 2025-06-30 | 5972507540b2233e | 148,124 | — |
| abroad | r2kaisei_pdf（PDF、未読） | 2024-01-18 | c4ee24b9989af4ec | 593,588 | — |
| kenpo | S52_tsuchi | なし | 3a0aec4d588447f7 | 7,871 | 4946d39337e46050 |
| kenpo | R01_kokunai | なし | 8c7a41bd8eb8937a | 44,339 | 3eb24bfa367ec588 |
| kenpo | R05_kokunai_kaisei | なし | a333fbd3a7355dd4 | 46,263 | 5cd8222c56ec3730 |
| kenpo | nenkin_kyojuyoken | 2026-10-14 | 45b5e40122ec0a3d | 35,956 | 4e5eccafe11521af |
| kenpo | nenkin_20200324（未読） | 2026-10-14 | c7e0b058def09b7f | 30,243 | 09d2f1dd65b84b34 |
| kenpo | nenkin_20141202 | 2026-10-14 | e090abd4c5550dfc | 46,959 | 01fb9d992d0d8622 |
| kenpo | kyoukai_guide2607（PDF） | 2026-06-23 | c655715c25266bee | 1,283,035 | — |
| kenpo | kyoukai_faq_dependent | なし | 28b63c1dee5c547a | 71,028 | 52ba098fbe9c0a42 |

- robots.txt（`robots_20261109-173918.json`）：国税庁は `/service_publication/` などだけを Disallow、厚労省は `/cgi-bin/`・`/images/` など、日本年金機構は特定の PDF 1件だけ。今回の取得先は含まれない。協会けんぽは robots.txt が 404（ページなし）。
- 協会けんぽ FAQ のテキスト SHA-256（52ba098fbe9c0a42）は、既存の実測の値（［PS-K］§7-10）と同じだった。
- 「テキスト SHA-256」は、`scripts/R2X_elderly-abroad_web.py` がメモリ上のテキストについて計算した値（取得記録の `text_sha256`）。保存した `text/<set>_<ts>/<ID>.txt` は `pathlib.write_text` で書かれており、Windows では改行 LF が CRLF に変換されている（国税庁の HTML のように元のテキストが CR を含むものは CR CR LF になる）。ファイルから再計算するときは、バイト列を読んで CRLF を LF に1回だけ戻してから SHA-256 を取る。universal newline（`read_text`）で読んで計算すると、国税庁の9件（ta_1180・ta_1180_qa・ta_1182・shitsugi_shotoku_05_32・tebiki2025_yogo_y11・tebiki2025_yogo_y12・tebiki2025_3_3_27・sochiho_tsutatsu_toc・kihon_tsutatsu_2_47）は表の値と一致しない。

## 3. 検査の結果（`scripts/R2X_elderly-abroad_checks.py` → `checks.json`、**67件中67件 OK**）

| 区分 | 検査の内容（要約） | 結果 |
|---|---|---|
| 所得税法 | 所法2①三十四の四（70歳以上）、84①（老人扶養48万円）が asof 2025-12-31・2026-11-09・2026-12-31 の3版にある | OK（6件） |
| 所得税法 | 所法2①三十四の所得要件：五十八万円・五十八万円・六十二万円 | OK |
| 所得税法 | 所法2①三十四の二（非居住者の区分）、120③（確定申告の書類）、85③（12月31日）、3（公務員のみなし）が3版で同文 | OK（4件） |
| 所得税法 | 所法194⑤〜⑦：2026-11-09 と 2026-12-31 は同文。2025-12-31 との違いは「控除対象扶養親族」→「源泉控除対象親族」の語の置き換えだけ | OK（2件） |
| 所得税法施行令・規則 | 所令13・14・15・262 が3版で同文。所規47の2⑤〜⑩（親族関係書類等の定義）が3版で同文 | OK（5件） |
| 措置法 | 措法41の16 が3版で同文。①に「直系尊属」「同居を常況としている者」「十万円を加算」 | OK（2件） |
| 「同居老親等」の語 | 所法・所令・所規・措法・措令の本則・附則（取得した全版）のキーワード一覧に「同居老親等」が出ない | OK（13件） |
| 地方税法 | 地法314の2①十一（33万・45万・38万、非居住者の区分）、④（同居直系尊属45万円）、⑧（前年12月31日）、34④（道府県民税45万円）、314の6（調整控除 老人扶養10万円・同居直系尊属13万円）が asof 2026-01-01・2026-11-09・2027-01-01 の各版にある | OK（15件） |
| 算術 | 48万＋10万＝58万。所得税と住民税の差 48万−38万＝10万、58万−45万＝13万が、地法314の6 の表の額と一致 | OK（2件） |
| 地方税法施行規則 | 地規2の2 に「国外居住者」「控除対象外国外扶養親族」を定義する項が3版にある（項番号は 2026-01-01・2026-11-09 で第4項・第6項、2027-01-01 で第5項・第7項） | OK（3件） |
| 健康保険 | 健保法3⑦が2版で同文。⑦一（直系尊属等）に「同一の世帯」がなく、⑦二にある。健保則37の2・37の3・38 が2版で同文。高確法50①一（75歳以上） | OK（5件） |
| 行政資料 | TA1180 の 48万円／58万円の表と入院・老人ホームの（注）。質疑応答事例05/32 の回答要旨・関係法令・基準日 | OK（3件） |
| 行政資料 | 措置法通達の目次に第41条の16 の項がない（見出しの並び：第41条の15 → 第41条の15の５ → 第41条の17） | OK |
| 行政資料 | 国外居住親族のページの Q&A のリンク名が「令和７年６月更新」 | OK |
| 行政資料 | 厚労省DBの R01 通知（00tc4995）の本文と、令和5年改正通知（00tc7769）に載る改正後の本文が、「第1」以降でテキストとして同じ（差分0行） | OK |
| 行政資料 | S52 通知の「六〇歳以上の者である場合」と「一八〇万円未満」がそれぞれ3回（記1(1)・記1(2)・記2）。S52 に「十二月三十一日」「時点」の語がない | OK（2件） |
| 行政資料 | 機構「従業員の家族が海外居住の場合の手続き」に「仕送り額未満」「2分の1未満」 | OK |

検査の方法の限界：

- 「同文」は、`articles_*.txt` に取り出したテキストの比較で、e-Gov の JSON をテキストにする処理（R1 のスクリプトを写したもの）の結果に依存する。ルビは落としている。
- 「語がない」は、キーワードを含む条の一覧（`kwhits_*`）に出ないことで判定した。走査の対象は取得した版の本則と附則（条を持たない附則は附則全体）で、別表・様式は対象外。
- R01 と R05 の比較は、HTML から取り出したテキストの比較。下線（改正箇所の印）は比較できない。

## 4. 実測で気づいたこと

1. 措法41の16 の 2026-12-31 版（`332AC0000000026_20261204_508AC0000000012`）は、e-Gov の revision_info の施行日（amendment_enforcement_date）が null だった。条文は 2025-12-31 版と同文。なお、改正履歴の一覧（`/law_revisions/332AC0000000026`）では、同じ law_revision_id の amendment_enforcement_date は 2026-12-04 で、amendment_enforcement_comment は「経済社会情勢の変化を踏まえた企業の事業活動の持続的な発展を図るための産業競争力強化法等の一部を改正する法律（令和八年法律第二十九号）附則第一条第二号に掲げる規定の施行の日」だった（/law_data の revision_info と /law_revisions で施行日の値が違う）。
2. 地方税法施行規則第2条の2 は、2027-01-01 の版で新しい第4項（「市町村長は、第二項の規定により同項に規定する明細書が添付された…申告書の提出があつた場合において…」）が加わり、国外居住者の項の番号が1つずつ後ろにずれる（`kwhits_chiho-ki_2026-11-09.txt` と `..._2027-01-01.txt` の比較）。条番号・項番号で参照するときは版を付ける必要がある。
3. 国税庁の国外居住親族のページのリンク名（「令和７年６月更新」「PDF/420KB」）と、リンク先の PDF の中身（「最終改訂 令和8年8月」、712,232 バイト）が合わない。ページのリンク名ではなく PDF の表紙と SHA-256 で版を記録する必要がある。
4. 国税庁の「送金関係書類の明細書」のページは、本文の説明に「所得税基本通達120-9」を引くが、末尾に「上記は、令和4年12月までの国外居住親族に係る扶養控除等の適用に関する説明となります」とある。令和5年以後の扱いは［QA-KG］Q32 の（注）による（［GD］§3.4）。

## 5. 再実行の手順

```
cd C:\Users\user\Documents\okura-gov
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_elderly-abroad_web.py robots elderly abroad kenpo
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_elderly-abroad_laws.py
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_elderly-abroad_laws.py koukirei
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_elderly-abroad_checks.py
```

- 全部の実行（2行目）で chiho-ki も3版を取る（スクリプトの JOBS は最後に asof 2026-01-01 を足した形）。
- 検査は、web の出力のうち最新のディレクトリ（`text/<set>_<ts>` の名前の順で最後）を読む。法令が改正されて未施行の版（2026-12-31・2027-01-01）が変わると、「同文」の検査が NG になることがある。それは検知として扱い、文書を直す。

## 訂正の記録

2026-11-09 の独立検証（実測 `docs/measurements/20261109_round2_elderly-abroad-verification.md`）で直した節：

- §2.2：「テキスト SHA-256」を保存したテキストのファイルから再計算するときの注意（Windows の改行の変換）を追記。表の値そのものは取得記録と一致。
- §4-1（補足）：/law_revisions の施行日（2026-12-04）と施行日の注記を追記。
