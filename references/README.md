# 参考資料

## 公開にあたり外したもの（2026-11-18）

リポジトリを公開するにあたり、官公庁以外の団体が書いた資料の写し（本文の抜き出し）を外した。再配布の許諾を確かめていないため。
取得元の URL と SHA-256 は、各実測の取得の記録（`scripts/results/<名前>/*.json`）と `docs/` の文書に残っている。同じスクリプトで取り直せる。
`docs/` の文書がこれらのファイルを根拠として指している箇所は、取り直してから確かめる。

- `references/govtech-tokyo_openfisca_report_2025-04-16.pdf`（下の節）
- 健康保険組合のページ：`scripts/results/R2B_kabu_web/text/20261109-181101_kenpo/`、`scripts/results/R2B_kabu_xcheck/web_text/` の `nec_*`・`ngk_*`・`otsuka_*`・`topre_*`
- 全国健康保険協会のページ：`scripts/results/R2X_elderly-abroad_web/`・`R2X_elderly-abroad_verify/` の `kyoukai_faq_dependent*`、`scripts/results/R2X_gaps_web/`・`R2X_gaps_verify/` の `kyoukai_faq_dependent_status*`
- 共済組合・大学の資料：`scripts/results/IMPL4_web_fetch/hifuyosha/fukuoka_kijun*`、`scripts/results/IMPL4_web_lines/`・`IMPL4_web_pdftext/` の `ehime_*`・`hiroshima_*`・`okayama_*`・`tokyo_fuyou_*`、
  `scripts/results/R3X_kyosai-b_pdftext/` の `chikyosai_info_250924_*`・`miyagi_fget96_*`・`tokyo_00_tsuchi_*`、
  `scripts/results/R3X_kyosai-b_verify/text/` の `boueikyosai_164`・`chikyosai_info_250924`・`miyagi_fget96`・`kouritu_tokyo_19_23`・`kouritu_tokyo_00_tsuchi`

残したもの：法令（e-Gov）、国・地方公共団体の通知・通達・手引き（共済組合などのサイトに載っていた国の通知・運用方針を含む）、robots.txt、取得の記録。

## govtech-tokyo_openfisca_report_2025-04-16.pdf

- 正式名：国際的技術フレームワーク『OpenFisca』の活用可能性の検討レポート
- 発行：一般財団法人 GovTech東京、2025年4月16日（全37ページ）
- 令和6年度の調査委託事業として、一般社団法人防窮研究所が調査・分析した内容をもとに作成
- 取得元：https://cdn.govtechtokyo.or.jp/blobgttwwwpubledd3ed2d0d/wp-content/uploads/2025/06/調査報告書_国際的技術フレームワーク「OpenFisca」の活用可能性の検討レポート.pdf
  - URLの「2025/06」はアップロードの月で、発行日ではない
- 取得日：2026-11-07
- SHA-256：`e718ead17348cb7b18a24629beb2f22af7e4753b29ec4a64ddda4d8549acae3`
- 2026-11-18：リポジトリの公開にあたり、PDF の写しを外した（再配布の許諾を確かめていないため）。上の取得元から取り直し、SHA-256 で同じ版かを確かめる。

### このプロジェクトに関係するページ（前のセッションで全ページを読んだ）

| ページ | 内容 | このプロジェクトでの意味 |
|---|---|---|
| p.5-6 | OpenFisca-Core（土台）と、国ごとのパッケージに分かれている。ライセンスは AGPL | D6：Core の上に自作パッケージを書く |
| p.8-9 | テストを YAML で書く。パラメータ（控除額・税率など）を YAML で管理する。日本語の変数名が推奨されている | 基準額を年度ごとに分けて管理できる |
| p.13 | 扶養親族の定義を and/or の木構造に分解した例。ただし所得要件は旧基準の「48万円以下」 | 条文の論理構造の表し方。基準額が古くなる実例 |
| p.16 | 出力は数値だけ。計算の単位は世帯か個人だけ | |
| p.17-18 | 名前空間がなく、名前が衝突する（所得税の「所得控除」と特別障害者手当の「所得控除」）。接頭辞で回避している | 用語を定義する層が要る |
| p.18-19 | OpenFisca-Japan のグループは「世帯」（同居している家族）だけ。役割は親・子・祖父母で、「子」は未成年 | **税の扶養（生計を一にする）に合わない** |
| p.21 | 世帯主を特定できないので、最も収入が高い人を世帯主とみなしている | 申告に使える精度ではない |
| p.22 | 3.2：テストも改正前のままなので、制度改正に対応していなくてもテストが成功してしまう | D9：施行日つきのテストを先に書く |
| p.26 | 4.1.2：ユーザーが入力する情報と中間変数を分けて部品化する。入力元にマイナポータルの自己情報取得APIを挙げている | D2・D5 の考え方を裏づける |
| p.28-29 | if 文を使わず、掛け算で条件を表すなど特殊な書き方になる。現金給付・対象者が多い・基本的な税と社会保障の制度に向く | |
| p.30 | 代替として Blawx（カナダ政府が試行中） | |
| p.34-35 | OpenFisca-Japan は「ヤドカリくん」専用で、正確さより入力項目の少なさを優先している。法制度の専門家のレビューはしていない | OpenFisca-Japan を使わない理由 |
| p.37 | 9制度に対応するのに、ボランティア2人で約2か月 | 工数の目安 |
