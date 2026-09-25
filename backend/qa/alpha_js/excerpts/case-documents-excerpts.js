// Alpha 原始碼的「節錄」（差異測試用）：來自 api/case-documents.js（v53，雜湊 0db7421c95f1…）。
// 這個檔案 import 了 'hatchable'，無法直接在 Node 執行，所以把其中不碰資料庫的部分原樣切出來：
// 第 9 行（MAX_BYTES）、第 16–34 行（reinsurerKey、requiredReinsurers、coverageFor）、第 61–93 行（safeFilename、decodeAndValidate）。
// 這個檔案是由程式從「雜湊與 Alpha 相同」的原檔切出的（見 MANIFEST.md），不可手動修改。

const MAX_BYTES = 5 * 1024 * 1024;

function reinsurerKey(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function requiredReinsurers(payload) {
  return [...new Set((Array.isArray(payload?.reinsurers) ? payload.reinsurers : [])
    .map((row) => reinsurerKey(row?.name)).filter(Boolean))];
}

function coverageFor(payload, files) {
  const selected = files.filter((file) => file.is_selected);
  const required = requiredReinsurers(payload);
  const offer = selected.some((file) => file.kind === 'offer');
  const covered = new Set();
  selected.filter((file) => file.kind === 'signed' || file.kind === 'confirmation')
    .forEach((file) => (Array.isArray(file.reinsurers) ? file.reinsurers : []).forEach((name) => covered.add(reinsurerKey(name))));
  const missing = required.filter((name) => !covered.has(name));
  return { offer, required, covered: required.filter((name) => covered.has(name)), missing, ready: offer && required.length > 0 && missing.length === 0, selected: selected.map((file) => file.id) };
}

function safeFilename(value) {
  return String(value || '').replace(/[\x00-\x1f\x7f/\\]/g, '_').slice(0, 180);
}

function decodeAndValidate(filename, encoded) {
  const ext = filename.includes('.') ? filename.split('.').pop().toLowerCase() : '';
  if (!['pdf', 'docx', 'png', 'jpg', 'jpeg', 'eml', 'msg'].includes(ext)) {
    return { error: [415, 'Use PDF, DOCX, PNG, JPG, EML or MSG.'] };
  }
  if (typeof encoded !== 'string' || !encoded.length || encoded.length > Math.ceil(MAX_BYTES / 3) * 4 + 8) {
    return { error: [413, 'Each file must be nonempty and no larger than 5 MB.'] };
  }
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
    return { error: [400, 'Invalid file encoding.'] };
  }
  let raw;
  try { raw = atob(encoded); } catch (_) { return { error: [400, 'Invalid file encoding.'] }; }
  if (!raw.length || raw.length > MAX_BYTES) return { error: [413, 'Maximum file size is 5 MB.'] };
  const starts = (...bytes) => bytes.every((byte, index) => raw.charCodeAt(index) === byte);
  const matches = ext === 'pdf' ? raw.startsWith('%PDF-')
    : ext === 'png' ? starts(137, 80, 78, 71, 13, 10, 26, 10)
      : ['jpg', 'jpeg'].includes(ext) ? starts(255, 216, 255)
        : ext === 'docx' ? starts(80, 75, 3, 4) && raw.includes('[Content_Types].xml') && raw.includes('word/')
          : ext === 'msg' ? starts(208, 207, 17, 224, 161, 177, 26, 225)
            : /^(?:From|Return-Path|Received|Delivered-To|MIME-Version|Message-ID|Date|Subject):/im.test(raw.slice(0, 8192));
  if (!matches) return { error: [415, 'File content does not match its extension.'] };
  const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
  const contentType = ext === 'pdf' ? 'application/pdf'
    : ext === 'docx' ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      : ext === 'png' ? 'image/png' : ['jpg', 'jpeg'].includes(ext) ? 'image/jpeg'
        : ext === 'eml' ? 'message/rfc822' : 'application/vnd.ms-outlook';
  return { ext, bytes, contentType };
}

export { reinsurerKey as documentsReinsurerKey, requiredReinsurers as documentsRequiredReinsurers, coverageFor as documentsCoverageFor, safeFilename, decodeAndValidate };
