// Regression checks for the actual Announce readiness function.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(process.argv[2] || path.join(__dirname, '../src/views/case-workspace.script.js'), 'utf8');
function extract(start, end) {
  const first = source.indexOf(start), last = source.indexOf(end, first);
  assert(first >= 0 && last > first, start);
  return source.slice(first, last);
}
const context = {
  filled: v => v !== null && v !== undefined && (typeof v !== 'string' || v.trim() !== ''),
  requiresManualTwRef: () => false, isAuwReinsurer: () => false,
};
vm.createContext(context);
vm.runInContext('(function(){'+fs.readFileSync(path.join(__dirname,'../src/alpha/construction.js'),'utf8').replace(/export /g,'')+'\nObject.assign(globalThis,{constructionIssues,constructionScope,constructionText,initializeConstruction});})()',context);
vm.runInContext("(function(){" + fs.readFileSync(path.join(__dirname, "../src/alpha/placingRules.js"), "utf8").replace(/export /g, "") + "\nObject.assign(globalThis,{placingRulesEnabled,newCgl,adjustClientIssues,shareClientIssues,placingExtraIssues,businessText});})()", context);
vm.runInContext('(function(){' + fs.readFileSync(path.join(__dirname, '../src/alpha/endorsementRules.js'), 'utf8').replace(/^import .*$/gm, '').replace(/export /g, '') + '\nObject.assign(globalThis,{insuranceIssues});})()', context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/alpha/facilitySelection.js'), 'utf8').replace(/export /g, ''), context);
vm.runInContext('(function(){' + fs.readFileSync(path.join(__dirname, '../src/alpha/dataIntegrity.js'), 'utf8').replace(/export /g, '') + '\nObject.assign(globalThis,{financialIssues,pendingTotals});})()', context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/alpha/propertyOriginal.js'), 'utf8').replace(/^import .*$/gm, '').replace(/export /g, ''), context);
vm.runInContext('(function(){' + fs.readFileSync(path.join(__dirname, '../src/alpha/lib/accounting.js'), 'utf8').replace(/^import .*$/gm, '').replace(/export /g, '') + '\nObject.assign(globalThis,{premiumInputErrors});})()', context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/alpha/swissCgl.js'), 'utf8').replace(/export /g, ''), context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/alpha/cglInformation.js'), 'utf8').replace(/^import .*$/gm, '').replace(/export /g, ''), context);
vm.runInContext('(function(){' + fs.readFileSync(path.join(__dirname, '../src/alpha/cglQs.js'), 'utf8').replace(/^import .*$/gm, '').replace(/export /g, '') + '\nObject.assign(globalThis,{cglQsScope,cglQsIssues,draftFormatIssues});})()', context);
vm.runInContext(extract('  const keyInScope =', '\n  const draftFamily =').replace('const ordinaryDraftScope =','globalThis.ordinaryDraftScope ='),context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/alpha/cglRiskDetails.js'), 'utf8').replace(/^import .*$/gm, '').replace(/export /g, ''), context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/alpha/sumInsured.js'), 'utf8').replace(/export /g, ''), context);
vm.runInContext(extract('  function validSumInsuredAmount(value)', '\n  function validPostcode')
  + extract('  function validPostcode(value', '\n  function validPositiveInteger')
  + extract('  function validLossRecordYears(value, caseData)', '\n  function fieldInvalid'), context);
const base = {
  ownerPersonnelId: 1, reinsuranceStructure: 'QS', ae: 'QA AE', currency: 'USD',
  classOfBusiness: 'QA Class', newOrRenew: 'New', type: 'Property', reinsured: 'QA Cedant',
  originalInsured: 'QA Insured', policyFrom: '2026-01-01', policyTo: '2027-01-01', interest: 'Buildings',
  situations: [{address: '1 QA Road', postcode: '100'}],
  reinsurers: [{name: 'QA Re', sharePct: 100, premium: 1000, riCommPct: 5, taxPct: 0}],
  limitOfLiability: 1000000, deductibles: 'As original', originalConditions: 'As original',
  occupation: 'Office', construction: 'Concrete', sumInsured: [{category: 'Building', amount: 1000000}],
  lossAdvisedDate: '2026-01-01', lossRecordYears: 5, lossRecord: [],
  originalPremium: 1000, paymentTermsDays: 30, riCommPct: 10, taxPct: 0,
};
const row = {date: '2025-01-01', cause: 'Fire', lossPaid: 0};
let count = 0;
function check(name, changes, expected) {
  const actual = Array.from(context.collectPayloadAnnounceIssues({...base, ...changes}));
  assert.deepStrictEqual(actual, expected, name);
  count++;
  console.log('PASS ' + name);
}
check('positive history with no losses is clean', {}, []);
check('zero-year New with no losses is clean', {lossRecordYears: 0}, []);
check('completed row accepts zero paid loss', {lossRecord: [row]}, []);
check('empty date is reported', {lossRecord: [{...row, date: ''}]}, ['Loss 1 Date of Loss']);
check('empty cause is reported', {lossRecord: [{...row, cause: '  '}]}, ['Loss 1 Cause']);
check('missing paid amount is reported', {lossRecord: [{...row, lossPaid: null}]}, ['Loss 1 Loss Amount']);
check('all missing row fields are reported', {lossRecord: [{date: '', cause: '', lossPaid: null}]},
  ['Loss 1 Date of Loss', 'Loss 1 Cause', 'Loss 1 Loss Amount']);
check('every loss row is checked', {lossRecord: [row, {...row, cause: ''}]}, ['Loss 2 Cause']);
check('zero-year history with a row rejects without runtime error', {lossRecordYears: 0, lossRecord: [row]},
  ['Loss Record must be empty when loss history years is 0']);
check('zero-year incomplete row reports both conflicting history and missing fields',
  {lossRecordYears: 0, lossRecord: [{date: '', cause: '', lossPaid: null}]},
  ['Loss Record must be empty when loss history years is 0', 'Loss 1 Date of Loss', 'Loss 1 Cause', 'Loss 1 Loss Amount']);
check('Renew cannot use zero years', {lossRecordYears: 0, newOrRenew: 'Renew'}, ['Loss history years']);
check('renewal linkage prevents zero-year New bypass', {lossRecordYears: 0, renewedFromTwRef: 'QA-ROOT'},
  ['Loss history years']);
console.log(`${count}/${count} Loss Record readiness regression checks passed`);

const cgl = {originalInsuredCn:'QA CN',reinsuredRetention:'As original',reinsurers:[{...base.reinsurers[0],paymentTermsDays:90}],typePrefix: 'Commercial General Liability', type: 'Commercial General Liability Facultative Reinsurance as original', coverages: ['Premises-Operations Liability'], classOfBusiness: 'Commercial General Liability', occupation: '', construction: '', sumInsured: [],
  cglInformation: {policyForm: 'Occurrence Form', territorialLimits: 'USA/Canada Only', insuredBusiness: 'Manufacturing', insuredProducts: 'Products',
    estimatedTurnover: [{region: 'USA/Canada', currency: 'USD', amount: 1000000}], specialAgreementApplies: 'notApplicable'}};
check('CGL replaces removed Property requirements', cgl, []);
check('CGL requires Business', {...cgl, cglInformation: {...cgl.cglInformation, insuredBusiness: ''}}, ['Insured’s Business']);
check('CGL requires Products', {...cgl, cglInformation: {...cgl.cglInformation, insuredProducts: ''}}, ['Insured’s Products']);
check('CGL Claims-Made requires retroactive date and ERP choice', {...cgl, cglInformation: {...cgl.cglInformation, policyForm: 'Claims-Made Form'}}, ['Retroactive Date', 'Extended Reporting Period applicability']);
check('CGL requires selected agreement content', {...cgl, cglInformation: {...cgl.cglInformation, specialAgreementApplies: 'applicable'}}, ['Special Agreement']);
check('CGL requires one coverage', {...cgl, coverages: []}, ['Coverages — select at least one available option']);
check('CGL Other requires wording', {...cgl, coverages: ['Other']}, ['Coverages — Other']);
check('CGL accepts Other alone and optional blank SIR', {...cgl, coverages: ['Other'], coveragesOther: 'Extra liability', selfInsuredRetention: ''}, []);
check('CGL requires permitted Type', {...cgl, typePrefix: 'Property'}, ['Type — select Products Liability or Commercial General Liability']);
check('CGL uses Limit of Indemnity label', {...cgl, limitOfLiability: null}, ['Limit of Indemnity']);
check('CGL XOL requires Underlying Limits', {...cgl, reinsuranceStructure: 'XOL'}, ['Underlying Limits']);
check('CGL XOL accepts Underlying and blank optionals', {...cgl, reinsuranceStructure: 'XOL', underlyingLimits: 'USD500,000', aggregateLimit: null, subLimits: ''}, []);
check('CGL hidden valuation Other does not block readiness', {...cgl, basisOfValuation: 'Other', basisOfValuationOther: '', indemnityPeriod: 'Legacy period', notices: ''}, []);
check('Property valuation Other still requires wording', {basisOfValuation: 'Other', basisOfValuationOther: ''}, ['Basis of Valuation — Other']);
const allianz = 'Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)';
check('Allianz Property combination is ready', {constructionSelections:['A2 Class'],classOfBusiness: 'Property', originalInsuredCn:'QA CN', reinsuredRetention:'As original', typePrefix:'Fire', reinsurers: [{...base.reinsurers[0], name: allianz}]}, []);
check('Allianz outside Property blocks readiness', {classOfBusiness: 'CGL', reinsurers: [{...base.reinsurers[0], name: allianz}]}, ['Reinsurer 1: Allianz Facility is available only for Property.']);
check('ordinary Allianz outside Property is unchanged', {reinsurers: [{...base.reinsurers[0], name: allianz.replace(' (Facility)', '')}]}, []);
check('CGL USD precision blocks formal readiness', {...cgl, originalPremium: 1000.001}, ['100% Premium must have at most two decimal places for USD.']);
check('CGL TWD precision blocks formal readiness', {...cgl, currency: 'TWD', originalPremium: 1000.5}, ['100% Premium must be a whole number for TWD; decimals are not allowed.']);
console.log(`${count}/${count} total readiness checks passed`);

require('./check_draft_autosave.cjs');
assert(context.draftFormatIssues({parentTwRef:'ROOT',originalPremium:-100,reinsurers:[{premium:-80}]}).every(i=>!i.field.endsWith('premium') && i.field!=='originalPremium'), 'Endorsement negative premium is valid raw input');
assert(context.draftFormatIssues({originalPremium:-100,reinsurers:[{premium:-80}]}).filter(i=>i.field.endsWith('premium') || i.field==='originalPremium').length===2, 'Original premiums retain their non-negative constraint');
require('./check_endorsement_rules.cjs');
