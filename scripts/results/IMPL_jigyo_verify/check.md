# IMPL_jigyo_verify check の結果

主張の定義：scripts/IMPL_jigyo_verify.py の CLAIMS

## 件数

- law: 全 250 件、一致 250、不一致 0、未確認 0
- eq: 全 53 件、一致 53、不一致 0、未確認 0
- rev: 全 20 件、一致 20、不一致 0、未確認 0
- lawnum: 全 6 件、一致 6、不一致 0、未確認 0
- nta: 全 34 件、一致 34、不一致 0、未確認 0
- links: 全 3 件、一致 3、不一致 0、未確認 0

## 再計算の一致

```json
{
 "C9": true,
 "C10": true,
 "C10_example": true,
 "C11": true,
 "I1": true,
 "I2": true,
 "I3": true,
 "I4A": true,
 "I5": true,
 "I7": true,
 "H3_doc_claim_max_550000_holds(偽なら仮説H3の誤り)": false
}
```

## 不一致

```json
{
 "law": [],
 "eq": [],
 "rev": [],
 "lawnum": [],
 "nta": [],
 "links": []
}
```

## 再計算の詳細

```json
{
 "C9": {
  "fuyo_from_law": {
   "7": 580000,
   "8": 620000
  },
  "kanai_from_law": {
   "7": 650000,
   "8": 690000
  },
  "upper_for_fuyo": {
   "7": 1230000,
   "8": 1310000
  },
  "upper_for_no_tax_using_TA_kiso": {
   "7": 1600000,
   "8": 1730000
  },
  "doc_claims": {
   "upper_for_fuyo": {
    "7": 1230000,
    "8": 1310000
   },
   "upper_for_no_tax": {
    "7": 1600000,
    "8": 1730000
   }
  },
  "ok": true
 },
 "beppyo5": {
  "R7": {
   "first_row": [
    "６５１，０００円未満",
    "０"
   ],
   "second_row": [
    "６５１，０００",
    "１，９００，０００",
    "給与等の金額から６５０，０００円を控除した金額"
   ],
   "parsed": [
    651000,
    1900000,
    650000
   ]
  },
  "R8": {
   "first_row": [
    "６９１，０００円未満",
    "０"
   ],
   "second_row": [
    "６９１，０００",
    "２，０２６，０００",
    "給与等の金額から６９０，０００円を控除した金額"
   ],
   "parsed": [
    691000,
    2026000,
    690000
   ]
  }
 },
 "C10": {
  "grid": "事業収入0〜100万(5万)×事業経費0〜70万(5万)×雑収入0〜100万(5万)×雑経費0〜30万(10万)×給与0/30万/60万、特例額65万",
  "all_combos": 79380,
  "skipped_no_income": 180,
  "not_eligible": 54120,
  "skipped_Rb0_Eb_pos": 960,
  "compared": 24120,
  "equal": 21524,
  "diff": 2596,
  "diff_with_Eb_le_Rb": 0,
  "diff_examples": [
   {
    "Rb": 50000,
    "Eb": 100000,
    "Rm": 300000,
    "Em": 0,
    "sal": 300000,
    "seirei": [
     50000,
     250000
    ],
    "sheet": [
     100000,
     250000
    ]
   },
   {
    "Rb": 50000,
    "Eb": 100000,
    "Rm": 300000,
    "Em": 100000,
    "sal": 300000,
    "seirei": [
     50000,
     250000
    ],
    "sheet": [
     100000,
     250000
    ]
   },
   {
    "Rb": 50000,
    "Eb": 100000,
    "Rm": 300000,
    "Em": 200000,
    "sal": 300000,
    "seirei": [
     50000,
     250000
    ],
    "sheet": [
     100000,
     250000
    ]
   }
  ],
  "if_Rb0_Eb_pos_included": {
   "compared": 960,
   "diff": 632
  },
  "doc_claims": {
   "compared": 24120,
   "equal": 21524,
   "diff": 2596,
   "diff_only_when_Eb_gt_Rb": true
  },
  "ok": true,
  "doc_example_Rb5_Eb10_Rm30_sal30": {
   "seirei": [
    50000,
    250000
   ],
   "sheet": [
    100000,
    250000
   ],
   "ok": true
  }
 },
 "C11": [
  {
   "salary": 0,
   "R7_literal": 650000,
   "R7_sheet": 650000,
   "R8_sochi29_4": 690000,
   "R8_sheet": 690000,
   "ok": true
  },
  {
   "salary": 100000,
   "R7_literal": 0,
   "R7_sheet": 550000,
   "R8_sochi29_4": 590000,
   "R8_sheet": 590000,
   "ok": true
  },
  {
   "salary": 300000,
   "R7_literal": 0,
   "R7_sheet": 350000,
   "R8_sochi29_4": 390000,
   "R8_sheet": 390000,
   "ok": true
  },
  {
   "salary": 640000,
   "R7_literal": 0,
   "R7_sheet": 10000,
   "R8_sochi29_4": 50000,
   "R8_sheet": 50000,
   "ok": true
  },
  {
   "salary": 650000,
   "R7_literal": 0,
   "R7_sheet": 0,
   "R8_sochi29_4": 40000,
   "R8_sheet": 40000,
   "ok": true
  },
  {
   "salary": 690000,
   "R7_literal": 0,
   "R7_sheet": 0,
   "R8_sochi29_4": 0,
   "R8_sheet": 0,
   "ok": true
  },
  {
   "salary": 700000,
   "R7_literal": 0,
   "R7_sheet": 0,
   "R8_sochi29_4": 0,
   "R8_sheet": 0,
   "ok": true
  },
  {
   "salary": 740000,
   "R7_literal": 0,
   "R7_sheet": 0,
   "R8_sochi29_4": 0,
   "R8_sheet": 0,
   "ok": true
  }
 ],
 "inferences": {
  "I1": [
   {
    "year": 7,
    "R": 1230000,
    "income": 580000,
    "fuyo": true,
    "ok": true
   },
   {
    "year": 7,
    "R": 1230001,
    "income": 580001,
    "fuyo": false,
    "ok": true
   },
   {
    "year": 8,
    "R": 1310000,
    "income": 620000,
    "fuyo": true,
    "ok": true
   },
   {
    "year": 8,
    "R": 1310001,
    "income": 620001,
    "fuyo": false,
    "ok": true
   },
   {
    "year": 7,
    "R": 1600000,
    "income": 950000,
    "fuyo": false,
    "ok": true
   }
  ],
  "I2": {
   "kyuyo_shotoku": 0,
   "sheet": {
    "F": 350000,
    "zatsu": 450000,
    "total": 450000
   },
   "literal": {
    "F": 0,
    "zatsu": 750000,
    "total": 750000
   },
   "ok": true
  },
  "I3": {
   "kyuyo_shotoku": 0,
   "F": 390000,
   "zatsu": 410000,
   "total": 410000,
   "ok": true
  },
  "I4A": {
   "seirei": [
    300000,
    200000
   ],
   "sheet": [
    300000,
    200000
   ],
   "sheet_v5": 600000,
   "sheet_v6": 450000,
   "ok": true
  },
  "I5": {
   "40%": 48000,
   "60%": 72000,
   "ok": true
  },
  "I7": [
   {
    "year": 7,
    "salary": 1000000,
    "prize": 700000,
    "got": [
     350000,
     200000,
     100000,
     450000,
     true
    ],
    "ok": true
   },
   {
    "year": 8,
    "salary": 1000000,
    "prize": 700000,
    "got": [
     260000,
     200000,
     100000,
     360000,
     true
    ],
    "ok": true
   },
   {
    "year": 7,
    "salary": 1000000,
    "prize": 400000,
    "got": [
     350000,
     0,
     0,
     350000,
     true
    ],
    "ok": true
   },
   {
    "year": 7,
    "salary": 1000000,
    "prize": 1800000,
    "got": [
     350000,
     1300000,
     650000,
     1000000,
     false
    ],
    "ok": true
   }
  ],
  "I1_age_at_year_end(2008-05-01生)": {
   "2025-12-31": 17,
   "2026-12-31": 18
  }
 },
 "H3_aoiro_special_deduction": {
  "sochi25_2_amounts_R7": [
   100000,
   550000,
   650000
  ],
  "max_R7_R8": 650000,
  "doc_claim_max": 550000,
  "ok": false
 },
 "gap_fill": {
  "sochi27_amounts_past": {
   "2020-12-31": [
    550000
   ],
   "2024-12-31": [
    550000
   ]
  },
  "sochi27_revision_past": {
   "2020-12-31": "332AC0000000026_20201228_502AC0000000068",
   "2024-12-31": "332AC0000000026_20241108_506AC0000000008"
  },
  "shotoku151_first_new_text": [
   "340AC0000000033_20260101_505AC0000000003",
   "340AC0000000033_20260101_507AC0000000013"
  ],
  "shotoku151_last_old_text": [
   "340AC0000000033_20251218_507AC0000000013"
  ],
  "R5law3_suppl_1_1_6": "六次に掲げる規定令和八年一月一日イ第一条中所得税法第百五十一条の改正規定、同法第二百二十九条の改正規定及び同法第二百三十条の改正規定並びに附則第五条及び第十条の規定",
  "R5law3_suppl_5": "（青色申告の取りやめ等に関する経過措置）第五条新所得税法第百五十一条（所得税法第百六十六条において準用する場合を含む。）の規定は、令和八年分以後の所得税につき青色申告書の提出をやめようとする場合について適用し、令和七年分以前の所得税につき青色申告書の提出をやめようとする場合については、なお従前の例による。",
  "ok_sochi27_550000": true,
  "ok_151_by_R5law3": true
 },
 "gap_fill_shotoku_ki_47_3_at_2027_01_01": true,
 "tsusoku118": {
  "text": "国税（印紙税及び附帯税を除く。以下この条において同じ。）の課税標準（その税率の適用上課税標準から控除する金額があるときは、これを控除した金額。以下この条において同じ。）を計算する場合において、その額に千円未満の端数があるとき、又はその全額が千円未満であるときは、その端数金額又はその全額を切り捨てる。",
  "revision": {
   "law_revision_id": "337AC0000000066_20251001_505AC0000000053",
   "amendment_law_num": "令和五年法律第五十三号",
   "amendment_enforcement_date": "2025-10-01",
   "current_revision_status": "PreviousEnforced"
  }
 }
}
```
