"""R3X design verify2: 設計の下準備の2つの仮説の文書の独立した検証の続き（ネットワークは使わない）。

前の検証者のスクリプト scripts/R3X_design_verify.py（以下 V1）とは別の方法で数え直し、V1 が見ていない範囲を足す。
  - 統合元に round3 の仮説・推測（設計の2文書を除く）を含める（V1 は round3 を除いた 61 文書）。
  - 引用の節は、V1 の「節の番号 → 見出し」の表ではなく、見出しの行を1行ずつ正規表現で照合して探す。
  - 内容の照合は、V1 の「語（2文字以上の連なり）」ではなく、2文字の連なり（bigram）の割合で測る。
  - 印は、V1 の「印らしい書き方の型」ではなく、「」の中身の語で集める。
  - D17〜D21 との食い違いの候補を、決まった語で2文書から抜き出す。

対象:
  docs/hypotheses/20261109_round3_design-vocabulary.md（VOC）
  docs/hypotheses/20261109_round3_design-output.md（OUTD）
  docs/measurements/20261109_round3_design-vocab-scan.md（M-VOC）

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_design_verify2.py
  ... scripts/R3X_design_verify2.py sec <文書.md> <見出しの番号>   … その見出しの節を表示する（目で確かめる用）

出力: scripts/results/R3X_design_verify2/
  snapshot.json        … 2文書・M-VOC・統合元（round3 を含む）の SHA-256
  a_cites.tsv          … (a) 引用ごとに、引用先のファイルにその番号の見出し（又は表の行の番号）があるか
  a_review.txt         … (a) 引用を含む行のうち bigram の割合が 0.5 未満の行と、引用先の節の先頭（目で確かめる用）
  a_paths.tsv          … (a) 2文書と M-VOC に書かれた docs/・scripts/ のパスが実在するか
  b_counts.json        … (b) 表の行の数え直しと、本文に書かれた数、UO の定義と使用
  b_corpus_docs.tsv    … (b) 統合元（round3 を含む）の文書が VOC §3・OUTD のどこかで挙がっているか
  b_marks.tsv          … (b) 統合元の「」の中身のうち印の語を含むものと、OUTD §1.5 の行が同じ文書を挙げているか
  b_fact_rows.tsv      … (b) 統合元の表の行のうち、列見出しに「粒度」「単位」「記録」「置き場所」を持つ表の最初のセルと、VOC の行への最も近い bigram の割合
  b_xrefs.tsv          … (b) VOC が参照する conflicts の文書の X 番号・concepts の文書の節と、VOC の中の文脈
  c_d21_lines.tsv      … (c) 2文書のうち D17〜D21 に関わる語を含む行（目で確かめる用）
  d_rules.json         … (d) 外部 URL、根拠の列の仮説の参照、個人の情報らしい語、ファイル名の形
"""
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R3X_design_verify2"
VOC = "docs/hypotheses/20261109_round3_design-vocabulary.md"
OUTD = "docs/hypotheses/20261109_round3_design-output.md"
MVOC = "docs/measurements/20261109_round3_design-vocab-scan.md"
TARGETS = [VOC, OUTD]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def corpus_all():
    out = []
    for sub in ("hypotheses", "inferences"):
        for p in sorted((ROOT / "docs" / sub).glob("20261109_*.md")):
            rel = p.relative_to(ROOT).as_posix()
            if rel in TARGETS:
                continue
            out.append(rel)
    return out


def short(rel):
    return pathlib.Path(rel).stem.replace("20261109_", "")


def bigrams(s):
    s = re.sub(r"[\s\|`*「」（）()、。・：:，,.\[\]［］〈〉—\-]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


# ---------- 見出し ----------

HEAD = re.compile(r"^(#{1,6})\s+(.*)$")


def headings(text):
    """(行番号0始まり, レベル, 見出し) の並び。コードの囲みの中は除く。"""
    out, fence = [], False
    for i, ln in enumerate(text.splitlines()):
        if ln.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = HEAD.match(ln)
        if m:
            out.append((i, len(m.group(1)), m.group(2).strip()))
    return out


def find_section(text, num):
    """見出しの文字列が num（例 '1.4'、'§3'）で始まる節。見出しの頭の「§」「第」は無視。返り値 (見出し, 本文) か None。"""
    lines = text.splitlines()
    hs = headings(text)
    pat = re.compile(r"^(?:§\s*)?" + re.escape(num) + r"(?![0-9]|\.[0-9])")
    for k, (i, lv, h) in enumerate(hs):
        if pat.match(h):
            end = len(lines)
            for j, lv2, _ in hs[k + 1:]:
                if lv2 <= lv:
                    end = j
                    break
            return h, "\n".join(lines[i:end])
    return None


def find_item(text, item):
    """実測の番号（T02、C1、V2、K1 など）が、見出し・表の最初のセル・行頭の太字・箇条の頭にあるか。範囲（C1〜C6）も見る。"""
    lines = text.splitlines()
    p = re.match(r"([A-Z]+)([0-9]+)([a-z]?)$", item)
    for i, ln in enumerate(lines):
        s = ln.strip()
        if re.match(r"^(#{1,6}\s+|\|\s*|[-*]\s+(\*\*)?|\*\*)" + re.escape(item) + r"(?![0-9])", s):
            return i, "\n".join(lines[i:i + 25])
    if p:
        pre, n = p.group(1), int(p.group(2))
        for i, ln in enumerate(lines):
            for m in re.finditer(r"(?<![A-Za-z])" + pre + r"([0-9]+)\s*[〜~\-]\s*" + pre + r"?([0-9]+)", ln):
                if int(m.group(1)) <= n <= int(m.group(2)) and re.match(r"^(#{1,6}\s|\|)", ln.strip()):
                    return i, "\n".join(lines[i:i + 25])
    return None


# ---------- (a) 引用 ----------

ALIAS_DEF = [re.compile(r"^\|\s*\[([A-Za-z0-9\-]+)\]\s*\|\s*`(docs/[^`]+)`"),
             re.compile(r"［([A-Za-z0-9\-]+)］`(docs/[^`]+)`"),
             re.compile(r"\[([A-Za-z0-9\-]+)\]\s*`(docs/[^`]+)`")]
TOKEN = re.compile(r"［([A-Za-z0-9\-]+)］|§([0-9]+(?:\.[0-9]+)*)(?:〜§?([0-9]+(?:\.[0-9]+)*))?|(?<![A-Za-z0-9])([TCVK][0-9]+[a-z]?)(?![0-9])")
SEP_OK = re.compile(r"^[\s、・,，（）()0-9〜~\-]*$")


def alias_map(text):
    al = {}
    for ln in text.splitlines():
        for rx in ALIAS_DEF:
            for m in rx.finditer(ln):
                al[m.group(1)] = m.group(2)
    return al


def cites_of(rel):
    text = read(rel)
    al = alias_map(text)
    res = []
    for i, ln in enumerate(text.splitlines()):
        if any(rx.search(ln) for rx in ALIAS_DEF):
            continue
        cur, last_end = None, 0
        for m in TOKEN.finditer(ln):
            between = ln[last_end:m.start()]
            if m.group(1):
                cur = m.group(1)
                res.append((i + 1, cur, None))
            elif cur is not None and SEP_OK.match(between):
                if m.group(2):
                    res.append((i + 1, cur, ("sec", m.group(2), m.group(3))))
                elif m.group(4):
                    res.append((i + 1, cur, ("item", m.group(4), None)))
            else:
                cur = None
            last_end = m.end()
    return al, res


def check_cites():
    rows = []
    for rel in TARGETS:
        al, res = cites_of(rel)
        by_line = {}
        for ln, a, ref in res:
            by_line.setdefault((ln, a), []).append(ref)
        for (ln, a), refs in sorted(by_line.items()):
            f = al.get(a)
            if not f:
                rows.append((short(rel), ln, a, "", "", "略号の表にない"))
                continue
            if not (ROOT / f).exists():
                rows.append((short(rel), ln, a, f, "", "ファイルがない"))
                continue
            body = read(f)
            real = [r for r in refs if r]
            if not real:
                rows.append((short(rel), ln, a, f, "", "番号なし"))
                continue
            for kind, x, y in real:
                if kind == "sec":
                    for num in [x] + ([y] if y else []):
                        s = find_section(body, num)
                        rows.append((short(rel), ln, a, f, "§" + num, ("OK " + s[0][:50]) if s else "見出しがない"))
                else:
                    s = find_item(body, x)
                    rows.append((short(rel), ln, a, f, x, "OK" if s else "番号がない"))
    return rows


def review_rows():
    """引用を含む行の、根拠以外のセルの bigram が、引用先の節（全部の和）に何割あるか。0.5 未満を目で見る用に書き出す。"""
    out, stats = [], []
    for rel in TARGETS:
        text = read(rel)
        lines = text.splitlines()
        al, res = cites_of(rel)
        by = {}
        for ln, a, ref in res:
            if ref:
                by.setdefault(ln, []).append((a, ref))
        for ln, refs in sorted(by.items()):
            row = lines[ln - 1]
            cells = [c.strip() for c in row.strip().strip("|").split("|")] if row.strip().startswith("|") else [row]
            content = " ".join(c for c in cells if "［" not in c and "〈" not in c) or row
            content = re.sub(r"［[^］]*］[^、。|]*", "", content)
            content = re.sub(r"`[^`]*`", "", content)
            cb = bigrams(content)
            blob, heads = "", []
            for a, (kind, x, y) in refs:
                f = al.get(a)
                if not f or not (ROOT / f).exists():
                    continue
                body = read(f)
                if kind == "sec":
                    s = find_section(body, x)
                else:
                    s = find_item(body, x)
                    s = (x, s[1]) if s else None
                if s:
                    blob += s[1]
                    heads.append(f"[{a}] {x}: {str(s[0])[:60]}\n      " + s[1][:600].replace("\n", "\n      "))
            sb = bigrams(blob)
            cov = len(cb & sb) / len(cb) if cb else 1.0
            stats.append((short(rel), ln, round(cov, 2)))
            if cov < 0.5:
                out.append(f"### {short(rel)} L{ln} cov={cov:.2f}\n{row[:500]}\n  " + "\n  ".join(heads) + "\n")
    return out, stats


def paths():
    rows = []
    for rel in TARGETS + [MVOC]:
        for i, ln in enumerate(read(rel).splitlines()):
            for m in re.finditer(r"`((?:docs|scripts)/[^`\s]+)`", ln):
                p = m.group(1).rstrip("/")
                if "<" in p or "*" in p:
                    continue
                rows.append((short(rel), i + 1, p, (ROOT / p).exists()))
    return rows


# ---------- (b) 数え直し ----------

def counts():
    voc, outd = read(VOC), read(OUTD)
    c = {}
    for pre in ("F-P", "F-R", "F-T", "F-D", "F-A", "F-E", "J-", "C-", "P-", "N"):
        ids = re.findall(r"^\|\s*(" + re.escape(pre) + r"[0-9]+)\s*\|", voc, re.M)
        c["VOC_" + pre] = len(set(ids))
    c["VOC_F_total"] = sum(c["VOC_" + p] for p in ("F-P", "F-R", "F-T", "F-D", "F-A", "F-E"))
    c["VOC_section4_numbers"] = re.findall(r"^\|\s*(事実の語彙|人の判断|納税者の選択|見込み・計画|名前の付け方の案)\s*\|\s*([0-9]+)", voc, re.M)
    o = re.findall(r"^\|\s*(O[0-9]+)\s*\|", outd, re.M)
    uo_def = re.findall(r"^\|\s*(UO[0-9]+)\s*\|", outd, re.M)
    uo_used = sorted(set(re.findall(r"UO[0-9]+", outd)), key=lambda x: int(x[2:]))
    d = re.findall(r"^\|\s*(D[0-9]{2})\s*\|", outd, re.M)
    c.update({"OUTD_O": len(set(o)), "OUTD_O_max": max(o) if o else None, "OUTD_UO_defined": len(set(uo_def)),
              "OUTD_UO_used_not_defined": [u for u in uo_used if u not in uo_def],
              "OUTD_UO_defined_not_used_outside_7": [u for u in uo_def if len(re.findall(re.escape(u) + r"(?![0-9])", outd)) < 2],
              "OUTD_D": len(set(d))})
    sec12 = outd.split("### 1.2", 1)[1].split("### 1.3", 1)[0]
    c["OUTD_1.2_marks"] = re.findall(r"^\|\s*\*\*([^*]+)\*\*\s*\|\s*([^|]+?)\s*\|", sec12, re.M)
    c["OUTD_numbers_in_text"] = re.findall(r"(?:\*\*)?([0-9]+)(?:\*\*)?\s*(?:にする案|件に整理|（SCOPE)", outd)
    return c


def corpus_docs():
    voc, outd = read(VOC), read(OUTD)
    sec3 = voc.split("## 3.", 1)[1].split("## 4.", 1)[0] if "## 3." in voc else ""
    # VOC の略号の表（〈略号〉→ 文書名）
    amap = {}
    for m in re.finditer(r"〈([A-Za-z0-9\-]+)〉\s*\|\s*([A-Za-z0-9_\-]+)\s*\|", voc):
        amap[m.group(2)] = m.group(1)
    rows = []
    for rel in corpus_all():
        s = short(rel)
        a = amap.get(s)
        in_sec3 = bool(a and re.search(r"^\|\s*〈" + re.escape(a) + r"〉\s*\|", sec3, re.M))
        rows.append((s, a or "", in_sec3, s in outd, sha(rel)[:16]))
    return rows


MARK_WORDS = re.compile(r"未確定|対象外|見込|見積|出典|未確認|条件|食い違|注記|要確認|未対応|不明|既定|判断が必要|解釈|通達|通知|依存|矛盾|あふれ|記入|推定|定めなし|明文")
MARK_CTX = re.compile(r"印|返す|返し|結果に|注記|出す|警告|状態")


def marks():
    outd = read(OUTD)
    sec15 = outd.split("### 1.5", 1)[1].split("### 1.6", 1)[0]
    orows = []
    for ln in sec15.splitlines():
        m = re.match(r"^\|\s*(O[0-9]+)\s*\|\s*([^|]*)\|\s*([^|]*)\|", ln)
        if m:
            orows.append((m.group(1), m.group(2), m.group(3)))
    rows = []
    for rel in corpus_all():
        s = short(rel)
        lines = read(rel).splitlines()
        for i, ln in enumerate(lines):
            if not MARK_CTX.search(ln):
                continue
            for m in re.finditer(r"「([^」]{1,40})」", ln):
                q = m.group(1)
                if not MARK_WORDS.search(q):
                    continue
                listed = [o for o, _, where in orows if "`" + s + "`" in where]
                qb = bigrams(q)
                best, best_o = 0.0, ""
                for o, orig, where in orows:
                    ob = bigrams(orig)
                    sc = len(qb & ob) / len(qb) if qb else 0
                    if sc > best:
                        best, best_o = sc, o
                same = [o for o, orig, where in orows if "`" + s + "`" in where and qb and len(qb & bigrams(orig)) / len(qb) >= 0.5]
                rows.append((s, i + 1, q, ",".join(listed[:6]), best_o, round(best, 2), ",".join(same)))
    return rows


def fact_rows():
    voc = read(VOC)
    vrows = [ln for ln in voc.splitlines() if re.match(r"^\|\s*(F-|J-|C-|P-)", ln)]
    vb = [(re.match(r"^\|\s*([A-Z]-[A-Z]?[0-9]+)", r).group(1), bigrams(r)) for r in vrows]
    out = []
    for rel in corpus_all():
        lines = read(rel).splitlines()
        hdr = None
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s.startswith("|"):
                hdr = None
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if hdr is None:
                hdr = cells
                continue
            if set(cells[0]) <= set("-: "):
                continue
            if not any(any(w in h for w in ("粒度", "単位", "記録", "置き場所")) for h in hdr):
                continue
            item = re.sub(r"[*`]", "", cells[0])
            if not item or len(item) < 2:
                continue
            ib = bigrams(" ".join(cells[:2]))
            best, bid = 0.0, ""
            for vid, b in vb:
                sc = len(ib & b) / len(ib) if ib else 0
                if sc > best:
                    best, bid = sc, vid
            out.append((short(rel), i + 1, item[:50], " / ".join(hdr[:4])[:60], bid, round(best, 2)))
    return out


def xrefs():
    voc = read(VOC)
    rows = []
    for i, ln in enumerate(voc.splitlines()):
        for m in re.finditer(r"X[0-9]{2}", ln):
            rows.append(("X", m.group(0), i + 1, re.sub(r"\s+", " ", ln[max(0, m.start() - 60):m.end() + 20])))
        for m in re.finditer(r"concepts[^|、。）]{0,12}§[0-9.]+|concepts の文書 §[0-9.]+", ln):
            rows.append(("concepts", m.group(0), i + 1, re.sub(r"\s+", " ", ln[max(0, m.start() - 60):m.end() + 20])))
        for m in re.finditer(r"conflicts の文書(?: §[0-9.]+| X[0-9]+)?", ln):
            rows.append(("conflicts", m.group(0), i + 1, re.sub(r"\s+", " ", ln[max(0, m.start() - 60):m.end() + 20])))
    return rows


# ---------- (c) D17〜D21 ----------

C_WORDS = re.compile(r"既定|UO1(?![0-9])|UO3(?![0-9])|UO6(?![0-9])|UO22|見積|計画|原文未|端数|未入力|判断がない|判断・選択がない|現金主義|小規模企業共済|雑損失|準確定|出国|有利な方|最大を選|予測|D21|後の段|まれな欄")


def d21_lines():
    rows = []
    for rel in TARGETS:
        for i, ln in enumerate(read(rel).splitlines()):
            ws = sorted(set(C_WORDS.findall(ln)))
            if ws:
                rows.append((short(rel), i + 1, ",".join(ws), ln.strip()[:240]))
    return rows


# ---------- (d) 規約 ----------

PERSONAL = re.compile(r"長男|長女|次男|次女|三男|三女|息子|娘さん|うちの|我が家|ユーザーの(?:家族|子|妻|夫|父|母)|実在の家族")


def rules():
    res = {}
    for rel in TARGETS + [MVOC]:
        text = read(rel)
        lines = text.splitlines()
        urls = [(i + 1, u) for i, ln in enumerate(lines) for u in re.findall(r"https?://\S+", ln)]
        al = alias_map(text)
        kinds = {a: p.split("/")[1] for a, p in al.items()}
        bad = {a: p for a, p in al.items() if p.split("/")[1] not in ("measurements", "public-sources")}
        hyp_in_evidence = []
        hdr = None
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s.startswith("|"):
                hdr = None
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if hdr is None:
                hdr = cells
                continue
            for k, h in enumerate(hdr):
                if k < len(cells) and h.startswith("根拠") and "仮説" not in h:
                    if re.search(r"〈|`(?:round|impl|R[1-4])", cells[k]) or "仮説" in cells[k]:
                        hyp_in_evidence.append((i + 1, h, cells[k][:120]))
        personal = [(i + 1, m.group(0)) for i, ln in enumerate(lines) for m in PERSONAL.finditer(ln)]
        name_ok = bool(re.match(r"^20261109_round3_design-[a-z\-]+\.md$", pathlib.Path(rel).name))
        res[short(rel)] = {"urls": urls, "alias_kinds": kinds, "aliases_not_measurement_or_public": bad,
                           "hypothesis_in_evidence_cells": hyp_in_evidence, "personal_terms": personal,
                           "file_name_ok": name_ok}
    return res


def tsv(name, header, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snap = {"targets": {r: sha(r) for r in TARGETS + [MVOC]},
            "corpus": {r: sha(r) for r in corpus_all()}}
    (OUT / "snapshot.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[-] targets", {short(k): v[:16] for k, v in snap["targets"].items()}, "corpus", len(snap["corpus"]))
    print("[-] round3 in corpus", [short(r) for r in snap["corpus"] if "_round3_" in r])

    ac = check_cites()
    tsv("a_cites.tsv", ["doc", "line", "alias", "file", "ref", "result"], ac)
    bad = [r for r in ac if not str(r[5]).startswith("OK")]
    print(f"[a] cites={len(ac)} not_ok={len(bad)}")
    for r in bad:
        print("    ", r[:3], r[4], r[5], r[3][-60:])
    rv, stats = review_rows()
    (OUT / "a_review.txt").write_text("\n".join(rv), encoding="utf-8")
    print(f"[a] rows with refs={len(stats)} bigram<0.5={len(rv)}")
    ap = paths()
    tsv("a_paths.tsv", ["doc", "line", "path", "exists"], ap)
    print(f"[a] paths={len(ap)} missing={[(r[0], r[1], r[2]) for r in ap if not r[3]]}")

    cn = counts()
    (OUT / "b_counts.json").write_text(json.dumps(cn, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[b] counts", json.dumps(cn, ensure_ascii=False))
    cd = corpus_docs()
    tsv("b_corpus_docs.tsv", ["doc", "voc_alias", "in_VOC_sec3", "named_in_OUTD", "sha256_16"], cd)
    print(f"[b] corpus={len(cd)} not_in_VOC_sec3={[r[0] for r in cd if not r[2]]} not_in_OUTD={[r[0] for r in cd if not r[3]]}")
    mk = marks()
    tsv("b_marks.tsv", ["doc", "line", "quoted", "O_rows_listing_doc", "best_O", "best_score", "O_rows_same_doc_and_words"], mk)
    miss = [r for r in mk if not r[6]]
    print(f"[b] quoted mark-like strings={len(mk)} without O row (same doc & words>=0.5)={len(miss)}")
    fr = fact_rows()
    tsv("b_fact_rows.tsv", ["doc", "line", "item", "header", "best_VOC_row", "score"], fr)
    print(f"[b] fact-like rows={len(fr)} best<0.3={sum(1 for r in fr if r[5] < 0.3)}")
    xr = xrefs()
    tsv("b_xrefs.tsv", ["kind", "ref", "line", "context"], xr)
    print(f"[b] VOC refs to concepts/conflicts docs: X={len({r[1] for r in xr if r[0] == 'X'})} concepts={len([r for r in xr if r[0] == 'concepts'])} conflicts={len([r for r in xr if r[0] == 'conflicts'])}")

    dl = d21_lines()
    tsv("c_d21_lines.tsv", ["doc", "line", "words", "text"], dl)
    print(f"[c] lines with D17-D21 words={len(dl)}")
    rl = rules()
    (OUT / "d_rules.json").write_text(json.dumps(rl, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in rl.items():
        print(f"[d] {k}: urls={len(v['urls'])} bad_alias={v['aliases_not_measurement_or_public']} hyp_in_evidence={v['hypothesis_in_evidence_cells']} personal={v['personal_terms']} name_ok={v['file_name_ok']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sec":
        s = find_section(read(sys.argv[2]), sys.argv[3])
        print(s[1] if s else "(見出しがない)")
    else:
        main()
