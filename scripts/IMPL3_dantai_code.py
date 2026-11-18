"""IMPL3 dantai_code: 総務省「全国地方公共団体コード」仕様（平成19年4月1日）の検査数字の方式を、総務省の一覧表（Excel）の全部のコードに当てて確かめ、
都道府県コード（第3〜5桁が000）と市区町村コードの対応（第1・2桁）、指定都市（第3〜5桁が100〜199 のうち市）・区を数える。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_dantai_code.py <一覧表の xlsx のパス>

- 入力の xlsx は scripts/IMPL3_web_fetch.py soumu_xlsx が .work/downloads/<ts>_IMPL3_web_fetch_soumu_xlsx/ に置いた信頼できないデータ。
  zipfile と xml.etree.ElementTree で読むだけ（マクロ・外部参照は使わない。中では何も実行しない）。
- 検査数字の方式（仕様 11）：第1桁〜第5桁に 6・5・4・3・2 を掛けた積の和を 11 で割った余りを r として、(11 − r) の下1桁。
  ただし積の和が 11 より小さいときは 11 − 積の和。仕様の例 062014 でも確かめる。
- 出力：scripts/results/IMPL3_dantai_code/summary.json（件数、検査数字が合わないコード、都道府県コード、第1・2桁ごとの件数、
  第3〜5桁が100〜199 のコードの名前の一覧〔指定都市・区・特別区〕）。個人の情報は含まない（公開の団体名だけ）。
"""
import json
import pathlib
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL3_dantai_code"
LOOKUP = {"130001", "131016"}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def check_digit(five):
    s = sum(int(d) * w for d, w in zip(five, (6, 5, 4, 3, 2)))
    if s < 11:
        return (11 - s) % 10  # 仕様「11から積の和を控除した数字」（積の和が1〜10 なら 10〜1。10 のときの扱いは仕様に書かれていないので下1桁にした）
    return (11 - s % 11) % 10


def read_xlsx(path):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    out = {}
    for sh in sheets:
        root = ET.fromstring(z.read(sh))
        rows = []
        for r in root.iter("{%s}row" % NS["m"]):
            cells = []
            for c in r.findall("m:c", NS):
                v = c.find("m:v", NS)
                t = c.get("t")
                if v is None:
                    is_ = c.find("m:is", NS)
                    cells.append("".join(x.text or "" for x in is_.iter("{%s}t" % NS["m"])) if is_ is not None else "")
                elif t == "s":
                    cells.append(shared[int(v.text)])
                else:
                    cells.append(v.text or "")
            rows.append(cells)
        out[sh] = rows
    return out


def main(path):
    OUT.mkdir(parents=True, exist_ok=True)
    sheets = read_xlsx(path)
    summary = {"input": str(path), "spec_example_062014": check_digit("06201") == 4, "sheets": {}}
    for sh, rows in sheets.items():
        codes = []
        for r in rows:
            if not r:
                continue
            c0 = r[0].strip()
            if re.fullmatch(r"\d{6}", c0):
                codes.append((c0, [x.strip() for x in r[1:4]]))
        bad = [c for c, _ in codes if int(c[5]) != check_digit(c[:5])]
        prefs = [(c, n) for c, n in codes if c[2:5] == "000"]
        by_pref = {}
        for c, _ in codes:
            by_pref[c[:2]] = by_pref.get(c[:2], 0) + 1
        hundred = [(c, n) for c, n in codes if 100 <= int(c[2:5]) <= 199]
        summary["sheets"][sh] = {
            "rows": len(rows), "codes": len(codes), "check_digit_mismatch": bad,
            "prefecture_codes": len(prefs), "prefecture_code_examples": prefs[:3],
            "first2_distinct": len(by_pref),
            "codes_100_199_count": len(hundred),
            "codes_x100": [(c, n) for c, n in hundred if c[2:5] == "100"],
            "header_rows": rows[:2],
            "lookup": {k: n for k, n in codes if k in LOOKUP},  # 推測の例（docs/inferences/20261111_impl-research3_all-cases.md J-4）の照合
        }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for sh, v in summary["sheets"].items():
        print(sh, {k: (v[k] if not isinstance(v[k], list) or len(v[k]) < 6 else f"{len(v[k])}件") for k in v})
    print("spec example ok:", summary["spec_example_062014"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(pathlib.Path(sys.argv[1]))
