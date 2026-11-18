"""中間表現（版 0）の語彙の表。`schema/ir.schema.json` はこの表から build_schema.py で作る。

語彙の出どころは `docs/hypotheses/20261109_round3_design-vocabulary.md`（以下 VOC）の
§1（事実の語彙 F-*）・§2.1（人の判断 J-*）・§2.2（納税者の選択 C-*）・§2.3（予測・見積り・計画 P-*）。
各項目の vocab に VOC の ID を書いた。VOC にない補いは vocab に「補」と書いた（README の表）。

名前の付け方（VOC §0.2）：
  - キー・事実の種類・列挙の値は英小文字の snake_case（N1）。日付は *_on、日時は *_at、識別子は *_id。
  - 人の判断・納税者の選択・予測などの種類は「判断.<名前>」「選択.<名前>」「見込み.<名前>」
    「見積り.<名前>」「計画.<名前>」（N3）。
  - 印（状態の印）の値は D22 の語「見積り」「計画」「予測」。
法令の区分（所得区分、扶養親族に当たるかなど）・基準額・率はこの表に入れない（D3・D5 改）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

SCHEMA_VERSION = "0"

Schema = Any  # dict か False

# ---------------------------------------------------------------------------
# スキーマの部品
# ---------------------------------------------------------------------------


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/$defs/{name}"}


def kind_ref(kind: str) -> dict[str, str]:
    """指定した kind の記録の id への参照（意味の検査で kind も確かめる）。"""
    return ref(f"ref_kind_{kind}")


def enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def array(item: Schema, *, min_items: int = 1) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "items": item}
    if min_items:
        schema["minItems"] = min_items
    return schema


@dataclass(frozen=True)
class Field:
    schema: Schema
    required: bool


def req(schema: Schema) -> Field:
    return Field(schema, True)


def opt(schema: Schema) -> Field:
    return Field(schema, False)


def obj(fields: Mapping[str, Field]) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object"}
    required = [name for name, f in fields.items() if f.required]
    if required:
        schema["required"] = required
    schema["additionalProperties"] = False
    schema["properties"] = {name: f.schema for name, f in fields.items()}
    return schema


BOOL: dict[str, Any] = {"type": "boolean"}
DATE = ref("date")
DATETIME = ref("datetime")
YEAR = ref("year")
YEN = ref("yen")
SYEN = ref("signed_yen")
COUNT = ref("count")
NAME = ref("name")
TEXT = ref("text")
CODE = ref("code")
ID = ref("id")
TX = ref("transaction_id")
SHA256 = ref("sha256")
MUNI = ref("municipality_code")
COUNTRY = ref("country_code")
CURRENCY = ref("currency_code")
FRACTION = ref("fraction")
RATE = ref("rate")
QUANTITY = ref("quantity")
RATIO = ref("ratio")
PERIOD = ref("period")
PERSON = ref("ref_person")
RECORD = ref("ref_record")
FACT = ref("ref_fact")
ASSET = ref("ref_asset")
CHOICE = ref("ref_choice")

#: 業務の支出の費目（business_expense.attributes.expense_category の語彙。2026-11-12 に利用者の符号から閉じた語彙にした）。
#: 支出が何に使われたかの事実の区分で、法的な意味（必要経費になるか・様式のどの科目か）は持たない（D3）。様式の科目への割当ては
#: 判定コアの様式の対応表（packages/core/src/okura_core/forms/data/r07/割当て/科目.yaml）が持つ。README §6.2。
EXPENSE_CATEGORIES: dict[str, str] = {
    "merchandise": "販売する商品の仕入",
    "materials": "製品の原材料・材料の仕入",
    "outsourcing": "外部への加工・作業の委託の対価",
    "tax": "税金（固定資産税・事業税・自動車税・印紙税など）",
    "membership_dues": "同業者団体・組合・商工会などの会費・組合費",
    "shipping": "荷造り・発送・運送の費用",
    "utilities": "電気・ガス・水道の料金",
    "travel": "旅費・交通費",
    "communication": "電話・通信・郵便の料金",
    "advertising": "広告・宣伝の費用",
    "entertainment": "接待・贈答の費用",
    "insurance": "損害保険（火災保険・自動車保険など）の保険料",
    "repairs": "修理・修繕の費用",
    "supplies": "消耗品・事務用品・少額の備品の購入",
    "welfare": "従業員の福利厚生の費用",
    "rent": "地代・家賃・駐車場代など土地・建物の賃借料",
    "loan_interest": "借入金の利子",
    "interest": "借入金以外の利子・手形の割引料",
    "fees": "支払手数料（振込手数料・仲介手数料など）",
    "management": "管理費・共益費・管理の委託料",
    "other": "上のどれにも当たらない支出",
    "dividend_debt_interest": "配当の元本を取得するための負債の利子（業務の支出でない）",
}
EXPENSE_CATEGORY = enum(*EXPENSE_CATEGORIES)

# 時の持ち方（envelope の when）
WHEN_ON = "on"
WHEN_PERIOD = "period"
WHEN_ON_OR_PERIOD = "on_or_period"
WHEN_TAX_YEAR = "tax_year"
WHEN_FISCAL_YEAR = "fiscal_year"
WHEN_DEFS = {
    WHEN_ON: "when_on",
    WHEN_PERIOD: "when_period",
    WHEN_ON_OR_PERIOD: "when_on_or_period",
    WHEN_TAX_YEAR: "when_tax_year",
    WHEN_FISCAL_YEAR: "when_fiscal_year",
}

MARK_ESTIMATE = "見積り"  # 法令が求める見積り（D21 R2。申告用の値を出す・印つき）
MARK_PLAN = "計画"  # 申告の計画（D21 R2。条件つきで出す）
MARK_FORECAST = "予測"  # 予測＝D19 の見込み（D21 R2。申告用の値を出さない）
MARKS = (MARK_ESTIMATE, MARK_PLAN, MARK_FORECAST)

# ---------------------------------------------------------------------------
# 共通の定義（$defs）
# ---------------------------------------------------------------------------

YEN_MAX = 1_000_000_000_000  # 誤入力と桁あふれを止めるための上限（法令の値ではない）

COMMON_DEFS: dict[str, Any] = {
    "id": {
        "description": "記録・人の識別子（ASCII。英数字で始まり、英数字と _ . : - で64文字まで）",
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$",
    },
    "transaction_id": {
        "description": "記録層の取引 ID（beancount の id メタデータ）。中間表現の中には取引そのものを置かないので存在は検査しない",
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$",
    },
    "code": {"description": "英小文字の短い符号", "type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
    "name": {
        "description": "名称・ラベル（制御文字なし、100文字まで）",
        "type": "string",
        "pattern": "^[^\\u0000-\\u001f\\u007f]{1,100}$",
    },
    "text": {
        "description": "説明の文（タブ・改行・復帰のほかの制御文字なし、2000文字まで）",
        "type": "string",
        "pattern": "^[^\\u0000-\\u0008\\u000b\\u000c\\u000e-\\u001f\\u007f]{1,2000}$",
    },
    "date": {"description": "日付 YYYY-MM-DD", "type": "string", "format": "date"},
    "datetime": {
        "description": "日時（秒まで・時差つき）。実在する日時かは意味の検査で確かめる",
        "type": "string",
        "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-][0-9]{2}:[0-9]{2})$",
    },
    "year": {"description": "年分・年度（西暦）", "type": "integer", "minimum": 1900, "maximum": 2100},
    "yen": {"description": "金額（整数の円、0 以上）", "type": "integer", "minimum": 0, "maximum": YEN_MAX},
    "signed_yen": {
        "description": "金額（整数の円。損失・還付など負になりうる欄）",
        "type": "integer",
        "minimum": -YEN_MAX,
        "maximum": YEN_MAX,
    },
    "count": {"description": "個数・回数・日数など", "type": "integer", "minimum": 0, "maximum": 1_000_000},
    "fraction": {
        "description": "整数の分数（外貨の額など）",
        "type": "object",
        "required": ["num", "den"],
        "additionalProperties": False,
        "properties": {
            "num": {"type": "integer", "minimum": -YEN_MAX, "maximum": YEN_MAX},
            "den": {"type": "integer", "minimum": 1, "maximum": YEN_MAX},
        },
    },
    "rate": {
        "description": "率（0 以上の整数の分数。例：年 1.5% は {num: 15, den: 1000}）",
        "type": "object",
        "required": ["num", "den"],
        "additionalProperties": False,
        "properties": {
            "num": {"type": "integer", "minimum": 0, "maximum": YEN_MAX},
            "den": {"type": "integer", "minimum": 1, "maximum": YEN_MAX},
        },
    },
    # 補（2026-11-12）：数量（鉱区の採掘予定数量・採掘数量など。単位は記録ごとに同じものを使う約束で、法令の値ではない）
    "quantity": {
        "description": "数量（0 以上の整数の分数。例：12.5 トンは {num: 125, den: 10}）",
        "type": "object",
        "required": ["num", "den"],
        "additionalProperties": False,
        "properties": {
            "num": {"type": "integer", "minimum": 0, "maximum": YEN_MAX},
            "den": {"type": "integer", "minimum": 1, "maximum": YEN_MAX},
        },
    },
    "ratio": {
        "description": "割合（0 以上 1 以下の整数の分数。num <= den は意味の検査で確かめる）",
        "type": "object",
        "required": ["num", "den"],
        "additionalProperties": False,
        "properties": {
            "num": {"type": "integer", "minimum": 0, "maximum": YEN_MAX},
            "den": {"type": "integer", "minimum": 1, "maximum": YEN_MAX},
        },
    },
    "period": {
        "description": "区間。from_on と to_on を含む。to_on がなければ続いている。from_on <= to_on は意味の検査で確かめる",
        "type": "object",
        "required": ["from_on"],
        "additionalProperties": False,
        "properties": {"from_on": DATE, "to_on": DATE},
    },
    "when_on": {
        "type": "object",
        "required": ["on"],
        "additionalProperties": False,
        "properties": {"on": DATE},
    },
    "when_period": ref("period"),
    "when_on_or_period": {"type": "object", "oneOf": [ref("when_on"), ref("when_period")]},
    "when_tax_year": {
        "description": "所得税の年分",
        "type": "object",
        "required": ["tax_year"],
        "additionalProperties": False,
        "properties": {"tax_year": YEAR},
    },
    "when_fiscal_year": {
        "description": "住民税・国保・国民年金などの年度",
        "type": "object",
        "required": ["fiscal_year"],
        "additionalProperties": False,
        "properties": {"fiscal_year": YEAR},
    },
    "sha256": {"description": "証憑の SHA-256（小文字の16進64桁）", "type": "string", "pattern": "^[0-9a-f]{64}$"},
    "municipality_code": {
        "description": "市町村（特別区・指定都市の区を含む）の6桁の団体コード。検査数字は検査しない",
        "type": "string",
        "pattern": "^[0-9]{6}$",
    },
    "country_code": {"description": "国の2文字の符号（英大文字）", "type": "string", "pattern": "^[A-Z]{2}$"},
    "currency_code": {"description": "通貨の3文字の符号（英大文字）", "type": "string", "pattern": "^[A-Z]{3}$"},
    "ref_person": {"description": "persons の id への参照", "$ref": "#/$defs/id"},
    "ref_record": {"description": "persons 以外のどれかの記録の id への参照", "$ref": "#/$defs/id"},
    "ref_fact": {"description": "facts の id への参照", "$ref": "#/$defs/id"},
    "ref_asset": {"description": "assets の id への参照", "$ref": "#/$defs/id"},
    "ref_judgment": {"description": "judgments の id への参照", "$ref": "#/$defs/id"},
    "ref_choice": {"description": "choices の id への参照", "$ref": "#/$defs/id"},
    "mark": {
        "description": "状態の印（D21 R2・D22）。見積り＝法令が求める見積り、計画＝申告の計画、予測＝見込み。なければ実際の記録",
        "type": "string",
        "enum": list(MARKS),
    },
    "source": {
        "description": "この記録の出どころ",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "transaction_ids": array(TX),
            "evidence_sha256": array(SHA256),
            "source_kind": enum("self_record", "document_copy", "external_calculation", "authority_decision"),
        },
    },
    "judge": {
        "description": "判断者。家族なら person、家族の外なら label",
        "type": "object",
        "oneOf": [
            {"type": "object", "required": ["person"], "additionalProperties": False, "properties": {"person": PERSON}},
            {"type": "object", "required": ["label"], "additionalProperties": False, "properties": {"label": NAME}},
        ],
    },
    "basis": {
        "description": "判断・選択の根拠（材料）",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "record_ids": array(RECORD),
            "transaction_ids": array(TX),
            "evidence_sha256": array(SHA256),
            "material_period": PERIOD,
            "method": TEXT,
        },
    },
    "person": {
        "description": "人（F-P01〜F-P03）。氏名・個人番号は持たない",
        "type": "object",
        "required": ["id", "birth_on"],
        "additionalProperties": False,
        "properties": {"id": ID, "birth_on": DATE, "death_on": DATE},
    },
}

# ---------------------------------------------------------------------------
# 共通の列挙
# ---------------------------------------------------------------------------

MEDICAL_KINDS = enum(
    "medical_treatment",
    "health_checkup",
    "specific_health_guidance",
    "medicine",
    "hospitalization",
    "care_service",
    "manual_therapy",
    "nursing_care",
    "midwifery",
    "suction_care",
    "transport",
    "medical_device",
    "diaper",
    "certified_other",
    "transplant_mediation",
    "welfare_levy",
    "deposit",
)  # 17。docs/hypotheses/20261109_impl-prep_iryohi-model.md H3
SECURITY_CLASS = enum("listed_stock", "listed_investment_trust", "public_bond", "unlisted_stock", "other")
ACCOUNT_TYPE = enum("withholding_specified_account", "other_account", "nisa")
# 配当等の種類（支払通知書の記載。法令の区分〔配当控除の対象か・率〕は判定コアが決める）
DIVIDEND_DISTRIBUTION_TYPE = enum(
    "surplus_dividend",  # 剰余金の配当・利益の配当・剰余金の分配・金銭の分配
    "specified_stock_investment_trust",  # 特定株式投資信託の収益の分配
    "foreign_index_linked_specified_stock_investment_trust",  # 外国株価指数連動型特定株式投資信託の収益の分配
    "securities_investment_trust",  # 証券投資信託（外貨建等証券投資信託でないもの）の収益の分配
    "foreign_currency_securities_investment_trust",  # 一般外貨建等証券投資信託の収益の分配
    "specified_foreign_currency_securities_investment_trust",  # 特定外貨建等証券投資信託の収益の分配
    "qualified_institutional_private_placement_trust",  # 適格機関投資家私募による投資信託の収益の分配
    "private_placement_bond_investment_trust",  # 私募公社債等運用投資信託等の収益の分配
    "investment_corporation",  # 投資法人から支払を受けるべき配当等
    "specific_purpose_company",  # 特定目的会社から支払を受けるべき配当等
    "specific_purpose_trust",  # 特定目的信託の収益の分配
    "fund_interest",  # 基金利息
    "foreign_corporation",  # 外国法人から受ける配当等
    "other",
)
REIMBURSEMENT_TYPE = enum(
    "hospitalization_benefit",
    "high_cost_medical_care_benefit",
    "childbirth_lump_sum",
    "mutual_aid_benefit",
    "sickness_allowance",
    "maternity_allowance",
    "sympathy_payment",
    "other",
)
NPI_EXEMPTION_TYPE = enum(
    "full", "three_quarters", "half", "one_quarter", "payment_deferral", "student_special", "perinatal"
)
DOCUMENT_TYPE = enum(
    "final_return",
    "quasi_final_return",
    "loss_return",
    "employee_dependents_declaration",
    "secondary_salary_dependents_declaration",
    "spouse_deduction_declaration",
    "basic_deduction_declaration",
    "specific_relative_deduction_declaration",
    "resident_tax_return",
    "local_tax_order_46_5_application",
    "salary_payment_report",
    "public_pension_payment_report",
)
ENTRY_SECTION = enum(
    "spouse",
    "dependent_relative",
    "specific_relative",
    "disabled_person",
    "widow_or_single_parent",
    "working_student",
    "other",
)
INCOME_TYPE = enum(
    "salary",
    "business",
    "real_estate",
    "public_pension",
    "dividend",
    "unemployment_benefit",
    "sickness_or_maternity_allowance",
    # 補（2026-11-11）：奨学金の貸与（返還を要するもの）と給付の区別（被扶養者の年間収入：rules/hifuyosha/README.md §5）
    "scholarship_loan",
    "scholarship_grant",
    "other",
    "unspecified",
)
TAX_TREATMENT = enum("tax_inclusive", "tax_exclusive")
# 補（2026-11-12 の4回目）：棚卸資産の評価の方法（所令99①一イ〜ヘ：個別法・先入先出法・総平均法・移動平均法・最終仕入原価法・売価還元法、
# 所令99の2 の承認を受けた特別な方法）と、評価の方法を選定する区分（所令100①：商品又は製品・半製品・仕掛品・主要原材料・補助原材料その他）
INVENTORY_METHOD = enum(
    "specific_identification", "fifo", "total_average", "moving_average", "final_purchase_cost", "retail", "special_approved"
)
INVENTORY_CLASS = enum("merchandise_or_products", "semi_finished", "work_in_process", "main_materials", "auxiliary_materials_and_other")
PARKING = obj(
    {
        "location": req(enum("near_workplace", "near_transit_facility", "home", "other")),  # 勤務先の周辺／駅・停留所等の周辺／自宅付近／その他
        "fee_unit": req(enum("month", "year", "per_use", "other")),  # 料金の単位（月・年・利用の都度・それ以外）
        "fee": req(YEN),  # 料金の額（per_use なら1回の料金）
        "fee_unit_multiple": opt(COUNT),  # 単位の整数倍（例：3か月単位は 3。無ければ1）
        "uses_per_month": opt(COUNT),  # per_use のときの1か月当たりの通勤の利用回数
        "fee_period_days": opt(COUNT),  # other のときの料金の算定の基礎となった期間の日数
    }
)

# ---------------------------------------------------------------------------
# 記録（relations・residences・insurance_memberships・facts・assets・filed_documents）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordKind:
    """役割つきの記録の種類。roles の値はどれも persons の id。"""

    kind: str
    vocab: str
    title: str
    roles: Mapping[str, bool]  # 役割 → 必須か
    when: str
    amounts: Mapping[str, Field] = field(default_factory=dict)
    attributes: Mapping[str, Field] = field(default_factory=dict)


# 人と人の関係（VOC §1.2）。続柄は記録せず、出来事から判定コアが導く（VOC §1.2 の注）
RELATION_KINDS: tuple[RecordKind, ...] = (
    RecordKind(
        "parentage", "F-R01", "親子関係の成立", {"parent": True, "child": True}, WHEN_ON,
        attributes={"basis": req(enum("birth_mother", "birth_in_marriage", "acknowledgment"))},
    ),
    RecordKind("adoption", "F-R02", "養子縁組・離縁", {"adoptive_parent": True, "adoptee": True}, WHEN_PERIOD),
    RecordKind(
        "marriage", "F-R03", "婚姻（届出）", {"spouse_a": True, "spouse_b": True}, WHEN_PERIOD,
        attributes={
            "ended_by": opt(enum("divorce", "death", "annulment")),
            "affinity_termination_on": opt(DATE),
            "spouse_missing": opt(
                obj(
                    {
                        "since_on": req(DATE),  # 生死が明らかでなくなった日（事故・危難の日）
                        "reason": opt(TEXT),
                        # 補（2026-11-11）：生死が明らかでない事由（所得税法施行令第11条の各号の材料。どの号に当たるかは判定コアが決める）
                        "circumstance": opt(
                            enum(
                                "former_military_not_returned",  # もとの陸海軍に属していて、まだ国内に帰らない
                                "abroad_since_war_not_returned",  # 同様の事情で国外にあって、まだ帰らない
                                "vessel_or_aircraft_accident",  # 船舶・航空機の事故
                                "peril",  # 死亡の原因となるべき危難に遭遇した
                                "other",  # それ以外（生死が明らかでない）
                            )
                        ),
                        "peril_ended_on": opt(DATE),  # 危難が去った日（peril のとき）
                    }
                )
            ),
        },
    ),
    RecordKind(
        "foster_placement", "F-R04", "里親委託・養護受託", {"caregiver": True, "placed_person": True}, WHEN_PERIOD,
        attributes={
            "placement": req(enum("foster_child", "elderly_entrustment")),
            # 補（2026-11-12）：里親の種類（児童福祉法第6条の4。養子縁組里親か：国民年金法第88条の3第2項の材料）
            "foster_parent_type": opt(enum("adoptive_foster_parent", "other")),
        },
    ),
    RecordKind("cohabitation", "F-R05", "同居（起居を共にする）", {"person": True, "other_person": True}, WHEN_PERIOD),
    RecordKind(
        "separation_reason", "F-R06", "別居の理由", {"person": True, "other_person": True}, WHEN_PERIOD,
        attributes={
            "reason": req(
                enum(
                    "member_transfer",
                    "work_related",
                    "hospitalization_or_facility",
                    "study",
                    "employment_or_independence",
                    "other",
                )
            )
        },
    ),
    RecordKind(
        "heirship", "F-R07", "相続人等", {"decedent": True, "heir": True}, WHEN_ON,
        attributes={
            "heir_type": req(enum("heir", "universal_legatee")),
            "share": opt(RATIO),
            "share_basis": opt(enum("statutory", "designated")),
            "qualified_acceptance": opt(BOOL),
            "renounced": opt(BOOL),
            "heir_departure_on": opt(DATE),
        },
    ),
)

# 各人の住所の市町村（区間つき）
RESIDENCE_KINDS: tuple[RecordKind, ...] = (
    RecordKind(
        "resident_record", "F-P06", "住民票の記録", {"person": True}, WHEN_PERIOD,
        attributes={
            "municipality_code": req(MUNI),
            "household_id": req(ID),
            "householder": req(BOOL),
            "relation_to_householder": opt(
                enum(
                    "householder",
                    "spouse",
                    "unregistered_spouse",
                    "child",
                    "parent",
                    "sibling",
                    "grandchild",
                    "grandparent",
                    "other_relative",
                    "cohabitant",
                    "other",
                )
            ),
        },
    ),
    RecordKind(
        "municipal_tax_domicile", "F-P16", "住民税を課す市町村", {"person": True}, WHEN_FISCAL_YEAR,
        attributes={
            "municipality_code": req(MUNI),
            "basis": req(enum("resident_record", "decided_different_from_resident_record", "house_or_office")),
        },
    ),
)

# 加入している保険と保険者（VOC F-P12・F-P13）
MEMBERSHIP_KINDS: tuple[RecordKind, ...] = (
    RecordKind(
        "medical_insurance", "F-P12", "医療保険の資格", {"member": True, "insured": False}, WHEN_PERIOD,
        amounts={"standard_monthly_remuneration": opt(YEN)},
        attributes={
            "scheme": req(
                enum(
                    "kyokai_kenpo",
                    "health_insurance_society",
                    "seamen_insurance",
                    "national_public_servants_mutual_aid",
                    "local_public_servants_mutual_aid",
                    "private_school_mutual_aid",
                    "national_health_insurance",
                    "late_stage_elderly_medical",
                )
            ),
            "insurer_id": req(ID),
            "branch_id": opt(ID),
            "capacity": req(enum("insured", "dependent")),
            # 補（2026-11-12）：scheme が national_health_insurance のとき、国民健康保険組合の被保険者か（偽・なしは都道府県と市町村が行う国保）
            "nhi_association": opt(BOOL),
        },
    ),
    RecordKind(
        "national_pension", "F-P13", "国民年金の被保険者の種別", {"member": True}, WHEN_PERIOD,
        attributes={"category": req(enum("first", "second", "third"))},
    ),
    RecordKind("employees_pension", "F-P13", "厚生年金保険の資格", {"member": True}, WHEN_PERIOD),
    RecordKind(
        # 補（2026-11-12）：国民年金基金の加入員の期間（国民年金法第87条の2第1項の除外・第4項の材料）
        "national_pension_fund", "補", "国民年金基金の加入員", {"member": True}, WHEN_PERIOD,
        attributes={"fund_id": opt(ID)},
    ),
    RecordKind(
        "pension_entitlement", "F-P13", "年金の受給権", {"member": True}, WHEN_PERIOD,
        attributes={
            "benefit": req(enum("old_age", "disability", "survivor")),
            # 補（2026-11-12）：workers_accident_compensation（労働者災害補償保険の年金）・corporate_pension（企業年金）を足した
            # （国民年金法施行令第6条の5第1項の列挙にない給付の材料。当たるかは判定コアが決める：rules/kokunen/README.md KN-20）
            "scheme": opt(
                enum("national_pension", "employees_pension", "mutual_aid", "workers_accident_compensation", "corporate_pension", "other")
            ),
            # 補（2026-11-12）：障害の年金の受給権者が、最後に障害等級に該当する程度の障害の状態に該当しなくなった日
            # （現に該当しない者だけが書く。国民年金法第89条第1項第1号のかっこ書きの材料）
            "disability_state_ended_on": opt(DATE),
            # 補（2026-11-12）：障害の年金の決定通知書等に記載された障害等級（1・2・3。厚生年金保険法第47条第2項の等級。
            # 国民年金法施行令第6条の5第1項第1号の「第4条の6に定める障害の状態」の材料：rules/kokunen/README.md KN-20）
            "disability_grade": opt(COUNT),
            # 補（2026-11-12）：scheme が mutual_aid の障害の年金の種類（決定通知書等の名称）。disability_employees_pension 障害厚生年金（被用者年金の一元化の後に
            # 共済組合等が支給するもの）、disability_mutual_aid_pension 障害共済年金（一元化の前の新法のもの）、old_law_disability_pension 共済組合・私学事業団が支給する
            # 障害年金（旧法のもの）。国民年金法施行令第6条の5第1項第1号（1級・2級の状態に限る）と第6号（限りなし）を分ける材料：rules/kokunen/README.md KN-20
            "mutual_aid_disability_kind": opt(
                enum("disability_employees_pension", "disability_mutual_aid_pension", "old_law_disability_pension")
            ),
        },
    ),
)

FACT_KINDS: tuple[RecordKind, ...] = (
    # --- 人の属性（VOC §1.1） ---
    RecordKind(
        "abroad_stay", "F-P04", "国外での滞在", {"person": True}, WHEN_PERIOD,
        attributes={
            "country": req(COUNTRY),
            "purpose": req(
                enum(
                    "study",
                    "assignment",
                    "accompanying_assignment",
                    "work",
                    "permanent_residence",
                    "tourism",
                    "other",
                )
            ),
            "planned_end_on": opt(DATE),
            "residence_status": opt(NAME),
        },
    ),
    RecordKind(
        "civil_status", "F-P05", "国籍・永住許可・国内の職業と資産・公務員か", {"person": True}, WHEN_PERIOD,
        attributes={
            "japanese_national": opt(BOOL),
            "permanent_residence_permit": opt(BOOL),
            "domestic_occupation": opt(BOOL),
            "domestic_assets": opt(BOOL),
            "public_servant": opt(BOOL),
            # 補（2026-11-11）：在留資格「特定活動」の活動の種類（健康保険法施行規則第37条の3 の除外の材料。当たるかは判定コアが決める）
            "designated_activity": opt(enum("medical_care_or_attendance", "sightseeing_or_recreation", "other")),
        },
    ),
    RecordKind(
        # 補（2026-11-11）：法令上の性別（戸籍の記載）。寡婦（所得税法第2条第1項第30号の「夫」）の判定などに使う。
        # 期間つき（性別の取扱いの変更の審判による変更がありうる）。続柄と同じく、法令の区分（寡婦か）は判定コアが決める
        "legal_sex", "補", "法令上の性別（戸籍の記載）", {"person": True}, WHEN_PERIOD,
        attributes={"sex": req(enum("female", "male"))},
    ),
    RecordKind(
        # 補（2026-11-11）：育児休業等の期間（夫婦共同扶養の被扶養者の異動の材料：rules/hifuyosha/README.md §5。期間は休業の期間）
        "childcare_leave", "補", "育児休業等", {"person": True}, WHEN_PERIOD,
        attributes={
            "leave_type": req(enum("childcare_leave", "postnatal_paternity_leave", "other")),
            "counterparty": opt(NAME),
            "child_ids": opt(array(PERSON)),
        },
    ),
    RecordKind(
        "dwelling_stay", "F-P07", "住居", {"person": True}, WHEN_PERIOD,
        attributes={"dwelling_id": req(ID), "building_id": opt(ID), "site_id": opt(ID)},
    ),
    RecordKind(
        "institution_stay", "F-P08", "入院・施設入所", {"person": True}, WHEN_PERIOD,
        attributes={
            "institution": req(enum("hospital", "care_facility", "other_facility")),
            "facility_type": opt(NAME),
            "for_treatment": opt(BOOL),
        },
    ),
    RecordKind(
        "enrollment", "F-P09", "在学", {"person": True}, WHEN_PERIOD,
        attributes={
            "school_type": req(
                enum(
                    "school_act_article1",
                    "specialized_training_college",
                    "miscellaneous_school",
                    "accredited_vocational_training",
                    "other",
                )
            ),
            "course": opt(NAME),
            "attendance": opt(enum("full_time", "part_time", "correspondence", "evening")),
            # 補（2026-11-11）：専修学校・各種学校・認定職業訓練の課程の材料（勤労学生：所得税法第2条第1項第32号ロ・ハ、同施行令第11条の3、
            # 同施行規則第47条の2第11項の証明書）。課程が要件に当たるかは判定コアが決める
            "course_division": opt(enum("upper_secondary", "postsecondary", "general", "other")),  # 高等課程・専門課程（専攻科を含む）・一般課程・その他
            "establisher_type": opt(enum("national", "local_government", "school_corporation", "other_corporation", "other")),
            "course_certificate": opt(BOOL),  # 課程が要件に当たる旨の大臣の証明の写し（学校の長・訓練法人の代表者から交付）を受けたか
            "establisher_certificate": opt(BOOL),  # 設置者が基準を満たす旨の大臣の証明の写しを受けたか
            "enrollment_certificate": opt(BOOL),  # 課程を履修する者である旨の学校の長・代表者の証明を受けたか
            # 補（2026-11-12）：課程の修業年限（月数。各種学校の修業年限1年以上の課程か：国民年金法施行令第6条の6第9号の材料）
            "course_length_months": opt(COUNT),
            # 補（2026-11-12）：在学する施設が日本年金機構の「学生納付特例対象校一覧」（国内大学の教育施設・外国大学の教育施設）に
            # 記載されているか（国民年金法施行令第6条の6第10号・同施行規則第77条の6 の教育施設の材料：rules/kokunen/README.md KN-17）
            "npi_student_school_listed": opt(BOOL),
        },
    ),
    RecordKind(
        "disability_basis", "F-P10", "障害の根拠", {"person": True}, WHEN_PERIOD,
        attributes={
            "basis": req(
                enum(
                    "physical_disability_certificate",
                    "mental_disability_certificate",
                    "war_injury_certificate",
                    "intellectual_disability_assessment",
                    "atomic_bomb_survivor_certification",
                    "municipal_certification",
                    "application",
                )
            ),
            "grade": opt(COUNT),
            "assessment_label": opt(NAME),
            # 補（2026-11-11）：程度の記載（特別障害者の判定：所得税法施行令第10条第2項の材料。区分は判定コアが決める）
            # 戦傷病者手帳の障害の程度（恩給法の項症・款症）
            "war_injury_class": opt(
                enum(
                    "special_item", "item_1", "item_2", "item_3", "item_4", "item_5", "item_6",
                    "clause_1", "clause_2", "clause_3", "clause_4", "clause_5",
                )
            ),
            # 市町村長等の認定・知的障害の判定の程度の記載（重度か）
            "certified_severity": opt(enum("severe", "not_severe")),
            "issuer": opt(NAME),
            "issued_on": opt(DATE),
            "valid_until": opt(DATE),
            "applied_on": opt(DATE),
            "medical_certificate": opt(BOOL),
        },
    ),
    RecordKind(
        "care_level", "F-P11", "要介護認定（税の障害者の判定には使わない）", {"person": True}, WHEN_PERIOD,
        attributes={"level": req(enum("support_1", "support_2", "care_1", "care_2", "care_3", "care_4", "care_5"))},
    ),
    RecordKind(
        "kokuho_event", "F-P14", "国保の特例と事由", {"person": True}, WHEN_ON_OR_PERIOD,
        attributes={
            "event": req(
                enum(
                    "student_special_case",
                    "institution_special_case",
                    "specified_same_household_member",
                    "involuntary_unemployment",
                    "childbirth",
                )
            ),
            "separation_category": opt(CODE),
            "separated_on": opt(DATE),
            # event の childbirth は以前の書き方（読める）。2026-11-12 から出産は共通の種類 childbirth に書く
            "expected_delivery_on": opt(DATE),
            "delivered_on": opt(DATE),
            "multiple_birth": opt(BOOL),
            # 補（2026-11-12）：student_special_case・institution_special_case で、市町村がみなした世帯（resident_record の household_id。国民健康保険法第116条）
            "deemed_household_id": opt(ID),
            # 補（2026-11-12）：institution_special_case の入院・入所・入居の種類（国民健康保険法第116条の2第1項の各号の材料。どの号に当たるかは判定コアが決める：
            # rules/kokuho/README.md KH-14）。hospital 病院・診療所への入院、child_welfare_placement 児童福祉施設への措置による入所、
            # disability_support_facility 障害者支援施設等への入所、nozomi_no_sono のぞみの園の施設への入所、elderly_home_placement 養護老人ホーム・
            # 特別養護老人ホームへの措置による入所、long_term_care_facility 特定施設への入居・介護保険施設への入所、other その他
            "admission_type": opt(
                enum(
                    "hospital",
                    "child_welfare_placement",
                    "disability_support_facility",
                    "nozomi_no_sono",
                    "elderly_home_placement",
                    "long_term_care_facility",
                    "other",
                )
            ),
        },
    ),
    RecordKind(
        # 補（2026-11-12）：出産（国保の産前産後の減額〔国保令第29条の7第6項第8号〕と国民年金の産前産後・育児期間の免除〔国民年金法第88条の2・第88条の3〕
        # が同じ記録を使う）。when.on は出産の日（まだなら出産予定日）
        "childbirth", "補", "出産・出産予定", {"person": True}, WHEN_ON,
        attributes={
            "expected_delivery_on": opt(DATE),
            "delivered_on": opt(DATE),
            "multiple_birth": opt(BOOL),
            "child_ids": opt(array(PERSON)),  # 出産に係る子
        },
    ),
    RecordKind(
        # 補（2026-11-12）：特別養子縁組の成立の請求（民法第817条の2第1項。請求をした日から家事審判事件が係属しなくなった日まで。
        # 国民年金法第88条の3第2項の材料）
        "special_adoption_petition", "補", "特別養子縁組の成立の請求", {"petitioner": True, "child": True}, WHEN_PERIOD,
    ),
    RecordKind(
        # 補（2026-11-12）：国民年金の申出（付加保険料の納付の申出〔国民年金法第87条の2第1項。期間は申出をした日から辞退の前日まで〕、
        # 法定免除の期間の保険料を納付する旨の申出〔第89条第2項。期間は申出のあった期間〕）
        "npi_application", "補", "国民年金の申出", {"person": True}, WHEN_PERIOD,
        attributes={
            "application_type": req(enum("additional_premium", "statutory_exemption_payment")),
            "applied_on": opt(DATE),
        },
    ),
    RecordKind(
        # 補（2026-11-12）：市町村の課税（非課税）証明書の記載（健保の夫婦共同扶養で一方が国保のとき、直近の証明書の所得金額で比べる：
        # 夫婦共同扶養の通知 別紙2(3)）。when.on は発行日
        "income_certificate", "補", "課税（非課税）証明書の記載", {"person": True}, WHEN_ON,
        amounts={"total_income": req(SYEN)},
        attributes={"fiscal_year": req(YEAR), "issuer": opt(NAME)},
    ),
    RecordKind(
        "public_assistance", "F-P15", "生活扶助の受給", {"person": True}, WHEN_PERIOD,
        attributes={"assistance": req(enum("livelihood_assistance"))},
    ),
    RecordKind(
        "ct_liability", "F-P17", "消費税の納税義務の状態（判定は外部）", {"person": True}, WHEN_PERIOD,
        attributes={
            "status": req(enum("exempt", "not_exempt")),
            "reason": opt(enum("invoice_registration", "election_notice", "base_period", "specified_period", "other")),
        },
    ),
    RecordKind("invoice_registration", "F-P18", "適格請求書発行事業者の登録", {"person": True}, WHEN_PERIOD),
    RecordKind(
        "dependent_allowance", "F-P19", "扶養手当の受給", {"recipient": True, "subject_person": True}, WHEN_PERIOD,
        attributes={"payer_name": opt(NAME)},
    ),
    RecordKind(
        "business_engagement", "F-P20", "事業専従者としての従事", {"business_owner": True, "relative": True},
        WHEN_PERIOD,
        attributes={
            "business_id": req(kind_ref("business")),
            "interruption_reason": opt(enum("death", "long_illness", "marriage", "other")),
            # 補（2026-11-12）：事業に従事することができた期間（長期の病気・婚姻・就職などで年を通じて従事できなかったときの、従事できた期間。
            # 所得税法施行令第165条第1項第2号の材料：rules/income_kinds/README.md IK-62）。事業の期間・死亡は business と persons から導く
            "available_period": opt(PERIOD),
            # 補（2026-11-12）：二以上の事業に従事したときの、この事業に従事した分量の割合（所令167 の材料：IK-63）。
            # 事業ごとの割合の比で配分する（合計が1でなくてもよい）。記録がなければ「明らかでない」
            "work_share": opt(RATIO),
        },
    ),
    RecordKind(
        "business", "補（F-T00・F-D11）", "業務（業務の識別子と、営んだ期間）", {"owner": True}, WHEN_PERIOD,
        attributes={"description": opt(NAME)},
    ),
    # --- 取引（VOC §1.3。役割つき・明細の粒度） ---
    RecordKind(
        "salary_payment", "F-T01", "給与の支払", {"recipient": True, "payer": False}, WHEN_ON,
        amounts={
            "gross": req(YEN),  # 総支給額（現金）。commuting_allowance は内数、commuting_pass_value は外数
            "withholding_tax": opt(YEN),
            "social_insurance_withheld": opt(YEN),
            "basic_pay": opt(YEN),
            "overtime_pay": opt(YEN),
            "commuting_allowance": opt(YEN),  # 通勤手当（gross の内数）
            "commuting_pass_value": opt(YEN),  # 現物で渡された通勤用定期乗車券の価額（gross に含めない）
            "commuting_nontaxable_stated": opt(YEN),  # 給与明細の「非課税通勤費」など、支払者が付けた区分（記載の事実）
            "bonus": opt(YEN),
            # 補（2026-11-12）：賞与の支払で、前月中に支払った通常の給与等の社会保険料等控除後の金額（所得税法第186条・別表第四の材料。
            # 前月中の通常の給与等がなければ 0 を書く：rules/tax/README.md TX-02）
            "prior_month_net_salary": opt(YEN),
            # 補（2026-11-12）：未払（unpaid）の給与のうち回収することができないこととなった金額（所得税法第64条第1項。判定は所基通64−1 で
            # 51−11〜51−16 に準ずる。回収できないこととなった日は attributes.uncollectible_on：rules/kyuyo/README.md KY-08）
            "uncollectible_amount": opt(YEN),
        },
        attributes={
            "counterparty": req(NAME),
            "payment_type": opt(
                enum("regular", "bonus", "retroactive_difference", "officer_bonus_by_resolution", "deemed_bonus")
            ),
            # 定められた支給日（契約・慣習・規程）。定めがないときは支給を受けた日（差額の追給で定めがないときは改訂の効力が
            # 生じた日）を書き、due_stipulated: false にする。D23 K3 で必須
            "due_on": req(DATE),
            "due_stipulated": opt(BOOL),
            "original_due_on": opt(DATE),  # 差額の追給（retroactive_difference）の、元の通勤手当の支給日
            "unpaid": opt(BOOL),  # 支給日が来ているが未払（when.on には支給日を書き、withholding_tax は書かない）
            "commuting_itemized": opt(BOOL),  # 通勤手当が給与明細書等で区分して表示されているか（無ければ区分されているものとする）
            "commuting_months": opt(COUNT),  # 通勤手当が対象とする月数（1か月を超える定期代などを一度に払うとき。無ければ1）
            # 補（2026-11-11）：役員の利益連動の賞与（officer_bonus_by_resolution）の収入すべき時期の材料（所基通36−9(2)：rules/kyuyo/README.md KY-01）
            "resolution_on": opt(DATE),  # 支給の決議等の日
            "amount_fixed_on": opt(DATE),  # 各人ごとの支給金額が具体的に定められた日（決議等の日と違うとき）
            # 補（2026-11-11）：支払者の区分（確定申告を要しない場合の第121条の材料：rules/tax/README.md TX-25）
            "payer_withholding_exempt_household": opt(BOOL),  # 支払者が常時2人以下の家事使用人だけに給与を支払う者（源泉徴収をしない者）か
            "paid_outside_japan": opt(BOOL),  # 国外で支払われた給与か（源泉徴収されない）
            "payer_family_company_officer": opt(BOOL),  # 支払者が同族会社で、受給者がその役員又はその親族等か
            "interest_or_rent_from_payer": opt(BOOL),  # その年に受給者がその支払者から貸付金の利子・不動産の賃貸料などの支払を受けたか
            # 補（2026-11-12）：支払者が家族（役割 payer）のときの、支払者の業務（所得税法第56条・第57条の受取側の材料：
            # rules/income_kinds/README.md IK-32・57〜61）。支払者の側の記録は payroll_paid（employer＝payer、recipient＝受給者）
            "payer_business_id": opt(kind_ref("business")),
            # 補（2026-11-12）：国際慣例により源泉徴収をする義務がないものとされる在日大公使館・在日外交官からの給与か
            # （所基通121−5(2)：rules/tax/README.md TX-25）
            "paid_by_foreign_mission": opt(BOOL),
            # 補（2026-11-12）：給与の支給期の区分（所得税法第185条第1項各号のイ〜ヘ：毎月・毎半月・毎旬・月の整数倍の期間ごと・
            # 毎日・その他）と、月の整数倍の月数・その他の支給日数（別表第二・第三の当て方の材料：rules/tax/README.md TX-02）
            "pay_period": opt(enum("monthly", "semimonthly", "ten_days", "multiple_months", "daily", "other")),
            "pay_period_months": opt(COUNT),  # multiple_months の月数
            "pay_period_days": opt(COUNT),  # other の支給日数
            "uncollectible_on": opt(DATE),  # 補（2026-11-12）：amounts.uncollectible_amount を回収することができないこととなった日
        },
    ),
    RecordKind(
        "commuting_status", "補（tsukin HT3）", "通勤の状況（支払者・期間ごとの交通手段・片道の距離・駐車場等）", {"worker": True},
        WHEN_PERIOD,
        attributes={
            "counterparty": req(NAME),
            "means": req(enum("transit", "vehicle", "transit_and_vehicle")),  # 交通機関・有料道路／交通用具／併用
            "one_way_km": opt(FRACTION),  # 交通用具の片道の距離（km。通勤経路に沿った長さ）
            "parkings": opt(array(PARKING)),  # 駐車場等（二以上なら全部）
        },
    ),
    RecordKind(
        # 補（2026-11-12）：給与所得者の特定支出の候補となる支出（所得税法第57条の2：rules/kyuyo/README.md KY-11。on は支出した日）。
        # 1件＝1つの支出（明細書の1行）。法令の区分・上限・除く部分は判定コアが決める。amount は実際の支出金額（明細書のⒶ）。
        # 2026-11-12 の2回目（kyuyo KY-13）：最も経済的かつ合理的な通常の経路・方法による部分（旅費・帰宅旅費）、通常必要な運賃・
        # 著しく超えない宿泊費（転居費）は人の判断として 判断.特定支出の通常の範囲の額 に持つ（以前は amount に政令の範囲の額を書く約束だった：
        # docs/hypotheses/20261112_impl-research8_tokutei-shishutsu-reading.md H5・H9）
        "specific_expense", "補（kyuyo KY-11）", "給与所得者の特定支出の候補となる支出（on は支出した日）", {"payer": True}, WHEN_ON,
        amounts={
            "amount": req(YEN),
            # 給与等の支払者により補塡される部分のうち所得税が課されない部分（確定していなければ見込額）
            "reimbursed_nontaxable": opt(YEN),
            # 雇用保険法の教育訓練給付金・母子家庭・父子家庭自立支援教育訓練給付金が支給される部分
            "training_benefit": opt(YEN),
            # amount の内数：特別車両料金・特別船室料金・航空機の上位の座席の料金など、客室の特別の設備の利用についての料金（寝台料金を除く）
            "special_seat_fee": opt(YEN),
            # 通勤（交通機関）：この支出の対象の月の、給与等の支払者が証明した経路・方法による1か月当たりの定期乗車券・定期乗船券の価額の合計
            # （特別車両料金等の部分を除く）
            "commuter_pass_value": opt(YEN),
        },
        attributes={
            "category": req(
                enum(
                    "commuting_transit",  # 通勤：交通機関の利用
                    "commuting_vehicle",  # 通勤：自動車その他の交通用具の使用（燃料費・有料道路・修理）
                    "business_travel",  # 勤務する場所を離れて職務を遂行するための旅行
                    "relocation",  # 転任に伴う転居
                    "training",  # 研修（資格を取得するためのものを除く）
                    "qualification",  # 資格の取得
                    "home_leave",  # 単身赴任などの帰宅の旅行
                    "books",  # 図書
                    "clothing",  # 勤務場所で着用する衣服
                    "entertainment",  # 職務上関係のある者への接待・供応・贈答など
                )
            ),
            # 証明をした者（給与等の支払者・キャリアコンサルタント・証明なし）
            "certified_by": req(enum("payer", "career_consultant", "none")),
            # キャリアコンサルタントの証明のとき、この支出が雇用保険法第60条の2第1項の教育訓練に係るものか
            "education_training": opt(BOOL),
            "air_travel": opt(BOOL),  # 航空機の利用に係る支出か
            "sleeper_fees": opt(array(YEN)),  # amount の内数：寝台料金（1回の利用ごとの額）
            "transfer_on": opt(DATE),  # 転居・帰宅旅行：転任の事実が生じた日
            # 転居費（category: relocation）の支出の別（所得税法施行令第167条の3第3項第1号〜第4号：旅行の運賃及び料金・自動車の燃料費及び有料の道路の料金・
            # 宿泊費・家具その他の資産の運送の費用）。2026-11-12 の2回目（kyuyo KY-13）：燃料費・運送の費用は通常の範囲の判断が要らない
            "relocation_item": opt(enum("fare", "vehicle", "lodging", "moving")),
            # 特定支出の額に数える年分（年をまたがる定期乗車券・授業料などを年ごとに分けて記録したとき。無ければ when.on の年）
            "attributed_year": opt(YEAR),
            "payer_name": opt(NAME),  # 給与等の支払者
            "counterparty": opt(NAME),
            "description": opt(TEXT),
        },
    ),
    RecordKind(
        "business_receipt", "F-T02", "業務の売上・報酬の受取", {"recipient": True}, WHEN_ON,
        amounts={"amount": req(YEN), "withholding_tax": opt(YEN)},
        attributes={
            "business_id": req(kind_ref("business")),
            "counterparty": opt(NAME),
            "contract_document": opt(
                enum("employment_contract", "labor_conditions_notice", "service_contract", "none", "other")
            ),
            "incurred_on": opt(DATE),
        },
    ),
    RecordKind(
        "business_expense", "F-T03", "業務の支出・家事関連費の支出（全額で記録する）", {"payer": True, "payee": False},
        WHEN_ON,
        amounts={"amount": req(YEN), "consumption_tax": opt(YEN)},
        attributes={
            "business_id": opt(kind_ref("business")),
            "expense_category": req(EXPENSE_CATEGORY),  # 2026-11-12：EXPENSE_CATEGORIES の閉じた語彙（前は利用者の符号 CODE）
            "counterparty": opt(NAME),
            "counterparty_invoice_registered": opt(BOOL),
            "incurred_on": opt(DATE),
            # 補（2026-11-12）：支出の結びつき（rules/income_kinds/README.md IK-36・37・69・70・89）。
            # 家族への支払なら受け取った側の記録（rent_flow・business_receipt）、家族から対価を受けた側の支出ならその対価の売上（business_receipt）、
            # 物件ごとの支出なら賃貸物件、借入金の利子ならその借入れ
            "rent_flow_id": opt(kind_ref("rent_flow")),
            "receipt_id": opt(kind_ref("business_receipt")),
            "property_id": opt(kind_ref("rental_property")),
            "loan_id": opt(kind_ref("loan")),
        },
    ),
    RecordKind(
        "payroll_paid", "F-T04", "支払う側の給与・報酬と源泉徴収", {"employer": True, "recipient": False}, WHEN_ON,
        amounts={"amount": req(YEN), "withholding_tax": opt(YEN)},
        attributes={
            "business_id": opt(kind_ref("business")),
            "pay_type": req(enum("wages", "family_employee_salary", "professional_fee")),
            "counterparty": opt(NAME),
            # 補（2026-11-12）：家族への報酬（professional_fee）を受け取った側の売上の記録（所法56 の受取側：IK-32）
            "receipt_id": opt(kind_ref("business_receipt")),
        },
    ),
    RecordKind(
        "medical_payment", "F-T05", "医療費の支払（on は支払った日）", {"payer": True, "patient": True}, WHEN_ON,
        amounts={"amount": req(YEN)},
        attributes={
            "incurred_on": req(DATE),
            "provider": opt(NAME),
            "medical_kinds": req(array(MEDICAL_KINDS)),
            "selfmed_label": opt(enum("present", "absent", "unknown")),
            "product_name": opt(NAME),
            "deposit_applied_on": opt(DATE),
            "payment_instrument": opt(NAME),
            # 補（2026-11-12）：この支払が医療費通知（medical_expense_notice）に記載された医療費の支払なら、その通知の記録。
            # 書いた支払は医療費控除の明細書の「2 明細」から除き、通知の paid_in_year（㋐）で数える（二重計上を防ぐ約束。
            # 通知に載った支払は medical_payment に書かないか、書くならこの欄を書く。手引き「❶に記入したものについては、記入しないでください」）。
            # 支払者・受診者・支払った年（when.on の年）は通知の記録と同じであること（違えば判定コアが入力の矛盾として返す）
            "notice_id": opt(kind_ref("medical_expense_notice")),
        },
    ),
    RecordKind(
        # 補（2026-11-12）：医療費通知（医療保険者等が発行する医療費の額等を通知する書類。所得税法第120条第4項第2号・所得税法施行規則
        # 第47条の2第13項。医療費控除の明細書の「1 医療費通知に記載された事項」の材料）。1件＝1つの通知の、1人の受診者（療養を受けた者）の
        # 1つの年分（paid_in_year を実際に支払った年 payment_year）の分。when は通知の対象の期間（療養を受けた年月の最初の日〜最後の日）。
        # notice_amount＝通知に記載された医療費の額（自己負担額。前年支払分を含みうる）、paid_in_year＝そのうち payment_year 中に実際に支払った額（㋐）、
        # reimbursed＝そのうち生命保険や社会保険などで補塡される金額（㋑。見込額を含む。なければ0）。issuer＝保険者等の名称。
        # 同じ支払を medical_payment にも書くときは、その支払の attributes.notice_id にこの記録の id を書く（書かなければ二重に数える）
        "medical_expense_notice", "補", "医療費通知に記載された医療費（受診者・年分ごと）", {"payer": True, "patient": True}, WHEN_PERIOD,
        amounts={"notice_amount": req(YEN), "paid_in_year": req(YEN), "reimbursed": opt(YEN)},
        attributes={"payment_year": req(YEAR), "issuer": req(NAME)},
    ),
    RecordKind(
        "reimbursement", "F-T06", "補塡の給付の受取（見込額は 見積り.補塡の見込額 で持つ）", {"recipient": True},
        WHEN_ON,
        amounts={"amount": req(YEN)},
        attributes={
            "benefit_type": req(REIMBURSEMENT_TYPE),
            "target_payment_ids": opt(array(kind_ref("medical_payment"))),
            "payer_name": opt(NAME),
        },
    ),
    RecordKind(
        "social_insurance_payment", "F-T07", "社会保険料の支払", {"payer": True, "liable_person": True}, WHEN_ON,
        amounts={"amount": req(YEN)},
        attributes={
            "premium_type": req(
                enum(
                    "national_health_insurance",
                    "national_pension",
                    "health_insurance",
                    "employees_pension",
                    "long_term_care_insurance",
                    "late_stage_elderly_medical",
                    "employment_insurance",
                    "national_pension_fund",
                    "other",
                )
            ),
            "prepaid_period": opt(PERIOD),
            # 補（2026-11-12）：前納した保険料の納付期日の全部（所基通74・75−1(2) の「その年中に到来する納付期日の回数÷納付期日の総回数」の材料）
            "prepaid_due_dates": opt(array(DATE)),
            "payroll_deduction": opt(BOOL),
        },
    ),
    RecordKind(
        "mutual_aid_payment", "F-T08", "小規模企業共済等掛金の支払", {"payer": True, "member": True}, WHEN_ON,
        amounts={"amount": req(YEN)},
        attributes={
            "contribution_type": req(
                enum(
                    "small_business_mutual_aid",
                    "individual_defined_contribution",
                    "corporate_defined_contribution_member",
                    "disability_mutual_aid",
                )
            ),
            "payroll_deduction": opt(BOOL),
        },
    ),
    RecordKind(
        "insurance_payment", "F-T09", "保険料の支払と剰余金", {"payer": True}, WHEN_ON,
        amounts={"amount": req(YEN)},
        attributes={
            "contract_id": req(kind_ref("insurance_contract")),
            "flow": req(enum("premium", "dividend", "rebate")),
            "prepaid": opt(BOOL),
            # 補（2026-11-12）：前納した保険料の払込期日の全部（所基通76−3(3)・77−7 の「その年中に到来する払込期日の回数÷払込期日の総回数」の材料）
            "prepaid_due_dates": opt(array(DATE)),
            "automatic_premium_loan": opt(BOOL),
            "applied_to_premium": opt(BOOL),
        },
    ),
    RecordKind(
        "donation", "F-T10", "寄附の支出と返礼品", {"donor": True}, WHEN_ON,
        amounts={"amount": req(YEN), "return_gift_value": opt(YEN)},
        attributes={
            "recipient_name": req(NAME),
            "recipient_type": opt(
                enum(
                    "local_government",
                    "national_government",
                    "political_party",
                    "certified_npo",
                    "public_interest_corporation",
                    "school_corporation",
                    "community_chest",  # 補（2026-11-11）：共同募金会（住民税の第314条の7第1項第2号）
                    "japanese_red_cross",  # 補（2026-11-11）：日本赤十字社（同号）
                    "other",
                )
            ),
            "receipt_issued": opt(BOOL),
            "return_gift": opt(BOOL),
            "admission_related_facts": opt(TEXT),
            "candidate_to_specified_party_branch": opt(BOOL),
            # 補（2026-11-12）：受領証等に記載された旨（所規47の2③）。指定寄附金である旨・特定公益増進法人の主たる目的である業務に
            # 関連する寄附金である旨・公益信託の信託事務に関連する寄附金である旨・記載なし。どの号に当たるかは判定コアが決める
            "receipt_statement": opt(
                enum("designated_donation", "specified_public_interest_business", "public_interest_trust", "none")
            ),
            # 補（2026-11-11）：寄附先の地方公共団体（recipient_type が local_government のとき。住民税の特例控除対象寄附金の指定の注入データを引く）
            "recipient_local_government_code": opt(MUNI),
            "recipient_local_government_kind": opt(enum("prefecture", "municipality")),
            # 補（2026-11-12）：寄附を受けた事務所（共同募金会は主たる事務所、日本赤十字社は寄附を収納した支部）の所在の都道府県の団体コード
            # （住民税の第314条の7第1項第2号の「住所の道府県内」の材料：rules/juminzei/README.md JM-08）
            "recipient_office_prefecture_code": opt(MUNI),
            # 補（2026-11-12）：共同募金会・日本赤十字社が、この寄附金の募集に当たり総務大臣の承認を受けたか（受領証等・募集の案内の記載。
            # 地方税法施行令第48条の8・第7条の17第1号・第3号の材料：rules/juminzei/README.md JM-08）
            "mic_approved_solicitation": opt(BOOL),
            # 補（2026-11-12）：この寄附先への申告特例の求め（申告特例申請書。変更の届出をしたときはその届出書）に記載した住所の市町村の団体コード
            # （附則第7条第13項第4号の材料：rules/juminzei/README.md JM-21）
            "onestop_request_municipality_code": opt(MUNI),
        },
    ),
    RecordKind(
        "casualty", "F-T11", "雑損の事象（on は発生日）", {"owner": True}, WHEN_ON,
        amounts={
            "insurance_recovery": opt(YEN),
            "pre_loss_value": opt(YEN),
            "post_loss_value": opt(YEN),
            "acquisition_cost": opt(YEN),
            # 補（2026-11-12）：損失の基因となった事実の発生直後の発生資材の価額（業務用の資産の損失の金額：所基通51−2。IK-72）
            "salvage_value": opt(YEN),
        },
        attributes={
            "cause": req(
                enum("earthquake", "fire", "storm_or_flood", "other_natural_disaster", "theft", "embezzlement", "other")
            ),
            "asset_description": opt(NAME),
            "asset_id": opt(ASSET),
            "business_use": opt(BOOL),
            "asset_acquired_on": opt(DATE),
            "disaster_ended_on": opt(DATE),  # 補（2026-11-11）：災害のやんだ日（災害等関連支出の期間：所令206①二、所基通72−6）
        },
    ),
    RecordKind(
        "casualty_expenditure", "F-T11", "災害等関連支出", {"payer": True}, WHEN_ON,
        amounts={"amount": req(YEN)},
        attributes={
            "casualty_id": req(kind_ref("casualty")),
            "expenditure_type": req(enum("removal", "restoration", "prevention", "other")),
        },
    ),
    RecordKind(
        "pension_payment", "F-T12", "年金の支払", {"recipient": True}, WHEN_ON,
        amounts={"gross": req(YEN), "social_insurance_withheld": opt(YEN), "withholding_tax": opt(YEN)},
        attributes={
            "counterparty": opt(NAME),
            "payer_domestic": opt(BOOL),
            "scheme": req(
                enum(
                    "national_pension",
                    "employees_pension",
                    "mutual_aid_pension",
                    "corporate_pension",
                    "foreign_pension",
                    "private_annuity",
                    "other",
                )
            ),
            "benefit_reason": req(enum("old_age", "disability", "survivor", "other")),
            "benefit_name": opt(NAME),
            "statutory_payment_on": opt(DATE),
            "covered_period": opt(PERIOD),
        },
    ),
    RecordKind(
        "retirement_payment", "F-T13", "退職手当等の支払", {"recipient": True}, WHEN_ON,
        amounts={
            "gross": req(YEN),
            "withholding_tax": opt(YEN),
            "employee_contributions": opt(YEN),
            # 補（2026-11-12）：役員等勤続期間以外の期間を基礎として、他の使用人に対する退職給与の支給の水準等を勘案して支払者が相当と
            # 認めた額（所令71の2⑬二の一般退職手当等・短期退職手当等の部分。rules/income_kinds/README.md IK-24）
            "non_officer_portion": opt(YEN),
        },
        attributes={
            "counterparty": opt(NAME),
            "retired_on": opt(DATE),
            "resolution_on": opt(DATE),
            "benefit_event_on": opt(DATE),
            "payment_category": opt(CODE),
            # 補（2026-11-12）：確定拠出年金法の老齢給付金として支給される一時金か（所令72③七。所令70①二ロ・ハの前の退職手当等の範囲の材料。
            # payment_category は自由な符号のままにし、法令の判定に要る区別はこの欄で受ける。IK-21）
            "old_age_dc_lump_sum": opt(BOOL),
        },
    ),
    RecordKind(
        "dividend", "F-T14", "配当等の受取", {"recipient": True}, WHEN_ON,
        amounts={"gross": req(YEN), "withholding_tax": opt(YEN), "dividend_local_tax": opt(YEN)},
        attributes={
            "counterparty": opt(NAME),
            "security_class": req(SECURITY_CLASS),
            "account_type": req(ACCOUNT_TYPE),
            "record_date": opt(DATE),
            # 補（2026-11-12）：配当計算期間（支払通知書の記載。措法8の5①一・③の少額配当の月数の材料。IK-87）
            "calculation_period": opt(PERIOD),
            # 補（2026-11-11）：支払通知書の配当等の種類（配当控除の対象の区分と率を判定コアが決める材料。
            # docs/public-sources/20261111_impl-research_haito-laws-and-nta.md §2・§3）。なければ判定コアは区分を決められない
            "distribution_type": opt(DIVIDEND_DISTRIBUTION_TYPE),
        },
    ),
    RecordKind(
        "security_sale", "F-T15", "一般口座などの譲渡（on は譲渡日）", {"seller": True}, WHEN_ON,
        amounts={"proceeds": req(YEN), "acquisition_cost": opt(YEN), "selling_expenses": opt(YEN)},
        attributes={
            "security_name": opt(NAME),
            "security_class": req(SECURITY_CLASS),
            "sale_method": opt(enum("brokered", "private")),
            "account_type": opt(ACCOUNT_TYPE),
        },
    ),
    RecordKind(
        "remittance", "F-T16", "送金（on は送金日）", {"sender": True, "recipient": True}, WHEN_ON,
        amounts={"amount": req(YEN), "fee": opt(YEN)},
        attributes={
            "method": req(enum("bank_transfer", "card", "electronic_payment", "cash", "in_kind")),
            "used_on": opt(DATE),
            "transferred_on": opt(DATE),
            "foreign_amount": opt(obj({"currency": req(CURRENCY), "value": req(FRACTION)})),
            "exchange_rate": opt(RATE),
            "purpose": opt(enum("living_expenses", "tuition", "medical_expenses", "other")),
            "beneficiaries": opt(array(PERSON)),
        },
    ),
    RecordKind(
        "windfall_receipt", "F-T17", "一時所得の材料になる受取", {"recipient": True}, WHEN_ON,
        amounts={"amount": req(YEN)},
        attributes={
            "counterparty": opt(NAME),
            "reason": req(enum("prize", "insurance_maturity", "gift", "other")),
            # 補（2026-11-12）：贈与者が法人か個人か（所基通34−1(5)：法人からの贈与は一時所得、個人からの贈与は贈与税。IK-11）
            "donor_type": opt(enum("corporation", "individual")),
            "business_related": opt(BOOL),
            "direct_expense_ids": opt(array(FACT)),
        },
    ),
    RecordKind(
        "benefit_receipt", "F-T18", "給付・その他の受取", {"recipient": True}, WHEN_ON_OR_PERIOD,
        amounts={"amount": req(YEN), "daily_amount": opt(YEN)},
        attributes={
            "benefit_type": req(
                enum(
                    "unemployment_benefit",
                    "sickness_allowance",
                    "maternity_allowance",
                    "scholarship_grant",
                    "scholarship_loan",
                    # 補（2026-11-12。IK-99）：死亡した年金の受給者の未支給の年金を遺族として受けたもの・労働者災害補償保険の給付
                    "unpaid_pension_of_deceased",
                    "workers_accident_compensation",
                    "other",
                )
            ),
            "benefit_start_on": opt(DATE),
            # 補（2026-11-12）：未支給年金の元の年金の支給の事由（老齢・障害・遺族）
            "unpaid_pension_reason": opt(enum("old_age", "disability", "survivor")),
        },
    ),
    RecordKind(
        "rent_flow", "F-T19", "賃料・敷金・家族の間の対価", {"recipient": True, "payer": False}, WHEN_ON,
        amounts={"amount": req(YEN)},
        attributes={
            "flow_type": req(
                enum(
                    "rent",
                    "common_service_fee",
                    "deposit_received",
                    "deposit_returned",
                    "key_money",
                    "renewal_fee",
                    "other",
                )
            ),
            "lease_id": opt(kind_ref("lease")),
            "property_id": opt(kind_ref("rental_property")),
            "counterparty": opt(NAME),
            "covered_period": opt(PERIOD),
        },
    ),
    # --- 書類・届出・処分（VOC §1.4。提出した申告書等は filed_documents） ---
    RecordKind(
        "prior_income_fixed", "F-D03", "前々年分などの業務の収入金額（確定値）", {"person": True}, WHEN_TAX_YEAR,
        amounts={"revenue": req(YEN)},
        attributes={
            "business_id": opt(kind_ref("business")),
            "income_source": req(enum("business", "real_estate", "miscellaneous_business")),
            "fixed_by": opt(NAME),
            "fixed_on": opt(DATE),
        },
    ),
    RecordKind(
        "withholding_slip", "F-D04", "源泉徴収票・支払調書の記載", {"recipient": True}, WHEN_TAX_YEAR,
        amounts={
            "payment_amount": req(YEN),
            "withholding_tax": opt(YEN),
            "social_insurance": opt(YEN),
            "special_collection_tax": opt(YEN),
            # 補（2026-11-12）：給与所得の源泉徴収票の「住宅借入金等特別控除の額」（年末調整で控除された額。記載がなければ 0 を書く：
            # rules/tax/README.md TX-20）
            "housing_loan_credit": opt(YEN),
        },
        attributes={
            "slip_type": req(enum("salary", "retirement", "public_pension", "payment_record")),
            "counterparty": opt(NAME),
            "year_end_adjusted": opt(BOOL),
            "secondary_column": opt(BOOL),
            "listed_person_ids": opt(array(PERSON)),
            # 給与の源泉徴収票で、就職前に他の支払者が支払った給与等を通算して年末調整した場合の、その支払者の名称
            # （「支払金額」の内書き。手引「支払金額」欄）
            "includes_prior_payers": opt(array(NAME)),
            "hired_on": opt(DATE),
            "retired_on": opt(DATE),
            "service_years": opt(COUNT),
        },
    ),
    RecordKind(
        "prepayment_notice", "F-D05", "予定納税の通知", {"taxpayer": True}, WHEN_TAX_YEAR,
        amounts={"prepayment_total": req(YEN), "first_installment": opt(YEN), "second_installment": opt(YEN)},
    ),
    RecordKind(
        "labor_contract", "F-D06", "労働契約の内容と申立て", {"worker": True}, WHEN_PERIOD,
        amounts={
            "hourly_wage": opt(YEN),
            "daily_wage": opt(YEN),  # 補（2026-11-11）
            "monthly_wage": opt(YEN),
            "monthly_allowances": opt(YEN),
            "monthly_commuting_allowance": opt(YEN),  # 補（2026-11-11）：通勤手当の月額（契約に金額の記載があるとき）
            "bonus": opt(YEN),
        },
        attributes={
            "counterparty": opt(NAME),
            "scheduled_minutes_per_week": opt(COUNT),
            "scheduled_days_per_week": opt(COUNT),
            "shift_based": opt(BOOL),
            "labor_conditions_notice": opt(BOOL),
            "salary_income_only_statement": opt(BOOL),
            # 補（2026-11-11）：労働契約による被扶養者の判定の材料（「通勤手当有」「賞与有」だけで金額がない記載、実費弁償の形の記載）
            "commuting_allowance_stated": opt(BOOL),
            "commuting_allowance_as_reimbursement": opt(BOOL),
            "bonus_stated": opt(BOOL),
            "fixed_term": opt(BOOL),
        },
    ),
    RecordKind(
        "employer_attestation", "F-D07", "事業主の証明・確認", {"person": True}, WHEN_ON,
        attributes={
            "attestation_type": req(enum("temporary_income_increase", "income_tax_dependent_confirmation")),
            "covered_period": opt(PERIOD),
            "counterparty": opt(NAME),
        },
    ),
    RecordKind(
        "insurer_decision", "F-D08", "保険者の決定・届出", {"dependent": True, "insured": True}, WHEN_ON,
        attributes={
            "decision": req(enum("notification_filed", "recognized", "removed", "rejected")),
            "effective_on": opt(DATE),
            "sent_on": opt(DATE),
            "insurer_id": opt(ID),
            "reason": opt(TEXT),
            "joint_support_agreement": opt(BOOL),
            "recognized_under_higher_income_criterion": opt(BOOL),
        },
    ),
    RecordKind(
        "npi_exemption", "F-D09", "国民年金の免除等の申請と承認", {"person": True}, WHEN_PERIOD,
        attributes={
            "exemption_type": req(NPI_EXEMPTION_TYPE),
            "status": req(enum("applied", "approved", "rejected")),
            "applied_on": opt(DATE),
            "decided_on": opt(DATE),  # 補（2026-11-11）：承認・却下の日
        },
    ),
    RecordKind(
        "foreign_kin_document", "F-D10", "国外居住親族の書類（on は発行日）",
        {"subject_person": True, "holder": True}, WHEN_ON,
        attributes={
            "document_type": req(
                enum("kinship_document", "student_visa_document", "remittance_document", "remittance_document_special")
            ),
            "issuer": opt(NAME),
            "translation_attached": opt(BOOL),
            "presented_to": opt(NAME),
            "presented_on": opt(DATE),
            "presented_with": opt(NAME),
        },
    ),
    RecordKind(
        "blue_return_procedure", "F-D11", "青色申告の手続（on は提出・通知の日）", {"person": True}, WHEN_ON,
        attributes={
            "procedure": req(
                enum(
                    "application_filed",
                    "approval_notice",
                    "rejection_notice",
                    "revocation_notice",
                    "withdrawal_notice",
                    "business_transfer_or_closure",
                )
            ),
            "first_tax_year": opt(YEAR),
            "business_start_on": opt(DATE),
            "succession_by_inheritance": opt(BOOL),
            # 補（2026-11-12）：相続で承継した業務の被相続人が青色申告の承認を受けていたか（所基通144−1 の期限の材料：IK-74）
            "decedent_blue_approved": opt(BOOL),
            "revoked_from_tax_year": opt(YEAR),
            "statutory_ground": opt(CODE),
        },
    ),
    RecordKind(
        "bookkeeping_status", "F-D12", "帳簿と届出の状態", {"person": True}, WHEN_TAX_YEAR,
        attributes={
            "business_id": opt(kind_ref("business")),
            "bookkeeping_method": req(enum("double_entry", "simplified", "cash_basis_simplified")),
            "inventory_list": opt(BOOL),
            "balance_sheet": opt(BOOL),
            "electronic_books_notice": opt(enum("none", "filed", "withdrawn")),
            "cash_basis_notice": opt(BOOL),
            "misc_cash_basis_entry": opt(BOOL),
            "depreciation_method_notice": opt(NAME),
            # 補（2026-11-12）：仕訳帳・総勘定元帳が優良な電子帳簿の要件（電子帳簿保存法施行規則第5条第5項）を満たし、
            # 最初の記録段階から電磁的記録で備え付け・保存しているか（措法25の2④一・措規9の6 の材料：IK-78）
            "electronic_books_qualified": opt(BOOL),
        },
    ),
    RecordKind(
        "family_employee_notice", "F-D13", "専従者の届出（on は提出日）", {"employer": True, "employee": True}, WHEN_ON,
        amounts={"monthly_salary": opt(YEN)},
        attributes={
            "notice_type": req(enum("initial", "change")),
            "duties": opt(TEXT),
            "pay_schedule": opt(TEXT),
            "bonus_criteria": opt(TEXT),
            "started_on": opt(DATE),
        },
    ),
    RecordKind(
        "health_checkup_record", "F-D14", "セルフメディケーションの取組", {"person": True}, WHEN_ON,
        attributes={
            "activity": req(
                enum(
                    "specific_health_checkup",
                    "vaccination",
                    "periodic_health_checkup",
                    "health_examination",
                    "cancer_screening",
                    "other",
                )
            ),
            "provider": opt(NAME),
            "certificate_available": opt(BOOL),
        },
    ),
    RecordKind(
        "retirement_record", "F-D16", "退職の申告書と勤務期間（期間は就職日〜退職日）", {"recipient": True},
        WHEN_PERIOD,
        attributes={
            "counterparty": opt(NAME),
            "declaration_submitted": req(BOOL),
            "officer_period": opt(PERIOD),
            "interruption_note": opt(TEXT),
            "prior_service_note": opt(TEXT),
            # 補（2026-11-12）：勤続期間の加算・除外（所令69①一イ〜ハ・70①一。IK-23）。when は退職の日まで引き続き勤務した期間。
            #   earlier_service_same_payer：一時勤務しなかった期間の前に同じ支払者の下で引き続き勤務した期間（イ：加算）
            #   other_employer_service：支払者が支払金額の計算の基礎に含める、他の者の下で勤務した期間（ロ：加算）
            #   prior_allowance_basis：同じ支払者から前に受けた退職手当等の支払金額の計算の基礎とされた期間（ハ：末日以前を除く。
            #     支払者が今回の計算の基礎に含めるなら included_in_payment_basis: true〔ハただし書〕）
            #   prior_allowance_period：ロの他の者から前に退職手当等を受けているときの、その退職手当等の所令69①の期間（70①一）
            "service_adjustments": opt(
                array(
                    obj(
                        {
                            "type": req(enum("earlier_service_same_payer", "other_employer_service", "prior_allowance_basis")),
                            "period": req(PERIOD),
                            "included_in_payment_basis": opt(BOOL),
                            "prior_allowance_period": opt(PERIOD),
                        }
                    )
                )
            ),
        },
    ),
    RecordKind(
        "brokerage_annual", "F-D17", "特定口座の年間取引", {"holder": True}, WHEN_TAX_YEAR,
        amounts={
            "proceeds": opt(YEN),
            "acquisition_cost": opt(YEN),
            "net_gain_loss": opt(SYEN),
            "dividends_received": opt(YEN),
            "withholding_tax": opt(YEN),
            "net_after_offset": opt(SYEN),
            # 補（2026-11-11）：年間取引報告書の住民税の額（配当割額・株式等譲渡所得割額。地方税法第314条の9 の控除の材料）
            "dividend_local_tax": opt(YEN),
            "transfer_local_tax": opt(YEN),
            # 補（2026-11-12）：年間取引報告書の源泉徴収税額（所得税）の譲渡の分と配当等の分（withholding_tax の内訳。IK-93）
            "transfer_withholding_tax": opt(YEN),
            "dividend_withholding_tax": opt(YEN),
        },
        attributes={"account_id": req(ID), "withholding_elected": req(BOOL), "counterparty": opt(NAME)},
    ),
    RecordKind(
        "housing_loan_credit", "F-D18", "外部で計算した住宅借入金等特別控除の額", {"person": True}, WHEN_TAX_YEAR,
        amounts={"credit_amount": req(YEN)},
        attributes={
            "moved_in_on": opt(DATE),
            "source_note": opt(TEXT),
            # 補（2026-11-11）：住宅借入金等特別控除額の計算明細書の取得の区分の記載（特定取得・特別特定取得。住民税の住宅借入金等特別税額控除の
            # 控除限度の材料：rules/juminzei/README.md §7）
            "acquisition_category": opt(enum("specified_acquisition", "specially_specified_acquisition", "other")),
            # 補（2026-11-12）：計算明細書に記載した、前年分の所得税で適用を受けた特例法（東日本大震災の震災特例法第13条・新型コロナ特例法第6条の2）。
            # 住民税の附則第45条・第61条の読替えの材料（rules/juminzei/README.md JM-18）。欄がなければどちらの適用も受けていない
            "special_acts": opt(array(enum("great_east_japan_earthquake", "covid19"), min_items=0)),
        },
    ),
    RecordKind(
        # 補（2026-11-12）：外部で計算した、住宅借入金等特別控除以外の税額控除の額（SCOPE §4：判定コアは計算せず額を受け取る）。
        # 確定申告書 第一表の ㉞（事業所得等の特例に係る税額控除：手引き 3-4_29 の「投資税額等」）と ㊴〜㊶（住宅耐震改修特別控除等：手引き 3-4_32）。
        # credit_type は計算明細書・付表で計算した控除の種類（事実の区分。欄・区分の番号への対応は判定コアの様式の対応表）：
        #   business_income_special：事業所得等の特例に係る税額控除（中小企業者が機械等を取得した場合の所得税額の特別控除など。合計した額を1件で書く）
        #   seismic_retrofit：住宅耐震改修特別控除
        #   specified_housing_renovation：住宅特定改修特別税額控除（バリアフリー・省エネ・多世帯同居・耐久性向上・子育て対応の改修工事等）
        #   certified_housing_new_build：認定住宅等新築等特別税額控除
        # 同じ人・年分・種類の記録は1件（2件以上は判定コアが入力の誤りとして返す：rules/tax/README.md TX-26）
        "external_tax_credit", "補", "外部で計算した税額控除の額（住宅借入金等特別控除以外）", {"person": True}, WHEN_TAX_YEAR,
        amounts={"credit_amount": req(YEN)},
        attributes={
            "credit_type": req(
                enum("business_income_special", "seismic_retrofit", "specified_housing_renovation", "certified_housing_new_build")
            ),
            "source_note": opt(TEXT),
        },
    ),
    RecordKind(
        # 補（2026-11-12）：外部で計算した割増償却・特別償却の額（租税特別措置法の個人の減価償却の特例。SCOPE §5.2 の減価償却の範囲。
        # 住宅借入金等特別控除と同じく、判定コアは特別償却限度額・割増償却の限度を計算せず、資産ごと・年分ごとの額を受け取る：
        # rules/income_kinds/README.md IK-112、docs/public-sources/20261112_impl-research7_tokubetsu-shokyaku.md）。
        #   asset_id：償却する資産（depreciable_asset）
        #   article：適用を受けた租税特別措置法の条（e-Gov の条の番号の形：10_3＝第10条の3、11_2＝第11条の2）。その年分の版の番号で書く
        #   method：special（特別償却）・extra（割増償却）
        #   shortfall_carryover：真なら、前年分の償却不足額（合計償却限度額に満たない金額）を翌年分に繰り越して必要経費に算入する額（第10条の3第2項など）
        #   amount：その年分に必要経費に算入する割増償却・特別償却の額（普通償却費を除く。事業専用割合を掛ける前の全額）
        # 前年以前の年分に適用を受けた額も年分ごとに書く（未償却残高と、その後の普通償却の基礎に要る）。同じ資産・年分は1件。
        # 条が個人の特別償却・割増償却の条か、青色申告書を提出する個人の要件・所得の種類・第19条（複数の規定の不適用）は判定コアが確かめる
        "special_depreciation", "補", "割増償却・特別償却の額（外部で計算した値）", {"owner": True}, WHEN_TAX_YEAR,
        amounts={"amount": req(YEN)},
        attributes={
            "asset_id": req(kind_ref("depreciable_asset")),
            "article": req({"type": "string", "pattern": "^[0-9]{1,3}(_[0-9]{1,3}){0,3}$"}),
            "method": req(enum("special", "extra")),
            "shortfall_carryover": opt(BOOL),
            "source_note": opt(TEXT),
        },
    ),
    RecordKind(
        "ct_return", "F-D18", "消費税等の申告書・処分（期間は課税期間）", {"person": True}, WHEN_PERIOD,
        amounts={"consumption_tax": req(SYEN), "local_consumption_tax": opt(SYEN), "additional_tax": opt(YEN)},
        attributes={
            "return_type": req(enum("final", "amended", "correction_decision", "assessment")),
            "filed_or_decided_on": req(DATE),
            # 補（2026-11-12）：消費税等の額の業務ごとの内訳（業務の区分の材料：rules/income_kinds/README.md IK-52・56）。
            # 書くなら全部の業務を書き、合計を amounts と一致させる（一致しなければ判定コアが入力の矛盾として返す）
            "business_breakdown": opt(
                array(
                    obj(
                        {
                            "business_id": req(kind_ref("business")),
                            "consumption_tax": req(SYEN),
                            "local_consumption_tax": opt(SYEN),
                        }
                    )
                )
            ),
        },
    ),
    RecordKind(
        "authority_decision", "F-D19", "市町村・保険者の個別の処分", {"person": True}, WHEN_FISCAL_YEAR,
        attributes={
            "decision": req(
                enum(
                    "reduction_approved",
                    "kokuho_student_special_case_recognized",
                    "taxation_at_non_resident_record_municipality",
                )
            ),
            "authority": req(enum("municipality", "insurer")),
            # 補（2026-11-12）：処分の税目（個人住民税〔市町村民税・道府県民税〕・国民健康保険料〔税〕）。減免は両方にある
            # （地方税法第323条・第45条、国保法第77条・地方税法第717条：docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md §8）。
            # 所得税は国税で処分をするのが税務署長なので、この種類に入れない（更正・決定は filed_document の return_type）
            "tax_item": req(enum("resident_tax", "national_health_insurance")),
            "municipality_code": opt(MUNI),
            "insurer_id": opt(ID),
        },
    ),
    RecordKind(
        "jan1_payer_status", "F-D20", "1月1日の給与・年金の支払者", {"person": True}, WHEN_FISCAL_YEAR,
        amounts={"prior_year_salary_from_former_payers": opt(YEN)},
        attributes={
            "salary_payer_on_jan1": req(BOOL),
            "pension_payer_on_jan1": req(BOOL),
            "payer_must_file_report": opt(BOOL),
        },
    ),
    RecordKind(
        "tax_agent_notice", "F-D21", "納税管理人の選任・解任の届出（on は提出日）", {"taxpayer": True}, WHEN_ON,
        attributes={"action": req(enum("appointment", "dismissal")), "agent_name": opt(NAME)},
    ),
    RecordKind(
        # 補（2026-11-12）：相続人の全員が放棄した（相続人不存在）ときの、相続財産の清算人が確定した日（裁判所から清算人に
        # 通知された日。国税庁の質疑応答事例 07-15 の期限の起算日：rules/tax/README.md TX-13）
        "estate_liquidator", "補（tax TX-13）", "相続財産の清算人が確定した日（on）", {"decedent": True}, WHEN_ON,
        attributes={"liquidator_name": opt(NAME)},
    ),
    # 補（2026-11-12 の4回目）：棚卸資産・家事消費等・貸倒れ（rules/income_kinds/README.md IK-108〜IK-111。
    # docs/public-sources/20261112_impl-research6_tanaoroshi-laws-and-nta.md）。法令の区分（どの評価の方法が当たるか・事業か業務か）は判定コアが決める
    RecordKind(
        "inventory_count", "補（income_kinds IK-108）",
        "棚卸資産の棚卸し（on は棚卸しの基準の日：12月31日・年の中途の死亡の日、期首の棚卸しは年の初日・業務の開始の日）", {"owner": True}, WHEN_ON,
        amounts={"valuation": req(YEN)},  # 評価額（valuation_method で評価した、その区分の棚卸資産の額の合計）
        attributes={
            "business_id": req(kind_ref("business")),
            # 評価の方法（所令99①一イ〜ヘ、99の2 の承認を受けた特別な方法）。最終仕入原価法は届出がないときの法定の方法（所令102①）
            "valuation_method": req(INVENTORY_METHOD),
            "lower_of_cost": opt(BOOL),  # 低価法（所令99①二：上の原価法の額と年末の価額の低い方）で評価した額か
            "asset_class": opt(INVENTORY_CLASS),  # 所令100① の区分（省略は全部の区分を1つの記録に書いたもの）
            "count_type": opt(enum("year_end", "opening")),  # 期末の棚卸し（既定）か、期首の棚卸し（所規60②・業務の開始）
        },
    ),
    RecordKind(
        "inventory_method_notice", "補（income_kinds IK-108）",
        "棚卸資産の評価の方法の届出・変更の承認の申請と処分（on は提出・処分の日）", {"person": True}, WHEN_ON,
        attributes={
            "business_id": req(kind_ref("business")),
            "procedure": req(
                enum(
                    "selection_notice",  # 所令100② の届出
                    "change_application",  # 所令101② の変更の承認の申請
                    "change_approved",  # 所令101④ の承認の通知
                    "change_rejected",  # 所令101③④ の却下の通知
                    "special_method_approved",  # 所令99の2③ の承認の通知
                )
            ),
            "method": req(INVENTORY_METHOD),
            "lower_of_cost": opt(BOOL),
            "asset_class": opt(INVENTORY_CLASS),
        },
    ),
    RecordKind(
        "household_consumption", "補（income_kinds IK-109）",
        "棚卸資産の家事消費・贈与（所法39・40①一。on は消費・贈与の日。その年中の合計を1件に書いてよい）", {"owner": True}, WHEN_ON,
        amounts={
            "normal_sales_price": opt(YEN),  # 通常他に販売する価額（販売用でない資産は通常売買される価額。所基通39−1）
            "recorded_amount": opt(YEN),  # 帳簿に記載して総収入金額に算入した額（所基通39−2）
            "acquisition_cost": opt(YEN),  # その棚卸資産の取得価額（所基通39−2 の「取得価額以上」の材料）
        },
        attributes={
            "business_id": req(kind_ref("business")),
            "event": req(enum("household_use", "gift")),  # 家事のための消費（所法39）・贈与又は遺贈（所法40①一）
        },
    ),
    RecordKind(
        "bad_debt", "補（income_kinds IK-110）",
        "業務の債権の貸倒れ・返品値引き等（on は貸倒れの事実が生じた日。所法51②・所令141・所法64①）", {"creditor": True}, WHEN_ON,
        amounts={"amount": req(YEN)},  # 損失の金額（所基通51−13 の備忘価額を控除した後の額）
        attributes={
            "business_id": req(kind_ref("business")),
            "event": req(
                enum(
                    "legal_cutoff",  # 所基通51−11(1)〜(3)：更生計画・再生計画・特別清算の協定・関係者の協議決定による切捨て
                    "debt_forgiveness_notice",  # 所基通51−11(4)：債務免除額の書面による通知
                    "uncollectible",  # 所基通51−12：全額が回収できないことが明らか
                    "transaction_stopped",  # 所基通51−13(1)：取引の停止後1年以上
                    "collection_cost",  # 所基通51−13(2)：取立ての費用に満たない
                    "returns_or_discounts",  # 所令141一：販売した商品の返戻・値引き
                    "guarantee_recourse",  # 所令141二：保証債務の履行に伴う求償権の行使不能
                    "invalid_act",  # 所令141三：無効な行為・取消し
                )
            ),
            "receivable_type": opt(enum("sales", "loan", "advance", "rent", "deposit", "other")),
            # その債権の収入金額を総収入金額に算入した年分（業務〔事業でない〕の所法64①：その年分の所得の金額の計算上なかったものとみなす）
            "revenue_tax_year": opt(YEAR),
        },
    ),
    RecordKind(
        "rental_inventory", "F-A05", "貸付不動産の保有状況", {"owner": True}, WHEN_TAX_YEAR,
        attributes={
            "rooms": opt(COUNT),
            "buildings": opt(COUNT),
            "land_lots": opt(COUNT),
            "parking_spaces": opt(COUNT),
            "land_area_m2": opt(RATE),
            "management_note": opt(TEXT),
        },
    ),
    RecordKind(
        "property_tax", "F-A06", "固定資産税額", {"taxpayer": True}, WHEN_FISCAL_YEAR,
        amounts={"land": opt(YEN), "building": opt(YEN)},
        attributes={"municipality_code": req(MUNI)},
    ),
    RecordKind(
        "residence_status", "F-A07", "住宅の賦課期日の状態（家屋敷課税の材料。on は賦課期日）", {"holder": True},
        WHEN_ON,
        attributes={
            "property_id": req(kind_ref("residence_property")),
            "occupant_person_ids": opt(array(PERSON)),
            "leased_to_others": opt(BOOL),
            "intended_for_lease": opt(BOOL),
            "always_habitable": opt(BOOL),
        },
    ),
)

# 資産・物件・契約の台帳（VOC §1.5。保険の契約 F-D15 もここ）
ASSET_KINDS: tuple[RecordKind, ...] = (
    RecordKind(
        "depreciable_asset", "F-A01", "減価償却資産（期間は取得日〜処分日）", {"owner": True}, WHEN_PERIOD,
        amounts={
            "acquisition_cost": req(YEN),
            "acquisition_consumption_tax": opt(YEN),
            "cost_excluding_consumption_tax": opt(YEN),
            "disposal_proceeds": opt(YEN),
            "disposal_expenses": opt(YEN),
            "insurance_recovery": opt(YEN),
            # 補（2026-11-12）：リース資産（所有権移転外リース取引で賃借人が取得したものとされる資産）の残価保証額（所得税法施行令第120条の2
            # 第2項第6号。リース期間定額法の材料：rules/income_kinds/README.md IK-103）
            "residual_value_guarantee": opt(YEN),
            # 補（2026-11-12）：国外リース資産の見積残存価額（所令第120条第2項。旧国外リース期間定額法の材料：IK-103）
            "estimated_residual_value": opt(YEN),
        },
        attributes={
            "name": req(NAME),
            "quantity": opt(COUNT),
            "unit": opt(NAME),
            "acquisition_type": opt(enum("purchase", "self_constructed", "gift", "inheritance", "other")),
            "placed_in_service_on": opt(DATE),
            "business_id": opt(kind_ref("business")),
            "prior_use_months": opt(COUNT),
            "leased_out": opt(BOOL),
            "acquisition_transaction_ids": opt(array(TX)),
            "disposal_type": opt(enum("sale", "scrapping", "loss", "other")),
            # 補（2026-11-12）：貸付けの用に供する賃貸物件（物件ごとの収支の材料：rules/income_kinds/README.md IK-70）
            "property_id": opt(kind_ref("rental_property")),
            # 補（2026-11-12）：この資産を専ら用いた売上（business_receipt）。家族から受けた対価の売上なら、その対価に係る減価償却費の材料
            # （所得税法第56条後段：rules/income_kinds/README.md IK-32。business_expense の receipt_id と同じ読み）
            "receipt_id": opt(kind_ref("business_receipt")),
            # 補（2026-11-12）：リース資産・国外リース資産のリース期間（契約に定められた賃貸借の期間。両端を含む）と契約の締結の日
            # （所令第120条第1項第6号・第120条の2第1項第6号・第2項第7号。IK-103）
            "lease_term": opt(obj({"from_on": req(DATE), "to_on": req(DATE)})),
            "lease_contracted_on": opt(DATE),
            # 補（2026-11-12）：鉱業用減価償却資産・鉱業権の、その資産の属する鉱区の採掘数量（年分ごと。年の中途で業務の用に供した・供しなくなった年は、
            # 業務の用に供していた期間の採掘数量：所令第120条第1項第3号ハ・第120条の2第1項第3号イ(2)・第132条第1項各号ロ。IK-103）。
            # 単位は 判断.減価償却の区分 の planned_extraction_quantity と同じ。year_quantity はその年の鉱区の採掘数量の全部（年の中途で業務の用に
            # 供した・供しなくなった年に、所令第134条第2項の均等償却の額を採掘数量で按分するときだけ要る：第134条第3項・第132条第1項各号ロ）
            "extraction_quantities": opt(
                array(obj({"tax_year": req(YEAR), "quantity": req(QUANTITY), "year_quantity": opt(QUANTITY)}))
            ),
        },
    ),
    RecordKind(
        "rental_property", "F-A02", "賃貸物件（期間は所有期間）", {"owner": True}, WHEN_PERIOD,
        amounts={"acquisition_cost": opt(YEN)},
        attributes={
            "property_type": req(enum("building", "room", "land", "parking", "other")),
            "municipality_code": opt(MUNI),
            "owner_share": opt(RATIO),
            "co_owners": opt(array(obj({"person": req(PERSON), "share": req(RATIO)}))),
            "mixed_use": opt(BOOL),
            "held_as_villa": opt(BOOL),
            "acquisition_contract": opt(NAME),
            "business_id": opt(kind_ref("business")),  # 補（2026-11-11）：貸付けを営む業務（事業の識別子）
            # 補（2026-11-12）：物件の所在地が国外なら国のコード（なければ国内。租税特別措置法第41条の4の3 の国外中古建物・国外不動産等の材料：
            # rules/income_kinds/README.md IK-104）
            "country_code": opt(COUNTRY),
            # 補（2026-11-12）：組合契約（民法第667条第1項の組合契約・投資事業有限責任組合契約・外国のこれらに類する契約・外国の有限責任事業組合契約に
            # 類する契約）に基づく組合事業、又は信託（受益者として）から生ずる不動産所得の物件か（措法第41条の4の2。IK-104）と、
            # その組合契約・信託の識別（組合事業・信託ごとに損失を計算する：措令第26条の6の2第4項・措規第18条の24第2項）
            "held_through": opt(enum("partnership_contract", "trust")),
            "arrangement_id": opt(NAME),
        },
    ),
    RecordKind(
        "lease", "F-A03", "賃貸借契約（期間は契約期間）", {"lessor": True, "lessee": False}, WHEN_PERIOD,
        amounts={"monthly_rent": opt(YEN), "common_service_fee": opt(YEN), "deposit": opt(YEN), "key_money": opt(YEN)},
        attributes={
            "property_id": req(kind_ref("rental_property")),
            "lessee_name": opt(NAME),
            "payment_due_day": opt(COUNT),
        },
    ),
    RecordKind(
        "loan", "F-A04", "借入れ", {"borrower": True}, WHEN_PERIOD,
        amounts={"principal": req(YEN)},
        attributes={
            "purpose_asset_id": opt(ASSET),
            "interest_rate": opt(RATE),
            "lender": opt(NAME),
            "business_id": opt(kind_ref("business")),  # 補（2026-11-11）：借入れを用いた業務（事業の識別子）
        },
    ),
    RecordKind(
        "residence_property", "F-A07", "住宅（家屋敷課税の材料。期間は所有・賃借の期間）", {"holder": True},
        WHEN_PERIOD,
        attributes={
            "municipality_code": req(MUNI),
            "tenure": req(enum("owned", "rented")),
            # 補（2026-11-11）：家屋敷（住宅）か事務所・事業所か（家屋敷課税：地方税法第294条第1項第2号）。なければ住宅
            "facility_type": opt(enum("dwelling", "office_or_business_place")),
        },
    ),
    RecordKind(
        "insurance_contract", "F-D15", "保険の契約（期間は保険期間）", {"policyholder": True, "insured": False},
        WHEN_PERIOD,
        amounts={"certificate_amount": opt(YEN)},
        attributes={
            "product_type": req(
                enum("life", "medical_or_care", "individual_annuity", "earthquake", "long_term_non_life", "other")
            ),
            "concluded_on": req(DATE),
            "insurer_name": opt(NAME),
            "beneficiary_ids": opt(array(PERSON)),
            "rider": opt(BOOL),
            # 補（2026-11-12）：附帯契約（rider: true）が附帯した契約（所法76⑩）
            "attached_to_contract_id": opt(kind_ref("insurance_contract")),
            # 補（2026-11-12）：保険金等の支払の定め（所令209①）。満了の日に生存している場合に限り支払う／満了の日に生存している場合と
            # 保険期間中に災害・感染症その他の特別の事由により死亡した場合に限り支払う／それ以外
            "benefit_payment_terms": opt(enum("survival_at_maturity_only", "survival_or_special_cause_death", "other")),
            # 補（2026-11-12）：長期損害保険の満期返戻金（平成18年法律第10号附則第10条第2項）。満期返戻金を支払う旨の特約／
            # 共済期間中の耐存を共済事故とする共済（質疑応答事例 05/68）／どちらでもない
            "maturity_refund": opt(enum("maturity_refund_rider", "durability_mutual_aid", "none")),
            # 補（2026-11-12）：契約の変更をした日の全部（変更がなければ空の配列。同附則第10条第2項の「平成19年1月1日以後に契約の変更をしていない」の材料）
            "contract_changes_on": opt(array(DATE, min_items=0)),
            "annuity_payment_start_on": opt(DATE),
            "insured_object": opt(enum("dwelling", "household_goods", "other")),
            "insured_object_owner": opt(PERSON),
            "residential_use": opt(BOOL),
            # 補（2026-11-12）：家屋のうち居住の用に供している部分の割合（所基通77−5：居住割合・床面積の比。77−6 のおおむね90%以上の判定にも使う）
            "residential_ratio": opt(RATIO),
            "certificate_electronic": opt(BOOL),
            "certificate_includes_projection": opt(BOOL),
        },
    ),
)

# 提出した書類の記載（VOC F-D01・F-D02）。VOC §0.3 の「選択 → 提出 → 記載」の2段目
FILED_DOCUMENT_KINDS: tuple[RecordKind, ...] = (
    RecordKind(
        "filed_document", "F-D01・F-D02", "申告書等の提出と記載（on は提出日）", {"filer": True}, WHEN_ON,
        attributes={
            "document_type": req(DOCUMENT_TYPE),
            "tax_year": opt(YEAR),
            "fiscal_year": opt(YEAR),
            "recipient": req(enum("tax_office", "employer", "pension_payer", "municipality", "insurer", "other")),
            "recipient_name": opt(NAME),
            "entries": opt(array(obj({"person": req(PERSON), "section": req(ENTRY_SECTION), "note": opt(TEXT)}))),
            "reported_amounts": opt(
                array(
                    obj(
                        {
                            "item": req(
                                enum(
                                    "taxable_income_total",
                                    "income_tax_before_credits",
                                    "income_tax_after_credits",
                                    "basic_deduction",
                                    "net_loss_total",
                                    "net_loss_carryforward_used",
                                    "net_loss_carryback",
                                    "listed_stock_loss_carryforward",
                                    "listed_stock_loss_carryforward_used",
                                    "casualty_loss_carryforward",
                                    "taxable_retirement_income",  # 課税退職所得金額（補 2026-11-11。純損失の繰戻し：所令271①）
                                    "taxable_timber_income",  # 課税山林所得金額（補 2026-11-11。同上）
                                    # 補（2026-11-12）：その年度分の住民税の所得割の計算で控除しきれず、翌年度以後に繰り越す雑損失の金額（地方税法第313条第9項。
                                    # origin_tax_year は損失の生じた年。fiscal_year のある書類に書く：rules/juminzei/README.md JM-32）
                                    "resident_tax_casualty_loss_carryforward",
                                    # 補（2026-11-12）：同じく繰り越す純損失の金額（地方税法第313条第8項・第9項。JM-32）
                                    "resident_tax_net_loss_carryforward",
                                    "other",
                                )
                            ),
                            "amount": req(SYEN),
                            "origin_tax_year": opt(YEAR),
                            "label": opt(NAME),
                        }
                    )
                )
            ),
            "realized_choice_ids": opt(array(CHOICE)),
            "correction": opt(enum("original", "amended_return", "correction_request", "reassessment")),
        },
    ),
)

# ---------------------------------------------------------------------------
# 判断台帳（judgments：人の判断・予測・見積り・計画）と納税者の選択（choices）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerKind:
    """判断台帳の項目の種類。value の型が D21 R6 の「値の領域」になる。"""

    kind: str
    vocab: str
    title: str
    subject: Mapping[str, Field]
    when: str | None  # None のときは when を置かない（対象の記録の日付を使う）
    value: Schema
    mark: str | None = None  # 種類で決まる印（見込み.*＝予測、見積り.*＝見積り、計画.*＝計画）


def _pair(a: str, b: str) -> dict[str, Field]:
    return {a: req(PERSON), b: req(PERSON)}


_ONE = {"person": req(PERSON)}

JUDGMENT_KINDS: tuple[LedgerKind, ...] = (
    LedgerKind("判断.生計を一にする", "J-01", "生計を一にする", _pair("person", "other_person"), WHEN_PERIOD, BOOL),
    LedgerKind("判断.事実婚", "J-02", "事実婚", _pair("person", "other_person"), WHEN_PERIOD, BOOL),
    LedgerKind("判断.同居を常況", "J-03", "同居を常況としている", _pair("person", "other_person"), WHEN_PERIOD, BOOL),
    LedgerKind(
        "判断.健保の同一の世帯", "J-04", "健保の同一の世帯", _pair("insured", "person"), WHEN_PERIOD,
        obj({"same_household": req(BOOL), "criterion": req(enum("actual_living", "resident_record"))}),
    ),
    LedgerKind("判断.共済の生計を共にする", "J-05", "共済の生計を共にする", _pair("member", "person"), WHEN_PERIOD, BOOL),
    LedgerKind("判断.一時的な別居", "J-05", "共済の一時的な別居", _pair("member", "person"), WHEN_PERIOD, BOOL),
    LedgerKind("判断.住所の所在", "J-06", "住所が国内にあるか（居住者か）", _ONE, WHEN_PERIOD, enum("domestic", "foreign")),
    # 補（2026-11-12）：出国の年に、国外転出をする場合の譲渡所得等の特例（所得税法第60条の2 など。範囲外：HANDOFF D22 S11）の
    # 対象になるか（true＝対象になる）。rules/personal_deductions/README.md PD-05
    LedgerKind("判断.国外転出時課税の対象", "補（personal_deductions PD-05）", "出国の年に国外転出時課税の対象になるか", _ONE, WHEN_TAX_YEAR, BOOL),
    # 補（2026-11-12）：非居住者の期間がある人の、その期間の国内源泉所得以外の所得の金額（その年分の合計所得金額に含めるかの
    # 読みの材料：rules/personal_deductions/README.md PD-06）。0 なら読みで値が分かれない
    LedgerKind(
        "判断.国内源泉所得の内訳", "補（personal_deductions PD-06）", "非居住者の期間の国内源泉所得以外の所得の金額", _ONE, WHEN_TAX_YEAR,
        obj({"non_domestic_income": req(SYEN)}),
    ),
    LedgerKind("判断.国内居住の例外第5号", "J-07", "健保の国内居住要件の例外", _ONE, WHEN_PERIOD, BOOL),
    LedgerKind("判断.老人ホーム等", "J-08", "施設が老人ホーム等か", {"stay_id": req(kind_ref("institution_stay"))}, None, BOOL),
    LedgerKind(
        "判断.事業と称するに至る程度", "J-09", "事業と称するに至る程度か",
        {"person": req(PERSON), "business_id": req(kind_ref("business"))}, WHEN_TAX_YEAR, BOOL,
    ),
    LedgerKind("判断.不動産の事業的規模", "J-10", "不動産の貸付けが事業的規模か", _ONE, WHEN_TAX_YEAR, BOOL),
    # 補（2026-11-12 の4回目）：その業務について、その年の12月31日（年の中途で死亡したときはその日）に棚卸資産（所令3：商品・製品・半製品・
    # 仕掛品・原材料・貯蔵中の消耗品など）を有するか。false なら期末の棚卸高は0（棚卸しの記録 inventory_count がなくても計算する）。
    # rules/income_kinds/README.md IK-108
    LedgerKind(
        "判断.棚卸資産の有無", "補（income_kinds IK-108）", "年末に棚卸資産を有するか",
        {"person": req(PERSON), "business_id": req(kind_ref("business"))}, WHEN_TAX_YEAR, BOOL,
    ),
    # 補（2026-11-12）：組合契約の組合員である人が、その年の12月31日（死亡・脱退・解散の日）において、組合契約を締結した日以後引き続き
    # 組合事業の重要な財産の処分・譲受け・多額の借財に関する業務のすべての執行の決定に関与し、かつ、契約の交渉その他の重要な部分のすべてを
    # 自ら執行しているか（true なら特定組合員でない。業務の執行の全部を委任していれば false：租税特別措置法施行令第26条の6の2第2項・第3項。
    # arrangement_id は rental_property の arrangement_id。rules/income_kinds/README.md IK-104）
    LedgerKind(
        "判断.組合の重要業務の執行", "補（income_kinds IK-104）", "組合事業の重要業務の執行の決定に関与し自ら執行しているか",
        {"person": req(PERSON), "arrangement_id": req(NAME)}, WHEN_TAX_YEAR, BOOL,
    ),
    LedgerKind(
        "判断.雇用か請負か", "J-11", "雇用か請負か", {"person": req(PERSON), "record_id": req(RECORD)}, None,
        enum("employment", "independent_contract"),
    ),
    LedgerKind("判断.業務関連性", "J-12", "支出が業務に関連するか", {"record_id": req(RECORD)}, None, BOOL),
    LedgerKind(
        "判断.按分の割合", "J-13", "按分の割合",
        {"person": req(PERSON), "record_ids": opt(array(RECORD)), "business_id": opt(kind_ref("business"))},
        WHEN_TAX_YEAR,
        obj(
            {
                "purpose": req(
                    enum(
                        "household_expense_business_share",
                        "asset_business_share",
                        "dwelling_residential_share",
                        # family_use_share（語彙の約束 2026-11-12）：record_ids の業務の資産（depreciable_asset）・支出（business_expense）の
                        # うち、業務を営む人（subject.person）が家族に使わせていて業務の用に供していない部分の割合。業務の部分は 1−割合。
                        # 同じ記録に asset_business_share・household_expense_business_share もあれば業務の部分はそちらの割合で、
                        # 家族の使用の割合は「両方の合計が1以下」の検査にだけ使う
                        "family_use_share",
                    )
                ),
                "ratio": req(RATIO),
                "measure": opt(enum("area", "time", "usage", "other")),
                "clearly_separable": opt(BOOL),
            }
        ),
    ),
    LedgerKind(
        "判断.医療費の範囲", "J-14", "支払が医療費の範囲に入るか", {"payment_id": req(kind_ref("medical_payment"))}, None,
        BOOL,
    ),
    LedgerKind(
        "判断.補塡の対象", "J-15", "給付が補塡か・どの医療費の補塡か", {"reimbursement_id": req(kind_ref("reimbursement"))},
        None,
        obj({"compensates_medical_expenses": req(BOOL), "target_payment_ids": opt(array(kind_ref("medical_payment")))}),
    ),
    LedgerKind(
        "判断.セルフメディケーション表示の上書き", "J-16", "レシートの表示の誤り・年分のずれ",
        {"payment_id": req(kind_ref("medical_payment"))}, None,
        obj({"eligible_item": req(BOOL), "tax_year": opt(YEAR)}),
    ),
    LedgerKind(
        "判断.障害の程度", "J-17", "障害の程度", _ONE, WHEN_PERIOD,
        obj(
            {
                "aspect": req(
                    enum(
                        "bedridden_requiring_complex_care",
                        "lacks_capacity",
                        "severe_intellectual_disability",
                        "evidently_disabled_pending_application",
                        "pension_disability_level_for_health_insurance",
                    )
                ),
                "applies": req(BOOL),
            }
        ),
    ),
    LedgerKind(
        "判断.自己の勤労に基づく", "J-18", "所得が自己の勤労に基づくか",
        {"person": req(PERSON), "record_id": opt(RECORD), "business_id": opt(kind_ref("business"))}, WHEN_TAX_YEAR,
        enum("based", "not_based"),
    ),
    LedgerKind("判断.家内労働者等", "J-19", "家内労働者等に当たるか", _ONE, WHEN_TAX_YEAR, BOOL),
    LedgerKind(
        "判断.減価償却の区分", "J-20", "耐用年数の区分など", {"asset_id": req(kind_ref("depreciable_asset"))}, None,
        obj(
            {
                "useful_life_table_row": opt(NAME),
                "useful_life_years": opt(COUNT),
                "usable_period_under_one_year": opt(BOOL),
                "essential_to_business": opt(BOOL),
                "lending_as_principal_business": opt(BOOL),
                # 補（2026-11-12）：資産の種類（耐用年数省令の別表の「種類」の大きな区分。償却の方法が選べるかの材料）。
                # building 建物、building_attachment 建物附属設備、structure 構築物、machinery_equipment 機械装置・船舶・航空機・
                # 車両運搬具・工具・器具備品、intangible 無形固定資産（ソフトウエアを含む）、other その他
                # 補（2026-11-12）：mining_asset 鉱業用減価償却資産・mining_right 鉱業権・foreign_lease_asset 国外リース資産（所得税法施行令第120条第1項
                # 第3号・第5号・第6号、第120条の2第1項第3号・第5号・第6号の資産の材料。rules/income_kinds/README.md IK-103）
                # 補（2026-11-12）：mine_tunnel 坑道（鉱業用。残存価額・償却の限度が無形と同じ：所令第134条第1項第1号ロ・第2号ロ、耐用年数省令 別表第十一）、
                # lease_asset リース資産（所有権移転外リース取引で賃借人が取得したものとされる資産：所令第120条の2第1項第6号・第2項第4号）
                "asset_class": opt(
                    enum(
                        "building",
                        "building_attachment",
                        "structure",
                        "machinery_equipment",
                        "intangible",
                        "mining_asset",
                        "mine_tunnel",
                        "mining_right",
                        "foreign_lease_asset",
                        "lease_asset",
                        "other",
                    )
                ),
                # 補（2026-11-12）：鉱業用減価償却資産・坑道・鉱業権の、その資産の耐用年数（鉱区の採掘予定年数が短ければその年数）の期間内の
                # 鉱区の採掘予定数量（所令第120条第1項第3号ハ・第120条の2第1項第3号イ(2)・第5号ロ。単位は depreciable_asset の extraction_quantities と同じ）
                "planned_extraction_quantity": opt(QUANTITY),
                # 補（2026-11-12）：鉱業用減価償却資産が所令第6条第1号・第2号の資産（建物・建物附属設備・構築物）か（第120条の2第1項第3号イ：
                # 平成28年4月1日以後の取得は定率法を選べない）
                "building_or_structure": opt(BOOL),
                # 補（2026-11-12）：耐用年数の決め方（legal 法定耐用年数、estimated_remaining 中古資産の見積り〔耐用年数省令第3条第1項第1号〕、
                # simplified 中古資産の簡便法〔同項第2号〕）と、見積りの使用可能期間が措規第18条の24の2第1項第1号イ〜ハの書類で確認できるか
                # （租税特別措置法第41条の4の3 の国外中古建物の材料：rules/income_kinds/README.md IK-104）
                "useful_life_method": opt(enum("legal", "estimated_remaining", "simplified")),
                "remaining_life_documented": opt(BOOL),
            }
        ),
    ),
    LedgerKind(
        "判断.不動産の区分の材料", "J-21", "不動産の区分の材料", {"record_id": req(RECORD)}, None,
        obj(
            {
                "custodial_parking": opt(BOOL),
                "simple_facility": opt(BOOL),
                "land_market_value": opt(YEN),
                "villa_purpose": opt(BOOL),
            }
        ),
    ),
    LedgerKind(
        "判断.正規の簿記の宣言", "J-22", "正規の簿記で記録・作成している旨",
        {"person": req(PERSON), "business_id": req(kind_ref("business"))}, WHEN_TAX_YEAR, BOOL,
    ),
    LedgerKind(
        "判断.専従者給与の相当性", "J-23", "専従者給与の相当性", _pair("employer", "employee"), WHEN_TAX_YEAR,
        obj(
            {
                "reasonable_amount": opt(YEN),
                "not_hindering_exclusive_engagement": opt(BOOL),
                "mental_or_physical_disability": opt(BOOL),
                "justifiable_reason": opt(BOOL),
                "bonus_criteria_amount": opt(YEN),
            }
        ),
    ),
    LedgerKind(
        "判断.退職の性質", "J-24", "退職手当等に当たるかなど", {"payment_id": req(kind_ref("retirement_payment"))}, None,
        obj(
            {
                "is_retirement_allowance": opt(BOOL),
                "disability_retirement": opt(BOOL),
                "officer_class": opt(enum("none", "specified_officer", "general_officer")),
                # 補（2026-11-12）：退職手当等に当たらないとしたとき、どの所得の収入に当たるか（給与・一時。IK-25）
                "income_type": opt(enum("salary", "occasional")),
            }
        ),
    ),
    LedgerKind(
        "判断.年金の性質", "J-25", "年金の性質", {"payment_id": req(kind_ref("pension_payment"))}, None,
        obj({"public_scheme": opt(BOOL), "employee_contribution_portion": opt(YEN)}),
    ),
    LedgerKind(
        "判断.雑損の計算", "J-26", "雑損の計算の材料", {"casualty_id": req(kind_ref("casualty"))}, None,
        obj(
            {
                "not_ordinarily_necessary_asset": opt(BOOL),
                "loss_measure": opt(enum("market_value", "acquisition_cost_basis")),
                "restoration_portion": opt(YEN),
                "expenditure_tax_year": opt(YEAR),
                # 補（2026-11-11）：大規模な災害の場合その他やむを得ない事情があるか（所基通72−6：災害のやんだ日から3年以内の支出）
                "unavoidable_circumstances": opt(BOOL),
            }
        ),
    ),
    LedgerKind(
        "判断.寄附の性質", "J-27", "寄附の性質", {"donation_id": req(kind_ref("donation"))}, None,
        obj({"admission_related": opt(BOOL), "special_benefit": opt(BOOL)}),
    ),
    LedgerKind(
        "判断.生命保険の区分", "J-28", "生命保険の区分", {"contract_id": req(kind_ref("insurance_contract"))}, None,
        obj(
            {
                "category": req(enum("general_life", "care_medical", "individual_annuity")),
                "dividend_allocation": opt(RATIO),
            }
        ),
    ),
    LedgerKind(
        "判断.収入の恒常性", "J-29", "収入・経費が一時的か恒常的か",
        {"person": req(PERSON), "record_ids": req(array(RECORD))}, None, enum("temporary", "recurring"),
    ),
    LedgerKind("判断.主たる扶養者", "J-30", "主たる扶養者か", _pair("person", "supporter"), WHEN_PERIOD, BOOL),
    # 補（2026-11-12）：過去の勤務実績等により、今後1年間の収入が被扶養者の収入の基準額以上とならないことが明らかか（when は判定日。
    # 保険者の運用の実績の窓の例外：FUKUOKA-KIJUN 第3 5(1)）
    LedgerKind(
        "判断.収入が基準額以上とならないことが明らか", "補", "今後1年間の収入が収入の基準額以上とならないことが明らか", _ONE, WHEN_ON, BOOL,
    ),
    LedgerKind("判断.大口株主等", "J-31", "大口株主等か", {"dividend_id": req(kind_ref("dividend"))}, None, BOOL),
    LedgerKind("判断.扶養費の一部負担", "J-32", "扶養費の一部負担（住民税の寡婦の判定）", _ONE, WHEN_TAX_YEAR, BOOL),
    LedgerKind(
        # 補（2026-11-12）：障害者が交通用具を使用せざるを得ない特別の事情で片道2km未満を自動車等で通勤するか（質疑応答事例 03/18：
        # rules/kyuyo/README.md §4）。true なら合理的な運賃の額を限度額とする
        "判断.障害者の通勤の特別の事情", "補（kyuyo 質疑03-18）", "障害者が特別の事情で交通用具を使用して通勤するか",
        {"person": req(PERSON), "counterparty": req(NAME)}, WHEN_PERIOD, BOOL,
    ),
    LedgerKind(
        "判断.通勤の合理的な運賃", "補（tsukin HT3・UT4）", "最も経済的かつ合理的と認められる通常の経路及び方法による1か月当たりの運賃等の額",
        {"person": req(PERSON), "counterparty": req(NAME)}, WHEN_PERIOD, obj({"monthly_amount": req(YEN)}),
    ),
    LedgerKind(
        "判断.通勤手当の限度の当て方", "補（tsukin UT1〜UT3）", "通勤手当の限度額の当て方で法令の読みが分かれるところをどちらで扱うか", _ONE,
        WHEN_TAX_YEAR, enum("low", "high"),
    ),
    LedgerKind(
        "判断.給与の支給期が死亡前か", "補（kyuyo-jiki UJ2）", "死亡の日と同じ日の支給日・支給日の定めがない給与の支給期が死亡の時より前か",
        {"record_id": req(kind_ref("salary_payment"))}, None, BOOL,
    ),
    LedgerKind(
        # 補（2026-11-12 の2回目。kyuyo KY-13）：特定支出の候補の支出（specific_expense）の amount のうち、政令の範囲に入る部分の額（人の判断）。
        # 職務上の旅費・帰宅旅費は「最も経済的かつ合理的と認められる通常の経路及び方法による」旅行に要する部分（所得税法施行令第167条の3第2項・第5項）、
        # 転居費は「旅行に通常必要であると認められる運賃及び料金」・「宿泊費（通常必要であると認められる額を著しく超える部分を除く）」（同第3項第1号・第3号）。
        # 特別車両料金等（amounts.special_seat_fee・attributes.sleeper_fees）は判定コアが別に除く。countable_amount は amount 以下
        "判断.特定支出の通常の範囲の額", "補（kyuyo KY-13）",
        "特定支出の候補の支出のうち、通常の経路・方法による部分（旅費・帰宅旅費）・通常必要な運賃・著しく超えない宿泊費（転居費）の額",
        {"record_id": req(kind_ref("specific_expense"))}, None, obj({"countable_amount": req(YEN)}),
    ),
    LedgerKind(
        # 補（2026-11-11）：事業の全部の相当期間の休止又は重要部分の譲渡に当たるか（所令272①：純損失の繰戻しの事業の廃止等に準ずる事実。
        # 事業の廃止・全部の譲渡は blue_return_procedure の business_transfer_or_closure）
        "判断.事業の休止・重要部分の譲渡", "補（income_totals IT-13）", "事業の全部の相当期間の休止又は重要部分の譲渡に当たるか",
        {"person": req(PERSON), "business_id": opt(kind_ref("business"))}, WHEN_TAX_YEAR,
        enum("considerable_suspension", "important_part_transfer", "neither"),
    ),
    LedgerKind(
        "判断.家屋敷・事務所に当たる", "J-33", "家屋敷・事務所に当たるか（when は賦課期日）",
        {"person": req(PERSON), "property_id": req(kind_ref("residence_property"))}, WHEN_ON, BOOL,
    ),
    LedgerKind(
        # 補（2026-11-11、hifuyosha）：業務の支出の費目（expense_category は利用者の符号）が、被扶養者の年間収入から差し引ける経費の
        # 保険者の表のどの費目（「売上原価」「旅費交通費」など、注入データ 健保.事業収入から差し引ける経費 の費目の名前）に当たるか。
        # 差し引けるかは判定コアが保険者の運用（注入データ）で決める（packages/core/src/okura_core/rules/hifuyosha/README.md）
        "判断.健保の経費の費目", "補（hifuyosha）", "業務の支出の費目が、被扶養者の認定の経費の表のどの費目に当たるか",
        {"person": req(PERSON), "business_id": opt(kind_ref("business"))}, None,
        obj({"mappings": req(array(obj({"expense_category": req(CODE), "item": req(NAME)})))}),
    ),
    # --- 予測（D19 の見込み）・法令が求める見積り・申告の計画（VOC §2.3。D21 R2） ---
    LedgerKind(
        "見込み.年間収入", "P-01", "今後1年の年間収入の見込み（when は判定日）", _ONE, WHEN_ON,
        obj(
            {
                "amounts": req(array(obj({"income_type": req(INCOME_TYPE), "amount": req(YEN)}))),
                "temporary_increase_excluded": opt(YEN),
                "known_changes": opt(TEXT),
            }
        ),
        mark=MARK_FORECAST,
    ),
    LedgerKind(
        "見込み.援助額", "P-02", "今後1年の援助の見込み（when は判定日）", _pair("supporter", "person"), WHEN_ON,
        obj({"annual_amount": req(YEN), "planned_count": opt(COUNT), "amount_per_transfer": opt(YEN)}),
        mark=MARK_FORECAST,
    ),
    LedgerKind(
        "見込み.被保険者の年間収入", "P-02", "被保険者本人の今後1年の年間収入の見込み（when は判定日）",
        {"insured": req(PERSON)}, WHEN_ON, obj({"annual_amount": req(YEN)}), mark=MARK_FORECAST,
    ),
    LedgerKind(
        "見込み.将来の所得・加入", "P-03", "将来の年度のための所得・加入の見込み", _ONE, WHEN_TAX_YEAR,
        obj(
            {
                "amounts": opt(array(obj({"income_type": req(INCOME_TYPE), "amount": req(YEN)}))),
                "membership_changes": opt(TEXT),
            }
        ),
        mark=MARK_FORECAST,
    ),
    LedgerKind(
        "計画.申告の方法と時期", "P-04", "申告の方法と時期", _ONE, WHEN_TAX_YEAR,
        obj(
            {
                "method": req(enum("e_tax", "paper")),
                "planned_filing_on": opt(DATE),
                "within_deadline": opt(BOOL),
                "statements_attached": opt(BOOL),
            }
        ),
        mark=MARK_PLAN,
    ),
    LedgerKind(
        "見積り.親族の合計所得金額", "P-05", "年の中途で死亡・出国した人の親族の合計所得金額の見積り",
        _pair("person", "taxpayer"), WHEN_TAX_YEAR,
        obj({"estimated_amount": req(SYEN), "estimated_as_of": req(DATE)}),
        mark=MARK_ESTIMATE,
    ),
    LedgerKind(
        "見積り.補塡の見込額", "P-05", "確定申告の時までに確定していない補塡の見込額",
        {"payment_ids": req(array(kind_ref("medical_payment")))}, WHEN_TAX_YEAR,
        obj({"estimated_amount": req(YEN), "benefit_type": req(REIMBURSEMENT_TYPE), "estimated_as_of": opt(DATE)}),
        mark=MARK_ESTIMATE,
    ),
)

CHOICE_KINDS: tuple[LedgerKind, ...] = (
    LedgerKind(
        "選択.扶養の所属", "C-01", "誰の申告書等に誰をどの区分で記載するか", {"person": req(PERSON)}, WHEN_TAX_YEAR,
        obj({"filer": req(PERSON), "document_type": req(DOCUMENT_TYPE), "section": req(ENTRY_SECTION)}),
    ),
    LedgerKind(
        "選択.配偶者の記載", "C-02", "配偶者控除等の記載", {"spouse": req(PERSON)}, WHEN_TAX_YEAR,
        obj({"filer": req(PERSON), "document_type": req(DOCUMENT_TYPE), "listed": req(BOOL)}),
    ),
    LedgerKind(
        "選択.医療費控除かセルフメディケーション税制か", "C-03", "医療費控除かセルフメディケーション税制か", _ONE,
        WHEN_TAX_YEAR, enum("medical_expense_deduction", "self_medication"),
    ),
    LedgerKind(
        "選択.保険料控除の区分", "C-04", "保険料控除の新旧・地震保険と旧長期",
        {"person": req(PERSON), "contract_id": opt(kind_ref("insurance_contract"))}, WHEN_TAX_YEAR,
        obj(
            {
                "life_insurance_regime": opt(enum("new_only", "old_only", "both")),
                "earthquake_or_old_long_term": opt(enum("earthquake", "old_long_term")),
            }
        ),
    ),
    LedgerKind(
        "選択.寄附金の控除の方式", "C-05", "所得控除か税額控除か", {"donation_id": req(kind_ref("donation"))}, None,
        enum("income_deduction", "tax_credit"),
    ),
    # 補（2026-11-12）：前納した社会保険料を、その年中に到来する納付期日の回数で按分するか（所基通74・75−1(2)）、
    # 全額を支払った年分にするか（74・75−2）
    LedgerKind(
        "選択.前納した社会保険料の控除の年分", "補", "前納した社会保険料の按分か全額か",
        {"payment_id": req(kind_ref("social_insurance_payment"))}, None,
        enum("pro_rata", "all_in_paid_year"),
    ),
    LedgerKind(
        "選択.株式等の申告", "C-06", "配当・源泉徴収口座の申告の選択",
        {"person": req(PERSON), "record_id": opt(RECORD), "account_id": opt(ID)}, WHEN_TAX_YEAR,
        obj(
            {
                "target": req(enum("dividend", "withholding_account_transfer")),
                "declare": opt(BOOL),
                "taxation": opt(enum("aggregate", "separate")),
                "loss_offset": opt(BOOL),
                "carryforward": opt(BOOL),
            }
        ),
    ),
    LedgerKind(
        "選択.現金主義（業務に係る雑所得）", "C-07", "業務に係る雑所得の現金主義",
        {"person": req(PERSON), "business_id": req(kind_ref("business"))}, WHEN_TAX_YEAR, BOOL,
    ),
    LedgerKind(
        "選択.消費税等の経理方式", "C-08", "消費税等の経理方式（D22：選択。未入力なら両方で評価）",
        {"person": req(PERSON), "business_id": req(kind_ref("business"))}, WHEN_TAX_YEAR,
        obj(
            {
                "sales": req(TAX_TREATMENT),
                "fixed_assets": opt(TAX_TREATMENT),
                "inventory": opt(TAX_TREATMENT),
                "expenses": opt(TAX_TREATMENT),
                "accrue_unpaid_tax": opt(BOOL),
            }
        ),
    ),
    LedgerKind(
        "選択.減価償却", "C-09", "一括償却・少額の特例・処分の年の償却費・償却の方法",
        {"asset_id": req(kind_ref("depreciable_asset"))}, WHEN_TAX_YEAR,
        obj(
            {
                "lump_sum_depreciation": opt(BOOL),
                "small_amount_special_rule": opt(BOOL),
                "depreciate_in_disposal_year": opt(BOOL),
                # 補（2026-11-12）：その資産に当てる償却の方法（届出〔bookkeeping_status の depreciation_method_notice〕で選んだもの）。
                # 定額法・定率法・旧定額法・旧定率法。届出がなければ書かない（判定コアが法定償却方法で計算する）
                # 補（2026-11-12）：units_of_production 生産高比例法（鉱業権は令和8年分から生産高等比例法：所令第120条の2第1項第3号・第5号）、
                # old_units_of_production 旧生産高比例法（所令第120条第1項第3号ハ・第5号ロ）、transitional_lease_term 経過リース期間定額法
                # （所得税法施行令等の一部を改正する政令〔令和7年政令第120号〕附則第7条第2項。令和8年分以後。rules/income_kinds/README.md IK-103）、
                # lease_term リース期間定額法（所令第120条の2第1項第6号。経過リース期間定額法を選ばないことを書くときに使う）
                "depreciation_method": opt(
                    enum(
                        "straight_line",
                        "declining_balance",
                        "old_straight_line",
                        "old_declining_balance",
                        "units_of_production",
                        "old_units_of_production",
                        "transitional_lease_term",
                        "lease_term",
                    )
                ),
            }
        ),
    ),
    LedgerKind(
        "選択.不動産所得の計上", "C-10", "不動産所得の計上の方法", {"record_id": req(RECORD)}, WHEN_TAX_YEAR,
        obj(
            {
                "rule": req(enum("period_matching", "loan_interest_allocation", "deposit_recognition_proviso")),
                "apply": req(BOOL),
            }
        ),
    ),
    LedgerKind(
        "選択.円換算の方法", "C-11", "送金額の円換算の方法", _ONE, WHEN_TAX_YEAR,
        obj({"method": req(enum("ttm", "ttb", "tts")), "institution": opt(NAME)}),
    ),
    LedgerKind(
        "選択.損失申告と繰戻し", "C-12", "損失申告をするか・純損失を繰り戻すか", _ONE, WHEN_TAX_YEAR,
        obj(
            {
                "file_loss_return": req(BOOL),
                "carryback_amount": opt(YEN),
                # 補（2026-11-11）：前々年分へ繰り戻す純損失の額（所法140⑤・141④：事業の廃止等・死亡の年の前年の純損失。rules/income_totals/README.md IT-13）
                "second_prior_year_carryback_amount": opt(YEN),
            }
        ),
    ),
    LedgerKind("選択.還付申告", "C-13", "還付申告をするか", _ONE, WHEN_TAX_YEAR, BOOL),
    # 補（2026-11-12）：その年分の確定申告書・修正申告書・更正請求書に特定支出控除の適用を受ける旨と特定支出の額の合計額を記載し、
    # 明細書と証明書を添付するか（所得税法第57条の2第3項：rules/kyuyo/README.md KY-11）
    LedgerKind("選択.特定支出控除", "補（kyuyo KY-11）", "所得税の申告書等で特定支出控除の適用を受けるか", _ONE, WHEN_TAX_YEAR, BOOL),
    LedgerKind(
        "選択.住民税の申告", "C-14", "住民税の申告・徴収方法", _ONE, WHEN_FISCAL_YEAR,
        obj(
            {
                "file_resident_tax_return": opt(BOOL),
                "collection_method_other_income": opt(enum("special_collection", "ordinary_collection")),
                "specific_expense_deduction": opt(BOOL),
            }
        ),
    ),
    LedgerKind(
        "選択.ワンストップ特例", "C-15", "寄附金税額控除に係る申告特例", _ONE, WHEN_TAX_YEAR,
        obj({"apply": req(BOOL), "municipality_codes": opt(array(MUNI))}),
    ),
    LedgerKind("選択.夫婦共同扶養の届出", "C-16", "夫婦共同扶養の届出", _pair("person", "insured"), WHEN_PERIOD, BOOL),
    LedgerKind(
        "選択.国民年金の免除の申請", "C-17", "国民年金の免除等を申請するか", _ONE, WHEN_FISCAL_YEAR,
        obj({"apply": req(BOOL), "exemption_type": opt(NPI_EXEMPTION_TYPE)}),
    ),
    LedgerKind(
        "選択.様式への割当て", "C-18", "決算書・内訳書の科目の割当て",
        {"person": req(PERSON), "business_id": opt(kind_ref("business"))}, WHEN_TAX_YEAR,
        obj({"mappings": req(array(obj({"expense_category": req(CODE), "form_item": req(CODE)})))}),
    ),
    LedgerKind("選択.被扶養者の届出", "C-20", "誰の健保・共済の被扶養者として届け出るか", _pair("person", "insured"), WHEN_PERIOD, BOOL),
    # 補（2026-11-12）：所得控除を上場株式等に係る配当所得等の金額と譲渡所得等の金額のどちらから控除するか（措通31・32共−4 の
    # ただし書の納税者の選択。dividends_first が通達の本文の順：rules/tax/README.md TX-19）
    LedgerKind(
        "選択.所得控除の順序", "補（tax TX-19）", "所得控除を上場株式等の配当所得等・譲渡所得等のどちらから先に控除するか", _ONE, WHEN_TAX_YEAR,
        enum("dividends_first", "transfers_first"),
    ),
)

# 中間表現の根の配列（persons のほか）と、その要素の種類
RECORD_SECTIONS: dict[str, tuple[RecordKind, ...]] = {
    "relations": RELATION_KINDS,
    "residences": RESIDENCE_KINDS,
    "insurance_memberships": MEMBERSHIP_KINDS,
    "facts": FACT_KINDS,
    "assets": ASSET_KINDS,
    "filed_documents": FILED_DOCUMENT_KINDS,
}
LEDGER_SECTIONS: dict[str, tuple[LedgerKind, ...]] = {
    "judgments": JUDGMENT_KINDS,
    "choices": CHOICE_KINDS,
}

# 計算に使わない種類（2026-11-12。README §6.4）：記録してよいが、判定コアのどの規則モジュールも使わない種類と、書類の種別。
# 判定コアはこれらを「未対応」の対象外にしない約束（共有の担当への申し送り：okura_core.scope.input_scope）。
# 理由と根拠は README §6.4。packages/core/tests/test_vocabulary_coverage.py が README の表と突き合わせる。
NOT_USED_IN_CALCULATION: frozenset[str] = frozenset({"care_level", "見込み.将来の所得・加入"})
#: 種類の中の書類の種別などで、計算に使わないもの：(kind, attributes の欄, 値)。
NOT_USED_IN_CALCULATION_VALUES: frozenset[tuple[str, str, str]] = frozenset(
    {("filed_document", "document_type", "basic_deduction_declaration")}
)
