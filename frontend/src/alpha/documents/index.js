// 產生 Cover Note／Debit Note／Endorsement（Alpha 的 docx-generator.js、pdf-generator.js 原樣照搬，這裡只接 VM 的 API）。
//  - 四個 Alpha 原檔放在 frontend/public/alpha-documents/（原封不動，run_calc_diff.sh 核對雜湊），和 Alpha 一樣用一般的
//    <script> 依序載入：不能交給 Vite 打包，docx-generator.js 是 UMD，打包工具看到 module.exports 會把它當 CommonJS 包起來，
//    結果走 require('jszip') 那條路（瀏覽器沒有 require）。第一次產生文件時才載入（Word 範本約 250 KB）。
//  - Word：在瀏覽器產生（同 Alpha）；產生前先呼叫 /api/document-generation-log 寫 Audit（VM 才有，2026-09-26 的決定）。
//  - PDF：版面同樣在瀏覽器組好，送 /api/render-document-pdf 由伺服器轉成 PDF。Alpha 的 RIPdf.generate() 直接用 fetch()，
//    沒有 VM 需要的 CSRF；所以改用它匯出的 _qa（同一組版面函式）組出一模一樣的 markup，再經 apiFetch 送出，原檔不改。
import JSZip from 'jszip'
import { apiFetch } from '../../api'

// 與 Alpha public/index.html 的 <script> 順序相同（jszip 之後）
const SCRIPTS = ['docx-templates.js', 'docx-generator.js', 'pdf-assets.js', 'pdf-generator.js']

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
  await load()
  if (!window.RIDocx || !window.RI_DOCX_TEMPLATES) throw new Error('Word document generator is unavailable.')
  const logged = await apiFetch('/api/document-generation-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ kind, format: 'docx', caseUid: documentCase.caseUid || '' })
  })
  if (!logged.ok) throw await readError(logged, `Document request failed (HTTP ${logged.status}).`)
  const blob = kind === 'cover'
    ? await window.RIDocx.generateCover(documentCase, window.RI_DOCX_TEMPLATES)
    : await window.RIDocx.generateDebit(documentCase, window.RI_DOCX_TEMPLATES)
  const filename = kind === 'cover' ? window.RIDocx.coverFilename(documentCase) : window.RIDocx.debitFilename(documentCase)
  window.RIDocx.downloadBlob(blob, filename)
}

export async function generatePdf(kind, documentCase) {
  await load()
  if (!window.RIPdf || !window.RI_PDF_ASSETS) throw new Error('PDF document generator is unavailable.')
  const qa = window.RIPdf._qa
  const pages = await (kind === 'cover' ? qa.coverPages(documentCase) : kind === 'endorsement' ? qa.endorsementPages(documentCase) : qa.debitPages(documentCase))
  // 同 Alpha generate()：markup = style() + 各頁
  const response = await apiFetch('/api/render-document-pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ markup: `${qa.style()}${pages.join('')}`, kind, caseUid: documentCase.caseUid || '' })
  })
  if (!response.ok) throw await readError(response, 'Unable to render PDF.')
  const blob = await response.blob()
  const filename = kind === 'cover'
    ? window.RIPdf.coverFilename(documentCase)
    : kind === 'endorsement'
      ? window.RIPdf.endorsementFilename(documentCase)
      : window.RIPdf.debitFilename(documentCase)
  window.RIPdf.download(blob, filename)
}
