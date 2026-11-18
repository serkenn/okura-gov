# 実装前の追加調査：tools の文書の独立検証（2026-11-09）

- 実測日：2026-11-09（実装前の追加調査、トピック tools）
- 種別：実測（検証の記録）。担当とは別の検証者が、tools の文書の主張を根拠の文書と、その先の `results.json`・ソース・一次情報に当たり直した記録。
- 検証した文書（以下の略号で参照）：
  - [OFP] `docs/measurements/20261109_impl-prep_tools-openfisca-probe.md`
  - [BCP] `docs/measurements/20261109_impl-prep_tools-beancount-probe.md`
  - [SRC] `docs/public-sources/20261109_impl-prep_tools-source-notes.md`
  - [H] `docs/hypotheses/20261109_impl-prep_tools-adoption-recheck.md`
  - [I] `docs/inferences/20261109_impl-prep_tools-implementation-checks.md`
- この文書は、上の各文書の末尾にあった「検証の記録（2026-11-09、独立検証）」の節を、規約（検証のコードと結果は実測として記録する）に合わせてここに移したもの。内容は移す前と同じ。各文書には「訂正の記録」の節で、訂正した節の一覧だけを残した。本文の中の〔2026-11-09 独立検証…〕の注は各文書に残っている。

## 根拠（再実行の方法）

| スクリプト | 出力 |
|---|---|
| `scripts/IMPL_tools_verify.py`（標準ライブラリだけ。V1〜V9） | `scripts/results/IMPL_tools_verify/results.json`、`summary.txt` |

```
C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/IMPL_tools_verify.py
```

- 環境：pyenv の CPython 3.11.9、`-I -X utf8`。
- 確かめたこと（スクリプトの冒頭の注のとおり）：
  - V1 [SRC] が挙げたソースの行番号に主張どおりのコードがあるか（実測用 venv の OpenFisca-Core 46.0.1・beancount 3.2.3 のファイルをテキストとして読む。実行はしない）
  - V2 読んだ版の一致（clone の HEAD・タグ、clone・wheel・venv のファイルの一致、wheel の SHA-256 と PyPI の JSON の digest）
  - V3 GitHub のタグが指すコミット（`git ls-remote`）
  - V4 floor(x × r) の float32・float64 の食い違いの数（[OFP] P08）を numpy を使わずに再計算
  - V5 期間・月・年齢・見本の合計（P01・P02・P09・P10）の暦の上の再計算
  - V6 [OFP] の時間の比（%・倍）を `results.json` から再計算
  - V7 [OFP]・[BCP] の数値と `results.json` の突き合わせ
  - V8 `-I` の有無と起動の形（`-c`・スクリプト・`-m`）で `sys.path[0]` がどうなるか（[BCP] A9 の一般化の確認）
  - V9 [H] H1 の4 の健保の年齢の基準日を一次情報で確かめる（取得物は `.work/downloads/<日時>_<名前>/` に置き、データとしてだけ読む。取得した原文の内容は [SRC] §4）
- プローブ（`scripts/IMPL_tools_openfisca_probe.py`、`scripts/IMPL_tools_beancount_probe.py`）は再実行していない（再実行すると `results.json` が上書きされ、本文の時間の値と合わなくなるため。beancount は A6 に 10 分近くかかる）。突き合わせの相手は、残っている `scripts/results/IMPL_tools_openfisca_probe/`・`scripts/results/IMPL_tools_beancount_probe/` の出力と、実測用 venv のソース。

## 1. [OFP] OpenFisca-Core 46.0.1 の実測

### 確かめたこと（一致した）

- 環境の版：venv の dist-info が openfisca_core 46.0.1・numpy 2.4.6・numexpr 2.14.2・pyyaml 6.0.3・psutil 7.2.2（V2）。
- §1 の表の8行（`str(period)`・2つのパラメータの値・式の切り替え）を `results.json` と突き合わせて一致（V7）。start・stop と ADD の月を暦で再計算して一致（V5）。
- §2〜§3、§5（2**31 の欄を除く）、§7、§8（検査で止めた 20 件がすべて終了コード 2、出力 39,720 バイト、2回の SHA-256 が同じ）、§10 の値は `results.json` と一致。試験用パッケージの変数 34・パラメータ 5 ファイル・見本の合計（子1 967,800、子2 979,800）・年齢（V5）も一致。
- §6 の表：食い違いの数（float32・float64、x<2²⁴）と例のすべてを、numpy を使わない計算で再現して一致（V4）。float32 への丸め（16777217→16777216、20000001→20000000、123456789→123456792）、int32 のあふれ（-2147483648）、0 方向への丸め（-300000。切り捨てなら -300001）も一致。
- §9 の CLI の wall・内訳・プロセス内の中央値・出力の大きさ・メモリ（46〜51 MB）・import の内訳は `results.json` と一致。`openfisca_core.tools` が `numpy.testing` を import することはソース（`openfisca_core/tools/__init__.py:3`）で確認。

### 訂正（節：訂正前 → 訂正後、根拠）

1. 冒頭の注：「実行ごとに 2〜3 割ほど揺れた」→ 同じ実行の中の CLI の3回で 13〜25%、前の実行との比較は記録が無い、と書き直した。根拠：V6（`CLI wall（trace あり3回）の最大 ÷ 最小` が 1.253・1.126・1.14）。本文 §4（約2倍）・§9（2〜5 割）とも食い違っていた。
2. §4：`calculation_time` の例「0.001112、別の実行では 0.00069」→「P05 で 0.001559、P06 で 0.0009997」。根拠：V7（元の2つの値は `results.json` に無い）。
3. §4：`json.dumps` の TypeError の原因「`生年月日` の値が `datetime.date` のリスト」を実測から推測（I）に改めた。根拠：`results.json` の `P05` で型を見たキー `生年月日<eternity>` は flat に無く（キーは `生年月日<2025>`）、型の一覧が空（V7）。
4. §5：int の `2**31` の「エラー（too large）」→「エラー（`SituationParsingError`）」とし、「too large」はソースからの読み取りと注記。根拠：`results.json` の例外の文字列は 300 字で切れている（V7）。ソース `variables/variable.py:462-464`（V1）。
5. §6：float64 の食い違いの説明「0.29 が2進数で 0.29 よりわずかに小さく表されるため」→ 積を倍精度に丸めた値が整数の手前になるため、と改めた。根拠：V4（0.3 も2進数では小さい 0.2999999999999999888… が食い違いは 0 件。1500×0.29 = 434.99999999999994、10×0.3 = 3.0）。
6. §9：「8 → 26 シミュレーションで約 3〜4 倍」「プロセス内の中央値で 3〜6%」→「プロセス内 3.0 倍、CLI の evaluate_s 2.9〜4.5 倍」「2.6〜6.6%」。CLI の1回ずつの `evaluate_s` では trace ありが 1.04〜2.05 倍だったことを追記（「大きな差は無かった」はプロセス内の中央値についての結論）。import の割合 6〜7割の内訳（5人の4回で 61〜75%、10人で 46〜61%、Python の起動は含まない）を追記。根拠：V6。

### 確認できなかったこと

- 「前の実行」の値（§4 の 5.2〜5.7 ms・6.7〜7.6 ms、§9 の 1.6〜1.8 秒・1.2〜1.8 秒・2〜5 割）：出力が上書きされて残っていない。
- プローブの再実行による挙動の再現（独立にもう一度動かしてはいない）。挙動はソース（V1。本文が引く行はすべて一致）と `results.json` の整合で確かめた。
- §7 の2つの年齢の書き方のどちらが法的に正しいか：[OFP] では扱わない。健保については、[H] H1 の4 に一次情報の確認結果を追記した（下の §4）。

## 2. [BCP] beancount 3.2.3 の実測

### 確かめたこと（一致した）

- 版：venv の dist-info が beancount 3.2.3・beanquery 0.2.0。wheel（`.work/downloads/20261109-150346_beancount/`）の中の 173 ファイルは venv とバイト単位で同じ。wheel の SHA-256（`851147a9…`）は PyPI の JSON（2026-11-09 取得）の digest と一致。venv の `beancount/*.py` 161 ファイルは clone（HEAD `eeda2aa2`＝タグ `3.2.3`）と改行コードを除いて同じ。GitHub のタグ `3.2.3` も `eeda2aa2a3204ffb980dab11220b2abde5e80b38`（V2・V3）。
- A1〜A10・B1〜B3 の表と本文の値を `results.json` と1つずつ突き合わせ、下の「訂正」以外は一致。A5 は 24 通りで、v1・v2 とも「受け入れたのにコードが実行された」ものは 0（V7）。A6 の倍々の比 3.92・4.02・3.99、16 行の対照は1行の 16.4 倍、メモリ 27.6〜42.9 MB（V6）。B2 の SHA-256 `b65fd97c…`、`(50000 + 2000) JPY` → `"52000"`。
- スクリプトの注（`loader.py:847` の `BEANCOUNT_DISABLE_LOAD_CACHE`）と、A1 の「pickle のファイルは loader が消した」の裏づけ（`use_cache=False` では `delete_cache_function`：`loader.py:843`）をソースで確認（V1）。

### 訂正（節：訂正前 → 訂正後、根拠）

1. 根拠（再実行の方法）の「比べた走査の関数」の表：`prescan_v1` を「R2 の `prescan` をそのまま写したもの」→「写したもの。判定の処理は同じだが、報告の文言と戻り値が違う」。根拠：`scripts/R2_beancount_check.py:344-377` と `scripts/IMPL_tools_beancount_probe.py` の `prescan_v1` の比較（R2 は `config=…` を出し、`files` は一覧。プローブは件数で、`problems` を 20 件まで）。
2. A3：「外を通って root の中のファイルだけに一致するパターンは、v1 では受け入れられる」を、実測ではなくコードからの読み取り（I）と明記。根拠：A3 の試験はこのパターンを含まない（`results.json` の A3 は外の `x.beancount` に一致する場合と一致なしの場合だけ）。
3. A5：UTF-16LE の v2 の理由「NUL、UTF-8 でない」→「BOM あり：NUL・UTF-8 でない。BOM なし：NUL だけ」。根拠：`results.json` の A5（V7）。
4. A9：「`-I` が無いと、カレントディレクトリの `.py` が標準ライブラリより先に import される」は `-c` での結果で、起動の形で変わることを追記。根拠：V8（`-c`・`-m`（カレントのモジュール）では台帳の `glob.py` が import された。別のディレクトリのスクリプトを指定したときは `sys.path[0]` がスクリプトのディレクトリで、import されなかった。`-I` ではどの形でも import されなかった）。結論は変わらない。

### 確認できなかったこと

- 最初の版での「60 MB の1行で CPU 時間 600 秒を超えた」：記録が残っていない。
- プローブの再実行による挙動の再現（ファイルのシンボリックリンク、`.gpg`／`.asc` の include は本文どおり未試験のまま）。
- 字句解析器（`_parser.cp311-win_amd64.pyd`）の中で長い行に2乗の時間がかかる原因：本文と同じく読んでいない。
- 16 MB・20 MB の時間（2乗の伸びからの見積もり。8 MB の 64.9 秒から 16 MB は約 260 秒、20 MB は約 406 秒：V6）は見積もりで、実測ではない。16 MB が 240 秒で打ち切られたことと矛盾はしない。

## 3. [SRC] ソースで確かめたこと

ソースは実測用 venv の中のファイルをテキストとして読んだだけで、実行していない。

### 確かめたこと（一致した）

- **行番号**：本文が挙げた行（OpenFisca-Core 51 か所、beancount 21 か所、`scripts/R2_beancount_check.py:344-377`）のすべてで、主張どおりのコードがその範囲にあった（V1。不一致 0）。補足として、`values_list` が新しい順に並べられること（`parameters/parameter.py:77-80`）、`ops.documents` が既定で動くこと（`loader.py:54-55` の `PLUGINS_PRE`）、`option "documents"` の相対パスが台帳ファイル基準になること（`ops/documents.py:115-117`）も確かめた。
- **版（OpenFisca-Core）**：GitHub のタグ `46.0.1` は `5a9fb9e6d30b2b002c1ec1a022d57dfecffeafd4`（`git ls-remote`、2026-11-09）。clone（`.work/downloads/20261109-132258_openfisca-core/`）の `refs/heads/main` は `db0484b54871b0a73e673478b3153841dba908e9`、`refs/tags/46.0.1` は上と同じ。venv の `openfisca_core/*.py` 167 ファイルは clone（main）と改行コードを除いて同じ（[SRC] §0 の表の6ファイルを含む）。wheel（`.work/downloads/20261109-150145_openfisca-core/openfisca_core-46.0.1-py3-none-any.whl`）の `openfisca_core/`・`openfisca_web_api/` の 201 ファイルは venv とバイト単位で同じ。wheel の SHA-256 `09a4cdc1…` は取得済みの PyPI の JSON の digest と一致（V2・V3）。
- **版（beancount）**：GitHub のタグ `3.2.3` は `eeda2aa2a3204ffb980dab11220b2abde5e80b38`。clone の HEAD・`refs/tags/3.2.3` も同じ。venv の `beancount/*.py` 161 ファイルは clone と改行コードを除いて同じ。wheel の 173 ファイルは venv と同じ。wheel の SHA-256 `851147a9…` は PyPI の JSON（[SRC] §0 の取得物。2026-11-09 取得、`.work/downloads/20261109-*_IMPL_tools_verify_pypi_beancount/`）の digest と一致（V2・V3）。
- リポジトリの URL（[SRC] §0 の表の2つ）は、どちらも `git ls-remote` で応答し、上のタグがあった（V3）。

### 訂正（節：訂正前 → 訂正後、根拠）

1. §1.6：「dtype を変える公開された設定は見当たらない」→「数値（int・float）の dtype を変える公開された設定は見当たらない」。`str` の変数は `max_length` で dtype が `|S{max_length}` になる（`variables/variable.py:125-128`）。変数のクラスに知らない属性を書くと ValueError（177-190行）。根拠：V1。
2. §2.4：設計の提案「正規化した JSON に出すときは…除くか、相対パスに直す必要がある（I）」を削除。公開資料の情報の文書には仮説（提案）を置かない規約（AGENTS.md）のため。同じ内容は [H] H3 にある。
3. §1.4：`SimpleTracer.record_parameter_access` が何もしないこと（`tracers/simple_tracer.py:43-46`）を追加。推測 I3 の前提に使われていたが、どの文書にも根拠が無かった。根拠：V1。
4. §2.2：「`does not exist`（446行）」→「判定は446行、文言は450行」（細かな補足）。根拠：V1。
5. §4（追加）：[H] H1 の4 の健保の年齢の基準日の一次情報（下の §4）。元は「検証の記録」の中の小節だったものを、公開資料の情報の本文の節にした。

### 確認できなかったこと

- `parse_file` に `report_filename` を渡さないとき、C のパーサがファイルの名前を何から取るか（§2.3 の「またはファイル名」）：C のコードは読んでいない。loader（`report_filename` を渡さない）で読んだ [BCP] A8 で、document の相対パスが台帳のディレクトリ基準で解決されたこととは合う。

## 4. [H] 採用の前提の仮説

### 確かめたこと（一致した）

- H1・H2・H3 の数値（16,777,217→16,777,216、20,000,001→20,000,000、int32 の上限、悪い入力 20 通り、悪い台帳7種、細工 24 通り、5,000 ディレクトリで約3秒、8 MB の1行で 65 秒、16 MB で 240 秒超、メモリ約 50 MB、import が6〜7割）は根拠の文書と `results.json` に合っていた（V6・V7）。
- 参照の規約：根拠に挙げた文書はすべて実測か公開資料の情報で、外部の URL を参照していない。冒頭の推測の文書へのリンクは根拠ではなく案内。
- 健保の年齢の基準日：[SRC] §4 の一次情報（厚生労働省 事務連絡 令和7年7月4日 Q4・Q8、日本年金機構 FAQ。robots.txt で許可されていることを確かめてから取得：V9）で、`docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md` §5.5 の記載（扶養認定日が属する年の12月31日）を確かめた。

### 訂正（節：訂正前 → 訂正後、根拠）

1. H1 の4：健保の年齢の基準日「判定日の属する年の12月31日など」に根拠が無かった → 「扶養認定日が属する年の12月31日［KENPO-src］§5.5」とし、［KENPO-src］を根拠の一覧に足した。さらに、同じ一次情報（Q4）が「誕生日が1月1日である者は12月31日において年齢が加算される」とすることを追記し、[OFP] §7 の `年齢_年末`（12月31日の暦の年齢）で数えると1月1日生まれを1歳少なく誤ること（正しいのは `年齢_年末の翌日` の列と同じ結果）を書いた。根拠：V9、[SRC] §4。
2. H2 の運用の条件1：「`-I` が無いと、台帳のディレクトリにある `glob.py` が先に import された」に、起動の形の条件（`-c`・`-m` のとき。スクリプトを指定したときはスクリプトのディレクトリ）を追記。根拠：V8（上の §2 の訂正4）。
3. H1 の根拠：推測 I4 が使っていた「プロセス内の evaluate の中央値 0.16〜1.0 秒」が仮説に無かった → [OFP] §9 を根拠に追記（推測は仮説だけを前提にする規約のため）。
4. H1 の5：推測 I3 の前提（トレースなしの `SimpleTracer.record_parameter_access` は何もしない）が仮説に無かった → [SRC] §1.4 を根拠に追記。

### 確認できなかったこと

- 所得税で1月1日生まれの年齢をどう数えるか（H1 の4）：国税庁の原文には当たり直していない。
- H4 の「致命的な安全上の問題は見つかっていない」：今回の実測とコードを読んだ範囲での主張で、無いことそのものは確かめようがない。
- Q2（健保の「今後1年間」の数え方）：本文どおり未決。

## 5. [I] 実装の約束から導いた推測

### 確かめたこと

- 規約：どの推測も前提の仮説（[H] の H1〜H3）を挙げ、検証方法を書いている。
- I3 の前提の事実：`SimpleTracer.record_parameter_access` は何もしない（`tracers/simple_tracer.py:43-46`）。式の中の `人.simulation` は、Population がシミュレーションを持つことで使える（`populations/_core_population.py` で `self.simulation.calculate(...)` を呼んでいる）。どちらもソースで確認した（V1）。`record_parameter_access` が OpenFisca のドキュメントで公開された使い方かは確かめていない（[I] の検証方法に残したまま）。
- I1 の検証方法の範囲（0〜20,000,000、3 刻み、率 0.05〜0.57・0.021）は、[OFP] §6 の表と同じであることを確かめた。食い違いの数は numpy を使わない計算でも同じだった（V4）。

### 訂正（節：訂正前 → 訂正後、根拠）

1. I3・I4：仮説に無い事実（I3 の `SimpleTracer` が何もしないこと、I4 のプロセス内の evaluate の中央値）を前提にしていた → [H] の H1 の5・H1 に根拠つきで足し、[I] ではそれを指すようにした。根拠：上の §4 の訂正3・4。
2. I2：[H] H1 の4 の訂正（健保の年齢は1月1日生まれが12月31日に加算される）を受けて、検証方法 (c) に1月1日生まれの場合を足した。

### 確認できなかったこと

- まだどの推測も検証されていない（[I] の本文の記述どおり）。
