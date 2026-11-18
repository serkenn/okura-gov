"""規則モジュール tax の計算の後の対象外の検出（黙って近似しない）。

- 確定申告書の提出義務があるか：calc.filing_obligation が判定できないとした人（第121条の事実の不足：c-入力）。
- 2026-11-12：上場株式等の所得控除の順序は 選択.所得控除の順序 の1か所（措通31・32共−4）、住宅借入金等特別控除は年末調整の分を源泉徴収票の housing_loan_credit から
  （措法41の2の2⑥二）、暦要項の未発表は入力の分かれ目（公表待ち）にした（以前の stock_order_undetermined・REASON_HOUSING・deadline_not_determined の対象外を外した）。
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from ...registry import CheckContext, Exclusion
from ...result import OutOfScopeCategory, OutOfScopeReason
from .variables import LO_DEDUCTIONS, obligations_of, other_income_basis


def _reason(text: str, ids: tuple[str, ...] = ()) -> OutOfScopeReason:
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, text, ids)


def filing_obligation_undetermined(ctx: CheckContext) -> Iterator[Exclusion]:
    p = ctx.parameters.所得税.確定申告を要しない場合
    v: dict[str, object] = {
        "税総": ctx.calc("所得税_課税総所得金額に対する税額"),
        "税退": ctx.calc("所得税_課税退職所得金額に対する税額"),
        "税配当": ctx.calc("所得税_上場株式等に係る課税配当所得等の金額に対する税額"),
        "税譲渡": ctx.calc("所得税_上場株式等に係る課税譲渡所得等の金額に対する税額"),
        "配当控除": ctx.calc("所得税_配当控除の額"),
        "住宅": ctx.calc("所得税_年末調整で控除された住宅借入金等特別控除の額"),
        "還付": ctx.calc("所得税_還付される税額"),
        "給与": ctx.calc("所得税_給与等の収入金額"),
        "年金": ctx.calc("所得税_公的年金等の収入金額"),
        "退職全部": ctx.calc("所得税_退職手当等の全部が源泉徴収の対象か"),
        "退職源泉": ctx.calc("所得税_退職手当等の源泉徴収税額"),
    }
    if (v["給与"] > 0).any() or (v["年金"] > 0).any():  # type: ignore[attr-defined]
        給与所得 = ctx.calc("所得税_給与所得")
        調整 = ctx.calc("所得税_所得金額調整控除")
        支払者 = ctx.calc("所得税_給与等の支払者の数")
        n = len(支払者)
        v.update(
            {
                "基礎": other_income_basis(ctx.calc("所得税_合計所得金額"), 給与所得, 調整, ctx.calc("所得税_退職所得の金額"), ctx.calc("所得税_青色申告特別控除額")),
                "給与所得": 給与所得,
                "調整": 調整,
                "年金雑": ctx.calc("所得税_公的年金等に係る雑所得の金額"),
                "支払者": 支払者,
                "全部源泉": ctx.calc("所得税_給与等の全部が源泉徴収の対象か"),
                "全部年調": ctx.calc("所得税_給与等の全部が年末調整の対象か"),
                "従たる給与": ctx.calc("所得税_従たる給与等の金額"),
                "従たる判明": ctx.calc("所得税_従たる給与等の金額が分かるか"),
                "年金全部": ctx.calc("所得税_公的年金等の全部が源泉徴収の対象か"),
                "除外": ctx.calc("所得税_給与等が第121条第1項の適用除外か"),
                "控除ロ": sum((ctx.calc(name) for name in LO_DEDUCTIONS), np.zeros(n, dtype=np.int64)),
            }
        )
    for pid, ob in zip(ctx.persons, obligations_of(v, p)):
        if ob.unresolved:
            yield Exclusion(pid, _reason("／".join(ob.unresolved)), "所得税_確定申告書の提出義務があるか")


CHECKS = (filing_obligation_undetermined,)
