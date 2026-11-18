"""段階評価の段「住民税の特定支出控除の申告」（地方税法第313条第11項・第32条第11項。README JM-41・JM-42）。

前年分の所得税につき納税義務を負わない所得割の納税義務者が、所得税の申告書等で特定支出控除（所得税法第57条の2）の適用を受けず、住民税の申告書
（第317条の2第1項・第45条の2第1項）に適用を受ける旨と特定支出の額の合計額を記載して提出したときに限り、同法第57条の2第1項の例により給与所得の計算上
特定支出の額の合計額のうち給与所得控除額の2分の1を超える部分を控除する（docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md §6）。

- 要件（この段が決める。所得税の値は同じ situation の前年分）：
  1. 特定支出の額の合計額が給与所得控除額の2分の1を超える（kyuyo の 所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか）。
  2. 所得税の申告書等で特定支出控除の適用を受けていない（所得税_特定支出控除の適用を受けるか が偽。受けていれば所得税の給与所得に入っていて、
     第313条第2項の「計算の例」で住民税にも及ぶ：仮説 impl-research8 H7）。
  3. 前年分の所得税につき納税義務を負わない：前年分の所得税の額が0（税額控除の後の額〔基準所得税額〕で見る読み、税額控除の前の算出税額で見る読み、
     2026-11-12 の9回目に足した所得税法第120条第1項の確定申告の義務の基準〔算出税額が配当控除の額以下〕で見る読み、2026-11-12 の10回目に足した
     同項の基準に租税特別措置法第41条の2の2第6項第2号の読替え〔配当控除の額に年末調整で控除された住宅借入金等特別控除の額を加える〕を含めた読みの4つの候補。
     読み:住民税の特定支出控除の所得税の納税義務。候補で結論が違う人〔税額控除の後が0で算出税額が正〕がいるときだけ読む）。
  4. 住民税の申告書の記載（選択.住民税の申告 の specific_expense_deduction。読んだときだけ開く1か所：1〜3 に当たる人だけが読む）。
- 当たる人の前年の所得（2026-11-12 の3回目に改めた。JM-42）：「所得税の計算の例」（第313条第2項）で、給与所得から始まる連鎖を所得税と同じ関数で
  計算し直した値を、所得税の各モジュールの窓口から写す：
  給与所得＝income_totals の 所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額（kyuyo の所法57の2① の額から所法64①・所令180② を当てた額）、
  合計所得金額＝income_totals の 所得税_特定支出控除を当てた場合の合計所得金額（公的年金等控除額の区分・所得金額調整控除の第2項・損益通算・一時所得の2分の1 を
  当て直した額。分離課税に係る退職所得のある人は 所得税_特定支出控除を当てた場合の分離課税の退職所得を除いた合計所得金額）、
  損益通算の後の退職所得の金額＝所得税_特定支出控除を当てた場合の損益通算の後の退職所得の金額。
  繰越控除の後の値は variables.py の住民税の雑損失の繰越の計算（calc.jumin_casualty_carryforward）で求める。
  以前（2026-11-12 の2回目）はこの段が所得税の合計所得金額との差で計算し、未払の給与の回収不能額等のある人・公的年金等控除額の区分が変わりうる人・
  分離課税に係る退職所得で区分が変わる人を対象外（JM-42。c-限界）にしていた。窓口が足りないことによるもの（制約ではない）なので (c) として窓口を足して実装した。
  一時所得の2分の1 の1円未満も所得税と同じ候補（所得税_一時所得の2分の1の端数の候補）で丸める（以前はこの段の根拠のない端数の候補だった）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...candidates import Candidate
from ...registry import DecisionSlot, StageContext, StageOutput, StageValue, YearContext

PS8 = "docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md"
H8 = "docs/hypotheses/20261112_impl-research8_tokutei-shishutsu-reading.md"
PS9 = "docs/public-sources/20261112_impl-research9_tokutei-jumin-sources.md"
H9 = "docs/hypotheses/20261112_impl-research9_tokutei-jumin-reading.md"

STAGE = "住民税の特定支出控除の申告"
C_RESIDENT_RETURN = "選択.住民税の申告"
READING = "住民税の特定支出控除の所得税の納税義務"
READING_AFTER_CREDITS = "税額控除の後の所得税の額が0"
READING_BEFORE_CREDITS = "算出税額が0"
READING_DIVIDEND_CREDIT = "算出税額が配当控除の額以下"  # 2026-11-12 の9回目：所得税法第120条第1項の基準（仮説 impl-research9 H1）
#: 2026-11-12 の10回目（ユーザーの指示：D21 R6）：3つ目の候補に、租税特別措置法第41条の2の2第6項第2号の読替え（第120条第1項の「配当控除の額」を
#: 「配当控除の額と年末調整で第41条の2の2第1項により控除される金額との合計額」とする）を含めた変形
READING_DIVIDEND_HOUSING_CREDIT = "算出税額が配当控除の額と年末調整の住宅借入金等特別控除の額の合計額以下"
READINGS = (READING_AFTER_CREDITS, READING_BEFORE_CREDITS, READING_DIVIDEND_CREDIT, READING_DIVIDEND_HOUSING_CREDIT)

# 段が読む所得税の値（同じ situation の前年分）
R_OVER = "所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか"
R_APPLY_IT = "所得税_特定支出控除の適用を受けるか"
R_TAX_AFTER = "所得税_基準所得税額"
R_TAX_BEFORE = "所得税_算出税額"
R_DIVIDEND = "所得税_配当控除の額"
R_HOUSING_YEAR_END = "所得税_年末調整で控除された住宅借入金等特別控除の額"  # 4つ目の候補が読む（措法41の2の2⑥二）
R_SEPARATE = "住民税_分離課税に係る退職所得の金額"
R_G313 = "所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額"
R_TOTAL = "所得税_特定支出控除を当てた場合の合計所得金額"
R_TOTAL_SEP = "所得税_特定支出控除を当てた場合の分離課税の退職所得を除いた合計所得金額"
R_TAISHOKU = "所得税_特定支出控除を当てた場合の損益通算の後の退職所得の金額"
READS = (R_OVER, R_APPLY_IT, R_TAX_AFTER, R_TAX_BEFORE, R_DIVIDEND, R_HOUSING_YEAR_END, R_SEPARATE, R_G313, R_TOTAL, R_TOTAL_SEP, R_TAISHOKU)

W_APPLY = "住民税_住民税の申告書で特定支出控除を受けるか"
W_KYUYO = "住民税_第313条第11項の給与所得の金額"
W_TOTAL = "住民税_第313条第11項の合計所得金額"
W_TAISHOKU = "住民税_第313条第11項の損益通算の後の退職所得の金額"
WRITES = (W_APPLY, W_KYUYO, W_TOTAL, W_TAISHOKU)

APPLY_RULE = BasisEntry(
    type=BasisType.RULE,
    name="住民税の申告書だけで受ける特定支出控除：所得税の納税義務がなく所得税で受けない人が住民税の申告書に記載したとき、給与所得から2分の1を超える部分を控除",
    source_kind=SourceKind.LAW,
    law=(
        "地方税法第313条第11項・第32条第11項（同法第五十七条の二第一項の規定の例により）。申告書の記載は 選択.住民税の申告 の specific_expense_deduction。"
        "総務省令で定める必要な書類（地方税法施行規則第1条の12：所得税法施行令第167条の4 の事項を記載した特定支出に関する明細書と第167条の5 の書類）の添付は"
        "その選択に含める（仮説 impl-research9 H2）。所得税の申告書等で受けた人は第313条第2項の計算の例で所得税の給与所得に従う"
    ),
    references=(f"{PS8}#6", f"{PS8}#1", f"{PS9}#3"),
)
OBLIGATION_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "「前年分の所得税につき納税義務を負わない」：前年分の所得税の額が0（税額控除の後・税額控除の前・所得税法第120条第1項の基準・"
        "同項の基準に租税特別措置法第41条の2の2第6項第2号の読替えを含めたものの4つの読みの候補）"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "地方税法第313条第11項。「納税義務を負わない」の定義は地方税法・同施行令・同施行規則になく、総務省の取扱通知・改正の説明も見つからなかった"
        "（impl-research9：一次情報で1つに決まらない）。税額控除の後の所得税の額（基準所得税額）が0 と読む読み、"
        "税額控除の前の算出税額が0 と読む読み、所得税法第120条第1項の確定申告の義務の基準（算出税額が配当控除の額を超えない）と読む読み、"
        "同項の基準に租税特別措置法第41条の2の2第6項第2号の読替え（「配当控除の額」を年末調整で同条第1項により控除される金額との合計額とする）を"
        "含めて読む読みの4つで評価する"
        "（読み:住民税の特定支出控除の所得税の納税義務。候補で結論が違う人がいるときだけ：D21 R6・D22 S1）"
    ),
    references=(f"{PS8}#6", f"{PS9}#2", f"{PS9}#2.2", "docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md#4"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": f"{H8}#H10", "reading_2": f"{H9}#H1"},
)
OFFSET_RULE = BasisEntry(
    type=BasisType.RULE,
    name="住民税の特定支出控除の後の前年の所得：給与所得から始まる連鎖を所得税の計算の例で計算し直す（回収不能額等・公的年金等控除額の区分・所得金額調整控除・損益通算）",
    source_kind=SourceKind.LAW,
    law=(
        "地方税法第313条第2項（所得税法の計算の例）・第11項。所得税法第57条の2第1項・第64条第1項・第35条第4項・第69条、同施行令第180条第2項・第198条、"
        "租税特別措置法第41条の3の11第2項。値は所得税の各モジュールの窓口（所得税_特定支出控除を当てた場合の…）が所得税と同じ関数で計算する。"
        "一時所得の2分の1 の1円未満は所得税と同じ（令和7年分は手引きの切捨て、令和8年分は所得税の根拠のない端数の候補）"
    ),
    references=(f"{PS8}#6", "docs/public-sources/20261109_round2_genka-laws-and-nta.md#6.1", "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md#1.1"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": f"{H8}#H10"},
)
STAGE_BASIS = (APPLY_RULE, OBLIGATION_RULE, OFFSET_RULE)

RESIDENT_SPECIFIC_CANDIDATES = (
    Candidate(False, "住民税の申告書に特定支出控除の適用を受ける旨を記載しない"),
    Candidate(True, "住民税の申告書に特定支出控除の適用を受ける旨と特定支出の額の合計額を記載する"),
)


# ---------------------------------------------------------------------------
# 純粋関数
# ---------------------------------------------------------------------------


def owes_income_tax(
    after_credits: int, before_credits: int, dividend_credit: int, reading: str | None, housing_year_end: int = 0
) -> bool | None:
    """前年分の所得税につき納税義務を負うか。読みで分かれる（税額控除の後が0で前が正）ときは reading（None なら分かれ目を読む：戻り値 None）。

    候補（READINGS）：税額控除の後が0 なら負わない／算出税額が0 のときだけ負わない／算出税額が配当控除の額以下なら負わない（所得税法第120条第1項の基準）／
    算出税額が配当控除の額と年末調整で控除された住宅借入金等特別控除の額（housing_year_end）の合計額以下なら負わない（同項の基準に
    租税特別措置法第41条の2の2第6項第2号の読替えを含めたもの）。
    税額控除の後が0 で算出税額が正の人は、前の2つの候補で必ず結論が違うので、3つ目の候補で同じになる人も読む。
    """
    if after_credits > 0:
        return True
    if before_credits <= 0:
        return False
    if reading is None:
        return None
    if reading == READING_AFTER_CREDITS:
        return False
    if reading == READING_BEFORE_CREDITS:
        return True
    if reading == READING_DIVIDEND_CREDIT:
        return before_credits > dividend_credit
    if reading == READING_DIVIDEND_HOUSING_CREDIT:
        return before_credits > dividend_credit + housing_year_end
    raise ValueError(f"住民税の特定支出控除の所得税の納税義務の読みが候補にない：{reading}")


# ---------------------------------------------------------------------------
# 判断・選択の1か所（選択.住民税の申告 の specific_expense_deduction）
# ---------------------------------------------------------------------------


def specific_key(pid: str, fiscal: int) -> str:
    return f"{pid}:{fiscal}:特定支出控除"


def resident_specific_slots(ctx: YearContext) -> list[DecisionSlot]:
    """特定支出の候補の支出（specific_expense）の記録がある人の、その年度分の住民税の申告書の特定支出控除の記載（読んだときだけ開く）。"""
    w = ctx.window("住民税", "年度")
    if w is None:
        return []
    fy = w.time.value
    payers = {r["roles"].get("payer") for r in ctx.records("specific_expense")}
    out: list[DecisionSlot] = []
    for pid in ctx.persons:
        if pid not in payers:
            continue
        out.append(
            DecisionSlot(
                key=specific_key(pid, fy),
                target={
                    "person": pid,
                    "fiscal_year": fy,
                    "決めるもの": (
                        "その年度分の住民税の申告書に特定支出控除の適用を受ける旨と特定支出の額の合計額を記載し、明細書等を添付するか"
                        "（選択.住民税の申告 の specific_expense_deduction。地方税法第313条第11項）"
                    ),
                },
                matches=lambda c, pid=pid, fy=fy: (
                    c["subject"].get("person") == pid and c.get("when", {}).get("fiscal_year") == fy and "specific_expense_deduction" in c["value"]
                ),
                candidates=RESIDENT_SPECIFIC_CANDIDATES,
                persons=(pid,),
                lazy=True,
            )
        )
    return out


def resident_specific_value(rec: Mapping[str, Any]) -> Any:
    return bool(rec["value"].get("specific_expense_deduction"))


# ---------------------------------------------------------------------------
# 段
# ---------------------------------------------------------------------------


def _int(v: StageValue) -> int:
    return int(v.value)


def run(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    w = ctx.window("住民税", "年度")
    fiscal = w.time.value if w is not None else ctx.year + 1
    for p in ctx.persons:
        over, apply_it = ctx.value(R_OVER, p), ctx.value(R_APPLY_IT, p)
        used: list[StageValue] = [over, apply_it]
        if not bool(over.value) or bool(apply_it.value):
            _not_applied(out, p, used)
            continue
        after, before = ctx.value(R_TAX_AFTER, p), ctx.value(R_TAX_BEFORE, p)
        used += [after, before]
        owes = owes_income_tax(_int(after), _int(before), 0, None)
        if owes is None:
            dividend = ctx.value(R_DIVIDEND, p)  # 第3・第4の候補が読む（分かれ目の人だけ）
            housing = ctx.value(R_HOUSING_YEAR_END, p)  # 第4の候補が読む（措法41の2の2⑥二）
            used += [dividend, housing]
            owes = owes_income_tax(_int(after), _int(before), _int(dividend), ctx.reading(READING), _int(housing))
        if owes:
            _not_applied(out, p, used)
            continue
        d = ctx.decision(C_RESIDENT_RETURN, specific_key(p, fiscal))
        if d.value is not True:
            _not_applied(out, p, used, d.record_ids, d.states)
            continue
        separate = ctx.value(R_SEPARATE, p)
        g = ctx.value(R_G313, p)
        total = ctx.value(R_TOTAL_SEP if _int(separate) > 0 else R_TOTAL, p)
        used += [separate, g, total]
        taishoku = 0
        if _int(separate) <= 0:  # 分離課税に係る退職所得の人は、退職所得を住民税の前年の所得に入れない（JM-20）
            t = ctx.value(R_TAISHOKU, p)
            used.append(t)
            taishoku = _int(t)
        ids, states = d.record_ids, d.states
        out.set(W_APPLY, p, True, ids, states, uses=used, basis=STAGE_BASIS)
        out.set(W_KYUYO, p, _int(g), ids, states, uses=used, basis=STAGE_BASIS)
        out.set(W_TOTAL, p, max(0, _int(total)), ids, states, uses=used, basis=STAGE_BASIS)
        out.set(W_TAISHOKU, p, taishoku, ids, states, uses=used, basis=STAGE_BASIS)
    return out


def _not_applied(out: StageOutput, p: str, used: list[StageValue], ids: Any = (), states: Any = ()) -> None:
    out.set(W_APPLY, p, False, ids, states, uses=used)
    for v in WRITES[1:]:
        out.set(v, p, 0, uses=used)


__all__ = [
    "C_RESIDENT_RETURN",
    "READING",
    "READINGS",
    "READS",
    "STAGE",
    "STAGE_BASIS",
    "WRITES",
    "owes_income_tax",
    "resident_specific_slots",
    "resident_specific_value",
    "run",
    "specific_key",
]
