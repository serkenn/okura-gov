# 実装前の追加調査：beancount 3.2.3 の実測（安全な読み込みの走査そのものの安全性、台帳 → 正規化した取引 JSON）

- 実測日：2026-11-09（実装前の追加調査、トピック tools）
- 種別：実測
- コードを読んで分かったこと：`docs/public-sources/20261109_impl-prep_tools-source-notes.md`（以下 [SRC]）§2
- R2 の実測（`docs/measurements/20261109_R2-tools_beancount-runtime.md`。以下 [BC-run]）の続き。R2 で確かめたこと（plugin 行・insert_pythonpath・pickle キャッシュで任意コードが実行されること、日本語の勘定科目名など）は繰り返さない。
- R2 の推測 I5（`docs/inferences/20261109_R2-tools_adoption-checks.md`）の検証方法「まだ一度も走査していない新しいディレクトリで、走査そのものが安全かを確かめる」を行った。

## 根拠（再実行の方法）

| スクリプト | 出力 |
|---|---|
| `scripts/IMPL_tools_beancount_probe.py`（台帳・プラグイン・pickle・巨大ファイルをすべて一時ディレクトリに生成し、最後に消す。コードが実行される試験の中身は、一時ディレクトリにマーカーファイルを1つ書くだけ） | `scripts/results/IMPL_tools_beancount_probe/results.json`、`summary.txt`、`normalized_sample.json`（アダプタの出力の見本） |

```
.work/venvs/R2-beancount/Scripts/python.exe -I -X utf8 scripts/IMPL_tools_beancount_probe.py
```

- 環境：Windows 11 Pro 10.0.26200、CPython 3.11.9（uv が管理するもの）、R2 で作った隔離 venv `.work/venvs/R2-beancount`（beancount 3.2.3、beanquery 0.2.0。新しいパッケージは入れていない）。`sys.flags.isolated = 1`、UTF-8 モード。
- スクリプトは beancount の import より前に `BEANCOUNT_DISABLE_LOAD_CACHE=1` を設定し、読み込みのたびに `loader.initialize(use_cache=False)` を呼ぶ。
- **この PC の PATH には `gpg` がある**（`results.json` の `env.gpg_on_PATH: true`）。暗号化ファイル（`.gpg`／`.asc`）の include は試していない（gpg を起動するため）。
- 最初の版のスクリプトでは、A6 の「60 MB の1行」の `parse_file` が CPU 時間で 600 秒を超えても終わらなかったので、実行を止め、A6 を「大きさを倍々にして 240 秒で打ち切る」形に改めた。下の結果はすべて改めた版の最後の実行のもの。〔2026-11-09 独立検証：最初の版の 600 秒の記録は残っておらず確かめられない。スクリプトの注（A6）に同じ記述がある〕

比べた走査の関数（どちらもスクリプトの中にある）：

| 関数 | 中身 |
|---|---|
| `prescan_v1` | R2 の `prescan`（`scripts/R2_beancount_check.py:344-377`）を写したもの。include を loader と同じ `glob.glob` で展開し、展開した後に root の外かを確かめる。〔2026-11-09 独立検証で訂正：元は「そのまま写したもの」。判定の処理は同じだが、報告の文言（plugin の設定文字列 `config=` を出さない）と戻り値（`files` を件数に、`problems` を 20 件までに）が R2 のものと違う〕 |
| `prescan_v2` | 今回改めたもの。include の文字列を glob の前に検査（相対・ASCII・`..` なし・ワイルドカードなし・拡張子 `.beancount`）、実体のパスが見かけと違う（リンク・ジャンクション）・root の外・通常のファイルでないものを拒否、`stat` で大きさの上限（1ファイル 20 MB、合計 100 MB、500 ファイル）、ファイルを1回だけバイト列で読んで SHA-256 を取り同じバイト列を `parse_file` に渡す、BOM・NUL・不正な UTF-8 を拒否、**1行が 64 KiB を超えるファイルは `parse_file` に渡さず拒否**、plugin 行・insert_pythonpath・plugin_processing_mode・`option "documents"`・root の外を指す document を拒否 |
| `safe_load` | `prescan_v2` が受け入れたときだけ `loader.initialize(use_cache=False)` → `loader.load_file`。読み込んだ後、loader が読んだファイルの一覧（`options_map["include"]`）が走査したものと同じか、各ファイルの SHA-256 が走査のときと同じかを確かめる |

## A1 まだ一度も走査していない新しいディレクトリでの走査の安全性

R2 の悪い台帳（[BC-run] §4・§6）を、試験ごとに新しい空のディレクトリに作り直し、走査だけを行った。

| 台帳 | `prescan_v1` | `prescan_v2` | `safe_load` | 走査・読み込みの後のマーカー |
|---|---|---|---|---|
| 4a：同じディレクトリに `.py`、`insert_pythonpath` ＋ `plugin` | 拒否 | 拒否 | 走査で拒否 | なし |
| 4c：`check_commodity` の設定文字列の eval | 拒否 | 拒否 | 走査で拒否 | なし |
| 4c：`commodity_attr` | 拒否 | 拒否 | 走査で拒否 | なし |
| 4c：`check_average_cost` | 拒否 | 拒否 | 走査で拒否 | なし |
| 4d：include 先に plugin 行 | 拒否（include 先で検出） | 拒否 | 走査で拒否 | なし |
| 4e：include 先に `insert_pythonpath`、トップに plugin | 拒否 | 拒否 | 走査で拒否 | なし |
| 6：台帳の隣に細工した `.main.beancount.picklecache` | 受け入れ | 受け入れ | 読み込めた | **なし**（pickle は読まれなかった）。pickle のファイルは loader が消した |
| 何もない台帳 | 受け入れ | 受け入れ | 読み込めた | なし |

→ **走査（`parse_file` で読むだけ）ではコードは実行されなかった**。R2 で切り分けられなかった点（[BC-run] §4 の末尾）を確かめた。pickle キャッシュは走査では触らず、`use_cache=False` の読み込みでは読まれない（その代わり、台帳のディレクトリにあるキャッシュのファイルは削除される）。

## A2 `parse_file` は include をたどらない

`main.beancount` に `include "sub.beancount"`（plugin 行と台帳でない文字列を含む）、`include "missing.beancount"`（無い）、`include "*.nothing"` を書いた。

- `parse_file(main)`：`options["include"]` に3つの文字列が入るだけ。エラー 0、plugin 0、エントリは `Open` 1つ。マーカーなし。
- `prescan_v1`：include を自分でたどり、`sub.beancount` の plugin 行を検出、一致しない2つを報告して拒否。
- `prescan_v2`：`*.nothing` を形で拒否、`missing.beancount` を「開けない」、`sub.beancount` の plugin 行を検出して拒否。

→ 走査が include 先を調べられるのは、走査の関数が自分で include をたどっているから（[SRC] §2.1）。

## A3 include の glob が root の外を歩く

root（`ledger/`）の隣に 5,000 ディレクトリ（100 × 50）の木を作り、その奥に `x.beancount` を1つ置いた。

| include | glob の一致数 | `prescan_v1` | `prescan_v2` |
|---|---|---|---|
| `../**/*.beancount` | 2（外の `x.beancount` と root の `main.beancount`） | 拒否（外の1件）。**2.77 秒**（glob が外の 5,000 ディレクトリを歩いた） | 拒否（形）。0.011 秒 |
| `../outside_tree/**/*.nothing`（一致なし） | 0 | 拒否（一致なし）。**2.60 秒** | 拒否（形）。0.011 秒 |
| `C:/**/*.beancount` | — | 実行しない（ディスク全体を歩くため） | 拒否（形）。0.029 秒 |

→ R2 の走査は、root の外かを確かめる前に glob で root の外のディレクトリを列挙する。外のファイルの中身は読まないが、時間は外のディレクトリの数に比例し、`C:/**` のような include でディスク全体を歩かせられる（I：5,000 ディレクトリで約3秒からの見積もり）。また、外を通って root の中のファイルだけに一致するパターンは、v1 では受け入れられる（I：`scripts/R2_beancount_check.py:358-376` の、glob で展開した後に `realpath` が root の中かだけを見る処理からの読み取り。〔2026-11-09 独立検証で注記：この点は実測していない。元は実測と区別せずに書いていた〕）。

## A4 include の循環

| 台帳 | `prescan_v1` | `prescan_v2` | loader |
|---|---|---|---|
| main → a、a → main、main → main | 受け入れ（2ファイル、止まった） | 受け入れ（2ファイル） | `Duplicate filename parsed` のエラー2件（読み込みは終わる） |
| `include "*.beancount"`（自分も一致） | 受け入れ | 拒否（形） | `Duplicate filename parsed` 1件 |

→ どちらの走査も循環で止まらなくなることは無かった。循環は loader のエラーとして出るので、読み込みのエラーを失敗として扱えば止まる。

## A5 エンコーディングの細工

各行は、plugin 行（`check_commodity` の設定文字列で一時ディレクトリにマーカーを書くもの）を細工して新しいディレクトリに置き、走査の判定と、**走査を通さずに loader で読んだときにコードが実行されたか**を比べた。

| 細工 | v1 | v2（v2 の理由） | loader でコードが実行されたか |
|---|---|---|---|
| 対照（そのまま） | 拒否 | 拒否 | された |
| UTF-8 BOM ＋ plugin 行（1行目） | **受け入れ** | 拒否（BOM） | されなかった（`Invalid token: '\ufeffplugin'`） |
| UTF-8 BOM ＋ 空行 ＋ plugin 行 | 拒否 | 拒否 | された |
| CRLF | 拒否 | 拒否 | された |
| CR だけ | 受け入れ | 受け入れ | されなかった（構文エラー） |
| NUL の行の後に plugin 行 | 拒否 | 拒否 | された |
| plugin 行の途中に NUL（`plu\0gin`） | 受け入れ | 拒否（NUL） | されなかった |
| plugin 行の後に NUL | 拒否 | 拒否 | された |
| 不正な UTF-8 のコメントの後に plugin 行 | 拒否 | 拒否 | された |
| plugin の設定文字列の中に不正な UTF-8 | 受け入れ | 拒否（UTF-8 でない） | されなかった（`UnicodeDecodeError` がエラーとして出た） |
| UTF-16LE（BOM あり／なし） | 受け入れ | 拒否（BOM あり：NUL・UTF-8 でない。BOM なし：NUL だけ〔独立検証で訂正：元は両方まとめて「NUL、UTF-8 でない」〕） | されなかった |
| 行頭に空白・タブ（字下げした plugin 行） | 拒否 | 拒否 | **された**（`syntax error, unexpected INDENT` も出るが plugin 行は有効） |
| 全角の `ｐｌｕｇｉｎ`、大文字の `PLUGIN` | 受け入れ | 受け入れ | されなかった |
| U+2028・フォームフィードで区切る | 受け入れ | 受け入れ | されなかった（`Invalid token`） |
| 1 MB の長いコメント行の後に plugin 行 | 拒否 | 拒否（行が長すぎる） | された |
| 最終行が plugin 行で改行なし | 拒否 | 拒否 | された |
| 複数行の文字列の中に plugin 行 | 受け入れ | 受け入れ | されなかった |
| 取引の途中に字下げなしの plugin 行 | 拒否 | 拒否 | された |
| `option "insert_pythonpath" "true"`（小文字）／`"1"` | 拒否 | 拒否 | （`.py` を置いていないので実行なし。`insert_pythonpath` は True になった） |

→ 24 通りすべてで、**走査が受け入れたのにコードが実行された（すり抜け）ものは v1・v2 とも無かった**。走査も loader も同じ `parse_file`（同じバイト列を同じパーサ）で読むので、判定が食い違わなかった（I）。v1 が受け入れたもの（BOM、NUL、UTF-16 など）は、loader でもコードは実行されなかったが、台帳として正しくないファイルを黙って受け入れている。

## A6 巨大なファイル（子プロセスで時間とピークのワーキングセットを測った）

| ファイル | 処理 | 時間 | ピークのワーキングセット |
|---|---|---|---|
| 取引 100,000 件（9.1 MB、短い行） | `parse_file` | 5.3 秒 | 197 MB |
| 同 | `prescan_v1` / `prescan_v2` | 5.6 / 6.4 秒 | 197 / 206 MB |
| 同 | `loader.load_file` ＋ アダプタ（B） | 読み込み 23.8 秒 ＋ 正規化 14.9 秒 | 494 MB |

1行が長いファイル（`;` の後に `x` を並べた1行のコメント、その後に plugin 行）：

| 1行の長さ | `parse_file` の時間 |
|---|---|
| 1 MB | 1.03 秒 |
| 2 MB | 4.04 秒 |
| 4 MB | 16.3 秒 |
| 8 MB | 64.9 秒 |
| 16 MB | **240 秒で終わらず打ち切り** |
| 対照：1 MB の行を16行（16 MB） | 16.9 秒 |

- **1行の長さが2倍になると時間が約4倍**（行の長さの2乗に比例）。行の数には比例する（1 MB の行 16 本で 1 MB の行1本の約16倍）。メモリは増えなかった（28〜43 MB）。
- `prescan_v2` は 16 MB の1行のファイルを `parse_file` に渡さずに 0.074 秒で拒否（行が長すぎる）、21 MB のファイルを `stat` だけで 0.0016 秒で拒否（大きすぎる）。
- → ファイルの大きさの上限だけでは足りない（20 MB の上限の内側でも、1行が長いと数百秒以上かかる。I：8 MB で 65 秒、2乗の伸びからの見積もり）。

## A7 パス

| 細工 | `prescan_v1` | `prescan_v2` | 補足 |
|---|---|---|---|
| ファイルのシンボリックリンク（root の中 → 外） | — | — | **作れなかった**（`OSError: 1314`、権限が無い）。試していない |
| ディレクトリのジャンクション（root の中 → 外。管理者権限なしで作れた） | 拒否（realpath が root の外） | 拒否（実体のパスが違う） | マーカーなし |
| `include "NUL"` | **受け入れ**（glob が一致し、realpath も root の中の `...\ledger\NUL` のまま） | 拒否（形） | loader は `NUL` を空のファイルとして読み、エラーなし |
| `include "CON"` | 拒否（glob が一致しない）。子プロセスで 0.02 秒 | 拒否（形） | loader では読んでいない（コンソールの入力を待つおそれがあるため） |
| NTFS の代替データストリーム `data.beancount:hidden`（中身は plugin 行） | 拒否（ストリームの中身を読んで plugin 行を検出） | 拒否（形） | マーカーなし |

## A8 `option "documents"` と document が root の外を指す

root の外のディレクトリ（`outside_docs/`）を `option "documents"` に絶対パスで書き、`document` ディレクティブで `../outside_docs/secret.pdf` と存在しないファイルを指した。

- loader（走査なし）：Document が3件できた。`outside_docs/secret.pdf`、存在しない `no-such-file.pdf`（`File does not exist` のエラー）、**`option "documents"` の走査で見つけた root の外の `Expenses/Medical/2026-02-03.他人の書類.pdf`**。つまり root の外のファイル名と、ファイルが存在するかどうかが読み込みの結果に出る。
- `prescan_v1`：受け入れ（documents を見ていない）。
- `prescan_v2`：拒否（`option documents`、`document が root の外` 2件）。

## A9 `-I` なしで、台帳のディレクトリをカレントにして動かしたとき

台帳のディレクトリに、走査のコードが import するモジュールと同じ名前の `glob.py`（import されるとマーカーを書く）を置き、そのディレクトリをカレントにして `python -c "import glob"` を実行した。

| 起動 | import された `glob` | マーカー |
|---|---|---|
| `-I -X utf8` | 標準ライブラリの `Lib\glob.py` | なし |
| `-X utf8` だけ | **台帳のディレクトリの `glob.py`** | **作られた** |

→ 走査・読み込みのプロセスは `-I` で起動する必要がある（`-I` が無いと、カレントディレクトリの `.py` が標準ライブラリより先に import される）。

〔2026-11-09 独立検証で訂正：上の括弧は `-c` で起動したときの結果で、起動の形によって変わる。pyenv の CPython 3.11.9 で、台帳のディレクトリ（`glob.py` を置いた）をカレントにして確かめた（`scripts/IMPL_tools_verify.py` の V8）：`-c` と、カレントにあるモジュールを `-m` で起動したときは、`sys.path[0]` がカレント（台帳のディレクトリ）になり台帳の `glob.py` が import された。**別のディレクトリにあるスクリプトのファイルを指定して起動したときは、`sys.path[0]` はスクリプトのディレクトリで、台帳の `glob.py` は import されなかった**（その代わり、スクリプトのディレクトリにある `.py` が先に import される）。`-I` をつけると、`-c`・`-m`・スクリプトのどの形でも、カレントもスクリプトのディレクトリも `sys.path` に入らず（`sys.path[0]` は `python311.zip`）、台帳の `glob.py` は import されなかった（`-I -m` ではカレントのモジュールが見つからず終了コード 1）。結論（`-I` で起動する）は変わらない〕

## A10 走査と読み込みの間にファイルが変わったとき

`safe_load` の走査の後・読み込みの前に `sub.beancount` を書き換えた：`ok: false`、`changed_after_scan: ["sub.beancount"]`（読み込んだファイルの一覧は同じ）。書き換えなければ `ok: true`。
→ 変更は**読み込みの後で**検出できる。読み込みの途中でコードが実行される種類の変更（plugin 行を足すなど）は、この方法では防げない（I）。

## B1 メタデータの値の型

| 台帳の書き方 | Python の型と値 |
|---|---|
| `sv: "文字列"` | `str` 文字列 |
| `iv: 3` / `dv: 0.25` / `neg: -5` | `Decimal` 3 / 0.25 / -5 |
| `expr: 2*3` / `div: 10/3` | `Decimal` **6** / **3.333333333333333333333333333**（台帳の中の算術式が計算される） |
| `comma: 1,500` | `Decimal` 1500 |
| `dt: 2026-01-09` | `date` |
| `bv: TRUE` / `bf: FALSE` | `bool` True / False |
| `acct: Assets:Cash` / `cur: JPY` | `str`（文字列と区別できない） |
| `amt: 100 JPY` | `Amount`（100 JPY） |
| `tg: #x` | `str` `'x'`（`#` が落ち、文字列と区別できない） |
| `empty:`（値なし）/ `nv: NULL` | `None` |
| `患者: "x"`（日本語のキー）/ `Payer: "x"`（大文字始まり）/ `p: "x"`（1文字） | `Invalid token` のエラーが1件出て、**その取引全体が読み込み結果から消えた** |

- 自動で付くメタデータ：取引に `filename`（絶対パス）・`lineno`・`__tolerances__`、posting に `filename`・`lineno`、金額を省略した posting に `__automatic__`。
- posting の金額は書いたとおりの桁の `Decimal`（`1000.00 JPY` → `"1000.00"`）。

## B2 アダプタ（台帳 → 正規化した取引 JSON）の出力と決定性

スクリプトの `normalize` 関数（法令の解釈を含めず、並べ替え・型の明示・パスの相対化・ハッシュだけを行う）。見本の台帳（日本語の payee・narration・メタデータの値、`id`・`payer`・`patient`・`person`・`visit-date`・`memo`、`document` と `txid`、`1,500 JPY`、`(50000 + 2000) JPY`）を `safe_load` で読み、`scripts/results/IMPL_tools_beancount_probe/normalized_sample.json` に書いた。

- 取引ごとに `id`、`date`、`flag`、`payee`、`narration`、`tags`、`links`、`meta`（型つき：`{"string": …}`・`{"decimal": "…"}`・`{"date": "…"}`・`{"bool": …}`・`{"amount": …, "currency": …}`・`{"null": true}`）、`source`（root からの相対パスと行番号）、`postings`（`account`、`number`（文字列）、`currency`、`cost`、`price`、`interpolated`（`__automatic__` から）、`meta`）。
- document ごとに `date`、`account`、`path`（root からの相対パス。日本語のファイル名 `receipts/2026-01-10.山田医院.pdf`）、`sha256`、`bytes`、`meta`（`txid`）、`links`。
- 出典のファイル：`source_files` に root からの相対パス・SHA-256・バイト数（走査のときに取ったもの）。
- `1,500 JPY` は `"1500"`、`(50000 + 2000) JPY` は `"52000"`、省略した posting は `"-3000"`・`interpolated: true` になった。
- **決定性**：同じ台帳を別のディレクトリに写して同じ処理をした出力の SHA-256 は同じ（`b65fd97c…`）。`filename` の絶対パスを出さず、相対パスにしたため。

## B3 アダプタの検査

見本に問題のある取引を足した台帳で、アダプタが報告したもの（読み込みのエラーは 0 件）：

- `id` の重複（`tx-2026-0001`、8行目と33行目）。beancount 自体は重複を報告しない（[BC-run] §3 と同じ）。
- `id` が無い取引、`id: 12345`（`Decimal` になる）の取引 →「id が無いか文字列でない」。
- 語彙に無いキー `patiant`（`patient` の書き間違い）。
- `id` の型が違う（期待 string、実際 decimal）。
- document の `txid` が指す取引が無い（`tx-9999-9999`）。

## 分からなかったこと・確かめていないこと

- ファイルのシンボリックリンクの経路（権限が無く作れなかった）。開発者モードか管理者で再実行する必要がある。
- `.gpg`／`.asc` の include（この PC には gpg があるが、起動させないため試していない。v1・v2 とも拡張子で拒否する）。
- 1行の長さが何バイトまでなら実用上の問題が無いか。今回の上限 64 KiB は仮の値で、実際の台帳の最長の行は測っていない。
- 字句解析器（C）の中で2乗の時間がかかる原因の箇所（ソースを読んでいない）。
- アダプタの正規化が 100,000 件で 14.9 秒かかった原因（パスの相対化を取引ごとに行っているためと思われるが、測っていない）。家族の台帳の件数（年に数千件程度と想定）では問題にならない（I）。

## 訂正の記録

この文書は 2026-11-09 の独立検証で訂正された。訂正の内容と根拠は実測 `docs/measurements/20261109_impl-prep_tools-verification.md` §2 を参照。

訂正した節：

- 根拠（再実行の方法）の「比べた走査の関数」の表
- A3 include の glob が root の外を歩く
- A5 エンコーディングの細工
- A9 `-I` なしで、台帳のディレクトリをカレントにして動かしたとき
