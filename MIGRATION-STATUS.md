# Alpha → VM 搬遷狀態

- 來源：Hatchable「RI System (Alpha)」`proj_FVUqiQUe3m0G`，**記錄基準：v53（2026-09-25，81 個檔案）**
- 目標：本專案（Django + MySQL + Vue，Docker Compose）
- 原則：Alpha 是唯一的正式規格來源，VM 只移植、不自行改規格。刻意不同的地方一律寫在下面「刻意與 Alpha 不同」。

## 固定技術規格（VM）

| 層 | 規格 | 鎖定方式 |
|---|---|---|
| 前端 | Vue 3.5.43 ＋ Element Plus 2.14.6 ＋ Vite 7（7.3.6），元件（SFC）加正式建置；JSZip 3.10.1（Production Report 的 Excel，與 Alpha 同版，2026-09-26 加入） | `frontend/package.json` 精確版本 ＋ `package-lock.json`，Dockerfile 用 `npm ci` |
| 後端／管理 | Django 5.2.17 ＋ DRF 3.16.1 ＋ Gunicorn 23.0.0 ＋ mysqlclient 2.3.0 | `backend/requirements.txt` 精確版本 |
| Web／反向代理 | Nginx 1.28（目前 1.28.3） | `nginx:1.28-alpine` |
| 資料庫 | MySQL 8.4.11 | `compose.yaml` 固定在目前使用中映像的摘要（`8.4.11` 標籤在 9/21 被重新打包過，MySQL 版本相同、底層不同，所以固定摘要而不是標籤） |

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

| Alpha 檔案 | Alpha 雜湊（v53） | VM 位置 | 狀態 |
|---|---|---|---|
| `api/fx-rates.js` | `a2496a82375c9159944318edbef2e7365f1b55c8acd78a8a6f1b3b29138e2de3` | `backend/fxrates/` | 完成（含 Audit，見下） |
| `migrations/0010_create_fx_rates.sql` | `0875485cf1049e3d6a39bc004decc950c9a547def9f6d82ceccd43204a965e4d` | `fxrates/models.py`、migrations | 完成 |
| `api/master-data.js` | `52604668228e90ded3a1815f65f1e2435fef0b73c6a75adb6401fdbc3f8eb4c7` | `backend/masterdata/views.py` | 完成（含 #18） |
| `migrations/0001_create_master_records.sql` | `f8dde66dc346c860cbeaa436770c7dbc8af190db2b125c18ffcb732df1e7b393` | `masterdata/models.py` | 完成 |
| `lib/accounting.js` | `e0acc3c8091b843d89aaa7c52dea5a7aba3be15499d8919b3c61b94fb471ac02` | `backend/cases/calc/accounting.py`（＋`jsnum.py`） | 完成，**逐位一致**（含 #3）：Alpha 的 JavaScript 與 Python 對 9 萬 7 千組輸入完全相同 |
| `lib/payment-terms.js` | `eaaeb93887d057255cc3a2b4ee7fdaf42c3a7dcfbd8aba6561a0e03c1213b248` | `backend/cases/calc/payment_terms.py` | 完成，**逐位一致** |
| `lib/case-draft.js` | `42983151fe3b0ec514abbcad750357ef71d2e2dd7086a9a4d009cd8d54bdd338` | `backend/cases/draft.py`（`normalize_draft`、`validate_announce_ready`） | 完成，**逐位一致**：錯誤訊息（含英文原文與出現的**順序**）、整理後的內容都相同；11 萬 3 千組輸入完全一致 |
| `api/personnel.js` | `b8c98af9a6ca3a8acd3c5fa28933588df5b25e10c44d7bd859c217a1a5a3742e` | `backend/personnel/views.py`（`PersonnelView`） | 完成（含 #14、#15，含 Audit／Snapshot） |
| `api/personnel-options.js` | `98e355b36501883a3bf0c11bd8f7ec42ddc779ef742cae021c9719facc0112ad` | `backend/personnel/views.py`（`PersonnelOptionsView`） | 完成 |
| `migrations/0011_create_personnel_accounts.sql`、`0012_add_internal_account_fields.sql`、`0013_add_personnel_auth_user_index.sql` | `e65f5d93…` / `5d0ce5cf…` / `e029be6d…` | `personnel/models.py`（姓名欄位放寬到 160，同 Alpha） | 完成 |
| `migrations/0033_add_master_records_ci_unique_indexes.sql` | `24f40ef637d6a4213ca6c59864c6012ed4fd8075b3e7ad704228e237c7338884` | `masterdata/migrations/0002` | 完成（MySQL 的 ai_ci 排序規則已不分大小寫） |
| `lib/authorization.js` | `86a63b152e9e6eace0be0817bfc87647c142e101e27f1106b815b71489457954` | `backend/ri_system/authz.py` | 完成（含 #13 的取捨，見下） |
| `api/app-context.js` | `952e70d6bd75625b4b3830227c7ec3bec8b9da697e3e9e3540076edf418ec991` | `ri_system/auth_views.py` `AppContextView` | 完成 |
| `lib/audit.js` | `3389da373c0a399204352bbb48ab6f8f6963d070c4b5da4116a81119dc6c2492` | `backend/audit/services.py` | 完成 |
| `api/audit-log.js` | `d5b60a7be8abff081f30608760850baf2b02c1c597caca8ab4562db7c73bfa7c` | `backend/audit/views.py` | 完成 |
| `migrations/0003_create_entity_snapshots.sql` | `62e6de4a5876a30131d46ea6d1c6376f28f8509e14e91acc3fac20a3d9c2f62b` | `audit/models.py` `EntitySnapshot` | 完成 |
| `migrations/0004_create_audit_log.sql` | `081b80765feee215cd9110c594e6a0ca1bcbef909e4662c55e613cb78dfb98b0` | `audit/models.py` `AuditLog` | 完成 |
| `migrations/0021_extend_audit_log_retention_20y.sql` | `b94788aa4e00808cc2edd0cd572b3f400b0ecd333f59a9bdfcf3fd91fb8b37ac` | `scripts/db_harden.sh`（保存期 trigger） | 完成 |
| `api/cases.js` | `a69b83d985026d9782d2bba3892d8210c23dcd9f0ac5e205259dfcca9a6ae18f` | `backend/cases/views.py`（`CasesView`）、`cases/resolve.py` | 完成（含 #7、#8；含 Snapshot／Audit）。以 `qa/suites/cases_api.py` 驗證，並已用 26 種故意破壞確認測試抓得到 |
| `api/case-announce.js` | `af6d6ed9e8658f2d5d99aa42d526b122a339e899c65779342fdb4680c8c94a6b` | `backend/cases/workflow_views.py`（`AnnounceView`）、`cases/workflow.py` | 完成（Announce、TW Reference 流水號、批單編號；含 Snapshot／Audit）。純函式與 Alpha JS 差異測試逐位一致 |
| `api/case-workflow.js` | `a74a399b9c8536151ad14ced2b4f29590fef7d8f2431582a388e873f134756cb` | `backend/cases/workflow_views.py`（`WorkflowView`）、`cases/workflow.py` | 完成（狀態、Endorsement、Renewal、Reverse、通知會計）。資料整理邏輯與 Alpha JS 差異測試逐位一致 |
| `api/case-documents.js` | `0db7421c95f10b83650cc3a006d96cd6a6747d77327c2219cee295e3b006ef77` | `backend/cases/document_views.py`（`CaseDocumentsView`）、`cases/documents.py`、`cases/storage.py` | 完成（上傳、列表、下載、勾選、刪除；含 #11、Audit）。純函式與 Alpha JS 逐位一致；測試組 `case_documents` 73 項 |
| `lib/signed-slip-reminders.js` | `37e712193f694afa6973914f650f9cab79045bff3fa397c0e39176bf18d508a9` | `backend/cases/calc/signed_slip.py` | 函式全部移植並與 Alpha JS 逐位一致（目前只有文件 API 用到 `signedSlipTracking`；寄信提醒 #10 尚未開始） |
| `api/accounting.js` | `ddd2cc0a643038a40de352e4d946d22c4d639aa1210cb0dd207ee3a16b16984a` | `backend/cases/accounting_views.py`（`AccountingView`）、`cases/ledger.py`（`ledger_rows`） | 完成（帳本、記付款、沖銷；含 Snapshot／Audit）。帳本 `ledgerRows` 與 Alpha JS 差異測試逐位一致（600 組，節錄見 `qa/alpha_js/MANIFEST.md`）；測試組 `accounting_api` 77 項；19 種故意破壞全部抓到（其中 3 種帳本的破壞由差異測試抓到） |
| `api/claims.js` | `b690ff62b93d2d88ab46b353e10be4c8ef3356605d67bbfc64fa4ae1020579dd` | `backend/cases/claims_views.py`（`ClaimsView`） | 完成（讀取、新增理賠、改準備金、記理賠付款並產生 Claim Leg 1/2 交易；含 Snapshot／Audit）。交易由已與 Alpha 逐位一致的 `build_claim_payment_transactions` 產生；測試組 `claims_api` 67 項；21 種故意破壞全部抓到 |
| `lib/production-report.js` | `4474c028d35fa1cb474a1188020eb7619e3df678b7e933e27ce2f9fcba48c3ba` | `backend/production/calc.py` | 完成，**逐位一致**（預覽、key、簽章、下個月；差異測試約 1,000 組，含情境一致的案件、排除、延後、分績、分期） |
| `api/production-report.js` | `669afb28d56692b9fbd0a842aa5f2a818eb9ffb5a2baa0915a4ed9ab0fd8271a` | `backend/production/views.py`（`ProductionReportView`）、`production/closing.py` | 完成（預覽、排除延後、產生版本、關帳：案件確認、Leg 1–3 交易、沖銷分錄、鎖匯率；含 Audit／Snapshot）。關帳整理案件的邏輯與 Alpha JS 逐位一致（600 組，節錄見 `qa/alpha_js/MANIFEST.md`）；測試組 `production_api` 72 項；故意破壞：計算 11＋關帳 4 種由差異測試抓到、API 18 種由測試組抓到 |
| `migrations/0016_create_production_report_lifecycle.sql` | `9fd6f3cc748e5a174715a09a289099be98cbfbf58c5ba6b8aa078e3cddcb5319` | `production/models.py`、`production/migrations/0001` | 完成（同樣的 CHECK 與唯一限制；PostgreSQL 的部分唯一索引／COALESCE 索引改用 MySQL 函式索引；排除紀錄 `ri_runtime` 只能 SELECT／INSERT） |
| `public/production-xlsx.js` | `256db219f84aa2e56c9e1a36c81541c1fe7a560b0a0f9054e2253773808dcf59` | `frontend/src/alpha/production-xlsx.js`（**原樣**，`run_calc_diff.sh` 會核對雜湊） | 完成（JSZip 改由 npm 套件提供，同版 3.10.1） |
| `api/draft-recycle-bin.js` | `0de8068d01da61ab036add0599639ed2f68bb9fa9057dd25f75db7673e9a7df8` | `backend/cases/recycle_views.py`（`DraftRecycleBinView`） | 完成（列表、丟進回收桶、還原；5 年期限；永久刪除一律禁止）。測試組 `recycle_bin` 50 項 |
| `migrations/0005_create_draft_recycle_bin.sql`、`0019_lock_draft_recycle_policy.sql`、`0032_add_draft_recycle_bin_case_fk.sql` | `97cfe172…` / `eb607919…` / `b9bdfb0d…` | `cases/models.py`（`DraftRecycleBin`）、`cases/migrations/0003` | 完成（CHECK 禁止永久刪除、外鍵、索引；`ri_runtime` 沒有 DELETE） |
| `public/index.html`（外框、Account List、案件明細（含 Claim 分頁）、新增／編輯表單、回收桶、MDM、Personnel、FX、Audit、Accounting、Production Report） | `72de4a046c42d0dc6acc3eae3773975f8bfea8aa675e639fc50c29efe8383e00` | `frontend/src/App.vue`、`src/views/*.vue`；案件工作區的模板由 `frontend/scripts/build_case_workspace.py` 按行號切自原檔 | 完成（Dashboard、產生文件、Target settings 尚未移植，顯示 Alpha 的「Queued for migration」或「later milestone」卡片） |
| `public/app.js`（上述畫面的邏輯） | `a2427dcb41711e94ddacee421a93b560075f414891a72b033ffaa858e2190427` | `frontend/src/views/case-workspace.script.js`、各 view、`src/alpha/constants.js`、`src/alpha/format.js` | 完成（逐函式移植，名稱相同） |
| `public/theme.css`、`public/overview.css`、`public/development-alignment.css` | `af2b57f0…` / `bceafbf2…` / `2da6fba1…` | `frontend/src/alpha/styles/`（原樣，載入順序同 Alpha） | 完成 |
| `migrations/0008_create_case_documents.sql` | `bd0d2ee6e9fc68b2d75fc2093d1886654448743bf2ead2d2a693e742798b8fc1` | `cases/models.py`、`cases/migrations/0002` | 完成（上限改為 10 MB，見下） |

## 只有資料表，尚無 API（Model only）

| Alpha 檔案 | Alpha 雜湊（v53） | VM 位置 |
|---|---|---|
| `migrations/0002_create_cases.sql` | `9e3a6164f8676df6dc0ce6fe4d7e5f9f700bfecd82aa32532fa400ab36b4aa68` | `cases/models.py` |
| `migrations/0006_add_case_uid.sql` | `59ad607b7e4c8f16854812ea7eb71ee332e831857228a837dece540f35ab31a5` | `cases/models.py` |
| `migrations/0007_expand_reinsurance_structures.sql` | `8e4e344972e9c6c8b5e9313514e8d33cc28c87f771ad42eafab95cee4d2dfea2` | `cases/models.py` |
| `migrations/0009_add_announce_workflow.sql` | `cd7b0f75dd953391fd500804ebdd48f53853cf7cb22d5cafbe9e1b9ae37deb4c` | `cases/models.py`（含 ReferenceSequence） |
| `migrations/0014_add_case_owner.sql`、`0015_add_case_owner_index.sql` | `d7b2d9d8…` / `ceb171d9…` | `cases/models.py` |

## 資料（不是程式碼）

| Alpha 來源 | VM 作法 |
|---|---|
| 主檔 74、人員 23、匯率 7（含 `0020`、`0022`–`0025` 產生的資料） | 2026-09-25 以 `import_alpha_reference` 一次匯入，內容雜湊對帳一致；`backfill_audit_baseline` 補上 snapshot 與 Audit 事件。不含 email、不含任何帳號 |
| `0026` 暫停 Audit 的 trigger、`0027`、`0028` | **不移植**（VM 不暫停 Audit；0027／0028 是 Alpha 內部資料修正） |

## 尚未開始

`api/dashboard*.js`（含 `0018`）、
`api/payment-reminders.js`（#9，含 `0029`–`0031`）、`api/signed-slip-reminders.js`（#10，含 `0017`；它用的 `lib/signed-slip-reminders.js` 已完成）、
`api/render-document-pdf.js`（#19、#21）、`api/data-reconciliation.js`、`api/foundation-status.js`、前端其餘部分：Dashboard 畫面，產生 Word／PDF（`docx-generator.js`、`docx-templates.js`、`pdf-generator.js`、`pdf-assets.js`）。Alpha 前端原檔的逐位元組副本在 `frontend/alpha-reference/`。

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
| 案件合計（列表、畫面、記帳） | 三套算法：記帳（`accounting.js`）每步進位到分；案件列表（`cases.js listFinancials`）與畫面（`case-calculations.js`）完全不進位 | **統一用記帳那套**（逐步進位）：`cases/calc/totals.py`。列表、畫面、記帳三處數字相同 | 2026-09-25 你的決定。與 Alpha 未進位算法的差距在分以下；4000 組隨機案件（最多 6 家再保人）實測最大差距：Brokerage 0.06、Leg 1 0.05、Leg 2 0.04。**建議 Alpha 也統一，否則之後兩邊列表數字會有幾分錢的出入** |
| 案件預設負責人 | 找不到登入者對應時退回固定人員 `P.L`（Hatchable 協作者路徑） | 只用「目前登入者」（已確認在職） | 2026-09-25 你的決定；VM 沒有協作者的概念 |
| 案件 API 的數字型別 | 列表的 `id`、`rowVersion` 是字串（bigint），單筆的 `rowVersion` 是數字 | `id`、`rowVersion` 一律是數字 | Alpha 不一致；前端以數字比對較不易出錯 |
| 案件付款條件鎖定（Announce 後） | 比對 `JSON.stringify` 的結果，物件鍵的順序不同也算變動（資料庫會重排 JSON 鍵的順序） | 比對內容，鍵的順序不算變動；內容有任何差異仍然擋下 | 避免因為資料庫重排鍵而誤擋；不會放行任何真正的變更。**尚未拿 Alpha 實測過它是否真的會誤擋，只是依 JSON 語意推論** |
| 主檔名稱比對（案件的 AE／Reinsured／Class 對應） | `lower(name) = lower(x)`（區分重音） | 同樣精確比對（資料庫 ai_ci 先縮小範圍，再用 Python 精確比對） | MySQL 的 ai_ci 會把 `Café` 與 `Cafe` 視為相同，不能直接用 |
| Performance Split 只給名字、且同名者不只一位 | 取到哪一位取決於資料庫回傳順序（不確定） | 拒絕（`invalid_personnel_split`），要求以 ID 指定 | 不同部門可以有同名的人（例如兩位 A.L）；不猜 |
| 首次登入強制改密碼 | 無（Alpha 的登入由 Hatchable 代管） | 管理員建立帳號、重設密碼、重新啟用帳號之後，本人第一次登入必須先改密碼（`personnel.must_change_password`）。後端在授權層直接拒絕所有業務 API（`403 PASSWORD_CHANGE_REQUIRED`），只放行登入／登出／app-context／改密碼；新密碼不能與暫時密碼相同。principal 多一個 `mustChangePassword` 欄位。既有帳號不受影響（預設 false） | 2026-09-25 你的決定 |
| 重新啟用停用的帳號 | 無 | `POST /api/personnel-accounts/enable`、`manage.py enable_ri_account`、Personnel 頁「重新啟用帳號」。沿用原密碼、不發新密碼，但**一律要求第一次登入先改密碼**（帳號可能是因疑似外洩才被停用）；人員本身若已停用（在職狀態）不能啟用帳號。有 Audit（`enable_account`）與 Snapshot | 2026-09-25 你的決定；「啟用後須改密碼」是我加的保守預設，可改 |
| 資料檢視（Django admin `/admin/`） | 無 | 唯讀，只有 System Administrator 進得去（在職、帳號啟用、已完成改密碼）。登入沿用 SPA 的同一個 session（`/admin/login/` 導向 SPA 登入頁）。唯讀三層：站點層拒絕除登出外的所有非 GET 請求、每個 ModelAdmin 沒有新增／修改／刪除權限、站點只接受唯讀的 admin 註冊（Django 內建的 User／Group 含密碼雜湊，不會出現）。可檢視 Case、CaseDocument、ReferenceSequence、Personnel、MasterRecord、FxRate、AuditLog、EntitySnapshot。靜態檔建置時 `collectstatic`，由 Nginx 提供（不增加任何套件） | 2026-09-25 你的決定（先前記錄的「唯讀、僅 admin」）。程式在 `ri_system/admin_site.py`；測試組 `admin_readonly`（67 項），13 種故意破壞都被抓到 |
| Reverse、通知會計的 Snapshot | 只寫 Audit（`row_version` 加 1 卻沒有 Snapshot，版本號有缺口） | 補寫 Snapshot（`case_reversed`、`accounting_notified`） | 2026-09-25 你的決定；建議 Alpha 也補 |
| TW Reference 流水號 | `lpad(…, 3)`：超過 999 會被截斷而產生重複編號 | 不截斷（第 1000 號就是 4 位） | 2026-09-25 你的決定 |
| 案件鏈的並行控制 | PostgreSQL advisory lock ＋ 事後「除以零」檢查 | 先鎖「根案件」那一列，檢查與寫入在同一個鎖內（Announce 鎖該案件列） | MySQL 沒有 advisory lock 的對應用法；行為相同（同時送出的請求依序處理） |
| Reverse 遇到 `transactions` 內有 `null` | 拋 TypeError（未處理的伺服器錯誤） | 409 `transactions_corrupt`，不改任何資料 | 2026-09-25 你的決定（差異測試發現）；正常流程不會寫出 null |
| Announce 之後的 `payload.status` | 資料庫的 `status` 變 `posted`，但 `payload.status` 維持 `draft`（下一次編輯才更新）；Alpha 的 API 與 lib 都沒有讀 `payload.status` | 同 Alpha（照搬） | 只是不一致，沒有已知影響；前端若要讀狀態請用欄位 `status` |
| 對 `/api/case-announce` 發 GET | 405 | 403（權限檢查在方法分派之前） | 兩者都是拒絕 |
| 案件文件單檔上限 | 5 MB | **10 MB**（資料表 CHECK 約束也改為 10 MB：`cases/migrations/0002`） | 2026-09-25 你的決定。Nginx 請求上限 20 MB（10 MB 檔案的 base64 約 14 MB）、Django `DATA_UPLOAD_MAX_MEMORY_SIZE` 16 MB |
| 案件文件的檔案本體 | Hatchable storage | Docker volume `case_documents`（容器內 `/data/documents`），路徑即 `storage_key`；先寫暫存檔再原子 rename；路徑限制在根目錄內 | 2026-09-25 你的決定。**不在 MySQL 備份裡，要另外備份**（見「維運」） |
| 刪除案件文件 | 任何狀態都能實體刪除（連同檔案） | **只有 Draft 能刪**；Announce 之後回 409 `document_delete_locked`，只能取消勾選，檔案保留作為證據 | 2026-09-25 你的決定 |
| `signedSlipReminder.outboundEnabled` | 固定 `true` | 依設定 `RI_SIGNED_SLIP_OUTBOUND_ENABLED`，預設 `false`（VM 尚未設定寄信） | 2026-09-25 你的決定：如實回報 |
| 下載時檔案本體不見 | 未處理的錯誤 | 404 `file_content_missing`（並寫入錯誤日誌） | 不應該發生；發生時要能看出是資料遺失 |
| 檔名含落單的 UTF-16 代理字元（例如 JSON 裡的 `\ud83d`） | Node 寫進 PostgreSQL 時換成 U+FFFD | 同樣換成 U+FFFD 再存（MySQL 不接受落單代理字元） | 結果與 Alpha 相同 |
| 文件 API 的 fileId 是 36 個「-」這類「格式對但不是 UUID」 | PostgreSQL 轉型失敗（未處理的錯誤） | 404 `file_not_found` | |
| 業績月份（Announce 月／批單建立月） | 取時間的 UTC 文字前 7 個字：台北時間每月 1 日早上 8 點前 Announce 的案件算上個月 | 先換成台北時間再取月份（calc 本身不變，只改傳入的文字）；Production 畫面的預設月份也用台北時間的上個月 | 2026-09-26 你的決定（先在 Alpha 以唯讀 `SELECT now()` 確認 Hatchable 回傳 UTC 文字）；**建議 Alpha 也改** |
| Production 的 Audit | 只有關帳寫 Audit | 排除（`exclude_production_row`）、產生版本（`generate_production_report`）也寫；關帳時每個案件補寫 Snapshot（`production_case_confirmed`），被鎖定的匯率寫 Snapshot（`fx_rate_locked`）與 Audit（`lock_fx_rate`） | 依「所有新增與修改都要有 Audit」、「row_version 增加就寫 Snapshot」 |
| 關帳的並行控制 | 事後以「除以零」檢查報表與每個案件的版本 | 先鎖報表與案件列，再檢查版本與狀態；有變動就 409 `close_conflict`，什麼都不寫 | 行為相同 |
| 關帳時 transactions 裡有 null | 拋 TypeError（未處理的錯誤） | 409 `transactions_corrupt`，什麼都不寫 | 同 Reverse 的決定 |
| 預覽的案件順序 | PostgreSQL `ORDER BY announced_at`（空值排最後） | 明確指定空值排最後（MySQL 預設排最前） | 結果相同 |
| Production 排除紀錄 | 程式不修改、不刪除 | 資料庫層也禁止：`ri_runtime` 只有 SELECT／INSERT | 排除會改變業績歸屬，保留完整紀錄 |
| 理賠交易編號 | `${rootCase.twRef}-CLM…`，但傳入的是 payload，沒有 `twRef`，編號開頭是 `undefined`（例如 `undefined-CLM1-P1-R1-TX1`），會出現在 SOA 與 Accounting | 用根案件的 TW Ref（`TWPAR2603001-CLM1-P1-R1-TX1`）；共用的 `build_claim_payment_transactions` 不變，只在呼叫時補上 `twRef` | 2026-09-26 你的決定；**建議 Alpha 也修** |
| 理賠的出險日、付款日期 | 不檢查：可留空，也可以是任何 20 字以內的文字 | **兩者都必填**，且必須是真實存在的日期（400 `invalid_date_of_loss`／`invalid_payment_date`）；畫面加必填標示，「Add claim」的說明改為「Date of Loss is required; the Outstanding Reserve can be updated later.」 | 2026-09-26 你的決定 |
| 理賠準備金與付款金額 | 準備金看不懂的文字安靜地存成 0、可以是負數；金額不進位（100.123 原樣存） | 準備金看不懂的文字回 400 `invalid_claim_reserve`、不可為負（留空仍是 0）；準備金與付款金額都進位到分（進位後是 0 的付款同樣拒絕）。付款**可以是負數**（追償、沖抵，2026-09-25 確認）不變 | 2026-09-26 你的決定 |
| 理賠寫入的 Snapshot 與並行控制 | 只寫 Audit；事後以「除以零」檢查版本 | 補寫 Snapshot（`claim_created`、`claim_reserve_updated`、`claim_payment_recorded`）；先鎖根案件列再檢查與寫入 | 延續 2026-09-25 的決定 |
| 記帳帳本讀取的案件數 | 最多 1000 件（`LIMIT 1000`），其餘直接不顯示、沒有警告 | 全部讀取 | 2026-09-26 你的決定 |
| 記付款、沖銷的案件狀態 | API 不檢查狀態（Draft 也能記；畫面只列 Announced／Confirmed） | 只接受 Announced（posted）／Confirmed（closed），其他回 409 `accounting_status_locked` | 2026-09-26 你的決定 |
| 付款日期 | 記付款只檢查 `YYYY-MM-DD` 的形狀（`2026-13-45` 會通過）；沖銷完全不檢查；預設日期用 UTC 的今天（台灣早上 8 點前是前一天） | 兩者都必須是真實存在的日期（記付款 400 `invalid_payment`、沖銷 400 `invalid_payment_date`）；沖銷沒給日期時與畫面預設都用台北的今天 | 2026-09-26 你的決定；到期日與逾期本來就用台北日期 |
| 記付款、沖銷的 Snapshot | 只寫 Audit | 補寫 Snapshot（`payment_recorded`、`payment_reversed`） | 延續 2026-09-25「row_version 增加就寫 Snapshot」的決定 |
| 記付款、沖銷的並行控制 | 先比對版本，再以 UPDATE ＋「除以零」事後檢查 | 先鎖案件列，檢查與寫入在同一個鎖內 | 行為相同（版本不符回 409 `version_conflict`） |
| 帳本遇到 `paymentEntries` 裡有 `null` | 整個帳本拋錯（`entry.scheduleKey`） | 略過非物件的項目 | 正常流程不會寫出 null；不讓一筆壞資料擋住整個帳本 |
| Accounting 表格的「Partial payment」字樣 | `<br v-if="row.partial"><small>Partial payment</small>`：`v-if` 只套到換行，**每一列都顯示** | 只在真的部分付款時顯示 | 2026-09-26 你的決定（畫面測試發現）；**建議 Alpha 也修** |
| Accounting 點 TW Ref 開啟案件 | 同一頁切換到案件的 SOA 分頁 | 導向 `/cases?case=…&tab=soa`，載入後開 SOA 分頁 | VM 每個畫面是一個路由 |
| Accounting 的 `settle` 動作（標記理賠交易已結清） | 前端有 `settleSelectedTransactions()`，但 API 不支援、畫面也沒有入口 | 不移植 | 無法執行的死碼 |
| 文件頁與 Announce 的再保人名稱比對 | 文件頁（與 Signed Slip 提醒）**不**去掉「(Facility)」，Announce 會去掉 | 同 Alpha（照搬） | 兩處規則不同但實務上一致：上傳時只能選案件上的原名。只有同一案件同時有「X」與「X (Facility)」時兩邊的「需要幾家」才會不同。**建議 Alpha 統一** |
| 丟進回收桶、還原的 Snapshot | 只寫 Audit（`row_version` 加 1 卻沒有 Snapshot） | 補寫 Snapshot（`draft_recycled`、`draft_restored`） | 比照 2026-09-25 你對 Reverse／通知會計的決定（每個版本都要有 Snapshot）；建議 Alpha 也補 |
| 回收桶的並行控制 | 事後「除以零」檢查 | 先鎖案件列（還原時也鎖回收桶那一列），檢查與寫入在同一個鎖內 | MySQL 沒有對應寫法；結果相同 |
| 畫面外觀與語言 | Hatchable 上的單一 HTML＋UMD | 同樣的模板、文字（英文）與 CSS，拆成 Vue 元件並正式建置；左側每一項是一個網址（重新整理、上一頁可用） | 2026-09-25 你的決定：全部照 Alpha 英文、盡量一模一樣 |
| VM 專有的畫面元素 | 無（登入由 Hatchable 代管） | 英文的登入頁、頁首的 Change password／Log out、System Administrator 的 Data viewer（`/admin/`）連結、強制改密碼對話框；Personnel 頁多了登入帳號欄與帳號動作、可重新啟用人員（Alpha 顯示「VM migration only」） | 2026-09-25 你的決定：用英文、與外框一致 |
| 外框的版本條與側欄文字 | 「Alpha · Audit Log paused until VM」等 | 如實描述 VM（Audit 已啟用、哪些畫面還在搬） | 如實回報 |
| 「Correct reversed case」 | 按了沒反應（`startEditCase` 只允許 draft／posted，#7 的確認流程走不到） | 可以用：打開表單，存檔時跳出 #7 的確認，後端也獨立檢查 | 2026-09-25 你的決定（疑似 Alpha 錯誤）；**建議 Alpha 也修** |
| 主檔 API 的 `payload` | 接受 JSON 字串或物件；`null` 是錯誤 | VM 先前的移植只接受物件、`null` 當成沒送；已修正成與 Alpha 相同（`master_payload_compat` 測試組） | 移植時漏掉（Alpha 自己的畫面就是送字串）|
| Case Viewer 打開案件明細 | 呼叫需要 `cases.read.all` 的流程 API，跳出權限錯誤 | 沒有權限時不呼叫（不跳錯誤） | 同樣看不到流程資料，只是不顯示錯誤訊息 |
| 產生 Cover Note／Debit Note／Endorsement（Word／PDF） | 可用 | 卡片照 Alpha，按鈕停用並說明尚未移植 | PDF 作法尚待決定 |
| Claim 分頁 | 可用 | 顯示 Alpha 自己的「will be converted … in a later milestone」卡片 | Claims API 尚未移植 |
| SOA 分頁 | 讀 `payload.transactions` 顯示 | 相同（唯讀；交易要到 Production close 才會產生） | |
| Personnel 的 Annual target settings 頁籤 | 可用 | 「Queued for migration」卡片 | dashboard-targets API 尚未移植 |
| 畫面上的案件合計、分期收入 | `case-calculations.js`（不進位） | `src/alpha/caseCalculations.js`：用 Alpha `lib/accounting.js` 的逐步進位，與後端 `totals.py` 相同（`run_qa.sh totals` 比對 3,000 個案件） | 2026-09-25「統一用記帳算法」的決定 |
| Announce 之後的「Record notification」按鈕 | Announce 後不重新載入流程狀態，要重新打開案件才出現 | 相同（照搬） | 只是不便，沒有錯誤；可以之後一起改 |
| Personnel 停用時間 | 每次儲存都會覆寫 `deactivated_by/at` | 只在「在職 → 停用」那一刻記錄，之後編輯已停用的人不覆寫 | 保留真正的停用時間 |
| Personnel Audit 的 before 內容 | `before_data` 用列表格式（含 `accountBound`、`updatedAt`），`after_data` 用另一種格式 | before 與 after 都用同一種格式（`personnel_state`） | Alpha 兩邊格式不一致，比對差異時不方便 |
| Personnel GET 的 `scope` | `authentication: company_vm_deferred`、`credentialsEnabled: false` | 如實回報：`django_session`、`credentialsEnabled: true`、`rolesEnforced: true` | VM 已啟用登入 |
| Personnel 列表欄位 | 無登入帳號名稱 | `accountUsername`（僅 `accounts.manage` 看得到） | 管理員畫面需要 |
| 停用中帳號換 Email | 解除綁定，可重新邀請 | 解除綁定，可為新 Email 重新建立帳號；舊的 Django 帳號保持停用（`ri_runtime` 沒有 DELETE 權限，也不該刪，稽核仍能對應） | |

## 維運

| 作業 | 指令 |
|---|---|
| 套用 migration（之後一定要重新授權） | `scripts/migrate.sh` |
| **一鍵執行全部驗證**（每次改動後都要跑） | `scripts/run_qa.sh`（可加參數 `suites`／`parity`／`calc` 只跑一部分） |
| 只重新套用資料庫權限與 Audit trigger | `scripts/db_harden.sh` |
| 以維護者身分執行 manage.py（需要 DDL 或 DELETE 時） | `scripts/manage_as_owner.sh <指令>` |
| 建立／停用／重新啟用／重設帳號 | `docker exec ri-backend python manage.py create_ri_account\|disable_ri_account\|enable_ri_account\|reset_ri_password --personnel-id N …` |
| 備份案件文件（volume） | `docker exec ri-backend tar czf - -C /data/documents . > backups/case-documents-$(date +%Y%m%d-%H%M%S).tar.gz && chmod 600 backups/case-documents-*.tar.gz`（與 MySQL 備份同時做，兩者才對得起來） |
| 畫面測試（無頭 Chromium） | `scripts/run_ui_test.sh`：另起用完即丟的測試環境（獨立資料庫、合成資料、隨機密鑰），跑完整套刪除；截圖在 `qa/ui/out/`（不進版控）。正式資料庫完全不動 |
| 前端與後端的案件合計一致 | `scripts/run_qa.sh totals`（`all` 也會跑） |
| 唯讀資料檢視 | 瀏覽器開 `/admin/`（System Administrator；主畫面上方有「資料檢視（唯讀）」連結）。要新增資料表或 model 時，在該 app 的 `admin.py` 用 `ReadOnlyModelAdmin` 註冊，其他寫法會被忽略 |
| 備份 | `docker exec ri-mysql sh -c 'mysqldump -uroot -p"$(cat /run/secrets/mysql_root_password)" --single-transaction --routines --triggers ri_system' > backups/…sql`（`backups/` 不進版控） |

**新增資料表後一定要跑 `scripts/migrate.sh`**：`ri_runtime` 對新表沒有任何權限，直接跑 `manage.py migrate` 會讓網站對新表失敗。

## 切換前的待辦

- **清空測試資料**（2026-09-25 你的決定）：在 VM 上點畫面建立的測試案件（名稱用 ZZ 或 UI 開頭）、文件、回收桶、TW Reference 流水號，要在正式匯入前用一支有記錄、需要 root 執行的腳本清掉（Audit 保留）。執行前先備份並問你。
