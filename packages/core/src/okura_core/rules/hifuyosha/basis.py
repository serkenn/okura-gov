"""規則モジュール hifuyosha の根拠：パラメータでない規則（式・数え方・読み）。パラメータの根拠はトレースから別に足される。"""

from __future__ import annotations

from collections.abc import Mapping

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind

_SH = "docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md"
_PSK = "docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md"
_KY = "docs/public-sources/20261109_round2_kyosai-law-and-criteria.md"
_SA2 = "docs/public-sources/20261109_round2_kyosai-separate-address.md"
_KYB = "docs/public-sources/20261109_round3_kyosai-b-ministerial-criteria.md"
_R1 = "docs/public-sources/20261109_R1-laws_social-insurance-age-records.md"


def _rule(name: str, kind: SourceKind, law: str, refs: tuple[str, ...], flags: tuple[ReadingFlag, ...] = ()) -> BasisEntry:
    return BasisEntry(type=BasisType.RULE, name=name, source_kind=kind, references=refs, law=law, flags=flags)


RANGE = _rule(
    "被扶養者の範囲の親族と、同一の世帯に属することを要する続柄",
    SourceKind.LAW,
    "健康保険法第3条第7項第1号〜第4号、国家公務員共済組合法第2条第1項第2号イ〜ハ、地方公務員等共済組合法第2条第1項第2号、私立学校教職員共済法第25条",
    (f"{_KY}#1.1", f"{_KY}#1.2", f"{_SA2}#1.1"),
)
EXCLUDED = _rule(
    "被保険者・組合員・後期高齢者医療の被保険者は被扶養者にならない（1人が2人の被保険者の被扶養者にならない）",
    SourceKind.NOTIFICATION,
    "健康保険法第3条第7項ただし書、国家公務員共済組合法等の運用方針 第2条関係 第1項第2号 1、事業主の証明に依る被扶養者認定に関するQ&A A4-1、令和3年4月30日 保保発0430第2号",
    (f"{_PSK}#4.1", f"{_PSK}#4.2", f"{_KY}#3.1"),
)
DESIGNATED_ACTIVITY = _rule(
    "日本の国籍を有しない者で、特定活動のうち医療を受ける活動等・観光保養等（1年を超えない滞在）を行う者は被扶養者にならない",
    SourceKind.MINISTERIAL_ORDINANCE,
    "健康保険法第3条第7項ただし書・健康保険法施行規則第37条の3、国家公務員共済組合法施行規則第2条の5第1項、地方公務員等共済組合法施行規程第2条の3第1項、私立学校教職員共済法施行規則第1条の4の2第1項",
    (f"{_PSK}#4.1", f"{_KY}#1.2"),
)
DOMESTIC = _rule(
    "国内居住の要件：住民票で判断し、国外にいる人は留学・赴任に同行・就労以外の一時的な渡航、その他（判断）の例外",
    SourceKind.LAW,
    "健康保険法第3条第7項、健康保険法施行規則第37条の2、国家公務員共済組合法施行規則第2条の5第2項、令和元年11月13日 保保発1113第1号 第1",
    (f"{_PSK}#2.3", f"{_KY}#1.2"),
)
AGE = _rule(
    "年齢は出生の日から起算し、応当日の前日に加わる（1月1日生まれは12月31日に加わる）",
    SourceKind.LAW,
    "年齢計算ニ関スル法律、民法第143条",
    (f"{_R1}#3", f"{_PSK}#5.5"),
)
AGE_DEC31 = _rule(
    "19歳以上23歳未満は、判定日（扶養認定日）の属する年の12月31日現在の年齢で判定する（共済は組合の案内による）",
    SourceKind.NOTIFICATION,
    "令和7年7月4日 事務連絡（19歳以上23歳未満の被扶養者に係る認定に関するＱ＆Ａ）Q4",
    (f"{_SH}#1.2", f"{_PSK}#5.5", f"{_KYB}#2.3", f"{_KYB}#3.3"),
)
SAME = _rule(
    "同一の世帯：判断（判断.健保の同一の世帯）がなければ、同居の事実と保険者の運用（注入データ）で決める。共済は生計を共にし、かつ同居",
    SourceKind.NOTIFICATION,
    "昭和52年4月6日 保発第9号・庁保発第9号、国家公務員共済組合法等の運用方針 第2条関係 第1項第2号 5",
    (f"{_PSK}#2.3", f"{_SA2}#1.2", f"{_SA2}#1.3", f"{_KY}#3.1"),
)
INCOME = _rule(
    "年間収入は認定日以降の今後1年間の収入の見込み。給与は総収入額、公的年金・障害年金・遺族年金・雇用保険の給付・傷病手当金なども含む。事業収入は保険者が認める経費だけを差し引く",
    SourceKind.NOTIFICATION,
    "平成30年8月29日 事務連絡 Q13、令和7年7月4日 事務連絡 Q5、日本年金機構・協会けんぽの案内",
    (f"{_PSK}#1.1", f"{_PSK}#1.2", f"{_SH}#1.4", f"{_KY}#6.2", f"{_KY}#6.3"),
)
CONTRACT = _rule(
    "労働契約の内容による年間収入（認定日が2026-04-01以後、給与収入のみ）。時給・日給は週の額の52週分（換算式は出典にない）",
    SourceKind.NOTIFICATION,
    "令和7年10月1日 保保発1001第3号・年管管発1001第3号、令和8年3月9日 事務連絡 Q&A（第2版）Q1・Q2・Q2-2・Q10",
    (f"{_SH}#1.3", f"{_PSK}#1.2", f"{_PSK}#8"),
    (ReadingFlag.LEGAL_READING,),
)
TEMPORARY = _rule(
    "事業主の証明による一時的な収入増は、原則として連続2回まで年間収入から除く（連続は証明の日の間が1年以内の読み）",
    SourceKind.NOTIFICATION,
    "令和5年10月20日 保保発1020第3号の Q&A、令和7年10月1日 保保発1001第1号",
    (f"{_SH}#1.5", f"{_PSK}#1.2"),
    (ReadingFlag.LEGAL_READING,),
)
CONSTANCY = _rule(
    "年間収入は恒常的な収入（継続して入るもの）の状況で算定し、一時的な収入は含めない。直近の確定申告の事業収入の実績のうち、"
    "判断.収入の恒常性 が一時的とした受取は除く（判断がなければ確定申告の総収入に含める）",
    SourceKind.NOTIFICATION,
    "昭和61年4月1日 庁保発第18号（日本年金機構の疑義照会回答 整理番号6・8 の引用）、組合の基準（一時的な収入は含まない・今後も同程度の収入が見込まれる場合）",
    ("docs/public-sources/20261109_round2_gaps-sources.md#6.3", f"{_KY}#6.2", f"{_KY}#6.3"),
    (ReadingFlag.LEGAL_READING,),
)
WINDOW = _rule(
    "実績の窓（連続する月の各月の額・平均、任意の連続12か月）で基準額を超えれば恒常的に超えるものとする（保険者の運用）",
    SourceKind.INSURER_GUIDANCE,
    "公立学校共済組合広島支部・大分支部、福岡県市町村職員共済組合の基準",
    (f"{_KY}#6.4",),
)
CHILDCARE_LEAVE = _rule(
    "主として生計を維持する者が育児休業等（健保法第43条の2）の期間中は被扶養者を異動しない。その休業の子（新たに誕生した子）は改めて判定する。"
    "leave_type が other の記録も育児休業等とする（記録の種類が育児休業等）",
    SourceKind.NOTIFICATION,
    "令和3年4月30日 保保発0430第2号・保国発0430第1号 別紙3、健康保険法第43条の2",
    (f"{_PSK}#3",),
    (ReadingFlag.LEGAL_READING,),
)
REMUNERATION = _rule(
    "夫婦とも被用者保険で保険者間の協議が整わない（insurer_decision の joint_support_agreement が偽）ときは、初めに届出を受理した保険者等に届出が提出された日の属する月の"
    "標準報酬月額が高い方（同額なら届出）。一方が国保なら直近の課税（非課税）証明書の所得金額が多い方（語彙がないので未確定）",
    SourceKind.NOTIFICATION,
    "令和3年4月30日 保保発0430第2号・保国発0430第1号 別紙1(5)・別紙2(3)",
    (f"{_PSK}#3",),
)
PRIORITY = _rule(
    "私学共済：認定対象者から見て加入者より近い親族等（配偶者が最も近い）が被用者保険の被保険者か、国保の被保険者で収入が加入者より多いときは、"
    "その扶養義務が優先して認定できない（親等は民法第726条で数え、近い親族等は中間表現の人に限る）",
    SourceKind.INSURER_GUIDANCE,
    "日本私立学校振興・共済事業団「被扶養者になれる人」（PMAC-01）",
    (f"{_KY}#5",),
    (ReadingFlag.ORIGINAL_UNVERIFIED, ReadingFlag.LEGAL_READING),
)
HALF_BORDER = _rule(
    "同一の世帯の比較の基準額は、被保険者の年間収入の2分の1の1円未満を切り上げた額（整数の年間収入との「未満」の比較が同じになる。境目の説明の額）",
    SourceKind.NOTIFICATION,
    "昭和52年4月6日 保発第9号・庁保発第9号 記1",
    (f"{_SH}#1.1",),
)
SUPPORT_BORDER = _rule(
    "仕送りの基準の下限額は、型ごとに援助の側の条件を満たす最小の年額（月額の型の上限の条件を含まない。境目の説明の額）",
    SourceKind.NOTIFICATION,
    "昭和52年4月6日 保発第9号・庁保発第9号 記2、組合の基準",
    (f"{_SH}#1.1", f"{_SA2}#2"),
)
NOT_MAIN = _rule(
    "主たる扶養者でない：夫婦共同扶養で年間収入の多い方（差が1割以内なら届出）が主、共済は他の者が扶養手当を受ける者・共同扶養で主たる扶養者でない者を除く",
    SourceKind.NOTIFICATION,
    "令和3年4月30日 保保発0430第2号・保国発0430第1号 別紙1・別紙2、国家公務員共済組合法等の運用方針 第2条関係 第1項第2号 2(1)(2)",
    (f"{_PSK}#3", f"{_KY}#3.1", f"{_KYB}#3.1"),
    (ReadingFlag.LEGAL_READING,),
)
CENTRAL = _rule(
    "世帯の生計維持の中心的役割の判断に、判断.主たる扶養者（被保険者がその人の主たる扶養者か）を使う",
    SourceKind.NOTIFICATION,
    "昭和52年4月6日 保発第9号・庁保発第9号 記1 ただし書",
    (f"{_SH}#1.1",),
    (ReadingFlag.LEGAL_READING,),
)
LIVELIHOOD = _rule(
    "主として被保険者により生計を維持する：年間収入が基準額未満で、同一の世帯なら被保険者の年間収入の2分の1未満（ただし書を含む）、別居なら仕送りの基準",
    SourceKind.NOTIFICATION,
    "昭和52年4月6日 保発第9号・庁保発第9号 記1・記2、各共済の大臣の定めと組合の基準",
    (f"{_SH}#1.1", f"{_SA2}#2"),
)
SUPPORT = _rule(
    "援助による収入額は、見込み.援助額。なければ判定日の前の1年の送金の実績。手渡しを認めない運用では現金・現物の送金を除く",
    SourceKind.NOTIFICATION,
    "平成30年8月29日 事務連絡（保険局版 Q16・年金局版 Q22）",
    (f"{_PSK}#5.1", f"{_SA2}#2"),
    (ReadingFlag.LEGAL_READING,),
)

#: 変数名 → その変数の値に付ける規則の根拠。
RULES: Mapping[str, tuple[BasisEntry, ...]] = {
    "健保_被扶養者の範囲の親族か": (RANGE,),
    "健保_被扶養者から除かれる資格を有するか": (EXCLUDED, DESIGNATED_ACTIVITY),
    "健保_国内居住の要件を満たすか": (DOMESTIC,),
    "健保_判定日の年齢": (AGE,),
    "健保_判定日の属する年の12月31日の年齢": (AGE, AGE_DEC31),
    "健保_同一の世帯に属するか": (SAME,),
    "健保_収入の見込みによる年間収入": (INCOME, TEMPORARY, CONSTANCY),
    "健保_労働契約による年間収入": (CONTRACT,),
    "健保_実績による年額": (WINDOW,),
    "健保_主たる扶養者でないか": (NOT_MAIN, CHILDCARE_LEAVE, REMUNERATION, PRIORITY),
    "健保_同一の世帯の比較の基準額": (HALF_BORDER,),
    "健保_仕送りの基準の下限額": (SUPPORT_BORDER,),
    "健保_被保険者が生計維持の中心的役割を果たすか": (CENTRAL,),
    "健保_援助の見込み額": (SUPPORT,),
    "健保_主として被保険者により生計を維持するか": (LIVELIHOOD,),
    "健保_被扶養者に当たるか": (RANGE, EXCLUDED, DESIGNATED_ACTIVITY),
}
