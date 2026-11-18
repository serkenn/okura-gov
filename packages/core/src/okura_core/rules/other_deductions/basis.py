"""規則モジュール other_deductions の根拠：パラメータでない規則（RULES）と、根拠のある端数処理（HOKEN_CEIL）。

パラメータ（基準額・率）の根拠は evaluate がトレースから足す。ここには、式・数え方・読み（D22 S1 の「法令の読み」）を置く。
"""

from __future__ import annotations

from collections.abc import Mapping

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...rounding import RoundingRule

_IRL = "docs/public-sources/20261109_impl-prep_iryohi-law-text.md"
_IRN = "docs/public-sources/20261109_impl-prep_iryohi-nta-mhlw.md"
_HKL = "docs/public-sources/20261109_round2_hoken-kifu-laws.md"
_HKN = "docs/public-sources/20261109_round2_hoken-kifu-nta-soumu.md"
_HKC = "docs/measurements/20261109_round2_hoken-kifu-formula-checks.md"
_ZG = "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md"
_SK = "docs/public-sources/20261111_impl-research_seito-kifu-laws-and-nta.md"
_KIN = "docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md"
_CON = "docs/public-sources/20261109_R4-modeling_concepts.md"
_KIFU4 = "docs/public-sources/20261112_impl-research4_juminzei-kifu-laws-and-kokuji.md"

#: 生命保険料控除・地震保険料控除の区分ごとの式の1円未満の端数を切り上げる（条文に定めがなく、国税庁の手引きに従う：D21 R5）。
HOKEN_CEIL = RoundingRule(
    name="ceil_yen_hokenryo_kojo_kubun",
    title="生命保険料控除・地震保険料控除の区分ごとの式（二分の一・四分の一）で算出した金額の1円未満の端数を切り上げる",
    function="ceil",
    source_kind=SourceKind.GUIDE_OR_FORM_NOTE,
    law=(
        "条文（所得税法第76条・第77条、租税特別措置法第41条の15の5、平成18年法律第10号附則第10条）に端数の定めはない。"
        "国税庁「令和8年分 年末調整のしかた」p.24 注2・p.26 注3「控除額の計算において算出した金額に1円未満の端数があるときは、"
        "その端数を切り上げます」。確定申告への当てはめと、区分ごとの式の値に当てる（合計に当てない）のは法令の読み"
    ),
    references=(f"{_HKN}#1.6", f"{_HKL}#9", f"{_HKC}#2"),
    flags=(ReadingFlag.LEGAL_READING,),
)

KINSHIP_RULE = BasisEntry(
    type=BasisType.RULE,
    name="「配偶者その他の親族」は民法の親族（6親等内の血族・配偶者・3親等内の姻族）とし、中間表現の親子・養子縁組・婚姻の記録から導く",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="民法第725条〜第729条（所得税法に「親族」の定義はなく、国税庁の説明と最高裁判決が民法の親族と読む）",
    references=(f"{_KIN}#2.2", f"{_KIN}#2.3", f"{_CON}#3.1"),
    flags=(ReadingFlag.LEGAL_READING,),
)

MEDICAL_PAYER_RULE = BasisEntry(
    type=BasisType.RULE,
    name="医療費は、その年中に現実に支払った人が、自己と、受診時又は支払時に生計を一にする配偶者その他の親族の分を控除する",
    source_kind=SourceKind.LAW,
    law="所得税法第73条第1項、所得税基本通達73−1（受診時又は支払時の現況）・73−2（現実に支払った医療費）",
    references=(f"{_IRL}#1", f"{_IRN}#1", f"{_IRN}#7"),
)

MEDICAL_SCOPE_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "所得税法施行令第207条各号に直接当たる支払（診療・治療、入院、助産、喀痰吸引等、移植のあっせん、福祉法の納付金）は"
        "医療費の範囲に入るものとし、目的・必要性で決まる支払（医薬品・健康診断・交通費・器具など）は判断.医療費の範囲で決める"
        "（未入力なら両方で評価）"
    ),
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法施行令第207条、所得税基本通達73−3〜73−7、タックスアンサー No.1122",
    references=(f"{_IRL}#2.1", f"{_IRN}#1", f"{_IRN}#3"),
    flags=(ReadingFlag.LEGAL_READING,),
)

REIMBURSEMENT_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "補塡は給付の目的となった医療費の合計を限度に差し引き、他の医療費から差し引かない。受取人が支払者と違っても差し引く。"
        "対象の医療費が2つの年分・2人の支払にまたがるときは、支払った額に応じてあん分する"
    ),
    source_kind=SourceKind.NTA_EXPLANATION,
    law=(
        "所得税法第73条第1項かっこ書、所得税基本通達73−8〜73−10、タックスアンサー No.1120、質疑応答事例 05/26・05/28・05/59・05/61"
        "（同じ対象の集合に当てる複数の給付は合計して限度を当てるのは法令の読み）"
    ),
    references=(f"{_IRL}#1", f"{_IRN}#1", f"{_IRN}#4"),
    flags=(ReadingFlag.LEGAL_READING,),
)

_TSUCHI = "docs/public-sources/20261112_impl-research6_forms-iryohi-tsuchi.md"

MEDICAL_NOTICE_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "医療費通知（medical_expense_notice）は、支払者自身か生計を一にする配偶者その他の親族の分に限り、その年中に実際に支払った医療費の額（㋐）から"
        "補塡される金額（㋑）を差し引いた額を補塡後の医療費に足す。㋑は通知の記録ごとに㋐を限度とし、ほかの医療費から差し引かない"
        "（記録ごとに限度を当てるのは法令の読み）。生計を一にするかは通知の対象の期間の終わりの日（受診者が死亡していれば死亡の日と早い方）の現況で判定する"
        "（通達73−1 の受診時の現況を通知の期間に当てる法令の読み）。通知に記載された医療費は所令207 の診療・治療の対価とし範囲の判断を引かない（法令の読み）。"
        "notice_id を書いた支払は明細から除く（手引き ❷：❶に記入したものは記入しない）"
    ),
    source_kind=SourceKind.GUIDE_OR_FORM_NOTE,
    law=(
        "所得税法第73条第1項・第120条第4項第2号、所得税法施行規則第47条の2第13項、所得税基本通達73−1、"
        "令和7年分 確定申告の手引き「医療費控除の明細書」❶※2・(2)・(3)・❷、タックスアンサー No.1120"
    ),
    references=(f"{_TSUCHI}#2", f"{_TSUCHI}#3", f"{_TSUCHI}#4", f"{_IRL}#5.2", f"{_IRN}#5.2"),
    flags=(ReadingFlag.LEGAL_READING,),
)

SELFMED_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "特定一般用医薬品等購入費は、申告者本人がその年に取組を行い、レシート等にセルフメディケーション税制の対象である旨の表示がある"
        "購入（表示の誤りは判断で上書き）の、自己と生計を一にする親族の分の合計。通常の医療費控除とは選択"
    ),
    source_kind=SourceKind.LAW,
    law="租税特別措置法第41条の17第1項・第2項、タックスアンサー No.1129・1131・1133、厚生労働省の事務連絡（レシートの記載事項）",
    references=(f"{_IRL}#4.1", f"{_IRN}#6.1", f"{_IRN}#6.2", f"{_IRN}#6.4"),
)

SOCIAL_INSURANCE_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "社会保険料控除は、その年中に支払った（又は給与・公的年金から差し引かれた）、自己又は生計を一にする配偶者その他の親族の負担すべき"
        "社会保険料の全額（前納は、期間が年分に収まらなければ納付期日の回数で按分するか、選択で全額を支払った年分にする〔前納期間が1年を超えるものは"
        "法令で前納できるとされているものかの一次情報がなく、按分と違えば未確定〕）。生計を一にするかは支払日と12月31日の両方で見る（判定の時点の一次情報がない：両方が同じときだけ決め、違えば未確定）。"
        "給与から控除された額は、控除が行われる給与の支払の日の年分に入れ、未払の給与からは数えない（支給日の年分にしないのは法令の読み）。"
        "給与の源泉徴収票の社会保険料等の金額があれば、その票の支払者の明細の額の代わりに使う（HANDOFF D23 K4）"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第74条第1項・第2項、所得税基本通達74・75−1（現実に支払った額・前納の按分）・74・75−2（全額をその年分）、タックスアンサー No.1130"
        "（「給与や公的年金から差し引かれた金額の全額」）、手引き p.15（親族の年金から特別徴収された保険料は受給者の控除）"
    ),
    references=(f"{_ZG}#7.1", f"{_ZG}#7.2"),
    flags=(ReadingFlag.LEGAL_READING,),
)

MUTUAL_AID_RULE = BasisEntry(
    type=BasisType.RULE,
    name="小規模企業共済等掛金控除は、その年中に支払った掛金の全額（加入者本人が支払ったものだけ。加入者以外の支払は後の段：D21 R3）",
    source_kind=SourceKind.LAW,
    law="所得税法第75条第1項・第2項、タックスアンサー No.1135",
    references=(f"{_HKL}#5", f"{_HKN}#4"),
)

LIFE_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "生命保険料は支払った人が控除する（契約者は問わない）。新旧は締結日（平成24年1月1日）、区分は契約の種類（判断.生命保険の区分で上書き）、"
        "受取人のすべてが支払者又はその配偶者その他の親族であること。新のみ・旧のみ・両方は納税者の選択（未入力なら全部で評価）。"
        "平成24年以後に旧契約に附帯して新契約を締結したら、その旧契約は附帯した日以後の支払から新契約（支払った時の現況：法令の読み）。"
        "保険期間5年未満で満了の日の生存等に限り支払う定めの契約（特定保険契約）は数えない。前納は払込期日の回数で按分"
    ),
    source_kind=SourceKind.LAW,
    law="所得税法第76条第1項〜第10項、所得税法施行令第209条第1項、所得税基本通達76−1・76−3(3)、質疑応答事例 05/74〜05/76、タックスアンサー No.1140 の Q&A",
    references=(f"{_HKL}#2.1", f"{_HKL}#2.2", f"{_HKN}#1.2", f"{_HKN}#1.4", f"{_HKN}#1.5"),
    flags=(ReadingFlag.LEGAL_READING,),
)

LIFE_SPECIAL_RULE = BasisEntry(
    type=BasisType.RULE,
    name="令和8年分・令和9年分は、年齢23歳未満の扶養親族を有する人の新生命保険料の式と新旧合計の上限を読み替える",
    source_kind=SourceKind.LAW,
    law="租税特別措置法第41条の15の5第1項・第2項（判定は12月31日の現況）",
    references=(f"{_HKL}#2.3",),
)

EARTHQUAKE_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "地震保険料は支払った人が控除する。保険の目的は自己又は生計を一にする配偶者その他の親族の有する常時居住の用に供する家屋か"
        "生活用動産（生計を一にするかは支払日と12月31日の両方で見る）。家屋の一部を居住の用に供するときは居住割合で按分し、おおむね90%以上なら全額"
        "（通達77−5・77−6）。前納は払込期日の回数で按分（77−7・76−3(3)）。旧長期損害保険料は締結日・始期・期間・満期返戻金・平成19年以後の変更を記録で確かめる"
    ),
    source_kind=SourceKind.LAW,
    law="所得税法第77条第1項・第2項、所得税基本通達77−1〜77−7、平成18年法律第10号附則第10条",
    references=(f"{_HKL}#3", f"{_HKN}#2.1", f"{_HKN}#2.2", f"{_HKN}#2.3", f"{_HKN}#2.4"),
    flags=(ReadingFlag.LEGAL_READING,),
)

DONATION_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "特定寄附金は、その年中に現実に支払った国又は地方公共団体に対する寄附金（学校の入学に関してするもの・特別の利益が及ぶものを除く）と、"
        "日本赤十字社（特定公益増進法人）に対する寄附金と、受領証等に指定寄附金・特定公益増進法人の業務に関連する寄附金・公益信託の信託事務に関連する"
        "寄附金である旨の記載がある寄附金（令和8年4月1日前の公益信託への支出は旧第3項の特定公益信託と読む）。そのほかの寄附先で記載なしは当たらない。"
        "共同募金会（社会福祉法人：社会福祉法第113条第2項、所令第217条第1項第5号の特定公益増進法人。昭和40年大蔵省告示第154号第4号・第4号の2 の指定寄附金でもある）"
        "への寄附金は、受領証等の記載によらず特定寄附金（どちらの読みでも第78条第2項の特定寄附金で額は同じ：2026-11-12）。"
        "そのほかの寄附先で記載の欄がないものは、両方で評価し、分かれるので未確定"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第78条第2項第1号〜第4号（第4号は令和8年4月1日から。それ前は旧第3項）、所得税法施行規則第47条の2第3項（受領証等の記載）、所得税基本通達78−1〜78−3、タックスアンサー No.1150（特定公益増進法人の説明に「日本赤十字社等」）・1155、"
        "所得税法施行令第217条第1項第5号・社会福祉法第113条第2項・昭和40年大蔵省告示第154号第4号・第4号の2（共同募金会）。"
        "日本赤十字社への寄附金を主たる目的の業務に関連する寄附金と読むことは法令の読み。共同募金会への寄附金を特定寄附金とするのも法令の読み"
        "（特定公益増進法人の読みにかかる第78条第2項第3号の業務関連の要件は、所法第78条第2項の本文を impl-research4 で取り直していないので確かめていない留保がある。"
        "指定寄附金の読み〔告示154号第4号の2：社会福祉事業等の設備・経常的経費・民間奉仕活動の基金に充てる寄附金〕ではその要件はかからない）"
    ),
    references=(f"{_HKL}#4", f"{_HKN}#3.1", f"{_HKN}#3.2", f"{_HKN}#3.6", f"{_KIFU4}#2.1", f"{_KIFU4}#2.3", "docs/hypotheses/20261112_impl-research4_all-model.md#H11"),
    flags=(ReadingFlag.LEGAL_READING,),
)


CASUALTY_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "雑損控除：災害・盗難・横領による所有者本人の資産の損失の金額（直前の価額−直後の価額。判断があれば取得費相当額を基礎）に災害等関連支出を足し、"
        "保険金等をまず損害金額から、超える分を支出から差し引く。足切りは総所得金額等の10分の1（災害関連支出が5万円を超えるときの第2号・第3号の額を含む）"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第72条第1項、所得税法施行令第206条第1項〜第3項、タックスアンサー No.1110 の注3、所得税基本通達72−4・72−5・72−7。"
        "記録の acquisition_cost を所法38② の取得費相当額と読むこと、insurance_recovery の欄がないときに保険金等なしと読むこと、"
        "第206条第1項第2号の「やんだ日の翌日から一年を経過した日の前日」をやんだ日の1年後の応当日と読み、第1号・第3号の支出にも同じ期間を当てることは法令の読み"
    ),
    references=(f"{_HKL}#6", f"{_HKN}#5.1", f"{_HKN}#5.3", "docs/public-sources/20261111_impl-research3_kojo-misc-laws-and-nta.md#1"),
    flags=(ReadingFlag.LEGAL_READING,),
)

CASUALTY_RELATIVE_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "雑損控除の親族の資産：所有者と損失の日に生計を一にする親族の居住者がいて、所有者の総所得金額・退職所得金額の合計額が基準額以下なら、"
        "その損失は所令第205条第2項の居住者（同一生計配偶者・扶養親族としている人、配偶者、合計額が最も大きい人）の控除に入れ、所有者本人の控除には入れない。"
        "被災事業用資産は雑損控除の対象から除く"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第72条第1項（被災事業用資産を除く）、所得税法施行令第205条第1項・第2項、所得税基本通達72−4（生計は損失の日、所得は12月31日の現況）。"
        "同じ損失を所有者と居住者の2人で控除しないこと（docs/hypotheses/20261109_round2_hoken-kifu-model.md H10）と、生計の判定を損失が生じた日にそろえること（支出の日を使わない）は法令の読み。"
        "第205条の合計額は措令第4条の2第9項・第25条の8第16項・第25条の11の2第20項の読替えで上場株式等の所得を加えた額（総所得金額等）"
    ),
    references=(f"{_HKL}#6", f"{_HKN}#5.1", f"{_HKN}#5.3", f"{_KIN}#4.3", "docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md#1", "docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md#2"),
    flags=(ReadingFlag.LEGAL_READING,),
)

DONATION_CHOICE_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "政党等・認定NPO法人等・公益社団法人等への寄附は、種類ごとの全額について所得控除か税額控除かを選ぶ（未入力なら全部の候補で評価：D22 S20）。"
        "所得控除を選べば特定寄附金の額に入る。公益社団法人等で税額控除を選ぶときは、法人が措法第41条の18の3第1項の要件を満たす前提とする。"
        "令和8年分は、令和8年1月1日以後に公職の候補者が特定政党支部に対してする寄附を除く"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "租税特別措置法第41条の18第1項・第41条の18の2第1項・第41条の18の3第1項、所得税法第78条第2項、措置法通達41の18−2・41の18の2−1・41の18の3−1、"
        "令和7年法律第2号附則第1条第2号・第5条。recipient_type の political_party を第41条の18第1項第1号・第2号の団体と読むことは法令の読み"
    ),
    references=(f"{_SK}#1", f"{_SK}#2", f"{_SK}#3", f"{_SK}#4", f"{_SK}#7"),
    flags=(ReadingFlag.LEGAL_READING,),
)

TAX_CREDIT_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "公益社団法人等→認定NPO法人等→政党等の順に、(min(寄附の額, 総所得金額等×40%−他の寄附)−max(0,2千円−他の寄附))×率（百円未満切捨て）を計算し、"
        "それぞれ税額控除の前の所得税の額の25%（認定NPOは公益の控除額を引いた残り、政党等は別枠）を限度に控除する"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "租税特別措置法第41条の18第2項・第41条の18の2第2項・第41条の18の3第1項、措令第26条の27の4、措置法通達41の18−3（税額控除の前の税額）、"
        "各計算明細書の順序（令和7年分）"
    ),
    references=(f"{_SK}#1", f"{_SK}#2", f"{_SK}#3", f"{_SK}#6", f"{_SK}#7", "docs/measurements/20261111_impl-research_phase2c-fetch-and-checks.md#5"),
)


def unfounded_rounding(name: str, title: str, references: tuple[str, ...]) -> BasisEntry:
    """根拠のない端数（候補の全部で評価：D22 S3）を値の根拠に書く項目。"""
    return BasisEntry(
        type=BasisType.ROUNDING,
        name=name,
        source_kind=None,
        references=references,
        detail={"title": f"{title}（根拠なし。切捨て・切上げ・四捨五入の候補の全部で評価）"},
    )


MEDICAL_ROUNDING = unfounded_rounding(
    "医療費控除の足切りの端数",
    "総所得金額等の百分の五に相当する金額の1円未満の端数",
    (f"{_IRL}#6", f"{_IRN}#9"),
)
DONATION_ROUNDING = unfounded_rounding(
    "寄附金控除の上限の端数",
    "総所得金額等の百分の四十に相当する金額の1円未満の端数",
    (f"{_HKL}#4",),
)
REIMBURSEMENT_ROUNDING_BASIS = unfounded_rounding(
    "医療費の補塡のあん分の端数",
    "2以上の年分・支払者にまたがる補塡を支払った医療費の額に応じてあん分した額の1円未満の端数",
    (f"{_IRN}#4",),
)
PREMIUM_ROUNDING_BASIS = unfounded_rounding(
    "保険料の前納・居住割合のあん分の端数",
    "前納した保険料の年分の額（総額×その年中に到来する期日の回数÷総回数）と居住割合で按分した地震保険料の1円未満の端数",
    (f"{_ZG}#7.2", f"{_HKN}#1.5", f"{_HKN}#2.4"),
)
CASUALTY_ROUNDING = unfounded_rounding(
    "雑損控除の足切りの端数",
    "総所得金額等の10分の1に相当する金額の1円未満の端数",
    (f"{_HKL}#6",),
)


def hoken_ceil_basis() -> BasisEntry:
    return HOKEN_CEIL.basis_entry()


#: 変数名 → その変数の値に付ける規則の根拠（パラメータはトレースから別に足す）。
RULES: Mapping[str, tuple[BasisEntry, ...]] = {
    "所得税_補塡後の医療費の額": (MEDICAL_PAYER_RULE, MEDICAL_SCOPE_RULE, REIMBURSEMENT_RULE, KINSHIP_RULE, REIMBURSEMENT_ROUNDING_BASIS, MEDICAL_NOTICE_RULE),
    "所得税_医療費通知に記載された医療費の額": (MEDICAL_NOTICE_RULE, KINSHIP_RULE),
    "所得税_医療費通知のその年中に実際に支払った医療費の額": (MEDICAL_NOTICE_RULE, KINSHIP_RULE),
    "所得税_医療費通知の補塡される金額": (MEDICAL_NOTICE_RULE, KINSHIP_RULE),
    "所得税_特定一般用医薬品等購入費の額": (SELFMED_RULE, MEDICAL_PAYER_RULE, KINSHIP_RULE),
    "所得税_医療費控除の額": (MEDICAL_PAYER_RULE, MEDICAL_SCOPE_RULE, REIMBURSEMENT_RULE, KINSHIP_RULE, MEDICAL_ROUNDING, REIMBURSEMENT_ROUNDING_BASIS, MEDICAL_NOTICE_RULE),
    "所得税_セルフメディケーション税制による医療費控除の額": (SELFMED_RULE, KINSHIP_RULE),
    "所得税_社会保険料控除の額": (SOCIAL_INSURANCE_RULE, KINSHIP_RULE, PREMIUM_ROUNDING_BASIS),
    "所得税_小規模企業共済等掛金控除の額": (MUTUAL_AID_RULE,),
    "所得税_生命保険料控除の額": (LIFE_RULE, LIFE_SPECIAL_RULE, KINSHIP_RULE, hoken_ceil_basis(), PREMIUM_ROUNDING_BASIS),
    "所得税_地震保険料控除の額": (EARTHQUAKE_RULE, KINSHIP_RULE, hoken_ceil_basis(), PREMIUM_ROUNDING_BASIS),
    "所得税_寄附金控除の額": (DONATION_RULE, DONATION_ROUNDING),
    "所得税_雑損控除の額": (CASUALTY_RULE, CASUALTY_RELATIVE_RULE, CASUALTY_ROUNDING, KINSHIP_RULE),
    "所得税_翌年以後に繰り越す雑損失の金額": (CASUALTY_RULE, CASUALTY_RELATIVE_RULE, CASUALTY_ROUNDING, KINSHIP_RULE),
    "所得税_政党等寄附金特別控除等の額": (DONATION_CHOICE_RULE, TAX_CREDIT_RULE),
    "所得税_雑損の損失の金額": (CASUALTY_RULE, CASUALTY_RELATIVE_RULE),
    "所得税_税額控除を受ける政党等寄附金の額": (DONATION_CHOICE_RULE,),
    "所得税_税額控除を受ける認定NPO法人等寄附金の額": (DONATION_CHOICE_RULE,),
    "所得税_税額控除を受ける公益社団法人等寄附金の額": (DONATION_CHOICE_RULE,),
    "所得税_年齢23歳未満の扶養親族を有するか": (LIFE_SPECIAL_RULE, KINSHIP_RULE),
}

__all__ = ["CASUALTY_RELATIVE_RULE", "DONATION_ROUNDING", "HOKEN_CEIL", "MEDICAL_ROUNDING", "RULES"]
