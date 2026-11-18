"""直す前の版の写し（.work/perf/snap_src）に、持ち場の共有のファイルだけを今の版から重ねた木を作る（使い捨て）。

並行の担当が規則モジュールを書き換えている間も、同じ規則で前後を比べるため。
  python -I -X utf8 scripts/IMPL5_core-perf_devtree.py <出力の src ディレクトリ> [before]
before を付けると重ねない（直す前の版そのもの）。
"""
import os
import shutil
import sys
from pathlib import Path

MINE = [
    "evaluate.py",
    "registry.py",
    "situation.py",
    "result.py",
    "query.py",
    "candidates.py",
    "explain.py",
    "basis.py",
    "cli.py",
    "__init__.py",
    "concepts/__init__.py",
    "schema/result.schema.json",
    "boundaries.py",
    "scenarios.py",
    "forms_output.py",
    "forms",
]
#: 重ねるファイルを環境変数 PERF_FILES（カンマ区切り）で絞れる（2026-11-12 の3回目：evaluate.py,situation.py,registry.py だけ。
#: forms などは並行の担当が書き換えているので、写しのままにする）
if os.environ.get("PERF_FILES"):
    MINE = os.environ["PERF_FILES"].split(",")
out = Path(sys.argv[1])
#: 直す前の版の写し（環境変数 PERF_SNAP で替えられる。2026-11-12 の2回目は .work/perf2/snap_src）
snap = Path(os.environ.get("PERF_SNAP", ".work/perf/snap_src")) / "okura_core"
live = Path("packages/core/src/okura_core")
if out.exists():
    shutil.rmtree(out)
shutil.copytree(snap, out / "okura_core")
if not (len(sys.argv) > 2 and sys.argv[2] == "before"):
    for rel in MINE:
        src = live / rel
        if src.is_dir():
            shutil.rmtree(out / "okura_core" / rel, ignore_errors=True)
            shutil.copytree(src, out / "okura_core" / rel, ignore=shutil.ignore_patterns("__pycache__"))
        elif src.exists():
            shutil.copy2(src, out / "okura_core" / rel)
print("ok", out)
