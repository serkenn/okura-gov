"""IMPL3 diffs: scripts/IMPL3_egov_fetch.py が取り出した条文のテキストを、版（令和7年分と令和8年分、令和8年度と令和9年度）の間で条ごとに比べる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_diffs.py

- 入力：scripts/results/IMPL3_egov_fetch/<topic>/<略称>_<asof>.txt（「## Num=」「## 附則 Num=」で条を区切ったもの）。
- 出力：scripts/results/IMPL3_diffs/<topic>_<略称>.md（条ごとに「同じ」か、違えば unified diff）。
"""
import difflib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
IN = ROOT / "scripts" / "results" / "IMPL3_egov_fetch"
OUT = ROOT / "scripts" / "results" / "IMPL3_diffs"


def sections(path):
    secs, cur, buf = {}, None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## ((?:附則 )?Num=\S+)", line)
        if m:
            if cur:
                secs[cur] = buf
            cur, buf = m.group(1), []
            continue
        if cur:
            buf.append(line)
    if cur:
        secs[cur] = buf
    return secs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for td in sorted(p for p in IN.iterdir() if p.is_dir() and p.name != "sames"):
        groups = {}
        for f in td.glob("*.txt"):
            if f.name.startswith("grep_"):
                continue
            short, asof = f.stem.rsplit("_", 1)
            groups.setdefault(short, []).append((asof, f))
        for short, files in groups.items():
            files.sort()
            if len(files) < 2:
                continue
            lines = [f"# {td.name} / {short}：版の間の条ごとの比較", ""]
            for (a, fa), (b, fb) in zip(files, files[1:]):
                sa, sb = sections(fa), sections(fb)
                hdr_a = fa.read_text(encoding="utf-8").splitlines()[1]
                hdr_b = fb.read_text(encoding="utf-8").splitlines()[1]
                lines += [f"## {a} → {b}", f"- {a}: {hdr_a}", f"- {b}: {hdr_b}", ""]
                for k in list(dict.fromkeys(list(sa) + list(sb))):
                    if sa.get(k) == sb.get(k):
                        lines.append(f"- {k}：同じ")
                        continue
                    lines.append(f"- {k}：**違う**")
                    lines.append("```diff")
                    lines += list(difflib.unified_diff(sa.get(k, []), sb.get(k, []), a, b, lineterm="", n=0))
                    lines.append("```")
                lines.append("")
            (OUT / f"{td.name}_{short}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()
