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
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/alpha/cglInformation.js'), 'utf8').replace(/export /g, ''), context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/alpha/sumInsured.js'), 'utf8').replace(/export /g, ''), context);
vm.runInContext(extract('  function validSumInsuredAmount(value)', '\n  function validPostcode')
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
check('missing paid amount is reported', {lossRecord: [{...row, lossPaid: null}]}, ['Loss 1 Loss Paid']);
check('all missing row fields are reported', {lossRecord: [{date: '', cause: '', lossPaid: null}]},
  ['Loss 1 Date of Loss', 'Loss 1 Cause', 'Loss 1 Loss Paid']);
check('every loss row is checked', {lossRecord: [row, {...row, cause: ''}]}, ['Loss 2 Cause']);
check('zero-year history with a row rejects without runtime error', {lossRecordYears: 0, lossRecord: [row]},
  ['Loss Record must be empty when loss history years is 0']);
check('zero-year incomplete row reports both conflicting history and missing fields',
  {lossRecordYears: 0, lossRecord: [{date: '', cause: '', lossPaid: null}]},
  ['Loss Record must be empty when loss history years is 0', 'Loss 1 Date of Loss', 'Loss 1 Cause', 'Loss 1 Loss Paid']);
check('Renew cannot use zero years', {lossRecordYears: 0, newOrRenew: 'Renew'}, ['Loss history years']);
check('renewal linkage prevents zero-year New bypass', {lossRecordYears: 0, renewedFromTwRef: 'QA-ROOT'},
  ['Loss history years']);
console.log(`${count}/${count} Loss Record readiness regression checks passed`);

const cgl = {classOfBusiness: 'Commercial General Liability', occupation: '', construction: '', sumInsured: [],
  cglInformation: {policyForm: 'Occurrence Form', territorialLimits: 'USA/Canada Only', insuredBusiness: 'Manufacturing', insuredProducts: 'Products',
    estimatedTurnover: [{region: 'USA/Canada', currency: 'USD', amount: 1000000}], specialAgreementApplies: 'notApplicable'}};
check('CGL replaces removed Property requirements', cgl, []);
check('CGL requires Business', {...cgl, cglInformation: {...cgl.cglInformation, insuredBusiness: ''}}, ['Insured’s Business']);
check('CGL requires Products', {...cgl, cglInformation: {...cgl.cglInformation, insuredProducts: ''}}, ['Insured’s Products']);
check('CGL Claims-Made requires retroactive date and ERP choice', {...cgl, cglInformation: {...cgl.cglInformation, policyForm: 'Claims-Made Form'}}, ['Retroactive Date', 'Extended Reporting Period applicability']);
check('CGL requires selected agreement content', {...cgl, cglInformation: {...cgl.cglInformation, specialAgreementApplies: 'applicable'}}, ['Special Agreement']);
console.log(`${count}/${count} total readiness checks passed`);
