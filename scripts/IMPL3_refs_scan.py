"""IMPL3 refs_scan: scripts/IMPL3_egov_fetch.py が取得した JSON の全文（本則・原始附則・改正附則）から、語を含む条を数える。
（国年令が平成16年改正法附則第19条〔納付猶予〕をどこで引くか、国保法・国保令・地令の「六歳」「十八歳」の減額の文言がどの版のどの条にあるか）

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_refs_scan.py <ダウンロード先>

- 入力：<ダウンロード先>/<略称>_<asof>.json（信頼できないデータ。json.loads で読むだけ）。
- 出力：scripts/results/IMPL3_refs_scan/refs.json（{ファイル: {語: [[本則|附則, 条番号, 前後の文字]]}}）
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL3_refs_scan"
JOBS = {
    "kokunenrei_2026-04-01": ["平成十六年改正法附則第十九条", "平成二十六年改正法附則第十四条", "納付猶予"],
    "kokunenrei_2027-04-01": ["平成十六年改正法附則第十九条", "平成二十六年改正法附則第十四条", "納付猶予"],
    "kokuho_2026-04-01": ["六歳に達する日以後", "十八歳に達する日以後"],
    "kokuho_2027-04-01": ["六歳に達する日以後", "十八歳に達する日以後"],
    "kokuhorei_2027-04-01": ["六歳に達する日以後", "十八歳に達する日以後", "出産"],
    "chihorei_2026-04-01": ["六歳に達する日以後", "十八歳に達する日以後", "出産"],
    "chihorei_2027-04-01": ["六歳に達する日以後", "十八歳に達する日以後", "出産"],
}


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def text(n):
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(text(c) for c in n.get("children", []))


def main(dl):
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    for stem, words in JOBS.items():
        p = dl / f"{stem}.json"
        if not p.exists():
            res[stem] = "missing"
            continue
        d = json.loads(p.read_bytes())
        hits = {w: [] for w in words}

        def fn(n, path):
            if n.get("tag") != "Article":
                return
            t = text(n)
            where = "附則" if "SupplProvision" in path else "本則"
            for w in words:
                for m in re.finditer(re.escape(w), t):
                    hits[w].append([where, n.get("attr", {}).get("Num"), t[max(0, m.start() - 30): m.end() + 30]])
        walk(d["law_full_text"], fn)
        res[stem] = {"law_revision_id": (d.get("revision_info") or {}).get("law_revision_id"),
                     "hits": hits, "articles": {w: sorted({f"{h[0]}{h[1]}" for h in v}) for w, v in hits.items()}}
        print(stem, {w: res[stem]["articles"][w] for w in words})
    (OUT / "refs.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(pathlib.Path(sys.argv[1]))
