"""規則モジュール personal_deductions：扶養の割当て（誰の扶養親族等か。段階評価の段の関数。D23 K1・SCOPE §6-3）。

段（registry.StageSpec。順序は読む変数の依存で決まる）：
1. 所得金額調整控除の対象の親族等：第1段の値（判定用の合計所得金額・年齢・特別障害者か）と親族・生計の判断から、「年齢23歳未満の扶養親族を有するか・特別障害者である
   同一生計配偶者又は扶養親族を有するか」を人ごとに決める（措法41の3の11①。同じ子を夫婦の双方が有する：措通41の3の11−1）。扶養所属のグループを使わない。
2. 扶養の割当て：第2段の値（合計所得金額・年齢・総所得金額ほか）と提出した書類の記載から、所令218〜220 の順で重複を解消し、扶養所属・法律婚のグループと
   申告者との関係の入力を書く（所令219②一：既に記載している人、二：所得の合計額が最も大きい人。同額なら「選択.扶養の所属」の未入力として候補で評価する）。
3. 扶養の連鎖の合計：扶養親族等とされた人が別の人の申告者でもあるとき（連鎖）、グループで1つの所属にしか入れない人の分を、申告者の入力に足す。

連鎖の表し方：連鎖の人（他の人の扶養親族等で、自分も申告者）は自分のインスタンスの申告者の役割に置き、扶養親族等の役割の代わりに入力 `所得税_連鎖の扶養親族等か` が真になる。
連鎖の人の分の控除の額は、段3が申告者の入力（連鎖の…の額）に集める（misc H5 の案A に当たる。根拠：docs/hypotheses/20261109_impl-prep_misc-hypotheses.md H3・H4・H5）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from ...candidates import Candidate
from ...dependents.allocation import (
    Alloc as _Alloc,
    Candidacy,
    DepListing,
    Rule,
    allocate_one,
    choose_spouses,
    largest,
    pair_candidacy,
    relation_facts,
    rule_220_3 as _rule_220_3,
)
from ...dependents.family import (  # noqa: F401  名前はこのモジュールのほかのファイル・テストも使う（2026-11-12 に共有の場所へ移した）
    C_ATTR,
    C_SPOUSE,
    DEP_DOCUMENTS,
    DEP_SECTIONS,
    J_ADDRESS,
    J_DOUKYO,
    J_SEIKEI,
    K_DOMESTIC,
    K_EST,
    REMITTANCE_DOCUMENTS,
    REMITTANCE_SPECIAL,
    RETURN_DOCUMENTS,
    SPOUSE_DOCUMENTS,
    WITHHOLDING_DECLARATIONS,
    Family,
    Listing,
    age_of as _age,
    build_family,
    dies_in_year,
    employers_of,
    estimate_key,
    is_senju,
    kin_for,
    known_non_resident as _known_non_resident,
    listings,
    nonresident_income_splits,
    pair_key,
    pair_match as _pair_match,
    person_departures,
    potential_claimants as _potential_claimants,
    relative_value,
    withdrawn as _withdrawn,
)
from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...dependents.person_at import PersonAt, judgment_day, limits_from, person_at
from ...registry import DecisionSlot, DecisionSpec, GroupInstance, StageContext, StageOutput, StageValue, YearContext, overlaps_year
from ...result import Means, OutOfScopeCategory, OutOfScopeReason, Split, State
from .cohab_fx import C_FX, HOME_RULE, J_HOME, fx_provenance, home_override
from .ir_facts import IrIndex, disability_bases, judgment_date
from .filing import NO_PERSON
from .kinship import other_spouse

# ---------------------------------------------------------------------------
# 名前（判断・選択の種類と書類の区分は dependents/family.py）
# ---------------------------------------------------------------------------

STAGE_HAS = "所得金額調整控除の対象の親族等"
STAGE_ALLOC = "扶養の割当て"
STAGE_CHAIN = "扶養の連鎖の合計"

V_HAS = "所得税_所得金額調整控除の対象の親族等を有するか"
V_KIN = "所得税_申告者の親族か"
V_CHILD = "所得税_申告者の子か"
V_LIVE = "所得税_申告者と生計を一にするか"
V_COHAB = "所得税_申告者と同居を常況としているか"
V_COHAB_ETC = "所得税_申告者等と同居を常況としているか"
V_COHAB_SPOUSE = "所得税_配偶者等と同居を常況としているか"
V_ASCENDANT = "所得税_申告者の直系尊属か"
V_SENJU = "所得税_申告者等の事業専従者か"
V_DOC = "所得税_国外居住親族の書類の要件を満たすか"
V_REMIT = "所得税_申告者から受けた生活費等の支払の額"
V_DOC_STUDY = "所得税_国外居住親族の留学の区分の書類の要件を満たすか"
V_DOC_38 = "所得税_国外居住親族の38万円以上の区分の書類の要件を満たすか"
V_SP_LIVE = "所得税_配偶者と生計を一にするか"
V_SP_SENJU = "所得税_配偶者が青色事業専従者等か"
V_SP_EXCL = "所得税_配偶者特別控除の適用除外に当たるか"
V_SPEC_EXCL = "所得税_特定親族特別控除の適用除外に当たるか"
V_CHAIN = "所得税_連鎖の扶養親族等か"
V_CLAIMANT = "所得税_扶養親族等の申告者"
V_CH_DED = "所得税_連鎖の扶養親族の扶養控除の額"
V_CH_SPEC = "所得税_連鎖の扶養親族の特定親族特別控除の額"
V_CH_DIS = "所得税_連鎖の扶養親族の障害者控除の額"
V_CH_ANY = "所得税_連鎖の扶養親族がいるか"
V_CH_CHILD = "所得税_連鎖のひとり親の子がいるか"
V_EST_USE = "所得税_死亡した申告者のための見積りを使うか"
V_OUT = "所得税_法律婚のグループ外の配偶者がいるか"
V_OUT_INC = "所得税_グループ外の配偶者の合計所得金額"
V_OUT_AGE = "所得税_グループ外の配偶者の年齢"
V_OUT_DEP = "所得税_グループ外の配偶者が他の居住者の扶養親族等とされているか"
V_OUT_DIS = "所得税_グループ外の配偶者の障害の区分"
V_EST_AMT = "所得税_死亡した申告者のための合計所得金額の見積額"
#: 申告書の欄が使う値（filing.py。2026-11-12：forms の行の割当て・第一表 G109）
V_SPOUSE = "所得税_法律婚の相手"
V_CH_SPEC_N = "所得税_連鎖の特定親族特別控除の人数"

#: 判定する人の判定の時の現況（PD-05。2026-11-12：dependents/person_at.py）。
V_AT_USE = "所得税_判定する人の判定の時の値を使うか"
V_AT_AGE = "所得税_判定する人の判定の時の年齢"
V_AT_RESIDENT = "所得税_判定する人の判定の時に居住者か"
V_AT_STUDY = "所得税_判定する人の判定の時に留学により国内に住所及び居所を有しなくなった者か"
V_AT_DISABLED = "所得税_判定する人の判定の時に障害者に当たるか"
V_AT_SPECIAL = "所得税_判定する人の判定の時に特別障害者に当たるか"

ALLOC_WRITES: tuple[str, ...] = (
    V_KIN, V_CHILD, V_LIVE, V_COHAB, V_COHAB_ETC, V_COHAB_SPOUSE, V_ASCENDANT, V_SENJU, V_DOC, V_DOC_STUDY, V_DOC_38, V_REMIT,
    V_SP_LIVE, V_SP_SENJU, V_SP_EXCL, V_SPEC_EXCL, V_CHAIN, V_CLAIMANT, V_EST_USE, V_EST_AMT,
    V_OUT, V_OUT_INC, V_OUT_AGE, V_OUT_DEP, V_OUT_DIS,
    V_AT_USE, V_AT_AGE, V_AT_RESIDENT, V_AT_STUDY, V_AT_DISABLED, V_AT_SPECIAL, V_SPOUSE,
)  # fmt: skip

R_TOTAL = "所得税_合計所得金額"
R_JUDGE = "所得税_所得金額調整控除の判定に使う合計所得金額"
R_AGE = "所得税_年齢"
R_SPECIAL = "所得税_特別障害者に当たるか"
R_DISABLED = "所得税_障害者に当たるか"
R_WAGE = "所得税_給与等の収入金額"
R_RESIDENT = "所得税_居住者か"
R_GROSS = "所得税_総所得金額"
R_RETIRE = "所得税_退職所得金額"
R_DIV = "所得税_申告分離課税の上場株式等に係る配当所得等の金額"
R_GAIN = "所得税_申告分離課税の上場株式等に係る譲渡所得等の金額"


def _reason(text: str, ids: Iterable[str] = ()) -> OutOfScopeReason:
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, text, tuple(sorted(set(ids))))


# 書類の記載（Listing・listings）と年分の状況（Family・build_family）は dependents/family.py に移した（2026-11-12）。


# ---------------------------------------------------------------------------
# 判断・選択の1か所の宣言（D21 R6・D22 S20）
# ---------------------------------------------------------------------------

_BOOL = (Candidate(True, "true"), Candidate(False, "false"))


def seikei_slots(ctx: YearContext) -> Iterator[DecisionSlot]:
    """親族（里子などを含む）の組ごとの 判断.生計を一にする（判定の時の現況。Family.slotted の組）。"""
    fam = build_family(ctx)
    for (a, b) in sorted(fam.slotted):
        on = fam.t(a, b)
        yield DecisionSlot(
            key=pair_key(a, b),
            target={"person": a, "other_person": b, "on": on.isoformat(), "purpose": "扶養親族等・同一生計配偶者の要件（所法2①三十三・三十四）"},
            matches=_pair_match(a, b, on),
            persons=(a, b),
        )


def doukyo_slots(ctx: YearContext) -> Iterator[DecisionSlot]:
    """判断.同居を常況：年齢の下限以上の親族・特別障害者になりうる親族だけ（同居老親等〔措法41の16〕・同居特別障害者〔所法79③〕）。"""
    fam = build_family(ctx)
    age_min = int(ctx.parameters.所得税.老人扶養親族.年齢の下限)
    for (a, b) in sorted(fam.slotted):
        on = fam.t(a, b)
        needs = False
        for d, other in ((a, b), (b, a)):
            if disability_bases(fam.idx, d, on) or _age(fam, d, on) >= age_min:
                needs = True
                break
        if not needs:
            continue
        yield DecisionSlot(
            key=pair_key(a, b),
            target={"person": a, "other_person": b, "on": on.isoformat(), "purpose": "同居老親等・同居特別障害者の同居を常況としているか"},
            matches=_pair_match(a, b, on),
            persons=(a, b),
            candidates=_BOOL,
        )


def tie_key(person: str) -> str:
    return f"所属:{person}"


def attribution_slots(ctx: YearContext) -> Iterator[DecisionSlot]:
    """選択.扶養の所属：所令219② 第2号でも決まらないとき（同額）に、どの居住者の扶養親族等とするかの1か所。

    扶養親族等に当たりうる人が2人以上いて、書類の記載で一意に決まらない人にだけ置く。申告者になりうる人からは、中間表現だけで当たらないと
    決まる人（生計を一にしない判断、d を事業専従者とする事業主、年を通じて国外の住所と判断された人）を除く（2026-11-11 の反証のレビュー）。
    所得の合計額が同額になるか（所令219②二）は段の値で決まり、宣言の時（段の前）には分からない。2026-11-11 から「読んだときだけ開く」
    1か所（DecisionSlot.lazy）にした：段は同額のときだけ値を読むので、所得で決まる場合には分かれ目が開かず、直積にも結果の分かれ目にも出ない
    （反証のレビューの指摘。packages/core/README.md §5）。
    """
    fam = build_family(ctx)
    for d in ctx.persons:
        if not fam.neighbours[d]:
            continue
        potential = _potential_claimants(fam, d)
        if len(potential) < 2:
            continue
        dep_listed = {l.filer for l in fam.listing if l.person == d and l.section in DEP_SECTIONS and l.filer in potential}
        if len(dep_listed) == 1:
            continue
        cands = sorted(dep_listed) if dep_listed else sorted(potential)
        yield DecisionSlot(
            key=tie_key(d),
            target={"person": d, "tax_year": ctx.year, "説明": "所令219② 第2号の所得の合計額が同じで、いずれの居住者の扶養親族等とするかが決まらない", "候補": cands},
            matches=lambda rec, p=d: rec["subject"]["person"] == p,
            candidates=tuple(Candidate(c, c) for c in cands),
            persons=(d, *cands),
            lazy=True,
        )


#: 判定する人の判定の時の現況の根拠（PD-05。2026-11-12 に「出国する人を出国しない居住者の扶養親族等・配偶者とした」ときの対象外をやめた）。
JUDGE_TIME_RULE = BasisEntry(
    type=BasisType.RULE,
    name="扶養親族等・配偶者に当たるかは、判定する人（申告者・配偶者）の判定の時の現況による（判定される人の出国は判定の時を変えない）",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第85条第3項（その年12月31日。その居住者がその年の中途で死亡し又は出国をする場合はその死亡又は出国の時。判定される人が既に死亡していれば死亡の時）。"
        "判定の時に住所が国外の人は同居を常況としていないと読む（法令の読み）"
    ),
    references=("docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#1.1", "docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.3"),
    flags=(ReadingFlag.LEGAL_READING,),
)


def domestic_source_slots(ctx: YearContext) -> Iterator[DecisionSlot]:
    """判断.国内源泉所得の内訳（2026-11-12 に語彙を足した。PD-06）：その年分の記録があるときだけ1か所を置く（金額は候補を作れない。食い違えば違う値が候補）。

    2026-11-12：ほかの年分の記録しかない人にも1か所を置いていたので、その年分では一致する判断がなく、候補を作れずに評価が止まっていた
    （例 08：2026年分の判断で 2025年分を評価した）。1か所の matches と同じく年分と重なる記録だけを見る。
    """
    seen: set[str] = set()
    for j in ctx.judgments(K_DOMESTIC):
        pid = j["subject"]["person"]
        if pid in seen or pid not in ctx.persons or not overlaps_year(j.get("when"), ctx.year):
            continue
        seen.add(pid)
        yield DecisionSlot(
            key=pid,
            target={"person": pid, "tax_year": ctx.year, "説明": "非居住者の期間の国内源泉所得以外の所得の金額（0 なら合計所得金額の読みで値が分かれない）"},
            matches=lambda rec, pid=pid: rec["subject"]["person"] == pid,
            persons=(pid,),
        )


class _Missing:
    """StageOutput に、人・変数ごとの読みの分かれ目（missing）を足して渡す包み。"""

    def __init__(self, out: StageOutput, by: Mapping[tuple[str, str | None], tuple[Split, ...]]) -> None:
        self.out = out
        self.by = by

    def set(self, variable: str, person: str, value: Any, record_ids: Iterable[str] = (), states: Iterable[State] = (), **kw: Any) -> None:
        extra = self.by.get((person, None), ()) + self.by.get((person, variable), ())
        self.out.set(variable, person, value, record_ids, states, **{**kw, "missing": tuple(kw.get("missing", ())) + extra})

    def exclude(self, *a: Any, **kw: Any) -> None:
        self.out.exclude(*a, **kw)


def spouse220_slots(ctx: YearContext) -> Iterator[DecisionSlot]:
    """選択.配偶者の記載（所令220①）：年の中途で死亡した配偶者と再婚した配偶者の一人。書類の記載で決まらない人に置く。"""
    fam = build_family(ctx)
    for a in ctx.persons:
        cands = [other_spouse(m, a) for m in fam.spouse_candidates[a]]
        if len(cands) < 2:
            continue
        listed = {l.person for l in fam.listing if l.filer == a and l.section == "spouse" and l.person in cands}
        if len(listed) == 1:
            continue
        yield DecisionSlot(
            key=f"所令220:{a}",
            target={"person": a, "tax_year": ctx.year, "説明": "年の中途で死亡した配偶者と再婚した配偶者のうち同一生計配偶者とする一人（所令220①）", "候補": sorted(cands)},
            matches=lambda rec, a=a, cs=frozenset(cands): rec["value"]["filer"] == a and rec["subject"]["spouse"] in cs and rec["value"]["listed"] is True,
            candidates=tuple(Candidate(c, c) for c in sorted(cands)) + (Candidate("", "どちらも同一生計配偶者としない"),),
            persons=(a, *cands),
        )


def estimate_slots(ctx: YearContext) -> Iterator[DecisionSlot]:
    """見積り.親族の合計所得金額（所基通85−1(2)）：年の中途で死亡した申告者 c の親族 d の、死亡の時の現況で見積もったその年の合計所得金額。

    記録があるときだけ1か所を置く（金額は候補を作れない。記録がない親族がいれば checks.py が c の親族に関する控除を対象外にする：入力すれば決まる）。
    """
    year = ctx.year
    seen: set[tuple[str, str]] = set()
    departures = person_departures(ctx)
    for j in ctx.judgments(K_EST):
        subj = j["subject"]
        d, c = subj["person"], subj["taxpayer"]
        if (d, c) in seen or c not in ctx.persons or d not in ctx.persons:
            continue
        death = ctx.death_on(c)
        if (death is None or death.year != year) and departures.get(c) is None:
            continue
        seen.add((d, c))
        yield DecisionSlot(
            key=estimate_key(d, c),
            target={"person": d, "taxpayer": c, "tax_year": year, "説明": "死亡した申告者の親族の合計所得金額の見積り（所基通85−1(2)）"},
            matches=lambda rec, d=d, c=c: rec["subject"]["person"] == d and rec["subject"]["taxpayer"] == c,
            persons=(d, c),
        )


DECISIONS: tuple[DecisionSpec, ...] = (
    DecisionSpec(J_SEIKEI, seikei_slots),
    DecisionSpec(J_DOUKYO, doukyo_slots),
    DecisionSpec(C_ATTR, attribution_slots, value_of=lambda rec: rec["value"]["filer"]),
    DecisionSpec(C_SPOUSE, spouse220_slots, value_of=lambda rec: rec["subject"]["spouse"]),
    DecisionSpec(K_EST, estimate_slots, value_of=lambda rec: rec["value"]["estimated_amount"]),
    DecisionSpec(K_DOMESTIC, domestic_source_slots, value_of=lambda rec: rec["value"]["non_domestic_income"]),
)


# 事業専従者（employers_of・is_senju：所法2①三十三・三十四、所基通2−48）は dependents/family.py。


# ---------------------------------------------------------------------------
# 段1：所得金額調整控除の対象の親族等を有するか
# ---------------------------------------------------------------------------


@dataclass
class _HasCandidate:
    """所得金額調整控除の第1項の「有する」の候補の親族1人（c から見た d）。"""

    d: str
    cap: int
    judged: int
    own_deduction: int  # d 自身の第1項の控除の額（d が給与等の収入金額の基準を超えなければ0）


def adjustment_first_item(wage: int, base: int, top: int, num: int, den: int) -> int:
    """措法41の3の11①の控除の額（給与等の収入金額が基準以下なら0。1円未満切上げ：TA No.1411）。"""
    if wage <= base:
        return 0
    return -(-((min(wage, top) - base) * num) // den)


def has_fixpoints(cands: Mapping[str, list[_HasCandidate]]) -> tuple[dict[str, bool], dict[str, bool]]:
    """第1項の「有する」の最小と最大の不動点。

    親族 d の合計所得金額は d 自身の第1項の控除の後の額（d も有するなら判定用の額から控除を引く）。d が有するほど親族の所得が下がって
    c も有しやすくなる（単調）ので、全員「有しない」からの反復で最小、全員「有する」からの反復で最大の不動点に着く。
    """

    def step(has: Mapping[str, bool]) -> dict[str, bool]:
        return {
            c: any(x.judged - (x.own_deduction if has.get(x.d, False) else 0) <= x.cap for x in xs)
            for c, xs in cands.items()
        }

    out = []
    for start in (False, True):
        has = {c: start for c in cands}
        while True:
            nxt = step(has)
            if nxt == has:
                break
            has = nxt
        out.append(has)
    return out[0], out[1]


def has_split(c: str, ds: Iterable[str]) -> Split:
    """「有する」が不動点の取り方で分かれる（親族どうしが互いの第1項の控除で上限以下になる）ときの読みの分かれ目。"""
    return Split(
        id=f"読み:所得金額調整控除の第1項の有する:{c}",
        means=Means.PRIMARY_SOURCE,
        target={
            "person": c,
            "親族": sorted(ds),
            "理由": "親族の合計所得金額が、その親族自身の所得金額調整控除の第1項の控除で上限以下になるかが、互いの「有する」に依存して決まらない（措法41の3の11①。一次情報が docs にない）",
        },
        candidates=("有する", "有しない"),
        splits_conclusion=True,
    )


def run_has(ctx: StageContext) -> StageOutput:
    """措法41の3の11①：年齢23歳未満の扶養親族又は特別障害者である同一生計配偶者若しくは扶養親族を有するか。

    親族の合計所得金額は、親族自身の第1項の控除の後の額で比べる（親族も給与等の収入金額が基準を超え、親族等を有するとき）。
    人をまたいで互いに依存するので、最小と最大の不動点を求め、一致すればその値、違えば読みの分かれ目（一次情報）にする（2026-11-11。以前は対象外）。
    """
    out = StageOutput()
    fam = build_family(ctx)
    p = ctx.parameters
    dep_cap = int(p.所得税.扶養親族.合計所得金額の上限)
    sp_cap = int(p.所得税.同一生計配偶者.合計所得金額の上限)
    age_cap = int(p.所得税.所得金額調整控除の対象の親族.年齢の上限)
    adj = p.所得税.所得金額調整控除
    base = int(adj.第1項の給与等の収入金額の基準)
    top = int(adj.第1項の給与等の収入金額の上限)
    num = int(adj.第1項の率.分子)
    den = int(adj.第1項の率.分母)
    cands: dict[str, list[_HasCandidate]] = {}
    meta: dict[str, tuple[set[str], set[State], list[StageValue]]] = {}
    for c in ctx.persons:
        ids: set[str] = set()
        states: set[State] = set()
        wage = ctx.value(R_WAGE, c)
        uses: list[StageValue] = [wage]
        meta[c] = (ids, states, uses)
        if wage.value <= base:  # 第1項の適用の入口（給与等の収入金額850万円超）に当たらない人は、親族の値を読まない（関係のない予測を伝えない）
            continue
        xs: list[_HasCandidate] = []
        for d in fam.neighbours[c]:
            rel = fam.relation(c, d)
            if rel.relative is not True:
                continue
            live = fam.live_decided(c, d)
            if live is None or live.value is not True:
                if live is not None and live.states:
                    states |= live.states
                continue
            if is_senju(fam, c, d):
                continue
            income = relative_value(fam, ctx, R_JUDGE, c, d)
            age = ctx.value(R_AGE, d)
            special = ctx.value(R_SPECIAL, d)
            uses += [income, age, special]
            ids |= set(rel.record_ids) | set(live.record_ids)
            states |= live.states
            if rel.kind == "配偶者":
                qualifies, cap = bool(special.value), sp_cap
            else:
                qualifies, cap = bool(age.value < age_cap or special.value), dep_cap
            if not qualifies:
                continue
            own = 0
            if income.value > cap:  # 上限を超える親族だけ、親族自身の第1項の控除を見る
                d_wage = ctx.value(R_WAGE, d)
                uses.append(d_wage)
                own = adjustment_first_item(int(d_wage.value), base, top, num, den)
            xs.append(_HasCandidate(d, cap, int(income.value), own))
        cands[c] = xs
    low, high = has_fixpoints(cands)
    nr = nonresident_income_splits(fam)
    for c in ctx.persons:
        ids, states, uses = meta[c]
        value = low.get(c, False)
        missing = () if value == high.get(c, False) else (has_split(c, (x.d for x in cands[c])),)
        missing += tuple(split for d, (split, claimants) in nr.items() if c in claimants and c in cands)
        out.set(V_HAS, c, value, ids, states, uses=uses, missing=missing)
    return out


# ---------------------------------------------------------------------------
# 段2：扶養の割当て
# ---------------------------------------------------------------------------


def _income_219(ctx: StageContext, person: str) -> tuple[int, list[StageValue]]:
    """所令219②二：総所得金額、退職所得金額及び山林所得金額の合計額（措令4の2⑨・25の11の2⑳ の読替えで上場株式等の所得を含める）。"""
    values = [ctx.value(v, person) for v in (R_GROSS, R_RETIRE, R_DIV, R_GAIN)]
    return sum(v.value for v in values), values


def _year_end_adjusted_or_filed(ctx: YearContext, idx: IrIndex, person: str) -> bool:
    """その年分について年末調整を受け、又は確定申告書を提出した（所法83の2②二・84の2②二のかっこ書き）か。決定は記録の語彙にない。"""
    for r in idx.of("withholding_slip", person):
        if overlaps_year(r.get("when"), ctx.year) and r["attributes"]["slip_type"] == "salary" and r["attributes"].get("year_end_adjusted") is True:
            return True
    for r in idx.of("filed_document", person):
        a = r["attributes"]
        if r["roles"]["filer"] == person and a.get("tax_year") == ctx.year and a["document_type"] in RETURN_DOCUMENTS:
            return True
    return False


def _withholding_lists(ctx: YearContext, idx: IrIndex, filer: str, section: str, target: str | None = None) -> list[str]:
    """filer がその年分の扶養控除等申告書に section の区分で記載した人（target があればその人だけ）を返す。"""
    out: list[str] = []
    for r in idx.of("filed_document", filer):
        a = r["attributes"]
        if r["roles"]["filer"] != filer or a.get("tax_year") != ctx.year or a["document_type"] not in WITHHOLDING_DECLARATIONS:
            continue
        out += [e["person"] for e in a.get("entries", []) if e["section"] == section and (target is None or e["person"] == target)]
    return out


def _spouse_status_ok(fam: Family, ctx: StageContext, a: str, b: str) -> tuple[bool, list[StageValue]]:
    """b が a の同一生計配偶者に当たりうるか（生計・専従者・所得）。"""
    uses: list[StageValue] = []
    live = fam.live_true(a, b)
    if not live or is_senju(fam, a, b):
        return False, uses
    income = relative_value(fam, ctx, R_TOTAL, a, b)
    uses.append(income)
    return income.value <= int(ctx.parameters.所得税.同一生計配偶者.合計所得金額の上限), uses


def _spouse_special_eligible(fam: Family, ctx: StageContext, a: str, b: str) -> tuple[bool, list[StageValue]]:
    """b が a の配偶者特別控除の対象の配偶者に当たりうるか（控除対象配偶者に当たらない部分）。"""
    uses: list[StageValue] = []
    if not fam.live_true(a, b) or is_senju(fam, a, b):
        return False, uses
    income = relative_value(fam, ctx, R_TOTAL, a, b)
    me = ctx.value(R_TOTAL, a)
    uses += [income, me]
    p = ctx.parameters.所得税
    ok = income.value <= int(p.配偶者特別控除.配偶者の合計所得金額の上限) and income.value > int(p.同一生計配偶者.合計所得金額の上限) and me.value <= int(p.配偶者特別控除.居住者の合計所得金額の上限)
    return ok, uses


def _choose_spouses(fam: Family, ctx: StageContext, states: dict[str, set[State]], ids: dict[str, set[str]]) -> dict[str, str | None]:
    """人 → その人の配偶者（法律婚のグループの相手。いなければ None）。死亡と再婚が同じ年なら所令220① で一人に絞る（dependents.allocation.choose_spouses）。"""
    return choose_spouses(fam, ctx.decision, states, ids)


def _apply_220_2(fam: Family, chosen: Mapping[str, str | None], allocs: Mapping[str, _Alloc]) -> dict[str, Split]:
    """所令220②：死亡した配偶者・再婚した配偶者のうち、a が一人を同一生計配偶者としたときは、それ以外の者は他の居住者の扶養親族に当たらない。
    いずれも同一生計配偶者としないときは、一人に限り他の居住者の扶養親族に当たる（どの一人かの定めは原文にないので、2人以上なら読みの分かれ目）。
    ③（_rule_220_3）で死亡した配偶者を他の居住者の扶養親族としたときは、その者を外さない。allocs を直し、分かれ目を返す。
    """
    splits: dict[str, Split] = {}
    for a in fam.ctx.persons:
        cand = fam.spouse_candidates[a]
        if len(cand) < 2:
            continue
        names = [other_spouse(m, a) for m in cand]
        third = _rule_220_3(fam, a, names)
        kept_dead = set()
        if third is not None:
            kept_dead = {b for b in names if b != third[0]}
        deps = [n for n in names if allocs[n].claimant is not None and allocs[n].claimant != a and n not in kept_dead]
        if chosen.get(a) is not None:
            for n in deps:
                if n != chosen[a]:
                    allocs[n].claimant = None
        elif len(deps) >= 2 and not kept_dead:
            for n in deps:
                splits[n] = Split(
                    id=f"読み:所令220②:{a}",
                    means=Means.PRIMARY_SOURCE,
                    target={
                        "person": a,
                        "配偶者": sorted(deps),
                        "理由": "死亡した配偶者と再婚した配偶者のどちらも他の居住者の扶養親族に当たりうるが、所令220② の「一人に限り」をどちらにするかの定めが docs の一次情報にない",
                    },
                    candidates=tuple(sorted(deps)),
                    splits_conclusion=True,
                )
    return splits


def _eligible_dep(fam: Family, ctx: StageContext, c: str, d: str, cap_dep: int, cap_spec: int, spec_low: int, spec_high: int) -> Candidacy:
    """c と d が扶養親族・特定親族の関係に当たりうるか（所法2①三十四・84の2①。所属を除く要件）。組の要件は dependents.allocation.pair_candidacy。"""
    ok, ids, states = pair_candidacy(fam, c, d)
    if not ok:
        return Candidacy(False, (), frozenset(ids), frozenset(states))
    uses: list[StageValue] = []
    resident = ctx.value(R_RESIDENT, c)
    uses.append(resident)
    if not resident.value:
        return Candidacy(False, tuple(uses), frozenset(ids), frozenset(states))
    income = relative_value(fam, ctx, R_TOTAL, c, d)
    age = ctx.value(R_AGE, d)
    uses += [income, age]
    years = _judged_age(fam, ctx, c, d, int(age.value))
    ok = income.value <= cap_dep or (spec_low <= years < spec_high and income.value <= cap_spec)
    return Candidacy(ok, tuple(uses), frozenset(ids), frozenset(states))


def _judged_age(fam: Family, ctx: StageContext, judge: str, d: str, own: int) -> int:
    """judge の判定の時の d の年齢（所法85③。判定の時が d 自身の判定の時と同じなら d の 所得税_年齢：PD-05）。"""
    t = fam.judge_time(judge, d)
    if t == judgment_date(ctx.year, fam.cut(d)):
        return own
    from ...dependents.kinship import age_on  # noqa: PLC0415

    return age_on(ctx.birth_on(d), judgment_day(t, t if t in (fam.deaths[judge], fam.deaths[d]) else None))


def _pick_by_income(fam: Family, ctx: StageContext, d: str, people: Iterable[str], a: _Alloc) -> str | None:
    """所令219② 第2号：所得の合計額が最も大きい居住者。同額なら選択の1か所（未入力なら候補を評価）。"""
    amounts: dict[str, int] = {}
    for p in people:
        v, used = _income_219(ctx, p)
        amounts[p] = v
        a.uses += used
    tied = largest(amounts)
    if len(tied) == 1:
        return tied[0]
    try:
        dec = ctx.decision(C_ATTR, tie_key(d))
    except KeyError:
        a.problems.append("所令219②二でも同額で、選択の1か所を宣言していない（提出日も同じで判断の材料がない）")
        return tied[0]
    a.ids |= set(dec.record_ids)
    a.states |= dec.states
    return dec.value if dec.value in tied else tied[0]


def _allocate_one(fam: Family, ctx: StageContext, d: str, eligible: Mapping[str, Candidacy], spouse: str | None, spouse_ok: bool, spouse_uses: list[StageValue]) -> _Alloc:
    """1人の扶養親族等の所属（所令218・218の2・219。純粋関数は dependents.allocation.allocate_one）。"""
    mine = [l for l in fam.listing if l.person == d]
    others: dict[str, set[str]] = {}
    for l in mine:
        others.setdefault(l.filer, set()).add(l.record_id)
    return allocate_one(
        eligible,
        spouse,
        spouse_ok,
        spouse_uses,
        [l.record_id for l in mine if l.filer == spouse and l.section == "spouse"],
        [DepListing(l.filer, l.on, l.record_id) for l in mine if l.section in DEP_SECTIONS],
        others,
        lambda people, a: _pick_by_income(fam, ctx, d, people, a),
        Rule.INCOME_TAX,
    )


def run_allocation(ctx: StageContext) -> StageOutput:
    """所令218〜220：親族の扶養親族等・配偶者の所属を、記載の事実（なければ所得の合計額）から決める。"""
    out = StageOutput()
    fam = build_family(ctx)
    p = ctx.parameters.所得税
    cap_dep = int(p.扶養親族.合計所得金額の上限)
    cap_spec = int(p.特定親族.合計所得金額の上限)
    spec_low = int(p.特定親族.年齢の下限)
    spec_high = int(p.特定親族.年齢の上限)
    spouse_ids = {a: set[str]() for a in ctx.persons}
    spouse_states: dict[str, set[State]] = {a: set() for a in ctx.persons}
    chosen = _choose_spouses(fam, ctx, spouse_states, spouse_ids)
    allocs: dict[str, _Alloc] = {}
    for d in ctx.persons:
        eligible: dict[str, Candidacy] = {}
        for c in fam.neighbours[d]:
            eligible[c] = _eligible_dep(fam, ctx, c, d, cap_dep, cap_spec, spec_low, spec_high)
        spouse = chosen[d] if chosen[d] is not None and chosen.get(chosen[d]) == d else None  # d を配偶者とする相手（所令220① で別の人を選んだ相手を除く）
        ok, sp_uses = (False, [])
        if spouse is not None:
            ok, sp_uses = _spouse_status_ok(fam, ctx, spouse, d)
            if not ok:
                ok2, uses2 = _spouse_special_eligible(fam, ctx, spouse, d)
                ok, sp_uses = ok2, sp_uses + uses2
        allocs[d] = _allocate_one(fam, ctx, d, eligible, spouse, ok, sp_uses)
    splits_220 = _apply_220_2(fam, chosen, allocs)
    claimants_with_deps = {a.claimant for a in allocs.values() if a.claimant is not None}
    chain = {d for d, a in allocs.items() if a.claimant is not None and d in claimants_with_deps}
    # --- 扶養所属のグループ ---
    deps_of: dict[str, list[str]] = {}
    for d, a in allocs.items():
        if a.claimant is not None and d not in chain:
            deps_of.setdefault(a.claimant, []).append(d)
    instances: list[GroupInstance] = []
    grouped_as_dep = {d for ds in deps_of.values() for d in ds}
    for person in ctx.persons:
        if person in grouped_as_dep:
            continue
        roles: dict[str, tuple[str, ...]] = {"申告者一覧": (person,)}
        deps = sorted(deps_of.get(person, ()))
        uses: list[StageValue] = []
        ids: set[str] = set()
        states: set[State] = set()
        for d in deps:
            uses += allocs[d].uses
            ids |= allocs[d].ids
            states |= allocs[d].states
        if deps:
            roles["扶養親族等一覧"] = tuple(deps)
        instances.append(GroupInstance(f"扶養所属:{person}", roles, tuple(sorted(ids)), frozenset(states), uses=tuple(uses)))
    if "扶養所属一覧" in ctx.stage.groups:  # テストの道具のモジュールがグループを受け持つ場合がある（tests/fixture_modules.py）
        out.group("扶養所属一覧", instances)
    # --- 法律婚のグループ ---
    used: set[str] = set()
    marriages: list[GroupInstance] = []
    for a in ctx.persons:
        if a in used:
            continue
        b = chosen[a]
        if b is not None and chosen.get(b) == a and b not in used and b in fam.alive:
            used |= {a, b}
            marriages.append(GroupInstance(f"法律婚:{min(a, b)}:{max(a, b)}", {"配偶者一覧": (a, b)}, tuple(sorted(spouse_ids[a] | spouse_ids[b])), frozenset(spouse_states[a] | spouse_states[b]), uses=()))
        else:
            used.add(a)
            marriages.append(GroupInstance(f"法律婚:{a}", {"配偶者一覧": (a,)}, tuple(sorted(spouse_ids[a])), frozenset(spouse_states[a]), uses=()))
    if "法律婚一覧" in ctx.stage.groups:
        out.group("法律婚一覧", marriages)
    by: dict[tuple[str, str | None], tuple[Split, ...]] = {(d, None): (sp,) for d, sp in splits_220.items()}
    for d, (split, claimants) in nonresident_income_splits(fam).items():
        by[(d, None)] = by.get((d, None), ()) + (split,)
        for c in claimants:  # 配偶者としての判定（同一生計配偶者・配偶者特別控除）は相手の側の入力も読む
            if chosen.get(c) == d:
                by[(c, V_SP_LIVE)] = by.get((c, V_SP_LIVE), ()) + (split,)
    target = _Missing(out, by) if by else out
    _write_relation_inputs(target, fam, ctx, chosen, allocs, chain)  # type: ignore[arg-type]
    for x in ctx.persons:
        _outside_spouse_inputs(target, fam, ctx, x, chosen, allocs)  # type: ignore[arg-type]
    return out


def judge_of(d: str, claimant: str | None, chosen: Mapping[str, str | None]) -> str | None:
    """d を判定する人：扶養の割当ての申告者、なければ d を配偶者とする法律婚の相手（所令220① で別の人を選んだ相手を除く）。"""
    if claimant is not None:
        return claimant
    b = chosen.get(d)
    return b if b is not None and chosen.get(b) == d else None


def _write_judge_time(out: StageOutput, fam: Family, ctx: StageContext, d: str, judge: str | None) -> PersonAt | None:
    """判定する人の判定の時の現況（所法85③。PD-05）。判定の時がその人自身の判定の時と同じなら書かない（式はその人自身の値を使う）。"""
    own = judgment_date(ctx.year, fam.cut(d))
    t = fam.judge_time(judge, d) if judge is not None else own
    if judge is None or t == own:
        for v in (V_AT_USE, V_AT_RESIDENT, V_AT_STUDY, V_AT_DISABLED, V_AT_SPECIAL):
            out.set(v, d, False, uses=())
        out.set(V_AT_AGE, d, 0, uses=())
        return None
    age_day = judgment_day(t, t if t in (fam.deaths[judge], fam.deaths[d]) else None)
    at = person_at(ctx.ir, fam.idx, d, ctx.birth_on(d), t, age_day, limits_from(ctx.parameters))
    basis = [JUDGE_TIME_RULE]
    out.set(V_AT_USE, d, True, at.ids, at.states, uses=(), basis=basis)
    out.set(V_AT_AGE, d, at.age, at.ids, at.states, uses=(), basis=basis)
    for v, value in ((V_AT_RESIDENT, at.resident), (V_AT_STUDY, at.study_abroad), (V_AT_DISABLED, at.disabled), (V_AT_SPECIAL, at.special)):
        out.set(v, d, bool(value), at.ids, at.states, uses=(), basis=basis, missing=at.missing)
    return at


def _write_relation_inputs(out: StageOutput, fam: Family, ctx: StageContext, chosen: Mapping[str, str | None], allocs: Mapping[str, _Alloc], chain: set[str]) -> None:
    for d in ctx.persons:
        a = allocs[d]
        c = a.claimant
        for prob in a.problems:
            out.exclude(d, _reason(prob, a.ids), V_KIN)
        ids = tuple(sorted(a.ids))
        states = frozenset(a.states)
        uses = tuple(a.uses)
        at = _write_judge_time(out, fam, ctx, d, judge_of(d, c, chosen))
        if c is None:
            for v in (V_KIN, V_CHILD, V_LIVE, V_COHAB, V_COHAB_ETC, V_ASCENDANT, V_SENJU, V_DOC, V_DOC_STUDY, V_DOC_38):
                out.set(v, d, False, ids, states, uses=uses)
            out.set(V_REMIT, d, 0, ids, states, uses=uses)
            out.set(V_CHAIN, d, False, ids, states, uses=uses)
            out.set(V_CLAIMANT, d, "", ids, states, uses=uses)
            out.set(V_SPEC_EXCL, d, False, ids, states, uses=uses)
        else:
            # 組ごとの事実（同居・直系尊属・国外居住親族の書類〔所令262④〕・送金）は dependents.allocation.relation_facts（住民税の割当てと同じ関数）
            f = relation_facts(fam, c, d, chosen.get(c), ids, on=fam.judge_time(c, d))
            # 判定する人の判定の時に住所が国外の人（出国した親族）は、その時に同居を常況としていない（法令の読み：PD-05）
            abroad = at is not None and at.resident is False
            out.set(V_KIN, d, f.kin, ids, states, uses=uses)
            out.set(V_CHILD, d, f.child, ids, states, uses=uses)
            out.set(V_LIVE, d, True, ids, states, uses=uses)
            # 同居老親等の同居：判定の時に老人ホーム等へ入所していれば同居でない（判断.老人ホーム等。cohab_fx.py。同居のときだけ読む）
            t_cd = fam.judge_time(c, d)
            home, home_ids, home_states = (
                home_override(fam.idx.of("institution_stay", d), t_cd, lambda k: ctx.decision(J_HOME, k)) if f.cohab and not abroad else (False, (), frozenset())
            )
            out.set(
                V_COHAB, d, f.cohab and not abroad and not home, tuple(sorted(set(f.cohab_ids) | set(home_ids))), states | f.cohab_states | home_states,
                uses=uses, basis=[HOME_RULE] if home_ids else [],
            )
            out.set(V_COHAB_ETC, d, f.cohab_etc and not abroad, f.cohab_ids, states | f.cohab_states, uses=uses)
            out.set(V_ASCENDANT, d, f.ascendant, ids, states, uses=uses)
            out.set(V_SENJU, d, False, ids, states, uses=uses)
            out.set(V_DOC, d, f.doc, f.doc_ids, states, uses=uses)
            out.set(V_DOC_STUDY, d, f.doc_study, f.study_ids, states, uses=uses)
            out.set(V_DOC_38, d, f.doc_38, f.doc38_ids, states, uses=uses)
            # 外貨建ての送金の円換算の方法（選択.円換算の方法。値は変えず、由来と根拠に付ける：cohab_fx.py）
            remits = [
                r for r in fam.idx.of("remittance", d)
                if r["roles"].get("sender") == c and r["roles"].get("recipient") == d and overlaps_year(r.get("when"), ctx.year)
            ]  # fmt: skip
            fx_ids, fx_basis = fx_provenance(remits, ctx.choices(C_FX), c, ctx.year)
            out.set(V_REMIT, d, f.remit, tuple(sorted(set(f.remit_ids) | set(fx_ids))), states | f.remit_states, uses=uses, basis=list(fx_basis))
            out.set(V_CHAIN, d, d in chain, ids, states, uses=uses)
            out.set(V_CLAIMANT, d, c, ids, states, uses=uses)
            _spec_excl(out, fam, ctx, d, c, allocs, ids, states, uses)
        _estimate_inputs(out, fam, ctx, d, c, chosen)
        _spouse_inputs(out, fam, ctx, d, chosen, abroad=c is None and at is not None and at.resident is False)


def _estimate_inputs(out: StageOutput, fam: Family, ctx: StageContext, d: str, claimant: str | None, chosen: Mapping[str, str | None]) -> None:
    """d の扶養等の判定に使う合計所得金額を、死亡した申告者の見積りにするか（所基通85−1(2)）。

    d を判定する申告者は、d の扶養親族等の申告者（割当て）、それがなければ d を配偶者とする人（法律婚の相手）。その人が年の中途で死亡し、
    見積り.親族の合計所得金額 があれば見積額を使う（状態「見積り」が依存する値へ伝わる：D21 R2）。
    """
    owner = claimant
    if owner is None:
        b = chosen.get(d)
        owner = b if b is not None and chosen.get(b) == d else None
    if owner is not None and dies_in_year(fam, owner):
        try:
            est = ctx.decision(K_EST, estimate_key(d, owner))
        except KeyError:
            est = None
        if est is not None:
            out.set(V_EST_USE, d, True, est.record_ids, est.states, uses=())
            out.set(V_EST_AMT, d, int(est.value), est.record_ids, est.states, uses=())
            return
    out.set(V_EST_USE, d, False, uses=())
    out.set(V_EST_AMT, d, 0, uses=())


def _spec_excl(out: StageOutput, fam: Family, ctx: StageContext, d: str, c: str, allocs: Mapping[str, _Alloc], ids: tuple[str, ...], states: frozenset[State], uses: tuple[StageValue, ...]) -> None:
    """所法84の2②・所令217の2：特定親族 d について c の特定親族特別控除を適用しない場合（令和8年分以後の号は年分で切り替える）。"""
    p = ctx.parameters.所得税.特定親族
    spec_low, spec_high = int(p.年齢の下限), int(p.年齢の上限)
    cap_spec = int(p.合計所得金額の上限)
    cap_dep = int(ctx.parameters.所得税.扶養親族.合計所得金額の上限)
    claimed = False
    more_uses: list[StageValue] = []
    for e, a in allocs.items():
        if a.claimant == d:
            inc = ctx.value(R_TOTAL, e)
            age = ctx.value(R_AGE, e)
            more_uses += [inc, age]
            if spec_low <= age.value < spec_high and inc.value <= cap_spec and inc.value > cap_dep:
                claimed = True
    excl = claimed
    extra: set[str] = set()
    if ctx.year >= 2026:  # 令和8年分以後（令和7年法律第13号附則第6条②、令和7年政令第120号附則第11条：misc §4.2）
        if _withholding_lists(ctx, fam.idx, d, "specific_relative") and not _year_end_adjusted_or_filed(ctx, fam.idx, d):
            excl = True
            extra |= {r["id"] for r in fam.idx.of("filed_document", d) if r["attributes"]["document_type"] in WITHHOLDING_DECLARATIONS}
        for z in fam.alive:
            if z == c or z == d:
                continue
            if _withholding_lists(ctx, fam.idx, z, "specific_relative", c) and not _year_end_adjusted_or_filed(ctx, fam.idx, z):
                excl = True
                extra |= {r["id"] for r in fam.idx.of("filed_document", z) if r["attributes"]["document_type"] in WITHHOLDING_DECLARATIONS}
    out.set(V_SPEC_EXCL, d, excl, tuple(sorted(set(ids) | extra)), states, uses=uses + tuple(more_uses))


def _outside_spouse_inputs(out: StageOutput, fam: Family, ctx: StageContext, x: str, chosen: Mapping[str, str | None], allocs: Mapping[str, _Alloc]) -> None:
    """法律婚のグループ外の配偶者（所令220①：x の配偶者 y が、別の人を自分の配偶者とした）について、x の配偶者に関する控除の材料を書く。

    法律婚のグループは1対1なので、年の中途の死亡と再婚で x→y と y→z が両方あると、x と y を同じグループにできない（2026-11-11 まで対象外 PD-18）。
    x の側の判定に要る y の値（合計所得金額〔x が死亡したときは見積り〕・年齢・他の居住者の扶養親族等か・障害の区分）を x の入力にし、
    式はグループの代わりにこれを使う。障害の区分は 0 なし・1 障害者・2 特別障害者・3 同居特別障害者（所法79③）。
    """
    y = chosen.get(x)
    if y is None or chosen.get(y) == x:
        out.set(V_OUT, x, False, uses=())
        out.set(V_OUT_INC, x, 0, uses=())
        out.set(V_OUT_AGE, x, 0, uses=())
        out.set(V_OUT_DEP, x, False, uses=())
        out.set(V_OUT_DIS, x, 0, uses=())
        return
    inc = relative_value(fam, ctx, R_TOTAL, x, y)
    age = ctx.value(R_AGE, y)
    special = ctx.value(R_SPECIAL, y)
    disabled = ctx.value(R_DISABLED, y)
    cohab, decs = fam.cohabits(x, y)
    for z in fam.neighbours[x]:
        if z != y and fam.live_true(x, z):
            v, more = fam.cohabits(z, y)
            cohab, decs = cohab or v, decs + more
    is_special, is_disabled, miss = bool(special.value), bool(disabled.value), ()
    t = fam.judge_time(x, y)
    if t != judgment_date(ctx.year, fam.cut(y)):  # x の判定の時の y の現況（所法85③。PD-05）
        at = person_at(ctx.ir, fam.idx, y, ctx.birth_on(y), t, judgment_day(t, t if t in (fam.deaths[x], fam.deaths[y]) else None), limits_from(ctx.parameters))
        is_special, is_disabled, miss = bool(at.special), bool(at.disabled), at.missing
        cohab = cohab and at.resident is not False
    kind = 3 if is_special and cohab else 2 if is_special else 1 if is_disabled else 0
    ids = tuple(sorted({i for d in decs for i in d.record_ids}))
    states = frozenset({st for d in decs for st in d.states})
    out.set(V_OUT, x, True, uses=())
    out.set(V_OUT_INC, x, int(inc.value), inc.facts, inc.states, uses=[inc])
    out.set(V_OUT_AGE, x, _judged_age(fam, ctx, x, y, int(age.value)), uses=[age])
    out.set(V_OUT_DEP, x, allocs[y].claimant is not None, tuple(sorted(allocs[y].ids)), frozenset(allocs[y].states), uses=tuple(allocs[y].uses))
    out.set(V_OUT_DIS, x, kind, ids, states, uses=[special, disabled], missing=miss)


def _spouse_inputs(out: StageOutput, fam: Family, ctx: StageContext, a: str, chosen: Mapping[str, str | None], abroad: bool = False) -> None:
    """a の法律婚の相手との関係の入力（生計・専従者・配偶者特別控除の適用除外・配偶者等との同居）と、相手の人の ID（様式の配偶者の行）。"""
    b = chosen.get(a)
    out.set(V_SPOUSE, a, b or NO_PERSON, uses=())
    if b is None:
        for v in (V_SP_LIVE, V_SP_SENJU, V_SP_EXCL, V_COHAB_SPOUSE):
            out.set(v, a, False, uses=())
        return
    live = fam.live_decided(a, b)
    if live is None:
        for v in (V_SP_LIVE, V_SP_SENJU, V_SP_EXCL, V_COHAB_SPOUSE):
            out.set(v, a, False, uses=())
        return
    out.set(V_SP_LIVE, a, live.value is True, live.record_ids, live.states, uses=())
    senju = is_senju(fam, a, b)
    out.set(V_SP_SENJU, a, senju, (), (), uses=())
    # 配偶者特別控除の適用除外（所法83の2②）
    excl = False
    ids: set[str] = set()
    states: set[State] = set()
    uses: list[StageValue] = []
    if fam.live_true(a, b):
        ok_a, u_a = _spouse_special_eligible(fam, ctx, a, b)
        ok_b, u_b = _spouse_special_eligible(fam, ctx, b, a)
        uses += u_a + u_b
        if ok_a and ok_b:  # 夫婦の双方が互いに要件に当たる：申告書等の記載（又は選択）でどちらが受けるかを決める（所法83の2②一）
            claimants = sorted({l.filer for l in fam.listing if l.section == "spouse" and {l.filer, l.person} == {a, b}})
            if len(claimants) == 1:
                excl = claimants[0] != a
                ids |= {l.record_id for l in fam.listing if l.section == "spouse" and {l.filer, l.person} == {a, b}}
            else:
                out.exclude(
                    a,
                    _reason(
                        "夫婦の双方が互いに配偶者特別控除の要件に当たり、どちらが適用を受けるか（所法83の2②一）が申告書等の記載で決まらない。"
                        "選択.配偶者の記載（listed=true）を一人について入力すれば決まる",
                        sorted({l.record_id for l in fam.listing if l.section == "spouse" and {l.filer, l.person} == {a, b}}),
                    ),
                    V_SP_EXCL,
                )
    # 第2号：b が a を源泉控除対象配偶者として記載し、年末調整・確定申告がない
    if _withholding_lists(ctx, fam.idx, b, "spouse", a) and not _year_end_adjusted_or_filed(ctx, fam.idx, b):
        excl = True
    out.set(V_SP_EXCL, a, excl, tuple(sorted(ids)), frozenset(states), uses=tuple(uses))
    # 配偶者等との同居（所法79③：配偶者の側の値。配偶者が特別障害者のとき相手から見た同居）
    cohab, decs = fam.cohabits(a, b)
    for x in fam.neighbours[b]:
        if x == a or not fam.live_true(b, x):
            continue
        v, more = fam.cohabits(x, a)
        cohab = cohab or v
        decs = decs + more
    # 配偶者の判定の時に住所が国外の人（出国した配偶者）は、その時に同居を常況としていない（法令の読み：PD-05）
    out.set(V_COHAB_SPOUSE, a, cohab and not abroad, tuple(sorted({i for d in decs for i in d.record_ids})), frozenset({s for d in decs for s in d.states}), uses=())


# ---------------------------------------------------------------------------
# 段3：扶養の連鎖の合計
# ---------------------------------------------------------------------------

R_DED1 = "所得税_扶養控除の1人分の額"
R_SPEC1 = "所得税_特定親族特別控除の1人分の額"
R_DIS1 = "所得税_障害者控除の扶養親族の1人分の額"
R_ISDEP = "所得税_扶養親族に当たるか"
R_CHILD1 = "所得税_ひとり親の子に当たるか"


def run_chain(ctx: StageContext) -> StageOutput:
    """連鎖の人（扶養親族等で、自分も申告者）の控除の額を、その人の申告者に集める（グループでは表せない分）。"""
    out = StageOutput()
    additions: dict[str, dict[str, Any]] = {
        p: {V_CH_DED: 0, V_CH_SPEC: 0, V_CH_DIS: 0, V_CH_ANY: False, V_CH_CHILD: False, V_CH_SPEC_N: 0} for p in ctx.persons
    }
    uses: dict[str, list[StageValue]] = {p: [] for p in ctx.persons}
    states: dict[str, set[State]] = {p: set() for p in ctx.persons}
    for x in ctx.persons:
        chain = ctx.value(V_CHAIN, x)
        claimant = ctx.value(V_CLAIMANT, x)
        if not chain.value or not claimant.value:
            continue
        c = claimant.value
        d = ctx.value(R_DED1, x)
        s = ctx.value(R_SPEC1, x)
        dis = ctx.value(R_DIS1, x)
        isdep = ctx.value(R_ISDEP, x)
        child = ctx.value(R_CHILD1, x)
        additions[c][V_CH_DED] += d.value
        additions[c][V_CH_SPEC] += s.value
        additions[c][V_CH_SPEC_N] += 1 if s.value > 0 else 0  # 第一表 G109 の人数（filing.py）
        additions[c][V_CH_DIS] += dis.value
        additions[c][V_CH_ANY] = additions[c][V_CH_ANY] or isdep.value
        additions[c][V_CH_CHILD] = additions[c][V_CH_CHILD] or child.value
        uses[c] += [d, s, dis, isdep, child, chain, claimant]
        states[c] |= set(d.states) | set(s.states) | set(dis.states)
    fam = build_family(ctx)
    missing: dict[str, list[Split]] = {}
    for split, claimants in nonresident_income_splits(fam).values():
        for c in claimants:  # 扶養親族として判定しうる申告者の額（グループに入らなかった場合も、読みによっては入りうる）
            missing.setdefault(c, []).append(split)
    for p in ctx.persons:
        for var, val in additions[p].items():
            out.set(var, p, val, (), frozenset(states[p]), uses=uses[p], missing=missing.get(p, ()))
    return out


__all__ = [
    "ALLOC_WRITES",
    "DECISIONS",
    "R_CHILD1",
    "R_DED1",
    "R_DIS1",
    "R_SPEC1",
    "STAGE_ALLOC",
    "STAGE_CHAIN",
    "STAGE_HAS",
    "V_CH_ANY",
    "V_CH_CHILD",
    "V_CH_DED",
    "V_CH_DIS",
    "V_CH_SPEC",
    "V_HAS",
    "run_allocation",
    "run_chain",
    "run_has",
]
