# R2 OpenFisca-Core 46.0.1 の実測

- 作成日：2026-11-09（R2 担当）
- 種別：実測（実際に動かして確かめたこと）
- コードを読んで分かったことは `docs/public-sources/20261109_R2-tools_openfisca-core-source.md`（以下「公開資料」）。
- 環境：Windows 11 Pro 10.0.26200、Python 3.11.9（MSC 64bit）、ロケールの既定の文字コードは cp932。

## 再実行の方法（根拠のスクリプト）

| スクリプト | 何をするか | 出力 |
|---|---|---|
| `scripts/R2_openfisca_check.py` | 試験用の国パッケージを一時ディレクトリに書き出し、T00〜T14 を実行する。先頭に venv の作り方と実行方法がある | `scripts/results/R2_openfisca_check/results_utf8.json`、`summary_utf8.txt`（`-X utf8` で実行）、`results_locale.json`、`summary_locale.txt`（UTF-8 モードなし） |
| `scripts/R2_openfisca_deps_osv.sh` ＋ `scripts/R2_osv_summarize.py` | venv の依存一覧と OSV での照会 | `scripts/results/R2_openfisca_deps_osv/`（`freeze.txt`、`summary.md`、`vulns/*.json`、`queried_at.txt`） |
| `scripts/R2_pypi_release_history.py` | PyPI のリリース履歴 | `scripts/results/R2_pypi_release_history/` |

```
uv venv .work/venvs/R2-openfisca --python 3.11
uv pip install --python .work/venvs/R2-openfisca/Scripts/python.exe --only-binary :all: "openfisca-core[web-api]==46.0.1"
.work/venvs/R2-openfisca/Scripts/python.exe -I -X utf8 scripts/R2_openfisca_check.py
.work/venvs/R2-openfisca/Scripts/python.exe -I scripts/R2_openfisca_check.py
bash scripts/R2_openfisca_deps_osv.sh
```

- パラメータの値（100、200、300）は**ダミー値**で、法令の基準額ではない。
- 年齢の計算（`満年齢_日`）は暦の上で誕生日を過ぎたかで数える試験用のもので、法的な年齢の数え方を表していない。
- Web API は Flask アプリ（`create_app`）を werkzeug の開発用サーバーで `127.0.0.1` の空きポートに立てて確かめ、最後に止めた（`results_utf8.json` の `web_api_server.stopped: true`）。
  `openfisca serve`（gunicorn）は Windows で起動しないため（T13）。アプリ層の挙動（CORS、本文の大きさ、計算量）はサーバーの種類によらないが、gunicorn 固有の挙動（待ち受けアドレス、タイムアウト）は未実測。

## 1. インストールした版と既知の脆弱性

- `uv pip install --only-binary :all: "openfisca-core[web-api]==46.0.1"` で28パッケージ（`scripts/results/R2_openfisca_deps_osv/freeze.txt`）：
  blinker 1.9.0、click 8.5.1、colorama 0.4.6、dpath 2.2.0、flask 3.1.3、**flask-cors 3.0.10**、**gunicorn 22.0.0**、iniconfig 2.3.1、itsdangerous 2.2.0、jinja2 3.1.6、markupsafe 3.0.4、numexpr 2.14.2、numpy 2.4.6、openfisca-core 46.0.1、packaging 26.3、pendulum 3.3.0、pluggy 1.7.0、psutil 7.2.2、pygments 2.21.0、pytest 9.2.0、python-dateutil 4.0.0、pyyaml 6.0.3、six 1.17.0、sortedcontainers 2.4.0、strenum 0.4.15、typing-extensions 4.16.0、tzdata 2026.6、werkzeug 3.1.9。
- OSV（2026-11-09 照会）：該当は flask-cors 3.0.10 の5件だけ（CVE-2024-6866、-6839、-6844、-1681、-6221）。他の27パッケージは該当なし。詳細は `scripts/results/R2_openfisca_deps_osv/summary.md` と公開資料 §1.4。
- PyYAML の wheel は libyaml を含む（`yaml/_yaml.cp311-win_amd64.pyd`。`results_*.json` の `pyyaml_has_libyaml: true`）。そのためパラメータとテストの読み込みは、どちらも `yaml.cyaml.CLoader`（安全でない読み込み）になった（`parameter_yaml_loader`、`test_yaml_loader`）。

## 2. 結果

### 2.1 日本語の名前と Windows（T00）

| 条件 | 結果 |
|---|---|
| `-I`（UTF-8 モードなし、cp932） | **失敗**。パラメータの YAML（`parameters/ダミー/所得要件.yaml`、UTF-8）を読むところで `UnicodeDecodeError: 'cp932' codec can't decode byte 0x83`（`summary_locale.txt`） |
| `-I -X utf8` | 成功。エンティティ名・役割名・変数名・パラメータのディレクトリ名とファイル名をすべて日本語にして読み込めた（エンティティ5、変数23） |

- 原因は公開資料 §2.2（`open()` に `encoding` が無い）。Linux・macOS の UTF-8 ロケールでは起きない（I）。
- Windows で使うなら `-X utf8`（または `PYTHONUTF8=1`。ただし `-I` は環境変数を無視するので `-X utf8` を使う）が必要。

### 2.2 グループと役割（T01〜T05、T14、T12n）— R4 向け

試験用のエンティティ（`scripts/R2_openfisca_check.py` の `ENTITIES_PY`）：

| グループ | 役割（`max`） |
|---|---|
| 生計 | 生計維持者（1）、生計構成員 |
| 住民票世帯 | 世帯主（1）、世帯員 |
| 健康保険 | 被保険者（1）、被扶養者 |
| 申告 | 納税者（1）、扶養親族 |

シナリオ：父・母・子（20歳、大学生、住民票は親と別）。子は 生計＝父と同じ、住民票世帯＝単独、健康保険＝父の被扶養者、申告＝父の扶養親族。母は自分の健康保険の被保険者。

| ID | 確かめたこと | 結果 |
|---|---|---|
| T01 | 種類の違うグループ4つを同時に定義し、1人が4種類すべてに属する | **できた**。子の `本人_生計の給与収入合計`＝6300（父・母・子の合計）、`本人_住民票世帯の人数`＝1、`本人_健保で被扶養者か`＝true、`本人_健保の被保険者の給与収入`＝5000（父の値）、`本人_申告で納税者か`＝false。グループ側の集計も正しい（父の健保の被扶養者数1、母の健保0、世帯A 2人・世帯B 1人） |
| T01 | 生計と住民票世帯が食い違う（生計は同じ、住民票は別） | **表せた**（上の値） |
| T02 | 同じ種類のグループの2つのインスタンスに同じ人（子を父の健保と母の健保の両方の被扶養者にする） | **エラー**：`子 has been declared more than once in 健康保険一覧`。Web API でも 400（T12n） |
| T03 | 1つのグループで1人に2つの役割（父を 生計維持者 と 生計構成員 の両方に） | **エラー**：`父 has been declared more than once in 生計一覧` |
| T05 | `max: 1` の役割に2人 | エラー：`There can be at most 1 世帯主一覧 in a 住民票世帯. 2 were declared in '世帯A'.` |
| T04 | どのグループにも書かなかった人（祖母） | **エラーにならず**、祖母だけの健康保険インスタンス「祖母」が自動で作られ、役割は最初の役割の「**被保険者**」になった |
| T14 | 所属に期間をつける（`"被扶養者一覧": {"2025-10": ["子"]}`） | エラー：`Invalid type: must be of type 'Array'.` 所属の書き方に期間は無い |
| T14b | 所属の内部表現 | 健康保険の `members_entity_id` は長さ3（人数）の ndarray、`members_role` も長さ3。期間の次元は無い |

まとめ（F）：

- **複数のグループの種類**：定義できる。
- **1人が複数のグループに属する**：種類が違えばできる。**同じ種類の2つのインスタンスには属せない**。
- **1つのグループ内で1人が複数の役割**：できない。
- **所属・役割を期間で変える**：1つのシミュレーションの中ではできない。
- 書き忘れた人は黙って「最初の役割」になる。

### 2.3 期間（T06、T06b、T06c、T06x）

| ID | 確かめたこと | 結果 |
|---|---|---|
| T06 | 月の変数（`月額収入`、2025-01〜12 に 10,20,…,120、2026-01 に 1000）を年で合計（`options=[ADD]`） | 780 |
| T06 | 月の途中から始まる1年（`year:2025-10`＝2025-10-01〜2026-09-30）で合計（将来の見込みのような期間） | 1330（=100+110+120+1000。2026-02〜09 は入力が無く 0） |
| T06 | 年額 1200 を月の変数に入れる（`set_input_divide_by_period`） | 2025-03 の値は 100 |
| T06 | 日の変数（`満年齢_日`）、2005-12-31 生まれ | 2025-12-30 → 19、2025-12-31 → 20。年の変数 `満年齢_年末`（その年の12月31日の日の値を引く）→ 20 |
| T06 | 永久（ETERNITY）の変数（生年月日）を日の式から引く | できた |
| T06b | 月の変数を年の期間で直接求める | エラー（ADD を使え、というメッセージ） |
| T06c | 年の変数に月の期間で入力する | エラー（`set_input` が無いと年単位でしか入れられない） |
| T06x | 同じシミュレーションで、ある人は月ごと、別の人は年額で同じ変数に入力 | **エラー**：`Inconsistent input: variable 月額収入 has already been set for all months contained in period 2025 ...`。人によって入力の粒度を変えられない |

### 2.4 パラメータの施行日・改正・テスト（T07〜T09）

- T07（パラメータ：2020-01-01 から 100、2025-01-01 から 200）：
  - 2019-12-31 → `ParameterNotFoundError`（値の始まりより前は**エラー**。0 や None にはならない）。2020-01-01 → 100、2024-12-31 → 100、2025-01-01 → 200、2030-01-01 → 200。
  - 年の変数の式で `parameters(period)` を使うと、年の初日（1月1日）の値になる（2024 → 判定 false、2025 → true。給与収入150）。
  - `formula_2020_01_01` と `formula_2025_01_01`：2019 → 0（式が無い期間は既定値）、2024 → 1、2025 → 2。
  - 年の変数を月の期間で求めるとエラー。
- T08（改正）：`Reform` で「2026-01-01 から 300」に変更し、`update_variable` で `formula_2026_01_01` を足した。
  基準：2025・2026 とも 200。改正後：2025 は 200 のまま、2026 は 300、式も 2026 だけ 3。元の制度は変わらない。
- T09（YAML テスト、日本語の変数名・グループ・役割を含む4件、うち1件は意図的に誤り）：`3 passed, 1 failed`、終了コード1。
  施行日の前後で別の期待値を書いたテスト（2024 は false、2025 は true）も正しく判定された。
  - 補足：`run_tests` に `{"verbose": True}` だけを渡すと `max_depth` が `None` のままで `TypeError` になった。CLI（`openfisca test --verbose`）は `--max-depth` の既定が `sys.maxsize` なので起きない（公開資料ではなく venv の `openfisca_core/scripts/openfisca_command.py:122-128` で確認）。スクリプトは verbose を使わない形に直した。

### 2.5 危険な入力（T10、T11）

- T10：パラメータの YAML に `!!python/object/apply:builtins.len [[1, 2, 3]]` と `!!python/object/apply:builtins.open [<一時ファイル>, 'w']` を書いた。
  **読み込めて値は 3 になり、一時ファイルが作られた**（`parameter_marker_created: true`）。
  テストの YAML に同じ `open` を書いたところ、テストの収集はエラーになった（終了コード2）が、**その前に一時ファイルが作られた**（`test_marker_created: true`）。
  → パラメータ・テストの YAML から任意の Python 呼び出しができる。
- T11：数値の変数（`給与収入`）に文字列を入れた（Python API）。
  `"1000*2"` → 2000、`"2**10"` → 1024、`"abs(-5)"` → 5、`"where(1>0, 7, 8)"` → 7（**式として評価される**）。
  `"__import__('os').getcwd()"`、`"().__class__"` → `SituationParsingError`（評価されなかった）。
  Web API でも `"100*3"` が 300 として扱われた（T12o。判定は false＝300 > 200。応答の入力欄は文字列のまま返る）。

### 2.6 Web API（T12a〜T12p）

| ID | 確かめたこと | 結果 |
|---|---|---|
| T12a | `GET /` | 状態コード **300**、`Access-Control-Allow-Origin: *` |
| T12b・c・d | `/entities`、`/variable/給与収入`（URL エンコード）、`/spec` | どれも 200。日本語の名前がそのまま使える。`/spec`（OpenAPI）にも日本語の変数名が入る。`/variable` の `source` は `https://openfisca.org/blob/0.0.0r2_test_country\\variables.py#L19-L23` のような壊れた URL（Windows のパス区切りのため） |
| T12e | `POST /calculate`（T01 のシナリオ、日本語） | 200。T01 と同じ値。Enum は名前（`"給与"`）、bool、日付が JSON で返った |
| T12f | 外部オリジン（`Origin: https://evil.example`）からの CORS の事前確認（`Access-Control-Request-Private-Network: true` 付き） | 200、`Access-Control-Allow-Origin: https://evil.example`、`Access-Control-Allow-Methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT`。`Access-Control-Allow-Private-Network` は**返らなかった** |
| T12g | 外部オリジンからの `POST /calculate` | 200、計算結果を返し、`Access-Control-Allow-Origin: https://evil.example` |
| T12h | `Host: evil.example`、`X-Forwarded-Host: evil2.example` | welcome の文の中の URL がそれぞれ `http://evil.example/spec`、`http://evil2.example/spec` になった |
| T12i | 約30MB（31,457,389 バイト）の JSON 本文 | 本文を全部受け取って解釈し、0.4秒で 400（未定義のエンティティ）。**大きさの上限は無かった** |
| T12j | `axes` の `count` を増やす（1人＋4グループ、Web API） | 1,000 → 0.03秒、10,000 → 0.11秒、100,000 → 0.73秒（RSS +47MB）、**1,000,000 → 6.3秒、RSS 122→525MB、ピーク 763MB**。計算量はほぼ `count` に比例し、上限は無い。どれも最後は 500（`'子' is not in list`。`/calculate` は axes の結果を返せない）だが、**計算とメモリの確保は終わってから**エラーになる |
| T12k | 同じ期間で循環する変数 | 0.01秒で 500：`Circular definition detected on formula 循環A@2025`（止まらなくなることは無い） |
| T12l | 前の年を参照し続ける変数（`前年までの累積 = 前年の値 + 1`） | 0.01秒で 200、値は **1.0**。前の年を既定値 0 とみなして打ち切り、**エラーにならない** |
| T12m | 存在しない変数 | 404 |
| T12p | `POST /trace` | 200。参照したパラメータの名前・日付・値（`ダミー.所得要件<2025-01-01>: 200`）と依存する変数が返る |

### 2.7 `openfisca serve`（T13）

- `.work/venvs/R2-openfisca/Scripts/openfisca.exe serve --country-package r2_test_country` は**すぐに終了**（終了コード1）：
  `ImportError: OpenFisca is missing some dependencies to run the Web API: 'No module named 'grp''`。
  `fcntl` も無い（T13b：`fcntl_available: false`）。**Windows では `openfisca serve` は動かない**。待ち受けたものは無い（ポート5000を netstat で確認し、LISTEN なし）。
- そのため「既定の待ち受けアドレスが 127.0.0.1:5000 であること」は、コード（公開資料 §2.5）でしか確認できていない。

## 3. 分からなかったこと・残っている実測

- Linux（または WSL・コンテナ）で `openfisca serve` を起動し、既定の待ち受けアドレス（127.0.0.1:5000）、ワーカー数3、タイムアウト1200秒が実際にそうなるかを確かめること。この PC の WSL には `docker-desktop` しか無く、今回は行っていない。
- `axes` の `count` を 10,000,000 以上にしたときの挙動（メモリを使い果たすか）は、PC を止めるおそれがあるので試していない。1,000,000 までの結果からは、時間・メモリともほぼ比例して増える（I）。
- 外部の Web ページから `127.0.0.1` への要求を、実際のブラウザ（Chrome などの Private Network Access / Local Network Access の仕組み）が止めるかどうかは試していない。サーバーが CORS で許可していることだけを確かめた。
- numexpr の検査をすり抜ける式があるかは調べていない。
- 一時ディレクトリ（`%TEMP%\r2_openfisca_*`）はスクリプトが消さない（中身の確認用）。
