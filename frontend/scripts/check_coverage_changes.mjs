import assert from 'node:assert/strict'
import { initialRecall, productRecallDraftIssues, productRecallIssues } from '../src/alpha/productRecall.js'
import { cglRiskDetailsIssues, cglOtherDraftIssues, cglCoveragesText } from '../src/alpha/cglRiskDetails.js'
const risk = initialRecall()
for (const row of risk.losses) Object.assign(row, { amount: 100, currency: 'USD' })
const p = { classOfBusiness: 'Product Recall', reinsuranceStructure: 'QS', currency: 'USD', limitOfLiability: 1000, deductibles: 10, originalExclusions:'None', originalConditions:'None', reinsuredRetention:'None', expressWarranties:'None', conditionsPrecedent:'None', subjectivities:'None', productRecall:risk }
risk.lossesOtherSelected = true
risk.losses.push({ id:'a', name:'Extra costs', fixed:false, selected:true, currency:'EUR', amount:5000 }, { id:'b', name:'Other costs', fixed:false, selected:true, currency:'TWD', amount:200 })
assert.deepEqual(productRecallDraftIssues(p), [])
assert.deepEqual(productRecallIssues(p), [])
risk.losses[5].name = ' extra COSTS '
assert.ok(productRecallDraftIssues(p).some(x => x.field.endsWith('.name')))
risk.losses[5].name = 'Other costs'; risk.losses[5].amount = 1.5
assert.ok(productRecallDraftIssues(p).some(x => x.field.endsWith('.amount')))
risk.lossesOtherSelected = false
assert.deepEqual(productRecallDraftIssues(p), [])
const c = { classOfBusiness:'Commercial General Liability', reinsuranceStructure:'QS', coverages:['Other'], coveragesOtherItems:['First other','Second other'] }
assert.deepEqual(cglRiskDetailsIssues(c), [])
assert.equal(cglCoveragesText(c), 'First other\nSecond other')
const swiss = {...c, reinsurers:[{name:'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'}]}
assert.deepEqual(cglRiskDetailsIssues(swiss), [])
assert.equal(cglCoveragesText(swiss), 'First other\nSecond other')
c.coveragesOtherItems.push('Straße', 'STRASSE')
assert.deepEqual(cglOtherDraftIssues(c), [])
c.coveragesOtherItems.push(' FIRST OTHER ')
assert.ok(cglOtherDraftIssues(c).length)
c.coverages = ['Medical Payment']
assert.deepEqual(cglOtherDraftIssues(c), [])
assert.equal(cglCoveragesText(c), 'Medical Payment')
console.log('Coverage change frontend checks passed')
