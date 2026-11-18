r"""R2X_kokuho: e-Gov 法令API v2 のキーワード検索API（/keyword）で、国民年金の納付猶予（平成16年改正法附則第19条、
平成26年年金事業運営改善法附則第14条）の所得基準を定める政令の所在を探し、見つかった政令の該当条を取得する。

実行:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_kokuho_keyword.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。

- 応答（JSON）は .work/downloads/<ts>_R2X_kokuho_keyword/ に置く（信頼できないデータ。中でコードを実行しない）。
- 結果は scripts/results/R2X_kokuho_keyword/ に書く。
  - keyword_search.json / keyword_search.txt：キーワードごとの該当法令と該当文
  - articles_<law_id>_<asof>.txt：キーワードを含む条（本則・附則）の全文
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
ASOF = "2026-11-09"

KEYWORDS = [
    "年金事業運営改善法附則第十四条第一項第一号",
    "平成十六年改正法附則第十九条第二項第一号",
    "附則第十四条第一項第一号に規定する政令で定める額",
    "附則第十九条第二項第一号に規定する政令で定める額",
    "三十五万円に乗じて得た額に三十二万円を加算した額",
    "改正法附則第十四条第一項第一号",
    "改正法附則第十九条第二項第一号",
]
# 本文を取得して、指定の語を含む条（本則・附則）を全文で書き出す法令。キーワード検索で見つかった法令のうち
# 国民年金の納付猶予に関係するものだけを、検索結果を見てから名指しで足す（恩給・法人税などの無関係な法令は取得しない）。
# 426CO0000000353：政府管掌年金事業等の運営の改善のための国民年金法等の一部を改正する法律の一部の施行に伴う経過措置に関する政令
# 416CO0000000298：平成十六年度、平成十七年度、…の国民年金制度…の改正に伴う厚生労働省関係法令に関する経過措置に関する政令
# 334CO0000000184：国民年金法施行令（附則を含めて、平成16年改正法附則第19条・平成26年改正法附則第14条に触れる条）
FETCH_LAWS = {
    "426CO0000000353": ["改正法附則第十四条第一項第一号"],
    "416CO0000000298": ["改正法附則第十九条第二項", "改正法附則第十九条第一項"],
    "334CO0000000184": ["改正法附則第十九条", "年金事業運営改善法附則第十四条"],
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    time.sleep(SLEEP)
    return st, body


# ---- テキスト化（scripts/R2X_kokuho_egov.py と同じもの） ----
BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


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


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_kokuho_keyword"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_kokuho_keyword"
    out.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "asof": ASOF, "download_dir": str(dl.relative_to(ROOT)), "searches": [], "fetches": []}
    lines = [f"# R2X_kokuho_keyword run_at={ts} asof={ASOF}", ""]
    found_ids = {}
    for i, kw in enumerate(KEYWORDS):
        q = {"keyword": kw, "asof": ASOF, "limit": 50, "response_format": "json"}
        url = f"{API}/keyword?" + urllib.parse.urlencode(q)
        st, body = get(url)
        (dl / f"kw{i:02d}.json").write_bytes(body)
        ent = {"keyword": kw, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "items": []}
        lines.append(f"## keyword={kw} status={st}")
        if st == 200:
            d = json.loads(body)
            ent["total_count"] = d.get("total_count")
            for item in d.get("items", []):
                li = item.get("law_info") or {}
                ri = item.get("revision_info") or {}
                sents = [s.get("text", "") if isinstance(s, dict) else str(s) for s in item.get("sentences", [])]
                ent["items"].append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_title": ri.get("law_title"),
                                     "law_revision_id": ri.get("law_revision_id"), "sentences": sents})
                lines.append(f"- {li.get('law_id')} {li.get('law_num')} {ri.get('law_title')} rev={ri.get('law_revision_id')}")
                for s in sents:
                    lines.append(f"    {s[:400]}")
                found_ids.setdefault(li.get("law_id"), set()).add(kw)
        else:
            lines.append(f"    応答: {body[:300]!r}")
        res["searches"].append(ent)
        lines.append("")
    # FETCH_LAWS の本文を取得し、指定の語を含む条を全文で書き出す
    for law_id, subs in FETCH_LAWS.items():
        url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": ASOF})
        st, body = get(url)
        (dl / f"{law_id}_{ASOF}.json").write_bytes(body)
        fe = {"law_id": law_id, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        if st != 200:
            res["fetches"].append(fe)
            continue
        d = json.loads(body)
        ri = d.get("revision_info") or {}
        fe.update({"law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                   "amendment_law_num": ri.get("amendment_law_num"), "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                   "current_revision_status": ri.get("current_revision_status")})
        res["fetches"].append(fe)
        arts = []

        def fn(n, path):
            if n.get("tag") == "Article":
                txt = inline(n)
                if any(k in txt for k in subs):
                    sp = [p for p in path if p.get("tag") == "SupplProvision"]
                    arts.append(("附則 " + sp[0].get("attr", {}).get("AmendLawNum", "(原始附則)") if sp else "本則", n))
        walk(d["law_full_text"], fn)
        al = [f"# {law_id} {ri.get('law_title')} asof={ASOF}",
              f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
              f"# 取得URL={url}", f"# 取得日時={ts}", f"# 書き出す条件：条の本文に {subs} のいずれかを含む", ""]
        for part, a in arts:
            al.append(f"## {part} Num={a['attr'].get('Num')}")
            render(a, 0, al)
            al.append("")
        (out / f"articles_{law_id}_{ASOF}.txt").write_text("\n".join(al), encoding="utf-8")
    (out / "keyword_search.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "keyword_search.txt").write_text("\n".join(lines), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
