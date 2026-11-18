"""R3X shibo-shukkoku: 取得済みの条文テキストだけを使って（ネットワークに出ない）、準確定申告・出国の申告・
相続人の按分・純損失の繰戻し（相続人）・雑損失の繰越の、期限と金額の計算例を作り、国税庁の資料に書かれた日付・例と照合する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_calc.py

入力（scripts/R3X_shibo-shukkoku_laws.py が書いた取得済みのテキスト。ダウンロードしたファイルそのものは読まない）:
  scripts/results/R3X_shibo-shukkoku_laws/shotoku_2026-11-09.txt   … 所法89①の税率の表
  scripts/results/R3X_shibo-shukkoku_laws/shukujitsu_2026-11-09.txt … 国民の祝日に関する法律 第2条の表・第3条
  （ほかに、条ごとの時点間の比較で scripts/results/R3X_shibo-shukkoku_laws/<略称>_<asof>.txt を、引用の照合で
  scripts/results/R3X_shibo-shukkoku_nta/<set>/<id>.txt も読む）
引用の照合:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_calc.py quotes <文書.md> ...
      文書の「」内の引用（8文字以上）が、取得したテキスト（laws/*.txt と nta/*/*.txt）に含まれるかを調べる（空白を除いて比較）。
      PDF を目視で写した引用は対象のテキストがないので「見つからない」になる（文書の側で区別して書く）。
出力:
  scripts/results/R3X_shibo-shukkoku_calc/results.json と results.txt
  scripts/results/R3X_shibo-shukkoku_calc/article_versions.json（条ごとに、取得した時点の間で本文が同じか）
  scripts/results/R3X_shibo-shukkoku_calc/quotes_check.json（quotes のとき）

- 照合に使う国税庁の資料の値（日付・例）は、人が PDF を読んで書き写したもの（EXPECTED_* に出典を書く）。
- 数字はすべて架空。個人の情報は使わない。
- 途中の値は Fraction（有理数）で持ち、丸めは名前つきの関数だけで行う（D21 R5）。
"""
import calendar
import datetime as dt
import json
import pathlib
import re
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAWS = ROOT / "scripts" / "results" / "R3X_shibo-shukkoku_laws"
OUT = ROOT / "scripts" / "results" / "R3X_shibo-shukkoku_calc"
D = dt.date

# ---------------------------------------------------------------- 漢数字
KD = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
KU = {"十": 10, "百": 100, "千": 1000}


def kanji_int(s):
    """「三百三十万」「四千万」「二十三」などを整数にする（万までで足りる範囲）。"""
    total, sect, num = 0, 0, 0
    for ch in s:
        if ch in KD:
            num = KD[ch]
        elif ch in KU:
            sect += (num or 1) * KU[ch]
            num = 0
        elif ch == "万":
            total += (sect + num) * 10000
            sect, num = 0, 0
        else:
            raise ValueError(f"unexpected {ch!r} in {s!r}")
    return total + sect + num


def section(path, num):
    lines = path.read_text(encoding="utf-8").splitlines()
    out, keep = [], False
    for ln in lines:
        if ln.startswith("## Num="):
            keep = ln == f"## Num={num}"
            continue
        if keep:
            out.append(ln)
    return out


# ---------------------------------------------------------------- 所法89① の表（取得したテキストから読む）
def parse_rates():
    rows = [ln.strip() for ln in section(LAWS / "shotoku_2026-11-09.txt", "89") if ln.strip().startswith("| ")]
    rates = []
    for r in rows:
        cells = [c.strip() for c in r.strip("|").split("|")]
        upper = re.search(r"([〇一二三四五六七八九十百千万]+)円以下の金額", cells[0])
        rate = kanji_int(re.fullmatch(r"百分の([〇一二三四五六七八九十]+)", cells[1]).group(1))
        rates.append((kanji_int(upper.group(1)) if upper else None, rate))
    return rows, rates


RATES_SRC, RATES = parse_rates()


def floor_to(x, unit):
    """名前つきの切捨て（x は int か Fraction。unit 円未満を切り捨てる）。"""
    return (int(x) // unit) * unit if isinstance(x, int) else (x.numerator // (x.denominator * unit)) * unit


def tax_89(kazei):
    """所法89①の超過累進。kazei は1,000円未満切捨て済みの課税総所得金額。結果は有理数のまま返す。"""
    t, lo = Fraction(0), 0
    for hi, r in RATES:
        top = kazei if hi is None else min(kazei, hi)
        if top > lo:
            t += Fraction(top - lo) * r / 100
        if hi is None or kazei <= hi:
            break
        lo = hi
    return t


# ---------------------------------------------------------------- 休日（祝日法 第2条・第3条、通則法10②、通則令2②）
def parse_holiday_rules():
    rules, unknown = [], []
    for ln in section(LAWS / "shukujitsu_2026-11-09.txt", "2"):
        ln = ln.strip()
        if not ln.startswith("| "):
            continue
        name, spec = [c.strip() for c in ln.strip("|").split("|")][:2]
        m = re.fullmatch(r"([一二三四五六七八九十]+)月([一二三四五六七八九十]+)日", spec)
        n = re.fullmatch(r"([一二三四五六七八九十]+)月の第([一二三四五]+)月曜日", spec)
        if m:
            rules.append((name, "fixed", kanji_int(m.group(1)), kanji_int(m.group(2))))
        elif n:
            rules.append((name, "nth_monday", kanji_int(n.group(1)), kanji_int(n.group(2))))
        else:
            unknown.append((name, spec))
    return rules, unknown


HOLIDAY_RULES, HOLIDAY_UNKNOWN = parse_holiday_rules()
# 春分の日（春分日）・秋分の日（秋分日）・建国記念の日（政令で定める日）は取得したテキストから日付が決まらない。
# 日付を推測で埋めず、その日がありうる月の全部を「未確定」にする。ただし「ありうる月」自体は取得した資料に書かれておらず、
# 春分日＝3月・秋分日＝9月・建国記念の日＝2月とするのは、この実測の前提（一次情報で確認していない推測）である。
UNKNOWN_MONTHS = {"建国記念の日": {2}, "春分の日": {3}, "秋分の日": {9}}


def kokumin_shukujitsu(year):
    days = {}
    for name, kind, mth, x in HOLIDAY_RULES:
        if kind == "fixed":
            days[D(year, mth, x)] = name
        else:
            first = D(year, mth, 1)
            off = (0 - first.weekday()) % 7  # 月曜日=0
            days[first + dt.timedelta(days=off + 7 * (x - 1))] = name
    return days


def kyujitsu(year):
    """祝日法第3条：①国民の祝日、②日曜日に当たる祝日の後の最も近い祝日でない日、③前日と翌日が祝日である日。"""
    s = kokumin_shukujitsu(year)
    h = dict(s)
    for d0 in sorted(s):
        if d0.weekday() == 6:
            d1 = d0 + dt.timedelta(days=1)
            while d1 in s:
                d1 += dt.timedelta(days=1)
            h[d1] = f"振替休日（{s[d0]}）"
    for d0 in sorted(s):
        d2 = d0 + dt.timedelta(days=2)
        if d2 in s and (d0 + dt.timedelta(days=1)) not in s:
            h[d0 + dt.timedelta(days=1)] = "国民の休日（第3条第3項）"
    return h


def holiday_status(d):
    """通則法10②・通則令2② の期限の休日か。戻り値 (True/False/None, 理由)。None は取得した資料だけでは決まらない。"""
    if d.weekday() == 6:
        return True, "日曜日"
    if d.weekday() == 5:
        return True, "土曜日（通則令2②）"
    if d.month == 12 and d.day in (29, 30, 31):
        return True, "12月29日〜31日（通則令2②）"
    h = kyujitsu(d.year)
    if d in h:
        return True, h[d]
    for name, months in UNKNOWN_MONTHS.items():
        if d.month in months:
            return None, f"{name}の日付は祝日法の条文だけでは決まらない"
    return False, "平日（「その他一般の休日」には当たらないとみなした。範囲は未確認）"


def shift_holiday(d):
    """通則法10②：期限が休日などに当たるときは翌日をもって期限とみなす（翌日も休日ならさらに翌日）。"""
    trail = []
    while True:
        st, why = holiday_status(d)
        trail.append((d.isoformat(), st, why))
        if st is None:
            return None, trail
        if not st:
            return d, trail
        d += dt.timedelta(days=1)


# ---------------------------------------------------------------- 期間の計算（通則法10①）
def add_months_or_none(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return D(y, m, d.day) if d.day <= calendar.monthrange(y, m)[1] else None, (y, m)


def period_end(kisanbi, months=0, years=0):
    """通則法10①二・三：起算日から月・年で定める期間の満了日。応当日の前日、応当日がなければその月の末日。"""
    n = months + 12 * years
    ota, (y, m) = add_months_or_none(kisanbi, n)
    if ota is None:
        return D(y, m, calendar.monthrange(y, m)[1])
    return ota - dt.timedelta(days=1)


def junkaku_deadline(knew):
    """所法125①「相続の開始があつたことを知つた日の翌日から四月を経過した日の前日」の2つの読み。
    読みA：「四月を経過した日」＝4月の期間の満了日の翌日 → その前日＝満了日。
    読みB：「四月を経過した日」＝満了日 → その前日＝満了日の前日。"""
    s = knew + dt.timedelta(days=1)
    end = period_end(s, months=4)
    return {"A": end, "B": end - dt.timedelta(days=1)}


def kosei_deadline(start, years=5):
    """附則「同日から五年以内」。読みX：初日算入（期間が午前零時から始まる：通則法10①一ただし書）、読みY：初日不算入。"""
    return {"X_初日算入": period_end(start, years=years), "Y_初日不算入": period_end(start + dt.timedelta(days=1), years=years)}


# ---------------------------------------------------------------- 年齢（年齢計算ニ関スル法律・民法143。誕生日の前日の終了で1歳加わる）
def age_at(birth, d):
    """d の日の終わりの時点の年齢。誕生日の前日に年をとる（既存の実測 impl-prep_misc の方法）。"""
    a = d.year - birth.year
    bday_eve = (D(d.year, birth.month, birth.day) if not (birth.month == 2 and birth.day == 29 and not calendar.isleap(d.year))
                else D(d.year, 3, 1)) - dt.timedelta(days=1)
    return a if d >= bday_eve else a - 1


# ---------------------------------------------------------------- 照合に使う国税庁の資料の値（人が PDF を読んで書き写した）
EXPECTED_KISAIYORYO = {
    "source": "死亡した者の＿年分の所得税及び復興特別所得税の確定申告書付表 書き方（f01.pdf、取得 2026-11-09、"
              ".work/downloads/20261109-211539_R3X_shibo-shukkoku_nta_forms3/fuhyo_kisaiyoryo.pdf）",
    "text": "相続の開始があったことを知った日の翌日から起算して4か月を経過した日の前日（例えば、死亡した日が6月20日であるときは、10月20日）",
    "knew_month_day": (6, 20), "deadline_month_day": (10, 20),
}
EXPECTED_KOSEI = [
    {"label": "令和7年度改正（令和7年法律第13号附則第2条②ほか）", "start": D(2025, 12, 1), "nta": D(2030, 12, 2),
     "source": "令和７年度税制改正（基礎控除の見直し等関係）Q&A 7-1・7-4（令和7年5月30日、r7_kiso_qa.pdf p.27-28）「令和12年12月2日（月）」"},
    {"label": "令和8年度改正（令和8年法律第12号附則第2条②ほか）", "start": D(2026, 12, 1), "nta": D(2031, 12, 1),
     "source": "令和８年度税制改正（所得税の基礎控除の引上げ等関係）Q&A 6-1・6-3（令和8年5月、r8_kiso_qa.pdf p.10-11）「令和13年12月1日（月）」"},
]
EXPECTED_RATES = [(1_950_000, 5), (3_300_000, 10), (6_950_000, 20), (9_000_000, 23), (18_000_000, 33), (40_000_000, 40), (None, 45)]


# ---------------------------------------------------------------- 条ごとの時点間の比較と引用の照合
NTA_OUT = ROOT / "scripts" / "results" / "R3X_shibo-shukkoku_nta"
VERSIONED = {
    "shotoku": ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"],
    "shotoku-rei": ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"],
    "shotoku-ki": ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"],
    "sochi": ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"],
    "tsusoku": ["2026-11-09", "2027-01-01"], "tsusoku-rei": ["2026-11-09", "2027-01-01"],
    "chiho": ["2026-11-09", "2027-01-01"], "shukujitsu": ["2026-11-09", "2027-01-01"],
}


def article_sections(path):
    d, cur = {}, None
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("## Num="):
            cur = ln[len("## Num="):]
            d[cur] = []
        elif cur is not None:
            d[cur].append(ln)
    return d


def article_versions():
    out = {}
    for short, asofs in VERSIONED.items():
        secs = {a: article_sections(LAWS / f"{short}_{a}.txt") for a in asofs}
        nums = list(secs[asofs[0]].keys())
        for num in nums:
            groups = []
            for a in asofs:
                body = "\n".join(secs[a].get(num, ["（なし）"])).strip()
                for g in groups:
                    if g["body"] == body:
                        g["asofs"].append(a)
                        break
                else:
                    groups.append({"asofs": [a], "body": body})
            out[f"{short}:{num}"] = [g["asofs"] for g in groups]
    return out


def corpus_text():
    parts = [p.read_text(encoding="utf-8") for p in sorted(LAWS.glob("*.txt"))]
    parts += [p.read_text(encoding="utf-8") for p in sorted(NTA_OUT.glob("*/*.txt"))]
    return re.sub(r"\s+", "", "".join(parts))


def quotes(md_paths):
    corpus = corpus_text()
    rows = []
    for mp in md_paths:
        text = (ROOT / mp).read_text(encoding="utf-8")
        for q in re.findall(r"「([^「」]{8,})」", text):
            norm = re.sub(r"\s+", "", q.replace("…", "|"))
            pieces = [x for x in norm.split("|") if x]
            ok = all(x in corpus for x in pieces)
            rows.append({"doc": mp, "quote": q, "found": ok})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "quotes_check.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    nf = [r for r in rows if not r["found"]]
    print(f"quotes: {len(rows)} 件、見つかった {len(rows) - len(nf)} 件、見つからない {len(nf)} 件")
    for r in nf:
        print("  NOT FOUND:", r["quote"][:120])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"inputs": {"rates_rows": RATES_SRC, "holiday_rules": HOLIDAY_RULES, "holiday_unknown": HOLIDAY_UNKNOWN}}
    txt = []

    # 0. 条ごとの時点間の比較
    av = article_versions()
    (OUT / "article_versions.json").write_text(json.dumps(av, ensure_ascii=False, indent=1), encoding="utf-8")
    diff_arts = {k: v for k, v in av.items() if len(v) > 1}
    txt.append(f"[0] 条ごとの時点間の比較：{len(av)} 条のうち、時点で本文が違うもの {len(diff_arts)} 条")
    for k, v in diff_arts.items():
        txt.append(f"    {k}: " + " | ".join("=".join(g) for g in v))

    # 1. 税率の表
    res["rates"] = {"parsed": RATES, "same_as_round2_aoiro": RATES == EXPECTED_RATES}
    txt.append(f"[1] 所法89①の表（2026-11-09 版から読んだ）: {RATES}  round2 aoiro と同じ: {RATES == EXPECTED_RATES}")

    # 2. 準確定申告の期限の読み（記載要領の例と照合）
    m0, d0 = EXPECTED_KISAIYORYO["knew_month_day"]
    me, de = EXPECTED_KISAIYORYO["deadline_month_day"]
    chk = []
    for y in range(2020, 2031):
        r = junkaku_deadline(D(y, m0, d0))
        chk.append({"year": y, "A": r["A"].isoformat(), "B": r["B"].isoformat(),
                    "A_matches": (r["A"].month, r["A"].day) == (me, de), "B_matches": (r["B"].month, r["B"].day) == (me, de)})
    res["junkaku_reading_check"] = {"expected": EXPECTED_KISAIYORYO, "rows": chk,
                                    "A_all": all(c["A_matches"] for c in chk), "B_any": any(c["B_matches"] for c in chk)}
    txt.append(f"[2] 記載要領の例（6/20→10/20）と一致：読みA {res['junkaku_reading_check']['A_all']}（全年）、読みB {res['junkaku_reading_check']['B_any']}（どれか1年）")

    # 3. 準確定申告の期限の例（読みA、休日の繰下げつき）。架空の日付。
    cases = [D(2026, 6, 20), D(2026, 1, 10), D(2026, 10, 28), D(2026, 10, 29), D(2026, 10, 30), D(2026, 10, 31),
             D(2027, 10, 31), D(2026, 8, 28), D(2026, 7, 2), D(2026, 4, 29), D(2026, 11, 1), D(2027, 2, 10)]
    rows = []
    for k in cases:
        a = junkaku_deadline(k)["A"]
        sh, trail = shift_holiday(a)
        rows.append({"knew": k.isoformat(), "raw_deadline": a.isoformat(), "raw_weekday": "月火水木金土日"[a.weekday()],
                     "deadline": sh.isoformat() if sh else None, "trail": trail})
    res["junkaku_examples"] = rows
    txt.append("[3] 準確定申告の期限（読みA、通則法10②の繰下げ）:")
    for r in rows:
        txt.append(f"    知った日 {r['knew']} → 満了 {r['raw_deadline']}({r['raw_weekday']}) → 期限 {r['deadline']}  {r['trail'][-1][2]}")

    # 4. 附則の更正の請求の期間（5年）と国税庁 Q&A の日付の照合
    ko = []
    for e in EXPECTED_KOSEI:
        rr = kosei_deadline(e["start"])
        row = {"label": e["label"], "start": e["start"].isoformat(), "nta": e["nta"].isoformat(), "source": e["source"]}
        for k, v in rr.items():
            sh, trail = shift_holiday(v)
            row[k] = {"raw": v.isoformat(), "raw_weekday": "月火水木金土日"[v.weekday()], "shifted": sh.isoformat() if sh else None,
                      "matches_nta": sh == e["nta"], "trail": trail}
        ko.append(row)
    res["kosei_seikyu_period"] = ko
    txt.append("[4] 附則の更正の請求（同日から五年以内）:")
    for r in ko:
        txt.append(f"    {r['label']} 起点 {r['start']} 国税庁 {r['nta']} | 初日算入 {r['X_初日算入']['raw']}({r['X_初日算入']['raw_weekday']})→{r['X_初日算入']['shifted']} 一致 {r['X_初日算入']['matches_nta']}"
                   f" | 初日不算入 {r['Y_初日不算入']['raw']}({r['Y_初日不算入']['raw_weekday']})→{r['Y_初日不算入']['shifted']} 一致 {r['Y_初日不算入']['matches_nta']}")

    # 5. 相続人の按分（所規49①三、所基通124・125−3、付表の書き方9）。架空の金額。相続分は有理数。
    def anbun(total, shares, refund):
        unit = 1 if refund else 100
        return [floor_to(Fraction(total) * s, unit) for s in shares]
    an = []
    for total, shares, refund in [
        (123_400, [Fraction(1, 2), Fraction(1, 4), Fraction(1, 4)], False),
        (100_000, [Fraction(1, 3)] * 3, False),
        (250, [Fraction(1, 2), Fraction(1, 4), Fraction(1, 4)], False),
        (12_345, [Fraction(2, 3), Fraction(1, 3)], True),
        (10_000, [Fraction(1, 3)] * 3, True),
    ]:
        parts = anbun(total, shares, refund)
        an.append({"total": total, "shares": [str(s) for s in shares], "kind": "還付（1円未満切捨て）" if refund else "納付（100円未満切捨て）",
                   "parts": parts, "sum": sum(parts), "lost": total - sum(parts)})
    res["anbun"] = an
    txt.append("[5] 相続人の按分:")
    for a in an:
        txt.append(f"    {a['kind']} 合計 {a['total']} 相続分 {a['shares']} → {a['parts']}（計 {a['sum']}、差 {a['lost']}）")

    # 6. 相続人の純損失の繰戻し（所法141①・④、所令271①一・272②、所基通140・141−2・−4）。架空の金額。
    def kurimodoshi(prev_kazei, loss, prev_tax_after_credits):
        a = floor_to(tax_89(floor_to(prev_kazei, 1000)), 100)
        b = floor_to(tax_89(floor_to(max(prev_kazei - loss, 0), 1000)), 100)
        return min(a - b, prev_tax_after_credits), a, b
    km = []
    # K1：2026年9月死亡。2026年分（準確定・青色）の純損失 1,500,000 を 2025年分（課税総所得 4,000,000）へ（141①）
    r1 = kurimodoshi(4_000_000, 1_500_000, 10**9)
    km.append({"case": "141① 死亡年の純損失→前年分", "prev_kazei": 4_000_000, "loss": 1_500_000, "refund": r1[0], "tax_before": r1[1], "tax_after": r1[2]})
    # K2：2025年の純損失 800,000。2026年（死亡年）の総所得金額 300,000 に繰越控除（70①）→残り 500,000 を 2024年分（課税総所得 3,000,000）へ（141④・所令272②）
    rest = 800_000 - min(800_000, 300_000)
    r2 = kurimodoshi(3_000_000, rest, 10**9)
    km.append({"case": "141④ 前年の純損失（死亡年に繰越控除した残り）→前々年分", "loss_prev": 800_000, "used_in_death_year": 300_000,
               "carried_back": rest, "prevprev_kazei": 3_000_000, "refund": r2[0], "tax_before": r2[1], "tax_after": r2[2]})
    # K3：K1 で前年分の税額控除後の所得税額が 100,000 のとき（140② 準用、所基通140・141−2）
    r3 = kurimodoshi(4_000_000, 1_500_000, 100_000)
    km.append({"case": "K1 で前年分の税額控除後の所得税額 100,000（限度）", "refund": r3[0], "tax_before": r3[1], "tax_after": r3[2]})
    res["kurimodoshi_heirs"] = km
    txt.append("[6] 相続人の繰戻し還付:")
    for k in km:
        txt.append(f"    {k['case']}: 還付 {k['refund']}（前 {k['tax_before']} → 後 {k['tax_after']}）")

    # 7. 雑損失の繰越控除の順序（所令204①一・二）。架空の金額。前年以前3年内、古い年から、総所得→山林→退職の順。
    def zasson_kurikoshi(pool, year, incomes):
        avail = {y: v for y, v in pool.items() if year - 3 <= y <= year - 1 and v > 0}
        used, inc = {}, dict(incomes)
        for y in sorted(avail):
            for k in ("総所得金額", "山林所得金額", "退職所得金額"):
                take = min(avail[y], inc.get(k, 0))
                if take:
                    avail[y] -= take
                    inc[k] -= take
                    used[(y, k)] = take
        newpool = {y: (avail.get(y, v) if year - 3 <= y <= year - 1 else v) for y, v in pool.items()}
        expired = {y: v for y, v in newpool.items() if y == year - 3 and v > 0}
        return used, inc, newpool, expired
    z_pool, z_inc = {2023: 500_000, 2025: 300_000}, {"総所得金額": 300_000, "山林所得金額": 0, "退職所得金額": 100_000}
    used, inc, pool2, expired = zasson_kurikoshi(z_pool, 2026, z_inc)
    res["zasson_kurikoshi"] = {"pool_before": z_pool, "year": 2026, "incomes": z_inc,
                               "used": {f"{y}:{k}": v for (y, k), v in used.items()}, "incomes_after": inc,
                               "pool_after": pool2, "expired_after_2026": expired}
    txt.append(f"[7] 雑損失の繰越（2026年分）: 使った {res['zasson_kurikoshi']['used']} 控除後 {inc} 残り {pool2} 2026年で期限切れ {expired}")

    # 8. 判定の時点と年齢（所法85①③の「死亡又は出国の時」）。架空の生年月日。
    birth = D(1956, 10, 1)
    death = D(2026, 6, 30)
    res["age_example"] = {"birth": birth.isoformat(), "death_of_taxpayer": death.isoformat(),
                          "age_at_death_time": age_at(birth, death), "age_at_dec31": age_at(birth, D(2026, 12, 31))}
    txt.append(f"[8] 年齢：生年月日 {birth} の親族、納税者の死亡 {death}：死亡の時 {res['age_example']['age_at_death_time']} 歳、12月31日 {res['age_example']['age_at_dec31']} 歳")

    # 9. 確定申告書を出さずに翌年の1月1日〜3月15日に死亡（所法124①）と期限後に死亡（所基通124・125−2）
    ex = []
    for death_d, note in [(D(2027, 2, 10), "前年分（2026年分）は124①、本年分（2027年分）は125①。期限はどちらも知った日の翌日から4か月（TA2022 の注）"),
                          (D(2027, 3, 20), "前年分の提出期限（第三期の末日）の後の死亡：124 の適用なし。前年分は期限後申告（所基通124・125−2）")]:
        dl = junkaku_deadline(death_d)["A"]
        sh, trail = shift_holiday(dl)
        ex.append({"death_and_knew": death_d.isoformat(), "deadline_125": sh.isoformat() if sh else None, "note": note})
    res["death_early_next_year"] = ex
    for e in ex:
        txt.append(f"[9] 死亡 {e['death_and_knew']}（同日に知った）→ 4か月の期限 {e['deadline_125']}：{e['note']}")

    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "results.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
    print("\n".join(txt))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "quotes":
        quotes(sys.argv[2:])
    else:
        main()
