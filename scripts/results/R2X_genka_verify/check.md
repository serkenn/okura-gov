# R2X genka verify check（自動生成。scripts/R2X_genka_verify.py check）

## 件数

- law: 287 件、うち不一致 1 件
- same: 55 件、うち不一致 1 件
- revs: 24 件、うち不一致 0 件
- lookups: 8 件、うち不一致 0 件
- rev198: 7 件、うち不一致 0 件
- taiyo_revs: 3 件、うち不一致 0 件
- nta: 36 件、うち不一致 0 件
- nta_meta: 23 件、うち不一致 0 件
- beppyo: 18 件、うち不一致 0 件

## 不一致（ok=false）

- law: {"id": "L70", "src": "PS§3.2 措令5の3⑧", "law": "sochi-rei", "asof": "2025-12-31", "path": "5_3/8", "ok": false, "missing": ["法第十条第八項第六号に規定する政令で定めるものは、常時使用する従業員の数が千人以下の個人とする。"], "negated": false}
- same: {"id": "D49", "src": "M§4 耐令2 は変わる", "a": "2025-12-31", "b": "2026-12-31", "path": "2", "expect_same": false, "same": true, "ok": false}

## 計算の再現

```json
{
 "beppyo8": {
  "title": "別表第八",
  "count": 99,
  "years": [
   2,
   100
  ],
  "same_r7_r8": true,
  "doc_values_match": true,
  "ceil_property_mismatch": []
 },
 "beppyo7": {
  "title": "別表第七",
  "6": "83/500",
  "22": "23/500",
  "33": "31/1000"
 },
 "months_check": {
  "days": 730,
  "mismatch": []
 },
 "E1_2026": [
  {
   "year": 2026,
   "m": 6,
   "dep": 30000,
   "biz": "18000",
   "end_A": 210000,
   "end_B": "222000"
  },
  {
   "year": 2027,
   "m": 12,
   "dep": 60000,
   "biz": "36000",
   "end_A": 150000,
   "end_B": "186000"
  },
  {
   "year": 2028,
   "m": 12,
   "dep": 60000,
   "biz": "36000",
   "end_A": 90000,
   "end_B": "150000"
  },
  {
   "year": 2029,
   "m": 12,
   "dep": 60000,
   "biz": "36000",
   "end_A": 30000,
   "end_B": "114000"
  },
  {
   "year": 2030,
   "m": 12,
   "dep": 29999,
   "biz": "89997/5",
   "end_A": 1,
   "end_B": "480003/5"
  }
 ],
 "I4A_2025": [
  {
   "year": 2025,
   "m": 6,
   "dep": 30000,
   "biz": "18000",
   "end_A": 210000,
   "end_B": "222000"
  },
  {
   "year": 2026,
   "m": 12,
   "dep": 60000,
   "biz": "36000",
   "end_A": 150000,
   "end_B": "186000"
  },
  {
   "year": 2027,
   "m": 12,
   "dep": 60000,
   "biz": "36000",
   "end_A": 90000,
   "end_B": "150000"
  },
  {
   "year": 2028,
   "m": 12,
   "dep": 60000,
   "biz": "36000",
   "end_A": 30000,
   "end_B": "114000"
  },
  {
   "year": 2029,
   "m": 12,
   "dep": 29999,
   "biz": "89997/5",
   "end_A": 1,
   "end_B": "480003/5"
  }
 ],
 "E2_2026": {
  "floor": [
   [
    2026,
    5,
    "617285/48",
    12860
   ],
   [
    2027,
    12,
    "123457/4",
    30864
   ],
   [
    2028,
    12,
    "123457/4",
    30864
   ],
   [
    2029,
    12,
    "123457/4",
    30864
   ],
   [
    2030,
    12,
    "123457/4",
    18004
   ]
  ],
  "ceil": [
   [
    2026,
    5,
    "617285/48",
    12861
   ],
   [
    2027,
    12,
    "123457/4",
    30865
   ],
   [
    2028,
    12,
    "123457/4",
    30865
   ],
   [
    2029,
    12,
    "123457/4",
    30865
   ],
   [
    2030,
    12,
    "123457/4",
    18000
   ]
  ]
 },
 "I2_2025": {
  "floor": [
   [
    2025,
    5,
    "617285/48",
    12860
   ],
   [
    2026,
    12,
    "123457/4",
    30864
   ],
   [
    2027,
    12,
    "123457/4",
    30864
   ],
   [
    2028,
    12,
    "123457/4",
    30864
   ],
   [
    2029,
    12,
    "123457/4",
    18004
   ]
  ],
  "ceil": [
   [
    2025,
    5,
    "617285/48",
    12861
   ],
   [
    2026,
    12,
    "123457/4",
    30865
   ],
   [
    2027,
    12,
    "123457/4",
    30865
   ],
   [
    2028,
    12,
    "123457/4",
    30865
   ],
   [
    2029,
    12,
    "123457/4",
    18000
   ]
  ]
 },
 "E3": [
  [
   2025,
   1,
   5000,
   295000
  ],
  [
   2026,
   12,
   60000,
   235000
  ],
  [
   2027,
   12,
   60000,
   175000
  ],
  [
   2028,
   12,
   60000,
   115000
  ],
  [
   2029,
   12,
   60000,
   55000
  ],
  [
   2030,
   12,
   55000,
   0
  ]
 ],
 "E4_I3": {
  "150000/3": "50000",
  "100001/3": "100001/3",
  "floor_x3": 99999,
  "residual_in_3rd": 33335,
  "ceil_ceil_rest": [
   33334,
   33334,
   33333
  ]
 },
 "E5": {
  "1": "250000",
  "5": "1250000",
  "7": "1750000",
  "12": "3000000"
 },
 "I1_9_months_2026-06-10": 7,
 "I1": {
  "#2": "100000/3",
  "#3": "25000/3",
  "#4": "65625",
  "#6": "75000",
  "#8": "50000"
 },
 "E6": {
  "correct": {
   "keijo": "0",
   "tanki": "0",
   "choki": "0",
   "ichiji": "100000",
   "sanrin": "0",
   "taishoku": "0",
   "junsonshitsu": "0",
   "soshotoku": "50000"
  },
  "naive": "0"
 },
 "E7": "400000",
 "E8_I7": {
  "r7_salary_income(1,350,000-650,000)": 700000,
  "r8_salary_income(1,440,000-740,000)": 700000,
  "jigyo": 500000,
  "zatsu": 700000
 },
 "E9_2026": {
  "y15": 6,
  "full_months": 25,
  "years": 2,
  "genka": "59760",
  "rem": "140240",
  "rows": [
   [
    2026,
    6,
    25000,
    115240
   ],
   [
    2027,
    12,
    50000,
    65240
   ],
   [
    2028,
    12,
    50000,
    15240
   ],
   [
    2029,
    12,
    15239,
    1
   ]
  ]
 },
 "I5_2025": {
  "y15": 6,
  "full_months": 25,
  "years": 2,
  "genka": "59760",
  "rem": "140240",
  "rows": [
   [
    2025,
    6,
    25000,
    115240
   ],
   [
    2026,
    12,
    50000,
    65240
   ],
   [
    2027,
    12,
    50000,
    15240
   ],
   [
    2028,
    12,
    15239,
    1
   ]
  ]
 },
 "04_17": {
  "18y": "15066000",
  "13y_alt": "10881000",
  "r7_dep_11m": "1138500"
 },
 "I6": {
  "dep_2026": "25000",
  "rem_2026_01_01": 100000,
  "loss": "75000",
  "jigyo": "-90000",
  "zatsu_limit": "-15000",
  "zatsu_loss_allowed": "0",
  "zatsu": "-15000"
 },
 "I8": {
  "junsonshitsu": 150000,
  "carry_white": 100000
 },
 "I9": {
  "no_dep_deduct": 1450000,
  "dep_deduct": 1250000
 },
 "disposal_equiv": {
  "cases": 153791,
  "mismatch": 0,
  "doc_cases_41x11x16": 7216
 }
}
```

## 文書の検査

```json
{
 "PS": {
  "urls": 18,
  "scope_refs": [],
  "personal_terms": []
 },
 "M": {
  "urls": 6,
  "scope_refs": [],
  "personal_terms": []
 },
 "H": {
  "urls": 0,
  "scope_refs": [
   "SCOPE §4.1",
   "SCOPE §4.2",
   "SCOPE §5-5",
   "SCOPE §7"
  ],
  "personal_terms": []
 },
 "I": {
  "urls": 0,
  "scope_refs": [],
  "personal_terms": []
 },
 "SCOPE_headings": [
  "## 1.",
  "## 2.",
  "## 3.",
  "## 4.",
  "## 5.",
  "### 5.1",
  "### 5.2",
  "### 5.3",
  "### 5.4",
  "### 5.5",
  "## 6.",
  "## 7.",
  "## 8.",
  "## 9.",
  "### 9.1",
  "### 9.2",
  "## 10."
 ],
 "refs": {
  "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md": {
   "## 1.": true,
   "### 1.3": true,
   "## 6.": true,
   "## 7.": true,
   "### 7.4": true,
   "## 11.": true
  },
  "docs/public-sources/20261109_R1-laws_income-tax.md": {
   "## 4.": true
  },
  "docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md": {
   "### 1.2": true
  },
  "docs/hypotheses/20261109_impl-prep_jigyo-calculation-model.md": {
   "## H3": true,
   "## H6": true,
   "## H10": true
  },
  "docs/hypotheses/20261109_impl-prep_kenpo-input-facts.md": {
   "## HK0": true,
   "## HK1": true,
   "## HK2": true
  },
  "docs/hypotheses/20261109_impl-prep_kyuyo-hypotheses.md": {
   "## H1": true
  }
 }
}
```

## その他

```json
{
 "robots": {
  "sha256": "a5f4e421e5bb2b20563fa568d7ee4d7c6a41afa72ef8bb96cd35510ebe6d8528",
  "all_allowed": true,
  "same_as_author": true
 },
 "pdf_flags": {
  "pdf_037": {
   "Encrypt": true,
   "ToUnicode": 0
  },
  "pdf_003": {
   "Encrypt": true,
   "ToUnicode": 31
  },
  "pdf_034": {
   "Encrypt": true,
   "ToUnicode": 6
  },
  "pdf_kichou09": {
   "Encrypt": true,
   "ToUnicode": 65
  }
 },
 "kichou09_link_texts": [
  "白色申告者の決算の手引き（一般用）（PDF/7,387KB）",
  "令和７年分白色申告者の決算の手引き（一般用）（PDF/7,138KB）"
 ],
 "kichou09_meta": {
  "last_modified": "Fri, 09 Oct 2026 01:00:02 GMT",
  "bytes": 7563616,
  "KiB": 7386
 },
 "suppl198": [
  [
   "平成一八年三月三一日政令第一二四号",
   "14"
  ],
  [
   "平成一九年三月三〇日政令第八二号",
   "19"
  ],
  [
   "平成二六年三月三一日政令第一三七号",
   "5"
  ],
  [
   "平成三〇年三月三一日政令第一三一号",
   "27"
  ],
  [
   "令和八年三月三一日政令第九三号",
   "1"
  ]
 ],
 "beppyo5": {
  "2025-12-31": [
   [
    "651,000",
    "1,900,000",
    "給与等の金額から650,000円を控除した金額"
   ]
  ],
  "2026-12-31": [
   [
    "691,000",
    "2,026,000",
    "給与等の金額から690,000円を控除した金額"
   ]
  ]
 },
 "rev198_extra_in_range": [],
 "taiyo_revs_count_2025_2030": 3,
 "author_pdf_hashes": {
  "aoiro_kessan_kakikata_r07": {
   "exists": true,
   "matches_record": true
  },
  "sonshitsu_tebiki_r07": {
   "exists": true,
   "matches_record": true
  },
  "ta_2100_01": {
   "exists": true,
   "matches_record": true
  },
  "ta_2100_02": {
   "exists": true,
   "matches_record": true
  },
  "shushi_ippan_r07": {
   "exists": true,
   "matches_record": true
  },
  "shushi_ippan_kakikata_r07": {
   "exists": true,
   "matches_record": true
  },
  "kanai_keisansho_r07": {
   "exists": true,
   "matches_record": true
  },
  "kanai_kakikata_r07": {
   "exists": true,
   "matches_record": true
  },
  "kessan_tebiki_shiro_r07": {
   "exists": true,
   "matches_record": true
  },
  "kicho_shikata_jigyo": {
   "exists": true,
   "matches_record": true
  }
 }
}
```
