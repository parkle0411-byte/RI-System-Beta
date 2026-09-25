# Alpha 原始碼副本（差異測試用）

這些檔案是 Hatchable「RI System (Alpha)」（`proj_FVUqiQUe3m0G`）**v53** 的原始碼，**逐位元組相同**，
不可手動修改。差異測試（`scripts/run_qa.sh calc`）會拿它們當作「標準答案」，與 VM 的 Python 移植版比對。

| 檔案 | 行數 | SHA-256（與 Alpha `list_files` 的雜湊相同） |
|---|---|---|
| `lib/accounting.js` | 135 | `e0acc3c8091b843d89aaa7c52dea5a7aba3be15499d8919b3c61b94fb471ac02` |
| `lib/payment-terms.js` | 248 | `eaaeb93887d057255cc3a2b4ee7fdaf42c3a7dcfbd8aba6561a0e03c1213b248` |
| `lib/case-draft.js` | 385 | `42983151fe3b0ec514abbcad750357ef71d2e2dd7086a9a4d009cd8d54bdd338` |

## 節錄（`excerpts/api-excerpts.js`）

`api/case-announce.js`（`af6d6ed9…`）與 `api/case-workflow.js`（`a74a399b…`）import 了 `hatchable`，無法在 Node 直接執行，
所以把其中不碰資料庫的函式節錄到這個檔案：`reinsurerKey`、`requiredReinsurers`、`coverageFor`、`sameIds`、`referencePrefix`、`shiftYear`、`resetSharedPayload`
與 `case-workflow.js` 裡 `createEndorsement`／`createRenewal`／`reverseCase`／`notifyAccounting` 的資料整理敘述（外面加了測試用的外殼函式）。
`shiftYear`、`resetSharedPayload` 已與還原出的 Alpha 檔案逐字比對相同；包裝函式內的每一行敘述也都在 Alpha 檔案內（只有外殼的變數定義與 `return` 是測試加的）。
`case-announce.js` 的部分是拿 Alpha 的逐行列表目視核對的。

| 檔案 | SHA-256 |
|---|---|
| `excerpts/api-excerpts.js` | `8b923741953d52f2c643f62dbf060ab2ad50c8f48e70ae29902059b92e738111` |

## Alpha 改了這些檔案時

1. 對 Claude 說「檢查漂移」，它會比對 Alpha 目前的雜湊，告訴你哪些檔案變了。
2. 重新取得新版並確認雜湊相同後，覆蓋這裡的檔案、更新上表與 `MIGRATION-STATUS.md`。
3. 跑 `scripts/run_qa.sh calc`：不一致的地方就是 Python 版要同步修改的地方。
