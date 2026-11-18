"""規則モジュール income_kinds：決算書・収支内訳書の科目の割当ての利用者による上書き（選択.様式への割当て C-18。2026-11-12）。

- 様式の対応表（forms/data/r07/割当て/科目.yaml。design-output UO19）は、必要経費の内訳のキー（記録の費目 expense_category など）を
  表ごとに既定の科目へ割り当てる。この選択は、利用者がある費目の額を **別の費目の既定の科目** に載せることを選ぶもの
  （例 {expense_category: membership_dues, form_item: other}：会費を租税公課でなく雑費に載せる）。所規47の3 は内訳書に必要経費を
  区分して書かせるが、印字のある科目のどれに載せるかの細目（書き方の「必要経費の各科目の具体例」）は例示で、記帳の科目は納税者が立てる
  （docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md §7.4 の 241 行・TA No.1810 の「任意科目」）。
- 科目の割当ては必要経費の額・所得・税額を変えない（欄の間で額を移すだけ）。そのため未入力のときに候補の全部で評価しない（D21 R6・D22 S20 の
  「選択の未入力は全候補で評価」は結論が変わりうる選択のため。ここでは結論が変わらない）：未入力なら既定の表どおり。
- 書き出す概念：所得税.<事業所得|不動産所得>の科目の割当ての選択（区分。人×年分）。値は「なし」か、「<費目>=<費目>」を費目の順に「;」でつないだ
  正規の形（例 "membership_dues=other;supplies=other"。同じ費目への割当て〔rent=rent〕は書かない）。forms の fill がこの値で科目の欄の内訳のキーを
  入れ替える（forms/README.md §4.1）。
- form_item は費目の符号（中間表現の CODE：科目名を持てない）。そのため、印字のない空欄の行（利用者が科目名を書く行。作成コーナーの「任意科目」）
  への割当ては受け付けない（語彙に科目名の欄がない。packages/ir への申し送り：README §5）。
- 売上原価の計算に使う費目（仕入：merchandise・materials。所法47・37①、収支内訳書⑥・決算書の仕入金額）は、売上原価の欄（⑦〜⑨）が仕入金額の
  概念から計算されるので、移す元にも先にもできない（移すと様式の式 ⑦＝⑤＋⑥ と合わなくなる）。
- business_id があれば、その業務の所得の側の表だけに当てる（不動産所得の業務なら不動産所得用、事業と称するに至る程度の業務なら一般用。業務に係る
  雑所得の業務は様式の表がないので当てない）。なければ、その人の事業所得・不動産所得の両方の表に当てる。表は人ごとに1つ（この版の様式の対応表）
  なので、その側の全部の業務の同じ費目を移す。
- 入力の矛盾（c-入力。README IK-120）：閉じた語彙 EXPENSE_CATEGORIES の業務の費目でない符号・売上原価の費目、同じ側で同じ費目を2つの違う費目へ
  割り当てる（1つの選択の中か、2つの選択の間）、業務の持ち主が選んだ人と違う。その側の概念を対象外にする（forms はその表の科目の欄を対象外にする）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...registry import Decided, ModuleInputs, YearContext
from ...result import OutOfScopeCategory, OutOfScopeReason
from .breakdown import INCOMES, NO_PERSON, PURCHASE_KEYS, RECORD_KEYS

K_FORM_MAP = "選択.様式への割当て"
JIGYO = "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md"
FORMS = "docs/public-sources/20261109_impl-prep_output-forms-and-specs.md"
_REFS = [f"{FORMS}#3", f"{JIGYO}#7.4"]

#: 割当てを変えられる費目（記録の費目のうち、売上原価の計算に使う仕入を除く）。
MOVABLE_KEYS: frozenset[str] = frozenset(RECORD_KEYS) - frozenset(PURCHASE_KEYS)
#: 上書きのないときの値（結果の区分の値は空にできない：result.Category）。
NO_OVERRIDE = NO_PERSON
PAIR_SEP = ";"
KV_SEP = "="

FORM_MAP_CODE_REASON = (
    "選択.様式への割当て の費目の符号が、割り当てを変えられる業務の支出の費目（okura_ir.vocabulary.EXPENSE_CATEGORIES のうち仕入〔merchandise・materials〕と"
    " dividend_debt_interest を除くもの）でない（仕入は売上原価の計算に使うので科目を変えられない。科目名を書く空欄の行への割当ては語彙に科目名がなく受け付けない）"
)
FORM_MAP_CONFLICT_REASON = "選択.様式への割当て で、同じ所得の表の同じ費目を2つの違う費目の科目へ割り当てている（選択を1つに直せば決まる）"
FORM_MAP_OWNER_REASON = "選択.様式への割当て の業務（business_id）の持ち主が、選んだ人（subject.person）と違う"

_PREFIX = "所得税"


def override_variable(side: str) -> str:
    return f"{_PREFIX}_{INCOMES[side]}の科目の割当ての選択"


def _input(name: str, label: str) -> type:
    attrs = {
        "value_type": str, "entity": 人物, "definition_period": YEAR, "label": label, "reference": _REFS,
        "default_value": NO_OVERRIDE, "__module__": __name__,
    }  # fmt: skip
    return type(name, (Variable,), attrs)


VARIABLES: tuple[type, ...] = tuple(
    _input(override_variable(side), f"{INCOMES[side]}の決算書・収支内訳書の科目の割当ての利用者の選択（「なし」か「費目=費目;…」）") for side in INCOMES
)


def encode(mapping: Mapping[str, str]) -> str:
    """費目 → 費目の上書きの正規の形（同じ費目への割当ては書かない）。"""
    pairs = sorted((k, v) for k, v in mapping.items() if k != v)
    return PAIR_SEP.join(f"{k}{KV_SEP}{v}" for k, v in pairs) if pairs else NO_OVERRIDE


def decode(value: str) -> dict[str, str]:
    """encode の逆（forms の fill も同じ形を読む）。「なし」は空。"""
    if value == NO_OVERRIDE:
        return {}
    out: dict[str, str] = {}
    for part in value.split(PAIR_SEP):
        k, _, v = part.partition(KV_SEP)
        out[k] = v
    return out


def _sides_of(ctx: YearContext, choice: Mapping[str, Any], owners: Mapping[str, str], rentals: Mapping[str, set[str]], bids: Mapping[str, list[str]]) -> tuple[tuple[str, ...], Decided | None, str | None]:
    """選択が当たる所得の側・使った判断（事業と称するに至る程度）・矛盾の理由。"""
    pid = choice["subject"]["person"]
    bid = choice["subject"].get("business_id")
    if bid is None:
        return tuple(INCOMES), None, None
    if owners.get(bid) != pid:
        return (), None, FORM_MAP_OWNER_REASON
    if bid in rentals.get(pid, ()):
        return ("rental",), None, None
    if bid not in bids.get(pid, ()):
        return (), None, None  # その年分に支出・売上・資産のない業務：表に載る額がない
    d = ctx.decision("判断.事業と称するに至る程度", f"{pid}:{bid}")
    return (("biz",) if d.value else ()), d, None


def write_form_overrides(ctx: YearContext, out: ModuleInputs) -> None:
    """全員の 所得税_<所得>の科目の割当ての選択 を書く（build_inputs の最後）。"""
    from .inputs import _owner, _person_bids, _rental_bids  # 循環の import を避ける（inputs は MODULE の組み立てで先に読まれる）

    persons = set(ctx.persons)
    chosen = [c for c in ctx.choices(K_FORM_MAP) if c["when"].get("tax_year") == ctx.year and c["subject"]["person"] in persons]
    owners, rentals, bids = (_owner(ctx), _rental_bids(ctx), _person_bids(ctx)) if chosen else ({}, {}, {})
    acc: dict[tuple[str, str], dict[str, str]] = {}
    ids: dict[tuple[str, str], list[str]] = {}
    states: dict[tuple[str, str], set[Any]] = {}
    bad: dict[tuple[str, str], list[tuple[str, list[str]]]] = {}
    for c in sorted(chosen, key=lambda x: x["id"]):
        pid = c["subject"]["person"]
        sides, d, problem = _sides_of(ctx, c, owners, rentals, bids)
        if problem is not None:
            for side in INCOMES:
                bad.setdefault((pid, side), []).append((problem, [c["id"]]))
            continue
        for side in sides:
            key = (pid, side)
            ids.setdefault(key, []).append(c["id"])
            if d is not None:
                ids[key] += [i for i in d.record_ids if i not in ids[key]]
                states.setdefault(key, set()).update(d.states)
            m = acc.setdefault(key, {})
            for item in c["value"]["mappings"]:
                src, dst = item["expense_category"], item["form_item"]
                if src not in MOVABLE_KEYS or dst not in MOVABLE_KEYS:
                    bad.setdefault(key, []).append((FORM_MAP_CODE_REASON, [c["id"]]))
                elif m.get(src, dst) != dst:
                    bad.setdefault(key, []).append((FORM_MAP_CONFLICT_REASON, sorted(set(ids[key]))))
                else:
                    m[src] = dst
    for pid in ctx.persons:
        for side in INCOMES:
            key = (pid, side)
            var = override_variable(side)
            for text, rids in bad.get(key, []):
                out.exclude(pid, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, text, tuple(rids)), var)
            value = NO_OVERRIDE if key in bad else encode(acc.get(key, {}))
            out.set(var, pid, value, ids.get(key, ()), states.get(key, set()))
