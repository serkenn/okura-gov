"""規則モジュール hifuyosha の変数（OpenFisca）。判定日 D の単位の situation（D の属する暦年）で計算する（timepoints.py）。

事実の層の入力は inputs.py の build_inputs が判定日 D の現況から書く（判定日の窓口がない単位では仮の値）。式は calc.py の純粋関数を呼ぶ。
基準額の版は判定日で選ぶ（parameters(判定日)。概念辞書の「年をまたぐ依存」にパラメータとして宣言した）。
"""

from __future__ import annotations

import datetime as _dt
from fractions import Fraction

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物, 健康保険
from .calc import SUPPORT_S52, AgeLimits, Livelihood, SupportRules, base_category, half_threshold, livelihood, support_minimum

_DOCS_SH = "docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md"
_DOCS_PSK = "docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md"
_DOCS_KY = "docs/public-sources/20261109_round2_kyosai-law-and-criteria.md"
_DOCS_SA2 = "docs/public-sources/20261109_round2_kyosai-separate-address.md"
_DOCS_KYB = "docs/public-sources/20261109_round3_kyosai-b-ministerial-criteria.md"
_DOCS_R1 = "docs/public-sources/20261109_R1-laws_social-insurance-age-records.md"

#: 判定日の窓口がない単位の判定日の既定（OpenFisca の date の既定 1970-01-01）より後で、対象の判定日より前の日。
_NO_DATE = _dt.date(2025, 1, 1)


def _fact(name: str, value_type: type, label: str, refs: list[str]) -> type:
    """事実の層の入力変数のクラスを作る（式を持たない）。"""
    return type(name, (Variable,), {"value_type": value_type, "entity": 人物, "definition_period": YEAR, "label": label, "reference": refs})


健保_判定日 = _fact("健保_判定日", _dt.date, "判定日（認定の対象の日。基準額の版を選ぶ）", [f"{_DOCS_PSK}#5.1"])
健保_判定日の年齢 = _fact("健保_判定日の年齢", int, "判定日の年齢（年齢計算ニ関スル法律・民法第143条）", [f"{_DOCS_R1}#3", f"{_DOCS_PSK}#5.5"])
健保_判定日の属する年の12月31日の年齢 = _fact(
    "健保_判定日の属する年の12月31日の年齢", int, "判定日の属する年の12月31日現在の年齢（19歳以上23歳未満の判定）", [f"{_DOCS_SH}#1.2", f"{_DOCS_PSK}#5.5"]
)
健保_障害を支給事由とする給付の受給要件に該当する程度の障害を有するか = _fact(
    "健保_障害を支給事由とする給付の受給要件に該当する程度の障害を有するか",
    bool,
    "障害を支給事由とする給付（障害厚生年金など）の受給要件に該当する程度の障害を有するか",
    [f"{_DOCS_SH}#1.1", f"{_DOCS_KYB}#1.2"],
)
健保_国内居住の要件を満たすか = _fact(
    "健保_国内居住の要件を満たすか", bool, "日本国内に住所を有するか、又は国内居住の要件の例外に当たるか", [f"{_DOCS_PSK}#2.3", f"{_DOCS_KY}#1.2"]
)
健保_被扶養者の範囲の親族か = _fact(
    "健保_被扶養者の範囲の親族か", str, "被保険者から見た続柄の区分（同居を要しない親族・同居を要する親族・範囲外）", [f"{_DOCS_KY}#1.1", f"{_DOCS_KY}#1.2"]
)
健保_同一の世帯に属するか = _fact("健保_同一の世帯に属するか", bool, "被保険者と同一の世帯に属するか（保険者の運用による）", [f"{_DOCS_PSK}#2.3", f"{_DOCS_SA2}#1.2"])
健保_被保険者の配偶者か = _fact("健保_被保険者の配偶者か", bool, "被保険者の配偶者（事実婚を含む）か（150万円の区分から除く）", [f"{_DOCS_SH}#1.2", f"{_DOCS_KYB}#3.3"])
健保_被保険者の制度 = _fact(
    "健保_被保険者の制度", str, "被扶養者として届け出る被保険者の制度（健康保険・国家公務員共済・地方公務員共済・私学共済。なければ空）", [f"{_DOCS_KY}#1.1"]
)
健保_被扶養者から除かれる資格を有するか = _fact(
    "健保_被扶養者から除かれる資格を有するか",
    bool,
    "判定日に健保・船員保険・共済の被保険者・組合員、後期高齢者医療の被保険者、又は健保則第37条の3 の者（日本の国籍を有しない特定活動の者）か（被扶養者にならない）",
    [f"{_DOCS_PSK}#4.1", f"{_DOCS_PSK}#4.2", f"{_DOCS_KY}#1.2", f"{_DOCS_KY}#3.1"],
)
健保_収入の見込みによる年間収入 = _fact(
    "健保_収入の見込みによる年間収入", int, "従来の方法（今後1年間の収入の見込み）による年間収入（保険者の運用を当てた後）", [f"{_DOCS_PSK}#1.1", f"{_DOCS_PSK}#1.2"]
)
健保_労働契約による判定を使うか = _fact("健保_労働契約による判定を使うか", bool, "労働契約の内容による年間収入の判定を使うか", [f"{_DOCS_SH}#1.3"])
健保_労働契約による年間収入 = _fact("健保_労働契約による年間収入", int, "労働契約で定められた賃金から見込まれる年間収入", [f"{_DOCS_SH}#1.3", f"{_DOCS_PSK}#1.2"])
健保_実績による年額 = _fact(
    "健保_実績による年額", int, "実績の窓（連続する月・任意の12か月）による年額換算（0 なら窓で超えない）", [f"{_DOCS_KY}#6.4"]
)
健保_被保険者本人の年間収入の見込み = _fact(
    "健保_被保険者本人の年間収入の見込み", int, "被保険者本人の今後1年間の年間収入の見込み（見込み.被保険者の年間収入）", [f"{_DOCS_SH}#1.1", f"{_DOCS_PSK}#3"]
)
健保_援助の見込み額 = _fact("健保_援助の見込み額", int, "被保険者からの今後1年間の援助（仕送り）の見込み額", [f"{_DOCS_SA2}#2", f"{_DOCS_PSK}#5.1"])
健保_他の者からの援助の見込み額 = _fact("健保_他の者からの援助の見込み額", int, "被保険者以外の者からの援助の見込み額（全収入の計算に使う）", [f"{_DOCS_SA2}#2"])
健保_別居の仕送りの基準の型 = _fact("健保_別居の仕送りの基準の型", str, "同一の世帯に属しないときの仕送りの基準の型（保険者の運用）", [f"{_DOCS_SA2}#2"])
健保_主たる扶養者でないか = _fact(
    "健保_主たる扶養者でないか",
    bool,
    "主として生計を維持する者でない（夫婦共同扶養で他方が主・共済で他の者が扶養手当を受ける・共同扶養で主たる扶養者でない）",
    [f"{_DOCS_PSK}#3", f"{_DOCS_KY}#3.1"],
)
健保_被保険者が生計維持の中心的役割を果たすか = _fact(
    "健保_被保険者が生計維持の中心的役割を果たすか", bool, "被保険者が世帯の生計維持の中心的役割を果たしていると認められるか（S52 記1 のただし書）", [f"{_DOCS_SH}#1.1"]
)


def _on_of(values: np.ndarray, fallback: str) -> str:
    """判定日（同じ situation の全員で同じ）。判定日の窓口がない単位（既定の日付）では期間の初日。"""
    if values.size == 0:
        return fallback
    d = _dt.date.fromisoformat(str(values[0])[:10])
    return d.isoformat() if d >= _NO_DATE else fallback


def _young_applies(node, on: str) -> bool:  # noqa: ANN001
    return on >= str(node["19歳以上23歳未満"].適用開始日)


def base_category_of(age: int, dec31: int, disabled: bool, spouse: bool, limits: AgeLimits, node, on: str) -> str:  # noqa: ANN001
    """基準額の区分（19歳以上23歳未満の区分は判定日が適用開始日以後のときだけ）。"""
    return base_category(age, dec31, disabled, spouse, limits, _young_applies(node, on))


def base_amount(node, on: str, category: str) -> int:  # noqa: ANN001
    """制度の基準額の木（parameters(…).健保.被扶養者の収入の基準額.<制度>）から区分の額。"""
    if category == "19歳以上23歳未満":
        return int(node[category].額)
    return int(node[category])


class 健保_収入の基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "被扶養者の年間収入の基準額（130万円・19歳以上23歳未満は150万円〔判定日が2025-10-01以後〕・60歳以上又は障害者は180万円）"
    reference = [f"{_DOCS_SH}#1.1", f"{_DOCS_SH}#1.2", f"{_DOCS_KYB}#4"]

    def formula_2025_01_01(人, period, parameters):
        日 = _on_of(人("健保_判定日", period), str(period.start))
        基準 = parameters(period).健保.被扶養者の収入の基準額
        区分 = parameters(period).健保.被扶養者の年齢の区分
        limits = AgeLimits(int(区分["60歳以上"]), int(区分["19歳以上"]), int(区分["23歳未満"]))
        年齢 = 人("健保_判定日の年齢", period)
        年末 = 人("健保_判定日の属する年の12月31日の年齢", period)
        障害 = 人("健保_障害を支給事由とする給付の受給要件に該当する程度の障害を有するか", period)
        配偶者 = 人("健保_被保険者の配偶者か", period)
        制度 = 人("健保_被保険者の制度", period)
        out = []
        for a, e, d, sp, s in zip(年齢, 年末, 障害, 配偶者, 制度):
            node = 基準[str(s) or "健康保険"]
            out.append(base_amount(node, 日, base_category_of(int(a), int(e), bool(d), bool(sp), limits, node, 日)))
        return np.array(out, dtype=np.int32)


class 健保_配偶者の収入の基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "被保険者の配偶者として認定するときの年間収入の基準額（健康保険の区分。国民年金の第3号被保険者の窓口）"
    reference = [f"{_DOCS_SH}#1.1", f"{_DOCS_SH}#1.2", "docs/public-sources/20261109_round3_dai3go-notice-search.md#3.1"]

    def formula_2025_01_01(人, period, parameters):
        日 = _on_of(人("健保_判定日", period), str(period.start))
        node = parameters(period).健保.被扶養者の収入の基準額["健康保険"]
        区分 = parameters(period).健保.被扶養者の年齢の区分
        limits = AgeLimits(int(区分["60歳以上"]), int(区分["19歳以上"]), int(区分["23歳未満"]))
        年齢 = 人("健保_判定日の年齢", period)
        年末 = 人("健保_判定日の属する年の12月31日の年齢", period)
        障害 = 人("健保_障害を支給事由とする給付の受給要件に該当する程度の障害を有するか", period)
        out = [
            base_amount(node, 日, base_category_of(int(a), int(e), bool(d), True, limits, node, 日))
            for a, e, d in zip(年齢, 年末, 障害)
        ]
        return np.array(out, dtype=np.int32)


class 健保_同一の世帯の収入の割合(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "同一の世帯の認定対象者の年間収入を比べる、被保険者の年間収入に対する割合（「分子/分母」。国民年金の第3号被保険者の窓口）"
    reference = [f"{_DOCS_SH}#1.1"]

    def formula_2025_01_01(人, period, parameters):
        比較 = parameters(period).健保.生計維持の比較.同一の世帯の収入の割合
        r = Fraction(int(比較.分子), int(比較.分母))
        return f"{r.numerator}/{r.denominator}"  # 全員に同じ値（OpenFisca が人の数の配列にする）


class 健保_年間収入(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "被扶養者の認定の年間収入（今後1年間の収入の見込み。認定日が2026-04-01以後で使えるなら労働契約の内容による）"
    reference = [f"{_DOCS_PSK}#1.1", f"{_DOCS_PSK}#1.2", f"{_DOCS_SH}#1.3"]

    def formula_2025_01_01(人, period):
        return np.where(
            人("健保_労働契約による判定を使うか", period),
            人("健保_労働契約による年間収入", period),
            人("健保_収入の見込みによる年間収入", period),
        ).astype(np.int32)


class 健保_被保険者の年間収入(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "被保険者の年間収入（同一の世帯の認定対象者の収入が、その2分の1未満かの比較に使う。被保険者本人の値）"
    reference = [f"{_DOCS_SH}#1.1", f"{_DOCS_PSK}#2.3"]

    def formula_2025_01_01(人, period):
        return 人("健保_被保険者本人の年間収入の見込み", period)


class 健保_援助による収入額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "同一の世帯に属しない認定対象者が、被保険者から受ける援助（仕送り）による収入額"
    reference = [f"{_DOCS_SA2}#2", f"{_DOCS_PSK}#2.3"]

    def formula_2025_01_01(人, period):
        return 人("健保_援助の見込み額", period)


def support_rules(p) -> SupportRules:  # noqa: ANN001
    """parameters(…).健保.別居の仕送りの基準 から型の中の数値の規則を作る。"""
    return SupportRules(
        share_of_total=Fraction(int(p.全収入に占める割合.分子), int(p.全収入に占める割合.分母)),
        monthly_income_border=int(p.月収の境),
        monthly_minimum=int(p.月の最低額),
        monthly_share=Fraction(int(p.月収に対する割合.分子), int(p.月収に対する割合.分母)),
        monthly_unit=int(p.端数の単位),
        annual_minimum=int(p.年の最低額),
    )


class 健保_年間収入が収入の基準額未満か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "年間収入が収入の基準額未満か（生計維持の収入の要件の比較だけ。境目の説明の判定）"
    reference = [f"{_DOCS_SH}#1.1", f"{_DOCS_SH}#1.2", f"{_DOCS_KYB}#4"]

    def formula_2025_01_01(人, period):
        return 人("健保_年間収入", period) < 人("健保_収入の基準額", period)


class 健保_同一の世帯の比較の基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "同一の世帯の比較の基準額：被保険者の年間収入の2分の1（1円未満切上げ。整数の年間収入との「未満」の比較が同じになる額。境目の説明の基準）"
    reference = [f"{_DOCS_SH}#1.1"]

    def formula_2025_01_01(人, period, parameters):
        比較 = parameters(period).健保.生計維持の比較.同一の世帯の収入の割合
        ratio = Fraction(int(比較.分子), int(比較.分母))
        被保険者の収入 = 人.健康保険.sum(人("健保_被保険者の年間収入", period) * 人.has_role(健康保険.被保険者))
        return np.array([half_threshold(int(x), ratio) for x in 被保険者の収入], dtype=np.int32)


class 健保_年間収入が同一の世帯の比較の基準額未満か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "年間収入が被保険者の年間収入の2分の1未満か（同一の世帯のときの比較だけ。S52 記1 のただし書を含まない。境目の説明の判定）"
    reference = [f"{_DOCS_SH}#1.1"]

    def formula_2025_01_01(人, period):
        return 人("健保_年間収入", period) < 人("健保_同一の世帯の比較の基準額", period)


class 健保_仕送りの基準の下限額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "同一の世帯に属しないとき、仕送りの基準の型を満たす被保険者からの援助の年額の下限（境目の説明の基準。月額の型の上限の条件は含まない）"
    reference = [f"{_DOCS_SH}#1.1", f"{_DOCS_SA2}#2"]

    def formula_2025_01_01(人, period, parameters):
        rules = support_rules(parameters(period).健保.別居の仕送りの基準)
        rows = zip(人("健保_別居の仕送りの基準の型", period), 人("健保_年間収入", period), 人("健保_他の者からの援助の見込み額", period))
        out = [min(support_minimum(str(k) or SUPPORT_S52, int(i), int(o), rules), 2**31 - 1) for k, i, o in rows]
        return np.array(out, dtype=np.int32)


class 健保_援助による収入額が仕送りの基準の下限額以上か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "被保険者からの援助による収入額が仕送りの基準の下限額以上か（同一の世帯に属しないときの援助の側の比較だけ。境目の説明の判定）"
    reference = [f"{_DOCS_SH}#1.1", f"{_DOCS_SA2}#2"]

    def formula_2025_01_01(人, period):
        return 人("健保_援助による収入額", period) >= 人("健保_仕送りの基準の下限額", period)


class 健保_主として被保険者により生計を維持するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "主としてその被保険者により生計を維持するか（収入の基準・同一の世帯なら被保険者の収入の2分の1未満・別居なら仕送りの基準）"
    reference = [f"{_DOCS_SH}#1.1", f"{_DOCS_PSK}#2.3", f"{_DOCS_SA2}#2"]

    def formula_2025_01_01(人, period, parameters):
        比較 = parameters(period).健保.生計維持の比較.同一の世帯の収入の割合
        half = Fraction(int(比較.分子), int(比較.分母))
        rules = support_rules(parameters(period).健保.別居の仕送りの基準)
        被保険者の収入 = 人.健康保険.sum(人("健保_被保険者の年間収入", period) * 人.has_role(健康保険.被保険者))
        rows = zip(
            人("健保_年間収入", period),
            人("健保_収入の基準額", period),
            人("健保_実績による年額", period),
            人("健保_同一の世帯に属するか", period),
            被保険者の収入,
            人("健保_被保険者が生計維持の中心的役割を果たすか", period),
            人("健保_別居の仕送りの基準の型", period),
            人("健保_援助による収入額", period),
            人("健保_他の者からの援助の見込み額", period),
            人("健保_主たる扶養者でないか", period),
        )
        out = [
            livelihood(Livelihood(int(i), int(b), int(w), bool(s), int(ins), bool(c), str(k), int(sp), int(o), bool(n)), half, rules)
            for i, b, w, s, ins, c, k, sp, o, n in rows
        ]
        return np.array(out, dtype=bool) & 人.has_role(健康保険.被扶養者)


class 健保_被扶養者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定日に、届け出る被保険者の被扶養者に当たるか"
    reference = [f"{_DOCS_KY}#1.1", f"{_DOCS_PSK}#4.2"]

    def formula_2025_01_01(人, period):
        範囲 = 人("健保_被扶養者の範囲の親族か", period)
        同居不要 = 範囲 == "同居を要しない親族"
        同居要 = 範囲 == "同居を要する親族"
        続柄 = 同居不要 | (同居要 & 人("健保_同一の世帯に属するか", period))
        # 境目の説明の判定を直接の依存として読む（boundaries.undeclared）。収入の基準額未満は生計維持の必要条件（calc.livelihood）なので値に効かない。
        # 2分の1・援助の比較は、ただし書・型の条件があり単独では必要条件でないので値には使わない（生計維持は 健保_主として被保険者により生計を維持するか が決める）
        収入の基準 = 人("健保_年間収入が収入の基準額未満か", period)
        人("健保_年間収入が同一の世帯の比較の基準額未満か", period)
        人("健保_援助による収入額が仕送りの基準の下限額以上か", period)
        return (
            人.has_role(健康保険.被扶養者)
            & (人("健保_被保険者の制度", period) != "")
            & 続柄
            & 人("健保_国内居住の要件を満たすか", period)
            & ~人("健保_被扶養者から除かれる資格を有するか", period)
            & 収入の基準
            & 人("健保_主として被保険者により生計を維持するか", period)
        )


FACTS = (
    健保_判定日,
    健保_判定日の年齢,
    健保_判定日の属する年の12月31日の年齢,
    健保_障害を支給事由とする給付の受給要件に該当する程度の障害を有するか,
    健保_国内居住の要件を満たすか,
    健保_被扶養者の範囲の親族か,
    健保_同一の世帯に属するか,
    健保_被保険者の配偶者か,
    健保_被保険者の制度,
    健保_被扶養者から除かれる資格を有するか,
    健保_収入の見込みによる年間収入,
    健保_労働契約による判定を使うか,
    健保_労働契約による年間収入,
    健保_実績による年額,
    健保_被保険者本人の年間収入の見込み,
    健保_援助の見込み額,
    健保_他の者からの援助の見込み額,
    健保_別居の仕送りの基準の型,
    健保_主たる扶養者でないか,
    健保_被保険者が生計維持の中心的役割を果たすか,
)
VARIABLES = FACTS + (
    健保_収入の基準額,
    健保_配偶者の収入の基準額,
    健保_同一の世帯の収入の割合,
    健保_年間収入,
    健保_年間収入が収入の基準額未満か,
    健保_被保険者の年間収入,
    健保_援助による収入額,
    健保_同一の世帯の比較の基準額,
    健保_年間収入が同一の世帯の比較の基準額未満か,
    健保_仕送りの基準の下限額,
    健保_援助による収入額が仕送りの基準の下限額以上か,
    健保_主として被保険者により生計を維持するか,
    健保_被扶養者に当たるか,
)
