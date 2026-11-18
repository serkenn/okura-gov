"""段階評価の段（D23 K1、SCOPE §6-3）：住民税の扶養の割当て（地方税法施行令第46条の3〜第46条の5）と、扶養の連鎖の人の分の額。

2026-11-12（README JM-24〜26）：以前は所得税の扶養の割当て（personal_deductions の段の 所得税_扶養親族等の申告者）を写し、住民税と所得税で
分かれうる場合を対象外にしていた。いまは所得税と同じ純粋関数（okura_core/dependents：所属の規則・申告者との関係の事実・扶養の区分）を、
住民税の合計所得金額（地法第328条：分離課税に係る退職所得を除く）と住民税の所属の規則（地令46の5②：記載が2人以上・記載がなく決まらないときは
前年の総所得金額・退職所得金額・山林所得金額の合計額が最も大きい納税義務者。所得税の「既に記載している人」の段はない）で呼び、住民税の割当てを
独立に組み立てる（docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md §4.2）。

- 納税義務者：賦課期日（1月1日）に住所を有する人（住民税_賦課期日に住所を有する市町村）。その年の中途で死亡した人・国外へ移った人は
  住民税の扶養親族等を有する納税義務者にならない（所得税では準確定申告・出国の申告の申告者になりうる）。
- 判定の時：前年の12月31日（判定される人がそれより前に死亡していれば死亡の時。出国は判定の時を変えない）。
- 記載（2026-11-12 に人の区分で分けた：JM-33）：地令46の5①（46の3①・46の4① も同じ）は書類を記載した人の区分で分ける。申告書を提出する義務を有する者は
  申告書（住民税の申告書。前年分の確定申告書は地法第317条の3 で住民税の申告書とみなす）、給与所得等以外の所得を有しなかった者（地令46の3① の定義：
  jan1_payer_status と前年の所得の種類で判定）は給与支払報告書・公的年金等支払報告書（報告書の記録がなければ扶養控除等申告書等の記載：法令の読み）。
  給与所得等以外の所得を有しなかった者が申請書を出せば、その人の分は申請書の記載による（同条第1項ただし書）。区分が決まらない人は両方で評価し、
  所属が分かれれば未確定（決める手段：事実 jan1_payer_status）。
- 住民税の割当て・区分が所得税と同じ人は、所得税の判定（所得税_扶養親族に当たるか など）をそのまま使う。違う人（所属・合計所得金額・判定の時が違う）は、
  この段が住民税の区分を書き（住民税_別の判定の…）、`住民税_扶養の判定を所得税と別に行うか`・`住民税_本人の判定を所得税と別に行うか` で式が切り替える。
- 同額で決まらない所属は、地令46の5② に同額のときの定めがないので一次情報の分かれ目（候補の全部を未確定）。

扶養の連鎖（扶養親族等である人が自分も納税義務者）は、所得税と同じく自分のインスタンスの納税義務者に置き、その人の1人分の額を
段 住民税の扶養の連鎖の合計 が納税義務者に集める。
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ...dependents.allocation import (
    Alloc,
    Candidacy,
    DepListing,
    DependentLimits,
    RelationFacts,
    Rule,
    allocate_one,
    categorize,
    choose_spouses,
    largest,
    pair_candidacy,
    relation_facts,
)
from ...dependents.family import Family, build_family, nonresident_income_splits
from ...dependents.ir_facts import judgment_date
from ...dependents.kinship import age_on
from ...dependents.person_at import judgment_day, limits_from, person_at
from ...registry import GroupInstance, StageContext, StageOutput, StageValue
from ...result import Means, Split, State
from .calc import has_domicile

STAGE = "住民税の扶養の割当て"
STAGE_CHAIN = "住民税の扶養の連鎖の合計"

# --- 段 住民税の扶養の割当て が読む値 ---
R_CLAIMANT_IT = "所得税_扶養親族等の申告者"
R_TOTAL = "住民税_合計所得金額"
R_TOTAL_IT = "所得税_合計所得金額"
R_GROSS = "住民税_総所得金額等"
R_DOMICILE = "住民税_賦課期日に住所を有する市町村"
R_AGE = "所得税_年齢"
R_RESIDENT = "所得税_居住者か"
R_STUDY = "所得税_留学により国内に住所及び居所を有しなくなった者か"
R_DISABLED = "所得税_障害者に当たるか"
R_SPECIAL = "所得税_特別障害者に当たるか"
R_SP_LIVE = "所得税_配偶者と生計を一にするか"
R_SP_SENJU = "所得税_配偶者が青色事業専従者等か"
R_COHAB_SPOUSE = "所得税_配偶者等と同居を常況としているか"
R_DIVORCED = "所得税_夫と離婚した後婚姻をしていない者か"
R_MARRIED = "所得税_配偶者がいるか"
R_WIDOWED = "所得税_夫と死別した後婚姻をしていない者又は夫の生死の明らかでない者か"
R_DE_FACTO = "所得税_住民票に事実婚の続柄の記載がある相手がいるか"
R_MISSING = "所得税_配偶者の生死が明らかでない者か"
R_STUDENT = "所得税_学生に当たるか"
R_WAGE = "所得税_給与等の収入金額"
R_SALARY = "所得税_給与所得"
R_RETIRE = "所得税_退職所得の金額"
R_RETIRE_SEP = "住民税_分離課税に係る退職所得の金額"
R_BUSINESS = "所得税_事業所得の金額"
R_MISC = "所得税_雑所得の金額"
R_LABOR = "所得税_事業所得等が自己の勤労に基づくか"
#: 給与所得等以外の所得を有しなかった者か（地令46の3①）の材料（2026-11-12。JM-33）
R_DIVIDEND = "所得税_配当所得の金額"
R_REAL = "所得税_不動産所得の金額"
R_WINDFALL = "所得税_一時所得の金額"
R_PENSION_MISC = "所得税_公的年金等に係る雑所得の金額"
R_PENSION_RECEIPT = "所得税_公的年金等の収入金額"
R_LISTED_SEP = "住民税_上場株式等に係る分離課税の所得の金額"
#: 所得税の本人の側の判定（材料が所得税と同じ区分はそのまま写す）
R_IT_SPOUSE = "所得税_同一生計配偶者に当たるか"
R_IT_WIDOW = "所得税_寡婦に当たるか"
R_IT_SINGLE = "所得税_ひとり親に当たるか"
R_IT_WORKING = "所得税_勤労学生に当たるか"

READS = (
    R_CLAIMANT_IT, R_TOTAL, R_TOTAL_IT, R_GROSS, R_DOMICILE, R_AGE, R_RESIDENT, R_STUDY, R_DISABLED, R_SPECIAL,
    R_SP_LIVE, R_SP_SENJU, R_COHAB_SPOUSE, R_DIVORCED, R_MARRIED, R_WIDOWED, R_DE_FACTO, R_MISSING,
    R_STUDENT, R_WAGE, R_SALARY, R_RETIRE, R_RETIRE_SEP, R_BUSINESS, R_MISC, R_LABOR,
    R_IT_SPOUSE, R_IT_WIDOW, R_IT_SINGLE, R_IT_WORKING,
    R_DIVIDEND, R_REAL, R_WINDFALL, R_PENSION_MISC, R_PENSION_RECEIPT, R_LISTED_SEP,
)  # fmt: skip

# --- 段 住民税の扶養の割当て が書く入力 ---
W_CLAIMANT = "住民税_扶養親族等の納税義務者"
W_CHAIN = "住民税_連鎖の扶養親族等か"
W_SEP = "住民税_扶養の判定を所得税と別に行うか"
W_SELF = "住民税_本人の判定を所得税と別に行うか"
#: 扶養親族等・配偶者として判定される側の住民税の区分（W_SEP が真の人だけ式が読む）
W_DEP_LISTED = "住民税_別の判定の扶養親族等とされているか"
W_DEP = "住民税_別の判定の扶養親族か"
W_CTRL = "住民税_別の判定の控除対象扶養親族か"
W_TOKU = "住民税_別の判定の特定扶養親族か"
W_OLD = "住民税_別の判定の老人扶養親族か"
W_DK = "住民税_別の判定の同居老親等か"
W_SPEC_REL = "住民税_別の判定の特定親族か"
W_COHAB_SP = "住民税_別の判定の同居特別障害者か"
W_DISABLED = "住民税_別の判定の障害者か"
W_SPECIAL = "住民税_別の判定の特別障害者か"
#: 本人の側の住民税の区分（W_SELF が真の人だけ式が読む）
W_SPOUSE = "住民税_別の判定の同一生計配偶者に当たるか"
W_WIDOW = "住民税_別の判定の寡婦か"
W_SINGLE = "住民税_別の判定のひとり親か"
W_WORKING = "住民税_別の判定の勤労学生か"
DEP_WRITES = (W_DEP_LISTED, W_DEP, W_CTRL, W_TOKU, W_OLD, W_DK, W_SPEC_REL, W_COHAB_SP, W_DISABLED, W_SPECIAL)
SELF_WRITES = (W_SPOUSE, W_WIDOW, W_SINGLE, W_WORKING)
WRITES = (W_CLAIMANT, W_CHAIN, W_SEP, W_SELF, *DEP_WRITES, *SELF_WRITES)

# --- 段 住民税の扶養の連鎖の合計 ---
R_DED = "住民税_扶養控除の1人分の額"
R_SPEC = "住民税_特定親族特別控除の1人分の額"
R_DIS = "住民税_障害者控除の扶養親族の1人分の額"
R_DIFF = "住民税_人的控除差の扶養親族の1人分の額"
R_COUNT = "住民税_非課税の判定で数える扶養親族か"
CHAIN_READS = (W_CLAIMANT, W_CHAIN, R_DED, R_SPEC, R_DIS, R_DIFF, R_COUNT)

C_DED = "住民税_連鎖の扶養親族の扶養控除の額"
C_SPEC = "住民税_連鎖の扶養親族の特定親族特別控除の額"
C_DIS = "住民税_連鎖の扶養親族の障害者控除の額"
C_DIFF = "住民税_連鎖の扶養親族の人的控除差の額"
C_COUNT = "住民税_連鎖の非課税の判定で数える扶養親族の数"
CHAIN_WRITES = (C_DED, C_SPEC, C_DIS, C_DIFF, C_COUNT)

#: 扶養親族・特定親族の記載がある書類（その年分の所得税の書類と、その年度の住民税の書類）。
DEP_SECTIONS = ("dependent_relative", "specific_relative")
TAX_YEAR_DOCS = (
    "final_return",
    "quasi_final_return",
    "employee_dependents_declaration",
    "secondary_salary_dependents_declaration",
    "specific_relative_deduction_declaration",
    "salary_payment_report",
    "public_pension_payment_report",
)
FISCAL_YEAR_DOCS = ("resident_tax_return", "local_tax_order_46_5_application", "salary_payment_report", "public_pension_payment_report")
APPLICATION = "local_tax_order_46_5_application"


def listings(ctx: StageContext, fiscal_year: int) -> dict[str, list[tuple[str, str, str, str]]]:
    """扶養・配偶者の記載：記載された人 → [(記載した人, 書類の種別, 記録の ID, 区分)]。区分は dependent_relative・specific_relative・spouse。"""
    out: dict[str, list[tuple[str, str, str, str]]] = {}
    for rec in ctx.records("filed_document"):
        a = rec["attributes"]
        doc = a["document_type"]
        if not ((doc in TAX_YEAR_DOCS and a.get("tax_year") == ctx.year) or (doc in FISCAL_YEAR_DOCS and a.get("fiscal_year") == fiscal_year)):
            continue
        for e in a.get("entries", ()):
            if e["section"] in DEP_SECTIONS or e["section"] == "spouse":
                out.setdefault(e["person"], []).append((rec["roles"]["filer"], doc, rec["id"], e["section"]))
    return out


def tie_split(d: str, tied: Iterable[str]) -> Split:
    """地令46の5② の所得の合計額が同額で、いずれの納税義務者の扶養親族等とするかの定めがない（一次情報の分かれ目）。"""
    names = sorted(tied)
    return Split(
        id=f"読み:住民税の扶養の所属の同額:{d}",
        means=Means.PRIMARY_SOURCE,
        target={
            "person": d,
            "納税義務者": names,
            "理由": "地方税法施行令第46条の5第2項の前年の総所得金額・退職所得金額・山林所得金額の合計額が同額で、いずれの納税義務者の扶養親族等とするかの定めが docs の一次情報にない",
        },
        candidates=tuple(names),
        splits_conclusion=True,
    )


# --- 地令46の5①（46の3①・46の4① も同じ）：所属を決める書類を、記載した人の区分で分ける（2026-11-12。JM-33） ---
#: 法第317条の2第1項の申告書を提出する義務を有する者（区分 RETURN_FILER）：その申告書（住民税の申告書。前年分の所得税の確定申告書は第317条の3 で住民税の
#: 申告書を提出したものとみなし、記載は住民税の申告書の記載とみなす）
RETURN_FILER = "申告義務者"
RETURN_DOCS = frozenset({"resident_tax_return", "final_return", "quasi_final_return"})
#: 給与所得等以外の所得を有しなかった者（区分 REPORT_PERSON。地令46の3① の定義）：給与支払報告書・公的年金等支払報告書（申請書を出せば申請書）
REPORT_PERSON = "給与所得等以外の所得を有しなかった者"
REPORT_DOCS = frozenset({"salary_payment_report", "public_pension_payment_report"})
#: 給与支払報告書の記録がないときに報告書の記載とみなす書類：給与所得者の扶養親族等申告書（第317条の3の2）は給与支払者を経由して出し、
#: 給与支払報告書の扶養の記載のもとになる。中間表現では所得税の扶養控除等申告書等の記載で書く（法令の読み：basis.REPORT_SOURCE_RULE）
REPORT_SOURCE_DOCS = frozenset(
    {"employee_dependents_declaration", "secondary_salary_dependents_declaration", "specific_relative_deduction_declaration"}
)
CATEGORIES = (RETURN_FILER, REPORT_PERSON)
#: 区分を決める記録（1月1日の給与・年金の支払者：jan1_payer_status。年度ごと）
JAN1_KIND = "jan1_payer_status"


def person_category(ctx: StageContext, L: _Local, x: str, fiscal: int) -> tuple[frozenset[str], tuple[str, ...]]:
    """地令46の3① の区分：(採りうる区分, 使った記録)。

    給与所得等以外の所得を有しなかった者 ＝ 1月1日現在に給与支払報告書・公的年金等支払報告書を提出する義務がある者から給与（公的年金等）の支払を受けていて、
    前年に給与所得以外（公的年金等に係る所得以外）の所得を有しなかった者（第317条の2第2項の指定を受けた者を除く：指定の語彙はない）。
    前年の所得が給与所得だけ・公的年金等に係る所得だけでなければ申告義務者。1月1日の支払者の記録（jan1_payer_status）がなければ両方の区分が候補。
    分離課税に係る退職所得は、他の所得と区分して課税する所得なので前年の所得に数えない（第328条。法令の読み）。"""
    other = any(L.num(v, x) for v in (R_DIVIDEND, R_REAL, R_BUSINESS, R_WINDFALL, R_LISTED_SEP))
    other = other or L.num(R_RETIRE, x) - L.num(R_RETIRE_SEP, x) != 0 or L.num(R_MISC, x) - L.num(R_PENSION_MISC, x) != 0
    wage = L.num(R_WAGE, x) > 0
    pension = L.num(R_PENSION_RECEIPT, x) > 0
    salary_only = wage and not pension and not other
    pension_only = pension and not wage and not other
    if not (salary_only or pension_only):
        return frozenset({RETURN_FILER}), ()
    recs = [r for r in ctx.records(JAN1_KIND) if r["roles"].get("person") == x and r["when"].get("fiscal_year") == fiscal]
    if not recs:
        return frozenset(CATEGORIES), ()
    a = recs[0]["attributes"]
    paid = bool(a["salary_payer_on_jan1"]) if salary_only else bool(a["pension_payer_on_jan1"])
    reporting = a.get("payer_must_file_report") is not False
    return frozenset({REPORT_PERSON if paid and reporting else RETURN_FILER}), tuple(r["id"] for r in recs)


def applicants(ctx: StageContext, fiscal_year: int) -> frozenset[str]:
    """その年度の地令46の5 の申請書（第1項ただし書）を出した人（記載のない申請書を含む：記載がなければ扶養親族等とする人はいない）。"""
    return frozenset(
        r["roles"]["filer"]
        for r in ctx.records("filed_document")
        if r["attributes"]["document_type"] == APPLICATION and r["attributes"].get("fiscal_year") == fiscal_year
    )


def document_rows(rows: Iterable[tuple[str, str, str, str]], category_of: Any, applied: frozenset[str] = frozenset()) -> list[tuple[str, str, str, str]]:
    """記載 (記載した人, 書類の種別, 記録の ID, 区分) のうち、記載した人の区分で地令46の5① の書類に当たるもの。applied は申請書を出した人。"""
    rows = list(rows)
    reports = {f for f, doc, _, _ in rows if doc in REPORT_DOCS}
    apps = set(applied) | {f for f, doc, _, _ in rows if doc == APPLICATION}
    out = []
    for f, doc, rid, sec in rows:
        if category_of(f) == RETURN_FILER:
            ok = doc in RETURN_DOCS
        elif f in apps:
            ok = doc == APPLICATION  # 第1項ただし書：申請書を出したときは申請書の記載による
        else:
            ok = doc in REPORT_DOCS or (f not in reports and doc in REPORT_SOURCE_DOCS)
        if ok:
            out.append((f, doc, rid, sec))
    return out


def category_split(d: str, filers: Iterable[str], fiscal: int) -> Split:
    """記載した人の区分（地令46の3①）が決まらず、所属が区分で分かれる（決める手段：事実）。"""
    names = sorted(filers)
    return Split(
        id=f"事実:地令46の5の書類の区分:{d}:{fiscal}",
        means=Means.FACT,
        target={
            "person": d,
            "記載した人": names,
            "入力": "記載した人の jan1_payer_status（1月1日現在の給与・公的年金等の支払者と、支払報告書を出す義務）。申告義務者は申告書、"
            "給与所得等以外の所得を有しなかった者は給与支払報告書・公的年金等支払報告書（申請書）の記載で所属を決める（地令46の5①）",
        },
        candidates=CATEGORIES,
        splits_conclusion=True,
    )


@dataclass
class _Local:
    """1回の段の計算で使う値の窓口。"""

    ctx: StageContext
    fam: Family
    used: dict[str, list[StageValue]] = field(default_factory=dict)

    def v(self, var: str, p: str) -> StageValue:
        sv = self.ctx.value(var, p)
        self.used.setdefault(p, []).append(sv)
        return sv

    def num(self, var: str, p: str) -> int:
        return int(self.v(var, p).value)

    def flag(self, var: str, p: str) -> bool:
        return bool(self.v(var, p).value)

    def uses_of(self, *people: str | None) -> tuple[StageValue, ...]:
        """その人たちについて読んだ値（段の出力の由来。状態・対象外・根拠が伝わる）。"""
        seen: list[StageValue] = []
        for p in dict.fromkeys(x for x in people if x is not None):
            seen += self.used.get(p, [])
        return tuple(seen)


def _limits(ctx: StageContext) -> DependentLimits:
    p = ctx.parameters.所得税
    c, n = p.控除対象扶養親族, p.控除対象扶養親族.非居住者
    return DependentLimits(
        resident_age_min=int(c.居住者の年齢の下限),
        nr_age_min=int(n.年齢の下限),
        nr_plain_age_max=int(n.区分の要件のない年齢の上限),
        nr_plain_high_min=int(n.区分の要件のない高い年齢の下限),
        nr_remit_min=int(n.生活費等の支払の額の下限),
        specific_low=int(p.特定扶養親族.年齢の下限),
        specific_high=int(p.特定扶養親族.年齢の上限),
        elderly_min=int(p.老人扶養親族.年齢の下限),
        spec_rel_low=int(p.特定親族.年齢の下限),
        spec_rel_high=int(p.特定親族.年齢の上限),
        spec_rel_cap=int(p.特定親族.合計所得金額の上限),
    )


def run(ctx: StageContext) -> StageOutput:
    """地令46の3〜46の5：住民税の扶養親族等・同一生計配偶者の所属を決め、所得税と違う人の住民税の区分を書く。"""
    out = StageOutput()
    fam = build_family(ctx)
    L = _Local(ctx, fam)
    w = ctx.window("住民税", "年度")
    fiscal = w.time.value if w is not None else ctx.year + 1
    persons = list(ctx.persons)
    p = ctx.parameters.所得税
    cap_dep = int(p.扶養親族.合計所得金額の上限)
    cap_spec = int(p.特定親族.合計所得金額の上限)
    cap_spouse = int(p.同一生計配偶者.合計所得金額の上限)
    cap_sp_special = int(ctx.parameters.住民税.所得控除.配偶者特別控除.配偶者の合計所得金額の上限)
    cap_self_special = int(ctx.parameters.住民税.所得控除.配偶者特別控除.本人の区分.第3号の上限)
    lim = _limits(ctx)
    total = {x: L.num(R_TOTAL, x) for x in persons}
    total_it = {x: L.num(R_TOTAL_IT, x) for x in persons}
    taxpayer = {x: has_domicile(L.v(R_DOMICILE, x).value) for x in persons}
    it_claimant = {x: (L.v(R_CLAIMANT_IT, x).value or None) for x in persons}
    # 判定の時（前年の12月31日、死亡していれば死亡の時）の年齢
    local_t = {x: judgment_date(ctx.year, fam.deaths[x]) for x in persons}
    ages = {x: age_on(ctx.birth_on(x), judgment_day(local_t[x], fam.deaths[x])) for x in persons}
    # 配偶者（所得税と同じ法律婚。所令220① の選び方も同じ：地令48の7⑤）
    sp_ids: dict[str, set[str]] = {a: set() for a in persons}
    sp_states: dict[str, set[State]] = {a: set() for a in persons}
    chosen = choose_spouses(fam, ctx.decision, sp_states, sp_ids)
    spouse_of = {a: (b if b is not None and chosen.get(b) == a else None) for a, b in chosen.items()}
    lists = listings(ctx, fiscal)
    # --- 住民税の所属（共有の純粋関数：Rule.LOCAL_TAX） ---
    allocs: dict[str, Alloc] = {}
    ties: dict[str, Split] = {}
    doc_cats: dict[str, tuple[frozenset[str], tuple[str, ...]]] = {}  # 記載した人 → 地令46の3① の区分の候補と使った記録
    applied = applicants(ctx, fiscal)
    for d in persons:
        eligible: dict[str, Candidacy] = {}
        for c in fam.neighbours[d]:
            ok, ids, states = pair_candidacy(fam, c, d)
            if ok and taxpayer[c]:
                ok = total[d] <= cap_dep or (lim.spec_rel_low <= ages[d] < lim.spec_rel_high and total[d] <= cap_spec)
            else:
                ok = False
            eligible[c] = Candidacy(ok, (), frozenset(ids), frozenset(states))
        a = spouse_of.get(d)
        spouse_ok = False
        if a is not None and taxpayer[a] and L.flag(R_SP_LIVE, a) and not L.flag(R_SP_SENJU, a):
            spouse_ok = total[d] <= cap_spouse or (total[d] <= cap_sp_special and total[a] <= cap_self_special)
        rows = lists.get(d, [])
        others: dict[str, set[str]] = {}
        for f, _, rid, _ in rows:
            others.setdefault(f, set()).add(rid)
        # 地令46の5①：記載した人の区分（申告義務者・給与所得等以外の所得を有しなかった者）ごとの書類だけを数える。区分が決まらない人は両方で評価する
        for f, *_ in rows:
            if f not in doc_cats and f in persons:
                doc_cats[f] = person_category(ctx, L, f, fiscal)
        unknown = sorted(f for f in {r[0] for r in rows} if len(doc_cats.get(f, (frozenset({RETURN_FILER}), ()))[0]) > 1)
        if len(unknown) <= 3:
            scenarios = [dict(zip(unknown, combo)) for combo in itertools.product(CATEGORIES, repeat=len(unknown))]
        else:
            scenarios = [dict.fromkeys(unknown, c) for c in CATEGORIES]
        results: list[tuple[Alloc, Split | None]] = []
        for sc in scenarios:
            kept = document_rows(rows, lambda f, sc=sc: sc.get(f) or next(iter(doc_cats.get(f, (frozenset({RETURN_FILER}), ()))[0])), applied)
            dep_rows = [r for r in kept if r[3] in DEP_SECTIONS]
            tie: list[Split] = []

            def pick(people: list[str], al: Alloc, d: str = d, tie: list[Split] = tie) -> str | None:
                amounts = {x: L.num(R_GROSS, x) for x in people}
                tied = largest(amounts)
                if len(tied) >= 2:
                    tie.append(tie_split(d, tied))
                    al.missing.append(tie[-1])
                return tied[0] if tied else None

            al_ = allocate_one(
                eligible,
                a,
                spouse_ok,
                (),
                [rid for f, _, rid, sec in kept if f == a and sec == "spouse"],
                [DepListing(f, None, rid) for f, _, rid, _ in dep_rows],
                others,
                pick,
                Rule.LOCAL_TAX,
            )
            results.append((al_, tie[-1] if tie else None))
        allocs[d], tied_split = results[0]
        if tied_split is not None:
            ties[d] = tied_split
        allocs[d].ids.update(i for f in {r[0] for r in rows} for i in doc_cats.get(f, ((), ()))[1])
        if len({r.claimant for r, _ in results}) > 1:
            allocs[d].missing.append(category_split(d, unknown, fiscal))
    claimant = {d: allocs[d].claimant for d in persons}
    claimants = {c for c in claimant.values() if c is not None}
    chain = {d for d in persons if claimant[d] is not None and d in claimants}
    # --- 住民税扶養所属のグループ ---
    deps_of: dict[str, list[str]] = {}
    for d in persons:
        if claimant[d] is not None and d not in chain:
            deps_of.setdefault(claimant[d], []).append(d)  # type: ignore[arg-type]
    grouped = {d for ds in deps_of.values() for d in ds}
    instances = []
    for x in persons:
        if x in grouped:
            continue
        roles: dict[str, tuple[str, ...]] = {"納税義務者一覧": (x,)}
        deps = sorted(deps_of.get(x, ()))
        if deps:
            roles["住民税の扶養親族等一覧"] = tuple(deps)
        ids = sorted({i for d in deps for i in allocs[d].ids})
        sts = frozenset({s for d in deps for s in allocs[d].states})
        instances.append(GroupInstance(f"住民税扶養所属:{x}", roles, tuple(ids), sts, uses=tuple(v for d in deps for v in L.used.get(d, ()))))
    out.group("住民税扶養所属一覧", instances)
    # --- 所得税と違う人 ---
    nr = nonresident_income_splits(fam)
    sep = {d: claimant[d] != it_claimant[d] or total[d] != total_it[d] or d in ties for d in persons}
    for a in persons:  # 配偶者として判定される人：相手の住民税の同一生計配偶者が所得税と違いうる
        b = spouse_of.get(a)
        if b is not None and (total[b] != total_it[b] or total[a] != total_it[a] or not taxpayer[a]):
            sep[b] = True
    self_sep = {a: total[a] != total_it[a] or not taxpayer[a] for a in persons}
    for d in persons:
        if sep[d]:
            for c in (claimant[d], it_claimant[d], spouse_of.get(d)):
                if c is not None:
                    self_sep[c] = True
    # --- 判定される側の住民税の区分 ---
    cats: dict[str, Any] = {}
    facts: dict[str, RelationFacts | None] = {}
    special_at: dict[str, bool] = {}
    disabled_at: dict[str, bool] = {}
    at_missing: dict[str, tuple[Split, ...]] = {}
    for d in persons:
        own = judgment_date(ctx.year, fam.cut(d))
        if local_t[d] == own:
            resident, study = L.flag(R_RESIDENT, d), L.flag(R_STUDY, d)
            disabled_at[d], special_at[d] = L.flag(R_DISABLED, d), L.flag(R_SPECIAL, d)
            at_missing[d] = ()
        else:  # 前年の中途に出国した人：判定の時（12月31日）の現況（dependents/person_at.py）
            at = person_at(ctx.ir, fam.idx, d, ctx.birth_on(d), local_t[d], judgment_day(local_t[d], fam.deaths[d]), limits_from(ctx.parameters))
            resident, study = bool(at.resident), at.study_abroad
            disabled_at[d], special_at[d] = bool(at.disabled), bool(at.special)
            at_missing[d] = at.missing
        c = claimant[d]
        f = relation_facts(fam, c, d, spouse_of.get(c), on=local_t[d]) if c is not None else None
        if f is not None and not resident:  # 判定の時に住所が国外の人は同居を常況としていない（法令の読み：personal_deductions PD-05 と同じ）
            f = dataclasses.replace(f, cohab=False, cohab_etc=False)
        facts[d] = f
        cats[d] = categorize(
            allocated=c is not None,
            dependent_income_ok=total[d] <= cap_dep,
            income=total[d],
            age=ages[d],
            resident=resident,
            study_abroad=study,
            disabled=disabled_at[d],
            special=special_at[d],
            facts=f,
            lim=lim,
        )
    # 住民税の同一生計配偶者（本人から見た配偶者について）
    local_spouse = {
        a: (
            (b := spouse_of.get(a)) is not None
            and taxpayer[a]
            and L.flag(R_SP_LIVE, a)
            and not L.flag(R_SP_SENJU, a)
            and total[b] <= cap_spouse
            and claimant[b] is None
        )
        for a in persons
    }
    # --- 書く ---
    for d in persons:
        c = claimant[d]
        al = allocs[d]
        ids = tuple(sorted(al.ids))
        states = frozenset(al.states)
        uses = L.uses_of(d, c, spouse_of.get(d), *(x for x in fam.neighbours[d]))
        miss = tuple(al.missing) + at_missing[d] + ((nr[d][0],) if d in nr else ())
        out.set(W_CLAIMANT, d, c or "", ids, states, uses=uses, missing=miss)
        out.set(W_CHAIN, d, d in chain, ids, states, uses=uses, missing=miss)
        out.set(W_SEP, d, sep[d], ids, states, uses=uses)
        k = cats[d]
        b = spouse_of.get(d)
        as_spouse = b is not None and local_spouse[b] and L.flag(R_COHAB_SPOUSE, d)
        values = {
            W_DEP_LISTED: c is not None,
            W_DEP: k.dependent,
            W_CTRL: k.control,
            W_TOKU: k.specific,
            W_OLD: k.elderly,
            W_DK: k.cohab_elderly,
            W_SPEC_REL: k.specified_relative,
            W_COHAB_SP: special_at[d] and (k.cohab_special or as_spouse),
            W_DISABLED: disabled_at[d],
            W_SPECIAL: special_at[d],
        }
        f = facts[d]
        f_ids = tuple(sorted(set(ids) | set(f.cohab_ids if f else ()) | set(f.doc_ids if f else ())))
        for var, val in values.items():
            out.set(var, d, bool(val), f_ids, states | (f.cohab_states if f else frozenset()), uses=uses, missing=miss if sep[d] else ())
    for a in persons:
        mine = [d for d in persons if claimant[d] == a]
        dep_any = any(cats[d].dependent for d in mine)
        divorced, married, widowed = L.flag(R_DIVORCED, a), L.flag(R_MARRIED, a), L.flag(R_WIDOWED, a)
        de_facto, missing_sp = L.flag(R_DE_FACTO, a), L.flag(R_MISSING, a)
        child_cap = int(p.ひとり親.子の総所得金額等の上限)
        has_child = any(facts[d] is not None and facts[d].child and L.num(R_GROSS, d) <= child_cap for d in mine)  # type: ignore[union-attr]
        single = (
            taxpayer[a]
            and (not married or missing_sp)
            and total[a] <= int(p.ひとり親.合計所得金額の上限)
            and not de_facto
            and a not in grouped
            and has_child
        )
        widow = (
            taxpayer[a]
            and ((divorced and not married and dep_any) or widowed)
            and total[a] <= int(p.寡婦.合計所得金額の上限)
            and not de_facto
            and not single
        )
        labor = L.flag(R_LABOR, a)
        biz = L.num(R_BUSINESS, a) + L.num(R_MISC, a)
        labor_biz = biz if labor else 0
        retire = L.num(R_RETIRE, a) - L.num(R_RETIRE_SEP, a)
        earned = L.num(R_SALARY, a) + retire + labor_biz
        has_earned = L.num(R_WAGE, a) > 0 or retire != 0 or labor_biz != 0
        working = (
            L.flag(R_STUDENT, a)
            and has_earned
            and total[a] <= int(p.勤労学生.合計所得金額の上限)
            and total[a] - earned <= int(p.勤労学生.給与所得等以外の所得の上限)
        )
        ids = tuple(sorted({i for d in mine for i in allocs[d].ids} | sp_ids[a]))
        states = frozenset({s for d in mine for s in allocs[d].states} | sp_states[a])
        uses = L.uses_of(a, spouse_of.get(a), *mine)
        miss = tuple(m for d in mine for m in allocs[d].missing) + tuple(nr[d][0] for d in nr if a in nr[d][1])
        # 材料が所得税と同じ区分は所得税の判定をそのまま書く（住民税の式で組み直した判定と所得税の判定の食い違いを、違いのない場合に持ち込まない）
        b = spouse_of.get(a)
        it_mine = [d for d in persons if it_claimant[d] == a]
        deps_changed = set(mine) != set(it_mine) or any(sep[d] for d in {*mine, *it_mine})
        income_changed = total[a] != total_it[a] or not taxpayer[a]
        changed = {
            W_SPOUSE: (b is not None and (total[b] != total_it[b] or claimant[b] != it_claimant[b])) or not taxpayer[a],
            W_WIDOW: income_changed or deps_changed,
            W_SINGLE: income_changed or deps_changed,
            W_WORKING: income_changed or L.num(R_RETIRE_SEP, a) > 0,
        }
        local = {W_SPOUSE: local_spouse[a], W_WIDOW: widow, W_SINGLE: single, W_WORKING: working}
        it = {W_SPOUSE: R_IT_SPOUSE, W_WIDOW: R_IT_WIDOW, W_SINGLE: R_IT_SINGLE, W_WORKING: R_IT_WORKING}
        out.set(W_SELF, a, self_sep[a], ids, states, uses=uses)
        for var in SELF_WRITES:
            val = local[var] if changed[var] else L.flag(it[var], a)
            out.set(var, a, bool(val), ids, states, uses=L.uses_of(a, b, *mine, *it_mine), missing=miss if self_sep[a] and changed[var] else ())
    return out


def run_chain(ctx: StageContext) -> StageOutput:
    """扶養の連鎖の人（住民税の扶養親族等で、自分も納税義務者）の1人分の額を、その人の納税義務者に集める。"""
    out = StageOutput()
    sums: dict[str, dict[str, int]] = {p: {k: 0 for k in CHAIN_WRITES} for p in ctx.persons}
    uses: dict[str, list[StageValue]] = {p: [] for p in ctx.persons}
    for d in ctx.persons:
        chain = ctx.value(W_CHAIN, d)
        c = ctx.value(W_CLAIMANT, d)
        if not chain.value or not c.value or c.value not in sums:
            continue
        uses[c.value] += [chain, c]
        for src, dst in ((R_DED, C_DED), (R_SPEC, C_SPEC), (R_DIS, C_DIS), (R_DIFF, C_DIFF)):
            v = ctx.value(src, d)
            sums[c.value][dst] += int(v.value)
            uses[c.value].append(v)
        v = ctx.value(R_COUNT, d)
        sums[c.value][C_COUNT] += 1 if v.value else 0
        uses[c.value].append(v)
    for p in ctx.persons:
        for var in CHAIN_WRITES:
            out.set(var, p, sums[p][var], uses=uses[p])
    return out


__all__ = ["CHAIN_READS", "CHAIN_WRITES", "READS", "STAGE", "STAGE_CHAIN", "WRITES", "listings", "run", "run_chain", "tie_split"]
