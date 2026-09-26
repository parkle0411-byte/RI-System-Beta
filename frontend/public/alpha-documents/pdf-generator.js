(function (global) {
  'use strict';

  const A4 = { width: 794, height: 1123, pdfWidth: 595.28, pdfHeight: 841.89 };
  const RASTER_SCALE = 1.5;
  const ADDRESS = 'TW Insurance Brokers Ltd. | 4F., No.23, Longjiang Rd., Zhongshan Dist., Taipei City 104, Taiwan. | T: +886-2-8772-2277 F: +886-2-8772-2748';
  const EXCLUSIONS_TAIL = 'All other terms and conditions are subject to original policy wordings.';
  const SECURITY_NOTICE = 'Your attention is drawn to the fact that the reinsurance contract(s) may contain certain warranties and/or conditions precedent to liability which, if not strictly adhered to, could void or invalidate the contract(s) of reinsurance. It is important however that any warranties and/or conditions precedent to liability are read in conjunction with all the other terms and conditions of the reinsurance contract(s) and not in isolation thereof. All contracts of reinsurance are founded on the principle of Utmost Good Faith. In addition to the full disclosure of the risk made at the inception of the reinsurance contract(s), it is important to realise that the duty to disclose material facts is a continuing duty during the term of the reinsurance contract(s).';
  const EXAMINE_NOTICE = 'Please examine the details of this Reinsurance Document carefully. If it is incorrect or you do not accept the security please advise us immediately and return this document so that we may endeavour to arrange the required alteration or amendment. All wordings and clauses stated hereon are available on request. If you are unsure of the content of any of the wordings or clauses stated please request a copy of such clause from TW Insurance Brokers.';
  const LIABILITY_TEXT = [
    '(Re)insurer’s liability several not joint',
    'The liability of a (re)insurer under this contract is several and not joint with other (re)insurers party to this contract. A (re)insurer is liable only for the proportion of liability it has underwritten. A (re)insurer is not jointly liable for the proportion of liability underwritten by any other (re)insurer. Nor is a (re)insurer otherwise responsible for any liability of any other (re)insurer that may underwrite this contract.',
    'The proportion of liability under this contract underwritten by a (re)insurer (or, in the case of a Lloyd’s syndicate, the total of the proportions underwritten by all the members of the syndicate taken together) is shown next to its stamp. This is subject always to the provision concerning “signing” below.',
    'In the case of a Lloyd’s syndicate, each member of the syndicate (rather than the syndicate itself) is a (re)insurer. Each member has underwritten a proportion of the total shown for the syndicate (that total itself being the total of the proportions underwritten by all the members of the syndicate taken together). The liability of each member of the syndicate is several and not joint with other members. A member is liable only for that member’s proportion. A member is not jointly liable for any other member’s proportion. Nor is any member otherwise responsible for any liability of any other (re)insurer that may underwrite this contract. The business address of each member is Lloyd’s, One Lime Street, London EC3M 7HA. The identity of each member of a Lloyd’s syndicate and their respective proportion may be obtained by writing to Market Services, Lloyd’s, at the above address.',
    'Proportion of liability',
    'Unless there is “signing” (see below), the proportion of liability under this contract underwritten by each (re)insurer (or, in the case of a Lloyd’s syndicate, the total of the proportions underwritten by all the members of the syndicate taken together) is shown next to its stamp and is referred to as its “written line”.',
    'Where this contract permits, written lines, or certain written lines, may be adjusted (“signed”). In that case a schedule is to be appended to this contract to show the definitive proportion of liability under this contract underwritten by each (re)insurer (or, in the case of a Lloyd’s syndicate, the total of the proportions underwritten by all the members of the syndicate taken together). A definitive proportion is referred to as a “signed line”. The signed lines shown in the schedule will prevail over the written lines unless a proven error in calculation has occurred.',
    'Although reference is made at various points in this clause to “this contract” in the singular, where the circumstances so require this should be read as a reference to contracts in the plural.',
    'LMA3333 | 21 June 2007'
  ];
  const INTERMEDIARY_TEXT = 'TW Insurance Brokers Ltd. is hereby recognized as the Intermediary negotiating this Agreement. All communications (including notices, statements, premiums, return premiums, commissions, taxes, loss expense, salvage and settlements) relating thereto shall be transmitted to the Reinsured or the Reinsurers through the Intermediary at the address shown below: 4F., No.23, Long Jiang Road, Taipei City, 10492 Taiwan.';

  function esc(value) {
    return String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function situationAddress(item) {
    return [String(item && item.address || '').trim(), String(item && item.postcode || '').trim()].filter(Boolean).join(' ');
  }
  function number(value, decimals) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '';
    return n.toLocaleString('en-US', { minimumFractionDigits: decimals || 0, maximumFractionDigits: decimals || 0 });
  }
  function pct(value, decimals) {
    const n = Number(value);
    return Number.isFinite(n) ? `${n.toFixed(decimals == null ? 2 : decimals)}%` : '';
  }
  function pctActual(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '';
    const rounded = Math.round((n + Number.EPSILON) * 10000) / 10000;
    const displayed = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(4).replace(/0+$/,'').replace(/\.$/,'');
    return `${displayed}%`;
  }
  function longDate(value) {
    if (!value) return '';
    const d = new Date(`${value}T00:00:00`);
    return Number.isNaN(d.getTime()) ? String(value) : new Intl.DateTimeFormat('en-GB', { day:'2-digit', month:'long', year:'numeric' }).format(d);
  }
  function today() {
    return new Intl.DateTimeFormat('en-GB', { day:'2-digit', month:'long', year:'numeric' }).format(new Date());
  }
  function policyTime(value) { return value === '00:00' ? '00:00' : '12:00'; }
  function policyPeriod(c) {
    return `From ${longDate(c.policyFrom)} at ${policyTime(c.policyFromTime)} to ${longDate(c.policyTo)} at ${policyTime(c.policyToTime)} Local Standard Time at the location of the Reinsured.`;
  }
  // Cedant due date(s) with the amount due on each one. A single installment
  // (the common, non-split case) yields one row whose amount is the whole
  // case total, unchanged from before. With 2+ installments, the total is
  // allocated across them the same way Accounting/Dashboard do (weighted by
  // installment premium/ratio, last installment absorbing any rounding
  // remainder so the rows foot exactly to the case total), instead of
  // showing the earliest date next to the full amount, which would imply
  // the whole premium is due that early.
  function debitSchedule(c) {
    if (!c) return [];
    const validTerms = (value) => {
      const number = Number(value);
      return Number.isInteger(number) && number >= 15 ? number : null;
    };
    const reinsurers = Array.isArray(c.reinsurers) ? c.reinsurers : [];
    const installmentEnabled = c.installmentEnabled === true;
    const raw = installmentEnabled && Array.isArray(c.performanceInstallments) && c.performanceInstallments.length
      ? c.performanceInstallments : [{ performanceMonth: '', paymentBaseDate: c.policyFrom }];
    const weights = raw.map((row) => {
      if (!installmentEnabled) return 1;
      const premium = Number(row.premium);
      if (Number.isFinite(premium) && row.premium !== '' && row.premium != null) return Math.max(0, premium);
      const ratio = Number(row.ratio);
      return Math.max(0, Number.isFinite(ratio) ? ratio : 0);
    });
    let weightSum = weights.reduce((a, b) => a + b, 0);
    let w = weights;
    if (weightSum <= 0) { weightSum = raw.length; w = raw.map(() => 1); }
    const share = totalShare(c);
    const premium = Number(c.originalPremium) || 0;
    const ceded = premium * share / 100;
    const commission = ceded * (Number(c.riCommPct) || 0) / 100;
    const tax = ceded * (Number(c.taxPct) || 0) / 100;
    const total = ceded - commission - tax;
    const roundMoney = (value) => Math.round((Number(value) + Number.EPSILON) * 100) / 100;
    let used = 0;
    const rows = raw.map((installment, index) => {
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
      const amount = index === raw.length - 1 ? roundMoney(total - used) : roundMoney(total * w[index] / weightSum);
      if (index !== raw.length - 1) used = roundMoney(used + amount);
      const label = installmentEnabled ? (String(installment.performanceMonth || '').trim() ? `${String(installment.performanceMonth).trim()} instalment` : `Instalment ${index + 1}`) : '';
      return { label, dueDate, amount };
    }).filter((row) => row.dueDate);
    return rows.sort((a, b) => a.dueDate.localeCompare(b.dueDate));
  }
  function tail(value) {
    const s = String(value || '').trim();
    return s.toLowerCase().includes(EXCLUSIONS_TAIL.toLowerCase()) ? s : [s, EXCLUSIONS_TAIL].filter(Boolean).join('\n');
  }
  // Matches the Word document's native numbered list (1. 2. 3. ...) for
  // Original Conditions / Original Exclusions.
  function numberedLines(value) {
    return String(value || '').split('\n').filter(Boolean).map((line, i) => `${i + 1}. ${line}`).join('\n');
  }
  function isFacility(name) {
    return /\(Facility\)\s*$/i.test(String(name || '').trim());
  }
  function stripFacility(name) {
    return String(name || '').trim().replace(/\s*\(Facility\)\s*$/i, '');
  }
  function totalShare(c) {
    return (Array.isArray(c.reinsurers) ? c.reinsurers : []).reduce((sum, r) => sum + (Number(r.sharePct) || 0), 0);
  }
  function titleOfClause(item) {
    const code = String(item && item.code || '').trim().toUpperCase();
    const title = String(item && item.title || '').trim();
    if (code === 'INTERMEDIARY') return title || 'Intermediary Clause (TW Insurance Brokers Ltd.)';
    return title || code;
  }
  function clauses(c) {
    const details = Array.isArray(c.clauseDetails) ? c.clauseDetails : [];
    const codes = Array.isArray(c.clauses) ? c.clauses : [];
    return codes.map(code => {
      const normalized = String(code || '').trim().toUpperCase();
      const found = details.find(x => String(x && x.code || '').trim().toUpperCase() === normalized);
      return titleOfClause(found || { code: normalized, title: normalized });
    });
  }
  function basis(c) { return c.basisOfValuation === 'Other' ? c.basisOfValuationOther : c.basisOfValuation; }
  function typeText(c) { return c.type || ''; }
  // Matches docx-generator.js's currencyLabel/money exactly: the case's
  // actual stored currency ("TWD" or "USD"), never the old hardcoded "NTD",
  // and no space between the currency code and the amount.
  function currency(c) { return String(c.currency || '').toUpperCase() === 'USD' ? 'USD' : 'TWD'; }
  function money(c, value, decimals) { const v = number(value, decimals); return v ? `${currency(c)}${v}` : ''; }
  function rows(items) {
    return items.filter(x => x && String(x[1] == null ? '' : x[1]).trim()).map(([label, value]) => `<div class="row"><div class="label">${esc(label)}</div><div class="value">${esc(value).replace(/\n/g,'<br />')}</div></div>`).join('');
  }
  function header(c, title, withLogo) {
    // "In case of query..." / "Email: ..." use whichever AE is assigned to
    // the case (c.aeName/c.aeEmail, resolved from the Sales Staff master),
    // and are omitted rather than shown broken when there's no AE on file.
    const aeName = String(c.aeName || '').trim();
    const aeEmail = String(c.aeEmail || '').trim();
    const contactLine = aeName ? `<div>In case of query please contact ${esc(aeName)}</div>` : '';
    const emailLine = aeEmail ? `<div>Email: ${esc(aeEmail)}</div>` : '';
    return `${withLogo ? `<img class="logo" src="${global.RI_PDF_ASSETS.logo}" />` : ''}<div class="header-meta"><div class="recipient"><div>${esc(c.reinsured || '')}</div><div>${esc(c.reinsuredAddress || 'Taiwan (R.O.C.)').replace(/\n/g,'<br />')}</div></div><div class="contact"><div>${today()}</div>${contactLine}${emailLine}</div></div><div class="doc-title">${esc(title)}</div>`;
  }
  function footer(page, count) { return `<div class="footer">${esc(ADDRESS)}</div><div class="page-no">Page ${page} of ${count}</div>`; }
  function page(body, pageNo, count, cls) { return `<div class="page ${cls || ''}">${body}${footer(pageNo,count)}</div>`; }
  function heading(text) { return `<h2>${esc(text)}</h2>`; }
  function sumTable(c) {
    const entries = (Array.isArray(c.sumInsured) ? c.sumInsured : []).filter(r => String(r.category || '').trim() || Number(r.amount));
    const decimals = currency(c)==='USD'?2:0;
    // One row per entry, ending with a Total row — matches the Word
    // document's Breakdown of Sum Insured table exactly, instead of
    // cramming every entry into one <br />-joined cell.
    const showLocation = !(Array.isArray(c.reinsurers) && c.reinsurers.length && c.reinsurers.every(r => isFacility(r.name)));
    const dataRows = entries.map(r => {
      const index = r.locationIndex || 0;
      const location = c.situations && c.situations[index] ? situationAddress(c.situations[index]) : '';
      const prefix = showLocation ? `Location ${index + 1}${location ? ` - ${location}` : ''}: ` : '';
      return `<tr><td>${esc(`${prefix}${r.category || '—'}`)}</td><td class="num">${esc(number(r.amount, decimals))}</td></tr>`;
    }).join('');
    const total = entries.reduce((s,r)=>s+(Number(r.amount)||0),0);
    return `<table class="amount-table"><tbody>${dataRows}<tr class="total"><td>Total</td><td class="num">${esc(number(total,decimals))}</td></tr></tbody></table>`;
  }
  function lossTable(c) {
    const losses = Array.isArray(c.lossRecord) ? c.lossRecord : [];
    const years = Number(c.lossRecordYears) || 5;
    const summary = `${losses.length ? `${losses.length} ${losses.length===1?'loss':'losses'}` : 'Loss Clean'} in the past ${years} ${years===1?'year':'years'}${c.lossAdvisedDate ? ` (as advised by TW Insurance Brokers Ltd. on ${longDate(c.lossAdvisedDate)})` : ''}`;
    if (!losses.length) return `<div>${esc(summary)}</div>`;
    return `<div>${esc(summary)}</div><table class="loss-table"><thead><tr><th>Date of Loss</th><th>Cause</th><th>Loss Paid</th></tr></thead><tbody>${losses.map(r=>`<tr><td>${esc(longDate(r.date))}</td><td>${esc(r.cause||'')}</td><td>${esc(number(r.lossPaid,currency(c)==='USD'?2:0))}</td></tr>`).join('')}</tbody></table>`;
  }
  function coverPages(c) {
    const ref = c.twRef || 'DRAFT';
    const count = 5;
    const xol = /excess|xol/i.test(String(c.structure || c.reinsuranceStructure || '')) || /excess/i.test(String(c.type || ''));
    const situations = (c.situations || []).map((s,i)=>`${i+1}. ${situationAddress(s)}`).join('\n');
    const clauseLines = clauses(c).map(x=>`• ${x}`).join('\n');
    const p1Rows = xol ? [
      ['TYPE',typeText(c)],['REINSURED',c.reinsured],['ORIGINAL INSURED',c.originalInsured],['PERIOD',policyPeriod(c)],['LOCATION',situations],['INTEREST',c.interest],['TOTAL SUM INSURED',money(c,(c.sumInsured||[]).reduce((s,r)=>s+(Number(r.amount)||0),0),currency(c)==='USD'?2:0)],['LIMIT OF LIABILITY',money(c,c.limitOfLiability,currency(c)==='USD'?2:0)],['POLICY LIMIT',money(c,c.aggregateLimit,currency(c)==='USD'?2:0)],['UNDERLYING LIMITS',c.underlyingLimits],['SUB-LIMITS',c.subLimits],['DEDUCTIBLES',c.deductibles],["REINSURED’S RETENTION",c.reinsuredRetention],['REINSTATEMENT PROVISIONS',c.reinstatementProvisions],['INDEMNITY PERIOD',c.indemnityPeriod],['SITUATION',situations],['BASIS OF VALUATION',basis(c)]
    ] : [
      ['TYPE',typeText(c)],['ORIGINAL INSURED',c.originalInsured],['REINSURED',c.reinsured],['ORIGINAL POLICY PERIOD',policyPeriod(c)],['INTEREST',c.interest],['LIMIT OF LIABILITY',money(c,c.limitOfLiability,0)],['AGGREGATE LIMIT',money(c,c.aggregateLimit,0)],['UNDERLYING LIMITS',c.underlyingLimits],['SUB-LIMITS',c.subLimits],['DEDUCTIBLES',c.deductibles],["REINSURED’S RETENTION",c.reinsuredRetention],['REINSTATEMENT PROVISIONS',c.reinstatementProvisions],['INDEMNITY PERIOD',c.indemnityPeriod],['ORIGINAL EXCLUSIONS',numberedLines(tail(c.originalExclusions))],['SITUATION',situations],['BASIS OF VALUATION',basis(c)],['ORIGINAL CONDITIONS',numberedLines(tail(c.originalConditions))]
    ];
    const p2Rows = [
      ['REINSURANCE CONDITIONS',`This Reinsurance is subject to the same terms and conditions as the Original Policy except as otherwise provided herein and Reinsurers will follow the Wordings, Clauses and Settlements of the Original Policy.\n${clauseLines}`],['LOSS PAYEE',c.lossPayee],['NOTICES',c.notices],['EXPRESS WARRANTIES',c.expressWarranties],['CONDITIONS PRECEDENT',c.conditionsPrecedent],['SUBJECTIVITIES',c.subjectivities],['CHOICE OF LAW AND JURISDICTION','This (re)insurance shall be governed by and construed in accordance with the law of Republic of China, Taiwan and each party agrees to submit to the exclusive jurisdiction of the Courts of the Republic of China, Taiwan.'],['100% PREMIUM',money(c,c.originalPremium,0)],['ORDER HEREON',`${pctActual(totalShare(c))} of 100%`],['CEDING COMMISSION',pct(c.riCommPct,2)],['TAX PAYABLE BY REINSURER',pct(c.taxPct,2)],['PREMIUM PAYMENT TERMS',`${c.paymentTermsDays || ''} Day Payment condition - LSW 3001 Premium Payment Clause`],['RECORDING TRANSMITTING & STORING INFORMATION','Where TW Insurance Brokers Ltd. maintains risk and/or claim data/information/documents the Broker may hold such data/information/documents electronically.'],['REINSURER CONTRACT DOCUMENTATION','This document details the contract terms entered into by the Reinsurer(s) and constitutes the contract document. No further contractual documentation to be produced, other than Intermediary Slip Endorsement(s) evidencing any amendments or alterations hereto.']
    ];
    const p1 = page(`<div class="content">${header(c,`COVER NOTE NO. ${ref}`,true)}<p class="intro">This Document provides evidence of the cover given by The Reinsurer(s) with whom this Reinsurance has been placed and has been prepared by TW Insurance Brokers acting as your Reinsurance Broker.</p>${heading('RISK DETAILS')}<div class="rows">${rows(p1Rows)}</div></div>`,1,count,'cover');
    const p2 = page(`<div class="content continued"><img class="logo small" src="${global.RI_PDF_ASSETS.logo}" /><div class="continued-title">COVER NOTE NO. ${esc(ref)} (continued)</div><div class="rows">${rows(p2Rows)}</div></div>`,2,count,'cover compact');
    const sumEntries = (Array.isArray(c.sumInsured) ? c.sumInsured : []).filter(r => String(r.category || '').trim() || Number(r.amount));
    const p3Optional = [
      String(c.occupation||'').trim() ? `<div class="row"><div class="label">OCCUPATION</div><div class="value">${esc(c.occupation)}</div></div>` : '',
      String(c.construction||'').trim() ? `<div class="row"><div class="label">CONSTRUCTION</div><div class="value">${esc(c.construction)}</div></div>` : '',
      sumEntries.length ? `<div class="row"><div class="label">BREAKDOWN OF SUM INSURED</div><div class="value">${sumTable(c)}</div></div>` : '',
      `<div class="row"><div class="label">LOSS RECORD</div><div class="value">${lossTable(c)}</div></div>`,
      `<div class="row"><div class="label">SPECIAL AGREEMENT</div><div class="value">${esc(c.specialAgreement||'Nil')}</div></div>`
    ].join('');
    const p3 = page(`<div class="content">${global.RI_PDF_ASSETS.logo ? `<img class="logo small" src="${global.RI_PDF_ASSETS.logo}" />` : ''}<div class="continued-title">COVER NOTE NO. ${esc(ref)} (continued)</div>${heading('INFORMATION')}<p>The following information was provided to Reinsurer(s) to support the assessment of the risk at the time of underwriting:</p>${p3Optional}</div>`,3,count,'cover');
    // Share % on the left, reinsurer name on the right, ending with a
    // total row ("X% of 100%") — matches the Word document's Schedule of
    // Security layout exactly.
    const security = (c.reinsurers||[]).map(r=>`<div class="security-row"><span>${esc(pctActual(r.sharePct))}</span><span>${esc(stripFacility(r.name) || '(Reinsurer)')}</span></div>`).join('');
    const securityTotal = (c.reinsurers||[]).length
      ? `<div class="security-row security-total"><span>${esc(pctActual(totalShare(c)))}</span><span>of 100%</span></div>`
      : '';
    const lossLimit = xol ? `<div class="row"><div class="label">LOSS LIMIT</div><div class="value">${esc(money(c,c.limitOfLiability,2))}</div></div>` : '';
    const p4 = page(`<div class="content"><img class="logo small" src="${global.RI_PDF_ASSETS.logo}" /><div class="continued-title">COVER NOTE NO. ${esc(ref)} (continued)</div>${heading('SCHEDULE OF SECURITY')}<p>Reinsurers as follows:</p>${lossLimit}<div class="security">${security}${securityTotal}</div><div class="security-notice"><p>${esc(SECURITY_NOTICE)}</p><p>${esc(EXAMINE_NOTICE)}</p></div><img class="signature" src="${global.RI_PDF_ASSETS.signature}" /><div>For and on behalf of<br />TW Insurance Brokers Ltd.</div></div>`,4,count,'cover');
    const liability = LIABILITY_TEXT.map(x=>`<p>${esc(x)}</p>`).join('');
    const p5 = page(`<div class="content clause-page"><img class="logo small" src="${global.RI_PDF_ASSETS.logo}" /><div class="continued-title">Attaching to and forming part of Cover Note No. ${esc(ref)}</div>${heading('(RE)INSURERS LIABILITY CLAUSE')}<div class="clause-text">${liability}</div>${heading('INTERMEDIARY CLAUSE')}<div class="clause-text"><p>${esc(INTERMEDIARY_TEXT)}</p></div></div>`,5,count,'cover');
    return [p1,p2,p3,p4,p5];
  }
  function endorsementPages(c) {
    const reference = c.twRef || `${c.parentTwRef || 'DRAFT'}-E${String(c.endorsementSeq || '').padStart(2, '0')}`;
    const types = Array.isArray(c.endoTypes) ? c.endoTypes.join(', ') : String(c.endoTypes || '');
    const body = `<div class="content endorsement">${header({ ...c, twRef: reference }, 'ENDORSEMENT', true)}
      ${rows([
        ['PARENT TW REFERENCE', c.parentTwRef || '—'],
        ['ENDORSEMENT REFERENCE', reference],
        ['ORIGINAL INSURED', c.originalInsured || '—'],
        ['REINSURED', c.reinsured || '—'],
        ['TYPE', typeText(c)],
        ['EFFECTIVE DATE', longDate(c.endoEffectiveDate) || '—'],
        ['ENDORSEMENT TYPE', types || '—']
      ])}
      <h2>ENDORSEMENT WORDING</h2>
      <div class="endorsement-wording">${String(c.endoText || '—').split('\n').map(line => `<p>${esc(line) || '&nbsp;'}</p>`).join('')}</div>
      <p class="endorsement-continuity">All other terms, conditions and exclusions remain unchanged.</p>
      <img class="signature endorsement-signature" src="${global.RI_PDF_ASSETS.signature}" />
      <div>For and on behalf of<br />TW Insurance Brokers Ltd.</div>
    </div>`;
    return [page(body, 1, 1, 'endorsement-page')];
  }

  function debitPages(c) {
    const share = totalShare(c);
    const premium = Number(c.originalPremium)||0;
    const ceded = premium * share / 100;
    const commission = ceded * (Number(c.riCommPct)||0) / 100;
    const tax = ceded * (Number(c.taxPct)||0) / 100;
    const due = ceded - commission - tax;
    const usd = currency(c)==='USD';
    const cur = currency(c);
    const decimals = usd ? 2 : 0;
    const account = usd ? '00590-180-00179-6' : '00590-120-00756-6';
    const name = usd ? 'United States Dollar' : 'New Taiwan Dollar';
    const premiumRows = [
      ['PREMIUM','',cur,number(premium,decimals)],['ORDER HEREON',pctActual(share),cur,number(ceded,decimals)],['Less CEDING COMMISSION',pct(c.riCommPct,2),cur,number(commission,decimals)],['Less TAX',pct(c.taxPct,2),cur,number(tax,decimals)]
    ].map(r=>`<div class="premium-row"><span>${esc(r[0])}</span><span>${esc(r[1])}</span><span>${esc(r[2])}</span><span>${esc(r[3]||'')}</span></div>`).join('');
    const schedule = debitSchedule(c);
    const paymentRows = (schedule.length ? schedule : [{ label: '', dueDate: '', amount: due }]).map((row) => `<span>${schedule.length > 1 && row.label ? esc(row.label) + ': ' : ''}${esc(longDate(row.dueDate) || '—')}</span><b>${cur}</b><span>${number(row.amount, decimals)}</span>`).join('');
    const body = `<div class="content debit">${header(c,'DEBIT NOTE',true)}${rows([['TW REFERENCE',c.twRef],['ORIGINAL INSURED',c.originalInsured],['REINSURED',c.reinsured],['TYPE',typeText(c)],['PERIOD',`From ${longDate(c.policyFrom)} to ${longDate(c.policyTo)}`],['DETAILS','Original Premium Payment']])}<div class="premium-grid">${premiumRows}<div class="premium-row total-due"><span>NET AMOUNT DUE FROM YOU</span><span></span><span>${cur}</span><span>${number(due,decimals)}</span></div></div><p>Please ensure that we are in receipt of cleared funds <b>at least 15 days before the due date(s)</b> in order that we can arrange our settlement in time to comply</p><div class="payment">${paymentRows}</div><p>Please arrange payment to our <b>${name}</b> bank account, as per the details provided below.<br /><b>The Company’s principal bankers are Taipei Fubon Commercial Bank<br />Chung Lun Branch, No. 6, Fu Hsing N. Road, Taipei, Taiwan (R.O.C.).<br />Account details are as follow:</b></p><table class="bank"><tr><th>Currency</th><th>Beneficiary Name (Chinese)</th><th>Beneficiary Name (English)</th><th>Account No.</th><th>Swift Code</th></tr><tr><td>${cur}</td><td>晶華保險經紀人股份有限公司</td><td>TW Insurance Brokers Ltd.</td><td>${account}</td><td>TPBKTWTP</td></tr></table><img class="signature debit-signature" src="${global.RI_PDF_ASSETS.signature}" /><div>TW Insurance Brokers Ltd.<br />E&amp;OE</div></div>`;
    return [page(body,1,1,'debit-page')];
  }
  function style() {
    // Arial and 標楷體 (the fonts the Word templates use) are Microsoft/
    // Office fonts that are very unlikely to be installed on the Linux
    // headless-Chromium host this PDF renders on, so listing them first
    // just means the browser silently falls back through the rest of the
    // stack anyway. Noto Sans / Noto Sans TC are the fonts most commonly
    // preinstalled on headless-Chromium/Docker images specifically for
    // CJK rendering support, so they're listed next to give the PDF a
    // consistent, intentional look instead of an arbitrary system fallback.
    return `<style>*{box-sizing:border-box}body{margin:0;font-family:Arial,"Liberation Sans","Noto Sans TC","Noto Sans CJK TC","Microsoft JhengHei","PingFang TC",sans-serif;color:#111}.page,.page *{font-size:10pt!important}.page{position:relative;width:${A4.width}px;height:${A4.height}px;background:#fff;overflow:hidden;font-size:13.5px;line-height:1.22}.content{position:absolute;left:72px;right:72px;top:48px;bottom:70px;overflow:hidden}.logo{display:block;width:180px;height:auto;margin:0 auto 16px}.logo.small{width:145px;margin-bottom:10px}.header-meta{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:28px;align-items:start;margin:0 8px 12px}.recipient,.contact{position:static;min-width:0;line-height:1.25;overflow-wrap:anywhere}.contact{text-align:right}.doc-title{border:1px solid #333;text-align:center;font-size:17px;font-weight:700;margin:0;padding:2px}.intro{margin:18px 8px}h2{text-align:center;text-decoration:underline;font-size:16px;margin:14px 0 16px}.row{display:flex;gap:18px;margin:0 0 11px}.label{width:155px;flex:0 0 155px;font-weight:700}.value{flex:1;white-space:normal}.continued-title{text-align:center;font-weight:700;font-size:15px;margin:2px 0 16px}.continued{top:55px}.compact .row{margin-bottom:8px;font-size:12.3px}.footer{position:absolute;left:60px;right:60px;bottom:30px;text-align:center;color:#888;font-size:10.5px}.page-no{position:absolute;right:60px;bottom:8px;text-align:right}.amount-table,.loss-table,.bank{width:100%;border-collapse:collapse}.amount-table td,.loss-table td,.loss-table th,.bank td,.bank th{border:1px solid #222;padding:3px 7px}.amount-table .num{text-align:right}.amount-table .total td{border-top:2px solid #111;text-align:center}.amount-table .total .num{text-align:right}.loss-table{text-align:center;margin-top:4px}.security{margin:16px 30px}.security-row{display:grid;grid-template-columns:90px 1fr;gap:20px;margin:3px}.security-total{margin-top:10px}.security-total span:first-child{border-top:1px dashed #444;padding-top:6px}.security-notice{margin-top:170px;text-align:justify}.signature{width:170px;height:auto;margin-top:20px}.clause-page{font-size:11.7px;line-height:1.18}.clause-page h2{font-size:15px;margin:12px}.clause-text p{margin:0 0 8px}.debit{top:45px;font-size:14px}.debit .doc-title{margin-top:0}.debit .row{margin:8px 0}.premium-grid{margin:28px 0 22px}.premium-row{display:grid;grid-template-columns:270px 105px 60px 110px;column-gap:10px}.premium-row span:nth-child(2),.premium-row span:nth-child(4){text-align:right}.total-due{font-weight:700;margin-top:16px}.payment{display:grid;grid-template-columns:1fr 70px 110px;text-align:right;margin:25px 50px}.bank{text-align:center;margin-top:16px;font-size:12px}.bank th{font-weight:700}.debit-signature{margin-top:35px;margin-left:40px}.endorsement .row{margin:9px 0}.endorsement-wording{min-height:260px;border:1px solid #333;padding:18px;margin:18px 0;white-space:normal}.endorsement-wording p{margin:0 0 10px}.endorsement-continuity{font-weight:700;margin-top:20px}.endorsement-signature{margin-top:38px}.page .doc-title{font-size:12pt!important}.page .security-notice p{font-size:9pt!important}.page .clause-text p{font-size:9pt!important}</style>`;
  }
  function waitForImage(img) {
    if (img.complete && img.naturalWidth) return Promise.resolve();
    return new Promise((resolve,reject)=>{
      img.addEventListener('load',resolve,{once:true});
      img.addEventListener('error',()=>reject(new Error('Unable to load PDF image asset')),{once:true});
    });
  }
  function loadImage(src) {
    return new Promise((resolve,reject)=>{
      const img=new Image();
      img.decoding='sync';
      img.onload=()=>resolve(img);
      img.onerror=()=>reject(new Error('Unable to load PDF image asset'));
      img.src=src;
    });
  }
  async function rasterize(markup) {
    // Chromium taints a canvas when an SVG foreignObject contains nested
    // data-URL images. Lay the page out off-screen, rasterize the text/layout
    // without those images, then draw each trusted embedded image separately.
    const host=document.createElement('div');
    host.style.cssText='position:fixed;left:-10000px;top:0;width:'+A4.width+'px;height:'+A4.height+'px;pointer-events:none;opacity:0;';
    host.innerHTML=`${style()}${markup}`;
    document.body.appendChild(host);
    let url='';
    try {
      const pageEl=host.querySelector('.page');
      if (!pageEl) throw new Error('Unable to lay out PDF page');
      const sourceImages=Array.from(pageEl.querySelectorAll('img')).filter(img=>img.getAttribute('src'));
      await Promise.all(sourceImages.map(waitForImage));
      const pageRect=pageEl.getBoundingClientRect();
      const overlays=sourceImages.map(img=>{
        const rect=img.getBoundingClientRect();
        return {src:img.src,x:rect.left-pageRect.left,y:rect.top-pageRect.top,width:rect.width,height:rect.height};
      });
      const cleanPage=pageEl.cloneNode(true);
      cleanPage.querySelectorAll('img').forEach(img=>{img.removeAttribute('src');img.style.visibility='hidden';});
      // DOM outerHTML serializes void elements such as <img> without an XML-closing slash,
      // which makes the SVG blob invalid XML in Chromium. XMLSerializer preserves valid XHTML.
      const serializedPage=new XMLSerializer().serializeToString(cleanPage);
      const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${A4.width}" height="${A4.height}"><foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml">${style()}${serializedPage}</div></foreignObject></svg>`;
      url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml;charset=utf-8'}));
      const base=await loadImage(url);
      const canvas=document.createElement('canvas');
      canvas.width=Math.round(A4.width*RASTER_SCALE);
      canvas.height=Math.round(A4.height*RASTER_SCALE);
      const ctx=canvas.getContext('2d');
      ctx.fillStyle='#fff';
      ctx.fillRect(0,0,canvas.width,canvas.height);
      ctx.drawImage(base,0,0,canvas.width,canvas.height);
      for (const overlay of overlays) {
        const image=await loadImage(overlay.src);
        ctx.drawImage(image,overlay.x*RASTER_SCALE,overlay.y*RASTER_SCALE,overlay.width*RASTER_SCALE,overlay.height*RASTER_SCALE);
      }
      return atob(canvas.toDataURL('image/jpeg',0.93).split(',')[1]);
    } finally {
      if(url) URL.revokeObjectURL(url);
      host.remove();
    }
  }
  function makePdf(images) {
    const objects=[null];
    objects[1]='<< /Type /Catalog /Pages 2 0 R >>';
    const pageNums=[],contentNums=[],imageNums=[];let next=3;
    images.forEach(()=>{pageNums.push(next++);contentNums.push(next++);imageNums.push(next++);});
    objects[2]=`<< /Type /Pages /Kids [${pageNums.map(n=>`${n} 0 R`).join(' ')}] /Count ${images.length} >>`;
    images.forEach((bin,i)=>{
      objects[pageNums[i]]=`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${A4.pdfWidth} ${A4.pdfHeight}] /Resources << /XObject << /Im0 ${imageNums[i]} 0 R >> >> /Contents ${contentNums[i]} 0 R >>`;
      const stream=`q ${A4.pdfWidth} 0 0 ${A4.pdfHeight} 0 0 cm /Im0 Do Q`;
      objects[contentNums[i]]=`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`;
      objects[imageNums[i]]=`<< /Type /XObject /Subtype /Image /Width ${Math.round(A4.width*RASTER_SCALE)} /Height ${Math.round(A4.height*RASTER_SCALE)} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${bin.length} >>\nstream\n${bin}\nendstream`;
    });
    let out='%PDF-1.4\n',offsets=[0];for(let i=1;i<objects.length;i++){offsets[i]=out.length;out+=`${i} 0 obj\n${objects[i]}\nendobj\n`;}
    const xref=out.length;out+=`xref\n0 ${objects.length}\n0000000000 65535 f \n`;for(let i=1;i<objects.length;i++)out+=`${String(offsets[i]).padStart(10,'0')} 00000 n \n`;out+=`trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
    const bytes=new Uint8Array(out.length);for(let i=0;i<out.length;i++)bytes[i]=out.charCodeAt(i)&255;return new Blob([bytes],{type:'application/pdf'});
  }
  async function generate(pages, meta) {
    const response=await fetch('/api/render-document-pdf',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(Object.assign({markup:`${style()}${pages.join('')}`}, meta || {}))
    });
    if(!response.ok){
      let message='Unable to render PDF.';
      try{const data=await response.json();if(data&&data.error)message=data.error;}catch(_error){}
      throw new Error(message);
    }
    return response.blob();
  }
  function download(blob,filename){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);}
  global.RIPdf={
    async cover(c){return generate(coverPages(c));},
    async endorsement(c){return generate(endorsementPages(c));},
    // Bugfix (#19): tag the request so the server can enforce "Debit Note
    // only after Announce assigns a TW Reference" -- see api/render-document-pdf.js.
    async debit(c){return generate(debitPages(c), {kind:'debit', caseUid: (c && c.caseUid) || ''});},
    download,
    coverFilename(c){return `CoverNote_${c.twRef||'DRAFT'}.pdf`;},
    endorsementFilename(c){return `Endorsement_${c.twRef||c.parentTwRef||'DRAFT'}.pdf`;},
    debitFilename(c){return `DebitNote_${c.twRef||'DRAFT'}.pdf`;},
    _qa: { coverPages, endorsementPages, debitPages, style, makePdf, pctActual, pageSize: A4 }
  };
})(window);