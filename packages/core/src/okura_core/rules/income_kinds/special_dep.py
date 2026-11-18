"""割増償却・特別償却（租税特別措置法 第10条の3〜第15条。2026-11-12。IK-112）：外部で計算した額を受け取り、普通償却と合わせる。

住宅借入金等特別控除と同じく、判定コアは特別償却限度額・割増償却の限度を計算しない（SCOPE §4・§5.2）。中間表現の事実
`special_depreciation`（資産・年分ごとの額、条、特別償却か割増償却か、前年の償却不足額の繰越か）を外部の値として受け取り、
- 青色申告書を提出する個人の要件（第11条の2〔被災代替資産等〕を除く各条の柱書）をその年分の青色申告の承認で確かめ、
- 普通償却費と合わせた償却費を必要経費に算入し（事業専用割合は合計に掛ける：決算書の「償却費合計×事業専用割合」）、
- 未償却残高を割増・特別償却の額でも減らし（その後の年分の定率法の基礎・累積の限度に効く：assets.depreciation_schedule の special）、
- 減価償却費の計算の行の「割増（特別）償却費」の列に写す（asset_rows.py）。

条の表（ARTICLES）は docs/public-sources/20261112_impl-research7_tokubetsu-shokyaku.md §1（scripts/IMPL7_tokubetsu_laws.py の出力）。
入力の不足・矛盾は c-入力（理由の定数）。根拠は SPECIAL_EXTERNAL_RULE（外部の値。detail に条・区分・繰越）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...basis import BasisEntry, BasisType, SourceKind
from ...registry import YearContext
from ...result import State

K_SPECIAL = "special_depreciation"
DOC = "docs/public-sources/20261112_impl-research7_tokubetsu-shokyaku.md"


@dataclass(frozen=True)
class Article:
    """個人の特別償却・割増償却の条（見出し・青色申告書を提出する個人の要件・所得の側〔biz 事業所得・rental 不動産所得〕）。"""

    title: str
    blue: bool
    sides: frozenset[str]


_BIZ = frozenset({"biz"})
_BOTH = frozenset({"biz", "rental"})
_T10_4_2 = "地方活力向上地域等において特定建物等を取得した場合の特別償却又は所得税額の特別控除"

#: 年分 → 条の番号 → 条（その年分の12月31日の版の本則。docs §1 の表）。10_4_2（令和7年分）と 10_5（令和8年分）は見出しが同じ（条の番号が移った）。
ARTICLES: Mapping[int, Mapping[str, Article]] = {
    2025: {
        "10_3": Article("中小事業者が機械等を取得した場合の特別償却又は所得税額の特別控除", True, _BIZ),
        "10_4": Article("地域経済牽引事業の促進区域内において特定事業用機械等を取得した場合の特別償却又は所得税額の特別控除", True, _BIZ),
        "10_4_2": Article(_T10_4_2, True, _BIZ),
        "10_5_3": Article("特定中小事業者が特定経営力向上設備等を取得した場合の特別償却又は所得税額の特別控除", True, _BIZ),
        "10_5_5": Article("生産工程効率化等設備を取得した場合の特別償却又は所得税額の特別控除", True, _BIZ),
        "11": Article("特定船舶の特別償却", True, _BIZ),
        "11_2": Article("被災代替資産等の特別償却", False, _BOTH),
        "11_3": Article("特定事業継続力強化設備等の特別償却", True, _BIZ),
        "11_4": Article("環境負荷低減事業活動用資産等の特別償却", True, _BIZ),
        "11_5": Article("生産方式革新事業活動用資産等の特別償却", True, _BIZ),
        "12": Article("特定地域における工業用機械等の特別償却", True, _BIZ),
        "12_2": Article("医療用機器等の特別償却", True, _BIZ),
        "13": Article("輸出事業用資産の割増償却", True, _BIZ),
        "14": Article("特定都市再生建築物の割増償却", True, _BOTH),
        "15": Article("倉庫用建物等の割増償却", True, _BIZ),
    },
    2026: {
        "10_3": Article("中小事業者が機械等を取得した場合の特別償却又は所得税額の特別控除", True, _BIZ),
        "10_4": Article("地域経済牽引事業の促進区域内において特定事業用機械等を取得した場合の特別償却又は所得税額の特別控除", True, _BIZ),
        "10_5": Article(_T10_4_2, True, _BIZ),
        "10_5_3": Article("特定中小事業者が特定経営力向上設備等を取得した場合の特別償却又は所得税額の特別控除", True, _BIZ),
        "10_5_5": Article("生産工程効率化等設備を取得した場合の特別償却又は所得税額の特別控除", True, _BIZ),
        "10_5_6": Article("特定生産性向上設備等を取得した場合の特別償却又は所得税額の特別控除", True, _BIZ),
        "11": Article("特定船舶の特別償却", True, _BIZ),
        "11_2": Article("被災代替資産等の特別償却", False, _BOTH),
        "11_3": Article("特定事業継続力強化設備等の特別償却", True, _BIZ),
        "11_4": Article("環境負荷低減事業活動用資産等の特別償却", True, _BIZ),
        "11_5": Article("生産方式革新事業活動用資産等の特別償却", True, _BIZ),
        "12": Article("特定地域における工業用機械等の特別償却", True, _BIZ),
        "12_2": Article("医療用機器等の特別償却", True, _BIZ),
        "13": Article("輸出事業用資産の割増償却", True, _BIZ),
        "14": Article("特定都市再生建築物の割増償却", True, _BOTH),
    },
}

METHOD_LABELS = {"special": "特別償却", "extra": "割増償却"}

SPECIAL_OWNER_REASON = "入力の矛盾：割増・特別償却の記録（special_depreciation）の owner が資産（depreciable_asset）の owner と違う"
SPECIAL_DUPLICATE_REASON = (
    "入力の矛盾：同じ資産・年分に割増・特別償却の記録（special_depreciation）が2件以上ある"
    "（同じ年に二以上の規定の適用を受けられる資産もいずれか一の規定だけ：租税特別措置法第19条第1項。1件にまとめる）"
)
SPECIAL_ARTICLE_REASON = (
    "入力の誤り：割増・特別償却の記録の条（article）が、その年分の版の租税特別措置法の個人の特別償却・割増償却の条でない"
    "（e-Gov の条の番号の形〔10_3 など〕で、その年分の版の番号を書く：docs/public-sources/20261112_impl-research7_tokubetsu-shokyaku.md §1）"
)
SPECIAL_BLUE_REASON = (
    "入力の矛盾：割増・特別償却の条が青色申告書を提出する個人を要件にするのに、その年分の青色申告の承認がない（blue_return_procedure の記録を確かめる）"
)
SPECIAL_SIDE_REASON = "入力の矛盾：割増・特別償却の条が当てる所得（事業所得、条によって不動産所得）でない業務の資産に記録がある"
SPECIAL_YEAR_REASON = "入力の矛盾：割増・特別償却の記録の年分が、資産を業務の用に供した年より前か、処分した年より後"
SPECIAL_MULTIPLE_REASON = (
    "入力の矛盾：同じ資産の割増・特別償却の記録の条が年分によって違う（前年以前にいずれか一の規定の適用を受けた資産は、ほかの規定を適用しない：租税特別措置法第19条第3項）"
)
SPECIAL_CARRYOVER_REASON = (
    "入力の矛盾：償却不足額の繰越（shortfall_carryover）の記録に、前年分の同じ資産・同じ規定の割増・特別償却の記録がない"
    "（繰り越せるのは適用を受けた年の翌年分だけ：第10条の3第2項・第13条第2項など）"
)
SPECIAL_FULL_EXPENSE_REASON = (
    "入力の矛盾：少額（所令138）・一括（所令139）・措法28の2 で全額を必要経費にした資産に、割増・特別償却の記録がある"
)
SPECIAL_LEASE_REASON = (
    "入力の矛盾：リース資産・国外リース資産（所有権移転外リース取引による取得）に割増・特別償却の記録がある（各条の第1項で除かれる）"
)
SPECIAL_EXCESS_REASON = "入力の矛盾：割増・特別償却の額が、その年の普通償却費を引いた後の償却できる残り（未償却残高の限度）を超える"

#: 根拠：外部で計算した値（SCOPE §4・§5.2：住宅借入金等特別控除と同じく額を受け取る）。detail に条・区分・繰越を足して使う。
SPECIAL_EXTERNAL_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "割増償却・特別償却の額は外部で計算した値（special_depreciation の amount）をそのまま使い、普通償却費と合わせた償却費（事業専用割合は合計に掛ける）を"
        "必要経費に算入し、未償却残高をその額でも減らす。青色申告書を提出する個人の要件と所得の種類は条ごとに確かめる"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "租税特別措置法第10条の3〜第15条（その年分の版の条）：普通償却の額と特別償却限度額（割増償却の限度）との合計額以下の金額で個人が必要経費として計算した金額。"
        "償却不足額は翌年分に繰り越せる（第10条の3第2項・第11条第2項・第13条第2項など）。第19条（複数の規定の不適用）。"
        "判定コアは限度額を計算しない（外部の値）"
    ),
    references=(f"{DOC}#1", f"{DOC}#2", f"{DOC}#4", f"{DOC}#5"),
    detail={"外部の値": True},
)


@dataclass
class SpecialPlan:
    """資産1つの割増・特別償却の材料（年分 → 額）と、その年分の問題・根拠。"""

    by_year: dict[int, int] = field(default_factory=dict)
    problem: str | None = None
    ids: tuple[str, ...] = ()
    states: set[State] = field(default_factory=set)
    basis: tuple[BasisEntry, ...] = ()
    blue_open: bool = False  # その年分の青色の承認が読みで分かれ、最初の候補（承認なし）で 0 にした

    @property
    def any(self) -> bool:
        return bool(self.by_year)


def _title(year: int, article: str) -> str | None:
    """条の見出し（その年分の版。表にない年分は令和7年分・令和8年分の版のどちらかにあれば、その見出し）。"""
    t = ARTICLES.get(year, {}).get(article)
    if t is not None:
        return t.title
    for table in ARTICLES.values():
        if article in table:
            return table[article].title
    return None


def records_for(ctx: YearContext, asset_id: str) -> list[Mapping[str, Any]]:
    """資産の割増・特別償却の記録（全部の年分。年分・ID の順）。"""
    recs = [r for r in ctx.records(K_SPECIAL) if r["attributes"]["asset_id"] == asset_id]
    return sorted(recs, key=lambda r: (int(r["when"]["tax_year"]), r["id"]))


def plan(
    ctx: YearContext,
    asset: Mapping[str, Any],
    side: str,
    placed_year: int,
    disposed_year: int | None,
    blue_now: Callable[[], tuple[bool, bool]],
    side_open: bool = False,
) -> SpecialPlan:
    """資産1つの割増・特別償却の材料。blue_now() は（その年分に青色申告の承認があるか, 承認が読みで分かれるか）。

    side_open：所得の側が未入力の判断（判断.事業と称するに至る程度）の候補か。候補の側が条の所得でなければ、その候補では適用しない（0。対象外にしない：
    判断の分かれ目で結論が分かれれば未確定）。入力した判断で当たらなければ入力の矛盾。"""
    recs = [r for r in records_for(ctx, asset["id"]) if int(r["when"]["tax_year"]) <= ctx.year]
    out = SpecialPlan()
    if not recs:
        return out
    out.ids = tuple(r["id"] for r in recs)
    out.states = {State.from_mark(r["mark"]) for r in recs if "mark" in r}
    owner = asset["roles"]["owner"]
    if any(r["roles"]["owner"] != owner for r in recs):
        out.problem = SPECIAL_OWNER_REASON
        return out
    years = [int(r["when"]["tax_year"]) for r in recs]
    if len(set(years)) != len(years):
        out.problem = SPECIAL_DUPLICATE_REASON
        return out
    if any(y < placed_year or (disposed_year is not None and y > disposed_year) for y in years):
        out.problem = SPECIAL_YEAR_REASON
        return out
    titles = {_title(int(r["when"]["tax_year"]), r["attributes"]["article"]) for r in recs} - {None}
    if len(titles) > 1:
        out.problem = SPECIAL_MULTIPLE_REASON
        return out
    by_year = {int(r["when"]["tax_year"]): int(r["amounts"]["amount"]) for r in recs}
    this = next((r for r in recs if int(r["when"]["tax_year"]) == ctx.year), None)
    if this is not None:
        a = this["attributes"]
        art = ARTICLES.get(ctx.year, {}).get(a["article"])
        if art is None:
            out.problem = SPECIAL_ARTICLE_REASON
            return out
        if side not in art.sides:
            if not side_open:
                out.problem = SPECIAL_SIDE_REASON
                return out
            by_year[ctx.year] = 0  # 未入力の判断の候補（業務に係る雑所得）では適用しない
        if a.get("shortfall_carryover"):
            prev = next((r for r in recs if int(r["when"]["tax_year"]) == ctx.year - 1), None)
            if prev is None or prev["attributes"].get("shortfall_carryover"):
                out.problem = SPECIAL_CARRYOVER_REASON
                return out
        if art.blue:
            approved, open_ = blue_now()
            if not approved:
                if not open_:
                    out.problem = SPECIAL_BLUE_REASON
                    return out
                by_year[ctx.year] = 0  # 承認が読みで分かれる：承認なしの候補では適用しない（分かれ目は呼び出し側が付ける）
                out.blue_open = True
        out.basis = () if not by_year.get(ctx.year) else (
            BasisEntry(
                type=SPECIAL_EXTERNAL_RULE.type,
                name=SPECIAL_EXTERNAL_RULE.name,
                source_kind=SPECIAL_EXTERNAL_RULE.source_kind,
                references=SPECIAL_EXTERNAL_RULE.references,
                law=SPECIAL_EXTERNAL_RULE.law,
                value=int(this["amounts"]["amount"]),
                detail={
                    "外部の値": True,
                    "資産": asset["id"],
                    "条": f"租税特別措置法第{_article_label(a['article'])}（{art.title}）",
                    "区分": METHOD_LABELS[a["method"]],
                    "償却不足額の繰越": bool(a.get("shortfall_carryover")),
                    "記録": this["id"],
                },
            ),
        )
    out.by_year = {y: v for y, v in by_year.items() if v}
    return out


def _article_label(num: str) -> str:
    """e-Gov の条の番号（10_3）を「10条の3」の形にする。"""
    head, *rest = num.split("_")
    return f"{head}条" + "".join(f"の{x}" for x in rest)


__all__ = [
    "ARTICLES",
    "Article",
    "K_SPECIAL",
    "METHOD_LABELS",
    "SPECIAL_ARTICLE_REASON",
    "SPECIAL_BLUE_REASON",
    "SPECIAL_CARRYOVER_REASON",
    "SPECIAL_DUPLICATE_REASON",
    "SPECIAL_EXCESS_REASON",
    "SPECIAL_EXTERNAL_RULE",
    "SPECIAL_FULL_EXPENSE_REASON",
    "SPECIAL_LEASE_REASON",
    "SPECIAL_MULTIPLE_REASON",
    "SPECIAL_OWNER_REASON",
    "SPECIAL_SIDE_REASON",
    "SPECIAL_YEAR_REASON",
    "SpecialPlan",
    "plan",
    "records_for",
]
