"""値ごとの候補の評価の、人と制度の境目（2026-11-13。B1 の直し：docs/measurements/20261113_family-run_findings.md）。

関数を直接呼ぶユニットテスト（D24）。OpenFisca の計算と situation の組み立てはスタブにする。
- attached_groups：値に由来を付けるグループは、値の概念が宣言したグループだけ（人をまたぐ値でも、ほかの制度のグループを付けない）。
- _closure の crossed：人をまたぐ辺を通った先で引いた変数だけを、ほかの人の値として読みうる変数にする（本人についてだけ読む変数は本人の分だけ）。
- _producer_dependencies_by_person：直積が上限を超える build_inputs の出力ごとの依存を、人ごとに、その人に関係する分かれ目だけの直積で決める。
- rules.juminzei.inputs.place_persons・municipal_slots：市町村・道府県の注入データの1か所に、その団体の注入データを引く人を宣言する。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from types import SimpleNamespace

from okura_core.candidates import Candidate, Slot
from okura_core.evaluate import _closure, _producer_dependencies_by_person, attached_groups
from okura_core.explain import TraceEntry
from okura_core.registry import ModuleInputs
from okura_core.result import Means
from okura_core.rules.juminzei import inputs as jm

ALL = ("扶養所属一覧", "法律婚一覧", "住民税扶養所属一覧", "健康保険一覧")


class AttachedGroupsTest(unittest.TestCase):
    def test_cross_person_value_gets_only_declared_groups(self) -> None:
        used = frozenset({"扶養所属一覧", "法律婚一覧"})
        # 所得税の人をまたぐ値（ひとり親など）に、住民税・健康保険のグループを付けない
        self.assertEqual(attached_groups(used, True, ALL), used)
        self.assertEqual(attached_groups(used, False, ALL), used)

    def test_no_declaration(self) -> None:
        self.assertEqual(attached_groups(frozenset(), False, ALL), frozenset())
        # 人をまたぐのに宣言したグループがない（宣言の漏れ）：安全側に全部
        self.assertEqual(attached_groups(frozenset(), True, ALL), frozenset(ALL))


P = "year:2026-01-01:1"


def _system(inputs: set[str], names: set[str]) -> SimpleNamespace:
    person = SimpleNamespace(is_person=True)
    return SimpleNamespace(
        variables={n: SimpleNamespace(entity=person, formulas={} if n in inputs else {"2025-01-01": object()}) for n in names}
    )


def _graph(children: dict[str, list[str]]) -> dict[tuple[str, str], TraceEntry]:
    return {(v, P): TraceEntry({(c, P) for c in cs}) for v, cs in children.items()}


class ClosureCrossedTest(unittest.TestCase):
    """X は 自分の入力・W（同じ人）・Y（人をまたぐ辺）・出力 P（同じ人）を引く。W は 自分の入力・共通の入力を、Y は ほかの人の入力・共通の入力・出力 O を引く。"""

    CHILDREN = {
        "X": ["自分の入力", "W", "Y", "P"],
        "W": ["Wの入力", "共通の入力"],
        "Y": ["ほかの人の入力", "共通の入力", "O"],
    }
    INPUTS = {"自分の入力", "Wの入力", "共通の入力", "ほかの人の入力"}
    NAMES = {"X", "W", "Y", "P", "O"} | INPUTS

    def _closure(self):
        return _closure(_graph(self.CHILDREN), "X", 2026, _system(self.INPUTS, self.NAMES), {"O", "P"}, frozenset({("X", "Y")}))  # type: ignore[arg-type]

    def test_only_variables_past_a_cross_person_edge_are_crossed(self) -> None:
        cl = self._closure()
        self.assertTrue(cl.cross)
        self.assertEqual(cl.variables, frozenset({"W", "Y"} | self.INPUTS))
        self.assertEqual(cl.out_deps, frozenset({"O", "P"}))
        # 共通の入力は、同じ人の道（W）と人をまたいだ先の道（Y）の両方で引く：どちらの順でたどっても、人をまたいだ先に入る
        self.assertEqual(cl.crossed, frozenset({"Y", "ほかの人の入力", "共通の入力", "O"}))

    def test_readers(self) -> None:
        cl = self._closure()
        scope = ["p", "q", "r"]
        self.assertEqual(list(cl.readers("自分の入力", "p", scope)), ["p"])  # 本人の級地など：ほかの人の分を依存に数えない
        self.assertEqual(list(cl.readers("Wの入力", "p", scope)), ["p"])
        self.assertEqual(list(cl.readers("P", "p", scope)), ["p"])
        self.assertEqual(list(cl.readers("ほかの人の入力", "p", scope)), scope)
        self.assertEqual(list(cl.readers("共通の入力", "p", scope)), scope)
        self.assertEqual(list(cl.readers("O", "p", scope)), scope)

    def test_no_cross_person_edge(self) -> None:
        cl = _closure(_graph(self.CHILDREN), "X", 2026, _system(self.INPUTS, self.NAMES), {"O", "P"}, frozenset())  # type: ignore[arg-type]
        self.assertFalse(cl.cross)
        self.assertEqual(cl.crossed, frozenset())

    def test_everything_below_a_crossed_variable_is_crossed(self) -> None:
        children = {"X": ["Y"], "Y": ["Z"], "Z": ["深い入力"]}
        names = {"X", "Y", "Z", "深い入力"}
        cl = _closure(_graph(children), "X", 2026, _system({"深い入力"}, names), set(), frozenset({("X", "Y")}))  # type: ignore[arg-type]
        self.assertEqual(cl.crossed, frozenset({"Y", "Z", "深い入力"}))


def _slot(sid: str, persons: tuple[str, ...], labels: tuple[str, ...] = ("a", "b")) -> Slot:
    return Slot(sid, Means.INJECTION, {"試験": sid}, tuple(Candidate(x, x) for x in labels), persons=persons)


class ProducerDependenciesByPersonTest(unittest.TestCase):
    """市町村ごとの分かれ目（人 p の市 Mp・人 q の市 Mq）と、人に結びつかない分かれ目 S。"""

    SLOTS = {s.id: s for s in (_slot("Mp", ("p",), ("1", "2", "3")), _slot("Mq", ("q",), ("1", "2", "3")), _slot("S", ()), _slot("Dp", ("p",)))}
    ORDER = {"Mp": 0, "Mq": 1, "S": 2, "Dp": 3}
    BASE = {"Mp": "1", "Mq": "1", "S": "a", "Dp": "a"}

    def _producer(self, calls: list[dict[str, str]]):
        def producer(comb):
            v = {**self.BASE, **{sid: c.value for sid, c in comb.items()}}
            calls.append(dict(v))
            read = {"Mp", "Mq", "S"}
            out = ModuleInputs()
            for person, m in (("p", v["Mp"]), ("q", v["Mq"])):
                out.set("級地の額", person, int(m) * 10)
                out.set("級地と共通", person, (m, v["S"]))
                out.set("繰越の記録", person, 0)  # 市町村の注入データと関係のない入力
            extra = "-"
            if v["Mp"] == "3":  # p の市が3級地のときだけ読む1か所
                read.add("Dp")
                extra = v["Dp"]
            out.set("条件つき", "p", extra)
            return out, read

        return producer

    def test_each_person_depends_only_on_related_slots(self) -> None:
        calls: list[dict[str, str]] = []
        first = [self.SLOTS["Mp"], self.SLOTS["Mq"], self.SLOTS["S"]]
        found = _producer_dependencies_by_person(self._producer(calls), first, self.SLOTS, self.ORDER.__getitem__, ["p", "q"])
        assert found is not None
        self.assertEqual(found[("v", ("級地の額", "p"))], {"Mp"})
        self.assertEqual(found[("v", ("級地の額", "q"))], {"Mq"})  # q の入力は、p だけが住む市の候補に依存しない
        self.assertEqual(found[("v", ("級地と共通", "p"))], {"Mp", "S"})
        self.assertEqual(found[("v", ("級地と共通", "q"))], {"Mq", "S"})
        self.assertNotIn(("v", ("繰越の記録", "p")), found)  # 以前の安全側の決め方では、読んだ全部の候補に依存した
        self.assertNotIn(("v", ("繰越の記録", "q")), found)
        self.assertEqual(found[("v", ("条件つき", "p"))], {"Mp", "Dp"})  # ある候補でだけ読む1か所も、読んだら足してやり直す
        # ほかの人の分かれ目は呼び出し側の組のまま（p の組では Mq を変えない）
        self.assertTrue(all(c["Mq"] == "1" for c in calls if c["Mp"] != "1"))

    def test_fewer_calls_than_the_full_product(self) -> None:
        calls: list[dict[str, str]] = []
        first = [self.SLOTS["Mp"], self.SLOTS["Mq"], self.SLOTS["S"]]
        # 全部の直積は 3×3×2×2＝36 組。人ごとなら p：3×2×2＝12 組、q：3×2＝6 組
        found = _producer_dependencies_by_person(self._producer(calls), first, self.SLOTS, self.ORDER.__getitem__, ["p", "q"], limit=18)
        self.assertIsNotNone(found)

    def test_changed_output_of_an_unlisted_person_gives_none(self) -> None:
        first = [self.SLOTS["Mp"], self.SLOTS["Mq"], self.SLOTS["S"]]
        # q を人の並びに入れない：q の出力が変わるのに人ごとに決められないので、呼び出し側が安全側にする
        self.assertIsNone(_producer_dependencies_by_person(self._producer([]), first, self.SLOTS, self.ORDER.__getitem__, ["p"]))

    def test_over_the_limit_gives_none(self) -> None:
        first = [self.SLOTS["Mp"], self.SLOTS["Mq"], self.SLOTS["S"]]
        self.assertIsNone(_producer_dependencies_by_person(self._producer([]), first, self.SLOTS, self.ORDER.__getitem__, ["p", "q"], limit=11))


class MunicipalSlotPersonsTest(unittest.TestCase):
    """架空の家族：p1 は市 131016 に住所・市 261009 に家屋敷、p2 は市 261009 に住所、p3（ID に「:」を含む）は市 131016 に住所。"""

    PLACES = {"p1:住所": "131016", "p1:家屋敷:261009": "261009", "p2:住所": "261009", "p:3:住所": "131016"}
    ON = _dt.date(2027, 1, 1)

    def test_place_persons(self) -> None:
        self.assertEqual(jm.place_persons(self.PLACES), {"131016": ("p1", "p:3"), "261009": ("p1", "p2")})

    def test_municipal_and_prefectural_slots_declare_persons(self) -> None:
        slots = {(s.issuer_kind, s.issuer_code): s for s in jm.municipal_slots(self.PLACES, ("municipality", "prefecture"), self.ON)}
        self.assertEqual(slots[("municipality", "131016")].persons, ("p1", "p:3"))
        self.assertEqual(slots[("municipality", "261009")].persons, ("p1", "p2"))
        # 道府県の1か所は、区域内の市町村の人の和
        self.assertEqual(slots[("prefecture", jm.issuer_code("prefecture", "131016"))].persons, ("p1", "p:3"))
        self.assertEqual(slots[("prefecture", jm.issuer_code("prefecture", "261009"))].persons, ("p1", "p2"))
        self.assertTrue(all(s.on == self.ON for s in slots.values()))

    def test_keep_filters_issuers(self) -> None:
        slots = jm.municipal_slots(self.PLACES, ("municipality",), self.ON, lambda kind, code: code == "261009")
        self.assertEqual([(s.issuer_code, s.persons) for s in slots], [("261009", ("p1", "p2"))])


if __name__ == "__main__":
    unittest.main()
