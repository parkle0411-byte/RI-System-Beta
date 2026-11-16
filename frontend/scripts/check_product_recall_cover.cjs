// Exercise the generated DOCX, not just the intermediate formatting helpers.
const fs = require('fs'), vm = require('vm'), assert = require('assert'), JSZip = require('jszip')
const path = require('path')
const assets = path.join(__dirname, '../public/alpha-documents')
const sandbox = {window: {}, self: {JSZip}, Buffer, Uint8Array, console, Intl, Date, TextEncoder, TextDecoder}
vm.runInNewContext(fs.readFileSync(path.join(assets, 'docx-templates.js'), 'utf8'), sandbox)
vm.runInNewContext(fs.readFileSync(path.join(assets, 'vm-docx-generator.js'), 'utf8'), sandbox)
const generator = sandbox.self.RIDocx
const risk = { events: [{id:'event-2',name:'Malicious Product Tampering', selected:true}, {id:'event-1',name:'Defect', selected:true}, {name:'Hidden event', selected:false}],
  losses: [{id:'loss-2',name:'Third Party Recall Costs', selected:true, amount:500}, {id:'loss-1',name:'First Party Recall Costs', selected:true, amount:400}],
  additionalSublimits: [{name:'Custom Costs', amount:250}], choiceOfLaw:'Test jurisdiction' }
const c = {classOfBusiness:'Product Recall', reinsuranceStructure:'QS', currency:'USD',
  placingRulesVersion:'placing-qs-20261028-v1', coReinsuranceWarranty:'Test co-reinsurance warranty',
  productRecall:risk, twRef:'TWPR2601001', type:'Product Recall Facultative Reinsurance',
  interest:'Reinsurance of the Reinsured’s liability under the original policy.', limitOfLiability:1000,
  deductibles:'', selfInsuredRetention:'Retention wording', originalExclusions:'Exclusions', originalConditions:'Conditions',
  paymentTermsDays:90, lossRecordYears:0, lossAdvisedDate:'2026-01-01', newOrRenew:'New', lossRecord:[], situations:[],
  reinsurers:[], cglInformationRows:[{label:'Policy Form', value:'Occurrence Form'}], cglInformation:{specialAgreementApplies:'notApplicable'} }
;(async () => {
  const result = await generator.generateCover(c, sandbox.window.RI_DOCX_TEMPLATES, 'nodebuffer')
  const zip = await JSZip.loadAsync(result), xml = await zip.file('word/document.xml').async('string')
  const content = [...xml.matchAll(/<w:t(?:\s[^>]*)?>(.*?)<\/w:t>/g)].map(x => x[1]).join(' ')
  for (const value of ['COVERED EVENTS','Defect','COVERED LOSS','Recall Costs','LIMIT OF INDEMNITY','in the aggregate',
    'Custom Costs','Retention wording','exclusive jurisdiction of the Courts of the Republic of China, Taiwan','LSW3001 Premium Payment Clause',
    'No previous recalls or product withdrawals since start selling.', 'As advised to TWIB as at', 'Test co-reinsurance warranty']) assert(content.includes(value), value)
  assert.strictEqual(xml.split('All other terms and conditions are as per the original policy wordings.').length - 1, 2, 'both original-policy sections have the agreed tail')
  assert(!content.includes('Hidden event'))
  assert(!content.includes('Test jurisdiction'))
  assert(content.indexOf('Defect') < content.indexOf('Malicious Product Tampering'))
  assert(content.indexOf('First Party Recall Costs') < content.indexOf('Third Party Recall Costs'))
  assert(content.toLowerCase().includes('liability several not joint'), 'LMA3333 full clause')
  assert(content.toLowerCase().includes('hereby recognized as the intermediary'), 'Intermediary full clause')
  assert(content.indexOf('COVERED EVENTS') < content.indexOf('COVERED LOSS'))
  assert(content.indexOf('COVERED LOSS') < content.indexOf('LIMIT OF INDEMNITY'))
  assert(!content.includes('DEDUCTIBLES'))
  assert(!content.includes('PRINCIPAL ADDRESS'))
  const withDeductible = await generator.generateCover({...c, deductibles:100, situations:[{address:'1 Test Road'}]}, sandbox.window.RI_DOCX_TEMPLATES, 'nodebuffer')
  const secondXml = await (await JSZip.loadAsync(withDeductible)).file('word/document.xml').async('string')
  assert(secondXml.includes('each and every Insured Event'), 'Deductibles wording')
  assert(secondXml.includes('1 Test Road'), 'provided principal address')
  console.log('PASS Product Recall Cover Note generated DOCX fields and ordering')
})().catch(error => {console.error(error); process.exitCode = 1})
