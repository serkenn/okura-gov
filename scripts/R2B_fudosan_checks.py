"""R2B_fudosan_checks: 不動産所得（第2ラウンド追加分、トピック fudosan）の機械的な確認。ネットワークは使わない。

実行（リポジトリのルートで）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_fudosan_checks.py

入力（先に次のスクリプトを実行しておく）
- scripts/results/R2B_fudosan_laws/      （scripts/R2B_fudosan_laws.py：e-Gov 法令API v2 の条文）
- scripts/results/R2B_fudosan_nta/       （scripts/R2B_fudosan_nta.py：国税庁の通達・タックスアンサー・質疑応答事例）
- scripts/results/R2B_fudosan_pdftext/   （scripts/R2B_fudosan_pdftext.py：様式・書き方の PDF の文字）

確認すること
- C1 条ごとの本文が時点（asof）の間で同じか（令和7年分＝2025-12-31、令和8年分＝2026-12-31、令和9年分＝2027-01-01）
- C2 条文の文言（事業／業務の別、「生じなかつたものとみなす」、損益通算の順序など）
- C3 年分ごとの基準額（勤労学生・扶養親族の合計所得金額）と、勤労学生の「給与所得等」に不動産所得が入らないこと
- C4 一次情報に書かれた計算を関数にして、出典にある数値例で検査する（措令26の6①、書き方の例、措法25の2の限度、所法57③）
- C5 様式（収支内訳書・青色申告決算書の不動産所得用、令和7年分）の欄コードと科目名の対応
- C6 国税庁の通達・タックスアンサー・書き方の文言
出力：scripts/results/R2B_fudosan_checks/checks.json（各確認の結果と根拠のファイル）
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAWS = ROOT / "scripts" / "results" / "R2B_fudosan_laws"
NTA = ROOT / "scripts" / "results" / "R2B_fudosan_nta"
PDF = ROOT / "scripts" / "results" / "R2B_fudosan_pdftext"
OUT = ROOT / "scripts" / "results" / "R2B_fudosan_checks"

RESULTS = []


def check(cid, desc, ok, evidence):
    RESULTS.append({"id": cid, "desc": desc, "ok": bool(ok), "evidence": evidence})
    print(("OK  " if ok else "NG  ") + cid + " " + desc, flush=True)


def articles(short, asof):
    """<略称>_<asof>.txt を「## 本則 Num=xx」ごとに分ける（ヘッダ行は除く）。"""
    t = (LAWS / f"{short}_{asof}.txt").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^## (本則|原始附則) Num=(\S+)\n(.*?)(?=^## |\Z)", t, re.S | re.M):
        out[m.group(2)] = m.group(3).strip()
    return out


def header(short, asof):
    t = (LAWS / f"{short}_{asof}.txt").read_text(encoding="utf-8").splitlines()
    return t[1]


KANJI = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kanji_man(s):
    """「八十五万」のような漢数字（万円単位の前の部分）を整数にする（十・百のみ対応）。"""
    n, cur = 0, 0
    for ch in s:
        if ch in KANJI:
            cur = KANJI[ch]
        elif ch == "十":
            n += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            n += (cur or 1) * 100
            cur = 0
    return (n + cur) * 10000


# ---------------------------------------------------------------- C4 の関数（一次情報の文言をそのまま式にしたもの）
def sochirei_26_6_disallowed(loss, interest):
    """措令26の6①：不動産所得の損失 loss（正の数）と、必要経費に算入した土地等の負債の利子 interest から、
    生じなかったものとみなす金額を返す。一号：利子＞損失 → 損失の金額。二号：利子≦損失 → 利子の額。"""
    if loss <= 0:
        return 0
    return loss if interest > loss else interest


def fudosan_for_tsusan(income, interest):
    """収支内訳書の書き方（令和7年分）p.3：⑮（所得金額）が赤字で土地等の負債の利子がある場合に、
    申告書第一表の「不動産③」に書く額。income は⑮（赤字なら負）。"""
    if income >= 0:
        return income
    return income + sochirei_26_6_disallowed(-income, interest)


def aoiro_tokubetsu_kojo(cap, fudosan, jigyo, sanrin=0):
    """措法25の2①二（令和7・8年分の第1項）・TA 2072（注2）（注3）：控除額は cap と「不動産・事業（・山林）の所得の合計額
    （損益通算前。赤字の所得は0とする）」の少ない方。不動産所得の金額、事業所得の金額（、山林所得の金額）から順に控除する。"""
    parts = [max(fudosan, 0), max(jigyo, 0), max(sanrin, 0)]
    total = min(cap, sum(parts))
    res, rest = [], total
    for p in parts:
        d = min(p, rest)
        res.append(d)
        rest -= d
    return total, res


def jigyo_senjusha_kojo(is_spouse, income_before, n_senjusha):
    """所法57③：事業専従者ごとに、一 配偶者86万円・それ以外50万円、二 所得÷(専従者の数＋1) のいずれか低い金額。"""
    a = 860_000 if is_spouse else 500_000
    b = income_before // (n_senjusha + 1)
    return min(a, b)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fl = json.loads((LAWS / "fetch_log.json").read_text(encoding="utf-8"))
    versions = {(f["short"], f["asof"]): f.get("law_revision_id") for f in fl["fetches"]}

    # ---------------- C1 時点の間で本文が同じか
    plan = {
        "shotoku": (["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"],
                    ["26", "33", "36", "37", "51", "56", "57", "63", "64", "69", "70", "143", "152"]),
        "shotoku-rei": (["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"], ["79", "80", "178", "180", "200"]),
        "sochi": (["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"], ["41_4", "41_4_2", "41_4_3"]),
        "sochi-rei": (["2025-12-31", "2026-12-31"], ["26_6", "26_6_2", "26_6_3"]),
    }
    for short, (asofs, nums) in plan.items():
        arts = {a: articles(short, a) for a in asofs}
        for n in nums:
            texts = [arts[a].get(n) for a in asofs]
            same = all(t is not None for t in texts) and len(set(texts)) == 1
            check(f"C1-{short}-{n}", f"{short} Num={n} の本文が {asofs[0]}〜{asofs[-1]} で同じ", same,
                  {"asofs": asofs, "law_revision_ids": [versions.get((short, a)) for a in asofs],
                   "present": [t is not None for t in texts], "distinct_texts": len(set(t for t in texts if t))})
    # 所令198：第3号・第6号の「及び」→「又は」だけが変わる（第1号は同じ）。どの版で変わったかは pin198.json
    r198 = {a: articles("shotoku-rei", a)["198"] for a in ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]}
    norm = {a: t.replace("譲渡所得の金額及び一時所得の金額", "譲渡所得の金額又は一時所得の金額") for a, t in r198.items()}
    check("C1-shotoku-rei-198", "所令198：2025-12-31 と 2026-11-09 以後の違いは第3号・第6号の「譲渡所得の金額及び一時所得の金額」→「又は」だけ（2026-11-09〜2027-01-01 は同じ）",
          len(set(norm.values())) == 1 and r198["2025-12-31"] != r198["2026-11-09"] and len({r198[a] for a in ["2026-11-09", "2026-12-31", "2027-01-01"]}) == 1, {})
    pin = json.loads((LAWS / "pin198.json").read_text(encoding="utf-8"))
    rows = {r["asof"]: r for r in pin["rows"]}
    check("C1-pin198", "所令198第3号の「及び」→「又は」は 2026-04-01 の版（令和8年政令第93号）から。2026-03-31 の版までは「及び」",
          rows["2026-03-31"]["uses_oyobi"] and rows["2026-04-01"]["uses_matawa"] and rows["2026-04-01"]["amendment_law_num"] == "令和八年政令第九十三号",
          {a: [r["law_revision_id"], r["uses_oyobi"], r["uses_matawa"]] for a, r in rows.items()})
    ch = {a: articles("chiho", a)["313"].split("\n１２　")[0] for a in ["2025-12-31", "2026-12-31", "2027-01-01"]}
    check("C1-chiho-313", "地方税法313：第1項〜第11項は 2025-12-31〜2027-01-01 で同じ（第12項の特定配当等の文言だけが変わる）", len(set(ch.values())) == 1, {})
    # 措法25の2 は令和9年分から組み替わる（第2ラウンドの jigyo・aoiro で扱う。ここでは「事業」の文言だけを見る）
    s = {a: articles("sochi", a)["25_2"] for a in ["2025-12-31", "2026-12-31", "2027-01-01"]}
    check("C1-sochi-25_2", "措法25の2 は 2025-12-31 と 2026-12-31 で同じで、2027-01-01 で変わる",
          s["2025-12-31"] == s["2026-12-31"] and s["2026-12-31"] != s["2027-01-01"], {})

    # ---------------- C2 条文の文言
    A = articles("shotoku", "2026-11-09")
    check("C2-26-1", "所法26①：不動産・不動産の上に存する権利・船舶・航空機の貸付け（地上権・永小作権の設定その他他人に使用させることを含む）、事業所得・譲渡所得に当たるものを除く",
          all(k in A["26"] for k in ["不動産、不動産の上に存する権利、船舶又は航空機", "地上権又は永小作権の設定その他他人に不動産等を使用させることを含む", "事業所得又は譲渡所得に該当するものを除く"]), {"file": "shotoku_2026-11-09.txt"})
    check("C2-26-2", "所法26②：不動産所得の金額＝総収入金額−必要経費", "総収入金額から必要経費を控除した金額" in A["26"], {})
    a51 = A["51"].splitlines()
    p1 = next(x for x in a51 if x.startswith("（Paragraph1）"))
    p2 = next(x for x in a51 if x.startswith("２　"))
    p4 = next(x for x in a51 if x.startswith("４　"))
    check("C2-51", "所法51：①資産損失・②貸倒れは「不動産所得…を生ずべき事業」、④は「不動産所得若しくは雑所得を生ずべき業務」で所得の金額を限度",
          "不動産所得、事業所得又は山林所得を生ずべき事業の用に供される固定資産" in p1 and "不動産所得、事業所得又は山林所得を生ずべき事業について" in p2
          and "不動産所得若しくは雑所得を生ずべき業務の用に供され" in p4 and "を限度として" in p4, {})
    check("C2-56", "所法56：生計を一にする配偶者その他の親族が「不動産所得、事業所得又は山林所得を生ずべき事業」から対価を受ける場合、対価は必要経費不算入・親族側の必要経費は事業主側で算入・親族の対価と必要経費は「ないものとみなす」",
          all(k in A["56"] for k in ["居住者と生計を一にする配偶者その他の親族", "不動産所得、事業所得又は山林所得を生ずべき事業に従事したことその他の事由により",
                                      "必要経費に算入しないものとし", "その居住者の当該事業に係る不動産所得の金額、事業所得の金額又は山林所得の金額の計算上、必要経費に算入する",
                                      "当該各種所得の金額の計算上ないものとみなす"]) and "業務" not in A["56"], {})
    check("C2-57", "所法57①③：専従者は「前条に規定する事業」に専ら従事する親族（15歳未満を除く）。③は86万円・50万円と所得÷(人数＋1)の低い方",
          "前条に規定する事業に従事するもの" in A["57"] and "八十六万円" in A["57"] and "五十万円" in A["57"] and "事業専従者の数に一を加えた数で除して" in A["57"], {})
    check("C2-63", "所法63：事業の廃止後の費用・損失は「不動産所得、事業所得又は山林所得を生ずべき事業」に限る", "不動産所得、事業所得又は山林所得を生ずべき事業を廃止した後" in A["63"], {})
    check("C2-64", "所法64①：事業所得の金額を除き、「不動産所得又は山林所得を生ずべき事業から生じたもの」を除く収入金額の回収不能は、所得の金額の計算上なかったものとみなす",
          "事業所得の金額を除く" in A["64"] and "不動産所得又は山林所得を生ずべき事業から生じたものを除く" in A["64"] and "なかつたものとみなす" in A["64"], {})
    check("C2-69", "所法69①：不動産・事業・山林・譲渡の損失を政令の順序で他の所得から控除。②：生活に通常必要でない資産に係る損失は原則「生じなかつたものとみなす」",
          "不動産所得の金額、事業所得の金額、山林所得の金額又は譲渡所得の金額の計算上生じた損失の金額" in A["69"] and "生じなかつたものとみなす" in A["69"], {})
    check("C2-70", "所法70①：純損失の繰越控除は青色申告書を提出した年に生じたもの（②は変動所得・被災事業用資産の損失）", "青色申告書を提出している年に限る" in A["70"] and "被災事業用資産の損失の金額" in A["70"], {})
    check("C2-143", "所法143：青色申告は「不動産所得、事業所得又は山林所得を生ずべき業務」（事業に限らない）", "不動産所得、事業所得又は山林所得を生ずべき業務を行なう居住者" in A["143"], {})
    check("C2-33-79", "所法33①・所令79：借地権等の設定の対価が土地の価額の10分の5を超えるものは譲渡所得（資産の譲渡とみなす）。地代の年額の20倍以下なら該当しないと推定",
          "契約により他人に土地を長期間使用させる行為で政令で定めるもの" in A["33"]
          and "十分の五に相当する金額を超えるもの" in articles("shotoku-rei", "2026-11-09")["79"]
          and "地代の年額の二十倍に相当する金額以下" in articles("shotoku-rei", "2026-11-09")["79"], {})
    R = articles("shotoku-rei", "2026-11-09")
    check("C2-198", "所令198一：不動産所得・事業所得の損失はまず経常所得（利子・配当・不動産・事業・給与・雑）から控除。三：次に譲渡・一時、五：山林・退職",
          "これをまず他の利子所得の金額、配当所得の金額、不動産所得の金額、事業所得の金額、給与所得の金額及び雑所得の金額" in R["198"]
          and "譲渡所得の金額又は一時所得の金額" in R["198"] and "まず山林所得の金額から控除し" in R["198"], {})
    check("C2-178", "所令178①二：通常自己・生計を一にする親族が居住の用に供しない家屋で主として趣味・娯楽・保養の目的で所有するもの（別荘）は生活に通常必要でない資産",
          "通常自己及び自己と生計を一にする親族が居住の用に供しない家屋で主として趣味、娯楽又は保養の用に供する目的で所有するもの" in R["178"], {})
    check("C2-180", "所令180②（法64①の計算）がこの時点の本則にある", "180" in R and "回収" in R.get("180", ""), {"caption_line": R.get("180", "")[:60]})
    S = articles("sochi", "2026-11-09")
    check("C2-41_4", "措法41の4①：不動産所得の損失のうち、土地等を取得するために要した負債の利子に相当する部分（政令で計算）は、所法69①その他の所得税に関する法令の適用上「生じなかつたものとみなす」",
          all(k in S["41_4"] for k in ["不動産所得を生ずべき業務の用に供する土地又は土地の上に存する権利", "を取得するために要した負債の利子の額",
                                        "所得税法第六十九条第一項の規定その他の所得税に関する法令の規定の適用については、生じなかつたものとみなす"]), {})
    SR = articles("sochi-rei", "2025-12-31")
    check("C2-sochirei-26_6", "措令26の6①：利子＞損失なら損失の金額、利子≦損失なら利子の額。②：土地と建物を一の契約で同一の者から取得し負債を区分できないときは、負債はまず建物、次に土地に充てたものとして計算できる",
          "負債の利子の額が当該不動産所得の金額の計算上生じた損失の金額を超える場合　当該損失の金額" in SR["26_6"]
          and "損失の金額以下である場合　当該損失の金額のうち当該負債の利子の額に相当する金額" in SR["26_6"]
          and "まず当該建物の取得の対価の額に充てられ、次に当該土地等の取得の対価の額に充てられたもの" in SR["26_6"], {})
    check("C2-41_4_3", "措法41の4の3：令和3年以後、国外中古建物の不動産所得の損失のうち償却費相当部分は所法26②・69①その他の適用上生じなかったものとみなす",
          "令和三年以後の各年において、国外中古建物から生ずる不動産所得を有する場合" in S["41_4_3"] and "所得税法第二十六条第二項及び第六十九条第一項" in S["41_4_3"], {})
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01"]:
        kh = json.loads((LAWS / f"keyword_hits_chiho_{asof}.json").read_text(encoding="utf-8"))
        n41 = sum(1 for h in kh["hits"] if h["keyword"] == "第四十一条の四")
        check(f"C2-chiho-41_4-{asof}", f"地方税法（{asof}）の本則・附則に「第四十一条の四」の文字列がない（住民税への適用は第313条②の「計算の例」による）", n41 == 0, {"hits": n41})
    C = articles("chiho", "2026-12-31")
    check("C2-chiho-313", "地方税法313②：総所得金額等は、特別の定めがある場合を除き、所得税法その他の所得税に関する法令の規定による総所得金額等の計算の例による。③④：青色事業専従者給与・事業専従者控除（所法56に規定する事業）",
          "所得税法その他の所得税に関する法令の規定による所得税法第二十二条第二項又は第三項の総所得金額、退職所得金額又は山林所得金額の計算の例により算定する" in C["313"]
          and "同法第五十六条に規定する事業" in C["313"] and "八十六万円" in C["313"], {})
    for asof in ["2025-12-31", "2026-12-31"]:
        t = articles("sochi", asof)["25_2"]
        check(f"C2-25_2-{asof}", f"措法25の2（{asof}）：55万円（65万円）の控除は「不動産所得又は事業所得を生ずべき事業を営むもの」、第1項（10万円）は不動産・事業・山林の所得",
              "不動産所得又は事業所得を生ずべき事業を営むもの" in t and "五十五万円" in t and "六十五万円" in t and "十万円" in t, {})
    t = articles("sochi", "2027-01-01")["25_2"]
    check("C2-25_2-2027", "措法25の2（2027-01-01）：65万円の控除も「不動産所得又は事業所得を生ずべき事業を営むもの」、前々年分の不動産所得の総収入金額1,000万円超の要件",
          "不動産所得又は事業所得を生ずべき事業を営むもの" in t and "前々年分の不動産所得に係る総収入金額が千万円を超える" in t and "六十五万円" in t, {})

    # ---------------- C3 年分ごとの基準額
    for asof, exp_k, exp_f in [("2025-12-31", 850_000, 580_000), ("2026-11-09", 850_000, 580_000), ("2026-12-31", 890_000, 620_000), ("2027-01-01", 890_000, 620_000)]:
        a2 = articles("shotoku", asof)["2"]
        k = re.search(r"三十二　勤労学生.*?合計所得金額が([一二三四五六七八九十百]+)万円以下であり、かつ、合計所得金額のうち給与所得等以外の所得に係る部分の金額が([一二三四五六七八九十百]+)万円以下", a2)
        f = re.search(r"三十四　扶養親族.*?合計所得金額が([一二三四五六七八九十百]+)万円以下である者", a2)
        kv, k10, fv = kanji_man(k.group(1)), kanji_man(k.group(2)), kanji_man(f.group(1))
        check(f"C3-{asof}", f"所法2①三十二・三十四（{asof}）：勤労学生 {exp_k}円以下・給与所得等以外10万円以下、扶養親族 {exp_f}円以下",
              kv == exp_k and k10 == 100_000 and fv == exp_f, {"kinro": kv, "kinro_other": k10, "fuyo": fv, "law_revision_id": versions.get(("shotoku", asof))})
    a2 = articles("shotoku", "2026-11-09")["2"]
    k = re.search(r"三十二　勤労学生　次に掲げる者で、自己の勤労に基づいて得た(.*?)（以下この号において「給与所得等」という。）", a2)
    check("C3-kyuyo-tou", "所法2①三十二：「給与所得等」＝自己の勤労に基づいて得た事業所得・給与所得・退職所得・雑所得（不動産所得を含まない）",
          k is not None and k.group(1) == "事業所得、給与所得、退職所得又は雑所得" and "不動産所得" not in k.group(1), {"text": k.group(1) if k else None})
    g = re.search(r"（２）　第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した場合における第二十二条（課税標準）に規定する総所得金額、退職所得金額及び山林所得金額の合計額（以下この条において「合計所得金額」という。）", a2)
    check("C3-gokei", "所法2①三十イ(2)：合計所得金額＝純損失・雑損失の繰越控除を適用しないで計算した総所得金額・退職所得金額・山林所得金額の合計額", g is not None, {})

    # ---------------- C4 計算の検査
    ex = [(-100, 90, -10), (-100, 120, 0), (-100, 100, 0), (50, 90, 50)]
    check("C4-41_4-example", "収支内訳書の書き方 p.3 の例（⑮が△100、利子90 → △10）と、利子が損失以上なら0",
          all(fudosan_for_tsusan(i, r) == e for i, r, e in ex), {"cases": [{"income": i, "interest": r, "expected": e, "got": fudosan_for_tsusan(i, r)} for i, r, e in ex]})
    tot, parts = aoiro_tokubetsu_kojo(100_000, -300_000, 80_000)
    check("C4-25_2-limit", "TA 2072（注1）：10万円の控除で、不動産所得が赤字・事業所得8万円なら、合計は損失を0として8万円 → 控除8万円（事業所得から）",
          tot == 80_000 and parts == [0, 80_000, 0], {"total": tot, "parts": parts})
    tot, parts = aoiro_tokubetsu_kojo(650_000, 400_000, 500_000)
    check("C4-25_2-order", "TA 2072（注3）：65万円の控除は不動産所得、事業所得の順に控除（不動産40万円・事業50万円 → 40万円・25万円）",
          tot == 650_000 and parts == [400_000, 250_000, 0], {"total": tot, "parts": parts})
    check("C4-57-3", "所法57③：配偶者の専従者1人・控除前所得150万円 → min(86万円, 75万円)=75万円。配偶者以外1人・所得300万円 → 50万円",
          jigyo_senjusha_kojo(True, 1_500_000, 1) == 750_000 and jigyo_senjusha_kojo(False, 3_000_000, 1) == 500_000, {})

    # ---------------- C5 様式の欄
    def codes(name, page):
        rows = {}
        for ln in (PDF / f"{name}_codes.tsv").read_text(encoding="utf-8").splitlines()[1:]:
            c = ln.split("\t")
            if len(c) >= 5 and c[0] == str(page):
                rows[c[1]] = c[4]
        return rows
    sh = codes("shushi_fudosan_r07", 1)
    exp_sh = {"G01": "賃貸料", "G02": "礼金・権利金", "G03": "名義書換料", "G04": "小計", "G05": "計", "G06": "給料賃金", "G07": "減価償却費",
              "G08": "貸倒金", "G09": "地代家賃", "G10": "借入金利子", "G11": "租税公課", "G12": "損害保険料", "G13": "修繕費", "G15": "雑費",
              "G16": "小計", "G17": "経費計", "G18": "専従者控除前の所得金額", "G19": "専従者控除", "G20": "所得金額", "G21": "土地等を取得するために"}
    bad = {k: sh.get(k) for k, v in exp_sh.items() if v not in (sh.get(k) or "")}
    check("C5-shushi", "収支内訳書（不動産所得用）令和7年分 1頁：欄コード G01〜G21 と科目名", not bad, {"mismatch": bad, "codes": {k: sh.get(k) for k in exp_sh}})
    ks = codes("kessan_fudosan_r07", 1)
    exp_ks = {"G01": "賃貸料", "G02": "礼金・権利金", "G04": "計", "G05": "租税公課", "G06": "損害保険料", "G07": "修繕費", "G08": "減価償却費",
              "G09": "借入金利子", "G10": "地代家賃", "G11": "給料賃金", "G17": "その他の経費", "G18": "計"}
    bad = {k: ks.get(k) for k, v in exp_ks.items() if v not in (ks.get(k) or "")}
    check("C5-kessan", "青色申告決算書（不動産所得用）令和7年分 1頁：欄コード G01〜G18 と科目名（G19〜G24 は右の列で、科目名は text.tsv の位置で確認）", not bad, {"mismatch": bad})
    kt = (PDF / "kessan_fudosan_r07_text.tsv").read_text(encoding="utf-8")
    check("C5-kessan-right", "決算書1頁の右の列に「差引金額」「専従者給与」「青色申告特別控除前の所得金額」「65万円又は55万円又は10万円と…のいずれか少ない方の金額」「所得金額」「土地等を取得するために要した負債の利子の額」",
          all(k in kt for k in ["差引金額", "専従者給与", "青色申告特別控", "除前の所得金額", "65万円又は55万円又", "は10万円と", "れか少ない方の金額", "所得金額", "要した負債の利子の額"]), {})

    # ---------------- C6 国税庁の文言
    def nta(path):
        return (NTA / path).read_text(encoding="utf-8")
    t = nta("tsutatsu/kihon_04_02.txt")
    check("C6-26-9", "所基通26−9：社会通念上事業と称するに至る程度の規模。貸間・アパート等は独立した室数おおむね10以上、独立家屋はおおむね5棟以上（特に反証がない限り事業）",
          "貸与することができる独立した室数がおおむね10以上" in t and "独立家屋の貸付けについては、おおむね5棟以上" in t and "特に反証がない限り" in t, {})
    check("C6-26-4", "所基通26−4：食事を供さないアパート・貸間は不動産所得、食事を供する下宿等は事業所得又は雑所得", "食事を供さない場合の所得は、不動産所得" in t and "食事を供する場合の所得は、事業所得又は雑所得" in t, {})
    check("C6-27-2", "所基通27−2：有料駐車場等は、自己の責任で他人の物を保管するなら事業所得又は雑所得、そうでなければ不動産所得", "自己の責任において他人の物を保管する場合の所得は事業所得又は雑所得" in t, {})
    t = nta("ta/ta_1373.txt")
    check("C6-1373", "TA 1373：事業的規模かで違う点（資産損失、貸倒損失、専従者給与・控除、青色申告特別控除。「令和8年分までの青色申告特別控除」）",
          all(k in t for k in ["資産損失", "貸倒損失", "事業専従者給与", "令和8年分までの青色申告特別控除", "最高10万円"]), {})
    t = nta("tsutatsu/kihon_11_01.txt")
    check("C6-56-1", "所基通56−1：生計を一にする親族が資産を無償で事業の用に供している場合、対価の授受があったとしたら事業主が算入できる金額を必要経費に算入",
          "その有する資産を無償で当該事業の用に供している場合" in t, {})
    t = nta("tsutatsu/kihon_09_01.txt")
    check("C6-51-5", "所基通51−5：生計を一にする親族の固定資産を事業の用に供している場合、事業主が所有しているものとみなして所法51①を適用できる", "当該事業を営む者が当該資産を所有しているものとみなして法第51条第1項の規定を適用することができる" in t, {})
    t = nta("ta/ta_2210.txt")
    check("C6-2210", "TA 2210：生計を一にする親族に支払う地代家賃は必要経費にならず、受け取った人も所得と考えない。父の土地・建物の固定資産税等は子の業務の必要経費（TA の文言は「業務」）",
          "生計を一にする配偶者その他の親族に支払う地代家賃などは必要経費になりません。逆に、受け取った人も所得としては考えません。" in t and "子が営む業務の必要経費になります" in t, {})
    t = nta("more/shitsugi_02_27.txt")
    check("C6-shitsugi-02-27", "質疑応答（事業に至らない規模の未収家賃の回収不能）：所法64①・所令180②。不動産所得が赤字なら、なかったものとみなす金額は生じない",
          "なかったものとみなされる金額は生じない" in t and "所得税法施行令第180条第2項" in t, {})
    t = nta("ta/ta_1391.txt")
    check("C6-1391", "TA 1391：別荘等の貸付けの損失と、土地等を取得するための負債の利子に相当する損失は損益通算の対象外",
          "別荘等のように主として趣味、娯楽、保養または鑑賞の目的で所有する不動産の貸付けに係るもの" in t and "土地等を取得するために要した負債の利子に相当する部分の金額" in t, {})
    t = nta("more/kobetsu_731106.txt")
    check("C6-731106", "個別通達 直所2−78（昭和48年）：継続的な記帳など一定の要件で、貸付期間に対応する賃貸料をその年の収入にできる（事業的規模でなくても1年以内の期間の賃貸料は可）。本文は「同法第67条の2」を引く",
          "その年中の貸付期間に対応する部分の賃貸料の額" in t and "事業的規模で行なっていない場合であつても" in t and "第67条の2" in t, {})
    lines = (PDF / "shushi_fudosan_kakikata_r07_text.tsv").read_text(encoding="utf-8")
    check("C6-kakikata-shushi", "収支内訳書の書き方：専従者控除は事業として行われていない場合は適用できない。⑮が赤字で土地等の負債の利子がある場合の「不動産③」の書き方。組合事業等は⑬欄を0",
          all(k in lines for k in ["不動産の貸付けが事業として行われていない場合には、専従者控除は適用できません。", "申告書第一表の「所得金額」欄の「不動産③」には、０と書いてください。",
                                   "収支内訳書の⑬欄は０と書いてください。", "既に収入金額とした未収賃貸料（事業として行われる不動産の貸付けによるものに限ります。）"]), {})
    sm = json.loads((PDF / "summary.json").read_text(encoding="utf-8"))
    kk = sm["files"].get("kessan_fudosan_kakikata_r07", {})
    jp = sum(1 for ln in (PDF / "kessan_fudosan_kakikata_r07_text.tsv").read_text(encoding="utf-8").splitlines() if re.search(r"[ぁ-んァ-ン一-龥]", ln))
    check("C6-kakikata-kessan", "青色申告決算書（不動産所得用）の書き方：復号はできた（key_ok）が、日本語として読める行がほとんどない（Identity-H で ToUnicode がない）",
          kk.get("key_ok") is True and jp < 50 and kk.get("type0_fonts", 0) > 0 and kk.get("type0_fonts_without_tounicode") == kk.get("type0_fonts")
          and kk.get("tounicode_cmap_streams") == 0,
          {"key_ok": kk.get("key_ok"), "encrypt": kk.get("encrypt"), "rows": kk.get("rows"), "rows_with_japanese": jp,
           "type0_fonts": kk.get("type0_fonts"), "type0_fonts_without_tounicode": kk.get("type0_fonts_without_tounicode"),
           "tounicode_cmap_streams": kk.get("tounicode_cmap_streams")})

    (OUT / "checks.json").write_text(json.dumps({"n": len(RESULTS), "ng": [r["id"] for r in RESULTS if not r["ok"]], "results": RESULTS},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", len(RESULTS), "NG:", [r["id"] for r in RESULTS if not r["ok"]])


if __name__ == "__main__":
    sys.exit(main())
