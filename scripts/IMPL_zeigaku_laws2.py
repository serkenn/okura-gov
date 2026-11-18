"""IMPL zeigaku（追加）: IMPL_zeigaku_laws.py で足りなかった条文と、キーワード検索を e-Gov 法令API v2 で取得する。

実行（pyenv のシムは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_laws2.py        # 下の 1〜4
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_laws2.py r9     # 下の 5 だけ
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_laws2.py fukko  # 下の 6 だけ

- 取得するもの
  1. 国民年金法施行令：第6条の7・第6条の8の2・第6条の12（学生納付特例の所得の計算に関係する条）と、「扶養親族等」「特定年齢扶養親族」を定義する条
  2. 国民年金法施行規則：法第90条第1項第1号の「厚生労働省令で定める月」を定める条（「前々年の所得」を含む条を本文で探す）
  3. 国税通則法施行令：第40条（政令で定める国税の課税標準・確定金額の端数計算）
  4. キーワード検索 /keyword：「防衛特別所得税」（2027-01-01 時点。令和9年分以後に新しい付加税があるかの確認）
  5. （引数 r9）所得税法第120条と令和8年法律第12号の附則のうち第120条に触れる条、所得税法施行令第262条（いずれも 2027-01-01 時点）
  6. （引数 fukko）復興特別所得税に関する政令・省令のうち「一円未満」「端数」を含む条（2026-12-31 時点）
- 取得した JSON は .work/downloads/<ts>_IMPL_zeigaku_laws2/ に置く（信頼できないデータ。中でコードを実行しない）。
- 結果は scripts/results/IMPL_zeigaku_laws2/ に書く。
- コードは scripts/R1_egov_articles.py・scripts/R4_fetch_laws.py から写した（import はしない）。標準ライブラリのみ。リクエストの間は 1.5 秒。
"""
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
TODAY = "2026-11-09"

# (略称, law_id または None, 法令名, asof, [条番号], [本文に含まれていれば抜き出す文字列])
JOBS = [
    ("kokunen-rei", "334CO0000000184", "国民年金法施行令", TODAY, ["6_7", "6_8_2", "6_12"], ["「扶養親族等」", "「特定年齢扶養親族」", "特定扶養親族等」"]),
    ("kokunen-ki", None, "国民年金法施行規則", TODAY, [], ["前々年の所得", "法第九十条第一項第一号に規定する厚生労働省令で定める月"]),
    ("tsusoku-rei", None, "国税通則法施行令", "2026-12-31", ["40"], []),
    # 2回目の実行で追加（引数 r9 で、この2件だけを実行する）：令和8年分以後の申告書（令和9年1月1日以後の提出）で
    # 国民年金保険料の証明書に代えて明細書を添付できるとする TA1130 の記載の根拠を探す。附則は令和8年法律第12号のものに限って文字列で探す。
    ("shotoku-r9", "340AC0000000033", "所得税法", "2027-01-01", ["120"], [], "令和八年三月三一日法律第一二号", ["第百二十条"]),
    ("shotoku-rei-r9", "340CO0000000096", "所得税法施行令", "2027-01-01", ["262"], [], None, []),
]
R9_ONLY = {"shotoku-r9", "shotoku-rei-r9"}
# 3回目の実行で追加（引数 fukko で、この2件だけを実行する）：申告書・手引きの「復興特別所得税額は1円未満切捨て」の法令上の根拠を探す
JOBS += [
    ("fukko-rei", None, "復興特別所得税に関する政令", "2026-12-31", [], ["一円未満", "端数"]),
    ("fukko-ki", None, "復興特別所得税に関する省令", "2026-12-31", [], ["一円未満", "端数"]),
]
FUKKO_ONLY = {"fukko-rei", "fukko-ki"}
KEYWORDS = [("防衛特別所得税", "2027-01-01"), ("防衛特別所得税", TODAY)]


def get(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    dest.write_bytes(body)
    time.sleep(SLEEP)
    return st, body


def text_of(n):
    if isinstance(n, str):
        return n
    if not isinstance(n, dict) or n.get("tag") == "Rt":
        return ""
    return "".join(text_of(c) for c in n.get("children", []))


def lines_of(n, depth=0, out=None):
    if out is None:
        out = []
    if isinstance(n, str) or not isinstance(n, dict):
        return out
    tag = n.get("tag", "")
    if tag in ("Paragraph", "Item") or (tag.startswith("Subitem") and not tag.endswith(("Title", "Sentence"))):
        head, rest = [], []
        for c in n.get("children", []):
            if isinstance(c, dict) and c.get("tag", "").endswith(("Num", "Title", "Sentence", "Caption")):
                head.append(text_of(c))
            else:
                rest.append(c)
        out.append("  " * depth + "　".join(h for h in head if h))
        for c in rest:
            lines_of(c, depth + 1, out)
        return out
    if tag == "TableRow":
        out.append("  " * depth + "| " + " | ".join(text_of(c) for c in n.get("children", []) if isinstance(c, dict)) + " |")
        return out
    if tag in ("ArticleCaption", "ArticleTitle"):
        out.append("  " * depth + text_of(n))
        return out
    for c in n.get("children", []):
        lines_of(c, depth, out)
    return out


def find_law_id(title, dl, idx):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    st, body = get(f"{API}/laws?{q}", dl / f"{idx:02d}_laws_search.json")
    data = json.loads(body)
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"]
    return None


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_zeigaku_laws2"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_zeigaku_laws2"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "keyword": [], "errors": []}
    only_r9 = sys.argv[1:] == ["r9"]
    only_fukko = sys.argv[1:] == ["fukko"]
    for idx, job in enumerate(JOBS, 1):
        short, law_id, title, asof, nums, needles = job[:6]
        suppl_amend, suppl_needles = (job[6], job[7]) if len(job) > 6 else (None, [])
        if only_r9 != (short in R9_ONLY) or only_fukko != (short in FUKKO_ONLY):
            continue
        try:
            if law_id is None:
                law_id = find_law_id(title, dl, idx)
                if not law_id:
                    log["errors"].append({"short": short, "error": "law_id not found"})
                    continue
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body = get(url, dl / f"{idx:02d}_{short}_{asof}.json")
            if st != 200:
                log["errors"].append({"short": short, "status": st})
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            lines = [f"# {short} {title} {law_id} asof={asof}",
                     f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                     f"# 取得URL={url}", f"# 取得日時={ts}", ""]
            picked = []

            def visit(n, where):
                if not isinstance(n, dict):
                    return
                if n.get("tag") == "SupplProvision":
                    where = "附則 " + (n.get("attr", {}).get("AmendLawNum") or "(原始附則)")
                if n.get("tag") == "Article":
                    num = n.get("attr", {}).get("Num")
                    t = text_of(n)
                    in_suppl = suppl_amend is not None and where == "附則 " + suppl_amend
                    if (where == "本則" and num in nums) or any(s in t for s in needles) or (in_suppl and any(s in t for s in suppl_needles)):
                        picked.append((where, num))
                        lines.append(f"## {where} Num={num}")
                        lines.extend(lines_of(n))
                        lines.append("")
                    return
                for c in n.get("children", []):
                    visit(c, where)
            visit(d["law_full_text"], "本則")
            (out / f"{short}_{asof}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            log["fetches"].append({"short": short, "title": title, "law_id": law_id, "asof": asof, "url": url,
                                   "law_revision_id": ri.get("law_revision_id"), "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                   "current_revision_status": ri.get("current_revision_status"), "picked": picked})
            print("ok", short, asof, ri.get("law_revision_id"), picked, flush=True)
        except Exception as e:  # noqa
            log["errors"].append({"short": short, "error": repr(e)})
            print("ERR", short, repr(e), flush=True)
    for n, (kw, asof) in enumerate([] if (only_r9 or only_fukko) else KEYWORDS):
        q = urllib.parse.urlencode({"keyword": kw, "response_format": "json", "asof": asof, "limit": 100, "sentences_limit": 3})
        url = f"{API}/keyword?{q}"
        st, body = get(url, dl / f"keyword_{n}.json")
        rec = {"keyword": kw, "asof": asof, "url": url, "status": st}
        try:
            data = json.loads(body)
            rec["total_count"] = data.get("total_count")
            rec["items"] = []
            for it in data.get("items", []):
                li, rv = it.get("law_info", {}), it.get("revision_info", {})
                rec["items"].append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_title": rv.get("law_title"),
                                     "law_revision_id": rv.get("law_revision_id"),
                                     "amendment_enforcement_date": rv.get("amendment_enforcement_date"),
                                     "sentences": [{"position": s.get("position"), "text": re.sub(r"<[^>]+>", "", s.get("text") or "")[:300]}
                                                   for s in it.get("sentences", [])]})
        except Exception as e:  # noqa
            rec["parse_error"] = repr(e)
            rec["body_head"] = body[:300].decode("utf-8", "replace")
        log["keyword"].append(rec)
        print("keyword", kw, asof, st, rec.get("total_count"), flush=True)
    (out / ("fetch_log_r9.json" if only_r9 else "fetch_log_fukko.json" if only_fukko else "fetch_log.json")).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())
