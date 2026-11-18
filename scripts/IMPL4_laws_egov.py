"""IMPL4 laws egov: impl-research4 で調べる条文を e-Gov 法令API v2（/law_data）で版（asof）ごとに取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL4_laws_egov.py fetch
      LAWS の全部（law_id × asof）を取得し（fetch <略称> ... なら指定したものだけ） .work/downloads/<YYYYMMDD-HHMMSS>_IMPL4_laws_egov/ に置く（新しい空のディレクトリ）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL4_laws_egov.py extract <ダウンロード先> [<ダウンロード先> ...]
      （2026-11-12 の実行：.work/downloads/20261112-013811_IMPL4_laws_egov と、kokuhorei だけを足した .work/downloads/20261112-013948_IMPL4_laws_egov。同じ名前は後の方を使う）
      ネットワークを使わず、取得した JSON から条・附則・語を含む条を取り出す。

- e-Gov の呼び方と条文のテキスト化は scripts/R1_egov_articles.py を写した（import はしない）。
- ダウンロードしたものは信頼できないデータとして新しい空のディレクトリに置き、json.loads で読むだけ。中では何も実行しない。
- 出力 scripts/results/IMPL4_laws_egov/
    fetch_log_<ts>.json           取得の記録（URL、版、改正法令、施行日、状態、SHA-256、バイト数）
    <略称>_<asof>.txt             指定した本則の条（「## Num=」。原始附則の条は「## Num=附則<Num>」）と、指定した改正法令の附則（「## 附則 AmendLawNum=」）
    grep_<略称>_<asof>.txt        語を含む条（本則・附則の全部を走査。附則は AmendLawNum を付ける）
    amendlaws_<略称>_<asof>.txt   本文に収録されている附則の AmendLawNum の一覧
    sames.json                    同じ条の本文の SHA-256 を版の間で比べた結果
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
"""
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
NAME = "IMPL4_laws_egov"
OUT = ROOT / "scripts" / "results" / NAME
NOW = "2026-11-12"

# 略称: (law_id, 名称, [asof], [本則の Num], [附則の AmendLawNum に含まれる語], [grep の語])
LAWS = {
    "shoho": ("340AC0000000033", "所得税法",
              ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31", "2026-12-31"],
              ["64", "89", "152"], [], ["第六十四条第一項"]),
    "shorei": ("340CO0000000096", "所得税法施行令", ["2025-12-31", "2026-12-31"],
               ["120", "120_2", "125", "180", "217", "274"], [], ["第六十四条第一項", "旧定額法"]),
    "sochi": ("332AC0000000026", "租税特別措置法", ["2025-12-31", "2026-12-31"], ["29_6"], [], ["未払賃金"]),
    "kokunen": ("334AC0000000141", "国民年金法", ["2026-04-01", NOW, "2027-04-01"],
                ["30", "87_2", "88_3", "89"], ["令和七年", "令和六年六月一二日法律第四七号"], ["第八十八条の三"]),
    "kokunenrei": ("334CO0000000184", "国民年金法施行令", ["2026-04-01", NOW],
                   ["4_6", "6_6"], [], ["法第八十九条第一項第一号", "第八十九条第一項第一号", "第八十九条第一項", "第八十八条の三"]),
    "kokunenki": ("335M50000100012", "国民年金法施行規則", [NOW],
                  ["77_6"], ["令和八年三月三〇日厚生労働省令第五〇号"], ["第六条の六第十号", "令第六条の六", "教育施設", "第八十八条の三"]),
    "kokuho": ("333AC0000000192", "国民健康保険法", ["2026-04-01", NOW, "2027-04-01"],
               ["5", "6", "116", "116_2"], [], ["第百十六条の二"]),
    "kokuhoki": ("333M50000100053", "国民健康保険法施行規則", [NOW], ["5_2"], [], ["第百十六条の二", "法第百十六条"]),
    "chiho": ("325AC0000000226", "地方税法", ["2026-04-01", "2027-04-01"], ["20_4_2", "37_2", "314_7", "703_4", "附則35_2_6"], [], []),
    "chihorei": ("325CO0000000245", "地方税法施行令", ["2026-04-01", "2027-04-01"], [],
                 [], ["共同募金会", "日本赤十字社", "法第二十条の四の二第一項"]),
    "shafuku": ("326AC0000000045", "社会福祉法", [NOW], ["112", "113"], [], []),
    "kokuhorei": ("333CO0000000362", "国民健康保険法施行令", ["2026-04-01", "2027-04-01"], ["27_2", "29_7"], [],
                  ["第三十五条の二の六", "第二十条の四の二"]),
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


# ---- R1_egov_articles.py から写した（テキスト化） ----
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
# ---- 写しここまで ----


def text_of(n):
    lines = []
    render(n, 0, lines)
    return "\n".join(lines)


def fetch(only=None):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": []}
    for short, (law_id, name, asofs, *_rest) in LAWS.items():
        if only and short not in only:
            continue
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body = get(url)
            (dl / f"{short}_{asof}.json").write_bytes(body)
            rec = {"short": short, "law_id": law_id, "name": name, "asof": asof, "url": url, "status": st,
                   "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            if st == 200:
                try:
                    ri = json.loads(body).get("revision_info") or {}
                    rec.update({k: ri.get(k) for k in ("law_revision_id", "amendment_law_num",
                                                         "amendment_enforcement_date", "current_revision_status")})
                except ValueError:
                    rec["parse_error"] = True
            log["fetches"].append(rec)
            print(short, asof, st, len(body))
    (OUT / f"fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)


def extract(dls):
    dls = [pathlib.Path(x) for x in dls]
    OUT.mkdir(parents=True, exist_ok=True)
    sames = {}
    for short, (law_id, name, asofs, arts, amend_words, words) in LAWS.items():
        for asof in asofs:
            cands = [d / f"{short}_{asof}.json" for d in dls if (d / f"{short}_{asof}.json").exists()]
            p = cands[-1] if cands else dls[0] / f"{short}_{asof}.json"
            if not p.exists():
                print("missing", p)
                continue
            try:
                d = json.loads(p.read_bytes())
            except ValueError:
                print("unreadable", p)
                continue
            ri = d.get("revision_info") or {}
            root = d["law_full_text"]
            main_arts, suppl = [], []

            def collect(n, path):
                if n.get("tag") == "Article" and "SupplProvision" not in path:
                    main_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            header = [f"# {name} {law_id} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 元データ={p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}", ""]
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            # 原始附則（AmendLawNum のない SupplProvision）の条は「附則<Num>」で指定する
            for s_ in suppl:
                if not s_.get("attr", {}).get("AmendLawNum"):
                    walk(s_, lambda n, path: by_num.setdefault("附則" + n["attr"].get("Num", ""), n) if n.get("tag") == "Article" else None)
            sames.setdefault(short, {})[asof] = {num: hashlib.sha256(text_of(a).encode("utf-8")).hexdigest()
                                                 for num, a in by_num.items() if num in arts}
            lines = list(header)
            for num in arts:
                a = by_num.get(num)
                if a is None:
                    lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                    continue
                lines.append(f"## Num={num}")
                render(a, 0, lines)
                lines.append("")
            for w in amend_words:
                hits = [s for s in suppl if w in (s.get("attr", {}).get("AmendLawNum") or "")]
                for s in hits:
                    lines.append(f"## 附則 AmendLawNum={s.get('attr', {}).get('AmendLawNum')}")
                    render(s, 0, lines)
                    lines.append("")
            (OUT / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            al = sorted({s.get("attr", {}).get("AmendLawNum") or "(原始附則)" for s in suppl})
            (OUT / f"amendlaws_{short}_{asof}.txt").write_text("\n".join(header + al), encoding="utf-8")
            if words:
                g = list(header)
                for a in main_arts:
                    t = text_of(a)
                    hit = [w for w in words if w in t]
                    if hit:
                        g += [f"## 本則 Num={a['attr'].get('Num')} 語={hit}", t, ""]
                for s in suppl:
                    an = s.get("attr", {}).get("AmendLawNum") or "(原始附則)"
                    t = text_of(s)
                    if not any(w in t for w in words):
                        continue
                    sub = []
                    walk(s, lambda n, path: sub.append(n) if n.get("tag") == "Article" else None)
                    for a in sub or [s]:
                        ta = text_of(a)
                        hit = [w for w in words if w in ta]
                        if hit:
                            g += [f"## 附則 AmendLawNum={an} Num={a.get('attr', {}).get('Num')} 語={hit}", ta, ""]
                (OUT / f"grep_{short}_{asof}.txt").write_text("\n".join(g), encoding="utf-8")
    cmp = {}
    for short, d in sames.items():
        asofs = sorted(d)
        cmp[short] = {"asofs": asofs, "sha256": d,
                      "changed_between_consecutive": {f"{a}..{b}": sorted(n for n in set(d[a]) | set(d[b]) if d[a].get(n) != d[b].get(n))
                                                      for a, b in zip(asofs, asofs[1:])}}
    (OUT / "sames.json").write_text(json.dumps(cmp, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    if sys.argv[1:2] == ["fetch"]:
        fetch(sys.argv[2:] or None)
    elif sys.argv[1:2] == ["extract"] and len(sys.argv) >= 3:
        extract(sys.argv[2:])
    else:
        print(__doc__)
        sys.exit(2)
