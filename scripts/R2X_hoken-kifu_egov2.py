"""R2X_hoken-kifu（補足）: scripts/R2X_hoken-kifu_egov.py の結果で見つかった変更について、施行日・適用年分を確かめるために、
中間の時点（asof）の条文と、改正附則（施行期日・適用関係）を e-Gov 法令API v2 で取得する。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_hoken-kifu_egov2.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
テキスト化の関数は scripts/R2X_hoken-kifu_egov.py（＝ scripts/R1_egov_articles.py の写し）と同じものを写した（import しない）。

確かめること（JOBS を参照）
- 措法第41条の15の5 が入った時点と、その後の文言の変化（2026-01-01、2026-03-31、2026-04-01）。附則でこの条に触れるもの
- 所法第78条の変更（特定公益信託 → 公益信託）が入った時点（2026-03-31、2026-04-01）と、その改正附則
- 所令第205条（雑損控除の親族の所得要件）の改正附則
- 地方税法第314条の7・第37条の2（ふるさと納税の特例控除額）の変更の時点と、改正附則の適用年度。原始附則第5条の4〜第7条の3
- 地方税法第317条の3・第45条の3（確定申告書の提出による住民税の申告のみなし）
- 地方税法施行令のうち、雑損控除の親族（地方税法第314条の2第1項第1号の「政令で定めるもの」）を定める条
- 所得税法 第2条（第37号 確定申告書の定義）・第121条・第122条。附則のうち措法第41条の15の5 に触れるもの
- 所得税法・所得税法施行令の「一円未満」の全文検索（生命保険料控除・地震保険料控除の端数の根拠を探す）、所得税法第120条〜第127条の所属（編・章・節・款）
- 地方税法 原始附則第7条の2（申告特例控除額）の 2026-01-01〜2026-04-01 の文言、地方税法施行令の雑損控除の親族の額（2027-01-01）
出力：scripts/results/R2X_hoken-kifu_egov2/
ダウンロードした JSON は .work/downloads/<ts>_R2X_hoken-kifu_egov2/ に置く（信頼できないデータ。中でコードを実行しない）。
"""
import hashlib
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5

# (略称, law_id, asof, [本則の条 Num], [原始附則の条 Num], [附則（改正附則を含む）から、本文にこの文字列を含む条を取り出す], [全文検索する文字列])
JOBS = [
    ("sochi", "332AC0000000026", "2026-01-01", ["41_15_5"], [], [], []),
    ("sochi", "332AC0000000026", "2026-03-31", ["41_15_5"], [], [], []),
    ("sochi", "332AC0000000026", "2026-04-01", ["41_15_5"], [], ["四十一条の十五の五"], []),
    ("sochi", "332AC0000000026", "2026-11-09", [], [], ["四十一条の十五の五", "生命保険料控除"], []),
    ("shotoku", "340AC0000000033", "2026-03-31", ["78"], [], [], []),
    ("shotoku", "340AC0000000033", "2026-04-01", ["2", "78", "121", "122"], [], ["第七十八条", "特定公益信託", "四十一条の十五の五"], ["一円未満"]),
    ("shotoku-rei", "340CO0000000096", "2026-12-31", [], [], ["第二百五条"], ["一円未満"]),
    ("shotoku-rei", "340CO0000000096", "2025-12-31", [], [], ["第二百五条"], []),
    ("chiho", "325AC0000000226", "2026-01-01", ["37_2", "314_2", "314_7"], ["7_2"], [], []),
    ("chiho", "325AC0000000226", "2026-03-31", ["314_7"], ["7_2"], [], []),
    ("chiho", "325AC0000000226", "2026-04-01", ["314_7"], ["7_2"], [], []),
    ("chiho", "325AC0000000226", "2027-01-01", ["45_3", "317_3", "314_3", "314_6"],
     ["5_4", "5_4_2", "5_5", "5_6", "5_6_2", "5_7", "7", "7_2", "7_3"],
     ["三百十四条の七", "三十七条の二第十一項", "寄附金税額控除", "申告特例"],
     ["八十四・八九五", "百分の八十四", "百十五万八千円", "二十三歳未満"]),
    ("chiho-rei", "325CO0000000245", "2026-11-09", [], [], [], ["第三百十四条の二第一項第一号", "雑損控除", "長期損害保険"]),
    ("chiho-rei", "325CO0000000245", "2027-01-01", [], [], ["第四十八条の六", "第七条の十三の三"], ["第三百十四条の二第一項第一号に規定する政令で定める親族", "法第三十四条第一項第一号に規定する政令で定める親族"]),
]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    time.sleep(SLEEP)
    return st, body


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
            walk(c, fn, path + (n,))


def text_of(node):
    lines = []
    render(node, 0, lines)
    return lines


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_hoken-kifu_egov2"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_hoken-kifu_egov2"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": []}
    for short, law_id, asof, arts, orig_suppl, suppl_text, fulltext in JOBS:
        q = {"response_format": "json", "asof": asof}
        url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
        st, body = get(url)
        (dl / f"{law_id}_{asof}.json").write_bytes(body)
        if st != 200:
            log["fetches"].append({"short": short, "asof": asof, "url": url, "status": st})
            print("NG", short, asof, st, flush=True)
            continue
        d = json.loads(body)
        ri = d.get("revision_info") or {}
        entry = {"short": short, "law_id": law_id, "asof": asof, "url": url, "law_title": ri.get("law_title"),
                 "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                 "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                 "current_revision_status": ri.get("current_revision_status"),
                 "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "article_sha256": {}}
        print("ok", short, asof, ri.get("law_revision_id"), flush=True)
        root = d["law_full_text"]
        main_arts, suppl = [], []

        def collect(n, path):
            tags = [p.get("tag") for p in path]
            if n.get("tag") == "Article" and "SupplProvision" not in tags:
                main_arts.append(n)
            if n.get("tag") == "SupplProvision":
                suppl.append(n)
        walk(root, collect)
        lines = [f"# {short} {law_id} asof={asof}",
                 f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                 f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                 f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
        by_num = {a["attr"].get("Num"): a for a in main_arts}
        for num in arts:
            a = by_num.get(num)
            if a is None:
                lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                entry["article_sha256"][f"本則:{num}"] = None
                continue
            tl = text_of(a)
            entry["article_sha256"][f"本則:{num}"] = hashlib.sha256("\n".join(tl).encode("utf-8")).hexdigest()
            lines.append(f"## 本則 Num={num}")
            lines += tl
            lines.append("")
        orig = [s for s in suppl if "AmendLawNum" not in (s.get("attr") or {})]
        for num in orig_suppl:
            hit = None
            for s in orig:
                for a in s.get("children", []):
                    if isinstance(a, dict) and a.get("tag") == "Article" and (a.get("attr") or {}).get("Num") == num:
                        hit = a
            if hit is None:
                lines += [f"## 原始附則 Num={num}: 見つからない", ""]
                continue
            tl = text_of(hit)
            entry["article_sha256"][f"原始附則:{num}"] = hashlib.sha256("\n".join(tl).encode("utf-8")).hexdigest()
            lines.append(f"## 原始附則 Num={num}")
            lines += tl
            lines.append("")
        if suppl_text:
            seen = set()
            lines.append("# ---- 附則（改正附則を含む）のうち、本文に次の文字列を含む条：" + "、".join(suppl_text))
            for s in suppl:
                an = (s.get("attr") or {}).get("AmendLawNum", "(原始附則)")
                if an == "(原始附則)":
                    continue
                kids = [a for a in s.get("children", []) if isinstance(a, dict) and a.get("tag") in ("Article", "Paragraph")]
                for a in kids:
                    tl = text_of(a)
                    joined = "\n".join(tl)
                    hits = [kw for kw in suppl_text if kw in joined]
                    if not hits:
                        continue
                    key = (an, (a.get("attr") or {}).get("Num"), a.get("tag"))
                    if key in seen:
                        continue
                    seen.add(key)
                    lines.append(f"## 附則 AmendLawNum={an} {a.get('tag')} Num={key[1]}（含む語：{'、'.join(hits)}）")
                    lines += tl
                    lines.append("")
        if fulltext:
            lines.append("# ---- 全文検索：" + "、".join(fulltext))
            found = []

            def fn(n, path):
                if n.get("tag") == "Sentence":
                    t = inline(n)
                    for kw in fulltext:
                        i = t.find(kw)
                        if i >= 0:
                            part, an, art, para = "本則", None, None, None
                            for p in list(path):
                                if p.get("tag") == "SupplProvision":
                                    part = "附則"
                                    an = (p.get("attr") or {}).get("AmendLawNum", "(原始附則)")
                                if p.get("tag") == "Article":
                                    art = (p.get("attr") or {}).get("Num")
                                if p.get("tag") == "Paragraph":
                                    para = (p.get("attr") or {}).get("Num")
                            found.append(f"[{kw}] {part} {an or ''} 条={art} 項={para}：…{t[max(0, i - 150): i + 250]}…")
            walk(root, fn)
            lines += found if found else ["（該当なし）"]
            lines.append("")
        if short == "shotoku" and asof == "2026-04-01":
            lines.append("# ---- 条の所属（編・章・節・款）：第120条〜第127条")
            want = {"120", "121", "122", "123", "124", "125", "126", "127"}

            def anc(n, path):
                if n.get("tag") == "Article" and (n.get("attr") or {}).get("Num") in want and not any(p.get("tag") == "SupplProvision" for p in path):
                    titles = []
                    for p in path:
                        t = p.get("tag")
                        if t in ("Part", "Chapter", "Section", "Subsection", "Division"):
                            for c in p.get("children", []):
                                if isinstance(c, dict) and c.get("tag") == t + "Title":
                                    titles.append(inline(c))
                    lines.append(f"第{(n.get('attr') or {}).get('Num')}条：" + " ／ ".join(titles))
            walk(root, anc)
            lines.append("")
        (out / f"articles_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
        log["fetches"].append(entry)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())
