# R1 法令の変更の監視（D9）に使える情報源の公開仕様

- 取得日：2026-11-09
- 種別：公開資料の情報（各サイトが公開している仕様・ページ）。実際に叩いた結果は `docs/measurements/20261109_R1-laws_egov-api-monitoring.md`。

## 1. e-Gov 法令API Version 2

- 仕様（OpenAPI 3.0.3、`info.version: 2.1.139`）：https://laws.e-gov.go.jp/api/2/swagger-ui/lawapi-v2.yaml
  （取得：`scripts/R1_egov_spec.py`。Redoc：https://laws.e-gov.go.jp/api/2/redoc/ ）
- サーバ：`https://laws.e-gov.go.jp/api/2`。認証なし。
- 仕様に書かれた注意：法令本文取得APIの JSON、法令本文ファイル取得APIの JSON などは「試行版となり仕様変更が発生する場合があります」。

| エンドポイント | 用途 | 監視に使えるパラメータ（仕様の記述） |
|---|---|---|
| `GET /laws` | 法令一覧 | `law_id`、`law_title`、`law_type`、`asof`、`category_cd`、`promulgation_date_from/to`（公布日）、`amendment_law_id`（改正法令の法令ID、部分一致）など。**`updated_from/to` はない** |
| `GET /law_revisions/{law_id_or_num}` | 1つの法令の改正履歴（新しい順） | `amendment_date_from/to`（改正法令施行期日）、`amendment_promulgate_date_from/to`、`amendment_law_id/num/title`、`current_revision_status`、**`updated_from/to`（データの更新日）**など。法令ID（または法令番号）の指定が必須 |
| `GET /law_data/{law_id_or_num_or_revision_id}` | 本文 | `asof`（指定時点以前で最新の履歴の本文）、`elm`（条項の一部だけ）、`omit_amendment_suppl_provision`、`response_format`（json/xml）、`json_format`（full/light） |
| `GET /keyword` | キーワード検索 | — |
| `GET /law_file/{file_type}/{id}` | 本文ファイル | — |

- `revision_info` の主な項目：`law_revision_id`（`<law_id>_<施行日YYYYMMDD>_<改正法令ID>`）、`amendment_law_num`、`amendment_law_title`、`amendment_promulgate_date`、`amendment_enforcement_date`、`amendment_scheduled_enforcement_date`、`amendment_enforcement_comment`、`current_revision_status`（`CurrentEnforced` / `PreviousEnforced` / `UnEnforced` など）、`updated`、`mission`、`amendment_type`。
- 改正区分の見分け方（仕様の表）：新規制定＝`amendment_type` 1 かつ `mission` New、一部改正＝`mission` Partial、被改正法＝`amendment_type` 3 かつ `mission` New、廃止＝`amendment_type` 8 または `repeal_status` が Repeal/Expire/LossOfEffectiveness。

## 2. e-Gov 法令データの一括ダウンロード（更新法令データ）

- 仕様の説明文に記載：
  - すべての法令データ：`https://laws.e-gov.go.jp/bulkdownload?file_section=1&only_xml_flag=true`
  - 最新の更新法令データ：`https://laws.e-gov.go.jp/bulkdownload?file_section=3&update_date={YYYYMMDD}&only_xml_flag=true`
  - 「更新法令データの取得範囲は過去３ヶ月です。」（ただし実測では1年7か月前の日付も取得できた。measurements を参照）
- 一括ダウンロードのページ：https://laws.e-gov.go.jp/bulkdownload/

## 3. 国税庁

- RSS：トップページ（https://www.nta.go.jp/ ）と新着情報一覧（https://www.nta.go.jp/information/news/news.htm ）の HTML に、RSS/Atom の `<link rel="alternate">` も、rss・rdf・atom・feed を含むリンクも**見つからなかった**（実測）。推測した URL（`/information/rss.htm`、`/about/rss/index.htm`）は「指定されたページを表示できませんでした」のページ（HTTP 200）だった。
- 新着情報一覧（HTML）：https://www.nta.go.jp/information/news/news.htm 、トピックス一覧：https://www.nta.go.jp/information/news/index.htm
- sitemap.xml：https://www.nta.go.jp/sitemap.xml （robots.txt に記載）。666件すべての `lastmod` が 2018-04-02 で、更新の検知には使えない（実測）。
- 税制改正の資料（一次情報）：
  - 令和7年度改正（基礎控除の見直し等）：https://www.nta.go.jp/users/gensen/2025kiso/index.htm
  - 令和8年度改正（基礎控除の引上げ等）：https://www.nta.go.jp/users/gensen/2026kiso/index.htm
  - URL の形が `users/gensen/<西暦>kiso/` で続いている（2つの例から。今後も同じとは限らない）。

## 4. 官報（インターネット版官報）

- https://www.kanpo.go.jp/ 。トップページに RSS/Atom の告知は見つからなかった（実測）。
- robots.txt（2026-11-09 取得）：
  ```
  User-agent: *
  Disallow: /20
  Disallow: /old/
  User-agent: ndl-japan
  Disallow:
  ```
  号ごとのページ（`/20…` で始まるパス）は一般のクローラに対して Disallow。**官報を自動で巡回する監視は robots.txt に反する**。

## 5. 財務省

- 毎年度の税制改正：https://www.mof.go.jp/tax_policy/tax_reform/index.html
- 年度ごとのページ（URL の形 `outline/fy<西暦>/`）：
  - 令和7年度：https://www.mof.go.jp/tax_policy/tax_reform/outline/fy2025/index.html （大綱 PDF `20241227taikou.pdf`、概要 `07taikou_gaiyou.pdf` へのリンクあり）
  - 令和8年度：https://www.mof.go.jp/tax_policy/tax_reform/outline/fy2026/index.html （大綱 PDF `20251226taikou.pdf`、概要 `08taikou_gaiyou.pdf`）
  - 税制改正の解説：`outline/fy2025/explanation/index.html`、`outline/fy2026/explanation/index.html`（どちらも HTTP 200、タイトル「令和７年度　税制改正の解説」「令和８年度　税制改正の解説」）
- 大綱の公表日（PDF のファイル名から）：令和7年度 2024-12-27、令和8年度 2025-12-26（ファイル名からの読み取り。本文の日付は未確認）。
- RSS：トップと税制改正ページの HTML にフィードのリンクは見つからなかった。robots.txt は 404。

## 6. 厚生労働省・日本年金機構（R3 の監視対象。R1 では有無だけ確認）

- 厚生労働省：新着情報の RSS（RDF）`https://www.mhlw.go.jp/stf/news.rdf` があり、取得できた（121件、先頭の日付 2026-11-09）。説明ページ：https://www.mhlw.go.jp/rss/index.html
- 日本年金機構：トップページに RSS のリンクは見つからなかった。

## 7. 法令の改正の流れ（今回取得した事実から）

| 段階 | 令和7年度改正 | 令和8年度改正 | 出典 |
|---|---|---|---|
| 大綱 | 2024-12-27（PDF ファイル名） | 2025-12-26（同） | 財務省ページ |
| 改正法の公布 | 2025-03-31（令和7年法律第13号、地方税は第7号） | 2026-03-31（令和8年法律第12号、地方税は第2号） | e-Gov `amendment_promulgate_date` |
| 主な施行 | 2025-12-01（基礎控除等） | 2026-12-01（基礎控除等） | 改正法附則第1条 |
| 適用 | 令和7年分以後 | 令和8年分以後 | 改正法附則 |
| 国税庁の説明資料 | （2025kiso ページ） | 「あらまし」令和8年4月、Q&A 令和8年5月 | 国税庁 |
