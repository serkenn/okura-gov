"""R2X_gaps: 残っていた個別の未解決のうち、法令の条文で確かめるものを e-Gov 法令API v2 で版ごとに取り出す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_gaps_egov.py

対象
- 所得税法（340AC0000000033）：第2条第1項第32号（勤労学生）、第86条（基礎控除）、第120条（確定所得申告。項の番号の確認用）
- 所得税法施行規則（340M50000040011）：第47条の3（事業所得等に係る総収入金額及び必要経費の内訳書）と、各版の改正法令の附則
- 租税特別措置法（332AC0000000026）：見出しに「所得金額調整控除」を含む条（本文に「所得金額調整控除」を含む条の一覧も）
- 租税特別措置法施行令（332CO0000000043）・同施行規則：本文に「所得金額調整控除」または措法の条番号を含む条
- 地方税法（325AC0000000226）：本文に「所得金額調整控除」を含む条（本則・原始附則）。住民税の対応規定の場所の確認用
- 所得税法施行規則・租税特別措置法の改正履歴（/law_revisions、2025-01-01 以後）

- scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py のコードを写して作った（import はしない）。標準ライブラリのみ。
- 本文（JSON）は .work/downloads/<YYYYMMDD-HHMMSS>_R2X_gaps_egov/ に置く（信頼できないデータ。中で何も実行しない）。
- 出力は scripts/results/R2X_gaps_egov/：
  - <略称>_asof<日付>.txt   選んだ条（項・号の構造つき）と、その版の改正法令の附則。先頭に law_revision_id・施行日・取得URL・SHA-256
  - <略称>_diff_<日付1>_vs_<日付2>.diff   版の間の差分（選んだ条の部分だけ）
  - kw_<略称>_asof<日付>.json   キーワードを含む条の一覧（本則／附則、条番号、見出し）
  - lookup.json   法令名からの law_id の検索結果
  - revisions_<略称>.json   改正履歴
  - fetch_log.json   取得の記録
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。
"""
import difflib
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
OUT = ROOT / "scripts" / "results" / "R2X_gaps_egov"

KW_CHOSEI = ["所得金額調整控除", "第四十一条の三の十一", "第四十一条の三の三"]

# (略称, law_id（None なら lookup の結果を使う）, [asof...], {選び方})
#   arts: 本則の条番号（Num 属性）
#   items: (条Num, 項Num, 号Num) の号だけを取り出す
#   caption_kw: 見出しにこの語を含む条（本則・原始附則）を取り出す
#   text_kw: 本文にこの語を含む条（本則・原始附則）を取り出す
#   amend_suppl: その版の改正法令（revision_info の amendment_law_num）の附則を取り出すか
JOBS = [
    ("shotoku", "340AC0000000033", ["2025-12-31", "2026-12-31", "2027-01-01"],
     {"arts": ["86", "120"], "items": [("2", "1", "32")], "amend_suppl": False}),
    ("shotoku-ki", "340M50000040011", ["2026-11-09", "2026-12-31", "2027-01-01"],
     {"arts": ["47_3"], "amend_suppl": True}),
    ("sochi", "332AC0000000026", ["2024-12-31", "2025-12-31", "2026-12-31", "2027-01-01"],
     {"caption_kw": ["所得金額調整控除"], "kw_list": KW_CHOSEI, "amend_suppl": False}),
    ("sochi-rei", "332CO0000000043", ["2025-12-31", "2026-12-31"],
     {"text_kw": KW_CHOSEI, "kw_list": KW_CHOSEI, "amend_suppl": False}),
    ("sochi-ki", None, ["2025-12-31", "2026-12-31"],
     {"text_kw": KW_CHOSEI, "kw_list": KW_CHOSEI, "amend_suppl": False}),
    ("chiho", "325AC0000000226", ["2026-01-01", "2027-01-01"],
     {"text_kw": ["所得金額調整控除"], "kw_list": ["所得金額調整控除"], "amend_suppl": False}),
]
LOOKUP = {"sochi-ki": "租税特別措置法施行規則"}
REVISIONS = [("shotoku-ki", "340M50000040011"), ("sochi", "332AC0000000026"), ("shotoku", "340AC0000000033")]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url, accept="application/json", tries=3):
    """取得する。読み取りのタイムアウト・接続の失敗は、間を空けて最大 tries 回まで試す（1回目の実行で措令の取得がタイムアウトしたため）。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                body, st = r.read(), r.status
            break
        except urllib.error.HTTPError as e:
            body, st = e.read(), e.code
            break
        except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
            print("retry", i + 1, url, repr(e), flush=True)
            if i == tries - 1:
                raise
            time.sleep(SLEEP * 10)
    time.sleep(SLEEP)
    return st, body


# ---- テキスト化（scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py の inline / render を写したもの） ----
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


def caption_of(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def article_text(a):
    ls = []
    render(a, 0, ls)
    return "\n".join(ls)


def child(n, tag, num):
    for c in n.get("children", []):
        if isinstance(c, dict) and c.get("tag") == tag and (c.get("attr") or {}).get("Num") == num:
            return c
    return None


def fetch_full(law_id, asof, dl):
    q = {"response_format": "json", "asof": asof}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, body, json.loads(body)


def lookup_law_id(title, dl, log):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json"})
    url = f"{API}/laws?{q}"
    st, body = get(url)
    (dl / f"lookup_{len(log)}.json").write_bytes(body)
    res = {"title": title, "url": url, "status": st, "candidates": []}
    if st == 200:
        for law in json.loads(body).get("laws", []):
            li = law.get("law_info") or {}
            ri = law.get("revision_info") or law.get("current_revision_info") or {}
            res["candidates"].append({"law_id": li.get("law_id"), "law_num": li.get("law_num"),
                                      "law_title": ri.get("law_title")})
    log.append(res)
    exact = [c for c in res["candidates"] if c["law_title"] == title]
    return exact[0]["law_id"] if exact else None


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_gaps_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "revisions": []}
    lookups = []
    ids = {}
    for short, title in LOOKUP.items():
        ids[short] = lookup_law_id(title, dl, lookups)
        print("lookup", short, ids[short], flush=True)
    (OUT / "lookup.json").write_text(json.dumps(lookups, ensure_ascii=False, indent=1), encoding="utf-8")

    for short, law_id, asofs, sel in JOBS:
        law_id = law_id or ids.get(short)
        if not law_id:
            print("skip (law_id 不明)", short, flush=True)
            continue
        texts = {}
        for asof in asofs:
            url, body, d = fetch_full(law_id, asof, dl)
            ri = d.get("revision_info") or {}
            entry = {"short": short, "law_id": law_id, "asof": asof, "url": url, "law_title": ri.get("law_title"),
                     "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            log["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)
            root = d["law_full_text"]
            main_arts, orig_suppl_arts, suppl = [], [], []

            def collect(n, path):
                tags = [p.get("tag") for p in path]
                if n.get("tag") == "Article":
                    sp = [p for p in path if p.get("tag") == "SupplProvision"]
                    if not sp:
                        main_arts.append(n)
                    elif "AmendLawNum" not in (sp[-1].get("attr") or {}):
                        orig_suppl_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            header = [f"# {short} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            body_lines = []
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            for num in sel.get("arts", []):
                a = by_num.get(num)
                if a is None:
                    body_lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                    continue
                body_lines.append(f"## 本則 Num={num}")
                render(a, 0, body_lines)
                body_lines.append("")
            for an, pn, inum in sel.get("items", []):
                a = by_num.get(an)
                p = child(a, "Paragraph", pn) if a else None
                it = child(p, "Item", inum) if p else None
                body_lines.append(f"## 本則 Num={an} 第{pn}項 第{inum}号")
                if it is None:
                    body_lines += ["見つからない", ""]
                else:
                    render(it, 0, body_lines)
                    body_lines.append("")
            cands = [("本則", a) for a in main_arts] + [("原始附則", a) for a in orig_suppl_arts]
            picked = set()
            for part, a in cands:
                cap = caption_of(a)
                txt = article_text(a)
                hit_cap = any(k in cap for k in sel.get("caption_kw", []))
                hit_txt = any(k in txt for k in sel.get("text_kw", []))
                key = (part, a["attr"].get("Num"))
                if (hit_cap or hit_txt) and key not in picked:
                    picked.add(key)
                    body_lines.append(f"## {part} Num={a['attr'].get('Num')} {cap}")
                    body_lines.append(txt)
                    body_lines.append("")
            if sel.get("kw_list"):
                kw = []
                for part, a in cands:
                    txt = article_text(a)
                    found = [k for k in sel["kw_list"] if k in txt]
                    if found:
                        kw.append({"part": part, "num": a["attr"].get("Num"), "caption": caption_of(a), "keywords": found})
                (OUT / f"kw_{short}_asof{asof}.json").write_text(json.dumps(
                    {"law_id": law_id, "asof": asof, "law_revision_id": ri.get("law_revision_id"), "keywords": sel["kw_list"],
                     "articles": kw}, ensure_ascii=False, indent=1), encoding="utf-8")
            if sel.get("amend_suppl"):
                an = ri.get("amendment_law_num")
                # e-Gov の AmendLawNum は漢数字の表記（例：令和八年三月三一日財務省令第一七号）なので、一覧も残す
                nums = sorted({(s.get("attr") or {}).get("AmendLawNum", "(原始附則)") for s in suppl})
                body_lines.append(f"## 収録された改正附則の AmendLawNum（{len(nums)} 件。令和七年・令和八年のものだけ表示）")
                body_lines += [x for x in nums if x.startswith(("令和七年", "令和八年"))]
                body_lines.append("")
                body_lines.append(f"## この版の改正法令（revision_info）: {an}")
                body_lines.append("")
            texts[asof] = body_lines
            extra = []
            if sel.get("amend_suppl"):
                for s in suppl:
                    a = (s.get("attr") or {}).get("AmendLawNum", "")
                    if a.startswith("令和八年"):
                        extra.append(f"## 附則 AmendLawNum={a}")
                        render(s, 0, extra)
                        extra.append("")
            (OUT / f"{short}_asof{asof}.txt").write_text("\n".join(header + body_lines + extra), encoding="utf-8")
        for a1, a2 in zip(asofs, asofs[1:]):
            diff = list(difflib.unified_diff(texts[a1], texts[a2], fromfile=f"{short} asof {a1}", tofile=f"{short} asof {a2}", lineterm=""))
            (OUT / f"{short}_diff_{a1}_vs_{a2}.diff").write_text("\n".join(diff) if diff else "(差分なし)", encoding="utf-8")

    for short, law_id in REVISIONS:
        q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
        url = f"{API}/law_revisions/{law_id}?{q}"
        st, body = get(url)
        (dl / f"revisions_{law_id}.json").write_bytes(body)
        revs = []
        if st == 200:
            for rv in json.loads(body).get("revisions", []):
                revs.append({k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                                   "amendment_scheduled_enforcement_date", "amendment_law_title", "amendment_law_num",
                                                   "current_revision_status")})
        (OUT / f"revisions_{short}.json").write_text(json.dumps({"url": url, "status": st, "revisions": revs}, ensure_ascii=False, indent=1), encoding="utf-8")
        log["revisions"].append({"short": short, "url": url, "status": st, "n": len(revs), "sha256": hashlib.sha256(body).hexdigest()})
    (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    sys.exit(main())
