"""境目の説明の宣言の一覧と、主要な判定に宣言があるかの確かめ（D19「判定ごとの境目の説明」、SCOPE §2-6・§8）。

境目の説明そのもの（判定ごと：使った基準・今の値・差・またぐ値・境目の種類〔上限・下限〕）は evaluate._boundaries が結果の
scenarios[].boundaries に出す。ここは、規則モジュールが概念辞書の `境目` に宣言したものを一覧にし（declarations）、
主要な判定（扶養・特定親族・勤労学生・配偶者・住民税の非課税・被扶養者・国保の軽減・国年の免除）のうち宣言のないもの
（undeclared）を求める。宣言を足すのは各規則モジュールの担当（概念辞書の `境目`。基準が葉1つのパラメータなら `基準`、
判定日・人数などで変わる額なら `基準の概念` と `比較`）。

年齢の境目（2026-11-12）：概念辞書の `年齢の境目` に、判定の日の終了時の年齢と基準の年齢の比較を宣言する（例「その年12月31日に19歳以上か」）。
evaluate._age_boundaries が結果の scenarios[].age_boundaries に、生年月日・判定の日・今の年齢・基準・比較の結果・境目の日（基準の年齢に
達する日）・あと何日（境目の日 − 判定の日）を出す。一覧は age_declarations。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .registry import Registry


@dataclass(frozen=True)
class BoundaryDeclaration:
    """概念辞書の境目の宣言1つ。criterion はパラメータの名前（比較の向きはパラメータのメタデータ）か、基準の額を値に持つ概念の変数。"""

    module: str  # 判定の概念の担当
    judgment: str  # 判定の概念 ID（真偽）
    boundary_id: str
    compared: str  # 比べる量の概念 ID
    criterion: str
    comparison: str | None  # 基準の概念のときの比較の向き（パラメータの基準なら None：メタデータ）

    def to_dict(self) -> dict[str, str | None]:
        return {
            "module": self.module,
            "judgment": self.judgment,
            "boundary_id": self.boundary_id,
            "compared": self.compared,
            "criterion": self.criterion,
            "comparison": self.comparison,
        }


#: 主要な判定（境目の説明が要る判定。D19 の依頼の列）→ その判定の概念 ID。
MAIN_JUDGMENTS: Mapping[str, tuple[str, ...]] = {
    "扶養": ("所得税.扶養親族に当たるか",),
    "特定親族": ("所得税.特定親族に当たるか",),
    "勤労学生": ("所得税.勤労学生に当たるか",),
    "配偶者": ("所得税.同一生計配偶者に当たるか", "所得税.控除対象配偶者に当たるか"),
    "住民税の非課税": ("住民税.第295条第1項の非課税に当たるか", "住民税.所得割を課さない者か", "住民税.均等割を課さない者か"),
    "被扶養者": ("健保.被扶養者に当たるか",),
    "国保の軽減": ("国保.軽減の区分",),
    "国年の免除": (
        "国年.全額免除の所得基準を満たすか",
        "国年.一部免除の区分",
        "国年.学生納付特例の所得基準を満たすか",
        "国年.納付猶予の所得基準を満たすか",
    ),
}


def declarations(reg: Registry) -> tuple[BoundaryDeclaration, ...]:
    """登録した全モジュールの境目の宣言（Registry.boundaries の順）。"""
    d = reg.dictionary
    out: list[BoundaryDeclaration] = []
    for judgment_var, compared_var, criterion, boundary_id, comparison in reg.boundaries:
        j = d.by_variable(judgment_var)
        c = d.by_variable(compared_var)
        if j is None or c is None:
            continue
        crit = criterion
        if comparison is not None:
            k = d.by_variable(criterion)
            crit = k.id if k is not None else criterion
        out.append(BoundaryDeclaration(j.module or "", j.id, boundary_id, c.id, crit, comparison))
    return tuple(out)


@dataclass(frozen=True)
class AgeBoundaryDeclaration:
    """概念辞書の年齢の境目の宣言1つ（2026-11-12）。criterion はパラメータの葉か、年齢の数（age_value・comparison）。"""

    module: str  # 宣言した概念の担当
    related: str  # 宣言した概念 ID
    boundary_id: str
    age: str  # 比べる年齢の概念 ID
    reference: str  # 判定の日
    criterion: str | None
    age_value: int | None
    comparison: str | None
    exclude: str | None
    from_param: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "module": self.module,
            "related": self.related,
            "boundary_id": self.boundary_id,
            "age": self.age,
            "reference": self.reference,
            "criterion": self.criterion,
            "age_value": self.age_value,
            "comparison": self.comparison,
            "exclude": self.exclude,
            "from_param": self.from_param,
        }


def age_declarations(reg: Registry) -> tuple[AgeBoundaryDeclaration, ...]:
    """登録した全モジュールの年齢の境目の宣言（Registry.age_boundaries の順）。"""
    d = reg.dictionary
    out: list[AgeBoundaryDeclaration] = []
    for s in reg.age_boundaries:
        rel, age = d.by_variable(s.related_variable), d.by_variable(s.age_variable)
        ex = d.by_variable(s.exclude_variable) if s.exclude_variable else None
        if rel is None or age is None:
            continue
        out.append(
            AgeBoundaryDeclaration(
                rel.module or "", rel.id, s.boundary_id, age.id, s.reference, s.criterion, s.age_value, s.comparison,
                ex.id if ex is not None else None, s.from_param,
            )
        )
    return tuple(out)


def undeclared(reg: Registry, judgments: Mapping[str, tuple[str, ...]] = MAIN_JUDGMENTS) -> dict[str, tuple[str, ...]]:
    """主要な判定のうち、境目の宣言がないもの（区分 → 概念 ID）。

    判定の概念そのものか、その直接の依存（概念辞書の「依存する概念」の1段）に境目の宣言があれば宣言ありとする
    （例：所得税.扶養親族に当たるか は 所得税.扶養親族の合計所得金額要件 の境目で説明する）。概念辞書にない概念 ID は数えない。
    """
    d = reg.dictionary
    declared = {b.judgment for b in declarations(reg)}
    out: dict[str, tuple[str, ...]] = {}
    for label, ids in judgments.items():
        missing: list[str] = []
        for cid in ids:
            c = d.get(cid)
            if c is None:
                continue
            if cid in declared or any(t in declared for t in c.declared_targets()):
                continue
            missing.append(cid)
        if missing:
            out[label] = tuple(missing)
    return out


__all__ = ["MAIN_JUDGMENTS", "AgeBoundaryDeclaration", "BoundaryDeclaration", "age_declarations", "declarations", "undeclared"]
