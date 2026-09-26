"""提醒信（api/payment-reminders.js、api/signed-slip-reminders.js 的純函式）的差異測試輸入向量。"""
from datetime import date, timedelta

from .vectors import R

WS = ["", " ", "\t", "\xa0", "　", "﻿", " ", "\x1c", "​", "\n"]
EMAILS = ["ae@tw-insure.com", "AE@TW-Insure.com", " ae@tw-insure.com ", "a@b.c", "a@b", "a b@c.d", "a@b c.d", "@b.c", "a@.c", "a@b.",
          "a@@b.c", "ｅ@ｆ.ｇ", "x@example.com", "x@test", "", None, 123, "a@b.c　", "﻿a@b.c", "a\xa0b@c.d", "a@b.c​",
          "İ@b.c", "a@b.co.uk", "first.last+tag@sub.domain.tw"]
NAMES = ["ZZ AE", "zz ae", " ZZ AE ", "ZZ\xa0AE", "ZZ AE　", "İstanbul", "istanbul", "ZZ Other", "", None, "Ǆ", "ǆ", "ß", "SS"]
KINDS = ["seven_days_before", "due_today", "weekly_overdue", "x", "", None]
AMOUNTS = [100, 1234.5, 0.005, 1.005, 2.675, 1234567.895, 0.015, 1e21, 999999999.995, 12.345, "1,000", "abc", None, 0, 7.125, 0.004, 3]
LABELS = ["Installment 1", "Full", "第一期", "<b>x</b>", "a&b", "'q'", None]


def _person(name=None, email=None, sup_name=None, sup_email=None, role=None):
    row = {"id": R.randint(1, 50)}
    for key, value in (("name", name), ("email", email), ("supervisor_name", sup_name), ("supervisor_email", sup_email), ("role_code", role)):
        if value is not None or R.random() < 0.3:
            row[key] = value
    return row


def _roster():
    people = []
    for _ in range(R.randint(0, 5)):
        people.append(_person(R.choice(NAMES), R.choice(EMAILS), R.choice(["Boss", "", " ", None, "主管"]), R.choice(EMAILS),
                              R.choice(["sales", "accounting", "ACCOUNTING", "accounting_manager", "Accounting_Manager ", "admin", None, ""])))
    return people


def _case():
    c = {"id": R.randint(1, 999)}
    r = R.random()
    if r < 0.6:
        c["twRef"] = R.choice(["TWPAR2603001", "TW<&>1", "", 0])
    c["ae"] = R.choice(NAMES)
    c["policyFrom"] = R.choice(["2026-03-01", "2026-02-30", "", "x", None])
    return c


def _item():
    it = {"installmentLabel": R.choice(LABELS), "partyName": R.choice(["Cedant", "ZZ Re Alpha", "晶華", "<Re>"]),
          "currency": R.choice(["USD", "TWD", "", None]), "outstanding": R.choice(AMOUNTS),
          "dueDate": R.choice(["2026-10-01", "2026-09-26", "", "2026-02-30", None])}
    if R.random() < 0.1:
        del it["installmentLabel"]
    return it


def build(count_each):
    vectors = []
    add = vectors.append
    for text in [None, "", "<a href='x'>&\"</a>", "中文", 0, False, 12.5, "&amp;"]:
        add({"fn": "payEsc", "args": [text]})
        add({"fn": "slipEscapeHtml", "args": [text]})
    for e in EMAILS + [w + "a@b.c" + w2 for w in WS for w2 in WS[:4]]:
        add({"fn": "payValidEmail", "args": [e]})
        add({"fn": "slipValidEmailApi", "args": [e]})
    for k in KINDS:
        add({"fn": "payLabel", "args": [k]})
    for _ in range(count_each):
        add({"fn": "payMessage", "args": [_case(), R.choice(KINDS[:3]), [_item() for _ in range(R.randint(0, 4))]]})
    for amount in AMOUNTS:
        add({"fn": "payMessage", "args": [{"id": 7, "twRef": "TW1"}, "due_today", [{"installmentLabel": "I1", "partyName": "P", "currency": "USD",
                                                                                   "outstanding": amount, "dueDate": "2026-10-01"}]]})
    for _ in range(count_each):
        roster = _roster()
        case = _case()
        if roster and R.random() < 0.5:
            case["ae"] = R.choice(roster).get("name")
        fin = R.choice([[], ["fin@tw-insure.com"], ["fin@tw-insure.com", "ae@tw-insure.com"], ["f1@a.b", "f2@a.b"]])
        add({"fn": "payResolveRecipients", "args": [case, roster, fin]})
        add({"fn": "slipContactFor", "args": [case, roster]})
        add({"fn": "payFinanceEmails", "args": [roster]})
    # 聯絡資料完整的情境（多產生幾組「會寄出」的結果）
    for _ in range(count_each):
        name = R.choice(["ZZ AE", "Amy Lin", "林小明"])
        roster = [_person(name, R.choice(EMAILS[:4] + EMAILS[-2:]), "Boss", R.choice(["boss@tw-insure.com", "BOSS@tw-insure.com", "ae@tw-insure.com"]), "sales"),
                  _person("Fin", "fin@tw-insure.com", None, None, "accounting")]
        case = {"id": 1, "ae": R.choice([name, name.upper(), " " + name, name + "\xa0"])}
        add({"fn": "payResolveRecipients", "args": [case, roster, ["fin@tw-insure.com"]]})
        add({"fn": "slipContactFor", "args": [case, roster]})
    today0 = date(2026, 9, 26)
    for _ in range(count_each * 3):
        today = today0 + timedelta(days=R.randint(-5, 5))
        due = today + timedelta(days=R.choice([8, 7, 6, 1, 0, -1, -6, -7, -8, -13, -14, -15, -21, -28, -30]))
        success = {}
        for kind in ("seven_days_before", "due_today", "weekly_overdue"):
            if R.random() < 0.3:
                success[kind] = (due + timedelta(days=R.choice([-7, -1, 0, 7, 14]))).isoformat()
            elif R.random() < 0.2:
                success[kind] = ""
        item = {"dueDate": R.choice([due.isoformat()] * 8 + ["", "2026-02-30", None]), "outstanding": R.choice([100, 0.004, 0.005, 0, -5, "50", "x", None])}
        if R.random() < 0.05:
            item = R.choice([None, {}, "x"])
        add({"fn": "payDueKind", "args": [item, R.choice([today.isoformat()] * 9 + ["2026-02-30"]), success]})
    for _ in range(count_each):
        case = _case()
        missing = R.sample(["ZZ Re Alpha", "ZZ Re Beta (Facility)", "<Re & Co>", "再保甲"], R.randint(0, 3))
        add({"fn": "slipReminderMessage", "args": [case, {"missing": missing, "daysSinceEffective": R.choice([60, 61, 209, 60.5])},
                                                   {"aeEmail": "a@b.c", "supervisorName": R.choice(["Boss", "<主管>", "O'Neil"]), "supervisorEmail": "s@b.c"}]})
    return vectors
