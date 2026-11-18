"""R3X_dai3go: e-Gov 法令API v2 で、国民年金法施行令（昭和34年政令第184号）の被扶養配偶者の認定の条（現行の第4条）が
e-Gov に収録されたどの版までさかのぼれるかを確かめ、各時点の条文を取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_dai3go_egov.py

- scripts/R1_egov_articles.py の取得・描画の関数（get、inline、render、walk）を写した（import はしない）。
- 手順：
  1. /law_revisions/334CO0000000184 で改正履歴（施行日・改正法令）を取得する。
  2. 収録されている最も古い版の施行日、2009-12-31（日本年金機構の設立の前日）、2010-01-01、2026-11-09 の各時点（asof）で
     /law_data を取得し、本則の第4条・第4条の2・第4条の3（あれば）を取り出す。asof が収録範囲より前なら、その応答をそのまま記録する。
- 取得した JSON は .work/downloads/<ts>_R3X_dai3go_egov/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力：scripts/results/R3X_dai3go_egov/kokunen-rei_revisions.json（改正履歴）、kokunen-rei_<asof>.txt（条文）、fetch_log.json
"""
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
LAW_ID = "334CO0000000184"
ARTS = ["4", "4_2", "4_3"]
OUT = ROOT / "scripts" / "results" / "R3X_dai3go_egov"

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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_dai3go_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "user_agent": UA, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": []}

    url = f"{API}/law_revisions/{LAW_ID}"
    st, body = get(url)
    (dl / "law_revisions.json").write_bytes(body)
    log["fetches"].append({"url": url, "status": st, "bytes": len(body)})
    revs = json.loads(body).get("revisions", []) if st == 200 else []
    rows = [{k: r.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_promulgate_date",
                                     "amendment_enforcement_date", "current_revision_status", "repeal_status")} for r in revs]
    (OUT / "kokunen-rei_revisions.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    dates = sorted(r["amendment_enforcement_date"] for r in rows if r.get("amendment_enforcement_date"))
    print("revisions", len(rows), "oldest", dates[:3], "newest", dates[-3:])

    asofs = []
    if dates:
        asofs.append(dates[0])
    asofs += ["2009-12-31", "2010-01-01", "2026-11-09"]
    for asof in dict.fromkeys(asofs):
        q = {"response_format": "json", "asof": asof}
        url = f"{API}/law_data/{LAW_ID}?" + urllib.parse.urlencode(q)
        st, body = get(url)
        (dl / f"{LAW_ID}_{asof}.json").write_bytes(body)
        rec = {"asof": asof, "url": url, "status": st, "bytes": len(body)}
        lines = [f"# kokunen-rei {LAW_ID} asof={asof}", f"# 取得URL={url}", f"# 取得日時={ts}", f"# HTTP {st}"]
        if st == 200:
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            rec.update({k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date", "current_revision_status")})
            lines.append(f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}")
            lines.append("")
            main_arts = []

            def collect(n, path):
                if n.get("tag") == "Article" and "SupplProvision" not in path:
                    main_arts.append(n)
            walk(d["law_full_text"], collect)
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            for num in ARTS:
                a = by_num.get(num)
                if a is None:
                    lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                    continue
                lines.append(f"## Num={num}")
                render(a, 0, lines)
                lines.append("")
        else:
            lines += ["", body[:2000].decode("utf-8", "replace")]
        (OUT / f"kokunen-rei_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
        log["fetches"].append(rec)
        print(json.dumps(rec, ensure_ascii=False))
    (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
