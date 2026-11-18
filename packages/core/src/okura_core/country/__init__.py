"""OpenFisca の TaxBenefitSystem（判定コアの法令パッケージ）を、登録した規則モジュールから組み立てる。

- エンティティ：entities.py（R4 のモデル）。共通の部分。
- 変数：各規則モジュールの RuleModule.variables（rules/<名前>/）。
- 仮置きの変数：概念辞書で担当のモジュールがあり、まだ実装済みでない概念の変数を、式のない入力変数として置く
  （registry.Registry.placeholders）。ほかのモジュールが、まだない上流の変数を名前で引き、テストで入力として与えられるように
  するため。評価では、仮置きの変数に依存する値は対象外になる（概念の「未実装のとき」で0とみなせる人を除く。evaluate.py）。
- パラメータ：各規則モジュールの parameters/（OpenFisca の YAML。日付のキーは適用開始日、metadata に law・source_kind・
  reference・施行日）を1つの木に合わせる。同じ名前の葉が2つのモジュールにあれば誤り（黙って上書きしない）。
  YAML はコードとして扱う（OpenFisca の読み込みは安全でない：docs/measurements/20261109_R2-tools_openfisca-core-runtime.md T10）。
  タグを書かないことを tests/test_data_and_parameters.py で確かめる。
- 大きな表：各規則モジュールの data/（CSV と SOURCES.json）。

build_system() は呼ぶたびに新しい TaxBenefitSystem を作る（共有の可変状態を持たない）。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from openfisca_core.model_api import DAY, ETERNITY, MONTH, YEAR, Variable
from openfisca_core.parameters import ParameterNode
from openfisca_core.taxbenefitsystems import TaxBenefitSystem

from .entities import ENTITIES

if TYPE_CHECKING:  # 型だけ（実行時は関数の中で読む：rules のモジュールが country.entities を読むので循環を避ける）
    from ..concepts import Concept
    from ..registry import Registry

COUNTRY_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = COUNTRY_DIR.parent

_PERIOD = {"年": YEAR, "月": MONTH, "日": DAY, "永久": ETERNITY}
_VALUE_TYPE: dict[str, type] = {"円": int, "真偽": bool, "整数": int, "区分": str, "日付": _dt.date}
_ENTITY = {e.key: e for e in ENTITIES}

class OkuraTaxBenefitSystem(TaxBenefitSystem):
    """okura-gov の判定コアの法令パッケージ。registry は組み立てに使った Registry。"""

    def __init__(self, registry: Registry) -> None:
        super().__init__(ENTITIES)
        self.registry = registry
        self.parameters = merged_parameters(registry)
        for m in registry.modules:
            self.add_variables(*m.variables)
        placeholders = set()
        for name, concept in sorted(registry.placeholders.items()):
            cls = placeholder_variable(name, concept)
            if cls is not None:
                self.add_variable(cls)
                placeholders.add(name)
        #: 仮置きの変数の名前（evaluate と構造の検査が見る）。
        self.placeholder_variables: frozenset[str] = frozenset(placeholders)

    def is_placeholder(self, variable: str) -> bool:
        return variable in self.placeholder_variables


def placeholder_variable(name: str, concept: Concept) -> type | None:
    """未実装の概念の仮置きの変数（式のない入力変数）。エンティティがまだないもの（予定の名前）は作らない。"""
    entity = _ENTITY.get(concept.entity)
    if entity is None:
        return None
    return type(
        name,
        (Variable,),
        {
            "value_type": _VALUE_TYPE[concept.value_type],
            "entity": entity,
            "definition_period": _PERIOD[concept.period],
            "label": f"【仮置き：未実装】{concept.name}（{concept.id}、担当 {concept.module}）",
            "reference": list(concept.definition.references),
            "__module__": __name__,
        },
    )


def _merge_into(target: ParameterNode, other: ParameterNode, where: str) -> None:
    for name, child in other.children.items():
        if name not in target.children:
            target.add_child(name, child)
            continue
        mine = target.children[name]
        if isinstance(mine, ParameterNode) and isinstance(child, ParameterNode):
            _merge_into(mine, child, where)
        else:
            raise ValueError(f"パラメータ {mine.name} が2つの規則モジュールにある（{where}）")


def merged_parameters(registry: Registry) -> ParameterNode:
    """登録した規則モジュールの parameters/ を1つの木にする（モジュールの登録の順）。"""
    root = ParameterNode("", data={})
    for m in registry.modules:
        if m.parameters_dir.is_dir():
            _merge_into(root, ParameterNode("", directory_path=str(m.parameters_dir)), m.name)
    return root


def build_system(registry: Registry | None = None) -> OkuraTaxBenefitSystem:
    if registry is None:
        from ..registry import default_registry

        registry = default_registry()
    return OkuraTaxBenefitSystem(registry)


def _hashes(registry: Registry, sub: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in registry.modules:
        base = m.directory / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                out[_relative(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(out.items()))


def _relative(path: Path) -> str:
    try:
        return path.relative_to(PACKAGE_DIR).as_posix()
    except ValueError:  # パッケージの外のモジュール（テストの道具）：モジュールのディレクトリの名前から
        return "/".join(path.parts[-4:])


def parameter_file_hashes(registry: Registry | None = None) -> dict[str, str]:
    """結果の版に書く：パラメータの YAML（okura_core からの相対パス。例 rules/kyuyo/parameters/…）→ SHA-256。"""
    if registry is None:
        from ..registry import default_registry

        registry = default_registry()
    return _hashes(registry, "parameters")


def data_file_hashes(registry: Registry | None = None) -> dict[str, str]:
    """結果の版に書く：表のデータ（okura_core からの相対パス。例 rules/kyuyo/data/…）→ SHA-256（いまのファイルの値）。"""
    if registry is None:
        from ..registry import default_registry

        registry = default_registry()
    return _hashes(registry, "data")


def parameter_dirs(registry: Registry | None = None) -> tuple[Path, ...]:
    if registry is None:
        from ..registry import default_registry

        registry = default_registry()
    return tuple(m.parameters_dir for m in registry.modules if m.parameters_dir.is_dir())
