---
name: add-rule
description: okura-gov の判定コア（packages/core）に法令の規則（概念・パラメータ・OpenFisca の変数）を足す・直すときに使う。「規則を足す」「控除・判定を実装する」「対象外の行を実装する」「(c) を片づける」「規則モジュールを作る」「rules/<名前> を直す」など。法令改正への対応は law-change、年分の追加は add-tax-year、市町村・保険者ごとの値は add-injection-point を使う。
---

# 規則を足す（okura-gov）

最初に `AGENTS.md`・`HANDOFF.md`（D19〜D24）・`SCOPE.md` §5（範囲）を読む。手順の元は `packages/core/README.md` §10「規則モジュールの足し方」と各 `rules/<名前>/README.md` の「足し方の手順」。
食い違ったら HANDOFF ＞ SCOPE ＞ README の順で正とし、直さずにユーザーに確認する。

## 0. 足してよいかを決める

- SCOPE §5 の範囲か。範囲の外（SCOPE §4・D20）と後の段（D21 R3・D22）は実装せず、「対象外」の行（分類 `(a)`・`(b)`）にする。
- 持ち場：規則は `packages/core/src/okura_core/rules/<名前>/` の中だけで足す。ほかの担当のモジュールのディレクトリと共有のファイル（`evaluate.py`・`situation.py`・`registry.py`・`country/`・`concepts/structure.yaml`・`timepoints.py`・`injection_points.py`・`dependents/`）は、並行の担当と調整してから触る。
- 市町村・保険者ごとに変わる値なら add-injection-point を先に使う。

## 1. 触るファイル

| ファイル | 書くこと |
|---|---|
| `docs/public-sources/YYYYMMDD_<群>_<題>.md` | 条文・基準額・施行日・適用年分の一次情報（なければ primary-source スキルで先に作る） |
| `rules/<名前>/concepts.yaml` | 概念（ID・定義の条文と出典・層・期間・値の型・依存・変数・パラメータ・実装済み） |
| `rules/<名前>/parameters/<制度>/….yaml` | 基準額・率・表（日付のキーは適用開始日。`metadata` 必須） |
| `rules/<名前>/data/` | 大きな表（CSV と `SOURCES.json`〔取得元と SHA-256〕） |
| `rules/<名前>/variables.py` など | OpenFisca の `Variable`、純粋関数 |
| `rules/<名前>/__init__.py` | `MODULE = RuleModule(...)`（変数・記録の種類・build_inputs・decisions・readings・roundings・groups・stages・checks・rules・basis） |
| `rules/<名前>/README.md` | 作る概念、上流・下流の概念、読み（法令の読み）、対象外の一覧と `### 集計` |
| `rules/__init__.py` | 新しいモジュールのときだけ、1行 `from .<名前> import MODULE as <名前>` |
| `packages/core/tests/test_<名前>*.py` | ユニットテスト |

## 2. 手順

1. **一次情報を確かめる。** `docs/public-sources`・`docs/measurements` で、条番号・文言・基準額・施行日・適用年分（「令和X年分以後」）を確かめる。記憶やモデルの知識で値を書かない。見つからなければ primary-source スキルで取得して記録する。一次情報で決まらないことは「分からなかった」と記録する。
2. **概念辞書**（`concepts.yaml`。キーは `concepts/__init__.py` の docstring）：
   - ID は `<制度>.<名前>`、変数名は ID の `.` を `_` にしたもの。同じ言葉で意味が違うもの（所得・収入・年収、配偶者、世帯と生計を一にする、年齢の判定時点）は別の ID。
   - `定義` の `出典` は docs のファイル#節。`根拠の種類` は `basis.SourceKind` の値（「法律」「政令」「省令」「告示」「通達」「通知・事務連絡」「手引き・様式の注記」「国税庁の説明」「保険者の案内」「自治体の資料」。強さの順位は `basis._RANK`。法律・政令・省令は同じ順位。自治体の資料は注入データの出典にだけ使う：D22 S2）。
   - 式が引く概念を全部 `依存する概念` に、ほかの制度・ほかの人・ほかの年を引くなら `制度をまたぐ依存`・`人をまたぐ依存`・`年をまたぐ依存` に、集約点のある層を直接引くなら `集約点を通らない依存` に根拠つきで書く。集約点へ集める概念は `集める先`。段が書く入力は事実の層に置き `段階:`。境目の説明が要る判定は `境目`。
   - 実装したら `実装済み: true`、`未実装のとき` を消す。ほかのモジュールが引く概念の名前・値の型・期間・層は、その担当と合わせずに変えない。
3. **パラメータ**（`packages/core/README.md` §7.1）：
   - 名前は日本語の木（例 `所得税.給与所得.措法第29条の4第2項.第2号.控除額`）。日付のキーは **適用開始日**（所得税は年分の1月1日）。施行日は `metadata` の `施行日`。
   - `metadata`：`law`（条・項・号と原文の語）、`source_kind`、`reference`（docs のファイル#節と、取得した写し `scripts/results/…` のパス）、`施行日`、必要なら `flags`（原文未確認など）・`reading`（法令の読み）・`比較`（超・以下・未満・以上）・`law_revision`・`unit`。
   - 率は `率.分子`・`率.分母` の整数。小数を書かない。時限の特例は終わりの日に `value: null` を置く。同じ葉を2つのモジュールに置かない。
   - YAML はコード：タグを書かない（アンカー `&`・`*` は既存のファイルどおり使ってよい）。値を変えるたびに出典を添える。
4. **変数と純粋関数**：
   - 式は同じ層か下の層の変数だけを引く。ほかの年分の値を引かない（前年以前の記載はその年分の入力にする）。ほかの人の値はグループを通して引き、概念辞書に宣言する。
   - 金額は整数の円、途中の値は `Fraction`（float を使わない）。丸めは根拠のある所でだけ `rounding.RoundingRule`（名前つき）。根拠のない端数は `RoundingSlotSpec`、一次情報で決まらない読みは `ReadingSlotSpec`（D22 S1・S3）。候補を引くのは値が分かれる人がいるときだけにする。
   - 入力されていない判断・選択は `DecisionSpec` で宣言し、候補の全部で評価する（D21 R6）。有利な候補を選ばない（D22 S20）。
5. **`MODULE` を書く**（`packages/core/README.md` §10 の表）。`record_kinds` には実際に使う記録の種類だけを書く。
6. **対象外**（黙って近似しない）：扱えない入力は `out.exclude(人, 理由, 変数)` か `checks` で対象外にする。理由の文は名前つきの定数（`*_REASON`・`REASON_*`・`R_*`・`T_*`）に置き、README の「対象外の一覧」の行の表（コード・理由の要約・検出の場所・分類・根拠の決定 ID・状態）と `### 集計` の両方に載せる。範囲内なのに未対応（`(c)`）を残さない（D24③）。
7. **ユニットテストを書く**（D24）：
   - 関数・表・1つの変数の式を直接呼ぶ。上流は入力として与える（`tests/support.py` の `system()` と `SimulationBuilder().build_from_entities(system(), {...})`、仮置きの変数に値を入れる）。
   - `evaluate`・CLI・結合を通すテストは作らない。テストのデータは架空の家庭だけ。
   - 法令の境目（以下と超の両側、年分の切り替わり、年齢の判定日）など間違えやすい所に絞る。期待値には出典（docs のファイル#節）と年分をコメントで書く。
8. **README を直す**（日付つき）：作った概念、上流・下流、読み、対象外の一覧と集計。

## 3. 確かめ方（リポジトリの根で）

```
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_<名前>.py
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_architecture.py packages/core/tests/test_architecture_modules.py packages/core/tests/test_architecture_imports.py
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_out_of_scope_inventory.py
```

- 構造の検査が止めたら、宣言（概念辞書）を直す。検査を弱めない。
- 最後に core の全部のテスト（`packages/core/tests`。数十分かかるのでバックグラウンドで）。注入点を使ったら `test_injection.py`、境目を宣言したら `test_output.py` も。
- 中間表現の語彙が足りないときは、`packages/ir/README.md` §9 の手順（ir の担当・記録層の担当と調整）。

## 4. してはいけないこと

- 一次情報なしに基準額・条番号を書く。テストの期待値を実装の出力から写す。
- 対象外にすべき入力を、近い規則で計算して黙って返す。
- 家族の実際のデータをテスト・例・docs・外部のサービスに入れる。
- シェルの引数にバッククォートや `$()` を入れる（ファイルは Edit・Write で書く）。
