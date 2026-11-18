"""規則モジュール income_kinds：申告書の欄の材料（2026-11-12 の4回目。様式の対応表 forms が写す。IK-111）。

- 第二表「住民税に関する事項」：確定申告不要制度を選んだ非上場株式の少額配当等（G29 の計算欄 B）、申告する配当等の配当割額（G30）、
  申告する源泉徴収選択口座の譲渡の株式等譲渡所得割額（G35）。令和7年分 確定申告の手引き 手順6（docs/public-sources/20261112_impl-research6_forms-tebiki.md §4）。
- 第一表 60「雑所得・一時所得等の源泉徴収税額の合計額」の材料：業務に係る雑所得の報酬の源泉徴収税額（同 §3）。
- 第二表「特例適用条文等」：判定コアが当てた課税の特例の条文（家内労働者等の必要経費の特例を当てたら「措法27」。当てなければ「なし」）。
  手引き 手順2（社会保険診療報酬 措法26・家内労働者 措法27・転廃業助成金 措法28の3 など）。住宅借入金等特別控除の居住開始年月日などの事実は利用アプリが足す（同 §1）。
"""

from __future__ import annotations

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from .calc import home_worker_expenses
from .variables import home_worker_amounts

TEBIKI = "docs/public-sources/20261112_impl-research6_forms-tebiki.md"
_PS8 = "docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md"


def tokutei_text(total: int) -> str:
    """特定支出控除の「特例適用条文等」の記載：「所法57の2 」と特定支出の合計額（明細書の ⑪）を3桁ごとのカンマで（記載例 所法５７の２ XXX,XXX円）。"""
    return f"所法57の2 {total:,}円"


def join_articles(home_worker: str | None, tokutei: str | None) -> str:
    """当てた特例の記載を並べる（家内労働者等 → 特定支出控除の順。並べ方の定めは見つからない：表示だけで税額は変わらない）。なければ「なし」。"""
    parts = [p for p in (home_worker, tokutei) if p]
    return "、".join(parts) if parts else "なし"


def _input(name: str, label: str, refs: list[str]) -> type:
    return type(name, (Variable,), {"value_type": int, "entity": 人物, "definition_period": YEAR, "label": label, "reference": refs, "__module__": __name__})


_VARS: list[type] = [
    _input("所得税_確定申告不要制度を選択した非上場株式の少額配当等の額", "確定申告不要制度（措法8の5①一）を選んだ非上場株式の少額配当等の収入金額（第二表 G29 の計算欄 B）", [f"{TEBIKI}#4"]),
    _input("所得税_申告する配当等の配当割額", "確定申告書に記載する配当等（総合課税・申告分離課税）に特別徴収された配当割額（第二表 G30）", [f"{TEBIKI}#4"]),
    _input("所得税_申告する上場株式等の譲渡の株式等譲渡所得割額", "確定申告書に記載する源泉徴収選択口座の譲渡に特別徴収された株式等譲渡所得割額（第二表 G35）", [f"{TEBIKI}#4"]),
    _input("所得税_業務に係る雑所得の源泉徴収税額", "業務に係る雑所得の報酬の受取（business_receipt）の源泉徴収税額（受取の日の年分。第一表 60 の材料）", [f"{TEBIKI}#3"]),
]


class 所得税_第二表の特例適用条文等(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    default_value = "なし"
    label = (
        "第二表「特例適用条文等」に書く、判定コアが当てた課税の特例の条文（家内労働者等の必要経費の特例：措法27。特定支出控除：所法57の2 と特定支出の合計額。"
        "なければ「なし」）"
    )
    reference = [f"{TEBIKI}#1", f"{_PS8}#7.2"]

    def formula_2025_01_01(人, period, parameters):
        # 特定支出控除（所法57の2。kyuyo KY-11）：明細書の注記「上記⑪の金額を申告書第二表の「特例適用条文等」欄に書きます。記載例：特例適用条文等 所法５７の２ XXX,XXX円」
        総額 = 人("所得税_特定支出の額の合計額", period)
        if np.any(総額 > 0):
            受ける = 人("所得税_特定支出控除の適用を受けるか", period) & 人("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", period)
        else:
            受ける = np.zeros(len(総額), dtype=bool)
        特定 = [tokutei_text(int(t)) if a else None for t, a in zip(総額, 受ける)]
        家内 = 人("所得税_家内労働者等か", period)
        if not np.any(家内):
            return np.array([join_articles(None, s) for s in 特定], dtype=object)
        事業収入 = 人("所得税_事業所得の総収入金額", period)
        事業経費 = 人("所得税_事業所得の必要経費", period)
        雑収入 = 人("所得税_業務に係る雑所得の総収入金額", period)
        雑経費 = 人("所得税_業務に係る雑所得の必要経費", period)
        減価 = 人("所得税_事業所得の減価償却費", period)
        専従給与 = 人("所得税_事業所得の青色事業専従者給与の額", period)
        専従控除 = 人("所得税_事業所得の事業専従者控除額", period)
        雑減価 = 人("所得税_業務に係る雑所得の減価償却費", period)
        給与 = 人("所得税_給与等の収入金額", period)
        控除 = 人("所得税_給与所得控除額", period) if np.any(家内 & (給与 > 0)) else np.zeros(len(家内), dtype=np.int32)
        額一覧 = home_worker_amounts(int(parameters(period).所得税.家内労働者等の必要経費の特例.額), 家内, 給与, 控除)
        out = []
        for rb, eb, rm, em, k, dep, s1, s2, md, a, s in zip(事業収入, 事業経費, 雑収入, 雑経費, 家内, 減価, 専従給与, 専従控除, 雑減価, 額一覧, 特定):
            e = home_worker_expenses(int(rb), int(eb) + int(dep) + int(s1) + int(s2), int(rm), int(em) + int(md), a, bool(k))
            out.append(join_articles("措法27" if e.special_applied else None, s))
        return np.array(out, dtype=object)


VARIABLES: tuple[type, ...] = tuple(_VARS) + (所得税_第二表の特例適用条文等,)
