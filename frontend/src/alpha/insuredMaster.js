import { apiFetch, ApiError } from '../api'
import { ElMessageBox } from 'element-plus'

// A merge is a separate, explicit confirmation. Failed/cancelled requests retain the editor.
export async function saveWithInsuredMerge(url, body, method='POST') {
  let data, response
  for(let attempt=0;attempt<4;attempt++) {
    response=await apiFetch(url,{method,headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify(body)})
    data=await response.json()
    if(response.ok)return data
    if(data.error==='insured_change_required') {
      let kind
      try {
        await ElMessageBox.confirm(`Case name: “${data.insuredChange.before}” → “${data.insuredChange.after}”. Name correction renames master “${data.insuredChange.masterName}”; other policies keep their historical names. A different combination changes only this Case's link.`, 'Confirm insured change', {confirmButtonText:'Name correction',cancelButtonText:'Change insured combination',distinguishCancelAndClose:true,closeOnClickModal:false,type:'warning'})
        kind='correction'
      } catch(action) {
        if(action==='cancel')kind='combination'
        else throw new Error('Insured change cancelled. Your changes remain in the editor.')
      }
      body={...body,insuredChangeKind:kind,insuredChange:data.insuredChange}
      continue
    }
    if(data.error!=='insured_merge_required')break
    try { await ElMessageBox.confirm(`“${data.sourceName}” and “${data.targetName}” already have separate insured masters. Confirm they are the same insured combination to merge their linked cases. Historical case names will be retained.`, 'Confirm insured merge', {confirmButtonText:'Same combination — merge',cancelButtonText:'Keep separate',type:'warning'}) } catch { throw new Error('Merge not confirmed. Your changes remain in the editor.') }
    body={...body,insuredMerge:data.insuredMerge}
  }
  throw new ApiError(data.message||data.error||`HTTP ${response.status}`,response.status,data.error)
}
