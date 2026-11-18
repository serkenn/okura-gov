"""中間表現の検査：スキーマ（JSON Schema の部分集合）の検査と、意味の検査。

公開する関数：
  validate(ir) -> list[Problem]   例外で落ちず、問題の一覧を返す（空なら合格）。
  load_schema() -> dict           同梱のスキーマ（呼ぶたびに新しい dict）。

検査の順序：
  1. 根がオブジェクトか、schema_version が SCHEMA_VERSION か（違えばそれだけを返す）。
  2. スキーマの検査（jsonschema_subset）。問題があればそれを返し、意味の検査はしない。
  3. 意味の検査：ID の一意、参照先の存在と kind、役割の人の存在、区間の前後、
     日時の実在、割合が 1 以下、死亡日が生年月日の後、関係・対象の2人が別人、
     被扶養者の資格の被保険者、住民票の記録の重なり、判断・選択の置き換えの連鎖の整合。
"""

from __future__ import annotations

import datetime as _dt
import json
from importlib import resources
from typing import Any, Iterator

from .jsonschema_subset import Annotation, SchemaError, evaluate
from .problem import ROOT, Problem, child_index, child_key
from .vocabulary import LEDGER_SECTIONS, RECORD_SECTIONS, SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION", "load_schema", "validate"]

RECORD_SECTION_NAMES: tuple[str, ...] = tuple(RECORD_SECTIONS)
LEDGER_SECTION_NAMES: tuple[str, ...] = tuple(LEDGER_SECTIONS)
ALL_SECTION_NAMES: tuple[str, ...] = RECORD_SECTION_NAMES + LEDGER_SECTION_NAMES

# 参照の定義の名前 → 参照先の section（None はどの section でもよい）
_SECTION_REFS: dict[str, tuple[str, ...] | None] = {
    "ref_record": None,
    "ref_fact": ("facts",),
    "ref_asset": ("assets",),
    "ref_judgment": ("judgments",),
    "ref_choice": ("choices",),
}
_KIND_REF_PREFIX = "ref_kind_"
#: authority_decision の処分の種類 → その処分がある税目（減免 reduction_approved は住民税・国保の両方にあるので載せない。2026-11-12）
_AUTHORITY_TAX_ITEMS: dict[str, str] = {
    "kokuho_student_special_case_recognized": "national_health_insurance",
    "taxation_at_non_resident_record_municipality": "resident_tax",
}
#: 判断.特定支出の通常の範囲の額 を書ける支出の区分（所得税法施行令第167条の3第2項・第3項第1号・第3号・第5項。2026-11-12 の2回目）
_ROUTE_JUDGED_CATEGORIES = frozenset({"business_travel", "home_leave", "relocation"})


def _schema_bytes() -> bytes:
    return resources.files("okura_ir").joinpath("schema", "ir.schema.json").read_bytes()


def load_schema() -> dict[str, Any]:
    """同梱の ir.schema.json を読む。呼ぶたびに新しい dict を返す（共有の可変状態を持たない）。"""
    return json.loads(_schema_bytes().decode("utf-8"))


def validate(ir: Any) -> list[Problem]:
    """中間表現を検査し、問題の一覧を返す。例外は送出しない。"""
    try:
        return _validate(ir, load_schema())
    except SchemaError as exc:
        return [Problem(ROOT, "schema_error", f"同梱のスキーマが部分集合の外にある（{exc}）")]
    except Exception as exc:  # 最後の守り：検査器の誤りでも呼び出し側を落とさない
        return [Problem(ROOT, "internal_error", f"検査器の内部の誤り（{type(exc).__name__}）")]


def _validate(ir: Any, schema: dict[str, Any]) -> list[Problem]:
    if not isinstance(ir, dict):
        return [Problem(ROOT, "type", "中間表現の根はオブジェクトでなければならない")]
    if "schema_version" not in ir:
        return [Problem(child_key(ROOT, "schema_version"), "required", "schema_version が必要")]
    version = ir["schema_version"]
    if not (isinstance(version, str) and version == SCHEMA_VERSION):
        return [
            Problem(
                child_key(ROOT, "schema_version"),
                "unsupported_schema_version",
                f"この検査器は版 {SCHEMA_VERSION!r} だけを扱う（{version!r} が来た）",
            )
        ]
    outcome = evaluate(ir, schema)
    if outcome.problems:
        return outcome.problems
    return _semantic_problems(ir, outcome.annotations)


# ---------------------------------------------------------------------------
# 意味の検査
# ---------------------------------------------------------------------------


def _records(ir: dict[str, Any], section: str) -> Iterator[tuple[str, dict[str, Any]]]:
    base = child_key(ROOT, section)
    for i, record in enumerate(ir.get(section, [])):
        yield child_index(base, i), record


def _parse_datetime(text: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _semantic_problems(ir: dict[str, Any], annotations: list[Annotation]) -> list[Problem]:
    problems: list[Problem] = []

    # --- ID の一意（人と全部の記録をまとめて） ---
    persons: dict[str, dict[str, Any]] = {}
    records: dict[str, tuple[str, dict[str, Any]]] = {}
    first_seen: dict[str, str] = {}
    for path, person in _records(ir, "persons"):
        pid = person["id"]
        if pid in first_seen:
            problems.append(Problem(child_key(path, "id"), "duplicate_id", f"id {pid} が重複（最初は {first_seen[pid]}）"))
            continue
        first_seen[pid] = path
        persons[pid] = person
    for section in ALL_SECTION_NAMES:
        for path, record in _records(ir, section):
            rid = record["id"]
            if rid in first_seen:
                problems.append(
                    Problem(child_key(path, "id"), "duplicate_id", f"id {rid} が重複（最初は {first_seen[rid]}）")
                )
                continue
            first_seen[rid] = path
            records[rid] = (section, record)

    # --- 注釈を使う検査：参照・区間・日時・割合 ---
    for ann in annotations:
        name, path, value = ann.name, ann.path, ann.value
        if name == "ref_person":
            if value not in persons:
                problems.append(Problem(path, "unknown_person", f"persons にない人: {value}"))
        elif name in _SECTION_REFS:
            wanted = _SECTION_REFS[name]
            target = records.get(value)
            if target is None:
                problems.append(Problem(path, "unknown_reference", f"記録がない: {value}"))
            elif wanted is not None and target[0] not in wanted:
                problems.append(
                    Problem(path, "reference_kind_mismatch", f"{value} は {target[0]} の記録（{'・'.join(wanted)} が必要）")
                )
        elif name.startswith(_KIND_REF_PREFIX):
            kind = name[len(_KIND_REF_PREFIX) :]
            target = records.get(value)
            if target is None:
                problems.append(Problem(path, "unknown_reference", f"記録がない: {value}"))
            elif target[1].get("kind") != kind:
                problems.append(
                    Problem(path, "reference_kind_mismatch", f"{value} の kind は {target[1].get('kind')}（{kind} が必要）")
                )
        elif name == "period":
            to_on = value.get("to_on")
            if to_on is not None and to_on < value["from_on"]:
                problems.append(Problem(path, "period_reversed", f"to_on {to_on} が from_on {value['from_on']} より前"))
        elif name == "datetime":
            if _parse_datetime(value) is None:
                problems.append(Problem(path, "invalid_datetime", f"実在しない日時: {value}"))
        elif name == "ratio":
            if value["num"] > value["den"]:
                problems.append(Problem(path, "ratio_out_of_range", f"割合は 1 以下（{value['num']}/{value['den']}）"))

    # --- 人 ---
    for path, person in _records(ir, "persons"):
        death_on = person.get("death_on")
        if death_on is not None and death_on < person["birth_on"]:
            problems.append(Problem(child_key(path, "death_on"), "death_before_birth", "死亡日が生年月日より前"))

    # --- 関係の2人は別人 ---
    for path, record in _records(ir, "relations"):
        people = list(record["roles"].values())
        if len(set(people)) != len(people):
            problems.append(Problem(child_key(path, "roles"), "same_person", "関係の両側が同じ人"))

    # --- 判断・選択の対象（subject の直下の人の欄）は別人 ---
    subject_people: dict[str, list[str]] = {}
    for ann in annotations:
        if ann.name == "ref_person":
            parent, _, _leaf = ann.path.rpartition(".")
            if parent.endswith(".subject"):
                subject_people.setdefault(parent, []).append(ann.value)
    for section in LEDGER_SECTION_NAMES:
        for path, _record in _records(ir, section):
            subject_path = child_key(path, "subject")
            people = subject_people.get(subject_path, [])
            if len(set(people)) != len(people):
                problems.append(Problem(subject_path, "same_person", "対象の人が重なっている"))

    # --- 医療保険の資格：被扶養者には被保険者が要る ---
    for path, record in _records(ir, "insurance_memberships"):
        if record["kind"] != "medical_insurance":
            continue
        capacity = record["attributes"]["capacity"]
        roles = record["roles"]
        roles_path = child_key(path, "roles")
        if capacity == "dependent":
            if "insured" not in roles:
                problems.append(
                    Problem(child_key(roles_path, "insured"), "dependent_without_insured", "被扶養者の資格には被保険者（insured）が要る")
                )
            elif roles["insured"] == roles["member"]:
                problems.append(Problem(roles_path, "same_person", "被扶養者と被保険者が同じ人"))
        elif "insured" in roles:
            problems.append(
                Problem(child_key(roles_path, "insured"), "unexpected_insured_person", "被保険者本人の資格には insured を置かない")
            )

    # --- 給与の支払：差額の追給の元の支給日、通勤手当の内数（法令の解釈ではなく、記録どうしの整合） ---
    for path, record in _records(ir, "facts"):
        if record["kind"] != "salary_payment":
            continue
        attributes = record["attributes"]
        amounts = record["amounts"]
        attrs_path = child_key(path, "attributes")
        amounts_path = child_key(path, "amounts")
        if attributes.get("payment_type") == "retroactive_difference" and "original_due_on" not in attributes:
            problems.append(
                Problem(child_key(attrs_path, "original_due_on"), "retroactive_without_original_due_on", "差額の追給には元の支給日（original_due_on）が要る")
            )
        commuting = amounts.get("commuting_allowance", 0)
        if commuting > amounts["gross"]:
            problems.append(Problem(child_key(amounts_path, "commuting_allowance"), "commuting_exceeds_gross", "通勤手当が総支給額を超える（通勤手当は gross の内数）"))
        stated = amounts.get("commuting_nontaxable_stated", 0)
        if stated > commuting + amounts.get("commuting_pass_value", 0):
            problems.append(
                Problem(child_key(amounts_path, "commuting_nontaxable_stated"), "commuting_stated_exceeds_allowance", "非課税通勤費の記載が通勤手当と現物の定期券の価額の合計を超える")
            )

    # --- 通勤の状況：交通用具を使う号の距離、駐車場等の料金の単位ごとの欄（計算に要る事実の書き忘れを止める） ---
    for path, record in _records(ir, "facts"):
        if record["kind"] != "commuting_status":
            continue
        attributes = record["attributes"]
        attrs_path = child_key(path, "attributes")
        km = attributes.get("one_way_km")
        if attributes["means"] in ("vehicle", "transit_and_vehicle") and (km is None or km["num"] < 0):
            problems.append(Problem(child_key(attrs_path, "one_way_km"), "commuting_km_required", "交通用具を使う通勤には 0 以上の片道の距離（one_way_km）が要る"))
        for i, lot in enumerate(attributes.get("parkings", [])):
            lot_path = child_index(child_key(attrs_path, "parkings"), i)
            if lot["fee_unit"] == "per_use" and "uses_per_month" not in lot:
                problems.append(Problem(child_key(lot_path, "uses_per_month"), "parking_field_required", "利用の都度の料金には1か月当たりの利用回数が要る"))
            if lot["fee_unit"] == "other" and lot.get("fee_period_days", 0) < 1:
                problems.append(Problem(child_key(lot_path, "fee_period_days"), "parking_field_required", "単位が other の料金には1日以上の算定の基礎の日数が要る"))

    # --- 特定支出の候補の支出：内数・除く部分が支出金額を超えない（2026-11-12。記録どうしの整合） ---
    for path, record in _records(ir, "facts"):
        if record["kind"] != "specific_expense":
            continue
        amounts = record["amounts"]
        amounts_path = child_key(path, "amounts")
        inner = amounts.get("special_seat_fee", 0) + sum(record["attributes"].get("sleeper_fees", ()))
        if inner > amounts["amount"]:
            problems.append(Problem(child_key(amounts_path, "special_seat_fee"), "specific_expense_parts_exceed_amount", "特別の設備の料金・寝台料金（amount の内数）の合計が支出金額を超える"))
        if amounts.get("reimbursed_nontaxable", 0) + amounts.get("training_benefit", 0) > amounts["amount"]:
            problems.append(Problem(child_key(amounts_path, "reimbursed_nontaxable"), "specific_expense_parts_exceed_amount", "補塡される部分と教育訓練給付金等の部分の合計が支出金額を超える"))
        if "relocation_item" in record["attributes"] and record["attributes"]["category"] != "relocation":
            problems.append(
                Problem(child_key(child_key(path, "attributes"), "relocation_item"), "specific_expense_field_mismatch", "relocation_item は転居費（category: relocation）だけに書く")
            )

    # --- 判断.特定支出の通常の範囲の額：対象の支出の区分と額（2026-11-12 の2回目。kyuyo KY-13） ---
    expenses = {r["id"]: r for _, r in _records(ir, "facts") if r["kind"] == "specific_expense"}
    for path, judgment in _records(ir, "judgments"):
        if judgment["kind"] != "判断.特定支出の通常の範囲の額":
            continue
        target = expenses.get(judgment["subject"]["record_id"])
        if target is None:
            continue  # 参照先の検査（ref_record）が止める
        if target["attributes"]["category"] not in _ROUTE_JUDGED_CATEGORIES or target["attributes"].get("relocation_item") in ("vehicle", "moving"):
            problems.append(
                Problem(child_key(path, "subject"), "specific_expense_field_mismatch", "通常の範囲の判断は旅費・帰宅旅費・転居費（運賃・宿泊費）の支出だけに書く")
            )
        if judgment["value"]["countable_amount"] > target["amounts"]["amount"]:
            problems.append(
                Problem(child_key(child_key(path, "value"), "countable_amount"), "specific_expense_parts_exceed_amount", "通常の範囲の額が支出金額（amount）を超える")
            )

    # --- 市町村・保険者の個別の処分：処分の種類と税目（2026-11-12。修学中の特例の認定は国保だけ、住民票と違う市町村での課税は住民税だけ） ---
    for path, record in _records(ir, "facts"):
        if record["kind"] != "authority_decision":
            continue
        attributes = record["attributes"]
        wanted = _AUTHORITY_TAX_ITEMS.get(attributes["decision"])
        if wanted is not None and attributes["tax_item"] != wanted:
            problems.append(
                Problem(child_key(child_key(path, "attributes"), "tax_item"), "authority_decision_tax_item_mismatch", f"{attributes['decision']} の税目は {wanted}")
            )

    # --- 住民票の記録は同じ人について重ならない ---
    problems.extend(_overlapping_resident_records(ir))

    # --- 判断・選択の置き換えの連鎖 ---
    for section, time_key in (("judgments", "judged_at"), ("choices", "chosen_at")):
        problems.extend(_replacement_problems(ir, section, time_key))
    return problems


def _overlapping_resident_records(ir: dict[str, Any]) -> list[Problem]:
    problems: list[Problem] = []
    by_person: dict[str, list[tuple[str, str, str | None]]] = {}
    for path, record in _records(ir, "residences"):
        if record["kind"] != "resident_record":
            continue
        when = record["when"]
        by_person.setdefault(record["roles"]["person"], []).append((when["from_on"], when.get("to_on"), path))
    for person, spans in by_person.items():
        spans.sort(key=lambda s: (s[0], s[2]))
        # それまでの区間のうち一番遅く終わるもの（None は終わりがない）と比べる
        latest_end, latest_path = spans[0][1], spans[0][2]
        open_ended = latest_end is None
        for start, end, path in spans[1:]:
            if open_ended or start <= latest_end:
                problems.append(
                    Problem(
                        child_key(path, "when"),
                        "overlapping_interval",
                        f"{person} の住民票の記録が {latest_path} と重なる",
                    )
                )
            if not open_ended and (end is None or end > latest_end):
                latest_end, latest_path = end, path
                open_ended = end is None
    return problems


def _replacement_problems(ir: dict[str, Any], section: str, time_key: str) -> list[Problem]:
    problems: list[Problem] = []
    entries: dict[str, tuple[str, dict[str, Any]]] = {}
    for path, record in _records(ir, section):
        entries.setdefault(record["id"], (path, record))

    replaced_by: dict[str, str] = {}
    for rid, (path, record) in entries.items():
        target_id = record.get("replaces")
        if target_id is None or target_id not in entries:
            continue  # 存在しない置き換え先は参照の検査（unknown_reference / reference_kind_mismatch）で出る
        rpath = child_key(path, "replaces")
        target_path, target = entries[target_id]
        if target_id in replaced_by:
            problems.append(
                Problem(rpath, "replacement_fork", f"{target_id} は {replaced_by[target_id]} にも置き換えられている")
            )
        else:
            replaced_by[target_id] = rid
        if target["kind"] != record["kind"]:
            problems.append(
                Problem(rpath, "replacement_kind_mismatch", f"種類の違う記録を置き換えている（{record['kind']} → {target['kind']}）")
            )
        mine = _parse_datetime(record[time_key])
        theirs = _parse_datetime(target[time_key])
        if mine is not None and theirs is not None and mine < theirs:
            problems.append(
                Problem(rpath, "replacement_time_order", f"置き換える側の {time_key} が置き換えられる側より前")
            )

    # 循環：replaces をたどって同じ記録に戻る。
    # 各記録の replaces は高々1つなので、たどり終えた記録（done）は二度たどらない（全体で記録の数に比例。
    # 以前の実装は始点ごとに連鎖の終わりまでたどり、リストで探していたため、長い連鎖で入力の大きさの3乗の時間がかかった）。
    done: set[str] = set()
    for start in entries:
        if start in done:
            continue
        walk: list[str] = []
        position: dict[str, int] = {}
        current: str | None = start
        while current is not None and current in entries and current not in done and current not in position:
            position[current] = len(walk)
            walk.append(current)
            current = entries[current][1].get("replaces")
        if current is not None and current in position:
            cycle = walk[position[current] :]
            key = min(cycle)
            path = entries[key][0]
            problems.append(
                Problem(child_key(path, "replaces"), "replacement_cycle", f"置き換えが循環している（{' → '.join(cycle)}）")
            )
        done.update(walk)
    return problems
