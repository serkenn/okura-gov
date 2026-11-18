# okura_monitor：法令・通知・通達の変更の監視（D9・D17 Q9・SCOPE §3）

一次情報の更新を毎日確かめて、変化があれば **issue の下書き**（Markdown と JSON）を作る。
GitHub への投稿は任意（`gh` コマンドがあれば `--post-github` で作る。既定は出力だけ）。

- **判定コア（okura_core）・記録（okura_records）を import しない。** 判定コアの YAML は、テキストとして読むだけ（`core_refs.py`）。
  判定コアからも、このパッケージを import しない。
- **ネットワークに出るのは、このパッケージだけ**（SCOPE §3）。
- **前回の状態は、利用側が渡すディレクトリ（`--state-dir`）に置く。** ライブラリ自身はデータを持たない。
- Python 3.11 の **標準ライブラリだけ**。依存のパッケージはない。

## 1. 監視対象

| 種類 | 対象 | 数 | 変化の見方 | 根拠（docs） |
|---|---|---|---|---|
| e-Gov 法令API v2 の改正履歴 | 判定コアのパラメータ（`rules/*/parameters/**.yaml` の `law`・`law_revision`）と概念辞書（`concepts.yaml` の `条文`）が引用する法令。`core_refs.collect` が静的に集める。ほかに `targets.EXTRA_LAWS` | 37 法令（2026-11-12。判定コアから 35、追加 2） | `/law_revisions/{id}`。初回は全件を基準にし、2回目から `updated_from=前回の確認日の前日`。新しい版・施行日などの変化を issue に。`updated` だけの変化は報告だけ | `measurements/20261109_R1-laws_egov-api-monitoring.md` §2・§3 |
| e-Gov 一括ダウンロードの日次 CSV | 更新法令データ（`file_section=3`） | 1 | 前回の続きの日から昨日まで（1回 7 日まで）。監視対象**外**の法令で、法令名・改正法令名が関係しうる語（`targets.BULK_RELATED_KEYWORDS`）を含む行を、その日の1つの issue に。監視対象の行は報告で API の状態と突き合わせる | 同 §5 |
| 厚労省「登載準備中の新着通知」 | `https://www.mhlw.go.jp/hourei/new/tsuchi/newindex.html` | 1 | 条件付き取得（If-Modified-Since → 304）。200 なら通知の一覧を読み、新しく載った通知のうち関係しうるもの（`targets.MhlwNoticeRule`：保険局・年金局〔医療課・調査課・企業年金を除く〕か、通知名に「被扶養者」などの語）を1件ずつ issue に。消えた通知（データベースへの登載で消える）は数えるだけ | `public-sources/20261109_R3-tsutatsu_monitoring-sources.md` §1.2、`measurements/20261109_R3-tsutatsu_fetch-and-monitor-probe.md` §1・§2-5 |
| 国税庁・日本年金機構の一覧ページ | `targets.PAGE_TARGETS`：国税庁の新着情報、所得税基本通達の改正一覧、源泉徴収義務者向け、日本年金機構の新着一覧 | 4 | 条件付き取得（ETag・Last-Modified → 304）。200 なら本文のテキスト（画像の alt を含む）を前回と比べる。新着の一覧は、足された行に監視の語があるときだけ issue に。ソフト404（タイトル）・404 は「ページが見つからない」の issue に | 同 §1・§2-1〜§2-4、`inferences/20261109_R3-tsutatsu_monitoring-design.md` I1・I2 |

**取得しないもの：** 官報（`kanpo.go.jp`）は robots.txt で巡回が禁止されている（`public-sources/20261109_R1-laws_monitoring-sources.md` §4）。
`fetch.py` がリダイレクト先を含めて拒否する。厚労省の RSS は通知の新着を含まず（R3 実測 §1）、再配布が禁止されているので使わない。

一覧は `python -I -X utf8 -m okura_monitor targets`（ネットワークに出ない）で見られる。表にない法令名が判定コアの出典にあれば「表にない法令名」として出る。

## 2. 準備（仮想環境）

```
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -m venv --without-pip .work\venvs\monitor
```

`.work\venvs\monitor\Lib\site-packages\okura_monitor_dev.pth` に、`packages\monitor\src` の絶対パスを1行で書く
（判定コアの `.work\venvs\core` の `okura_dev.pth` と同じ方法）。`pip install -e packages/monitor`（`pyproject.toml`）でもよい。

## 3. 使い方

```
.work\venvs\monitor\Scripts\python.exe -I -X utf8 -m okura_monitor run --state-dir .work\monitor\state --out .work\monitor\out
```

| 引数 | 意味 |
|---|---|
| `--state-dir`（必須） | 前回の状態を置くディレクトリ。なければ作る。消すと次の実行が「初回」になる |
| `--out`（必須） | 出力の親ディレクトリ。実行ごとに `<YYYYMMDD-HHMMSS>/` を作る |
| `--core-src` | 判定コアの src（既定はこのリポジトリの `packages/core/src` を探す） |
| `--sources` | `egov,bulk,mhlw,pages` から選ぶ（既定は全部） |
| `--law-id`（複数可） | e-Gov の改正履歴を確かめる法令をこれだけにする（試すとき用） |
| `--bulk-max-days` | 日次 CSV を1回で遡る日数（既定 7） |
| `--min-interval` | リクエストの間隔（秒。既定 1.5、1 未満にはしない）。User-Agent は `okura-gov-monitor/0.1` |
| `--post-github`・`--repo OWNER/NAME`・`--label`（複数可） | `gh issue create` で投稿する。投稿した key は `<state-dir>/github_posted.json` に記録し、2回投稿しない。ラベルはリポジトリに先に作っておく |

- `-I` なしで起動すると終了コード 2 で止まる（カレントディレクトリの `.py` を読まないため）。
- **各情報源の初回は、状態を記録するだけで issue を作らない。** 日次 CSV は初回に「昨日」を起点として記録し、次の実行から先を見る。
- 取得に失敗した対象は状態を進めない（次の実行でやり直す）。終了コード：0 完了、2 使い方の誤り、3 一部を取得できなかった（出力は書く）。

出力：

```
<out>/<YYYYMMDD-HHMMSS>/
  report.md       要約（下書きの一覧、取得の誤り、表にない法令名）
  report.json     情報源ごとの結果（e-Gov の法令ごとの件数、日次 CSV の日ごとの行数・仮の施行日の数・API との突き合わせ、新着通知、ページ）
  issues/<key>.md   issue の本文（GitHub にそのまま貼れる）
  issues/<key>.json 同じ内容の JSON
```

issue の下書きの欄（D9）：何が変わったか、出典 URL（e-Gov の版のページ・API・通知の PDF など）、施行日（版ごと。未定・仮の日付は空にして備考に定めを書く）、
適用年分（**自動では決めない**。所得税は附則の「令和X年分以後」で決まることなどの手がかりだけ：R1 仮説 H2）、
影響する層（パラメータ・計算式・概念辞書・注入点・中間表現・記録・出力の整形。チェックは人が付け、判定コアの出典から言える候補だけを添える）、
関係する概念・パラメータ・モジュールの候補（その法令・通知の番号を引用している判定コアの出典から機械的に拾う）、対応の手順（施行日つきのテストを先に書く）。
**基準額などの値は書かない**（原文で確かめるまで使わない）。

状態のディレクトリ：`egov_revisions/<法令ID>.json`（版の一覧と確認日）、`egov_bulk.json`（日次 CSV の続きの日）、
`mhlw_new_notices.json`（通知の PDF の URL の一覧と Last-Modified）、`pages/<id>.json`（ETag・Last-Modified・抽出したテキスト）、`github_posted.json`。

## 4. 定期実行の例

1日1回（朝）。リクエストは 1 回の実行で約 45 回（e-Gov 37、日次 CSV 1〜7、厚労省 1、ページ 4）。日次 CSV の ZIP は日によって 2MB〜76MB（R1 実測 §5）。

Windows のタスク スケジューラ：

```
schtasks /Create /SC DAILY /ST 07:30 /TN okura-gov-monitor /TR "C:\Users\user\Documents\okura-gov\.work\venvs\monitor\Scripts\python.exe -I -X utf8 -m okura_monitor run --state-dir C:\Users\user\Documents\okura-gov\.work\monitor\state --out C:\Users\user\Documents\okura-gov\.work\monitor\out"
```

cron（Linux・macOS。仮想環境の作り方は §2 と同じ。`bin/python` になる）：

```
30 7 * * * /path/to/okura-gov/.work/venvs/monitor/bin/python -I -X utf8 -m okura_monitor run --state-dir /path/to/state --out /path/to/out --post-github --repo OWNER/NAME
```

状態のディレクトリは実行のたびに同じものを渡す。CI で動かす場合は、状態のディレクトリをキャッシュなどで次の実行に引き継ぐ。

### 4.1 本番の定期実行：GitHub Actions（2026-11-12 ユーザーの決定）

監視は GitHub Actions の `.github/workflows/law-monitor.yml` で毎日 07:30（日本時間）に動かす。上のタスク スケジューラ・cron は手元で試すときの例として残す。

| 項目 | 中身 |
|---|---|
| きっかけ | `schedule`（毎日 22:30 UTC）と手動の `workflow_dispatch`（入力 `post_github`：issue を作るか。既定は作る） |
| 状態・出力 | 専用のブランチ `monitor-state`（main と履歴を共有しない孤立したブランチ）の `state/`（`--state-dir`）と `out/<日時>/`（`--out`。新しい 90 回分だけ残す）。ブランチがなければ初回として作る（初回は基準を記録するだけで issue を作らない：§3） |
| issue | 定期の実行と `post_github=true` の手動の実行で `--post-github`。ラベル `monitor`・`law-change`（ワークフローが `gh label create --force` で用意する）。同じ key は2回作らない（`state/github_posted.json`） |
| 要約 | 実行ごとの `report.md` を、ワークフローの実行の要約（Summary）に出す |
| 終了コード | 0 完了。3 一部を取得できなかった → 警告にして状態は保存する（その対象は次の実行でやり直す）。それ以外 → 失敗にして状態を保存しない |
| 依存 | GitHub 公式の `actions/checkout`（コミットの SHA で固定）だけ。Python はランナー（ubuntu-24.04）の `python3`（3.11 以上を確かめる）。`gh` はランナーに入っているもの |
| 権限 | `contents: write`（`monitor-state` への push）・`issues: write`。トークンは実行ごとの `GITHUB_TOKEN` |

- **2026-11-13 の状態：** ワークフローを main に置いて手動で動かしたが、`startup_failure`（ジョブが作られない）で止まった。`echo ok` だけの最小のワークフローでも同じだったので、
  アカウントの側（非公開リポジトリの Actions の利用枠・支払いの設定など）が原因と考えている（HANDOFF §5.2 の 0.）。同じ日に手元で1回動かした実行（`--state-dir .work/monitor/trial/state`、issue を作らない）は、
  取得の誤り 0・リクエスト 42 回で完了した。
- 状態を最初からやり直すとき：`monitor-state` ブランチを消す（次の実行が初回になる。投稿済みの key の記録も消えるので、同じ変化の issue がもう一度作られうる）。
- 取得の誤りが続くとき（ランナーは国外の回線）：実行の要約の「取得の誤り」を見る。特定のサイトが国外からの取得を拒むなら、その情報源だけ手元のタスク スケジューラで動かす（`--sources`）。

**issue が作られたあと（ユーザーの決定：人が Claude Code で対応する）：** issue の本文の「対応の始め方」のとおり、このリポジトリで Claude Code を開き、
「スキル law-change で、この issue に対応して」と issue の URL か番号を渡す。エージェントは `gh issue view` で本文を読み、スキル `law-change` の手順
（原文の確認 → 施行日つきのテストを先に → パラメータ・式・概念辞書 → 影響する層）で進める。値に関係しない変化は、確かめた結果を書いて issue を閉じる。

## 5. 対象の追加の手順

- **法令：** 判定コアのパラメータ・概念辞書の出典（`law:`・`条文:`）に法令名を書けば、次の実行から自動で対象に入る。
  `targets` で「表にない法令名」に出たら、e-Gov 法令API（`/laws?law_title=<法令名>`）で法令IDを確かめ、`targets.LAW_NAMES` に足す（取得日をコメントに書く）。
  略称・番号の書き方（`所令`、`平成16年政令第298号` など）も `LAW_NAMES` に足せる。判定コアが引用しない法令を監視するときは `targets.EXTRA_LAWS` に理由つきで足す。
- **一覧ページ：** `targets.PAGE_TARGETS` に `PageTarget(id, 機関, 名前, URL, keywords=…)` を足す。先に条件付き取得（304）とソフト404 の有無を確かめ、
  `docs/measurements` に記録する（`scripts/R3_monitor_probe.py` の候補に足して実行する）。robots.txt で禁止されているサイトは足さない。
- **厚労省の通知の絞り込み：** `targets.MhlwNoticeRule`（部局、除く課、通知名の語）。
- **日次 CSV の「関係しうる」語：** `targets.BULK_RELATED_KEYWORDS`。

## 6. 推測に基づく扱い（仕様で確かめていない）

- 日次 CSV の「令和九十九年…」は施行日未定の改正に入る仮の日付とみなし、施行日を空にする（R1 実測 §5：本文URL が `2117…`、未施行が ○、施行日備考に実際の定め）。元号の年が 99 の日付すべてに当てはめる。
- 日次 CSV で HTTP 500・404 が返った日は「その日の更新なし」として先へ進む（日曜に 500 が返った：同 §5）。公開が遅れた日を取りこぼすおそれがある。
- `updated` だけが変わった版は issue にしない（新しい版が加わると隣の版の `updated` も変わる：同 §3）。

## 7. テスト

ユニットテストだけ（D24）。取得はスタブ（`tests/stubs.py`）。

```
.work\venvs\core\Scripts\python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/monitor/tests
```

| ファイル | 中身 |
|---|---|
| `test_wareki.py` | 漢数字、和暦、「令和九十九年」の仮の日付 |
| `test_egov.py` | 日次 CSV の解析（BOM・引用符・仮の日付）、ZIP から CSV、HTTP 500、遡る日付、版の差分（新・変化・updated だけ）、初回と updated_from |
| `test_pages.py` | テキストの抽出（alt）、初回と 304、本文が同じ 200、差分の行、ソフト404、Shift_JIS |
| `test_mhlw.py` | 新着通知の解析（部局・掲載日・発出日・番号・添付）、関係しうるかの判定、差分 |
| `test_issues.py` | 判定コアの出典の収集（パラメータ名・概念・同施行規則・表にない名前・通知）、issue の下書き（改正法令ごとのまとめ、D9 の欄、未定の施行日）、日次 CSV の下書き、通知の候補、gh の投稿を1回だけ |
