"""規則モジュール other_deductions：社会保険料・小規模企業共済等掛金・生命保険料・地震保険料の前処理（中間表現 → 支払者の入力変数）。

- 社会保険料（所得税法第74条）：social_insurance_payment（支払者・負担すべき人）と、給与から控除された額（salary_payment の
  social_insurance_withheld。控除される年分は給与の支払の日 when.on の年で、未払〔unpaid〕の給与からは数えない：法令の読み）。負担すべき人が支払者でなければ、親族で生計を一にすること。生計の判定の時点は一次情報にないので、
  支払日と12月31日の両方を見て、同じなら決め、違えば両方の読みで結論が分かれるので未確定（決める手段は一次情報：D22 S1）。前納は、前納の期間が支払った年分に
  収まれば全額をその年分に入れ、収まらなければ 選択.前納した社会保険料の控除の年分（未入力なら両方）で、按分（通達74・75−1(2)：総額×その年中に到来する
  納付期日〔prepaid_due_dates〕の回数÷総回数）か全額を支払った年分（74・75−2：前納期間が1年以内。1年を超えるものは「法令で前納できるとされているもの」かの
  一次情報がないので、按分と違えば未確定）。公的年金から差し引かれた（特別徴収された）額（pension_payment の social_insurance_withheld）は
  年金の受給者の支払として数える（タックスアンサー No.1130「給与や公的年金から差し引かれた金額の全額」、手引き p.15 の注意書き）。
  給与の源泉徴収票（withholding_slip）に「社会保険料等の金額」があれば、その票が覆う支払者の明細の額の代わりに票の額を使う（D23 K4）。
  記録の種類は登録しない（kyuyo・income_kinds が登録する。所得の安全側の検出を残す）。
- 小規模企業共済等掛金（所得税法第75条）：加入者本人が支払った掛金の全額。加入者以外の支払は後の段（D21 R3。対象外）。
- 生命保険料（所得税法第76条）：insurance_payment（flow：premium は加え、dividend・rebate は差し引く）と insurance_contract。
  新旧は締結日（平成24年以後に旧契約に附帯して新契約〔attached_to_contract_id〕を締結したら、その旧契約は附帯した日以後の支払から新契約：所法76⑩・
  通達76−1 の支払った時の現況。法令の読み）、区分は契約の種類（判断.生命保険の区分で上書き。個人年金は第8項の要件を記録で確かめられないので判断が要る）、
  受取人のすべてが支払者又はその配偶者その他の親族（第5項〜第7項。支払日の現況：通達76−1）。新旧の選択は 選択.保険料控除の区分。
- 地震保険料（所得税法第77条）：保険の目的が、支払者又は生計を一にする親族の有する常時居住の用に供する家屋か生活用動産。
  前納した保険料は払込期日（prepaid_due_dates）の回数で按分する（通達76−3(3)・77−7）。家屋の一部を居住の用に供するときは居住割合
  （residential_ratio）で按分し、おおむね90%以上なら全額（通達77−5・77−6）。
  旧長期損害保険料（平成18年法律第10号附則第10条第2項）：締結日（平成18年12月31日まで）・保険期間の始期（平成19年1月1日より前）・
  保険期間10年以上・満期返戻金（maturity_refund）・平成19年1月1日以後の契約の変更（contract_changes_on）を記録で確かめる（満期返戻金か変更の記録が
  なければ両方で評価：c-入力）。一の契約が両方に当たるときの選択（附則第10条第3項）は 選択.保険料控除の区分 の earthquake_or_old_long_term。
- 一次情報・語彙で決まらないもの（候補の全部で評価し、値が分かれれば入力を未確定にする：facts.reading_split）：
  公的年金以外の年金から差し引かれた社会保険料・受給者の死亡の日以後の支払から差し引かれた社会保険料・この年分に生存していない人の保険料
  （数える・数えない。一次情報）、保険期間5年未満の契約で支払の定め（benefit_payment_terms）がない（所令209①：事実。c-入力）、附帯契約で
  附帯した契約（attached_to_contract_id）がない（所法76⑩：事実。c-入力）、個人年金の受取人が第8項第1号を満たさない年金の契約（第5項の一般の生命保険料に当たるか：一次情報）。
- 剰余金・割戻金（所基通76−6・（注））：保険料の払込みに充てたもの（applied_to_premium）を含めて同じ区分の保険料から差し引く。
  区分の合計が負になれば0（第76条第1項各号の「控除した残額」：法令の読み）。判断.生命保険の区分 の dividend_allocation は使わない
  （剰余金はその契約の区分から差し引く：所令第208条の5・所基通76−6。法令の読み）。

docs：docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §7、docs/public-sources/20261109_round2_hoken-kifu-laws.md §2・§3・§5、
docs/public-sources/20261109_round2_hoken-kifu-nta-soumu.md §1・§2・§4。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ...candidates import Candidate
from ...registry import DecisionSlot, YearContext
from ...result import Means, Split
from .facts import (
    reading_split,
    C_INSURANCE,
    C_PREPAID,
    J_LIFE,
    J_SEIKEI,
    Acc,
    d,
    heads_for,
    not_implemented,
    on_year,
    relative_on,
    seikei_key,
    seikei_slot,
    states_of,
    year_end,
)
from .kinship import RelationIndex, relation_index

V_SOCIAL = "所得税_支払った社会保険料の額"
V_MUTUAL = "所得税_支払った小規模企業共済等掛金の額"
V_NEW_LIFE = "所得税_新生命保険料の額"
V_OLD_LIFE = "所得税_旧生命保険料の額"
V_CARE = "所得税_介護医療保険料の額"
V_NEW_ANNUITY = "所得税_新個人年金保険料の額"
V_OLD_ANNUITY = "所得税_旧個人年金保険料の額"
V_REGIME = "所得税_生命保険料の新旧の選択"
V_QUAKE = "所得税_地震保険料の額"
V_OLD_LONG = "所得税_旧長期損害保険料の額"
LIFE_VARS = (V_NEW_LIFE, V_OLD_LIFE, V_CARE, V_NEW_ANNUITY, V_OLD_ANNUITY)

#: 所得税法第76条第5項〜第9項の新旧の境（平成24年1月1日以後に締結した契約が新契約）。
NEW_CONTRACT_FROM = _dt.date(2012, 1, 1)
#: 社会保険料の種類のうち、所得税法第74条第2項各号に当たるもの（other は決められない）。
SOCIAL_PREMIUMS = frozenset(
    {
        "national_health_insurance", "national_pension", "health_insurance", "employees_pension",
        "long_term_care_insurance", "late_stage_elderly_medical", "employment_insurance", "national_pension_fund",
    }
)  # fmt: skip
REGIME_CANDIDATES = tuple(Candidate(x, x) for x in ("new_only", "old_only", "both"))

R_PREMIUM_OTHER = "社会保険料の種類（premium_type）が other で、所得税法第74条第2項の社会保険料に当たるか決められない。種類を入力すれば決まる"
R_PAYROLL = "給与から差し引かれた社会保険料の支払の記録（payroll_deduction）がある。給与の支払の記録の社会保険料の欄と重なりうるので数えない"
R_PREPAID = (
    "前納した社会保険料の前納の期間が支払った年分に収まらず、按分（所得税基本通達74・75−1(2)：前納の総額×その年中に到来する納付期日の回数÷"
    "納付期日の総回数）の材料の納付期日（attributes.prepaid_due_dates）がない。入力すれば決まる"
)
#: 根拠のない端数（RoundingSlotSpec(variable=None) の名前）：前納の按分・居住割合の按分の1円未満。
PREMIUM_ROUNDING = "保険料の前納・居住割合のあん分の端数"
#: 所基通77−6：家屋全体のおおむね90%以上を居住の用に供しているときは全額を居住用として差し支えない。
RESIDENTIAL_FULL_FROM = Fraction(9, 10)
#: 読みの分かれ目の論点（facts.reading_split の topic）。
T_PENSION = "公的年金以外の年金から差し引かれた社会保険料"
T_AFTER_DEATH = "受給者の死亡の日以後の支払から差し引かれた社会保険料"
T_GONE = "この年分に生存していない人の保険料"
T_SHORT_TERM = "保険期間5年未満の契約が所令第209条第1項の特定保険契約か"
T_RIDER = "附帯契約が附帯した旧契約"
T_ANNUITY_GENERAL = "第8項第1号を満たさない年金の契約が一般の生命保険料に当たるか"
T_OLD_LONG = "旧長期損害保険料の要件（満期返戻金の特約・平成19年以後の契約の変更なし）"
T_PREPAID_LONG = "前納の期間が1年を超える社会保険料が法令で前納できるとされているもの（所基通74・75−2）か"
#: 平成18年法律第10号附則第10条第2項の日付の要件（締結は平成18年12月31日まで、保険期間の始期は平成19年1月1日より前、保険期間10年以上）。
OLD_LONG_CONCLUDED_BY = _dt.date(2006, 12, 31)
OLD_LONG_START_BEFORE = _dt.date(2007, 1, 1)
OLD_LONG_YEARS = 10
R_SLIP_NO_PAYER = "支払者の名がない給与の源泉徴収票に社会保険料の欄があり、給与の明細の社会保険料と重なるかを決められない"
R_SLIP_DUPLICATE = "同じ支払者の給与の源泉徴収票が2枚ある。社会保険料等の金額を二重に数えうる"
#: 社会保険料を特別徴収する公的年金（老齢等年金給付）の制度。企業年金・外国の年金・私的年金から差し引かれた額は決めない。
SPECIAL_COLLECTION_SCHEMES = frozenset({"national_pension", "employees_pension", "mutual_aid_pension"})


@dataclass(frozen=True)
class SlipPlan:
    """1人の給与の源泉徴収票の社会保険料の使い方：数える票・票で覆う支払者・重複・支払者の名がない票の有無・票の ID。"""

    used: tuple[Mapping[str, Any], ...]
    covered: frozenset[str]
    duplicates: tuple[str, ...]
    no_payer: bool
    ids: tuple[str, ...]
R_GONE = "負担すべき人・保険の目的の所有者がこの年分に生存していない"
R_KIN = "負担すべき人・保険の目的の所有者・受取人が支払者の配偶者その他の親族であることを、中間表現の関係から導けない。関係（親子・養子縁組・婚姻）の記録を入力すれば決まる"
R_TIMING = "生計を一にするかが支払日と12月31日とで違う。社会保険料控除・地震保険料控除の生計の判定の時点を決める一次情報が docs にない"


def timing_split(plan: "Livelihood", ids: list[str]) -> Split:
    """社会保険料控除・地震保険料控除の生計を一にするかの判定の時点の読みの分かれ目（D22 S1：両方の読みで結論が違う）。"""
    return Split(
        id=f"読み:生計の判定の時点:{plan.a}:{plan.b}:{plan.dates[0].isoformat()}",
        means=Means.PRIMARY_SOURCE,
        target={
            "person": plan.a, "other_person": plan.b, "規則": plan.purpose, "日": [x.isoformat() for x in plan.dates],
            "記録": sorted(set(ids)), "理由": R_TIMING,
        },
        candidates=("支払日の現況", "12月31日の現況"),
        splits_conclusion=True,
    )  # fmt: skip
R_MUTUAL_OTHER = "加入者以外が支払った小規模企業共済等掛金がある。後の段（HANDOFF D21 R3）"
R_LIFE_PREPAID = (
    "前納した保険料の払込期日（attributes.prepaid_due_dates）がない。その年に支払った金額（所得税基本通達76−3(3)・77−7：前納した総額×"
    "その年中に到来する払込期日の回数÷払込期日の総回数）を決められない。入力すれば決まる"
)
R_DIVIDEND_APPLIED = (
    "保険料の支払（flow: premium）に applied_to_premium がある。剰余金・割戻金を保険料の払込みに充てたことは、剰余金・割戻金の記録"
    "（flow: dividend・rebate）の applied_to_premium に書く（所基通76−6（注）でその区分の保険料から差し引く）"
)
R_PRODUCT_OTHER = "保険の種類（insurance_contract.attributes.product_type）が other で、生命保険料控除・地震保険料控除のどの区分に当たるか決められない。種類を入力すれば決まる"
R_BENEFICIARY = "保険金等の受取人（beneficiary_ids）がない、又は支払者・その配偶者その他の親族と導けない受取人がいる（所得税法第76条第5項〜第7項）"
R_ANNUITY = "個人年金保険の契約の要件（所得税法第76条第8項各号：受取人・払込期間・支払の期間）を記録で確かめられない（判断.生命保険の区分が要る）"
R_CONTRACT_CHOICE = (
    "選択.保険料控除の区分 の life_insurance_regime に contract_id がある。新旧の選択は区分（一般・個人年金）ごとの選択（質疑応答事例 05/76）で、"
    "契約ごとには選べない。contract_id を書かない人ごとの選択を入力すれば決まる"
)
R_QUAKE_CHOICE = (
    "選択.保険料控除の区分 の earthquake_or_old_long_term に contract_id がない。一の契約が地震保険料と旧長期損害保険料の両方に当たるときの選択"
    "（平成18年法律第10号附則第10条第3項）は契約ごとなので、contract_id を入力すれば決まる"
)
R_QUAKE_OBJECT = "地震保険の目的（insured_object：dwelling・household_goods）又はその所有者（insured_object_owner）が記録にない。入力すれば決まる"
R_QUAKE_RESIDENTIAL = (
    "家屋（insured_object: dwelling）が常時その居住の用に供するものか（residential_use）も居住の用に供する部分の割合（residential_ratio）も"
    "記録にない。入力すれば決まる"
)


def prepaid_dates(attrs: Mapping[str, Any]) -> list[_dt.date] | None:
    """前納の納付期日・払込期日の全部（記録になければ None）。"""
    xs = attrs.get("prepaid_due_dates")
    return None if xs is None else sorted(d(x) for x in xs)


def prepaid_share(amount: int, dates: list[_dt.date], year: int) -> Fraction:
    """前納の総額×その年中に到来する期日の回数÷期日の総回数（所基通74・75−1(2)・76−3(3)・77−7）。"""
    return Fraction(amount * sum(1 for x in dates if x.year == year), len(dates))


def _add_years(day: _dt.date, years: int) -> _dt.date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 2月29日
        return day.replace(year=day.year + years, day=28)


@dataclass(frozen=True)
class Livelihood:
    """支払者 a と相手 b の、日付ごとの生計の判断の段取り（日付は全部が同じ結論のときだけ決める）。"""

    a: str
    b: str
    dates: tuple[_dt.date, ...]
    purpose: str


class InsuranceYear:
    """社会保険料・小規模企業共済等掛金・生命保険料・地震保険料の年分の段取り。"""

    def __init__(self, ctx: YearContext, idx: RelationIndex | None = None) -> None:
        self.ctx = ctx
        self.year = ctx.year
        self.persons = set(ctx.persons)
        self.idx = idx if idx is not None else relation_index(ctx.ir)
        self.contracts = {r["id"]: r for r in ctx.records("insurance_contract")}
        self.ye = year_end(ctx)
        # 人の数 × 記録の数の計算にしないよう、年分の支払と選択を最初に1回だけ読む
        self._year_payments = [
            (r, self.contracts[r["attributes"]["contract_id"]])
            for r in sorted(ctx.records("insurance_payment"), key=lambda r: r["id"])
            if self._touches(r) and r["roles"]["payer"] in self.persons
        ]
        self._payments_by_payer: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
        for r, c in self._year_payments:
            self._payments_by_payer.setdefault(r["roles"]["payer"], []).append((r, c))
        #: 平成24年以後に旧契約に附帯して新契約を締結した旧契約 → 附帯した日（所法76⑩：その旧契約は新契約とみなす）。
        self._deemed_new: dict[str, _dt.date] = {}
        for c in self.contracts.values():
            a = c["attributes"]
            base = self.contracts.get(a.get("attached_to_contract_id") or "")
            if a.get("rider") and base is not None and d(a["concluded_on"]) >= NEW_CONTRACT_FROM > d(base["attributes"]["concluded_on"]):
                on = d(a["concluded_on"])
                self._deemed_new[base["id"]] = min(on, self._deemed_new.get(base["id"], on))
        self._choices_by_person: dict[str, list[Mapping[str, Any]]] = {}
        for x in ctx.choices(C_INSURANCE):
            if x["when"]["tax_year"] == self.year:
                self._choices_by_person.setdefault(x["subject"]["person"], []).append(x)

    def _touches(self, r: Mapping[str, Any]) -> bool:
        """支払がこの年分に関係するか：支払った年分か、前納の期日がこの年分に到来する（所基通74・75−1(2)・76−3(3)）。"""
        return on_year(r) == self.year or any(x.year == self.year for x in prepaid_dates(r["attributes"]) or ())

    def _round(self, x: Fraction) -> int:
        return int(x) if x.denominator == 1 else self.ctx.round_unfounded(PREMIUM_ROUNDING, x)

    def _is_new(self, c: Mapping[str, Any], paid_on: _dt.date) -> bool:
        """新契約か：平成24年1月1日以後の締結、又は所法76⑩で新契約とみなされる旧契約（附帯した日以後の支払。所基通76−1 の支払った時の現況：法令の読み）。"""
        if d(c["attributes"]["concluded_on"]) >= NEW_CONTRACT_FROM:
            return True
        deemed = self._deemed_new.get(c["id"])
        return deemed is not None and paid_on >= deemed

    # --- 前納 ---

    def _prepaid_needs_choice(self, r: Mapping[str, Any]) -> bool:
        """前納の期間（又は期日）が支払った年分に収まらない社会保険料：按分（74・75−1(2)）か全額か（74・75−2）の選択が要る。"""
        a = r["attributes"]
        pp, dates, paid_year = a.get("prepaid_period"), prepaid_dates(a), on_year(r)
        if dates is not None:
            return any(x.year != paid_year for x in dates)
        if pp is None:
            return False
        return not (d(pp["from_on"]).year == paid_year and pp.get("to_on") and d(pp["to_on"]).year == paid_year)

    def prepaid_slots(self) -> list[DecisionSlot]:
        return [
            DecisionSlot(
                key=r["id"],
                target={"payment_id": r["id"], "person": r["roles"]["payer"]},
                matches=lambda x, rid=r["id"]: x["subject"]["payment_id"] == rid,
                persons=(r["roles"]["payer"],),
            )
            for r, _ in self._social_items()
            if self._prepaid_needs_choice(r)
        ]

    def _social_amount(self, acc: Acc, r: Mapping[str, Any]) -> tuple[int | None, list[Split]]:
        """社会保険料の支払のこの年分の額と、読みの分かれ目。None は按分の材料（納付期日）がない（c-入力）。"""
        a = r["attributes"]
        amount, paid_year = r["amounts"]["amount"], on_year(r)
        whole = amount if paid_year == self.year else 0
        if not self._prepaid_needs_choice(r):
            return whole, []
        dates = prepaid_dates(a)
        pro = None if dates is None else self._round(prepaid_share(amount, dates, self.year))
        dec = self.ctx.decision(C_PREPAID, r["id"])
        acc.note_decided(V_SOCIAL, r["roles"]["payer"], dec)
        if dec.value != "all_in_paid_year":
            return pro, []
        pp = a.get("prepaid_period")
        if pp is not None and pp.get("to_on") and d(pp["to_on"]) < _add_years(d(pp["from_on"]), 1):
            return whole, []  # 前納期間が1年以内：全額をその支払った年分にできる（74・75−2）
        # 1年を超える前納：法令で前納できるとされているものかを決める一次情報が docs にない。全額の値で入れ、按分と違えば未確定（D22 S1）
        if pro == whole:
            return whole, []
        return whole, [reading_split(T_PREPAID_LONG, r["id"], {"person": r["roles"]["payer"], "記録": [r["id"]]}, ("全額をその年分にできる", "按分する"))]

    def _premium_amount(self, r: Mapping[str, Any]) -> int | None:
        """生命保険料・地震保険料の支払のこの年分の額（前納は所基通76−3(3)・77−7 の按分）。None は払込期日がない前納（c-入力）。"""
        a = r["attributes"]
        dates = prepaid_dates(a)
        if dates is None:
            if a.get("prepaid"):
                return None
            return r["amounts"]["amount"] if on_year(r) == self.year else 0
        return self._round(prepaid_share(r["amounts"]["amount"], dates, self.year))

    # --- 生計を一にする（支払日と12月31日） ---

    def _livelihood(self, a: str, b: str, paid_on: _dt.date, purpose: str) -> Livelihood | str:
        """相手が親族か（両方の日）を確かめ、生計の判断の段取りを返す。だめなら対象外の理由。"""
        if b not in self.persons:
            return R_GONE
        dates = (paid_on, self.ye) if paid_on != self.ye else (paid_on,)
        rel = relative_on(self.idx, a, b, dates)
        if rel.dates_where(False) or rel.dates_where(None):
            return f"{R_KIN}（{rel.notes}）" if rel.notes else R_KIN
        return Livelihood(a, b, dates, purpose)

    def _social_items(self) -> list[tuple[Mapping[str, Any], Livelihood | str | None]]:
        out = []
        for r in sorted(self.ctx.records("social_insurance_payment"), key=lambda r: r["id"]):
            if not self._touches(r) or r["roles"]["payer"] not in self.persons:
                continue
            payer, liable = r["roles"]["payer"], r["roles"]["liable_person"]
            plan = None if liable == payer else self._livelihood(payer, liable, d(r["when"]["on"]), "社会保険料（所得税法第74条第1項）")
            out.append((r, plan))
        return out

    def _quake_items(self) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Livelihood | str | None]]:
        out = []
        for r, c in self._payments():
            if self._quake_or_long(c) != "earthquake":
                continue
            payer = r["roles"]["payer"]
            owner = c["attributes"].get("insured_object_owner")
            plan = None if owner in (None, payer) else self._livelihood(payer, owner, d(r["when"]["on"]), "地震保険料（所得税法第77条第1項）")
            out.append((r, c, plan))
        return out

    def seikei_slots(self) -> list[DecisionSlot]:
        out = []
        plans = [p for _, p in self._social_items()] + [p for _, _, p in self._quake_items()]
        for plan in plans:
            if isinstance(plan, Livelihood):
                out += [seikei_slot(plan.a, plan.b, on, plan.purpose) for on in plan.dates]
        return out

    def _livelihood_value(self, acc: Acc, var: str, plan: Livelihood, ids: list[str]) -> bool | None:
        vals = []
        for on in plan.dates:
            dec = self.ctx.decision(J_SEIKEI, seikei_key(plan.a, plan.b, on))
            acc.note_decided(var, plan.a, dec)
            vals.append(bool(dec.value))
        if all(vals):
            return True
        if not any(vals):
            return False
        # 判定の時点（支払日か12月31日か）の一次情報がない：両方の読みで評価し、結論が分かれるので未確定（HANDOFF D22 S1）。
        # 値は支払日の読み（数える）で入れ、依存する値を未確定にする（outcomes は空。決める手段は一次情報）
        acc.undetermined(var, plan.a, timing_split(plan, ids))
        return True

    # --- 社会保険料 ---

    def _both_ways(self, acc: Acc, var: str, pid: str, amount: int, ids: list[str], states: Any, topic: str, key: str, **target: Any) -> None:
        """一次情報で決まらない（数える・数えない）支払：数える値で入れ、値が分かれるので入力を未確定にする（D22 S1）。"""
        acc.add(var, pid, amount, ids, states)
        if amount:
            acc.undetermined(var, pid, reading_split(topic, key, {"person": pid, "記録": sorted(set(ids)), **target}, ("数える", "数えない")))

    def social(self, acc: Acc) -> None:
        for r, plan in self._social_items():
            payer = r["roles"]["payer"]
            a = r["attributes"]
            ids = [r["id"]]
            acc.note(V_SOCIAL, payer, ids, states_of(r))
            if a["premium_type"] not in SOCIAL_PREMIUMS:
                acc.exclude(V_SOCIAL, payer, not_implemented(R_PREMIUM_OTHER, ids))
                continue
            if a.get("payroll_deduction"):
                acc.exclude(V_SOCIAL, payer, not_implemented(R_PAYROLL, ids))
                continue
            amount, prepaid_splits = self._social_amount(acc, r)
            if amount is None:
                acc.exclude(V_SOCIAL, payer, not_implemented(R_PREPAID, ids))
                continue
            for sp in prepaid_splits:
                acc.undetermined(V_SOCIAL, payer, sp)
            if plan == R_GONE:
                # 負担すべき人がこの年分に生存していない（前年以前に死亡）：その人の保険料を支払った人が控除できるかの一次情報がない
                self._both_ways(acc, V_SOCIAL, payer, amount, ids, states_of(r), T_GONE, r["id"], 負担すべき人=r["roles"]["liable_person"])
                continue
            if isinstance(plan, str):
                acc.exclude(V_SOCIAL, payer, not_implemented(plan, ids))
                continue
            if isinstance(plan, Livelihood):
                acc.note(V_SOCIAL, payer, *self._kin_provenance(plan))
                if not self._livelihood_value(acc, V_SOCIAL, plan, ids):
                    continue
            acc.add(V_SOCIAL, payer, amount, ids, states_of(r))
        slips = self._salary_slip_plan()
        for r in sorted(self.ctx.records("salary_payment"), key=lambda r: r["id"]):
            pid = r["roles"]["recipient"]
            amt = r["amounts"].get("social_insurance_withheld", 0)
            # 給与から控除される年分は、控除が行われる給与の支払の日（when.on）の年。未払の給与からはまだ控除されていないので数えない
            # （第74条第1項「給与から控除される場合」・TA No.1130「給与…から差し引かれた金額」。支給日 due_on の年分にしないのは法令の読み）
            if on_year(r) != self.year or pid not in self.persons or not amt or r["attributes"].get("unpaid"):
                continue
            plan = slips.get(pid)
            if plan is not None and r["attributes"].get("counterparty") in plan.covered:
                continue  # 源泉徴収票の「社会保険料等の金額」を使う（D23 K4。明細の額は数えない）
            if plan is not None and plan.no_payer:
                acc.exclude(V_SOCIAL, pid, not_implemented(R_SLIP_NO_PAYER, [r["id"], *plan.ids]))
                continue
            death = self.ctx.death_on(pid)
            if death is not None and d(r["when"]["on"]) >= death:
                self._both_ways(acc, V_SOCIAL, pid, amt, [r["id"]], states_of(r), T_AFTER_DEATH, r["id"], 死亡の日=death.isoformat())
                continue
            acc.add(V_SOCIAL, pid, amt, [r["id"]], states_of(r))  # 給与から控除される場合（第74条第1項）
        for pid, plan in sorted(slips.items()):
            if plan.duplicates:
                acc.exclude(V_SOCIAL, pid, not_implemented(R_SLIP_DUPLICATE, plan.duplicates))
                continue
            for s in plan.used:
                acc.add(V_SOCIAL, pid, s["amounts"]["social_insurance"], [s["id"]], states_of(s))
        for r in sorted(self.ctx.records("pension_payment"), key=lambda r: r["id"]):
            pid = r["roles"]["recipient"]
            amt = r["amounts"].get("social_insurance_withheld", 0)
            if on_year(r) != self.year or pid not in self.persons or not amt:
                continue
            death = self.ctx.death_on(pid)
            if death is not None and d(r["when"]["on"]) >= death:
                self._both_ways(acc, V_SOCIAL, pid, amt, [r["id"]], states_of(r), T_AFTER_DEATH, r["id"], 死亡の日=death.isoformat())
                continue
            if r["attributes"]["scheme"] not in SPECIAL_COLLECTION_SCHEMES:
                # 企業年金・外国の年金などから差し引かれた額：社会保険料に当たるか・受給者の負担かの一次情報がない
                self._both_ways(acc, V_SOCIAL, pid, amt, [r["id"]], states_of(r), T_PENSION, r["id"], 年金の制度=r["attributes"]["scheme"])
                continue
            # 公的年金から差し引かれた（特別徴収された）社会保険料は、年金の受給者が支払ったもの（TA No.1130・手引き p.15）
            acc.add(V_SOCIAL, pid, amt, [r["id"]], states_of(r))

    def _salary_slip_plan(self) -> dict[str, SlipPlan]:
        """人 → 給与の源泉徴収票の「社会保険料等の金額」の使い方（D23 K4：源泉徴収票の値を優先する）。

        源泉徴収票が覆う支払者（その票の支払者と、通算した前の支払者 includes_prior_payers）の給与の明細の社会保険料は数えない。
        票に社会保険料の欄がなければ、明細の額を数える（票で上書きしない）。同じ支払者の票が2枚あれば対象外（kyuyo と同じ）。
        """
        by_person: dict[str, list[Mapping[str, Any]]] = {}
        for r in sorted(self.ctx.records("withholding_slip"), key=lambda r: r["id"]):
            pid = r["roles"]["recipient"]
            if r["attributes"]["slip_type"] == "salary" and r["when"].get("tax_year") == self.year and pid in self.persons:
                by_person.setdefault(pid, []).append(r)
        out: dict[str, SlipPlan] = {}
        for pid, slips in by_person.items():
            prior: set[str] = set()
            for s in slips:
                prior.update(s["attributes"].get("includes_prior_payers", ()))
            seen: dict[str, str] = {}
            duplicates: list[str] = []
            used: list[Mapping[str, Any]] = []
            covered: set[str] = set()
            no_payer = False
            for s in slips:
                payer = s["attributes"].get("counterparty")
                if payer is None:
                    no_payer = True
                else:
                    others = set().union(*(set(t["attributes"].get("includes_prior_payers", ())) for t in slips if t is not s))
                    if payer in others:
                        continue  # ほかの票に通算された前の支払者の票（二重に数えない）
                    if payer in seen:
                        duplicates += [seen[payer], s["id"]]
                        continue
                    seen[payer] = s["id"]
                if "social_insurance" in s["amounts"]:
                    used.append(s)
                    if payer is not None:
                        covered.add(payer)
                        covered.update(s["attributes"].get("includes_prior_payers", ()))
            out[pid] = SlipPlan(
                used=tuple(used),
                covered=frozenset(covered),
                duplicates=tuple(sorted(set(duplicates))),
                no_payer=no_payer and any("social_insurance" in s["amounts"] for s in slips),
                ids=tuple(s["id"] for s in slips),
            )
        return out

    def _kin_provenance(self, plan: Livelihood) -> tuple[list[str], set[Any]]:
        rel = relative_on(self.idx, plan.a, plan.b, plan.dates)
        return list(rel.ids), set(rel.states)

    # --- 小規模企業共済等掛金 ---

    def mutual_aid(self, acc: Acc) -> None:
        for r in sorted(self.ctx.records("mutual_aid_payment"), key=lambda r: r["id"]):
            if on_year(r) != self.year:
                continue
            payer, member = r["roles"]["payer"], r["roles"]["member"]
            ids = [r["id"]]
            if payer != member:
                for pid in (payer, member):
                    acc.exclude(V_MUTUAL, pid, not_implemented(R_MUTUAL_OTHER, ids))
                continue
            if payer in self.persons:
                acc.add(V_MUTUAL, payer, r["amounts"]["amount"], ids, states_of(r))

    # --- 生命保険料・地震保険料 ---

    def _payments(self) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
        return self._year_payments

    def _life_category(
        self, r: Mapping[str, Any], c: Mapping[str, Any], splits: list[Split] | None = None
    ) -> tuple[str | None, str | None, list[str]]:
        """生命保険の支払の区分（入力変数の名前）と、対象外の理由・使った判断の ID。区分を引く前の判断は宣言済みの1か所だけを引く。
        区分も理由も None なら、生命保険料に当たらない（所令209① の特定保険契約）。

        splits に、一次情報・語彙で決まらない分かれ目（候補の全部で評価し、値が分かれる：数える値で入れて未確定）を足す。
        """
        a = c["attributes"]
        payer = r["roles"]["payer"]
        paid_on = d(r["when"]["on"])
        used: list[str] = []
        out_splits: list[Split] = []
        start = d(c["when"]["from_on"])
        if c["when"].get("to_on") and d(c["when"]["to_on"]) < _add_years(start, 5):
            # 保険期間5年未満：所令第209条第1項（満了の日に生存している場合〔又は災害等による死亡〕に限り支払う定めのあるもの）は特定保険契約で、
            # 生命保険料に当たらない。支払の定め（benefit_payment_terms）がなければ、当たる・当たらないの両方で評価する（c-入力）
            terms = a.get("benefit_payment_terms")
            if terms in ("survival_at_maturity_only", "survival_or_special_cause_death"):
                return None, None, used
            if terms is None:
                out_splits.append(
                    reading_split(T_SHORT_TERM, c["id"], {"contract_id": c["id"], "person": payer}, ("特定保険契約に当たる（数えない）", "当たらない（数える）"),
                                  means=Means.FACT)
                )  # fmt: skip
        category = {"life": "general_life", "medical_or_care": "care_medical", "individual_annuity": None}[a["product_type"]]
        if heads_for(self.ctx, J_LIFE, "contract_id", c["id"]):
            dec = self.ctx.decision(J_LIFE, c["id"])
            used += list(dec.record_ids)
            category = dec.value["category"]  # dividend_allocation は使わない（剰余金はその契約の区分から：所令208の5・所基通76−6）
        if category is None:
            return None, R_ANNUITY, used
        bens = a.get("beneficiary_ids") or []
        if not bens:
            return None, R_BENEFICIARY, used
        for b in bens:
            if b == payer:
                continue
            rel = relative_on(self.idx, payer, b, [paid_on])
            if rel.by_date[paid_on].relative is not True:
                return None, R_BENEFICIARY, used
            used += list(rel.ids)
        if category == "individual_annuity":
            for b in bens:
                if b != payer and self.idx.spouse_record(payer, b, paid_on) is None:
                    # 第8項第1号を満たさない年金の契約：第5項の一般の生命保険料に当たるかの一次情報がない（［PS3-KM］§2）。一般の値で入れて未確定
                    category = "general_life"
                    out_splits.append(
                        reading_split(T_ANNUITY_GENERAL, c["id"], {"contract_id": c["id"], "person": payer, "受取人": b},
                                      ("一般の生命保険料に当たる", "当たらない"))
                    )  # fmt: skip
                    break
        new = self._is_new(c, paid_on)
        var = {
            ("general_life", True): V_NEW_LIFE,
            ("general_life", False): V_OLD_LIFE,
            ("care_medical", True): V_CARE,
            ("care_medical", False): V_OLD_LIFE,  # 第6項第4号：旧契約の医療保険・介護保険は旧生命保険料
            ("individual_annuity", True): V_NEW_ANNUITY,
            ("individual_annuity", False): V_OLD_ANNUITY,
        }[(category, new)]
        if splits is not None:
            splits.extend(out_splits)
        return var, None, used

    def life_slots(self) -> list[DecisionSlot]:
        out = []
        seen: set[str] = set()
        for _, c in self._payments():
            if c["id"] in seen or not heads_for(self.ctx, J_LIFE, "contract_id", c["id"]):
                continue
            seen.add(c["id"])
            out.append(
                DecisionSlot(key=c["id"], target={"contract_id": c["id"]}, matches=lambda j, cid=c["id"]: j["subject"]["contract_id"] == cid)
            )
        return out

    def _person_choices(self, pid: str) -> list[Mapping[str, Any]]:
        return self._choices_by_person.get(pid, [])

    def _premium_totals(self, pid: str) -> tuple[dict[str, int], bool]:
        """判断の1か所を引かずに分かる新旧の区分の支払の件数と、区分を決められない契約があるか（選択の1か所を宣言するかの判定だけに使う）。"""
        totals: dict[str, int] = {}
        unknown = False
        default = {"life": "general_life", "medical_or_care": "care_medical", "individual_annuity": None}
        for r, c in self._payments_by_payer.get(pid, []):
            pt = c["attributes"]["product_type"]
            if pt not in default:
                continue
            heads = heads_for(self.ctx, J_LIFE, "contract_id", c["id"])
            if len(heads) > 1:
                unknown = True
                continue
            category = heads[0]["value"]["category"] if heads else default[pt]
            if category is None:
                continue
            new = self._is_new(c, d(r["when"]["on"]))
            if category == "care_medical" and new:
                continue  # 介護医療保険料は新旧の選択の対象でない（第2項）
            kind = ("annuity" if category == "individual_annuity" else "general") + (":new" if new else ":old")
            totals[kind] = totals.get(kind, 0) + (1 if r["attributes"]["flow"] == "premium" else 0)
        return totals, unknown

    def regime_persons(self) -> list[str]:
        out = []
        for pid in self.ctx.persons:
            t, unknown = self._premium_totals(pid)
            both = (t.get("general:new") and t.get("general:old")) or (t.get("annuity:new") and t.get("annuity:old"))
            person_choice = [x for x in self._person_choices(pid) if "contract_id" not in x["subject"] and "life_insurance_regime" in x["value"]]
            if both or unknown or person_choice:
                out.append(pid)
        return out

    def regime_slots(self) -> list[DecisionSlot]:
        return [
            DecisionSlot(
                key=pid,
                target={"person": pid, "choice": "life_insurance_regime"},
                matches=lambda x, pid=pid: x["subject"]["person"] == pid
                and "contract_id" not in x["subject"]
                and "life_insurance_regime" in x["value"],
                candidates=REGIME_CANDIDATES,
            )
            for pid in self.regime_persons()
        ]

    def life_and_quake(self, acc: Acc) -> None:
        regime_persons = set(self.regime_persons())
        for pid in self.ctx.persons:
            regime = "both"
            if pid in regime_persons:
                dec = self.ctx.decision(C_INSURANCE, pid)
                regime = str(dec.value)
                for v in (*LIFE_VARS, V_REGIME):
                    acc.note_decided(v, pid, dec)
            acc.set_value(V_REGIME, pid, regime)
            for x in self._person_choices(pid):
                if "contract_id" in x["subject"] and x["value"].get("life_insurance_regime"):
                    for v in LIFE_VARS:
                        acc.exclude(v, pid, not_implemented(R_CONTRACT_CHOICE, [x["id"]]))
                if x["value"].get("earthquake_or_old_long_term") and "contract_id" not in x["subject"]:
                    for v in (V_QUAKE, V_OLD_LONG):
                        acc.exclude(v, pid, not_implemented(R_QUAKE_CHOICE, [x["id"]]))
        sums: dict[tuple[str, str], int] = {}
        quake_plans = {rr["id"]: p for rr, _, p in self._quake_items()}
        riders = self._rider_splits()
        for r, c in self._payments():
            payer = r["roles"]["payer"]
            a = r["attributes"]
            pt = self._quake_or_long(c)
            ids = [r["id"], c["id"]]
            sign = 1 if a["flow"] == "premium" else -1
            if pt == "other":
                for v in (*LIFE_VARS, V_QUAKE):
                    acc.exclude(v, payer, not_implemented(R_PRODUCT_OTHER, ids))
                continue
            life = pt in ("life", "medical_or_care", "individual_annuity")
            targets = LIFE_VARS if life else (V_QUAKE, V_OLD_LONG)
            amount = self._premium_amount(r)
            if amount is None:
                for v in targets:
                    acc.exclude(v, payer, not_implemented(R_LIFE_PREPAID, ids))
                continue
            if a.get("applied_to_premium") and a["flow"] == "premium":
                for v in targets:
                    acc.exclude(v, payer, not_implemented(R_DIVIDEND_APPLIED, ids))
                continue
            # 剰余金・割戻金は払込みに充てたもの（applied_to_premium）を含めて同じ区分から差し引く（所基通76−6（注）・77−7）
            if life:
                splits: list[Split] = []
                var, why, used = self._life_category(r, c, splits)
                if var is None and why is None:
                    for v in LIFE_VARS:
                        acc.note(v, payer, ids + used, states_of(r) | states_of(c))
                    continue  # 特定保険契約（所令209①）：生命保険料に当たらない
                if var is None:
                    for v in LIFE_VARS:
                        acc.exclude(v, payer, not_implemented(why or R_PRODUCT_OTHER, ids + used))
                    continue
                acc.add(var, payer, sign * amount, ids + used, states_of(r) | states_of(c))
                sums[(var, payer)] = sums.get((var, payer), 0) + sign * amount
                for sp in [*splits, *riders.get(payer, ())]:
                    for v in LIFE_VARS if sp.id.startswith("事実:" + T_RIDER) else (var,):
                        acc.undetermined(v, payer, sp)
                continue
            if pt == "long_term_non_life":
                self._old_long(acc, r, c, ids, sign * amount, sums)
                continue
            if self._quake_ok(acc, r, c, ids, quake_plans.get(r["id"])):
                amount = self._residential_amount(c, amount)
                acc.add(V_QUAKE, payer, sign * amount, ids, states_of(r) | states_of(c))
                sums[(V_QUAKE, payer)] = sums.get((V_QUAKE, payer), 0) + sign * amount
        for (var, payer), total in sorted(sums.items()):
            if total < 0:
                # 剰余金・割戻金がその区分の保険料を超える：第76条第1項各号・第77条第1項の「控除した残額」は0（法令の読み。区分をまたがない：76−6（注））
                acc.add(var, payer, -total)

    def _quake_or_long(self, c: Mapping[str, Any]) -> str:
        """契約の種類。一の契約が地震保険料と旧長期損害保険料の両方に当たるときは、契約ごとの選択（附則第10条第3項）で決める。"""
        pt = c["attributes"]["product_type"]
        if pt not in ("earthquake", "long_term_non_life"):
            return pt
        holder_choices = [
            x for pid in sorted(self.persons) for x in self._person_choices(pid)
            if x["subject"].get("contract_id") == c["id"] and x["value"].get("earthquake_or_old_long_term")
        ]  # fmt: skip
        if holder_choices:
            return "earthquake" if holder_choices[0]["value"]["earthquake_or_old_long_term"] == "earthquake" else "long_term_non_life"
        return pt

    def _old_long(self, acc: Acc, r: Mapping[str, Any], c: Mapping[str, Any], ids: list[str], signed: int, sums: dict[tuple[str, str], int]) -> None:
        """旧長期損害保険料（平成18年法律第10号附則第10条第2項）。日付の要件・満期返戻金（maturity_refund）・平成19年以後の契約の変更
        （contract_changes_on）を記録で確かめる。満期返戻金か変更の記録がなければ両方で評価する（c-入力）。"""
        payer = r["roles"]["payer"]
        a = c["attributes"]
        start = d(c["when"]["from_on"])
        end = d(c["when"]["to_on"]) if c["when"].get("to_on") else None
        refund, changes = a.get("maturity_refund"), a.get("contract_changes_on")
        if (
            d(a["concluded_on"]) > OLD_LONG_CONCLUDED_BY or start >= OLD_LONG_START_BEFORE or (end is not None and end < _add_years(start, OLD_LONG_YEARS))
            or refund == "none" or any(d(x) >= OLD_LONG_START_BEFORE for x in changes or ())
        ):  # fmt: skip
            acc.note(V_OLD_LONG, payer, ids, states_of(r) | states_of(c))
            return  # 要件に当たらない（TA1145：満期返戻金等のあるもの、平成19年1月1日以後に変更していない）：旧長期損害保険料でない
        acc.add(V_OLD_LONG, payer, signed, ids, states_of(r) | states_of(c))
        sums[(V_OLD_LONG, payer)] = sums.get((V_OLD_LONG, payer), 0) + signed
        if refund is not None and changes is not None:
            return
        acc.undetermined(
            V_OLD_LONG, payer,
            reading_split(T_OLD_LONG, c["id"], {"contract_id": c["id"], "person": payer}, ("要件を満たす", "満たさない"), means=Means.FACT),
        )  # fmt: skip

    def _rider_splits(self) -> dict[str, tuple[Split, ...]]:
        """平成24年1月1日以後に締結した附帯契約があり、同じ支払者に旧契約の保険料があるとき：所法76⑩でどの旧契約が新契約とみなされるかは
        語彙にない事実（附帯した旧契約）なので、支払者の生命保険料の全区分を未確定にする（決める手段は事実）。"""
        out: dict[str, list[Split]] = {}
        for payer, items in self._payments_by_payer.items():
            life = [(r, c) for r, c in items if c["attributes"]["product_type"] in ("life", "medical_or_care", "individual_annuity")]
            riders = sorted(
                {
                    c["id"] for _, c in life
                    if c["attributes"].get("rider") and not c["attributes"].get("attached_to_contract_id")
                    and d(c["attributes"]["concluded_on"]) >= NEW_CONTRACT_FROM
                }
            )  # fmt: skip
            olds = sorted({c["id"] for _, c in life if d(c["attributes"]["concluded_on"]) < NEW_CONTRACT_FROM})
            for rid in riders:
                out.setdefault(payer, []).append(
                    reading_split(T_RIDER, rid, {"contract_id": rid, "person": payer, "旧契約": olds}, tuple(["附帯していない", *olds]), means=Means.FACT)
                )
        return {k: tuple(v) for k, v in out.items() if any(sp.target["旧契約"] for sp in v)}

    def _residential_amount(self, c: Mapping[str, Any], amount: int) -> int:
        """家屋の一部を居住の用に供するときの地震保険料（所基通77−5：居住割合で按分。77−6：おおむね90%以上なら全額。法令の読み）。"""
        a = c["attributes"]
        ratio = a.get("residential_ratio")
        if a.get("insured_object") != "dwelling" or ratio is None:
            return amount
        share = Fraction(ratio["num"], ratio["den"])
        if share >= RESIDENTIAL_FULL_FROM:
            return amount
        return self._round(amount * share)

    def _quake_ok(
        self, acc: Acc, r: Mapping[str, Any], c: Mapping[str, Any], ids: list[str], plan: Livelihood | str | None
    ) -> bool:
        payer = r["roles"]["payer"]
        a = c["attributes"]
        obj, owner = a.get("insured_object"), a.get("insured_object_owner")
        if obj not in ("dwelling", "household_goods") or owner is None:
            acc.exclude(V_QUAKE, payer, not_implemented(R_QUAKE_OBJECT, ids))
            return False
        ratio = a.get("residential_ratio")
        if obj == "dwelling" and a.get("residential_use") is None and ratio is None:
            acc.exclude(V_QUAKE, payer, not_implemented(R_QUAKE_RESIDENTIAL, ids))
            return False
        if obj == "dwelling" and (a.get("residential_use") is False or (ratio is not None and ratio["num"] == 0)):
            acc.note(V_QUAKE, payer, ids)
            return False  # 常時その居住の用に供する家屋でない：第77条第1項の地震保険料に当たらない
        if owner == payer:
            return True
        if plan == R_GONE:
            # 保険の目的の所有者がこの年分に生存していない：数える・数えないの一次情報がない（数える値で入れ、未確定にする）
            acc.undetermined(V_QUAKE, payer, reading_split(T_GONE, r["id"], {"person": payer, "記録": ids, "所有者": owner}, ("数える", "数えない")))
            return True
        if isinstance(plan, str) or plan is None:
            acc.exclude(V_QUAKE, payer, not_implemented(plan or R_QUAKE_OBJECT, ids))
            return False
        acc.note(V_QUAKE, payer, *self._kin_provenance(plan))
        return bool(self._livelihood_value(acc, V_QUAKE, plan, ids))


__all__ = ["InsuranceYear", "LIFE_VARS", "V_MUTUAL", "V_OLD_LONG", "V_QUAKE", "V_REGIME", "V_SOCIAL"]
