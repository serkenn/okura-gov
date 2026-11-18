"""事実台帳・判断台帳（追記のみの JSON Lines）の検査：読み込み、畳み込み、改ざんの検出。"""

from __future__ import annotations

import copy
import hashlib
import json
import unittest

from okura_records import facts_ledger, judgments_ledger
from okura_records.jsonl_ledger import append_entry, encode_entry

from .helpers import household_fact_entries, household_judgment_entries, jsonl

P = {"person": "p-a"}


def fe(n: int, section: str = "persons", record=None, *, op: str = "add", at: str = "2026-01-05T20:00:00+09:00", **extra):
    entry = {"ledger": "okura-facts/0", "entry_id": f"fe-{n}", "recorded_at": at, "recorded_by": P, "op": op, "section": section}
    if record is not None:
        entry["record"] = record
    entry.update(extra)
    return entry


def person(pid: str, birth: str = "2000-01-01") -> dict:
    return {"id": pid, "birth_on": birth}


def codes(problems) -> set[str]:
    return {p.code for p in problems}


class HouseholdFoldTests(unittest.TestCase):
    def test_facts_fold(self):
        state, problems = facts_ledger.read(jsonl(household_fact_entries()), "facts.jsonl")
        self.assertEqual(problems, [])
        persons = {r.record["id"]: r for r in state.in_section("persons")}
        self.assertEqual(persons["p-c"].record["birth_on"], "2005-06-15")  # 訂正の後の値
        self.assertEqual(persons["p-c"].history, ("fe-0003", "fe-0012"))
        self.assertEqual(persons["p-c"].origin, "facts.jsonl:12 (fe-0012)")
        self.assertEqual(persons["p-c"].recorded_at, "2026-01-06T08:00:00+09:00")
        # 連鎖の最初の行の順に並ぶ（訂正しても位置は変わらない）
        self.assertEqual([r.record["id"] for r in state.in_section("persons")], ["p-a", "p-b", "p-c", "p-g"])
        # 取り消した記録は現在の状態に無い
        self.assertNotIn("cohab-ag-dup", [r.record["id"] for r in state.records])
        self.assertIn("rel-cohab-ag", [r.record["id"] for r in state.in_section("relations")])

    def test_judgments_fold_and_current_values(self):
        state, problems = judgments_ledger.read(jsonl(household_judgment_entries()), "judgments.jsonl")
        self.assertEqual(problems, [])
        ids = [r.record["id"] for r in state.in_section("judgments")]
        self.assertEqual(ids, ["j-livelihood-ac", "j-taxi-scope", "j-elec-ratio-v1", "j-elec-ratio-v2", "j-below-c"])
        v1 = next(r for r in state.records if r.record["id"] == "j-elec-ratio-v1")
        self.assertIn("平日だけ", v1.record["basis"]["method"])  # 行の訂正の後
        current = [r["id"] for r in judgments_ledger.current_values(state)]
        self.assertEqual(current, ["j-livelihood-ac", "j-taxi-scope", "j-elec-ratio-v2", "j-below-c"])  # 判断の見直しの後
        self.assertEqual([r.record["id"] for r in state.in_section("choices")], ["c-medical-2026", "c-npi-prepay-2026"])

    def test_fold_is_pure_and_deterministic(self):
        data = jsonl(household_fact_entries())
        entries, problems = facts_ledger.parse(data, "facts.jsonl")
        snapshot = copy.deepcopy(entries)
        first, _ = facts_ledger.fold(entries, "facts.jsonl")
        second, _ = facts_ledger.fold(entries, "facts.jsonl")
        self.assertEqual(first, second)
        self.assertEqual(entries, snapshot)

    def test_encode_is_canonical_and_appendable(self):
        entry = fe(1, record=person("p-a"))
        line = encode_entry(entry, None)
        self.assertEqual(line, encode_entry(dict(reversed(list(entry.items()))), None))
        self.assertTrue(line.endswith(b"\n"))
        data = append_entry(line, fe(2, record=person("p-b")))
        state, problems = facts_ledger.read(data, "f")
        self.assertEqual(problems, [])
        self.assertEqual(len(state.records), 2)


_DUMP_STATE = """
import json, sys
from okura_records import facts_ledger, judgments_ledger
out = []
for module, name in ((facts_ledger, sys.argv[1]), (judgments_ledger, sys.argv[2]), (facts_ledger, sys.argv[3])):
    with open(name, "rb") as fh:
        state, problems = module.read(fh.read(), "x")
    out.append([[r.section, r.entry_id, list(r.history), r.origin, r.recorded_at, r.record] for r in state.records])
    out.append([p.to_dict() for p in problems])
sys.stdout.write(json.dumps(out, ensure_ascii=False))  # キーを並べ替えない（dict の順も比べる）
"""


class FoldDeterminismTests(unittest.TestCase):
    """独立したレビューで足した検査：畳み込みが決定的であること（同じバイト列なら同じ状態・同じ問題の並び）。"""

    def faulty_facts(self) -> bytes:
        return jsonl(
            [
                fe(1, record=person("p-a")),
                fe(2, record=person("p-a", "2000-01-02"), op="correct", replaces="fe-1", reason="x"),
                fe(3, record=person("p-a", "2000-01-03"), op="correct", replaces="fe-1", reason="x"),  # 分岐
                fe(4, record=person("p-b")),
                fe(5, record=person("p-b")),  # record.id の重複
            ]
        )

    def test_same_bytes_same_state_under_different_hash_seeds(self):
        import os
        import subprocess
        import sys

        from .helpers import fresh_dir, write_bytes

        with fresh_dir() as d:
            names = [
                write_bytes(os.path.join(d, "facts.jsonl"), jsonl(household_fact_entries())),
                write_bytes(os.path.join(d, "judgments.jsonl"), jsonl(household_judgment_entries())),
                write_bytes(os.path.join(d, "faulty.jsonl"), self.faulty_facts()),
            ]
            outputs = set()
            for seed in ("0", "1", "4242"):
                env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
                env["PYTHONHASHSEED"] = seed  # -I では環境変数が効かないので、空の一時ディレクトリで -I なしで動かす
                done = subprocess.run([sys.executable, "-X", "utf8", "-c", _DUMP_STATE, *names], capture_output=True, cwd=d, env=env, timeout=60)
                self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
                outputs.add(done.stdout)
            self.assertEqual(len(outputs), 1, "ハッシュの種で畳み込みの結果が変わった")
            self.assertIn("entry_fork".encode(), next(iter(outputs)))

    def test_key_order_of_lines_does_not_change_the_state(self):
        # 行のキーの順・record のキーの順が違う（encode_entry で書いていない）台帳でも、現在の状態は同じ
        entries = household_fact_entries()

        def reverse_keys(value):
            if isinstance(value, dict):
                return {k: reverse_keys(value[k]) for k in reversed(list(value))}
            return value

        data = b""
        previous = None
        for entry in entries:
            line = json.dumps(reverse_keys({**entry, "prev_sha256": None if previous is None else hashlib.sha256(previous).hexdigest()}), ensure_ascii=False).encode()
            data += line + b"\n"
            previous = line
        canonical, problems_a = facts_ledger.read(jsonl(entries), "f")
        reordered, problems_b = facts_ledger.read(data, "f")
        self.assertEqual((problems_a, problems_b), ([], []))
        self.assertEqual(canonical, reordered)
        self.assertEqual(
            [json.dumps(r.record, sort_keys=True, ensure_ascii=False) for r in canonical.records],
            [json.dumps(r.record, sort_keys=True, ensure_ascii=False) for r in reordered.records],
        )

    def test_every_prefix_is_valid_and_replay_matches(self):
        # 追記のみ：どの時点の台帳も問題なく読め、1行ずつ足して読んだ最後の状態は、まとめて読んだ状態と同じ
        data = jsonl(household_fact_entries())
        lines = data.splitlines(keepends=True)
        state = None
        for k in range(1, len(lines) + 1):
            state, problems = facts_ledger.read(b"".join(lines[:k]), "f")
            self.assertEqual(problems, [], k)
        self.assertEqual(state, facts_ledger.read(data, "f")[0])

    def test_tail_truncation_is_not_detected_by_the_chain(self):
        # 限界の記録（README §4.2）：末尾の行を消しても連鎖は切れない。前の行の書き換え・削除・並べ替えだけを見つける
        # （取り消しの行 fe-0015 とその後の行を末尾から消す。2026-11-11 に例の行を足したので、位置を ID で探す）
        entries = household_fact_entries()
        k = next(i for i, e in enumerate(entries) if e["entry_id"] == "fe-0015")
        lines = jsonl(entries).splitlines(keepends=True)
        state, problems = facts_ledger.read(b"".join(lines[:k]), "f")
        self.assertEqual(problems, [])
        self.assertIn("cohab-ag-dup", [r.record["id"] for r in state.records])  # 取り消しの行が消え、取り消した記録が戻る


class TamperDetectionTests(unittest.TestCase):
    def setUp(self):
        self.data = jsonl([fe(1, record=person("p-a")), fe(2, record=person("p-b")), fe(3, record=person("p-c"))])

    def test_untouched_ledger_has_no_problems(self):
        self.assertEqual(facts_ledger.read(self.data, "f")[1], [])

    def test_edited_line_breaks_chain(self):
        tampered = self.data.replace(b'"2000-01-01","id":"p-a"', b'"1999-01-01","id":"p-a"', 1)
        self.assertNotEqual(tampered, self.data)
        _, problems = facts_ledger.read(tampered, "f")
        self.assertEqual([(p.where, p.code) for p in problems], [("f:2.prev_sha256", "chain_broken")])

    def test_deleted_or_reordered_line_breaks_chain(self):
        lines = self.data.splitlines(keepends=True)
        for label, data in (("deleted", lines[0] + lines[2]), ("reordered", lines[1] + lines[0] + lines[2])):
            with self.subTest(label):
                self.assertIn("chain_broken", codes(facts_ledger.read(data, "f")[1]))

    def test_first_line_must_have_null_prev(self):
        line = json.dumps({**fe(1, record=person("p-a")), "prev_sha256": "0" * 64}).encode() + b"\n"
        self.assertIn("chain_broken", codes(facts_ledger.read(line, "f")[1]))


class LineFormatTests(unittest.TestCase):
    def test_file_level_problems(self):
        good = jsonl([fe(1, record=person("p-a"))])
        cases = {
            "ledger_bom": b"\xef\xbb\xbf" + good,
            "ledger_cr": good.replace(b"\n", b"\r\n"),
            "ledger_no_final_newline": good[:-1],
            "ledger_not_utf8": good[:-3] + b"\xff\"}\n",
        }
        for code, data in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, codes(facts_ledger.read(data, "f")[1]))

    def test_line_level_problems(self):
        first = encode_entry(fe(1, record=person("p-a")), None)
        prev = first[:-1]
        cases = {
            "ledger_blank_line": first + b"\n",
            "json_syntax": first + b"{not json}\n",
            "json_duplicate_key": first + b'{"entry_id":"a","entry_id":"b"}\n',
            "json_constant": first + b'{"x": NaN}\n',
            "entry_field": first + encode_entry({**fe(2, record=person("p-b")), "extra": 1}, prev),
        }
        for code, data in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, codes(facts_ledger.read(data, "f")[1]))

    def test_field_checks(self):
        cases = [
            ("entry_ledger_mismatch", {**fe(1, record=person("p-a")), "ledger": "okura-judgments/0"}),
            ("entry_field", {k: v for k, v in fe(1, record=person("p-a")).items() if k != "recorded_by"}),
            ("entry_field", fe(1, record=person("p-a"), at="2026-02-30T10:00:00+09:00")),
            ("entry_field", fe(1, record=person("p-a"), at="2026-02-01T10:00:00")),
            ("entry_field", {**fe(1, record=person("p-a")), "entry_id": "行-1"}),
            ("entry_field", {**fe(1, record=person("p-a")), "recorded_by": {"person": "p-a", "label": "x"}}),
            ("entry_field", fe(1, "judgments", record=person("p-a"))),
            ("entry_field", fe(1, record={"birth_on": "2000-01-01"})),
            ("entry_op", {**fe(1, record=person("p-a")), "op": "update"}),
            ("entry_op", fe(1, record=person("p-a"), replaces="fe-0")),
            ("entry_op", fe(2, record=person("p-a"), op="correct", replaces="fe-1")),  # reason が無い
            ("entry_op", fe(2, record=person("p-a"), op="delete", replaces="fe-1", reason="x")),  # delete に record
            ("record_has_recorded_at", fe(1, "facts", record={"id": "f-1", "recorded_at": "2026-01-01T00:00:00+09:00"})),
        ]
        for code, entry in cases:
            with self.subTest(code=code, entry=entry):
                data = json.dumps({**entry, "prev_sha256": None}, ensure_ascii=False).encode() + b"\n"
                self.assertIn(code, codes(facts_ledger.read(data, "f")[1]))


class ReplacementTests(unittest.TestCase):
    def test_correct_and_delete(self):
        data = jsonl(
            [
                fe(1, record=person("p-a", "2000-01-01")),
                fe(2, record=person("p-a", "2000-01-02"), op="correct", replaces="fe-1", reason="訂正"),
                fe(3, record=person("p-b")),
                fe(4, op="delete", replaces="fe-3", reason="重複"),
            ]
        )
        state, problems = facts_ledger.read(data, "f")
        self.assertEqual(problems, [])
        self.assertEqual([r.record for r in state.records], [person("p-a", "2000-01-02")])

    def test_replacement_problems(self):
        cases = {
            "entry_replaces_unknown": [fe(1, record=person("p-a")), fe(2, record=person("p-a"), op="correct", replaces="fe-9", reason="x")],
            "entry_replaces_section": [
                fe(1, record=person("p-a")),
                fe(2, "facts", record={"id": "p-a"}, op="correct", replaces="fe-1", reason="x"),
            ],
            "entry_replaces_deleted": [
                fe(1, record=person("p-a")),
                fe(2, op="delete", replaces="fe-1", reason="x"),
                fe(3, record=person("p-a"), op="correct", replaces="fe-2", reason="x"),
            ],
            "entry_fork": [
                fe(1, record=person("p-a")),
                fe(2, record=person("p-a", "2000-01-02"), op="correct", replaces="fe-1", reason="x"),
                fe(3, record=person("p-a", "2000-01-03"), op="correct", replaces="fe-1", reason="x"),
            ],
            "entry_id_duplicate": [fe(1, record=person("p-a")), fe(1, record=person("p-b"))],
            "entry_time_order": [fe(1, record=person("p-a"), at="2026-02-01T00:00:00+09:00"), fe(2, record=person("p-b"), at="2026-01-31T23:59:59+09:00")],
            "record_id_duplicate": [fe(1, record=person("p-a")), fe(2, record=person("p-a"))],
        }
        for code, entries in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, codes(facts_ledger.read(jsonl(entries), "f")[1]))

    def test_forward_reference_is_unknown(self):
        entries = [fe(1, record=person("p-a"), op="correct", replaces="fe-2", reason="x"), fe(2, record=person("p-a"))]
        self.assertIn("entry_replaces_unknown", codes(facts_ledger.read(jsonl(entries), "f")[1]))

    def test_time_order_uses_offsets(self):
        # 時差が違っても実際の時刻で比べる（09:00+09:00 は 00:00Z と同じ）
        entries = [fe(1, record=person("p-a"), at="2026-02-01T09:00:00+09:00"), fe(2, record=person("p-b"), at="2026-02-01T00:00:00Z")]
        self.assertEqual(facts_ledger.read(jsonl(entries), "f")[1], [])


class JudgmentLedgerTests(unittest.TestCase):
    def je(self, n: int, record, at: str, section: str = "judgments"):
        return {"ledger": "okura-judgments/0", "entry_id": f"je-{n}", "recorded_at": at, "recorded_by": P, "op": "add",
                "section": section, "record": record}

    def test_judged_after_recorded(self):
        record = {"id": "j-1", "kind": "判断.生計を一にする", "judged_by": P, "judged_at": "2026-03-02T00:00:00+09:00",
                  "subject": {"person": "p-a", "other_person": "p-b"}, "when": {"from_on": "2026-01-01"}, "value": True}
        _, problems = judgments_ledger.read(jsonl([self.je(1, record, "2026-03-01T00:00:00+09:00")]), "j")
        self.assertIn("judged_after_recorded", codes(problems))
        choice = {"id": "c-1", "kind": "選択.還付申告", "chosen_by": "p-a", "chosen_at": "2026-03-02T00:00:00+09:00",
                  "subject": {"person": "p-a"}, "when": {"tax_year": 2026}, "value": True}
        _, problems = judgments_ledger.read(jsonl([self.je(1, choice, "2026-03-01T00:00:00+09:00", "choices")]), "j")
        self.assertIn("judged_after_recorded", codes(problems))

    def test_facts_section_not_allowed_in_judgments(self):
        entry = self.je(1, {"id": "p-a", "birth_on": "2000-01-01"}, "2026-03-01T00:00:00+09:00", "persons")
        self.assertIn("entry_field", codes(judgments_ledger.read(jsonl([entry]), "j")[1]))

    def test_facts_line_in_judgments_ledger(self):
        self.assertIn("entry_ledger_mismatch", codes(judgments_ledger.read(jsonl([fe(1, record=person("p-a"))]), "j")[1]))


if __name__ == "__main__":
    unittest.main()
