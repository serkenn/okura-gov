"""扶養親族等・配偶者として判定される人の、判定する人の判定の時の現況（2026-11-12。personal_deductions PD-05・juminzei JM-24〜26）。

所得税法第85条第3項：扶養親族等に該当するかの判定は、その年12月31日（その居住者がその年の中途で死亡し又は出国をする場合は、その死亡又は出国の時）の
現況による（判定される人が既に死亡していれば死亡の時）。personal_deductions の入力は、人ごとに「その人自身の判定の時」の現況（年齢・住所・障害）を
1つずつ持つ。判定する人の判定の時が違う（出国する人を出国しない居住者が判定する・年の中途で死亡した人が判定する）ときは、判定される人の現況を
判定する人の判定の時で取り出す必要がある（以前は対象外：PD-05 の残り）。ここは、その現況を中間表現から取り出す純粋関数。

式（personal_deductions の classify.py・facts.py・inputs.py）と同じ材料・同じ向きで書く：年齢は判定の日の終了時（年齢計算ニ関スル法律）、
住所は 判断.住所の所在（なければ国外の滞在の記録。どちらもなければ国内）、障害者・特別障害者は所得税法施行令第10条の区分の論理和。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..registry import heads
from ..result import Means, Split, State
from .ir_facts import (
    FOREIGN,
    IrIndex,
    application_special,
    certificate_grade,
    covers,
    disability_bases,
    war_special,
)
from .kinship import age_on

K_ADDRESS = "判断.住所の所在"
K_DISABILITY = "判断.障害の程度"
ASPECT_LACKS_CAPACITY = "lacks_capacity"
ASPECT_SEVERE = "severe_intellectual_disability"
ASPECT_BEDRIDDEN = "bedridden_requiring_complex_care"
ASPECT_PENDING = "evidently_disabled_pending_application"
#: 判断.障害の程度 の側面と、判断が未入力でも分かれ目にする材料の記録の根拠（personal_deductions/inputs.py の ASPECT_TRIGGERS と同じ）。
ASPECT_TRIGGERS: Mapping[str, str | None] = {
    ASPECT_LACKS_CAPACITY: None,
    ASPECT_SEVERE: "intellectual_disability_assessment",
    ASPECT_BEDRIDDEN: None,
    ASPECT_PENDING: "application",
}


@dataclass(frozen=True)
class DisabilityLimits:
    """障害者・特別障害者の区分の基準（パラメータの値を呼ぶ側が渡す：所得税.障害者・所得税.特別障害者）。"""

    municipal_age_min: int
    physical_special_max: int
    mental_special_grade: int


@dataclass(frozen=True)
class PersonAt:
    """ある日の現況。resident・disabled・special が None なら中間表現で決まらない（missing に分かれ目）。"""

    on: _dt.date
    age: int
    resident: bool | None
    study_abroad: bool
    disabled: bool | None
    special: bool | None
    ids: tuple[str, ...]
    states: frozenset[State]
    missing: tuple[Split, ...]


def _marks(records: Iterable[Mapping[str, Any]]) -> frozenset[State]:
    return frozenset(State.from_mark(r["mark"]) for r in records if "mark" in r)


def residence_at(ir: Mapping[str, Any], idx: IrIndex, pid: str, t: _dt.date) -> tuple[bool | None, bool, list[Mapping[str, Any]]]:
    """t の日に国内に住所があるか（判断.住所の所在 がそろっていればその値、判断がなく国外の滞在もなければ国内、それ以外は None）と、留学か。"""
    js = [j for j in heads(r for r in ir["judgments"] if r["kind"] == K_ADDRESS) if j["subject"]["person"] == pid and covers(j.get("when"), t)]
    stays = [r for r in idx.of("abroad_stay", pid) if covers(r.get("when"), t)]
    study = any(r["attributes"]["purpose"] == "study" for r in stays)
    values = {j.get("value") for j in js}
    if len(values) == 1:
        return values.pop() != FOREIGN, study, [*js, *stays]
    if not js and not stays:
        return True, False, []
    return None, study, [*js, *stays]


def disability_at(
    ir: Mapping[str, Any], idx: IrIndex, pid: str, t: _dt.date, age: int, lim: DisabilityLimits
) -> tuple[bool | None, bool | None, list[Mapping[str, Any]], list[Split]]:
    """t の日の障害者・特別障害者の区分（所令10①②。classify.py の式と同じ論理和）と、使った記録・判断、決まらない側面の分かれ目。"""
    bases = disability_bases(idx, pid, t)
    used: list[Mapping[str, Any]] = list(bases)
    missing: list[Split] = []
    aspects: dict[str, bool | None] = {}
    judged = [j for j in heads(r for r in ir["judgments"] if r["kind"] == K_DISABILITY) if j["subject"]["person"] == pid and covers(j.get("when"), t)]
    for aspect, trigger in ASPECT_TRIGGERS.items():
        js = [j for j in judged if j["value"]["aspect"] == aspect]
        values = {bool(j["value"]["applies"]) for j in js}
        if len(values) == 1:
            aspects[aspect] = values.pop()
            used += js
        elif js or (trigger is not None and any(r["attributes"]["basis"] == trigger for r in bases)):
            aspects[aspect] = None
            missing.append(
                Split(
                    id=f"判断:判定の時の障害の程度:{pid}:{aspect}:{t.isoformat()}",
                    means=Means.JUDGMENT,
                    target={"person": pid, "on": t.isoformat(), "aspect": aspect, "入力": "その日を覆う 判断.障害の程度"},
                    candidates=("true", "false"),
                    splits_conclusion=True,
                )
            )
        else:
            aspects[aspect] = False
    physical, _ = certificate_grade(bases, "physical_disability_certificate")
    mental, _ = certificate_grade(bases, "mental_disability_certificate")
    kinds = {r["attributes"]["basis"] for r in bases}
    municipal = "municipal_certification" in kinds and age >= lim.municipal_age_min
    municipal_special = age >= lim.municipal_age_min and any(
        r["attributes"]["basis"] == "municipal_certification" and r["attributes"].get("certified_severity") == "severe" for r in bases
    )
    war_sp = any(r["attributes"]["basis"] == "war_injury_certificate" and war_special(r) is True for r in bases)
    app_sp = any(r["attributes"]["basis"] == "application" and application_special(r, lim.physical_special_max) is True for r in bases)

    def known(*xs: bool | None) -> bool | None:
        if any(x is True for x in xs):
            return True
        return None if any(x is None for x in xs) else False

    disabled = known(
        physical > 0,
        mental > 0,
        "intellectual_disability_assessment" in kinds,
        aspects[ASPECT_SEVERE],
        aspects[ASPECT_LACKS_CAPACITY],
        "war_injury_certificate" in kinds,
        "atomic_bomb_survivor_certification" in kinds,
        aspects[ASPECT_BEDRIDDEN],
        municipal,
        aspects[ASPECT_PENDING],
    )
    pending_special = None if aspects[ASPECT_PENDING] is None else (aspects[ASPECT_PENDING] and app_sp)
    special = known(
        1 <= physical <= lim.physical_special_max,
        war_sp,
        municipal_special,
        pending_special,
        mental == lim.mental_special_grade,
        aspects[ASPECT_SEVERE],
        aspects[ASPECT_LACKS_CAPACITY],
        "atomic_bomb_survivor_certification" in kinds,
        aspects[ASPECT_BEDRIDDEN],
    )
    return disabled, special, used, missing


def judgment_day(t: _dt.date, death: _dt.date | None) -> _dt.date:
    """年齢を数える日：判定の時が死亡の時なら前日の終了時（personal_deductions の 所得税_年齢 と同じ読み：impl-research3 H6）。"""
    return t - _dt.timedelta(days=1) if death is not None and death == t else t


def person_at(
    ir: Mapping[str, Any], idx: IrIndex, pid: str, birth: _dt.date, t: _dt.date, age_day: _dt.date, lim: DisabilityLimits
) -> PersonAt:
    """pid の t の日の現況（年齢は age_day の終了時）。"""
    age = age_on(birth, age_day)
    resident, study, rec_r = residence_at(ir, idx, pid, t)
    disabled, special, rec_d, missing = disability_at(ir, idx, pid, t, age, lim)
    if resident is None:
        missing = [
            *missing,
            Split(
                id=f"判断:判定の時の住所の所在:{pid}:{t.isoformat()}",
                means=Means.JUDGMENT,
                target={"person": pid, "on": t.isoformat(), "入力": "その日を覆う 判断.住所の所在（国外の滞在があり、判断がないか食い違う）"},
                candidates=("domestic", "foreign"),
                splits_conclusion=True,
            ),
        ]
    recs = [*rec_r, *rec_d]
    return PersonAt(
        on=t,
        age=age,
        resident=resident,
        study_abroad=bool(study) and resident is False,
        disabled=disabled,
        special=special,
        ids=tuple(sorted({r["id"] for r in recs})),
        states=_marks(recs),
        missing=tuple(missing),
    )


def limits_from(parameters: Any) -> DisabilityLimits:
    """所得税のパラメータ（その年分）から障害者・特別障害者の基準を取り出す。"""
    p = parameters.所得税
    return DisabilityLimits(
        municipal_age_min=int(p.障害者.市町村長等の認定の年齢の下限),
        physical_special_max=int(p.特別障害者.身体障害者手帳の級の上限),
        mental_special_grade=int(p.特別障害者.精神障害者保健福祉手帳の等級),
    )


__all__ = ["DisabilityLimits", "PersonAt", "disability_at", "judgment_day", "limits_from", "person_at", "residence_at"]
