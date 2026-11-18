"""R2: OpenFisca-Core 46.0.1 の実測（モデルの表現力、期間、パラメータ、改正、YAML テスト、Web API の安全性）。

## 仮想環境の作り方（リポジトリのルートで。PyPI の wheel だけ、版を固定）
    uv venv .work/venvs/R2-openfisca --python 3.11
    uv pip install --python .work/venvs/R2-openfisca/Scripts/python.exe --only-binary :all: "openfisca-core[web-api]==46.0.1"
  依存の版は scripts/results/R2_openfisca_deps_osv/freeze.txt（bash scripts/R2_openfisca_deps_osv.sh で再取得）。

## 実行方法（リポジトリのルートで）
    .work/venvs/R2-openfisca/Scripts/python.exe -I scripts/R2_openfisca_check.py            # 既定のエンコーディング（Windows では cp932）
    .work/venvs/R2-openfisca/Scripts/python.exe -I -X utf8 scripts/R2_openfisca_check.py    # UTF-8 モード
  出力: scripts/results/R2_openfisca_check/results_<utf8|locale>.json と summary_<utf8|locale>.txt

## 方針
- 試験用の国パッケージ（r2_test_country）は、このスクリプトが一時ディレクトリに自分で書き出す。ダウンロードしたコードは使わない。
- パラメータの値は **ダミー値**（100, 200, 300）。法令の基準額ではない。
- Web API は Flask アプリ（openfisca_web_api.app.create_app）を werkzeug の開発用サーバーで 127.0.0.1 の空きポートに
  立てて確かめ、終わったら止める（Windows では gunicorn が動かないため。結果の T13 を参照）。
- 危険な YAML の確認では、副作用は一時ディレクトリにファイルを1つ作るだけにする。
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODE = "utf8" if sys.flags.utf8_mode else "locale"
OUT = ROOT / "scripts" / "results" / "R2_openfisca_check"
RESULTS: dict[str, object] = {}

TMP = pathlib.Path(tempfile.mkdtemp(prefix="r2_openfisca_"))
PKG = TMP / "r2_test_country"

ENTITIES_PY = '''
from openfisca_core.entities import build_entity

人物 = build_entity(key="人物", plural="人物一覧", label="人（試験用）", is_person=True)
生計 = build_entity(key="生計", plural="生計一覧", label="生計の単位（試験用）", roles=[
    {"key": "生計維持者", "plural": "生計維持者一覧", "max": 1},
    {"key": "生計構成員", "plural": "生計構成員一覧"},
])
住民票世帯 = build_entity(key="住民票世帯", plural="住民票世帯一覧", label="住民票上の世帯（試験用）", roles=[
    {"key": "世帯主", "plural": "世帯主一覧", "max": 1},
    {"key": "世帯員", "plural": "世帯員一覧"},
])
健康保険 = build_entity(key="健康保険", plural="健康保険一覧", label="被保険者とその被扶養者（試験用）", roles=[
    {"key": "被保険者", "plural": "被保険者一覧", "max": 1},
    {"key": "被扶養者", "plural": "被扶養者一覧"},
])
申告 = build_entity(key="申告", plural="申告一覧", label="申告する人と扶養親族（試験用）", roles=[
    {"key": "納税者", "plural": "納税者一覧", "max": 1},
    {"key": "扶養親族", "plural": "扶養親族一覧"},
])
entities = [人物, 生計, 住民票世帯, 健康保険, 申告]
'''

VARIABLES_PY = '''
from datetime import date

import numpy as np

from openfisca_core import periods
from openfisca_core.model_api import (ADD, DAY, ETERNITY, MONTH, YEAR, Enum, Variable,
                                      set_input_divide_by_period)
from r2_test_country.entities import 人物, 生計, 住民票世帯, 健康保険, 申告


class 生年月日(Variable):
    value_type = date
    entity = 人物
    definition_period = ETERNITY
    default_value = date(1970, 1, 1)
    label = "生年月日"


class 給与収入(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR
    label = "給与の支払金額（試験用）"


class 月額収入(Variable):
    value_type = float
    entity = 人物
    definition_period = MONTH
    set_input = set_input_divide_by_period
    label = "月ごとの収入（試験用）"


class 年収_月額の合計(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("月額収入", period, options=[ADD])


class 見込み年収_当月から12か月(Variable):
    value_type = float
    entity = 人物
    definition_period = MONTH

    def formula(人, period, parameters):
        return 人("月額収入", periods.period(f"year:{period.start}"), options=[ADD])


class 満年齢_日(Variable):
    """暦の上で誕生日を過ぎたかで数える試験用の年齢（法的な年齢計算ではない）。"""
    value_type = int
    entity = 人物
    definition_period = DAY

    def formula(人, period, parameters):
        b = 人("生年月日", period)
        by = b.astype("datetime64[Y]").astype(int) + 1970
        bm = b.astype("datetime64[M]").astype(int) % 12 + 1
        bd = (b - b.astype("datetime64[M]")).astype(int) + 1
        s = period.start
        not_yet = (bm > s.month) | ((bm == s.month) & (bd > s.day))
        return s.year - by - not_yet


class 満年齢_年末(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("満年齢_日", periods.period(f"day:{period.stop}"))


class 生計_給与収入合計(Variable):
    value_type = float
    entity = 生計
    definition_period = YEAR

    def formula(g, period, parameters):
        return g.sum(g.members("給与収入", period))


class 住民票世帯_人数(Variable):
    value_type = int
    entity = 住民票世帯
    definition_period = YEAR

    def formula(g, period, parameters):
        return g.nb_persons()


class 健保_被扶養者数(Variable):
    value_type = int
    entity = 健康保険
    definition_period = YEAR

    def formula(g, period, parameters):
        return g.nb_persons(role=健康保険.被扶養者)


class 健保_被保険者の給与収入(Variable):
    value_type = float
    entity = 健康保険
    definition_period = YEAR

    def formula(g, period, parameters):
        return g.value_from_person(g.members("給与収入", period), role=健康保険.被保険者)


class 申告_扶養親族数(Variable):
    value_type = int
    entity = 申告
    definition_period = YEAR

    def formula(g, period, parameters):
        return g.nb_persons(role=申告.扶養親族)


class 本人_生計の給与収入合計(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.生計("生計_給与収入合計", period)


class 本人_住民票世帯の人数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.住民票世帯("住民票世帯_人数", period)


class 本人_健保で被扶養者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.has_role(健康保険.被扶養者)


class 本人_健保の被保険者の給与収入(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.健康保険("健保_被保険者の給与収入", period)


class 本人_申告で納税者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.has_role(申告.納税者)


class ダミー判定_所得要件以下(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("給与収入", period) <= parameters(period).ダミー.所得要件


class 試験_施行日で式を切替(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR

    def formula_2020_01_01(人, period, parameters):
        return 人("給与収入", period) * 0 + 1

    def formula_2025_01_01(人, period, parameters):
        return 人("給与収入", period) * 0 + 2


class 所得区分の例(Enum):
    給与 = "給与所得（試験用の列挙値）"
    事業 = "事業所得（試験用の列挙値）"


class 試験_列挙型(Variable):
    value_type = Enum
    possible_values = 所得区分の例
    default_value = 所得区分の例.給与
    entity = 人物
    definition_period = YEAR


class 循環A(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("循環B", period)


class 循環B(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("循環A", period)


class 前年までの累積(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("前年までの累積", period.last_year) + 1
'''

INIT_PY = '''
import os

from openfisca_core.taxbenefitsystems import TaxBenefitSystem

from r2_test_country import entities

HERE = os.path.dirname(os.path.abspath(__file__))


class CountryTaxBenefitSystem(TaxBenefitSystem):
    def __init__(self):
        super().__init__(entities.entities)
        self.add_variables_from_file(os.path.join(HERE, "variables.py"))
        self.load_parameters(os.path.join(HERE, "parameters"))
'''

PARAM_YAML = '''description: 試験用のダミー値（法令の値ではない）
values:
  2020-01-01:
    value: 100
  2025-01-01:
    value: 200
metadata:
  reference: 試験用（出典なし）
'''

TEST_YAML = '''- name: 日本語の変数名でのテスト（施行後）
  period: 2025
  input:
    給与収入: 150
  output:
    ダミー判定_所得要件以下: true
- name: 施行前は旧値で判定される
  period: 2024
  input:
    給与収入: 150
  output:
    ダミー判定_所得要件以下: false
- name: グループと役割を YAML テストで書く
  period: 2025
  input:
    人物一覧:
      父: {給与収入: 500}
      子: {給与収入: 100}
    生計一覧:
      g1: {生計維持者一覧: [父], 生計構成員一覧: [子]}
    健康保険一覧:
      k1: {被保険者一覧: [父], 被扶養者一覧: [子]}
  output:
    本人_生計の給与収入合計: [600, 600]
    健保_被扶養者数: [1]
- name: 意図的に失敗させる（テストが失敗を検出するか）
  period: 2025
  input:
    給与収入: 150
  output:
    ダミー判定_所得要件以下: false
'''


def write_package() -> None:
    (PKG / "parameters" / "ダミー").mkdir(parents=True)
    (PKG / "__init__.py").write_text(INIT_PY, encoding="utf-8")
    (PKG / "entities.py").write_text(ENTITIES_PY, encoding="utf-8")
    (PKG / "variables.py").write_text(VARIABLES_PY, encoding="utf-8")
    (PKG / "parameters" / "ダミー" / "所得要件.yaml").write_text(PARAM_YAML, encoding="utf-8")
    (TMP / "tests").mkdir()
    (TMP / "tests" / "試験.yaml").write_text(TEST_YAML, encoding="utf-8")


def record(key: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        value = fn()
        RESULTS[key] = {"ok": True, "result": value, "seconds": round(time.perf_counter() - t0, 3)}
    except BaseException as e:  # noqa: BLE001  実測なので例外も結果として記録する
        RESULTS[key] = {"ok": False, "error_type": type(e).__name__, "error": str(e)[:2000],
                        "traceback_tail": traceback.format_exc().splitlines()[-6:],
                        "seconds": round(time.perf_counter() - t0, 3)}
    print(f"[{key}] {'ok' if RESULTS[key]['ok'] else 'NG'}", flush=True)


# ---------------------------------------------------------------- 基本のシナリオ
# 父（会社員・被保険者・納税者）、母（自分の健康保険の被保険者）、子（20歳、大学生。親と別に住民票を置く）。
# 子は 生計=父と同じ、住民票世帯=単独、健康保険=父の被扶養者、申告=父の扶養親族。
SITUATION = {
    "人物一覧": {
        "父": {"生年月日": {"ETERNITY": "1970-05-01"}, "給与収入": {"2025": 5000}},
        "母": {"生年月日": {"ETERNITY": "1972-03-01"}, "給与収入": {"2025": 1200}},
        "子": {"生年月日": {"ETERNITY": "2005-12-31"}, "給与収入": {"2025": 100}},
    },
    "生計一覧": {"生計1": {"生計維持者一覧": ["父"], "生計構成員一覧": ["母", "子"]}},
    "住民票世帯一覧": {
        "世帯A": {"世帯主一覧": ["父"], "世帯員一覧": ["母"]},
        "世帯B": {"世帯主一覧": ["子"]},
    },
    "健康保険一覧": {
        "父の健保": {"被保険者一覧": ["父"], "被扶養者一覧": ["子"]},
        "母の健保": {"被保険者一覧": ["母"]},
    },
    "申告一覧": {
        "父の申告": {"納税者一覧": ["父"], "扶養親族一覧": ["子"]},
        "母の申告": {"納税者一覧": ["母"]},
    },
}

PERSON_VARS = ["本人_生計の給与収入合計", "本人_住民票世帯の人数", "本人_健保で被扶養者か",
               "本人_健保の被保険者の給与収入", "本人_申告で納税者か", "満年齢_年末"]


def deep(o):
    return json.loads(json.dumps(o))


def tolist(a):
    try:
        return a.tolist()
    except AttributeError:
        return a


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_package()
    sys.path.insert(0, str(TMP))
    RESULTS["env"] = {"python": sys.version, "utf8_mode": sys.flags.utf8_mode, "isolated": sys.flags.isolated,
                      "preferred_encoding": __import__("locale").getpreferredencoding(False), "tmp": str(TMP)}
    import numpy as np  # noqa: F401
    import openfisca_core
    import yaml
    from importlib.metadata import version
    RESULTS["versions"] = {p: version(p) for p in ["openfisca-core", "flask", "flask-cors", "werkzeug", "gunicorn",
                                                    "numexpr", "numpy", "pyyaml"]}
    RESULTS["pyyaml_has_libyaml"] = bool(getattr(yaml, "__with_libyaml__", False))
    from openfisca_core.parameters import config as pconfig
    RESULTS["parameter_yaml_loader"] = f"{pconfig.Loader.__module__}.{pconfig.Loader.__name__}"
    from openfisca_core.tools import test_runner
    RESULTS["test_yaml_loader"] = f"{test_runner.Loader.__module__}.{test_runner.Loader.__name__}"

    from openfisca_core.simulations import SimulationBuilder

    tbs_holder = {}

    def t00_load():
        from r2_test_country import CountryTaxBenefitSystem
        tbs_holder["tbs"] = CountryTaxBenefitSystem()
        tbs = tbs_holder["tbs"]
        return {"entities": [e.key for e in tbs.entities],
                "roles": {e.key: [r.key for r in e.roles] for e in tbs.entities if not e.is_person},
                "n_variables": len(tbs.variables),
                "parameter_2025": float(tbs.parameters("2025-01-01").ダミー.所得要件)}
    record("T00_日本語の名前でパッケージを読み込む", t00_load)
    if "tbs" not in tbs_holder:
        finish()
        return
    tbs = tbs_holder["tbs"]

    def simulate(situation, variables, period="2025"):
        sim = SimulationBuilder().build_from_entities(tbs, deep(situation))
        return {v: tolist(sim.calculate(v, period)) for v in variables}

    # T01: 複数グループ、1人が複数（種類の違う）グループ、生計と住民票世帯の不一致
    def t01():
        sim = SimulationBuilder().build_from_entities(tbs, deep(SITUATION))
        out = {"人物の順": sim.persons.ids}
        for v in PERSON_VARS:
            out[v] = tolist(sim.calculate(v, "2025"))
        for ent, v in [("生計", "生計_給与収入合計"), ("住民票世帯", "住民票世帯_人数"),
                       ("健康保険", "健保_被扶養者数"), ("申告", "申告_扶養親族数")]:
            pop = sim.populations[ent]
            out[f"{ent}:{v}"] = dict(zip(pop.ids, tolist(sim.calculate(v, "2025"))))
        out["役割（エンティティごと、人物の順）"] = {
            e: [str(r.key) for r in sim.populations[e].members_role] for e in ["生計", "住民票世帯", "健康保険", "申告"]}
        return out
    record("T01_複数グループ_1人が複数グループ", t01)

    # T02: 同じ種類のグループの2つのインスタンスに同じ人を入れる
    def t02():
        s = deep(SITUATION)
        s["健康保険一覧"]["母の健保"]["被扶養者一覧"] = ["子"]  # 子が父と母の両方の健保の被扶養者
        return simulate(s, ["健保_被扶養者数"])
    record("T02_同じ種類のグループ2つに同じ人", t02)

    # T03: 1つのグループで1人に2つの役割
    def t03():
        s = deep(SITUATION)
        s["生計一覧"]["生計1"]["生計構成員一覧"] = ["母", "子", "父"]  # 父が 生計維持者 と 生計構成員 の両方
        return simulate(s, ["生計_給与収入合計"])
    record("T03_1グループ内で1人に2つの役割", t03)

    # T04: グループに割り当てなかった人の扱い
    def t04():
        s = deep(SITUATION)
        s["人物一覧"]["祖母"] = {"給与収入": {"2025": 0}}
        sim = SimulationBuilder().build_from_entities(tbs, s)
        hk = sim.populations["健康保険"]
        return {"健康保険のインスタンス": hk.ids,
                "人物ごとの健康保険の役割": dict(zip(sim.persons.ids, [str(r.key) for r in hk.members_role])),
                "本人_健保で被扶養者か": dict(zip(sim.persons.ids, tolist(sim.calculate("本人_健保で被扶養者か", "2025"))))}
    record("T04_割り当てなかった人", t04)

    # T05: 役割の上限（max）
    def t05():
        s = deep(SITUATION)
        s["住民票世帯一覧"]["世帯A"] = {"世帯主一覧": ["父", "母"]}  # max=1 の役割に2人
        return simulate(s, ["住民票世帯_人数"])
    record("T05_役割の上限max", t05)

    # T14: グループの所属に期間をつけられるか（年の途中で被扶養者になる、など）
    def t14():
        s = deep(SITUATION)
        s["健康保険一覧"]["父の健保"]["被扶養者一覧"] = {"2025-10": ["子"]}  # 期間つきで書いてみる
        return simulate(s, ["健保_被扶養者数"])
    record("T14_所属に期間をつける", t14)

    def t14b():
        sim = SimulationBuilder().build_from_entities(tbs, deep(SITUATION))
        hk = sim.populations["健康保険"]
        return {"members_entity_id の型と形": [type(hk.members_entity_id).__name__, list(hk.members_entity_id.shape)],
                "members_role の長さ": len(hk.members_role),
                "注": "所属と役割は人物ごとに1つの配列で、期間の次元を持たない"}
    record("T14b_所属の内部表現", t14b)

    # T06: 期間
    def t06():
        s = {"人物一覧": {"子": {"生年月日": {"ETERNITY": "2005-12-31"},
                                 "月額収入": {f"2025-{m:02d}": 10 * m for m in range(1, 13)} | {"2026-01": 1000}}}}
        sim = SimulationBuilder().build_from_entities(tbs, s)
        s2 = {"人物一覧": {"年額入力": {"月額収入": {"2025": 1200}}}}
        sim2 = SimulationBuilder().build_from_entities(tbs, s2)
        return {
            "入力（子の月額収入）": "2025-01〜12 に 10,20,...,120、2026-01 に 1000",
            "年収_月額の合計 2025": tolist(sim.calculate("年収_月額の合計", "2025")),
            "見込み年収 2025-10（2025-10〜2026-09）": tolist(sim.calculate("見込み年収_当月から12か月", "2025-10")),
            "月額収入 2025-03（年額1200を入れた別のシミュレーション）": tolist(sim2.calculate("月額収入", "2025-03")),
            "満年齢_日 2025-12-30": tolist(sim.calculate("満年齢_日", "2025-12-30")),
            "満年齢_日 2025-12-31": tolist(sim.calculate("満年齢_日", "2025-12-31")),
            "満年齢_年末 2025": tolist(sim.calculate("満年齢_年末", "2025")),
            "期間の文字列 year:2025-10 の start/stop": [str(__import__("openfisca_core").periods.period("year:2025-10").start),
                                                       str(__import__("openfisca_core").periods.period("year:2025-10").stop)],
        }
    record("T06_期間", t06)

    def t06b():
        s = {"人物一覧": {"子": {"月額収入": {"2025-01": 10}}}}
        sim = SimulationBuilder().build_from_entities(tbs, s)
        return tolist(sim.calculate("月額収入", "2025"))  # MONTH の変数を YEAR で直接求める
    record("T06b_月の変数を年で直接求める", t06b)

    def t06x():
        s = {"人物一覧": {"子": {"月額収入": {f"2025-{m:02d}": 10 for m in range(1, 13)}},
                          "年額入力": {"月額収入": {"2025": 1200}}}}  # 人によって入力の粒度（月・年）が違う
        return simulate(s, ["月額収入"], "2025-03")
    record("T06x_人ごとに入力の粒度を混ぜる", t06x)

    def t06c():
        s = {"人物一覧": {"子": {"給与収入": {"2025-01": 10}}}}  # YEAR の変数に月で入力
        return simulate(s, ["給与収入"])
    record("T06c_年の変数に月で入力", t06c)

    # T07: パラメータの施行日
    def t07():
        out = {}
        for inst in ["2019-12-31", "2020-01-01", "2024-12-31", "2025-01-01", "2030-01-01"]:
            try:
                out[inst] = float(tbs.parameters(inst).ダミー.所得要件)
            except Exception as e:  # noqa: BLE001
                out[inst] = f"{type(e).__name__}: {e}"[:300]
        s = {"人物一覧": {"子": {"給与収入": {"2019": 150, "2024": 150, "2025": 150}}}}
        sim = SimulationBuilder().build_from_entities(tbs, s)
        for y in ["2024", "2025"]:
            out[f"ダミー判定_所得要件以下 {y}（給与収入150）"] = tolist(sim.calculate("ダミー判定_所得要件以下", y))
        for y in ["2019", "2024", "2025"]:
            out[f"試験_施行日で式を切替 {y}"] = tolist(sim.calculate("試験_施行日で式を切替", y))
        try:
            out["ダミー判定 2019（パラメータの開始前）"] = tolist(sim.calculate("ダミー判定_所得要件以下", "2019"))
        except Exception as e:  # noqa: BLE001
            out["ダミー判定 2019（パラメータの開始前）"] = f"{type(e).__name__}: {e}"[:300]
        out["月の期間で年の変数を求めたとき"] = None
        try:
            sim.calculate("ダミー判定_所得要件以下", "2025-06")
        except Exception as e:  # noqa: BLE001
            out["月の期間で年の変数を求めたとき"] = f"{type(e).__name__}: {e}"[:300]
        return out
    record("T07_パラメータの施行日", t07)

    # T08: 改正（reform）
    def t08():
        from openfisca_core import periods
        from openfisca_core.model_api import Reform, Variable, YEAR
        from r2_test_country.entities import 人物

        class ダミー改正(Reform):
            def apply(self):
                def modify(parameters):
                    parameters.ダミー.所得要件.update(start=periods.instant("2026-01-01"), value=300)
                    return parameters
                self.modify_parameters(modifier_function=modify)

                class 試験_施行日で式を切替(Variable):
                    value_type = float
                    entity = 人物
                    definition_period = YEAR

                    def formula_2026_01_01(人, period, parameters):
                        return 人("給与収入", period) * 0 + 3
                self.update_variable(試験_施行日で式を切替)

        reformed = ダミー改正(tbs)
        out = {}
        for name, system in [("基準", tbs), ("改正後", reformed)]:
            s = {"人物一覧": {"子": {"給与収入": {"2025": 250, "2026": 250}}}}
            sim = SimulationBuilder().build_from_entities(system, s)
            out[name] = {y: {"所得要件": float(system.parameters(f"{y}-01-01").ダミー.所得要件),
                              "判定": tolist(sim.calculate("ダミー判定_所得要件以下", y)),
                              "式": tolist(sim.calculate("試験_施行日で式を切替", y))} for y in ["2025", "2026"]}
        return out
    record("T08_改正reform", t08)

    # T09: YAML テスト（openfisca test と同じ run_tests を呼ぶ。プロセス内で pytest が動く）
    def t09():
        code, lines = run_yaml_tests(tbs, TMP / "tests" / "試験.yaml")
        return {"exit_code": int(code), "pytest_summary": lines,
                "注": "4件のうち1件は意図的に失敗させている。3 passed, 1 failed なら期待どおり"}
    record("T09_YAMLテスト", t09)

    # T10: 危険な YAML タグ（パラメータとテスト）。副作用は一時ディレクトリにファイルを1つ作るだけ
    def t10():
        from openfisca_core.parameters import ParameterNode
        out = {}
        marker_p = TMP / "marker_parameter.txt"
        bad_dir = TMP / "bad_parameters"
        bad_dir.mkdir()
        (bad_dir / "危険.yaml").write_text(
            "description: 危険なタグの試験\nvalues:\n  2020-01-01:\n    value: !!python/object/apply:builtins.len "
            f"[[1, 2, 3]]\nmetadata:\n  x: !!python/object/apply:builtins.open [{json.dumps(str(marker_p))}, 'w']\n",
            encoding="utf-8")
        try:
            node = ParameterNode("bad", directory_path=str(bad_dir))
            out["parameter_load"] = "読み込めた"
            out["parameter_value_2020"] = float(node("2020-01-01").危険)
        except Exception as e:  # noqa: BLE001
            out["parameter_load"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["parameter_marker_created"] = marker_p.exists()
        marker_t = TMP / "marker_test.txt"
        bad_test = TMP / "bad_tests"
        bad_test.mkdir()
        (bad_test / "危険.yaml").write_text(
            f"- name: 危険なタグ\n  period: 2025\n  x: !!python/object/apply:builtins.open [{json.dumps(str(marker_t))}, 'w']\n"
            "  input: {給与収入: 1}\n  output: {給与収入: 1}\n", encoding="utf-8")
        code, lines = run_yaml_tests(tbs, bad_test / "危険.yaml")
        out["test_exit_code"] = int(code)
        out["test_pytest_summary"] = lines
        out["test_marker_created"] = marker_t.exists()
        return out
    record("T10_危険なYAMLタグ", t10)

    # T11: 数値の変数に文字列を入れると numexpr で評価される
    def t11():
        out = {}
        for expr in ["1000*2", "2**10", "__import__('os').getcwd()", "().__class__", "abs(-5)", "where(1>0, 7, 8)"]:
            try:
                s = {"人物一覧": {"子": {"給与収入": {"2025": expr}}}}
                out[expr] = simulate(s, ["給与収入"])["給与収入"]
            except Exception as e:  # noqa: BLE001
                out[expr] = f"{type(e).__name__}: {str(e)[:200]}"
        return out
    record("T11_文字列の入力とnumexpr", t11)

    run_web_api_checks(tbs)
    run_serve_check()
    finish()


def run_yaml_tests(tbs, path):
    """openfisca test（run_tests）と同じプラグインで pytest を動かし、要約行を返す。キャッシュは書かない。"""
    import contextlib
    import io

    import pytest

    from openfisca_core.tools.test_runner import OpenFiscaPlugin
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = pytest.main(["-p", "no:cacheprovider", "-q", "-rA", "--rootdir", str(path.parent), str(path)],
                           plugins=[OpenFiscaPlugin(tbs, {})])
    lines = [l for l in buf.getvalue().splitlines()
             if l.startswith(("PASSED", "FAILED", "ERROR")) or " passed" in l or " failed" in l or " error" in l]
    return code, lines[-12:]


# ---------------------------------------------------------------- Web API
def run_web_api_checks(tbs) -> None:
    import psutil
    from werkzeug.serving import make_server

    from openfisca_web_api.app import create_app

    app = create_app(tbs)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    proc = psutil.Process()
    RESULTS["web_api_server"] = {"bind": f"127.0.0.1:{port}", "server": "werkzeug.serving.make_server（開発用）"}

    def req(method, path, body=None, headers=None, timeout=600):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
        h = {"Content-Type": "application/json"} if data is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(base + path, data=data, method=method, headers=h)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                raw = resp.read()
                st, hd = resp.status, dict(resp.headers)
        except urllib.error.HTTPError as e:
            raw, st, hd = e.read(), e.code, dict(e.headers)
        return {"status": st, "headers": hd, "body": raw.decode("utf-8", "replace"),
                "seconds": round(time.perf_counter() - t0, 3)}

    def short(r, n=600):
        return {"status": r["status"], "seconds": r["seconds"], "body": r["body"][:n],
                "cors_headers": {k: v for k, v in r["headers"].items() if k.lower().startswith("access-control")}}

    try:
        record("T12a_GET_root", lambda: short(req("GET", "/")))
        record("T12b_GET_entities_日本語", lambda: short(req("GET", "/entities"), 1500))
        record("T12c_GET_variable_日本語URL", lambda: short(req("GET", "/variable/" + urllib.parse.quote("給与収入")), 800))
        record("T12d_GET_spec", lambda: (lambda r: {"status": r["status"], "bytes": len(r["body"]),
                                                    "日本語の変数名を含む（JSONを解釈して）": "給与収入" in json.dumps(json.loads(r["body"]), ensure_ascii=False)})(req("GET", "/spec")))

        def calc():
            s = deep(SITUATION)
            for p in s["人物一覧"].values():
                for v in PERSON_VARS:
                    p[v] = {"2025": None}
            s["健康保険一覧"]["父の健保"]["健保_被扶養者数"] = {"2025": None}
            s["人物一覧"]["子"]["試験_列挙型"] = {"2025": None}
            r = req("POST", "/calculate", s)
            return {"status": r["status"], "body": json.loads(r["body"]) if r["status"] == 200 else r["body"][:800]}
        record("T12e_POST_calculate_日本語", calc)

        record("T12f_CORS_preflight_外部オリジン", lambda: short(req("OPTIONS", "/calculate", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type", "Access-Control-Request-Private-Network": "true"})))
        record("T12g_CORS_POST_外部オリジン", lambda: short(req("POST", "/calculate", {
            "人物一覧": {"子": {"給与収入": {"2025": 1}, "ダミー判定_所得要件以下": {"2025": None}}}},
            headers={"Origin": "https://evil.example"})))
        record("T12h_Hostヘッダ", lambda: {"Host": short(req("GET", "/", headers={"Host": "evil.example"}))["body"],
                                          "X-Forwarded-Host": short(req("GET", "/", headers={"X-Forwarded-Host": "evil2.example"}))["body"]})

        def big_body():
            pad = "x" * (30 * 1024 * 1024)
            body = json.dumps({"人物一覧": {"子": {"給与収入": {"2025": 1}}}, "詰め物": pad}).encode("utf-8")
            r = req("POST", "/calculate", body)
            return {"sent_bytes": len(body), **short(r, 300)}
        record("T12i_30MBの要求本文", big_body)

        def axes(n):
            def f():
                rss0 = proc.memory_info().rss
                r = req("POST", "/calculate", {
                    "人物一覧": {"子": {"ダミー判定_所得要件以下": {"2025": None}}},
                    "生計一覧": {"g": {"生計維持者一覧": ["子"]}}, "住民票世帯一覧": {"h": {"世帯主一覧": ["子"]}},
                    "健康保険一覧": {"k": {"被保険者一覧": ["子"]}}, "申告一覧": {"s": {"納税者一覧": ["子"]}},
                    "axes": [[{"count": n, "name": "給与収入", "min": 0, "max": 1000, "period": "2025"}]]})
                mi = proc.memory_info()
                return {"count": n, **short(r, 300), "rss_before_MB": round(rss0 / 2**20, 1),
                        "rss_after_MB": round(mi.rss / 2**20, 1),
                        "peak_wset_MB": round(getattr(mi, "peak_wset", 0) / 2**20, 1),
                        "response_bytes": len(r["body"])}
            return f
        for n in [1_000, 10_000, 100_000, 1_000_000]:
            record(f"T12j_axes_count_{n}", axes(n))

        record("T12k_循環する変数", lambda: short(req("POST", "/calculate", {
            "人物一覧": {"子": {"循環A": {"2025": None}}}})))
        record("T12l_前年を参照し続ける変数", lambda: short(req("POST", "/calculate", {
            "人物一覧": {"子": {"前年までの累積": {"2025": None}}}})))
        record("T12m_存在しない変数", lambda: short(req("POST", "/calculate", {
            "人物一覧": {"子": {"存在しない": {"2025": None}}}})))
        record("T12n_同じ種類のグループ2つに同じ人_API", lambda: short(req("POST", "/calculate", {
            "人物一覧": {"子": {}, "父": {}, "母": {}},
            "健康保険一覧": {"a": {"被保険者一覧": ["父"], "被扶養者一覧": ["子"]},
                         "b": {"被保険者一覧": ["母"], "被扶養者一覧": ["子"]}}})))
        record("T12o_文字列の式_API", lambda: short(req("POST", "/calculate", {
            "人物一覧": {"子": {"給与収入": {"2025": "100*3"}, "ダミー判定_所得要件以下": {"2025": None}}}})))
        record("T12p_trace", lambda: short(req("POST", "/trace", {
            "人物一覧": {"子": {"給与収入": {"2025": 1}, "ダミー判定_所得要件以下": {"2025": None}}}}), 1200))
    finally:
        server.shutdown()
        th.join(timeout=10)
        RESULTS["web_api_server"]["stopped"] = not th.is_alive()


# ---------------------------------------------------------------- openfisca serve（gunicorn）
def run_serve_check() -> None:
    def f():
        exe = pathlib.Path(sys.executable).parent / ("openfisca.exe" if os.name == "nt" else "openfisca")
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env["PYTHONPATH"] = str(TMP)
        try:
            p = subprocess.run([str(exe), "serve", "--country-package", "r2_test_country"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=40, env=env)
            return {"returncode": p.returncode, "stderr_tail": p.stderr.strip().splitlines()[-4:],
                    "stdout_tail": p.stdout.strip().splitlines()[-4:]}
        except subprocess.TimeoutExpired as e:
            return {"timeout": True, "注": "40秒で止めた（起動した可能性がある）",
                    "stderr_tail": (e.stderr or b"").decode("utf-8", "replace").splitlines()[-10:]
                    if isinstance(e.stderr, bytes) else str(e.stderr)[-1000:]}
    record("T13_openfisca_serve_の起動", f)

    def g():
        import importlib.util
        return {"fcntl_available": importlib.util.find_spec("fcntl") is not None, "os_name": os.name}
    record("T13b_fcntl", g)


def finish() -> None:
    path = OUT / f"results_{MODE}.json"
    path.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = []
    for k, v in RESULTS.items():
        if isinstance(v, dict) and "ok" in v:
            body = v["result"] if v["ok"] else f"{v['error_type']}: {v['error']}"
            lines.append(f"## {k} ({'ok' if v['ok'] else 'NG'}, {v['seconds']}s)\n{json.dumps(body, ensure_ascii=False, default=str)[:1500]}\n")
        else:
            lines.append(f"## {k}\n{json.dumps(v, ensure_ascii=False, default=str)[:1500]}\n")
    (OUT / f"summary_{MODE}.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
