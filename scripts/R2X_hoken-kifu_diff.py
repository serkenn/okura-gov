"""R2X_hoken-kifu: scripts/R2X_hoken-kifu_egov2.py が書いた条文のテキストから、変更の時点の前後（asof 2026-03-31 と 2026-04-01）の
差分を作る。ネットワークは使わない。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_hoken-kifu_diff.py
入力：scripts/results/R2X_hoken-kifu_egov2/articles_<略称>_<asof>.txt（先に R2X_hoken-kifu_egov2.py を実行しておく）
出力：scripts/results/R2X_hoken-kifu_diff/diff_<略称>_<節>_<asofA>_<asofB>.txt と summary.json
"""
import difflib
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "results" / "R2X_hoken-kifu_egov2"
OUT = ROOT / "scripts" / "results" / "R2X_hoken-kifu_diff"

# (略称, 節の見出し行, asofA, asofB)
PAIRS = [
    ("sochi", "## 本則 Num=41_15_5", "2026-03-31", "2026-04-01"),
    ("shotoku", "## 本則 Num=78", "2026-03-31", "2026-04-01"),
    ("chiho", "## 本則 Num=314_7", "2026-03-31", "2026-04-01"),
    ("chiho", "## 原始附則 Num=7_2", "2026-03-31", "2026-04-01"),
]


def section(path, head):
    lines = path.read_text(encoding="utf-8").split("\n")
    out, on = [], False
    for ln in lines:
        if ln.startswith("## ") or ln.startswith("# ----"):
            on = (ln.strip() == head)
            continue
        if on:
            out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for short, head, a, b in PAIRS:
        fa, fb = SRC / f"articles_{short}_{a}.txt", SRC / f"articles_{short}_{b}.txt"
        sa, sb = section(fa, head), section(fb, head)
        ud = list(difflib.unified_diff(sa, sb, fromfile=f"{short} {head} asof={a}", tofile=f"{short} {head} asof={b}", lineterm="", n=0))
        name = head.replace("## ", "").replace(" ", "_").replace("=", "")
        fn = f"diff_{short}_{name}_{a}_{b}.txt"
        (OUT / fn).write_text("\n".join(ud), encoding="utf-8")
        rec = {"short": short, "section": head, "from": a, "to": b, "lines_from": len(sa), "lines_to": len(sb),
               "sha256_from": hashlib.sha256("\n".join(sa).encode("utf-8")).hexdigest(),
               "sha256_to": hashlib.sha256("\n".join(sb).encode("utf-8")).hexdigest(),
               "changed_lines": sum(1 for x in ud if x.startswith(("+", "-")) and not x.startswith(("+++", "---"))), "file": fn}
        summary.append(rec)
        print(rec)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
