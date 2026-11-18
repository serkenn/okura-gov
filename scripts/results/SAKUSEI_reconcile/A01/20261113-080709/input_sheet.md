# 作成コーナーに入れる内容：A01 給与所得者の還付申告：医療費控除と、年末調整で受けなかった特定親族特別控除

- 年分：2025年分（令和7年分）。申告者：架空 太郎（本人）（p-1）
- **架空の家庭。** 氏名・住所などは下の架空の値だけを使う。個人番号は入れない。提出方法は「書面」を選び、e-Tax に送信しない。

## 確かめたいこと

- 給与所得（令和7年分の給与所得控除の表、4,000円の区切り）
- 基礎控除の特例（合計所得 489万円以下の区分）
- 配偶者控除・一般の扶養親族（16歳）
- 特定親族特別控除（19〜22歳、合計所得 58万円超 85万円以下の区分）と第二表の記載
- 医療費控除（足切り 10万円）と明細書
- 復興特別所得税・還付の額

## 人

| ID | 呼び名 | 生年月日 | 年末の年齢 |
|---|---|---|---|
| p-1 | 架空 太郎（本人） | 1975-06-10 | 50 |
| p-2 | 架空 花子（配偶者） | 1977-03-03 | 48 |
| p-3 | 架空 一郎（長男・大学生） | 2004-09-15 | 21 |
| p-4 | 架空 次郎（二男・高校生） | 2009-01-20 | 16 |

## 作成コーナーだけで要る記載（中間表現にない、書類に印字された値など）

| 項目 | 値 | 注 |
|---|---|---|
| p-1 の源泉徴収票：給与所得控除後の金額 | 4760000 | 支払者が計算して印字した値（架空） |
| p-1 の源泉徴収票：所得控除の額の合計額 | 2390000 | 社会保険料 950,000＋配偶者控除 380,000＋扶養控除 380,000＋基礎控除 680,000（年末調整で特定親族特別控除を受けなかった） |
| p-1 の源泉徴収票：控除対象配偶者の有無・配偶者（特別）控除の額 | 有・380,000 |  |
| p-1 の源泉徴収票：控除対象扶養親族の数（特定・老人・その他） | 特定 0・老人 0・その他 1 | p-4。p-3 は合計所得が 58万円を超えるので扶養親族でない |
| p-1 の源泉徴収票：16歳未満扶養親族の数 | 0 |  |
| p-1 の源泉徴収票：生命保険料・地震保険料の控除額 | 0 |  |
| p-1 の源泉徴収票：基礎控除の額 | 680000 |  |
| p-1 の源泉徴収票：特定親族特別控除の額 | 0 | 年末調整で受けていない |
| p-1 の源泉徴収票：支払者 | 架空工業株式会社（架空の所在地） |  |
| p-3 の所得の見積額（第二表の特定親族の欄） | 給与収入 1,400,000 円（給与所得 750,000 円） | p-3 の源泉徴収票から |
| 住所・氏名など | 架空の値（実在しない番地・電話番号を使う） | 計算に関係しない |

## relations

- `rel-marriage-12` marriage（婚姻（届出））
  - 役割：spouse_a=架空 太郎（本人）（p-1）、spouse_b=架空 花子（配偶者）（p-2）
  - 時：from_on=2002-04-01
- `rel-parent-13` parentage（親子関係の成立）
  - 役割：parent=架空 太郎（本人）（p-1）、child=架空 一郎（長男・大学生）（p-3）
  - 時：on=2004-09-15
  - 属性：basis=birth_in_marriage
- `rel-parent-23` parentage（親子関係の成立）
  - 役割：parent=架空 花子（配偶者）（p-2）、child=架空 一郎（長男・大学生）（p-3）
  - 時：on=2004-09-15
  - 属性：basis=birth_mother
- `rel-parent-14` parentage（親子関係の成立）
  - 役割：parent=架空 太郎（本人）（p-1）、child=架空 次郎（二男・高校生）（p-4）
  - 時：on=2009-01-20
  - 属性：basis=birth_in_marriage
- `rel-parent-24` parentage（親子関係の成立）
  - 役割：parent=架空 花子（配偶者）（p-2）、child=架空 次郎（二男・高校生）（p-4）
  - 時：on=2009-01-20
  - 属性：basis=birth_mother

## residences

- `res-1` resident_record（住民票の記録）
  - 役割：person=架空 太郎（本人）（p-1）
  - 時：from_on=2010-04-01
  - 属性：municipality_code=990001、household_id=hh-1、householder=True、relation_to_householder=householder
- `res-2` resident_record（住民票の記録）
  - 役割：person=架空 花子（配偶者）（p-2）
  - 時：from_on=2010-04-01
  - 属性：municipality_code=990001、household_id=hh-1、householder=False、relation_to_householder=spouse
- `res-3` resident_record（住民票の記録）
  - 役割：person=架空 一郎（長男・大学生）（p-3）
  - 時：from_on=2010-04-01
  - 属性：municipality_code=990001、household_id=hh-1、householder=False、relation_to_householder=child
- `res-4` resident_record（住民票の記録）
  - 役割：person=架空 次郎（二男・高校生）（p-4）
  - 時：from_on=2010-04-01
  - 属性：municipality_code=990001、household_id=hh-1、householder=False、relation_to_householder=child

## facts

- `f-slip-1` withholding_slip（源泉徴収票・支払調書の記載）
  - 役割：recipient=架空 太郎（本人）（p-1）
  - 時：tax_year=2025
  - 金額：payment_amount=6,500,000、withholding_tax=142,400、social_insurance=950,000、housing_loan_credit=0
  - 属性：slip_type=salary、counterparty=架空工業、year_end_adjusted=True
- `f-slip-3` withholding_slip（源泉徴収票・支払調書の記載）
  - 役割：recipient=架空 一郎（長男・大学生）（p-3）
  - 時：tax_year=2025
  - 金額：payment_amount=1,400,000、withholding_tax=0、social_insurance=0、housing_loan_credit=0
  - 属性：slip_type=salary、counterparty=架空書店、year_end_adjusted=True
- `f-enroll-3` enrollment（在学）
  - 役割：person=架空 一郎（長男・大学生）（p-3）
  - 時：from_on=2023-04-01、to_on=2027-03-31
  - 属性：school_type=school_act_article1、attendance=full_time
- `f-med-1` medical_payment（医療費の支払（on は支払った日））
  - 役割：payer=架空 太郎（本人）（p-1）、patient=架空 次郎（二男・高校生）（p-4）
  - 時：on=2025-07-14
  - 金額：amount=180,000
  - 属性：incurred_on=2025-07-14、provider=架空病院、medical_kinds=["medical_treatment"]
- `f-med-2` medical_payment（医療費の支払（on は支払った日））
  - 役割：payer=架空 太郎（本人）（p-1）、patient=架空 次郎（二男・高校生）（p-4）
  - 時：on=2025-10-06
  - 金額：amount=70,000
  - 属性：incurred_on=2025-10-06、provider=架空病院、medical_kinds=["medical_treatment"]

## judgments

- `j-liv-12` 判断.生計を一にする（生計を一にする）
  - subject：person=架空 太郎（本人）（p-1）、other_person=架空 花子（配偶者）（p-2）
  - judged_by：person=架空 太郎（本人）（p-1）
  - 時：from_on=2002-04-01
  - 値：true
- `j-liv-13` 判断.生計を一にする（生計を一にする）
  - subject：person=架空 太郎（本人）（p-1）、other_person=架空 一郎（長男・大学生）（p-3）
  - judged_by：person=架空 太郎（本人）（p-1）
  - 時：from_on=2004-09-15
  - 値：true
- `j-liv-14` 判断.生計を一にする（生計を一にする）
  - subject：person=架空 太郎（本人）（p-1）、other_person=架空 次郎（二男・高校生）（p-4）
  - judged_by：person=架空 太郎（本人）（p-1）
  - 時：from_on=2009-01-20
  - 値：true

