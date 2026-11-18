"""R2X aoiro: 取得済みの条文・国税庁ページ・様式のテキストに対する検査と、仮説から導いた計算例（ネットワークは使わない）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_checks.py

入力（先に実行しておくもの）:
  scripts/R2X_aoiro_laws.py articles / revisions / suppl → scripts/results/R2X_aoiro_laws/
  scripts/R2X_aoiro_nta.py pages pages2 forms forms2     → scripts/results/R2X_aoiro_nta/
  scripts/R2X_aoiro_pdftext.py ...                        → scripts/results/R2X_aoiro_pdftext/
出力: scripts/results/R2X_aoiro_checks/
  quotes.json   … 公開資料の文書で引用した文言が、取得したテキストに（空白を除いて）そのまま含まれるか。断片は「…」で区切り、順に現れるかを見る
  articles.json … 条ごとに、時点（asof）の間で本文が同じか（ハッシュ）
  examples.json … 仮説（docs/hypotheses/20261109_round2_aoiro-model.md）の計算規則で、推測の文書の例を計算した結果
"""
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAWS = ROOT / "scripts" / "results" / "R2X_aoiro_laws"
NTA = ROOT / "scripts" / "results" / "R2X_aoiro_nta"
PDF = ROOT / "scripts" / "results" / "R2X_aoiro_pdftext"
OUT = ROOT / "scripts" / "results" / "R2X_aoiro_checks"

_TR = str.maketrans("０１２３４５６７８９（）％－−―‐，「」［］", "0123456789()%----,「」[]")


def norm(s):
    return re.sub(r"[\s　]", "", s or "").translate(_TR)


def sections(path):
    """'## Num=xx' ごとの本文（見出し行を含まない）"""
    t = path.read_text(encoding="utf-8")
    out, cur = {}, None
    for ln in t.splitlines():
        m = re.match(r"## Num=(\S+)", ln)
        if m:
            cur = m.group(1)
            out[cur] = []
            continue
        if ln.startswith("## "):
            cur = None
            continue
        if cur:
            out[cur].append(ln)
    return {k: "\n".join(v) for k, v in out.items()}


def contains_seq(text, quote):
    t, pos = norm(text), 0
    for frag in re.split(r"…+", quote):
        f = norm(frag)
        if not f:
            continue
        i = t.find(f, pos)
        if i < 0:
            return False, frag
        pos = i + len(f)
    return True, None


def law_text(short, asof, num):
    return sections(LAWS / f"{short}_{asof}.txt").get(num, "")


def nta_text(setname, key):
    p = NTA / setname / f"{key}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def pdf_text(name):
    p = PDF / f"{name}_text.tsv"
    if not p.exists():
        return ""
    rows = [ln.split("\t") for ln in p.read_text(encoding="utf-8").splitlines()[2:]]
    return "".join(r[4] for r in rows if len(r) >= 5)


R7, R8, R9 = "2025-12-31", "2026-12-31", "2027-01-01"
BOTH = (R7, R8)

# (識別子, 種類, 対象, 時点の組, 文言)
Q = [
    # 所得税法
    ("shotoku143", "law", ("shotoku", "143"), BOTH, "不動産所得、事業所得又は山林所得を生ずべき業務を行なう居住者は、納税地の所轄税務署長の承認を受けた場合には、確定申告書及び当該申告書に係る修正申告書を青色の申告書により提出することができる"),
    ("shotoku144", "law", ("shotoku", "144"), BOTH, "その年三月十五日まで（その年一月十六日以後新たに同条に規定する業務を開始した場合には、その業務を開始した日から二月以内）に、当該業務に係る所得の種類その他財務省令で定める事項を記載した申請書"),
    ("shotoku145_3", "law", ("shotoku", "145"), BOTH, "第百五十一条第一項（青色申告の取りやめ）に規定する届出書の提出をした日以後一年以内にその申請書を提出したこと"),
    ("shotoku147", "law", ("shotoku", "147"), BOTH, "承認を受けようとする年の十二月三十一日（その年十一月一日以後新たに同条に規定する業務を開始した場合には、その年の翌年二月十五日）までにその申請につき承認又は却下の処分がなかつたときは、その日においてその承認があつたものとみなす"),
    ("shotoku148_1", "law", ("shotoku", "148"), BOTH, "財務省令で定めるところにより、同条に規定する業務につき帳簿書類を備え付けてこれに不動産所得の金額、事業所得の金額及び山林所得の金額に係る取引を記録し、かつ、当該帳簿書類を保存しなければならない"),
    ("shotoku149", "law", ("shotoku", "149"), BOTH, "貸借対照表、損益計算書その他不動産所得の金額、事業所得の金額若しくは山林所得の金額又は純損失の金額の計算に関する明細書を添附しなければならない"),
    ("shotoku150_1", "law", ("shotoku", "150"), BOTH, "当該各号に掲げる年までさかのぼつて、その承認を取り消すことができる。この場合において、その取消しがあつたときは、その居住者の当該年分以後の各年分の所得税につき提出したその承認に係る青色申告書は、青色申告書以外の申告書とみなす"),
    ("shotoku151_1_R7", "law", ("shotoku", "151"), (R7,), "その年の翌年三月十五日までに、その申告をやめようとする年その他財務省令で定める事項を記載した届出書"),
    ("shotoku151_1_R8", "law", ("shotoku", "151"), (R8,), "その年分の所得税に係る確定申告期限までに、その申告をやめようとする年その他財務省令で定める事項を記載した届出書"),
    ("shotoku151_2", "law", ("shotoku", "151"), BOTH, "業務の全部を譲渡し…廃止した場合には…翌年分以後の各年分の所得税については、その承認は、その効力を失うものとする"),
    ("shotoku155_1", "law", ("shotoku", "155"), BOTH, "その居住者の帳簿書類を調査し、その調査によりこれらの金額の計算に誤りがあると認められる場合に限り、これをすることができる"),
    ("shotoku57_1", "law", ("shotoku", "57"), BOTH, "青色申告書を提出することにつき税務署長の承認を受けている居住者と生計を一にする配偶者その他の親族（年齢十五歳未満である者を除く。）で専らその居住者の営む前条に規定する事業に従事するもの…次項の書類に記載されている方法に従いその記載されている金額の範囲内において給与の支払を受けた場合には…労務の対価として相当であると認められるものは…必要経費に算入し、かつ、当該青色事業専従者の当該年分の給与所得に係る収入金額とする"),
    ("shotoku57_2", "law", ("shotoku", "57"), BOTH, "その年三月十五日まで（その年一月十六日以後新たに同項の事業を開始した場合には、その事業を開始した日から二月以内）に、青色事業専従者の氏名、その職務の内容及び給与の金額並びにその給与の支給期その他財務省令で定める事項を記載した書類"),
    ("shotoku57_7", "law", ("shotoku", "57"), BOTH, "年齢が十五歳未満であるかどうかの判定は、その年十二月三十一日（これらの規定に規定する居住者がその年の中途において死亡し又は出国をした場合には、その死亡又は出国の時）の現況による。ただし、当該親族がその当時既に死亡している場合は、当該死亡の時の現況による"),
    ("shotoku57_3", "law", ("shotoku", "57"), BOTH, "その居住者の配偶者である事業専従者　八十六万円…イに掲げる者以外の事業専従者　五十万円"),
    ("shotoku67_1", "law", ("shotoku", "67"), BOTH, "青色申告書を提出することにつき税務署長の承認を受けている居住者で不動産所得又は事業所得を生ずべき業務を行うもののうち小規模事業者として政令で定める要件に該当するもの…その年において収入した金額及び支出した費用の額とすることができる"),
    ("shotoku2_25", "law", ("shotoku", "2"), BOTH, "純損失の金額　第六十九条第一項（損益通算）に規定する損失の金額のうち同条の規定を適用してもなお控除しきれない部分の金額をいう"),
    ("shotoku2_33", "law", ("shotoku", "2"), BOTH, "同一生計配偶者　居住者の配偶者でその居住者と生計を一にするもの（第五十七条第一項（事業に専従する親族がある場合の必要経費の特例等）に規定する青色事業専従者に該当するもので同項に規定する給与の支払を受けるもの及び同条第三項に規定する事業専従者に該当するもの"),
    ("shotoku2_40", "law", ("shotoku", "2"), BOTH, "青色申告書　第百四十三条（青色申告）（第百六十六条において準用する場合を含む。）の規定により青色の申告書によつて提出する確定申告書及び確定申告書に係る修正申告書をいう"),
    ("shotoku70_1", "law", ("shotoku", "70"), BOTH, "確定申告書を提出する居住者のその年の前年以前三年内の各年（その年分の所得税につき青色申告書を提出している年に限る。）において生じた純損失の金額（この項の規定により前年以前において控除されたもの及び第百四十二条第二項（純損失の繰戻しによる還付）の規定により還付を受けるべき金額の計算の基礎となつたものを除く。）"),
    ("shotoku70_2", "law", ("shotoku", "70"), BOTH, "一　変動所得の金額の計算上生じた損失の金額…二　被災事業用資産の損失の金額"),
    ("shotoku70_4", "law", ("shotoku", "70"), BOTH, "純損失の金額が生じた年分の所得税につき確定申告書を提出し、かつ、それぞれその後において連続して確定申告書を提出している場合に限り、適用する"),
    ("shotoku123_1", "law", ("shotoku", "123"), BOTH, "その年において生じた純損失の金額がある場合"),
    ("shotoku140_1", "law", ("shotoku", "140"), BOTH, "青色申告書を提出する居住者は、その年において生じた純損失の金額がある場合には、当該申告書の提出と同時に、納税地の所轄税務署長に対し、第一号に掲げる金額から第二号に掲げる金額を控除した金額に相当する所得税の還付を請求することができる"),
    ("shotoku140_2", "law", ("shotoku", "140"), BOTH, "当該所得税の額に相当する金額を限度とする"),
    ("shotoku140_4", "law", ("shotoku", "140"), BOTH, "その年の前年分の所得税につき青色申告書を提出している場合であつて、その年分の青色申告書をその提出期限までに提出した場合（税務署長においてやむを得ない事情があると認める場合には、当該申告書をその提出期限後に提出した場合を含む。）に限り、適用する"),
    ("shotoku140_5", "law", ("shotoku", "140"), BOTH, "同日の属する年の前年分及び前前年分の所得税につき青色申告書を提出している場合に限り、同日の属する年分の所得税に係る確定申告期限までに"),
    ("shotoku142_1", "law", ("shotoku", "142"), BOTH, "その還付を受けようとする所得税の額、その計算の基礎その他財務省令で定める事項を記載した還付請求書"),
    ("shotoku232_1", "law", ("shotoku", "232"), BOTH, "（青色申告書を提出することにつき税務署長の承認を受けている者を除く。）…財務省令で定める簡易な方法により記録し"),
    # 所得税法施行令
    ("rei164_1", "law", ("shotoku-rei", "164"), BOTH, "一　法第五十七条第一項に規定する青色事業専従者の労務に従事した期間、労務の性質及びその提供の程度…二　その事業に従事する他の使用人が支払を受ける給与の状況及びその事業と同種の事業でその規模が類似するものに従事する者が支払を受ける給与の状況…三　その事業の種類及び規模並びにその収益の状況"),
    ("rei164_2", "law", ("shotoku-rei", "164"), BOTH, "当該書類に記載した事項を変更する場合には、財務省令で定めるところにより、その旨その他必要な事項を記載した書類を納税地の所轄税務署長に提出しなければならない"),
    ("rei165_1", "law", ("shotoku-rei", "165"), BOTH, "当該事業に専ら従事する期間がその年を通じて六月をこえるかどうかによる。ただし、同条第一項の場合にあつては、次の各号のいずれかに該当するときは、当該事業に従事することができると認められる期間を通じてその二分の一に相当する期間をこえる期間当該事業に専ら従事すれば足りるものとする"),
    ("rei165_2", "law", ("shotoku-rei", "165"), BOTH, "当該期間は、同項に規定する事業に専ら従事する期間に含まれないものとする…学校の学生又は生徒である者…二　他に職業を有する者（その職業に従事する時間が短い者その他当該事業に専ら従事することが妨げられないと認められる者を除く。）…三　老衰その他心身の障害により事業に従事する能力が著しく阻害されている者"),
    ("rei195_1", "law", ("shotoku-rei", "195"), BOTH, "その年の前々年分の不動産所得の金額及び事業所得の金額（法第五十七条（事業に専従する親族がある場合の必要経費の特例等）の規定を適用しないで計算した場合の金額とする。）の合計額が三百万円以下であること"),
    ("rei196_2", "law", ("shotoku-rei", "196"), BOTH, "償却費並びに法第五十一条第一項及び第四項（資産損失の必要経費算入）の規定の適用を受けるものを除き"),
    ("rei197_1", "law", ("shotoku-rei", "197"), BOTH, "その年三月十五日まで（その年一月十六日以後新たに同項に規定する業務を開始した場合には、その業務を開始した日から二月以内）に、同項の規定の適用を受けようとする旨その他財務省令で定める事項を記載した届出書"),
    ("rei197_2", "law", ("shotoku-rei", "197"), BOTH, "その年三月十五日までに、その適用を受けることをやめる旨"),
    ("rei201_1", "law", ("shotoku-rei", "201"), BOTH, "これらの年のうち最も古い年に生じた純損失の金額から順次控除する…まず法第六十九条（損益通算）の規定による控除を行つた後に法第七十条第一項又は第二項の規定による控除を行う"),
    ("rei271_1", "law", ("shotoku-rei", "271"), BOTH, "これをまず前年分の課税総所得金額から控除する"),
    ("rei272_1", "law", ("shotoku-rei", "272"), BOTH, "事業の全部の相当期間の休止又は重要部分の譲渡"),
    # 所得税法施行規則
    ("ki36_4_3", "law", ("shotoku-ki", "36_4"), BOTH, "その年一月十六日以後新たに青色事業専従者を有することとなつた場合には、その者は、その有することとなつた日から二月以内に"),
    ("ki39_2_1", "law", ("shotoku-ki", "39_2"), BOTH, "再び法第六十七条第一項（小規模事業者等の収入及び費用の帰属時期）の規定の適用を受けようとする年の一月三十一日までに"),
    ("ki40_1", "law", ("shotoku-ki", "40"), BOTH, "売掛金、買掛金、未収収益、前受収益、前払費用、未払費用その他これらに類する資産及び負債並びに棚卸資産"),
    ("ki55_R7", "law", ("shotoku-ki", "55"), BOTH, "前号の申請書を提出した後最初に青色申告書を提出しようとする年…その年一月十六日以後新たに法第百四十三条（青色申告）に規定する業務を開始した場合には、その開始した年月日"),
    ("ki56_1", "law", ("shotoku-ki", "56"), BOTH, "財務大臣の定める簡易な記録の方法及び記載事項によることができる"),
    ("ki56_2", "law", ("shotoku-ki", "56"), BOTH, "第六十条（決算）の規定による棚卸資産の棚卸を行うことを要しない"),
    ("ki57_1", "law", ("shotoku-ki", "57"), BOTH, "資産、負債及び資本に影響を及ぼす一切の取引（以下この節において「取引」という。）を正規の簿記の原則に従い、整然と、かつ、明りように記録し、その記録に基づき、貸借対照表及び損益計算書を作成しなければならない"),
    ("ki57_2", "law", ("shotoku-ki", "57"), BOTH, "そのつど区分整理し難いものは年末において、一括して区分整理することができる"),
    ("ki58_1", "law", ("shotoku-ki", "58"), BOTH, "すべての取引を借方及び貸方に仕訳する帳簿…すべての取引を勘定科目の種類別に分類して整理計算する帳簿"),
    ("ki59", "law", ("shotoku-ki", "59"), BOTH, "取引の発生順に、取引の年月日、内容、勘定科目及び金額を記載しなければならない…その勘定ごとに、記載の年月日、相手方の勘定科目及び金額を記載しなければならない"),
    ("ki60_1", "law", ("shotoku-ki", "60"), BOTH, "毎年十二月三十一日"),
    ("ki61_1", "law", ("shotoku-ki", "61"), BOTH, "財務大臣の定める科目に従い、貸借対照表及び損益計算書を作成しなければならない"),
    ("ki62", "law", ("shotoku-ki", "62"), BOTH, "その親族の労務に従事した期間、労務の性質その他その労務の事績を明らかにする事項の記載を命ずることができる"),
    ("ki63_1", "law", ("shotoku-ki", "63"), BOTH, "起算日から七年間（第三号に掲げる書類のうち、現金預金取引等関係書類に該当する書類以外のものにあつては、五年間）"),
    ("ki64", "law", ("shotoku-ki", "64"), BOTH, "納税地の所轄税務署長の承認を受け、これらの規定に規定する記載事項の一部を省略し又は変更することができる"),
    ("ki65_1", "law", ("shotoku-ki", "65"), BOTH, "一　貸借対照表及び損益計算書…三　純損失の金額の計算に関する明細書"),
    ("ki65_2", "law", ("shotoku-ki", "65"), BOTH, "第五十六条第一項ただし書（青色申告者の備え付けるべき帳簿書類）の規定の適用を受ける青色申告者は、前項の規定にかかわらず、貸借対照表を青色申告書に添付することを要しない"),
    ("ki66_R7", "law", ("shotoku-ki", "66"), (R7,), "二　青色申告書の提出の承認を受けた日又はその承認があつたものとみなされた日…三　青色申告書の提出をやめようとする理由"),
    ("ki54_1", "law", ("shotoku-ki", "54"), BOTH, "当該青色申告書がその提出期限までに提出されなかつた事情の詳細"),
    # 租税特別措置法・同施行規則
    ("sochi25_2_R7_1", "law", ("sochi", "25_2"), BOTH, "（第三項の規定の適用を受ける年分を除く。）…一　十万円…合計額"),
    ("sochi25_2_R7_3", "law", ("sochi", "25_2"), BOTH, "不動産所得又は事業所得を生ずべき事業を営むもの（所得税法第六十七条第一項の規定の適用を受ける者を除く。）…一切の取引の内容を詳細に記録している場合として財務省令で定める場合に限る…一　五十五万円"),
    ("sochi25_2_R7_4", "law", ("sochi", "25_2"), BOTH, "「五十五万円」とあるのは、「六十五万円」として…第八条第四項に規定する財務省令で定める要件を満たしている場合に限る…二　その年分の所得税の確定申告書の提出期限までに…電子情報処理組織を使用して"),
    ("sochi25_2_R7_5", "law", ("sochi", "25_2"), BOTH, "第三項の規定により控除すべき金額は、不動産所得の金額又は事業所得の金額から順次控除する"),
    ("sochi25_2_R7_6", "law", ("sochi", "25_2"), BOTH, "第三項（第四項の規定により、同項第二号に掲げる要件を満たしている者について適用する場合を除く。）の規定は、確定申告書に第三項の規定の適用を受けようとする旨及び同項の規定による控除を受ける金額の計算に関する事項の記載並びに…貸借対照表、損益計算書…の添付があり、かつ、当該確定申告書をその提出期限までに提出した場合に限り、適用する"),
    ("sochi25_2_R9_2", "law", ("sochi", "25_2"), (R9,), "前項の規定は、同項に規定する個人でその年において不動産所得又は事業所得を生ずべき事業を営むもの…が、第四項に規定する場合に該当しない場合には、適用しない…その年の前々年分の事業所得に係る総収入金額が千万円を超えること"),
    ("sochi25_2_R9_4", "law", ("sochi", "25_2"), (R9,), "一　六十五万円"),
    ("sochi25_2_R9_5", "law", ("sochi", "25_2"), (R9,), "「六十五万円」とあるのは、「七十五万円」として"),
    ("sochi25_2_R9_7", "law", ("sochi", "25_2"), (R9,), "第四項の規定は、その年分の所得税の確定申告書の提出期限までに…電子情報処理組織を使用して…送信した場合に限り、適用する"),
    ("sochiki9_6_1", "law", ("sochi-ki", "9_6"), BOTH, "所得税法施行規則第五十七条から第六十二条まで及び第六十四条の規定に定めるところにより記録し、かつ、作成している場合とする"),
    ("sochiki9_6_2", "law", ("sochi-ki", "9_6"), BOTH, "所得税法施行規則第五十八条第一項に規定する仕訳帳及び総勘定元帳とする"),
    ("sochiki9_6_3", "law", ("sochi-ki", "9_6"), BOTH, "最初の記録段階から一貫して…電子帳簿保存法施行規則第五条第五項に規定する要件を満たすものに限る"),
    ("sochiki9_6_5", "law", ("sochi-ki", "9_6"), BOTH, "電子帳簿保存法施行規則第五条第一項に規定する届出書（以下この項において「適用届出書」という。）の提出をしなければならない"),
    ("sochiki9_6_6", "law", ("sochi-ki", "9_6"), BOTH, "その年分の所得税の確定申告書の提出期限までに、同号に規定する確定申告書に記載すべき事項及び第一項の帳簿書類に基づき作成された所得税法施行規則第六十五条第一項各号に掲げる書類に記載すべき事項に係る情報"),
    ("denki5_5", "law", ("denchou-ki", "5"), BOTH, "訂正又は削除を行った場合には、これらの事実及び内容を確認することができること…通常の期間を経過した後に行った場合には、その事実を確認することができること…相互にその関連性を確認することができるようにしておくこと…取引年月日、取引金額及び取引先…範囲を指定して条件を設定することができること…二以上の任意の記録項目を組み合わせて条件を設定することができること"),
    ("denki5_1", "law", ("denchou-ki", "5"), BOTH, "あらかじめ…届出書"),
    # 国税庁（HTML）
    ("ta2072_kuroji", "nta", ("pages", "ta_2072"), None, "この合計額とは損益通算前の黒字の所得金額の合計額をいいますので、いずれかの所得に損失が生じている場合には、その損失をないものとして合計額を計算します"),
    ("ta2072_genkin", "nta", ("pages", "ta_2072"), None, "現金主義による所得計算の特例を選択している方は、55万円の青色申告特別控除を受けることはできません"),
    ("ta2072_todoke", "nta", ("pages", "ta_2072"), None, "一定の事項を記載した届出書をその年分の確定申告期限（翌年3月15日）までに提出する必要があります"),
    ("ta2072_image", "nta", ("pages", "ta_2072"), None, "確定申告書、貸借対照表、損益計算書等をイメージデータで送信することはできません"),
    ("ta2075_15", "nta", ("pages", "ta_2075"), None, "その年の12月31日現在で年齢が15歳以上であること"),
    ("ta2075_fuyou", "nta", ("pages", "ta_2075"), None, "青色申告者の事業専従者として給与の支払を受ける人または白色申告者の事業専従者である人は、同一生計配偶者や扶養親族にはなれません"),
    ("ta2075_fudosan", "nta", ("pages", "ta_2075"), None, "不動産貸付けが事業として行われている場合は適用がありますが、それ以外の場合には適用がありません"),
    ("sochitsu25_2_1", "nta", ("pages", "sochitsu_25_2"), None, "損益通算をする前のいわゆる黒字の所得金額をいうのであるから、これらの所得の金額の計算上生じた損失の金額がある場合には、その損失の金額を除外したところにより"),
    ("sochitsu25_2_3", "nta", ("pages", "sochitsu_25_2"), None, "確定申告書への記載を要件とするものではないから"),
    ("sochitsu25_2_5", "nta", ("pages", "sochitsu_25_2"), None, "措置法規則第９条の６第５項に規定する適用届出書又は同条第８項に規定する適用届出書を措置法第25条の２第７項に規定する提出期限までに提出しなければならない"),
    ("kihon144_1", "nta", ("pages", "kihon_20_01"), None, "当該被相続人についての所得税の準確定申告書の提出期限（当該期限が法第147条《青色申告書の承認があったものとみなす場合》の規定により青色申告の承認があったとみなされる日後に到来するときは、その日）までに提出して差し支えない"),
    ("kihon148_1", "nta", ("pages", "kihon_20_01"), None, "損益計算書はそれぞれの業務に係るものの区分ごとに各別に作成し、貸借対照表は全ての業務に係るものを合併して作成するものとする"),
    ("kihon150_1", "nta", ("pages", "kihon_20_01"), None, "同条第6項に規定する「やむを得ない事情がある」ものとして同条第3項に規定する事業専従者控除を認めるものとする"),
    ("kihon67_1", "nta", ("pages", "kihon_14_02"), None, "法第67条第１項の規定の適用を受けようとする年の前年末現在において確定しているところにより、また、当該前々年分の不動産所得又は事業所得のいずれかに赤字が生じている場合には、当該赤字の金額は他の黒字の金額と相殺したところにより判定するものとする"),
    ("kihon70_15", "nta", ("pages", "kihon_15_01"), None, "当該相続人の総所得金額、退職所得金額又は山林所得金額の計算上控除することができないことに留意する"),
    ("kihon140_2", "nta", ("pages", "kihon_19_02"), None, "法第120条第1項第3号《確定所得申告》に掲げる各種の税額控除後の所得税の額をいうことに留意する"),
    ("kihon140_4", "nta", ("pages", "kihon_19_02"), None, "通則法第118条第1項《国税の課税標準の端数計算等》及び第119条第1項《国税の確定金額の端数計算等》の規定を準用する"),
    ("kihon142_1", "nta", ("pages", "kihon_19_02"), None, "当該増加した部分の純損失の金額は繰戻しをすることができないものとし、当該金額については、法第70条第1項《純損失の繰越控除》の規定を適用する"),
    ("annai09_2_kigen", "nta", ("pages", "annai_09_2"), None, "適用を受けようとする年の翌年3月15日（適用を受けようとする年分に係る法定申告期限）までに提出してください"),
    ("annai12_15", "nta", ("pages", "annai_12"), None, "その年12月31日現在（専従者又は青色申告者が年の中途で死亡した場合には、それぞれ死亡当時）で年齢が15歳以上であること"),
    ("annai13_chitai", "nta", ("pages2", "annai_13"), None, "遅滞なく提出してください"),
    ("annai23200008", "nta", ("pages", "annai_23200008"), None, "青色申告を取りやめようとする年分の所得税の確定申告期限までに提出してください"),
    ("annai23200002", "nta", ("pages2", "annai_23200002"), None, "確定申告期限内に提出してください"),
    ("annai09_sozoku", "nta", ("pages", "annai_09"), None, "その死亡の日がその年の1月1日から8月31日までの場合・・・死亡の日から4か月以内"),
    ("ta2070_kanni", "nta", ("pages", "ta_2070"), None, "年末に貸借対照表と損益計算書を作成することができるような正規の簿記によることが原則ですが、現金出納帳、売掛帳、買掛帳、経費帳、固定資産台帳のような帳簿を備え付けて簡易な記帳をするだけでもよいことになっています"),
    ("ta2070_hozon", "nta", ("pages", "ta_2070"), None, "原則として7年間保存することとされていますが、書類によっては5年間でよいものもあります"),
    ("ta2070_fuyou", "nta", ("pages", "ta_2070"), None, "青色事業専従者として給与の支払を受ける方は、同一生計配偶者や扶養親族にはなれません"),
    ("ta2070_kashidaore", "nta", ("pages", "ta_2070"), None, "年末における貸金の帳簿価額の合計額の5.5パーセント以下の金額を貸倒引当金勘定へ繰り入れたときは、その金額を必要経費として認める"),
    ("ta2070_sozoku", "nta", ("pages", "ta_2070"), None, "被相続人が青色申告者の場合(死亡の日がその年の9月1日から10月31日)…その年12月31日…被相続人が青色申告者の場合(死亡の日がその年の11月1日から12月31日)…翌年2月15日"),
    ("ta2070_kurimodoshi", "nta", ("pages", "ta_2070"), None, "前年も青色申告をしている場合は、純損失の繰越しに代えて、その損失額を生じた年の前年分の所得金額に繰り戻して控除し、前年分の所得税額の還付を受けることもできます"),
    ("kihon67_5", "nta", ("pages", "kihon_14_02"), None, "当該被相続人についての所得税の準確定申告書の提出期限"),
    ("kihon70_13", "nta", ("pages", "kihon_15_01"), None, "更正の請求に基づく更正により新たに純損失の金額があることとなった場合も含まれることに留意する"),
    ("kihon140_3", "nta", ("pages", "kihon_19_02"), None, "同時に提出されたかったことについて税務署長においてやむを得ない事情があると認めるときは、これを同時に提出されたものとして"),
    ("ki_suppl_r5_12_2", "file", ("R2X_aoiro_laws/shotoku-ki_suppl_36_4_55_66.txt",), None, "新規則」という。）第三十六条の四第一項の規定は、令和九年分以後の所得税について適用し、令和八年分以前の所得税については、なお従前の例による"),
    ("ki_suppl_r5_12_5", "file", ("R2X_aoiro_laws/shotoku-ki_suppl_36_4_55_66.txt",), None, "新規則第五十五条（所得税法施行規則第六十七条において準用する場合を含む。）の規定は、令和九年分以後の所得税につき所得税法第百四十三条（同法第百六十六条において準用する場合を含む。以下この条において同じ。）の承認を受けようとする場合について適用し"),
    ("ki_suppl_r5_12_6", "file", ("R2X_aoiro_laws/shotoku-ki_suppl_36_4_55_66.txt",), None, "新規則第六十六条（所得税法施行規則第六十七条において準用する場合を含む。）の規定は、令和八年分以後の所得税につき青色申告書の提出をやめようとする場合について適用し"),
    ("ki_suppl_r5_12_1", "file", ("R2X_aoiro_laws/shotoku-ki_suppl_36_4_55_66.txt",), None, "四　第六十六条の改正規定及び第九十八条の改正規定並びに附則第六条及び第十三条の規定　令和八年一月一日…五　第三十六条の四第一項の改正規定、第五十五条の改正規定"),
    ("sochi_rev_r7_4_1_ro", "file", ("R2X_aoiro_laws/sochi_25_2_by_revision.txt",), None, "# law_revision_id=332AC0000000026_20270101_507AC0000000013…（次に掲げる場合のいずれかに該当する場合に限る。）…ロ　次に掲げる要件の全てを満たす場合"),
    ("sochiki_r7_26_1_6", "file", ("R2X_aoiro_laws/sochi-ki_2027-01-01.txt",), None, "六　第一条中租税特別措置法施行規則第九条の六の改正規定、同令第十八条の二十四第一項の改正規定及び同令第三十七条の四の十二第二項を同条第三項とし、同条第一項の次に一項を加える改正規定　令和九年一月一日"),
    # 国税庁（PDF の文字）
    ("kessan_formid", "pdf", ("kessan_ippan_r07",), None, "NTA0KOA210010110"),
    ("kessan_p1", "pdf", ("kessan_ippan_r07",), None, "青色申告特別控除前の所得金額"),
    ("kessan_p2_senju", "pdf", ("kessan_ippan_r07",), None, "専従者給与の内訳"),
    ("kessan_p2_koujo", "pdf", ("kessan_ippan_r07",), None, "青色申告特別控除額の計算"),
    ("kessan_p4_bs", "pdf", ("kessan_ippan_r07",), None, "貸借対照表"),
    ("kessan_genkin_formid", "pdf", ("kessan_genkin_r07",), None, "NTA0KOA230010090"),
    ("todoke65_ki_atode", "pdf", ("todoke_65man_ki",), None, "本規定の適用を受けようとする年分に係る法定申告期限（翌年の３月15日）までに、この届出書を提出した場合には、あらかじめ、届出書を提出したものと取り扱います"),
    ("kurimodoshi_ki_kigen", "pdf", ("kanpu_kurimodoshi_ki",), None, "繰戻しを行う純損失の金額が生じた年分の確定申告書とともに確定申告期限までに提出してください"),
    ("kurimodoshi_ki_fukko", "pdf", ("kanpu_kurimodoshi_ki",), None, "復興特別所得税の還付の請求はできません"),
]


def run_quotes():
    res = []
    for qid, kind, tgt, asofs, quote in Q:
        if kind == "law":
            for asof in asofs:
                ok, miss = contains_seq(law_text(tgt[0], asof, tgt[1]), quote)
                res.append({"id": qid, "target": f"{tgt[0]}@{asof} Num={tgt[1]}", "ok": ok, "missing_fragment": miss})
        elif kind == "nta":
            ok, miss = contains_seq(nta_text(*tgt), quote)
            res.append({"id": qid, "target": f"nta/{tgt[0]}/{tgt[1]}", "ok": ok, "missing_fragment": miss})
        elif kind == "file":
            p = ROOT / "scripts" / "results" / tgt[0]
            ok, miss = contains_seq(p.read_text(encoding="utf-8") if p.exists() else "", quote)
            res.append({"id": qid, "target": f"results/{tgt[0]}", "ok": ok, "missing_fragment": miss})
        else:
            ok, miss = contains_seq(pdf_text(tgt[0]), quote)
            res.append({"id": qid, "target": f"pdf/{tgt[0]}", "ok": ok, "missing_fragment": miss})
    return res


def run_articles():
    out = {}
    for short in ("shotoku", "shotoku-rei", "shotoku-ki", "sochi", "sochi-ki", "denchou", "denchou-ki"):
        secs = {a: sections(LAWS / f"{short}_{a}.txt") for a in (R7, R8, R9)}
        for num in secs[R7]:
            h = {a: hashlib.sha256(norm(secs[a].get(num, "")).encode()).hexdigest()[:12] for a in (R7, R8, R9)}
            out[f"{short}:{num}"] = {"R7==R8": h[R7] == h[R8], "R8==R9": h[R8] == h[R9], "hash": h}
    return out


# ---------------------------------------------------------------- 計算例（仮説 H の規則をそのまま書いたもの）
def aoiro_tokubetsu_r7r8(fudosan, jigyo, sanrin, *, jigyo_teki_fudosan, seiki_boki, kigennai, genkin_shugi, etax, yuryo_denshi):
    """令和7年分・令和8年分（措法25の2、2025-12-31・2026-12-31 の版）。
    fudosan/jigyo/sanrin は青色申告特別控除前の各所得の金額（赤字は負）。返り値：(控除額, 内訳{所得: 控除額}, 適用した項)。
    - 55万/65万の対象：「事業を営む」（事業所得があるか、不動産が事業的規模）かつ 現金主義でなく 正規の簿記。
      上限＝不動産所得と事業所得の黒字の合計（山林は入らない）。不動産→事業の順に黒字から控除。
      65万：（優良な電子帳簿＋届出）又は（期限内に e-Tax）。55万：書面で期限内提出＋添付（措法25の2⑥）。
    - 上に当たらなければ 10万：不動産・事業・山林の黒字の合計が上限。不動産→事業→山林の順。"""
    eigyo = jigyo is not None or jigyo_teki_fudosan
    kuro = {k: max(v or 0, 0) for k, v in (("fudosan", fudosan), ("jigyo", jigyo), ("sanrin", sanrin))}
    cap3 = None
    if eigyo and seiki_boki and not genkin_shugi:
        if etax:                      # ④二（⑥の記載・添付・期限内の要件は除かれる）
            cap3 = 650_000
        elif yuryo_denshi and kigennai:   # ④一 ＋ ⑥
            cap3 = 650_000
        elif kigennai:                # ③ ＋ ⑥
            cap3 = 550_000
    if cap3 is not None:
        limit = min(cap3, kuro["fudosan"] + kuro["jigyo"])
        order, applied = ("fudosan", "jigyo"), "措法25の2③（④）"
    else:
        limit = min(100_000, kuro["fudosan"] + kuro["jigyo"] + kuro["sanrin"])
        order, applied = ("fudosan", "jigyo", "sanrin"), "措法25の2①"
    rest, br = limit, {}
    for k in order:
        d = min(rest, kuro[k])
        br[k] = d
        rest -= d
    return limit, br, applied


def aoiro_tokubetsu_r9(fudosan, jigyo, sanrin, *, jigyo_teki_fudosan, seiki_boki, genkin_shugi, etax_kigennai, yuryo_or_dentori,
                       zenzen_fudosan_shunyu, zenzen_jigyo_shunyu):
    """令和9年分以後（措法25の2、2027-01-01 の版）の読み（仮説 H5）。
    ④ 65万：事業を営む・現金主義でない・正規の簿記（④の「場合」）＋ ⑦ 期限内の e-Tax。⑤ 75万：④＋電子帳簿（優良 又は 電子取引の要件）。
    ① 10万：④の適用がない年分。ただし ② 前々年の総収入金額が1,000万円超の事業を営み、④の「場合」（正規の簿記の記録）に当たらない者には適用しない。"""
    eigyo = jigyo is not None or jigyo_teki_fudosan
    kuro = {k: max(v or 0, 0) for k, v in (("fudosan", fudosan), ("jigyo", jigyo), ("sanrin", sanrin))}
    case4 = eigyo and seiki_boki and not genkin_shugi       # ④に規定する場合
    if case4 and etax_kigennai:
        cap = 750_000 if yuryo_or_dentori else 650_000
        return min(cap, kuro["fudosan"] + kuro["jigyo"]), "措法25の2④（⑤）＋⑦"
    over = (jigyo is not None and zenzen_jigyo_shunyu > 10_000_000) or (jigyo_teki_fudosan and zenzen_fudosan_shunyu > 10_000_000)
    if over and not genkin_shugi and not case4:
        return 0, "措法25の2②（①を適用しない）"
    return min(100_000, kuro["fudosan"] + kuro["jigyo"] + kuro["sanrin"]), "措法25の2①"


RATES = [(1_950_000, 5), (3_300_000, 10), (6_950_000, 20), (9_000_000, 23), (18_000_000, 33), (40_000_000, 40), (None, 45)]


def tax_89(kazei):
    """所法89①の超過累進（課税総所得金額は1,000円未満切捨て済みとして渡す）。端数は1円未満切捨て（整数演算）。"""
    t, lo = 0, 0
    for hi, r in RATES:
        top = kazei if hi is None else min(kazei, hi)
        if top > lo:
            t += (top - lo) * r // 100
        if hi is None or kazei <= hi:
            break
        lo = hi
    return t


def floor_to(x, unit):
    return x // unit * unit


def kurimodoshi(prev_kazei_sougou, loss_to_carry_back, prev_tax_after_credits):
    """所法140①②・所令271①一（総所得の損失だけの単純な場合）。課税標準は1,000円未満、税額の計は100円未満を切捨て（所基通140・141−4、請求書の⑬・㉑の欄）。"""
    a = floor_to(tax_89(floor_to(prev_kazei_sougou, 1000)), 100)
    after = max(prev_kazei_sougou - loss_to_carry_back, 0)
    b = floor_to(tax_89(floor_to(after, 1000)), 100)
    return min(a - b, prev_tax_after_credits), a, b


def kurikoshi(losses, incomes):
    """所法70①・所令201①一：古い年の純損失から順に、各年の総所得金額（損益通算後）から控除。3年で消える。
    losses: {年: 純損失}（青色の年だけ）、incomes: {年: 繰越控除前の総所得金額}。連続して申告していることを前提にする。"""
    pool = dict(losses)
    log = {}
    for y in sorted(incomes):
        inc = incomes[y]
        used = []
        for ly in sorted(pool):
            if not (y - 3 <= ly <= y - 1) or pool[ly] <= 0 or inc <= 0:
                continue
            d = min(pool[ly], inc)
            pool[ly] -= d
            inc -= d
            used.append((ly, d))
        log[y] = {"控除": used, "控除後の総所得金額": inc}
        for ly in list(pool):
            if ly <= y - 3:
                pool[ly] = 0  # y の年分が最後（前年以前三年内）。翌年以後は控除できない
    return log, pool


def senju_age_ok(birth, year, death=None):
    """所法57⑦：その年12月31日（居住者の死亡・出国の時、親族が先に死亡していればその時）の現況で15歳未満でないか。
    年齢は「年齢計算ニ関スル法律」により誕生日の前日に1つ加わる（R4 の既存調査）。ここでは日付の比較で近似：
    基準日 >= 誕生日の前日の15年後 なら15歳以上。"""
    import datetime as dt
    ref = death or dt.date(year, 12, 31)
    b = birth
    try:
        b15 = b.replace(year=b.year + 15)
    except ValueError:  # 2月29日生まれ
        b15 = dt.date(b.year + 15, 3, 1)
    return ref >= b15 - dt.timedelta(days=1)


def run_examples():
    import datetime as dt
    ex = {}
    base = dict(jigyo_teki_fudosan=False, seiki_boki=True, kigennai=True, genkin_shugi=False, etax=True, yuryo_denshi=False)
    ex["T1_事業300万_e-Tax"] = aoiro_tokubetsu_r7r8(None, 3_000_000, None, **base)
    ex["T2_事業40万_e-Tax"] = aoiro_tokubetsu_r7r8(None, 400_000, None, **base)
    ex["T3_事業200万_不動産(事業的)▲50万_e-Tax"] = aoiro_tokubetsu_r7r8(-500_000, 2_000_000, None, **{**base, "jigyo_teki_fudosan": True})
    ex["T4_事業300万_書面_期限内"] = aoiro_tokubetsu_r7r8(None, 3_000_000, None, **{**base, "etax": False})
    ex["T5_事業300万_書面_期限後"] = aoiro_tokubetsu_r7r8(None, 3_000_000, None, **{**base, "etax": False, "kigennai": False})
    ex["T6_事業300万_簡易簿記"] = aoiro_tokubetsu_r7r8(None, 3_000_000, None, **{**base, "seiki_boki": False})
    ex["T7_事業300万_現金主義"] = aoiro_tokubetsu_r7r8(None, 3_000_000, None, **{**base, "genkin_shugi": True})
    ex["T8_不動産(事業的規模でない)80万のみ_e-Tax"] = aoiro_tokubetsu_r7r8(800_000, None, None, **base)
    ex["T9_不動産(非事業)30万＋事業20万_e-Tax"] = aoiro_tokubetsu_r7r8(300_000, 200_000, None, **base)
    ex["T10_事業▲100万のみ"] = aoiro_tokubetsu_r7r8(None, -1_000_000, None, **base)
    ex["T11_事業300万_電子保存が年の途中から(優良に当たらない)_書面_期限内"] = aoiro_tokubetsu_r7r8(None, 3_000_000, None, **{**base, "etax": False, "yuryo_denshi": False})
    ex["T12_事業300万_優良な電子帳簿＋届出_書面_期限内"] = aoiro_tokubetsu_r7r8(None, 3_000_000, None, **{**base, "etax": False, "yuryo_denshi": True})
    r9 = dict(jigyo_teki_fudosan=False, genkin_shugi=False, zenzen_fudosan_shunyu=0)
    ex["R9_1_前々年収入1,200万_簡易簿記"] = aoiro_tokubetsu_r9(None, 3_000_000, None, seiki_boki=False, etax_kigennai=True, yuryo_or_dentori=False,
                                                     zenzen_jigyo_shunyu=12_000_000, **r9)
    ex["R9_2_前々年収入1,200万_正規簿記_書面"] = aoiro_tokubetsu_r9(None, 3_000_000, None, seiki_boki=True, etax_kigennai=False, yuryo_or_dentori=False,
                                                       zenzen_jigyo_shunyu=12_000_000, **r9)
    ex["R9_3_前々年収入900万_簡易簿記"] = aoiro_tokubetsu_r9(None, 3_000_000, None, seiki_boki=False, etax_kigennai=True, yuryo_or_dentori=False,
                                                   zenzen_jigyo_shunyu=9_000_000, **r9)
    ex["R9_4_正規簿記_e-Tax"] = aoiro_tokubetsu_r9(None, 3_000_000, None, seiki_boki=True, etax_kigennai=True, yuryo_or_dentori=False,
                                              zenzen_jigyo_shunyu=0, **r9)
    ex["R9_6_正規簿記_書面_期限内"] = aoiro_tokubetsu_r9(None, 3_000_000, None, seiki_boki=True, etax_kigennai=False, yuryo_or_dentori=False,
                                              zenzen_jigyo_shunyu=0, **r9)
    ex["R9_5_正規簿記_e-Tax_優良"] = aoiro_tokubetsu_r9(None, 3_000_000, None, seiki_boki=True, etax_kigennai=True, yuryo_or_dentori=True,
                                                 zenzen_jigyo_shunyu=0, **r9)
    # 繰戻し還付（前年の課税総所得金額 300万円、本年の純損失 100万円を全部繰り戻す、前年の税額控除後の所得税は十分にある）
    ex["K1_繰戻し_前年課税300万_損失100万"] = kurimodoshi(3_000_000, 1_000_000, 10**9)
    ex["K2_繰戻し_前年課税150万_損失300万"] = kurimodoshi(1_500_000, 3_000_000, 10**9)
    ex["K3_繰戻し_限度（前年の税額控除後の税額 5万円）"] = kurimodoshi(3_000_000, 1_000_000, 50_000)
    # 繰越控除
    ex["C1_繰越_2025損失100万_2026所得60万_2027所得60万"] = kurikoshi({2025: 1_000_000}, {2026: 600_000, 2027: 600_000})
    ex["C2_繰越_2025損失100万_2026所得0_2027所得0_2028所得20万_2029所得200万"] = kurikoshi({2025: 1_000_000}, {2026: 0, 2027: 0, 2028: 200_000, 2029: 2_000_000})
    ex["C3_繰越_古い年から_2025損失50万_2026損失50万_2027所得70万"] = kurikoshi({2025: 500_000, 2026: 500_000}, {2027: 700_000})
    # 専従者の年齢
    ex["S1_2010-12-31生_2025年"] = senju_age_ok(dt.date(2010, 12, 31), 2025)
    ex["S2_2011-01-01生_2025年"] = senju_age_ok(dt.date(2011, 1, 1), 2025)
    ex["S3_2011-01-02生_2025年"] = senju_age_ok(dt.date(2011, 1, 2), 2025)
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in ex.items()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    q = run_quotes()
    (OUT / "quotes.json").write_text(json.dumps({"total": len(q), "ok": sum(r["ok"] for r in q), "ng": [r for r in q if not r["ok"]], "all": q},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    a = run_articles()
    (OUT / "articles.json").write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    e = run_examples()
    (OUT / "examples.json").write_text(json.dumps(e, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("quotes", sum(r["ok"] for r in q), "/", len(q))
    for r in q:
        if not r["ok"]:
            print("  NG", r["id"], r["target"], "missing:", r["missing_fragment"])
    print("articles R7!=R8:", [k for k, v in a.items() if not v["R7==R8"]])
    print("articles R8!=R9:", [k for k, v in a.items() if not v["R8==R9"]])
    print(json.dumps(e, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
