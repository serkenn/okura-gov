"""根拠の組み立て（D13・D22 S2）：パラメータのメタデータ、OpenFisca のトレース、規則の根拠の一覧。

- パラメータ：名前と参照日から、パラメータの木をたどって値・適用開始日（YAML の日付のキー）・施行日・出典・
  根拠の種類・読みの印を取り出す（docs/measurements/20261109_impl-prep_tools-openfisca-probe.md §3・§4）。
- トレース：get_flat_trace() は使わず木をたどる。キーは期間を日まで含めて作る（同 §2.3）。時間の欄は使わない。
- 規則（パラメータでないもの）の根拠は、規則モジュールの RuleModule.rules・RuleModule.basis（registry.py）。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from openfisca_core.parameters import Parameter, ParameterNode

from .basis import BasisEntry, BasisType, ReadingFlag, SourceKind

_DETAIL_KEYS = ("適用", "比較", "unit", "law_revision", "reading", "note")


def find_parameter(root: ParameterNode, name: str) -> Parameter:
    node: Any = root
    for part in name.split("."):
        node = node.children[part]
    if not isinstance(node, Parameter):
        raise KeyError(f"パラメータではない: {name}")
    return node


def parameter_basis(root: ParameterNode, name: str, instant: str) -> BasisEntry:
    """パラメータ name の、参照日 instant の値の根拠。

    パラメータの木は組み立てた後に変えないので、（名前, 参照日）ごとに1回だけ作り、同じ根拠の項目（不変）を使い回す。
    """
    cache = root.__dict__.setdefault("_okura_basis_cache", {})
    key = (name, instant)
    hit = cache.get(key)
    if hit is None:
        hit = cache[key] = _parameter_basis(root, name, instant)
    return hit


def _parameter_basis(root: ParameterNode, name: str, instant: str) -> BasisEntry:
    param = find_parameter(root, name)
    for at in param.values_list:  # 新しい順
        if at.instant_str <= instant:
            break
    else:
        raise KeyError(f"{name} に {instant} の値がない")
    meta: dict[str, Any] = {**param.metadata, **at.metadata}
    try:
        kind = SourceKind.from_label(meta["source_kind"])
        refs = tuple(meta["reference"])
    except KeyError as e:
        raise KeyError(f"{name} のメタデータに {e} がない") from None
    flags = tuple(ReadingFlag.from_label(f) for f in meta.get("flags", []))
    detail = {k: meta[k] for k in _DETAIL_KEYS if k in meta}
    return BasisEntry(
        type=BasisType.PARAMETER,
        name=name,
        source_kind=kind,
        references=refs,
        flags=flags,
        law=meta.get("law"),
        value=at.value,
        instant=instant,
        effective_from=at.instant_str,
        enforced_on=meta.get("施行日"),
        detail=detail or None,
    )


# ---------------------------------------------------------------------------
# トレース
# ---------------------------------------------------------------------------


_PERIOD_KEYS: dict[Any, str] = {}


def period_key(period: Any) -> str:
    """期間のキー（日まで含める。str(Period) は日を落とす）。期間（不変のタプル）ごとに1回だけ文字列にする。"""
    hit = _PERIOD_KEYS.get(period)
    if hit is None:
        hit = _PERIOD_KEYS[period] = f"{period.unit}:{period.start}:{period.size}"
    return hit


@dataclass
class TraceEntry:
    children: set[tuple[str, str]] = field(default_factory=set)
    parameters: set[tuple[str, str]] = field(default_factory=set)


def trace_graph(tracer: Any) -> dict[tuple[str, str], TraceEntry]:
    """（変数名, 期間のキー）→ 子（依存した変数）とパラメータ（名前, 参照日）。同じ計算の全部の記録を合わせる。"""
    graph: dict[tuple[str, str], TraceEntry] = {}
    for node in tracer.browse_trace():
        key = (node.name, period_key(node.period))
        entry = graph.setdefault(key, TraceEntry())
        for child in node.children:
            entry.children.add((child.name, period_key(child.period)))
        for p in node.parameters:
            entry.parameters.add((p.name, str(p.period)))
    return graph


def sorted_unique(entries: Iterable[BasisEntry]) -> tuple[BasisEntry, ...]:
    """根拠の項目の重複を除き、決定的な順に並べる（型・名前・参照日）。"""
    seen: dict[tuple[str, str, str], BasisEntry] = {}
    for e in entries:
        seen.setdefault((e.type.value, e.name, e.instant or ""), e)
    return tuple(seen[k] for k in sorted(seen))
