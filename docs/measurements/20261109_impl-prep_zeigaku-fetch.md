# 実装前の追加調査（zeigaku）実測：所得税の税額計算・申告義務に関係する条文と国税庁・年金機構の資料の取得

- 実施日：2026-11-09（JST）
- 種別：実測（measurements）。ここには「何を実行し、何が返ってきたか」だけを書く。条文・資料の内容の整理は
  `docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md`、そこからの仮説は `docs/hypotheses/20261109_impl-prep_zeigaku-calc-model.md`。
- 独立検証（2026-11-09）で取り直した記録：`docs/measurements/20261109_impl-prep_zeigaku-verify.md`（以下 [M-ZV]）。直した箇所の訂正前・訂正後と根拠は `docs/measurements/20261109_impl-prep_zeigaku-verification.md`（末尾の「訂正の記録」に訂正した節の一覧）。
- 環境：Windows 11、Python 3.11.9（`C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8`。pyenv のシムは使っていない）、標準ライブラリのみ。
  User-Agent `okura-gov-research/0.1`、リクエストの間隔 1.5 秒。個人の情報は送っていない。官報は取得していない。
- ダウンロードしたものは、実行ごとに新しい空のディレクトリ `.work/downloads/<YYYYMMDD-HHMMSS>_IMPL_zeigaku_*/` に置き、その中ではコードを実行していない
  （スクリプトはリポジトリの直下から実行し、JSON は `json.loads`、HTML は `html.parser` でデータとして読んだだけ。PDF は Read ツールのページ指定で読んだ）。

## 再実行の方法

```
PY=C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe
$PY -I -X utf8 scripts/IMPL_zeigaku_laws.py              # 法令本文（e-Gov 法令API v2）。§1
$PY -I -X utf8 scripts/IMPL_zeigaku_laws2.py             # 追加の条文とキーワード検索。§1・§3
$PY -I -X utf8 scripts/IMPL_zeigaku_laws2.py r9          # 所得税法第120条・所令第262条の 2027-01-01 版。§1
$PY -I -X utf8 scripts/IMPL_zeigaku_laws2.py fukko       # 復興特別所得税に関する政令・省令。§1
$PY -I -X utf8 scripts/IMPL_zeigaku_grep.py <JSON> <名前> <文字列...>   # 取得済み JSON の文字列検索。§2
$PY -I -X utf8 scripts/IMPL_zeigaku_fetch_web.py ta index nenkin round2 round3   # 国税庁・年金機構のページ。§4
$PY -I -X utf8 scripts/IMPL_zeigaku_example_calc.py      # 推測の文書の手計算の検算（ネットワーク不要）。§6
```

結果の置き場所：

| スクリプト | 結果 | ダウンロード先（コミットしない） |
|---|---|---|
| `scripts/IMPL_zeigaku_laws.py` | `scripts/results/IMPL_zeigaku_laws/`（`<略称>_<asof>.txt`、`<略称>_diff_<a>_vs_<b>.diff`、`fetch_log.json`） | `.work/downloads/20261109-145308_IMPL_zeigaku_laws/` |
| `scripts/IMPL_zeigaku_laws2.py` | `scripts/results/IMPL_zeigaku_laws2/`（`fetch_log.json`、`fetch_log_r9.json`、`fetch_log_fukko.json` ほか） | `.work/downloads/20261109-145751_IMPL_zeigaku_laws2/`、`20261109-150604_…`、`20261109-151321_…` |
| `scripts/IMPL_zeigaku_grep.py` | `scripts/results/IMPL_zeigaku_grep/*.txt` | （取得済みの JSON を読むだけ） |
| `scripts/IMPL_zeigaku_fetch_web.py` | `scripts/results/IMPL_zeigaku_fetch_web/<set>_<ts>.json`（ステータス、Last-Modified、SHA-256、ページの「現在法令等」の表示、抜き書き） | `.work/downloads/<ts>_IMPL_zeigaku_<set>/`、テキストは `.work/text/<ts>_IMPL_zeigaku_<set>/` |
| `scripts/IMPL_zeigaku_example_calc.py` | `scripts/results/IMPL_zeigaku_example_calc/examples.{json,md}` | なし |

## 1. 取得した法令の版（e-Gov 法令API v2 `/law_data/{law_id}?response_format=json&asof=<日付>`）

すべて HTTP 200、`errors` は空（各 `fetch_log*.json`）。状態は 2026-11-09 時点の API の返り値。

| 略称 | 法令（law_id） | asof | law_revision_id | 状態 | 版の施行日 |
|---|---|---|---|---|---|
| shotoku | 所得税法（340AC0000000033） | 2024-12-31 | 340AC0000000033_20240612_506AC0000000047 | PreviousEnforced | 2024-06-12 |
| shotoku | 同 | 2025-12-31 | 340AC0000000033_20251218_507AC0000000013 | PreviousEnforced | 2025-12-18 |
| shotoku | 同 | 2026-12-31 | 340AC0000000033_20261201_508AC0000000012 | UnEnforced | 2026-12-01 |
| shotoku-r9 | 同 | 2027-01-01 | 340AC0000000033_20270101_508AC0000000012 | UnEnforced | 2027-01-01 |
| shotoku-rei | 所得税法施行令（340CO0000000096） | 2025-12-31 | 340CO0000000096_20251201_507CO0000000120 | PreviousEnforced | 2025-12-01 |
| shotoku-rei | 同 | 2026-12-31 | 340CO0000000096_20261201_508CO0000000093 | UnEnforced | 2026-12-01 |
| shotoku-rei-r9 | 同 | 2027-01-01 | 340CO0000000096_20270101_508CO0000000093 | UnEnforced | 2027-01-01 |
| shotoku-ki | 所得税法施行規則（340M50000040011） | 2025-12-31 | 340M50000040011_20251201_507M60000040018 | PreviousEnforced | 2025-12-01 |
| shotoku-ki | 同 | 2026-12-31 | 340M50000040011_20261211_508M60000040017 | UnEnforced | 2026-12-11 |
| tsusoku | 国税通則法（337AC0000000066） | 2025-12-31 | 337AC0000000066_20251001_505AC0000000053 | PreviousEnforced | 2025-10-01 |
| tsusoku | 同 | 2026-12-31 | 337AC0000000066_20261101_507AC0000000013 | CurrentEnforced | 2026-11-01 |
| tsusoku-rei | 国税通則法施行令（337CO0000000135） | 2026-12-31 | 337CO0000000135_20260401_507CO0000000126 | CurrentEnforced | 2026-04-01 |
| fukko | 東日本大震災からの復興のための施策を実施するために必要な財源の確保に関する特別措置法（423AC0000000117） | 2025-12-31 | 423AC0000000117_20250601_504AC0000000068 | PreviousEnforced | 2025-06-01 |
| fukko | 同 | 2026-12-31 | 423AC0000000117_20261201_508AC0000000012 | UnEnforced | 2026-12-01 |
| fukko | 同 | 2027-01-01 | 423AC0000000117_20270101_508AC0000000012 | UnEnforced | 2027-01-01 |
| fukko-rei | 復興特別所得税に関する政令（424CO0000000016） | 2026-12-31 | 424CO0000000016_20260525_507CO0000000244 | **PreviousEnforced** | 2026-05-25 |
| fukko-ki | 復興特別所得税に関する省令（424M60000040006） | 2026-12-31 | 424M60000040006_20260901_506M60000040028 | CurrentEnforced | 2026-09-01 |
| kokunen | 国民年金法（334AC0000000141） | 2026-11-09 | 334AC0000000141_20261001_507AC0000000074 | CurrentEnforced | 2026-10-01 |
| kokunen-rei | 国民年金法施行令（334CO0000000184） | 2025-04-01 | 334CO0000000184_20250401_507CO0000000106 | PreviousEnforced | 2025-04-01 |
| kokunen-rei | 同 | 2026-11-09、2027-04-01 | 334CO0000000184_20261001_508CO0000000226（2つの asof で同じ版） | CurrentEnforced | 2026-10-01 |
| kokunen-ki | 国民年金法施行規則（335M50000100012） | 2026-11-09 | 335M50000100012_20261001_508M60000100121 | CurrentEnforced | 2026-10-01 |
| gakko | 学校教育法（322AC0000000026） | 2026-11-09 | 322AC0000000026_20260617_508AC0000000037 | CurrentEnforced | 2026-06-17 |

- 復興特別所得税に関する政令は、asof 2026-12-31 で返った版の状態が `PreviousEnforced` だった（同じ asof の他の法令は CurrentEnforced か UnEnforced）。理由は調べていない。
- 改正履歴（`/law_revisions/{id}?amendment_date_from=2024-01-01`、HTTP 200。`fetch_log.json` の `revisions`）：
  - 復興財源確保法：令和8年法律第12号による版が 2026-04-01（CurrentEnforced）、2026-12-01、2027-01-01、**2028-01-01**（いずれも UnEnforced）の4つ登録されていた。
  - 国民年金法施行令：2024-01-01 以後の版は 12 件。2026-10-01 の令和8年政令第226号の版が最新（CurrentEnforced）。2027-04-01 を asof にしても同じ版が返った（＝2026-11-09 時点で登録済みの未施行の改正はない）。

## 2. 条ごとの年分間の比較（同じ条の本文を asof ごとに比べた結果）

方法：`scripts/results/IMPL_zeigaku_laws/shotoku_<asof>.txt` から `## Num=<n>` の節を切り出し、文字列として比較した（bash の `diff`）。

| 所得税法の条 | 2024-12-31 → 2025-12-31 | 2025-12-31 → 2026-12-31 |
|---|---|---|
| 第21条（所得税額の計算の順序） | 同じ | 同じ |
| 第22条（課税標準） | 同じ | 同じ |
| 第28条（給与所得） | 違う | 違う |
| 第74条（社会保険料控除） | 同じ | 同じ |
| 第82条（勤労学生控除） | 同じ | 同じ |
| 第86条（基礎控除） | 違う | 違う |
| 第87条（所得控除の順序） | 違う（「特定親族特別控除」が加わった） | 同じ |
| 第89条（税率） | 同じ | 同じ |
| 第104条（予定納税額の納付） | 同じ | 同じ |
| 第120条（確定所得申告） | 違う（第3項第3号に特定親族特別控除が加わった） | 違う（第4項第2号の「社会保険診療報酬支払基金」が「医療情報基盤・診療報酬審査支払機構」に） |
| 第121条（確定所得申告を要しない場合） | 違う（第1項第2号ロに「特定親族特別控除の額」が加わった） | 同じ |
| 第122条（還付等を受けるための申告） | 同じ | 同じ |
| 第138条（源泉徴収税額等の還付） | 同じ | 同じ |

- 第120条の 2026-12-31 版と 2027-01-01 版（`scripts/results/IMPL_zeigaku_laws2/shotoku-r9_2027-01-01.txt`）の比較：第3項第1号に「第六項において同じ。」が加わり、第6項・第7項が新設され、旧第6項・第7項が第8項・第9項になった。
  （注：2つのスクリプトでテキストの整形が少し違う（`（Paragraph1）` の有無、号の見出しと本文の間の全角空白）ので、bash の `diff` はそれらの行も差として出す。上は整形の差を除いて読んだ結果。）
- 別表第五（所得税法第28条第4項）の先頭の行（`scripts/results/IMPL_zeigaku_laws/shotoku_<asof>.txt` の「## 別表 別表第五」。先頭60行だけ保存）：

| asof | 給与所得控除後の給与等の金額が 0 の範囲 | 「給与等の金額から〇〇円を控除した金額」の範囲 | 表の総行数（`IMPL_zeigaku_laws.py` の整形後の行数。表の TableRow の数ではない。TableRow の数は 543／496／484：[M-ZV] §2） |
|---|---|---|---|
| 2024-12-31 | 551,000円未満 | 551,000円以上 1,619,000円未満：−550,000円 | 556 |
| 2025-12-31 | 651,000円未満 | 651,000円以上 1,900,000円未満：−650,000円 | 508 |
| 2026-12-31 | 691,000円未満 | 691,000円以上 2,026,000円未満：−690,000円 | 496 |

- 国税通則法 第118条〜第120条：2025-12-31 版と 2026-12-31 版で差なし（`tsusoku_diff_2025-12-31_vs_2026-12-31.diff` が空）。
- 復興財源確保法：
  - 2025-12-31 → 2026-12-31：第1条の文言、第33条の読替表などが変わった。第8条〜第13条、第17条〜第19条、第24条の本文は差の中に現れなかった（`fukko_diff_2025-12-31_vs_2026-12-31.diff`）。
  - 2026-12-31 → 2027-01-01：条ごとに本文を比べると、第9・13・14・16・17・18・19・21・23・27・28・29・30・32・33条が違い、第8・10・12・15・20・20の2・22・24〜26・31条は同じだった。主な変更：第9条（「令和十九年」→「令和二十九年」）、第13条（「百分の二・一」→「百分の一・一」）、第27条（法人：同じく「百分の一・一」）、第28条第2項（源泉徴収：同じく「百分の一・一」）・第9項（「百二・一分の」→「百一・一分の」）（`fukko_diff_2026-12-31_vs_2027-01-01.diff`、`fukko_2027-01-01.txt`）。第24条（端数）は変わらない。
    - 注（独立検証で追記）：上の比較の対象は第1〜39条の整数番号の条だけだった。本則の全条を比べると、第13条の2 と第71・72・73条も違う（[M-ZV] §2、`scripts/results/IMPL_zeigaku_verify/extra/extra.txt`）。
- 所得税法施行令：2025-12-31 → 2026-12-31 で第11条の3第2項の構成が変わった（高等課程・専門課程と専攻科・一般課程・その他の4区分になり、単位数・通信教育の要件が加わった）。第208条・第262条・第262条の2・第264条・第267条は差の中に現れなかった（`shotoku-rei_diff_2025-12-31_vs_2026-12-31.diff`）。
- 所得税法施行規則：見出しの正規表現（勤労学生|確定申告書|専修学校|各種学校）で拾えたのは第47条の4・第49条・第68条だけで、勤労学生の証明書の規定は見出しで拾えなかった。本文の文字列検索（§3）で第47条の2第11項を見つけた。
  - 注（独立検証で追記）：第47条・第47条の2 は比べていない。両条とも 2025-12-31 版と 2026-12-31 版で違い、第47条の2第11項は「生徒」→「学生又は生徒」、課程の号（第1号・第2号 → 第1号〜第4号）、認定職業訓練の課程（令第11条の3第2項第2号 → 第4号）が変わっている（[M-ZV] §2）。
- 国民年金法施行令：2025-04-01 → 2026-11-09 で、**比べた第6条の6・第6条の9〜第6条の11 の中では**第6条の6第8号（「専修学校に在学する生徒」→「生徒又は学生」）だけが変わった。第6条の9〜第6条の11 は差なし（`kokunen-rei_diff_2025-04-01_vs_2026-11-09.diff`）。
  - 注（独立検証で追記）：比べていない第6条の12第2項第1号（「第十号の二」→「第十号の二又は第十二号」、特定親族特別控除額を追加。令和7年政令第355号、2026-04-01 の版から）と第5条の4 も変わっている（[M-ZV] §2）。2026-11-09 → 2027-04-01 は差なし。

## 3. 取得済みの JSON の文字列検索（`scripts/IMPL_zeigaku_grep.py`）と e-Gov のキーワード検索

| 出力 | 対象（JSON） | 探した文字列 | 該当した条 |
|---|---|---|---|
| `IMPL_zeigaku_grep/shotoku-ki_kinro.txt` | 所得税法施行規則 2026-12-31 | 第三十二号ロ、勤労学生 | 本則 第1条、第47条、第47条の2、第74条、第93条（5件） |
| `IMPL_zeigaku_grep/shotoku-ki_kinro_2025.txt` | 同 2025-12-31 | 第三十二号ロ | 本則 第47条の2（第11項にある。1件） |
| `IMPL_zeigaku_grep/fukko_2027_r9.txt` | 復興財源確保法 2027-01-01 | 令和九年分、防衛特別所得税、令和八年法律第十二号 | 附則（令和8年法律第12号）第88条（1件） |
| `IMPL_zeigaku_grep/kokunen-ki_month.txt` | 国民年金法施行規則 2026-11-09 | 定める月は、第九十条第一項第一号、学生納付特例、第九十条の三 | 第77条の2、第77条の4 など16件 |
| `IMPL_zeigaku_grep/shotoku-rei_11_3_suppl.txt` | 所得税法施行令 2026-12-31 | 第十一条の三 | 本則 第11条の3、附則（原始）第13条、附則（平成20年政令第155号）第1条、附則（令和8年政令第93号）第3条 |
| `IMPL_zeigaku_grep/shotoku-rei_r8_93_suppl1.txt` | 同 | 第十一条の三第二項の改正規定 | 0件（施行期日の条に第11条の3の改正規定の名前が出てこない＝本文の施行日 2026-04-01 による、と読んだ） |
| `IMPL_zeigaku_grep/shotoku-rei_r8_93_sekou.txt` | 同 | この政令は、令和八年四月一日から施行する | 附則（令和8年政令第93号）第1条 |
| `IMPL_zeigaku_grep/kokunen_88.txt` | 国民年金法 2026-11-09（R1 のダウンロード `.work/downloads/20261109-133413_egov_articles/334AC0000000141_2026-11-09.json`） | 連帯して納付する義務 | 本則 第88条 |

- `IMPL_zeigaku_laws2.py` の「国民年金法施行規則」で、文字列「前々年の所得」「法第九十条第一項第一号に規定する厚生労働省令で定める月」はどちらも0件だった（`fetch_log.json` の picked が空）。上の表の検索（「定める月は」）で第77条の2 を見つけた。
- `IMPL_zeigaku_laws2.py fukko`：復興特別所得税に関する政令で「一円未満」「端数」を含む条は第4条・第6条〜第10条（いずれも按分・納付・還付があったものとされる額の端数の扱い）。**復興特別所得税に関する省令では0件**。「第13条で計算した復興特別所得税の額の一円未満を切り捨てる」という趣旨の条は、この2つの中には見つからなかった。
- `/keyword?keyword=防衛特別所得税`（`scripts/results/IMPL_zeigaku_laws2/fetch_log.json` の `keyword`）：
  - asof 2027-01-01：HTTP 200、total_count 228。先頭に法人税法（340AC0000000034_20270101_508AC0000000012）、我が国の防衛力の抜本的な強化等のために必要な財源の確保に関する特別措置法（令和5年法律第69号、505AC0000000069_20270101_508AC0000000012。目次に「第三章の二　防衛特別所得税」）。
  - asof 2026-11-09：HTTP 404（0件）。
  - 防衛財源確保法の本文は取得していない。

## 4. 国税庁・日本年金機構のページ（`scripts/IMPL_zeigaku_fetch_web.py`）

robots.txt（取得ごとに保存）：
- `https://www.nta.go.jp/robots.txt`：HTTP 200（SHA-256 `a5f4e421e5bb2b20…`）。`User-agent: *` の Disallow は `/service_publication/` と各国税局の `…/service_publication/` だけ。今回の URL はどれも禁止されていなかった（`urllib.robotparser` で判定）。
- `https://www.nenkin.go.jp/robots.txt`：HTTP 200（SHA-256 `b1b1b2e85299b5a3…`）。Disallow は特定の PDF 1件だけ。

| id | URL | HTTP | Last-Modified | SHA-256（先頭16桁） | ページの表示 |
|---|---|---|---|---|---|
| ta_1130 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1130.htm | 200 | 2026-09-09 | eb55eb32e48ff54d | [令和8年4月1日現在法令等] |
| ta_1175 | …/shotoku/1175.htm | 200 | 2026-09-09 | fbf07a1c42e16c68 | [令和8年4月1日現在法令等] |
| ta_1900 | …/shotoku/1900.htm | 200 | 2026-09-09 | 68ad70cadf7276e2 | [令和8年4月1日現在法令等] |
| ta_2020 | …/shotoku/2020.htm | 200 | 2026-09-09 | edc9d0d3da6a76c7 | [令和8年4月1日現在法令等] |
| ta_2030 | …/shotoku/2030.htm | 200 | 2026-09-09 | 609d7d542866121b | [令和8年4月1日現在法令等] |
| ta_2040 | …/shotoku/2040.htm | 200 | 2026-11-02 | 2fb09b056bddb0db | [令和8年6月1日現在法令等] |
| ta_2260 | …/shotoku/2260.htm | 200 | 2026-10-20 | 638f0d78c9624168 | [令和8年4月1日現在法令等] |
| ta_1199 | …/shotoku/1199.htm | 200 | 2026-09-09 | 21507083e62c8014 | [令和8年4月1日現在法令等] |
| ta_1410 | …/shotoku/1410.htm | 200 | 2026-10-16 | df763b0259059e88 | [令和8年4月1日現在法令等] |
| shitsugi_shotoku_index | https://www.nta.go.jp/law/shitsugi/shotoku/01.htm | 200 | 2025-12-03 | 265c6c375a970b70 | — |
| kihon_shotoku_index | https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01.htm | 200 | 2025-12-25 | 74710f9540adcb9b | — |
| tebiki_index | https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/index.htm | 200 | 2026-03-04 | a1093b20b2fe4b6f | — |
| kihon_16_02 | https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/02.htm | 200 | 2024-01-18 | c2f88d72b969cb95 | — |
| kihon_01_07 | https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01/07.htm | 200 | 2026-10-02 | 52d60882df0b13f9 | — |
| kihon_19_01 | https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/19/01.htm | 200 | 2025-11-25 | 9e7dbd6d0d4d6914 | — |
| kihon_19_02 | https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/19/02.htm | 200 | 2025-11-25 | a9a3b2a8f9de88eb | — |
| tebiki_r07 | https://www.nta.go.jp/taxes/shiraberu/shinkoku/syotoku/r07.htm | 200 | 2026-10-20 | ff769ff6e512b73d | — |
| tebiki_r07_001pdf | https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/pdf/001.pdf | 200 | 2025-12-12 | 9691e822b247dd06 | PDF 23,044,322 バイト、48ページ（`/Type /Page` の数） |
| shinkokusho_r07_01pdf | https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/01.pdf | 200 | 2026-08-31 | 833e641919fbc1eb | 取得したが読んでいない |
| nencho2026_index | https://www.nta.go.jp/publication/pamph/gensen/nencho2026/01.htm | 200 | 2026-10-16 | 3e47f99112faf3ff | — |
| nenkin_gakusei | https://www.nenkin.go.jp/service/kokunen/menjo/20150331.html | 200 | 2026-10-14 | 649f918d5dc71c31 | **「国民年金保険料の追納制度」のページだった**（URL を取り違えた） |
| nenkin_gakutoku | https://www.nenkin.go.jp/service/kokunen/menjo/20150514.html | 200 | 2026-11-05 | cefed8451ba87800 | 「更新日：2026年11月5日」 |
| nenkin_koujo | https://www.nenkin.go.jp/service/kokunen/hokenryo/koujo/index.html | 200 | 2026-11-09 | 3a5bdedcefe64e2d | — |
| nenkin_r8koujo | https://www.nenkin.go.jp/service/kokunen/hokenryo/koujo/R8koujo/index.html | 200 | 2026-11-09 | faba3b5d13b7c8d6 | — |

SHA-256 の全桁は `scripts/results/IMPL_zeigaku_fetch_web/*.json` にある。

PDF「令和７年分 所得税及び復興特別所得税の確定申告の手引き」（tebiki_r07_001pdf）は、Read ツールで PDF の 1〜3、16〜17、19〜20、25〜30 ページを読んだ。PDF のページ番号と手引きの印刷ページ番号は1つずれる（PDF 3ページ＝手引き2ページ、PDF 25ページ＝手引き24ページ）。

## 5. 読んでいて気づいたこと（実測した事実）

1. TA No.2260（[令和8年4月1日現在法令等]）の「具体例」：所得税額を「7,000,000円×0.23 - 636,000円= 974,000円」と計算したあと、復興特別所得税を「947,000×0.021＝19,887円」と書いている（974,000 と 947,000 で数字の並びが違う）。974,000×0.021＝20,454 になる（`.work/text/20261109-145959_IMPL_zeigaku_ta/ta_2260.txt`）。
2. TA No.1175 の「（3）ロ」は私立学校法の条を「同法第64条第4項」と書いているが、所得税法第2条第1項第32号ロ（2025-12-31 版・2026-12-31 版）は「同法第百五十二条第五項（私立専修学校等）」と書いている（`scripts/results/IMPL_zeigaku_laws/shotoku_2025-12-31.txt`）。2024-12-31 版は「同法第六十四条第四項」だった（`shotoku_diff_2024-12-31_vs_2025-12-31.diff`）。
3. 所得税基本通達 120−4の2（`kihon_19_01`）は「法第120条第８項に規定する『その年の前々年分の当該業務に係る収入金額が1,000万円を超える』」と書いている。この内容は 2026-12-31 版の所得税法では第120条**第6項**、2027-01-01 版では第8項にある（§2）。
4. 日本年金機構の学生納付特例のページ（`nenkin_gakutoku`）は「（2）学生納付特例の申請可能期間と前年所得の関係（令和8年4月時点）」を参照しているが、HTML から取り出したテキストにその表の中身はなかった（画像か別の要素と思われるが確かめていない）。
5. 国税庁の質疑応答事例（所得税）の目次（`shitsugi_shotoku_index`、リンク 317件）のリンク文字列には、「社会保険料」「国民年金」「勤労学生」を含むものがなかった。
6. 所得税基本通達のページ `kihon_01_07` の `<title>` は「〔障害者（第28号関係）〕｜国税庁」で、同じページに〔勤労学生（第32号関係）〕（2−43〜2−45の２）がある。2−45の２ の末尾は「（令８課個2-8、課法12-7、課審5-3追加）」。

## 6. 推測の文書の手計算の検算（`scripts/IMPL_zeigaku_example_calc.py`）

- 入力（架空）と期待値の計算は `docs/inferences/20261109_impl-prep_zeigaku-examples.md`。このスクリプトは条文の値を手で写した検算用で、判定コアの実装ではない。
- 出力 `scripts/results/IMPL_zeigaku_example_calc/examples.md`：

| case | 年 | 給与所得 | 雑所得 | 合計所得 | 控除計 | 課税総所得 | 所得税 | 復興（端数そのまま） | 復興（1円未満切捨て） | 精算（手引きの順） | 精算（切捨てなし） | 120条 | 121条①一 | 申告義務 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Z1 | 2026 | 660000 | 0 | 660000 | 1310000 | 0 | 0 | 0 | 0 | 還付 40000 | 還付 40000 | False | True | False |
| Z1-R7 | 2025 | 750000 | 0 | 750000 | 1220000 | 0 | 0 | 0 | 0 | 還付 40000 | 還付 40000 | False | True | False |
| Z1-nokinro | 2026 | 660000 | 0 | 660000 | 1040000 | 0 | 0 | 0 | 0 | 還付 40000 | 還付 40000 | False | True | False |
| Z2 | 2026 | 660000 | 500000 | 1160000 | 1040000 | 120000 | 6000 | 126 | 126 | 還付 95134 | 還付 95134 | False | False | False |
| Z3 | 2026 | 660000 | 500000 | 1160000 | 1040000 | 120000 | 6000 | 126 | 126 | 納付 6100 | 納付 6100 | True | False | True |
| Z3-small | 2026 | 660000 | 200000 | 860000 | 1310000 | 0 | 0 | 0 | 0 | 納付 0 | 納付 0 | False | True | False |
| Z5-R7 | 2025 | 750000 | 321000 | 1071000 | 950000 | 121000 | 6050 | 2541/20（＝127.05） | 127 | 還付 95083 | 還付 95082 | False | False | False |

- 性質の検算：令和7年分（給与収入 651,000〜1,899,000円）・令和8年分（741,000〜2,190,000円）を 1,000円刻みで、勤労学生控除（27万円）の有無で課税総所得金額が変わる例は **0件**（`examples.json` の `property_kinro_no_effect`。合計所得金額 132万円以下の範囲だけを比べた）。
- 曜日（`datetime`）：2026-03-15 は日曜、2026-03-16 は月曜、2027-02-16 は火曜、2027-03-15 は月曜。

## 訂正の記録

この文書は 2026-11-09 の独立検証で訂正された。訂正の内容（訂正前・訂正後）と根拠は、実測 `docs/measurements/20261109_impl-prep_zeigaku-verification.md` §2 を参照。

訂正した節：§2（国民年金法施行令、復興財源確保法（R8→R9）、所得税法施行規則、別表第五の表の総行数）
