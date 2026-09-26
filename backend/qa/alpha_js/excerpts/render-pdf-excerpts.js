// Alpha 原始碼的「節錄」（差異測試用）：來自 api/render-document-pdf.js（v53，雜湊 1741aaa47f3c478d…）。
// 這個檔案 import 了 'hatchable'，無法直接在 Node 執行，所以把不碰資料庫與瀏覽器的部分原樣切出來：
//   - 第 6–20 行：rejectUnsafeMarkup（逐字）
//   - 第 23–32 行：handler 開頭的 markup 檢查（逐字），外面加上測試用的外殼函式 renderPdfMarkupStatus：
//     外殼提供 req（只有 body）與 res.status().json()（直接回傳 {status, body}），最後的「通過」回傳是測試加的。
// 這個檔案是由程式從「雜湊與 Alpha 相同」的原檔切出的（見 MANIFEST.md），不可手動修改。

function rejectUnsafeMarkup(value) {
  return /<(script|iframe|object|embed|link|base)\b/i.test(value)
    || /@import\b/i.test(value)
    || /url\s*\(/i.test(value)
    || /<img\b[^>]*\bsrc\s*=\s*["'](?!data:image\/jpeg;base64,)/i.test(value)
    // Bugfix (#21): the blacklist above only stopped a few known-dangerous
    // tags, not event-handler attributes (onerror, onload, onclick, ...) on
    // any ordinary tag, nor a javascript: URI scheme — both are enough to
    // execute script in the headless browser this markup is rendered in.
    // This is defense-in-depth (all free-text case fields are already
    // HTML-escaped before reaching here), but this endpoint had no second
    // layer of its own.
    || /\son\w+\s*=/i.test(value)
    || /javascript\s*:/i.test(value);
}

export function renderPdfMarkupStatus(body) {
  const req = { body };
  const res = { status(code) { return { json(payload) { return { status: code, body: payload }; } }; } };
  const markup = req.body && req.body.markup;
  if (typeof markup !== "string" || !markup.trim()) {
    return res.status(400).json({ error: "PDF markup is required." });
  }
  if (markup.length > 2_000_000) {
    return res.status(413).json({ error: "PDF markup is too large." });
  }
  if (rejectUnsafeMarkup(markup)) {
    return res.status(400).json({ error: "PDF markup contains unsupported content." });
  }
  return { status: 200 };
}

export { rejectUnsafeMarkup as renderPdfRejectUnsafeMarkup };
