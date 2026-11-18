"""規則モジュール kokunen：年度 F の月ごとの事実（学生等である月・産前産後と育児期間の免除の月・付加保険料を納付できる月）。

出典（docs/public-sources/20261111_impl-research3_kokunen-laws.md。以下 [PS3-KN]）と、原文の取得
（scripts/results/IMPL3_egov_fetch/kokunen/kokunen_2027-04-01.txt の Num=87_2・88_2・88_3・89・90、grep_kokunenrei_2027-04-01.txt の Num=6_6）：
  - 学生等（国年法第90条第1項柱書のかっこ書き・第90条の2・第90条の3、国年令第6条の6）：[PS3-KN] §2
  - 付加保険料（国年法第87条の2：月400円。第89条・第90条・第90条の3・第90条の2・国民年金基金の加入員を除く。産前産後・育児期間の月は納付できる）：[PS3-KN] §3
  - 産前産後（国年法第88条の2：出産予定月の前月〔多胎は3月前〕から翌々月まで。国年規第73条の6：届出の前に出産したときは出産の日）：[PS3-KN] §4
  - 育児期間（国年法第88条の3。令和6年法律第47号、2026-10-01 施行。附則第10条：令和8年10月以後の各月の保険料に適用）：[PS3-KN] §4、
    docs/public-sources/20261112_impl-research4_kokunen-laws.md §2（以下 [PS4-KN]）。期間の計算は民法第143条
    （docs/public-sources/20261109_R1-laws_social-insurance-age-records.md §3）
  - 法定免除（国年法第89条第1項：該当するに至った日の属する月の前月から該当しなくなる日の属する月まで）：原文 Num=89。
    第1号の政令で定める給付・除かれる者は国年令第6条の5第1項・第2項（[PS4-KN] §3）
  - 学生等の第10号の教育施設（国年則第77条の6。日本年金機構の学生納付特例対象校一覧）：[PS4-KN] §1

月の数え方（法令の読み）：年度の各月について、その月の末日の状態で決める（第1号被保険者か・承認された免除の期間か）。
在学の始まり・終わりが月の途中にある月は、数えるかを決める一次情報が docs にないので分かれ目にする（一次情報）。
第10号の教育施設は学生納付特例対象校一覧の欄（npi_student_school_listed）で決め、欄がなければ分かれ目（事実）。
OpenFisca を知らない。中間表現の記録を読む純粋関数だけ。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...registry import YearContext
from ...result import Means, Split, State

Month = tuple[int, int]

#: 国年法第88条の3 の施行日（令和6年法律第47号附則第1条第6号ロ）。附則第10条により、令和8年10月以後の各月の保険料に当てる
#: （出産・養育の開始の日で区切らない。[PS4-KN] §2、仮説 docs/hypotheses/20261112_impl-research4_all-model.md H5）。
CHILDCARE_FROM = _dt.date(2026, 10, 1)

#: 国年令第6条の6 に当たる学校の種類（中間表現の enrollment.school_type）。
#: school_act_article1（学校教育法第1条の学校）は、第1号〜第7号（夜間等の中学校・高等学校・中等教育学校・特別支援学校の高等部・大学・短大・高専）と読む
#: （20歳以上の被保険者が在学する第1条の学校。法令の読み）。specialized_training_college は第8号（専修学校）。
STUDENT_YES = frozenset({"school_act_article1", "specialized_training_college"})
#: 第9号（各種学校）は修業年限1年以上の課程に限る：enrollment.attributes.course_length_months（2026-11-12 に足した語彙）が12以上か。
#: 欄がなければ分かれ目（事実）。
STUDENT_TERM_UNKNOWN = frozenset({"miscellaneous_school"})
#: 修業年限1年（月数）。
ONE_YEAR_MONTHS = 12
#: 第10号（準ずる教育施設として厚生労働省令で定めるもの＝国年則第77条の6 第1号〜第34号：[PS4-KN] §1）に当たりうる学校の種類。
#: enrollment.attributes.npi_student_school_listed（日本年金機構の学生納付特例対象校一覧に記載されているか。2026-11-12 の語彙）が
#: 真なら学生等、偽なら第10号に当たらない（機構の説明「一覧表に記載のある学校に在籍している方は、学生納付特例を申請することができます」が
#: あり反対の一次情報がないので、その読みで決める：D22 S1、仮説 H4。根拠に法令の読み）。欄がなければ候補（当たる・当たらない）で分かれ目（事実）。
STUDENT_ORDINANCE_UNKNOWN = frozenset({"accredited_vocational_training", "other"})

#: 第89条第1項第1号の障害の給付（国年令第6条の5第1項：[PS4-KN] §3、仮説 H6）。pension_entitlement.attributes.scheme で区別する。
#: 障害基礎年金は法律の本文。障害厚生年金・障害共済年金（第1号）は国年令第4条の6 の障害の状態（1級・2級）の者に支給するものに限る。
#: 共済組合が支給する障害年金（第6号）は等級を問わない。労災の年金・企業年金は列挙にない。
DISABILITY_NOT_LISTED = frozenset({"workers_accident_compensation", "corporate_pension"})
DISABILITY_GRADED = frozenset({"employees_pension", "mutual_aid"})
#: 第89条第1項第1号のかっこ書きの「その他の政令で定める者」（国年令第6条の5第2項：障害状態に該当しなくなった日から3年を経過した者）が
#: 当たる給付（第2項第1号イ・ロ、第5号〜第7号の共済組合等の障害年金）。
DISABILITY_THREE_YEARS = frozenset({"national_pension", "employees_pension", "mutual_aid"})

#: 付加保険料を納付できない承認された免除（第90条・第90条の2・第90条の3、納付猶予は第90条の3 とみなす）。
EXEMPT_TYPES = frozenset({"full", "three_quarters", "half", "one_quarter", "student_special", "payment_deferral"})


def _d(s: str | None) -> _dt.date | None:
    return _dt.date.fromisoformat(s) if s else None


def period_of(when: Mapping[str, Any] | None) -> tuple[_dt.date | None, _dt.date | None]:
    if not when:
        return None, None
    if "on" in when:
        day = _d(when["on"])
        return day, day
    if "from_on" in when:
        return _d(when["from_on"]), _d(when.get("to_on"))
    return None, None


def covers(when: Mapping[str, Any] | None, day: _dt.date) -> bool:
    if not when:
        return True
    if "on" in when:
        return _d(when["on"]) == day
    a, b = period_of(when)
    return (a is None or a <= day) and (b is None or day <= b)


def add_months(m: Month, k: int) -> Month:
    n = m[0] * 12 + m[1] - 1 + k
    return (n // 12, n % 12 + 1)


def month_of(day: _dt.date) -> Month:
    return (day.year, day.month)


def first_day(m: Month) -> _dt.date:
    return _dt.date(m[0], m[1], 1)


def last_day(m: Month) -> _dt.date:
    return first_day(add_months(m, 1)) - _dt.timedelta(days=1)


def months_from(start: Month, n: int) -> list[Month]:
    return [add_months(start, i) for i in range(n)]


def fiscal_months(fiscal_year: int) -> list[Month]:
    """年度 F の月（F年4月〜F+1年3月）。保険料の月額・産前産後・育児期間・付加保険料はこの月で数える。"""
    return months_from((fiscal_year, 4), 12)


def exemption_months(fiscal_year: int) -> list[Month]:
    """年度 F の免除等の期間（F年7月〜F+1年6月。国年規第77条の2）。"""
    return months_from((fiscal_year, 7), 12)


def elapsed_day(start: _dt.date, months: int) -> _dt.date:
    """start から起算して months 月を経過した日（民法第143条：起算日に応当する日の前日に満了。応当日がなければその月の末日。経過した日はその翌日）。"""
    m = add_months(month_of(start), months)
    last = last_day(m)
    if start.day > last.day:
        return last + _dt.timedelta(days=1)
    return _dt.date(m[0], m[1], start.day)


def birthday(birth: _dt.date, years: int) -> _dt.date:
    """years 回目の誕生日（年齢計算に関する法律：誕生日の前日に年齢に達し、その翌日が誕生日。2月29日生まれは平年の3月1日）。"""
    try:
        return birth.replace(year=birth.year + years)
    except ValueError:
        return _dt.date(birth.year + years, 3, 1)


def _states(recs: Iterable[Mapping[str, Any]]) -> set[State]:
    return {State.from_mark(r["mark"]) for r in recs if "mark" in r}


def _split(sid: str, means: Means, target: Mapping[str, Any], candidates: tuple[str, ...] = ()) -> Split:
    return Split(id=sid, means=means, target=dict(target), candidates=candidates, splits_conclusion=True)


@dataclass
class Count:
    """月数と、その由来・分かれ目。"""

    months: set[Month] = field(default_factory=set)
    record_ids: list[str] = field(default_factory=list)
    states: set[State] = field(default_factory=set)
    missing: list[Split] = field(default_factory=list)

    def note(self, recs: Iterable[Mapping[str, Any]]) -> None:
        recs = list(recs)
        self.record_ids += [r["id"] for r in recs]
        self.states |= _states(recs)

    @property
    def value(self) -> int:
        return len(self.months)


# ---------------------------------------------------------------------------
# 被保険者の種別（月の末日）
# ---------------------------------------------------------------------------


def category_on(ctx: YearContext, pid: str, day: _dt.date) -> tuple[str | None, list[Mapping[str, Any]]]:
    """その日の国民年金の被保険者の種別（first・second・third）。national_pension の記録、なければ厚生年金保険の資格（第2号）。分からなければ None。"""
    recs = [r for r in ctx.records("national_pension") if r["roles"]["member"] == pid and covers(r.get("when"), day)]
    if recs:
        return str(recs[0]["attributes"]["category"]), recs[:1]
    ep = [r for r in ctx.records("employees_pension") if r["roles"]["member"] == pid and covers(r.get("when"), day)]
    if ep:
        return "second", ep[:1]
    return None, []


def _age_on(birth: _dt.date, day: _dt.date) -> int:
    n = day.year - birth.year + 1
    while n > 0 and birthday(birth, n) - _dt.timedelta(days=1) > day:
        n -= 1
    return n


def first_category_months(ctx: YearContext, pid: str, months: Iterable[Month], out: Count, what: str) -> set[Month]:
    """months のうち、月の末日に第1号被保険者である月。種別の記録がない20歳以上60歳未満の月は分かれ目（事実）。"""
    got: set[Month] = set()
    unknown: list[Month] = []
    birth = ctx.birth_on(pid)
    for m in months:
        cat, recs = category_on(ctx, pid, last_day(m))
        out.note(recs)
        if cat == "first":
            got.add(m)
        elif cat is None and 20 <= _age_on(birth, last_day(m)) < 60:
            unknown.append(m)
    if unknown:
        out.missing.append(
            _split(
                f"事実:国年の被保険者の種別:{pid}:{what}:{unknown[0][0]}-{unknown[0][1]:02d}",
                Means.FACT,
                {"person": pid, "事項": f"{what}の月の末日の国民年金の被保険者の種別（national_pension・employees_pension の記録）", "月": [f"{y}-{m:02d}" for y, m in unknown]},
            )
        )
    return got


# ---------------------------------------------------------------------------
# 学生等である月（国年令第6条の6）
# ---------------------------------------------------------------------------


def is_student_record(r: Mapping[str, Any]) -> bool:
    """在学の記録が国年令第6条の6 の学生等に当たるか（第1号〜第8号、第9号は修業年限1年以上の課程、第10号は学生納付特例対象校一覧に
    記載された施設）。決まらないもの（第9号の欄なし・第10号の欄なし）は偽。"""
    a = r["attributes"]
    if a["school_type"] in STUDENT_YES:
        return True
    if a["school_type"] in STUDENT_ORDINANCE_UNKNOWN:
        return a.get("npi_student_school_listed") is True
    return a["school_type"] in STUDENT_TERM_UNKNOWN and a.get("course_length_months") is not None and int(a["course_length_months"]) >= ONE_YEAR_MONTHS


def student_months(ctx: YearContext, pid: str, months: list[Month], what: str) -> Count:
    out = Count()
    recs = [r for r in ctx.records("enrollment") if r["roles"]["person"] == pid]
    partial: list[Month] = []
    for m in months:
        start, end = first_day(m), last_day(m)
        rel = [r for r in recs if _overlaps(r.get("when"), start, end)]
        if not rel:
            continue
        yes = [r for r in rel if is_student_record(r)]
        if any(covers(r.get("when"), start) and covers(r.get("when"), end) and _whole(r.get("when"), start, end) for r in yes):
            out.months.add(m)
            out.note(yes)
            continue
        if yes:
            partial.append(m)
            out.note(yes)
        for r in rel:
            st = r["attributes"]["school_type"]
            if st in STUDENT_TERM_UNKNOWN and r["attributes"].get("course_length_months") is not None:
                out.note([r])
            elif st in STUDENT_TERM_UNKNOWN:
                out.note([r])
                out.missing.append(
                    _split(
                        f"事実:国年の各種学校の修業年限:{r['id']}",
                        Means.FACT,
                        {"person": pid, "記録": r["id"], "欄": "attributes.course_length_months", "事項": "各種学校の課程の修業年限が1年以上か（国年令第6条の6第9号）"},
                        ("1年以上", "1年未満"),
                    )
                )
            elif st in STUDENT_ORDINANCE_UNKNOWN:
                out.note([r])
                if r["attributes"].get("npi_student_school_listed") is None:
                    out.missing.append(
                        _split(
                            f"事実:国年の準ずる教育施設:{r['id']}",
                            Means.FACT,
                            {
                                "person": pid,
                                "記録": r["id"],
                                "欄": "attributes.npi_student_school_listed",
                                "事項": "在学する施設が日本年金機構の学生納付特例対象校一覧に記載されているか（国年令第6条の6第10号・国年則第77条の6）",
                            },
                            ("当たる", "当たらない"),
                        )
                    )
    if partial:
        out.missing.append(
            _split(
                f"一次情報:国年の月の途中の在学:{pid}:{what}",
                Means.PRIMARY_SOURCE,
                {"person": pid, "事項": f"{what}で在学の始まり・終わりが月の途中にある月を学生等である月に数えるか（docs に一次情報がない）", "月": [f"{y}-{m:02d}" for y, m in partial]},
                ("数える", "数えない"),
            )
        )
    return out


def _overlaps(when: Mapping[str, Any] | None, start: _dt.date, end: _dt.date) -> bool:
    a, b = period_of(when)
    return (a is None or a <= end) and (b is None or b >= start)


def _whole(when: Mapping[str, Any] | None, start: _dt.date, end: _dt.date) -> bool:
    a, b = period_of(when)
    return (a is None or a <= start) and (b is None or b >= end)


# ---------------------------------------------------------------------------
# 産前産後（第88条の2）
# ---------------------------------------------------------------------------


@dataclass
class Birth:
    """出産1件：出産予定日（第88条の2 の「出産予定日」）、多胎か、出産の日、記録。"""

    due: _dt.date
    multiple: bool
    delivered: _dt.date | None
    records: list[Mapping[str, Any]]
    missing: list[Split] = field(default_factory=list)
    #: 出産に係る子（childbirth の child_ids。2026-11-12）
    child_ids: tuple[str, ...] = ()

    def perinatal(self) -> list[Month]:
        """第88条の2 の期間（出産予定月の前月〔多胎は3月前〕から翌々月まで）。"""
        m = month_of(self.due)
        before = 3 if self.multiple else 1
        return months_from(add_months(m, -before), before + 3)


def births(ctx: YearContext, pid: str) -> list[Birth]:
    """出産の記録（共通の種類 childbirth と、以前の書き方 kokuho_event の childbirth。出産予定日・出産の日・多胎）と npi_exemption の perinatal
    （届出の日）から出産予定日を決める。同じ出産予定日になる記録は1つの出産にまとめる（2026-11-12）。

    国年規第73条の6：届出（第73条の7第1項）を行う前に出産した場合は出産の日を出産予定日とする。届出の記録がなく出産の日があれば、届出の前に出産した。
    届出の記録に届出の日がなく、出産予定日と出産の日の月が違えば分かれ目（事実）。
    """
    notices = [
        r for r in ctx.records("npi_exemption")
        if r["roles"]["person"] == pid and r["attributes"]["exemption_type"] == "perinatal" and r["attributes"]["status"] != "rejected"
    ]
    out: list[Birth] = []
    recs = [e for e in ctx.records("childbirth") if e["roles"]["person"] == pid] + [
        e for e in ctx.records("kokuho_event") if e["roles"]["person"] == pid and e["attributes"]["event"] == "childbirth"
    ]
    for e in recs:
        a = e["attributes"]
        start, _ = period_of(e.get("when"))
        exp, dl = _d(a.get("expected_delivery_on")), _d(a.get("delivered_on"))
        missing: list[Split] = []
        if exp and dl:
            applied = [_d(n["attributes"].get("applied_on")) for n in notices]
            known = [x for x in applied if x is not None]
            if not notices:
                due = dl
            elif known and min(known) < dl:
                due = exp
            elif known and len(known) == len(applied):
                due = dl
            else:
                due = exp
                if month_of(exp) != month_of(dl):
                    missing.append(
                        _split(
                            f"事実:国年の産前産後の届出の日:{e['id']}",
                            Means.FACT,
                            {"person": pid, "記録": e["id"], "事項": "産前産後の免除の届出の日（出産の前か。国年規第73条の6）"},
                        )
                    )
        else:
            due = exp or dl or start  # type: ignore[assignment]
        if due is None:
            continue
        b = Birth(due, bool(a.get("multiple_birth")), dl, [e] + notices, missing, tuple(a.get("child_ids") or ()))
        same = next((x for x in out if x.due == b.due), None)
        if same is None:
            out.append(b)
            continue
        same.multiple = same.multiple or b.multiple
        same.delivered = same.delivered or b.delivered
        same.records += [e]
        same.missing += [m for m in b.missing if m.id not in {x.id for x in same.missing}]
        same.child_ids = same.child_ids or b.child_ids
    return out


def perinatal_count(ctx: YearContext, pid: str, fiscal_year: int) -> Count:
    out = Count()
    fy = set(fiscal_months(fiscal_year))
    for b in births(ctx, pid):
        months = [m for m in b.perinatal() if m in fy]
        if not months:
            continue
        out.note(b.records)
        out.missing += b.missing
        out.months |= first_category_months(ctx, pid, months, out, "産前産後の期間")
    return out


# ---------------------------------------------------------------------------
# 育児期間（第88条の3）
# ---------------------------------------------------------------------------


def rearing(ctx: YearContext, pid: str, child: str, on: _dt.date) -> tuple[bool | None, list[Mapping[str, Any]]]:
    """その日に pid が子を養育するか（法令の読み：同居〔cohabitation〕か、住民票の世帯が同じなら養育する。住民票の世帯が違い同居の記録もなければ養育しない。
    材料がなければ None）。"""
    death = ctx.death_on(child)
    if death is not None and death < on:
        return False, []
    co = ctx.relations.between(pid, child, ("cohabitation",), on=on)
    if co:
        return True, [r.record for r in co]
    rp = [r for r in ctx.records("resident_record") if r["roles"]["person"] == pid and covers(r.get("when"), on)]
    rc = [r for r in ctx.records("resident_record") if r["roles"]["person"] == child and covers(r.get("when"), on)]
    if rp and rc:
        return rp[0]["attributes"]["household_id"] == rc[0]["attributes"]["household_id"], rp[:1] + rc[:1]
    return None, []


def _end_month(end_marker: _dt.date, death: _dt.date | None) -> Month:
    """期間の終わりの日（その日の属する月の前月まで）。子の死亡がその前日までにあれば死亡の日の翌日（第88条の3 の各項のかっこ書き）。"""
    if death is not None and death < end_marker - _dt.timedelta(days=1):
        return month_of(death + _dt.timedelta(days=1))
    return month_of(end_marker)


def childcare_count(ctx: YearContext, pid: str, fiscal_year: int) -> Count:
    """年度 F の月のうち、第88条の3 第1項・第2項で納付を要しない月（2026年9月以前の月を除く。第1号被保険者の月）。
    施行の前の出産・養育の開始でも 2026年10月以後の月には当てる（令和6年法律第47号附則第10条：[PS4-KN] §2）。"""
    out = Count()
    fy = fiscal_months(fiscal_year)
    from_month = month_of(CHILDCARE_FROM)
    want = [m for m in fy if m >= from_month]
    if not want:
        return out
    target: set[Month] = set()
    own = births(ctx, pid)
    perinatal_of = {id(b): set(b.perinatal()) for b in own}
    matched_children: set[str] = set()
    # 施行（2026-10-01）より前の出産・養育の開始でも、2026年10月以後の月に当てる（令和6年法律第47号附則第10条：[PS4-KN] §2。want で月を絞る）
    # 第1項：第88条の2 の適用を受けた被保険者（産前産後の期間に第1号の月がある）がその出産に係る子を養育する
    for b in own:
        probe = Count()
        if not first_category_months(ctx, pid, b.perinatal(), probe, "産前産後の期間"):
            continue
        start = month_of(elapsed_day(b.due, 3))
        end_marker = elapsed_day(b.due, 12)
        child = _child_of_birth(ctx, pid, b)
        months = [m for m in months_from(start, 12) if m < month_of(end_marker)]
        others = set().union(*(perinatal_of[id(x)] for x in own if x is not b)) if len(own) > 1 else set()
        months = [m for m in months if m not in others and m in want]
        if not months:
            continue
        out.note(b.records)
        if child is None:
            out.missing.append(
                _split(
                    f"事実:国年の育児期間の子:{pid}:{b.due.isoformat()}",
                    Means.FACT,
                    {"person": pid, "事項": "出産に係る子（出生の日が出産の日の人）と、その子を養育するか（第88条の3第1項）"},
                )
            )
            continue
        matched_children.add(child)
        months = [m for m in months if m < _end_month(end_marker, ctx.death_on(child))]
        ok, recs = rearing(ctx, pid, child, ctx.birth_on(child))
        out.note(recs)
        if ok is None:
            out.missing.append(_rearing_split(pid, child))
        if ok is False:
            continue
        target |= set(months)
    # 第2項：それ以外の被保険者が、その子（実子・養子）を養育することとなった日の属する月から1歳に達する日の翌日の属する月の前月まで
    my_perinatal = set().union(*perinatal_of.values()) if perinatal_of else set()
    for rel in ctx.relations.of(pid, ("parentage", "adoption")):
        if rel.my_role not in ("parent", "adoptive_parent") or rel.other in matched_children:
            continue
        child = rel.other
        cbirth = ctx.birth_on(child)
        first = birthday(cbirth, 1)
        start_day = cbirth if rel.kind == "parentage" else max(cbirth, rel.from_on or cbirth)
        if start_day >= first:
            continue
        months = [m for m in months_from(month_of(start_day), 13) if m < _end_month(first, ctx.death_on(child))]
        months = [m for m in months if m not in my_perinatal and m in want]
        if not months:
            continue
        out.note([rel.record])
        ok, recs = rearing(ctx, pid, child, start_day)
        out.note(recs)
        if ok is None:
            out.missing.append(_rearing_split(pid, child))
        if ok is False:
            continue
        target |= set(months)
    # 第2項のかっこ書き：養子縁組里親に委託されている児童（foster_placement の foster_parent_type。2026-11-12）と、
    # 特別養子縁組の成立の請求をした子で家事審判事件が係属している間に監護する子（special_adoption_petition。2026-11-12）
    placed: list[tuple[str, _dt.date | None, Mapping[str, Any]]] = []
    for rel in ctx.relations.of(pid, ("foster_placement",)):
        if rel.my_role != "caregiver" or rel.record["attributes"].get("placement") != "foster_child":
            continue
        kind = rel.record["attributes"].get("foster_parent_type")
        if kind == "adoptive_foster_parent":
            placed.append((rel.other, rel.from_on, rel.record))
            continue
        if kind is not None:
            continue
        child = rel.other
        first = birthday(ctx.birth_on(child), 1)
        start_day = max(ctx.birth_on(child), rel.from_on or ctx.birth_on(child))
        if start_day < first and any(m in want for m in months_from(month_of(start_day), 13) if m < month_of(first)):
            out.note([rel.record])
            out.missing.append(
                _split(
                    f"事実:国年の養子縁組里親:{rel.record_id}",
                    Means.FACT,
                    {"person": pid, "記録": rel.record_id, "欄": "attributes.foster_parent_type", "事項": "養子縁組里親としての委託か（第88条の3第2項）"},
                )
            )
    for r in ctx.records("special_adoption_petition"):
        if r["roles"]["petitioner"] == pid:
            placed.append((r["roles"]["child"], period_of(r.get("when"))[0], r))
    for child, from_on, rec in placed:
        if child in matched_children:
            continue
        cbirth = ctx.birth_on(child)
        first = birthday(cbirth, 1)
        start_day = max(cbirth, from_on or cbirth)
        if start_day >= first:
            continue
        months = [m for m in months_from(month_of(start_day), 13) if m < _end_month(first, ctx.death_on(child))]
        months = [m for m in months if m not in my_perinatal and m in want]
        if not months:
            continue
        out.note([rec])
        ok, recs = rearing(ctx, pid, child, start_day)
        out.note(recs)
        if ok is None:
            out.missing.append(_rearing_split(pid, child))
        if ok is False:
            continue
        target |= set(months)
    out.months = first_category_months(ctx, pid, sorted(target), out, "育児期間")
    return out


def _rearing_split(pid: str, child: str) -> Split:
    return _split(
        f"事実:国年の養育:{pid}:{child}",
        Means.FACT,
        {"person": pid, "other_person": child, "事項": "子を養育するか（同居の記録か住民票の世帯）"},
    )


def _child_of_birth(ctx: YearContext, pid: str, b: Birth) -> str | None:
    """出産に係る子：childbirth の child_ids があればその子。なければ pid の子（親子関係の成立）で、生年月日が出産の日の人。
    出産の日の記録がなければ決めない。"""
    if b.child_ids:
        return b.child_ids[0]
    if b.delivered is None:
        return None
    for rel in ctx.relations.of(pid, ("parentage",)):
        if rel.my_role == "parent" and ctx.birth_on(rel.other) == b.delivered:
            return rel.other
    return None


# ---------------------------------------------------------------------------
# 付加保険料（第87条の2）
# ---------------------------------------------------------------------------


def _assistance_months(when: Mapping[str, Any] | None) -> tuple[Month | None, Month | None]:
    """第89条第1項：該当するに至った日の属する月の前月から、該当しなくなる日の属する月まで（区間の末日の翌日が該当しなくなる日）。"""
    a, b = period_of(when)
    start = add_months(month_of(a), -1) if a else None
    end = month_of(b + _dt.timedelta(days=1)) if b else None
    return start, end


def additional_premium_count(ctx: YearContext, pid: str, fiscal_year: int, relief: set[Month]) -> Count:
    """年度 F の月のうち、付加保険料を納付する者となることができる月（申出をすれば納付できる月）。relief は産前産後・育児期間の月（納付できる：第87条の2第2項）。"""
    out = Count()
    months = fiscal_months(fiscal_year)
    first = first_category_months(ctx, pid, months, out, "付加保険料")
    blocked: set[Month] = set()
    # 第89条第2項：法定免除の期間の各月につき保険料を納付する旨の申出があった月は、第89条第1項を適用しない（npi_application。2026-11-12）
    paying: set[Month] = set()
    for r in ctx.records("npi_application"):
        if r["roles"]["person"] == pid and r["attributes"]["application_type"] == "statutory_exemption_payment":
            hit = {m for m in first if covers(r.get("when"), last_day(m))}
            if hit:
                paying |= hit
                out.note([r])
    for r in ctx.records("npi_exemption"):
        a = r["attributes"]
        if r["roles"]["person"] != pid or a["status"] != "approved" or a["exemption_type"] not in EXEMPT_TYPES:
            continue
        hit = {m for m in first if covers(r.get("when"), last_day(m))}
        if hit:
            blocked |= hit
            out.note([r])
    # 第89条第1項（法定免除）：生活扶助・障害の年金。産前産後・育児期間の月は第89条から除かれる
    for r in ctx.records("public_assistance"):
        if r["roles"]["person"] != pid:
            continue
        s, e = _assistance_months(r.get("when"))
        hit = {m for m in first if (s is None or m >= s) and (e is None or m <= e) and m not in relief and m not in paying}
        if hit:
            blocked |= hit
            out.note([r])
    for r in ctx.records("pension_entitlement"):
        a = r["attributes"]
        if r["roles"]["member"] != pid or a["benefit"] != "disability":
            continue
        scheme = a.get("scheme")
        if scheme in DISABILITY_NOT_LISTED:
            # 国年令第6条の5第1項の列挙にない給付（労災の障害〔補償〕年金・企業年金の障害給付）：法定免除に当たらない
            out.note([r])
            continue
        s, e = _assistance_months(r.get("when"))
        hit = {m for m in first if (s is None or m >= s) and (e is None or m <= e) and m not in relief and m not in paying}
        ended = _d(a.get("disability_state_ended_on"))
        if ended is not None and scheme in DISABILITY_THREE_YEARS:
            # 第89条第1項第1号のかっこ書き（障害基礎年金は法律の本文、障害厚生年金・障害共済年金・共済組合等の障害年金は国年令第6条の5第2項）：
            # 最後に障害状態に該当しなくなった日から起算して障害状態に該当することなく3年を経過した受給権者（現に障害状態に該当しない者）は除く。
            # 除かれる者に該当するに至った日の属する月の翌月から第89条を当てない（該当しなくなる日の属する月までは法定免除：同項柱書の読み）
            out_month = month_of(elapsed_day(ended, 36))
            hit = {m for m in hit if m <= out_month}
        if not hit:
            continue
        out.note([r])
        listed = disability_benefit_listed(scheme, a.get("disability_grade"), a.get("mutual_aid_disability_kind"))
        if listed is True:
            blocked |= hit
        elif listed is None:
            out.missing.append(_disability_split(pid, r, scheme))
    # 国民年金基金の加入員（national_pension_fund。2026-11-12）の月は除く（第87条の2第1項）。加入の記録がなく基金の掛金の支払があれば分かれ目（事実）
    members = [r for r in ctx.records("national_pension_fund") if r["roles"]["member"] == pid]
    for r in members:
        hit = {m for m in first if covers(r.get("when"), last_day(m))}
        if hit:
            blocked |= hit
            out.note([r])
    fund = [
        r for r in ctx.records("social_insurance_payment")
        if r["attributes"]["premium_type"] == "national_pension_fund" and r["roles"].get("liable_person") == pid
        and _overlaps(r.get("when"), first_day(months[0]), last_day(months[-1]))
    ]
    if fund and first and not members:
        out.note(fund)
        out.missing.append(
            _split(
                f"事実:国年の国民年金基金の加入員:{pid}:{fiscal_year}",
                Means.FACT,
                {"person": pid, "年度": fiscal_year, "kind": "national_pension_fund", "事項": "国民年金基金の加入員である期間（基金の掛金の支払の記録があり、加入員の期間の記録がない）"},
            )
        )
    out.months = first - blocked
    return out


def disability_benefit_listed(scheme: str | None, grade: int | None, mutual_aid_kind: str | None = None) -> bool | None:
    """障害の年金が第89条第1項第1号の給付（障害基礎年金・国年令第6条の5第1項の給付）か。決まらなければ None（[PS4-KN] §3、仮説 H6）。

    - national_pension（障害基礎年金）：当たる（法律の本文）。
    - employees_pension（障害厚生年金。第1号）：国年令第4条の6 の障害の状態（国年法第30条第2項の1級・2級）の者に支給するものに限る。
      決定通知書等の障害等級（disability_grade）が1・2なら当たる、それ以外（3級）は当たらない、欄がなければ決まらない（法令の読み：
      厚生年金保険法の1級・2級を国年令別表の1級・2級の状態と読む。別表の本文は docs にない）。
    - mutual_aid：1級・2級なら当たる（第1号の障害共済年金でも第6号の共済組合の障害年金でも）。それ以外は種類（mutual_aid_disability_kind。
      2026-11-12 に語彙を足した）で決める：旧法の共済組合等の障害年金（第6号：等級を問わない）は当たる、障害厚生年金・障害共済年金（第1号）は
      等級が3なら当たらない。種類の欄がなく等級が1・2でなければ決まらない。
    - workers_accident_compensation・corporate_pension：列挙にないので当たらない。
    - other・欄なし：どの給付か分からないので決まらない。
    """
    if scheme == "national_pension":
        return True
    if scheme in DISABILITY_NOT_LISTED:
        return False
    if scheme == "mutual_aid" and mutual_aid_kind == "old_law_disability_pension":
        return True
    if scheme == "mutual_aid" and mutual_aid_kind is not None and grade is not None and int(grade) not in (1, 2):
        return False
    if scheme in DISABILITY_GRADED and grade is not None and int(grade) in (1, 2):
        return True
    if scheme == "employees_pension" and grade is not None:
        return False
    return None


def _disability_split(pid: str, r: Mapping[str, Any], scheme: str | None) -> Split:
    if scheme == "employees_pension":
        what, field_ = "障害厚生年金の障害等級（1級・2級なら第89条第1項第1号の給付。国年令第6条の5第1項第1号）", "attributes.disability_grade"
    elif scheme == "mutual_aid":
        what = (
            "共済の障害の年金が、障害共済年金・障害厚生年金（国年令第6条の5第1項第1号：1級・2級の状態の者に限る）か旧法の共済組合等の障害年金（同項第6号：等級を問わない）か、"
            "と障害等級（1級・2級ならどちらでも当たる）"
        )
        field_ = "attributes.mutual_aid_disability_kind・attributes.disability_grade"
    else:
        what, field_ = "障害の年金の種類（国年令第6条の5第1項の列挙の給付か）", "attributes.scheme"
    return _split(
        f"事実:国年の法定免除の障害の給付:{r['id']}",
        Means.FACT,
        {"person": pid, "記録": r["id"], "欄": field_, "事項": what},
        ("当たる", "当たらない"),
    )


def additional_premium_paid_count(ctx: YearContext, pid: str, can: Count) -> Count:
    """付加保険料を納付する者である月：納付する者となることができる月（can）のうち、付加保険料の納付の申出（npi_application の additional_premium）
    をした日の属する月以後で、辞退の申出をするまでの月（第87条の2第1項・第3項。第4項の基金の加入員はみなし辞退で can から除かれている）。
    申出の期間の終わり（辞退の申出をした日の前日）が月の途中なら、その月を数えるかは docs に一次情報がないので分かれ目（一次情報）。"""
    out = Count()
    out.record_ids = list(can.record_ids)
    out.states = set(can.states)
    out.missing = list(can.missing)
    for r in ctx.records("npi_application"):
        if r["roles"]["person"] != pid or r["attributes"]["application_type"] != "additional_premium":
            continue
        a, b = period_of(r.get("when"))
        hit = {m for m in can.months if (a is None or m >= month_of(a)) and (b is None or last_day(m) <= b)}
        if b is not None and b != last_day(month_of(b)) and month_of(b) in can.months and (a is None or month_of(b) >= month_of(a)):
            out.missing.append(
                _split(
                    f"一次情報:国年の付加保険料の辞退の月:{r['id']}",
                    Means.PRIMARY_SOURCE,
                    {"person": pid, "記録": r["id"], "事項": "辞退の申出（第87条の2第3項）をした日の属する月の付加保険料を納付するか（docs に一次情報がない）"},
                    ("納付しない", "納付する"),
                )
            )
        if hit:
            out.months |= hit
            out.note([r])
    return out


__all__ = [
    "Birth",
    "CHILDCARE_FROM",
    "Count",
    "additional_premium_count",
    "additional_premium_paid_count",
    "births",
    "birthday",
    "category_on",
    "childcare_count",
    "disability_benefit_listed",
    "elapsed_day",
    "exemption_months",
    "fiscal_months",
    "perinatal_count",
    "student_months",
]
