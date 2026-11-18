"""中間表現から、判定の時の事実を取り出す道具（法令の値は持たない）。

2026-11-12：rules/personal_deductions/ir_facts.py から共有の場所（okura_core/dependents）に移した。扶養の割当て（所令218〜220・
地令46の3〜46の5）を所得税（personal_deductions）と住民税（juminzei）の両方から使うため（juminzei README JM-24〜26）。
personal_deductions/ir_facts.py は名前を写すだけのファイルとして残す。

判定の時（所得税法第85条第1項・第2項・第3項）：その年12月31日。その年の中途で死亡したときは死亡の日。
出国の時は、出国の年分を対象外にする（inputs.py）ので扱わない。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..registry import RECORD_SECTIONS, overlaps_year

#: 障害の根拠のうち、特別障害者に当たるかの程度を中間表現で決められないもの（checks.py が対象外にする）。
UNGRADED_SPECIAL_BASES = frozenset({"war_injury_certificate", "municipal_certification", "application"})
#: 学校教育法第1条の学校以外で、政令の課程の要件（所得税法施行令第11条の3第2項）を中間表現で確かめられない在学。
NON_ARTICLE1_SCHOOLS = frozenset({"specialized_training_college", "miscellaneous_school", "accredited_vocational_training"})
#: 親族・配偶者がありうる人の記録（その人が役割にある）。
KIN_RECORD_KINDS = ("parentage", "adoption", "marriage", "foster_placement")
#: 判断.住所の所在 の値。
DOMESTIC, FOREIGN = "domestic", "foreign"


def date_of(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def judgment_date(year: int, death_on: _dt.date | None) -> _dt.date:
    """判定の時：その年12月31日。その年の中途で死亡したときは死亡の日。"""
    end = _dt.date(year, 12, 31)
    if death_on is not None and death_on < end:
        return death_on
    return end


def departure_day(year: int, judgments: Iterable[Mapping[str, Any]], notices: Iterable[Mapping[str, Any]], person: str) -> _dt.date | None:
    """その年の中途の「出国」（所得税法第2条第1項第42号：納税管理人の届出をしないで国内に住所及び居所を有しないこととなること）の日。

    判断.住所の所在（person の判断）の国外の期間の最初の開始日 S が、その年の1月1日より後・12月31日まで（年の始めから国外なら出国の年でない）で、
    S までに納税管理人の選任の届出（tax_agent_notice の appointment）がなければ S。tax の inputs._departure_on と同じ読み（モジュールどうしは import しない）。
    """
    starts = [
        date_of(j["when"]["from_on"])
        for j in judgments
        if j["subject"]["person"] == person and j.get("value") == "foreign" and "from_on" in (j.get("when") or {})
    ]
    if not starts:
        return None
    s = min(starts)
    if not (_dt.date(year, 1, 1) < s <= _dt.date(year, 12, 31)):
        return None
    for n in notices:
        if n["roles"]["taxpayer"] == person and n["attributes"]["action"] == "appointment" and date_of(n["when"]["on"]) <= s:
            return None
    return s


def cut_date(death_on: _dt.date | None, departure: _dt.date | None) -> _dt.date | None:
    """判定の時を決める日（judgment_date に渡す）：死亡の日、出国の日の前日（「出国の時」の現況は国外へ移る前の日の現況と読む：法令の読み）の早い方。"""
    days = [d for d in (death_on, departure - _dt.timedelta(days=1) if departure is not None else None) if d is not None]
    return min(days) if days else None


def covers(when: Mapping[str, Any] | None, t: _dt.date) -> bool:
    """記録・判断の when が日 t を含むか。when がなければ含むとする。"""
    if not when:
        return True
    if "on" in when:
        return date_of(when["on"]) == t
    if "from_on" in when:
        a = date_of(when["from_on"])
        b = date_of(when["to_on"]) if when.get("to_on") else None
        return a <= t and (b is None or t <= b)
    if "tax_year" in when:
        return when["tax_year"] == t.year
    return True


def interval_in_year(when: Mapping[str, Any] | None, year: int, until: _dt.date) -> tuple[_dt.date, _dt.date] | None:
    """区間の when のうち、その年の1月1日から until（判定の時）までと重なる部分。重ならなければ None。"""
    start, end = _dt.date(year, 1, 1), until
    if not when:
        return (start, end)
    if "on" in when:
        d = date_of(when["on"])
        return (d, d) if start <= d <= end else None
    a = date_of(when["from_on"]) if "from_on" in when else start
    b = date_of(when["to_on"]) if when.get("to_on") else end
    lo, hi = max(a, start), min(b, end)
    return (lo, hi) if lo <= hi else None


def union_covers(intervals: Iterable[tuple[_dt.date, _dt.date]], target: tuple[_dt.date, _dt.date]) -> bool:
    """区間の和が target を全部覆うか（両端を含む日の区間）。"""
    cur = target[0]
    for a, b in sorted(intervals):
        if a > cur:
            break
        if b >= cur:
            cur = b + _dt.timedelta(days=1)
        if cur > target[1]:
            return True
    return cur > target[1]


class IrIndex:
    """中間表現の記録を、種類と人で引く索引（呼び出しごとに1回作る。人の数×記録の数の走査を避ける）。"""

    def __init__(self, ir: Mapping[str, Any]) -> None:
        self.ir = ir
        self._by_kind: dict[str, list[Mapping[str, Any]]] = {}
        self._by_person: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for section in RECORD_SECTIONS:
            for r in ir[section]:
                self._by_kind.setdefault(r["kind"], []).append(r)
                for pid in set(r.get("roles", {}).values()):
                    self._by_person.setdefault((r["kind"], pid), []).append(r)
        self._death = {p["id"]: (date_of(p["death_on"]) if p.get("death_on") else None) for p in ir["persons"]}
        self._households: dict[str, list[Mapping[str, Any]]] | None = None

    def of_kind(self, kind: str) -> list[Mapping[str, Any]]:
        return self._by_kind.get(kind, [])

    def of(self, kind: str, pid: str) -> list[Mapping[str, Any]]:
        """その人が（どれかの役割に）いる、その種類の記録（ID の順）。"""
        return sorted(self._by_person.get((kind, pid), []), key=lambda r: r["id"])

    def death(self, pid: str) -> _dt.date | None:
        return self._death[pid]

    def household(self, household_id: str) -> list[Mapping[str, Any]]:
        """同じ世帯の住民票の記録（resident_record の household_id）。"""
        if self._households is None:
            self._households = {}
            for r in self.of_kind("resident_record"):
                self._households.setdefault(r["attributes"]["household_id"], []).append(r)
        return self._households.get(household_id, [])


def disability_bases(idx: IrIndex, pid: str, t: _dt.date) -> list[Mapping[str, Any]]:
    """判定の時に有効な障害の根拠（disability_basis）。"""
    return [r for r in idx.of("disability_basis", pid) if covers(r.get("when"), t)]


def certificate_grade(bases: list[Mapping[str, Any]], basis: str) -> tuple[int, tuple[str, ...]]:
    """手帳の級（等級）：手帳がなければ0。最も重い級（小さい数）。級の記載のある手帳がなければ99（級が分からない）。

    級の記載のない手帳があり、記載のある級で特別障害者に当たらないときの対象外は checks.py が決める。
    返す値の2つ目は使った記録の ID。
    """
    recs = [r for r in bases if r["attributes"]["basis"] == basis]
    if not recs:
        return 0, ()
    grades = [r["attributes"]["grade"] for r in recs if "grade" in r["attributes"]]
    return (min(grades) if grades else 99), tuple(r["id"] for r in recs)


def enrollments(idx: IrIndex, pid: str, t: _dt.date) -> list[Mapping[str, Any]]:
    return [r for r in idx.of("enrollment", pid) if covers(r.get("when"), t)]


def kin_record_ids(idx: IrIndex, pid: str) -> tuple[str, ...]:
    """その人が役割にある親子・養子縁組・婚姻・里親委託の記録の ID（時を問わない）。

    親子関係の成立（when は出生の日）や過去に終わった婚姻も、その後の年分の扶養・寡婦・ひとり親の材料になる。
    """
    return tuple(sorted(r["id"] for kind in KIN_RECORD_KINDS for r in idx.of(kind, pid)))


def birthday_follows(birth: _dt.date, day: _dt.date) -> bool:
    """day の翌日が誕生日に応当する日（年齢が day の終了時に1つ加わる日）か。2月29日生まれは平年の3月1日の前日（2月28日）。"""
    nxt = day + _dt.timedelta(days=1)
    if (nxt.month, nxt.day) == (birth.month, birth.day):
        return True
    if (birth.month, birth.day) == (2, 29) and (nxt.month, nxt.day) == (3, 1):
        try:
            _dt.date(nxt.year, 2, 29)
        except ValueError:
            return True  # 平年：2月29日がないので、その月の末日（2月28日）の終了時に加わる（民法143②ただし書）
    return False


# ---------------------------------------------------------------------------
# 寡婦の「夫」（法令上の性別）・住民票の事実婚の続柄（inputs.py と checks.py が使う）
# ---------------------------------------------------------------------------

MALE, FEMALE = "male", "female"


def other_party(rec: Mapping[str, Any], pid: str) -> str:
    roles = rec["roles"]
    return roles["spouse_b"] if roles["spouse_a"] == pid else roles["spouse_a"]


def legal_sex_on(idx: IrIndex, pid: str, on: _dt.date) -> tuple[str | None, tuple[str, ...]]:
    """日 on の法令上の性別（legal_sex。期間つき）と使った記録の ID。記録がない・食い違うときは None。"""
    recs = [r for r in idx.of("legal_sex", pid) if covers(r.get("when"), on)]
    values = {r["attributes"]["sex"] for r in recs}
    return (values.pop() if len(values) == 1 else None), tuple(r["id"] for r in recs)


def marriage_ended_on(rec: Mapping[str, Any], other_death: _dt.date | None) -> _dt.date | None:
    """婚姻が離婚・死別で終わった日（終わっていなければ None）。"""
    w = rec.get("when") or {}
    end = date_of(w["to_on"]) if w.get("to_on") else None
    if other_death is not None and (end is None or other_death < end):
        return other_death
    return end


@dataclass(frozen=True)
class EndedMarriage:
    """判定の時までに離婚・死別で終わった婚姻1件と、相手が「夫」か（所得税法第2条第1項第30号）。

    husband：相手の法令上の性別（婚姻が終わった日の現況）が male なら True、female なら False、記録がなければ None。
    """

    record: Mapping[str, Any]
    divorced: bool
    husband: bool | None
    sex_ids: tuple[str, ...]


def ended_marriages(idx: IrIndex, pid: str, t: _dt.date) -> list[EndedMarriage]:
    """判定の時 t に婚姻していない人の、t までに離婚・死別で終わった婚姻（判定の時に続いている婚姻があれば空）。"""
    mine = idx.of("marriage", pid)
    for r in mine:
        other_death = idx.death(other_party(r, pid))
        if covers(r.get("when"), t) and (other_death is None or other_death >= t):
            return []
    out: list[EndedMarriage] = []
    for r in mine:
        other = other_party(r, pid)
        other_death = idx.death(other)
        ended = marriage_ended_on(r, other_death)
        if ended is None or ended > t:
            continue
        by = r.get("attributes", {}).get("ended_by")
        if by == "divorce":
            divorced = True
        elif by == "death" or (other_death is not None and other_death == ended):
            divorced = False
        else:
            continue
        sex, sex_ids = legal_sex_on(idx, other, ended)
        out.append(EndedMarriage(r, divorced, None if sex is None else sex == MALE, sex_ids))
    return out


@dataclass(frozen=True)
class Cohabitation:
    """判定の時の住民票の事実婚の続柄（所規1の3・1の4）。unknown は、記載を確かめられない（住民票の記録がない・続柄の記載がない）。"""

    found: bool
    ids: tuple[str, ...]
    records: tuple[Mapping[str, Any], ...]
    unknown: bool


def cohabitation(idx: IrIndex, pid: str, t: _dt.date) -> Cohabitation:
    own = [r for r in idx.of("resident_record", pid) if covers(r.get("when"), t)]
    if not own:
        return Cohabitation(False, (), (), True)
    ids: list[str] = [r["id"] for r in own]
    found = False
    unknown = False
    for r in own:
        attrs = r["attributes"]
        if attrs["householder"]:
            for other in idx.household(attrs["household_id"]):
                if (
                    other["roles"]["person"] != pid
                    and covers(other.get("when"), t)
                    and other["attributes"].get("relation_to_householder") == "unregistered_spouse"
                ):
                    found = True
                    ids.append(other["id"])
        else:
            rel = attrs.get("relation_to_householder")
            if rel is None:
                unknown = True
            elif rel == "unregistered_spouse":
                found = True
    return Cohabitation(found, tuple(ids), tuple(own), unknown and not found)


# ---------------------------------------------------------------------------
# 配偶者の生死が明らかでない者（所得税法施行令第11条・第11条の2第1項）
# ---------------------------------------------------------------------------

#: 所令11 第1号・第2号の事由（太平洋戦争の終結の当時もとの陸海軍に属していてまだ国内に帰らない者・同様の事情で国外にあってまだ帰らない者）。
WAR_CIRCUMSTANCES = frozenset({"former_military_not_returned", "abroad_since_war_not_returned"})


def add_months_clamped(day: _dt.date, months: int) -> _dt.date:
    """day の months 月後の応当する日（応当する日がなければその月の末日：民法第143条第2項ただし書）。"""
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    for d in (day.day, 30, 29, 28):
        try:
            return _dt.date(year, month, min(day.day, d))
        except ValueError:
            continue
    raise ValueError(day)


def period_elapsed(start: _dt.date, months: int, t: _dt.date, at_day_end: bool) -> bool:
    """start（事故・危難の日など。初日不算入：民法第140条）から months 月の期間が判定の時 t までに満了したか。

    期間の末日は start の応当する日（民法第143条第2項）。その日の終了で満了するので、判定の時がその日の途中（死亡の時）なら満了していない。
    """
    end = add_months_clamped(start, months)
    return t > end or (t == end and at_day_end)


@dataclass(frozen=True)
class MissingSpouse:
    """判定の時に続いている婚姻で、配偶者の生死が明らかでないもの1件（所令11 の各号に当たるか）。

    applies：当たる True・当たらない False・中間表現の語で決まらない None（needs に入力すれば決まる欄）。husband：相手の法令上の性別が male か（記録がなければ None）。
    """

    record: Mapping[str, Any]
    applies: bool | None
    needs: str
    husband: bool | None
    sex_ids: tuple[str, ...]


def missing_spouse_applies(sm: Mapping[str, Any], t: _dt.date, at_day_end: bool) -> tuple[bool | None, str]:
    """所令11：一・二 戦争の事由、三 船舶・航空機の事故で3月以上、四 危難が去った後1年以上、五 3年以上 生死が明らかでない。"""
    since = date_of(sm["since_on"])
    circ = sm.get("circumstance")
    if circ in WAR_CIRCUMSTANCES:
        return True, ""
    if period_elapsed(since, 36, t, at_day_end):  # 第5号（どの事由でも当たる）
        return True, ""
    if circ == "vessel_or_aircraft_accident":
        return period_elapsed(since, 3, t, at_day_end), ""
    if circ == "peril":
        if "peril_ended_on" in sm:
            return period_elapsed(date_of(sm["peril_ended_on"]), 12, t, at_day_end), ""
        if not period_elapsed(since, 12, t, at_day_end):  # 危難が去った日は遭遇した日より後なので、1年は経っていない
            return False, ""
        return None, "spouse_missing.peril_ended_on（危難が去った日。所令11 第4号）"
    if circ == "other":
        return False, ""
    if not period_elapsed(since, 3, t, at_day_end):  # 第3号〜第5号のどれも3月未満では当たらない（第1号・第2号は事由の記載が要る）
        return False, ""
    return None, "spouse_missing.circumstance（生死が明らかでない事由。所令11 の各号）"


def missing_spouses(idx: IrIndex, pid: str, t: _dt.date) -> list[MissingSpouse]:
    """判定の時 t に続いている婚姻のうち、配偶者の生死が明らかでない記録のあるもの。"""
    death = idx.death(pid)
    at_day_end = death is None or death != t
    out: list[MissingSpouse] = []
    for r in idx.of("marriage", pid):
        sm = r.get("attributes", {}).get("spouse_missing")
        if sm is None:
            continue
        other = other_party(r, pid)
        other_death = idx.death(other)
        if not covers(r.get("when"), t) or (other_death is not None and other_death < t):
            continue
        if date_of(sm["since_on"]) > t:
            continue
        applies, needs = missing_spouse_applies(sm, t, at_day_end)
        sex, sex_ids = legal_sex_on(idx, other, t)
        out.append(MissingSpouse(r, applies, needs, None if sex is None else sex == MALE, sex_ids))
    return out


# ---------------------------------------------------------------------------
# 特別障害者の程度の記載（所令10②四・六、所基通2−38）・勤労学生の専修学校等（所法2①三十二ロ・ハ、所令11の3）
# ---------------------------------------------------------------------------

#: 恩給法別表第一号表ノ二の特別項症から第三項症まで（所令10②四）。中間表現の war_injury_class の値。
WAR_SPECIAL_CLASSES = frozenset({"special_item", "item_1", "item_2", "item_3"})
#: 所法2①三十二ロの設置者のうち、法律に書かれたもの（国・地方公共団体・学校法人等）。
LISTED_ESTABLISHERS = frozenset({"national", "local_government", "school_corporation"})


def war_special(r: Mapping[str, Any]) -> bool | None:
    """戦傷病者手帳（又はその申請）の程度が特別項症〜第三項症か。記載がなければ None。"""
    c = r["attributes"].get("war_injury_class")
    return None if c is None else c in WAR_SPECIAL_CLASSES


def application_special(r: Mapping[str, Any], physical_max: int) -> bool | None:
    """手帳の申請中の程度が明らかに特別障害者の程度か（所基通2−38：身体障害者手帳の1級・2級〔grade〕、戦傷病者手帳の特別項症〜第三項症）。

    所基通2−38 は身体障害者手帳・戦傷病者手帳についての通達なので、申請の grade は身体障害者手帳の級と読む（法令の読み）。記載がなければ None。
    """
    a = r["attributes"]
    w = war_special(r)
    if w is True or ("grade" in a and 1 <= a["grade"] <= physical_max):
        return True
    if w is None and "grade" not in a:
        return None
    return False


def course_student(r: Mapping[str, Any]) -> tuple[bool | None, str]:
    """専修学校・各種学校（所法2①三十二ロ）・認定職業訓練（ハ）の在学が、政令で定める課程を履修する学生等に当たるか。

    課程の要件（所令11の3②）は学校の長等から交付を受けた大臣の証明（所規47の2⑪）の有無で受ける（zeigaku-calc-model H3）。
    設置者は法律に書かれた者（国・地方公共団体・学校法人等）か、大臣の定める基準を満たす旨の証明（所令11の3①二）があれば当たる。
    決まらなければ None と、入力すれば決まる欄。
    """
    a = r["attributes"]
    st = a["school_type"]
    if st not in ("specialized_training_college", "miscellaneous_school", "accredited_vocational_training"):
        return False, ""
    needs: list[str] = []
    if st != "accredited_vocational_training":
        est = a.get("establisher_type")
        if est in LISTED_ESTABLISHERS or a.get("establisher_certificate") is True:
            pass
        elif est == "other":
            return False, ""
        elif est is None:
            needs.append("establisher_type（設置者）")
        else:  # other_corporation：所令11の3①一の法人（日本赤十字社・社会福祉法人など）か、①二の基準の証明があるか
            needs.append("establisher_certificate（設置者が基準を満たす旨の大臣の証明。所令11の3①一の法人かは語彙にない）")
    cc = a.get("course_certificate")
    if cc is False:
        return False, ""
    if cc is None:
        needs.append("course_certificate（課程が所令11の3②に当たる旨の大臣の証明）")
    if needs:
        return None, "・".join(needs)
    return True, ""


# ---------------------------------------------------------------------------
# 非居住者の期間と所得の記録（inputs.py・allocation.py・checks.py が使う）
# ---------------------------------------------------------------------------

J_ADDRESS_KIND = "判断.住所の所在"


def _record_in_year(rec: Mapping[str, Any], year: int) -> bool:
    w = rec.get("when") or {}
    if "tax_year" in w:
        return w["tax_year"] == year
    if "fiscal_year" in w:
        return w["fiscal_year"] in (year, year + 1)
    if rec["kind"] == "filed_document":
        return rec.get("attributes", {}).get("tax_year") in (None, year)
    return overlaps_year(w, year)


def income_record_ids(ir: Mapping[str, Any], pid: str, year: int) -> tuple[str, ...]:
    """その年分の、その人が当事者の所得に関係しうる記録（scope.INCOME_RELATED_RECORD_KINDS）の ID。"""
    from ..scope import INCOME_RELATED_RECORD_KINDS  # noqa: PLC0415

    out = []
    for sec in ("facts", "assets", "filed_documents"):
        for r in ir[sec]:
            if r["kind"] in INCOME_RELATED_RECORD_KINDS and pid in r.get("roles", {}).values() and _record_in_year(r, year):
                out.append(r["id"])
    return tuple(sorted(out))


def foreign_period_ids(ir: Mapping[str, Any], pid: str, year: int, t: _dt.date) -> tuple[str, ...]:
    """その年の1月1日から判定の時 t までに、住所が国外と判断された期間（非居住者の期間）がある判断の ID。"""
    from ..registry import heads  # noqa: PLC0415

    out = []
    for j in heads(r for r in ir["judgments"] if r["kind"] == J_ADDRESS_KIND):
        if j["subject"]["person"] == pid and j.get("value") == FOREIGN and interval_in_year(j.get("when"), year, t) is not None:
            out.append(j["id"])
    return tuple(sorted(out))


def nonresident_income_split(pid: str, ids: Iterable[str]) -> Any:
    """非居住者の期間がある親族の合計所得金額の読みの分かれ目（impl-research3 H2：(a) 国内源泉所得だけ、(b) 全世界の所得。D22 S1 の同程度の支え）。

    (b) は所得の記録から計算できるが、(a) の値は計算しない（outcomes は空）。判断.国内源泉所得の内訳 で国内源泉所得以外の所得が0なら、
    読みで値が分かれないので分かれ目にしない（allocation._no_non_domestic_income）。
    """
    from ..result import Means, Split  # noqa: PLC0415

    return Split(
        id=f"読み:非居住者の親族の合計所得金額:{pid}",
        means=Means.PRIMARY_SOURCE,
        target={
            "person": pid,
            "記録": sorted(set(ids)),
            "理由": (
                "非居住者の期間がある親族の合計所得金額を国内源泉所得だけで計算するか（所法7①三・165①）、全世界の所得で計算するか（所法2①三十ロ(2)・22）"
                "を決める一次情報が docs にない。非居住者の期間の国内源泉所得以外の所得の金額（判断.国内源泉所得の内訳）が0なら読みで分かれない"
            ),
        },
        candidates=("国内源泉所得だけ", "全世界の所得"),
        splits_conclusion=True,
    )
