"""規則モジュール tax の根拠：パラメータでない規則（RULES）と、根拠を自分で組み立てる変数（BASIS：税率表の使った段・端数の根拠）。

パラメータの根拠は、組み立ての関数がない変数ではトレースから evaluate が足す（explain.parameter_basis）。
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...explain import parameter_basis
from ...registry import BasisContext
from .calc import FUKKO_ROUNDING_YEARS, HAITO_FLOOR, KAKUTEI_KINGAKU_FLOOR, KAZEI_HYOJUN_FLOOR, brackets_from_parameters, progressive_tax
from .inputs import KIND_DEATH, KIND_DEATH_NEXT_YEAR, KIND_DEPARTURE

_ZG = "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md"
_KABU = "docs/public-sources/20261109_round2b_kabu-law-and-nta.md"
_SHIBO = "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md"
_GENSEN = "docs/public-sources/20261111_impl-research_gensen-laws-and-nta.md"
_HAITO = "docs/public-sources/20261111_impl-research_haito-laws-and-nta.md"
_R121 = "docs/public-sources/20261111_impl-research_121-laws-and-nta.md"
_JJ = "docs/public-sources/20261111_impl-research_joto-junjo-laws.md"
_JJ3 = "docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md"
_CREDITS = "docs/public-sources/20261112_impl-research6_forms-tax-credits.md"


def _rule(name: str, law: str, refs: tuple[str, ...], *, kind: SourceKind = SourceKind.LAW, flags: tuple[ReadingFlag, ...] = ()) -> BasisEntry:
    return BasisEntry(type=BasisType.RULE, name=name, source_kind=kind, law=law, references=refs, flags=flags)


WITHHOLDING_RULE = _rule(
    "源泉徴収税額は、源泉徴収票（給与：D23 K4）・給与の支払・業務の報酬・公的年金等・退職手当等・申告をする配当等・特定口座の源泉徴収税額（所得税及び復興特別所得税の合計）をその年分に合計する。"
    "確定申告をしないことを選択した配当等の税額は差し引かない",
    "所得税法第120条第1項第4号（「源泉徴収をされた又はされるべき所得税の額」）、復興財源確保法第28条・第31条第2項、措法第8条の5・第37条の11の5、"
    "手引き 3-4_38、TA1330。記録した源泉徴収の額を「されるべき」額とみなすことと、給与の源泉徴収税額を支払日ではなく支給日（due_on）の年分"
    "（未払・遅配の給与を含む。所法120①四の「計算の基礎となつた各種所得につき」の読み：kyuyo-jiki UJ4）に数えることは法令の読み",
    (f"{_ZG}#4.1", f"{_ZG}#3.1", f"{_GENSEN}#1", f"{_GENSEN}#3", "docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md#1"),
    flags=(ReadingFlag.LEGAL_READING,),
)
PREPAYMENT_RULE = _rule(
    "予定納税額は、予定納税の通知書の合計額（実際に納めたかにかかわらない）",
    "所得税法第120条第2項（予納税額）。通知書の合計額を書くことは令和7年分の確定申告の手引き p.28（第一表 51 番の欄）",
    (f"{_ZG}#4.3",),
    kind=SourceKind.GUIDE_OR_FORM_NOTE,
)
HOUSING_RULE = _rule(
    "住宅借入金等特別控除の額は、外部で計算した額をそのまま使う",
    "租税特別措置法第41条（判定コアは計算しない：SCOPE §4・§5.2）",
    (f"{_ZG}#5.1",),
)
KIND_RULE = _rule(
    "申告の種類は、その年の中途の死亡（第125条）・国外の滞在又は住所の所在の判断（出国・非居住者）・それ以外（第120条）に分ける",
    "所得税法第120条第1項・第125条第1項・第127条第1項、第2条第1項第42号（出国）",
    (f"{_SHIBO}#2.1", f"{_SHIBO}#3.1", f"{_SHIBO}#1"),
)
SUM_DEDUCTIONS_RULE = _rule(
    "所得控除の合計は、雑損控除から基礎控除までの各控除の額の合計",
    "所得税法第87条（第1項：雑損控除を先に行う。第2項の控除の順序は課税所得の側）",
    (f"{_ZG}#1.1",),
)
ALLOCATION_RULE = _rule(
    "所得控除は、総所得金額 → 上場株式等に係る配当所得等・譲渡所得等の金額 → 山林所得金額 → 退職所得金額の順に控除し、残額は0未満にしない",
    "所得税法第87条第2項・第89条第2項、租税特別措置法第8条の4第3項第3号・第37条の11第6項（第37条の10第6項第5号の準用）の"
    "「総所得金額」の読替え",
    (f"{_ZG}#1.1", f"{_KABU}#1.3", f"{_KABU}#4"),
)
ORDER_RULE = _rule(
    "上場株式等に係る配当所得等の金額と譲渡所得等の金額の間は、配当所得等 → 譲渡所得等 の順に控除する。ただし納税者が異なる順序で控除して申告したときはそれを認める"
    "（選択.所得控除の順序。未入力なら両方で評価し、最適化しない：D22 S20）",
    "租税特別措置法関係通達31・32共−4（雑損失の繰越控除及び所得控除の順序。「その年分の所得控除についても、これと同様に取り扱う」）",
    (f"{_JJ3}#3",),
    kind=SourceKind.CIRCULAR,
)
NIL_BELOW_UNIT_RULE = _rule(
    "差引金額が千円未満（赤字を含む）なら課税される所得金額は0",
    "令和7年分 確定申告の手引き p.24（「1,000円未満の場合（赤字の場合を含む。）は、0円となります。」）。国税通則法第118条第1項と同じ結論",
    (f"{_ZG}#1.3",),
    kind=SourceKind.GUIDE_OR_FORM_NOTE,
)
PROGRESSIVE_RULE = _rule(
    "課税標準を税率の表の区分ごとに分け、それぞれに率を乗じて合計する（超過累進）",
    "所得税法第89条第1項",
    (f"{_ZG}#2",),
)
FLAT_RULE = _rule("課税標準に率を乗じる", "租税特別措置法第8条の4第1項・第37条の11第1項", (f"{_KABU}#1.1", f"{_KABU}#4"))
SUM_TAX_RULE = _rule(
    "算出税額は、課税総所得金額・課税退職所得金額・上場株式等に係る課税所得の各税額の合計",
    "所得税法第21条第1項第4号",
    (f"{_ZG}#1.1",),
)
DIVIDEND_CREDIT_RULE = _rule(
    "配当控除の額は、課税総所得金額等（課税総所得金額に上場株式等の課税配当所得等・課税譲渡所得等を足した額）の1,000万円を区切りに、"
    "総合課税の配当所得の金額の区分（剰余金の配当等・証券投資信託・一般外貨建等証券投資信託）ごとに率を掛ける。限度は所得税額",
    "所得税法第92条第1項・第2項、租税特別措置法第8条の4第3項第4号・第37条の10第6項第6号（第92条第1項の読替え）・第9条第3項・第4項、"
    "タックスアンサー No.1250、手引き 3-4_28",
    (f"{_HAITO}#2", f"{_HAITO}#3", f"{_HAITO}#3.1", f"{_HAITO}#4"),
)
BASE_TAX_RULE = _rule(
    "基準所得税額は、算出税額（㉜）から配当控除（㉝）・事業所得等の特例に係る税額控除（㉞）・住宅借入金等特別控除（㉟）・政党等寄附金特別控除等（㊱〜㊳）・"
    "住宅耐震改修特別控除等（㊴〜㊶）をこの順に控除した額（各控除はその前に残った税額を限度。赤字は0）",
    "所得税法第21条第1項第5号・第92条第2項、復興財源確保法第10条第1号（第93条・第95条の控除は除く）、令和7年分 確定申告の手引き 3-4_36（㊷ 差引所得税額の順と赤字の0）。"
    "各税額控除の限度と順序の条文は docs で読んでいない（手引きの順に、控除の合計で税額を限度とする読み）。災害減免額（㊸）は後の段",
    (f"{_ZG}#3.1", f"{_ZG}#1.1", f"{_KABU}#3", f"{_CREDITS}#4"),
    flags=(ReadingFlag.LEGAL_READING,),
)
EXTERNAL_CREDIT_RULE = _rule(
    "外部で計算した税額控除の額（事業所得等の特例に係る税額控除・住宅耐震改修特別控除・住宅特定改修特別税額控除・認定住宅等新築等特別税額控除）は、そのまま使う",
    "判定コアは計算しない（SCOPE §4・§5.2）。欄と控除の対応は令和7年分 確定申告の手引き 3-4_29（㉞）・3-4_32（㊴〜㊶）",
    (f"{_CREDITS}#2", f"{_CREDITS}#3"),
    kind=SourceKind.GUIDE_OR_FORM_NOTE,
)
CREDIT_CATEGORY_RULE = _rule(
    "区分：㉞ は事業所得等の特例に係る税額控除があれば 1。㊴〜㊶ は住宅耐震改修特別控除 1・住宅特定改修特別税額控除 2・認定住宅等新築等特別税額控除 3・複数 4（額は合計）",
    "令和7年分 確定申告の手引き 3-4_29・3-4_32",
    (f"{_CREDITS}#2", f"{_CREDITS}#3"),
    kind=SourceKind.GUIDE_OR_FORM_NOTE,
)
TOTAL_TAX_RULE = _rule(
    "所得税及び復興特別所得税の額は、基準所得税額と復興特別所得税額の合計",
    "復興財源確保法第17条第1項（併せて記載）、令和7年分 確定申告の手引き ㊻",
    (f"{_ZG}#3.1", f"{_ZG}#3.3", f"{_ZG}#5.4"),
)
SETTLEMENT_RULE = _rule(
    "精算は所得税と復興特別所得税の合計で行う：申告納税額＝所得税及び復興特別所得税の額−源泉徴収税額（黒字は百円未満切捨て、赤字はそのまま）、"
    "第3期分＝申告納税額−予定納税額（黒字は百円未満切捨て、赤字は還付）",
    "所得税法第120条第1項第4号・第5号・第122条第1項、国税通則法第119条第1項・第120条第1項、復興財源確保法第24条第2項・第3項。"
    "欄の順序は令和7年分 確定申告の手引き ㊿〜53。源泉徴収税額を合計のまま精算するのは法令の読み（源泉徴収票の額は合計）",
    (f"{_ZG}#4.1", f"{_ZG}#4.2", f"{_ZG}#3.3", f"{_ZG}#1.2"),
    flags=(ReadingFlag.LEGAL_READING,),
)
OBLIGATION_RULE = _rule(
    "確定申告の義務：総合課税・上場株式等の課税所得・退職所得の税額の合計が配当控除の額を超え、控除しきれない源泉徴収税額・予納税額がなく、"
    "第121条（給与：第1項、退職：第2項、公的年金等：第3項）で申告不要とならない部分の税額がある",
    "所得税法第120条第1項（かっこ書き：控除しきれない源泉徴収税額・予納税額がある場合を除く）・第121条第1項〜第3項、租税特別措置法施行令第4条の2第8項・第25条の8第15項（分離課税の読替え）、"
    "所得税基本通達121−4・121−5・121−6、タックスアンサー No.1900。源泉徴収税額は所得税と復興特別所得税の合計で比べる（かっこ書きは所得税の部分）。"
    "「全部が源泉徴収の対象か」は記録の源泉徴収税額の欄の有無で読む（法令の読み）。第184条の家事使用人のみに支払う者・国外の支払（基通121−5(1)(3)）と"
    "令第262条の2 の同族会社の役員等（第121条第1項ただし書）は給与の支払の記録の欄で判定し、欄がなければ当たらないものとする（法令の読み。基通121−5(2) の在日大公使館等は語彙にない）。"
    "第120条第1項の「配当控除の額」は措法第41条の2の2第6項第2号で年末調整の住宅借入金等特別控除の額との合計額と読み替える",
    (f"{_ZG}#5.1", f"{_ZG}#5.2", "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md#6", f"{_R121}#1", f"{_R121}#2", f"{_R121}#3", f"{_R121}#4", f"{_JJ}#2.1", f"{_JJ3}#4"),
    flags=(ReadingFlag.LEGAL_READING,),
)
REFUND_RETURN_RULE = _rule(
    "還付等を受けるための申告書は、控除しきれない源泉徴収税額・予納税額がある（還付される税額が0超）ときに提出できる",
    "所得税法第122条第1項第2号・第3号（第1号の外国税額控除は範囲外：D20）",
    (f"{_ZG}#4.2", f"{_ZG}#5.3"),
)
DEADLINE_RULE = _rule(
    "確定申告書の提出期限は第三期の末日（翌年3月15日）。日曜日・祝日法の休日・1月2日・3日・土曜日・12月29日〜31日に当たるときは翌日（休日が続けばその翌日）",
    "所得税法第120条第1項、国税通則法第10条第2項、国税通則法施行令第2条第2項、国民の祝日に関する法律第2条・第3条、"
    "建国記念の日となる日を定める政令、国税通則法基本通達（徴収部関係）第10条関係4、暦要項",
    (f"{_ZG}#5.1", f"{_SHIBO}#6", f"{_SHIBO}#6.1"),
)

DEATH_DEADLINE_RULE = _rule(
    "年の中途で死亡した人（第125条）と、翌年の期限までに確定申告書を提出しないで死亡した人（第124条）の提出期限は、相続人が相続の開始があったことを知った日の翌日を起算日とする4月の期間の満了日。休日なら繰り下げる",
    "所得税法第124条第1項・第125条第1項、国税通則法第10条第1項第2号・第3号・第2項。数え方（読みA）は申告書付表の書き方の例と一致。"
    "相続人等の記録の日付（when.on）を知った日として読むのは語彙の読み（VOC F-R07）",
    (f"{_SHIBO}#2.1", f"{_SHIBO}#2.3", f"{_SHIBO}#6", "docs/measurements/20261109_round3_shibo-shukkoku-fetch-and-calc.md#4"),
    flags=(ReadingFlag.LEGAL_READING,),
)

DEPARTURE_DEADLINE_RULE = _rule(
    "年の中途又は翌年の期限までに出国（納税管理人の届出をしないで国内に住所及び居所を有しないこととなること）をする人の提出期限は出国の時（繰り下げない）",
    "所得税法第2条第1項第42号・第126条第1項・第127条第1項、国税通則法施行令第2条第1項第1号。判断.住所の所在 の foreign の開始日を出国の日と読むのは法令の読み",
    (f"{_SHIBO}#3.1", f"{_SHIBO}#6"),
    flags=(ReadingFlag.LEGAL_READING,),
)

NENMATSU_HOUSING_RULE = _rule(
    "年末調整で控除された住宅借入金等特別控除の額：居住の年分・給与がない・全部の支払者の源泉徴収票が年末調整なしなら0。それ以外は"
    "源泉徴収票の欄が中間表現の語彙にないので、外部で計算した額と0の両端で評価する",
    "租税特別措置法第41条の2の2第1項（居住日の属する年の翌年以後の年末調整）・第6項第2号",
    (f"{_JJ3}#4",),
)
SECTION121_EXCLUDED_RULE = _rule(
    "第121条第1項を適用しない給与：常時2人以下の家事使用人のみに支払う者・国外で支払われたもの（基通121−5(1)(3)）、同族会社の役員等が"
    "その支払者から貸付金の利子・資産の対価などの支払を受ける場合（所令262の2）。欄がなければ当たらないものとする",
    "所得税法第121条第1項ただし書・第184条、所得税法施行令第262条の2、所得税基本通達121−5",
    (f"{_R121}#1", f"{_R121}#2", f"{_R121}#3"),
    flags=(ReadingFlag.LEGAL_READING,),
)

#: 変数名 → その変数の値に付ける規則の根拠（パラメータはトレースか BASIS の関数が別に足す）。
RULES: Mapping[str, tuple[BasisEntry, ...]] = {
    "所得税_源泉徴収税額": (WITHHOLDING_RULE,),
    "所得税_予定納税額": (PREPAYMENT_RULE,),
    "所得税_住宅借入金等特別控除の額": (HOUSING_RULE,),
    "所得税_事業所得等の特例に係る税額控除の額": (EXTERNAL_CREDIT_RULE,),
    "所得税_住宅耐震改修特別控除の額": (EXTERNAL_CREDIT_RULE,),
    "所得税_住宅特定改修特別税額控除の額": (EXTERNAL_CREDIT_RULE,),
    "所得税_認定住宅等新築等特別税額控除の額": (EXTERNAL_CREDIT_RULE,),
    "所得税_事業所得等の特例に係る税額控除の区分": (CREDIT_CATEGORY_RULE,),
    "所得税_住宅耐震改修特別控除等の額": (EXTERNAL_CREDIT_RULE, CREDIT_CATEGORY_RULE),
    "所得税_住宅耐震改修特別控除等の区分": (CREDIT_CATEGORY_RULE,),
    "所得税_申告の種類": (KIND_RULE,),
    "所得税_所得控除の合計": (SUM_DEDUCTIONS_RULE,),
    "所得税_課税総所得金額": (ALLOCATION_RULE, NIL_BELOW_UNIT_RULE, KAZEI_HYOJUN_FLOOR.basis_entry()),
    "所得税_課税退職所得金額": (ALLOCATION_RULE, KAZEI_HYOJUN_FLOOR.basis_entry()),
    "所得税_上場株式等に係る課税配当所得等の金額": (ALLOCATION_RULE, ORDER_RULE, KAZEI_HYOJUN_FLOOR.basis_entry()),
    "所得税_上場株式等に係る課税譲渡所得等の金額": (ALLOCATION_RULE, ORDER_RULE, KAZEI_HYOJUN_FLOOR.basis_entry()),
    "所得税_上場株式等の所得控除の順序": (ORDER_RULE,),
    "所得税_年末調整で控除された住宅借入金等特別控除の額": (NENMATSU_HOUSING_RULE,),
    "所得税_給与等が第121条第1項の適用除外か": (SECTION121_EXCLUDED_RULE,),
    "所得税_課税総所得金額に対する税額": (PROGRESSIVE_RULE,),
    "所得税_課税退職所得金額に対する税額": (PROGRESSIVE_RULE,),
    "所得税_上場株式等に係る課税配当所得等の金額に対する税額": (FLAT_RULE,),
    "所得税_上場株式等に係る課税譲渡所得等の金額に対する税額": (FLAT_RULE,),
    "所得税_算出税額": (SUM_TAX_RULE,),
    "所得税_配当控除の額": (DIVIDEND_CREDIT_RULE, HAITO_FLOOR.basis_entry()),
    "所得税_申告書の配当控除の欄の額": (DIVIDEND_CREDIT_RULE, HAITO_FLOOR.basis_entry()),
    "所得税_基準所得税額": (BASE_TAX_RULE,),
    "所得税_所得税及び復興特別所得税の額": (TOTAL_TAX_RULE,),
    "所得税_申告納税額": (SETTLEMENT_RULE, KAKUTEI_KINGAKU_FLOOR.basis_entry()),
    "所得税_申告書の申告納税額の欄の額": (SETTLEMENT_RULE, KAKUTEI_KINGAKU_FLOOR.basis_entry()),
    "所得税_還付される税額": (SETTLEMENT_RULE, KAKUTEI_KINGAKU_FLOOR.basis_entry()),
    "所得税_第3期分の税額": (SETTLEMENT_RULE, KAKUTEI_KINGAKU_FLOOR.basis_entry()),
    "所得税_確定申告書の提出義務があるか": (OBLIGATION_RULE,),
    "所得税_還付申告ができるか": (REFUND_RETURN_RULE,),
}


def _progressive_basis(taxable: str, tax: str):  # noqa: ANN202
    def build(ctx: BasisContext) -> list[BasisEntry]:
        brackets = brackets_from_parameters(ctx.parameters.所得税.税率)
        base = int(ctx.computed(taxable)[ctx.index])
        value, used = progressive_tax(base, brackets)
        if value != int(ctx.computed(tax)[ctx.index]):
            raise AssertionError(f"{tax} が OpenFisca と純粋関数で食い違う: {ctx.person} {ctx.year}")
        names = [n for b in used for n in b.parameter_names()] or list(brackets[0].parameter_names())
        return [parameter_basis(ctx.root, n, ctx.instant) for n in names]

    return build


def fukko_basis(ctx: BasisContext) -> list[BasisEntry]:
    """復興特別所得税額の根拠：税率のパラメータと、1円未満の端数の根拠（令和7年分は手引き、令和8年分は通達の読み。根拠のない年分は候補で評価）。"""
    out = [parameter_basis(ctx.root, n, ctx.instant) for n in ("所得税.復興特別所得税.税率.分子", "所得税.復興特別所得税.税率.分母")]
    rule = FUKKO_ROUNDING_YEARS.get(ctx.year)
    if rule is not None:
        out.append(rule.basis_entry())
    else:
        out.append(
            BasisEntry(
                type=BasisType.ROUNDING,
                name="復興特別所得税額の1円未満",
                source_kind=None,
                references=(),
                detail={
                    "title": "根拠なし（候補で評価）",
                    "note": "この年分の端数の根拠が登録されていない。候補は evaluated に出る",
                },
            )
        )
    return out


def deadline_basis(ctx: BasisContext) -> list[BasisEntry]:
    """申告期限の根拠：申告の種類ごとの規定、期限の暦年の春分の日・秋分の日（暦要項）と一般の休日（通達）。休日の表の全部は並べない。"""
    kind = str(ctx.computed("所得税_申告の種類")[ctx.index])
    day = np.datetime64(ctx.computed("所得税_申告期限")[ctx.index], "D").astype(object)
    if kind == KIND_DEPARTURE:
        return [DEPARTURE_DEADLINE_RULE]
    if kind in (KIND_DEATH, KIND_DEATH_NEXT_YEAR):
        rule, main = DEATH_DEADLINE_RULE, "所得税.申告期限.死亡の場合の月数"
    else:
        rule, main = DEADLINE_RULE, "所得税.申告期限.第三期の末日"
    if day.year >= 9999:  # 期限が決まらない（入力の分かれ目で未確定）
        return [rule]
    at = f"{day.year}-01-01"
    holidays = (
        "所得税.休日.国民の祝日.春分の日",
        "所得税.休日.国民の祝日.秋分の日",
        "所得税.休日.一般の休日.一月二日",
        "所得税.休日.一般の休日.一月三日",
    )
    return [rule, parameter_basis(ctx.root, main, ctx.instant)] + [parameter_basis(ctx.root, n, at) for n in holidays]


BASIS = {
    "所得税_申告期限": deadline_basis,
    "所得税_課税総所得金額に対する税額": _progressive_basis("所得税_課税総所得金額", "所得税_課税総所得金額に対する税額"),
    "所得税_課税退職所得金額に対する税額": _progressive_basis("所得税_課税退職所得金額", "所得税_課税退職所得金額に対する税額"),
    "所得税_復興特別所得税額": fukko_basis,
}
