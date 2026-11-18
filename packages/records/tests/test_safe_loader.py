"""safe_loader の検査：攻撃の経路ごとに拒否すること、拒否したときにコードが実行されないこと。

どの試験も、まだ一度も使っていない新しい一時ディレクトリに台帳を作る。実行されるかを見るコードは、
一時ディレクトリに印のファイル（名前に marker を含む）を1つ書くだけ。拒否の試験では印のファイルが作られないことを確かめる。
「陽性対照」は、同じ台帳を beancount の loader（キャッシュなしの内部関数 `_load`）で読むと印のファイルが作られることを確かめ、
試験の台帳が本当にコードを実行するものであることを示す（実行されるのは印のファイルを書くコードだけ）。
"""

from __future__ import annotations

import contextlib
import os
import pickle
import sys
import time
import unicodedata
import unittest
from unittest import mock

from beancount import loader
from beancount.core import data as bc_data
from beancount.parser import parser as bc_parser
from beancount.parser import printer

from okura_records import safe_loader
from okura_records.safe_loader import Limits, check_text, load_ledger, longest_string_span

from .helpers import BASE_LEDGER, eval_plugin_line, fresh_dir, markers, plugin_module_source, write_bytes, write_text


def codes(result) -> set[str]:
    return {p.code for p in result.problems}


def run_beancount_loader(main: str) -> None:
    """陽性対照：beancount の loader（キャッシュなし）でそのまま読む。"""
    loader._load([(main, True)], None, None, None)


class _Base(unittest.TestCase):
    def assert_rejected(self, main: str, code: str, directory: str, *, root: str | None = None, limits: Limits | None = None):
        kwargs = {} if limits is None else {"limits": limits}
        result = load_ledger(main, root=root, **kwargs)
        self.assertFalse(result.ok, result)
        self.assertIsNone(result.ledger)
        self.assertIn(code, codes(result), [p.to_dict() for p in result.problems])
        self.assertEqual(markers(directory), [], "拒否したのに印のファイルが作られた")
        return result


class PluginAndOptionTests(_Base):
    def test_plugin_eval_in_config_is_rejected_and_not_executed(self):
        for module in ("beancount.plugins.check_commodity", "beancount.plugins.commodity_attr", "beancount.plugins.check_average_cost"):
            with self.subTest(module=module), fresh_dir() as d:
                main = write_text(os.path.join(d, "main.beancount"), eval_plugin_line(os.path.join(d, "eval_marker.txt"), module) + "\n" + BASE_LEDGER)
                self.assert_rejected(main, "plugin", d)
            with self.subTest(module=module, control=True), fresh_dir() as d:
                main = write_text(os.path.join(d, "main.beancount"), eval_plugin_line(os.path.join(d, "eval_marker.txt"), module) + "\n" + BASE_LEDGER)
                run_beancount_loader(main)
                self.assertEqual(markers(d), ["eval_marker.txt"], "陽性対照：loader では実行される")

    def test_plugin_in_included_file_is_rejected(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "sub.beancount"), eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n")
            main = write_text(os.path.join(d, "main.beancount"), 'include "sub.beancount"\n' + BASE_LEDGER)
            self.assert_rejected(main, "plugin", d)

    def test_indented_plugin_line_is_rejected(self):
        # 行頭に空白のある plugin 行も loader では有効（beancount-probe A5）
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + "  " + eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n")
            self.assert_rejected(main, "plugin", d)
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + "  " + eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n")
            run_beancount_loader(main)
            self.assertEqual(markers(d), ["eval_marker.txt"], "陽性対照")

    def test_insert_pythonpath_with_local_plugin_is_rejected_and_not_imported(self):
        name = "okura_test_plugin_a"
        with fresh_dir() as d:
            write_text(os.path.join(d, f"{name}.py"), plugin_module_source("plugin_marker.txt"))
            main = write_text(os.path.join(d, "main.beancount"), f'option "insert_pythonpath" "TRUE"\nplugin "{name}"\n' + BASE_LEDGER)
            result = self.assert_rejected(main, "insert_pythonpath", d)
            self.assertIn("plugin", codes(result))
            self.assertNotIn(name, sys.modules)
        with fresh_dir() as d:
            write_text(os.path.join(d, f"{name}.py"), plugin_module_source("plugin_marker.txt"))
            main = write_text(os.path.join(d, "main.beancount"), f'option "insert_pythonpath" "TRUE"\nplugin "{name}"\n' + BASE_LEDGER)
            try:
                run_beancount_loader(main)
                self.assertEqual(markers(d), ["plugin_marker.txt"], "陽性対照")
            finally:
                sys.modules.pop(name, None)

    def test_insert_pythonpath_in_include_is_rejected(self):
        name = "okura_test_plugin_b"
        with fresh_dir() as d:
            write_text(os.path.join(d, "sub", f"{name}.py"), plugin_module_source("plugin_marker.txt"))
            write_text(os.path.join(d, "sub", "sub.beancount"), 'option "insert_pythonpath" "TRUE"\n')
            main = write_text(os.path.join(d, "main.beancount"), f'include "sub/sub.beancount"\nplugin "{name}"\n' + BASE_LEDGER)
            result = self.assert_rejected(main, "insert_pythonpath", d)
            self.assertIn("plugin", codes(result))
            self.assertNotIn(name, sys.modules)

    def test_insert_pythonpath_lowercase_value_is_rejected(self):
        for value in ("true", "1", "TRUE"):
            with self.subTest(value=value), fresh_dir() as d:
                main = write_text(os.path.join(d, "main.beancount"), f'option "insert_pythonpath" "{value}"\n' + BASE_LEDGER)
                self.assert_rejected(main, "insert_pythonpath", d)

    def test_plugin_processing_mode_is_rejected(self):
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), 'option "plugin_processing_mode" "raw"\n' + BASE_LEDGER)
            self.assert_rejected(main, "plugin_processing_mode", d)

    def test_option_documents_is_rejected(self):
        with fresh_dir() as d:
            outside = os.path.join(d, "outside_docs")
            write_bytes(os.path.join(outside, "Expenses", "Misc", "2026-02-03.secret.pdf"), b"x")
            root = os.path.join(d, "ledger")
            main = write_text(os.path.join(root, "main.beancount"), f'option "documents" "{outside.replace(os.sep, "/")}"\n' + BASE_LEDGER)
            result = self.assert_rejected(main, "option_documents", d)
            self.assertFalse(any("secret" in p.message for p in result.problems))

    def test_plugin_inside_multiline_string_or_uppercase_is_not_a_plugin(self):
        # 文字列の中の plugin 行、大文字の PLUGIN は plugin にならない（構文の誤りとして拒否される）
        with fresh_dir() as d:
            marker = os.path.join(d, "eval_marker.txt")
            body = BASE_LEDGER + "PLUGIN" + eval_plugin_line(marker)[len("plugin"):] + "\n"
            main = write_text(os.path.join(d, "main.beancount"), body)
            self.assert_rejected(main, "beancount_error", d)


class PickleCacheTests(_Base):
    def _payload(self, marker: str) -> bytes:
        class Payload:
            def __reduce__(self):
                import pathlib

                return (pathlib.Path.write_text, (pathlib.Path(marker), "unpickled"))

        return pickle.dumps(Payload())

    def test_pickle_cache_is_never_read_or_touched(self):
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER)
            cache = write_bytes(os.path.join(d, ".main.beancount.picklecache"), self._payload(os.path.join(d, "pickle_marker.txt")))
            before = os.stat(cache)
            result = load_ledger(main)
            self.assertTrue(result.ok, result.problems)
            self.assertEqual(markers(d), [], "キャッシュの pickle が読まれた")
            self.assertTrue(os.path.exists(cache), "キャッシュのファイルを消した（触らないはず）")
            self.assertEqual(os.stat(cache).st_mtime_ns, before.st_mtime_ns)

    def test_pickle_cache_control_with_beancount_cache_enabled(self):
        # 陽性対照：beancount の既定（キャッシュあり）の load_file では pickle が読まれる
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER)
            write_bytes(os.path.join(d, ".main.beancount.picklecache"), self._payload(os.path.join(d, "pickle_marker.txt")))
            saved = loader._load_file
            try:
                loader.initialize(use_cache=True)
                try:
                    loader.load_file(main)
                except Exception:
                    pass  # 読み込み自体は失敗する（pickle の中身が台帳でないため）
            finally:
                loader._load_file = saved
            self.assertEqual(markers(d), ["pickle_marker.txt"], "陽性対照")


class IncludeAndPathTests(_Base):
    def test_include_outside_root_is_rejected_before_reading(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "outside.beancount"), eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n")
            root = os.path.join(d, "ledger")
            for inc in ("../outside.beancount", d.replace(os.sep, "/") + "/outside.beancount", "sub/../../outside.beancount"):
                with self.subTest(inc=inc):
                    main = write_text(os.path.join(root, "main.beancount"), f'include "{inc}"\n' + BASE_LEDGER)
                    self.assert_rejected(main, "include_form", d)

    def test_include_glob_and_other_extensions_are_rejected(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "notes.txt"), "password = hunter2\n")
            write_bytes(os.path.join(d, "x.gpg"), b"-----BEGIN PGP MESSAGE-----\n")
            for inc in ("*.beancount", "**/*.beancount", "sub/?.beancount", "notes.txt", "x.gpg", "x.asc", "main.BEANCOUNT", "日本語.beancount", ".hidden.beancount"):
                with self.subTest(inc=inc):
                    main = write_text(os.path.join(d, "main.beancount"), f'include "{inc}"\n' + BASE_LEDGER)
                    result = self.assert_rejected(main, "include_form", d)
                    self.assertFalse(any("hunter2" in p.message for p in result.problems), "台帳でないファイルの中身がエラーに出た")

    def test_windows_device_names_and_alternate_streams_are_rejected(self):
        with fresh_dir() as d:
            for inc in ("NUL.beancount", "con.beancount", "sub/COM1.beancount", "LPT9.beancount", "data.beancount:hidden"):
                with self.subTest(inc=inc):
                    main = write_text(os.path.join(d, "main.beancount"), f'include "{inc}"\n' + BASE_LEDGER)
                    self.assert_rejected(main, "include_form", d)

    def test_include_cycle_is_rejected(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "a.beancount"), 'include "main.beancount"\n')
            main = write_text(os.path.join(d, "main.beancount"), 'include "a.beancount"\ninclude "main.beancount"\n' + BASE_LEDGER)
            self.assert_rejected(main, "include_duplicate", d)

    def test_missing_include_is_rejected(self):
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), 'include "missing.beancount"\n' + BASE_LEDGER)
            self.assert_rejected(main, "not_found", d)

    @unittest.skipUnless(os.name == "nt", "ジャンクションは Windows だけ")
    def test_junction_to_outside_is_rejected(self):
        import _winapi

        with fresh_dir() as d:
            outside = os.path.join(d, "outside")
            write_text(os.path.join(outside, "x.beancount"), eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n")
            root = os.path.join(d, "ledger")
            os.makedirs(root)
            _winapi.CreateJunction(outside, os.path.join(root, "sub"))
            main = write_text(os.path.join(root, "main.beancount"), 'include "sub/x.beancount"\n' + BASE_LEDGER)
            self.assert_rejected(main, "link", d)
            # 最上位の台帳をジャンクションの中に置いたとき
            write_text(os.path.join(outside, "main2.beancount"), BASE_LEDGER)
            self.assert_rejected(os.path.join(root, "sub", "main2.beancount"), "link", d, root=root)

    def test_file_symlink_is_rejected(self):
        with fresh_dir() as d:
            outside = write_text(os.path.join(d, "outside.beancount"), eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n")
            root = os.path.join(d, "ledger")
            os.makedirs(root)
            try:
                os.symlink(outside, os.path.join(root, "linked.beancount"))
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"ファイルのシンボリックリンクを作れない（{exc.__class__.__name__}：権限・開発者モード）")
            main = write_text(os.path.join(root, "main.beancount"), 'include "linked.beancount"\n' + BASE_LEDGER)
            self.assert_rejected(main, "link", d)

    def test_symlink_detection_logic_with_simulated_realpath(self):
        # シンボリックリンクを作れない環境でも、判定の処理（実体のパスが見かけと違えば拒否）を確かめる
        from unittest import mock

        from okura_records import safe_loader

        with fresh_dir() as d:
            outside = write_text(os.path.join(d, "outside.beancount"), BASE_LEDGER)
            root = os.path.join(d, "ledger")
            linked = write_text(os.path.join(root, "linked.beancount"), BASE_LEDGER)
            main = write_text(os.path.join(root, "main.beancount"), 'include "linked.beancount"\n' + BASE_LEDGER)
            real = os.path.realpath

            def fake_realpath(p, *args, **kwargs):
                if os.path.normcase(os.path.normpath(p)) == os.path.normcase(linked):
                    return outside
                return real(p, *args, **kwargs)

            with mock.patch.object(safe_loader.path, "realpath", fake_realpath):
                result = load_ledger(main)
            self.assertIn("link", codes(result))

    def test_hard_link_is_rejected(self):
        with fresh_dir() as d:
            outside = write_text(os.path.join(d, "outside.beancount"), BASE_LEDGER)
            root = os.path.join(d, "ledger")
            os.makedirs(root)
            try:
                os.link(outside, os.path.join(root, "linked.beancount"))
            except OSError as exc:
                self.skipTest(f"ハードリンクを作れない（{exc}）")
            main = write_text(os.path.join(root, "main.beancount"), 'include "linked.beancount"\n')
            self.assert_rejected(main, "hard_link", d)

    def test_main_path_rules(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "main.txt"), BASE_LEDGER)
            write_text(os.path.join(d, "main.gpg"), BASE_LEDGER)
            write_text(os.path.join(d, "家計.beancount"), BASE_LEDGER)
            for name in ("main.txt", "main.gpg", "家計.beancount"):
                with self.subTest(name=name):
                    self.assert_rejected(os.path.join(d, name), "main_path", d)
            main = write_text(os.path.join(d, "a", "main.beancount"), BASE_LEDGER)
            os.makedirs(os.path.join(d, "b"))
            self.assert_rejected(main, "outside_root", d, root=os.path.join(d, "b"))

    def test_directory_as_ledger_is_rejected(self):
        with fresh_dir() as d:
            os.makedirs(os.path.join(d, "dir.beancount"))
            main = write_text(os.path.join(d, "main.beancount"), 'include "dir.beancount"\n' + BASE_LEDGER)
            self.assert_rejected(main, "not_regular_file", d)


class EncodingTests(_Base):
    def _ledger_with(self, d: str, data: bytes) -> str:
        return write_bytes(os.path.join(d, "main.beancount"), data)

    def test_encoding_tricks_are_rejected_before_parse(self):
        cases = {
            "bom": lambda pl: b"\xef\xbb\xbf" + pl + b"\n",
            "nul": lambda pl: pl.replace(b"plugin", b"plu\x00gin") + b"\n",
            "not_utf8": lambda pl: pl[:-4] + b"\xff\xfe" + pl[-4:] + b"\n",
            "bare_cr": lambda pl: BASE_LEDGER.encode().replace(b"\n", b"\r") + pl + b"\r",
            "control_char": lambda pl: b"\x0c" + pl + b"\n",
        }
        for code, make in cases.items():
            with self.subTest(code=code), fresh_dir() as d:
                payload = eval_plugin_line(os.path.join(d, "eval_marker.txt")).encode("utf-8")
                self.assert_rejected(self._ledger_with(d, make(payload) + BASE_LEDGER.encode()), code, d)

    def test_utf16_is_rejected(self):
        with fresh_dir() as d:
            text = eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n" + BASE_LEDGER
            for encoding in ("utf-16-le", "utf-16"):
                with self.subTest(encoding=encoding):
                    result = self.assert_rejected(self._ledger_with(d, text.encode(encoding)), "nul", d)
                    self.assertTrue({"nul"} <= codes(result))

    def test_plugin_line_positions(self):
        # 最終行で改行なし・取引の途中に字下げなし（beancount-probe A5 ではどちらも loader で実行された）
        layouts = {
            "last_line_without_newline": lambda pl: BASE_LEDGER + pl,
            "inside_transaction": lambda pl: BASE_LEDGER + '2026-01-02 * "x"\n  Expenses:Misc 1 JPY\n' + pl + "\n  Assets:Cash -1 JPY\n",
        }
        for label, make in layouts.items():
            with self.subTest(label), fresh_dir() as d:
                main = write_text(os.path.join(d, "main.beancount"), make(eval_plugin_line(os.path.join(d, "eval_marker.txt"))))
                self.assert_rejected(main, "plugin", d)

    def test_crlf_is_accepted(self):
        with fresh_dir() as d:
            main = self._ledger_with(d, BASE_LEDGER.replace("\n", "\r\n").encode())
            self.assertTrue(load_ledger(main).ok)

    def test_crlf_does_not_hide_plugin_line(self):
        with fresh_dir() as d:
            text = eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n" + BASE_LEDGER
            self.assert_rejected(self._ledger_with(d, text.replace("\n", "\r\n").encode()), "plugin", d)

    def test_metadata_key_error_drops_transaction_so_it_fails(self):
        # 日本語のキーの1行の誤りで、取引が黙って消える（beancount-probe B1）。エラーを失敗として扱う
        with fresh_dir() as d:
            text = BASE_LEDGER + '2026-01-02 * "x"\n  患者: "p-a"\n  Expenses:Misc 100 JPY\n  Assets:Cash\n'
            self.assert_rejected(write_text(os.path.join(d, "main.beancount"), text), "beancount_error", d)


class ResourceLimitTests(_Base):
    def test_long_line_is_rejected_without_parsing(self):
        with fresh_dir() as d:
            text = ";" + "x" * (70 * 1024) + "\n" + eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n"
            main = write_text(os.path.join(d, "main.beancount"), text)
            started = time.perf_counter()
            self.assert_rejected(main, "line_too_long", d)
            self.assertLess(time.perf_counter() - started, 5.0)

    def test_long_multiline_string_is_rejected_without_parsing(self):
        # 改行を含む文字列の字句も長さの2乗の時間がかかる（実装時に確かめた。README §3.3）。行の上限では止まらない
        with fresh_dir() as d:
            body = ("y" * 60 + "\n") * 2200  # 約 134 KB、どの行も短い
            text = BASE_LEDGER + f'2026-01-02 note Assets:Cash "{body}"\n'
            main = write_text(os.path.join(d, "main.beancount"), text)
            result = self.assert_rejected(main, "string_too_long", d)
            self.assertNotIn("line_too_long", codes(result))

    def test_longest_string_span(self):
        self.assertEqual(longest_string_span(b'a "bc" d'), 4)
        self.assertEqual(longest_string_span(b'"a\\"b"'), 6)  # エスケープした " は閉じない
        self.assertEqual(longest_string_span(b'"ab\\\ncd"'), 4)  # バックスラッシュと改行で字句は失敗する
        self.assertEqual(longest_string_span(b'"abc'), 4)  # 閉じない文字列はファイルの終わりまで
        self.assertEqual(longest_string_span(b'; comment "x\n' + b"z" * 100 + b'"'), 104)  # コメントの中の " も数える（控えめ）
        self.assertEqual(longest_string_span(b"no quotes"), 0)

    def test_check_text_accepts_ordinary_ledger(self):
        self.assertEqual(check_text(("; コメント\n" + BASE_LEDGER + '2026-01-02 * "架空" "説明"\n').encode()), [])

    def test_size_and_count_limits(self):
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER * 20)
            self.assert_rejected(main, "file_too_large", d, limits=Limits(max_file_bytes=200))
        with fresh_dir() as d:
            for i in range(3):
                write_text(os.path.join(d, f"s{i}.beancount"), "; x\n" * 40)
            includes = "".join(f'include "s{i}.beancount"\n' for i in range(3))
            main = write_text(os.path.join(d, "main.beancount"), includes)
            self.assert_rejected(main, "total_too_large", d, limits=Limits(max_total_bytes=300))
            self.assert_rejected(main, "too_many_files", d, limits=Limits(max_files=2))


class DocumentTests(_Base):
    def test_document_outside_root_is_rejected(self):
        with fresh_dir() as d:
            write_bytes(os.path.join(d, "secret.pdf"), b"x")
            root = os.path.join(d, "ledger")
            main = write_text(os.path.join(root, "main.beancount"), BASE_LEDGER + '2026-01-02 document Assets:Cash "../secret.pdf"\n')
            self.assert_rejected(main, "document_outside_root", d)

    def test_document_bad_names_are_rejected(self):
        with fresh_dir() as d:
            write_bytes(os.path.join(d, "receipt.pdf"), b"x")
            for name in ("receipt.pdf:hidden", "NUL.pdf", "sub/CON.pdf"):
                with self.subTest(name=name):
                    main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + f'2026-01-02 document Assets:Cash "{name}"\n')
                    self.assert_rejected(main, "document_path", d)

    def test_missing_document_is_rejected(self):
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + '2026-01-02 document Assets:Cash "nothing.pdf"\n')
            self.assert_rejected(main, "beancount_error", d)

    @unittest.skipUnless(os.name == "nt", "ジャンクションは Windows だけ")
    def test_document_through_junction_is_rejected(self):
        import _winapi

        with fresh_dir() as d:
            write_bytes(os.path.join(d, "outside", "secret.pdf"), b"x")
            root = os.path.join(d, "ledger")
            os.makedirs(root)
            _winapi.CreateJunction(os.path.join(d, "outside"), os.path.join(root, "docs"))
            main = write_text(os.path.join(root, "main.beancount"), BASE_LEDGER + '2026-01-02 document Assets:Cash "docs/secret.pdf"\n')
            self.assert_rejected(main, "link", d)

    def test_evidence_is_hashed(self):
        import hashlib

        with fresh_dir() as d:
            write_bytes(os.path.join(d, "receipts", "2026-01-02.架空薬局.pdf"), b"fictional receipt")
            main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + '2026-01-02 document Assets:Cash "receipts/2026-01-02.架空薬局.pdf"\n')
            result = load_ledger(main)
            self.assertTrue(result.ok, result.problems)
            (evidence,) = result.ledger.evidence.values()
            self.assertEqual(evidence.path, "receipts/2026-01-02.架空薬局.pdf")
            self.assertEqual(evidence.sha256, hashlib.sha256(b"fictional receipt").hexdigest())
            self.assertEqual(evidence.size, len(b"fictional receipt"))
            self.assert_rejected(main, "evidence_too_large", d, limits=Limits(max_evidence_bytes=4))


class CleanLedgerTests(unittest.TestCase):
    def test_same_entries_as_beancount_loader(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "sub", "accounts.beancount"), BASE_LEDGER + "2026-01-01 open Expenses:Medical JPY\n")
            write_bytes(os.path.join(d, "receipts", "r.pdf"), b"r")
            main = write_text(
                os.path.join(d, "main.beancount"),
                'option "operating_currency" "JPY"\ninclude "sub/accounts.beancount"\n'
                '2026-01-05 * "架空病院" "診察"\n  id: "tx-1"\n  patient: "p-a"\n  Expenses:Medical 1,500 JPY\n  Assets:Cash\n'
                '2026-01-05 document Expenses:Medical "receipts/r.pdf"\n'
                "2026-01-06 balance Assets:Cash -1500 JPY\n",
            )
            ours = load_ledger(main)
            self.assertTrue(ours.ok, ours.problems)
            entries, errors, _ = loader._load([(main, True)], None, None, None)
            self.assertEqual(errors, [])
            self.assertEqual([printer.format_entry(e) for e in ours.ledger.entries], [printer.format_entry(e) for e in entries])
            self.assertEqual([s.path for s in ours.ledger.source_files], ["main.beancount", "sub/accounts.beancount"])
            self.assertEqual(markers(d), [])

    def test_beancount_errors_fail(self):
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + '2026-01-02 * "x"\n  Expenses:Misc 100 JPY\n  Assets:Cash -90 JPY\n')
            result = load_ledger(main)
            self.assertIn("beancount_error", codes(result))
            self.assertTrue(all(p.where.startswith("main.beancount") for p in result.problems))

    def test_no_absolute_paths_in_problem_locations(self):
        with fresh_dir() as d:
            main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + "2026-01-02 open Assets:Cash JPY\n")
            result = load_ledger(main)
            self.assertFalse(result.ok)
            self.assertFalse(any(d.lower() in p.where.lower() for p in result.problems))


# ---------------------------------------------------------------------------
# 独立したレビューで足した攻撃（実装の担当とは別の経路）
# ---------------------------------------------------------------------------

_EXT = "\\\\?\\"  # Windows の拡張パスの接頭辞 \\?\


def _bc_string(text: str) -> str:
    """beancount の文字列の字句の中身（バックスラッシュをエスケープする）。"""
    return text.replace("\\", "\\\\")


@contextlib.contextmanager
def _recorded_fs_access():
    """ファイルシステムに触る関数の引数を記録する（UNC のパスで外のホストに触らないことを確かめる）。"""
    seen: list[str] = []

    def wrap(fn):
        def inner(p, *args, **kwargs):
            seen.append(str(p))
            return fn(p, *args, **kwargs)

        return inner

    with mock.patch("os.stat", wrap(os.stat)), mock.patch("os.lstat", wrap(os.lstat)), mock.patch(
        "builtins.open", wrap(open)
    ), mock.patch.object(safe_loader.path, "realpath", wrap(os.path.realpath)):
        yield seen


class ReviewIncludeTests(_Base):
    def test_include_chain_with_plugin_at_the_end(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "s", "c.beancount"), eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n")
            write_text(os.path.join(d, "s", "b.beancount"), 'include "c.beancount"\n')
            write_text(os.path.join(d, "a.beancount"), 'include "s/b.beancount"\n')
            main = write_text(os.path.join(d, "main.beancount"), 'include "a.beancount"\n' + BASE_LEDGER)
            self.assert_rejected(main, "plugin", d)
            # 連鎖の途中で親へ戻る include は形で拒否する
            write_text(os.path.join(d, "s", "b.beancount"), 'include "../s/c.beancount"\n')
            self.assert_rejected(main, "include_form", d)

    def test_deep_include_chain(self):
        with fresh_dir() as d:
            depth = 40
            for i in range(depth):
                last = i + 1 == depth
                body = eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n" if last else f'include "f{i + 1}.beancount"\n'
                write_text(os.path.join(d, f"f{i}.beancount"), body)
            main = write_text(os.path.join(d, "main.beancount"), 'include "f0.beancount"\n' + BASE_LEDGER)
            self.assert_rejected(main, "plugin", d)
            result = self.assert_rejected(main, "too_many_files", d, limits=Limits(max_files=10))
            self.assertNotIn("plugin", codes(result))  # 上限を超えた先は読まない

    @unittest.skipUnless(os.path.normcase("A") == "a", "大小文字を区別しないファイルシステムだけ")
    def test_case_variants_of_the_same_file_are_duplicates(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "sub.beancount"), "")
            for body in ('include "sub.beancount"\ninclude "SUB.beancount"\n', 'include "MAIN.beancount"\n', 'include "Main.beancount"\n'):
                with self.subTest(body=body):
                    main = write_text(os.path.join(d, "main.beancount"), body + BASE_LEDGER)
                    self.assert_rejected(main, "include_duplicate", d)

    def test_spoofed_extensions_and_names_are_rejected(self):
        with fresh_dir() as d:
            payload = eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n"
            write_text(os.path.join(d, "sub.beancount"), payload)
            write_text(os.path.join(d, "sub.txt"), payload)
            spoofs = (
                "sub.Beancount",
                "sub.BEANCOUNT",
                "sub.beancount.",
                "sub.beancount ",
                "sub.beancount\u200b",  # ゼロ幅の空白
                "sub.beanc\u043eunt",  # キリル文字の \u043e
                "\uff53ub.beancount",  # 全角の \uff53
                "sub\uff0ebeancount",  # 全角の \uff0e
                unicodedata.normalize("NFD", "s\u00fcb.beancount"),  # 結合文字
                "./sub.beancount",
                "sub//sub.beancount",
                "sub.txt/../sub.beancount",
                "SUB~1.beancount",  # 8.3 の短い名前
            )
            for inc in spoofs:
                with self.subTest(inc=inc):
                    main = write_text(os.path.join(d, "main.beancount"), f'include "{inc}"\n' + BASE_LEDGER)
                    self.assert_rejected(main, "include_form", d)
            # 右から左への上書き（txt を beancount に見せる）は parse の前に拒否する
            for inc in ("sub.txt\u202e", "\u202etnuocnaeb.txt"):
                with self.subTest(inc=inc):
                    main = write_text(os.path.join(d, "main.beancount"), f'include "{inc}"\n' + BASE_LEDGER)
                    self.assert_rejected(main, "bidi_control", d)


class ReviewEncodingTests(_Base):
    def test_bom_in_included_file(self):
        with fresh_dir() as d:
            write_bytes(os.path.join(d, "sub.beancount"), b"\xef\xbb\xbf" + eval_plugin_line(os.path.join(d, "eval_marker.txt")).encode() + b"\n")
            main = write_text(os.path.join(d, "main.beancount"), 'include "sub.beancount"\n' + BASE_LEDGER)
            self.assert_rejected(main, "bom", d)

    def test_crlf_in_included_file_does_not_hide_plugin(self):
        with fresh_dir() as d:
            write_bytes(os.path.join(d, "sub.beancount"), (eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\r\n").encode())
            main = write_bytes(os.path.join(d, "main.beancount"), ('include "sub.beancount"\n' + BASE_LEDGER).replace("\n", "\r\n").encode())
            self.assert_rejected(main, "plugin", d)

    def test_c1_controls_and_line_separators_are_rejected(self):
        # NEL（U+0085）・U+2028 などは beancount では改行にならない。エディタによっては改行に見えるので、
        # コメントの後ろに取引や plugin 行を「見えるのに無い」形で隠せる（陽性対照：beancount はそれを読まない）
        hidden = '2026-01-02 * "x"\n  Expenses:Misc 100 JPY\n  Assets:Cash\n'
        entries, _, _ = bc_parser.parse_string(BASE_LEDGER + "; memo\u0085" + hidden)
        self.assertEqual(sum(isinstance(e, bc_data.Transaction) for e in entries), 0, "陽性対照：NEL の後の取引はコメントの中")
        for sep in ("\u0085", "\u2028", "\u2029", "\u009b"):
            with self.subTest(sep=f"U+{ord(sep):04X}"), fresh_dir() as d:
                plugin = eval_plugin_line(os.path.join(d, "eval_marker.txt"))
                main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + "; memo" + sep + plugin + "\n" + "; memo" + sep + hidden)
                self.assert_rejected(main, "control_char", d)

    def test_bidi_controls_are_rejected(self):
        for ch in ("\u202e", "\u2066", "\u200f", "\u061c"):
            with self.subTest(ch=f"U+{ord(ch):04X}"), fresh_dir() as d:
                main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + f'2026-01-02 * "x{ch}"\n  Expenses:Misc 100 JPY\n  Assets:Cash\n')
                self.assert_rejected(main, "bidi_control", d)

    def test_ordinary_japanese_text_is_accepted(self):
        text = BASE_LEDGER + '; 全角の空白\u3000・長音ー・波ダッシュ〜・丸数字①\n2026-01-02 * "架空の店" "日用品（税込）"\n  Expenses:Misc 100 JPY\n  Assets:Cash\n'
        self.assertEqual(check_text(text.encode("utf-8")), [])


class ReviewResourceTests(_Base):
    def test_deeply_nested_expression_is_rejected_without_crash(self):
        for label, expr in (("parens", "(" * 20000 + "1" + ")" * 20000), ("unary_minus", "-" * 20000 + "1")):
            with self.subTest(label), fresh_dir() as d:
                main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + f'2026-01-02 * "x"\n  Expenses:Misc {expr} JPY\n  Assets:Cash\n')
                result = load_ledger(main)
                self.assertFalse(result.ok)
                self.assertTrue(result.problems)
                self.assertEqual(markers(d), [])


@unittest.skipUnless(os.name == "nt", "Windows のパスの形")
class ReviewWindowsPathTests(_Base):
    HOST = "okura-test-unreachable.invalid"

    def test_windows_path_forms_in_include_are_rejected_before_touching_them(self):
        with fresh_dir() as d:
            outside = write_text(os.path.join(d, "outside", "x.beancount"), eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n")
            root = os.path.join(d, "ledger")
            includes = (
                _EXT + outside,
                (_EXT + outside).replace("\\", "/"),
                f"\\\\{self.HOST}\\share\\x.beancount",
                f"//{self.HOST}/share/x.beancount",
                f"\\\\?\\UNC\\{self.HOST}\\share\\x.beancount",
                "\\\\.\\NUL",
                f"{d[0]}:x.beancount",  # ドライブの相対パス
                "/x.beancount",
                "\\x.beancount",
            )
            for inc in includes:
                with self.subTest(inc=inc):
                    main = write_text(os.path.join(root, "main.beancount"), f'include "{_bc_string(inc)}"\n' + BASE_LEDGER)
                    with _recorded_fs_access() as seen:
                        self.assert_rejected(main, "include_form", d)
                    self.assertFalse([p for p in seen if self.HOST in p], "UNC のホストに触った")

    def test_windows_path_forms_in_document_are_rejected_before_touching_them(self):
        with fresh_dir() as d:
            secret = write_bytes(os.path.join(d, "outside", "secret.pdf"), b"secret")
            root = os.path.join(d, "ledger")
            other_drive = "E" if d[0].upper() == "D" else "D"
            documents = (
                _EXT + secret,
                f"\\\\{self.HOST}\\share\\secret.pdf",
                f"//{self.HOST}/share/secret.pdf",
                f"\\\\?\\UNC\\{self.HOST}\\share\\secret.pdf",
                "\\\\.\\NUL",
                f"{other_drive}:secret.pdf",
                f"{d[0]}:../outside/secret.pdf",
                "/secret.pdf",
                "\\secret.pdf",
            )
            for doc in documents:
                with self.subTest(doc=doc):
                    main = write_text(os.path.join(root, "main.beancount"), BASE_LEDGER + f'2026-01-02 document Assets:Cash "{_bc_string(doc)}"\n')
                    with _recorded_fs_access() as seen, mock.patch.object(safe_loader, "_build", wraps=safe_loader._build) as build:
                        self.assert_rejected(main, "document_outside_root", d)
                    build.assert_not_called()  # beancount の verify_document_files_exist（path.exists）まで進まない
                    self.assertFalse([p for p in seen if self.HOST in p], "UNC のホストに触った")

    def test_superscript_device_names_in_document_are_rejected(self):
        with fresh_dir() as d:
            for name in ("COM\u00b9.pdf", "lpt\u00b3.pdf", "sub/COM\u00b2"):
                with self.subTest(name=name):
                    main = write_text(os.path.join(d, "main.beancount"), BASE_LEDGER + f'2026-01-02 document Assets:Cash "{name}"\n')
                    self.assert_rejected(main, "document_path", d)

    def test_extended_length_prefix_for_main_and_root(self):
        # main と root の片方だけに \\?\ があっても同じに読める（以前は root の外と誤って判定した）
        with fresh_dir() as d:
            root = os.path.join(d, "ledger")
            write_bytes(os.path.join(root, "r.pdf"), b"r")
            write_text(os.path.join(root, "sub.beancount"), '2026-01-02 document Assets:Cash "r.pdf"\n')
            main = write_text(os.path.join(root, "main.beancount"), 'include "sub.beancount"\n' + BASE_LEDGER)
            for m, r in ((_EXT + main, None), (main, _EXT + root), (_EXT + main, _EXT + root), (_EXT + main, root)):
                with self.subTest(main=m, root=r):
                    result = load_ledger(m, root=r)
                    self.assertTrue(result.ok, [p.to_dict() for p in result.problems])
                    self.assertEqual([s.path for s in result.ledger.source_files], ["main.beancount", "sub.beancount"])
                    self.assertEqual([e.path for e in result.ledger.evidence.values()], ["r.pdf"])
                    self.assertFalse(result.ledger.root.startswith(_EXT))
            write_bytes(os.path.join(d, "secret.pdf"), b"s")
            write_text(main, BASE_LEDGER + '2026-01-02 document Assets:Cash "../secret.pdf"\n')
            self.assert_rejected(_EXT + main, "document_outside_root", d, root=_EXT + root)
            self.assert_rejected(_EXT + main, "document_outside_root", d)

    def test_junctions_inside_root_and_to_parent_are_rejected(self):
        import _winapi

        with fresh_dir() as d:
            root = os.path.join(d, "ledger")
            write_text(os.path.join(root, "real", "x.beancount"), "")
            write_text(os.path.join(d, "outside.beancount"), eval_plugin_line(os.path.join(d, "eval_marker.txt")) + "\n")
            write_bytes(os.path.join(d, "secret.pdf"), b"s")
            inner, up = os.path.join(root, "j"), os.path.join(root, "up")
            _winapi.CreateJunction(os.path.join(root, "real"), inner)  # root の中から root の中へ
            _winapi.CreateJunction(d, up)  # root の親へ（ループ）
            try:
                for body in ('include "j/x.beancount"\n', 'include "up/outside.beancount"\n', 'include "up/ledger/main.beancount"\n'):
                    with self.subTest(body=body):
                        main = write_text(os.path.join(root, "main.beancount"), body + BASE_LEDGER)
                        self.assert_rejected(main, "link", d)
                main = write_text(os.path.join(root, "main.beancount"), BASE_LEDGER + '2026-01-02 document Assets:Cash "up/secret.pdf"\n')
                self.assert_rejected(main, "link", d)
            finally:
                os.rmdir(up)  # ジャンクションだけを消す（先は消さない）
                os.rmdir(inner)

    def test_root_that_is_a_junction_is_allowed(self):
        # root そのものの解決は利用者が選んだもの（中のファイルは root の実体の中で検査する）
        import _winapi

        with fresh_dir() as d:
            write_text(os.path.join(d, "real", "main.beancount"), BASE_LEDGER)
            link = os.path.join(d, "jroot")
            _winapi.CreateJunction(os.path.join(d, "real"), link)
            try:
                result = load_ledger(os.path.join(link, "main.beancount"))
                self.assertTrue(result.ok, result.problems)
                self.assertEqual(os.path.normcase(result.ledger.root), os.path.normcase(os.path.join(d, "real")))
            finally:
                os.rmdir(link)


if __name__ == "__main__":
    unittest.main()
