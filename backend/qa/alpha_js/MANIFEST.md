# Alpha 原始碼副本（差異測試用）

這些檔案是 Hatchable「RI System (Alpha)」（`proj_FVUqiQUe3m0G`）**v53** 的原始碼，**逐位元組相同**，
不可手動修改。差異測試（`scripts/run_qa.sh calc`）會拿它們當作「標準答案」，與 VM 的 Python 移植版比對。

| 檔案 | 行數 | SHA-256（與 Alpha `list_files` 的雜湊相同） |
|---|---|---|
| `lib/accounting.js` | 135 | `e0acc3c8091b843d89aaa7c52dea5a7aba3be15499d8919b3c61b94fb471ac02` |
| `lib/payment-terms.js` | 248 | `eaaeb93887d057255cc3a2b4ee7fdaf42c3a7dcfbd8aba6561a0e03c1213b248` |
| `lib/case-draft.js` | 385 | `42983151fe3b0ec514abbcad750357ef71d2e2dd7086a9a4d009cd8d54bdd338` |
| `lib/signed-slip-reminders.js` | 95 | `37e712193f694afa6973914f650f9cab79045bff3fa397c0e39176bf18d508a9` |
| `lib/production-report.js` | 211 | `4474c028d35fa1cb474a1188020eb7619e3df678b7e933e27ce2f9fcba48c3ba` |

## 節錄（`excerpts/api-excerpts.js`）

`api/case-announce.js`（`af6d6ed9…`）與 `api/case-workflow.js`（`a74a399b…`）import 了 `hatchable`，無法在 Node 直接執行，
所以把其中不碰資料庫的函式節錄到這個檔案：`reinsurerKey`、`requiredReinsurers`、`coverageFor`、`sameIds`、`referencePrefix`、`shiftYear`、`resetSharedPayload`
與 `case-workflow.js` 裡 `createEndorsement`／`createRenewal`／`reverseCase`／`notifyAccounting` 的資料整理敘述（外面加了測試用的外殼函式）。
`shiftYear`、`resetSharedPayload` 已與還原出的 Alpha 檔案逐字比對相同；包裝函式內的每一行敘述也都在 Alpha 檔案內（只有外殼的變數定義與 `return` 是測試加的）。
`case-announce.js` 的部分是拿 Alpha 的逐行列表目視核對的。

| 檔案 | SHA-256 |
|---|---|
| `excerpts/api-excerpts.js` | `8b923741953d52f2c643f62dbf060ab2ad50c8f48e70ae29902059b92e738111` |

### `excerpts/case-documents-excerpts.js`

由程式從 `api/case-documents.js`（231 行，雜湊 `0db7421c95f10b83650cc3a006d96cd6a6747d77327c2219cee295e3b006ef77`，先確認整檔雜湊相同）
原樣切出第 9、16–34、61–93 行，前面加說明、最後加一行 `export`（名稱加 `documents` 前綴，避免與 Announce 的同名函式衝突）。

| 檔案 | SHA-256 |
|---|---|
| `excerpts/case-documents-excerpts.js` | `c8d56984be7b2b775227e6bf8ba87a3a6f56b69ec5f5f870192050de3ac97877` |

### `excerpts/accounting-excerpts.js`

由程式從 `api/accounting.js`（209 行，雜湊 `ddd2cc0a643038a40de352e4d946d22c4d639aa1210cb0dd207ee3a16b16984a`，先確認整檔雜湊相同）
原樣切出第 3–4 行（import）與第 37–85 行（`ledgerRows`），前面加說明、最後加一行 `export`（名稱改為 `accountingLedgerRows`）。

| 檔案 | SHA-256 |
|---|---|
| `excerpts/accounting-excerpts.js` | `46509d7f4cbfe6144d184b36a289a38fd53e7d30598a8f4589ba4d9cd9b36a77` |

### `excerpts/production-excerpts.js`

由程式從 `api/production-report.js`（355 行，雜湊 `669afb28d56692b9fbd0a842aa5f2a818eb9ffb5a2baa0915a4ed9ab0fd8271a`，先確認整檔雜湊相同）
原樣切出 closeReport() 的第 241–288 行（整理一個案件：確認 key、沖銷分錄、保費交易），外面加上測試用的外殼函式 `productionConfirmCase`
（外殼的宣告、`closedCases` 的初值與 `return` 是測試加的），前面加 import。

| 檔案 | SHA-256 |
|---|---|
| `excerpts/production-excerpts.js` | `ecfaed1cd3835b6537ad3b399bf8fab1a5b2c661cd52c7e1dbbb40640cd05640` |

### `excerpts/dashboard-excerpts.js`

由程式從 `api/dashboard.js`（206 行，雜湊 `26002e5ca5fa431860e2cd7c677fbe4d52cbabb094de77c8d9c793625bb79561`，先確認整檔雜湊相同）
原樣切出第 8–81 行（輔助函式）與第 114–205 行（handler 在三個查詢之後的全部敘述），後者外面加上測試用的外殼函式 `dashboardSummary`
（外殼提供查詢結果與 `res.json`），前面加 import。

| 檔案 | SHA-256 |
|---|---|
| `excerpts/dashboard-excerpts.js` | `b5b6a3ef3baa10f576485ddd402c30121c3886ebd021af2a0d52d7e3785713df` |

## Alpha 改了這些檔案時

1. 對 Claude 說「檢查漂移」，它會比對 Alpha 目前的雜湊，告訴你哪些檔案變了。
2. 重新取得新版並確認雜湊相同後，覆蓋這裡的檔案、更新上表與 `MIGRATION-STATUS.md`。
3. 跑 `scripts/run_qa.sh calc`：不一致的地方就是 Python 版要同步修改的地方。

### `excerpts/render-pdf-excerpts.js`

由程式從 `api/render-document-pdf.js`（100 行，雜湊 `1741aaa47f3c478d9f101d6fd066d31386257b89e1ca499d9995e1b046b343d2`，先確認整檔雜湊相同）
原樣切出第 6–20 行（`rejectUnsafeMarkup`）與第 23–32 行（handler 開頭的 markup 檢查，外面加測試用的外殼函式 `renderPdfMarkupStatus`），
最後加一行 `export`（`rejectUnsafeMarkup` 以 `renderPdfRejectUnsafeMarkup` 的名稱匯出）。

| 檔案 | SHA-256 |
|---|---|
| `excerpts/render-pdf-excerpts.js` | `8da173d97483b0565bb6d5068be28b2a02543996ba58e55892d06a838f330b88` |

### `excerpts/reminders-excerpts.js`

由程式從 `api/payment-reminders.js`（223 行，雜湊 `14d5c92bc56dd9e176d05216104599b2bd682a512a4ddc332ddd90ad84c0dced`）與
`api/signed-slip-reminders.js`（232 行，雜湊 `4bf1b2d5f60b44c6e3cf3c026b4196296e8265576e44b575eb7919a346368617`）切出（先確認兩檔整檔雜湊相同）：
付款第 19–100 行（`esc`、`validEmail`、`label`、`message`、`resolveRecipients`、`dueKind`）、第 129–131 行（Finance 收件人篩選，外殼 `payFinanceEmails`）；
Signed Slip 第 18–57 行（`escapeHtml`、`validEmail`、`contactFor`、`reminderMessage`，包在區塊內避免與付款的同名函式衝突）。
import 只保留用到的 `daysBetweenDates`、`addCalendarDays`；最後的 `export` 加上 `pay`／`slip` 前綴。

| 檔案 | SHA-256 |
|---|---|
| `excerpts/reminders-excerpts.js` | `a7f7662e7d538614a43fd2bf9dd98a44d73270c293899962869fbe2be3cc2266` |
