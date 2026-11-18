"""IMPL2 phase2c の独立検証：docs/*/20261111_impl-research_* の主張を、最初の取得とは別の経路で一次情報に当たり直して確かめ、反証を探す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_phase2c_verify.py

最初の取得（scripts/IMPL2_phase2c_egov.py・IMPL2_phase2c_nta.py）との違い
- e-Gov は response_format=xml で取り、XML の文字列から正規表現で条を切り出し、タグを外して読む（JSON の木のテキスト化を通らない）。
- 国税庁のページは新しいディレクトリに取り直し、最初の取得の SHA-256 と比べ、本文の文字列を照合する。
- 主張ごとに「含まれるべき文字列」「含まれてはならない文字列」を書く。

ダウンロード先：.work/downloads/<YYYYMMDD-HHMMSS>_IMPL2_phase2c_verify/（新しい空のディレクトリ。中では何も実行しない）。
出力：scripts/results/IMPL2_phase2c_verify/verify.json。リクエストの間は 1.5 秒。User-Agent は okura-gov-research/0.1。
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
OUT = ROOT / "scripts" / "results" / "IMPL2_phase2c_verify"
HO, REI, SO, SOREI = "340AC0000000033", "340CO0000000096", "332AC0000000026", "332CO0000000043"
R7, R8 = "2025-12-31", "2026-12-31"
NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
TEB = NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/03/"
KEISAN = "https://www.keisan.nta.go.jp/r7yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/"
FORM = NTA + "/taxes/shiraberu/shinkoku/yoshiki/04/pdf/"

# (検査, law_id, asof, 条の Num, 含まれるべき文字列, 含まれてはならない文字列)。空白を除いて照合する
A = "当該金額に百円未満の端数があるときは、これを切り捨てる。"
LAW = [
    ("seito 措法41の18 R7", SO, R7, "41_18", ["その超える金額の百分の三十に相当する金額（" + A + "）を控除する", "百分の二十五に相当する金額（" + A + "）を限度とする", "令和十一年十二月三十一日"], ["特定政党支部"]),
    ("seito 措法41の18 R8", SO, R8, "41_18", ["特定政党支部", "その超える金額の百分の三十に相当する金額（" + A + "）を控除する", "百分の二十五に相当する金額（" + A + "）を限度とする"], []),
    ("seito 措法41の18の2 R7", SO, R7, "41_18_2", ["その超える金額の百分の四十に相当する金額（" + A + "）を控除する", "次条第一項の規定の適用がある場合には、当該百分の二十五に相当する金額から同項の規定により控除する金額を控除した残額"], []),
    ("seito 措法41の18の2 R8", SO, R8, "41_18_2", ["その超える金額の百分の四十に相当する金額（" + A + "）を控除する", "次条第一項の規定の適用がある場合には、当該百分の二十五に相当する金額から同項の規定により控除する金額を控除した残額"], []),
    ("seito 措法41の18の3 R8", SO, R8, "41_18_3", ["その超える金額の百分の四十に相当する金額（" + A + "）を控除する", "百分の二十五に相当する金額（" + A + "）を限度とする"], []),
    ("seito 措令26の27の4 R8", SOREI, R8, "26_27_4", ["所得税法第九十二条第一項に規定する所得税額から控除する"], []),
    ("haito 所法24 R8", HO, R8, "24", ["配当所得の金額は、その年中の配当等の収入金額とする", "その年においてその元本を有していた期間に対応する部分の金額"], []),
    ("haito 所令59 R8", REI, R8, "59", ["十二で除し、これにその年において当該負債により取得した元本を有していた期間の月数を乗じて計算した金額", "一月に満たない端数を生じたときは、これを一月とする"], []),
    ("haito 所法92 R7", HO, R7, "92", ["その年分の課税総所得金額が千万円以下である場合", "百分の十を乗じて計算した金額", "百分の二・五", "当該控除をすべき金額がその年分の所得税額をこえるときは、当該控除をすべき金額は、当該所得税額に相当する金額とする"], ["端数"]),
    ("haito 所法92 R8", HO, R8, "92", ["その年分の課税総所得金額が千万円以下である場合", "百分の十を乗じて計算した金額", "百分の二・五", "当該控除をすべき金額がその年分の所得税額をこえるときは、当該控除をすべき金額は、当該所得税額に相当する金額とする"], ["端数"]),
    ("joto 所法87 R8", HO, R8, "87", ["順次控除する"], []),
    ("joto 措法8の4③三 R8", SO, R8, "8_4", ["所得税法第七十一条及び第七十二条から第八十七条までの規定の適用については、これらの規定中「総所得金額」とあるのは、「総所得金額、上場株式等に係る配当所得等の金額」とする"], []),
    ("joto 措法37の10⑥五 R8", SO, R8, "37_10", ["所得税法第七十一条及び第七十二条から第八十七条までの規定の適用については、これらの規定中「総所得金額」とあるのは、「総所得金額、一般株式等に係る譲渡所得等の金額」とする"], []),
    ("joto 措法37の11⑥ R8", SO, R8, "37_11", ["「一般株式等に係る譲渡所得等の金額」とあるのは「上場株式等に係る譲渡所得等の金額」"], []),
    ("joto 措令4の2⑧ R8", SOREI, R8, "4_2", ["総所得金額、上場株式等に係る配当所得等の金額若しくは", "第百二十一条第一項及び第三項"], []),
    ("joto 措令25の11の2⑳ R8", SOREI, R8, "25_11_2", ["総所得金額、上場株式等に係る配当所得等の金額、上場株式等に係る譲渡所得等の金額"], []),
    ("joto 所令204 R8", REI, R8, "204", ["総所得金額、山林所得金額又は退職所得金額から順次控除する", "まず、法第六十九条（損益通算）及び第七十条の規定による控除を行つた後、法第七十一条第一項の規定による控除を行う"], []),
    ("121 所法121① R7", HO, R7, "121", ["二千万円以下", "二十万円以下", "百五十万円", "一の給与等の支払者から給与等の支払を受け", "二以上の給与等の支払者", "従たる給与等", "四百万円以下"], []),
    ("121 所法121① R8", HO, R8, "121", ["二千万円以下", "二十万円以下", "百五十万円", "特定親族特別控除の額", "四百万円以下"], []),
    ("gensen 所法120①四 R8", HO, R8, "120", ["源泉徴収をされた又はされるべき所得税の額"], []),
    ("hasu 所法76 R8", HO, R8, "76", [], ["端数"]),
    ("hasu 所法77 R8", HO, R8, "77", [], ["端数"]),
    ("genka 所令120の2 R8", REI, R8, "120_2", [], ["一円未満"]),
    ("genka 所令132 R8", REI, R8, "132", ["一月に満たない端数を生じたときは、これを一月とする"], ["一円未満"]),
    ("genka 所令134 R8", REI, R8, "134", [], ["一円未満"]),
    ("genka 所令139 R8", REI, R8, "139", [], ["一円未満"]),
    ("fudosan 措法41の4 R8", SO, R8, "41_4", ["を取得するために要した負債の利子の額があるときは", "所得税法第六十九条第一項の規定その他の所得税に関する法令の規定の適用については、生じなかつたものとみなす"], []),
]
# (名前, URL, 最初の取得の set, 最初の取得の id, 含まれるべき, 含まれてはならない)
PAGES = [
    ("3-3_12 生命保険料", TEB + "order3/3-3_12.htm", "sha:e7347b85a2a141529e8cdda2cb5926c69a5558933eab259fa08ca11e836876b5", None, ["控除額の計算において算出した金額に1円未満の端数があるときは、その端数を切り上げて差し支えありません。"], ["切り捨て"]),
    ("3-3_13 地震保険料", TEB + "order3/3-3_13.htm", "sha:3a8904729a63b8e9bf8e88915098156bb34360a83ea56e34ae2613de9446673a", None, ["控除額の計算において算出した金額に1円未満の端数があるときは、その端数を切り上げて差し支えありません。"], ["切り捨て"]),
    ("3-2_07 公的年金等", TEB + "order2/3-2_07.htm", "tebiki_html", "t3_2_07", ["1円未満の端数があるときは、その端数を切り捨てます。"], ["切り上げ"]),
    ("3-4_28 配当控除", TEB + "order4/3-4_28.htm", "tebiki_html", "t3_4_28", ["他の所得の赤字と損益通算する前の配当所得の金額です", "申告分離課税の所得のうち、山林所得・退職所得以外の所得がある場合は"], []),
    ("3-4_38 源泉徴収税額", TEB + "order4/3-4_38.htm", "tebiki_html", "t3_4_38", ["確定申告をしないことを選択した配当所得等などに係る所得税等の源泉徴収税額は、控除できません", "申告分離課税の上場株式等の配当所得等、株式等の譲渡所得等を併せて申告する場合は"], []),
    ("TA1260 政党等", TA + "1260.htm", "ta", "ta_1260", ["令和8年1月1日以後にする公職の候補者が特定政党支部に対してする寄附以外のもの", "25パーセント相当額（100円未満の端数があれば切り捨てます。）を限度", "2,000円からその特定寄附金等の額の合計額を控除した残額"], []),
    ("TA1263 認定NPO", TA + "1263.htm", "ta", "ta_1263", ["25パーセント相当額から公益社団法人等寄附金特別控除額を控除した残額"], []),
    ("TA1250 配当控除", TA + "1250.htm", "ta", "ta_1250", ["配当控除の金額は算出税額を限度", "確定申告不要制度を選択したもの", "申告分離課税制度を選択したもの"], []),
    ("TA1330 配当所得", TA + "1330.htm", "ta", "ta_1330", ["確定申告不要制度を選択した配当所得に係る源泉徴収税額は、その年分の所得税額から差し引くことはできません"], []),
    ("TA1900", TA + "1900.htm", "ta", "ta_1900", ["2,000万円を超える人", "年末調整されなかった給与の収入金額", "源泉徴収義務のない者から給与等の支払を受けている人"], []),
    ("基通121", KIHON + "19/01.htm", "tsutatsu", "kihon_19_01", ["2以上の給与等の支払者から給与等の支払を受ける場合であっても、当該給与等の全部について法第190条", "確定申告書の提出又は確定申告書への記載若しくは明細書等の添付を要件として適用される特例等を適用しないで計算した"], []),
    ("基通24-5", KIHON + "04/01.htm", "tsutatsu2", "kihon_04_01", ["24-5", "株式等を取得するために要した負債の利子"], []),
    ("基通49（償却）", KIHON + "08/05.htm", "tsutatsu2", "kihon_08_05", ["49－1"], ["1円未満", "１円未満", "一円未満"]),
    ("FAQ 減価償却費の端数処理 R7", KEISAN + "hasushori.html", "genka_keisan", "keisan_r7_hasu", ["作成コーナーでは、減価償却費の計算で小数点以下の端数が生じた場合、切上げ処理を行っています。", "令和7年分"], ["切り捨て", "切捨て"]),
    ("TA2100 減価償却", TA + "2100.htm", "ta", "ta_2100", ["減価償却のあらまし"], ["1円未満", "１円未満"]),
    ("TA2106 定額法", TA + "2106.htm", "ta", "ta_2106", ["定額法"], ["1円未満", "１円未満"]),
    ("通基通119-6", NTA + "/law/tsutatsu/kihon/tsusoku/09/01/119.htm", "genka_keisan", "kobetsu_hasu_tsusoku_119", ["国税の確定金額を算出する過程におけるその算出額に、1円未満の端数があるときは、その端数金額を切り捨てるものとする"], []),
    ("TA1140 生命保険料", TA + "1140.htm", "nencho", "ta_1140", ["生命保険料控除"], ["端数"]),
    ("R8年調のしかた p.24 等", NTA + "/publication/pamph/gensen/nencho2026/pdf/107.pdf", "nencho", "nencho2026_107", [], []),
    ("退職源泉徴収票 源泉徴収税額欄", NTA + "/publication/pamph/hotei/tebikihtml/3-2-6.htm", "hotei2", "hotei_3_2_6", ["源泉徴収すべき所得税及び復興特別所得税の合計額"], []),
    ("r08 様式案内", NTA + "/taxes/shiraberu/shinkoku/syotoku/r08.htm", "index", "r08", ["指定されたページを表示できませんでした"], []),
    ("措通41の18", NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/41/17.htm", "tsutatsu2", "sochi_41_17", ["全額について同項の規定を適用しなければならない", "法第92条、第95条及び第165条の6の規定並びに", "を適用しないで計算したその年分の所得税額の100分の25に相当する金額"], []),
    ("様式 政党等", FORM + "06.pdf", "forms", "form_seito", [], []),
    ("様式 NPO", FORM + "09-1.pdf", "forms", "form_npo", [], []),
    ("様式 公益", FORM + "09-4.pdf", "forms", "form_koeki", [], []),
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


def article(xml, num):
    m = re.search(r"<MainProvision[^>]*>.*?</MainProvision>", xml, flags=re.S)
    main = m.group(0) if m else ""
    a = re.search(rf'<Article Num="{re.escape(num)}"[^>]*>.*?</Article>', main, flags=re.S)
    return xml_text(a.group(0)) if a else None


def decode(body):
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:2048])
    e = m.group(1).decode().lower() if m else "utf-8"
    if e in ("shift_jis", "sjis", "x-sjis"):
        e = "cp932"
    try:
        return body.decode(e, "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def clean(t):
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S | re.I)
    t = re.sub(r"<style.*?</style>", "", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"[\s\u3000]+", "", t)


def first_sha(setname, key):
    if not setname:
        return None
    if setname.startswith("sha:"):  # scripts/results/R2X_yoshiki_fetch/20261109-174731_tebiki の取得（2026-11-09）の SHA-256
        return setname[4:]
    p = ROOT / "scripts" / "results" / "IMPL2_phase2c_nta" / setname / "fetch_log.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for it in d["items"]:
        if it["id"] == key:
            return it["sha256"]
    return None


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_phase2c_verify"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "laws": [], "pages": [], "law_fetch": {}}
    cache = {}
    for name, law, asof, num, inc, exc in LAW:
        key = (law, asof)
        if key not in cache:
            url = f"{API}/law_data/{law}?" + urllib.parse.urlencode({"response_format": "xml", "asof": asof})
            st, body, _ = get(url)
            (dl / f"{law}_{asof}.xml").write_bytes(body)
            cache[key] = body.decode("utf-8", "replace")
            res["law_fetch"][f"{law}_{asof}"] = {"status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        txt = article(cache[key], num)
        if txt is None:
            res["laws"].append({"check": name, "num": num, "ok": False, "note": "条が見つからない"})
            print("FAIL", name, "条なし", flush=True)
            continue
        missing = [s for s in inc if re.sub(r"\s+", "", s) not in txt]
        present = [s for s in exc if re.sub(r"\s+", "", s) in txt]
        ok = not missing and not present
        res["laws"].append({"check": name, "num": num, "asof": asof, "ok": ok, "missing": missing, "must_not_contain_but_present": present})
        print("ok " if ok else "NG ", name, missing[:2], present[:2], flush=True)
    for name, url, setname, key, inc, exc in PAGES:
        st, body, hd = get(url)
        sha = hashlib.sha256(body).hexdigest()
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", url.split("/")[-1])
        (dl / f"{len(res['pages']):02d}_{safe}").write_bytes(body)
        same = (sha == first_sha(setname, key)) if setname else None
        if url.endswith(".pdf"):
            res["pages"].append({"check": name, "url": url, "status": st, "sha256": sha, "same_as_first_fetch": same, "ok": st == 200})
            print("ok " if st == 200 else "NG ", name, "pdf same=", same, flush=True)
            continue
        text = clean(decode(body))
        missing = [s for s in inc if re.sub(r"[\s\u3000]+", "", s) not in text]
        present = [s for s in exc if re.sub(r"[\s\u3000]+", "", s) in text]
        ok = st == 200 and not missing and not present
        res["pages"].append({"check": name, "url": url, "status": st, "sha256": sha, "same_as_first_fetch": same, "ok": ok,
                             "missing": missing, "must_not_contain_but_present": present})
        print("ok " if ok else "NG ", name, "same=", same, missing[:2], present[:2], flush=True)
    res["all_ok"] = all(x.get("ok") for x in res["laws"]) and all(x.get("ok") for x in res["pages"])
    (OUT / "verify.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("all_ok", res["all_ok"])


if __name__ == "__main__":
    main()
