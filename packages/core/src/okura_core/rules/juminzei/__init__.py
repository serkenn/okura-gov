"""規則モジュール juminzei：住民税（個人の市町村民税・道府県民税）と森林環境税の判定と税額（令和8年度分・令和9年度分）。README.md を見る。"""

from __future__ import annotations

from pathlib import Path

from ...registry import ReadingSlotSpec, RoundingSlotSpec, RuleModule, StageSpec
from . import allocation, calc, kintowari, separate, tokutei
from .basis import KINTO_STAGE_BASIS, RULES, SEPARATE_STAGE_BASIS, STAGE_BASIS
from .checks import CHECKS
from .inputs import DECISIONS, INJECTIONS, RECORD_KINDS, build_inputs
from .variables import VARIABLES

MODULE = RuleModule(
    name="juminzei",
    title="住民税（個人の市町村民税・道府県民税）と森林環境税",
    directory=Path(__file__).resolve().parent,
    variables=VARIABLES,
    record_kinds=RECORD_KINDS,
    build_inputs=build_inputs,
    decisions=DECISIONS,
    injections=INJECTIONS,
    roundings=(
        RoundingSlotSpec("住民税の生命保険料控除の1円未満", "住民税_生命保険料控除の端数の候補", "住民税の生命保険料控除の区分ごとの額（1/2・1/4）の1円未満（根拠なし）"),
        RoundingSlotSpec("住民税の地震保険料控除の1円未満", "住民税_地震保険料控除の端数の候補", "住民税の地震保険料控除（1/2）の1円未満（根拠なし）"),
        RoundingSlotSpec("住民税の医療費控除の足切りの1円未満", "住民税_医療費控除の足切りの端数の候補", "前年の総所得金額等の5%の1円未満（根拠なし）"),
        RoundingSlotSpec("住民税の雑損控除の足切りの1円未満", "住民税_雑損控除の足切りの端数の候補", "前年の総所得金額等の1/10の1円未満（根拠なし）"),
        RoundingSlotSpec("住民税の税額控除の額の1円未満", "住民税_税額控除の額の端数の候補", "表示する税額控除の額の1円未満（根拠なし。所得割の額は途中を有理数で持つ）"),
        # 2026-11-12 の3回目（JM-42）：第313条第11項の後の一時所得の2分の1 の1円未満の候補（住民税の側）を外した。所得税と同じ候補
        # （所得税_一時所得の2分の1の端数の候補）で、income_totals の窓口が計算する（第313条第2項の計算の例）
    ),
    readings=(
        ReadingSlotSpec(
            name="住民税の課税標準の千円未満の切捨ての当て先",
            variable="住民税_課税標準の千円未満の切捨ての当て先の読み",
            title="課税標準額の千円未満の切捨て（地方税法第20条の4の2第1項）を控除後の課税総所得金額等に当てるか、控除前の総所得金額（第313条）に当てるか（JT1：一次情報がない）",
            candidates=calc.TAXABLE_READINGS,
            explanations={
                calc.READING_AFTER_DEDUCTION: "総所得金額−所得控除の合計の千円未満を切り捨てる（自治体の計算例の扱い）",
                calc.READING_BEFORE_DEDUCTION: "総所得金額の千円未満を切り捨ててから所得控除の合計を引く（第313条の課税標準を課税標準額と読む）",
            },
        ),
        ReadingSlotSpec(
            name=tokutei.READING,
            variable=None,
            title=(
                "地方税法第313条第11項の「前年分の所得税につき納税義務を負わない」を、前年分の所得税の額（税額控除の後）が0と読むか、算出税額（税額控除の前）が0と読むか、"
                "所得税法第120条第1項の確定申告の義務の基準（算出税額が配当控除の額以下）と読むか、同項の基準に租税特別措置法第41条の2の2第6項第2号の"
                "読替え（配当控除の額に年末調整で控除された住宅借入金等特別控除の額を加える）を含めて読むか（定義の一次情報がない。JM-41）"
            ),
            candidates=tokutei.READINGS,
            explanations={
                tokutei.READING_AFTER_CREDITS: "配当控除・住宅借入金等特別控除などの税額控除の後の所得税の額（基準所得税額）が0なら納税義務を負わない",
                tokutei.READING_BEFORE_CREDITS: "税額控除の前の算出税額が0のときだけ納税義務を負わない",
                tokutei.READING_DIVIDEND_CREDIT: (
                    "所得税法第120条第1項の確定申告の義務の基準：算出税額が配当控除の額を超えないなら納税義務を負わない"
                    "（配当控除以外の税額控除だけで0になる人は負う）"
                ),
                tokutei.READING_DIVIDEND_HOUSING_CREDIT: (
                    "所得税法第120条第1項の基準に租税特別措置法第41条の2の2第6項第2号の読替えを含める：算出税額が配当控除の額と年末調整で"
                    "控除された住宅借入金等特別控除の額の合計額を超えないなら納税義務を負わない（確定申告で初めて受ける住宅借入金等特別控除は加えない）"
                ),
            },
        ),
    ),
    stages=(
        StageSpec(
            name=tokutei.STAGE,
            title="住民税の申告書だけで受ける特定支出控除（地方税法第313条第11項・第32条第11項）：要件を決め、住民税の給与所得と前年の合計所得金額を計算し直す",
            reads=tokutei.READS,
            writes=tokutei.WRITES,
            run=tokutei.run,
            basis=tokutei.STAGE_BASIS,
        ),
        StageSpec(
            name=allocation.STAGE,
            title="住民税の扶養の割当て（地令46の3〜46の5：所得税と共有の純粋関数を住民税の合計所得金額と所属の規則で呼ぶ）と、所得税と違う人の住民税の区分",
            reads=allocation.READS,
            writes=allocation.WRITES,
            groups=("住民税扶養所属一覧",),
            run=allocation.run,
            basis=STAGE_BASIS,
        ),
        StageSpec(
            name=allocation.STAGE_CHAIN,
            title="住民税の扶養の連鎖の人（扶養親族等で、自分も納税義務者）の1人分の額を納税義務者に集める",
            reads=allocation.CHAIN_READS,
            writes=allocation.CHAIN_WRITES,
            run=allocation.run_chain,
            basis=STAGE_BASIS,
        ),
        StageSpec(
            name=kintowari.STAGE,
            title="住民税の均等割（第311条の軽減に当たる人と、家屋敷課税の市町村ごとの均等割。扶養の判定・配偶者の住所地の課税を読む）",
            reads=kintowari.READS,
            writes=kintowari.WRITES,
            run=kintowari.run,
            basis=KINTO_STAGE_BASIS,
        ),
        StageSpec(
            name=separate.STAGE,
            title="住民税の分離課税の所得への所得控除（総所得金額から引ききれない所得控除を上場株式等の分離課税の所得から控除する額）",
            reads=separate.READS,
            writes=separate.WRITES,
            run=separate.run,
            basis=SEPARATE_STAGE_BASIS,
        ),
    ),
    checks=CHECKS,
    rules=RULES,
)
