// Alpha 原始碼的「節錄」（差異測試用）：來自 api/payment-reminders.js（v53，雜湊 14d5c92bc56dd9e1…）
// 與 api/signed-slip-reminders.js（v53，雜湊 4bf1b2d5f60b44c6…）。兩個檔案都 import 了 'hatchable'，無法直接在 Node 執行，
// 所以把不碰資料庫、寄信與排程的部分原樣切出來：
//   - payment-reminders.js 第 2 行（import，改成只取用到的兩個函式）、第 19–100 行（esc、validEmail、label、message、resolveRecipients、dueKind，逐字）
//   - payment-reminders.js 第 129–131 行（Finance 收件人的篩選，逐字），外面加測試用的外殼函式 payFinanceEmails（外殼提供 personnelResult）
//   - signed-slip-reminders.js 第 18–57 行（escapeHtml、validEmail、contactFor、reminderMessage，逐字）；
//     兩個檔案都有 validEmail，Signed Slip 的放在區塊內（名稱衝突），與付款的逐字相同
// 這個檔案是由程式從「雜湊與 Alpha 相同」的原檔切出的（見 MANIFEST.md），不可手動修改。

import { daysBetweenDates, addCalendarDays } from '../lib/payment-terms.js';

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function validEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || "").trim());
}

function label(kind) {
  return kind === "seven_days_before" ? "7 天後到期" : kind === "due_today" ? "今日到期" : "逾期每週提醒";
}

function message(caseData, kind, items) {
  const reference = caseData.twRef || "Case #" + caseData.id;
  const rows = items.map((item) => {
    const amount = Number(item.outstanding || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${item.installmentLabel} · ${item.partyName} · ${item.currency} ${amount} · ${item.dueDate} 12:00 (Taiwan)`;
  });
  return {
    subject: `[Payment ${label(kind)}] ${reference}`,
    html: `<p>案件 <strong>${esc(reference)}</strong> 有以下付款期限項目：</p><ul>${rows.map((row) => "<li>" + esc(row) + "</li>").join("")}</ul><p><a href="https://ri-system-alpha.hatchable.site">開啟 RI System (Alpha)</a></p><p style="color:#666">本信由系統自動產生。</p>`
  };
}

// Recipient policy (owner-confirmed): a reminder only goes out when ALL of
// the following resolve cleanly — otherwise nothing is sent to anyone and
// the case is recorded as a configuration error, same strict all-or-nothing
// model as Signed Slip Reminders' contactFor():
//   - the case's AE name matches exactly one active Personnel record
//   - that AE record has a valid e-mail
//   - that AE record's supervisor name is set and supervisor e-mail is valid
//   - at least one active Finance Staff / Finance Manager has a valid e-mail
//     (a partial Finance roster is fine — recipients go only to the ones
//     with a valid e-mail; it's an all-active-Finance-missing roster that
//     blocks sending)
function resolveRecipients(caseData, personnel, financeEmails) {
  const target = String(caseData.ae || "").trim().toLowerCase();
  const matches = personnel.filter((row) => String(row.name || "").trim().toLowerCase() === target);
  if (!target || matches.length !== 1) {
    return { error: matches.length > 1 ? "AE name matches multiple active Personnel records." : "AE does not match one active Personnel record." };
  }
  const ae = matches[0];
  const aeEmail = String(ae.email || "").trim().toLowerCase();
  const supervisorName = String(ae.supervisor_name || "").trim();
  const supervisorEmail = String(ae.supervisor_email || "").trim().toLowerCase();
  if (!validEmail(aeEmail) || !supervisorName || !validEmail(supervisorEmail)) {
    return { error: "AE or supervisor contact fields are incomplete or invalid." };
  }
  if (!financeEmails.length) {
    return { error: "No active Finance Staff or Finance Manager has a valid e-mail." };
  }
  return { recipients: [...new Set([aeEmail, supervisorEmail, ...financeEmails])] };
}

// Bugfix (#9): the previous exact-day check (days-before-due === 7, === 0, or
// overdueDays a multiple of 7) had no retry — if that one day's send failed
// (email outage, a caught error, etc.), the next day's date math produced a
// different kind, so the failed attempt was silently lost for good (the two
// one-time notices) or delayed a full week (the weekly overdue cadence).
// This mirrors Signed Slip Reminders' self-healing "last successful send + N
// days" anchor: a kind stays due on every later day until a 'sent'/'simulated'
// alert is actually recorded for it (a 'failed' delivery does not count), so a
// missed day gets picked up on the very next run instead of being lost.
//   - seven_days_before: catch-up window from 7 days out through the day
//     before due, as long as it hasn't gone out yet.
//   - due_today: catch-up window from the due date through 6 days overdue, as
//     long as it hasn't gone out yet and the weekly cadence hasn't taken over.
//   - weekly_overdue: cadence anchored to the last successful weekly send (or
//     one week after the due date if none yet), exactly like Signed Slip.
function dueKind(item, today, successDates) {
  if (!item?.dueDate || item.outstanding <= 0.004) return "";
  const days = daysBetweenDates(today, item.dueDate); // positive = due date still upcoming
  if (days == null) return "";
  if (days >= 1 && days <= 7 && !successDates.seven_days_before) return "seven_days_before";
  if (days <= 0 && days >= -6 && !successDates.due_today && !successDates.weekly_overdue) return "due_today";
  if (days < 0) {
    const anchor = successDates.weekly_overdue || item.dueDate;
    const dueSince = addCalendarDays(anchor, 7);
    if (dueSince && today >= dueSince) return "weekly_overdue";
  }
  return "";
}

export function payFinanceEmails(rows) {
  const personnelResult = { rows };
  const financeEmails = personnelResult.rows
    .filter((row) => ["accounting", "accounting_manager"].includes(String(row.role_code || "").toLowerCase()))
    .map((row) => row.email).filter(validEmail);
  return financeEmails;
}

const slip = (() => {
function escapeHtml(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[character]));
}

function validEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || '').trim());
}

function contactFor(caseData, personnel) {
  const target = String(caseData.ae || '').trim().toLowerCase();
  const matches = personnel.filter((row) => String(row.name || '').trim().toLowerCase() === target);
  if (!target || matches.length !== 1) {
    return { error: matches.length > 1 ? 'AE name matches multiple active Personnel records.' : 'AE does not match one active Personnel record.' };
  }
  const person = matches[0];
  const aeEmail = String(person.email || '').trim();
  const supervisorName = String(person.supervisor_name || '').trim();
  const supervisorEmail = String(person.supervisor_email || '').trim();
  if (!validEmail(aeEmail) || !supervisorName || !validEmail(supervisorEmail)) {
    return { error: 'AE or supervisor contact fields are incomplete or invalid.' };
  }
  return { aeEmail, supervisorName, supervisorEmail };
}

function reminderMessage(caseData, due, contact) {
  const reference = caseData.twRef || `Case #${caseData.id}`;
  const subject = `[Signed Slip 逾期警示] ${reference} — 尚缺 ${due.missing.length} 家再保人簽署文件`;
  const text = `AE ${caseData.ae || '—'}、${contact.supervisorName} 您好：

案件 ${reference} 自保單生效日 ${caseData.policyFrom} 起已經過 ${due.daysSinceEffective} 天，系統仍未收到以下再保人的 Reinsurer Signed Slip：
${due.missing.map((name) => '• ' + name).join('\n')}

即使已上傳 Reinsurer Confirmation E-mail，Signed Slip 追蹤仍會持續。請完成追蹤並將 Signed Slip 上傳至 Reinsurance Department System。

本信由系統自動產生。`;
  const html = `<p>AE ${escapeHtml(caseData.ae || '—')}、${escapeHtml(contact.supervisorName)} 您好：</p><p>案件 <strong>${escapeHtml(reference)}</strong> 自保單生效日 ${escapeHtml(caseData.policyFrom)} 起已經過 ${due.daysSinceEffective} 天，系統仍未收到以下再保人的 Reinsurer Signed Slip：</p><ul>${due.missing.map((name) => `<li>${escapeHtml(name)}</li>`).join('')}</ul><p>即使已上傳 Reinsurer Confirmation E-mail，Signed Slip 追蹤仍會持續。請完成追蹤並將 Signed Slip 上傳至 Reinsurance Department System。</p><p><a href="https://ri-system-alpha.hatchable.site">開啟 RI System (Alpha)</a></p><p style="color:#666">本信由系統自動產生。</p>`;
  return { subject, text, html };
}
  return { escapeHtml, validEmail, contactFor, reminderMessage };
})();

export {
  esc as payEsc, validEmail as payValidEmail, label as payLabel, message as payMessage,
  resolveRecipients as payResolveRecipients, dueKind as payDueKind,
};
export const slipEscapeHtml = slip.escapeHtml;
export const slipValidEmailApi = slip.validEmail;
export const slipContactFor = slip.contactFor;
export const slipReminderMessage = slip.reminderMessage;
