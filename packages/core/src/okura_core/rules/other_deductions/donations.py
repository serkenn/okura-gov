"""規則モジュール other_deductions：寄附の前処理（中間表現の donation → 寄附者の 特定寄附金の額・税額控除を受ける寄附金の額）。

- 特定寄附金（所得税法第78条第2項）：国又は地方公共団体に対する寄附金は、その年中に現実に支払ったもの（所得税基本通達78−1）を数える。
  学校の入学に関してするもの・特別の利益が及ぶものは除く（判断.寄附の性質。入学との関係の事実の記録があり判断がなければ両方で評価。
  事実の記録も判断もなければ、どちらにも当たらないものとして数える）。
- 税額控除を選べる寄附（選択.寄附金の控除の方式。未入力なら全候補で評価：D22 S20、全額どちらかの選択：措通41の18−2 ほか）：
  - 政党等（recipient_type: political_party。措法第41条の18第1項第1号・第2号の団体と読む）。令和8年分は、個人が令和8年1月1日以後に支出する
    公職の候補者が特定政党支部に対してする寄附（attributes.candidate_to_specified_party_branch）を除く（令和7年法律第2号附則第1条第2号・第5条）。
  - 認定NPO法人等（certified_npo。措法第41条の18の2）。
  - 公益社団法人等（public_interest_corporation・school_corporation。措法第41条の18の3第1項第1号）：
    税額控除の要件（公益性の証明書類）を満たすかは、税額控除を選んだことの前提とする（法令の読み。根拠に記録）。
  所得控除を選べば特定寄附金の額に入る（措法第41条の18第1項・第41条の18の2第1項・所法第78条第2項）。
- 日本赤十字社（japanese_red_cross）：特定公益増進法人（所法第78条第2項第3号）として特定寄附金に数える（TA1150 の特定寄附金の範囲の説明に
  「日本赤十字社等」：docs/public-sources/20261109_round2_hoken-kifu-nta-soumu.md §3.1。根拠の種類は国税庁の説明、主たる目的の業務に関連する
  寄附金とするのは法令の読み）。
- 共同募金会（community_chest。2026-11-12）：受領証等の記載（receipt_statement）によらず特定寄附金に数える。共同募金会は社会福祉法人
  （社会福祉法第113条第2項）で、社会福祉法人は所令第217条第1項第5号の特定公益増進法人。さらに昭和40年大蔵省告示第154号の第4号（財務大臣の承認を
  受けた募集）・第4号の2（社会福祉事業等の設備・経常的経費・民間奉仕活動の基金に充てる寄附金）は指定寄附金。どちらの読みでも第78条第2項の
  特定寄附金で額は同じ（docs/public-sources/20261112_impl-research4_juminzei-kifu-laws-and-kokuji.md#2.1・#2.3、docs/hypotheses/20261112_impl-research4_all-model.md#H11）。
  根拠には法令の読みの印（特定公益増進法人の読みにかかる第78条第2項第3号の業務関連の要件は、所法第78条第2項の本文を取り直していない留保：basis.DONATION_RULE）。
- そのほかの寄附先（other）：受領証等に記載された旨（attributes.receipt_statement。所規47の2③）で、
  指定寄附金である旨は第78条第2項第2号、特定公益増進法人の主たる目的である業務に関連する寄附金である旨は第3号、公益信託の信託事務に関連する
  寄附金である旨は第4号（令和8年4月1日〔公益信託に関する法律の施行の日〕前の支出は旧第3項の特定公益信託の支出と読む：法令の読み）の特定寄附金。
  other で「記載なし」は特定寄附金に当たらない（第2号〜第4号はどれも指定・法人・信託の要件があり、受領証等にその旨を書く：法令の読み）。
  other で記載（receipt_statement）がないものは両方で評価して未確定（c-入力：入力すれば決まる）。
  recipient_type の記載がない寄附は c-入力（入力すれば決まる）。

docs/public-sources/20261111_impl-research_seito-kifu-laws-and-nta.md、docs/public-sources/20261109_round2_hoken-kifu-laws.md §4。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from typing import Any

from ...candidates import Candidate
from ...registry import DecisionSlot, YearContext
from ...result import Means
from .facts import C_DONATION, J_DONATION, Acc, d, heads_for, not_implemented, on_year, reading_split, states_of

V_DONATION = "所得税_特定寄附金の額"
V_SEITO = "所得税_税額控除を受ける政党等寄附金の額"
V_NPO = "所得税_税額控除を受ける認定NPO法人等寄附金の額"
V_KOEKI = "所得税_税額控除を受ける公益社団法人等寄附金の額"
CREDIT_VARS: Mapping[str, str] = {"政党等": V_SEITO, "認定NPO法人等": V_NPO, "公益社団法人等": V_KOEKI}

#: 第78条第2項第1号の国又は地方公共団体（中間表現の recipient_type）。
GOVERNMENT = frozenset({"local_government", "national_government"})
#: 税額控除を選べる寄附先（中間表現の recipient_type → 税額控除の種類）。
CREDIT_TYPES: Mapping[str, str] = {
    "political_party": "政党等",
    "certified_npo": "認定NPO法人等",
    "public_interest_corporation": "公益社団法人等",
    "school_corporation": "公益社団法人等",
}
#: 「公職の候補者が特定政党支部に対してするもの」の除外の適用（個人が令和8年1月1日以後に支出する寄附：seito-kifu §4）。
PARTY_BRANCH_EXCLUSION_FROM = _dt.date(2026, 1, 1)
TAX_CREDIT = "tax_credit"
#: 所得税法第78条第2項第4号（公益信託の信託事務に関連する寄附金）の施行の日（公益信託に関する法律の施行の日：hoken-kifu-laws §1・§4）。
PUBLIC_TRUST_FROM = _dt.date(2026, 4, 1)
#: 受領証等に記載された旨のうち、特定寄附金に当たるもの（第78条第2項第2号〜第4号）。
SPECIFIED_STATEMENTS = frozenset({"designated_donation", "specified_public_interest_business", "public_interest_trust"})

R_RECIPIENT = "寄附先の区分（donation.attributes.recipient_type）の記載がない。入力すれば決まる"
#: 受領証等の記載によらず特定寄附金に数える寄附先：日本赤十字社（特定公益増進法人：TA1150 の説明）、共同募金会（所令217①五 の特定公益増進法人
#: 又は告示154号第4号・第4号の2 の指定寄附金：impl-research4 juminzei-kifu §2.1・§2.3。2026-11-12）。
SPECIFIED_PUBLIC_INTEREST = frozenset({"japanese_red_cross", "community_chest"})
#: 特定寄附金に当たるかを候補の両方で評価する寄附先 → (論点, 決める手段)。
BOTH_WAYS: Mapping[str, tuple[str, Means]] = {
    "other": ("寄附先が所得税法第78条第2項第2号〜第4号の寄附先（指定寄附金・特定公益増進法人・公益信託）か（受領証等の記載 receipt_statement がない）", Means.FACT),
}

#: value_of が返す「特定寄附金から除かれるか」の候補（判断の値の語彙では入学・特別の利益の2つの欄）。
EXCLUDED_CANDIDATES = (Candidate(False, "除かれない"), Candidate(True, "入学に関してする・特別の利益が及ぶ"))


def excluded_value(rec: Mapping[str, Any]) -> bool:
    v = rec["value"]
    return bool(v.get("admission_related") or v.get("special_benefit"))


class DonationYear:
    def __init__(self, ctx: YearContext) -> None:
        self.ctx = ctx
        self.persons = set(ctx.persons)
        self.donations = sorted(
            (r for r in ctx.records("donation") if on_year(r) == ctx.year and r["roles"]["donor"] in self.persons),
            key=lambda r: r["id"],
        )

    def _needs_judgment(self, r: Mapping[str, Any]) -> bool:
        return bool(r["attributes"].get("admission_related_facts")) or bool(heads_for(self.ctx, J_DONATION, "donation_id", r["id"]))

    def _excluded_branch(self, r: Mapping[str, Any]) -> bool:
        """令和8年分：公職の候補者が特定政党支部に対してする寄附は第41条の18の適用がない（seito-kifu §4）。"""
        return (
            r["attributes"].get("recipient_type") == "political_party"
            and bool(r["attributes"].get("candidate_to_specified_party_branch"))
            and d(r["when"]["on"]) >= PARTY_BRANCH_EXCLUSION_FROM
        )

    def _credit_kind(self, r: Mapping[str, Any]) -> str | None:
        return CREDIT_TYPES.get(r["attributes"].get("recipient_type") or "")

    def judgment_slots(self) -> list[DecisionSlot]:
        return [
            DecisionSlot(
                key=r["id"],
                target={"donation_id": r["id"], "person": r["roles"]["donor"]},
                matches=lambda j, rid=r["id"]: j["subject"]["donation_id"] == rid,
                candidates=EXCLUDED_CANDIDATES,
            )
            for r in self.donations
            if self._may_be_specified(r) and self._needs_judgment(r)
        ]

    def _may_be_specified(self, r: Mapping[str, Any]) -> bool:
        rtype = r["attributes"].get("recipient_type")
        return rtype in GOVERNMENT or rtype in SPECIFIED_PUBLIC_INTEREST or rtype in BOTH_WAYS or self._credit_kind(r) is not None

    @staticmethod
    def choice_key(donor: str, kind: str) -> str:
        return f"{donor}:{kind}"

    def choice_slots(self) -> list[DecisionSlot]:
        """選択.寄附金の控除の方式の1か所：寄附者 × 税額控除の種類ごと（その種類の寄附金の全額についてどちらか：措通41の18−2 ほか）。"""
        groups: dict[tuple[str, str], list[str]] = {}
        for r in self.donations:
            kind = self._credit_kind(r)
            if kind is not None and not self._excluded_branch(r):
                groups.setdefault((r["roles"]["donor"], kind), []).append(r["id"])
        return [
            DecisionSlot(
                key=self.choice_key(donor, kind),
                target={"person": donor, "寄附の区分": kind, "donation_ids": sorted(ids)},
                matches=lambda x, ids=frozenset(ids): x["subject"]["donation_id"] in ids,
                persons=(donor,),
            )
            for (donor, kind), ids in sorted(groups.items())
        ]

    def inputs(self, acc: Acc) -> None:
        for r in self.donations:
            pid = r["roles"]["donor"]
            ids = [r["id"]]
            rtype = r["attributes"].get("recipient_type")
            kind = self._credit_kind(r)
            acc.note(V_DONATION, pid, ids, states_of(r))
            if not self._may_be_specified(r):
                acc.exclude(V_DONATION, pid, not_implemented(R_RECIPIENT, ids))
                continue
            if self._needs_judgment(r):
                dec = self.ctx.decision(J_DONATION, r["id"])
                acc.note_decided(V_DONATION, pid, dec)
                if dec.value:
                    continue
            amount = r["amounts"]["amount"]
            if rtype in GOVERNMENT or rtype in SPECIFIED_PUBLIC_INTEREST:
                acc.add(V_DONATION, pid, amount, ids, states_of(r))
                continue
            statement = r["attributes"].get("receipt_statement")
            if rtype in BOTH_WAYS and statement in SPECIFIED_STATEMENTS:
                acc.add(V_DONATION, pid, amount, ids, states_of(r))  # 受領証等の記載で第2号〜第4号（旧第3項）の特定寄附金
                continue
            if rtype == "other" and statement == "none":
                continue  # 指定・特定公益増進法人・公益信託の記載がない：特定寄附金に当たらない（法令の読み）
            if rtype in BOTH_WAYS:
                topic, means = BOTH_WAYS[rtype]
                acc.add(V_DONATION, pid, amount, ids, states_of(r))
                if amount:
                    acc.undetermined(
                        V_DONATION, pid,
                        reading_split(topic, r["id"], {"person": pid, "記録": ids, "寄附先": r["attributes"]["recipient_name"]},
                                      ("特定寄附金に当たる", "当たらない"), means=means),
                    )  # fmt: skip
                continue
            if self._excluded_branch(r):
                continue  # 特定寄附金にも税額控除の対象にもならない
            assert kind is not None
            method = self.ctx.decision(C_DONATION, self.choice_key(pid, kind))
            for v in (V_DONATION, CREDIT_VARS[kind]):
                acc.note_decided(v, pid, method)
            if method.value == TAX_CREDIT:
                acc.add(CREDIT_VARS[kind], pid, amount, ids, states_of(r))
            else:
                acc.add(V_DONATION, pid, amount, ids, states_of(r))


__all__ = ["CREDIT_VARS", "DonationYear", "V_DONATION", "V_KOEKI", "V_NPO", "V_SEITO", "excluded_value"]
