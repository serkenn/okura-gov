"""規則モジュール kokuho の入力の組み立て：国保世帯のグループ、注入データの1か所、入力変数、段階評価の段（所得の段階・端数）。

年度 F の値は所得の年分 F−1 の situation で計算する（timepoints.kokuho_window）。窓口がない situation（所得税の年分だけなど）でも
全員の入力に仮の値を書き、グループは全員を自分だけの世帯の世帯主にする（値は使われない）。

未確定（D19）：次の場合は保険料（税）の額を決められないので、入力 国保_賦課の定め に分かれ目（missing）を付ける。
  - 率・額・方式・賦課限度額が注入されていない（候補を持たない注入点。injection.py）。注入データに必要な区分がない。
  - 年度の途中の資格の取得・喪失、年度の途中の40歳・65歳の到達で、注入データ 国保.年度の途中の資格の月割り がない、又は月の数え方が
    「その他」（月割りは法令に見つからない：[KHP] §13-2、[PS3-KH] §2。条例の事項）。注入されていれば月割りで計算する。
  - 産前産後の減額の期間があり、注入データ 国保.産前産後の減額の算定 がない（「期間に係る額を基準として算定」の具体は条例：[PS3-KH] §3）。
  - 特定世帯・特定継続世帯で、注入データ 国保.特定世帯の世帯別平等割額 がない。特定世帯の区分が年度の中・「経過する月」の読みで変わる。
  - 資産割の基礎が固定資産税額の全部で、償却資産の記録がある（中間表現に償却資産に係る税額の語彙がない）、
    又はほかの市町村の固定資産税額がある（どの市町村の税額を基礎にするかは docs で未確認）。
  - 世帯の市町村が分からない（賦課期日の住民票の記録がない被保険者）。
  - 年度の政令の基準（軽減の基準額・賦課限度額）が未登録（令和9年度：[PS3-KH] §1。入力 国保_年度の政令の基準が登録されているか、公表待ち）。
  - 国保法第116条でみなされる世帯が親の世帯で1つに決まらない（事実）。第116条の2 の人で入院等の前日の住民票がない・入院等の種類の欄がなく
    親がほかの世帯にいる（事実）、みなされる住所の市町村と世帯の市町村が違う（一次情報）。
按分・減額の1円未満は注入データ 国保.端数処理（未注入なら3つの候補の全部）で丸める。国保税の課税標準の千円未満（地方税法第20条の4の2第1項が
及ぶか一次情報で未確認）と、月割りと賦課限度額の順序は、段階評価の段 国保の端数の判定 で、候補の全部で計算して分かれれば分かれ目を付ける。
非自発的失業者の特例は、段 国保の所得の段階 が住民税の窓口の値から入力を書く。
第116条の2 で児童福祉施設に措置入所した扶養義務者のいる子の世帯は、注入データ 国保.児童福祉施設に措置入所した子の世帯（未注入なら2つの型の候補）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...registry import (
    GroupInstance,
    InjectionSlot,
    InjectionSpec,
    ModuleInputs,
    RecordKind,
    RoundingSlotSpec,
    StageContext,
    StageOutput,
    StageSpec,
    YearContext,
    injection_key,
)
from ...result import Means, OutOfScopeCategory, OutOfScopeReason, Split, State
from .calc import (
    KUBUN_ALL,
    Household,
    MunicipalRules,
    household_premium,
    personal_income_levy,
    rules_from_json,
    rules_to_json,
    unemployment_cut,
    介護,
    方式_イ,
    子ども,
    特定世帯,
    特定継続世帯,
)
from .facts import (
    AUTHORITY_DECISIONS,
    AUTHORITY_TAX_ITEM,
    CHILD_HOME,
    HouseholdPlan,
    PersonFacts,
    deem_institution,
    deem_student,
    households,
    month_index,
    person_facts,
)

_KHP = "docs/public-sources/20261109_round2_kokuho-premium-structure.md"
_PS3 = "docs/public-sources/20261111_impl-research3_kokuho-laws.md"
_PS4 = "docs/public-sources/20261112_impl-research4_kokuho-laws.md"

#: 国保法第116条の2 の人の 国保_被保険者か に付ける根拠（住所だけをみなし、世帯は事実の世帯：仮説 H7）。
INSTITUTION_BASIS = BasisEntry(
    BasisType.RULE,
    "国保法第116条の2（入院等の特例）の住所と世帯",
    SourceKind.LAW,
    (f"{_PS4}#1", f"{_PS4}#1.1"),
    flags=(ReadingFlag.LEGAL_READING,),
    law=(
        "国民健康保険法第116条の2第1項・第2項：入院等をした際の他の市町村に住所を有するものとみなす（入院等の前日の住民票の市町村。継続入院等は最初の病院等への"
        "入院等の日を特例の始まりとして記録する）。第116条の「当該世帯に属するものとみなす」の文言がないので、世帯は入院等により属することとなった世帯"
        "（国保則第5条の2 の語）で計算する（法令の読み）。児童福祉施設に措置入所した扶養義務者のいる子の世帯は市町村の運用（注入データ）"
    ),
)

V_INSURED = "国保_被保険者か"
V_MONTHS = "国保_被保険者である月数"
V_KAIGO_MONTHS = "国保_介護納付金賦課被保険者である月数"
V_ADULT = "国保_十八歳以上被保険者か"
V_SPECIFIED = "国保_特定同一世帯所属者か"
V_PRESCHOOL = "国保_未就学児か"
V_ASSET = "国保_資産割の基礎の額"
V_UNEMPLOYED = "国保_非自発的失業者の特例の対象か"
V_RULES = "国保_賦課の定め"
V_SEIREI = "国保_年度の政令の基準が登録されているか"
V_EXACT = "国保_保険料の額が端数の定めなしで決まるか"
V_LIMIT_ORDER = "国保_保険料の額が月割りと限度額の順序で変わらないか"
V_BASE = "国保_基礎控除後の総所得金額等"
V_TIER = "国保_軽減の区分"
V_RULE_MONTHS = "国保_月割りの月数"
V_RULE_KAIGO = "国保_介護の月割りの月数"
V_BIRTH = "国保_産前産後の減額の月数"
V_BIRTH_KAIGO = "国保_介護の産前産後の減額の月数"
V_CUT = "国保_非自発的失業者の特例で総所得金額から減る額"
V_CUT_KEIGEN = "国保_非自発的失業者の特例で軽減判定の所得から減る額"
#: 2026-11-12（語彙の突き合わせ）：世帯に、その年度の保険料（税）の減免の承認（authority_decision の reduction_approved）があるか
V_REDUCTION = "国保_減免の承認があるか"

# 段 国保の所得の段階 が読む住民税・所得税の値
R_SALARY = "住民税_給与所得の金額"
R_GOKEI = "住民税_合計所得金額"
R_RETIRE = "住民税_総所得金額等に含まれる退職所得金額"
R_SEP = "住民税_上場株式等に係る分離課税の所得の金額"
R_LISTED_CARRY = "住民税_上場株式等の譲渡損失の繰越控除額"
R_FAMILY = "住民税_事業専従者給与等の額"
R_ADJUST = "所得税_所得金額調整控除"
R_ICHIJI = "所得税_一時所得の金額"

POINT_LEVY = "国保.料か税か"
POINT_METHOD = "国保.賦課の方式"
POINT_RATES = "国保.率と額"
POINT_LIMIT = "国保.賦課限度額"
POINT_KEIGEN = "国保.軽減の割合"
POINT_PRESCHOOL = "国保.未就学児の均等割の減額"
POINT_ROUND = "国保.端数処理"
POINT_MONTHLY = "国保.年度の途中の資格の月割り"
POINT_BIRTH = "国保.産前産後の減額の算定"
POINT_SPECIFIED_HH = "国保.特定世帯の世帯別平等割額"
#: 2026-11-12：第116条の2第1項第2号の子の世帯（世帯の組み方を変えるので、ほかの注入点の1か所とは別に宣言する）
POINT_CHILD = "国保.児童福祉施設に措置入所した子の世帯"
POINTS_USED = (
    POINT_LEVY, POINT_METHOD, POINT_RATES, POINT_LIMIT, POINT_KEIGEN, POINT_PRESCHOOL,
    POINT_ROUND, POINT_MONTHLY, POINT_BIRTH, POINT_SPECIFIED_HH,
)  # fmt: skip

STAGE_EXACT = "国保の端数の判定"
STAGE_INCOME = "国保の所得の段階"

#: 非自発的失業者の特例の給与所得の100分の30の1円未満（法令に端数の定めが見つからない：[KHP] §4.3。D21 R5 で候補の全部）。
ROUND_UNEMPLOYED = "国保の非自発的失業者の特例の100分の30"
ROUNDINGS = (RoundingSlotSpec(ROUND_UNEMPLOYED, None, "非自発的失業者の特例で給与所得を100分の30にした額の1円未満の端数（根拠が見つからず候補で評価）"),)

#: 注入データ 国保.年度の途中の資格の月割り の月の数え方のうち、計算できるもの。
MONTHS_STANDARD = "取得した月から喪失した月の前月まで"
#: 注入データ 国保.年度の途中の資格の月割り の 月割りと賦課限度額の順序 のうち、計算できるもの（2026-11-12）。
LIMIT_AFTER_PRORATE = "月割りした後の額に賦課限度額を当てる"

R_NO_HEAD = "住民票の世帯の世帯主が中間表現の人にいない（世帯主の所得と納付義務者が分からない）"
R_LIMIT_OVER = "注入データの賦課限度額が政令の額を超える（国保令第29条の7・地方税法第703条の4 の限度額を超えることができない）"


def kubun_names(fiscal_year: int) -> tuple[str, ...]:
    """その年度の区分（子ども・子育て支援納付金賦課額は令和8年度から：[KHP] §2.3）。"""
    return KUBUN_ALL if fiscal_year >= 2026 else tuple(k for k in KUBUN_ALL if k != 子ども)


def _split(sid: str, means: Means, target: Mapping[str, Any], candidates: tuple[str, ...] = ()) -> Split:
    return Split(id=sid, means=means, target=dict(target), candidates=candidates, splits_conclusion=True)


def _ratio(v: Mapping[str, Any]) -> Fraction:
    return Fraction(int(v["num"]), int(v["den"]))


@dataclass
class Plan:
    """年度 F の世帯と人の事実（build_inputs・グループ・注入データの1か所・段で同じものを使う）。"""

    fiscal_year: int
    levy_day: _dt.date
    facts: dict[str, PersonFacts]
    households: list[HouseholdPlan]
    of: dict[str, HouseholdPlan] = field(default_factory=dict)

    def nhi(self, h: HouseholdPlan) -> bool:
        return any(self.facts[p].insured for p in h.members)

    def insured(self, h: HouseholdPlan) -> list[PersonFacts]:
        return [self.facts[m] for m in h.members if self.facts[m].insured]


def child_key(f: PersonFacts, levy_day: _dt.date) -> str:
    """注入点 国保.児童福祉施設に措置入所した子の世帯 の1か所（第116条の2 でみなされる住所の市町村 × 賦課期日）。"""
    return injection_key("municipality", str(f.deemed_municipality), levy_day)


def plan(ctx: YearContext, home: bool | None = None) -> Plan | None:
    """年度 F の世帯と人の事実。home は第116条の2 の児童福祉施設の子を親元の世帯に入れるか：None なら注入データの1か所
    （国保.児童福祉施設に措置入所した子の世帯）を引く。注入データの1か所を宣言する前（slots）は True・False を渡して両方を見る。"""
    w = ctx.window("国保", "年度")
    if w is None:
        return None
    fy = int(w.time.value)
    levy_day = w.date("賦課期日")
    facts = {p: person_facts(ctx, p, fy) for p in ctx.persons}
    deem_student(ctx, facts, levy_day)

    def home_of(f: PersonFacts) -> bool:
        if home is not None:
            return home
        dec = ctx.injection(POINT_CHILD, child_key(f, levy_day))
        f.child_choice = dec
        return (dec.value or {}).get("世帯") == CHILD_HOME

    deem_institution(ctx, facts, levy_day, home_of)
    hs = households(ctx, facts)
    p = Plan(fy, levy_day, facts, hs)
    for h in hs:
        for m in h.members:
            p.of[m] = h
    return p


# ---------------------------------------------------------------------------
# 世帯ごとの事実の判定（月割り・特定世帯）
# ---------------------------------------------------------------------------


def needs_monthly(p: Plan, h: HouseholdPlan) -> bool:
    """年度の途中の資格の取得・喪失、40歳・65歳の到達がある被保険者がいるか（月割りの条例が要る）。"""
    for f in p.insured(h):
        if f.months != 12 or f.kaigo_months not in (0, 12) or len(f.rule_months) != 12:
            return True
        if len(f.rule_kaigo_months) not in (0, 12) or bool(f.rule_kaigo_months) != (f.kaigo_months > 0):
            return True
    return False


#: 特定世帯の「特定月以後五年を経過する月」・特定継続世帯の「八年を経過する月」の数え方の候補（特定月から数えた月の差の上限）。
#: 国保令第29条の7第2項第8号イ（[PS3-KH] §4）の「経過する月」が特定月から60月目（5年後の同じ月）か59月目（その前月）かは docs で決まらない。
SPECIFIED_READINGS: tuple[tuple[str, int, int], ...] = (("5年後の同じ月まで", 60, 96), ("5年後の同じ月の前月まで", 59, 95))


def specified_class(on: _dt.date, fiscal_year: int) -> tuple[str | None, bool]:
    """特定同一世帯所属者になった日 on（特定月はその日の属する月）から、年度 F の各月の区分（特定世帯・特定継続世帯・どちらでもない）。
    返り値は（区分, 年度の中又は読みで区分が変わるか）。"""
    start = month_index(on, fiscal_year)
    seen: set[str | None] = set()
    for _, five, eight in SPECIFIED_READINGS:
        for m in range(12):
            d = m - start
            seen.add(特定世帯 if 0 <= d <= five else 特定継続世帯 if five < d <= eight else None)
    if len(seen) == 1:
        return next(iter(seen)), False
    return None, True


# ---------------------------------------------------------------------------
# グループ（国保世帯）
# ---------------------------------------------------------------------------


def build_groups(ctx: YearContext) -> list[GroupInstance]:
    p = plan(ctx)
    if p is None:
        return [GroupInstance(f"solo:{q}", {"世帯主一覧": (q,), "世帯員一覧": ()}) for q in ctx.persons]
    out = []
    for h in p.households:
        persons = h.persons
        out.append(
            GroupInstance(
                h.key,
                {"世帯主一覧": (persons[0],), "世帯員一覧": tuple(persons[1:])},
                tuple(sorted(set(h.record_ids))),
                frozenset(h.states),
            )
        )
    return out


# ---------------------------------------------------------------------------
# 注入データの1か所（世帯の市町村 × 賦課期日）
# ---------------------------------------------------------------------------


def _wants(ctx: YearContext, p: Plan, h: HouseholdPlan, point: str, key: str) -> bool:
    """その世帯でその注入点の1か所が要るか（要らない世帯の分かれ目を開かない）。"""
    if point == POINT_PRESCHOOL:
        return any(p.facts[m].preschool for m in h.members)
    if point == POINT_ROUND:
        # 率と額が注入されているときだけ（率と額がなければ保険料の額は未確定で、端数処理の候補を評価しても結論は変わらない）
        return ctx.injected.find(POINT_RATES, "municipality", str(h.municipality), p.levy_day) is not None
    if point == POINT_MONTHLY:
        return needs_monthly(p, h)
    if point == POINT_BIRTH:
        return any(f.birth_months for f in p.insured(h))
    if point == POINT_SPECIFIED_HH:
        return _specified(p, h)[0] is not None
    return True


def _specified(p: Plan, h: HouseholdPlan) -> tuple[str | None, bool]:
    """世帯の特定世帯・特定継続世帯の区分（特定同一世帯所属者がいて、ほかの被保険者がいない世帯：被保険者が1人）。"""
    spec = [p.facts[m] for m in h.members if p.facts[m].specified and p.facts[m].specified_on is not None]
    if not spec or len(p.insured(h)) != 1:
        return None, False
    classes = {specified_class(f.specified_on, p.fiscal_year) for f in spec}  # type: ignore[arg-type]
    if len(classes) != 1:
        return None, True
    return next(iter(classes))


def _variants(ctx: YearContext) -> list[Plan]:
    """注入データの1か所を宣言する前に見る世帯の組み方：児童福祉施設の子がいれば、事実の世帯と親元の世帯の両方。"""
    p = plan(ctx, home=False)
    if p is None:
        return []
    if not any(f.child_home for f in p.facts.values()):
        return [p]
    q = plan(ctx, home=True)
    return [p] + ([q] if q is not None else [])


def _slots(point: str) -> Any:
    def slots(ctx: YearContext) -> list[InjectionSlot]:
        out: dict[str, InjectionSlot] = {}
        for p in _variants(ctx):
            for h in p.households:
                if not p.nhi(h) or h.municipality is None:
                    continue
                key = injection_key("municipality", h.municipality, p.levy_day)
                if not _wants(ctx, p, h, point, key):
                    continue
                prev = out.get(key)
                persons = tuple(sorted(set(h.members) | set(prev.persons or () if prev else ())))
                out[key] = InjectionSlot(key, "municipality", h.municipality, p.levy_day, {"年度": p.fiscal_year}, persons=persons)
        return list(out.values())

    return slots


def child_slots(ctx: YearContext) -> list[InjectionSlot]:
    """第116条の2第1項第2号で住所をみなされる、扶養義務者がほかの世帯にいる子の市町村ごとの1か所（facts.deem_institution）。"""
    p = plan(ctx, home=False)
    if p is None:
        return []
    out: dict[str, InjectionSlot] = {}
    for f in p.facts.values():
        if f.child_home is None:
            continue
        key = child_key(f, p.levy_day)
        parents = [m for m, g in p.facts.items() if g.household == f.child_home]
        prev = out.get(key)
        persons = tuple(sorted({f.pid, *parents} | set(prev.persons or () if prev else ())))
        out[key] = InjectionSlot(key, "municipality", str(f.deemed_municipality), p.levy_day, {"年度": p.fiscal_year}, persons=persons)
    return list(out.values())


INJECTIONS = tuple(InjectionSpec(pt, _slots(pt)) for pt in POINTS_USED) + (InjectionSpec(POINT_CHILD, child_slots),)


# ---------------------------------------------------------------------------
# 賦課の定め（注入データを1つの文字列にする）
# ---------------------------------------------------------------------------


@dataclass
class RulesInput:
    text: str
    record_ids: list[str] = field(default_factory=list)
    basis: list[Any] = field(default_factory=list)
    missing: list[Split] = field(default_factory=list)
    excluded: str | None = None
    #: 月割りで計算するか（注入データ 国保.年度の途中の資格の月割り が月割りする・数え方が標準）
    prorate: bool = False
    #: 月割りと賦課限度額の順序（注入データの欄。LIMIT_AFTER_PRORATE・その他・None〔欄がない〕）
    limit_order: str | None = None
    #: 産前産後の減額を計算するか（注入データ 国保.産前産後の減額の算定 がある）
    birth: bool = False


def household_rules(ctx: YearContext, p: Plan, h: HouseholdPlan) -> RulesInput:
    """世帯の市町村の賦課の定め（JSON の文字列）と、決まらない理由（missing）。"""
    fy = p.fiscal_year
    target_base = {"世帯": h.key, "年度": fy}
    out = RulesInput("")
    if h.municipality is None:
        out.missing.append(_split(f"事実:国保の世帯の市町村:{h.key}:{fy}", Means.FACT, {**target_base, "事項": "賦課期日の住民票の記録（世帯の市町村）"}))
        return out
    key = injection_key("municipality", h.municipality, p.levy_day)

    def get(point: str) -> Any:
        dec = ctx.injection(point, key)
        out.record_ids.extend(dec.record_ids)
        out.basis.extend(dec.basis)
        out.missing.extend(dec.missing)
        return dec.value

    levy = (get(POINT_LEVY) or {}).get("賦課", "料")
    methods = {x["区分"]: x for x in (get(POINT_METHOD) or {}).get("区分", [])}
    rates = {x["区分"]: x for x in (get(POINT_RATES) or {}).get("区分", [])}
    limits = {x["区分"]: x["限度額"] for x in (get(POINT_LIMIT) or {}).get("区分", [])}
    keigen = (get(POINT_KEIGEN) or {}).get("割合", "7割・5割・2割")
    members = [p.facts[m] for m in h.members]
    insured = p.insured(h)
    preschool: Fraction | None = None
    if any(f.preschool for f in members):
        if levy == "税":
            v = get(POINT_PRESCHOOL)
            if v is not None:
                preschool = _ratio(v["減額の割合"])
        else:
            r = ctx.parameters.国保.未就学児の均等割の減額の割合
            preschool = Fraction(int(r.分子), int(r.分母))
            out.basis.append(ctx.parameter_basis("国保.未就学児の均等割の減額の割合.分子"))
    names = kubun_names(fy)
    seirei = ctx.parameters.国保.賦課限度額
    kubun: dict[str, dict[str, Any]] = {}
    # 方式・率と額・限度額が全部注入されているのに、その年度の区分の行がない
    injected_all = not any(s.means is Means.INJECTION and s.target.get("注入点") in (POINT_METHOD, POINT_RATES, POINT_LIMIT) for s in out.missing)
    for k in names:
        m, r, lim = methods.get(k), rates.get(k), limits.get(k)
        if injected_all and (m is None or r is None or lim is None):
            out.missing.append(
                _split(f"注入:国保の区分:{h.municipality}:{fy}:{k}", Means.INJECTION, {**target_base, "事項": f"注入データに区分 {k} の方式・率と額・賦課限度額がない"})
            )
        row: dict[str, Any] = {"方式": (m or {}).get("方式", "所得割・被保険者均等割")}
        for f_name in ("所得割率", "資産割率", "被保険者均等割額", "世帯別平等割額", "18歳以上被保険者均等割額"):
            if r is not None and f_name in r:
                row[f_name] = r[f_name]
        row["限度額"] = lim
        if lim is not None and lim > int(getattr(seirei, k)):
            out.excluded = R_LIMIT_OVER
        if row["方式"] == 方式_イ:
            basis_kind = (m or {}).get("資産割の基礎")
            if basis_kind is None:
                out.missing.append(_split(f"注入:国保の資産割の基礎:{h.municipality}:{fy}", Means.INJECTION, {**target_base, "事項": "資産割の基礎（固定資産税額か土地・家屋に係る部分か）"}))
            elif basis_kind == "固定資産税額" and any(f.depreciable for f in insured):
                out.missing.append(_split(f"事実:国保の償却資産:{h.key}:{fy}", Means.FACT, {**target_base, "事項": "償却資産に係る固定資産税額（中間表現に語彙がない）"}))
            if any(f.asset_other_municipality for f in insured):
                out.missing.append(
                    _split(f"一次情報:国保の資産割の市町村:{h.key}:{fy}", Means.PRIMARY_SOURCE, {**target_base, "事項": "ほかの市町村の固定資産税額を資産割の基礎に含めるか（docs で未確認）"})
                )
        kubun[k] = row
    # 端数処理（按分・減額の1円未満。率と額が注入されているときだけ宣言した1か所）
    rounding = None
    if _wants(ctx, p, h, POINT_ROUND, key):
        v = get(POINT_ROUND)
        rounding = None if v is None else v["1円未満"]
    # 年度の途中の資格の取得・喪失、40歳・65歳の到達の月割り（条例）
    month_ratio: Fraction | None = None
    hh_months = hh_kaigo = 12
    if needs_monthly(p, h):
        v = get(POINT_MONTHLY)
        if v is not None and v["月割りする"]:
            if v.get("月の数え方") == MONTHS_STANDARD and v.get("1月分の割合") is not None:
                out.prorate = True
                out.limit_order = v.get("月割りと賦課限度額の順序")
                month_ratio = _ratio(v["1月分の割合"])
                hh_months = len(frozenset().union(*(f.rule_months for f in insured)))
                hh_kaigo = len(frozenset().union(*(f.rule_kaigo_months for f in insured)))
            else:
                out.missing.append(
                    _split(
                        f"注入:国保の月割りの数え方:{h.key}:{fy}",
                        Means.INJECTION,
                        {**target_base, "注入点": POINT_MONTHLY, "事項": f"月の数え方が「{MONTHS_STANDARD}」でないか1月分の割合がない（計算の方法が決まらない）"},
                    )
                )
    # 産前産後の減額（国保令第29条の7第6項第8号・第9号。期間に係る額の算定は条例）
    birth_ratio: Fraction | None = None
    if any(f.birth_months for f in insured):
        v = get(POINT_BIRTH)
        if v is not None:
            out.birth = True
            birth_ratio = _ratio(v["1月分の割合"])
    # 特定世帯・特定継続世帯の世帯別平等割額（国保令第29条の7第2項第8号ロ・ハ。介護の区分にはない）
    specified, changes = _specified(p, h)
    if changes:
        out.missing.append(
            _split(
                f"読み:国保の特定世帯の区分:{h.key}:{fy}",
                Means.PRIMARY_SOURCE,
                {**target_base, "事項": "特定世帯・特定継続世帯の区分が年度の途中か「経過する月」の読みで変わる（年度の途中の切替えは条例の月割り：[PS3-KH] §4）"},
                tuple(name for name, _, _ in SPECIFIED_READINGS),
            )
        )
    elif specified is not None:
        v = get(POINT_SPECIFIED_HH)
        if v is not None:
            amounts = {x["区分"]: x for x in v["区分"]}
            for k in names:
                if k == 介護:
                    continue
                a = amounts.get(k)
                if a is None:
                    out.missing.append(
                        _split(f"注入:国保の特定世帯の額:{h.municipality}:{fy}:{k}", Means.INJECTION, {**target_base, "事項": f"注入データに区分 {k} の特定世帯の額がない"})
                    )
                    continue
                kubun[k]["特定世帯の世帯別平等割額"] = a["特定世帯の額" if specified == 特定世帯 else "特定継続世帯の額"]
    out.text = rules_to_json(
        levy, kubun, keigen, preschool,
        rounding=rounding, specified=specified, month_ratio=month_ratio, birth_ratio=birth_ratio,
        household_months=hh_months, household_kaigo_months=hh_kaigo,
    )  # fmt: skip
    return out


# ---------------------------------------------------------------------------
# 入力変数
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    V_INSURED: False,
    V_MONTHS: 0,
    V_KAIGO_MONTHS: 0,
    V_ADULT: False,
    V_SPECIFIED: False,
    V_PRESCHOOL: False,
    V_ASSET: 0,
    V_UNEMPLOYED: False,
    V_RULES: "",
    V_SEIREI: True,
    V_RULE_MONTHS: 0,
    V_RULE_KAIGO: 0,
    V_BIRTH: 0,
    V_BIRTH_KAIGO: 0,
    V_REDUCTION: False,
}


def _states(f: PersonFacts, *whats: str) -> set[State]:
    out: set[State] = set()
    for w in whats:
        out |= f.states.get(w, set())
    return out


def _ids(f: PersonFacts, *whats: str) -> list[str]:
    return [i for w in whats for i in f.record_ids.get(w, [])]


def person_weights(f: PersonFacts, prorate: bool, birth_on: bool) -> tuple[int, int, int, int]:
    """月割りの月数・介護の月割りの月数・産前産後の減額の月数・介護の産前産後の減額の月数。
    月割りしない世帯は、被保険者は12、介護納付金賦課被保険者は（全部の日で40歳以上65歳未満の月があれば）12。"""
    if not f.insured:
        return 0, 0, 0, 0
    if prorate:
        months, kaigo = len(f.rule_months), len(f.rule_kaigo_months)
    else:
        months, kaigo = 12, 12 if f.kaigo_months > 0 else 0
    if birth_on:
        birth = len(f.birth_months)
        birth_kaigo = len(f.birth_months & f.rule_kaigo_months) if prorate else (birth if kaigo else 0)
    else:
        birth = birth_kaigo = 0
    return months, kaigo, birth, birth_kaigo


def build_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    p = plan(ctx)
    if p is None:
        for q in ctx.persons:
            for v, x in _DEFAULTS.items():
                out.set(v, q, x)
        return out
    fy = p.fiscal_year
    seirei_year = int(ctx.parameters.国保.政令の基準の年度)
    seirei_missing = (
        []
        if seirei_year == fy
        else [
            _split(
                f"公表待ち:国保の政令の基準:{fy}",
                Means.AWAITING_PUBLICATION,
                {"年度": fy, "事項": f"国保令第29条の7・地方税法施行令第56条の88の2・第56条の89 のこの年度の版（軽減の基準額・賦課限度額）が未公布（{_PS3} §1）"},
            )
        ]
    )
    rules_of: dict[str, RulesInput] = {}
    for h in p.households:
        if p.nhi(h):
            rules_of[h.key] = household_rules(ctx, p, h)
    for q in ctx.persons:
        f = p.facts[q]
        h = p.of[q]
        r = rules_of.get(h.key)
        special_missing = [_split(f"{sid}:{q}:{fy}", means, {"person": q, "年度": fy, "事項": what}) for sid, means, what in f.problems]
        insured_ids, insured_states = _ids(f, "被保険者", "特例"), _states(f, "被保険者", "特例")
        insured_basis: list[Any] = []
        if f.special_case == "institution_special_case":
            insured_basis.append(INSTITUTION_BASIS)
        if f.child_choice is not None:
            insured_ids += list(f.child_choice.record_ids)
            insured_states |= set(f.child_choice.states)
            insured_basis += list(f.child_choice.basis)
            special_missing += list(f.child_choice.missing)
        out.set(V_INSURED, q, f.insured, insured_ids, insured_states, basis=insured_basis, missing=special_missing)
        out.set(V_MONTHS, q, f.months, _ids(f, "被保険者"), _states(f, "被保険者"))
        out.set(V_KAIGO_MONTHS, q, f.kaigo_months, _ids(f, "被保険者"), _states(f, "被保険者"))
        out.set(V_ADULT, q, f.adult18, _ids(f, "被保険者"), _states(f, "被保険者"))
        out.set(V_SPECIFIED, q, f.specified, _ids(f, "特定同一世帯所属者"), _states(f, "特定同一世帯所属者"))
        out.set(V_PRESCHOOL, q, f.preschool, _ids(f, "被保険者"), _states(f, "被保険者"))
        out.set(V_ASSET, q, f.asset, _ids(f, "資産"), _states(f, "資産"))
        out.set(V_UNEMPLOYED, q, f.unemployed, _ids(f, "非自発的失業"), _states(f, "非自発的失業"))
        out.set(V_SEIREI, q, seirei_year == fy, missing=seirei_missing)
        months, kaigo, birth, birth_kaigo = person_weights(f, r is not None and r.prorate, r is not None and r.birth)
        out.set(V_RULE_MONTHS, q, months, _ids(f, "被保険者"), _states(f, "被保険者"))
        out.set(V_RULE_KAIGO, q, kaigo, _ids(f, "被保険者"), _states(f, "被保険者"))
        out.set(V_BIRTH, q, birth, _ids(f, "出産"), _states(f, "出産"))
        out.set(V_BIRTH_KAIGO, q, birth_kaigo, _ids(f, "出産"), _states(f, "出産"))
        # 減免の承認は世帯の値（世帯の全員に同じ値。保険料は世帯主に課され、減免もその保険料について行われる：国保法第76条第1項・第77条）
        red = reduction_records(p, h)
        out.set(V_REDUCTION, q, bool(red), [e["id"] for e in red], {State.from_mark(e["mark"]) for e in red if "mark" in e})
        if r is None:
            out.set(V_RULES, q, "")
        else:
            out.set(V_RULES, q, r.text, r.record_ids, basis=r.basis, missing=r.missing)
            if r.excluded:
                out.exclude(q, OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, r.excluded, tuple(r.record_ids)), V_RULES)
    for h in p.households:
        if p.nhi(h) and h.head is None and not h.key.startswith("solo:"):
            for m in h.members:
                out.exclude(m, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, R_NO_HEAD, tuple(h.record_ids)), V_INSURED)
    return out


# ---------------------------------------------------------------------------
# 段階評価の段：所得の段階（非自発的失業者の特例）
# ---------------------------------------------------------------------------


def run_income(ctx: StageContext) -> StageOutput:
    """非自発的失業者の特例（国保令第29条の7の2・地方税法第703条の5の2：[KHP] §4.3）で総所得金額から減る額。

    上場株式等に係る譲渡所得等の金額は、譲渡損失の繰越控除（地方税法附則第35条の2の6第11項）の後の額（住民税.上場株式等に係る分離課税の所得の金額）を
    使う（2026-11-12 に読みの分かれ目をやめた：軽減は国保令第29条の7第6項第1号のかっこ書きの明文、所得割は附則第35条の2の6第13項の読替え。
    docs/public-sources/20261112_impl-research4_kokuho-laws.md §2、仮説 H8）。ここでは損益通算の後・繰越控除の前の総所得金額を求めるのに読む。"""
    out = StageOutput()
    p = plan(ctx)
    fy = None if p is None else p.fiscal_year
    for q in ctx.persons:
        carry = ctx.value(R_LISTED_CARRY, q)
        f = None if p is None else p.facts[q]
        if f is None or not f.unemployed:
            out.set(V_CUT, q, 0, uses=())
            out.set(V_CUT_KEIGEN, q, 0, uses=())
            continue
        vals = {v: ctx.value(v, q) for v in (R_SALARY, R_GOKEI, R_RETIRE, R_SEP, R_FAMILY, R_ADJUST, R_ICHIJI)}
        salary = int(vals[R_SALARY].value)
        gross = int(vals[R_GOKEI].value) - int(vals[R_RETIRE].value) - int(vals[R_SEP].value) - int(carry.value)
        exact = Fraction(3 * salary, 10)
        thirty = int(exact) if exact.denominator == 1 else ctx.round_unfounded(ROUND_UNEMPLOYED, exact)
        missing: list[Split] = []
        tgt = {"person": q, "年度": fy}
        if int(vals[R_ADJUST].value) > 0:
            missing.append(
                _split(
                    f"読み:国保の非自発的失業者の特例と所得金額調整控除:{q}:{fy}",
                    Means.PRIMARY_SOURCE,
                    {**tgt, "事項": "所得金額調整控除がある人の給与所得の100分の30（所得税法第28条第2項の額の30%に置き換えるとき、調整控除を引くか。docs に一次情報がない）"},
                    ("調整控除を引かない", "調整控除を引く"),
                )
            )
        ichiji = int(vals[R_ICHIJI].value)
        if ichiji > 0 and gross - ichiji < salary - thirty:
            missing.append(
                _split(
                    f"一次情報:国保の非自発的失業者の特例と一時所得:{q}:{fy}",
                    Means.PRIMARY_SOURCE,
                    {**tgt, "事項": "給与所得を減らすと損益通算で一時所得（2分の1の前）に損失が及び、減る額が決まらない（一時所得の2分の1の端数の一次情報がない）"},
                )
            )
        used = [carry, *vals.values()]
        out.set(V_CUT, q, unemployment_cut(salary, gross, thirty), _ids(f, "非自発的失業"), _states(f, "非自発的失業"), uses=used, missing=missing)
        family = int(vals[R_FAMILY].value)
        out.set(V_CUT_KEIGEN, q, unemployment_cut(salary, gross + family, thirty), _ids(f, "非自発的失業"), _states(f, "非自発的失業"), uses=used, missing=missing)
    return out


# ---------------------------------------------------------------------------
# 段階評価の段：端数の判定
# ---------------------------------------------------------------------------


def household_material(p: Plan, h: HouseholdPlan, base: Mapping[str, int], rules: MunicipalRules, prorate: bool = True) -> tuple[Household, list[int]]:
    """世帯の按分の基礎の合計と人数（calc.Household。月割り・産前産後の減額の重みつき）と、被保険者ごとの基礎控除後の総所得金額等。
    prorate=False は月割りしない年額（月割りと賦課限度額の順序を比べるため）。式 国保_保険料の額 と同じ重み。"""
    ins = p.insured(h)
    m = rules.month_ratio if prorate else Fraction(1, 12)
    b = rules.birth_ratio
    acc: dict[str, Fraction] = {k: Fraction(0) for k in ("base", "base_kaigo", "asset", "asset_kaigo", "insured", "kaigo", "adults", "preschool")}
    for f in ins:
        months, kaigo, birth, birth_kaigo = person_weights(f, prorate, b != 0)
        w = months * m
        wk = kaigo * m
        w_inc = w - birth * b
        wk_inc = wk - birth_kaigo * b
        acc["base"] += base[f.pid] * w_inc
        acc["base_kaigo"] += base[f.pid] * wk_inc
        acc["asset"] += f.asset * w
        acc["asset_kaigo"] += f.asset * wk
        acc["insured"] += w_inc
        acc["kaigo"] += wk_inc
        acc["adults"] += w_inc if f.adult18 else 0
        acc["preschool"] += w if f.preschool else 0
    hh = rules.household_months * m if prorate else Fraction(1)
    hk = rules.household_kaigo_months * m if prorate else Fraction(1)
    return Household(**acc, household=hh, household_kaigo=hk), [base[f.pid] for f in ins]


def run_exact(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    p = plan(ctx)
    if p is None:
        for q in ctx.persons:
            out.set(V_EXACT, q, True, uses=())
            out.set(V_LIMIT_ORDER, q, True, uses=())
        return out
    fy = p.fiscal_year
    names = kubun_names(fy)
    for h in p.households:
        values = {m: ctx.value(V_BASE, m) for m in h.members} if p.nhi(h) else {}
        tiers = {m: ctx.value(V_TIER, m) for m in h.members} if p.nhi(h) else {}
        used = list(values.values()) + list(tiers.values())
        missing: list[Split] = []
        order: list[Split] = []
        if p.nhi(h):
            ri = household_rules(ctx, p, h)
            r = rules_from_json(ri.text)
            if r is not None and set(names) <= set(r.kubun):
                base = {m: int(v.value) for m, v in values.items()}
                tier = str(tiers[h.persons[0]].value) or "なし"
                material, bases = household_material(p, h, base, r, prorate=ri.prorate)
                prem = household_premium(material, tier, r, names, bases)
                tgt = {"世帯": h.key, "年度": fy}
                personal = any(personal_income_levy(base[f.pid], f.kaigo, r, names).denominator != 1 for f in p.insured(h))
                if prem.fractional or personal:
                    # 端数処理の1か所を宣言していない世帯（率と額が未注入）だけ。保険料の額は率と額の分かれ目で未確定
                    missing.append(
                        _split(f"注入:国保の端数処理:{h.key}:{fy}", Means.INJECTION, {**tgt, "注入点": POINT_ROUND, "事項": "按分・減額の1円未満の端数処理（国保法第81条・条例の事項：[KHP] §10）"})
                    )
                if prem.base_not_thousand:
                    # 地方税法第20条の4の2第1項（千円未満の切捨て）が国保税の課税標準に及ぶかは一次情報で未確認：両方で計算して比べる
                    floored = {k: v // 1000 * 1000 for k, v in base.items()}
                    alt, _ = household_material(p, h, floored, r, prorate=ri.prorate)
                    alt_prem = household_premium(alt, tier, r, names, [])
                    levy_differs = any(
                        personal_income_levy(base[f.pid], f.kaigo, r, names) != personal_income_levy(floored[f.pid], f.kaigo, r, names) for f in p.insured(h)
                    )
                    if alt_prem.total != prem.total or levy_differs:
                        missing.append(
                            _split(
                                f"一次情報:国保税の課税標準の千円未満:{h.key}:{fy}",
                                Means.PRIMARY_SOURCE,
                                {**tgt, "事項": "国保税の課税標準に地方税法第20条の4の2第1項（千円未満の切捨て）が及ぶか（[KHP] §10）"},
                                ("及ばない", "千円未満を切り捨てる"),
                            )
                        )
                if ri.prorate and ri.limit_order != LIMIT_AFTER_PRORATE:
                    # 賦課限度額を月割りの後の額に当てるか、それ以外の定めか（注入データの欄 月割りと賦課限度額の順序。2026-11-12）：
                    # 欄がないか「その他」で、年額が限度額を超える区分があれば分かれる（式は月割りの後の額に当てる）
                    annual, _ = household_material(p, h, base, r, prorate=False)
                    over = [a.kubun for a in household_premium(annual, tier, r, names, []).kubun if a.exact != a.amount]
                    if over:
                        why = "欄がない" if ri.limit_order is None else "「その他」の定め（計算できない）"
                        order.append(
                            _split(
                                f"注入:国保の月割りと賦課限度額:{h.key}:{fy}",
                                Means.INJECTION,
                                {**tgt, "注入点": POINT_MONTHLY, "欄": "月割りと賦課限度額の順序", "事項": f"月割りと賦課限度額の順序（年額が限度額を超える区分：{'・'.join(over)}。{why}）"},
                            )
                        )
        for m in h.members:
            out.set(V_EXACT, m, not missing, uses=used, missing=missing)
            out.set(V_LIMIT_ORDER, m, not order, uses=used, missing=order)
    return out


STAGES = (
    StageSpec(
        name=STAGE_INCOME,
        title="国保の所得の段階：非自発的失業者の特例で総所得金額から減る額（住民税の窓口の値から決める）",
        reads=(R_SALARY, R_GOKEI, R_RETIRE, R_SEP, R_LISTED_CARRY, R_FAMILY, R_ADJUST, R_ICHIJI),
        writes=(V_CUT, V_CUT_KEIGEN),
        run=run_income,
    ),
    StageSpec(
        name=STAGE_EXACT,
        title="国保の保険料（税）の額に、課税標準の千円未満・月割りと限度額の順序が関わるか（計算した按分の基礎から決める）",
        reads=(V_BASE, V_TIER),
        writes=(V_EXACT, V_LIMIT_ORDER),
        run=run_exact,
    ),
)


def reduction_records(p: Plan, h: HouseholdPlan) -> list[Mapping[str, Any]]:
    """国保の世帯の誰かについての、その年度の減免の承認の記録（世帯の値）。"""
    return [e for m in h.persons for e in p.facts[m].reduction] if h.persons else []


def record_kinds() -> frozenset[str | RecordKind]:
    # authority_decision は税目（tax_item）で絞る（2026-11-12 の2回目：国民健康保険料〔税〕の処分＝減免の承認・修学中の特例の認定。
    # 住民税の処分〔減免・住民票と違う住所での課税〕は juminzei。処分の種類と税目の組合せは okura_ir の検査が止める）。以前は decision の値で絞っていた
    return frozenset(
        {
            "resident_record", "medical_insurance", "kokuho_event", "childbirth", "property_tax",
            RecordKind("authority_decision", "tax_item", frozenset({AUTHORITY_TAX_ITEM})),
        }
    )  # fmt: skip


__all__ = [
    "INJECTIONS",
    "ROUNDINGS",
    "STAGES",
    "build_groups",
    "build_inputs",
    "child_key",
    "child_slots",
    "household_material",
    "household_rules",
    "kubun_names",
    "needs_monthly",
    "person_weights",
    "plan",
    "record_kinds",
    "reduction_records",
    "specified_class",
]
