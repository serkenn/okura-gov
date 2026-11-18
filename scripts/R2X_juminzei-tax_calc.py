"""R2X juminzei-tax: 個人住民税の税額の計算の条文を検査し、読みを式にして公開の計算例と照合する（ネットワーク不要）。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_juminzei-tax_calc.py

入力（先に scripts/R2X_juminzei-tax_laws.py と scripts/R2X_juminzei-tax_web.py を実行しておく）:
  scripts/results/R2X_juminzei-tax_laws/*.articles.json, hits_*.json
  scripts/results/R2X_juminzei-tax_web/*.txt
出力: scripts/results/R2X_juminzei-tax_calc/
  evidence.md / evidence.json  … 条文の文字列の検査（主張ごとに版ごとの有無）
  versions.md                  … 項ごとの版の比較（令和8年度分・令和9年度分に効く版の確認）
  identities.md                … 率の表どうしの恒等式（附則5の6・7の3、市と県の配分）
  reachability.md              … 調整控除の表の（７）（配偶者特別控除の差）が当たりうるかの列挙
  examples.md / examples.json  … 計算の読みで自治体の計算例（名古屋市・横浜市、令和8年度）を再現する。仮の例（令和9年度）
  rounding.md                  … 1円未満の扱い（一次情報で決まらない）を変えたときに結果が変わる頻度
  municipal_checks.md          … 自治体のページの文字列の検査（計算例の数字が取得したページにあること）

計算は fractions.Fraction で厳密に行う。税率・均等割など市町村・道府県ごとの値は引数として注入する（既定値を置かない）。
"""
import difflib
import itertools
import json
import pathlib
import random
import re
import sys
from fractions import Fraction as Fr

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAWS = ROOT / "scripts" / "results" / "R2X_juminzei-tax_laws"
WEB = ROOT / "scripts" / "results" / "R2X_juminzei-tax_web"
OUT = ROOT / "scripts" / "results" / "R2X_juminzei-tax_calc"

ASOFS = ["2026-01-01", "2026-11-09", "2027-01-01", "2028-01-01"]


def load(short, asof):
    p = LAWS / f"{short}_{asof}.articles.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


ART = {a: load("chiho", a) for a in ASOFS}
OTHER = {
    ("chiho-rei", "2026-11-09"): load("chiho-rei", "2026-11-09"),
    ("chiho-rei", "2027-01-01"): load("chiho-rei", "2027-01-01"),
    ("shinrin", "2026-11-09"): load("shinrin", "2026-11-09"),
    ("shinrin", "2027-01-01"): load("shinrin", "2027-01-01"),
    ("shinrin-rei", "2026-11-09"): load("shinrin-rei", "2026-11-09"),
    ("shinsai", "2026-11-09"): load("shinsai", "2026-11-09"),
    ("shitei", "2026-11-09"): load("shitei", "2026-11-09"),
    ("chiho-0401", "2026-03-31"): load("chiho-0401", "2026-03-31"),
    ("chiho-0401", "2026-04-01"): load("chiho-0401", "2026-04-01"),
}


def text(short, asof, key):
    d = ART[asof] if short == "chiho" else OTHER.get((short, asof))
    if d is None:
        return None
    return d["articles"].get(key)


# ---------------------------------------------------------------------------
# 1. 条文の文字列の検査
# (主張ID, 内容, 法令の略称, 条のキー（版ごとに違う場合は dict）, 版, 含むべき文字列, 含まないべき文字列)
# ---------------------------------------------------------------------------
JUTAKU_KEY = {"2026-01-01": "附則:5_4_2", "2026-11-09": "附則:5_4", "2027-01-01": "附則:5_4", "2028-01-01": "附則:5_4"}
TOKUREI_ROWS = ["| 百九十五万円以下の金額 | 百分の八十五 |", "| 百九十五万円を超え三百三十万円以下の金額 | 百分の八十 |",
                "| 三百三十万円を超え六百九十五万円以下の金額 | 百分の七十 |", "| 六百九十五万円を超え九百万円以下の金額 | 百分の六十七 |",
                "| 九百万円を超え千八百万円以下の金額 | 百分の五十七 |", "| 千八百万円を超え四千万円以下の金額 | 百分の五十 |",
                "| 四千万円を超える金額 | 百分の四十五 |"]
CLAIMS = [
    ("C01", "市町村民税の所得割の標準税率 6%（指定都市 8%）、一の率", "chiho", "本則:314_3", ASOFS,
     ["百分の六（所得割の納税義務者が地方自治法第二百五十二条の十九第一項の市", "の区域内に住所を有する場合には、百分の八）の標準税率", "当該定める率は、一の率でなければならない"], []),
    ("C02", "道府県民税の所得割の標準税率 4%（指定都市 2%）、同一の標準税率ごとに一の率", "chiho", "本則:35", ASOFS,
     ["百分の四（所得割の納税義務者が地方自治法第二百五十二条の十九第一項の市", "には、百分の二）の標準税率", "同一の標準税率ごとに一の率でなければならない"], []),
    ("C03", "市町村民税の均等割の標準税率 3,000円", "chiho", "本則:310", ASOFS, ["個人の均等割の標準税率は、三千円とする。"], []),
    ("C04", "道府県民税の均等割の標準税率 1,000円", "chiho", "本則:38", ASOFS, ["個人の均等割の標準税率は、千円とする。"], []),
    ("C05", "均等割の軽減（条例）", "chiho", "本則:311", ASOFS, ["当該市町村の条例で定めるところにより、軽減することができる"], []),
    ("C06", "端数：課税標準額の千円未満切捨て、確定金額の百円未満切捨て、市町村民税・道府県民税・森林環境税を一の地方税とみなす場合", "chiho", "本則:20_4_2", ASOFS,
     ["課税標準額を計算する場合において、その額に千円未満の端数があるとき", "地方税の確定金額に百円未満の端数があるとき", "それぞれ一の地方税とみなす", "森林環境税"], []),
    ("C07", "調整控除（市町村民税）：2,500万円以下、200万円、3%（指定都市 4%）、5万円の下限、人的控除差の表", "chiho", "本則:314_6", ASOFS,
     ["前年の合計所得金額が二千五百万円以下である所得割の納税義務者", "が二百万円以下である場合", "百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）",
      "当該金額が五万円を下回る場合には、五万円とする。", "当該障害者一人につき一万円", "当該特別障害者一人につき十万円", "当該同居特別障害者一人につき二十二万円",
      "当該特定扶養親族一人につき十八万円", "当該老人扶養親族一人につき十万円", "当該老人扶養親族一人につき十三万円", "前年の合計所得金額が五十五万円未満である者に限る"],
     ["特定親族"]),
    ("C08", "調整控除（道府県民税）：2%（指定都市 1%）", "chiho", "本則:37", ASOFS, ["百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）"], ["特定親族"]),
    ("C09", "寄附金税額控除（市町村民税）：30%・2,000円・6%（8%）・特例 3/5（4/5）・所得割の20%・割合の表", "chiho", "本則:314_7", ASOFS,
     ["百分の三十に相当する金額を超える場合", "二千円を超える場合には、その超える金額の百分の六（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の八）",
      "の五分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、五分の四）", "所得割の額の百分の二十に相当する金額", "百分の九十"] + TOKUREI_ROWS, []),
    ("C09a", "人的控除差調整額に「所得税の基礎控除の額−48万円」を含む（寄附金税額控除）", "chiho", "本則:314_7", ["2026-11-09", "2027-01-01", "2028-01-01"],
     ["から四十八万円を控除して得た額"], []),
    ("C09b", "（2026-01-01 の版）人的控除差調整額に基礎控除の差を含まない", "chiho", "本則:314_7", ["2026-01-01"], [], ["四十八万円"]),
    ("C09c", "特例控除額の定額の上限 115万8千円（指定都市 154万4千円）が入った版（令和10年度分から適用：令和8年法律第2号附則第11条第8項）", "chiho", "本則:314_7",
     ["2027-01-01", "2028-01-01"], ["百十五万八千円", "百五十四万四千円"], []),
    ("C10", "寄附金税額控除（道府県民税）：4%（2%）・特例 2/5（1/5）", "chiho", "本則:37_2", ASOFS,
     ["その超える金額の百分の四（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の二）", "の五分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、五分の一）"], []),
    ("C10a", "特例控除額の定額の上限（道府県）77万2千円（指定都市 38万6千円）", "chiho", "本則:37_2", ["2027-01-01", "2028-01-01"], ["七十七万二千円", "三十八万六千円"], []),
    ("C11", "特例控除の割合の読替え（復興特別所得税分）：平成26年度〜令和20年度", "chiho", "附則:5_6", ["2026-01-01", "2026-11-09", "2027-01-01"],
     ["平成二十六年度から令和二十年度までの各年度分の個人の市町村民税", "百分の八十四・八九五", "百分の七十九・七九", "百分の六十九・五八", "百分の六十六・五一七",
      "百分の五十六・三〇七", "百分の四十九・一六", "百分の四十四・〇五五", "百分の五十九・三七", "百分の七十四・六八五"], []),
    ("C11a", "（2028-01-01 の版）期間を令和30年度までに延ばし、令和31年度以後の読替えを追加", "chiho", "附則:5_6", ["2028-01-01"],
     ["平成二十六年度から令和三十年度まで", "令和三十一年度以後", "百分の八十四・九五"], []),
    ("C12", "申告特例控除（市町村民税）の割合の表", "chiho", "附則:7_2", ASOFS,
     ["| 百九十五万円以下の金額 | 八十五分の五 |", "| 百九十五万円を超え三百三十万円以下の金額 | 八十分の十 |", "| 三百三十万円を超え六百九十五万円以下の金額 | 七十分の二十 |",
      "| 六百九十五万円を超え九百万円以下の金額 | 六十七分の二十三 |", "| 九百万円を超える金額 | 五十七分の三十三 |", "第三百十四条の七第一項及び第十一項の規定を適用した場合の所得割の額から控除"], []),
    ("C12a", "申告特例控除の区分に「所得税の基礎控除の額−48万円」を含む", "chiho", "附則:7_2", ["2026-11-09", "2027-01-01", "2028-01-01"], ["から四十八万円を控除して得た額"], []),
    ("C12b", "（2026-01-01 の版）申告特例控除の区分に基礎控除の差を含まない", "chiho", "附則:7_2", ["2026-01-01"], [], ["四十八万円"]),
    ("C13", "申告特例控除の割合の読替え（平成28年度〜令和20年度）", "chiho", "附則:7_3", ["2026-01-01", "2026-11-09", "2027-01-01"],
     ["八十四・八九五分の五・一〇五", "七十九・七九分の十・二一", "六十九・五八分の二十・四二", "六十六・五一七分の二十三・四八三", "五十六・三〇七分の三十三・六九三", "令和二十年度"], []),
    ("C14", "配当控除（市町村民税）1.6%（2.24%）／0.8%（1.12%）ほか、千万円超の部分", "chiho", "附則:5", ASOFS,
     ["百分の一・六（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の二・二四）", "百分の〇・八（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一・一二）",
      "百分の一・二（当該納税義務者が地方自治法第二百五十二条の十九第一項の市", "百分の〇・五六", "千万円を超える場合", "第三百十四条の三及び第三百十四条の六の規定を適用した場合の所得割の額から控除"], []),
    ("C15", "住宅借入金等特別税額控除：3/5（4/5）・2/5（1/5）、限度 3%（4%）・58,500円（78,000円）、2%（1%）・39,000円（19,500円）、特別特定取得の読替え", "chiho", JUTAKU_KEY, ASOFS,
     ["の五分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、五分の四）", "五万八千五百円", "七万八千円", "三万九千円", "一万九千五百円",
      "八万千九百円", "十万九千二百円", "五万四千六百円", "二万七千三百円",
      "第三百十四条の三及び第三百十四条の六の規定を適用した場合の所得割の額から控除"], []),
    ("C15c", "住宅借入金等特別税額控除の控除限度額の基礎に「所得税の基礎控除の額−48万円」を加える（居住年 平成28年〜令和7年）", "chiho", JUTAKU_KEY,
     ["2026-11-09", "2027-01-01", "2028-01-01"], ["居住年が平成二十八年から令和七年までの各年である場合には", "から四十八万円を控除して得た額"], []),
    ("C15d", "（2026-01-01 の版）控除限度額の基礎に基礎控除の差を含まない", "chiho", JUTAKU_KEY, ["2026-01-01"], [], ["四十八万円"]),
    ("C36", "（2026-03-31 の版）寄附金税額控除・申告特例・住宅借入金等に基礎控除の差がない", "chiho-0401", "本則:314_7", ["2026-03-31"], [], ["四十八万円"]),
    ("C36a", "", "chiho-0401", "本則:37_2", ["2026-03-31"], [], ["四十八万円"]),
    ("C36b", "", "chiho-0401", "附則:5_4_2", ["2026-03-31"], [], ["四十八万円"]),
    ("C36c", "", "chiho-0401", "附則:7_2", ["2026-03-31"], [], ["四十八万円"]),
    ("C36d", "（2026-04-01 の版＝令和8年法律第2号の施行）基礎控除の差が入った", "chiho-0401", "本則:314_7", ["2026-04-01"], ["から四十八万円を控除して得た額"], []),
    ("C36e", "", "chiho-0401", "本則:37_2", ["2026-04-01"], ["から四十八万円を控除して得た額"], []),
    ("C36f", "", "chiho-0401", "附則:5_4", ["2026-04-01"], ["から四十八万円を控除して得た額", "居住年が平成二十八年から令和七年までの各年である場合には"], []),
    ("C36g", "", "chiho-0401", "附則:7_2", ["2026-04-01"], ["から四十八万円を控除して得た額"], []),
    ("C15a", "住宅借入金等特別税額控除の居住年 平成21年〜令和7年、令和20年度まで", "chiho", JUTAKU_KEY, ["2026-01-01", "2026-11-09"],
     ["平成二十一年から令和七年までの各年である場合に限る", "平成二十二年度から令和二十年度まで"], []),
    ("C15b", "住宅借入金等特別税額控除の居住年 平成21年〜令和12年、令和25年度まで（居住が令和8年1月1日以後の分から：令和8年法律第2号附則第11条第10項）", "chiho", JUTAKU_KEY,
     ["2027-01-01", "2028-01-01"], ["平成二十一年から令和十二年までの各年である場合に限る", "平成二十二年度から令和二十五年度まで"], []),
    ("C16", "同一生計配偶者・扶養親族の所得要件 58万円（令和8年度分）", "chiho", "本則:292", ["2026-01-01", "2026-11-09"], ["合計所得金額が五十八万円以下である者をいう"], []),
    ("C16a", "同一生計配偶者・扶養親族の所得要件 62万円（令和9年度分）", "chiho", "本則:292", ["2027-01-01", "2028-01-01"], ["合計所得金額が六十二万円以下である者をいう"], []),
    ("C17", "所得控除の額（住民税）", "chiho", "本則:314_2", ASOFS,
     ["三十三万円（その控除対象配偶者が老人控除対象配偶者", "各控除対象扶養親族につき三十三万円（その者が特定扶養親族", "である場合には四十五万円", "である場合には三十八万円",
      "各障害者につき二十六万円", "三十万円）", "五十三万円", "寡婦である所得割の納税義務者　二十六万円", "勤労学生である所得割の納税義務者　二十六万円",
      "前年の合計所得金額が二千四百万円以下である場合　四十三万円", "二万八千円", "三万五千円", "七万円を超える場合には、七万円", "二万五千円を超える場合には、二万五千円",
      "百三十三万円以下", "九十五万円以下である特定親族　四十五万円", "百二十三万円以下", "二分の一に相当する金額"], []),
    ("C17a", "ひとり親控除 30万円（令和9年度分まで）", "chiho", "本則:314_2", ["2026-01-01", "2026-11-09", "2027-01-01"], ["ひとり親である所得割の納税義務者　三十万円"], []),
    ("C17b", "ひとり親控除 33万円の版（令和10年度分から：令和8年法律第2号附則第11条第3項）", "chiho", "本則:314_2", ["2028-01-01"], ["ひとり親である所得割の納税義務者　三十三万円"], []),
    ("C18", "所得割の非課税の調整（附則第3条の3第5項）", "chiho", "附則:3_3", ASOFS,
     ["三十五万円に市町村民税の所得割の納税義務者の同一生計配偶者及び扶養親族の数に一を加えた数を乗じて得た金額に十万円を加算した金額", "三十二万円を加算した金額",
      "当該超える金額に第二号に掲げる額を同号に掲げる額と第三号に掲げる額との合計額で除して得た数値を乗じて得た金額"], []),
    ("C19", "配当割額・株式等譲渡所得割額の控除 市 3/5", "chiho", "本則:314_9", ASOFS, ["五分の三を乗じて得た金額"], []),
    ("C19a", "配当割額・株式等譲渡所得割額の控除 県 2/5", "chiho", "本則:37_4", ASOFS, ["五分の二を乗じて得た金額"], []),
    ("C20", "標準税率の定義", "chiho", "本則:1", ASOFS, ["これによることを要しない税率"], []),
    ("C21", "均等割のみ（事務所・家屋敷）と均等割＋所得割（住所）", "chiho", "本則:294", ASOFS,
     ["第一号の者に対しては均等割額及び所得割額の合算額により", "第二号及び第四号の者に対しては均等割額により", "市町村内に事務所、事業所又は家屋敷を有する個人で当該市町村内に住所を有しない者"], []),
    ("C22", "所得割・均等割の条に制限税率の文言がない", "chiho", "本則:314_3", ASOFS, [], ["制限税率", "超えることができない"]),
    ("C22a", "", "chiho", "本則:310", ASOFS, [], ["制限税率", "超えることができない"]),
    ("C22b", "", "chiho", "本則:35", ASOFS, [], ["制限税率", "超えることができない"]),
    ("C22c", "", "chiho", "本則:38", ASOFS, [], ["制限税率", "超えることができない"]),
    ("C40", "退職所得の分離課税：市町村民税 6%（「標準税率」の語がない）、その年の1月1日の住所の市町村が課する", "chiho", "本則:328_3", ASOFS, ["分離課税に係る所得割の税率は、百分の六とする。"], ["標準税率"]),
    ("C40a", "", "chiho", "本則:50_4", ASOFS, ["分離課税に係る所得割の税率は、百分の四とする。"], ["標準税率"]),
    ("C40b", "", "chiho", "本則:328", ASOFS, ["当該退職手当等の支払を受けるべき日の属する年の一月一日現在におけるその者の住所所在の市町村において課する"], []),
    ("C40c", "", "chiho", "本則:328_2", ASOFS, ["分離課税に係る所得割の課税標準は、その年中の退職所得の金額とする。"], []),
    ("C41", "上場株式等の配当所得等の分離課税：市 3%（指定都市 4%）、県 2%（1%）、配当控除なし", "chiho", "附則:33_2", ASOFS,
     ["百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）", "百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）",
      "附則第五条第三項の規定は、適用しない"], ["標準税率"]),
    ("C41a", "上場株式等の譲渡所得等の分離課税：市 3%（4%）、県 2%（1%）", "chiho", "附則:35_2_2", ASOFS,
     ["百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）", "百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）"], ["標準税率"]),
    ("C42", "特定配当等・特定株式等譲渡所得：確定申告書に記載がなければ総所得金額から除く", "chiho", "本則:313", ["2026-11-09", "2027-01-01", "2028-01-01"],
     ["に係る所得を有する者に係る総所得金額は、当該特定配当等に係る所得の金額を除外して算定する", "特定株式等譲渡所得金額に係る所得を有する者に係る総所得金額は"], []),
    ("C30", "森林環境税：住所を有する個人、1,000円、賦課期日1月1日、市町村が均等割と併せて賦課徴収、非課税", "shinrin", "本則:3", ["2026-11-09", "2027-01-01"],
     ["この法律の施行地に住所を有する個人に対しては、この法律により、国が均等の額により森林環境税を課する。"], []),
    ("C30a", "", "shinrin", "本則:5", ["2026-11-09", "2027-01-01"], ["森林環境税の税率は、千円とする。"], []),
    ("C30b", "", "shinrin", "本則:6", ["2026-11-09", "2027-01-01"], ["当該年度の初日の属する年の一月一日"], []),
    ("C30c", "", "shinrin", "本則:4", ["2026-11-09", "2027-01-01"], ["百三十五万円を超える場合を除く", "前年の合計所得金額が政令で定める金額以下である者"], []),
    ("C30d", "", "shinrin", "本則:7", ["2026-11-09", "2027-01-01"], ["個人の市町村民税の均等割の賦課徴収（地方税法第六条、第七条、第三百十一条、第三百二十一条第二項又は第三百二十三条の規定によるものを除く。）の例により"], []),
    ("C30e", "森林環境税の適用：令和6年度分から", "shinrin", "附則:2", ["2026-11-09", "2027-01-01"], ["令和六年度以後の年度分の森林環境税について適用する"], []),
    ("C31", "森林環境税の非課税の金額（政令）：35万円×級地の率×(人数+1)+10万円（+21万円×級地の率）", "shinrin-rei", "本則:1", ["2026-11-09"],
     ["三十五万円に、生活保護法", "十万円を加算した金額", "二十一万円に、前号に規定する総務省令で定める率"], ["条例"]),
    ("C32", "東日本大震災の臨時特例（均等割に500円加算）は平成35年度（令和5年度）まで", "shinsai", "本則:2", ["2026-11-09"],
     ["平成二十六年度から平成三十五年度までの各年度分の個人の市町村民税に限り", "五百円を加算した額"], []),
    ("C33", "施行令第6条の17：端数の特例の対象に個人の市町村民税は含まれない", "chiho-rei", "本則:6_17", ["2026-11-09", "2027-01-01"],
     ["法第二十条の四の二第一項ただし書に規定する政令で定める地方税は", "利子等に係る道府県民税"], ["市町村民税"]),
    ("C34", "調整控除の表の（３）（４）：ひとり親のうち父／母", "chiho-rei", "本則:48_7_2", ["2026-11-09", "2027-01-01"], ["ひとり親のうち父である者", "ひとり親のうち母である者"], []),
]

SHITEI = ["大阪市", "名古屋市", "京都市", "横浜市", "神戸市", "北九州市", "札幌市", "川崎市", "福岡市", "広島市", "仙台市", "千葉市", "さいたま市", "静岡市", "堺市",
          "新潟市", "浜松市", "岡山市", "相模原市", "熊本市"]


def run_claims():
    rows, res = [], []
    for cid, desc, short, key, asofs, must, mustnot in CLAIMS:
        for a in asofs:
            k = key[a] if isinstance(key, dict) else key
            t = text(short, a, k)
            if t is None:
                ok, miss, bad = False, ["(条が見つからない)"], []
            else:
                flat = t.replace("\n", "")
                miss = [m for m in must if m not in flat and m not in t]
                bad = [m for m in mustnot if m in flat]
                ok = not miss and not bad
            res.append({"claim": cid, "desc": desc, "law": short, "article": k, "asof": a, "ok": ok, "missing": miss, "present_but_should_not": bad})
            rows.append(f"| {cid} | {short} {k} | {a} | {'OK' if ok else 'NG'} | {'; '.join(miss + ['禁止:' + b for b in bad])} |")
    t = text("shitei", "2026-11-09", "本則:(no-article)") or ""
    names = re.findall(r"[^\s　]+市", t.split("指定する。")[-1]) if "指定する。" in t else []
    ok = sorted(names) == sorted(SHITEI)
    res.append({"claim": "C35", "desc": "指定都市20市", "law": "shitei", "asof": "2026-11-09", "ok": ok, "names": names})
    rows.append(f"| C35 | shitei 本則 | 2026-11-09 | {'OK' if ok else 'NG'} | {len(names)} 市: {'、'.join(names)} |")
    head = ["# 条文の文字列の検査", "", "各主張について、版（asof）ごとに、含むべき文字列があり、含まないべき文字列がないかを見た。", "",
            "| 主張 | 条 | 版 | 結果 | 不足・禁止語 |", "|---|---|---|---|---|"]
    descs = ["", "## 主張の内容", ""] + [f"- {c[0]}：{c[1]}" for c in CLAIMS if c[1]] + ["- C35：指定都市の一覧（政令）が 20 市"]
    (OUT / "evidence.md").write_text("\n".join(head + rows + descs) + "\n", encoding="utf-8")
    (OUT / "evidence.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    ng = [r for r in res if not r["ok"]]
    print(f"claims: {len(res)} checks, NG={len(ng)}")
    for r in ng:
        print("  NG", r)
    return res


# ---------------------------------------------------------------------------
# 2. 項ごとの版の比較
# ---------------------------------------------------------------------------
PARA_RE = re.compile(r"\n(?=[２-９]|１[０-９]|２[０-９])")


def paragraphs(t):
    if t is None:
        return {}
    parts = PARA_RE.split(t)
    res = {}
    for i, p in enumerate(parts):
        res[str(i + 1)] = p
    return res


def norm_refs(s):
    # 条番号の付け替えだけの違いを除いて比べるための正規化（附則第五条の四の二 → 附則第五条の四 など）
    s = s.replace("第五条の四の二", "第五条の四")
    return s


def compare(short_key_pairs):
    out = ["# 項ごとの版の比較", "",
           "条を項（行頭の全角数字）で分け、版の間で同じかを比べた。「同じ」は文字列が完全に一致すること。違う項は差分の一部を示す。", ""]
    for title, (ka, a), (kb, b), paras in short_key_pairs:
        ta, tb = text("chiho", a, ka), text("chiho", b, kb)
        pa, pb = paragraphs(ta), paragraphs(tb)
        out.append(f"## {title}：{ka}@{a} と {kb}@{b}")
        out.append("")
        out.append("| 項 | 結果 |")
        out.append("|---|---|")
        for p in paras or sorted(set(pa) | set(pb), key=int):
            x, y = pa.get(p), pb.get(p)
            if x is None or y is None:
                out.append(f"| {p} | 片方にない |")
                continue
            if x == y:
                out.append(f"| {p} | 同じ |")
            elif norm_refs(x) == norm_refs(y):
                out.append(f"| {p} | 条番号の付け替えだけ違う |")
            else:
                sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
                ds = []
                for op, i1, i2, j1, j2 in sm.get_opcodes():
                    if op != "equal":
                        ds.append(f"{op}【{x[i1:i2][:60]}】→【{y[j1:j2][:60]}】")
                out.append(f"| {p} | 違う：{' / '.join(ds[:4])}{' …' if len(ds) > 4 else ''} |")
        out.append("")
    (OUT / "versions.md").write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. 率の恒等式
# ---------------------------------------------------------------------------
def kanji_frac(s):
    """「八十四・八九五」のような漢数字（小数点つき）を Fraction にする。"""
    digits = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if "・" in s:
        ip, fp = s.split("・")
    else:
        ip, fp = s, ""
    v = 0
    cur = 0
    for ch in ip:
        if ch in digits:
            cur = digits[ch]
        elif ch == "十":
            v += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            v += (cur or 1) * 100
            cur = 0
    v += cur
    f = Fr(0)
    for i, ch in enumerate(fp):
        f += Fr(digits[ch], 10 ** (i + 1))
    return v + f


def identities():
    out = ["# 率の表どうしの恒等式", ""]
    t = text("chiho", "2026-11-09", "附則:5_6")
    pairs = re.findall(r"「百分の([一二三四五六七八九十〇・]+)」とあるのは「百分の([一二三四五六七八九十〇・]+)」", t)
    out += ["## 附則第5条の6（2026-11-09 の版）：読替え前の割合 r と読替え後の割合 r' が r' = 90 − (90 − r)×1.021 になるか", "",
            "（90 − r は所得税の税率に当たる。附則第5条の5の第3〜5号の 50・60・75 は 90 − 40・30・15）", "", "| r | r' | 90−(90−r)×1.021 | 一致 |", "|---|---|---|---|"]
    allok = True
    seen = set()
    for a, b in pairs:
        ra, rb = kanji_frac(a), kanji_frac(b)
        if (ra, rb) in seen:
            continue
        seen.add((ra, rb))
        calc = 90 - (90 - ra) * Fr(1021, 1000)
        ok = calc == rb
        allok &= ok
        out.append(f"| {float(ra)} | {float(rb)} | {float(calc)} | {'OK' if ok else 'NG'} |")
    out.append("")
    t28 = text("chiho", "2028-01-01", "附則:5_6")
    p28 = re.findall(r"令和三十一年度以後.*?とする。", t28.replace("\n", ""))
    if p28:
        pairs28 = re.findall(r"「百分の([一二三四五六七八九十〇・]+)」とあるのは「百分の([一二三四五六七八九十〇・]+)」", p28[0])
        out += ["## 附則第5条の6（2028-01-01 の版）の令和31年度以後の読替え：r' = 90 − (90 − r)×1.01 になるか（意味の解釈はしない）", "", "| r | r' | 計算 | 一致 |", "|---|---|---|---|"]
        for a, b in pairs28:
            ra, rb = kanji_frac(a), kanji_frac(b)
            calc = 90 - (90 - ra) * Fr(101, 100)
            out.append(f"| {float(ra)} | {float(rb)} | {float(calc)} | {'OK' if calc == rb else 'NG'} |")
        out.append("")
    # 附則7の3：申告特例の割合 (90-r')... 「八十五分の五」→「八十四・八九五分の五・一〇五」
    t73 = text("chiho", "2026-11-09", "附則:7_3")
    p73 = re.findall(r"「([一二三四五六七八九十〇・]+)分の([一二三四五六七八九十〇・]+)」とあるのは「([一二三四五六七八九十〇・]+)分の([一二三四五六七八九十〇・]+)」", t73)
    out += ["## 附則第7条の3（2026-11-09 の版）：申告特例の割合 a/b（読替え後）が、b = 特例控除の割合（読替え後）、a = 90 − b になるか", "",
            "| 読替え前 | 読替え後 | a+b=90 | b が附則5の6の読替え後の割合に一致 |", "|---|---|---|---|"]
    rates56 = {kanji_frac(b) for _, b in pairs}
    seen = set()
    for d0, n0, d1, n1 in p73:
        key = (d0, n0, d1, n1)
        if key in seen:
            continue
        seen.add(key)
        b, a = kanji_frac(d1), kanji_frac(n1)
        out.append(f"| {kanji_frac(n0)}/{kanji_frac(d0)} | {float(a)}/{float(b)} | {'OK' if a + b == 90 else 'NG'} | {'OK' if b in rates56 else 'NG'} |")
    out.append("")
    # 市と県の配分
    out += ["## 市町村民税と道府県民税の配分（指定都市とそれ以外で合計が同じか）", "", "| 項目 | 指定都市以外（市＋県） | 指定都市（市＋県） | 一致 |", "|---|---|---|---|"]
    items = [("所得割の標準税率", Fr(6, 100) + Fr(4, 100), Fr(8, 100) + Fr(2, 100)),
             ("調整控除の率", Fr(3, 100) + Fr(2, 100), Fr(4, 100) + Fr(1, 100)),
             ("寄附金税額控除（基本控除）の率", Fr(6, 100) + Fr(4, 100), Fr(8, 100) + Fr(2, 100)),
             ("特例控除の配分", Fr(3, 5) + Fr(2, 5), Fr(4, 5) + Fr(1, 5)),
             ("特例控除の定額上限（令和10年度分から）", 1158000 + 772000, 1544000 + 386000),
             ("住宅借入金等特別税額控除の配分", Fr(3, 5) + Fr(2, 5), Fr(4, 5) + Fr(1, 5)),
             ("同 控除限度額の率", Fr(3, 100) + Fr(2, 100), Fr(4, 100) + Fr(1, 100)),
             ("同 控除限度額の上限", 58500 + 39000, 78000 + 19500),
             ("同 特別特定取得の率", Fr(42, 1000) + Fr(28, 1000), Fr(56, 1000) + Fr(14, 1000)),
             ("同 特別特定取得の上限", 81900 + 54600, 109200 + 27300),
             ("配当控除（配当、1,000万円以下の部分）", Fr(16, 1000) + Fr(12, 1000), Fr(224, 10000) + Fr(56, 10000)),
             ("配当控除（配当、1,000万円超の部分）", Fr(8, 1000) + Fr(6, 1000), Fr(112, 10000) + Fr(28, 10000)),
             ("配当控除（証券投資信託、1,000万円以下）", Fr(8, 1000) + Fr(6, 1000), Fr(112, 10000) + Fr(28, 10000)),
             ("配当控除（一般外貨建等、1,000万円以下）", Fr(4, 1000) + Fr(3, 1000), Fr(56, 10000) + Fr(14, 10000))]
    for name, a, b in items:
        out.append(f"| {name} | {a} | {b} | {'OK' if a == b else 'NG'} |")
    out.append("")
    # ワンストップの全額控除の性質
    out += ["## 申告特例（ワンストップ）での住民税の控除の合計が (寄附金−2,000円)×100% になるか（上限にかからない場合）", "",
            "市：基本 6%＋特例 r'×3/5＋申告特例（特例×a/b）、県：基本 4%＋特例 r'×2/5＋申告特例。指定都市は 8%・4/5 と 2%・1/5。", "",
            "| 区分 r'（読替え後） | a/b | 指定都市以外 合計 | 指定都市 合計 |", "|---|---|---|---|"]
    table = [(Fr(84895, 1000), Fr(5105, 84895)), (Fr(7979, 100), Fr(1021, 7979)), (Fr(6958, 100), Fr(2042, 6958)),
             (Fr(66517, 1000), Fr(23483, 66517)), (Fr(56307, 1000), Fr(33693, 56307))]
    for r, ab in table:
        def tot(bc, bp, sc, sp):
            tk = r / 100
            return bc + bp + tk * sc * (1 + ab) + tk * sp * (1 + ab)
        n = tot(Fr(6, 100), Fr(4, 100), Fr(3, 5), Fr(2, 5))
        s = tot(Fr(8, 100), Fr(2, 100), Fr(4, 5), Fr(1, 5))
        out.append(f"| {float(r)}% | {ab} | {n} | {s} |")
    out.append("")
    out += ["## 確定申告の場合：所得税の寄附金控除による減税（(寄附金−2,000)×t×1.021）と住民税（基本10%＋特例 (90%−t×1.021)）の合計", "",
            "| 所得税率 t | 住民税の特例の割合（読替え後） | 合計 |", "|---|---|---|"]
    for t_, r in [(5, Fr(84895, 1000)), (10, Fr(7979, 100)), (20, Fr(6958, 100)), (23, Fr(66517, 1000)), (33, Fr(56307, 1000)), (40, Fr(4916, 100)), (45, Fr(44055, 1000))]:
        total = Fr(t_, 100) * Fr(1021, 1000) + Fr(10, 100) + r / 100
        out.append(f"| {t_}% | {float(r)}% | {total} |")
    out.append("")
    (OUT / "identities.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return allok


# ---------------------------------------------------------------------------
# 4. 調整控除の表の（７）が当たりうるか
# ---------------------------------------------------------------------------
def reachability():
    out = ["# 調整控除の表の（７）（配偶者特別控除の人的控除差）が当たりうるかの列挙", "",
           "条文の条件（第292条第1項第7号・第8号、第314条の2第1項第10号の2、第314条の6第1号イの表（７））を、配偶者の合計所得金額 s、納税義務者の合計所得金額 T、",
           "配偶者が事業専従者等か、の組み合わせで総当たりした。同一生計配偶者の上限 X は、令和7年度分 48万円（既存の公開資料の情報）、令和8年度分 58万円、令和9年度分 62万円。", ""]
    s_vals = sorted(set(list(range(0, 1340001, 10000)) + [479999, 480000, 480001, 499999, 500000, 549999, 550000, 579999, 580000, 580001, 619999, 620000, 620001, 1330000, 1330001]))
    T_vals = [0, 5000000, 9000000, 9000001, 9500000, 10000000, 10000001, 20000000]
    out += ["| 年度分 | X | （７）に当たる組み合わせの数 | s の範囲 |", "|---|---|---|---|"]
    res = {}
    for label, X in [("令和7年度分", 480000), ("令和8年度分", 580000), ("令和9年度分", 620000)]:
        hits = []
        for s, T, senju in itertools.product(s_vals, T_vals, [False, True]):
            doitsu = (not senju) and s <= X
            kojo_taisho = doitsu and T <= 10000000
            tokubetsu = (not senju) and s <= 1330000 and not kojo_taisho and T <= 10000000
            row7 = tokubetsu and s < 550000 and T <= 10000000
            if row7:
                hits.append((s, T))
        rng = f"{min(h[0] for h in hits)}〜{max(h[0] for h in hits)}" if hits else "なし"
        res[label] = len(hits)
        out.append(f"| {label} | {X} | {len(hits)} | {rng} |")
    out.append("")
    (OUT / "reachability.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return res


# ---------------------------------------------------------------------------
# 5. 計算の読み（式）。値の出典は docs/public-sources/20261109_round2_juminzei-tax-law-text.md
# ---------------------------------------------------------------------------
def floor_unit(x, unit):
    return (Fr(x) // unit) * unit


def life_ins_new(p):
    """新契約（一般・介護医療・新個人年金）：第314条の2第1項第5号。1円未満は丸めない（一次情報で決まらない）。"""
    p = Fr(p)
    if p <= 12000:
        return p
    if p <= 32000:
        return 12000 + (p - 12000) / 2
    if p <= 56000:
        return 22000 + (p - 32000) / 4
    return Fr(28000)


def life_ins_old(p):
    p = Fr(p)
    if p <= 15000:
        return p
    if p <= 40000:
        return 15000 + (p - 15000) / 2
    if p <= 70000:
        return Fr(27500) + (p - 40000) / 4
    return Fr(35000)


def life_ins_total(new_general=0, old_general=0, kaigo=0, new_nenkin=0, old_nenkin=0):
    def kind(new, old):
        if new and old:
            return min(life_ins_new(new) + life_ins_old(old), Fr(28000))
        if new:
            return life_ins_new(new)
        if old:
            return life_ins_old(old)
        return Fr(0)
    return min(kind(new_general, old_general) + (life_ins_new(kaigo) if kaigo else 0) + kind(new_nenkin, old_nenkin), Fr(70000))


def jishin(p):
    return min(Fr(p) / 2, Fr(25000))


def kiso(gokei):
    if gokei <= 24000000:
        return 430000
    if gokei <= 24500000:
        return 290000
    if gokei <= 25000000:
        return 150000
    return 0


# 調整控除の人的控除差（第314条の6第1号イの表）。配偶者は（６）だけ実装（（７）は令和8・9年度分では当たらない：reachability.md）
def jinteki_sa(p):
    total = 50000
    total += 10000 * p.get("shogaisha", 0) + 100000 * p.get("tokubetsu_shogaisha", 0) + 220000 * p.get("doukyo_tokubetsu_shogaisha", 0)
    if p.get("kafu_or_hitorioya_father"):
        total += 10000
    if p.get("hitorioya_mother"):
        total += 50000
    if p.get("kinro_gakusei"):
        total += 10000
    sp = p.get("spouse")  # None / "general" / "elderly"
    T = p["gokei"]
    if sp == "general":
        total += 50000 if T <= 9000000 else 40000 if T <= 9500000 else 20000 if T <= 10000000 else 0
    elif sp == "elderly":
        total += 100000 if T <= 9000000 else 60000 if T <= 9500000 else 30000 if T <= 10000000 else 0
    total += 50000 * p.get("fuyo_general", 0) + 180000 * p.get("fuyo_tokutei", 0) + 100000 * p.get("fuyo_rojin", 0) + 130000 * p.get("fuyo_doukyo_rojin", 0)
    return total


def chosei(p, taxable, shitei):
    if p["gokei"] > 25000000:
        return Fr(0), Fr(0)
    js = jinteki_sa(p)
    if taxable <= 2000000:
        base = min(js, taxable)
    else:
        base = max(js - (taxable - 2000000), 50000)
    rc, rp = (Fr(4, 100), Fr(1, 100)) if shitei else (Fr(3, 100), Fr(2, 100))
    return base * rc, base * rp


TOKUREI_BRACKETS = [(1950000, Fr(84895, 100000), Fr(5105, 84895)), (3300000, Fr(7979, 10000), Fr(1021, 7979)),
                    (6950000, Fr(6958, 10000), Fr(2042, 6958)), (9000000, Fr(66517, 100000), Fr(23483, 66517)),
                    (18000000, Fr(56307, 100000), Fr(33693, 56307)), (40000000, Fr(4916, 10000), Fr(33693, 56307)),
                    (None, Fr(44055, 100000), Fr(33693, 56307))]


def tokurei_rate(x):
    """x = 課税総所得金額 − 人的控除差調整額。x<0（山林・退職なし）は 90%。申告特例の割合は 900万円超を一つの区分とする表（附則7の2）。"""
    if x < 0:
        return Fr(90, 100), Fr(5105, 84895)  # 申告特例の表の最初の区分「百九十五万円以下」に負の値も入るという読み（I）
    for lim, r, ab in TOKUREI_BRACKETS:
        if lim is None or x <= lim:
            return r, ab
    raise AssertionError


def compute(p, inj, policy="P0"):
    """一人の令和8年度分または令和9年度分の個人住民税（所得割・均等割）と森林環境税。
    p: 事実と所得税側の結果（総所得金額等、所得控除の合計、人的控除の該当、寄附金、住宅借入金等）。
    inj: 注入するデータ（市・県の所得割の税率、均等割、指定都市か）。
    policy: 1円未満の扱い。P0=途中で丸めない、P1=算出所得割を1円未満切捨て、P2=P1＋税額控除を1円未満切捨て、P3=P1＋税額控除を1円未満切上げ。
    """
    steps = []
    shitei = inj["shitei"]
    taxable = floor_unit(max(p["soshotoku"] - p["kojo"], 0), 1000)  # 第20条の4の2第1項（どの額に当てるかは I）
    steps.append(("課税総所得金額（千円未満切捨て）", taxable))
    city = taxable * inj["city_rate"]
    pref = taxable * inj["pref_rate"]
    if policy in ("P1", "P2", "P3"):
        city, pref = floor_unit(city, 1), floor_unit(pref, 1)
    steps += [("市 算出所得割", city), ("県 算出所得割", pref)]
    cc, cp = chosei(p, taxable, shitei)
    steps += [("市 調整控除", cc), ("県 調整控除", cp)]
    city1, pref1 = max(city - cc, 0), max(pref - cp, 0)

    def rnd(x):
        if policy == "P2":
            return floor_unit(x, 1)
        if policy == "P3":
            return -floor_unit(-x, 1)
        return x
    credits_c, credits_p = Fr(0), Fr(0)
    # 住宅借入金等特別税額控除（附則第5条の4）
    j = p.get("jutaku")
    if j:
        diff = max(j["shotokuzei_kojo_kano"] - j["shotokuzei_mae"], 0)
        add_back = max(p["shotokuzei_kiso"] - 480000, 0) if j["kyojunen"] in range(2016, 2026) else 0
        base = j["shotokuzei_kazei"] + add_back
        if j.get("tokubetsu"):
            rc, rp, capc, capp = (Fr(56, 1000), Fr(14, 1000), 109200, 27300) if shitei else (Fr(42, 1000), Fr(28, 1000), 81900, 54600)
        else:
            rc, rp, capc, capp = (Fr(4, 100), Fr(1, 100), 78000, 19500) if shitei else (Fr(3, 100), Fr(2, 100), 58500, 39000)
        sc, sp = (Fr(4, 5), Fr(1, 5)) if shitei else (Fr(3, 5), Fr(2, 5))
        jc = rnd(min(diff * sc, min(base * rc, capc)))
        jp = rnd(min(diff * sp, min(base * rp, capp)))
        steps += [("市 住宅借入金等特別税額控除", jc), ("県 住宅借入金等特別税額控除", jp)]
        credits_c += jc
        credits_p += jp
    # 寄附金税額控除（第314条の7・第37条の2、附則第5条の6）と申告特例控除（附則第7条の2・第7条の3）
    k = p.get("kifu")
    if k:
        total = min(k["total"], Fr(p["soshotoku_tou"]) * Fr(30, 100))
        bc, bp = (Fr(8, 100), Fr(2, 100)) if shitei else (Fr(6, 100), Fr(4, 100))
        kc = max(total - 2000, 0) * bc
        kp = max(total - 2000, 0) * bp
        tc = tp = Fr(0)
        if k.get("tokurei", 0) > 2000:
            adj = jinteki_sa(p) + max(p["shotokuzei_kiso"] - 480000, 0)
            r, ab = tokurei_rate(taxable - adj)
            sc, sp = (Fr(4, 5), Fr(1, 5)) if shitei else (Fr(3, 5), Fr(2, 5))
            tc = min((k["tokurei"] - 2000) * r * sc, city1 * Fr(20, 100))
            tp = min((k["tokurei"] - 2000) * r * sp, pref1 * Fr(20, 100))
            steps += [("特例控除の割合", r), ("人的控除差調整額", adj)]
        dc = rnd(min(kc + tc, city1))
        dp = rnd(min(kp + tp, pref1))
        steps += [("市 寄附金税額控除（基本＋特例）", dc), ("県 寄附金税額控除（基本＋特例）", dp)]
        credits_c += dc
        credits_p += dp
        if k.get("onestop") and tc:
            oc, op = rnd(tc * ab), rnd(tp * ab)
            steps += [("市 申告特例控除", oc), ("県 申告特例控除", op)]
            credits_c += oc
            credits_p += op
    city2, pref2 = max(city1 - credits_c, 0), max(pref1 - credits_p, 0)
    # 所得割の非課税の調整（附則第3条の3第2項・第5項）
    n = p.get("n_fuyo", 0)
    L = 350000 * (n + 1) + 100000 + (320000 if n else 0)
    A = p["soshotoku_tou"]
    B, C = city2, pref2
    if B + C > 0 and L > A - (B + C):
        ex = L - (A - (B + C))
        ac, ap = ex * B / (B + C), ex * C / (B + C)
        steps += [("市 非課税の調整", ac), ("県 非課税の調整", ap)]
        city2, pref2 = max(city2 - ac, 0), max(pref2 - ap, 0)
    if p["soshotoku_tou"] <= L:
        steps.append(("所得割の非課税（附則第3条の3第4項）", "該当"))
        city2 = pref2 = Fr(0)
    steps += [("市 所得割（控除後）", city2), ("県 所得割（控除後）", pref2)]
    city_tax = floor_unit(city2 + inj["city_kinto"], 100)
    pref_tax = floor_unit(pref2 + inj["pref_kinto"], 100)
    steps += [("市町村民税（均等割を加え百円未満切捨て）", city_tax), ("道府県民税（同）", pref_tax), ("森林環境税", inj["shinrin"])]
    return {"city": int(city_tax), "pref": int(pref_tax), "total": int(city_tax + pref_tax + inj["shinrin"]), "steps": steps}


def fmt(v):
    if isinstance(v, Fr):
        return str(v.numerator) if v.denominator == 1 else f"{v}（≈{float(v):.4f}）"
    return str(v)


def examples():
    out = ["# 計算の読みによる計算例の再現", "",
           "総所得金額と所得控除の合計は、所得税側（給与所得の計算）の結果を入力として与える。所得控除の内訳は第314条の2 の読みで計算する。",
           "市町村・道府県ごとの値（税率・均等割）は、計算例のページに書かれた値を注入した（標準税率と違う値を含む）。", ""]
    res = []
    # 名古屋市（令和8年度）
    p = {"gokei": 3963200, "soshotoku": 3963200, "soshotoku_tou": 3963200, "spouse": "general", "fuyo_tokutei": 1, "fuyo_general": 1, "n_fuyo": 4}
    kojo = Fr(825600) + life_ins_total(old_general=80000) + 330000 + (450000 + 330000) + kiso(p["gokei"])
    p["kojo"] = kojo
    inj = {"shitei": True, "city_rate": Fr(77, 1000), "pref_rate": Fr(2, 100), "city_kinto": 2800, "pref_kinto": 1500, "shinrin": 1000}
    exp = {"city": 109800, "pref": 29400, "total": 140200, "kojo": 2400600, "jinteki_sa": 330000}
    r = compute(p, inj)
    ok = r["city"] == exp["city"] and r["pref"] == exp["pref"] and r["total"] == exp["total"] and kojo == exp["kojo"] and jinteki_sa(p) == exp["jinteki_sa"]
    res.append({"name": "名古屋市 令和8年度", "ok": ok, "result": {k: r[k] for k in ("city", "pref", "total")}, "expected": exp})
    out += ["## 名古屋市の計算例（令和8年度、指定都市、市民税は名古屋市の減税後の税率 7.7%・均等割 2,800円、県民税 2%・均等割 1,500円：ページの記載）", "",
            f"- 所得控除の合計（社保 825,600＋生命保険（旧 80,000→{fmt(life_ins_old(80000))}）＋配偶者 330,000＋扶養 450,000＋330,000（12歳は0）＋基礎 430,000）＝{fmt(kojo)}（ページ 2,400,600）",
            f"- 人的控除差の合計 {jinteki_sa(p)}（ページ 330,000）"] + [f"- {a}：{fmt(b)}" for a, b in r["steps"]] + [
            f"- 結果：市 {r['city']}（ページ 109,800）、県 {r['pref']}（ページ 29,400）、合計 {r['total']}（ページ 140,200）→ **{'一致' if ok else '不一致'}**", ""]
    # 横浜市（令和8年度）
    p = {"gokei": 3960000, "soshotoku": 3960000, "soshotoku_tou": 3960000, "spouse": "general", "fuyo_general": 1, "n_fuyo": 3}
    kojo = Fr(394800) + life_ins_total(new_general=90000) + jishin(20000) + 330000 + 330000 + kiso(p["gokei"])
    p["kojo"] = kojo
    inj = {"shitei": True, "city_rate": Fr(8, 100), "pref_rate": Fr(2025, 100000), "city_kinto": 3900, "pref_kinto": 1300, "shinrin": 1000}
    exp = {"city_shotokuwari": 192900, "pref_shotokuwari": 48800, "total": 247900, "kojo": 1522800}
    rr = {}
    for pol in ("P0", "P1"):
        r = compute(p, inj, pol)
        rr[pol] = r
    r = rr["P1"]
    city_sw = r["city"] - 3900
    pref_sw = r["pref"] - 1300
    ok = all(rr[pol]["total"] == exp["total"] for pol in rr) and kojo == exp["kojo"] and city_sw == exp["city_shotokuwari"] and pref_sw == exp["pref_shotokuwari"]
    res.append({"name": "横浜市 令和8年度", "ok": ok, "result": {k: r[k] for k in ("city", "pref", "total")}, "expected": exp})
    out += ["## 横浜市の計算例（令和8年度、指定都市、市民税 8%・均等割 3,900円、県民税 2.025%・均等割 1,300円：ページの記載）", "",
            f"- 所得控除の合計（社保 394,800＋生命保険（新 90,000→{fmt(life_ins_new(90000))}）＋地震 {fmt(jishin(20000))}＋配偶者 330,000＋扶養 330,000（13歳は0）＋基礎 430,000）＝{fmt(kojo)}（ページ 1,522,800）"] + [
            f"- {a}：{fmt(b)}" for a, b in r["steps"]] + [
            f"- 結果（P1：算出所得割を1円未満切捨て。ページの書き方）：市 {r['city']}（所得割分 {city_sw}、ページ 192,900）、県 {r['pref']}（所得割分 {pref_sw}、ページ 48,800）、合計 {r['total']}（ページ 247,900）",
            f"- P0（途中で丸めない）でも合計 {rr['P0']['total']} → **{'一致' if ok else '不一致'}**",
            "- 注：ページは所得割（控除後）を百円未満切捨てしてから均等割を足している。均等割が百円単位なので、均等割を足してから切り捨てても同じになる。", ""]
    # 仮の例（令和9年度、指定都市以外の標準税率、ワンストップのふるさと納税）
    out += ["## 仮の例 A（令和9年度分、指定都市以外、標準税率・標準の均等割を注入。単身の給与所得者、特例控除対象寄附金 50,000円、申告特例）", ""]
    p = {"gokei": 4000000, "soshotoku": 4000000, "soshotoku_tou": 4000000, "kojo": 600000 + 430000, "n_fuyo": 0, "shotokuzei_kiso": 1040000,
         "kifu": {"total": 50000, "tokurei": 50000, "onestop": True}}
    inj = {"shitei": False, "city_rate": Fr(6, 100), "pref_rate": Fr(4, 100), "city_kinto": 3000, "pref_kinto": 1000, "shinrin": 1000}
    r = compute(p, inj)
    kc = [b for a, b in r["steps"] if a.startswith("市 寄附金") or a.startswith("市 申告特例")]
    kp = [b for a, b in r["steps"] if a.startswith("県 寄附金") or a.startswith("県 申告特例")]
    out += ["- 所得税の基礎控除の額（令和8年分、所得税側の結果を入力）：1,040,000（人的控除差調整額に 1,040,000−480,000 を足す）"] + [f"- {a}：{fmt(b)}" for a, b in r["steps"]] + [
            f"- 寄附金関係の控除の合計：市 {fmt(sum(kc))}、県 {fmt(sum(kp))}、合計 {fmt(sum(kc) + sum(kp))}（＝(50,000−2,000)×100% = 48,000 になるはず：{'OK' if sum(kc) + sum(kp) == 48000 else 'NG'}）", ""]
    res.append({"name": "仮の例A", "ok": sum(kc) + sum(kp) == 48000, "result": {k: r[k] for k in ("city", "pref", "total")}})
    # 仮の例 B（令和9年度、住宅借入金等特別税額控除）
    out += ["## 仮の例 B（令和9年度分、指定都市以外、標準。住宅借入金等特別税額控除、居住年 令和5年）", ""]
    p = {"gokei": 3000000, "soshotoku": 3000000, "soshotoku_tou": 3000000, "kojo": 450000 + 430000 + 330000, "spouse": "general", "n_fuyo": 1, "shotokuzei_kiso": 1040000,
         "jutaku": {"shotokuzei_kojo_kano": 140000, "shotokuzei_mae": 30000, "shotokuzei_kazei": 690000, "kyojunen": 2023}}
    r = compute(p, inj)
    out += ["- 所得税側の結果（入力）：住宅借入金等特別税額控除額 140,000、控除前の所得税額 30,000、課税総所得金額等 690,000、基礎控除の額 1,040,000"] + [f"- {a}：{fmt(b)}" for a, b in r["steps"]] + [""]
    res.append({"name": "仮の例B", "ok": True, "result": {k: r[k] for k in ("city", "pref", "total")}})
    # 仮の例 C（所得割の非課税の調整）
    out += ["## 仮の例 C（非課税の境目のすぐ上：単身、総所得金額等 451,000、所得控除は基礎控除だけ）", ""]
    p = {"gokei": 451000, "soshotoku": 451000, "soshotoku_tou": 451000, "kojo": 430000, "n_fuyo": 0}
    r = compute(p, inj)
    out += [f"- {a}：{fmt(b)}" for a, b in r["steps"]] + ["- 注：均等割の非課税（条例の額）は別の判定（既存の仮説 H2）。ここでは均等割を課す前提で足している。", ""]
    res.append({"name": "仮の例C", "ok": True, "result": {k: r[k] for k in ("city", "pref", "total")}})
    (OUT / "examples.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    (OUT / "examples.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res


def rounding_sensitivity():
    rng = random.Random(20261109)
    rates = [(Fr(6, 100), Fr(4, 100), False), (Fr(8, 100), Fr(2, 100), True), (Fr(61, 1000), Fr(4, 100), False), (Fr(77, 1000), Fr(2, 100), True),
             (Fr(8, 100), Fr(2025, 100000), True), (Fr(6, 100), Fr(4025, 100000), False)]
    N = 20000
    diff = {"P1": 0, "P2": 0, "P3": 0}
    diff_by_rate = {}
    maxdiff = {"P1": 0, "P2": 0, "P3": 0}
    for i in range(N):
        cr, pr, sh = rng.choice(rates)
        so = rng.randrange(500000, 20000000)
        kojo = rng.randrange(430000, min(so, 3000000) + 430001)
        p = {"gokei": so, "soshotoku": so, "soshotoku_tou": so, "kojo": kojo, "n_fuyo": rng.choice([0, 0, 1, 2]),
             "spouse": rng.choice([None, "general"]), "fuyo_general": rng.choice([0, 1]), "shotokuzei_kiso": rng.choice([580000, 630000, 680000, 880000, 950000, 1040000])}
        if rng.random() < 0.6:
            t = rng.randrange(3000, 400000)
            p["kifu"] = {"total": t, "tokurei": t if rng.random() < 0.8 else 0, "onestop": rng.random() < 0.5}
        if rng.random() < 0.3:
            p["jutaku"] = {"shotokuzei_kojo_kano": rng.randrange(10000, 350000), "shotokuzei_mae": rng.randrange(0, 300000),
                           "shotokuzei_kazei": max(so - kojo - 300000, 0), "kyojunen": rng.choice([2019, 2022, 2024, 2025])}
        inj = {"shitei": sh, "city_rate": cr, "pref_rate": pr, "city_kinto": 3000, "pref_kinto": 1000, "shinrin": 1000}
        base = compute(p, inj, "P0")
        for pol in ("P1", "P2", "P3"):
            r = compute(p, inj, pol)
            d = abs(r["total"] - base["total"])
            if d:
                diff[pol] += 1
                key = (pol, f"{float(cr) * 100:g}%/{float(pr) * 100:g}%")
                diff_by_rate[key] = diff_by_rate.get(key, 0) + 1
                maxdiff[pol] = max(maxdiff[pol], d)
    out = ["# 1円未満の扱いを変えたときに年税額（市＋県＋森林環境税）が変わる頻度", "",
           f"乱数の種 20261109 で {N} 件の仮の入力を作り、P0（途中で丸めない。百円未満の切捨てだけ）と比べた。",
           "P1＝算出所得割を1円未満切捨て、P2＝P1＋税額控除（住宅・寄附金・申告特例）を1円未満切捨て、P3＝P1＋税額控除を1円未満切上げ。", "",
           "| 方式 | P0 と違った件数 | 最大の差（円） |", "|---|---|---|"]
    for pol in ("P1", "P2", "P3"):
        out.append(f"| {pol} | {diff[pol]} / {N} | {maxdiff[pol]} |")
    out += ["", "## 税率の組み合わせ別（違った件数）", "", "| 方式 | 市/県の税率 | 件数 |", "|---|---|---|"]
    for (pol, rk), c in sorted(diff_by_rate.items()):
        out.append(f"| {pol} | {rk} | {c} |")
    (OUT / "rounding.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return diff, maxdiff


def haigusha_tokubetsu_table():
    """第314条の2第1項第10号の2 の式を 1円刻みで評価し、配偶者の合計所得金額の区間ごとの控除額をまとめる（納税義務者 900万円以下・900万超950万以下・950万超1000万以下）。
    同一生計配偶者の上限（令和8年度分 58万、令和9年度分 62万）を超える配偶者だけが対象（控除対象配偶者に当たらないもの）。"""
    t = text("chiho", "2026-11-09", "本則:314_2").replace("\n", "")
    must = ["前年の合計所得金額が百万円以下である配偶者　三十三万円", "三十八万円から当該配偶者の前年の合計所得金額のうち九十三万一円を超える部分の金額",
            "五万円の整数倍の金額から三万円を控除した金額", "前年の合計所得金額が百三十万円を超える配偶者　三万円", "三分の二に相当する金額（当該金額に一万円未満の端数がある場合には、これを切り上げた金額）",
            "三分の一に相当する金額（当該金額に一万円未満の端数がある場合には、これを切り上げた金額）", "前年の合計所得金額が百三十三万円以下であるもの"]
    ok = all(m in t for m in must)

    def base(s):
        if s <= 1000000:
            return 330000
        if s <= 1300000:
            ex = s - 930001
            k = (ex + 30000) // 50000
            v = 50000 * k - 30000
            if v > ex:
                v -= 50000
            if v != ex:
                pass
            return 380000 - v
        return 30000

    def ceil10k(x):
        return -((-x) // 10000) * 10000
    out = ["# 配偶者特別控除（住民税）の区間（第314条の2第1項第10号の2 を 1円刻みで評価）", "", f"条文の文字列の確認：{'OK' if ok else 'NG'}", ""]
    for label, lo in [("令和8年度分（同一生計配偶者の上限 58万円）", 580001), ("令和9年度分（同 62万円）", 620001)]:
        out += [f"## {label}", "", "| 配偶者の合計所得金額 | 納税義務者 900万円以下 | 900万超950万以下 | 950万超1,000万以下 |", "|---|---|---|---|"]
        prev, start = None, lo
        for s in range(lo, 1330002):
            if s <= 1330000:
                b = base(s)
                cur = (b, ceil10k(Fr(b * 2, 3)), ceil10k(Fr(b, 3)))
            else:
                cur = (0, 0, 0)
            if prev is not None and cur != prev:
                out.append(f"| {start:,}〜{s - 1:,} | {prev[0]:,} | {int(prev[1]):,} | {int(prev[2]):,} |")
                start = s
            prev = cur
        out.append(f"| {start:,}〜 | {prev[0]:,} | {int(prev[1]):,} | {int(prev[2]):,} |")
        out.append("")
    (OUT / "haigusha_tokubetsu.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return ok


def municipal_checks():
    checks = [
        ("nagoya_keisanrei.txt", ["市民税・県民税の計算例（令和8年度）", "3,963,200円－2,400,600円＝1,562,600円→1,562,000円(1,000円未満切捨)", "1,562,000円×7.7%＝120,274円",
                                  "1,562,000円×2%＝31,240円", "市民税調整控除額 330,000円×4%＝13,200円", "120,274円－13,200円+2,800円＝109,874円→109,800円(100円未満切捨)",
                                  "31,240円－3,300円＋1,500円＝29,440円→29,400円(100円未満切捨)", "139,200円＋1,000円＝140,200円", "名古屋市市民税減税を適用した税率"]),
        ("yokohama_keisan.txt", ["2,437,000円×8％（市民税の税率）＝194,960円", "2,437,000円×2.025％（県民税の税率）＝49,349.25円→49,349円（1円未満切捨）",
                                 "50,000円×4％＝2,000円", "50,000円×1％＝500円", "194,960円－2,000円＝192,960円→192,900円（百円未満切捨）",
                                 "49,349円－500円＝48,849円→48,800円（百円未満切捨）", "3,900円（市民税）＋1,300円（県民税）＝5,200円", "241,700円＋5,200円＋1,000円＝247,900円"]),
        ("chuo_zeigakukoujo.txt", ["税額控除は次の順序で控除します。", "1円未満の端数がある場合は、1円に切り上げ", "配偶者特別控除（配偶者の合計所得金額が48万円超50万円未満）"]),
        ("soumu_choka.txt", ["超過課税実施団体数（令和7年4月1日現在）", "＜道府県民税＞個人均等割 37団体", "所得割 1団体 神奈川県",
                             "＜市町村民税＞個人均等割 2団体 神奈川県横浜市、兵庫県神戸市", "所得割 1団体 兵庫県豊岡市"]),
    ]
    out = ["# 自治体のページの文字列の検査", "", "| ファイル | 文字列 | 結果 |", "|---|---|---|"]
    allok = True
    for f, ss in checks:
        t = (WEB / f).read_text(encoding="utf-8")
        for s in ss:
            ok = s in t
            allok &= ok
            out.append(f"| {f} | {s} | {'OK' if ok else 'NG'} |")
    (OUT / "municipal_checks.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return allok


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    claims = run_claims()
    compare([
        ("令和8年度分：寄附金税額控除（市）", ("本則:314_7", "2026-01-01"), ("本則:314_7", "2026-11-09"), None),
        ("令和9年度分：寄附金税額控除（市）", ("本則:314_7", "2026-11-09"), ("本則:314_7", "2027-01-01"), None),
        ("令和8年度分：申告特例控除", ("附則:7_2", "2026-01-01"), ("附則:7_2", "2026-11-09"), None),
        ("令和9年度分：申告特例控除", ("附則:7_2", "2026-11-09"), ("附則:7_2", "2027-01-01"), None),
        ("令和8年度分：住宅借入金等特別税額控除（附則5の4の2 → 5の4 に移動）", ("附則:5_4_2", "2026-01-01"), ("附則:5_4", "2026-11-09"), None),
        ("令和9年度分：住宅借入金等特別税額控除", ("附則:5_4", "2026-11-09"), ("附則:5_4", "2027-01-01"), None),
        ("調整控除（市）", ("本則:314_6", "2026-01-01"), ("本則:314_6", "2027-01-01"), None),
        ("所得割の税率（市）", ("本則:314_3", "2026-01-01"), ("本則:314_3", "2028-01-01"), None),
        ("所得控除（市）令和8年度分→令和9年度分", ("本則:314_2", "2026-11-09"), ("本則:314_2", "2027-01-01"), None),
        ("所得割の非課税（附則3の3）", ("附則:3_3", "2026-11-09"), ("附則:3_3", "2027-01-01"), None),
    ])
    idok = identities()
    reach = reachability()
    ex = examples()
    diff, maxdiff = rounding_sensitivity()
    mok = municipal_checks()
    hok = haigusha_tokubetsu_table()
    summary = {"claims_ng": [r for r in claims if not r["ok"]], "identities_ok": idok, "reachability": reach, "haigusha_tokubetsu_text_ok": hok,
               "examples": [{k: e[k] for k in ("name", "ok", "result")} for e in ex], "rounding_diff": diff, "rounding_maxdiff": maxdiff, "municipal_checks_ok": mok}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    sys.exit(main())
