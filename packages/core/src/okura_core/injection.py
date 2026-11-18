"""注入データ（市町村・保険者ごとに変わる値。D17・D19・D22、SCOPE §3・§8）の入れ物と検査。

注入データは利用側が出典つきで渡す宣言的なデータで、判定コアは値そのものを持たない（SCOPE §4）。
ここにあるのは、注入点（注入できる項目）ごとのデータの形（スキーマ）と検査だけ。注入点の一覧は injection_points.py。

注入データの JSON（配列）：

    [
      {"id": "inj-1",
       "point": "住民税.均等割の税率",                注入点の名前（injection_points.POINTS のどれか）
       "issuer": {"kind": "municipality", "code": "990001"},   団体（municipality・prefecture・insurer。注入点ごとに使える種類が決まる）
       "applies": {"from_on": "2026-04-01", "to_on": "2027-03-31"},  適用期間（to_on は任意。両端を含む）
       "source": {"url": "https://…", "retrieved_on": "2026-11-01", "source_kind": "自治体の資料",
                  "title": "…", "sha256": "…"},       title・sha256 は任意
       "data": { … }}                                 中身（注入点のスキーマで検査する）
    ]

検査（例外を送出しない。誤りは Problem の一覧）：
  - 包み：出典の URL・取得日・根拠の種類・適用期間が必須（SCOPE §8「出典（URL・取得日）と適用期間がないものは受け付けない」）。
  - 注入点：知らない名前は誤り（unknown_point）。団体の種類が注入点の種類でなければ誤り（issuer_kind）。
  - 中身：注入点のスキーマ（DataField の木）に合わないものは誤り。知らないキー・数の欄の文字列・小数・真偽値は拒否する
    （中間表現と同じ規則：金額は整数の円、率は {num, den}）。
  - 同じ注入点・同じ団体の適用期間が重なれば誤り（overlapping_period。どちらを使うかを判定コアが決めない）。

使い方（規則モジュール）：registry.InjectionSpec で「この値は注入点 X の団体 Y の、時点 Z のデータから来る」と宣言し、
YearContext.injection(注入点, key) で値を引く（registry.py・situation.py）。データがなければ、注入点の候補
（InjectionPoint.candidates：級地1〜3・調査で集めた運用の型など）の全部で評価し、結論が同じなら断定、違えば未確定と
「何を注入すれば決まるか」（分かれ目の決める手段＝注入）を返す（D19・D21 R6）。候補を持たない注入点（率・額など範囲が
有限でないもの）は、データがなければ、その値に依存する値を未確定にする（Decided.missing）。
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .basis import BasisEntry, BasisType, SourceKind
from .query import parse_date
from .result import Problem

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", re.ASCII)
#: 都道府県の団体コードの形（上2桁＋000＋検査数字。検査数字の検査は判定コアの juminzei.calc.prefecture_code が作る側で行う）
_PREF_CODE = re.compile(r"[0-9]{2}000[0-9]", re.ASCII)
_URL = re.compile(r"https?://[!-~]+", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
_NAME = re.compile(r"[^\u0000-\u001f\u007f]{1,100}")
ISSUER_KINDS = ("municipality", "prefecture", "insurer")
MAX_ENTRIES = 256
#: 金額の上限（誤入力と桁あふれを止めるための値で、法令の値ではない。okura_ir と同じ）。
YEN_MAX = 1_000_000_000_000
MAX_LIST = 200


# ---------------------------------------------------------------------------
# 中身のスキーマ
# ---------------------------------------------------------------------------

#: 欄の型：
#:   yen       0 以上の整数の円
#:   ratio     {num, den}（den は1以上。1 を超えない）
#:   count     0 以上の整数
#:   bool      真偽
#:   enum      values のどれかの文字列
#:   names     名前（1〜100文字）の配列（重複なし）
#:   object    fields の欄を持つオブジェクト
#:   objects   fields の欄を持つオブジェクトの配列（1件以上）
FIELD_KINDS = ("yen", "ratio", "count", "bool", "enum", "names", "object", "objects")


@dataclass(frozen=True)
class DataField:
    """注入データの中身の欄。"""

    name: str
    kind: str
    title: str
    required: bool = True
    values: tuple[str, ...] = ()
    fields: tuple[DataField, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"欄 {self.name} の型 {self.kind} は {FIELD_KINDS} のどれでもない")
        if (self.kind == "enum") != bool(self.values):
            raise ValueError(f"欄 {self.name}：enum だけが values を持つ")
        if (self.kind in ("object", "objects")) != bool(self.fields):
            raise ValueError(f"欄 {self.name}：object・objects だけが fields を持つ")


@dataclass(frozen=True)
class NamedCandidate:
    """注入されていないときの候補の1つ（級地・調査で集めた運用の型など）。data は注入点のスキーマに合う中身。"""

    label: str
    data: Mapping[str, Any]
    references: tuple[str, ...]
    note: str | None = None


@dataclass(frozen=True)
class InjectionPoint:
    """注入点（注入できる項目）。

    - name：`<制度>.<項目>`。概念辞書の「注入データ」に書く名前。
    - issuer_kinds：使える団体の種類。
    - fields：中身の欄。
    - timing：どの日の適用期間のデータを使うか（人が読む説明。どの日で引くかは規則モジュールが InjectionSlot.on に書く）。
    - candidates：注入されていないときの候補（空なら候補を持たない：その値に依存する値は未確定）。
      候補は「取りうる範囲」（級地1〜3のように有限のもの）か「調査で集めた運用の型」（D21 R6）に限る。既定値を1つ選ばない（D19）。
    - candidates_note：候補の範囲の説明（何を候補にし、何を候補にしなかったか）。
    - references：出典（docs/public-sources か docs/measurements の .md#節）。
    """

    name: str
    institution: str
    title: str
    issuer_kinds: tuple[str, ...]
    fields: tuple[DataField, ...]
    timing: str
    references: tuple[str, ...]
    candidates: tuple[NamedCandidate, ...] = ()
    candidates_note: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.name.startswith(self.institution + "."):
            raise ValueError(f"注入点 {self.name} の接頭辞が制度 {self.institution} と違う")
        if not self.issuer_kinds or any(k not in ISSUER_KINDS for k in self.issuer_kinds):
            raise ValueError(f"注入点 {self.name} の団体の種類が不正")
        labels = [c.label for c in self.candidates]
        if len(set(labels)) != len(labels):
            raise ValueError(f"注入点 {self.name} の候補の名前が重複している")
        if len(self.candidates) == 1:
            raise ValueError(f"注入点 {self.name} の候補が1つだけ（既定値になる。候補は2つ以上か、持たない）")

    def check_data(self, data: Any, path: str = "$.data") -> list[Problem]:
        """中身がスキーマに合うか（問題の一覧）。"""
        problems: list[Problem] = []
        _check_object(self.fields, data, path, problems)
        return problems


def _type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "真偽値"
    if isinstance(v, int):
        return "整数"
    if isinstance(v, float):
        return "小数"
    if isinstance(v, str):
        return "文字列"
    if isinstance(v, list):
        return "配列"
    if isinstance(v, dict):
        return "オブジェクト"
    return type(v).__name__


def _check_object(fields: tuple[DataField, ...], v: Any, path: str, problems: list[Problem]) -> None:
    if not isinstance(v, Mapping):
        problems.append(Problem(path, "type", f"オブジェクトが必要（{_type_name(v)} が来た）"))
        return
    names = {f.name for f in fields}
    for f in fields:
        if f.name not in v:
            if f.required:
                problems.append(Problem(f"{path}.{f.name}", "required", f"{f.name}（{f.title}）がない"))
            continue
        _check_field(f, v[f.name], f"{path}.{f.name}", problems)
    for k in v:
        if k not in names:
            problems.append(Problem(f"{path}.{k}", "additional_property", f"知らないキー: {k}"))


def _check_field(f: DataField, v: Any, path: str, problems: list[Problem]) -> None:
    if f.kind in ("yen", "count"):
        if type(v) is not int:
            problems.append(Problem(path, "type", f"整数が必要（{_type_name(v)} が来た）"))
        elif not 0 <= v <= YEN_MAX:
            problems.append(Problem(path, "range", f"0〜{YEN_MAX} の整数"))
    elif f.kind == "ratio":
        if not isinstance(v, Mapping) or set(v) != {"num", "den"}:
            problems.append(Problem(path, "type", "率は {num, den}（整数の分子と1以上の分母）"))
        elif type(v["num"]) is not int or type(v["den"]) is not int or v["num"] < 0 or v["den"] < 1:
            problems.append(Problem(path, "type", "率の分子は0以上の整数、分母は1以上の整数"))
        elif v["num"] > v["den"]:
            problems.append(Problem(path, "ratio_out_of_range", "率が1を超える"))
    elif f.kind == "bool":
        if type(v) is not bool:
            problems.append(Problem(path, "type", f"真偽値が必要（{_type_name(v)} が来た）"))
    elif f.kind == "enum":
        if not isinstance(v, str) or v not in f.values:
            problems.append(Problem(path, "enum", f"{list(f.values)} のどれか"))
    elif f.kind == "names":
        if not isinstance(v, list) or len(v) > MAX_LIST:
            problems.append(Problem(path, "type", f"名前の配列が必要（{MAX_LIST} 個まで）"))
            return
        for i, x in enumerate(v):
            if not isinstance(x, str) or not _NAME.fullmatch(x):
                problems.append(Problem(f"{path}[{i}]", "pattern", "名前は制御文字のない1〜100文字"))
        if all(isinstance(x, str) for x in v) and len(set(v)) != len(v):
            problems.append(Problem(path, "duplicate", "名前が重複している"))
    elif f.kind == "object":
        _check_object(f.fields, v, path, problems)
    elif f.kind == "objects":
        if not isinstance(v, list) or not v or len(v) > MAX_LIST:
            problems.append(Problem(path, "type", f"オブジェクトの配列が必要（1〜{MAX_LIST} 件）"))
            return
        for i, x in enumerate(v):
            _check_object(f.fields, x, f"{path}[{i}]", problems)


def check_catalog(points: Mapping[str, InjectionPoint]) -> list[str]:
    """注入点の一覧の矛盾（候補の中身がスキーマに合わない、名前の重複など）。空なら問題なし。"""
    out: list[str] = []
    for name, p in points.items():
        if name != p.name:
            out.append(f"{name}: 一覧のキーと名前が違う")
        for c in p.candidates:
            for prob in p.check_data(c.data, f"{name}.候補[{c.label}]"):
                out.append(f"{prob.path}: {prob.code} {prob.message}")
            if not c.references:
                out.append(f"{name}.候補[{c.label}]: 出典がない")
        if not p.references:
            out.append(f"{name}: 出典がない")
    return out


# ---------------------------------------------------------------------------
# 包みと項目
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InjectionSource:
    url: str
    retrieved_on: _dt.date
    source_kind: SourceKind
    title: str | None
    sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "retrieved_on": self.retrieved_on.isoformat(),
            "source_kind": self.source_kind.value,
            "title": self.title,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class InjectionEntry:
    id: str
    point: str
    issuer_kind: str
    issuer_code: str
    applies_from: _dt.date
    applies_to: _dt.date | None
    source: InjectionSource
    data: Mapping[str, Any]

    def covers(self, on: _dt.date) -> bool:
        """on が適用期間（両端を含む）に入るか。"""
        return self.applies_from <= on and (self.applies_to is None or on <= self.applies_to)

    def to_summary(self) -> dict[str, Any]:
        """結果に写す要約（中身の data は写さない）。"""
        return {
            "id": self.id,
            "point": self.point,
            "issuer": {"kind": self.issuer_kind, "code": self.issuer_code},
            "applies": {
                "from_on": self.applies_from.isoformat(),
                "to_on": None if self.applies_to is None else self.applies_to.isoformat(),
            },
            "source": self.source.to_dict(),
        }

    def basis(self, on: _dt.date) -> BasisEntry:
        """この項目を値の根拠にするときの根拠の項目（出典は注入データの URL）。"""
        detail: dict[str, Any] = {
            "injection_id": self.id,
            "issuer": {"kind": self.issuer_kind, "code": self.issuer_code},
            "applies": self.to_summary()["applies"],
            "retrieved_on": self.source.retrieved_on.isoformat(),
        }
        if self.source.title is not None:
            detail["title"] = self.source.title
        if self.source.sha256 is not None:
            detail["sha256"] = self.source.sha256
        return BasisEntry(
            type=BasisType.INJECTION,
            name=self.point,
            source_kind=self.source.source_kind,
            references=(self.source.url,),
            value=_plain(self.data),
            instant=on.isoformat(),
            detail=detail,
        )


def _plain(v: Any) -> Any:
    """JSON にできる、共有しない値の写し。"""
    if isinstance(v, Mapping):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


@dataclass(frozen=True)
class InjectedData:
    entries: tuple[InjectionEntry, ...]

    def find(self, point: str, issuer_kind: str, issuer_code: str, on: _dt.date) -> InjectionEntry | None:
        """注入点・団体の、on を適用期間に含む項目（parse_injected が重なりを拒否するので高々1つ）。"""
        for e in self.entries:
            if e.point == point and e.issuer_kind == issuer_kind and e.issuer_code == issuer_code and e.covers(on):
                return e
        return None

    def points(self) -> frozenset[str]:
        return frozenset(e.point for e in self.entries)


EMPTY = InjectedData(())


def _keys(obj: Mapping[str, Any], path: str, required: tuple[str, ...], optional: tuple[str, ...]) -> list[Problem]:
    out: list[Problem] = []
    for k in required:
        if k not in obj:
            out.append(Problem(f"{path}.{k}", "required", f"{k} がない"))
    for k in obj:
        if k not in required and k not in optional:
            out.append(Problem(f"{path}.{k}", "additional_property", f"知らないキー: {k}"))
    return out


def _entry(v: Any, path: str, problems: list[Problem], points: Mapping[str, InjectionPoint]) -> InjectionEntry | None:
    if not isinstance(v, dict):
        problems.append(Problem(path, "type", "注入データの項目はオブジェクト"))
        return None
    ps = _keys(v, path, ("id", "point", "issuer", "applies", "source", "data"), ())
    if ps:
        problems.extend(ps)
        return None
    n0 = len(problems)
    eid = v["id"]
    if not isinstance(eid, str) or not _ID.fullmatch(eid):
        problems.append(Problem(f"{path}.id", "pattern", "ID は英数字で始まる64文字までの ASCII"))
    point_name = v["point"]
    point: InjectionPoint | None = None
    if not isinstance(point_name, str) or not point_name or len(point_name) > 200:
        problems.append(Problem(f"{path}.point", "type", "注入点の名前は1〜200文字の文字列"))
    elif point_name not in points:
        problems.append(Problem(f"{path}.point", "unknown_point", f"知らない注入点: {point_name}（injection_points.POINTS）"))
    else:
        point = points[point_name]

    issuer = v["issuer"]
    ip = f"{path}.issuer"
    if not isinstance(issuer, dict):
        problems.append(Problem(ip, "type", "団体はオブジェクト {kind, code}"))
    else:
        ps = _keys(issuer, ip, ("kind", "code"), ())
        problems.extend(ps)
        if not ps:
            if issuer["kind"] not in ISSUER_KINDS:
                problems.append(Problem(f"{ip}.kind", "enum", f"団体の種類は {ISSUER_KINDS} のどれか"))
            elif point is not None and issuer["kind"] not in point.issuer_kinds:
                problems.append(
                    Problem(f"{ip}.kind", "issuer_kind", f"注入点 {point.name} の団体の種類は {list(point.issuer_kinds)} のどれか")
                )
            if not isinstance(issuer["code"], str) or not _ID.fullmatch(issuer["code"]):
                problems.append(Problem(f"{ip}.code", "pattern", "団体のコードは ASCII の文字列"))
            elif issuer["kind"] == "prefecture" and not _PREF_CODE.fullmatch(issuer["code"]):
                # 道府県の注入データの鍵は都道府県の団体コード（上2桁＋000＋検査数字。例 130001。2026-11-12 の整理：
                # docs/public-sources/20261111_impl-research3_juminzei-laws-and-soumu.md §4）。市町村のコードで書いた道府県の値を黙って使わない
                problems.append(Problem(f"{ip}.code", "prefecture_code", "道府県の団体のコードは都道府県の団体コード（上2桁＋000＋検査数字。例 130001）"))

    applies = v["applies"]
    ap = f"{path}.applies"
    a_from = a_to = None
    if not isinstance(applies, dict):
        problems.append(Problem(ap, "type", "適用期間はオブジェクト {from_on, to_on}"))
    else:
        ps = _keys(applies, ap, ("from_on",), ("to_on",))
        problems.extend(ps)
        if not ps:
            a_from = parse_date(applies["from_on"], f"{ap}.from_on", problems)
            if "to_on" in applies and applies["to_on"] is not None:
                a_to = parse_date(applies["to_on"], f"{ap}.to_on", problems)
            if a_from is not None and a_to is not None and a_to < a_from:
                problems.append(Problem(f"{ap}.to_on", "period_reversed", "適用期間の終わりが始まりより前"))

    source = v["source"]
    sp = f"{path}.source"
    src = None
    if not isinstance(source, dict):
        problems.append(Problem(sp, "type", "出典はオブジェクト {url, retrieved_on, source_kind}"))
    else:
        ps = _keys(source, sp, ("url", "retrieved_on", "source_kind"), ("title", "sha256"))
        problems.extend(ps)
        if not ps:
            url = source["url"]
            if not isinstance(url, str) or not _URL.fullmatch(url) or len(url) > 2000:
                problems.append(Problem(f"{sp}.url", "pattern", "出典の URL は http(s):// で始まる ASCII の文字列"))
            retrieved = parse_date(source["retrieved_on"], f"{sp}.retrieved_on", problems)
            kind = None
            try:
                kind = SourceKind.from_label(source["source_kind"]) if isinstance(source["source_kind"], str) else None
            except ValueError:
                kind = None
            if kind is None:
                problems.append(Problem(f"{sp}.source_kind", "enum", "根拠の種類は basis.SourceKind の名前のどれか"))
            title = source.get("title")
            if title is not None and (not isinstance(title, str) or len(title) > 500):
                problems.append(Problem(f"{sp}.title", "type", "title は500文字までの文字列"))
            sha = source.get("sha256")
            if sha is not None and (not isinstance(sha, str) or not _SHA256.fullmatch(sha)):
                problems.append(Problem(f"{sp}.sha256", "pattern", "sha256 は小文字の16進64文字"))
            if len(problems) == n0 and retrieved is not None and kind is not None:
                src = InjectionSource(url, retrieved, kind, title, sha)

    data = v["data"]
    if not isinstance(data, dict):
        problems.append(Problem(f"{path}.data", "type", "中身は JSON のオブジェクト"))
    elif point is not None:
        problems.extend(point.check_data(data, f"{path}.data"))

    if len(problems) != n0 or src is None or a_from is None:
        return None
    return InjectionEntry(
        id=eid,
        point=point_name,
        issuer_kind=issuer["kind"],
        issuer_code=issuer["code"],
        applies_from=a_from,
        applies_to=a_to,
        source=src,
        data=_plain(data),
    )


def _overlap(a: InjectionEntry, b: InjectionEntry) -> bool:
    a_end = a.applies_to or _dt.date.max
    b_end = b.applies_to or _dt.date.max
    return a.applies_from <= b_end and b.applies_from <= a_end


def parse_injected(
    raw: Any, *, path: str = "$", points: Mapping[str, InjectionPoint] | None = None
) -> tuple[InjectedData | None, list[Problem]]:
    """注入データを検査する。None は「注入なし」。例外を送出しない。points は注入点の一覧（省略は injection_points.POINTS）。"""
    if points is None:
        from .injection_points import POINTS  # 一覧はデータなので関数の中で読む（循環を避ける）

        points = POINTS
    if raw is None:
        return EMPTY, []
    if not isinstance(raw, list):
        return None, [Problem(path, "type", "注入データは配列（なければ null か []）")]
    if len(raw) > MAX_ENTRIES:
        return None, [Problem(path, "max_items", f"注入データは {MAX_ENTRIES} 項目まで")]
    problems: list[Problem] = []
    entries: list[tuple[int, InjectionEntry]] = []
    seen: set[str] = set()
    for i, v in enumerate(raw):
        e = _entry(v, f"{path}[{i}]", problems, points)
        if e is None:
            continue
        if e.id in seen:
            problems.append(Problem(f"{path}[{i}].id", "duplicate_id", f"ID {e.id} が重複している"))
            continue
        for _, other in entries:
            if (other.point, other.issuer_kind, other.issuer_code) == (e.point, e.issuer_kind, e.issuer_code) and _overlap(other, e):
                problems.append(
                    Problem(
                        f"{path}[{i}].applies",
                        "overlapping_period",
                        f"同じ注入点・同じ団体の項目 {other.id} と適用期間が重なる（どちらを使うかを判定コアは決めない）",
                    )
                )
                break
        seen.add(e.id)
        entries.append((i, e))
    if problems:
        return None, problems
    return InjectedData(tuple(e for _, e in entries)), []


__all__ = [
    "DataField",
    "EMPTY",
    "FIELD_KINDS",
    "ISSUER_KINDS",
    "InjectedData",
    "InjectionEntry",
    "InjectionPoint",
    "InjectionSource",
    "MAX_ENTRIES",
    "NamedCandidate",
    "check_catalog",
    "parse_injected",
]
