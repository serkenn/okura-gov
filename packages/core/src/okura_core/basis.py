"""根拠（D13・D22 S2）の型：根拠の種類（順序つきの列挙型）、読みの印、根拠の1項目。

D22 S2：結果の「状態」（後続の処理を変えるもの。result.py の State）と「根拠」（値ごとの出典と根拠の種類）を
別の項目として持つ。根拠の種類は順序つきの列挙型。「法令の読み」「原文未確認」は根拠の側の印（ReadingFlag）。

根拠の種類の順序（強い順。D22 S2・D21 R5）：
  1 法律・政令・省令  ＞ 2 告示 ＞ 3 通達（通知・事務連絡を同じ順位に置く） ＞ 4 手引き・様式の注記
  ＞ 5 国税庁の説明 ＞ 6 保険者の案内 ＞ 7 自治体の資料（注入データの出典にだけ使う）
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


class SourceKind(enum.Enum):
    """根拠の種類。値は出力に書く日本語の名前。順位は rank（小さいほど強い）。"""

    LAW = "法律"
    CABINET_ORDER = "政令"
    MINISTERIAL_ORDINANCE = "省令"
    PUBLIC_NOTICE = "告示"
    CIRCULAR = "通達"
    NOTIFICATION = "通知・事務連絡"
    GUIDE_OR_FORM_NOTE = "手引き・様式の注記"
    NTA_EXPLANATION = "国税庁の説明"
    INSURER_GUIDANCE = "保険者の案内"
    MUNICIPAL_MATERIAL = "自治体の資料"

    @property
    def rank(self) -> int:
        """強さの順位（1 が最も強い）。"""
        return _RANK[self]

    def is_statute(self) -> bool:
        """法令（法律・政令・省令）か。端数の根拠が法令以外かの判定（D21 R5）に使う。"""
        return self.rank == 1

    def stronger_than(self, other: SourceKind) -> bool:
        return self.rank < other.rank

    @classmethod
    def from_label(cls, label: str) -> SourceKind:
        for kind in cls:
            if kind.value == label:
                return kind
        raise ValueError(f"根拠の種類として知らない名前: {label!r}")


_RANK: dict[SourceKind, int] = {
    SourceKind.LAW: 1,
    SourceKind.CABINET_ORDER: 1,
    SourceKind.MINISTERIAL_ORDINANCE: 1,
    SourceKind.PUBLIC_NOTICE: 2,
    SourceKind.CIRCULAR: 3,
    SourceKind.NOTIFICATION: 3,
    SourceKind.GUIDE_OR_FORM_NOTE: 4,
    SourceKind.NTA_EXPLANATION: 5,
    SourceKind.INSURER_GUIDANCE: 6,
    SourceKind.MUNICIPAL_MATERIAL: 7,
}

#: 判定コアの規則（パラメータ・関数）の根拠に使ってはならない種類。注入データの出典にだけ使う（D22 S2）。
INJECTION_ONLY_KINDS: frozenset[SourceKind] = frozenset({SourceKind.MUNICIPAL_MATERIAL})


def strongest(kinds: Iterable[SourceKind]) -> SourceKind:
    """一番強い根拠の種類。空なら ValueError。"""
    items = list(kinds)
    if not items:
        raise ValueError("根拠の種類が1つもない")
    return min(items, key=lambda k: k.rank)


class ReadingFlag(enum.Enum):
    """根拠の側の印（D22 S1・S2、D21 R4）。"""

    #: 法令の読みが分かれうるところで、公式の説明があり反対の一次情報がない読みで計算した（D22 S1）。
    LEGAL_READING = "法令の読み"
    #: 原文（通達・大臣の定めなど）を docs で確かめていない（D21 R4）。
    ORIGINAL_UNVERIFIED = "原文未確認"

    @classmethod
    def from_label(cls, label: str) -> ReadingFlag:
        for flag in cls:
            if flag.value == label:
                return flag
        raise ValueError(f"読みの印として知らない名前: {label!r}")


class BasisType(enum.Enum):
    """根拠の項目の型。"""

    PARAMETER = "parameter"  # OpenFisca のパラメータ（基準額・率）
    DATA = "data"  # 大きな表のデータ（data/ の CSV）の行
    ROUNDING = "rounding"  # 名前つきの端数処理の関数
    RULE = "rule"  # 式・数え方・読み（パラメータでない規則）
    INJECTION = "injection"  # 注入データ（市町村・保険者）


@dataclass(frozen=True)
class BasisEntry:
    """根拠の1項目。

    - name：パラメータ名・表の名前・関数名・規則の名前。
    - source_kind：根拠の種類。端数の候補で評価したとき（根拠なし）だけ None。
    - references：出典（docs のファイル#節。注入データなら URL）。
    - flags：「法令の読み」「原文未確認」。
    - law：条・号など（人が読む）。
    - value：パラメータの値・表の行など（JSON にできる値）。
    - instant：参照日（パラメータを引いた日）。effective_from：適用開始日（YAML の日付のキー）。
      enforced_on：施行日（メタデータ）。
    - detail：そのほかの付記（ファイルの SHA-256、候補など。JSON にできる値）。
    """

    type: BasisType
    name: str
    source_kind: SourceKind | None
    references: tuple[str, ...]
    flags: tuple[ReadingFlag, ...] = ()
    law: str | None = None
    value: Any = None
    instant: str | None = None
    effective_from: str | None = None
    enforced_on: str | None = None
    detail: Mapping[str, Any] | None = field(default=None)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("根拠の名前が空")
        if self.source_kind is None and self.type is not BasisType.ROUNDING:
            raise ValueError(f"根拠の種類がない（端数の候補の評価だけが種類なしを許す）: {self.name}")
        if self.source_kind in INJECTION_ONLY_KINDS and self.type is not BasisType.INJECTION:
            raise ValueError(f"自治体の資料は注入データの出典にだけ使える: {self.name}")
        if not isinstance(self.references, tuple) or not all(isinstance(r, str) and r for r in self.references):
            raise ValueError(f"出典は空でない文字列のタプル: {self.name}")
        if self.type is not BasisType.ROUNDING and not self.references:
            raise ValueError(f"出典がない: {self.name}")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": self.type.value,
            "name": self.name,
            "source_kind": None if self.source_kind is None else self.source_kind.value,
            "references": list(self.references),
            "flags": [f.value for f in self.flags],
        }
        if self.law is not None:
            out["law"] = self.law
        if self.value is not None:
            out["value"] = self.value
        if self.instant is not None:
            out["instant"] = self.instant
        if self.effective_from is not None:
            out["effective_from"] = self.effective_from
        if self.enforced_on is not None:
            out["enforced_on"] = self.enforced_on
        if self.detail is not None:
            out["detail"] = dict(self.detail)
        return out
