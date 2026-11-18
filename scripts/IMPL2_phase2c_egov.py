"""IMPL2 phase2c: e-Gov 法令API v2 で、実装で「一次情報が docs にない」と報告された条文を、令和7年分・令和8年分の版で取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_phase2c_egov.py fetch
      LAWS の全部（law_id × asof）を /law_data で取得する。.work/downloads/<ts>_IMPL2_phase2c_egov/ に置く。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_phase2c_egov.py extract <ダウンロード先>
      ネットワークを使わず、取得した JSON から条を取り出す（TOPICS を直すたびに取得し直さないため）。

- e-Gov の呼び方と条文のテキスト化は scripts/R1_egov_articles.py を写した（import はしない）。
- 複数のトピック（seito-kifu, haito, joto-junjo, 121, gensen, hasu, fudosan, genka）が同じ法令の同じ版を使うので、取得は1回にまとめ、
  出力をトピックごとのディレクトリに分けた。
- ダウンロードしたものは信頼できないデータとして新しい空のディレクトリに置き、json.loads で読むだけ。中では何も実行しない。
- 出力 scripts/results/IMPL2_phase2c_egov/
    fetch_log.json                      取得の記録（URL、版、SHA-256、バイト数）
    index_<略称>_<asof>.txt             本則の条番号と見出しの一覧
    <topic>/<略称>_<asof>.txt           トピックごとの条文
    <topic>/grep_<略称>_<asof>.txt      トピックごとのキーワードを含む条（本則の全条を走査）
    sames/<略称>.json                   条ごとの本文の SHA-256 と、版の間で本文が変わった条
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
"""
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "IMPL2_phase2c_egov"

R7, R8, R9, NOW = "2025-12-31", "2026-12-31", "2027-01-01", "2026-11-11"
LAWS = {
    "shoho": ("340AC0000000033", "所得税法", [R7, NOW, R8, R9]),
    "shorei": ("340CO0000000096", "所得税法施行令", [R7, NOW, R8, R9]),
    "shoki": ("340M50000040011", "所得税法施行規則", [R7, R8]),
    "sochi": ("332AC0000000026", "租税特別措置法", [R7, NOW, R8, R9]),
    "sochirei": ("332CO0000000043", "租税特別措置法施行令", [R7, NOW, R8, R9]),
    "sochiki": ("332M50000040015", "租税特別措置法施行規則", [R7, R8]),
    "taiyo": ("340M50000040015", "減価償却資産の耐用年数等に関する省令", [R7, R8]),
    "fukko": ("423AC0000000117", "復興財源確保法", [R7, R8]),
    "hasuho": ("325AC0000000061", "国等の債権債務等の金額の端数計算に関する法律", [R8]),
    "seiji": ("323AC1000000194", "政治資金規正法", [R8]),
}

# topic -> {略称: [条番号]}。キーワードは本則の全条を走査して当たった条を書く
TOPICS = {
    "seito-kifu": {
        "arts": {
            "sochi": ["41_18", "41_18_2", "41_18_3", "41_18_4"],
            "shoho": ["78", "92", "120"],
            "seiji": ["3", "4", "5", "6", "21_2", "22_5"],
        },
        "grep": {"sochirei": ["第四十一条の十八", "政治活動に関する寄附"],
                 "sochiki": ["第四十一条の十八", "政治活動に関する寄附", "特定寄附金"]},
    },
    "haito": {
        "arts": {
            "shoho": ["24", "25", "92", "93", "95"],
            "sochi": ["8_4", "8_5", "9", "9_3", "9_3_2"],
        },
        "grep": {"shorei": ["第二十四条第二項", "配当所得の金額の計算"],
                 "sochirei": ["配当所得の金額の計算", "第二十四条第二項"]},
    },
    "joto-junjo": {
        "arts": {
            "shoho": ["21", "22", "69", "70", "71", "72", "87", "89", "120"],
            "sochi": ["8_4", "37_10", "37_11", "37_12_2"],
            "sochirei": ["4_2", "21", "25_8", "25_9", "25_11_2"],
        },
        "grep": {
            "shorei": ["雑損失の繰越控除", "第七十一条", "第八十七条"],
            "sochirei": ["第八十七条", "第七十一条", "第七十条第一項", "読替"],
        },
    },
    "121": {
        "arts": {"shoho": ["120", "121", "183", "184", "190", "194", "195"],
                 "shorei": ["262_2"]},
        "grep": {},
    },
    "gensen": {
        "arts": {
            "shoho": ["120", "122", "138", "181", "182", "183", "199", "201", "203_2", "203_3", "203_4", "203_7",
                      "204", "205", "225", "226"],
            "sochi": ["8_4", "9_3", "9_3_2", "37_11_4", "37_11_6", "37_12_2"],
            "fukko": ["8", "9", "10", "11", "12", "13", "17", "18", "19", "24", "26", "27", "28", "29", "30", "31",
                      "32", "33"],
            "sochirei": ["4_2", "25_9", "25_10_11"],
        },
        "grep": {"shorei": ["源泉徴収税額", "第百二十条第一項第四号"],
                 "sochirei": ["第百二十条第一項第四号", "源泉徴収税額"]},
    },
    "hasu": {
        "arts": {"shoho": ["35", "76", "77"]},
        "grep": {"shoho": ["端数"], "shorei": ["一円未満の端数"], "sochi": ["一円未満の端数"]},
    },
    "fudosan": {
        "arts": {"sochi": ["41_4", "41_4_2", "41_4_3"], "shoho": ["69", "26"], "shorei": ["178", "198"],
                 "sochirei": ["26_6", "26_6_2", "26_6_3"]},
        "grep": {},
    },
    "genka": {
        "arts": {"shorei": ["120", "120_2", "125", "126", "129", "131", "132", "134", "138", "139"],
                 "shoho": ["49", "51"], "hasuho": ["__ALL__"]},
        "grep": {"shorei": ["端数"], "taiyo": ["端数"], "sochi": ["端数を切り上", "端数切上"],
                 "sochirei": ["端数を切り上"]},
    },
}

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
            walk(c, fn, path + (n.get("tag"),))


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def fetch():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_phase2c_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": []}
    for short, (law_id, name, asofs) in LAWS.items():
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body = get(url)
            (dl / f"{short}_{asof}.json").write_bytes(body)
            rec = {"short": short, "law_id": law_id, "name": name, "asof": asof, "url": url, "status": st, "bytes": len(body),
                   "sha256": hashlib.sha256(body).hexdigest()}
            if st == 200:
                ri = json.loads(body).get("revision_info") or {}
                rec.update({k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date",
                                                   "current_revision_status")})
            log["fetches"].append(rec)
            print(short, asof, st, len(body), rec.get("law_revision_id"), flush=True)
    (OUT / f"fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("download_dir", dl)


def load(path):
    d = json.loads(path.read_bytes())
    ri = d.get("revision_info") or {}
    main, suppl = [], []

    def collect(n, p):
        if n.get("tag") == "Article" and "SupplProvision" not in p:
            main.append(n)
        if n.get("tag") == "SupplProvision":
            suppl.append(n)
    walk(d["law_full_text"], collect)
    return ri, main, suppl, d["law_full_text"]


def article_text(a):
    lines = []
    render(a, 0, lines)
    return "\n".join(lines)


def extract(dl):
    OUT.mkdir(parents=True, exist_ok=True)
    cache = {}
    sames = {}
    for short, (law_id, name, asofs) in LAWS.items():
        for asof in asofs:
            p = dl / f"{short}_{asof}.json"
            if not p.exists():
                print("missing", p)
                continue
            ri, main, suppl, full = load(p)
            by_num = {a["attr"].get("Num"): a for a in main}
            cache[(short, asof)] = (ri, main, suppl, full, by_num)
            (OUT / f"index_{short}_{asof}.txt").write_text(
                "\n".join(f"{a['attr'].get('Num')}\t{caption(a)}" for a in main) + "\n", encoding="utf-8")
            sames.setdefault(short, {})[asof] = {
                num: hashlib.sha256(article_text(a).encode("utf-8")).hexdigest() for num, a in by_num.items()}
    sd = OUT / "sames"
    sd.mkdir(exist_ok=True)
    for short, d in sames.items():
        asofs = sorted(d)
        out = {"asofs": asofs, "changed_between_consecutive": {}}
        for a, b in zip(asofs, asofs[1:]):
            changed = sorted(n for n in set(d[a]) | set(d[b]) if d[a].get(n) != d[b].get(n))
            out["changed_between_consecutive"][f"{a}..{b}"] = changed
        (sd / f"{short}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for topic, cfg in TOPICS.items():
        td = OUT / topic
        td.mkdir(exist_ok=True)
        for short, arts in cfg["arts"].items():
            law_id, name, asofs = LAWS[short]
            for asof in asofs:
                if (short, asof) not in cache:
                    continue
                ri, main, suppl, full, by_num = cache[(short, asof)]
                lines = [f"# {name} {law_id} asof={asof}", f"# law_revision_id={ri.get('law_revision_id')} 状態={ri.get('current_revision_status')}", ""]
                if arts == ["__ALL__"]:
                    render(full, 0, lines)
                else:
                    for num in arts:
                        a = by_num.get(num)
                        if a is None:
                            lines += [f"## Num={num}: 本則にない", ""]
                            continue
                        lines.append(f"## Num={num}")
                        lines.append(article_text(a))
                        lines.append("")
                (td / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
        for short, kws in cfg["grep"].items():
            law_id, name, asofs = LAWS[short]
            for asof in asofs:
                if (short, asof) not in cache:
                    continue
                ri, main, suppl, full, by_num = cache[(short, asof)]
                lines = [f"# grep {name} {law_id} asof={asof} 語={kws}", ""]
                for num, a in by_num.items():
                    t = article_text(a)
                    if any(k in t for k in kws):
                        lines += [f"## Num={num} {caption(a)}", t, ""]
                (td / f"grep_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "fetch":
        fetch()
    elif len(sys.argv) == 3 and sys.argv[1] == "extract":
        extract(pathlib.Path(sys.argv[2]))
    else:
        print(__doc__)
        sys.exit(2)
