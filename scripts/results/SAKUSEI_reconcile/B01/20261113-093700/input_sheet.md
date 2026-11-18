# 作成コーナーに入れる内容：B01 年金受給者（70歳）：公的年金、上場株式の配当（総合課税で配当控除）、一般口座の上場株式の譲渡（第三表）

- 年分：2025年分（令和7年分）。申告者：架空 年男（本人）（p-1）
- **架空の家庭。** 氏名・住所などは下の架空の値だけを使う。個人番号は入れない。提出方法は「書面」を選び、e-Tax に送信しない。

## 確かめたいこと

- 公的年金等控除（65歳以上）と公的年金等以外の合計所得金額（56）
- 上場株式の配当の総合課税と配当控除（税額の上限）
- 一般口座の上場株式等の譲渡（申告分離課税）と第三表、所得控除の分離課税への繰り入れ
- 源泉徴収税額の還付

## 人

| ID | 呼び名 | 生年月日 | 年末の年齢 |
|---|---|---|---|
| p-1 | 架空 年男（本人） | 1955-05-05 | 70 |

## 作成コーナーだけで要る記載（中間表現にない、書類に印字された値など）

| 項目 | 値 | 注 |
|---|---|---|
| 公的年金等の源泉徴収票 | 支払金額 1,800,000、源泉徴収税額 18,000、社会保険料の金額（介護保険料）78,000、支払者 架空年金機構 | 種類は厚生年金（老齢） |
| 配当金の支払通知書（一般口座） | 架空電機株式会社、配当金額 200,000、源泉徴収税額（所得税）30,630、配当割額 10,000 | 総合課税で申告する |
| 一般口座の上場株式の譲渡 | 架空化学株式会社、2025-09-12 売却、譲渡価額 1,000,000、取得費 800,000、委託手数料 5,000 | 特定口座ではない |
| 住所・氏名など | 架空の値（実在しない番地。電話番号は入れない） | 計算に関係しない |

## residences

- `res-1` resident_record（住民票の記録）
  - 役割：person=架空 年男（本人）（p-1）
  - 時：from_on=2000-04-01
  - 属性：municipality_code=990001、household_id=hh-1、householder=True、relation_to_householder=householder

## facts

- `f-slip-pen` withholding_slip（源泉徴収票・支払調書の記載）
  - 役割：recipient=架空 年男（本人）（p-1）
  - 時：tax_year=2025
  - 金額：payment_amount=1,800,000、withholding_tax=18,000、social_insurance=78,000
  - 属性：slip_type=public_pension、counterparty=架空年金機構
- `f-div-1` dividend（配当等の受取）
  - 役割：recipient=架空 年男（本人）（p-1）
  - 時：on=2025-06-20
  - 金額：gross=200,000、withholding_tax=30,630、dividend_local_tax=10,000
  - 属性：counterparty=架空電機株式会社、security_class=listed_stock、account_type=other_account、record_date=2025-03-31、distribution_type=surplus_dividend
- `f-sale-1` security_sale（一般口座などの譲渡（on は譲渡日））
  - 役割：seller=架空 年男（本人）（p-1）
  - 時：on=2025-09-12
  - 金額：proceeds=1,000,000、acquisition_cost=800,000、selling_expenses=5,000
  - 属性：security_name=架空化学株式会社、security_class=listed_stock、sale_method=brokered、account_type=other_account
- `f-pen-1` pension_payment（年金の支払）
  - 役割：recipient=架空 年男（本人）（p-1）
  - 時：on=2025-02-14
  - 金額：gross=300,000、social_insurance_withheld=13,000、withholding_tax=3,000
  - 属性：counterparty=架空年金機構、payer_domestic=True、scheme=employees_pension、benefit_reason=old_age、statutory_payment_on=2025-02-14
- `f-pen-2` pension_payment（年金の支払）
  - 役割：recipient=架空 年男（本人）（p-1）
  - 時：on=2025-04-15
  - 金額：gross=300,000、social_insurance_withheld=13,000、withholding_tax=3,000
  - 属性：counterparty=架空年金機構、payer_domestic=True、scheme=employees_pension、benefit_reason=old_age、statutory_payment_on=2025-04-15
- `f-pen-3` pension_payment（年金の支払）
  - 役割：recipient=架空 年男（本人）（p-1）
  - 時：on=2025-06-13
  - 金額：gross=300,000、social_insurance_withheld=13,000、withholding_tax=3,000
  - 属性：counterparty=架空年金機構、payer_domestic=True、scheme=employees_pension、benefit_reason=old_age、statutory_payment_on=2025-06-13
- `f-pen-4` pension_payment（年金の支払）
  - 役割：recipient=架空 年男（本人）（p-1）
  - 時：on=2025-08-15
  - 金額：gross=300,000、social_insurance_withheld=13,000、withholding_tax=3,000
  - 属性：counterparty=架空年金機構、payer_domestic=True、scheme=employees_pension、benefit_reason=old_age、statutory_payment_on=2025-08-15
- `f-pen-5` pension_payment（年金の支払）
  - 役割：recipient=架空 年男（本人）（p-1）
  - 時：on=2025-10-15
  - 金額：gross=300,000、social_insurance_withheld=13,000、withholding_tax=3,000
  - 属性：counterparty=架空年金機構、payer_domestic=True、scheme=employees_pension、benefit_reason=old_age、statutory_payment_on=2025-10-15
- `f-pen-6` pension_payment（年金の支払）
  - 役割：recipient=架空 年男（本人）（p-1）
  - 時：on=2025-12-15
  - 金額：gross=300,000、social_insurance_withheld=13,000、withholding_tax=3,000
  - 属性：counterparty=架空年金機構、payer_domestic=True、scheme=employees_pension、benefit_reason=old_age、statutory_payment_on=2025-12-15

## choices

- `c-div` 選択.株式等の申告（配当・源泉徴収口座の申告の選択）
  - subject：person=架空 年男（本人）（p-1）、record_id=f-div-1
  - chosen_by：架空 年男（本人）（p-1）
  - 時：tax_year=2025
  - 値：{"target": "dividend", "declare": true, "taxation": "aggregate"}
- `c-refund` 選択.還付申告（還付申告をするか）
  - subject：person=架空 年男（本人）（p-1）
  - chosen_by：架空 年男（本人）（p-1）
  - 時：tax_year=2025
  - 値：true

