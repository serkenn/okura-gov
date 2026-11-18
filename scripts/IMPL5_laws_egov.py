"""IMPL5 laws egov: impl-research5 で調べる条文を e-Gov 法令API v2（/law_data）で版（asof）ごとに取り出す。

調べること（docs/public-sources/20261112_impl-research5_*.md）：
- genka：所得税法施行令第120条・第120条の2（鉱業用減価償却資産・鉱業権・国外リース資産・リース資産の償却の方法）、第132条・第134条（月数・累積の限度）、
  耐用年数省令（採掘予定数量・鉱業権の耐用年数）。
- fudosan：租税特別措置法第41条の4の2（特定組合員等）・第41条の4の3（国外中古建物）、同施行令第26条の6の2・第26条の6の3。
- jumin-zasson：地方税法第313条（第9項：雑損失の繰越控除）・第317条の2・第317条の3、同施行令（雑損失の金額・第46条の3〜第46条の5）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL5_laws_egov.py fetch
      LAWS の全部（law_id × asof）を取得し（fetch <略称> ... なら指定したものだけ） .work/downloads/<YYYYMMDD-HHMMSS>_IMPL5_laws_egov/ に置く（新しい空のディレクトリ）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL5_laws_egov.py extract <ダウンロード先> [<ダウンロード先> ...]
      ネットワークを使わず、取得した JSON から条・語を含む条を取り出す（同じ名前は後に書いたディレクトリのものを使う）。

- e-Gov の呼び方と条文のテキスト化は scripts/IMPL4_laws_egov.py（もとは scripts/R1_egov_articles.py）を写した（import はしない）。
- ダウンロードしたものは信頼できないデータとして新しい空のディレクトリに置き、json.loads で読むだけ。中では何も実行しない。
- 出力 scripts/results/IMPL5_laws_egov/
    fetch_log_<ts>.json           取得の記録（URL、版、改正法令、施行日、状態、SHA-256、バイト数）
    <略称>_<asof>.txt             指定した本則の条（「## Num=」）
    grep_<略称>_<asof>.txt        語を含む条（本則・附則の全部を走査。附則は AmendLawNum を付ける）
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
NAME = "IMPL5_laws_egov"
OUT = ROOT / "scripts" / "results" / NAME
R7, R8 = "2025-12-31", "2026-12-31"  # 令和7年分・令和8年分の年末の版
F8, F9 = "2026-01-01", "2027-01-01"  # 住民税の令和8年度分・令和9年度分の賦課期日の版

# 略称: (law_id, 名称, [asof], [本則の Num], [grep の語])
LAWS = {
    "shorei": ("340CO0000000096", "所得税法施行令", [R7, R8],
               ["120", "120_2", "125", "132", "134", "138", "139"],
               ["採掘予定数量", "採掘予定年数", "生産高比例法", "リース期間定額法", "残価保証額", "見積残存価額", "国外リース資産"]),
    "taiyo": ("340M50000040015", "減価償却資産の耐用年数等に関する省令", [R7, R8],
              ["1", "2", "3", "4", "5", "6"],
              ["鉱業権", "採掘", "鉱業用", "坑道", "貯留権"]),
    "shoki": ("340M50000040011", "所得税法施行規則", [R7, R8], [],
              ["採掘予定数量", "生産高比例法", "リース期間定額法", "国外リース", "鉱業権"]),
    "sochi": ("332AC0000000026", "租税特別措置法", [R7, R8], ["28_2", "41_4", "41_4_2", "41_4_3"], []),
    "sochirei": ("332CO0000000043", "租税特別措置法施行令", [R7, R8], ["26_6", "26_6_2", "26_6_3"], []),
    "sochiki": ("332M50000040015", "租税特別措置法施行規則", [R7, R8], [], ["国外中古建物", "特定組合員", "第四十一条の四の二", "第四十一条の四の三"]),
    "chiho": ("325AC0000000226", "地方税法", [F8, F9], ["313", "314_2", "317_2", "317_3", "317_3_2", "317_6"],
              ["雑損失", "国外中古建物", "特定組合員", "第四十一条の四の二", "第四十一条の四の三"]),
    "chihorei": ("325CO0000000245", "地方税法施行令", [F8, F9], ["46_3", "46_4", "46_5"],
                 ["雑損失", "第三百十三条第九項", "第三百十三条第八項", "給与所得等以外の所得を有しなかつた者"]),
}

#: 改正法令の附則（AmendLawNum に含まれる語 → その附則の全部を suppl_<略称>_<asof>.txt に書く）
SUPPL = {
    "shorei": ["令和八年三月三一日政令第九三号", "令和七年三月三一日政令第一二〇号"],
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


# ---- IMPL4_laws_egov.py から写した（テキスト化） ----
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
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle", "AppdxTableTitle"):
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
    for short, (law_id, name, asofs, arts, words) in LAWS.items():
        for asof in asofs:
            cands = [d / f"{short}_{asof}.json" for d in dls if (d / f"{short}_{asof}.json").exists()]
            if not cands:
                print("missing", short, asof)
                continue
            p = cands[-1]
            try:
                d = json.loads(p.read_bytes())
            except ValueError:
                print("unreadable", p)
                continue
            ri = d.get("revision_info") or {}
            root = d["law_full_text"]
            main_arts, suppl, appdx = [], [], []

            def collect(n, path):
                if n.get("tag") == "Article" and "SupplProvision" not in path:
                    main_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
                if n.get("tag", "").startswith("AppdxTable") and n.get("tag") != "AppdxTableTitle" and "AppdxTable" not in path:
                    appdx.append(n)
            walk(root, collect)
            header = [f"# {name} {law_id} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 元データ={p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}", ""]
            by_num = {a["attr"].get("Num"): a for a in main_arts}
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
            (OUT / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            if short in SUPPL:
                sl = list(header)
                for w in SUPPL[short]:
                    for s in suppl:
                        if w in (s.get("attr", {}).get("AmendLawNum") or ""):
                            sl.append(f"## 附則 AmendLawNum={s.get('attr', {}).get('AmendLawNum')}")
                            render(s, 0, sl)
                            sl.append("")
                (OUT / f"suppl_{short}_{asof}.txt").write_text("\n".join(sl), encoding="utf-8")
            if words:
                g = list(header)
                for a in main_arts:
                    t = text_of(a)
                    hit = [w for w in words if w in t]
                    if hit:
                        g += [f"## 本則 Num={a['attr'].get('Num')} 語={hit}", t, ""]
                for i, t_node in enumerate(appdx):
                    t = text_of(t_node)
                    lines_hit = [ln for ln in t.splitlines() if any(w in ln for w in words)]
                    if lines_hit:
                        g += [f"## 別表 {i} 語を含む行（{t.splitlines()[0] if t else ''}）"] + lines_hit + [""]
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
