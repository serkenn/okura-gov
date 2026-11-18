"""IMPL4 verify: impl-research4 の記録を、別の取り出し方と別の版（asof）で当たり直し、反証を探す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL4_verify_recheck.py fetch
      RECHECK の law_id × asof を e-Gov 法令API v2 で新しく取得し、.work/downloads/<YYYYMMDD-HHMMSS>_IMPL4_verify_recheck/ に置く。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL4_verify_recheck.py check <取得先> <IMPL4_laws_egov の取得先> [...]
      ネットワークを使わず、CHECKS の各項目を確かめる。

- 条文のテキスト化は scripts/IMPL4_laws_egov.py（R1 の写し）を使わず、Article の下の文字列をすべて連結するだけの別の方法で行う
  （レンダラの誤りで語を見落とす・作ることを避ける）。ルビ（Rt）は落とす。
- CHECKS は「その版のその条に、その語が含まれる（want=True）／含まれない（want=False）」の組。反証になる結果は ok=False で出る。
- ダウンロードしたものは信頼できないデータとして新しい空のディレクトリに置き、json.loads で読むだけ。
- 出力 scripts/results/IMPL4_verify_recheck/checks.json・fetch_log_<ts>.json
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
NAME = "IMPL4_verify_recheck"
OUT = ROOT / "scripts" / "results" / NAME

LAW_IDS = {"shoho": "340AC0000000033", "shorei": "340CO0000000096", "kokunen": "334AC0000000141",
           "kokunenki": "335M50000100012", "kokuho": "333AC0000000192", "chihorei": "325CO0000000245",
           "kokuhorei": "333CO0000000362", "chiho": "325AC0000000226", "kokunenrei": "334CO0000000184",
           "shafuku": "326AC0000000045", "sochi": "332AC0000000026"}
# 新しく取得する版（令和5年の年の途中・施行の前日・省令の施行の前日）
RECHECK = [("shoho", "2023-01-01"), ("shoho", "2023-06-30"), ("kokunen", "2026-09-30"),
           ("kokunenki", "2026-03-31"), ("shorei", "2023-12-31")]

T89 = ["百九十五万円以下の金額", "百分の五", "百九十五万円を超え三百三十万円以下の金額", "百分の十",
       "三百三十万円を超え六百九十五万円以下の金額", "百分の二十", "六百九十五万円を超え九百万円以下の金額", "百分の二十三",
       "九百万円を超え千八百万円以下の金額", "百分の三十三", "千八百万円を超え四千万円以下の金額", "百分の四十",
       "四千万円を超える金額", "百分の四十五"]
# (略称, asof, 条〔本則の Num。原始附則は "附則<Num>"〕, 語, want)
CHECKS = []
for asof in ["2022-12-31", "2023-01-01", "2023-06-30", "2023-12-31", "2024-12-31", "2025-12-31", "2026-12-31"]:
    CHECKS += [("shoho", asof, "89", w, True) for w in T89]
    CHECKS += [("shoho", asof, "89", "百分の五十五", False)]
CHECKS += [
    # 所法64①：事業所得だけを除く（給与所得は除かない）。不動産所得・山林所得は事業から生じたものだけを除く
    ("shoho", "2025-12-31", "64", "各種所得の金額（事業所得の金額を除く。以下この項において同じ。）", True),
    ("shoho", "2025-12-31", "64", "不動産所得又は山林所得を生ずべき事業から生じたものを除く", True),
    ("shoho", "2025-12-31", "64", "給与所得", False),
    ("shoho", "2026-12-31", "152", "当該事実が生じた日の翌日から二月以内に限り", True),
    ("shorei", "2023-12-31", "180", "いずれか低い金額に達するまでの金額", True),
    # 所令125①一イ：平成19年3月31日以前取得・120①一イ（平成10年3月31日以前取得の建物）と120①二 → 旧定額法（連結なので号の名と方法の間に空白はない）
    ("shorei", "2023-12-31", "125", "第百二十条第一項第一号イ及び同項第二号（減価償却資産の償却の方法）に掲げる減価償却資産旧定額法", True),
    ("shorei", "2025-12-31", "125", "第百二十条第一項第一号イ及び同項第二号（減価償却資産の償却の方法）に掲げる減価償却資産旧定額法", True),
    ("shorei", "2026-12-31", "125", "第百二十条第一項第一号イ及び同項第二号（減価償却資産の償却の方法）に掲げる減価償却資産旧定額法", True),
    ("shorei", "2025-12-31", "120", "平成十年三月三十一日以前に取得された建物", True),
    # 国年法88の3：2026-09-30 の版にはない（施行は 2026-10-01）
    ("kokunen", "2026-09-30", "88_3", "出産予定日から起算して三月を経過した日の属する月", False),
    ("kokunen", "2026-11-12", "88_3", "出産予定日から起算して三月を経過した日の属する月", True),
    # 国年則77の6：第29号の2 は 2026-04-01 施行の省令で足された（2026-03-31 の版にはない）
    ("kokunenki", "2026-03-31", "77_6", "一時保護施設の設備及び運営に関する基準", False),
    ("kokunenki", "2026-11-12", "77_6", "一時保護施設の設備及び運営に関する基準", True),
    ("kokunenki", "2026-11-12", "77_6", "厚生労働大臣が指定するもの", True),
    # 国保法116 は「世帯に属するものとみなす」が、116の2 は住所だけをみなす
    ("kokuho", "2026-11-12", "116", "当該世帯に属するものとみなす", True),
    ("kokuho", "2026-11-12", "116_2", "世帯に属するものとみなす", False),
    ("kokuho", "2026-11-12", "116_2", "当該他の市町村の区域内に住所を有するものとみなす", True),
    # 地方税令7の17：共同募金会（1号・2号）と日本赤十字社（3号）。48の8 は市町村民税に 7の17 を当てる
    ("chihorei", "2026-04-01", "7_17", "総務大臣の承認を受けたもの", True),
    ("chihorei", "2026-04-01", "7_17", "日本赤十字社に対して支出された寄附金で、日本赤十字社が当該寄附金の募集に当たり総務大臣の承認を受けたもの", True),
    ("chihorei", "2027-04-01", "48_8", "第七条の十七各号に掲げる寄附金とする", True),
    ("chihorei", "2026-04-01", "6_17", "国民健康保険税", False),
    # 国保令29の7⑥一：上場株式等に係る譲渡所得等の金額は、地方税法附則35の2の6⑪（繰越控除）の適用後
    ("kokuhorei", "2026-04-01", "29_7", "同法附則第三十五条の二の二第五項に規定する上場株式等に係る譲渡所得等の金額（同法附則第三十五条の二の六第十一項", True),
    ("chiho", "2026-04-01", "附則35_2_6", "市町村民税の所得割の納税義務者の前年前三年内の各年に生じた上場株式等に係る譲渡損失の金額", True),
    # 社会福祉法113②：共同募金会は社会福祉法人。所令217①五：社会福祉法人は特定公益増進法人
    ("shafuku", "2026-11-12", "113", "共同募金事業を行うことを目的として設立される社会福祉法人を共同募金会と称する", True),
    ("shorei", "2025-12-31", "217", "社会福祉法人", True),
    # 国年令6の5①：障害の給付の列挙
    ("kokunenrei", "2026-11-12", "6_5", "厚生年金保険法による障害厚生年金", True),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    time.sleep(SLEEP)
    return st, body


def fetch():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": []}
    for short, asof in RECHECK:
        url = f"{API}/law_data/{LAW_IDS[short]}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
        st, body = get(url)
        (dl / f"{short}_{asof}.json").write_bytes(body)
        rec = {"short": short, "asof": asof, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest()}
        if st == 200:
            ri = json.loads(body).get("revision_info") or {}
            rec.update({k: ri.get(k) for k in ("law_revision_id", "amendment_enforcement_date", "current_revision_status")})
        log["fetches"].append(rec)
        print(short, asof, st, flush=True)
    (OUT / f"fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def flat(n):
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(flat(c) for c in n.get("children", []))


def articles(root):
    """本則の Article を Num で、原始附則の Article を "附則<Num>" で引く辞書。"""
    found = {}

    def rec(n, in_suppl, amend):
        if not isinstance(n, dict):
            return
        tag = n.get("tag")
        if tag == "SupplProvision":
            in_suppl, amend = True, n.get("attr", {}).get("AmendLawNum")
        if tag == "Article":
            num = n.get("attr", {}).get("Num")
            if not in_suppl:
                found.setdefault(num, n)
            elif not amend:
                found.setdefault("附則" + num, n)
            return
        for c in n.get("children", []):
            rec(c, in_suppl, amend)
    rec(root, False, None)
    return found


def check(dls):
    dls = [pathlib.Path(d) for d in dls]
    OUT.mkdir(parents=True, exist_ok=True)
    cache, results = {}, []
    for short, asof, num, word, want in CHECKS:
        key = (short, asof)
        if key not in cache:
            cands = [d / f"{short}_{asof}.json" for d in dls if (d / f"{short}_{asof}.json").exists()]
            if not cands:
                cache[key] = None
            else:
                p = cands[0]
                d = json.loads(p.read_bytes())
                cache[key] = (str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                              (d.get("revision_info") or {}).get("law_revision_id"), articles(d["law_full_text"]))
        c = cache[key]
        if c is None:
            results.append({"law": short, "asof": asof, "num": num, "word": word, "want": want, "ok": None, "note": "版の取得なし"})
            continue
        src, rev, arts = c
        a = arts.get(num)
        if a is None:
            has = False
            note = "この版にこの条がない"
        else:
            has = word in flat(a)
            note = ""
        results.append({"law": short, "asof": asof, "num": num, "word": word, "want": want, "has": has,
                        "ok": has == want, "law_revision_id": rev, "source": src, "note": note})
    summary = {"total": len(results), "ok": sum(1 for r in results if r["ok"]),
               "ng": [r for r in results if r["ok"] is False], "missing": [r for r in results if r["ok"] is None]}
    (OUT / "checks.json").write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("total", summary["total"], "ok", summary["ok"], "ng", len(summary["ng"]), "missing", len(summary["missing"]))


if __name__ == "__main__":
    if sys.argv[1:2] == ["fetch"]:
        fetch()
    elif sys.argv[1:2] == ["check"] and len(sys.argv) >= 3:
        check(sys.argv[2:])
    else:
        print(__doc__)
        sys.exit(2)
