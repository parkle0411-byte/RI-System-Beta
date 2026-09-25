# Alpha → VM 搬遷狀態

- 來源：Hatchable「RI System (Alpha)」`proj_FVUqiQUe3m0G`，**記錄基準：v53（2026-09-25，81 個檔案）**
- 目標：本專案（Django + MySQL + Vue，Docker Compose）
- 原則：Alpha 是唯一的正式規格來源，VM 只移植、不自行改規格。刻意不同的地方一律寫在下面「刻意與 Alpha 不同」。

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

## 只有資料表，尚無 API（Model only）

| Alpha 檔案 | Alpha 雜湊（v53） | VM 位置 |
|---|---|---|
| `migrations/0002_create_cases.sql` | `9e3a6164f8676df6dc0ce6fe4d7e5f9f700bfecd82aa32532fa400ab36b4aa68` | `cases/models.py` |
| `migrations/0006_add_case_uid.sql` | `59ad607b7e4c8f16854812ea7eb71ee332e831857228a837dece540f35ab31a5` | `cases/models.py` |
| `migrations/0007_expand_reinsurance_structures.sql` | `8e4e344972e9c6c8b5e9313514e8d33cc28c87f771ad42eafab95cee4d2dfea2` | `cases/models.py` |
| `migrations/0008_create_case_documents.sql` | `bd0d2ee6e9fc68b2d75fc2093d1886654448743bf2ead2d2a693e742798b8fc1` | `cases/models.py` |
| `migrations/0009_add_announce_workflow.sql` | `cd7b0f75dd953391fd500804ebdd48f53853cf7cb22d5cafbe9e1b9ae37deb4c` | `cases/models.py`（含 ReferenceSequence） |
| `migrations/0014_add_case_owner.sql`、`0015_add_case_owner_index.sql` | `d7b2d9d8…` / `ceb171d9…` | `cases/models.py` |

## 資料（不是程式碼）

| Alpha 來源 | VM 作法 |
|---|---|
| 主檔 74、人員 23、匯率 7（含 `0020`、`0022`–`0025` 產生的資料） | 2026-09-25 以 `import_alpha_reference` 一次匯入，內容雜湊對帳一致；`backfill_audit_baseline` 補上 snapshot 與 Audit 事件。不含 email、不含任何帳號 |
| `0026` 暫停 Audit 的 trigger、`0027`、`0028` | **不移植**（VM 不暫停 Audit；0027／0028 是 Alpha 內部資料修正） |

## 尚未開始

`api/cases.js`（#7、#8）、`lib/case-draft.js`、`api/case-announce.js`、`api/case-workflow.js`、
`api/case-documents.js`（#11）、`api/draft-recycle-bin.js`（含 `0005`、`0019`、`0032`）、`api/accounting.js`＋`lib/accounting.js`（#3）、
`lib/payment-terms.js`、`api/production-report.js`＋`lib/production-report.js`（#16，含 `0016`）、`api/claims.js`、`api/dashboard*.js`（含 `0018`）、
`api/payment-reminders.js`（#9，含 `0029`–`0031`）、`api/signed-slip-reminders.js`＋`lib/signed-slip-reminders.js`（#10，含 `0017`）、
`api/render-document-pdf.js`（#19、#21）、`api/data-reconciliation.js`、`api/foundation-status.js`、前端 `public/*`（`app.js` 含 #7、#17、#22）。

不需要移植：`hatchable.toml`、`public/vendor/*`（沿用前端時直接提供即可）、`AGENTS.md`、`README.md`。

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
| Personnel 停用時間 | 每次儲存都會覆寫 `deactivated_by/at` | 只在「在職 → 停用」那一刻記錄，之後編輯已停用的人不覆寫 | 保留真正的停用時間 |
| Personnel Audit 的 before 內容 | `before_data` 用列表格式（含 `accountBound`、`updatedAt`），`after_data` 用另一種格式 | before 與 after 都用同一種格式（`personnel_state`） | Alpha 兩邊格式不一致，比對差異時不方便 |
| Personnel GET 的 `scope` | `authentication: company_vm_deferred`、`credentialsEnabled: false` | 如實回報：`django_session`、`credentialsEnabled: true`、`rolesEnforced: true` | VM 已啟用登入 |
| Personnel 列表欄位 | 無登入帳號名稱 | `accountUsername`（僅 `accounts.manage` 看得到） | 管理員畫面需要 |
| 停用中帳號換 Email | 解除綁定，可重新邀請 | 解除綁定，可為新 Email 重新建立帳號；舊的 Django 帳號保持停用（`ri_runtime` 沒有 DELETE 權限，也不該刪，稽核仍能對應） | |

## 維運

| 作業 | 指令 |
|---|---|
| 套用 migration（之後一定要重新授權） | `scripts/migrate.sh` |
| 只重新套用資料庫權限與 Audit trigger | `scripts/db_harden.sh` |
| 以維護者身分執行 manage.py（需要 DDL 或 DELETE 時） | `scripts/manage_as_owner.sh <指令>` |
| 建立／停用／重設帳號 | `docker exec ri-backend python manage.py create_ri_account\|disable_ri_account\|reset_ri_password …` |
| 備份 | `docker exec ri-mysql sh -c 'mysqldump -uroot -p"$(cat /run/secrets/mysql_root_password)" --single-transaction --routines --triggers ri_system' > backups/…sql`（`backups/` 不進版控） |

**新增資料表後一定要跑 `scripts/migrate.sh`**：`ri_runtime` 對新表沒有任何權限，直接跑 `manage.py migrate` 會讓網站對新表失敗。
