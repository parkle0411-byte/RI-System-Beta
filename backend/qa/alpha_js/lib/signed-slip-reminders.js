const DAY = 86400000;

export function reinsurerKey(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

export function requiredReinsurers(payload) {
  return [...new Set((Array.isArray(payload?.reinsurers) ? payload.reinsurers : [])
    .map((row) => reinsurerKey(row?.name)).filter(Boolean))];
}

export function dateUtc(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : NaN;
}

export function addDays(value, days) {
  const timestamp = dateUtc(value);
  return Number.isFinite(timestamp) ? new Date(timestamp + days * DAY).toISOString().slice(0, 10) : '';
}

export function daysBetween(from, to) {
  const start = dateUtc(from);
  const end = dateUtc(to);
  return Number.isFinite(start) && Number.isFinite(end) ? Math.floor((end - start) / DAY) : NaN;
}

export function taipeiToday(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit'
  }).format(now);
}

export function missingSignedReinsurers(payload, files) {
  const covered = new Set((Array.isArray(files) ? files : [])
    .filter((file) => file?.kind === 'signed')
    .flatMap((file) => Array.isArray(file?.reinsurers) ? file.reinsurers.map(reinsurerKey) : []));
  return requiredReinsurers(payload).filter((name) => !covered.has(name));
}

export function reminderDue(caseData, files, lastSuccessfulAlertOn, today) {
  if (!caseData || !['posted', 'closed'].includes(caseData.status) || !caseData.policyFrom) return null;
  const missing = missingSignedReinsurers(caseData, files);
  if (!missing.length) return null;
  const daysSinceEffective = daysBetween(caseData.policyFrom, today);
  if (!Number.isFinite(daysSinceEffective) || daysSinceEffective < 60) return null;
  const dueSince = lastSuccessfulAlertOn ? addDays(lastSuccessfulAlertOn, 7) : addDays(caseData.policyFrom, 60);
  if (!dueSince || today < dueSince) return null;
  return {
    missing,
    daysSinceEffective,
    firstReminder: !lastSuccessfulAlertOn,
    dueSince
  };
}

export function signedSlipTracking(caseData, files, today = taipeiToday()) {
  const required = requiredReinsurers(caseData);
  const missing = missingSignedReinsurers(caseData, files);
  const daysSinceEffective = daysBetween(caseData?.policyFrom, today);
  const eligibleStatus = ['posted', 'closed'].includes(caseData?.status);
  const firstReminderOn = caseData?.policyFrom ? addDays(caseData.policyFrom, 60) : '';
  return {
    complete: required.length > 0 && missing.length === 0,
    missing,
    eligibleStatus,
    daysSinceEffective: Number.isFinite(daysSinceEffective) ? daysSinceEffective : null,
    firstReminderOn,
    due: Boolean(
      eligibleStatus &&
      missing.length &&
      Number.isFinite(daysSinceEffective) &&
      daysSinceEffective >= 60
    ),
    today,
    cadenceDays: 7,
    outboundEnabled: true
  };
}

export function isReservedTestEmail(value) {
  const email = String(value || '').trim().toLowerCase();
  const domain = email.includes('@') ? email.split('@').pop() : '';
  // Bugfix (#10): this previously only matched example.com/.net/.org
  // exactly, missing any subdomain of them (e.g. "foo.example.com"), and
  // only matched the bare "localhost" domain, missing the ".localhost" TLD
  // (RFC 6761 reserves the whole *.localhost namespace, not just the bare
  // name) — either gap could let a real-looking test address slip through
  // and trigger a genuine outbound email.
  return domain === 'example' || domain === 'test' || domain === 'invalid' || domain === 'localhost'
    || domain === 'example.com' || domain === 'example.net' || domain === 'example.org'
    || domain.endsWith('.example') || domain.endsWith('.test') || domain.endsWith('.invalid')
    || domain.endsWith('.example.com') || domain.endsWith('.example.net') || domain.endsWith('.example.org')
    || domain.endsWith('.localhost');
}