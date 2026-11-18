"""IMPL2 kyuyo-jiki の独立検証：公開資料の情報の文書（docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md）の主張を、
最初の取得とは別の経路で一次情報に当たり直して確かめる。反証（主張と食い違う本文）を探す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_kyuyo-jiki_verify.py

最初の取得（scripts/IMPL2_kyuyo-jiki_egov.py・IMPL2_kyuyo-jiki_nta.py）との違い
- e-Gov は response_format=xml で取り、XML の文字列から正規表現で条を切り出し、タグを外して読む（scripts/IMPL2_tsukin_verify.py と同じ方法。
  import はしない）。時点は 2025-01-01（令和7年分の初日）と 2027-01-01 も足す（年分の範囲で条文が変わっていないかを見るため）。
- 国税庁のページは新しいディレクトリに取り直し、最初の取得の SHA-256 と比べ、文字コードを宣言どおりに読んで文字列を照合する。
- 反証の探索：所基通36−9 のページに「支払を受けた日」を原則とする書き方がないか（MUST_NOT）、相基通3−33 が「退職手当金等に該当する」と
  していないか、質疑応答事例が「支払日」で年分を決めるとしていないかを、含まれてはならない文字列として調べる。

ダウンロード先：.work/downloads/<YYYYMMDD-HHMMSS>_IMPL2_kyuyo-jiki_verify/（新しい空のディレクトリ。中では何も実行しない）。
出力：scripts/results/IMPL2_kyuyo-jiki_verify/verify.json。リクエストの間は 1.5 秒。User-Agent は okura-gov-research/0.1。
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
OUT = ROOT / "scripts" / "results" / "IMPL2_kyuyo-jiki_verify"
HO, SOZOKU = "340AC0000000033", "325AC0000000073"

ARTICLE_CHECKS = []
for asof in ("2025-01-01", "2026-11-11", "2027-01-01"):
    ARTICLE_CHECKS += [
        (f"V1 所法36① {asof}", HO, asof, "36", ["別段の定めがあるものを除き、その年において収入すべき金額"], []),
        (f"V1 所法183② {asof}", HO, asof, "183", ["支払の確定した日から一年を経過した日までにその支払がされない場合には、その一年を経過した日においてその支払があつたものとみなして"], []),
        (f"V1 所法190一 {asof}", HO, asof, "190", ["その年中にその居住者に対し支払うべきことが確定した給与等"], []),
        (f"V1 所法9①十七 {asof}", HO, asof, "9", ["相続、遺贈又は個人からの贈与により取得するもの"], []),
        (f"V1 所法28① {asof}", HO, asof, "28", ["給与所得とは、俸給、給料、賃金、歳費及び賞与並びにこれらの性質を有する給与"], []),
    ]
ARTICLE_CHECKS += [
    ("V2 相続税法3①二 2026-11-11", SOZOKU, "2026-11-11", "3", ["被相続人に支給されるべきであつた退職手当金、功労金その他これらに準ずる給与", "被相続人の死亡後三年以内に支給が確定したもの"], []),
]
NTA_PAGES = [
    ("kihon_05_01", "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/05/01.htm", "IMPL2_kyuyo-jiki_nta/pages/fetch_log.json",
     ["契約又は慣習その他株主総会の決議等により支給日が定められている給与等（次の(2)に掲げるものを除く。）についてはその支給日、その日が定められていないものについてはその支給を受けた日",
      "その支給日が定められているものについてはその支給日、その日が定められていないものについてはその改訂の効力が生じた日"],
     ["給与所得の収入金額の収入すべき時期は、その支給を受けた日によるものとする"]),
    ("kihon_02_04", "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/02/04.htm", "IMPL2_kyuyo-jiki_nta/pages/fetch_log.json",
     ["その死亡後に支給期の到来するもののうち相続税法の規定により相続税の課税価格計算の基礎に算入されるものについては、課税しないものとする",
      "支給期については、36－9、36－10及び36－14の(1)に定めるところによる"], []),
    ("sokihon_01_03", "https://www.nta.go.jp/law/tsutatsu/kihon/sisan/sozoku2/01/03.htm", "IMPL2_kyuyo-jiki_nta/pages/fetch_log.json",
     ["相続開始の時において支給期の到来していない俸給、給料等は、法第3条第1項第2号に規定する退職手当金等には該当しないで、本来の相続財産に属するものであるから留意する"], []),
    ("shitsugi_hotei_7_05", "https://www.nta.go.jp/law/shitsugi/hotei/7/05.htm", "IMPL2_kyuyo-jiki_nta/pages/fetch_log.json",
     ["その死亡後に支給期の到来するものについては、本来の相続財産として、相続税の課税対象となるため", "死亡時までに支給期の到来している給与等については", "所得税法基本通達36－9に定めるところによります"],
     ["支払日の属する年"]),
    ("shitsugi_hotei_7_16", "https://www.nta.go.jp/law/shitsugi/hotei/7/16.htm", "IMPL2_kyuyo-jiki_nta/pages/fetch_log.json",
     ["死亡前に支払が確定している給与の合計額を記載します"], []),
    ("kihon_31_01", "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/31/01.htm", "IMPL2_kyuyo-jiki_nta/pages/fetch_log.json",
     ["その支払の確定した日（36－9に定める日をいう。）の属する年の翌年の応当日の翌日"], []),
    ("kihon_32_01", "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/32/01.htm", "IMPL2_kyuyo-jiki_nta/pages/fetch_log.json",
     ["給与等の支払を受ける者が死亡により退職した場合"], []),
    ("tebikihtml_2_3_4", "https://www.nta.go.jp/publication/pamph/hotei/tebikihtml/2-3-4.htm", "IMPL2_tsukin_nta/pages3/fetch_log.json",
     ["令和８年中に支払の確定した給与等", "未払のものがあるときは、その未払額を内書きしてください"], []),
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
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", fragment))


def article(xml, num):
    m = re.search(r"<MainProvision[^>]*>.*?</MainProvision>", xml, flags=re.S)
    main = m.group(0) if m else ""
    a = re.search(rf'<Article Num="{re.escape(num)}"[^>]*>.*?</Article>', main, flags=re.S)
    return xml_text(a.group(0)) if a else None


def first_sha(rel, item_id):
    p = ROOT / "scripts" / "results" / rel
    if not p.exists():
        return None
    for it in json.loads(p.read_text(encoding="utf-8"))["items"]:
        if it["id"] == item_id:
            return it.get("sha256")
    return None


def decode_html(body):
    cs = re.search(rb"charset=[\"']?([A-Za-z0-9_\-]+)", body[:2048])
    enc = cs.group(1).decode().lower() if cs else "utf-8"
    return body.decode("cp932" if enc in ("shift_jis", "sjis", "x-sjis") else enc, "replace"), enc


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_kyuyo-jiki_verify"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "articles": [], "nta": []}
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
        r = {"check": name, "url": url, "status": st, "sha256": sha, "law_revision_id": rid, "found_article": t is not None,
             "must": {m: (t is not None and re.sub(r"\s+", "", m) in t) for m in must},
             "must_not": {m: (t is not None and re.sub(r"\s+", "", m) in t) for m in must_not}}
        r["ok"] = st == 200 and t is not None and all(r["must"].values()) and not any(r["must_not"].values())
        res["articles"].append(r)
        print(r["ok"], name, rid, flush=True)

    for name, url, rel, must, must_not in NTA_PAGES:
        st, body, hd = get(url)
        (dl / (name + ".htm")).write_bytes(body)
        sha = hashlib.sha256(body).hexdigest()
        prev = first_sha(rel, name)
        text, enc = decode_html(body)
        t = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", text))
        r = {"name": name, "url": url, "status": st, "last_modified": hd.get("Last-Modified"), "sha256": sha, "encoding": enc,
             "first_fetch_sha256": prev, "same_as_first_fetch": sha == prev,
             "must": {m: re.sub(r"\s+", "", m) in t for m in must},
             "must_not": {m: re.sub(r"\s+", "", m) in t for m in must_not}}
        r["ok"] = st == 200 and all(r["must"].values()) and not any(r["must_not"].values())
        res["nta"].append(r)
        print(r["ok"], name, "same" if r["same_as_first_fetch"] else "CHANGED", flush=True)

    res["all_ok"] = all(r["ok"] for k in ("articles", "nta") for r in res[k])
    (OUT / "verify.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("all_ok", res["all_ok"])


if __name__ == "__main__":
    main()
