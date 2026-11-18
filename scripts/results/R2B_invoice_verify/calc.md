# R2B invoice 独立検証：例の再計算（仕訳を積み上げる別の実装）

```
{
 "basic": {
  "komi_filed": {
   "2025": 770000,
   "2026": 750000,
   "2027": -20000
  },
  "komi_accrued": {
   "2025": 750000,
   "2026": 750000,
   "2027": 0
  },
  "nuki": {
   "2025": 750000,
   "2026": 750000,
   "2027": 0
  },
  "menzei": {
   "2025": 770000,
   "2026": 770000,
   "2027": 0
  }
 },
 "I1": {
  "komi_filed": 583000,
  "komi_accrued": 571000,
  "nuki": 571000,
  "menzei": 583000
 },
 "I1_limit": 580000,
 "I1_within": {
  "komi_filed": false,
  "komi_accrued": true,
  "nuki": true,
  "menzei": false
 },
 "partial": {
  "10000": 972000,
  "8000": 972000,
  "7000": 972000,
  "0": 972000,
  "komi_accrued": 972000
 },
 "refund": {
  "komi_filed": {
   "2026": -1650000,
   "2027": 150000
  },
  "komi_accrued": {
   "2026": -1500000,
   "2027": 0
  },
  "nuki": {
   "2026": -1500000,
   "2027": 0
  }
 },
 "I3": [
  {
   "price": 107000,
   "case": "登録",
   "karibarai_exact": "107000/11",
   "cost_floor": 97273,
   "cost_round": 97273,
   "under_100k": [
    true,
    true
   ]
  },
  {
   "price": 107000,
   "case": "80%",
   "karibarai_exact": "85600/11",
   "cost_floor": 99219,
   "cost_round": 99218,
   "under_100k": [
    true,
    true
   ]
  },
  {
   "price": 107000,
   "case": "70%",
   "karibarai_exact": "74900/11",
   "cost_floor": 100191,
   "cost_round": 100191,
   "under_100k": [
    false,
    false
   ]
  },
  {
   "price": 108900,
   "case": "登録",
   "karibarai_exact": "9900",
   "cost_floor": 99000,
   "cost_round": 99000,
   "under_100k": [
    true,
    true
   ]
  },
  {
   "price": 108900,
   "case": "80%",
   "karibarai_exact": "7920",
   "cost_floor": 100980,
   "cost_round": 100980,
   "under_100k": [
    false,
    false
   ]
  },
  {
   "price": 108900,
   "case": "70%",
   "karibarai_exact": "6930",
   "cost_floor": 101970,
   "cost_round": 101970,
   "under_100k": [
    false,
    false
   ]
  }
 ],
 "depr": {
  "komi_accrued": {
   "2026": 970000,
   "2027": 970000,
   "2028": 970000
  },
  "nuki": {
   "2026": 950000,
   "2027": 980000,
   "2028": 980000
  }
 }
}
```