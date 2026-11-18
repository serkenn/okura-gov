"""IMPL2 kyuyo-jiki: e-Gov 法令API v2 で、給与所得の収入すべき時期と未払・死亡後の給与に関係する条文を取り出す。

対象：所得税法 第9条（第1項第17号：相続等により取得するもの）・第28条・第36条・第183条（源泉徴収義務。第2項：未払の役員賞与等）・
第190条（年末調整：「その年中に支払うべきことが確定した給与等」）・第226条（源泉徴収票）、相続税法 第3条（退職手当金等）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_kyuyo-jiki_egov.py

- e-Gov の呼び方と条文のテキスト化は scripts/IMPL2_tsukin_egov.py（その元は scripts/R1_egov_articles.py）を写した（import はしない）。
- 各時点の本文から対象の条を取り出し、時点ごとの本文の SHA-256 を記録する（時点の間で条文が同じかを見るため）。
- ダウンロードしたもの（信頼できないデータ）は .work/downloads/<YYYYMMDD-HHMMSS>_IMPL2_kyuyo-jiki_egov/ に置く（新しい空のディレクトリ。
  中では何も実行しない）。出力は scripts/results/IMPL2_kyuyo-jiki_egov/。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
"""
import datetime as dt
import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "IMPL2_kyuyo-jiki_egov"

# (略称, 名称, law_id, [asof...], [条の Num])
JOBS = [
    ("ho", "所得税法", "340AC0000000033", ["2025-12-31", "2026-11-11", "2026-12-31", "2027-01-01"],
     ["9", "28", "36", "183", "190", "226"]),
    ("sozoku", "相続税法", "325AC0000000073", ["2025-12-31", "2026-11-11"], ["3"]),
]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}
NL = "\n"


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
        cells = [inline(c).replace(NL, " ") for c in ch if isinstance(c, dict)]
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


def api(path, **q):
    q.setdefault("response_format", "json")
    url = API + path + "?" + urllib.parse.urlencode(q)
    st, body = get(url)
    return url, st, body


def fetch_law(law_id, asof, dl):
    url, st, body = api(f"/law_data/{law_id}", asof=asof)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    d = json.loads(body)
    ri = d.get("revision_info") or {}
    meta = {"law_id": law_id, "asof": asof, "url": url, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
            "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
            "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
            "current_revision_status": ri.get("current_revision_status")}
    return meta, d["law_full_text"]


def split(root):
    main_arts, suppl = [], []

    def collect(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path:
            main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            suppl.append(n)
    walk(root, collect)
    return {a["attr"].get("Num"): a for a in main_arts}, suppl


def article_text(by_num, num):
    a = by_num.get(num)
    if a is None:
        return f"## Num={num}: 見つからない（この時点の本則にない）" + NL
    lines = [f"## Num={num}"]
    render(a, 0, lines)
    return NL.join(lines) + NL


def prev_day(d):
    return (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()


def header(name, law_id, asof, meta, ts):
    return NL.join([f"# {name} {law_id} asof={asof}",
                    f"# law_revision_id={meta['law_revision_id']} 改正法令={meta['amendment_law_num']} "
                    f"施行日={meta['amendment_enforcement_date']} 状態={meta['current_revision_status']}",
                    f"# 取得URL={meta['url']}", f"# 取得日時={ts}", "", ""])



def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_kyuyo-jiki_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": []}
    for short, name, law_id, asofs, arts in JOBS:
        for asof in asofs:
            meta, root = fetch_law(law_id, asof, dl)
            by_num, _ = split(root)
            per_art = {}
            texts = []
            for n in arts:
                t = article_text(by_num, n)
                per_art[n] = hashlib.sha256(t.encode("utf-8")).hexdigest()
                texts.append(t)
            meta["article_text_sha256"] = per_art
            log["fetches"].append(meta)
            (OUT / f"{short}_{asof}.txt").write_text(header(name, law_id, asof, meta, ts) + "".join(texts), encoding="utf-8")
            print(short, asof, meta["law_revision_id"], flush=True)
    (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()
