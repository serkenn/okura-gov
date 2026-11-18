"""中間表現（okura_ir で検査済み）から、年分ごとの OpenFisca の situation を組み立てる（R4 H6 提案2・D7 改）。

共通の部分だけを持つ。何をどう写すかは規則モジュールが宣言する（registry.RuleModule）：
- 入力変数の値：RuleModule.build_inputs（YearContext → ModuleInputs）。モジュールは自分の入力変数を、その年分に生存している
  全員について書く（書き忘れは誤り）。値の由来（記録・判断・選択の ID と印から決まる状態）も一緒に返す。
- 判断・選択：RuleModule.decisions（DecisionSpec）が「この年分に要る1か所」を宣言し、ここで中間表現の判断・選択（置き換えの
  連鎖の先頭）から値を決める。なければ「未入力」で、候補（語彙の値の領域か、宣言した候補）を evaluate が全部評価する（D21 R6）。
- 根拠のない端数：RuleModule.roundings。候補の名前を入力変数で式に渡す（D22 S3）。
- グループ：RuleModule.groups。組み立てるモジュールがないグループは、全員を自分だけのインスタンスの最初の役割に明示して書く
  （扶養所属＝申告者、法律婚＝配偶者、健康保険＝対象外。R4 H1.6：書き忘れを起こさない）。
- 段階評価（D23 K1）：StageState が前の段までに決まった入力・グループ・対象外を持ち、build_year がそれを入れて situation を作る。
- OpenFisca に渡す値は int・bool・str・date だけ。int は 0 以上 int32 の上限以下を確かめる（入力の検査の後の二重の守り）。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from okura_ir import vocabulary

from .candidates import Candidate, Policy, Slot
from .country.entities import ENTITIES, SOLO_ROLE
from .money import INT32_MAX
from . import registry as _registry
from .registry import (
    RECORD_SECTIONS,
    Decided,
    DecisionSpec,
    Exclusion,
    GroupInstance,
    InjectionSlot,
    InjectionSpec,
    InputValue,
    ModuleInputs,
    Registry,
    ReadingSlotSpec,
    RoundingSlotSpec,
    StageContext,
    StageSpec,
    StageValue,
    YearContext,
    overlaps_year,
)
from .result import Means, OutOfScopeCategory, OutOfScopeReason, Split, State
from .rounding import unfounded_slot
from .scope import strings_in

# ---------------------------------------------------------------------------
# 判断・選択の1か所の値を決める
# ---------------------------------------------------------------------------


def _domain(kind: str) -> tuple[Candidate, ...] | None:
    """中間表現の語彙の値の領域から候補を作る（真偽・列挙だけ）。"""
    for k in [*vocabulary.JUDGMENT_KINDS, *vocabulary.CHOICE_KINDS]:
        if k.kind != kind:
            continue
        v = k.value if isinstance(k.value, Mapping) else {}
        if v.get("type") == "boolean":
            return (Candidate(True, "true"), Candidate(False, "false"))
        if "enum" in v:
            return tuple(Candidate(x, str(x)) for x in v["enum"])
        return None
    raise KeyError(f"中間表現の語彙にない判断・選択の種類: {kind}")


def _state_of(rec: Mapping[str, Any]) -> frozenset[State]:
    return frozenset({State.from_mark(rec["mark"])}) if "mark" in rec else frozenset()


def _label(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class Decisions:
    """年分の判断・選択の1か所の値。fixed は中間表現で決まったもの、open は未入力（候補を評価する分かれ目）。

    monotone_members：単調な判断の両端評価の分かれ目（Policy.MONOTONE）の ID → 群の1か所の一覧 ((種類, key), 候補)。候補の値は添字（0・1）で、
    群の各1か所には同じ添字の候補を入れる。
    """

    fixed: Mapping[tuple[str, str], Decided]
    open: tuple[Slot, ...]
    slot_keys: Mapping[str, tuple[str, str]]  # 分かれ目の ID → (種類, key)
    monotone_members: Mapping[str, tuple[tuple[tuple[str, str], tuple[Candidate, ...]], ...]] = field(default_factory=dict)
    #: 読んだときだけ開く未入力の1か所（DecisionSlot.lazy）。最初は最初の候補で計算し、読まれたら evaluate が分かれ目にする。
    lazy: tuple[Slot, ...] = ()


def slot_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def _record_persons(ir: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """記録の ID → その記録の役割の人。"""
    return {r["id"]: tuple(sorted(set(r.get("roles", {}).values()))) for s in RECORD_SECTIONS for r in ir[s]}


def _slot_persons(
    slot: Any, person_ids: frozenset[str], record_persons: Mapping[str, tuple[str, ...]]
) -> tuple[str, ...]:
    """判断の1か所に関係する人。宣言（DecisionSlot.persons）がなければ target と key から導く（人の ID・記録の ID の役割の人）。"""
    if slot.persons is not None:
        return tuple(dict.fromkeys(slot.persons))
    found: set[str] = set()
    for text in strings_in(slot.target) | {slot.key}:
        for piece in (text, *text.replace(",", ":").split(":")):
            if piece in person_ids:
                found.add(piece)
            found.update(record_persons.get(piece, ()))
    return tuple(sorted(found))


@dataclass
class _MonotoneMember:
    key: tuple[str, str]
    candidates: tuple[Candidate, ...]
    target: Mapping[str, Any]
    persons: tuple[str, ...]


def resolve_decisions(ctx: YearContext, reg: Registry) -> Decisions:
    fixed: dict[tuple[str, str], Decided] = {}
    open_slots: dict[str, Slot] = {}
    keys: dict[str, tuple[str, str]] = {}
    monotone: dict[str, list[_MonotoneMember]] = {}
    lazy: dict[str, Slot] = {}
    person_ids = frozenset(p["id"] for p in ctx.ir["persons"])
    rec_persons = _record_persons(ctx.ir)
    done: set[tuple[str, str]] = set()
    for m in reg.modules:
        for spec in m.decisions:
            records = ctx.choices(spec.kind) if spec.section == "choices" else ctx.judgments(spec.kind)
            for slot in spec.slots(ctx):
                sid = slot_id(spec.kind, slot.key)
                if (spec.kind, slot.key) in done:
                    continue  # 同じ1か所をほかのモジュールも宣言した
                done.add((spec.kind, slot.key))
                matched = [r for r in records if slot.matches(r) and (not slot.year_filter or overlaps_year(r.get("when"), ctx.year))]
                persons = _slot_persons(slot, person_ids, rec_persons)
                _resolve_one(spec, slot, sid, matched, fixed, lazy if slot.lazy else open_slots, keys, persons, monotone)
        for ispec in m.injections:
            for islot in ispec.slots(ctx):
                key = (ispec.kind, islot.key)
                if key in done:
                    continue  # 同じ1か所をほかのモジュールも宣言した
                done.add(key)
                _resolve_injection(ctx, ispec, islot, fixed, open_slots, keys, _slot_persons(islot, person_ids, rec_persons))
    collapsed, members = _collapse_monotone(monotone)
    open_slots.update(collapsed)
    return Decisions(fixed, tuple(open_slots[k] for k in sorted(open_slots)), keys, members, tuple(lazy[k] for k in sorted(lazy)))


def _resolve_injection(
    ctx: YearContext,
    spec: InjectionSpec,
    slot: InjectionSlot,
    fixed: dict[tuple[str, str], Decided],
    open_slots: dict[str, Slot],
    keys: dict[str, tuple[str, str]],
    persons: tuple[str, ...],
) -> None:
    """注入データの1か所（D17・D19・D21 R6）：注入されていればその中身、なければ注入点の候補で分かれ目、候補がなければ missing。"""
    from .injection_points import POINTS  # 関数の中で読む（循環を避ける）

    key = (spec.kind, slot.key)
    entry = ctx.injected.find(spec.point, slot.issuer_kind, slot.issuer_code, slot.on)
    if entry is not None:
        fixed[key] = Decided(entry.data, (entry.id,), frozenset(), open=False, basis=(entry.basis(slot.on),))
        return
    point = POINTS[spec.point]
    target = {
        **dict(slot.target),
        "kind": spec.kind,
        "注入点": spec.point,
        "団体": {"kind": slot.issuer_kind, "code": slot.issuer_code},
        "適用の日": slot.on.isoformat(),
    }
    sid = slot_id(spec.kind, slot.key)
    candidates = slot.candidates
    if candidates is None:
        candidates = tuple(Candidate(c.data, c.label) for c in point.candidates)
    if len(candidates) >= 2:
        open_slots[sid] = Slot(id=sid, means=Means.INJECTION, target=target, candidates=tuple(candidates), persons=persons)
        keys[sid] = key
        return
    # 候補を持たない注入点（率・額など）：値は決まらない。依存する値を未確定にする（既定値で計算しない：D19）
    missing = Split(id=sid, means=Means.INJECTION, target=target, candidates=(), splits_conclusion=True)
    fixed[key] = Decided(None, (), frozenset(), open=False, missing=(missing,))


def _collapse_monotone(
    groups: Mapping[str, list[_MonotoneMember]],
) -> tuple[dict[str, Slot], dict[str, tuple[tuple[tuple[str, str], tuple[Candidate, ...]], ...]]]:
    """単調な判断の群を、両端（候補の添字 0 と 1）の2つの候補の1つの分かれ目にまとめる（D21 R6）。"""
    slots: dict[str, Slot] = {}
    members: dict[str, tuple[tuple[tuple[str, str], tuple[Candidate, ...]], ...]] = {}
    for group in sorted(groups):
        items = sorted(groups[group], key=lambda x: x.key)
        labels = tuple(c.label for c in items[0].candidates)
        if len(labels) != 2 or any(tuple(c.label for c in it.candidates) != labels for it in items):
            raise ValueError(f"単調な判断の群 {group} の1か所の候補は、同じ名前の2つでなければならない")
        sid = f"単調:{group}"
        target = {
            "monotone": group,
            "evaluated_at_ends_only": True,
            "members": [{**dict(it.target), "key": it.key[1], "kind": it.key[0]} for it in items],
        }
        persons = tuple(sorted({p for it in items for p in it.persons}))
        slots[sid] = Slot(
            id=sid,
            means=Means.JUDGMENT,
            target=target,
            candidates=(Candidate(0, labels[0]), Candidate(1, labels[1])),
            policy=Policy.MONOTONE,
            persons=persons,
        )
        members[sid] = tuple((it.key, it.candidates) for it in items)
    return slots, members


def _resolve_one(
    spec: DecisionSpec,
    slot: Any,
    sid: str,
    matched: list[Mapping[str, Any]],
    fixed: dict[tuple[str, str], Decided],
    open_slots: dict[str, Slot],
    keys: dict[str, tuple[str, str]],
    persons: tuple[str, ...],
    monotone: dict[str, list[_MonotoneMember]],
) -> None:
    key = (spec.kind, slot.key)
    values = [spec.value_of(r) for r in matched]
    if matched and all(v == values[0] for v in values):
        ids = tuple(sorted(r["id"] for r in matched))
        states = frozenset(s for r in matched for s in _state_of(r))
        fixed[key] = Decided(values[0], ids, states, open=False)
        return
    target = dict(slot.target)
    target["kind"] = spec.kind
    if matched:  # 食い違う判断・選択：違う値だけを候補にして評価する
        seen: dict[str, Candidate] = {}
        for v in values:
            seen.setdefault(_label(v), Candidate(v, _label(v)))
        candidates = tuple(seen[k] for k in sorted(seen))
        target["conflicting_ids"] = sorted(r["id"] for r in matched)
    else:
        candidates = slot.candidates if slot.candidates is not None else _domain(spec.kind)
        if candidates is None:
            raise ValueError(f"{spec.kind} の値の領域から候補を作れない（DecisionSlot.candidates を書く）")
    if slot.monotone is not None:
        if slot.lazy:
            raise ValueError(f"{spec.kind} {slot.key}：読んだときだけ開く1か所（lazy）は単調な判断の群（monotone）にできない")
        monotone.setdefault(slot.monotone, []).append(_MonotoneMember(key, tuple(candidates), target, persons))
        return
    open_slots[sid] = Slot(id=sid, means=Means.JUDGMENT, target=target, candidates=tuple(candidates), persons=persons)
    keys[sid] = key


def reading_slot(spec: ReadingSlotSpec) -> Slot:
    """法令の読みの候補の分かれ目（ID「読み:<name>」、方針 READING、決める手段は一次情報）。"""
    target: dict[str, Any] = {"reading": spec.name, "title": spec.title}
    if spec.variable is not None:
        target["variable"] = spec.variable
    if spec.explanations:
        target["explanations"] = {k: spec.explanations[k] for k in spec.candidates if k in spec.explanations}
    return Slot(
        id=f"読み:{spec.name}",
        means=Means.PRIMARY_SOURCE,
        target=target,
        candidates=tuple(Candidate(value=c, label=c) for c in spec.candidates),
        policy=Policy.READING,
    )


def rounding_slots(reg: Registry) -> tuple[tuple[Slot, RoundingSlotSpec | ReadingSlotSpec], ...]:
    """根拠のない端数（RoundingSlotSpec）と法令の読みの候補（ReadingSlotSpec）の分かれ目。どちらも候補の名前を
    入力変数（variable）か YearContext の窓口で渡し、読んだときだけ開き、金額なら幅にする（同じ広げ方・まとめ方）。"""
    out: dict[str, tuple[Slot, RoundingSlotSpec | ReadingSlotSpec]] = {}
    for m in reg.modules:
        for spec in m.roundings:
            target = {"title": spec.title}
            if spec.variable is not None:
                target["variable"] = spec.variable
            s = unfounded_slot(spec.name, target=target)
            out.setdefault(s.id, (s, spec))
        for rspec in m.readings:
            s = reading_slot(rspec)
            out.setdefault(s.id, (s, rspec))
    return tuple(out[k] for k in sorted(out))


# ---------------------------------------------------------------------------
# 年分の situation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YearBuild:
    """候補の組1つについて組み立てた situation と、入力の由来・対象外・グループ。"""

    situation: Mapping[str, Any]
    persons: tuple[str, ...]
    inputs: Mapping[tuple[str, str], InputValue]
    exclusions: tuple[Exclusion, ...]
    groups: Mapping[str, tuple[GroupInstance, ...]]

    def group_signature(self) -> str:
        sig = self.__dict__.get("_group_signature")
        if sig is None:  # 不変なので1回だけ作る（frozen の dataclass の項目ではない写し。等しさの比較には使わない）
            sig = self.__dict__["_group_signature"] = self._make_group_signature()
        return sig

    def _make_group_signature(self) -> str:
        return json.dumps(
            {g: [[i.id, {r: list(p) for r, p in sorted(i.roles.items())}] for i in insts] for g, insts in sorted(self.groups.items())},
            ensure_ascii=False,
            sort_keys=True,
        )


@dataclass
class StageState:
    """段階評価の、前の段までに決まったもの（D23 K1）。

    - inputs：run のある段が書いた入力変数（InputValue）。
    - groups：run のある段が書いたグループ。
    - exclusions：段が出した対象外。
    - values：run=None の段の、読んだ値（段の名前 → (変数, 人) → 値。YearContext.stage_value が読む）。
    - reads：run のある段の関数が読んだ判断・選択・注入の1か所と端数・読みの候補（段の名前 → {(種類, key)}。端数・読みは種類が ""）。
      evaluate が、段の出力がどの分かれ目に依存するかを決めるのに使う（2026-11-12 の4回目。値ごとの候補の評価）。
    """

    inputs: dict[tuple[str, str], InputValue] = field(default_factory=dict)
    groups: dict[str, tuple[GroupInstance, ...]] = field(default_factory=dict)
    exclusions: list[Exclusion] = field(default_factory=list)
    values: dict[str, dict[tuple[str, str], StageValue]] = field(default_factory=dict)
    reads: dict[str, set[tuple[str, str]]] = field(default_factory=dict)


def _with_default_uses(iv: InputValue | GroupInstance, reads: tuple[StageValue, ...], basis: tuple[Any, ...]) -> Any:
    """段の出力の由来の既定：uses がなければその段で読んだ値の全部（安全側）。basis に段の根拠を足す。"""
    return dataclasses.replace(iv, uses=reads if iv.uses is None else iv.uses, basis=tuple(basis) + tuple(iv.basis))


def apply_stage(
    stage: StageSpec,
    ctx: YearContext,
    values: Mapping[tuple[str, str], StageValue],
    state: StageState,
    late: Mapping[tuple[str, str], StageValue] | None = None,
    memo: dict[Any, list[Any]] | None = None,
) -> list[StageValue]:
    """段を1つ実行して state に足す。run=None の段は読んだ値を残すだけ（build_inputs が stage_value で読む）。

    段は純粋関数：同じ前の段の値と中間表現と判断なら同じ結果（evaluate は候補の組ごとに段を計算し直す）。
    late は StageSpec.late_reads の値（不動点の繰り返しで evaluate が渡す。なければ pending）。late で読んだ値を返す。

    memo を渡すと、同じ段に同じ値（values・late が同じオブジェクト）を渡し、段の関数が読んだもの（判断・選択・注入の1か所・端数と
    読みの候補・stage_value の値。_reuse と同じ条件）が同じなら、前の出力（同じオブジェクト）を使い回す（計算の速さのため。2026-11-12）。
    使い回したときは、読んだときの副作用（読んだときだけ開く1か所・端数の候補を読んだ記録）を同じ順にもう一度起こす。
    """
    if stage.run is None:
        state.values[stage.name] = dict(values)
        return []
    key = (stage.name, id(values), id(late) if late else None)
    if memo is not None:
        for entry in memo.get(key, ()):
            e_values, e_late, reads_log, stage_log, out_inputs, out_excl, out_groups, late_log = entry
            if e_values is values and (e_late is late if late else not e_late) and _same_reads(ctx, reads_log, stage_log):
                # 段の関数の stage_value は StageContext の上の読み（ctx の stage_reads を変えない）ので、判断・端数の読みだけを起こし直す
                _replay(ctx, reads_log, ())
                state.reads.setdefault(stage.name, set()).update((k, kk) for k, kk, _ in reads_log)
                state.inputs.update(out_inputs)
                state.exclusions.extend(out_excl)
                state.groups.update(out_groups)
                return list(late_log)
    sc = StageContext(ctx, stage, values, late)
    sc.read_log = []  # 段の関数が読んだ1か所（StageState.reads。値ごとの候補の評価が使う）
    if memo is not None:
        sc.stage_log = []
    out = stage.run(sc)
    state.reads.setdefault(stage.name, set()).update((k, kk) for k, kk, _ in sc.read_log)
    reads = tuple(sc.reads)
    expected = {(v, p) for v in stage.writes for p in ctx.persons}
    if set(out.inputs.values) != expected:
        missing = sorted(expected - set(out.inputs.values))[:5]
        extra = sorted(set(out.inputs.values) - expected)[:5]
        raise ValueError(f"段 {stage.name} の出力が全員分でない（足りない {missing}・余分 {extra}）")
    new_inputs: dict[tuple[str, str], InputValue] = {}
    for (var, pid), iv in out.inputs.values.items():
        check_value(var, pid, iv.value)
        new_inputs[(var, pid)] = _with_default_uses(iv, reads, stage.basis)
    state.inputs.update(new_inputs)
    state.exclusions.extend(out.inputs.exclusions)
    if set(out.groups) != set(stage.groups):
        raise ValueError(f"段 {stage.name} のグループが宣言（{sorted(stage.groups)}）と違う（{sorted(out.groups)}）")
    new_groups: dict[str, tuple[GroupInstance, ...]] = {}
    for g, insts in out.groups.items():
        new_groups[g] = tuple(_with_default_uses(i, reads, stage.basis) for i in insts)
    state.groups.update(new_groups)
    if memo is not None:
        assert sc.read_log is not None and sc.stage_log is not None
        memo.setdefault(key, []).append(
            (values, late, tuple(sc.read_log), tuple(sc.stage_log), new_inputs, tuple(out.inputs.exclusions), new_groups, tuple(sc.late_log))
        )
    return list(sc.late_log)


def check_value(var: str, pid: str, v: Any) -> None:
    if type(v) is int:
        if not 0 <= v <= INT32_MAX:
            raise ValueError(f"入力 {var} の {pid} の値が 0〜int32 の上限の外: {v}")
    elif type(v) not in (bool, str, _dt.date):
        raise TypeError(f"入力 {var} の {pid} の値の型が int・bool・str・date でない: {type(v).__name__}")


def _solo(group: str, persons: tuple[str, ...]) -> tuple[GroupInstance, ...]:
    role = SOLO_ROLE[group]
    return tuple(GroupInstance(f"{group}:{p}", {role: (p,)}) for p in persons)


def _check_groups(group: str, insts: tuple[GroupInstance, ...], persons: tuple[str, ...]) -> None:
    entity = next(e for e in ENTITIES if e.plural == group)
    roles = {r.plural: r for r in entity.roles}
    seen: list[str] = []
    ids = [i.id for i in insts]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{group} のインスタンスの ID が重複している")
    for inst in insts:
        for role, members in inst.roles.items():
            if role not in roles:
                raise ValueError(f"{group} に役割 {role} がない")
            if roles[role].max is not None and len(members) > roles[role].max:
                raise ValueError(f"{group} の {inst.id} の役割 {role} が多すぎる")
            seen += members
    if sorted(seen) != sorted(persons):
        raise ValueError(f"{group} に、生存している全員がちょうど1回ずつ入っていない")


def _reuse(memo: dict[Any, list[Any]] | None, key: Any, ctx: YearContext, fn: Any, sink: dict[Any, Any] | None = None) -> Any:
    """fn(ctx)（build_inputs・グループの組み立て：YearContext の純粋関数）を、読んだものが同じなら使い回す。

    sink を渡すと、sink[key] に読んだ判断・選択・注入の1か所と端数・読みの候補（(種類, key) の集まり。使い回したときも同じもの）を入れる
    （YearBuild の _reads。evaluate が、入力がどの分かれ目に依存するかを決めるのに使う。2026-11-12 の4回目）。

    読んだもの（YearContext.read_log）：判断・選択・注入の1か所の値と、根拠のない端数・読みの候補。段の値（stage_value。
    YearContext.stage_log）は、同じ値のオブジェクト（pending は pending どうし）を読むときだけ使い回す（2026-11-12。以前は
    stage_value を呼んだものを使い回さなかった。段の値は回の使い回しで同じオブジェクトになる）。中間表現・人・問いの時点・注入データは
    評価の単位の中で同じ。使い回したときは、読んだときの副作用（読んだときだけ開く1か所・端数の候補を読んだ記録・段の値を読んだ記録
    stage_reads）を同じ順にもう一度起こす（呼んだときと同じ結果にする）。
    """
    if memo is not None:
        for reads, stage_reads, result in memo.get(key, ()):
            if _same_reads(ctx, reads, stage_reads):
                _replay(ctx, reads, stage_reads)
                if sink is not None:
                    sink[key] = frozenset((k, kk) for k, kk, _ in reads)
                return result
    outer_log, outer_touched, outer_stage = ctx.read_log, ctx.stage_touched, ctx.stage_log
    ctx.read_log, ctx.stage_touched, ctx.stage_log = [], False, []
    outer_capture = _registry.CAPTURE[0]
    capture: tuple[list[Any], dict[int, Any]] = (ctx.read_log, {})
    _registry.CAPTURE[0] = capture
    try:
        result = fn(ctx)
        reads, stage_reads = tuple(ctx.read_log), tuple(ctx.stage_log)
    finally:
        _registry.CAPTURE[0] = outer_capture
        ctx.read_log, ctx.stage_touched, ctx.stage_log = outer_log, outer_touched or ctx.stage_touched, outer_stage
    if isinstance(result, ModuleInputs):
        # 読んだ1か所の並びと、入力・対象外を作った時点までに読んだ数（registry.CAPTURE。evaluate の候補の評価の安全側の決め方）
        result.__dict__["_causal"] = (tuple((k, kk) for k, kk, _ in reads), capture[1])
    if outer_stage is not None:
        outer_stage.extend(stage_reads)
    if memo is not None:
        memo.setdefault(key, []).append((reads, stage_reads, result))
    if sink is not None:
        sink[key] = frozenset((k, kk) for k, kk, _ in reads)
    return result


def _same_reads(ctx: YearContext, reads: Iterable[tuple[str, str, Any]], stage_reads: Iterable[tuple[str, str, str, StageValue]]) -> bool:
    """前に読んだもの（判断・選択・注入の1か所と端数・読みの候補の値、段の値のオブジェクト）が、ctx で同じか。"""
    for kind, k, v in reads:
        if (ctx._window.rounding.get(k) != v) if kind == "" else (ctx._decided.get((kind, k)) != v):
            return False
    for stage, var, person, sv in stage_reads:
        values = ctx._window.stage_values.get(stage)
        if values is None:
            if not sv.pending:
                return False
        elif sv.pending or values.get((var, person)) is not sv:
            return False
    return True


def _replay(ctx: YearContext, reads: Iterable[tuple[str, str, Any]], stage_reads: Iterable[tuple[str, str, str, StageValue]]) -> None:
    """読んだときの副作用を同じ順にもう一度起こす（読んだときだけ開く1か所・端数の候補を読んだ記録・段の値を読んだ記録）。"""
    for kind, k, _ in reads:
        if kind == "":
            ctx.rounding_candidate(k)
        else:
            ctx.decision(kind, k)
    for stage, var, person, _sv in stage_reads:
        ctx.stage_value(stage, var, person)


def build_year(
    ctx: YearContext,
    reg: Registry,
    rounding: Mapping[str, str],
    touched: Mapping[str, tuple[str, ...]],
    person_exclusions: Iterable[Exclusion] = (),
    stage: StageState | None = None,
    memo: dict[Any, list[Any]] | None = None,
) -> YearBuild:
    """候補の組1つ（ctx の判断・選択の値と、端数の候補 rounding：変数 → 候補の名前）について situation を作る。

    stage は段階評価の前の段までの結果（なければ段階を使わない）。段の変数のうち、まだ計算していない段のものは入力に書かない（OpenFisca の
    既定値になる。その変数に依存する値は、循環の検査により、その段より前の段の reads にならない）。

    memo は評価の単位の中で build_inputs・グループの組み立ての結果を使い回す表（計算の速さのため。_reuse）。memo があれば、
    モジュールごとの入力（build_inputs の結果・段の由来の付け直し・端数の候補）、モジュールの入力を合わせたものと対象外の検出、
    組み立てた YearBuild も、材料が同じオブジェクトなら使い回す（2026-11-12。同じ材料からは同じ値になる。YearBuild は変えない）。
    situation の「人物一覧」には人だけを書く（入力の値は inputs。OpenFisca には new_simulation が変数ごとの配列で入れる）。
    """
    persons = ctx.persons
    person_excl = tuple(person_exclusions)
    written = reg.stages.written_variables
    # 評価の単位の中で変わらないもの（モジュールごとの、全員分の入力のキー・端数の候補を渡す変数）と、検査した build_inputs の結果
    fixed: dict[Any, Any] = memo.setdefault(("fixed", persons), {}) if memo is not None else {}  # type: ignore[arg-type]
    checked: dict[int, Any] = memo.setdefault(("checked",), {}) if memo is not None else {}  # type: ignore[arg-type]
    cache: dict[Any, Any] = memo.setdefault(("built", persons), {}) if memo is not None else {}  # type: ignore[arg-type]
    parts: list[tuple[dict[tuple[str, str], InputValue], tuple[Exclusion, ...]]] = []
    module_parts: list[tuple[str, Mapping[tuple[str, str], InputValue], tuple[Exclusion, ...], frozenset[str], tuple[StageValue, ...], Any]] = []
    reads_sink: dict[Any, frozenset[tuple[str, str]]] = {}  # 作り手（("inputs", モジュール)・("group", モジュール, グループ)）→ 読んだ1か所
    for m in reg.modules:
        shape = fixed.get(m.name)
        if shape is None:
            shape = fixed[m.name] = (
                frozenset((v, p) for v in reg.input_variables(m) if v not in written for p in persons),
                {s.variable for s in (*m.roundings, *m.readings) if s.variable is not None},
            )
        expected, auto = shape
        mark = len(ctx.stage_reads)
        mi = None
        if m.build_inputs is not None:
            mi = _reuse(memo, ("inputs", m.name), ctx, m.build_inputs, reads_sink)
        reads = tuple(ctx.stage_reads[mark:])
        # モジュールの入力：build_inputs の結果・段の読んだ値（同じオブジェクト）・端数の候補が同じなら、前に作って検査したもの
        gkey = ("got", m.name, id(mi), tuple(map(id, reads)), tuple(rounding[var] for var in auto))
        hit = cache.get(gkey)
        if hit is not None and hit[0] is mi and len(hit[1]) == len(reads) and all(a is b for a, b in zip(hit[1], reads)):
            got = hit[2]
        else:
            got = {}
            if mi is not None:
                got.update(mi.values)
            for spec in m.stages:
                if spec.run is not None:
                    continue
                for var in spec.writes:  # build_inputs の段：読んだ値の全部を由来の既定にし、段の根拠を足す
                    for p in persons:
                        if (var, p) in got:
                            got[(var, p)] = _with_default_uses(got[(var, p)], reads, spec.basis)
            for var in auto:  # 端数の候補を渡す変数は、ここで全員に書く
                for p in persons:
                    got[(var, p)] = InputValue(rounding[var])
            if got.keys() != expected:
                missing = sorted(expected - set(got))[:5]
                extra = sorted(set(got) - expected)[:5]
                raise ValueError(f"モジュール {m.name} の入力が全員分でない（足りない {missing}・余分 {extra}）")
            if mi is not None and checked.get(id(mi)) is mi:
                # 前に検査した build_inputs の結果（使い回し）：値は同じ（段の由来の付け直しは値を変えない）。端数の候補の名前だけ検査する
                for var in auto:
                    for p in persons:
                        check_value(var, p, got[(var, p)].value)
            else:
                for (var, pid), iv in got.items():
                    check_value(var, pid, iv.value)
                if mi is not None and memo is not None:
                    checked[id(mi)] = mi  # 結果を持っておく（id を使い回されないように）
            if memo is not None:
                cache[gkey] = (mi, reads, got)  # 材料を持っておく（id を使い回されないように）
        parts.append((got, tuple(mi.exclusions) if mi is not None else ()))
        module_parts.append((m.name, got, parts[-1][1], frozenset(auto), reads, mi))
    # モジュールの入力を合わせたもの・モジュールの対象外・使わない判断の対象になった記録の入力（キーの順）
    mkey = ("merged",) + tuple(id(g) for g, _ in parts) + tuple(tuple(map(id, e)) for _, e in parts)
    merged = cache.get(mkey)
    if merged is None or any(a is not b for a, (b, _) in zip(merged[0], parts)):
        module_inputs: dict[tuple[str, str], InputValue] = {}
        module_excl: list[Exclusion] = []
        for got, excl in parts:
            module_inputs.update(got)
            module_excl += excl
        merged = (tuple(g for g, _ in parts), module_inputs, tuple(module_excl), _touched_hits(module_inputs, touched), parts)
        if memo is not None:
            cache[mkey] = merged
    module_inputs, module_excl, module_hits = merged[1], merged[2], merged[3]
    stage_inputs = stage.inputs if stage is not None else {}
    stage_excl = tuple(stage.exclusions) if stage is not None else ()
    groups: dict[str, tuple[GroupInstance, ...]] = {}
    for m in reg.modules:
        for g, builder in m.groups.items():
            groups[g] = _reuse(memo, ("group", m.name, g), ctx, lambda c, b=builder: tuple(b(c)), reads_sink)
    if stage is not None:
        groups.update(stage.groups)
    for g in SOLO_ROLE:
        if g not in groups:
            groups[g] = _solo(g, persons)
    # 同じ材料（モジュールの入力・段の出力・対象外・グループが同じオブジェクト）なら、前に組み立てた YearBuild
    bkey = (
        "build",
        id(module_inputs),
        tuple((k, id(v)) for k, v in stage_inputs.items()),
        tuple(map(id, person_excl)),
        tuple(map(id, stage_excl)),
        tuple((g, id(insts)) for g, insts in groups.items()),
    )
    built = cache.get(bkey)
    if built is not None and built[0] is module_inputs:
        return built[1]
    for g in SOLO_ROLE:
        ckey = ("checked_group", g, id(groups[g]))
        if cache.get(ckey) is not groups[g]:
            _check_groups(g, groups[g], persons)
            if memo is not None:
                cache[ckey] = groups[g]
    inputs: dict[tuple[str, str], InputValue] = {**module_inputs, **stage_inputs} if stage_inputs else module_inputs
    exclusions: list[Exclusion] = list(person_excl) + list(module_excl) + list(stage_excl)
    # 使わない判断・選択が、モジュールの使う記録を対象にしている：その記録から作った入力を対象外にする（キーの順）
    if touched:  # 対象にされた記録がなければ何もしない（速さのため）
        hits = [h for h in module_hits if h[0] not in stage_inputs] + _touched_hits(stage_inputs, touched)
        for (var, pid), hit in sorted(hits, key=lambda h: h[0]):
            exclusions.append(
                Exclusion(
                    pid,
                    OutOfScopeReason(
                        OutOfScopeCategory.NOT_IMPLEMENTED,
                        "入力の記録を対象にした判断・選択がある（その種類を使う規則モジュールがない）",
                        hit,
                    ),
                    var,
                )
            )
    situation: dict[str, Any] = {"人物一覧": {p: {} for p in persons}}
    for g, insts in groups.items():
        situation[g] = {i.id: {r: list(ps) for r, ps in i.roles.items()} for i in insts}
    out = YearBuild(situation, persons, inputs, tuple(exclusions), groups)
    # 入力の部分（モジュールごと・段の出力）：evaluate が2つの situation の入力の違いを、同じでない部分だけ比べて求める（等しさには使わない）
    out.__dict__["_input_parts"] = (tuple(g for g, _ in parts), dict(stage_inputs))
    # モジュールごとの入力・対象外・端数の候補を渡す変数・build_inputs が読んだ段の値と、作り手ごとの読んだ1か所（evaluate が、入力が
    # どの分かれ目に依存するかを決める：値ごとの候補の評価。2026-11-12 の4回目。等しさには使わない）
    out.__dict__["_modules"] = tuple(module_parts)
    out.__dict__["_reads"] = dict(reads_sink)
    if memo is not None:
        # 材料を持っておく（id を使い回されないように：段の出力・対象外・グループは out が持つ）
        cache[bkey] = (module_inputs, out)
    return out


def _touched_hits(
    inputs: Mapping[tuple[str, str], InputValue], touched: Mapping[str, tuple[str, ...]]
) -> list[tuple[tuple[str, str], tuple[str, ...]]]:
    """使わない判断・選択の対象になった記録から作った入力（キーの順）と、その判断・選択の ID（空のものは除く）。"""
    if not touched:
        return []
    out = []
    for k in sorted(k for k, iv in inputs.items() if iv.record_ids and not touched.keys().isdisjoint(iv.record_ids)):
        hit = tuple(sorted({j for rid in inputs[k].record_ids for j in touched.get(rid, ())}))
        if hit:
            out.append((k, hit))
    return out


__all__ = [
    "Decisions",
    "StageState",
    "YearBuild",
    "apply_stage",
    "build_year",
    "check_value",
    "resolve_decisions",
    "rounding_slots",
    "slot_id",
]
