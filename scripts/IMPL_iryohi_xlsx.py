"""IMPL_iryohi: 国税庁「医療費集計フォーム」（xlsx）の列の構成（見出し・入力規則・数式の参照先）を読む。

実行（xlsx のパスを引数で渡す。ダウンロードしたディレクトリの中ではインタプリタを実行しない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_iryohi_xlsx.py <xlsx> [<xlsx> ...]

- 取得したファイルは信頼できないデータ。ディスクへは展開せず、zipfile でメモリ上で XML を読むだけ。
  展開後 50MB を超えるエントリは読まない（ZIP 爆弾対策）。XML は正規表現で読む（外部実体を解決しない）。
- 出力：scripts/results/IMPL_iryohi_xlsx/<ファイル名>.json
  - 各シートの 1〜8 行目のセルの値（共有文字列は文字列に直す）
  - 入力規則（dataValidation の範囲・種類・リストの値）
  - 数式のあるセルと数式（国税庁の表の構造を確かめるため。式は短い SUM/IF/ROW だけ）
  - 「ご利用に当たって」シートの文字列（全セル）
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
OUT = ROOT / "scripts" / "results" / "IMPL_iryohi_xlsx"
LIMIT = 50 * 1024 * 1024


def read(z, name):
    info = z.getinfo(name)
    if info.file_size > LIMIT:
        raise ValueError(f"too large: {name}")
    return z.read(name).decode("utf-8")


def shared_strings(z):
    try:
        x = read(z, "xl/sharedStrings.xml")
    except KeyError:
        return []
    out = []
    for si in re.findall(r"<si>(.*?)</si>", x, flags=re.S):
        si = re.sub(r"<rPh\b.*?</rPh>", "", si, flags=re.S)  # ふりがな（ルビ）は落とす
        out.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, flags=re.S))))
    return out


def cells(x, ss):
    res = {}
    for m in re.finditer(r'<c r="([A-Z]+)([0-9]+)"([^>]*?)(?:/>|>(.*?)</c>)', x, flags=re.S):
        col, row, attrs, inner = m.group(1), int(m.group(2)), m.group(3), m.group(4) or ""
        t = re.search(r't="([^"]+)"', attrs)
        v = re.search(r"<v>(.*?)</v>", inner, flags=re.S)
        f = re.search(r"<f[^>]*>(.*?)</f>", inner, flags=re.S)
        isv = re.search(r"<is>(.*?)</is>", inner, flags=re.S)
        val = None
        if t and t.group(1) == "s" and v:
            val = ss[int(v.group(1))]
        elif isv:
            val = html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", isv.group(1), flags=re.S)))
        elif v:
            val = html.unescape(v.group(1))
        res[(row, col)] = {"v": val, "f": html.unescape(f.group(1)) if f else None}
    return res


def main(paths):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    for p in map(pathlib.Path, paths):
        raw = p.read_bytes()
        z = zipfile.ZipFile(p)
        names = z.namelist()
        ss = shared_strings(z)
        wb = read(z, "xl/workbook.xml")
        rels = read(z, "xl/_rels/workbook.xml.rels")
        relmap = {}
        for m in re.finditer(r"<Relationship ([^>]*)/?>", rels):
            a = m.group(1)
            i = re.search(r'Id="([^"]+)"', a)
            t = re.search(r'Target="([^"]+)"', a)
            if i and t:
                relmap[i.group(1)] = t.group(1)
        summary = {"file": p.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                   "has_vba": any("vbaProject" in n for n in names), "sheets": []}
        for m in re.finditer(r"<sheet ([^>]*)/>", wb):
            a = m.group(1)
            name = html.unescape(re.search(r'name="([^"]+)"', a).group(1))
            rid = re.search(r'r:id="([^"]+)"', a).group(1)
            target = relmap[rid].lstrip("/")
            path = target if target.startswith("xl/") else "xl/" + target
            x = read(z, path)
            cs = cells(x, ss)
            head = {f"{c}{r}": d["v"] for (r, c), d in sorted(cs.items()) if (r <= 8 or (r == 2 and c in ("L", "M"))) and d["v"] not in (None, "")}
            head["L2(raw)"] = cs.get((2, "L"), {}).get("v")
            forms = {f"{c}{r}": d["f"] for (r, c), d in sorted(cs.items()) if d["f"]}
            dvs = []
            for dm in re.finditer(r"<dataValidation ([^>]*)>(.*?)</dataValidation>", x, flags=re.S):
                attrs, inner = dm.group(1), dm.group(2)
                f1 = re.search(r"<formula1>(.*?)</formula1>", inner, flags=re.S)
                f2 = re.search(r"<formula2>(.*?)</formula2>", inner, flags=re.S)
                dvs.append({"type": (re.search(r'type="([^"]+)"', attrs) or [None, None])[1],
                            "sqref": (re.search(r'sqref="([^"]+)"', attrs) or [None, None])[1],
                            "allowBlank": (re.search(r'allowBlank="([^"]+)"', attrs) or [None, None])[1],
                            "operator": (re.search(r'operator="([^"]+)"', attrs) or [None, None])[1],
                            "formula1": html.unescape(f1.group(1)) if f1 else None,
                            "formula2": html.unescape(f2.group(1)) if f2 else None,
                            "promptTitle": html.unescape((re.search(r'promptTitle="([^"]*)"', attrs) or [None, ""])[1]),
                            "prompt": html.unescape((re.search(r'prompt="([^"]*)"', attrs) or [None, ""])[1]),
                            "errorTitle": html.unescape((re.search(r'errorTitle="([^"]*)"', attrs) or [None, ""])[1]),
                            "error": html.unescape((re.search(r'error="([^"]*)"', attrs) or [None, ""])[1])})
            sh = {"name": name, "path": path, "max_row": max((r for r, _ in cs), default=0),
                  "rows_1_8": head, "formulas": forms if len(forms) <= 60 else dict(list(forms.items())[:60]),
                  "n_formulas": len(forms), "data_validations": dvs}
            if "利用" in name:
                sh["all_text"] = [f"{c}{r}: {d['v']}" for (r, c), d in sorted(cs.items()) if isinstance(d["v"], str) and d["v"].strip()]
            summary["sheets"].append(sh)
        (OUT / f"{p.stem}_{summary['sha256'][:12]}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(p.name, summary["sha256"], [s["name"] for s in summary["sheets"]])


if __name__ == "__main__":
    main(sys.argv[1:])
