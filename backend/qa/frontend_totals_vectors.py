"""產生案件資料並用後端 totals.py 算出合計，供與前端 src/alpha/caseCalculations.js 比對（scripts/run_qa.sh totals）。"""
import json
import sys

from cases.calc.totals import case_totals
from qa.calc import vectors

count = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
cases = [vectors.case_data() for _ in range(count)]
print(json.dumps([{"case": c, "totals": case_totals(c)} for c in cases], allow_nan=False))
