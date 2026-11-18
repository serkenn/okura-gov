"""SAKUSEI: 取得した xlsx（ZIP）を展開せずに読み、シート名・数式の数・マクロの有無を調べる。

実行: python -I scripts/SAKUSEI_xlsx.py <xlsxファイル> [--show-formulas] [--cells=A1,B2,...]
  --cells= ：最初のシートの指定セルの値（共有文字列は文字列に直す）を端末に表示する（見出しの確認用）。

- 取得したファイルは信頼できないデータ。ディスクへは展開せず、zipfile でメモリ上で XML を読むだけ。
  各エントリの展開後サイズが大きすぎるもの（50MB超）は読まない（ZIP 爆弾対策）。
- 標準出力に要約（JSON）を出す。--show-formulas を付けると、数式を端末に表示する（確認用。リポジトリには書かない）。
- 要約は scripts/results/SAKUSEI_xlsx/<ファイル名>.json に書く（数式の本文は含めない。数式で使われている関数名と件数だけ）。
標準ライブラリのみ。
"""
import collections
import hashlib
import json
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIMIT = 50 * 1024 * 1024


def main(a):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = pathlib.Path(a[0])
    show = "--show-formulas" in a
    raw = p.read_bytes()
    z = zipfile.ZipFile(p)
    entries = [(i.filename, i.file_size) for i in z.infolist()]
    wb = z.read("xl/workbook.xml").decode("utf-8")
    sheets = re.findall(r'<sheet [^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', wb)
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    relmap = dict((m[1], m[0]) for m in re.findall(r'<Relationship [^>]*Target="([^"]+)"[^>]*Id="([^"]+)"', rels))
    relmap.update(dict(re.findall(r'<Relationship [^>]*Id="([^"]+)"[^>]*Target="([^"]+)"', rels)))
    defined = re.findall(r'<definedName [^>]*name="([^"]+)"', wb)
    summary = {"file": p.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
               "has_vba": any("vbaProject" in n for n, _ in entries),
               "entries": [{"name": n, "size": s} for n, s in entries], "defined_names": defined, "sheets": []}
    for name, rid in sheets:
        target = relmap.get(rid, "")
        path = "xl/" + target.lstrip("/").replace("xl/", "", 1) if not target.startswith("/xl/") else target[1:]
        info = z.getinfo(path)
        if info.file_size > LIMIT:
            summary["sheets"].append({"name": name, "path": path, "skipped": "too large"})
            continue
        x = z.read(path).decode("utf-8")
        forms = re.findall(r'<c r="([A-Z]+[0-9]+)"[^>]*>(?:(?!</c>).)*?<f[^>]*>([^<]*)</f>', x, flags=re.S)
        shared = len(re.findall(r'<f [^>]*t="shared"[^>]*/>', x))
        funcs = collections.Counter(f for _, body in forms for f in re.findall(r"([A-Z][A-Z0-9.]+)\(", body))
        dv = len(re.findall(r"<dataValidation ", x))
        summary["sheets"].append({"name": name, "path": path, "formula_cells": len(forms),
                                  "shared_formula_refs": shared, "functions": dict(funcs.most_common()),
                                  "data_validations": dv})
        if show:
            print(f"== {name} ({path})")
            for ref, body in forms:
                print(f"{ref}\t{body.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', chr(34))[:300]}")
    cells_arg = [x for x in a if x.startswith("--cells=")]
    if cells_arg:
        want = cells_arg[0].split("=", 1)[1].split(",")
        ss = []
        if "xl/sharedStrings.xml" in z.namelist():
            sx = z.read("xl/sharedStrings.xml").decode("utf-8")
            ss = ["".join(re.findall(r"<t[^>]*>([^<]*)</t>", si)) for si in re.findall(r"<si>(.*?)</si>", sx, flags=re.S)]
        x = z.read(summary["sheets"][0]["path"]).decode("utf-8")
        for ref in want:
            m = re.search(rf'<c r="{ref}"([^>]*)>(.*?)</c>', x, flags=re.S)
            val = None
            if m:
                v = re.search(r"<v>([^<]*)</v>", m.group(2))
                if v and 't="s"' in m.group(1):
                    val = ss[int(v.group(1))]
                elif v:
                    val = v.group(1)
            print(f"{ref}\t{val}")
    out = ROOT / "scripts" / "results" / "SAKUSEI_xlsx"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{p.name}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "entries"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
