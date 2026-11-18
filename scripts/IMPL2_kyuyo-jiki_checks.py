"""IMPL2 kyuyo-jiki: 取得済みの条文・通達・質疑応答事例から、公開資料の情報の文書が引く文を機械で照合し、
給与の年分の割当て（所基通36−9）と現在の判定コア（支払日の年）の違いを架空の設例で数える（ネットワークは使わない）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_kyuyo-jiki_checks.py

入力（先に実行しておくもの）:
  scripts/IMPL2_kyuyo-jiki_egov.py → scripts/results/IMPL2_kyuyo-jiki_egov/ho_<asof>.txt・sozoku_<asof>.txt
  scripts/IMPL2_kyuyo-jiki_nta.py pages → scripts/results/IMPL2_kyuyo-jiki_nta/pages/*.txt
  scripts/IMPL2_tsukin_nta.py pages3 → scripts/results/IMPL2_tsukin_nta/pages3/tebikihtml_2_3_4.txt（法定調書の手引「支払金額」欄）
出力: scripts/results/IMPL2_kyuyo-jiki_checks/checks.json

検査
  Q  引用の照合：QUOTES の各文が、指定したファイルの本文（空白・改行を除いて比べる）にそのまま含まれるか。
  S  設例：架空の給与の支払（支給日の定め・実際の支払日・死亡日など）を、(a) 所基通36−9・9−17 の読み（下の year_by_36_9）と
     (b) 現在の判定コア（packages/core の situation：支払日 when.on の年に入れ、死亡の日以後の支払は対象外）に当て、年分が違う設例を数える。
     (a) は通達の読みを関数にしたもの（法令の読み）で、判定コアの仕様ではない。
"""
import datetime as dt
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
EG = ROOT / "scripts" / "results" / "IMPL2_kyuyo-jiki_egov"
NT = ROOT / "scripts" / "results" / "IMPL2_kyuyo-jiki_nta" / "pages"
TS = ROOT / "scripts" / "results" / "IMPL2_tsukin_nta"
OUT = ROOT / "scripts" / "results" / "IMPL2_kyuyo-jiki_checks"

QUOTES = [
    (EG / "ho_2026-11-11.txt", "その年分の各種所得の金額の計算上収入金額とすべき金額又は総収入金額に算入すべき金額は、別段の定めがあるものを除き、その年において収入すべき金額"),
    (EG / "ho_2026-11-11.txt", "法人の法人税法第二条第十五号（定義）に規定する役員に対する賞与については、支払の確定した日から一年を経過した日までにその支払がされない場合には、その一年を経過した日においてその支払があつたものとみなして、前項の規定を適用する。"),
    (EG / "ho_2026-11-11.txt", "その年中にその居住者に対し支払うべきことが確定した給与等"),
    (EG / "ho_2026-11-11.txt", "十七　相続、遺贈又は個人からの贈与により取得するもの（相続税法（昭和二十五年法律第七十三号）の規定により相続、遺贈又は個人からの贈与により取得したものとみなされるものを含み"),
    (EG / "ho_2025-12-31.txt", "その年において収入すべき金額"),
    (EG / "sozoku_2026-11-11.txt", "被相続人の死亡により相続人その他の者が当該被相続人に支給されるべきであつた退職手当金、功労金その他これらに準ずる給与（政令で定める給付を含む。）で被相続人の死亡後三年以内に支給が確定したもの"),
    (NT / "kihon_05_01.txt", "36－9　給与所得の収入金額の収入すべき時期は、それぞれ次に掲げる日によるものとする。"),
    (NT / "kihon_05_01.txt", "(1)　契約又は慣習その他株主総会の決議等により支給日が定められている給与等（次の(2)に掲げるものを除く。）についてはその支給日、その日が定められていないものについてはその支給を受けた日"),
    (NT / "kihon_05_01.txt", "(3)　給与規程の改訂が既往にさかのぼって実施されたため既往の期間に対応して支払われる新旧給与の差額に相当する給与等で、その支給日が定められているものについてはその支給日、その日が定められていないものについてはその改訂の効力が生じた日"),
    (NT / "kihon_05_01.txt", "(4)　いわゆる認定賞与とされる給与等で、その支給日があらかじめ定められているものについてはその支給日、その日が定められていないものについては現実にその支給を受けた日（その日が明らかでない場合には、その支給が行われたと認められる事業年度の終了の日）"),
    (NT / "kihon_02_04.txt", "9－17　死亡した者に係る給与等、公的年金等及び退職手当等（法第30条第1項《退職所得》に規定する退職手当等をいう。）で、その死亡後に支給期の到来するもののうち相続税法の規定により相続税の課税価格計算の基礎に算入されるものについては、課税しないものとする。"),
    (NT / "kihon_02_04.txt", "（注）　上記の給与等、公的年金等及び退職手当等の支給期については、36－9、36－10及び36－14の(1)に定めるところによる。"),
    (NT / "kihon_31_01.txt", "183－1　法第183条第2項の規定する「支払の確定した日から1年を経過した日」とは、その支払の確定した日（36－9に定める日をいう。）の属する年の翌年の応当日の翌日をいうことに留意する。"),
    (NT / "kihon_28_01.txt", "181～223共－1　法第4編《源泉徴収》に規定する「支払の際」又は「支払をする際」の支払には、現実に金銭を交付する行為のほか、元本に繰り入れ又は預金口座に振り替えるなどその支払の債務が消滅する一切の行為が含まれることに留意する。"),
    (NT / "kihon_32_01.txt", "（1） 給与等の支払を受ける者が死亡により退職した場合"),
    (NT / "kihon_32_01.txt", "（4） 給与等の支払を受ける者が12月に支給期の到来する給与等の支払を受けた後に退職した場合"),
    (NT / "sokihon_01_03.txt", "3-33　相続開始の時において支給期の到来していない俸給、給料等は、法第3条第1項第2号に規定する退職手当金等には該当しないで、本来の相続財産に属するものであるから留意する。"),
    (NT / "shitsugi_hotei_7_05.txt", "死亡した者に係る給与等で、その死亡後に支給期の到来するものについては、本来の相続財産として、相続税の課税対象となるため、「給与所得の源泉徴収票」の「支払金額」欄に含める必要はありません。"),
    (NT / "shitsugi_hotei_7_05.txt", "なお、死亡時までに支給期の到来している給与等については、「給与所得の源泉徴収票」の「支払金額」欄に含める必要があります（この分も含め、年末調整を行います。）。"),
    (NT / "shitsugi_hotei_7_05.txt", "(注)　「支給期」とは、所得税法基本通達36－9に定めるところによります。"),
    (NT / "shitsugi_hotei_7_16.txt", "また、死亡後に支給期の到来する給与については、相続財産となり、所得税の課税対象となりませんので、「給与所得の源泉徴収票」の「支払金額」欄には、死亡前に支払が確定している給与の合計額を記載します。"),
    (TS / "pages3" / "tebikihtml_2_3_4.txt", "令和８年中に支払の確定した給与等（中途就職者について、その就職前に他の支払者が支払った給与等を通算して年末調整を行った場合には、その給与等の金額を含みます。）の総額を記載してください。この場合、源泉徴収票の作成日現在で未払のものがあるときは、その未払額を内書きしてください。"),
]


def norm(s):
    return re.sub(r"\s+", "", s)


def year_by_36_9(p):
    """所基通36−9 の読み。p: due_on（契約・慣習で定められた支給日。None＝定めなし）、paid_on（実際に支払を受けた日。None＝未払）、
    kind（regular / retro_diff〔(3) 給与規程の遡及改訂の差額〕）、retro_effective_on（(3) で支給日の定めがないときの改訂の効力が生じた日）、
    died_on（受給者の死亡日。None＝生存）、in_inheritance_base（9−17 の「相続税の課税価格計算の基礎に算入されるもの」か）。
    戻り値：(年分 or None, 理由)。"""
    if p.get("kind") == "retro_diff" and p.get("due_on") is None:
        when = p.get("retro_effective_on")
        rule = "36−9(3)：支給日の定めなし→改訂の効力が生じた日"
    elif p.get("due_on") is not None:
        when = p["due_on"]
        rule = "36−9(1)/(3)：支給日"
    else:
        when = p.get("paid_on")
        rule = "36−9(1)：支給日の定めなし→支給を受けた日"
    if when is None:
        return None, rule + "（支給を受けた日がまだない：年分が決まらない）"
    d = dt.date.fromisoformat(when)
    died = p.get("died_on")
    if died is not None and d > dt.date.fromisoformat(died):
        if p.get("in_inheritance_base") is True:
            return None, rule + "。死亡後に支給期が到来し、相続税の課税価格計算の基礎に算入される→所得税を課さない（9−17）"
        if p.get("in_inheritance_base") is None:
            return "未確定", rule + "。死亡後に支給期が到来。相続税の課税価格計算の基礎に算入されるかが入力にない（9−17 の要件）"
    return d.year, rule


def year_by_core(p):
    """現在の判定コア（packages/core/src/okura_core/situation.py の docstring と README §6）：支払日（when.on）の年。
    死亡の日以後の支払があれば、その人・年分は対象外（未対応）。未払（支払日がない）は記録にならない。"""
    if p.get("paid_on") is None:
        return None, "支払の記録がない（未払）"
    d = dt.date.fromisoformat(p["paid_on"])
    if p.get("died_on") is not None and d >= dt.date.fromisoformat(p["died_on"]):
        return "対象外", "死亡の日以後の支払→対象外（未対応）"
    return d.year, "支払日の年"


CASES = [
    ("S1 12月分を翌年1月10日に支給（規程の支給日も1月10日）", dict(due_on="2026-01-10", paid_on="2026-01-10")),
    ("S2 12月25日が支給日の給与が遅れて翌年1月5日に支払われた", dict(due_on="2025-12-25", paid_on="2026-01-05")),
    ("S3 支給日 2026-12-25 の給与が 2027年3月の時点で未払", dict(due_on="2026-12-25", paid_on=None)),
    ("S4 支給日の定めがなく 2026-12-30 に支払われた", dict(due_on=None, paid_on="2026-12-30")),
    ("S5 2026年の各月分の昇給差額。改訂で定めた支給日 2027-01-25", dict(kind="retro_diff", due_on="2027-01-25", paid_on="2027-01-25")),
    ("S6 遡及改訂の差額で支給日の定めなし。改訂の効力 2026-12-01、支払 2027-01-15", dict(kind="retro_diff", due_on=None, retro_effective_on="2026-12-01", paid_on="2027-01-15")),
    ("S7 2026-03-15 死亡、支給日 2026-03-25 の給与を遺族に支払（相続財産に算入）", dict(due_on="2026-03-25", paid_on="2026-03-25", died_on="2026-03-15", in_inheritance_base=True)),
    ("S8 2026-03-15 死亡、支給日 2026-03-25 の給与（相続財産に算入するか入力なし）", dict(due_on="2026-03-25", paid_on="2026-03-25", died_on="2026-03-15")),
    ("S9 2026-03-15 死亡、支給日 2026-02-25 の給与が死亡時に未払で、2026-03-25 に遺族に支払", dict(due_on="2026-02-25", paid_on="2026-03-25", died_on="2026-03-15")),
    ("S10 2026-03-15 死亡、支給日 2026-03-15（死亡日と同日）の給与を同日に支払", dict(due_on="2026-03-15", paid_on="2026-03-15", died_on="2026-03-15")),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    qres = []
    for path, q in QUOTES:
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        qres.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"), "quote_head": q[:40], "found": norm(q) in norm(body)})
    sres = []
    for name, p in CASES:
        a, ra = year_by_36_9(p)
        b, rb = year_by_core(p)
        sres.append({"case": name, "input": p, "by_36_9": a, "why_36_9": ra, "by_core": b, "why_core": rb, "differs": a != b})
    res = {"Q_quotes": {"ok": all(r["found"] for r in qres), "items": qres},
           "S_scenarios": {"ok": True, "differs_count": sum(r["differs"] for r in sres), "items": sres}}
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("quotes", res["Q_quotes"]["ok"], [r["quote_head"] for r in qres if not r["found"]])
    for r in sres:
        print(("≠ " if r["differs"] else "= ") + r["case"], "|", r["by_36_9"], "|", r["by_core"])


if __name__ == "__main__":
    main()
