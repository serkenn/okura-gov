"""IMPL_iryohi: e-Gov 法令API v2 で、医療費控除・セルフメディケーション税制に関係する条文を、指定した時点（asof）の版で取り出す。

実行（Windows では pyenv のシムを通さずに実体の python.exe を使う）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_iryohi_egov.py

- 書き方は scripts/R1_egov_articles.py（取得と描画）と scripts/R4_fetch_laws.py（法令名からの law_id の検索）を写したもの（import はしない）。
- ダウンロードした JSON は .work/downloads/<ts>_IMPL_iryohi_egov/ に置く（信頼できないデータ。その中でコードを実行しない）。
- 取り出した条文は scripts/results/IMPL_iryohi_egov/<略称>_<asof>.txt、取得の記録は fetch_log.json に書く。
- 「第七十三条」を読み替える措置法の規定（総所得金額等に分離課税の所得を含める規定）の出現箇所は sochi_ref73_<asof>.txt に書く。
- 標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
"""
import hashlib
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
TODAY = "2026-11-09"

# asof の意味：2025-12-31 = 令和7年分の年末時点、2026-11-09 = 取得日（現行）、
# 2026-12-31 = 令和8年分の年末時点（取得日には未施行の改正を含む。今後の改正で変わりうる）、2027-01-01 = 令和9年分の初日
ASOFS = ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]
R8 = "令和八年三月三一日法律第一二号"
R7 = "令和七年三月三一日法律第一三号"

# (略称, 法令名（law_id を検索で求める）または law_id, asof のリスト, 本則の条番号, 見出しの正規表現, 附則を探すキーワード)
JOBS = [
    ("shotoku", "340AC0000000033", ASOFS, ["22", "73", "87", "120"], None, None),
    ("shotoku-rei", "340CO0000000096", ASOFS, ["207", "262"], r"医療費", None),
    ("shotoku-ki", "所得税法施行規則", ASOFS, ["40_3", "47_2"], r"医療費|医薬品", None),
    ("sochi", "332AC0000000026", ASOFS, ["41_17"], None, r"第四十一条の十七"),
    ("sochi-rei", "租税特別措置法施行令", ASOFS, [], r"一般用医薬品|医療費控除", r"第二十六条の二十七の二|第四十一条の十七"),
    ("sochi-ki", "租税特別措置法施行規則", ASOFS, [], r"一般用医薬品|医療費控除", r"第十九条の十の二|第四十一条の十七"),
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


# ---- 以下の inline / render / walk / article_caption は scripts/R1_egov_articles.py の写し ----
def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):  # ルビの読みは落とす
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


def article_caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""
# ---- 写しここまで ----


def find_law_id(title, dl, log):
    """scripts/R4_fetch_laws.py の find_law_id の写し（法令名の完全一致で law_id を選ぶ）。"""
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    url = f"{API}/laws?{q}"
    st, body = get(url, dl / f"laws_search_{len(log['searches']):02d}.json")
    data = json.loads(body)
    hit = None
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            hit = (law["law_info"]["law_id"], law["law_info"].get("law_num"))
            break
    log["searches"].append({"title": title, "url": url, "status": st, "hit": hit})
    return hit[0] if hit else None


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_iryohi_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_iryohi_egov"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "user_agent": UA, "searches": [], "fetches": []}
    for short, ident, asofs, nums, cap_re, suppl_kw in JOBS:
        law_id = ident if re.fullmatch(r"[0-9A-Z]+", ident) else find_law_id(ident, dl, log)
        if not law_id:
            log["fetches"].append({"short": short, "error": f"law_id not found for {ident}"})
            continue
        for asof in asofs:
            q = {"response_format": "json", "asof": asof}
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
            dest = dl / f"{short}_{asof}.json"
            st, body = get(url, dest)
            rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st,
                   "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            if st != 200:
                rec["error"] = body[:300].decode("utf-8", "replace")
                log["fetches"].append(rec)
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            rec.update({"law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                        "amendment_law_num": ri.get("amendment_law_num"),
                        "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                        "current_revision_status": ri.get("current_revision_status")})
            root = d["law_full_text"]
            main_arts, suppl = [], []

            def collect(n, path):
                if n.get("tag") == "Article" and "SupplProvision" not in path:
                    main_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            header = [f"# {short} {law_id} {ri.get('law_title')} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 本文JSONの SHA-256={rec['sha256']}", ""]
            lines = list(header)
            picked = []
            for a in main_arts:
                num = a.get("attr", {}).get("Num", "")
                cap = article_caption(a)
                if num in nums or (cap_re and re.search(cap_re, cap)):
                    picked.append(num)
                    lines.append(f"## Num={num}")
                    render(a, 0, lines)
                    lines.append("")
            missing = [n for n in nums if n not in picked]
            for n in missing:
                lines += [f"## Num={n}: 見つからない（この時点の本則にない）", ""]
            rec["articles"] = picked
            rec["missing"] = missing
            if suppl_kw:
                hits = 0
                lines.append(f"# 附則のうち本文に /{suppl_kw}/ を含む条（改正法令ごと）")
                for s in suppl:
                    amend = s.get("attr", {}).get("AmendLawNum", "(原始附則)")
                    arts = []
                    walk(s, lambda n, p: arts.append(n) if n.get("tag") == "Article" else None)
                    for a in arts:
                        t = inline(a)
                        if re.search(suppl_kw, t):
                            hits += 1
                            lines.append(f"## 附則 AmendLawNum={amend} Num={a.get('attr', {}).get('Num')}")
                            render(a, 0, lines)
                            lines.append("")
                rec["suppl_hits"] = hits
            (out / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            if short == "sochi":
                # 措置法の本則で「第七十三条」に触れる箇所（読替え規定）を前後つきで書き出す
                ref = list(header)
                for a in main_arts:
                    t = inline(a)
                    for m in re.finditer(r"第七十三条", t):
                        s0 = max(0, m.start() - 160)
                        ref.append(f"## Num={a.get('attr', {}).get('Num')} {article_caption(a)} @{m.start()}")
                        ref.append(t[s0:m.end() + 220])
                        ref.append("")
                (out / f"sochi_ref73_{asof}.txt").write_text("\n".join(ref), encoding="utf-8")
            log["fetches"].append(rec)
            print(json.dumps({k: rec.get(k) for k in ("short", "asof", "status", "law_revision_id", "current_revision_status", "articles", "missing", "suppl_hits")}, ensure_ascii=False))
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
