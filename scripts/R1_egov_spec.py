"""R1: e-Gov 法令API v2 の OpenAPI 仕様を取得し、エンドポイントとパラメータの一覧を書き出す。

実行: python -I scripts/R1_egov_spec.py
- ダウンロードした仕様は .work/downloads/<ts>_egov_spec/ に置く（信頼できないデータ）。
- 要約は scripts/results/R1_egov_spec/ に書く。
標準ライブラリのみ。
"""
import json
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
CANDIDATES = [
    "https://laws.e-gov.go.jp/api/2/swagger-ui/lawapi-v2.yaml",
    "https://laws.e-gov.go.jp/api/2/openapi.json",
    "https://laws.e-gov.go.jp/api/2/swagger-ui/lawapi-v2.json",
    "https://laws.e-gov.go.jp/api/2/openapi.yaml",
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_egov_spec"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R1_egov_spec"
    out.mkdir(parents=True, exist_ok=True)
    log = []
    for url in CANDIDATES:
        try:
            st, ct, body = get(url)
            name = url.rsplit("/", 1)[-1]
            (dl / name).write_bytes(body)
            log.append({"url": url, "status": st, "content_type": ct, "bytes": len(body), "saved": str(dl / name)})
        except Exception as e:  # noqa
            log.append({"url": url, "error": repr(e)})
        time.sleep(1.5)
    (out / "fetch_log.json").write_text(json.dumps({"fetched_at": ts, "results": log}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(log, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
