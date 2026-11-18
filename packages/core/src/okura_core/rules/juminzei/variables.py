"""規則モジュール juminzei の OpenFisca の変数（README.md §2・§4）。

- 年度 F の値は所得の年分 F−1 の situation で計算する。所得税の値（前年分）は同じ期間の変数を引く（制度をまたぐ依存）。
- 扶養・配偶者・障害者・寡婦・ひとり親・勤労学生に当たるかは、所得税の判定（同じ situation の前年分）をそのまま使う
  （地方税法の定義が所得税法と同じ形で、所得の年で見れば額も同じ。違いは分離課税の退職所得だけで、段の検出が対象外にする：allocation.py）。
- 金額は整数の円。途中の値は calc.py の Fraction。根拠のない1円未満は RoundingSlotSpec の候補（式は端数が出る人がいるときだけ候補を引く）。
"""

from __future__ import annotations

from collections.abc import Iterable
from fractions import Fraction
from typing import Any

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物, 住民税扶養所属
from ...money import INT32_MAX
from ...rounding import FUNCTIONS
from . import calc

_LAW = "docs/public-sources/20261109_round2_juminzei-tax-law-text.md"
_PSJ = "docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md"
_EXTRA = "docs/public-sources/20261109_round3_juminzei-extra-law-text.md"
_R1 = "docs/public-sources/20261109_R1-laws_local-tax.md"
_SPOUSE = "docs/public-sources/20261109_round2_spouse-laws-and-sources.md"
_JINTEKI = "docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md"
_HOKEN = "docs/public-sources/20261109_round2_hoken-kifu-laws.md"
_TAISHOKU = "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md"
_SOCHI = "docs/public-sources/20261109_round3_chiho-sochi-law-and-notices.md"
_JM3 = "docs/public-sources/20261111_impl-research3_juminzei-laws-and-soumu.md"
_JZ = "docs/public-sources/20261112_impl-research5_juminzei-zasson-and-46-5.md"
_KIFU4 = "docs/public-sources/20261112_impl-research4_juminzei-kifu-laws-and-kokuji.md"
_FKIFU = "docs/public-sources/20261112_impl-research6_forms-jumin-kifu.md"
_PS8 = "docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md"


def _yen(values: Iterable[Any], what: str) -> np.ndarray:
    """整数の円の配列（int32）。int32 を超える値は、int32 を超える入力からしか生じない（evaluate はその入力を OpenFisca に渡さず対象外にする：
    packages/core/README.md §5）ので、端で止める（構造の検査の架空の大きな入力で式が落ちないため）。what は読み手のための名前。"""
    del what
    arr = np.array([int(v) for v in values], dtype=np.int64)
    return np.clip(arr, -INT32_MAX, INT32_MAX).astype(np.int32)


def _rounded(exact: list[Fraction], candidates: Any) -> np.ndarray:
    """有理数の額を、根拠のない端数の候補（floor・ceil・half_up）で人ごとに丸める。candidates は候補の名前の配列。"""
    return _yen((FUNCTIONS[str(c)](x) if Fraction(x).denominator != 1 else int(x) for x, c in zip(exact, candidates)), "端数を丸めた額")


def _input(name: str, value_type: type, label: str, refs: list[str], default: Any = None) -> type:
    attrs: dict[str, Any] = {
        "value_type": value_type,
        "entity": 人物,
        "definition_period": YEAR,
        "label": label,
        "reference": refs,
    }
    if default is not None:
        attrs["default_value"] = default
    return type(name, (Variable,), attrs)


# ---------------------------------------------------------------------------
# 事実（入力変数。inputs.py の build_inputs と allocation.py の段が書く）
# ---------------------------------------------------------------------------

INPUTS: tuple[type, ...] = (
    _input("住民税_賦課期日に住所を有する市町村", str, "賦課期日（年度の初日の属する年の1月1日）に住所を有する市町村の団体コード（なければ「なし」：calc.NO_DOMICILE）", [f"{_EXTRA}#1.3", f"{_PSJ}#3.1"], calc.NO_DOMICILE),
    _input("住民税_家屋敷課税の対象か", bool, "住所を有しない市町村内に事務所・事業所・家屋敷を有するか（賦課期日。判断.家屋敷・事務所に当たる）", [f"{_EXTRA}#1.1", f"{_EXTRA}#1.2"]),
    _input("住民税_生活扶助を受けているか", bool, "賦課期日に生活保護法の生活扶助を受けているか（第295条第1項第1号）", [f"{_PSJ}#3.1", f"{_PSJ}#3.2"]),
    # 2026-11-12（JM-40）：市町村民税の減免の承認（第323条・第45条。authority_decision の reduction_approved・税目 resident_tax）
    _input(
        "住民税_減免の承認があるか",
        bool,
        "その年度の住民税の減免の承認（市町村長の個別の処分。地方税法第323条・第45条）があるか（税額は減免の前の額）",
        ["docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md#8"],
    ),
    _input("住民税_非課税の判定を賦課期日の現況で行うか", bool, "第295条第1項第2号の障害者・寡婦・ひとり親を賦課期日の現況で判定するか（注入データ 住民税.135万円の非課税の判定の時点）", [f"{_PSJ}#3.2", f"{_PSJ}#3.3"]),
    _input("住民税_賦課期日の寡婦・ひとり親の判定が決まらないか", bool, "賦課期日の現況で判定する候補で、前年の12月31日に婚姻・事実婚が終わった（性別が変わった）人（分かれ目：一次情報）", [f"{_PSJ}#3.2"]),
    # 2026-11-12 の2回目（JM-41）：段 住民税の特定支出控除の申告（tokutei.py）が書く。地方税法第313条第11項・第32条第11項
    _input("住民税_住民税の申告書で特定支出控除を受けるか", bool, "前年分の所得税の納税義務がなく所得税で特定支出控除を受けない人が、住民税の申告書に適用を受ける旨と特定支出の額の合計額を記載したか（第313条第11項。段が書く）", [f"{_PS8}#6"]),
    _input("住民税_第313条第11項の給与所得の金額", int, "住民税の申告書だけで受ける特定支出控除の後の給与所得の金額（所得税法第57条の2第1項の例。当たらない人は0。段が書く）", [f"{_PS8}#6", f"{_PS8}#1"]),
    _input("住民税_第313条第11項の合計所得金額", int, "住民税の申告書だけで受ける特定支出控除の後の合計所得金額（損益通算の後・繰越控除の前。分離課税に係る退職所得を除く。当たらない人は0。段が書く）", [f"{_PS8}#6"]),
    _input("住民税_第313条第11項の損益通算の後の退職所得の金額", int, "住民税の申告書だけで受ける特定支出控除の後の損益通算の後の退職所得の金額（分離課税に係る退職所得の人・当たらない人は0。段が書く）", [f"{_PS8}#6"]),
    _input("住民税_分離課税の退職所得の区分が決まらないか", bool,"源泉徴収の対象の退職手当等とそれ以外の退職手当等が両方ある（分離課税と総合課税に分ける計算の一次情報がない：分かれ目。JM-19）", [f"{_TAISHOKU}#6.3"]),
    _input("住民税_未成年者か", bool, "第295条第1項第2号の未成年者か（年齢18歳未満。判定の時点は注入データ 住民税.135万円の非課税の判定の時点）", [f"{_PSJ}#3.1", f"{_PSJ}#3.2"]),
    _input("住民税_指定都市の区域内に住所を有するか", bool, "賦課期日の住所が指定都市の区域内か（注入データ 住民税.所得割の税率 の 指定都市）", [f"{_LAW}#4"]),
    _input("住民税_市町村民税の所得割の税率の分子", int, "市町村民税の所得割の税率の分子（注入データ。未注入なら値は未確定）", [f"{_LAW}#4"], 0),
    _input("住民税_市町村民税の所得割の税率の分母", int, "市町村民税の所得割の税率の分母", [f"{_LAW}#4"], 1),
    _input("住民税_道府県民税の所得割の税率の分子", int, "道府県民税の所得割の税率の分子（指定都市の区域内か外かで選んだ率）", [f"{_LAW}#4"], 0),
    _input("住民税_道府県民税の所得割の税率の分母", int, "道府県民税の所得割の税率の分母", [f"{_LAW}#4"], 1),
    _input("住民税_市町村民税の均等割の税率", int, "市町村民税の均等割の税率（年額。注入データ）", [f"{_LAW}#13"]),
    _input("住民税_道府県民税の均等割の税率", int, "道府県民税の均等割の税率（年額。注入データ）", [f"{_LAW}#13"]),
    _input("住民税_均等割の非課税の基本額", int, "均等割を課さない者の基準の条例の基本額（注入データ。未注入なら政令の基準どおりの級地ごとの型）", [f"{_PSJ}#1.2", f"{_PSJ}#1.4"]),
    _input("住民税_均等割の非課税の加算額", int, "均等割を課さない者の基準の条例の加算額", [f"{_PSJ}#1.2", f"{_PSJ}#1.4"]),
    _input("住民税_森林環境税の非課税の基本額", int, "森林環境税の非課税の基準の基本額（35万円×級地の率。施行令第1条）", [f"{_LAW}#14"]),
    _input("住民税_森林環境税の非課税の加算額", int, "森林環境税の非課税の基準の加算額（21万円×級地の率）", [f"{_LAW}#14"]),
    _input("住民税_都道府県等に対する寄附金の額", int, "前年中に支出した都道府県・市町村・特別区に対する寄附金の額（第314条の7第1項第1号）", [f"{_LAW}#8.1"]),
    _input("住民税_特例控除対象寄附金の額", int, "前年中に支出した特例控除対象寄附金の額（総務大臣の指定：注入データ 住民税.特例控除対象寄附金の指定）", [f"{_LAW}#8.1", f"{_LAW}#8.2"]),
    _input("住民税_市町村民税の第2号から第4号までの寄附金の額", int, "第314条の7第1項第2号（共同募金会・日本赤十字社）・第3号・第4号（市町村の条例で定めるもの）の寄附金の額", [f"{_LAW}#8.1", f"{_JM3}#1"]),
    _input("住民税_道府県民税の第2号から第4号までの寄附金の額", int, "第37条の2第1項第2号・第3号・第4号（道府県の条例で定めるもの）の寄附金の額", [f"{_LAW}#8.1", f"{_JM3}#1"]),
    _input(
        "住民税_第2号の寄附金の額",
        int,
        "第314条の7第1項第2号（第37条の2第1項第2号）の寄附金の額：賦課期日の住所の道府県内の共同募金会・日本赤十字社への寄附金（施行令第48条の8 → 第7条の17。市町村民税と道府県民税で同じ）",
        [f"{_LAW}#8.1", f"{_KIFU4}#1"],
    ),
    _input("住民税_申告特例控除の対象か", bool, "申告特例通知書の送付があり、なかったものとみなされない（附則第7条第8項〜第13項・第7条の2第4項）", [f"{_LAW}#8.3", f"{_HOKEN}#8.3"]),
    _input("住民税_控除の対象の配当割額等", int, "前年分の確定申告書に記載した特定配当等に課された配当割額・株式等譲渡所得割額（第314条の9）", [f"{_EXTRA}#2.1", f"{_EXTRA}#2.5"]),
    _input(
        "住民税_住宅借入金等特別税額控除の控除限度額に基礎控除の差を加算するか",
        bool,
        "居住年が平成28年〜令和7年で、控除限度の基に前年分の所得税の基礎控除の額−48万円を加算する（附則第5条の4第5項。令和8年以後の居住は加算しない）",
        [f"{_EXTRA}#3.2", f"{_EXTRA}#3.4"],
    ),
    _input("住民税_住宅借入金等特別税額控除の特定取得か", bool, "居住年が平成26年〜令和3年で、特定取得・特別特定取得の住宅借入金等がある（附則第5条の4第7項・第3項：控除限度の率・上限の読替え）", [f"{_EXTRA}#3.2"]),
    _input("住民税_軽減後の市町村民税の均等割の税率", int, "第311条の条例の軽減を当てた住所地の市町村民税の均等割の額（段階：住民税の均等割。軽減がなければ税率）", [f"{_LAW}#13"], 0),
    _input("住民税_家屋敷課税の均等割の額", int, "家屋敷課税の均等割の額（住所のない市町村ごとの市町村民税・道府県民税の均等割の合計。段階：住民税の均等割）", [f"{_EXTRA}#1.1", f"{_EXTRA}#1.5", f"{_EXTRA}#1.7"], 0),
    _input("住民税_上場株式等に係る配当所得等の金額から控除する所得控除の額", int, "総所得金額から引ききれない所得控除のうち、上場株式等に係る配当所得等の金額から控除する額（段階：住民税の分離課税の所得への所得控除）", [f"{_JM3}#3"], 0),
    _input("住民税_上場株式等に係る譲渡所得等の金額から控除する所得控除の額", int, "総所得金額から引ききれない所得控除のうち、上場株式等に係る譲渡所得等の金額から控除する額（同）", [f"{_JM3}#3"], 0),
    _input("住民税_扶養費の一部を負担しているか", bool, "離婚した人が、他の納税義務者の扶養親族とされている扶養親族の扶養費の一部を負担しているか（判断.扶養費の一部負担。非課税の判定の寡婦だけに使う）", [f"{_JINTEKI}#2.5"]),
    _input("住民税_法令上の性別が女性か", bool, "前年の12月31日の法令上の性別が女性か（調整控除のひとり親の父・母：施行令第48条の7の2）", [f"{_LAW}#5"]),
    _input("住民税_退職手当等の支払を受けるべき年の1月1日に住所を有する市町村", str, "分離課税に係る所得割を課する市町村（退職手当等の支払を受けるべき日の属する年の1月1日の住所：第328条）", [f"{_LAW}#12", f"{_TAISHOKU}#6.3"], ""),
    _input("住民税_退職手当等の支払を受けるべき年の1月1日に生活扶助を受けているか", bool, "第295条第1項第1号・第2項（分離課税に係る所得割の生活扶助の判定の時点）", [f"{_PSJ}#3.1"]),
    _input("住民税_生命保険料控除の端数の候補", str, "生命保険料控除の区分ごとの額の1円未満の端数の候補（根拠なし：D22 S3）", [f"{_HOKEN}#9"], ""),
    _input("住民税_地震保険料控除の端数の候補", str, "地震保険料控除の1円未満の端数の候補（根拠なし）", [f"{_HOKEN}#9"], ""),
    _input("住民税_医療費控除の足切りの端数の候補", str, "前年の総所得金額等の5%の1円未満の端数の候補（根拠なし）", [f"{_LAW}#15"], ""),
    _input("住民税_雑損控除の足切りの端数の候補", str, "前年の総所得金額等の1/10の1円未満の端数の候補（根拠なし）", [f"{_LAW}#15"], ""),
    _input("住民税_税額控除の額の端数の候補", str, "税額控除の額（表示する値）の1円未満の端数の候補（根拠なし。所得割の額は有理数のまま計算する）", [f"{_LAW}#15"], ""),
    _input(
        "住民税_課税標準の千円未満の切捨ての当て先の読み",
        str,
        "課税標準額の千円未満の切捨ての当て先の読みの候補（JT1。ReadingSlotSpec：evaluate が候補の名前を入れる。既定は控除後）",
        [f"{_LAW}#15", f"{_LAW}#16"],
        "控除後の課税総所得金額等",
    ),
    _input("住民税_連鎖の扶養親族の扶養控除の額", int, "自分も納税義務者である扶養親族（扶養の連鎖）の分の扶養控除の額（段階：住民税の扶養の割当て）", [f"{_PSJ}#4.1"], 0),
    _input("住民税_連鎖の扶養親族の特定親族特別控除の額", int, "扶養の連鎖の人の分の特定親族特別控除の額", [f"{_PSJ}#4.1"], 0),
    _input("住民税_連鎖の扶養親族の障害者控除の額", int, "扶養の連鎖の人の分の障害者控除の額", [f"{_PSJ}#4.1"], 0),
    _input("住民税_連鎖の扶養親族の人的控除差の額", int, "扶養の連鎖の人の分の調整控除の人的控除差", [f"{_PSJ}#4.1"], 0),
    _input("住民税_連鎖の非課税の判定で数える扶養親族の数", int, "扶養の連鎖の人のうち非課税の判定で数える扶養親族の数", [f"{_PSJ}#4.1"], 0),
    # 住民税の扶養の割当て（2026-11-12。段 住民税の扶養の割当て が書く：地令46の3〜46の5。README JM-24〜26）
    _input("住民税_扶養親族等の納税義務者", str, "住民税の扶養親族等（扶養親族・特定親族）とする納税義務者（なければ空。地令第46条の5）", [f"{_PSJ}#4.2"], ""),
    _input("住民税_連鎖の扶養親族等か", bool, "住民税の扶養親族等で、自分も納税義務者として扶養親族等を有するか（扶養の連鎖）", [f"{_PSJ}#4.1"]),
    _input("住民税_扶養の判定を所得税と別に行うか", bool, "扶養親族等・配偶者として判定される人の住民税の割当て・合計所得金額・判定の時が所得税と違うか（違えば 住民税_別の判定の… を使う）", [f"{_PSJ}#4.2", f"{_TAISHOKU}#6.3"]),
    _input("住民税_本人の判定を所得税と別に行うか", bool, "納税義務者本人の住民税の合計所得金額・扶養親族等・配偶者が所得税と違うか（違えば 住民税_別の判定の… を使う）", [f"{_PSJ}#4.2", f"{_TAISHOKU}#6.3"]),
    _input("住民税_別の判定の扶養親族等とされているか", bool, "住民税の割当てで他の納税義務者の扶養親族等とされているか", [f"{_PSJ}#4.2"]),
    _input("住民税_別の判定の扶養親族か", bool, "住民税の扶養親族か（第292条第1項第9号：住民税の合計所得金額）", [f"{_PSJ}#5"]),
    _input("住民税_別の判定の控除対象扶養親族か", bool, "住民税の控除対象扶養親族か（第314条の2第1項第11号）", [f"{_PSJ}#5"]),
    _input("住民税_別の判定の特定扶養親族か", bool, "住民税の特定扶養親族か", [f"{_PSJ}#5"]),
    _input("住民税_別の判定の老人扶養親族か", bool, "住民税の老人扶養親族か", [f"{_PSJ}#5"]),
    _input("住民税_別の判定の同居老親等か", bool, "住民税の同居老親等か（第314条の2第4項）", [f"{_PSJ}#5"]),
    _input("住民税_別の判定の特定親族か", bool, "住民税の特定親族か（第314条の2第1項第12号）", [f"{_PSJ}#5"]),
    _input("住民税_別の判定の同居特別障害者か", bool, "住民税の同居特別障害者か（第314条の2第3項。扶養親族として、又は相手の同一生計配偶者として）", [f"{_JINTEKI}#2.3"]),
    _input("住民税_別の判定の障害者か", bool, "判定の時（前年の12月31日）に障害者に当たるか", [f"{_JINTEKI}#2.1"]),
    _input("住民税_別の判定の特別障害者か", bool, "判定の時（前年の12月31日）に特別障害者に当たるか", [f"{_JINTEKI}#2.2"]),
    _input("住民税_別の判定の同一生計配偶者に当たるか", bool, "住民税の同一生計配偶者か（本人から見た配偶者について。第292条第1項第7号）", [f"{_SPOUSE}#3.1"]),
    _input("住民税_別の判定の寡婦か", bool, "住民税の寡婦か（第292条第1項第11号：住民税の合計所得金額・扶養親族）", [f"{_JINTEKI}#2.1"]),
    _input("住民税_別の判定のひとり親か", bool, "住民税のひとり親か（第292条第1項第12号）", [f"{_JINTEKI}#2.1"]),
    _input("住民税_別の判定の勤労学生か", bool, "住民税の勤労学生か（第314条の2第9項）", [f"{_PSJ}#5"]),
    # 住民税の雑損失の繰越（2026-11-12。第313条第9項・施行令第48条の3。JM-32：docs/public-sources/20261112_impl-research5_juminzei-zasson-and-46-5.md §1）
    _input("住民税_雑損失の繰越の記録があるか", bool, "前年度分の住民税の所得割の計算で控除しきれず繰り越す雑損失の金額の記録（reported_amounts の resident_tax_casualty_loss_carryforward）があるか", [f"{_JZ}#1"]),
    _input("住民税_記録による繰り越された雑損失の金額", int, "前年前3年内に生じ、前年度までに控除されなかった住民税の雑損失の金額（前年度の記録。第313条第9項）", [f"{_JZ}#1"], 0),
    _input("住民税_純損失の繰越の記録があるか", bool, "前年度分の住民税の所得割の計算で控除しきれず繰り越す純損失の金額の記録（reported_amounts の resident_tax_net_loss_carryforward）があるか", [f"{_JZ}#1"]),
    _input("住民税_記録による繰り越された純損失の金額", int, "前年前3年間に生じ、前年度までに控除されなかった住民税の純損失の金額（前年度の記録。第313条第8項・第9項）", [f"{_JZ}#1"], 0),
)


# ---------------------------------------------------------------------------
# 住民税の扶養・人的控除の判定（2026-11-12。README JM-24〜26）：所得税と同じ人は所得税の判定、違う人は段が書いた住民税の判定
# ---------------------------------------------------------------------------


class 住民税_扶養親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の扶養親族に当たるか（第292条第1項第9号。所得税と割当て・合計所得金額が同じなら所得税の判定）"
    reference = [f"{_PSJ}#5", f"{_PSJ}#4.2"]

    def formula(人, period, parameters):
        return np.where(人("住民税_扶養の判定を所得税と別に行うか", period), 人("住民税_別の判定の扶養親族か", period), 人("所得税_扶養親族に当たるか", period))


class 住民税_控除対象扶養親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の控除対象扶養親族に当たるか（第314条の2第1項第11号）"
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        return np.where(人("住民税_扶養の判定を所得税と別に行うか", period), 人("住民税_別の判定の控除対象扶養親族か", period), 人("所得税_控除対象扶養親族に当たるか", period))


class 住民税_特定扶養親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の特定扶養親族に当たるか（19歳以上23歳未満）"
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        return np.where(人("住民税_扶養の判定を所得税と別に行うか", period), 人("住民税_別の判定の特定扶養親族か", period), 人("所得税_特定扶養親族に当たるか", period))


class 住民税_老人扶養親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の老人扶養親族に当たるか（70歳以上）"
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        return np.where(人("住民税_扶養の判定を所得税と別に行うか", period), 人("住民税_別の判定の老人扶養親族か", period), 人("所得税_老人扶養親族に当たるか", period))


class 住民税_同居老親等に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の同居老親等に当たるか（第314条の2第4項）"
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        return np.where(人("住民税_扶養の判定を所得税と別に行うか", period), 人("住民税_別の判定の同居老親等か", period), 人("所得税_同居老親等に当たるか", period))


class 住民税_特定親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の特定親族に当たるか（第314条の2第1項第12号）"
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        return np.where(人("住民税_扶養の判定を所得税と別に行うか", period), 人("住民税_別の判定の特定親族か", period), 人("所得税_特定親族に当たるか", period))


class 住民税_同居特別障害者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の同居特別障害者に当たるか（第314条の2第3項。障害者である本人の側）"
    reference = [f"{_JINTEKI}#2.3"]

    def formula(人, period, parameters):
        return np.where(人("住民税_扶養の判定を所得税と別に行うか", period), 人("住民税_別の判定の同居特別障害者か", period), 人("所得税_同居特別障害者に当たるか", period))


class 住民税_扶養等の判定に使う障害者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養親族等・配偶者として判定されるときに障害者に当たるか（判定の時の現況）"
    reference = [f"{_JINTEKI}#2.1"]

    def formula(人, period, parameters):
        return np.where(人("住民税_扶養の判定を所得税と別に行うか", period), 人("住民税_別の判定の障害者か", period), 人("所得税_扶養等の判定に使う障害者か", period))


class 住民税_扶養等の判定に使う特別障害者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養親族等・配偶者として判定されるときに特別障害者に当たるか（判定の時の現況）"
    reference = [f"{_JINTEKI}#2.2"]

    def formula(人, period, parameters):
        return np.where(人("住民税_扶養の判定を所得税と別に行うか", period), 人("住民税_別の判定の特別障害者か", period), 人("所得税_扶養等の判定に使う特別障害者か", period))


class 住民税_他の納税義務者の扶養親族等とされているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の割当てで他の納税義務者の扶養親族等とされているか（地令第46条の3〜第46条の5）"
    reference = [f"{_PSJ}#4.2"]

    def formula(人, period, parameters):
        return np.where(
            人("住民税_扶養の判定を所得税と別に行うか", period),
            人("住民税_別の判定の扶養親族等とされているか", period),
            人("所得税_他の居住者の扶養親族等とされているか", period),
        )


class 住民税_同一生計配偶者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の同一生計配偶者に当たるか（本人から見た配偶者について。第292条第1項第7号）"
    reference = [f"{_SPOUSE}#3.1"]

    def formula(人, period, parameters):
        return np.where(人("住民税_本人の判定を所得税と別に行うか", period), 人("住民税_別の判定の同一生計配偶者に当たるか", period), 人("所得税_同一生計配偶者に当たるか", period))


class 住民税_寡婦に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の寡婦に当たるか（第292条第1項第11号）"
    reference = [f"{_JINTEKI}#2.1"]

    def formula(人, period, parameters):
        return np.where(人("住民税_本人の判定を所得税と別に行うか", period), 人("住民税_別の判定の寡婦か", period), 人("所得税_寡婦に当たるか", period))


class 住民税_ひとり親に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税のひとり親に当たるか（第292条第1項第12号）"
    reference = [f"{_JINTEKI}#2.1"]

    def formula(人, period, parameters):
        return np.where(人("住民税_本人の判定を所得税と別に行うか", period), 人("住民税_別の判定のひとり親か", period), 人("所得税_ひとり親に当たるか", period))


class 住民税_勤労学生に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の勤労学生に当たるか（第314条の2第9項）"
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        return np.where(人("住民税_本人の判定を所得税と別に行うか", period), 人("住民税_別の判定の勤労学生か", period), 人("所得税_勤労学生に当たるか", period))


JUDGMENT_VIEWS: tuple[type, ...] = (
    住民税_扶養親族に当たるか,
    住民税_控除対象扶養親族に当たるか,
    住民税_特定扶養親族に当たるか,
    住民税_老人扶養親族に当たるか,
    住民税_同居老親等に当たるか,
    住民税_特定親族に当たるか,
    住民税_同居特別障害者に当たるか,
    住民税_扶養等の判定に使う障害者か,
    住民税_扶養等の判定に使う特別障害者か,
    住民税_他の納税義務者の扶養親族等とされているか,
    住民税_同一生計配偶者に当たるか,
    住民税_寡婦に当たるか,
    住民税_ひとり親に当たるか,
    住民税_勤労学生に当たるか,
)


# ---------------------------------------------------------------------------
# 中心の概念（前年の所得）
# ---------------------------------------------------------------------------


class 住民税_分離課税に係る退職所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "所得税の源泉徴収の対象となる退職手当等の退職所得の金額（第328条・第328条の2：所得税法第30条の計算の例。他の所得と区分し、損益通算・繰越控除を当てない）"
    reference = [f"{_TAISHOKU}#6.1", f"{_TAISHOKU}#6.3", f"{_LAW}#12"]

    def formula(人, period, parameters):
        # 源泉徴収の対象の退職手当等とそれ以外が両方ある人は分かれ目（一次情報：inputs._retirement_split。JM-19）
        混在 = 人("住民税_分離課税の退職所得の区分が決まらないか", period)
        return np.where(人("所得税_退職手当等の全部が源泉徴収の対象か", period) & ~混在, 人("所得税_退職所得の金額", period), 0)


class 住民税_合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の合計所得金額（第292条第1項第13号。所得税の合計所得金額から分離課税に係る退職所得の金額を除く）"
    reference = [f"{_LAW}#2", f"{_TAISHOKU}#6.3", f"{_R1}#2"]

    def formula(人, period, parameters):
        # 分離課税に係る退職所得がある人：損益通算・公的年金等控除額の区分をその退職所得がないものとして計算した額（income_totals の窓口。JM-20・JM-23）
        分離 = 人("住民税_分離課税に係る退職所得の金額", period) > 0
        元 = np.where(分離, 人("所得税_分離課税の退職所得を除いた合計所得金額", period), 人("所得税_合計所得金額", period))
        # 住民税の申告書だけで受ける特定支出控除（第313条第11項。JM-41）：段 住民税の特定支出控除の申告 が計算した額
        return np.where(人("住民税_住民税の申告書で特定支出控除を受けるか", period), 人("住民税_第313条第11項の合計所得金額", period), 元)


class 住民税_繰り越された雑損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "前年前3年内に生じ、前年度までに控除されなかった住民税の雑損失の金額（第313条第9項）。前年度の記録がなければ所得税の繰り越された雑損失の金額"
        "（法令の読み：basis.JUMIN_CASUALTY_FALLBACK）"
    )
    reference = [f"{_JZ}#1"]

    def formula(人, period):
        return np.where(
            人("住民税_雑損失の繰越の記録があるか", period), 人("住民税_記録による繰り越された雑損失の金額", period), 人("所得税_繰り越された雑損失の金額", period)
        ).astype(np.int32)


class 住民税_繰り越された純損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "前年前3年間に生じ、前年度までに控除されなかった住民税の純損失の金額（第313条第8項・第9項）。前年度の記録がなければ所得税の繰り越された純損失の金額"
        "（法令の読み：basis.JUMIN_CASUALTY_FALLBACK）"
    )
    reference = [f"{_JZ}#1"]

    def formula(人, period):
        return np.where(
            人("住民税_純損失の繰越の記録があるか", period), 人("住民税_記録による繰り越された純損失の金額", period), 人("所得税_繰り越された純損失の金額", period)
        ).astype(np.int32)


class 住民税_損失の繰越が所得税と違うか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民税の繰り越された雑損失・純損失の金額が所得税の繰り越された金額と違うか（違えば住民税の前年の所得を住民税の繰越で計算し直す）"
    reference = [f"{_JZ}#1"]

    def formula(人, period):
        雑 = 人("住民税_繰り越された雑損失の金額", period) != 人("所得税_繰り越された雑損失の金額", period)
        純 = 人("住民税_繰り越された純損失の金額", period) != 人("所得税_繰り越された純損失の金額", period)
        return 雑 | 純


def _casualty_rows(分離額, 合計_住, 合計_所, 退職額, 配当, 譲渡, 通算, 上場繰越, 純損失, 雑損失, 特定, 退職_特定):  # noqa: ANN001, ANN202
    """住民税の雑損失の繰越控除（calc.jumin_casualty_carryforward）を人ごとに。分離課税に係る退職所得のある人は住民税の合計所得金額（退職所得を除く）から。
    住民税の申告書だけで特定支出控除を受ける人（第313条第11項。JM-41）は住民税の合計所得金額と、段が書いた損益通算の後の退職所得の金額から。
    引数は式の中で引いた値（式の依存を静的に読めるように、各式が 人("…") で引いて渡す）。"""
    分離 = np.asarray(分離額) > 0
    特定 = np.asarray(特定, dtype=bool)
    合計 = np.where(分離 | 特定, 合計_住, 合計_所)
    退職 = np.where(分離, 0, np.where(特定, 退職_特定, 退職額))
    return [
        calc.jumin_casualty_carryforward(int(t), int(r), int(d), int(g), bool(o), int(lc), int(n), int(c))
        for t, r, d, g, o, lc, n, c in zip(合計, 退職, 配当, 譲渡, 通算, 上場繰越, 純損失, 雑損失)
    ]


class 住民税_雑損失の繰越控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の所得の計算で控除した住民税の雑損失の繰越控除の額（第313条第9項・施行令第48条の3。国保・国年の窓口）"
    reference = [f"{_LAW}#2", f"{_JZ}#1"]

    def formula(人, period):
        所得税 = 人("所得税_雑損失の繰越控除額", period)
        別 = (
            人("住民税_損失の繰越が所得税と違うか", period)
            | (人("住民税_分離課税に係る退職所得の金額", period) > 0)
            | 人("住民税_住民税の申告書で特定支出控除を受けるか", period)
        )
        if not np.any(別 & (人("住民税_繰り越された雑損失の金額", period) > 0)):
            return 所得税
        rows = _casualty_rows(
            人("住民税_分離課税に係る退職所得の金額", period), 人("住民税_合計所得金額", period), 人("所得税_合計所得金額", period),
            人("所得税_損益通算の後の退職所得の金額", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_上場株式等の譲渡損失の繰越控除額", period), 人("住民税_繰り越された純損失の金額", period), 人("住民税_繰り越された雑損失の金額", period),
            人("住民税_住民税の申告書で特定支出控除を受けるか", period), 人("住民税_第313条第11項の損益通算の後の退職所得の金額", period),
        )  # fmt: skip
        return np.where(別, _yen((x.deducted for x in rows), "住民税の雑損失の繰越控除額"), 所得税).astype(np.int32)


class 住民税_雑損失の繰越控除の後の総所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の総所得金額（繰越控除の後。退職所得を含まない。分離課税に係る退職所得のある人は退職所得がないものとした額。住民税の雑損失の繰越で計算する）"
    reference = [f"{_LAW}#2", f"{_JZ}#1"]

    def formula(人, period):
        分離 = 人("住民税_分離課税に係る退職所得の金額", period) > 0
        元 = np.where(分離, 人("所得税_分離課税の退職所得を除いた総所得金額", period), 人("所得税_総所得金額", period))
        違う = 人("住民税_損失の繰越が所得税と違うか", period) | 人("住民税_住民税の申告書で特定支出控除を受けるか", period)  # JM-32・JM-41
        if not np.any(違う):
            return 元.astype(np.int32)
        rows = _casualty_rows(
            人("住民税_分離課税に係る退職所得の金額", period), 人("住民税_合計所得金額", period), 人("所得税_合計所得金額", period),
            人("所得税_損益通算の後の退職所得の金額", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_上場株式等の譲渡損失の繰越控除額", period), 人("住民税_繰り越された純損失の金額", period), 人("住民税_繰り越された雑損失の金額", period),
            人("住民税_住民税の申告書で特定支出控除を受けるか", period), 人("住民税_第313条第11項の損益通算の後の退職所得の金額", period),
        )  # fmt: skip
        return np.where(違う, _yen((x.total for x in rows), "総所得金額"), 元).astype(np.int32)


class 住民税_雑損失の繰越控除の後の上場株式等に係る配当所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の申告分離課税の上場株式等に係る配当所得等の金額（繰越控除の後。住民税の雑損失の繰越で計算する）"
    reference = [f"{_LAW}#2", f"{_JZ}#1"]

    def formula(人, period):
        元 = 人("所得税_申告分離課税の上場株式等に係る配当所得等の金額", period)
        違う = 人("住民税_損失の繰越が所得税と違うか", period) | 人("住民税_住民税の申告書で特定支出控除を受けるか", period)  # JM-32・JM-41
        if not np.any(違う):
            return 元
        rows = _casualty_rows(
            人("住民税_分離課税に係る退職所得の金額", period), 人("住民税_合計所得金額", period), 人("所得税_合計所得金額", period),
            人("所得税_損益通算の後の退職所得の金額", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_上場株式等の譲渡損失の繰越控除額", period), 人("住民税_繰り越された純損失の金額", period), 人("住民税_繰り越された雑損失の金額", period),
            人("住民税_住民税の申告書で特定支出控除を受けるか", period), 人("住民税_第313条第11項の損益通算の後の退職所得の金額", period),
        )  # fmt: skip
        return np.where(違う, _yen((x.dividend for x in rows), "上場株式等に係る配当所得等の金額"), 元).astype(np.int32)


class 住民税_雑損失の繰越控除の後の上場株式等に係る譲渡所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の申告分離課税の上場株式等に係る譲渡所得等の金額（繰越控除の後。住民税の雑損失の繰越で計算する）"
    reference = [f"{_LAW}#2", f"{_JZ}#1"]

    def formula(人, period):
        元 = 人("所得税_申告分離課税の上場株式等に係る譲渡所得等の金額", period)
        違う = 人("住民税_損失の繰越が所得税と違うか", period) | 人("住民税_住民税の申告書で特定支出控除を受けるか", period)  # JM-32・JM-41
        if not np.any(違う):
            return 元
        rows = _casualty_rows(
            人("住民税_分離課税に係る退職所得の金額", period), 人("住民税_合計所得金額", period), 人("所得税_合計所得金額", period),
            人("所得税_損益通算の後の退職所得の金額", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_上場株式等の譲渡損失の繰越控除額", period), 人("住民税_繰り越された純損失の金額", period), 人("住民税_繰り越された雑損失の金額", period),
            人("住民税_住民税の申告書で特定支出控除を受けるか", period), 人("住民税_第313条第11項の損益通算の後の退職所得の金額", period),
        )  # fmt: skip
        return np.where(違う, _yen((x.gain for x in rows), "上場株式等に係る譲渡所得等の金額"), 元).astype(np.int32)


class 住民税_事業専従者給与等の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の青色事業専従者給与の額と事業専従者控除の額の合計（国保・国年の窓口）"
    reference = [f"{_LAW}#2"]

    def formula(人, period):
        return 人("所得税_青色事業専従者給与の額", period) + 人("所得税_事業専従者控除額", period)


class 住民税_上場株式等に係る分離課税の所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の上場株式等に係る配当所得等の金額と譲渡所得等の金額の合計（国保・国年の窓口。住民税の雑損失の繰越控除の後）"
    reference = [f"{_LAW}#2", f"{_JZ}#1"]

    def formula(人, period):
        return 人("住民税_雑損失の繰越控除の後の上場株式等に係る配当所得等の金額", period) + 人("住民税_雑損失の繰越控除の後の上場株式等に係る譲渡所得等の金額", period)


class 住民税_上場株式等の譲渡損失の繰越控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の上場株式等に係る譲渡損失の繰越控除の額（国保・国年の窓口）"
    reference = [f"{_LAW}#2"]

    def formula(人, period):
        return 人("所得税_上場株式等の譲渡損失の繰越控除額", period)


class 住民税_総所得金額等に含まれる退職所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の退職所得金額のうち分離課税に係る退職所得でないもの（国保・国年の窓口。住民税の申告書だけで特定支出控除を受ける人は損益通算・繰越控除をし直した額）"
    reference = [f"{_LAW}#2", f"{_PS8}#6"]

    def formula(人, period):
        全部 = 人("所得税_退職手当等の全部が源泉徴収の対象か", period) & ~人("住民税_分離課税の退職所得の区分が決まらないか", period)
        元 = np.where(全部, 0, 人("所得税_退職所得金額", period)).astype(np.int32)
        特定 = 人("住民税_住民税の申告書で特定支出控除を受けるか", period) & ~全部  # 第313条第11項（JM-41）
        if not np.any(特定):
            return 元
        rows = _casualty_rows(
            人("住民税_分離課税に係る退職所得の金額", period), 人("住民税_合計所得金額", period), 人("所得税_合計所得金額", period),
            人("所得税_損益通算の後の退職所得の金額", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_上場株式等の譲渡損失の繰越控除額", period), 人("住民税_繰り越された純損失の金額", period), 人("住民税_繰り越された雑損失の金額", period),
            人("住民税_住民税の申告書で特定支出控除を受けるか", period), 人("住民税_第313条第11項の損益通算の後の退職所得の金額", period),
        )  # fmt: skip
        return np.where(特定, _yen((x.retirement for x in rows), "退職所得金額"), 元).astype(np.int32)


class 住民税_公的年金等に係る所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の公的年金等に係る雑所得の金額（国保・国年の窓口）"
    reference = [f"{_LAW}#2"]

    def formula(人, period):
        分離 = 人("住民税_分離課税に係る退職所得の金額", period) > 0  # 公的年金等控除額の区分を分離課税に係る退職所得を除いて求める（JM-23）
        return np.where(分離, 人("所得税_退職所得を除いた区分による公的年金等に係る雑所得の金額", period), 人("所得税_公的年金等に係る雑所得の金額", period))


class 住民税_65歳以上の者に係る公的年金等控除額の控除を受けたか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "前年中に年齢65歳以上である者に係る公的年金等控除額の控除を受けたか（国保・国年の窓口）"
    reference = [f"{_LAW}#2"]

    def formula(人, period):
        return 人("所得税_65歳以上の者に係る公的年金等控除額の控除を受けたか", period)


class 住民税_給与等の収入金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の給与等の収入金額（国保・国年の窓口）"
    reference = [f"{_LAW}#2"]

    def formula(人, period):
        return 人("所得税_給与等の収入金額", period)


class 住民税_公的年金等の収入金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の公的年金等の収入金額（国保・国年の窓口）"
    reference = [f"{_LAW}#2"]

    def formula(人, period):
        return 人("所得税_公的年金等の収入金額", period)


class 住民税_給与所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の給与所得の金額（所得税法第28条第2項。住民税の申告書だけで特定支出控除を受ける人は第313条第11項の額。国保・国年の窓口）"
    reference = [f"{_LAW}#2", f"{_PS8}#6"]

    def formula(人, period):
        return np.where(人("住民税_住民税の申告書で特定支出控除を受けるか", period), 人("住民税_第313条第11項の給与所得の金額", period), 人("所得税_給与所得", period))


class 住民税_総所得金額等(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年の総所得金額・退職所得金額・山林所得金額の合計額（第313条第1項。繰越控除の後。分離課税に係る退職所得を除く）"
    reference = [f"{_LAW}#2", f"{_SOCHI}#1.1"]

    def formula(人, period, parameters):
        分離 = 人("住民税_分離課税に係る退職所得の金額", period) > 0
        元 = np.where(分離, 人("所得税_分離課税の退職所得を除いた総所得金額等", period), 人("所得税_総所得金額等", period))
        # 住民税の雑損失の繰越（第313条第9項。JM-32）・住民税の申告書だけで受ける特定支出控除（第313条第11項。JM-41）で計算し直す
        違う = 人("住民税_損失の繰越が所得税と違うか", period) | 人("住民税_住民税の申告書で特定支出控除を受けるか", period)
        if not np.any(違う):
            return 元
        rows = _casualty_rows(
            人("住民税_分離課税に係る退職所得の金額", period), 人("住民税_合計所得金額", period), 人("所得税_合計所得金額", period),
            人("所得税_損益通算の後の退職所得の金額", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_上場株式等の譲渡損失の繰越控除額", period), 人("住民税_繰り越された純損失の金額", period), 人("住民税_繰り越された雑損失の金額", period),
            人("住民税_住民税の申告書で特定支出控除を受けるか", period), 人("住民税_第313条第11項の損益通算の後の退職所得の金額", period),
        )  # fmt: skip
        return np.where(違う, _yen((x.total + x.dividend + x.gain + x.retirement for x in rows), "総所得金額等"), 元).astype(np.int32)


# ---------------------------------------------------------------------------
# 人的控除・扶養の判定（所得税の判定を使う）と非課税
# ---------------------------------------------------------------------------


class 住民税_非課税の判定で数える扶養親族か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "非課税の判定で数える扶養親族か（年齢16歳未満の者と控除対象扶養親族に限る。附則第3条の3第4項・施行令第47条の3第1号）"
    reference = [f"{_PSJ}#1.4", f"{_PSJ}#2.1"]

    def formula(人, period, parameters):
        上限 = parameters(period).住民税.非課税.数える扶養親族の年齢の上限
        return 人("住民税_扶養親族に当たるか", period) & ((人("所得税_年齢", period) < 上限) | 人("住民税_控除対象扶養親族に当たるか", period))


class 住民税_同一生計配偶者及び扶養親族の数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "非課税の判定で数える同一生計配偶者及び扶養親族の数（納税義務者の側）"
    reference = [f"{_PSJ}#1.2", f"{_PSJ}#2.1"]

    def formula(人, period, parameters):
        配偶者 = 人("住民税_同一生計配偶者に当たるか", period).astype(np.int64)
        扶養 = 人.住民税扶養所属.sum(人("住民税_非課税の判定で数える扶養親族か", period) * 人.has_role(住民税扶養所属.住民税の扶養親族等)) * 人.has_role(住民税扶養所属.納税義務者)
        return _yen(np.asarray(配偶者 + 扶養).round() + 人("住民税_連鎖の非課税の判定で数える扶養親族の数", period), "同一生計配偶者及び扶養親族の数")


class 住民税_第295条第1項の非課税に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "生活扶助を受けている者、又は障害者・未成年者・寡婦・ひとり親で前年の合計所得金額が135万円以下の者か（施行地に住所を有する者に限る）"
    reference = [f"{_R1}#4", f"{_PSJ}#3.1", f"{_JINTEKI}#2.4"]

    def formula(人, period, parameters):
        現況 = 人("住民税_非課税の判定を賦課期日の現況で行うか", period)
        障害 = np.where(現況, 人("所得税_翌年1月1日に障害者に当たるか", period), 人("所得税_障害者に当たるか", period))
        寡婦等 = 人("住民税_非課税の判定で寡婦に当たるか", period) | 人("住民税_ひとり親に当たるか", period)
        # 賦課期日に婚姻・事実婚が続いていれば寡婦・ひとり親に当たらない。前年の12月31日に婚姻が終わった人などは分かれ目（一次情報。inputs._minor）
        婚姻 = 現況 & 人("所得税_翌年1月1日に婚姻の状況が判定の時と違うか", period) & 人("所得税_翌年1月1日に婚姻又は事実婚をしているか", period)
        寡婦等 = np.where(婚姻 & ~人("住民税_賦課期日の寡婦・ひとり親の判定が決まらないか", period), False, 寡婦等)
        該当 = 障害 | 人("住民税_未成年者か", period) | 寡婦等
        住所 = _domiciled(人("住民税_賦課期日に住所を有する市町村", period))
        return 住所 & (人("住民税_生活扶助を受けているか", period) | (該当 & 人("住民税_第295条第1項の合計所得金額要件", period)))


class 住民税_非課税の判定で寡婦に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = (
        "第295条第1項第2号の非課税の判定の寡婦か（寡婦に当たるか、又は夫と離婚した後婚姻をしていない者で、扶養親族が他の納税義務者の扶養親族とされているが"
        "その扶養費の一部を負担している者：取扱通知 第2章第1節第1の3。所得の要件は 135万円 の要件で足りる）"
    )
    reference = [f"{_JINTEKI}#2.1", f"{_JINTEKI}#2.5"]

    def formula(人, period, parameters):
        取扱い = (
            人("住民税_扶養費の一部を負担しているか", period)
            & 人("所得税_夫と離婚した後婚姻をしていない者か", period)
            & ~人("所得税_配偶者がいるか", period)
            & ~人("所得税_住民票に事実婚の続柄の記載がある相手がいるか", period)
            & ~人("住民税_ひとり親に当たるか", period)
        )
        return 人("住民税_寡婦に当たるか", period) | 取扱い


class 住民税_第295条第1項の合計所得金額要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "前年の合計所得金額が135万円以下か（第295条第1項第2号の所得の要件。境目の説明の判定）"
    reference = [f"{_R1}#4", f"{_PSJ}#3.1"]

    def formula(人, period, parameters):
        return 人("住民税_合計所得金額", period) <= parameters(period).住民税.非課税.第295条第1項の合計所得金額の上限


class 住民税_所得割の非課税の基準の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "35万円×（同一生計配偶者及び扶養親族の数＋1）＋10万円（＋32万円）（附則第3条の3第4項）"
    reference = [f"{_PSJ}#2.1", f"{_LAW}#10"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.非課税.所得割
        数 = 人("住民税_同一生計配偶者及び扶養親族の数", period)
        return _yen((calc.exemption_line(int(n), int(p.人数ごとの額), int(p.定額), int(p.扶養がある場合の加算額)) for n in 数), "所得割の非課税の基準の額")


class 住民税_所得割を課さない者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "前年の総所得金額等が所得割の非課税の基準の額以下の者か（附則第3条の3第4項）"
    reference = [f"{_PSJ}#2.1", f"{_LAW}#10"]

    def formula(人, period, parameters):
        return 人("住民税_総所得金額等", period) <= 人("住民税_所得割の非課税の基準の額", period)


class 住民税_均等割を課さない者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "均等割のみを課すべき者で、前年の合計所得金額が条例の基本額×（数＋1）＋10万円（＋加算額）以下の者か（第295条第3項）"
    reference = [f"{_PSJ}#1.1", f"{_PSJ}#1.2", f"{_PSJ}#1.4"]

    def formula(人, period, parameters):
        return 人("住民税_所得割を課さない者か", period) & 人("住民税_均等割の非課税の合計所得金額要件", period)


class 住民税_均等割の非課税の基準の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "均等割を課さない者の基準の額：条例の基本額×（同一生計配偶者及び扶養親族の数＋1）＋10万円（＋条例の加算額）（第295条第3項。2026-11-12 に分けた：境目の説明）"
    reference = [f"{_PSJ}#1.1", f"{_PSJ}#1.2", f"{_PSJ}#1.4"]

    def formula(人, period, parameters):
        定額 = int(parameters(period).住民税.非課税.均等割.定額)
        数 = 人("住民税_同一生計配偶者及び扶養親族の数", period)
        基本 = 人("住民税_均等割の非課税の基本額", period)
        加算 = 人("住民税_均等割の非課税の加算額", period)
        return _yen((calc.exemption_line(int(n), int(a), 定額, int(b)) for n, a, b in zip(数, 基本, 加算)), "均等割の非課税の基準")


class 住民税_均等割の非課税の合計所得金額要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "前年の合計所得金額が均等割の非課税の基準の額以下か（第295条第3項の所得の要件だけ。境目の説明の判定。2026-11-12）"
    reference = [f"{_PSJ}#1.1"]

    def formula(人, period, parameters):
        return 人("住民税_合計所得金額", period) <= 人("住民税_均等割の非課税の基準の額", period)


class 住民税_住所地の均等割を課すか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "賦課期日に住所を有する市町村で均等割を課される者か（住所があり、第295条第1項・第3項に当たらない。第311条の軽減・家屋敷課税の運用の型 B の材料）"
    reference = [f"{_PSJ}#1.1", f"{_PSJ}#3.1", f"{_LAW}#13"]

    def formula(人, period, parameters):
        住所 = _domiciled(人("住民税_賦課期日に住所を有する市町村", period))
        return 住所 & ~人("住民税_第295条第1項の非課税に当たるか", period) & ~人("住民税_均等割を課さない者か", period)


class 住民税_森林環境税を課さない者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "森林環境税を課さない者か（森林環境税法第4条：生活扶助、135万円、政令の式の額以下）"
    reference = [f"{_LAW}#14"]

    def formula(人, period, parameters):
        定額 = int(parameters(period).住民税.森林環境税.非課税.定額)
        数 = 人("住民税_同一生計配偶者及び扶養親族の数", period)
        基本 = 人("住民税_森林環境税の非課税の基本額", period)
        加算 = 人("住民税_森林環境税の非課税の加算額", period)
        基準 = _yen((calc.exemption_line(int(n), int(a), 定額, int(b)) for n, a, b in zip(数, 基本, 加算)), "森林環境税の非課税の基準")
        return 人("住民税_第295条第1項の非課税に当たるか", period) | (人("住民税_合計所得金額", period) <= 基準)


class 住民税_人的控除差の扶養親族の1人分の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "調整控除の人的控除差の表（１）（２）（８）（９）の、その人が扶養親族に当たるときの1人分（納税義務者に集める）"
    reference = [f"{_LAW}#5"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.調整控除.人的控除差
        障害 = np.select(
            [人("住民税_同居特別障害者に当たるか", period), 人("住民税_扶養等の判定に使う特別障害者か", period), 人("住民税_扶養等の判定に使う障害者か", period)],
            [int(p.同居特別障害者), int(p.特別障害者), int(p.障害者)],
            0,
        )
        扶養 = np.select(
            [人("住民税_同居老親等に当たるか", period), 人("住民税_老人扶養親族に当たるか", period), 人("住民税_特定扶養親族に当たるか", period)],
            [int(p.同居老親等), int(p.老人扶養親族), int(p.特定扶養親族)],
            int(p.扶養親族),
        )
        return _yen(np.where(人("住民税_扶養親族に当たるか", period), 障害, 0) + np.where(人("住民税_控除対象扶養親族に当たるか", period), 扶養, 0), "人的控除差の1人分")


class 住民税_人的控除差の合計(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "調整控除の第1号イの金額（5万円に人的控除差の表の金額を合算した金額）"
    reference = [f"{_LAW}#5", f"{_SPOUSE}#3.3"]

    def formula(人, period, parameters):
        q = parameters(period).住民税.調整控除
        p = q.人的控除差
        sp = parameters(period).住民税.所得控除.配偶者控除.本人の区分
        本人の合計 = 人("住民税_合計所得金額", period)
        本人の区分 = np.select([本人の合計 <= int(sp.第1号の上限), 本人の合計 <= int(sp.第2号の上限), 本人の合計 <= int(sp.第3号の上限)], [1, 2, 3], 0)
        本人の障害 = np.select([人("所得税_特別障害者に当たるか", period), 人("所得税_障害者に当たるか", period)], [int(p.特別障害者), int(p.障害者)], 0)
        ひとり親 = 人("住民税_ひとり親に当たるか", period)
        寡婦等 = np.where(ひとり親 & 人("住民税_法令上の性別が女性か", period), int(p.ひとり親の母), np.where(ひとり親 | 人("住民税_寡婦に当たるか", period), int(p.寡婦又はひとり親の父), 0))
        勤労 = np.where(人("住民税_勤労学生に当たるか", period), int(p.勤労学生), 0)
        同一生計 = 人("住民税_同一生計配偶者に当たるか", period)
        自分の配偶者としての障害 = np.select(
            [人("住民税_同居特別障害者に当たるか", period), 人("住民税_扶養等の判定に使う特別障害者か", period), 人("住民税_扶養等の判定に使う障害者か", period)],
            [int(p.同居特別障害者), int(p.特別障害者), int(p.障害者)],
            0,
        )
        配偶者の障害 = (
            人.法律婚.sum(
                np.select(
                    [人("住民税_同居特別障害者に当たるか", period), 人("住民税_扶養等の判定に使う特別障害者か", period), 人("住民税_扶養等の判定に使う障害者か", period)],
                    [int(p.同居特別障害者), int(p.特別障害者), int(p.障害者)],
                    0,
                )
            )
            - 自分の配偶者としての障害
        )
        配偶者の年齢 = 人.法律婚.sum(人("所得税_年齢", period)) - 人("所得税_年齢", period)
        老人 = 配偶者の年齢 >= int(parameters(period).住民税.所得控除.配偶者控除.老人の年齢の下限)
        控除対象 = 同一生計 & (本人の区分 > 0)
        配偶者の行 = np.where(
            控除対象,
            np.select(
                [本人の区分 == 1, 本人の区分 == 2, 本人の区分 == 3],
                [np.where(老人, int(p.老人控除対象配偶者.第1号), int(p.控除対象配偶者.第1号)), np.where(老人, int(p.老人控除対象配偶者.第2号), int(p.控除対象配偶者.第2号)), np.where(老人, int(p.老人控除対象配偶者.第3号), int(p.控除対象配偶者.第3号))],
                0,
            ),
            0,
        )
        配偶者の合計 = 人.法律婚.sum(人("住民税_合計所得金額", period)) - 本人の合計
        特別 = p.配偶者特別控除
        第7行の対象 = 人("住民税_配偶者特別控除の対象か", period) & (配偶者の合計 < int(特別.配偶者の合計所得金額の上限))
        低い = 配偶者の合計 >= int(特別.低い額の配偶者の合計所得金額の下限)
        第7行 = np.where(
            第7行の対象,
            np.select(
                [本人の区分 == 1, 本人の区分 == 2, 本人の区分 == 3],
                [np.where(低い, int(特別.低い額の第1号), int(特別.第1号)), np.where(低い, int(特別.低い額の第2号), int(特別.第2号)), np.where(低い, int(特別.低い額の第3号), int(特別.第3号))],
                0,
            ),
            0,
        )
        扶養 = 人.住民税扶養所属.sum(人("住民税_人的控除差の扶養親族の1人分の額", period) * 人.has_role(住民税扶養所属.住民税の扶養親族等)) * 人.has_role(住民税扶養所属.納税義務者)
        合計 = int(q.基本の額) + 本人の障害 + 寡婦等 + 勤労 + np.where(同一生計, 配偶者の障害, 0) + 配偶者の行 + 第7行 + np.asarray(扶養).round()
        return _yen(合計 + 人("住民税_連鎖の扶養親族の人的控除差の額", period), "人的控除差の合計")


class 住民税_配偶者特別控除の対象か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "第10号の2 の配偶者（生計を一にし、専従者でなく、前年の合計所得金額133万円以下で控除対象配偶者に当たらない）を有する1,000万円以下の納税義務者か"
    reference = [f"{_SPOUSE}#3.2"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.配偶者特別控除
        本人の合計 = 人("住民税_合計所得金額", period)
        配偶者の合計 = 人.法律婚.sum(人("住民税_合計所得金額", period)) - 本人の合計
        配偶者が扶養親族等 = 人.法律婚.sum(人("住民税_他の納税義務者の扶養親族等とされているか", period)) - 人("住民税_他の納税義務者の扶養親族等とされているか", period)
        # 相手が自分を控除対象配偶者として配偶者控除を受けている（令和8年度分から「前号又はこの号」）
        自分が相手の同一生計配偶者 = (人.法律婚.sum(人("住民税_同一生計配偶者に当たるか", period)) - 人("住民税_同一生計配偶者に当たるか", period)) > 0
        相手が配偶者控除を受ける = 自分が相手の同一生計配偶者 & (配偶者の合計 <= int(p.本人の区分.第3号の上限))
        return (
            (人.法律婚.nb_persons() == 2)
            & 人("所得税_配偶者と生計を一にするか", period)
            & ~人("所得税_配偶者が青色事業専従者等か", period)
            & ~人("住民税_同一生計配偶者に当たるか", period)
            & (配偶者が扶養親族等 == 0)
            & (配偶者の合計 <= int(p.配偶者の合計所得金額の上限))
            & (本人の合計 <= int(p.本人の区分.第3号の上限))
            & ~人("所得税_配偶者特別控除の適用除外に当たるか", period)
            & ~相手が配偶者控除を受ける
        )


# ---------------------------------------------------------------------------
# 所得控除（第314条の2）
# ---------------------------------------------------------------------------


class 住民税_扶養控除の1人分の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "扶養控除の、その人が控除対象扶養親族に当たるときの1人分の額（33万円・特定45万円・老人38万円・同居老親等45万円）"
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.扶養控除
        額 = np.select(
            [人("住民税_同居老親等に当たるか", period), 人("住民税_老人扶養親族に当たるか", period), 人("住民税_特定扶養親族に当たるか", period)],
            [int(p.同居老親等), int(p.老人扶養親族), int(p.特定扶養親族)],
            int(p.一般),
        )
        return _yen(np.where(人("住民税_控除対象扶養親族に当たるか", period), 額, 0), "扶養控除の1人分")


class 住民税_特定親族特別控除の1人分の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定親族特別控除の、その人が特定親族に当たるときの1人分の額（その人の前年の合計所得金額の区分）"
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.特定親族特別控除
        当たる = 人("住民税_特定親族に当たるか", period)
        合計 = 人("住民税_合計所得金額", period)
        return _yen((calc.specified_relative_amount(int(x), p) if a else 0 for a, x in zip(当たる, 合計)), "特定親族特別控除の1人分")


class 住民税_障害者控除の扶養親族の1人分の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "障害者控除の、その人が扶養親族に当たるときの1人分の額（26万円・特別障害者30万円・同居特別障害者53万円）"
    reference = [f"{_JINTEKI}#2.3"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.障害者控除
        額 = np.select(
            [人("住民税_同居特別障害者に当たるか", period), 人("住民税_扶養等の判定に使う特別障害者か", period), 人("住民税_扶養等の判定に使う障害者か", period)],
            [int(p.同居特別障害者), int(p.特別障害者), int(p.障害者)],
            0,
        )
        return _yen(np.where(人("住民税_扶養親族に当たるか", period), 額, 0), "障害者控除の1人分")


def _sum_dependents_note() -> str:
    return "扶養親族等の役割の人の1人分を納税義務者に集め、扶養の連鎖の人の分（段の入力）を足す"


class 住民税_扶養控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "扶養控除の額（第314条の2第1項第11号・第4項）。" + _sum_dependents_note()
    reference = [f"{_PSJ}#5", f"{_LAW}#3"]

    def formula(人, period, parameters):
        扶養 = 人.住民税扶養所属.sum(人("住民税_扶養控除の1人分の額", period) * 人.has_role(住民税扶養所属.住民税の扶養親族等)) * 人.has_role(住民税扶養所属.納税義務者)
        return _yen(np.asarray(扶養).round() + 人("住民税_連鎖の扶養親族の扶養控除の額", period), "扶養控除の額")


class 住民税_特定親族特別控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定親族特別控除の額（第12号）。" + _sum_dependents_note()
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        扶養 = 人.住民税扶養所属.sum(人("住民税_特定親族特別控除の1人分の額", period) * 人.has_role(住民税扶養所属.住民税の扶養親族等)) * 人.has_role(住民税扶養所属.納税義務者)
        return _yen(np.asarray(扶養).round() + 人("住民税_連鎖の扶養親族の特定親族特別控除の額", period), "特定親族特別控除の額")


class 住民税_障害者控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "障害者控除の額（本人・同一生計配偶者・扶養親族の分。第6号・第3項）"
    reference = [f"{_JINTEKI}#2.3"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.障害者控除
        本人 = np.select([人("所得税_特別障害者に当たるか", period), 人("所得税_障害者に当たるか", period)], [int(p.特別障害者), int(p.障害者)], 0)
        自分の配偶者としての額 = np.select(
            [人("住民税_同居特別障害者に当たるか", period), 人("住民税_扶養等の判定に使う特別障害者か", period), 人("住民税_扶養等の判定に使う障害者か", period)],
            [int(p.同居特別障害者), int(p.特別障害者), int(p.障害者)],
            0,
        )
        配偶者の額 = (
            人.法律婚.sum(
                np.select(
                    [人("住民税_同居特別障害者に当たるか", period), 人("住民税_扶養等の判定に使う特別障害者か", period), 人("住民税_扶養等の判定に使う障害者か", period)],
                    [int(p.同居特別障害者), int(p.特別障害者), int(p.障害者)],
                    0,
                )
            )
            - 自分の配偶者としての額
        )
        配偶者の分 = np.where(人("住民税_同一生計配偶者に当たるか", period), 配偶者の額, 0)
        扶養 = 人.住民税扶養所属.sum(人("住民税_障害者控除の扶養親族の1人分の額", period) * 人.has_role(住民税扶養所属.住民税の扶養親族等)) * 人.has_role(住民税扶養所属.納税義務者)
        return _yen(本人 + np.asarray(配偶者の分).round() + np.asarray(扶養).round() + 人("住民税_連鎖の扶養親族の障害者控除の額", period), "障害者控除の額")


class 住民税_寡婦控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "寡婦控除の額（第8号。寡婦の判定は所得税と同じ形：前年の12月31日の現況）"
    reference = [f"{_JINTEKI}#2.1", f"{_JINTEKI}#2.3"]

    def formula(人, period, parameters):
        return np.where(人("住民税_寡婦に当たるか", period), int(parameters(period).住民税.所得控除.寡婦控除), 0)


class 住民税_ひとり親控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "ひとり親控除の額（第8号の2。令和9年度分まで30万円）"
    reference = [f"{_JINTEKI}#2.1", f"{_JINTEKI}#2.3"]

    def formula(人, period, parameters):
        return np.where(人("住民税_ひとり親に当たるか", period), int(parameters(period).住民税.所得控除.ひとり親控除), 0)


class 住民税_勤労学生控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "勤労学生控除の額（第9号。勤労学生の意義は前年分に適用された所得税法第2条第1項第32号：第9項・第292条第5項）"
    reference = [f"{_PSJ}#5"]

    def formula(人, period, parameters):
        return np.where(人("住民税_勤労学生に当たるか", period), int(parameters(period).住民税.所得控除.勤労学生控除), 0)


class 住民税_配偶者控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配偶者控除の額（第10号：33万円・22万円・11万円、老人控除対象配偶者 38万円・26万円・13万円）"
    reference = [f"{_SPOUSE}#3.2"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.配偶者控除
        本人の合計 = 人("住民税_合計所得金額", period)
        配偶者の年齢 = 人.法律婚.sum(人("所得税_年齢", period)) - 人("所得税_年齢", period)
        老人 = 配偶者の年齢 >= int(p.老人の年齢の下限)
        同一生計 = 人("住民税_同一生計配偶者に当たるか", period)
        return _yen((calc.spouse_deduction(int(x), bool(o), p) if s else 0 for s, x, o in zip(同一生計, 本人の合計, 老人)), "配偶者控除の額")


class 住民税_配偶者特別控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配偶者特別控除の額（第10号の2）"
    reference = [f"{_SPOUSE}#3.2"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.配偶者特別控除
        対象 = 人("住民税_配偶者特別控除の対象か", period)
        本人の合計 = 人("住民税_合計所得金額", period)
        配偶者の合計 = 人.法律婚.sum(人("住民税_合計所得金額", period)) - 本人の合計
        return _yen((calc.spouse_special_deduction(int(x), int(y), p) if t else 0 for t, x, y in zip(対象, 本人の合計, 配偶者の合計)), "配偶者特別控除の額")


class 住民税_基礎控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "基礎控除の額（第2項：43万円・29万円・15万円。所得税の基礎控除の引上げは及ばない）"
    reference = [f"{_R1}#3", f"{_PSJ}#5"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.基礎控除
        return _yen((calc.basic_deduction(int(x), p) for x in 人("住民税_合計所得金額", period)), "基礎控除の額")


class 住民税_社会保険料控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "社会保険料控除の額（第3号：前年中に支払った額の全額。所得税の社会保険料控除と同じ額）"
    reference = [f"{_LAW}#3"]

    def formula(人, period, parameters):
        return 人("所得税_社会保険料控除の額", period)


class 住民税_小規模企業共済等掛金控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "小規模企業共済等掛金控除の額（第4号：全額。所得税と同じ額）"
    reference = [f"{_HOKEN}#7"]

    def formula(人, period, parameters):
        return 人("所得税_小規模企業共済等掛金控除の額", period)


class 住民税_生命保険料控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "生命保険料控除の額（第5号：区分ごとの上限 2万8千円・3万5千円、合計 7万円。区分ごとの1円未満は候補で評価）"
    reference = [f"{_HOKEN}#7"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.生命保険料控除
        rows = list(
            zip(
                人("所得税_新生命保険料の額", period),
                人("所得税_旧生命保険料の額", period),
                人("所得税_介護医療保険料の額", period),
                人("所得税_新個人年金保険料の額", period),
                人("所得税_旧個人年金保険料の額", period),
                人("所得税_生命保険料の新旧の選択", period),
            )
        )
        parts = [calc.life_insurance_exact(int(a), int(b), int(c), int(d), int(e), str(r) or "both", p) for a, b, c, d, e, r in rows]
        if not any(Fraction(x).denominator != 1 for xs in parts for x in xs):
            return _yen((calc.life_insurance_deduction(xs, int, p) for xs in parts), "生命保険料控除の額")
        候補 = 人("住民税_生命保険料控除の端数の候補", period)
        return _yen((calc.life_insurance_deduction(xs, FUNCTIONS[str(c)], p) for xs, c in zip(parts, 候補)), "生命保険料控除の額")


class 住民税_地震保険料控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "地震保険料控除の額（第5号の3：2分の1、上限 2万5千円。旧長期損害保険料は最高1万円）"
    reference = [f"{_HOKEN}#7"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.地震保険料控除
        exact = [calc.earthquake_exact(int(a), int(b), p) for a, b in zip(人("所得税_地震保険料の額", period), 人("所得税_旧長期損害保険料の額", period))]
        if all(x.denominator == 1 for x in exact):
            return _yen(exact, "地震保険料控除の額")
        return _rounded(exact, 人("住民税_地震保険料控除の端数の候補", period))


class 住民税_医療費控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "医療費控除の額（第2号：前年の総所得金額等の5%〔上限10万円〕を超える額、最高200万円。セルフメディケーション税制を選んだ人は附則第4条の5 の特例の額）"
    reference = [f"{_LAW}#3", f"{_SOCHI}#5"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.医療費控除
        医療費 = 人("所得税_補塡後の医療費の額", period)
        総所得 = 人("住民税_総所得金額等", period)
        セルフ = 人("所得税_セルフメディケーション税制の選択", period)
        要る = [(not s) and calc.medical_fraction_matters(int(e), int(t), p) for s, e, t in zip(セルフ, 医療費, 総所得)]
        候補 = 人("住民税_医療費控除の足切りの端数の候補", period) if any(要る) else [""] * len(要る)
        通常 = [
            calc.medical_deduction(int(e), int(t), FUNCTIONS[str(c)] if m else (lambda v: int(v)), p)
            for e, t, c, m in zip(医療費, 総所得, 候補, 要る)
        ]
        # セルフメディケーション税制の額は所得税の額（同じ購入費・同じ1万2千円・8万8千円）を写す（附則第4条の5 の読替えの額は docs に写していない：原文未確認）
        return _yen(np.where(セルフ, 人("所得税_セルフメディケーション税制による医療費控除の額", period), 通常), "医療費控除の額")


class 住民税_雑損控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "雑損控除の額（第1号：損失の金額−前年の総所得金額等の1/10 など。所得税法第72条と同じ形）"
    reference = [f"{_HOKEN}#7"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.所得控除.雑損控除
        損失 = 人("所得税_雑損の損失の金額", period)
        if not (損失 > 0).any():
            return np.zeros(len(損失), dtype=np.int32)
        関連 = 人("所得税_雑損の災害関連支出の金額", period)
        総所得 = 人("住民税_総所得金額等", period)
        要る = [calc.casualty_fraction_matters(int(a), int(t), p) for a, t in zip(損失, 総所得)]
        候補 = 人("住民税_雑損控除の足切りの端数の候補", period) if any(要る) else [""] * len(要る)
        return _yen(
            (calc.casualty_deduction(int(a), int(b), int(t), FUNCTIONS[str(c)] if m else (lambda v: int(v)), p) for a, b, t, c, m in zip(損失, 関連, 総所得, 候補, 要る)),
            "雑損控除の額",
        )


class 住民税_所得控除の合計(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "所得控除の額の合計（第314条の2）"
    reference = [f"{_LAW}#3", f"{_R1}#3"]

    def formula(人, period, parameters):
        return _yen(
            人("住民税_雑損控除の額", period)
            + 人("住民税_医療費控除の額", period)
            + 人("住民税_社会保険料控除の額", period).astype(np.int64)
            + 人("住民税_小規模企業共済等掛金控除の額", period)
            + 人("住民税_生命保険料控除の額", period)
            + 人("住民税_地震保険料控除の額", period)
            + 人("住民税_障害者控除の額", period)
            + 人("住民税_寡婦控除の額", period)
            + 人("住民税_ひとり親控除の額", period)
            + 人("住民税_勤労学生控除の額", period)
            + 人("住民税_配偶者控除の額", period)
            + 人("住民税_配偶者特別控除の額", period)
            + 人("住民税_扶養控除の額", period)
            + 人("住民税_特定親族特別控除の額", period)
            + 人("住民税_基礎控除の額", period),
            "所得控除の合計",
        )


# ---------------------------------------------------------------------------
# 課税所得
# ---------------------------------------------------------------------------


class 住民税_課税総所得金額等(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "課税総所得金額・課税退職所得金額・課税山林所得金額の合計（総所得金額−所得控除の合計。千円未満切捨て。分離課税の退職所得・山林所得はこの版では0）"
    reference = [f"{_LAW}#4", f"{_LAW}#15"]

    def formula(人, period, parameters):
        unit = int(parameters(period).住民税.税率.端数.課税標準の単位)
        総 = 人("住民税_雑損失の繰越控除の後の総所得金額", period).astype(np.int64)  # 分離課税に係る退職所得のある人は退職所得がないものとした額（JM-32）
        控除 = 人("住民税_所得控除の合計", period).astype(np.int64)
        控除後 = [calc.floor_unit(int(t) - int(d), unit) for t, d in zip(総, 控除)]
        控除前 = [calc.taxable_floor_before_deduction(int(t), int(d), unit) for t, d in zip(総, 控除)]
        if 控除後 == 控除前:  # 読みで値が違う人がいないときは読みの候補を引かない（引いたときだけ分かれ目が開く）
            return _yen(控除後, "課税総所得金額等")
        読み = 人("住民税_課税標準の千円未満の切捨ての当て先の読み", period)
        return _yen((b if str(r) == calc.READING_BEFORE_DEDUCTION else a for a, b, r in zip(控除後, 控除前, 読み)), "課税総所得金額等")


class 住民税_上場株式等に係る課税配当所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る課税配当所得等の金額（附則第33条の2。総所得金額から引ききれない所得控除を控除した後、千円未満切捨て）"
    reference = [f"{_LAW}#12", f"{_JM3}#3"]

    def formula(人, period, parameters):
        unit = int(parameters(period).住民税.税率.端数.課税標準の単位)
        差 = 人("住民税_雑損失の繰越控除の後の上場株式等に係る配当所得等の金額", period).astype(np.int64) - 人("住民税_上場株式等に係る配当所得等の金額から控除する所得控除の額", period)
        return _yen((calc.floor_unit(int(x), unit) for x in 差), "課税配当所得等")


class 住民税_上場株式等に係る課税譲渡所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る課税譲渡所得等の金額（附則第35条の2の2。総所得金額から引ききれない所得控除を控除した後、千円未満切捨て）"
    reference = [f"{_LAW}#12", f"{_JM3}#3"]

    def formula(人, period, parameters):
        unit = int(parameters(period).住民税.税率.端数.課税標準の単位)
        差 = 人("住民税_雑損失の繰越控除の後の上場株式等に係る譲渡所得等の金額", period).astype(np.int64) - 人("住民税_上場株式等に係る譲渡所得等の金額から控除する所得控除の額", period)
        return _yen((calc.floor_unit(int(x), unit) for x in 差), "課税譲渡所得等")


# ---------------------------------------------------------------------------
# 税額
# ---------------------------------------------------------------------------


class 住民税_人的控除差調整額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "人的控除差調整額（第314条の6第1号イの金額＋前年分の所得税の基礎控除の額−48万円〔零未満は零〕。寄附金の特例控除・申告特例控除の区分に使う）"
    reference = [f"{_LAW}#8.2", f"{_LAW}#8.3"]

    def formula(人, period, parameters):
        基準 = int(parameters(period).住民税.税額控除.寄附金税額控除.基礎控除の差の基準)
        差 = np.maximum(人("所得税_基礎控除の額", period).astype(np.int64) - 基準, 0)
        return _yen(人("住民税_人的控除差の合計", period) + 差, "人的控除差調整額")


class 住民税_前年分の所得税の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年分の所得税の額（住宅借入金等特別控除・政党等寄附金特別控除などを適用しない額：算出税額−配当控除。附則第5条の4第5項第2号）"
    reference = [f"{_EXTRA}#3.2"]

    def formula(人, period, parameters):
        return np.maximum(人("所得税_算出税額", period) - 人("所得税_配当控除の額", period), 0).astype(np.int32)


class 住民税_住宅借入金等特別税額控除の控除限度の基(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "控除限度額の基（前年分の所得税の課税総所得金額・課税退職所得金額の合計。居住年が平成28年〜令和7年なら基礎控除の額−48万円を加算）"
    reference = [f"{_EXTRA}#3.2", f"{_EXTRA}#3.4"]

    def formula(人, period, parameters):
        基準 = int(parameters(period).住民税.税額控除.住宅借入金等特別税額控除.基礎控除の差の基準)
        差 = np.maximum(人("所得税_基礎控除の額", period).astype(np.int64) - 基準, 0)
        加算 = np.where(人("住民税_住宅借入金等特別税額控除の控除限度額に基礎控除の差を加算するか", period), 差, 0)
        return _yen(人("所得税_課税総所得金額", period).astype(np.int64) + 人("所得税_課税退職所得金額", period) + 加算, "控除限度の基")


def _chain_input(v: dict[str, Any], i: int) -> calc.ChainInput:
    return calc.ChainInput(
        taxable=int(v["課税"][i]),
        taxable_dividend=int(v["分離配当"][i]),
        taxable_gain=int(v["分離譲渡"][i]),
        total_income=int(v["合計"][i]),
        gross_income=int(v["総所得等"][i]),
        personal_diff=int(v["人的"][i]),
        personal_adjust=int(v["人的調整"][i]),
        surplus_dividend=int(v["剰余金"][i]),
        trust_dividend=int(v["証券"][i]),
        foreign_dividend=int(v["外貨"][i]),
        housing_credit=int(v["住宅①"][i]),
        income_tax_before=int(v["所得税額"][i]),
        housing_base=int(v["限度の基"][i]),
        donation_total=int(v["寄附1号"][i]),
        special_donation=int(v["特例"][i]),
        filing_special=bool(v["申告特例"][i]),
        withheld_local=int(v["配当割"][i]),
        exemption_line=int(v["非課税基準"][i]),
        designated=bool(v["指定都市"][i]),
        rate_m=Fraction(int(v["市分子"][i]), max(int(v["市分母"][i]), 1)),
        rate_p=Fraction(int(v["県分子"][i]), max(int(v["県分母"][i]), 1)),
        donation_extra_m=int(v["寄附市"][i]),
        donation_extra_p=int(v["寄附県"][i]),
        housing_specified=bool(v["特定取得"][i]),
        separate_income=int(v["分離所得"][i]) > 0,
    )


def _chain(v: dict[str, Any], p: Any) -> list[calc.ChainResult | None]:
    """課税される人（住所があり、第295条第1項・所得割の非課税に当たらない）の連鎖。課税されない人は None。"""
    rules = calc.ChainRules(adjust=p["調整"], credits=p["控除"], rates=p["率"])
    out: list[calc.ChainResult | None] = []
    for i in range(len(v["課税"])):
        if not v["課税される"][i]:
            out.append(None)
            continue
        out.append(calc.compute_chain(_chain_input(v, i), rules))
    return out


def _domiciled(住所: Any) -> np.ndarray:
    """住民税_賦課期日に住所を有する市町村 の配列から、住所を有するか（団体コードがあり「なし」でない）。"""
    a = np.asarray(住所)
    return (a != "") & (a != calc.NO_DOMICILE)


def _taxed(住所: Any, 非課税: Any, 所得割非課税: Any) -> np.ndarray:
    return _domiciled(住所) & ~np.asarray(非課税) & ~np.asarray(所得割非課税)


class 住民税_調整控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "調整控除の額（市町村民税と道府県民税の合計。第314条の6・第37条の式の額。率の合計は指定都市かによらず5%。算出所得割を超える部分は所得割の額の計算で切り捨てる）"
    reference = [f"{_LAW}#5"]

    def formula(人, period, parameters):
        p = parameters(period).住民税.調整控除
        率 = Fraction(int(p.率.市町村民税.分子), int(p.率.市町村民税.分母)) + Fraction(int(p.率.道府県民税.分子), int(p.率.道府県民税.分母))
        課税される = _taxed(人("住民税_賦課期日に住所を有する市町村", period), 人("住民税_第295条第1項の非課税に当たるか", period), 人("住民税_所得割を課さない者か", period))
        rows = zip(課税される, 人("住民税_人的控除差の合計", period), 人("住民税_課税総所得金額等", period), 人("住民税_合計所得金額", period))
        return _yen((Fraction(calc.adjustment_base(int(d), int(t), int(g), p)) * 率 if c else 0 for c, d, t, g in rows), "調整控除の額")


class 住民税_所得割の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "所得割の額（市町村民税・道府県民税の合計。税額控除・附則第3条の3第5項の調整の後、それぞれ百円未満切捨て）"
    reference = [f"{_LAW}#4", f"{_LAW}#10", f"{_LAW}#11", f"{_EXTRA}#2.4"]

    def formula(人, period, parameters):
        課税される = _taxed(人("住民税_賦課期日に住所を有する市町村", period), 人("住民税_第295条第1項の非課税に当たるか", period), 人("住民税_所得割を課さない者か", period))
        if not 課税される.any():
            return np.zeros(len(課税される), dtype=np.int32)
        v = {
            "課税される": 課税される,
            "課税": 人("住民税_課税総所得金額等", period),
            "分離配当": 人("住民税_上場株式等に係る課税配当所得等の金額", period),
            "分離譲渡": 人("住民税_上場株式等に係る課税譲渡所得等の金額", period),
            "合計": 人("住民税_合計所得金額", period),
            "総所得等": 人("住民税_総所得金額等", period),
            "人的": 人("住民税_人的控除差の合計", period),
            "人的調整": 人("住民税_人的控除差調整額", period),
            "剰余金": 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period),
            "証券": 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period),
            "外貨": 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period),
            "住宅①": 人("所得税_住宅借入金等特別控除の額", period),
            "所得税額": 人("住民税_前年分の所得税の額", period),
            "限度の基": 人("住民税_住宅借入金等特別税額控除の控除限度の基", period),
            "寄附1号": 人("住民税_都道府県等に対する寄附金の額", period),
            "寄附市": 人("住民税_市町村民税の第2号から第4号までの寄附金の額", period),
            "寄附県": 人("住民税_道府県民税の第2号から第4号までの寄附金の額", period),
            "特定取得": 人("住民税_住宅借入金等特別税額控除の特定取得か", period),
            "分離所得": 人("住民税_上場株式等に係る分離課税の所得の金額", period),
            "特例": 人("住民税_特例控除対象寄附金の額", period),
            "申告特例": 人("住民税_申告特例控除の対象か", period),
            "配当割": 人("住民税_控除の対象の配当割額等", period),
            "非課税基準": 人("住民税_所得割の非課税の基準の額", period),
            "指定都市": 人("住民税_指定都市の区域内に住所を有するか", period),
            "市分子": 人("住民税_市町村民税の所得割の税率の分子", period),
            "市分母": 人("住民税_市町村民税の所得割の税率の分母", period),
            "県分子": 人("住民税_道府県民税の所得割の税率の分子", period),
            "県分母": 人("住民税_道府県民税の所得割の税率の分母", period),
        }
        p = {"調整": parameters(period).住民税.調整控除, "控除": parameters(period).住民税.税額控除, "率": parameters(period).住民税.税率}
        return _yen((r.municipal.final + r.prefectural.final if r is not None else 0 for r in _chain(v, p)), "所得割の額")


class 住民税_配当控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配当控除の額（附則第5条第3項・第1項。市町村民税と道府県民税の合計。調整控除の後の所得割の額を限度）"
    reference = [f"{_LAW}#6"]

    def formula(人, period, parameters):
        課税される = _taxed(人("住民税_賦課期日に住所を有する市町村", period), 人("住民税_第295条第1項の非課税に当たるか", period), 人("住民税_所得割を課さない者か", period))
        if not 課税される.any():
            return np.zeros(len(課税される), dtype=np.int32)
        v = {
            "課税される": 課税される,
            "課税": 人("住民税_課税総所得金額等", period),
            "分離配当": 人("住民税_上場株式等に係る課税配当所得等の金額", period),
            "分離譲渡": 人("住民税_上場株式等に係る課税譲渡所得等の金額", period),
            "合計": 人("住民税_合計所得金額", period),
            "総所得等": 人("住民税_総所得金額等", period),
            "人的": 人("住民税_人的控除差の合計", period),
            "人的調整": 人("住民税_人的控除差調整額", period),
            "剰余金": 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period),
            "証券": 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period),
            "外貨": 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period),
            "住宅①": 人("所得税_住宅借入金等特別控除の額", period),
            "所得税額": 人("住民税_前年分の所得税の額", period),
            "限度の基": 人("住民税_住宅借入金等特別税額控除の控除限度の基", period),
            "寄附1号": 人("住民税_都道府県等に対する寄附金の額", period),
            "寄附市": 人("住民税_市町村民税の第2号から第4号までの寄附金の額", period),
            "寄附県": 人("住民税_道府県民税の第2号から第4号までの寄附金の額", period),
            "特定取得": 人("住民税_住宅借入金等特別税額控除の特定取得か", period),
            "分離所得": 人("住民税_上場株式等に係る分離課税の所得の金額", period),
            "特例": 人("住民税_特例控除対象寄附金の額", period),
            "申告特例": 人("住民税_申告特例控除の対象か", period),
            "配当割": 人("住民税_控除の対象の配当割額等", period),
            "非課税基準": 人("住民税_所得割の非課税の基準の額", period),
            "指定都市": 人("住民税_指定都市の区域内に住所を有するか", period),
            "市分子": 人("住民税_市町村民税の所得割の税率の分子", period),
            "市分母": 人("住民税_市町村民税の所得割の税率の分母", period),
            "県分子": 人("住民税_道府県民税の所得割の税率の分子", period),
            "県分母": 人("住民税_道府県民税の所得割の税率の分母", period),
        }
        p = {"調整": parameters(period).住民税.調整控除, "控除": parameters(period).住民税.税額控除, "率": parameters(period).住民税.税率}
        results = _chain(v, p)
        exact = [r.total("dividend") if r is not None else Fraction(0) for r in results]
        if all(x.denominator == 1 for x in exact):
            return _yen(exact, "住民税_配当控除の額")
        return _rounded(exact, 人("住民税_税額控除の額の端数の候補", period))


class 住民税_住宅借入金等特別税額控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "住宅借入金等特別税額控除の額（附則第5条の4第5項・第1項。前年分の所得税で控除しきれなかった額×3/5・2/5、控除限度額まで）"
    reference = [f"{_EXTRA}#3.2"]

    def formula(人, period, parameters):
        課税される = _taxed(人("住民税_賦課期日に住所を有する市町村", period), 人("住民税_第295条第1項の非課税に当たるか", period), 人("住民税_所得割を課さない者か", period))
        if not 課税される.any():
            return np.zeros(len(課税される), dtype=np.int32)
        v = {
            "課税される": 課税される,
            "課税": 人("住民税_課税総所得金額等", period),
            "分離配当": 人("住民税_上場株式等に係る課税配当所得等の金額", period),
            "分離譲渡": 人("住民税_上場株式等に係る課税譲渡所得等の金額", period),
            "合計": 人("住民税_合計所得金額", period),
            "総所得等": 人("住民税_総所得金額等", period),
            "人的": 人("住民税_人的控除差の合計", period),
            "人的調整": 人("住民税_人的控除差調整額", period),
            "剰余金": 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period),
            "証券": 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period),
            "外貨": 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period),
            "住宅①": 人("所得税_住宅借入金等特別控除の額", period),
            "所得税額": 人("住民税_前年分の所得税の額", period),
            "限度の基": 人("住民税_住宅借入金等特別税額控除の控除限度の基", period),
            "寄附1号": 人("住民税_都道府県等に対する寄附金の額", period),
            "寄附市": 人("住民税_市町村民税の第2号から第4号までの寄附金の額", period),
            "寄附県": 人("住民税_道府県民税の第2号から第4号までの寄附金の額", period),
            "特定取得": 人("住民税_住宅借入金等特別税額控除の特定取得か", period),
            "分離所得": 人("住民税_上場株式等に係る分離課税の所得の金額", period),
            "特例": 人("住民税_特例控除対象寄附金の額", period),
            "申告特例": 人("住民税_申告特例控除の対象か", period),
            "配当割": 人("住民税_控除の対象の配当割額等", period),
            "非課税基準": 人("住民税_所得割の非課税の基準の額", period),
            "指定都市": 人("住民税_指定都市の区域内に住所を有するか", period),
            "市分子": 人("住民税_市町村民税の所得割の税率の分子", period),
            "市分母": 人("住民税_市町村民税の所得割の税率の分母", period),
            "県分子": 人("住民税_道府県民税の所得割の税率の分子", period),
            "県分母": 人("住民税_道府県民税の所得割の税率の分母", period),
        }
        p = {"調整": parameters(period).住民税.調整控除, "控除": parameters(period).住民税.税額控除, "率": parameters(period).住民税.税率}
        results = _chain(v, p)
        exact = [r.total("housing") if r is not None else Fraction(0) for r in results]
        if all(x.denominator == 1 for x in exact):
            return _yen(exact, "住民税_住宅借入金等特別税額控除の額")
        return _rounded(exact, 人("住民税_税額控除の額の端数の候補", period))


class 住民税_寄附金税額控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "寄附金税額控除の額（第314条の7・第37条の2。基本控除額と特例控除額。所得割の額を限度）"
    reference = [f"{_LAW}#8.1"]

    def formula(人, period, parameters):
        課税される = _taxed(人("住民税_賦課期日に住所を有する市町村", period), 人("住民税_第295条第1項の非課税に当たるか", period), 人("住民税_所得割を課さない者か", period))
        if not 課税される.any():
            return np.zeros(len(課税される), dtype=np.int32)
        v = {
            "課税される": 課税される,
            "課税": 人("住民税_課税総所得金額等", period),
            "分離配当": 人("住民税_上場株式等に係る課税配当所得等の金額", period),
            "分離譲渡": 人("住民税_上場株式等に係る課税譲渡所得等の金額", period),
            "合計": 人("住民税_合計所得金額", period),
            "総所得等": 人("住民税_総所得金額等", period),
            "人的": 人("住民税_人的控除差の合計", period),
            "人的調整": 人("住民税_人的控除差調整額", period),
            "剰余金": 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period),
            "証券": 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period),
            "外貨": 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period),
            "住宅①": 人("所得税_住宅借入金等特別控除の額", period),
            "所得税額": 人("住民税_前年分の所得税の額", period),
            "限度の基": 人("住民税_住宅借入金等特別税額控除の控除限度の基", period),
            "寄附1号": 人("住民税_都道府県等に対する寄附金の額", period),
            "寄附市": 人("住民税_市町村民税の第2号から第4号までの寄附金の額", period),
            "寄附県": 人("住民税_道府県民税の第2号から第4号までの寄附金の額", period),
            "特定取得": 人("住民税_住宅借入金等特別税額控除の特定取得か", period),
            "分離所得": 人("住民税_上場株式等に係る分離課税の所得の金額", period),
            "特例": 人("住民税_特例控除対象寄附金の額", period),
            "申告特例": 人("住民税_申告特例控除の対象か", period),
            "配当割": 人("住民税_控除の対象の配当割額等", period),
            "非課税基準": 人("住民税_所得割の非課税の基準の額", period),
            "指定都市": 人("住民税_指定都市の区域内に住所を有するか", period),
            "市分子": 人("住民税_市町村民税の所得割の税率の分子", period),
            "市分母": 人("住民税_市町村民税の所得割の税率の分母", period),
            "県分子": 人("住民税_道府県民税の所得割の税率の分子", period),
            "県分母": 人("住民税_道府県民税の所得割の税率の分母", period),
        }
        p = {"調整": parameters(period).住民税.調整控除, "控除": parameters(period).住民税.税額控除, "率": parameters(period).住民税.税率}
        results = _chain(v, p)
        exact = [r.total("donation") if r is not None else Fraction(0) for r in results]
        if all(x.denominator == 1 for x in exact):
            return _yen(exact, "住民税_寄附金税額控除の額")
        return _rounded(exact, 人("住民税_税額控除の額の端数の候補", period))


class 住民税_申告特例控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "申告特例控除の額（附則第7条の2第4項・第1項。特例控除額×割合、寄附金税額控除の後の所得割の額を限度）"
    reference = [f"{_LAW}#8.3"]

    def formula(人, period, parameters):
        課税される = _taxed(人("住民税_賦課期日に住所を有する市町村", period), 人("住民税_第295条第1項の非課税に当たるか", period), 人("住民税_所得割を課さない者か", period))
        if not 課税される.any():
            return np.zeros(len(課税される), dtype=np.int32)
        v = {
            "課税される": 課税される,
            "課税": 人("住民税_課税総所得金額等", period),
            "分離配当": 人("住民税_上場株式等に係る課税配当所得等の金額", period),
            "分離譲渡": 人("住民税_上場株式等に係る課税譲渡所得等の金額", period),
            "合計": 人("住民税_合計所得金額", period),
            "総所得等": 人("住民税_総所得金額等", period),
            "人的": 人("住民税_人的控除差の合計", period),
            "人的調整": 人("住民税_人的控除差調整額", period),
            "剰余金": 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period),
            "証券": 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period),
            "外貨": 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period),
            "住宅①": 人("所得税_住宅借入金等特別控除の額", period),
            "所得税額": 人("住民税_前年分の所得税の額", period),
            "限度の基": 人("住民税_住宅借入金等特別税額控除の控除限度の基", period),
            "寄附1号": 人("住民税_都道府県等に対する寄附金の額", period),
            "寄附市": 人("住民税_市町村民税の第2号から第4号までの寄附金の額", period),
            "寄附県": 人("住民税_道府県民税の第2号から第4号までの寄附金の額", period),
            "特定取得": 人("住民税_住宅借入金等特別税額控除の特定取得か", period),
            "分離所得": 人("住民税_上場株式等に係る分離課税の所得の金額", period),
            "特例": 人("住民税_特例控除対象寄附金の額", period),
            "申告特例": 人("住民税_申告特例控除の対象か", period),
            "配当割": 人("住民税_控除の対象の配当割額等", period),
            "非課税基準": 人("住民税_所得割の非課税の基準の額", period),
            "指定都市": 人("住民税_指定都市の区域内に住所を有するか", period),
            "市分子": 人("住民税_市町村民税の所得割の税率の分子", period),
            "市分母": 人("住民税_市町村民税の所得割の税率の分母", period),
            "県分子": 人("住民税_道府県民税の所得割の税率の分子", period),
            "県分母": 人("住民税_道府県民税の所得割の税率の分母", period),
        }
        p = {"調整": parameters(period).住民税.調整控除, "控除": parameters(period).住民税.税額控除, "率": parameters(period).住民税.税率}
        results = _chain(v, p)
        exact = [r.total("filing_special") if r is not None else Fraction(0) for r in results]
        if all(x.denominator == 1 for x in exact):
            return _yen(exact, "住民税_申告特例控除の額")
        return _rounded(exact, 人("住民税_税額控除の額の端数の候補", period))


class 住民税_配当割額等の控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配当割額・株式等譲渡所得割額の控除の額（第314条の9・第37条の4。控除できた額。最後に控除する）"
    reference = [f"{_EXTRA}#2.1"]

    def formula(人, period, parameters):
        課税される = _taxed(人("住民税_賦課期日に住所を有する市町村", period), 人("住民税_第295条第1項の非課税に当たるか", period), 人("住民税_所得割を課さない者か", period))
        if not 課税される.any():
            return np.zeros(len(課税される), dtype=np.int32)
        v = {
            "課税される": 課税される,
            "課税": 人("住民税_課税総所得金額等", period),
            "分離配当": 人("住民税_上場株式等に係る課税配当所得等の金額", period),
            "分離譲渡": 人("住民税_上場株式等に係る課税譲渡所得等の金額", period),
            "合計": 人("住民税_合計所得金額", period),
            "総所得等": 人("住民税_総所得金額等", period),
            "人的": 人("住民税_人的控除差の合計", period),
            "人的調整": 人("住民税_人的控除差調整額", period),
            "剰余金": 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period),
            "証券": 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period),
            "外貨": 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period),
            "住宅①": 人("所得税_住宅借入金等特別控除の額", period),
            "所得税額": 人("住民税_前年分の所得税の額", period),
            "限度の基": 人("住民税_住宅借入金等特別税額控除の控除限度の基", period),
            "寄附1号": 人("住民税_都道府県等に対する寄附金の額", period),
            "寄附市": 人("住民税_市町村民税の第2号から第4号までの寄附金の額", period),
            "寄附県": 人("住民税_道府県民税の第2号から第4号までの寄附金の額", period),
            "特定取得": 人("住民税_住宅借入金等特別税額控除の特定取得か", period),
            "分離所得": 人("住民税_上場株式等に係る分離課税の所得の金額", period),
            "特例": 人("住民税_特例控除対象寄附金の額", period),
            "申告特例": 人("住民税_申告特例控除の対象か", period),
            "配当割": 人("住民税_控除の対象の配当割額等", period),
            "非課税基準": 人("住民税_所得割の非課税の基準の額", period),
            "指定都市": 人("住民税_指定都市の区域内に住所を有するか", period),
            "市分子": 人("住民税_市町村民税の所得割の税率の分子", period),
            "市分母": 人("住民税_市町村民税の所得割の税率の分母", period),
            "県分子": 人("住民税_道府県民税の所得割の税率の分子", period),
            "県分母": 人("住民税_道府県民税の所得割の税率の分母", period),
        }
        p = {"調整": parameters(period).住民税.調整控除, "控除": parameters(period).住民税.税額控除, "率": parameters(period).住民税.税率}
        results = _chain(v, p)
        exact = [r.total("withheld") if r is not None else Fraction(0) for r in results]
        if all(x.denominator == 1 for x in exact):
            return _yen(exact, "住民税_配当割額等の控除の額")
        return _rounded(exact, 人("住民税_税額控除の額の端数の候補", period))


class 住民税_配当割額等の控除不足額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配当割額等の控除しきれなかった額（第314条の9第2項：同じ年度分の住民税・森林環境税に充当し、残りは還付。充当の後の額はコアの外）"
    reference = [f"{_EXTRA}#2.3"]

    def formula(人, period, parameters):
        課税される = _taxed(人("住民税_賦課期日に住所を有する市町村", period), 人("住民税_第295条第1項の非課税に当たるか", period), 人("住民税_所得割を課さない者か", period))
        if not 課税される.any():
            return np.zeros(len(課税される), dtype=np.int32)
        v = {
            "課税される": 課税される,
            "課税": 人("住民税_課税総所得金額等", period),
            "分離配当": 人("住民税_上場株式等に係る課税配当所得等の金額", period),
            "分離譲渡": 人("住民税_上場株式等に係る課税譲渡所得等の金額", period),
            "合計": 人("住民税_合計所得金額", period),
            "総所得等": 人("住民税_総所得金額等", period),
            "人的": 人("住民税_人的控除差の合計", period),
            "人的調整": 人("住民税_人的控除差調整額", period),
            "剰余金": 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period),
            "証券": 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period),
            "外貨": 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period),
            "住宅①": 人("所得税_住宅借入金等特別控除の額", period),
            "所得税額": 人("住民税_前年分の所得税の額", period),
            "限度の基": 人("住民税_住宅借入金等特別税額控除の控除限度の基", period),
            "寄附1号": 人("住民税_都道府県等に対する寄附金の額", period),
            "寄附市": 人("住民税_市町村民税の第2号から第4号までの寄附金の額", period),
            "寄附県": 人("住民税_道府県民税の第2号から第4号までの寄附金の額", period),
            "特定取得": 人("住民税_住宅借入金等特別税額控除の特定取得か", period),
            "分離所得": 人("住民税_上場株式等に係る分離課税の所得の金額", period),
            "特例": 人("住民税_特例控除対象寄附金の額", period),
            "申告特例": 人("住民税_申告特例控除の対象か", period),
            "配当割": 人("住民税_控除の対象の配当割額等", period),
            "非課税基準": 人("住民税_所得割の非課税の基準の額", period),
            "指定都市": 人("住民税_指定都市の区域内に住所を有するか", period),
            "市分子": 人("住民税_市町村民税の所得割の税率の分子", period),
            "市分母": 人("住民税_市町村民税の所得割の税率の分母", period),
            "県分子": 人("住民税_道府県民税の所得割の税率の分子", period),
            "県分母": 人("住民税_道府県民税の所得割の税率の分母", period),
        }
        p = {"調整": parameters(period).住民税.調整控除, "控除": parameters(period).住民税.税額控除, "率": parameters(period).住民税.税率}
        results = _chain(v, p)
        exact = [r.total("shortfall") if r is not None else Fraction(0) for r in results]
        if all(x.denominator == 1 for x in exact):
            return _yen(exact, "住民税_配当割額等の控除不足額")
        return _rounded(exact, 人("住民税_税額控除の額の端数の候補", period))


class 住民税_均等割の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "均等割の額（市町村民税・道府県民税の合計。住所地の均等割〔第311条の軽減の後〕と、家屋敷課税の均等割。税率は注入データ。"
        "住所地の分は所得割と合わせた確定金額の百円未満の切捨ての差を含む：calc.per_capita_with_income_levy）"
    )
    reference = [f"{_LAW}#13", f"{_LAW}#15", f"{_EXTRA}#1.1", f"{_EXTRA}#1.7"]

    def formula(人, period, parameters):
        unit = int(parameters(period).住民税.税率.端数.確定金額の単位)
        住所地 = 人("住民税_住所地の均等割を課すか", period)
        市 = 人("住民税_軽減後の市町村民税の均等割の税率", period)
        県 = 人("住民税_道府県民税の均等割の税率", period)
        端数 = np.zeros((2, len(市)), dtype=np.int64)
        課税される = _taxed(人("住民税_賦課期日に住所を有する市町村", period), 人("住民税_第295条第1項の非課税に当たるか", period), 人("住民税_所得割を課さない者か", period))
        if (課税される & ((市 % unit != 0) | (県 % unit != 0))).any():
            # 均等割の税率が百円の倍数でない団体：所得割の額の百円未満の部分が要る（第294条第1項第1号・第20条の4の2第3項）
            v = {
                "課税される": 課税される,
                "課税": 人("住民税_課税総所得金額等", period),
                "分離配当": 人("住民税_上場株式等に係る課税配当所得等の金額", period),
                "分離譲渡": 人("住民税_上場株式等に係る課税譲渡所得等の金額", period),
                "合計": 人("住民税_合計所得金額", period),
                "総所得等": 人("住民税_総所得金額等", period),
                "人的": 人("住民税_人的控除差の合計", period),
                "人的調整": 人("住民税_人的控除差調整額", period),
                "剰余金": 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period),
                "証券": 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period),
                "外貨": 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period),
                "住宅①": 人("所得税_住宅借入金等特別控除の額", period),
                "所得税額": 人("住民税_前年分の所得税の額", period),
                "限度の基": 人("住民税_住宅借入金等特別税額控除の控除限度の基", period),
                "寄附1号": 人("住民税_都道府県等に対する寄附金の額", period),
                "寄附市": 人("住民税_市町村民税の第2号から第4号までの寄附金の額", period),
                "寄附県": 人("住民税_道府県民税の第2号から第4号までの寄附金の額", period),
                "特定取得": 人("住民税_住宅借入金等特別税額控除の特定取得か", period),
                "分離所得": 人("住民税_上場株式等に係る分離課税の所得の金額", period),
                "特例": 人("住民税_特例控除対象寄附金の額", period),
                "申告特例": 人("住民税_申告特例控除の対象か", period),
                "配当割": 人("住民税_控除の対象の配当割額等", period),
                "非課税基準": 人("住民税_所得割の非課税の基準の額", period),
                "指定都市": 人("住民税_指定都市の区域内に住所を有するか", period),
                "市分子": 人("住民税_市町村民税の所得割の税率の分子", period),
                "市分母": 人("住民税_市町村民税の所得割の税率の分母", period),
                "県分子": 人("住民税_道府県民税の所得割の税率の分子", period),
                "県分母": 人("住民税_道府県民税の所得割の税率の分母", period),
            }
            p = {"調整": parameters(period).住民税.調整控除, "控除": parameters(period).住民税.税額控除, "率": parameters(period).住民税.税率}
            for i, r in enumerate(_chain(v, p)):
                if r is not None:
                    端数[0][i], 端数[1][i] = r.municipal.fraction, r.prefectural.fraction
        住所地の額 = [
            calc.per_capita_with_income_levy(int(m), int(f0), unit) + calc.per_capita_with_income_levy(int(q), int(f1), unit) if c else 0
            for c, m, q, f0, f1 in zip(住所地, 市, 県, 端数[0], 端数[1])
        ]
        return _yen(np.asarray(住所地の額, dtype=np.int64) + 人("住民税_家屋敷課税の均等割の額", period), "均等割の額")


class 住民税_森林環境税の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "森林環境税の額（1,000円。施行地に住所を有する個人。事務所・家屋敷だけの者は課さない。均等割の軽減・減免は及ばない）"
    reference = [f"{_LAW}#14"]

    def formula(人, period, parameters):
        額 = int(parameters(period).住民税.森林環境税.額)
        住所 = _domiciled(人("住民税_賦課期日に住所を有する市町村", period))
        return np.where(住所 & ~人("住民税_森林環境税を課さない者か", period), 額, 0).astype(np.int32)


class 住民税_退職所得の分離課税に係る所得割の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "その年（所得の年分）中に支払を受けるべき退職手当等の分離課税に係る所得割の額（第328条〜第328条の3：退職所得の金額の千円未満切捨て×6%・4%、"
        "それぞれ百円未満切捨て。その年の1月1日の住所の市町村が課する。年度 F の値は F−1 年中の支払の分）"
    )
    reference = [f"{_LAW}#12", f"{_TAISHOKU}#6.3"]

    def formula(人, period, parameters):
        率 = parameters(period).住民税.税率
        住所 = 人("住民税_退職手当等の支払を受けるべき年の1月1日に住所を有する市町村", period) != ""
        課す = 住所 & ~人("住民税_退職手当等の支払を受けるべき年の1月1日に生活扶助を受けているか", period)
        金額 = 人("住民税_分離課税に係る退職所得の金額", period)
        return _yen((calc.retirement_separate_tax(int(x), 率) if c else 0 for c, x in zip(課す, 金額)), "分離課税に係る所得割の額")


# ---------------------------------------------------------------------------
# 確定申告書 第二表「住民税に関する事項」の寄附金の欄（2026-11-12。forms が年分＋1 の年度の値として読む）
# 令和7年分 確定申告の手引き 手順6（docs/public-sources/20261112_impl-research6_forms-jumin-kifu.md）。
# ---------------------------------------------------------------------------


class 住民税_第二表の特例控除対象の寄附金の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "第二表「都道府県、市区町村への寄附（特例控除対象）」：都道府県・市区町村への寄附金のうち、寄附の日に総務大臣の指定を受けた団体へのもの（特例控除対象寄附金）"
    reference = [f"{_FKIFU}#1", f"{_LAW}#8.1"]

    def formula(人, period, parameters):
        return _yen(人("住民税_特例控除対象寄附金の額", period), "特例控除対象の寄附金の額")


class 住民税_第二表の共同募金日赤その他の寄附金の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "第二表「共同募金、日赤その他の寄附」：住所地の共同募金会・日本赤十字社支部への寄附金（第2号）と、"
        "総務大臣の指定のない都道府県・市区町村への寄附金（都道府県等に対する寄附金−特例控除対象寄附金）"
    )
    reference = [f"{_FKIFU}#1", f"{_LAW}#8.1"]

    def formula(人, period, parameters):
        指定なし = 人("住民税_都道府県等に対する寄附金の額", period).astype(np.int64) - 人("住民税_特例控除対象寄附金の額", period)
        return _yen(人("住民税_第2号の寄附金の額", period).astype(np.int64) + 指定なし, "共同募金・日赤その他の寄附金の額")


class 住民税_第二表の都道府県条例指定寄附の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "第二表「都道府県条例指定寄附」：住所地の都道府県が条例で指定した寄附金（第37条の2第1項第3号・第4号。第2号〜第4号の額−第2号の額）"
    reference = [f"{_FKIFU}#1", f"{_JM3}#1"]

    def formula(人, period, parameters):
        return _yen(人("住民税_道府県民税の第2号から第4号までの寄附金の額", period).astype(np.int64) - 人("住民税_第2号の寄附金の額", period), "都道府県条例指定寄附の額")


class 住民税_第二表の市区町村条例指定寄附の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "第二表「市区町村条例指定寄附」：住所地の市区町村が条例で指定した寄附金（第314条の7第1項第3号・第4号。第2号〜第4号の額−第2号の額）"
    reference = [f"{_FKIFU}#1", f"{_JM3}#1"]

    def formula(人, period, parameters):
        return _yen(人("住民税_市町村民税の第2号から第4号までの寄附金の額", period).astype(np.int64) - 人("住民税_第2号の寄附金の額", period), "市区町村条例指定寄附の額")


VARIABLES: tuple[type, ...] = INPUTS + JUDGMENT_VIEWS + (
    住民税_分離課税に係る退職所得の金額,
    住民税_合計所得金額,
    住民税_総所得金額等,
    住民税_繰り越された雑損失の金額,
    住民税_繰り越された純損失の金額,
    住民税_損失の繰越が所得税と違うか,
    住民税_雑損失の繰越控除額,
    住民税_雑損失の繰越控除の後の総所得金額,
    住民税_雑損失の繰越控除の後の上場株式等に係る配当所得等の金額,
    住民税_雑損失の繰越控除の後の上場株式等に係る譲渡所得等の金額,
    住民税_事業専従者給与等の額,
    住民税_上場株式等に係る分離課税の所得の金額,
    住民税_上場株式等の譲渡損失の繰越控除額,
    住民税_総所得金額等に含まれる退職所得金額,
    住民税_公的年金等に係る所得の金額,
    住民税_65歳以上の者に係る公的年金等控除額の控除を受けたか,
    住民税_給与等の収入金額,
    住民税_公的年金等の収入金額,
    住民税_給与所得の金額,
    住民税_非課税の判定で数える扶養親族か,
    住民税_同一生計配偶者及び扶養親族の数,
    住民税_第295条第1項の非課税に当たるか,
    住民税_第295条第1項の合計所得金額要件,
    住民税_非課税の判定で寡婦に当たるか,
    住民税_所得割の非課税の基準の額,
    住民税_所得割を課さない者か,
    住民税_均等割の非課税の基準の額,
    住民税_均等割の非課税の合計所得金額要件,
    住民税_均等割を課さない者か,
    住民税_住所地の均等割を課すか,
    住民税_森林環境税を課さない者か,
    住民税_人的控除差の扶養親族の1人分の額,
    住民税_人的控除差の合計,
    住民税_配偶者特別控除の対象か,
    住民税_扶養控除の1人分の額,
    住民税_特定親族特別控除の1人分の額,
    住民税_障害者控除の扶養親族の1人分の額,
    住民税_扶養控除の額,
    住民税_特定親族特別控除の額,
    住民税_障害者控除の額,
    住民税_寡婦控除の額,
    住民税_ひとり親控除の額,
    住民税_勤労学生控除の額,
    住民税_配偶者控除の額,
    住民税_配偶者特別控除の額,
    住民税_基礎控除の額,
    住民税_社会保険料控除の額,
    住民税_小規模企業共済等掛金控除の額,
    住民税_生命保険料控除の額,
    住民税_地震保険料控除の額,
    住民税_医療費控除の額,
    住民税_雑損控除の額,
    住民税_所得控除の合計,
    住民税_課税総所得金額等,
    住民税_上場株式等に係る課税配当所得等の金額,
    住民税_上場株式等に係る課税譲渡所得等の金額,
    住民税_人的控除差調整額,
    住民税_前年分の所得税の額,
    住民税_住宅借入金等特別税額控除の控除限度の基,
    住民税_調整控除の額,
    住民税_所得割の額,
    住民税_配当控除の額,
    住民税_住宅借入金等特別税額控除の額,
    住民税_寄附金税額控除の額,
    住民税_申告特例控除の額,
    住民税_配当割額等の控除の額,
    住民税_配当割額等の控除不足額,
    住民税_均等割の額,
    住民税_森林環境税の額,
    住民税_退職所得の分離課税に係る所得割の額,
    住民税_第二表の特例控除対象の寄附金の額,
    住民税_第二表の共同募金日赤その他の寄附金の額,
    住民税_第二表の都道府県条例指定寄附の額,
    住民税_第二表の市区町村条例指定寄附の額,
)
