"""IMPL3 verify: impl-research3 の文書に書いた主な値・規則を、一次情報に当たり直して確かめ、反証を探す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_verify.py

- 取得の経路を変えて確かめる：本文の取り出し（scripts/IMPL3_egov_fetch.py）は JSON を描画したが、ここでは e-Gov 法令API v2 の
  /law_data を response_format=xml で取り直し、タグを除いた本文の中に、文書に書いた語句がそのまま（又は数字の並びとして）あるかを見る。
  あわせて /law_revisions を取り直し、令和9年度（2027-04-01）に施行される国保令・地方税法施行令・国年令の改正が新たに出ていないかを見る。
- 国税庁の「国外居住親族に係る扶養控除等Q&A」の別の版（0022009-107_01.pdf）を取得し、「国内源泉所得」「国外」の語の有無を数える
  （非居住者の親族の合計所得金額の計算に触れた説明があれば、仮説を覆す材料になる）。PDF のテキスト化は scripts/IMPL3_pdftext.py で別に行う。
- 取得したものは .work/downloads/<YYYYMMDD-HHMMSS>_IMPL3_verify/ に置く（信頼できないデータ。中で何も実行しない）。
- 出力：scripts/results/IMPL3_verify/verify.json（各検査の期待、見つかったか、取得の版・SHA-256）
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
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
SLEEP = 1.5
NAME = "IMPL3_verify"
OUT = ROOT / "scripts" / "results" / NAME

# (id, law_id, asof, [期待する語句（タグを除いた本文に含まれること）], [含まれないこと（反証の語句）])
XML_CHECKS = [
    ("V1 所令134 95%・五で除す R7", "340CO0000000096", "2025-12-31",
     ["その取得価額（減価償却資産の償却費の額の計算の基礎となる取得価額をいい", "の百分の九十五に相当する金額", "を五で除して計算した金額"], []),
    ("V1 所令134 95%・五で除す R8", "340CO0000000096", "2026-12-31",
     ["の百分の九十五に相当する金額", "を五で除して計算した金額"], []),
    ("V1b 所令120 旧定額法・旧定率法の定義 R8", "340CO0000000096", "2026-12-31",
     ["旧定額法（当該減価償却資産の取得価額からその残存価額を控除した金額にその償却費が毎年同一となるように",
      "旧定率法（当該減価償却資産の取得価額（第二年目以後の償却の場合にあつては"], []),
    ("V1c 所令205 62万円 R8・58万円 R7", "340CO0000000096", "2026-12-31", ["山林所得金額の合計額が六十二万円以下であるもの"], []),
    ("V1c 所令205 58万円 R7", "340CO0000000096", "2025-12-31", ["山林所得金額の合計額が五十八万円以下であるもの"], []),
    ("V2 耐用年数省令 別表 R8", "340M50000040015", "2026-12-31",
     ["一〇〇・一〇〇〇・二〇六", "一〇〇・二〇〇〇・二五〇〇・〇六五五二", "一〇〇・二五〇〇・三三四〇・〇四四四八"], []),
    ("V3 所法 別表第二 R8（105,000円未満・170・3,700）", "340AC0000000033", "2026-12-31",
     ["１０５，０００円未満", "１０５，０００１０７，０００１７００００００００３，７００"], []),
    ("V3 所法 別表第二 R7（88,000円未満・130・3,100）", "340AC0000000033", "2025-12-31",
     ["８８，０００円未満", "８８，０００８９，０００１３００００００００３，１００"], []),
    ("V4 措令4の2⑨ と 25の11の2⑳ に所令205 R8", "332CO0000000043", "2026-12-31",
     ["第二百四条第一項第二号、第二百五条、第二百十九条第二項第二号、第二百二十一条の三第二項",
      "第百七十九条第一号イ及び第二号イ、第百八十条第二項第一号、第二百四条第一項第二号、第二百五条並びに第二百十九条第二項第二号"], []),
    ("V4 同 R7", "332CO0000000043", "2025-12-31",
     ["第二百四条第一項第二号、第二百五条、第二百十九条第二項第二号、第二百二十一条の三第二項",
      "第百七十九条第一号イ及び第二号イ、第百八十条第二項第一号、第二百四条第一項第二号、第二百五条並びに第二百十九条第二項第二号"], []),
    ("V4b 措法41の2の2⑥二 所法120の読替え R8", "332AC0000000026", "2026-12-31",
     ["同項中「配当控除の額」とあるのは、「配当控除の額と租税特別措置法第四十一条の二の二第一項（年末調整に係る住宅借入金等を有する場合の所得税額の特別控除）の規定により控除される金額との合計額」とする"], []),
    ("V6 国保令29の7 限度額 R9年度の版", "333CO0000000362", "2027-04-01",
     ["基礎賦課額は、六十七万円を超えることができない", "後期高齢者支援金等賦課額は、二十六万円を超えることができない",
      "介護納付金賦課額は、十七万円を超えることができない", "子ども・子育て支援納付金賦課額は、三万円を超えることができない"], []),
    ("V6b 地令56の88の2 R9年度の版", "325CO0000000245", "2027-04-01",
     ["法第七百三条の四第十一項に規定する政令で定める金額は、六十七万円とする"], []),
    ("V7 地法 改正附則：314の7⑪・附則5の5②は令和10年度以後", "325AC0000000226", "2027-04-01",
     ["第三百十四条の七第十一項及び附則第五条の五第二項の規定は、令和十年度以後の年度分の個人の市町村民税について適用し"], []),
    ("V7b 地法703の4・703の5（国保税）の改正は令和9年度以後", "325AC0000000226", "2027-04-01",
     ["改正後の地方税法第七百三条の四及び第七百三条の五の規定は、令和九年度以後の年度分の国民健康保険税について適用し"], []),
    ("V8 国年令6の8 135万円・6の7の2", "334CO0000000184", "2026-04-01",
     ["法第九十条第一項第三号に規定する政令で定める額は、百三十五万円とする",
      "地方税法第二百九十二条第一項第十号に規定する障害者、同項第十一号に規定する寡婦及び同項第十二号に規定するひとり親とする"], []),
    ("V8b 国年法90の2・90の3 の第2号の文言", "334AC0000000141", "2026-04-01",
     ["二前条第一項第二号及び第三号に該当するとき。", "二第九十条第一項第二号及び第三号に該当するとき。",
      "平成二十八年七月から令和十七年六月までの期間において、五十歳に達する日の属する月の前月までの被保険者期間"], []),
]
REVISION_CHECKS = [("333CO0000000362", "国保令"), ("325CO0000000245", "地方税法施行令"), ("334CO0000000184", "国年令")]
WEB = {
    "kokugai_qa_01": "https://www.nta.go.jp/publication/pamph/pdf/0022009-107_01.pdf",
    "soumu_code_page": "https://www.soumu.go.jp/denshijiti/code.html",
    "nta_sanrin_31_32": "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/710826/sanrin/sanjyou/soti31/02.htm",
}


def get(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    dest.write_bytes(body)
    time.sleep(SLEEP)
    return st, body


def plain(xml_bytes):
    t = xml_bytes.decode("utf-8", "replace")
    t = re.sub(r"<Rt>.*?</Rt>", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", "", t)


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "xml": [], "revisions": [], "web": []}
    cache = {}
    for cid, law_id, asof, must, mustnot in XML_CHECKS:
        key = (law_id, asof)
        if key not in cache:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "xml", "asof": asof})
            st, body = get(url, dl / f"{law_id}_{asof}.xml")
            rid = re.search(rb"<law_revision_id>([^<]+)</law_revision_id>", body)
            cache[key] = (url, st, plain(body), hashlib.sha256(body).hexdigest(), rid.group(1).decode() if rid else None)
        url, st, text, sha, rid = cache[key]
        found = {m: (re.sub(r"\s+", "", m) in text) for m in must}
        absent = {m: (re.sub(r"\s+", "", m) not in text) for m in mustnot}
        res["xml"].append({"id": cid, "url": url, "status": st, "law_revision_id": rid, "sha256": sha,
                           "found": found, "absent": absent, "ok": all(found.values()) and all(absent.values())})
        print(("OK " if res["xml"][-1]["ok"] else "NG ") + cid, rid, flush=True)
    for law_id, name in REVISION_CHECKS:
        url = f"{API}/law_revisions/{law_id}?response_format=json"
        st, body = get(url, dl / f"revisions_{law_id}.json")
        revs = json.loads(body).get("revisions", []) if st == 200 else []
        later = [{"enf": r.get("amendment_enforcement_date"), "law": r.get("amendment_law_num"), "promulgated": r.get("amendment_promulgate_date"),
                  "status": r.get("current_revision_status")} for r in revs if (r.get("amendment_enforcement_date") or "") >= "2027-01-01"]
        res["revisions"].append({"law": name, "url": url, "status": st, "enforced_2027_or_later": later})
        print("revisions", name, later, flush=True)
    for key, url in WEB.items():
        st, body = get(url, dl / (key + (".pdf" if url.endswith(".pdf") else ".htm")))
        item = {"id": key, "url": url, "status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                "saved": str((dl / (key + (".pdf" if url.endswith(".pdf") else ".htm"))).relative_to(ROOT)).replace("\\", "/")}
        if not url.endswith(".pdf"):
            m = re.search(rb"charset=[\"']?([A-Za-z0-9_\-]+)", body[:2048])
            enc = (m.group(1).decode() if m else "utf-8").lower()
            enc = "cp932" if enc in ("shift_jis", "sjis", "x-sjis") else enc
            t = re.sub(r"<[^>]+>", "", body.decode(enc, "replace"))
            item["encoding"] = enc
            item["contains"] = {w: (w in t) for w in ["令和6年1月1日更新", "000925835.xlsx", "上場株式等に係る配当所得等の金額", "これと同様に取り扱う"]}
        res["web"].append(item)
        print("web", key, st, len(body), item.get("contains"), flush=True)
    (OUT / "verify.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()
