"""R1: 健康保険・国民年金の被扶養者（第3号被保険者）の収入基準が、法律・政令・省令の本文に書かれているかを全文検索で確かめる。

実行:  python -I scripts/R1_kenpo_amount_scan.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。

対象の法令の本文（asof=今日）を e-Gov 法令API v2 の /law_data で取得し、本則と附則のすべての文から、
基準額として使われうる金額の表記（漢数字）と「生計を維持」を含む文を探して、条番号つきで書き出す。
本文（JSON）は .work/downloads/<ts>_kenpo_scan/ に置く（信頼できないデータ）。
結果は scripts/results/R1_kenpo_amount_scan/ に書く。
"""
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
ASOF = time.strftime("%Y-%m-%d")

LAWS = {
    "211AC0000000070": "健康保険法",
    "215IO0000000243": "健康保険法施行令",
    "215M10000008036": "健康保険法施行規則",
    "334AC0000000141": "国民年金法",
    "334CO0000000184": "国民年金法施行令",
    "335M50000100012": "国民年金法施行規則",
}
PATTERNS = ["百三十万", "百五十万", "百八十万", "百六万", "百万円", "生計を維持", "認定"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    time.sleep(SLEEP)
    return st, body


def text(n):
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(text(c) for c in n.get("children", []))


def sentences(n, ctx):
    """(文脈, 文) を列挙する。文脈は 本則/附則（AmendLawNum）と条番号。"""
    if isinstance(n, str):
        return
    tag = n.get("tag")
    attr = n.get("attr", {})
    if tag == "SupplProvision":
        ctx = dict(ctx, part="附則(" + attr.get("AmendLawNum", "原始") + ")")
    if tag == "Article":
        ctx = dict(ctx, article=attr.get("Num"))
    if tag == "Paragraph":
        ctx = dict(ctx, paragraph=attr.get("Num"))
    if tag == "Sentence":
        yield ctx, text(n)
        return
    for c in n.get("children", []):
        yield from sentences(c, ctx)


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_kenpo_scan"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R1_kenpo_amount_scan"
    out.mkdir(parents=True, exist_ok=True)
    result = {"run_at": ts, "asof": ASOF, "patterns": PATTERNS, "laws": []}
    for law_id, name in LAWS.items():
        url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": ASOF})
        st, body = get(url)
        (dl / f"{law_id}.json").write_bytes(body)
        rec = {"law_id": law_id, "name": name, "url": url, "status": st}
        if st == 200:
            d = json.loads(body)
            rec["law_revision_id"] = (d.get("revision_info") or {}).get("law_revision_id")
            hits = {p: [] for p in PATTERNS}
            n_sent = 0
            for ctx, s in sentences(d["law_full_text"], {"part": "本則"}):
                n_sent += 1
                for p in PATTERNS:
                    if p in s:
                        hits[p].append({"part": ctx.get("part"), "article": ctx.get("article"),
                                        "paragraph": ctx.get("paragraph"), "text": s[:400]})
            rec["sentence_count"] = n_sent
            rec["hit_counts"] = {p: len(v) for p, v in hits.items()}
            rec["hits"] = {p: v[:30] for p, v in hits.items()}
        result["laws"].append(rec)
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
