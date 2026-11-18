"""規則モジュール other_deductions：雑損控除の前処理（中間表現 casualty・casualty_expenditure → 所有者の 損失の金額・災害関連支出の金額）。

- 第72条第1項の損失の金額：災害・盗難・横領による資産の損失（損失の直前の価額 − 直後の価額）に、やむを得ない支出（所令第206条第1項）を足したものから、
  保険金等で補塡される部分を除いた額。保険金等はまず損害金額から差し引き、超える分を災害等関連支出から差し引く（TA1110 注3）。
  docs/public-sources/20261109_round2_hoken-kifu-laws.md §6、docs/public-sources/20261109_round2_hoken-kifu-nta-soumu.md §5。
- 損失の金額（損害金額）：所令第206条第3項の「損失を生じた時の直前のその資産の価額」が基礎。判断.雑損の計算の loss_measure が
  acquisition_cost_basis なら取得費相当額（所法38②：記録の acquisition_cost と読む）を基礎にする（法令の読み）。直後の価額（post_loss_value）がなければ
  損失を決められないので対象外。
- 年分：損失はその発生の日の年分。災害等関連支出は支出した日の年分（通達72−5）。判断の expenditure_tax_year があれば、
  1月1日〜3月15日の支出を前年分に入れる通達72−5 のただし書を当てる。
- 原状回復の支出の割合（判断.雑損の計算 の restoration_portion：通達72−3）：判断があれば、その事象の原状回復の支出の額の代わりに判断の額を数える
  （法令の読み。判断の額が原状回復の支出の合計を超える・原状回復の支出が2以上の年分にまたがるときは対象外）。
- 事業用の資産（business_use）は被災事業用資産（第70条第3項）で、第72条の対象から除かれる（第72条第1項のかっこ書き）。雑損控除には数えない
  （損失は事業所得等の必要経費の側：income_kinds）。
- 第206条第1項第2号の期間（災害のやんだ日の翌日から1年を経過した日の前日まで。大規模な災害の場合その他やむを得ない事情がある場合は3年）：
  発生の日から1年以内の支出はやんだ日によらず期間内。それより後は casualty.attributes.disaster_ended_on（やんだ日 E）で、E の1年後の応当日まで
  （「翌日から一年を経過した日の前日」を応当日と読む：法令の読み）は期間内、3年後の応当日までは 判断.雑損の計算 の unavoidable_circumstances
  （未入力なら両方で評価）、それより後は第206条第1項の支出に当たらない（数えない）。取壊し・除去（第1号）・緊急の防止（第3号）にも同じ期間を当てる
  （所基通72−7 が準ずる 70−6 の「おおむね1年以内」。法令の読み）。やんだ日がなく発生から1年を超える支出は c-入力（やんだ日を入力すれば決まる）。
- 盗難・横領の原状回復以外の支出（除去・防止）：第206条第1項第4号の「その他これに類する支出」に当たるかの一次情報がない（［PS3-KM］§1）ので、
  当たる・当たらないの両方で評価し、損失の金額が分かれるので未確定（決める手段は一次情報）。第4号の支出は災害関連支出（第2項）に入れない。
- 災害等関連支出の支払者が控除を受ける人でない：ほかの人が支払った支出を控除を受ける人の損失の金額に含めるかの一次情報がない
  （所基通72−4(1)ロは生計の判定の時点だけ）ので、含める・含めないの両方で評価し、分かれれば未確定（決める手段は一次情報）。
- 損失の金額の基礎（第206条第3項）：取得費相当額は所法38②（第3項第1号）で、所令142（資産損失の必要経費算入：所法51）は雑損控除には当たらない
  （［PS3-KM］§3）。
- 生活に通常必要でない資産（第62条第1項）は判断.雑損の計算 not_ordinarily_necessary_asset。未入力なら両方で評価（D21 R6）。
- 控除を受ける人（第72条第1項・所令第205条。段階評価 STAGE で扶養の割当ての結果を読む：`attribute_claimant`）：
  所有者と、損失が生じた日に生計を一にする親族（判断.生計を一にする の日ごとの1か所。所基通72−4(1)）がいなければ所有者本人。
  いれば、所有者の総所得金額・退職所得金額（山林所得は範囲外）の合計額がその年12月31日の現況で所令第205条第1項の基準額以下なら、
  その親族の資産として、所令第205条第2項の居住者（一 同一生計配偶者・扶養親族としている人、二イ 配偶者、二ロ 合計額が最も大きい人。1人だけならその人）の控除に入れ、
  所有者本人の控除には入れない（同じ損失を2人で控除しない読み：docs/hypotheses/20261109_round2_hoken-kifu-model.md H10・法令の読み）。
  基準額を超えれば所有者本人。災害等関連支出は、控除を受ける人が支払ったものだけを数える（ほかの人の支払は対象外）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...candidates import Candidate
from ...registry import DecisionSlot, StageSpec, StageValue, YearContext
from ...result import State
from .basis import CASUALTY_RELATIVE_RULE
from ...result import Split
from .facts import J_CASUALTY, J_SEIKEI, Acc, d, not_implemented, on_year, reading_split, seikei_key, seikei_slot, states_of
from .kinship import RelationIndex, kinship, relation_index

V_LOSS = "所得税_雑損の損失の金額"
V_RELATED = "所得税_雑損の災害関連支出の金額"

#: 第72条第1項の「災害又は盗難若しくは横領」に当たる原因（other は決められない）。
DISASTER_CAUSES = frozenset({"earthquake", "fire", "storm_or_flood", "other_natural_disaster"})
THEFT_CAUSES = frozenset({"theft", "embezzlement"})

#: 所令第206条第1項第2号の期間（災害のやんだ日の翌日から一年〔大規模な災害の場合その他やむを得ない事情がある場合は三年〕を経過した日の前日まで）。
ONE_YEAR = 1
THREE_YEARS = 3

NECESSARY_CANDIDATES = (Candidate(False, "生活に通常必要な資産"), Candidate(True, "生活に通常必要でない資産"))
UNAVOIDABLE_CANDIDATES = (Candidate(False, "やむを得ない事情はない（1年）"), Candidate(True, "大規模な災害・やむを得ない事情がある（3年）"))

R_CAUSE = "雑損の原因（casualty.attributes.cause）が other で、第72条第1項の災害・盗難・横領に当たるか決められない。災害・盗難・横領の種類を入力すれば決まる（詐欺・恐喝は当たらない：質疑応答事例 05/05）"
R_POST_VALUE = "損失の直後の資産の価額（amounts.post_loss_value）がなく、損失の金額（所令第206条第3項）を決められない"
R_PRE_VALUE = "損失の直前の資産の価額（amounts.pre_loss_value）がなく、損失の金額（所令第206条第3項）を決められない"
R_ACQUISITION = "判断.雑損の計算の loss_measure が acquisition_cost_basis だが取得費（amounts.acquisition_cost）がない"
R_PORTION = (
    "判断.雑損の計算の原状回復の支出の額（restoration_portion：通達72−3）が、その事象の原状回復の支出の合計を超えるか、"
    "原状回復の支出が2以上の年分にまたがる（どの年分の支出に当てるか決められない）"
)
R_NECESSARY = "判断.雑損の計算に生活に通常必要でない資産か（not_ordinarily_necessary_asset）の記載がない。記載を入力すれば決まる"
#: 読みの分かれ目の論点（reading_split の topic）。
T_PAYER = "災害等関連支出の支払者が控除を受ける人でない"
T_THEFT = "盗難・横領の原状回復以外の支出が所令第206条第1項第4号の類する支出か"
T_ATTRIBUTION = "所令第205条第2項の居住者"
R_KIN = "損失が生じた日に、所有者がほかの人の親族かを中間表現の関係から決められない（所令第205条の親族の資産かを決められない）。関係（親子・養子縁組・婚姻）の記録の区間を入力すれば決まる"
R_NOT_LIVING = (
    "所令第205条第2項第1号の居住者（所有者を同一生計配偶者・扶養親族としている人）が、損失が生じた日に所有者と生計を一にしていない"
    "（12月31日の現況の割当てと損失の日の生計が食い違う）。第1号を当てる・当てずに第2号で決めるの一次情報がない"
)
R_TIE = "所令第205条第2項第2号ロ：所有者と生計を一にする居住者のうち合計額が最も大きい人が2人以上いる（同額のときの定めが一次情報にない）"
R_EXPENDITURE_TYPE = (
    "災害等関連支出の種類（casualty_expenditure.attributes.expenditure_type）が other で、所令第206条第1項のどの支出か決められない。"
    "removal（取壊し・除去）・restoration（原状回復）・prevention（損壊等の防止）のどれかを入力すれば決まる"
)
R_ENDED_MISSING = (
    "災害等関連支出が損失の発生の日から1年より後に支払われたが、災害のやんだ日（casualty.attributes.disaster_ended_on）がなく、"
    "所令第206条第1項第2号の期間内か決められない。やんだ日を入力すれば決まる"
)
R_YEAR_JUDGMENT = "判断.雑損の計算の expenditure_tax_year が通達72−5 のただし書（翌年1月1日〜3月15日の支出を前年分に）に当たらない。判断を直せば決まる"



#: 段階評価の段（所令第205条の親族の資産の所属。run=None：build_inputs が stage_value で読む）。
STAGE_NAME = "雑損控除の資産の所属"
R_TOTAL_ETC = "所得税_総所得金額等"
R_CLAIMANT = "所得税_扶養親族等の申告者"
R_ISDEP = "所得税_扶養親族に当たるか"
R_SPOUSE = "所得税_同一生計配偶者に当たるか"
R_RESIDENT = "所得税_居住者か"
STAGE_READS = (R_TOTAL_ETC, R_CLAIMANT, R_ISDEP, R_SPOUSE, R_RESIDENT)


@dataclass(frozen=True)
class Attribution:
    """所令第205条で決めた、資産の損失の控除を受ける人（claimant）。

    一次情報で決まらないとき（第2項第1号の居住者が損失の日に生計を一にしていない・第2号ロの同額）は、candidates に候補の全部
    （claimant はその最初）と reason（論点）を入れる。呼び出し側は候補の全部の人の損失の金額を未確定にする（決める手段は一次情報）。
    """

    claimant: str
    candidates: tuple[str, ...] = ()
    reason: str | None = None


def _second_paragraph_two(living: list[str], measures: Mapping[str, int], spouses: list[str]) -> list[str]:
    """第2項第2号：イ 配偶者ならその夫又は妻、ロ 合計額が最も大きい居住者（同額なら全員を返す）。"""
    if len(spouses) == 1:
        return [spouses[0]]
    top = max(measures[r] for r in living)
    return [r for r in living if measures[r] == top]


def attribute_claimant(
    owner: str,
    living: list[str],
    measures: Mapping[str, int],
    limit: int,
    *,
    dependent_of: str | None,
    spouse_claimant: str | None,
    spouses: list[str],
) -> Attribution:
    """所令第205条の純粋関数。

    - living：損失が生じた日に所有者と生計を一にする親族である居住者（所有者を除く）。
    - measures：人 → 所令第205条の「総所得金額、退職所得金額及び山林所得金額の合計額」。措令第4条の2第9項・第25条の8第16項・
      第25条の11の2第20項の読替えの表に第205条があり、上場株式等に係る配当所得等・譲渡所得等（損益通算・繰越控除の後）を加えて読む
      （［PS3-JJ］§1・§2、［H3］H4）。この版の範囲の所得では 所得税_総所得金額等 と同じ（山林所得・一般株式等は範囲外）。
    - dependent_of：所有者を扶養親族としている人（扶養の割当て）、spouse_claimant：所有者を同一生計配偶者としている人。
    - spouses：living のうち所有者の配偶者。
    """
    if not living:
        return Attribution(owner)
    if measures[owner] > limit:  # 第1項の親族に当たらない：所有者本人の資産
        return Attribution(owner)
    if len(living) == 1:
        return Attribution(living[0])
    first = dependent_of or spouse_claimant  # 第2項第1号
    if first is not None and first in living:
        return Attribution(first)
    picks = _second_paragraph_two(living, measures, spouses)
    if first is not None:
        # 第1号の居住者が損失の日に生計を一にしていない：第1号を当てる読みと、第2号で決める読み（一次情報なし：両方で評価）
        cands = tuple(dict.fromkeys([*picks, first]))
        return Attribution(cands[0], cands, R_NOT_LIVING)
    if len(picks) > 1:
        return Attribution(picks[0], tuple(picks), R_TIE)
    return Attribution(picks[0])


@dataclass(frozen=True)
class _Casualty:
    record: Mapping[str, Any]
    owner: str
    cause: str
    on: _dt.date
    expenditures: tuple[Mapping[str, Any], ...]


class CasualtyYear:
    """雑損の事象と災害等関連支出の年分の段取り。"""

    def __init__(self, ctx: YearContext, idx: RelationIndex | None = None) -> None:
        self.ctx = ctx
        self.year = ctx.year
        self.persons = set(ctx.persons)
        self.idx = idx if idx is not None else relation_index(ctx.ir)
        by_casualty: dict[str, list[Mapping[str, Any]]] = {}
        for r in ctx.records("casualty_expenditure"):
            by_casualty.setdefault(r["attributes"]["casualty_id"], []).append(r)
        self.items: list[_Casualty] = []
        for r in sorted(ctx.records("casualty"), key=lambda r: r["id"]):
            owner = r["roles"]["owner"]
            if owner not in self.persons:
                continue
            self.items.append(
                _Casualty(r, owner, r["attributes"]["cause"], d(r["when"]["on"]), tuple(sorted(by_casualty.get(r["id"], []), key=lambda e: e["id"])))
            )

    def _judged(self, c: _Casualty) -> list[Mapping[str, Any]]:
        return [j for j in self.ctx.judgments(J_CASUALTY) if j["subject"]["casualty_id"] == c.record["id"]]

    def _relevant(self, c: _Casualty) -> bool:
        return c.on.year == self.year or any(self._exp_year(c, e) == self.year for e in c.expenditures)

    def _counted(self, c: _Casualty) -> bool:
        """雑損控除の計算に入れうる事象（原因が災害・盗難・横領で、被災事業用資産でない）。"""
        return self._relevant(c) and c.cause in (DISASTER_CAUSES | THEFT_CAUSES) and not c.record["attributes"].get("business_use")

    def _exp_year(self, c: _Casualty, e: Mapping[str, Any]) -> int:
        for j in self._judged(c):
            y = j["value"].get("expenditure_tax_year")
            if y is not None:
                return y
        return on_year(e)

    def _kin(self, c: _Casualty) -> tuple[list[str], list[str]]:
        """損失が生じた日に所有者の親族である人（所有者を除く・その年分に生存）と、親族かを決められない人。"""
        kin: list[str] = []
        unknown: list[str] = []
        for r in sorted(self.persons - {c.owner}):
            k = kinship(self.idx, r, c.owner, c.on)
            if k.relative is True:
                kin.append(r)
            elif k.relative is None:
                unknown.append(r)
        return kin, unknown

    def slots(self) -> list[DecisionSlot]:
        return [
            DecisionSlot(
                key=c.record["id"],
                target={"casualty_id": c.record["id"], "person": c.owner, "判断の項目": "not_ordinarily_necessary_asset"},
                matches=lambda j, cid=c.record["id"]: j["subject"]["casualty_id"] == cid,
                candidates=NECESSARY_CANDIDATES,
                persons=(c.owner,),
            )
            for c in self.items
            if self._counted(c)
        ]

    def seikei_slots(self) -> list[DecisionSlot]:
        """所令第205条の親族の資産かの判定に使う、損失が生じた日の 判断.生計を一にする（所基通72−4(1)）。"""
        out = []
        for c in self.items:
            if not self._counted(c):
                continue
            for r in self._kin(c)[0]:
                out.append(seikei_slot(r, c.owner, c.on, "雑損控除の親族の資産（所得税法第72条第1項・所得税法施行令第205条・所得税基本通達72−4）"))
        return out

    def _ended_on(self, c: _Casualty) -> _dt.date | None:
        v = c.record["attributes"].get("disaster_ended_on")
        return d(v) if v else None

    def _period(self, c: _Casualty, paid: _dt.date) -> str:
        """所令第206条第1項第2号の期間：'in'（期間内）・'unavoidable'（3年の期間だけに入る）・'out'（期間外）・'unknown'（やんだ日がない）。"""
        if paid <= _add_years(c.on, ONE_YEAR):
            return "in"  # やんだ日は発生の日以後なので、発生から1年以内は期間内
        ended = self._ended_on(c)
        if ended is None:
            return "unknown"
        if paid <= _add_years(ended, ONE_YEAR):
            return "in"
        if paid <= _add_years(ended, THREE_YEARS):
            return "unavoidable"
        return "out"

    @staticmethod
    def unavoidable_key(c_id: str) -> str:
        return f"{c_id}:やむを得ない事情"

    def unavoidable_slots(self) -> list[DecisionSlot]:
        """判断.雑損の計算 の unavoidable_circumstances（大規模な災害の場合その他やむを得ない事情：3年）が値を変える事象の1か所。"""
        out = []
        for c in self.items:
            if not self._counted(c) or c.cause not in DISASTER_CAUSES:
                continue
            if any(self._exp_year(c, e) == self.year and self._period(c, d(e["when"]["on"])) == "unavoidable" for e in c.expenditures):
                cid = c.record["id"]
                out.append(
                    DecisionSlot(
                        key=self.unavoidable_key(cid),
                        target={"casualty_id": cid, "person": c.owner, "判断の項目": "unavoidable_circumstances"},
                        matches=lambda j, cid=cid: j["subject"]["casualty_id"] == cid and j["value"].get("unavoidable_circumstances") is not None,
                        candidates=UNAVOIDABLE_CANDIDATES,
                        persons=(c.owner,),
                    )
                )
        return out

    def inputs(self, acc: Acc) -> None:
        acc.stage_vars.update((V_LOSS, V_RELATED))  # 段の値を読まなかった人の由来は空（読んだ値の全部を既定にしない）
        for c in self.items:
            if not self._relevant(c):
                continue
            self._one(c, acc)

    def _one(self, c: _Casualty, acc: Acc) -> None:
        pid = c.owner
        r = c.record
        ids = [r["id"]]
        states = states_of(r)
        acc.note(V_LOSS, pid, ids, states)
        acc.note(V_RELATED, pid, ids, states)
        if c.cause not in DISASTER_CAUSES | THEFT_CAUSES:
            self._exclude(acc, [pid], R_CAUSE, ids)
            return
        if r["attributes"].get("business_use"):
            return  # 被災事業用資産：第72条第1項のかっこ書きで雑損控除の対象から除かれる（損失は事業所得等の側）
        dec = self.ctx.decision(J_CASUALTY, r["id"])
        acc.note_decided(V_LOSS, pid, dec)
        acc.note_decided(V_RELATED, pid, dec)
        if dec.value is None:
            self._exclude(acc, [pid], R_NECESSARY, ids + list(dec.record_ids))
            return
        if dec.value:  # 生活に通常必要でない資産：第72条の対象外
            return
        who = self._claimant(c, acc)
        if who is None:
            return
        claimant, uses, more_ids, more_states, attribution = who
        judged = self._judged(c)
        loss_measure = next((j["value"]["loss_measure"] for j in judged if j["value"].get("loss_measure") is not None), "market_value")
        portion = next((j["value"]["restoration_portion"] for j in judged if j["value"].get("restoration_portion") is not None), None)
        judged_ids = [j["id"] for j in judged]
        amounts = r["amounts"]
        if loss_measure == "acquisition_cost_basis":
            base = amounts.get("acquisition_cost")
            if base is None:
                self._exclude(acc, [pid], R_ACQUISITION, ids)
                return
        else:
            base = amounts.get("pre_loss_value")
            if base is None:
                self._exclude(acc, [pid], R_PRE_VALUE, ids)
                return
        post = amounts.get("post_loss_value")
        if post is None:
            self._exclude(acc, [pid], R_POST_VALUE, ids)
            return
        damage = max(int(base) - int(post), 0)
        recovery = int(amounts.get("insurance_recovery", 0))
        is_disaster = c.cause in DISASTER_CAUSES
        # 保険金等はまず損害金額から（TA1110 注3）。超える分は災害等関連支出から
        damage_after = max(damage - recovery, 0)
        rest = max(recovery - damage, 0)
        exp_total = 0
        restoration_total = 0
        exp_ids: list[str] = []
        exp_states: set[Any] = set()
        splits: list[Split] = []
        if portion is not None:
            years = {self._exp_year(c, e) for e in c.expenditures if e["attributes"]["expenditure_type"] == "restoration"}
            if len(years) > 1:
                self._exclude(acc, [pid, claimant], R_PORTION, ids + judged_ids)
                return
        for e in c.expenditures:
            if self._exp_year(c, e) != self.year:
                continue
            kind = e["attributes"]["expenditure_type"]
            if kind == "other":
                self._exclude(acc, [claimant], R_EXPENDITURE_TYPE, ids + [e["id"]])
                return
            paid = d(e["when"]["on"])
            if not self._year_override_valid(c, e, paid):
                self._exclude(acc, [claimant], R_YEAR_JUDGMENT, ids + [e["id"]])
                return
            if is_disaster:
                period = self._period(c, paid)
                if period == "unknown":
                    self._exclude(acc, [claimant], R_ENDED_MISSING, ids + [e["id"]])
                    return
                if period == "unavoidable":
                    dec = self.ctx.decision(J_CASUALTY, self.unavoidable_key(r["id"]))
                    exp_ids += list(dec.record_ids)
                    exp_states |= set(dec.states)
                    if not dec.value:
                        continue  # 1年の期間の外：第206条第1項第2号の支出に当たらない
                elif period == "out":
                    continue  # 3年の期間の外：第206条第1項第2号の支出に当たらない
            exp_ids.append(e["id"])
            exp_states |= states_of(e)
            amount = e["amounts"]["amount"]
            if e["roles"]["payer"] != claimant:
                # ほかの人が支払った支出：控除を受ける人の損失に含めるかの一次情報がない（含める値で入れ、損失の金額を未確定にする）
                splits.append(
                    reading_split(
                        T_PAYER, e["id"], {"casualty_id": r["id"], "記録": [e["id"]], "支払者": e["roles"]["payer"], "person": claimant},
                        ("控除を受ける人の損失の金額に含める", "含めない"),
                    )
                )
            if not is_disaster and kind != "restoration":
                # 盗難・横領の原状回復以外の支出：第206条第1項第4号の「その他これに類する支出」に当たるか（一次情報なし）
                splits.append(
                    reading_split(T_THEFT, e["id"], {"casualty_id": r["id"], "記録": [e["id"]], "person": claimant}, ("類する支出に当たる", "当たらない"))
                )
            if kind == "restoration":
                restoration_total += amount
            else:
                exp_total += amount
        if portion is not None and restoration_total:
            if portion > restoration_total:
                self._exclude(acc, [claimant], R_PORTION, ids + judged_ids)
                return
            restoration_total = int(portion)  # 通達72−3：原状回復のための支出とする部分の額（判断）
            exp_ids += judged_ids
        exp_total += restoration_total
        exp_after = max(exp_total - rest, 0)
        loss = (damage_after if c.on.year == self.year else 0) + exp_after
        all_ids = ids + exp_ids + more_ids
        all_states = set(states) | exp_states | more_states
        acc.add(V_LOSS, claimant, loss, all_ids, all_states)
        acc.note(V_RELATED, claimant, all_ids, all_states)
        for var in (V_LOSS, V_RELATED):
            acc.use(var, claimant, uses)
        if is_disaster:
            acc.add(V_RELATED, claimant, exp_after, exp_ids, exp_states)
        if attribution is not None and attribution.candidates:
            # 所令第205条第2項の居住者が一次情報で決まらない：候補の全部の人の損失の金額を未確定にする（決める手段は一次情報）
            sp = reading_split(
                T_ATTRIBUTION, r["id"],
                {"casualty_id": r["id"], "所有者": pid, "理由": attribution.reason, "候補": list(attribution.candidates)},
                tuple(attribution.candidates),
            )  # fmt: skip
            for who_ in attribution.candidates:
                for var in (V_LOSS, V_RELATED):
                    acc.note(var, who_, all_ids, all_states)
                    if who_ != claimant:
                        acc.use(var, who_, uses)
                    acc.undetermined(var, who_, sp)
        if splits and loss > 0:
            for var in (V_LOSS, V_RELATED):
                for sp2 in splits:
                    acc.undetermined(var, claimant, sp2)

    def _claimant(self, c: _Casualty, acc: Acc) -> tuple[str, list[StageValue], list[str], set[State], Attribution | None] | None:
        """所令第205条で控除を受ける人を決める（決められなければ対象外にして None）。"""
        owner = c.owner
        kin, unknown = self._kin(c)
        living: list[str] = []
        ids: list[str] = []
        states: set[State] = set()
        for r in kin:
            dec = self.ctx.decision(J_SEIKEI, seikei_key(r, owner, c.on))
            k = kinship(self.idx, r, owner, c.on)
            ids += list(dec.record_ids) + list(k.record_ids)
            states |= set(dec.states) | set(k.states)
            if dec.value:
                living.append(r)
        if not living and not unknown:
            return owner, [], ids, states, None
        v0 = self.ctx.stage_value(STAGE_NAME, R_TOTAL_ETC, owner)
        if v0.pending:  # 最初の回（扶養の割当てより前）：値は最後の回で決まる
            return owner, [], ids, states, None
        if unknown:
            self._exclude(acc, [owner, *kin, *unknown], R_KIN, [c.record["id"]])
            return None
        uses: list[StageValue] = [v0]

        def read(var: str, p: str) -> Any:
            v = self.ctx.stage_value(STAGE_NAME, var, p)
            uses.append(v)
            return v.value

        living = [r for r in living if read(R_RESIDENT, r)]
        people = [owner, *living]
        measures = {p: int(read(R_TOTAL_ETC, p)) for p in people}
        limit = int(self.ctx.parameters.所得税.雑損控除.親族の総所得金額等の上限)
        claimant_of = str(read(R_CLAIMANT, owner) or "")
        dependent_of = claimant_of if claimant_of and read(R_ISDEP, owner) else None
        death = self.ctx.death_on(owner)
        on_ye = min(_dt.date(self.year, 12, 31), death) if death is not None else _dt.date(self.year, 12, 31)
        spouse_claimant = next(
            (r for r in sorted(self.persons - {owner}) if self.idx.spouse_record(r, owner, on_ye) is not None and read(R_SPOUSE, r)),
            None,
        )
        spouses = [r for r in living if self.idx.spouse_record(r, owner, c.on) is not None]
        res = attribute_claimant(owner, living, measures, limit, dependent_of=dependent_of, spouse_claimant=spouse_claimant, spouses=spouses)
        return res.claimant, uses, ids, states, res

    def _year_override_valid(self, c: _Casualty, e: Mapping[str, Any], paid: _dt.date) -> bool:
        for j in self._judged(c):
            y = j["value"].get("expenditure_tax_year")
            if y is None:
                continue
            if y == paid.year:
                return True
            return y == paid.year - 1 and paid <= _dt.date(paid.year, 3, 15) and y >= c.on.year
        return True

    def _exclude(self, acc: Acc, pids: list[str], reason: str, ids: list[str]) -> None:
        for pid in dict.fromkeys(pids):
            for var in (V_LOSS, V_RELATED):
                acc.exclude(var, pid, not_implemented(reason, ids))


STAGE = StageSpec(
    name=STAGE_NAME,
    title="雑損控除の親族の資産の所属（所得税法施行令第205条：扶養の割当ての結果と総所得金額等を読み、損失の金額を控除を受ける人に入れる）",
    reads=STAGE_READS,
    writes=(V_LOSS, V_RELATED),
    run=None,
    basis=(CASUALTY_RELATIVE_RULE,),
)


def _add_years(day: _dt.date, years: int) -> _dt.date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 2月29日
        return day.replace(year=day.year + years, day=28)


__all__ = ["STAGE", "STAGE_NAME", "Attribution", "CasualtyYear", "V_LOSS", "V_RELATED", "attribute_claimant"]
