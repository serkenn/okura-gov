"""R3X design verify: 設計の下準備の2つの仮説の文書の独立した検証（ネットワークは使わない）。

対象:
  docs/hypotheses/20261109_round3_design-vocabulary.md（略号 VOC）
  docs/hypotheses/20261109_round3_design-output.md（略号 OUTD）
  docs/measurements/20261109_round3_design-vocab-scan.md と scripts/results/R3X_design_vocab-scan/（略号 M-VOC）

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_design_verify.py
  ... scripts/R3X_design_verify.py show <文書.md> <節番号>      … 文書の節の本文を表示する（目で確かめる用）
  ... scripts/R3X_design_verify.py grep <文書.md> <正規表現>    … 文書の中で当たった行を、直前の見出しつきで表示する

出力: scripts/results/R3X_design_verify/
  a_citations.json      … (a) 2文書の「［略号］§n」「［略号］T02」などの引用ごとに、ファイル・節・番号があるか
  a_rows.tsv            … (a) 引用を含む行ごとに、行の語（漢字・カタカナの2文字以上の連なり）が引用先の節にあるか
  a_hyp_refs.json       … (a) 関係する仮説（〈略号〉H5.1、`round2_xxx` H5 など）の番号が統合元の文書にあるか
  a_doc_paths.json      … (a) 2文書に書かれた docs/ のパスが実在するか
  b_corpus.json         … (b) 統合元の 61 文書の SHA-256 と、M-VOC の corpus.json との一致
  b_counts.json         … (b) 2文書の表の行の数え直し（F-/J-/C-/P-/N/O/UO/D）と、本文に書かれた数との比較
  b_voc_docs.json       … (b) VOC §3 が 61 文書を全部挙げているか
  b_ascii_keys.tsv      … (b) 統合元のすべての英小文字の識別子（バッククォートの外も）と、VOC に出てくるか
  b_dotted.tsv          … (b) 統合元のすべての「日本語.日本語」の名前（バッククォートの外も）と、VOC・OUTD に出てくるか
  b_judgment_rows.tsv   … (b) 統合元の表の行のうち、セルが「判断」「選択」「見込み」を区分として持つ行と、VOC の J/C/P の行への最も近い対応
  b_marks.tsv           … (b) 統合元の印らしい書き方（「X」の印、印「X」、「X」と返す 等）と、OUTD §1.5 の出てくる文書に挙がっているか
  b_output_sections.tsv … (b) 統合元の見出しのうち出力に関わるもの（出力・結果・印・根拠・境目・シナリオ・様式・欄）と、OUTD がその文書に触れているか
  b_mvoc_recount.json   … (b) M-VOC の数（見出し・バッククォート・言い換え）の別の方法での数え直し
  d_rules.json          … (d) 2文書の外部 URL、根拠の略号の参照先の種類、根拠の列に仮説・推測が入っていないか
  a_o_rows.tsv          … (a) OUTD §1.5 の O01〜O63 の「元の書き方」が、挙げた文書の挙げた番号の節にあるか（2文字の連なりの割合）
  b_injection_rows.tsv  … (b) 統合元の表のうち注入（市町村・保険者のデータ）を列に持つ行の項目
  b_mvoc_section5.json  … (b) M-VOC §5 の表の「文書：行」の行に項目の語があるか
  targets_sha256.json   … 実行したときの2文書の SHA-256（訂正の前後を区別するため）
  before_fix/           … 2文書を訂正する前の実行の出力の写し（手で写した。スクリプトは書かない）
"""
import hashlib
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R3X_design_verify"
VOC = "docs/hypotheses/20261109_round3_design-vocabulary.md"
OUTD = "docs/hypotheses/20261109_round3_design-output.md"
MVOC_RES = ROOT / "scripts" / "results" / "R3X_design_vocab-scan"
TARGETS = [VOC, OUTD]

HEAD = re.compile(r"^(#{1,6})\s*(.*?)\s*$")
SECNUM = re.compile(r"^(?:§\s*)?([0-9]+(?:\.[0-9]+)*)(?=[.\s　）)：:]|$)")
JP_TERM = re.compile(r"[一-龥々〆ヵヶァ-ヴー]{2,}")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def corpus():
    files = []
    for sub in ("hypotheses", "inferences"):
        for p in sorted((ROOT / "docs" / sub).glob("20261109_*.md")):
            if "_round3_" in p.name:
                continue
            files.append(p.relative_to(ROOT).as_posix())
    return files


def sections(text):
    """節番号 → (開始行, 終了行(含まない), レベル, 見出し)。見出しの番号は「## 1.」「### 1.1 」「## §1」の形。"""
    lines = text.splitlines()
    heads = []
    in_fence = False
    for i, ln in enumerate(lines):
        if ln.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEAD.match(ln)
        if m and m.group(1):
            heads.append((i, len(m.group(1)), m.group(2)))
    out = {}
    for k, (i, lv, title) in enumerate(heads):
        end = len(lines)
        for j, lv2, _ in heads[k + 1:]:
            if lv2 <= lv:
                end = j
                break
        n = SECNUM.match(title)
        if n and n.group(1) not in out:
            out[n.group(1)] = (i, end, lv, title)
    return out, lines


def section_text(rel, sec):
    secs, lines = sections(read(rel))
    if sec not in secs:
        return None
    i, end, lv, title = secs[sec]
    return "\n".join(lines[i:end])


def heading_of_line(lines, idx):
    for j in range(idx, -1, -1):
        m = HEAD.match(lines[j])
        if m and m.group(1):
            return m.group(2)
    return ""


# ---------- (a) 引用 ----------

ALIAS_TABLE = re.compile(r"^\|\s*\[([A-Za-z0-9\-]+)\]\s*\|\s*`(docs/[^`]+\.md)`")
ALIAS_INLINE = re.compile(r"［([A-Za-z0-9\-]+)］`(docs/[^`]+\.md)`")
CIT = re.compile(r"［([A-Za-z0-9\-]+)］")
TAIL_OK = set("§0123456789.-、・,（）()〜 TCVabcdefghijklmnopqrstuvwxyz#")
REF_SEC = re.compile(r"§([0-9]+(?:\.[0-9]+)*)(?:-([0-9]+))?(?:[（(]([0-9・、]+)[）)])?")
REF_RANGE = re.compile(r"§([0-9]+(?:\.[0-9]+)*)〜§?([0-9]+(?:\.[0-9]+)*)")
REF_NUM = re.compile(r"(?<![A-Za-z0-9])([TCV][0-9]+[a-z]?)(?![0-9])")
REF_ITEM = re.compile(r"#([0-9]+)")


def aliases_of(text):
    al = {}
    for ln in text.splitlines():
        m = ALIAS_TABLE.match(ln)
        if m:
            al[m.group(1)] = m.group(2)
        for m in ALIAS_INLINE.finditer(ln):
            al[m.group(1)] = m.group(2)
    return al


def num_in_body(ref, body):
    if re.search(r"(?<![A-Za-z0-9])" + re.escape(ref) + r"(?![0-9])", body):
        return True
    m = re.match(r"([TCV])([0-9]+)", ref)
    if not m:
        return False
    p, n = m.group(1), int(m.group(2))
    for r in re.finditer(r"(?<![A-Za-z0-9])" + p + r"([0-9]+)[a-z]?\s*[〜~\-]\s*" + p + r"?([0-9]+)", body):
        if int(r.group(1)) <= n <= int(r.group(2)):
            return True
    return False


def parse_citations(rel):
    text = read(rel)
    al = aliases_of(text)
    lines = text.splitlines()
    cites = []
    for i, ln in enumerate(lines):
        if ALIAS_TABLE.match(ln) or ALIAS_INLINE.search(ln):
            continue
        for m in CIT.finditer(ln):
            alias = m.group(1)
            j = m.end()
            tail = []
            while j < len(ln) and ln[j] in TAIL_OK:
                tail.append(ln[j])
                j += 1
            tail = "".join(tail)
            refs = []
            for r in REF_RANGE.finditer(tail):
                refs.append(("range", r.group(1), r.group(2)))
            for r in REF_SEC.finditer(tail):
                refs.append(("sec", r.group(1), r.group(2) or "", r.group(3) or ""))
            for r in REF_NUM.finditer(tail):
                refs.append(("num", r.group(1)))
            for r in REF_ITEM.finditer(tail):
                refs.append(("item", r.group(1)))
            cites.append({"line": i + 1, "alias": alias, "tail": tail.strip(), "refs": refs, "col": m.start()})
    return al, cites, lines


def check_citations():
    report = {}
    for rel in TARGETS:
        al, cites, lines = parse_citations(rel)
        cache = {}
        results = []
        for c in cites:
            alias = c["alias"]
            if alias not in al:
                results.append({**c, "ok": False, "why": "略号が表にない"})
                continue
            f = al[alias]
            if not (ROOT / f).exists():
                results.append({**c, "ok": False, "why": "ファイルがない: " + f})
                continue
            if f not in cache:
                body = read(f)
                cache[f] = (sections(body)[0], body)
            secs, body = cache[f]
            if not c["refs"]:
                results.append({**c, "file": f, "ok": False, "why": "節・番号の指定がない"})
                continue
            for r in c["refs"]:
                if r[0] == "sec":
                    ok = r[1] in secs
                    results.append({"line": c["line"], "alias": alias, "file": f, "ref": "§" + r[1] + (("-" + r[2]) if r[2] else "") + (("（" + r[3] + "）") if r[3] else ""),
                                    "ok": ok, "why": "" if ok else "見出しに節番号がない",
                                    "heading": secs[r[1]][3] if ok else ""})
                elif r[0] == "range":
                    ok = r[1] in secs and r[2] in secs
                    results.append({"line": c["line"], "alias": alias, "file": f, "ref": "§" + r[1] + "〜§" + r[2], "ok": ok,
                                    "why": "" if ok else "範囲の端の節がない"})
                elif r[0] == "num":
                    ok = num_in_body(r[1], body)
                    results.append({"line": c["line"], "alias": alias, "file": f, "ref": r[1], "ok": ok,
                                    "why": "" if ok else "本文に番号がない"})
                elif r[0] == "item":
                    results.append({"line": c["line"], "alias": alias, "file": f, "ref": "#" + r[1], "ok": True,
                                    "why": "項目番号（目で確かめる）"})
        unused = sorted(set(al) - {c["alias"] for c in cites})
        kinds = {a: ("measurements" if "/measurements/" in p else "public-sources" if "/public-sources/" in p else "other")
                 for a, p in al.items()}
        report[rel] = {"aliases": al, "alias_kinds": kinds, "unused_aliases": unused,
                       "n_citation_groups": len(cites), "n_refs": len(results),
                       "n_fail": sum(1 for r in results if not r["ok"]),
                       "failures": [r for r in results if not r["ok"]], "all": results}
    return report


def split_row(ln):
    s = ln.strip()
    if not s.startswith("|"):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    return cells


def table_header(lines, idx):
    """idx 行（表の行）の表の見出し行のセル。"""
    j = idx
    while j > 0 and lines[j - 1].strip().startswith("|"):
        j -= 1
    return split_row(lines[j]) or []


def strip_cites(s):
    s = re.sub(r"［[A-Za-z0-9\-]+］[§0-9.\-、・,（）()〜 TCVa-z#]*", " ", s)
    s = re.sub(r"〈[^〉]+〉[A-Za-z0-9.・#\- ]*", " ", s)
    s = re.sub(r"`[^`]*`", " ", s)
    return s


STOP = {"案", "事実", "判断", "選択", "根拠", "記録", "名前", "中身", "対象", "区分", "種類", "文書", "印", "未決",
        "入力", "出力", "結果", "値", "人", "日付", "区間", "年分", "年度", "粒度", "仮説", "関係", "推論", "判定コア",
        "コア", "台帳", "事実台帳", "判断台帳", "語彙", "概念", "書き方", "統合", "統合元", "注入", "注入データ",
        "取引", "メタデータ", "キー", "持つ", "使う"}


def row_support(al, cites_by_line, rel):
    lines = read(rel).splitlines()
    out = []
    cache = {}
    for ln_no, cs in sorted(cites_by_line.items()):
        ln = lines[ln_no - 1]
        cells = split_row(ln)
        if cells:
            hdr = table_header(lines, ln_no - 1)
            keep = []
            for k, cell in enumerate(cells):
                h = hdr[k] if k < len(hdr) else ""
                if any(w in h for w in ("根拠", "文書と節", "関係する仮説", "ID", "粒度", "出てくる文書", "#")):
                    continue
                keep.append(cell)
            content = " ".join(keep)
        else:
            content = ln
        content = strip_cites(content)
        terms = sorted({t for t in JP_TERM.findall(content) if t not in STOP})
        texts = []
        refs = []
        for c in cs:
            f = al.get(c["alias"])
            if not f or not (ROOT / f).exists():
                continue
            for r in c["refs"]:
                if r[0] in ("sec",):
                    key = (f, r[1])
                    if key not in cache:
                        cache[key] = section_text(f, r[1]) or ""
                    texts.append(cache[key])
                    refs.append(c["alias"] + "§" + r[1])
                elif r[0] == "range":
                    secs, ls = sections(read(f))
                    if r[1] in secs and r[2] in secs:
                        texts.append("\n".join(ls[secs[r[1]][0]:secs[r[2]][1]]))
                    refs.append(c["alias"] + "§" + r[1] + "〜" + r[2])
                elif r[0] == "num":
                    body = read(f)
                    # 番号の前後 40 行
                    ls = body.splitlines()
                    hit = [k for k, x in enumerate(ls) if re.search(r"(?<![A-Za-z0-9])" + re.escape(r[1]) + r"(?![0-9])", x)]
                    if not hit:
                        p = r[1][0]
                        for k, x in enumerate(ls):
                            for mm in re.finditer(r"(?<![A-Za-z0-9])" + p + r"([0-9]+)[a-z]?\s*[〜~\-]\s*" + p + r"?([0-9]+)", x):
                                if int(mm.group(1)) <= int(re.sub(r"[^0-9]", "", r[1])) <= int(mm.group(2)):
                                    hit.append(k)
                    for k in hit:
                        texts.append("\n".join(ls[max(0, k - 5):k + 40]))
                    refs.append(c["alias"] + ":" + r[1])
        blob = "\n".join(texts)
        found = [t for t in terms if t in blob]
        missing = [t for t in terms if t not in blob]
        cov = (len(found) / len(terms)) if terms else 1.0
        out.append((rel, ln_no, round(cov, 2), len(terms), " ".join(refs), " ".join(missing), ln.strip()[:120]))
    return out


# ---------- (a) 関係する仮説の番号 ----------

HYP_ID = r"(?:H[0-9]+(?:\.[0-9]+)*|HS[0-9]+|HE[0-9]+(?:\.[0-9]+)?|HK[0-9]+|HKY[0-9]+|HG[0-9]+|J[0-9]+|E[0-9]+|U[0-9]+|UK[0-9]+|UKY[0-9]+|I[0-9]+|IS[0-9]+|IE[0-9]+|IG[0-9]+|IKY[0-9]+|KI[0-9]+|S3-[0-9]+)"


def voc_hyp_aliases(text):
    """VOC の「関係する仮説・推測」の表（最初の「---」より前）だけから、〈略号〉→ 文書名を読む。"""
    amap = {}
    for ln in text.split("\n---\n", 1)[0].splitlines():
        for m in re.finditer(r"〈([A-Za-z0-9\-]+)〉\s*\|\s*([A-Za-z0-9_\-]+)\s*\|", ln):
            amap[m.group(1)] = m.group(2)
    return amap


def hyp_refs():
    res = {}
    # VOC: 〈略号〉ID・ID の形。略号 → 文書名は VOC の表。
    text = read(VOC)
    amap = voc_hyp_aliases(text)
    def path_of(name):
        for sub in ("hypotheses", "inferences"):
            p = ROOT / "docs" / sub / ("20261109_" + name + ".md")
            if p.exists():
                return p.relative_to(ROOT).as_posix()
        return None
    voc_items = []
    for i, ln in enumerate(text.splitlines(), 1):
        if re.match(r"^\|\s*〈", ln):
            continue
        for m in re.finditer(r"〈([A-Za-z0-9\-]+)〉((?:\s*(?:" + HYP_ID + r")(?:\s*#[0-9]+)?\s*[・、]?)*)", ln):
            alias, tail = m.group(1), m.group(2)
            name = amap.get(alias)
            p = path_of(name) if name else None
            ids = re.findall(HYP_ID, tail)
            for idv in ids:
                ok = bool(p) and re.search(r"(?<![A-Za-z0-9])" + re.escape(idv) + r"(?![0-9])(?!\.[0-9])", read(p)) is not None
                voc_items.append({"line": i, "alias": alias, "doc": p, "id": idv, "ok": ok})
            if not p:
                voc_items.append({"line": i, "alias": alias, "doc": None, "id": "", "ok": False})
    res[VOC] = {"alias_map": amap, "n": len(voc_items), "fail": [x for x in voc_items if not x["ok"]]}
    # OUTD: `name` ID・ID の形
    text = read(OUTD)
    out_items = []
    for i, ln in enumerate(text.splitlines(), 1):
        for m in re.finditer(r"`((?:round2b?|impl-prep|R[1-4]-[a-z]+|sakusei-corner)_[A-Za-z0-9_\-]+)`((?:\s*(?:" + HYP_ID + r")(?:〜(?:" + HYP_ID + r"))?\s*[・、]?)*)", ln):
            name, tail = m.group(1), m.group(2)
            p = path_of(name)
            ids = re.findall(HYP_ID, tail)
            if not p:
                out_items.append({"line": i, "name": name, "id": "", "ok": False, "why": "文書がない"})
                continue
            body = read(p)
            for idv in ids:
                ok = re.search(r"(?<![A-Za-z0-9])" + re.escape(idv) + r"(?![0-9])(?!\.[0-9])", body) is not None
                out_items.append({"line": i, "name": name, "id": idv, "ok": ok})
    # OUT-H1 / YH1 の略記
    for i, ln in enumerate(text.splitlines(), 1):
        for m in re.finditer(r"(?<![A-Za-z])(OUT-H|YH)([0-9]+(?:\.[0-9]+)?)", ln):
            name = "impl-prep_output-minimal-layer" if m.group(1) == "OUT-H" else "round2_yoshiki-mapping-table"
            idv = "H" + m.group(2)
            ok = re.search(r"(?<![A-Za-z0-9])" + re.escape(idv) + r"(?![0-9])", read(path_of(name))) is not None
            out_items.append({"line": i, "name": name, "id": idv, "ok": ok})
    res[OUTD] = {"n": len(out_items), "fail": [x for x in out_items if not x["ok"]]}
    return res


def doc_paths():
    res = {}
    for rel in TARGETS:
        items = []
        for i, ln in enumerate(read(rel).splitlines(), 1):
            for m in re.finditer(r"(docs/[A-Za-z\-]+/[0-9A-Za-z_\-]+\.md)", ln):
                items.append({"line": i, "path": m.group(1), "exists": (ROOT / m.group(1)).exists()})
        res[rel] = {"n": len(items), "missing": [x for x in items if not x["exists"]]}
    return res


# ---------- (b) 数え直し ----------

def counts():
    voc = read(VOC).splitlines()
    outd = read(OUTD).splitlines()
    def ids(lines, pat):
        return [m.group(1) for ln in lines for m in [re.match(r"^\|\s*(" + pat + r")\s*\|", ln)] if m]
    c = {
        "VOC_F": ids(voc, r"F-[A-Z][0-9]{2}"),
        "VOC_J": ids(voc, r"J-[0-9]{2}"),
        "VOC_C": ids(voc, r"C-[0-9]{2}"),
        "VOC_P": ids(voc, r"P-[0-9]{2}"),
        "VOC_N": ids(voc, r"N[0-9]"),
        "OUTD_O": ids(outd, r"O[0-9]{2}"),
        "OUTD_UO": ids(outd, r"UO[0-9]+"),
        "OUTD_D": ids(outd, r"D[0-9]{2}"),
    }
    summary = {k: {"n": len(v), "dups": [x for x, n in Counter(v).items() if n > 1]} for k, v in c.items()}
    fam = Counter(x[:3] for x in c["VOC_F"])
    summary["VOC_F_by_family"] = dict(fam)
    # OUTD §1.2 の統合後の語の行
    names = []
    in12 = False
    for ln in outd:
        if ln.startswith("### 1.2"):
            in12 = True
            continue
        if in12 and ln.startswith("### "):
            break
        if in12:
            cells = split_row(ln)
            if cells and cells[0].startswith("**"):
                names.append((cells[0].strip("*"), cells[1]))
    summary["OUTD_1.2_names"] = names
    # UO の参照（本文で使われているのに表にない／表にあるのに本文で使われていない）
    used = Counter(re.findall(r"UO[0-9]+", "\n".join(outd)))
    summary["OUTD_UO_used_not_defined"] = sorted(set(used) - set(c["OUTD_UO"]), key=lambda s: int(s[2:]))
    # VOC の X 番号（conflicts の文書の番号）の参照
    xs = sorted(set(re.findall(r"(?<![A-Za-z])X[0-9]{2}", "\n".join(voc))), key=lambda s: int(s[1:]))
    summary["VOC_X_refs"] = xs
    summary["VOC_concepts_refs"] = sorted(set(re.findall(r"concepts[^§\n]{0,6}§[0-9.]+", "\n".join(voc))))
    return summary


def voc_docs():
    text = read(VOC)
    amap = voc_hyp_aliases(text)
    listed = set()
    lines = text.splitlines()
    in3 = False
    for ln in lines:
        if ln.startswith("## 3."):
            in3 = True
            continue
        if in3 and ln.startswith("## "):
            break
        if in3:
            m = re.match(r"^\|\s*〈([A-Za-z0-9\-]+)〉\s*\|", ln)
            if m:
                listed.add(amap.get(m.group(1), "?" + m.group(1)))
    names = {pathlib.Path(p).stem.replace("20261109_", "") for p in corpus()}
    return {"n_corpus": len(names), "n_listed": len(listed), "not_listed": sorted(names - listed),
            "listed_not_in_corpus": sorted(listed - names)}


def corpus_hash():
    mine = {}
    for rel in corpus():
        raw = (ROOT / rel).read_bytes()
        mine[rel] = hashlib.sha256(raw).hexdigest()
    try:
        prev = json.loads((MVOC_RES / "corpus.json").read_text(encoding="utf-8"))
        prevmap = {x["file"]: x["sha256"] for x in prev["files"]}
    except FileNotFoundError:
        prevmap = {}
    diff = [f for f in mine if prevmap.get(f) != mine[f]]
    return {"n": len(mine), "n_prev": len(prevmap), "changed_or_new": diff,
            "missing_now": sorted(set(prevmap) - set(mine))}


ASCII_ID = re.compile(r"(?<![A-Za-z0-9_./\-])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?![A-Za-z0-9_(])")


def ascii_keys():
    voc = read(VOC)
    rows = []
    seen = defaultdict(list)
    for rel in corpus():
        lines = read(rel).splitlines()
        for i, ln in enumerate(lines):
            if "docs/" in ln and False:
                continue
            for m in ASCII_ID.finditer(ln):
                tok = m.group(1)
                if re.search(r"\.(py|md|json|tsv)$", tok):
                    continue
                seen[tok].append((rel, i + 1))
    for tok, occ in sorted(seen.items()):
        files = sorted({r for r, _ in occ})
        rows.append((tok, len(occ), len(files), "1" if tok in voc else "0",
                     ";".join(pathlib.Path(f).stem.replace("20261109_", "") + ":" + str(next(l for r, l in occ if r == f)) for f in files[:4])))
    return rows


DOTTED = re.compile(r"(?<![A-Za-z0-9_/])([一-龥々ァ-ヴー][一-龥々ァ-ヴーぁ-ん0-9A-Za-z_]*(?:\.[一-龥々ァ-ヴーぁ-ん0-9A-Za-z_（）()]+)+)")


def dotted():
    voc, outd = read(VOC), read(OUTD)
    seen = defaultdict(list)
    for rel in corpus():
        for i, ln in enumerate(read(rel).splitlines(), 1):
            for m in DOTTED.finditer(ln):
                tok = m.group(1).rstrip(".")
                if "." not in tok:
                    continue
                seen[tok].append((rel, i))
    rows = []
    for tok, occ in sorted(seen.items(), key=lambda kv: (kv[0].split(".")[0], kv[0])):
        files = sorted({r for r, _ in occ})
        rows.append((tok.split(".")[0], tok, len(occ), len(files), "1" if tok in voc else "0", "1" if tok in outd else "0",
                     ";".join(pathlib.Path(f).stem.replace("20261109_", "") for f in files[:4])))
    return rows


def bigrams(s):
    s = re.sub(r"[^一-龥々ァ-ヴーぁ-ん]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


CLASS_CELL = re.compile(r"(人の判断|判断|選択|見込み)")


def judgment_rows():
    voc_lines = read(VOC).splitlines()
    targets = []
    for ln in voc_lines:
        m = re.match(r"^\|\s*((?:J|C|P)-[0-9]{2})\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|", ln)
        if m:
            targets.append((m.group(1), m.group(2) + " " + m.group(4)))
    tb = [(tid, bigrams(t)) for tid, t in targets]
    rows = []
    for rel in corpus():
        lines = read(rel).splitlines()
        for i, ln in enumerate(lines):
            cells = split_row(ln)
            if not cells or len(cells) < 2 or set(cells[0]) <= set("-: "):
                continue
            hdr = table_header(lines, i)
            if cells == hdr:
                continue
            cls = None
            for k, cell in enumerate(cells[1:], 1):
                c = re.sub(r"[*`]", "", cell)
                if len(c) <= 40 and CLASS_CELL.search(c) and not c.startswith("判断台帳"):
                    h = hdr[k] if k < len(hdr) else ""
                    if any(w in h for w in ("区分", "種類", "記録", "層", "置き場所", "性質", "置く", "入力", "扱い", "分類")) or re.fullmatch(r"\**(人の)?判断[^|]{0,30}", c) or c.startswith("判断") or c.startswith("人の判断") or c.startswith("選択") or c.startswith("納税者の選択"):
                        cls = c
                        break
            if not cls:
                continue
            item = re.sub(r"[*`]", "", cells[0])
            b = bigrams(item + " " + (cells[1] if len(cells) > 1 else ""))
            best = ("", 0.0)
            for tid, tbg in tb:
                if not b or not tbg:
                    continue
                sc = len(b & tbg) / len(b)
                if sc > best[1]:
                    best = (tid, sc)
            rows.append((pathlib.Path(rel).stem.replace("20261109_", ""), i + 1, item[:60], cls[:40], best[0], round(best[1], 2)))
    return rows


MARK_PATS = [
    re.compile(r"「([^」\n]{1,30})」の印"),
    re.compile(r"印「([^」\n]{1,30})」"),
    re.compile(r"「([^」\n]{1,30})」(?:と|を)(?:返す|返し|出す|出し|表示|注記|明示|記録して返す|印)"),
    re.compile(r"「([^」\n]{1,30})」の(?:注記|警告|状態|フラグ)"),
    re.compile(r"(?:注記|警告|状態)「([^」\n]{1,30})」"),
]


def marks():
    outd = read(OUTD)
    # §1.5 の表の「出てくる文書」に挙がっている文書名
    listed = set(re.findall(r"`((?:round2b?|impl-prep|R[1-4]-[a-z]+|sakusei-corner)_[A-Za-z0-9_\-]+)`", outd))
    o_rows = {}
    for ln in outd.splitlines():
        m = re.match(r"^\|\s*(O[0-9]{2})\s*\|\s*([^|]*)\|\s*([^|]*)\|", ln)
        if m:
            o_rows[m.group(1)] = (m.group(2), set(re.findall(r"`([^`]+)`", m.group(3))))
    o_docs = set().union(*[d for _, d in o_rows.values()]) if o_rows else set()
    rows = []
    for rel in corpus():
        name = pathlib.Path(rel).stem.replace("20261109_", "")
        lines = read(rel).splitlines()
        for i, ln in enumerate(lines):
            for pat in MARK_PATS:
                for m in pat.finditer(ln):
                    s = m.group(1)
                    in_o = [k for k, (orig, _) in o_rows.items() if s and (s in orig or orig.strip("「」 ") in s)]
                    rows.append((name, i + 1, heading_of_line(lines, i)[:40], s, "1" if name in o_docs else "0",
                                 "1" if name in listed else "0", ",".join(in_o)))
    return rows


OUT_HEAD = re.compile(r"出力|結果|印|根拠の|境目|シナリオ|様式|欄|未確定|返す|返し方")


def output_sections():
    outd = read(OUTD)
    rows = []
    for rel in corpus():
        name = pathlib.Path(rel).stem.replace("20261109_", "")
        lines = read(rel).splitlines()
        for i, ln in enumerate(lines):
            m = HEAD.match(ln)
            if not (m and m.group(1)):
                continue
            title = m.group(2)
            if not OUT_HEAD.search(title):
                continue
            hid = re.match(r"((?:H|HS|HE|HK|HKY|HG|I|IS|IE|IG|IKY|KI|J|S3-)[0-9]+(?:\.[0-9]+)*)", title)
            hid = hid.group(1) if hid else ""
            doc_in = name in outd
            id_in = bool(hid) and re.search(re.escape(name) + r"`[^\n]{0,80}?(?<![A-Za-z0-9])" + re.escape(hid) + r"(?![0-9])", outd) is not None
            rows.append((name, i + 1, title[:70], hid, "1" if doc_in else "0", "1" if id_in else "0"))
    return rows


def mvoc_recount():
    """M-VOC の数を、別の方法（1行ずつの正規表現ではなく、ファイル全体の走査と、表の外も含めた数え方）で数え直す。"""
    files = corpus()
    n_head = 0
    n_tick = 0
    texts = {}
    for rel in files:
        t = read(rel)
        texts[rel] = t
        in_fence = False
        for ln in t.splitlines():
            if ln.startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence and re.match(r"#{1,6}\s", ln):
                n_head += 1
                continue
            if not in_fence:
                n_tick += len([x for x in re.findall(r"`([^`\n]+)`", ln) if x.strip()])
    var = {}
    for form in ["生計を一にする", "生計一", "同一の世帯に属する", "同一世帯", "判定日", "認定日", "基準日", "事実台帳", "人と関係の記録",
                 "判断台帳", "人の判断", "判断の記録", "納税者の選択", "本人の選択", "注入データ", "注入するデータ", "保険者データ",
                 "見込み", "見積り", "年間収入", "収入の見込み", "年収", "支払者", "支払った人", "受診者", "扶養所属", "扶養の所属",
                 "所属の割当て", "申告書の記載", "申告書等の記載", "中間表現", "未確定", "対象外", "出典未確認"]:
        n = sum(t.count(form) for t in texts.values())
        nf = sum(1 for t in texts.values() if form in t)
        var[form] = [n, nf]
    try:
        tok_lines = (MVOC_RES / "tokens.tsv").read_text(encoding="utf-8").count("\n") - 1
        sec_lines = (MVOC_RES / "sections.tsv").read_text(encoding="utf-8").count("\n") - 1
        cls_lines = (MVOC_RES / "classification_rows.tsv").read_text(encoding="utf-8").count("\n") - 1
    except FileNotFoundError:
        tok_lines = sec_lines = cls_lines = None
    return {"n_files": len(files), "headings_recount": n_head, "backtick_recount": n_tick,
            "mvoc_tokens_tsv_rows": tok_lines, "mvoc_sections_tsv_rows": sec_lines, "mvoc_classification_rows": cls_lines,
            "variants_recount": var,
            "mvoc_cite_check_json_exists": (MVOC_RES / "cite_check.json").exists()}


# ---------- (d) 規約 ----------

def rules():
    res = {}
    for rel in TARGETS:
        text = read(rel)
        lines = text.splitlines()
        urls = [(i + 1, u) for i, ln in enumerate(lines) for u in re.findall(r"https?://\S+|www\.\S+", ln)]
        al = aliases_of(text)
        bad_alias = {a: p for a, p in al.items() if not ("/measurements/" in p or "/public-sources/" in p)}
        # 根拠の列に〈 〉や仮説・推測の文書名が入っている行
        bad_cells = []
        for i, ln in enumerate(lines):
            cells = split_row(ln)
            if not cells:
                continue
            hdr = table_header(lines, i)
            for k, cell in enumerate(cells):
                h = hdr[k] if k < len(hdr) else ""
                if ("根拠" in h or h == "文書と節") and cells != hdr:
                    if re.search(r"〈|docs/(hypotheses|inferences)|`(round2b?|impl-prep|R[1-4]-)", cell):
                        bad_cells.append((i + 1, h, cell[:100]))
        res[rel] = {"urls": urls, "aliases_not_measurement_or_public": bad_alias, "evidence_cells_with_hypotheses": bad_cells}
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cit = check_citations()
    (OUT / "a_citations.json").write_text(json.dumps(cit, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = []
    for rel in TARGETS:
        al, cites, _ = parse_citations(rel)
        by = defaultdict(list)
        for c in cites:
            by[c["line"]].append(c)
        rows += row_support(al, by, rel)
    with (OUT / "a_rows.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("doc\tline\tcoverage\tn_terms\trefs\tmissing_terms\trow_head\n")
        for r in rows:
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    hr = hyp_refs()
    (OUT / "a_hyp_refs.json").write_text(json.dumps(hr, ensure_ascii=False, indent=1), encoding="utf-8")
    dp = doc_paths()
    (OUT / "a_doc_paths.json").write_text(json.dumps(dp, ensure_ascii=False, indent=1), encoding="utf-8")
    ch = corpus_hash()
    (OUT / "b_corpus.json").write_text(json.dumps(ch, ensure_ascii=False, indent=1), encoding="utf-8")
    cn = counts()
    (OUT / "b_counts.json").write_text(json.dumps(cn, ensure_ascii=False, indent=1), encoding="utf-8")
    vd = voc_docs()
    (OUT / "b_voc_docs.json").write_text(json.dumps(vd, ensure_ascii=False, indent=1), encoding="utf-8")
    ak = ascii_keys()
    with (OUT / "b_ascii_keys.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("token\tn\tn_files\tin_VOC\tfiles(first4):line\n")
        for r in ak:
            f.write("\t".join(str(x) for x in r) + "\n")
    dt = dotted()
    with (OUT / "b_dotted.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("prefix\ttoken\tn\tn_files\tin_VOC\tin_OUTD\tfiles(first4)\n")
        for r in dt:
            f.write("\t".join(str(x) for x in r) + "\n")
    jr = judgment_rows()
    with (OUT / "b_judgment_rows.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("doc\tline\titem\tclass_cell\tbest_VOC_row\tscore\n")
        for r in jr:
            f.write("\t".join(str(x) for x in r) + "\n")
    mk = marks()
    with (OUT / "b_marks.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("doc\tline\theading\tmark\tdoc_in_O_rows\tdoc_named_in_OUTD\tO_rows_with_same_words\n")
        for r in mk:
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    os_ = output_sections()
    with (OUT / "b_output_sections.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("doc\tline\theading\thyp_id\tdoc_named_in_OUTD\tid_named_in_OUTD\n")
        for r in os_:
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    mv = mvoc_recount()
    (OUT / "b_mvoc_recount.json").write_text(json.dumps(mv, ensure_ascii=False, indent=1), encoding="utf-8")
    rl = rules()
    (OUT / "d_rules.json").write_text(json.dumps(rl, ensure_ascii=False, indent=1), encoding="utf-8")

    # 要約を標準出力へ
    for rel in TARGETS:
        c = cit[rel]
        print(f"[a] {rel}: aliases={len(c['aliases'])} unused={c['unused_aliases']} groups={c['n_citation_groups']} refs={c['n_refs']} fail={c['n_fail']}")
        for r in c["failures"][:40]:
            print(f"    L{r['line']} [{r['alias']}] {r.get('ref', r.get('tail'))}: {r['why']}")
    low = [r for r in rows if r[2] < 0.5]
    print(f"[a] rows with citations={len(rows)} coverage<0.5={len(low)}")
    for rel in TARGETS:
        print(f"[a] hyp refs {rel}: n={hr[rel]['n']} fail={len(hr[rel]['fail'])}")
        for x in hr[rel]["fail"][:30]:
            print("    ", x)
        print(f"[a] doc paths {rel}: n={dp[rel]['n']} missing={len(dp[rel]['missing'])}")
        for x in dp[rel]["missing"][:20]:
            print("    ", x)
    print(f"[b] corpus n={ch['n']} prev={ch['n_prev']} changed={len(ch['changed_or_new'])} missing_now={ch['missing_now']}")
    print("[b] counts", json.dumps({k: (v if not isinstance(v, dict) else v.get('n', v)) for k, v in cn.items() if k != 'OUTD_1.2_names'}, ensure_ascii=False))
    print("[b] OUTD 1.2 names:", [n for n, _ in cn["OUTD_1.2_names"]])
    print(f"[b] VOC §3 docs: corpus={vd['n_corpus']} listed={vd['n_listed']} not_listed={vd['not_listed']} extra={vd['listed_not_in_corpus']}")
    print(f"[b] ascii ids={len(ak)} not_in_VOC={sum(1 for r in ak if r[3] == '0')}")
    print(f"[b] dotted names={len(dt)} not_in_VOC={sum(1 for r in dt if r[4] == '0')} not_in_either={sum(1 for r in dt if r[4] == '0' and r[5] == '0')}")
    print(f"[b] judgment-like rows={len(jr)} best_score<0.35={sum(1 for r in jr if r[5] < 0.35)}")
    print(f"[b] mark-like strings={len(mk)} in_docs_not_in_O_rows={sum(1 for r in mk if r[4] == '0')}")
    print(f"[b] output headings={len(os_)} doc_not_named={sum(1 for r in os_ if r[4] == '0')} id_not_named={sum(1 for r in os_ if r[3] and r[5] == '0')}")
    print("[b] mvoc recount", json.dumps({k: v for k, v in mv.items() if k != 'variants_recount'}, ensure_ascii=False))
    for rel in TARGETS:
        r = rl[rel]
        print(f"[d] {rel}: urls={len(r['urls'])} bad_alias={r['aliases_not_measurement_or_public']} evidence_cells_with_hyp={len(r['evidence_cells_with_hypotheses'])}")
        for x in r["evidence_cells_with_hypotheses"][:10]:
            print("    ", x)


def show(rel, sec):
    t = section_text(rel, sec)
    print(t if t is not None else f"(節 {sec} がない)")


def grep(rel, pat):
    lines = read(rel).splitlines()
    for i, ln in enumerate(lines):
        if re.search(pat, ln):
            print(f"{i + 1}\t[{heading_of_line(lines, i)[:30]}]\t{ln[:300]}")


# ---------- (a) OUTD §1.5 の「出てくる文書」の検査（追加） ----------

def o_rows_check():
    """OUTD §1.5 の各行（O01〜O63）の「元の書き方」が、挙げた文書の、挙げた番号の節（見出しがその番号で始まる節）にあるか。
    元の書き方から「」（）を外した語を、2文字の連なり（bigram）で比べ、節の本文に元の書き方の bigram の何割があるかを出す。"""
    outd = read(OUTD)
    rows = []
    for ln in outd.splitlines():
        m = re.match(r"^\|\s*(O[0-9]{2})\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|", ln)
        if not m:
            continue
        oid, orig, where = m.group(1), m.group(2).strip(), m.group(3)
        core = re.sub(r"[「」（）()]", " ", orig)
        cb = bigrams(core)
        for seg in re.split(r"；", where):
            mm = re.search(r"`([^`]+)`\s*(.*)", seg)
            if not mm:
                continue
            name, ids = mm.group(1), re.findall(HYP_ID + r"|の表", mm.group(2))
            p = None
            for sub in ("hypotheses", "inferences"):
                q = ROOT / "docs" / sub / ("20261109_" + name + ".md")
                if q.exists():
                    p = q.relative_to(ROOT).as_posix()
            if not p:
                rows.append((oid, orig, name, "", "", "文書がない"))
                continue
            text = read(p)
            lines = text.splitlines()
            for idv in [i for i in ids if i != "の表"] or [""]:
                if idv:
                    # 見出しがその番号で始まる節（次の同じか上のレベルの見出しまで）。見出しがなければ番号を含む行の前後 30 行
                    start = None
                    for k, x in enumerate(lines):
                        h = HEAD.match(x)
                        if h and h.group(1) and re.match(r"(?:" + re.escape(idv) + r")(?![0-9])", h.group(2)):
                            start, lv = k, len(h.group(1))
                            break
                    if start is not None:
                        end = len(lines)
                        for k in range(start + 1, len(lines)):
                            h = HEAD.match(lines[k])
                            if h and h.group(1) and len(h.group(1)) <= lv:
                                end = k
                                break
                        body = "\n".join(lines[start:end])
                    else:
                        hits = [k for k, x in enumerate(lines) if re.search(r"(?<![A-Za-z0-9])" + re.escape(idv) + r"(?![0-9])", x)]
                        body = "\n".join("\n".join(lines[max(0, k - 3):k + 30]) for k in hits)
                else:
                    body = text
                sb = bigrams(body)
                cov = (len(cb & sb) / len(cb)) if cb else 1.0
                rows.append((oid, orig[:40], name, idv, round(cov, 2), "" if body else "節がない"))
    return rows


def write_o_rows():
    rr = o_rows_check()
    with (OUT / "a_o_rows.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("O\toriginal\tdoc\tid\tbigram_coverage\tnote\n")
        for r in rr:
            f.write("\t".join(str(x) for x in r) + "\n")
    print(f"[a] OUTD §1.5 O rows: (行, 文書, 番号) の組={len(rr)} bigram<0.6={sum(1 for r in rr if isinstance(r[4], float) and r[4] < 0.6)} 文書・節なし={sum(1 for r in rr if r[5])}")
    for r in rr:
        if (isinstance(r[4], float) and r[4] < 0.6) or r[5]:
            print("   ", r)


# ---------- (b) 注入点の候補（追加） ----------

INJ_CELL = re.compile(r"注入")


def injection_rows():
    """統合元の表の行のうち、見出しに「注入」を含む列のセルが空でない（「なし」「—」でない）行、又は行のどこかのセルが
    「注入」で始まる短いセル（30字以下）の行。最初のセル（項目）を集める。"""
    rows = []
    for rel in corpus():
        name = pathlib.Path(rel).stem.replace("20261109_", "")
        lines = read(rel).splitlines()
        for i, ln in enumerate(lines):
            cells = split_row(ln)
            if not cells or len(cells) < 2 or set(cells[0]) <= set("-: "):
                continue
            hdr = table_header(lines, i)
            if cells == hdr:
                continue
            hit = ""
            for k, cell in enumerate(cells[1:], 1):
                h = hdr[k] if k < len(hdr) else ""
                c = re.sub(r"[*`]", "", cell).strip()
                if INJ_CELL.search(h) and c and c not in ("なし", "—", "-", "不要", "（なし）"):
                    hit = h[:20] + "=" + c[:40]
                    break
                if len(c) <= 30 and c.startswith("注入"):
                    hit = c
                    break
            if hit:
                rows.append((name, i + 1, re.sub(r"[*`]", "", cells[0])[:60], hit))
    return rows


def mvoc_section5_lines():
    """M-VOC §5 の表の「文書：行」が、classification_rows.tsv にあり、その行に項目の語があるか。"""
    mv = (ROOT / "docs/measurements/20261109_round3_design-vocab-scan.md").read_text(encoding="utf-8")
    sec = mv.split("## 5.", 1)[1].split("## 6.", 1)[0]
    out = []
    for ln in sec.splitlines():
        cells = split_row(ln)
        if not cells or len(cells) < 2 or cells[0] in ("項目",) or set(cells[0]) <= set("-: "):
            continue
        item, where = cells[0], cells[1]
        m = re.match(r"([A-Za-z0-9_\-]+):([0-9・]+)", where)
        if not m:
            continue
        name, nums = m.group(1), m.group(2).split("・")
        p = None
        for sub in ("hypotheses", "inferences"):
            q = ROOT / "docs" / sub / ("20261109_" + name + ".md")
            if q.exists():
                p = q
        lines = p.read_text(encoding="utf-8").splitlines() if p else []
        kws = [k for k in re.split(r"[・]", item)]
        for n in nums:
            n = int(n)
            ok = p is not None and 0 < n <= len(lines) and any(k[:3] in lines[n - 1] for k in kws)
            out.append((item, name, n, ok))
    return out


def main_all():
    OUT.mkdir(parents=True, exist_ok=True)
    sha = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in TARGETS}
    (OUT / "targets_sha256.json").write_text(json.dumps(sha, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[-] 対象の文書の SHA-256:", {pathlib.Path(k).name: v[:16] for k, v in sha.items()})
    main()
    write_o_rows()
    inj = injection_rows()
    with (OUT / "b_injection_rows.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("doc\tline\titem\tinjection_cell\n")
        for r in inj:
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    print(f"[b] 注入点の候補の行={len(inj)} 文書={len({r[0] for r in inj})}")
    s5 = mvoc_section5_lines()
    (OUT / "b_mvoc_section5.json").write_text(json.dumps(s5, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[b] M-VOC §5 の文書：行 = {len(s5)} 行に項目の語がない = {[x for x in s5 if not x[3]]}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        show(sys.argv[2], sys.argv[3])
    elif len(sys.argv) > 1 and sys.argv[1] == "grep":
        grep(sys.argv[2], sys.argv[3])
    else:
        main_all()
