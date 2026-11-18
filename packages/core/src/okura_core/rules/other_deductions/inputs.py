"""規則モジュール other_deductions の situation への写し方（build_inputs）と、判断・選択の1か所の宣言（decisions）。

値の作り方は medical.py（医療費）・insurance.py（社会保険料・掛金・生命保険料・地震保険料）・donations.py（寄附）。
ここは、それらを束ねて ModuleInputs（全員分の入力変数と対象外）にするだけ。
"""

from __future__ import annotations

from collections.abc import Iterable

from ...registry import DecisionSlot, DecisionSpec, ModuleInputs, YearContext
from .casualty import V_LOSS, V_RELATED, CasualtyYear
from .donations import CREDIT_VARS, V_DONATION, DonationYear, excluded_value
from .facts import (
    C_DONATION,
    C_INSURANCE,
    C_PREPAID,
    C_SELFMED,
    J_CASUALTY,
    J_DONATION,
    J_LIFE,
    J_RANGE,
    J_REIMB,
    J_SEIKEI,
    J_SELFMED,
    P_ESTIMATE,
    Acc,
)
from .insurance import LIFE_VARS, V_MUTUAL, V_OLD_LONG, V_QUAKE, V_REGIME, V_SOCIAL, InsuranceYear
from .kinship import relation_index
from .life_special import seikei_slots as life_special_seikei_slots
from .medical import NOTICE_VARS, V_CHOICE, V_MEDICAL, V_SELFMED, MedicalYear

#: 金額の入力変数（build_inputs が全員に書く）。
INT_INPUTS: tuple[str, ...] = (
    V_MEDICAL, V_SELFMED, *NOTICE_VARS, V_SOCIAL, V_MUTUAL, *LIFE_VARS, V_QUAKE, V_OLD_LONG, V_DONATION, V_LOSS, V_RELATED, *CREDIT_VARS.values()
)  # fmt: skip


def build_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    acc = Acc(ctx.persons)
    idx = relation_index(ctx.ir)
    MedicalYear(ctx, idx).inputs(acc)
    ins = InsuranceYear(ctx, idx)
    ins.social(acc)
    ins.mutual_aid(acc)
    ins.life_and_quake(acc)
    DonationYear(ctx).inputs(acc)
    CasualtyYear(ctx, idx).inputs(acc)
    acc.write(out, INT_INPUTS, {V_CHOICE: False, V_REGIME: "both"})
    return out


def _unique(slots: Iterable[DecisionSlot]) -> list[DecisionSlot]:
    seen: dict[str, DecisionSlot] = {}
    for s in slots:
        seen.setdefault(s.key, s)
    return [seen[k] for k in sorted(seen)]


def _seikei(ctx: YearContext) -> list[DecisionSlot]:
    idx = relation_index(ctx.ir)
    return _unique(
        [*MedicalYear(ctx, idx).seikei_slots(), *InsuranceYear(ctx, idx).seikei_slots(), *life_special_seikei_slots(ctx), *CasualtyYear(ctx, idx).seikei_slots()]
    )


def _range(ctx: YearContext) -> list[DecisionSlot]:
    return MedicalYear(ctx).range_slots()


def _reimb(ctx: YearContext) -> list[DecisionSlot]:
    return MedicalYear(ctx).reimbursement_slots()


def _label(ctx: YearContext) -> list[DecisionSlot]:
    return MedicalYear(ctx).label_slots()


def _choice(ctx: YearContext) -> list[DecisionSlot]:
    return MedicalYear(ctx).choice_slots()


def _life(ctx: YearContext) -> list[DecisionSlot]:
    return InsuranceYear(ctx).life_slots()


def _regime(ctx: YearContext) -> list[DecisionSlot]:
    return InsuranceYear(ctx).regime_slots()


def _prepaid(ctx: YearContext) -> list[DecisionSlot]:
    return InsuranceYear(ctx).prepaid_slots()


def _donation(ctx: YearContext) -> list[DecisionSlot]:
    return DonationYear(ctx).judgment_slots()


def _donation_choice(ctx: YearContext) -> list[DecisionSlot]:
    return DonationYear(ctx).choice_slots()


def _casualty(ctx: YearContext) -> list[DecisionSlot]:
    return CasualtyYear(ctx).slots()


def _casualty_unavoidable(ctx: YearContext) -> list[DecisionSlot]:
    return CasualtyYear(ctx).unavoidable_slots()


def _none(ctx: YearContext) -> list[DecisionSlot]:
    """補塡の見込額は支払の記録を対象にするので、「使う判断」として宣言する（1か所の値としては読まない：medical.py が見込額ごとに読む）。"""
    return []


DECISIONS: tuple[DecisionSpec, ...] = (
    DecisionSpec(J_SEIKEI, _seikei),
    DecisionSpec(J_RANGE, _range),
    DecisionSpec(J_REIMB, _reimb),
    DecisionSpec(J_SELFMED, _label),
    DecisionSpec(C_SELFMED, _choice),
    DecisionSpec(J_LIFE, _life),
    DecisionSpec(C_INSURANCE, _regime, value_of=lambda rec: rec["value"].get("life_insurance_regime")),
    DecisionSpec(C_PREPAID, _prepaid),
    DecisionSpec(J_DONATION, _donation, value_of=excluded_value),
    DecisionSpec(C_DONATION, _donation_choice),
    DecisionSpec(J_CASUALTY, _casualty, value_of=lambda rec: rec["value"].get("not_ordinarily_necessary_asset")),
    # 同じ判断の種類の別の欄（所令第206条第1項第2号の3年の期間）：1か所の key は「<事象>:やむを得ない事情」
    DecisionSpec(J_CASUALTY, _casualty_unavoidable, value_of=lambda rec: rec["value"].get("unavoidable_circumstances")),
    DecisionSpec(P_ESTIMATE, _none),
)

__all__ = ["DECISIONS", "INT_INPUTS", "build_inputs"]
