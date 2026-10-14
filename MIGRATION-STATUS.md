# Alpha → VM 搬遷狀態

- 來源：Hatchable「RI System (Alpha)」`proj_FVUqiQUe3m0G`，**記錄基準：v63（2026-10-05，82 個檔案）**
- 2026-09-29 起你決定把 VM 的改動**同步回 Alpha**（登入／權限、資料表結構、Personnel & Accounts 資料除外），之後會先在 Alpha 開發新功能。每批部署後，下表的雜湊改成新版本，漂移檢查照舊。見下方「VM → Alpha 同步」。
- 目標：本專案（Django + MySQL + Vue，Docker Compose）
- 原則：Alpha 是唯一的正式規格來源，VM 只移植、不自行改規格。刻意不同的地方一律寫在下面「刻意與 Alpha 不同」。

## Audit 暫停（2026-10-05，最新決定）

業主要求 VM Audit 功能先關閉，直至另行通知。已於同日備份後清除當時的 264 筆 Audit（備份 `backups/ri_system_before_audit_clear_20261005_142025.sql`）。
本次以 `compose.yaml` 的 `AUDIT_LOG_PAUSED=true` 暫停 `record_audit`，保持 `AUDIT_LOG_ENABLED=true`，讓業務寫入與 Entity Snapshot 照常；Audit 表的不可修改／刪除 trigger 與權限不變。畫面與 API 如實回報暫停。
只有業主另行要求才重新啟用：將 `AUDIT_LOG_PAUSED` 改為 false 並重建 backend 容器；不補寫暫停期間事件。下方歷史紀錄「Audit 全面啟用」由本段最新決定取代。

## 固定技術規格（VM）

| Layer | Stack |
|---|---|
| Frontend | Vue 3.5.43 + Element Plus 2.14.6 + Vite 7.3.6（另有 Vue Router 4.6.4、JSZip 3.10.1） |
| Backend/Admin Panel | Django 5.2.17 + DRF 3.16.1 + Gunicorn 23.0.0 + mysqlclient 2.3.0（Python 3.13） |
| Web Server / Reverse Proxy | Nginx 1.28（1.28.3） |
| DBMS | MySQL 8.4.11 |
| PDF Service | Gotenberg 8.37.0（Chromium 152；字型 Liberation Sans、Noto Sans CJK） |
| Host / Container Runtime | Debian GNU/Linux 13（trixie）+ Docker 29.8.1 + Docker Compose v5.5.1 |

各元件的鎖定方式（2026-09-26 實際核對執行中的版本）：

- **Frontend**：`frontend/package.json` 精確版本＋`package-lock.json`，Dockerfile 用 `npm ci` 在 `node:22-alpine` 建置。JSZip 是 Production Report 的 Excel 與 Word 產生用（與 Alpha 同版，2026-09-26 加入）。Alpha 的 Word／PDF 產生檔原樣放在 `frontend/public/alpha-documents/`，不經 Vite 打包。
- **Backend/Admin Panel**：`backend/requirements.txt` 精確版本，基底映像 `python:3.13-slim-bookworm`。Admin Panel 是唯讀的 Django admin（`/admin/`，只有 System Administrator）。
- **Web Server / Reverse Proxy**：`nginx:1.28-alpine`（與前端靜態檔同一個映像）。對外開 80 與 8080 埠：同事用 `http://ri-dev.tw-insure.com`，舊網址 `http://192.168.1.127:8080` 繼續可用。目前是 HTTP（HTTPS 暫緩）。
- **DBMS**：`compose.yaml` 固定在目前使用中映像的摘要（`8.4.11` 標籤在 9/21 被重新打包過，MySQL 版本相同、底層不同，所以固定摘要而不是標籤）。網站以最小權限的 `ri_runtime` 連線。
- **PDF Service**：`compose.yaml` 固定標籤＋摘要（`gotenberg/gotenberg:8.37.0@sha256:f29984bd…`）；只在內部網路 `pdf`，沒有對外埠、連不到 MySQL 與網際網路，關閉 JavaScript。
- **Host / Container Runtime**：主機時區 Asia/Taipei（提醒排程的 cron 依賴它，`scripts/install_reminder_cron.sh` 會檢查）。

前端因此**不沿用 Alpha 的無建置（UMD）前端**，畫面以 Vue 元件重寫；API 格式維持與 Alpha 一致，方便對照。
要升級任何一項，必須先更新這張表與鎖定檔，並重跑全部測試。

## 金額運算的原則

- 金額用**浮點數**，並完全比照 Alpha 的進位方式（`Math.round((x + EPSILON) * 100) / 100`，.5 往正無限大），
  所以 Python 版刻意重現 JavaScript 的語意（`backend/cases/calc/jsnum.py`），而不是改用 Decimal。
- 這些語意（`Number()` 的解析、數字轉文字、空白的定義、`2/30` 的日期滾動…）都用 Node 實測過。
- 驗證方式是**差異測試**：`scripts/run_qa.sh calc` 用同一批輸入（固定亂數種子）分別跑 Alpha 的原始 JavaScript
  （`backend/qa/alpha_js`，逐位元組相同、雜湊記錄在 `MANIFEST.md`）與 Python 移植版，要求輸出完全一致。
  已故意破壞 Python 版確認測試抓得到（四捨五入、日期滾動、數字轉文字、Facility 標籤、到期日）。

## 案件草稿驗證（`cases/draft.py`）的注意事項

- **錯誤訊息維持英文，與 Alpha 逐字相同**（2026-09-25 你的決定）；前端之後要中文化，可在前端加一層對照。
- 與 Alpha 相同的 JavaScript 特有行為（都用 Node 實測過）：文字以 **UTF-16 單位**截斷（表情符號可能被切成一半）、
  `Number()` 的解析規則、`Date.UTC` 把 **0–99 年當成 1900–1999**（所以 `0050-01-01` 會被拒絕）、
  JSON 大小上限 250000（以 UTF-16 單位計，剛好 250000 允許、250001 拒絕）。
- 一個刻意的差別：整數值的數字輸出成整數（`5`，不是 `5.0`），因為存進 JSON 後要能用文字比對（例如 `personnelId`）。
- **Clause 代碼的排序**用 ICU（`localeCompare('en')`）的規則：符號 < 數字 < 字母（所以 `LMA_1` 排在 `LMA3333` 前面，與一般的 ASCII 排序相反）。
  Python 沒有 ICU，`jsnum.js_locale_key` 是依 Node 逐類實測重建的：可印 ASCII、拉丁字母（含各種重音與 `Æ Œ Ø Ð Đ Ł Ŋ`）、
  相容字形、控制字元、希臘、西里爾、中日韓文字都已驗證與 Alpha 一致。
  **已知不一致**：非 ASCII 的符號與貨幣符號（`€ © ™ ° ± × …`）。Clause 代碼實務上是英數字與底線，不受影響；
  若日後代碼會用到這類符號，要先補上對照表（差異測試會立刻顯示）。

## 檢查漂移

Alpha 仍在持續修改。要確認哪些「已移植」的檔案在 Alpha 又被改了，請對 Claude 說「檢查漂移」：
它會取得 Alpha 目前每個檔案的雜湊，和下表「Alpha 雜湊」比對，列出不一致的檔案與需要同步的 VM 位置。
同步完成後，更新該列的雜湊，並把上面的「記錄基準」版本更新。

雜湊是 Alpha `list_files` 回傳的 SHA-256。

## 已移植

| Alpha 檔案 | Alpha 雜湊（v63） | VM 位置 | 狀態 |
|---|---|---|---|
| `api/fx-rates.js` | `a2496a82375c9159944318edbef2e7365f1b55c8acd78a8a6f1b3b29138e2de3` | `backend/fxrates/` | 完成（含 Audit，見下） |
| `migrations/0010_create_fx_rates.sql` | `0875485cf1049e3d6a39bc004decc950c9a547def9f6d82ceccd43204a965e4d` | `fxrates/models.py`、migrations | 完成 |
| `api/master-data.js` | `0993fb9df0419e1bdd1491cabd61627621967814f6df7719e873de09ece9288d` | `backend/masterdata/views.py` | 完成（含 #18） |
| `migrations/0001_create_master_records.sql` | `f8dde66dc346c860cbeaa436770c7dbc8af190db2b125c18ffcb732df1e7b393` | `masterdata/models.py` | 完成 |
| `lib/accounting.js` | `6449ed2677be5f35de1c5e69a29248e8cd9275d57ea441816a91dcb3d41f2778` | `backend/cases/calc/accounting.py`（＋`jsnum.py`） | 完成，**逐位一致**（含 #3）：Alpha 的 JavaScript 與 Python 對 9 萬 7 千組輸入完全相同 |
| `lib/payment-terms.js` | `50d6ad382f09238e960f783f6d7f7c64242bad09adb1d6cd28d205caaa129fee` | `backend/cases/calc/payment_terms.py` | 完成，**逐位一致** |
| `lib/case-draft.js` | `24d409bc954e4bbefc793de5bb5c3916034f8a700b45b33475ff8c1a542cb3a1` | `backend/cases/draft.py`（`normalize_draft`、`validate_announce_ready`） | 完成，**逐位一致**：錯誤訊息（含英文原文與出現的**順序**）、整理後的內容都相同；11 萬 3 千組輸入完全一致 |
| `api/personnel.js` | `f05dbd98a6de4c726efd3ef26f2db08a55d5b49812ce68526bcc8e49548f29c5` | `backend/personnel/views.py`（`PersonnelView`） | 完成（含 #14、#15，含 Audit／Snapshot） |
| `api/personnel-options.js` | `98e355b36501883a3bf0c11bd8f7ec42ddc779ef742cae021c9719facc0112ad` | `backend/personnel/views.py`（`PersonnelOptionsView`） | 完成 |
| `migrations/0011_create_personnel_accounts.sql`、`0012_add_internal_account_fields.sql`、`0013_add_personnel_auth_user_index.sql` | `e65f5d93…` / `5d0ce5cf…` / `e029be6d…` | `personnel/models.py`（姓名欄位放寬到 160，同 Alpha） | 完成 |
| `migrations/0033_add_master_records_ci_unique_indexes.sql` | `24f40ef637d6a4213ca6c59864c6012ed4fd8075b3e7ad704228e237c7338884` | `masterdata/migrations/0002` | 完成（MySQL 的 ai_ci 排序規則已不分大小寫） |
| `migrations/0034_scope_fixed_clauses_by_class.sql`（v54 新增，由 VM 同步回 Alpha） | `7fe60bcc5e3611ac6d2b98b0524d93f332c118da23279f127829efb6df962013` | VM 已由 CLI 做過同樣的資料更新（2026-09-29） | 不需要移植（只改資料） |
| `lib/authorization.js` | `86a63b152e9e6eace0be0817bfc87647c142e101e27f1106b815b71489457954` | `backend/ri_system/authz.py` | 完成（含 #13 的取捨，見下） |
| `api/app-context.js` | `952e70d6bd75625b4b3830227c7ec3bec8b9da697e3e9e3540076edf418ec991` | `ri_system/auth_views.py` `AppContextView` | 完成 |
| `lib/audit.js` | `3389da373c0a399204352bbb48ab6f8f6963d070c4b5da4116a81119dc6c2492` | `backend/audit/services.py` | 完成 |
| `api/audit-log.js` | `d5b60a7be8abff081f30608760850baf2b02c1c597caca8ab4562db7c73bfa7c` | `backend/audit/views.py` | 完成 |
| `migrations/0003_create_entity_snapshots.sql` | `62e6de4a5876a30131d46ea6d1c6376f28f8509e14e91acc3fac20a3d9c2f62b` | `audit/models.py` `EntitySnapshot` | 完成 |
| `migrations/0004_create_audit_log.sql` | `081b80765feee215cd9110c594e6a0ca1bcbef909e4662c55e613cb78dfb98b0` | `audit/models.py` `AuditLog` | 完成 |
| `migrations/0021_extend_audit_log_retention_20y.sql` | `b94788aa4e00808cc2edd0cd572b3f400b0ecd333f59a9bdfcf3fd91fb8b37ac` | `scripts/db_harden.sh`（保存期 trigger） | 完成 |
| `api/cases.js` | `783fa8c63da6f37ed2d590977f572f8ff10f856ec8a217ff9f003e238afb5723` | `backend/cases/views.py`（`CasesView`）、`cases/resolve.py` | 完成（含 #7、#8；含 Snapshot／Audit）。以 `qa/suites/cases_api.py` 驗證，並已用 26 種故意破壞確認測試抓得到 |
| `api/case-announce.js` | `e5221d95186f8219129a7c6543b1628d43a0811c76a40b055dbac25f2ef5ce62` | `backend/cases/workflow_views.py`（`AnnounceView`）、`cases/workflow.py` | 完成（Announce、TW Reference 流水號、批單編號；含 Snapshot／Audit）。純函式與 Alpha JS 差異測試逐位一致 |
| `api/case-workflow.js` | `8e3193e135a891ada6c3b11355552c0a37b98b96ab0885943cdd50421eff90fb` | `backend/cases/workflow_views.py`（`WorkflowView`）、`cases/workflow.py` | 完成（狀態、Endorsement、Renewal、Reverse、通知會計）。資料整理邏輯與 Alpha JS 差異測試逐位一致 |
| `api/case-documents.js` | `45b13fe76642d52a3ca61fbc873a429e32679c716626f3c70281e9d24a1ade05` | `backend/cases/document_views.py`（`CaseDocumentsView`）、`cases/documents.py`、`cases/storage.py` | 完成（上傳、列表、下載、勾選、刪除；含 #11、Audit）。純函式與 Alpha JS 逐位一致；測試組 `case_documents` 73 項 |
| `lib/signed-slip-reminders.js` | `37e712193f694afa6973914f650f9cab79045bff3fa397c0e39176bf18d508a9` | `backend/cases/calc/signed_slip.py` | 函式全部移植並與 Alpha JS 逐位一致（文件 API 用 `signedSlipTracking`，提醒排程用 `reminderDue`、`isReservedTestEmail`） |
| `api/accounting.js` | `abddcf88795fddc4d04b32d291fa7dabc9e8e4733440630ef73d8a008090b3cc` | `backend/cases/accounting_views.py`（`AccountingView`）、`cases/ledger.py`（`ledger_rows`） | 完成（帳本、記付款、沖銷；含 Snapshot／Audit）。帳本 `ledgerRows` 與 Alpha JS 差異測試逐位一致（600 組，節錄見 `qa/alpha_js/MANIFEST.md`）；測試組 `accounting_api` 77 項；19 種故意破壞全部抓到（其中 3 種帳本的破壞由差異測試抓到） |
| `api/claims.js` | `3444de68a9dade3b645a48084f631e5e32b105e261f4d5f2b66e2f4fe75862c9` | `backend/cases/claims_views.py`（`ClaimsView`） | 完成（讀取、新增理賠、改準備金、記理賠付款並產生 Claim Leg 1/2 交易；含 Snapshot／Audit）。交易由已與 Alpha 逐位一致的 `build_claim_payment_transactions` 產生；測試組 `claims_api` 67 項；21 種故意破壞全部抓到 |
| `lib/production-report.js` | `789e38dfb9974adcf71b3a9cf7302d1c458858fafb5ec41106d504f5bb5bfcb3` | `backend/production/calc.py` | 完成，**逐位一致**（預覽、key、簽章、下個月；差異測試約 1,000 組，含情境一致的案件、排除、延後、分績、分期） |
| `api/production-report.js` | `ad033c0da163ba9fc2f30bfb0915793f361352b1c72de69e0cc6896219b417b2` | `backend/production/views.py`（`ProductionReportView`）、`production/closing.py` | 完成（預覽、排除延後、產生版本、關帳：案件確認、Leg 1–3 交易、沖銷分錄、鎖匯率；含 Audit／Snapshot）。關帳整理案件的邏輯與 Alpha JS 逐位一致（600 組，節錄見 `qa/alpha_js/MANIFEST.md`）；測試組 `production_api` 72 項；故意破壞：計算 11＋關帳 4 種由差異測試抓到、API 18 種由測試組抓到 |
| `migrations/0016_create_production_report_lifecycle.sql` | `9fd6f3cc748e5a174715a09a289099be98cbfbf58c5ba6b8aa078e3cddcb5319` | `production/models.py`、`production/migrations/0001` | 完成（同樣的 CHECK 與唯一限制；PostgreSQL 的部分唯一索引／COALESCE 索引改用 MySQL 函式索引；排除紀錄 `ri_runtime` 只能 SELECT／INSERT） |
| `public/production-xlsx.js` | `256db219f84aa2e56c9e1a36c81541c1fe7a560b0a0f9054e2253773808dcf59` | `frontend/alpha-reference/production-xlsx.js`（**原樣**，雜湊固定）；VM 實際使用 `frontend/src/alpha/production-xlsx.js` = 原檔 + 4 處已記錄的修改（多一欄 First Policy No，見 2026-10-08 段落）；`scripts/check_production_xlsx.py`（由 `run_calc_diff.sh` 呼叫）核對兩者 | 完成（JSZip 改由 npm 套件提供，同版 3.10.1；VM 版多一欄） |
| `public/case-calculations.js` | `fd7036a492db60afaf2091d9f556001cb71f9f104bc6aa403eab0a5951920632` | `frontend/src/alpha/caseCalculations.js` | 完成（v60 起金額與記帳算法相同，兩邊一致；`run_qa.sh totals` 比對 VM 前端與後端） |
| `public/docx-generator.js` | `6726dda0f766ac4a6b4dbc084aa857a182f93cb5639c05d02b7afc9d23ebbbad` | `frontend/public/alpha-documents/`（**原樣**，`run_calc_diff.sh` 核對雜湊；和 Alpha 一樣以一般 `<script>` 載入，不經 Vite 打包） | 完成：Word 在瀏覽器產生（同 Alpha） |
| `public/docx-templates.js` | `b06c99814f1b0b3ecd556bdd3fe921f135363ed50a506f9f5b91d0fb2e3a0ef7` | 同上（原樣） | 完成 |
| `public/pdf-generator.js` | `f403fe41074f259066e8d192afa2adaa16828b59610dc9893b9841cdfbbb7d21` | 同上（原樣）；`frontend/src/alpha/documents/index.js` 用它匯出的 `_qa` 版面函式組 markup，經 `apiFetch`（帶 CSRF）送出 | 完成 |
| `public/pdf-assets.js` | `45736bdb789036bdfdbe36d3e764992af79fd6b92ec1c8af2df040db0d5711fa` | 同上（原樣） | 完成 |
| `api/render-document-pdf.js` | `1741aaa47f3c478d9f101d6fd066d31386257b89e1ca499d9995e1b046b343d2` | `backend/cases/document_generation_views.py`、`document_markup.py`；PDF 由內部的 Gotenberg（Chromium）產生 | 完成（含 #19、#21）。markup 檢查與 Alpha 逐字一致（差異測試 `renderPdfRejectUnsafeMarkup`／`renderPdfMarkupStatus`，約 5 千組）；測試組 `document_generation`（40 項；7 種故意破壞抓到 6 種，另 1 種「拿掉邊界 0」經實測是等價的：HTML 的 `@page { margin: 0 }` 優先，輸出完全相同）；差異測試的 3 種故意破壞（Unicode 大小寫、Python 的 `\s`、以字元數算長度）都抓到；畫面測試階段 H 實際點按鈕下載 5 種文件，檢查 Word 內容、PDF 的文字與字型（Liberation Sans、Noto Sans CJK TC）與 Audit |
| `api/dashboard.js` | `496539893d6f1c20b4d160ede275ff93cc88e78172434338f48a72252ec764e6` | `backend/dashboard/views.py`（`DashboardView`）、`dashboard/calc.py` | 完成。計算的「Alpha 模式」與 Alpha JS 逐位一致（600 組，節錄見 `qa/alpha_js/MANIFEST.md`；9 種故意破壞全部抓到）；正式 API 用台北時間與 Production 規則（見下） |
| `api/dashboard-targets.js` | `e53c69a6b18041de0cdee0f68b86bdb74643a719a8f98fe38cd7518e79b28005` | `backend/dashboard/views.py`（`DashboardTargetsView`） | 完成（列表、新增、修改、停用／重新啟用；含 Snapshot／Audit）。測試組 `dashboard_api` 38 項；API 故意破壞 14 種抓到 12 種，另 2 種與原行為等效（重複期間由資料庫唯一限制擋下；金額進位 MySQL DECIMAL 本身就是四捨五入） |
| `migrations/0011_create_personnel_accounts.sql` 的 `ri_dashboard_targets` | `e65f5d93…` | `dashboard/models.py`、`dashboard/migrations/0001` | 完成（同樣的 CHECK 與唯一限制；`ri_runtime` 沒有 DELETE） |
| `api/draft-recycle-bin.js` | `dc536779b7866648987eea2180884c4cd39c91144957cfcf5e30a2240cae8753` | `backend/cases/recycle_views.py`（`DraftRecycleBinView`） | 完成（列表、丟進回收桶、還原；5 年期限；永久刪除一律禁止）。測試組 `recycle_bin` 50 項 |
| `migrations/0005_create_draft_recycle_bin.sql`、`0019_lock_draft_recycle_policy.sql`、`0032_add_draft_recycle_bin_case_fk.sql` | `97cfe172…` / `eb607919…` / `b9bdfb0d…` | `cases/models.py`（`DraftRecycleBin`）、`cases/migrations/0003` | 完成（CHECK 禁止永久刪除、外鍵、索引；`ri_runtime` 沒有 DELETE） |
| `public/index.html`（外框、Dashboard、Account List、案件明細（含 Claim 分頁）、新增／編輯表單、回收桶、MDM、Personnel（含目標設定）、FX、Audit、Accounting、Production Report） | `c1872c843dca201e51340042807ce6563c77caf43f675d7e823d77371cbb385d` | `frontend/src/App.vue`、`src/views/*.vue`；案件工作區的模板由 `frontend/scripts/build_case_workspace.py` 按行號切自原檔 | 完成（9 個左側選單的畫面全部可用，沒有「Queued for migration」頁面；Alpha 隱藏未上選單的 Data reconciliation 畫面未移植） |
| `public/app.js`（上述畫面的邏輯） | `d91a6c969a156002567ea5d5317732f02dc767918ab7e71dfbc970ed5c83527c` | `frontend/src/views/case-workspace.script.js`、各 view、`src/alpha/constants.js`、`src/alpha/format.js` | 完成（逐函式移植，名稱相同） |
| `public/theme.css`、`public/overview.css`、`public/development-alignment.css` | `af2b57f0…` / `bceafbf2…` / `2da6fba1…` | `frontend/src/alpha/styles/`（原樣，載入順序同 Alpha） | 完成 |
| `migrations/0002_create_cases.sql`、`0006_add_case_uid.sql`、`0007_expand_reinsurance_structures.sql`、`0009_add_announce_workflow.sql`、`0014_add_case_owner.sql`、`0015_add_case_owner_index.sql` | `9e3a6164…` / `59ad607b…` / `8e4e3449…` / `cd7b0f75…` / `d7b2d9d8…` / `ceb171d9…` | `cases/models.py`（含 `ReferenceSequence`）、`cases/migrations` | 完成（由 cases／announce／workflow／accounting／claims／production 等 API 使用） |
| `api/signed-slip-reminders.js` | `db0d055ca9fda0ccd5b169d676b8028d37fb8bd59a830944c9875f933f8cb086` | `backend/reminders/`（`runner.run_signed_slip`、`messages.py`）、`manage.py run_signed_slip_reminders`（cron 每天台北 09:00） | 完成（#10，**不寄信模式**，見下）。收件人、信件內容與 Alpha JS 逐位一致（差異測試約 1.2 萬組，含金額四捨五入邊界）；測試組 `reminders`（45 項，8 種故意破壞都抓到）；畫面測試階段 R（案件明細 Reminders 分頁） |
| `api/payment-reminders.js` | `14d5c92bc56dd9e176d05216104599b2bd682a512a4ddc332ddd90ad84c0dced` | `backend/reminders/`（`runner.run_payment`、`messages.py`）、`manage.py run_payment_reminders`（cron 每天台北 09:30） | 完成（#9，**不寄信模式**）。收件人、到期判斷（`dueKind`）、信件內容（含金額格式）與 Alpha JS 逐位一致 |
| `migrations/0017_create_signed_slip_alerts.sql`、`0029_create_payment_alerts.sql`、`0030_index_payment_alerts.sql` | `33364cb8…` / `4f06c0ef…` / `913f5bb3…` | `reminders/models.py`、`reminders/migrations/0001` | 完成（同樣的唯一限制與索引；狀態多 `suppressed`、多存信件主旨與內文；`ri_runtime` 沒有 DELETE） |
| `migrations/0031_backfill_payment_schedule_state.sql` | `7e2bacb4…` | 不需要 | VM 的 `normalize_draft` 本來就設定 `paymentScheduleReviewRequired`，切換匯入的是 Alpha 已補過的資料 |
| `migrations/0008_create_case_documents.sql` | `bd0d2ee6e9fc68b2d75fc2093d1886654448743bf2ead2d2a693e742798b8fc1` | `cases/models.py`、`cases/migrations/0002` | 完成（上限改為 10 MB，見下） |

## VM → Alpha 同步

2026-09-29 你的決定：把 VM 的改動同步回 Alpha，範圍是新功能與業務規則、Alpha 的 bug 修正、畫面文字、主檔資料；不含登入／權限、資料表結構（不寫 DDL）、Personnel & Accounts 的資料。分批進行：先寫入 Alpha 檔案並驗證，給你看過、你同意才部署，部署後實測並更新上表的雜湊。

| 批次 | Alpha 版本 | 內容 | 驗證 |
|---|---|---|---|
| 1 | v54（2026-09-29） | Fixed Clause 依 Class、LMA3333 標題；`api/master-data.js`、`lib/case-draft.js`、`public/app.js`、`public/index.html`、`migrations/0034`（只改資料：58 條 → Property、LMA3333 主檔標題，含 Snapshot；Alpha 的 Audit 仍暫停） | 新 `case-draft.js` 與 VM 差異測試 69,272 組全部一致（不需任何替換）；新 `masterPayload` 與 VM 的 `validate_payload` 4,000 組隨機輸入全部一致（過程中把 VM 對齊 Alpha：`fixedClauses`／`ratings` 為 null 時回錯誤、Class id 84.0 視為整數 84）；migration 在臨時 PostgreSQL 試跑兩次（第二次無變動）；部署後以唯讀 SQL、`run_function` 確認資料與 API，畫面由你實測 |
| 2 | v55（2026-09-29） | 理賠：出險日與付款日期必須是真實日期、準備金看不懂或為負回 400、準備金與付款金額進位到分、交易編號用根案件 TW Ref、每次寫入補 Snapshot；`api/claims.js`、`public/index.html`（兩個日期必填標示與說明文字） | 三個新檢查函式與 VM 差異測試 3,000 組全部一致（年份 1–99 以 `setUTCFullYear` 避開 `Date.UTC` 的 1900 位移）；修改後的 Alpha `claims.js` 以模擬資料庫與 Alpha 真的 `lib/accounting.js` 跑 10 個步驟，回應、最終理賠與交易、版本號與 VM 完全相同；部署後 GET／POST 找不到案件回 404（Alpha 目前沒有案件，寫入流程待有案件時實測）；VM 的案件模板改由 v55 產生、內容不變（原本 3 處替換已移除） |
| 3 | v56（2026-09-29） | 記帳：帳本讀全部案件、記付款／沖銷只接受 Announced／Confirmed（409 `accounting_status_locked`）、付款與沖銷日期必須是真實日期（沖銷沒給日期用台北今天）、非物件的 paymentEntries／transactions 略過、記付款／沖銷補 Snapshot；畫面的付款／沖銷日期預設台北今天、「Partial payment」只在部分付款時顯示；`api/accounting.js`、`public/app.js`、`public/index.html` | 帳本差異測試改以 Alpha v56 的節錄為基準（`qa/alpha_js/excerpts/accounting-excerpts.js`，多切 `isObject`），600 組全部一致，並加入非物件 paymentEntries 的向量（226 組；其中 50 組兩邊都因向量裡其他無效日期拋錯，拿掉非物件項目後仍拋錯，與本批無關）；修改後的 Alpha `accounting.js` 以模擬資料庫跑 11 個步驟（含 Draft、重複沖銷、夾 null、無日期沖銷），回應、付款紀錄、版本號、Snapshot 與 VM 完全相同；部署後 GET 帳本、POST 錯誤日期／無日期實測 |
| 4a | v57（2026-09-29） | Dashboard：今天／本月／今年與 Announce 月用台北時間、每月佣金趨勢與再保人占比用 Production 規則（`lib/production-report.js` 的 `installmentAllocations` 加 export 共用）、占比長條 `display:block`；業績目標：`dashboardConsumption` true、同時新增同一期間回 409、預設年月用台北時間、頁面標題（Audit 那句保留 Alpha 原文，因 Alpha 的 Audit 仍暫停）；`api/dashboard.js`、`api/dashboard-targets.js`、`lib/production-report.js`、`public/app.js`、`public/index.html`。VM 的 `dashboard.read.all`（Finance 看全部）屬權限，不同步 | Dashboard 差異測試改以 Alpha v57 節錄對 VM API 實際模式（台北＋Production 規則，`compare.py` 的 `_dashboard_vm`），600 組全部一致；向量加入批單建立時間與跨台北／UTC 月界的時間；換回 v56 節錄時 306 組不一致（確認測試有鑑別力）；部署後 GET Dashboard／目標、重複期間 POST 回 409 實測 |
| 4b | v58（2026-09-29） | Production Report：業績月份用台北時間（Announce／建立時間先換成台北時間文字）、Production 畫面預設台北的上個月、關帳時待沖銷又有空交易項目回 409 `transactions_corrupt`、關帳的每個案件（`production_case_confirmed`）與鎖定的匯率（`fx_rate_locked`）寫 Snapshot；`api/production-report.js`、`public/app.js`。VM 額外的 Audit（排除、產生版本、案件、匯率鎖定）未同步（Alpha 的 Audit 暫停） | 關帳整理的差異測試改以 Alpha v58 節錄（外殼的 `res.json` 會拋錯，讓 409 與 VM 的例外一樣算出錯），600 組全部一致；原本沒有「待沖銷＋空交易」的向量，已補上（6 組兩邊擋下、12 組不會走到沖銷、52 組非物件項目照常處理）；匯率鎖定＋Snapshot 的 SQL 在臨時 PostgreSQL 試跑（只鎖未鎖的、第二次無變動）；部署後 GET 預覽實測 |
| 5a | v59（2026-09-29） | 流程：TW Reference 流水號不截斷（`lpad` 改為 `greatest(最小位數, 實際位數)`；原本第 1000 號變成「…100」重複）、Reverse 遇到空交易項目回 409 `transactions_corrupt`、Reverse 與通知會計補 Snapshot（`case_reversed`、`accounting_notified`）、「Correct reversed case」能打開表單（後端原本就支援 `reverseCorrectionConfirmed`）；`api/case-announce.js`、`api/case-workflow.js`、`public/app.js` | 新舊編號 SQL 在臨時 PostgreSQL 實測（舊的 1000→100、E100→E10；新的與 VM `zfill` 相同）；修改後的 `case-workflow.js` 以模擬資料庫跑 Reverse（空項目 409 且不寫入、正常 Reverse 的 Snapshot）與通知會計；差異測試的節錄不受影響（檢查放在資料整理之前）；部署後兩個 API 找不到案件回 404 實測 |
| 5b | v60（2026-09-29） | 案件合計統一用記帳的逐步進位：`api/cases.js` 的 `listFinancials` 改用 `lib/accounting.js` 的 `calcLegsForReinsurer`、`public/case-calculations.js` 的金額改成相同算法（非金額合計不變），合計再進位一次；Performance Split 只給名字而同名者不只一位時拒絕（`invalid_personnel_split`，要求以 ID 指定） | VM 的 3,000 個隨機案件：Alpha 新版畫面合計（10 欄）與列表合計都與 VM 完全相同，5,705 筆再保人明細與 Alpha 記帳算法逐筆相同；換回舊版時 1,480／1,599 個案件不同（測試有鑑別力）；Performance Split 四種情況與 VM 相同；部署後 GET 案件列表實測 |
| 5c | v61（2026-09-29） | 回收桶：丟棄與還原補 Snapshot（`draft_recycled`、`draft_restored`，內容是更新後整列案件 `to_jsonb(c)`）；Personnel：停用者／時間只在「在職 → 停用」時記錄（之後編輯不覆寫、重新啟用清空）、Audit 的 before 改成與 after 相同的 11 個欄位；`api/draft-recycle-bin.js`、`api/personnel.js`（只改程式行為，不動人員資料） | 停用時間的 SQL 在臨時 PostgreSQL 跑「停用 → 停用中編輯 → 重新啟用 → 再停用」四步驟、回收桶 Snapshot 的 SQL 試跑；before 欄位與 VM 的 `personnel_state` 核對相同（Alpha 的 Audit 仍暫停）；部署後 GET 回收桶、PUT 不存在的人員回 404 實測 |
| 6 | v62（2026-09-29） | 提醒信與提醒紀錄裡缺 Signed Slip 的再保人顯示案件上的原始名稱（`displayNames`）；文件 fileId 去掉「-」後不是 32 位十六進位就回 404（`canonicalFileId`，原本在 PostgreSQL 轉型出錯）；下載時檔案本體不見回 404 `file_content_missing`（只攔 Hatchable 的 `storage/get 404`，其他錯誤照常拋出）；`api/signed-slip-reminders.js`、`api/case-documents.js` | 兩個新函式與 VM 差異測試：fileId 3,000 組（400／404／UUID 各 622／697／1,681）、再保人名稱 2,000 組全部一致；以唯讀 `run_code` 確認 Hatchable 缺檔時拋 `storage/get 404`；部署後文件 API 實測 |
| 7 | v63（2026-10-05；VM 先於 2026-09-29 部署） | 分期案件每關一期 Production 月報，就產生「該期」的保費交易（SoA／Transactions）：該期所有 Production key 都確認才產生、每期只產生一次；金額是每個再保人的 Leg 1／2 依分期權重拆開（與付款排程同一個 `allocate`，所以 SoA 的 Leg 2 與 Accounting 各期應付金額相同，最後一期拿尾差），Leg 3 = 該期 Leg 1 − Leg 2；編號加 `-I{n}`（例如 `TW…-R1-TX1a-I1`，有 Reverse 週期再加 `-C{n}`）、文字加「· Installment {月份}」、交易帶 `installmentId`／`installmentLabel`；SoA 的結清狀態只看該期的付款排程項目；沒有分期的案件、舊的整案全額交易（沒有 `installmentId`）維持原樣不重複產生；`confirmedCases`（畫面「fully Confirmed」件數）仍是「這次變成全部確認」的案件數；SoA 空表格的提示文字；`lib/accounting.js`、`lib/payment-terms.js`、`lib/production-report.js`、`api/production-report.js`、`public/index.html` | Alpha 新版 JavaScript 與 VM 的 Python 差異測試約 18 萬組全部一致（含新函式 `premiumInstallmentPlan`、`buildPremiumTransactions` 的分期參數、`deriveLedgerSettlement` 的 `installmentId`、`productionConfirmCase` 以「期」為單位確認的情境；其中 266／600 組產生了分期交易、110 組仍是部分確認）；`production_api` 測試組 82 項、新測試組 `backfill_installment_transactions` 9 項；故意破壞（回到舊規則、結清狀態不分期、重複產生、金額不拆）都被抓到；畫面測試全部階段（178 項）通過；部署後 `list_files` 核對 5 個檔案雜湊與預期相同（Alpha 目前沒有案件，關帳路徑用上述差異測試與模擬資料驗證） |

**同步完成**：第 1～7 批都已部署（Alpha v54～v63；第 7 批是 2026-09-29 同事測試 VM 發現分期案件的 SoA 是空的而追加）。**尚未決定**：VM 的「文件只有 Draft 能刪」（本表之外的業務規則）要不要同步回 Alpha。

## 資料（不是程式碼）

| Alpha 來源 | VM 作法 |
|---|---|
| 主檔 74、人員 23、匯率 7（含 `0020`、`0022`–`0025` 產生的資料） | 2026-09-25 以 `import_alpha_reference` 一次匯入，內容雜湊對帳一致；`backfill_audit_baseline` 補上 snapshot 與 Audit 事件。不含 email、不含任何帳號 |
| 切換時的全部業務資料（案件、文件、回收桶、Production、目標、流水號；主檔／人員／匯率對到或新增） | `import_alpha_cutover`（`backend/conversion/`，含 `0018` 的轉換批次表）。**已用合成資料演練通過**（`qa/conversion/rehearse.sh`，見下方「切換（資料轉換）」）；從 Alpha 匯出真實資料與檔案的方法尚未決定 |
| `ri_payment_alerts`、`ri_signed_slip_alerts`（提醒信紀錄） | VM 已有這兩張表（2026-09-26），但**轉換程式還沒匯入**：切換時原始內容仍存在轉換批次的 item（status = excluded），之後依批次的案件對照匯入（待做） |
| `0026` 暫停 Audit 的 trigger、`0027`、`0028` | **不移植**（VM 不暫停 Audit；0027／0028 是 Alpha 內部資料修正） |

## 尚未開始

`api/data-reconciliation.js`、`api/foundation-status.js`。Alpha 前端原檔的逐位元組副本在 `frontend/alpha-reference/`。

不需要移植：`hatchable.toml`、`public/vendor/*`（前端改用 npm 套件，見「固定技術規格」）、`AGENTS.md`、`README.md`。

## 刻意與 Alpha 不同

| 項目 | Alpha | VM | 原因 |
|---|---|---|---|
| Audit 寫入 | 以 trigger `ri_audit_writes_paused` 暫停 | 全面啟用；`AUDIT_LOG_ENABLED=false` 時直接拒絕寫入 | MIGRATION-VM-NOTES：搬到 VM 才啟用，不沿用暫停 |
| Audit 不可變 | 只靠程式不去改 | 三層：應用層 model 拒絕、資料庫 trigger（連 root 也擋）、`ri_runtime` 只有 SELECT／INSERT | 「任何角色都不得修改或刪除」 |
| FX 稽核 | 只寫 snapshot，沒有 Audit 事件 | 每筆匯率新增／修改都有 `create_fx_rate`／`update_fx_rate` | 「每一次新增與修改都要有 Audit」；建議 Alpha 也補上 |
| 專案協作者路徑（#13） | Hatchable 協作者可自動成為 admin | 不存在；所有人都必須是綁定 Personnel 的 Django 帳號 | VM 沒有這個概念 |
| 資料庫帳號 | 單一 | `ri_app`（維護：migrate、DDL）與 `ri_runtime`（網站：最小權限，多數表無 DELETE） | 案件與主檔永不實體刪除，在資料庫層落實 |
| 稽核事件 | 無帳號事件 | 帳號建立／停用／重設密碼都會記錄（不含密碼） | VM 才有登入 |
| 帳號管理 | 尚無（Alpha 的登入由 Hatchable 代管） | 管理員畫面與 API（`/api/personnel-accounts`，需 `accounts.manage`）＋同樣邏輯的 CLI 指令，共用 `personnel/accounts.py`。初始密碼可由管理員指定（須通過 Django 密碼規則，不回傳、不進 Audit；Audit 只記 `passwordSource`），留空則由系統產生並只顯示一次；不能停用或重設自己；不能停用最後一位啟用中的管理員 | VM 才有登入 |
| 案件合計（列表、畫面、記帳）（**已同步回 Alpha v60**，兩邊相同） | 三套算法：記帳（`accounting.js`）每步進位到分；案件列表（`cases.js listFinancials`）與畫面（`case-calculations.js`）完全不進位 | **統一用記帳那套**（逐步進位）：`cases/calc/totals.py`。列表、畫面、記帳三處數字相同 | 2026-09-25 你的決定。與 Alpha 未進位算法的差距在分以下；4000 組隨機案件（最多 6 家再保人）實測最大差距：Brokerage 0.06、Leg 1 0.05、Leg 2 0.04。**建議 Alpha 也統一，否則之後兩邊列表數字會有幾分錢的出入** |
| 案件預設負責人 | 找不到登入者對應時退回固定人員 `P.L`（Hatchable 協作者路徑） | 只用「目前登入者」（已確認在職） | 2026-09-25 你的決定；VM 沒有協作者的概念 |
| 案件 API 的數字型別 | 列表的 `id`、`rowVersion` 是字串（bigint），單筆的 `rowVersion` 是數字 | `id`、`rowVersion` 一律是數字 | Alpha 不一致；前端以數字比對較不易出錯 |
| 案件付款條件鎖定（Announce 後） | 比對 `JSON.stringify` 的結果，物件鍵的順序不同也算變動（資料庫會重排 JSON 鍵的順序） | 比對內容，鍵的順序不算變動；內容有任何差異仍然擋下 | 避免因為資料庫重排鍵而誤擋；不會放行任何真正的變更。**尚未拿 Alpha 實測過它是否真的會誤擋，只是依 JSON 語意推論** |
| 主檔名稱比對（案件的 AE／Reinsured／Class 對應） | `lower(name) = lower(x)`（區分重音） | 同樣精確比對（資料庫 ai_ci 先縮小範圍，再用 Python 精確比對） | MySQL 的 ai_ci 會把 `Café` 與 `Cafe` 視為相同，不能直接用 |
| Performance Split 只給名字、且同名者不只一位（**已同步回 Alpha v60**，兩邊相同） | 取到哪一位取決於資料庫回傳順序（不確定） | 拒絕（`invalid_personnel_split`），要求以 ID 指定 | 不同部門可以有同名的人（例如兩位 A.L）；不猜 |
| 首次登入強制改密碼 | 無（Alpha 的登入由 Hatchable 代管） | 管理員建立帳號、重設密碼、重新啟用帳號之後，本人第一次登入必須先改密碼（`personnel.must_change_password`）。後端在授權層直接拒絕所有業務 API（`403 PASSWORD_CHANGE_REQUIRED`），只放行登入／登出／app-context／改密碼；新密碼不能與暫時密碼相同。principal 多一個 `mustChangePassword` 欄位。既有帳號不受影響（預設 false） | 2026-09-25 你的決定 |
| 重新啟用停用的帳號 | 無 | `POST /api/personnel-accounts/enable`、`manage.py enable_ri_account`、Personnel 頁「重新啟用帳號」。沿用原密碼、不發新密碼，但**一律要求第一次登入先改密碼**（帳號可能是因疑似外洩才被停用）；人員本身若已停用（在職狀態）不能啟用帳號。有 Audit（`enable_account`）與 Snapshot | 2026-09-25 你的決定；「啟用後須改密碼」是我加的保守預設，可改 |
| 角色權限矩陣 | `lib/authorization.js` 的 ROLE_PERMISSIONS | 2026-09-27 依你的決定調整（`backend/ri_system/authz.py`）：**General Manager** 的案件功能與 Reinsurance Staff 相同（新增／編輯、Announce、批單等流程、上傳文件、理賠），保留人員檢視與業績目標；**Audit Log 只有 System Administrator**（GM 拿掉）；**Finance Staff／Finance Manager** 可以看 Dashboard（全部案件），但仍然不能開 Account List 與案件明細；**Reinsurance Staff、General Manager** 可以看 Accounting 帳本（唯讀，不能記付款、沖銷）。新增 VM 權限 `dashboard.read.all`（Dashboard 顯示全部案件；Case Viewer 沒有，只看自己的案件）。權限矩陣測試 `auth_permissions` 逐角色檢查 | 2026-09-27 你的決定；**Alpha 要不要同步由你決定** |
| 忘記密碼 | 無（登入由 Hatchable 代管） | 登入頁「Forgot password?」→ 輸入帳號或 e-mail → 寄出重設連結（1 小時內有效、只能用一次；帳號之後又登入過也會失效）→ 設定新密碼（規則同 Change password）→ 結束該帳號其他所有登入、清除「必須改密碼」。不論帳號存不存在都回同一句話；只寄給在職、帳號啟用、Personnel 有 e-mail 的人；申請與設定都有次數限制；Audit：`request_password_reset`、`reset_own_password`（不含密碼與連結）。**寄信啟用前（SMTP 未決定）登入頁不顯示入口**，API 回 503。程式在 `backend/ri_system/password_reset.py`；測試組 `password_reset`（27 項）、畫面測試階段 P1／P2 | 2026-09-27 你的決定 |
| System status 畫面與 `/health/` | 無（VM 才有） | 只有 System Administrator 能看（`foundation.read`，與 Alpha foundation-status 同一個權限）：後端 `/health/` 未登入 401、其他角色 403；前端路由同樣擋下並導回首頁。沒有任何可用頁面的角色改顯示「No access」頁（以前會導到 System status） | 2026-09-26 你的決定（原本 `/health/` 不用登入、畫面任何登入者都能開） |
| 資料檢視（Django admin `/admin/`） | 無 | 唯讀，只有 System Administrator 進得去（在職、帳號啟用、已完成改密碼）。登入沿用 SPA 的同一個 session（`/admin/login/` 導向 SPA 登入頁）。唯讀三層：站點層拒絕除登出外的所有非 GET 請求、每個 ModelAdmin 沒有新增／修改／刪除權限、站點只接受唯讀的 admin 註冊（Django 內建的 User／Group 含密碼雜湊，不會出現）。可檢視 Case、CaseDocument、ReferenceSequence、Personnel、MasterRecord、FxRate、AuditLog、EntitySnapshot。靜態檔建置時 `collectstatic`，由 Nginx 提供（不增加任何套件） | 2026-09-25 你的決定（先前記錄的「唯讀、僅 admin」）。程式在 `ri_system/admin_site.py`；測試組 `admin_readonly`（67 項），13 種故意破壞都被抓到 |
| Reverse、通知會計的 Snapshot（**已同步回 Alpha v59**，兩邊相同） | 只寫 Audit（`row_version` 加 1 卻沒有 Snapshot，版本號有缺口） | 補寫 Snapshot（`case_reversed`、`accounting_notified`） | 2026-09-25 你的決定；建議 Alpha 也補 |
| TW Reference 流水號（**已同步回 Alpha v59**，兩邊相同） | `lpad(…, 3)`：超過 999 會被截斷而產生重複編號 | 不截斷（第 1000 號就是 4 位） | 2026-09-25 你的決定 |
| 案件鏈的並行控制 | PostgreSQL advisory lock ＋ 事後「除以零」檢查 | 先鎖「根案件」那一列，檢查與寫入在同一個鎖內（Announce 鎖該案件列） | MySQL 沒有 advisory lock 的對應用法；行為相同（同時送出的請求依序處理） |
| Reverse 遇到 `transactions` 內有 `null`（**已同步回 Alpha v59**，兩邊相同） | 拋 TypeError（未處理的伺服器錯誤） | 409 `transactions_corrupt`，不改任何資料 | 2026-09-25 你的決定（差異測試發現）；正常流程不會寫出 null |
| Announce 之後的 `payload.status` | 資料庫的 `status` 變 `posted`，但 `payload.status` 維持 `draft`（下一次編輯才更新）；Alpha 的 API 與 lib 都沒有讀 `payload.status` | 同 Alpha（照搬） | 只是不一致，沒有已知影響；前端若要讀狀態請用欄位 `status` |
| 對 `/api/case-announce` 發 GET | 405 | 403（權限檢查在方法分派之前） | 兩者都是拒絕 |
| 案件文件單檔上限 | 5 MB | **10 MB**（資料表 CHECK 約束也改為 10 MB：`cases/migrations/0002`） | 2026-09-25 你的決定。Nginx 請求上限 20 MB（10 MB 檔案的 base64 約 14 MB）、Django `DATA_UPLOAD_MAX_MEMORY_SIZE` 16 MB |
| 案件文件的檔案本體 | Hatchable storage | Docker volume `case_documents`（容器內 `/data/documents`），路徑即 `storage_key`；先寫暫存檔再原子 rename；路徑限制在根目錄內 | 2026-09-25 你的決定。**不在 MySQL 備份裡，要另外備份**（見「維運」） |
| 刪除案件文件 | 任何狀態都能實體刪除（連同檔案） | **只有 Draft 能刪**；Announce 之後回 409 `document_delete_locked`，只能取消勾選，檔案保留作為證據 | 2026-09-25 你的決定 |
| `signedSlipReminder.outboundEnabled` | 固定 `true` | 依設定 `RI_REMINDER_EMAIL_ENABLED`（舊名 `RI_SIGNED_SLIP_OUTBOUND_ENABLED` 仍可用），預設 `false`（VM 尚未設定寄信） | 2026-09-25 你的決定：如實回報 |
| 提醒信的寄送 | Hatchable `email.send` | **不寄信模式**（SMTP 未決定）：提醒照常產生、佔位、防重複，但記成 `suppressed`（VM 才有的狀態，算「已提醒」，與 `sent`／`simulated` 相同），並寫 Audit `suppress_signed_slip_reminder`／`suppress_payment_reminder`。收件人有測試網域時仍先記 `simulated`（同 Alpha）。之後設定 `RI_EMAIL_*` 並把 `RI_REMINDER_EMAIL_ENABLED` 設為 true 就會真的寄（Django SMTP；已用測試郵件後端驗證寄出、失敗、重試）。測試期間的提醒不會補寄 | 2026-09-26 你的決定 |
| 分期案件的保費交易何時產生（**已同步回 Alpha v63**，兩邊相同） | 所有期別的 Production key 都確認、案件變 Confirmed 時，一次產生整個案件全額的 Leg 1–3；中間幾期關帳後 SoA 一直是空的 | 每一期的所有 key 都確認就產生該期交易（依該期比例，每期一次）；案件仍要全部期別確認才變 Confirmed | 2026-09-29 你的決定（同事測試：Announced、關了 9 月月報、SoA 沒東西，但 Claim 付款會立刻出現）。既有案件以 `manage.py backfill_installment_transactions`（預設 dry-run，`--apply` 才寫入）補上；`TWPF2609001` 的 9 月那期已於 2026-09-29 補上（備份 `backups/ri_system_before_installment_tx_20260929_164440.sql`） |
| 提醒排程 | Hatchable scheduler（UTC 01:00／01:30），每次最多 10 件，一分鐘後接著跑 | 主機 cron 台北 09:00／09:30（`scripts/install_reminder_cron.sh`），一次處理完，`moreWork` 一律 false；結果附加到 `logs/reminders.log` | Hatchable 的限制在 VM 不存在 |
| 提醒紀錄的內容 | 只存收件人與狀態 | 另存產生當下的信件主旨與內文（`subject`、`body_html`、`body_text`） | 2026-09-26 你的決定：案件明細預覽「當天會寄出的原文」 |
| 查看提醒紀錄 | 沒有畫面（只有資料表與 Audit） | 案件明細新增「Reminders」分頁（`GET /api/case-reminders`，看得到案件的人就能看）：兩種提醒的紀錄、設定錯誤（來自 Audit）、信件預覽（沙箱 iframe）；兩張表也加進唯讀的 `/admin/` | 2026-09-26 你的決定：放在案件明細 |
| 提醒信的連結 | 「開啟 RI System (Alpha)」→ ri-system-alpha.hatchable.site | 「開啟 Reinsurance Department System」→ `RI_REMINDER_LINK_URL`（`http://ri-dev.tw-insure.com`） | 2026-09-26 你的決定；其餘主旨與內文逐字同 Alpha |
| Signed Slip 提醒裡缺文件的再保人名稱（**已同步回 Alpha v62**，兩邊相同） | 顯示比對用的鍵值（去空白、全小寫，例如「ui re beta (facility)」） | 信件、提醒紀錄與 Reminders 分頁顯示案件上的原始名稱（「UI Re Beta (Facility)」）；判斷哪幾家缺文件的邏輯不變 | 2026-09-26 你的決定（疑似 Alpha 的小問題）；**建議 Alpha 也修** |
| 提醒紀錄的 status 約束 | `ri_payment_alerts.status` 沒有 CHECK | 兩張表都有 CHECK（pending／sent／simulated／suppressed／failed） | |
| 下載時檔案本體不見（**已同步回 Alpha v62**，兩邊相同） | 未處理的錯誤 | 404 `file_content_missing`（並寫入錯誤日誌） | 不應該發生；發生時要能看出是資料遺失 |
| 檔名含落單的 UTF-16 代理字元（例如 JSON 裡的 `\ud83d`） | Node 寫進 PostgreSQL 時換成 U+FFFD | 同樣換成 U+FFFD 再存（MySQL 不接受落單代理字元） | 結果與 Alpha 相同 |
| 文件 API 的 fileId 是 36 個「-」這類「格式對但不是 UUID」（**已同步回 Alpha v62**，兩邊相同） | PostgreSQL 轉型失敗（未處理的錯誤） | 404 `file_not_found` | |
| Dashboard 占比長條（Mix by Class、Top Reinsurers）（**已同步回 Alpha v57**，兩邊相同） | 填色的 `<i class="mix-fill">` 是行內元素，`height:100%` 無效，長條沒有填色 | 在 `Dashboard.vue` 補 `display:block`（Alpha 的 CSS 檔原樣不動） | 2026-09-26 你的決定（畫面測試截圖發現）；**建議 Alpha 也修** |
| Dashboard 的時間（**已同步回 Alpha v57**，兩邊相同） | 今天／本月／今年與 Announce 月都用 UTC（台北時間月初 8 小時內還是上個月） | 台北時間；目標設定的預設年份／月份也用台北時間 | 2026-09-26 你的決定 |
| Dashboard 的每月佣金趨勢與再保人占比（**已同步回 Alpha v57**，兩邊相同） | 自己另一套算法：分期不先進位、批單用 Announce 月、只去掉「(Facility)」 | 用 Production Report 的規則（分期逐期進位、尾差在第一期；批單用建立月；去掉「(Facility)」與「[Facility]」），與 Production Report 數字一致 | 2026-09-26 你的決定；**建議 Alpha 也統一** |
| 目標設定頁的說明文字（**標題與 `dashboardConsumption` 已同步回 Alpha v57**；說明裡 Audit 的那句兩邊仍不同，因為 Alpha 的 Audit 仍暫停） | 「Dashboard consumption follows later」「Audit recording is paused until VM migration」 | 「Targets feed the Dashboard brokerage trend」「every change is recorded in the Audit Log」；API 的 `scope.dashboardConsumption` 與 Audit metadata 也改為 true | 2026-09-26 你的決定（VM 的實際情況） |
| 同時新增同一期間的目標（**已同步回 Alpha v57**，兩邊相同） | 未處理的資料庫錯誤 | 409 `duplicate_target` | |
| Fixed Clause 依 Class（**已同步回 Alpha v54**，兩邊相同） | v53：只有再保人有 Fixed Clause，案件帶入所選再保人的全部條款，與 Class 無關 | 再保人的每條 Fixed Clause 可指定適用 Class（payload `fixedClauses[].classIds`＝Class 主檔 id；沒有這個鍵＝All classes，格式與 Alpha 相同；MDM 新增條款時預設 Property）；Class 主檔也可以有自己的 `fixedClauses`（沒有條款時 payload 維持 `{}`）。案件條款＝Universal＋該 Class 的條款＋各再保人適用該 Class 的條款＋手動；全部是 Facility 的案件也帶入 Class 條款；Draft 改 Class 時會重新帶入（Alpha 改 Class 不會觸發）；已存檔的案件不會被改寫。MDM Clauses 分頁的 Used by 會列出 Class 與適用範圍。測試組 `fixed_clause_classes`（28 項；8 種故意破壞全部抓到）、畫面測試階段 K。既有資料：2026-09-29 依你的決定，5 家啟用中再保人的 58 條全部改為只適用 Property（CLI 執行，每家各一筆 Snapshot 與 `update_master` Audit，`source = maintenance`）；停用中的測試再保人 Munich 未改 | 2026-09-29 你的決定：目前的 Fixed Clause 只用於 Property，Universal 不變 |
| Universal 條款 LMA3333 的標題（**已同步回 Alpha v54**，兩邊相同） | v53：`Reinsurers Liability Clause` | `LMA3333 Reinsurers Liability Clause`（`cases/draft.py` 的 `LMA3333_TITLE`、`frontend/src/alpha/constants.js`、Clause 主檔 id 93 以 CLI 更新並留 Snapshot／Audit）。文件的 Reinsurance Conditions 只印條款標題（Word／PDF 產生檔與 Alpha 相同，未修改），所以文件上會印出「• LMA3333 Reinsurers Liability Clause」。差異測試：`qa/calc/compare.py` 的 `vm_divergence` 先把 Alpha 結果的舊標題換成新標題再比對；關掉這個對應時 normalizeDraft 有 2,992 組只差在這個標題。畫面測試階段 H 檢查 Cover Note PDF 印出新標題 | 2026-09-29 你的決定 |
| 業績月份（Announce 月／批單建立月）（**已同步回 Alpha v58**，兩邊相同） | 取時間的 UTC 文字前 7 個字：台北時間每月 1 日早上 8 點前 Announce 的案件算上個月 | 先換成台北時間再取月份（calc 本身不變，只改傳入的文字）；Production 畫面的預設月份也用台北時間的上個月 | 2026-09-26 你的決定（先在 Alpha 以唯讀 `SELECT now()` 確認 Hatchable 回傳 UTC 文字）；**建議 Alpha 也改** |
| Production 的 Audit（**關帳的案件與匯率 Snapshot 已同步回 Alpha v58**；額外的 Audit 事件未同步，因 Alpha 的 Audit 仍暫停） | 只有關帳寫 Audit | 排除（`exclude_production_row`）、產生版本（`generate_production_report`）也寫；關帳時每個案件補寫 Snapshot（`production_case_confirmed`），被鎖定的匯率寫 Snapshot（`fx_rate_locked`）與 Audit（`lock_fx_rate`） | 依「所有新增與修改都要有 Audit」、「row_version 增加就寫 Snapshot」 |
| 關帳的並行控制 | 事後以「除以零」檢查報表與每個案件的版本 | 先鎖報表與案件列，再檢查版本與狀態；有變動就 409 `close_conflict`，什麼都不寫 | 行為相同 |
| 關帳時 transactions 裡有 null（**已同步回 Alpha v58**，兩邊相同） | 拋 TypeError（未處理的錯誤） | 409 `transactions_corrupt`，什麼都不寫 | 同 Reverse 的決定 |
| 預覽的案件順序 | PostgreSQL `ORDER BY announced_at`（空值排最後） | 明確指定空值排最後（MySQL 預設排最前） | 結果相同 |
| Production 排除紀錄 | 程式不修改、不刪除 | 資料庫層也禁止：`ri_runtime` 只有 SELECT／INSERT | 排除會改變業績歸屬，保留完整紀錄 |
| 理賠交易編號（**已同步回 Alpha v55**，兩邊相同） | `${rootCase.twRef}-CLM…`，但傳入的是 payload，沒有 `twRef`，編號開頭是 `undefined`（例如 `undefined-CLM1-P1-R1-TX1`），會出現在 SOA 與 Accounting | 用根案件的 TW Ref（`TWPAR2603001-CLM1-P1-R1-TX1`）；共用的 `build_claim_payment_transactions` 不變，只在呼叫時補上 `twRef` | 2026-09-26 你的決定；**建議 Alpha 也修** |
| 理賠的出險日、付款日期（**已同步回 Alpha v55**，兩邊相同） | 不檢查：可留空，也可以是任何 20 字以內的文字 | **兩者都必填**，且必須是真實存在的日期（400 `invalid_date_of_loss`／`invalid_payment_date`）；畫面加必填標示，「Add claim」的說明改為「Date of Loss is required; the Outstanding Reserve can be updated later.」 | 2026-09-26 你的決定 |
| 理賠準備金與付款金額（**已同步回 Alpha v55**，兩邊相同） | 準備金看不懂的文字安靜地存成 0、可以是負數；金額不進位（100.123 原樣存） | 準備金看不懂的文字回 400 `invalid_claim_reserve`、不可為負（留空仍是 0）；準備金與付款金額都進位到分（進位後是 0 的付款同樣拒絕）。付款**可以是負數**（追償、沖抵，2026-09-25 確認）不變 | 2026-09-26 你的決定 |
| 理賠寫入的 Snapshot 與並行控制（**已同步回 Alpha v55**；並行控制仍各自的寫法） | 只寫 Audit；事後以「除以零」檢查版本 | 補寫 Snapshot（`claim_created`、`claim_reserve_updated`、`claim_payment_recorded`）；先鎖根案件列再檢查與寫入 | 延續 2026-09-25 的決定 |
| 記帳帳本讀取的案件數（**已同步回 Alpha v56**，兩邊相同） | 最多 1000 件（`LIMIT 1000`），其餘直接不顯示、沒有警告 | 全部讀取 | 2026-09-26 你的決定 |
| 記付款、沖銷的案件狀態（**已同步回 Alpha v56**，兩邊相同） | API 不檢查狀態（Draft 也能記；畫面只列 Announced／Confirmed） | 只接受 Announced（posted）／Confirmed（closed），其他回 409 `accounting_status_locked` | 2026-09-26 你的決定 |
| 付款日期（**已同步回 Alpha v56**，兩邊相同） | 記付款只檢查 `YYYY-MM-DD` 的形狀（`2026-13-45` 會通過）；沖銷完全不檢查；預設日期用 UTC 的今天（台灣早上 8 點前是前一天） | 兩者都必須是真實存在的日期（記付款 400 `invalid_payment`、沖銷 400 `invalid_payment_date`）；沖銷沒給日期時與畫面預設都用台北的今天 | 2026-09-26 你的決定；到期日與逾期本來就用台北日期 |
| 記付款、沖銷的 Snapshot（**已同步回 Alpha v56**，兩邊相同） | 只寫 Audit | 補寫 Snapshot（`payment_recorded`、`payment_reversed`） | 延續 2026-09-25「row_version 增加就寫 Snapshot」的決定 |
| 記付款、沖銷的並行控制 | 先比對版本，再以 UPDATE ＋「除以零」事後檢查 | 先鎖案件列，檢查與寫入在同一個鎖內 | 行為相同（版本不符回 409 `version_conflict`） |
| 帳本遇到 `paymentEntries` 裡有 `null`（**已同步回 Alpha v56**，兩邊相同） | 整個帳本拋錯（`entry.scheduleKey`） | 略過非物件的項目 | 正常流程不會寫出 null；不讓一筆壞資料擋住整個帳本 |
| Accounting 表格的「Partial payment」字樣（**已同步回 Alpha v56**，兩邊相同） | `<br v-if="row.partial"><small>Partial payment</small>`：`v-if` 只套到換行，**每一列都顯示** | 只在真的部分付款時顯示 | 2026-09-26 你的決定（畫面測試發現）；**建議 Alpha 也修** |
| Accounting 點 TW Ref 開啟案件 | 同一頁切換到案件的 SOA 分頁 | 導向 `/cases?case=…&tab=soa`，載入後開 SOA 分頁 | VM 每個畫面是一個路由 |
| Accounting 的 `settle` 動作（標記理賠交易已結清） | 前端有 `settleSelectedTransactions()`，但 API 不支援、畫面也沒有入口 | 不移植 | 無法執行的死碼 |
| 文件頁與 Announce 的再保人名稱比對 | 文件頁（與 Signed Slip 提醒）**不**去掉「(Facility)」，Announce 會去掉 | 同 Alpha（照搬） | 兩處規則不同但實務上一致：上傳時只能選案件上的原名。只有同一案件同時有「X」與「X (Facility)」時兩邊的「需要幾家」才會不同。**建議 Alpha 統一** |
| 丟進回收桶、還原的 Snapshot（**已同步回 Alpha v61**，兩邊相同） | 只寫 Audit（`row_version` 加 1 卻沒有 Snapshot） | 補寫 Snapshot（`draft_recycled`、`draft_restored`） | 比照 2026-09-25 你對 Reverse／通知會計的決定（每個版本都要有 Snapshot）；建議 Alpha 也補 |
| 回收桶的並行控制 | 事後「除以零」檢查 | 先鎖案件列（還原時也鎖回收桶那一列），檢查與寫入在同一個鎖內 | MySQL 沒有對應寫法；結果相同 |
| 畫面外觀與語言 | Hatchable 上的單一 HTML＋UMD | 同樣的模板、文字（英文）與 CSS，拆成 Vue 元件並正式建置；左側每一項是一個網址（重新整理、上一頁可用） | 2026-09-25 你的決定：全部照 Alpha 英文、盡量一模一樣 |
| VM 專有的畫面元素 | 無（登入由 Hatchable 代管） | 英文的登入頁、頁首的 Change password／Log out、System Administrator 的 Data viewer（`/admin/`）連結、強制改密碼對話框；Personnel 頁多了登入帳號欄與帳號動作、可重新啟用人員（Alpha 顯示「VM migration only」） | 2026-09-25 你的決定：用英文、與外框一致 |
| 外框的版本條與側欄文字 | 「Alpha · Audit Log paused until VM」等 | 如實描述 VM（Audit 已啟用、哪些畫面還在搬） | 如實回報 |
| 「Correct reversed case」（**已同步回 Alpha v59**，兩邊相同） | 按了沒反應（`startEditCase` 只允許 draft／posted，#7 的確認流程走不到） | 可以用：打開表單，存檔時跳出 #7 的確認，後端也獨立檢查 | 2026-09-25 你的決定（疑似 Alpha 錯誤）；**建議 Alpha 也修** |
| 主檔 API 的 `payload` | 接受 JSON 字串或物件；`null` 是錯誤 | VM 先前的移植只接受物件、`null` 當成沒送；已修正成與 Alpha 相同（`master_payload_compat` 測試組） | 移植時漏掉（Alpha 自己的畫面就是送字串）|
| Case Viewer 打開案件明細 | 呼叫需要 `cases.read.all` 的流程 API，跳出權限錯誤 | 沒有權限時不呼叫（不跳錯誤） | 同樣看不到流程資料，只是不顯示錯誤訊息 |
| 產生 PDF 的引擎 | Hatchable 內建的無頭 Chromium（`browser.pdf`，A4、印背景） | 內部的 Gotenberg 8.37.0（Chromium 152）：關閉 JavaScript、只允許讀它自己的暫存 HTML、擋所有外部與內網網址；A4（8.27 × 11.7 英吋）、邊界 0、印背景 | 2026-09-26 你的決定。Arial 在 Linux 上以字寬相同的 Liberation Sans 呈現、中文用 Noto Sans CJK TC（你的決定）。**2026-09-26 已與 Alpha 實際輸出比對**（你同意後，用你的 Chrome 把一份合成案件的 Cover Note 版面送 Alpha 的 API；兩邊版面輸入雜湊相同）：Alpha 同樣是 Chromium 152（Skia/PDF m152）＋Liberation Sans；5 頁、A4 尺寸、圖片完全相同；**第 1–4 頁內容串流逐位元組相同**；第 5 頁只差在彎引號（’ “ ”）的字形編號（兩邊 Liberation Sans 版本不同，字寬相同、位置相同）與底線裁切框約 0.003 pt 的差距。Alpha 的 PDF 有無障礙標籤（tagged PDF），VM 也加上（Gotenberg `generateTaggedPdf`，2026-09-26 你的決定）：加上後第 1–4 頁連同標籤逐位元組相同 |
| 誰可以產生 PDF | 只要登入（沒有檢查 RI 權限） | 需要 `documents.read`（System Administrator、Sales、General Manager） | 2026-09-26 你的決定 |
| 產生文件的 Audit | 不記錄 | PDF 與 Word 每次產生都寫一筆 `generate_document`（案件、種類、格式、操作者；不存文件內容）。Word 在瀏覽器產生，所以前端下載前先呼叫 `POST /api/document-generation-log` | 2026-09-26 你的決定 |
| PDF 請求的 `kind`、`caseUid` | 只有 Debit Note 會帶；其他種類不需要 | 一律要帶，`kind` 只能是 cover／endorsement／debit，案件必須存在且看得到（400／404） | 為了寫 Audit；VM 的前端每次都會帶 |
| Debit Note 的 Word | 只有前端擋（Draft 不能下載） | 伺服器也檢查（記錄 Word 的 API 對沒有 TW Ref 的案件回 409） | Alpha 的註解自己寫了這個缺口 |
| PDF 的送出方式 | `pdf-generator.js` 的 `generate()` 直接 `fetch` | 用同一份檔案匯出的 `_qa` 版面函式組出相同的 markup，改由 `apiFetch` 送出（VM 需要 CSRF）；原檔不改 | |
| SOA 分頁 | 讀 `payload.transactions` 顯示 | 相同（唯讀；保費交易在 Production 關帳時產生，理賠交易在記理賠付款時產生） | |
| 畫面上的案件合計、分期收入（**已同步回 Alpha v60**，兩邊相同） | `case-calculations.js`（不進位） | `src/alpha/caseCalculations.js`：用 Alpha `lib/accounting.js` 的逐步進位，與後端 `totals.py` 相同（`run_qa.sh totals` 比對 3,000 個案件） | 2026-09-25「統一用記帳算法」的決定 |
| Announce 之後的「Record notification」按鈕 | Announce 後不重新載入流程狀態，要重新打開案件才出現 | 相同（照搬） | 只是不便，沒有錯誤；可以之後一起改 |
| Personnel 停用時間（**已同步回 Alpha v61**，兩邊相同） | 每次儲存都會覆寫 `deactivated_by/at` | 只在「在職 → 停用」那一刻記錄，之後編輯已停用的人不覆寫 | 保留真正的停用時間 |
| Personnel Audit 的 before 內容（**已同步回 Alpha v61**，兩邊相同） | `before_data` 用列表格式（含 `accountBound`、`updatedAt`），`after_data` 用另一種格式 | before 與 after 都用同一種格式（`personnel_state`） | Alpha 兩邊格式不一致，比對差異時不方便 |
| Personnel GET 的 `scope` | `authentication: company_vm_deferred`、`credentialsEnabled: false` | 如實回報：`django_session`、`credentialsEnabled: true`、`rolesEnforced: true` | VM 已啟用登入 |
| Personnel 列表欄位 | 無登入帳號名稱 | `accountUsername`（僅 `accounts.manage` 看得到） | 管理員畫面需要 |
| 停用中帳號換 Email | 解除綁定，可重新邀請 | 解除綁定，可為新 Email 重新建立帳號；舊的 Django 帳號保持停用（`ri_runtime` 沒有 DELETE 權限，也不該刪，稽核仍能對應） | |

## 維運

| 作業 | 指令 |
|---|---|
| 套用 migration（之後一定要重新授權） | `scripts/migrate.sh` |
| **一鍵執行全部驗證**（每次改動後都要跑） | `scripts/run_qa.sh`（可加參數 `suites`／`parity`／`calc` 只跑一部分） |
| 只重新套用資料庫權限與 Audit trigger | `scripts/db_harden.sh` |
| 補上分期案件已確認期別缺少的保費交易（先 dry-run，備份後再 `--apply`） | `docker exec ri-backend python manage.py backfill_installment_transactions [--apply]` |
| 以維護者身分執行 manage.py（需要 DDL 或 DELETE 時） | `scripts/manage_as_owner.sh <指令>` |
| 建立／停用／重新啟用／重設帳號 | `docker exec ri-backend python manage.py create_ri_account\|disable_ri_account\|enable_ri_account\|reset_ri_password --personnel-id N …` |
| 備份案件文件（volume） | `docker exec ri-backend tar czf - -C /data/documents . > backups/case-documents-$(date +%Y%m%d-%H%M%S).tar.gz && chmod 600 backups/case-documents-*.tar.gz`（與 MySQL 備份同時做，兩者才對得起來） |
| 畫面測試（無頭 Chromium） | `scripts/run_ui_test.sh`：另起用完即丟的測試環境（獨立資料庫、合成資料、隨機密鑰），跑完整套刪除；截圖在 `qa/ui/out/`（不進版控）。正式資料庫完全不動 |
| 前端與後端的案件合計一致 | `scripts/run_qa.sh totals`（`all` 也會跑） |
| 切換轉換演練（合成資料、兩套用完即丟的環境） | `qa/conversion/rehearse.sh`（`KEEP=1` 保留工作目錄；`REUSE_WORK=<目錄>` 重用上次環境 A 的匯出，只跑 B） |
| 網址 | 同事使用 **http://ri-dev.tw-insure.com**（公司 DNS 已把這個名稱指向 192.168.1.127；短名 `http://ri-dev` 也可以）；舊網址 `http://192.168.1.127:8080` 繼續可用。Nginx 同時開 80 與 8080 埠；Django 允許的主機名稱在 `compose.yaml` 的 `DJANGO_ALLOWED_HOSTS`。**目前是 HTTP，密碼與資料以明文在區網傳送**（HTTPS 暫緩，見切換前的待辦） |
| 寄信開關 | `RI_EMAIL_ENABLED`（提醒信與忘記密碼共用；舊名 `RI_REMINDER_EMAIL_ENABLED` 仍可用）。啟用前要先設定 `RI_EMAIL_HOST`、`RI_EMAIL_PORT`、`RI_EMAIL_USE_TLS`、`RI_EMAIL_FROM`（SMTP 未決定）。信件裡的連結用 `RI_PUBLIC_BASE_URL`（預設 `http://ri-dev.tw-insure.com`） |
| 提醒排程 | 安裝／更新：`scripts/install_reminder_cron.sh`（`--remove` 移除）；手動執行：`docker exec ri-backend python manage.py run_signed_slip_reminders`（或 `run_payment_reminders`，可加 `--today YYYY-MM-DD` 測試）；結果在 `logs/reminders.log`（不進版控）。**收件人靠人員的 e-mail 與主管 e-mail**：缺了就只記「設定錯誤」（案件明細的 Reminders 分頁看得到） |
| PDF 服務 | `docker compose up -d pdf`；健康檢查 `docker exec ri-backend python -c "import urllib.request;print(urllib.request.urlopen('http://pdf:3000/health').status)"`。沒有資料、不用備份；產生失敗時看 `docker logs ri-pdf` |
| 唯讀資料檢視 | 瀏覽器開 `/admin/`（System Administrator；主畫面上方有「資料檢視（唯讀）」連結）。要新增資料表或 model 時，在該 app 的 `admin.py` 用 `ReadOnlyModelAdmin` 註冊，其他寫法會被忽略 |
| 備份 | `docker exec ri-mysql sh -c 'mysqldump -uroot -p"$(cat /run/secrets/mysql_root_password)" --single-transaction --routines --triggers ri_system' > backups/…sql`（`backups/` 不進版控） |

**新增資料表後一定要跑 `scripts/migrate.sh`**：`ri_runtime` 對新表沒有任何權限，直接跑 `manage.py migrate` 會讓網站對新表失敗。

## 切換（資料轉換）

2026-09-26 的決定：**重新編號**（Alpha 的數字 ID 依對照表全部換成 VM 的 ID）；主檔／人員／匯率用名稱對到 VM 現有資料，
**內容有差異就整批停止並列出差異**；案件等業務表 VM 端**必須是空的**；**登入帳號切換後重新建立**；**Audit／Snapshot 歷史不搬**，
從轉換事件開始（每筆匯入的資料在 VM 寫一份 Snapshot 與一筆 `import_alpha_record` Audit，`source = data_migration`）。

- 需要重新對應的所有位置列在 `backend/conversion/remap.py` 開頭（案件 ID、人員 ID、主檔 ID、`personnel:<id>` 操作者；payload 裡的
  `ownerPersonnelId`、`splitParties[].personnelId`、`accountingNotifications[].accountingPersonnelId`、`confirmedProductionKeys`、
  `paymentEntries[].createdBy`；Production 報表列與排除紀錄的 key；回收桶的案件快照）。數字的型別保持不變（文字的 "12" 還是文字）。
  UUID（案件 `case_uid`、文件、報表 `report_uid`、排除紀錄）不變，文件的 `storage_key` 也不變。
- Production 報表的 `source_signature` 含有列 ID，匯入後用新 ID 重算；Alpha 原本的簽章若與它自己的列不符，會記在批次 item 的 issue。
- 預設 dry-run（整批做完、對帳後回滾，只留一筆 `dry_run` 批次摘要）；`--apply` 才提交；任何一項不符就整批回滾，已寫出的文件檔也刪除。
- 對帳四項：各表筆數；**來回比對**（匯入的每一筆轉回 Alpha 的 ID 後與來源逐欄相同）；參照完整性；財務控制總數（各幣別原始保費、
  交易筆數與金額、未結／已結筆數、文件總位元組、各狀態報表數）；**第五項：獨立完整性檢查**（`backend/conversion/integrity.py`）：
  不用 `remap.py`，自己用 case_uid／姓名／主檔自然鍵重建對照，逐一檢查每個 ID 位置是否換成應有的 VM 值、引用是否存在
  （含回收桶快照的 `id` 必須等於 `original_case_id`、排除紀錄的 key 開頭必須是它自己的案件）；`--apply` 時再檢查每份文件的
  檔案本體在 VM 文件庫、大小與 SHA-256 相同。原因：來回比對正反都用 `remap.py`，漏換的位置正反都漏、會互相抵消
  （2026-09-26 故意破壞測試發現排除紀錄 key、回收桶快照漏換都沒被抓到）。
- 人員的 email 不匯入（沿用 9/25 第一次匯入的規則）；帳號欄位不匯入也不比對。

**演練**（`qa/conversion/rehearse.sh`，約 5 分鐘；只用合成資料，不碰 Alpha、不碰 VM 正式資料庫）：一套測試環境扮演 Alpha，用 API 建出
6 件案件（分績、付款與沖銷、理賠含負數付款、批單、分期、回收桶、Reverse 待沖銷、Production 排除延後＋關帳、下月 valid 報表、目標），
擷取所有畫面 API 輸出後匯出成 Alpha 格式；另一套全新環境先把流水號推開（ID 一定不同），先驗證三種壞檔（主檔內容不同、文件被竄改、
缺文件）都會被擋下、dry-run 不留資料，再正式匯入、確認第二次匯入被拒絕，最後擷取同樣的 API 輸出：**6 件案件與 8 個畫面的輸出逐項相同**；
並在新環境關掉 A 留下的 valid 報表（成功，兩件案件正確變成 Confirmed）。

切換當天的步驟（草案，細節待定）：1) 通知 Alpha 停止寫入；2) 從 Alpha 匯出（**方法待決定**：資料表與 Hatchable storage 的文件檔）；
3) VM 備份 MySQL 與文件 volume；4) 清空 VM 測試資料（見下，先問你）；5) `import_alpha_cutover … --files …` dry-run，看報告；
6) `--apply`；7) 抽查畫面；8) 重新建立登入帳號。

## 切換前的待辦

- **切換匯入的案件仍是舊的 LMA3333 標題**（2026-09-29）：Alpha 案件的 `clauseDetails` 存的是 `Reinsurers Liability Clause`，匯入後產生文件會印舊標題，直到案件重新存檔。切換時要決定：匯入時一併換成新標題（屬於改寫匯入資料，要記在批次報告），或維持原樣。先問你。
- **轉換程式要換掉條款裡的 Class id**（2026-09-29，同步回 Alpha 時發現）：再保人條款的 `payload.fixedClauses[].classIds` 存的是 Class 主檔的 id，Alpha 的 Property 是 45、VM 是 92。`backend/conversion/remap.py` 目前沒有這個位置：主檔用名稱比對時會因 id 不同而判定內容不一致（整批停止），Alpha 新建的再保人匯入後也會指向錯的 Class。要在 remap.py 與獨立檢查 integrity.py 加上這個位置（Class id 依對照表換成 VM 的 id），並用合成資料演練與故意破壞驗證。LMA3333 標題、Class 的 `fixedClauses` 兩邊已相同（v54），不再造成差異。
- **清空測試資料**（2026-09-25 你的決定）：在 VM 上點畫面建立的測試案件（名稱用 ZZ 或 UI 開頭）、文件、回收桶、TW Reference 流水號，要在正式匯入前用一支有記錄、需要 root 執行的腳本清掉（Audit 保留）。執行前先備份並問你。


## 2026-10-05：VM 高優先度 Bug 修正（Owner 已確認規則）
- Production 關帳、產生報表、排除與匯率存檔共用 MySQL 月份操作鎖。遇到同月份操作衝突，立即回 409 operation_busy，提示稍後重試，不等待。
- 匯率或來源變動後拒絕關帳，要求重新預覽並產生報表；關帳交易內再次核對匯率集合、數值及版本，衝突整筆回滾。
- 排除業績自動跳過已關帳月份，延到第一個未關帳月份；來源、目的月份均保護到提交完成。
- 帳號停用、降權及人員離職共用 ri_operation_locks 的 admin_accounts 交易鎖；第一筆可完成，移除最後啟用管理員的另一筆拒絕。
- 新 migration coordination.0001_initial；ri_runtime 對新鎖表僅 SELECT、INSERT、UPDATE。
- Audit 仍暫停直至另行通知。此次僅修高優先度項目；兩個中優先度 Bug 依 Owner 決定另行安排，尚未修正。未同步修改 Hatchable Alpha。
- 並行回歸測試只可執行於隔離測試資料庫，因測試需提交資料讓其他連線可見；不可在正式 VM 資料庫執行。


## 2026-10-06：VM 中優先度 Bug 修正（Owner 已確認小數處理規則）
- 付款先沿用既有 money() 四捨五入至兩位小數，再檢查實際存入金額必須大於 0。拒絕零金額，不新增付款、Snapshot 或版本；超額付款也使用實際存入金額判斷。
- 主檔新增／更新、匯率、登入及改密碼先確認請求是物件。非物件 JSON 回 400 invalid_body；保留既有認證、CSRF、權限及限流。
- 匯率逐項檢查物件，NaN／sNaN／Infinity 等非有限值回 400；版本數字溢位回 400。儲存前四捨五入至六位小數，結果為 0 時拒絕，回應及 Snapshot 與資料庫數值一致。
- 主檔評等清單拒絕非物件項目；主檔 id／rowVersion 溢位回 400。
- 無新增 migration。原有高優先度交易鎖及 Audit 暫停規則維持；未同步修改 Hatchable Alpha。
- 回歸測試 input_validation.py 在交易內執行並回滾，不留下測試資料。


## 2026-10-06：補充 Bug 修正（依 Owner 指定順序與規則）
- 關帳提交前在 production_sources 交易鎖內重讀完整預覽；案件公告、編輯、理賠、付款與工作流程寫入先取得同一保護。案件可先完成；來源有變動則拒絕關帳並要求重新產生報表。
- 公告的業績月份已關帳時，自動建立排除紀錄延到第一個未關帳月份，保留原保單日期與金額；支援分期、跨年與連續關帳月份，前端提示延後月份。
- 匯率新增／修改以 closed 報表判定月份鎖定，無匯率列的已關帳月份也拒絕寫入。
- 理賠準備金及付款在既有兩位小數四捨五入後再驗證有限值；保留負數沖抵及合法零準備金，避免空值／零交易。
- 密碼重設在管理員操作保護及使用者列鎖內重新檢查 token、啟用狀態及 Personnel 資格；同一 token 並行僅一筆成功。
- Alpha 匯入先建立完整主檔對照，再轉換 fixedClauses[].classIds；匹配既有主檔與反向對帳使用轉換後範圍，獨立完整性檢查拒絕漏轉、錯誤 Class 及非 Class 引用。
- 無 migration；Audit 維持暫停。本次沒有執行正式 Alpha 匯入。


## 2026-10-06：忘記密碼完整流程檢查與修正
- 含 @ 的合法帳號先以帳號名稱辨識，再嘗試 Personnel e-mail。
- 遺失、非數字或超大 auth_user_id 不再造成 500；已停用 Django User 不寄信。
- 申請／重設要求 JSON 物件及字串欄位，拒絕把陣列轉成新密碼。
- 申請／重設使用單一表單提交並防止重複送出；重設後下次導航重讀登入狀態。
- Nginx access log 遮蔽重設連結及 Referer 中的 token；SPA HTML 使用 no-store、no-referrer。
- 隔離 MySQL/API/並行/Chromium 共 136 項通過，另驗證實際 token 未出現在測試 Nginx 日誌。前端建置及 nginx -t 通過。
- 寄信仍未啟用，SMTP 尚未設定；Audit 維持暫停。沒有 migration，正式帳號／密碼與業務資料未改動。


## 2026-10-06：Accounting 改以 SoA／Transactions 對帳
- Accounting 預設顯示已儲存的 SoA 保費、理賠與沖銷交易：SoA／Statement no.、Transaction no.、Reconciliation Ref、Leg、對象、金額與結清狀態。
- 可依 SoA、交易編號、對帳參考號或 TW Ref 搜尋；提供幣別、再保人／R/I Broker、公告日期、Leg、來源與結清狀態篩選。
- transactionRows 沿用案件 SoA 的參考號與分期付款結清規則；納入 Reversed 案件歷史，不產生交易、不改寫既有交易。
- 原有 rows 及記付款／沖銷 API 保留；Payment schedule 為獨立子分頁。會計可直接讀取對帳交易，既有案件讀取權限維持。
- 在獨立 MySQL 與 Chromium 驗證會計 API、分期／理賠／沖銷對帳資料與畫面操作；沒有 migration。Audit 與寄信設定維持。
- 本次只更新 VM，未同步 Hatchable Alpha。


## 2026-10-06：交易編號改為 T／C
- 新保費交易編號的 TX1／TX2／TX3 改為 T1／T2／T3；理賠交易的 CLM{id} 改為 C{id}。分績 a／b、分期 I{n}、更正週期 C{n} 與沖銷 RVS{n} 後綴沿用。
- Accounting 與案件 SoA 以共用顯示函式呈現歷史交易的新寫法，包括沖銷引用文字；Accounting 同時接受原始與顯示編號搜尋。
- 歷史 payload／Snapshot／Audit 的原始交易編號保持原樣，沒有資料重編或 migration；新交易直接儲存新格式。
- 會計與交易金額、Leg、結清狀態沿用原規則。
- Alpha 原始碼測試副本與雜湊保持原樣；差異測試僅轉換 Alpha 預期輸出中「新產生交易」的編號，其餘欄位與歷史交易嚴格比較。
- 隔離驗證涵蓋理賠 API、Production 關帳、分期補登、編碼、計算差異及 Chromium 的 Accounting／案件 SoA 顯示與搜尋；Audit／寄信設定維持。
- 本次只更新 VM，未同步 Hatchable Alpha。


## 2026-10-06：前端金額格式、Case 預設值與 Claim 對象
- 12 個金額輸入欄位使用共用 formatter/parser 顯示千分位；保留數字型別、原有小數位、上下限與理賠負數沖抵。百分比、匯率及天數不改。
- New case 預設 TWD、Cedant/Reinsurer Tax 1%、登入 Personnel 姓名作 AE；新增再保人列 Tax 預設 1%。既有案件載入、續保及批改的資料沿用原值。
- New case 選 Effective date 後帶一年後 Expiration date，閏日用翌年 2/28；手動設定迄日及既有案件編輯不覆寫。
- 共用 Claim 對象顯示：Leg 1 顯示 Reinsurer/R/I Broker；Leg 2 顯示 Cedant。Accounting SoA、Payment schedule、Case SoA 共用此邏輯，Recipient 也顯示 Cedant 名稱；保留原始交易的 reinsurer 分配關聯。
- 模板產生程式同步，重新產生保持既有 VM 修正與本次修正。
- 隔離 MySQL/Chromium 驗證輸入、存檔、既有零稅率及日期保留、會計付款及 Claim Leg 名稱。只部署前端；後端、資料、Audit 與寄信設定維持。


## 2026-10-06：批單退保費（保費差額，不走 Reverse）
- 依使用者確認：批單輸入本次保費差額，正數加保費、負數退保費；原保單與原交易保留。
- 後端僅允許資料庫確認為 endorsement 且有 parent_case 的批單填負保費；原保單及續保維持非負限制，批單 parentTwRef/序號由原流程資料固定。
- 批單保費、再保保費與分期保費支援負數；保費差額欄位可在風險鎖定時編輯，風險與條件維持鎖定。分期差額須與總保費同方向，依絕對值比例分攤並保留原計算進位。
- 新退保費交易沿用 E{n}/T1/T2/T3，T1 應退分保人、T2 應向再保人或 RI Broker 收回、T3 經紀費差額；不標記 Reverse 或 RVS。零經紀費的退保費批單仍能列入 Production 並產生交易。
- 負數付款排程保留 signed amount/paid/outstanding，狀態與結清依絕對值計算。操作輸入正數現金金額，後端依原排程方向存入負數退款/回款紀錄，保留原超額、版本與付款沖銷檢查。
- 非分期退保費的到期基準使用批單生效日；分期依各期基準日。提醒能識別負餘額及應退/應收方向。
- Accounting 與 Case SoA 顯示實際對象及收付款方向；保費 Leg1 顯示分保人，Leg3 顯示 Broker。財務 Leg3 沿用經紀費差額及未追蹤付款狀態。
- 隔離 QA 驗證批單建立、存檔、Announce、Production 關帳、非沖銷交易、退款/回款、分期進位、提醒及原保單完整保留；既有 API 與 frozen Alpha 差異驗證維持。沒有 migration 或正式資料改寫。


## 2026-10-06：0609 AUW Facility 額外手動 TW Ref.
- 依使用者確認：保留既有自動 TW Reference，另加案件層級 TW Ref. (Manual)，不以手動編號替換流水號。
- 再保人名單包含 Lloyd's Underwriter Syndicate No. 0609 AUW (Facility) 時顯示欄位；混合再保人案件也適用。草稿可先留空，Announce 前前後端檢查必填，已公告及更正案件也不可存成空白。
- 手動編號以文字保留前導零及標點、去前後空白，上限 160 字元。案件概覽、列表及 Accounting SoA／Payment schedule 顯示兩組編號，列表及會計可依手動編號搜尋。
- 移除指定再保人後，存檔清除額外編號；新增續保與批單草稿清空手動編號供重新輸入。既有 Reinsurer Ref.、交易編號與上帳金額沿用原規則。
- 隔離 API／MySQL／Chromium 及原有流程回歸驗證通過。沒有 migration 或既有資料改寫；未變更文件產生、Audit／寄信設定，未同步 Hatchable Alpha。


## 2026-10-06：TW Ref. 顯示合併及順序
- 依使用者指定：自動 TW Ref. 在前、AUW 手動編號在後，以 & 連接；例如 TWPF2601001 & TW26SM010001。
- 案件列表及預覽、案件標題及概覽、Case SoA、Reminders、Accounting SoA／付款排程及付款視窗使用同一顯示函式。原來兩個列表欄位合併成 TW Ref. 一欄。
- 案件及會計搜尋同時支援完整合併文字或任一單獨編號；一般案件只顯示自動編號。手動輸入欄位仍只編輯 AUW 編號。
- 只部署前端。後端、兩個原始欄位、交易編號、文件產生、既有資料及 Audit／寄信設定維持。隔離 Chromium 驗證順序、畫面、搜尋及原始資料不變。


## 2026-10-06：AUW 保費固定比例及 Draft Policy Period
- 指定 0609 AUW (Facility) 再保人列的 Deductions 固定 10%、Reinsurer Tax 固定 0%。選取及載入編輯時自動帶入，欄位鎖定；後端新增／儲存一律寫固定值。其他再保人、Cedant 的比例及稅率保留各自原值。
- 舊 AUW Draft 若仍是其他比例，前後端拒絕 Announce，要求先編輯存檔。既有交易與文件不重算、不改寫。
- 已實際重現：Effective Date 鍵入後按 Tab，新案會帶一年後日期，已存 Draft 因 isEditing 檢查被跳過而不帶。修正空白迄日 Draft 可自動帶一年，並以日期模型監看補強；閏日帶翌年 2/28，手動或既有非空迄日保留。已公告及批單的原日期行為維持。
- 隔離 API／MySQL／Chromium 驗證固定比例、混合再保人、零稅率上帳金額、批單退款、鍵入及重開 Draft 的日期；既有流程與 Alpha 計算差異回歸通過。沒有 migration 或正式資料批次改寫。


## 2026-10-06：AUW Deductions 改為可修改的選取預設值
- 依使用者確認：選取 Lloyd's Underwriter Syndicate No. 0609 AUW (Facility) 時，只有該列 Deductions 自動帶入 10%；欄位可修改。儲存、重開及 Announce 保留最後輸入的比例，包括 0%。
- 移除前後端強制 Deductions 10% 的覆寫及公告限制；仍驗證 0–100% 的數值。草稿可保留空白，但公告前必填。選取其他列再保人不會重設既有 AUW 的比例。
- 使用者確認 Reinsurer Tax 維持固定 0% 並鎖定；其他再保人與 Cedant 的條件維持各自數值。
- 隔離 MySQL/API/Chromium 實測選取預設、手動修改、儲存重開、混合列及 0%；實際 Announce、Production 關帳及 SoA 驗證 8,000 保費、12.5% Deductions，應付 7,000；退費 -800 對應 -100 Deductions、-700 淨額。批改與續約沿用既有案件比例。
- 保留已部署的 Policy Period 與雙 TW Ref. 行為。沒有 migration 或正式案件、交易及文件批次改寫。


## 2026-10-06：AUW Facility 月底＋120 天付款及新案 Cedant 90 天預設
- 使用者逐項確認：0609 AUW (Facility) 保費付款採適用日期所在月底＋120 個日曆天，實際付款日期遇假日不順延；Accounting 與既有提醒採實際日期前 10 天，12:00 Taiwan。單期按保單生效日、分期按各期付款基準日、批改補退保费按批改生效日。
- AUW 120 天為固定條件，前端選取及載入時帶入且鎖定，分期 AUW override 也鎖定；後端固定 120 且排程忽略其他付款天數覆寫。Deductions 仍預設 10% 且可修改，Tax 維持 0%。
- 所有既有 AUW 排程讀取時套用新日期，原收付款紀錄、付款對應 key、交易及上帳分錄保留。Accounting 顯示月底基準、會計提前日期、AUW 實際付款日期，避免混淆。
- 使用者確認 Cedant 收款 95% 以上為保單生效日＋90 天；所有新案的 Case Payment Terms 預設 90 且可修改，會計仍提前 15 天。新案以 Cedant 自身的 Case／Installment terms 計算，不受再保人 override 影響；新建及工作流程的新 Draft 記錄 cedantTermsBasis=case。既有非 AUW 案件保持舊最短再保期限算法，既有已填天數及複製案件的明確條件保留。
- AUW 固定條件以 canonical payment_terms_signature 比較，避免舊已公告案件 null／舊 override 因載入帶 120 而誤判已改付款條件；其他付款條件與計算模式公告後仍鎖定。
- 隔離 MySQL／API／Chromium 驗證：同月不同日、月底長短與閏年世紀、跨年、分期、補退保費、既有付款／沖銷與提醒日期，以及新案 90 天、手動例外及既有 180 天保留。既有案件／會計／關帳／批改及 Alpha 計算差異回歸通過。沒有 migration 或正式資料批次改寫。


## 2026-10-07：Board of Directors／President 正式唯讀角色
- 使用者指定 David Kao／david.kao@tw-insure.com，Department=Board of Directors，Role=President；先建立 Personnel，暫不開通登入帳號。Board of Directors 預設不列入業績分配。
- 新增正式 president 角色，所有相同角色共用：Dashboard 全案、Account List 全案（含他人草稿）、文件閱讀下載、Reinsurance MDM、Production Report、Accounting、FX Rates 唯讀。排除 Personnel & Accounts、Draft Recycle Bin、Audit Log；不授予寫入、公告、人員、帳號、目標設定、系統管理權限。
- 前後端新增 board_of_directors／president 選項與預設；Personnel migration 0004 擴充既有 CHECK 約束允許值，保留既有資料與未知值拒絕檢查。
- 修正案件頁 Record notification 缺少 cases.write 判斷，以及唯讀草稿文件頁狀態徽章誤顯示 Announced；既有各項修改／上帳／理賠／文件／收付款／Production 操作由後端既有權限與角色檢查拒絕。登入者修改自己的密碼仍沿用帳號安全流程。
- 隔離資料庫測試 President 跨所有者草稿與各種案件狀態、業務讀取、排除 API、每項寫入拒絕且資料指紋不變；既有角色登入及人員帳號、案件流程、會計、關帳、文件、理賠回歸通過。Chromium 驗證部門角色下拉預設、人員名冊及唯讀頁面、禁止頁面導向。


## 2026-10-07：President 作為所有部門的 Supervisor 選項
- 使用者確認所有部門都能選 David Kao 為 Supervisor，禁止選自己，既有主管不改寫；並說明 President 只有一位，因此以在職 President 角色納入跨部門主管候選，現在為 David Kao。
- Personnel 前端 Supervisor 選項及後端 resolve_supervisor 同時擴充：同部門在職人員、在職 General Manager、在職 President；未開通登入帳號不影響主管候選資格。停用在職人員仍排除；編輯時排除自己；原同名主管解析的同部門優先與 id 次序保留。
- 選取時顯示 David 的 Email，後端依人員資料解析，忽略客戶端傳入的錯誤 Supervisor Email，讓後續主管提醒沿用正確聯絡資料。現有 SupervisorName／Email 與 David 帳號、在職、分績設定均保留。
- 隔離 Personnel／Accounts 回歸及八部門 President Supervisor API、Chromium 驗證通過：跨部門選取、新增／編輯儲存、自動帶 Email、未開通帳號可被選取、停用排除、不能選自己、舊 General Manager／同部門規則保留。沒有資料庫 migration 或正式人員資料批次修改。


## 2026-10-07：AUW Draft 手動 Ref. 必填及 Howden 綁定
- Placement 包含 0609 AUW (Facility) 時，新增／編輯 Draft 必須填單行、最多 160 字的手動 TW Ref.；前端提示並阻擋，後端獨立驗證。Announce 仍保留原有自動流水號及自動 & 手動 Ref. 顯示。
- AUW 的 Foreign RI Broker 自動帶入 Howden Specialty Limited 並鎖定；後端強制正規化，Announce 亦檢核。改成非 AUW 時解除鎖定、清空 Howden。混合 Placement 的其他再保人欄位保留獨立設定。
- AUW 續保／批改先提示輸入新 Ref.，後端檢查後才建立新 Draft，不沿用來源手動 Ref.；一般案件沿用原工作流程。
- 經使用者確認，既有 AUW 案件批次補上 Howden，逐案提升版本並留存 Snapshot；只改 AUW foreignBroker，既有稅率、Deductions、金額、手動／自動 Ref.、交易及收付款紀錄保留。缺少手動 Ref. 另輸出待補清單，不生成替代編號。Audit 暫停及寄信設定沿用。
- 隔離資料庫 API、既有案件／工作流程／Accounting／Production 回歸及 Chromium 實際操作驗證通過，包含必填阻擋、後端防繞過、混合 Placement、續保／批改、舊案修正與重跑不重複寫入。


## 2026-10-07：AUW 與批單單期結算規則
- 手動 AUW 欄位及提示改為 TW Ref. (for AUW)。AUW 改選其他再保人時，清空 Howden、Deductions、Tax、再保人付款天數及其分期覆寫；新選 AUW 仍帶入可修改的 10%、固定 0% Tax 與 Howden。
- 所有批單不允許保費分期；工作流程建立單期，前端停用分期及 Cedant 天數，後端依實際 case_kind 拒絕繞過。原保單、續保保留原有分期。
- 批單 Cedant 天數繼承原始保單，不沿用中間批單；以台北時間實際 Announce 日與批改生效日較晚者加原保單天數，會計提前 15 天。AUW 批單採同一較晚日期的月底加固定 120 天，會計提前 10 天，遇假日不調整。非 AUW 再保人原付款規則保留。
- Announce 時寫入伺服器認定的時間；草稿不推測公告日，後續修改不接受使用者偽造時間。公告後批改生效日依既有付款條件鎖定。
- 經使用者確認，TWPF2609001-E01 改為單期，新日期適用，原始業績合併歸屬 2026-09；9 月已關帳，透過新增不可改寫的 exclusion 遞延到下一個未關帳月份。已關帳報表、原保單、稅率、佣金、保費、既有上帳與收付款紀錄不改寫；缺少 AUW Ref. 沿用待補，不生成號碼。保留版本與 Snapshot。
- 隔離 API、帳務／Production／負保費回歸及 Chromium 實際操作驗證通過；既有批單修正可重跑且不重複寫入。


## 2026-10-07：Finance 案件唯讀、President 文件限制、主管新增下屬
- 使用者逐題確認 A/B/A/A/A：Finance Staff 與 Finance Manager 可檢視全部 Account List、案件明細、流程與理賠，保留原帳務權限，不新增案件寫入或文件權限；President 隱藏整個文件區，不能預覽、產生、下載、上傳、勾選或刪除文件。
- 有其他 Personnel 指定本人為 Supervisor 即具主管身份，依既有同部門優先與同名排序規則判斷。所有角色可依此取得 personnel.read.team 與 personnel.create.subordinate；不授予 personnel.write 或 accounts.manage。移除最後一筆主管指定後，後端立即收回窄範圍權限。
- 主管只能新增本人所屬部門的下屬；角色固定為再保部 sales、財務部 accounting、其他部門 viewer；Supervisor 固定本人、主管 Email 由後端解析。非原 personnel.read 角色只可讀本人及同部門直屬下屬，不能編輯既有人員；General Manager 保留既有全人員唯讀，System Administrator 保留完整人員與帳號管理。新增人員不建立或啟用登入帳號。
- 前端新增 Add subordinate 操作，部門、角色與主管固定，隱藏無權限的人員編輯、帳號管理、業績目標及文件入口；後端拒絕跨部門新增、角色升權與換主管。保留原案件負責人轉移、Draft 文件刪除、5 年還原與禁止永久刪除規則。
- 213 項新權限 API 驗證、12 套隔離回歸及 Chromium 驗證通過。無資料庫 migration；正式資料表內容指紋與筆數、Email 與 Audit 暫停狀態於部署前後一致。


## 2026-10-07：主管可建立直屬下屬登入帳號
- 使用者選擇 A：已有下屬的主管可為既有或新增的同部門、一般角色直屬下屬建立登入帳號。一般角色依部門固定為 reinsurance=sales、finance=accounting、其他=viewer。
- 新增 accounts.create.subordinate 動態權限，僅建立帳號 API 採 accounts.manage 或此權限；停用、重新啟用及重設密碼仍限 accounts.manage。主管不能修改既有人員、角色、主管或 Email，也不能為自己、同部門非下屬、跨部門、非一般角色、非在職或已有帳號的人員建帳號。
- 帳號建立沿用 ADMIN_ACCOUNTS 共用交易鎖，在鎖定後重新驗證主管及人員現況；主管只能使用既存 Personnel Email。維持密碼強度、一次性回傳、首次登入強制改密碼與 Audit/Snapshot 原子寫入。
- 前端僅在後端 canCreateAccount 為真時顯示 Create account；一般主管僅取得其直屬一般角色下屬的帳號名稱，其餘管理控制仍隱藏。
- 主管權限 API、既有帳號/密碼/角色與 President/主管回歸及 Chromium 瀏覽器驗證通過，詳見 Supervisor-Accounts-2026-10-07 驗證產物。無 migration；正式資料與帳號指紋及設定於部署前後一致。


## 2026-10-07：Finance Staff 業績唯讀、President 人員與帳號唯讀
- 使用者確認 Finance Staff 可檢視月業績預覽與既有版本、下載既有版本 Excel，但不能產生報表或排除業績列；關帳仍不允許。Finance Manager 與 System Administrator 保留產生、排除及關帳權限，財務兩角色原帳務操作及全部案件檢視保留。
- 使用者選擇 A/A：President 可唯讀全部部門的人員，不能新增 Personnel，也不能建立登入帳號。新增 President personnel.read；主管身份仍可由 Personnel 指定成立，但 President 不取得任何主管額外寫入權限。帳號服務在鎖定現有資料後亦拒絕 President。
- 業績 API 的 readOnly 與 canOperate 正確反映角色，已知無權限的寫入在取得月份鎖及計算來源前回 403；前端隱藏寫入按鈕並使用唯讀說明，既有 XLSX 下載保留。
- President 全人員名單入口可用，前端不顯示人員新增、修改、停用或帳號建立、重設等控制。其他主管同部門一般角色下屬新增與建帳號規則保留。
- 隔離角色權限、人員帳號、密碼、President、業績 API 回歸及 Chromium 操作與實際 XLSX 下載驗證通過，產物見 Role-Refinement-2026-10-07。無資料庫 migration；正式資料、帳號及設定部署前後一致。


## 2026-10-07：Dashboard 貨幣位置與標題
- Total Gross Premium 及 Outstanding · Cedant / Reinsurer 改為 TWD 前綴，例如 TWD 0 與 TWD 0 / 0，保留原有千分位格式。
- 趨勢標題改為 YTD Brokerage Trend (TWD)。
- 僅調整 Dashboard 前端顯示；正式建置與獨立 Chromium 驗證零值及非零金額，既有資料及後端維持。


## 2026-10-07：Dashboard Total Bound YTD 標題
- YTD Case Volume 改名為 Total Bound YTD；沿用原有當年及去年同期計數，後端計算規則維持。
- 前端建置與獨立 Chromium 檢查標題、當年及去年同期數值，以及既有 TWD 格式。


## 2026-10-08：Accounting 合併 SoA／Transactions 與收付款
- 改為單一交易列表，每筆既有 Transaction 顯示 SoA、對帳參考號、實際對象、到期日、已收付、未清餘額及操作；不列出尚未生成交易的付款排程。
- 同幣別、同收付方向、同實際交易對象可跨案件／分期登錄一筆匯款。每筆交易手動分配，可部分收付；分配合計須等於匯款總額。版本、餘額或任何一筆驗證失敗時整批不寫入。
- 新 paymentEntries 記錄原始交易編號、共同 batchId、匯款參考號與金額；每案件只增加一次版本，保留 Snapshot 與原有 Audit 設定。既有排程收付以整數分攤，現金不重複計算。
- T3 是保留經紀費，沒有獨立匯款登錄；對應的 T1／T2 全結清後自動結清，沖回後重新反映狀態。
- Claim 紀錄建立應收應付，實際向再保人收款及付給分保人分別在 Accounting 登錄；Claims 的文字改為 obligation。案件 SoA 即時顯示一致的收付／結清狀態。
- 更正匯款必須整筆新增不可覆寫的 reversal，保留所有原始分配。原有單筆付款 API 保留相容性，但不能繞過整批沖回規則。
- 50 項新會計 API、既有案件／Production／理賠測試及實際 Chromium 操作驗證；7,100 組計算向量與部署前完全相同，既有 Alpha 差異不增加。無 migration、未更改正式資料、Audit 暫停與寄信關閉維持。此批為 VM 更新。


## 2026-10-08：移除共用頁框開發提示
- 移除所有登入後分頁的 VM 版本／Audit 狀態與案件／提醒信搬遷說明列。
- 移除左上角「再保部 | VM」與「Facultative Outward — Phase 1」；登入、忘記密碼與重設密碼頁的同名標示一併移除。
- 前端 production build 與正式靜態檔核對通過。僅四個 Vue 顯示模板變更，後端服務、業務資料與設定不變。


## 2026-10-08：主分頁說明文字
- Dashboard：Production & Records Overview。
- Account List：All outward cases；共用路由與案件工作區的頁首設定同步更新。
- FX Rates：Official monthly foreign currency to TWD rates。
- 前端建置與正式靜態檔核對通過；僅說明文字調整。


## 2026-10-08：Risk Details 欄位排列與 Type 寬度
- 第 1 排：Reinsurance structure、Case owner、AE、Currency。
- 第 2 排：Class、New / Renew、Type；Type 佔兩格。
- 第 3 排：Reinsured、Original insured (EN)、Effective date、Expiration date。
- Type 輸入改為依內容自動增高的文字欄位；固定的 structure suffix 保留。窄螢幕仍依兩欄／一欄排列。
- 前端建置、瀏覽器欄位排列與長文字顯示檢查通過；僅重建 nginx 前端，業務資料及後端不變。


## 2026-10-08：Case Overview 上傳與 Announce
- Review & Announce 自 Cover & Debit Note 移至 Overview；正式確認對話框及 Announce API 保留。
- Overview 與 Cover & Debit Note 均提供 Upload Evidence，共用檔案種類、待上傳檔案與已上傳資料。
- 首次開啟案件即載入證據；切回 Overview 更新覆蓋狀態。Overview 顯示缺漏提醒、證據覆蓋與所選檔案。
- 前端建置及隔離瀏覽器流程檢查通過；僅更新前端，後端與業務資料不變。


## 2026-10-08：Case Documentation 分頁名稱
- Case 中 Cover & Debit Note 分頁名稱與對應頁首改為 Documentation。
- 模板產生器及既有 UI 測試選取器同步更新。
- 前端建置及正式靜態檔文字核對通過；上傳及 Overview 的 Review & Announce 保留。


## 2026-10-08：純 AUW 以手動 Ref. 作為主編號
- 純 AUW 原保單、續保及批單 Announce 直接採手填 TW Ref. (for AUW)，不產生、查詢或消耗流水號；混合及一般案件保留自動 TW Ref.。顯示相同主／AUW Ref. 時去重，混合案件維持自動編號在前。
- 手動 AUW Ref. 在 Draft、修改、批單、續保及 Announce 檢查與其他案件的主編號、手動編號及舊編號衝突；回收與封存案件仍保留編號。共用序列化鎖避免併發重號，自動流水號略過已被手動 Ref. 保留的值。手動主編號公告後鎖定。
- 主編號與流水號前綴欄位擴為 192 字元，保留手動 Ref. 160 字元限制，並保留長 Ref. 的批單／續保來源連結。純 AUW 批單業績編號由正式 endorsementSeq 判定。
- 使用者將免文件決定改為 C：原有 Offer Slip、所有再保人 Signed Slip／Confirmation E-mail 及 Signed Slip 提醒規則全部保留。
- 既有純 AUW 案件僅製作轉換清單；本次未變更案件、帳務、文件、報表、流水號或其他業務資料。經確認後才可使用有版本、歷史及關聯防護的轉換工具。
- 隔離 API 回歸與逐字鍵盤、滑鼠錄影驗證通過，包括 Production 關帳、Accounting、批單及續保。


## 2026-10-08：已批准既有 AUW 主編號轉換
- 使用者選 A，僅將 Polystar／Starich（fb43316b-126d-4e0b-be26-ba93b7553771）主編號 TWPF2311001 改為 TW23SM010736；舊號保留 previousTwRefs 可查詢且不能再分配。
- 轉換前核對第 9 版、純 AUW placement、未上帳／無現金／無理賠／無報表或續保批單關聯；同一交易內只變更主編號與來源／歷史 metadata、版本與編輯資訊，新增一份 Snapshot。金額、日期、文件與流水號內容保留；Audit 暫停、寄信關閉設定保留。
- 歷史 Ref. 改以文字 casefold 比對，避免 MySQL JSON 陣列大小寫敏感導致舊号重用；API、轉換防護與搜尋驗證通過。


## 2026-10-08：Production Report 新增 First Policy No（首次承保號碼）
- 起因：批單的 Policy No 是原保單的 TW Ref，所以批單即使改了 Insured Name 也能用 Policy No 歸組；但續保會產生新的 TW Ref，匯出檔上看不出新舊保單是同一個案子（系統內有記 `renewedFromTwRef`，匯出沒有）。
- 做法（使用者選定）：匯出與畫面的**最後一欄**新增 `First Policy No`＝沿「批單→原保單、續保→來源」一路追到最初那張保單的 TW Ref。同一案子的各年度保單與批單這欄相同，不受 Insured Name 變更影響。Policy No、Endorse No 等既有 17 欄不變。
- 追溯規則（`production/calc.py` 的 `reference_links`／`first_policy_no`）：TW Ref 改過時（`previousTwRefs`）以現行號碼為準；來源不存在時顯示最後知道的號碼；有循環或自我指向時停止；連結表用「所有有 TW Ref 的案件」建（含已封存），中間那張被封存也不會斷。**只靠 TW Ref 連結，從不比對名字**，同名不同案不會被併在一起。
- 不放進 `source_signature`：連結不影響金額，避免讓已產生的報表全部變成「過期」。已關帳的月份保存的是當時的列，**不會補這一欄**（欄位是空白）；開著的月份重新 Generate 才會有。舊系統／Excel 轉入、沒有續保來源紀錄的案件，這欄就是它自己的 Policy No。
- 偏離 Alpha（**尚未同步回 Alpha，使用者決定先只改 VM**）：`production-xlsx.js` 多 4 處（標題、`cellValue` 多一格、第 18 欄寬度、autoFilter A1:R）；`run_calc_diff.sh` 改由 `scripts/check_production_xlsx.py` 核對「Alpha 原檔雜湊 + VM 版 = 原檔 + 這 4 處」。差異測試（`qa/calc/compare.py`）比對 Alpha 前先拿掉 `firstPolicyNo`，沒有這個欄位會算不一致。
- 驗證：新套件 `qa/suites/production_first_policy.py`（25 項，含批單／續保／從批單續保／兩層續保／來源不存在／中間封存／舊 TW Ref／循環）；故意弄壞 8 處（批單不追父、續保不追來源、忽略舊 Ref、不用現行 Ref、View 不傳完整連結表、欄位進簽章、少標題、拿掉循環保護）全數被抓到（拿掉循環保護會無窮迴圈卡死）。


## 2026-10-10：Case Loss Record 0 年規範
- New 案的 Past year(s) 可填 0，由業務員判斷；所有 Case 儲存時年數與 broker advised date 不可空白。
- 0 年時 Loss Record 明細必須為空；Endorsement 沿用 0 年，Renewal 建立時可帶入 0，但編輯儲存前必須改為大於 0。
- 0 年摘要在 Case、Word 與 PDF 顯示 Loss Clean since operation.；Alpha 參考檔保留原樣。


## 2026-10-13：Accounting 顯示原被保險人名稱
- Accounting 主分頁 SoA / Transactions 在 Transaction / SoA / TW Ref 後新增 Original Insured (EN / CN) 合併欄：英文在上、中文在下，缺值顯示 —。
- 所有交易列從所属案件 payload 取得英文／中文原被保險人；兼容舊 original_insured 欄位。
- 隔離 accounting_transactions API 回歸、18 組純函式比較、瀏覽器排列與唯讀／會計視圖驗證通過；交易金額、餘額、結清、權限及業務資料不變。


## 2026-10-13：3 小時人員閒置自動登出
- 使用者選擇 A/A：真實點擊、鍵盤／輸入、捲動重新計時；滿 3 小時閒置自動登出，提前 5 分鐘提醒，可點 Continue using 重新計時。提醒告知未儲存內容可能遺失，不會自動提交人員／案件或其他業務資料。
- 改為 10800 秒閒置與 300 秒提醒，SESSION_SAVE_EVERY_REQUEST=False。登入建立人員活動時間與非憑證公開識別碼；只有 CSRF 保護且識別碼符合的 activity POST 才延長絕對期限，背景 API、程式捲動、焦點切換不續期。後端 middleware 與 Django session 到期共同拒絕過期存取，過期 cookie 不能復活。
- SPA 與管理員 Data viewer 共用活動偵測程式；多分頁同步期限，登出前重新查核伺服器狀態，避免其他分頁已續期時誤登出。不同瀏覽器登入各自計時，改密碼換 Session cookie 時保留活動識別碼與期限。
- 舊 8 小時 Session 在下一個已登入請求採用新規則；重新整理頁面載入新版提醒與活動偵測。未新增資料表或 migration，未批次刪除現有 Session，未更改角色權限、帳號、密碼或既有業務資料。
- 新閒置邊界與 CSRF／到期重放檢查、登入／帳號／密碼重設／管理員／President 回歸與 Chromium 多分頁、持續輸入、捲動、提醒、自動登出驗證通過。僅獨立 QA 使用縮短時間，正式部署另驗證 10800/300 秒。產物見 Idle-Timeout-2026-10-13。


## 2026-10-13：Swiss Re Asia Facility Property 會計規則
- 僅適用 Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)／Property。原保單、續保、分期及加費批單採約定 90／會計 75 個日曆天；批單取生效日與正式 Announce 台北日較晚者。假日不順延；75 天提醒、超過 90 天逾期。
- Swiss 固定 02/14、05/14、08/14、11/14；保費依會計 75 天、最後填寫收款日期及實際手動確認日取最晚歸期。月底為確認截止，提前收齊不提前結算，未确认顯示原定及目前預計日期。我方漏付、銀行退回保留原期並標逾期。
- 全筆 insurer 應收（含其他再保部分）帳面結清後由會計確認；新增／修改／刪除或沖回收款紀錄須重確認。手續費／短收須先留原因登錄非現金結清。每笔 Swiss 应付一次全額沖銷，可合併匯款分配多筆。
- 退費 Swiss 原定收款提前一個結算期，仍受正式 Announce 月底列期限制；逾期保留原日、不滾動催收日期。所有再保退款確認收齊後才整筆退保險公司，可提前退款，原 75／90 日保留。批單不分期、不混合補退費。
- 原案及其對應退費批單同一 Swiss 結算期可抵減，保留雙邊原金額、實際淨收付與互相連結的非現金沖銷；不同原案及跨期不互抵。已送出清單跨期時由會計手動修訂確認。
- 尚未結算舊案於讀取套用規則；可驗證歷史結清時間承接並保留來源，無來源需會計重確認；已完成付款及銀行退回原紀錄保留。雙方清帳前對帳，依使用者最新決定不建立清帳後差額項目。
- Accounting 新增 Swiss Facility · Property 操作表。27 日期／邏輯測試、56 隔離 API 檢查、12 套 979 項既有回歸、5 項瀏覽器流程及前端建置通過。Finance QA 提醒讀取預期與 2026-10-07 已核准全案讀取權限一致，未修改權限。
- 無 migration、無正式業務資料批次改寫；上線前後所有 managed model（除 session）筆數／內容指紋相同；Audit 暫停及 Email 關閉保持。同期 System Reference 英文介面與文件名稱更新已保留。


## 2026-10-13：Dashboard New Business MTD 新增 Case 入口
- 在 New Business MTD 卡片右下角新增 + New Case 按鈕；依 cases.write 權限顯示。
- 點擊導向 /cases?action=new，消費查詢後沿用現有 startNewCase 表單及預設值。開啟表單不寫入案件資料，待使用者儲存。
- 前端建置、隔離瀏覽器的桌面／手機點擊、預設值、重載及權限檢查通過；僅更新前端。


## 2026-10-13：Swiss Accounting 無資料時固定顯示
- 移除 Swiss Facility · Property 區域的非空案件顯示限制。沒有符合案件仍顯示標題、75／90 天與固定 Swiss 日期說明、日期及收齊確認欄，空白表格說明 Swiss Facility Property 案件 Announce 後列入。
- 7 項隔離瀏覽器驗證通過：會計及唯讀空白狀態、既有收齊／清單修訂／整筆合併匯款／唯讀控制／Swiss 範圍鎖定。前端建置通過。僅重建 nginx，後端、資料庫、PDF 服務及所有 managed model 指紋保持。


## 2026-10-14：Swiss 整合至單一 Accounting 清單
- 使用者明確同意移除獨立 Swiss Facility · Property 專區，將日期與人工操作整合至既有 SoA / Transactions。
- Swiss 原定／目前結算日、月底截止、75／90 日期、延期、逾期、收齊狀態均在對應交易列顯示；多分期按各自排程顯示。移除重複表格，保留會計手動收付、收齊、結清、費用／短收、同案同期抵減、清單修訂與歷史；輔助操作由該列 More 開啟。
- 已 Announce 尚未 Production close 的 Swiss 項目在同一清單顯示，清楚標示 Awaiting Production close，沿用原 schedule payment／confirmation API；正式交易生成後以 cashParts 對應排程，避免重複列出及重複加總。原歷史反向交易及理賠不遮蔽現行保費排程。
- 12 項資料整合檢查、16 項 Chromium 流程與前端建置通過，涵蓋無資料、已上帳／未上帳、保費／退費、收齊／取消、手續費、清單修訂、抵減、整筆合併匯款、人工結清、其他 Facility 與唯讀。測試採合成資料，無正式業務寫入。
- 僅更新前端並重建 nginx；所有後端計算、75／90 天、Swiss 歸期及延期、月底截止及手動結清規則保留。後端／MySQL（及存在的 PDF）容器、業務資料指紋與設定保持。已備份來源與舊映像，可回復。


## 2026-10-14：全面除錯修正（依使用者逐項確認）
- 除錯不再與 Hatchable Alpha 比對：刪除 Alpha JS 差異測試（alpha_js、compare.py、harness.mjs、run_calc_diff.sh、check_production_xlsx.py），run_qa.sh 不再有 calc 步驟；前端合計一致性檢查保留。
- Swiss 同案同期抵減：Cedant 退費須所有再保人退款確認收齊後才可抵減（refund_collection_required），與現金退費相同。
- Performance Split 兩方合計 100% 時，b 方金額 = 該 Leg 總額 − a 方，Leg 1 交易合計與付款排程一致（原本可能差 1–3 分錢而停在 Partial）。
- Swiss 收齊證據維持 10/13 規則：可驗證的歷史交易結清時間可承接並保留來源（撤回當日另一 session 改為一律手動確認的修改）。
- 新案「Cedant 天數以案件為準」標記（cedantTermsBasis）由伺服器保留，存檔漏傳不會改回舊算法。
- Accounting 逐案計算：單一案件資料無法解讀時只略過該案並顯示警告，其餘照常顯示。
- 全 Facility 改成混合再保人時，只清空沒有有效 Location 的 Sum Insured；已指到存在 Location 的保留（舊資料原本記在 Location 1 時，原規則會一直清空導致無法 Announce）。前後端一致。
- 刪除 Location 不會讓 Sum Insured 變成零筆；System Reference 單一損壞中繼資料只略過並提示；nginx /static、/assets 補回 nosniff 與 X-Frame-Options；刪除未使用的 PDF 產生器腳本（pdf-generator.js、vm-pdf-generator.js、pdf-assets.js），退役 PDF 端點仍回 410。
- 測試：8 個過時測試組依 10/08–10/13 規則更新（純 AUW 主編號、Sum Insured 位置、Loss Record 必填、閒置 Session、Audit 空表）。獨立環境（ri_runtime＋db_harden、每組全新資料庫）49 組全部通過；密碼規則與前後端合計一致性通過。無 migration、無正式資料改寫。
