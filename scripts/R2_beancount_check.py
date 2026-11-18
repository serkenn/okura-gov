"""R2: beancount 3.2.3 / beanquery 0.2.0 の実測スクリプト。

再実行の手順（リポジトリのルートで。Windows / Git Bash の例）:

    uv venv .work/venvs/R2-beancount --python 3.11
    uv pip install --python .work/venvs/R2-beancount --only-binary :all: \
        beancount==3.2.3 beanquery==0.2.0
    # 2026-11-09 の実測で入った依存（uv pip freeze）:
    #   beancount==3.2.3 beanquery==0.2.0 click==8.5.1 python-dateutil==4.0.0
    #   regex==2026.11.9 tatsu-lts==5.16.0 tzdata==2026.6
    # 完全に同じ環境にしたい場合は上の7つを == で固定して入れる。
    .work/venvs/R2-beancount/Scripts/python.exe -I scripts/R2_beancount_check.py

- 作業用の台帳・プラグイン・pickle はすべてこのスクリプトが一時ディレクトリに生成する。
- 「任意コード実行」の確認で実行されるコードは、一時ディレクトリにマーカーファイルを1つ書くだけ。
- 出力: scripts/results/R2_beancount_check/results.json と summary.txt
  （一時ディレクトリの絶対パスは <TMP> に置き換えて書く）
"""

from __future__ import annotations

import glob
import json
import os
import pickle
import platform
import shutil
import sys
import tempfile
import textwrap
from os import path

# loader はインポート時に pickle キャッシュの使用を決める（loader.py:847）。
# ここでは既定の挙動（環境変数なし＝キャッシュ有効）のまま読み込み、
# 個々の試験で loader.initialize() を明示的に呼んで切り替える。
os.environ.pop("BEANCOUNT_DISABLE_LOAD_CACHE", None)

import beancount  # noqa: E402
import beanquery  # noqa: E402
from beancount import loader  # noqa: E402
from beancount.core import account as bc_account  # noqa: E402
from beancount.parser import parser as bc_parser  # noqa: E402

HERE = path.dirname(path.abspath(__file__))
OUTDIR = path.join(HERE, "results", "R2_beancount_check")
TMP = tempfile.mkdtemp(prefix="r2bc_")
RESULTS: dict = {}


def scrub(obj):
    """一時ディレクトリの絶対パスを <TMP> に置き換える。"""
    if isinstance(obj, str):
        for p in (TMP, TMP.replace("\\", "/")):
            obj = obj.replace(p, "<TMP>")
        return obj
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


def fwd(p: str) -> str:
    return p.replace("\\", "/")


def write(p: str, text: str) -> str:
    os.makedirs(path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(textwrap.dedent(text).lstrip("\n"))
    return p


def errs(errors) -> list[str]:
    return [e.message.splitlines()[0] for e in errors]


def newdir(name: str) -> str:
    d = path.join(TMP, name)
    os.makedirs(d)
    return d


# ---------------------------------------------------------------- 1. 勘定科目名
def test_account_names():
    cases = [
        "Expenses:Medical",
        "Expenses:医療費",
        "Expenses:Medical:医療費",
        "Expenses:Ｍ医療費",  # 先頭が全角 M（U+FF2D, Lu）
        "Expenses:M-医療費",
        "Expenses:1医療費",
        "Assets:現金:太郎",
        "Assets:Cash:太郎",
        "Assets:Cash:Taro",
        "Expenses:Ä医療費",
    ]
    out = []
    for acc in cases:
        src = f"""
        2026-01-01 open {acc} JPY
        2026-01-01 open Assets:Bank JPY
        2026-01-10 * "テスト"
          {acc}   1000 JPY
          Assets:Bank
        """
        entries, errors, options = loader.load_string(textwrap.dedent(src))
        rows = None
        if not errors:
            conn = beanquery.connect("beancount:", entries=entries, errors=errors, options=options)
            cur = conn.execute("SELECT account, sum(number) AS total WHERE account ~ '^Expenses|^Assets:Cash' GROUP BY account")
            rows = [[r[0], str(r[1])] for r in cur.fetchall()]
        out.append(
            {
                "account": acc,
                "load_errors": errs(errors),
                "beanquery_rows": rows,
                "account.is_valid (fullmatch)": bc_account.is_valid(acc),
                "first_char_after_root": hex(ord(acc.split(":")[1][0])),
            }
        )
    # ルート名を日本語にする option
    src = """
    option "name_assets" "資産"
    2026-01-01 open 資産:Cash JPY
    """
    _, errors, opts = loader.load_string(textwrap.dedent(src))
    out.append(
        {
            "account": 'option "name_assets" "資産" + 資産:Cash',
            "load_errors": errs(errors),
            "name_assets_after": opts["name_assets"],
        }
    )
    RESULTS["1_account_names"] = out


# ------------------------------------------- 2. 日本語の文字列・メタデータ・タグ
def test_japanese_text():
    out = {}
    src = """
    2026-01-01 open Expenses:Medical JPY
    2026-01-01 open Assets:Cash:Taro JPY
    2026-01-10 * "山田医院" "初診料（次郎）"
      id: "tx-2026-0001"
      patient: "次郎"
      payer: "太郎"
      Expenses:Medical   3000 JPY
        memo: "保険適用後の自己負担"
      Assets:Cash:Taro
    """
    entries, errors, _ = loader.load_string(textwrap.dedent(src))
    txn = [e for e in entries if type(e).__name__ == "Transaction"][0]
    out["japanese_payee_narration_meta"] = {
        "errors": errs(errors),
        "payee": txn.payee,
        "narration": txn.narration,
        "meta_patient": txn.meta.get("patient"),
        "posting_meta_memo": txn.postings[0].meta.get("memo"),
    }
    for label, line in [
        ("japanese_meta_key", '  患者: "次郎"'),
        ("japanese_tag", None),
        ("japanese_link", None),
    ]:
        if label == "japanese_meta_key":
            s = src.replace('  patient: "次郎"', line)
        elif label == "japanese_tag":
            s = src.replace('"初診料（次郎）"', '"初診料（次郎）" #医療費')
        else:
            s = src.replace('"初診料（次郎）"', '"初診料（次郎）" ^医療-1')
        _, errors, _ = loader.load_string(textwrap.dedent(s))
        out[label] = {"errors": errs(errors)}
    RESULTS["2_japanese_text"] = out


# ------------------------------------- 3. id メタデータと beanquery による集計
def test_id_and_query():
    src = """
    2026-01-01 open Expenses:Medical JPY
    2026-01-01 open Income:Job:Konbini JPY
    2026-01-01 open Assets:Cash:Taro JPY
    2026-01-01 open Assets:Cash:Jiro JPY
    2026-01-10 * "山田医院" "初診料" ^tx-2026-0001
      id: "tx-2026-0001"
      patient: "jiro"
      payer: "taro"
      Expenses:Medical   3000 JPY
      Assets:Cash:Taro
    2026-02-03 * "山田医院" "再診料"
      id: "tx-2026-0002"
      patient: "taro"
      payer: "taro"
      Expenses:Medical   1500 JPY
      Assets:Cash:Taro
    2026-02-25 * "コンビニ" "2月分給与"
      id: "tx-2026-0003"
      person: "jiro"
      Assets:Cash:Jiro   52000 JPY
      Income:Job:Konbini
    2025-12-25 * "コンビニ" "前年分"
      id: "tx-2025-0099"
      person: "jiro"
      Assets:Cash:Jiro   10000 JPY
      Income:Job:Konbini
    """
    # 2025-12-25 の取引は open より前なのでエラーになるはず（境界の確認）
    entries, errors, options = loader.load_string(textwrap.dedent(src))
    out = {"load_errors": errs(errors)}
    conn = beanquery.connect("beancount:", entries=entries, errors=errors, options=options)
    queries = {
        "find_by_id": "SELECT date, narration, account, number WHERE entry_meta('id') = 'tx-2026-0001'",
        "medical_by_patient_2026": (
            "SELECT entry_meta('patient') AS patient, entry_meta('payer') AS payer, "
            "sum(number) AS total WHERE account ~ '^Expenses:Medical' AND year = 2026 "
            "AND currency = 'JPY' GROUP BY patient, payer ORDER BY patient"
        ),
        "income_by_person_month": (
            "SELECT entry_meta('person') AS person, month, sum(number) AS total "
            "WHERE account ~ '^Income:' AND year = 2026 GROUP BY person, month ORDER BY month"
        ),
        "links": "SELECT date, links WHERE 'tx-2026-0001' IN links",
    }
    for name, q in queries.items():
        try:
            cur = conn.execute(q)
            cols = [d[0] for d in cur.description]
            rows = [
                {c: (str(v) if not isinstance(v, (int, float, str, type(None))) else v) for c, v in zip(cols, r)}
                for r in cur.fetchall()
            ]
            out[name] = {"query": q, "rows": rows}
        except Exception as exc:  # noqa: BLE001
            out[name] = {"query": q, "error": f"{type(exc).__name__}: {exc}"}
    # entry の id 重複を検出できるか（標準では検出しない → 自前で数える）
    ids = [e.meta.get("id") for e in entries if "id" in e.meta]
    out["duplicate_id_check_by_script"] = sorted({i for i in ids if ids.count(i) > 1})
    s2 = textwrap.dedent(src) + (
        '\n2026-03-01 * "dup"\n  id: "tx-2026-0001"\n  Expenses:Medical  1 JPY\n  Assets:Cash:Taro\n'
    )
    entries2, errors2, _ = loader.load_string(s2)
    out["duplicate_id_builtin_errors"] = errs(errors2)
    ids2 = [e.meta.get("id") for e in entries2 if "id" in e.meta]
    out["duplicate_id_check_by_script_after_adding_dup"] = sorted({i for i in ids2 if ids2.count(i) > 1})
    RESULTS["3_id_and_query"] = out


# ----------------------------------------------------------- 4. plugin 行
PLUGIN_SRC = '''
import os
_marker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin_marker.txt")
with open(_marker, "w", encoding="utf-8") as f:
    f.write("r2_harmless_plugin was imported and executed\\n")
__plugins__ = ("noop",)
def noop(entries, options_map):
    return entries, []
'''


def test_plugin():
    out = {}
    base = """
    2026-01-01 open Assets:Cash JPY
    """
    # 4a: 台帳と同じディレクトリに .py を置き、insert_pythonpath + plugin 行
    d = newdir("plugin_a")
    write(path.join(d, "r2_harmless_plugin.py"), PLUGIN_SRC)
    main = write(
        path.join(d, "main.beancount"),
        'option "insert_pythonpath" "TRUE"\nplugin "r2_harmless_plugin"\n' + textwrap.dedent(base),
    )
    loader.initialize(use_cache=False)
    _, errors, _ = loader.load_file(main)
    out["4a_insert_pythonpath_plus_plugin"] = {
        "marker_created": path.exists(path.join(d, "plugin_marker.txt")),
        "errors": errs(errors),
    }
    sys.modules.pop("r2_harmless_plugin", None)

    # 4b: insert_pythonpath なし（-I なので cwd も sys.path にない）
    d = newdir("plugin_b")
    write(path.join(d, "r2_harmless_plugin.py"), PLUGIN_SRC)
    main = write(path.join(d, "main.beancount"), 'plugin "r2_harmless_plugin"\n' + textwrap.dedent(base))
    _, errors, _ = loader.load_file(main)
    out["4b_plugin_without_insert_pythonpath"] = {
        "marker_created": path.exists(path.join(d, "plugin_marker.txt")),
        "errors": errs(errors),
    }
    sys.modules.pop("r2_harmless_plugin", None)

    # 4c: 同梱プラグインの設定文字列が eval される（台帳のテキストだけで任意コード実行）
    for mod in ("beancount.plugins.check_commodity", "beancount.plugins.commodity_attr",
                "beancount.plugins.check_average_cost"):
        d = newdir("plugin_c_" + mod.rsplit(".", 1)[1])
        marker = fwd(path.join(d, "eval_marker.txt"))
        tail = "and 0.01" if mod.endswith("check_average_cost") else "and {}"
        expr = f"__import__('pathlib').Path('{marker}').write_text('eval executed') {tail}"
        main = write(path.join(d, "main.beancount"), f'plugin "{mod}" "{expr}"\n' + textwrap.dedent(base))
        _, errors, _ = loader.load_file(main)
        out["4c_eval_in_" + mod] = {
            "plugin_line": f'plugin "{mod}" "{expr}"',
            "marker_created": path.exists(marker),
            "errors": errs(errors),
        }

    # 4d: include 先のファイルにある plugin 行は実行されるか
    d = newdir("plugin_d")
    marker = fwd(path.join(d, "eval_marker.txt"))
    expr = f"__import__('pathlib').Path('{marker}').write_text('eval executed') and {{}}"
    write(path.join(d, "sub.beancount"), f'plugin "beancount.plugins.check_commodity" "{expr}"\n')
    main = write(path.join(d, "main.beancount"), 'include "sub.beancount"\n' + textwrap.dedent(base))
    _, errors, opts = loader.load_file(main)
    out["4d_plugin_line_in_included_file"] = {
        "marker_created": path.exists(marker),
        "errors": errs(errors),
        "options_plugin": opts["plugin"],
    }

    # 4e: include 先の insert_pythonpath は sys.path に入るか（aggregate_options_map）
    d = newdir("plugin_e")
    sub = path.join(d, "sub")
    write(path.join(sub, "r2_harmless_plugin.py"), PLUGIN_SRC)
    write(path.join(sub, "sub.beancount"), 'option "insert_pythonpath" "TRUE"\n')
    main = write(path.join(d, "main.beancount"),
                 'include "sub/sub.beancount"\nplugin "r2_harmless_plugin"\n' + textwrap.dedent(base))
    _, errors, opts = loader.load_file(main)
    out["4e_insert_pythonpath_in_included_file"] = {
        "marker_created": path.exists(path.join(sub, "plugin_marker.txt")),
        "pythonpath": opts.get("pythonpath"),
        "errors": errs(errors),
    }
    sys.modules.pop("r2_harmless_plugin", None)

    # 4f: 対策 = 読み込む前に parser だけで全ファイルを走査し、危険な指示があれば拒否する
    out["4f_prescan"] = {}
    for name in ["plugin_a", "plugin_b", "plugin_c_check_commodity", "plugin_d", "plugin_e"]:
        main = path.join(TMP, name, "main.beancount")
        out["4f_prescan"][name] = prescan(main, root=path.join(TMP, name))
    clean = write(path.join(newdir("plugin_clean"), "main.beancount"), textwrap.dedent(base))
    out["4f_prescan"]["clean"] = prescan(clean, root=path.dirname(clean))
    RESULTS["4_plugin"] = out


def prescan(main: str, root: str) -> dict:
    """plugin 行・insert_pythonpath・root の外への include を検出する（実行はしない）。

    beancount.parser.parser.parse_file は文法の処理だけで、プラグインを読み込まない
    （loader.py:_load の run_transformations で初めて import される）。
    include の展開は loader._parse_recursive（loader.py:494-518）と同じ規則で行う。
    """
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
            problems.append(f"plugin line: {name!r} config={conf!r} in {f}")
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
    return {"accepted": not problems, "problems": problems, "files": sorted(seen)}


# ----------------------------------------------------------- 5. include
def test_include():
    out = {}
    d = newdir("include")
    outside = newdir("include_outside")
    write(path.join(outside, "other.beancount"), """
    2026-01-01 open Assets:Outside JPY
    """)
    write(path.join(outside, "notes.txt"), """
    これは台帳ではないテキスト SECRET-LINE-1
    password = hunter2
    """)
    main = write(path.join(d, "main.beancount"), f"""
    include "../include_outside/other.beancount"
    include "{fwd(path.join(outside, 'other.beancount'))}"
    include "../include_outside/notes.txt"
    include "../include_outside/*.beancount"
    """)
    loader.initialize(use_cache=False)
    entries, errors, opts = loader.load_file(main)
    out["relative_parent_and_absolute"] = {
        "opened_accounts": sorted({e.account for e in entries if type(e).__name__ == "Open"}),
        "errors": [e.message[:200] for e in errors],
        "files_read": opts["include"],
    }
    out["prescan"] = prescan(main, root=d)
    RESULTS["5_include"] = out


# ----------------------------------------------------------- 6. pickle キャッシュ
def make_pickle(marker: str) -> bytes:
    # pathlib.Path(marker).write_text("...") を unpickle 時に呼ぶ pickle を作る。
    import pathlib

    class Payload:
        def __reduce__(self):
            return (pathlib.Path.write_text, (pathlib.Path(marker), "pickle executed"))

    return pickle.dumps(Payload())


def test_pickle_cache():
    out = {}
    for label, use_cache in [("cache_enabled_default", True), ("cache_disabled", False)]:
        d = newdir("pickle_" + label)
        main = write(path.join(d, "main.beancount"), "2026-01-01 open Assets:Cash JPY\n")
        cache = path.join(d, ".main.beancount.picklecache")
        marker = path.join(d, "pickle_marker.txt")
        with open(cache, "wb") as f:
            f.write(make_pickle(marker))
        loader.initialize(use_cache=use_cache)
        try:
            _, errors, _ = loader.load_file(main)
            e = errs(errors)
        except Exception as exc:  # noqa: BLE001
            e = [f"{type(exc).__name__}: {exc}"]
        out[label] = {
            "marker_created": path.exists(marker),
            "cache_file_still_exists": path.exists(cache),
            "errors": e,
        }
    # 既定（環境変数なし）でキャッシュが有効かどうか: loader.py:847 の initialize の結果
    RESULTS["6_pickle_cache"] = out


# ----------------------------------------------------------- 7. document
def test_document():
    out = {}
    d = newdir("document")
    write(path.join(d, "receipts", "2026-01-10.山田医院.pdf"), "dummy")
    write(path.join(d, "docs", "Expenses", "Medical", "2026-02-03.再診.pdf"), "dummy")
    write(path.join(d, "docs", "Expenses", "医療費", "2026-02-04.x.pdf"), "dummy")
    main = write(path.join(d, "main.beancount"), """
    option "documents" "docs"
    2026-01-01 open Expenses:Medical JPY
    2026-01-10 document Expenses:Medical "receipts/2026-01-10.山田医院.pdf"
      txid: "tx-2026-0001"
    2026-01-11 document Expenses:Medical "receipts/missing.pdf"
    """)
    loader.initialize(use_cache=False)
    entries, errors, _ = loader.load_file(main)
    docs = [e for e in entries if type(e).__name__ == "Document"]
    out["documents"] = [
        {"date": str(e.date), "account": e.account, "filename": e.filename, "meta_txid": e.meta.get("txid")}
        for e in docs
    ]
    out["errors"] = errs(errors)
    RESULTS["7_document"] = out


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    RESULTS["env"] = {
        "python": sys.version,
        "platform": platform.platform(),
        "beancount": beancount.__version__,
        "beanquery": getattr(beanquery, "__version__", "?"),
        "flags_isolated": sys.flags.isolated,
        "BEANCOUNT_DISABLE_LOAD_CACHE_at_start": os.environ.get("BEANCOUNT_DISABLE_LOAD_CACHE"),
    }
    try:
        test_account_names()
        test_japanese_text()
        test_id_and_query()
        test_plugin()
        test_include()
        test_pickle_cache()
        test_document()
    finally:
        loader.initialize(use_cache=False)
        shutil.rmtree(TMP, ignore_errors=True)
    res = scrub(RESULTS)
    with open(path.join(OUTDIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    with open(path.join(OUTDIR, "summary.txt"), "w", encoding="utf-8") as f:
        for k, v in res.items():
            f.write(f"## {k}\n{json.dumps(v, ensure_ascii=False, indent=1)}\n\n")
    print("wrote", OUTDIR)


if __name__ == "__main__":
    main()
