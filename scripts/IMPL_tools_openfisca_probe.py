"""IMPL（実装前の追加調査）tools: OpenFisca-Core 46.0.1 の実測。

調べること（docs/measurements/20261109_impl-prep_tools-openfisca-probe.md に結果を書く）:
  P01 年の途中・月の途中から始まる期間でのパラメータの評価日（R4 未決 U15）と、式（formula_YYYY_MM_DD）の切り替え
  P02 年の変数の入力と、年の途中から始まる年の期間の食い違い
  P03 施行日をキーにしたパラメータと、適用開始日をキーにしたパラメータ（年の変数で引いたとき）
  P05 tracer（計算の過程）を Python から取り出す：構造、JSON 化、パラメータの名前・参照日・値、メタデータへの対応づけ
  P06 tracer の決定性と負荷
  P07 dict の situation に入れた値の型ごとの扱い（文字列・真偽・巨大な数・日付の文字列・列挙）と set_input の配列
  P08 float（float32）・int（int32）の精度と端数
  P09 列挙・日付・年齢（12月31日時点）の書き方
  P10 判定コアの CLI 形（標準入力の JSON → 標準出力の JSON）：入力の検査、Windows、決定性
  P11 複数の判定時点を1回の呼び出しで作るときの性能

## 実行方法（リポジトリのルートで。R2 で作った隔離 venv を使う。新しいパッケージは入れない）
    .work/venvs/R2-openfisca/Scripts/python.exe -I -X utf8 scripts/IMPL_tools_openfisca_probe.py
  venv の作り方は scripts/R2_openfisca_check.py の先頭（openfisca-core[web-api]==46.0.1、--only-binary :all:）。
  出力: scripts/results/IMPL_tools_openfisca_probe/results.json と summary.txt

## 方針
- 試験用の国パッケージ（impl_probe_country）と CLI（impl_cli.py）は、このスクリプトが一時ディレクトリに自分で書き出す。
  ダウンロードしたコードは使わない。一時ディレクトリはスクリプトの最後に消す。
- パラメータの値は **すべてダミー値**（1111111、3333333 など、法令の値と紛れない数）。法令の基準額ではない。
- 年齢の計算は暦の上で誕生日を迎えたかで数える試験用のもので、法的な年齢の数え方を表していない。
- 外部への通信はしない。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
import warnings

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_tools_openfisca_probe"
RESULTS: dict[str, object] = {}
TMP = pathlib.Path(tempfile.mkdtemp(prefix="impl_of_"))
PKG = TMP / "impl_probe_country"

# ---------------------------------------------------------------- 試験用の国パッケージ
ENTITIES_PY = '''
from openfisca_core.entities import build_entity

人物 = build_entity(key="人物", plural="人物一覧", label="人（試験用）", is_person=True)
扶養所属 = build_entity(key="扶養所属", plural="扶養所属一覧", label="扶養の所属（試験用。R4 H1.1）", roles=[
    {"key": "申告者", "plural": "申告者一覧", "max": 1},
    {"key": "扶養親族等", "plural": "扶養親族等一覧"},
])
法律婚 = build_entity(key="法律婚", plural="法律婚一覧", label="法律婚（試験用。R4 H1.2）", roles=[
    {"key": "配偶者", "plural": "配偶者一覧", "max": 2},
])
健康保険 = build_entity(key="健康保険", plural="健康保険一覧", label="健康保険（試験用。R4 H1.3）", roles=[
    {"key": "対象外", "plural": "対象外一覧"},
    {"key": "被保険者", "plural": "被保険者一覧", "max": 1},
    {"key": "被扶養者", "plural": "被扶養者一覧"},
])
entities = [人物, 扶養所属, 法律婚, 健康保険]
'''

VARIABLES_PY = '''
from datetime import date

import numpy as np

from openfisca_core import periods
from openfisca_core.model_api import (ADD, DAY, ETERNITY, MONTH, YEAR, Enum, Variable,
                                      set_input_divide_by_period)
from impl_probe_country.entities import 人物, 扶養所属, 法律婚, 健康保険


def 暦の年齢(生年月日, 基準日):
    """生年月日（datetime64[D] の配列）と基準日（Instant）から、基準日までに暦の上で誕生日を迎えた回数を数える。
    試験用。法的な年齢の数え方（誕生日の前日の扱いなど）はここでは決めない。"""
    b = 生年月日.astype("datetime64[D]")
    by = b.astype("datetime64[Y]").astype(int) + 1970
    bm = b.astype("datetime64[M]").astype(int) % 12 + 1
    bd = (b - b.astype("datetime64[M]")).astype(int) + 1
    not_yet = (bm > 基準日.month) | ((bm == 基準日.month) & (bd > 基準日.day))
    return 基準日.year - by - not_yet


class 生年月日(Variable):
    value_type = date
    entity = 人物
    definition_period = ETERNITY
    default_value = date(1970, 1, 1)
    label = "生年月日"


class 年齢_年末(Variable):
    """期間の最後の日（暦年なら12月31日）の暦の年齢。"""
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 暦の年齢(人("生年月日", period), period.stop)


class 年齢_年末の翌日(Variable):
    """期間の最後の日の翌日の暦の年齢（「前日に年齢が加わる」と数える場合の書き方の例。法的な正しさは未確認）。"""
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 暦の年齢(人("生年月日", period), period.stop.offset(1, periods.DateUnit.DAY))


class 年齢_判定日の年の年末(Variable):
    """期間（例 year:2025-10-01）の始まりの日が属する暦年の12月31日の暦の年齢。"""
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 暦の年齢(人("生年月日", period), periods.period(period.start.year).stop)


class 所得区分(Enum):
    給与 = "給与（試験用の列挙値）"
    事業 = "事業（試験用の列挙値）"
    なし = "なし（試験用の列挙値）"


class 所得区分_入力(Variable):
    value_type = Enum
    possible_values = 所得区分
    default_value = 所得区分.なし
    entity = 人物
    definition_period = YEAR


class 区分は給与か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("所得区分_入力", period) == 所得区分.給与


class 区分別控除_試験(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return parameters(period).試験.区分別控除[人("所得区分_入力", period)]


class 月額収入_円(Variable):
    value_type = int
    entity = 人物
    definition_period = MONTH
    set_input = set_input_divide_by_period


class 年額収入_円(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR


class 合計収入_試験(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("年額収入_円", period) + 人("月額収入_円", period, options=[ADD])


class 扶養判定_試験(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("合計収入_試験", period) <= parameters(period).試験.所得要件_適用開始キー


class 所得要件_施行日キーの値(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.filled_array(parameters(period).試験.所得要件_施行日キー)


class 所得要件_適用開始キーの値(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.filled_array(parameters(period).試験.所得要件_適用開始キー)


class 健保_見込み年収(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("月額収入_円", period, options=[ADD])


class 健保_基準値(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.filled_array(parameters(period).試験.健保_年収基準)


class 健保_基準値_期間末(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.filled_array(parameters(period.stop).試験.健保_年収基準)


class 健保_基準値_月(Variable):
    value_type = int
    entity = 人物
    definition_period = MONTH

    def formula(人, period, parameters):
        return 人.filled_array(parameters(period).試験.健保_年収基準)


class 健保_基準値_日(Variable):
    value_type = int
    entity = 人物
    definition_period = DAY

    def formula(人, period, parameters):
        return 人.filled_array(parameters(period).試験.健保_年収基準)


class 健保_基準未満(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("健保_見込み年収", period) < 人("健保_基準値", period)


class 式の切替_試験(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula_2020_01_01(人, period, parameters):
        return 人.filled_array(1)

    def formula_2025_10_01(人, period, parameters):
        return 人.filled_array(2)


class 税額_試験(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return parameters(period).試験.税率表.calc(人("合計収入_試験", period))


class 給与収入_float(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR


class 給与収入_int(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR


class 一割の切り捨て_float(Variable):
    value_type = float
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return np.floor(人("給与収入_float", period) * 0.1)


class 三割_int(Variable):
    """int の変数の式が小数を返したときの暗黙の変換を見る。"""
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人("給与収入_int", period) * 0.3


class 真偽_入力(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR


class 日付_入力(Variable):
    value_type = date
    entity = 人物
    definition_period = YEAR
    default_value = date(1970, 1, 1)


class 金額_int64_試験(Variable):
    """dtype を int64 に差し替える試み（OpenFisca の公開された使い方ではない）。"""
    value_type = int
    entity = 人物
    definition_period = YEAR

    def __init__(self, baseline_variable=None):
        super().__init__(baseline_variable)
        self.dtype = np.int64


class 扶養親族等の人数(Variable):
    value_type = int
    entity = 扶養所属
    definition_period = YEAR

    def formula(g, period, parameters):
        return g.nb_persons(role=扶養所属.扶養親族等)


class 本人_扶養親族等か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.has_role(扶養所属.扶養親族等)


class 本人_申告者の扶養親族等の人数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.扶養所属("扶養親族等の人数", period)


class 本人_被扶養者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.has_role(健康保険.被扶養者)


class 法律婚_合計収入(Variable):
    value_type = int
    entity = 法律婚
    definition_period = YEAR

    def formula(g, period, parameters):
        return g.sum(g.members("合計収入_試験", period))


class 本人_配偶者の合計収入(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR

    def formula(人, period, parameters):
        return 人.法律婚("法律婚_合計収入", period) - 人("合計収入_試験", period)
'''

INIT_PY = '''
import os

from openfisca_core.taxbenefitsystems import TaxBenefitSystem

from impl_probe_country import entities

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_VERSION = "0.0.0-impl-probe"


class CountryTaxBenefitSystem(TaxBenefitSystem):
    def __init__(self):
        super().__init__(entities.entities)
        self.add_variables_from_file(os.path.join(HERE, "variables.py"))
        self.load_parameters(os.path.join(HERE, "parameters"))
'''

PARAMS = {
    "健保_年収基準.yaml": '''description: 健保の年収の基準（試験用のダミー値。法令の値ではない。2025-10-01 で値が変わる境目の試験）
metadata:
  unit: 円
  reference: 試験用（ダミー）#パラメータ全体
values:
  2020-01-01:
    value: 3333333
    metadata:
      reference: 試験用（ダミー）#旧
  2025-10-01:
    value: 4444444
    metadata:
      reference: 試験用（ダミー）#新
      施行日: 2025-10-01
''',
    "所得要件_施行日キー.yaml": '''description: 施行日（2025-12-01）をキーにした例（ダミー値）
values:
  2020-01-01:
    value: 1111111
  2025-12-01:
    value: 2222222
''',
    "所得要件_適用開始キー.yaml": '''description: 適用開始日（年分の初日）をキーにし、施行日をメタデータに書いた例（ダミー値）
values:
  2020-01-01:
    value: 1111111
    metadata:
      reference: 試験用（ダミー）#旧
  2025-01-01:
    value: 2222222
    metadata:
      reference: 試験用（ダミー）#新
      施行日: 2025-12-01
      適用: 2025年分以後（ダミーの説明）
''',
    "税率表.yaml": '''description: 試験用の累進税率表（ダミー値。法令の値ではない）
metadata:
  type: marginal_rate
  threshold_unit: currency
  rate_unit: /1
  reference: 試験用（ダミー）#税率表
brackets:
  - threshold:
      2020-01-01:
        value: 0
    rate:
      2020-01-01:
        value: 0.1
  - threshold:
      2020-01-01:
        value: 1000000
    rate:
      2020-01-01:
        value: 0.2
''',
    "区分別控除.yaml": '''description: 所得区分ごとの控除（試験用のダミー値）
給与:
  values:
    2020-01-01:
      value: 10
      metadata:
        reference: 試験用（ダミー）#給与
事業:
  values:
    2020-01-01:
      value: 20
なし:
  values:
    2020-01-01:
      value: 0
''',
}

# ---------------------------------------------------------------- 判定コアの CLI の最小形（実測用。本番のコードではない）
CLI_PY = r'''"""impl_cli: 標準入力の JSON（試験用の中間表現 impl-probe-ir/0）→ 標準出力の JSON。実測用の最小形。

使い方: python -I -X utf8 impl_cli.py [--no-trace] [--timing]  < 入力.json  > 出力.json
終了コード: 0 成功、2 入力の誤り、3 内部の誤り、4 UTF-8 モードでない
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import time

MAX_BYTES = 1_000_000
MAX_PERSONS = 20
MAX_ITEMS = 5000
MAX_POINTS = 50
MAX_AMOUNT = 2_000_000_000  # int32 の範囲に収める（OpenFisca の int は int32）
ENUM_所得区分 = ("給与", "事業", "なし")
DATE_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
MONTH_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}\Z")
ID_RE = re.compile(r"\A[^\x00-\x1f\x7f]{1,32}\Z")
TX_RE = re.compile(r"\A[A-Za-z0-9._:-]{1,64}\Z")


class InputError(Exception):
    def __init__(self, path, msg):
        super().__init__(f"{path}: {msg}")
        self.path = path
        self.msg = msg


# ------------------------------------------------------------ 読み込み
def _no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise InputError("$", f"重複したキー: {k}")
        d[k] = v
    return d


def _reject_constant(name):
    raise InputError("$", f"使えない数値: {name}")


def parse(raw: bytes):
    if len(raw) > MAX_BYTES:
        raise InputError("$", f"入力が大きすぎる（上限 {MAX_BYTES} バイト）")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise InputError("$", f"UTF-8 ではない（{e.start} バイト目）")
    if text.startswith("﻿"):
        raise InputError("$", "BOM つきは受け付けない")
    try:
        return json.loads(text, object_pairs_hook=_no_dup, parse_constant=_reject_constant)
    except InputError:
        raise
    except RecursionError:
        raise InputError("$", "入れ子が深すぎる")
    except ValueError as e:
        raise InputError("$", f"JSON として読めない: {str(e)[:120]}")


# ------------------------------------------------------------ 検査（JSON Schema の代わりの手書きの検査）
def _obj(x, path, keys):
    if type(x) is not dict:
        raise InputError(path, "object が必要")
    extra = sorted(set(x) - set(keys))
    if extra:
        raise InputError(path, f"知らないキー: {extra}")
    missing = sorted(set(keys) - set(x))
    if missing:
        raise InputError(path, f"必須のキーが無い: {missing}")
    return x


def _list(x, path, max_len):
    if type(x) is not list:
        raise InputError(path, "array が必要")
    if len(x) > max_len:
        raise InputError(path, f"要素が多すぎる（上限 {max_len}）")
    return x


def _int(x, path, lo, hi):
    if type(x) is not int:  # bool は int の派生型なので type で比べて弾く
        raise InputError(path, f"整数が必要（{type(x).__name__} が来た）")
    if not lo <= x <= hi:
        raise InputError(path, f"範囲外（{lo}〜{hi}）")
    return x


def _date(x, path):
    if type(x) is not str or not DATE_RE.match(x):
        raise InputError(path, "日付は YYYY-MM-DD の文字列")
    try:
        return datetime.date.fromisoformat(x)
    except ValueError:
        raise InputError(path, "存在しない日付")


def _month(x, path):
    if type(x) is not str or not MONTH_RE.match(x):
        raise InputError(path, "月は YYYY-MM の文字列")
    y, m = int(x[:4]), int(x[5:])
    if not 1 <= m <= 12:
        raise InputError(path, "存在しない月")
    return f"{y:04d}-{m:02d}"


def _pid(x, path, known):
    if type(x) is not str or not ID_RE.match(x):
        raise InputError(path, "人のIDは制御文字を含まない1〜32文字の文字列")
    if known is not None and x not in known:
        raise InputError(path, f"知らない人: {x}")
    return x


def _txids(x, path):
    out = []
    for i, t in enumerate(_list(x, path, 50)):
        if type(t) is not str or not TX_RE.match(t):
            raise InputError(f"{path}[{i}]", "取引IDの形が違う")
        out.append(t)
    return out


def _active(item, d):
    return item["from"] <= d and (item["to"] is None or d <= item["to"])


def validate(d):
    _obj(d, "$", ["schema", "persons", "monthly_income", "annual_income", "dependency", "marriage",
                  "health_insurance", "judgments"])
    if d["schema"] != "impl-probe-ir/0":
        raise InputError("$.schema", "知らないスキーマ")
    persons, ids = [], set()
    for i, p in enumerate(_list(d["persons"], "$.persons", MAX_PERSONS)):
        path = f"$.persons[{i}]"
        _obj(p, path, ["id", "birth_date", "category"])
        pid = _pid(p["id"], path + ".id", None)
        if pid in ids:
            raise InputError(path + ".id", f"人のIDが重複: {pid}")
        ids.add(pid)
        if type(p["category"]) is not str or p["category"] not in ENUM_所得区分:
            raise InputError(path + ".category", f"列挙の値は {list(ENUM_所得区分)} のどれか")
        persons.append({"id": pid, "birth_date": _date(p["birth_date"], path + ".birth_date"),
                        "category": p["category"]})
    if not persons:
        raise InputError("$.persons", "1人以上必要")
    monthly = []
    for i, r in enumerate(_list(d["monthly_income"], "$.monthly_income", MAX_ITEMS)):
        path = f"$.monthly_income[{i}]"
        _obj(r, path, ["person", "month", "amount", "source_tx"])
        monthly.append({"person": _pid(r["person"], path + ".person", ids), "month": _month(r["month"], path + ".month"),
                        "amount": _int(r["amount"], path + ".amount", 0, MAX_AMOUNT),
                        "source_tx": _txids(r["source_tx"], path + ".source_tx")})
    annual = []
    for i, r in enumerate(_list(d["annual_income"], "$.annual_income", MAX_ITEMS)):
        path = f"$.annual_income[{i}]"
        _obj(r, path, ["person", "year", "amount", "source_tx"])
        annual.append({"person": _pid(r["person"], path + ".person", ids), "year": _int(r["year"], path + ".year", 2000, 2100),
                       "amount": _int(r["amount"], path + ".amount", 0, MAX_AMOUNT),
                       "source_tx": _txids(r["source_tx"], path + ".source_tx")})
    dependency, seen = [], {}
    for i, r in enumerate(_list(d["dependency"], "$.dependency", MAX_ITEMS)):
        path = f"$.dependency[{i}]"
        _obj(r, path, ["year", "filer", "dependents"])
        y = _int(r["year"], path + ".year", 2000, 2100)
        filer = _pid(r["filer"], path + ".filer", ids)
        deps = [_pid(x, f"{path}.dependents[{j}]", ids) for j, x in enumerate(_list(r["dependents"], path + ".dependents", MAX_PERSONS))]
        for who in [filer, *deps]:
            if (y, who) in seen:
                raise InputError(path, f"{y}年分に {who} が2か所に書かれている（{seen[(y, who)]} と重複）")
            seen[(y, who)] = path
        dependency.append({"year": y, "filer": filer, "dependents": deps})
    marriage = []
    for i, r in enumerate(_list(d["marriage"], "$.marriage", MAX_ITEMS)):
        path = f"$.marriage[{i}]"
        _obj(r, path, ["spouses", "from", "to"])
        sp = [_pid(x, f"{path}.spouses[{j}]", ids) for j, x in enumerate(_list(r["spouses"], path + ".spouses", 2))]
        if len(sp) != 2 or sp[0] == sp[1]:
            raise InputError(path + ".spouses", "別々の2人が必要")
        marriage.append({"spouses": sp, "from": _date(r["from"], path + ".from"),
                         "to": None if r["to"] is None else _date(r["to"], path + ".to")})
    health = []
    for i, r in enumerate(_list(d["health_insurance"], "$.health_insurance", MAX_ITEMS)):
        path = f"$.health_insurance[{i}]"
        _obj(r, path, ["insured", "dependents", "from", "to"])
        health.append({"insured": _pid(r["insured"], path + ".insured", ids),
                       "dependents": [_pid(x, f"{path}.dependents[{j}]", ids) for j, x in enumerate(_list(r["dependents"], path + ".dependents", MAX_PERSONS))],
                       "from": _date(r["from"], path + ".from"),
                       "to": None if r["to"] is None else _date(r["to"], path + ".to")})
    j = _obj(d["judgments"], "$.judgments", ["tax_years", "kenpo_dates"])
    years = [_int(y, f"$.judgments.tax_years[{k}]", 2000, 2100) for k, y in enumerate(_list(j["tax_years"], "$.judgments.tax_years", MAX_POINTS))]
    dates = [_date(x, f"$.judgments.kenpo_dates[{k}]") for k, x in enumerate(_list(j["kenpo_dates"], "$.judgments.kenpo_dates", MAX_POINTS))]
    ir = {"persons": persons, "monthly": monthly, "annual": annual, "dependency": dependency,
          "marriage": marriage, "health": health, "tax_years": sorted(set(years)), "kenpo_dates": sorted(set(dates))}
    # 判定の時点ごとに、同じ種類のグループに2回書かれる人がいないか（OpenFisca のエラーより先に、人の名前つきで止める）
    for d0 in [datetime.date(y, 12, 31) for y in ir["tax_years"]] + ir["kenpo_dates"]:
        for kind, items, members in [("marriage", marriage, lambda r: r["spouses"]),
                                     ("health_insurance", health, lambda r: [r["insured"], *r["dependents"]])]:
            where = {}
            for k, r in enumerate(items):
                if _active(r, d0):
                    for who in members(r):
                        if who in where:
                            raise InputError(f"$.{kind}[{k}]", f"{d0} に {who} が2つの {kind} に属している")
                        where[who] = k
    return ir


# ------------------------------------------------------------ 状況の組み立て
def _assert_typed(situation, tbs):
    """OpenFisca に渡る値が、数値・真偽・日付・列挙名（決まった集合）だけであることを確かめる。"""
    from openfisca_core.indexed_enums import Enum
    for plural, instances in situation.items():
        for inst_id, fields in instances.items():
            assert type(inst_id) is str
            for name, val in fields.items():
                if name.endswith("一覧"):  # 役割（人のIDのリスト）
                    assert type(val) is list and all(type(x) is str for x in val), (plural, inst_id, name)
                    continue
                var = tbs.variables[name]
                assert type(val) is dict
                for per, v in val.items():
                    assert type(per) is str
                    vt = var.value_type
                    ok = ((vt is int and type(v) is int) or (vt is float and type(v) in (int, float))
                          or (vt is bool and type(v) is bool) or (vt is datetime.date and type(v) is datetime.date)
                          or (vt is Enum and type(v) is str and v in var.possible_values.__members__))
                    assert ok, (plural, inst_id, name, per, type(v).__name__)


def build_situation(ir, as_of, dep_year, provenance):
    persons = {p["id"]: {"生年月日": {"ETERNITY": p["birth_date"]},
                         "所得区分_入力": {str(y): p["category"] for y in ir["tax_years"]}} for p in ir["persons"]}
    monthly, annual = {}, {}
    for r in ir["monthly"]:
        k = (r["person"], r["month"])
        a, tx = monthly.get(k, (0, []))
        monthly[k] = (a + r["amount"], tx + r["source_tx"])
    for r in ir["annual"]:
        k = (r["person"], str(r["year"]))
        a, tx = annual.get(k, (0, []))
        annual[k] = (a + r["amount"], tx + r["source_tx"])
    for (pid, per), (a, tx) in sorted(monthly.items()):
        persons[pid].setdefault("月額収入_円", {})[per] = a
        provenance.setdefault(f"月額収入_円<{per}>", {})[pid] = sorted(set(tx))
    for (pid, per), (a, tx) in sorted(annual.items()):
        persons[pid].setdefault("年額収入_円", {})[per] = a
        provenance.setdefault(f"年額収入_円<{per}>", {})[pid] = sorted(set(tx))
    fuyo, placed = {}, set()
    for r in ir["dependency"]:
        if r["year"] == dep_year:
            fuyo[f"{r['filer']}の扶養所属"] = {"申告者一覧": [r["filer"]], "扶養親族等一覧": list(r["dependents"])}
            placed.update([r["filer"], *r["dependents"]])
    for p in ir["persons"]:
        if p["id"] not in placed:
            fuyo[f"{p['id']}の扶養所属"] = {"申告者一覧": [p["id"]]}
    kon, placed = {}, set()
    for k, r in enumerate(ir["marriage"]):
        if _active(r, as_of):
            kon[f"婚姻{k}"] = {"配偶者一覧": list(r["spouses"])}
            placed.update(r["spouses"])
    for p in ir["persons"]:
        if p["id"] not in placed:
            kon[f"{p['id']}（婚姻なし）"] = {"配偶者一覧": [p["id"]]}
    ken, placed = {}, set()
    for k, r in enumerate(ir["health"]):
        if _active(r, as_of):
            ken[f"{r['insured']}の健保"] = {"被保険者一覧": [r["insured"]], "被扶養者一覧": list(r["dependents"])}
            placed.update([r["insured"], *r["dependents"]])
    for p in ir["persons"]:
        if p["id"] not in placed:
            ken[f"{p['id']}（健保対象外）"] = {"対象外一覧": [p["id"]]}
    return {"人物一覧": persons, "扶養所属一覧": fuyo, "法律婚一覧": kon, "健康保険一覧": ken}


# ------------------------------------------------------------ 根拠
def _find_parameter(root, dotted):
    node = root
    for part in dotted.split("."):
        node = node.children[part]
    return node


def _entry_at(param, instant_str):
    for v in param.values_list:  # 新しい順
        if v.instant_str <= instant_str:
            return v
    return None


def _param_basis(tbs, name, instant_str, value):
    try:
        node = _find_parameter(tbs.parameters, name)
    except KeyError:
        return {"名前": name, "参照日": instant_str, "値": value, "注": "パラメータの木で見つからない"}
    if hasattr(node, "values_list"):
        e = _entry_at(node, instant_str)
        return {"名前": name, "参照日": instant_str, "値": value, "適用開始": e.instant_str if e else None,
                "メタデータ": dict(e.metadata) if e else None, "説明": node.description}
    # 配列で引いた（列挙で添字をつけた）場合は親の名前になる → 子ごとに適用開始とメタデータを並べる
    kids = {}
    for k, child in sorted(getattr(node, "children", {}).items()):
        if hasattr(child, "values_list"):
            e = _entry_at(child, instant_str)
            kids[k] = {"適用開始": e.instant_str if e else None, "値": e.value if e else None,
                       "メタデータ": dict(e.metadata) if e else None}
    return {"名前": name, "参照日": instant_str, "値": value, "子": kids}


def _jsonable(v):
    if isinstance(v, (datetime.date,)):
        return v.isoformat()
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


def _pkey(period):
    """期間を日まで含めて表す（str(Period) は年・月の途中から始まる期間の日を落とすため使わない）。"""
    unit, start, size = period
    if str(unit) == "eternity":
        return "eternity"
    return f"{unit}:{start}:{size}"


def basis_of(tbs, sim):
    from openfisca_core.tracers import FlatTrace
    variables = {}
    for node in sim.tracer.browse_trace():
        key = f"{node.name}<{_pkey(node.period)}>"
        if key in variables:  # 2回目以降はキャッシュの読み出し（FlatTrace と同じく最初の記録を残す）
            continue
        variables[key] = {"依存": [f"{c.name}<{_pkey(c.period)}>" for c in node.children],
                          "値": _jsonable(FlatTrace.serialize(node.value)),
                          "パラメータ": sorted(f"{p.name}<{p.period}>" for p in node.parameters)}
    variables = {k: variables[k] for k in sorted(variables)}
    params = {}
    for node in sim.tracer.browse_trace():
        for p in node.parameters:
            k = f"{p.name}<{p.period}>"
            if k not in params:
                params[k] = _param_basis(tbs, p.name, str(p.period), _jsonable(FlatTrace.serialize(p.value)))
    return {"変数": variables, "パラメータ": [params[k] for k in sorted(params)]}


def _values(sim, tbs, requests):
    from openfisca_core.indexed_enums import Enum
    out = {}
    for ent, var, per in requests:
        arr = sim.calculate(var, per)
        vt = tbs.variables[var].value_type
        if vt is Enum:
            vals = arr.decode_to_str().tolist()
        elif vt is datetime.date:
            vals = [x.isoformat() for x in arr.tolist()]
        else:
            vals = arr.tolist()
        out.setdefault(var, {})[per] = dict(zip(sim.populations[ent].ids, vals))
    return out


def parameters_digest(pkg_dir):
    h = hashlib.sha256()
    base = os.path.join(pkg_dir, "parameters")
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            h.update(os.path.relpath(p, base).replace(os.sep, "/").encode("utf-8") + b"\0")
            with open(p, "rb") as f:
                h.update(f.read() + b"\0")
    return h.hexdigest()


TAX_REQUESTS = [("人物", "年齢_年末"), ("人物", "合計収入_試験"), ("人物", "扶養判定_試験"), ("人物", "本人_扶養親族等か"),
                ("人物", "本人_申告者の扶養親族等の人数"), ("人物", "本人_配偶者の合計収入"), ("人物", "区分別控除_試験"),
                ("人物", "税額_試験"), ("人物", "所得区分_入力"), ("扶養所属", "扶養親族等の人数")]
KENPO_REQUESTS = [("人物", "健保_見込み年収"), ("人物", "健保_基準値"), ("人物", "健保_基準未満"), ("人物", "本人_被扶養者か"),
                  ("人物", "年齢_判定日の年の年末")]


def evaluate(tbs, ir, trace=True):
    from openfisca_core.simulations import SimulationBuilder
    out = []
    points = [("所得税_試験", datetime.date(y, 12, 31), y, str(y), TAX_REQUESTS) for y in ir["tax_years"]]
    points += [("健保_試験", d, d.year, f"year:{d.isoformat()}", KENPO_REQUESTS) for d in ir["kenpo_dates"]]
    for kind, as_of, dep_year, per, reqs in points:
        prov = {}
        situation = build_situation(ir, as_of, dep_year, prov)
        _assert_typed(situation, tbs)
        sim = SimulationBuilder().build_from_entities(tbs, situation)
        sim.trace = trace
        vals = _values(sim, tbs, [(e, v, per) for e, v in reqs])
        item = {"判定": kind, "切り出し日": as_of.isoformat(), "期間": per, "値": vals,
                "入力の取引ID": {k: prov[k] for k in sorted(prov)}}
        if trace:
            item["根拠"] = basis_of(tbs, sim)
        out.append(item)
    return out


def versions(pkg_dir):
    from importlib.metadata import version
    import impl_probe_country
    return {"openfisca-core": version("openfisca-core"), "numpy": version("numpy"),
            "法令パッケージ": impl_probe_country.PACKAGE_VERSION, "パラメータのsha256": parameters_digest(pkg_dir)}


def _emit(obj):
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sys.stdout.buffer.flush()


def main(argv):
    if not sys.flags.utf8_mode:
        sys.stderr.write("error: run with python -I -X utf8 (UTF-8 mode is required)\n")
        return 4
    trace = "--no-trace" not in argv
    t0 = time.perf_counter()
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    try:
        ir = validate(parse(raw))
    except InputError as e:
        _emit({"ok": False, "エラー": [{"場所": e.path, "内容": e.msg}]})
        return 2
    t1 = time.perf_counter()
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    from impl_probe_country import CountryTaxBenefitSystem
    import openfisca_core.simulations  # noqa: F401  （import の時間を分けて測る）
    t2 = time.perf_counter()
    tbs = CountryTaxBenefitSystem()
    t3 = time.perf_counter()
    try:
        results = evaluate(tbs, ir, trace=trace)
    except Exception as e:  # noqa: BLE001
        _emit({"ok": False, "内部エラー": type(e).__name__})
        sys.stderr.write(f"{type(e).__name__}: {str(e)[:500]}\n")
        return 3
    t4 = time.perf_counter()
    _emit({"ok": True, "版": versions(os.path.join(here, "impl_probe_country")), "結果": results})
    t5 = time.perf_counter()
    if "--timing" in argv:
        timing = {"検査_s": round(t1 - t0, 4), "import_s": round(t2 - t1, 4), "tbs_load_s": round(t3 - t2, 4),
                  "evaluate_s": round(t4 - t3, 4), "出力_s": round(t5 - t4, 4), "simulations": len(results), "trace": trace}
        try:
            import psutil
            mi = psutil.Process().memory_info()
            timing["rss_MB"] = round(mi.rss / 2**20, 1)
            timing["peak_wset_MB"] = round(getattr(mi, "peak_wset", 0) / 2**20, 1)
        except Exception:  # noqa: BLE001
            pass
        sys.stderr.write(json.dumps(timing) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''


# ---------------------------------------------------------------- 共通
def write_package() -> None:
    (PKG / "parameters" / "試験").mkdir(parents=True)
    (PKG / "__init__.py").write_text(INIT_PY, encoding="utf-8")
    (PKG / "entities.py").write_text(ENTITIES_PY, encoding="utf-8")
    (PKG / "variables.py").write_text(VARIABLES_PY, encoding="utf-8")
    for name, text in PARAMS.items():
        (PKG / "parameters" / "試験" / name).write_text(text, encoding="utf-8")
    (TMP / "impl_cli.py").write_text(CLI_PY, encoding="utf-8")


def scrub(o):
    if isinstance(o, str):
        for p in (str(TMP), str(TMP).replace("\\", "/"), str(TMP).replace("\\", "\\\\")):
            o = o.replace(p, "<TMP>")
        return o
    if isinstance(o, dict):
        return {scrub(k): scrub(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [scrub(v) for v in o]
    return o


def record(key: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            value = fn()
        RESULTS[key] = {"ok": True, "result": value, "seconds": round(time.perf_counter() - t0, 3)}
        if w:
            RESULTS[key]["warnings"] = sorted({f"{x.category.__name__}: {str(x.message)[:200]}" for x in w})
    except BaseException as e:  # noqa: BLE001  実測なので例外も結果として記録する
        RESULTS[key] = {"ok": False, "error_type": type(e).__name__, "error": str(e)[:2000],
                        "traceback_tail": traceback.format_exc().splitlines()[-6:],
                        "seconds": round(time.perf_counter() - t0, 3)}
    print(f"[{key}] {'ok' if RESULTS[key]['ok'] else 'NG'}", flush=True)


def tolist(a):
    try:
        return a.tolist()
    except AttributeError:
        return a


def attempt(fn):
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            v = fn()
        out = {"結果": v}
        if w:
            out["警告"] = sorted({f"{x.category.__name__}: {str(x.message)[:150]}" for x in w})
        return out
    except Exception as e:  # noqa: BLE001
        return {"例外": f"{type(e).__name__}: {str(e)[:300]}"}


def sample_ir(n_children=3, years=(2025, 2026), kenpo_dates=None):
    """家族（父・母・祖母・子 n 人）のダミーの中間表現。金額はダミー。"""
    kenpo_dates = kenpo_dates or ["2025-04-01", "2025-09-30", "2025-10-01", "2026-01-01", "2026-04-01", "2026-10-01"]
    persons = [{"id": "父", "birth_date": "1970-05-01", "category": "給与"},
               {"id": "母", "birth_date": "1972-03-01", "category": "事業"},
               {"id": "祖母", "birth_date": "1945-01-01", "category": "なし"}]
    births = ["2005-12-31", "2006-01-01", "2008-07-15", "2004-02-29", "2010-04-02", "2012-01-02", "2003-06-30"]
    for i in range(n_children):
        persons.append({"id": f"子{i + 1}", "birth_date": births[i % len(births)], "category": "給与"})
    monthly = []
    for i in range(n_children):
        for y in range(2025, 2028):
            for m in range(1, 13):
                monthly.append({"person": f"子{i + 1}", "month": f"{y}-{m:02d}", "amount": 80000 + 1000 * i + 100 * m,
                                "source_tx": [f"tx-{y}-{m:02d}-c{i + 1}"]})
    annual = [{"person": "父", "year": y, "amount": 6000000, "source_tx": [f"gensen-{y}-father"]} for y in years]
    annual += [{"person": "母", "year": y, "amount": 1500000, "source_tx": [f"biz-{y}-mother"]} for y in years]
    dependency = [{"year": y, "filer": "父", "dependents": [f"子{i + 1}" for i in range(n_children)] + ["祖母"]} for y in years]
    return {"schema": "impl-probe-ir/0", "persons": persons, "monthly_income": monthly, "annual_income": annual,
            "dependency": dependency,
            "marriage": [{"spouses": ["父", "母"], "from": "2000-01-01", "to": None}],
            "health_insurance": [{"insured": "父", "dependents": [f"子{i + 1}" for i in range(n_children)], "from": "2020-01-01", "to": "2026-03-31"},
                                 {"insured": "父", "dependents": [f"子{i + 1}" for i in range(1, n_children)], "from": "2026-04-01", "to": None},
                                 {"insured": "子1", "dependents": [], "from": "2026-04-01", "to": None}],
            "judgments": {"tax_years": list(years), "kenpo_dates": kenpo_dates}}


# ---------------------------------------------------------------- 本体
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_package()
    sys.path.insert(0, str(TMP))
    from importlib.metadata import version

    import numpy as np

    RESULTS["env"] = {"python": sys.version, "executable": sys.executable.replace(str(ROOT), "<ROOT>"),
                      "utf8_mode": sys.flags.utf8_mode, "isolated": sys.flags.isolated,
                      "versions": {p: version(p) for p in ["openfisca-core", "numpy", "numexpr", "pyyaml", "psutil"]}}
    from openfisca_core import periods
    from openfisca_core.simulations import SimulationBuilder
    from impl_probe_country import CountryTaxBenefitSystem
    t0 = time.perf_counter()
    tbs = CountryTaxBenefitSystem()
    RESULTS["tbs_load_seconds_in_process"] = round(time.perf_counter() - t0, 4)

    def build(situation, trace=False):
        sim = SimulationBuilder().build_from_entities(tbs, json.loads(json.dumps(situation, default=str)))
        sim.trace = trace
        return sim

    one = {"人物一覧": {"A": {"生年月日": {"ETERNITY": "2005-01-01"}}}}

    # ------------------------------------------------ P01 U15
    def p01():
        sim = build(one, trace=True)
        rows = []
        for per in ["2025", "year:2025-09", "year:2025-09-30", "year:2025-10", "year:2025-10-01", "year:2025-10-15",
                    "year:2026-04-01", "2026"]:
            p = periods.period(per)
            rows.append({"期間の指定": per, "str(period)": str(p), "start": str(p.start), "stop": str(p.stop),
                         "健保_基準値＝parameters(period)": int(sim.calculate("健保_基準値", per)[0]),
                         "健保_基準値_期間末＝parameters(period.stop)": int(sim.calculate("健保_基準値_期間末", per)[0]),
                         "式の切替_試験（formula_2020_01_01→1、formula_2025_10_01→2）": int(sim.calculate("式の切替_試験", per)[0])})
        month_rows = {per: int(sim.calculate("健保_基準値_月", per)[0]) for per in ["2025-09", "month:2025-10", "2025-10"]}
        day_rows = {per: int(sim.calculate("健保_基準値_日", per)[0]) for per in ["2025-09-30", "day:2025-10-01"]}
        direct = {d: int(tbs.parameters(d).試験.健保_年収基準) for d in ["2025-09-30", "2025-10-01"]}
        accessed = sorted({(p.name, str(p.period), int(p.value)) for n in sim.tracer.browse_trace() for p in n.parameters})
        return {"年の変数": rows, "月の変数（健保_基準値_月）": month_rows, "日の変数（健保_基準値_日）": day_rows,
                "tbs.parameters(日付) を直接": direct,
                "トレースに記録されたパラメータ（名前, 参照日, 値）": [list(x) for x in accessed],
                "注": "パラメータ 試験.健保_年収基準 はダミー値：2020-01-01 から 3333333、2025-10-01 から 4444444"}
    record("P01_U15_期間の途中から始まる期間とパラメータの評価日", p01)

    # ------------------------------------------------ P02 入力の期間の食い違い
    def p02():
        s = {"人物一覧": {"A": {"年額収入_円": {"2025": 1000}, "月額収入_円": {"2025-10": 10, "2025-11": 20, "2026-09": 30, "2026-10": 40}}}}
        sim = build(s)
        out = {"年額収入_円 2025（入力したとおり）": int(sim.calculate("年額収入_円", "2025")[0]),
               "年額収入_円 year:2025-10（入力なし）": int(sim.calculate("年額収入_円", "year:2025-10")[0]),
               "合計収入_試験 year:2025-10（月の ADD は 10+20+30）": int(sim.calculate("合計収入_試験", "year:2025-10")[0]),
               "合計収入_試験 2025": int(sim.calculate("合計収入_試験", "2025")[0])}
        s2 = {"人物一覧": {"A": {"年額収入_円": {"2025": 1000, "year:2025-10": 500}}}}
        sim2 = build(s2)
        out["同じ変数に 2025 と year:2025-10 の両方を入力"] = {
            "2025": int(sim2.calculate("年額収入_円", "2025")[0]),
            "year:2025-10": int(sim2.calculate("年額収入_円", "year:2025-10")[0]),
            "year:2025-04（どちらとも違う）": int(sim2.calculate("年額収入_円", "year:2025-04")[0])}
        s3 = {"人物一覧": {"A": {"月額収入_円": {"year:2025-10": 1200}}}}
        sim3 = build(s3)
        out["月の変数に year:2025-10 で 1200 を入力（set_input_divide_by_period）"] = {
            m: int(sim3.calculate("月額収入_円", m)[0]) for m in ["2025-09", "2025-10", "2026-09", "2026-10"]}
        # 月の途中から始まる年の期間で ADD したとき、どの月が足されるか（月ごとに別のビットを入れて合計から読み取る）
        months = [f"{2025 + (7 + i) // 12}-{(7 + i) % 12 + 1:02d}" for i in range(16)]  # 2025-08 〜 2026-11
        s4 = {"人物一覧": {"A": {"月額収入_円": {m: 2 ** i for i, m in enumerate(months)}}}}
        sim4 = build(s4)
        added = {}
        for per in ["2025", "year:2025-09-30", "year:2025-10-01", "year:2025-10-15", "year:2025-10-31"]:
            total = int(sim4.calculate("健保_見込み年収", per)[0])
            inc = [m for i, m in enumerate(months) if total >> i & 1]
            added[per] = {"足された月": f"{inc[0]}〜{inc[-1]}（{len(inc)}か月）" if inc else "なし",
                          "期間の start〜stop": f"{periods.period(per).start}〜{periods.period(per).stop}"}
        out["ADD で足される月（月の変数を年の期間で合計）"] = added
        return out
    record("P02_年の途中から始まる年の期間と入力", p02)

    # ------------------------------------------------ P03 施行日キーと適用開始キー
    def p03():
        sim = build(one)
        out = {}
        for per in ["2024", "2025", "2026", "year:2025-12"]:
            out[per] = {"施行日キー（2025-12-01 から 2222222）": int(sim.calculate("所得要件_施行日キーの値", per)[0]),
                        "適用開始キー（2025-01-01 から 2222222、施行日はメタデータ）": int(sim.calculate("所得要件_適用開始キーの値", per)[0])}
        meta = {e.instant_str: dict(e.metadata) for e in tbs.parameters.試験.所得要件_適用開始キー.values_list}
        return {"年の変数で引いた値": out, "適用開始キーの値ごとのメタデータ": meta}
    record("P03_施行日キーと適用開始キー", p03)

    # ------------------------------------------------ P05 トレース
    family = {"人物一覧": {"父": {"生年月日": {"ETERNITY": "1970-05-01"}, "年額収入_円": {"2025": 6000000},
                                  "所得区分_入力": {"2025": "給与"}},
                           "子": {"生年月日": {"ETERNITY": "2005-12-31"}, "月額収入_円": {f"2025-{m:02d}": 90000 for m in range(1, 13)},
                                  "所得区分_入力": {"2025": "事業"}}},
              "扶養所属一覧": {"父の扶養所属": {"申告者一覧": ["父"], "扶養親族等一覧": ["子"]}},
              "法律婚一覧": {"父": {"配偶者一覧": ["父"]}, "子": {"配偶者一覧": ["子"]}},
              "健康保険一覧": {"父の健保": {"被保険者一覧": ["父"], "被扶養者一覧": ["子"]}}}
    targets = [("扶養判定_試験", "2025"), ("区分別控除_試験", "2025"), ("税額_試験", "2025"), ("年齢_年末", "2025"),
               ("本人_申告者の扶養親族等の人数", "2025"), ("健保_基準未満", "year:2025-10-01")]

    def p05():
        sim = build(family, trace=True)
        for v, p in targets:
            sim.calculate(v, p)
        tr = sim.tracer
        out = {"tracer の型": type(tr).__name__, "木の数（calculate を呼んだ回数）": len(tr.trees)}
        t0n = tr.trees[0]
        out["木の根の構造（扶養判定_試験）"] = {
            "name": t0n.name, "period": str(t0n.period), "value": tolist(t0n.value),
            "children": [{"name": c.name, "period": str(c.period), "value": tolist(c.value),
                          "children": [f"{g.name}<{g.period}>" for g in c.children]} for c in t0n.children],
            "parameters": [{"name": p.name, "period": str(p.period), "value": tolist(p.value)} for p in t0n.parameters]}
        flat = tr.get_flat_trace()
        out["get_flat_trace のキーの数"] = len(flat)
        out["get_flat_trace のキー"] = sorted(flat.keys())
        k0 = "扶養判定_試験<2025>"
        out[f"flat の1件（{k0}）"] = {k: (tolist(v) if k == "value" else v) for k, v in flat[k0].items()}
        ser = tr.get_serialized_flat_trace()
        try:
            json.dumps(ser, ensure_ascii=False)
            out["get_serialized_flat_trace は json.dumps できるか"] = True
        except TypeError as e:
            out["get_serialized_flat_trace は json.dumps できるか"] = f"できない: {e}"
        out["年齢_年末<2025> の serialized の値"] = ser["年齢_年末<2025>"]["value"]
        out["生年月日<eternity> の serialized の値の型"] = [type(x).__name__ for x in ser.get("生年月日<eternity>", {}).get("value", [])]
        out["パラメータへのアクセス（全ノード、名前, 参照日, 値）"] = [
            [p.name, str(p.period), tolist(p.value)] for n in tr.browse_trace() for p in n.parameters]
        out["税額_試験<2025> のノードに記録されたパラメータ"] = flat["税額_試験<2025>"]["parameters"]
        out["区分別控除_試験<2025> のノードに記録されたパラメータ"] = {k: tolist(v) for k, v in flat["区分別控除_試験<2025>"]["parameters"].items()}
        lines = tr.computation_log.lines()
        out["computation_log.lines() の行数"] = len(lines)
        out["computation_log.lines() の先頭"] = lines[:14]
        # メタデータへの対応づけ（CLI と同じ関数）
        import impl_cli
        out["根拠（CLI の basis_of で作ったもの）のパラメータ"] = impl_cli.basis_of(tbs, sim)["パラメータ"]
        return out
    record("P05_トレースの構造と根拠", p05)

    # ------------------------------------------------ P05b 期間の文字列表現で日が落ちる
    def p05b():
        out = {"str(period)": {p: str(periods.period(p)) for p in
                               ["year:2025-10-01", "year:2025-10-15", "month:2025-10-15", "day:2025-10-15", "year:2025-01-15"]}}
        sim = build(one, trace=True)
        a = int(sim.calculate("健保_基準値_期間末", "year:2025-09")[0])
        b = int(sim.calculate("健保_基準値_期間末", "year:2025-09-30")[0])
        flat = sim.tracer.get_flat_trace()
        out["同じシミュレーションで year:2025-09 と year:2025-09-30 を計算"] = {
            "計算結果（期間末のパラメータ。どちらも正しい）": {"year:2025-09": a, "year:2025-09-30": b},
            "flat_trace のキー": sorted(k for k in flat if k.startswith("健保_基準値_期間末")),
            "トレースの木の根": [f"{t.name} / {t.period!r}" for t in sim.tracer.trees],
            "パラメータの参照日（木ごと）": [[p.period for p in t.parameters] for t in sim.tracer.trees],
            "CLI の basis_of（日まで含むキー）の変数のキー": sorted(__import__("impl_cli").basis_of(tbs, sim)["変数"].keys())}
        s = {"人物一覧": {"A": {"年額収入_円": {"year:2025-10-01": 100, "year:2025-10-15": 200}}}}
        sim2 = build(s)
        out["年の変数に year:2025-10-01 と year:2025-10-15 の2つを入力"] = {
            p: int(sim2.calculate("年額収入_円", p)[0]) for p in ["year:2025-10-01", "year:2025-10-15"]}
        s3 = {"人物一覧": {"A": {"年額収入_円": {"year:2025-10-15": 200}}}}
        sim3 = build(s3)
        out["年の変数に year:2025-10-15 だけを入力"] = {
            p: int(sim3.calculate("年額収入_円", p)[0]) for p in ["year:2025-10-01", "year:2025-10-15"]}
        return out
    record("P05b_期間の文字列で日が落ちる", p05b)

    # ------------------------------------------------ P06 決定性と負荷
    def p06():
        import impl_cli
        hashes = []
        for _ in range(3):
            sim = build(family, trace=True)
            for v, p in targets:
                sim.calculate(v, p)
            b = impl_cli.basis_of(tbs, sim)
            hashes.append(hashlib.sha256(json.dumps(b, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
        sim = build(family, trace=True)
        for v, p in targets:
            sim.calculate(v, p)
        times = sorted({json.dumps([n["calculation_time"] for n in sim.tracer.get_flat_trace().values()])} )
        def run(trace):
            ts = []
            for _ in range(60):
                t = time.perf_counter()
                s = build(family, trace=trace)
                for v, p in targets:
                    s.calculate(v, p)
                if trace:
                    impl_cli.basis_of(tbs, s)
                ts.append(time.perf_counter() - t)
            return round(statistics.median(ts) * 1000, 3)
        return {"根拠（時間の欄を除く）の sha256（3回）": hashes, "3回とも同じか": len(set(hashes)) == 1,
                "flat_trace の calculation_time（例。実行ごとに変わる値）": json.loads(times[0])[:6],
                "1シミュレーション（2人、6変数）の組み立て＋計算の中央値_ms": {"trace なし": run(False), "trace あり＋根拠の組み立て": run(True)}}
    record("P06_トレースの決定性と負荷", p06)

    # ------------------------------------------------ P07 値の型ごとの扱い（dict の situation）
    def put(var, value, per="2025"):
        def f():
            sim = SimulationBuilder().build_from_entities(tbs, {"人物一覧": {"A": {var: {per: value}}}})
            arr = sim.calculate(var, per)
            if tbs.variables[var].value_type.__name__ == "Enum":
                return arr.decode_to_str().tolist()
            return [str(x) if isinstance(x, datetime.date) else x for x in arr.tolist()]
        return attempt(f)

    def p07():
        cases = {
            "給与収入_float（float32）": [("100*3", "文字列の式"), ("1e3", "文字列の数"), (True, "真偽"), (16777217, "2**24+1"),
                                     (1e39, "1e39"), (10 ** 40, "10**40（int）"), ("nan", "文字列 nan")],
            "給与収入_int（int32）": [("100*3", "文字列の式"), (3.7, "小数"), (-3.7, "負の小数"), (True, "真偽"),
                                  (2 ** 31, "2**31"), (2 ** 31 - 1, "2**31-1")],
            "真偽_入力（bool）": [("false", "文字列 false"), ("", "空文字列"), ("0", "文字列 0"), (0, "0"), (2, "2"), (0.0, "0.0")],
            "日付_入力（date）": [("2005-12-31", "YYYY-MM-DD"), ("2005-12", "YYYY-MM"), ("2005", "YYYY"),
                              ("2005-12-31T23:59", "時刻つき"), ("20051231", "区切りなし"), (0, "整数 0"),
                              (datetime.date(2005, 12, 31), "datetime.date"), ("2005-02-30", "存在しない日")],
            "所得区分_入力（Enum）": [("給与", "名前"), ("未定義", "知らない名前"), (0, "整数 0"), (2, "整数 2"), (99, "整数 99"),
                                 ("給与（試験用の列挙値）", "値（説明文）")],
        }
        out = {}
        for label, items in cases.items():
            var = label.split("（")[0]
            out[label] = {f"{desc}: {value!r}": put(var, value) for value, desc in items}
        # set_input に numpy の配列を渡す（dict を通さない）
        def via_set_input(var, arr):
            def f():
                sim = SimulationBuilder().build_default_simulation(tbs, 1)
                sim.set_input(var, "2025", arr)
                return tolist(sim.calculate(var, "2025"))
            return attempt(f)
        out["set_input に配列を渡す"] = {
            "給与収入_float ← np.array(['1000*2'])": via_set_input("給与収入_float", np.array(["1000*2"])),
            "給与収入_float ← np.array([1000.5])": via_set_input("給与収入_float", np.array([1000.5])),
            "給与収入_int ← np.array([3.7])": via_set_input("給与収入_int", np.array([3.7])),
            "給与収入_float ← '1000*2'（配列でない文字列）": via_set_input("給与収入_float", "1000*2"),
            "所得区分_入力 ← np.array(['事業'])": via_set_input("所得区分_入力", np.array(["事業"])),
        }
        return out
    record("P07_値の型ごとの扱い", p07)

    # ------------------------------------------------ P08 精度と端数
    def p08():
        out = {}
        out["float32 の入力（入れた値: 読み戻した値）"] = {str(x): put("給与収入_float", x) for x in [16777216, 16777217, 20000001, 123456789]}
        out["int32 の入力（入れた値: 読み戻した値）"] = {str(x): put("給与収入_int", x) for x in [20000001, 2147483647]}
        sim = SimulationBuilder().build_from_entities(tbs, {"人物一覧": {
            "A": {"給与収入_float": {"2025": 7000000}, "給与収入_int": {"2025": 1000001}},
            "B": {"給与収入_float": {"2025": 12345670}, "給与収入_int": {"2025": -1000001}}}})
        out["一割の切り捨て_float（floor(float32 × 0.1)）"] = dict(zip(["A: 7000000", "B: 12345670"], tolist(sim.calculate("一割の切り捨て_float", "2025"))))
        out["三割_int（int32 × 0.3 を int の変数で返す）"] = dict(zip(["A: 1000001", "B: -1000001"], tolist(sim.calculate("三割_int", "2025"))))
        # 端数の食い違いの数：率 r = k/100（例示。法令の率ではない）。正確な値は整数演算 (x*k)//100
        counts = {}
        for label, xs in [("x = 1,000 の倍数（0〜20,000,000、20,001 点）", np.arange(0, 20_000_001, 1000, dtype=np.int64)),
                          ("x = 3 刻み（0〜20,000,000、6,666,667 点）", np.arange(0, 20_000_001, 3, dtype=np.int64))]:
            row = {}
            for k, den in [(5, 100), (10, 100), (20, 100), (30, 100), (40, 100), (29, 100), (57, 100), (21, 1000)]:
                r = k / den
                exact = (xs * k) // den
                f32 = np.floor(xs.astype(np.float32) * r).astype(np.int64)
                f64 = np.floor(xs.astype(np.float64) * r).astype(np.int64)
                bad32 = np.nonzero(f32 != exact)[0]
                bad64 = np.nonzero(f64 != exact)[0]
                small32 = int(np.count_nonzero(bad32 < np.searchsorted(xs, 2 ** 24)))
                row[f"r={r}"] = {"float32 で食い違った数": int(bad32.size), "うち x < 2**24": small32,
                                 "float32 の例（x, float32, 正確）": [[int(xs[i]), int(f32[i]), int(exact[i])] for i in bad32[:3]],
                                 "float64 で食い違った数": int(bad64.size),
                                 "float64 の例（x, float64, 正確）": [[int(xs[i]), int(f64[i]), int(exact[i])] for i in bad64[:3]]}
            counts[label] = row
        out["floor(x × r) の食い違い"] = counts
        out["numpy の型の昇格"] = {"float32 配列 × 0.1 の dtype": str((np.array([1], dtype=np.float32) * 0.1).dtype),
                              "int32 配列 × 0.3 の dtype": str((np.array([1], dtype=np.int32) * 0.3).dtype),
                              "int32 配列 + int32 配列（2**31-1 + 1）": int((np.array([2**31 - 1], dtype=np.int32) + np.array([1], dtype=np.int32))[0])}
        out["dtype を int64 に差し替えた変数"] = {
            "変数の dtype": str(tbs.variables["金額_int64_試験"].dtype),
            "3000000000 を入力して読む": put("金額_int64_試験", 3000000000)}
        return out
    record("P08_精度と端数", p08)

    # ------------------------------------------------ P09 列挙・日付・年齢
    def p09():
        births = {"12月31日生": "2005-12-31", "1月1日生": "2006-01-01", "1月2日生": "2006-01-02", "2月29日生": "2004-02-29"}
        s = {"人物一覧": {k: {"生年月日": {"ETERNITY": v}, "所得区分_入力": {"2025": ["給与", "事業", "なし", "給与"][i]}}
                          for i, (k, v) in enumerate(births.items())}}
        sim = build(s)
        ids = sim.persons.ids
        def col(var, per):
            a = sim.calculate(var, per)
            if hasattr(a, "decode_to_str"):
                return dict(zip(ids, a.decode_to_str().tolist()))
            return dict(zip(ids, [str(x) if isinstance(x, datetime.date) else x for x in a.tolist()]))
        return {"年齢_年末 2025（2025-12-31 の暦の年齢）": col("年齢_年末", "2025"),
                "年齢_年末の翌日 2025（2026-01-01 の暦の年齢）": col("年齢_年末の翌日", "2025"),
                "年齢_判定日の年の年末 year:2025-10-01": col("年齢_判定日の年の年末", "year:2025-10-01"),
                "年齢_年末 year:2025-10-01（期間の最後＝2026-09-30）": col("年齢_年末", "year:2025-10-01"),
                "生年月日（ETERNITY）を年の期間で引く": col("生年月日", "2025"),
                "所得区分_入力 2025（名前）": col("所得区分_入力", "2025"),
                "所得区分_入力 2026（入力なし→既定値）": col("所得区分_入力", "2026"),
                "区分は給与か 2025": col("区分は給与か", "2025"),
                "区分別控除_試験 2025（列挙で添字をつけたパラメータ）": col("区分別控除_試験", "2025"),
                "列挙の内部（index と name）": [[e.index, e.name, e.value] for e in tbs.variables["所得区分_入力"].possible_values]}
    record("P09_列挙・日付・年齢", p09)

    # ------------------------------------------------ P10 CLI
    cli = [sys.executable, "-I", "-X", "utf8", str(TMP / "impl_cli.py")]

    def run_cli(payload: bytes, args=(), utf8=True):
        cmd = list(cli) + list(args)
        if not utf8:
            cmd = [sys.executable, "-I", str(TMP / "impl_cli.py"), *args]
        t = time.perf_counter()
        p = subprocess.run(cmd, input=payload, capture_output=True, timeout=300)
        wall = time.perf_counter() - t
        try:
            body = json.loads(p.stdout.decode("utf-8")) if p.stdout else None
        except Exception as e:  # noqa: BLE001
            body = f"出力が JSON でない: {e}"
        return {"returncode": p.returncode, "wall_s": round(wall, 3), "stdout": body,
                "stdout_sha256": hashlib.sha256(p.stdout).hexdigest(),
                "stderr": p.stderr.decode("utf-8", "replace")[-600:]}

    base_ir = sample_ir(n_children=2, years=(2025, 2026),
                        kenpo_dates=["2025-09-30", "2025-10-01", "2026-04-01"])

    def enc(o):
        return json.dumps(o, ensure_ascii=False).encode("utf-8")

    def p10():
        out = {}
        ok = run_cli(enc(base_ir), ["--timing"])
        body = ok["stdout"]
        short = None
        if isinstance(body, dict) and body.get("ok"):
            r0 = body["結果"][0]
            k1 = [r for r in body["結果"] if r["期間"] == "year:2025-10-01"][0]
            k0 = [r for r in body["結果"] if r["期間"] == "year:2025-09-30"][0]
            short = {"版": body["版"], "判定の数": len(body["結果"]),
                     "所得税_試験 2025 の値": r0["値"], "所得税_試験 2025 の入力の取引ID（抜粋）": {k: v for k, v in list(r0["入力の取引ID"].items())[:3]},
                     "所得税_試験 2025 の根拠のパラメータ": r0["根拠"]["パラメータ"],
                     "所得税_試験 2025 の根拠の変数（抜粋）": {k: v for k, v in r0["根拠"]["変数"].items() if k.startswith(("扶養判定_試験<", "合計収入_試験<"))},
                     "健保_試験 year:2025-09-30 の値": k0["値"], "健保_試験 year:2025-10-01 の値": k1["値"],
                     "健保_試験 year:2025-10-01 の根拠のパラメータ": k1["根拠"]["パラメータ"],
                     "出力の大きさ_bytes": len(enc(body))}
        out["正常な入力（家族5人、年分2、健保の判定日3）"] = {"returncode": ok["returncode"], "wall_s": ok["wall_s"],
                                                     "stderr（計測）": ok["stderr"], "要約": short}
        again = run_cli(enc(base_ir))
        out["同じ入力で2回目（--timing なし）の stdout の sha256 が1回目と同じか"] = again["stdout_sha256"] == ok["stdout_sha256"]
        bad = {}

        def mutate(f):
            o = json.loads(json.dumps(base_ir))
            f(o)
            return enc(o)
        variants = {
            "数値の欄に文字列の式 '100*3'": mutate(lambda o: o["monthly_income"][0].__setitem__("amount", "100*3")),
            "数値の欄に true": mutate(lambda o: o["monthly_income"][0].__setitem__("amount", True)),
            "数値の欄に小数 1.5": mutate(lambda o: o["monthly_income"][0].__setitem__("amount", 1.5)),
            "数値の欄に 10**30": mutate(lambda o: o["monthly_income"][0].__setitem__("amount", 10 ** 30)),
            "NaN": enc(base_ir).replace(b'"amount": 80100', b'"amount": NaN', 1),
            "Infinity": enc(base_ir).replace(b'"amount": 80100', b'"amount": Infinity', 1),
            "5000桁の整数": enc(base_ir).replace(b'"amount": 80100', b'"amount": ' + b"9" * 5000, 1),
            "重複したキー": enc(base_ir).replace(b'"amount": 80100', b'"amount": 80100, "amount": 1', 1),
            "UTF-8 でないバイト": enc(base_ir).replace("父".encode("utf-8"), b"\xff\xfe", 1),
            "BOM つき": b"\xef\xbb\xbf" + enc(base_ir),
            "日付が YYYY-MM": mutate(lambda o: o["persons"][0].__setitem__("birth_date", "1970-05")),
            "存在しない日付 2025-02-30": mutate(lambda o: o["judgments"].__setitem__("kenpo_dates", ["2025-02-30"])),
            "列挙に知らない値": mutate(lambda o: o["persons"][0].__setitem__("category", "雑")),
            "axes キーを足す": mutate(lambda o: o.__setitem__("axes", [[{"count": 1000000, "name": "x", "min": 0, "max": 1}]])),
            "知らない人を参照": mutate(lambda o: o["dependency"][0]["dependents"].append("隣人")),
            "1人を同じ年分に2つの扶養所属": mutate(lambda o: o["dependency"].append({"year": 2025, "filer": "母", "dependents": ["子1"]})),
            "1人が同じ日に2つの健保": mutate(lambda o: o["health_insurance"].append({"insured": "母", "dependents": ["子2"], "from": "2025-01-01", "to": None})),
            "入れ子が深い配列（50万段）": b"[" * 500000 + b"]" * 500000,
            "大きすぎる入力（1,000,001 バイト）": b" " * 1_000_001,
            "人のIDに改行": mutate(lambda o: o["persons"][0].__setitem__("id", "父\n")),
        }
        for k, payload in variants.items():
            r = run_cli(payload)
            bad[k] = {"returncode": r["returncode"], "stdout": r["stdout"], "stderr": r["stderr"][-200:]}
        out["検査で止めるべき入力"] = bad
        nu = run_cli(enc(base_ir), utf8=False)
        out["-X utf8 なしで起動"] = {"returncode": nu["returncode"], "stderr": nu["stderr"]}
        # 比較：検査を通さず OpenFisca に同じ値を渡したとき
        out["比較：検査を通さず OpenFisca に直接渡したとき（月額収入_円）"] = {
            "'100*3'": put("月額収入_円", "100*3", "2025-01"), "True": put("月額収入_円", True, "2025-01"),
            "1.5": put("月額収入_円", 1.5, "2025-01"), "10**30": put("月額収入_円", 10 ** 30, "2025-01")}
        out["比較：生年月日に '1970-05'"] = put("生年月日", "1970-05", "ETERNITY")
        return out
    record("P10_CLI", p10)

    # ------------------------------------------------ P11 性能
    def p11():
        out = {}
        cases = {
            "家族5人（子2）・年分2・健保の判定日6（計8シミュレーション）": sample_ir(2, (2025, 2026)),
            "家族5人（子2）・年分2・健保の判定日24（計26シミュレーション）": sample_ir(2, (2025, 2026), [f"{y}-{m:02d}-01" for y in (2025, 2026) for m in range(1, 13)]),
            "家族10人（子7）・年分2・健保の判定日24（計26シミュレーション）": sample_ir(7, (2025, 2026), [f"{y}-{m:02d}-01" for y in (2025, 2026) for m in range(1, 13)]),
        }
        import impl_cli
        for label, ir in cases.items():
            runs = [run_cli(enc(ir), ["--timing"]) for _ in range(3)]
            nt = [run_cli(enc(ir), ["--timing", "--no-trace"]) for _ in range(2)]
            v = impl_cli.validate(json.loads(json.dumps(ir)))
            warm = []
            for _ in range(10):
                t = time.perf_counter()
                impl_cli.evaluate(tbs, v, trace=True)
                warm.append(time.perf_counter() - t)
            warm_nt = []
            for _ in range(10):
                t = time.perf_counter()
                impl_cli.evaluate(tbs, v, trace=False)
                warm_nt.append(time.perf_counter() - t)
            out[label] = {"CLI（別プロセス、trace あり）の wall_s 3回": [r["wall_s"] for r in runs],
                          "CLI の内訳（1回目の stderr）": runs[0]["stderr"].strip(),
                          "CLI（trace なし）の wall_s 2回": [r["wall_s"] for r in nt],
                          "CLI（trace なし）の内訳": nt[0]["stderr"].strip(),
                          "プロセス内で evaluate を10回（trace あり）の中央値_s": round(statistics.median(warm), 4),
                          "プロセス内で evaluate を10回（trace なし）の中央値_s": round(statistics.median(warm_nt), 4),
                          "出力の大きさ_bytes": len(json.dumps(runs[0]["stdout"], ensure_ascii=False).encode("utf-8")),
                          "returncode": [r["returncode"] for r in runs]}
        t = time.perf_counter()
        subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", "import openfisca_core.simulations"], capture_output=True, timeout=120)
        out["参考：python の起動＋openfisca_core の import だけの wall_s"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", "pass"], capture_output=True, timeout=120)
        out["参考：python の起動だけの wall_s"] = round(time.perf_counter() - t, 3)
        # import の内訳（-X importtime。cumulative の上位。2回目の値）
        for _ in range(2):
            p = subprocess.run([sys.executable, "-I", "-X", "utf8", "-X", "importtime", "-c", "import openfisca_core.simulations"],
                               capture_output=True, timeout=120)
        rows = []
        for line in p.stderr.decode("utf-8", "replace").splitlines():
            if line.startswith("import time:") and "|" in line and "cumulative" not in line:
                parts = line[len("import time:"):].split("|")
                rows.append((int(parts[1]), parts[2][1:]))
        def level(n):
            return (len(n) - len(n.lstrip(" "))) // 2
        for lv in (0, 1, 2):
            top = sorted([(c, n.strip()) for c, n in rows if level(n) == lv], reverse=True)[:10]
            out[f"import openfisca_core.simulations の内訳（入れ子の深さ {lv}、cumulative の上位、ミリ秒）"] = [[n, round(c / 1000)] for c, n in top]
        named = ["numpy", "numpy.testing", "pendulum", "numexpr", "yaml", "openfisca_core.tools", "pytest", "psutil", "dpath", "sortedcontainers"]
        out["import openfisca_core.simulations の内訳（主なパッケージ、深さによらず、cumulative、ミリ秒）"] = {
            n: [round(c / 1000) for c, m in rows if m.strip() == n] for n in named}
        return out
    record("P11_性能", p11)

    finish()


def finish() -> None:
    res = scrub(RESULTS)
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = []
    for k, v in res.items():
        if isinstance(v, dict) and "ok" in v:
            body = v["result"] if v["ok"] else f"{v['error_type']}: {v['error']}"
            lines.append(f"## {k} ({'ok' if v['ok'] else 'NG'}, {v['seconds']}s)\n{json.dumps(body, ensure_ascii=False, indent=1, default=str)}\n")
        else:
            lines.append(f"## {k}\n{json.dumps(v, ensure_ascii=False, indent=1, default=str)}\n")
    (OUT / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
