"""R3X juminzei-extra: 住民税の (1) 家屋敷課税（事務所・事業所・家屋敷を有する者への均等割）、(2) 配当割額・株式等譲渡所得割額の控除、
(3) 住宅借入金等特別税額控除 の条文を、e-Gov 法令API v2 で時点（asof）ごとに取得し、条ごとのテキスト・版の間の差分・語の出現箇所を書く。

実行（リポジトリのルートで）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_juminzei-extra_laws.py            # 全部
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_juminzei-extra_laws.py chiho-rei  # 指定した略称だけ

標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
e-Gov の使い方と描画は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py・scripts/R2X_juminzei-tax_laws.py を写した（import はしない）。

- ダウンロードした JSON は .work/downloads/<ts>_R3X_juminzei-extra_laws/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/R3X_juminzei-extra_laws/:
  - <略称>_<asof>.txt            抜き出した本則の条・原始附則の条（版の情報つき）
  - <略称>_<asof>.articles.json  条ごとのテキスト（{"本則:294": "...", "附則:5_4": "..."}）。検査（R3X_juminzei-extra_checks.py）が読む
  - index_<略称>_<asof>.txt      本則と原始附則の条番号と見出しの一覧
  - hits_<略称>_<asof>.json      語（HIT_PATTERNS）の出現箇所（本則・原始附則・改正附則のどこか、条、前後の文）
  - amend_<略称>_<asof>.md       改正附則のうち AMEND_RE に当たる項（改正法令の番号つき）。適用関係を読むため
  - diff_<略称>_<asofA>_vs_<asofB>.md 条ごとの変化の有無と、変化した条の差分
  - fetch_log.json / fetch_log_<略称>.json 取得した URL・版・状態・SHA-256
"""
import difflib
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
NAME = "R3X_juminzei-extra_laws"

# 令和7年度分の賦課期日（比較のため）, 令和8年度分の賦課期日, 令和8年法律第2号の本体の施行日, 今日（現行）,
# 令和9年度分の賦課期日, 令和10年度分の賦課期日（令和9年度分との違いを見るため）
CHIHO_ASOFS = ["2025-01-01", "2026-01-01", "2026-04-01", "2026-11-09", "2027-01-01", "2028-01-01"]

CHIHO_MAIN = [
    # 定義・道府県民税
    "1", "23", "24", "24_5", "25", "32", "37_4", "39", "41", "45_2", "45_3",
    # 配当割・株式等譲渡所得割（税率と特別徴収）
    "71_27", "71_28", "71_31", "71_47", "71_49", "71_51",
    # 市町村民税
    "292", "294", "295", "296", "300", "310", "311", "313", "314_9", "317_2", "317_3", "317_6", "318", "319", "320",
    # 指定都市の区
    "737",
]
CHIHO_MAIN_RE = r"家屋敷|配当割額又は株式等譲渡所得割額|住宅借入金等特別税額控除|第二百九十四条第一項第二号|第二十四条第一項第二号"
CHIHO_SUPPL_NUMS = ["3_3", "5_4", "5_4_2", "45", "33_2", "35_2_2"]
CHIHO_SUPPL_RE = r"住宅借入金|配当割額|株式等譲渡所得割額|家屋敷"

AMEND_RE = (r"家屋敷|第二百九十四条|第二十四条第一項|第三百十四条の九|第三十七条の四|配当割額|株式等譲渡所得割額|附則第五条の四|住宅借入金"
            r"|特定配当等|第二十三条第一項第十五号|第三百十三条第十二項|第三十二条第十二項"
            # 改正法の附則の「…に関する部分は、令和X年度以後の年度分…について適用」（年度ごとの適用関係の原則）
            r"|令和六年度以後の年度分|令和八年度以後の年度分|令和九年度以後の年度分|令和十年度以後の年度分")
AMEND_LAW_RE = r"^令和"  # 改正附則は令和の改正法だけを見る（平成の改正附則は量が多く、令和8・9年度分の適用関係には直接関わらないため）

HIT_PATTERNS = [r"家屋敷", r"第二百九十四条第一項第二号", r"第二十四条第一項第二号", r"配当割額又は株式等譲渡所得割額",
                r"住宅借入金等特別税額控除"]

REI_RE = (r"家屋敷|配当割額又は株式等譲渡所得割額|第三百十四条の九|法第三十七条の四|住宅借入金|第二百九十四条第一項第二号|第二十四条第一項第二号"
          r"|第二十三条第一項第十五号ロ")
KISOKU_RE = r"家屋敷|配当割額又は株式等譲渡所得割額|第三百十四条の九|第三十七条の四|住宅借入金等特別税額控除|第二百九十四条第一項第二号|第二十四条第一項第二号"

# (略称, 法令名（/laws の law_title 完全一致）, 既知の law_id（None なら検索）, asofs, 本則の条番号, 本則の正規表現, 原始附則の条番号, 原始附則の正規表現)
JOBS = [
    ("chiho", "地方税法", "325AC0000000226", CHIHO_ASOFS, CHIHO_MAIN, CHIHO_MAIN_RE, CHIHO_SUPPL_NUMS, CHIHO_SUPPL_RE),
    # 改正附則のうち、e-Gov が施行前の版では表示しない項を見るための遠い時点（本則は抜き出さない）
    ("chiho-far", "地方税法", "325AC0000000226", ["2030-01-01"], [], None, [], None),
    ("chiho-rei", "地方税法施行令", "325CO0000000245", ["2026-01-01", "2026-11-09", "2027-01-01"], [], REI_RE, [], REI_RE),
    ("chiho-kisoku", "地方税法施行規則", None, ["2026-01-01", "2026-11-09", "2027-01-01"], [], KISOKU_RE, [], KISOKU_RE),
    # 特定配当等の定義（地方税法第23条第1項第15号ロ）が引く租税特別措置法第9条の3、上場株式等の配当等（第8条の4）
    ("sochi", "租税特別措置法", "332AC0000000026", ["2026-11-09"], ["8_4", "9_3"], None, [], None),
]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    if dest is not None:
        dest.write_bytes(body)
    time.sleep(SLEEP)
    return st, body


# ---- R1_egov_articles.py / R2X_juminzei-tax_laws.py から写した描画 ----
def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):
        return ""
    parts = [inline(c) for c in n.get("children", [])]
    if n.get("tag", "").endswith("Sentence") and any(isinstance(c, dict) and c.get("tag") == "Column" for c in n.get("children", [])):
        return "　".join(p for p in parts if p)
    return "".join(parts)


def render(n, depth, lines):
    if isinstance(n, str):
        if n.strip():
            lines.append("  " * depth + n)
        return
    tag = n.get("tag", "")
    ch = n.get("children", [])
    if tag in BLOCK_LIKE:
        title = "".join(inline(c) for c in ch if isinstance(c, dict) and c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
        sent = [c for c in ch if isinstance(c, dict) and c.get("tag", "").endswith("Sentence")]
        body = "　".join(inline(s) for s in sent)
        cap = [inline(c) for c in ch if isinstance(c, dict) and c.get("tag") == "ParagraphCaption"]
        if cap:
            lines.append("  " * depth + cap[0])
        num = n.get("attr", {}).get("Num", "")
        prefix = title if title else (f"（{tag}{num}）" if tag == "Paragraph" else "")
        lines.append("  " * depth + (prefix + "　" if prefix else "") + body)
        for c in ch:
            if isinstance(c, dict) and not (c.get("tag", "").endswith(("Num", "Title", "Sentence")) or c.get("tag") == "ParagraphCaption"):
                render(c, depth + 1, lines)
        return
    if tag == "TableRow":
        cells = [inline(c).replace("\n", " ") for c in ch if isinstance(c, dict)]
        lines.append("  " * depth + "| " + " | ".join(cells) + " |")
        return
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle"):
        lines.append("  " * depth + inline(n))
        return
    for c in ch:
        render(c, depth, lines)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def find_law_id(title, dl, tag, log):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": "2026-11-09"})
    url = f"{API}/laws?{q}"
    st, body = get(url, dl / f"laws_{tag}.json")
    log["lookups"].append({"title": title, "url": url, "status": st})
    if st != 200:
        return None
    data = json.loads(body)
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"]
    return None


def split(root):
    """本則の条、原始附則（AmendLawNum なし）の条、改正附則（AmendLawNum ごと）に分ける。"""
    main_arts, orig_suppl_arts, amend_suppl = [], [], []

    def fn(n, path):
        if n.get("tag") == "Article":
            if "SupplProvision" not in path:
                main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            if not n.get("attr", {}).get("AmendLawNum"):
                walk(n, lambda m, p: orig_suppl_arts.append(m) if m.get("tag") == "Article" else None)
                if not any(isinstance(c, dict) and c.get("tag") == "Article" for c in n.get("children", [])):
                    orig_suppl_arts.append({"tag": "Article", "attr": {"Num": "(no-article)"}, "children": n.get("children", [])})
            else:
                amend_suppl.append(n)
    walk(root, fn)
    if not main_arts:
        mp = []
        walk(root, lambda m, p: mp.append(m) if m.get("tag") == "MainProvision" else None)
        for m in mp:
            main_arts.append({"tag": "Article", "attr": {"Num": "(no-article)"}, "children": m.get("children", [])})
    return main_arts, orig_suppl_arts, amend_suppl


def text_of(n):
    lines = []
    render(n, 0, lines)
    return "\n".join(l.strip() for l in lines)


def sort_key(k):
    kind, num = k.split(":", 1)
    return (kind, [int(p) if p.isdigit() else 10 ** 9 for p in re.split(r"[_:]", num)], num)


def article_diff_md(a_json, b_json, x, y, short):
    keys = sorted(set(a_json) | set(b_json), key=sort_key)
    out = [f"# {short}: {x} → {y} の条ごとの変化", "", "| 条 | 変化 |", "|---|---|"]
    details = []
    for k in keys:
        a, b = a_json.get(k), b_json.get(k)
        if a is None:
            out.append(f"| {k} | 新たに抜き出された（{x} にない、または {x} では正規表現に当たらない） |")
        elif b is None:
            out.append(f"| {k} | 抜き出されない（{y} にない、または {y} では正規表現に当たらない） |")
        elif a == b:
            out.append(f"| {k} | 同じ |")
        else:
            out.append(f"| {k} | **違う** |")
            sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
            details.append(f"\n## {k}\n")
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op == "equal":
                    continue
                ctx_a = a[max(0, i1 - 40):i1].replace("\n", " ")
                details.append(f"- {op}: …{ctx_a}【{a[i1:i2]}】→【{b[j1:j2]}】")
    return "\n".join(out + details) + "\n"


def amend_paragraph_hits(amend_suppl):
    """改正附則の項（Paragraph）のうち AMEND_RE に当たるものを、改正法令の番号・条・項つきで返す。"""
    res = []
    for s in amend_suppl:
        an = s.get("attr", {}).get("AmendLawNum") or ""
        if not re.search(AMEND_LAW_RE, an):
            continue

        def fa(n, path, an=an):
            if n.get("tag") == "Article":
                num = n.get("attr", {}).get("Num")
                for c in n.get("children", []):
                    if isinstance(c, dict) and c.get("tag") == "Paragraph":
                        t = text_of(c)
                        if re.search(AMEND_RE, t):
                            res.append({"amend_law_num": an, "article": num, "caption": caption(n),
                                        "paragraph": c.get("attr", {}).get("Num"), "text": t})
        walk(s, fa)
        # 条のない改正附則（項だけ）
        if not any(isinstance(c, dict) and c.get("tag") == "Article" for c in s.get("children", [])):
            for c in s.get("children", []):
                if isinstance(c, dict) and c.get("tag") == "Paragraph":
                    t = text_of(c)
                    if re.search(AMEND_RE, t):
                        res.append({"amend_law_num": an, "article": "(no-article)", "caption": "",
                                    "paragraph": c.get("attr", {}).get("Num"), "text": t})
    return res


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / NAME
    out.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "only": sorted(only), "lookups": [], "fetches": [], "errors": []}

    for short, title, law_id, asofs, main_nums, main_re, suppl_nums, suppl_re in JOBS:
        if only and short not in only:
            continue
        try:
            if law_id is None:
                law_id = find_law_id(title, dl, short, log)
                if law_id is None:
                    log["errors"].append({"law": title, "error": "law_id not found"})
                    print(f"ERR {short} law_id not found", flush=True)
                    continue
            arts_by_asof = {}
            for asof in asofs:
                q = {"response_format": "json", "asof": asof}
                url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
                st, raw = get(url, dl / f"{short}_{asof}.json")
                if st != 200:
                    log["errors"].append({"law": title, "asof": asof, "status": st, "body": raw[:300].decode("utf-8", "replace")})
                    print(f"ERR {short} {asof} {st}", flush=True)
                    continue
                d = json.loads(raw)
                ri = d.get("revision_info") or {}
                li = d.get("law_info") or {}
                log["fetches"].append({"short": short, "law": title, "law_id": law_id, "law_num": li.get("law_num"), "asof": asof, "url": url,
                                       "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                       "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                                       "amendment_law_title": ri.get("amendment_law_title"),
                                       "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                       "updated": ri.get("updated"),
                                       "current_revision_status": ri.get("current_revision_status")})
                root = d["law_full_text"]
                main_arts, orig_arts, amend_suppl = split(root)
                header = [f"# {title}（{li.get('law_num')}） law_id={law_id} asof={asof}",
                          f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')} updated={ri.get('updated')}",
                          f"# 取得URL={url}", f"# 取得日時={ts}", ""]
                idx = header + ["## 本則"] + [f"{a['attr'].get('Num')}\t{caption(a)}" for a in main_arts]
                idx += ["", "## 原始附則"] + [f"附則{a['attr'].get('Num')}\t{caption(a)}" for a in orig_arts]
                idx += ["", "## 改正附則（AmendLawNum）"] + sorted({s.get('attr', {}).get('AmendLawNum') or "" for s in amend_suppl})
                (out / f"index_{short}_{asof}.txt").write_text("\n".join(idx) + "\n", encoding="utf-8")

                by_num = {a["attr"].get("Num"): a for a in main_arts}
                sby = {a["attr"].get("Num"): a for a in orig_arts}
                chosen_main, chosen_suppl, missing = [], [], []
                for num in main_nums:
                    (chosen_main.append(num) if num in by_num else missing.append(f"本則:{num}"))
                if main_re:
                    for a in main_arts:
                        n = a["attr"].get("Num")
                        if n not in chosen_main and (re.search(main_re, text_of(a)) or re.search(main_re, caption(a))):
                            chosen_main.append(n)
                for num in suppl_nums:
                    (chosen_suppl.append(num) if num in sby else missing.append(f"附則:{num}"))
                if suppl_re:
                    for a in orig_arts:
                        n = a["attr"].get("Num")
                        if n not in chosen_suppl and (re.search(suppl_re, caption(a)) or re.search(suppl_re, text_of(a))):
                            chosen_suppl.append(n)
                lines = list(header)
                arts_json = {}
                for m in missing:
                    lines += [f"## {m}: 見つからない（この時点にない）", ""]
                for num in chosen_main:
                    lines.append(f"## 本則 Num={num}")
                    render(by_num[num], 0, lines)
                    lines.append("")
                    arts_json[f"本則:{num}"] = text_of(by_num[num])
                for num in chosen_suppl:
                    lines.append(f"## 原始附則 Num={num}")
                    render(sby[num], 0, lines)
                    lines.append("")
                    arts_json[f"附則:{num}"] = text_of(sby[num])
                (out / f"{short}_{asof}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                (out / f"{short}_{asof}.articles.json").write_text(json.dumps({"law": title, "law_id": law_id, "asof": asof,
                                                                               "law_revision_id": ri.get("law_revision_id"),
                                                                               "missing": missing,
                                                                               "articles": arts_json}, ensure_ascii=False, indent=1), encoding="utf-8")
                # 語の出現箇所（本則・原始附則・改正附則）
                hits = []
                for kind, arts_ in (("本則", main_arts), ("原始附則", orig_arts)):
                    for a in arts_:
                        t = text_of(a).replace("\n", "")
                        for pat in HIT_PATTERNS:
                            for m in re.finditer(pat, t):
                                hits.append({"pattern": pat, "where": kind, "article": a["attr"].get("Num"), "caption": caption(a),
                                             "snippet": t[max(0, m.start() - 100):m.end() + 60]})
                for s in amend_suppl:
                    t = text_of(s).replace("\n", "")
                    for pat in HIT_PATTERNS:
                        for m in re.finditer(pat, t):
                            hits.append({"pattern": pat, "where": "改正附則", "amend_law_num": s.get("attr", {}).get("AmendLawNum"),
                                         "snippet": t[max(0, m.start() - 100):m.end() + 60]})
                (out / f"hits_{short}_{asof}.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
                # 改正附則の項（適用関係）
                ah = amend_paragraph_hits(amend_suppl)
                md = header + [f"改正附則（AmendLawNum が {AMEND_LAW_RE} に当たるもの）の項のうち、/{AMEND_RE}/ に当たるもの：{len(ah)} 件", ""]
                for h in ah:
                    md += [f"## {h['amend_law_num']} 附則 第{h['article']}条 {h['caption']} 第{h['paragraph']}項", "", h["text"], ""]
                (out / f"amend_{short}_{asof}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
                arts_by_asof[asof] = arts_json
                print(f"ok {short} {asof} {ri.get('law_revision_id')} {ri.get('current_revision_status')} main={len(chosen_main)} suppl={len(chosen_suppl)} hits={len(hits)} amend={len(ah)} missing={missing}", flush=True)
            got = [a for a in asofs if a in arts_by_asof]
            for x, y in zip(got, got[1:]):
                (out / f"diff_{short}_{x}_vs_{y}.md").write_text(article_diff_md(arts_by_asof[x], arts_by_asof[y], x, y, short), encoding="utf-8")
        except Exception as e:  # noqa
            log["errors"].append({"law": title, "error": repr(e)})
            print(f"ERR {short} {e!r}", flush=True)

    (out / ("fetch_log.json" if not only else f"fetch_log_{'_'.join(sorted(only))}.json")).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())
