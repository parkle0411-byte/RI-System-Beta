"""Accounting server paging (2026-11-17 owner decision).

All Accounts / Settled/Closed / Brokerage are filtered, sorted and paged here (100 rows per page) instead of
downloading every settled legacy row to the browser. The rows are exactly those the browser used to build:
the same list response it loaded (``?view=list&legacy=open``) plus the settled legacy history
(``?view=list&legacy=history``), both after the JSON round trip, turned into list rows by the port of
frontend/src/alpha/accountingRows.js, then filtered and sorted by the port of frontend/src/views/accountingList.js
(with accountingCash.js, transactionParty.js, manualTwRef.js, transactionNumber.js). Each helper below names its
JavaScript original; change both together. ``scripts/run_qa.sh pages`` runs the JavaScript on the same data and
compares every page.

GET /api/accounting?view=page&tab=all|settled|brokerage&page=N&reference=&insured=&cedant=&reinsurer=&currency=
    &direction=&settlement=open,settled&source=&origin=&due=
GET /api/accounting?view=options            Cedant / Reinsurer / currency choices over every account (incl. history)
"""
import re
import threading

from rest_framework.response import Response

from .calc.jsnum import UNDEFINED, get, js_locale_key_cached, js_or, js_to_number, js_to_string, js_trim, js_truthy, json_roundtrip

PAGE_SIZE = 100
TABS = ("all", "settled", "brokerage")
FILTERS = ("reference", "insured", "cedant", "reinsurer", "currency", "direction", "source", "origin", "due")
MAX_PAGE = 1_000_000


# ---- frontend/src/alpha/transactionNumber.js ----
_TX_ALIAS = re.compile(r"(-R\d+)-TX([123])(?=[ab]?(?:-|\Z))", re.ASCII)
_CLM_ALIAS = re.compile(r"-CLM(\d+)(?=-P\d+-R\d+-T[12](?:-|\Z))", re.ASCII)


def transaction_number(value):
    text = "" if value is None or value is UNDEFINED else js_to_string(value)
    return _CLM_ALIAS.sub(r"-C\1", _TX_ALIAS.sub(r"\1-T\2", text))


# ---- frontend/src/alpha/manualTwRef.js: displayTwRef ----
def display_tw_ref(row, fallback="—"):
    automatic = js_trim(js_to_string(js_or(get(row, "twRef"), "")))
    auw = js_trim(js_to_string(js_or(get(row, "manualTwRef"), get(get(row, "payload"), "manualTwRef"), "")))
    parts = []
    for value in (automatic, auw):
        if value and value not in parts:
            parts.append(value)
    return " & ".join(parts) or fallback


# ---- frontend/src/alpha/transactionParty.js: transactionParty ----
def transaction_party(row):
    leg = js_to_string(js_or(get(row, "legType"), ""))
    if leg.startswith("Claim Leg 2") or leg.startswith("Leg 1") or get(row, "partyType") == "cedant":
        return js_trim(js_to_string(js_or(get(row, "reinsured"), ""))) or "Cedant"
    if leg.startswith("Leg 3"):
        return js_or(get(row, "partyName"), get(row, "reinsurer"), "—") if js_truthy(get(row, "overseaBusiness")) else "Broker"
    return js_or(get(row, "partyName"), get(row, "reinsurer"), "—")


# ---- frontend/src/views/accountingCash.js ----
_CEDANT_LEG = re.compile(r"^(Leg 1|Claim Leg 2)(?:\b|$)", re.ASCII)


def is_oversea_cash(row):
    return js_truthy(get(row, "overseaBusiness")) and get(row, "cashTracking") != "derived"


def is_derived_brokerage(row):
    return get(row, "cashTracking") == "derived" or (not js_truthy(get(row, "overseaBusiness"))
                                                    and js_to_string(js_or(get(row, "legType"), "")).startswith("Leg 3"))


def active_account(row):
    return (js_truthy(get(row, "txNo")) and not js_truthy(get(row, "scheduleOnly"))
            and not js_truthy(get(row, "reversed")) and not js_truthy(get(row, "isReversalEntry")))


def is_cedant_account(row):
    return get(row, "partyType") == "cedant" or bool(_CEDANT_LEG.search(js_to_string(js_or(get(row, "legType"), ""))))


def account_source(row):
    return "brokerage" if is_oversea_cash(row) else get(row, "source")


def visible_account(row, tab):
    if is_derived_brokerage(row):
        return tab == "brokerage"
    if is_oversea_cash(row):
        if tab == "all":
            return True
        if not active_account(row):
            return False
        if tab == "brokerage":
            return get(row, "settlement") == "settled"
        if tab == "settled" or get(row, "settlement") == "settled":
            return False
    elif tab == "brokerage":
        return False
    if tab == "settled":
        return active_account(row) and get(row, "settlement") == "settled"
    if tab == "unreconciled":
        return not js_truthy(get(row, "financeReviewed"))
    if tab == "reconciled":
        return js_truthy(get(row, "financeReviewed"))
    return True


# ---- frontend/src/alpha/accountingRows.js: accountingRows ----
def _list(value):
    return value if isinstance(value, list) else []


def account_rows(body):
    transactions = _list(js_or(get(body, "transactionRows"), []))
    merged = {}
    for row in [*_list(js_or(get(body, "scheduleRows"), [])), *[r for r in _list(js_or(get(body, "rows"), [])) if get(r, "source") == "premium"],
                *_list(js_or(get(body, "swissRows"), []))]:
        merged[_map_key(get(row, "key"))] = row          # Map: a later row replaces the value, the first position stays
    schedules = list(merged.values())
    by_key = {_map_key(get(row, "key")): row for row in schedules}
    ledger = {}
    for row in _list(js_or(get(body, "rows"), [])):
        ledger[_map_key(get(row, "key"))] = row
    covered = set()
    out = []
    for row in transactions:
        current = get(row, "source") != "claim" and not js_truthy(get(row, "reversed")) and not js_truthy(get(row, "isReversalEntry"))
        associated = []
        if current:
            keys = []
            for part in _list(js_or(get(row, "cashParts"), [])):
                key = js_to_string(get(row, "caseUid")) + ":" + js_to_string(get(part, "scheduleKey"))
                if key not in keys:
                    keys.append(key)
            for key in keys:
                item = by_key.get(_map_key(key))
                if not js_truthy(item):
                    continue
                if js_truthy(get(row, "financeDates")):
                    item = {**item, **row["financeDates"]} if isinstance(row["financeDates"], dict) else {**item}
                elif js_truthy(get(row, "swissCgl")) and get(row, "settlement") == "settled":
                    dates = {k: row[k] for k in ("baseDate", "dueDate", "contractDueDate", "termsDays", "reminderDate", "paymentRule")
                             if k in row and row[k] is not None}
                    item = {**item, **dates, "status": get(row, "paymentStatus")}
                associated.append(item)
        for item in associated:
            covered.add(_map_key(get(item, "key")))
        out.append({**row, "schedules": associated})
    for item in schedules:
        if _map_key(get(item, "key")) in covered or not any(js_truthy(get(item, k)) for k in
                                                           ("swissCase", "swissFacility", "requiresCollectionConfirmation", "greatAmericanCase", "qbeCase")):
            continue
        entries = [{**e, "appliedAmount": js_to_number(js_or(get(e, "amount"), 0)) * (-1 if get(e, "entryType") == "reversal" else 1)}
                   for e in _list(js_or(get(item, "entries"), []))]
        non_cash = 0
        for entry in entries:
            non_cash = non_cash + (entry["appliedAmount"] if js_truthy(get(entry, "nonCash")) else 0)
        cedant = next((r for r in schedules if get(r, "caseUid") == get(item, "caseUid") and get(r, "partyType") == "cedant"), None)
        amount = js_to_number(get(item, "amount"))
        incoming = (get(item, "partyType") == "cedant") == (amount > 0)
        outstanding, paid = js_to_number(get(item, "outstanding")), js_to_number(get(item, "paid"))
        settlement = js_or(get(item, "settlement"), "settled" if abs(outstanding) < .005 else "partial" if abs(paid) > .004 else "open")
        base = ledger.get(_map_key(get(item, "key")))
        out.append({**(base if isinstance(base, dict) else {}), **item, "scheduleOnly": True, "schedules": [item], "source": "premium",
                    "txNo": "", "legType": "Leg 1" if get(item, "partyType") == "cedant" else "Leg 2",
                    "reinsured": js_or(get(cedant, "partyName"), ""), "cashTracking": "cash",
                    "paymentDirection": "receivable" if incoming else "payable",
                    "cashPaid": paid - non_cash, "nonCashPaid": non_cash, "entries": entries,
                    "paymentStatus": get(item, "status"), "settlement": settlement,
                    "canRecord": False, "canConfirmSettlement": False})
    return out


def _map_key(value):
    """Map keys use SameValueZero; the keys here are strings or missing (undefined)."""
    return ("u",) if value is UNDEFINED else ("v", type(value).__name__, value if isinstance(value, (str, int, float, bool)) or value is None else repr(value))


# ---- frontend/src/views/accountingList.js ----
def row_title(row):
    if js_truthy(get(row, "scheduleOnly")):
        return "Historical schedule · " + js_to_string(get(row, "installmentLabel"))
    return transaction_number(get(row, "txNo"))


def _first_schedule(row, field):
    for item in _list(get(row, "schedules")):
        if js_truthy(get(item, field)):
            return get(item, field)
    return UNDEFINED


def actual_due(row):
    return js_or(get(row, "contractDueDate"), _first_schedule(row, "contractDueDate"), get(row, "dueDate"), "")


def normalized_settlement(row):
    return "open" if get(row, "settlement") == "partial" else get(row, "settlement")


def _lower(value):
    return js_to_string(js_or(value, "")).lower()


def matches(values, query):
    if not js_truthy(query):
        return True
    needle = js_trim(query).lower()
    return any(needle in _lower(v) for v in values)


def _js_less_equal(a, b):
    return isinstance(a, str) and isinstance(b, str) and a <= b


def filter_rows(rows, tab, filters, text):
    settlement = filters.get("settlement") or []
    out = []
    for r in rows:
        if not visible_account(r, tab):
            continue
        if settlement and (js_truthy(get(r, "reversed")) or js_truthy(get(r, "isReversalEntry")) or normalized_settlement(r) not in settlement):
            continue
        if not (matches([get(r, "twRef"), get(r, "manualTwRef"), display_tw_ref(r)], text.get("reference"))
                and matches([get(r, "originalInsured"), get(r, "originalInsuredCn")], text.get("insured"))):
            continue
        if filters.get("cedant") and not (is_cedant_account(r) and transaction_party(r) == filters["cedant"]):
            continue
        if filters.get("reinsurer") and not (not is_cedant_account(r) and transaction_party(r) == filters["reinsurer"]):
            continue
        if filters.get("currency") and filters["currency"] != get(r, "currency"):
            continue
        if filters.get("direction") and get(r, "paymentDirection") != filters["direction"]:
            continue
        if filters.get("source") and account_source(r) != filters["source"]:
            continue
        if filters.get("origin") and js_or(get(r, "origin"), "native") != filters["origin"]:
            continue
        if filters.get("due"):
            due = actual_due(r)
            if not (js_truthy(due) and _js_less_equal(due, filters["due"])):
                continue
        out.append(r)
    return out


def _collate(value):
    return js_locale_key_cached(js_to_string(value))


def sort_key(row, tab, now):
    if tab == "brokerage":
        return (int(get(row, "settlement") == "settled"), _collate(display_tw_ref(row)))
    due = actual_due(row)
    overdue = get(row, "settlement") != "settled" and js_truthy(due) and isinstance(due, str) and due < now
    date = due if overdue else js_or(get(row, "dueDate"), _first_schedule(row, "dueDate"), due, "9999-12-31")
    return (-int(bool(overdue)), _collate(date), _collate(display_tw_ref(row)), _collate(row_title(row)))


def _code_units(value):
    return js_to_string(value).encode("utf-16-be", "surrogatepass")


def party_options(rows):
    cedants, reinsurers = {}, {}
    for r in rows:
        if is_derived_brokerage(r):
            continue
        party = transaction_party(r)
        if js_truthy(party):
            (cedants if is_cedant_account(r) else reinsurers).setdefault(party, None)
    return {"cedants": sorted(cedants, key=_code_units), "reinsurers": sorted(reinsurers, key=_code_units)}


# ---- the settled legacy history part, computed once per day and history content ----
_HISTORY = {}
_HISTORY_LOCK = threading.Lock()
RECHECK_SECONDS = 60


def _cheap_signature(ledger):
    """Count, highest key, version sum and latest update of the history rows: every import, withdrawal, deletion or
    saved edit changes it (the same kind of change signature as the Dashboard / Production result cache)."""
    from django.db.models import Count, Max, Sum
    found = ledger.historical_queryset().order_by().aggregate(n=Count("pk"), top=Max("pk"), v=Sum("version"), s=Max("updated_at"))
    return tuple(sorted((k, str(v)) for k, v in found.items()))


def _history_part(view, request):
    """List rows of the settled legacy history (with sort keys), its registrations, correction histories and currencies.

    The history is read-only and settled, so it changes only with its content or the Taipei date. Each request checks the
    cheap change signature; at most once a minute the full content fingerprint of the legacy result cache (MD5 of every
    column) is compared as well, which also catches direct database edits that did not touch the update time. With the
    legacy result cache switched off (RI_LEGACY_RESULT_CACHE=false) the part is rebuilt on every request."""
    import time
    import legacy.ledger as ledger
    if ledger._cache_enabled():
        today, cheap = ledger._today(), _cheap_signature(ledger)
        with _HISTORY_LOCK:
            hit = _HISTORY.get("value") if _HISTORY.get("today") == today and _HISTORY.get("cheap") == cheap else None
            fresh = hit is not None and time.monotonic() - _HISTORY.get("checked", 0) < RECHECK_SECONDS
            digest = _HISTORY.get("digest")
        if fresh:
            return hit
        if hit is not None:
            if ledger._fingerprint(ledger.historical_queryset()) == digest:
                with _HISTORY_LOCK:
                    if _HISTORY.get("value") is hit:
                        _HISTORY["checked"] = time.monotonic()
                return hit
    else:
        today = cheap = None
    started = time.monotonic()
    digest = ledger._fingerprint(ledger.historical_queryset()) if today is not None else None
    body = json_roundtrip(view.list_body(request, "history"))
    rows = account_rows({"transactionRows": body.get("transactionRows") or []})
    part = {"rows": rows, "batches": {b.get("batchId"): b for b in body.get("cashBatches") or []},
            "caseHistories": body.get("caseHistories") or {}, "currencies": body.get("currencies") or [], "sortKeys": {}}
    if today is not None and ledger._today() == today and _cheap_signature(ledger) == cheap:
        with _HISTORY_LOCK:
            _HISTORY.clear(); _HISTORY.update(today=today, cheap=cheap, digest=digest, checked=started, value=part)
    return part


def _history_keys(part, tab, now):
    """Sort keys of the history rows for one tab and day (by row identity; the cached rows are never modified)."""
    with _HISTORY_LOCK:
        keys = part["sortKeys"].get((tab, now))
    if keys is None:
        keys = {id(r): sort_key(r, tab, now) for r in part["rows"]}
        with _HISTORY_LOCK:
            part["sortKeys"][(tab, now)] = keys
    return keys


def _merged(view, request):
    """Rows in the browser's former order: the open list response first, then the settled history (as it was merged)."""
    open_body = json_roundtrip(view.list_body(request, "open"))
    history = _history_part(view, request)
    rows = [r for r in account_rows(open_body) if not js_truthy(get(r, "legacyHistorical"))] + history["rows"]   # mergeHistory()
    currencies = sorted({*map(js_to_string, open_body.get("currencies") or []), *map(js_to_string, history["currencies"])}, key=_code_units)
    batches = {b.get("batchId"): b for b in open_body.get("cashBatches") or []}
    for batch_id, batch in history["batches"].items():
        batches[batch_id] = batch
    case_histories = {**(open_body.get("caseHistories") or {}), **history["caseHistories"]}
    return rows, currencies, batches, case_histories, history


def _filters(params):
    values = {name: js_to_string(params.get(name, "")) for name in FILTERS}
    settlement = [s for s in js_to_string(params.get("settlement", "")).split(",") if s]
    return {**{k: values[k] for k in ("cedant", "reinsurer", "currency", "direction", "source", "origin", "due")}, "settlement": settlement}, \
           {"reference": values["reference"], "insured": values["insured"]}


def _error(code, message):
    return Response({"error": code, "message": message}, status=400)


def page_response(view, request):
    from .calc.payment_terms import taipei_date
    params = request.query_params
    rows, currencies, batches, case_histories, history = _merged(view, request)
    options = {**party_options(rows), "currencies": currencies}
    if params.get("view") == "options":
        return Response(json_roundtrip({"ok": True, "options": options}))
    tab = params.get("tab", "")
    if tab not in TABS:
        return _error("invalid_tab", "tab must be all, settled or brokerage.")
    try:
        page = int(params.get("page", "1"))
    except (TypeError, ValueError):
        return _error("invalid_page", "page must be a whole number.")
    page = min(MAX_PAGE, max(1, page))
    filters, text = _filters(params)
    now = taipei_date(None)
    listed = filter_rows(rows, tab, filters, text)
    cached = _history_keys(history, tab, now)
    listed.sort(key=lambda r: cached.get(id(r)) or sort_key(r, tab, now))
    total = len(listed)
    shown = listed[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    wanted = set()
    for row in shown:
        for entry in _list(get(row, "entries")):
            wanted.add(js_or(get(entry, "batchId"), get(entry, "offsetId"), "legacy:" + js_to_string(get(entry, "id"))))
    uids = {get(row, "caseUid") for row in shown}
    return Response(json_roundtrip({
        "ok": True, "tab": tab, "page": page, "pageSize": PAGE_SIZE, "total": total,
        "rows": shown, "options": options,
        "cashBatches": [batches[b] for b in batches if b in wanted],
        "caseHistories": {uid: h for uid, h in case_histories.items() if uid in uids},
    }))
