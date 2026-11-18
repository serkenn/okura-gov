"""規則モジュール income_totals の根拠：パラメータでない規則（損益通算の順序・繰越控除の順序・合計所得金額の範囲・記載の読み方）。

パラメータ（所得金額調整控除の第2項の10万円など）の根拠は evaluate がトレースから足す。
"""

from __future__ import annotations

from collections.abc import Mapping

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from .calc import ADJUSTMENT_1_CEIL, ICHIJI_HALF_TEBIKI_R7

OFFSET_RULE = BasisEntry(
    type=BasisType.RULE,
    name="損益通算：不動産所得・事業所得の損失を、経常所得 → 一時所得 → 退職所得の順に控除し、残りを純損失の金額とする",
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法第69条第1項・第2条第1項第25号、所得税法施行令第198条第1号・第3号・第5号（総合課税の譲渡所得・山林所得は範囲外）",
    references=(
        "docs/public-sources/20261109_round2_genka-laws-and-nta.md#6.1",
        "docs/public-sources/20261109_round2_genka-laws-and-nta.md#6.2",
        "docs/measurements/20261109_round2_genka-fetch-and-checks.md#5.4",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={
        "読み": "令和8年分の版の所令198 第3号の「及び」→「又は」（令和8年政令第93号）は順序を変えないと読む",
        "reading": ["docs/hypotheses/20261109_round2_genka-model.md#H7"],
    },
)

NO_OFFSET_RULE = BasisEntry(
    type=BasisType.RULE,
    name="配当所得・雑所得・一時所得の損失は他の所得の金額から控除しない（0として合計する）",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="所得税法第69条第1項（損益通算の対象は不動産・事業・山林・譲渡の損失だけ）、TA No.2250（注2）",
    references=("docs/public-sources/20261109_round2_genka-laws-and-nta.md#6.3", "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md#6"),
)

HALF_RULE = BasisEntry(
    type=BasisType.RULE,
    name="一時所得の金額は損益通算の後に2分の1にして総所得金額に入れる（1円未満は令和7年分は手引きの切捨て、令和8年分は候補で評価）",
    source_kind=SourceKind.LAW,
    law="所得税法第22条第2項第2号（条文に端数の定めがない。令和7年分は手引きの計算欄の注記に従う：D21 R5・D22 S2。令和8年分の手引きは未公表で候補で評価：D22 S3）",
    references=("docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md#6", "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md#11"),
)

#: 令和7年分の1円未満の切捨ての根拠（年分で変わるが、rules は年分を持たないので、根拠の文面で年分を書く）。
HALF_ROUNDING_RULE = ICHIJI_HALF_TEBIKI_R7.basis_entry()

TOTAL_RULE = BasisEntry(
    type=BasisType.RULE,
    name="合計所得金額は繰越控除の前。上場株式等に係る配当所得等は譲渡損失との損益通算の後、譲渡所得等の損失は0",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第2条第1項第30号イ(2)、租税特別措置法第8条の4第3項第1号・第37条の11第1項後段・第6項・第37条の12の2第4項・第8項。"
        "申告不要を選んだ配当・源泉徴収口座の所得は入れない（措令25の10の12、TA No.1331）"
    ),
    references=(
        "docs/public-sources/20261109_R1-laws_income-tax.md#4",
        "docs/public-sources/20261109_round2b_kabu-law-and-nta.md#1.3",
        "docs/public-sources/20261109_round2b_kabu-law-and-nta.md#2.2",
        "docs/public-sources/20261109_round2b_kabu-law-and-nta.md#5.2",
        "docs/public-sources/20261109_round2b_kabu-law-and-nta.md#6",
    ),
)

ADJUSTMENT_IN_OFFSET_RULE = BasisEntry(
    type=BasisType.RULE,
    name="損益通算の給与所得の金額は所得金額調整控除の後の残額",
    source_kind=SourceKind.CABINET_ORDER,
    law="租税特別措置法第41条の3の11第5項、租税特別措置法施行令第26条の5第1項",
    references=("docs/public-sources/20261109_round2_gaps-sources.md#3.1", "docs/public-sources/20261109_round2_gaps-sources.md#3.3"),
)

CARRY_RULE = BasisEntry(
    type=BasisType.RULE,
    name="純損失・雑損失の繰越控除：損益通算の後に純損失、次に雑損失を控除する。純損失は総所得金額 → 退職所得金額、雑損失は総所得金額 → 上場株式等の配当所得等 → 譲渡所得等 → 退職所得金額の順",
    source_kind=SourceKind.CABINET_ORDER,
    law=(
        "所得税法第70条第1項・第71条第1項、所得税法施行令第201条第1項第2号・第3号、第204条第1項第2号・第2項、"
        "租税特別措置法施行令第4条の2第9項・第25条の11の2第20項（山林所得・一般株式等は範囲外）"
    ),
    references=(
        "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.2",
        "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#8",
        "docs/measurements/20261109_round3_shibo-shukkoku-fetch-and-calc.md#4",
        "docs/public-sources/20261111_impl-research_joto-junjo-laws.md#2.3",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"読み": "所令204② の第1文（まず第69条・第70条の控除を行った後に第71条の控除）を、純損失を全部先に控除すると読む"},
)

CARRIED_RECORD_RULE = BasisEntry(
    type=BasisType.RULE,
    name="繰り越された損失は、前年以前に提出した申告書の記載（中間表現の filed_document の reported_amounts）から作る",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第70条第1項・第4項（前年以前三年内・青色・連続して提出）、第71条第1項・第2項、租税特別措置法第37条の12の2第5項・第7項。"
        "reported_amounts の item の意味はこのモジュールの読み（packages/core/src/okura_core/rules/income_totals/README.md §3）"
    ),
    references=(
        "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.2",
        "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#8",
        "docs/public-sources/20261109_round2b_kabu-law-and-nta.md#6",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
    value={"前年以前の年数": 3},
)

LISTED_RULE = BasisEntry(
    type=BasisType.RULE,
    name="上場株式等の譲渡損失：配当所得等の限度で損益通算し、繰り越された損失はまず譲渡所得等から、次に配当所得等から控除する",
    source_kind=SourceKind.CABINET_ORDER,
    law="租税特別措置法第37条の12の2第1項・第3項・第5項・第7項、租税特別措置法施行令第25条の11の2第8項第2号",
    references=("docs/public-sources/20261109_round2b_kabu-law-and-nta.md#6",),
)

ADJUSTMENT_RULE = BasisEntry(
    type=BasisType.RULE,
    name="所得金額調整控除は第1項（給与等の収入金額850万円超の要件を満たす者）と第2項の合計を給与所得の金額から控除する（第2項は第1項の控除の後）",
    source_kind=SourceKind.LAW,
    law="租税特別措置法第41条の3の11第1項・第2項・第4項第5号・第6号（令和8年分は租税特別措置法施行令第19条の4の2第1項の読替え）",
    references=("docs/public-sources/20261109_round2_gaps-sources.md#3.1", "docs/public-sources/20261109_round2_gaps-sources.md#3.3"),
)

ADJUSTMENT_1_ROUNDING_RULE = ADJUSTMENT_1_CEIL.basis_entry()

CARRYBACK_RULE = BasisEntry(
    type=BasisType.RULE,
    name="純損失の繰戻し還付：前年分の課税総所得金額の税額から、繰り戻した後の税額を引く（前年分の税額控除後の所得税の額が限度）",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第140条第1項・第2項・第4項、第141条第1項〜第3項、所得税法施行令第271条第1項第1号、"
        "所得税基本通達140・141−2・140・141−4（通則法118①・119① の準用）"
    ),
    references=(
        "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3",
        "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#9",
        "docs/measurements/20261109_round2_aoiro-fetch-and-checks.md#4.3",
    ),
    detail={"読み": "繰り戻す額が前年分の課税総所得金額を超える場合は、課税退職所得金額から控除する（所令271①三。課税山林所得金額があれば範囲外）。前年の平均課税は後の段"},
)

SECOND_PRIOR_RULE = BasisEntry(
    type=BasisType.RULE,
    name="前々年分への純損失の繰戻し還付：事業の全部の譲渡・廃止等又は死亡の年の前年の純損失を、前々年分の課税総所得金額（次に課税退職所得金額）から控除した税額の差（前々年分の税額控除後の所得税の額が限度）",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第140条第5項・第141条第4項、所得税法施行令第272条第1項・第2項・第271条第1項、"
        "所得税基本通達140・141−2・140・141−4"
    ),
    references=(
        "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3",
        "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#9",
        "scripts/results/R2X_aoiro_laws/shotoku-rei_2025-12-31.txt",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={
        "読み": (
            "所令272② 後段の「所得税の額」からの還付額の控除は、還付の限度（税額控除後の所得税の額）に当て、各号の所得税の額は控除した後の課税総所得金額等から計算する。"
            "選択.損失申告と繰戻し の second_prior_year_carryback_amount を書くことは、期限（その年分の確定申告期限）までの請求を表すと読む。"
            "繰り戻した額は、その年分の純損失の繰越控除の対象から除く（所法70① かっこ書）。"
            "事実（事業の全部の譲渡・廃止等・死亡）・判断（事業の休止・重要部分の譲渡）・選択のどれの記録もない人は、繰戻しには還付の請求（所法140⑤・141④）が"
            "要るので、請求がないものとして繰り戻す額・還付請求額を0とする（2026-11-12 統括の決定。入力すれば評価する）"
        )
    },
)

JUMIN_WINDOW_RULE = BasisEntry(
    type=BasisType.RULE,
    name="住民税への窓口：分離課税に係る退職所得がないものとして損益通算・繰越控除・公的年金等控除額の区分を当てた所得の合計",
    source_kind=SourceKind.LAW,
    law="地方税法第292条第1項第13号・第313条第1項第2項・第328条・第328条の2、地方税法施行令第48条の5の2、所得税法第35条第4項・第69条・第70条・第71条",
    references=(
        "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#6.1",
        "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#6.3",
        "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md#2.1",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"読み": "繰越控除の額は、所得税の申告の記載から作った繰り越された損失の額を使う（住民税の繰越の額を記載した記録が中間表現にない）"},
)

_OFFSET = (OFFSET_RULE, NO_OFFSET_RULE, ADJUSTMENT_IN_OFFSET_RULE)

#: 変数名 → その変数の値に付ける規則の根拠（パラメータはトレースから別に足す）。
RULES: Mapping[str, tuple[BasisEntry, ...]] = {
    "所得税_所得金額調整控除": (ADJUSTMENT_RULE, ADJUSTMENT_1_ROUNDING_RULE),
    "所得税_合計所得金額": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, TOTAL_RULE),
    "所得税_所得金額調整控除の判定に使う合計所得金額": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, TOTAL_RULE, ADJUSTMENT_RULE),
    "所得税_公的年金等に係る雑所得以外の合計所得金額": (OFFSET_RULE, NO_OFFSET_RULE, HALF_RULE, HALF_ROUNDING_RULE, TOTAL_RULE),
    "所得税_純損失の金額": _OFFSET,
    "所得税_純損失の繰越控除額": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, CARRY_RULE, CARRIED_RECORD_RULE),
    "所得税_雑損失の繰越控除額": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, CARRY_RULE, CARRIED_RECORD_RULE),
    "所得税_総所得金額": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, CARRY_RULE),
    "所得税_退職所得金額": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, CARRY_RULE),
    "所得税_総所得金額等": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, CARRY_RULE, LISTED_RULE),
    "所得税_上場株式等の譲渡損失の繰越控除額": (LISTED_RULE, CARRIED_RECORD_RULE),
    "所得税_申告分離課税の上場株式等に係る配当所得等の金額": (LISTED_RULE,),
    "所得税_申告分離課税の上場株式等に係る譲渡所得等の金額": (LISTED_RULE,),
    "所得税_純損失の繰戻しによる還付請求額": (CARRYBACK_RULE,),
    "所得税_前々年分への純損失の繰戻しによる還付請求額": (SECOND_PRIOR_RULE,),
    "所得税_前々年分に繰り戻す純損失の金額": (SECOND_PRIOR_RULE, CARRIED_RECORD_RULE),
    "所得税_繰り越された純損失の金額": (CARRIED_RECORD_RULE,),
    "所得税_繰り越された雑損失の金額": (CARRIED_RECORD_RULE,),
    "所得税_繰り越された上場株式等の譲渡損失の金額": (CARRIED_RECORD_RULE, LISTED_RULE),
    "所得税_損益通算の後の退職所得の金額": (*_OFFSET, JUMIN_WINDOW_RULE),
    "所得税_退職所得を除いた公的年金等に係る雑所得以外の合計所得金額": (OFFSET_RULE, NO_OFFSET_RULE, HALF_RULE, HALF_ROUNDING_RULE, JUMIN_WINDOW_RULE),
    "所得税_分離課税の退職所得を除いた合計所得金額": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, TOTAL_RULE, JUMIN_WINDOW_RULE),
    "所得税_分離課税の退職所得を除いた総所得金額": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, CARRY_RULE, JUMIN_WINDOW_RULE),
    "所得税_分離課税の退職所得を除いた総所得金額等": (*_OFFSET, HALF_RULE, HALF_ROUNDING_RULE, CARRY_RULE, LISTED_RULE, JUMIN_WINDOW_RULE),
}
