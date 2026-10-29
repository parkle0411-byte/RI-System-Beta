// Confirmed Property / QS / PD Original rules, 2026-10-22.
import { financialIssues, pendingTotals } from './dataIntegrity.js'
const objectRows=value=>(Array.isArray(value)?value:[]).filter(row=>row!==null && typeof row==='object' && !Array.isArray(row))
export const propertyScope = p => p?.reinsuranceStructure === 'QS' && !p?.parentTwRef && (p?.classCode === 'PD' || p?.classOfBusiness === 'Property')
const accountingFacilities=new Set(["Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)", "Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)", "Great American Insurance Company, Singapore Branch (Facility)", "QBE Hongkong & Shanghai Insurance Limited (Facility)", "Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)"].map(n=>n.toLowerCase()))
const accountingName=n=>String(n||'').trim().replace(/\s+/g,' ').toLowerCase()
export const fixedCedant=p=>objectRows(p?.reinsurers).some(r=>accountingFacilities.has(accountingName(r.name)))
export const legacyMath=p=>Boolean(p?.accountingLegacyMath || p?.premiumRounding==='legacy-cents' || p?.propertyOriginalRules==='historical')
export const propertyEnabled=p=>!p?._legacyCalculation && objectRows(p?.reinsurers).some(r=>r.name) && objectRows(p?.reinsurers).filter(r=>r.name).every(r=>accountingFacilities.has(accountingName(r.name)) || !/facility|\bpws\b/i.test(r.name))

export const perReinsurer=p=>p?.premiumLedgerLayout==='per-reinsurer-v1' || (!p?.premiumLedgerLayout && !legacyMath(p) && !objectRows(p?.transactions).some(t=>t.source!=='claim'&&!t.reversed&&!t.isReversalEntry))

export const propertyPostcode = value => /^(?=.*[A-Za-z0-9])[A-Za-z0-9 -]+$/.test(String(value ?? '').trim())
const n = v => Number(String(v ?? '').replace(/,/g, '')) || 0
const filled = v => v !== null && v !== undefined && String(v).trim() !== ''
// Exact decimal ratios: binary floating point must never decide a half-cent.
const gcd = (a,b) => b ? gcd(b,a%b) : (a<0n?-a:a)
const ratio = (a,b=1n) => { const g=gcd(a,b)||1n;return [a/g,b/g] }
function decimal(value) {
  if (Array.isArray(value)) return value.length===2 && value.every(v=>typeof v==='bigint') ? value : [0n,1n]
  const match=String(value ?? 0).replace(/,/g,'').trim().match(/^([+-]?)(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i)
  if (!match || !(match[2]||match[3])) return [0n,1n]
  const exponent=Number(match[4]||0)-(match[3]||'').length
  if (Math.abs(exponent)>100) return [0n,1n]
  const digits=BigInt((match[2]||'0')+(match[3]||''))*(match[1]==='-'?-1n:1n)
  return exponent>=0 ? [digits*10n**BigInt(exponent),1n] : ratio(digits,10n**BigInt(-exponent))
}
const plus=(a,b) => {a=decimal(a);b=decimal(b);return ratio(a[0]*b[1]+b[0]*a[1],a[1]*b[1])}
const times=(a,b) => {a=decimal(a);b=decimal(b);return ratio(a[0]*b[0],a[1]*b[1])}
const divide=(a,b) => {a=decimal(a);b=decimal(b);return b[0] ? ratio(a[0]*b[1],a[1]*b[0]) : [0n,1n]}
function rounded(value) {
  let [a,b]=decimal(value);if(b<0n){a=-a;b=-b}
  const sign=a<0n?-1n:1n; a=a<0n?-a:a
  return sign*((a*2n+b)/(b*2n))
}
const scaleOf=p => p?.currency==='TWD' && p?.premiumRounding!=='legacy-cents'?1n:100n
const percentUnits=(units,pct) => rounded(divide(times([units,1n],pct),100))
export function propertyMoney(value,p) {return Number(rounded(times(value,[scaleOf(p),1n])))/Number(scaleOf(p))}
export function propertyAllocate(total,weights,p) {
  const ww=weights.map(w=>n(w)>0?decimal(w):decimal(0)),sum=ww.reduce(plus,decimal(0)),scale=scaleOf(p)
  if(!sum[0])return ww.map(()=>0)
  const units=rounded(times(total,[scale,1n])),values=ww.map(w=>rounded(divide(times([units,1n],w),sum)))
  let tail=units-values.reduce((a,b)=>a+b,0n)
  const order=ww.map((w,i)=>i).filter(i=>ww[i][0]>0n).sort((a,b)=>n(weights[b])-n(weights[a])||a-b)
  for(const i of order){
    if(!tail)break
    const delta=units>=0n&&tail<0n&&tail < -values[i] ? -values[i] : tail
    values[i]+=delta;tail-=delta
  }
  return values.map(v=>Number(v)/Number(scale))
}
export function propertyPeriodAllocate(total,weights,p) {
  if(!weights.length)return []
  let ww=weights.map(w=>n(w)>0?decimal(w):decimal(0)),sum=ww.reduce(plus,decimal(0))
  if(!sum[0]){ww=ww.map(()=>decimal(1));sum=decimal(ww.length)}
  const scale=scaleOf(p),units=rounded(times(total,[scale,1n]))
  const values=ww.map(w=>rounded(divide(times([units,1n],w),sum)))
  values[0]+=units-values.reduce((a,b)=>a+b,0n)
  if(units>0n && values[0]<0n){
    let tail=-values[0];values[0]=0n
    for(let i=1;i<values.length && tail>0n;i++){const delta=values[i]<tail?values[i]:tail;values[i]-=delta;tail-=delta}
  }
  return values.map(v=>Number(v)/Number(scale))
}
function legacyLegs(p,r) {
  const rnd=v=>p.premiumRounding==='legacy-cents'?Math.round((Number(v)+Number.EPSILON)*100)/100:(v<0?-1:1)*Math.round((Math.abs(v)+Number.EPSILON)*(p.currency==='TWD'?1:100))/(p.currency==='TWD'?1:100)
  const src=v=>['TWD','USD'].includes(p.currency)&&p.premiumRounding!=='legacy-cents'?rnd(n(v)):n(v)
  const cp=rnd(src(p.originalPremium)*n(r.sharePct)/100),ri=rnd(cp*n(p.riCommPct)/100),tax=rnd(cp*n(p.taxPct)/100)
  const rp=rnd(src(r.premium)*n(r.sharePct)/100),rd=rnd(rp*n(r.riCommPct)/100),rt=rnd(rp*n(r.taxPct)/100)
  const t1=rnd(cp-ri-tax),t2=rnd(rp-rd-rt),t3=rnd(t1-t2)
  return {cp,ri,tax,leg1:t1,reinsurerCp:rp,reinsurerRi:rd,reinsurerTax:rt,leg2:t2,leg3:t3,brokerage:t3}
}
export function propertyTotals(p) {
  if (financialIssues(p).length) return {...pendingTotals(),order:null,t2s:[],components:[]}
  if(legacyMath(p)) {
    const ris=p.reinsurers||[],legs=ris.map(r=>legacyLegs(p,r)),fields={cedantPremium:'cp',cedantCommission:'ri',cedantTax:'tax',leg1:'leg1',reinsurerPremium:'reinsurerCp',reinsurerDeductions:'reinsurerRi',reinsurerTax:'reinsurerTax',leg2:'leg2',leg3:'leg3',brokerage:'brokerage'}
    return {...Object.fromEntries(Object.entries(fields).map(([k,f])=>[k,propertyMoney(legs.reduce((s,r)=>s+r[f],0),p)])),order:ris.reduce((s,r)=>s+n(r.sharePct),0),t2s:legs.map(r=>r.leg2),components:legs.map(r=>({premium:r.reinsurerCp,deduction:r.reinsurerRi,tax:r.reinsurerTax,t2:r.leg2}))}
  }
  const scale=scaleOf(p),amount=v=>Number(v)/Number(scale),ris=p?.reinsurers||[]
  const source=v=>rounded(times(v,[scale,1n]))
  const order=ris.reduce((s,r)=>plus(s,r.sharePct),decimal(0))
  const cp=percentUnits(source(p.originalPremium),order)
  const commission=percentUnits(cp,p.riCommPct),tax=percentUnits(cp,p.taxPct),t1=cp-commission-tax
  const components=ris.map(r=>{
    const premium=percentUnits(source(r.premium),r.sharePct),deduction=percentUnits(premium,r.riCommPct),rt=percentUnits(premium,r.taxPct)
    return {premium,deduction,tax:rt,t2:premium-deduction-rt}
  })
  const sum=key=>components.reduce((s,r)=>s+r[key],0n),t2=sum('t2'),t3=t1-t2
  return {order:Number(order[0])/Number(order[1]),cedantPremium:amount(cp),cedantCommission:amount(commission),cedantTax:amount(tax),leg1:amount(t1),
    reinsurerPremium:amount(sum('premium')),reinsurerDeductions:amount(sum('deduction')),reinsurerTax:amount(sum('tax')),leg2:amount(t2),leg3:amount(t3),brokerage:amount(t3),
    t2s:components.map(r=>amount(r.t2)),components:components.map(r=>Object.fromEntries(Object.entries(r).map(([k,v])=>[k,amount(v)])))}
}
export function propertyLegs(p,r) {
  if(legacyMath(p))return legacyLegs(p,r)
  const rows=p.reinsurers||[],index=rows.indexOf(r)
  if(index<0)return null
  const full=propertyTotals(p),single=propertyTotals({...p,reinsurers:[r]}),ri=full.components[index]
  const leg1=propertyAllocate(full.leg1,rows.map(row=>row.sharePct),p)[index],leg3=propertyMoney(plus(leg1,-ri.t2),p)
  return {cp:single.cedantPremium,ri:single.cedantCommission,tax:single.cedantTax,leg1,
    reinsurerCp:ri.premium,reinsurerRi:ri.deduction,reinsurerTax:ri.tax,leg2:ri.t2,leg3,brokerage:leg3}
}
export function propertyIssues(p) {
  if (!propertyScope(p)) return []
  const issues=[], add=(field,label) => issues.push({field,label})
  for (const [k,label] of [['originalInsuredCn','Original Insured (CN)'],['reinsuredRetention',"Reinsured's Retention"],['riCommPct','Cedant Commission'],['taxPct','Cedant Tax'],['paymentTermsDays','Cedant Payment Terms (Days)']]) if (!filled(p[k])) add(k,label)
  if (p.policyFrom && p.policyTo && p.policyTo <= p.policyFrom) add('policyTo','Expiration date must be later than Effective date')
  if ((p.reinsurers || []).reduce((s,r) => s+n(r.sharePct),0) > 100) add('reinsurers','Total Order Hereon must not exceed 100%')
  if (!filled(p.typePrefix)) add('type','Type')
  if (n(p.originalPremium) <= 0) add('originalPremium','100% Premium must be greater than 0')
  ;(p.reinsurers || []).forEach((r,i) => {
    if (n(r.premium)<=0) add(`reinsurers.${i}.premium`,`Reinsurer ${i+1} Premium must be greater than 0`)
    if (!/facility|\bpws\b/i.test(r.name || '') && !filled(r.paymentTermsDays)) add(`reinsurers.${i}.paymentTermsDays`,`Reinsurer ${i+1} Payment Terms (Days)`)
  })
  if (filled(p.aggregateLimit) && n(p.aggregateLimit)<=0) add('aggregateLimit','Aggregate Limit must be greater than 0')
  if (p.splitEnabled && ![[40,60],[70,30]].some(pair => pair.every((v,i) => n(p.splitParties?.[i]?.pct)===v))) add('splitParties','Reinsurance Staff / Other Staff split must be 40% / 60% or 70% / 30%')
  if (p.installmentEnabled) (p.performanceInstallments || []).forEach((r,i) => {
    if (n(r.premium)<=0) add(`performanceInstallments.${i}.premium`,`Installment ${i+1} Premium must be greater than 0`)
    if (!/facility|\bpws\b/i.test(r.name || '') && !filled(r.paymentTermsDays)) add(`performanceInstallments.${i}.paymentTermsDays`,`Installment ${i+1} Cedant Payment Terms (Days)`)
    ;(p.reinsurers || []).forEach((ri,j) => {if (!/facility|\bpws\b/i.test(ri.name || '') && !filled(r.reinsurerPaymentTerms?.[`r${j+1}`])) add(`performanceInstallments.${i}.reinsurerPaymentTerms.r${j+1}`,`Installment ${i+1} Reinsurer ${j+1} Payment Terms (Days)`)})
  })
  return issues
}
