export const overseaEnabled = p => String(p?.reinsuranceStructure || '').trim().toUpperCase() === 'OVERSEA'
export function overseaDates(p, transaction = null) {
  const periods=p?.performanceInstallments || []
  const period=transaction?.installmentId ? periods.find(r=>r.id===transaction.installmentId) : p?.installmentEnabled ? periods[0] : null
  const actual = period ? period.paymentBaseDate || '' : p?.receiptPaymentDate || ''
  const date = new Date(actual+'T00:00:00Z')
  if (!actual || !Number.isFinite(date.getTime())) return {baseDate:'',dueDate:'',contractDueDate:'',actualPaymentDate:'',accountingDate:'',paymentRule:'oversea_actual_minus_10'}
  date.setUTCDate(date.getUTCDate()-10)
  const accounting = date.toISOString().slice(0,10)
  return {baseDate:actual,dueDate:accounting,contractDueDate:actual,actualPaymentDate:actual,accountingDate:accounting,paymentRule:'oversea_actual_minus_10'}
}
export const overseaClasses = ['Fine Art', 'Terrorism']
export function overseaIssues(p, ready = false) {
  if (!overseaEnabled(p)) return []
  const result = [], add = (field,label) => result.push({field,label})
  if (p.classOfBusiness && !overseaClasses.includes(p.classOfBusiness) || ready && !p.classOfBusiness) add('classOfBusiness','Oversea Business supports Fine Art and Terrorism only.')
  const moneyFields = [['originalPremium',p.originalPremium],...(p.reinsurers || []).map((r,i)=>[`reinsurers.${i}.brokerageAmount`,r.brokerageAmount])]
  for (const [field,value] of moneyFields) if (value != null && String(value).trim() !== '' && Number.isFinite(Number(value))) {
    const scale = p.currency === 'TWD' ? 1 : 100
    if (Math.abs(Number(value)*scale - Math.round(Number(value)*scale)) > 1e-7) add(field,(field==='originalPremium'?'100% Premium':'Brokerage')+(scale===1?' must be a whole number for TWD.':' must have at most two decimal places.'))
  }
  const periods=p.performanceInstallments || []
  if (p.installmentEnabled && new Set(periods.map(r=>r.id)).size!==periods.length) add('performanceInstallments','Installment IDs must be unique.')
  if (!ready) return result
  if (p.installmentEnabled) {
    if (periods.length<2) add('performanceInstallments','Use at least two installments.')
    for (const [i,row] of periods.entries()) {
      if (!(Number(row.ratio)>0 && Number(row.ratio)<=100)) add(`performanceInstallments.${i}.ratio`,'Enter an installment ratio greater than 0 and at most 100%.')
      const date=String(row.paymentBaseDate || ''), parsed=new Date(date+'T00:00:00Z')
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0,10)!==date) add(`performanceInstallments.${i}.paymentBaseDate`,'Each installment requires an actual Receipt / Payment Date.')
    }
    if (Math.abs(periods.reduce((sum,r)=>sum+Number(r.ratio || 0),0)-100)>0.000001) add('performanceInstallments','Installment ratios must total 100%.')
  }
  if (p.parentTwRef) for (const [key,label] of [['endoEffectiveDate','Endorsement Effective Date'],['endoText','Endorsement Description']]) if (!String(p[key] || '').trim()) add(key,label+' is required.')
  for (const [key,label] of [['originalInsured','Insured (EN)'],['originalInsuredCn','Insured (CN)'],['policyFrom','Effective Date'],['policyTo','Expiration Date'],['ae','Account Executive'],['reinsured','Cedant'],['currency','Currency'],['originalPremium','100% Premium'],['receiptPaymentDate','Receipt / Payment Date']]) {
    if (key==='receiptPaymentDate' && p.installmentEnabled) continue
    if (p[key] == null || String(p[key]).trim() === '') add(key,label+' is required.')
  }
  if (!p.installmentEnabled && p.receiptPaymentDate && (!/^\d{4}-\d{2}-\d{2}$/.test(p.receiptPaymentDate) || !Number.isFinite(Date.parse(p.receiptPaymentDate+'T00:00:00Z')) || new Date(p.receiptPaymentDate+'T00:00:00Z').toISOString().slice(0,10) !== p.receiptPaymentDate)) add('receiptPaymentDate','Receipt / Payment Date must use YYYY-MM-DD.')
  if ((p.reinsurers || []).length !== 1) add('reinsurers','Select one Reinsurance Broker for Oversea Business.')
  ;(p.reinsurers || []).forEach((r,i) => {
    for (const [key,label] of [['name','Reinsurance Broker'],['sharePct','Share (%)'],['brokerageAmount','Brokerage']]) if (r[key] == null || String(r[key]).trim() === '') add(`reinsurers.${i}.${key}`,label+' is required.')
    if (r.sharePct != null && !(Number(r.sharePct)>0 && Number(r.sharePct)<=100)) add(`reinsurers.${i}.sharePct`,'Share must be greater than 0 and at most 100%.')
  })
  return result
}

export function overseaPeriods(p) {
  const round=value=>{
    if(p.premiumRounding==='legacy-cents')return Math.round((Number(value)+Number.EPSILON)*100)/100
    const scale=p.currency==='TWD'?1:100, x=Number(value)
    const v=scale===1?Math.round(Math.abs(x)+Number.EPSILON):Math.round((Math.abs(x)+Number.EPSILON)*scale)/scale
    return x<0 && v?-v:v+0
  }
  const total=round((p.reinsurers || []).reduce((sum,r)=>sum+(Number(r.brokerageAmount)||0),0))
  if (!p.installmentEnabled || !p.performanceInstallments?.length) return [{id:'FULL',number:1,label:'Full',ratio:100,amount:total,...overseaDates(p)}]
  const rows=p.performanceInstallments, weights=rows.map(r=>Math.max(0,Number(r.ratio)||0))
  let denominator=weights.reduce((a,b)=>a+b,0)
  if (!denominator) {weights.fill(1);denominator=rows.length}
  const magnitude=Math.abs(total)
  const amounts=weights.map(w=>round(magnitude*w/denominator))
  amounts[0]=round(amounts[0]+round(magnitude-amounts.reduce((a,b)=>a+b,0)))
  if(magnitude>0 && amounts[0]<0 && p.premiumRounding!=='legacy-cents') {
    let remainder=round(-amounts[0]);amounts[0]=0
    for(let i=1;i<amounts.length && remainder>0;i++){const deduction=Math.min(amounts[i],remainder);amounts[i]=round(amounts[i]-deduction);remainder=round(remainder-deduction)}
  }
  if(total<0)for(let i=0;i<amounts.length;i++)amounts[i]=amounts[i]?-amounts[i]:0
  return rows.map((r,i)=>({id:r.id,number:i+1,label:`Installment ${i+1}`,ratio:r.ratio,amount:amounts[i],...overseaDates(p,{installmentId:r.id})}))
}
