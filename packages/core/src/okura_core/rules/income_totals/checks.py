"""規則モジュール income_totals の計算の後の対象外の検出（安全側。黙って近似しない）。

繰り戻す純損失の金額が前年分の課税総所得金額を超える場合（残りは課税山林所得金額、次に課税退職所得金額から控除する：所令271①三）：
- 前年分の課税山林所得金額が正：山林所得は範囲外（D20）なので、還付請求額を対象外（範囲外）にする。
- 前年分の申告書に課税退職所得金額・課税山林所得金額の記載（0 を含む）がない：控除先が決まらない（0 か書き忘れかを区別できない）ので対象外にする。

実装した不動産所得の損益通算の制限・雑損失の繰越控除の順序・所得金額調整控除の第1項の検出は外した（2026-11-11）。
"""

from __future__ import annotations

from collections.abc import Iterator

from ...registry import CheckContext, Exclusion
from ...result import OutOfScopeCategory, OutOfScopeReason

_AO = "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md §5.3"
CARRYBACK_REASON = (
    "繰り戻す純損失の金額が前年分の課税総所得金額を超える。残りを控除する前年分の課税山林所得金額・課税退職所得金額（所令271①三："
    f"{_AO}）の記載（taxable_timber_income・taxable_retirement_income。ないなら0と書く）が前年分の申告書にないので、還付請求額を決められない"
)
CARRYBACK_TIMBER_REASON = (
    "繰り戻す純損失の金額が前年分の課税総所得金額を超え、前年分に課税山林所得金額がある。残りはまず課税山林所得金額から控除する（所令271①三："
    f"{_AO}）が、山林所得は範囲外（D20・SCOPE §4）"
)


def carryback_exceeds_taxable(ctx: CheckContext) -> Iterator[Exclusion]:
    net = ctx.calc("所得税_純損失の金額")
    chosen = ctx.calc("所得税_繰り戻す純損失の金額の選択")
    prev = ctx.calc("所得税_前年分の課税総所得金額")
    blue = ctx.calc("所得税_青色申告の承認を受けているか")
    prev_blue = ctx.calc("所得税_前年分に青色申告書を提出したか")
    timely = ctx.calc("所得税_その年分の確定申告書を期限内に提出するか")
    timber = ctx.calc("所得税_前年分の課税山林所得金額")
    stated = ctx.calc("所得税_前年分の課税退職所得金額等の記載があるか")
    for i, pid in enumerate(ctx.persons):
        if not (bool(blue[i]) and bool(prev_blue[i]) and bool(timely[i]) and min(int(chosen[i]), int(net[i])) > int(prev[i])):
            continue
        if int(timber[i]) > 0:
            yield Exclusion(pid, OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, CARRYBACK_TIMBER_REASON), "所得税_純損失の繰戻しによる還付請求額")
        elif not bool(stated[i]):
            yield Exclusion(pid, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, CARRYBACK_REASON), "所得税_純損失の繰戻しによる還付請求額")


CHECKS = (carryback_exceeds_taxable,)
