r"""R2X_kokuho: e-Gov 法令API v2 の法令一覧取得API（/laws）で、国保・国民年金の調査に使う法令の law_id を法令名・法令番号から引く。

実行:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_kokuho_lawsearch.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。

- 応答（JSON）は .work/downloads/<ts>_R2X_kokuho_lawsearch/ に置く（信頼できないデータ。中でコードを実行しない）。
- 要約は scripts/results/R2X_kokuho_lawsearch/summary.json と summary.txt に書く。
"""
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

QUERIES = [
    ("law_title", "国民健康保険法"),
    ("law_title", "国民年金法"),
    ("law_title", "改定率の改定等に関する政令"),
    ("law_title", "政府管掌年金事業等の運営の改善のための国民年金法等の一部を改正する法律"),
    ("law_num", "平成十六年法律第百四号"),
    ("law_num", "平成二十六年法律第六十四号"),
    ("law_title", "子ども・子育て支援法"),
    ("law_title", "地方税法施行令"),
    ("law_title", "地方税法施行規則"),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    time.sleep(SLEEP)
    return st, body


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_kokuho_lawsearch"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_kokuho_lawsearch"
    out.mkdir(parents=True, exist_ok=True)
    summary = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "queries": []}
    lines = [f"# R2X_kokuho_lawsearch run_at={ts}", ""]
    for i, (k, v) in enumerate(QUERIES):
        q = {k: v, "limit": 100, "response_format": "json"}
        url = f"{API}/laws?" + urllib.parse.urlencode(q)
        st, body = get(url)
        (dl / f"q{i:02d}.json").write_bytes(body)
        ent = {"param": k, "value": v, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "laws": []}
        if st == 200:
            d = json.loads(body)
            ent["total_count"] = d.get("total_count")
            for law in d.get("laws", []):
                li = law.get("law_info") or {}
                ri = law.get("revision_info") or {}
                ent["laws"].append({"law_id": li.get("law_id"), "law_num": li.get("law_num"),
                                    "law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                                    "promulgation_date": li.get("promulgation_date"),
                                    "repeal_status": ri.get("repeal_status")})
        summary["queries"].append(ent)
        lines.append(f"## {k}={v} status={st} total={ent.get('total_count')}")
        for law in ent["laws"]:
            lines.append(f"{law['law_id']}\t{law['law_num']}\t{law['law_title']}\t{law['repeal_status']}")
        lines.append("")
        print(k, v, st, ent.get("total_count"), flush=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "summary.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
