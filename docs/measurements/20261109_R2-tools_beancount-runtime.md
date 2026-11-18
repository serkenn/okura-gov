# R2 beancount 3.2.3 / beanquery 0.2.0 の実測

- 実測日：2026-11-09（R2 担当）
- 種別：実測
- 対応する公開資料の情報（ソースの行番号など）：`docs/public-sources/20261109_R2-tools_plain-text-accounting-source.md`
- hledger と ledger はネイティブのバイナリなので、このタスクではインストールも実行もしていない（末尾の「インストールして確かめるべきこと」）。

## 根拠（再実行の方法）

| スクリプト | 出力 |
|---|---|
| `scripts/R2_beancount_check.py`（先頭に仮想環境の作り方とバージョン固定を書いた） | `scripts/results/R2_beancount_check/results.json`、`summary.txt` |
| `scripts/R2_beancount_deps_osv.sh`（依存一覧と OSV / GitHub Advisory の照会） | `scripts/results/R2_beancount_deps_osv/`（`freeze.txt`、`osv_query.json`、`osv_response.json`、`osv_allversions_*.json`、`ghsa_*.json`、`queried_at.txt`） |

環境：

- Windows 11（`platform.platform()` = `Windows-10-10.0.26200-SP0`）、CPython 3.11.9（uv が管理するもの）
- 仮想環境：`uv venv .work/venvs/R2-beancount --python 3.11` → `uv pip install --python .work/venvs/R2-beancount --only-binary :all: beancount==3.2.3 beanquery==0.2.0`（wheel だけ。Windows 用 wheel `beancount-3.2.3-cp311-cp311-win_amd64.whl` があり、そのまま入った）
- 入った依存（`uv pip freeze`、`scripts/results/R2_beancount_deps_osv/freeze.txt`）：
  `beancount==3.2.3`, `beanquery==0.2.0`, `click==8.5.1`, `python-dateutil==4.0.0`, `regex==2026.11.9`, `tatsu-lts==5.16.0`, `tzdata==2026.6`
- 実行：`.work/venvs/R2-beancount/Scripts/python.exe -I scripts/R2_beancount_check.py`（`sys.flags.isolated = 1`。カレントディレクトリもスクリプトのディレクトリも `sys.path` に入らない）
- 作業用の台帳・プラグイン・pickle はスクリプトが一時ディレクトリに作り、終了時に消す。結果の中の一時ディレクトリのパスは `<TMP>` に置き換えた。

## 0. インストールしたものとソースの一致

- wheel の `beancount/loader.py`, `core/account.py`, `parser/grammar.py`, `parser/options.py`, `ops/documents.py`, `plugins/check_commodity.py` は、タグ `3.2.3` のソースとバイト単位で一致（`cmp`）。
- beanquery の `compiler.py`, `hashable.py`, `sources/beancount.py` は改行コードの違い（clone 側が CRLF）を除いて一致（`diff --strip-trailing-cr`）。
- beanquery 0.2.0 の wheel は site-packages 直下に `docs/conf.py` を入れる（`beanquery-0.2.0.dist-info/RECORD`）。
- 既知の脆弱性：OSV の一括照会で上の7パッケージ＋beangulp 0.2.0 はすべて該当なし。GitHub Advisory（pip）も beancount / beanquery / beangulp で0件（2026-11-09 照会）。

## 1. 日本語の勘定科目名（results.json の `1_account_names`）

`open` と取引1件を書いた台帳を `loader.load_string` で読んだ結果：

| 勘定科目名 | 読み込みのエラー | `account.is_valid()`（fullmatch） | beanquery で集計できたか |
|---|---|---|---|
| `Expenses:Medical` | なし | True | できた |
| `Expenses:医療費` | `Invalid account name` | False | — |
| `Expenses:Medical:医療費` | **なし** | **False** | できた（`Expenses:Medical:医療費  1000`） |
| `Expenses:Ｍ医療費`（先頭が全角Ｍ U+FF2D） | なし | True | できた |
| `Expenses:M-医療費` | なし | True | できた |
| `Expenses:1医療費` | なし | True | できた |
| `Assets:現金:太郎` | `Invalid account name` | False | — |
| `Assets:Cash:太郎` | **なし** | **False** | できた |
| `Assets:Cash:Taro` | なし | True | できた |
| `Expenses:Ä医療費`（Ä は Lu） | なし | True | できた |
| `option "name_assets" "資産"` ＋ `資産:Cash` | `Error for option 'name_assets': Invalid root account name: '資産'` と `Invalid account name: 資産:Cash`。`name_assets` は `Assets` のまま | — | — |

分かったこと：

- ルートの次の成分（第2成分）が漢字・かなで始まると読み込みでエラーになる。第2成分が大文字・数字で始まっていれば、**第3成分以降は漢字で始まってもエラーにならない**。ただしこの場合 `account.is_valid()` は False で、ライブラリ内部の判定と食い違う。
- 成分の先頭を大文字（ASCII、全角英字、Ä など）や数字にすれば、その後ろは日本語を書ける（`Expenses:M-医療費` など）。
- ルート名（Assets / Liabilities / Equity / Income / Expenses）は日本語にできない。

## 2. 日本語の文字列・メタデータ・タグ（`2_japanese_text`）

- payee `山田医院`、narration `初診料（次郎）`、取引のメタデータの値 `patient: "次郎"`、posting のメタデータの値 `memo: "保険適用後の自己負担"` は、エラーなく読め、値もそのまま取り出せた。
- メタデータのキーを日本語にする（`患者: "次郎"`）と `Invalid token: '患者:'`。
- タグ `#医療費` は `syntax error, unexpected HASH ...` と `Invalid token: '医療費'`。リンク `^医療-1` は `Invalid token: '^医療-1'`。

## 3. 取引ID（メタデータ `id:`）と beanquery による集計（`3_id_and_query`）

- `id: "tx-2026-0001"` を付けた取引を、beanquery の `WHERE entry_meta('id') = 'tx-2026-0001'` で特定できた（posting 2行が返る）。
- リンク `^tx-2026-0001` も付けられ、`WHERE 'tx-2026-0001' IN links` で引けた。
- 中間表現（人 × 期間 × 事実の種類）に近い集計が書けた：
  - `SELECT entry_meta('patient') AS patient, entry_meta('payer') AS payer, sum(number) AS total WHERE account ~ '^Expenses:Medical' AND year = 2026 AND currency = 'JPY' GROUP BY patient, payer`
    → `{patient: jiro, payer: taro, total: 3000}`, `{patient: taro, payer: taro, total: 1500}`（受診した人と支払った人を別々に持てる）
  - `SELECT entry_meta('person') AS person, month, sum(number) AS total WHERE account ~ '^Income:' AND year = 2026 GROUP BY person, month`
    → `{person: jiro, month: 2, total: -52000}`（収入は負の数で出る）
  - 結果は Python API（`beanquery.connect` → `execute` → `fetchall`）で取り出し、`Decimal` を文字列にして JSON にした。beanquery 自体に JSON 出力はない。
- 同じ `id` を2つの取引に付けても、beancount はエラーを出さない。重複はスクリプトで数えれば検出できた（`duplicate_id_check_by_script_after_adding_dup = ["tx-2026-0001"]`）。
- 境界の確認：`open` より前の日付（2025-12-25）の取引は `Invalid reference to inactive account` のエラーになる。

## 4. `plugin` 行（`4_plugin`）

実行されるコードは、どれも一時ディレクトリにマーカーファイルを1つ書くだけのもの。

| 試験 | 台帳に書いたもの | コードが実行されたか | エラー |
|---|---|---|---|
| 4a | 同じディレクトリに `r2_harmless_plugin.py`、台帳に `option "insert_pythonpath" "TRUE"` と `plugin "r2_harmless_plugin"` | **実行された** | なし |
| 4b | 4a から `insert_pythonpath` を除いたもの（`-I` で実行） | されなかった | `Error importing "r2_harmless_plugin"` |
| 4c | `.py` は置かず、台帳に `plugin "beancount.plugins.check_commodity" "__import__('pathlib').Path('…/eval_marker.txt').write_text('eval executed') and {}"` | **実行された** | `Missing Commodity directive ...` だけ（コードの実行は何も報告されない） |
| 4c | 同じく `beancount.plugins.commodity_attr` | **実行された** | なし |
| 4c | 同じく `beancount.plugins.check_average_cost`（末尾を `and 0.01`） | **実行された** | なし |
| 4d | 4c の `plugin` 行を include 先のファイルに書いたもの | されなかった | なし（include 先の `plugin` 行は黙って無視される。`options_map["plugin"] = []`） |
| 4e | include 先（`sub/sub.beancount`）に `option "insert_pythonpath" "TRUE"`、`sub/` に `.py`、トップレベルに `plugin "r2_harmless_plugin"` | **実行された** | なし（`pythonpath = ["<TMP>\plugin_e\sub"]`） |

- **beancount の台帳ファイル1つ（テキストだけ）で任意の Python コードが実行される**（4c）。`python -I` でも防げない。
- 対策の試験（4f）：読み込む前に `beancount.parser.parser.parse_file` だけで全ファイル（include を loader と同じ規則で展開）を走査し、`plugin` 行・`insert_pythonpath`・`plugin_processing_mode` の変更・暗号化ファイル・root の外への include を検出したら拒否する関数 `prescan`（スクリプト内）を書いた。4a〜4e の台帳はすべて拒否され（4d の include 先の `plugin` 行も検出）、何もない台帳は受け入れた。なお、走査そのものでコードが実行されないことは、この実測では直接確かめていない（4a〜4e の後に同じディレクトリを走査したため、マーカーの有無で区別できない）。`parse_file` がプラグインを読み込まないことはソースで確認した（公開資料の文書 §1.2）。

## 5. `include` 行（`5_include`）

- 台帳のディレクトリの外にあるファイルを `include "../include_outside/other.beancount"`、絶対パス、glob `../include_outside/*.beancount` のどれでも読めた（`Assets:Outside` が開かれた）。同じファイルの2回目以降は `Duplicate filename parsed` のエラー。
- 台帳でないテキストファイル（`notes.txt`）を include すると、`Invalid token: 'これは台帳ではないテキスト'`, `Invalid token: 'password'`, `Invalid token: '='`, `Invalid token: 'hunter2'` のように、**ファイルの中身の断片がエラーメッセージに出た。**
- `prescan` は root の外への include を2件検出して拒否した。

## 6. 読み込みキャッシュ（pickle）（`6_pickle_cache`）

- 台帳 `main.beancount` の隣に、読み込むとマーカーを書く pickle を `.main.beancount.picklecache` という名前で置き、`loader.initialize(use_cache=True)`（環境変数なしのときの既定と同じ）で `loader.load_file` を呼んだ → **マーカーが作られた**（その後 `TypeError: cannot unpack non-iterable int object` で読み込みは失敗）。
- `loader.initialize(use_cache=False)`（`BEANCOUNT_DISABLE_LOAD_CACHE` を設定したときと同じ）では、マーカーは作られず、キャッシュファイルは削除され、台帳は正常に読めた。

## 7. 証憑（`document`）（`7_document`）

- `2026-01-10 document Expenses:Medical "receipts/2026-01-10.山田医院.pdf"` は台帳のディレクトリ基準の絶対パスになり、メタデータ `txid: "tx-2026-0001"` も付けられた。日本語のファイル名も問題なし。
- 存在しないファイルを指す document は `File does not exist: ...` のエラー。
- `option "documents" "docs"` で、`docs/Expenses/Medical/2026-02-03.再診.pdf` から Document が自動生成された。`docs/Expenses/医療費/2026-02-04.x.pdf` は、ディレクトリ名が勘定科目名として不正なので無視された（エラーも出ない）。

## インストールして確かめるべきこと（hledger / ledger。未実施）

- hledger（安定版 1.52.4 と 2.0 プレビュー 1.99.6）：日本語の勘定科目名・ルート名・タグ名、`account 資産  ; type: A`、`print -O json` / `balance -O json` の出力、journal から rules ファイル（`source | コマンド`）を include したときにコマンドが実行されるか（1.52.4 と 1.99.6 の両方）、`hledger-web` の既定の待ち受けと `add` 権限。
- ledger 3.4.1：配布バイナリが Python 対応か（`ledger --version` や `python` ディレクティブを書いた journal で parse error になるか）、日本語の勘定科目名、`xml` 出力。
