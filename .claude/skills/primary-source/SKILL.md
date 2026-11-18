---
name: primary-source
description: okura-gov で法令・通達・通知・手引き・様式・告示などの一次情報を取得し、版（law_revision_id）・施行日・取得日・対象年分つきで docs/public-sources に記録するときに使う。e-Gov 法令API v2（/laws・/law_revisions・/law_data）の使い方を含む。「一次情報で確かめる」「条文を取ってくる」「e-Gov」「原文を確認」「出典を記録」「基準額の根拠」など。
---

# 一次情報を取得して記録する（okura-gov）

最初に `AGENTS.md`（記録のルール・ドキュメント規約・安全のルール）を読む。既存の例：`scripts/IMPL5_laws_egov.py`（e-Gov の取得と条の取り出し）、`docs/measurements/20261109_R1-laws_egov-api-monitoring.md`（API の実測）、`docs/public-sources/20261112_impl-research4_kokunen-laws.md`（記録の書き方）。

## 0. 何を一次情報とするか

根拠の強さ（D21 R5・D22 S2。`basis.SourceKind`）：法令（法律・政令・省令）＞ 告示 ＞ 通達・通知（事務連絡を含む。同じ順位）＞ 手引き・様式の注記 ＞ 国税庁の説明 ＞ 保険者の案内 ＞ 自治体の資料（注入データの出典にだけ使う）。
共済組合の基準のように原文が見つからないものは、組合の案内を出典にして「原文未確認」の印を付ける（D21 R4）。条番号・通達番号は原文で確かめたものだけを書く。

## 1. 準備

- 先に `docs/public-sources` を Grep し、既にあれば取り直さずに使う（取得日と版を確かめる）。
- **送らないもの**：家族の実際のデータ（金額・生年月日・住所・保険者・病院の名前）を、検索の語・URL・リクエストに入れない。
- 取得のスクリプトは `scripts/<群>_<名前>.py`（実測用。標準ライブラリだけ。既存の `scripts/IMPL5_laws_egov.py` を写して直す。import しない）。User-Agent は `okura-gov-research/0.1`、リクエストの間は 1.5 秒以上。robots.txt で禁止されたサイト（官報 `kanpo.go.jp`）は取らない。
- ダウンロードしたものは信頼できないデータ：実行ごとに新しい空のディレクトリ `.work/downloads/<YYYYMMDD-HHMMSS>_<名前>/` に置き、その中で何も実行しない。読むときは `json.loads` などでデータとして読む。Python は `-I -X utf8`。
- 取り出した結果（条の本文の写し・取得の記録）は `scripts/results/<スクリプトの名前>/` に置く。

## 2. e-Gov 法令API v2

基点は `https://laws.e-gov.go.jp/api/2`（仕様：`/api/2/swagger-ui/lawapi-v2.yaml`）。

| 目的 | 呼び方 | 見るもの |
|---|---|---|
| 法令ID を探す | `/laws?law_title=<法令名>` | `law_id`（例 所得税法 `340AC0000000033`、所得税法施行令 `340CO0000000096`、地方税法 `325AC0000000226`） |
| 版の一覧 | `/law_revisions/{law_id}`（更新の絞り込みは `?updated_from=YYYY-MM-DD`） | `law_revision_id`（`<law_id>_<施行日>_<改正法令ID>`）、`amendment_law_num`・`amendment_law_title`、`amendment_promulgate_date`、`amendment_enforcement_date`、`current_revision_status`（未施行は UnEnforced）、施行日が未定なら `amendment_scheduled_enforcement_date`・`amendment_enforcement_comment`、`updated`（最後に更新された日時） |
| ある日の版の本文 | `/law_data/{law_id}?response_format=json&asof=YYYY-MM-DD` | `law_full_text`（要素の木。条は `Num` 属性）。版の `law_revision_id` を記録する |

- **asof の選び方**：所得税の年分 Y は年末 `Y-12-31` の版、住民税の年度 F は賦課期日 `F-01-01` の版を基本にする。施行日をまたぐ比較は施行日の前日と当日。未施行の版も asof に未来の日付を渡せば取れる。
- 1つの改正法令は施行日ごとに別の版になる。**適用年分は改正法令の附則で決まる**（「令和X年分以後の所得税について適用」など）。施行日と適用年分を混同しない。
- 更新の監視そのものは `packages/monitor` の仕事。ここでは本文と版を確かめて記録する。

## 3. e-Gov 以外（国税庁・厚労省・日本年金機構・自治体・保険者）

- 通達・質疑応答・手引き・様式・源泉徴収税額表などは発行元のページか PDF を取得する。URL・取得日・SHA-256・バイト数・ページ番号を記録する。
- PDF の文字の取り出しは既存の `scripts/*_pdftext.py` に倣う。画像の PDF で文字が取れないときは、そう記録する（推測で埋めない）。
- 帳票レイアウト設計書（AI-OCR）は取得してよいが、中身をリポジトリに写さない（D21 R7）。

## 4. 記録する

ドキュメント規約どおり別々のファイルに分ける。

1. **実測**（`docs/measurements/YYYYMMDD_<群>_<題>.md`）：取得の手順。スクリプトのパス、再実行のコマンド、結果のパス（`scripts/results/…`）、取得の記録（URL・版・状態・SHA-256）、取れなかったもの。
2. **公開資料の情報**（`docs/public-sources/YYYYMMDD_<群>_<題>.md`）。節ごとに：
   - 出典：法令名・`law_id`・`law_revision_id`・改正法令（番号）・施行日・状態・asof、または URL と発行日。
   - 取得日、対象の年分・年度（「令和X年分」）、適用の開始（いつから施行・適用されるか）。
   - 原文の引用（必要な所だけ）と、写しのパス（`scripts/results/<名前>/<略称>_<asof>.txt` の `## Num=…`）。
   - 経過措置・附則、版の間で文言が同じか違うか。
   - 見つからなかったこと・分からなかったこと。
3. 解釈・当てはめは公開資料の情報に混ぜず、`docs/hypotheses/` に分ける（research-loop スキル）。

パラメータ・概念辞書から引くときは、この public-sources のファイル#節を `reference`・`出典` に書く（外部の URL を直接書かない）。

## 5. 確かめ方

- 再実行のコマンドで同じ結果が出るか（`updated` や現行の版は日によって変わりうる。変わること自体は異常ではない）。
- パラメータに反映したら `test_architecture.py`（出典の実在）と、そのモジュールのユニットテスト（期待値に出典）を動かす。

```
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_architecture.py
```

シェルの引数にバッククォートや `$()` を入れない。スクリプトと文書は Write・Edit で書く。
