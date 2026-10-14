// Word-only generation uses preserved Alpha templates and the VM generator.
// UMD scripts load lazily after JSZip; the API checks access and records metadata.
import JSZip from 'jszip'
import { apiFetch } from '../../api'

// 與 Alpha public/index.html 的 <script> 順序相同（jszip 之後）
const SCRIPTS = ['docx-templates.js', 'vm-docx-generator.js']

function addScript(name) {
  return new Promise((resolve, reject) => {
    const el = document.createElement('script')
    el.src = `${import.meta.env.BASE_URL}alpha-documents/${name}`
    el.async = false
    el.onload = resolve
    el.onerror = () => { el.remove(); reject(new Error('Document generator could not be loaded.')) }
    document.head.appendChild(el)
  })
}

let loading = null
function load() {
  if (!loading) {
    window.JSZip = window.JSZip || JSZip   // docx-generator.js 載入當下就讀 window.JSZip（npm 套件 jszip 3.10.1，與 Alpha 同版）
    loading = SCRIPTS.reduce((chain, name) => chain.then(() => addScript(name)), Promise.resolve())
      .catch((err) => { loading = null; throw err })
  }
  return loading
}

async function readError(response, fallback) {
  const body = await response.json().catch(() => ({}))
  return new Error(body.message || body.error || fallback)
}

export async function generateDocx(kind, documentCase) {
  if (!['cover', 'debit', 'endorsement'].includes(kind)) throw new Error('Unsupported document kind.')
  await load()
  if (!window.RIDocx || !window.RI_DOCX_TEMPLATES) throw new Error('Word document generator is unavailable.')
  const logged = await apiFetch('/api/document-generation-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ kind, format: 'docx', caseUid: documentCase.caseUid || '' })
  })
  if (!logged.ok) throw await readError(logged, `Document request failed (HTTP ${logged.status}).`)
  const generator = {
    cover: ['generateCover', 'coverFilename'],
    debit: ['generateDebit', 'debitFilename'],
    endorsement: ['generateEndorsement', 'endorsementFilename']
  }[kind]
  const blob = await window.RIDocx[generator[0]](documentCase, window.RI_DOCX_TEMPLATES)
  window.RIDocx.downloadBlob(blob, window.RIDocx[generator[1]](documentCase))
}
