"""規則モジュール income_kinds の根拠：パラメータでない規則（入力の組み立てで当てる規則の根拠。RULES）。

パラメータ（基準額・率）の根拠は evaluate がトレースから足す。ここは、中間表現の記録をどの所得・どの年分に数えるか、
何を非課税として数えないか、のような「入力の段の規則」の根拠だけを書く。
"""

from __future__ import annotations

from collections.abc import Mapping

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from .calc import DEPRECIATION_CEIL, PENSION_FLOOR

NENKIN = "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md"
TAISHOKU = "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md"
JIGYO = "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md"
AOIRO = "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md"
KABU = "docs/public-sources/20261109_round2b_kabu-law-and-nta.md"
KIFU = "docs/public-sources/20261109_round2_hoken-kifu-nta-soumu.md"
FUDOSAN = "docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md"
GENKA = "docs/public-sources/20261109_round2_genka-laws-and-nta.md"
GENKA3 = "docs/public-sources/20261111_impl-research3_genka-laws.md"
HAITO = "docs/public-sources/20261111_impl-research_haito-laws-and-nta.md"
GENSEN = "docs/public-sources/20261111_impl-research_gensen-laws-and-nta.md"
INVOICE = "docs/public-sources/20261109_round2b_invoice-laws-and-nta.md"

PENSION_SCOPE = BasisEntry(
    type=BasisType.RULE,
    name="公的年金等の収入金額に数える年金：国民年金・厚生年金の老齢の年金、共済組合の退職年金（老齢）。障害・遺族の年金は非課税で数えない",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第35条第3項第1号・第31条第1号（公的年金等）、国民年金法第25条・厚生年金保険法第41条第2項（老齢の給付のほかは公課の禁止）、"
        "国家公務員共済組合法第49条・地方公務員等共済組合法第52条・私立学校教職員共済法第5条（障害の給付は公課の禁止）、"
        "所得税法第9条第1項第3号ロ（遺族の受ける年金）"
    ),
    references=(f"{NENKIN}#1.1", f"{NENKIN}#4.1", f"{NENKIN}#4.2"),
)

PENSION_KINDS = BasisEntry(
    type=BasisType.RULE,
    name="企業年金の老齢の年金は加入者の負担分を控除した額を公的年金等の収入金額に、生命保険契約等の年金・公的な制度でない外国の年金はその他の雑所得（収入金額−本人の負担分）に数え、企業年金の遺族の給付・共済組合の遺族年金は非課税で数えない",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第35条第3項第3号・所得税法施行令第82条の2第2項（企業年金）、第35条第2項第2号（その他の雑所得）、第9条第1項第3号ロ。"
        "外国の制度は所令82の2②一・72③九。遺族年金は TA No.1605（国税庁の説明）"
    ),
    references=(f"{NENKIN}#1.1", f"{NENKIN}#1.2", f"{NENKIN}#4.2", f"{NENKIN}#4.3"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "加入者の負担分・必要経費は判断.年金の性質（額が判断にないものは対象外）。共済組合の遺族年金は TA1605 の「原則として」課税されないに従う（名称に公務・職務があるものは対象外）"},
)

PENSION_YEAR = BasisEntry(
    type=BasisType.RULE,
    name="公的年金等は、法令等により定められた支給日（statutory_payment_on。なければ支払日 when.on）の年分の収入金額に数える",
    source_kind=SourceKind.CIRCULAR,
    law="所得税基本通達36−14(1)イ（所得税法第36条第1項「その年において収入すべき金額」）",
    references=(f"{NENKIN}#3",),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "statutory_payment_on がない記録は支払日を支給日と読む（法令の読み）"},
)

WINDFALL_SCOPE = BasisEntry(
    type=BasisType.RULE,
    name="一時所得の総収入金額に数えるのは、業務に関して受けるものでない懸賞の賞金品（windfall_receipt の reason=prize・business_related=false）。支出した金額は direct_expense_ids の支出の額",
    source_kind=SourceKind.LAW,
    law="所得税法第34条第1項・第2項、所得税基本通達34−1(1)（懸賞の賞金品。業務に関して受けるものを除く）",
    references=(f"{JIGYO}#6",),
)

WINDFALL_GIFT = BasisEntry(
    type=BasisType.RULE,
    name="寄附の返礼品の経済的利益（donation の return_gift_value）を、寄附の日（when.on）の年分の一時所得の総収入金額に数える",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="質疑応答事例 02/37（所得税法第34条・第36条第1項、所得税基本通達34−1(5)）。価額の見積りと収入すべき時期の定めは docs にない",
    references=(f"{KIFU}#3.5",),
    flags=(ReadingFlag.LEGAL_READING,),
)

WINDFALL_YEAR = BasisEntry(
    type=BasisType.RULE,
    name="一時所得の受取は、受取日（when.on）の年分の総収入金額に数える",
    source_kind=SourceKind.LAW,
    law="所得税法第36条第1項（「その年において収入すべき金額」）。一時所得の収入すべき時期の通達は docs に未取得",
    references=(f"{NENKIN}#3",),
    flags=(ReadingFlag.LEGAL_READING, ReadingFlag.ORIGINAL_UNVERIFIED),
)

RETIRE_YEAR = BasisEntry(
    type=BasisType.RULE,
    name="退職手当等の年分：退職の日（retired_on。なければ支払日）。役員の決議を要するもの（resolution_on）は決議の日、一の勤務先の退職で2以上の支払があれば最初の支払の日の年",
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法第30条第2項・第36条第1項、所得税法施行令第77条、所得税基本通達36−10 の本文、タックスアンサー No.2728（決議の日。金額が具体的に定められた日の語彙はないので決議の日と読む。確定拠出年金の一時金の例外は見ない）",
    references=(f"{TAISHOKU}#1.2", "docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md#2.1"),
    flags=(ReadingFlag.LEGAL_READING,),
)

RETIRE_YEARS = BasisEntry(
    type=BasisType.RULE,
    name=(
        "勤続年数：退職の申告書の勤務期間（就職日〜退職日）を暦に従って年・月・日で数え、1年未満の端数は1年とする。その年に2以上の支払者があれば、"
        "最も長い期間にそれと重複しない期間を加算する"
    ),
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法施行令第69条第1項第1号・第3号・第2項、所得税基本通達30−13（暦に従って計算し、1月に満たない期間は日をもって数え…）",
    references=(f"{TAISHOKU}#2.2",),
)

RETIRE_PRIOR = BasisEntry(
    type=BasisType.RULE,
    name=(
        "前の退職手当等：前年以前4年内（5年〜19年内は確定拠出年金の老齢給付金の一時金の有無で決まり、分かれれば未確定）に支払を受けた退職手当等の勤続期間"
        "（収入金額が退職所得控除額に満たなければ所令70②の期間）と重複する期間の年数（1年未満切捨て）。その年数の③の額を退職所得控除額から控除する"
    ),
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法第30条第6項第1号、所得税法施行令第70条第1項第2号・第2項・第3項（令和8年分は令和7年政令第120号の改正後の第2号イ〜ハ）",
    references=(f"{TAISHOKU}#2.3",),
)

RETIRE_MULTI = BasisEntry(
    type=BasisType.RULE,
    name=(
        "その年中に一般・短期・特定役員の退職手当等のうち二以上がある場合：区分ごとの勤続期間と重複期間（1年未満は1年）から短期・特定役員退職所得控除額を計算し、"
        "前の退職手当等と重複する短期・特定役員の期間の分を控除する"
    ),
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法第30条第7項、所得税法施行令第71条の2第1項〜第12項",
    references=(f"{TAISHOKU}#2.4",),
)

RETIRE_KIND = BasisEntry(
    type=BasisType.RULE,
    name=(
        "退職手当等の区分（支払者ごと）：勤務期間の全部が役員等の期間で5年以下なら特定役員退職手当等、役員等勤続年数が5年を超えれば特定役員退職手当等でなく、"
        "短期勤続年数（役員等勤続期間を含めて数える）が5年以下なら短期退職手当等、それ以外は一般"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第30条第4項・第5項、所得税法施行令第69条の2（5年以下の役員等勤続期間とそれ以外の期間が混ざる退職手当等〔所令71の2⑬〕は、"
        "相当と認められる一般・短期の部分の額の語彙がなく対象外）"
    ),
    references=(f"{TAISHOKU}#2.1", f"{TAISHOKU}#2.2", f"{TAISHOKU}#2.4"),
)

RETIRE_NATURE = BasisEntry(
    type=BasisType.RULE,
    name="退職手当等の支払の記録（retirement_payment）は退職手当等として扱い、障害者になったことに直接基因する退職かは判断.退職の性質で決める（未入力なら両方で評価）",
    source_kind=SourceKind.LAW,
    law="所得税法第30条第1項・第6項第3号、所得税法施行令第71条",
    references=(f"{TAISHOKU}#1.1", f"{TAISHOKU}#2.4"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "記録の種類（退職手当等の支払）を退職手当等に当たると読む。判断.退職の性質の is_retirement_allowance=false なら対象外"},
)

BUSINESS_REVENUE = BasisEntry(
    type=BasisType.RULE,
    name="業務の売上・報酬（business_receipt の amount。源泉徴収の前の額と読む）を、発生日（incurred_on。なければ受取日）の年分の総収入金額に数え、判断.事業と称するに至る程度で事業所得か業務に係る雑所得かに分ける",
    source_kind=SourceKind.LAW,
    law="所得税法第27条第2項・第35条第2項第2号・第36条第1項（その年において収入すべき金額）",
    references=(f"{JIGYO}#1.1", f"{JIGYO}#4.2"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "incurred_on がない記録は受取日を収入すべき日と読む。amount は報酬の額（源泉徴収税額を差し引く前）と読む（中間表現の欄の読み）"},
)

BUSINESS_EXPENSE = BasisEntry(
    type=BasisType.RULE,
    name="業務の支出（business_expense・payroll_paid の wages・professional_fee）を、その業務の必要経費に数える。判断.業務関連性が未入力の支出は人ごとに全部 true・全部 false の両端で評価する（D21 R6）。false なら数えず、家事関連費の按分の判断があれば明らかに区分できる業務の部分だけを数える",
    source_kind=SourceKind.LAW,
    law="所得税法第37条第1項・第45条第1項第1号、所得税法施行令第96条、所得税基本通達45−2",
    references=(f"{JIGYO}#1.1", f"{JIGYO}#1.2"),
)

HOME_WORKER = BasisEntry(
    type=BasisType.RULE,
    name="家内労働者等に当たるかは判断.家内労働者等（未入力なら両方で評価）",
    source_kind=SourceKind.LAW,
    law="租税特別措置法第27条、同施行令第18条の2第1項",
    references=(f"{JIGYO}#2.1", f"{JIGYO}#2.5"),
)

HOME_WORKER_SALARY = BasisEntry(
    type=BasisType.RULE,
    name=(
        "給与所得を有する家内労働者等の特例の額は、特例の額から給与所得控除額（給与等の収入金額を限度）を差し引いた額"
        "（国税庁の計算書の④は「給与所得の収入金額」。令和7年分は所得税法第28条第3項第1号の文言〔65万円〕と食い違い、公式の説明の読みによる）"
    ),
    source_kind=SourceKind.NTA_EXPLANATION,
    law="租税特別措置法第27条第1項、同施行令第18条の2第2項、国税庁「家内労働者等の事業所得等の所得計算の特例」の計算書・書き方",
    references=(f"{JIGYO}#2.1", f"{JIGYO}#2.3", f"{JIGYO}#2.4"),
    flags=(ReadingFlag.LEGAL_READING,),
)

HOME_WORKER_DEFICIT = BasisEntry(
    type=BasisType.RULE,
    name=(
        "家内労働者等の特例で事業所得と業務に係る雑所得の両方があり、事業所得の実額の必要経費が総収入金額を超え、雑所得の総収入金額が"
        "特例の額から事業所得の必要経費を引いた額を超えるときは、事業所得の必要経費は実額（計算書の⑧）、雑所得は特例の額から事業所得の必要経費を引いた額（⑨）"
    ),
    source_kind=SourceKind.GUIDE_OR_FORM_NOTE,
    law="租税特別措置法第27条第1項、同施行令第18条の2第2項第2号、国税庁「家内労働者等の事業所得等の所得計算の特例」の計算書",
    references=(f"{JIGYO}#2.3", f"{JIGYO}#2.4"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": (
        "措法27 後段（総収入金額を限度）・措令18の2②二の文言では事業所得の必要経費は総収入金額までになり、計算書と食い違う。公式の説明（計算書）があり"
        "反対の一次情報がないので計算書の読み（D22 S1）。書き方は事業所得が赤字の人に税務署に尋ねるよう書いている"
    )},
)

BLUE_STATE = BasisEntry(
    type=BasisType.RULE,
    name="青色申告の承認：承認の通知、期限内の申請でみなし承認の期日までに却下がないもの（所法147）から、取消し・取りやめ・業務の廃止までの年分",
    source_kind=SourceKind.LAW,
    law="所得税法第143条〜第147条・第150条・第151条",
    references=(f"{AOIRO}#1.2", f"{AOIRO}#1.4", f"{AOIRO}#1.5", f"{AOIRO}#1.6"),
)

BOOKKEEPING = BasisEntry(
    type=BasisType.RULE,
    name="正規の簿記の要件は判断.正規の簿記の宣言（未入力なら両方で評価。帳簿の方式が簡易帳簿なら満たさない）",
    source_kind=SourceKind.MINISTERIAL_ORDINANCE,
    law="租税特別措置法第25条の2第3項、同施行規則第9条の6第1項（所得税法施行規則第57条〜第62条・第64条）",
    references=(f"{AOIRO}#3.1",),
)

FILING_PLAN = BasisEntry(
    type=BasisType.RULE,
    name="青色申告特別控除の申告の要件は計画.申告の方法と時期（期限内・控除の記載と書類の添付・e-Tax。未入力なら3つの場合で評価）",
    source_kind=SourceKind.LAW,
    law="租税特別措置法第25条の2第4項第2号・第6項",
    references=(f"{AOIRO}#3.1", f"{AOIRO}#3.2"),
)

DIVIDEND_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "上場株式等の配当等（一般の口座・源泉徴収選択口座の年間取引報告書）を、選択.株式等の申告（未入力なら申告不要・総合課税・申告分離課税の3つで評価。"
        "subject.record_id のある選択はその1回の支払にだけ当てる：措法8の5④）で分け、申告不要は合計所得金額に入れない。NISA の配当は非課税で数えない。"
        "大口株主等（判断.大口株主等。未入力なら両端で評価）と非上場株式の配当は総合課税で、内国法人からの少額配当（10万円×配当計算期間の月数/12 以下）は申告不要を選べる"
        "（月数の語彙がなく、月数で分かれれば未確定）"
    ),
    source_kind=SourceKind.LAW,
    law="所得税法第24条、租税特別措置法第8条の4第1項〜第3項・第8条の5第1項第4項・第9条の8",
    references=(f"{KABU}#1.1", f"{KABU}#1.2", f"{KABU}#2.1", f"{KABU}#2.2", f"{KABU}#7"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "申告不要を選んだ配当を合計所得金額に入れないのは国税庁の説明（kabu §2.2）。源泉徴収選択口座の配当は年間取引報告書の金額を口座ごとに選ぶ（措法37の11の6⑨）"},
)

STOCK_SALE_RULE = BasisEntry(
    type=BasisType.RULE,
    name="上場株式等の譲渡：一般の口座の譲渡（譲渡の対価−取得価額−譲渡の費用）と特定口座の年間の損益を合計する。源泉徴収選択口座は選択.株式等の申告（未入力なら両方で評価）で申告不要なら除く。NISA の譲渡は数えない",
    source_kind=SourceKind.LAW,
    law="租税特別措置法第37条の11第1項・第37条の11の5第1項・第37条の14、同施行令第25条の10の12第1項",
    references=(f"{KABU}#4", f"{KABU}#5.1", f"{KABU}#5.2", f"{KABU}#7"),
)

DIVIDEND_INTEREST = BasisEntry(
    type=BasisType.RULE,
    name=(
        "配当所得の負債の利子：費目が配当の負債の利子の支出（業務の識別子なし）の合計 × 負債の保有の月数/12。申告しない配当に係る利子は控除しない。赤字は0。"
        "負債が2つ以上で月数が違えば未確定。配当控除の区分が2つ以上なら、区分の順・按分の候補で区分の金額が分かれれば未確定（仮説 H3）"
    ),
    source_kind=SourceKind.LAW,
    law="所得税法第24条第2項、所得税法施行令第59条第2項・第3項、所得税基本通達24−5・24−10、措置法通達8の5−2",
    references=(f"{HAITO}#1", "docs/public-sources/20261111_impl-research3_haito-laws-and-nta.md#3", "docs/hypotheses/20261111_impl-research3_all-model.md#H3"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "中間表現に配当の負債の語彙がないので、費目 dividend_debt_interest の支出と purpose_asset_id のない借入れ（loan）で読む（README の「足りない窓口」）"},
)

WINDFALL_OTHER = BasisEntry(
    type=BasisType.RULE,
    name="windfall_receipt の other・insurance_maturity は一時所得の総収入金額に数える。保険の満期金等は保険料を受取人自身が負担し、5年を超える保険期間の契約に限る（それ以外は対象外）。贈与は対象外（相手が法人か個人かの語彙がない）",
    source_kind=SourceKind.LAW,
    law="所得税法第34条第1項、所得税基本通達34−1(4)・(5)、TA No.1490（5年以下の一時払い等は源泉分離課税）",
    references=(f"{JIGYO}#6",),
    flags=(ReadingFlag.LEGAL_READING,),
)

RENTAL_REVENUE = BasisEntry(
    type=BasisType.RULE,
    name="不動産所得の総収入金額：賃料・共益費・礼金・更新料など（rent_flow）を受取日の年分に数える。敷金の預り・返還は数えない",
    source_kind=SourceKind.CIRCULAR,
    law="所得税法第26条第2項・第36条第1項、所得税基本通達36−5〜36−7、TA No.1370",
    references=(f"{FUDOSAN}#2.2",),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "契約の支払日の定めは受取日と同じと読む（基通36−5。受取日がずれた賃料は別の年分に入らない）。敷金のうち返還を要しない部分は記録にないので預りのまま"},
)

RENTAL_EXPENSE = BasisEntry(
    type=BasisType.RULE,
    name="不動産所得の必要経費：貸付けの記録がある人の、その年分に売上のない業務（business）の支出を不動産所得の必要経費と読む",
    source_kind=SourceKind.LAW,
    law="所得税法第26条第2項・第37条第1項",
    references=(f"{FUDOSAN}#2.3",),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "中間表現に業務と物件の結びつきがないための読み（README の「足りない窓口」）"},
)

RENTAL_SCALE = BasisEntry(
    type=BasisType.RULE,
    name="不動産の貸付けが事業として行われているかは判断.不動産の事業的規模（未入力なら両方で評価）。事業的規模なら専従者・55万円/65万円の控除・資産損失の全額算入が使える",
    source_kind=SourceKind.CIRCULAR,
    law="所得税基本通達26−9、TA No.1373",
    references=(f"{FUDOSAN}#3.1", f"{FUDOSAN}#3.2"),
)

FUDOSAN5 = "docs/public-sources/20261112_impl-research5_fudosan-special-losses.md"
RENTAL_SPECIAL = BasisEntry(
    type=BasisType.RULE,
    name=(
        "特定組合員・特定受益者の組合事業・信託ごとの不動産所得の損失（総収入金額の合計が必要経費の合計に満たない部分）と、国外中古建物の"
        "国外不動産所得の損失の金額（建物ごとの損失のうち償却費に相当する部分の合計から、国外不動産等の所得のうち損失が償却費を超える部分を超える額を控除）は、"
        "不動産所得の計算と損益通算の上で生じなかったものとみなす"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "租税特別措置法第41条の4の2第1項・第41条の4の3第1項・第2項、租税特別措置法施行令第26条の6の2第2項〜第4項・第26条の6の3第1項〜第3項、"
        "租税特別措置法施行規則第18条の24の2第1項"
    ),
    references=(f"{FUDOSAN5}#2", f"{FUDOSAN5}#3"),
)
RENTAL_SPECIAL_LAND_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "土地等を取得するために要した負債の利子の額は、組合事業・信託の業務の区分ごとに、生じなかったものとみなされる金額を超える部分だけ（措通41の4−4）。"
        "国外中古建物の分（償却費に相当する部分）は利子と重ならないので、その後の不動産所得の損失に措法41の4 を当てる"
    ),
    source_kind=SourceKind.CIRCULAR,
    law="租税特別措置法関係通達（所得税）41の4−4",
    references=(f"{FUDOSAN5}#4",),
    flags=(ReadingFlag.LEGAL_READING,),
)
RENTAL_LOSS = BasisEntry(
    type=BasisType.RULE,
    name="不動産所得の損失のうち土地等を取得するために要した負債の利子に相当する部分（損失の額を限度）、貸付けがすべて別荘等なら損失の全部を生じなかったものとする。負債の利子は、土地の借入れだけのときは借入金の利子の全部",
    source_kind=SourceKind.LAW,
    law="租税特別措置法第41条の4第1項、租税特別措置法施行令第26条の6第1項、所得税法第69条第2項、所得税法施行令第178条第1項第2号",
    references=(f"{FUDOSAN}#4.1", f"{FUDOSAN}#4.3"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "借入金の利子は費目 loan_interest・interest の支出で読む。土地等とそれ以外の負債が混ざる場合で損失があれば対象外"},
)

DEPRECIATION = BasisEntry(
    type=BasisType.RULE,
    name=(
        "減価償却費：資産ごとに、少額（10万円未満・使用可能期間1年未満）、一括（20万円未満・3年で1/3）、措法28の2（青色・30万円/40万円未満。年の上限まで）か、"
        "通常の償却（償却の方法の届出がなければ法定償却方法〔平成19年3月31日以前の取得は旧定額法、以後は定額法〕。届出があれば資産の種類と取得の日で選べる"
        "定率法・旧定率法を 選択.減価償却 の depreciation_method で当てる）を当てる。定額法は別表第八、定率法は別表第九・第十（保証率・改定償却率）、"
        "旧定額法・旧定率法は別表第七と別表第十一の残存割合、旧償却は取得価額の95%まで・その後5年の均等償却。月数/12。事業専用割合（家族の使用の割合だけなら 1−割合）を掛ける"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第49条第1項、所得税法施行令第120条第1項・第120条の2第1項第2項・第125条・第132条・第134条第1項〜第3項・第138条・第139条、"
        "耐用年数省令第4条第1項・第5条第1項・第6条第1項・別表第七〜第十一、租税特別措置法第28条の2・同施行令第18条の5（経過措置：令和8年法律第12号附則第35条）"
    ),
    references=(
        f"{GENKA}#2.1", f"{GENKA}#2.2", f"{GENKA}#3.1", f"{GENKA}#3.2", f"{GENKA}#4",
        f"{GENKA3}#1", f"{GENKA3}#2", f"{GENKA3}#3", f"{GENKA3}#4", f"{GENKA3}#5",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": (
        "家事兼用の未償却残高は償却費の全額で減らす読み（案A：genka H4-2）。按分の後の1円未満・一括の3分の1の1円未満は根拠のない端数の候補。"
        "中小事業者の常時使用する従業員の数の要件は記録にないので満たすと読む（家族の事業の範囲）。前年以前の償却費の累計は業務の用に供した年から計算し直す。"
        "資産の種類（判断.減価償却の区分 の asset_class）が分からず届出がある資産は、選べる方法を両方とも候補にする"
    )},
)

FAMILY = BasisEntry(
    type=BasisType.RULE,
    name="青色事業専従者給与（親族・生計を一にする・15歳以上・6月を超えて専ら従事・届出の期限内・届出の金額と相当性の範囲内）と事業専従者控除（配偶者86万円・ほか50万円と 所得÷（専従者の数＋1）の低い方）。事業に限る",
    source_kind=SourceKind.LAW,
    law="所得税法第56条・第57条第1項〜第4項・第7項、所得税法施行令第164条・第165条、所得税法施行規則第36条の4",
    references=(f"{AOIRO}#4.1", f"{AOIRO}#4.2", f"{FUDOSAN}#5.1", f"{FUDOSAN}#5.2"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "親族は婚姻・親子などの関係の記録でたどれる人と読む。専ら従事する期間は従事の記録（business_engagement）の期間で読む（6月以下・ただし書の場合は対象外）"},
)

RULE_56 = BasisEntry(
    type=BasisType.RULE,
    name=(
        "生計を一にする親族が事業（事業所得・事業的規模の不動産所得）から対価の支払を受ける場合、その対価は事業の必要経費に算入せず、"
        "親族のその対価に係る必要経費を事業の必要経費に算入し、親族の側ではその対価と必要経費をないものとみなす。"
        "家族からの賃料のうち支払った人の業務の支出と結びつかないもの（家事のための賃料）は通常の不動産所得"
    ),
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第56条（TA No.2210 の注意事項(2)）。業務（雑所得・事業的規模でない不動産所得）への当てはめは条文（事業）と TA2210（業務）で分かれ、"
        "両方で評価する（D22 S1）。青色事業専従者給与のうち届出・相当性の範囲を超える部分、要件を満たさない親族への給与も第56条で必要経費にしない（第57条第1項は第56条の例外）"
    ),
    references=(f"{FUDOSAN}#5.1", f"{FUDOSAN}#5.2", f"{FUDOSAN}#9", f"{AOIRO}#4.1"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "受取側の賃料は、支払った人の業務の支出（payee が受取側）の合計と一致するときにその業務からの対価と読む（中間表現に rent_flow と支出の結びつきがない）"},
)

FAMILY_PERIOD = BasisEntry(
    type=BasisType.RULE,
    name=(
        "専ら従事する期間：その年を通じて6月を超えるか。青色で、年の中途の開業・廃業・死亡等で事業が年を通じて営まれなかったときは、従事することができた期間の"
        "2分の1を超えるか（所令165①ただし書）。月で数えるか日で数えるかは一次情報がなく、両方で評価する。二以上の事業に従事する事業専従者の控除額は、"
        "事業の所得の合計と専従者の数で限度を計算し（所令166②）、従事した分量（記録の期間の月数か均等）で配分する（所令167）"
    ),
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法施行令第165条第1項・第166条第2項・第167条、質疑応答事例「年の中途で事業に従事した親族に係る青色事業専従者給与」",
    references=(f"{AOIRO}#4.1",),
    flags=(ReadingFlag.LEGAL_READING,),
)

CT_METHOD = BasisEntry(
    type=BasisType.RULE,
    name="消費税等の経理方式（選択。未入力なら税込・税込未払金計上・税抜の3つで評価）：税込は納付税額を申告の年（未払金に計上すれば課税期間の年）の必要経費に、税抜は課税期間の年に清算（資産の仮払消費税等を含む）",
    source_kind=SourceKind.CIRCULAR,
    law="法令解釈通達「消費税法等の施行に伴う所得税の取扱いについて」（平成元年直所3-8ほか）2・3・5・6・7・8・9",
    references=(f"{INVOICE}#5", f"{INVOICE}#8"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "税抜の所得は「税込の売上−税込の経費−その年の課税期間の納付すべき消費税等」と同じ（実測 invoice §6）。資産の税抜の取得価額は外部の値（depreciable_asset）"},
)

WITHHOLDING_RECORD = BasisEntry(
    type=BasisType.RULE,
    name="源泉徴収税額は源泉徴収票の値を優先し、なければ支払の記録の額の合計（所得税及び復興特別所得税の合計額）",
    source_kind=SourceKind.LAW,
    law="所得税法第120条第1項第4号",
    references=(f"{GENSEN}#1", f"{GENSEN}#3"),
)

#: 変数名 → その変数の値に付ける規則の根拠。
RULES: Mapping[str, tuple[BasisEntry, ...]] = {
    "所得税_公的年金等の収入金額": (PENSION_SCOPE, PENSION_KINDS, PENSION_YEAR),
    "所得税_公的年金等控除額": (PENSION_FLOOR.basis_entry(),),
    "所得税_その他の雑所得の総収入金額": (PENSION_KINDS,),
    "所得税_その他の雑所得の必要経費": (PENSION_KINDS,),
    "所得税_一時所得の総収入金額": (WINDFALL_SCOPE, WINDFALL_OTHER, WINDFALL_YEAR, WINDFALL_GIFT),
    "所得税_一時所得の支出した金額": (WINDFALL_SCOPE,),
    "所得税_退職手当等の収入金額": (RETIRE_YEAR,),
    "所得税_退職所得の勤続年数": (RETIRE_YEARS,),
    "所得税_退職手当等の区分": (RETIRE_KIND,),
    "所得税_障害者になったことに直接基因する退職か": (RETIRE_NATURE,),
    "所得税_前の退職手当等との重複年数": (RETIRE_PRIOR,),
    "所得税_短期退職手当等の収入金額": (RETIRE_KIND, RETIRE_MULTI),
    "所得税_特定役員退職手当等の収入金額": (RETIRE_KIND, RETIRE_MULTI),
    "所得税_短期退職所得控除額": (RETIRE_MULTI,),
    "所得税_特定役員退職所得控除額": (RETIRE_MULTI,),
    "所得税_事業所得の総収入金額": (BUSINESS_REVENUE,),
    "所得税_事業所得の必要経費": (BUSINESS_EXPENSE, CT_METHOD, RULE_56),
    "所得税_業務に係る雑所得の総収入金額": (BUSINESS_REVENUE,),
    "所得税_業務に係る雑所得の必要経費": (BUSINESS_EXPENSE, CT_METHOD, RULE_56),
    "所得税_事業所得の減価償却費": (DEPRECIATION, DEPRECIATION_CEIL.basis_entry()),
    "所得税_業務に係る雑所得の減価償却費": (DEPRECIATION, DEPRECIATION_CEIL.basis_entry()),
    "所得税_不動産所得の減価償却費": (DEPRECIATION, DEPRECIATION_CEIL.basis_entry()),
    "所得税_不動産所得の総収入金額": (RENTAL_REVENUE, RULE_56),
    "所得税_不動産所得の必要経費": (RENTAL_EXPENSE, BUSINESS_EXPENSE, CT_METHOD, RULE_56),
    "所得税_不動産の貸付けが事業として行われているか": (RENTAL_SCALE,),
    "所得税_土地等を取得するために要した負債の利子の額": (RENTAL_LOSS,),
    "所得税_不動産所得の貸付けがすべて別荘等か": (RENTAL_LOSS,),
    "所得税_別荘等の貸付けに係る損失の額": (RENTAL_LOSS,),
    "所得税_組合事業等と国外中古建物の不動産所得の損失のうち生じなかったものとみなす金額": (RENTAL_SPECIAL, RENTAL_SPECIAL_LAND_RULE),
    "所得税_事業所得の青色事業専従者給与の額": (FAMILY, FAMILY_PERIOD, RULE_56),
    "所得税_不動産所得の青色事業専従者給与の額": (FAMILY, FAMILY_PERIOD, RULE_56),
    "所得税_事業所得の事業専従者控除額": (FAMILY, FAMILY_PERIOD, RULE_56),
    "所得税_不動産所得の事業専従者控除額": (FAMILY, FAMILY_PERIOD, RULE_56),
    "所得税_事業専従者としてみなされる給与の収入金額": (FAMILY, FAMILY_PERIOD, RULE_56),
    "所得税_生計を一にする親族の事業から受けた給与のうち収入金額に含めない額": (FAMILY, FAMILY_PERIOD, RULE_56),
    "所得税_総合課税の配当等の負債の利子": (DIVIDEND_INTEREST,),
    "所得税_申告分離課税の配当等の負債の利子": (DIVIDEND_INTEREST,),
    "所得税_公的年金等の源泉徴収税額": (WITHHOLDING_RECORD,),
    "所得税_退職所得の源泉徴収税額": (WITHHOLDING_RECORD,),
    "所得税_配当等の源泉徴収税額": (WITHHOLDING_RECORD,),
    "所得税_上場株式等の譲渡の源泉徴収税額": (WITHHOLDING_RECORD,),
    "所得税_家内労働者等か": (HOME_WORKER,),
    "所得税_業務に係る雑所得の金額": (HOME_WORKER_SALARY, HOME_WORKER_DEFICIT),
    "所得税_青色申告特別控除前の事業所得の金額": (HOME_WORKER_SALARY, HOME_WORKER_DEFICIT),
    "所得税_青色申告の承認の状態": (BLUE_STATE,),
    "所得税_正規の簿記の要件": (BOOKKEEPING,),
    "所得税_青色申告特別控除の申告の要件": (FILING_PLAN,),
    "所得税_総合課税の配当等の収入金額": (DIVIDEND_RULE,),
    "所得税_申告分離課税の配当等の収入金額": (DIVIDEND_RULE,),
    "所得税_上場株式等の譲渡の収入金額": (STOCK_SALE_RULE,),
    "所得税_上場株式等の譲渡の取得費等": (STOCK_SALE_RULE,),
}
