# R3 監視（D9）に使えそうな情報源の公開仕様

- 作成日・取得日：2026-11-09
- 本書は各機関が**公表している**仕様・注意事項の記録。実際に取得して確かめた結果は `docs/measurements/20261109_R3-tsutatsu_fetch-and-monitor-probe.md`。

## 1. 厚生労働省

### 1.1 RSS（公式）

- 「RSSによる情報配信について」https://www.mhlw.go.jp/rss/index.html
  - 形式：RSS 1.0（RDF）。
  - 提供フィード：新着情報 `https://www.mhlw.go.jp/stf/news.rdf`（「厚生労働省ホームページに新規に掲載した情報若しくは更新した情報」）、緊急情報 `https://www.mhlw.go.jp/stf/kinkyu.rdf`、感染症関係 `https://www.mhlw.go.jp/rss/inful_news.rdf` ほか2本。
  - 注意事項（原文）：「RSS情報の更新は必ずしも公表時間とは一致しておりません」「予告なくサービスを休止したり、RSSのURLや提供される内容などを変更する可能性があります」「厚生労働省ホームページから配信されたRSSについて、営利・非営利を問わず、その情報に基づいたホームページ・メールマガジンの作成、**情報の再配布は固くお断りします**」。

### 1.2 法令等データベースサービス（通知）

- トップ：https://www.mhlw.go.jp/hourei/
  - 「本データベースシステムのデータは**毎月更新**されます」。
  - 「更新までの間に発出された法令・通知等は以下の**登載準備中のコーナー**に掲載され、データベースへ登載後当該コーナーから**削除**されます」。
  - 取得時の表示：通知検索《最新：令和８年９月16日》（令和８年１１月４日更新）。
- 登載準備中の新着通知：https://www.mhlw.go.jp/hourei/new/tsuchi/new.html （中身は iframe の https://www.mhlw.go.jp/hourei/new/tsuchi/newindex.html 、取得日 2026-11-09。部局別・掲載日別に、通知名・発出日・番号・PDF リンクが並ぶ）
- 定期更新の内容：https://www.mhlw.go.jp/hourei/new/update/data.html （「令和８年１０月 定期データ更新内容」、新規の件数と一覧 PDF へのリンク）
- 情報詳細検索：`https://www.mhlw.go.jp/web/t_itemsrch?type=1` のフォーム（GET）。パラメータ `startGengo`（1明治〜5令和）、`yearFrom`、`monthFrom`、`dayFrom`、`endGengo`、`yearTo`、`monthTo`、`dayTo`、`shubetsu`（種別）、`bango`（番号）。結果は `/web/t_itemsrch_result?...`、本文は `/web/t_doc?dataId=<ID>&dataType=1&pageNo=1`。
  - 「平成21年7月1日以降制定の通知については、種別・発翰番号を読み替えて入力・検索する必要があります」（検索フォームの説明。読み替えの詳細 https://www.mhlw.go.jp/hourei/html/tsuchi/bango_g2.html は未取得）。データベースの表示は「保発第704001号」のような形（通知本文では「保発0704第1号」）。
- API や RSS の提供は、データベースのページ上に見当たらなかった。

## 2. 国税庁

- 新着情報（トピックス一覧）：https://www.nta.go.jp/information/news/index.htm （HTML。掲載日つきの一覧）
- 法令解釈通達：https://www.nta.go.jp/law/tsutatsu/menu.htm 。所得税基本通達の一部改正通達の一覧 https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/kaisei/kaisei_a.htm （改正日つき）。個別通達（申告所得税）https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/shinkoku/sinkoku.htm 、源泉所得税 https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/gensen/gensen.htm
- 源泉徴収義務者向けの新着・税制改正 https://www.nta.go.jp/users/gensen/index.htm
- RSS：国税庁のページ上には見つからなかった。二次情報（E、検索結果の要約）では、国税庁は「新着情報配信サービス」（メール、https://www.nta.go.jp/merumaga/news_toroku.htm ）と X（@NTA_Japan）で新着を知らせているとされる。R3 ではメール配信のページは取得していない。

## 3. 日本年金機構

- 新着情報一覧：https://www.nenkin.go.jp/allNewsList.html （HTML。「2026年11月9日」形式の日付つき。入札・調達の情報も混在）
- RSS：トップページ・新着一覧に RSS のリンクは見つからなかった。

## 4. 協会けんぽ

- トップ：https://www.kyoukaikenpo.or.jp/ 。RSS のリンクは見つからなかった。

## 5. 総務省・e-Gov（参考）

- 総務省「RSSについて」https://www.soumu.go.jp/menu_kyotsuu/rss_information.html 。新着 `https://www.soumu.go.jp/news.rdf`（RSS 1.0、Shift_JIS）。
- e-Gov パブリックコメントの RSS：`https://public-comment.e-gov.go.jp/rss/pcm_list.xml`（RSS 1.0）。政省令の改正案の意見募集が載る。
