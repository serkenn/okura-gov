"""R2X_kyosai: e-Gov 法令API v2 で、共済組合の被扶養者の定義と、住民税の納税義務者・扶養親族の条文を取得する。

実行:
  python -I -X utf8 scripts/R2X_kyosai_egov.py index   # law_id を引き、今日の版の条の見出しの索引と語句の走査だけを作る
  python -I -X utf8 scripts/R2X_kyosai_egov.py         # 指定した条を時点（asof）ごとに抜き出し、版の間の差分をとり、語句を走査する

- 標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。
- ダウンロードした JSON は .work/downloads/<ts>_R2X_kyosai_egov/ に置く（信頼できないデータ。その中でコードを実行しない）。
- 結果は scripts/results/R2X_kyosai_egov/ に書く：
    law_ids.json                         法令名 → law_id（/laws?law_title= で引いた結果）
    index/<略称>_<asof>.md                条番号と見出しの一覧（index モード）
    index/<略称>_<asof>_toc.md            章・節・款ごとの最初・最後の条番号（full モード、今日の版）
    articles/<略称>_<asof>.txt           抜き出した条（版の情報つき）
    diff/<略称>_<asof1>_vs_<asof2>.diff
    scan/<略称>_<asof>.md / .json        語句の走査結果（場所・項・前後の文）
    fetch_log_<mode>.json                取得記録（URL、law_revision_id、改正法令、施行日、SHA-256）
scripts/IMPL_kenpo_egov.py と scripts/IMPL_jigyo_laws.py のコードを写して作った（import はしていない）。
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
WAIT = 1.5
OUT = ROOT / "scripts" / "results" / "R2X_kyosai_egov"
TODAY = "2026-11-09"

# 時点の選び方
#   2025-10-01：19歳以上23歳未満150万円（健保の通知）の適用日
#   2026-01-01：令和8年度分の住民税の賦課期日
#   2026-04-01：労働契約による判定（健保の通知）の適用日
#   2026-11-09：今日
#   2027-01-01：令和9年度分の住民税の賦課期日（2026-11-09 時点で成立している改正までを反映した版）
KYOSAI_ASOFS = ["2025-10-01", "2026-04-01", TODAY]
CHIZEI_ASOFS = ["2026-01-01", TODAY, "2027-01-01"]

SCAN_DEP = [r"被扶養者", r"同一の世帯", r"世帯に属", r"生計を維持", r"主としてその"]
SCAN_CHIZEI = [r"住所を有する", r"住所を有しない", r"家屋敷", r"扶養親族", r"生計を一に", r"同居", r"賦課期日",
               r"住民基本台帳に記録", r"住所所在地"]

# (略称, 法令名, [抜き出す本則の条番号（Article@Num）], [走査する正規表現], [asof...])
JOBS = [
    # 条番号は index モードの見出しと走査の結果から選んだ（scripts/results/R2X_kyosai_egov/index/）
    ("kokkyo", "国家公務員共済組合法", ["2", "53"], SCAN_DEP, KYOSAI_ASOFS),
    ("kokkyo-rei", "国家公務員共済組合法施行令", ["1", "3"], SCAN_DEP, KYOSAI_ASOFS),
    ("kokkyo-ki", "国家公務員共済組合法施行規則", ["2", "2_5", "88"], SCAN_DEP, KYOSAI_ASOFS),
    ("chikyo", "地方公務員等共済組合法", ["2", "55"], SCAN_DEP, KYOSAI_ASOFS),
    ("chikyo-rei", "地方公務員等共済組合法施行令", ["3"], SCAN_DEP, KYOSAI_ASOFS),
    ("chikyo-kitei", "地方公務員等共済組合法施行規程", ["2", "2_3", "94", "97", "100"], SCAN_DEP, KYOSAI_ASOFS),
    ("shigaku", "私立学校教職員共済法", ["14", "25"], SCAN_DEP, KYOSAI_ASOFS),
    ("shigaku-rei", "私立学校教職員共済法施行令", ["3"], SCAN_DEP, KYOSAI_ASOFS),
    ("shigaku-ki", "私立学校教職員共済法施行規則", ["1_4_2", "1_5"], SCAN_DEP, KYOSAI_ASOFS),
    ("kyuyo", "一般職の職員の給与に関する法律", ["11"], [r"扶養親族", r"扶養手当"], [TODAY]),
    ("kenpo", "健康保険法", ["3"], SCAN_DEP, KYOSAI_ASOFS),
    ("kenpo-ki", "健康保険法施行規則", ["37_2", "38"], SCAN_DEP, [TODAY]),
    ("chizei", "地方税法", ["23", "24", "39", "292", "294", "314_2", "317_2", "317_6", "318"], SCAN_CHIZEI, CHIZEI_ASOFS),
    ("chijiho", "地方自治法", ["10"], [r"住所を有する者"], [TODAY]),
    ("jumin", "住民基本台帳法", ["4", "6", "7"], [r"住所"], [TODAY]),
    # 取扱通知（市町村税）第2章第1節第1の6(5) が引く「公務員の国内住所のみなし」の条
    ("shotoku", "所得税法", ["3"], [r"国内に住所を有するものとみな"], [TODAY]),
]


def get(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    dest.write_bytes(body)
    time.sleep(WAIT)
    return st, body


def text_of(node):
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("tag") == "Rt":  # ルビの読みは捨てる
        return ""
    return "".join(text_of(c) for c in node.get("children", []))


def child(node, tag):
    for c in node.get("children", []):
        if isinstance(c, dict) and c.get("tag") == tag:
            return c
    return None


def iter_tag(node, tag):
    if isinstance(node, dict):
        if node.get("tag") == tag:
            yield node
        for c in node.get("children", []):
            yield from iter_tag(c, tag)


def render(node, depth=0, out=None):
    """条文の構造を、行ごとのテキストにする（項・号・イロハの字下げつき）。IMPL_kenpo_egov.py から写した。"""
    if out is None:
        out = []
    if not isinstance(node, dict):
        return out
    tag = node.get("tag", "")
    ind = "  " * depth
    if tag == "Article":
        cap = child(node, "ArticleCaption")
        tit = child(node, "ArticleTitle")
        out.append(f"{ind}{text_of(cap) if cap else ''}")
        out.append(f"{ind}{text_of(tit) if tit else ''}")
        for c in node.get("children", []):
            if isinstance(c, dict) and c.get("tag") == "Paragraph":
                render(c, depth, out)
        return out
    if tag == "Paragraph":
        num = child(node, "ParagraphNum")
        sen = child(node, "ParagraphSentence")
        out.append(f"{ind}[項{node.get('attr', {}).get('Num', '')}] {text_of(num) if num else ''} {text_of(sen) if sen else ''}".rstrip())
        for c in node.get("children", []):
            if isinstance(c, dict) and c.get("tag") not in ("ParagraphNum", "ParagraphSentence", "ParagraphCaption"):
                render(c, depth + 1, out)
        return out
    m = re.fullmatch(r"(Item|Subitem\d+)", tag)
    if m:
        t = child(node, f"{tag}Title")
        s = child(node, f"{tag}Sentence")
        sent = ""
        if s:
            parts = [text_of(c) for c in s.get("children", []) if isinstance(c, (dict, str))]
            sent = "　".join(p for p in parts if p)
        out.append(f"{ind}{text_of(t) if t else ''} {sent}".rstrip())
        for c in node.get("children", []):
            if isinstance(c, dict) and c.get("tag") not in (f"{tag}Title", f"{tag}Sentence"):
                render(c, depth + 1, out)
        return out
    if tag == "TableStruct":
        for row in iter_tag(node, "TableRow"):
            cells = [text_of(c) for c in row.get("children", []) if isinstance(c, dict)]
            out.append(f"{ind}| " + " | ".join(cells) + " |")
        return out
    for c in node.get("children", []):
        render(c, depth, out)
    return out


def toc(full):
    """本則の章（Chapter）ごとに、見出しと最初・最後の条番号を返す（章がない法令は空）。"""
    mp = next(iter_tag(full, "MainProvision"), None)
    rows = []
    for ch in (c for c in (mp or {}).get("children", []) if isinstance(c, dict) and c.get("tag") == "Chapter"):
        t = child(ch, "ChapterTitle")
        nums = [a.get("attr", {}).get("Num") for a in iter_tag(ch, "Article")]
        rows.append(f"| {text_of(t) if t else ''} | {nums[0] if nums else ''} | {nums[-1] if nums else ''} | {len(nums)} |")
        # 節（Section）と款（Subsection）も、章の中の行として書く（準用の範囲の確認に使う）
        for sec in (c for c in ch.get("children", []) if isinstance(c, dict) and c.get("tag") == "Section"):
            st = child(sec, "SectionTitle")
            sn = [a.get("attr", {}).get("Num") for a in iter_tag(sec, "Article")]
            rows.append(f"| 　{text_of(st) if st else ''} | {sn[0] if sn else ''} | {sn[-1] if sn else ''} | {len(sn)} |")
            for sub in (c for c in sec.get("children", []) if isinstance(c, dict) and c.get("tag") == "Subsection"):
                bt = child(sub, "SubsectionTitle")
                bn = [a.get("attr", {}).get("Num") for a in iter_tag(sub, "Article")]
                rows.append(f"| 　　{text_of(bt) if bt else ''} | {bn[0] if bn else ''} | {bn[-1] if bn else ''} | {len(bn)} |")
    return rows


def main_articles(full):
    mp = next(iter_tag(full, "MainProvision"), None)
    return list(iter_tag(mp, "Article")) if mp else []


def walk_units(full):
    """本則の条と、附則（SupplProvision）の条・項を、(場所の名前, ノード) の組で返す。"""
    units = []
    mp = next(iter_tag(full, "MainProvision"), None)
    if mp:
        arts = list(iter_tag(mp, "Article"))
        units += [(f"本則 第{a.get('attr', {}).get('Num')}条", a) for a in arts] or [("本則", mp)]
    for sp in iter_tag(full, "SupplProvision"):
        label = sp.get("attr", {}).get("AmendLawNum") or "原始附則"
        arts = list(iter_tag(sp, "Article"))
        if arts:
            units += [(f"附則({label}) 第{a.get('attr', {}).get('Num')}条", a) for a in arts]
        else:
            units.append((f"附則({label})", sp))
    return units


def scan(full, patterns):
    hits = []
    for where, node in walk_units(full):
        paras = list(iter_tag(node, "Paragraph")) or [node]
        for p in paras:
            t = text_of(p)
            pnum = p.get("attr", {}).get("Num", "") if p.get("tag") == "Paragraph" else ""
            for pat in patterns:
                for mt in re.finditer(pat, t):
                    s = max(0, mt.start() - 60)
                    hits.append({"where": where, "paragraph": pnum, "pattern": pat,
                                 "snippet": t[s:mt.end() + 60].replace("\n", " ")})
    return hits


def find_law_id(title, dl, idx):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    url = f"{API}/laws?{q}"
    st, body = get(url, dl / f"{idx:02d}_laws_search.json")
    if st != 200:
        return None, None, url, st
    data = json.loads(body)
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"], law["law_info"].get("law_num"), url, st
    return None, None, url, st


def rev_info(d):
    ri = d.get("revision_info") or {}
    return {k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title", "amendment_enforcement_date",
                                   "amendment_promulgate_date", "current_revision_status", "updated")}


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    mode = argv[0] if argv else "full"
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_kyosai_egov"
    dl.mkdir(parents=True, exist_ok=False)
    for sub in ("index", "articles", "diff", "scan"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    log = {"mode": mode, "fetched_at_local": ts, "download_dir": str(dl.relative_to(ROOT)), "lookups": [], "fetches": [], "errors": []}
    ids_path = OUT / "law_ids.json"
    ids = json.loads(ids_path.read_text(encoding="utf-8")) if ids_path.exists() else {}
    n = 0
    for short, title, arts, pats, asofs in JOBS:
        if title not in ids or mode == "index":
            n += 1
            law_id, law_num, url, st = find_law_id(title, dl, n)
            log["lookups"].append({"title": title, "law_id": law_id, "law_num": law_num, "url": url, "status": st})
            if not law_id:
                log["errors"].append({"short": short, "error": f"law_id not found ({st})"})
                print("NOT FOUND", title, st, flush=True)
                continue
            ids[title] = {"law_id": law_id, "law_num": law_num, "lookup_url": url, "looked_up_at": ts}
        law_id = ids[title]["law_id"]
        use_asofs = [TODAY] if mode == "index" else asofs
        texts = {}
        for asof in use_asofs:
            q = urllib.parse.urlencode({"response_format": "json", "asof": asof})
            url = f"{API}/law_data/{law_id}?{q}"
            dest = dl / f"{short}_{asof}.json"
            st, body = get(url, dest)
            rec = {"short": short, "law": title, "law_id": law_id, "asof": asof, "url": url, "status": st,
                   "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            if st != 200:
                rec["error"] = body[:300].decode("utf-8", "replace")
                log["fetches"].append(rec)
                print("ERR", short, asof, st, flush=True)
                continue
            d = json.loads(body)
            ri = rev_info(d)
            rec.update(ri)
            log["fetches"].append(rec)
            full = d["law_full_text"]
            header = [f"# {title} {law_id} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", ""]
            if mode == "index":
                rows = []
                for a in main_articles(full):
                    cap = child(a, "ArticleCaption")
                    tit = child(a, "ArticleTitle")
                    rows.append(f"| {a.get('attr', {}).get('Num')} | {text_of(tit) if tit else ''} | {text_of(cap) if cap else ''} |")
                (OUT / "index" / f"{short}_{asof}.md").write_text("\n".join(header + ["| Num | 条 | 見出し |", "|---|---|---|"] + rows) + "\n", encoding="utf-8")
            else:
                by_num = {a.get("attr", {}).get("Num"): a for a in main_articles(full)}
                lines = []
                for num in arts:
                    a = by_num.get(num)
                    if a is None:
                        lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                        continue
                    lines.append(f"## Num={num}")
                    lines += render(a)
                    lines.append("")
                texts[asof] = "\n".join(lines)
                if asof == TODAY:
                    rows = toc(full)
                    if rows:
                        (OUT / "index" / f"{short}_{asof}_toc.md").write_text(
                            "\n".join(header + ["| 章 | 最初の条 | 最後の条 | 条の数 |", "|---|---|---|---|"] + rows) + "\n", encoding="utf-8")
                if arts:
                    (OUT / "articles" / f"{short}_{asof}.txt").write_text("\n".join(header) + texts[asof] + "\n", encoding="utf-8")
            hits = scan(full, pats)
            (OUT / "scan" / f"{short}_{asof}.json").write_text(json.dumps({"law": title, "asof": asof, "law_revision_id": ri.get("law_revision_id"),
                                                                           "patterns": pats, "hits": hits}, ensure_ascii=False, indent=1), encoding="utf-8")
            md = header + [f"走査パターン: {pats}", f"該当: {len(hits)} 件", "", "| 場所 | 項 | パターン | 前後の文 |", "|---|---|---|---|"]
            md += [f"| {h['where']} | {h['paragraph']} | `{h['pattern']}` | {h['snippet'].replace('|', '｜')} |" for h in hits]
            (OUT / "scan" / f"{short}_{asof}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
            print("ok", short, asof, ri.get("law_revision_id"), "hits", len(hits), flush=True)
        ks = sorted(texts)
        for x, y in zip(ks, ks[1:]):
            if not arts:
                continue
            diff = "\n".join(difflib.unified_diff(texts[x].splitlines(), texts[y].splitlines(), f"{short}@{x}", f"{short}@{y}", lineterm=""))
            (OUT / "diff" / f"{short}_{x}_vs_{y}.diff").write_text((diff or "(差分なし)") + "\n", encoding="utf-8")
    ids_path.write_text(json.dumps(ids, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"fetch_log_{mode}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
