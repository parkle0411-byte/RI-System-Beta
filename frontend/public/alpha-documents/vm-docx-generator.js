(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('jszip'));
  } else {
    root.RIDocx = factory(root.JSZip);
  }
}(typeof self !== 'undefined' ? self : this, function (JSZip) {
  'use strict';

  if (!JSZip) throw new Error('JSZip is required for Word generation');

  const MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  const REINSURANCE_INTRO = 'This Reinsurance is subject to the same terms and conditions as the Original Policy except as otherwise provided herein and Reinsurers will follow the Wordings, Clauses and Settlements of the Original Policy.';
  const ORIGINAL_CONDITIONS_TAIL = 'All other terms and conditions are subject to original policy wordings.';
  const LEGACY_CLAUSE_TITLES = {
    LMA3333: 'Reinsurers Liability Clause',
    INTERMEDIARY: 'Intermediary Clause (TW Insurance Brokers Ltd.)',
  };

  function text(value) {
    return value === null || value === undefined ? '' : String(value).trim();
  }
  // Document-only QS Property presentation. Never reorder or write Case rows.
  function newQs(c) { return c && c.placingRulesVersion === 'placing-qs-20261028-v1' && c.reinsuranceStructure === 'QS'; }
  function newCgl(c) { return newQs(c) && c.classOfBusiness === 'Commercial General Liability'; }
  function propertyExtras(c) { return newQs(c) && c.classOfBusiness === 'Property' && (!(c.reinsurers || []).some(r => r.name) || (c.reinsurers || []).some(r => r.name && !/\(Facility\)\s*$/i.test(r.name))); }
  function qsProperty(c) {
    return text(c && c.reinsuranceStructure).toUpperCase() === 'QS'
      && !text(c && c.parentTwRef)
      && (text(c && c.classCode) === 'PD' || text(c && c.classOfBusiness) === 'Property');
  }

  function qsStructure(c) {
    return text(c && c.reinsuranceStructure).toUpperCase() === 'QS';
  }

  function recipientLines(c) {
    const name = text(c && c.reinsured);
    const original = text(c && c.reinsuredAddress) || 'Taiwan (R.O.C.)';
    if (!qsProperty(c)) return [name, original].filter(Boolean);
    let address = original;
    if (name && address.toLowerCase().includes(name.toLowerCase())) {
      const at = address.toLowerCase().indexOf(name.toLowerCase());
      address = (address.slice(0, at) + address.slice(at + name.length)).trim().replace(/^[,;:\s]+/, '');
    }
    if (!address) address = 'Taiwan (R.O.C.)';
    if (/\r|\n/.test(address)) return [name].concat(address.split(/\r\n?|\n/).map(text).filter(Boolean)).filter(Boolean);
    const parts = address.split(/,\s*/).filter(Boolean);
    const country = parts.length > 1 && /^(?:Taiwan\b|Singapore\b|Hong Kong\b|Japan\b|China\b|United States\b|United Kingdom\b|U\.?S\.?A\.?\b|U\.?K\.?\b)/i.test(parts[parts.length - 1])
      ? parts.pop() : '';
    const end = parts.findIndex(part => /\b(?:Rd\.?|Road|St\.?|Street|Ave\.?|Avenue|Blvd\.?|Boulevard|Dr\.?|Drive|Ln\.?|Lane|Alley|Aly\.?)\s*$/i.test(part));
    const lines = end >= 0
      ? [parts.slice(0, end + 1).join(', '), parts.slice(end + 1).join(', ')]
      : [parts.join(', ')];
    return [name].concat(lines, [country]).filter(Boolean);
  }

  function coverPaymentTerms(c) {
    const suffix = ' Day Payment condition - LSW 3001 Premium Payment Clause';
    const valid = value => Number.isInteger(Number(value)) && Number(value) >= 15;
    if (!qsProperty(c)) return (text(c && c.paymentTermsDays) || '0') + suffix;
    if (c.installmentEnabled !== true) return valid(c.paymentTermsDays) ? Number(c.paymentTermsDays) + suffix : '';
    const rows = Array.isArray(c.performanceInstallments) ? c.performanceInstallments : [];
    const days = rows.map(row => text(row && row.paymentTermsDays) ? row.paymentTermsDays : c.paymentTermsDays);
    if (!days.length || days.some(value => !valid(value))) return '';
    if (days.every(value => Number(value) === Number(days[0]))) return Number(days[0]) + suffix;
    return days.map((value, index) => 'Instalment ' + (index + 1) + ': ' + Number(value) + suffix).join('\n');
  }

  function displayedRate(c, value) {
    return qsProperty(c) && (!text(value) || Number(value) === 0)
      ? '' : text(value) ? percent(value, 2) : '';
  }

  function originalClauseLines(value) {
    const pattern = /All other terms and conditions are subject to original policy wordings\.?/ig;
    return text(value).split(/\r?\n/).map(line => {
      const hasTail = /All other terms and conditions are subject to original policy wordings\.?/i.test(line);
      const body = line.replace(pattern, '').trim();
      return hasTail && /^(?:\d+[.)]|[-•])?\s*$/.test(body) ? '' : body;
    }).filter(Boolean);
  }

  function originalClauseText(c, value) {
    return qsStructure(c) ? originalClauseLines(value).concat([ORIGINAL_CONDITIONS_TAIL]).join('\n')
      : appendRequiredTail(value, ORIGINAL_CONDITIONS_TAIL);
  }

  function lossDocumentRows(c) {
    const rows = Array.isArray(c && c.lossRecord) ? c.lossRecord : [];
    if (!qsProperty(c)) return rows;
    return rows.map((row, index) => ({ row, index, date: Date.parse(row.date) }))
      .sort((a, b) => (Number.isFinite(b.date) ? b.date : -Infinity) - (Number.isFinite(a.date) ? a.date : -Infinity)
        || a.index - b.index).map(item => item.row);
  }

  function securityDocumentRows(c) {
    const rows = Array.isArray(c && c.reinsurers) ? c.reinsurers : [];
    return !qsProperty(c) ? rows : rows.map((row, index) => ({ row, index }))
      .sort((a, b) => number(b.row.sharePct) - number(a.row.sharePct) || a.index - b.index).map(item => item.row);
  }

  function generationDate(c) {
    const supplied = text(c && c.qsGenerationDate);
    if (qsProperty(c) && /^\d{4}-\d{2}-\d{2}$/.test(supplied)) return supplied;
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    const value = type => parts.find(part => part.type === type).value;
    return value('year') + '-' + value('month') + '-' + value('day');
  }

  function generatedFilename(c, prefix) {
    if (!qsProperty(c)) return prefix + '_' + safeRef(documentReference(c)) + '.docx';
    const safe = value => text(value).replace(/[\u0000-\u001f\u007f\\/:*?"<>|]/g, '_').replace(/\s+/g, ' ').trim().replace(/[. ]+$/, '');
    let ref = safeRef(documentReference(c));
    let insured = safe(c.originalInsured) || 'Original Insured';
    const suffix = '_' + generationDate(c) + '.docx';
    const build = () => prefix + '_' + ref + '_' + insured + suffix;
    // Keep the extension/date intact and stay within the attachment name and filesystem limits.
    const bytes = value => encodeURIComponent(value).replace(/%[A-F\d]{2}/gi, 'x').length;
    while (build().length > 180 || bytes(build()) > 240) {
      if (Array.from(insured).length > 12) insured = Array.from(insured).slice(0, -1).join('');
      else if (Array.from(ref).length > 12) ref = Array.from(ref).slice(0, -1).join('');
      else break;
    }
    return build();
  }

  function situationAddress(item) {
    return [text(item && item.address), text(item && item.postcode)].filter(Boolean).join(' ');
  }

  function number(value) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function currencyLabel(c) {
    const cur = text(c && c.currency).toUpperCase();
    return cur === 'USD' ? 'USD' : (cur || 'TWD');
  }

  function formatMoney(value, c) {
    const decimals = currencyLabel(c) !== 'TWD' || c?.premiumRounding === 'legacy-cents' ? 2 : 0;
    return number(value).toLocaleString('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  // Round with exactly the same rules and precision as the printed amount.
  function roundedMoney(value, c) {
    return Number(formatMoney(value, c).replace(/,/g, ''));
  }

  function money(value, c) {
    if (value === '' || value === null || value === undefined) return '';
    return `${currencyLabel(c)}${formatMoney(value, c)}`;
  }

  // 2026-10-21：保費取位正負對稱（-50.5 → -51），與會計（premium_money／premiumMoney）一致；legacy-cents 維持原算法
  function premiumRound(value, c) {
    const scale = currencyLabel(c) === 'TWD' && c?.premiumRounding !== 'legacy-cents' ? 1 : 100;
    const x = Number(value);
    if (c?.premiumRounding === 'legacy-cents' || !Number.isFinite(x)) return Math.round((x + Number.EPSILON) * scale) / scale;
    const rounded = Math.round((Math.abs(x) + Number.EPSILON) * scale) / scale;
    return x < 0 && rounded ? -rounded : rounded + 0;
  }

  function premiumAllocation(total, weights, c) {
    const sum = weights.reduce((a, b) => a + b, 0);
    const result = weights.map(weight => premiumRound(total * weight / sum, c));
    result[0] = premiumRound(result[0] + premiumRound(total - result.reduce((a, b) => a + b, 0), c), c);
    if (total > 0 && result[0] < 0 && c?.premiumRounding !== 'legacy-cents') {
      let remainder = premiumRound(-result[0], c);
      result[0] = 0;
      for (let i = 1; i < result.length && remainder > 0; i += 1) {
        const deduction = Math.min(result[i], remainder);
        result[i] = premiumRound(result[i] - deduction, c);
        remainder = premiumRound(remainder - deduction, c);
      }
    }
    return result;
  }

  function percent(value, decimals) {
    if (value === '' || value === null || value === undefined) return '';
    return `${number(value).toFixed(decimals)}%`;
  }

  function percentTrim(value, decimals) {
    if (value === '' || value === null || value === undefined) return '';
    const n = number(value);
    const rounded = Math.round((n + Number.EPSILON) * 100000000) / 100000000;
    const displayed = decimals === undefined
      ? (Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(8).replace(/0+$/, '').replace(/\.$/, ''))
      : rounded.toFixed(decimals);
    return `${displayed}%`;
  }

  // Match every displayed share and both documents' totals to the largest
  // meaningful decimal count among this case's reinsurers, capped at eight.
  function shareDecimalPlaces(reinsurers) {
    return reinsurers.reduce((decimals, row) => {
      const fraction = percentTrim(row.sharePct).match(/\.(\d+)%$/);
      return Math.max(decimals, fraction ? fraction[1].length : 0);
    }, 0);
  }

  function longDate(value) {
    if (!value) return '';
    const date = value instanceof Date ? value : new Date(`${value}T00:00:00Z`);
    if (Number.isNaN(date.getTime())) return text(value);
    return new Intl.DateTimeFormat('en-GB', {
      day: '2-digit', month: 'long', year: 'numeric', timeZone: 'UTC',
    }).format(date);
  }

  function documentDate(c) {
    if (qsProperty(c) && text(c.qsGenerationDate)) return longDate(generationDate(c));
    // Document issue dates follow Taiwan's calendar day, wherever Word is generated.
    return new Intl.DateTimeFormat('en-GB', {
      day: '2-digit', month: 'long', year: 'numeric', timeZone: 'Asia/Taipei',
    }).format(new Date());
  }

  // The document date line, plus "In case of query please contact <AE
  // name>" / "Email: <AE email>" for whichever AE is assigned to the case
  // (c.aeName/c.aeEmail, resolved from the Sales Staff master). Falls back
  // to just the date when there's no AE on file, rather than showing a
  // broken contact line.
  function contactBlock(c) {
    const lines = [documentDate(c)];
    const aeName = text(c && c.aeName);
    if (aeName) {
      lines.push(`In case of query please contact ${aeName}`);
      const aeEmail = text(c && c.aeEmail);
      if (aeEmail) lines.push(`Email: ${aeEmail}`);
    }
    return lines.join('\n');
  }

  // Cedant due date(s). With a single installment (the common case, and the
  // non-split default), this is unchanged: one date, matching NET_DUE which
  // already shows the whole-case total. With 2+ installments, showing only
  // the earliest date alongside the whole-case total would misstate the
  // schedule (implying the full amount is due that early), so instead this
  // returns one "<label>: <date> — <amount>" line per installment, with each
  // installment's cedant amount weighted by its saved premium/ratio. The
  // first installment in Case order absorbs any rounding remainder so the
  // lines foot exactly to NET_DUE, using the same currency precision as
  // the printed invoice amounts. When a positive total would make the first
  // amount negative, the first is floored at zero and the remaining shortfall
  // is deducted from following installments in Case order.
  function debitPaymentRows(c) {
    if (!c) return [];
    const validTerms = (value) => {
      const number = Number(value);
      return Number.isInteger(number) && number >= 15 ? number : null;
    };
    const reinsurers = Array.isArray(c.reinsurers) ? c.reinsurers : [];
    const installmentEnabled = c.installmentEnabled === true;
    const rawInstallments = installmentEnabled && Array.isArray(c.performanceInstallments) && c.performanceInstallments.length
      ? c.performanceInstallments : [{ performanceMonth: '', paymentBaseDate: endorsementNote(c) ? c.endoEffectiveDate : c.policyFrom, paymentTermsDays: c.paymentTermsDays }];
    const weights = rawInstallments.map((row) => {
      if (!installmentEnabled) return 1;
      const premium = Number(row.premium);
      if (Number.isFinite(premium) && row.premium !== '' && row.premium != null) return Math.max(0, premium);
      const ratio = Number(row.ratio);
      return Math.max(0, Number.isFinite(ratio) ? ratio : 0);
    });
    let weightSum = weights.reduce((a, b) => a + b, 0);
    let w = weights;
    if (weightSum <= 0) { weightSum = rawInstallments.length; w = rawInstallments.map(() => 1); }
    // Allocate each reinsurer's T1 using the same plan as posted transactions.
    // Rounding a combined Net Due instead can move cents between periods.
    const t1s = financials(c).t1s;
    const allocations = t1s.map(total => premiumAllocation(total, w, c));
    const installmentAmounts = c.propertyInstallmentNet?.length === rawInstallments.length ? c.propertyInstallmentNet : rawInstallments.map((_, i) => premiumRound(allocations.reduce((sum, row) => sum + row[i], 0), c));
    // Mirrors build_payment_schedule: new (basis 'case') and AUW cases use the Cedant's own terms; older cases the shortest reinsurer terms.
    const cedantOwnTerms = true;
    const rows = rawInstallments.map((installment, index) => {
      const terms = reinsurers.map((reinsurer, rIndex) => {
        const map = installment.reinsurerPaymentTerms && typeof installment.reinsurerPaymentTerms === 'object' ? installment.reinsurerPaymentTerms : {};
        return validTerms(map['r' + (rIndex + 1)]);
      }).filter((value) => value != null);
      const ownTerms = validTerms(installment.paymentTermsDays);
      const shortest = cedantOwnTerms ? ownTerms : (terms.length ? Math.min(...terms) : ownTerms);
      const baseDate = installment.paymentBaseDate || c.policyFrom;
      let dueDate = '';
      if (baseDate && shortest != null) {
        const date = new Date(baseDate + 'T00:00:00Z');
        if (!Number.isNaN(date.getTime())) {
          // Debit Note: the date we need the Cedant's funds (15 days before due). Credit Note: the date we pay.
          date.setUTCDate(date.getUTCDate() + shortest - (c.creditNote ? 0 : 15));
          dueDate = date.toISOString().slice(0, 10);
        }
      }
      const amount = installmentAmounts[index];
      const label = installmentEnabled ? `Instalment ${index + 1}` : '';
      return { label, dueDate, amount };
    }).filter((row) => row.dueDate);
    return rows;
  }

  function debitDueDate(c) {
    const rows = debitPaymentRows(c);
    if (!rows.length) return '';
    if (rows.length === 1) return longDate(rows[0].dueDate);
    return rows.map((row) => `${row.label}: ${longDate(row.dueDate)} — ${money(row.amount, c)}`).join('\n');
  }

  function policyTime(value) {
    return value === '00:00' ? '00:00' : '12:00';
  }

  function period(c, full) {
    const from = longDate(c && c.policyFrom) || '—';
    const to = longDate(c && c.policyTo) || '—';
    const fromTime = policyTime(c && c.policyFromTime);
    const toTime = policyTime(c && c.policyToTime);
    return full
      ? `From ${from} at ${fromTime} to ${to} at ${toTime} Local Standard Time at the location of the Reinsured.`
      : `From ${from} ${fromTime} to ${to} ${toTime}`;
  }

  function basisOfValuation(c) {
    return text(c && c.basisOfValuation) === 'Other'
      ? text(c && c.basisOfValuationOther)
      : text(c && c.basisOfValuation);
  }

  function appendRequiredTail(value, tail) {
    const body = text(value);
    if (!body) return tail;
    if (body.toLowerCase().includes(tail.toLowerCase())) return body;
    return `${body}\n${tail}`;
  }

  function isFacility(name) {
    return /\(Facility\)\s*$/i.test(text(name));
  }

  function stripFacility(name) {
    return text(name).replace(/\s*\(Facility\)\s*$/i, '');
  }

  function isAuwReinsurer(name) {
    return text(name).split(/\s+/).join(' ').toLowerCase() === "lloyd's underwriter syndicate no. 0609 auw (facility)";
  }

  function clauseRank(code) {
    if (code === 'LMA3333') return [-2, ''];
    if (code === 'INTERMEDIARY') return [-1, ''];
    if (/^LMA/i.test(code)) return [0, code];
    if (/^NMA/i.test(code)) return [1, code];
    if (/^LPO/i.test(code)) return [2, code];
    return [3, code];
  }

  function clauseDetails(c) {
    const snapshots = Array.isArray(c && c.clauseDetails) ? c.clauseDetails : [];
    const codes = Array.isArray(c && c.clauses) ? c.clauses : [];
    const byCode = new Map();
    snapshots.forEach(item => {
      const code = text(item && item.code).toUpperCase();
      if (code) byCode.set(code, { code, title: text(item.title) || code });
    });
    codes.forEach(raw => {
      const code = text(raw).toUpperCase();
      if (code && !byCode.has(code)) byCode.set(code, { code, title: LEGACY_CLAUSE_TITLES[code] || '' });
    });
    return Array.from(byCode.values()).sort((a, b) => {
      const ar = clauseRank(a.code);
      const br = clauseRank(b.code);
      return ar[0] - br[0] || ar[1].localeCompare(br[1], 'en', { sensitivity: 'base' });
    });
  }

  function clauseLine(item) {
    if (!item) return '';
    return text(item.title) || item.code;
  }

  function documentReference(c) {
    const refs = [text(c && c.twRef), text(c && c.manualTwRef)]
      .flatMap(value => value.split(/\s+&\s+/)).filter(Boolean);
    return Array.from(new Set(refs)).join(' & ') || 'DRAFT';
  }

  function sumInsuredRows(c) {
    const rows = Array.isArray(c && c.sumInsured) ? c.sumInsured : [];
    const named = (Array.isArray(c && c.reinsurers) ? c.reinsurers : []).filter(r => text(r && r.name));
    const facility = named.length > 0 && named.every(r => isFacility(r.name));
    const items = rows.filter(row => row && (text(row.category) || number(row.amount) !== 0)).map(row => ({
      label: text(row.category) || '—', amount: formatMoney(row.amount, c), numericAmount: number(row.amount),
      locationIndex: Number.isInteger(Number(row.locationIndex)) && Number(row.locationIndex) >= 0 ? Number(row.locationIndex) : 0,
    }));
    if (facility) return items;
    const locations = Array.from(new Set(items.map(row => row.locationIndex))).sort((a, b) => a - b);
    return locations.flatMap(index => [{ label: `Location ${index + 1}`, amount: '', numericAmount: 0, heading: true }, ...items.filter(row => row.locationIndex === index)]);
  }

  function lossValues(c) {
    const rows = Array.isArray(c && c.lossRecord) ? c.lossRecord : [];
    const years = Number.parseInt(c && c.lossRecordYears, 10);
    const periodYears = years > 0 ? years : 5;
    const countText = rows.length === 0 ? 'Loss Clean' : `${rows.length} ${rows.length === 1 ? 'loss' : 'losses'}`;
    let summary = years === 0 && rows.length === 0 && c && c.newOrRenew === 'New' && !c.renewedFromTwRef
      ? 'Loss Clean since operation.'
      : `${countText} in the past ${periodYears} ${periodYears === 1 ? 'year' : 'years'}`;
    if (text(c && c.lossAdvisedDate)) summary += ` (as advised by TW Insurance Brokers Ltd. on ${longDate(c.lossAdvisedDate)})`;
    return {
      summary,
      dates: rows.map(row => longDate(row.date) || '—').join('\n'),
      causes: rows.map(row => text(row.cause) || '—').join('\n'),
      paid: rows.map(row => formatMoney(row.lossPaid, c)).join('\n'),
    };
  }

  function financials(c) {
    if (c && c.propertyFinancials) return c.propertyFinancials;
    const reinsurers = Array.isArray(c && c.reinsurers) ? c.reinsurers : [];
    const order = reinsurers.reduce((total, row) => total + number(row.sharePct), 0);
    const rawPremium = number(c && c.originalPremium);
    const originalPremium = ['TWD', 'USD'].includes(currencyLabel(c)) && c?.premiumRounding !== 'legacy-cents' ? premiumRound(rawPremium, c) : rawPremium;
    const propertyOriginal = !c?.accountingLegacyMath && c?.premiumRounding !== 'legacy-cents' && c?.propertyOriginalRules !== 'historical' && reinsurers.length > 0 && reinsurers.every(r=>["Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)", "Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)", "Great American Insurance Company, Singapore Branch (Facility)", "QBE Hongkong & Shanghai Insurance Limited (Facility)", "Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)"].some(n=>n.toLowerCase()===String(r.name||'').trim().toLowerCase()) || !/facility|\bpws\b/i.test(r.name || ''));
    const components = (propertyOriginal ? [{sharePct:order}] : reinsurers).map(row => {
      const cp = premiumRound(originalPremium * number(row.sharePct) / 100, c);
      const commission = premiumRound(cp * number(c && c.riCommPct) / 100, c);
      const tax = premiumRound(cp * number(c && c.taxPct) / 100, c);
      return { cp, commission, tax, t1: premiumRound(cp - commission - tax, c) };
    });
    const sum = key => premiumRound(components.reduce((total, row) => total + row[key], 0), c);
    const cededPremium = sum('cp'), commission = sum('commission'), tax = sum('tax'), netDue = sum('t1');
    return { order, originalPremium, cededPremium, commission, tax, netDue, t1s: components.map(row => row.t1) };
  }

  function commonValues(c) {
    const fin = financials(c);
    const sums = sumInsuredRows(c);
    const losses = lossValues(c);
    const situations = Array.isArray(c && c.situations) ? c.situations : [];
    const reinsurers = Array.isArray(c && c.reinsurers) ? c.reinsurers : [];
    const shareDecimals = shareDecimalPlaces(reinsurers);
    const clauses = clauseDetails(c);
    const addressLines = recipientLines(c);
    const originalExclusions = originalClauseText(c, c && c.originalExclusions);
    const originalConditions = originalClauseText(c, c && c.originalConditions);
    const reinsuranceConditions = [REINSURANCE_INTRO].concat(clauses.map(item => `•\u00a0${clauseLine(item)}`)).join('\n');
    return {
      RECIPIENT_BLOCK: addressLines.join('\n'),
      CONTACT_BLOCK: contactBlock(c),
      TW_REF: documentReference(c),
      TYPE: text(c && c.type),
      ORIGINAL_INSURED: text(c && c.originalInsured),
      REINSURED: text(c && c.reinsured),
      PERIOD: period(c, true),
      PERIOD_SHORT: period(c, false),
      INTEREST: text(c && c.interest) || (newCgl(c) ? 'Reinsurance of the Reinsured’s liability under the original policy.' : ''),
      LIMIT_OF_LIABILITY: money(c && c.limitOfLiability, c) + (newCgl(c) ? ' each occurrence' : ''),
      AGGREGATE_LIMIT: newQs(c) ? (Number(c.aggregateLimit) ? money(c.aggregateLimit,c) : '') : Array.isArray(c && c.cglInformationRows) && (String(c.reinsuranceStructure || '').toUpperCase() === 'QS' || !text(c && c.aggregateLimit)) ? '' : money(c && c.aggregateLimit, c),
      UNDERLYING_LIMITS: qsProperty(c) ? '' : Array.isArray(c && c.cglInformationRows) && text(c && c.reinsuranceStructure).toUpperCase() !== 'XOL' ? '' : text(c && c.underlyingLimits),
      SUB_LIMITS: text(c && c.subLimits),
      DEDUCTIBLES: text(c && c.deductibles),
      REINSURED_RETENTION: text(c && c.reinsuredRetention) || ((qsProperty(c) || newCgl(c)) ? "Advice of Reinsured's retention waived." : ""),
      REINSTATEMENT_PROVISIONS: text(c && c.reinstatementProvisions),
      INDEMNITY_PERIOD: Array.isArray(c && c.cglInformationRows) ? '' : text(c && c.indemnityPeriod),
      ORIGINAL_EXCLUSIONS: originalExclusions,
      LOCATION: situations.map((item, index) => `${index + 1}. ${situationAddress(item)}`).join('\n'),
      SITUATION: situations.map((item, index) => `${index + 1}. ${situationAddress(item)}`).join('\n'),
      TOTAL_SUM_INSURED: money(sums.reduce((total, row) => total + row.numericAmount, 0), c),
      POLICY_LIMIT: newQs(c) ? (Number(c.aggregateLimit) ? money(c.aggregateLimit,c) : '') : Array.isArray(c && c.cglInformationRows) && (String(c.reinsuranceStructure || '').toUpperCase() === 'QS' || !text(c && c.aggregateLimit)) ? '' : money(c && c.aggregateLimit, c),
      BASIS_OF_VALUATION: Array.isArray(c && c.cglInformationRows) ? '' : basisOfValuation(c),
      ORIGINAL_CONDITIONS: originalConditions,
      REINSURANCE_CONDITIONS: reinsuranceConditions,
      LOSS_PAYEE: Array.isArray(c && c.cglInformationRows) || (newQs(c) && !propertyExtras(c)) ? '' : text(c && c.lossPayee),
      NOTICES: text(c && c.notices),
      EXPRESS_WARRANTIES: text(c && c.expressWarranties) || (newQs(c) ? 'None - other than as may exist in this document or in the wording that forms part of this contract.' : ''),
      CONDITIONS_PRECEDENT: text(c && c.conditionsPrecedent) || (newQs(c) ? 'None - other than as may exist in this document or in the wording that forms part of this contract.' : ''),
      SUBJECTIVITIES: text(c && c.subjectivities) || (newQs(c) ? 'None - other than as may exist in this document or in the wording that forms part of this contract.' : ''),
      PREMIUM: money(c && c.originalPremium, c) + (Array.isArray(c && c.cglInformationRows) && c.cglAnnual !== false ? ' (Annual)' : ''),
      ORDER_HEREON: `${percentTrim(fin.order, shareDecimals)} of 100%`,
      ORDER_HEREON_DEBIT: percentTrim(fin.order, shareDecimals),
      CEDING_COMMISSION: displayedRate(c, c && c.riCommPct),
      TAX: displayedRate(c, c && c.taxPct),
      PAYMENT_TERMS: coverPaymentTerms(c),
      DEBIT_PAYMENT_TERMS: debitDueDate(c) || '—',
      OCCUPATION: text(c && c.occupation),
      CONSTRUCTION: text(c && c.construction),
      SUM_INSURED_LABELS: sums.map(row => row.label).join('\n'),
      SUM_INSURED_AMOUNTS: sums.map(row => row.amount).join('\n'),
      SUM_INSURED_TOTAL: formatMoney(sums.reduce((total, row) => total + row.numericAmount, 0), c),
      LOSS_SUMMARY: losses.summary,
      LOSS_DATES: losses.dates,
      LOSS_CAUSES: losses.causes,
      LOSS_PAID: losses.paid,
      SPECIAL_AGREEMENT: c && Array.isArray(c.cglInformationRows) && c.cglInformation?.specialAgreementApplies !== 'applicable' ? '' : text(c && c.specialAgreement),
      SECURITY_NAMES: reinsurers.map(row => stripFacility(row.name) || '(Reinsurer)').join('\n'),
      SECURITY_SHARES: reinsurers.map(row => percentTrim(row.sharePct, shareDecimals)).join('\n'),
      LOSS_LIMIT: money(c && c.limitOfLiability, c),
      ORIGINAL_PREMIUM: formatMoney(fin.originalPremium, c),
      CEDED_PREMIUM: formatMoney(fin.cededPremium, c),
      COMMISSION_AMOUNT: formatMoney(fin.commission, c),
      TAX_AMOUNT: formatMoney(fin.tax, c),
      NET_DUE: formatMoney(fin.netDue, c),
    };
  }

  function xmlEscape(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&apos;');
  }

  function xmlValue(value) {
    return xmlEscape(value).replace(/\r?\n/g, '</w:t><w:br/><w:t xml:space="preserve">');
  }

  // Reserve the inline logo's actual height explicitly instead of relying on
  // inherited paragraph spacing in Word-compatible renderers.
  function reserveHeaderLogoSpace(xml) {
    return xml.replace(/<w:p\b[^>]*>[\s\S]*?<\/w:p>/g, paragraph => {
      const extent = paragraph.match(/<wp:inline\b[\s\S]*?<wp:extent\b[^>]*\bcy="(\d+)"/);
      if (!extent) return paragraph;
      const line = Math.ceil(Number(extent[1]) / 635); // EMU to twips.
      if (!Number.isFinite(line) || line <= 0) return paragraph;
      return paragraph.replace(/<w:pPr>([\s\S]*?)<\/w:pPr>/, (tag, properties) => {
        let content = properties.replace(/<w:keepLines\b[^>]*\/>/g, '')
          .replace(/<w:spacing\b[^>]*\/>/g, '');
        content = content.replace(/(<w:pStyle\b[^>]*\/>|^)/, '$1<w:keepLines/>');
        const spacing = `<w:spacing w:before="0" w:after="0" w:line="${line}" w:lineRule="atLeast"/>`;
        const alignment = content.search(/<w:(?:jc|rPr)\b/);
        content = alignment < 0 ? content + spacing : content.slice(0, alignment) + spacing + content.slice(alignment);
        return `<w:pPr>${content}</w:pPr>`;
      });
    });
  }

  function normalizeRunTypography(xml) {
    const required = '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="標楷體" w:cs="Arial"/><w:sz w:val="20"/><w:szCs w:val="20"/>';
    return xml.replace(/<w:r\b([^>]*)>([\s\S]*?)<\/w:r>/g, (run, attrs, body) => {
      if (/^\s*<w:rPr\b[^>]*\/>/.test(body)) {
        body = body.replace(/^\s*<w:rPr\b[^>]*\/>/, `<w:rPr>${required}</w:rPr>`);
      } else if (/^\s*<w:rPr\b/.test(body)) {
        body = body.replace(/<w:rPr\b([^>]*)>([\s\S]*?)<\/w:rPr>/, (props, propAttrs, inner) => {
          const cleaned = inner
            .replace(/<w:rFonts\b[^>]*\/>/g, '')
            .replace(/<w:sz\b[^>]*\/>/g, '')
            .replace(/<w:szCs\b[^>]*\/>/g, '');
          return `<w:rPr${propAttrs}>${required}${cleaned}</w:rPr>`;
        });
      } else {
        body = `<w:rPr>${required}</w:rPr>${body}`;
      }
      return `<w:r${attrs}>${body}</w:r>`;
    });
  }

  // Fields that are genuinely optional on a case: when blank, the whole
  // table row carrying that field is removed from the document rather
  // than leaving an empty-looking row. Fields that always carry content
  // (defaults, boilerplate, or required case data) are left out of this
  // list on purpose.
  const OPTIONAL_KEYS = [
    'AGGREGATE_LIMIT', 'POLICY_LIMIT', 'LOSS_LIMIT',
    'UNDERLYING_LIMITS', 'SUB_LIMITS', 'DEDUCTIBLES', 'REINSURED_RETENTION',
    'REINSTATEMENT_PROVISIONS', 'INDEMNITY_PERIOD', 'BASIS_OF_VALUATION', 'LOSS_PAYEE', 'NOTICES',
    'EXPRESS_WARRANTIES', 'CONDITIONS_PRECEDENT', 'SUBJECTIVITIES',
    'OCCUPATION', 'CONSTRUCTION', 'CEDING_COMMISSION', 'TAX',
    'SPECIAL_AGREEMENT',
  ];

  // Parses a document.xml fragment into "table frames": one entry per
  // <w:tbl>, each holding the list of its own DIRECT <w:tr> child rows
  // (start/end character offsets). Nesting-aware, so a row inside a
  // nested table (e.g. a breakdown table placed inside one cell of an
  // outer two-column layout) is never confused with its outer table's
  // rows — this matters because several Cover Note sections are laid
  // out as a table nested inside another table.
  function scanTableFrames(xml) {
    const tagRe = /<(\/)?w:(tbl|tr)\b([^>]*?)(\/?)>/g;
    const frames = [];
    const stack = [];
    let m;
    while ((m = tagRe.exec(xml))) {
      const closing = !!m[1];
      const name = m[2];
      const selfClosing = m[4] === '/';
      if (selfClosing) continue;
      if (name === 'tbl') {
        if (!closing) {
          stack.push({ rows: [], tblStart: m.index });
        } else {
          const frame = stack.pop();
          if (frame) {
            frame.tblEnd = tagRe.lastIndex;
            frames.push(frame);
          }
        }
      } else if (name === 'tr') {
        const top = stack[stack.length - 1];
        if (!top) continue;
        if (!closing) {
          top._openStart = m.index;
        } else if (top._openStart !== undefined) {
          top.rows.push({ start: top._openStart, end: tagRe.lastIndex });
          top._openStart = undefined;
        }
      }
    }
    return frames;
  }

  // The bank block is two rows within the Debit Note's larger layout table.
  // Keep its header with the account row without binding the entire document.
  function keepDebitBankDetailsTogether(xml) {
    const edits = [];
    scanTableFrames(xml).forEach(frame => {
      frame.rows.forEach((row, index) => {
        const header = xml.slice(row.start, row.end).replace(/<[^>]+>/g, '');
        const account = frame.rows[index + 1];
        if (!header.includes('Beneficiary Name') || !header.includes('Account No.') || !header.includes('Swift Code') || !account) return;
        if (!xml.slice(account.start, account.end).includes('TPBKTWTP')) return;
        [row, account].forEach((part, partIndex) => {
          let updated = xml.slice(part.start, part.end);
          updated = updated.replace(/<w:cantSplit\b[^>]*\/>/g, '');
          updated = updated.replace(/<w:trPr\b[^>]*>/, '$&<w:cantSplit/>');
          updated = updated.replace(/<w:p\b[^>]*>[\s\S]*?<\/w:p>/g, paragraph => {
            const properties = `${partIndex === 0 ? '<w:keepNext/>' : ''}<w:keepLines/>`;
            const cleaned = paragraph.replace(/<w:(?:keepNext|keepLines)\b[^>]*\/>/g, '');
            return /<w:pPr\b/.test(cleaned)
              ? cleaned.replace(/<w:pPr\b[^>]*>/, '$&' + properties)
              : cleaned.replace(/<w:p\b[^>]*>/, '$&<w:pPr>' + properties + '</w:pPr>');
          });
          edits.push({ start: part.start, end: part.end, xml: updated });
        });
      });
    });
    edits.sort((a, b) => b.start - a.start).forEach(edit => {
      xml = xml.slice(0, edit.start) + edit.xml + xml.slice(edit.end);
    });
    return xml;
  }

  // Apply the chapter break to INFORMATION's first paragraph, before Case
  // values are inserted, so literal Case text cannot select another table.
  function startCoverInformationPage(xml) {
    const frames = scanTableFrames(xml);
    const table = frames.find(frame => !frames.some(parent =>
      parent.tblStart < frame.tblStart && parent.tblEnd > frame.tblEnd)
      && /<w:t\b[^>]*>INFORMATION<\/w:t>/.test(xml.slice(frame.tblStart, frame.tblEnd)));
    if (!table) return xml;
    const content = xml.slice(table.tblStart, table.tblEnd).replace(/<w:p\b[^>]*>[\s\S]*?<\/w:p>/, paragraph => {
      if (/<w:pageBreakBefore\b/.test(paragraph)) {
        return paragraph.replace(/<w:pageBreakBefore\b[^>]*\/>/, '<w:pageBreakBefore/>');
      }
      return /<w:pPr\b/.test(paragraph)
        ? paragraph.replace(/<w:pPr\b[^>]*>/, '$&<w:pageBreakBefore/>')
        : paragraph.replace(/<w:p\b[^>]*>/, '$&<w:pPr><w:pageBreakBefore/></w:pPr>');
    });
    return xml.slice(0, table.tblStart) + content + xml.slice(table.tblEnd);
  }

  // A standalone page-break run can overflow onto an empty page before
  // breaking again. Keep each chapter break on its compact separator instead.
  // Word/Writer can ignore a page-break run placed in only one table cell.
  // Split at the intended row so both the label and value start on the new
  // page, instead of allowing the value to collide with the page footer.
  function splitCoverTablePageBreaks(xml) {
    const frames = scanTableFrames(xml);
    const edits = [];
    const pageBreak = /<w:br\b[^>]*w:type="page"[^>]*\/>/g;
    const separator = '<w:p><w:pPr><w:keepNext/><w:pageBreakBefore/><w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/><w:rPr><w:sz w:val="2"/><w:szCs w:val="2"/></w:rPr></w:pPr></w:p>';
    frames.filter(frame => !frames.some(parent =>
      parent.tblStart < frame.tblStart && parent.tblEnd > frame.tblEnd)).forEach(frame => {
      const breaks = frame.rows.slice(1).filter(row =>
        /<w:br\b[^>]*w:type="page"[^>]*\/>/.test(xml.slice(row.start, row.end)));
      if (!breaks.length) return;
      const opening = xml.slice(frame.tblStart, frame.rows[0].start);
      let cursor = frame.tblStart;
      let replacement = '';
      breaks.forEach(row => {
        replacement += xml.slice(cursor, row.start) + '</w:tbl>' + separator + opening
          + xml.slice(row.start, row.end).replace(pageBreak, '');
        cursor = row.end;
      });
      replacement += xml.slice(cursor, frame.tblEnd);
      edits.push({ start: frame.tblStart, end: frame.tblEnd, xml: replacement });
    });
    edits.sort((a, b) => b.start - a.start).forEach(edit => {
      xml = xml.slice(0, edit.start) + edit.xml + xml.slice(edit.end);
    });
    return xml;
  }

  function normalizeCoverPageBreaks(xml) {
    xml = splitCoverTablePageBreaks(xml);
    // Keep each label and its value on the same page when the row fits.
    xml = xml.replace(/<w:tr\b[^>]*>(?:<w:trPr\b[^>]*>[\s\S]*?<\/w:trPr>)?/g, row => {
      if (/<w:cantSplit\b/.test(row)) return row;
      return /<w:trPr\b/.test(row)
        ? row.replace(/<w:trPr\b[^>]*>/, '$&<w:cantSplit/>')
        : row + '<w:trPr><w:cantSplit/></w:trPr>';
    });
    const frames = scanTableFrames(xml);
    const tables = frames.filter(frame => !frames.some(parent =>
      parent.tblStart < frame.tblStart && parent.tblEnd > frame.tblEnd))
      .sort((a, b) => a.tblStart - b.tblStart);
    const edits = [];
    tables.slice(1).forEach((table, index) => {
      const start = tables[index].tblEnd;
      const gap = xml.slice(start, table.tblStart);
      if (!/<w:br\b[^>]*w:type="page"/.test(gap) || !isBlankRowText(gap)) return;
      if (/<w:(?:tbl|drawing|pict|object|fldChar|instrText|sectPr|bookmarkStart|commentRangeStart|footnoteReference|endnoteReference)\b/.test(gap)) return;
      const separator = '<w:p><w:pPr><w:keepNext/><w:pageBreakBefore/><w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/><w:rPr><w:sz w:val="2"/><w:szCs w:val="2"/></w:rPr></w:pPr></w:p>';
      edits.push({ start, end: table.tblStart, xml: separator });
    });
    edits.reverse().forEach(edit => {
      xml = xml.slice(0, edit.start) + edit.xml + xml.slice(edit.end);
    });
    return xml;
  }

  // Replace only the consecutive empty rows immediately before a signature
  // with one 12 pt line; keep that line with the signature on the next page.
  function normalizeSignatureSpacing(xml) {
    const edits = [];
    const blankParagraph = '<w:p><w:pPr><w:keepNext/><w:keepLines/><w:snapToGrid w:val="0"/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="exact"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="標楷體" w:cs="Arial"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:pPr></w:p>';
    scanTableFrames(xml).forEach(frame => {
      frame.rows.forEach((row, index) => {
        if (!/<w:drawing\b/.test(xml.slice(row.start, row.end))) return;
        if (!frame.rows.slice(index + 1).some(part =>
          xml.slice(part.start, part.end).replace(/<[^>]+>/g, '').includes('TW Insurance Brokers Ltd.'))) return;
        let first = index;
        while (first > 0) {
          const previous = frame.rows[first - 1];
          const value = xml.slice(previous.start, previous.end);
          if (!isBlankRowText(value) || /<w:(?:drawing|pict|object|tbl|vMerge|fldChar|instrText|br|sectPr|bookmarkStart|bookmarkEnd|commentRangeStart|commentRangeEnd|footnoteReference|endnoteReference)\b/.test(value)) break;
          first -= 1;
        }
        if (first === index) return;
        const last = frame.rows[index - 1];
        let spacer = xml.slice(last.start, last.end)
          .replace(/<w:(?:trHeight|cantSplit)\b[^>]*\/>/g, '')
          .replace(/<w:trPr\b[^>]*>/, '$&<w:cantSplit/><w:trHeight w:val="240" w:hRule="exact"/>');
        spacer = spacer.replace(/<w:p\b[^>]*\/>|<w:p\b[^>]*>[\s\S]*?<\/w:p>/g, blankParagraph);
        edits.push({ start: frame.rows[first].start, end: last.end, xml: spacer });
      });
    });
    edits.sort((a, b) => b.start - a.start).forEach(edit => {
      xml = xml.slice(0, edit.start) + edit.xml + xml.slice(edit.end);
    });
    return xml;
  }

  // Keep the signature image and closing text together, including the
  // intervening blank rows and the Debit Note's E&OE line.
  function keepSignatureBlockTogether(xml) {
    const edits = [];
    scanTableFrames(xml).forEach(frame => {
      frame.rows.forEach((row, signatureIndex) => {
        if (!/<w:drawing\b/.test(xml.slice(row.start, row.end))) return;
        const companyIndex = frame.rows.findIndex((part, index) => index > signatureIndex
          && xml.slice(part.start, part.end).replace(/<[^>]+>/g, '').includes('TW Insurance Brokers Ltd.'));
        if (companyIndex < 0) return;
        const eoeIndex = frame.rows.findIndex((part, index) => index > companyIndex
          && /E(?:&amp;|&)OE/.test(xml.slice(part.start, part.end).replace(/<[^>]+>/g, '')));
        const endIndex = eoeIndex < 0 ? companyIndex : eoeIndex;
        frame.rows.slice(signatureIndex, endIndex + 1).forEach((part, offset) => {
          let updated = xml.slice(part.start, part.end).replace(/<w:cantSplit\b[^>]*\/>/g, '');
          updated = updated.replace(/<w:trPr\b[^>]*>/, '$&<w:cantSplit/>');
          updated = updated.replace(/<w:p\b[^>]*>[\s\S]*?<\/w:p>/g, paragraph => {
            const properties = `${signatureIndex + offset < endIndex ? '<w:keepNext/>' : ''}<w:keepLines/>`;
            const cleaned = paragraph.replace(/<w:(?:keepNext|keepLines)\b[^>]*\/>/g, '');
            return /<w:pPr\b/.test(cleaned)
              ? cleaned.replace(/<w:pPr\b[^>]*>/, '$&' + properties)
              : cleaned.replace(/<w:p\b[^>]*>/, '$&<w:pPr>' + properties + '</w:pPr>');
          });
          edits.push({ start: part.start, end: part.end, xml: updated });
        });
      });
    });
    edits.sort((a, b) => b.start - a.start).forEach(edit => {
      xml = xml.slice(0, edit.start) + edit.xml + xml.slice(edit.end);
    });
    return xml;
  }

  function findFrameForToken(xml, frames, token) {
    const idx = xml.indexOf(token);
    if (idx === -1) return null;
    for (let f = 0; f < frames.length; f += 1) {
      const rows = frames[f].rows;
      const rowIndex = rows.findIndex(r => idx >= r.start && idx < r.end);
      if (rowIndex !== -1) return { frame: frames[f], rowIndex };
    }
    return null;
  }

  // Use a separate table so Word can repeat the heading across pages.
  // Split only the template payment row; dates and amounts share the same
  // calculation as the legacy DEBIT_PAYMENT_TERMS value.
  function renderDebitInstalments(xml, c) {
    if (!c || c.installmentEnabled !== true) return xml;
    const rows = debitPaymentRows(c);
    if (rows.length < 2) return xml;
    const found = findFrameForToken(xml, scanTableFrames(xml), '{{DEBIT_PAYMENT_TERMS}}');
    if (!found) return xml;
    const frame = found.frame;
    const target = frame.rows[found.rowIndex];
    const prefix = xml.slice(frame.tblStart, frame.rows[0].start);
    const page = xml.match(/<w:pgSz\b[^>]*w:w="(\d+)"/);
    const margins = xml.match(/<w:pgMar\b[^>]*>/);
    const margin = name => Number((margins && margins[0].match(new RegExp('w:' + name + '="(\\d+)"')) || [0, 1080])[1]);
    const width = Math.max(1, Number(page ? page[1] : 11906) - margin('left') - margin('right'));
    const widths = [Math.round(width * 0.25), Math.round(width * 0.40)];
    widths.push(width - widths[0] - widths[1]);
    const paragraph = (value, align, heading) => '<w:p><w:pPr>'
      + (heading ? '<w:keepNext/>' : '')
      + '<w:snapToGrid w:val="0"/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
      + '<w:jc w:val="' + align + '"/></w:pPr><w:r><w:rPr>'
      + '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="標楷體"/>'
      + (heading ? '<w:b/>' : '') + '<w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
      + '<w:t xml:space="preserve">' + xmlEscape(value) + '</w:t></w:r></w:p>';
    const tableRow = (values, heading) => '<w:tr><w:trPr><w:cantSplit/>'
      + (heading ? '<w:tblHeader/>' : '') + '</w:trPr>'
      + values.map((value, index) => '<w:tc><w:tcPr><w:tcW w:w="' + widths[index]
        + '" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>'
        + paragraph(value, heading ? 'center' : ['left', 'center', 'right'][index], heading) + '</w:tc>').join('') + '</w:tr>';
    const border = ['top', 'left', 'bottom', 'right', 'insideH', 'insideV'].map(name => '<w:' + name + ' w:val="single" w:sz="4" w:color="000000"/>').join('');
    const table = '<w:tbl><w:tblPr><w:tblW w:w="' + width + '" w:type="dxa"/><w:jc w:val="center"/>'
      + '<w:tblBorders>' + border + '</w:tblBorders><w:tblLayout w:type="fixed"/>'
      + '<w:tblCellMar><w:top w:w="20" w:type="dxa"/><w:left w:w="100" w:type="dxa"/>'
      + '<w:bottom w:w="20" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>'
      + '<w:tblGrid>' + widths.map(value => '<w:gridCol w:w="' + value + '"/>').join('') + '</w:tblGrid>'
      + tableRow(['Instalment', 'Payment Due Date', 'Amount'], true)
      + rows.map(row => tableRow([row.label, longDate(row.dueDate), money(row.amount, c)], false)).join('') + '</w:tbl>';
    const separator = '<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/><w:rPr><w:sz w:val="2"/></w:rPr></w:pPr></w:p>';
    return xml.slice(0, target.start) + '</w:tbl>' + separator + table + separator
      + prefix + xml.slice(target.end);
  }

  function isBlankRowText(rowXml) {
    const runs = rowXml.match(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>/g) || [];
    return !runs.some(run => run.replace(/^<w:t\b[^>]*>/, '').replace(/<\/w:t>$/, '').trim().length > 0);
  }

  // Property XOL lists the same Case addresses under SITUATION. Remove only
  // the duplicate template row before any user-provided text is inserted.
  function stripPropertyXolLocation(xml, c) {
    if (text(c && c.classOfBusiness).toLowerCase() !== 'property'
      || coverTemplateKey(c) !== 'propertyCoverXol') return xml;
    const found = findFrameForToken(xml, scanTableFrames(xml), '{{LOCATION}}');
    if (!found) return xml;
    const { frame, rowIndex } = found;
    const row = frame.rows[rowIndex];
    const next = frame.rows[rowIndex + 1];
    const spacer = next ? xml.slice(next.start, next.end) : '';
    const end = next && isBlankRowText(spacer)
      && !/<w:(?:tbl|drawing|pict|object|fldChar|instrText|br|sectPr)\b/.test(spacer)
      ? next.end : row.end;
    return xml.slice(0, row.start) + xml.slice(end);
  }

  function stripEmptyOptionalRows(xml, values) {
    let result = xml;
    OPTIONAL_KEYS.forEach(key => {
      const value = values[key];
      if (value !== '' && value !== null && value !== undefined) return;
      const token = `{{${key}}}`;
      if (!result.includes(token)) return;
      const frames = scanTableFrames(result);
      const found = findFrameForToken(result, frames, token);
      if (found) {
        const { frame, rowIndex } = found;
        let endRowIndex = rowIndex;
        const next = frame.rows[rowIndex + 1];
        if (next && isBlankRowText(result.slice(next.start, next.end))) {
          endRowIndex = rowIndex + 1;
        }
        const blockStart = frame.rows[rowIndex].start;
        const blockEnd = frame.rows[endRowIndex].end;
        result = result.slice(0, blockStart) + result.slice(blockEnd);
        return;
      }
      const escapedToken = token.replace(/[{}]/g, '\\$&');
      const paraPattern = new RegExp('<w:p\\b[^>]*>(?:(?!<w:p\\b)[\\s\\S])*?' + escapedToken + '(?:(?!<w:p\\b)[\\s\\S])*?<\\/w:p>', 'g');
      result = result.replace(paraPattern, '');
    });
    return result;
  }

  // Fills one cloned copy of a repeating template row with per-entry
  // values, escaping for XML the same way plain token substitution does.
  function renderTemplateRow(rowXml, subs) {
    let out = rowXml;
    Object.keys(subs).forEach(token => {
      if (out.indexOf(token) !== -1) out = out.split(token).join(xmlValue(subs[token]));
    });
    return out;
  }

  // Finds the table row carrying `token`, then clones it once per entry
  // in `rows` (via `buildSubs(entry)` → {token: value} for that row),
  // consuming any blank filler rows the template pre-built after it so
  // no stray empty rows remain. When `rows` is empty and
  // opts.wholeFrameWhenEmpty is set, the whole table (all of its direct
  // rows, e.g. header + data + filler) is removed instead of just the
  // data/filler block — used for LOSS RECORD, which should disappear
  // entirely when there are no losses.
  function expandRepeatingRows(xml, token, rows, buildSubs, opts) {
    opts = opts || {};
    if (!xml.includes(token)) return xml;
    const frames = scanTableFrames(xml);
    const found = findFrameForToken(xml, frames, token);
    if (!found) return xml;
    const { frame, rowIndex } = found;
    if (!rows.length && opts.wholeFrameWhenEmpty) {
      // Remove the whole <w:tbl> (not just its rows) so no empty table
      // shell is left behind in the document.
      return xml.slice(0, frame.tblStart) + xml.slice(frame.tblEnd);
    }
    let blockEndRow = rowIndex;
    while (blockEndRow + 1 < frame.rows.length && isBlankRowText(xml.slice(frame.rows[blockEndRow + 1].start, frame.rows[blockEndRow + 1].end))) {
      blockEndRow += 1;
    }
    const blockStart = frame.rows[rowIndex].start;
    const blockEnd = frame.rows[blockEndRow].end;
    const anchorRowXml = xml.slice(frame.rows[rowIndex].start, frame.rows[rowIndex].end);
    let replacement = rows.length
      ? rows.map(entry => { const rendered = renderTemplateRow(anchorRowXml, buildSubs(entry)); return opts.renderRow ? opts.renderRow(rendered, entry) : rendered; }).join('')
      : '';
    if (rows.length && opts.beforeTrailingRow) {
      replacement += opts.beforeTrailingRow(anchorRowXml);
    }
    if (rows.length && opts.trailingRowSubs) {
      replacement += renderTemplateRow(anchorRowXml, opts.trailingRowSubs);
    }
    if (rows.length && opts.afterTrailingRow) {
      replacement += opts.afterTrailingRow(anchorRowXml);
    }
    return xml.slice(0, blockStart) + replacement + xml.slice(blockEnd);
  }

  // Renders `rowXml` with every token in `tokens` substituted with an empty
  // string, producing a blank spacer row with the same cell structure
  // (widths, shading, etc.) as the data row it was cloned from.
  function blankRow(rowXml, tokens) {
    const subs = {};
    tokens.forEach(token => { subs[token] = ''; });
    return renderTemplateRow(rowXml, subs);
  }

  // Adds a dashed top border to just the first <w:tc> cell of a row,
  // leaving any other cells (and the row's own borders) untouched. Used for
  // the Schedule of Security spacer row, where only the share % column
  // should show a dividing line right after the last reinsurer row.
  function addDashedTopBorderToFirstCell(rowXml) {
    const match = rowXml.match(/<w:tc>\s*<w:tcPr>([\s\S]*?)<\/w:tcPr>/);
    if (!match) return rowXml;
    const original = match[0];
    const border = '<w:tcBorders><w:top w:val="dashed" w:sz="4" w:space="0" w:color="auto"/></w:tcBorders>';
    const injected = /<w:shd\b/.test(original)
      ? original.replace(/<w:shd\b/, `${border}<w:shd`)
      : original.replace(/<\/w:tcPr>$/, `${border}</w:tcPr>`);
    return rowXml.replace(original, injected);
  }

  // numId values from the templates' numbering.xml that are not otherwise
  // used in the document body (verified against propertyCover.docx and
  // propertyCoverXol.docx): 19 is a decimal "1." list, 26 is a bullet
  // list. Reused here so clause/condition lines render as real Word list
  // paragraphs instead of a literal "•" character glued into the text.
  const DECIMAL_LIST_NUM_ID = 19;
  const BULLET_LIST_NUM_ID = 26;

  function findParagraphSpan(xml, token) {
    const idx = xml.indexOf(token);
    if (idx === -1) return null;
    const openRe = /<w:p\b[^>]*>/g;
    let m;
    let start = -1;
    while ((m = openRe.exec(xml))) {
      if (m.index > idx) break;
      start = m.index;
    }
    if (start === -1) return null;
    const closeIdx = xml.indexOf('</w:p>', idx);
    if (closeIdx === -1) return null;
    return { start, end: closeIdx + '</w:p>'.length };
  }

  // Splits a template paragraph "<w:p><w:pPr>...</w:pPr><w:r><w:rPr>...
  // </w:rPr><w:t>{{TOKEN}}</w:t></w:r></w:p>" into its paragraph
  // formatting and its run's character formatting, so both can be reused
  // when cloning the paragraph once per list item.
  function paragraphRunParts(paraXml) {
    const pPrMatch = paraXml.match(/^<w:p\b[^>]*>(<w:pPr>[\s\S]*?<\/w:pPr>)?/);
    const pPr = (pPrMatch && pPrMatch[1]) || '<w:pPr/>';
    const afterPPrIndex = pPrMatch ? pPrMatch[0].length : paraXml.indexOf('>') + 1;
    const rest = paraXml.slice(afterPPrIndex);
    const runMatch = rest.match(/^<w:r\b[^>]*>(<w:rPr>[\s\S]*?<\/w:rPr>)?/);
    const rPr = (runMatch && runMatch[1]) || '';
    return { pPr, rPr };
  }

  // Notes belong below the loss detail table, or below its clean-history
  // summary. Reuse the final blank paragraph inside that section's value cell.
  function appendLossRecordNotes(xml, c) {
    const notes = text(c && c.lossRecordText).replace(/\r\n?/g, '\n');
    if (!notes) return xml;
    const found = findFrameForToken(xml, scanTableFrames(xml), '{{LOSS_SUMMARY}}');
    if (!found) return xml;
    const row = found.frame.rows[found.rowIndex];
    const rowXml = xml.slice(row.start, row.end);
    const cellEnd = rowXml.lastIndexOf('</w:tc>');
    if (cellEnd === -1) return xml;
    const lastStart = paragraphStartAt(rowXml, cellEnd);
    const lastEnd = lastStart === -1 ? -1 : paragraphEndAt(rowXml, lastStart);
    const replaceBlank = lastStart !== -1 && lastEnd <= cellEnd
      && isBlankRowText(rowXml.slice(lastStart, lastEnd));
    const summarySpan = findParagraphSpan(rowXml, '{{LOSS_SUMMARY}}');
    const styleXml = replaceBlank ? rowXml.slice(lastStart, lastEnd)
      : summarySpan ? rowXml.slice(summarySpan.start, summarySpan.end) : '<w:p/>';
    const { pPr, rPr } = paragraphRunParts(styleXml);
    // Numeric character references keep literal {{...}} in notes from being
    // interpreted by the later template substitutions. Word displays the braces.
    const value = xmlValue(notes).replace(/\{/g, '&#123;').replace(/\}/g, '&#125;');
    const paragraph = `<w:p>${pPr}<w:r>${rPr}<w:t xml:space="preserve">${value}</w:t></w:r></w:p>`;
    const start = replaceBlank ? lastStart : cellEnd;
    const end = replaceBlank ? lastEnd : cellEnd;
    const updated = rowXml.slice(0, start) + paragraph + rowXml.slice(end);
    return xml.slice(0, row.start) + updated + xml.slice(row.end);
  }

  function injectNumPr(pPrXml, numId) {
    const numPr = `<w:numPr><w:ilvl w:val="0"/><w:numId w:val="${numId}"/></w:numPr>`;
    if (/^<w:pPr\/>$/.test(pPrXml)) return `<w:pPr>${numPr}</w:pPr>`;
    return pPrXml.replace(/^<w:pPr>/, `<w:pPr>${numPr}`);
  }

  // Replaces the single template paragraph carrying `token` with one
  // plain paragraph for `opts.intro` (if given, no list numbering) followed
  // by one real numbered/bulleted paragraph per entry in `lines`, all
  // reusing the template paragraph's own formatting and referencing an
  // existing list definition (`opts.numId`) from the template's
  // numbering.xml — so Word renders genuine list numbers/bullets instead
  // of a literal character typed into the text.
  function expandListParagraph(xml, token, lines, opts) {
    opts = opts || {};
    if (!xml.includes(token)) return xml;
    const span = findParagraphSpan(xml, token);
    if (!span) return xml;
    const paraXml = xml.slice(span.start, span.end);
    const { pPr, rPr } = paragraphRunParts(paraXml);
    const listPPr = opts.numId ? injectNumPr(pPr, opts.numId) : pPr;
    const paragraphs = [];
    if (opts.intro) {
      paragraphs.push(`<w:p>${pPr}<w:r>${rPr}<w:t xml:space="preserve">${xmlValue(opts.intro)}</w:t></w:r></w:p>`);
    }
    lines.forEach(line => {
      paragraphs.push(`<w:p>${listPPr}<w:r>${rPr}<w:t xml:space="preserve">${xmlValue(line)}</w:t></w:r></w:p>`);
    });
    if (opts.tail) {
      const plain = injectNumPr(pPr.replace(/<w:numPr\b[^>]*>[\s\S]*?<\/w:numPr>/g, ''), 0);
      paragraphs.push('<w:p>' + plain + '<w:r>' + rPr + '<w:t xml:space="preserve">' + xmlValue(opts.tail) + '</w:t></w:r></w:p>');
    }
    const replacement = paragraphs.length ? paragraphs.join('') : `<w:p>${pPr}</w:p>`;
    return xml.slice(0, span.start) + replacement + xml.slice(span.end);
  }

  // Expands the Cover Note's three multi-entry sections — Breakdown of
  // Sum Insured, Loss Record and Schedule of Security — into one table
  // row per actual entry instead of cramming every entry's text into the
  // template's single first data row.
  function renderSumInsuredLocation(rowXml) {
    const cells = rowXml.match(/<w:tc\b[^>]*>[\s\S]*?<\/w:tc>/g) || [];
    if (cells.length !== 2) return rowXml;
    const widths = cells.map(cell => Number((cell.match(/<w:tcW\b[^>]*w:w="(\d+)"/) || [])[1]));
    if (!widths.every(Number.isFinite)) return rowXml;
    let merged = cells[0].replace(/<w:tcW\b[^>]*\/>/, `<w:tcW w:w="${widths[0] + widths[1]}" w:type="dxa"/><w:gridSpan w:val="2"/>`);
    merged = merged.replace(/<w:pPr>([\s\S]*?)<\/w:pPr>/g, (tag, properties) => {
      let content = properties.replace(/<w:jc\b[^>]*\/>/g, '');
      content = content.includes('<w:rPr>')
        ? content.replace('<w:rPr>', '<w:jc w:val="center"/><w:rPr>')
        : content + '<w:jc w:val="center"/>';
      return `<w:pPr>${content}</w:pPr>`;
    }).replace(/<w:rPr>/g, '<w:rPr><w:b/>');
    return rowXml.replace(cells[0] + cells[1], merged);
  }

  // Currency spacing is a Cover display rule; saved Case prose stays intact.
  function compactCoverCurrencyAmounts(xml, c) {
    const codes = ['USD', 'TWD', 'NTD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR', 'CNY', 'AUD', 'CAD', 'CHF', 'SGD', 'NZD', text(c && c.currency).toUpperCase()]
      .filter(code => /^[A-Z]{3}$/.test(code));
    const pattern = new RegExp(`\\b(${[...new Set(codes)].join('|')})[ \t\u00a0\u202f]+(?=[+-]?\\d)`, 'g');
    return xml.replace(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>/g, node => node.replace(pattern, '$1'));
  }

  function expandDocumentRepeatingRows(xml, c) {
    const sums = sumInsuredRows(c);
    xml = expandRepeatingRows(xml, '{{SUM_INSURED_LABELS}}', sums, row => ({
      '{{SUM_INSURED_LABELS}}': row.label,
      '{{SUM_INSURED_AMOUNTS}}': row.amount,
    }), { renderRow: (rowXml, row) => row.heading ? renderSumInsuredLocation(rowXml) : rowXml });

    const lossRows = lossDocumentRows(c);
    xml = expandRepeatingRows(xml, '{{LOSS_DATES}}', lossRows, row => ({
      '{{LOSS_DATES}}': longDate(row.date) || '—',
      '{{LOSS_CAUSES}}': text(row.cause) || '—',
      '{{LOSS_PAID}}': formatMoney(row.lossPaid, c),
    }), { wholeFrameWhenEmpty: true });

    const reinsurers = securityDocumentRows(c);
    const totalSharePct = reinsurers.reduce((total, row) => total + number(row.sharePct), 0);
    const shareDecimals = shareDecimalPlaces(reinsurers);
    // The template's row has the {{SECURITY_NAMES}} token in its narrow
    // (left) cell and {{SECURITY_SHARES}} in its wide (right) cell. The
    // desired layout is share % on the left, reinsurer name on the right,
    // so the values are swapped relative to the token names below.
    xml = expandRepeatingRows(xml, '{{SECURITY_NAMES}}', reinsurers, row => ({
      '{{SECURITY_NAMES}}': percentTrim(row.sharePct, shareDecimals),
      '{{SECURITY_SHARES}}': stripFacility(row.name) || '(Reinsurer)',
    }), {
      // A blank spacer row between the last reinsurer and the total row,
      // with a dashed bottom border under the share % column only (the
      // name column stays borderless) so the total reads as a subtotal.
      beforeTrailingRow: anchorRowXml => addDashedTopBorderToFirstCell(
        blankRow(anchorRowXml, ['{{SECURITY_NAMES}}', '{{SECURITY_SHARES}}'])
      ),
      // A final row summing the reinsurers' shares, e.g. "100% of 100%",
      // the same way the Breakdown of Sum Insured table ends with a Total.
      trailingRowSubs: {
        '{{SECURITY_NAMES}}': percentTrim(totalSharePct, shareDecimals),
        '{{SECURITY_SHARES}}': 'of 100%',
      },
      // Another plain blank spacer row after the total row so the
      // following text isn't crammed right up against it.
      afterTrailingRow: anchorRowXml => blankRow(anchorRowXml, ['{{SECURITY_NAMES}}', '{{SECURITY_SHARES}}']),
    });

    const clauses = clauseDetails(c);
    xml = expandListParagraph(xml, '{{REINSURANCE_CONDITIONS}}', clauses.map(item => clauseLine(item)), {
      intro: REINSURANCE_INTRO,
      numId: BULLET_LIST_NUM_ID,
    });

    if (qsStructure(c)) {
      xml = expandListParagraph(xml, '{{ORIGINAL_CONDITIONS}}', originalClauseLines(c && c.originalConditions), {
        numId: DECIMAL_LIST_NUM_ID,
        tail: ORIGINAL_CONDITIONS_TAIL,
      });
    } else {
    const originalConditionsText = appendRequiredTail(c && c.originalConditions, ORIGINAL_CONDITIONS_TAIL);
    xml = expandListParagraph(xml, '{{ORIGINAL_CONDITIONS}}', originalConditionsText.split('\n').filter(Boolean), {
      numId: text(c && c.originalConditions) ? DECIMAL_LIST_NUM_ID : null,
    });
    }

    if (qsStructure(c)) {
      xml = expandListParagraph(xml, '{{ORIGINAL_EXCLUSIONS}}', originalClauseLines(c && c.originalExclusions), {
        numId: DECIMAL_LIST_NUM_ID,
        tail: ORIGINAL_CONDITIONS_TAIL,
      });
    } else {
    const originalExclusionsText = appendRequiredTail(c && c.originalExclusions, ORIGINAL_CONDITIONS_TAIL);
    xml = expandListParagraph(xml, '{{ORIGINAL_EXCLUSIONS}}', originalExclusionsText.split('\n').filter(Boolean), {
      numId: text(c && c.originalExclusions) ? DECIMAL_LIST_NUM_ID : null,
    });
    }

    return xml;
  }

  // The templates' footer places the "Page X of Y" field (wrapped in a
  // content control / <w:sdt>) before the company address paragraphs, so it
  // renders above the address. Reorder it so the address renders on top and
  // the page number sits below it, matching the desired footer layout.
  // No-op (returns xml unchanged) when there's no page-number field, or when
  // it's already after the address (idempotent/safe to call more than once).
  function reorderFooterPageNumber(xml) {
    const sdtStart = xml.indexOf('<w:sdt>');
    if (sdtStart === -1) return xml;
    const sdtEndTag = '</w:sdt>';
    const sdtEndIdx = xml.indexOf(sdtEndTag, sdtStart);
    if (sdtEndIdx === -1) return xml;
    const sdtEnd = sdtEndIdx + sdtEndTag.length;
    const closeIdx = xml.indexOf('</w:ftr>', sdtEnd);
    if (closeIdx === -1) return xml;
    const before = xml.slice(0, sdtStart);
    const sdtBlock = xml.slice(sdtStart, sdtEnd);
    const addressBlock = xml.slice(sdtEnd, closeIdx);
    const after = xml.slice(closeIdx);
    if (!addressBlock.trim()) return xml;
    return `${before}${addressBlock}${sdtBlock}${after}`;
  }

  // Keep the company, address and contacts on separate centered lines.
  function separateFooterContacts(xml) {
    return xml.replace(/<w:p\b[^>]*>[\s\S]*?<\/w:p>/g, paragraph => {
      if (!paragraph.includes('Taiwan.')) return paragraph;
      const contact = [...paragraph.matchAll(/<w:r\b[^>]*>[\s\S]*?<\/w:r>/g)]
        .find(run => run[0].replace(/<[^>]+>/g, '').trim() === 'T: +886-2-8772-2277 F: +886-2-8772-2748');
      if (!contact) return paragraph;
      const properties = (paragraph.match(/<w:pPr>[\s\S]*?<\/w:pPr>/) || [''])[0];
      const contactRun = contact[0].replace(/<w:t\b([^>]*)>([\s\S]*?)<\/w:t>/g,
        (tag, attrs, value) => `<w:t${attrs}>${value.split('-').join(`</w:t><w:noBreakHyphen/><w:t${attrs}>`)}</w:t>`);
      return paragraph.slice(0, contact.index) + paragraph.slice(contact.index + contact[0].length)
        + `<w:p>${properties}${contactRun}</w:p>`;
    });
  }

  // Use live Word fields on every page; preserve an existing page-number footer.
  function ensureFooterPageNumber(xml) {
    const hasPageField = /<w:instrText\b[^>]*>\s*PAGE\b|<w:fldSimple\b[^>]*\bw:instr=["']\s*PAGE\b/.test(xml);
    if (hasPageField) return xml;
    const paragraph = '<w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:t xml:space="preserve">Page </w:t></w:r><w:fldSimple w:instr="PAGE \\* Arabic"><w:r><w:t>1</w:t></w:r></w:fldSimple><w:r><w:t xml:space="preserve"> of </w:t></w:r><w:fldSimple w:instr="NUMPAGES \\* Arabic"><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p>';
    return xml.replace('</w:ftr>', paragraph + '</w:ftr>');
  }

  // Locates the <w:p ...> that contains character offset `idx` by scanning
  // backward for the nearest paragraph-opening tag (works for both
  // "<w:p>" and "<w:p w14:paraId=...>" forms; OOXML paragraphs never
  // nest, so the nearest preceding opening tag is always the right one).
  function paragraphStartAt(xml, idx) {
    const bare = xml.lastIndexOf('<w:p>', idx);
    const attrs = xml.lastIndexOf('<w:p ', idx);
    return Math.max(bare, attrs);
  }
  // Locates the end of the <w:p> that contains character offset `idx` by
  // scanning forward for the next paragraph-closing tag.
  function paragraphEndAt(xml, idx) {
    const closeIdx = xml.indexOf('</w:p>', idx);
    return closeIdx === -1 ? -1 : closeIdx + '</w:p>'.length;
  }

  // Overwrites every <w:sz>/<w:szCs> value found within xml.slice(start,end)
  // with `halfPoints` (OOXML font sizes are in half-points, so 24 = 12pt,
  // 18 = 9pt). Used to restore a specific block's intended font size after
  // normalizeRunTypography's blanket 10pt default has been applied to
  // every run in the document.
  function setSizeInRange(xml, start, end, halfPoints) {
    if (start === -1 || end === -1 || end <= start) return xml;
    const before = xml.slice(0, start);
    const segment = xml.slice(start, end)
      .replace(/<w:sz w:val="\d+"\/>/g, `<w:sz w:val="${halfPoints}"/>`)
      .replace(/<w:szCs w:val="\d+"\/>/g, `<w:szCs w:val="${halfPoints}"/>`);
    const after = xml.slice(end);
    return before + segment + after;
  }

  // Finds a block of text by its first and last distinctive substrings
  // (both literal, not regex) and resizes every run's font size within
  // that whole paragraph range, inclusive of the paragraphs containing
  // each anchor. Safe no-op if either anchor isn't found.
  function resizeTextBlock(xml, startNeedle, endNeedle, halfPoints, searchFrom) {
    const startIdx = xml.indexOf(startNeedle, searchFrom || 0);
    if (startIdx === -1) return xml;
    const endIdx = xml.indexOf(endNeedle, startIdx);
    if (endIdx === -1) return xml;
    const pStart = paragraphStartAt(xml, startIdx);
    const pEnd = paragraphEndAt(xml, endIdx);
    return setSizeInRange(xml, pStart, pEnd, halfPoints);
  }

  // Applied last (after normalizeRunTypography has forced every run in the
  // document to the default 10pt body size) to restore the font sizes
  // specifically wanted for a handful of static boilerplate blocks: the
  // main Cover Note / Debit Note titles at 12pt, and the long legal
  // notices on the Schedule of Security and closing clause pages at 9pt.
  // Every lookup is anchored on literal, non-token text so it works
  // identically whether it runs before or after `{{TOKEN}}` substitution,
  // and is a no-op wherever a given block doesn't exist in the template
  // (e.g. the Debit Note templates have no Schedule of Security section).
  // Only the bank rows use grid boundary 8 in the Debit templates.
  // Shift it left by 6 pt; all other row boundaries and table width stay fixed.
  function formatDebitBankAccount(xml) {
    const edits = [];
    scanTableFrames(xml).forEach(frame => {
      const headerIndex = frame.rows.findIndex(row => {
        const value = xml.slice(row.start, row.end).replace(/<[^>]+>/g, '');
        return value.includes('Beneficiary Name') && value.includes('Account No.') && value.includes('Swift Code');
      });
      if (headerIndex < 0 || !frame.rows[headerIndex + 1]) return;
      const account = frame.rows[headerIndex + 1];
      if (!xml.slice(account.start, account.end).includes('TPBKTWTP')) return;
      const prefix = xml.slice(frame.tblStart, frame.rows[0].start);
      const grid = prefix.match(/<w:tblGrid\b[^>]*>[\s\S]*?<\/w:tblGrid>/);
      if (!grid) return;
      const columns = [...grid[0].matchAll(/<w:gridCol\b[^>]*w:w="(\d+)"[^>]*\/>/g)];
      if (columns.length !== 12) return;
      const widths = columns.map(column => Number(column[1]));
      const shift = 120;
      const preferredShift = Math.round(shift * 5000 / widths.reduce((sum, width) => sum + width, 0));
      let columnIndex = 0;
      const resizedGrid = grid[0].replace(/<w:gridCol\b[^>]*w:w="(\d+)"[^>]*\/>/g, (column, width) => {
        const adjustment = columnIndex === 7 ? -shift : columnIndex === 8 ? shift : 0;
        columnIndex += 1;
        return column.replace(`w:w="${width}"`, `w:w="${Number(width) + adjustment}"`);
      });
      const gridStart = frame.tblStart + grid.index;
      edits.push({ start: gridStart, end: gridStart + grid[0].length, xml: resizedGrid });
      const notice = frame.rows.slice(0, headerIndex).find(row =>
        xml.slice(row.start, row.end).replace(/<[^>]+>/g, '').includes('Please arrange payment to our'));
      if (notice) {
        const noticeXml = xml.slice(notice.start, notice.end);
        edits.push({ start: notice.start, end: notice.end, xml: setSizeInRange(noticeXml, 0, noticeXml.length, 18) });
      }
      [frame.rows[headerIndex], account].forEach((row, rowIndex) => {
        let cellIndex = 0;
        const updated = xml.slice(row.start, row.end).replace(/<w:tc\b[^>]*>[\s\S]*?<\/w:tc>/g, cell => {
          const index = cellIndex++;
          if (index === 2 || index === 3) {
            cell = cell.replace(/<w:tcW\b[^>]*w:w="(\d+)"[^>]*\/>/, (tag, width) =>
              tag.replace(`w:w="${width}"`, `w:w="${Number(width) + (index === 3 ? preferredShift : -preferredShift)}"`));
          }
          cell = setSizeInRange(cell, 0, cell.length, 18);
          if (rowIndex === 1 && index === 3) {
            if (!/<w:noWrap\b/.test(cell)) cell = cell.replace('<w:vAlign', '<w:noWrap/><w:vAlign');
          }
          return cell;
        });
        edits.push({ start: row.start, end: row.end, xml: updated });
      });
    });
    edits.sort((a, b) => b.start - a.start).forEach(edit => {
      xml = xml.slice(0, edit.start) + edit.xml + xml.slice(edit.end);
    });
    return xml;
  }

  function applyFontSizeOverrides(xml) {
    // Main Cover Note title, e.g. "COVER NOTE NO. TWPF2609014" — but not
    // the smaller "(continued)" repeats of the title used on later
    // pages/sections, which stay at their existing (10pt) size. This scans
    // for each "COVER NOTE NO. " occurrence and picks the first one whose
    // <w:t> content runs straight to "</w:t>" without " (continued)" in
    // between — that's the main title, whether this runs before or after
    // the {{TW_REF}} token itself has been substituted.
    let titleIdx = -1;
    let titleSearchFrom = 0;
    for (;;) {
      const idx = xml.indexOf('COVER NOTE NO. ', titleSearchFrom);
      if (idx === -1) break;
      const closeIdx = xml.indexOf('</w:t>', idx);
      if (closeIdx !== -1 && !xml.slice(idx, closeIdx).includes('(continued)')) {
        titleIdx = idx;
        break;
      }
      titleSearchFrom = idx + 1;
    }
    if (titleIdx !== -1) {
      xml = setSizeInRange(xml, paragraphStartAt(xml, titleIdx), paragraphEndAt(xml, titleIdx), 24);
    }

    // Debit Note title ("DEBIT" + " NOTE" as two runs in one paragraph).
    const debitTitleNeedle = '<w:t>DEBIT</w:t>';
    const debitTitleIdx = xml.indexOf(debitTitleNeedle);
    if (debitTitleIdx !== -1) {
      xml = setSizeInRange(xml, paragraphStartAt(xml, debitTitleIdx), paragraphEndAt(xml, debitTitleIdx), 24);
      xml = formatDebitBankAccount(xml);
    }

    // Schedule of Security page: the reinsurance-warranties notice
    // followed by the "please examine the details" notice.
    xml = resizeTextBlock(xml, 'Your attention is drawn', 'from TW Insurance Brokers.', 18);

    // (Re)insurers Liability Clause, ending at the LMA reference line.
    xml = resizeTextBlock(xml, 'liability several not joint', '21 June 2007', 18);

    // Intermediary Clause, ending at the broker's address line.
    xml = resizeTextBlock(xml, 'hereby recognized as the Intermediary', '10492 Taiwan', 18);

    return xml;
  }

  // The Case supplies the standard CGL Information rows through its shared
  // scope/formatting module. Only the Property Information rows are replaced;
  // Loss Record and Special Agreement keep their existing Word formatting.
  function applyCglInformation(xml, c) {
    if (!Array.isArray(c && c.cglInformationRows)) return xml;
    // Rename the fixed heading before inserting any user-provided address text.
    xml = xml.replace('<w:t>SITUATION</w:t>', '<w:t>PRINCIPAL ADDRESS</w:t>');
    xml = xml.replace('<w:t>LIMIT OF LIABILITY</w:t>', '<w:t>LIMIT OF INDEMNITY</w:t>');
    xml = xml.replace('<w:t>POLICY LIMIT</w:t>', '<w:t>AGGREGATE LIMIT</w:t>');
    xml = xml.replace('<w:t>ORIGINAL POLICY PERIOD</w:t>', '<w:t>PERIOD</w:t>');
    // The QS template splits this fixed heading across two Word runs.
    xml = xml.replace('<w:t xml:space="preserve">ORIGINAL POLICY </w:t>', '<w:t xml:space="preserve"></w:t>');
    const edits = [];
    const frames = scanTableFrames(xml);
    ['{{LOCATION}}', '{{TOTAL_SUM_INSURED}}', '{{OCCUPATION}}', '{{CONSTRUCTION}}', '{{SUM_INSURED_LABELS}}'].forEach(token => {
      // Use the outer row in the INFORMATION table for the nested sum table.
      const matches = frames.flatMap(frame => frame.rows.map((row, index) => ({ frame, row, index })))
        .filter(item => xml.slice(item.row.start, item.row.end).includes(token))
        .sort((a, b) => (b.row.end - b.row.start) - (a.row.end - a.row.start));
      if (!matches.length) return;
      const { frame, row, index } = matches[0];
      const next = frame.rows[index + 1];
      const spacer = next && isBlankRowText(xml.slice(next.start, next.end)) ? xml.slice(next.start, next.end) : '';
      let replacement = '';
      if (token === '{{OCCUPATION}}') {
        const templateRow = xml.slice(row.start, row.end);
        replacement = c.cglInformationRows.filter(item => item.value && item.value !== '—').map(item => {
          const value = xmlValue(item.value).replace(/\{/g, '&#123;').replace(/\}/g, '&#125;');
          return templateRow.split(token).join(value).replace(/>OCCUPATION</, '>' + xmlEscape(item.label.toUpperCase()) + '<') + spacer;
        }).join('');
      }
      edits.push({ start: row.start, end: spacer ? next.end : row.end, replacement });
    });
    edits.sort((a, b) => b.start - a.start).forEach(edit => { xml = xml.slice(0, edit.start) + edit.replacement + xml.slice(edit.end); });
    return xml;
  }

  // Reuse the adjacent template row typography and spacing for CGL Risk Details.
  // Render escaped text before normal placeholders, protecting literal braces.
  function applyCglRiskDetails(xml, c) {
    if (!Array.isArray(c && c.cglInformationRows)) return xml;
    [
      { token: '{{INTEREST}}', heading: 'INTEREST', label: 'COVERAGES', value: c.cglCoveragesText },
      { token: '{{DEDUCTIBLES}}', heading: 'DEDUCTIBLES', label: 'SELF-INSURED RETENTION', value: c.selfInsuredRetention },
    ].forEach(item => {
      if (!text(item.value)) return;
      const found = findFrameForToken(xml, scanTableFrames(xml), item.token);
      if (!found) return;
      const row = found.frame.rows[found.rowIndex];
      const next = found.frame.rows[found.rowIndex + 1];
      const spacer = next && isBlankRowText(xml.slice(next.start, next.end)) ? xml.slice(next.start, next.end) : '';
      const value = xmlValue(item.value).replace(/\{/g, '&#123;').replace(/\}/g, '&#125;');
      const added = xml.slice(row.start, row.end).replace('>' + item.heading + '<', '>' + item.label + '<')
        .split(item.token).join(value) + spacer;
      const at = spacer ? next.end : row.end;
      xml = xml.slice(0, at) + added + xml.slice(at);
    });
    return xml;
  }

  function applyNewQsRows(xml, c) {
    if (!newQs(c)) return xml;
    const additions = [
      {token:'{{DEDUCTIBLES}}', heading:'DEDUCTIBLES', label:'SELF-INSURED RETENTION', value:propertyExtras(c) ? c.selfInsuredRetention : ''},
      {token:'{{REINSTATEMENT_PROVISIONS}}', heading:'REINSTATEMENT PROVISIONS', label:'CO-REINSURANCE WARRANTY', value:(newCgl(c) || propertyExtras(c)) ? c.coReinsuranceWarranty : ''}
    ];
    additions.forEach(item => {
      if (!text(item.value)) return;
      const found=findFrameForToken(xml,scanTableFrames(xml),item.token);
      if (!found) return;
      const row=found.frame.rows[found.rowIndex];
      const added=xml.slice(row.start,row.end).replace('>'+item.heading+'<','>'+item.label+'<').split(item.token).join(xmlValue(item.value).replace(/\{/g,'&#123;').replace(/\}/g,'&#125;'));
      xml=xml.slice(0,row.end)+added+xml.slice(row.end);
    });
    if (newCgl(c) && !(c.situations || []).some(r=>text(r.address))) {
      const found=findFrameForToken(xml,scanTableFrames(xml),'{{SITUATION}}');
      if(found){const row=found.frame.rows[found.rowIndex];xml=xml.slice(0,row.start)+xml.slice(row.end);}
    }
    return xml;
  }
  async function fillTemplate(base64, c, values, outputType, includeLossNotes = false, keepBankDetails = false) {
    const zip = await JSZip.loadAsync(base64, { base64: true });
    const names = Object.keys(zip.files).filter(name => /\.xml$/i.test(name));
    await Promise.all(names.map(async name => {
      const file = zip.file(name);
      if (!file) return;
      let xml = await file.async('string');
      let changed = false;
      if (includeLossNotes && /Loss Paid/.test(xml)) { xml=xml.replace(/Loss Paid/g,'Loss Amount');changed=true; }
      if (/^word\/document\.xml$/i.test(name)) {
        if (qsProperty(c)) {
          if (includeLossNotes) xml = xml.replace('amendments or alternations hereto', 'amendments or alterations hereto');
          if (keepBankDetails) xml = xml.replace(/(<w:t(?:\s[^>]*)?>)PREMIUM(<\/w:t>)/g, (_, open, close) => open + '100% PREMIUM' + close);
        }
        // Correct the Cover template heading before inserting any Case text.
        if (includeLossNotes) {
          const corrected = stripPropertyXolLocation(startCoverInformationPage(xml.replace('<w:t>BREAKFOWN OF SUM INSURED</w:t>', '<w:t>BREAKDOWN OF SUM INSURED</w:t>')), c);
          if (corrected !== xml) {
            xml = corrected;
            changed = true;
          }
        }
        const information = applyCglInformation(xml, c);
        if (information !== xml) { xml = information; changed = true; }
        const riskDetails = applyCglRiskDetails(xml, c);
        if (riskDetails !== xml) { xml = riskDetails; changed = true; }
        xml = applyNewQsRows(xml,c);
        const stripped = stripEmptyOptionalRows(xml, values);
        if (stripped !== xml) {
          xml = stripped;
          changed = true;
        }
        const expanded = expandDocumentRepeatingRows(xml, c);
        if (expanded !== xml) {
          xml = expanded;
          changed = true;
        }
      }
      if (keepBankDetails && /^word\/document\.xml$/i.test(name)) {
        if (currencyLabel(c) === 'TWD') {
          const labelled = xml.replace(/(<w:t\b[^>]*>)NTD(<\/w:t>)/g, '$1TWD$2');
          if (labelled !== xml) { xml = labelled; changed = true; }
        }
        const schedule = renderDebitInstalments(xml, c);
        if (schedule !== xml) { xml = schedule; changed = true; }
        const keptTogether = keepDebitBankDetailsTogether(xml);
        if (keptTogether !== xml) {
          xml = keptTogether;
          changed = true;
        }
      }
      if (includeLossNotes && /^word\/document\.xml$/i.test(name)) {
        const annotated = appendLossRecordNotes(xml, c);
        if (annotated !== xml) {
          xml = annotated;
          changed = true;
        }
      }
      if (/^word\/header\d+\.xml$/i.test(name)) {
        const reserved = reserveHeaderLogoSpace(xml);
        if (reserved !== xml) {
          xml = reserved;
          changed = true;
        }
      }
      if (/^word\/footer\d+\.xml$/i.test(name)) {
        const reordered = separateFooterContacts(ensureFooterPageNumber(reorderFooterPageNumber(xml)));
        if (reordered !== xml) {
          xml = reordered;
          changed = true;
        }
      }
      if (/^word\/settings\.xml$/i.test(name)) {
        // Refresh PAGE / NUMPAGES when Word opens the generated document.
        const updated = /<w:updateFields\b/.test(xml)
          ? xml.replace(/<w:updateFields\b[^>]*\/>/, '<w:updateFields w:val="true"/>')
          : xml.replace('</w:settings>', '<w:updateFields w:val="true"/></w:settings>');
        if (updated !== xml) {
          xml = updated;
          changed = true;
        }
      }
      Object.keys(values).forEach(key => {
        const token = `{{${key}}}`;
        if (!xml.includes(token)) return;
        xml = xml.split(token).join(xmlValue(values[key]));
        changed = true;
      });
      if (/^word\/(?:document|header\d+|footer\d+|footnotes|endnotes)\.xml$/i.test(name)) {
        const normalized = normalizeRunTypography(xml);
        if (normalized !== xml) {
          xml = normalized;
          changed = true;
        }
      }
      if (/^word\/document\.xml$/i.test(name)) {
        const resized = applyFontSizeOverrides(xml);
        if (resized !== xml) {
          xml = resized;
          changed = true;
        }
      }
      if (includeLossNotes && /^word\/document\.xml$/i.test(name)) {
        const paginated = normalizeCoverPageBreaks(compactCoverCurrencyAmounts(xml, c));
        if (paginated !== xml) {
          xml = paginated;
          changed = true;
        }
      }
      if (/^word\/document\.xml$/i.test(name)) {
        const signatureKept = keepSignatureBlockTogether(normalizeSignatureSpacing(xml));
        if (signatureKept !== xml) {
          xml = signatureKept;
          changed = true;
        }
      }
      if (changed) zip.file(name, xml);
    }));
    return zip.generateAsync({
      type: outputType || 'blob',
      mimeType: MIME,
      compression: 'DEFLATE',
      compressionOptions: { level: 6 },
    });
  }

  function coverTemplateKey(c) {
    const structure = text(c && c.reinsuranceStructure).toUpperCase();
    return structure.includes('XOL') || structure.includes('EXCESS')
      ? 'propertyCoverXol'
      : 'propertyCover';
  }

  function debitTemplateKey(c) {
    return currencyLabel(c) === 'USD' ? 'debitUsd' : 'debitNtd';
  }

  async function generateCover(c, templates, outputType) {
    const key = coverTemplateKey(c);
    if (!templates || !templates[key]) throw new Error(`Missing Word template: ${key}`);
    return fillTemplate(templates[key], c, commonValues(c), outputType, true);
  }

  async function generateDebit(c, templates, outputType) {
    const key = debitTemplateKey(c);
    if (!templates || !templates[key]) throw new Error(`Missing Word template: ${key}`);
    if (endorsementNote(c)) return generateEndorsementNote(templates[key], c, outputType, false);
    return fillTemplate(templates[key], c, commonValues(c), outputType, false, true);
  }

  // 2026-10-29：批單的 Debit Note（加費）與 Credit Note（退費）。
  // 金額是這張批單 Cedant 那邊的 Premium、Ceding Commission、Tax、Net；
  // 付款日 = 批單生效日 + 沿用原單的 Cedant Collection Days（Debit Note 照原本再提前 15 天）。
  // 版面沿用 Debit Note（標題下不寫 Endorsement No.，批單號寫在 DETAILS）；Credit Note 依業主的 Credit Note Template (NTD) 文字，不列銀行帳戶，金額顯示正數。
  function endorsementNote(c) {
    return Boolean(text(c && c.parentTwRef));
  }

  function endorsementNumber(c) {
    const seq = Number(c && c.endorsementSeq);
    if (Number.isInteger(seq) && seq > 0) return String(seq);
    const match = text(c && c.twRef).match(/-E0*(\d+)$/);
    return match ? match[1] : '';
  }

  async function generateCredit(c, templates, outputType) {
    if (!endorsementNote(c)) throw new Error('Credit Note is available only for endorsements.');
    if (currencyLabel(c) !== 'TWD') throw new Error('Credit Note generation is available only for TWD.');
    if (!templates || !templates.debitNtd) throw new Error('Missing Word template: debitNtd');
    return generateEndorsementNote(templates.debitNtd, creditCase(c), outputType, true);
  }

  // 退費的金額是負的；Credit Note 顯示正數。取位正負對稱，所以整件翻號後算出的就是原本金額的絕對值。
  function creditCase(c) {
    const flip = value => (value === '' || value === null || value === undefined || !Number.isFinite(Number(value))) ? value : 0 - Number(value);
    const fin = c.propertyFinancials;
    return {
      ...c,
      creditNote: true,
      originalPremium: flip(c.originalPremium),
      reinsurers: (Array.isArray(c.reinsurers) ? c.reinsurers : []).map(row => ({ ...row, premium: flip(row && row.premium) })),
      performanceInstallments: Array.isArray(c.performanceInstallments) ? c.performanceInstallments.map(row => ({ ...row, premium: flip(row && row.premium) })) : c.performanceInstallments,
      propertyFinancials: fin ? { ...fin, originalPremium: flip(fin.originalPremium), cededPremium: flip(fin.cededPremium), commission: flip(fin.commission),
        tax: flip(fin.tax), netDue: flip(fin.netDue), t1s: (fin.t1s || []).map(flip) } : fin,
      propertyInstallmentNet: Array.isArray(c.propertyInstallmentNet) ? c.propertyInstallmentNet.map(flip) : c.propertyInstallmentNet,
    };
  }

  function paragraphText(paragraph) {
    return (paragraph.match(/<w:t\b[^>]*>[^<]*<\/w:t>/g) || []).map(run => run.replace(/<[^>]+>/g, '')).join('');
  }

  // Replace the whole text of every paragraph that reads `from`; keep the first run's formatting.
  function replaceParagraphText(xml, from, to, extraLine) {
    return xml.replace(/<w:p\b[^>]*>[\s\S]*?<\/w:p>/g, paragraph => {
      if (paragraphText(paragraph).trim() !== from) return paragraph;
      let first = true;
      return paragraph.replace(/<w:t\b[^>]*>[^<]*<\/w:t>/g, () => {
        if (!first) return '<w:t></w:t>';
        first = false;
        return `<w:t xml:space="preserve">${xmlValue(to)}</w:t>` + (extraLine ? `<w:br/><w:t xml:space="preserve">${xmlValue(extraLine)}</w:t>` : '');
      });
    });
  }

  function removeBankDetailRows(xml) {
    const edits = [];
    scanTableFrames(xml).forEach(frame => {
      const rowText = row => xml.slice(row.start, row.end).replace(/<[^>]+>/g, '');
      const first = frame.rows.findIndex(row => rowText(row).includes('Please arrange payment to our'));
      const last = frame.rows.findIndex(row => rowText(row).includes('TPBKTWTP'));
      if (first >= 0 && last >= first) edits.push({ start: frame.rows[first].start, end: frame.rows[last].end });
    });
    edits.sort((a, b) => b.start - a.start).forEach(edit => { xml = xml.slice(0, edit.start) + xml.slice(edit.end); });
    return xml;
  }

  async function generateEndorsementNote(base64, c, outputType, credit) {
    const zip = await JSZip.loadAsync(base64, { base64: true });
    let xml = await zip.file('word/document.xml').async('string');
    const number = endorsementNumber(c);
    if (credit) xml = replaceParagraphText(xml, 'DEBIT NOTE', 'CREDIT NOTE');
    xml = replaceParagraphText(xml, 'Original Premium Payment', `${credit ? 'Return' : 'Additional'} Premium – Endorsement No. ${number || '—'}`);
    if (credit) {
      xml = replaceParagraphText(xml, 'NET AMOUNT DUE FROM YOU', 'NET AMOUNT DUE TO YOU');
      xml = replaceParagraphText(xml, 'Please ensure that we are in receipt of cleared funds at least 15 days before the due date(s) in order that we can arrange our settlement in time to comply',
        'We shall arrange the payment of premium on the following date(s):');
      xml = removeBankDetailRows(xml);
    }
    zip.file('word/document.xml', xml);
    const prepared = await zip.generateAsync({ type: 'base64' });
    const filled = await JSZip.loadAsync(await fillTemplate(prepared, c, commonValues(c), 'uint8array', false, true));
    // 2026-10-29 業主：批單 Debit／Credit Note 的頁尾（公司資訊與頁碼）用 8 pt；其他文件維持原字級。
    for (const name of Object.keys(filled.files).filter(n => /^word\/footer\d+\.xml$/.test(n))) {
      const footer = await filled.file(name).async('string');
      filled.file(name, footer.replace(/<w:(sz|szCs) w:val="\d+"\/>/g, '<w:$1 w:val="16"/>'));
    }
    return filled.generateAsync({ type: outputType || 'blob', mimeType: MIME, compression: 'DEFLATE', compressionOptions: { level: 6 } });
  }

  function endorsementReference(c) {
    return text(c && c.twRef) || `${text(c && c.parentTwRef) || 'DRAFT'}-E${String(c && c.endorsementSeq || '').padStart(2, '0')}`;
  }

  // Reuse the established Word letterhead, footer and signature assets.
  // Wording stays in flowing paragraphs so long endorsements can span pages.
  async function generateEndorsement(c, templates, outputType) {
    if (!templates || !templates.debitNtd) throw new Error('Missing Word template: debitNtd');
    const zip = await JSZip.loadAsync(templates.debitNtd, { base64: true });
    let xml = await zip.file('word/document.xml').async('string');
    const section = xml.match(/<w:sectPr\b[\s\S]*?<\/w:sectPr>/);
    const signature = (xml.match(/<w:p\b[^>]*>[\s\S]*?<\/w:p>/g) || []).find(p => p.includes('<w:drawing>'));
    if (!section || !signature) throw new Error('Word letterhead or signature is unavailable.');
    const paragraph = (value, options = {}) => `<w:p><w:pPr>${options.keepNext ? '<w:keepNext/>' : ''}<w:snapToGrid w:val="0"/><w:spacing w:after="${options.after ?? 100}" w:line="240" w:lineRule="auto"/>${options.center ? '<w:jc w:val="center"/>' : ''}</w:pPr><w:r><w:rPr>${options.bold ? '<w:b/>' : ''}</w:rPr><w:t xml:space="preserve">${xmlValue(value)}</w:t></w:r></w:p>`;
    const cell = (value, width, options = {}) => `<w:tc><w:tcPr><w:tcW w:w="${width}" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>${paragraph(value, options)}</w:tc>`;
    const table = (rows, widths, boldLabels = false) => `<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/><w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders></w:tblPr><w:tblGrid>${widths.map(w => `<w:gridCol w:w="${w}"/>`).join('')}</w:tblGrid>${rows.map(row => `<w:tr><w:trPr><w:cantSplit/></w:trPr>${row.map((v,i) => cell(v,widths[i],{bold:boldLabels && i===0})).join('')}</w:tr>`).join('')}</w:tbl>`;
    const types = Array.isArray(c.endoTypes) ? c.endoTypes.join(', ') : text(c.endoTypes);
    const details = [
      ['PARENT TW REFERENCE', text(c.parentTwRef) || '—'],
      ['ENDORSEMENT REFERENCE', endorsementReference(c)],
      ['ORIGINAL INSURED', text(c.originalInsured) || '—'],
      ['REINSURED', text(c.reinsured) || '—'],
      ['TYPE', text(c.type)],
      ['EFFECTIVE DATE', longDate(c.endoEffectiveDate) || '—'],
      ['ENDORSEMENT TYPE', types || '—']
    ].filter(row => text(row[1]));
    const recipient = [text(c.reinsured), text(c.reinsuredAddress) || 'Taiwan (R.O.C.)'].filter(Boolean).join('\n');
    const contact = [documentDate(), text(c.aeName) ? `In case of query please contact ${text(c.aeName)}` : '', text(c.aeEmail) ? `Email: ${text(c.aeEmail)}` : ''].filter(Boolean).join('\n');
    const body = table([[recipient, contact]], [4900,4846])
      + paragraph('ENDORSEMENT', {bold:true,center:true,after:180,keepNext:true})
      + table(details,[3200,6546],true)
      + paragraph('ENDORSEMENT WORDING', {bold:true,keepNext:true,after:120})
      + String(c.endoText || '—').split(/\r\n|\r|\n/).map(line => paragraph(line)).join('')
      + paragraph('All other terms, conditions and exclusions remain unchanged.',{keepNext:true,after:180})
      + signature + paragraph('For and on behalf of\nTW Insurance Brokers Ltd.') + section[0];
    xml = xml.replace(/<w:body>[\s\S]*?<\/w:body>/, () => `<w:body>${body}</w:body>`);
    xml = normalizeRunTypography(xml);
    xml = resizeTextBlock(xml, 'ENDORSEMENT</w:t>', 'ENDORSEMENT</w:t>', 24);
    zip.file('word/document.xml', xml);
    for (const name of Object.keys(zip.files).filter(n => /^word\/(?:header\d+|footer\d+|footnotes|endnotes)\.xml$/.test(n))) {
      let story = normalizeRunTypography(await zip.file(name).async('string'));
      if (/^word\/footer/.test(name)) {
        story = reorderFooterPageNumber(story);
        // Fields update to the actual page count when Word opens or exports.
        const pageNumber = '<w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:t xml:space="preserve">Page </w:t></w:r><w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple><w:r><w:t xml:space="preserve"> of </w:t></w:r><w:fldSimple w:instr="NUMPAGES"><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p>';
        story = normalizeRunTypography(story.replace('</w:ftr>', pageNumber + '</w:ftr>'));
      }
      zip.file(name, story);
    }
    return zip.generateAsync({type:outputType || 'blob',mimeType:MIME,compression:'DEFLATE',compressionOptions:{level:6}});
  }

  function safeRef(value) {
    return (text(value) || 'DRAFT').replace(/[^A-Za-z0-9._-]+/g, '_');
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return {
    MIME,
    commonValues,
    coverTemplateKey,
    debitTemplateKey,
    generateCover,
    generateDebit,
    generateCredit,
    generateEndorsement,
    downloadBlob,
    coverFilename: c => generatedFilename(c, 'CoverNote'),
    endorsementFilename: c => `Endorsement_${safeRef(endorsementReference(c))}.docx`,
    debitFilename: c => generatedFilename(c, 'DebitNote'),
    creditFilename: c => generatedFilename(c, 'CreditNote'),
  };
}));
