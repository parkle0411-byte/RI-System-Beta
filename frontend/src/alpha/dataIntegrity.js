// Read-only data quality checks. Empty draft values are allowed; saved data is never repaired here.
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const numberPattern = /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/
export const readableNumber = value => value == null || typeof value === 'string' && !value.trim()
  || (typeof value === 'number' && Number.isFinite(value))
  || (typeof value === 'string' && numberPattern.test(value.trim().replace(/,/g,'')) && Number.isFinite(Number(value.trim().replace(/,/g,''))))
const fields = ['originalPremium','riCommPct','taxPct']
const rows = {reinsurers:['sharePct','premium','riCommPct','taxPct'],performanceInstallments:['premium','ratio']}
export function financialIssues(payload) {
  if (payload == null) return []
  if (!object(payload)) return [{field:'case',label:'Case data has an invalid format.'}]
  const issues=[]
  const add=field=>issues.push({field,label:`${field}: invalid financial data. Correct the saved data before continuing.`})
  const numbers=(row,keys,prefix='')=>keys.forEach(key=>{
    const value=row[key]
    if(!readableNumber(value))add(prefix+key)
    else if(['sharePct','riCommPct','taxPct','ratio'].includes(key) && value!=null && String(value).trim() && !(Number(String(value).replace(/,/g,''))>=0 && Number(String(value).replace(/,/g,''))<=100))add(prefix+key)
  })
  numbers(payload,fields)
  for(const [key,keys] of Object.entries(rows)) {
    const value=payload[key]
    if(value==null)continue
    if(!Array.isArray(value)){add(key);continue}
    value.forEach((row,i)=>{
      const field=`${key}.${i}`
      if(!object(row)){add(field);return}
      numbers(row,keys,field+'.')
      if(key==='reinsurers' && row.name!=null && typeof row.name!=='string')add(field+'.name')
    })
  }
  return issues
}
export const financialFields=['cedantPremium','cedantCommission','cedantTax','leg1','reinsurerPremium','reinsurerDeductions','reinsurerTax','leg2','leg3','brokerage']
export const pendingTotals=()=>Object.fromEntries(financialFields.map(key=>[key,null]))
export function displayPayload(payload) {
  // Only a render copy is made safe. Editing and all writes keep the raw payload and its issues.
  const result=object(payload)?{...payload}:{}
  for(const [key,keys] of Object.entries(rows)) {
    result[key]=(Array.isArray(result[key])?result[key]:[]).filter(object).map(row=>{
      const copy={...row}
      for(const field of keys)if(!readableNumber(copy[field]))copy[field]=null
      if(key==='reinsurers' && typeof copy.name!=='string')copy.name=''
      if(key==='performanceInstallments' && !object(copy.reinsurerPaymentTerms))copy.reinsurerPaymentTerms={}
      return copy
    })
  }
  for(const field of fields)if(!readableNumber(result[field]))result[field]=null
  return result
}
