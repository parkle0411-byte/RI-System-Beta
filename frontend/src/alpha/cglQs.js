import { isStandardCgl } from './cglInformation'

export const cglQsScope = p => isStandardCgl(p) && ['QS', 'FACULTATIVE'].includes(String(p?.reinsuranceStructure || '').toUpperCase())
const filled = v => v !== null && v !== undefined && String(v).trim() !== ''
const n = v => filled(v) && Number.isFinite(Number(v)) ? Number(v) : null
const days = v => n(v) !== null && Number.isInteger(n(v)) && n(v) >= 15

export function cglQsIssues(p) {
  if (!cglQsScope(p) || p.parentTwRef) return []
  const issues = [], add = (field, label) => issues.push({ field, label })
  for (const [key,label] of [['originalInsuredCn','Original Insured (CN)'],['reinsuredRetention','Reinsured’s Retention'],['riCommPct','Cedant Commission'],['taxPct','Cedant Tax'],['paymentTermsDays','Cedant Collection Days']]) {
    if (!filled(p[key])) add(key,label)
  }
  if (!['TWD','USD'].includes(p.currency)) add('currency','CGL QS Currency must be TWD or USD')
  if (p.policyFrom && p.policyTo && p.policyTo <= p.policyFrom) add('policyTo','Expiration date must be later than Effective date')
  if (filled(p.limitOfLiability) && (n(p.limitOfLiability) === null || n(p.limitOfLiability) <= 0)) add('limitOfLiability','Limit of Indemnity must be greater than 0')
  const rows = p.reinsurers || []
  if (rows.reduce((s,r) => s + (n(r.sharePct) || 0),0) > 100) add('reinsurers','Total Order Hereon must not exceed 100%')
  rows.forEach((r,i) => { if (!days(r.paymentTermsDays)) add(`reinsurers.${i}.paymentTermsDays`,`Reinsurer ${i+1} Payment Terms Days must be an integer of at least 15`) })
  if (!p.parentTwRef) {
    if (filled(p.originalPremium) && (n(p.originalPremium) === null || n(p.originalPremium) <= 0)) add('originalPremium','100% Premium must be greater than 0')
    rows.forEach((r,i) => { if (filled(r.premium) && (n(r.premium) === null || n(r.premium) <= 0)) add(`reinsurers.${i}.premium`,`Reinsurer ${i+1} Premium must be greater than 0`) })
  }
  ;(p.lossRecord || []).forEach((r,i) => { if (filled(r.lossPaid) && (n(r.lossPaid) === null || n(r.lossPaid) <= 0)) add(`lossRecord.${i}.lossPaid`,`Loss ${i+1} Loss Amount must be greater than 0`) })
  if (p.installmentEnabled) (p.performanceInstallments || []).forEach((r,i) => {
    if (n(r.premium) === null || n(r.premium) <= 0) add(`performanceInstallments.${i}.premium`,`Installment ${i+1} Premium must be greater than 0`)
    if (!days(r.paymentTermsDays)) add(`performanceInstallments.${i}.paymentTermsDays`,`Installment ${i+1} Cedant Collection Days must be an integer of at least 15`)
    rows.forEach((_,j) => { if (!days(r.reinsurerPaymentTerms?.[`r${j+1}`])) add(`performanceInstallments.${i}.reinsurerPaymentTerms.r${j+1}`,`Installment ${i+1} Reinsurer ${j+1} Payment Terms Days must be an integer of at least 15`) })
  })
  if (p.splitEnabled && ![[40,60],[70,30]].some(pair => pair.every((v,i) => n(p.splitParties?.[i]?.pct) === v))) add('splitParties','Reinsurance Staff / Other Staff split must be 40% / 60% or 70% / 30%')
  return issues
}

export function draftFormatIssues(p) {
  const issues = [], add = (field,label) => issues.push({field,label})
  const date = v => { const d = /^\d{4}-\d{2}-\d{2}$/.test(v || '') ? new Date(v + 'T00:00:00Z') : null; return d && !Number.isNaN(d.getTime()) && d.getUTCFullYear() >= 100 && d.toISOString().slice(0,10) === v }
  for (const [key,label] of [['policyFrom','Effective date'],['policyTo','Expiration date'],['lossAdvisedDate','Loss record advised date']]) if (filled(p[key]) && !date(p[key])) add(key,label + ' must use YYYY-MM-DD')
  const numeric = (field,value,label,min=0,max=Infinity,integer=false) => {
    if (filled(value) && (n(value) === null || n(value) < min || n(value) > max || integer && !Number.isInteger(n(value)))) add(field,label + ' is invalid')
  }
  for (const [k,l] of [['originalPremium','100% Premium'],['limitOfLiability','Limit'],['aggregateLimit','Aggregate Limit']]) {
    if (k === 'aggregateLimit' && cglQsScope(p)) continue
    numeric(k,p[k],l,k === 'originalPremium' && p.parentTwRef ? -Infinity : 0)
  }
  for (const key of ['riCommPct','taxPct']) numeric(key,p[key],key,0,100)
  numeric('paymentTermsDays',p.paymentTermsDays,'Cedant Collection Days',15,Infinity,true)
  numeric('lossRecordYears',p.lossRecordYears,'Loss history years',0,Infinity,true)
  ;(p.reinsurers || []).forEach((r,i) => {
    for (const k of ['sharePct','riCommPct','taxPct']) numeric(`reinsurers.${i}.${k}`,r[k],`Reinsurer ${i+1} ${k}`,0,100)
    numeric(`reinsurers.${i}.premium`,r.premium,`Reinsurer ${i+1} Premium`,p.parentTwRef ? -Infinity : 0)
    numeric(`reinsurers.${i}.paymentTermsDays`,r.paymentTermsDays,`Reinsurer ${i+1} Payment Terms Days`,15,Infinity,true)
  })
  ;(p.lossRecord || []).forEach((r,i) => {
    if (filled(r.date) && !date(r.date)) add(`lossRecord.${i}.date`,`Loss ${i+1} Date of Loss is invalid`)
    numeric(`lossRecord.${i}.lossPaid`,r.lossPaid,`Loss ${i+1} Loss Amount`)
  })
  ;(p.performanceInstallments || []).forEach((r,i) => {
    if (filled(r.paymentBaseDate) && !date(r.paymentBaseDate)) add(`performanceInstallments.${i}.paymentBaseDate`,`Installment ${i+1} Payment Base Date is invalid`)
    if (filled(r.performanceMonth) && !/^\d{4}-(0[1-9]|1[0-2])$/.test(r.performanceMonth)) add(`performanceInstallments.${i}.performanceMonth`,`Installment ${i+1} Performance Month is invalid`)
    numeric(`performanceInstallments.${i}.premium`,r.premium,`Installment ${i+1} Premium`)
    numeric(`performanceInstallments.${i}.paymentTermsDays`,r.paymentTermsDays,`Installment ${i+1} Cedant Collection Days`,15,Infinity,true)
    for (const [key,v] of Object.entries(r.reinsurerPaymentTerms || {})) numeric(`performanceInstallments.${i}.reinsurerPaymentTerms.${key}`,v,`Installment ${i+1} Reinsurer Payment Terms Days`,15,Infinity,true)
  })
  return issues
}
