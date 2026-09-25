"""
記帳計算 - 逐行移植自 Hatchable Alpha 的 lib/accounting.js（v53，含 #3：每一步四捨五入到分）。

與 Alpha 逐位相同是刻意的：差異測試（scripts/run_qa.sh calc）會拿 Alpha 的 JavaScript 與這裡的 Python
餵同一批輸入，要求輸出完全一致。所以這裡刻意保留 JavaScript 的語意（見 jsnum.py），不「順手」改成 Python 的慣用寫法。

案件列表與畫面的合計（case_totals）不在 Alpha 的這個檔案裡，見檔案最後的說明。
"""
from .jsnum import (
    UNDEFINED, at, get, is_array, js_is_integer, js_or, js_string_to_number, js_to_string, js_trim, js_num_str,
    money, strip_ws_regex, is_nullish, WS_CLASS, js_is_finite,
)

import re

_FACILITY_TAG = strip_ws_regex(r"\s*[\[(]Facility[\])]\s*\Z", re.IGNORECASE | re.ASCII)
_WS_RUN = re.compile(WS_CLASS + "+")


def number_or_zero(value):
    """Number(String(value ?? '').replace(/,/g, '')) 不是有限數字就回傳 0"""
    text = "" if is_nullish(value) else js_to_string(value)
    number = js_string_to_number(text.replace(",", ""))
    return number if js_is_finite(number) else 0.0


def strip_facility_tag(value):
    text = js_to_string(js_or(value, ""))
    return js_trim(_FACILITY_TAG.sub("", text, count=1))


def calc_legs_for_reinsurer(case_data, reinsurer):
    order_pct = number_or_zero(get(reinsurer, "sharePct"))
    case_cp = money(number_or_zero(get(case_data, "originalPremium")) * order_pct / 100)
    case_ri = money(case_cp * number_or_zero(get(case_data, "riCommPct")) / 100)
    case_tax = money(case_cp * number_or_zero(get(case_data, "taxPct")) / 100)
    leg1 = money(case_cp - case_ri - case_tax)

    reinsurer_cp = money(number_or_zero(get(reinsurer, "premium")) * order_pct / 100)
    reinsurer_ri = money(reinsurer_cp * number_or_zero(get(reinsurer, "riCommPct")) / 100)
    reinsurer_tax = money(reinsurer_cp * number_or_zero(get(reinsurer, "taxPct")) / 100)
    leg2 = money(reinsurer_cp - reinsurer_ri - reinsurer_tax)
    leg3 = money(leg1 - leg2)
    return {
        "cp": case_cp, "ri": case_ri, "tax": case_tax, "leg1": leg1,
        "reinsurerCp": reinsurer_cp, "reinsurerRi": reinsurer_ri, "reinsurerTax": reinsurer_tax,
        "leg2": leg2, "leg3": leg3, "brokerage": leg3,
    }


def build_premium_transactions(case_data):
    transactions = []
    reinsurers = get(case_data, "reinsurers")
    reinsurers = reinsurers if is_array(reinsurers) else []
    for reinsurer_idx, reinsurer in enumerate(reinsurers):
        legs = calc_legs_for_reinsurer(case_data, reinsurer)
        reinsurer_label = js_or(strip_facility_tag(get(reinsurer, "name")), f"Reinsurer {reinsurer_idx + 1}")
        settlement_label = js_or(js_trim(js_to_string(js_or(get(reinsurer, "foreignBroker"), ""))), reinsurer_label)
        base = [
            {"legType": "Leg 1", "label": f"Receivable — cedant unit owes reinsurance dept ({reinsurer_label})", "amount": legs["leg1"]},
            {"legType": "Leg 2", "label": f"Payable — reinsurance dept owes {settlement_label}", "amount": legs["leg2"]},
            {"legType": "Leg 3", "label": "Payable — reinsurance dept owes broker", "amount": legs["leg3"]},
        ]
        split_parties = get(case_data, "splitParties")
        split = get(case_data, "splitEnabled") is True and is_array(split_parties) and len(split_parties) == 2
        tw_ref = js_to_string(get(case_data, "twRef"))
        via = settlement_label != reinsurer_label
        if split:
            for party_idx, party in enumerate(split_parties):
                suffix = "a" if party_idx == 0 else "b"
                pct = number_or_zero(get(party, "pct"))
                for leg_idx, leg in enumerate(base):
                    party_name = get(party, "name")
                    transactions.append({
                        "txNo": f"{tw_ref}-R{reinsurer_idx + 1}-TX{leg_idx + 1}{suffix}",
                        "legType": f"{leg['legType']}{suffix}",
                        "label": f"{leg['label']} ({js_to_string(js_or(party_name, 'Unassigned'))}, {js_num_str(pct)}%)",
                        "amount": money(leg["amount"] * pct / 100),
                        "splitParty": js_or(party_name, f"Party {suffix.upper()}"),
                        "reinsurer": settlement_label,
                        "viaForeignBroker": via,
                        "settlement": "open",
                        "reinsurerIdx": reinsurer_idx,
                    })
        else:
            for leg_idx, leg in enumerate(base):
                transactions.append({
                    "txNo": f"{tw_ref}-R{reinsurer_idx + 1}-TX{leg_idx + 1}",
                    "legType": leg["legType"],
                    "label": leg["label"],
                    "amount": leg["amount"],
                    "splitParty": None,
                    "reinsurer": settlement_label,
                    "viaForeignBroker": via,
                    "settlement": "open",
                    "reinsurerIdx": reinsurer_idx,
                })
    return transactions


def normalized_name(value):
    text = strip_facility_tag(value).lower()
    return js_trim(_WS_RUN.sub(" ", text))


def build_claim_payment_transactions(root_case, split_source, claim, payment):
    transactions = []
    loss_label = js_to_string(js_or(get(claim, "lossNo"), f"Claim #{js_to_string(get(claim, 'id'))}"))
    root_reinsurers = get(root_case, "reinsurers")
    root_reinsurers = root_reinsurers if is_array(root_reinsurers) else []
    split_reinsurers = get(split_source, "reinsurers")
    split_reinsurers = split_reinsurers if is_array(split_reinsurers) else []
    for split_idx, reinsurer in enumerate(split_reinsurers):
        share_amount = money(number_or_zero(get(payment, "amount")) * number_or_zero(get(reinsurer, "sharePct")) / 100)
        reinsurer_label = js_or(strip_facility_tag(get(reinsurer, "name")), f"Reinsurer {split_idx + 1}")
        settlement_label = js_or(js_trim(js_to_string(js_or(get(reinsurer, "foreignBroker"), ""))), reinsurer_label)
        root_idx = next(
            (i for i, row in enumerate(root_reinsurers)
             if normalized_name(get(row, "name")) == normalized_name(get(reinsurer, "name"))),
            -1,
        )
        tx_base = (f"{js_to_string(get(root_case, 'twRef'))}-CLM{js_to_string(get(claim, 'id'))}"
                   f"-P{js_to_string(get(payment, 'id'))}-R{split_idx + 1}")
        common = {
            "amount": share_amount,
            "splitParty": None,
            "reinsurer": settlement_label,
            "viaForeignBroker": settlement_label != reinsurer_label,
            "settlement": "open",
            "reinsurerIdx": root_idx if root_idx >= 0 else None,
            "source": "claim",
            "claimId": get(claim, "id"),
            "paymentId": get(payment, "id"),
            "lossNo": js_or(get(claim, "lossNo"), ""),
        }
        transactions.append({**common, "txNo": f"{tx_base}-TX1", "legType": "Claim Leg 1",
                             "label": f"Receivable — {settlement_label} owes reinsurance dept (claim {loss_label})"})
        transactions.append({**common, "txNo": f"{tx_base}-TX2", "legType": "Claim Leg 2",
                             "label": f"Payable — reinsurance dept owes cedant unit (claim {loss_label})"})
    return transactions


def reconciliation_ref_for(case_data, transaction):
    leg = js_to_string(js_or(get(transaction, "legType"), ""))
    is_claim = leg.startswith("Claim")
    cedant_facing = leg.startswith("Claim Leg 2") if is_claim else leg.startswith("Leg 1")
    reinsurer_facing = leg.startswith("Claim Leg 1") if is_claim else leg.startswith("Leg 2")
    if cedant_facing:
        return js_to_string(js_or(get(case_data, "statementNo"), ""))
    if reinsurer_facing:
        idx = get(transaction, "reinsurerIdx")
        index = idx if js_is_integer(idx) else -1
        if index >= 0:
            row = at(get(case_data, "reinsurers"), int(index))
            return js_to_string(js_or(get(row, "settlementRef"), ""))
        return ""
    return ""
