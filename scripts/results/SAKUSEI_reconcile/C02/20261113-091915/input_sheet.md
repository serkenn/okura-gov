# 作成コーナーに入れる内容：C02 青色申告の事業所得（翻訳業）：書面提出の青色申告特別控除55万円、青色申告決算書

- 年分：2025年分（令和7年分）。申告者：架空 青子（本人）（p-1）
- **架空の家庭。** 氏名・住所などは下の架空の値だけを使う。個人番号は入れない。提出方法は「書面」を選び、e-Tax に送信しない。

## 確かめたいこと

- 青色申告特別控除（正規の簿記・貸借対照表・書面で期限内：55万円）
- 青色申告決算書（一般用）の損益計算書
- 事業所得の報酬の源泉徴収税額と納付額（100円未満の切捨て）
- 基礎控除の特例（合計所得 489万円以下）

## 人

| ID | 呼び名 | 生年月日 | 年末の年齢 |
|---|---|---|---|
| p-1 | 架空 青子（本人） | 1980-10-10 | 45 |

## 作成コーナーだけで要る記載（中間表現にない、書類に印字された値など）

| 項目 | 値 | 注 |
|---|---|---|
| 報酬 | 架空出版 2,000,000（源泉 204,200）、架空商事 2,500,000、架空学院 1,500,000 | 業種：翻訳業 |
| 経費 | 外注工賃 600,000、通信費 150,000、消耗品費 250,000、諸会費 100,000 |  |
| 貸借対照表（作成コーナーの入力用。中間表現にない） | 期首：普通預金 1,000,000／元入金 1,000,000。期末：普通預金 2,000,000、事業主貸 3,900,000／元入金 1,000,000、青色申告特別控除前の所得金額 4,900,000 | 貸借が一致するように作った架空の値 |
| 社会保険料 | 国民年金保険料 210,120、国民健康保険料 400,000 |  |
| 提出 | 書面で期限内（電子申告・優良な電子帳簿ではない） | 65万円の控除の要件に当たらない |
| 住所・氏名など | 架空の値（実在しない番地。電話番号は入れない） | 計算に関係しない |

## residences

- `res-1` resident_record（住民票の記録）
  - 役割：person=架空 青子（本人）（p-1）
  - 時：from_on=2015-04-01
  - 属性：municipality_code=990001、household_id=hh-1、householder=True、relation_to_householder=householder

## facts

- `biz-1` business（業務（業務の識別子と、営んだ期間））
  - 役割：owner=架空 青子（本人）（p-1）
  - 時：from_on=2018-04-01
  - 属性：description=架空翻訳業
- `f-blue` blue_return_procedure（青色申告の手続（on は提出・通知の日））
  - 役割：person=架空 青子（本人）（p-1）
  - 時：on=2018-05-10
  - 属性：procedure=application_filed、first_tax_year=2018、business_start_on=2018-04-01
- `f-books` bookkeeping_status（帳簿と届出の状態）
  - 役割：person=架空 青子（本人）（p-1）
  - 時：tax_year=2025
  - 属性：business_id=biz-1、bookkeeping_method=double_entry、balance_sheet=True、electronic_books_notice=none、electronic_books_qualified=False
- `f-rc-1` business_receipt（業務の売上・報酬の受取）
  - 役割：recipient=架空 青子（本人）（p-1）
  - 時：on=2025-04-30
  - 金額：amount=2,000,000、withholding_tax=204,200
  - 属性：business_id=biz-1、counterparty=架空出版、contract_document=service_contract、incurred_on=2025-04-15
- `f-rc-2` business_receipt（業務の売上・報酬の受取）
  - 役割：recipient=架空 青子（本人）（p-1）
  - 時：on=2025-08-29
  - 金額：amount=2,500,000、withholding_tax=0
  - 属性：business_id=biz-1、counterparty=架空商事、contract_document=service_contract、incurred_on=2025-08-10
- `f-rc-3` business_receipt（業務の売上・報酬の受取）
  - 役割：recipient=架空 青子（本人）（p-1）
  - 時：on=2025-12-19
  - 金額：amount=1,500,000、withholding_tax=0
  - 属性：business_id=biz-1、counterparty=架空学院、contract_document=service_contract、incurred_on=2025-12-05
- `f-ex-1` business_expense（業務の支出・家事関連費の支出（全額で記録する））
  - 役割：payer=架空 青子（本人）（p-1）
  - 時：on=2025-12-25
  - 金額：amount=600,000
  - 属性：business_id=biz-1、expense_category=outsourcing、counterparty=架空校正
- `f-ex-2` business_expense（業務の支出・家事関連費の支出（全額で記録する））
  - 役割：payer=架空 青子（本人）（p-1）
  - 時：on=2025-12-25
  - 金額：amount=150,000
  - 属性：business_id=biz-1、expense_category=communication、counterparty=架空通信
- `f-ex-3` business_expense（業務の支出・家事関連費の支出（全額で記録する））
  - 役割：payer=架空 青子（本人）（p-1）
  - 時：on=2025-10-01
  - 金額：amount=250,000
  - 属性：business_id=biz-1、expense_category=supplies、counterparty=架空文具
- `f-ex-4` business_expense（業務の支出・家事関連費の支出（全額で記録する））
  - 役割：payer=架空 青子（本人）（p-1）
  - 時：on=2025-11-01
  - 金額：amount=100,000
  - 属性：business_id=biz-1、expense_category=membership_dues、counterparty=架空翻訳者協会
- `f-np` social_insurance_payment（社会保険料の支払）
  - 役割：payer=架空 青子（本人）（p-1）、liable_person=架空 青子（本人）（p-1）
  - 時：on=2025-12-26
  - 金額：amount=210,120
  - 属性：premium_type=national_pension
- `f-nhi` social_insurance_payment（社会保険料の支払）
  - 役割：payer=架空 青子（本人）（p-1）、liable_person=架空 青子（本人）（p-1）
  - 時：on=2025-12-26
  - 金額：amount=400,000
  - 属性：premium_type=national_health_insurance

## judgments

- `j-scale` 判断.事業と称するに至る程度（事業と称するに至る程度か）
  - subject：person=架空 青子（本人）（p-1）、business_id=biz-1
  - judged_by：person=架空 青子（本人）（p-1）
  - 時：tax_year=2025
  - 値：true
- `j-homework` 判断.家内労働者等（家内労働者等に当たるか）
  - subject：person=架空 青子（本人）（p-1）
  - judged_by：person=架空 青子（本人）（p-1）
  - 時：tax_year=2025
  - 値：false
- `j-double` 判断.正規の簿記の宣言（正規の簿記で記録・作成している旨）
  - subject：person=架空 青子（本人）（p-1）、business_id=biz-1
  - judged_by：person=架空 青子（本人）（p-1）
  - 時：tax_year=2025
  - 値：true
- `j-rel-1` 判断.業務関連性（支出が業務に関連するか）
  - subject：record_id=f-ex-1
  - judged_by：person=架空 青子（本人）（p-1）
  - 値：true
- `j-rel-2` 判断.業務関連性（支出が業務に関連するか）
  - subject：record_id=f-ex-2
  - judged_by：person=架空 青子（本人）（p-1）
  - 値：true
- `j-rel-3` 判断.業務関連性（支出が業務に関連するか）
  - subject：record_id=f-ex-3
  - judged_by：person=架空 青子（本人）（p-1）
  - 値：true
- `j-rel-4` 判断.業務関連性（支出が業務に関連するか）
  - subject：record_id=f-ex-4
  - judged_by：person=架空 青子（本人）（p-1）
  - 値：true
- `p-file` 計画.申告の方法と時期（申告の方法と時期）
  - subject：person=架空 青子（本人）（p-1）
  - judged_by：person=架空 青子（本人）（p-1）
  - 時：tax_year=2025
  - 値：{"method": "paper", "planned_filing_on": "2026-03-10", "within_deadline": true, "statements_attached": true}

