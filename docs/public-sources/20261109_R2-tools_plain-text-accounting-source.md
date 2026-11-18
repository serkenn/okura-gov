# R2 plain text accounting（beancount / beanquery / beangulp / hledger / ledger）のソースと公開資料

- 作成日：2026-11-09（R2 担当）
- 種別：公開資料の情報（ソースコードを静的に読んで分かったこと、公開ドキュメント・脆弱性データベースの記載）
- 実行して確かめたことは別ファイル：`docs/measurements/20261109_R2-tools_beancount-runtime.md`
- ソースは `git clone` で `.work/downloads/<日時>_<repo>/` に取得し、Read / grep / git log だけで読んだ（clone の中でインタプリタ・ビルド・テストは実行していない）。
  `.work/` は git 管理外なので、下の「確認したコミット」で再取得して検証すること。

## 0. 確認したリポジトリとコミット

| ツール | リポジトリ（取得日 2026-11-09） | 読んだコミット | タグ | 備考 |
|---|---|---|---|---|
| beancount | https://github.com/beancount/beancount | `eeda2aa2a3204ffb980dab11220b2abde5e80b38`（2026-05-05） | `3.2.3` | 下記 0.1 参照。PyPI の最新版も 3.2.3 |
| beanquery | https://github.com/beancount/beanquery | `f8079cd6ca6aa2f38dfc5490ad29333cea20309a`（2025-03-24） | `v0.2.0` | master は `62b6abb`（2026-06-12、v0.2.0 から13コミット、pyproject の version は `0.3.0.dev0`） |
| beangulp | https://github.com/beancount/beangulp | `c312969913e1db16498725f84e3fe4ae71a35a21`（2025-01-20） | `v0.2.0` | master は `81972f0`（2026-10-18、v0.2.0 から54コミット） |
| hledger | https://github.com/simonmichael/hledger（API 上は `hledgerorg/hledger` に移っている） | `5b22de2f78b139e7f6c0b019cc99b29d801eb5e1`（master、2026-11-06） | 直近：`1.99.6`（2026-11-01、2.0 プレビュー6）、安定版 `1.52.4`（`33fa849e`、2026-09-10） | ネイティブ（Haskell）。インストールしていない |
| ledger | https://github.com/ledger/ledger | `2f9e4134cafc44c4d9d28c4ad59414b947df4c3e`（master、2026-11-06） | 直近：`v3.4.1`（`d422d3cd`、2025-10-25） | ネイティブ（C++）。インストールしていない。master は v3.4.1 から1940コミット先 |

### 0.1 beancount のタグ 3.2.3 と master の関係（F）

- タグ `3.2.3`（`eeda2aa2`）は master の祖先ではない。`git log HEAD..3.2.3` は `eeda2aa2 Push the version change in beancount/VERSION` の1件だけ。
  master 側（`97472138`、2026-08-23）には 3.2.3 タグ以後に9コミットがある（`a75c419c Fix literal account component matching` など）。master の `beancount/VERSION` も `3.2.3` のまま。
- つまり 3.2.3 はリリース用ブランチ上で打たれ、master はリリースされていない修正を含む。**本文書の行番号はすべてタグ `3.2.3` のもの**（PyPI の wheel と一致するもの。実測文書で wheel 内の `loader.py` などがタグのソースとバイト単位で同じことを確認した）。

### 0.2 リリースと保守の状況（F：git log、E：PyPI。取得日 2026-11-09）

| | リリース（PyPI のアップロード日） | 直近1年（2025-11-09〜）のコミット数と主な作者 | ライセンス |
|---|---|---|---|
| beancount | 3.0.0（2024-06-22）、3.1.0（2025-01-19）、3.2.0（2025-09-14）、3.2.1（2026-04-29）、3.2.2（2026-04-30）、3.2.3（2026-05-05） | 44（Martin Blais 27） | GPL-2.0-only（`COPYING`、`pyproject.toml:28`） |
| beanquery | 0.1.0（2024-11-05）、0.2.0（2025-03-24） | 6（Daniele Nicolodi 6） | GPL-2.0-only（`LICENSE`、pyproject） |
| beangulp | 0.1.0/0.1.1（2024-05-29）、0.2.0（2025-01-20） | 12 | GPL-2.0（`LICENSE`） |
| hledger | 1.52（2026-03-20）〜1.52.4（2026-09-10）、1.99.1〜1.99.6（2.0 プレビュー、毎月） | 2476（Simon Michael 2205） | GPL-3.0-or-later（`LICENSE`、`hledger/hledger.cabal:26`、`hledger-lib/hledger-lib.cabal:33`） |
| ledger | v3.3.2（2023-03-30）→ v3.4.0（2025-10-22）、v3.4.1（2025-10-25） | 1933（John Wiegley 1889） | BSD（3条項型、`LICENSE.md`） |

- 対応する Python：beancount `requires-python = ">=3.9"`（`pyproject.toml:29`）。wheel は cp310〜cp314 の win_amd64 / win32 / macOS / manylinux が PyPI にある（E：https://pypi.org/pypi/beancount/json 、取得日 2026-11-09）。beanquery `>=3.8`、beangulp は指定なし。
- 依存（`pyproject.toml` / PyPI の requires_dist）：beancount＝`click>=7.0`, `python-dateutil>=2.6.0`, `regex>=2022.9.13`。beanquery＝`beancount>=2.3.4`, `click>7.0`, `python-dateutil>=2.6.0`, `tatsu-lts`。beangulp＝`beancount>=2.3.5`, `beautifulsoup4`, `chardet`, `click>8.0`, `lxml`, `python-magic`（win32 以外）。
- beancount v3 では、v2 にあったクエリ（bean-query）と取り込み（ingest）が別パッケージ beanquery・beangulp に分かれ、beancount 本体のコンソールスクリプトは `bean-check`, `bean-doctor`, `bean-example`, `bean-format`, `treeify` だけ（`pyproject.toml:54-59`）。Web UI（fava）は別プロジェクトで、本調査の対象外。
- 参考（F）：ledger のリポジトリ直下に `CLAUDE.md`、hledger に `.claude/skills/` があり、どちらも AI ツールを使った開発をしている。直近1年のコミット数の多さはこれと関係があると思われる（I）。

## 1. beancount 3.2.3

### 1.1 勘定科目名の文字種（F）

- 字句解析器 `beancount/parser/lexer.l:121-130`：
  - `ACCOUNTTYPE  ([A-Z]|{UTF-8-ONLY})([A-Za-z0-9\-]|{UTF-8-ONLY})*`
  - `ACCOUNTNAME  ([A-Z0-9]|{UTF-8-ONLY})([A-Za-z0-9\-]|{UTF-8-ONLY})*`
  - `lexer.l:272-274` で `{ACCOUNTTYPE}(:{ACCOUNTNAME})+` を ACCOUNT トークンにする。字句解析の段階では、各成分の先頭に任意の非 ASCII 文字（UTF-8 の2〜4バイト列）を許す。
- ただし文法側の検査が別にある。`beancount/parser/grammar.py:109-127` の `valid_account_regexp` は
  `(?:<5つのルート名>)(?::[\p{Lu}\p{Nd}][\p{L}\p{Nd}\-]*)+` を作り、`grammar.py:286` で `self.account_regexp.match(account)` を通らなければ `Invalid account name` のエラーにする。
  - `ACC_COMP_NAME_RE = r"[\p{Lu}\p{Nd}][\p{L}\p{Nd}\-]*"`（`beancount/core/account.py:37-38`）。**成分の先頭は Unicode の大文字（Lu）か数字（Nd）でなければならない。** 漢字・ひらがな・カタカナは Lo（その他の文字）なので、成分の先頭には置けない。2文字目以降は `\p{L}`（Lo を含む）なので置ける。
  - `grammar.py:286` は `fullmatch` ではなく `match`（先頭一致）。このため `Expenses:Medical:医療費` のように、**先頭の成分が規則を満たせば、その後の成分は先頭が漢字でもエラーにならない**（実測で確認）。一方 `account.is_valid()`（`account.py:75-84`）は `fullmatch` なので False を返す。ファイルの読み込みは通るが、`is_valid` を使う処理（`account.walk` による documents ディレクトリの走査、`account.py:195-220`。`plugins/currency_accounts.py:62`）とは判定が食い違う。
  - master には 3.2.3 以後に `a75c419c Fix literal account component matching` があるが、これが上の先頭一致の挙動に関係するかは確認していない。
- ルート名（Assets など）は option で変えられるが、`options_validate_root_account`（`parser/options.py:120-133`）が `ACC_COMP_TYPE_RE = r"[\p{Lu}][\p{L}\p{Nd}\-]*"`（`account.py:37`）で検査するので、`資産` のような日本語のルート名は使えない（`name_assets` などの定義：`options.py:322-330`）。
- タグ・リンク・メタデータのキーは ASCII だけ（`lexer.l:286-299`）：TAG `#[A-Za-z0-9\-_/.]+`、LINK `\^[A-Za-z0-9\-_/.]+`、KEY `[a-z][a-zA-Z0-9\-_]+`（小文字で始まり2文字以上）。メタデータの**値**は文字列なので日本語を書ける。
- 公式テスト `parser/lexer_test.py:136-154` は `Óthяr:Bあnk`、`ΑβγⅠ:ΑβγⅠ`、`ابجا:ابجا` などを字句解析のレベルで ACCOUNT として受け付けることを確かめているが、文法の検査（上記）を通るかまでは見ていない。

### 1.2 `plugin` 行と任意コード実行（F）

- `plugin "モジュール名" "設定文字列"` は `grammar.py:449-460` でオプション `plugin` のリストに追加され、`loader.py:639-742` の `run_transformations` で **`importlib.import_module(plugin_name)`（`loader.py:688`）** される。モジュール名に制限（許可リスト）はない。インポートした時点でモジュールのトップレベルのコードが走り、`__plugins__` にある関数が `callback(entries, options_map, *args)` で呼ばれる（`loader.py:705-719`）。
- `option "insert_pythonpath" "TRUE"`（`options.py:718-724`）を書くと、そのファイルのあるディレクトリが `sys.path` の先頭に入る（`loader.py:554-558` の `aggregate_options_map`、`loader.py:612-620`）。これは **include された側のファイルに書いても有効**（`other_options_map` も見る、`loader.py:555`）。
  → 台帳と同じ場所に `.py` を置き、台帳に `option "insert_pythonpath" "TRUE"` と `plugin "そのモジュール"` を書けば、読み込んだだけでその Python が実行される。
- さらに、**同梱のプラグイン3つが、台帳に書かれた設定文字列を `eval` する**：
  - `beancount/plugins/check_average_cost.py:50` `config_obj = eval(config_str, {}, {})`
  - `beancount/plugins/check_commodity.py:120` `config_obj = eval(config_str, {}, {})`
  - `beancount/plugins/commodity_attr.py:44` `config_obj = eval(config_str, {}, {})`
  - `eval` の globals に `{}` を渡しても、Python は `__builtins__` を自動で補うので `__import__` などが使える。**`.py` を置かなくても、台帳ファイルのテキスト1行（例 `plugin "beancount.plugins.check_commodity" "__import__('os')...."`）で任意の Python コードが実行される。**（実測で確認）
- `plugin` 行はトップレベルのファイルのものだけが使われる。`_parse_recursive` はトップレベルの options_map だけを採用し、include 先からは `operating_currency`・`dcontext`・`insert_pythonpath` だけを集約する（`loader.py:485-490, 532-560`）。include 先の `plugin` 行はエラーも出さずに無視される（実測で確認）。
- `plugin_processing_mode`（`options.py:615-631`）は `default`（既定のプラグインも動かす）と `raw`（台帳に書かれたものだけ）の切り替えで、**台帳の `plugin` 行を止める設定ではない。** `READ_ONLY_OPTIONS = {"filename", "plugin"}`（`options.py:741`）は `option "plugin" ...` という書き方を禁じるだけで、`plugin` ディレクティブは止めない。
- `loader.load_file` / `load_string` の引数（`loader.py:89-95`）にプラグインを無効にする・許可リストを渡すものはない。止めるには、読み込む前に `beancount.parser.parser.parse_file`（文法処理だけでプラグインを読み込まない）で全ファイルを走査し、`plugin` 行や `insert_pythonpath` があれば拒否する、などを自分で書く必要がある（実測で試した）。
- beanquery の `beancount:` データソース（`beanquery/sources/beancount.py:44-47`）と beangulp の `--existing`（`beangulp/__init__.py:72`）も `loader.load_file` を呼ぶので、同じ経路を通る。

### 1.3 読み込みキャッシュ（pickle）（F）

- `loader.py:847` `initialize(os.getenv("BEANCOUNT_DISABLE_LOAD_CACHE") is None)`：**環境変数を設定しない限り、読み込みキャッシュが有効。**
- キャッシュのファイル名は既定で台帳と同じディレクトリの `.{filename}.picklecache`（`loader.py:74-75, 180-196`）。`pickle_cache_function`（`loader.py:198-277`）は、このファイルが存在すれば **鮮度を確かめる前に `pickle.load`（`loader.py:231`）する。** pickle の読み込みは任意コード実行になりうるので、台帳の隣に細工した `.xxx.beancount.picklecache` を置かれると、読み込んだだけでコードが実行される（実測で確認）。
- キャッシュを書くのは読み込みに1秒以上かかったとき（`PICKLE_CACHE_THRESHOLD = 1.0`、`loader.py:79`、`264-273`）。
- 無効にする方法：環境変数 `BEANCOUNT_DISABLE_LOAD_CACHE`（loader のインポート前に設定）、`loader.initialize(use_cache=False)`、`bean-check --no-cache`（`scripts/check.py:31`）。無効のときはキャッシュファイルを削除する（`delete_cache_function`、`loader.py:280-301`）。

### 1.4 `include` 行（F）

- `include "パス"`（`grammar.py:439-447`）は、相対パスなら **include を書いたファイルのディレクトリ** を基準に、`glob.glob(search_path, recursive=True)` で展開する（`loader.py:492-518`）。絶対パス、`..`、`**` の再帰 glob を制限なく受け付ける。台帳のディレクトリの外のファイルも読める（実測で確認）。
- 同じファイルを2回読むと `Duplicate filename parsed` のエラー（`loader.py:434-442`）。存在しないときは `File ... does not exist`、glob が何にも一致しないときもエラー。
- include 先が台帳でないテキストだと、各トークンが `Invalid token: '...'` のエラーになり、**エラーメッセージにファイルの中身の断片が出る**（実測で確認）。エラーを外へ返す設計にすると情報の漏れにつながる（I）。
- 拡張子が `.gpg`、または `.asc` で先頭に `--BEGIN PGP MESSAGE--` があるファイルは、`gpg --batch --decrypt` を `shell=False` で起動して復号する（`beancount/utils/encryption.py:41-80`、`loader.py:418-422`）。include 先がそうなら gpg が起動する。

### 1.5 証憑：`document` ディレクティブと `option "documents"`（F）

- `YYYY-MM-DD document 勘定科目 "パス"`：相対パスは台帳ファイルのディレクトリ基準で絶対パスにする（`grammar.py:799-820`）。メタデータ（`key: value`）を付けられる。
- 既定で動く `beancount.ops.documents`（`loader.py:54-56` の PLUGINS_PRE、`ops/documents.py:17`）が
  - `verify_document_files_exist`：document のファイルがなければエラー（`ops/documents.py:70-89`）
  - `process_documents`：`option "documents" "ディレクトリ"`（`options.py:579-586`）の下を `account.walk` で走査し、勘定科目名と同じ階層のディレクトリにある `YYYY-MM-DD.<何でも>` という名前のファイルから Document を自動生成する（`ops/documents.py:35-67, 92-185`）。相対ディレクトリは台帳ファイル基準。`account.walk` は `is_valid`（fullmatch）を通るディレクトリだけを対象にするので、`Expenses/医療費/` のようなディレクトリは無視される（`account.py:195-220`）。
- Document と取引を直接つなぐ仕組みはない。共通のリンク（`^tx-...`）か、メタデータ（例 `txid: "..."`）を両方に書いてつなぐ（I。実測で両方書けることは確認）。

### 1.6 取引を特定する識別子（F）

- beancount に「取引 ID」の専用の仕組みはない。使えるのは
  - メタデータ：`id: "tx-2026-0001"` のような任意のキー（キーは ASCII 小文字始まり、値は文字列）。重複の検査はしない（実測で確認）。
  - リンク：`^tx-2026-0001`（ASCII だけ）。複数の取引・document に同じリンクを付けられる。
  - beanquery の `id` 列（`beanquery/sources/beancount.py:293-296`）はエントリの内容から計算したハッシュで、取引を書き換えると変わる（I：`hash_entry` を使っていると思われるが、コードの行は追っていない）。D4 の「人の判断」から参照する安定した識別子には、自分で振るメタデータ `id:` を使うのが妥当（I）。

### 1.7 beanquery 0.2.0（F）

- SQL に似たクエリ言語（BQL）。字句・構文解析は TatSu（`tatsu-lts`）で生成したパーサ。式はコンパイラ（`beanquery/compiler.py`）が評価用オブジェクトの木にする。
- `eval` / `exec` の使用箇所：`beanquery/hashable.py:75` の `exec` だけ。これは列の位置と型から `__hash__` 関数のソースを組み立てるもので、組み立てる文字列は `self[i]`・`func{i}` のような固定の形と列番号だけ。クエリの文字列はそこに入らない（`hashable.py:48-80`）。
- `importlib.import_module` は `beanquery.sources.{scheme}`（`beanquery/__init__.py:49`、`compiler.py:756`）と `beanquery.render.{name}`（`shell.py:86`）で、パッケージの接頭辞が固定されている。
- `CREATE TABLE ... USING 'file.csv'` で任意のローカル CSV を読める（`beanquery/sources/csv.py:89-107`）。クエリを外部から受け付けるなら制限が要る（I）。
- 出力形式は text と csv（`beanquery/render/` に `beancount.py`, `csv.py`, `text.py`）。JSON 出力はない。Python API（`beanquery.connect('beancount:', entries=..., errors=..., options=...)` → `execute()` → `fetchall()`、`beanquery/__init__.py:25-66`）で結果を取り出し、自分で JSON にする。
- メタデータを引く関数：`meta(key)`（posting）、`entry_meta(key)`（取引）、`any_meta(key)`（`beanquery/query_env.py:389-408`）。
- wheel（0.2.0）は、site-packages の直下に `docs/conf.py`（Sphinx の設定）を入れてしまう（`beanquery-0.2.0.dist-info/RECORD` に `docs/conf.py`。実測文書の環境で確認）。トップレベルのパッケージ名 `docs` を占有する。害は小さいが、パッケージの作りの粗さとして記録する。

### 1.8 beangulp 0.2.0（F）

- 取り込みの枠組み。利用者が Python で「importer」（`beangulp/importer.py` の `Importer` を継承したクラス）を書き、それを含むスクリプトを実行する方式。CSV 用の基底クラス `beangulp/importers/csvbase.py`、`csv.py` がある。つまり **取り込みの設定そのものが Python コード**（信頼できる自分のコードである前提）。
- 外部ファイルの処理に関わる点：
  - ファイル種別の判定に `python-magic`（libmagic）を使う。Windows では依存に入らない（`beangulp/file_type.py:18-43`、PyPI の requires_dist）。
  - `beangulp/cache.py:160-200` の `@cache` は変換結果を pickle でディスクに保存し、`pickle.load`（`cache.py:187`）で読む。保存先は Windows で `%LOCALAPPDATA%\Beangulp`、それ以外で `~/.cache/beangulp`（`cache.py:29-31`）。ユーザーのキャッシュディレクトリに他人が書き込めない限り問題になりにくい（I）。
  - `archive` は `shutil.move` でファイルを `勘定科目/日付.名前` に移す（`archive.py:40-75`）。ファイル名に `os.sep` が含まれるかだけを調べる（`archive.py:42`）ので、Windows では `/` を含む名前を防がない（ファイル名を返すのは利用者の importer なので、影響は小さい。I）。
  - lxml・BeautifulSoup は依存にあるが、beangulp 0.2.0 の本体コード（テスト以外）では import していない（grep で確認。利用者の importer 用）。
- `eval` / `exec` / `subprocess` の使用はない（テスト以外を grep）。

## 2. hledger（master `5b22de2f`、安定版 1.52.4 と比較）

### 2.1 勘定科目名・タグ・出力（F / E）

- 勘定科目名：`accountnamep = singlespacedtext1p`（`hledger-lib/Hledger/Read/Common.hs:1005-1006, 1029-1030`）。文字種の制限はなく、2つ以上の空白（またはタブ2つ）で区切られるまでが名前。マニュアル（`hledger/hledger.m4.md:979-990`）は「大文字・小文字どちらでもよく、文字・数字・記号・1つの空白を含められ、どの言語でもよい」とする。日本語のルート名（`資産` など）も書ける。勘定科目の種別は英語名からの推定か、`account 資産  ; type: A` の `type:` タグで宣言する（`hledger.m4.md:1897-1930`）。
- タグ：コメントの中に `name:` / `name: value` と書く（`hledger.m4.md:1488-1510`）。タグ名は「コロンの前の、空白で区切られた最後の語」（`Common.hs:2105`）で、文字種の制限は見当たらない（日本語のタグ名が通るかは未実測）。
- `include`（`hledger.m4.md:2417-2475`、`hledger-lib/Hledger/Read/JournalReader.hs:346-520`。`includedirectivep` と `parseIncludedFile`）：相対パスは include を書いたファイル基準。絶対パス、`~`、`..`、glob（`*`, `**`）を受け付ける。読み込む形式は拡張子か `timedot:` などの接頭辞で決まり、**journal・timeclock・timedot・CSV/SSV/TSV・CSV rules ファイルを include できる**（master のマニュアル。1.52.4 のマニュアル `hledger.m4.md:2709` では「CSV は include できない」とあるが、1.52.4 の `JournalReader.hs:144` の読み込み器の一覧には `RulesReader.reader` が入っている。1.52.4 で rules ファイルの include が実際に動くかは未確認）。
- 出力形式に `json` がある（`hledger/Hledger/Cli/CliOptions.hs:874`、マニュアル `hledger.m4.md:7910` の表）。`beancount` 形式の出力もある。

### 2.2 CSV rules の `source` 行によるシェルコマンドの実行（F）— 重要

- CSV rules ファイルの `source パターン | コマンド`（データ整形コマンド）と `source | コマンド`（データ生成コマンド）は、**既定のシェルでコマンドを実行する**（hledger 1.50 から。`hledger.m4.md:3307-3342`）。
  - 実装：`hledger-lib/Hledger/Read/RulesReader.hs:198-215`（`source` の解釈）、`:286-301`（実行の分岐）、`:337-375`（`runCommand` / `runCommandAsFilter` が `System.Process.shell cmd` を rules ファイルのディレクトリで起動）。安定版 1.52.4 でも同じ（`RulesReader.hs:275-297`）。
  - マニュアルは「`import --dry-run` でも実行される」と明記している（`hledger.m4.md:3340`）。
  - rules ファイルを読み込むだけで実行され、**信頼できるファイルかどうかを確かめる仕組み（許可の設定やフラグ）は RulesReader にない**（`unsafe` / `allow` / `trust` を grep して該当なし）。
- master では journal から rules ファイルを include でき（2.1）、CSV を include すると隣の `FILE.rules` が使われる。したがって **「journal ＋ rules ファイル」を受け取って `hledger -f` で読むだけで、任意のシェルコマンドが実行されうる。**
- 対照的に、設定ファイル `hledger.conf` のシェルコマンドのエイリアス（`!` で始まるもの）は、明示した `--conf` かユーザーの設定ファイルにあるときだけ実行し、カレントや親ディレクトリで自動で見つかった `hledger.conf` のものは実行しない、という対策がある（`hledger.m4.md:387-401`）。rules の `source` コマンドには同等の対策がない。
- `hledger get` は journal のディレクトリの `data/getdata` スクリプトを実行する（`hledger/Hledger/Cli/Commands/Get.hs:5, 94-97`）。これは利用者が明示的に `get` を打ったときだけ。

### 2.3 hledger-web（F / E）

- 既定の待ち受けは `127.0.0.1:5000`（`hledger-web/Hledger/Web/Settings.hs:49-54`）。認証はない。
- 権限は待ち受けアドレスがループバック（`127.0.0.1`, `::1`, `localhost`）か unix ソケットなら既定で `add`（取引の追記が可能）、それ以外なら `view`（`hledger-web/Hledger/Web/WebOptions.hs:186-205`）。`--allow` で変更、`--cors` で CORS を許可（`WebOptions.hs:73-82`）。
- 既知の脆弱性（E、取得日 2026-11-09）：
  - GHSA-vq7r-8w52-jv84（high、2026-08-27）：hledger-web の追加フォームの XSS と、改行を使った journal への注入。影響 1.18〜1.52.2、修正 1.52.3。https://github.com/hledgerorg/hledger/security/advisories/GHSA-vq7r-8w52-jv84
  - GHSA-538p-cvc4-4qjm（high、2026-08-24）：追加フォームの自動補完の XSS。影響 0.24〜1.52.1、1.99.1〜1.99.3、修正 1.52.2。https://github.com/hledgerorg/hledger/security/advisories/GHSA-538p-cvc4-4qjm
  - CVE-2021-46888 / HSEC-2023-0008：hledger-web 1.23 未満の stored XSS（https://osv.dev/vulnerability/HSEC-2023-0008）
  - OSV の Hackage `hledger` / `hledger-lib` には登録なし（https://api.osv.dev/v1/query 、取得日 2026-11-09）。

## 3. ledger（master `2f9e4134`、v3.4.1）

- 勘定科目名：posting の行で、次の要素（2つ以上の空白など）までが名前（`src/textual_xacts.cc:535-560`）。文字種の検査はない。回帰テスト `test/regress/2338.test` が `Expenses:食費`・`Assets:現金` を使い、UTF-8 が保たれることを確かめている（issue #2338、PR #2341 で修正）。
- **`python` ディレクティブ**：journal に書いた Python コードを実行する（`src/textual_directives.cc:1046-1082`、ディスパッチ `:1199-1200`、マニュアル `doc/ledger3.texi:12387-12400`「Embedded Python」）。`import` ディレクティブは Python モジュールを読み込む（`textual_directives.cc:1040-1044`、`:1186-1187`）。Python 対応でビルドされていなければ parse error（`:1087-1093`）。CMake の既定は `option(USE_PYTHON ... OFF)`（`CMakeLists.txt:58`）。**Python 対応でビルドされた ledger では、信頼できない journal を読むだけで任意コード実行になる。** 配布パッケージ（Homebrew、各 Linux ディストリビューションなど）が Python 対応でビルドしているかは確認していない。
- `--download` を付けたときだけ、`getquote` コマンドを `popen` で起動する（`src/quotes.cc:64-83`）。コモディティ記号は `shell_escape` されている。
- `include`：ワイルドカード（`*`）可（`doc/ledger3.texi:2778-2783`）。
- JSON 出力：`select` 文の `style json` はプレースホルダで何もしない（`src/select.cc:456-464`、v3.4.1 でも `:420`）。XML 出力（`xml` コマンド）はある。
- 既知の脆弱性（E、取得日 2026-11-09）：NVD のキーワード `ledger-cli` で CVE-2017-2807（タグ解析のバッファオーバーフロー）、CVE-2017-2808（勘定科目解析の use-after-free）。どちらも Ledger-CLI 3.1.1、細工した journal で起きる（https://nvd.nist.gov/vuln/detail/CVE-2017-2807 、https://nvd.nist.gov/vuln/detail/CVE-2017-2808 ）。GitHub のリポジトリのセキュリティアドバイザリは0件。

## 4. 脆弱性データベースの照会結果（E、取得日 2026-11-09）

- OSV（https://api.osv.dev/v1/querybatch 、パッケージ名とバージョンだけ送信）：beancount 3.2.3、beanquery 0.2.0、beangulp 0.2.0、click 8.5.1、python-dateutil 4.0.0、regex 2026.11.9、tatsu-lts 5.16.0、tzdata 2026.6 → すべて登録なし。beancount / beanquery / beangulp は全バージョンでも登録なし。
- GitHub Advisory（`gh api advisories?ecosystem=pip&affects=...`）：beancount / beanquery / beangulp とも0件。beancount と ledger のリポジトリのセキュリティアドバイザリも0件。
- NVD（キーワード `beancount`）：CVE-2022-2523、CVE-2022-2589（どちらも fava の反射型 XSS。beancount 本体ではない）。
- 照会の手順と生の応答：`scripts/R2_beancount_deps_osv.sh` → `scripts/results/R2_beancount_deps_osv/`（実測文書を参照）。

## 5. 分からなかったこと・確認していないこと

- beancount wheel に入っているコンパイル済みのパーサ（`beancount/parser/_parser.cp311-win_amd64.pyd`）が、タグ 3.2.3 のソースから作られたものかは検証できない（Python のファイルはタグと一致した）。
- beancount master の `a75c419c Fix literal account component matching` が勘定科目の先頭一致の挙動を変えるか（未確認）。
- beanquery の `id` 列の計算方法の詳細（行を追っていない）。
- hledger：日本語のタグ名、日本語の勘定科目名を含む JSON 出力、1.52.4 での rules ファイルの include の可否は、バイナリを入れていないので未実測。
- ledger：配布バイナリが Python 対応でビルドされているか。master（v3.4.1 から1940コミット）の変更内容の安全面の評価はしていない。
- fava（beancount の Web UI）は対象外として読んでいない。
