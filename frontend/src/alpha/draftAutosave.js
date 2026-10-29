import { ref, nextTick, onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

// A single serial writer owns rowVersion. Failed writes retain the editor.
export function useDraftAutosave({ enabled, snapshot, identity, save, applied }) {
  const message = ref(''), error = ref('')
  let baseline = '', intent = false, changed = false, epoch = 0, flight = null, requested = false, timer = null
  let interactionBaseline = ''
  const signature = () => JSON.stringify(snapshot(), (key,value) => key === 'clientKey' ? undefined : value)
  function reset() {
    epoch++; flight=null; baseline=signature(); interactionBaseline=baseline; intent=false; changed=false; requested=false
    message.value='';error.value=''; clearTimeout(timer)
  }
  function touch(event) {
    if (event?.type === 'pointerdown' && !event.target.closest('input,textarea,button,[role="combobox"],[role="switch"],[role="checkbox"],.el-select,.el-date-editor')) return
    if (!intent) interactionBaseline=signature()
    intent=true
  }
  async function blur() {
    await nextTick()
    if (!intent || !enabled.value) return
    const current=signature()
    if (current !== interactionBaseline) changed=true
    if (changed && current !== baseline) {
      clearTimeout(timer)
      timer=setTimeout(() => { void flush() },0)
    }
  }
  async function flush(force=false) {
    clearTimeout(timer)
    if (!enabled.value || (!force && (!intent || !changed))) return true
    requested=true
    if (flight) { await flight; return !error.value }
    const runEpoch=epoch
    const run=async () => {
      while (requested && enabled.value && epoch===runEpoch) {
        requested=false
        const data=snapshot(), current=JSON.stringify(data,(key,v)=>key==='clientKey'?undefined:v)
        if (current===baseline) { changed=false; continue }
        message.value='Saving draft…';error.value=''
        try {
          const result=await save(data,identity())
          if (epoch!==runEpoch) return
          applied(result)
          baseline=current
          changed=signature()!==current
          interactionBaseline=current
          message.value='Draft saved automatically'
        } catch (e) {
          if(epoch!==runEpoch)return
          changed=true; requested=false;message.value=''
          error.value=e instanceof Error ? e.message : String(e)
        }
      }
    }
    const currentFlight=run()
    flight=currentFlight
    await currentFlight
    if(flight===currentFlight)flight=null
    return !error.value
  }
  function beforeUnload(event) {
    if (enabled.value && (changed || intent && signature()!==baseline)) { event.preventDefault();event.returnValue='' }
  }
  window.addEventListener('beforeunload',beforeUnload)
  onBeforeRouteLeave(async () => !enabled.value || !intent || await flush(true))
  onBeforeUnmount(() => { clearTimeout(timer);window.removeEventListener('beforeunload',beforeUnload);epoch++ })
  return { message,error,reset,touch,blur,flush }
}
