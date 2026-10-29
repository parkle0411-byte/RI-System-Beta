// 2026-10-29 批單 Debit Note／Credit Note 的 Word 內容檢查（合成資料）。
// 用法：node scripts/check_endorsement_notes.cjs（需要 node_modules/jszip）
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert')
const JSZip = require('jszip')
const dir = path.join(__dirname, '..', 'public', 'alpha-documents')
const ctx = { window: { JSZip }, JSZip, console }
ctx.globalThis = ctx; ctx.self = ctx.window
vm.createContext(ctx)
for (const f of ['docx-templates.js', 'vm-docx-generator.js']) vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx, { filename: f })
const D = ctx.window.RIDocx || ctx.RIDocx, T = ctx.window.RI_DOCX_TEMPLATES

const base = {
  twRef: 'QA0001-E01', parentTwRef: 'QA0001', endorsementSeq: 1, endoEffectiveDate: '2025-12-16', currency: 'TWD', reinsuranceStructure: 'QS',
  originalInsured: 'Sample Insured', reinsured: 'Sample Cedant', reinsuredAddress: 'Taipei', type: 'Property', policyFrom: '2025-12-10', policyTo: '2026-12-10',
  aeName: 'Sample AE', aeEmail: 'ae@example.invalid', paymentTermsDays: 90, riCommPct: 15, taxPct: 1, originalPremium: 5842,
  reinsurers: [{ name: 'Sample RI', sharePct: 60, premium: 5732, paymentTermsDays: 90 }],
  propertyFinancials: { order: 60, originalPremium: 5842, cededPremium: 3505, commission: 526, tax: 35, netDue: 2944, t1s: [2944] },
}
const refund = { ...base, twRef: 'QA0001-E02', endorsementSeq: 2, originalPremium: -5842, reinsurers: [{ ...base.reinsurers[0], premium: -5732 }],
  propertyFinancials: { order: 60, originalPremium: -5842, cededPremium: -3505, commission: -526, tax: -35, netDue: -2944, t1s: [-2944] } }

async function rows(blob) {
  const zip = await JSZip.loadAsync(blob)
  const xml = await zip.file('word/document.xml').async('string')
  const footer = (await Promise.all(Object.keys(zip.files).filter(n => /^word\/footer\d+\.xml$/.test(n)).map(n => zip.file(n).async('string')))).join('')
  const sizes = [...new Set([...footer.matchAll(/<w:sz w:val="(\d+)"\/>/g)].map(m => m[1]))]
  return { xml, sizes, footer, text: (xml.match(/<w:tr[ >][\s\S]*?<\/w:tr>/g) || []).map(r => r.replace(/<w:br\/>/g, ' / ').replace(/<\/w:p>/g, ' ').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim()).filter(Boolean) }
}
let passed = 0
const check = (name, ok) => { assert.ok(ok, name); passed += 1; console.log('PASS ' + name) }

;(async () => {
  const debit = await rows(await D.generateDebit(base, T, 'nodebuffer'))
  check('Debit: title is DEBIT NOTE only (no Endorsement No. under it)', debit.text.includes('DEBIT NOTE') && !debit.text.some(r => r.includes('NOTE / ')))
  check('Debit: details say additional premium', debit.text.some(r => r === 'DETAILS Additional Premium – Endorsement No. 1'))
  check('Debit: Cedant amounts', ['PREMIUM TWD 5,842', 'ORDER HEREON 60% TWD 3,505', 'Less CEDING COMMISSION 15.00% TWD 526', 'Less TAX 1.00% TWD 35', 'NET AMOUNT DUE FROM YOU TWD 2,944'].every(t => debit.text.includes(t)))
  check('Debit: date = effective date + Cedant days − 15', debit.text.includes('01 March 2026 TWD 2,944'))
  check('Debit: keeps the bank account', debit.text.some(r => r.includes('TPBKTWTP')))
  check('Debit: no placeholder left', !/\{\{[A-Z_]+\}\}/.test(debit.xml))
  check('Debit: footer (company details and page number) is 8 pt', debit.sizes.join() === '16' && debit.footer.includes('TW Insurance Brokers Ltd.') && debit.footer.includes('PAGE'))
  check('Debit filename', D.debitFilename(base) === 'DebitNote_QA0001-E01.docx')

  const credit = await rows(await D.generateCredit(refund, T, 'nodebuffer'))
  check('Credit: title is CREDIT NOTE only (no Endorsement No. under it)', credit.text.includes('CREDIT NOTE') && !credit.text.some(r => r.includes('NOTE / ')))
  check('Credit: details say return premium', credit.text.some(r => r === 'DETAILS Return Premium – Endorsement No. 2'))
  check('Credit: amounts shown as positive numbers', ['PREMIUM TWD 5,842', 'ORDER HEREON 60% TWD 3,505', 'Less CEDING COMMISSION 15.00% TWD 526', 'Less TAX 1.00% TWD 35', 'NET AMOUNT DUE TO YOU TWD 2,944'].every(t => credit.text.includes(t)) && !credit.xml.includes('-5,842') && !credit.xml.includes('-2,944'))
  check('Credit: wording from the Credit Note template', credit.text.includes('We shall arrange the payment of premium on the following date(s):') && !credit.xml.includes('Please ensure'))
  check('Credit: date = effective date + Cedant days', credit.text.includes('16 March 2026 TWD 2,944'))
  check('Credit: no bank account and no US Dollar sentence', !credit.xml.includes('TPBKTWTP') && !credit.xml.includes('Please arrange payment') && !credit.xml.includes('United States Dollar'))
  check('Credit: keeps signature and E&OE', credit.text.includes('TW Insurance Brokers Ltd.') && credit.xml.includes('E&amp;OE'))
  check('Credit: no placeholder left', !/\{\{[A-Z_]+\}\}/.test(credit.xml))
  check('Credit: footer (company details and page number) is 8 pt', credit.sizes.join() === '16' && credit.footer.includes('Taiwan.') && credit.footer.includes('PAGE'))
  check('Credit filename', D.creditFilename(refund) === 'CreditNote_QA0001-E02.docx')
  await assert.rejects(D.generateCredit({ ...refund, currency: 'USD' }, T, 'nodebuffer'), /only for TWD/)
  check('Credit: USD is refused', true)
  await assert.rejects(D.generateCredit({ ...refund, parentTwRef: '' }, T, 'nodebuffer'), /only for endorsements/)
  check('Credit: original cases are refused', true)

  const usd = await rows(await D.generateDebit({ ...base, currency: 'USD' }, T, 'nodebuffer'))
  check('USD Debit: endorsement title and details', usd.text.includes('DEBIT NOTE') && usd.text.some(r => r === 'DETAILS Additional Premium – Endorsement No. 1') && usd.text.includes('NET AMOUNT DUE FROM YOU USD 2,944.00'))

  // 原單的 Debit Note 不受影響
  const original = { ...base, parentTwRef: '', twRef: 'QA0001', endorsementSeq: undefined, endoEffectiveDate: undefined }
  const plain = await rows(await D.generateDebit(original, T, 'nodebuffer'))
  check('Original Debit: unchanged title and details', plain.text.includes('DEBIT NOTE') && plain.text.some(r => r === 'DETAILS Original Premium Payment'))
  check('Original Debit: footer stays 10 pt', plain.sizes.join() === '20')
  check('Original Debit: date still from policy start', plain.text.includes('23 February 2026 TWD 2,944'))
  console.log(`\n${passed}/${passed} passed`)
})().catch(e => { console.error(e); process.exit(1) })
