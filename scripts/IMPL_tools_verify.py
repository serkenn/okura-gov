"""IMPL（実装前の追加調査）tools の独立検証（反証役）。標準ライブラリだけで書いた。

確かめること（結果は scripts/results/IMPL_tools_verify/ に書く。実測 docs/measurements/20261109_impl-prep_tools-verification.md から参照する）:
  V1 公開資料の文書（docs/public-sources/20261109_impl-prep_tools-source-notes.md）が挙げたソースの行番号に、
     主張どおりのコードがあるか（実測用 venv に入っている OpenFisca-Core 46.0.1・beancount 3.2.3 のファイルを読む。実行はしない）
  V2 読んだ版の一致：clone の HEAD・タグの参照（.git の中のファイルをデータとして読む）、clone・wheel・venv のファイルの一致、
     wheel の SHA-256 と PyPI の JSON の digests の一致
  V3 GitHub のタグが指すコミット（git ls-remote。手元の clone の中では実行しない）
  V4 floor(x × r) の float32・float64 の食い違いの数（P08）を、numpy を使わずに再計算する
     （float32 の丸めは array('f') で再現。float32 どうしの積は倍精度で正確に表せるので、積を array('f') で丸めれば IEEE の float32 の積と同じ）
  V5 期間・月・年齢・見本の合計（P01・P02・P09・P10）の暦の上の再計算
  V6 実測の文書に書かれた時間の比（%・倍）を results.json から再計算する
  V7 実測の文書の数値と results.json の突き合わせ（主なもの）
  V8 `-I` の有無と起動の形（-c・スクリプト・-m）で sys.path[0] がどうなるか（beancount 実測 A9 の一般化の確認）
     この PC の pyenv の CPython 3.11.9 で行う。一時ディレクトリに置く glob.py の中身は、マーカーを書くだけ
  V9 仮説の文書 H1 の4 が書く健保の年齢の基準日（扶養認定日が属する年の12月31日）を一次情報で確かめる
     （厚生労働省 事務連絡 R7QA19 と日本年金機構 FAQ を取得する。取得物は .work/downloads/<日時>_<名前>/ に置き、データとしてだけ読む）

## 実行方法（リポジトリのルートで）
    C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_tools_verify.py
"""

from __future__ import annotations

import datetime
import hashlib
import html
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
import zipfile
from array import array

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_tools_verify"
DL = ROOT / ".work" / "downloads"
UA = "okura-gov-research/0.1"
WAIT = 1.5
R: dict = {}

OF_SP = ROOT / ".work" / "venvs" / "R2-openfisca" / "Lib" / "site-packages"
BC_SP = ROOT / ".work" / "venvs" / "R2-beancount" / "Lib" / "site-packages"
OF_CLONE = DL / "20261109-132258_openfisca-core" / "openfisca-core"
BC_CLONE = DL / "20261109-132305_beancount" / "beancount"
OF_WHEEL = DL / "20261109-150145_openfisca-core" / "openfisca_core-46.0.1-py3-none-any.whl"
OF_PYPI_JSON = DL / "20261109-150145_openfisca-core" / "pypi_openfisca-core_46.0.1.json"
BC_WHEEL = DL / "20261109-150346_beancount" / "beancount-3.2.3-cp311-cp311-win_amd64.whl"
OF_RES = ROOT / "scripts" / "results" / "IMPL_tools_openfisca_probe" / "results.json"
BC_RES = ROOT / "scripts" / "results" / "IMPL_tools_beancount_probe" / "results.json"


def record(key, fn):
    t0 = time.perf_counter()
    try:
        R[key] = {"ok": True, "result": fn(), "seconds": round(time.perf_counter() - t0, 2)}
    except Exception as e:  # noqa: BLE001  検証なので例外も結果として残す
        import traceback
        R[key] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:1500],
                  "traceback_tail": traceback.format_exc().splitlines()[-6:]}
    print(f"[{key}] {'ok' if R[key]['ok'] else 'NG'}", flush=True)


# ---------------------------------------------------------------- V1 ソースの行番号
# (主張の場所, venv の中のファイル, 開始行, 終了行, その範囲に含まれるべき文字列)
OF_CLAIMS = [
    ("SRC1.1 parameters 引数（トレースの有無）", "openfisca_core/simulations/simulation.py", 331, 351,
     ["def trace_parameters_at_instant", "parameters_at = self.trace_parameters_at_instant",
      "parameters_at = self.tax_benefit_system.get_parameters_at_instant"]),
    ("SRC1.1 get_parameters_at_instant", "openfisca_core/taxbenefitsystems/tax_benefit_system.py", 443, 466, ["def get_parameters_at_instant"]),
    ("SRC1.1 Period なら start", "openfisca_core/taxbenefitsystems/tax_benefit_system.py", 462, 463,
     ["elif isinstance(instant, Period):", "key = instant.start"]),
    ("SRC1.1 values_list を先頭から", "openfisca_core/parameters/parameter.py", 213, 217,
     ["def _get_at_instant", "for value_at_instant in self.values_list:", "if value_at_instant.instant_str <= instant:"]),
    ("SRC1.1 values_list は新しい順（行番号は文書に無い。補足）", "openfisca_core/parameters/parameter.py", 77, 80, ["reverse=True"]),
    ("SRC1.1 null は子に登録されない", "openfisca_core/parameters/parameter_node_at_instant.py", 23, 34,
     ["if child_at_instant is not None:", "raise ParameterNotFoundError"]),
    ("SRC1.1 式の選択", "openfisca_core/variables/variable.py", 384, 431, ["def get_formula"]),
    ("SRC1.1 式の選択は period.start", "openfisca_core/variables/variable.py", 412, 413,
     ["if isinstance(period, Period):", "instant = period.start"]),
    ("SRC1.2 Period.__str__", "openfisca_core/periods/period_.py", 126, 157, ["def __str__"]),
    ("SRC1.2 rolling year", "openfisca_core/periods/period_.py", 139, 144, ['return t.PeriodStr(f"{DateUnit.YEAR}:{f_year}-{month:02d}")']),
    ("SRC1.2 1月始まりは年だけ", "openfisca_core/periods/period_.py", 140, 142, ["if month == 1:", "return t.PeriodStr(str(f_year))"]),
    ("SRC1.2 月", "openfisca_core/periods/period_.py", 147, 148, ['return t.PeriodStr(f"{f_year}-{month:02d}")']),
    ("SRC1.2 日", "openfisca_core/periods/period_.py", 154, 157, ["if unit == DateUnit.DAY:", "{day:02d}"]),
    ("SRC1.2 input_buffer のキー", "openfisca_core/simulations/simulation_builder.py", 651, 651,
     ["self.input_buffer[variable.name][str(periods.period(period_str))] = array"]),
    ("SRC1.2 finalize_variables_init", "openfisca_core/simulations/simulation_builder.py", 669, 684,
     ["periods.period(period_str)", "holder.set_input(period_value, array)"]),
    ("SRC1.2 flat trace のキー", "openfisca_core/tracers/flat_trace.py", 58, 63, ['f"{name}<{period}>"']),
    ("SRC1.2 キャッシュは Period をキー（get）", "openfisca_core/data_storage/in_memory_storage.py", 60, 62, ["self._arrays.get(period)"]),
    ("SRC1.2 キャッシュは Period をキー（put）", "openfisca_core/data_storage/in_memory_storage.py", 92, 94, ["self._arrays[period] = value"]),
    ("SRC1.3 calculate_add", "openfisca_core/simulations/simulation.py", 182, 182, ["def calculate_add"]),
    ("SRC1.3 get_subperiods の合計", "openfisca_core/simulations/simulation.py", 224, 224, ["period.get_subperiods(variable.definition_period)"]),
    ("SRC1.3 get_subperiods(MONTH)", "openfisca_core/periods/period_.py", 486, 490, ["self.first_month.offset(i, DateUnit.MONTH)"]),
    ("SRC1.3 first_month", "openfisca_core/periods/period_.py", 892, 896, ["def first_month", 'self.start.offset("first-of", DateUnit.MONTH)']),
    ("SRC1.4 trace の切り替え", "openfisca_core/simulations/simulation.py", 67, 76, ["def trace", "tracers.FullTracer()", "tracers.SimpleTracer()"]),
    ("SRC1.4 Web API の /trace", "openfisca_web_api/handlers.py", 67, 90, ["def trace(", "simulation.trace = True", "get_serialized_flat_trace()"]),
    ("SRC1.4 TraceNode", "openfisca_core/tracers/trace_node.py", 8, 34,
     ["class TraceNode", "name: str", "period:", "parent:", "children:", "parameters:", "value:", "start:", "end:"]),
    ("SRC1.4 record_parameter_access", "openfisca_core/tracers/full_tracer.py", 60, 69,
     ["def record_parameter_access", "self._current_node.parameters.append"]),
    ("SRC1.4 get_traced_child", "openfisca_core/tracers/tracing_parameter_node_at_instant.py", 50, 81, ["def get_traced_child"]),
    ("SRC1.4 記録は ndarray か ALLOWED_PARAM_TYPES のとき", "openfisca_core/tracers/tracing_parameter_node_at_instant.py", 78, 79,
     ["ALLOWED_PARAM_TYPES", "self.tracer.record_parameter_access(name, period, child)"]),
    ("SRC1.4 ベクトルで引くと親の名前", "openfisca_core/tracers/tracing_parameter_node_at_instant.py", 70, 76,
     ["name = self.parameter_node_at_instant._name"]),
    ("SRC1.4 ALLOWED_PARAM_TYPES", "openfisca_core/parameters/config.py", 24, 24,
     ["ALLOWED_PARAM_TYPES = (float, int, bool, type(None), list, str)"]),
    ("SRC1.4 trees", "openfisca_core/tracers/full_tracer.py", 32, 34, ["def trees"]),
    ("SRC1.4 browse_trace", "openfisca_core/tracers/full_tracer.py", 106, 114, ["def browse_trace"]),
    ("SRC1.4 get_flat_trace / serialized", "openfisca_core/tracers/full_tracer.py", 100, 104,
     ["def get_flat_trace", "def get_serialized_flat_trace"]),
    ("SRC1.4 computation_log", "openfisca_core/tracers/full_tracer.py", 36, 39, ["def computation_log"]),
    ("SRC1.4 ComputationLog.lines", "openfisca_core/tracers/computation_log.py", 17, 45, ["def lines("]),
    ("SRC1.4 FlatTrace は上書きしない", "openfisca_core/tracers/flat_trace.py", 15, 31, ["if key not in trace"]),
    ("SRC1.4 FlatTrace の1件", "openfisca_core/tracers/flat_trace.py", 45, 56,
     ['"dependencies"', '"parameters"', '"value"', '"calculation_time"', '"formula_time"']),
    ("SRC1.4 serialize", "openfisca_core/tracers/flat_trace.py", 66, 84, ["def serialize", "decode_to_str", "return value.tolist()"]),
    ("SRC1.5 Parameter の属性", "openfisca_core/parameters/parameter.py", 47, 72,
     ["self.description", "self.metadata", "self.documentation"]),
    ("SRC1.5 値ごとのメタデータの継承", "openfisca_core/parameters/parameter_at_instant.py", 34, 37,
     ["self.metadata.update(metadata)", 'self.metadata.update(data.get("metadata", {}))']),
    ("SRC1.5 値ごとのキー", "openfisca_core/parameters/parameter_at_instant.py", 12, 12,
     ['_allowed_keys = {"value", "metadata", "unit", "reference"}']),
    ("SRC1.5 YAML の日付は文字列", "openfisca_core/parameters/config.py", 29, 33,
     ["def date_constructor", "return node.value", "tag:yaml.org,2002:timestamp"]),
    ("SRC1.6 dtype の表", "openfisca_core/variables/config.py", 8, 50,
     ['"dtype": numpy.bool_', '"dtype": numpy.int32', '"dtype": numpy.float32', '"dtype": object',
      '"dtype": indexed_enums.ENUM_ARRAY_DTYPE', '"dtype": "datetime64[D]"']),
    ("SRC1.6 Variable.__init__ の dtype", "openfisca_core/variables/variable.py", 116, 116,
     ['self.dtype = config.VALUE_TYPES[self.value_type]["dtype"]']),
    ("SRC1.6 補足（独立検証）：str だけは max_length で dtype が変わる", "openfisca_core/variables/variable.py", 125, 128,
     ['self.max_length = self.set(attr, "max_length", allowed_type=int)', 'self.dtype = f"|S{self.max_length}"']),
    ("SRC1.6 補足（独立検証）：知らないクラス属性はエラー（dtype をクラス属性で書けない）", "openfisca_core/variables/variable.py", 177, 186,
     ["formulas_attr, unexpected_attrs = helpers._partition(", "if unexpected_attrs:", "Unexpected attributes in definition of variable"]),
    ("SRC1.6 check_set_value", "openfisca_core/variables/variable.py", 437, 466, ["def check_set_value"]),
    ("SRC1.6 列挙の名前", "openfisca_core/variables/variable.py", 438, 450, ["self.possible_values[value].index", "raise ValueError"]),
    ("SRC1.6 数値の文字列は eval_expression", "openfisca_core/variables/variable.py", 451, 452, ["commons.eval_expression(value)"]),
    ("SRC1.6 numpy.array([value], dtype)", "openfisca_core/variables/variable.py", 455, 455, ["numpy.array([value], dtype=self.dtype)[0]"]),
    ("SRC1.6 OverflowError も ValueError", "openfisca_core/variables/variable.py", 456, 464, ["except OverflowError:", "too large"]),
    ("SRC1.6 Holder.set_input の文字列", "openfisca_core/holders/holder.py", 239, 240, ["isinstance(array, str)", "commons.eval_expression(array)"]),
    ("SRC1.6 Holder._to_array は astype", "openfisca_core/holders/holder.py", 245, 266, ["def _to_array", "value.astype(self.variable.dtype)"]),
    ("SRC1.6 _cast_formula_result", "openfisca_core/simulations/simulation.py", 393, 407, ["def _cast_formula_result", "value.astype(variable.dtype)"]),
    ("推測 I3 の前提：SimpleTracer.record_parameter_access は何もしない（行番号は文書に無い）",
     "openfisca_core/tracers/simple_tracer.py", 43, 46, ["def record_parameter_access", "Ignore parameter access"]),
    ("推測 I3 の前提：Population はシミュレーションを持つ（行番号は文書に無い）", "openfisca_core/populations/_core_population.py", 135, 148,
     ["if self.simulation is None:", "return self.simulation.calculate("]),
    ("推測 I3 の前提：シミュレーションが population.simulation を設定（行番号は文書に無い）", "openfisca_core/simulations/simulation.py", 78, 80,
     ["def link_to_entities_instances", "entity_instance.simulation = self"]),
    ("実測 §9：openfisca_core.tools が numpy.testing を import（行番号は文書に無い）",
     "openfisca_core/tools/__init__.py", 3, 3, ["from numpy.testing import assert_array_equal"]),
]
BC_CLAIMS = [
    ("SRC2.1 parse_file", "beancount/parser/parser.py", 188, 227, ["def parse_file("]),
    ("SRC2.1 UTF-8 以外は ValueError", "beancount/parser/parser.py", 212, 213, ['"utf-8"', "raise ValueError"]),
    ("SRC2.1 '-' は標準入力", "beancount/parser/parser.py", 215, 216, ['if file == "-":', "sys.stdin.buffer"]),
    ("SRC2.1 ファイル名なら open(rb)", "beancount/parser/parser.py", 220, 221, ['open(file, "rb")']),
    ("SRC2.1 IOBase はそのまま", "beancount/parser/parser.py", 222, 223, ["file_io = file"]),
    ("SRC2.1 include は options に足すだけ", "beancount/parser/grammar.py", 439, 447,
     ["def include(", 'self.options["include"].append(include_filename)']),
    ("SRC2.2 _parse_recursive", "beancount/loader.py", 376, 376, ["def _parse_recursive("]),
    ("SRC2.2 幅優先 pop(0)", "beancount/loader.py", 414, 414, ["source_stack.pop(0)"]),
    ("SRC2.2 暗号化ファイルの判定", "beancount/loader.py", 421, 421, ["encryption.is_encrypted_file(source)"]),
    ("SRC2.2 is_encrypted_file", "beancount/utils/encryption.py", 40, 58,
     ['if ext == ".gpg":', 'if ext == ".asc":', "read(1024)", "--BEGIN PGP MESSAGE--"]),
    ("SRC2.2 gpg の起動", "beancount/utils/encryption.py", 61, 80, ['"gpg", "--batch", "--decrypt"', "shell=False"]),
    ("SRC2.2 Duplicate filename parsed", "beancount/loader.py", 435, 442, ["Duplicate filename parsed"]),
    ("SRC2.2 does not exist（446 行は判定、文言は 450 行）", "beancount/loader.py", 446, 450, ["if not path.exists(filename):", "does not exist"]),
    ("SRC2.2 include の glob", "beancount/loader.py", 500, 500, ["glob.glob(search_path, recursive=True)"]),
    ("SRC2.2 読んだファイルの一覧", "beancount/loader.py", 525, 525, ['options_map["include"] = sorted(filenames_seen)']),
    ("実測の環境：BEANCOUNT_DISABLE_LOAD_CACHE（スクリプトの注 loader.py:847）", "beancount/loader.py", 847, 847, ["BEANCOUNT_DISABLE_LOAD_CACHE"]),
    ("実測 A1：use_cache=False はキャッシュを消す関数（行番号は文書に無い）", "beancount/loader.py", 843, 843, ["delete_cache_function"]),
    ("SRC2.3 document の相対パス", "beancount/parser/grammar.py", 799, 821, ["def document("]),
    ("SRC2.3 abspath", "beancount/parser/grammar.py", 816, 819, ["if not path.isabs(document_filename):", "path.abspath("]),
    ("SRC2.3 ops.documents の __plugins__", "beancount/ops/documents.py", 17, 17,
     ['__plugins__ = ("process_documents", "verify_document_files_exist")']),
    ("SRC2.3 既定で動く（PLUGINS_PRE。行番号は文書に無い）", "beancount/loader.py", 54, 55, ['("beancount.ops.documents", None)']),
    ("SRC2.3 option documents の走査", "beancount/ops/documents.py", 35, 67, ["def process_documents", 'options_map["documents"]']),
    ("SRC2.3 document の存在確認", "beancount/ops/documents.py", 70, 89, ["def verify_document_files_exist", "File does not exist"]),
    ("SRC2.3 documents の相対は台帳ファイル基準（行番号は文書に無い）", "beancount/ops/documents.py", 115, 117,
     ["if not path.isabs(directory):", "path.dirname(input_filename)"]),
    ("SRC2.4 自動のメタデータ", "beancount/core/interpolate.py", 236, 242,
     ['AUTOMATIC_META = "__automatic__"', 'AUTOMATIC_RESIDUAL = "__residual__"', 'AUTOMATIC_TOLERANCES = "__tolerances__"']),
]
REPO_CLAIMS = [
    ("SRC2.2 R2 の prescan（glob の後に root を確かめる）", "scripts/R2_beancount_check.py", 344, 377,
     ["def prescan(", "if not path.realpath(f).startswith(root + os.sep):", "matched = glob.glob(pat, recursive=True)", "stack.extend(matched)"]),
]


def check_lines(base: pathlib.Path, claims):
    out = []
    for label, rel, a, b, needles in claims:
        p = base / rel
        lines = p.read_text(encoding="utf-8").splitlines()
        seg = "\n".join(lines[a - 1:b])
        missing = [n for n in needles if n not in seg]
        row = {"主張": label, "ファイル": rel, "行": f"{a}-{b}", "一致": not missing}
        if missing:
            row["範囲に無い文字列と実際の行"] = {n: [i + 1 for i, s in enumerate(lines) if n in s][:5] for n in missing}
        out.append(row)
    return {"件数": len(out), "不一致": [r for r in out if not r["一致"]], "全件": out}


def v1():
    return {"openfisca": check_lines(OF_SP, OF_CLAIMS), "beancount": check_lines(BC_SP, BC_CLAIMS),
            "repo": check_lines(ROOT, REPO_CLAIMS)}


# ---------------------------------------------------------------- V2 版の一致
def read_ref(gitdir: pathlib.Path, ref: str):
    loose = gitdir / ref
    if loose.is_file():
        return {"sha": loose.read_text(encoding="ascii").strip(), "from": "loose"}
    packed = gitdir / "packed-refs"
    if packed.is_file():
        lines = packed.read_text(encoding="ascii").splitlines()
        for i, line in enumerate(lines):
            if line.endswith(" " + ref):
                peeled = lines[i + 1][1:] if i + 1 < len(lines) and lines[i + 1].startswith("^") else None
                return {"sha": line.split()[0], "peeled": peeled, "from": "packed-refs"}
    return None


def norm_bytes(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def tree_py(base: pathlib.Path, pkg: str):
    root = base / pkg
    return {str(p.relative_to(base)).replace(os.sep, "/"): p for p in root.rglob("*.py") if "__pycache__" not in p.parts}


def compare_trees(a: dict, b: dict, normalize=True):
    common = sorted(set(a) & set(b))
    diff = [k for k in common
            if (norm_bytes(a[k].read_bytes()) if normalize else a[k].read_bytes())
            != (norm_bytes(b[k].read_bytes()) if normalize else b[k].read_bytes())]
    return {"共通": len(common), "差分あり": diff, "片方だけ（先）": sorted(set(a) - set(b))[:20],
            "片方だけ（後）": sorted(set(b) - set(a))[:20]}


def compare_wheel(wheel: pathlib.Path, base: pathlib.Path, prefixes):
    out = {"wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}
    same, diff, missing = 0, [], []
    with zipfile.ZipFile(wheel) as z:  # データとして読むだけ（展開しない）
        for info in z.infolist():
            n = info.filename
            if not n.startswith(prefixes) or n.endswith("/"):
                continue
            p = base / n
            if not p.is_file():
                missing.append(n)
                continue
            if z.read(n) == p.read_bytes():
                same += 1
            else:
                diff.append(n)
    out.update({"venv と同じバイト列のファイル数": same, "違うファイル": diff[:20], "venv に無いファイル": missing[:20]})
    return out


def v2():
    out = {}
    g = OF_CLONE / ".git"
    head = (g / "HEAD").read_text(encoding="ascii").strip()
    out["openfisca clone HEAD"] = {"HEAD": head, "refs/heads/main": read_ref(g, "refs/heads/main"),
                                   "refs/tags/46.0.1": read_ref(g, "refs/tags/46.0.1")}
    of_inst = tree_py(OF_SP, "openfisca_core")
    of_clone = tree_py(OF_CLONE, "openfisca_core")
    out["openfisca venv と clone（main。CRLF を LF にして比較）"] = compare_trees(of_inst, of_clone)
    six = ["openfisca_core/simulations/simulation_builder.py", "openfisca_core/periods/period_.py",
           "openfisca_core/tracers/flat_trace.py", "openfisca_core/tracers/tracing_parameter_node_at_instant.py",
           "openfisca_core/variables/config.py", "openfisca_core/taxbenefitsystems/tax_benefit_system.py"]
    out["openfisca 文書の表の6ファイル（venv と clone）"] = {
        f: norm_bytes((OF_SP / f).read_bytes()) == norm_bytes((OF_CLONE / f).read_bytes()) for f in six}
    out["openfisca wheel と venv"] = compare_wheel(OF_WHEEL, OF_SP, ("openfisca_core/", "openfisca_web_api/"))
    pj = json.loads(OF_PYPI_JSON.read_text(encoding="utf-8"))
    digests = {u["filename"]: u["digests"]["sha256"] for u in pj.get("urls", [])}
    out["openfisca wheel の sha256 と PyPI の JSON（取得済み）"] = {
        "PyPI": digests.get(OF_WHEEL.name), "一致": digests.get(OF_WHEEL.name) == out["openfisca wheel と venv"]["sha256"],
        "PyPI の版": pj.get("info", {}).get("version")}
    g = BC_CLONE / ".git"
    out["beancount clone HEAD"] = {"HEAD": (g / "HEAD").read_text(encoding="ascii").strip(),
                                   "refs/tags/3.2.3": read_ref(g, "refs/tags/3.2.3")}
    bc_inst = tree_py(BC_SP, "beancount")
    bc_clone = tree_py(BC_CLONE, "beancount")
    out["beancount venv と clone（HEAD。CRLF を LF にして比較）"] = compare_trees(bc_inst, bc_clone)
    out["beancount wheel と venv"] = compare_wheel(BC_WHEEL, BC_SP, ("beancount/",))
    dist = {}
    for sp in (OF_SP, BC_SP):
        for d in sp.glob("*.dist-info"):
            dist[d.name] = sp.parent.parent.name
    out["venv の dist-info"] = sorted(dist)
    return out


# ---------------------------------------------------------------- 取得の共通
def new_dl_dir(name: str) -> pathlib.Path:
    d = DL / f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}_{name}"
    d.mkdir(parents=True, exist_ok=False)
    return d


def fetch(url: str, dest: pathlib.Path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
        info = {"status": r.status, "content_type": r.headers.get("Content-Type"),
                "last_modified": r.headers.get("Last-Modified"), "final_url": r.geturl()}
    dest.write_bytes(body)
    time.sleep(WAIT)
    info.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), file=str(dest.relative_to(ROOT)).replace(os.sep, "/"))
    return body, info


def robots_ok(base: str, url: str, d: pathlib.Path):
    try:
        body, info = fetch(base + "/robots.txt", d / "robots.txt")
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.decode("utf-8", "replace").splitlines())
        return rp.can_fetch(UA, url), info
    except urllib.error.HTTPError as e:
        time.sleep(WAIT)
        return e.code == 404, {"status": e.code}


# ---------------------------------------------------------------- V3 GitHub のタグ
def v3():
    out = {}
    git = shutil.which("git")
    if not git:
        return {"git": None}
    tmp = tempfile.mkdtemp(prefix="impl_verify_git_")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        for url, tag in [("https://github.com/openfisca/openfisca-core", "46.0.1"),
                         ("https://github.com/beancount/beancount", "3.2.3")]:
            p = subprocess.run([git, "ls-remote", "--tags", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
                               cwd=tmp, capture_output=True, timeout=120, env=env, stdin=subprocess.DEVNULL)
            out[f"{url} {tag}"] = {"returncode": p.returncode, "lines": p.stdout.decode("utf-8", "replace").splitlines(),
                                   "stderr": p.stderr.decode("utf-8", "replace")[-300:]}
            time.sleep(WAIT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # PyPI の beancount 3.2.3 の wheel の digest
    d = new_dl_dir("IMPL_tools_verify_pypi_beancount")
    body, info = fetch("https://pypi.org/pypi/beancount/3.2.3/json", d / "pypi_beancount_3.2.3.json")
    pj = json.loads(body.decode("utf-8"))
    dg = {u["filename"]: u["digests"]["sha256"] for u in pj.get("urls", [])}
    local = hashlib.sha256(BC_WHEEL.read_bytes()).hexdigest()
    out["beancount wheel の sha256 と PyPI"] = {"取得": info, "PyPI": dg.get(BC_WHEEL.name), "手元": local,
                                                "一致": dg.get(BC_WHEEL.name) == local}
    return out


# ---------------------------------------------------------------- V4 float32 / float64 の食い違い
def f32(x: float) -> float:
    return array("f", [x])[0]


def v4():
    out = {"方法": "float32(x) と float32(r) の積を倍精度で正確に求め、array('f') で float32 に丸めてから floor。"
                   "float64 は Python の float で floor(x * (k/den))。正確な値は (x*k)//den（整数）。"}
    rates = [(5, 100), (10, 100), (20, 100), (30, 100), (40, 100), (29, 100), (57, 100), (21, 1000)]
    for label, step in [("x = 1,000 の倍数（0〜20,000,000）", 1000), ("x = 3 刻み（0〜20,000,000）", 3)]:
        xs = range(0, 20_000_001, step)
        xs32 = array("f", map(float, xs))
        row = {"点の数": len(xs)}
        for k, den in rates:
            r = k / den
            r32 = f32(r)
            prod = array("f", [a * r32 for a in xs32])
            bad32 = small32 = bad64 = 0
            ex32, ex64 = [], []
            for x, p in zip(xs, prod):
                e = (x * k) // den
                if math.floor(p) != e:
                    bad32 += 1
                    if x < 2 ** 24:
                        small32 += 1
                    if len(ex32) < 3:
                        ex32.append([x, math.floor(p), e])
                g = math.floor(x * r)
                if g != e:
                    bad64 += 1
                    if len(ex64) < 3:
                        ex64.append([x, g, e])
            row[f"r={r}"] = {"float32": bad32, "float32 で x<2**24": small32, "float32 の例": ex32,
                             "float64": bad64, "float64 の例": ex64}
        out[label] = row
    from decimal import Decimal
    out["率の2進表現（倍精度の正確な値）"] = {s: str(Decimal(float(s))) for s in ["0.29", "0.57", "0.3", "0.05", "0.1"]}
    out["倍精度の積の例（repr）"] = {f"{x}*{r}": repr(x * r) for x, r in [(1500, 0.29), (3000, 0.29), (300, 0.57), (10, 0.3), (3000, 0.3)]}
    out["float32 への丸め"] = {str(x): f32(float(x)) for x in [16777216, 16777217, 20000001, 123456789]}
    out["int32 のあふれ（2147483647 + 1 を 32 ビットで折り返す）"] = ((2147483647 + 1 + 2 ** 31) % 2 ** 32) - 2 ** 31
    out["0 方向への丸め（C の (int) と同じ）"] = {"1000001*0.3": int(1000001 * 0.3), "-1000001*0.3": int(-1000001 * 0.3),
                                         "切り捨てなら": math.floor(-1000001 * 0.3)}
    return out


# ---------------------------------------------------------------- V5 暦の再計算
def add_years(d: datetime.date, n: int) -> datetime.date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 2月29日
        return d.replace(year=d.year + n, day=28)


def cal_age(birth: datetime.date, on: datetime.date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def legal_age_end_of_day(birth: datetime.date, on: datetime.date) -> int:
    """年齢は誕生日の前日の終わりに加わる、と数えたときの on の日の終わりの年齢（＝ on の翌日の暦の年齢）。"""
    return cal_age(birth, on + datetime.timedelta(days=1))


def v5():
    out = {}
    rows = {}
    for s in ["2025-09-30", "2025-10-01", "2025-10-15", "2025-10-31", "2026-04-01", "2025-09-01"]:
        d = datetime.date.fromisoformat(s)
        stop = add_years(d, 1) - datetime.timedelta(days=1)
        first = datetime.date(d.year, d.month, 1)
        months = []
        y, m = first.year, first.month
        for _ in range(12):
            months.append(f"{y}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        rows[f"year:{s}"] = {"stop": stop.isoformat(), "ADD の月": f"{months[0]}〜{months[-1]}",
                             "境目 2025-10-01 の新値か（start で判定）": d >= datetime.date(2025, 10, 1)}
    out["rolling year の終わりと ADD の月"] = rows
    births = {"12月31日生": "2005-12-31", "1月1日生": "2006-01-01", "1月2日生": "2006-01-02", "2月29日生": "2004-02-29"}
    ages = {}
    for k, b in births.items():
        bd = datetime.date.fromisoformat(b)
        ages[k] = {"暦 2025-12-31": cal_age(bd, datetime.date(2025, 12, 31)),
                   "暦 2026-01-01": cal_age(bd, datetime.date(2026, 1, 1)),
                   "暦 2026-09-30": cal_age(bd, datetime.date(2026, 9, 30)),
                   "前日に加算と数えた 2025-12-31 の終わり": legal_age_end_of_day(bd, datetime.date(2025, 12, 31))}
    out["P09 の年齢"] = ages
    out["P10 見本の合計（子1・子2 の 2025 年）"] = {f"子{i + 1}": sum(80000 + 1000 * i + 100 * m for m in range(1, 13)) for i in range(2)}
    out["P10 見本の年齢（2025-12-31）"] = {k: cal_age(datetime.date.fromisoformat(b), datetime.date(2025, 12, 31))
                                      for k, b in {"父": "1970-05-01", "母": "1972-03-01", "祖母": "1945-01-01",
                                                   "子1": "2005-12-31", "子2": "2006-01-01"}.items()}
    src = (ROOT / "scripts" / "IMPL_tools_openfisca_probe.py").read_text(encoding="utf-8")
    vpy = src.split("VARIABLES_PY = '''", 1)[1].split("'''", 1)[0]
    out["試験用の国パッケージの変数の数（class X(Variable)）"] = len(re.findall(r"^class \S+\(Variable\):", vpy, re.M))
    params = src.split("PARAMS = {", 1)[1].split("\n}\n", 1)[0]
    out["パラメータのファイルの数"] = len(re.findall(r'^    "[^"]+\.yaml":', params, re.M))
    a5 = (ROOT / "scripts" / "IMPL_tools_beancount_probe.py").read_text(encoding="utf-8")
    body = a5.split("def variants(marker):", 1)[1].split("probe_dir = fresh", 1)[0]
    out["beancount A5 の細工の数"] = len(re.findall(r'^            "', body, re.M))
    return out


# ---------------------------------------------------------------- V6 時間の比
def v6():
    of = json.loads(OF_RES.read_text(encoding="utf-8"))
    p11 = of["P11_性能"]["result"]
    out = {}
    cases = [k for k in p11 if k.startswith("家族")]
    for k in cases:
        v = p11[k]
        t = json.loads(v["CLI の内訳（1回目の stderr）"].splitlines()[-1])
        n = json.loads(v["CLI（trace なし）の内訳"].splitlines()[-1])
        on, off = v["プロセス内で evaluate を10回（trace あり）の中央値_s"], v["プロセス内で evaluate を10回（trace なし）の中央値_s"]
        out[k] = {"trace の有無の差（プロセス内、trace なしに対する %）": round((on - off) / off * 100, 2),
                  "import_s / wall（trace あり 1回目）": round(t["import_s"] / v["CLI（別プロセス、trace あり）の wall_s 3回"][0], 3),
                  "import_s / wall（trace なし 1回目）": round(n["import_s"] / v["CLI（trace なし）の wall_s 2回"][0], 3),
                  "evaluate_s（CLI、trace あり / なし）": [t["evaluate_s"], n["evaluate_s"]],
                  "プロセス内 evaluate（あり / なし）": [on, off],
                  "peak_wset_MB（あり / なし）": [t.get("peak_wset_MB"), n.get("peak_wset_MB")],
                  "CLI の evaluate_s の比（あり ÷ なし）": round(t["evaluate_s"] / n["evaluate_s"], 2),
                  "CLI wall（trace あり3回）の最大 ÷ 最小": round(max(v["CLI（別プロセス、trace あり）の wall_s 3回"]) / min(v["CLI（別プロセス、trace あり）の wall_s 3回"]), 3)}
    a, b, c = (p11[k] for k in cases)

    def ratio(x, y, key):
        return round(y[key] / x[key], 2)
    out["8 → 26 シミュレーション（5人）の比"] = {
        "プロセス内 trace あり": ratio(a, b, "プロセス内で evaluate を10回（trace あり）の中央値_s"),
        "プロセス内 trace なし": ratio(a, b, "プロセス内で evaluate を10回（trace なし）の中央値_s"),
        "CLI evaluate_s trace あり": round(out[cases[1]]["evaluate_s（CLI、trace あり / なし）"][0] / out[cases[0]]["evaluate_s（CLI、trace あり / なし）"][0], 2),
        "CLI evaluate_s trace なし": round(out[cases[1]]["evaluate_s（CLI、trace あり / なし）"][1] / out[cases[0]]["evaluate_s（CLI、trace あり / なし）"][1], 2)}
    out["5人 → 10人（26 シミュレーション）の比"] = {
        "プロセス内 trace あり": ratio(b, c, "プロセス内で evaluate を10回（trace あり）の中央値_s"),
        "プロセス内 trace なし": ratio(b, c, "プロセス内で evaluate を10回（trace なし）の中央値_s"),
        "CLI evaluate_s trace あり": round(out[cases[2]]["evaluate_s（CLI、trace あり / なし）"][0] / out[cases[1]]["evaluate_s（CLI、trace あり / なし）"][0], 2),
        "CLI evaluate_s trace なし": round(out[cases[2]]["evaluate_s（CLI、trace あり / なし）"][1] / out[cases[1]]["evaluate_s（CLI、trace あり / なし）"][1], 2)}
    bc = json.loads(BC_RES.read_text(encoding="utf-8"))
    lad = bc["A6_巨大なファイル"]["result"]["1行のコメント（x の繰り返し）の後に plugin 行：parse_file の時間"]
    ts = [lad[f"{m} MB の1行"].get("parse_s") for m in (1, 2, 4, 8)]
    ctrl = bc["A6_巨大なファイル"]["result"]["対照：1 MB の行を16行（16 MB）"]["parse_s"]
    out["beancount A6 長い行"] = {"parse_s": ts, "倍々の比": [round(ts[i + 1] / ts[i], 2) for i in range(3)],
                                 "1 MB×16行 / 1 MB×1行": round(ctrl / ts[0], 1),
                                 "2乗の伸びで 16 MB を見積もる（8 MB × 4）": round(ts[3] * 4, 0),
                                 "2乗の伸びで 20 MB を見積もる": round(ts[3] * (20 / 8) ** 2, 0),
                                 "メモリ（MB）": [lad[f"{m} MB の1行"].get("peak_working_set_MB") for m in (1, 2, 4, 8)]}
    return out


# ---------------------------------------------------------------- V7 文書の数値と results.json
def v7():
    of = json.loads(OF_RES.read_text(encoding="utf-8"))
    bc = json.loads(BC_RES.read_text(encoding="utf-8"))
    checks = []

    def c(label, actual, doc):
        checks.append({"項目": label, "results.json": actual, "文書": doc, "一致": actual == doc})
    p01 = {r["期間の指定"]: r for r in of["P01_U15_期間の途中から始まる期間とパラメータの評価日"]["result"]["年の変数"]}
    doc_p01 = {"2025": ("2025", 3333333, 4444444, 1), "year:2025-09": ("year:2025-09", 3333333, 4444444, 1),
               "year:2025-09-30": ("year:2025-09", 3333333, 4444444, 1), "year:2025-10": ("year:2025-10", 4444444, 4444444, 2),
               "year:2025-10-01": ("year:2025-10", 4444444, 4444444, 2), "year:2025-10-15": ("year:2025-10", 4444444, 4444444, 2),
               "year:2026-04-01": ("year:2026-04", 4444444, 4444444, 2), "2026": ("2026", 4444444, 4444444, 2)}
    for k, v in doc_p01.items():
        r = p01[k]
        c(f"P01 {k}", (r["str(period)"], r["健保_基準値＝parameters(period)"], r["健保_基準値_期間末＝parameters(period.stop)"],
                       r["式の切替_試験（formula_2020_01_01→1、formula_2025_10_01→2）"]), v)
    p05 = of["P05_トレースの構造と根拠"]["result"]
    c("P05 木の数", p05["木の数（calculate を呼んだ回数）"], 6)
    c("P05 flat の件数", p05["get_flat_trace のキーの数"], 34)
    c("P05 computation_log の行数", p05["computation_log.lines() の行数"], 38)
    c("P05 calculation_time（文書の例 0.001112）", p05["flat の1件（扶養判定_試験<2025>）"]["calculation_time"], 0.001112)
    p06 = of["P06_トレースの決定性と負荷"]["result"]
    c("P06 calculation_time の例（文書の『別の実行では 0.00069』）", p06["flat_trace の calculation_time（例。実行ごとに変わる値）"][0], 0.00069)
    c("P06 sha256 の先頭", p06["根拠（時間の欄を除く）の sha256（3回）"][0][:8], "44f7a64c")
    c("P06 中央値 ms", list(p06["1シミュレーション（2人、6変数）の組み立て＋計算の中央値_ms"].values()), [10.121, 14.698])
    c("P05 生年月日の serialized の値の型（キー 生年月日<eternity> は flat に無い）", p05["生年月日<eternity> の serialized の値の型"], [])
    c("P05 flat のキーに 生年月日<2025> があるか", "生年月日<2025>" in p05["get_flat_trace のキー"], True)
    p07 = of["P07_値の型ごとの扱い"]["result"]
    c("P07 int 2**31 の例外にメッセージ too large が残っているか（300 字で切れている）",
      "too large" in p07["給与収入_int（int32）"]["2**31: 2147483648"]["例外"], True)
    p10 = of["P10_CLI"]["result"]
    c("P10 検査で止めた入力の数", len(p10["検査で止めるべき入力"]), 20)
    c("P10 すべて終了コード 2", sorted({v["returncode"] for v in p10["検査で止めるべき入力"].values()}), [2])
    c("P10 出力の大きさ", p10["正常な入力（家族5人、年分2、健保の判定日3）"]["要約"]["出力の大きさ_bytes"], 39720)
    c("P10 2回の sha256 が同じ", p10["同じ入力で2回目（--timing なし）の stdout の sha256 が1回目と同じか"], True)
    a5 = bc["A5_エンコーディングの細工"]["result"]
    c("A5 細工の数", len(a5), 24)
    c("A5 すり抜け（v1 か v2）", any(r["v1 が受け入れたのにコードが実行された（すり抜け）"] or r["v2 が受け入れたのにコードが実行された（すり抜け）"]
                                 for r in a5.values()), False)
    u16 = {k: a5[k]["prescan_v2"]["problems"] for k in a5 if k.startswith("UTF-16LE")}
    c("A5 UTF-16LE（BOM なし）の v2 の理由", [p.split("（")[0].split(":")[0] for p in u16["UTF-16LE（BOM なし）"]], ["NUL を含む"])
    c("A5 UTF-16LE（BOM あり）の v2 の理由", [p.split("（")[0].split(":")[0] for p in u16["UTF-16LE（BOM あり）"]], ["NUL を含む", "UTF-8 でない"])
    b2 = bc["B2_アダプタの出力と決定性"]["result"]
    c("B2 sha256 の先頭", b2["出力の sha256"][:8], "b65fd97c")
    c("B2 写した台帳と同じ", b2["同じか"], True)
    a1 = bc["A1_新しいディレクトリでの走査の安全性"]["result"]
    c("A1 マーカーが1つでもできたか", any(x.get("マーカー（走査の後）", x.get("マーカー（後）")) for row in a1.values() for x in row.values()), False)
    return {"件数": len(checks), "不一致": [x for x in checks if not x["一致"]], "全件": checks}


# ---------------------------------------------------------------- V8 sys.path[0] と -I
def v8():
    out = {"python": sys.version, "executable": sys.executable}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="impl_verify_syspath_"))
    try:
        ledger = tmp / "ledger"
        tooldir = tmp / "tool"
        ledger.mkdir()
        tooldir.mkdir()
        (ledger / "glob.py").write_text("import pathlib\npathlib.Path(__file__).with_name('glob_marker.txt').write_text('shadowed')\n"
                                        "from fnmatch import fnmatch as _f\n", encoding="utf-8")
        (tooldir / "scan_tool.py").write_text("import sys, glob\nprint(repr(sys.path[0]))\nprint(glob.__file__)\n", encoding="utf-8")
        (tooldir / "scan_mod.py").write_text("import sys, glob\nprint(repr(sys.path[0]))\nprint(glob.__file__)\n", encoding="utf-8")
        py = sys.executable
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONSAFEPATH", "PYTHONSTARTUP")}
        cases = {
            "-X utf8 -c（カレント＝台帳）": [py, "-X", "utf8", "-c", "import sys, glob; print(repr(sys.path[0])); print(glob.__file__)"],
            "-I -X utf8 -c（カレント＝台帳）": [py, "-I", "-X", "utf8", "-c", "import sys, glob; print(repr(sys.path[0])); print(glob.__file__)"],
            "-X utf8 スクリプト（スクリプトは別のディレクトリ、カレント＝台帳）": [py, "-X", "utf8", str(tooldir / "scan_tool.py")],
            "-X utf8 -m（PYTHONPATH なし、カレント＝台帳。モジュールはカレントに無いので失敗するはず）": [py, "-X", "utf8", "-m", "scan_mod"],
        }
        for label, cmd in cases.items():
            for m in ledger.glob("glob_marker.txt"):
                m.unlink()
            p = subprocess.run(cmd, cwd=ledger, capture_output=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
            out[label] = {"returncode": p.returncode,
                          "stdout": p.stdout.decode("utf-8", "replace").replace(str(tmp), "<TMP>").splitlines(),
                          "stderr_tail": p.stderr.decode("utf-8", "replace").replace(str(tmp), "<TMP>")[-200:],
                          "マーカー（台帳の glob.py が import された）": (ledger / "glob_marker.txt").exists()}
        # -m で台帳のディレクトリのモジュールを走らせると sys.path[0] はカレント
        shutil.copy(tooldir / "scan_mod.py", ledger / "scan_mod.py")
        for m in ledger.glob("glob_marker.txt"):
            m.unlink()
        p = subprocess.run([py, "-X", "utf8", "-m", "scan_mod"], cwd=ledger, capture_output=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
        out["-X utf8 -m（カレントのモジュール）"] = {"returncode": p.returncode,
                                               "stdout": p.stdout.decode("utf-8", "replace").replace(str(tmp), "<TMP>").splitlines(),
                                               "マーカー（台帳の glob.py が import された）": (ledger / "glob_marker.txt").exists()}
        for label, cmd in {"-I -X utf8 -m（カレントのモジュール）": [py, "-I", "-X", "utf8", "-m", "scan_mod"],
                           "-I -X utf8 スクリプト（スクリプトは別のディレクトリ、カレント＝台帳）": [py, "-I", "-X", "utf8", str(tooldir / "scan_tool.py")]}.items():
            for m in ledger.glob("glob_marker.txt"):
                m.unlink()
            p = subprocess.run(cmd, cwd=ledger, capture_output=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
            out[label] = {"returncode": p.returncode,
                          "stdout": p.stdout.decode("utf-8", "replace").replace(str(tmp), "<TMP>").splitlines(),
                          "stderr_tail": p.stderr.decode("utf-8", "replace").replace(str(tmp), "<TMP>")[-200:],
                          "マーカー（台帳の glob.py が import された）": (ledger / "glob_marker.txt").exists()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# ---------------------------------------------------------------- V9 健保の年齢の基準日の一次情報
def page_text(body: bytes, content_type: str | None) -> str:
    cs = None
    if content_type and "charset=" in content_type.lower():
        cs = content_type.lower().split("charset=")[1].split(";")[0].strip()
    if not cs:
        m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:3000])
        cs = m.group(1).decode("ascii") if m else "utf-8"
    try:
        t = body.decode(cs, "replace")
    except LookupError:
        t = body.decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", "", t)
    t = html.unescape(t)
    t = unicodedata.normalize("NFKC", t)
    return re.sub(r"\s+", "", t)


def find_ctx(text: str, needle: str, width=80):
    i = text.find(needle)
    return None if i < 0 else text[max(0, i - width): i + len(needle) + width]


def v9():
    out = {}
    targets = [
        ("mhlw_R7QA19", "https://www.mhlw.go.jp", "https://www.mhlw.go.jp/web/t_doc?dataId=00tc9628&dataType=1&pageNo=1",
         ["19歳以上23歳未満の被扶養者に係る認定に関するQ&Aについて", "令和7年7月4日", "事務連絡",
          "その年の12月31日現在の年齢で判定する", "誕生日が1月1日である者は12月31日において年齢が加算される"]),
        ("nenkin_faq_timing", "https://www.nenkin.go.jp", "https://www.nenkin.go.jp/section/faq/kounen/dependents/aged19to22/timing.html",
         ["扶養認定日が属する年の12月31日時点の年齢で判定"]),
    ]
    for name, base, url, needles in targets:
        d = new_dl_dir(f"IMPL_tools_verify_{name}")
        ok, rinfo = robots_ok(base, url, d)
        row = {"url": url, "取得日": datetime.date.today().isoformat(), "robots で許可": ok, "robots": rinfo}
        if not ok:
            out[name] = row
            continue
        try:
            body, info = fetch(url, d / "page.html")
        except urllib.error.HTTPError as e:
            row["error"] = f"HTTP {e.code}"
            out[name] = row
            continue
        row["取得"] = info
        text = page_text(body, info.get("content_type"))
        row["見つかった文"] = {n: find_ctx(text, unicodedata.normalize("NFKC", n).replace(" ", ""), 60) for n in needles}
        row["見つからなかった文"] = [n for n, v in row["見つかった文"].items() if v is None]
        m = re.search(r"更新日[:：]?\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)", text)
        row["ページの更新日"] = m.group(1) if m else None
        out[name] = row
    return out


# ---------------------------------------------------------------- 本体
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    R["env"] = {"python": sys.version, "isolated": sys.flags.isolated, "utf8_mode": sys.flags.utf8_mode,
                "実行日": datetime.date.today().isoformat()}
    record("V1_ソースの行番号", v1)
    record("V2_版の一致", v2)
    record("V3_GitHub のタグと PyPI", v3)
    record("V4_floor の食い違いの再計算", v4)
    record("V5_暦の再計算", v5)
    record("V6_時間の比", v6)
    record("V7_文書の数値と results.json", v7)
    record("V8_sys.path[0] と -I", v8)
    record("V9_健保の年齢の基準日（一次情報）", v9)
    (OUT / "results.json").write_text(json.dumps(R, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = []
    for k, v in R.items():
        lines.append(f"## {k}\n{json.dumps(v, ensure_ascii=False, indent=1, default=str)}\n")
    (OUT / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
