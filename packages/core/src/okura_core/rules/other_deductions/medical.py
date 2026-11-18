"""規則モジュール other_deductions：医療費の前処理（中間表現の明細 → 支払者の 補塡後の医療費の額・特定一般用医薬品等購入費の額）。

HANDOFF D5（改）：法令が関わる集計（補塡の限度・生計の判定）は判定コアで行う。R4 H3.3 案A：支払者の入力変数にする。

- 年分：支払日（when.on）の年（所得税基本通達73−2：現実に支払った医療費）。入院の保証金（medical_kinds に deposit）は、入院費用に充当された日
  （attributes.deposit_applied_on）の年分の医療費とし（質疑応答事例 05/86）、記録の額を充当された額と読む（法令の読み。充当されずに返還された
  部分は記録の額に含めない約束）。充当の日がなければ c-入力（入力すれば決まる）。
- 誰が控除するか：支払者。受診者が支払者自身か、受診時（incurred_on）又は支払時（when.on）に支払者と生計を一にする親族
  （所基通73−1、質疑応答事例 05/57）。親族は kinship.py。生計は 判断.生計を一にする（その日の現況の1か所。未入力なら両方で評価）。
- 医療費の範囲：所令第207条各号に直接当たる種類は範囲に入るものとし（法令の読み）、目的・必要性で決まる種類は
  判断.医療費の範囲（未入力なら両方で評価：D21 R6）。
- 補塡（reimbursement と 見積り.補塡の見込額）：対象の医療費の集合ごとに、その合計を限度として差し引く（TA1120・質疑応答事例 05/28）。
  受取人は問わない（05/26）。対象が2つの年分・2人の支払にまたがれば、支払った額に応じてあん分する（05/61）。補塡に当たるかは
  給付の種類（通達73−8・73−9）か 判断.補塡の対象。見込額は印 見積り（D21 R2）。
  対象の集合が一部だけ重なる補塡は、補塡ごとの限度の当て方の一次情報がないので、(a) 重なる集合をまとめて合計を限度とする読みと
  (b) 補塡ごとにその対象の合計を限度とし、医療費ごとにその額を限度とする読みの両方で計算し、差し引く額が分かれれば未確定（決める手段は一次情報）。
  値は (a) で入れる。
- セルフメディケーション税制の対象の購入に補塡があるとき（特定一般用医薬品等購入費は補塡される部分を除く：措法41の17）、同じ補塡の対象の
  ほかの医療費との割り振りの一次情報がないので、支払った額のあん分・対象の購入から先に・ほかの医療費から先にの3つで計算し、分かれれば未確定。
- セルフメディケーション税制：申告者本人のその年の取組（health_checkup_record）と、対象の表示（selfmed_label。判断で上書き）。
  通常の医療費控除との選択は 選択.医療費控除かセルフメディケーション税制か（未入力なら両方で評価：D22 S20）。
- 医療費通知（medical_expense_notice。2026-11-12）：年分は記録の payment_year。支払者の補塡後の医療費に ㋐−min(㋑, ㋐) を足す
  （補塡は通知の記録ごとに ㋐ を限度とし、ほかの医療費から差し引かない：手引き 6_01 ❶(3)・TA1120。記録ごとに限度を当てるのは法令の読み）。
  受診者の要件は明細と同じ（支払者自身か、生計を一にする親族：手引き ❶※2）。生計を判定する日は通知の対象の期間の終わりの日（when.to_on。
  受診者が死亡していれば死亡の日と早い方）とする（通達73−1 の受診時の現況を通知の期間に当てる法令の読み）。医療費通知に記載された医療費は
  所令207 の診療・治療の対価として範囲の判断を引かない（法令の読み）。notice_id を書いた medical_payment は明細から除く（二重計上を防ぐ約束：
  手引き ❷「❶に記入したものについては、記入しないでください」）。矛盾（notice_id の通知と支払者・受診者・年が違う、㋐ が通知の額を超える、
  通知に載った支払を対象にする補塡）は c-入力。様式の ❶ の3欄の値（所得税_医療費通知に記載された医療費の額 など）も同じ要件で数える。

docs：docs/public-sources/20261109_impl-prep_iryohi-law-text.md、docs/public-sources/20261109_impl-prep_iryohi-nta-mhlw.md、
docs/public-sources/20261112_impl-research6_forms-iryohi-tsuchi.md（医療費通知）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from ...candidates import Candidate
from ...registry import DecisionSlot, YearContext
from ...result import Split, State
from .facts import (
    C_SELFMED,
    J_RANGE,
    J_REIMB,
    J_SEIKEI,
    J_SELFMED,
    P_ESTIMATE,
    Acc,
    d,
    heads_for,
    known_seikei,
    not_implemented,
    on_year,
    reading_split,
    relative_on,
    seikei_key,
    seikei_slot,
    states_of,
)
from .kinship import RelationIndex, relation_index

V_MEDICAL = "所得税_補塡後の医療費の額"
V_SELFMED = "所得税_特定一般用医薬品等購入費の額"
V_CHOICE = "所得税_セルフメディケーション税制の選択"
#: 医療費控除の明細書の「1 医療費通知に記載された事項」の3欄（filing.py の入力変数）。
V_NOTICE_AMOUNT = "所得税_医療費通知に記載された医療費の額"
V_NOTICE_PAID = "所得税_医療費通知のその年中に実際に支払った医療費の額"
V_NOTICE_REIMB = "所得税_医療費通知の補塡される金額"
NOTICE_VARS = (V_NOTICE_AMOUNT, V_NOTICE_PAID, V_NOTICE_REIMB)

_IRL = "docs/public-sources/20261109_impl-prep_iryohi-law-text.md"
_IRN = "docs/public-sources/20261109_impl-prep_iryohi-nta-mhlw.md"

#: 所令第207条各号・通達73−3(3)・TA1122 の10・11 に直接当たる種類（医療費の範囲に入るものとする。法令の読み）。
KINDS_BY_ORDER = frozenset(
    {"medical_treatment", "hospitalization", "midwifery", "suction_care", "transplant_mediation", "welfare_levy"}
)
#: 補塡に当たる給付の種類（通達73−8(1)(2)）・当たらない種類（通達73−9(2)(3)）。互助会の給付金・その他は判断で決める。
COMPENSATING_BENEFITS: Mapping[str, bool] = {
    "hospitalization_benefit": True,
    "high_cost_medical_care_benefit": True,
    "childbirth_lump_sum": True,
    "sickness_allowance": False,
    "maternity_allowance": False,
    "sympathy_payment": False,
}
#: セルフメディケーション税制の取組の種類（告示181・TA1133 の5つ）。other は取組に当たるか決められない。
TORIKUMI = frozenset({"specific_health_checkup", "vaccination", "periodic_health_checkup", "health_examination", "cancer_screening"})

REIMB_CANDIDATES = (
    Candidate({"compensates_medical_expenses": True}, "補塡に当たる"),
    Candidate({"compensates_medical_expenses": False}, "補塡に当たらない"),
)
SELFMED_LABEL_CANDIDATES = (
    Candidate({"eligible_item": True}, "対象の医薬品"),
    Candidate({"eligible_item": False}, "対象でない"),
)

R_DEPOSIT = (
    "入院の保証金（medical_kinds に deposit）に、入院費用に充当された日（attributes.deposit_applied_on）がない。充当の年分（質疑応答事例 05/86）を"
    "決められない。充当された日を入力すれば決まる"
)
T_OVERLAP = "対象の集合が一部だけ重なる補塡の限度の当て方"
T_SELFMED_REIMB = "セルフメディケーション税制の対象の購入とほかの医療費への補塡の割り振り"
R_PATIENT_GONE = "受診者がこの年分に生存していない人で、死亡日の記録がないか、受診の日（incurred_on）が死亡の日より後（質疑応答事例 05/57 の受診した時の現況を決められない）"
R_KIN_NOT_DERIVED = (
    "受診者が支払者の配偶者その他の親族であることを、中間表現の関係（親子・養子縁組・婚姻）から導けない"
    "（記録の書き忘れと区別できないので、控除の対象から黙って外さない）"
)
R_KIN_UNDECIDED = "受診者が支払者の親族かを決められない（関係の記録の区間・死亡の記録を入力すれば決まる）"
R_REIMB_NO_TARGET = "補塡に当たりうる給付に対象の医療費（target_payment_ids）がなく、どの医療費から差し引くか決められない（通達73−8、TA1120）"
R_ESTIMATE_DUP = "同じ医療費を対象にする、同じ種類の確定した補塡と見込額がある。見込額が確定した額に置き換わったのか決められない（通達73−10）"
R_ESTIMATE_AMBIGUOUS = "補塡の見込額の給付の種類が互助会の給付金・その他で、補塡に当たるか決められない（判断.補塡の対象は見込額に使えない）"
R_ESTIMATE_YEAR = "補塡の見込額の年分（when.tax_year）が対象の医療費を支払った年分と違う"
#: 補塡のあん分（質疑応答事例 05/61）の1円未満の端数（根拠なし。RoundingSlotSpec(variable=None) の名前）。
REIMBURSEMENT_ROUNDING = "医療費の補塡のあん分の端数"
R_SELFMED_YEAR = "判断.セルフメディケーション表示の上書きが、支払った年分と違う年分（tax_year）を指す。この版では年分を移さない"
R_TORIKUMI_OTHER = "取組の種類が other だけで、告示の取組（健康診査・予防接種・定期健康診断・特定健康診査等・がん検診）に当たるか決められない。取組の種類を入力すれば決まる"
R_CHOSE_WITHOUT_TORIKUMI = "セルフメディケーション税制を選択したが、申告者本人のその年の取組の記録がない（租税特別措置法第41条の17第1項の要件）"
R_NOTICE_LINK = (
    "医療費の支払（medical_payment）の notice_id が指す医療費通知と、支払者・受診者・年（支払った日の年と通知の payment_year）が違う。"
    "通知の記録か支払の notice_id を直せば決まる"
)
R_NOTICE_OVER = (
    "医療費通知の、その年中に実際に支払った医療費の額（paid_in_year：明細書の㋐）が、通知に記載された医療費の額（notice_amount）を超える"
    "（㋐は通知に記載された医療費の額のうちの額）"
)
R_NOTICE_REIMB = (
    "医療費通知に記載された支払（notice_id のある medical_payment）を対象にする補塡・補塡の見込額がある。通知の分の補塡は通知の reimbursed"
    "（明細書の㋑）に書く（二重に差し引かない）"
)
R_NOTICE_NO_END = "医療費通知の対象の期間の終わりの日（when.to_on）がなく、受診者と生計を一にするかを判定する日を決められない。期間の終わりの日を入力すれば決まる"


@dataclass(frozen=True)
class Payment:
    id: str
    rec: Mapping[str, Any]
    payer: str
    patient: str
    paid_on: _dt.date
    incurred_on: _dt.date
    amount: int
    kinds: frozenset[str]

    @classmethod
    def of(cls, rec: Mapping[str, Any]) -> Payment:
        a = rec["attributes"]
        kinds = frozenset(a["medical_kinds"])
        paid = d(rec["when"]["on"])
        if "deposit" in kinds and a.get("deposit_applied_on"):
            paid = d(a["deposit_applied_on"])  # 入院の保証金は入院費用に充当された年分の医療費（質疑応答事例 05/86）
        if "deposit" in kinds and len(kinds) > 1:
            kinds = kinds - {"deposit"}  # 充当された費用の種類（入院など）で範囲を決める
        return cls(rec["id"], rec, rec["roles"]["payer"], rec["roles"]["patient"], paid, d(a["incurred_on"]), rec["amounts"]["amount"], kinds)


@dataclass(frozen=True)
class Notice:
    """医療費通知の記録1件（1つの通知の、1人の受診者の、1つの年分の分）。"""

    id: str
    rec: Mapping[str, Any]
    payer: str
    patient: str
    start: _dt.date
    end: _dt.date | None
    year: int
    notice_amount: int
    paid: int  # ㋐
    reimbursed: int  # ㋑（記録の額。限度は当てる前）

    @classmethod
    def of(cls, rec: Mapping[str, Any]) -> Notice:
        w, a = rec["when"], rec["amounts"]
        return cls(
            rec["id"], rec, rec["roles"]["payer"], rec["roles"]["patient"], d(w["from_on"]), d(w["to_on"]) if w.get("to_on") else None,
            rec["attributes"]["payment_year"], a["notice_amount"], a["paid_in_year"], a.get("reimbursed", 0),
        )  # fmt: skip


@dataclass
class Plan:
    """支払1件の、受診者の要件の判定の段取り（判断を引く前に決まる部分）。"""

    excluded: str | None = None
    self_paid: bool = False
    seikei_dates: list[_dt.date] = field(default_factory=list)  # 判断を引く日（受診時・支払時。親族と導けた日だけ）
    undecided: str = ""  # 親族を決められない日があるときの説明（生計の判断で対象にならなかったときに対象外にする）
    kin_ids: tuple[str, ...] = ()
    kin_states: frozenset[State] = frozenset()
    outside: bool = False  # 受診者がこの年分に生存していない（分かれ目の人は支払者だけ）


@dataclass(frozen=True)
class Source:
    """補塡1件（確定した給付か見込額）。"""

    id: str
    estimate: bool
    amount: int
    benefit_type: str
    targets: tuple[str, ...]  # 記録の対象（判断で替わりうる）
    tax_year: int | None
    received_year: int | None
    states: frozenset[State]
    judged: bool  # 判断.補塡の対象の1か所を宣言する


class MedicalYear:
    """年分の医療費の前処理の段取り。slots（判断・選択の1か所）と inputs（値）が同じ段取りを使う（同じ1か所だけを引く）。"""

    def __init__(self, ctx: YearContext, idx: RelationIndex | None = None) -> None:
        self.ctx = ctx
        self.year = ctx.year
        self.persons = set(ctx.persons)
        self.idx = idx if idx is not None else relation_index(ctx.ir)
        self.all_payments = {r["id"]: Payment.of(r) for r in ctx.records("medical_payment")}
        all_notices = {r["id"]: Notice.of(r) for r in ctx.records("medical_expense_notice")}
        self.notices = sorted(
            (n for n in all_notices.values() if n.year == self.year and n.payer in self.persons), key=lambda n: n.id
        )
        #: notice_id を書いた支払（通知の ㋐ で数える。補塡の対象にしない）と、そのうち通知と食い違う支払 → 理由
        self.notice_linked = {pid for pid, p in self.all_payments.items() if p.rec["attributes"].get("notice_id")}
        self.notice_mismatch: dict[str, str] = {}
        for pid in self.notice_linked:
            p = self.all_payments[pid]
            n = all_notices.get(p.rec["attributes"]["notice_id"])
            if n is None or (n.payer, n.patient, n.year) != (p.payer, p.patient, p.paid_on.year):
                self.notice_mismatch[pid] = R_NOTICE_LINK
        self.payments = sorted(
            (
                p for p in self.all_payments.values()
                if p.paid_on.year == self.year and p.payer in self.persons and (p.id not in self.notice_linked or p.id in self.notice_mismatch)
            ),
            key=lambda p: p.id,
        )  # fmt: skip
        self._payments_by_payer: dict[str, list[Payment]] = {}
        for p in self.payments:
            self._payments_by_payer.setdefault(p.payer, []).append(p)
        self._choices_by_person: dict[str, list[Mapping[str, Any]]] = {}
        for c in ctx.choices(C_SELFMED):
            if c["when"]["tax_year"] == self.year:
                self._choices_by_person.setdefault(c["subject"]["person"], []).append(c)
        self.plans = {p.id: self._plan(p) for p in self.payments}
        self.notice_plans = {n.id: self._notice_plan(n) for n in self.notices}
        self.sources = self._sources()
        self.torikumi: dict[str, list[Mapping[str, Any]]] = {}
        for r in ctx.records("health_checkup_record"):
            if on_year(r) == self.year:
                self.torikumi.setdefault(r["roles"]["person"], []).append(r)

    # --- 受診者の要件 ---

    def _plan(self, p: Payment) -> Plan:
        if p.id in self.notice_mismatch:
            return Plan(excluded=self.notice_mismatch[p.id])
        if "deposit" in p.rec["attributes"]["medical_kinds"] and not p.rec["attributes"].get("deposit_applied_on"):
            return Plan(excluded=R_DEPOSIT)
        if p.patient == p.payer:
            return Plan(self_paid=True)
        dates = [p.paid_on, p.incurred_on]
        outside = p.patient not in self.persons
        if outside:
            # 受診者がこの年分に生存していない（前年以前に死亡）：受診した時（医療費を支出すべき事由が生じた時）に生計を一にしていれば、
            # 支払った相続人等の医療費になる（質疑応答事例 05/57・通達73−1）。死亡の後に受診した日・死亡日のない人は決められない
            death = self.ctx.death_on(p.patient)
            if death is None or p.incurred_on > death:
                return Plan(excluded=R_PATIENT_GONE)
            dates = [p.incurred_on]
        rel = relative_on(self.idx, p.payer, p.patient, dates)
        usable = rel.dates_where(True)
        if not usable:
            if rel.dates_where(None):
                return Plan(excluded=f"{R_KIN_UNDECIDED}（{rel.notes}）")
            return Plan(excluded=R_KIN_NOT_DERIVED)
        dates = usable
        for on in usable:  # 判断で生計を一にすると決まる日があれば、その日だけを引く
            if known_seikei(self.ctx, p.payer, p.patient, on) is True:
                dates = [on]
                break
        undecided = f"{R_KIN_UNDECIDED}（{rel.notes}）" if rel.dates_where(None) else ""
        return Plan(seikei_dates=dates, undecided=undecided, kin_ids=rel.ids, kin_states=rel.states, outside=outside)

    def _notice_plan(self, n: Notice) -> Plan:
        """医療費通知の受診者の要件の段取り。生計を判定する日は通知の対象の期間の終わりの日（死亡していれば死亡の日と早い方。法令の読み）。"""
        if n.paid > n.notice_amount:
            return Plan(excluded=R_NOTICE_OVER)
        if n.patient == n.payer:
            return Plan(self_paid=True)
        if n.end is None:
            return Plan(excluded=R_NOTICE_NO_END)
        on = n.end
        outside = n.patient not in self.persons
        if outside:
            death = self.ctx.death_on(n.patient)
            if death is None or n.start > death:
                return Plan(excluded=R_PATIENT_GONE)
            on = min(on, death)
        rel = relative_on(self.idx, n.payer, n.patient, [on])
        if not rel.dates_where(True):
            if rel.dates_where(None):
                return Plan(excluded=f"{R_KIN_UNDECIDED}（{rel.notes}）")
            return Plan(excluded=R_KIN_NOT_DERIVED)
        return Plan(seikei_dates=[on], kin_ids=rel.ids, kin_states=rel.states, outside=outside)

    def needs_range(self, p: Payment) -> bool:
        return bool(p.kinds - KINDS_BY_ORDER) or bool(heads_for(self.ctx, J_RANGE, "payment_id", p.id))

    def eligible(self, p: Payment, acc: Acc, var: str) -> bool:
        """受診者の要件を満たすか（判断を引く）。満たさないなら False、決められなければ対象外にして False。"""
        return self._eligible(self.plans[p.id], p.payer, p.patient, p.id, p.rec, acc, (var,))

    def _eligible(
        self, plan: Plan, payer: str, patient: str, rid: str, rec: Mapping[str, Any], acc: Acc, variables: tuple[str, ...]
    ) -> bool:
        for var in variables:
            acc.note(var, payer, [rid], states_of(rec))
        if plan.excluded:
            for var in variables:
                acc.exclude(var, payer, not_implemented(plan.excluded, [rid]))
            return False
        if plan.self_paid:
            return True
        for var in variables:
            acc.note(var, payer, plan.kin_ids, plan.kin_states)
        ok = False
        for on in plan.seikei_dates:
            dec = self.ctx.decision(J_SEIKEI, seikei_key(payer, patient, on))
            for var in variables:
                acc.note_decided(var, payer, dec)
            ok = ok or bool(dec.value)
        if not ok and plan.undecided:
            for var in variables:
                acc.exclude(var, payer, not_implemented(plan.undecided, [rid]))
        return ok

    # --- 補塡 ---

    def _sources(self) -> list[Source]:
        out: list[Source] = []
        for r in self.ctx.records("reimbursement"):
            a = r["attributes"]
            judged = bool(heads_for(self.ctx, J_REIMB, "reimbursement_id", r["id"])) or a["benefit_type"] not in COMPENSATING_BENEFITS
            out.append(
                Source(r["id"], False, r["amounts"]["amount"], a["benefit_type"], tuple(a.get("target_payment_ids", ())),
                       None, on_year(r), states_of(r), judged)
            )
        for j in self.ctx.judgments(P_ESTIMATE):
            v = j["value"]
            out.append(
                Source(j["id"], True, v["estimated_amount"], v["benefit_type"], tuple(j["subject"]["payment_ids"]),
                       j["when"]["tax_year"], None, states_of(j), False)
            )
        return sorted(out, key=lambda s: s.id)

    def _possible_targets(self, s: Source) -> set[str]:
        tg = set(s.targets)
        if s.judged:
            for j in heads_for(self.ctx, J_REIMB, "reimbursement_id", s.id):
                tg |= set(j["value"].get("target_payment_ids", ()))
        return tg

    def relevant(self, s: Source) -> bool:
        tg = self._possible_targets(s)
        if tg:
            return any(t in self.all_payments and self.all_payments[t].paid_on.year == self.year for t in tg)
        return s.received_year == self.year

    def _payers_in_year(self, targets: set[str] | None) -> set[str]:
        ps = self.payments if targets is None else [self.all_payments[t] for t in targets if t in self.all_payments]
        return {p.payer for p in ps if p.paid_on.year == self.year and p.payer in self.persons}

    # --- 判断・選択の1か所 ---

    def seikei_slots(self) -> list[DecisionSlot]:
        out = []
        for p in self.payments:
            plan = self.plans[p.id]
            for on in plan.seikei_dates:
                out.append(seikei_slot(p.payer, p.patient, on, "医療費（所得税基本通達73−1）", (p.payer,) if plan.outside else None))
        for n in self.notices:
            plan = self.notice_plans[n.id]
            for on in plan.seikei_dates:
                out.append(
                    seikei_slot(n.payer, n.patient, on, "医療費通知（所得税基本通達73−1。通知の対象の期間の終わりの日）", (n.payer,) if plan.outside else None)
                )
        return out

    def range_slots(self) -> list[DecisionSlot]:
        return [
            DecisionSlot(
                key=p.id,
                target={"payment_id": p.id, "person": p.payer},
                matches=lambda r, pid=p.id: r["subject"]["payment_id"] == pid,
            )
            for p in self.payments
            if self.plans[p.id].excluded is None and self.needs_range(p)
        ]

    def reimbursement_slots(self) -> list[DecisionSlot]:
        return [
            DecisionSlot(
                key=s.id,
                target={"reimbursement_id": s.id, "benefit_type": s.benefit_type},
                matches=lambda r, rid=s.id: r["subject"]["reimbursement_id"] == rid,
                candidates=REIMB_CANDIDATES,
            )
            for s in self.sources
            if s.judged and not s.estimate and self.relevant(s)
        ]

    def _selfmed_candidates(self, person: str) -> list[Payment]:
        out = []
        for p in self._payments_by_payer.get(person, []):
            if self.plans[p.id].excluded:
                continue
            label = p.rec["attributes"].get("selfmed_label")
            if label in ("present", "unknown") or heads_for(self.ctx, J_SELFMED, "payment_id", p.id):
                out.append(p)
        return out

    def label_slots(self) -> list[DecisionSlot]:
        out = []
        for person in sorted(self.torikumi):
            for p in self._selfmed_candidates(person):
                if p.rec["attributes"].get("selfmed_label") == "unknown" or heads_for(self.ctx, J_SELFMED, "payment_id", p.id):
                    out.append(
                        DecisionSlot(
                            key=p.id,
                            target={"payment_id": p.id, "person": p.payer},
                            matches=lambda r, pid=p.id: r["subject"]["payment_id"] == pid,
                            candidates=SELFMED_LABEL_CANDIDATES,
                        )
                    )
        return out

    def _choice_records(self, person: str) -> list[Mapping[str, Any]]:
        return self._choices_by_person.get(person, [])

    def choice_persons(self) -> list[str]:
        return [
            pid
            for pid in self.ctx.persons
            if (pid in self.torikumi and self._selfmed_candidates(pid)) or self._choice_records(pid)
        ]

    def choice_slots(self) -> list[DecisionSlot]:
        return [
            DecisionSlot(key=pid, target={"person": pid}, matches=lambda r, pid=pid: r["subject"]["person"] == pid)
            for pid in self.choice_persons()
        ]

    # --- 値 ---

    def inputs(self, acc: Acc) -> None:
        included: dict[str, bool] = {}
        for p in self.payments:
            ok = self.eligible(p, acc, V_MEDICAL)
            if ok and self.needs_range(p):
                dec = self.ctx.decision(J_RANGE, p.id)
                acc.note_decided(V_MEDICAL, p.payer, dec)
                ok = bool(dec.value)
            included[p.id] = ok
            if ok:
                acc.add(V_MEDICAL, p.payer, p.amount, [p.id], states_of(p.rec))
        self._notices(acc)
        compensated = self._reimbursements(acc, included)
        self._selfmed(acc, compensated)

    def _notices(self, acc: Acc) -> None:
        """医療費通知：受診者の要件を満たす記録の ㋐−min(㋑, ㋐) を支払者の補塡後の医療費に足し、明細書の ❶ の3欄の値を数える。"""
        for n in self.notices:
            if not self._eligible(self.notice_plans[n.id], n.payer, n.patient, n.id, n.rec, acc, (V_MEDICAL, *NOTICE_VARS)):
                continue
            states = states_of(n.rec)
            cut = min(n.reimbursed, n.paid)  # 補塡はその通知の医療費を限度とし、ほかの医療費から差し引かない（手引き ❶(3)）
            acc.add(V_MEDICAL, n.payer, n.paid - cut, [n.id], states)
            acc.add(V_NOTICE_AMOUNT, n.payer, n.notice_amount, [n.id], states)
            acc.add(V_NOTICE_PAID, n.payer, n.paid, [n.id], states)
            acc.add(V_NOTICE_REIMB, n.payer, cut, [n.id], states)

    def _reimbursements(self, acc: Acc, included: Mapping[str, bool]) -> set[str]:
        """補塡を差し引く。補塡の対象になった（この年分の）医療費の ID を返す。"""
        groups: dict[frozenset[str], list[tuple[Source, int, list[str], frozenset[State]]]] = {}
        for s in self.sources:
            if not self.relevant(s):
                continue
            ids = [s.id]
            states = set(s.states)
            targets = set(s.targets)
            if s.estimate:
                comp = COMPENSATING_BENEFITS.get(s.benefit_type)
                if comp is None:
                    self._exclude_payers(acc, targets, R_ESTIMATE_AMBIGUOUS, ids)
                    continue
                if s.tax_year != self.year:
                    self._exclude_payers(acc, targets, R_ESTIMATE_YEAR, ids)
                    continue
            elif s.judged:
                dec = self.ctx.decision(J_REIMB, s.id)
                ids += list(dec.record_ids)
                states |= dec.states
                comp = bool(dec.value["compensates_medical_expenses"])
                if dec.value.get("target_payment_ids"):
                    targets = set(dec.value["target_payment_ids"])
            else:
                comp = COMPENSATING_BENEFITS[s.benefit_type]
            if not comp:
                continue
            if targets & self.notice_linked:
                # 通知に載った支払（notice_id）を対象にする補塡：通知の reimbursed（㋑）と二重に差し引きうる（c-入力）
                self._exclude_payers(acc, targets, R_NOTICE_REIMB, ids)
                continue
            if not targets:
                for pid in self._payers_in_year(None):
                    acc.exclude(V_MEDICAL, pid, not_implemented(R_REIMB_NO_TARGET, ids))
                continue
            groups.setdefault(frozenset(targets), []).append((s, s.amount, ids, frozenset(states)))
        keys = sorted(groups, key=lambda k: sorted(k))
        # 一部だけ重なる対象の集合をつなぐ（つながりごとに読み (a)・(b) で計算する）
        comp: dict[frozenset[str], int] = {g: i for i, g in enumerate(keys)}
        for i, g1 in enumerate(keys):
            for g2 in keys[i + 1:]:
                if g1 & g2:
                    a, b = comp[g1], comp[g2]
                    for g in keys:
                        if comp[g] == b:
                            comp[g] = a
        components: dict[int, list[frozenset[str]]] = {}
        for g in keys:
            components.setdefault(comp[g], []).append(g)
        compensated: set[str] = set()
        reductions: dict[str, Fraction] = {}
        reduction_ids: dict[str, set[str]] = {}
        #: 支払 → (補塡で差し引く額, 対象の合計)（セルフメディケーション税制の割り振りに使う）
        self.reimbursed: dict[str, tuple[Fraction, int]] = {}
        self.overlap_splits: dict[str, Split] = {}
        for _, gs in sorted(components.items()):
            members = [m for g in gs for m in groups[g]]
            ids = sorted({i for _, _, ii, _ in members for i in ii})
            actual = {s.benefit_type for s, _, _, _ in members if not s.estimate}
            if any(s.estimate and s.benefit_type in actual for s, _, _, _ in members):
                self._exclude_payers(acc, set().union(*gs), R_ESTIMATE_DUP, ids)
                continue
            union = frozenset().union(*gs)
            merged = self._allocate(sum(a for _, a, _, _ in members), union)  # 読み (a)：まとめて合計を限度
            if len(gs) > 1:
                separate: dict[str, Fraction] = {}
                for g in gs:  # 読み (b)：補塡ごとにその対象の合計を限度にし、医療費ごとにその額を限度にする
                    for pid_, v in self._allocate(sum(a for _, a, _, _ in groups[g]), g).items():
                        separate[pid_] = separate.get(pid_, Fraction(0)) + v
                separate = {k: min(v, Fraction(self.all_payments[k].amount)) for k, v in separate.items()}
                if self._by_payer(merged, included) != self._by_payer(separate, included):
                    sp = reading_split(
                        T_OVERLAP, ":".join(sorted(union)), {"記録": ids, "医療費": sorted(union)},
                        ("重なる集合をまとめて合計を限度にする", "補塡ごとに対象の合計を限度にする"),
                    )
                    for pid in self._payers_in_year(set(union)):
                        acc.undetermined(V_MEDICAL, pid, sp)
                    for t in union:
                        self.overlap_splits[t] = sp
            base = sum(self.all_payments[t].amount for t in union if t in self.all_payments)
            states = frozenset(x for _, _, _, st in members for x in st)
            for t, frac in sorted(merged.items()):
                p = self.all_payments[t]
                if p.paid_on.year != self.year or p.payer not in self.persons:
                    continue
                compensated.add(p.id)
                self.reimbursed[p.id] = (Fraction(min(sum(a for _, a, _, _ in members), base)), base)
                if not included.get(p.id):
                    continue
                # 支払った額に応じたあん分（質疑応答事例 05/61）。対象が1人・1年分なら差し引く額そのもの
                reductions[p.payer] = reductions.get(p.payer, Fraction(0)) + frac
                reduction_ids.setdefault(p.payer, set()).update(ids)
                acc.note(V_MEDICAL, p.payer, ids, states)
        for payer, frac in sorted(reductions.items()):
            # あん分の1円未満の端数は根拠がない（D22 S3）：候補（切捨て・切上げ・四捨五入）の全部で評価する（金額だけが違えば幅）
            amount = int(frac) if frac.denominator == 1 else self.ctx.round_unfounded(REIMBURSEMENT_ROUNDING, frac)
            acc.add(V_MEDICAL, payer, -amount, sorted(reduction_ids[payer]))
        return compensated

    def _allocate(self, total: int, targets: frozenset[str]) -> dict[str, Fraction]:
        """補塡の合計 total を、対象の医療費の合計を限度に、支払った額に応じてあん分する（質疑応答事例 05/28・05/61）。支払 → 差し引く額。"""
        pays = [self.all_payments[t] for t in sorted(targets) if t in self.all_payments]
        base = sum(p.amount for p in pays)
        if base <= 0:
            return {}
        deducted = min(total, base)
        return {p.id: Fraction(deducted * p.amount, base) for p in pays}

    def _by_payer(self, alloc: Mapping[str, Fraction], included: Mapping[str, bool]) -> dict[str, Fraction]:
        out: dict[str, Fraction] = {}
        for t, v in alloc.items():
            p = self.all_payments[t]
            if p.paid_on.year == self.year and p.payer in self.persons and included.get(t):
                out[p.payer] = out.get(p.payer, Fraction(0)) + v
        return out

    def _exclude_payers(self, acc: Acc, targets: set[str], reason: str, ids: list[str]) -> None:
        for pid in self._payers_in_year(targets):
            acc.exclude(V_MEDICAL, pid, not_implemented(reason, ids))

    # --- セルフメディケーション税制 ---

    def _selfmed(self, acc: Acc, compensated: set[str]) -> None:
        choosers = set(self.choice_persons())
        for pid in self.ctx.persons:
            chosen = False
            if pid in choosers:
                dec = self.ctx.decision(C_SELFMED, pid)
                acc.note_decided(V_CHOICE, pid, dec)
                acc.note_decided(V_MEDICAL, pid, dec)
                acc.note_decided(V_SELFMED, pid, dec)
                chosen = dec.value == "self_medication"
            acc.set_value(V_CHOICE, pid, chosen)
            records = self.torikumi.get(pid, [])
            if not records:
                if chosen:
                    acc.exclude(V_CHOICE, pid, not_implemented(R_CHOSE_WITHOUT_TORIKUMI))
                    acc.exclude(V_SELFMED, pid, not_implemented(R_CHOSE_WITHOUT_TORIKUMI))
                continue
            acc.note(V_SELFMED, pid, [r["id"] for r in records], {s for r in records for s in states_of(r)})
            candidates = self._selfmed_candidates(pid)
            if candidates and not any(r["attributes"]["activity"] in TORIKUMI for r in records):
                acc.exclude(V_SELFMED, pid, not_implemented(R_TORIKUMI_OTHER, [r["id"] for r in records]))
                continue
            for p in candidates:
                label = p.rec["attributes"].get("selfmed_label")
                eligible_item = label == "present"
                if label == "unknown" or heads_for(self.ctx, J_SELFMED, "payment_id", p.id):
                    dec = self.ctx.decision(J_SELFMED, p.id)
                    acc.note_decided(V_SELFMED, pid, dec)
                    eligible_item = bool(dec.value["eligible_item"])
                    if dec.value.get("tax_year") not in (None, self.year):
                        acc.exclude(V_SELFMED, pid, not_implemented(R_SELFMED_YEAR, [p.id, *dec.record_ids]))
                        continue
                if not eligible_item:
                    continue
                if not self.eligible(p, acc, V_SELFMED):
                    continue
                if p.id in compensated:
                    self._selfmed_reimbursed(acc, pid, p)
                    continue
                acc.add(V_SELFMED, pid, p.amount, [p.id], states_of(p.rec))

    def _selfmed_reimbursed(self, acc: Acc, pid: str, p: Payment) -> None:
        """補塡のある対象の購入：補塡される部分を除く（措法41の17）。ほかの医療費との割り振りの一次情報がないので、
        あん分・対象の購入から先に・ほかの医療費から先に の3つで計算し、分かれれば未確定（値はあん分）。"""
        deducted, base = self.reimbursed[p.id]
        prop = deducted * p.amount / base
        first = min(Fraction(p.amount), deducted)
        last = max(Fraction(0), min(Fraction(p.amount), deducted - (base - p.amount)))
        cut = int(prop) if prop.denominator == 1 else self.ctx.round_unfounded(REIMBURSEMENT_ROUNDING, prop)
        acc.add(V_SELFMED, pid, p.amount - cut, [p.id], states_of(p.rec))
        if len({prop, first, last}) > 1:
            acc.undetermined(
                V_SELFMED, pid,
                reading_split(T_SELFMED_REIMB, p.id, {"person": pid, "記録": [p.id]}, ("あん分", "対象の購入から先に", "ほかの医療費から先に")),
            )  # fmt: skip
        if p.id in self.overlap_splits:
            acc.undetermined(V_SELFMED, pid, self.overlap_splits[p.id])


__all__ = [
    "KINDS_BY_ORDER",
    "MedicalYear",
    "NOTICE_VARS",
    "V_CHOICE",
    "V_MEDICAL",
    "V_NOTICE_AMOUNT",
    "V_NOTICE_PAID",
    "V_NOTICE_REIMB",
    "V_SELFMED",
]
