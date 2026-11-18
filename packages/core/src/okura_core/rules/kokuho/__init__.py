"""規則モジュール kokuho：国民健康保険料（税）の法令の構造（SCOPE §5.4）。README.md を見る。"""

from __future__ import annotations

from pathlib import Path

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...registry import RuleModule
from .checks import CHECKS
from .inputs import INJECTIONS, ROUNDINGS, STAGES, build_groups, build_inputs, record_kinds
from .variables import VARIABLES

_KHP = "docs/public-sources/20261109_round2_kokuho-premium-structure.md"
_PS3 = "docs/public-sources/20261111_impl-research3_kokuho-laws.md"
_JJ = "docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md"
_SS = "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md"
#: 2026-11-12：上場株式等の譲渡損失の繰越控除と国保の所得（impl-research4。仮説 H8）
_PS4 = "docs/public-sources/20261112_impl-research4_kokuho-laws.md"

RULES = {
    "国保_基礎控除後の総所得金額等": (
        BasisEntry(
            BasisType.RULE,
            "国保の所得割の基礎の所得の段階",
            SourceKind.CABINET_ORDER,
            (f"{_KHP}#4.1", f"{_KHP}#4.2"),
            law="国保令第29条の7第2項第4号・第5号、地方税法第703条の4第6項・第7項（雑損失の繰越控除をしない）",
        ),
        BasisEntry(
            BasisType.RULE,
            "繰越控除を控除する所得の順序",
            SourceKind.CABINET_ORDER,
            (f"{_SS}#8", f"{_JJ}#1", f"{_JJ}#2"),
            flags=(ReadingFlag.LEGAL_READING,),
            law=(
                "所得税法施行令第204条第1項第2号・第2項（雑損失は純損失の後に、総所得金額・〔読替えで上場株式等の所得〕・山林所得金額・退職所得金額の順に控除）："
                "退職所得金額から控除した雑損失は足し戻さない（退職所得は国保の所得に含まれない）"
            ),
        ),
        BasisEntry(
            BasisType.RULE,
            "国保の非自発的失業者の特例",
            SourceKind.CABINET_ORDER,
            (f"{_KHP}#4.3",),
            flags=(ReadingFlag.LEGAL_READING,),
            law=(
                "国保令第29条の7の2・地方税法第703条の5の2（給与所得を所得税法第28条第2項により計算した金額の100分の30とする）："
                "置き換えた総所得金額は損益通算の後の総所得金額から減らした額（0で止める）、繰越控除はその後に当てると読む。100分の30の1円未満は根拠がなく候補で評価"
            ),
        ),
        BasisEntry(
            BasisType.RULE,
            "国保の所得割の基礎の上場株式等に係る譲渡所得等の金額",
            SourceKind.LAW,
            (f"{_PS4}#2",),
            flags=(ReadingFlag.LEGAL_READING,),
            law=(
                "国保令第29条の7第2項第4号の「他の所得と区分して計算される所得の金額」の上場株式等に係る譲渡所得等の金額は、地方税法附則第35条の2の6第13項"
                "（第11項の適用がある場合は附則第35条の2の2第5項の金額を適用後の金額と読み替える）により、譲渡損失の繰越控除の後の額と読む"
            ),
        ),
    ),
    "国保_軽減判定に使う所得": (
        BasisEntry(
            BasisType.RULE,
            "国保の軽減の判定の所得の段階",
            SourceKind.CABINET_ORDER,
            (f"{_KHP}#6.1", f"{_KHP}#6.2"),
            flags=(ReadingFlag.LEGAL_READING,),
            law="国保令第29条の7第6項第1号・第2号、附則第5条（公的年金等に係る所得から15万円を控除。控除しきれない額は他の所得から差し引かないと読む）",
        ),
        BasisEntry(
            BasisType.RULE,
            "国保の軽減の判定の上場株式等に係る譲渡所得等の金額",
            SourceKind.CABINET_ORDER,
            (f"{_PS4}#2",),
            law="国保令第29条の7第6項第1号のかっこ書き（地方税法附則第35条の2の6第11項の規定の適用がある場合には、その適用後の金額）：譲渡損失の繰越控除の後の額",
        ),
    ),
    "国保_保険料の額": (
        BasisEntry(
            BasisType.RULE,
            "国保の賦課限度額と減額の順序",
            SourceKind.CABINET_ORDER,
            (f"{_KHP}#5", f"{_KHP}#6.1", f"{_KHP}#7", f"{_KHP}#9"),
            flags=(ReadingFlag.LEGAL_READING,),
            law="国保令第29条の7第2項第9号ほか（賦課額は限度額を超えることができない）・第6項（均等割額等を減額する）：減額の後の賦課額に限度額を当てると読む",
        ),
        BasisEntry(
            BasisType.RULE,
            "国保税の確定金額の端数",
            SourceKind.LAW,
            (f"{_KHP}#10",),
            law="地方税法第20条の4の2第3項（国保税の確定金額の100円未満の切捨て）",
        ),
        BasisEntry(
            BasisType.RULE,
            "国保の月割り・産前産後の減額・特定世帯・端数処理の当て方",
            SourceKind.CABINET_ORDER,
            (f"{_PS3}#2", f"{_PS3}#3", f"{_PS3}#4", f"{_KHP}#8", f"{_KHP}#10"),
            flags=(ReadingFlag.LEGAL_READING,),
            law=(
                "月割りは条例（注入データ）：人ごとの所得割・資産割・均等割を月割りの月数、平等割を被保険者のいる月数で月割りする。"
                "産前産後（国保令第29条の7第6項第8号・第9号）：出産被保険者の所得割額・均等割額のうち期間の月数×1月分の割合（注入データ）を減額する（資産割・平等割は対象外）。"
                "特定世帯・特定継続世帯（同条第2項第8号ロ・ハ）：基礎・後期・子どもの区分の平等割額を注入データの額にする（介護の区分にはない）。"
                "端数処理（注入データ）：所得割額・資産割額・均等割額・平等割額・未就学児の減額の額をそれぞれ丸める"
            ),
        ),
    ),
}

MODULE = RuleModule(
    name="kokuho",
    title="国民健康保険料（税）の法令の構造",
    directory=Path(__file__).resolve().parent,
    variables=VARIABLES,
    record_kinds=record_kinds(),
    build_inputs=build_inputs,
    injections=INJECTIONS,
    groups={"国保世帯一覧": build_groups},
    roundings=ROUNDINGS,
    stages=STAGES,
    checks=CHECKS,
    rules=RULES,
)
