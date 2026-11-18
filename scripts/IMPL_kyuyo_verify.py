"""IMPL_kyuyo_verify: kyuyo トピック（給与所得の計算と住民税への波及）の文書を、一次情報に当たり直して独立に検証する（反証役）。

このスクリプトは、他の担当のスクリプト（IMPL_kyuyo_*.py）とその出力を import も再利用もしない。
e-Gov 法令API v2・国税庁などから自分で取り直し、自分の読み方（別の実装）で表を読み、自分で再計算する。
その後で、他の担当の出力（scripts/results/IMPL_kyuyo_*）と突き合わせる。

実行（Python 標準ライブラリのみ）:
  PY=C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe
  $PY -I -X utf8 scripts/IMPL_kyuyo_verify.py fetch_laws        # e-Gov（ネットワーク。約3分）
  $PY -I -X utf8 scripts/IMPL_kyuyo_verify.py fetch_docs        # 国税庁・総務省・地方公共団体（ネットワーク）
  $PY -I -X utf8 scripts/IMPL_kyuyo_verify.py analyze <laws_dir> <docs_dir>   # ネットワーク不要
    <laws_dir>, <docs_dir> は fetch_* が作ったダウンロード先（.work/downloads/<ts>_kyuyo_verify_laws など）

- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。
- ダウンロードしたものは .work/downloads/<YYYYMMDD-HHMMSS>_kyuyo_verify_<group>/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/IMPL_kyuyo_verify/。
"""
import csv
import hashlib
import html.parser
import json
import math
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_kyuyo_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5

LAWS = [
    ("shotoku", "340AC0000000033", ["2024-12-31", "2025-11-30", "2025-12-01", "2025-12-31", "2026-11-09", "2026-11-30", "2026-12-01", "2027-01-01"]),
    ("sochi", "332AC0000000026", ["2026-11-09", "2026-11-30", "2026-12-01", "2027-01-01", "2028-01-01"]),
    ("sochi-rei", "332CO0000000043", ["2026-12-01"]),
    ("chiho", "325AC0000000226", ["2025-12-31", "2026-11-09", "2027-01-01", "2028-01-01"]),
    ("chiho-rei", "325CO0000000245", ["2027-01-01"]),
]
REVISIONS = [("shotoku", "340AC0000000033"), ("sochi", "332AC0000000026"), ("chiho", "325AC0000000226"),
             ("sochi-rei", "332CO0000000043"), ("chiho-rei", "325CO0000000245")]

DOCS = [
    ("nta_ta1410", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1410.htm"),
    ("nta_2026kaisei_pdf", "https://www.nta.go.jp/publication/pamph/gensen/2026kaisei.pdf"),
    ("nta_2026kiso_qa_pdf", "https://www.nta.go.jp/users/gensen/2026kiso/pdf/0026005-024.pdf"),
    ("nta_2025kiso_qa_pdf", "https://www.nta.go.jp/publication/pamph/gensen/0025005-051.pdf"),
    ("nta_nencho2025_114_pdf", "https://www.nta.go.jp/publication/pamph/gensen/nencho2025/pdf/114.pdf"),
    ("nta_nencho2026_114_pdf", "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/114.pdf"),
    ("soumu_r8_chihozei_an_pdf", "https://www.soumu.go.jp/main_content/001047636.pdf"),
    ("sendai_r8", "https://www.city.sendai.jp/shiminze-kikaku/kurashi/tetsuzuki/zekin/kojin/kaisei/r8.html"),
    ("osaka_pref_r8_zeikai", "https://www.pref.osaka.lg.jp/o050030/zei/alacarte/reiwa8_zeikai.html"),
    ("kumamoto_r9", "https://www.city.kumamoto.jp/kiji00373630/index.html"),
]


# ---------------------------------------------------------------- 取得
def get(url, accept=None):
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    req = urllib.request.Request(url, headers=h)
    hdr = {}
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
            hdr = {k: r.headers.get(k) for k in ("Content-Type", "Last-Modified", "Content-Length", "ETag")}
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    time.sleep(SLEEP)
    return st, body, hdr


def new_dl(group):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_kyuyo_verify_{group}"
    dl.mkdir(parents=True, exist_ok=False)
    return ts, dl


def fetch_laws():
    ts, dl = new_dl("laws")
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "revisions": []}
    for short, law_id, asofs in LAWS:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body, hdr = get(url, "application/json")
            fn = dl / f"{short}_{asof}.json"
            fn.write_bytes(body)
            rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "file": fn.name,
                   "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            if st == 200:
                ri = json.loads(body).get("revision_info") or {}
                rec.update({k: ri.get(k) for k in ("law_title", "law_revision_id", "amendment_law_num", "amendment_enforcement_date",
                                                   "amendment_scheduled_enforcement_date", "current_revision_status")})
            log["fetches"].append(rec)
            print(short, asof, st, rec.get("law_revision_id"), flush=True)
    for short, law_id in REVISIONS:
        url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json"})
        st, body, hdr = get(url, "application/json")
        fn = dl / f"revisions_{short}.json"
        fn.write_bytes(body)
        log["revisions"].append({"short": short, "law_id": law_id, "url": url, "status": st, "file": fn.name,
                                 "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})
        print("revisions", short, st, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fetch_laws_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)


def fetch_docs():
    ts, dl = new_dl("docs")
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "docs": []}
    for name, url in DOCS:
        st, body, hdr = get(url)
        ext = ".pdf" if url.endswith(".pdf") or (hdr.get("Content-Type") or "").startswith("application/pdf") else ".html"
        fn = dl / f"{name}{ext}"
        fn.write_bytes(body)
        log["docs"].append({"name": name, "url": url, "status": st, "headers": hdr, "file": fn.name,
                            "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})
        print(name, st, len(body), hdr.get("Last-Modified"), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fetch_docs_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] in ("fetch_laws", "fetch_docs"):
    {"fetch_laws": fetch_laws, "fetch_docs": fetch_docs}[sys.argv[1]]()
    sys.exit(0)


# ---------------------------------------------------------------- 条文の読み取り（自前の実装）
def txt(n):
    """要素の文字列を連結する（ルビ Rt は除く）。"""
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(txt(c) for c in n.get("children", []))


def norm(s):
    """比較用：空白（全角を含む）を除き、全角数字・記号を半角に。"""
    s = re.sub(r"[\s\u3000]", "", s)
    return s.translate(str.maketrans("０１２３４５６７８９，％．", "0123456789,%."))


def children(n, tag):
    return [c for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == tag]


def iter_nodes(n, path=()):
    if isinstance(n, dict):
        yield n, path
        for c in n.get("children", []):
            yield from iter_nodes(c, path + (n,))


def load_law(laws_dir, short, asof):
    d = json.loads((pathlib.Path(laws_dir) / f"{short}_{asof}.json").read_text(encoding="utf-8"))
    return d


def main_articles(root):
    """本則の Article（SupplProvision の外）を Num → node。"""
    out = {}
    for n, path in iter_nodes(root):
        if n.get("tag") == "Article" and not any(p.get("tag") == "SupplProvision" for p in path):
            out.setdefault((n.get("attr") or {}).get("Num"), n)
    return out


def suppl(root, amend_law_num):
    return [n for n, _ in iter_nodes(root) if n.get("tag") == "SupplProvision" and (n.get("attr") or {}).get("AmendLawNum") == amend_law_num]


def suppl_article(root, amend_law_num, num):
    for s in suppl(root, amend_law_num):
        for n, _ in iter_nodes(s):
            if n.get("tag") == "Article" and (n.get("attr") or {}).get("Num") == num:
                return n
    return None


def paragraph(article, num):
    for p in children(article, "Paragraph"):
        if (p.get("attr") or {}).get("Num") == str(num):
            return p
    return None


def item(par, num):
    for i in children(par, "Item"):
        if (i.get("attr") or {}).get("Num") == str(num):
            return i
    return None


def caption(article):
    c = children(article, "ArticleCaption")
    return txt(c[0]) if c else ""


def dump_articles(laws_dir):
    """読むための条文テキスト（自前の抽出）。"""
    OUT.mkdir(parents=True, exist_ok=True)
    want = {
        "shotoku": (["28", "190"], ["令和七年三月三一日法律第一三号", "令和八年三月三一日法律第一二号"]),
        "sochi": (["27", "29_4", "29_5"], ["令和八年三月三一日法律第一二号"]),
        "sochi-rei": (["19_4_2"], []),
        "chiho": (["292", "295", "313", "314_2"], ["令和七年三月三一日法律第七号", "令和八年三月三一日法律第二号"]),
    }
    for short, law_id, asofs in LAWS:
        if short not in want:
            continue
        arts, ams = want[short]
        for asof in asofs:
            root = load_law(laws_dir, short, asof)["law_full_text"]
            ma = main_articles(root)
            lines = [f"# {short} asof={asof}"]
            for a in arts:
                n = ma.get(a)
                lines.append(f"## 本則 Num={a} 見出し={caption(n) if n else None}")
                if n:
                    for p in children(n, "Paragraph"):
                        lines.append(f"[項{(p.get('attr') or {}).get('Num')}] " + txt(p))
            for am in ams:
                ss = suppl(root, am)
                lines.append(f"## 附則 {am}: {len(ss)} 件")
                for s in ss:
                    for n, _ in iter_nodes(s):
                        if n.get("tag") == "Article":
                            lines.append(f"### 附則 Num={(n.get('attr') or {}).get('Num')} 見出し={caption(n)}")
                            for p in children(n, "Paragraph"):
                                lines.append(f"[項{(p.get('attr') or {}).get('Num')}] " + txt(p))
                    if not any(n.get("tag") == "Article" for n, _ in iter_nodes(s)):
                        lines.append("(Article なし) " + txt(s)[:3000])
            (OUT / f"dump_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            print("dump", short, asof)


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "dump":
    dump_articles(sys.argv[2])
    sys.exit(0)


# ---------------------------------------------------------------- 別表第五（自前の読み取り）
Z2H = str.maketrans("０１２３４５６７８９，％", "0123456789,%")


def yen(s):
    s = s.translate(Z2H).replace(",", "").replace("円", "").strip()
    return int(s) if re.fullmatch(r"\d+", s) else None


def beppyo5_node(root):
    for n, _ in iter_nodes(root):
        if n.get("tag") == "AppdxTable":
            t = children(n, "AppdxTableTitle")
            if t and txt(t[0]).strip() == "別表第五":
                return n
    return None


HEADER_CELLS = {"給与等の金額", "以上", "未満", "円", "給与所得控除後の給与等の金額"}


def beppyo5_parse(root):
    """別表第五を (lower, upper, kind, a, b) の list にする。
    kind: fixed(a=値) / minus(a=控除する円) / rate(a=百分率, b=控除する円) / point(a=給与等の金額, b=値)。
    実装：TableStruct ごとに占有格子を作り（rowspan/colspan）、各セルを「起点の行・列」に置く。
    列 0-2, 3-5, 6-8 を「以上・未満・値」の3組として読む。"""
    node = beppyo5_node(root)
    structs = children(node, "TableStruct")
    bands = []
    remarks = []
    for si, st in enumerate(structs):
        for rm in children(st, "Remarks"):
            remarks.append(txt(rm))
        tab = children(st, "Table")[0]
        rows = [r for r in tab.get("children", []) if isinstance(r, dict) and r.get("tag") in ("TableRow", "TableHeaderRow")]
        occ = {}      # (r, c) -> True（占有）
        origin = {}   # (r, c) -> (text, rowspan, colspan)  起点のセルだけ
        for r, row in enumerate(rows):
            c = 0
            for cell in [x for x in row.get("children", []) if isinstance(x, dict)]:
                while occ.get((r, c)):
                    c += 1
                a = cell.get("attr") or {}
                rs, cs = int(a.get("rowspan", 1)), int(a.get("colspan", 1))
                origin[(r, c)] = (txt(cell).strip(), rs, cs)
                for dr in range(rs):
                    for dc in range(cs):
                        occ[(r + dr, c + dc)] = True
                c += cs
        width = max(c for (_, c) in occ) + 1
        if width != 9:
            raise ValueError(f"struct {si}: width {width}")
        for g in range(3):
            c0 = 3 * g
            for r in range(len(rows)):
                cell = origin.get((r, c0))
                if not cell or not cell[0]:
                    continue
                t0 = cell[0].translate(Z2H)
                if cell[2] == 2:   # 「◯円未満」または「20,000,000円」
                    v = origin.get((r, c0 + 2))
                    m = re.fullmatch(r"([\d,]+)円未満", t0)
                    if m:
                        bands.append((0, int(m.group(1).replace(",", "")), "fixed", yen(v[0]), None))
                        continue
                    if yen(t0) is not None:
                        bands.append((yen(t0), yen(t0) + 1, "point", yen(t0), yen(v[0])))
                        continue
                    if cell[0] not in HEADER_CELLS:
                        raise ValueError(("colspan2", t0))
                    continue   # 見出し（給与等の金額）
                lo = yen(cell[0])
                if lo is None:
                    if cell[0] not in HEADER_CELLS:
                        raise ValueError(("unexpected cell", cell[0]))
                    continue   # 見出し（以上・未満・円）
                up = yen(origin[(r, c0 + 1)][0])
                vt = origin[(r, c0 + 2)][0]
                if yen(vt) is not None:
                    bands.append((lo, up, "fixed", yen(vt), None))
                    continue
                t = vt.translate(Z2H).replace(",", "")
                m1 = re.fullmatch(r"給与等の金額から(\d+)円を控除した金額", t)
                m2 = re.fullmatch(r"給与等の金額に(\d+)%を乗じて算出した金額から(\d+)円を控除した金額", t)
                if m1:
                    bands.append((lo, up, "minus", int(m1.group(1)), None))
                elif m2:
                    bands.append((lo, up, "rate", int(m2.group(1)), int(m2.group(2))))
                else:
                    raise ValueError(("unknown value", vt))
    bands.sort()
    rel = children(node, "RelatedArticleNum")
    return {"bands": bands, "n_structs": len(structs), "remarks": remarks + [txt(x) for x in children(node, "Remarks")],
            "related": txt(rel[0]).strip() if rel else None}


class B5:
    def __init__(self, bands):
        self.b = [x for x in bands if x[2] != "point"]
        self.points = {x[0]: x[4] for x in bands if x[2] == "point"}
        self.lows = [x[0] for x in self.b]

    def __call__(self, x):
        import bisect
        if x in self.points:
            return self.points[x]
        i = bisect.bisect_right(self.lows, x) - 1
        lo, up, k, a, b = self.b[i]
        if not (lo <= x < up):
            raise ValueError(("no band", x))
        if k == "fixed":
            return a
        if k == "minus":
            return x - a
        return (x * a) // 100 - b   # 1円未満切捨て（備考）


# ---------------------------------------------------------------- 第28条第3項（条文を読んで書いたもの。Fraction で正確に）
def koujo(year, x):
    x = Fraction(x)
    M = 10_000
    if year <= 2024:      # asof 2024-12-31 の第3項
        if x <= 180 * M:
            return max(x * Fraction(40, 100) - 10 * M, Fraction(55 * M))
        if x <= 360 * M:
            return 62 * M + (x - 180 * M) * Fraction(30, 100)
    elif year == 2025:    # asof 2025-12-31 の第3項
        if x <= 190 * M:
            return Fraction(65 * M)
        if x <= 360 * M:
            return 65 * M + (x - 190 * M) * Fraction(30, 100)
    else:                 # asof 2026-12-01 の第3項（第1号：8万円＋30%、69万円に満たないときは69万円）
        if x <= 360 * M:
            return max(8 * M + x * Fraction(30, 100), Fraction(69 * M))
    if x <= 660 * M:
        return 116 * M + (x - 360 * M) * Fraction(20, 100)
    if x <= 850 * M:
        return 176 * M + (x - 660 * M) * Fraction(10, 100)
    return Fraction(195 * M)


def sochi2(x):
    """措置法第29条の4第2項（asof 2026-12-01 の本文を読んで書いたもの）。範囲外は None。"""
    if 691_000 <= x < 741_000:
        return 0
    if 741_000 <= x < 2_191_000:
        return x - 740_000
    if 2_191_000 <= x < 2_193_000:
        return 1_451_000
    if 2_193_000 <= x < 2_196_000:
        return 1_453_000
    if 2_196_000 <= x < 2_200_000:
        return 1_456_000
    return None


# ---------------------------------------------------------------- 条文の主張の照合
R7S = "令和七年三月三一日法律第一三号"
R8S = "令和八年三月三一日法律第一二号"
R7C = "令和七年三月三一日法律第七号"
R8C = "令和八年三月三一日法律第二号"

# (ID, 文書の箇所, 略称, [asof], 位置, [断片（文書が引いた文言。… で区切った部分ごとに照合）], 期待＝含む(True)/含まない(False))
# 位置: ("main", 条, 項|None, 号|None) / ("suppl", 改正法令番号, 条, 項|None, 号|None) / ("caption_main", 条) / ("caption_suppl", 改正法令番号, 条)
LAW_CLAIMS = [
    ("PS1.1", "PS §1.1", "shotoku", ["2024-12-31", "2025-12-31", "2026-12-01"], ("main", "28", 4, None),
     ["その年中の給与等の収入金額が六百六十万円未満である場合には、当該給与等に係る給与所得の金額は、前二項の規定にかかわらず、当該収入金額を別表第五の給与等の金額として、同表により当該金額に応じて求めた同表の給与所得控除後の給与等の金額に相当する金額とする。"], True),
    ("PS1.1-hasu2", "PS §1.1 第2項に端数の語がない", "shotoku", ["2024-12-31", "2025-12-31", "2026-12-01"], ("main", "28", 2, None), ["端数"], False),
    ("PS1.1-hasu3", "PS §1.1 第3項に端数の語がない", "shotoku", ["2024-12-31", "2025-12-31", "2026-12-01"], ("main", "28", 3, None), ["端数"], False),
    ("PS1.3", "PS §1.3 第190条第2号", "shotoku", ["2026-12-01"], ("main", "190", 1, 2),
     ["別表第五により、その年中にその居住者に対し支払うべきことが確定した給与等の金額に応じて求めた同表の給与所得控除後の給与等の金額から次に掲げる金額の合計額を控除した金額（当該金額に千円未満の端数があるとき、又は当該金額の全額が千円未満であるときは、その端数金額又はその全額を切り捨てた金額）を課税総所得金額とみなして"], True),
    ("PS1.4-a", "PS §1.4 R7法13 附則1条1号イ", "shotoku", ["2027-01-01"], ("suppl", R7S, "1", 1, 1),
     ["令和七年十二月一日", "同法別表第二から別表第五までの改正規定（別表第五に係る部分に限る。）"], True),
    ("PS1.4-b", "PS §1.4 R7法13 附則3条1項", "shotoku", ["2027-01-01"], ("suppl", R7S, "3", 1, None),
     ["新所得税法第二十八条の規定は、令和七年分以後の所得税について適用し、令和六年分以前の所得税については、なお従前の例による。"], True),
    ("PS1.4-b2", "PS §1.4 R7法13 附則3条 見出し", "shotoku", ["2027-01-01"], ("caption_suppl", R7S, "3"), ["給与所得に関する経過措置"], True),
    ("PS1.4-c", "PS §1.4 R7法13 附則9条2項", "shotoku", ["2027-01-01"], ("suppl", R7S, "9", 2, None),
     ["新所得税法第百九十条（第二号ホに係る部分に限る。）及び別表第五の規定は、令和七年中に支払うべき給与等でその最後に支払をする日が同年十二月一日以後であるものについて適用し、同年中に支払うべき給与等でその最後に支払をする日が同年十二月一日前であるものについては、なお従前の例による。"], True),
    ("PS1.4-c2", "PS §1.4 R7法13 附則9条 見出し", "shotoku", ["2027-01-01"], ("caption_suppl", R7S, "9"), ["給与所得に係る源泉徴収に関する経過措置"], True),
    ("PS1.4-d", "PS §1.4 R8法12 附則1条4号イ", "shotoku", ["2027-01-01"], ("suppl", R8S, "1", 1, 4),
     ["令和八年十二月一日", "同法別表第二から別表第五までの改正規定（別表第五に係る部分に限る。）"], True),
    ("PS1.4-e", "PS §1.4 R8法12 附則3条1項", "shotoku", ["2027-01-01"], ("suppl", R8S, "3", 1, None),
     ["新所得税法第二十八条の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。"], True),
    ("PS1.4-e2", "PS §1.4 R8法12 附則3条 見出し", "shotoku", ["2027-01-01"], ("caption_suppl", R8S, "3"), ["給与所得に関する経過措置"], True),
    ("PS1.4-f", "PS §1.4 R8法12 附則13条2項", "shotoku", ["2027-01-01"], ("suppl", R8S, "13", 2, None),
     ["新所得税法別表第五の規定は、令和八年分の所得税については、同年中に支払うべき給与等でその最後に支払をする日が同年十二月一日以後であるものについて適用し、同年中に支払うべき給与等でその最後に支払をする日が同年十二月一日前であるものについては、なお従前の例による。"], True),
    ("PS1.4-f2", "PS §1.4 R8法12 附則13条 見出し", "shotoku", ["2027-01-01"], ("caption_suppl", R8S, "13"), ["給与所得に係る源泉徴収に関する経過措置"], True),
    ("IT-101", "I5（[IT] §2 経由）R8法12 附則101条", "shotoku", ["2027-01-01"], ("suppl", R8S, "101", 1, None),
     ["令和十年分以後の所得税の基礎控除の額については", "二年ごとに", "全国消費者物価指数の変化率", "給与所得控除の最低保障額についても、同様とする。"], True),
    ("PS2.1-1", "PS §2.1 措法29条の4第1項", "sochi", ["2026-12-01", "2027-01-01", "2028-01-01"], ("main", "29_4", 1, None),
     ["令和八年又は令和九年において、その年中の所得税法第二十八条第一項に規定する給与等（", "）の収入金額が二百二十万円以下である場合には、当該給与等に係る同条第三項に規定する給与所得控除額は、同項第一号の規定にかかわらず、七十四万円（当該収入金額が七十四万円に満たない場合には、当該収入金額に相当する金額）とする。"], True),
    ("PS2.1-2", "PS §2.1 措法29条の4第2項柱書", "sochi", ["2026-12-01", "2027-01-01", "2028-01-01"], ("main", "29_4", 2, None),
     ["令和八年又は令和九年において、その年中の給与等の収入金額が六十九万千円以上二百二十万円未満である場合には、当該給与等に係る給与所得の金額については、前項及び所得税法第二十八条第二項から第四項までの規定にかかわらず、次に定めるところによる。"], True),
    ("PS2.1-2-1", "PS §2.1 同第1号", "sochi", ["2026-12-01", "2027-01-01", "2028-01-01"], ("main", "29_4", 2, 1), ["六十九万千円以上七十四万千円未満である場合には", "給与所得の金額は、ないものとする。"], True),
    ("PS2.1-2-2", "PS §2.1 同第2号", "sochi", ["2026-12-01", "2027-01-01", "2028-01-01"], ("main", "29_4", 2, 2), ["七十四万千円以上二百十九万千円未満である場合には", "当該収入金額から七十四万円を控除した残額とする。"], True),
    ("PS2.1-2-3", "PS §2.1 同第3号", "sochi", ["2026-12-01", "2027-01-01", "2028-01-01"], ("main", "29_4", 2, 3), ["二百十九万千円以上二百十九万三千円未満である場合には", "百四十五万千円とする。"], True),
    ("PS2.1-2-4", "PS §2.1 同第4号", "sochi", ["2026-12-01", "2027-01-01", "2028-01-01"], ("main", "29_4", 2, 4), ["二百十九万三千円以上二百十九万六千円未満である場合には", "百四十五万三千円とする。"], True),
    ("PS2.1-2-5", "PS §2.1 同第5号", "sochi", ["2026-12-01", "2027-01-01", "2028-01-01"], ("main", "29_4", 2, 5), ["二百十九万六千円以上二百二十万円未満である場合には", "百四十五万六千円とする。"], True),
    ("PS2.1-3", "PS §2.1 同第3項（特定支出控除の読替え）", "sochi", ["2026-12-01"], ("main", "29_4", 3, None), ["前項の規定の適用がある場合における所得税法第五十七条の二第一項の規定の適用については"], True),
    ("PS2.1-4", "PS §2.1 同第4項", "sochi", ["2026-12-01", "2027-01-01", "2028-01-01"], ("main", "29_4", 4, None),
     ["令和八年又は令和九年において、所得税法第百九十条に規定する居住者に対しその年中に支払うべきことが確定した給与等", "の金額が六十九万千円以上二百二十万円未満である場合には、当該給与等に係る同条第二号に規定する給与所得控除後の給与等の金額は、同号の規定（同法別表第五を含む。）にかかわらず、", "第二項の給与等の収入金額とみなして同項の規定を適用した場合の同項に規定する給与所得の金額に相当する金額とする。"], True),
    ("PS2.1-5", "PS §2.1 同第5項", "sochi", ["2026-12-01"], ("main", "29_4", 5, None), ["前二項に定めるもののほか、第一項又は第二項の規定の適用に関し必要な事項は、政令で定める。"], True),
    ("PS2.1-cap", "PS §2.1 見出し", "sochi", ["2026-12-01", "2027-01-01", "2028-01-01"], ("caption_main", "29_4"), ["給与所得控除の最低控除額等の特例"], True),
    ("PS2.1-old", "PS §2.1 asof 2026-11-09 の第29条の4 は未払賃金の特例", "sochi", ["2026-11-09"], ("caption_main", "29_4"), ["退職勤労者が弁済を受ける未払賃金に係る課税の特例"], True),
    ("PS2.1-old2", "PS §2.1 2026-12-01 版で第29条の5", "sochi", ["2026-12-01"], ("caption_main", "29_5"), ["退職勤労者が弁済を受ける未払賃金に係る課税の特例"], True),
    ("PS2.2-a", "PS §2.2 R8法12 附則1条4号ロ（措法）", "sochi", ["2026-12-01"], ("suppl", R8S, "1", 1, 4),
     ["令和八年十二月一日", "同法第二章第三節中第二十九条の四を第二十九条の五とし、第二十九条の三の次に一条を加える改正規定"], True),
    ("PS2.2-b", "PS §2.2 附則36条1項", "sochi", ["2026-12-01"], ("suppl", R8S, "36", 1, None),
     ["新租税特別措置法第二十九条の四第四項の規定は、令和八年分の所得税については、同年中に支払うべき所得税法第百九十条第一号に規定する給与等でその最後に支払をする日が同年十二月一日以後であるものについて適用する。"], True),
    ("PS2.2-b2", "PS §2.2 附則36条 見出し", "sochi", ["2026-12-01"], ("caption_suppl", R8S, "36"), ["給与所得控除の最低控除額等の特例に関する経過措置"], True),
    ("PS2.2-c", "PS §2.2 附則36条2項", "sochi", ["2026-12-01"], ("suppl", R8S, "36", 2, None),
     ["令和八年十二月一日前に同年分の所得税につき", "確定申告書を提出した者及び", "決定を受けた者は", "新租税特別措置法第二十九条の四の規定の適用により異動を生ずることとなったときは", "同日から五年以内に", "更正の請求をすることができる。"], True),
    ("PS2.3-1", "PS §2.3 措令19条の4の2第1項", "sochi-rei", ["2026-12-01"], ("main", "19_4_2", 1, None),
     ["法第二十九条の四第二項の規定の適用がある場合における法第四十一条の三の十一第二項の規定の適用については、同条第四項第五号中「", "」とあるのは、「第二十九条の四第二項の規定の適用がある場合には、同項の規定を適用した場合の同項に規定する給与所得の金額に相当する金額」とする。"], True),
    ("PS2.3-2", "PS §2.3 措令19条の4の2第2項", "sochi-rei", ["2026-12-01"], ("main", "19_4_2", 2, None),
     ["前項に定めるもののほか、法第二十九条の四第一項又は第二項の規定の適用に関し必要な事項は、財務省令で定める。"], True),
    ("PS2.3-cap", "PS §2.3 見出し", "sochi-rei", ["2026-12-01"], ("caption_main", "19_4_2"), ["給与所得控除の最低控除額等の特例"], True),
    ("PS2.3-41311", "PS §2.3 法第41条の3の11 は所得金額調整控除", "sochi", ["2026-12-01"], ("caption_main", "41_3_11"), ["所得金額調整控除"], True),
    ("PS2.4-a", "PS §2.4 措法27条（現行）65万円", "sochi", ["2026-11-09"], ("main", "27", 1, None),
     ["六十五万円（当該個人が給与所得を有する場合にあつては、六十五万円から所得税法第二十八条第二項に規定する給与所得控除額を控除した残額"], True),
    ("PS2.4-b", "PS §2.4 措法27条（R8）69万円", "sochi", ["2026-12-01"], ("main", "27", 1, None),
     ["六十九万円（当該個人が給与所得を有する場合にあつては、六十九万円から所得税法第二十八条第二項に規定する給与所得控除額を控除した残額"], True),
    ("PS2.4-c", "PS §2.4 附則34条1項", "sochi", ["2026-12-01"], ("suppl", R8S, "34", 1, None),
     ["新租税特別措置法第二十七条の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。"], True),
    ("PS3.1-1", "PS §3.1 地法313条1項", "chiho", ["2025-12-31", "2026-11-09", "2027-01-01", "2028-01-01"], ("main", "313", 1, None),
     ["所得割の課税標準は、前年の所得について算定した総所得金額、退職所得金額及び山林所得金額とする。"], True),
    ("PS3.1-2", "PS §3.1 地法313条2項", "chiho", ["2025-12-31", "2026-11-09", "2027-01-01", "2028-01-01"], ("main", "313", 2, None),
     ["前項の総所得金額、退職所得金額又は山林所得金額は、この法律又はこれに基づく政令で特別の定めをする場合を除くほか、それぞれ所得税法その他の所得税に関する法令の規定による所得税法第二十二条第二項又は第三項の総所得金額、退職所得金額又は山林所得金額の計算の例により算定するものとする。ただし、同法第六十条の二から第六十条の四までの規定の例によらないものとする。"], True),
    ("PS3.1-11", "PS §3.1 地法313条11項", "chiho", ["2027-01-01"], ("main", "313", 11, None), ["同法第二十八条第二項に規定する給与所得控除額の二分の一"], True),
    ("PS3.3-292a", "PS §3.3 地法292条1項9号（2025-12-31）", "chiho", ["2025-12-31"], ("main", "292", 1, 9), ["前年の合計所得金額が四十八万円以下"], True),
    ("PS3.3-292b", "PS §3.3 地法292条1項9号（2026-11-09）", "chiho", ["2026-11-09"], ("main", "292", 1, 9), ["前年の合計所得金額が五十八万円以下"], True),
    ("PS3.3-292c", "PS §3.3 地法292条1項9号（2027-01-01）", "chiho", ["2027-01-01"], ("main", "292", 1, 9), ["前年の合計所得金額が六十二万円以下"], True),
    ("PS3.3-r7c", "PS §3.3 R7法7 附則8条1項", "chiho", ["2027-01-01"], ("suppl", R7C, "8", 1, None),
     ["新法第二百九十二条第一項（第七号及び第九号に係る部分に限る。）、第三項及び第四項、第三百十四条の二並びに第三百十七条の二第一項", "の規定は、令和八年度以後の年度分の個人の市町村民税について適用し、令和七年度分までの", "なお従前の例による。"], True),
    ("PS3.3-r8c1", "PS §3.3 R8法2 附則11条1項", "chiho", ["2027-01-01"], ("suppl", R8C, "11", 1, None),
     ["別段の定めがあるものを除き、新法の規定中個人の市町村民税に関する部分（", "）は、令和八年度以後の年度分の個人の市町村民税について適用し"], True),
    ("PS3.3-r8c2", "PS §3.3 R8法2 附則11条2項", "chiho", ["2027-01-01"], ("suppl", R8C, "11", 2, None),
     ["新法第二百九十二条第一項（第七号及び第九号に係る部分に限る。）の規定は、令和九年度以後の年度分の個人の市町村民税について適用し、令和八年度分までの", "なお従前の例による。"], True),
    ("PS3.3-314", "PS §3.3 地法314条の2第1項第12号", "chiho", ["2027-01-01"], ("main", "314_2", 1, 12),
     ["年齢十九歳以上二十三歳未満の親族", "前年の合計所得金額が百二十三万円以下であるものに限る。）で控除対象扶養親族に該当しないもの",
      "イ前年の合計所得金額が九十五万円以下である特定親族四十五万円", "ロ前年の合計所得金額が九十五万円を超え百十五万円以下である特定親族六十三万円から当該特定親族の前年の合計所得金額のうち八十四万一円を超える部分の金額に二を乗じた金額",
      "十万円の整数倍の金額から八万円を控除した金額", "ハ前年の合計所得金額が百十五万円を超え百二十万円以下である特定親族六万円", "ニ前年の合計所得金額が百二十万円を超える特定親族三万円"], True),
    ("PS3.3-314-9", "PS §3.3 地法314条の2第9項", "chiho", ["2027-01-01"], ("main", "314_2", 9, None),
     ["所得税法第二条第一項第三十二号の規定は、第一項第九号及び第三百十四条の六の勤労学生の意義について準用する。この場合において、同法第二条第一項第三十二号中「合計所得金額が」とあるのは「当該年度の初日の属する年の前年"], True),
    ("PS3.3-295", "PS §3.3 地法295条1項2号", "chiho", ["2026-11-09", "2027-01-01"], ("main", "295", 1, 2),
     ["障害者、未成年者、寡婦又はひとり親（これらの者の前年の合計所得金額が百三十五万円を超える場合を除く。）"], True),
]


def locate_text(root, loc):
    kind = loc[0]
    if kind in ("main", "suppl"):
        if kind == "main":
            n = main_articles(root).get(loc[1])
            rest = loc[2:]
        else:
            n = suppl_article(root, loc[1], loc[2])
            rest = loc[3:]
        if n is None:
            return None
        if rest[0] is not None:
            n = paragraph(n, rest[0])
            if n is None:
                return None
        if rest[1] is not None:
            n = item(n, rest[1])
            if n is None:
                return None
        return txt(n)
    if kind == "caption_main":
        a = main_articles(root).get(loc[1])
        return caption(a) if a is not None else None
    if kind == "caption_suppl":
        a = suppl_article(root, loc[1], loc[2])
        return caption(a) if a is not None else None
    raise ValueError(loc)


# ---------------------------------------------------------------- HTML のテキスト化（自前）
class _Text(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, t, a):
        if t in ("script", "style", "noscript"):
            self.skip += 1
        if t in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table", "dt", "dd", "caption"):
            self.out.append("\n")
        if t in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, t):
        if t in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def html_text(path):
    b = pathlib.Path(path).read_bytes()
    t = None
    for enc in ("utf-8", "cp932", "euc_jp"):
        try:
            t = b.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    p = _Text()
    p.feed(t)
    return "\n".join(ln.strip() for ln in "".join(p.out).splitlines() if ln.strip() and ln.strip() != "|")


# 文書（PS §4.1・§5.2）が引いた文言（HTML）。norm() して部分一致を見る。"A|B" は隣り合う2つのセル
HTML_CLAIMS = [
    ("nta_ta1410", "PS §4.1 版", ["[令和8年4月1日現在法令等]"]),
    ("nta_ta1410", "PS §4.1 令和8・9年分の表", ["2,200,000円まで", "740,000円", "2,200,001円から3,600,000円まで", "収入金額×30％+80,000円"]),
    ("nta_ta1410", "PS §4.1 （注1）", ["令和8年12月1日に施行され、令和8年分及び令和9年分に適用される金額です。"]),
    ("nta_ta1410", "PS §4.1 （注2）", ["給与等の収入金額が69万円1,000円以上220万円未満である場合、その給与等に係る給与所得の金額については、上記の表にかかわらず、次の金額とすることとされています。"]),
    ("nta_ta1410", "PS §4.1 （注2）の表", ["69万1,000円以上74万1,000円未満", "74万1,000円以上219万1,000円未満", "219万1,000円以上219万3,000円未満", "219万3,000円以上219万6,000円未満", "219万6,000円以上220万円未満", "なし", "その収入金額－74万円", "145万1,000円", "145万3,000円", "145万6,000円"]),
    ("nta_ta1410", "PS §4.1 （注3）", ["給与等の収入金額が660万円未満の場合には、上記の表にかかわらず、所得税法別表第五", "により給与所得の金額を求めます（給与等の収入金額が220万円未満である場合の給与所得の金額は、上記（注2）の表の金額となります。）。"]),
    ("nta_ta1410", "PS §4.1 （注4）", ["同一年分の給与所得の源泉徴収票が2枚以上ある場合には、それらの支払金額の合計額により上記の表を適用してください。"]),
    ("nta_ta1410", "PS §4.1 令和7年分の表", ["令和7年分", "1,900,000円まで", "650,000円", "1,900,001円から", "給与等の収入金額が660万円未満の場合には、上記の表にかかわらず、令和７年分の所得税に適用される所得税法別表第五"]),
    ("nta_ta1410", "PS §4.1 660万円以上の速算表", ["令和2年分以降", "6,600,000円以上", "8,500,000円未満", "収入金額×90％-1,100,000円", "8,500,000円以上", "収入金額-1,950,000円"]),
    ("sendai_r8", "PS §5.2 仙台市 74万円", ["令和9年度及び令和10年度はさらに5万円加算され、74万円となります"]),
    ("sendai_r8", "PS §5.2 仙台市 R9・R10 速算表", ["給与所得の速算表（令和9年度及び令和10年度）", "740,999円まで", "0円", "741,000円から2,190,999円まで", "収入金額-740,000円", "2,191,000円から2,192,999円まで", "1,451,000円", "2,193,000円から2,195,999円まで", "1,453,000円", "2,196,000円から2,199,999円まで", "1,456,000円", "※給与所得控除の最低控除額等の特例（租税特別措置法第29条の4）適用後の給与所得控除額となります。"]),
    ("sendai_r8", "PS §5.2 仙台市 R8 速算表", ["給与所得の速算表（令和8年度）", "A＝収入金額÷4（千円未満の端数切捨て）", "650,999円まで", "651,000円から1,899,999円まで", "収入金額-650,000円", "1,900,000円から3,599,999円まで", "A×2.8-80,000円"]),
    ("sendai_r8", "PS §5.2 仙台市 所得要件", ["58万円以下（123万円以下）", "62万円以下（136万円以下）", "85万円以下（150万円以下）", "89万円以下（163万円以下）", "※改正前は令和8年度の場合、改正後は令和9年度及び令和10年度の場合となります。"]),
    ("sendai_r8", "PS §5.2 仙台市 非課税早見表", ["45万円以下（1,100,000円）", "45万円以下（1,190,000円）", "101万円以下（1,660,000円）", "101万円以下（1,750,000円）", "136万円以下（2,059,000円）|136万円以下（2,059,000円）", "171万円以下（2,559,999円）", "206万円以下（3,059,999円）", "241万円以下（3,559,999円）"]),
    ("sendai_r8", "PS §5.2 仙台市 非課税の基準", ["35万円×人数（本人＋同一生計配偶者＋扶養親族数）＋21万円+10万円", "「45万円（給与収入のみの場合、年収119万円）」以下の方"]),
    ("osaka_pref_r8_zeikai", "PS §5.2 大阪府", ["給与所得控除の最低保障額を74万円（現行:65万円）に引き上げます。（令和9年度分の個人住民税から適用します。なお、引上げ額9万円のうち、5万円は令和9年度分及び令和10年度分の2年間の時限措置とします。）"]),
    ("kumamoto_r9", "PS §5.2 熊本市", ["改正は令和9年度個人住民税（令和8年1月1日から12月31日までの収入を基礎とする個人住民税）から適用", "令和9年度分及び令和10年度分の市民税・県民税については、給与所得控除額の最低保障額をさらに5万円引き上げることとされました。", "よって、令和8年中及び令和9年中の給与収入が220万円以下の方については、給与所得控除の最低保障額が74万円となります。"]),
]

# 文書（PS §4・§5）が記録した取得の記録（Last-Modified の日付、SHA-256 またはその先頭）
DOC_META_CLAIMS = {
    "nta_ta1410": ("2026-10-16", "df763b0259059e8810ffe27385cf2a326b0bee008b7a62f2a67b66b9500d9a41"),
    "nta_2026kiso_qa_pdf": ("2026-05-29", "a3c12744dbed64e7a03383868baa055f51eb1d0434ee3267d6374d2fe959cea8"),
    "nta_2025kiso_qa_pdf": ("2025-05-30", "af377dfb7700cb28a8c328bdb83916b148e9ff24bf2064e2be35c76bb793805b"),
    "nta_2026kaisei_pdf": ("2026-04-20", "8db585cd5feef2eb29109a16a2e7b16054a0fa4d6423ac622d9ea12c54b39945"),
    "nta_nencho2025_114_pdf": ("2025-08-29", "cc316009c20bad7709444d8fc3328ce35abacf3803dc6ecaddc40a352398eb89"),
    "nta_nencho2026_114_pdf": ("2026-08-31", "3d06c41b675161d51cc59c89d6d129ce8ea204b5ccc986f5b30b1072a12a032c"),
    "soumu_r8_chihozei_an_pdf": ("2025-12-23", "0b2fa54af7eeb7aac1350c22996ed69a5ecaec7ec15b85470e65c774da67671e"),
    "sendai_r8": ("2026-10-29", "7eaa2cb559d8cbc2"),
    "osaka_pref_r8_zeikai": ("2026-04-13", "60aa1c42806889a2"),
    "kumamoto_r9": ("2026-11-06", "dd5769318abd20e3"),
}

# 文書（PS §0）が記録した版： (略称, asof, law_revision_id, 状態, 生データ SHA-256 の先頭16桁)
LAW_META_CLAIMS = [
    ("shotoku", "2024-12-31", "340AC0000000033_20240612_506AC0000000047", "PreviousEnforced", "9af089a685c8f0ca"),
    ("shotoku", "2025-11-30", "340AC0000000033_20251001_506AC0000000026", "PreviousEnforced", "7d442ce5a9252084"),
    ("shotoku", "2025-12-31", "340AC0000000033_20251218_507AC0000000013", "PreviousEnforced", "84a2235cb4437184"),
    ("shotoku", "2026-11-09", "340AC0000000033_20261001_507AC0000000070", "CurrentEnforced", "94c4a7ad83726cde"),
    ("shotoku", "2026-11-30", "340AC0000000033_20261001_507AC0000000070", "CurrentEnforced", "94c4a7ad83726cde"),
    ("shotoku", "2026-12-01", "340AC0000000033_20261201_508AC0000000012", "UnEnforced", "47792299f0fb5a74"),
    ("shotoku", "2027-01-01", "340AC0000000033_20270101_508AC0000000012", "UnEnforced", "d4bf435220bc0b0c"),
    ("sochi", "2026-11-09", "332AC0000000026_20261101_507AC0000000013", "CurrentEnforced", "e6e6013bbc0608c6"),
    ("sochi", "2026-12-01", "332AC0000000026_20261201_508AC0000000012", "UnEnforced", "1a11304351168b77"),
    ("sochi", "2027-01-01", "332AC0000000026_20270101_508AC0000000012", "UnEnforced", "8c6ee577201c3be0"),
    ("sochi", "2028-01-01", "332AC0000000026_20280101_508AC0000000012", "UnEnforced", "678b8017bbae338b"),
    ("sochi-rei", "2026-12-01", "332CO0000000043_20261201_508CO0000000098", "UnEnforced", "cc9aa8b1a0a429fb"),
    ("chiho", "2025-12-31", "325AC0000000226_20251212_507AC0000000087", "PreviousEnforced", "0deae64106b42fdb"),
    ("chiho", "2026-11-09", "325AC0000000226_20261101_508AC0000000002", "CurrentEnforced", "3dd29e0078bf24e0"),
    ("chiho", "2027-01-01", "325AC0000000226_20270101_508AC0000000002", "UnEnforced", "ee21722ce5fd1561"),
    ("chiho", "2028-01-01", "325AC0000000226_20280101_508AC0000000002", "UnEnforced", "ba69aa86514c9750"),
    ("chiho-rei", "2027-01-01", "325CO0000000245_20270101_508CO0000000083", "UnEnforced", "962bfc48e43c49b4"),
]

# 文書（M1 §6）が記録した、地方税法（4版）・同施行令（1版）の「文」単位の出現数
KW_CLAIMS = {
    "七十四万円": {"chiho": [0, 0, 0, 0], "chiho-rei": [0]},
    "六十九万": {"chiho": [0, 0, 0, 0], "chiho-rei": [0]},
    "六十九万千円": {"chiho": [0, 0, 0, 0], "chiho-rei": [0]},
    "二十九条の四": {"chiho": [7, 7, 5, 5], "chiho-rei": [1]},
    "租税特別措置法第二十九条": {"chiho": [2, 2, 2, 2], "chiho-rei": [5]},
    "給与所得控除": {"chiho": [2, 2, 2, 2], "chiho-rei": [1]},
    "別表第五": {"chiho": [2, 2, 2, 2], "chiho-rei": [0]},
}
CHIHO_ASOFS = ["2025-12-31", "2026-11-09", "2027-01-01", "2028-01-01"]


def keyword_sentences(root, kw):
    hits = []
    for n, path in iter_nodes(root):
        if n.get("tag") == "Sentence":
            t = txt(n)
            if kw in t:
                art, sp = None, None
                for p in path:
                    if p.get("tag") == "SupplProvision":
                        sp = (p.get("attr") or {}).get("AmendLawNum", "(原始附則)")
                    if p.get("tag") == "Article":
                        art = (p.get("attr") or {}).get("Num")
                i = t.find(kw)
                hits.append({"suppl": sp, "article": art, "snippet": t[max(0, i - 60): i + 80]})
    return hits


# ---------------------------------------------------------------- 給与所得（自前）と境目
TABLE_FOR_YEAR = {2024: "2024-12-31", 2025: "2025-12-31", 2026: "2026-12-01", 2027: "2026-12-01", 2028: "2026-12-01"}
OLD_TABLE_FOR_YEAR = {2025: "2024-12-31", 2026: "2025-12-31"}


def make_kyuyo(tables):
    def kyuyo(year, x, old=False):
        if x >= 6_600_000:
            return math.floor(Fraction(x) - koujo(year, x))   # 第28条第2項・第3項（1円未満切捨て＝H6）
        if year in (2026, 2027) and not old:
            v = sochi2(x)
            if v is not None:
                return v
        return tables[OLD_TABLE_FOR_YEAR[year] if old else TABLE_FOR_YEAR[year]](x)
    return kyuyo


def formula_only(year, x):
    if year in (2026, 2027) and x <= 2_200_000:
        d = Fraction(min(740_000, x))
    else:
        d = koujo(year, x)
    return max(0, math.floor(Fraction(x) - d))


def max_x(fn, limit, hi=40_000_000):
    lo = 0
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fn(mid) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return lo


# 文書が書いた境目（M2 §2・§3、H5、I2、I5）： (ラベル, 年分, 所得要件, 文書の値, 文書の「式だけの値」 or None)
THRESHOLD_CLAIMS = [
    ("R7 扶養58万", 2025, 580_000, 1_230_000, 1_230_000),
    ("R7 勤労学生85万", 2025, 850_000, 1_500_000, 1_500_000),
    ("R7 特定親族85万", 2025, 850_000, 1_500_000, 1_500_000),
    ("R7 特定親族90万", 2025, 900_000, 1_550_000, None), ("R7 特定親族95万", 2025, 950_000, 1_600_000, None),
    ("R7 特定親族100万", 2025, 1_000_000, 1_650_000, None), ("R7 特定親族105万", 2025, 1_050_000, 1_700_000, None),
    ("R7 特定親族110万", 2025, 1_100_000, 1_750_000, None), ("R7 特定親族115万", 2025, 1_150_000, 1_800_000, None),
    ("R7 特定親族120万", 2025, 1_200_000, 1_850_000, None), ("R7 特定親族123万", 2025, 1_230_000, 1_880_000, 1_880_000),
    ("R7 源泉控除対象親族100万", 2025, 1_000_000, 1_650_000, 1_650_000),
    ("R7 配偶者特別控除133万", 2025, 1_330_000, 2_015_999, 2_014_287),
    ("R7 基礎控除132万", 2025, 1_320_000, 2_003_999, 2_000_001),
    ("R7 基礎控除336万", 2025, 3_360_000, 4_751_999, 4_750_001),
    ("R7 基礎控除489万", 2025, 4_890_000, 6_655_556, 6_655_556),
    ("R7 基礎控除655万", 2025, 6_550_000, 8_500_000, 8_500_000),
    ("R7 基礎控除2350万", 2025, 23_500_000, 25_450_000, 25_450_000),
    ("R8 扶養62万", 2026, 620_000, 1_360_000, 1_360_000),
    ("R8 勤労学生89万", 2026, 890_000, 1_630_000, 1_630_000),
    ("R8 特定親族85万", 2026, 850_000, 1_590_000, 1_590_000),
    ("R8 特定親族90万", 2026, 900_000, 1_640_000, None), ("R8 特定親族95万", 2026, 950_000, 1_690_000, None),
    ("R8 特定親族100万", 2026, 1_000_000, 1_740_000, None), ("R8 特定親族105万", 2026, 1_050_000, 1_790_000, None),
    ("R8 特定親族110万", 2026, 1_100_000, 1_840_000, None), ("R8 特定親族115万", 2026, 1_150_000, 1_890_000, None),
    ("R8 特定親族120万", 2026, 1_200_000, 1_940_000, None), ("R8 特定親族123万", 2026, 1_230_000, 1_970_000, 1_970_000),
    ("R8 配偶者特別控除133万", 2026, 1_330_000, 2_070_000, 2_070_000),
    ("R8 基礎控除132万", 2026, 1_320_000, 2_060_000, 2_060_000),
    ("R8 基礎控除336万", 2026, 3_360_000, 4_751_999, 4_750_001),
    ("R8 基礎控除489万", 2026, 4_890_000, 6_655_556, 6_655_556),
    ("R8 基礎控除655万", 2026, 6_550_000, 8_500_000, 8_500_000),
    ("R8 基礎控除2350万", 2026, 23_500_000, 25_450_000, 25_450_000),
    ("R9 扶養62万", 2027, 620_000, 1_360_000, None), ("R9 勤労学生89万", 2027, 890_000, 1_630_000, None),
    ("R9 特定親族123万", 2027, 1_230_000, 1_970_000, None),
    ("R6 扶養48万", 2024, 480_000, 1_030_000, None), ("R6 勤労学生75万", 2024, 750_000, 1_300_000, None),
    # M2 §2「R1 の計算値は1円単位で正しかった」の確認用（scripts/results/R1_wage_thresholds/thresholds.md の残りの2項目）
    ("R1 R7 本人の所得税0（基礎控除95万）", 2025, 950_000, 1_600_000, None), ("R1 R8 本人の所得税0（基礎控除104万）", 2026, 1_040_000, 1_780_000, None),
    ("(仮定)R10 扶養62万", 2028, 620_000, 1_310_000, None), ("(仮定)R10 勤労学生89万", 2028, 890_000, 1_580_000, None),
    ("(仮定)R10 特定親族85万", 2028, 850_000, 1_540_000, None), ("(仮定)R10 特定親族123万", 2028, 1_230_000, 1_920_000, None),
    # 住民税（年度 → 前年の年分）。H4 の下での計算
    ("住R8年度 扶養58万", 2025, 580_000, 1_230_000, None), ("住R8年度 勤労学生85万", 2025, 850_000, 1_500_000, None),
    ("住R8年度 特定親族95万", 2025, 950_000, 1_600_000, None), ("住R8年度 特定親族100万", 2025, 1_000_000, 1_650_000, None),
    ("住R8年度 特定親族105万", 2025, 1_050_000, 1_700_000, None), ("住R8年度 特定親族110万", 2025, 1_100_000, 1_750_000, None),
    ("住R8年度 特定親族115万", 2025, 1_150_000, 1_800_000, None), ("住R8年度 特定親族120万", 2025, 1_200_000, 1_850_000, None),
    ("住R8年度 特定親族123万", 2025, 1_230_000, 1_880_000, None),
    ("住R8年度 非課税135万", 2025, 1_350_000, 2_043_999, 2_042_858),
    ("住R8年度 仙台45万", 2025, 450_000, 1_100_000, None), ("住R8年度 仙台101万", 2025, 1_010_000, 1_660_000, None),
    ("住R8年度 仙台136万", 2025, 1_360_000, 2_059_999, 2_057_144),
    ("住R8年度 仙台171万", 2025, 1_710_000, 2_559_999, 2_557_144), ("住R8年度 仙台206万", 2025, 2_060_000, 3_059_999, None),
    ("住R8年度 仙台241万", 2025, 2_410_000, 3_559_999, None),
    ("住R9年度 扶養62万", 2026, 620_000, 1_360_000, None), ("住R9年度 勤労学生89万", 2026, 890_000, 1_630_000, None),
    ("住R9年度 特定親族95万", 2026, 950_000, 1_690_000, None), ("住R9年度 特定親族100万", 2026, 1_000_000, 1_740_000, None),
    ("住R9年度 特定親族105万", 2026, 1_050_000, 1_790_000, None), ("住R9年度 特定親族110万", 2026, 1_100_000, 1_840_000, None),
    ("住R9年度 特定親族115万", 2026, 1_150_000, 1_890_000, None), ("住R9年度 特定親族120万", 2026, 1_200_000, 1_940_000, None),
    ("住R9年度 特定親族123万", 2026, 1_230_000, 1_970_000, None),
    ("住R9年度 非課税135万", 2026, 1_350_000, 2_090_000, 2_090_000),
    ("住R9年度 仙台45万", 2026, 450_000, 1_190_000, 1_190_000), ("住R9年度 仙台101万", 2026, 1_010_000, 1_750_000, 1_750_000),
    ("住R9年度 仙台136万", 2026, 1_360_000, 2_100_000, 2_100_000),
    ("住R9年度 仙台171万", 2026, 1_710_000, 2_559_999, None), ("住R9年度 仙台206万", 2026, 2_060_000, 3_059_999, None),
    ("住R9年度 仙台241万", 2026, 2_410_000, 3_559_999, None),
    ("住R10年度 扶養62万", 2027, 620_000, 1_360_000, None), ("住R10年度 非課税135万", 2027, 1_350_000, 2_090_000, None),
]

# I2 の表・M2 §4・I4 の点の値： (年分, 給与収入, 文書の値, old=年末調整の旧表か)
POINT_CLAIMS = [
    (2025, 650_999, 0, False), (2025, 651_000, 1_000, False), (2025, 1_230_000, 580_000, False), (2025, 1_230_001, 580_001, False),
    (2025, 1_500_000, 850_000, False), (2025, 1_500_001, 850_001, False), (2025, 1_880_000, 1_230_000, False), (2025, 1_880_001, 1_230_001, False),
    (2025, 2_003_999, 1_320_000, False), (2025, 2_004_000, 1_322_800, False), (2025, 2_015_999, 1_328_400, False), (2025, 2_016_000, 1_331_200, False),
    (2026, 690_999, 0, False), (2026, 691_000, 0, False), (2026, 740_999, 0, False), (2026, 741_000, 1_000, False),
    (2026, 1_360_000, 620_000, False), (2026, 1_360_001, 620_001, False), (2026, 1_630_000, 890_000, False), (2026, 1_630_001, 890_001, False),
    (2026, 1_590_000, 850_000, False), (2026, 1_590_001, 850_001, False), (2026, 1_970_000, 1_230_000, False), (2026, 1_970_001, 1_230_001, False),
    (2026, 2_190_999, 1_450_999, False), (2026, 2_191_000, 1_451_000, False), (2026, 2_199_999, 1_456_000, False), (2026, 2_200_000, 1_460_000, False),
    (2026, 4_751_999, 3_358_400, False), (2026, 4_752_000, 3_361_600, False), (2026, 6_655_556, 4_890_000, False), (2026, 6_655_557, 4_890_001, False),
    (2026, 650_000, 0, True), (2026, 650_000, 0, False), (2026, 680_000, 30_000, True), (2026, 680_000, 0, False),
    (2026, 1_000_000, 350_000, True), (2026, 1_000_000, 260_000, False), (2026, 1_360_000, 710_000, True), (2026, 1_360_000, 620_000, False),
    (2026, 1_900_000, 1_250_000, True), (2026, 1_900_000, 1_160_000, False), (2026, 2_036_000, 1_345_200, True), (2026, 2_036_000, 1_296_000, False),
    (2026, 2_200_000, 1_460_000, True), (2026, 2_200_000, 1_460_000, False),
]
# M1 §5 の参考（別表第五のみ / 措置法適用後）
REF_R8 = [(690_999, 0, 0), (691_000, 1_000, 0), (740_999, 50_999, 0), (741_000, 51_000, 1_000), (1_360_000, 670_000, 620_000),
          (2_190_999, 1_451_600, 1_450_999), (2_199_999, 1_457_200, 1_456_000)]
# M1 §3 の表
B5_STATS_CLAIMS = {
    "2024-12-31": {"n": 1252, "below": 551_000, "minus_low": (551_000, 1_619_000, 550_000), "steps": [(1_619_000, 1_620_000, 1000, 1), (1_620_000, 1_624_000, 2000, 2), (1_624_000, 6_600_000, 4000, 1244)]},
    "2025-12-31": {"n": 1180, "below": 651_000, "minus_low": (651_000, 1_900_000, 650_000), "steps": [(1_900_000, 6_600_000, 4000, 1175)]},
    "2026-12-01": {"n": 1149, "below": 691_000, "minus_low": (691_000, 2_026_000, 690_000), "steps": [(2_026_000, 2_028_000, 2000, 1), (2_028_000, 6_600_000, 4000, 1143)]},
}
VERSION_DIFF_CLAIMS = [("2024-12-31", "2025-11-30", None), ("2025-11-30", "2025-12-31", (551_000, 1_900_000)), ("2025-12-31", "2026-11-09", None),
                       ("2026-11-09", "2026-11-30", None), ("2026-11-30", "2026-12-01", (651_000, 2_036_000)), ("2026-12-01", "2027-01-01", None)]
YEAR_OF_ASOF = {"2024-12-31": 2024, "2025-11-30": 2024, "2025-12-01": 2025, "2025-12-31": 2025, "2026-11-09": 2025, "2026-11-30": 2025,
                "2026-12-01": 2026, "2027-01-01": 2026}


def diff_ranges(f, g, lo, hi):
    """[lo, hi) の整数で f != g となる範囲（区間の list）。"""
    out, start = [], None
    for x in range(lo, hi):
        d = f(x) != g(x)
        if d and start is None:
            start = x
        if not d and start is not None:
            out.append((start, x))
            start = None
    if start is not None:
        out.append((start, hi))
    return out


def analyze(laws_dir, docs_dir):
    import email.utils
    laws_dir, docs_dir = pathlib.Path(laws_dir).resolve(), pathlib.Path(docs_dir).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    R = {"laws_dir": str(laws_dir), "docs_dir": str(docs_dir), "checks": []}

    def check(cid, where, ok, detail):
        R["checks"].append({"id": cid, "where": where, "ok": bool(ok), "detail": detail})

    # 1. 版（PS §0）と改正履歴
    mylog = json.loads((OUT / "fetch_laws_log.json").read_text(encoding="utf-8"))
    mine = {(f["short"], f["asof"]): f for f in mylog["fetches"]}
    for short, asof, rid, status, sha16 in LAW_META_CLAIMS:
        m = mine[(short, asof)]
        check(f"PS0-{short}-{asof}", "PS §0", m["law_revision_id"] == rid and m["current_revision_status"] == status,
              {"claimed": [rid, status, sha16], "mine": [m["law_revision_id"], m["current_revision_status"], m["sha256"][:16]],
               "sha_same": m["sha256"].startswith(sha16), "amendment_enforcement_date": m.get("amendment_enforcement_date")})
    R["my_versions"] = {f"{k[0]}@{k[1]}": [v.get("law_revision_id"), v.get("current_revision_status"), v.get("amendment_enforcement_date")] for k, v in mine.items()}
    revs = {}
    for rv in mylog["revisions"]:
        d = json.loads((laws_dir / rv["file"]).read_text(encoding="utf-8"))
        revs[rv["short"]] = {r["law_revision_id"]: r for r in d.get("revisions", [])}
    for short, rid in [("shotoku", "340AC0000000033_20251201_507AC0000000013"), ("shotoku", "340AC0000000033_20251218_507AC0000000013"),
                       ("shotoku", "340AC0000000033_20261201_508AC0000000012"), ("sochi", "332AC0000000026_20261201_508AC0000000012"),
                       ("sochi", "332AC0000000026_20261126_508AC0000000012"), ("chiho", "325AC0000000226_20270101_508AC0000000002")]:
        r = revs[short].get(rid)
        check(f"REV-{rid}", "PS §0・§1.4・§2.2（施行日）", r is not None,
              None if r is None else {k: r.get(k) for k in ("amendment_law_num", "amendment_promulgate_date", "amendment_enforcement_date", "amendment_enforcement_comment", "current_revision_status")})

    # 2. 条文の文言
    roots = {}

    def root_of(short, asof):
        if (short, asof) not in roots:
            roots[(short, asof)] = load_law(laws_dir, short, asof)["law_full_text"]
        return roots[(short, asof)]
    for cid, where, short, asofs, loc, frags, expect in LAW_CLAIMS:
        for asof in asofs:
            t = locate_text(root_of(short, asof), loc)
            if t is None:
                check(f"{cid}@{asof}", where, False, {"error": "箇所が見つからない", "loc": loc})
                continue
            nt = norm(t)
            res = {f: (norm(f) in nt) for f in frags}
            ok = all(res.values()) if expect else not any(res.values())
            check(f"{cid}@{asof}", where, ok, {"loc": loc, "fragments": res, "expect_present": expect, "text_head": t[:160]})
    t29 = {a: txt(main_articles(root_of("sochi", a))["29_4"]) for a in ["2026-12-01", "2027-01-01", "2028-01-01"]}
    check("PS2.1-same", "PS §2.1（2027-01-01・2028-01-01 版も同じ文言）", len(set(t29.values())) == 1,
          {a: hashlib.sha256(v.encode()).hexdigest()[:16] for a, v in t29.items()})
    t28 = {a: txt(paragraph(main_articles(root_of("shotoku", a))["28"], 4)) for a in ["2024-12-31", "2025-12-31", "2026-12-01"]}
    check("PS1.1-same", "PS §1.1（所法 R6・R7・R8 で同じ文言）", len(set(t28.values())) == 1, {})
    p313 = {a: [txt(p) for p in children(main_articles(root_of("chiho", a))["313"], "Paragraph")] for a in CHIHO_ASOFS}
    base = p313["2027-01-01"]
    dd = {}
    for a in CHIHO_ASOFS:
        n = max(len(base), len(p313[a]))
        dd[a] = [i + 1 for i in range(n) if (base[i] if i < len(base) else None) != (p313[a][i] if i < len(p313[a]) else None)]
    check("PS3.1-diff", "PS §3.1（2027-01-01 版と比べ、2025-12-31 版との差は第12項だけ、2026-11-09・2028-01-01 版とは差がない）",
          dd["2025-12-31"] == [12] and dd["2026-11-09"] == [] and dd["2028-01-01"] == [], dd)
    b5 = {a: beppyo5_parse(root_of("shotoku", a)) for a in LAWS[0][2]}
    rem = {a: tuple(v["remarks"]) for a, v in b5.items()}
    check("PS1.2-remarks", "PS §1.2 備考（全版で同じ文言）", len(set(rem.values())) == 1 and all(len(r) == 1 for r in rem.values()),
          {"n_distinct": len(set(rem.values())), "text": list(rem.values())[0]})
    want_rem = ("（備考）給与所得控除後の給与等の金額を求めるには、その年中の給与等の金額に応じ、「給与等の金額」欄の該当する行を求めるものとし、"
                "その行の「給与所得控除後の給与等の金額」欄に記載されている金額が、その給与等の金額についての給与所得控除後の給与等の金額である。"
                "この場合において、給与等の金額が６，６００，０００円以上の居住者の給与所得控除後の給与等の金額に１円未満の端数があるときは、"
                "これを切り捨てた額をもつてその求める給与所得控除後の給与等の金額とする。")
    check("PS1.2-remarks-text", "PS §1.2 備考の文言", norm(want_rem) == norm(list(rem.values())[0][0]), {})
    check("PS1.2-related", "PS §1.2 関係条", all(v["related"] == "年末調整等のための給与所得控除後の給与等の金額の表（第二十八条、第百九十条関係）" for v in b5.values()),
          {a: v["related"] for a, v in b5.items()})
    ns = {a: v["n_structs"] for a, v in b5.items()}
    check("PS1.2-structs", "PS §1.2 TableStruct の数（（一）〜（九）または（八））", set(ns.values()) <= {8, 9}, ns)
    lit = set()
    for n, _ in iter_nodes(beppyo5_node(root_of("shotoku", "2025-12-31"))):
        if n.get("tag") == "TableColumn" and ("控除" in txt(n) or txt(n).strip().endswith("円")):
            lit.add(txt(n).strip())
    # 訂正の確認：文書は当初、式のセルを漢数字（「六五〇，〇〇〇」）で引用していた。原文は全角の算用数字
    check("PS1.2-literal（訂正後）", "PS §1.2 式のセルの原文の表記は全角の算用数字（当初の文書は漢数字で引用＝誤り）",
          "給与等の金額から６５０，０００円を控除した金額" in lit and "２０，０００，０００円" in lit and "１８，０５０，０００円" in lit
          and not any("〇" in x for x in lit),
          {"literal_cells_2025-12-31": sorted(lit), "original_claim": "給与等の金額から六五〇，〇〇〇円を控除した金額／二〇，〇〇〇，〇〇〇円｜一八，〇五〇，〇〇〇円"})

    # 3. 別表第五：自前の読み取り、他の担当の CSV との照合、統計、式との照合
    other_dir = ROOT / "scripts" / "results" / "IMPL_kyuyo_beppyo5"
    tables = {}
    for a, v in b5.items():
        bands = v["bands"]
        tables[a] = B5(bands)
        nonpt = [b for b in bands if b[2] != "point"]
        gaps = [(nonpt[i][1], nonpt[i + 1][0]) for i in range(len(nonpt) - 1) if nonpt[i][1] != nonpt[i + 1][0]]
        check(f"M1-b5-gaps@{a}", "M1 §3 隙間・重なり 0", not gaps and nonpt[0][0] == 0 and nonpt[-1][1] == 20_000_000, {"gaps": gaps[:5]})
        p_other = other_dir / f"beppyo5_{a}.csv"
        if p_other.exists():
            other = []
            with open(p_other, encoding="utf-8") as fp:
                for r in csv.DictReader(fp):
                    if r["kind"] == "point":
                        continue
                    lo, up, k = int(r["lower_incl"]), int(r["upper_excl"]), r["kind"]
                    if k == "fixed":
                        other.append((lo, up, "fixed", int(r["value"]), None))
                    elif k == "minus":
                        other.append((lo, up, "minus", int(r["formula_c"]), None))
                    elif k == "rate_minus":
                        other.append((lo, up, "rate", int(r["formula_rate_pct"]), int(r["formula_c"])))
            other.sort()
            check(f"M1-b5-vs-other@{a}", "M1 §3（他の担当の CSV と自前の読み取りが全区分で一致）", other == nonpt,
                  {"n_mine_nonpoint": len(nonpt), "n_other_nonpoint": len(other),
                   "only_mine": [x for x in nonpt if x not in other][:5], "only_other": [x for x in other if x not in nonpt][:5]})
        steps = {}
        for b in bands:
            if b[2] == "fixed" and b[0] > 0:
                steps.setdefault(b[1] - b[0], []).append(b[0])
        st = {"n": len(bands), "steps": {w: (min(v), max(v) + w, len(v)) for w, v in steps.items()},
              "first": bands[0], "formula": [b for b in bands if b[2] in ("minus", "rate")], "point": [b for b in bands if b[2] == "point"]}
        R.setdefault("beppyo5_stats", {})[a] = st
        if a in B5_STATS_CLAIMS:
            c = B5_STATS_CLAIMS[a]
            ok = (st["n"] == c["n"] and bands[0][:4] == (0, c["below"], "fixed", 0)
                  and any(b[:4] == (c["minus_low"][0], c["minus_low"][1], "minus", c["minus_low"][2]) for b in bands)
                  and all(st["steps"].get(w) == (lo, hi, n) for lo, hi, w, n in c["steps"]) and len(st["steps"]) == len(c["steps"])
                  and any(b[:5] == (6_600_000, 8_500_000, "rate", 90, 1_100_000) for b in bands)
                  and any(b[:4] == (8_500_000, 20_000_000, "minus", 1_950_000) for b in bands)
                  and len(st["point"]) == 1 and st["point"][0][3] == 20_000_000 and st["point"][0][4] == 18_050_000)
            check(f"M1-b5-stats@{a}", "M1 §3 の表（区分の数・最初の区分・式の区分・刻み）", ok, st)
        year = YEAR_OF_ASOF[a]
        bad = []
        for b in bands:
            if b[2] == "fixed" and b[0] > 0 and b[3] != math.floor(Fraction(b[0]) - koujo(year, b[0])):
                bad.append(b)
            if b[2] in ("minus", "rate"):
                for x in (b[0], b[0] + 1, b[1] - 2, b[1] - 1):
                    if tables[a](x) != math.floor(Fraction(x) - koujo(year, x)):
                        bad.append((b, x))
            if b[2] == "point" and b[4] != math.floor(Fraction(b[3]) - koujo(year, b[3])):
                bad.append(b)
        below = bands[0][1] - 1
        e999 = math.floor(Fraction(below) - koujo(year, below))
        check(f"M1-b5-formula@{a}", "M1 §3.1 表の金額＝区分の下限で評価した第28条第3項の式（不一致0）、下限0の区分の上端の手前は式で999",
              not bad and e999 == 999, {"bad": bad[:5], "art28_at_below_upper_minus_1": e999})
    for a1, a2, rng in VERSION_DIFF_CLAIMS:
        same_bands = b5[a1]["bands"] == b5[a2]["bands"]
        if rng is None:
            check(f"M1-vdiff {a1}->{a2}", "M1 §3.2 同一", same_bands, {})
        else:
            dr = diff_ranges(tables[a1], tables[a2], 0, 6_600_000)
            check(f"M1-vdiff {a1}->{a2}", "M1 §3.2 値が違う範囲（1円単位で再計算）", bool(dr) and (dr[0][0], dr[-1][1]) == rng,
                  {"ranges_head": dr[:3], "ranges_tail": dr[-3:], "n_ranges": len(dr)})
    dr = diff_ranges(tables["2025-12-31"], tables["2026-12-01"], 0, 6_600_000)
    outside = [(lo, min(hi, 691_000)) for lo, hi in dr if lo < 691_000] + [(max(lo, 2_200_000), hi) for lo, hi in dr if hi > 2_200_000]
    check("H3-range", "H3 確定申告で旧表と新表が違うのは措置法の範囲外の [651,000, 691,000) だけ", outside == [(651_000, 691_000)], {"outside": outside, "diff_ranges": dr[:2]})

    # 4. 措置法第29条の4第2項 と 別表第五（2026-12-01）の差（M1 §5）
    t8 = tables["2026-12-01"]
    sw = {"n": 0, "min": None, "max": None, "argmax": None, "eq50000": 0, "sochi_greater": 0, "zero": 0}
    for x in range(691_000, 2_200_000):
        d = t8(x) - sochi2(x)
        sw["n"] += 1
        if sw["min"] is None or d < sw["min"]:
            sw["min"] = d
        if sw["max"] is None or d > sw["max"]:
            sw["max"], sw["argmax"] = d, x
        sw["eq50000"] += d == 50_000
        sw["sochi_greater"] += d < 0
        sw["zero"] += d == 0
    sw["below_691000_all_zero"] = all(t8(x) == 0 for x in range(0, 691_000))
    check("M1-5-sweep", "M1 §5 の表（最小600・最大50,999@740,999・50,000ちょうど1,285,004・措置法が大きい0・差0が0）",
          (sw["min"], sw["max"], sw["argmax"], sw["eq50000"], sw["sochi_greater"], sw["zero"], sw["below_691000_all_zero"]) == (600, 50_999, 740_999, 1_285_004, 0, 0, True), sw)
    kyuyo = make_kyuyo(tables)
    for x, b, s in REF_R8:
        check(f"M1-5-ref {x}", "M1 §5 参考", (t8(x), kyuyo(2026, x)) == (b, s), {"mine": (t8(x), kyuyo(2026, x)), "claimed": (b, s)})
    check("M1-4-ex", "M1 §4 手で照合した例", (tables["2025-12-31"](1_900_000), tables["2025-12-31"](6_256_000), t8(2_026_000), t8(2_027_999), kyuyo(2026, 2_204_000))
          == (1_250_000, 4_564_800, 1_336_000, 1_336_000, 1_462_800), {})
    xe = Fraction(690_000 - 80_000) / Fraction(30, 100)
    check("H2-2033333", "H2 「8万円＋収入×30%」が 69万円になる収入（約 2,033,333円）", math.floor(xe) == 2_033_333, {"exact": str(xe)})
    # 国税庁の表（PDF を自分で読んで書き写した値）との照合。令和7年分＝別表第五（2025-12-31）、令和8年分＝本調査の関数
    nta = [(2025, 650_999, 0), (2025, 651_000, 1_000), (2025, 1_899_999, 1_249_999), (2025, 1_900_000, 1_250_000), (2025, 1_939_999, 1_275_200),
           (2025, 2_003_999, 1_320_000), (2025, 2_043_999, 1_348_000), (2025, 2_044_000, 1_350_800), (2025, 2_059_999, 1_359_200), (2025, 2_060_000, 1_362_000),
           (2025, 2_459_999, 1_639_200), (2025, 6_256_000, 4_564_800), (2025, 6_599_999, 4_836_800),
           (2026, 740_999, 0), (2026, 741_000, 1_000), (2026, 2_190_999, 1_450_999), (2026, 2_191_000, 1_451_000), (2026, 2_195_999, 1_453_000),
           (2026, 2_196_000, 1_456_000), (2026, 2_200_000, 1_460_000), (2026, 2_204_000, 1_462_800), (2026, 2_383_999, 1_586_000),
           (2026, 2_583_999, 1_726_000), (2026, 2_584_000, 1_728_800), (2026, 2_783_999, 1_866_000), (2026, 2_987_999, 2_008_800), (2026, 3_183_999, 2_146_000)]
    bad = [(y, x, v, kyuyo(y, x)) for y, x, v in nta if kyuyo(y, x) != v]
    check("NTA-table", "M1 §4 国税庁の表（nencho2025/2026 114.pdf を検証者が読んで書き写した 27 点）", not bad, {"bad": bad})

    # 5. 単調性（全整数）と境目
    mono = {}
    for y in (2024, 2025, 2026, 2027, 2028):
        prev, nbad = -1, 0
        for x in range(0, 6_700_001):
            v = kyuyo(y, x)
            if v < prev:
                nbad += 1
            prev = v
        mono[y] = nbad
    check("M2-monotone", "M2 §1 関数が非減少（全整数 0〜6,700,000 で確認）", all(v == 0 for v in mono.values()), mono)
    rows = []
    for label, y, lim, claimed, claimed_f in THRESHOLD_CLAIMS:
        w = max_x(lambda x: kyuyo(y, x), lim)
        wf = max_x(lambda x: formula_only(y, x), lim)
        ok = (w == claimed) and (claimed_f is None or wf == claimed_f)
        rows.append({"label": label, "year": y, "limit": lim, "mine": w, "mine_formula_only": wf, "claimed": claimed, "claimed_formula_only": claimed_f, "ok": ok})
        check(f"TH {label}", "M2 §2・§3 / H5 / I2 / I3 / I5", ok, rows[-1])
    R["thresholds"] = rows
    for y, x, v, old in POINT_CLAIMS:
        mv = kyuyo(y, x, old=old)
        check(f"PT {y} {x}{' 旧表' if old else ''}", "I2・M2 §4・I4", mv == v, {"mine": mv, "claimed": v})
    diffs = [(x, kyuyo(2026, x, old=True) - kyuyo(2026, x)) for x in range(0, 2_300_000)]
    nz = [x for x, d in diffs if d != 0]
    mxd = max(d for _, d in diffs)
    argm = [x for x, d in diffs if d == mxd]
    n90000 = [x for x, d in diffs if d == 90_000]
    # 訂正の確認：文書は当初「最大 90,000円」と書いていた。実際の最大は 90,999円（給与収入 740,999円）
    check("M2-4-max（訂正後）", "M2 §4・H3・I4 年末調整（旧表）と確定申告の差は [651,000, 2,200,000) で最大 90,999円（740,999円）。差がちょうど 90,000円は 740,000円と [741,000, 1,900,000]",
          mxd == 90_999 and argm == [740_999] and nz[0] == 651_000 and nz[-1] == 2_199_999 and (n90000[0], n90000[-1], len(n90000)) == (740_000, 1_900_000, 1_159_002),
          {"max": mxd, "argmax": argm, "first": nz[0], "last": nz[-1], "eq90000_first_last_n": (n90000[0], n90000[-1], len(n90000)), "original_claim": "最大 90,000円"})
    a1, a2 = 1_000_000, 1_002_000
    check("H7-ex", "H7 支払者ごとに求めて足すと値が変わる（例：令和7年分 100万円＋100.2万円）", kyuyo(2025, a1 + a2) != kyuyo(2025, a1) + kyuyo(2025, a2),
          {"sum_then_table": kyuyo(2025, a1 + a2), "table_then_sum": kyuyo(2025, a1) + kyuyo(2025, a2)})

    # 6. 地方税法・同施行令のキーワード（文単位）
    for kw, exp in KW_CLAIMS.items():
        got = {"chiho": [len(keyword_sentences(root_of("chiho", a), kw)) for a in CHIHO_ASOFS],
               "chiho-rei": [len(keyword_sentences(root_of("chiho-rei", "2027-01-01"), kw))]}
        check(f"KW {kw}", "M1 §6 の表", got == exp, {"mine": got, "claimed": exp})
    det = {}
    for kw in ["二十九条の四", "給与所得控除", "別表第五", "租税特別措置法第二十九条"]:
        det[kw] = {a: keyword_sentences(root_of("chiho", a), kw) for a in CHIHO_ASOFS}
        det[kw]["chiho-rei 2027-01-01"] = keyword_sentences(root_of("chiho-rei", "2027-01-01"), kw)
    R["keyword_detail"] = det
    main29 = {a: sorted({h["article"] for h in det["二十九条の四"][a] if h["suppl"] is None}) for a in CHIHO_ASOFS}
    check("M1-6-main29", "M1 §6 本則の「二十九条の四」は 2025-12-31・2026-11-09 の第23条・第292条だけ、2027-01-01 以後は 0", main29 == {"2025-12-31": ["23", "292"], "2026-11-09": ["23", "292"], "2027-01-01": [], "2028-01-01": []}, main29)
    kyu = sorted({(h["suppl"], h["article"]) for h in det["給与所得控除"]["2027-01-01"]}, key=str)
    check("M1-6-kyuyo", "M1 §6 「給与所得控除」は第32条・第313条だけ", kyu == [(None, "313"), (None, "32")], kyu)
    kr = [(h["suppl"], h["article"]) for h in det["給与所得控除"]["chiho-rei 2027-01-01"]]
    check("M1-6-kyuyo-rei", "M1 §6 施行令の「給与所得控除」は第56条の89", kr == [(None, "56_89")], kr)
    a5689 = main_articles(root_of("chiho-rei", "2027-01-01")).get("56_89")
    rcap = caption(a5689) if a5689 is not None else None
    check("M1-6-56_89", "M1 §6 施行令第56条の89（国民健康保険税の減額）", rcap is not None and "国民健康保険税の減額" in rcap, rcap)
    b5hits = [(h["suppl"], h["article"]) for h in det["別表第五"]["2027-01-01"]]
    check("M1-6-beppyo5", "M1 §6 地方税法の「別表第五」は住民基本台帳法の別表を改める附則の文", all(s is not None for s, _ in b5hits),
          [h["snippet"] for h in det["別表第五"]["2027-01-01"]])

    # 7. 国税庁・総務省・地方公共団体（取得の記録、HTML の文言）
    dlog = json.loads((OUT / "fetch_docs_log.json").read_text(encoding="utf-8"))
    dmine = {d["name"]: d for d in dlog["docs"]}
    for name, (lm_date, sha) in DOC_META_CLAIMS.items():
        d = dmine[name]
        lm = d["headers"].get("Last-Modified") or ""
        lmd = email.utils.parsedate_to_datetime(lm).strftime("%Y-%m-%d") if lm else None
        check(f"DOC-meta {name}", "PS §4・§5（Last-Modified、SHA-256）", lmd == lm_date and d["sha256"].startswith(sha),
              {"mine_last_modified": lm, "mine_sha256": d["sha256"], "claimed": [lm_date, sha]})
    texts = {}
    for name in sorted({c[0] for c in HTML_CLAIMS}):
        texts[name] = html_text(docs_dir / dmine[name]["file"])
        (OUT / f"text_{name}.txt").write_text(texts[name], encoding="utf-8")
    for name, where, frags in HTML_CLAIMS:
        nt = norm(texts[name])
        res = {}
        for f in frags:
            if "|" in f:
                pa, pb = [norm(p) for p in f.split("|")]
                res[f] = (pa + "|" + pb) in nt or (pa + pb) in nt
            else:
                res[f] = norm(f) in nt
        check(f"HTML {name} {where}", where, all(res.values()), res)

    n_ok = sum(c["ok"] for c in R["checks"])
    R["summary"] = {"n_checks": len(R["checks"]), "n_ok": n_ok, "n_ng": len(R["checks"]) - n_ok, "ng": [c["id"] for c in R["checks"] if not c["ok"]]}
    (OUT / "verify.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = ["# IMPL_kyuyo_verify の結果", "", f"- 条文：`{laws_dir.relative_to(ROOT).as_posix()}`、資料：`{docs_dir.relative_to(ROOT).as_posix()}`",
          f"- 検査 {R['summary']['n_checks']} 件、合格 {n_ok} 件、不合格 {R['summary']['n_ng']} 件（不合格：{', '.join(R['summary']['ng'])}）", "",
          "| ID | 文書の箇所 | 結果 | 詳細（先頭） |", "|---|---|---|---|"]
    for c in R["checks"]:
        md.append(f"| {c['id']} | {c['where']} | {'OK' if c['ok'] else '**NG**'} | {json.dumps(c['detail'], ensure_ascii=False, default=str)[:300].replace('|', '／')} |")
    md += ["", "## 境目（自前の計算）", "", "| 項目 | 年分 | 要件 | 自前 | 自前（式だけ） | 文書 | 文書（式だけ） | 一致 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['label']} | {r['year']} | {r['limit']:,} | {r['mine']:,} | {r['mine_formula_only']:,} | {r['claimed']:,} | "
                  f"{'' if r['claimed_formula_only'] is None else format(r['claimed_formula_only'], ',')} | {'一致' if r['ok'] else '不一致'} |")
    (OUT / "verify.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(R["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__" and len(sys.argv) > 3 and sys.argv[1] == "analyze":
    analyze(sys.argv[2], sys.argv[3])
