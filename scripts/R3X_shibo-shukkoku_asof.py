"""R3X shibo-shukkoku: 令和8年度改正の施行日（2026-12-01）の前日と当日の版で、所得税法と租税特別措置法の条文を取り出し、
年の中途の死亡・出国の申告書（準確定申告書）を施行日の前に出すか後に出すかで、使う条文の版が変わることを確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_asof.py

- 既存の取得（scripts/R3X_shibo-shukkoku_laws.py。時点は 2025-12-31・2026-11-09・2026-12-31・2027-01-01）には
  2026-11-30 と 2026-12-01 の版がない。2026-12-31 の措置法の版の ID は 20261204 で、第41条の16の2 が 12月1日に変わるのかを
  既存の取得からは確かめられないので、この2つの時点だけを足して取る。
- API の使い方とテキスト化は scripts/R3X_shibo-shukkoku_laws.py（その元は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py）を写した。
  import はしない。
- ダウンロードした JSON は .work/downloads/<YYYYMMDD-HHMMSS>_R3X_shibo-shukkoku_asof/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力：scripts/results/R3X_shibo-shukkoku_asof/
  - <略称>_<asof>.txt … 取り出した条（先頭に law_revision_id・改正法令・施行日・取得URL・SHA-256）
  - diff_<略称>_<asof1>_vs_<asof2>.diff … 時点の間の差分
  - fetch_log.json … 取得した URL、版、SHA-256
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
OUT = ROOT / "scripts" / "results" / "R3X_shibo-shukkoku_asof"

ASOFS = ["2026-11-30", "2026-12-01"]
# (略称, 法令名, law_id, [本則の条番号（Num 属性）])
JOBS = [
    ("shotoku", "所得税法", "340AC0000000033", ["2", "86"]),
    ("sochi", "租税特別措置法", "332AC0000000026", ["41_16_2"]),
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


# ---- 本文のテキスト化（scripts/R3X_shibo-shukkoku_laws.py の inline / render / walk を写したもの） ----
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


def main_articles(root):
    arts = []
    walk(root, lambda n, p: arts.append(n) if n.get("tag") == "Article" and "SupplProvision" not in p else None)
    return arts


def rev_info(d):
    ri = d.get("revision_info") or {}
    return {k: ri.get(k) for k in ("law_revision_id", "law_title", "amendment_law_num", "amendment_law_title",
                                   "amendment_enforcement_date", "amendment_promulgate_date", "current_revision_status", "updated")}


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_shibo-shukkoku_asof"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "errors": []}
    for short, title, law_id, nums in JOBS:
        texts = {}
        for asof in ASOFS:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body = get(url)
            (dl / f"{short}_{asof}.json").write_bytes(body)
            if st != 200:
                log["errors"].append({"short": short, "asof": asof, "status": st})
                print("ERR", short, asof, st, flush=True)
                continue
            sha = hashlib.sha256(body).hexdigest()
            d = json.loads(body)
            ri, li = rev_info(d), d.get("law_info") or {}
            by_num = {a["attr"].get("Num"): a for a in main_articles(d["law_full_text"])}
            lines = [f"# {short} {title} law_id={law_id} 法令番号={li.get('law_num')} asof={asof}",
                     f"# law_revision_id={ri['law_revision_id']} 改正法令={ri['amendment_law_num']}（{ri['amendment_law_title']}） "
                     f"施行日={ri['amendment_enforcement_date']} 状態={ri['current_revision_status']} updated={ri['updated']}",
                     f"# 取得URL={url}", f"# 取得日時={ts} sha256={sha}", ""]
            body_lines = []
            for num in nums:
                body_lines.append(f"## Num={num}")
                if num in by_num:
                    render(by_num[num], 0, body_lines)
                else:
                    body_lines.append("（この時点の本則にない）")
                body_lines.append("")
            texts[asof] = body_lines
            (OUT / f"{short}_{asof}.txt").write_text("\n".join(lines + body_lines) + "\n", encoding="utf-8")
            log["fetches"].append({"short": short, "law_id": law_id, "asof": asof, "url": url, "sha256": sha, "bytes": len(body), **ri})
            print("ok", short, asof, ri["law_revision_id"], ri["amendment_enforcement_date"], ri["current_revision_status"], flush=True)
        if all(a in texts for a in ASOFS):
            a, b = ASOFS
            diff = list(difflib.unified_diff(texts[a], texts[b], f"{short}@{a}", f"{short}@{b}", lineterm=""))
            (OUT / f"diff_{short}_{a}_vs_{b}.diff").write_text("\n".join(diff) + "\n", encoding="utf-8")
            log.setdefault("diff_line_counts", {})[f"{short}_{a}_vs_{b}"] = len(diff)
    (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT, "errors", len(log["errors"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
