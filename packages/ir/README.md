# okura_ir：中間表現の約束（版 0）

記録層（`okura_records`）が作り、判定コア（`okura_core`）が受け取る **中間表現** の JSON Schema と、
それを解釈する自作の検査器。**標準ライブラリだけ** で書いてあり、core と records の両方の仮想環境から
import する（core と records は互いに import しない。SCOPE §6）。

## 1. 責務

| する | しない |
|---|---|
| 中間表現の形を決める（`schema/ir.schema.json`。JSON Schema 2020-12 の部分集合） | 法令の解釈（所得区分、扶養親族に当たるか、基準額・率）。中間表現には法令の区分を入れない（HANDOFF D3・D5 改） |
| 中間表現を検査する：スキーマの検査と意味の検査（`validate`） | 判定・計算（判定コア）、台帳の読み込み（記録層） |
| JSON を厳密に読む（`loads`：重複キー・NaN・BOM などを拒否） | 判断・選択の履歴の畳み込み（現在の値を求める処理。判定コアか記録層） |
| 有効な例・無効な例（期待する問題つき）を持つ | 注入データ（市町村・保険者）と問い（年分・判定日など）の形（判定コアの `evaluate` の入力） |

法令の値（基準額・表・率）はこのパッケージに一つもない。金額の上限（1兆円）は誤入力と桁あふれを止めるための値で、法令の値ではない。

## 2. 公開する関数

```python
from okura_ir import SCHEMA_VERSION, Problem, loads, validate, load_schema

ir, problems = loads(raw_bytes)        # JSON を厳密に読む。問題があれば ir は None
problems = problems or validate(ir)    # 中間表現を検査する。空なら合格
for p in problems:
    print(p.path, p.code, p.message)   # 例：$.facts[0].amounts.amount type 整数が必要（文字列が来た）
```

| 名前 | 中身 |
|---|---|
| `SCHEMA_VERSION` | `"0"`。中間表現の `schema_version` はこれと同じでなければならない |
| `Problem` | `path`（`$.facts[3].roles.payer` の形）・`code`（§5 の表）・`message`（日本語）。`to_dict()` |
| `validate(ir) -> list[Problem]` | 例外を送出しない。版が違えばその1件だけ、スキーマの問題があればそれだけを返し、なければ意味の検査の問題を返す |
| `loads(data, *, max_bytes=16MiB, max_depth=64) -> (value, list[Problem])` | `str` か `bytes`。例外を送出しない |
| `load_schema() -> dict` | 同梱のスキーマ。呼ぶたびに新しい dict（共有の可変状態を持たない） |

下位のモジュール：`okura_ir.jsonschema_subset`（`evaluate`・`check_schema`。部分集合の解釈器そのもの）、
`okura_ir.vocabulary`（語彙の表）、`okura_ir.build_schema`（表からスキーマを作る）。

## 3. 中間表現の形

根のオブジェクトは次の欄を **全部** 持つ（中身が無くても空の配列を書く。書き忘れと「無い」を分けるため）。

| 欄 | 中身 |
|---|---|
| `schema_version` | `"0"` |
| `persons` | 人：`id`・`birth_on`・`death_on`（任意）。氏名・個人番号は持たない（VOC F-P01） |
| `relations` | 人と人の関係（区間つき） |
| `residences` | 各人の住所の市町村（住民票の記録・住民税を課す市町村） |
| `insurance_memberships` | 加入している保険と保険者（医療保険・国民年金・厚生年金・年金の受給権） |
| `facts` | 役割つきの事実（人の属性・取引・書類・処分）。明細の粒度 |
| `assets` | 資産・物件・契約の台帳（保険の契約を含む） |
| `filed_documents` | 提出した書類の記載 |
| `judgments` | 判断台帳：人の判断・予測・法令が求める見積り・申告の計画 |
| `choices` | 納税者の選択 |

### 3.1 記録（relations〜filed_documents）の共通の欄

```json
{"id": "mp-g-1", "kind": "medical_payment",
 "roles": {"payer": "p-x", "patient": "p-g"},
 "when": {"on": "2026-02-10"},
 "amounts": {"amount": 120000},
 "attributes": {"incurred_on": "2026-01-28", "medical_kinds": ["medical_treatment"]},
 "mark": "予測", "source": {"transaction_ids": ["tx-…"], "evidence_sha256": ["…"]},
 "recorded_at": "2026-02-11T21:00:00+09:00", "note": "…"}
```

- `kind` ごとに `roles`（役割 → `persons` の id）・`when`・`amounts`・`attributes` の欄が決まっている。
  知らないキーは拒否する。役割は家族（`persons`）だけ。家族の外の相手は `counterparty` などの名前の欄に書く。
- `when` は種類ごとに次のどれか：`{"on": 日付}`、`{"from_on": 日付, "to_on": 日付}`（両端を含む。`to_on` が無ければ続いている）、
  `{"tax_year": 年}`（所得税の年分）、`{"fiscal_year": 年}`（年度）、日付か区間のどちらか一方。
- `amounts` は全部 **整数の円**。率・割合・外貨の額は `{"num": 整数, "den": 1以上の整数}`。
  **数の欄に文字列・小数・真偽値を置けない**（OpenFisca が数の欄の文字列を式として評価する問題への対策：
  `docs/measurements/20261109_R2-tools_openfisca-core-runtime.md` T11、`docs/measurements/20261109_impl-prep_tools-openfisca-probe.md` §5）。
- `mark`（任意。`filed_documents` には置けない）：状態の印（D21 R2・D22）。`見積り`＝法令が求める見積り、
  `計画`＝申告の計画、`予測`＝見込み（D19）。無ければ実際の記録。印を結果にどう伝えるかは判定コアの責務。
- `source`：根拠の取引 ID（記録層の `id` メタデータ）と証憑の SHA-256。取引そのものは中間表現に入れないので、取引 ID の存在は検査しない。

### 3.2 判断・選択の共通の欄

```json
{"id": "j-rent-ratio-v2", "kind": "判断.按分の割合",
 "judged_by": {"person": "p-s"}, "judged_at": "2026-03-01T09:00:00+09:00",
 "subject": {"person": "p-s", "record_ids": ["f-rent-2026-01"], "business_id": "biz-s"},
 "when": {"tax_year": 2026},
 "value": {"purpose": "household_expense_business_share", "ratio": {"num": 3, "den": 10}},
 "basis": {"record_ids": ["…"], "method": "…"}, "replaces": "j-rent-ratio-v1"}
```

- 判断（`judgments`）：判断者 `judged_by`（家族なら `{"person": id}`、外なら `{"label": 名前}`）、日時 `judged_at`（秒まで・時差つき）、
  対象 `subject`（種類ごとの欄）、`when`（種類ごと。時を持たない種類には置けない）、`value`、根拠 `basis`、置き換える判断 `replaces`。
- `value` の型が種類ごとの **値の領域**（真偽・列挙・数の範囲）。判断が無いときに判定コアがありうる値の全部で評価する（D21 R6）ための語彙。
- 印：`見込み.*` は `"mark": "予測"`、`見積り.*` は `"mark": "見積り"`、`計画.*` は `"mark": "計画"` が必須。`判断.*` は将来についての判断なら `"mark": "予測"` を付けてよい。
- 選択（`choices`）：選んだ人 `chosen_by`（`persons` の id）、`chosen_at`、`subject`、`when`、`value`、`basis`、`replaces`。印は持たない（§6 の UO2）。
- 置き換えは追記のみ（D12）。現在の値は `replaces` の連鎖の先頭。連鎖の整合は §5 の意味の検査で確かめる。

### 3.3 種類の一覧（VOC の ID つき）

VOC＝`docs/hypotheses/20261109_round3_design-vocabulary.md`。各欄の中身は `src/okura_ir/vocabulary.py`（とそこから作った `ir.schema.json`）を見る。

| 配列 | kind（VOC の ID） |
|---|---|
| `relations` | `parentage`（F-R01）、`adoption`（F-R02）、`marriage`（F-R03）、`foster_placement`（F-R04）、`cohabitation`（F-R05）、`separation_reason`（F-R06）、`heirship`（F-R07） |
| `residences` | `resident_record`（F-P06）、`municipal_tax_domicile`（F-P16） |
| `insurance_memberships` | `medical_insurance`（F-P12）、`national_pension`（F-P13）、`employees_pension`（F-P13）、`national_pension_fund`（補。2026-11-12）、`pension_entitlement`（F-P13） |
| `facts` | `abroad_stay`（F-P04）、`civil_status`（F-P05）、`legal_sex`（補）、`childcare_leave`（補。2026-11-11）、`dwelling_stay`（F-P07）、`institution_stay`（F-P08）、`enrollment`（F-P09）、`disability_basis`（F-P10）、`care_level`（F-P11）、`kokuho_event`（F-P14）、`childbirth`（補。2026-11-12）、`special_adoption_petition`（補。2026-11-12）、`npi_application`（補。2026-11-12）、`income_certificate`（補。2026-11-12）、`public_assistance`（F-P15）、`ct_liability`（F-P17）、`invoice_registration`（F-P18）、`dependent_allowance`（F-P19）、`business_engagement`（F-P20）、`business`（補）、`salary_payment`（F-T01）、`commuting_status`（補）、`specific_expense`（補。2026-11-12）、`business_receipt`（F-T02）、`business_expense`（F-T03）、`payroll_paid`（F-T04）、`medical_payment`（F-T05）、`reimbursement`（F-T06）、`social_insurance_payment`（F-T07）、`mutual_aid_payment`（F-T08）、`insurance_payment`（F-T09）、`donation`（F-T10）、`casualty`（F-T11）、`casualty_expenditure`（F-T11）、`pension_payment`（F-T12）、`retirement_payment`（F-T13）、`dividend`（F-T14）、`security_sale`（F-T15）、`remittance`（F-T16）、`windfall_receipt`（F-T17）、`benefit_receipt`（F-T18）、`rent_flow`（F-T19）、`prior_income_fixed`（F-D03）、`withholding_slip`（F-D04）、`prepayment_notice`（F-D05）、`labor_contract`（F-D06）、`employer_attestation`（F-D07）、`insurer_decision`（F-D08）、`npi_exemption`（F-D09）、`foreign_kin_document`（F-D10）、`blue_return_procedure`（F-D11）、`bookkeeping_status`（F-D12）、`family_employee_notice`（F-D13）、`health_checkup_record`（F-D14）、`retirement_record`（F-D16）、`brokerage_annual`（F-D17）、`housing_loan_credit`（F-D18）、`external_tax_credit`（補。2026-11-12）、`special_depreciation`（補。2026-11-12）、`medical_expense_notice`（補。2026-11-12）、`inventory_count`・`inventory_method_notice`・`household_consumption`・`bad_debt`（補。2026-11-12）、`ct_return`（F-D18）、`authority_decision`（F-D19）、`jan1_payer_status`（F-D20）、`tax_agent_notice`（F-D21）、`estate_liquidator`（補。2026-11-12）、`rental_inventory`（F-A05）、`property_tax`（F-A06）、`residence_status`（F-A07） |
| `assets` | `depreciable_asset`（F-A01）、`rental_property`（F-A02）、`lease`（F-A03）、`loan`（F-A04）、`residence_property`（F-A07）、`insurance_contract`（F-D15） |
| `filed_documents` | `filed_document`（F-D01・F-D02） |
| `judgments` | `判断.生計を一にする`（J-01）、`判断.事実婚`（J-02）、`判断.同居を常況`（J-03）、`判断.健保の同一の世帯`（J-04）、`判断.共済の生計を共にする`（J-05）、`判断.一時的な別居`（J-05）、`判断.住所の所在`（J-06）、`判断.国外転出時課税の対象`（補。2026-11-12）、`判断.国内源泉所得の内訳`（補。2026-11-12）、`判断.国内居住の例外第5号`（J-07）、`判断.老人ホーム等`（J-08）、`判断.事業と称するに至る程度`（J-09）、`判断.不動産の事業的規模`（J-10）、`判断.組合の重要業務の執行`（補。2026-11-12）、`判断.雇用か請負か`（J-11）、`判断.業務関連性`（J-12）、`判断.按分の割合`（J-13）、`判断.医療費の範囲`（J-14）、`判断.補塡の対象`（J-15）、`判断.セルフメディケーション表示の上書き`（J-16）、`判断.障害の程度`（J-17）、`判断.自己の勤労に基づく`（J-18）、`判断.家内労働者等`（J-19）、`判断.減価償却の区分`（J-20）、`判断.不動産の区分の材料`（J-21）、`判断.正規の簿記の宣言`（J-22）、`判断.専従者給与の相当性`（J-23）、`判断.退職の性質`（J-24）、`判断.年金の性質`（J-25）、`判断.雑損の計算`（J-26）、`判断.寄附の性質`（J-27）、`判断.生命保険の区分`（J-28）、`判断.収入の恒常性`（J-29）、`判断.主たる扶養者`（J-30）、`判断.収入が基準額以上とならないことが明らか`（補。2026-11-12）、`判断.大口株主等`（J-31）、`判断.扶養費の一部負担`（J-32）、`判断.障害者の通勤の特別の事情`（補。2026-11-12）、`判断.通勤の合理的な運賃`（補）、`判断.通勤手当の限度の当て方`（補）、`判断.給与の支給期が死亡前か`（補）、`判断.特定支出の通常の範囲の額`（補。2026-11-12 の2回目）、`判断.事業の休止・重要部分の譲渡`（補。2026-11-11）、`判断.家屋敷・事務所に当たる`（J-33）、`判断.健保の経費の費目`（補。2026-11-11）、`見込み.年間収入`（P-01）、`見込み.援助額`（P-02）、`見込み.被保険者の年間収入`（P-02）、`見込み.将来の所得・加入`（P-03）、`計画.申告の方法と時期`（P-04）、`見積り.親族の合計所得金額`（P-05）、`見積り.補塡の見込額`（P-05） |
| `choices` | `選択.扶養の所属`（C-01）、`選択.配偶者の記載`（C-02）、`選択.医療費控除かセルフメディケーション税制か`（C-03）、`選択.保険料控除の区分`（C-04）、`選択.寄附金の控除の方式`（C-05）、`選択.前納した社会保険料の控除の年分`（補。2026-11-12）、`選択.株式等の申告`（C-06）、`選択.現金主義（業務に係る雑所得）`（C-07）、`選択.消費税等の経理方式`（C-08）、`選択.減価償却`（C-09）、`選択.不動産所得の計上`（C-10）、`選択.円換算の方法`（C-11）、`選択.損失申告と繰戻し`（C-12）、`選択.還付申告`（C-13）、`選択.特定支出控除`（補。2026-11-12）、`選択.住民税の申告`（C-14）、`選択.ワンストップ特例`（C-15）、`選択.夫婦共同扶養の届出`（C-16）、`選択.国民年金の免除の申請`（C-17）、`選択.様式への割当て`（C-18）、`選択.被扶養者の届出`（C-20）、`選択.所得控除の順序`（補。2026-11-12） |

## 4. 検査器が解釈する JSON Schema の部分集合

`type`、`required`、`properties`、`additionalProperties`、`enum`、`const`、`items`、`minItems`、`minimum`、`maximum`、
`pattern`、`format`（`date` だけ）、`$defs`（根だけ）、`$ref`（`#/$defs/<名前>` だけ）、`oneOf`。
注釈の `$schema`・`$id`・`$comment`・`title`・`description` は読み飛ばす。スキーマとして `false`（その場所に値を置けない）と `{}`（何でもよい）を使える。
これ以外のキーワードがあるスキーマは `check_schema` が問題にし、`evaluate` は `SchemaError` を送出する（黙って無視しない）。

仕様より厳しい・違う点：

- `integer` は Python の `int` だけ（`bool` と `float` を拒否。`1.0` も拒否）。`number` は有限の数だけ（このスキーマでは使わない）。
- 文字列にサロゲートの符号位置があれば拒否する（UTF-8 で書き出せない）。
- `format: date` を検査として扱う：`YYYY-MM-DD` の形で実在する日付だけ（`20260210` のように Python の `fromisoformat` が受け付ける形も拒否）。
- `pattern` は `re.ASCII` で照合し、文字クラスの外の `$` を `\Z` に置き換える（Python の `$` は末尾の改行の直前にも合うため）。ECMA-262 と Python の共通部分だけを使う前提。
- `oneOf` の枝がどれも直下の `kind` を `const` で決めているときは、`kind` の合う枝だけを評価する（結果は同じ）。合う枝が無ければ `unknown_kind`。
- `type` が合わない値には、ほかのキーワードの問題を重ねて出さない。

意味の検査は、スキーマの検査が `$ref` で通った名前つきの定義（`ref_person`、`ref_record`、`ref_kind_<kind>`、`period`、`datetime`、`ratio` など）の注釈を使う。
注釈は `oneOf` で選ばれた枝のものだけを残す。

## 5. 問題の code

| code | 意味 |
|---|---|
| `type`・`required`・`additional_property`・`enum`・`const`・`min_items`・`minimum`・`maximum`・`pattern`・`format`・`forbidden`・`invalid_key`・`invalid_string` | スキーマの各キーワードの違反 |
| `unknown_kind`・`one_of_none`・`one_of_multiple` | `oneOf` の違反（知らない種類、どの形にも合わない、複数に合う） |
| `unsupported_schema_version` | 版が `"0"` でない |
| `duplicate_id` | 人と記録の id が重複（全部の配列をまとめて一意） |
| `unknown_person` | 役割・対象などの人が `persons` にない |
| `unknown_reference`・`reference_kind_mismatch` | 参照先の記録がない・配列や kind が違う（例：補塡の対象が医療費の支払でない） |
| `period_reversed` | 区間の `to_on` が `from_on` より前 |
| `invalid_datetime` | 形は合うが実在しない日時 |
| `ratio_out_of_range` | 割合が 1 を超える |
| `death_before_birth` | 死亡日が生年月日より前 |
| `same_person` | 関係の両側・判断の対象の人・被扶養者と被保険者が同じ人 |
| `dependent_without_insured`・`unexpected_insured_person` | 医療保険の被扶養者の資格に被保険者がない・被保険者本人の資格に被保険者を書いた |
| `retroactive_without_original_due_on`・`commuting_exceeds_gross`・`commuting_stated_exceeds_allowance` | 給与の支払：差額の追給に元の支給日がない・通勤手当が総支給額を超える・非課税通勤費の記載が通勤手当と現物の定期券の合計を超える |
| `commuting_km_required`・`parking_field_required` | 通勤の状況：交通用具を使うのに片道の距離がない・駐車場等の料金の単位に応じた欄がない |
| `specific_expense_parts_exceed_amount` | 特定支出の候補の支出：内数（特別の設備の料金・寝台料金）か除く部分（補塡・教育訓練給付金等）の合計が支出金額を超える（2026-11-12）。判断.特定支出の通常の範囲の額 が支出金額を超える（2026-11-12 の2回目） |
| `specific_expense_field_mismatch` | 特定支出の候補の支出：`relocation_item` を転居費でない支出に書いた、通常の範囲の判断を旅費・帰宅旅費・転居費（運賃・宿泊費）でない支出に書いた（2026-11-12 の2回目） |
| `authority_decision_tax_item_mismatch` | 市町村・保険者の個別の処分の種類と税目が合わない（修学中の特例の認定は国民健康保険、住民票と違う市町村での課税は住民税。2026-11-12） |
| `overlapping_interval` | 同じ人の住民票の記録の区間が重なる |
| `replacement_kind_mismatch`・`replacement_fork`・`replacement_cycle`・`replacement_time_order` | 置き換えの連鎖：種類が違う・1つを2つが置き換える・循環・置き換える側の日時が前 |
| `json_syntax`・`json_duplicate_key`・`json_constant`・`json_bom`・`json_not_utf8`・`json_too_deep`・`json_too_large` | `loads` の問題 |
| `schema_error`・`internal_error` | 検査器の側の誤り（同梱のスキーマでは起きないことをテストで確かめている） |

## 6. 語彙の決定と、まだ未決のもの

### 6.1 決定を当てはめたもの

| 事項 | 中間表現での形 | 根拠 |
|---|---|---|
| 消費税等の経理方式は事実か選択か（VOC V-U1・X22） | **選択** `選択.消費税等の経理方式`（売上・固定資産等・棚卸資産等・経費等ごと） | D22（経理方式は選択で、未入力なら両方で評価） |
| 選択が入力されていないときの扱い（VOC V-U2） | 選択の `value` は列挙・真偽で、値の領域を持つ（判定コアが全候補で評価する材料。ライブラリは最適化しない） | D22、D21 R6 |
| 判断の値の領域 | 判断の種類ごとに `value` の型（真偽・列挙・割合など）を決めた | D21 R6、VOC §2 の冒頭 |
| 予測・見積り・計画の区別 | 印 `予測`・`見積り`・`計画`。判断台帳の `見込み.*`・`見積り.*`・`計画.*` は種類で印が決まり必須。事実にも任意で付けられる | D19、D21 R2、D22 S2 |
| 状態（未確定・対象外）と根拠の種類 | 中間表現には置かない（判定コアの出力側） | D22 S2 |
| 医療費の粒度 | 支払1件ごと（支払者・受診者・受診日・支払日）。補塡は給付1件ごとに対象の支払の集合 | D5 改 |
| 補塡の見込額（VOC F-T06 の「確定額／見込額」） | 受け取った補塡は事実 `reimbursement`、まだ確定していない見込額は判断台帳の `見積り.補塡の見込額` に分けた | D21 R2（法令が求める見積り）、VOC P-05 |
| 数の欄 | 金額は整数の円、率は `{num, den}`。float と文字列を置けない | D21 R5、R2 の実測 T11 |
| 選択 → 提出 → 記載（VOC §0.3・X25） | 提出前は `choices`、提出後は `filed_documents`。`realized_choice_ids` で、提出した書類がどの選択を実行したかをつなぐ | VOC §0.3 の案を採った |
| 判断の追記と置き換え | `replaces` の連鎖（追記のみ）。同じ種類だけを置き換え、分岐・循環・日時の逆転を拒否する | D12 |

### 6.2 この実装で決めたこと（VOC にない・VOC の案を変えたもの）

- ID は ASCII（英数字で始まり `_ . : -` を含む64文字まで）。人と全部の記録で一意。
- `business`（業務の登録。期間＝営んだ期間）を足した。`business_id` の書き間違いで業務が黙って分かれないように、参照を検査するため（VOC F-T00 の業務の識別子・F-D11 の業務の開始日の補い）。
- VOC の1行を分けたもの：F-T11 → `casualty`・`casualty_expenditure`、F-D18 → `housing_loan_credit`・`ct_return`（税抜の取得価額は `depreciable_asset`、相手方の登録は `business_expense` の欄）、F-P13 → `national_pension`・`employees_pension`・`pension_entitlement`、F-A07 → `residence_property`（台帳）・`residence_status`（賦課期日の状態）、J-05 → `判断.共済の生計を共にする`・`判断.一時的な別居`。
- 置き場所：F-P16 は `residences`、F-D15（保険の契約）は `assets`、F-D01・F-D02 は `filed_documents` の1つの種類にまとめた。
- 業務の支出の費目 `business_expense.attributes.expense_category`（2026-11-12、様式の担当）：利用者の符号（`code`）から、閉じた語彙
  `vocabulary.EXPENSE_CATEGORIES` にした（`merchandise`・`materials`・`outsourcing`・`tax`・`membership_dues`・`shipping`・`utilities`・`travel`・
  `communication`・`advertising`・`entertainment`・`insurance`・`repairs`・`supplies`・`welfare`・`rent`・`loan_interest`・`interest`・`fees`・
  `management`・`other`・`dividend_debt_interest`。意味は表の説明）。支出が何に使われたかの事実の区分で、必要経費になるか・様式のどの科目かの
  法的な意味は持たない（D3）。決算書・収支内訳書の科目への割当ては判定コアの様式の対応表（`packages/core/src/okura_core/forms/data/r07/割当て/科目.yaml`。
  design-output UO19）が持ち、判定コアは費目ごとの必要経費の額（`所得税.<所得>の必要経費の内訳.<費目>`）を返す。
  閉じた語彙にしたので、表にない符号の中間表現は検査で誤りになる（既存の例・テストの符号は全部表にある。版は "0" のまま：公開前で既存の中間表現の保存がない）。
  `判断.健保の経費の費目` と `選択.様式への割当て`（C-18）の `expense_category` は利用者の符号のまま（どの値でも読める）。
- 置かないもの：F-E01・F-E02（証憑の保存・操作の記録）は記録層の責務。中間表現は SHA-256 で参照するだけ。VOC C-19（届出で事実になる選択）は事実 `brokerage_annual`・`retirement_record` として入る。
- 続柄は記録しない（親子・養子縁組・婚姻・里親委託の出来事から判定コアが導く。VOC §1.2 の注の案）。
- 給与の支給日 `salary_payment.attributes.due_on` は必須（D23 K3。年分は支給日で決まる：所基通36−9）。`when.on` は実際に支給を受けた日（未払なら `unpaid: true` で支給日）。定めがない給与は `due_stipulated: false`。
- 通勤手当の非課税の材料：現物の定期券 `commuting_pass_value`、支払者の区分 `commuting_nontaxable_stated`、区分表示 `commuting_itemized`、対象の月数 `commuting_months`、差額の追給の元の日 `original_due_on`、事実 `commuting_status`（交通手段・片道の距離・駐車場等）、判断 `判断.通勤の合理的な運賃`。源泉徴収票 `withholding_slip` の `includes_prior_payers`（通算した前の支払者）。
- 雑損の損失の金額の材料 `casualty.amounts.post_loss_value`（損失の直後の資産の価額。所令206③ の損失の金額の算定に要る）を足した（2026-11-11。任意）。
- 政党等寄附金特別控除の除外の材料 `donation.attributes.candidate_to_specified_party_branch`（公職の候補者が特定政党支部に対してする寄附か。令和7年法律第2号附則第5条の令和8年分からの除外に要る）を足した（2026-11-11。任意。なければ当たらないものとして扱う）。
- 医療保険の被扶養者は `medical_insurance` の `capacity: dependent` と役割 `insured`（被保険者）で表す。保険者の届出・認定の経過は `insurer_decision`。
  資格の区間（`when`）は `from_on`＝資格を取得した日、`to_on`＝資格を有する最後の日（資格を喪失した日の前日。区間は両端を含む）。保険者は `insurer_id`。
  国民健康保険の世帯は住民票の世帯（`resident_record` の `household_id`・`householder`）で表し、国保の被保険者でない世帯主（擬制世帯主）も
  `householder: true` で書く（擬制世帯主かは判定コアが医療保険の資格から決める）。
- Phase 3 と所得税の「範囲内なのに未対応」の解消に要る語彙（2026-11-11。どれも任意の欄か新しい種類で、版は "0" のまま）：
  - 法令上の性別 `legal_sex`（補。期間つき。寡婦の「夫」の判定などに使う。`docs/hypotheses/20261109_round3_design-vocabulary.md` にない）。
  - 配当等の種類 `dividend.attributes.distribution_type`（剰余金の配当・特定株式投資信託・証券投資信託・外貨建等証券投資信託・投資法人・特定目的会社など。
    配当控除の対象と率の材料：`docs/public-sources/20261111_impl-research_haito-laws-and-nta.md` §2・§3）。
  - 提出した申告書の記載 `reported_amounts.item` に `taxable_retirement_income`（課税退職所得金額）・`taxable_timber_income`（課税山林所得金額）
    （純損失の繰戻しの所令271①）。
  - 事業の識別子 `business_id` を `rental_property`・`loan` に（賃料・物件・借入れと業務の結びつき）。
  - 労働契約 `labor_contract`：`amounts.daily_wage`・`amounts.monthly_commuting_allowance`、`attributes.commuting_allowance_stated`（通勤手当の支給の記載）・
    `commuting_allowance_as_reimbursement`（実費弁償の形の記載）・`bonus_stated`（賞与の支給の記載）・`fixed_term`（労働契約による被扶養者の判定）。
  - 国民年金の免除等 `npi_exemption.attributes.decided_on`（承認・却下の日）。学生納付特例は `exemption_type: student_special`（既存）。
  - 家屋敷課税の材料 `residence_property.attributes.facility_type`（住宅か事務所・事業所か）。
  - 被扶養者の認定の経費の費目 `判断.健保の経費の費目`（補。`business_expense.expense_category`〔利用者の符号〕が、保険者の経費の表の
    どの費目〔注入データ 健保.事業収入から差し引ける経費 の費目の名前〕に当たるか。差し引けるかは判定コアが保険者の運用で決める。§6.3 の未決を解いた）。
  - 既存で足りたもの（確かめた）：加入している制度と保険者（`medical_insurance`・`national_pension`）、国保の世帯（`resident_record`）、
    住所の市町村の区間（`resident_record`・`municipal_tax_domicile`）、仕送り・援助の額（`remittance`・`見込み.援助額`）、
    障害者手帳の種類と等級（`disability_basis` の `basis`・`grade`・`assessment_label`）、事業の識別子（`business`）。
- 所得税・住民税・被扶養者の「語彙がない」対象外を解くための語彙（2026-11-11、共有の担当。どれも任意の欄か新しい種類で、版は "0" のまま。
  法令の区分〔どの号に当たるか〕は判定コアが決め、ここには記載・事実だけを置く。記録層は語彙の表から読むので、取引のメタデータ・事実台帳にそのまま書ける）：
  - 住宅ローン：`housing_loan_credit.attributes.acquisition_category`（計算明細書の特定取得・特別特定取得の記載）。
  - 源泉徴収選択口座の住民税：`brokerage_annual.amounts.dividend_local_tax`（配当割額）・`transfer_local_tax`（株式等譲渡所得割額）。
  - 純損失の前々年分への繰戻し：`選択.損失申告と繰戻し` の `second_prior_year_carryback_amount`、判断 `判断.事業の休止・重要部分の譲渡`（補。所令272①）。
    前々年分の申告の記載は既存の `filed_document`（tax_year）。
  - 給与の支払者の区分：`salary_payment.attributes.payer_withholding_exempt_household`（常時2人以下の家事使用人だけに支払う者）・`paid_outside_japan`・
    `payer_family_company_officer`（同族会社の役員等）・`interest_or_rent_from_payer`（同社からの利子・賃貸料などの受取）。
  - 役員の利益連動の賞与：`salary_payment.attributes.resolution_on`（決議等の日）・`amount_fixed_on`（各人ごとの支給金額が定められた日）。
  - 配偶者の生死不明：`marriage.attributes.spouse_missing.circumstance`（陸海軍・国外・船舶航空機の事故・危難・その他）・`peril_ended_on`。
  - 特別障害者の程度：`disability_basis.attributes.war_injury_class`（戦傷病者手帳の項症・款症）・`certified_severity`（重度か）。
  - 専修学校等の課程：`enrollment.attributes.course_division`・`establisher_type`・`course_certificate`・`establisher_certificate`・`enrollment_certificate`。
  - 災害がやんだ日：`casualty.attributes.disaster_ended_on`、`判断.雑損の計算` の `unavoidable_circumstances`（大規模な災害などのやむを得ない事情）。
  - 夫婦共同扶養の育児休業：事実 `childcare_leave`（補。期間・休業の種類・子）。
  - 健保則第37条の3：`civil_status.attributes.designated_activity`（特定活動の種類）。
  - 奨学金の貸与・給付：`INCOME_TYPE`（`見込み.年間収入` などの種類）に `scholarship_loan`・`scholarship_grant`。
  - ふるさと納税の寄附先：`donation.attributes.recipient_local_government_code`・`recipient_local_government_kind`（判定コアの注入点
    `住民税.特例控除対象寄附金の指定` を引く）、`recipient_type` に `community_chest`（共同募金会）・`japanese_red_cross`（日本赤十字社）。
- 判定コアの各モジュールの「対象外」の行（`packages/core/src/okura_core/rules/<module>/README.md` の表の ID）を解くための語彙（2026-11-12、共有の担当。
  どれも任意の欄か新しい種類・列挙の値で、版は "0" のまま。法令の区分〔どの号に当たるか〕は判定コアが決め、ここには記載・事実・判断・選択だけを置く。
  記録層は語彙の表から読むので、取引のメタデータ・事実台帳・判断台帳にそのまま書ける。`vocabulary.py` の注「補（2026-11-12）」）：
  - 給与（kyuyo）：
    - KY-08 未払のまま支払われなくなった給与：`salary_payment.amounts.uncollectible_amount`（回収できないこととなった金額。所法64①）・
      `attributes.uncollectible_on`（その日）。
    - KY-09 障害者の片道2km未満の自動車通勤の特別の事情：判断 `判断.障害者の通勤の特別の事情`（補。対象は人と支払者 `counterparty`、期間つき。真偽）。
  - 税額・申告（tax）：
    - TX-02 源泉徴収税額の表の当て方：`salary_payment.amounts.prior_month_net_salary`（賞与の前月の社会保険料等控除後の通常の給与等。所法186）・
      `attributes.pay_period`（支給期の区分：`monthly`・`semimonthly`・`ten_days`・`multiple_months`・`daily`・`other`。所法185①）・`pay_period_months`・`pay_period_days`。
    - TX-13 相続人不存在の期限の起算日：事実 `estate_liquidator`（補。相続財産の清算人が確定した日。役割 `decedent`）。
    - TX-19 所得控除を上場株式等の配当所得等・譲渡所得等のどちらから控除するか：選択 `選択.所得控除の順序`（補。`dividends_first`・`transfers_first`。措通31・32共−4）。
    - TX-20 年末調整で控除された住宅借入金等特別控除の額：`withholding_slip.amounts.housing_loan_credit`。
    - TX-25 在日大公使館からの給与：`salary_payment.attributes.paid_by_foreign_mission`（所基通121−5）。
    - 第一表 ㉞・㊴〜㊶ の税額控除（2026-11-12 の2回目。SCOPE §4：住宅借入金等特別控除と同じく外部で計算した額を受け取る）：事実 `external_tax_credit`（補。役割 `person`、
      `when.tax_year`、`amounts.credit_amount`、`attributes.credit_type`・`source_note`）。`credit_type` は計算した控除の種類：`business_income_special`
      （事業所得等の特例に係る税額控除。手引き 3-4_29 の「投資税額等」。合計した額を1件で書く）・`seismic_retrofit`（住宅耐震改修特別控除）・
      `specified_housing_renovation`（住宅特定改修特別税額控除）・`certified_housing_new_build`（認定住宅等新築等特別税額控除）。区分の番号（㉞は 1、
      ㊴〜㊶は 1〜4）への対応と差し引く順序は判定コア（`rules/tax/README.md`、`docs/public-sources/20261112_impl-research6_forms-tax-credits.md`）。
      同じ人・年分・種類は1件（2件以上は判定コアが入力の誤りとして返す：TX-26）。
  - 所得の種類（income_kinds）：
    - IK-11 贈与者が法人か個人か：`windfall_receipt.attributes.donor_type`（`corporation`・`individual`）。
    - IK-21 確定拠出年金の老齢給付金の一時金か：`retirement_payment.attributes.old_age_dc_lump_sum`。
    - IK-23 勤続期間の加算・除外：`retirement_record.attributes.service_adjustments`（`earlier_service_same_payer`・`other_employer_service`・
      `prior_allowance_basis`、期間・`included_in_payment_basis`・`prior_allowance_period`。所令69①一・70①一）。
    - IK-24 役員等勤続期間以外の期間に係る部分：`retirement_payment.amounts.non_officer_portion`。
    - IK-25 退職手当等に当たらないときの収入の種類：`判断.退職の性質` の `income_type`（`salary`・`occasional`）。
    - IK-32（所法56・57 の受取側）：`salary_payment.attributes.payer_business_id`（家族の支払者の業務）、`payroll_paid.attributes.receipt_id`、
      `business_expense.attributes.receipt_id`、`depreciable_asset.attributes.receipt_id`（家族から受けた対価の売上 `business_receipt`）。
    - IK-36・37・69・70・89 支出・資産の結びつき：`business_expense.attributes.rent_flow_id`・`property_id`・`loan_id`、`depreciable_asset.attributes.property_id`。
    - IK-52・56 消費税等の額の業務ごとの内訳：`ct_return.attributes.business_breakdown`（書くなら全部の業務。合計の一致は判定コアが確かめる）。
    - IK-62・63 専従者の従事：`business_engagement.attributes.available_period`（従事できた期間）・`work_share`（二以上の事業に従事したときの割合）。
    - IK-65 償却の方法：`判断.減価償却の区分` の `asset_class`（資産の種類の大きな区分）、`選択.減価償却` の `depreciation_method`（届出で選んだ方法）。
    - IK-66 家族の使用の按分：`判断.按分の割合` の `purpose` に `family_use_share`（業務を営む人が家族に使わせている部分の割合）。
    - IK-72 業務用の資産の損失：`casualty.amounts.salvage_value`（発生直後の発生資材の価額。所基通51−2）。
    - IK-74 相続で承継した業務の青色申告の期限：`blue_return_procedure.attributes.decedent_blue_approved`。
    - IK-78 優良な電子帳簿：`bookkeeping_status.attributes.electronic_books_qualified`。
    - IK-87 少額配当の月数：`dividend.attributes.calculation_period`（配当計算期間）。
    - IK-93 年間取引報告書の源泉徴収税額の内訳：`brokerage_annual.amounts.transfer_withholding_tax`・`dividend_withholding_tax`。
    - IK-99 その他の給付：`benefit_receipt.attributes.benefit_type` に `unpaid_pension_of_deceased`（未支給の年金）・`workers_accident_compensation`
      （労働者災害補償保険の給付）、`unpaid_pension_reason`（元の年金の支給の事由）。
  - 所得控除（other_deductions）：
    - OD-20 前納した社会保険料：`social_insurance_payment.attributes.prepaid_due_dates`（納付期日の全部。日付の配列）、
      選択 `選択.前納した社会保険料の控除の年分`（補。`pro_rata`＝その年中に到来する納付期日の回数で按分・`all_in_paid_year`＝全額を支払った年分。所基通74・75−1(2)・75−2）。
    - OD-28 前納した生命保険料・地震保険料：`insurance_payment.attributes.prepaid_due_dates`（払込期日の全部。所基通76−3(3)・77−7）。
    - OD-31 附帯契約：`insurance_contract.attributes.attached_to_contract_id`（所法76⑩）。
    - OD-32 保険金等の支払の定め：`insurance_contract.attributes.benefit_payment_terms`（所令209①）。
    - OD-41 一部を居住の用に供する家屋：`insurance_contract.attributes.residential_ratio`（所基通77−5・77−6）。
    - OD-42 旧長期損害保険料の要件：`insurance_contract.attributes.maturity_refund`・`contract_changes_on`（変更がなければ空の配列。平成18年法律第10号附則第10条②）。
    - OD-44 受領証等に記載された旨：`donation.attributes.receipt_statement`（所規47の2③）。
    - 医療費通知（医療費控除の明細書の「1 医療費通知に記載された事項」。様式の担当の2回目、2026-11-12）：事実 `medical_expense_notice`（補。役割 `payer`＝支払った人・
      `patient`＝療養を受けた者、when は通知の対象の期間〔療養を受けた年月の最初の日〜最後の日〕、`amounts.notice_amount`＝通知に記載された医療費の額〔自己負担額〕・
      `paid_in_year`＝そのうち `attributes.payment_year` 中に実際に支払った額〔㋐〕・`reimbursed`＝そのうち補塡される金額〔㋑。任意、見込額を含む〕、
      `attributes.issuer`＝保険者等の名称）。1件＝1つの通知の1人の受診者の1つの年分（2つの年分にまたがって支払った通知は年分ごとに2件）。
      所法120④二・所規47の2⑬、手引き「医療費控除の明細書」❶（`docs/public-sources/20261112_impl-research6_forms-iryohi-tsuchi.md`）。
      **二重計上を防ぐ約束**：通知に載った支払は `medical_payment` に書かないか、書くなら `medical_payment.attributes.notice_id`（補）に通知の記録の id を書く
      （判定コアはその支払を明細から除き、通知の ㋐ で数える。手引き ❷「❶に記入したものについては、記入しないでください」）。
      notice_id の通知と支払者・受診者・年が違う・通知に載った支払を対象にする `reimbursement`・`見積り.補塡の見込額`・㋐ が通知の額を超える、は判定コアが
      入力の矛盾（c-入力）として返す（中間表現の検査では止めない）。notice_id を書かずに同じ支払を両方に書くと、判定コアは区別できない。
  - 人的控除（personal_deductions）：
    - PD-05 出国の年の国外転出時課税：判断 `判断.国外転出時課税の対象`（補。年分ごと。真偽。国外転出時課税そのものは範囲外：D22 S11）。
    - PD-06 非居住者の期間の所得：判断 `判断.国内源泉所得の内訳`（補。年分ごと。`non_domestic_income`＝国内源泉所得以外の所得の金額）。
  - 住民税（juminzei）：
    - JM-08 第314条の7第1項第2号の寄附：`donation.attributes.recipient_office_prefecture_code`（寄附を受けた事務所の所在の都道府県の団体コード）・
      `mic_approved_solicitation`（募集に当たり総務大臣の承認を受けたか。地方税法施行令第48条の8・第7条の17）。
    - JM-18 震災特例法・新型コロナ特例法の適用：`housing_loan_credit.attributes.special_acts`（`great_east_japan_earthquake`・`covid19`）。
    - JM-21 申告特例の求めに記載した住所の市町村：`donation.attributes.onestop_request_municipality_code`。
  - 国民健康保険（kokuho）：
    - KH-08・KH-14 第116条・第116条の2 の特例の人：`kokuho_event.attributes.deemed_household_id`（市町村がみなした世帯）・
      `admission_type`（入院・入所・入居の種類：`hospital`・`child_welfare_placement`・`disability_support_facility`・`nozomi_no_sono`・
      `elderly_home_placement`・`long_term_care_facility`・`other`。どの号に当たるかは判定コア）。
    - 国民健康保険組合の被保険者：`medical_insurance.attributes.nhi_association`（行の ID なし。kokuho README の「2026-11-12 の共有の変更」）。
    - 産前産後の減額（KH-04 の材料）：事実 `childbirth`（補。kokunen と同じ記録。出産予定日・出産の日・多胎・出産に係る子 `child_ids`）。
      以前の書き方 `kokuho_event` の `event: childbirth` も読める（新しく書くときは `childbirth`）。
  - 国民年金（kokunen）：
    - KN-06・KN-22 付加保険料の申出と第89条第2項の納付の申出：事実 `npi_application`（補。`application_type`：`additional_premium`・`statutory_exemption_payment`）。
    - KN-12 各種学校の課程の修業年限：`enrollment.attributes.course_length_months`。
    - KN-14 育児期間の免除：`childbirth.attributes.child_ids`、`foster_placement.attributes.foster_parent_type`（`adoptive_foster_parent`・`other`）、
      事実 `special_adoption_petition`（補。特別養子縁組の成立の請求。役割 `petitioner`・`child`、期間）。
    - KN-15 国民年金基金の加入員の期間：`insurance_memberships` の `national_pension_fund`（補。`fund_id`）。
    - KN-16 障害の年金の受給権者が障害状態に該当しなくなった日：`pension_entitlement.attributes.disability_state_ended_on`。
    - KN-17 学生納付特例対象校一覧の教育施設：`enrollment.attributes.npi_student_school_listed`（日本年金機構の一覧に記載されているか）。
    - KN-20 障害基礎年金・厚生年金保険以外の障害の給付：`pension_entitlement.attributes.scheme` に `workers_accident_compensation`（労災の年金）・
      `corporate_pension`（企業年金）、`disability_grade`（決定通知書等に記載された障害等級 1〜3。整数）。共済の障害の年金の種類
      `mutual_aid_disability_kind`（`disability_employees_pension` 障害厚生年金・`disability_mutual_aid_pension` 障害共済年金・`old_law_disability_pension` 旧法の障害年金。
      国年令第6条の5第1項第1号と第6号を分ける。2026-11-12 の2回目）。
  - 所得の種類（income_kinds）の2回目（2026-11-12）：
    - IK-103 鉱業用減価償却資産・鉱業権・国外リース資産：`判断.減価償却の区分` の `asset_class` に `mining_asset`・`mining_right`・`foreign_lease_asset`
      （記録された資産は判定コアが対象外にする。償却の式の材料の語彙は足していない）。
  - 所得の種類（income_kinds）の5回目（2026-11-12）：
    - IK-112 割増償却・特別償却（租税特別措置法 第10条の3〜第15条。SCOPE §5.2 の減価償却の範囲）：事実 `special_depreciation`（補。外部で計算した値：住宅借入金等特別控除と同じく
      判定コアは限度額を計算しない。役割 `owner`、`when.tax_year`、`amounts.amount`＝その年分の割増・特別償却の額〔普通償却費を除く・事業専用割合を掛ける前〕、
      `attributes.asset_id`＝資産、`article`＝適用を受けた条〔e-Gov の条の番号の形 10_3 など。その年分の版の番号〕、`method`＝`special`（特別償却）・`extra`（割増償却）、
      `shortfall_carryover`＝前年分の償却不足額の翌年分への繰越の額か、`source_note`）。前年以前に適用を受けた年分も1件ずつ書く（未償却残高に要る）。同じ資産・年分は1件。
      青色申告書を提出する個人の要件・所得の種類・第19条（複数の規定の不適用）は判定コアが確かめる（`docs/public-sources/20261112_impl-research7_tokubetsu-shokyaku.md`）。
  - 所得の種類（income_kinds）の4回目（2026-11-12）：
    - IK-108 棚卸資産の売上原価（所法47・37①、所令99〜102）：事実 `inventory_count`（補。棚卸しの基準の日・業務・評価の方法 `valuation_method`〔所令99①一イ〜ヘと99の2 の承認の方法〕・
      低価法か `lower_of_cost`・所令100① の区分 `asset_class`・期末か期首か `count_type`・評価額 `amounts.valuation`）、事実 `inventory_method_notice`（補。評価の方法の届出・
      変更の承認の申請と処分・特別な方法の承認：`procedure`・`method`・`lower_of_cost`・`asset_class`）、判断 `判断.棚卸資産の有無`（補。業務・年分ごと。偽なら期末の棚卸高は0）。
      どの評価の方法がその年分に当たるか（届出の期限・みなし承認・青色申告の承認）は判定コアが決める。
    - IK-109 家事消費・贈与（所法39・40①一）：事実 `household_consumption`（補。`normal_sales_price`・`recorded_amount`・`acquisition_cost`、`event`：household_use・gift）。
    - IK-110 貸倒れ（所法51②④・所令141・所法64①）：事実 `bad_debt`（補。役割 `creditor`、on は貸倒れの事実が生じた日、`event`〔所基通51−11〜13 と所令141 の事由〕・
      `receivable_type`・その債権の収入金額を算入した年分 `revenue_tax_year`）。事業か業務か・どの条を当てるかは判定コアが決める。
    - 例 `examples/valid/10_inventory_household_bad_debt_2026_11_12.json`。`tests/test_robustness.py` の乱数の入れ替えは JUNK の値の写しを入れるようにした（例を足して乱数の並びが変わり、
      テストの道具 `_paths` が自分を含む list で止まらなくなったため。validate の扱いは変えていない）。
  - 被扶養者（hifuyosha）：
    - HF-04 夫婦共同扶養で一方が国保のときの比較：事実 `income_certificate`（補。課税〔非課税〕証明書の記載：`total_income`・`fiscal_year`・`issuer`。when は発行日）。
    - HF-08 窓の例外：判断 `判断.収入が基準額以上とならないことが明らか`（補。when は判定日。真偽）。
  - 給与所得（kyuyo。2026-11-12 の impl-research8）：
    - KY-11 特定支出控除（所法57の2）：事実 `specific_expense`（補。役割 `payer`、on は支出した日。支出金額 `amount`、補塡される部分のうち非課税 `reimbursed_nontaxable`、
      教育訓練給付金等 `training_benefit`、内数の特別の設備の料金 `special_seat_fee`・寝台料金 `sleeper_fees`、通勤の定期乗車券等の価額の合計 `commuter_pass_value`、
      区分 `category`〔10〕、証明をした者 `certified_by`、`education_training`・`air_travel`・`transfer_on`・`attributed_year`）と、選択 `選択.特定支出控除`（補。年分。真偽：
      申告書等の記載と明細書・証明書の添付〔所法57の2③〕）。法令の区分・上限・除く部分は判定コアが決める。人の判断の結果（最も経済的かつ合理的な経路によらない部分など）は
      amount に含めない約束（docs/hypotheses/20261112_impl-research8_tokutei-shishutsu-reading.md H5。ユーザーに確認）。台帳の取引ではなく事実台帳に書く（VOC の F-T の番号がない）。
    - `authority_decision` の税目 `tax_item`（必須：`resident_tax`・`national_health_insurance`）：減免（reduction_approved）は住民税（地方税法第323条・第45条）と国保の両方にある。
      所得税は国税で処分をするのが税務署長なので入れない（H8）。意味の検査：修学中の特例の認定は国保、住民票と違う市町村での課税は住民税だけ
      （`authority_decision_tax_item_mismatch`）。既存の記録は tax_item を足して直す（記録層の例は事実台帳の `correct` の行で直した）。
    - 例 `examples/valid/12_specific_expense_and_authority_tax_item_2026_11_12.json`、無効な例 `examples/invalid/authority_decision_tax_item_mismatch.json`。
    - **2026-11-12 の2回目（KY-13・juminzei JM-41）**：上の「amount に含めない約束」を改めた。`amount` は実際の支出金額を書き、旅費・帰宅旅費の
      「最も経済的かつ合理的と認められる通常の経路及び方法」による部分、転居の運賃（通常必要であると認められる額）・宿泊費（著しく超える部分を除く）は
      人の判断 `判断.特定支出の通常の範囲の額`（補。subject は specific_expense の `record_id`、when なし、値 `{countable_amount: 円}`：所令167の3②③⑤。D4）に持つ。
      判断がなければ判定コアは支出金額の全部と0の両端で評価する（D21 R6）。転居費の支出の別 `relocation_item`（任意：`fare`・`vehicle`・`lodging`・`moving`。
      所令167の3③一〜四。燃料費・運送の費用は判断が要らない）を足した。意味の検査：`relocation_item` は転居費だけ、判断は旅費・帰宅旅費・転居費（運賃・宿泊費）の
      支出だけ（`specific_expense_field_mismatch`）、`countable_amount` は amount 以下（`specific_expense_parts_exceed_amount`）。
      `選択.住民税の申告` の `specific_expense_deduction`（地方税法第313条第11項）は juminzei が読むようになった（語彙は変えていない）。
      例 `examples/valid/13_specific_expense_judgment_and_resident_return_2026_11_12.json`、無効な例 `examples/invalid/specific_expense_judgment_mismatch.json`。
- 団体コードは6桁の数字の形だけを検査する。例では実在しない `99` で始まるコードを使う。
- 列挙の値の多く（給付の種類、施設の種類、帳票の欄の区分など）は VOC の「中身」の列から作った案で、様式・通達の語との対応は確かめていない。
  医療費の種類 `medical_kinds` の17は `docs/hypotheses/20261109_impl-prep_iryohi-model.md` H3 の案。

### 6.3 まだ未決のもの

| 事項 | 版 0 での扱い |
|---|---|
| 未提出の選択に付ける印（design-output UO2） | 選択は印を持たない。判定コアの出力でどう扱うかは未決 |
| 続柄を事実として持つか、出来事から導くか（VOC X20） | 出来事から導く案で作った。戸籍の続柄の記載を事実として足すかは未決 |
| 健保の「同一の世帯」の区分（VOC X21、R4 U3） | 判断 `判断.健保の同一の世帯`（判断に使った基準の欄つき）。事実か注入にするかは未決 |
| 大口株主等を事実とするか判断とするか（VOC X28） | 判断 `判断.大口株主等` |
| 年間収入の見込みに総額だけを許すか（〈KEN〉UK2） | `income_type: "unspecified"` で総額だけも書ける |
| 提出後に変えられない選択の変更を入力の誤りにするか（design-output UO17） | 中間表現の検査では止めない |
| シナリオで変えてよいもの（design-output UO13） | 中間表現はシナリオを持たない。差分は `$defs/judgment`・`$defs/choice` の形を使う想定（判定コアの入力の形） |
| 1人が同じ年分に2つの扶養所属・2つの健保の被扶養者（R4 H1.1・U9） | 法令の判断なので中間表現では検査しない（判定コア） |
| 寡婦などの判定に性別の事実が要るか | 2026-11-11 に `legal_sex`（補）を足した。VOC には語彙がない |
| 保険者の費目の名前と `business_expense.expense_category` の対応 | 2026-11-11 に判断 `判断.健保の経費の費目` を足した（§6.2）。費目の名前の語彙そのもの（保険者ごとの表の名前の揺れ）は統一していない |
| 団体コードの一次情報 | `docs/public-sources` に記録がない（TODO）。検査数字の検査はしない |
| VOC の concepts・conflicts の文書（V-U4） | 作られていない。X 番号の多くは中身が分からない（VOC §5.4） |
| 配列の要素の数の上限 | スキーマに `maxItems` を置いていない（入力の上限は `loads` の 16 MiB だけ）。判定コアは `evaluate` の入口で、検査の前に人 2,000 人・記録・判断・選択の合計 20,000 件の上限を確かめる（`packages/core/README.md` §3。仮の値）。検査の時間は要素の数に比例する（置き換えの連鎖の循環の検査も、以前の3乗の実装を直した。2万件の連鎖で約 14 秒〔判定コアのコマンド全体〕、給与の記録 5 万件・9.6 MB で約 30 秒：2026-11-11 のレビューで計測） |
| `salary_payment` の `gross` の意味 | 総支給額（VOC F-T01）。通勤手当 `commuting_allowance` は内数（超えれば `commuting_exceeds_gross`）、現物の定期券 `commuting_pass_value` は外数。非課税の部分は判定コアが通勤の状況などから計算する（`packages/core/src/okura_core/rules/kyuyo/README.md`） |

### 6.4 計算に使わない種類（2026-11-12）

記録してよいが、判定コアのどの規則モジュールも使わない種類（と書類の種別）。判定コアはこれらを「未対応」の対象外にしない
（`okura_core.scope.input_scope`・`not_alive_items` が `vocabulary.NOT_USED_IN_CALCULATION`・`NOT_USED_IN_CALCULATION_VALUES` を読み、結果にも出さない。
2026-11-12 に実装した：`scope.not_used_in_calculation`。以前は申し送りで、入力にあると「未対応」で返していた）。
語彙のほかの種類は全部、どれかの規則モジュールが使う（`packages/core/tests/test_vocabulary_coverage.py` がこの表・定数・登録を突き合わせる）。
この表に足すのは、法令上の役割を一次情報で確かめて「計算に使う規則がない」と言える種類だけ（実装していないだけの種類は足さない。D24③）。

| 種類 | 計算に使わない理由 | 根拠 |
|---|---|---|
| `care_level`（F-P11） | 介護保険法の要介護認定を受けただけでは障害者控除の対象にならない。税の障害者の判定は市町村長等の認定（`disability_basis`）で行う。被扶養者・国保・国年の規則も要介護度を使わない | `docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md` §1.5（所令10 に要介護認定は出てこない）・§1.8（No.1185）・§1.9 |
| `見込み.将来の所得・加入`（P-03） | 将来の年度の保険料のための今年の所得の見込みは、判定コアではその年分の **予測の印つきの事実**（給与の支払などに `"mark": "予測"`）で受け、年度 F の値を年分 F−1 の事実から計算して「予測」の印を結果まで伝える（D19）。この種類の値は所得の種類ごとの額（収入か所得かを決めていない）と加入の変更の文で、法令の所得金額・資格の区間に換算できない。見込みの作り方は利用アプリの責務（SCOPE §4）。利用アプリの記録として残す（**ユーザーに確認**：D19 の「見込みを判断として受け取る口」をこの種類にも持たせるか） | `docs/hypotheses/20261109_round2_kokuho-core-vs-injected.md`（将来の年度の保険料の見込み → 見込みの印を結果まで伝える）、SCOPE §4 |
| `filed_document` の `document_type: basic_deduction_declaration`（給与所得者の基礎控除申告書） | 年末調整（所法190）の基礎控除のための書類で、確定申告の計算・扶養の所属（所令218① の申告書等に入らない）・住民税の扶養の所属（地令46の5① の書類に入らない）に役割がない。配偶者控除等・特定親族特別控除の申告書は別の種別で使う | `docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md` §3（`packages/core/src/okura_core/rules/personal_deductions/README.md` §4.2） |

## 7. ファイル

```
packages/ir/
  README.md
  src/okura_ir/
    __init__.py            公開する名前
    problem.py             Problem と path の書き方
    jsonschema_subset.py   部分集合の解釈器（evaluate・check_schema）
    jsonio.py              loads
    validate.py            validate（スキーマの検査＋意味の検査）・load_schema
    vocabulary.py          語彙の表（スキーマの元）
    build_schema.py        表から schema/ir.schema.json を作る
    schema/ir.schema.json  中間表現の約束（生成物。直接編集しない）
    examples/valid/        有効な例（架空の家庭）
    examples/invalid/      無効な例と expected.json（期待する code と path）
  tests/                   unittest
```

有効な例（どれも架空の家庭）：

| ファイル | 場面 |
|---|---|
| `01_student_away_and_parent_on_assignment.json` | 別居の大学生と単身赴任の親。仕送り・生計を一にする判断・扶養の所属の選択と提出した扶養控除等申告書 |
| `02_medical_payer_differs_from_patient.json` | 医療費の支払者と受診者が別（同居の親の入院を子が払う）。補塡・補塡の見込額（印 `見積り`）・医療費の範囲の判断 |
| `03_business_with_household_apportionment.json` | 事業収入と家事按分の判断（置き換えの連鎖つき）、専従者、減価償却資産、経理方式の選択 |
| `04_forecast_and_plan_marks.json` | 印つきの入力：将来の受取（`予測`）、年間収入の見込み（`予測`）、申告の計画（`計画`） |
| `05_commuting_and_withholding_slip.json` | 支給日（`due_on`）と支払日が違う給与、未払、差額の追給、通勤の状況（交通用具・駐車場）、合理的な運賃の判断、給与の源泉徴収票 |
| `06_phase3_insurance_and_resident_tax_facts.json` | 共済の被保険者と被扶養者（資格の喪失と国保への加入）、国民年金の種別、法令上の性別、障害者手帳、労働契約の記載、学生納付特例の承認、配当等の種類、貸室の業務、住宅、課税退職所得金額の記載（2026-11-11） |
| `07_vocabulary_additions_2026_11_11.json` | 2026-11-11 に足した語彙：配偶者の生死不明の事由、特定活動、育児休業等、専修学校の課程と証明書、戦傷病者手帳の項症、役員の利益連動の賞与の決議日と支払者の区分、災害がやんだ日、ふるさと納税の寄附先の団体コード、日本赤十字社、年間取引報告書の住民税の額、住宅ローンの特定取得、奨学金の貸与・給付、前々年分への繰戻し |
| `08_vocabulary_additions_2026_11_12.json` | 2026-11-12 に足した語彙：国保組合、国民年金基金、労災・企業年金の受給権と障害等級・障害状態でなくなった日、各種学校の修業年限と学生納付特例対象校一覧、国保の特例のみなし世帯と入院等の種類、出産・特別養子縁組の請求・養子縁組里親、付加保険料の申出、課税証明書、専従者の従事できた期間と割合、回収できない未払の給与・賞与の前月の給与・支給期・在日大公使館、家族への報酬・賃料の受取側の記録との結びつき、物件・借入れとの結びつき、前納の納付期日・払込期日、共同募金会の事務所の都道府県と総務大臣の承認・受領証の記載・申告特例の市町村、発生資材の価額、退職手当の勤続期間の加算と役員以外の部分、配当計算期間、法人からの贈与、未支給年金・労災の給付、源泉徴収票の住宅借入金等特別控除の額、相続の青色申告、優良な電子帳簿、年間取引報告書の税額の内訳、特例法の適用、消費税の業務ごとの内訳、清算人の確定、附帯契約・支払の定め・満期返戻金・居住割合、判断（国外転出時課税・国内源泉所得の内訳・障害者の通勤・収入の見込みの例外・家族の使用の割合・資産の種類・退職手当でない収入の種類）、選択（前納の按分・所得控除の順序・償却の方法） |
| `11_special_depreciation_2026_11_12.json` | 2026-11-12 に足した割増償却・特別償却の額（`special_depreciation`。外部で計算した値）：青色申告者の機械の特別償却（第10条の3。令和7年分）と、翌年分への償却不足額の繰越（令和8年分） |
| `12_specific_expense_and_authority_tax_item_2026_11_12.json` | 2026-11-12 に足した語彙：特定支出の候補の支出（通勤の定期券〔年分を分けた〕・転居・キャリアコンサルタントの証明の資格取得・図書・帰宅旅行の寝台料金）、選択.特定支出控除、住民税の減免の承認（`tax_item`） |
| `13_specific_expense_judgment_and_resident_return_2026_11_12.json` | 2026-11-12 の2回目に足した語彙：特定支出の通常の範囲の判断（旅費の遠回りの経路・転居の宿泊費）、転居費の支出の別（宿泊費・燃料費）、所得税で特定支出控除を受けず住民税の申告書で受ける選択（`選択.住民税の申告` の `specific_expense_deduction`） |
| `09_external_tax_credit_2026_11_12.json` | 2026-11-12 に足した外部で計算した税額控除（`external_tax_credit`）：事業所得等の特例に係る税額控除（投資税額等）、住宅耐震改修特別控除と住宅特定改修特別税額控除（同じ人の2種類）、認定住宅等新築等特別税額控除 |

## 8. テストの動かし方

リポジトリの根で、判定コアと記録層の両方の仮想環境で動かす（どちらでも通ること）。

```
.work/venvs/core/Scripts/python.exe    -I -X utf8 -m unittest discover -s packages/ir/tests -t packages/ir
.work/venvs/records/Scripts/python.exe -I -X utf8 -m unittest discover -s packages/ir/tests -t packages/ir
```

テストの中身：部分集合の各キーワードの解釈（`test_keywords.py`）、例（`test_examples.py`。`examples/valid/` の `.json` を全部拾うので、例を足してもテストは直さない）、意味の検査（`test_semantic.py`）、
スキーマのファイルの性質（語彙の表と一致・部分集合だけ・数の欄は上下限つきの整数・pattern は `^…$`、`test_schema_file.py`）、
`loads`（`test_jsonio.py`）、壊れた入力で例外を出さないこと（`test_robustness.py`）。

## 9. 語彙を変える手順

1. `src/okura_ir/vocabulary.py` を直す（VOC の ID を `vocab` に書く。VOC にないものは「補」）。
2. `packages/ir` で `<python> -I -X utf8 -m okura_ir.build_schema --write` を実行して `ir.schema.json` を作り直す（`--check` は一致の確認だけ）。
3. 例とテストを直し、両方の仮想環境でテストを通す。
4. 既存の中間表現を読めなくする変更（欄の削除・名前の変更・必須の追加）では `SCHEMA_VERSION` を上げ、判定コアと記録層の担当に知らせる。
