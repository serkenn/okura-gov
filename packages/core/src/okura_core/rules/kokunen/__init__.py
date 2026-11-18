"""規則モジュール kokunen：国民年金（保険料の月額、免除・納付猶予・学生納付特例の所得基準、第3号被保険者の判定。SCOPE §5.4・§5.5）。README.md を見る。"""

from __future__ import annotations

from pathlib import Path

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...registry import RuleModule
from .checks import CHECKS
from .inputs import DECISIONS, RECORD_KINDS, ROUTE_135_BASIS, STAGES, build_inputs
from .variables import VARIABLES

_KHP = "docs/public-sources/20261109_round2_kokuho-premium-structure.md"
_JZL = "docs/public-sources/20261109_round2_juminzei-tax-law-text.md#3"
_D3 = "docs/public-sources/20261109_round3_dai3go-notice-search.md"
_SH = "docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md#1.3"
_KN3 = "docs/public-sources/20261111_impl-research3_kokunen-laws.md"
#: 2026-11-12：第88条の3第2項・第89条の本文（取得済みの原文からの記録）
_KN89 = "docs/public-sources/20261112_impl-c_kokunen-88-3-89-text.md"
#: 2026-11-12：国年則第77条の6・令和6年法律第47号附則第10条・国年令第6条の5（impl-research4）
_KN4 = "docs/public-sources/20261112_impl-research4_kokunen-laws.md"
_ZG = "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#8.1"
_AGE = "docs/public-sources/20261109_R1-laws_social-insurance-age-records.md#3"

_MONTH_READING = "月の末日の状態（第1号被保険者か・承認された免除の期間か）で月を数える（法令の読み）"

RULES = {
    "年金_一部免除判定所得": (
        BasisEntry(
            BasisType.RULE,
            "国年の一部免除判定所得の控除",
            SourceKind.CABINET_ORDER,
            (f"{_KHP}#12.3", _JZL),
            flags=(ReadingFlag.LEGAL_READING,),
            law=(
                "国民年金法施行令第6条の12第2項：市町村民税の雑損控除額・医療費控除額・社会保険料控除額・小規模企業共済等掛金控除額に相当する額は、"
                "地方税法第314条の2第1項第1号〜第4号が所得税と同じ額（全額・同じ計算）なので所得税の値を使う。地方税法の障害者・寡婦・ひとり親・勤労学生は所得税の判定を使う。"
                "配偶者特別控除額・特定親族特別控除額は市町村民税の額（特定親族特別控除額は令和8年度の基準月の翌月以後の月分から：令和7年政令第355号附則第2条第2項）。"
                "上場株式等に係る配当所得等・譲渡所得等は第1項の列挙にない"
            ),
        ),
    ),
    "年金_免除判定所得": (
        BasisEntry(
            BasisType.RULE,
            "国年の免除判定所得の範囲",
            SourceKind.CABINET_ORDER,
            (f"{_KN3}#1", f"{_KHP}#12.3"),
            law=(
                "国民年金法施行令第6条の11：地方税法第313条第8項・第9項の控除前の総所得金額・退職所得金額・山林所得金額と、列挙した分離課税の所得の合計額。"
                "上場株式等に係る配当所得等（地方税法附則第33条の2第5項）・譲渡所得等（附則第35条の2の2第5項）は列挙にない"
            ),
        ),
    ),
    "年金_令和8年6月以前の月分の一部免除判定所得": (
        BasisEntry(
            BasisType.RULE,
            "国年令第6条の12第2項第1号の特定親族特別控除額の適用の月",
            SourceKind.CABINET_ORDER,
            (_ZG,),
            law="令和7年政令第355号附則第2条第2項（令和8年度の基準月〔国年規第77条の2：6月〕以前の月分は従前の例：特定親族特別控除額を差し引かない）",
        ),
    ),
    "年金_一部免除の区分": (ROUTE_135_BASIS,),
    "年金_納付猶予の所得基準を満たすか": (ROUTE_135_BASIS,),
    "年金_免除等の期間の学生等である月数": (
        BasisEntry(
            BasisType.RULE,
            "国年の学生等である月",
            SourceKind.CABINET_ORDER,
            (f"{_KN3}#2", f"{_KN4}#1"),
            flags=(ReadingFlag.LEGAL_READING,),
            law=(
                "国民年金法第90条第1項柱書のかっこ書き・第90条の2・第90条の3第1項、国年令第6条の6。学校教育法第1条の学校の在学は第1号〜第7号のどれかと読み、"
                "専修学校は第8号。第10号（国年則第77条の6 の教育施設）は日本年金機構の学生納付特例対象校一覧に記載された施設か（enrollment の "
                "npi_student_school_listed）で決める（機構の説明があり反対の一次情報がない：法令の読み）。各種学校の修業年限・第10号の一覧の欄がないもの・"
                "月の途中の在学は分かれ目"
            ),
        ),
    ),
    "年金_産前産後の免除の月数": (
        BasisEntry(
            BasisType.RULE,
            "国年の産前産後の期間",
            SourceKind.LAW,
            (f"{_KN3}#4",),
            flags=(ReadingFlag.LEGAL_READING,),
            law="国民年金法第88条の2（出産予定月の前月〔多胎は3月前〕から翌々月まで）、国年規第73条の6（届出の前に出産したときは出産の日）。" + _MONTH_READING,
        ),
    ),
    "年金_育児期間の免除の月数": (
        BasisEntry(
            BasisType.RULE,
            "国年の育児期間",
            SourceKind.LAW,
            (f"{_KN3}#4", f"{_KN89}#3", f"{_KN4}#2", _AGE),
            flags=(ReadingFlag.LEGAL_READING,),
            law=(
                "国民年金法第88条の3第1項・第2項（令和6年法律第47号、2026-10-01 施行。同法附則第10条：令和8年10月以後の各月の保険料に適用するので、"
                "施行の前の出産・養育の開始でも2026年10月以後の月に当てる）。期間の計算は民法第143条。養育は同居の記録か住民票の世帯が同じことで読む。"
                + _MONTH_READING
            ),
        ),
    ),
    "年金_付加保険料を納付する者となることができる月数": (
        BasisEntry(
            BasisType.RULE,
            "国年の付加保険料を納付できる月",
            SourceKind.LAW,
            (f"{_KN3}#3",),
            flags=(ReadingFlag.LEGAL_READING,),
            law=(
                "国民年金法第87条の2第1項・第2項（第89条・第90条・第90条の3・第90条の2の適用を受ける者と国民年金基金の加入員を除く。産前産後・育児期間の月は納付できる）、"
                "第89条第1項（該当するに至った日の属する月の前月から該当しなくなる日の属する月まで。第1号のかっこ書き：障害状態に該当しなくなった日から"
                "3年を経過した障害基礎年金の受給権者を除く）・第2項（納付する旨の申出のあった期間は第1項を適用しない）。" + _MONTH_READING
            ),
        ),
        BasisEntry(
            BasisType.RULE,
            "国年の法定免除の第1号のかっこ書きと第2項",
            SourceKind.LAW,
            (f"{_KN89}#1", f"{_KN89}#2"),
            law="国民年金法第89条第1項第1号のかっこ書き・第2項（原文：scripts/results/IMPL3_egov_fetch/kokunen/kokunen_2027-04-01.txt の Num=89）",
        ),
        BasisEntry(
            BasisType.RULE,
            "国年の法定免除の障害の給付と除かれる者",
            SourceKind.CABINET_ORDER,
            (f"{_KN4}#3",),
            flags=(ReadingFlag.LEGAL_READING,),
            law=(
                "国年令第6条の5第1項（障害厚生年金・障害共済年金は第4条の6 の障害の状態〔1級・2級〕の者に支給するものに限る。共済組合等の障害年金〔第6号〕ほか。"
                "労災の年金・企業年金は列挙にない）・第2項（障害状態に該当しなくなった日から3年を経過した者を除く）。決定通知書等の1級・2級を第4条の6 の状態と読む"
                "（原文：scripts/results/IMPL4_laws_egov/grep_kokunenrei_2026-11-12.txt の Num=6_5）"
            ),
        ),
    ),
    "年金_付加保険料を納付する者である月数": (
        BasisEntry(
            BasisType.RULE,
            "国年の付加保険料を納付する月",
            SourceKind.LAW,
            (f"{_KN3}#3",),
            flags=(ReadingFlag.LEGAL_READING,),
            law="国民年金法第87条の2第1項（申出をした日の属する月以後の各月）・第3項（辞退の申出）・第4項（基金の加入員となったときは辞退とみなす）。" + _MONTH_READING,
        ),
    ),
    "年金_全額免除の所得基準を満たすか": (
        BasisEntry(
            BasisType.RULE,
            "国年の障害者等の判定",
            SourceKind.LAW,
            (f"{_KHP}#12.1",),
            flags=(ReadingFlag.LEGAL_READING,),
            law="国民年金法第90条第1項第3号（地方税法に定める障害者・寡婦・ひとり親）：所得税の判定（前年の12月31日の現況）を使う",
        ),
    ),
    "年金_第3号被保険者に当たるか": (
        BasisEntry(
            BasisType.RULE,
            "国年の被扶養配偶者の認定",
            SourceKind.NOTIFICATION,
            (f"{_D3}#3", f"{_D3}#3.1", f"{_D3}#6", _SH),
            flags=(ReadingFlag.ORIGINAL_UNVERIFIED,),
            law=(
                "国民年金法施行令第4条（健康保険法等の被扶養者の認定の取扱いを勘案して機構が認定）。収入の基準（130万円・障害者180万円）と同一世帯の"
                "2分の1は健保の基準（健保.配偶者の収入の基準額・健保.同一の世帯の収入の割合）を使い、別世帯は援助額より少ない"
                "（第3号について昭和61年 庁保発第13号の最終改正の原文は未確認：HANDOFF D22 S7）。令和8年4月以後の認定日は労働契約の内容による年収（保保発1001第3号・年管管発1001第3号）"
            ),
        ),
    ),
}
RULES["年金_学生納付特例の期間の学生等である月数"] = RULES["年金_免除等の期間の学生等である月数"]
RULES["年金_令和8年6月以前の月分の学生納付特例の所得基準を満たすか"] = RULES["年金_令和8年6月以前の月分の一部免除判定所得"]

MODULE = RuleModule(
    name="kokunen",
    title="国民年金（保険料・免除等の所得基準・第3号被保険者）",
    directory=Path(__file__).resolve().parent,
    variables=VARIABLES,
    record_kinds=RECORD_KINDS,
    build_inputs=build_inputs,
    decisions=DECISIONS,
    stages=STAGES,
    checks=CHECKS,
    rules=RULES,
)
