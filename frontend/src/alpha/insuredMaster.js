import { apiFetch, ApiError } from '../api'
import { ElMessageBox } from 'element-plus'

// A merge is a separate, explicit confirmation. Failed/cancelled requests retain the editor.
export async function saveWithInsuredMerge(url, body, method='POST') {
  let data, response
  for(let attempt=0;attempt<2;attempt++) {
    response=await apiFetch(url,{method,headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify(body)})
    data=await response.json()
    if(response.ok)return data
    if(data.error!=='insured_merge_required'||attempt)break
    try { await ElMessageBox.confirm(`“${data.sourceName}” and “${data.targetName}” already have separate insured masters. Confirm they are the same insured to merge their linked cases. Historical case names will be retained.`, 'Confirm insured merge', {confirmButtonText:'Same insured — merge',cancelButtonText:'Keep separate',type:'warning'}) } catch { throw new Error('Merge not confirmed. Your changes remain in the editor.') }
    body={...body,insuredMerge:data.insuredMerge}
  }
  throw new ApiError(data.message||data.error||`HTTP ${response.status}`,response.status,data.error)
}
