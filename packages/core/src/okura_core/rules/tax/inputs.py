"""規則モジュール tax の situation への写し方と対象外の検出（中間表現 → 事実の層の入力変数）。

- 所得税_源泉徴収税額：所得税法第120条第1項第4号の「源泉徴収をされた又はされるべき」額（所得税及び復興特別所得税の合計額）の合計：
  - 給与：支払者ごとに、源泉徴収票（withholding_slip の salary）に源泉徴収税額があればそれを優先し（D23 K4）、なければ支払の記録の amounts.withholding_tax を合計する
    （支給日 attributes.due_on の年分：kyuyo が収入に入れる年分と同じ〔所基通36−9、D23 K3〕。所法120①四は「総所得金額…の計算の基礎となつた
    各種所得につき源泉徴収をされた又はされるべき」額なので、12月が支給日で翌年1月に支払った給与の税額も支給日の年分で差し引く〔2026-11-11 の反証役のレビュー：
    以前は支払日の年分で数え、収入と源泉徴収税額の年分が食い違っていた〕。どちらもなければ 0 か未記録かを区別できず対象外）。同じ支払者の源泉徴収票が2件以上あれば対象外。
  - 業務の報酬の受取：amounts.withholding_tax（支払明細の事実として読む：zeigaku-examples Z2、仮説 H7）。支払調書（payment_record）だけで受取の記録がなければ対象外。
  - 公的年金等：非課税（障害・遺族の年金：公的年金等の収入金額に数えない種類）を除く支払の amounts.withholding_tax。公的年金等の源泉徴収票だけで支払の記録がなければ対象外。
  - 退職手当等：支払の amounts.withholding_tax（課税退職所得金額に係る税額は常に算出税額に入れるので、源泉徴収税額も入れる）。退職所得の源泉徴収票だけで支払の記録がなければ対象外。
  - 配当等・特定口座：確定申告をしないことを選択したものは差し引かない（措法8の5・37の11の5、手引き 3-4_38、TA1330）。選択.株式等の申告の値（income_kinds の1か所：
    配当は "<人>:配当"、源泉徴収選択口座は "<人>:<口座>"）で declare が真の分だけ足す。income_kinds が1か所を宣言しない配当等（範囲外の配当・特定口座の配当）は対象外。
    2026-11-13：配当等の支払ごとの選択（subject.record_id のある選択。措法8の5④）は、その支払には人の1か所より優先する（income_kinds と同じ規則）。
  - 源泉徴収税額の欄が必要な記録に欄がないときは 0 か未記録かを区別できない（対象外。どの記録のどの欄を書けば決まるかを理由に書く）。
    ただし、源泉徴収をしない支払者（常時2人以下の家事使用人のみに支払う者：所法184）・国外で支払われた給与（所法183①「国内において」、基通121−5(3)）は0。
  - 未払（unpaid）の給与で欄がないもの：所法120①四の「されるべき」額に入るかは一次情報で決まらない（［H3］H7）ので、(a) 別表（gensen.py）で計算した額を
    入れる・(b) 入れない の両方で評価する。(a) の額は支給期の区分（attributes.pay_period など。2026-11-12 に語彙を足した）・賞与の前月の給与で
    計算し（unpaid_table_amount）、(a) でも0と言えるときを除き、源泉徴収税額を (b) の額で書いて分かれ目（決める手段：一次情報）を付ける（依存する値は未確定）。
  - 受給者が死亡した人：支給期が死亡の後の給与（所基通9−17：相続財産）の源泉徴収税額は数えない。支給期が死亡の前の給与は死亡の後に支払っても数える。
    支給日が死亡の日と同じ・定めのない給与は kyuyo の 判断.給与の支給期が死亡前か の1か所に従う（法令の読み：AFTER_DEATH_RULE）。
- 所得税法第121条の判定の事実（第1項：給与の支払者の数・全部が源泉徴収の対象か・全部が年末調整の対象か・従たる給与等の金額、第2項：退職、第3項：公的年金等）。
  docs/public-sources/20261111_impl-research_121-laws-and-nta.md。
- 所得税_予定納税額：予定納税の通知（prepayment_notice）の prepayment_total（実際に納めたかにかかわらず通知書の合計額：手引き p.28）。
  同じ人・年分に2件以上なら対象外。
- 所得税_住宅借入金等特別控除の額：housing_loan_credit の credit_amount（外部で計算した額。SCOPE §4）。2件以上なら対象外。
- 外部で計算した税額控除（external_tax_credit。2026-11-12）：credit_type ごとの credit_amount を EXTERNAL_CREDIT_VARIABLES の入力変数へ
  （事業所得等の特例に係る税額控除・住宅耐震改修特別控除・住宅特定改修特別税額控除・認定住宅等新築等特別税額控除）。同じ人・年分・種類に2件以上なら対象外（TX-26）。
- 所得税_申告の種類・所得税_相続の開始があったことを知った日：「第120条」（通常）。その年の中途に死亡した人は「第125条」で、相続人等の記録
  （heirship）の when.on を知った日として読む（VOC F-R07 の中身の「相続の開始があったことを知った日」。heirship で人ごとの日付はこれだけ：
  docs/hypotheses/20261109_round3_design-vocabulary.md §1.2。語彙の表 vocabulary.py の題には書かれていない）。相続人等の記録がない・
  知った日が相続人で違う・相続人に出国の日があるときは、相続人ごとの期限を全部求め、同じなら断定、違えば分かれ目（決める手段：一次情報。連署の1通の期限の
  定めが docs にない：shibo-shukkoku §12）。相続人の全員が放棄した（相続人不存在）ときは、国税庁の説明（質疑07-15）の「清算人が確定した日」が中間表現の語彙に
  ないので分かれ目（決める手段：事実）。相続人等の記録がないときだけ対象外（記録を入力すれば決まる）。期限の暦年の暦要項が未発表なら分かれ目（決める手段：公表待ち）。
  翌年の1月1日から通常の期限までに死亡した人は、確定申告書を提出しないで死亡したなら「第124条」
  （提出の有無は filed_document と問いの提出日で確かめる）。
  国外の滞在（abroad_stay）・判断.住所の所在 がある人は、住所が国外という判断と納税管理人の届出（tax_agent_notice）から「出国」（所得税法第2条第1項第42号）の
  日を決める：判断がなければ「出国又は非居住者」で対象外（出国の判定の材料がない）。年の中途の出国は第127条、翌年の期限までの出国は第126条で、期限は出国の時。
- 所得税_給与等が第121条第1項の適用除外か：基通121−5(1)(3)（家事使用人のみに支払う者・国外の支払）と所令262の2（同族会社の役員等が、その支払者から貸付金の利子・
  資産の対価などの支払を受ける：第121条第1項ただし書）。salary_payment の attributes（共有の担当が足した語彙）が真の支払があれば真。欄がなければ当たらないものとする（法令の読み）。
- 所得税_年末調整で控除された住宅借入金等特別控除の額（措法41の2の2⑥二：所法120① の比較で配当控除の額に加える）：住宅借入金等特別控除の額のうち年末調整で控除された額。
  居住の年分（moved_in_on の年＝その年）・給与がない・支払者ごとの源泉徴収票が年末調整なしなら0、それ以外は源泉徴収票の「住宅借入金等特別控除の額」
  （amounts.housing_loan_credit。2026-11-12 に語彙を足した）の合計。記載のない源泉徴収票・源泉徴収票のない支払者があれば分かれ目（決める手段：事実）で未確定。
- 所得税_上場株式等の所得控除の順序：措通31・32共−4 の順（配当所得等 → 譲渡所得等）と、同じ通達のただし書の納税者の選択（譲渡所得等 → 配当所得等）。
  上場株式等の配当・譲渡の記録がある人だけ 選択.所得控除の順序（dividends_first・transfers_first）の1か所を置き、未入力なら両方で評価する（D22 S20。最適化しない）。
- 記録の印（予測・見積り・計画）は状態として由来に入れる（evaluate がトレースに沿って依存する値へ伝える）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fractions import Fraction

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...candidates import Candidate
from ...money import INT32_MAX
from ...registry import DecisionSlot, DecisionSpec, ModuleInputs, YearContext, overlaps_year
from ...result import Means, OutOfScopeCategory, OutOfScopeReason, Split, State
from .calc import ORDER_ALT, ORDER_TSUTATSU, CalendarUnknown, calendar_from_parameters, death_deadline, normal_deadline
from .gensen import KO, OTSU, bonus_rate, load_wage_table, version_for, wage_tax

V_WITHHOLDING = "所得税_源泉徴収税額"
V_PREPAYMENT = "所得税_予定納税額"
V_HOUSING = "所得税_住宅借入金等特別控除の額"
V_KIND = "所得税_申告の種類"
V_KNOWN = "所得税_相続の開始があったことを知った日"
V_DEPARTURE = "所得税_出国の日"
V_PAYERS = "所得税_給与等の支払者の数"
V_SAL_ALL_WITHHELD = "所得税_給与等の全部が源泉徴収の対象か"
V_SAL_ALL_ADJUSTED = "所得税_給与等の全部が年末調整の対象か"
V_SECONDARY = "所得税_従たる給与等の金額"
V_SECONDARY_KNOWN = "所得税_従たる給与等の金額が分かるか"
V_PEN_ALL_WITHHELD = "所得税_公的年金等の全部が源泉徴収の対象か"
V_RET_ALL_WITHHELD = "所得税_退職手当等の全部が源泉徴収の対象か"
V_RET_WITHHELD = "所得税_退職手当等の源泉徴収税額"
V_121_EXCLUDED = "所得税_給与等が第121条第1項の適用除外か"
V_NENMATSU_HOUSING = "所得税_年末調整で控除された住宅借入金等特別控除の額"
V_ORDER = "所得税_上場株式等の所得控除の順序"
#: 外部で計算した税額控除（external_tax_credit の credit_type → 入力変数）。第一表 ㉞・㊴〜㊶（手引き 3-4_29・3-4_32。2026-11-12）。
EXTERNAL_CREDIT_VARIABLES: Mapping[str, str] = {
    "business_income_special": "所得税_事業所得等の特例に係る税額控除の額",
    "seismic_retrofit": "所得税_住宅耐震改修特別控除の額",
    "specified_housing_renovation": "所得税_住宅特定改修特別税額控除の額",
    "certified_housing_new_build": "所得税_認定住宅等新築等特別税額控除の額",
}

KIND_NORMAL = "第120条"
KIND_DEATH = "第125条"
KIND_DEATH_NEXT_YEAR = "第124条"
KIND_DEATH_UNDETERMINED = "第125条（知った日が決まらない）"
KIND_DEPARTURE = "出国"
KIND_ABROAD = "出国又は非居住者"
#: 知った日・出国の日がない人の入力に入れる日（式は使わない。結果には出ない）。
NO_DATE = _dt.date(1970, 1, 1)

K_STOCK = "選択.株式等の申告"
#: 公的年金等のうち非課税（公的年金等の収入金額に数えない。income_kinds の PENSION_EXEMPT と同じ支給の理由）。
EXEMPT_PENSION_REASONS = frozenset({"disability", "survivor"})

MISSING_WITHHOLDING_REASON = (
    "給与の支払に源泉徴収税額（salary_payment の amounts.withholding_tax）が書かれていない。0 か未記録かを区別できないので、"
    "源泉徴収税額の合計を決めない（欄を書くか、その支払者の給与所得の源泉徴収票〔withholding_slip の amounts.withholding_tax〕を入れれば決まる。"
    "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §4.1）"
)
UNPAID_READING = (
    "未払（unpaid）の給与で源泉徴収税額が書かれていない。所法120①四の「源泉徴収をされるべき」額に未払の給与の分が入るかは一次情報で決まらない"
    "（docs/hypotheses/20261111_impl-research3_all-model.md H7。docs/public-sources/20261111_impl-research3_gensen-laws.md §3）。"
    "(a) 別表第二〜第四（所法185・186）で計算した額を入れる・(b) 入れない の両方で評価する。(a) が0と言える給与は分かれ目にしない。"
    "源泉徴収票に源泉徴収税額があればそれを使う"
)
#: (a) の額を別表で計算するのに要る入力（分かれ目の対象に書く）。
UNPAID_NEEDS = (
    "支給期の区分（salary_payment の attributes.pay_period）と、月の整数倍の月数（pay_period_months）・その他の支給日数（pay_period_days）",
    "扶養控除等申告書の提出先（filed_document の employee_dependents_declaration：甲欄・乙欄）",
    "社会保険料等（salary_payment の amounts.social_insurance_withheld）",
    "扶養親族等の数と加算（扶養控除等申告書の entries）",
    "賞与なら前月の社会保険料等控除後の給与等の金額（salary_payment の amounts.prior_month_net_salary）",
)
#: 源泉徴収の義務がない支払（欄がなければ0）：所法184（常時2人以下の家事使用人のみに支払う者）、国外で支払われた給与（所法183①「国内において」）。
NO_WITHHOLDING_ATTRS = ("payer_withholding_exempt_household", "paid_by_foreign_mission", "paid_outside_japan")
NO_WITHHOLDING_RULE = BasisEntry(
    type=BasisType.RULE,
    name="源泉徴収をしない支払者（常時2人以下の家事使用人のみに支払う者・在日大公使館等）の給与と国外で支払われた給与は、源泉徴収税額の欄がなければ0とする",
    source_kind=SourceKind.LAW,
    law="所得税法第183条第1項（「国内において」「その支払の際」）・第184条、所得税基本通達121−5(1)(2)(3)（(2)：国際慣例により源泉徴収をする義務がないものとされる在日大公使館又は在日外交官）",
    references=(
        "docs/public-sources/20261111_impl-research_121-laws-and-nta.md#2",
        "docs/public-sources/20261111_impl-research_121-laws-and-nta.md#3",
        "docs/public-sources/20261111_impl-research3_gensen-laws.md#1",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
)
MISSING_RECEIPT_WITHHOLDING_REASON = (
    "業務の報酬の受取に源泉徴収税額（business_receipt の amounts.withholding_tax）が書かれていない。0 か未記録かを区別できないので、"
    "源泉徴収税額の合計を決めない（源泉徴収がなければ 0 と書けば決まる）"
)
MISSING_OTHER_WITHHOLDING_REASON = (
    "年金・退職手当等・配当等の支払（pension_payment・retirement_payment・dividend）に源泉徴収税額（amounts.withholding_tax）が書かれていない。"
    "0 か未記録かを区別できないので、源泉徴収税額の合計を決めない（欄を書けば決まる。docs/public-sources/20261111_impl-research_gensen-laws-and-nta.md §3）"
)
DUPLICATE_SLIP_REASON = "同じ支払者の同じ年分の給与所得の源泉徴収票が2件以上ある（どれを使うかを決められない。重複する withholding_slip を1件にすれば決まる）"
SLIP_WITHOUT_PAYMENT_REASON = (
    "源泉徴収票・支払調書に源泉徴収税額があるのに、対応する支払の記録（pension_payment・retirement_payment・business_receipt）がない"
    "（どの所得の税額かを決められない。支払の記録を入力すれば決まる）"
)
UNDECLARED_REASON = (
    "配当等・特定口座の源泉徴収税額について、確定申告をするかの選択の1か所が決まらない（この版で扱わない配当等など。"
    "確定申告をしないことを選択した配当等の税額は差し引かない：docs/public-sources/20261111_impl-research_gensen-laws-and-nta.md §1）"
)
DEATH_UNDECIDED_REASON = (
    "支給日が死亡の日と同じ日か支給日の定めのない給与で、支給期が死亡の前か（判断.給与の支給期が死亡前か）の1か所を kyuyo が宣言していない"
)
#: 給与の支給期と死亡の判断（kyuyo が宣言する1か所。key は給与の支払の記録の ID）。
K_DEATH = "判断.給与の支給期が死亡前か"
#: 死亡の日以後に支払った給与の源泉徴収税額の扱い（所基通9−17・36−9 と所法120①四の読み）。
LIQUIDATOR_RULE = BasisEntry(
    type=BasisType.RULE,
    name="相続人の全員が放棄した被相続人の期限：清算人が確定した日（estate_liquidator）を「相続の開始があったことを知った日」に当てて第125条の期限を求めた",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="国税庁の質疑応答事例 07-15（相続財産法人に所得税法第125条を類推適用し、清算人が確定した日の翌日から4か月を経過した日の前日を期限とする）",
    references=("docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#2.3",),
    flags=(ReadingFlag.LEGAL_READING,),
)
AFTER_DEATH_RULE = BasisEntry(
    type=BasisType.RULE,
    name="受給者の死亡の後の給与の支払の源泉徴収税額は、支給期が死亡の前のもの（給与等の収入金額に入れたもの）だけを死亡した人の年分に数える",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第120条第1項第4号（「総所得金額…の計算の基礎となつた各種所得につき源泉徴収をされた又はされるべき所得税の額」）、所得税基本通達9−17・36−9。"
        "支給期が死亡の後の給与は相続財産で所得税を課さないので、その源泉徴収税額も数えない。支給期が死亡の前で死亡の後に支払った給与は、kyuyo が収入に入れる年分の"
        "源泉徴収税額として数える（法令の読み）"
    ),
    references=(
        "docs/public-sources/20261111_impl-research_gensen-laws-and-nta.md#1",
        "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#2.2",
        "docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md#2.2",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
)
MULTIPLE_PREPAYMENT_REASON = "同じ年分の予定納税の通知が2件以上ある（減額の承認などで置き換わったかを決められない）"
MULTIPLE_HOUSING_REASON = "同じ年分の外部で計算した住宅借入金等特別控除の額が2件以上ある（合計してよいかを決められない）"
MULTIPLE_EXTERNAL_CREDIT_REASON = (
    "同じ年分・同じ種類（credit_type）の外部で計算した税額控除の額（external_tax_credit）が2件以上ある（重複か、合計してよいかを決められない。"
    "計算明細書・付表で計算した額を種類ごとに1件にすれば決まる）"
)
NO_HEIR_REASON = (
    "この年の中途に死亡したが、相続人等の記録（heirship）がない。期限の起算になる相続の開始があったことを知った日が決まらない"
    "（相続人・包括受遺者の heirship を入力すれば決まる。所得税法第125条第1項：docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md §2.1）"
)
HEIR_DATES_DIFFER_REASON = (
    "相続人等ごとの期限（知った日・出国の日）が違う。期限は相続人ごとで（第125条第1項の主語は「その相続人」）、連署の1通の申告書（所令263②）の"
    "期限の定めの一次情報が見つからない（docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md §12）"
)
NO_HEIR_LEFT_REASON = (
    "相続人等の全員が相続を放棄した（相続人不存在）。国税庁の説明（質疑応答事例 07-15）は相続財産法人に第125条を類推適用し、期限を「清算人が確定した日"
    "（裁判所から清算人に通知された日）の翌日から4か月を経過した日の前日」とする。清算人が確定した日（estate_liquidator）の記録がないか、1つに決まらない"
    "（docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md §2.3）"
)
HEIR_BEFORE_DEATH_REASON = "相続の開始があったことを知った日（heirship の when.on）が死亡日より前（記録の日付を直せば決まる）"
CALENDAR_PENDING = (
    "期限の日の属する暦年の春分の日・秋分の日（暦要項）が未発表で、休日の繰下げを決められない"
    "（docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md §6.1。暦要項の公表で決まる）"
)
#: 役員の利益連動の賞与（所基通36−9(2)。kyuyo と同じ語彙の値）。
OFFICER_BONUS = "officer_bonus_by_resolution"
#: 所得控除を上場株式等の所得に当てる順序の選択（措通31・32共−4 のただし書。2026-11-12 に中間表現の語彙にした）。
K_ORDER = "選択.所得控除の順序"
ORDER_BY_CHOICE = {"dividends_first": ORDER_TSUTATSU, "transfers_first": ORDER_ALT}
ORDER_CANDIDATES = (Candidate("dividends_first", ORDER_TSUTATSU), Candidate("transfers_first", ORDER_ALT))
#: 上場株式等の申告分離課税の所得になりうる記録の種類と、その当事者の役割。
STOCK_RECORDS = (("dividend", "recipient"), ("brokerage_annual", "holder"), ("security_sale", "seller"))
ABROAD_REASON = (
    "この年分に国外の滞在又は住所の所在の判断があるが、住所が国外にあるとの判断がなく「出国」（納税管理人の届出をしないで国内に住所及び居所を有しないこととなること："
    "所得税法第2条第1項第42号）の判定の材料がない（判断.住所の所在 を国外の滞在の期間について入力すれば決まる）。非居住者の申告（範囲外：D20）は判定しない"
)
NONRESIDENT_REASON = (
    "その年の1月1日より前から住所が国外という判断がある（年の始めから非居住者）。非居住者本人の申告（期限・税額）は範囲外（D20・SCOPE §4）"
)
OVERFLOW_REASON = "源泉徴収税額の合計が判定コアの整数の範囲を超える"


def _states(recs: Iterable[Mapping[str, Any]]) -> set[State]:
    return {State.from_mark(r["mark"]) for r in recs if "mark" in r}


def _reason(text: str, ids: Iterable[str]) -> OutOfScopeReason:
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, text, tuple(sorted(set(ids))))


def _in_year(rec: Mapping[str, Any], year: int) -> bool:
    when = rec.get("when") or {}
    if "on" in when:
        return _dt.date.fromisoformat(when["on"]).year == year
    if "tax_year" in when:
        return when["tax_year"] == year
    return overlaps_year(when, year)


def salary_due(rec: Mapping[str, Any]) -> _dt.date:
    """給与の収入すべき時期の日（所基通36−9。kyuyo の inputs.due_date と同じ区切り：モジュールどうしは import しないので同じ規則をここにも書く）。

    役員の利益連動の賞与（payment_type officer_bonus_by_resolution：36−9(2)）は各人ごとの支給金額が定められた日（amount_fixed_on）か
    決議等の日（resolution_on）。決議等の日がない記録は kyuyo が入力の不足として収入を対象外にするので、ここでは支給日 due_on で数える。
    それ以外は支給日 due_on（(1)・(3)・(4)。中間表現で必須）。
    """
    a = rec["attributes"]
    if a.get("payment_type") == OFFICER_BONUS:
        on = a.get("amount_fixed_on") or a.get("resolution_on")
        if on:
            return _dt.date.fromisoformat(on)
    return _dt.date.fromisoformat(a["due_on"])


def _salary_in_year(rec: Mapping[str, Any], year: int) -> bool:
    """給与の支払の年分：収入すべき時期の日（salary_due）の年（所基通36−9、D23 K3。kyuyo の収入金額と同じ区切り）。"""
    return salary_due(rec).year == year


def _death_class(rec: Mapping[str, Any], death: _dt.date) -> str:
    """給与の支給期と死亡の関係（kyuyo の区分と同じ。所基通9−17・36−9）：before・after・open（判断.給与の支給期が死亡前か の1か所）。"""
    due = salary_due(rec)
    stipulated = rec["attributes"].get("due_stipulated", True) or rec["attributes"].get("payment_type") == OFFICER_BONUS
    if due < death:
        return "before"
    if due == death or not stipulated:
        return "open"
    return "after"


def _pension_year(rec: Mapping[str, Any]) -> int:
    on = rec.get("attributes", {}).get("statutory_payment_on") or rec["when"]["on"]
    return _dt.date.fromisoformat(on).year


def _group(records: Iterable[Mapping[str, Any]], role: str) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for r in records:
        pid = r.get("roles", {}).get(role)
        if pid is not None:
            out.setdefault(pid, []).append(r)
    return out


def _by_id(recs: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(recs, key=lambda r: r["id"])


def _decision(ctx: YearContext, key: str) -> Any:
    """選択.株式等の申告の値（income_kinds が宣言した1か所）。宣言がなければ None（呼ぶ側が対象外にする）。"""
    try:
        return ctx.decision(K_STOCK, key)
    except KeyError:
        return None


@dataclass
class _Year:
    salaries: Mapping[str, list[Mapping[str, Any]]]
    receipts: Mapping[str, list[Mapping[str, Any]]]
    slips: Mapping[str, list[Mapping[str, Any]]]
    pensions: Mapping[str, list[Mapping[str, Any]]]
    retirements: Mapping[str, list[Mapping[str, Any]]]
    retirement_records: Mapping[str, list[Mapping[str, Any]]]
    dividends: Mapping[str, list[Mapping[str, Any]]]
    brokerage: Mapping[str, list[Mapping[str, Any]]]


def _year_records(ctx: YearContext) -> _Year:
    y = ctx.year
    return _Year(
        salaries=_group((r for r in ctx.records("salary_payment") if _salary_in_year(r, y)), "recipient"),
        receipts=_group((r for r in ctx.records("business_receipt") if _in_year(r, y)), "recipient"),
        slips=_group((r for r in ctx.records("withholding_slip") if _in_year(r, y)), "recipient"),
        pensions=_group((r for r in ctx.records("pension_payment") if _pension_year(r) == y), "recipient"),
        retirements=_group((r for r in ctx.records("retirement_payment") if _in_year(r, y)), "recipient"),
        retirement_records=_group(
            (r for r in ctx.records("retirement_record") if overlaps_year(r.get("when"), y) or overlaps_year(r.get("when"), y - 1)), "recipient"
        ),
        dividends=_group((r for r in ctx.records("dividend") if _in_year(r, y) and r["attributes"]["account_type"] != "nisa"), "recipient"),
        brokerage=_group((r for r in ctx.records("brokerage_annual") if _in_year(r, y)), "holder"),
    )


def build_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    year = ctx.year
    y = _year_records(ctx)
    notices: dict[str, list[Mapping[str, Any]]] = {}
    for rec in ctx.records("prepayment_notice"):
        if _in_year(rec, year):
            notices.setdefault(rec["roles"]["taxpayer"], []).append(rec)
    credits: dict[str, list[Mapping[str, Any]]] = {}
    for rec in ctx.records("housing_loan_credit"):
        if _in_year(rec, year):
            credits.setdefault(rec["roles"]["person"], []).append(rec)
    external = external_credits_by_person(ctx.records("external_tax_credit"), year)
    deadline = _normal_deadline(ctx)
    for pid in ctx.persons:
        _withholding(out, ctx, pid, y)
        _section121_facts(out, ctx, pid, y)
        _single_amount(out, pid, V_PREPAYMENT, notices.get(pid, []), "prepayment_total", MULTIPLE_PREPAYMENT_REASON)
        _single_amount(out, pid, V_HOUSING, credits.get(pid, []), "credit_amount", MULTIPLE_HOUSING_REASON)
        external_credit_inputs(out, pid, external)
        _nenmatsu_housing(out, ctx, pid, credits.get(pid, []), y)
        _order(out, ctx, pid)
        _filing_kind(out, ctx, pid, deadline)
    return out


# ---------------------------------------------------------------------------
# 選択の1か所と、年末調整の住宅借入金等特別控除（源泉徴収票の記載）
# ---------------------------------------------------------------------------


def _housing_from_slips(ctx: YearContext, pid: str, credits: Sequence[Mapping[str, Any]], y: _Year) -> tuple[int | None, tuple[str, ...]]:
    """住宅借入金等特別控除の額のうち年末調整で控除された額（措法41の2の2⑥二）と、使った源泉徴収票。決まらなければ額は None。

    決まる場合：額が0、居住の年分（措法41の2の2① は居住日の属する年の翌年以後）、その年の給与がない、
    支払者ごとの給与所得の源泉徴収票（各1件）が年末調整なし（0）か「住宅借入金等特別控除の額」（amounts.housing_loan_credit。2026-11-12 に語彙を足した）の記載がある。
    """
    rec = credits[0]
    amount = rec["amounts"]["credit_amount"]
    moved = rec.get("attributes", {}).get("moved_in_on")
    if amount <= 0 or (moved is not None and _dt.date.fromisoformat(moved).year == ctx.year):
        return 0, ()
    recs = y.salaries.get(pid, [])
    slips = [s for s in y.slips.get(pid, []) if s["attributes"]["slip_type"] == "salary"]
    by_cp = _salary_by_payer(recs, slips)
    total = 0
    used: list[str] = []
    for _p, cs in by_cp.values():
        if len(cs) != 1:
            return None, ()
        slip = cs[0]
        used.append(slip["id"])
        if slip["attributes"].get("year_end_adjusted") is False:
            continue
        if "housing_loan_credit" not in slip["amounts"]:
            return None, ()
        total += slip["amounts"]["housing_loan_credit"]
    return total, tuple(sorted(used))


def nenmatsu_split(pid: str, ids: Sequence[str]) -> Split:
    """年末調整で控除された住宅借入金等特別控除の額が記録から決まらない（決める手段：事実。源泉徴収票の欄を入力すれば決まる）。"""
    return Split(
        id=f"事実:年末調整の住宅借入金等特別控除:{pid}",
        means=Means.FACT,
        target={
            "person": pid,
            "記録": sorted(set(ids)),
            "決めるもの": "給与所得の源泉徴収票（withholding_slip の salary、支払者ごとに1件）の amounts.housing_loan_credit"
            "（住宅借入金等特別控除の額。年末調整がなければ attributes.year_end_adjusted: false）",
            "根拠": "租税特別措置法第41条の2の2第6項第2号（所得税法第120条第1項の「配当控除の額」の読替え）",
        },
        candidates=("年末調整で控除された（外部で計算した額）", "年末調整で控除されていない（0）"),
        splits_conclusion=True,
    )


def _order_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    for pid in ctx.persons:
        if _has_stock_records(ctx, pid):
            yield DecisionSlot(
                key=pid,
                target={
                    "person": pid,
                    "決めるもの": "所得控除を上場株式等に係る配当所得等の金額と譲渡所得等の金額のどちらから先に控除して申告するか（選択.所得控除の順序）",
                    "根拠": "租税特別措置法関係通達31・32共−4（ただし書）",
                },
                matches=lambda c, _pid=pid: c.get("subject", {}).get("person") == _pid,
                candidates=ORDER_CANDIDATES,
                persons=(pid,),
            )


DECISIONS = (DecisionSpec(K_ORDER, _order_slots),)


def _has_stock_records(ctx: YearContext, pid: str) -> bool:
    for kind, role in STOCK_RECORDS:
        for r in ctx.records(kind):
            if r.get("roles", {}).get(role) == pid and _in_year(r, ctx.year) and r.get("attributes", {}).get("account_type") != "nisa":
                return True
    return False


def _nenmatsu_housing(out: ModuleInputs, ctx: YearContext, pid: str, credits: Sequence[Mapping[str, Any]], y: _Year) -> None:
    ids = tuple(sorted(r["id"] for r in credits))
    if len(credits) > 1:
        out.exclude(pid, _reason(MULTIPLE_HOUSING_REASON, ids), V_NENMATSU_HOUSING)
        out.set(V_NENMATSU_HOUSING, pid, 0, ids)
        return
    if not credits:
        out.set(V_NENMATSU_HOUSING, pid, 0)
        return
    value, slip_ids = _housing_from_slips(ctx, pid, credits, y)
    slips = [s for s in y.slips.get(pid, []) if s["id"] in slip_ids]
    if value is None:
        out.set(V_NENMATSU_HOUSING, pid, 0, ids, _states(credits), missing=[nenmatsu_split(pid, ids)])
        return
    if value > INT32_MAX:
        out.exclude(pid, _reason("金額が判定コアの整数の範囲を超える", ids + slip_ids), V_NENMATSU_HOUSING)
        value = 0
    out.set(V_NENMATSU_HOUSING, pid, value, ids + slip_ids, _states(credits) | _states(slips))


def _order(out: ModuleInputs, ctx: YearContext, pid: str) -> None:
    if not _has_stock_records(ctx, pid):
        out.set(V_ORDER, pid, ORDER_TSUTATSU)
        return
    d = ctx.decision(K_ORDER, pid)
    out.set(V_ORDER, pid, ORDER_BY_CHOICE[d.value], d.record_ids, d.states)


# ---------------------------------------------------------------------------
# 源泉徴収税額
# ---------------------------------------------------------------------------


def _salary_by_payer(recs: Sequence[Mapping[str, Any]], slips: Sequence[Mapping[str, Any]]) -> dict[str, tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]]:
    """支払者 → (給与の支払の記録, 給与所得の源泉徴収票)。支払者のない源泉徴収票は `""` にまとめる。"""
    out: dict[str, tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]] = {}
    for r in recs:
        out.setdefault(r["attributes"]["counterparty"], ([], []))[0].append(r)
    for s in slips:
        if s["attributes"]["slip_type"] == "salary":
            out.setdefault(s["attributes"].get("counterparty", ""), ([], []))[1].append(s)
    return out


def _withholding(out: ModuleInputs, ctx: YearContext, pid: str, y: _Year) -> None:
    recs = _by_id(y.salaries.get(pid, []))
    receipts = _by_id(y.receipts.get(pid, []))
    slips = _by_id(y.slips.get(pid, []))
    pensions = _by_id(y.pensions.get(pid, []))
    retirements = _by_id(y.retirements.get(pid, []))
    dividends = _by_id(y.dividends.get(pid, []))
    brokerage = _by_id(y.brokerage.get(pid, []))
    ids: list[str] = []
    state_recs: list[Mapping[str, Any]] = []
    extra_states: set[State] = set()
    reasons: list[OutOfScopeReason] = []
    total = 0
    # 給与（源泉徴収票を優先：D23 K4）。死亡した人は、支給期が死亡の前の給与だけ（kyuyo の所基通9−17 の区分と同じ）
    basis: list[BasisEntry] = []
    death = ctx.death_on(pid)
    if death is not None:
        kept: list[Mapping[str, Any]] = []
        for r in recs:
            status = _death_class(r, death)
            if status == "open":
                try:
                    d = ctx.decision(K_DEATH, r["id"])
                except KeyError:
                    reasons.append(_reason(DEATH_UNDECIDED_REASON, [r["id"]]))
                    continue
                ids += list(d.record_ids)
                extra_states |= set(d.states)
                if not d.value:
                    ids.append(r["id"])
                    continue
            elif status == "after":
                ids.append(r["id"])
                continue
            kept.append(r)
        if any(_dt.date.fromisoformat(r["when"]["on"]) >= death or _death_class(r, death) != "before" for r in recs):
            basis.append(AFTER_DEATH_RULE)
        recs = kept
    missing: list[str] = []
    unpaid_open: list[str] = []
    unpaid_a: dict[str, Fraction] = {}
    for _cp, (payments, cp_slips) in sorted(_salary_by_payer(recs, slips).items()):
        ids += [r["id"] for r in payments] + [s["id"] for s in cp_slips]
        state_recs += payments + cp_slips
        if len(cp_slips) > 1:
            reasons.append(_reason(DUPLICATE_SLIP_REASON, [s["id"] for s in cp_slips]))
            continue
        if cp_slips and "withholding_tax" in cp_slips[0]["amounts"]:
            total += cp_slips[0]["amounts"]["withholding_tax"]
            continue
        for r in payments:
            if "withholding_tax" in r["amounts"]:
                continue
            if any(r["attributes"].get(a) for a in NO_WITHHOLDING_ATTRS):
                if NO_WITHHOLDING_RULE not in basis:
                    basis.append(NO_WITHHOLDING_RULE)  # 源泉徴収の義務がない：0
            elif r["attributes"].get("unpaid"):
                table = unpaid_table_amount(ctx, pid, r)
                if table != 0:
                    unpaid_open.append(r["id"])
                    if table is not None:
                        unpaid_a[r["id"]] = table
            else:
                missing.append(r["id"])
        total += sum(r["amounts"].get("withholding_tax", 0) for r in payments)
    if missing:
        reasons.append(_reason(MISSING_WITHHOLDING_REASON, missing))
    # 業務の報酬
    missing_receipts = [r["id"] for r in receipts if "withholding_tax" not in r["amounts"]]
    if missing_receipts:
        reasons.append(_reason(MISSING_RECEIPT_WITHHOLDING_REASON, missing_receipts))
    total += sum(r["amounts"].get("withholding_tax", 0) for r in receipts)
    ids += [r["id"] for r in receipts]
    state_recs += receipts
    # 公的年金等（非課税の年金の源泉徴収はない）・退職手当等
    taxable_pensions = [r for r in pensions if r["attributes"]["benefit_reason"] not in EXEMPT_PENSION_REASONS]
    for group in (taxable_pensions, retirements):
        miss = [r["id"] for r in group if "withholding_tax" not in r["amounts"]]
        if miss:
            reasons.append(_reason(MISSING_OTHER_WITHHOLDING_REASON, miss))
        total += sum(r["amounts"].get("withholding_tax", 0) for r in group)
        ids += [r["id"] for r in group]
        state_recs += group
    # 配当等：申告をする分だけ
    if dividends:
        # 1回に支払を受ける配当等ごとの選択（措法8の5④）：subject.record_id のある選択はその支払にだけ当て、ないものは人の1か所（income_kinds と同じ規則。
        # 2026-11-13：作成コーナーとの照合 B01 で、支払ごとの選択を tax が読まず、源泉徴収税額が人の1か所の候補で分かれていた）
        per_payment: dict[str, list[Mapping[str, Any]]] = {}
        for c in ctx.choices(K_STOCK):
            if (c["subject"]["person"] == pid and c["value"]["target"] == "dividend" and c["subject"].get("record_id")
                    and overlaps_year(c.get("when"), ctx.year)):
                per_payment.setdefault(c["subject"]["record_id"], []).append(c)
        dec = _decision(ctx, f"{pid}:配当") if any(r["id"] not in per_payment for r in dividends) else None
        for r in dividends:
            ids.append(r["id"])
            state_recs.append(r)
            amt = r["amounts"].get("withholding_tax")
            pc = per_payment.get(r["id"])
            if pc:
                # 同じ支払に食い違う選択があれば income_kinds が配当の値を対象外にする（MIXED_CHOICE_REASON）。ここは先頭の選択を読む
                ids += [c["id"] for c in pc]
                state_recs += pc
                value = pc[0]["value"]
            else:
                if dec is None:
                    if amt:
                        reasons.append(_reason(UNDECLARED_REASON, [r["id"]]))
                    continue
                ids += list(dec.record_ids)
                extra_states |= set(dec.states)
                value = dec.value
            if not (isinstance(value, Mapping) and value.get("declare")):
                continue
            if amt is None:
                reasons.append(_reason(MISSING_OTHER_WITHHOLDING_REASON, [r["id"]]))
            else:
                total += amt
    # 特定口座：源泉徴収選択口座は申告をする分だけ、それ以外の口座はそのまま
    for r in brokerage:
        ids.append(r["id"])
        state_recs.append(r)
        amt = r["amounts"].get("withholding_tax", 0)
        if r["attributes"]["withholding_elected"]:
            dec = _decision(ctx, f"{pid}:{r['attributes']['account_id']}")
            if dec is None:
                if amt:
                    reasons.append(_reason(UNDECLARED_REASON, [r["id"]]))
                continue
            ids += list(dec.record_ids)
            extra_states |= set(dec.states)
            if not (isinstance(dec.value, Mapping) and dec.value.get("declare")):
                continue
        total += amt
    # 支払の記録のない源泉徴収票
    for s in slips:
        kind = s["attributes"]["slip_type"]
        if kind == "salary" or not s["amounts"].get("withholding_tax"):
            continue
        related = {"public_pension": pensions, "retirement": retirements, "payment_record": receipts}.get(kind, [])
        if not related:
            ids.append(s["id"])
            state_recs.append(s)
            reasons.append(_reason(SLIP_WITHOUT_PAYMENT_REASON, [s["id"]]))
    if type(total) is not int or total < 0:
        raise TypeError("源泉徴収税額の合計が0以上の整数でない")
    if total > INT32_MAX:
        reasons.append(_reason(OVERFLOW_REASON, ids))
    for r in reasons:
        out.exclude(pid, r, V_WITHHOLDING)
    splits = [unpaid_split(pid, unpaid_open, unpaid_a)] if unpaid_open else []
    out.set(V_WITHHOLDING, pid, 0 if reasons else total, tuple(ids), _states(state_recs) | extra_states, basis=basis, missing=splits)


def unpaid_split(pid: str, ids: Sequence[str], table: Mapping[str, Fraction] | None = None) -> Split:
    """未払の給与の「されるべき」源泉徴収税額の読みの分かれ目（D22 S1：支えが同程度なので両方。［H3］H7）。

    table：別表で (a) の額を計算できた記録 → その額（扶養親族等0人の上限。1円未満は丸めない）。計算できなかった記録は要る入力を対象に書く。
    """
    table = table or {}
    return Split(
        id=f"読み:未払の給与の源泉徴収税額:{pid}",
        means=Means.PRIMARY_SOURCE,
        target={
            "person": pid, "記録": sorted(set(ids)), "理由": UNPAID_READING,
            "(a) の別表の額（扶養親族等0人とした上限）": {k: str(v) for k, v in sorted(table.items())},
            "(a) の額を決めるのに要る入力": list(UNPAID_NEEDS) if set(ids) - set(table) else [],
            "根拠": "所得税法第120条第1項第4号・第183条第1項・第185条・第186条、別表第二〜第四",
        },
        candidates=("(a) 別表で計算した額を入れる", "(b) 入れない"),
        splits_conclusion=True,
    )  # fmt: skip


def _ko_declared(ctx: YearContext, pid: str, rec: Mapping[str, Any]) -> bool:
    """その支払者に給与所得者の扶養控除等申告書を提出したか（甲欄：所法185①一）。"""
    cp = rec["attributes"]["counterparty"]
    due_year = salary_due(rec).year
    for d in ctx.records("filed_document"):
        a = d["attributes"]
        if (
            d["roles"].get("filer") == pid
            and a["document_type"] == "employee_dependents_declaration"
            and a.get("recipient_name") == cp
            and a.get("tax_year") == due_year
        ):
            return True
    return False


def unpaid_table_amount(ctx: YearContext, pid: str, rec: Mapping[str, Any]) -> Fraction | None:
    """未払の給与について、読み (a) の別表の額（扶養親族等の数を0人とした甲欄・乙欄。0人の額は数が多いときの額以上）。決まらなければ None。

    - 支給期の区分 attributes.pay_period（2026-11-12 に語彙を足した。所法185①各号イ〜ヘ）：毎月は別表第二、毎半月・毎旬は月額表の2倍・3倍の金額の
      税額の1/2・1/3、月の整数倍は月割額（pay_period_months で割った額）の税額の倍数、毎日は別表第三、その他は日割額（pay_period_days で割った額）の
      税額の支給日数倍（docs/public-sources/20261111_impl-research3_gensen-laws.md §1）。月割額・日割額の1円未満は帯の引き方に影響しない（帯の端は整数）。
    - 賞与（payment_type bonus・amounts.bonus）：前月の社会保険料等控除後の給与等の金額（amounts.prior_month_net_salary）で別表第四の率（所法186）。
      前月の給与がない（0）ときの6分の1の計算は対象にしない（None）。
    - 区分がないときは、どの区分でも0と言える場合（甲欄で、社会保険料等控除後の金額が日額表の最初の帯の下の端より小さい）だけ 0。
    甲欄・乙欄は扶養控除等申告書をその支払者に提出したか（所法185①一・二）。
    """
    a = rec["attributes"]
    amounts = rec["amounts"]
    due = salary_due(rec)
    try:
        version = version_for(due)
    except ValueError:
        return None
    column = KO if _ko_declared(ctx, pid, rec) else OTSU
    base = max(amounts["gross"] - amounts.get("social_insurance_withheld", 0), 0)
    if a.get("payment_type") == "bonus" or amounts.get("bonus"):
        prior = amounts.get("prior_month_net_salary")
        if not prior:
            return None
        rate = bonus_rate(due, prior, column)
        return None if rate is None else rate * base / 100
    if a.get("payment_type") not in (None, "regular", "retroactive_difference"):
        return None
    period = a.get("pay_period")
    if period is None:
        if column == KO and base < load_wage_table("nichigaku", version).first_lower:
            return Fraction(0)
        return None
    if period in ("monthly", "semimonthly", "ten_days"):
        times = {"monthly": 1, "semimonthly": 2, "ten_days": 3}[period]
        tax = wage_tax("getsugaku", due, base * times, column)
        return None if tax is None else tax / times
    if period == "multiple_months":
        n = a.get("pay_period_months")
        if not n:
            return None
        tax = wage_tax("getsugaku", due, base // n, column)
        return None if tax is None else tax * n
    if period == "daily":
        return wage_tax("nichigaku", due, base, column)
    days = a.get("pay_period_days")
    if not days:
        return None
    tax = wage_tax("nichigaku", due, base // days, column)
    return None if tax is None else tax * days


# ---------------------------------------------------------------------------
# 所得税法第121条の判定の事実
# ---------------------------------------------------------------------------


def _section121_facts(out: ModuleInputs, ctx: YearContext, pid: str, y: _Year) -> None:
    recs = _by_id(y.salaries.get(pid, []))
    slips = [s for s in _by_id(y.slips.get(pid, [])) if s["attributes"]["slip_type"] == "salary"]
    by_cp = _salary_by_payer(recs, slips)
    ids = tuple(r["id"] for r in recs) + tuple(s["id"] for s in slips)
    states = _states([*recs, *slips])
    all_withheld = True
    all_adjusted = bool(by_cp)
    secondary = 0
    secondary_known = bool(by_cp)
    for _cp, (payments, cp_slips) in by_cp.items():
        if not (len(cp_slips) == 1 and "withholding_tax" in cp_slips[0]["amounts"]):
            all_withheld = all_withheld and all("withholding_tax" in r["amounts"] for r in payments)
        if len(cp_slips) != 1:
            all_adjusted = False
            secondary_known = False
            continue
        a = cp_slips[0]["attributes"]
        if a.get("year_end_adjusted") is not True:
            all_adjusted = False
        if a.get("secondary_column") is None:
            secondary_known = False
        elif a["secondary_column"]:
            secondary += cp_slips[0]["amounts"]["payment_amount"]
    out.set(V_PAYERS, pid, len(by_cp), ids, states)
    excluded = [r["id"] for r in recs if section121_excluded(r)]
    out.set(V_121_EXCLUDED, pid, bool(excluded), tuple(excluded) or ids, states)
    out.set(V_SAL_ALL_WITHHELD, pid, all_withheld, ids, states)
    out.set(V_SAL_ALL_ADJUSTED, pid, all_adjusted, ids, states)
    if secondary > INT32_MAX:
        out.exclude(pid, _reason("従たる給与等の金額が判定コアの整数の範囲を超える", ids), V_SECONDARY)
        secondary = 0
    out.set(V_SECONDARY, pid, secondary, ids, states)
    out.set(V_SECONDARY_KNOWN, pid, secondary_known, ids, states)
    pensions = [r for r in _by_id(y.pensions.get(pid, [])) if r["attributes"]["benefit_reason"] not in EXEMPT_PENSION_REASONS]
    pension_ids = tuple(r["id"] for r in pensions)
    out.set(V_PEN_ALL_WITHHELD, pid, all("withholding_tax" in r["amounts"] for r in pensions), pension_ids, _states(pensions))
    retirements = _by_id(y.retirements.get(pid, []))
    records = _by_id(y.retirement_records.get(pid, []))
    declared = bool(records) and all(r["attributes"].get("declaration_submitted") is True for r in records)
    retirement_ids = tuple(r["id"] for r in retirements) + tuple(r["id"] for r in records)
    ret_withheld = sum(r["amounts"].get("withholding_tax", 0) for r in retirements)
    if ret_withheld > INT32_MAX:
        out.exclude(pid, _reason("退職手当等の源泉徴収税額が判定コアの整数の範囲を超える", retirement_ids), V_RET_WITHHELD)
        ret_withheld = 0
    # 第121条第2項第1号：退職手当等の全部について第199条及び第201条第1項の規定による徴収（退職所得の受給に関する申告書の提出があった場合）
    out.set(V_RET_ALL_WITHHELD, pid, not retirements or (declared and all("withholding_tax" in r["amounts"] for r in retirements)), retirement_ids, _states([*retirements, *records]))
    out.set(V_RET_WITHHELD, pid, ret_withheld, retirement_ids, _states(retirements))


def section121_excluded(rec: Mapping[str, Any]) -> bool:
    """その給与の支払が第121条第1項の適用を除く場合に当たるか。

    - 基通121−5(1)：所法184 の常時2人以下の家事使用人のみに支払う者からの給与（payer_withholding_exempt_household）。
    - 基通121−5(2)：国際慣例により源泉徴収をする義務がないものとされる在日大公使館・在日外交官からの給与（paid_by_foreign_mission。2026-11-12）。
    - 基通121−5(3)：国外において支払を受ける給与（paid_outside_japan）。
    - 所令262の2（第121条第1項ただし書）：同族会社の役員・その親族等が、その法人から給与等のほかに貸付金の利子・資産の対価などの支払を受ける
      （payer_family_company_officer と interest_or_rent_from_payer の両方）。
    欄がなければ当たらないものとする（法令の読み）。
    """
    a = rec["attributes"]
    return bool(
        a.get("payer_withholding_exempt_household")
        or a.get("paid_by_foreign_mission")
        or a.get("paid_outside_japan")
        or (a.get("payer_family_company_officer") and a.get("interest_or_rent_from_payer"))
    )


def external_credits_by_person(recs: Iterable[Mapping[str, Any]], year: int) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    """外部で計算した税額控除（external_tax_credit）の、その年分の記録を（人、種類）ごとに集める（種類ごとに1件。2件以上は _single_amount が対象外にする）。"""
    out: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for rec in recs:
        if _in_year(rec, year):
            out.setdefault((rec["roles"]["person"], rec["attributes"]["credit_type"]), []).append(rec)
    return out


def external_credit_inputs(out: ModuleInputs, pid: str, external: Mapping[tuple[str, str], list[Mapping[str, Any]]]) -> None:
    """種類ごとの外部で計算した税額控除の額を入力変数に書く（記録がなければ0、同じ種類に2件以上なら対象外：TX-26）。"""
    for ctype, var in EXTERNAL_CREDIT_VARIABLES.items():
        _single_amount(out, pid, var, list(external.get((pid, ctype), [])), "credit_amount", MULTIPLE_EXTERNAL_CREDIT_REASON)


def _single_amount(
    out: ModuleInputs, pid: str, var: str, recs: list[Mapping[str, Any]], field: str, multiple_reason: str
) -> None:
    ids = tuple(sorted(r["id"] for r in recs))
    value = 0
    if len(recs) > 1:
        out.exclude(pid, _reason(multiple_reason, ids), var)
    elif recs:
        value = recs[0]["amounts"][field]
        if type(value) is not int or value < 0:
            raise TypeError(f"{field} が0以上の整数でない")
        if value > INT32_MAX:
            out.exclude(pid, _reason("金額が判定コアの整数の範囲を超える", ids), var)
            value = 0
    out.set(var, pid, value, ids, _states(recs))


# ---------------------------------------------------------------------------
# 申告の種類（期限の規定）
# ---------------------------------------------------------------------------


def _normal_deadline(ctx: YearContext) -> _dt.date | None:
    """その年分の第120条の期限（第124条・第126条の「提出期限」）。パラメータの窓口がないとき・暦要項が未発表のときは None。"""
    y = ctx.year
    try:
        cals = {
            y + i: calendar_from_parameters(y + i, ctx.parameters_at(_dt.date(y + i, 1, 1)).所得税.休日)
            for i in (0, 1)
        }
        return normal_deadline(y, ctx.parameters.所得税.申告期限.第三期の末日, cals)
    except (ValueError, CalendarUnknown):
        return None


def _heirs_of(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    """被相続人 pid の相続人等（相続を放棄した人を除く：付表の注。docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md §2.3）。"""
    return sorted(
        (r for r in ctx.records("heirship") if r["roles"]["decedent"] == pid and not r.get("attributes", {}).get("renounced")),
        key=lambda r: r["id"],
    )


def _filed_before(ctx: YearContext, pid: str, day: _dt.date) -> bool:
    """その年分の確定申告書を day までに提出したか（提出した申告書の記録か、問いの提出日）。"""
    if ctx.filing_date is not None and ctx.filing_date.on <= day:
        return True
    for r in ctx.records("filed_document"):
        a = r["attributes"]
        if (
            r["roles"].get("filer") == pid
            and a["document_type"] in ("final_return", "loss_return", "quasi_final_return")
            and a.get("tax_year") == ctx.year
            and _dt.date.fromisoformat(r["when"]["on"]) <= day
        ):
            return True
    return False


def _covered_by_domestic(stay: Mapping[str, Any], judgments: Sequence[Mapping[str, Any]]) -> bool:
    """国外の滞在の全期間を、住所が国内という判断の1つが覆うか（滞在に終わりがなければ、終わりのない判断だけが覆う）。"""
    start = _dt.date.fromisoformat(stay["when"]["from_on"])
    end = _dt.date.fromisoformat(stay["when"]["to_on"]) if stay["when"].get("to_on") else None
    for j in judgments:
        when = j.get("when") or {}
        if j["value"] != "domestic" or not when.get("from_on") or _dt.date.fromisoformat(when["from_on"]) > start:
            continue
        j_end = _dt.date.fromisoformat(when["to_on"]) if when.get("to_on") else None
        if j_end is None or (end is not None and j_end >= end):
            return True
    return False


def _departure_on(ctx: YearContext, pid: str, deadline: _dt.date | None) -> tuple[_dt.date | None, tuple[str, ...], bool]:
    """「出国」の日（国内に住所及び居所を有しないこととなる日）と根拠の記録・決まらないか（undetermined）。

    判断.住所の所在 の foreign の開始日を、その年の中途か翌年の通常の期限までに探す。納税管理人の選任の届出（tax_agent_notice）が
    その日までにあれば「出国」でない（所得税法第2条第1項第42号）。国外の滞在があって住所の判断がなければ決まらない。
    """
    stays = [r for r in ctx.records("abroad_stay") if r["roles"]["person"] == pid]
    judgments = [j for j in ctx.judgments("判断.住所の所在") if j["subject"]["person"] == pid]
    y = ctx.year
    start_y = _dt.date(y, 1, 1)
    end_window = deadline if deadline is not None else _dt.date(y + 1, 3, 15)
    in_window = [r for r in stays if overlaps_year(r.get("when"), y) or start_y <= _dt.date.fromisoformat(r["when"]["from_on"]) <= end_window]
    relevant_judgments = [j for j in judgments if overlaps_year(j.get("when"), y) or overlaps_year(j.get("when"), y + 1)]
    if not in_window and not relevant_judgments:
        return None, (), False
    ids = tuple(sorted({r["id"] for r in in_window} | {j["id"] for j in relevant_judgments}))
    foreign_starts: list[_dt.date] = []
    for j in relevant_judgments:
        if j["value"] != "foreign":
            continue
        when = j.get("when") or {}
        start = _dt.date.fromisoformat(when["from_on"]) if when.get("from_on") else None
        if start is None:
            return None, ids, True
        foreign_starts.append(start)
    if not foreign_starts:
        # 住所が国内という判断だけ：国外の滞在の全期間を判断が覆わなければ決まらない
        return None, ids, any(not _covered_by_domestic(r, relevant_judgments) for r in in_window)
    start = min(foreign_starts)
    if start < start_y:
        return None, ids, True  # 年の始めから住所が国外（非居住者の申告は範囲外：D20）
    if start > end_window:
        return None, ids, False
    notices = [
        r
        for r in ctx.records("tax_agent_notice")
        if r["roles"]["taxpayer"] == pid and r["attributes"]["action"] == "appointment" and _dt.date.fromisoformat(r["when"]["on"]) <= start
    ]
    if notices:
        return None, tuple(sorted({*ids, *(r["id"] for r in notices)})), False
    return start, ids, False


def _foreign_from_year_start(ctx: YearContext, pid: str) -> bool:
    """住所が国外という判断（判断.住所の所在 の foreign）が、その年の1月1日より前から続いているか（年の始めから非居住者：範囲外）。"""
    start_y = _dt.date(ctx.year, 1, 1)
    for j in ctx.judgments("判断.住所の所在"):
        when = j.get("when") or {}
        if j["subject"]["person"] != pid or j["value"] != "foreign" or not when.get("from_on"):
            continue
        if _dt.date.fromisoformat(when["from_on"]) < start_y and (not when.get("to_on") or _dt.date.fromisoformat(when["to_on"]) >= start_y):
            return True
    return False


def _filing_kind(out: ModuleInputs, ctx: YearContext, pid: str, deadline: _dt.date | None) -> None:
    death = ctx.death_on(pid)
    departure, abroad_ids, undetermined = _departure_on(ctx, pid, deadline)
    if undetermined:
        if _foreign_from_year_start(ctx, pid):
            out.exclude(pid, OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, NONRESIDENT_REASON, tuple(sorted(set(abroad_ids)))), V_KIND)
        else:
            out.exclude(pid, _reason(ABROAD_REASON, abroad_ids), V_KIND)
        out.set(V_KIND, pid, KIND_ABROAD, abroad_ids)
        out.set(V_KNOWN, pid, NO_DATE)
        out.set(V_DEPARTURE, pid, NO_DATE)
        return
    if departure is not None:
        out.set(V_KIND, pid, KIND_DEPARTURE, abroad_ids)
        out.set(V_KNOWN, pid, NO_DATE)
        out.set(V_DEPARTURE, pid, departure, abroad_ids)
        return
    if death is not None and death.year == ctx.year:
        _death_kind(out, ctx, pid, death, KIND_DEATH)
        return
    next_jan1 = _dt.date(ctx.year + 1, 1, 1)
    if death is not None and deadline is not None and next_jan1 <= death <= deadline and not _filed_before(ctx, pid, death):
        _death_kind(out, ctx, pid, death, KIND_DEATH_NEXT_YEAR)  # 第124条第1項：提出しないで翌年の期限までに死亡
        return
    out.set(V_DEPARTURE, pid, NO_DATE)
    out.set(V_KIND, pid, KIND_NORMAL)
    out.set(V_KNOWN, pid, NO_DATE, missing=[] if deadline is not None else [calendar_split(pid, ctx.year)])


def calendar_split(pid: str, year: int) -> Split:
    """期限の暦年の暦要項が未発表（決める手段：公表待ち）。"""
    return Split(
        id=f"公表待ち:暦要項:{pid}:{year}",
        means=Means.AWAITING_PUBLICATION,
        target={"person": pid, "tax_year": year, "理由": CALENDAR_PENDING, "決めるもの": "期限の日の属する暦年の暦要項（春分の日・秋分の日）"},
        candidates=(),
        splits_conclusion=True,
    )


def _heir_deadline(ctx: YearContext, known: _dt.date, departure: _dt.date | None) -> _dt.date:
    """相続人1人の第124条・第125条の期限（calc.death_deadline）。暦要項が未発表なら CalendarUnknown。"""
    y = ctx.year
    cals = {y + i: calendar_from_parameters(y + i, ctx.parameters_at(_dt.date(y + i, 1, 1)).所得税.休日) for i in (0, 1, 2)}
    return death_deadline(known, ctx.parameters.所得税.申告期限.死亡の場合の月数, cals, departure)


def _death_kind(out: ModuleInputs, ctx: YearContext, pid: str, death: _dt.date, kind: str) -> None:
    all_heirs = sorted((r for r in ctx.records("heirship") if r["roles"]["decedent"] == pid), key=lambda r: r["id"])
    heirs = _heirs_of(ctx, pid)
    ids = tuple(r["id"] for r in all_heirs)
    states = _states(all_heirs)
    if not all_heirs:  # c-入力：相続人等の記録を入れれば決まる
        out.exclude(pid, _reason(NO_HEIR_REASON, ids), V_KIND)
        out.set(V_KIND, pid, KIND_DEATH_UNDETERMINED, ids)
        out.set(V_KNOWN, pid, NO_DATE, ids)
        out.set(V_DEPARTURE, pid, NO_DATE)
        return
    if not heirs:  # 全員が放棄（相続人不存在）：清算人が確定した日（estate_liquidator。2026-11-12 に語彙を足した）
        liq = sorted((r for r in ctx.records("estate_liquidator") if r["roles"]["decedent"] == pid), key=lambda r: r["id"])
        days = {_dt.date.fromisoformat(r["when"]["on"]) for r in liq}
        lids = ids + tuple(r["id"] for r in liq)
        lstates = states | _states(liq)
        if len(days) != 1:
            split = Split(
                id=f"事実:清算人が確定した日:{pid}",
                means=Means.FACT,
                target={"person": pid, "記録": list(lids), "理由": NO_HEIR_LEFT_REASON,
                        "決めるもの": "相続財産の清算人が確定した日（estate_liquidator の when.on。1件に決まらない・記録がない）"},
                candidates=tuple(sorted(d.isoformat() for d in days)),
                splits_conclusion=True,
            )  # fmt: skip
            out.set(V_KIND, pid, kind, lids, lstates)
            out.set(V_KNOWN, pid, NO_DATE, lids, lstates, missing=[split])
            out.set(V_DEPARTURE, pid, NO_DATE)
            return
        (known,) = days
        missing: list[Split] = []
        try:
            _heir_deadline(ctx, known, None)
        except CalendarUnknown:
            missing.append(calendar_split(pid, ctx.year))
        out.set(V_KIND, pid, kind, lids, lstates)
        out.set(V_KNOWN, pid, known, lids, lstates, missing=missing, basis=[LIQUIDATOR_RULE])
        out.set(V_DEPARTURE, pid, NO_DATE)
        return
    dates = {(_dt.date.fromisoformat(r["when"]["on"]), r.get("attributes", {}).get("heir_departure_on")) for r in heirs}
    if min(d for d, _e in dates) < death:  # c-入力
        out.exclude(pid, _reason(HEIR_BEFORE_DEATH_REASON, ids), V_KIND)
        out.set(V_KIND, pid, KIND_DEATH_UNDETERMINED, ids)
        out.set(V_KNOWN, pid, NO_DATE, ids)
        out.set(V_DEPARTURE, pid, NO_DATE)
        return
    known, dep = min(dates, key=lambda x: (x[0], x[1] or ""))
    departure = _dt.date.fromisoformat(dep) if dep else None
    missing: list[Split] = []
    if len(dates) > 1:
        try:
            deadlines = sorted({_heir_deadline(ctx, k, _dt.date.fromisoformat(e) if e else None) for k, e in dates})
        except CalendarUnknown:
            missing.append(calendar_split(pid, ctx.year))
        else:
            if len(deadlines) > 1:
                missing.append(
                    Split(
                        id=f"読み:相続人ごとの期限:{pid}",
                        means=Means.PRIMARY_SOURCE,
                        target={"person": pid, "記録": list(ids), "理由": HEIR_DATES_DIFFER_REASON, "相続人ごとの期限": [d.isoformat() for d in deadlines]},
                        candidates=tuple(d.isoformat() for d in deadlines),
                        splits_conclusion=True,
                    )
                )
    if not missing:
        try:
            _heir_deadline(ctx, known, departure)
        except CalendarUnknown:
            missing.append(calendar_split(pid, ctx.year))
    out.set(V_KIND, pid, kind, ids, states)
    out.set(V_KNOWN, pid, known, ids, states, missing=missing)
    out.set(V_DEPARTURE, pid, departure or NO_DATE, ids, states)
