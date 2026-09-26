// 格式化與共用小工具。逐函式移植自 Alpha public/app.js（函式名稱與內容相同）。
import { ElMessage, ElMessageBox } from 'element-plus';
import { PERSONNEL_DEPARTMENTS, PERSONNEL_ROLES, STRUCTURE_LABEL } from './constants';

export function filled(value) {
  if (value === null || value === undefined) return false;
  if (typeof value === 'string') return value.trim() !== '';
  return true;
}

export function formatAmount(value) {
  if (!filled(value)) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 }).format(Number(value));
}

export function formatFxRate(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(number);
}

export function formatMoney(value) {
  const number = Number(value);
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number.isFinite(number) ? number : 0);
}

export function formatCurrency(value, currency) {
  const number = Number(value);
  const digits = currency === 'TWD' ? 0 : 2;
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number.isFinite(number) ? number : 0);
}

export function formatDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
}

export function formatFileSize(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.ceil(bytes / 1024).toLocaleString('en-US')} KB`;
}

export function normalizedPolicyTime(value) {
  return value === '00:00' ? '00:00' : '12:00';
}

export function formatPolicyDateTime(date, time) {
  return date ? `${date} ${normalizedPolicyTime(time)}` : '—';
}

export function formatPolicyPeriod(row) {
  return `${formatPolicyDateTime(row?.effectiveDate || row?.policyFrom, row?.effectiveTime || row?.policyFromTime)} ~ ${formatPolicyDateTime(row?.expirationDate || row?.policyTo, row?.expirationTime || row?.policyToTime)}`;
}

export function statusLabel(status) {
  return { draft: 'Draft', posted: 'Announced', closed: 'Confirmed', reversed: 'Reversed', archived: 'Archived' }[status] || status || 'Unknown';
}

export function structureLabel(value) {
  return STRUCTURE_LABEL[value] || value || '—';
}

export function departmentLabel(value) {
  return PERSONNEL_DEPARTMENTS.find((item) => item.value === value)?.label || value || '—';
}

export function roleLabel(value) {
  return PERSONNEL_ROLES.find((item) => item.value === value)?.label || value || '—';
}

// Alpha #22：409（版本衝突）要提供「重新載入最新版本」，其他錯誤顯示訊息
export function reportWriteError(err, reload) {
  const status = err && err.status;
  const message = err instanceof Error ? err.message : String(err);
  if (Number(status) === 409) {
    ElMessageBox.confirm(
      `${message} Reload the latest version now?`,
      'Version conflict',
      { confirmButtonText: 'Reload latest version', cancelButtonText: 'Close', type: 'warning' }
    ).then(() => { if (typeof reload === 'function') reload(); }).catch(() => {});
  } else {
    ElMessage.error(message);
  }
}

// Alpha 各處共用的寫法：!response.ok 時丟出帶 status 的 Error
export async function jsonOrThrow(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
    requestErr.status = response.status;
    throw requestErr;
  }
  return body;
}
