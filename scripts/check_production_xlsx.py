"""核對 Production Report 的 Excel 產生程式：
  1. frontend/alpha-reference/production-xlsx.js 必須是 Alpha 的原樣副本（雜湊固定）。
  2. frontend/src/alpha/production-xlsx.js（VM 實際使用的版本）必須剛好等於「原檔 + 下面這幾處已知修改」。
VM 的偏離只有「多一欄 First Policy No」，所以任何多改或少改都會在這裡被擋下。"""
import hashlib
import sys

ALPHA_SHA256 = "256db219f84aa2e56c9e1a36c81541c1fe7a560b0a0f9054e2253773808dcf59"
VM_CHANGES = [  # (Alpha 原文, VM 改成)；每一處在原檔中都必須剛好出現一次
    ("'Remark','Tranx Date'];", "'Remark','Tranx Date','First Policy No'];"),
    ("dateSlashes(row.tranxDate)][index];", "dateSlashes(row.tranxDate),row.firstPolicyNo][index];"),
    ("[13,14].includes(i)?18:14", "[13,14,17].includes(i)?18:14"),
    ('<autoFilter ref="A1:Q', '<autoFilter ref="A1:R'),
]

original = open("frontend/alpha-reference/production-xlsx.js", "rb").read()
if hashlib.sha256(original).hexdigest() != ALPHA_SHA256:
    sys.exit("frontend/alpha-reference/production-xlsx.js 與 Alpha 的 public/production-xlsx.js 不同，請勿修改")
expected = original.decode("utf-8")
for before, after in VM_CHANGES:
    if expected.count(before) != 1:
        sys.exit(f"Alpha 原檔中找不到唯一的 {before!r}")
    expected = expected.replace(before, after)
if open("frontend/src/alpha/production-xlsx.js", "rb").read().decode("utf-8") != expected:
    sys.exit("frontend/src/alpha/production-xlsx.js 不是「Alpha 原檔 + 已記錄的 First Policy No 修改」，請對照 scripts/check_production_xlsx.py")
