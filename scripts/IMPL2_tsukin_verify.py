"""IMPL2 tsukin の独立検証：公開資料の情報の文書（docs/public-sources/20261111_impl-research_tsukin-laws-and-nta.md）の主張を、
最初の取得とは別の経路で一次情報に当たり直して確かめる。反証（主張と食い違う本文）を探す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_tsukin_verify.py

最初の取得（scripts/IMPL2_tsukin_egov.py・IMPL2_tsukin_nta.py）との違い
- e-Gov は response_format=xml で取り、JSON の木を辿らずに XML の文字列から正規表現で条を切り出し、タグを外して読む（取り出し方の誤りを独立に検出するため）。
- 改正履歴は所得税法施行規則も取る（第2条の2 の施行日と改正法令を確かめる）。
- 国税庁のページ・PDF は新しいディレクトリに取り直し、最初の取得の SHA-256 と比べる（変わっていれば本文を見直す）。
- 主張ごとに「本文に含まれるべき文字列」「含まれてはならない文字列」を書き、満たすかを記録する。

ダウンロード先：.work/downloads/<YYYYMMDD-HHMMSS>_IMPL2_tsukin_verify/（新しい空のディレクトリ。中では何も実行しない）。
出力：scripts/results/IMPL2_tsukin_verify/verify.json。リクエストの間は 1.5 秒。User-Agent は okura-gov-research/0.1。
"""
import hashlib
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
WAIT = 1.5
OUT = ROOT / "scripts" / "results" / "IMPL2_tsukin_verify"
REI, HO, KI = "340CO0000000096", "340AC0000000033", "340M50000040011"

# (検査の名前, law_id, asof, 条の Num, 含まれるべき文字列, 含まれてはならない文字列)
ARTICLE_CHECKS = [
    ("V1 所令20の2 改正前（2025-11-19）", REI, "2025-11-19", "20_2", ["一月当たり三万千六百円", "一月当たり二万八千円", "一月当たり七千百円"], ["三万八千七百円", "駐車場等"]),
    ("V1 所令20の2 令和7年改正（2025-11-20）", REI, "2025-11-20", "20_2", ["片道五十五キロメートル以上である場合　一月当たり三万八千七百円", "一月当たり三万二千三百円", "一月当たり七千三百円", "一月当たり四千二百円"], ["六万六千四百円", "駐車場等"]),
    ("V1 所令20の2 令和8年改正前日（2026-03-31）", REI, "2026-03-31", "20_2", ["片道五十五キロメートル以上である場合　一月当たり三万八千七百円"], ["六万六千四百円", "駐車場等"]),
    ("V1 所令20の2 令和8年改正（2026-04-01）", REI, "2026-04-01", "20_2",
     ["片道五十五キロメートル以上六十五キロメートル未満である場合　一月当たり三万八千七百円", "六十五キロメートル以上七十五キロメートル未満である場合　一月当たり四万五千七百円",
      "七十五キロメートル以上八十五キロメートル未満である場合　一月当たり五万二千七百円", "八十五キロメートル以上九十五キロメートル未満である場合　一月当たり五万九千六百円",
      "九十五キロメートル以上である場合　一月当たり六万六千四百円", "当該金額が五千円を超えるときは、五千円", "一月当たりの金額が十五万円を超えるときは、一月当たり十五万円"], []),
    ("V1 所令20の2 現行（2026-11-11）", REI, "2026-11-11", "20_2", ["九十五キロメートル以上である場合　一月当たり六万六千四百円", "当該金額が五千円を超えるときは、五千円"], []),
    ("V1 所令20の2 予定の最後の版（2028-01-01）", REI, "2028-01-01", "20_2", ["九十五キロメートル以上である場合　一月当たり六万六千四百円", "当該金額が五千円を超えるときは、五千円"], []),
    ("V2 所法9①五 改正前日（2026-03-31）", HO, "2026-03-31", "9", ["交通用具の使用のために支出する費用に充てるものとして通常の給与に加算して受ける通勤手当"], ["駐車のための施設"]),
    ("V2 所法9①五 改正（2026-04-01）", HO, "2026-04-01", "9", ["（自動車その他の交通用具の駐車のための施設の利用のために支出する費用を含む。）に充てるものとして通常の給与に加算して受ける通勤手当", "次に掲げる所得については、所得税を課さない。"], []),
    ("V3 所規2の2 改正前日（2026-03-31）", KI, "2026-03-31", "2_2", [], ["駐車場等"]),
    ("V3 所規2の2 改正（2026-04-01）", KI, "2026-04-01", "2_2", ["勤務する場所の周辺又はその者が通勤のため利用する交通機関の駅若しくは停留所その他の施設の周辺にあること", "当該料金の額を十二", "三百六十五を乗じて"], []),
]
# 附則（最後の版の本文の SupplProvision。AmendLawNum で選ぶ）
SUPPL_CHECKS = [
    ("V4 令和7年政令第380号 附則", REI, "2026-11-11", "令和七年一一月一九日政令第三八〇号",
     ["この政令は、令和七年十一月二十日から施行する。", "令和七年四月一日以後に受けるべき通勤手当", "差額として追給されるもの", "なお従前の例による"], []),
    ("V4 令和8年政令第93号 附則第4条", REI, "2026-11-11", "令和八年三月三一日政令第九三号",
     ["この政令は、令和八年四月一日から施行する。", "新令第二十条の二の規定は、この政令の施行の日（以下「施行日」という。）以後に受けるべき通勤手当"], []),
]
NTA_PAGES = [
    # (名前, URL, 最初の取得の SHA-256 の結果ファイル, 含まれるべき文字列)
    ("ta_2585", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2585.htm", "IMPL2_tsukin_nta/pages/fetch_log.json",
     ["66,400円", "上限5,000円", "最高限度　150,000円", "[令和8年4月1日現在法令等]", "片道の通勤距離（通勤経路に沿った長さです。）",
      "上記１の金額と1か月当たりの駐車場等の料金相当額（上限5,000円）との合計額"]),
    ("ta_2582", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2582.htm", "IMPL2_tsukin_nta/pages/fetch_log.json",
     ["月を単位にして計算します", "15万円が非課税となる限度額",
      "役員や使用人などの給与所得者に対して通常の給与に加算して支給する通勤手当や通勤定期券などは、一定の限度額まで非課税となっています。",
      "グリーン料金は最も経済的かつ合理的な通勤経路および方法のための料金とは認められないため含まれません。",
      "1か月当たりの非課税となる限度額を超えて通勤手当や通勤定期券などを支給する場合には、超える部分の金額が給与として課税されます。",
      "なお、通勤手当などの非課税となる限度額は、パートやアルバイトなど短期間雇い入れる人についても、月を単位にして計算します。",
      "所法9、所令20の2、所基通9-6の3"]),
    ("ta_2508", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2508.htm", "IMPL2_tsukin_nta/pages2/fetch_log.json",
     ["例外として、次のような手当は非課税となります。", "（1）　通勤手当のうち、一定金額以下のもの"]),
    ("shitsugi_g_03_19", "https://www.nta.go.jp/law/shitsugi/gensen/03/19.htm", "IMPL2_tsukin_nta/pages2/fetch_log.json",
     ["それぞれの営業所等への通勤日数に応ずる合理的な運賃等の額の合計額を1か月当たりの合理的な運賃等の額として計算し"]),
    ("shitsugi_g_03_20", "https://www.nta.go.jp/law/shitsugi/gensen/03/20.htm", "IMPL2_tsukin_nta/pages2/fetch_log.json",
     ["月の中途で通勤距離が変更した場合の「1か月当たりの非課税限度額」の算定方法については、特段の規定はありません。"]),
    ("shitsugi_g_03_18", "https://www.nta.go.jp/law/shitsugi/gensen/03/18.htm", "IMPL2_tsukin_nta/pages2/fetch_log.json",
     ["交通機関利用者と同様に取り扱い、交通機関を利用したとした場合の合理的な運賃の額を非課税限度額(自動車通勤による実費の範囲内に限ります。)として取り扱って差し支えありません。"]),
    ("shitsugi_g_03_22", "https://www.nta.go.jp/law/shitsugi/gensen/03/22.htm", "IMPL2_tsukin_nta/pages2/fetch_log.json",
     ["給与明細書等において、通勤費の実費部分の額が通常の給与に加算して支給される通勤手当として区分識別できるのであれば",
      "通勤費の実費部分について通勤手当として加算した旨を明確に表示する必要があります。"]),
    ("users_2026tsukin", "https://www.nta.go.jp/users/gensen/2026tsukin/index.htm", "IMPL2_tsukin_nta/pages2/fetch_log.json",
     ["令和８年４月１日以後に支払われるべき通勤手当（同日前に支払われるべき通勤手当の差額として追加支給するものを除きます。）"]),
    ("users_2025tsukin", "https://www.nta.go.jp/users/gensen/2025tsukin/index.htm", "IMPL2_tsukin_nta/pages2/fetch_log.json",
     ["令和７年11月20日に施行され、令和７年４月１日以後に支払われるべき通勤手当"]),
    ("shitsugi_g_03_21", "https://www.nta.go.jp/law/shitsugi/gensen/03/21.htm", "IMPL2_tsukin_nta/pages2/fetch_log.json",
     ["日割額ではなく月額で判定します",
      "通勤手当のうち非課税とされる金額は、その勤務する者にその月中に支給する通勤手当の合計額のうち、所得税法施行令第20条の2各号《非課税とされる通勤手当》に非課税限度額として規定されている額に達するまでの金額となります。"]),
    ("kihon_02_02", "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/02/02.htm", "IMPL2_tsukin_nta/pages/fetch_log.json",
     ["9-6の3", "新幹線鉄道を利用した場合の運賃等の額も含まれるものとする。", "9-6の2　削除"]),
    ("tsukin2026_01", "https://www.nta.go.jp/users/gensen/2026tsukin/pdf/01.pdf", "IMPL2_tsukin_nta/pdfs/fetch_log.json", []),
    ("tsukin2025_03", "https://www.nta.go.jp/users/gensen/2025tsukin/pdf/03.pdf", "IMPL2_tsukin_nta/pages3/fetch_log.json", []),
    ("tsukin2025_01", "https://www.nta.go.jp/users/gensen/2025tsukin/pdf/01.pdf", "IMPL2_tsukin_nta/pdfs/fetch_log.json", []),
]


def get(url, accept=None):
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st, hd = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        body, st, hd = e.read(), e.code, dict(e.headers or {})
    time.sleep(WAIT)
    return st, body, hd


def xml_text(fragment):
    fragment = re.sub(r"<Rt>.*?</Rt>", "", fragment, flags=re.S)
    t = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", "", t)


def main_part(xml):
    """本則（MainProvision の要素の中。目次の TOCSupplProvision・SupplProvisionLabel に引っかからないようにする）。"""
    m = re.search(r"<MainProvision[^>]*>.*?</MainProvision>", xml, flags=re.S)
    return m.group(0) if m else ""


def article(xml, num):
    m = re.search(rf'<Article Num="{re.escape(num)}"[^>]*>.*?</Article>', main_part(xml), flags=re.S)
    return xml_text(m.group(0)) if m else None


def suppl(xml, amend):
    ms = re.findall(rf'<SupplProvision[^>]*AmendLawNum="{re.escape(amend)}"[^>]*>.*?</SupplProvision>', xml, flags=re.S)
    return xml_text("".join(ms)) if ms else None


def first_sha(rel, item_id):
    p = ROOT / "scripts" / "results" / rel
    if not p.exists():
        return None
    for it in json.loads(p.read_text(encoding="utf-8"))["items"]:
        if it["id"] == item_id:
            return it.get("sha256")
    return None


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_tsukin_verify"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "articles": [], "suppl": [], "revisions": {}, "nta": []}
    cache = {}

    def law_xml(law_id, asof):
        key = (law_id, asof)
        if key not in cache:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "xml", "asof": asof})
            st, body, _ = get(url, "application/xml")
            (dl / f"{law_id}_{asof}.xml").write_bytes(body)
            x = body.decode("utf-8", "replace")
            rid = re.search(r"<law_revision_id>(.*?)</law_revision_id>", x)
            cache[key] = (url, st, x, hashlib.sha256(body).hexdigest(), rid.group(1) if rid else None)
        return cache[key]

    for name, law_id, asof, num, must, must_not in ARTICLE_CHECKS:
        url, st, x, sha, rid = law_xml(law_id, asof)
        t = article(x, num)
        r = {"check": name, "url": url, "status": st, "sha256": sha, "law_revision_id": rid, "found_article": t is not None}
        r["must"] = {m: (t is not None and re.sub(r"\s+", "", m) in t) for m in must}
        r["must_not"] = {m: (t is not None and re.sub(r"\s+", "", m) in t) for m in must_not}
        if num == "2_2" and not must:
            r["ok"] = st == 200 and (t is None or not any(r["must_not"].values()))
        else:
            r["ok"] = st == 200 and t is not None and all(r["must"].values()) and not any(r["must_not"].values())
        res["articles"].append(r)
        print(r["ok"], name, rid, flush=True)

    for name, law_id, asof, amend, must, must_not in SUPPL_CHECKS:
        url, st, x, sha, rid = law_xml(law_id, asof)
        t = suppl(x, amend)
        r = {"check": name, "url": url, "law_revision_id": rid, "found": t is not None,
             "must": {m: (t is not None and re.sub(r"\s+", "", m) in t) for m in must}}
        r["ok"] = t is not None and all(r["must"].values())
        res["suppl"].append(r)
        print(r["ok"], name, flush=True)

    # 改正履歴：所得税法施行規則（第2条の2 の施行日）と所得税法施行令（2026-11-11 以後に予定された改正の有無）
    for law_id in (KI, REI):
        url = f"{API}/law_revisions/{law_id}?response_format=json"
        st, body, _ = get(url, "application/json")
        (dl / f"revisions_{law_id}.json").write_bytes(body)
        revs = json.loads(body).get("revisions", []) if st == 200 else []
        keep = [{k: r.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date", "current_revision_status", "updated")}
                for r in revs if (r.get("amendment_enforcement_date") or "") >= "2025-01-01"]
        res["revisions"][law_id] = {"url": url, "status": st, "rows_since_2025": keep}

    for name, url, rel, must in NTA_PAGES:
        st, body, hd = get(url)
        is_pdf = url.endswith(".pdf")
        fn = dl / (name + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        sha = hashlib.sha256(body).hexdigest()
        prev = first_sha(rel, name)
        r = {"name": name, "url": url, "status": st, "last_modified": hd.get("Last-Modified"), "sha256": sha,
             "first_fetch_sha256": prev, "same_as_first_fetch": sha == prev}
        if not is_pdf and st == 200:
            cs = re.search(rb"charset=[\"']?([A-Za-z0-9_\-]+)", body[:2048])
            enc = cs.group(1).decode().lower() if cs else "utf-8"
            text = body.decode("cp932" if enc in ("shift_jis", "sjis", "x-sjis") else enc, "replace")
            r["encoding"] = enc
            t = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", text))
            r["must"] = {m: re.sub(r"\s+", "", m) in t for m in must}
            r["ok"] = all(r["must"].values())
        else:
            r["ok"] = st == 200 and body[:5] == b"%PDF-"
        res["nta"].append(r)
        print(r["ok"], name, "same" if r["same_as_first_fetch"] else "CHANGED", flush=True)

    res["all_ok"] = all(r["ok"] for k in ("articles", "suppl", "nta") for r in res[k])
    (OUT / "verify.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("all_ok", res["all_ok"])


if __name__ == "__main__":
    main()
