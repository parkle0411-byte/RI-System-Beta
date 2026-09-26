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
    const decimals = currencyLabel(c) === 'USD' ? 2 : 0;
    return number(value).toLocaleString('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  function money(value, c) {
    if (value === '' || value === null || value === undefined) return '';
    return `${currencyLabel(c)}${formatMoney(value, c)}`;
  }

  function percent(value, decimals) {
    if (value === '' || value === null || value === undefined) return '';
    return `${number(value).toFixed(decimals)}%`;
  }

  function percentTrim(value) {
    if (value === '' || value === null || value === undefined) return '';
    const n = number(value);
    const rounded = Math.round((n + Number.EPSILON) * 10000) / 10000;
    const displayed = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
    return `${displayed}%`;
  }

  function longDate(value) {
    if (!value) return '';
    const date = value instanceof Date ? value : new Date(`${value}T00:00:00Z`);
    if (Number.isNaN(date.getTime())) return text(value);
    return new Intl.DateTimeFormat('en-GB', {
      day: '2-digit', month: 'long', year: 'numeric', timeZone: 'UTC',
    }).format(date);
  }

  function documentDate() {
    return longDate(new Date().toISOString().slice(0, 10));
  }

  // The document date line, plus "In case of query please contact <AE
  // name>" / "Email: <AE email>" for whichever AE is assigned to the case
  // (c.aeName/c.aeEmail, resolved from the Sales Staff master). Falls back
  // to just the date when there's no AE on file, rather than showing a
  // broken contact line.
  function contactBlock(c) {
    const lines = [documentDate()];
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
  // installment's cedant amount allocated the same way Accounting/Dashboard
  // do (weighted by installment premium/ratio, last installment absorbing
  // any rounding remainder so the lines foot exactly to NET_DUE).
  function debitDueDate(c) {
    if (!c) return '';
    const validTerms = (value) => {
      const number = Number(value);
      return Number.isInteger(number) && number >= 15 ? number : null;
    };
    const reinsurers = Array.isArray(c.reinsurers) ? c.reinsurers : [];
    const installmentEnabled = c.installmentEnabled === true;
    const rawInstallments = installmentEnabled && Array.isArray(c.performanceInstallments) && c.performanceInstallments.length
      ? c.performanceInstallments : [{ performanceMonth: '', paymentBaseDate: c.policyFrom }];
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
    const total = financials(c).netDue;
    const roundMoney = (value) => Math.round((Number(value) + Number.EPSILON) * 100) / 100;
    let used = 0;
    const rows = rawInstallments.map((installment, index) => {
      const terms = reinsurers.map((reinsurer, rIndex) => {
        const map = installment.reinsurerPaymentTerms && typeof installment.reinsurerPaymentTerms === 'object' ? installment.reinsurerPaymentTerms : {};
        return validTerms(map['r' + (rIndex + 1)]) ?? validTerms(reinsurer?.paymentTermsDays) ?? validTerms(installment.paymentTermsDays) ?? validTerms(c.paymentTermsDays);
      }).filter((value) => value != null);
      const shortest = terms.length ? Math.min(...terms) : validTerms(installment.paymentTermsDays) ?? validTerms(c.paymentTermsDays);
      const baseDate = installment.paymentBaseDate || c.policyFrom;
      let dueDate = '';
      if (baseDate && shortest != null) {
        const date = new Date(baseDate + 'T00:00:00Z');
        if (!Number.isNaN(date.getTime())) {
          date.setUTCDate(date.getUTCDate() + shortest - 15);
          dueDate = date.toISOString().slice(0, 10);
        }
      }
      const amount = index === rawInstallments.length - 1 ? roundMoney(total - used) : roundMoney(total * w[index] / weightSum);
      if (index !== rawInstallments.length - 1) used = roundMoney(used + amount);
      const label = installmentEnabled ? (text(installment.performanceMonth) ? `${text(installment.performanceMonth)} instalment` : `Instalment ${index + 1}`) : '';
      return { label, dueDate, amount };
    }).filter((row) => row.dueDate).sort((a, b) => a.dueDate.localeCompare(b.dueDate));
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
    if (item.code === 'INTERMEDIARY') return LEGACY_CLAUSE_TITLES.INTERMEDIARY;
    return text(item.title) || item.code;
  }

  function sumInsuredRows(c) {
    const situations = Array.isArray(c && c.situations) ? c.situations : [];
    const rows = Array.isArray(c && c.sumInsured) ? c.sumInsured : [];
    const showLocation = !(Array.isArray(c && c.reinsurers) && c.reinsurers.length && c.reinsurers.every(r => isFacility(r.name)));
    return rows.filter(row => text(row.category) || number(row.amount) !== 0).map(row => {
      const index = Number.isInteger(row.locationIndex) ? row.locationIndex : number(row.locationIndex);
      const location = situations[index] ? situationAddress(situations[index]) : '';
      const prefix = showLocation ? `Location ${index + 1}${location ? ` - ${location}` : ''}: ` : '';
      return {
        label: `${prefix}${text(row.category) || '—'}`,
        amount: formatMoney(row.amount, c),
        numericAmount: number(row.amount),
      };
    });
  }

  function lossValues(c) {
    const rows = Array.isArray(c && c.lossRecord) ? c.lossRecord : [];
    const years = Number.parseInt(c && c.lossRecordYears, 10);
    const periodYears = years > 0 ? years : 5;
    const countText = rows.length === 0 ? 'Loss Clean' : `${rows.length} ${rows.length === 1 ? 'loss' : 'losses'}`;
    let summary = `${countText} in the past ${periodYears} ${periodYears === 1 ? 'year' : 'years'}`;
    if (text(c && c.lossAdvisedDate)) summary += ` (as advised by TW Insurance Brokers Ltd. on ${longDate(c.lossAdvisedDate)})`;
    return {
      summary,
      dates: rows.map(row => longDate(row.date) || '—').join('\n'),
      causes: rows.map(row => text(row.cause) || '—').join('\n'),
      paid: rows.map(row => formatMoney(row.lossPaid, c)).join('\n'),
    };
  }

  function financials(c) {
    const reinsurers = Array.isArray(c && c.reinsurers) ? c.reinsurers : [];
    const order = reinsurers.reduce((total, row) => total + number(row.sharePct), 0);
    const originalPremium = number(c && c.originalPremium);
    const cededPremium = originalPremium * order / 100;
    const commission = cededPremium * number(c && c.riCommPct) / 100;
    const tax = cededPremium * number(c && c.taxPct) / 100;
    return { order, originalPremium, cededPremium, commission, tax, netDue: cededPremium - commission - tax };
  }

  function commonValues(c) {
    const fin = financials(c);
    const sums = sumInsuredRows(c);
    const losses = lossValues(c);
    const situations = Array.isArray(c && c.situations) ? c.situations : [];
    const reinsurers = Array.isArray(c && c.reinsurers) ? c.reinsurers : [];
    const clauses = clauseDetails(c);
    const addressLines = [text(c && c.reinsured), text(c && c.reinsuredAddress) || 'Taiwan (R.O.C.)'].filter(Boolean);
    const originalExclusions = appendRequiredTail(c && c.originalExclusions, ORIGINAL_CONDITIONS_TAIL);
    const originalConditions = appendRequiredTail(c && c.originalConditions, ORIGINAL_CONDITIONS_TAIL);
    const reinsuranceConditions = [REINSURANCE_INTRO].concat(clauses.map(item => `•\u00a0${clauseLine(item)}`)).join('\n');
    return {
      RECIPIENT_BLOCK: addressLines.join('\n'),
      CONTACT_BLOCK: contactBlock(c),
      TW_REF: text(c && c.twRef) || 'DRAFT',
      TYPE: text(c && c.type),
      ORIGINAL_INSURED: text(c && c.originalInsured),
      REINSURED: text(c && c.reinsured),
      PERIOD: period(c, true),
      PERIOD_SHORT: period(c, false),
      INTEREST: text(c && c.interest),
      LIMIT_OF_LIABILITY: money(c && c.limitOfLiability, c),
      AGGREGATE_LIMIT: money(c && c.aggregateLimit, c),
      UNDERLYING_LIMITS: text(c && c.underlyingLimits),
      SUB_LIMITS: text(c && c.subLimits),
      DEDUCTIBLES: text(c && c.deductibles),
      REINSURED_RETENTION: text(c && c.reinsuredRetention),
      REINSTATEMENT_PROVISIONS: text(c && c.reinstatementProvisions),
      INDEMNITY_PERIOD: text(c && c.indemnityPeriod),
      ORIGINAL_EXCLUSIONS: originalExclusions,
      LOCATION: situations.map((item, index) => `${index + 1}. ${situationAddress(item)}`).join('\n'),
      SITUATION: situations.map((item, index) => `${index + 1}. ${situationAddress(item)}`).join('\n'),
      TOTAL_SUM_INSURED: money(sums.reduce((total, row) => total + row.numericAmount, 0), c),
      POLICY_LIMIT: money(c && c.aggregateLimit, c),
      BASIS_OF_VALUATION: basisOfValuation(c),
      ORIGINAL_CONDITIONS: originalConditions,
      REINSURANCE_CONDITIONS: reinsuranceConditions,
      LOSS_PAYEE: text(c && c.lossPayee),
      NOTICES: text(c && c.notices),
      EXPRESS_WARRANTIES: text(c && c.expressWarranties),
      CONDITIONS_PRECEDENT: text(c && c.conditionsPrecedent),
      SUBJECTIVITIES: text(c && c.subjectivities),
      PREMIUM: money(c && c.originalPremium, c),
      ORDER_HEREON: `${percentTrim(fin.order)} of 100%`,
      ORDER_HEREON_DEBIT: percentTrim(fin.order),
      CEDING_COMMISSION: percent(c && c.riCommPct, 2),
      TAX: percent(c && c.taxPct, 2),
      PAYMENT_TERMS: `${text(c && c.paymentTermsDays) || '0'} Day Payment condition - LSW 3001 Premium Payment Clause`,
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
      SPECIAL_AGREEMENT: text(c && c.specialAgreement) || 'Nil',
      SECURITY_NAMES: reinsurers.map(row => stripFacility(row.name) || '(Reinsurer)').join('\n'),
      SECURITY_SHARES: reinsurers.map(row => percentTrim(row.sharePct)).join('\n'),
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
  // table row carrying that field is removed from the Cover Note rather
  // than leaving an empty-looking row. Fields that always carry content
  // (defaults, boilerplate, or required case data) are left out of this
  // list on purpose.
  const OPTIONAL_KEYS = [
    'AGGREGATE_LIMIT', 'POLICY_LIMIT', 'LOSS_LIMIT',
    'UNDERLYING_LIMITS', 'SUB_LIMITS', 'DEDUCTIBLES', 'REINSURED_RETENTION',
    'REINSTATEMENT_PROVISIONS', 'INDEMNITY_PERIOD', 'LOSS_PAYEE', 'NOTICES',
    'EXPRESS_WARRANTIES', 'CONDITIONS_PRECEDENT', 'SUBJECTIVITIES',
    'OCCUPATION', 'CONSTRUCTION',
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

  function isBlankRowText(rowXml) {
    const runs = rowXml.match(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>/g) || [];
    return !runs.some(run => run.replace(/^<w:t\b[^>]*>/, '').replace(/<\/w:t>$/, '').trim().length > 0);
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
      ? rows.map(entry => renderTemplateRow(anchorRowXml, buildSubs(entry))).join('')
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
    const replacement = paragraphs.length ? paragraphs.join('') : `<w:p>${pPr}</w:p>`;
    return xml.slice(0, span.start) + replacement + xml.slice(span.end);
  }

  // Expands the Cover Note's three multi-entry sections — Breakdown of
  // Sum Insured, Loss Record and Schedule of Security — into one table
  // row per actual entry instead of cramming every entry's text into the
  // template's single first data row.
  function expandDocumentRepeatingRows(xml, c) {
    const sums = sumInsuredRows(c);
    xml = expandRepeatingRows(xml, '{{SUM_INSURED_LABELS}}', sums, row => ({
      '{{SUM_INSURED_LABELS}}': row.label,
      '{{SUM_INSURED_AMOUNTS}}': row.amount,
    }));

    const lossRows = Array.isArray(c && c.lossRecord) ? c.lossRecord : [];
    xml = expandRepeatingRows(xml, '{{LOSS_DATES}}', lossRows, row => ({
      '{{LOSS_DATES}}': longDate(row.date) || '—',
      '{{LOSS_CAUSES}}': text(row.cause) || '—',
      '{{LOSS_PAID}}': formatMoney(row.lossPaid, c),
    }), { wholeFrameWhenEmpty: true });

    const reinsurers = Array.isArray(c && c.reinsurers) ? c.reinsurers : [];
    const totalSharePct = reinsurers.reduce((total, row) => total + number(row.sharePct), 0);
    // The template's row has the {{SECURITY_NAMES}} token in its narrow
    // (left) cell and {{SECURITY_SHARES}} in its wide (right) cell. The
    // desired layout is share % on the left, reinsurer name on the right,
    // so the values are swapped relative to the token names below.
    xml = expandRepeatingRows(xml, '{{SECURITY_NAMES}}', reinsurers, row => ({
      '{{SECURITY_NAMES}}': percentTrim(row.sharePct),
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
        '{{SECURITY_NAMES}}': percentTrim(totalSharePct),
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

    const originalConditionsText = appendRequiredTail(c && c.originalConditions, ORIGINAL_CONDITIONS_TAIL);
    xml = expandListParagraph(xml, '{{ORIGINAL_CONDITIONS}}', originalConditionsText.split('\n').filter(Boolean), {
      numId: DECIMAL_LIST_NUM_ID,
    });

    const originalExclusionsText = appendRequiredTail(c && c.originalExclusions, ORIGINAL_CONDITIONS_TAIL);
    xml = expandListParagraph(xml, '{{ORIGINAL_EXCLUSIONS}}', originalExclusionsText.split('\n').filter(Boolean), {
      numId: DECIMAL_LIST_NUM_ID,
    });

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

  async function fillTemplate(base64, c, values, outputType) {
    const zip = await JSZip.loadAsync(base64, { base64: true });
    const names = Object.keys(zip.files).filter(name => /\.xml$/i.test(name));
    await Promise.all(names.map(async name => {
      const file = zip.file(name);
      if (!file) return;
      let xml = await file.async('string');
      let changed = false;
      if (/^word\/document\.xml$/i.test(name)) {
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
      if (/^word\/footer\d+\.xml$/i.test(name)) {
        const reordered = reorderFooterPageNumber(xml);
        if (reordered !== xml) {
          xml = reordered;
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
    return fillTemplate(templates[key], c, commonValues(c), outputType);
  }

  async function generateDebit(c, templates, outputType) {
    const key = debitTemplateKey(c);
    if (!templates || !templates[key]) throw new Error(`Missing Word template: ${key}`);
    return fillTemplate(templates[key], c, commonValues(c), outputType);
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
    downloadBlob,
    coverFilename: c => `CoverNote_${safeRef(c && c.twRef)}.docx`,
    debitFilename: c => `DebitNote_${safeRef(c && c.twRef)}.docx`,
  };
}));