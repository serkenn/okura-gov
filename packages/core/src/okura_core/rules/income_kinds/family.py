"""青色事業専従者給与・事業専従者控除（所法57）と、生計を一にする親族への対価（所法56）の判定の材料。

- 青色：所法57①。親族（生計を一にする・15歳以上）で専らその事業に従事する者への給与で、届出の範囲内で相当なものを必要経費に算入する。
- 白色：所法57③。事業専従者控除額（配偶者86万円・ほか50万円と、事業の所得 ÷（専従者の数＋1）の低い方）。専従者の側では給与の収入金額とみなす（第4項）。
  限度の除算の1円未満は根拠のない端数の候補（fudosan §9-3）。
- 専ら従事するか：従事の記録（business_engagement）の期間がその年を通じて6月を超えるか（所令165①本文。年の途中の開業等で期間が短くなる場合〔ただし書〕は対象外）。
- 事業に限る（所法56・57「不動産所得、事業所得又は山林所得を生ずべき事業」。業務に係る雑所得には適用がない）。事業的規模でない不動産所得には適用がない（fudosan §3.2）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from typing import Any

from ...registry import DecisionSlot, YearContext
from .common import add_months, calendar_months, date_of

K_SEIKEI = "判断.生計を一にする"
K_REASONABLE = "判断.専従者給与の相当性"


def pair_key(a: str, b: str) -> str:
    """生計を一にするかの1か所の key（personal_deductions と同じ：2人の ID の小さい方:大きい方。同じ組は同じ1か所）。"""
    return f"{min(a, b)}:{max(a, b)}"


def seikei_slots(ctx: YearContext, pairs: Iterable[tuple[str, str]]) -> list[DecisionSlot]:
    """専従者・家族への支払の判定に使う生計を一にするかの1か所（personal_deductions が同じ組を宣言していれば、そちらの1か所になる）。"""
    out = []
    for a, b in sorted({tuple(sorted(p)) for p in pairs}):
        out.append(
            DecisionSlot(
                key=pair_key(a, b),
                target={"person": a, "other_person": b, "tax_year": ctx.year},
                matches=lambda rec, a=a, b=b: {rec["subject"].get("person"), rec["subject"].get("other_person")} == {a, b},
                persons=(a, b),
            )
        )
    return out


def age_on(ctx: YearContext, pid: str, on: _dt.date) -> int:
    b = ctx.birth_on(pid)
    return on.year - b.year - (0 if (on.month, on.day) >= (b.month, b.day) else 1)


def is_spouse(ctx: YearContext, a: str, b: str, on: _dt.date) -> bool:
    return any(r.other == b for r in ctx.relations.spouses(a, on))


def is_relative(ctx: YearContext, a: str, b: str, on: _dt.date) -> bool:
    """親族（婚姻・親子などの関係の記録でたどれる人）か。親等の精密な判定は personal_deductions（読みの印：basis.FAMILY）。"""
    if is_spouse(ctx, a, b, on):
        return True
    return any(p.person == b for p in ctx.relations.kin(a, on))


def engagement_months(ctx: YearContext, employer: str, employee: str, bid: str) -> tuple[int, list[str], bool]:
    """その年中の従事の月数（暦に従い1月未満は1月）と記録。ただし書の事由（interruption_reason）があるかも返す。"""
    recs = sorted(
        (
            r
            for r in ctx.records("business_engagement")
            if r["roles"]["business_owner"] == employer and r["roles"]["relative"] == employee and r["attributes"]["business_id"] == bid
        ),
        key=lambda r: r["id"],
    )
    months = 0
    ids: list[str] = []
    interrupted = False
    y0, y1 = _dt.date(ctx.year, 1, 1), _dt.date(ctx.year, 12, 31)
    for r in recs:
        a = max(date_of(r["when"]["from_on"]), y0)
        b = min(date_of(r["when"]["to_on"]) if r["when"].get("to_on") else y1, y1)
        if a > b:
            continue
        months += calendar_months(a, b)
        ids.append(r["id"])
        interrupted = interrupted or bool(r["attributes"].get("interruption_reason"))
    return min(months, 12), ids, interrupted


def notice_deadline(ctx: YearContext, notice: Mapping[str, Any]) -> _dt.date:
    """届出の期限（所法57②・所規36の4③：その年3月15日。その年1月16日以後に専従者を有することとなった〔started_on〕なら、その日から2月以内）。"""
    base = _dt.date(ctx.year, 3, 15)
    started = notice["attributes"].get("started_on")
    if started:
        on = date_of(started)
        if on >= _dt.date(ctx.year, 1, 16):
            return max(base, add_months(on, 2))
    return base


def within_notice(ctx: YearContext, employer: str, employee: str) -> tuple[bool, list[str], int | None]:
    """届出（family_employee_notice）が期限までにあるか。戻り値：(届出済みか, 記録, 届出の月額)。"""
    recs = sorted(
        (r for r in ctx.records("family_employee_notice") if r["roles"]["employer"] == employer and r["roles"]["employee"] == employee),
        key=lambda r: (r["when"]["on"], r["id"]),
    )
    filed = [r for r in recs if date_of(r["when"]["on"]) <= notice_deadline(ctx, r)]
    if not filed:
        return False, [r["id"] for r in recs], None
    return True, [r["id"] for r in filed], filed[-1].get("amounts", {}).get("monthly_salary")


__all__ = ["K_REASONABLE", "K_SEIKEI", "age_on", "pair_key", "engagement_months", "is_relative", "is_spouse", "notice_deadline", "seikei_slots", "within_notice"]
