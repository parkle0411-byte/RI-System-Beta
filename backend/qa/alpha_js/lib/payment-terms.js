import { calcLegsForReinsurer, stripFacilityTag } from "lib/accounting.js";

export const MIN_PAYMENT_TERMS_DAYS = 15;

function num(value) {
  // Bugfix: Number("") is 0 (finite), not NaN, so an empty/absent value must be
  // rejected explicitly before the numeric conversion or every ?? fallback that
  // chains off this function (e.g. premium ?? ratio) silently never triggers.
  if (value === null || value === undefined) return null;
  const trimmed = String(value).trim();
  if (trimmed === "") return null;
  const n = Number(trimmed.replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}

function money(value) {
  return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
}

function validTerms(value) {
  const n = num(value);
  return n != null && Number.isInteger(n) && n >= MIN_PAYMENT_TERMS_DAYS ? n : null;
}

function validDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));
}

export function addCalendarDays(value, days) {
  if (!validDate(value)) return "";
  const d = new Date(value + "T00:00:00Z");
  if (Number.isNaN(d.getTime())) return "";
  d.setUTCDate(d.getUTCDate() + Number(days || 0));
  return d.toISOString().slice(0, 10);
}

export function taipeiDate(now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit"
  }).format(now);
}

export function daysBetweenDates(from, to) {
  if (!validDate(from) || !validDate(to)) return null;
  return Math.round((Date.parse(to + "T00:00:00Z") - Date.parse(from + "T00:00:00Z")) / 86400000);
}

function allocate(total, installments) {
  if (!installments.length) return [];
  const weights = installments.map((row) => Math.max(0, Number(row.weight) || 0));
  let sum = weights.reduce((a, b) => a + b, 0);
  if (sum <= 0) {
    sum = installments.length;
    weights.fill(1);
  }
  let used = 0;
  return installments.map((row, index) => {
    if (index === installments.length - 1) return money(total - used);
    const amount = money(total * weights[index] / sum);
    used = money(used + amount);
    return amount;
  });
}

export function paymentInstallments(caseData) {
  if (caseData?.installmentEnabled === true) {
    return (Array.isArray(caseData.performanceInstallments) ? caseData.performanceInstallments : []).map((row, index) => ({
      ...row,
      id: String(row?.id || "installment-" + (index + 1)),
      label: String(row?.performanceMonth || "Installment " + (index + 1)),
      baseDate: String(row?.paymentBaseDate || ""),
      weight: Math.max(0, num(row?.premium) ?? num(row?.ratio) ?? 0)
    }));
  }
  return [{
    id: "case-effective-date",
    label: "Case Effective Date",
    baseDate: String(caseData?.policyFrom || ""),
    weight: 1
  }];
}

function resolvedTerms(caseData, installment, reinsurer, reinsurerIndex) {
  const key = "r" + (reinsurerIndex + 1);
  const map = installment?.reinsurerPaymentTerms && typeof installment.reinsurerPaymentTerms === "object"
    ? installment.reinsurerPaymentTerms : {};
  return validTerms(map[key])
    ?? validTerms(reinsurer?.paymentTermsDays)
    ?? validTerms(installment?.paymentTermsDays)
    ?? validTerms(caseData?.paymentTermsDays);
}

function appliedByKey(caseData) {
  const result = {};
  const entries = Array.isArray(caseData?.paymentEntries) ? caseData.paymentEntries : [];
  entries.forEach((entry) => {
    const key = String(entry?.scheduleKey || "");
    const amount = num(entry?.amount);
    if (!key || amount == null) return;
    const signed = entry?.entryType === "reversal" ? -Math.abs(amount) : Math.abs(amount);
    result[key] = money((result[key] || 0) + signed);
  });
  return result;
}

function statusFor(dueDate, outstanding, paid, today, now) {
  if (!dueDate) return "pending_review";
  if (outstanding <= 0.004) return "settled";
  const delta = daysBetweenDates(dueDate, today);
  if (delta > 0) return "overdue";
  if (delta === 0) {
    const time = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit", hour12: false
    }).format(now);
    return time > "12:00" ? "overdue" : "due_today";
  }
  return paid > 0.004 ? "partially_paid" : "upcoming";
}

export function buildPaymentSchedule(caseData, now = new Date()) {
  const reinsurers = Array.isArray(caseData?.reinsurers) ? caseData.reinsurers : [];
  const installments = paymentInstallments(caseData);
  const applied = appliedByKey(caseData);
  const today = taipeiDate(now);
  const issues = [];
  const weights = installments.map((row) => ({ ...row, weight: row.weight }));
  const legs = reinsurers.map((reinsurer) => calcLegsForReinsurer(caseData, reinsurer));
  const cedantAmounts = allocate(legs.reduce((sum, row) => sum + row.leg1, 0), weights);
  const reinsurerAmounts = legs.map((row) => allocate(row.leg2, weights));
  const items = [];

  if (validTerms(caseData?.paymentTermsDays) == null) issues.push("Case Payment Terms must be at least 15 calendar days.");

  installments.forEach((installment, installmentIndex) => {
    const baseDate = validDate(installment.baseDate) ? installment.baseDate : "";
    if (!baseDate) issues.push(installment.label + ": payment base date is required.");

    const resolvedTermsPerReinsurer = reinsurers.map((reinsurer, index) => resolvedTerms(caseData, installment, reinsurer, index));
    const allTerms = resolvedTermsPerReinsurer.filter((value) => value != null);
    // Low/observational fix: the cedant due date below takes the min() of only the
    // VALID reinsurer terms -- any invalid one is silently excluded from that
    // calculation. A per-reinsurer "invalid Payment Terms" issue is still raised
    // separately further down, but it doesn't say it also affected this cedant
    // calculation, so make that link explicit here.
    if (allTerms.length < resolvedTermsPerReinsurer.length) {
      issues.push(installment.label + ": Cedant due date calculation excludes Reinsurer(s) with invalid Payment Terms.");
    }
    const cedantTerms = allTerms.length ? Math.min(...allTerms) : validTerms(installment?.paymentTermsDays) ?? validTerms(caseData?.paymentTermsDays);
    const cedantKey = installment.id + ":cedant";
    const cedantPaid = Math.max(0, money(applied[cedantKey] || 0));
    const cedantAmount = Math.max(0, money(cedantAmounts[installmentIndex] || 0));
    const cedantOutstanding = Math.max(0, money(cedantAmount - cedantPaid));
    const cedantDue = baseDate && cedantTerms != null ? addCalendarDays(baseDate, cedantTerms - 15) : "";
    items.push({
      scheduleKey: cedantKey, installmentId: installment.id, installmentLabel: installment.label,
      partyType: "cedant", partyKey: "cedant", partyName: String(caseData?.reinsuredName || caseData?.cedantName || "Cedant"),
      currency: String(caseData?.currency || ""), baseDate, termsDays: cedantTerms,
      dueDate: cedantDue, dueTime: "12:00", amount: cedantAmount, paid: Math.min(cedantAmount, cedantPaid),
      outstanding: cedantOutstanding, status: statusFor(cedantDue, cedantOutstanding, cedantPaid, today, now),
      partial: cedantPaid > 0.004 && cedantOutstanding > 0.004
    });

    reinsurers.forEach((reinsurer, reinsurerIndex) => {
      const terms = resolvedTerms(caseData, installment, reinsurer, reinsurerIndex);
      if (terms == null) issues.push(installment.label + ": invalid Payment Terms for Reinsurer " + (reinsurerIndex + 1) + ".");
      const key = installment.id + ":reinsurer:r" + (reinsurerIndex + 1);
      const paid = Math.max(0, money(applied[key] || 0));
      const amount = Math.max(0, money(reinsurerAmounts[reinsurerIndex]?.[installmentIndex] || 0));
      const outstanding = Math.max(0, money(amount - paid));
      const dueDate = baseDate && terms != null ? addCalendarDays(baseDate, terms - 10) : "";
      items.push({
        scheduleKey: key, installmentId: installment.id, installmentLabel: installment.label,
        partyType: "reinsurer", partyKey: "r" + (reinsurerIndex + 1),
        partyName: String(reinsurer?.foreignBroker || stripFacilityTag(reinsurer?.name) || "Reinsurer " + (reinsurerIndex + 1)),
        currency: String(caseData?.currency || ""), baseDate, termsDays: terms,
        dueDate, dueTime: "12:00", amount, paid: Math.min(amount, paid), outstanding,
        status: statusFor(dueDate, outstanding, paid, today, now),
        partial: paid > 0.004 && outstanding > 0.004
      });
    });
  });

  return {
    items,
    issues: [...new Set(issues)],
    reviewRequired: issues.some((issue) => issue.includes("payment base date")),
    totals: {
      cedantOutstanding: money(items.filter((row) => row.partyType === "cedant").reduce((sum, row) => sum + row.outstanding, 0)),
      reinsurerOutstanding: money(items.filter((row) => row.partyType === "reinsurer").reduce((sum, row) => sum + row.outstanding, 0))
    }
  };
}

// Maps a single row of the OLD premium ledger (payload.transactions[], produced
// by lib/accounting.js buildPremiumTransactions at Production Report close) to a
// settlement status derived from the NEW payment schedule (paymentEntries[]).
// The old ledger's own `settlement` field is permanently stale for premium rows
// (nothing has written to it since Payment Terms shipped), so this recomputes a
// status on the fly instead. Claim-sourced rows are untouched — a different,
// still-working code path keeps their `settlement` field accurate.
//
// Leg 1 (cedant receivable, per-reinsurer allocation in the old ledger) maps to
// the case's single pooled cedant obligation — the cedant pays once for the
// whole case, not per reinsurer, so every Leg 1 row (including split a/b) shares
// one true status.
// Leg 2 (reinsurer payable) maps cleanly to that specific reinsurer's schedule
// rows, summed across installments — the underlying amount formula is identical,
// just no longer collapsed into one lump sum.
// Leg 3 (brokerage spread) has no equivalent in the payment schedule at all — it
// was never turned into a trackable, payable line — so it is reported as
// "not_tracked" rather than a possibly-wrong open/settled guess.
// Performance Split a/b rows for the same reinsurer/leg share one status, since
// the payment schedule has no concept of split parties.
export function deriveLedgerSettlement(caseData, transaction) {
  if (transaction?.source === 'claim') {
    return transaction?.settlement === 'settled' ? 'settled' : 'open';
  }
  const legType = String(transaction?.legType || '');
  const schedule = buildPaymentSchedule(caseData);
  const summarize = (items) => {
    if (!items.length) return 'not_tracked';
    const outstanding = items.reduce((sum, item) => sum + item.outstanding, 0);
    const paid = items.reduce((sum, item) => sum + item.paid, 0);
    if (outstanding <= 0.004) return 'settled';
    if (paid > 0.004) return 'partial';
    return 'open';
  };
  if (legType.startsWith('Leg 1')) {
    return summarize(schedule.items.filter((item) => item.partyType === 'cedant'));
  }
  if (legType.startsWith('Leg 2')) {
    const reinsurerIdx = Number.isInteger(transaction?.reinsurerIdx) ? transaction.reinsurerIdx : -1;
    if (reinsurerIdx < 0) return 'not_tracked';
    const key = 'r' + (reinsurerIdx + 1);
    return summarize(schedule.items.filter((item) => item.partyType === 'reinsurer' && item.partyKey === key));
  }
  return 'not_tracked';
}

export function reminderKind(item, today = taipeiDate()) {
  if (!item?.dueDate || item.outstanding <= 0.004) return "";
  const days = daysBetweenDates(today, item.dueDate);
  if (days === 7) return "seven_days_before";
  if (days === 0) return "due_today";
  const overdueDays = daysBetweenDates(item.dueDate, today);
  if (overdueDays > 0 && overdueDays % 7 === 0) return "weekly_overdue";
  return "";
}