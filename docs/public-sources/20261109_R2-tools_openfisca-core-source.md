# R2 OpenFisca-Core のソースと公開資料

- 作成日：2026-11-09（R2 担当）
- 種別：公開資料の情報（ソースコードを静的に読んで分かったこと、ライセンス文、PyPI・OSV の記載）
- 実行して確かめたことは別ファイル：`docs/measurements/20261109_R2-tools_openfisca-core-runtime.md`
- OpenFisca-Japan のコードは別ファイル：`docs/public-sources/20261109_R2-tools_openfisca-japan-source.md`
- ソースは `git clone` で `.work/downloads/20261109-132258_openfisca-core/` に取得し、Read / grep / git log だけで読んだ
  （clone の中でインタプリタ・ビルド・テストは実行していない）。`.work/` は git 管理外なので、下のコミットで再取得して検証すること。
- 記号：F＝コード・原文で確認、E＝外部の二次情報、I＝推測（ここでは最小限。判断は hypotheses に書く）

## 0. 確認したバージョン

| 項目 | 値 |
|---|---|
| リポジトリ | https://github.com/openfisca/openfisca-core （取得日 2026-11-09） |
| 読んだコミット | `db0484b54871b0a73e673478b3153841dba908e9`（main、2026-10-23、pyproject の version は `46.0.2`、未リリース） |
| 最新タグ／PyPI 最新 | `46.0.1`（コミット `5a9fb9e6d30b2b002c1ec1a022d57dfecffeafd4`、2026-10-19）。PyPI の最新も 46.0.1 |
| タグと main の差 | `git diff 46.0.1 HEAD -- openfisca_core openfisca_web_api` は差分なし。違いは `pyproject.toml` の version 行だけ。**以下の行番号は 46.0.1 と main で同じ** |
| PyPI の wheel | `openfisca_core-46.0.1-py3-none-any.whl`、sha256 `09a4cdc1627684cb97a11d1aac50577fb8f0d3549b742480c5d3e1b8d9fa3a31`（`scripts/results/R2_pypi_release_history/OpenFisca-Core.txt`） |
| wheel とソースの一致（F） | 実測用 venv に入れた wheel の `openfisca_core/`・`openfisca_web_api/` を clone と `diff -rq --strip-trailing-cr` で比べ、差分なし（改行コードだけ違う。clone 側は Windows の autocrlf） |

## 1. ライセンス・保守

### 1.1 ライセンス（F）

- `LICENSE`：GNU AFFERO GENERAL PUBLIC LICENSE Version 3（1-2行）。`pyproject.toml:46` は `license = "AGPL-3.0-or-later"`、`publiccode.yml:87` も同じ。
- 判断に関係する原文（`LICENSE` の行番号）：
  - 68-82行：「The Program」は本ライセンスの対象の著作物。「modify」は著作権の許可が要る形で全部または一部を複製・翻案すること。その結果が「modified version」または「work based on」。「covered work」は改変していない Program か、Program に基づく著作物。
  - 226-232行：別個で独立した著作物で、性質上 covered work の拡張ではなく、より大きなプログラムを形作るように結合されていないものとの寄せ集め（aggregate）には、本ライセンスは及ばない。
  - 540-551行（第13条）：Program を**改変した場合**、改変版がネットワーク越しの利用者とのやりとりに対応しているなら、その利用者すべてに対応するソースを受け取る機会を目立つ形で提供しなければならない。
- FSF の GPL FAQ（https://www.gnu.org/licenses/gpl-faq.html 、「MereAggregation」「GPLPlugins」などの項）を一次情報として取りに行ったが、**取得できなかった**（2026-11-09、curl は 403、WebFetch は 429）。
  したがって「import した自作パッケージは結合著作物になるか」「HTTP で呼ぶだけのクライアントには及ばないか」について、FSF の見解の原文はこの文書では確認していない。

### 1.2 リリース・Python・保守（F：git log、E：PyPI。取得日 2026-11-09）

- `pyproject.toml:13` `requires-python = ">=3.11"`。classifiers は Python 3.11〜3.13、`Operating System :: POSIX`（14-22行）。Windows は classifiers に無い。
- PyPI のリリース（`scripts/results/R2_pypi_release_history/OpenFisca-Core.txt`）：直近1年（2025-11-09 以降）で 43.4.4（2025-11-26）から 46.0.1（2026-10-19）まで21回。メジャー版が 43→44（2025-12）→45（2026-09）→46（2026-10）と1年で3回上がっている。
- `CHANGELOG.md` 先頭：46.0.0 で Python 3.10 のサポートを削除、`tracker` extra を削除（「not maintained nor used」）、pip から uv へ移行。
- 直近1年（2025-11-09 以降）の main のコミット 321件。作者の上位：Thomas Guillet 168、Mahdi Ben Jelloul 68、benoit-cty 46、Vincent Lara 20（`git log --since=2025-11-09`）。

### 1.3 依存（F：`pyproject.toml`）

- 実行時（25-44行）：PyYAML `>=6.0.1,<7.0`、StrEnum、dpath、numexpr `>=2.10.1,<3.0`、numpy、pendulum、psutil、**pytest `>=8.3.3,<10.0`**（実行時の依存に pytest が入っている）、sortedcontainers、typing_extensions。
- `web-api` extra（74-79行）：Flask `>=2.2.3,<4.0`、**Flask-Cors `>=3.0.10,<4.0`**、**gunicorn `>=21.0,<23.0`**、Werkzeug。
  Flask-Cors は 4.0 未満に上限があるため、下の 1.4 の修正版（4.0.2、6.0.0）を入れられない。
- 実際に入った版と既知の脆弱性は実測文書の §1。

### 1.4 依存の既知の脆弱性（E：OSV。照会日 2026-11-09。`scripts/R2_openfisca_deps_osv.sh`）

- 照会した28パッケージのうち、該当があったのは **flask-cors 3.0.10 だけ**（5件。結果は `scripts/results/R2_openfisca_deps_osv/summary.md`）。
  - CVE-2024-6866（大文字小文字の扱い、修正 6.0.0）、CVE-2024-6839（パスの正規表現の照合、修正 6.0.0）、CVE-2024-6844（CORS の照合の不整合、修正 6.0.0）、CVE-2024-1681（debug ログへの注入、修正 4.0.1）、CVE-2024-6221（`Access-Control-Allow-Private-Network` を既定で true にする、修正 4.0.2）。
  - CVE-2024-6221 の OSV の説明文は「version 4.0.1」の問題としている一方、影響範囲は `introduced: 0` から `fixed: 4.0.2` になっている。
    3.0.10 のコードに Private-Network の処理は無い（F：venv の `flask_cors/` を grep して該当なし）。実測でもこのヘッダは返らなかった（実測文書 T12f）。
- gunicorn 22.0.0、PyYAML 6.0.3、numexpr 2.14.2、Werkzeug 3.1.9、Flask 3.1.3 などは該当なし。

## 2. 安全性（コードで確認したこと）

### 2.1 YAML の読み込み：安全な読み込みではない（F）

- パラメータ：`openfisca_core/parameters/config.py:8-20` は `from yaml import CLoader as Loader`、無ければ `from yaml import Loader`。
  `openfisca_core/parameters/helpers.py:45-47` で `config.yaml.load(f, Loader=config.Loader)`。
- テスト：`openfisca_core/tools/test_runner.py:95-109` の `import_yaml()` は `CLoader`、無ければ **`SafeLoader`**。543-544行で `yaml.load(file, Loader=Loader)`。
  libyaml の有無で、安全な読み込みかどうかが変わる。
- PyYAML 6.0.3 では `CLoader`（`yaml/cyaml.py:44`）も `Loader`（`yaml/loader.py:41`）も `Constructor` を使い、`Constructor` は `UnsafeConstructor` の別名（`yaml/constructor.py:747-748`）。
  つまり `!!python/object/apply:` などのタグで任意の Python 呼び出しができる（F：venv に入った PyYAML 6.0.3 を読んで確認。実測文書 T10 で実行も確認）。
- 意味：パラメータの YAML とテストの YAML は、**Python のコードと同じ信頼度で扱う必要がある**。外部から受け取った YAML をそのまま置いてはいけない。

### 2.2 ファイルを開くときに文字コードを指定していない（F）

- `parameters/helpers.py:45` の `open(file_path)`、`tools/test_runner.py:543` の `open(self.path)` は `encoding` を指定していない。
  Python は既定でロケールの文字コードを使うので、Windows（cp932）では UTF-8 の日本語 YAML を読めない可能性がある（実測文書 T00 で確認）。

### 2.3 eval / exec / 動的 import（F）

| 箇所 | 内容 | 外部の入力が届くか |
|---|---|---|
| `openfisca_web_api/scripts/serve.py:32-35` | `--configuration-file` で指定したファイルを `exec` する（gunicorn の設定ファイルと同じ考え方） | コマンドラインで指定したファイルだけ。HTTP の要求からは届かない |
| `openfisca_core/taxbenefitsystems/tax_benefit_system.py:224-276` | 変数を定義した `.py` を `spec.loader.exec_module` で読み込む | 国パッケージ・拡張のディレクトリだけ |
| 同 `:295-320`（`load_extension`）、`:322-`（`apply_reform`）、`openfisca_core/scripts/__init__.py:39,57,81`、`openfisca_web_api/loader/tax_benefit_system.py:11` | `importlib.import_module` で国パッケージ・拡張・改正を読み込む | コマンドライン引数、YAML テストの `reforms:`・`extensions:` キー（`test_runner.py:72-74, 779-797`）。HTTP の要求からは届かない |
| `openfisca_core/commons/misc.py:79-106`（`eval_expression`） | `numexpr.evaluate(expression)`。`KeyError, TypeError, SyntaxError` のときは文字列をそのまま返す | **届く**。数値型の変数に文字列を入れると評価される：`variables/variable.py:451-452`、`holders/holder.py:239-240`。Web API の `/calculate` の入力もここを通る |

- numexpr 2.14.2（venv に入った版。F）の `numexpr/necompiler.py:281-298` は、式から空白と**単引用符で囲まれた部分を除いた**うえで、`;`・`:`・`[`・`__名前__`・`.`（`.real`・`.imag`・数値リテラルを除く）を禁止する正規表現で検査し、通ったものを `compile`（308行）して **Python の `eval`（324行）** にかける。名前はすべて numexpr の変数ノードに置き換えられる（309-320行）。
  守りは**禁止パターンの列挙（denylist）**で、許可の列挙ではない。実測では `__import__(...)` や属性参照は拒否され、四則演算・`abs`・`where` などは評価された（実測文書 T11）。
- `openfisca_core/tools/__init__.py:74-92`（`get_trace_tool_link`）はシミュレーションの JSON を URL に埋め込んだリンクを作るが、送信はしない。Python 2 の `urllib.urlencode` を使っており、Python 3 では動かない（I）。

### 2.4 外部への送信（F）

- 本体（`openfisca_core`、`openfisca_web_api`）に、HTTP クライアントで外部へ送る処理は無い（`urllib`・`requests`・`socket` などを grep。上の `get_trace_tool_link` だけ）。
- Web API の利用状況の送信（tracker）：`openfisca_web_api/app.py:21-45, 55-58, 200-216`。`--tracker-url` と `--tracker-idsite` の両方を指定し、かつ `openfisca_tracker` パッケージが入っているときだけ、要求の URL と送信元 IP を Piwik（Matomo）へ送る。**既定では無効**。46.0.0 で `tracker` extra は削除された（CHANGELOG）。

### 2.5 Web API（`openfisca serve`）の初期設定（F）

- 待ち受けアドレス：`openfisca_web_api/scripts/serve.py:19-22` `DEFAULT_PORT = "5000"`、`HOST = "127.0.0.1"`、`DEFAULT_WORKERS_NUMBER = "3"`、`DEFAULT_TIMEOUT = 1200`。92-97行で `bind = "127.0.0.1:5000"`。**既定はループバックだけ**。
  - `--bind` など gunicorn の引数で上書きできる（41-46行）。`update()`（55-63行）は `--port` を受けると `bind` の末尾4文字を切ってポートを付け直すので、4桁でないポートを `--bind` に書いたうえで `--port` も指定するとおかしな値になる（I：コードからの読み取り。未実測）。
- タイムアウト：gunicorn の `timeout` を 1200 秒にしている（gunicorn の既定は 30 秒。E）。1つの要求で最大20分計算し続けられる。
- CORS：`app.py:63` `CORS(app, origins="*")`。どのオリジンの Web ページからも呼べて、応答を読める。設定で変える口は無い。
- 認証：無い。`app.py` の全ルート（`/`、`/parameters`、`/parameter/<id>`、`/variables`、`/variable/<id>`、`/entities`、`/spec`、`POST /calculate`、`POST /trace`）に認証・認可の処理は無い。
- 要求の大きさ：`app.py` は Flask の `MAX_CONTENT_LENGTH` を設定していない。Flask 3.1.3 の既定は `None`（venv の `flask/app.py:198`）で、JSON の本文に上限は無い。
- 計算量の上限：`axes`（`simulations/simulation_builder.py:737-780` の `expand_axes`）は、要求の `count` の積だけ人とグループを複製する。`count` に上限は無い。
- 循環：同じ期間の循環は `CycleError`（`simulations/simulation.py:425-427`）。前の期間を次々にたどる参照（spiral）は `max_spiral_loops = 1`（61行）で打ち切り、`SpiralError` を捕まえて**既定値の配列を返す**（168-169行）。エラーにはならない。
- `ProxyFix(app.wsgi_app, x_for=1, x_host=1)`（`app.py:62`）：`X-Forwarded-Host` を信用するので、応答中の URL（`/` の welcome、`/parameters`・`/variables` の href）に要求側が指定したホスト名が入る。
- 500 エラー（`app.py:218-224`）は例外のメッセージを応答に入れる。
- `/variable/<id>` は計算式のソースの場所（ファイル名・行）を返す（`openfisca_web_api/loader/variables.py:26-50`）。
- `openfisca serve` は gunicorn で動く（`serve.py:8-12, 66-99`）。gunicorn は `fcntl`・`pwd`・`grp` を import する（venv の `gunicorn/util.py:8,15`、`gunicorn/config.py:10,13`）ので、**Windows では起動しない**（実測文書 T13）。

## 3. 適合性（コードで確認したこと）

### 3.1 エンティティと役割（F）

- エンティティは「人」1種類と、グループを任意の数定義できる：`openfisca_core/entities/helpers.py:10-20`（`build_entity`）、`TaxBenefitSystem(entities)`。
  GovTech の報告書 p.18 も「人エンティティは1種類しか定義できないが、グループエンティティは複数定義できる」「OpenFisca-France では家族・世帯など複数定義され、構成員が重複しても制度ごとに計算単位を使い分けられる」と書いている。
- 役割：`openfisca_core/entities/role.py:50-54, 78-86`。役割は `key`、`plural`、`max`（人数の上限）、`subroles` を持つ。
  `group_entity.py:106-119`：`subroles` を指定すると、各サブ役割は `max: 1` になり、役割の `max` はサブ役割の数になる。役割はグループの属性 `役割キー.upper()` としても登録される（108行）。
- **所属の表し方**：`simulations/simulation_builder.py:475-476` で、グループの種類ごとに「人物の数」の長さの配列 `memberships`（どのインスタンスに属するか）と `roles`（役割）を1本ずつ作る。
  - 1人は、グループの種類ごとに**ちょうど1つのインスタンス**に属し、**ちょうど1つの役割**を持つ。
  - 同じ種類の中で2回目に出てきた人はエラー：`check_persons_to_allocate`（562-587行）の「`{person_id} has been declared more than once in {entity_plural}`」。同じインスタンスの別の役割でも、別のインスタンスでも同じエラーになる。
  - 役割の `max` を超えるとエラー（520-524行）。
  - どのインスタンスにも書かれなかった人は、その人だけのインスタンスが自動で作られ、**最初の役割（`flattened_roles[0]`）が割り当てられる**（536-546行）。
  - 所属と役割には期間の次元が無い（`memberships`・`roles` は期間ごとに持たない）。1つのシミュレーションの中で、所属や役割を期間によって変えられない。
- 人からグループの値を引く：`populations/population.py:26-36`（`人.生計("変数", period)` のような書き方。`projectors/helpers.py`）。
  グループから人の値を集める：`populations/group_population.py` の `sum`（102行）、`any`（129行）、`max`（193行）、`nb_persons`（243行）、`value_from_person`（261行、`max: 1` の役割だけ）、`value_nth_person`（289行）、`project`（320行）。
- `containing_entities`（`group_entity.py:91-120`、`projectors/helpers.py:132`）：あるグループの構成員が別のグループの構成員を必ず含む、という関係を宣言し、グループからグループへ値を引ける。

### 3.2 期間（F）

- 単位：`periods/date_unit.py:52-` の `DateUnit` は `weekday`・`week`・`day`・`month`・`year`・`eternity` の6種。変数ごとに `definition_period` を1つ決める。
- `periods/period_.py`：期間は（単位、開始日、長さ）。`year:2025-10` のように**月の途中から始まる1年**も表せる。`last_year`（871行）、`this_year`（885行）、`first_month`（892行）、`offset`（512行）、`get_subperiods`（466行）などがある。
- 単位の違う変数のつなぎ方：`options=[ADD]`（合計）・`[DIVIDE]`、入力側は `set_input_divide_by_period`・`set_input_dispatch_by_period`（`model_api.py`）。

### 3.3 パラメータ・改正・テスト（F）

- パラメータは YAML のファイル・ディレクトリの木で、`values:` の下に日付ごとの値を書く。`parameters(日付).ディレクトリ名.ファイル名` で引く。**パラメータには階層（名前空間）がある**。
- 計算式の切り替え：`formula_YYYY_MM_DD` の名前で施行日ごとに式を分けられる（`variables/variable.py` の `formulas`。430行付近）。
- 改正：`openfisca_core/reforms/`、`Reform.apply()` の中で `modify_parameters`・`update_variable`・`add_variable`・`neutralize_variable`。元の `TaxBenefitSystem` は変更しない（`tax_benefit_system.py:322-327` の説明）。
- テスト：YAML（`tools/test_runner.py`）。キーワードは `name, period, input, output, reforms, extensions, absolute_error_margin, relative_error_margin, max_spiral_loops` など（112-127行）。pytest のプラグインとして動く（489-532行の `run_tests` は `pytest.main`）。
- 変数の名前空間：変数は `TaxBenefitSystem.variables` の1つの辞書に名前で登録される。同じ名前を2回登録すると `VariableNameConflictError`（`tax_benefit_system.py:156-166`）。拡張（`load_extension`、295-320行）も同じ辞書に足す。
  **変数には名前空間が無い**（報告書 p.17 の主張と一致）。パラメータは上のとおり階層がある。

## 4. GovTech 報告書の主張との対応（OpenFisca-Core 側）

| 報告書 | 主張 | Core のコード・実測で |
|---|---|---|
| p.16 | 「OpenFisca の出力は数値形式」 | Core の変数の型は float・int・bool・str・Enum・date（`variables/variable.py`）。実測で Enum の名前（文字列）、真偽値、日付が JSON で返った（実測文書 T12e）。**Core については成り立たない**。数値だけなのは OpenFisca-Japan の使い方 |
| p.16 | 「世帯または個人単位でしか計算できない」 | Core はグループを任意に定義できる（§3.1、実測 T01）。OpenFisca-Japan が「世帯」だけを定義しているための制約 |
| p.17-18 | 制度名を階層で管理できない（名前の重複） | 変数については成り立つ（§3.3）。パラメータには階層がある |
| p.18 | 人は1種類、グループは複数定義できる | 成り立つ（§3.1、実測 T00・T01） |
| p.8-9 | 日本語の変数名 | 成り立つ（実測 T00・T12）。ただし Windows では UTF-8 モードが必要（実測 T00） |

報告書 p.18-19（グループは「世帯」だけ、「子」は未成年）と p.21（世帯主の簡略化）は OpenFisca-Japan のコードの話なので、
`docs/public-sources/20261109_R2-tools_openfisca-japan-source.md` を参照。

## 5. 分からなかったこと

- FSF の GPL FAQ の原文（§1.1）。取得できなかった。
- numexpr の禁止パターンをすり抜ける式があるかどうかは調べていない（§2.3。検査は denylist）。
- gunicorn で動かしたときの実際の待ち受けアドレス・タイムアウトは、Windows では起動しないため実測していない（Linux で確かめる必要がある）。
- 公式ドキュメント（https://openfisca.org/doc/ ）は今回読んでいない。コードとリポジトリ内の README・CHANGELOG だけで判断した。
