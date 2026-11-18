# okura_records：記録層（版 0）

家族の入出金の台帳（beancount）、事実台帳、判断台帳から、**法令の解釈をせずに** 中間表現（`okura_ir`）を作る。
依存は `okura_ir` と beancount 3.2.3（GPL）。判定コア（`okura_core`、OpenFisca は AGPL）とは互いに import しない（SCOPE §6）。
プロセスを分け、JSON だけでやり取りする。

```
main.beancount ─ safe_loader.load_ledger ─ adapter.normalize ─┐ 正規化した取引 JSON
facts.jsonl ────────────── facts_ledger.read ──────────────────┼─▶ build_ir.build_ir ─▶ 中間表現（okura_ir.validate に通る）
judgments.jsonl ────────── judgments_ledger.read ──────────────┘
```

## 1. 責務

| する | しない |
|---|---|
| beancount の台帳を安全に読む（§3） | 台帳の保存・編集・UI（D8） |
| 台帳 → 正規化した取引 JSON（取引 ID・日付・JPY の整数の金額・勘定・型つきのメタデータ・証憑のパスと SHA-256） | 勘定科目名からの推測（D3・D11。科目名に法的な意味を持たせない） |
| 事実台帳・判断台帳（追記のみの JSON Lines）の読み込みと、現在の状態への畳み込み・改ざんの検出 | 法令の解釈：所得区分、合計、按分、扶養の判定、基準額（D5 改）。このパッケージに法令の値は一つも無い |
| 中間表現の作成（純粋関数）と okura_ir による検査 | 判断・選択の欠けの補い（判定コアが全候補で評価する。D21 R6） |

`build_ir` が行うのは、法令と無関係な正規化だけ：型の明示（日付・整数・分数・区間・並び）、記帳の向きの符号を捨てて金額を 0 以上の整数の円にすること、台帳の記録の写し、並べ替え。

## 2. 公開する関数

| モジュール | 関数 | 中身 |
|---|---|---|
| `safe_loader` | `load_ledger(main, *, root=None, limits=DEFAULT_LIMITS) -> LoadResult` | 例外を送出しない。`result.ok` なら `result.ledger`（`LoadedLedger`）、そうでなければ `result.problems` |
| `adapter` | `normalize(ledger) -> (dict \| None, list[Problem])` | 純粋関数。正規化した取引 JSON（§5） |
| `facts_ledger` | `read(data: bytes, source) -> (LedgerState, list[Problem])` | 純粋関数。`parse`・`fold` に分けても呼べる |
| `judgments_ledger` | `read(data, source)`、`current_values(state, section="judgments")` | `current_values` は record の `replaces` の連鎖の先頭だけ |
| `jsonl_ledger` | `encode_entry(entry, previous_line) -> bytes`、`append_entry(existing, entry) -> bytes`、`append_drafts(existing, drafts, spec, source) -> (bytes \| None, list[Problem])` | 台帳に足す1行を作る（`prev_sha256` を計算して入れる）。`append_drafts` は手で書いた下書きの列をつなぎ、台帳全体を検査する（§4.2）。書き込みは呼び出し側 |
| `ledger_map` | `PLACEMENTS`、`SECTION_OF_KIND`、`guide_markdown()` | 語彙の種類ごとの書く場所（台帳の取引・事実台帳・判断台帳。§4.3）と、§4.3 の表 |
| `build_ir` | `build_ir(transactions, facts_state, judgments_state) -> BuildResult` | 純粋関数。`result.ok` なら `result.ir`（okura_ir の検査に通ったもの） |
| `cli` | `python -I -X utf8 -m okura_records.cli build-ir …`（§7） | |

問題は `Problem(where, code, message, origin)`。`where` は `main.beancount:12`・`facts.jsonl:3.record.id`・`$.facts[0].roles.payer` の形、
`origin` は中間表現の問題のときのその要素の出どころ（`facts.jsonl:3 (fe-0003)`・`main.beancount:12 (tx-…)`）。

`safe_loader` と `adapter` だけが beancount を読み込む。`problem`・`meta_vocabulary`・`ledger_map`・`jsonl_ledger`・`facts_ledger`・`judgments_ledger`・`build_ir` は
beancount なしで動く（`tests/test_layering.py` で確かめる）。

## 3. 安全な読み込み（safe_loader）

beancount の `loader.load_file` は使わない。走査で読んだバイト列を `parser.parse_file` に渡し、その結果だけで loader の `_load` と同じ順
（並べ替え → booking → ops.documents → ops.pad → ops.balance → ops.validation）に処理する。根拠：
`docs/measurements/20261109_R2-tools_beancount-runtime.md`（以下 R2）、`docs/measurements/20261109_impl-prep_tools-beancount-probe.md`（以下 BCP）、
`docs/hypotheses/20261109_impl-prep_tools-adoption-recheck.md` H2。

### 3.1 攻撃の経路と扱い

| 経路（実測） | 扱い | テスト（`tests/test_safe_loader.py`） |
|---|---|---|
| `plugin` 行（同じディレクトリの `.py`、既存のプラグインの設定文字列の eval。R2 §4・BCP A1） | 走査で拒否（`plugin`）。**しかも loader を使わないので plugin 行はどのみち実行されない** | `test_plugin_eval_in_config_is_rejected_and_not_executed` ほか（陽性対照つき） |
| include 先の plugin 行、字下げした plugin 行、改行の無い最終行・取引の途中の plugin 行（R2 4d・BCP A5） | include を自分でたどってすべてのファイルを走査し拒否 | `test_plugin_in_included_file_is_rejected`、`test_indented_plugin_line_is_rejected`、`test_plugin_line_positions` |
| `option "insert_pythonpath"`（どのファイルでも。値 `true`・`1` も。R2 4a・4e） | 拒否（`insert_pythonpath`）。`sys.path` は触らない | `test_insert_pythonpath_*` |
| `option "plugin_processing_mode"` | 拒否 | `test_plugin_processing_mode_is_rejected` |
| 読み込みキャッシュの pickle（`.main.beancount.picklecache`。R2 §6） | loader を使わないので **読まない・書かない・消さない** | `test_pickle_cache_is_never_read_or_touched`（陽性対照つき） |
| `.beancount` 以外の include（`.txt` の中身がエラーに出る、`.gpg`／`.asc` で gpg が起動する。R2 §5・BCP H2-4） | include の文字列を glob の前に形で検査：相対・ASCII の英数字と `_` `-`・`/` 区切り・拡張子 `.beancount`。`..`・絶対パス・ワイルドカード・装置名（`NUL` `CON` `COM1` …）・`:`（代替データストリーム）を拒否（`include_form`）。暗号化の処理は呼ばない | `test_include_glob_and_other_extensions_are_rejected`、`test_include_outside_root_is_rejected_before_reading`、`test_windows_device_names_and_alternate_streams_are_rejected` |
| glob が root の外のディレクトリを歩く（BCP A3） | glob を使わない | 同上 |
| シンボリックリンク・ジャンクション（BCP A7） | 実体のパス（realpath）が見かけのパスと違えば拒否（`link`）。`lstat` の `S_ISLNK` も見る | `test_junction_to_outside_is_rejected`、`test_file_symlink_is_rejected`（**この PC では権限が無くスキップ**）、`test_symlink_detection_logic_with_simulated_realpath` |
| ハードリンク | リンク数が 1 でないファイルを拒否（`hard_link`） | `test_hard_link_is_rejected` |
| 通常でないファイル（ディレクトリ・装置） | `S_ISREG` でないものを拒否 | `test_directory_as_ledger_is_rejected` |
| include の循環・重複（BCP A4） | 同じファイル（normcase で比べる）の2回目を拒否（`include_duplicate`） | `test_include_cycle_is_rejected` |
| 1行が長い（行の長さの2乗の時間。BCP A6） | parse の前に 1行 64 KiB を超えるものを拒否（`line_too_long`） | `test_long_line_is_rejected_without_parsing` |
| 改行を含む長い文字列の字句（§3.3） | parse の前に、文字列の字句になりうる範囲が 64 KiB を超えるものを拒否（`string_too_long`） | `test_long_multiline_string_is_rejected_without_parsing`、`test_longest_string_span` |
| 文字コードの細工（BOM・NUL・UTF-16・不正な UTF-8・CR だけの改行・制御文字。BCP A5） | parse の前に拒否（`bom`・`nul`・`not_utf8`・`bare_cr`・`control_char`）。CRLF は受け入れる | `test_encoding_tricks_are_rejected_before_parse`、`test_utf16_is_rejected` |
| C1 制御文字（U+0085 NEL など）・U+2028・U+2029（beancount では改行にならないが、エディタによっては改行に見え、コメントの後ろに取引や plugin 行を「見えるのに無い」形で隠せる）、双方向の書式制御文字（U+202E など。表示の順が変わる） | parse の前に拒否（`control_char`・`bidi_control`）。レビューで足した | `test_c1_controls_and_line_separators_are_rejected`（陽性対照つき）、`test_bidi_controls_are_rejected` |
| 大きすぎるファイル・多すぎるファイル（BCP A6） | 1ファイル 20 MiB、合計 100 MiB、500 ファイル（読む前に stat） | `test_size_and_count_limits` |
| `option "documents"`・root の外を指す `document`（BCP A8） | 拒否（`option_documents`・`document_outside_root`）。証憑のパスの装置名・`:` も拒否（`document_path`） | `DocumentTests` |
| 走査と読み込みの間の書き換え（BCP A10） | ファイルを1回だけ読み、同じバイト列を parse するので隙が無い。開いた後に `fstat` の (st_dev, st_ino) が確かめたものと同じかも見る | （設計で除いた。試験なし） |
| beancount のエラー（メタデータの1行の誤りで取引が黙って消える。BCP B1） | 1件でもあれば失敗（`beancount_error`） | `test_metadata_key_error_drops_transaction_so_it_fails` |
| `-I` なしの起動で台帳のディレクトリの `.py` が先に読まれる（BCP A9） | CLI は `sys.flags.isolated` でなければ終了コード 2 で止まる | `tests/test_cli.py` の `test_requires_isolated_mode` |

独立したレビューで足した攻撃（`tests/test_safe_loader.py` の `Review*Tests`）：3段の include の連鎖の先の plugin 行、40段の include（上限を超えた先は読まない）、
大小文字違いの同じファイル・自分自身の include（`include_duplicate`）、拡張子と名前の偽装（大小文字・末尾の `.` と空白・ゼロ幅の空白・キリル文字・全角・NFD・
右から左への上書き・`./`・`//`・8.3 の短い名前）、include 先の BOM、include 先の CRLF、深い入れ子の式（括弧・単項のマイナス 2 万段。beancount の構文解析が
MemoryError を出し `internal_error` になる。プロセスは落ちない）、Windows のパスの形（`\\?\`・UNC・`\\?\UNC\`・`\\.\NUL`・ドライブの相対パス `C:x`・`/x`・`\x`）を
include と document に書いたもの（UNC のホストのパスにはファイルシステムの関数が一度も触れないことを記録して確かめる）、上付きの数字の装置名
（`COM¹` など）の証憑、root の中どうしのジャンクション・root の親を指すジャンクション（ループ）、main・root を `\\?\` つきで渡すこと
（以前は片方だけに `\\?\` があると root の外と誤って判定した。`_plain` で揃える）、root そのものがジャンクション（許す）。

印のファイルによる確かめ方：どの試験も新しい一時ディレクトリに台帳を作り、実行されると一時ディレクトリに印のファイルを1つ書くだけのコードを仕込む。
拒否の試験では印のファイルが無いことを、陽性対照では同じ台帳を beancount の loader（キャッシュなしの `_load`）で読むと印のファイルができることを確かめる。

### 3.2 拒否できない・確かめていないこと

- **ファイルのシンボリックリンクは実物で確かめていない**（この PC では作る権限が無い。`OSError 1314`）。判定の処理は realpath を差し替えた試験でだけ確かめた。開発者モードか管理者で `test_file_symlink_is_rejected` を動かす必要がある。
- `-I` なしで起動されたときは守れない部分がある：CLI の確認（`sys.flags.isolated`）より前に読み込まれるモジュール（`okura_records/__init__.py`・`cli.py` と、それらが読む標準ライブラリ）は、カレントディレクトリの同名の `.py` に差し替えられうる。確認の後に読む beancount は守れる。ライブラリとして import するときの確認は呼び出し側の責任。
- 走査の判定と beancount の字句解析の食い違いの網羅的な探索（BCP I5 の検証方法2：1万通りの書き換え）はしていない。
- 上限（1行・文字列 64 KiB、1ファイル 20 MiB、証憑 256 MiB）は仮の値。実際の台帳の最長の行は測っていない（I5 の検証方法3）。
- ハードリンクの判定はリンク数だけ（root の中どうしのハードリンクも拒否する）。
- 大きい台帳の時間（レビューのときの非公式な測定。docs/measurements には記録していない）：短い取引を並べた台帳は長さにほぼ比例し、
  0.5 MB 1.5 秒・1 MB 4.0 秒・2 MB 8.6 秒だった。1ファイル 20 MiB の上限では1分を超えうる。include のファイルが多いときは、
  ファイルを開いて読む時間（この PC ではウイルス対策の検査とみられる、1ファイル約 10〜20 ms）が大半だった。
- UNC のパス（`\\server\share`）を root や `--ledger` に渡すことは試していない（利用者が渡す引数。ネットワークに出ないため）。

### 3.3 実装のときに確かめたこと（docs/measurements には記録していない）

改行を含む文字列の字句（短い行を並べた1つの文字列）でも、`parse_file` の時間が長さの2乗で増えた：0.5 MB 0.31 秒、1 MB 1.0 秒、2 MB 4.1 秒
（同じ長さの1行のコメントは 0.26・1.0・4.1 秒）。字句解析の規則（`lexer.l` の文字列の規則が改行を含みうる）と合う。1行の上限だけでは止まらないので
`string_too_long` を足した。正式な実測の文書（スクリプトつき）にするのは TODO。

## 4. 台帳の書き方

### 4.1 beancount の取引（メタデータの語彙）

語彙の元は okura_ir の語彙の表。取引から作れる事実は VOC §1.3 の取引（`F-T` の20種類：`salary_payment`・`medical_payment`・`remittance` など）だけ。
人・関係・住所・保険・書類・資産・業務（`business`）は事実台帳に書く（種類ごとの書く場所と必須の欄は §4.3）。キーと値の書き方の全体は `src/okura_records/meta_vocabulary.py` の先頭。
語彙の全種類の例は `examples/vocabulary/main.beancount`。

給与の支払（`salary_payment`）には支給日 `due_on` を必ず書く（D23 K3。年分は支給日で決まる。`due_stipulated: FALSE` で定めがないことを示す）。通勤の状況（`commuting_status`）は事実台帳、合理的な運賃は判断台帳に書く。

```beancount
2026-02-10 * "架空総合病院" "入院費"
  id: "tx-2026-0210-hospital"          ; 必須。事実の ID にもなる
  fact_kind: "medical_payment"         ; 無い取引はただの記帳（事実にしない）
  payer: "p-a"                         ; 役割 → 人の ID
  patient: "p-g"
  incurred_on: 2026-01-28              ; 日付
  medical_kinds: "medical_treatment hospitalization"   ; 並びは空白区切り
  Expenses:Medical   120,000 JPY
    fact_amount: "amount"              ; この posting の金額（絶対値）を amounts.amount に入れる
  Liabilities:Card:A

2026-02-10 document Expenses:Medical "receipts/2026-02-10-hospital.pdf"
  transaction_id: "tx-2026-0210-hospital"   ; 証憑の SHA-256 が事実の source に入る
```

- 1取引＝1件の事実（明細の粒度。D5 改）。1つの支払で2人分なら取引を分ける。
- 金額は JPY の整数だけ（`1000.00 JPY` も拒否）。取得価額・価格つきの posting、`pad`・`price`・`query`・`custom` は扱わない。
- `fact_amount` は費用（expenses）の勘定の負の金額・収益（income）の勘定の正の金額（返金・取消し）には付けられない。
- 金額でない円の欄（`return_gift_value`、`daily_amount` など）はメタデータに `5000 JPY` と書く。posting と両方から同じ欄を入れると拒否（合計しない）。
  回収できない未払の給与 `uncollectible_amount` なども同じ（例：`examples/household` の `tx-2026-0925-salary-a-unpaid`）。
- 日付の並び（`social_insurance_payment`・`insurance_payment` の `prepaid_due_dates`：前納した保険料の納付期日・払込期日の全部）は、
  ID・列挙の並びと同じく **空白で区切った文字列** で書く（beancount のメタデータは配列を持てないため）。各日付は `YYYY-MM-DD` で実在する日付だけ
  （`2026/11/30`・`20261130`・`,` 区切り・全角の数字・空の文字列は `fact_value_type`）。build_ir は書いた順のまま日付の配列にし、並べ替え・重複の除去・数えることはしない
  （その年中に到来する回数を数えるのは判定コア）。

  ```beancount
  2026-10-30 * "国民年金保険料の前納（子の分）"
    id: "tx-2026-1030-npi-prepay"
    fact_kind: "social_insurance_payment"
    payer: "p-a"
    liable_person: "p-c"
    premium_type: "national_pension"
    prepaid_period: "2026-10-01/2027-03-31"
    prepaid_due_dates: "2026-11-30 2026-12-31 2027-01-31 2027-02-28 2027-03-31 2027-04-30"
    Expenses:SocialInsurance     104000 JPY
      fact_amount: "amount"
    Assets:Bank:A
  ```
- payee・narration・勘定科目名・`memo`・`x_*` のキーは中間表現に写さない（人の名前を含みうるため）。中間表現に説明を残すなら `note`。
- フラグ `!` の取引は正規化はするが事実にしない（`fact_flag_pending`）。

### 4.2 事実台帳・判断台帳（追記のみの JSON Lines）

1行1件、UTF-8（BOM なし）、改行は LF だけ、最後の行も LF で終える。形は `src/okura_records/jsonl_ledger.py` の先頭。

```json
{"entry_id":"fe-0012","ledger":"okura-facts/0","op":"correct","prev_sha256":"…","reason":"生年月日の打ち間違い","record":{"birth_on":"2005-06-15","id":"p-c"},"recorded_at":"2026-01-06T08:00:00+09:00","recorded_by":{"person":"p-a"},"replaces":"fe-0003","section":"persons"}
```

- `section`：事実台帳は `persons`・`relations`・`residences`・`insurance_memberships`・`facts`・`assets`・`filed_documents`、判断台帳は `judgments`・`choices`
  （kind ごとの section は §4.3。違えば `record_section_mismatch`）。
  `record` は中間表現のその配列の1件をそのまま書く（`recorded_at` は書かない。行の `recorded_at` を build_ir が写す）。
- `op`：`add`・`correct`（`replaces` の行の記録を差し替える）・`delete`（取り消す）。`correct`・`delete` には `reason` が必須。
- 現在の状態：置き換えの連鎖の先頭だけを残し、`delete` で終わる連鎖を除く。並びは連鎖の最初の行の順。
- 判断台帳の2つの置き換え：行の `replaces` は **記録の誤りの訂正**、record の `replaces` は **判断の見直し**（古い判断も中間表現に残し、判定コアが連鎖の先頭を使う。okura_ir README §3.2）。
- 検査：記録日時が前の行より前、entry_id の重複、置き換える行が前に無い・section が違う・取り消しの行を置き換える・分岐、
  現在の状態で record.id が重複、判断・選択の日時が記録日時より後。

**改ざんの検出（ハッシュの連鎖）**：各行の `prev_sha256` は前の行のバイト列（LF を除く）の SHA-256、最初の行は null。
前の行の書き換え・削除・並べ替えは `chain_broken` になる。**末尾の行を消すこと（台帳の切り詰め）は見つけられない**（残った行の連鎖は正しいまま。
取り消しの行を末尾から消すと、取り消した記録が現在の状態に戻る。`test_tail_truncation_is_not_detected_by_the_chain`）。
見つけるには最後の行の SHA-256 を台帳の外に控える必要がある（版 0 には無い）。本人がすべての行を作り直すことも防げない（運用の記録・事故の検知の道具。
`docs/hypotheses/20261109_impl-prep_denchoho-record-layer.md` H3 の5と同じ位置づけ）。

**手で書いて足す**：`prev_sha256` は手では計算できないので、下書き（行のオブジェクトから `prev_sha256` を除いたもの。`ledger` も省いてよい）を
JSON のファイル（1件のオブジェクトか、その配列。複数行で書いてよい）に書き、`append` コマンド（§7）で足す。コマンドは `prev_sha256` を入れ、
足した後の台帳全体を検査してから末尾に書く（`jsonl_ledger.append_drafts`。プログラムからは `facts_ledger.append_drafts`・`judgments_ledger.append_drafts`）。

```json
[
 {"entry_id": "fe-0101", "recorded_at": "2027-03-01T20:00:00+09:00", "recorded_by": {"person": "p-a"}, "op": "add",
  "section": "facts", "record": {"id": "cl-g", "kind": "care_level", "roles": {"person": "p-g"},
  "when": {"from_on": "2026-04-01"}, "attributes": {"level": "care_3"}}}
]
```

`record` の書き方（中間表現の1件。okura_ir README §3.1・§3.2）：

| section | record の形 |
|---|---|
| `persons` | `{"id", "birth_on", "death_on"（任意）}`。氏名・個人番号は書かない |
| `relations`〜`filed_documents` | `{"id", "kind", "roles": {役割: 人の id}, "when", "amounts": {欄: 整数の円}, "attributes": {欄: 値}, "mark"（任意）, "source"（任意）, "note"（任意）}`。`amounts`・`attributes` は欄が無ければ省く |
| `judgments` | `{"id", "kind", "judged_by": {"person": id} か {"label": 名前}, "judged_at": 日時, "subject": {…}, "when"（種類による）, "value", "basis"（任意）, "replaces"（任意。判断の見直し）, "mark"（見込み.*・見積り.*・計画.* は必須）}` |
| `choices` | `{"id", "kind", "chosen_by": 人の id, "chosen_at": 日時, "subject": {…}, "when"（種類による）, "value", "basis"（任意）, "replaces"（任意）}` |

値の書き方（JSON）：日付 `"2026-02-10"`、日時 `"2026-02-10T09:00:00+09:00"`（秒まで・時差つき）、円 `120000`（整数）、真偽 `true`、
割合・率・分数 `{"num": 3, "den": 10}`、区間 `{"from_on": "2026-04-01", "to_on": "2027-03-31"}`（続いていれば `to_on` を書かない）、
when は `{"on": 日付}`・区間・`{"tax_year": 2026}`・`{"fiscal_year": 2026}` のどれか（種類ごとに §4.3 の表）。
`record` に `recorded_at` は書かない（行の `recorded_at` を build_ir が写す）。現在の状態で kind を違う section に書いていると `record_section_mismatch`（書いて取り消した行は問題にしない）。

### 4.3 種類ごとの書く場所と必須の欄

書く場所は語彙の表（`okura_ir.vocabulary`）から機械的に決める（`src/okura_records/ledger_map.py`）：

| 種類 | 書く場所 | 理由 |
|---|---|---|
| 取引（VOC の ID が F-T：`facts` のうち20種類） | **台帳の取引のメタデータ**（`fact_kind`）。家計の台帳に記帳していない入出金（家族の別の人の口座、台帳を付け始める前の分など）は **事実台帳の facts にも書ける** | 金額が記帳と一致し、取引 ID と証憑の SHA-256 が source に付く。同じ取引を両方に書くと `fact_written_twice`（事実台帳の記録の `source.transaction_ids` が、事実にした台帳の取引を指すとき） |
| 人と、取引でない記録（`relations`・`residences`・`insurance_memberships`・`facts` の残り・`assets`・`filed_documents`） | **事実台帳** | 入出金ではない（人の属性・関係・住所・加入・書類・資産・提出した書類）。台帳に `fact_kind` で書くと `fact_kind_unknown` |
| 判断・予測・見積り・計画（`judgments`）と選択（`choices`） | **判断台帳** | 人の判断と納税者の選択は事実と分け、判断者・日時つきで追記のみ（D4・D12） |

下の表は生成したもの（語彙の表が変わったら `python -I -X utf8 -m okura_records.ledger_map --write packages/records/README.md`。
`tests/test_vocabulary_examples.py` が一致を確かめる）。任意の欄の型は `packages/ir/src/okura_ir/vocabulary.py` を見る。
どの種類にも例が `examples/vocabulary/`（§6）に1つ以上ある（kind の名前で検索する）。

<!-- BEGIN ledger_guide（python -I -X utf8 -m okura_records.ledger_map --write README.md で作る。手で直さない） -->

種類の数：台帳の取引 20、事実台帳 73（ほかに persons）、判断台帳 75（judgments 53・choices 22）、合計 168。
型の語：人＝persons の id、`<kind>のID`＝その種類の記録の id、円＝整数の円、割合・率・分数＝`{"num": 整数, "den": 整数}`、区間＝`{"from_on": 日付, "to_on": 日付}`（`to_on` は任意）、並び＝配列。

#### 台帳の取引（beancount のメタデータ。値の書き方は §4.1）

| 配列 | kind | VOC | 書く場所 | when | 必須の欄 | 任意の欄 |
|---|---|---|---|---|---|---|
| facts | `salary_payment` | F-T01 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.recipient: 人<br>amounts.gross: 円<br>attributes.counterparty: 名称<br>attributes.due_on: 日付 | roles.payer・amounts.withholding_tax・amounts.social_insurance_withheld・amounts.basic_pay・amounts.overtime_pay・amounts.commuting_allowance・amounts.commuting_pass_value・amounts.commuting_nontaxable_stated・amounts.bonus・amounts.prior_month_net_salary・amounts.uncollectible_amount・attributes.payment_type・attributes.due_stipulated・attributes.original_due_on・attributes.unpaid・attributes.commuting_itemized・attributes.commuting_months・attributes.resolution_on・attributes.amount_fixed_on・attributes.payer_withholding_exempt_household・attributes.paid_outside_japan・attributes.payer_family_company_officer・attributes.interest_or_rent_from_payer・attributes.payer_business_id・attributes.paid_by_foreign_mission・attributes.pay_period・attributes.pay_period_months・attributes.pay_period_days・attributes.uncollectible_on |
| facts | `business_receipt` | F-T02 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.recipient: 人<br>amounts.amount: 円<br>attributes.business_id: businessのID | amounts.withholding_tax・attributes.counterparty・attributes.contract_document・attributes.incurred_on |
| facts | `business_expense` | F-T03 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.payer: 人<br>amounts.amount: 円<br>attributes.expense_category: 列挙（`merchandise`・`materials`・`outsourcing`・`tax`・`membership_dues`・`shipping`・`utilities`・`travel`・`communication`・`advertising`・`entertainment`・`insurance`・`repairs`・`supplies`・`welfare`・`rent`・`loan_interest`・`interest`・`fees`・`management`・`other`・`dividend_debt_interest`） | roles.payee・amounts.consumption_tax・attributes.business_id・attributes.counterparty・attributes.counterparty_invoice_registered・attributes.incurred_on・attributes.rent_flow_id・attributes.receipt_id・attributes.property_id・attributes.loan_id |
| facts | `payroll_paid` | F-T04 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.employer: 人<br>amounts.amount: 円<br>attributes.pay_type: 列挙（`wages`・`family_employee_salary`・`professional_fee`） | roles.recipient・amounts.withholding_tax・attributes.business_id・attributes.counterparty・attributes.receipt_id |
| facts | `medical_payment` | F-T05 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.payer: 人<br>roles.patient: 人<br>amounts.amount: 円<br>attributes.incurred_on: 日付<br>attributes.medical_kinds: 列挙（`medical_treatment`・`health_checkup`・`specific_health_guidance`・`medicine`・`hospitalization`・`care_service`・`manual_therapy`・`nursing_care`・`midwifery`・`suction_care`・`transport`・`medical_device`・`diaper`・`certified_other`・`transplant_mediation`・`welfare_levy`・`deposit`）の並び | attributes.provider・attributes.selfmed_label・attributes.product_name・attributes.deposit_applied_on・attributes.payment_instrument・attributes.notice_id |
| facts | `reimbursement` | F-T06 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.recipient: 人<br>amounts.amount: 円<br>attributes.benefit_type: 列挙（`hospitalization_benefit`・`high_cost_medical_care_benefit`・`childbirth_lump_sum`・`mutual_aid_benefit`・`sickness_allowance`・`maternity_allowance`・`sympathy_payment`・`other`） | attributes.target_payment_ids・attributes.payer_name |
| facts | `social_insurance_payment` | F-T07 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.payer: 人<br>roles.liable_person: 人<br>amounts.amount: 円<br>attributes.premium_type: 列挙（`national_health_insurance`・`national_pension`・`health_insurance`・`employees_pension`・`long_term_care_insurance`・`late_stage_elderly_medical`・`employment_insurance`・`national_pension_fund`・`other`） | attributes.prepaid_period・attributes.prepaid_due_dates・attributes.payroll_deduction |
| facts | `mutual_aid_payment` | F-T08 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.payer: 人<br>roles.member: 人<br>amounts.amount: 円<br>attributes.contribution_type: 列挙（`small_business_mutual_aid`・`individual_defined_contribution`・`corporate_defined_contribution_member`・`disability_mutual_aid`） | attributes.payroll_deduction |
| facts | `insurance_payment` | F-T09 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.payer: 人<br>amounts.amount: 円<br>attributes.contract_id: insurance_contractのID<br>attributes.flow: 列挙（`premium`・`dividend`・`rebate`） | attributes.prepaid・attributes.prepaid_due_dates・attributes.automatic_premium_loan・attributes.applied_to_premium |
| facts | `donation` | F-T10 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.donor: 人<br>amounts.amount: 円<br>attributes.recipient_name: 名称 | amounts.return_gift_value・attributes.recipient_type・attributes.receipt_issued・attributes.return_gift・attributes.admission_related_facts・attributes.candidate_to_specified_party_branch・attributes.receipt_statement・attributes.recipient_local_government_code・attributes.recipient_local_government_kind・attributes.recipient_office_prefecture_code・attributes.mic_approved_solicitation・attributes.onestop_request_municipality_code |
| facts | `casualty` | F-T11 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.owner: 人<br>attributes.cause: 列挙（`earthquake`・`fire`・`storm_or_flood`・`other_natural_disaster`・`theft`・`embezzlement`・`other`） | amounts.insurance_recovery・amounts.pre_loss_value・amounts.post_loss_value・amounts.acquisition_cost・amounts.salvage_value・attributes.asset_description・attributes.asset_id・attributes.business_use・attributes.asset_acquired_on・attributes.disaster_ended_on |
| facts | `casualty_expenditure` | F-T11 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.payer: 人<br>amounts.amount: 円<br>attributes.casualty_id: casualtyのID<br>attributes.expenditure_type: 列挙（`removal`・`restoration`・`prevention`・`other`） | — |
| facts | `pension_payment` | F-T12 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.recipient: 人<br>amounts.gross: 円<br>attributes.scheme: 列挙（`national_pension`・`employees_pension`・`mutual_aid_pension`・`corporate_pension`・`foreign_pension`・`private_annuity`・`other`）<br>attributes.benefit_reason: 列挙（`old_age`・`disability`・`survivor`・`other`） | amounts.social_insurance_withheld・amounts.withholding_tax・attributes.counterparty・attributes.payer_domestic・attributes.benefit_name・attributes.statutory_payment_on・attributes.covered_period |
| facts | `retirement_payment` | F-T13 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.recipient: 人<br>amounts.gross: 円 | amounts.withholding_tax・amounts.employee_contributions・amounts.non_officer_portion・attributes.counterparty・attributes.retired_on・attributes.resolution_on・attributes.benefit_event_on・attributes.payment_category・attributes.old_age_dc_lump_sum |
| facts | `dividend` | F-T14 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.recipient: 人<br>amounts.gross: 円<br>attributes.security_class: 列挙（`listed_stock`・`listed_investment_trust`・`public_bond`・`unlisted_stock`・`other`）<br>attributes.account_type: 列挙（`withholding_specified_account`・`other_account`・`nisa`） | amounts.withholding_tax・amounts.dividend_local_tax・attributes.counterparty・attributes.record_date・attributes.calculation_period・attributes.distribution_type |
| facts | `security_sale` | F-T15 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.seller: 人<br>amounts.proceeds: 円<br>attributes.security_class: 列挙（`listed_stock`・`listed_investment_trust`・`public_bond`・`unlisted_stock`・`other`） | amounts.acquisition_cost・amounts.selling_expenses・attributes.security_name・attributes.sale_method・attributes.account_type |
| facts | `remittance` | F-T16 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.sender: 人<br>roles.recipient: 人<br>amounts.amount: 円<br>attributes.method: 列挙（`bank_transfer`・`card`・`electronic_payment`・`cash`・`in_kind`） | amounts.fee・attributes.used_on・attributes.transferred_on・attributes.foreign_amount・attributes.exchange_rate・attributes.purpose・attributes.beneficiaries |
| facts | `windfall_receipt` | F-T17 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.recipient: 人<br>amounts.amount: 円<br>attributes.reason: 列挙（`prize`・`insurance_maturity`・`gift`・`other`） | attributes.counterparty・attributes.donor_type・attributes.business_related・attributes.direct_expense_ids |
| facts | `benefit_receipt` | F-T18 | 台帳の取引（事実台帳にも書ける） | 取引の日付（区間はメタデータ period） | roles.recipient: 人<br>amounts.amount: 円<br>attributes.benefit_type: 列挙（`unemployment_benefit`・`sickness_allowance`・`maternity_allowance`・`scholarship_grant`・`scholarship_loan`・`unpaid_pension_of_deceased`・`workers_accident_compensation`・`other`） | amounts.daily_amount・attributes.benefit_start_on・attributes.unpaid_pension_reason |
| facts | `rent_flow` | F-T19 | 台帳の取引（事実台帳にも書ける） | 取引の日付 | roles.recipient: 人<br>amounts.amount: 円<br>attributes.flow_type: 列挙（`rent`・`common_service_fee`・`deposit_received`・`deposit_returned`・`key_money`・`renewal_fee`・`other`） | roles.payer・attributes.lease_id・attributes.property_id・attributes.counterparty・attributes.covered_period |

#### 事実台帳（`record` に中間表現の1件を書く。§4.2）

| 配列 | kind | VOC | 書く場所 | when | 必須の欄 | 任意の欄 |
|---|---|---|---|---|---|---|
| persons | （種類なし） | F-P01〜F-P03 | 事実台帳 | なし | id: ID<br>birth_on: 日付 | death_on |
| relations | `parentage` | F-R01 | 事実台帳 | 日付 | roles.parent: 人<br>roles.child: 人<br>attributes.basis: 列挙（`birth_mother`・`birth_in_marriage`・`acknowledgment`） | — |
| relations | `adoption` | F-R02 | 事実台帳 | 区間 | roles.adoptive_parent: 人<br>roles.adoptee: 人 | — |
| relations | `marriage` | F-R03 | 事実台帳 | 区間 | roles.spouse_a: 人<br>roles.spouse_b: 人 | attributes.ended_by・attributes.affinity_termination_on・attributes.spouse_missing |
| relations | `foster_placement` | F-R04 | 事実台帳 | 区間 | roles.caregiver: 人<br>roles.placed_person: 人<br>attributes.placement: 列挙（`foster_child`・`elderly_entrustment`） | attributes.foster_parent_type |
| relations | `cohabitation` | F-R05 | 事実台帳 | 区間 | roles.person: 人<br>roles.other_person: 人 | — |
| relations | `separation_reason` | F-R06 | 事実台帳 | 区間 | roles.person: 人<br>roles.other_person: 人<br>attributes.reason: 列挙（`member_transfer`・`work_related`・`hospitalization_or_facility`・`study`・`employment_or_independence`・`other`） | — |
| relations | `heirship` | F-R07 | 事実台帳 | 日付 | roles.decedent: 人<br>roles.heir: 人<br>attributes.heir_type: 列挙（`heir`・`universal_legatee`） | attributes.share・attributes.share_basis・attributes.qualified_acceptance・attributes.renounced・attributes.heir_departure_on |
| residences | `resident_record` | F-P06 | 事実台帳 | 区間 | roles.person: 人<br>attributes.municipality_code: 団体コード<br>attributes.household_id: ID<br>attributes.householder: 真偽 | attributes.relation_to_householder |
| residences | `municipal_tax_domicile` | F-P16 | 事実台帳 | 年度 | roles.person: 人<br>attributes.municipality_code: 団体コード<br>attributes.basis: 列挙（`resident_record`・`decided_different_from_resident_record`・`house_or_office`） | — |
| insurance_memberships | `medical_insurance` | F-P12 | 事実台帳 | 区間 | roles.member: 人<br>attributes.scheme: 列挙（`kyokai_kenpo`・`health_insurance_society`・`seamen_insurance`・`national_public_servants_mutual_aid`・`local_public_servants_mutual_aid`・`private_school_mutual_aid`・`national_health_insurance`・`late_stage_elderly_medical`）<br>attributes.insurer_id: ID<br>attributes.capacity: 列挙（`insured`・`dependent`） | roles.insured・amounts.standard_monthly_remuneration・attributes.branch_id・attributes.nhi_association |
| insurance_memberships | `national_pension` | F-P13 | 事実台帳 | 区間 | roles.member: 人<br>attributes.category: 列挙（`first`・`second`・`third`） | — |
| insurance_memberships | `employees_pension` | F-P13 | 事実台帳 | 区間 | roles.member: 人 | — |
| insurance_memberships | `national_pension_fund` | 補 | 事実台帳 | 区間 | roles.member: 人 | attributes.fund_id |
| insurance_memberships | `pension_entitlement` | F-P13 | 事実台帳 | 区間 | roles.member: 人<br>attributes.benefit: 列挙（`old_age`・`disability`・`survivor`） | attributes.scheme・attributes.disability_state_ended_on・attributes.disability_grade・attributes.mutual_aid_disability_kind |
| facts | `abroad_stay` | F-P04 | 事実台帳 | 区間 | roles.person: 人<br>attributes.country: 国の符号<br>attributes.purpose: 列挙（`study`・`assignment`・`accompanying_assignment`・`work`・`permanent_residence`・`tourism`・`other`） | attributes.planned_end_on・attributes.residence_status |
| facts | `civil_status` | F-P05 | 事実台帳 | 区間 | roles.person: 人 | attributes.japanese_national・attributes.permanent_residence_permit・attributes.domestic_occupation・attributes.domestic_assets・attributes.public_servant・attributes.designated_activity |
| facts | `legal_sex` | 補 | 事実台帳 | 区間 | roles.person: 人<br>attributes.sex: 列挙（`female`・`male`） | — |
| facts | `childcare_leave` | 補 | 事実台帳 | 区間 | roles.person: 人<br>attributes.leave_type: 列挙（`childcare_leave`・`postnatal_paternity_leave`・`other`） | attributes.counterparty・attributes.child_ids |
| facts | `dwelling_stay` | F-P07 | 事実台帳 | 区間 | roles.person: 人<br>attributes.dwelling_id: ID | attributes.building_id・attributes.site_id |
| facts | `institution_stay` | F-P08 | 事実台帳 | 区間 | roles.person: 人<br>attributes.institution: 列挙（`hospital`・`care_facility`・`other_facility`） | attributes.facility_type・attributes.for_treatment |
| facts | `enrollment` | F-P09 | 事実台帳 | 区間 | roles.person: 人<br>attributes.school_type: 列挙（`school_act_article1`・`specialized_training_college`・`miscellaneous_school`・`accredited_vocational_training`・`other`） | attributes.course・attributes.attendance・attributes.course_division・attributes.establisher_type・attributes.course_certificate・attributes.establisher_certificate・attributes.enrollment_certificate・attributes.course_length_months・attributes.npi_student_school_listed |
| facts | `disability_basis` | F-P10 | 事実台帳 | 区間 | roles.person: 人<br>attributes.basis: 列挙（`physical_disability_certificate`・`mental_disability_certificate`・`war_injury_certificate`・`intellectual_disability_assessment`・`atomic_bomb_survivor_certification`・`municipal_certification`・`application`） | attributes.grade・attributes.assessment_label・attributes.war_injury_class・attributes.certified_severity・attributes.issuer・attributes.issued_on・attributes.valid_until・attributes.applied_on・attributes.medical_certificate |
| facts | `care_level` | F-P11 | 事実台帳 | 区間 | roles.person: 人<br>attributes.level: 列挙（`support_1`・`support_2`・`care_1`・`care_2`・`care_3`・`care_4`・`care_5`） | — |
| facts | `kokuho_event` | F-P14 | 事実台帳 | 日付か区間 | roles.person: 人<br>attributes.event: 列挙（`student_special_case`・`institution_special_case`・`specified_same_household_member`・`involuntary_unemployment`・`childbirth`） | attributes.separation_category・attributes.separated_on・attributes.expected_delivery_on・attributes.delivered_on・attributes.multiple_birth・attributes.deemed_household_id・attributes.admission_type |
| facts | `childbirth` | 補 | 事実台帳 | 日付 | roles.person: 人 | attributes.expected_delivery_on・attributes.delivered_on・attributes.multiple_birth・attributes.child_ids |
| facts | `special_adoption_petition` | 補 | 事実台帳 | 区間 | roles.petitioner: 人<br>roles.child: 人 | — |
| facts | `npi_application` | 補 | 事実台帳 | 区間 | roles.person: 人<br>attributes.application_type: 列挙（`additional_premium`・`statutory_exemption_payment`） | attributes.applied_on |
| facts | `income_certificate` | 補 | 事実台帳 | 日付 | roles.person: 人<br>amounts.total_income: 円（負も可）<br>attributes.fiscal_year: 年 | attributes.issuer |
| facts | `public_assistance` | F-P15 | 事実台帳 | 区間 | roles.person: 人<br>attributes.assistance: 列挙（`livelihood_assistance`） | — |
| facts | `ct_liability` | F-P17 | 事実台帳 | 区間 | roles.person: 人<br>attributes.status: 列挙（`exempt`・`not_exempt`） | attributes.reason |
| facts | `invoice_registration` | F-P18 | 事実台帳 | 区間 | roles.person: 人 | — |
| facts | `dependent_allowance` | F-P19 | 事実台帳 | 区間 | roles.recipient: 人<br>roles.subject_person: 人 | attributes.payer_name |
| facts | `business_engagement` | F-P20 | 事実台帳 | 区間 | roles.business_owner: 人<br>roles.relative: 人<br>attributes.business_id: businessのID | attributes.interruption_reason・attributes.available_period・attributes.work_share |
| facts | `business` | 補（F-T00・F-D11） | 事実台帳 | 区間 | roles.owner: 人 | attributes.description |
| facts | `commuting_status` | 補（tsukin HT3） | 事実台帳 | 区間 | roles.worker: 人<br>attributes.counterparty: 名称<br>attributes.means: 列挙（`transit`・`vehicle`・`transit_and_vehicle`） | attributes.one_way_km・attributes.parkings |
| facts | `specific_expense` | 補（kyuyo KY-11） | 事実台帳 | 日付 | roles.payer: 人<br>amounts.amount: 円<br>attributes.category: 列挙（`commuting_transit`・`commuting_vehicle`・`business_travel`・`relocation`・`training`・`qualification`・`home_leave`・`books`・`clothing`・`entertainment`）<br>attributes.certified_by: 列挙（`payer`・`career_consultant`・`none`） | amounts.reimbursed_nontaxable・amounts.training_benefit・amounts.special_seat_fee・amounts.commuter_pass_value・attributes.education_training・attributes.air_travel・attributes.sleeper_fees・attributes.transfer_on・attributes.relocation_item・attributes.attributed_year・attributes.payer_name・attributes.counterparty・attributes.description |
| facts | `medical_expense_notice` | 補 | 事実台帳 | 区間 | roles.payer: 人<br>roles.patient: 人<br>amounts.notice_amount: 円<br>amounts.paid_in_year: 円<br>attributes.payment_year: 年<br>attributes.issuer: 名称 | amounts.reimbursed |
| facts | `prior_income_fixed` | F-D03 | 事実台帳 | 年分 | roles.person: 人<br>amounts.revenue: 円<br>attributes.income_source: 列挙（`business`・`real_estate`・`miscellaneous_business`） | attributes.business_id・attributes.fixed_by・attributes.fixed_on |
| facts | `withholding_slip` | F-D04 | 事実台帳 | 年分 | roles.recipient: 人<br>amounts.payment_amount: 円<br>attributes.slip_type: 列挙（`salary`・`retirement`・`public_pension`・`payment_record`） | amounts.withholding_tax・amounts.social_insurance・amounts.special_collection_tax・amounts.housing_loan_credit・attributes.counterparty・attributes.year_end_adjusted・attributes.secondary_column・attributes.listed_person_ids・attributes.includes_prior_payers・attributes.hired_on・attributes.retired_on・attributes.service_years |
| facts | `prepayment_notice` | F-D05 | 事実台帳 | 年分 | roles.taxpayer: 人<br>amounts.prepayment_total: 円 | amounts.first_installment・amounts.second_installment |
| facts | `labor_contract` | F-D06 | 事実台帳 | 区間 | roles.worker: 人 | amounts.hourly_wage・amounts.daily_wage・amounts.monthly_wage・amounts.monthly_allowances・amounts.monthly_commuting_allowance・amounts.bonus・attributes.counterparty・attributes.scheduled_minutes_per_week・attributes.scheduled_days_per_week・attributes.shift_based・attributes.labor_conditions_notice・attributes.salary_income_only_statement・attributes.commuting_allowance_stated・attributes.commuting_allowance_as_reimbursement・attributes.bonus_stated・attributes.fixed_term |
| facts | `employer_attestation` | F-D07 | 事実台帳 | 日付 | roles.person: 人<br>attributes.attestation_type: 列挙（`temporary_income_increase`・`income_tax_dependent_confirmation`） | attributes.covered_period・attributes.counterparty |
| facts | `insurer_decision` | F-D08 | 事実台帳 | 日付 | roles.dependent: 人<br>roles.insured: 人<br>attributes.decision: 列挙（`notification_filed`・`recognized`・`removed`・`rejected`） | attributes.effective_on・attributes.sent_on・attributes.insurer_id・attributes.reason・attributes.joint_support_agreement・attributes.recognized_under_higher_income_criterion |
| facts | `npi_exemption` | F-D09 | 事実台帳 | 区間 | roles.person: 人<br>attributes.exemption_type: 列挙（`full`・`three_quarters`・`half`・`one_quarter`・`payment_deferral`・`student_special`・`perinatal`）<br>attributes.status: 列挙（`applied`・`approved`・`rejected`） | attributes.applied_on・attributes.decided_on |
| facts | `foreign_kin_document` | F-D10 | 事実台帳 | 日付 | roles.subject_person: 人<br>roles.holder: 人<br>attributes.document_type: 列挙（`kinship_document`・`student_visa_document`・`remittance_document`・`remittance_document_special`） | attributes.issuer・attributes.translation_attached・attributes.presented_to・attributes.presented_on・attributes.presented_with |
| facts | `blue_return_procedure` | F-D11 | 事実台帳 | 日付 | roles.person: 人<br>attributes.procedure: 列挙（`application_filed`・`approval_notice`・`rejection_notice`・`revocation_notice`・`withdrawal_notice`・`business_transfer_or_closure`） | attributes.first_tax_year・attributes.business_start_on・attributes.succession_by_inheritance・attributes.decedent_blue_approved・attributes.revoked_from_tax_year・attributes.statutory_ground |
| facts | `bookkeeping_status` | F-D12 | 事実台帳 | 年分 | roles.person: 人<br>attributes.bookkeeping_method: 列挙（`double_entry`・`simplified`・`cash_basis_simplified`） | attributes.business_id・attributes.inventory_list・attributes.balance_sheet・attributes.electronic_books_notice・attributes.cash_basis_notice・attributes.misc_cash_basis_entry・attributes.depreciation_method_notice・attributes.electronic_books_qualified |
| facts | `family_employee_notice` | F-D13 | 事実台帳 | 日付 | roles.employer: 人<br>roles.employee: 人<br>attributes.notice_type: 列挙（`initial`・`change`） | amounts.monthly_salary・attributes.duties・attributes.pay_schedule・attributes.bonus_criteria・attributes.started_on |
| facts | `health_checkup_record` | F-D14 | 事実台帳 | 日付 | roles.person: 人<br>attributes.activity: 列挙（`specific_health_checkup`・`vaccination`・`periodic_health_checkup`・`health_examination`・`cancer_screening`・`other`） | attributes.provider・attributes.certificate_available |
| facts | `retirement_record` | F-D16 | 事実台帳 | 区間 | roles.recipient: 人<br>attributes.declaration_submitted: 真偽 | attributes.counterparty・attributes.officer_period・attributes.interruption_note・attributes.prior_service_note・attributes.service_adjustments |
| facts | `brokerage_annual` | F-D17 | 事実台帳 | 年分 | roles.holder: 人<br>attributes.account_id: ID<br>attributes.withholding_elected: 真偽 | amounts.proceeds・amounts.acquisition_cost・amounts.net_gain_loss・amounts.dividends_received・amounts.withholding_tax・amounts.net_after_offset・amounts.dividend_local_tax・amounts.transfer_local_tax・amounts.transfer_withholding_tax・amounts.dividend_withholding_tax・attributes.counterparty |
| facts | `housing_loan_credit` | F-D18 | 事実台帳 | 年分 | roles.person: 人<br>amounts.credit_amount: 円 | attributes.moved_in_on・attributes.source_note・attributes.acquisition_category・attributes.special_acts |
| facts | `external_tax_credit` | 補 | 事実台帳 | 年分 | roles.person: 人<br>amounts.credit_amount: 円<br>attributes.credit_type: 列挙（`business_income_special`・`seismic_retrofit`・`specified_housing_renovation`・`certified_housing_new_build`） | attributes.source_note |
| facts | `special_depreciation` | 補 | 事実台帳 | 年分 | roles.owner: 人<br>amounts.amount: 円<br>attributes.asset_id: depreciable_assetのID<br>attributes.article: 文字列<br>attributes.method: 列挙（`special`・`extra`） | attributes.shortfall_carryover・attributes.source_note |
| facts | `ct_return` | F-D18 | 事実台帳 | 区間 | roles.person: 人<br>amounts.consumption_tax: 円（負も可）<br>attributes.return_type: 列挙（`final`・`amended`・`correction_decision`・`assessment`）<br>attributes.filed_or_decided_on: 日付 | amounts.local_consumption_tax・amounts.additional_tax・attributes.business_breakdown |
| facts | `authority_decision` | F-D19 | 事実台帳 | 年度 | roles.person: 人<br>attributes.decision: 列挙（`reduction_approved`・`kokuho_student_special_case_recognized`・`taxation_at_non_resident_record_municipality`）<br>attributes.authority: 列挙（`municipality`・`insurer`）<br>attributes.tax_item: 列挙（`resident_tax`・`national_health_insurance`） | attributes.municipality_code・attributes.insurer_id |
| facts | `jan1_payer_status` | F-D20 | 事実台帳 | 年度 | roles.person: 人<br>attributes.salary_payer_on_jan1: 真偽<br>attributes.pension_payer_on_jan1: 真偽 | amounts.prior_year_salary_from_former_payers・attributes.payer_must_file_report |
| facts | `tax_agent_notice` | F-D21 | 事実台帳 | 日付 | roles.taxpayer: 人<br>attributes.action: 列挙（`appointment`・`dismissal`） | attributes.agent_name |
| facts | `estate_liquidator` | 補（tax TX-13） | 事実台帳 | 日付 | roles.decedent: 人 | attributes.liquidator_name |
| facts | `inventory_count` | 補（income_kinds IK-108） | 事実台帳 | 日付 | roles.owner: 人<br>amounts.valuation: 円<br>attributes.business_id: businessのID<br>attributes.valuation_method: 列挙（`specific_identification`・`fifo`・`total_average`・`moving_average`・`final_purchase_cost`・`retail`・`special_approved`） | attributes.lower_of_cost・attributes.asset_class・attributes.count_type |
| facts | `inventory_method_notice` | 補（income_kinds IK-108） | 事実台帳 | 日付 | roles.person: 人<br>attributes.business_id: businessのID<br>attributes.procedure: 列挙（`selection_notice`・`change_application`・`change_approved`・`change_rejected`・`special_method_approved`）<br>attributes.method: 列挙（`specific_identification`・`fifo`・`total_average`・`moving_average`・`final_purchase_cost`・`retail`・`special_approved`） | attributes.lower_of_cost・attributes.asset_class |
| facts | `household_consumption` | 補（income_kinds IK-109） | 事実台帳 | 日付 | roles.owner: 人<br>attributes.business_id: businessのID<br>attributes.event: 列挙（`household_use`・`gift`） | amounts.normal_sales_price・amounts.recorded_amount・amounts.acquisition_cost |
| facts | `bad_debt` | 補（income_kinds IK-110） | 事実台帳 | 日付 | roles.creditor: 人<br>amounts.amount: 円<br>attributes.business_id: businessのID<br>attributes.event: 列挙（`legal_cutoff`・`debt_forgiveness_notice`・`uncollectible`・`transaction_stopped`・`collection_cost`・`returns_or_discounts`・`guarantee_recourse`・`invalid_act`） | attributes.receivable_type・attributes.revenue_tax_year |
| facts | `rental_inventory` | F-A05 | 事実台帳 | 年分 | roles.owner: 人 | attributes.rooms・attributes.buildings・attributes.land_lots・attributes.parking_spaces・attributes.land_area_m2・attributes.management_note |
| facts | `property_tax` | F-A06 | 事実台帳 | 年度 | roles.taxpayer: 人<br>attributes.municipality_code: 団体コード | amounts.land・amounts.building |
| facts | `residence_status` | F-A07 | 事実台帳 | 日付 | roles.holder: 人<br>attributes.property_id: residence_propertyのID | attributes.occupant_person_ids・attributes.leased_to_others・attributes.intended_for_lease・attributes.always_habitable |
| assets | `depreciable_asset` | F-A01 | 事実台帳 | 区間 | roles.owner: 人<br>amounts.acquisition_cost: 円<br>attributes.name: 名称 | amounts.acquisition_consumption_tax・amounts.cost_excluding_consumption_tax・amounts.disposal_proceeds・amounts.disposal_expenses・amounts.insurance_recovery・amounts.residual_value_guarantee・amounts.estimated_residual_value・attributes.quantity・attributes.unit・attributes.acquisition_type・attributes.placed_in_service_on・attributes.business_id・attributes.prior_use_months・attributes.leased_out・attributes.acquisition_transaction_ids・attributes.disposal_type・attributes.property_id・attributes.receipt_id・attributes.lease_term・attributes.lease_contracted_on・attributes.extraction_quantities |
| assets | `rental_property` | F-A02 | 事実台帳 | 区間 | roles.owner: 人<br>attributes.property_type: 列挙（`building`・`room`・`land`・`parking`・`other`） | amounts.acquisition_cost・attributes.municipality_code・attributes.owner_share・attributes.co_owners・attributes.mixed_use・attributes.held_as_villa・attributes.acquisition_contract・attributes.business_id・attributes.country_code・attributes.held_through・attributes.arrangement_id |
| assets | `lease` | F-A03 | 事実台帳 | 区間 | roles.lessor: 人<br>attributes.property_id: rental_propertyのID | roles.lessee・amounts.monthly_rent・amounts.common_service_fee・amounts.deposit・amounts.key_money・attributes.lessee_name・attributes.payment_due_day |
| assets | `loan` | F-A04 | 事実台帳 | 区間 | roles.borrower: 人<br>amounts.principal: 円 | attributes.purpose_asset_id・attributes.interest_rate・attributes.lender・attributes.business_id |
| assets | `residence_property` | F-A07 | 事実台帳 | 区間 | roles.holder: 人<br>attributes.municipality_code: 団体コード<br>attributes.tenure: 列挙（`owned`・`rented`） | attributes.facility_type |
| assets | `insurance_contract` | F-D15 | 事実台帳 | 区間 | roles.policyholder: 人<br>attributes.product_type: 列挙（`life`・`medical_or_care`・`individual_annuity`・`earthquake`・`long_term_non_life`・`other`）<br>attributes.concluded_on: 日付 | roles.insured・amounts.certificate_amount・attributes.insurer_name・attributes.beneficiary_ids・attributes.rider・attributes.attached_to_contract_id・attributes.benefit_payment_terms・attributes.maturity_refund・attributes.contract_changes_on・attributes.annuity_payment_start_on・attributes.insured_object・attributes.insured_object_owner・attributes.residential_use・attributes.residential_ratio・attributes.certificate_electronic・attributes.certificate_includes_projection |
| filed_documents | `filed_document` | F-D01・F-D02 | 事実台帳 | 日付 | roles.filer: 人<br>attributes.document_type: 列挙（`final_return`・`quasi_final_return`・`loss_return`・`employee_dependents_declaration`・`secondary_salary_dependents_declaration`・`spouse_deduction_declaration`・`basic_deduction_declaration`・`specific_relative_deduction_declaration`・`resident_tax_return`・`local_tax_order_46_5_application`・`salary_payment_report`・`public_pension_payment_report`）<br>attributes.recipient: 列挙（`tax_office`・`employer`・`pension_payer`・`municipality`・`insurer`・`other`） | attributes.tax_year・attributes.fiscal_year・attributes.recipient_name・attributes.entries・attributes.reported_amounts・attributes.realized_choice_ids・attributes.correction |

#### 判断台帳（`record` に判断・選択の1件を書く。§4.2）

| 配列 | kind | VOC | when | 必須の欄 | 任意の欄 | value | mark |
|---|---|---|---|---|---|---|---|
| judgments | `判断.生計を一にする` | J-01 | 区間 | subject.person: 人<br>subject.other_person: 人 | — | 真偽 | — |
| judgments | `判断.事実婚` | J-02 | 区間 | subject.person: 人<br>subject.other_person: 人 | — | 真偽 | — |
| judgments | `判断.同居を常況` | J-03 | 区間 | subject.person: 人<br>subject.other_person: 人 | — | 真偽 | — |
| judgments | `判断.健保の同一の世帯` | J-04 | 区間 | subject.insured: 人<br>subject.person: 人 | — | {same_household: 真偽; criterion: 列挙（`actual_living`・`resident_record`）} | — |
| judgments | `判断.共済の生計を共にする` | J-05 | 区間 | subject.member: 人<br>subject.person: 人 | — | 真偽 | — |
| judgments | `判断.一時的な別居` | J-05 | 区間 | subject.member: 人<br>subject.person: 人 | — | 真偽 | — |
| judgments | `判断.住所の所在` | J-06 | 区間 | subject.person: 人 | — | 列挙（`domestic`・`foreign`） | — |
| judgments | `判断.国外転出時課税の対象` | 補（personal_deductions PD-05） | 年分 | subject.person: 人 | — | 真偽 | — |
| judgments | `判断.国内源泉所得の内訳` | 補（personal_deductions PD-06） | 年分 | subject.person: 人 | — | {non_domestic_income: 円（負も可）} | — |
| judgments | `判断.国内居住の例外第5号` | J-07 | 区間 | subject.person: 人 | — | 真偽 | — |
| judgments | `判断.老人ホーム等` | J-08 | なし | subject.stay_id: institution_stayのID | — | 真偽 | — |
| judgments | `判断.事業と称するに至る程度` | J-09 | 年分 | subject.person: 人<br>subject.business_id: businessのID | — | 真偽 | — |
| judgments | `判断.不動産の事業的規模` | J-10 | 年分 | subject.person: 人 | — | 真偽 | — |
| judgments | `判断.棚卸資産の有無` | 補（income_kinds IK-108） | 年分 | subject.person: 人<br>subject.business_id: businessのID | — | 真偽 | — |
| judgments | `判断.組合の重要業務の執行` | 補（income_kinds IK-104） | 年分 | subject.person: 人<br>subject.arrangement_id: 名称 | — | 真偽 | — |
| judgments | `判断.雇用か請負か` | J-11 | なし | subject.person: 人<br>subject.record_id: 記録のID | — | 列挙（`employment`・`independent_contract`） | — |
| judgments | `判断.業務関連性` | J-12 | なし | subject.record_id: 記録のID | — | 真偽 | — |
| judgments | `判断.按分の割合` | J-13 | 年分 | subject.person: 人 | subject.record_ids・subject.business_id | {purpose: 列挙（`household_expense_business_share`・`asset_business_share`・`dwelling_residential_share`・`family_use_share`）; ratio: 割合; 任意 measure・clearly_separable} | — |
| judgments | `判断.医療費の範囲` | J-14 | なし | subject.payment_id: medical_paymentのID | — | 真偽 | — |
| judgments | `判断.補塡の対象` | J-15 | なし | subject.reimbursement_id: reimbursementのID | — | {compensates_medical_expenses: 真偽; 任意 target_payment_ids} | — |
| judgments | `判断.セルフメディケーション表示の上書き` | J-16 | なし | subject.payment_id: medical_paymentのID | — | {eligible_item: 真偽; 任意 tax_year} | — |
| judgments | `判断.障害の程度` | J-17 | 区間 | subject.person: 人 | — | {aspect: 列挙（`bedridden_requiring_complex_care`・`lacks_capacity`・`severe_intellectual_disability`・`evidently_disabled_pending_application`・`pension_disability_level_for_health_insurance`）; applies: 真偽} | — |
| judgments | `判断.自己の勤労に基づく` | J-18 | 年分 | subject.person: 人 | subject.record_id・subject.business_id | 列挙（`based`・`not_based`） | — |
| judgments | `判断.家内労働者等` | J-19 | 年分 | subject.person: 人 | — | 真偽 | — |
| judgments | `判断.減価償却の区分` | J-20 | なし | subject.asset_id: depreciable_assetのID | — | {任意 useful_life_table_row・useful_life_years・usable_period_under_one_year・essential_to_business・lending_as_principal_business・asset_class・planned_extraction_quantity・building_or_structure・useful_life_method・remaining_life_documented} | — |
| judgments | `判断.不動産の区分の材料` | J-21 | なし | subject.record_id: 記録のID | — | {任意 custodial_parking・simple_facility・land_market_value・villa_purpose} | — |
| judgments | `判断.正規の簿記の宣言` | J-22 | 年分 | subject.person: 人<br>subject.business_id: businessのID | — | 真偽 | — |
| judgments | `判断.専従者給与の相当性` | J-23 | 年分 | subject.employer: 人<br>subject.employee: 人 | — | {任意 reasonable_amount・not_hindering_exclusive_engagement・mental_or_physical_disability・justifiable_reason・bonus_criteria_amount} | — |
| judgments | `判断.退職の性質` | J-24 | なし | subject.payment_id: retirement_paymentのID | — | {任意 is_retirement_allowance・disability_retirement・officer_class・income_type} | — |
| judgments | `判断.年金の性質` | J-25 | なし | subject.payment_id: pension_paymentのID | — | {任意 public_scheme・employee_contribution_portion} | — |
| judgments | `判断.雑損の計算` | J-26 | なし | subject.casualty_id: casualtyのID | — | {任意 not_ordinarily_necessary_asset・loss_measure・restoration_portion・expenditure_tax_year・unavoidable_circumstances} | — |
| judgments | `判断.寄附の性質` | J-27 | なし | subject.donation_id: donationのID | — | {任意 admission_related・special_benefit} | — |
| judgments | `判断.生命保険の区分` | J-28 | なし | subject.contract_id: insurance_contractのID | — | {category: 列挙（`general_life`・`care_medical`・`individual_annuity`）; 任意 dividend_allocation} | — |
| judgments | `判断.収入の恒常性` | J-29 | なし | subject.person: 人<br>subject.record_ids: 記録のIDの並び | — | 列挙（`temporary`・`recurring`） | — |
| judgments | `判断.主たる扶養者` | J-30 | 区間 | subject.person: 人<br>subject.supporter: 人 | — | 真偽 | — |
| judgments | `判断.収入が基準額以上とならないことが明らか` | 補 | 日付 | subject.person: 人 | — | 真偽 | — |
| judgments | `判断.大口株主等` | J-31 | なし | subject.dividend_id: dividendのID | — | 真偽 | — |
| judgments | `判断.扶養費の一部負担` | J-32 | 年分 | subject.person: 人 | — | 真偽 | — |
| judgments | `判断.障害者の通勤の特別の事情` | 補（kyuyo 質疑03-18） | 区間 | subject.person: 人<br>subject.counterparty: 名称 | — | 真偽 | — |
| judgments | `判断.通勤の合理的な運賃` | 補（tsukin HT3・UT4） | 区間 | subject.person: 人<br>subject.counterparty: 名称 | — | {monthly_amount: 円} | — |
| judgments | `判断.通勤手当の限度の当て方` | 補（tsukin UT1〜UT3） | 年分 | subject.person: 人 | — | 列挙（`low`・`high`） | — |
| judgments | `判断.給与の支給期が死亡前か` | 補（kyuyo-jiki UJ2） | なし | subject.record_id: salary_paymentのID | — | 真偽 | — |
| judgments | `判断.特定支出の通常の範囲の額` | 補（kyuyo KY-13） | なし | subject.record_id: specific_expenseのID | — | {countable_amount: 円} | — |
| judgments | `判断.事業の休止・重要部分の譲渡` | 補（income_totals IT-13） | 年分 | subject.person: 人 | subject.business_id | 列挙（`considerable_suspension`・`important_part_transfer`・`neither`） | — |
| judgments | `判断.家屋敷・事務所に当たる` | J-33 | 日付 | subject.person: 人<br>subject.property_id: residence_propertyのID | — | 真偽 | — |
| judgments | `判断.健保の経費の費目` | 補（hifuyosha） | なし | subject.person: 人 | subject.business_id | {mappings: {expense_category: 符号; item: 名称}の並び} | — |
| judgments | `見込み.年間収入` | P-01 | 日付 | subject.person: 人 | — | {amounts: {income_type: 列挙（`salary`・`business`・`real_estate`・`public_pension`・`dividend`・`unemployment_benefit`・`sickness_or_maternity_allowance`・`scholarship_loan`・`scholarship_grant`・`other`・`unspecified`）; amount: 円}の並び; 任意 temporary_increase_excluded・known_changes} | `予測`（必須） |
| judgments | `見込み.援助額` | P-02 | 日付 | subject.supporter: 人<br>subject.person: 人 | — | {annual_amount: 円; 任意 planned_count・amount_per_transfer} | `予測`（必須） |
| judgments | `見込み.被保険者の年間収入` | P-02 | 日付 | subject.insured: 人 | — | {annual_amount: 円} | `予測`（必須） |
| judgments | `見込み.将来の所得・加入` | P-03 | 年分 | subject.person: 人 | — | {任意 amounts・membership_changes} | `予測`（必須） |
| judgments | `計画.申告の方法と時期` | P-04 | 年分 | subject.person: 人 | — | {method: 列挙（`e_tax`・`paper`）; 任意 planned_filing_on・within_deadline・statements_attached} | `計画`（必須） |
| judgments | `見積り.親族の合計所得金額` | P-05 | 年分 | subject.person: 人<br>subject.taxpayer: 人 | — | {estimated_amount: 円（負も可）; estimated_as_of: 日付} | `見積り`（必須） |
| judgments | `見積り.補塡の見込額` | P-05 | 年分 | subject.payment_ids: medical_paymentのIDの並び | — | {estimated_amount: 円; benefit_type: 列挙（`hospitalization_benefit`・`high_cost_medical_care_benefit`・`childbirth_lump_sum`・`mutual_aid_benefit`・`sickness_allowance`・`maternity_allowance`・`sympathy_payment`・`other`）; 任意 estimated_as_of} | `見積り`（必須） |
| choices | `選択.扶養の所属` | C-01 | 年分 | subject.person: 人 | — | {filer: 人; document_type: 列挙（`final_return`・`quasi_final_return`・`loss_return`・`employee_dependents_declaration`・`secondary_salary_dependents_declaration`・`spouse_deduction_declaration`・`basic_deduction_declaration`・`specific_relative_deduction_declaration`・`resident_tax_return`・`local_tax_order_46_5_application`・`salary_payment_report`・`public_pension_payment_report`）; section: 列挙（`spouse`・`dependent_relative`・`specific_relative`・`disabled_person`・`widow_or_single_parent`・`working_student`・`other`）} | — |
| choices | `選択.配偶者の記載` | C-02 | 年分 | subject.spouse: 人 | — | {filer: 人; document_type: 列挙（`final_return`・`quasi_final_return`・`loss_return`・`employee_dependents_declaration`・`secondary_salary_dependents_declaration`・`spouse_deduction_declaration`・`basic_deduction_declaration`・`specific_relative_deduction_declaration`・`resident_tax_return`・`local_tax_order_46_5_application`・`salary_payment_report`・`public_pension_payment_report`）; listed: 真偽} | — |
| choices | `選択.医療費控除かセルフメディケーション税制か` | C-03 | 年分 | subject.person: 人 | — | 列挙（`medical_expense_deduction`・`self_medication`） | — |
| choices | `選択.保険料控除の区分` | C-04 | 年分 | subject.person: 人 | subject.contract_id | {任意 life_insurance_regime・earthquake_or_old_long_term} | — |
| choices | `選択.寄附金の控除の方式` | C-05 | なし | subject.donation_id: donationのID | — | 列挙（`income_deduction`・`tax_credit`） | — |
| choices | `選択.前納した社会保険料の控除の年分` | 補 | なし | subject.payment_id: social_insurance_paymentのID | — | 列挙（`pro_rata`・`all_in_paid_year`） | — |
| choices | `選択.株式等の申告` | C-06 | 年分 | subject.person: 人 | subject.record_id・subject.account_id | {target: 列挙（`dividend`・`withholding_account_transfer`）; 任意 declare・taxation・loss_offset・carryforward} | — |
| choices | `選択.現金主義（業務に係る雑所得）` | C-07 | 年分 | subject.person: 人<br>subject.business_id: businessのID | — | 真偽 | — |
| choices | `選択.消費税等の経理方式` | C-08 | 年分 | subject.person: 人<br>subject.business_id: businessのID | — | {sales: 列挙（`tax_inclusive`・`tax_exclusive`）; 任意 fixed_assets・inventory・expenses・accrue_unpaid_tax} | — |
| choices | `選択.減価償却` | C-09 | 年分 | subject.asset_id: depreciable_assetのID | — | {任意 lump_sum_depreciation・small_amount_special_rule・depreciate_in_disposal_year・depreciation_method} | — |
| choices | `選択.不動産所得の計上` | C-10 | 年分 | subject.record_id: 記録のID | — | {rule: 列挙（`period_matching`・`loan_interest_allocation`・`deposit_recognition_proviso`）; apply: 真偽} | — |
| choices | `選択.円換算の方法` | C-11 | 年分 | subject.person: 人 | — | {method: 列挙（`ttm`・`ttb`・`tts`）; 任意 institution} | — |
| choices | `選択.損失申告と繰戻し` | C-12 | 年分 | subject.person: 人 | — | {file_loss_return: 真偽; 任意 carryback_amount・second_prior_year_carryback_amount} | — |
| choices | `選択.還付申告` | C-13 | 年分 | subject.person: 人 | — | 真偽 | — |
| choices | `選択.特定支出控除` | 補（kyuyo KY-11） | 年分 | subject.person: 人 | — | 真偽 | — |
| choices | `選択.住民税の申告` | C-14 | 年度 | subject.person: 人 | — | {任意 file_resident_tax_return・collection_method_other_income・specific_expense_deduction} | — |
| choices | `選択.ワンストップ特例` | C-15 | 年分 | subject.person: 人 | — | {apply: 真偽; 任意 municipality_codes} | — |
| choices | `選択.夫婦共同扶養の届出` | C-16 | 区間 | subject.person: 人<br>subject.insured: 人 | — | 真偽 | — |
| choices | `選択.国民年金の免除の申請` | C-17 | 年度 | subject.person: 人 | — | {apply: 真偽; 任意 exemption_type} | — |
| choices | `選択.様式への割当て` | C-18 | 年分 | subject.person: 人 | subject.business_id | {mappings: {expense_category: 符号; form_item: 符号}の並び} | — |
| choices | `選択.被扶養者の届出` | C-20 | 区間 | subject.person: 人<br>subject.insured: 人 | — | 真偽 | — |
| choices | `選択.所得控除の順序` | 補（tax TX-19） | 年分 | subject.person: 人 | — | 列挙（`dividends_first`・`transfers_first`） | — |

<!-- END ledger_guide -->

## 5. 正規化した取引 JSON（`okura-transactions/0`）

`src/okura_records/adapter.py` の先頭に形がある。要点：取引ごとに `id`・`date`・`flag`・`payee`・`narration`・`tags`・`links`・
`meta`（型つき：`{"string"}`・`{"decimal"}`・`{"date"}`・`{"bool"}`・`{"amount": {"number", "currency"}}`・`{"null"}`）・
`postings`（`account`・`account_root`・`amount`（整数の円）・`currency`・`interpolated`・`meta`）・`source`（root からの相対パスと行）。
`documents` は証憑の root からの相対パスと SHA-256・バイト数。絶対パスは出さない（別のディレクトリに写しても同じ出力）。

## 6. 中間表現の作成（build_ir）

- 事実台帳・判断台帳の現在の記録をそのまま写し、`fact_kind` のある取引を事実の1件にする（§4.1）。`when` は取引の日付
  （`benefit_receipt` で `period` があれば区間）。`source` は取引 ID と証憑の SHA-256。
- 最後に `okura_ir.validate` で検査し、問題に出どころ（`origin`）を付ける。問題があれば `ir` は None。
- 例：`examples/household/`（架空の家庭。`tests/helpers.py` の `write_household` と同じ内容で、テストが一致を確かめる。改行を変換しないよう `.gitattributes` で `-text`）。
  2026-11-11 に中間表現の語彙の追加に合わせ、法令上の性別（`legal_sex`）・医療保険の資格（被保険者と被扶養者・保険者 ID）の事実と、
  配当等の種類（`distribution_type`）つきの配当の取引を足した。
  2026-11-12 に語彙の追加（`packages/ir/README.md` §6.2 の2026-11-12 の節）に合わせて足した：
  - 取引：回収できない未払の給与（`unpaid`・`uncollectible_amount`・`uncollectible_on`・`pay_period`）、共同募金会への寄附（`receipt_statement`・
    `recipient_office_prefecture_code`・`mic_approved_solicitation`）、国民年金保険料の前納と生命保険料の前納（`prepaid_due_dates`。日付の並び §4.1）。
    勘定 `Assets:Receivable:A`・`Expenses:Insurance`・`Expenses:Donation` を開いた。
  - 事実台帳：国民年金基金の加入員（`national_pension_fund`）、年金の受給権の制度 `corporate_pension`・`workers_accident_compensation` と障害等級
    `disability_grade`、在学の `npi_student_school_listed`（行の訂正 `correct` で書き足した）、課税（非課税）証明書（`income_certificate`）、
    保険の契約（`insurance_contract` の `benefit_payment_terms`。前納の取引が参照する）。
  - 判断台帳：`判断.収入が基準額以上とならないことが明らか`、`選択.前納した社会保険料の控除の年分`。
  - 事実台帳の新しい種類（`childbirth`・`special_adoption_petition`・`npi_application`・`estate_liquidator`、`kokuho_event` の `admission_type`、
    `depreciable_asset` の `receipt_id` など）は記録をそのまま写す（`tests/test_build_ir.py` の `test_ledger_records_of_2026_11_12_vocabulary_are_copied_as_is`）。
- 例：`examples/vocabulary/`（2026-11-12。**語彙の全種類**の書き方の例。架空の三世代の家庭：人 11、`main.beancount` に取引の20種類、
  `facts.jsonl` に取引でない種類の全部と取引の種類を事実台帳に書く例〔記帳していない祖父の年金・死亡後に支払われた祖母の給与〕、
  `judgments.jsonl` に判断・選択の全種類〔判断の見直しの連鎖 `replaces` つき〕。行の訂正 `correct` と取消し `delete` の例も入れた）。
  `facts.jsonl`・`judgments.jsonl` が正（生成元は無い）。行を足すときは `append` コマンド（§7）を使う。
  `tests/test_vocabulary_examples.py` が、`examples/` の下の全部の例で build_ir の結果が okura_ir の検査に通ること、
  語彙のすべての種類が書く場所（§4.3）どおりに例にあることを確かめる（語彙に種類が足されたら、例を足すまで失敗する）。
- 同じ取引を台帳と事実台帳の両方に書いたもの（事実台帳の取引の種類の記録の `source.transaction_ids` が、事実にした台帳の取引を指す）は
  `fact_written_twice`（重複の検出。合計はしない）。

## 7. コマンド

```
.work/venvs/records/Scripts/python.exe -I -X utf8 -m okura_records.cli build-ir \
    --ledger packages/records/examples/household/main.beancount \
    --facts packages/records/examples/household/facts.jsonl \
    --judgments packages/records/examples/household/judgments.jsonl [--root DIR]
.work/venvs/records/Scripts/python.exe -I -X utf8 -m okura_records.cli transactions --ledger …
.work/venvs/records/Scripts/python.exe -I -X utf8 -m okura_records.cli append --facts facts.jsonl --draft draft.json
.work/venvs/records/Scripts/python.exe -I -X utf8 -m okura_records.cli append --judgments judgments.jsonl --draft draft.json
```

`append` は下書き（§4.2）に `prev_sha256` を入れ、足した後の台帳全体を検査してから末尾に書く（台帳が無ければ作る。読んだ後に台帳が変わっていれば
`changed_during_read` で書かない）。record の中身の検査は build-ir で行う。

標準出力に JSON（UTF-8・LF・キーを並べた決定的な出力）。終了コード：0 成功、1 入力の問題（標準エラー出力に `{"ok": false, "problems": [...]}`）、
2 使い方の誤り・`-I` なし。`--root` の既定は `--ledger` のディレクトリ（include・document はこの中だけ）。

## 8. 問題の code

| 部品 | code |
|---|---|
| safe_loader | `root`・`main_path`・`outside_root`・`not_found`・`link`・`hard_link`・`not_regular_file`・`file_too_large`・`total_too_large`・`too_many_files`・`changed_during_read`・`io_error`・`bom`・`nul`・`control_char`・`bidi_control`・`bare_cr`・`not_utf8`・`line_too_long`・`string_too_long`・`plugin`・`insert_pythonpath`・`plugin_processing_mode`・`option_documents`・`include_form`・`include_duplicate`・`document_path`・`document_outside_root`・`evidence_too_large`・`beancount_error`・`internal_error` |
| adapter | `transaction_id_missing`・`transaction_id_type`・`transaction_id_pattern`・`transaction_id_duplicate`・`currency_not_jpy`・`amount_not_integer`・`amount_out_of_range`・`cost_or_price`・`directive_not_supported`・`flag_not_supported`・`meta_unknown_key`・`meta_type`・`document_transaction_unknown` |
| 台帳（JSON Lines） | `ledger_too_large`・`ledger_bom`・`ledger_not_utf8`・`ledger_cr`・`ledger_no_final_newline`・`ledger_blank_line`・`ledger_line_too_long`・`json_*`（okura_ir.loads）・`entry_field`・`entry_ledger_mismatch`・`entry_op`・`entry_id_duplicate`・`entry_time_order`・`chain_broken`・`entry_replaces_unknown`・`entry_replaces_section`・`entry_replaces_deleted`・`entry_fork`・`record_id_duplicate`・`record_has_recorded_at`・`judged_after_recorded`・`record_section_mismatch`（kind を違う section に書いた）・`draft_shape`（append の下書きの形） |
| build_ir | `input_shape`・`fact_kind_unknown`・`fact_keys_without_kind`・`fact_key_not_for_kind`・`fact_value_type`・`fact_amount_field`・`fact_amount_reversed`・`fact_amount_duplicate`・`fact_flag_pending`・`fact_when`・`record_has_recorded_at`・`fact_written_twice`、ほかは okura_ir.validate の code（`unknown_person`・`duplicate_id` など） |

## 9. テストの動かし方

リポジトリの根で（記録層の仮想環境）：

```
.work/venvs/records/Scripts/python.exe -I -X utf8 -m unittest discover -s packages/records/tests -t packages/records
```

| ファイル | 中身 |
|---|---|
| `test_safe_loader.py` | §3.1 の攻撃の経路ごとの拒否と印のファイル（陽性対照つき）、loader と同じ結果になること、証憑のハッシュ、レビューで足した攻撃（`Review*Tests`） |
| `test_adapter.py` | 取引 ID、JPY の整数、ディレクティブとフラグ、メタデータの語彙と型、証憑、決定性、`examples/household` の一致 |
| `test_ledgers.py` | 畳み込み（訂正・取消し・連鎖）、改ざんの検出、行の形と欄の検査、判断台帳の検査、`current_values`、畳み込みの決定性（ハッシュの種・キーの順・1行ずつの再生）と末尾の切り詰めの限界 |
| `test_build_ir.py` | 架空の家庭の中間表現が okura_ir の検査に通る、値の変換、名前・科目名を写さない、問題の出どころ、純粋・決定的、合計しない・科目名で変わらない・台帳に無い欄を足さない |
| `test_vocabulary_examples.py` | `examples/` の全部の例で build_ir（直接呼ぶ）の結果が okura_ir の検査に通る、語彙の全種類が書く場所（§4.3）どおりに例にある、書く場所の対応（`ledger_map`）、§4.3 の表が語彙の表と一致、`record_section_mismatch`・`fact_written_twice`・`append_drafts` |
| `test_layering.py` | okura_core・OpenFisca を import しない、純粋な部品が beancount なしで動く |

（D24 で CLI を通すテスト `test_cli.py` は消した。CLI はテストしない。）

## 10. 未決・TODO

- 2026-11-11：中間表現の語彙に欄・種類を足した（`packages/ir/README.md` §6.2 の「所得税・住民税・被扶養者の『語彙がない』対象外を解くための語彙」）。
  記録層のメタデータの語彙は `okura_ir.vocabulary` から作るので、取引（`salary_payment` の `resolution_on`・`paid_outside_japan` など、`donation` の
  `recipient_local_government_code` など）と事実台帳（`childcare_leave`・`brokerage_annual` の住民税の額など）にそのまま書ける（`tests/test_build_ir.py`）。
- 2026-11-12：中間表現の語彙にさらに欄・種類を足した（`packages/ir/README.md` §6.2 の2026-11-12 の節。約60か所）。取引の欄（`salary_payment` の
  `uncollectible_amount`・`uncollectible_on`・`prior_month_net_salary`・`payer_business_id`・`paid_by_foreign_mission`・`pay_period`、`business_expense` の
  `receipt_id`・`rent_flow_id`・`property_id`・`loan_id`、`donation` の `mic_approved_solicitation`・`recipient_office_prefecture_code`・`onestop_request_municipality_code` など）は
  取引のメタデータにそのまま書ける（`test_vocabulary_added_2026_11_12`）。**日付の配列**（`prepaid_due_dates`）は、それまでメタデータの書き方が無く
  取引の欄の検査（`test_all_transaction_fields_have_a_shape`）が失敗していたので、書き方 `date_list`（空白区切りの日付。§4.1）を `meta_vocabulary` と `build_ir` に足した
  （法令の解釈をしない正規化だけ）。事実台帳の新しい種類はそのまま写る。
- 取引から作る事実で、メタデータに書けない欄の形（配列の中のオブジェクトなど）は、取引の種類（F-T）にはいまない（`test_all_transaction_fields_have_a_shape`）。
  語彙の表に足されたら書き方を決める必要がある。
- ファイルのシンボリックリンクの実物での試験（§3.2）。
- 上限の値の根拠（実際の台帳の最長の行）、走査と字句解析の食い違いの網羅的な探索（§3.2）、§3.3 の測定の正式な記録。
- 1取引に複数の事実（明細を1取引にまとめた記帳）は版 0 では書けない。証券（JPY 以外の商品）は台帳に書けないので事実台帳に書く。
- `recorded_by.person` が人の記録にあるかは検査しない。
- 2026-11-12：語彙の全種類（この時点で記録 85・判断 51・選択 21。§4.3）を記録層から作れるようにし、例（`examples/vocabulary/`）を足した。
  語彙に種類が足されたら `test_every_kind_has_an_example_in_its_place` が失敗するので、`append` で例の行を足し、§4.3 の表を `--write` で作り直す
  （`判断.組合の重要業務の執行` はこの手順で足した：judgments.jsonl の je-0073）。任意の欄だけの追加は例を直さなくてよい。
  `append` コマンドはテストしていない（中身の `append_drafts` だけをユニットテストした。D24）。
  取引の種類（F-T）に新しい欄の型（例：2026-11-12 に足された `$defs/quantity`）が使われたら、`meta_vocabulary.field_shape` に書き方を足す必要がある
  （`test_all_transaction_fields_have_a_shape` が知らせる）。
  `fact_written_twice` は `source.transaction_ids` を書いたときだけ見つけられる（書かずに同じ取引を両方に書いた二重は見つけられない）。
- 2026-11-12（impl-research8。kyuyo の担当）：語彙に `specific_expense`（事実台帳。VOC の F-T の番号がないので台帳の取引には書けない）・`選択.特定支出控除`、
  `authority_decision` の必須の欄 `tax_item` を足した。例は `append` と同じ `append_drafts` で足した（facts.jsonl の fe-0108〜fe-0110、judgments.jsonl の je-0075）。
  既存の `authority_decision`（fe-0081）は必須の欄が増えたので、追記のみの規則どおり `correct` の行（fe-0108）で tax_item を足して直した
  （実際の台帳でも、2026-11-12 より前に書いた authority_decision は同じように `correct` で tax_item を足す必要がある）。§4.3 の表は `ledger_map --write` で作り直した。
- 2026-11-12（2回目）：その後に語彙に足された事実台帳の種類 `medical_expense_notice`・`external_tax_credit`・`inventory_method_notice`・`inventory_count`・
  `household_consumption`・`bad_debt`・`special_depreciation`（割増償却・特別償却の額。外部の値：packages/ir/README.md §6.2 の IK-112）の例を facts.jsonl の fe-0101〜fe-0107 に、
  `判断.棚卸資産の有無` の例を judgments.jsonl の je-0074 に足し、§4.3 の表を `--write` で作り直した（記録 92・判断 52・選択 21）。どれも取引（F-T）でないので事実台帳に書く。
- 2026-11-12 の2回目（kyuyo の担当。KY-13）：`specific_expense` の amount は実際の支出金額を書く約束に改め、旅費・帰宅旅費の通常の経路・方法による部分、
  転居の運賃・宿泊費の通常の範囲の額は判断台帳の `判断.特定支出の通常の範囲の額`（subject は specific_expense の ID）に書くようにした。転居費の支出の別
  `attributes.relocation_item`（任意）を足した。例：facts.jsonl の fe-0111（転居の宿泊費）、judgments.jsonl の je-0076（旅費の通常の範囲の額）を `append` で足し、
  §4.3 の表を `ledger_map --write` で作り直した（判断 53）。それより前に amount に政令の範囲の額を書いた記録は、実際の支出金額に `correct` で直し、判断を足す。
- 電帳法の証憑の保存と操作の記録（VOC F-E01・F-E02、denchoho H2〜H5）はこのパッケージに無い。
- beanquery は使っていない（D11 の「beancount 3 ＋ beanquery」のうち、アダプタは beancount だけで足りた。集計の問い合わせは利用者が別に使う）。
- 語彙の未決（okura_ir README §6.3：未提出の選択の印、続柄、健保の同一の世帯など）はそのまま引き継ぐ。
