import { usesStoredQsWord, saveAndDownloadQsWord, readDocumentError } from './qsWordWorkflow'
import { premiumPeriodAmounts } from '../lib/accounting.js'
// Word-only generation uses preserved Alpha templates and the VM generator.
// UMD scripts load lazily after JSZip; the API checks access and records metadata.
import JSZip from 'jszip'
import { propertyEnabled, propertyTotals, propertyMoney, propertyPeriodAllocate, perReinsurer } from '../propertyOriginal.js'
import { apiFetch } from '../../api'
import { isStandardCgl, cglInformationRows } from '../cglInformation'
import { CGL_TYPE_PREFIXES, cglTypePrefix, cglType, cglCoveragesText } from '../cglRiskDetails'

// Load shared templates before the current VM Word generator.
const SCRIPTS = ['docx-templates.js', 'vm-docx-generator.js']

function addScript(name) {
  return new Promise((resolve, reject) => {
    const el = document.createElement('script')
    el.src = `${import.meta.env.BASE_URL}alpha-documents/${name}?v=endorsement-notes-20261029`
    el.async = false
    el.onload = resolve
    el.onerror = () => { el.remove(); reject(new Error('Document generator could not be loaded.')) }
    document.head.appendChild(el)
  })
}

let loading = null
function load() {
  if (!loading) {
    window.JSZip = window.JSZip || JSZip   // The VM generator reads JSZip when its script loads.
    loading = SCRIPTS.reduce((chain, name) => chain.then(() => addScript(name)), Promise.resolve())
      .catch((err) => { loading = null; throw err })
  }
  return loading
}

async function readError(response, fallback) {
  return readDocumentError(response, fallback)
}

export async function generateDocx(kind, documentCase) {
  if (!['cover', 'debit', 'credit', 'endorsement'].includes(kind)) throw new Error('Unsupported document kind.')
  await load()
  if (!window.RIDocx || !window.RI_DOCX_TEMPLATES) throw new Error('Word document generator is unavailable.')
  const storedQs = usesStoredQsWord(kind, documentCase)
  const logged = await apiFetch('/api/document-generation-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ kind, format: 'docx', caseUid: documentCase.caseUid || '', ...(storedQs ? { saveWorkflow: 1, rowVersion: documentCase.caseRowVersion } : {}) })
  })
  if (!logged.ok) throw await readError(logged, `Document request failed (HTTP ${logged.status}).`)
  if (storedQs) {
    const prepared = await logged.json()
    documentCase = { ...documentCase, qsGenerationDate: prepared.generationDate }
  }

  const generator = {
    cover: ['generateCover', 'coverFilename'],
    debit: ['generateDebit', 'debitFilename'],
    credit: ['generateCredit', 'creditFilename'],
    endorsement: ['generateEndorsement', 'endorsementFilename']
  }[kind]
  if (isStandardCgl(documentCase) && CGL_TYPE_PREFIXES.includes(cglTypePrefix(documentCase))) documentCase = { ...documentCase, type: cglType(documentCase) }
  if (propertyEnabled(documentCase)) {
    const exact=propertyTotals(documentCase)
    const installmentWeights=(documentCase.performanceInstallments||[]).map(r=>r.premium ?? r.ratio ?? 0)
    documentCase={...documentCase,propertyInstallmentNet:perReinsurer(documentCase) ? premiumPeriodAmounts(documentCase).map(r=>r.leg1) : propertyPeriodAllocate(exact.leg1,installmentWeights,documentCase),propertyFinancials:{order:exact.order,originalPremium:propertyMoney(documentCase.originalPremium,documentCase),
      cededPremium:exact.cedantPremium,commission:exact.cedantCommission,tax:exact.cedantTax,netDue:exact.leg1,t1s:[exact.leg1]}}
  }
  const renderCase = kind === 'cover' && isStandardCgl(documentCase)
    ? { ...documentCase, cglInformationRows: cglInformationRows(documentCase), cglCoveragesText: cglCoveragesText(documentCase) } : documentCase
  if (storedQs) {
    return saveAndDownloadQsWord(kind, documentCase, () => window.RIDocx[generator[0]](renderCase, window.RI_DOCX_TEMPLATES))
  }
  const blob = await window.RIDocx[generator[0]](renderCase, window.RI_DOCX_TEMPLATES)
  window.RIDocx.downloadBlob(blob, window.RIDocx[generator[1]](documentCase))
}
