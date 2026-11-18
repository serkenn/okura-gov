"""規則モジュール personal_deductions の根拠：パラメータでない規則（年齢の数え方、判定の時、段階の切下げ・切上げ、読み）。"""

from __future__ import annotations

from collections.abc import Mapping

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind

_MISC = "docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md"
_MISC_M = "docs/measurements/20261109_impl-prep_misc-fetch-and-age-check.md"
_JINTEKI = "docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md"
_SPOUSE = "docs/public-sources/20261109_round2_spouse-laws-and-sources.md"
_SPOUSE_M = "docs/measurements/20261109_round2_spouse-fetch-and-tables.md"
_R1 = "docs/public-sources/20261109_R1-laws_income-tax.md"
_GAPS = "docs/public-sources/20261109_round2_gaps-sources.md"
_ABROAD = "docs/public-sources/20261109_round2_elderly-abroad-laws.md"
_R4 = "docs/public-sources/20261109_R4-modeling_concepts.md"

_KM3 = "docs/public-sources/20261111_impl-research3_kojo-misc-laws-and-nta.md"

DEATH_AGE_READING = BasisEntry(
    type=BasisType.RULE,
    name="死亡の時の現況の年齢は、死亡の日の前日の終了時までに達した年齢（死亡の日の終了時に加わる1歳を含めない）",
    source_kind=SourceKind.LAW,
    law="所得税法第85条第3項ただし書、年齢計算ニ関スル法律",
    references=(f"{_KM3}#4", f"{_MISC}#1.3"),
    flags=(ReadingFlag.LEGAL_READING,),
)

AGE_RULE = BasisEntry(
    type=BasisType.RULE,
    name="年齢は判定の日の終了時までに達した年齢（1月1日生まれは前年の12月31日の終了時に1つ加わる）",
    source_kind=SourceKind.LAW,
    law="年齢計算ニ関スル法律第1項・第2項、民法第143条第2項",
    references=(f"{_MISC}#1.3", f"{_MISC_M}#4.2"),
)

JUDGMENT_TIME_RULE = BasisEntry(
    type=BasisType.RULE,
    name="人の区分は、その年12月31日（死亡したときは死亡の時）の現況で判定する",
    source_kind=SourceKind.LAW,
    law="所得税法第85条第1項・第2項・第3項",
    references=(f"{_MISC}#1.1", f"{_JINTEKI}#1.3"),
)

RESIDENT_RULE = BasisEntry(
    type=BasisType.RULE,
    name="居住者か：判定の時に国内に住所を有するか。国外の滞在があれば判断.住所の所在による（この年分に非居住者の期間がある人は対象外）",
    source_kind=SourceKind.LAW,
    law="所得税法第2条第1項第3号",
    references=(f"{_ABROAD}#4",),
    flags=(ReadingFlag.LEGAL_READING,),
)

DISABILITY_RULE = BasisEntry(
    type=BasisType.RULE,
    name="障害者の範囲：所得税法施行令第10条第1項各号",
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法第2条第1項第28号、所得税法施行令第10条第1項",
    references=(f"{_JINTEKI}#1.5",),
)

PENDING_CERTIFICATE_RULE = BasisEntry(
    type=BasisType.RULE,
    name="手帳の交付を申請中で明らかに手帳に記載される程度の障害がある者は、障害者として取り扱う（判断.障害の程度 があるときだけ当たる）",
    source_kind=SourceKind.CIRCULAR,
    law="所得税基本通達2−38（身体障害者手帳・戦傷病者手帳について）",
    references=(f"{_JINTEKI}#1.7",),
)

SPECIAL_DISABILITY_RULE = BasisEntry(
    type=BasisType.RULE,
    name="特別障害者の範囲：所得税法施行令第10条第2項各号",
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法第2条第1項第29号、所得税法施行令第10条第2項",
    references=(f"{_JINTEKI}#1.5",),
)

MARRIAGE_RULE = BasisEntry(
    type=BasisType.RULE,
    name="配偶者は婚姻の届出による配偶者（内縁の者を含まない）",
    source_kind=SourceKind.LAW,
    law="民法第739条第1項、所得税基本通達2−46",
    references=(f"{_R4}#3.1", f"{_SPOUSE}#2.1"),
)

WORKING_STUDENT_READING = BasisEntry(
    type=BasisType.RULE,
    name="給与所得・退職所得は自己の勤労に基づくとし、「給与所得を有する」は給与等の収入金額があることとする",
    source_kind=SourceKind.LAW,
    law="所得税法第2条第1項第32号",
    references=(f"{_GAPS}#1.1", f"{_GAPS}#1.3"),
    flags=(ReadingFlag.LEGAL_READING,),
)

SPOUSE_SPECIAL_STEP_RULE = BasisEntry(
    type=BasisType.RULE,
    name="配偶者特別控除の第1号ロの5万円刻みの切下げと、第2号・第3号の1万円未満の切上げ（条文の端数処理）",
    source_kind=SourceKind.LAW,
    law="所得税法第83条の2第1項第1号ロ・第2号・第3号",
    references=(f"{_SPOUSE}#1.3", f"{_SPOUSE_M}#3.1", f"{_SPOUSE_M}#3.2"),
)

SPECIFIED_RELATIVE_STEP_RULE = BasisEntry(
    type=BasisType.RULE,
    name="特定親族特別控除の第2号の、乗じた金額の10万円刻みの切下げ（条文の端数処理）",
    source_kind=SourceKind.LAW,
    law="所得税法第84条の2第1項第2号",
    references=(f"{_R1}#3",),
)

ALLOCATION_RULE = BasisEntry(
    type=BasisType.RULE,
    name="配偶者と扶養親族等の所属は申告書等の記載により、記載で定まらないときは夫又は妻の同一生計配偶者（所令218②）、既に記載した居住者、所得の合計額が最も大きい居住者の順で決める",
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法第85条第4項〜第7項、所得税法施行令第218条・第218条の2・第219条・第220条",
    references=(f"{_MISC}#3.2", f"{_MISC}#3.3"),
)

HAS_RULE = BasisEntry(
    type=BasisType.RULE,
    name="所得金額調整控除の第1項の親族等は、親族の組ごとに扶養親族・同一生計配偶者の要件で判定する（同じ親族を複数の居住者が有することができる）",
    source_kind=SourceKind.LAW,
    law="租税特別措置法第41条の3の11第1項・第3項・第4項、租税特別措置法関係通達41の3の11−1",
    references=(f"{_GAPS}#3.1", f"{_GAPS}#3.4", f"{_GAPS}#3.5"),
)

CHAIN_RULE = BasisEntry(
    type=BasisType.RULE,
    name="扶養親族とされた人が別の人の申告者でもある（連鎖）とき、その人の分の控除の額を申告者に集める",
    source_kind=SourceKind.LAW,
    law="所得税法第84条（扶養親族である人が扶養親族を有することを制限する文言がない）",
    references=(f"{_MISC}#4.1", f"{_MISC}#4.2"),
    flags=(ReadingFlag.LEGAL_READING,),
)

#: 変数名 → その変数の値に付ける規則の根拠（パラメータはトレースから別に足す）。
RULES: Mapping[str, tuple[BasisEntry, ...]] = {
    "所得税_年齢": (AGE_RULE, JUDGMENT_TIME_RULE, DEATH_AGE_READING),
    "所得税_居住者か": (RESIDENT_RULE, JUDGMENT_TIME_RULE),
    "所得税_障害者に当たるか": (DISABILITY_RULE, PENDING_CERTIFICATE_RULE, JUDGMENT_TIME_RULE),
    "所得税_特別障害者に当たるか": (SPECIAL_DISABILITY_RULE, JUDGMENT_TIME_RULE),
    "所得税_配偶者がいるか": (MARRIAGE_RULE, JUDGMENT_TIME_RULE),
    "所得税_勤労学生に当たるか": (WORKING_STUDENT_READING, JUDGMENT_TIME_RULE),
    "所得税_勤労学生の給与所得等以外の所得の金額": (WORKING_STUDENT_READING,),
    "所得税_配偶者特別控除の額": (SPOUSE_SPECIAL_STEP_RULE,),
    "所得税_特定親族特別控除の額": (SPECIFIED_RELATIVE_STEP_RULE,),
}
