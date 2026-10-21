"""Idempotent, explicit conversion of existing TWD premiums (owner confirmed)."""
import copy,re
from .calc.premium_money import premium_money, LEGACY
from .calc.accounting import build_premium_transactions
from .calc.payment_terms import premium_installment_plan

VERSION = "currency-stepwise-v1"

def has_history(payload):
    from .accounting_rules import premium_activity
    state = payload.get("facilityAccounting") or {}
    return bool(payload.get("paymentEntries") or premium_activity(payload) or state.get("history") or state.get("confirmations") or state.get("finalizedTransactions")
                or any((payload.get("swissAccounting") or {}).get(key) for key in ("confirmations", "statements", "history"))
                or any(isinstance(t, dict) and (t.get("settlement") == "settled" or t.get("settledAt")) for t in payload.get("transactions") or []))

def converted(payload, tw_ref=""):
    result = copy.deepcopy(payload)
    if str(result.get("currency") or "").upper() != "TWD" or result.get("premiumRounding") in (VERSION, LEGACY):
        return result
    if has_history(result):
        result["premiumRounding"] = LEGACY
        return result
    result["premiumRounding"] = VERSION
    for row, key in [(result, "originalPremium")] + [(r, "premium") for name in ("reinsurers", "performanceInstallments") for r in result.get(name, []) if isinstance(r, dict)]:
        if row.get(key) is not None and str(row[key]).strip() != "":
            row[key] = premium_money(float(str(row[key]).replace(",", "")), result)
    # Recalculate existing premium entries only; preserve IDs, dates, status,
    # party attribution, claim entries, reversal identity and every other field.
    transaction_case = {**result, "twRef": tw_ref or result.get("twRef") or ""}
    plans = premium_installment_plan(transaction_case)
    generated = build_premium_transactions(transaction_case)
    for entry in plans:
        generated += build_premium_transactions(transaction_case, entry)
    amounts = {entry["txNo"]: entry["amount"] for entry in generated}
    for entry in result.get("transactions") or []:
        if not isinstance(entry, dict) or entry.get("source") == "claim" or str(entry.get("legType", "")).startswith("Claim"):
            continue
        no = re.sub(r"-RVS[0-9]+$", "", str(entry.get("txNo") or ""))
        no = re.sub(r"-C[0-9]+$", "", no)
        if no not in amounts:
            raise ValueError("Unrecognized premium transaction; cannot safely recalculate " + no)
        entry["amount"] = -amounts[no] if entry.get("isReversalEntry") else amounts[no]
    return result
