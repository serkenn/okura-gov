"""IMPL_output: 取得した xlsx（ZIP）を展開せずに読み、全シートのセルの値と入力規則（プルダウンの選択肢など）を書き出す。

実行: python -I -X utf8 scripts/IMPL_output_xlsx.py <xlsxファイル> <出力名>

- 取得したファイルは信頼できないデータ。ディスクへは展開せず、zipfile でメモリ上で XML を読むだけ。
  各エントリの展開後サイズが LIMIT を超えるものは読まない（ZIP 爆弾対策）。マクロ（vbaProject.bin）は読まない。
- XML は正規表現で読む（外部実体の解決などはしない）。
- 出力：scripts/results/IMPL_output_xlsx/<出力名>/
    summary.json        … ファイルの SHA-256、シート名、数式の数、入力規則、マクロの有無
    <シート番号>_cells.tsv … 空でないセルの「セル番地<TAB>種類<TAB>値」（数式のセルは値の代わりに数式を書く）
標準ライブラリのみ。
"""
import hashlib
import html
import json
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIMIT = 50 * 1024 * 1024


def read(z, name):
    info = z.getinfo(name)
    if info.file_size > LIMIT:
        raise ValueError(f"too large: {name} {info.file_size}")
    return z.read(name).decode("utf-8")


def main(a):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p, outname = pathlib.Path(a[0]), re.sub(r"[^A-Za-z0-9_.-]", "_", a[1])
    raw = p.read_bytes()
    z = zipfile.ZipFile(p)
    names = z.namelist()
    wb = read(z, "xl/workbook.xml")
    sheets = re.findall(r'<sheet [^>]*?name="([^"]+)"[^>]*?r:id="([^"]+)"', wb)
    rels = read(z, "xl/_rels/workbook.xml.rels")
    relmap = {}
    for m in re.finditer(r"<Relationship ([^>]*)/?>", rels):
        at = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        relmap[at.get("Id")] = at.get("Target", "")
    ss = []
    if "xl/sharedStrings.xml" in names:
        sx = read(z, "xl/sharedStrings.xml")
        for si in re.findall(r"<si>(.*?)</si>", sx, flags=re.S):
            si = re.sub(r"<rPh .*?</rPh>", "", si, flags=re.S)  # ふりがなを除く
            ss.append(html.unescape("".join(re.findall(r"<t[^>]*>([^<]*)</t>", si))))
    out = ROOT / "scripts" / "results" / "IMPL_output_xlsx" / outname
    out.mkdir(parents=True, exist_ok=True)
    summary = {"file": p.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
               "has_vba": any("vbaProject" in n for n in names), "sheets": []}
    for i, (sname, rid) in enumerate(sheets, 1):
        target = relmap.get(rid, "")
        path = target[1:] if target.startswith("/") else "xl/" + target
        x = read(z, path)
        rows = []
        nform = 0
        for m in re.finditer(r'<c r="([A-Z]+[0-9]+)"([^>]*?)(?:/>|>(.*?)</c>)', x, flags=re.S):
            ref, attrs, body = m.group(1), m.group(2), m.group(3) or ""
            f = re.search(r"<f[^>]*>([^<]*)</f>", body)
            v = re.search(r"<v>([^<]*)</v>", body)
            t = re.search(r't="([^"]+)"', attrs)
            t = t.group(1) if t else "n"
            if f:
                nform += 1
                rows.append((ref, "formula", html.unescape(f.group(1))))
                continue
            if t == "s" and v:
                rows.append((ref, "s", ss[int(v.group(1))]))
            elif t == "inlineStr":
                rows.append((ref, "inline", html.unescape("".join(re.findall(r"<t[^>]*>([^<]*)</t>", body)))))
            elif v:
                rows.append((ref, t, html.unescape(v.group(1))))
        dvs = []
        for m in re.finditer(r"<dataValidation ([^>]*)>(.*?)</dataValidation>", x, flags=re.S):
            at = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            f1 = re.search(r"<formula1>(.*?)</formula1>", m.group(2), flags=re.S)
            dvs.append({"sqref": at.get("sqref"), "type": at.get("type"), "allowBlank": at.get("allowBlank"),
                        "promptTitle": html.unescape(at.get("promptTitle", "")), "prompt": html.unescape(at.get("prompt", "")),
                        "errorTitle": html.unescape(at.get("errorTitle", "")), "error": html.unescape(at.get("error", "")),
                        "formula1": html.unescape(f1.group(1)) if f1 else None})
        # x14 拡張の入力規則（別シート参照のリストなど）
        for m in re.finditer(r"<x14:dataValidation ([^>]*)>(.*?)</x14:dataValidation>", x, flags=re.S):
            at = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            f1 = re.search(r"<xm:f>(.*?)</xm:f>", m.group(2), flags=re.S)
            sq = re.search(r"<xm:sqref>(.*?)</xm:sqref>", m.group(2), flags=re.S)
            dvs.append({"sqref": sq.group(1) if sq else None, "type": at.get("type"), "x14": True,
                        "formula1": html.unescape(f1.group(1)) if f1 else None})
        merged = re.findall(r'<mergeCell ref="([^"]+)"', x)
        (out / f"{i:02d}_cells.tsv").write_text(
            f"# sheet={sname} path={path}\n" + "\n".join(f"{r}\t{t}\t{v}".replace("\r", "").replace("\n", "\\n") for r, t, v in rows),
            encoding="utf-8")
        summary["sheets"].append({"index": i, "name": sname, "path": path, "cells": len(rows), "formula_cells": nform,
                                  "data_validations": dvs, "merged_cells": len(merged),
                                  "dimension": (re.search(r'<dimension ref="([^"]+)"', x) or [None, None])[1]})
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()}, ensure_ascii=False, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
