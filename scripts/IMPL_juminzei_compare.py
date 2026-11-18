"""IMPL juminzei: IMPL_juminzei_laws.py が書いた条文テキストを、版（asof）の間で条ごとに比べ、変わった文字列だけを抜き出す。

実行（ネットワーク不要。入力は scripts/results/IMPL_juminzei_laws/ の自分の出力だけ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_compare.py

出力: scripts/results/IMPL_juminzei_compare/changes.md
  条（"## " 見出しの単位）ごとに、隣り合う asof の間で変わった箇所を「前後 40 文字＋旧→新」で示す。
  改正附則の節は版によって収録の範囲が違うので、本則・原始附則の節だけを比べる。
"""
import difflib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "results" / "IMPL_juminzei_laws"
OUT = ROOT / "scripts" / "results" / "IMPL_juminzei_compare"
CTX = 40


def sections(path):
    secs, cur, buf = {}, None, []
    header = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and cur is None:
            header.append(line)
            continue
        if line.startswith("## "):
            if cur is not None:
                secs[cur] = "\n".join(buf).strip()
            cur, buf = line[3:].strip(), []
            continue
        if cur is not None:
            buf.append(line)
    if cur is not None:
        secs[cur] = "\n".join(buf).strip()
    return header, secs


def changes(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    res = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        before = a[max(0, i1 - CTX):i1].replace("\n", "⏎")
        after = a[i2:i2 + CTX].replace("\n", "⏎")
        res.append(f"…{before}【{a[i1:i2].replace(chr(10), '⏎')} → {b[j1:j2].replace(chr(10), '⏎')}】{after}…")
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    md = ["# 版の間の条文の変化（IMPL_juminzei_compare.py）", "",
          f"入力: {SRC.relative_to(ROOT)}/<略称>_<asof>.txt", ""]
    for short in ("chiho", "chiho-rei", "chiho-ki"):
        files = sorted(SRC.glob(f"{short}_????-??-??.txt"))
        if len(files) < 2:
            continue
        parsed = []
        for f in files:
            asof = re.search(r"_(\d{4}-\d{2}-\d{2})\.txt$", f.name).group(1)
            h, s = sections(f)
            parsed.append((asof, h, {k: v for k, v in s.items() if k.startswith(("本則", "原始附則"))}))
        md += [f"## {short}", ""]
        for asof, h, _ in parsed:
            md.append(f"- {asof}: {h[1][2:] if len(h) > 1 else ''}")
        md.append("")
        for (xa, _, xs), (ya, _, ys) in zip(parsed, parsed[1:]):
            md += [f"### {xa} → {ya}", ""]
            keys = list(dict.fromkeys(list(xs) + list(ys)))
            any_change = False
            for k in keys:
                a, b = xs.get(k), ys.get(k)
                if a == b:
                    continue
                any_change = True
                if a is None:
                    md.append(f"- {k}: {ya} で新たに抜き出された（{xa} の抜き出しにはない）")
                    continue
                if b is None:
                    md.append(f"- {k}: {ya} の抜き出しにはない")
                    continue
                md.append(f"- {k}:")
                for c in changes(a, b):
                    md.append(f"  - {c}")
            if not any_change:
                md.append("- 変化なし")
            md.append("")
        # 主な条について、隣り合う版の間で変わったかどうかの一覧
        key = [k for k in KEY.get(short, []) if any(k in s for _, _, s in parsed)]
        if key:
            md += [f"### {short}：主な条の変化の有無（○＝同じ、×＝違う、－＝抜き出しにない）", "",
                   "| 条 | " + " | ".join(f"{x}→{y}" for (x, _, _), (y, _, _) in zip(parsed, parsed[1:])) + " |",
                   "|---|" + "---|" * (len(parsed) - 1)]
            for k in key:
                cells = []
                for (_, _, xs), (_, _, ys) in zip(parsed, parsed[1:]):
                    a, b = xs.get(k), ys.get(k)
                    cells.append("－" if a is None or b is None else ("○" if a == b else "×"))
                md.append(f"| {k} | " + " | ".join(cells) + " |")
            md.append("")
    md += sapporo()
    (OUT / "changes.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("done", OUT / "changes.md")


KEY = {
    "chiho": ["本則 Num=24_5", "本則 Num=292", "本則 Num=295", "本則 Num=310", "本則 Num=313", "本則 Num=314_2", "本則 Num=317_2",
              "本則 Num=317_3", "本則 Num=317_6", "本則 Num=318", "原始附則 Num=3_3"],
    "chiho-rei": ["本則 Num=46_3", "本則 Num=46_4", "本則 Num=46_5", "本則 Num=47_3", "本則 Num=48_9_7"],
    "chiho-ki": ["本則 Num=9_21"],
}

MUNI = ROOT / "scripts" / "results" / "IMPL_juminzei_municipal"


def sapporo():
    """札幌市税条例の現行と未施行の表示で、主な条の文字列が同じかを比べる（入力は IMPL_juminzei_municipal.py の出力）。"""
    a_p, b_p = MUNI / "sapporo_shizei_jorei.txt", MUNI / "sapporo_shizei_jorei_misikou.txt"
    if not (a_p.exists() and b_p.exists()):
        return ["## 札幌市税条例：入力がない", ""]
    a, b = a_p.read_text(encoding="utf-8"), b_p.read_text(encoding="utf-8")

    def art(t, start, stop):
        i = t.find(start)
        if i < 0:
            return None
        j = t.find(stop, i + 1)
        return t[i:j if j > 0 else None]
    out = ["## 札幌市税条例：現行（_j.html）と未施行の表示（_misikou_j.html）の比較", "",
           "| 条（見出し） | 現行の文字数 | 未施行の表示の文字数 | 同じか |", "|---|---|---|---|"]
    for start, stop in [("（個人の市民税の非課税の範囲）", "第20条"), ("（市民税の申告）", "（所得税に係る更正"),
                        ("（個人の市民税の所得割の非課税の範囲等）", "一部改正")]:
        x, y = art(a, start, stop), art(b, start, stop)
        out.append(f"| {start} | {len(x or '')} | {len(y or '')} | {'同じ' if x == y and x else '違う／見つからない'} |")
    out.append("")
    return out


if __name__ == "__main__":
    main()
