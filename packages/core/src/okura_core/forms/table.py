"""様式の欄の対応表（データ）の型と読み込み（SCOPE §3「様式の欄の対応表」、HANDOFF D19 T5-2）。

対応表は年分ごとのデータ（forms/data/<年分のディレクトリ>/*.yaml。1ファイル＝1帳票）。年分の一覧は forms/data/index.yaml。
鍵は（年分、帳票、位置名）：帳票は e-Tax の様式ID＋ページ（例 KOA020-01）、位置名は様式の区画・行・列から作る名前
（docs/hypotheses/20261109_round2_yoshiki-mapping-table.md H1）。欄コード・欄番号・欄名は位置名の属性。

帳票のファイルのキー（知らないキーは誤り）：
  帳票・名称・様式番号・様式の根拠・記載事項の根拠・出典・欄       必須
  紙の様式ID・版の表示・仮説・注・検査                           省略可
  使う型        この帳票を使う申告の型（通常・第三表あり・損失申告）のリスト。必須
  使う条件      省略可。条件のリスト（すべて満たせば使う）か、文字列「事実」（入力の事実で決まる。例：次葉。fill は作らない）
  科目の表・所得  省略可（対応 {科目: …} を使う帳票は両方が要る）。科目の表は 割当て/科目.yaml の 表 の名前、所得は 事業所得・不動産所得
欄の項目のキー：
  位置          位置名（必須）。「行」「列」を書いたら {行}・{列} を含める（展開して1つずつの欄にする）
  番号・コード・名称・注   省略可（コードは「行」「列」があれば並びのリスト。~ はその位置に欄がない）
  型            金額・区分・人数・印・文字列・日付・個人番号（yoshiki-mapping-table H2）・数（人数でない整数：耐用年数・月数など。2026-11-12）
  単位          金額の欄の右端に印字された 0 の桁（1・100・1000・10000。既定 1）。値がその倍数でなければ食い違い
  行・列・列の型  繰り返し（行は数、列は名前のリスト、列の型は列ごとの型）
  人            行の区画の名前（rows.SECTIONS。行が要る）。行 i の欄は、区画の行の割当て（rows.assign_rows）が i 番目に置いた人の値を写す。
                その行に人がいなければ空欄。対応がなし（事実など）なら、欄の subject にその人を出す（利用アプリが入力の事実から書く）
  空ける        その申告の型では記入しない（yoshiki-mapping-table H4）
  出典          欄の追加の出典
  対応          欄 → 概念の対応（下）。概念 ID に {行}・{列} を書けば、展開した欄ごとにその行の番号・列の名前にする
                （例 所得税.事業所得の減価償却資産の行{行}.{列}。2026-11-12）
対応（変換）：
  {そのまま: 概念}                 概念の値を写す（所得税の概念は年分の値、「住民税.」の概念は年分＋1 の年度の値）
  {合計: [概念, …]}                概念の値の和（様式が1つの欄に複数の額を書かせるときと、様式の小計だけ。計算はしない：SCOPE §6-1）
  {値: 定数}                       区分の番号（"1" など）・印（true/false）・金額 0
  {空欄: 理由}                     書かない
  {未確定: 理由}                   一次情報で決まらない（決める手段は一次情報）
  {なし: 区分, 理由: 文}           対応する概念がない。区分は 事実・判断・対象外・未対応・未決・出力しない
  {問い: 年分}                     問いの年分（令和の年）
  {場合: [{もし: [条件, …], <上のどれか>}, …]}   条件つき（最初に条件をすべて満たす場合。もしのない場合は「それ以外」）
  {科目: 名前 か [名前, …]}        決算書・収支内訳書の科目（design-output UO19。リストは様式の小計）。読み込みで、年分のディレクトリの 割当て/科目.yaml の
                                   帳票の 科目の表 でその科目に割り当てた内訳のキーの概念「所得税.<所得>の必要経費の内訳.<キー>」の合計に展開する。
                                   内訳のない額（所得税.<所得>の必要経費のうち内訳のない額）が0でなければ「なし: 未対応」
                                   （科目の割当てのない必要経費があるので、科目ごとの額を出さない。雑費に入れない）。
                                   利用者の科目の割当ての選択（所得税.<所得>の科目の割当ての選択。2026-11-12）が「なし」でなければ、fill がキーを入れ替えて
                                   作り直す（FieldMapping.kamoku）
条件：{概念: ID, 判定: 正|零|負|非零|真|偽} か {概念: ID, 等しい: 区分の値} か {型: 申告の型} か {いずれか: [条件, …]}。
検査（様式に印字された式。yoshiki-mapping-table H3）：{式: 合計|差, 左: 位置, 右: [位置, …], 注}。
  合計：左 ＝ 右の和、差：左 ＝ 右[0] － 右[1:] の和。写した値が満たさなければ、その申告者・年分の欄を出さない。

読み込みは概念辞書と同じ安全な読み込み（SafeLoader に重複したキーの検査を足したもの：concepts.read_yaml）。
"""

from __future__ import annotations

import dataclasses
import functools
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..concepts import ConceptDictionary, read_yaml
from .rows import SECTIONS

DATA_DIR = Path(__file__).resolve().parent / "data"
INDEX_FILE = "index.yaml"

#: 申告の型（yoshiki-mapping-table H4）。
FILING_TYPES: tuple[str, ...] = ("通常", "第三表あり", "損失申告")
#: 欄の値の型（yoshiki-mapping-table H2）。
VALUE_TYPES: tuple[str, ...] = ("金額", "区分", "人数", "印", "文字列", "日付", "個人番号", "数")
#: 対応する概念がないときの区分。
NONE_CATEGORIES: tuple[str, ...] = ("事実", "判断", "対象外", "未対応", "未決", "出力しない")
#: 条件の判定。
TESTS: tuple[str, ...] = ("正", "零", "負", "非零", "真", "偽")
UNITS: tuple[int, ...] = (1, 100, 1000, 10000)
#: 欄が写してよい概念の制度（所得税は年分の値、住民税は年分＋1 の年度の値：fill.fill_forms）。
FIELD_INSTITUTIONS: frozenset[str] = frozenset({"所得税", "住民税"})
#: 年分の次の年度の値として読む概念 ID の接頭辞（住民税の制度）。
FISCAL_YEAR_PREFIX = "住民税."
#: 年分の状態。
YEAR_PUBLISHED = "公表済み"
YEAR_UNPUBLISHED = "未公表"

#: 欄の値の型 → 写してよい概念の値の型（概念辞書の「値の型」）。
CONCEPT_TYPES_FOR_FIELD: Mapping[str, frozenset[str]] = {
    "金額": frozenset({"円"}),
    "区分": frozenset({"区分"}),
    "人数": frozenset({"整数"}),
    "印": frozenset({"真偽"}),
    "文字列": frozenset({"区分"}),
    "日付": frozenset({"日付"}),
    "個人番号": frozenset(),
    "数": frozenset({"整数"}),
}
#: 条件の判定 → 概念の値の型。
CONCEPT_TYPES_FOR_TEST: Mapping[str, frozenset[str]] = {
    "正": frozenset({"円", "整数"}),
    "零": frozenset({"円", "整数"}),
    "負": frozenset({"円", "整数"}),
    "非零": frozenset({"円", "整数"}),
    "真": frozenset({"真偽"}),
    "偽": frozenset({"真偽"}),
    "等しい": frozenset({"区分"}),
}


class FormTableError(ValueError):
    """対応表のデータの誤り（読み込みで見つけたもの）。"""

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("様式の欄の対応表の誤り:\n" + "\n".join(self.problems))


# ---------------------------------------------------------------------------
# 型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Predicate:
    """条件。kind：概念・型・いずれか。"""

    kind: str
    concept: str | None = None
    test: str | None = None  # 正・零・負・非零・真・偽・等しい
    equals: str | None = None
    filing_type: str | None = None
    any_of: tuple[Predicate, ...] = ()

    def concepts(self) -> tuple[str, ...]:
        if self.kind == "概念":
            return (self.concept,) if self.concept else ()
        return tuple(c for p in self.any_of for c in p.concepts())


@dataclass(frozen=True)
class Outcome:
    """場合の結果。kind：そのまま・合計・値・空欄・未確定・なし・問い。"""

    kind: str
    concepts: tuple[str, ...] = ()
    value: Any = None
    category: str | None = None  # なし の区分
    reason: str | None = None


@dataclass(frozen=True)
class Case:
    when: tuple[Predicate, ...]
    outcome: Outcome


@dataclass(frozen=True)
class KamokuSpec:
    """{科目: …} の欄の材料（2026-11-12）：利用者の科目の割当ての選択（選択.様式への割当て C-18。rules/income_kinds/form_override.py）で
    内訳のキーを入れ替えるときに、fill が欄の対応を作り直すために使う。"""

    table: str
    income: str
    items: tuple[str, ...]
    assignments: Mapping[str, Mapping[str, str]] = field(compare=False)  # キー → 表 → 科目（KamokuTable.assignments。年分の表で同じ）

    @property
    def override_concept(self) -> str:
        return override_concept(self.income)

    def keys(self, override: Mapping[str, str]) -> tuple[str, ...] | None:
        """上書き（費目 → 費目：その費目の額を、選んだ費目の既定の科目に載せる）の後に、この欄の科目に載る内訳のキー。
        選んだ費目が割当ての表にないときは None。"""
        out: list[str] = []
        for key in self.assignments:
            target = override.get(key, key)
            if target not in self.assignments:
                return None
            if self.assignments[target][self.table] in self.items:
                out.append(key)
        return tuple(out)

    def cases(self, keys: Iterable[str]) -> tuple[Case, ...]:
        return _kamoku_cases(self.income, tuple(breakdown_concept(self.income, k) for k in keys))


@dataclass(frozen=True)
class FieldMapping:
    """欄 → 概念の対応。kind は人が読む変換の名前（そのまま・合計・条件・値・なし・問い）。
    kamoku は {科目: …} の欄だけ（cases は既定の割当て。利用者の選択があれば fill が kamoku から作り直す）。"""

    kind: str
    cases: tuple[Case, ...]
    kamoku: KamokuSpec | None = None

    def concepts(self) -> tuple[str, ...]:
        out: list[str] = []
        for c in self.cases:
            for p in c.when:
                out += p.concepts()
            out += c.outcome.concepts
        if self.kamoku is not None:
            out.append(self.kamoku.override_concept)
        return tuple(dict.fromkeys(out))

    @property
    def none_category(self) -> str | None:
        """対応する概念がない欄（場合のないなし）の区分。"""
        if self.kind == "なし":
            return self.cases[0].outcome.category
        return None


@dataclass(frozen=True)
class FieldSpec:
    form: str
    position: str
    value_type: str
    mapping: FieldMapping
    number: str | None = None
    code: str | None = None
    name: str | None = None
    unit: int = 1
    row: int | None = None
    blank_in: frozenset[str] = frozenset()
    references: tuple[str, ...] = ()
    note: str | None = None
    section: str | None = None  # 人：行の区画（rows.SECTIONS）
    capacity: int | None = None  # 区画の行の数（展開する前の 行）


@dataclass(frozen=True)
class Check:
    kind: str  # 合計・差
    left: str
    right: tuple[str, ...]
    note: str | None = None


@dataclass(frozen=True)
class FormTable:
    form: str
    name: str
    yoshiki_number: str
    form_basis: str
    items_basis: str
    references: tuple[str, ...]
    filing_types: frozenset[str]
    fields: tuple[FieldSpec, ...]
    paper_id: str | None = None
    version_label: str | None = None
    hypotheses: tuple[str, ...] = ()
    use_when: tuple[Predicate, ...] = ()
    use_by_facts: bool = False  # 使う条件「事実」：入力の事実で決まる（fill は作らない）
    checks: tuple[Check, ...] = ()
    note: str | None = None
    source_file: str = ""
    _by_position: Mapping[str, FieldSpec] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_position", {f.position: f for f in self.fields})

    def field_at(self, position: str) -> FieldSpec:
        return self._by_position[position]


@dataclass(frozen=True)
class YearTables:
    """年分の対応表。状態が未公表なら forms は空で、reason と references が拒否の理由。"""

    tax_year: int
    status: str
    references: tuple[str, ...]
    forms: tuple[FormTable, ...] = ()
    reason: str | None = None
    directory: str | None = None
    kamoku: KamokuTable | None = None  # 科目の割当て（UO19）

    def form(self, form_id: str) -> FormTable:
        for f in self.forms:
            if f.form == form_id:
                return f
        raise KeyError(form_id)


# ---------------------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------------------

_FORM_KEYS = frozenset(
    {
        "帳票", "名称", "様式番号", "紙の様式ID", "版の表示", "様式の根拠", "記載事項の根拠", "出典", "仮説", "注", "使う型", "使う条件", "欄", "検査",
        "科目の表", "所得",
    }
)  # fmt: skip
_FORM_REQUIRED = ("帳票", "名称", "様式番号", "様式の根拠", "記載事項の根拠", "出典", "使う型", "欄")
_FIELD_KEYS = frozenset({"位置", "番号", "コード", "名称", "型", "単位", "行", "列", "列の型", "空ける", "出典", "注", "対応", "人"})
_OUTCOME_KEYS = ("そのまま", "合計", "値", "空欄", "未確定", "なし", "問い")

#: 科目の割当ての表（年分のディレクトリの 割当て/科目.yaml）。
KAMOKU_FILE = "割当て/科目.yaml"
#: 帳票の 所得 → 必要経費の内訳の概念の接頭辞（rules/income_kinds/breakdown.py）。
KAMOKU_INCOMES: tuple[str, ...] = ("事業所得", "不動産所得")


def breakdown_concept(income: str, key: str) -> str:
    """必要経費の内訳の概念 ID（rules/income_kinds/breakdown.py と同じ名前）。"""
    return f"所得税.{income}の必要経費の内訳.{key}"


def unclassified_concept(income: str) -> str:
    return f"所得税.{income}の必要経費のうち内訳のない額"


def override_concept(income: str) -> str:
    """科目の割当ての利用者の選択の概念 ID（rules/income_kinds/form_override.py と同じ名前。値は「なし」か「費目=費目;…」）。"""
    return f"所得税.{income}の科目の割当ての選択"


#: 科目の割当ての選択の値の形（rules/income_kinds/form_override.py の encode と同じ）。
NO_OVERRIDE = "なし"


def decode_override(value: str) -> dict[str, str] | None:
    """「なし」は空、「費目=費目;…」は辞書。形が違えば None。"""
    if value == NO_OVERRIDE:
        return {}
    out: dict[str, str] = {}
    for part in value.split(";"):
        k, sep, v = part.partition("=")
        if not sep or not re.fullmatch(r"[a-z][a-z0-9_]*", k) or not re.fullmatch(r"[a-z][a-z0-9_]*", v) or k in out:
            return None
        out[k] = v
    return out


@dataclass(frozen=True)
class KamokuTable:
    """科目の割当て（UO19）：表の名前 → 内訳のキー → 科目。"""

    tables: tuple[str, ...]
    assignments: Mapping[str, Mapping[str, str]]  # キー → 表 → 科目
    references: tuple[str, ...]

    def keys_for(self, table: str, item: str) -> tuple[str, ...]:
        return tuple(k for k, m in self.assignments.items() if m[table] == item)


def parse_kamoku(data: Any, where: str = KAMOKU_FILE) -> KamokuTable:
    """割当て/科目.yaml を KamokuTable にする。どのキーも表ごとにちょうど1つの科目に割り当てる。"""
    p = _Problems(where)
    if not isinstance(data, Mapping) or set(data) != {"出典", "表", "割当て"}:
        raise FormTableError([f"{where}: キーは 出典・表・割当て"])
    tables, assignments, refs = data["表"], data["割当て"], data["出典"]
    if not isinstance(tables, list) or not tables or not all(isinstance(t, str) and t for t in tables):
        p.add("表は空でない名前のリスト")
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r for r in refs):
        p.add("出典は空でない文字列のリスト")
    if not isinstance(assignments, Mapping) or not assignments:
        p.add("割当ては空でない辞書")
    if p.items:
        raise FormTableError(p.items)
    out: dict[str, dict[str, str]] = {}
    for key, m in assignments.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            p.add(f"内訳のキーの形が違う: {key!r}")
            continue
        if not isinstance(m, Mapping) or set(m) != set(tables) or not all(isinstance(v, str) and v for v in m.values()):
            p.add(f"{key}: 表ごとに1つの科目（{'・'.join(tables)}）")
            continue
        out[key] = dict(m)
    if p.items:
        raise FormTableError(p.items)
    return KamokuTable(tuple(tables), out, tuple(refs))


def _kamoku_mapping(item: Any, table: str | None, income: str | None, kamoku: KamokuTable | None, p: _Problems) -> FieldMapping | None:
    """{科目: 名前} を、内訳の概念の合計（内訳のない額が0のとき）と なし: 未対応（それ以外）の条件つきの対応に展開する。"""
    if kamoku is None or table is None or income is None:
        p.add("科目 を使う帳票には 科目の表・所得 と年分の 割当て/科目.yaml が要る")
        return None
    items = item if isinstance(item, list) else [item]
    if not items or not all(isinstance(x, str) and x for x in items):
        p.add(f"科目 は科目の名前か、その空でないリスト（様式の小計）: {item!r}")
        return None
    keys: tuple[str, ...] = ()
    for x in items:
        found = kamoku.keys_for(table, x)
        if not found:
            p.add(f"科目「{x}」に割り当てた内訳のキーがない（{KAMOKU_FILE} の {table}）")
            return None
        keys += found
    concepts = tuple(breakdown_concept(income, k) for k in keys)
    return FieldMapping("科目", _kamoku_cases(income, concepts), kamoku=KamokuSpec(table, income, tuple(items), kamoku.assignments))


def _kamoku_cases(income: str, concepts: tuple[str, ...]) -> tuple[Case, ...]:
    """科目の欄の対応：内訳のない額が0なら内訳の概念の合計、それ以外は なし: 未対応。"""
    return (
        Case((Predicate(kind="概念", concept=unclassified_concept(income), test="零"),), Outcome("合計", concepts=concepts)),
        Case(
            (),
            Outcome(
                "なし",
                category="未対応",
                reason=f"{income}の必要経費に、科目の割当て（{KAMOKU_FILE}）のない額がある。科目ごとの額を出さない（雑費に入れない）",
            ),
        ),
    )


class _Problems:
    def __init__(self, where: str) -> None:
        self.where = where
        self.items: list[str] = []

    def add(self, msg: str) -> None:
        self.items.append(f"{self.where}: {msg}")


def _text(x: Any) -> str | None:
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (str, int)):
        raise TypeError(x)
    return str(x)


def _predicate(data: Any, p: _Problems) -> Predicate | None:
    if not isinstance(data, Mapping):
        p.add(f"条件は辞書: {data!r}")
        return None
    if "いずれか" in data:
        items = data["いずれか"]
        if set(data) != {"いずれか"} or not isinstance(items, list) or not items:
            p.add(f"いずれか は空でない条件のリストだけ: {data!r}")
            return None
        subs = tuple(x for x in (_predicate(i, p) for i in items) if x is not None)
        return Predicate(kind="いずれか", any_of=subs)
    if "型" in data:
        if set(data) != {"型"} or data["型"] not in FILING_TYPES:
            p.add(f"型の条件は {{型: {'|'.join(FILING_TYPES)}}}: {data!r}")
            return None
        return Predicate(kind="型", filing_type=data["型"])
    if "概念" in data:
        concept = data["概念"]
        if not isinstance(concept, str) or not concept:
            p.add(f"概念の ID は文字列: {data!r}")
            return None
        if set(data) == {"概念", "判定"} and data["判定"] in TESTS:
            return Predicate(kind="概念", concept=concept, test=data["判定"])
        if set(data) == {"概念", "等しい"} and isinstance(data["等しい"], str):
            return Predicate(kind="概念", concept=concept, test="等しい", equals=data["等しい"])
        p.add(f"概念の条件は 判定（{'・'.join(TESTS)}）か 等しい（文字列）: {data!r}")
        return None
    p.add(f"知らない条件: {data!r}")
    return None


def _outcome(data: Mapping[str, Any], p: _Problems, extra: frozenset[str] = frozenset()) -> Outcome | None:
    keys = [k for k in _OUTCOME_KEYS if k in data]
    if len(keys) != 1:
        p.add(f"対応の結果はちょうど1つ（{'・'.join(_OUTCOME_KEYS)}）: {dict(data)!r}")
        return None
    k = keys[0]
    allowed = {k} | extra | ({"理由"} if k == "なし" else set())
    unknown = set(data) - allowed
    if unknown:
        p.add(f"対応の知らないキー {sorted(unknown)}")
        return None
    v = data[k]
    if k == "そのまま":
        if not isinstance(v, str) or not v:
            p.add(f"そのまま は概念の ID: {v!r}")
            return None
        return Outcome("そのまま", concepts=(v,))
    if k == "合計":
        if not isinstance(v, list) or not v or not all(isinstance(x, str) and x for x in v) or len(set(v)) != len(v):
            p.add(f"合計 は重複のない概念の ID のリスト: {v!r}")
            return None
        return Outcome("合計", concepts=tuple(v))
    if k == "値":
        if v is None or not isinstance(v, (str, bool, int)):
            p.add(f"値 は文字列・真偽・整数: {v!r}")
            return None
        return Outcome("値", value=v)
    if k in ("空欄", "未確定"):
        if not isinstance(v, str) or not v:
            p.add(f"{k} には理由の文を書く: {v!r}")
            return None
        return Outcome(k, reason=v)
    if k == "なし":
        reason = data.get("理由")
        if v not in NONE_CATEGORIES or not isinstance(reason, str) or not reason:
            p.add(f"なし は区分（{'・'.join(NONE_CATEGORIES)}）と理由: {dict(data)!r}")
            return None
        return Outcome("なし", category=v, reason=reason)
    if v != "年分":
        p.add(f"問い は 年分 だけ: {v!r}")
        return None
    return Outcome("問い", value="年分")


def _mapping(data: Any, p: _Problems) -> FieldMapping | None:
    if not isinstance(data, Mapping):
        p.add(f"対応は辞書: {data!r}")
        return None
    if "場合" in data:
        cases_data = data["場合"]
        if set(data) != {"場合"} or not isinstance(cases_data, list) or not cases_data:
            p.add("場合 は空でないリストだけ")
            return None
        cases: list[Case] = []
        for i, c in enumerate(cases_data):
            if not isinstance(c, Mapping):
                p.add(f"場合[{i}] は辞書")
                return None
            when_data = c.get("もし", [])
            if not isinstance(when_data, list):
                p.add(f"場合[{i}] の もし は条件のリスト")
                return None
            when = tuple(x for x in (_predicate(w, p) for w in when_data) if x is not None)
            if len(when) != len(when_data):
                return None
            if not when and i != len(cases_data) - 1:
                p.add(f"場合[{i}]：もしのない場合（それ以外）は最後にだけ書く")
            out = _outcome({k: v for k, v in c.items() if k != "もし"}, p)
            if out is None:
                return None
            cases.append(Case(when, out))
        return FieldMapping("条件", tuple(cases))
    out = _outcome(data, p)
    if out is None:
        return None
    return FieldMapping(out.kind, (Case((), out),))


def _expand_mapping(mapping: FieldMapping, row: str | None, col: str | None) -> FieldMapping:
    """対応の概念 ID の {行}・{列} を、展開した欄の行の番号・列の名前にする（行 k の概念：例 減価償却費の計算の行ごとの資産の概念）。"""

    def sub(cid: str | None) -> str | None:
        if cid is None:
            return None
        if row is not None:
            cid = cid.replace("{行}", row)
        if col is not None:
            cid = cid.replace("{列}", col)
        return cid

    def pred(p: Predicate) -> Predicate:
        return dataclasses.replace(p, concept=sub(p.concept), any_of=tuple(pred(x) for x in p.any_of))

    if not any("{" in c for c in mapping.concepts()):
        return mapping
    return FieldMapping(
        mapping.kind,
        tuple(
            Case(tuple(pred(p) for p in c.when), dataclasses.replace(c.outcome, concepts=tuple(sub(x) or x for x in c.outcome.concepts)))
            for c in mapping.cases
        ),
        kamoku=mapping.kamoku,
    )


def _codes_for(raw: Any, rows: int | None, cols: list[str] | None, p: _Problems) -> list[list[str | None]] | None:
    """コードを [行][列] の格子にする（行・列がなければ 1×1）。"""
    nr = rows or 1
    nc = len(cols) if cols else 1
    if raw is None:
        return [[None] * nc for _ in range(nr)]
    if rows and cols:
        ok = isinstance(raw, list) and len(raw) == nr and all(isinstance(r, list) and len(r) == nc for r in raw)
        if not ok:
            p.add(f"行と列があるときのコードは {nr}×{nc} のリストのリスト")
            return None
        grid = [[c for c in r] for r in raw]
    elif rows or cols:
        n = nr if rows else nc
        if not isinstance(raw, list) or len(raw) != n:
            p.add(f"コードは {n} 個のリスト")
            return None
        grid = [[c] for c in raw] if rows else [list(raw)]
    else:
        grid = [[raw]]
    for r in grid:
        for c in r:
            if c is not None and not (isinstance(c, str) and re.fullmatch(r"[A-Z][0-9]{2,3}", c)):
                p.add(f"欄コードの形が違う: {c!r}")
                return None
    return grid


def _fields(
    form_id: str,
    data: Any,
    p: _Problems,
    kamoku: tuple[str | None, str | None, KamokuTable | None] = (None, None, None),
) -> list[FieldSpec]:
    out: list[FieldSpec] = []
    for i, f in enumerate(data):
        fp = _Problems(f"{p.where} 欄[{i}]")
        if not isinstance(f, Mapping):
            fp.add("欄は辞書")
            p.items += fp.items
            continue
        unknown = set(f) - _FIELD_KEYS
        if unknown:
            fp.add(f"知らないキー {sorted(unknown)}")
        pos = f.get("位置")
        if not isinstance(pos, str) or not pos:
            fp.add("位置がない")
            p.items += fp.items
            continue
        fp.where += f"（{pos}）"
        vtype = f.get("型")
        if vtype not in VALUE_TYPES:
            fp.add(f"型は {'・'.join(VALUE_TYPES)}: {vtype!r}")
        unit = f.get("単位", 1)
        if unit not in UNITS or isinstance(unit, bool):
            fp.add(f"単位は {UNITS}: {unit!r}")
        if unit != 1 and vtype != "金額":
            fp.add("単位は金額の欄だけ")
        rows = f.get("行")
        if rows is not None and (isinstance(rows, bool) or not isinstance(rows, int) or rows < 1):
            fp.add(f"行は1以上の整数: {rows!r}")
            rows = None
        cols = f.get("列")
        if cols is not None and (not isinstance(cols, list) or not cols or not all(isinstance(c, (str, int)) for c in cols)):
            fp.add(f"列は名前のリスト: {cols!r}")
            cols = None
        cols = [str(c) for c in cols] if cols else None
        col_types = f.get("列の型")
        if col_types is not None:
            if not cols or not isinstance(col_types, list) or len(col_types) != len(cols) or any(t not in VALUE_TYPES for t in col_types):
                fp.add(f"列の型は列と同じ数の型のリスト: {col_types!r}")
                col_types = None
        if rows and "{行}" not in pos:
            fp.add("行があるのに位置に {行} がない")
        if cols and "{列}" not in pos:
            fp.add("列があるのに位置に {列} がない")
        if ("{行}" in pos and not rows) or ("{列}" in pos and not cols):
            fp.add("位置の {行}・{列} に対応する 行・列 がない")
        section = f.get("人")
        if section is not None and (section not in SECTIONS or not rows):
            fp.add(f"人 は行のある欄の区画の名前（{'・'.join(SECTIONS)}）: {section!r}")
            section = None
        blank = f.get("空ける", [])
        if not isinstance(blank, list) or any(b not in FILING_TYPES for b in blank):
            fp.add(f"空ける は申告の型のリスト: {blank!r}")
            blank = []
        refs = f.get("出典", [])
        if not isinstance(refs, list) or not all(isinstance(r, str) and r for r in refs):
            fp.add("出典は文字列のリスト")
            refs = []
        m_data = f.get("対応")
        if isinstance(m_data, Mapping) and set(m_data) == {"科目"}:
            if vtype != "金額":
                fp.add("科目 は金額の欄だけ")
            mapping = _kamoku_mapping(m_data["科目"], *kamoku, fp)
        else:
            mapping = _mapping(m_data, fp)
        if mapping is not None:
            cs = mapping.concepts()
            if (any("{行}" in c for c in cs) and not rows) or (any("{列}" in c for c in cs) and not cols):
                fp.add("対応の概念の {行}・{列} に対応する 行・列 がない")
        grid = _codes_for(f.get("コード"), rows, cols, fp)
        try:
            number = _text(f.get("番号"))
            name = _text(f.get("名称"))
            note = _text(f.get("注"))
        except TypeError as e:
            fp.add(f"番号・名称・注は文字列: {e.args[0]!r}")
            number = name = note = None
        if fp.items or mapping is None or grid is None:
            p.items += fp.items or [f"{fp.where}: 対応の誤り"]
            continue
        for ri in range(rows or 1):
            for ci in range(len(cols) if cols else 1):
                code = grid[ri][ci]
                if (rows or cols) and f.get("コード") is not None and code is None:
                    continue  # ~：その位置に欄がない
                position = pos
                if rows:
                    position = position.replace("{行}", str(ri + 1))
                if cols:
                    position = position.replace("{列}", cols[ci])
                out.append(
                    FieldSpec(
                        form=form_id,
                        position=position,
                        value_type=col_types[ci] if col_types else vtype,
                        mapping=_expand_mapping(mapping, str(ri + 1) if rows else None, cols[ci] if cols else None),
                        number=number,
                        code=code,
                        name=name,
                        unit=unit,
                        row=(ri + 1) if rows else None,
                        blank_in=frozenset(blank),
                        references=tuple(refs),
                        note=note,
                        section=section,
                        capacity=rows if section else None,
                    )
                )
    return out


def _checks(data: Any, positions: set[str], p: _Problems) -> list[Check]:
    out: list[Check] = []
    if data is None:
        return out
    if not isinstance(data, list):
        p.add("検査はリスト")
        return out
    for i, c in enumerate(data):
        if not isinstance(c, Mapping) or set(c) - {"式", "左", "右", "注"} or c.get("式") not in ("合計", "差"):
            p.add(f"検査[{i}] は {{式: 合計|差, 左, 右, 注}}: {c!r}")
            continue
        left, right = c.get("左"), c.get("右")
        if not isinstance(left, str) or not isinstance(right, list) or not right or not all(isinstance(r, str) for r in right):
            p.add(f"検査[{i}] の左は位置、右は位置のリスト")
            continue
        missing = [x for x in [left, *right] if x not in positions]
        if missing:
            p.add(f"検査[{i}] の位置がない: {missing}")
            continue
        out.append(Check(c["式"], left, tuple(right), c.get("注")))
    return out


def parse_form(data: Any, source_file: str = "", kamoku: KamokuTable | None = None) -> FormTable:
    """帳票のファイルの中身を FormTable にする。誤りがあれば FormTableError。kamoku は年分の科目の割当て（{科目: …} の展開に使う）。"""
    p = _Problems(source_file or "帳票")
    if not isinstance(data, Mapping):
        raise FormTableError([f"{p.where}: 帳票のファイルは辞書"])
    unknown = set(data) - _FORM_KEYS
    if unknown:
        p.add(f"知らないキー {sorted(unknown)}")
    for k in _FORM_REQUIRED:
        if k not in data:
            p.add(f"{k} がない")
    if p.items:
        raise FormTableError(p.items)
    form_id = data["帳票"]
    if not isinstance(form_id, str) or not re.fullmatch(r"KO[AB][0-9]{3}-[0-9]{2}", form_id):
        p.add(f"帳票は e-Tax の様式ID＋ページ（例 KOA020-01）: {form_id!r}")
    for k in ("名称", "様式番号", "様式の根拠", "記載事項の根拠"):
        if not isinstance(data[k], str) or not data[k]:
            p.add(f"{k} は空でない文字列")
    refs = data["出典"]
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r for r in refs):
        p.add("出典は空でない文字列のリスト")
        refs = []
    hyps = data.get("仮説", [])
    if not isinstance(hyps, list) or not all(isinstance(r, str) and r for r in hyps):
        p.add("仮説は文字列のリスト")
        hyps = []
    types = data["使う型"]
    if not isinstance(types, list) or not types or any(t not in FILING_TYPES for t in types):
        p.add(f"使う型は申告の型のリスト: {types!r}")
        types = []
    use_when: list[Predicate] = []
    use_by_facts = False
    uw = data.get("使う条件")
    if uw == "事実":
        use_by_facts = True
    elif uw is not None:
        if not isinstance(uw, list) or not uw:
            p.add("使う条件は条件のリストか「事実」")
        else:
            use_when = [x for x in (_predicate(w, p) for w in uw) if x is not None]
    if not isinstance(data["欄"], list) or not data["欄"]:
        p.add("欄は空でないリスト")
        raise FormTableError(p.items)
    k_table, k_income = data.get("科目の表"), data.get("所得")
    if (k_table is None) != (k_income is None):
        p.add("科目の表 と 所得 は両方を書く")
    if k_income is not None and k_income not in KAMOKU_INCOMES:
        p.add(f"所得は {'・'.join(KAMOKU_INCOMES)}: {k_income!r}")
    if k_table is not None and (kamoku is None or k_table not in kamoku.tables):
        p.add(f"科目の表 {k_table!r} が年分の {KAMOKU_FILE} にない")
    fields = _fields(str(form_id), data["欄"], p, (k_table, k_income, kamoku))
    seen: dict[str, int] = {}
    codes: dict[str, str] = {}
    for f in fields:
        seen[f.position] = seen.get(f.position, 0) + 1
        if f.code is not None:
            if f.code in codes:
                p.add(f"欄コード {f.code} が2つの位置にある: {codes[f.code]}・{f.position}")
            codes[f.code] = f.position
    for pos, n in seen.items():
        if n > 1:
            p.add(f"位置名が重複している: {pos}")
    checks = _checks(data.get("検査"), set(seen), p)
    for k in ("紙の様式ID", "版の表示", "注"):
        if k in data and not isinstance(data[k], str):
            p.add(f"{k} は文字列")
    if p.items:
        raise FormTableError(p.items)
    return FormTable(
        form=form_id,
        name=data["名称"],
        yoshiki_number=data["様式番号"],
        form_basis=data["様式の根拠"],
        items_basis=data["記載事項の根拠"],
        references=tuple(refs),
        filing_types=frozenset(types),
        fields=tuple(fields),
        paper_id=data.get("紙の様式ID"),
        version_label=data.get("版の表示"),
        hypotheses=tuple(hyps),
        use_when=tuple(use_when),
        use_by_facts=use_by_facts,
        checks=tuple(checks),
        note=data.get("注"),
        source_file=source_file,
    )


def _read(path: Path) -> Any:
    return read_yaml(path.read_text(encoding="utf-8"), path.name)


@functools.cache
def load_index(data_dir: Path = DATA_DIR) -> Mapping[int, Mapping[str, Any]]:
    """年分の一覧（年分 → {状態, ディレクトリ, 理由, 出典}）。"""
    data = _read(data_dir / INDEX_FILE)
    years = data.get("年分") if isinstance(data, Mapping) else None
    if not isinstance(years, Mapping) or set(data) != {"年分"}:
        raise FormTableError([f"{INDEX_FILE}: 先頭のキーは 年分 だけ"])
    problems: list[str] = []
    out: dict[int, Mapping[str, Any]] = {}
    for year, entry in years.items():
        where = f"{INDEX_FILE} 年分 {year}"
        if isinstance(year, bool) or not isinstance(year, int) or not isinstance(entry, Mapping):
            problems.append(f"{where}: 年分は整数、中身は辞書")
            continue
        status = entry.get("状態")
        refs = entry.get("出典")
        if status not in (YEAR_PUBLISHED, YEAR_UNPUBLISHED) or not isinstance(refs, list) or not refs:
            problems.append(f"{where}: 状態（{YEAR_PUBLISHED}・{YEAR_UNPUBLISHED}）と出典が要る")
            continue
        if status == YEAR_PUBLISHED and not isinstance(entry.get("ディレクトリ"), str):
            problems.append(f"{where}: 公表済みの年分にはディレクトリが要る")
            continue
        if status == YEAR_UNPUBLISHED and not isinstance(entry.get("理由"), str):
            problems.append(f"{where}: 未公表の年分には理由が要る")
            continue
        out[year] = dict(entry)
    if problems:
        raise FormTableError(problems)
    return out


@functools.cache
def load_year(tax_year: int, data_dir: Path = DATA_DIR) -> YearTables | None:
    """年分の対応表。一覧にない年分は None。未公表の年分は forms が空の YearTables（status＝未公表）。"""
    entry = load_index(data_dir).get(tax_year)
    if entry is None:
        return None
    refs = tuple(entry["出典"])
    if entry["状態"] == YEAR_UNPUBLISHED:
        return YearTables(tax_year=tax_year, status=YEAR_UNPUBLISHED, references=refs, reason=entry["理由"])
    directory = entry["ディレクトリ"]
    problems: list[str] = []
    forms: list[FormTable] = []
    kamoku_path = data_dir / directory / KAMOKU_FILE
    kamoku = parse_kamoku(_read(kamoku_path), f"{directory}/{KAMOKU_FILE}") if kamoku_path.exists() else None
    for path in sorted((data_dir / directory).glob("*.yaml")):
        rel = f"{directory}/{path.name}"
        try:
            t = parse_form(_read(path), rel, kamoku)
        except FormTableError as e:
            problems += e.problems
            continue
        if path.stem != t.form:
            problems.append(f"{rel}: ファイル名と帳票（{t.form}）が違う")
        forms.append(t)
    if problems:
        raise FormTableError(problems)
    return YearTables(tax_year=tax_year, status=YEAR_PUBLISHED, references=refs, forms=tuple(forms), directory=directory, kamoku=kamoku)


# ---------------------------------------------------------------------------
# 概念辞書との突き合わせ（純粋関数）
# ---------------------------------------------------------------------------


def check_against_dictionary(tables: YearTables, dictionary: ConceptDictionary) -> list[str]:
    """対応表が使う概念が概念辞書に実在し、所得税か住民税の人ごと・年ごとの概念で、値の型が欄・条件と合うかを確かめる。

    所得税の概念はその年分（tax_year）の値、住民税の概念はその年分の次の年度（fiscal_year ＝ 年分＋1）の値として読む（fill.fill_forms）。
    住民税の年度の値は問いの resident_tax_fiscal_years に年分＋1 を含めたときだけ結果にある（forms/README.md §3）。
    """
    problems: list[str] = []

    def concept_ok(cid: str, where: str, allowed: frozenset[str]) -> None:
        c = dictionary.get(cid)
        if c is None:
            problems.append(f"{where}: 概念辞書にない概念 {cid}")
            return
        if c.institution not in FIELD_INSTITUTIONS or c.entity != "人物" or c.period != "年":
            problems.append(f"{where}: {cid} は所得税・住民税の人ごと・年ごとの概念ではない（{c.institution}・{c.entity}・{c.period}）")
        if not c.implemented:
            problems.append(f"{where}: {cid} は未実装の概念")
        if allowed and c.value_type not in allowed:
            problems.append(f"{where}: {cid} の値の型 {c.value_type} は {sorted(allowed)} でない")

    def preds(ps: Iterable[Predicate], where: str) -> None:
        for p in ps:
            if p.kind == "概念" and p.concept and p.test:
                concept_ok(p.concept, where, CONCEPT_TYPES_FOR_TEST[p.test])
            preds(p.any_of, where)

    for t in tables.forms:
        preds(t.use_when, f"{t.form} 使う条件")
        for f in t.fields:
            where = f"{t.form}/{f.position}"
            if f.mapping.kamoku is not None:
                concept_ok(f.mapping.kamoku.override_concept, where, frozenset({"区分"}))
            for case in f.mapping.cases:
                preds(case.when, where)
                o = case.outcome
                for cid in o.concepts:
                    concept_ok(cid, where, CONCEPT_TYPES_FOR_FIELD[f.value_type])
                if o.kind == "合計" and f.value_type != "金額":
                    problems.append(f"{where}: 合計は金額の欄だけ")
                if o.kind == "値":
                    ok = {
                        "金額": type(o.value) is int,
                        "区分": isinstance(o.value, str),
                        "文字列": isinstance(o.value, str),
                        "印": type(o.value) is bool,
                    }.get(f.value_type, False)
                    if not ok:
                        problems.append(f"{where}: 値 {o.value!r} は欄の型 {f.value_type} に合わない")
                if o.kind == "問い" and f.value_type != "区分":
                    problems.append(f"{where}: 問い（年分）は区分の欄だけ")
    return problems
