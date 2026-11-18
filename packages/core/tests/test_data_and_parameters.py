"""規則モジュールの data/ の表（rules/kyuyo/data/ の別表第五の CSV）とパラメータの YAML（rules/<名前>/parameters/）の検査。

- 写した CSV の SHA-256 が、SOURCES.json の記録と、元のファイル（実測の出力 scripts/results/…）と一致すること。
- 表の区分に隙間・重なりがないこと（tables.py の読み込みの検査）。
- パラメータの全部の値に、出典（docs のファイル#節。ファイルがリポジトリにあること）・根拠の種類・法令の条がある。
  根拠の種類は自治体の資料でない。日付のキー（適用開始日）は1月1日（所得税は年分の全体に効く）。
- パラメータの YAML にタグ（!! など）を書かない（YAML はコードとして扱う。PyYAML の読み込みは安全でない：
  docs/measurements/20261109_R2-tools_openfisca-core-runtime.md T10）。
"""

from __future__ import annotations

import hashlib
import re
import unittest

from openfisca_core.parameters import Parameter

from okura_core.basis import INJECTION_ONLY_KINDS, ReadingFlag, SourceKind
from okura_core.country import parameter_dirs, parameter_file_hashes
from okura_core.rules.kyuyo.tables import DATA_DIR, DataFileError, _parse_beppyo5, load_beppyo5, sources

from .support import REPO, system


class TestDataFiles(unittest.TestCase):
    def test_sha256_matches_record_and_original(self) -> None:
        files = sources()["files"]
        self.assertEqual(sorted(files), ["beppyo5_2025-12-31.csv", "beppyo5_2026-12-01.csv"])
        for name, info in files.items():
            with self.subTest(name=name):
                digest = hashlib.sha256((DATA_DIR / name).read_bytes()).hexdigest()
                self.assertEqual(digest, info["sha256"])
                self.assertEqual(info["sha256"], info["original_sha256"])
                original = REPO / info["original"]
                if not original.exists():
                    self.skipTest(f"元のファイルがない: {original}")
                self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), info["original_sha256"])
                for ref in info["references"]:
                    self.assertTrue((REPO / ref.split("#")[0]).exists(), ref)

    def test_tables_load_and_are_contiguous(self) -> None:
        for table_id, n_rows, first_upper in (("beppyo5_2025-12-31", 1180, 651_000), ("beppyo5_2026-12-01", 1149, 691_000)):
            with self.subTest(table_id=table_id):
                t = load_beppyo5(table_id)
                self.assertEqual(len(t.rows), n_rows)  # docs/measurements/20261109_impl-prep_kyuyo-beppyo5.md §3 の区分の数
                self.assertEqual((t.rows[0].lower, t.rows[0].upper, t.rows[0].value), (0, first_upper, 0))
                last = t.rows[-1]
                self.assertEqual((last.kind, last.lower, last.value), ("point", 20_000_000, 18_050_000))

    def test_parser_rejects_gaps(self) -> None:
        header = "lower_incl,upper_excl,kind,value,formula_c,formula_rate_pct,struct,group,row,source_text\n"
        gap = header + "0,100,fixed,0,,,0,0,1,a\n200,300,fixed,1,,,0,0,2,b\n"
        with self.assertRaises(DataFileError):
            _parse_beppyo5(gap, "x.csv")
        bad_kind = header + "0,100,weird,0,,,0,0,1,a\n"
        with self.assertRaises(DataFileError):
            _parse_beppyo5(bad_kind, "x.csv")

    def test_unknown_table_is_rejected(self) -> None:
        with self.assertRaises(DataFileError):
            load_beppyo5("beppyo5_2099-01-01")


def _parameters(node) -> list[Parameter]:
    out: list[Parameter] = []
    for child in node.children.values():
        if isinstance(child, Parameter):
            out.append(child)
        else:
            out += _parameters(child)
    return out


class TestParameters(unittest.TestCase):
    def test_every_value_has_basis_metadata(self) -> None:
        params = _parameters(system().parameters)
        self.assertGreater(len(params), 20)
        for p in params:
            for at in p.values_list:
                meta = {**p.metadata, **at.metadata}
                with self.subTest(name=p.name, instant=at.instant_str):
                    kind = SourceKind.from_label(meta["source_kind"])
                    self.assertNotIn(kind, INJECTION_ONLY_KINDS)
                    self.assertTrue(meta.get("law"))
                    refs = meta["reference"]
                    self.assertTrue(refs)
                    for ref in refs:
                        self.assertTrue((REPO / ref.split("#")[0]).exists(), ref)
                    for f in meta.get("flags", []):
                        ReadingFlag.from_label(f)
                    self.assertTrue(at.instant_str.endswith("-01-01"), "所得税のパラメータの適用開始日は1月1日")
                    if "施行日" in meta:
                        self.assertRegex(str(meta["施行日"]), r"^\d{4}-\d{2}-\d{2}$")
                    self.assertNotIsInstance(at.value, float)

    def test_values_named_in_docs(self) -> None:
        """docs の値（kyuyo-sources §1.1・§2.1、R1 §2）と一致するか、パラメータの木から直接確かめる。"""
        p = system().parameters
        at = lambda d: system().get_parameters_at_instant(d)  # noqa: E731
        self.assertEqual(at("2025-01-01").所得税.扶養親族.合計所得金額の上限, 580_000)
        self.assertEqual(at("2026-01-01").所得税.扶養親族.合計所得金額の上限, 620_000)
        self.assertFalse(at("2025-01-01").所得税.給与所得.措法第29条の4第2項.適用)
        self.assertTrue(at("2026-01-01").所得税.給与所得.措法第29条の4第2項.適用)
        self.assertTrue(at("2027-01-01").所得税.給与所得.措法第29条の4第2項.適用)
        self.assertFalse(at("2028-01-01").所得税.給与所得.措法第29条の4第2項.適用)
        self.assertEqual(at("2025-01-01").所得税.給与所得.別表第五, "beppyo5_2025-12-31")
        self.assertEqual(at("2026-01-01").所得税.給与所得.別表第五, "beppyo5_2026-12-01")
        self.assertIsNotNone(p)

    def test_no_yaml_tags(self) -> None:
        tag = re.compile(r"(^|[\s:\[{,-])!")
        files = sorted(f for d in parameter_dirs() for f in d.rglob("*.yaml"))
        self.assertTrue(files)
        for f in files:
            text = f.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                with self.subTest(file=f.name, line=i):
                    self.assertIsNone(tag.search(line), line)

    def test_parameter_hashes_are_relative(self) -> None:
        h = parameter_file_hashes()
        self.assertTrue(h)
        for k in h:
            self.assertRegex(k, r"^rules/[a-z_]+/parameters/", k)
            self.assertNotIn(":", k)


if __name__ == "__main__":
    unittest.main()
