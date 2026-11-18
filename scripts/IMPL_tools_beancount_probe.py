"""IMPL（実装前の追加調査）tools: beancount 3.2.3 の実測。

調べること（docs/measurements/20261109_impl-prep_tools-beancount-probe.md に結果を書く）:
  A  安全な読み込み関数（R2 の prescan と、それを改めた prescan_v2）の「走査そのもの」が安全か
     A1 まだ一度も走査していない新しいディレクトリで、走査だけではコードが実行されないこと
     A2 parser.parse_file は include 先を辿らない（走査側が自分で辿る）こと
     A3 include の glob が root の外を歩くこと（R2 の prescan は glob の後で root を確かめる）
     A4 include の循環
     A5 エンコーディングの細工（BOM、UTF-16、NUL、不正な UTF-8、改行の種類など）で走査と読み込みの判定が食い違わないか
     A6 巨大なファイル（子プロセスで時間とメモリを測る）
     A7 パス（シンボリックリンク・ジャンクション・NUL などのデバイス名・NTFS の代替データストリーム）
     A8 option "documents" と document ディレクティブで root の外を指す
     A9 走査を -I なしで、台帳のディレクトリをカレントにして動かしたとき（同名のモジュールの差し替え）
     A10 走査と読み込みの間にファイルが変わったときの検出
  B  台帳 → 正規化した取引 JSON のアダプタの最小形（メタデータの型、document と証憑のハッシュ、決定性）

## 実行方法（リポジトリのルートで。R2 で作った隔離 venv を使う。新しいパッケージは入れない）
    .work/venvs/R2-beancount/Scripts/python.exe -I -X utf8 scripts/IMPL_tools_beancount_probe.py
  venv の作り方は scripts/R2_beancount_check.py の先頭（beancount==3.2.3 beanquery==0.2.0、--only-binary :all:）。
  出力: scripts/results/IMPL_tools_beancount_probe/results.json、summary.txt、normalized_sample.json

## 方針
- 台帳・プラグイン・pickle・巨大ファイルはすべてこのスクリプトが一時ディレクトリに生成し、最後に消す。
- 「任意コード実行」の確認で実行されるコードは、一時ディレクトリにマーカーファイルを1つ書くだけ。
- 外部への通信はしない。gpg は起動しない（.gpg/.asc の読み込みは試さない）。
"""

from __future__ import annotations

import ctypes
import glob
import hashlib
import io
import json
import os
import pickle
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from ctypes import wintypes
from os import path

os.environ["BEANCOUNT_DISABLE_LOAD_CACHE"] = "1"  # loader の import より前（loader.py:847）

import beancount  # noqa: E402
from beancount import loader  # noqa: E402
from beancount.core import data as bc_data  # noqa: E402
from beancount.parser import parser as bc_parser  # noqa: E402

HERE = path.dirname(path.abspath(__file__))
OUTDIR = path.join(HERE, "results", "IMPL_tools_beancount_probe")
RESULTS: dict = {}
TMP = ""  # main() で一時ディレクトリを作る（子プロセスでは作らない）
_counter = [0]


# ---------------------------------------------------------------- 共通
def scrub(obj):
    if isinstance(obj, str) and TMP:
        for p in (TMP, TMP.replace("\\", "/"), TMP.replace("\\", "\\\\")):
            obj = obj.replace(p, "<TMP>")
        return obj
    if isinstance(obj, dict):
        return {scrub(k): scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


def fresh(name: str) -> str:
    """まだ一度も使っていない新しい空のディレクトリ。"""
    _counter[0] += 1
    d = path.join(TMP, f"{_counter[0]:03d}_{name}")
    os.makedirs(d)
    return d


def wbytes(p: str, b: bytes) -> str:
    os.makedirs(path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(b)
    return p


def wtext(p: str, s: str) -> str:
    return wbytes(p, s.encode("utf-8"))


def errs(errors) -> list[str]:
    return [e.message.splitlines()[0][:200] for e in errors]


def record(key: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        RESULTS[key] = {"ok": True, "result": fn(), "seconds": round(time.perf_counter() - t0, 3)}
    except BaseException as e:  # noqa: BLE001
        RESULTS[key] = {"ok": False, "error_type": type(e).__name__, "error": str(e)[:2000],
                        "traceback_tail": traceback.format_exc().splitlines()[-8:],
                        "seconds": round(time.perf_counter() - t0, 3)}
    print(f"[{key}] {'ok' if RESULTS[key]['ok'] else 'NG'}", flush=True)


def eval_plugin_line(marker: str, mod: str = "beancount.plugins.check_commodity") -> str:
    tail = "and 0.01" if mod.endswith("check_average_cost") else "and {}"
    m = marker.replace("\\", "/")
    return f'plugin "{mod}" "__import__(\'pathlib\').Path(\'{m}\').write_text(\'eval executed\') {tail}"'


PLUGIN_SRC = '''
import os
_marker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin_marker.txt")
with open(_marker, "w", encoding="utf-8") as f:
    f.write("imported\\n")
__plugins__ = ("noop",)
def noop(entries, options_map):
    return entries, []
'''

BASE = "2026-01-01 open Assets:Cash JPY\n"


def markers_in(d: str) -> list[str]:
    return sorted(path.relpath(p, d) for p in glob.glob(path.join(d, "**", "*marker*"), recursive=True))


def peak_working_set_mb() -> float:
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return round(pmc.PeakWorkingSetSize / 2**20, 1)


# ---------------------------------------------------------------- 走査（R2 の prescan をそのまま写したもの）
def prescan_v1(main: str, root: str) -> dict:
    """scripts/R2_beancount_check.py の prescan と同じ処理（比較用）。"""
    root = path.realpath(root)
    problems, seen, stack = [], set(), [path.abspath(main)]
    while stack:
        f = path.normpath(stack.pop())
        if f in seen:
            continue
        seen.add(f)
        if not path.realpath(f).startswith(root + os.sep):
            problems.append(f"include outside root: {f}")
            continue
        if f.endswith((".gpg", ".asc")):
            problems.append(f"encrypted file (gpg would be run): {f}")
            continue
        _, _, opts = bc_parser.parse_file(f)
        for name, conf in opts["plugin"]:
            problems.append(f"plugin line: {name!r} in {f}")
        if opts.get("insert_pythonpath"):
            problems.append(f"insert_pythonpath in {f}")
        if opts.get("plugin_processing_mode") != "default":
            problems.append(f"plugin_processing_mode={opts['plugin_processing_mode']} in {f}")
        for inc in opts["include"]:
            pat = inc if path.isabs(inc) else path.join(path.dirname(f), inc)
            matched = glob.glob(pat, recursive=True)
            if not matched:
                problems.append(f"include matched nothing: {inc}")
            stack.extend(matched)
    return {"accepted": not problems, "problems": problems[:20], "n_problems": len(problems), "files": len(seen)}


# ---------------------------------------------------------------- 走査（改めたもの）
MAX_FILE_BYTES = 20 * 2**20
MAX_TOTAL_BYTES = 100 * 2**20
MAX_FILES = 500
MAX_LINE_BYTES = 64 * 1024  # 1行が長いと parse_file の時間が行の長さの2乗で増える（A6）ため、読む前に止める
INCLUDE_RE = re.compile(r"\A[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)*\.beancount\Z")


def _norm(p: str) -> str:
    return path.normcase(path.normpath(p))


def _inside(p: str, root_real: str) -> bool:
    return _norm(p).startswith(_norm(root_real) + os.sep)


def prescan_v2(main: str, root: str) -> dict:
    """読み込む前の走査（改めた版）。

    - include の文字列は、glob を使う前に形を検査する（相対・ASCII・'..' なし・ワイルドカードなし・拡張子 .beancount）。
    - 実体のパス（realpath）が見かけのパスと違う（リンク・ジャンクションなど）ファイル、root の外、通常のファイルでないものを拒否。
    - 大きさの上限を、読む前に stat で確かめる。
    - ファイルは1回だけバイト列で読み、そのバイト列の SHA-256 を取り、同じバイト列を parse_file に渡す。
    - UTF-8 として正しくない・BOM・NUL を含むファイルを拒否する。
    - 1行（LF までの長さ）が MAX_LINE_BYTES を超えるファイルは、parse_file に渡さずに拒否する。
    - plugin 行・insert_pythonpath・plugin_processing_mode・option "documents"・root の外を指す document を拒否する。
    """
    root_real = path.realpath(root)
    problems, files, seen, total = [], [], set(), 0
    stack = [path.abspath(main)]
    while stack:
        f = path.normpath(stack.pop())
        key = _norm(f)
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > MAX_FILES:
            problems.append("ファイルが多すぎる")
            break
        try:
            real = path.realpath(f, strict=True)
        except OSError as e:
            problems.append(f"開けない: {f}: {type(e).__name__}")
            continue
        if _norm(real) != key:
            problems.append(f"実体のパスが違う（リンク・ジャンクションなど）: {f} -> {real}")
            continue
        if not _inside(real, root_real):
            problems.append(f"root の外: {f}")
            continue
        st = os.stat(real)
        if not stat.S_ISREG(st.st_mode):
            problems.append(f"通常のファイルでない: {f}")
            continue
        if st.st_size > MAX_FILE_BYTES:
            problems.append(f"大きすぎる（{st.st_size} バイト）: {f}")
            continue
        total += st.st_size
        if total > MAX_TOTAL_BYTES:
            problems.append("合計が大きすぎる")
            break
        with open(real, "rb") as fh:
            data = fh.read(MAX_FILE_BYTES + 1)
        rel = path.relpath(real, root_real).replace(os.sep, "/")
        files.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        if data.startswith(b"\xef\xbb\xbf"):
            problems.append(f"BOM: {rel}")
        if b"\x00" in data:
            problems.append(f"NUL を含む: {rel}")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            problems.append(f"UTF-8 でない（{e.start} バイト目）: {rel}")
        longest = max((len(x) for x in data.split(b"\n")), default=0)
        if longest > MAX_LINE_BYTES:
            problems.append(f"行が長すぎる（{longest} バイト。parse しない）: {rel}")
            continue
        entries, perrors, opts = bc_parser.parse_file(io.BytesIO(data), report_filename=real)
        for name, _conf in opts["plugin"]:
            problems.append(f"plugin 行: {name!r}: {rel}")
        if opts.get("insert_pythonpath"):
            problems.append(f"insert_pythonpath: {rel}")
        if opts.get("plugin_processing_mode") != "default":
            problems.append(f"plugin_processing_mode: {rel}")
        if opts.get("documents"):
            problems.append(f"option documents（自動の走査は使わない）: {opts['documents']}: {rel}")
        for e in entries:
            if isinstance(e, bc_data.Document) and not _inside(e.filename, root_real):
                problems.append(f"document が root の外: {rel}:{e.meta.get('lineno')}")
        for inc in opts["include"]:
            if not INCLUDE_RE.match(inc):
                problems.append(f"include の形が許されない: {inc!r}: {rel}")
                continue
            stack.append(path.join(path.dirname(real), *inc.split("/")))
    return {"accepted": not problems, "problems": problems[:20], "n_problems": len(problems),
            "files": sorted(files, key=lambda x: x["path"])}


def safe_load(main: str, root: str, between=None) -> dict:
    scan = prescan_v2(main, root)
    if not scan["accepted"]:
        return {"ok": False, "stage": "prescan", "problems": scan["problems"]}
    if between is not None:
        between()
    loader.initialize(use_cache=False)
    entries, errors, opts = loader.load_file(main)
    root_real = path.realpath(root)
    loaded = sorted(path.relpath(path.realpath(p), root_real).replace(os.sep, "/") for p in opts["include"])
    scanned = sorted(x["path"] for x in scan["files"])
    changed = []
    for x in scan["files"]:
        with open(path.join(root_real, *x["path"].split("/")), "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != x["sha256"]:
                changed.append(x["path"])
    consistent = loaded == scanned and not changed
    return {"ok": consistent, "stage": "loaded", "errors": errs(errors), "loaded_files": loaded,
            "scanned_files": scanned, "changed_after_scan": changed,
            "_entries": entries, "_options": opts, "_scan": scan}


def public(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.startswith("_")}


# ---------------------------------------------------------------- A1 新しいディレクトリでの走査の安全性
def build_case(kind: str, d: str) -> str:
    main = path.join(d, "main.beancount")
    if kind == "4a_insert_pythonpath_plugin":
        wtext(path.join(d, "r2_harmless_plugin.py"), PLUGIN_SRC)
        wtext(main, 'option "insert_pythonpath" "TRUE"\nplugin "r2_harmless_plugin"\n' + BASE)
    elif kind.startswith("4c_eval_"):
        mod = "beancount.plugins." + kind[len("4c_eval_"):]
        wtext(main, eval_plugin_line(path.join(d, "eval_marker.txt"), mod) + "\n" + BASE)
    elif kind == "4d_plugin_in_include":
        wtext(path.join(d, "sub.beancount"), eval_plugin_line(path.join(d, "eval_marker.txt")) + "\n")
        wtext(main, 'include "sub.beancount"\n' + BASE)
    elif kind == "4e_insert_pythonpath_in_include":
        wtext(path.join(d, "sub", "r2_harmless_plugin.py"), PLUGIN_SRC)
        wtext(path.join(d, "sub", "sub.beancount"), 'option "insert_pythonpath" "TRUE"\n')
        wtext(main, 'include "sub/sub.beancount"\nplugin "r2_harmless_plugin"\n' + BASE)
    elif kind == "6_pickle_cache":
        wtext(main, BASE)
        marker = path.join(d, "pickle_marker.txt")

        class Payload:
            def __reduce__(self):
                import pathlib
                return (pathlib.Path.write_text, (pathlib.Path(marker), "pickle executed"))
        wbytes(path.join(d, ".main.beancount.picklecache"), pickle.dumps(Payload()))
    elif kind == "clean":
        wtext(main, BASE)
    return main


def a1():
    kinds = ["4a_insert_pythonpath_plugin", "4c_eval_check_commodity", "4c_eval_commodity_attr",
             "4c_eval_check_average_cost", "4d_plugin_in_include", "4e_insert_pythonpath_in_include",
             "6_pickle_cache", "clean"]
    out = {}
    for kind in kinds:
        row = {}
        for label, fn in [("prescan_v1（R2）", prescan_v1), ("prescan_v2", prescan_v2)]:
            d = fresh(f"a1_{kind}")
            main = build_case(kind, d)
            before = markers_in(d)
            r = fn(main, d)
            row[label] = {"accepted": r["accepted"], "problems": r["problems"][:3], "マーカー（前）": before,
                          "マーカー（走査の後）": markers_in(d)}
            sys.modules.pop("r2_harmless_plugin", None)
        d = fresh(f"a1_{kind}_safe_load")
        main = build_case(kind, d)
        r = safe_load(main, d)
        row["safe_load"] = {"ok": r["ok"], "stage": r["stage"], "problems_or_errors": (r.get("problems") or r.get("errors"))[:3],
                            "マーカー（後）": markers_in(d),
                            "pickle キャッシュのファイルが残っているか": path.exists(path.join(d, ".main.beancount.picklecache"))}
        sys.modules.pop("r2_harmless_plugin", None)
        out[kind] = row
    return out


# ---------------------------------------------------------------- A2 parse_file は include を辿らない
def a2():
    d = fresh("a2")
    wtext(path.join(d, "sub.beancount"), eval_plugin_line(path.join(d, "eval_marker.txt")) + "\nこれは台帳ではない\n")
    main = wtext(path.join(d, "main.beancount"), 'include "sub.beancount"\ninclude "missing.beancount"\ninclude "*.nothing"\n' + BASE)
    entries, errors, opts = bc_parser.parse_file(main)
    return {"parse_file(main) の include": opts["include"], "plugin": opts["plugin"], "errors": errs(errors),
            "entries": [type(e).__name__ for e in entries], "マーカー": markers_in(d),
            "prescan_v1": prescan_v1(main, d), "prescan_v2": prescan_v2(main, d)}


# ---------------------------------------------------------------- A3 glob が root の外を歩く
def a3():
    parent = fresh("a3_parent")
    root = path.join(parent, "ledger")
    os.makedirs(root)
    outside = path.join(parent, "outside_tree")
    n_dirs = 0
    for i in range(100):
        for j in range(50):
            os.makedirs(path.join(outside, f"d{i:03d}", f"e{j:02d}"))
            n_dirs += 1
    wtext(path.join(outside, "d000", "e00", "x.beancount"), BASE)
    out = {"root の外に作ったディレクトリ数": n_dirs}
    for label, inc in [("相対 ../**/*.beancount", "../**/*.beancount"),
                       ("相対 ../outside_tree/**/*.nothing（一致なし）", "../outside_tree/**/*.nothing")]:
        main = wtext(path.join(root, "main.beancount"), f'include "{inc}"\n' + BASE)
        t = time.perf_counter()
        r1 = prescan_v1(main, root)
        t1 = time.perf_counter() - t
        t = time.perf_counter()
        r2 = prescan_v2(main, root)
        t2 = time.perf_counter() - t
        g = glob.glob(path.join(root, inc), recursive=True)
        out[label] = {"glob の一致数": len(g), "prescan_v1": {"accepted": r1["accepted"], "n_problems": r1["n_problems"],
                                                         "problems": r1["problems"][:2], "seconds": round(t1, 3)},
                      "prescan_v2": {"accepted": r2["accepted"], "problems": r2["problems"][:2], "seconds": round(t2, 4)}}
    # 絶対パスのワイルドカード（実際には走らせない。v2 が glob の前に拒否することだけを確かめる）
    main = wtext(path.join(root, "main.beancount"), 'include "C:/**/*.beancount"\n' + BASE)
    t = time.perf_counter()
    r2 = prescan_v2(main, root)
    out["絶対パス C:/**/*.beancount（v2 だけ。v1 はディスク全体を歩くので実行しない）"] = {
        "accepted": r2["accepted"], "problems": r2["problems"], "seconds": round(time.perf_counter() - t, 4)}
    return out


# ---------------------------------------------------------------- A4 循環
def a4():
    out = {}
    d = fresh("a4_cycle")
    wtext(path.join(d, "a.beancount"), 'include "main.beancount"\n')
    main = wtext(path.join(d, "main.beancount"), 'include "a.beancount"\ninclude "main.beancount"\n' + BASE)
    loader.initialize(use_cache=False)
    _, errors, _ = loader.load_file(main)
    out["main ↔ a、main → main"] = {"prescan_v1": prescan_v1(main, d), "prescan_v2": prescan_v2(main, d),
                                     "loader のエラー": errs(errors)}
    d = fresh("a4_glob_self")
    main = wtext(path.join(d, "main.beancount"), 'include "*.beancount"\n' + BASE)
    _, errors, _ = loader.load_file(main)
    out["include \"*.beancount\"（自分を含む）"] = {"prescan_v1": prescan_v1(main, d), "prescan_v2": prescan_v2(main, d),
                                                 "loader のエラー": errs(errors)}
    return out


# ---------------------------------------------------------------- A5 エンコーディングの細工
def a5():
    out = {}

    def variants(marker):
        pl = eval_plugin_line(marker).encode("utf-8")
        base = BASE.encode("utf-8")
        return {
            "対照（そのまま）": pl + b"\n" + base,
            "UTF-8 BOM ＋ plugin 行（1行目）": b"\xef\xbb\xbf" + pl + b"\n" + base,
            "UTF-8 BOM ＋ 空行 ＋ plugin 行": b"\xef\xbb\xbf\n" + pl + b"\n" + base,
            "CRLF": (pl + b"\n" + base).replace(b"\n", b"\r\n"),
            "CR だけ": (pl + b"\n" + base).replace(b"\n", b"\r"),
            "NUL の行の後に plugin 行": b"\x00\n" + pl + b"\n" + base,
            "plugin 行の途中に NUL": pl.replace(b"plugin", b"plu\x00gin", 1) + b"\n" + base,
            "plugin 行の後に NUL": pl + b"\n\x00\n" + base,
            "不正な UTF-8 のコメントの後に plugin 行": b"; \xff\xfe\n" + pl + b"\n" + base,
            "plugin の設定文字列の中に不正な UTF-8": pl.replace(b"eval executed", b"eval \xff executed", 1) + b"\n" + base,
            "UTF-16LE（BOM あり）": (b"\xff\xfe" + (pl.decode() + "\n" + BASE).encode("utf-16-le")),
            "UTF-16LE（BOM なし）": (pl.decode() + "\n" + BASE).encode("utf-16-le"),
            "行頭に空白（字下げ）": b"  " + pl + b"\n" + base,
            "行頭にタブ": b"\t" + pl + b"\n" + base,
            "全角の ｐｌｕｇｉｎ": pl.replace(b"plugin", "ｐｌｕｇｉｎ".encode("utf-8"), 1) + b"\n" + base,
            "大文字の PLUGIN": pl.replace(b"plugin", b"PLUGIN", 1) + b"\n" + base,
            "U+2028（行区切り）で区切る": base.rstrip(b"\n") + "\u2028".encode("utf-8") + pl + b"\n",
            "フォームフィード（0x0C）の後に plugin 行": b"\x0c" + pl + b"\n" + base,
            "1 MB の長いコメント行の後に plugin 行": b";" + b"x" * (1 << 20) + b"\n" + pl + b"\n" + base,
            "最終行が plugin 行で改行なし": base + pl,
            "文字列の中に改行と plugin 行": base + b'2026-01-02 note Assets:Cash "abc\n' + pl.replace(b'"', b"'") + b'\nend"\n',
            "取引の中に plugin 行": base + b'2026-01-03 * "x"\n  Assets:Cash  1 JPY\n' + pl + b"\n  Assets:Cash  -1 JPY\n",
            "option \"insert_pythonpath\" \"true\"（小文字）": b'option "insert_pythonpath" "true"\n' + base,
            "option \"insert_pythonpath\" \"1\"": b'option "insert_pythonpath" "1"\n' + base,
        }

    probe_dir = fresh("a5_probe")
    for label in variants("x").keys():
        row = {}
        d = fresh("a5")
        marker = path.join(d, "eval_marker.txt")
        main = wbytes(path.join(d, "main.beancount"), variants(marker)[label])
        r1 = prescan_v1(main, d)
        r2 = prescan_v2(main, d)
        row["prescan_v1"] = {"accepted": r1["accepted"], "problems": r1["problems"][:2]}
        row["prescan_v2"] = {"accepted": r2["accepted"], "problems": r2["problems"][:3]}
        row["走査の後のマーカー"] = markers_in(d)
        # 比較：走査を通さずに loader で読む（コードが実行されるかを見る。中身はマーカーを書くだけ）
        loader.initialize(use_cache=False)
        try:
            _, errors, opts = loader.load_file(main)
            row["loader（走査なし）"] = {"コードが実行されたか": path.exists(marker), "options の plugin": [p[0] for p in opts["plugin"]],
                                       "insert_pythonpath": opts.get("insert_pythonpath"), "errors": errs(errors)[:3]}
        except Exception as e:  # noqa: BLE001
            row["loader（走査なし）"] = {"コードが実行されたか": path.exists(marker), "例外": f"{type(e).__name__}: {str(e)[:200]}"}
        row["v1 が受け入れたのにコードが実行された（すり抜け）"] = r1["accepted"] and path.exists(marker)
        row["v2 が受け入れたのにコードが実行された（すり抜け）"] = r2["accepted"] and path.exists(marker)
        out[label] = row
    shutil.rmtree(probe_dir, ignore_errors=True)
    return out


# ---------------------------------------------------------------- A6 巨大なファイル（子プロセス）
def child(task: str, arg: str) -> dict:
    out = {"task": task}
    t = time.perf_counter()
    if task == "parse":
        _, errors, opts = bc_parser.parse_file(arg)
        out.update(parse_s=round(time.perf_counter() - t, 2), n_errors=len(errors), plugin=[p[0] for p in opts["plugin"]])
    elif task == "prescan_v1":
        r = prescan_v1(arg, path.dirname(arg))
        out.update(seconds=round(time.perf_counter() - t, 2), accepted=r["accepted"], problems=r["problems"][:2])
    elif task == "prescan_v2":
        r = prescan_v2(arg, path.dirname(arg))
        out.update(seconds=round(time.perf_counter() - t, 3), accepted=r["accepted"], problems=r["problems"][:2])
    elif task == "load":
        loader.initialize(use_cache=False)
        entries, errors, _ = loader.load_file(arg)
        out.update(load_s=round(time.perf_counter() - t, 2), n_entries=len(entries), n_errors=len(errors))
        t2 = time.perf_counter()
        norm = normalize(entries, path.dirname(arg), [])
        out.update(normalize_s=round(time.perf_counter() - t2, 2), n_tx=len(norm["transactions"]))
    out["peak_working_set_MB"] = peak_working_set_mb()
    return out


def run_child(task: str, arg: str, timeout=900) -> dict:
    t = time.perf_counter()
    try:
        p = subprocess.run([sys.executable, "-I", "-X", "utf8", path.abspath(__file__), "--child", task, arg],
                           capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        wall = round(time.perf_counter() - t, 2)
        try:
            body = json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            body = {"stdout": p.stdout.decode("utf-8", "replace")[-300:], "stderr": p.stderr.decode("utf-8", "replace")[-500:]}
        return {"returncode": p.returncode, "wall_s": wall, **body}
    except subprocess.TimeoutExpired:
        return {"timeout": True, "timeout_s": timeout}


def a6():
    out = {}
    d = fresh("a6_big")
    n = 100_000
    lines = ["2020-01-01 open Assets:Cash JPY", "2020-01-01 open Expenses:Food JPY"]
    for i in range(n):
        day = 1 + i % 28
        lines.append(f'2026-01-{day:02d} * "店{i % 97}" "買い物{i}"\n  id: "tx-{i:07d}"\n  Expenses:Food  {100 + i % 900} JPY\n  Assets:Cash')
    big = wtext(path.join(d, "main.beancount"), "\n".join(lines) + "\n")
    size = path.getsize(big)
    out[f"取引 {n:,} 件（{size / 2**20:.1f} MB）"] = {t: run_child(t, big) for t in ["parse", "prescan_v1", "prescan_v2", "load"]}
    # 1行が長いファイル：大きさを倍々にして parse_file の時間を測る（1回 240 秒で打ち切り、打ち切ったら止める）
    # 注：最初の版では 60 MB の1行で parse_file が CPU 時間 600 秒を超えても終わらなかったため、この形に改めた。
    ladder = {}
    for mb in [1, 2, 4, 8, 16]:
        d = fresh(f"a6_longline_{mb}MB")
        longf = path.join(d, "main.beancount")
        with open(longf, "wb") as f:
            f.write(b";" + b"x" * (mb << 20) + b"\n" + eval_plugin_line(path.join(d, "eval_marker.txt")).encode() + b"\n" + BASE.encode())
        r = run_child("parse", longf, timeout=240)
        ladder[f"{mb} MB の1行"] = r
        if r.get("timeout"):
            break
    out["1行のコメント（x の繰り返し）の後に plugin 行：parse_file の時間"] = ladder
    t = time.perf_counter()
    r3 = prescan_v2(longf, path.dirname(longf))
    out[f"最後に作った {mb} MB の1行のファイルを prescan_v2（行の長さの上限 {MAX_LINE_BYTES} バイト）"] = {
        "accepted": r3["accepted"], "problems": r3["problems"], "seconds": round(time.perf_counter() - t, 4)}
    d = fresh("a6_toolarge")
    big2 = path.join(d, "main.beancount")
    with open(big2, "wb") as f:
        f.write(b";" + b"x" * (21 << 20) + b"\n" + BASE.encode())
    t = time.perf_counter()
    r2 = prescan_v2(big2, d)
    out["21 MB のファイルを prescan_v2（大きさの上限 20 MB）"] = {"accepted": r2["accepted"], "problems": r2["problems"],
                                                         "seconds": round(time.perf_counter() - t, 4)}
    # 行の数が多い（短い行）なら速いかの対照：1 MB ごとに改行を入れた 16 MB
    d = fresh("a6_manylines")
    many = path.join(d, "main.beancount")
    with open(many, "wb") as f:
        for _ in range(16):
            f.write(b";" + b"x" * ((1 << 20) - 2) + b"\n")
        f.write(BASE.encode())
    out["対照：1 MB の行を16行（16 MB）"] = run_child("parse", many, timeout=240)
    return out


# ---------------------------------------------------------------- A7 パス
def a7():
    out = {}
    parent = fresh("a7")
    root = path.join(parent, "ledger")
    outside = path.join(parent, "outside")
    os.makedirs(root)
    os.makedirs(outside)
    wtext(path.join(outside, "evil.beancount"), eval_plugin_line(path.join(outside, "eval_marker.txt")) + "\n")
    # シンボリックリンク（権限が無ければ作れない）
    try:
        os.symlink(path.join(outside, "evil.beancount"), path.join(root, "link.beancount"))
        made = True
    except OSError as e:
        made = f"作れなかった: {type(e).__name__}: {e.winerror if hasattr(e, 'winerror') else ''}"
    if made is True:
        main = wtext(path.join(root, "main.beancount"), 'include "link.beancount"\n' + BASE)
        out["ファイルのシンボリックリンク（root の中 → 外）"] = {"作成": True, "prescan_v1": prescan_v1(main, root), "prescan_v2": prescan_v2(main, root)}
    else:
        out["ファイルのシンボリックリンク（root の中 → 外）"] = {"作成": made}
    # ジャンクション（ディレクトリ。管理者権限は要らない）
    try:
        import _winapi
        _winapi.CreateJunction(outside, path.join(root, "junction"))
        main = wtext(path.join(root, "main.beancount"), 'include "junction/evil.beancount"\n' + BASE)
        out["ディレクトリのジャンクション（root の中 → 外）"] = {
            "作成": True, "realpath": path.realpath(path.join(root, "junction", "evil.beancount")),
            "prescan_v1": prescan_v1(main, root), "prescan_v2": prescan_v2(main, root),
            "マーカー（走査の後）": markers_in(outside)}
    except Exception as e:  # noqa: BLE001
        out["ディレクトリのジャンクション（root の中 → 外）"] = {"作成": f"作れなかった: {type(e).__name__}: {e}"}
    # デバイス名 NUL（開いても空なので安全）
    main = wtext(path.join(root, "main.beancount"), 'include "NUL"\n' + BASE)
    out['include "NUL"'] = {"glob": glob.glob(path.join(root, "NUL")), "realpath": path.realpath(path.join(root, "NUL")),
                            "prescan_v1": prescan_v1(main, root), "prescan_v2": prescan_v2(main, root)}
    loader.initialize(use_cache=False)
    _, errors, opts = loader.load_file(main)
    out['include "NUL"']["loader"] = {"errors": errs(errors), "読んだファイル": opts["include"]}
    # デバイス名 CON（読むとコンソールの入力を待つおそれがあるので、v1 は子プロセスで時間を区切って走らせる。loader では読まない）
    main = wtext(path.join(root, "main.beancount"), 'include "CON"\n' + BASE)
    out['include "CON"'] = {"glob": glob.glob(path.join(root, "CON")), "realpath": path.realpath(path.join(root, "CON")),
                            "prescan_v1（子プロセス、20秒で打ち切り）": run_child("prescan_v1", main, timeout=20),
                            "prescan_v2": prescan_v2(main, root)}
    # NTFS の代替データストリーム
    try:
        wtext(path.join(root, "data.beancount"), BASE)
        with open(path.join(root, "data.beancount") + ":hidden", "wb") as f:
            f.write(eval_plugin_line(path.join(root, "ads_marker.txt")).encode() + b"\n")
        main = wtext(path.join(root, "main.beancount"), 'include "data.beancount:hidden"\n' + BASE)
        out["代替データストリーム data.beancount:hidden"] = {"prescan_v1": prescan_v1(main, root), "prescan_v2": prescan_v2(main, root),
                                                     "マーカー（走査の後）": markers_in(root)}
    except OSError as e:
        out["代替データストリーム data.beancount:hidden"] = {"作成": f"作れなかった: {e}"}
    return out


# ---------------------------------------------------------------- A8 documents が root の外
def a8():
    out = {}
    parent = fresh("a8")
    root = path.join(parent, "ledger")
    outside = path.join(parent, "outside_docs")
    wtext(path.join(outside, "Expenses", "Medical", "2026-02-03.他人の書類.pdf"), "dummy")
    wtext(path.join(outside, "secret.pdf"), "dummy")
    main = wtext(path.join(root, "main.beancount"),
                 f'option "documents" "{outside.replace(chr(92), "/")}"\n2026-01-01 open Expenses:Medical JPY\n'
                 '2026-01-05 document Expenses:Medical "../outside_docs/secret.pdf"\n'
                 '2026-01-06 document Expenses:Medical "../outside_docs/no-such-file.pdf"\n')
    loader.initialize(use_cache=False)
    entries, errors, _ = loader.load_file(main)
    docs = [{"filename": e.filename, "date": str(e.date)} for e in entries if isinstance(e, bc_data.Document)]
    out["loader（走査なし）"] = {"Document": docs, "errors": errs(errors)}
    out["prescan_v1"] = prescan_v1(main, root)
    out["prescan_v2"] = prescan_v2(main, root)
    return out


# ---------------------------------------------------------------- A9 -I なしで台帳のディレクトリをカレントにする
def a9():
    out = {}
    d = fresh("a9_shadow")
    wtext(path.join(d, "main.beancount"), BASE)
    # 走査のコードが import するモジュール名と同じ名前の .py を台帳のディレクトリに置く
    wtext(path.join(d, "glob.py"), "import pathlib\npathlib.Path(__file__).with_name('glob_marker.txt').write_text('shadowed')\n"
                                   "from fnmatch import fnmatch as _f\n")
    code = ("import sys; sys.path.insert(1, sys.argv[1]); import glob; print(glob.__file__)")
    # 走査のスクリプトを模して、-c で glob を import する（sys.argv[1] は使わない形にするためダミー）
    for label, flags in [("-I -X utf8（推奨）", ["-I", "-X", "utf8"]), ("-X utf8 だけ（-I なし）", ["-X", "utf8"])]:
        for p in glob.glob(path.join(d, "glob_marker.txt")):
            os.remove(p)
        r = subprocess.run([sys.executable, *flags, "-c", "import glob; print(glob.__file__)"], cwd=d,
                           capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        out[label] = {"import された glob": r.stdout.decode("utf-8", "replace").strip().replace(TMP, "<TMP>"),
                      "マーカー": markers_in(d)}
    del code
    return out


# ---------------------------------------------------------------- A10 走査と読み込みの間の変更
def a10():
    d = fresh("a10")
    main = wtext(path.join(d, "main.beancount"), 'include "sub.beancount"\n' + BASE)
    wtext(path.join(d, "sub.beancount"), "2026-01-01 open Assets:Bank JPY\n")

    def tamper():
        wtext(path.join(d, "sub.beancount"), "2026-01-01 open Assets:Bank JPY\n2026-01-01 open Assets:Other JPY\n")
    r = safe_load(main, d, between=tamper)
    d2 = fresh("a10_clean")
    main2 = wtext(path.join(d2, "main.beancount"), 'include "sub.beancount"\n' + BASE)
    wtext(path.join(d2, "sub.beancount"), "2026-01-01 open Assets:Bank JPY\n")
    r2 = safe_load(main2, d2)
    return {"走査の後に sub.beancount を書き換えた": public(r), "書き換えない": public(r2)}


# ---------------------------------------------------------------- B アダプタ
SKIP_META = {"filename", "lineno"}
VOCAB = {"id": "string", "payer": "string", "patient": "string", "person": "string", "txid": "string",
         "visit-date": "date", "memo": "string"}


def _meta_value(v):
    import datetime
    from decimal import Decimal
    from beancount.core.amount import Amount
    if isinstance(v, bool):
        return {"bool": v}
    if isinstance(v, Decimal):
        return {"decimal": str(v)}
    if isinstance(v, datetime.date):
        return {"date": v.isoformat()}
    if isinstance(v, Amount):
        return {"amount": str(v.number), "currency": v.currency}
    if isinstance(v, str):
        return {"string": v}
    if v is None:
        return {"null": True}
    return {"unknown_type": type(v).__name__, "repr": repr(v)[:80]}


def _meta(meta: dict) -> dict:
    return {k: _meta_value(v) for k, v in sorted(meta.items()) if k not in SKIP_META and not k.startswith("__")}


def _src(meta: dict, root: str) -> dict:
    fn = meta.get("filename")
    rel = path.relpath(fn, root).replace(os.sep, "/") if fn and path.isabs(fn) else fn
    return {"file": rel, "line": meta.get("lineno")}


def normalize(entries, root: str, problems: list) -> dict:
    """台帳のエントリ → 正規化した取引 JSON。法令の解釈は含めない（並べ替え、型の明示、パスの相対化、ハッシュだけ）。"""
    root = path.realpath(root)
    txs, docs, ids = [], [], {}
    for e in entries:
        if isinstance(e, bc_data.Transaction):
            m = e.meta
            tid = m.get("id")
            if not isinstance(tid, str):
                problems.append({"種類": "id が無いか文字列でない", "場所": _src(m, root)})
            elif tid in ids:
                problems.append({"種類": "id の重複", "id": tid, "場所": [ids[tid], _src(m, root)]})
            else:
                ids[tid] = _src(m, root)
            txs.append({
                "id": tid if isinstance(tid, str) else None,
                "date": e.date.isoformat(), "flag": e.flag, "payee": e.payee, "narration": e.narration,
                "tags": sorted(e.tags), "links": sorted(e.links), "meta": _meta(m), "source": _src(m, root),
                "postings": [{"account": p.account,
                              "number": None if p.units is None or p.units.number is None else str(p.units.number),
                              "currency": None if p.units is None else p.units.currency,
                              "cost": None if p.cost is None else {"number": str(p.cost.number), "currency": p.cost.currency, "date": str(p.cost.date)},
                              "price": None if p.price is None else {"number": str(p.price.number), "currency": p.price.currency},
                              "interpolated": bool((p.meta or {}).get("__automatic__", False)),
                              "meta": _meta(p.meta or {})} for p in e.postings]})
        elif isinstance(e, bc_data.Document):
            real = path.realpath(e.filename)
            item = {"date": e.date.isoformat(), "account": e.account, "meta": _meta(e.meta), "source": _src(e.meta, root),
                    "tags": sorted(e.tags or []), "links": sorted(e.links or [])}
            if not _inside(real, root):
                problems.append({"種類": "document が root の外", "場所": item["source"]})
                item["path"] = None
            elif not path.isfile(real):
                problems.append({"種類": "document のファイルが無い", "場所": item["source"]})
                item["path"] = path.relpath(real, root).replace(os.sep, "/")
            else:
                with open(real, "rb") as fh:
                    b = fh.read()
                item.update(path=path.relpath(real, root).replace(os.sep, "/"), sha256=hashlib.sha256(b).hexdigest(), bytes=len(b))
            docs.append(item)
    # 語彙の検査（決まったキーと型だけを中間表現に使う）
    for t in txs:
        for k, v in t["meta"].items():
            want = VOCAB.get(k)
            if want is None:
                problems.append({"種類": "語彙に無いメタデータのキー", "id": t["id"], "キー": k})
            elif want not in v:
                problems.append({"種類": "メタデータの型が違う", "id": t["id"], "キー": k, "期待": want, "実際": sorted(v)})
    for doc in docs:
        tx = doc["meta"].get("txid", {}).get("string")
        if tx is not None and tx not in ids:
            problems.append({"種類": "document の txid が指す取引が無い", "txid": tx, "場所": doc["source"]})
    txs.sort(key=lambda t: (t["date"], t["id"] or "", t["source"]["file"] or "", t["source"]["line"] or 0))
    docs.sort(key=lambda x: (x["date"], x.get("path") or "", x["source"]["line"] or 0))
    return {"transactions": txs, "documents": docs}


SAMPLE = '''option "operating_currency" "JPY"
2026-01-01 open Assets:Cash:Taro JPY
2026-01-01 open Assets:Bank:Taro JPY
2026-01-01 open Expenses:Medical JPY
2026-01-01 open Income:Job:Konbini JPY
2026-01-01 open Assets:Cash:Jiro JPY

2026-01-10 * "山田医院" "初診料（次郎）" ^tx-2026-0001
  id: "tx-2026-0001"
  payer: "太郎"
  patient: "次郎"
  visit-date: 2026-01-09
  Expenses:Medical   3000 JPY
    memo: "保険適用後の自己負担"
  Assets:Cash:Taro

2026-01-10 document Expenses:Medical "receipts/2026-01-10.山田医院.pdf" ^tx-2026-0001
  txid: "tx-2026-0001"

2026-02-03 * "やまだ薬局" "処方薬"
  id: "tx-2026-0002"
  payer: "太郎"
  patient: "太郎"
  Expenses:Medical   1,500 JPY
  Assets:Bank:Taro  -1500 JPY

2026-02-25 * "コンビニ" "2月分給与"
  id: "tx-2026-0003"
  person: "次郎"
  Assets:Cash:Jiro   (50000 + 2000) JPY
  Income:Job:Konbini
'''

META_TYPES = '''2026-01-01 open Assets:Cash JPY
2026-01-01 open Expenses:Misc JPY
2026-01-10 * "型の確認"
  id: "tx-types"
  sv: "文字列"
  iv: 3
  dv: 0.25
  neg: -5
  expr: 2*3
  div: 10/3
  dt: 2026-01-09
  bv: TRUE
  acct: Assets:Cash
  cur: JPY
  amt: 100 JPY
  comma: 1,500
  empty:
  Expenses:Misc   1000.00 JPY
  Assets:Cash
'''


def b1():
    out = {}
    d = fresh("b1_types")
    main = wtext(path.join(d, "main.beancount"), META_TYPES)
    r = safe_load(main, d)
    out["読み込みのエラー"] = r["errors"]
    tx = [e for e in r["_entries"] if isinstance(e, bc_data.Transaction)][0]
    out["メタデータの Python の型"] = {k: [type(v).__name__, str(v)] for k, v in tx.meta.items() if k not in SKIP_META}
    out["自動で付くメタデータのキー（取引）"] = sorted(k for k in tx.meta if k in SKIP_META or k.startswith("__"))
    out["posting のメタデータのキー"] = [sorted((p.meta or {}).keys()) for p in tx.postings]
    out["posting の金額"] = [[p.account, None if p.units is None else str(p.units.number)] for p in tx.postings]
    for label, line in [("タグ（tg: #x）", "  tg: #x"), ("日本語のキー", '  患者: "x"'), ("NULL（nv: NULL）", "  nv: NULL"),
                        ("大文字始まりのキー", '  Payer: "x"'), ("1文字のキー", '  p: "x"'), ("FALSE（bf: FALSE）", "  bf: FALSE")]:
        dd = fresh("b1_variant")
        m2 = wtext(path.join(dd, "main.beancount"), META_TYPES.replace('  sv: "文字列"', line))
        r2 = safe_load(m2, dd)
        if r2["stage"] == "loaded":
            t2 = [e for e in r2["_entries"] if isinstance(e, bc_data.Transaction)]
            key = line.strip().split(":")[0]
            out[label] = {"errors": r2["errors"][:2], "取引が残ったか": bool(t2),
                          "値": [type(t2[0].meta.get(key)).__name__, repr(t2[0].meta.get(key))] if t2 else None}
        else:
            out[label] = public(r2)
    return out


def b2():
    d = fresh("b2_sample")
    wtext(path.join(d, "receipts", "2026-01-10.山田医院.pdf"), "%PDF-1.4 dummy receipt\n")
    main = wtext(path.join(d, "main.beancount"), SAMPLE)
    r = safe_load(main, d)
    problems: list = []
    norm = normalize(r["_entries"], d, problems)
    doc = {"schema": "impl-probe-tx/0", "beancount": beancount.__version__,
           "source_files": r["_scan"]["files"], "load_errors": r["errors"], "problems": problems, **norm}
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1)
    with open(path.join(OUTDIR, "normalized_sample.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    # 決定性：同じ台帳を別のディレクトリに写して、もう一度
    d2 = fresh("b2_copy")
    shutil.copytree(d, d2, dirs_exist_ok=True)
    r2 = safe_load(path.join(d2, "main.beancount"), d2)
    p2: list = []
    doc2 = {"schema": "impl-probe-tx/0", "beancount": beancount.__version__,
            "source_files": r2["_scan"]["files"], "load_errors": r2["errors"], "problems": p2, **normalize(r2["_entries"], d2, p2)}
    text2 = json.dumps(doc2, ensure_ascii=False, sort_keys=True, indent=1)
    return {"safe_load": public(r), "出力": "scripts/results/IMPL_tools_beancount_probe/normalized_sample.json",
            "出力の sha256": hashlib.sha256(text.encode()).hexdigest(),
            "別ディレクトリに写した台帳での出力の sha256": hashlib.sha256(text2.encode()).hexdigest(),
            "同じか": text == text2, "problems": problems}


def b3():
    d = fresh("b3_problems")
    wtext(path.join(d, "receipts", "a.pdf"), "dummy")
    src = SAMPLE + '''
2026-03-01 * "重複"
  id: "tx-2026-0001"
  payer: "太郎"
  Expenses:Medical   100 JPY
  Assets:Cash:Taro

2026-03-02 * "id なし"
  patiant: "次郎"
  Expenses:Medical   100 JPY
  Assets:Cash:Taro

2026-03-03 * "id が数"
  id: 12345
  Expenses:Medical   100 JPY
  Assets:Cash:Taro

2026-03-04 document Expenses:Medical "receipts/a.pdf"
  txid: "tx-9999-9999"
'''
    wtext(path.join(d, "receipts", "2026-01-10.山田医院.pdf"), "x")
    main = wtext(path.join(d, "main.beancount"), src)
    r = safe_load(main, d)
    problems: list = []
    normalize(r["_entries"], d, problems)
    return {"problems": problems, "load_errors": r["errors"]}


# ---------------------------------------------------------------- 本体
def main():
    global TMP
    TMP = path.realpath(tempfile.mkdtemp(prefix="impl_bc_"))
    os.makedirs(OUTDIR, exist_ok=True)
    RESULTS["env"] = {"python": sys.version, "beancount": beancount.__version__, "flags_isolated": sys.flags.isolated,
                      "utf8_mode": sys.flags.utf8_mode, "gpg_on_PATH": shutil.which("gpg") is not None,
                      "TMP は realpath": TMP == path.realpath(TMP)}
    try:
        record("A1_新しいディレクトリでの走査の安全性", a1)
        record("A2_parse_file は include を辿らない", a2)
        record("A3_include の glob が root の外を歩く", a3)
        record("A4_include の循環", a4)
        record("A5_エンコーディングの細工", a5)
        record("A6_巨大なファイル", a6)
        record("A7_パス", a7)
        record("A8_documents が root の外", a8)
        record("A9_-I なしでのモジュールの差し替え", a9)
        record("A10_走査と読み込みの間の変更", a10)
        record("B1_メタデータの型", b1)
        record("B2_アダプタの出力と決定性", b2)
        record("B3_アダプタの検査", b3)
    finally:
        loader.initialize(use_cache=False)
        shutil.rmtree(TMP, ignore_errors=True)
    res = scrub(RESULTS)
    with open(path.join(OUTDIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2, default=str)
    with open(path.join(OUTDIR, "summary.txt"), "w", encoding="utf-8") as f:
        for k, v in res.items():
            f.write(f"## {k}\n{json.dumps(v, ensure_ascii=False, indent=1, default=str)}\n\n")
    print("wrote", OUTDIR)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--child":
        print(json.dumps(child(sys.argv[2], sys.argv[3]), ensure_ascii=False))
    else:
        main()
