# 封存：Alpha → VM 搬遷紀錄

> 2026-10-14 封存。搬遷已完成，VM 是正式系統；Alpha 的業務資料**不會**匯入 VM。本檔只保留歷史紀錄，不再維護。
> 現行規則見根目錄 `VM-RULES.md`。轉換程式（`backend/conversion/`、`qa/conversion/`）暫留在 repo，不再使用。

## 搬遷總覽（封存時的內容）

- 來源：Hatchable「RI System (Alpha)」`proj_FVUqiQUe3m0G`，**記錄基準：v63（2026-10-05，82 個檔案）**
- 2026-09-29 起你決定把 VM 的改動**同步回 Alpha**（登入／權限、資料表結構、Personnel & Accounts 資料除外），之後會先在 Alpha 開發新功能。每批部署後，下表的雜湊改成新版本，漂移檢查照舊。見下方「VM → Alpha 同步」。
- 目標：本專案（Django + MySQL + Vue，Docker Compose）
- 原則：Alpha 是唯一的正式規格來源，VM 只移植、不自行改規格。刻意不同的地方一律寫在下面「刻意與 Alpha 不同」。

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
