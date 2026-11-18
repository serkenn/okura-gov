"""規則モジュール juminzei の根拠：パラメータでない規則（所得税の判定を写す読み、時点、端数の当て先、税額控除の順序など）。"""

from __future__ import annotations

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind

_LAW = "docs/public-sources/20261109_round2_juminzei-tax-law-text.md"
_ADMIN = "docs/public-sources/20261109_round2_juminzei-tax-admin-and-municipal.md"
_PSJ = "docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md"
_EXTRA = "docs/public-sources/20261109_round3_juminzei-extra-law-text.md"
_SOCHI = "docs/public-sources/20261109_round3_chiho-sochi-law-and-notices.md"
_TAISHOKU = "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md"
_JINTEKI = "docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md"
_R1 = "docs/public-sources/20261109_R1-laws_local-tax.md"
_SPOUSE = "docs/public-sources/20261109_round2_spouse-laws-and-sources.md"
_JM3 = "docs/public-sources/20261111_impl-research3_juminzei-laws-and-soumu.md"
_JEA = "docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md"

INCOME_RULE = BasisEntry(
    type=BasisType.RULE,
    name="前年の所得は所得税法・租税特別措置法の計算の例による（措置法の所得計算の特例を含む）。分離課税に係る退職所得（第328条）は前年の所得に入れない",
    source_kind=SourceKind.LAW,
    law="地方税法第313条第1項・第2項、第292条第1項第13号・第5項、第328条",
    references=(f"{_LAW}#2", f"{_SOCHI}#1.1", f"{_TAISHOKU}#6.3", f"{_R1}#1"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": "docs/hypotheses/20261109_round3_chiho-sochi-reading.md#H1"},
)

JUDGMENT_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "扶養親族・同一生計配偶者・特定親族・障害者・寡婦・ひとり親・勤労学生に当たるかは、所得税の同じ年（前年）の判定を使う"
        "（定義が所得税法と同じ形で、判定の時は前年の12月31日、所得の年で見た額も同じ。分離課税に係る退職所得で分かれうる場合は段の検出が対象外にする）"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第292条第1項第7号〜第12号、第314条の2第8項・第9項、同施行令第46条〜第46条の2の2",
    references=(f"{_PSJ}#5", f"{_JINTEKI}#2.1", f"{_JINTEKI}#2.2", f"{_SPOUSE}#3.1"),
    flags=(ReadingFlag.LEGAL_READING,),
)

ALLOCATION_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "住民税の扶養の所属は所得税と共有の純粋関数を住民税の規則で呼んで決める（記載で決まり、2人以上・記載なしは前年の総所得金額等が最も大きい納税義務者："
        "地方税法施行令第46条の5第2項。合計所得金額は分離課税に係る退職所得を除く。納税義務者は賦課期日に住所を有する人。所得税と同じ人は所得税の判定を使う）"
    ),
    source_kind=SourceKind.CABINET_ORDER,
    law="地方税法第292条第2項〜第4項、同施行令第46条の3〜第46条の5",
    references=(f"{_PSJ}#4.1", f"{_PSJ}#4.2"),
    flags=(ReadingFlag.LEGAL_READING,),
)

MINOR_RULE = BasisEntry(
    type=BasisType.RULE,
    name="未成年者は判定の時点（注入データ：賦課期日か前年の12月31日）の終了時に18歳未満の者（誕生日の前日の終了時に加齢する）",
    source_kind=SourceKind.LAW,
    law="地方税法第295条第1項第2号、民法第4条、年齢計算ニ関スル法律",
    references=(f"{_PSJ}#3.1", f"{_PSJ}#3.2", f"{_PSJ}#3.3"),
)

DOMICILE_RULE = BasisEntry(
    type=BasisType.RULE,
    name="賦課期日の住所は住民基本台帳に記録されている市町村（住民票と違う市町村が課税する決定があればその市町村）",
    source_kind=SourceKind.LAW,
    law="地方税法第294条第1項〜第4項、第318条",
    references=(f"{_EXTRA}#1.2", f"{_EXTRA}#1.3"),
)

COUNT_RULE = BasisEntry(
    type=BasisType.RULE,
    name="非課税の判定で数える扶養親族の人数・年齢は前年の12月31日の現況で判定する（時点を定めた規定が見つからない：控除の判定の時点の類推）",
    source_kind=SourceKind.LAW,
    law="地方税法附則第3条の3第4項、同施行令第47条の3第1号、第314条の2第8項",
    references=(f"{_PSJ}#9", f"{_PSJ}#1.4"),
    flags=(ReadingFlag.LEGAL_READING,),
)

TAXABLE_ROUNDING_RULE = BasisEntry(
    type=BasisType.RULE,
    name="課税標準額の千円未満の切捨ては、所得控除の後の課税総所得金額等（税率を乗じる額）に当てる",
    source_kind=SourceKind.LAW,
    law="地方税法第20条の4の2第1項、第314条の3第2項",
    references=(f"{_LAW}#15", f"{_LAW}#16"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": "docs/hypotheses/20261109_round2_juminzei-tax-calc-model.md#H5", "未決": "JT1（当て先を定めた一次情報がない）", "読みの候補": "読み:住民税の課税標準の千円未満の切捨ての当て先（控除前の総所得金額に当てる読みと両方で評価し、金額だけが違えば幅：D22 S1・S3）"},
)

CHAIN_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "所得割の額：市町村民税・道府県民税ごとに、算出所得割（課税総所得金額等×税率＋上場株式等の分離課税）→ 調整控除 → 配当控除・住宅借入金等特別税額控除・"
        "寄附金税額控除（調整控除の後の額が基。順序は結果に効かない）→ 附則第3条の3第5項の調整 → 申告特例控除 → 配当割額等の控除（最後）。"
        "途中は有理数で持ち、最後に百円未満を切り捨てる"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第314条の3・第314条の6・第314条の7・第314条の9・第20条の4の2第3項、附則第3条の3第5項・第5条・第5条の4・第7条の2",
    references=(f"{_LAW}#11", f"{_LAW}#15", f"{_EXTRA}#2.4", f"{_ADMIN}#1"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={
        "reading": ["docs/hypotheses/20261109_round2_juminzei-tax-calc-model.md#H8", "docs/hypotheses/20261109_round3_juminzei-extra-model.md#H4-3"],
        "申告特例控除と配当割額等の控除": (
            "申告特例は確定申告書・住民税の申告書の提出でなかったものとみなされ（附則第7条第13項第2号）、配当割額等の控除は確定申告書に記載したものに限るので、"
            "この実装では両方が同じ人に当たることがない（D22 S15 の両方の順序で評価する必要が生じない）"
        ),
        "分離課税の上場株式等": "附則第33条の2・第35条の2の2 の所得割を第314条の3 の所得割の額に加える読み（読替えの原文は docs にない）",
    },
)

DONATION_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "寄附金税額控除は、前年中の寄附金について申告（確定申告書・住民税の申告書・申告特例通知書）があったものとして計算する（申告の計画は利用側）。"
        "特例控除対象寄附金は寄附をした日の総務大臣の指定（注入データ）、第3号・第4号は市町村・道府県それぞれの条例（注入データ）で決め、"
        "寄附金の合計額（総所得金額等の30%が上限）を市町村民税・道府県民税ごとに求める。第2号（共同募金会・日本赤十字社）は地令第48条の8・第7条の17 で、"
        "総務大臣の承認を受けた募集（donation の mic_approved_solicitation）と住所の道府県内の事務所で決め、承認の記載がないもの・共同募金会の第7条の17第2号"
        "（総務大臣が定めるもの：告示が docs にない）は当たる・当たらないの候補がある（2026-11-12。JM-08）。分離課税の所得がある人の特例控除の割合は附則第5条の5（74.685%）"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第314条の7第1項・第2項・第9項・第11項・第37条の2、附則第5条の5・第5条の6・第7条第8項〜第13項",
    references=(f"{_LAW}#8.1", f"{_LAW}#8.2", f"{_LAW}#8.3", f"{_JM3}#1", f"{_JM3}#2"),
    flags=(ReadingFlag.LEGAL_READING,),
)

HOUSING_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "住宅借入金等特別税額控除：前年分の所得税の住宅借入金等特別控除の額（外部の値）が前年分の所得税の額（算出税額−配当控除）を超える部分×按分、控除限度額まで。"
        "居住年が平成28年〜令和7年なら控除限度の基に基礎控除の額−48万円を加算（令和8年以後の居住は加算しない）。平成28年〜令和3年の加算は現行の文言どおり（経路は未確認）"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法附則第5条の4第1項・第5項・第7項、令和8年法律第2号附則第11条第10項",
    references=(f"{_EXTRA}#3.2", f"{_EXTRA}#3.3", f"{_EXTRA}#3.4"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={
        "reading": "docs/hypotheses/20261109_round3_juminzei-extra-model.md#H3",
        "特定取得": "居住年が平成26年〜令和3年で特定取得・特別特定取得なら控除限度の率・上限を読み替える（第7項・第3項：4.2%・81,900円など）。housing_loan_credit の acquisition_category",
    },
)

WITHHELD_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "配当割額等の控除：前年分の確定申告書に記載した特定配当等に課された配当割額（3/5・2/5。指定都市も同じ）。"
        "令和9年度分は、2026-04-01 以後に支払を受けるべき大口株主等（同族会社と合わせて3%以上）の上場株式等の配当にも配当割があり控除の対象"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第314条の9・第37条の4・第23条第1項第15号、令和8年法律第2号附則第3条第3項",
    references=(f"{_EXTRA}#2.1", f"{_EXTRA}#2.5"),
)

SELF_MEDICATION_RULE = BasisEntry(
    type=BasisType.RULE,
    name="セルフメディケーション税制を選んだ人の医療費控除の額は、所得税の特例の額（同じ購入費、1万2千円・8万8千円）を写す",
    source_kind=SourceKind.LAW,
    law="地方税法附則第4条の5第3項（所得控除の特例。措法第41条の17 に対応）",
    references=(f"{_SOCHI}#5", f"{_LAW}#3"),
    flags=(ReadingFlag.ORIGINAL_UNVERIFIED,),
)

RETIREMENT_RULE = BasisEntry(
    type=BasisType.RULE,
    name="分離課税に係る所得割：その年中の退職所得の金額（千円未満切捨て）× 6%・4%、それぞれ百円未満切捨て。その年の1月1日の住所の市町村が課する",
    source_kind=SourceKind.LAW,
    law="地方税法第328条〜第328条の3・第50条の2〜第50条の4・第20条の4の2第1項・第3項",
    references=(f"{_LAW}#12", f"{_TAISHOKU}#6.3"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"未決": "退職所得の分離課税の端数の扱いを定めた文言の確認（docs/public-sources/20261109_round2_juminzei-tax-law-text.md §16）"},
)

PER_CAPITA_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "住所地の均等割：第311条の条例の軽減（注入データ。第1号・第2号に当たる人だけ）の後の額。住所を有する者の市町村民税・道府県民税は均等割額と所得割額の"
        "合算額で課し、確定金額の百円未満を切り捨てるので、合算額の切捨ての差を均等割の側に置く（税率が百円の倍数なら税率のまま）。家屋敷課税の均等割は"
        "住所のない市町村ごとに、その団体の税率・非課税の基準（第295条第1項・第3項）と運用の型（注入データ。型 B は配偶者が住所地で課税されていれば課さない）で決めて足す"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第24条第1項・第7項・第294条第1項・第295条・第310条・第311条・第20条の4の2第3項",
    references=(f"{_LAW}#13", f"{_LAW}#15", f"{_EXTRA}#1.1", f"{_EXTRA}#1.5", f"{_EXTRA}#1.7", f"{_JEA}#3"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": ["docs/hypotheses/20261109_round3_juminzei-extra-model.md#H1", "docs/hypotheses/20261109_round3_juminzei-extra-model.md#H2"]},
)

SEPARATE_ORDER_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "総所得金額から引ききれない所得控除は、上場株式等に係る配当所得等の金額、譲渡所得等の金額の順に控除する（住民税の一次情報がない。所得税の措通31・32共−4 の順。"
        "もう一つの順と課税標準の合計が違う人は分かれ目：一次情報なしで候補評価）"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第314条の2第11項、附則第33条の2第7項第3号・第35条の2第8項第3号・第35条の2の2第8項",
    references=(f"{_JM3}#3", "docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md#3"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": "docs/hypotheses/20261111_impl-research3_all-model.md#H10"},
)

_JZ = "docs/public-sources/20261112_impl-research5_juminzei-zasson-and-46-5.md"
JUMIN_CASUALTY_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "前年前3年内に生じた住民税の雑損失の金額（住民税の総所得金額等で計算した雑損控除の基準を超える額で、前年度までに控除されなかったもの）は、生じた年の翌年度から"
        "連続して申告書を提出しているときに限り、純損失の繰越控除の後の総所得金額・山林所得金額・退職所得金額の順に控除する（古い年の損失から）"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第313条第9項・第317条の3、同施行令第48条の3第1項",
    references=(f"{_JZ}#1",),
)
JUMIN_NET_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "前年前3年間の総所得金額・退職所得金額・山林所得金額の計算上生じた純損失の金額（前年前に控除されたものを除く）は、青色申告書を提出した年の損失は"
        "翌々年度以後、変動所得・被災事業用資産の損失は翌年度以後、連続して申告書を提出しているときに限り、総所得金額、山林所得金額、退職所得金額の順に控除する"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第313条第8項・第9項・第317条の3、同施行令第48条の3第1項",
    references=(f"{_JZ}#1",),
)
JUMIN_CASUALTY_ORDER = BasisEntry(
    type=BasisType.RULE,
    name=(
        "住民税の雑損失は、総所得金額、次に申告分離課税の上場株式等に係る配当所得等の金額・譲渡所得等の金額、次に退職所得金額から控除する"
        "（上場株式等の部分の位置は所得税の措令4の2⑨・25の11の2⑳ の順の読み。住民税の附則の読替えの原文は docs にない）"
    ),
    source_kind=SourceKind.CABINET_ORDER,
    law="地方税法施行令第48条の3第1項第2号ホ",
    references=(f"{_JZ}#1",),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": "docs/hypotheses/20261112_impl-research5_juminzei-zasson-and-46-5.md#H1"},
)
JUMIN_CASUALTY_FALLBACK = BasisEntry(
    type=BasisType.RULE,
    name=(
        "前年度の住民税の繰り越す雑損失・純損失の金額の記録がないときは、所得税の繰り越された雑損失・純損失の金額を住民税の繰越の額とする（損失の金額の計算と"
        "控除する所得が同じ人は額が同じ。分離課税に係る退職所得・特定配当等の申告で違いうる）"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第313条第2項・第9項",
    references=(f"{_JZ}#1",),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": "docs/hypotheses/20261112_impl-research5_juminzei-zasson-and-46-5.md#H2"},
)

RULES: dict[str, tuple[BasisEntry, ...]] = {
    "住民税_合計所得金額": (INCOME_RULE,),
    "住民税_総所得金額等": (INCOME_RULE, JUMIN_CASUALTY_RULE, JUMIN_CASUALTY_ORDER),
    "住民税_繰り越された雑損失の金額": (JUMIN_CASUALTY_RULE, JUMIN_CASUALTY_FALLBACK),
    "住民税_繰り越された純損失の金額": (JUMIN_NET_RULE, JUMIN_CASUALTY_FALLBACK),
    "住民税_雑損失の繰越控除額": (JUMIN_CASUALTY_RULE, JUMIN_CASUALTY_ORDER),
    "住民税_雑損失の繰越控除の後の総所得金額": (INCOME_RULE, JUMIN_CASUALTY_RULE, JUMIN_CASUALTY_ORDER),
    "住民税_雑損失の繰越控除の後の上場株式等に係る配当所得等の金額": (INCOME_RULE, JUMIN_CASUALTY_RULE, JUMIN_CASUALTY_ORDER),
    "住民税_雑損失の繰越控除の後の上場株式等に係る譲渡所得等の金額": (INCOME_RULE, JUMIN_CASUALTY_RULE, JUMIN_CASUALTY_ORDER),
    "住民税_分離課税に係る退職所得の金額": (INCOME_RULE,),
    "住民税_同一生計配偶者及び扶養親族の数": (JUDGMENT_RULE, COUNT_RULE),
    "住民税_非課税の判定で数える扶養親族か": (JUDGMENT_RULE, COUNT_RULE),
    "住民税_第295条第1項の非課税に当たるか": (JUDGMENT_RULE, MINOR_RULE),
    "住民税_人的控除差の合計": (JUDGMENT_RULE,),
    "住民税_扶養控除の額": (JUDGMENT_RULE, ALLOCATION_RULE),
    "住民税_特定親族特別控除の額": (JUDGMENT_RULE, ALLOCATION_RULE),
    "住民税_障害者控除の額": (JUDGMENT_RULE, ALLOCATION_RULE),
    "住民税_寡婦控除の額": (JUDGMENT_RULE,),
    "住民税_ひとり親控除の額": (JUDGMENT_RULE,),
    "住民税_勤労学生控除の額": (JUDGMENT_RULE,),
    "住民税_配偶者控除の額": (JUDGMENT_RULE,),
    "住民税_配偶者特別控除の額": (JUDGMENT_RULE,),
    "住民税_医療費控除の額": (SELF_MEDICATION_RULE,),
    "住民税_課税総所得金額等": (TAXABLE_ROUNDING_RULE,),
    "住民税_所得割の額": (CHAIN_RULE, DONATION_RULE),
    "住民税_寄附金税額控除の額": (CHAIN_RULE, DONATION_RULE),
    "住民税_申告特例控除の額": (CHAIN_RULE, DONATION_RULE),
    "住民税_住宅借入金等特別税額控除の額": (CHAIN_RULE, HOUSING_RULE),
    "住民税_配当割額等の控除の額": (CHAIN_RULE, WITHHELD_RULE),
    "住民税_配当割額等の控除不足額": (CHAIN_RULE, WITHHELD_RULE),
    "住民税_配当控除の額": (CHAIN_RULE,),
    "住民税_退職所得の分離課税に係る所得割の額": (RETIREMENT_RULE,),
    "住民税_均等割の額": (PER_CAPITA_RULE,),
    "住民税_上場株式等に係る課税配当所得等の金額": (SEPARATE_ORDER_RULE,),
    "住民税_上場株式等に係る課税譲渡所得等の金額": (SEPARATE_ORDER_RULE,),
}

DOCUMENT_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "所属を決める書類は記載した人の区分による：申告書を提出する義務を有する者は申告書（住民税の申告書。前年分の確定申告書は住民税の申告書とみなす）、"
        "給与所得等以外の所得を有しなかった者（1月1日現在に支払報告書を出す義務がある者から給与・公的年金等の支払を受け、前年に給与所得・公的年金等に係る所得"
        "以外の所得がない者）は給与支払報告書・公的年金等支払報告書（申請書を出せば申請書）。区分の材料（jan1_payer_status）がなければ両方で評価する"
    ),
    source_kind=SourceKind.CABINET_ORDER,
    law="地方税法施行令第46条の3第1項・第46条の4第1項・第46条の5第1項、地方税法第317条の2第1項・第317条の3",
    references=(f"{_JZ}#2",),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": "docs/hypotheses/20261112_impl-research5_juminzei-zasson-and-46-5.md#H3"},
)
REPORT_SOURCE_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "給与支払報告書の記録がない給与所得者は、扶養控除等申告書等の記載（給与所得者の扶養親族等申告書は給与支払者を経由して出し、給与支払報告書の扶養の記載の"
        "もとになる）を給与支払報告書の記載とする"
    ),
    source_kind=SourceKind.LAW,
    law="地方税法第317条の3の2・第317条の6第1項",
    references=(f"{_JZ}#2",),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"reading": "docs/hypotheses/20261112_impl-research5_juminzei-zasson-and-46-5.md#H4"},
)
STAGE_BASIS = (ALLOCATION_RULE, DOMICILE_RULE, DOCUMENT_RULE, REPORT_SOURCE_RULE)
KINTO_STAGE_BASIS = (PER_CAPITA_RULE, DOMICILE_RULE)
SEPARATE_STAGE_BASIS = (SEPARATE_ORDER_RULE,)
