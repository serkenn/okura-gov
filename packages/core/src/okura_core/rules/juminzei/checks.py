"""規則モジュール juminzei の計算の後の対象外の検出（黙って近似しない）。

- 退職所得：源泉徴収の対象でない退職手当等を含む人（分離課税と総合課税に分ける材料がない）、損益通算で退職所得金額が退職所得の金額と違う人
  （住民税では分離課税に係る退職所得に損失を通算しない）。
- 公的年金等控除の「公的年金等に係る雑所得以外の合計所得金額」の区分が、分離課税に係る退職所得を除くと変わる人（施行令第48条の5の2 の読替え）。
（2026-11-12：所得控除が総所得金額を超え上場株式等の分離課税の所得がある人は段 住民税の分離課税の所得への所得控除〔separate.py〕、
特例控除対象寄附金と分離課税の所得がある人は附則第5条の5〔calc.special_ratio_with_separate〕で計算するようにし、検出を外した。）
"""

from __future__ import annotations

from collections.abc import Iterator

from ...registry import CheckContext, Exclusion
from ...result import OutOfScopeCategory, OutOfScopeReason

MIXED_RETIREMENT = "源泉徴収の対象でない退職手当等がある（総合課税になる退職所得と分離課税に係る退職所得を分ける材料がない）"
OFFSET_RETIREMENT = "損益通算などで所得税の退職所得金額が退職所得の金額と違う（住民税では分離課税に係る退職所得に損失を通算しないので、総所得金額が変わる）"
PENSION_THRESHOLD = (
    "公的年金等控除額の区分（公的年金等に係る雑所得以外の合計所得金額：1,000万円・2,000万円）が、分離課税に係る退職所得を除く住民税の定義"
    "（地方税法施行令第48条の5の2）で変わる。住民税の公的年金等控除額を計算し直す実装をしていない"
)


def _reason(text: str) -> OutOfScopeReason:
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, text, ())


def retirement_checks(ctx: CheckContext) -> Iterator[Exclusion]:
    retire = ctx.calc("所得税_退職所得金額")
    if not (retire != 0).any():
        return
    kind = ctx.calc("所得税_退職所得の金額")
    whole = ctx.calc("所得税_退職手当等の全部が源泉徴収の対象か")
    for i, pid in enumerate(ctx.persons):
        if int(retire[i]) == 0 and int(kind[i]) == 0:
            continue
        if not bool(whole[i]):
            yield Exclusion(pid, _reason(MIXED_RETIREMENT), "住民税_分離課税に係る退職所得の金額")
        elif int(retire[i]) != int(kind[i]):
            yield Exclusion(pid, _reason(OFFSET_RETIREMENT), "住民税_分離課税に係る退職所得の金額")


def pension_threshold_check(ctx: CheckContext) -> Iterator[Exclusion]:
    retire = ctx.calc("所得税_退職所得金額")
    if not (retire > 0).any():
        return
    pension = ctx.calc("所得税_公的年金等の収入金額")
    other = ctx.calc("所得税_公的年金等に係る雑所得以外の合計所得金額")
    q = ctx.parameters.所得税.公的年金等控除額.区分
    lines = (int(q.第1号の上限), int(q.第2号の上限))
    for i, pid in enumerate(ctx.persons):
        r, o = int(retire[i]), int(other[i])
        if r > 0 and int(pension[i]) > 0 and any(o - r <= t < o for t in lines):
            yield Exclusion(pid, _reason(PENSION_THRESHOLD), "住民税_合計所得金額")


#: 2026-11-12：retirement_checks（JM-19・JM-20）と pension_threshold_check（JM-23）は、income_totals・income_kinds の窓口
#: （分離課税に係る退職所得を除いた所得の合計・公的年金等に係る雑所得の金額）で計算するようにして外した。混在（JM-19）は inputs._retirement_split の分かれ目。
CHECKS: tuple = ()
