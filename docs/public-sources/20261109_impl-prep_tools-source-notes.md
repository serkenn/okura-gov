# 実装前の追加調査：OpenFisca-Core 46.0.1 と beancount 3.2.3 のソースで確かめたこと（期間・根拠・入力の型・読み込み）

- 作成日：2026-11-09（実装前の追加調査、トピック tools）
- 種別：公開資料の情報（ソースコードを静的に読んで分かったこと）。実行して確かめたことは別ファイル：
  - `docs/measurements/20261109_impl-prep_tools-openfisca-probe.md`
  - `docs/measurements/20261109_impl-prep_tools-beancount-probe.md`
- R2 で読んだことは繰り返さない（`docs/public-sources/20261109_R2-tools_openfisca-core-source.md`、`docs/public-sources/20261109_R2-tools_plain-text-accounting-source.md`）。ここに書くのは、その後に足りなかった箇所だけ。
- 記号：F＝コードで確認、I＝コードからの読み取りによる推測（実測で確かめたものは実測の文書を参照）。

## 0. 読んだ版

| ツール | 読んだファイル | 版 | 一致の確認 |
|---|---|---|---|
| OpenFisca-Core | `.work/venvs/R2-openfisca/Lib/site-packages/openfisca_core/`（PyPI の wheel を入れたもの） | 46.0.1（タグ `46.0.1` = `5a9fb9e6d30b2b002c1ec1a022d57dfecffeafd4`、https://github.com/openfisca/openfisca-core 、取得日 2026-11-09） | R2 で wheel 全体と clone の一致を確認済み。今回も下の表の6ファイルを clone（`.work/downloads/20261109-132258_openfisca-core/`、main `db0484b5`。`openfisca_core/` は 46.0.1 と差分なし）と `diff --strip-trailing-cr` で比べ、差分なし：`simulations/simulation_builder.py`、`periods/period_.py`、`tracers/flat_trace.py`、`tracers/tracing_parameter_node_at_instant.py`、`variables/config.py`、`taxbenefitsystems/tax_benefit_system.py` |
| beancount | `.work/venvs/R2-beancount/Lib/site-packages/beancount/` | 3.2.3（タグ `3.2.3` = `eeda2aa2a3204ffb980dab11220b2abde5e80b38`、https://github.com/beancount/beancount 、取得日 2026-11-09） | R2 で `loader.py`・`parser/grammar.py` などがタグとバイト単位で一致することを確認済み |

以下の行番号は、すべて上の版のもの。

## 1. OpenFisca-Core 46.0.1

### 1.1 パラメータはどの日付の値で評価されるか（F）

- 式の第3引数 `parameters` は、トレースなしなら `tax_benefit_system.get_parameters_at_instant`、トレースありなら `Simulation.trace_parameters_at_instant`（`simulations/simulation.py:331-351`）。
- `get_parameters_at_instant(instant)` は、引数が `Period` なら `instant.start` を使う（`taxbenefitsystems/tax_benefit_system.py:443-466`、462-463行）。
  つまり式の中の `parameters(period)` は、**期間の始まりの日**の値になる。`parameters(period.stop)` のように Instant を渡せば、その日の値になる。
- 1つのパラメータの値は、`values_list`（新しい順）を先頭から見て、`instant_str <= 参照日` を満たす最初のものを返す（`parameters/parameter.py:213-217`）。値が `null` の区間は `ParameterNodeAtInstant` に子として登録されず、参照すると `ParameterNotFoundError`（`parameters/parameter_node_at_instant.py:23-34`）。
- 式（`formula_YYYY_MM_DD`）の選択も期間の始まりの日で決まる（`variables/variable.py:384-431`、412-413行の `instant = period.start`）。

### 1.2 期間の文字列表現は日を落とす（F）

- `Period.__str__`（`periods/period_.py:126-157`）：
  - 長さ1の年の期間で、始まりが1月でないもの（rolling year）は `f"year:{年}-{月:02d}"`（139-144行）。**始まりの日は文字列に入らない**。始まりが1月なら日にかかわらず `"{年}"`（140-142行）。
  - 長さ1の月の期間は `f"{年}-{月:02d}"`（147-148行）。これも日を落とす。
  - 日の期間だけは日まで入る（154-157行）。
- この文字列が使われる箇所：
  - `SimulationBuilder.add_variable_value` は入力を `self.input_buffer[変数名][str(periods.period(period_str))]` に貯める（`simulations/simulation_builder.py:651`）。`finalize_variables_init` はそのキーの文字列を `periods.period(...)` で解析し直して `holder.set_input` に渡す（669-684行）。
    → `year:2025-10-15` で入れた値は、キー `year:2025-10` を経て **`year:2025-10-01` の値として登録される**（I。実測で確認：実測文書 P05b）。
  - トレースの平らな形のキー `f"{name}<{period}>"`（`tracers/flat_trace.py:58-63`）。
- 一方、計算結果のキャッシュ（`data_storage/in_memory_storage.py:60-62, 92-94`）は `Period`（タプル）をキーにするので、日を区別する。

### 1.3 月の変数を年の期間で合計するとき（`ADD`）の月（F）

- `calculate_add`（`simulations/simulation.py:182-`、224行）は `period.get_subperiods(変数の definition_period)` の各期間を合計する。
- `get_subperiods(MONTH)` は `self.first_month` から12か月（`periods/period_.py:486-490`）。`first_month` は始まりの日を含む月の1日から始まる月（892-896行）。
  → `year:2025-09-30` の合計は 2025-09〜2026-08 の12か月になる（期間の大部分が入る 2026-09 は入らない）。実測文書 P02 で確認。

### 1.4 トレース（計算の過程）の構造（F）

- `simulation.trace = True` で `FullTracer` に切り替わる（`simulations/simulation.py:67-76`）。Web API なしで Python から使える。Web API の `/trace` も同じ仕組みで、`get_serialized_flat_trace()` を返すだけ（`openfisca_web_api/handlers.py:67-90`）。
- `TraceNode`（`tracers/trace_node.py:8-34`）：`name`、`period`（`Period` オブジェクト）、`parent`、`children`、`parameters`（参照したパラメータの `TraceNode` のリスト）、`value`、`start`、`end`（時刻）。
- パラメータの記録：`FullTracer.record_parameter_access(name, period, value)` が、今計算中のノードの `parameters` に（名前、参照日の文字列 `YYYY-MM-DD`、値）を足す（`tracers/full_tracer.py:60-69`）。トレースなしのときの `SimpleTracer.record_parameter_access` は何もしない（`tracers/simple_tracer.py:43-46`。〔2026-11-09 独立検証で追加〕）。
  呼ぶのは `TracingParameterNodeAtInstant.get_traced_child`（`tracers/tracing_parameter_node_at_instant.py:50-81`）で、
  - 子が `numpy.ndarray` か `ALLOWED_PARAM_TYPES`（`float, int, bool, None, list, str`。`parameters/config.py:24`）のときだけ記録する（78-79行）。**累進税率表（`ParameterScale` から作られる税率表のオブジェクト）を引いて `.calc()` しても記録されない**（I。実測文書 P05 で確認）。
  - 列挙の配列などで添字をつけた（ベクトルで引いた）ときは、子の名前ではなく**親の名前**で記録する（70-76行）。
  - 記録されるのは名前・参照日・値だけで、パラメータのメタデータ（出典など）は記録されない。
- 取り出し方（`tracers/full_tracer.py`）：`trees`（32-34行）、`browse_trace()`（106-114行、全ノードを深さ優先）、`get_flat_trace()` / `get_serialized_flat_trace()`（100-104行）、`computation_log`（36-39行。`tracers/computation_log.py:17-45` の `lines()` は字下げつきの文字列のリスト）。
- `FlatTrace`（`tracers/flat_trace.py`）：
  - 同じキーの2回目以降（キャッシュの読み出し）は上書きしない（15-31行）。
  - 1件は `dependencies`、`parameters`、`value`、`calculation_time`、`formula_time`（45-56行）。後ろの2つは時刻の差で、実行ごとに変わる。
  - `serialize`（66-84行）は EnumArray を名前の文字列に、ndarray を `tolist()` にする。**日付の配列は `datetime.date` のリストになり、そのままでは `json.dumps` できない**（I。実測文書 P05 で確認）。

### 1.5 パラメータのメタデータ（F）

- `Parameter` は `description`、`metadata`（辞書）、`documentation` を持つ（`parameters/parameter.py:47-72`）。値ごとの `ParameterAtInstant` は、パラメータ全体の `metadata` を引き継いだうえで値ごとの `metadata` を重ねる（`parameters/parameter_at_instant.py:34-37`）。値ごとに書けるキーは `value`、`metadata`、`unit`、`reference`（12行）。
- YAML の日付（`2025-10-01` など）は、文字列のまま返す設定（`parameters/config.py:29-33`）なので、メタデータに日付を書いても文字列になる。
- トレースの（名前、参照日）から `tax_benefit_system.parameters` の木をたどり、`values_list` で参照日に当たる `ParameterAtInstant` を探せば、その値のメタデータに届く（I。実測文書 P05 で確認）。

### 1.6 値の型（dtype）と入力の変換（F）

- 変数の型ごとの numpy の dtype（`variables/config.py:8-50`）：`bool`→`bool_`、**`int`→`int32`**、**`float`→`float32`**、`str`→`object`、Enum→列挙用の整数、`date`→`datetime64[D]`。
  `Variable.__init__` が `self.dtype` を設定する（`variables/variable.py:116`）。数値（int・float）の dtype を変える公開された設定は見当たらない。〔2026-11-09 独立検証で訂正：元は「dtype を変える公開された設定は見当たらない」。`str` の変数だけは `max_length` を書くと dtype が `|S{max_length}` になる（`variables/variable.py:125-128`）。変数のクラスに知らない属性（例 `dtype = ...`）を書くと `Unexpected attributes in definition of variable` の ValueError になる（177-190行）〕
- dict の situation の値は `Variable.check_set_value`（`variables/variable.py:437-466`）を通る：
  - Enum で値が文字列 → 名前として index に変える。知らない名前は ValueError（438-450行）。文字列でない値は、そのまま numpy の配列に変える。
  - float・int で値が文字列 → `commons.eval_expression`（numexpr。R2 で確認済み）（451-452行）。
  - `numpy.array([value], dtype=self.dtype)[0]`（455行）。変換できないと ValueError、`OverflowError` も ValueError にする（456-464行）。
- `Simulation.set_input` → `Holder.set_input` でも、**配列でない文字列**なら `eval_expression` を通る（`holders/holder.py:239-240`）。配列（ndarray）は `astype(変数の dtype)` だけで、式は評価しない（245-266行）。
- 式の戻り値は `_cast_formula_result` で `astype(変数の dtype)` される（`simulations/simulation.py:393-407`）。int の変数の式が小数を返すと、**切り捨てではなく 0 方向への丸め（astype の動作）** で整数になる（I。実測文書 P08 で確認）。

## 2. beancount 3.2.3

### 2.1 `parser.parse_file` は1つのファイルだけを読む（F）

- `beancount/parser/parser.py:188-227`：
  - `encoding` に UTF-8 以外を指定すると ValueError（212-213行）。
  - 引数がファイル名なら `open(file, "rb")` で開く（220-221行）。`io.IOBase`（`io.BytesIO` を含む）ならそれをそのまま読む（222-223行）。**引数が文字列の `"-"` なら標準入力を読む**（215-216行）。
  - include はたどらない。文法の処理は include の文字列を `options["include"]` に足すだけ（`parser/grammar.py:439-447`）。
- したがって「読み込む前の走査」が include 先を調べるには、走査側が自分で include をたどる必要がある（R2 の `prescan` はそうしている）。

### 2.2 loader の include の展開（F）

- `loader._parse_recursive`（`beancount/loader.py:376-`）：
  - 読むファイルの列は幅優先（414行の `pop(0)`）。
  - 暗号化ファイルの判定（421行）は `utils/encryption.py:40-58`：拡張子が `.gpg`、または `.asc` で先頭 1024 文字に `--BEGIN PGP MESSAGE--`。拡張子の比較は大文字小文字を区別する。復号は `gpg --batch --decrypt` を `shell=False` で起動（61-80行）。
  - 同じファイル名（`normpath` したもの）の2回目は `Duplicate filename parsed`（435-442行）、無ければ `does not exist`（判定は446行、文言は450行）。
  - include は、include を書いたファイルのディレクトリを基準に `glob.glob(search_path, recursive=True)`（500行）。一致しなければエラー。
  - 読んだファイルの一覧は `options_map["include"] = sorted(filenames_seen)`（525行）。
- R2 の `prescan` は include の展開を loader と同じ `glob.glob` で行うので、**root の外かどうかの検査は glob で展開した後**になる（`scripts/R2_beancount_check.py:344-377`）。

### 2.3 document ディレクティブのパス（F）

- 相対パスは「いま解析しているファイル名」（`parse_file` の `report_filename`、またはファイル名）のディレクトリを基準に `path.abspath` する（`parser/grammar.py:799-821`、816-819行）。`..` や絶対パスも制限しない。
- 既定で動く `beancount.ops.documents`（`ops/documents.py:17`）：`option "documents"` のディレクトリの走査（35-67行）、document のファイルの存在確認（70-89行）。`option "documents"` のディレクトリも制限しない（相対なら台帳ファイル基準）。

### 2.4 自動で付くメタデータ（F）

- 取引・posting・document の `meta` には、解析した位置として `filename`（絶対パス）と `lineno` が入る（`data.new_metadata`。grammar の各処理）。
- 金額を省略した posting を補うときの印は `__automatic__`、ほかに `__residual__`、`__tolerances__`（`core/interpolate.py:236-242`）。〔2026-11-09 独立検証で削除：元はこの後に「正規化した JSON に出すときは、これらと `filename`・`lineno` を除くか、相対パスに直す必要がある（I）」とあった。設計の提案で、公開資料の情報の文書に置くものではないため消した。同じ内容は仮説の文書 H3 にある〕

## 3. 分からなかったこと・読んでいないこと

- OpenFisca のトレースが、`calculate_divide` などの別の経路でもパラメータを同じように記録するかは、コードを追っていない（今回の実測は `ADD` と通常の式だけ）。
- beancount の C の字句解析器（`_parser.cp311-win_amd64.pyd`）が BOM・NUL・不正な UTF-8 をどう扱うかは、ソース（`lexer.l`）を読んでいない。挙動は実測で確かめた（実測文書 A5）。
- beancount の文法（`grammar.y`）でメタデータの値に書ける型の一覧は読んでいない。実測で確かめた（実測文書 B1）。

## 4. 一次情報：健保の19歳以上23歳未満の年齢の基準日（F。2026-11-09 取得）

仮説の文書（`docs/hypotheses/20261109_impl-prep_tools-adoption-recheck.md`）H1 の4 の健保の年齢の基準日の根拠として、既存の `docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md` §5.5 の記載を、次の原文で当たり直した（取得物は `.work/downloads/20261109-*_IMPL_tools_verify_mhlw_R7QA19/`・`…_nenkin_faq_timing/`。どちらも robots.txt で許可されていることを確かめてから取得。取得と照合の実測は `docs/measurements/20261109_impl-prep_tools-verification.md` §4、`scripts/IMPL_tools_verify.py` の V9）。

- 厚生労働省保険局保険課・年金局事業管理課「19歳以上23歳未満の被扶養者に係る認定に関するＱ＆Ａについて」（令和7年7月4日、事務連絡）https://www.mhlw.go.jp/web/t_doc?dataId=00tc9628&dataType=1&pageNo=1
  - Q4：「所得税法（昭和40年法律第33号）上の取扱いと同様、その年の12月31日現在の年齢で判定する。…なお、健康保険法等における取扱いと同様、民法（明治29年法律第89号）の期間に関する規定を準用するため、年齢は誕生日の前日において加算することから、誕生日が1月1日である者は12月31日において年齢が加算される点に留意すること。」
  - Q8：「令和7年10月1日以降の届出で、令和7年10月1日より前に遡って認定する場合の19歳以上23歳未満の被扶養者の認定対象者の年間収入の要件は130万円未満ということでよいか。」「お見込みのとおり。」（150万円の要件が使われるのは、扶養認定日が令和7年10月1日以降の認定）
- 日本年金機構 年金Q&A「年齢要件（19歳以上23歳未満）は、いつの時点で判定するのですか。」https://www.nenkin.go.jp/section/faq/kounen/dependents/aged19to22/timing.html （ページの更新日 2025年8月19日）：「年齢要件（19歳以上23歳未満）は、扶養認定日が属する年の12月31日時点の年齢で判定します。」

## 訂正の記録

この文書は 2026-11-09 の独立検証で訂正された。訂正の内容と根拠は実測 `docs/measurements/20261109_impl-prep_tools-verification.md` §3 を参照。

訂正した節：

- §1.4 トレース（計算の過程）の構造
- §1.6 値の型（dtype）と入力の変換
- §2.2 loader の include の展開
- §2.4 自動で付くメタデータ
- §4 一次情報：健保の19歳以上23歳未満の年齢の基準日（追加）
