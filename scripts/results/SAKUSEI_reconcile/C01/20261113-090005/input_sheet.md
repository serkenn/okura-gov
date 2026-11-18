# 作成コーナーに入れる内容：C01 白色申告の事業所得（デザイン業）：収支内訳書、国民年金・国保

- 年分：2025年分（令和7年分）。申告者：架空 白男（本人）（p-1）
- **架空の家庭。** 氏名・住所などは下の架空の値だけを使う。個人番号は入れない。提出方法は「書面」を選び、e-Tax に送信しない。

## 確かめたいこと

- 収支内訳書（一般用）の経費の科目と所得金額
- 事業所得の報酬の源泉徴収税額（第二表の所得の内訳）
- 社会保険料控除（国民年金・国民健康保険）
- 基礎控除の特例（合計所得 336万円以下）

## 人

| ID | 呼び名 | 生年月日 | 年末の年齢 |
|---|---|---|---|
| p-1 | 架空 白男（本人） | 1985-04-04 | 40 |

## 作成コーナーだけで要る記載（中間表現にない、書類に印字された値など）

| 項目 | 値 | 注 |
|---|---|---|
| 報酬の支払調書・受取 | 架空出版 1,100,000（源泉 112,310）、架空工房 1,500,000（源泉なし）、架空商店 1,000,000（源泉なし） | 業種：デザイン業 |
| 経費 | 通信費 120,000、消耗品費 80,000、旅費交通費 60,000 | すべて業務用（按分なし） |
| 社会保険料 | 国民年金保険料 210,120、国民健康保険料 250,000 |  |
| 住所・氏名など | 架空の値（実在しない番地。電話番号は入れない） | 計算に関係しない |

## residences

- `res-1` resident_record（住民票の記録）
  - 役割：person=架空 白男（本人）（p-1）
  - 時：from_on=2015-04-01
  - 属性：municipality_code=990001、household_id=hh-1、householder=True、relation_to_householder=householder

## facts

- `biz-1` business（業務（業務の識別子と、営んだ期間））
  - 役割：owner=架空 白男（本人）（p-1）
  - 時：from_on=2020-04-01
  - 属性：description=架空デザイン業
- `f-books` bookkeeping_status（帳簿と届出の状態）
  - 役割：person=架空 白男（本人）（p-1）
  - 時：tax_year=2025
  - 属性：business_id=biz-1、bookkeeping_method=simplified
- `f-rc-1` business_receipt（業務の売上・報酬の受取）
  - 役割：recipient=架空 白男（本人）（p-1）
  - 時：on=2025-03-31
  - 金額：amount=1,100,000、withholding_tax=112,310
  - 属性：business_id=biz-1、counterparty=架空出版、contract_document=service_contract、incurred_on=2025-03-15
- `f-rc-2` business_receipt（業務の売上・報酬の受取）
  - 役割：recipient=架空 白男（本人）（p-1）
  - 時：on=2025-07-31
  - 金額：amount=1,500,000、withholding_tax=0
  - 属性：business_id=biz-1、counterparty=架空工房、contract_document=service_contract、incurred_on=2025-07-10
- `f-rc-3` business_receipt（業務の売上・報酬の受取）
  - 役割：recipient=架空 白男（本人）（p-1）
  - 時：on=2025-11-28
  - 金額：amount=1,000,000、withholding_tax=0
  - 属性：business_id=biz-1、counterparty=架空商店、contract_document=service_contract、incurred_on=2025-11-10
- `f-ex-1` business_expense（業務の支出・家事関連費の支出（全額で記録する））
  - 役割：payer=架空 白男（本人）（p-1）
  - 時：on=2025-12-25
  - 金額：amount=120,000
  - 属性：business_id=biz-1、expense_category=communication、counterparty=架空通信
- `f-ex-2` business_expense（業務の支出・家事関連費の支出（全額で記録する））
  - 役割：payer=架空 白男（本人）（p-1）
  - 時：on=2025-06-10
  - 金額：amount=80,000
  - 属性：business_id=biz-1、expense_category=supplies、counterparty=架空文具
- `f-ex-3` business_expense（業務の支出・家事関連費の支出（全額で記録する））
  - 役割：payer=架空 白男（本人）（p-1）
  - 時：on=2025-09-05
  - 金額：amount=60,000
  - 属性：business_id=biz-1、expense_category=travel、counterparty=架空鉄道
- `f-np` social_insurance_payment（社会保険料の支払）
  - 役割：payer=架空 白男（本人）（p-1）、liable_person=架空 白男（本人）（p-1）
  - 時：on=2025-12-26
  - 金額：amount=210,120
  - 属性：premium_type=national_pension
- `f-nhi` social_insurance_payment（社会保険料の支払）
  - 役割：payer=架空 白男（本人）（p-1）、liable_person=架空 白男（本人）（p-1）
  - 時：on=2025-12-26
  - 金額：amount=250,000
  - 属性：premium_type=national_health_insurance

## judgments

- `j-scale` 判断.事業と称するに至る程度（事業と称するに至る程度か）
  - subject：person=架空 白男（本人）（p-1）、business_id=biz-1
  - judged_by：person=架空 白男（本人）（p-1）
  - 時：tax_year=2025
  - 値：true
- `j-homework` 判断.家内労働者等（家内労働者等に当たるか）
  - subject：person=架空 白男（本人）（p-1）
  - judged_by：person=架空 白男（本人）（p-1）
  - 時：tax_year=2025
  - 値：false
- `j-rel-1` 判断.業務関連性（支出が業務に関連するか）
  - subject：record_id=f-ex-1
  - judged_by：person=架空 白男（本人）（p-1）
  - 値：true
- `j-rel-2` 判断.業務関連性（支出が業務に関連するか）
  - subject：record_id=f-ex-2
  - judged_by：person=架空 白男（本人）（p-1）
  - 値：true
- `j-rel-3` 判断.業務関連性（支出が業務に関連するか）
  - subject：record_id=f-ex-3
  - judged_by：person=架空 白男（本人）（p-1）
  - 値：true

