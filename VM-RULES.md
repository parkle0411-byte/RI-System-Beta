# VM 規則與維運（RI System）

VM（`/opt/ri-system`）是再保部系統的**正式系統與唯一規格**。Hatchable Alpha 的搬遷已完成（2026-10-14），之後的修改與新增都直接在 VM 進行；
除錯與驗證以本文件的規則與使用者的決定為準，**不再與 Alpha 比對**。Alpha 搬遷過程的紀錄（檔案雜湊、同步、資料轉換）已封存在 `docs/archive/ALPHA-MIGRATION.md`。

**維護方式**：每次新增或修改業務規則，在文末「變更紀錄」加一段（日期、決定、影響範圍、驗證方式）；規則改變時，舊條目不刪，由新條目註明取代。

## 目前設定

### Audit 記錄暫停（2026-10-05 起）

業主要求 VM Audit 功能先關閉，直至另行通知。已於同日備份後清除當時的 264 筆 Audit（備份 `backups/ri_system_before_audit_clear_20261005_142025.sql`）。
本次以 `compose.yaml` 的 `AUDIT_LOG_PAUSED=true` 暫停 `record_audit`，保持 `AUDIT_LOG_ENABLED=true`，讓業務寫入與 Entity Snapshot 照常；Audit 表的不可修改／刪除 trigger 與權限不變。畫面與 API 如實回報暫停。
只有業主另行要求才重新啟用：將 `AUDIT_LOG_PAUSED` 改為 false 並重建 backend 容器；不補寫暫停期間事件。下方「2026-09 規則決定」表中的「Audit 全面啟用」由本段取代。

### 寄信

寄信關閉（`RI_EMAIL_ENABLED` 未啟用，SMTP 尚未決定）：提醒信以不寄信模式記錄，忘記密碼入口隱藏。設定方式見「維運」。

## 固定技術規格（VM）

| Layer | Stack |
|---|---|
| Frontend | Vue 3.5.43 + Element Plus 2.14.6 + Vite 7.3.6（另有 Vue Router 4.6.4、JSZip 3.10.1） |
| Backend/Admin Panel | Django 5.2.17 + DRF 3.16.1 + Gunicorn 23.0.0 + mysqlclient 2.3.0（Python 3.13.16） |
| Web Server / Reverse Proxy | Nginx 1.28.3 |
| DBMS | MySQL 8.4.11 |
| Host / Container Runtime | Debian GNU/Linux 13（trixie）+ Docker 29.8.2 + Docker Compose v5.6.0 |

各元件的鎖定方式（2026-09-26 實際核對執行中的版本）：

- **Frontend**：`frontend/package.json` 精確版本＋`package-lock.json`，Dockerfile 用 `npm ci` 在 `node:22-alpine` 建置。JSZip 是 Production Report 的 Excel 與 Word 產生用（與 Alpha 同版，2026-09-26 加入）。Alpha 的 Word／PDF 產生檔原樣放在 `frontend/public/alpha-documents/`，不經 Vite 打包。
- **Backend/Admin Panel**：`backend/requirements.txt` 精確版本，基底映像 `python:3.13-slim-bookworm`。Admin Panel 是唯讀的 Django admin（`/admin/`，只有 System Administrator）。
- **Web Server / Reverse Proxy**：`nginx:1.28-alpine`（與前端靜態檔同一個映像）。對外開 80 與 8080 埠：同事用 `http://ri-dev.tw-insure.com`，舊網址 `http://192.168.1.127:8080` 繼續可用。目前是 HTTP（HTTPS 暫緩）。
- **DBMS**：`compose.yaml` 固定在目前使用中映像的摘要（`8.4.11` 標籤在 9/21 被重新打包過，MySQL 版本相同、底層不同，所以固定摘要而不是標籤）。網站以最小權限的 `ri_runtime` 連線。
- **Host / Container Runtime**：主機時區 Asia/Taipei（提醒排程的 cron 依賴它，`scripts/install_reminder_cron.sh` 會檢查）。

要升級任何一項，必須先更新這張表與鎖定檔，並重跑全部測試。

- PDF 產生已於 2026-10 退役（只產生 Word，PDF 由使用者在 Word 匯出）；Gotenberg 容器已移除，舊端點 `/api/render-document-pdf` 固定回 410。

## 金額運算的原則

- 金額用**浮點數**，進位方式為 `Math.round((x + EPSILON) * 100) / 100`（.5 往正無限大）。
  後端刻意重現 JavaScript 的數字語意（`backend/cases/calc/jsnum.py`：`Number()` 解析、數字轉文字、空白定義、日期滾動），
  讓前端畫面與後端計算一致；不要「順手」改成 Decimal。前後端合計一致性由 `scripts/run_qa.sh totals` 檢查。
- Performance Split 兩方合計 100% 時，b 方 = 該 Leg 總額 − a 方（2026-10-14），交易合計與付款排程分毫不差。

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
  若日後代碼會用到這類符號，要先補上對照表。

## 維運

| 作業 | 指令 |
|---|---|
| 套用 migration（之後一定要重新授權） | `scripts/migrate.sh` |
| **一鍵執行全部驗證**（每次改動後都要跑） | `scripts/run_qa.sh`（可加參數 `suites`／`parity`／`totals` 只跑一部分） |
| 只重新套用資料庫權限與 Audit trigger | `scripts/db_harden.sh` |
| 補上分期案件已確認期別缺少的保費交易（先 dry-run，備份後再 `--apply`） | `docker exec ri-backend python manage.py backfill_installment_transactions [--apply]` |
| 以維護者身分執行 manage.py（需要 DDL 或 DELETE 時） | `scripts/manage_as_owner.sh <指令>` |
| 建立／停用／重新啟用／重設帳號 | `docker exec ri-backend python manage.py create_ri_account\|disable_ri_account\|enable_ri_account\|reset_ri_password --personnel-id N …` |
| 備份案件文件（volume） | `docker exec ri-backend tar czf - -C /data/documents . > backups/case-documents-$(date +%Y%m%d-%H%M%S).tar.gz && chmod 600 backups/case-documents-*.tar.gz`（與 MySQL 備份同時做，兩者才對得起來） |
| 畫面測試（無頭 Chromium） | `scripts/run_ui_test.sh`：另起用完即丟的測試環境（獨立資料庫、合成資料、隨機密鑰），跑完整套刪除；截圖在 `qa/ui/out/`（不進版控）。正式資料庫完全不動 |
| 前端與後端的案件合計一致 | `scripts/run_qa.sh totals`（`all` 也會跑） |
| 網址 | 同事使用 **http://ri-dev.tw-insure.com**（公司 DNS 已把這個名稱指向 192.168.1.127；短名 `http://ri-dev` 也可以）；舊網址 `http://192.168.1.127:8080` 繼續可用。Nginx 同時開 80 與 8080 埠；Django 允許的主機名稱在 `compose.yaml` 的 `DJANGO_ALLOWED_HOSTS`。**目前是 HTTP，密碼與資料以明文在區網傳送**（HTTPS 暫緩，見切換前的待辦） |
| 寄信開關 | `RI_EMAIL_ENABLED`（提醒信與忘記密碼共用；舊名 `RI_REMINDER_EMAIL_ENABLED` 仍可用）。啟用前要先設定 `RI_EMAIL_HOST`、`RI_EMAIL_PORT`、`RI_EMAIL_USE_TLS`、`RI_EMAIL_FROM`（SMTP 未決定）。信件裡的連結用 `RI_PUBLIC_BASE_URL`（預設 `http://ri-dev.tw-insure.com`） |
| 提醒排程 | 安裝／更新：`scripts/install_reminder_cron.sh`（`--remove` 移除）；手動執行：`docker exec ri-backend python manage.py run_signed_slip_reminders`（或 `run_payment_reminders`，可加 `--today YYYY-MM-DD` 測試）；結果在 `logs/reminders.log`（不進版控）。**收件人靠人員的 e-mail 與主管 e-mail**：缺了就只記「設定錯誤」（案件明細的 Reminders 分頁看得到） |
| 唯讀資料檢視 | 瀏覽器開 `/admin/`（System Administrator；主畫面上方有「資料檢視（唯讀）」連結）。要新增資料表或 model 時，在該 app 的 `admin.py` 用 `ReadOnlyModelAdmin` 註冊，其他寫法會被忽略 |
| 備份 | `docker exec ri-mysql sh -c 'mysqldump -uroot -p"$(cat /run/secrets/mysql_root_password)" --single-transaction --routines --triggers ri_system' > backups/…sql`（`backups/` 不進版控） |

**新增資料表後一定要跑 `scripts/migrate.sh`**：`ri_runtime` 對新表沒有任何權限，直接跑 `manage.py migrate` 會讓網站對新表失敗。

**測試組的執行環境**：多數 `backend/qa/suites` 需要 `RI_DISPOSABLE_QA=true` 且 Audit 記錄啟用，**不要在正式容器跑**（正式 Audit 暫停中）。一律用 **`scripts/run_isolated_qa.sh`**（全部約 30–40 分鐘；可只列出要跑的測試組，例如 `scripts/run_isolated_qa.sh cases_api accounting_api`；`KEEP=1` 保留環境除錯）：以目前原始碼建專用映像 `ri-backend:isoqa`、起隔離的 MySQL＋後端（`qa/isolated/compose.yaml`，`ri_runtime` 連線並套用 `db_harden.sh`），每組前重建全新資料庫，結束自動刪除。**每次改功能後、部署前都要跑**，全部通過才部署。前端與後端合計、密碼規則一致性仍用 `scripts/run_qa.sh totals`／`parity`。

**畫面測試**（`scripts/run_ui_test.sh`，無頭 Chromium，另起用完即丟的環境）：2026-10-15 全部階段 A、H、R、B0、B、K、C、E、F、D、G、P1、P2 共 185 項通過。`UT_BACKEND_IMAGE`／`UT_FRONTEND_IMAGE` 可指定用目前原始碼建出的映像（預設是正式在跑的 `ri-backend:local`／`ri-frontend:local`，可能比原始碼舊）。階段 D（Accounting）排在 F（Production close）之後，因為交易要關帳後才產生；畫面改版時請同步更新對應階段的欄位標籤與流程。

## 2026-09 規則決定（原「刻意與 Alpha 不同」）

> 2026-09 搬遷期間做的規則決定。「Alpha」欄是當時的對照，只供理解規則由來；現行規則以「VM」欄及下方「變更紀錄」較新的條目為準。

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

## 變更紀錄

### 2026-10-05：VM 高優先度 Bug 修正（Owner 已確認規則）
- Production 關帳、產生報表、排除與匯率存檔共用 MySQL 月份操作鎖。遇到同月份操作衝突，立即回 409 operation_busy，提示稍後重試，不等待。
- 匯率或來源變動後拒絕關帳，要求重新預覽並產生報表；關帳交易內再次核對匯率集合、數值及版本，衝突整筆回滾。
- 排除業績自動跳過已關帳月份，延到第一個未關帳月份；來源、目的月份均保護到提交完成。
- 帳號停用、降權及人員離職共用 ri_operation_locks 的 admin_accounts 交易鎖；第一筆可完成，移除最後啟用管理員的另一筆拒絕。
- 新 migration coordination.0001_initial；ri_runtime 對新鎖表僅 SELECT、INSERT、UPDATE。
- Audit 仍暫停直至另行通知。此次僅修高優先度項目；兩個中優先度 Bug 依 Owner 決定另行安排，尚未修正。未同步修改 Hatchable Alpha。
- 並行回歸測試只可執行於隔離測試資料庫，因測試需提交資料讓其他連線可見；不可在正式 VM 資料庫執行。


### 2026-10-06：VM 中優先度 Bug 修正（Owner 已確認小數處理規則）
- 付款先沿用既有 money() 四捨五入至兩位小數，再檢查實際存入金額必須大於 0。拒絕零金額，不新增付款、Snapshot 或版本；超額付款也使用實際存入金額判斷。
- 主檔新增／更新、匯率、登入及改密碼先確認請求是物件。非物件 JSON 回 400 invalid_body；保留既有認證、CSRF、權限及限流。
- 匯率逐項檢查物件，NaN／sNaN／Infinity 等非有限值回 400；版本數字溢位回 400。儲存前四捨五入至六位小數，結果為 0 時拒絕，回應及 Snapshot 與資料庫數值一致。
- 主檔評等清單拒絕非物件項目；主檔 id／rowVersion 溢位回 400。
- 無新增 migration。原有高優先度交易鎖及 Audit 暫停規則維持；未同步修改 Hatchable Alpha。
- 回歸測試 input_validation.py 在交易內執行並回滾，不留下測試資料。


### 2026-10-06：補充 Bug 修正（依 Owner 指定順序與規則）
- 關帳提交前在 production_sources 交易鎖內重讀完整預覽；案件公告、編輯、理賠、付款與工作流程寫入先取得同一保護。案件可先完成；來源有變動則拒絕關帳並要求重新產生報表。
- 公告的業績月份已關帳時，自動建立排除紀錄延到第一個未關帳月份，保留原保單日期與金額；支援分期、跨年與連續關帳月份，前端提示延後月份。
- 匯率新增／修改以 closed 報表判定月份鎖定，無匯率列的已關帳月份也拒絕寫入。
- 理賠準備金及付款在既有兩位小數四捨五入後再驗證有限值；保留負數沖抵及合法零準備金，避免空值／零交易。
- 密碼重設在管理員操作保護及使用者列鎖內重新檢查 token、啟用狀態及 Personnel 資格；同一 token 並行僅一筆成功。
- Alpha 匯入先建立完整主檔對照，再轉換 fixedClauses[].classIds；匹配既有主檔與反向對帳使用轉換後範圍，獨立完整性檢查拒絕漏轉、錯誤 Class 及非 Class 引用。
- 無 migration；Audit 維持暫停。本次沒有執行正式 Alpha 匯入。


### 2026-10-06：忘記密碼完整流程檢查與修正
- 含 @ 的合法帳號先以帳號名稱辨識，再嘗試 Personnel e-mail。
- 遺失、非數字或超大 auth_user_id 不再造成 500；已停用 Django User 不寄信。
- 申請／重設要求 JSON 物件及字串欄位，拒絕把陣列轉成新密碼。
- 申請／重設使用單一表單提交並防止重複送出；重設後下次導航重讀登入狀態。
- Nginx access log 遮蔽重設連結及 Referer 中的 token；SPA HTML 使用 no-store、no-referrer。
- 隔離 MySQL/API/並行/Chromium 共 136 項通過，另驗證實際 token 未出現在測試 Nginx 日誌。前端建置及 nginx -t 通過。
- 寄信仍未啟用，SMTP 尚未設定；Audit 維持暫停。沒有 migration，正式帳號／密碼與業務資料未改動。


### 2026-10-06：Accounting 改以 SoA／Transactions 對帳
- Accounting 預設顯示已儲存的 SoA 保費、理賠與沖銷交易：SoA／Statement no.、Transaction no.、Reconciliation Ref、Leg、對象、金額與結清狀態。
- 可依 SoA、交易編號、對帳參考號或 TW Ref 搜尋；提供幣別、再保人／R/I Broker、公告日期、Leg、來源與結清狀態篩選。
- transactionRows 沿用案件 SoA 的參考號與分期付款結清規則；納入 Reversed 案件歷史，不產生交易、不改寫既有交易。
- 原有 rows 及記付款／沖銷 API 保留；Payment schedule 為獨立子分頁。會計可直接讀取對帳交易，既有案件讀取權限維持。
- 在獨立 MySQL 與 Chromium 驗證會計 API、分期／理賠／沖銷對帳資料與畫面操作；沒有 migration。Audit 與寄信設定維持。
- 本次只更新 VM，未同步 Hatchable Alpha。


### 2026-10-06：交易編號改為 T／C
- 新保費交易編號的 TX1／TX2／TX3 改為 T1／T2／T3；理賠交易的 CLM{id} 改為 C{id}。分績 a／b、分期 I{n}、更正週期 C{n} 與沖銷 RVS{n} 後綴沿用。
- Accounting 與案件 SoA 以共用顯示函式呈現歷史交易的新寫法，包括沖銷引用文字；Accounting 同時接受原始與顯示編號搜尋。
- 歷史 payload／Snapshot／Audit 的原始交易編號保持原樣，沒有資料重編或 migration；新交易直接儲存新格式。
- 會計與交易金額、Leg、結清狀態沿用原規則。
- Alpha 原始碼測試副本與雜湊保持原樣；差異測試僅轉換 Alpha 預期輸出中「新產生交易」的編號，其餘欄位與歷史交易嚴格比較。
- 隔離驗證涵蓋理賠 API、Production 關帳、分期補登、編碼、計算差異及 Chromium 的 Accounting／案件 SoA 顯示與搜尋；Audit／寄信設定維持。
- 本次只更新 VM，未同步 Hatchable Alpha。


### 2026-10-06：前端金額格式、Case 預設值與 Claim 對象
- 12 個金額輸入欄位使用共用 formatter/parser 顯示千分位；保留數字型別、原有小數位、上下限與理賠負數沖抵。百分比、匯率及天數不改。
- New case 預設 TWD、Cedant/Reinsurer Tax 1%、登入 Personnel 姓名作 AE；新增再保人列 Tax 預設 1%。既有案件載入、續保及批改的資料沿用原值。
- New case 選 Effective date 後帶一年後 Expiration date，閏日用翌年 2/28；手動設定迄日及既有案件編輯不覆寫。
- 共用 Claim 對象顯示：Leg 1 顯示 Reinsurer/R/I Broker；Leg 2 顯示 Cedant。Accounting SoA、Payment schedule、Case SoA 共用此邏輯，Recipient 也顯示 Cedant 名稱；保留原始交易的 reinsurer 分配關聯。
- 模板產生程式同步，重新產生保持既有 VM 修正與本次修正。
- 隔離 MySQL/Chromium 驗證輸入、存檔、既有零稅率及日期保留、會計付款及 Claim Leg 名稱。只部署前端；後端、資料、Audit 與寄信設定維持。


### 2026-10-06：批單退保費（保費差額，不走 Reverse）
- 依使用者確認：批單輸入本次保費差額，正數加保費、負數退保費；原保單與原交易保留。
- 後端僅允許資料庫確認為 endorsement 且有 parent_case 的批單填負保費；原保單及續保維持非負限制，批單 parentTwRef/序號由原流程資料固定。
- 批單保費、再保保費與分期保費支援負數；保費差額欄位可在風險鎖定時編輯，風險與條件維持鎖定。分期差額須與總保費同方向，依絕對值比例分攤並保留原計算進位。
- 新退保費交易沿用 E{n}/T1/T2/T3，T1 應退分保人、T2 應向再保人或 RI Broker 收回、T3 經紀費差額；不標記 Reverse 或 RVS。零經紀費的退保費批單仍能列入 Production 並產生交易。
- 負數付款排程保留 signed amount/paid/outstanding，狀態與結清依絕對值計算。操作輸入正數現金金額，後端依原排程方向存入負數退款/回款紀錄，保留原超額、版本與付款沖銷檢查。
- 非分期退保費的到期基準使用批單生效日；分期依各期基準日。提醒能識別負餘額及應退/應收方向。
- Accounting 與 Case SoA 顯示實際對象及收付款方向；保費 Leg1 顯示分保人，Leg3 顯示 Broker。財務 Leg3 沿用經紀費差額及未追蹤付款狀態。
- 隔離 QA 驗證批單建立、存檔、Announce、Production 關帳、非沖銷交易、退款/回款、分期進位、提醒及原保單完整保留；既有 API 與 frozen Alpha 差異驗證維持。沒有 migration 或正式資料改寫。


### 2026-10-06：0609 AUW Facility 額外手動 TW Ref.
- 依使用者確認：保留既有自動 TW Reference，另加案件層級 TW Ref. (Manual)，不以手動編號替換流水號。
- 再保人名單包含 Lloyd's Underwriter Syndicate No. 0609 AUW (Facility) 時顯示欄位；混合再保人案件也適用。草稿可先留空，Announce 前前後端檢查必填，已公告及更正案件也不可存成空白。
- 手動編號以文字保留前導零及標點、去前後空白，上限 160 字元。案件概覽、列表及 Accounting SoA／Payment schedule 顯示兩組編號，列表及會計可依手動編號搜尋。
- 移除指定再保人後，存檔清除額外編號；新增續保與批單草稿清空手動編號供重新輸入。既有 Reinsurer Ref.、交易編號與上帳金額沿用原規則。
- 隔離 API／MySQL／Chromium 及原有流程回歸驗證通過。沒有 migration 或既有資料改寫；未變更文件產生、Audit／寄信設定，未同步 Hatchable Alpha。


### 2026-10-06：TW Ref. 顯示合併及順序
- 依使用者指定：自動 TW Ref. 在前、AUW 手動編號在後，以 & 連接；例如 TWPF2601001 & TW26SM010001。
- 案件列表及預覽、案件標題及概覽、Case SoA、Reminders、Accounting SoA／付款排程及付款視窗使用同一顯示函式。原來兩個列表欄位合併成 TW Ref. 一欄。
- 案件及會計搜尋同時支援完整合併文字或任一單獨編號；一般案件只顯示自動編號。手動輸入欄位仍只編輯 AUW 編號。
- 只部署前端。後端、兩個原始欄位、交易編號、文件產生、既有資料及 Audit／寄信設定維持。隔離 Chromium 驗證順序、畫面、搜尋及原始資料不變。


### 2026-10-06：AUW 保費固定比例及 Draft Policy Period
- 指定 0609 AUW (Facility) 再保人列的 Deductions 固定 10%、Reinsurer Tax 固定 0%。選取及載入編輯時自動帶入，欄位鎖定；後端新增／儲存一律寫固定值。其他再保人、Cedant 的比例及稅率保留各自原值。
- 舊 AUW Draft 若仍是其他比例，前後端拒絕 Announce，要求先編輯存檔。既有交易與文件不重算、不改寫。
- 已實際重現：Effective Date 鍵入後按 Tab，新案會帶一年後日期，已存 Draft 因 isEditing 檢查被跳過而不帶。修正空白迄日 Draft 可自動帶一年，並以日期模型監看補強；閏日帶翌年 2/28，手動或既有非空迄日保留。已公告及批單的原日期行為維持。
- 隔離 API／MySQL／Chromium 驗證固定比例、混合再保人、零稅率上帳金額、批單退款、鍵入及重開 Draft 的日期；既有流程與 Alpha 計算差異回歸通過。沒有 migration 或正式資料批次改寫。


### 2026-10-06：AUW Deductions 改為可修改的選取預設值
- 依使用者確認：選取 Lloyd's Underwriter Syndicate No. 0609 AUW (Facility) 時，只有該列 Deductions 自動帶入 10%；欄位可修改。儲存、重開及 Announce 保留最後輸入的比例，包括 0%。
- 移除前後端強制 Deductions 10% 的覆寫及公告限制；仍驗證 0–100% 的數值。草稿可保留空白，但公告前必填。選取其他列再保人不會重設既有 AUW 的比例。
- 使用者確認 Reinsurer Tax 維持固定 0% 並鎖定；其他再保人與 Cedant 的條件維持各自數值。
- 隔離 MySQL/API/Chromium 實測選取預設、手動修改、儲存重開、混合列及 0%；實際 Announce、Production 關帳及 SoA 驗證 8,000 保費、12.5% Deductions，應付 7,000；退費 -800 對應 -100 Deductions、-700 淨額。批改與續約沿用既有案件比例。
- 保留已部署的 Policy Period 與雙 TW Ref. 行為。沒有 migration 或正式案件、交易及文件批次改寫。


### 2026-10-06：AUW Facility 月底＋120 天付款及新案 Cedant 90 天預設
- 使用者逐項確認：0609 AUW (Facility) 保費付款採適用日期所在月底＋120 個日曆天，實際付款日期遇假日不順延；Accounting 與既有提醒採實際日期前 10 天，12:00 Taiwan。單期按保單生效日、分期按各期付款基準日、批改補退保费按批改生效日。
- AUW 120 天為固定條件，前端選取及載入時帶入且鎖定，分期 AUW override 也鎖定；後端固定 120 且排程忽略其他付款天數覆寫。Deductions 仍預設 10% 且可修改，Tax 維持 0%。
- 所有既有 AUW 排程讀取時套用新日期，原收付款紀錄、付款對應 key、交易及上帳分錄保留。Accounting 顯示月底基準、會計提前日期、AUW 實際付款日期，避免混淆。
- 使用者確認 Cedant 收款 95% 以上為保單生效日＋90 天；所有新案的 Case Payment Terms 預設 90 且可修改，會計仍提前 15 天。新案以 Cedant 自身的 Case／Installment terms 計算，不受再保人 override 影響；新建及工作流程的新 Draft 記錄 cedantTermsBasis=case。既有非 AUW 案件保持舊最短再保期限算法，既有已填天數及複製案件的明確條件保留。
- AUW 固定條件以 canonical payment_terms_signature 比較，避免舊已公告案件 null／舊 override 因載入帶 120 而誤判已改付款條件；其他付款條件與計算模式公告後仍鎖定。
- 隔離 MySQL／API／Chromium 驗證：同月不同日、月底長短與閏年世紀、跨年、分期、補退保費、既有付款／沖銷與提醒日期，以及新案 90 天、手動例外及既有 180 天保留。既有案件／會計／關帳／批改及 Alpha 計算差異回歸通過。沒有 migration 或正式資料批次改寫。


### 2026-10-07：Board of Directors／President 正式唯讀角色
- 使用者指定 David Kao／david.kao@tw-insure.com，Department=Board of Directors，Role=President；先建立 Personnel，暫不開通登入帳號。Board of Directors 預設不列入業績分配。
- 新增正式 president 角色，所有相同角色共用：Dashboard 全案、Account List 全案（含他人草稿）、文件閱讀下載、Reinsurance MDM、Production Report、Accounting、FX Rates 唯讀。排除 Personnel & Accounts、Draft Recycle Bin、Audit Log；不授予寫入、公告、人員、帳號、目標設定、系統管理權限。
- 前後端新增 board_of_directors／president 選項與預設；Personnel migration 0004 擴充既有 CHECK 約束允許值，保留既有資料與未知值拒絕檢查。
- 修正案件頁 Record notification 缺少 cases.write 判斷，以及唯讀草稿文件頁狀態徽章誤顯示 Announced；既有各項修改／上帳／理賠／文件／收付款／Production 操作由後端既有權限與角色檢查拒絕。登入者修改自己的密碼仍沿用帳號安全流程。
- 隔離資料庫測試 President 跨所有者草稿與各種案件狀態、業務讀取、排除 API、每項寫入拒絕且資料指紋不變；既有角色登入及人員帳號、案件流程、會計、關帳、文件、理賠回歸通過。Chromium 驗證部門角色下拉預設、人員名冊及唯讀頁面、禁止頁面導向。


### 2026-10-07：President 作為所有部門的 Supervisor 選項
- 使用者確認所有部門都能選 David Kao 為 Supervisor，禁止選自己，既有主管不改寫；並說明 President 只有一位，因此以在職 President 角色納入跨部門主管候選，現在為 David Kao。
- Personnel 前端 Supervisor 選項及後端 resolve_supervisor 同時擴充：同部門在職人員、在職 General Manager、在職 President；未開通登入帳號不影響主管候選資格。停用在職人員仍排除；編輯時排除自己；原同名主管解析的同部門優先與 id 次序保留。
- 選取時顯示 David 的 Email，後端依人員資料解析，忽略客戶端傳入的錯誤 Supervisor Email，讓後續主管提醒沿用正確聯絡資料。現有 SupervisorName／Email 與 David 帳號、在職、分績設定均保留。
- 隔離 Personnel／Accounts 回歸及八部門 President Supervisor API、Chromium 驗證通過：跨部門選取、新增／編輯儲存、自動帶 Email、未開通帳號可被選取、停用排除、不能選自己、舊 General Manager／同部門規則保留。沒有資料庫 migration 或正式人員資料批次修改。


### 2026-10-07：AUW Draft 手動 Ref. 必填及 Howden 綁定
- Placement 包含 0609 AUW (Facility) 時，新增／編輯 Draft 必須填單行、最多 160 字的手動 TW Ref.；前端提示並阻擋，後端獨立驗證。Announce 仍保留原有自動流水號及自動 & 手動 Ref. 顯示。
- AUW 的 Foreign RI Broker 自動帶入 Howden Specialty Limited 並鎖定；後端強制正規化，Announce 亦檢核。改成非 AUW 時解除鎖定、清空 Howden。混合 Placement 的其他再保人欄位保留獨立設定。
- AUW 續保／批改先提示輸入新 Ref.，後端檢查後才建立新 Draft，不沿用來源手動 Ref.；一般案件沿用原工作流程。
- 經使用者確認，既有 AUW 案件批次補上 Howden，逐案提升版本並留存 Snapshot；只改 AUW foreignBroker，既有稅率、Deductions、金額、手動／自動 Ref.、交易及收付款紀錄保留。缺少手動 Ref. 另輸出待補清單，不生成替代編號。Audit 暫停及寄信設定沿用。
- 隔離資料庫 API、既有案件／工作流程／Accounting／Production 回歸及 Chromium 實際操作驗證通過，包含必填阻擋、後端防繞過、混合 Placement、續保／批改、舊案修正與重跑不重複寫入。


### 2026-10-07：AUW 與批單單期結算規則
- 手動 AUW 欄位及提示改為 TW Ref. (for AUW)。AUW 改選其他再保人時，清空 Howden、Deductions、Tax、再保人付款天數及其分期覆寫；新選 AUW 仍帶入可修改的 10%、固定 0% Tax 與 Howden。
- 所有批單不允許保費分期；工作流程建立單期，前端停用分期及 Cedant 天數，後端依實際 case_kind 拒絕繞過。原保單、續保保留原有分期。
- 批單 Cedant 天數繼承原始保單，不沿用中間批單；以台北時間實際 Announce 日與批改生效日較晚者加原保單天數，會計提前 15 天。AUW 批單採同一較晚日期的月底加固定 120 天，會計提前 10 天，遇假日不調整。非 AUW 再保人原付款規則保留。
- Announce 時寫入伺服器認定的時間；草稿不推測公告日，後續修改不接受使用者偽造時間。公告後批改生效日依既有付款條件鎖定。
- 經使用者確認，TWPF2609001-E01 改為單期，新日期適用，原始業績合併歸屬 2026-09；9 月已關帳，透過新增不可改寫的 exclusion 遞延到下一個未關帳月份。已關帳報表、原保單、稅率、佣金、保費、既有上帳與收付款紀錄不改寫；缺少 AUW Ref. 沿用待補，不生成號碼。保留版本與 Snapshot。
- 隔離 API、帳務／Production／負保費回歸及 Chromium 實際操作驗證通過；既有批單修正可重跑且不重複寫入。


### 2026-10-07：Finance 案件唯讀、President 文件限制、主管新增下屬
- 使用者逐題確認 A/B/A/A/A：Finance Staff 與 Finance Manager 可檢視全部 Account List、案件明細、流程與理賠，保留原帳務權限，不新增案件寫入或文件權限；President 隱藏整個文件區，不能預覽、產生、下載、上傳、勾選或刪除文件。
- 有其他 Personnel 指定本人為 Supervisor 即具主管身份，依既有同部門優先與同名排序規則判斷。所有角色可依此取得 personnel.read.team 與 personnel.create.subordinate；不授予 personnel.write 或 accounts.manage。移除最後一筆主管指定後，後端立即收回窄範圍權限。
- 主管只能新增本人所屬部門的下屬；角色固定為再保部 sales、財務部 accounting、其他部門 viewer；Supervisor 固定本人、主管 Email 由後端解析。非原 personnel.read 角色只可讀本人及同部門直屬下屬，不能編輯既有人員；General Manager 保留既有全人員唯讀，System Administrator 保留完整人員與帳號管理。新增人員不建立或啟用登入帳號。
- 前端新增 Add subordinate 操作，部門、角色與主管固定，隱藏無權限的人員編輯、帳號管理、業績目標及文件入口；後端拒絕跨部門新增、角色升權與換主管。保留原案件負責人轉移、Draft 文件刪除、5 年還原與禁止永久刪除規則。
- 213 項新權限 API 驗證、12 套隔離回歸及 Chromium 驗證通過。無資料庫 migration；正式資料表內容指紋與筆數、Email 與 Audit 暫停狀態於部署前後一致。


### 2026-10-07：主管可建立直屬下屬登入帳號
- 使用者選擇 A：已有下屬的主管可為既有或新增的同部門、一般角色直屬下屬建立登入帳號。一般角色依部門固定為 reinsurance=sales、finance=accounting、其他=viewer。
- 新增 accounts.create.subordinate 動態權限，僅建立帳號 API 採 accounts.manage 或此權限；停用、重新啟用及重設密碼仍限 accounts.manage。主管不能修改既有人員、角色、主管或 Email，也不能為自己、同部門非下屬、跨部門、非一般角色、非在職或已有帳號的人員建帳號。
- 帳號建立沿用 ADMIN_ACCOUNTS 共用交易鎖，在鎖定後重新驗證主管及人員現況；主管只能使用既存 Personnel Email。維持密碼強度、一次性回傳、首次登入強制改密碼與 Audit/Snapshot 原子寫入。
- 前端僅在後端 canCreateAccount 為真時顯示 Create account；一般主管僅取得其直屬一般角色下屬的帳號名稱，其餘管理控制仍隱藏。
- 主管權限 API、既有帳號/密碼/角色與 President/主管回歸及 Chromium 瀏覽器驗證通過，詳見 Supervisor-Accounts-2026-10-07 驗證產物。無 migration；正式資料與帳號指紋及設定於部署前後一致。


### 2026-10-07：Finance Staff 業績唯讀、President 人員與帳號唯讀
- 使用者確認 Finance Staff 可檢視月業績預覽與既有版本、下載既有版本 Excel，但不能產生報表或排除業績列；關帳仍不允許。Finance Manager 與 System Administrator 保留產生、排除及關帳權限，財務兩角色原帳務操作及全部案件檢視保留。
- 使用者選擇 A/A：President 可唯讀全部部門的人員，不能新增 Personnel，也不能建立登入帳號。新增 President personnel.read；主管身份仍可由 Personnel 指定成立，但 President 不取得任何主管額外寫入權限。帳號服務在鎖定現有資料後亦拒絕 President。
- 業績 API 的 readOnly 與 canOperate 正確反映角色，已知無權限的寫入在取得月份鎖及計算來源前回 403；前端隱藏寫入按鈕並使用唯讀說明，既有 XLSX 下載保留。
- President 全人員名單入口可用，前端不顯示人員新增、修改、停用或帳號建立、重設等控制。其他主管同部門一般角色下屬新增與建帳號規則保留。
- 隔離角色權限、人員帳號、密碼、President、業績 API 回歸及 Chromium 操作與實際 XLSX 下載驗證通過，產物見 Role-Refinement-2026-10-07。無資料庫 migration；正式資料、帳號及設定部署前後一致。


### 2026-10-07：Dashboard 貨幣位置與標題
- Total Gross Premium 及 Outstanding · Cedant / Reinsurer 改為 TWD 前綴，例如 TWD 0 與 TWD 0 / 0，保留原有千分位格式。
- 趨勢標題改為 YTD Brokerage Trend (TWD)。
- 僅調整 Dashboard 前端顯示；正式建置與獨立 Chromium 驗證零值及非零金額，既有資料及後端維持。


### 2026-10-07：Dashboard Total Bound YTD 標題
- YTD Case Volume 改名為 Total Bound YTD；沿用原有當年及去年同期計數，後端計算規則維持。
- 前端建置與獨立 Chromium 檢查標題、當年及去年同期數值，以及既有 TWD 格式。


### 2026-10-08：Accounting 合併 SoA／Transactions 與收付款
- 改為單一交易列表，每筆既有 Transaction 顯示 SoA、對帳參考號、實際對象、到期日、已收付、未清餘額及操作；不列出尚未生成交易的付款排程。
- 同幣別、同收付方向、同實際交易對象可跨案件／分期登錄一筆匯款。每筆交易手動分配，可部分收付；分配合計須等於匯款總額。版本、餘額或任何一筆驗證失敗時整批不寫入。
- 新 paymentEntries 記錄原始交易編號、共同 batchId、匯款參考號與金額；每案件只增加一次版本，保留 Snapshot 與原有 Audit 設定。既有排程收付以整數分攤，現金不重複計算。
- T3 是保留經紀費，沒有獨立匯款登錄；對應的 T1／T2 全結清後自動結清，沖回後重新反映狀態。
- Claim 紀錄建立應收應付，實際向再保人收款及付給分保人分別在 Accounting 登錄；Claims 的文字改為 obligation。案件 SoA 即時顯示一致的收付／結清狀態。
- 更正匯款必須整筆新增不可覆寫的 reversal，保留所有原始分配。原有單筆付款 API 保留相容性，但不能繞過整批沖回規則。
- 50 項新會計 API、既有案件／Production／理賠測試及實際 Chromium 操作驗證；7,100 組計算向量與部署前完全相同，既有 Alpha 差異不增加。無 migration、未更改正式資料、Audit 暫停與寄信關閉維持。此批為 VM 更新。


### 2026-10-08：移除共用頁框開發提示
- 移除所有登入後分頁的 VM 版本／Audit 狀態與案件／提醒信搬遷說明列。
- 移除左上角「再保部 | VM」與「Facultative Outward — Phase 1」；登入、忘記密碼與重設密碼頁的同名標示一併移除。
- 前端 production build 與正式靜態檔核對通過。僅四個 Vue 顯示模板變更，後端服務、業務資料與設定不變。


### 2026-10-08：主分頁說明文字
- Dashboard：Production & Records Overview。
- Account List：All outward cases；共用路由與案件工作區的頁首設定同步更新。
- FX Rates：Official monthly foreign currency to TWD rates。
- 前端建置與正式靜態檔核對通過；僅說明文字調整。


### 2026-10-08：Risk Details 欄位排列與 Type 寬度
- 第 1 排：Reinsurance structure、Case owner、AE、Currency。
- 第 2 排：Class、New / Renew、Type；Type 佔兩格。
- 第 3 排：Reinsured、Original insured (EN)、Effective date、Expiration date。
- Type 輸入改為依內容自動增高的文字欄位；固定的 structure suffix 保留。窄螢幕仍依兩欄／一欄排列。
- 前端建置、瀏覽器欄位排列與長文字顯示檢查通過；僅重建 nginx 前端，業務資料及後端不變。


### 2026-10-08：Case Overview 上傳與 Announce
- Review & Announce 自 Cover & Debit Note 移至 Overview；正式確認對話框及 Announce API 保留。
- Overview 與 Cover & Debit Note 均提供 Upload Evidence，共用檔案種類、待上傳檔案與已上傳資料。
- 首次開啟案件即載入證據；切回 Overview 更新覆蓋狀態。Overview 顯示缺漏提醒、證據覆蓋與所選檔案。
- 前端建置及隔離瀏覽器流程檢查通過；僅更新前端，後端與業務資料不變。


### 2026-10-08：Case Documentation 分頁名稱
- Case 中 Cover & Debit Note 分頁名稱與對應頁首改為 Documentation。
- 模板產生器及既有 UI 測試選取器同步更新。
- 前端建置及正式靜態檔文字核對通過；上傳及 Overview 的 Review & Announce 保留。


### 2026-10-08：純 AUW 以手動 Ref. 作為主編號
- 純 AUW 原保單、續保及批單 Announce 直接採手填 TW Ref. (for AUW)，不產生、查詢或消耗流水號；混合及一般案件保留自動 TW Ref.。顯示相同主／AUW Ref. 時去重，混合案件維持自動編號在前。
- 手動 AUW Ref. 在 Draft、修改、批單、續保及 Announce 檢查與其他案件的主編號、手動編號及舊編號衝突；回收與封存案件仍保留編號。共用序列化鎖避免併發重號，自動流水號略過已被手動 Ref. 保留的值。手動主編號公告後鎖定。
- 主編號與流水號前綴欄位擴為 192 字元，保留手動 Ref. 160 字元限制，並保留長 Ref. 的批單／續保來源連結。純 AUW 批單業績編號由正式 endorsementSeq 判定。
- 使用者將免文件決定改為 C：原有 Offer Slip、所有再保人 Signed Slip／Confirmation E-mail 及 Signed Slip 提醒規則全部保留。
- 既有純 AUW 案件僅製作轉換清單；本次未變更案件、帳務、文件、報表、流水號或其他業務資料。經確認後才可使用有版本、歷史及關聯防護的轉換工具。
- 隔離 API 回歸與逐字鍵盤、滑鼠錄影驗證通過，包括 Production 關帳、Accounting、批單及續保。


### 2026-10-08：已批准既有 AUW 主編號轉換
- 使用者選 A，僅將 Polystar／Starich（fb43316b-126d-4e0b-be26-ba93b7553771）主編號 TWPF2311001 改為 TW23SM010736；舊號保留 previousTwRefs 可查詢且不能再分配。
- 轉換前核對第 9 版、純 AUW placement、未上帳／無現金／無理賠／無報表或續保批單關聯；同一交易內只變更主編號與來源／歷史 metadata、版本與編輯資訊，新增一份 Snapshot。金額、日期、文件與流水號內容保留；Audit 暫停、寄信關閉設定保留。
- 歷史 Ref. 改以文字 casefold 比對，避免 MySQL JSON 陣列大小寫敏感導致舊号重用；API、轉換防護與搜尋驗證通過。


### 2026-10-08：Production Report 新增 First Policy No（首次承保號碼）
- 起因：批單的 Policy No 是原保單的 TW Ref，所以批單即使改了 Insured Name 也能用 Policy No 歸組；但續保會產生新的 TW Ref，匯出檔上看不出新舊保單是同一個案子（系統內有記 `renewedFromTwRef`，匯出沒有）。
- 做法（使用者選定）：匯出與畫面的**最後一欄**新增 `First Policy No`＝沿「批單→原保單、續保→來源」一路追到最初那張保單的 TW Ref。同一案子的各年度保單與批單這欄相同，不受 Insured Name 變更影響。Policy No、Endorse No 等既有 17 欄不變。
- 追溯規則（`production/calc.py` 的 `reference_links`／`first_policy_no`）：TW Ref 改過時（`previousTwRefs`）以現行號碼為準；來源不存在時顯示最後知道的號碼；有循環或自我指向時停止；連結表用「所有有 TW Ref 的案件」建（含已封存），中間那張被封存也不會斷。**只靠 TW Ref 連結，從不比對名字**，同名不同案不會被併在一起。
- 不放進 `source_signature`：連結不影響金額，避免讓已產生的報表全部變成「過期」。已關帳的月份保存的是當時的列，**不會補這一欄**（欄位是空白）；開著的月份重新 Generate 才會有。舊系統／Excel 轉入、沒有續保來源紀錄的案件，這欄就是它自己的 Policy No。
- 偏離 Alpha（**尚未同步回 Alpha，使用者決定先只改 VM**）：`production-xlsx.js` 多 4 處（標題、`cellValue` 多一格、第 18 欄寬度、autoFilter A1:R）；`run_calc_diff.sh` 改由 `scripts/check_production_xlsx.py` 核對「Alpha 原檔雜湊 + VM 版 = 原檔 + 這 4 處」。差異測試（`qa/calc/compare.py`）比對 Alpha 前先拿掉 `firstPolicyNo`，沒有這個欄位會算不一致。
- 驗證：新套件 `qa/suites/production_first_policy.py`（25 項，含批單／續保／從批單續保／兩層續保／來源不存在／中間封存／舊 TW Ref／循環）；故意弄壞 8 處（批單不追父、續保不追來源、忽略舊 Ref、不用現行 Ref、View 不傳完整連結表、欄位進簽章、少標題、拿掉循環保護）全數被抓到（拿掉循環保護會無窮迴圈卡死）。


### 2026-10-10：Case Loss Record 0 年規範
- New 案的 Past year(s) 可填 0，由業務員判斷；所有 Case 儲存時年數與 broker advised date 不可空白。
- 0 年時 Loss Record 明細必須為空；Endorsement 沿用 0 年，Renewal 建立時可帶入 0，但編輯儲存前必須改為大於 0。
- 0 年摘要在 Case、Word 與 PDF 顯示 Loss Clean since operation.；Alpha 參考檔保留原樣。


### 2026-10-13：Accounting 顯示原被保險人名稱
- Accounting 主分頁 SoA / Transactions 在 Transaction / SoA / TW Ref 後新增 Original Insured (EN / CN) 合併欄：英文在上、中文在下，缺值顯示 —。
- 所有交易列從所属案件 payload 取得英文／中文原被保險人；兼容舊 original_insured 欄位。
- 隔離 accounting_transactions API 回歸、18 組純函式比較、瀏覽器排列與唯讀／會計視圖驗證通過；交易金額、餘額、結清、權限及業務資料不變。


### 2026-10-13：3 小時人員閒置自動登出
- 使用者選擇 A/A：真實點擊、鍵盤／輸入、捲動重新計時；滿 3 小時閒置自動登出，提前 5 分鐘提醒，可點 Continue using 重新計時。提醒告知未儲存內容可能遺失，不會自動提交人員／案件或其他業務資料。
- 改為 10800 秒閒置與 300 秒提醒，SESSION_SAVE_EVERY_REQUEST=False。登入建立人員活動時間與非憑證公開識別碼；只有 CSRF 保護且識別碼符合的 activity POST 才延長絕對期限，背景 API、程式捲動、焦點切換不續期。後端 middleware 與 Django session 到期共同拒絕過期存取，過期 cookie 不能復活。
- SPA 與管理員 Data viewer 共用活動偵測程式；多分頁同步期限，登出前重新查核伺服器狀態，避免其他分頁已續期時誤登出。不同瀏覽器登入各自計時，改密碼換 Session cookie 時保留活動識別碼與期限。
- 舊 8 小時 Session 在下一個已登入請求採用新規則；重新整理頁面載入新版提醒與活動偵測。未新增資料表或 migration，未批次刪除現有 Session，未更改角色權限、帳號、密碼或既有業務資料。
- 新閒置邊界與 CSRF／到期重放檢查、登入／帳號／密碼重設／管理員／President 回歸與 Chromium 多分頁、持續輸入、捲動、提醒、自動登出驗證通過。僅獨立 QA 使用縮短時間，正式部署另驗證 10800/300 秒。產物見 Idle-Timeout-2026-10-13。


### 2026-10-13：Swiss Re Asia Facility Property 會計規則
- 僅適用 Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)／Property。原保單、續保、分期及加費批單採約定 90／會計 75 個日曆天；批單取生效日與正式 Announce 台北日較晚者。假日不順延；75 天提醒、超過 90 天逾期。
- Swiss 固定 02/14、05/14、08/14、11/14；保費依會計 75 天、最後填寫收款日期及實際手動確認日取最晚歸期。月底為確認截止，提前收齊不提前結算，未确认顯示原定及目前預計日期。我方漏付、銀行退回保留原期並標逾期。
- 全筆 insurer 應收（含其他再保部分）帳面結清後由會計確認；新增／修改／刪除或沖回收款紀錄須重確認。手續費／短收須先留原因登錄非現金結清。每笔 Swiss 应付一次全額沖銷，可合併匯款分配多筆。
- 退費 Swiss 原定收款提前一個結算期，仍受正式 Announce 月底列期限制；逾期保留原日、不滾動催收日期。所有再保退款確認收齊後才整筆退保險公司，可提前退款，原 75／90 日保留。批單不分期、不混合補退費。
- 原案及其對應退費批單同一 Swiss 結算期可抵減，保留雙邊原金額、實際淨收付與互相連結的非現金沖銷；不同原案及跨期不互抵。已送出清單跨期時由會計手動修訂確認。
- 尚未結算舊案於讀取套用規則；可驗證歷史結清時間承接並保留來源，無來源需會計重確認；已完成付款及銀行退回原紀錄保留。雙方清帳前對帳，依使用者最新決定不建立清帳後差額項目。
- Accounting 新增 Swiss Facility · Property 操作表。27 日期／邏輯測試、56 隔離 API 檢查、12 套 979 項既有回歸、5 項瀏覽器流程及前端建置通過。Finance QA 提醒讀取預期與 2026-10-07 已核准全案讀取權限一致，未修改權限。
- 無 migration、無正式業務資料批次改寫；上線前後所有 managed model（除 session）筆數／內容指紋相同；Audit 暫停及 Email 關閉保持。同期 System Reference 英文介面與文件名稱更新已保留。


### 2026-10-13：Dashboard New Business MTD 新增 Case 入口
- 在 New Business MTD 卡片右下角新增 + New Case 按鈕；依 cases.write 權限顯示。
- 點擊導向 /cases?action=new，消費查詢後沿用現有 startNewCase 表單及預設值。開啟表單不寫入案件資料，待使用者儲存。
- 前端建置、隔離瀏覽器的桌面／手機點擊、預設值、重載及權限檢查通過；僅更新前端。


### 2026-10-13：Swiss Accounting 無資料時固定顯示
- 移除 Swiss Facility · Property 區域的非空案件顯示限制。沒有符合案件仍顯示標題、75／90 天與固定 Swiss 日期說明、日期及收齊確認欄，空白表格說明 Swiss Facility Property 案件 Announce 後列入。
- 7 項隔離瀏覽器驗證通過：會計及唯讀空白狀態、既有收齊／清單修訂／整筆合併匯款／唯讀控制／Swiss 範圍鎖定。前端建置通過。僅重建 nginx，後端、資料庫、PDF 服務及所有 managed model 指紋保持。


### 2026-10-14：Swiss 整合至單一 Accounting 清單
- 使用者明確同意移除獨立 Swiss Facility · Property 專區，將日期與人工操作整合至既有 SoA / Transactions。
- Swiss 原定／目前結算日、月底截止、75／90 日期、延期、逾期、收齊狀態均在對應交易列顯示；多分期按各自排程顯示。移除重複表格，保留會計手動收付、收齊、結清、費用／短收、同案同期抵減、清單修訂與歷史；輔助操作由該列 More 開啟。
- 已 Announce 尚未 Production close 的 Swiss 項目在同一清單顯示，清楚標示 Awaiting Production close，沿用原 schedule payment／confirmation API；正式交易生成後以 cashParts 對應排程，避免重複列出及重複加總。原歷史反向交易及理賠不遮蔽現行保費排程。
- 12 項資料整合檢查、16 項 Chromium 流程與前端建置通過，涵蓋無資料、已上帳／未上帳、保費／退費、收齊／取消、手續費、清單修訂、抵減、整筆合併匯款、人工結清、其他 Facility 與唯讀。測試採合成資料，無正式業務寫入。
- 僅更新前端並重建 nginx；所有後端計算、75／90 天、Swiss 歸期及延期、月底截止及手動結清規則保留。後端／MySQL（及存在的 PDF）容器、業務資料指紋與設定保持。已備份來源與舊映像，可回復。


### 2026-10-14：全面除錯修正（依使用者逐項確認）
- 除錯不再與 Hatchable Alpha 比對：刪除 Alpha JS 差異測試（alpha_js、compare.py、harness.mjs、run_calc_diff.sh、check_production_xlsx.py），run_qa.sh 不再有 calc 步驟；前端合計一致性檢查保留。
- Swiss 同案同期抵減：Cedant 退費須所有再保人退款確認收齊後才可抵減（refund_collection_required），與現金退費相同。
- Performance Split 兩方合計 100% 時，b 方金額 = 該 Leg 總額 − a 方，Leg 1 交易合計與付款排程一致（原本可能差 1–3 分錢而停在 Partial）。
- Swiss 收齊證據維持 10/13 規則：可驗證的歷史交易結清時間可承接並保留來源（撤回當日另一 session 改為一律手動確認的修改）。
- 新案「Cedant 天數以案件為準」標記（cedantTermsBasis）由伺服器保留，存檔漏傳不會改回舊算法。
- Accounting 逐案計算：單一案件資料無法解讀時只略過該案並顯示警告，其餘照常顯示。
- 全 Facility 改成混合再保人時，只清空沒有有效 Location 的 Sum Insured；已指到存在 Location 的保留（舊資料原本記在 Location 1 時，原規則會一直清空導致無法 Announce）。前後端一致。
- 刪除 Location 不會讓 Sum Insured 變成零筆；System Reference 單一損壞中繼資料只略過並提示；nginx /static、/assets 補回 nosniff 與 X-Frame-Options；刪除未使用的 PDF 產生器腳本（pdf-generator.js、vm-pdf-generator.js、pdf-assets.js），退役 PDF 端點仍回 410。
- 測試：8 個過時測試組依 10/08–10/13 規則更新（純 AUW 主編號、Sum Insured 位置、Loss Record 必填、閒置 Session、Audit 空表）。獨立環境（ri_runtime＋db_harden、每組全新資料庫）49 組全部通過；密碼規則與前後端合計一致性通過。無 migration、無正式資料改寫。

### 2026-10-14：取消所有自動結清（一律由會計人工確認）
- 使用者決定：系統不應有自動結清功能，目前一律人工處理。所有案件（不再只限 Facility）的保費 T1／T2／T3、理賠交易（Claim Leg 1／2），以及付款排程的每一列，餘額歸零後顯示 Awaiting confirmation（`pending_confirmation`），須由會計在 Accounting 按 Confirm settlement 並填寫對帳參考或理由才變成 Settled。
- 經紀費 T3 仍須先人工確認對應的 T1 與 T2，再確認 T3；確認不產生任何匯款紀錄。任何收付款、沖回或費用調整改變餘額後，原確認失效，須重新確認。
- 收付款、沖回、費用／短收、抵減一律由會計手動登錄（原本即如此）；「自動」只曾指狀態，現已取消。
- Facility 結清 API 收到非文字的交易或排程編號回 400，不再造成伺服器錯誤。
- 測試：facility_manual、accounting_unified、accounting_transactions、production_api、endorsement_refunds 依新規則更新（含一般案件、理賠、經紀費的人工流程）。

### 2026-10-15：畫面測試更新與 AE Email 修正部署
- 正式環境 Bug（已修）：重新登入、F5 或直接連結開啟案件時，人員清單尚未載入，Cover Note／Debit Note 被誤報「缺少 Account Executive Email」；案件明細現在一併載入人員清單（c0e0e6a，已備份並部署）。
- Debit Note 檢查分期的 Premium／Ratio；System Reference 新增 AUW Facility 與 Swiss Re Asia Facility 規則說明檔。
- 畫面測試全部階段更新到現行規則（見上方）；階段 D 改寫成合併後的 Accounting：部分收款、收完仍為 Awaiting confirmation、人工確認、沖回整筆匯款。

### 2026-10-15：續保說明、移除自動結清的殘留
- 續保規則不變：案件有較新的批單，或批單鏈上有未完成（非 Announced／Confirmed）的批單時不能續保。新增：`GET /api/case-workflow` 的 `actions.renewalNotice` 說明原因，案件明細頁頂端顯示提示（有 `cases.write` 才看得到），不再只是讓「Create renewal」按鈕消失。
- 後端移除經紀費 T3 隨 T1／T2 自動結清的舊計算（`cash_ledger.py`）：T3 的結清一律由 `facility_accounting` 的人工確認決定。以 1,500 組隨機案件比對新舊程式，12,702 筆交易中非歷史交易 0 筆不同；只有已沖回（Reversed）的 T3 不再顯示 Settled。前端刪除「Auto settlement」按鈕字樣與「settles automatically」說明。
- 沖回整筆匯款成功後，Remittance details 與 Payment history 視窗維持開啟（使用者決定維持現狀）。
- 注意：`frontend/src/views/CaseWorkspace.vue` 已直接維護，產生器 `frontend/scripts/build_case_workspace.py` 與現況不同步（表單標籤大小寫等），**不要重新產生**，否則會蓋掉直接修改的內容。


### 2026-10-15：壓力測試與後端／MySQL 設定調整
- 壓力測試（1 萬件案件、SoA 1.8 萬列、7 人使用；工具 qa/stress/，結果 qa/stress/RESULTS-20261015.md，在獨立環境執行，正式系統未動）：單人 Accounting 約 23 秒（回應 47 MB）、Dashboard 8 秒、Production Report 8.5 秒。原本只有 2 個 gunicorn worker，有人開 Accounting 時其他人全部排隊，7 人同一秒開 Accounting 有 3/7 逾時（504）。
- 使用者選擇調整設定：gunicorn worker 2→4（= CPU 核心數，backend/Dockerfile）、MySQL innodb_buffer_pool_size 128MB→512MB（compose.yaml）。重測：7 人平常使用時開案件 P90 29 秒→0.09 秒、Accounting 最慢 52→27 秒、6 分鐘無錯誤；後端記憶體尖峰約 2.4 GB。
- 不使用 thread（--threads）：多個 Accounting 同時在記憶體，測試中撐爆記憶體被終止。nginx 轉發逾時維持 60 秒（7 人同一秒開 Accounting 仍可能有 1/7 逾時）。
- 單次 Accounting 約 24 秒不變（程式計算量：每件案件重算交易明細、回應 47 MB；Dashboard、Production Report 每次讀全部案件），設定改不了；是否優化程式另行決定。
- 無 migration、不改業務規則與資料；部署前已備份，保留回復用映像 before-workers4-20261015_180259，部署前後各表筆數相同。


### 2026-10-15：Accounting 表格分頁
- 問題：1 萬件案件、SoA 1.8 萬列時，Accounting 表格一次畫出全部列。在真實瀏覽器（無頭 Chromium，3 GB 記憶體）測試，資料下載完成約 25 秒後，280 秒內都畫不出第一列，分頁最後崩潰。
- 使用者選擇先做前端分頁：表格每頁預設 100 列（可選 50／100／200／500）；篩選仍在全部資料上進行，標題的 (N) 是篩選後的總數；篩選或改每頁筆數會回到第 1 頁；勾選的列跨頁保留；符合的列在 50 列以下時不顯示分頁列。後端 API、資料、權限與規則都沒變。
- 結果（同一份資料）：第一列約 28 秒出現（伺服器與下載約 25 秒），畫面 5,450 個 DOM 節點、JS 記憶體 179 MB，篩選後 1.5 秒更新。伺服器端 Accounting 約 24 秒不變，是否再優化另行決定。
- 驗證：真實瀏覽器 13 項分頁功能檢查（換頁、改每頁筆數、篩選、跨頁勾選、清除篩選）與整套畫面測試 13 階段 185 項通過；部署前已備份，回復用映像 before-paging-20261015_184454；部署的前端與測試版本的組建檔案雜湊相同；後端未動。


### 2026-10-15：Accounting 加速（共用計算、壓縮）
- 問題：1 萬件案件、SoA 1.8 萬列時單次 Accounting 約 23 秒；同一件案件的付款排程平均被算 2.3 次，有收款的案件交易明細被算兩次，另有不必要的整份複製。
- 使用者選擇「去掉重複計算 + nginx 壓縮」。後端：Accounting 列表每件案件的付款排程與交易明細只算一次，付款排程列、SoA 交易列與 Swiss 排程共用（cases/shared_compute.py 的 CaseCompute；兩種呼叫的輸入內容不完全相同時維持各算各的）；只讀的列表不再整份複製 payload；JSON 鍵順序與排序鍵加快（結果不變）。nginx 對 JSON、JS、CSS 啟用 gzip（46 MB 的 Accounting 回應約 4 MB）。不改任何計算規則、權限與資料。
- 結果（同一份 1 萬件資料）：單次 Accounting 23 秒→13 秒；7 人同一秒開 Accounting 由每輪 3/7 逾時變成全部成功（最慢 33 秒）；7 人平常使用時 Accounting 中位 13 秒、最慢 18 秒。
- 驗證：新舊程式對 1 萬件資料的 Accounting 回應及 589 件案件明細逐位元組完全相同；新增 accounting_shared_compute 測試（共用結果須與重算相同，故意弄壞會失敗）；全部 52 組資料庫／API 測試與 13 階段畫面測試通過；部署前已備份，回復用映像 before-accel-20261015_203721；部署後各表筆數相同。
- 仍未改：Dashboard、Production Report 每次讀全部案件（約 7 秒）；每件案件的結果快取尚未實作。


### 2026-10-15：Dashboard 與 Production Report 結果快取
- 問題：1 萬件案件時 Dashboard 約 7 秒、Production Report 約 6 秒，每次都把全部案件讀出來重算。
- 使用者選擇做結果快取（只有 GET 讀取；Production 的 Generate、Close、Exclude 一律不使用快取，仍在鎖之內讀最新資料）。做法見 `ri_system/result_cache.py`：每次請求先取得「資料變更指紋」（案件筆數、版本號總和、最新更新時間；匯率、目標、當月排除紀錄；Production 另含所有有 TW Ref 的案件），再讀資料；指紋相同且未超過保險上限才回傳上次結果。Dashboard 的鍵還包含台北日期、是否過了 12:00、使用者範圍（看全部／個人）；看全部的人，草稿存檔不使 Dashboard 快取失效（草稿只用於「進行中報價」件數，草稿的新增、回收、公布仍立即反映）。
- 保險上限：使用者決定 5 分鐘（compose.yaml 的 RI_RESULT_CACHE_TTL=300；程式預設 60 秒）。只補「直接改資料庫、繞過系統」這種不更新版本號的情況；系統內所有案件寫入都會更新版本號與更新時間。RI_RESULT_CACHE=false 可完全關閉。快取在各 worker 的記憶體，每個 worker 最多 32 筆，重啟或部署後清空。
- 結果（1 萬件資料）：命中時 Dashboard 約 0.02~0.2 秒、Production Report 約 0.08~0.3 秒；沒命中仍約 6~8 秒。寫入頻繁、或查看間隔很長時命中率低。7 人同一秒查看時，第一輪約 7 秒，之後幾輪約 0.1~0.2 秒。
- 驗證：新舊程式輸出逐位元組相同（Dashboard、三個月份的 Production Report、Accounting、589 件案件明細，含快取命中的第二次回應）；新增 result_cache 測試 35 項（各種變更後快取等於重新計算；故意弄壞 4 種都會失敗）；全部 53 組資料庫／API 測試與 13 階段畫面測試通過；其他測試組在隔離環境預設關閉快取（RI_RESULT_CACHE=false）。部署前已備份，回復用映像 before-cache-20261015_221400；部署後各表筆數相同。


### 2026-10-16：Accounting 畫面只取需要的資料、回到頁面先顯示上次清單
- Accounting API 新增 ?view=list（畫面使用）：付款排程列（rows）只有 Swiss Facility 案件會在畫面上顯示，其他案件不再產生這些列；warnings、currencies 與其他欄位照常。不帶參數時輸出與以前逐位元組相同（其他用途與既有測試不受影響）。1 萬件資料：約 14.5 秒→約 11.6 秒，回應約 46 MB→30 MB（原估 9~10 秒，實測只省約 20%）。
- 同一次登入中回到 Accounting 時，先顯示上次載入的清單並在背景重新載入（約 1.6 秒看到清單）；上方顯示「Showing the list loaded at HH:MM. Updating…」，更新完成前隱藏記收款與確認結清等操作。清單只存在該瀏覽器分頁的記憶體，登出或換人登入即清除。
- 驗證：1 萬件資料完整模式新舊逐位元組相同、精簡模式除付款排程列外完全相同；Swiss 與一般案件各加對照測試；真實瀏覽器回到頁面 8 項、分頁 13 項檢查；部署版本（含另一個 session 當天已部署的內容）上重跑相關 11 組測試與 13 階段畫面測試皆通過。部署前已備份，回復用映像 before-lean-20261016_120011；部署後各表筆數相同。


### 2026-10-15：經使用者確認退役第一批舊碼
- 已確認移除：舊 Word 產生器 docx-generator.js、Alpha 畫面產生器與 frontend/alpha-reference 副本、rebuild_alpha_file.py、未使用的 ASGI 入口，以及兩份沒有測試案例的 tests.py。刪除前封存完整原檔及變更前版本，保留回滾映像。
- CaseWorkspace.vue 與 case-workspace.script.js 直接維護；已移除要求重新產生 Alpha 模板的舊註解。Word 載入器仍使用 docx-templates.js 與 vm-docx-generator.js。
- 不變更業務規則、資料庫結構與資料；保留搬遷管理命令及測試、conversion models/migrations、WSGI 入口、frontend/src/alpha 與 System Reference 資料。


### 2026-10-15：啟用 Premium Installments 至少兩期（Case 儲存即檢查）

- 業主選 A：只有一期屬於一般付款，不應啟用分期。所有 Case 新增／編輯儲存時，`installmentEnabled === true` 必須至少兩期；零期／一期均拒絕，提示補到兩期，單次付款則關閉 Premium Installments。只檢查期數，不新增草稿其他分期欄位的必填限制。
- 前端儲存先提示並展開 Cedant Premium；分期狀態、Review／Announce 與後端草稿正規化／Announce 必填檢查使用相同最少兩期規則。API 不可繞過；不自動關閉、不改寫已存資料。分期關閉可維持一般付款；Endorsement 既有禁止分期規則保留。
- 此項為 Case 儲存規則，Treaty 同樣適用；先前 Treaty 文件生成必填豁免不變。Word 付款日期、金額、期別順序、尾差與模板均未修改。
- 驗證：隔離資料庫 API 新增／編輯零期、一期拒絕且無寫入，兩期以上與關閉分期接受；Review／Announce、既有案件回歸、畫面儲存／補第二期／關閉分期與建置檢查通過。


### 2026-10-15：Announced／Confirmed 案件事後更新對帳號碼
- 使用者選擇：Case 的 SoA / Transactions 與 Accounting 合併列表都提供 Edit references，僅 cases.write 可操作；accounting.write 本身不授權修改。
- Statement No. 與各再保人 Reinsurer Ref. 可在 Announced／Confirmed 後直接更新、清空或重複填寫；部分收付款及人工結清後仍可改。現有 160 字元上限、案件可見範圍及 rowVersion 競爭保護沿用。
- 專用 API /api/case-reconciliation-references 只更新 payload 的 statementNo／reinsurers[index].settlementRef，提升 rowVersion 並建立 Snapshot；Audit 暫停設定維持。原始交易、保費、付款、結清確認及 Production 紀錄不重新計算或重建。
- Accounting 保費、理賠與尚未關帳的 Swiss 排程均讀取最新號碼；Case 的 Confirmed 一般欄位仍鎖定。
- 隔離 API 61 項、既有 Accounting／Case／權限回歸及桌面／手機瀏覽器雙向同步、Finance 唯讀與競爭更新檢查通過；無 migration，正式 managed model（除 Session）部署前後筆數與雜湊一致。


### 2026-10-15：QS／XOL Debit Note 收款帳戶僅開放 USD、TWD

- 業主選 A：USD 使用既有美元銀行模板，TWD 使用既有臺幣銀行模板；其他幣別的 QS／XOL Debit Note 先阻擋生成，待另行確認對應收款帳戶。不得將其他外幣自動當作臺幣收款帳戶。
- 依已儲存 Case 的 currency，trim 並轉大寫後只接受 USD／TWD；空白、缺漏及其他代碼也阻擋。前端 Debit Note 卡片提示且下載前攔截，後端 Word 生成紀錄 API 同步回 409／debit_bank_currency_unsupported，不接受請求中的幣別覆寫。
- 既有必填檢查優先順序維持；Treaty 維持全部文件必填豁免。僅限制文件種類 debit，Cover Note、Endorsement Word、Case 儲存／Review／Announce 與會計不新增幣別限制。批單 Debit Note 的內容留待後續確認。
- Word 模板、產生器、USD／TWD 帳戶資料、Original Premium Payment 文字、付款期限與「顯示期限前再提前 15 天收妥款項」英文均維持。
- 驗證：隔離資料庫 API 測試、既有文件生成回歸、畫面攔截與實際 Word 下載檢查通過；其他幣別不得繞過儲存幣別檢查，Treaty 與其他文件保持可用，USD／TWD 銀行模板對應正確。


### 2026-10-15：經使用者確認退役第二批 Alpha 搬遷工具
- 第一批清理後另獲使用者同意，整組退役 import_alpha_reference、import_alpha_cutover、export_alpha_shape，及 conversion 的 importer／alpha_format／integrity／remap、qa/conversion 演練與 conversion_clause_remap 舊測試。刪除前完整封存原檔並保留回滾映像。
- conversion 的 App 註冊、models、migrations 及既有資料表保留；沒有資料庫 migration 或資料清除。正式 Web 路由與帳號維運指令不變。前段第一批紀錄中的「保留搬遷管理命令及測試」由本段取代。
- PendingView、舊版 AUW 說明檔、目前 System Guides、Document Templates、案件附件均保留。


### 2026-10-15：經使用者確認清理第三批備援畫面與舊說明檔
- 所有 10 個現行選單均有對應正式元件，移除 PendingView.vue 與 router 的 import／fallback；路由、權限與現行頁面保持。
- 封存後移除 AUW_Facility_Accounting_Rules_2026-10-13.docx；MANUALS 已使用 AUW_Facility_Rules_2026-10-14.docx，現行四份 System Guides 與共享 volume 的 Document Templates 均保留。第二批記錄中的這兩項保留狀態由本段取代。
- 原檔與變更前版本先封存並保留回滾映像；無 migration 或正式資料改寫。


### 2026-10-15：Great American Facility 專屬規則確認問卷

- 依業主確認，於 System Reference Data → System Guides 新增獨立 Word 問卷，標示「規則確認問卷／待決議」；200題、20主題、56頁，含可勾選選項、逐題共同決議／備註及待決追蹤。
- 已確認前提為 Great American Insurance Company, Singapore Branch (Facility) 專屬、參照Swiss季結算、暫由人工對帳／沖帳／銷帳；具體季日、範圍及系統功能仍由同事共同討論決議。
- Swiss對照來自查核當日正式程式及既有Swiss PD指南。僅新增下載登錄與文件，未實作Great American季結算規則或改寫業務資料；既有指南及權限沿用。
- 驗證Word200題與欄位、56頁排版、隔離下載／角色限制、正式清單／檔案雜湊、其他指南及業務來源完整性。


### 2026-10-15：Cover Note／Debit Note 每頁靠右顯示頁碼

- 業主選 A：兩份 Word 每頁均於頁尾靠右顯示 Page X of Y，單頁同樣顯示 Page 1 of 1。Cover Note 保留既有 PAGE／NUMPAGES 欄位；Debit Note 新增相同功能，置於既有公司地址下方。
- 使用 Word 自動欄位及開啟文件時更新欄位設定，依實際頁數顯示，不寫死總頁數。紙張、邊界、Logo 尺寸、內文字型字級、銀行及業務內容不變。原始模板與 Endorsement Word 產生流程不修改。
- 驗證：11 份單頁／多頁合成 Word 套件比對、動態頁碼欄位與每頁預覽、隔離瀏覽器實際下載、前端建置與 Loss Record readiness 檢查通過；不改正式案件資料。


### 2026-10-16：Debit Note 銀行資料表整組保持同頁

- 業主選 A：銀行資料表空間不足時整組移至下一頁，不拆開表頭與帳戶資料。USD／TWD 銀行表頭與帳戶列禁止列內拆頁，表頭段落與下一列保持同頁；帳戶列不連帶綁定後續署名段落。
- 僅調整 Debit Note 銀行區塊的 Word 分頁屬性；公司／帳戶資訊、付款日期金額、其他表格、字型字級、Logo、頁尾與頁碼均保留。Cover Note、Endorsement Word 與原始模板不修改。
- 驗證：13 份單頁／多頁及 USD／TWD 合成文件套件比對、Word 分頁屬性、原先表頭／資料分頁案例的實際預覽、隔離瀏覽器下載與建置檢查通過。正式案件資料不改寫。


### 2026-10-16：Debit Note 完整銀行帳號單行顯示、帳號字體 8 pt

- 業主選 A 並指定帳號改為 8 pt：USD／TWD 的帳號數字採 Arial 8 pt、不換行。Account No. 表頭及其他銀行資料維持 10 pt；本項取代銀行帳號原先 10 pt 設定。
- 銀行表頭與帳戶列同步將帳號欄加寬 6 pt，由相鄰英文收款人欄調整；整表總寬及其他內容列的分界不變。僅移動銀行區塊使用的共用格線分界，並同步更新兩列儲存格寬度。銀行資料表保持同頁的既有規則沿用。
- 帳號文字、收款人、Swift Code、付款金額日期、字型、Logo、頁尾與頁碼均保留；Cover Note、Endorsement Word 及原始模板不修改。
- 驗證：13 份 USD／TWD 與單頁／多頁文件套件、XML／欄位幾何比對，完整帳號單行與 8 pt 預覽，銀行同頁及頁碼回歸，隔離瀏覽器實際 Word 下載與建置檢查通過。正式業務資料不改寫。


### 2026-10-16：Cover Note 移除章節換頁造成的多餘空白頁

- 業主選 A：調整多餘空白與換頁，避免只有 Logo／頁尾的空白頁；Schedule of Security 與附加條款仍各另起新頁。
- 原本位於頂層章節表格之間的獨立分頁符號及連續空白段落，改為單一緊湊分隔段落，設定段落前換頁與緊接下一段。避免空白段落自然溢到下一頁後又觸發一次分頁。只處理不含文字、圖片、欄位或書籤等內容的章節間空白。
- 不刪減表格列、保額／地點／理賠資訊、條款、Security 或簽名；內文可依實際長度延伸。維持 A4、頁面邊界、Arial／標楷體、字級、Logo、每頁頁尾及 Page X of Y。原始模板、Debit Note 與 Endorsement Word 不修改。
- 驗證：QS／XOL、長內容、多地點、選填留白與多再保人等合成 Word 套件／XML／預覽／瀏覽器下載；XOL 基準範例空白第 3 頁消除，5 頁變 4 頁，Security 與附加條款仍新頁開始。建置與 readiness 檢查通過；正式業務資料不改寫。


### 2026-10-16：Cover Note／Debit Note 簽名區塊整組保持同頁

- 業主選 A：簽名圖與公司署名整組保持同頁；Debit Note 再包含 E&OE。空間不足時整組移至下一頁。
- 在兩份文件的簽名表格列至公司署名／E&OE 之間，逐列禁止拆頁，段落保持同頁並與後續列銜接，包含中間原有空白列；最後一列結束銜接，不綁定後續章節。保留原有圖片、文字、列高與間距。
- 既有銀行資料表同頁、完整帳號 8 pt 單行、Cover 章節換頁、每頁 Logo／頁尾／頁碼與所有業務內容均保留。原始模板及 Endorsement Word 不修改。
- 驗證：QS／XOL、USD／TWD、長內容、多地點、多再保人及接近頁尾的分期範例；套件／XML 僅分頁屬性改動，實際預覽簽名圖與署名／E&OE 位於同頁，瀏覽器下載、建置與 readiness 檢查通過。正式業務資料不改寫。


### 2026-10-16：Cover Note／Debit Note 簽名圖前統一一行空白

- 業主選 A：縮減簽名圖前的多餘空白，兩份文件均保留一行。僅處理簽名圖前連續的純空白表格列：Cover 原 6 列、Debit 原 4 列，改為單列 12 pt 的空白行；段落前後間距為 0、行距固定 12 pt、字級 10 pt。
- 空白行不拆頁並跟隨簽名區塊，簽名圖、公司署名及 Debit Note 的 E&OE 仍整組同頁。圖片、署名與 E&OE 之間既有間距不變；含文字、圖片、欄位、合併、書籤或註解等內容的列不作為空白列刪除。
- 其他內容、銀行資料表同頁、帳號 Arial 8 pt 單行、Cover 章節分頁、Logo、每頁頁尾與頁碼保留。原始模板與 Endorsement Word 不修改。本項取代前段「保留簽名前間距」的設定。
- 驗證：20 份 QS／XOL、USD／TWD、長內容、多地點、多再保人與分期邊界範例，套件／XML 僅純空白列改動，預覽確認單行空白及簽名同頁、銀行／章節／頁碼正常；隔離瀏覽器下載、建置與 readiness 檢查通過。正式資料不改寫。


### 2026-10-16：Cover Note 保額明細標題拼字修正

- 業主選 A：保額明細標題統一為 BREAKDOWN OF SUM INSURED，修正 QS／XOL 模板中的 BREAKFOWN 拼字。
- Word 包裝產生器在填入 Case 內容前只修正固定標題；不改寫已儲存 Case，Case 自填內容即使含同樣文字也維持原文。保額明細、地點、金額、字型字級及既有分頁設定保留。原始模板、Debit Note 與 Endorsement Word 不修改。
- 驗證：QS／XOL、多地點、Facility、長內容與 literal Case 文字等 21 份 Word 套件比對，僅固定標題一字母不同；兩份模板預覽的標題正確且頁數保持。隔離瀏覽器實際下載、前端建置及 readiness 檢查通過。正式業務資料不改寫。


### 2026-10-16：一般再保人 CGL Case Information
- 依業主逐題決定，一般版 Commercial General Liability（QS／XOL；Facility、PWS、Swiss Re Asia 專屬組合維持原流程）以 Information 取代 Occupation & Construction、Breakdown of Sum Insured、Loss Record、Special Agreement；後兩項移入 Information 並保留小標題。其他 Risk Details／Terms 尚待後續整理。
- Policy Form 必選且預設空白：Occurrence Form／Claims-Made Form。Claims-Made 顯示並必填 Retroactive Date；Extended Reporting Period 僅 Claims-Made 顯示，必選適用／不適用，適用時必填期間及說明。
- Territorial / Jurisdiction Limits 必選且預設空白：範本三項或 Other；Other 必填說明。Insured’s Business／Products 均為必填多行文字。Website 選填文字，不檢查網址格式。
- Estimated Turnover 可新增／刪除多筆，至少一筆，每筆區域、幣別、非負金額必填；幣別預填當時 Case 幣別，可逐筆另選。既有列的幣別不因後續 Case 幣別變更而覆寫；零金額可填。
- Special Agreement 適用／不適用必選且預設空白，適用時必填多行內容。Policy Form／適用狀態切換會先提醒，取消保留選擇與內容，確認後清空相關內容；後端亦清除不適用的從屬資料，避免文件洩出舊文字。
- 新增必填規則不阻擋未完成草稿儲存；Review／Announce 與 Cover Note 生成均檢查。Loss Record 欄位與原有儲存、年數、逐筆規則完整沿用。一般 CGL 不再要求已移除的 Occupation、Construction、Sum Insured；Property 規則維持。
- 新資料保存在既有 Case payload.cglInformation，沿用 Snapshot／rowVersion，無 migration、無既有案件批次改寫。案件檢視、Review 與現有 Cover Note 的 Information 段讀取相同資料；其餘 CGL 文件格式留待後續整理。
- 驗證：10 組隔離 API 回歸共 3,467 項、CGL 前後端 229 組、金額 3,000 組與密碼 20 組一致性、桌面／手機實際操作與 Word 內容檢查通過。部署前後正式 managed tables（除 Session）筆數及雜湊一致，Audit 暫停及寄信關閉維持；保留同步 Word 更新及其他正在編輯的原始碼。


## 2026-10-16：92 項會計規則重新確認

本節與 `backend/qa/accounting-review-92.json` 優先於前述舊會計規則；未涉及的規則及權限繼續沿用。這是供財務登錄與對帳的系統，不執行銀行收付款。

- 保費在 Production 關帳後建立帳款；零收入仍不列業績，但在關帳建立帳款並轉 Confirmed。批單業績月份改取生效與 Announce 較晚月；分期尾差集中第一期。
- 收付登錄、抵銷及銷帳全由財務逐筆操作。餘額歸零只顯示已收／已付，須再手動銷帳且填參考號／說明。保費每次須登錄整筆餘額；只有賠款可部分收付。
- 未銷帳收付金額可填原因直接更正並保留前後歷史。曾銷帳金額永久鎖定；取消銷帳不解鎖金額。T3 須對應 T1／T2 人工銷帳後才可銷帳，T3 完成後整組都不能取消。
- 每期 Cedant 及每期每家普通再保人的約定天數須獨立填寫，沒有預設繼承；缺漏列待確認，不得收付或銷帳。案件維護人員可補填缺漏天數並留原因／歷史；已有效天數不可藉此修改。固定 AUW／Swiss 天數依特殊規則。逾期以實際約定到期日判斷。
- Swiss 收妥與 Cedant 逐筆銷帳合一；整期全部完成才放行付款，且付款前必填結算清單參考號。保留固定結算期、退費收齊先後限制；移除另設收妥勾選及銀行手續費／短款作業。人工抵銷擴大至 AUW／普通案件，限同原單直接退批、同幣別、同對象、退批整筆抵完；Swiss 另須同期且不得繞過原有限制。
- 賠款建立即建帳，按出險日適用比例分攤，建立帳款台灣日期加15日到期且不可修改；付出不得超過該筆已登錄收到的金額。未經收付或抵銷可填原因更正義務金額並留歷史。保費 Reverse 不影響賠款，但保費有收付或抵銷歷史禁止 Reverse。
- Dashboard 以 Accounting 已建所有應收應付餘額及上帳月匯率為準，含已到期保單。缺匯率不擋原幣作業，顯示待補及合計未完整；已關帳業績採正式報表，未關帳標示預估。
- 財務提醒改用正式帳款實際到期日前7日、到期日及之後每7日，餘額零停止；寄 AE、AE主管、啟用中 Finance Staff。有效地址先寄，缺漏另提示。財務信件獨立以 `RI_PAYMENT_REMINDER_ENABLED` 控制；必須配置 `RI_EMAIL_HOST` 等 SMTP 設定才實際寄送，不變更 Signed Slip／忘記密碼總開關。
- 舊帳修復：`python manage.py apply_accounting_review` 預覽，確認簽章後 `--apply --expected-signature <signature>`。只更正未處理金額，保留版本、快照及業務修改歷史，不改正式關帳報表；曾處理的分期分攤保留待人工核對，避免跨期尾差漂移。賠款建立日只用實際快照證據，無證據不猜日期；零收入補建遞延第一個未關帳月。

驗證：`backend/qa/suites/accounting_review_92.py`、`accounting_review_edges.py`、`accounting_shared_compute.py`、`audit_pause.py`；僅在 `RI_DISPOSABLE_QA=true` 的隔離資料庫執行。舊 Alpha 對照及 Swiss／Facility 測試中關於部分保費、獨立收妥勾選、費用及自動鎖定解除的舊斷言，已由上述新規則取代。


### 2026-10-16：Property Key In Information 合併
- 使用者選定四項合為同一張 Information 卡片，保留 Occupation & Construction、Breakdown of Sum Insured、Loss Record、Special Agreement 四個小標題及原有欄位。適用 Property，包括 Facility；其餘 Class 沿用原版面。
- 必填 Review 與 Loss Record 存檔檢查的定位改為展開 Information。資料仍使用既有 payload 欄位。
- 前端建置與 17 項既有 readiness 檢查、桌面／手機瀏覽器、收合後驗證定位、新增刪除項目、模擬存檔重開與其他 Class 版面檢查通過。僅部署前端。


### 2026-10-16：Word 檢視範例第二輪修正

- 依業主指示，Cover Note 貨幣代碼與數字金額之間不留空格，包括 Case 原文帶入的 USD／TWD 等常用幣別及案件幣別；只格式化 Word 顯示，不改寫 Case 原文、數值或幣別。
- Original Conditions／Original Exclusions：AE 留白時，僅保留固定 All other terms and conditions are subject to original policy wordings.，不加 1.／2.／3.；有填時維持原有逐行編號及固定尾句。
- Breakdown of Sum Insured 的每個 Location 標題合併明細表兩欄並置中，保留粗體、全表寬及項目／金額。Facility 既有平面明細不新增 Location；CGL Information 保留最新獨立格式。
- Debit Note 銀行收款說明、銀行名稱／地址與整張帳戶表格均改 9 pt，包括 Account No. 表頭及帳號；以業主「銀行資訊都用 9 pt」為範圍，取代原先 8 pt 帳號及 10 pt 其他銀行文字。帳號單行、銀行表格同頁等規則沿用。
- 原始模板、Endorsement Word、付款金額、Logo／頁碼、簽名同頁與簽名前單行空白不變。保留同步 CGL／Property Information 及會計規則更新。驗證實際 Word／XML、單頁多頁預覽、隔離瀏覽器下載、前端建置與最新 readiness 檢查；另更新 System Reference 的檢視範例版本。
- 修復非分期 Debit Note 的 Case 付款天數未傳入日期計算的遺漏：保單起日加 Case 天數減 15 天；分期繼續各期獨立付款天數，不加入繼承。


### 2026-10-16：Case Reinsurance Structure 優先選擇
- Account List 的 Case 新增／編輯表單將 Reinsurance Structure 從 Risk Details 移至最上方獨立區塊，沿用 Quota Share／Excess of Loss／Treaty 選項與既有 Type 後綴邏輯。
- 新案預設空白；選定後才顯示其他表單內容、頁首／頁尾儲存與 Review 按鈕。清除選項會隱藏下方內容並保留記憶體內已填資料，重新選擇可繼續填寫。Cancel 後另開新案仍依原規則重設。
- 編輯既有案件沿用已存選擇直接顯示內容；歷史 FACULTATIVE 仍映射 QS。批單的 Structure 選項遵守 Risk fields locked／unlocked 開關。資料格式與後端業務規則不變。
- 驗證：候選前端建置與 17 項既有 readiness、桌面／手機三選項顯隱與資料保留、既有案件及批單鎖定通過。隔離 cases_api 與 case_workflow、密碼及 3000 案件合計一致性通過；case_workflow 的舊 fixture 缺少各再保人付款天數，只在暫存測試副本補 30 天，正式測試與程式不改。僅部署前端。


### 2026-10-16：一般 CGL Situation 更名為 Principal Address，逐欄範本對照
- 業主指定一般再保人 CGL 的 Situation 改為 Principal Address。同步 key-in 標題／輸入提示／新增刪除、案件檢視、Review、草稿與 Announce 錯誤訊息、文件提示及 Cover Note 固定標題。Property 與 Facility／PWS／Swiss 專屬範圍沿用原名稱。
- 沿用既有 situations/address/postcode 資料；不改地址筆數、郵遞區號必填或檢查時點，不批次改寫舊案件，無 migration。Word 僅改固定 SITUATION 標題，Case 原文含相同文字仍完整保留。
- 依 System Reference Data 一般版 CGL 範本逐項核對 47 項，包含 30 項 Risk Details、10 項 Information 及 Security／附件／額外欄位。Coverages、Self-Insured Retention、Interest 預設、限額名稱／格式、Type、Notices、CGL 固定條款及殘留 Property 欄位列待確認；此次僅執行業主明確指定的 Principal Address 更名，其他以選擇題另行確認。
- 驗證 100 項無資料庫後端名稱／資料／存取一致性、既有 17 項 readiness、19 項隔離瀏覽器、四份實際 Word 及 8 項固定標題／原文保留檢查通過；保留同步 Reinsurance Structure 先選流程。正式 managed tables（除 Session）部署前後筆數／雜湊及功能設定一致。


### 2026-10-16：Case 選定 Class 後顯示後續區塊
- 延續 Reinsurance Structure 優先選擇：選定 Structure 後只顯示 Risk Details，選定其中的 Class 後，才顯示 Schedule of Security、Terms & Conditions、Information／各 Class 原有資訊區塊、保費、Performance Split 及 Reinsurance Conditions；AUW TW Ref 與頁首頁尾儲存／Review 按鈕亦等 Class 選定後顯示。批單說明與風險欄位鎖定開關保留，以便操作既有案件。
- 清除 Class 僅隱藏相關區塊，保留已填欄位；重新選定後沿用既有 Class 切換與條款規則。既有案件有 Class（含歷史主檔名稱）直接顯示後續內容，空白 Class 僅顯示 Risk Details。原有 Structure 顯示條件仍適用。
- 僅調整 CaseWorkspace.vue 的顯示條件；案件資料格式、後端與儲存驗證不變。前端建置與既有 17 項 readiness、桌面／手機三種 Structure × 三種 Class 選擇及清除、資料保留、既有／歷史案件、批單鎖定與 Review 檢查通過；隔離案件 API 及密碼／3000 案件合計一致性通過。


### 2026-10-16：Cover／Debit 頁首 Logo 排版相容性
- 依業主選擇 A，保留現有 TWIG Logo 圖檔、4.73 × 2.71 cm 尺寸、置中位置與 A4／全部頁面邊界。
- Cover Note／Debit Note 頁首 Logo 所在段落明確設定最小行高為圖檔高度（975360 EMU → 1536 twips），段前後為 0、段落不拆分，讓頁首高度不依賴繼承的段落行距。沿用行內圖片與現有頁首距離，不改為浮動圖。
- 主文件 XML、頁尾、金額、付款期限及原始模板均不變；Endorsement 不變。以 27 份 Word 原生結構與每頁實際圖片座標檢查裁切、置中及與內文間距，另執行隔離瀏覽器下載與 API 回歸。
- 補充更正：原版與調整版的離線圖片座標檢查均顯示 Logo 位於紙張內；先前目視裁切判斷不準確。本次屬明確保留行高的相容性調整，不宣稱已證實原版 Word 存在裁切。


### 2026-10-16：Reinsurance Structure 與 Class 同區塊先選
- 依業主最新決定，Class 從 Risk Details 移至最上方 Reinsurance Structure 卡片，兩個選項同時顯示、可依任意順序選擇；桌面並排、手機上下排列。此條取代前述「選完 Structure 先顯示 Risk Details，再選 Class」流程。
- Structure 與 Class 兩項皆有值才顯示 Risk Details、AUW TW Ref、批單明細、其他後續區塊及儲存／Review。清除任一項即隱藏下方內容，已填 payload 保留；重新選定仍沿用既有 Type、Class 條款與資訊版面規則。既有案件沿用儲存值，歷史主檔名稱與舊 FACULTATIVE 轉 QS 規則不變。
- 批單 Risk fields locked／unlocked 開關移至上方卡片，讓兩個選項遵守同一鎖定狀態，且即使選項清空也能重新解鎖，不會因下方隱藏而無法操作。
- 只修改 CaseWorkspace.vue 版面與顯示條件，資料格式與後端不改；保留 CGL Principal Address 與最新 Word 更新。候選建置與既有 readiness、桌面／手機三種 Structure、兩種選擇順序、清除／重選資料保留、Property／CGL／Marine、歷史與未完成案件、批單鎖定及 Review 瀏覽器檢查通過；隔離案件 API、密碼與 3000 案件合計一致性通過。


### 2026-10-16：Reinsurance MDM 的 Lloyd's Market 分區
- Reinsurers 新增與 Case 同式的展開／收合區塊 Lloyd's Market，預設收合，標題顯示分類內全部主檔筆數。名稱以 Lloyd's Underwriter Syndicate No. 開頭的再保人（不分大小寫，支援直／彎撇號）自動列入，包含 Active／Inactive；其他再保人保留原清單，分類成員不重複顯示。
- 展開顯示原有 Name、Abbreviation、Status、Ratings、Fixed clauses 與按權限開放的 Edit／Deactivate／Reactivate。Refresh、新增或修改後自動重新分組，不另存成員名單。
- 此次只調整 MDM 顯示，沒有新增分類資料欄位或改寫主檔；Case 選單、Facility／AUW／Swiss 的既有業務判斷與其他 MDM 分頁保留。
- 驗證：前端建置及 17 項既有 readiness 檢查、桌面／手機展開收合與無重複、完整欄位、Inactive 成員、原紀錄編輯、重新啟用、其他分頁、新成員 Refresh、唯讀權限、空分類等 15 項隔離瀏覽器檢查通過；master_payload_compat 隔離 API、密碼與 3000 件前後端合計一致性通過。


### 2026-10-19：Cover／Debit 三行頁尾（10/16 業主決定）
- 依業主選擇 A，Cover Note／Debit Note 每頁固定公司資訊分三行置中：公司名稱、完整地址、電話與傳真。保留既有文字、10 pt 灰色字體及 Arial／標楷體；頁碼仍於下方靠右顯示 Page X of Y。
- 電話與傳真中的連字號改用 Word 原生不可斷行連字號，完整號碼不拆行；不更改任一電話／傳真數字與地址。沿用原頁碼欄位、頁首 Logo 與頁面邊界。Endorsement 沿用原版，不在本次修改範圍。
- 以 27 份 Word 原生套件／XML、逐頁預覽與完整號碼位置驗證三行頁尾；檢查銀行表格／簽名／頁碼、隔離瀏覽器下載、前端建置與 API 回歸。保留同步 CGL 與 Case 畫面更新，正式 Case 資料不改寫。
- 部署採正式前端映像上僅覆蓋此靜態生成器的新映像；首頁 HTML 與應用程式 bundle 位元組相同。只改此來源檔並追加規則，保留其他工作階段正在編輯或尚未上線的 Case／MasterData 原始碼。部署前核對正式映像及生成器來源，避免覆蓋同步上線。


### 2026-10-19：Lloyd's Market 置頂並固定共用 Lloyd's of London 信評
- Lloyd's Market 展開／收合區塊移至 Reinsurers 清單最上方，其他再保人清單排在下方；原有分類辨識、筆數及生命周期操作保留。
- 分類內全部再保人共用 Lloyd's of London 財務實力評等。2026-10-19 核對 https://www.lloyds.com/about-lloyds/investor-relations/ratings：AM Best A+、S&P Global AA-、Fitch Ratings AA-、KBRA AA-。不混用 AM Best 的長期發行人信用評等；未核對各社展望／發布日期的欄位留空。以 checkedAt 記錄核對日期，並保留官方來源連結。
- 共用資料集中於 backend/masterdata/lloyds_market.py，透過 API profile 與 serializer 提供；既有主檔立即顯示共同信評，不批次改寫正式資料。POST／PUT（含未送 payload）依名稱強制採用共用資料，不能由個別 syndicate 覆寫；儲存時留下當時評等與來源供原有版本快照。從已存共用來源改名離開分類且未提供 payload 時清除繼承來源與信評；普通再保人維持自行維護。
- 分類展開後顯示共同信評、官方來源及核對日期；每家分類成員的信評欄標示 Lloyd's of London。編輯／新增時依名稱即時顯示固定信評，隱藏個別信評增刪欄位，其他欄位照常。無即時外部自動抓取或新增排程，共用評等後續須核對並集中維護。
- 驗證：候選前後端建置、桌面／手機分類置頂與固定信評瀏覽器流程；隔離 lloyds_market_ratings、master_payload_compat、fixed_clause_classes API 檢查；密碼與 3000 件前後端合計一致性通過。部署前後核對主檔資料指紋、案件筆數與 Audit／寄信設定相同，正式 API 唯讀 smoke test 共用評等通過。額外執行 input_validation 廣泛測試，其中 7 個舊付款斷言已由逐筆交易付款規則取代；與未修改正式後端逐項比對，候選版失敗項目完全相同，其他輸入驗證通過。無 migration、無正式資料批次寫入。


### 2026-10-19：QS／XOL Cover Note INFORMATION 一律另起新頁
- 依業主選擇 B，QS／XOL Cover Note 的 INFORMATION 固定從新頁開始，統一原本 QS 另頁、XOL 接續前文的差異。沿用既有段落分頁方式，不加獨立硬換頁空白段落，避免重複換頁。
- 在插入 Case 原文之前定位 INFORMATION 章節首段，確保只改固定章節排版，不因 Case 內容出現 INFORMATION 而誤選其他表格。QS 原有分頁保留且不重複加入；XOL 加入相同設定。包含一般、Facility 與 CGL 的 Cover 章節；Treaty 沿用既有 QS 模板行為，沒有新增必填限制。
- Schedule of Security 與附加條款仍各自另起新頁。所有內容、金額、頁首尺寸／邊界、三行頁尾、銀行與簽名排版均沿用。Debit Note／Endorsement 不變。
- 驗證 29 份 Word／原生 XML 與逐頁預覽（含多地點、長文、CGL／Facility XOL、Case 原文同名），檢查章節新頁、標題連貫、無空白頁、三行頁尾及頁碼；另執行隔離瀏覽器實際下載與 API 回歸。部署只更新文件生成靜態程式並保留最新正式映像的 HTML／bundle，正式 Case 資料不改寫。


### 2026-10-19：一般 CGL 新增 Coverages 與 Self-Insured Retention
- 依業主選擇，一般再保人 CGL 的 Risk Details 在 Interest 後新增 Coverages：Premises-Operations Liability、Products & Completed-Operation Liability、Personal & Advertising Injury Liability、Medical Payment 及 Other 多選。新案與舊案缺欄均預設全不勾，至少選一項；選 Other 必填多行說明，可單獨選 Other。
- Coverages 缺漏及 Other 空白不阻擋草稿儲存，Review／Announce／Cover Note 才要求完整；後端文件授權只讀已存 payload，不能用請求中的選項繞過。輸入不存在的選項或非清單則拒絕儲存。選項按範本順序去重保存。
- Terms & Conditions 在 Deductibles 後新增 Self-Insured Retention，為選填多行文字，與 Reinsured’s Retention 各自儲存；留白或只有空白字元時，檢視／Review／Cover Note 省略該列。填寫時 Word 置於 Deductibles 後。Coverages 置於 Word 的 Interest 後。
- 使用既有 payload 新增 coverages、coveragesOther、selfInsuredRetention；取消 Other 時保留已填說明方便重選，但未選 Other 時不帶入檢視、Review 或 Word。不改既有案件內容，無 migration。Facility、PWS、Swiss、Treaty 與其他 Class 不啟用新增欄位／必填規則；Property／Facility 相同輸入的 Word 全部套件內容與修改前一致。
- 驗證：CGL 新增 API 測試、既有 Information、Case 與現行會計規則，前後端選項／空白字元一致性、金額／密碼一致性、桌面／手機實際操作、Word 欄位順序／多行／空白省略／字面大括號保留均通過。舊 document_generation、input_validation 與 additional_validation 中已由會計 92 規則取代的付款／理賠斷言，失敗項逐一與修改前版本一致，並保留原始測試結果。Debit 幣別測試僅在暫存 fixture 補各再保人／各期獨立 90 天後 401 項通過，正式測試檔不改。保留同步 Lloyd's MDM／信評、Class 先選及 Word 頁尾變更；部署前後正式 managed tables（除 Session）指紋與開關相同。


### 2026-10-19：Property XOL Cover Note 保留 SITUATION，移除重複 LOCATION
- 依業主選擇 A，Class 為 Property 且採 XOL／EXCESS 模板的 Cover Note 移除固定 LOCATION 整列及其後單一純空白間隔列；SITUATION 繼續列出 Case 的所有地址、郵遞區號及原有編號順序。Location 1／2 的保額明細標題不受影響。
- 於 Case 原文插入前依 {{LOCATION}} 定位固定列，避免刪除 Case 原文中的同名字詞。只讀 classOfBusiness，沿用系統 Property Class 判斷，不以 Type 猜測缺漏 Class。Case 資料與 commonValues 的兩個原有映射不改。
- QS、CGL（含 Principal Address、Coverages、Self-Insured Retention）、其他 Class、缺漏 Class、Treaty、Debit Note 與 Endorsement 保留原版；Property Facility XOL 同樣移除重複地址列。
- 保留 INFORMATION／Security／附加條款另頁、三行頁尾、頁首與簽名排版。驗證 33 份 Word／原生 XML、逐頁預覽、多地點完整地址／郵遞區號、Class 邊界與字面 LOCATION／大括號原文；另檢查隔離瀏覽器下載及 API 回歸。部署僅替換正式映像中的文件生成靜態程式，正式 Case 不改寫。


### 2026-10-19：隱藏 Lloyd's 信評來源及核對日期一行
- 依業主要求，移除 Lloyd's Market 區塊與分類成員編輯視窗中 Lloyd's official ratings · Checked 日期的顯示；共用 Lloyd's of London 信評、等級、分類與來源 metadata 保留。僅移除 MasterData.vue 的兩行模板，不改後端、主檔或案件資料。
- 前端建置及既有 readiness 檢查、桌面／手機既有 MDM 瀏覽器流程通過，來源連結不再顯示，共用信評與分類操作仍正常；部署核對來源檔與實際提供的 bundle，後端及資料庫容器保留。


### 2026-10-19：Schedule of Security 維持 0.5 pt 虛線
- 依業主選擇 B，QS／XOL Cover Note 各再保人比例與總比例之間維持目前 0.5 pt 虛線，沿用現有線長與比例欄位置。
- 核對正式生成器與兩份 v6 Cover 範例，確認為比例欄儲存格上框線 dashed／4 eighth-points；本次只記錄版面決定，沒有修改生成程式、範例或正式資料，沿用已發布的 v6。


### 2026-10-19：一般 CGL Interest 預填、Type 選項與 Limit of Indemnity
- 依業主三項選擇，新建一般 CGL 預填 Reinsurance of the Reinsured’s liability under the original policy.，可自由編輯。只有新案仍保留預設原文時會隨 CGL／其他範圍切換預設；AE 已自訂的文字不覆寫。既有案件載入／儲存保留原 Interest，包含舊 Property 原文或空白；續保與批單沿用既有內容。後端 normalizer 不自動改寫 Interest。
- 一般 CGL Type 改為 Products Liability／Commercial General Liability 必選單選，預設空白。QS 為「名稱 Facultative Reinsurance as original」，XOL 為「名稱 Excess of Loss Facultative Reinsurance as original」，保留各自結構後綴。舊 FACULTATIVE 沿用轉 QS；可辨識既有完整 Type，有／無 as original 均只組合一次。
- 未選 Type 可儲存未完成草稿，Review／Announce／Cover Note 必須選定；不在兩個選項內的非空名稱拒絕儲存，舊自由輸入名稱需選為有效名稱後通過。文件授權檢查已存 Type，請求文字不能繞過。一般 CGL Word 以確認後格式輸出 Type，其他險種與 Facility／PWS／Swiss／Treaty 沿用原有 Type。
- 一般 CGL Limit of Liability 更名為 Limit of Indemnity，同步 key-in、案件檢視、Review、草稿／Announce／文件檢查及 Cover Note 固定標題。沿用 payload.limitOfLiability 單筆非負金額與 Case 幣別，保留原有驗證時點及錯誤代碼；不增加多筆或自由文字，不改既有金額／幣別。Property 與特殊再保組合名稱維持。
- 無 migration、無既有 Case 批次改寫。保留 Coverages／Self-Insured Retention、Information、Principal Address、Class／Structure 先選、Lloyd’s 信評及最新 Word 頁首／頁尾／Information 分頁及 Property XOL Location 去重。
- 驗證：5 組相關隔離 API 共 336 項、前後端 Type／標籤 129 組、合計 3000 組與密碼 20 組一致性；32 項桌面／手機實際操作、新舊 Interest／空白保留、Type 清除／選擇／重開、Review 與 Word 下載；26 項 Word 內容／原文字面保留及 Property／Facility QS／XOL 完整套件一致性，QS／XOL 離線預覽通過。部署前後正式 managed tables（除 Session）指紋與開關一致。


### 2026-10-19：Lloyd's Market 共用信評 Edit
- 在 Lloyd's Market 信評標題旁提供 Edit，沿用 mdm.write 權限；mdm.read 使用者可查看，但不能儲存。可增刪／修改 Rating agency、Grade、Outlook、Rating type、As-of date、Status。來源維持 Lloyd's of London，原先移除的官方連結與 Checked 日期顯示不恢復。
- 新增 ri_market_rating_profiles 表集中保存共用資料與 rowVersion，首次儲存前沿用既有四組評等；GET 不建立資料。API /api/master-data/lloyds-ratings 的 GET／PUT 套用認證、CSRF、權限及樂觀版本檢查。儲存寫入一筆共用版本與 Snapshot，Audit 仍依暫停設定運作；不批次改寫 125 筆成員主檔或既有案件。
- 全部 Lloyd's Market 成員（含 Inactive、既有及未來新增成員）讀取同一個持久化信評；個別成員仍不可覆寫。MDM GET 一次讀取共用資料供所有成員使用，避免逐筆查詢。並保留來源既有 metadata；手動編輯不宣稱已重新核對官方來源，因此清空該次信評 checkedAt。
- 編輯取消不寫入；必填 agency／grade、至少一筆、最多 50 筆；失敗保留草稿，版本衝突可選擇重新載入最新共用版本。普通再保人信評維持獨立。
- 驗證：migration 與 model state 一致、Django check、隔離 lloyds_market_editor（36 項）、lloyds_market_ratings（17 項）、master_payload_compat（13 項）、fixed_clause_classes（32 項）、密碼及 3000 案件合計一致性；桌面／手機共用編輯、取消、欄位驗證、儲存／重整／成員同步、增刪機構、衝突與唯讀流程通過。正式部署先備份，使用 candidate one-off 維護者執行 migration，依既有 db_harden 重新授權後再切換程式；正式既有業務資料指紋不變，共用資料表可讀且初值保留。

## 2026-10-19 — Debit Note instalment table
- User selected a three-column Word schedule: Instalment / Payment Due Date / Amount, one row per period.
- Enabled schedules with at least two printable periods use a standalone table with repeating header and unsplit rows. Preserve Case order, existing period date calculation, currency precision, premium/ratio priority and first-period rounding adjustment. Displayed instalments total to the displayed Net Due; retain the financial summary total above the schedule.
- Non-instalment and legacy single-period documents retain their existing output. Treaty retains its validation exemption. No new Case validation or accounting changes.
- Preserve Arial/標楷體, existing margins/logo/footer/signature rules and bank information at 9 pt. Word only; offline QA PDF previews remain temporary.
- Deploy only the document generator static asset on the current frontend image; preserve all other application assets and concurrent work. User authorized immediate implementation, verification and deployment after each choice.


### 2026-10-19：Debit Note 銀行資訊與簽名可分頁
- 依業主選擇 B，維持銀行資訊與簽名可分在不同頁；不將銀行資訊與簽名整組綁在同頁。銀行表頭與帳戶資料仍保持同頁，簽名圖片／公司署名／E&OE 仍整組保持同頁。
- 保留已上線 v7 三欄分期表格與範例。本次只記錄決定，無生成器、範例或業務資料修改，無需重新部署。


### 2026-10-19：一般 CGL Aggregate Limit／Underlying Limits／Sub-Limits
- 依業主逐題選擇，一般再保人 CGL 的欄名改為 Aggregate Limit：選填單筆非負金額，沿用 aggregateLimit 與 Case 幣別；空白不輸出，明確輸入 0 仍輸出。Sub-Limits 為選填多行文字，空白不輸出。
- 一般 CGL 的 Underlying Limits 只在 XOL 顯示；草稿可未填，Review／Announce／產生 Cover Note 時必填。QS 不顯示、不輸出，沿用既有 QS 儲存清空規則；生成文件不改寫舊案資料。
- Case 編輯、Overview、Review、前後端完整性檢查與 Word 同步。一般 CGL XOL 的 Word POLICY LIMIT 固定標題改為 AGGREGATE LIMIT；空白欄位整列省略，多行文字及字面 placeholder、明確零值保留。
- 範圍限一般 CGL；Property、Facility、PWS、Swiss、Treaty 維持既有欄名與驗證。無 schema migration、無舊案批次修改；保留同時上線的 Lloyd’s 共用信評編輯及 Debit Note 三欄分期表。
- 驗證：隔離 API 五組共 258 項、32 項桌面／手機瀏覽器檢查、39 項 Word 內容及 Property／Facility XOL 套件逐檔比對、161 組 Type／limit／Underlying 前後端一致性、3000 組合計與 20 組密碼一致性通過。QS／XOL Word 離線預覽可正常排版。
- 正式部署先備份再切換候選 backend／frontend；Django check、Nginx、靜態資產雜湊與健康檢查通過。正式 managed tables（Session 除外）筆數／內容指紋與 Audit／寄信／付款提醒開關保持一致；隔離測試資源用後清理。


### 2026-10-20：Great American Facility Property 規則摘要及同仁覆核問卷
- 依業主逐題確認及同仁覆核格式選擇，System Reference Data → System Guides 原 Great American 入口更新為 v2.0 Word；適用 Great American Insurance Company, Singapore Branch (Facility)，僅限 Property。文件內容確認日期為 2026-10-19，2026-10-20 完成發布。
- 前4頁整理季度末＋90日曆天到帳、＋75日曆天提醒、各期／批單歸期、整筆 Cedant 收齊後付款、人工確認付款完成、退匯及實際到帳系統外追蹤、退款先收再退／一次退清／不抵保費，以及理賠15天到帳與每7天提醒；後2頁共8題，供同仁勾選符合實務／有差異並補充說明。
- 原200題問卷備份後替換同一文件入口，保留其他指南及既有下載權限。本次僅更新 Word、下載登錄及本維運紀錄，未實作會計、逾期或提醒邏輯，未改寫案件及會計資料。
- 驗證：6頁逐頁預覽、52個Word可填控制項（40個未勾選選項、12個文字欄）、日期與閏年範例、隔離指南列示／所有指南下載／既有角色權限、正式下載雜湊及Django check；核對所有既有Python／Word雜湊，確認僅目標下載登錄及新文件變動，前端與資料庫容器保持原狀。


### 2026-10-20：Allianz Facility 會計日期及人工收付規則部署

- 適用 Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility) 指定再保人列；混合案件其他再保人沿用各自規則。原保單／續保採生效月份，分期採各期 Payment base date 月份，加費及退費／退保採生效日與實際 Announce 日較晚者所在月份。
- Allianz 保費與退款均採基準月份實際月底＋90個日曆天最晚到帳、＋75個日曆天開始會計提醒；包含週末假日，不作營業日調整。固定90天在 Case／分期介面及後端統一處理，Cedant 自身天數與其他再保人不變。
- 正常保費付款前，對應期別的 Cedant 應收款須由會計人工登錄全額收齊。此為人工確認收齊，不要求先完成銷帳；收付、對帳、沖帳、銷帳各自仍由財務操作。
- 超過原90天最晚到帳日，且會計尚未登錄全額付款完成，自動顯示逾期。原基準月與原結算日不變，不逐期移期，不設 Allianz 延期申請、同意或同意證據留存流程；原問卷先前的同意與人工逾期標示規則由本段取代。
- 退費與保費分別收付，不抵減；不同原到帳期限的 Allianz 保費分開登錄匯款，理賠與保費／退款不放在同一筆匯款。畫面及 API 均限制。更正／撤回 Cedant 收款不得繞過已付款 Allianz 的全額收款前提。
- Allianz 理賠採成功建立該筆理賠應收應付（畫面標示 Claim Announce）的伺服器時間，使用台灣日期＋15個日曆天為最晚到帳日；每筆新增請款各自起算，更正保留原公告時間，部分到帳保留原期限。舊有成功建帳的伺服器 createdAt 可作歷史依據，不以出險日、人工義務日期或保單公告日代替；無可靠時間列待確認，不猜日期。
- 理賠自公告後第7天起，每7個日曆天在 Accounting 顯示追蹤提醒，財務可逐筆登錄追蹤紀錄；到全額到帳並由會計人工登錄後停止。理賠獨立收付，不納入12個保費結算點。提醒採畫面列示，不新增對外寄信流程或變更既有寄信／Audit 設定。
- 使用既有 Case payload 保存公告時間及追蹤紀錄，案例編輯保護財務紀錄、續保／批單清除舊追蹤紀錄；沒有 migration，沒有批次改寫正式案件、交易、關帳報表或收付紀錄。
- 驗證：Allianz 日期與會計 API 專項、既有92項會計／邊界／共用計算／理賠／Case／工作流程／AUW／對帳參考號／Audit 暫停回歸，均於任務專用隔離 MySQL 及最小權限帳號執行；實際瀏覽器驗證財務與非財務權限、桌面／手機、全額及部分收付、逾期與追蹤紀錄，另核對3000組合計與密碼一致性。部署保留同期 CGL／Word 及主檔更新，先備份程式、映像與資料庫，再驗證正式映像、健康狀態及資料摘要。


### 2026-10-20：Great American 分筆安排付款規則修正
- 依業主指定文字及後續範圍選擇，取代先前每案／每期一律分開匯款的規則：多筆已符合付款條件、但原到帳期限不同的保費，分別依各筆原期限安排，不合併匯款。原到帳期限相同的保費能否合併匯款尚待確認；同筆可分次付款、原全額到帳期限不變。
- 同步更新規則摘要及GAR-03同仁覆核題，Word改為2026-10-20 v2.1。System Guides維持原Great American入口，發布前備份v2.0。此次僅更新文件、下載登錄及維運紀錄，無會計功能實作或業務資料改寫。
- 驗證6頁排版、8題及52個可填控制項、舊文字移除與其他規則一致；隔離指南列示／下載／既有權限、正式下載雜湊及Django check通過；保留所有其他程式／文件，前端及資料庫容器維持原狀。


### 2026-10-20：一般 CGL Notices、隱藏估值／賠償期間及地址規則確認
- 依業主三項選擇，一般再保人 CGL 的 Terms & Conditions 新增 Notices：選填多行文字，沿用 payload.notices（既有 5000 字上限），可載入及修改舊文字。Overview／Review／Cover Note 保留多行內容；空白或全空白不輸出，Word 整列省略。
- 一般 CGL 隱藏 Basis of Valuation、Basis of Valuation — Other 及 Indemnity Period；Overview／Review／Cover Note 不輸出。保留既有 payload 的估值與期間資料，不在載入、儲存或生成文件時主動清空。一般 CGL 不再因隱藏的 Other 說明空白而阻擋 Review／Announce。
- Principal Address 沿用多筆格式，每筆地址及 3–6 位數字郵遞區號必填，保留前導零、增刪確認、既有草稿及 Review／Announce／Cover Note 驗證；本次不修改地址儲存或驗證規則。
- 範圍限一般 CGL；Property／Facility／PWS／Swiss／Treaty 維持既有欄位與 Other 說明檢查。Word 以既有一般 CGL Cover scope marker 省略兩項財產險欄位，Debit Note／Endorsement 沿用原規則。無 migration、無舊案批次改寫。
- 整合部署前已上線的 Allianz 會計與 Great American 文件更新，僅覆蓋本次目標檔案，保留其他更新。
- 驗證：六組隔離 API 共 308 項、36 項桌面／手機瀏覽器操作、56 項 Word 欄位／地址／Property 與 Facility QS／XOL 套件逐檔一致性、180 組完整性與 161 組 CGL Type／limit 前後端一致性、3000 組合計與 20 組密碼一致性通過；QS／XOL Word 離線預覽通過。
- 正式部署先備份再切換候選版本，Django check／Nginx／健康及靜態資產雜湊通過；managed tables（Session 除外）筆數／指紋及 Audit／寄信／付款提醒開關保持一致。測試使用專用隔離資料庫及模擬 API，部署後清理測試資源。


### 2026-10-20：Great American Singapore Facility Property 作業邏輯
- 依業主要求及範圍選擇，部署 Great American Insurance Company, Singapore Branch (Facility) 的 Property 已確認規則。原單／續保取生效季度，各期取自己的 Payment Base Date；加費／退費批單取生效日與成功 Announce 台北日期較晚者所在季度。季度末＋90日曆天為最晚全額到帳日，＋75日曆天開始畫面提醒，跨年／閏年照算、不調假日；不設延期申請或同意流程。
- GA保費付款須先收齊對應整筆Cedant款（含其他再保人分攤）並逐筆人工確認。分期各自判斷。可分次匯出，原期限不變；不同原到帳期限的多筆保費各依原期限分別付款，不合併匯款。同期限能否合併仍待確認，本次沿用既有相同收付方向／幣別／收款對象的操作，不新增合併功能。
- 全額匯出且銀行成功後，會計以既有人工確認完成付款；未確認前按原期限自動顯示逾期，確認後停止。退匯保留原完成狀態；實際到帳、退匯與重付安排在系統外追蹤，無新欄位／自動延期／新逾期流程；已確認付款不可撤回原完成或沖回既有匯款。
- 退款季度90／75天，未人工確認收齊按原期限顯示逾期。退費批單所有再保人退款須收齊並逐筆人工確認後，才能一次全額退清Cedant，不必等待季結算。GA保費與退款分別收付、不得抵減；本金須以實際銀行收款全額收妥，非現金沖帳或銀行費不得視為收齊。
- 理賠獨立收付；每筆成功請款的Claim Announced台北日期＋15日曆天到帳，第7天起每7天畫面提醒，直到全額到帳且人工確認。部分到帳不重算原期限或提醒，新請款各自起算；逾期持續提醒。會計可登錄追蹤備註，記錄操作者／時間並檢查版本與權限。
- 沿用現有人工對帳／逐筆沖銷確認、資料鎖定與Audit暫停／寄信開關；提醒為Accounting畫面列示，不新增寄信。讀取時計算既有案件日期，不批次改寫原案件、交易或付款紀錄，無migration。其他Class、一般再保人、AUW、Swiss及Allianz維持原規則。保留同期CGL Notices與Great American問卷v2.1。
- 驗證：GA專屬API與曆法／隔離邊界、既有會計92規則及邊界／共用運算、Allianz、案件與工作流程、理賠、AUW、對帳參考與Audit暫停；實際桌面／手機付款及理賠追蹤操作、105組非目標範圍前後完全相同、3000組金額與密碼一致性。正式部署前備份資料庫及變更檔案；切換後核對實際映像／靜態資產、Django與Nginx、原資料表及開關指紋，資料庫容器不變。


### 2026-10-20：一般 CGL 最後確認項目整批實作並一次上線
- 業主要求所有欄位與範本差異整理、選擇題確認完畢後，再統一實作、驗證並一次部署；本批依最後八項已確認規格整批切換，不逐題部署。
- 一般 CGL 的 Reinsurance Conditions 提供 LMA3100 Sanctions Limitations and Exclusion Clause、LMA5396 Communicable Disease Exclusion、Excluding Ex-Gratia and without prejudice payment 三項人工勾選，預設未勾，不自動帶入。沿用 manualClauses 的代碼／名稱及既有 Case snapshot；可各自勾選／移除，其他人工、Universal 與固定條款保留。既有固定代碼已包含時顯示鎖定，不改寫主檔或批次補條款。
- 新增 payload.cglAnnual 勾選，只有一般 CGL 顯示，預設勾選；舊案缺欄位也按勾選顯示，Cover Note 加印 (Annual)，可取消並儲存。取消後重開仍保留。只作文件標示，不變更保費、年化、稅額、佣金、分期或任何會計計算。GET／生成文件不改寫舊 payload；個案主動儲存才保存勾選值。非一般 CGL 不產生新預設，已有值切換範圍後保留但不啟用。
- 一般 CGL Overview／Review／Cover Note 的期間標題統一為 Period。Case 日期輸入仍保留 Effective Date／Expiration Date，以及 12:00／00:00 選項，預設 12:00；文件列印實際選擇時間。
- 一般 CGL Cover Note 停止輸出 Loss Payee，既有資料保留。XOL 移除範本沒有的 LOCATION 及 TOTAL SUM INSURED 固定列，地址僅於 Principal Address 列出；保留 Case 地址、郵遞區號與保額資料。
- 業主最後選 C：Case key-in、Overview／Review 與 Cover Note 各自保留目前欄位順序，Case key-in 不必與 Cover Note 相同。本批僅新增已確認控制項、改名與移除指定文件列，其餘列不重排；先前 Principal Address 多筆／3–6 位郵遞區號及 Information 規則沿用。
- 範圍仍限一般再保人 CGL，Facility／PWS／Swiss／Treaty 與其他 Class 沿用既有畫面及輸出；Debit Note／Endorsement 不加 Annual、不套用一般 CGL Cover 移除列。無 migration，無正式 Case 或 MDM 批次改寫，保留同期 Allianz／Great American／主檔及文件更新。
- 驗證：七組相關隔離 API 共 397 項；33 項桌面／手機實際操作及 Word 下載；92 項 Word 原生套件／內容／逐列順序及 Property／Facility QS／XOL、CGL Debit／Endorsement 套件逐檔一致性；161 組 CGL Type／limit、180 組完整性、含 Annual 狀態的 3000 組合計及 20 組密碼前後端一致性通過。QS／XOL Word 離線預覽通過。
- 正式一次部署前備份程式與映像，核對來源未變後切換；Django check／Nginx／健康及靜態生成器雜湊通過。正式 managed tables（Session 除外）筆數與指紋、Audit／寄信／付款提醒開關一致；專用隔離測試資源部署後清理。


### 2026-10-20：Great American 逐案／逐期人工收付款登記
- 依業主選擇B及後續確認，本系統以會計逐筆登記、人工確認的收付款資料為依據；實際匯款安排由會計於外部系統處理。此條目取代先前同期限可跨案件合併登記的暫行作法及「同期限能否合併匯款待確認」的文件文字。
- Great American Singapore Branch (Facility)的Property收付款，逐案／逐期登記，相同或不同期限均不跨案件、期別一起登記；理賠按各筆請款分開登記。允許相同的外部系統參考號重複用於不同案件／期別／分次紀錄，資料仍依獨立登記識別碼保存，不因參考號相同自動合併。
- 同案同一期的既有不可變分攤交易可在一筆案件／期別登記內分攤；保留退費批單須一次全額退清Cedant的原規則。跨多期的舊合計交易不自動比例登記，須先核對期別。各筆原期限、累計收付、餘額、人工確認、既有分次付款、收齊條件、退款及理賠提醒維持原規則。
- 畫面明示由會計登記實際日期、金額及外部參考號，改用Record receipt / payment、External system reference、View registration等用語；銀行成功仍由會計人工查核及確認，未新增外部系統串接或狀態查核。登記條件只依本系統已保存與人工確認的資料判斷。
- System Guides原Great American入口同步更新Word v2.2：6頁、8題同仁覆核、52個可填控制項；原v2.1保留並備份。本次無migration、無既有案件／付款紀錄改寫，Audit暫停、寄信設定及其他再保人既有流程保留。
- 驗證：GA季度／收款條件／分次／退款／理賠與新增逐案逐期及共用外部參考號API測試；既有會計、Allianz、案件、工作流程、理賠、AUW、對帳參考及Audit回歸；105組非目標會計結果完全相同、3000組合計及20組密碼一致性；桌面／手機實際登記及參考號重用；Word修改頁預覽與下載／既有權限。正式發布前備份資料庫及變更檔，發布後核對映像／靜態資產／指南雜湊、Django與Nginx、資料及開關指紋。


### 2026-10-20：Case Clause Title 持續同步 MDM；Cover／Debit 雙 Ref.
- 業主明確選 A：Case 條款 Title 持續跟隨 MDM 最新 Title 原文，不由文件拼接 Code＋Title。本段取代舊規則中 Title 固定使用 Case 快照的部分；已選條款 Code／筆數及歷史文件不因此自動增刪或改寫。
- 以條款主檔（entityType=clause）的 name／Clause title 為準；缺少條款主檔時使用所選 Class／Reinsurer 的對應固定條款 Title，再缺少則保留 Case 自訂 Title。既有選用且已停用的主檔仍可提供當前 Title。
- 案件檢視、編輯與 Review 使用相同解析；開啟、切回視窗及前景每30秒更新 MDM，Review／明確儲存／生成文件前重新讀取。更新僅替換 Title 的顯示，不覆寫未存業務欄位；生成前讀取失敗則阻擋使用過期 Title 的下載。
- 正常儲存 Case 時將當前 Title 寫入該次版本；純讀取及文件生成不批次改寫 Case／MDM。Word 包含 MDM Title 原文，無論 Title 自身是否包含 LMA／NMA／LPO，均不另外補碼；移除 Intermediary 的固定 Title 覆寫。
- Cover／Debit 的內文、續頁與附加條款引用、檔名統一顯示系統 twRef 及 AUW manualTwRef，以「 & 」連接並去重。Endorsement 格式維持。
- 驗證：27項解析檢查、15項實際瀏覽器流程（含不帶 Code 的新 Title、持續更新、編輯保留及模擬明確儲存）、35份Word／917項內容結構、Marketech排版、17項既有readiness、fixed_clause_classes／master_payload_compat／case_documents 隔離API通過。另有先前即存在的 document_generation／auw_reference_only 後端回歸失敗已記錄，未修改其後端行為。僅部署前端，保留同期Accounting更新。
- Asia等一般再保人付款天數必填時點仍待業主確認，未於本批更改。


### 2026-10-20：四類會計收付、提醒及銷帳條件統一確認
- 業主完成逐項確認後指示開始修正。本段優先於先前一般／AUW／Allianz／Great American Singapore Facility Property 同項規則；Swiss及其他未變更特殊規則保留。
- Allianz 保費及退款採基準月底＋80日提醒、＋90日到期；Great American Property採基準季末＋80日提醒、＋90日到期。原單／續保、分期及批單起算來源不變，AUW月底＋120日及提前10日不變。
- AUW、Allianz、Great American Property付款須先登錄整期Cedant全額收款（含其他再保人分攤），並逐筆人工銷帳。一般案件不新增此收款先後條件。已付出時不得藉取消收款銷帳或撤回收款破壞收妥前提。
- 四類保費均整筆登錄餘額，Great American不再允許分次匯出；既有部分收付歷史保留。付款過原到期日後，即使已登錄全額付款，尚未人工確認完成仍顯示逾期；原期限不重算。
- 四類退費須先收到所有再保人退款並逐筆人工銷帳，才可將該批單所有Cedant退款交易一次全額退清；可提前退、不等結算日。Cedant帳款期限維持生效及Announce台灣日期較晚者＋該批單Cedant天數。
- 一般及AUW再保退款必須全額收款登錄，不能以抵銷取代；原保費及再保退款分開全額登錄。Allianz／Great American原有禁止保費退款抵銷限制保留；一般Cedant端的合法抵銷仍須先滿足全部再保退款實收及銷帳。AUW要求整期Cedant實收，因此不能以Cedant抵銷繞過此條件。
- 四類賠款統一從帳款建立的台灣日期加15日到期，到期前7日、到期日及其後每7日提醒。全額收款登錄即停止該筆提醒，不等待銷帳；部分收到不改原期限。移除舊Allianz／Great American建帳第7日起提醒與GA等銷帳才停止的差異，保留追蹤備註歷史。
- 以共用payment_policy計算日期、整期收妥、退款放行及付款完成；讀取不改寫案件及既有金額，不做schema migration或舊收付批次改寫。批次操作先檢查所有案與全部Cedant退款交易，任一失敗即回復整批。保留Finance權限、修改原因／歷史、T3最終鎖定、賠款已收金額上限及Audit暫停設定。
- 財務賠款信件沿用既有內部收件人、寄信開關及SMTP設定；沒有寄信設定不實際寄送。保費畫面逾期須人工確認才消除，郵件仍按已確認的餘額規則停止；Signed Slip及忘記密碼寄信設定不變。
- 同時保留當日Great American登錄範圍修正：每次限同案件及同一期／同一賠款請求，拆分交易仍逐筆記錄；外部會計參考號可在分開登錄中重複使用。

### 2026-10-20：會計與 Cover Note／Debit Note 的逐步取位及 T1 一致
- 依業主逐題確認，這批完成後統一修改、測試與部署。TWD 金額每一步四捨五入到整數；USD 每一步保留兩位小數。佣金與 Tax 以取位後的分出保費為基礎；T1 為取位後分出保費減佣金及 Tax。Case 金額合計、會計、付款排程與 Word 同一口徑。原保費先按幣別取位，再算承保比例，不只格式化最後顯示。
- 確認例：TWD999、10%／15%／1% → 分出保費100、佣金15、Tax1、T1=84。TWD1001、33.33%／12.5%／1.5% → 334／42／5／287；USD1001.00 同比例 → 333.63／41.70／5.00／286.93。
- Debit Note 上方分出保費、佣金、Tax 採會計逐再保人取位後合計；Net Due 與全部 T1 一致。分期表只顯示各期 T1，每家再保人先分配再加總，與期別交易一致。首期吸收尾差，正數總額時首期最低0，剩餘尾差按 Case 順序扣回後續期，保持總額一致。T2/T3 不列在 Debit Note 分期表。
- Word 自動產生的臺幣標示統一 TWD，固定銀行幣別亦同；AE 條款原文不改。上方保費／佣金／Tax／Net Due 仍分幣別、數字兩欄；分期 Amount 同格顯示如 TWD287／USD286.93。保留 A4、Logo、頁尾、銀行9pt、分期重複表頭、銀行資訊與簽名可分頁等既有版面。
- TWD 的 Case 100% Premium、每筆再保人 Premium、每期 Premium 均只准整數；前後端皆提示並阻擋小數輸入，不能由 UI 或 API 偷偷取整。比例欄位小數不改；USD 的新輸入規則不額外變更。
- 依業主選擇 B，沒有收付款或銷帳紀錄的既有 TWD 案件納入一次性轉換：舊保費欄位含小數則取整，並重新計算既有保費交易。已有收付款／銷帳（含取消後歷史）者保留原輸入、會計金額與歷史 cents 計算模式；不清除、重算或覆寫收付款／銷帳。legacy-cents／currency-stepwise-v1 為伺服器保留旗標，不能由新增或編輯請求偽造。新續保／批單草稿使用新計算模式，原案件不改。
- 一次性命令 convert_twd_premiums 預設 dry-run，--apply 才寫入；加鎖、逐案 rowVersion +1，留 Entity Snapshot，Audit 沿用暫停設定。可重複執行，已轉換案件不再更動。正式套用前備份，部署前後核對變更範圍與未涉及資料表。
- 理賠金額與收付款登錄的既有精度、付款日規則、PDF 退役、Treaty 文件必填豁免不改。批單 Debit Note 內容與版面仍待後續討論。本次回歸另補齊 case_workflow 測試範例本來缺漏的獨立再保人付款天數，不更改產品付款條件。
- Case 與 Accounting 畫面依幣別顯示：TWD 整數不補 .00，USD 維持兩位；已有歷史 TWD 小數仍完整顯示。收付款及理賠資料的數值不由格式化函式改寫。

### 2026-10-20：固定技術規格表更新為實際版本

- 現場核對執行中版本：Docker 29.8.1→29.8.2、Docker Compose v5.5.1→v5.6.0（主機套件升級）；Python 標示為完整版本 3.13.16、Nginx 標示為 1.28.3。其餘元件版本不變。
- PDF 服務（Gotenberg）維持退役，不列入規格表（使用者決定）。


### 2026-10-21：更新完整 MDM／Schema 系統指南
- 依使用者指示補齊本次改版全套文件；以目前 VM 結構與程式規則重整兩份完整指南，非只改日期。涵蓋 Lloyd’s Market 共用評等表、CGL、付款／退款／理賠、逐筆人工結清、T3 最終鎖定、TWD 精度、Word 與對帳參考維護。
- information_schema 核對 28 表、273 欄、80 索引、20 外鍵、38 CHECK、5 trigger、37 migration；記載 VM 為正式系統、PDF 容器已退役、Audit 暫停及獨立財務寄信開關現況。
- System Reference Data → System Guides 原 MDM／Schema 入口與英文檔名保留，檔案本體及發行日期同步更新為 2026-10-21；其他指南與上傳模板不變。
- 僅發布兩份文件及其預設日期，無 schema migration、無業務資料寫入。完成逐欄覆蓋、Word XML／連結／離線分頁、隔離及正式角色權限與下載 SHA-256 核對；保留來源、舊映像及 metadata 備份。


### 2026-10-21：週三除錯——保費負數對稱取位、提醒信日期、暫停時逾期提醒間隔、批單沿用付款天數
- **保費取位正負對稱（使用者選「和正數對稱」）**：TWD 逐步取位到元、USD 到分時，負數的 .5 改為遠離零（-50.5 → -51），與正數 50.5 → 51 對稱。原本負數 .5 往零捨去，佣金或稅剛好算出 .5 時，全額退保後各 Leg 會留下 1 元（或 1 分）差額。後端 premium_money、畫面 premiumMoney、Word premiumRound 三處同步；正數結果不變（2 萬組隨機案件新舊逐位元組相同），legacy-cents 案件維持原算法。驗證：6,000 組前後端一致、6,000 組原保單＋全額退保逐 Leg 歸零；premium_rounding 測試加入 3,000 組退保歸零檢查。
- **付款提醒信日期**：信件改寫觸發提醒所依據的真正到期日，並附較早的會計提醒日（「到期日 2026-08-31 (Taiwan)；會計提醒 2026-08-21」）。原本只寫會計提醒日，「7 天後到期」的信會列出已過去的日期。Swiss 原有寫法不變。
- **寄信暫停時的逾期提醒**：寄信未啟用（suppressed）時，逾期提醒也維持每 7 天一次，不再每天產生一筆；到期前 7 日與到期日只在當天觸發，日後開啟寄信不受影響。與 2026-09-26「suppressed 算已提醒」一致（僅用於每週間隔）。
- **批單付款天數一律沿用（使用者決定，取代 92 項規則第 35 條「批單 Cedant 自填天數，不沿用原單」）**：新批單的 Cedant 與各再保人付款天數沿用來源保單，Draft 仍可修改；Announce 後鎖定規則不變。AUW 批單因此沿用原單 Cedant 120 天。
- **測試**：依 10-16～10-20 已確認的新規則更新過時的 19 組測試（未放寬檢查；依各規則改用整筆保費、逐筆交易、人工銷帳、出險日分攤、每期獨立天數等情境），兩支瀏覽器測試用的準備資料腳本移到 backend/qa/browser_fixtures/。全部 68 組資料庫／API 測試通過。


### 2026-10-22：Reinsurer 信評欄位與日期規則
- 依業主表格，一般再保人及 Lloyd's Market 每筆信評必填 Rating agency、Grade、As-of date；Rating type 固定 Financial Strength（畫面唯讀、API 強制同值）。Checked at 為兩者選填，填寫時需有效 YYYY-MM-DD 日期，儲存／重開保留，不再由 Lloyd's 儲存 API 強制清空。
- Outlook、Status、一般 Legal entity、Source URL 從信評表單移除；Lloyd's legal entity 固定 Lloyd's of London。未恢復已移除的官方來源／Checked 顯示一行。既有隱藏歷史 metadata 保留，不批次清除。
- 一般再保人既有評等改為可直接編輯上述欄位；新增仍先按 Add rating 再儲存，未加入的草稿會提示；一般再保人仍可無信評，共用 Lloyd's 至少一筆，兩者最多 50 筆。
- 既有沒有日期的信評不補造或批次改寫；編輯信評須補有效基準日期。未變更舊信評的停用／其他欄位 API 更新，以及個別 Lloyd's 成員繼承共用資料，保留舊日期，避免無法在成員頁填寫共用日期或影響生命周期操作。共用 Edit 的新儲存仍一律要求每筆日期。
- 驗證：rating_field_rules 33 項、更新新日期 fixture 的 lloyds_market_editor 36 項與 lloyds_market_ratings 17 項、master_payload_compat 13 項、fixed_clause_classes 32 項，共 131 項 API／MDM 檢查；密碼與 3000 案件合計一致性、桌面／手機一般及 Lloyd's 新欄位、日期必填、查核日期選填、儲存／重整／繼承、唯讀權限通過。部署前後既有 managed models（除 Session）資料指紋與開關一致，無 migration 或正式業務資料批次改寫。


### 2026-10-22：Rating agency 限定四家
- 一般再保人與 Lloyd's Market 共用信評的 Rating agency 改為下拉選單，只可選 S&P Global、A.M. Best、Moody's、Fitch。新增與編輯 API 同步拒絕其他機構。
- 舊 AM Best、Fitch Ratings 在表單正規化顯示為 A.M. Best、Fitch；其他歷史機構保留，編輯時顯示歷史提示並要求改選或移除。未自行新增 Moody's 信評、刪除 KBRA 信評或改造評等／日期。未改信評的生命周期操作與個別 Lloyd's 成員繼承維持相容。
- 無 migration 或正式業務資料批次改寫；隔離 API 回歸與桌面／手機下拉選單、歷史資料處理、儲存／重整／繼承驗證通過。部署前後正式資料指紋一致。


### 2026-10-22：QBE Hongkong & Shanghai Insurance Limited (Facility) Property 會計規則
- 僅適用 Class of Business 為 Property 且再保人為 QBE Hongkong & Shanghai Insurance Limited (Facility)。核保年度由8月1日至次年7月31日；Q1為8–10月、Q2為11–1月、Q3為2–4月、Q4為5–7月。原單／續保取生效日、分期各取 Payment Base Date；加費及退費批單取批改生效日與成功 Announce 台北日期較晚者。
- 保費與退款採核保季度末＋80日曆天提醒、＋90日曆天到帳，不調週末假日。原＋75天提醒由本次確認取代。各筆原期限不因收款延遲、部分歷史收付或分筆作業重算，不設延期流程。
- QBE保費須收齊該案／期／加費批單對應整筆Cedant現金本金（含其他再保人分攤）並逐交易人工確認後才放行。保費整筆登錄剩餘餘額，取代原可分次付款；同案同一期分攤交易可一起登錄，禁止跨案、跨期合併，即使同到期日亦分開；外部參考號可於各獨立登錄重複使用。
- 全額付款登錄後仍須財務查核銀行成功並人工確認完成，才停止付款逾期。完成後不撤回／沖回原付款；QBE實際到帳、退匯及重新付款在系統外追蹤，無新增到帳／重付欄位或重新付款逾期。已付出不得藉撤回Cedant收款或確認繞過先收後付。
- 退費批單須先全數收齊所有再保人退款本金並逐筆人工確認，才可一次全額退清Cedant，可提前安排、不等季結算。退款及保費分別收付、不抵減；銀行費及非現金沖帳不得視為收齊本金。QBE退款未人工確認收齊時依原90天期限保留逾期判斷。
- 理賠獨立收付；每筆請款成功登錄並建立帳款的台北日期＋15日曆天為最晚全額到帳日，到期前7日、到期日及之後每7日提醒，不調假日。新增請款各自起算，部分收款不改原期限。全額收款登錄即停止提醒及逾期、改顯示待人工確認，銷帳仍由財務逐筆確認；取代原第7天起提醒及必須人工確認才停止的文字。沿用財務追蹤備註、權限與既有寄信開關，不新增外部通知。
- 新案及既有未結清帳款適用；不批次改寫Case、交易、付款、銷帳或歷史紀錄。既有有效完成確認的QBE帳款保留原日期，新QBE確認保留版本標記；失效確認不視為已結清。無schema migration。其他Class、一般QBE及其他Facility沿用原規則。
- 驗證：完整隔離資料庫／API測試組（含QBE日期／收款放行／退款／理賠／逐案逐期／歷史保留）、3000案件合計與密碼一致性、非目標會計結果逐項比較、桌面及手機實際登錄／人工確認／理賠追蹤及唯讀權限。正式切換前備份資料庫與程式，部署後核對Django／Nginx、映像與靜態資產雜湊、正式資料及開關指紋。


### 2026-10-22：Allianz Facility 限 Property 選用及會計適用範圍
- 依業主明確確認，本 Session 的專屬規則限 Class of Business 為 Property，且再保人為 Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)。非 Property 不能選用這個再保人，不改為套用一般規則後允許建案；一般 Allianz（無 Facility）及其他再保人沿用原規則。
- 案件再保人選單於非 Property 隱藏該精確名稱，歷史選項補入機制不會重新提供不符組合。已選 Allianz 後切換或清空 Class 時，阻擋變更並提示先移除 Allianz；保留 Class、已填再保人與金額等資料，不自動刪除整列。
- Draft 新增／編輯、Announce 完整性及 Word 文件授權均檢查伺服器保存或收到的 Class／再保人組合；無法以直接 API、舊有 Draft、偽造文件請求或付款天數補填繞過限制。錯誤保留英文，拒絕操作不變更案件版本、會計及歷史。
- Allianz 原單／續保、分期、加退費排程、固定天數、付款放行及理賠專屬標記統一檢查 Property；理賠依已凍結的分攤來源 Class 判斷，沒有來源 Class 則沿用案件 Class。不能只靠舊有 Allianz 標記套用到非 Property。
- 本次只限縮適用範圍及選用組合，Property 的現行月底＋80日提醒／＋90日到期、整期 Cedant 實收及人工銷帳放行、付款完成及理賠提醒規則不變；先前 2026-10-20「四類會計統一」的確認仍有效。未加入手動延期功能。
- 部署前唯讀盤點正式 Allianz 案件為0筆；不批次改寫舊案、交易、收付款、銷帳或 MDM，無 schema migration。保留其他 Session 的主檔、QBE、文件及會計更新，以及 Audit／寄信開關。
- 驗證：Property 適用範圍及 API 原子性專項、相關隔離案件／工作流程／文件／會計回歸；實際桌面與手機選單、阻擋 Class 切換並保留資料、移除再保人後可切換、既有草稿重開。另核對前後端適用範圍、3000組合計、密碼及非目標會計結果一致；備份後切換，核對正式映像、實際靜態資產、Django／Nginx及資料指紋。


### 2026-10-22：五家 Facility 的 Case 可選險種限制
- 依業主確認，Lloyd's 0609 AUW、Allianz Hong Kong、Great American Singapore、QBE Hongkong & Shanghai 的指定 Facility 精確名稱僅可選 Property；Swiss Re Asia Hong Kong 的指定 Facility 僅可選 Property 或 Commercial General Liability。
- 前端選單、歷史選項補入及險種切換採一致限制。含不相容 Facility 時阻擋切換或清空 Class，提示先移除對應再保人，保留已填 Class、再保人與金額；舊不相容案件仍可檢視及移除／替換再保人修正。
- 後端新增／編輯、Announce、續保／批單建立、Word 文件授權及付款天數補填都檢查保存或收到的險種／Facility 組合；拒絕操作不改案件、版本、會計或歷史。大小寫與名稱空白正規化，非指定名稱及不含 Facility 的一般再保人維持原規則。
- 本次只修改 Case 選用範圍，不改變會計、付款、信評或既有 Property 原單規則，不批次改寫歷史案件，無 schema migration。正式盤點五家現有案件均為0。
- 驗證：隔離資料庫 API 專項、相關案件／工作流程／文件／會計及最新 Property 回歸、前後端範圍一致性、桌面／手機選單與切換阻擋、重開及歷史案件修正。部署前備份、核對最新正式版本，部署後核對資料指紋、實際映像與靜態資產、Django／Nginx；保留 Audit／寄信原開關。


# 會計 A–G 統一規則（2026-10-22）

依本 session 最後逐項確認內容實作。適用一般再保人、AUW 0609、Allianz HK、Great American Singapore、QBE HK & Shanghai、Swiss Re Asia HK。案件的 Facility／Class 選用限制沿用其他 session 已部署設定。

## A．建帳與銷帳

- Announce 時立即建立保費帳款；分期一次建立全部期別。
- 每案每期一筆 Cedant T1、每家再保人一筆 T2，以及一筆 T3。
- 會計人工登錄實際收付資料；全額後自動 Settled 並鎖定。零金額自動完成，不建立虛構收付款。
- 同期 T1 及全部 T2 完成後，T3 自動完成；T3＝0 也自動完成。
- Production 只確認業績與認列月份，不重複建帳。零業績仍保留會計帳款。
- 已銷帳不可取消、不可修改收付金額。Reverse 不得移除已有保費收付、抵銷或最終確認的帳款；既有賠款獨立保留。

## B．原單、續保與分期日期

B：單期保單生效日；分期各期 Payment Base Date。C：各期 Cedant 天數；R：各期各家一般再保人天數。日數採日曆天。

| 類別 | Cedant 到期日 | Cedant 畫面提醒 | 再保人到期日 | 再保人畫面提醒 |
|---|---|---|---|---|
| 一般 | B＋C | 到期前 15 天 | B＋R | 到期前 10 天 |
| AUW | B＋90 | B＋75 | B 所在月底＋120 | 月底＋110 |
| Allianz | B＋90 | B＋75 | B 所在月底＋90 | 月底＋80 |
| Great American | B＋90 | B＋75 | B 所在曆年季末＋90 | 季末＋80 |
| QBE | B＋90 | B＋75 | B 所在承保年度季末＋90 | 承保年度季末＋80 |
| Swiss | B＋90 | **B＋80** | 固定結算期 | 固定結算日 |

Facility Cedant 天數固定 90；一般案每期獨立填寫 C／R，未填列待確認並禁止收付。可填天數維持至少 15 天的整數。

QBE 承保年度由 8 月起算：8–10 月、11–翌年 1 月、2–4 月、5–7 月。

## C．付款前提與 Swiss 歸期

- 所有類別付再保人保費前，須收齊該期全部 Cedant 款（含其他再保人分攤）並自動銷帳。
- 保費不得分次登錄，須一次登錄整筆剩餘額；完成後停止逾期。
- Swiss 固定結算日為每年 2/14、5/14、8/14、11/14。
- 日期歸期：11–翌年 1 月→2/14；2–4 月→5/14；5–7 月→8/14；8–10 月→11/14。
- 原始期依 Cedant **B＋90** 歸期；比較原始期、最後有效收款日歸期及財務確認日歸期，取最晚一期。未收妥先顯示預計期。
- 財務確認日為 Cedant 自動銷帳的實際操作台灣日期，不允許回填；會計填寫的收款日期另存。
- Cedant 全部銷帳後填寫結算清單參考號；未填不得登錄 Swiss 已付款。

## D．補保費與退保費批單

L＝批單生效日與實際 Announce 台灣日期較晚者。補／退保費批單均單期。

| 類別 | 補保費 Cedant 收款／退給 Cedant | 補保費付再保人／向再保人收退款 |
|---|---|---|
| 一般 | L＋C | L＋R |
| AUW | L＋90 | L 所在月底＋120 |
| Allianz | L＋90 | L 所在月底＋90 |
| Great American | L＋90 | L 所在曆年季末＋90 |
| QBE | L＋90 | L 所在承保年度季末＋90 |
| Swiss | L＋90 | 固定結算期；退保費依既有 Announce 截止規則可提前一期 |

畫面提醒：Cedant 到期前 15 天，Swiss 單獨採 **L＋80**；再保人到期前 10 天，Swiss 顯示固定結算日。超過實際到期日才逾期。

**所有類別**均須全額實收所有再保人退款並完成自動銷帳，才能一次全額退清該批單 Cedant。可提前退，不必等待月底／季結算日。原保費與退保費在 Cedant、再保人兩端均禁止抵銷，分別全額登錄收付；舊抵銷歷史保留。

## E．人工收付登錄

- Finance Staff、Finance Manager、System Administrator 操作；案件編輯角色不因此取得財務權限。
- 登錄時「對帳參考號」或「說明」至少一項必填。
- 可補登過往收付日期，系統另存實際操作時間；不允許負值、超額或零金額收付。
- 金額僅在未曾銷帳且未破壞收付先後條件時可填原因修改，保留修改前後歷史。
- 同筆登錄限同案、同期或同一筆賠款請款；同幣別、同方向、同對象限制維持。Accounting 批次操作畫面另在專屬 session 討論。
- 本系統僅供人工記錄收付及對帳，未接銀行或外部會計系統；銀行手續費由外部會計系統處理。

## F．賠款

- Claim Payment 建立時立即建立再保人應收及 Cedant 應付；準備金只追蹤、不建帳。
- 比例依出險當天適用保單／批單；同一請款的累計付出不得超過累計已登錄收款。
- 可分次收付；部分收付不改原到期日。全額後比照保費自動 Settled 並鎖定。
- 一般、AUW、Allianz、Great American、QBE：以建立賠款帳款的台灣日期＋15 天到期，固定不可人工修改。
- Swiss：依建立賠款帳款的台灣日期歸入固定結算期，同筆向 Swiss 收款與付 Cedant 採同一到期日。例如 10/15→11/14；11/2→翌年 2/14。
- 各類均採一般帳款提醒；原 Allianz／Great American／QBE 專屬追蹤歷史保留顯示。
- 完全未有收付、抵銷或銷帳時，可依權限填原因更正應賠金額；已有紀錄另走調整流程。

## G．金額、匯率與提醒信

- T1：先加總再保比例，再計算 Cedant 分出保費，扣 Cedant 佣金及稅。T2：各再保人獨立計算。T3＝同期 T1－全部 T2。
- 保費 TWD 整數、外幣兩位；受保護歷史帳款保留原算法與精度。賠款與收付款均以兩位小數處理。
- 分期尾差集中第一期；再保人分配尾差優先最大正分攤比例，同比例依案件順序。
- 有案件編輯權限者可填原因更正未處理帳款並保留歷史；已完成 T1 不變時，可只更正未處理 T2 並重算 T3。Production 已認列事實與正式報表保持鎖定。
- 保費未 Production 認列時，以最新儲存的月匯率暫估台幣金額並標示 Estimated；認列後固定各期實際認列月份及正式匯率。賠款採建立帳款月份正式匯率。
- 缺匯率不阻擋原幣建帳、人工收付或自動銷帳；顯示 Awaiting FX，Dashboard 標示換算尚未完整。
- 全六類保費、退保費及賠款都納入提醒信：實際到期前 7 天、到期當天，之後每隔 7 天追蹤至餘額歸零。同日同類提醒避免重複。
- 收件人：案件 AE、AE 主管及所有啟用中的 Finance Staff。先寄有效 Email，缺漏聯絡資料在系統列出。
- **SMTP 依使用者指示最後處理。此次保持正式寄送關閉；提醒規則使用隔離資料與模擬寄送驗證。**

## 部署與驗證原則

以部署當下 VM 原始碼與映像為基底，保留其他 session 變更。部署前備份程式與資料庫；本次不需 schema migration。正式 VM 若沒有案件，不虛構補建或修改歷史業務資料。


### 2026-10-23：一般 CGL QS 欄位規則與草稿自動儲存

依本 session 逐項確認及最後修訂整批實作。一般 CGL QS 適用本次欄位規則；Facility 專屬規則另行處理，XOL 不套用新增的 QS 欄位限制。已部署的會計 A–G 為本次基底，算法、收付、銷帳及 Production 規則沿用。

- CGL QS Case 幣別只提供 TWD／USD，新案預設 USD；New／Renew 預設 New，Type 預設 Commercial General Liability。保留 Products Liability 選項與既有結構後綴、as original。
- 一般再保人搭配 PWS Foreign RI Broker 仍使用一般 CGL QS Information，不再因 Broker 名稱切回 Property 欄位。XOL 舊有適用範圍保留。
- CGL QS 的 Aggregate Limit 在輸入、Overview、Review、Cover Note 隱藏，既有儲存值保留。Basis of Valuation、Indemnity Period、Loss Payee 等既有 CGL 文件隱藏規則沿用。
- Principal Address 至少一筆，每筆地址必填；Postcode 選填，有填時為 3–6 位數字。Expiration Date 必須晚於 Effective Date，不接受同日；時間選項與實際輸出沿用。
- Limit of Indemnity 必填且大於 0。每家 Order Hereon 0–100%，合計不超過 100%。Original／Renewal 的 Case／RI／分期保費大於 0；批改沿用既有補／退保費規則。
- 新增一般再保人的付款天數預設 90，可修改；有填／正式檢查時須為至少 15 天的整數。
- 第一個分期的 Payment Base Date／Performance Month 預帶 Effective Date／月份，其後人工選擇。各期預帶 Case Cedant 天數與各再保人天數，允許逐期修改；每期保費合計等於 100% Premium。
- Performance Split 預設關閉；啟用後一位 Reinsurance Staff、一位 Other Staff，預設 40%／60%，僅允許 40%／60% 或 70%／30%，比例連動。

**最後修訂的必填時點以 PD 現行做法為準，取代先前不同選項：**

- Review／Announce 要求 Original Insured (CN)、Reinsured’s Retention、Cedant Commission／Tax／Collection Days，以及一般再保人 Payment Terms Days；分期逐期檢查天數。佣金與稅允許 0%。
- Original Exclusions 改為選填。Case Owner 於 Announce 必填，Review 不另阻擋。AE Email 只在產生文件前要求。
- 文件端沿用既有 PD 檢查；另補齊 CGL QS 分期 Debit Note 的後端 Cedant Collection Days 檢查，使畫面與伺服器一致。
- Policy Form、Claims-Made Retroactive Date／ERP 適用與期間、Territorial／Other、Business、Products、Estimated Turnover、Special Agreement 等既有 Information 正式檢查保留。
- Loss Record：New 可為 0 年且不得有明細；Renew 至少 1 年。新增明細時日期、原因、Loss Amount 皆必填，CGL QS Loss Amount 大於 0。
- Sub-Limits、Self-Insured Retention、Reinstatement Provisions、Notices、Express Warranties、Conditions Precedent、Subjectivities、Website、補充 Loss Notes 等選填；空白的文件輸出沿用已確認規則。Website 不驗證網址。
- Annual 預設勾選，可取消。三項 CGL 範本條款人工選用、預設不勾選；人工條款加入清單時 Code／Name 均必填。

**CGL QS 與一般 Property QS 共用的草稿規則（使用者明確要求一致）：**

- Structure／Class 都選定後才啟動；系統預填本身不觸發自動建案。人工填寫、選擇或修改後，離開欄位自動儲存，保留填寫頁面。
- 缺漏、錯誤格式、未完成數字／日期及尚未加入清單的條款文字都可保留。有效數字於離開欄位時轉成數值；錯誤輸入仍保留原文。
- 原始輸入以受限制的 draftInput／pendingClause 保存，供重新開啟／重新整理還原；可計算欄位與日期欄位另用安全的正規化值。
- Review／Announce 及文件仍執行所需檢查。Announce 重新驗證原始輸入，成功後移除草稿輸入資料；Announce 前不建立會計帳款。帶有草稿原始輸入的修正案即使保留舊 TW Ref.，也須重新 Announce 後才能產生文件。
- 新案首次儲存使用可重試識別，避免遺失回應後重複建案；寫入依序送出並使用 rowVersion，發生錯誤保留編輯內容。
- 已有草稿暫時清空 Class／Structure 可繼續保存；XOL 不能藉清空 Structure 進入 QS 自動儲存。已公告／已確認／Reversed 案件不啟用自動儲存。
- 前後端繼續保護帳款、收付款、Claims、Production 與歷史算法旗標；草稿儲存不接受前端覆寫這些資料。

本次無 schema migration，不批次改寫業務資料。USD／TWD 使用既有對應的 Debit Note 收款帳戶；其他險種的銀行幣別限制保持原規格。

驗證使用本次獨立 MySQL、後端及瀏覽器環境；正式資料僅唯讀核對。舊 Case API 的付款鎖定／Reverse 測例明確使用保留舊流程的 Facility 夾具，一般案件的新會計行為由 accounting_ag 與 cgl_qs 覆蓋。


# Per-reinsurer premium ledger and insured master — 2026-10-24

Owner-approved changes superseding the aggregate T1/T3 portion of the 2026-10-22 A–G rules. All other accounting deadlines, claims, permissions, FX and reminder rules remain in force. SMTP remains deferred; real outbound email remains disabled.

## Premium ledgers

- Each case / installment / strictly positive-share reinsurer has independent T1, T2 and T3 transactions. Zero-share reinsurers do not create accounts.
- Calculate the whole Cedant T1 first, allocate it by positive reinsurer shares (largest share absorbs remainder; ties use case order), then split each reinsurer T1 into installments (first installment absorbs that reinsurer's tail). T1=1,000 at 33.33/33.33/33.34 becomes 333/333/334; two 50% periods total 499/501.
- T2 retains independent reinsurer calculations. Each reinsurer T3 equals its own T1 minus its own T2.
- Every T1 in the installment must be fully received and automatically settled before any T2 payment. Swiss statement-reference requirements remain.
- Each T3 automatically settles after its own T1 and T2 settle, including T3=0. No cash record is fabricated. Once any T3 settles, all T2/T3 amounts in that installment are locked; remaining T2 can still be paid at their original amounts.
- A single actual Cedant receipt registration may select several independent T1 of the same case / period. Existing currency / direction / counterparty and complete-refund safeguards remain.
- New cases and entirely untreated historical premium cases use the new layout. Any premium cash (including reversed entries), offsets, settlement, or Production recognition protects the original ledger and history. Conversion retains explicit before/after history and never registers cash. Formal Production reports are not rewritten.
- Debit Note installment amounts follow the same per-reinsurer-first allocation (499/501 in the example). Protected historical document calculations remain unchanged.
- Accounting and the case SoA display the actual reinsurer allocation on all three legs, separately from a foreign broker used as the cash counterparty. Case SoA displays the same stored transactions. Existing claim ledger and partial cash rules are unchanged.

## Insured master

- New fixed original-insured identities use Chinese names as the primary identity/display/search field; there is no group hierarchy. Same Chinese name reuses the master even if English names differ.
- Drafts may omit Chinese name. Chinese name is mandatory before Announce; newly linked cases must have a master. Existing cases are not backfilled.
- New original cases, renewals and endorsements link to the directory. A renewal/endorsement inherits its source master where present; an unlinked historical source remains unchanged.
- Saving a changed Chinese name on a linked original, renewal or endorsement renames that same master. It changes that case's name only; other case names and English names remain snapshots. Saving an unchanged old snapshot must not rename the master back.
- Reinsurance Staff, General Manager and System Administrator can create/rename. Finance is read-only. Case visibility follows existing permissions.
- A proposed name matching a separate existing identity requires explicit human confirmation of a merge; without confirmation the case/master remains unchanged. The confirmation includes both current versions; stale confirmation does not merge changed identities. Merge retains both identities' histories and old names; old fixed links resolve to the survivor.
- Finance case links use stored case data without requiring MDM read access; this does not grant MDM or case editing permissions.
- Master name/merge history is persisted in the master even while the general Audit Log is paused. No financial records or policy/renewal references are changed by master renaming.

## User entry points

- Sidebar **Insured Master** (`/insured`): search Chinese current/former names; open identity to see linked policies, renewal/endorsement references, historical case names, and name/merge history. Authorized staff can create/rename here.
- Account List → case → Overview → **Insured master**: direct link to the same identity. Case entry retains **Original Insured (CN)** as the input; normal save/CGL auto-save handles linking and rename confirmation.
- Sidebar **Accounting** (`/accounting`): per-reinsurer T1/T2/T3, independent balances and settlement; select several same-period T1 for one receipt. Account List → case → SoA shows its stored rows.

Implementation uses a nullable Case → insured MasterRecord FK and additive insured entity type migrations. No historical insured names are batch-linked. Prepared against live CGL QS release on 2026-10-23; source/image guards prevent overwriting concurrent releases.


# Swiss Re CGL Facility QS 規則與財務提醒日期 — 2026-10-24

本次依業主重新逐項確認的規則及最新部署衝突題 1A／2A／3B 實作。以 2026-10-24 20:29 的按再保人拆帳及被保險人主檔版本為基底；原先「先不要實作」已由業主「開始實作」明確解除。

- 專屬範圍須同時符合 QS、Commercial General Liability、Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility) 精確名稱（允許大小寫及多餘空白正規化）。不靠 Class Code 判斷；Swiss Property、CGL XOL、其他再保人的專屬期限維持原規則。
- 採最新一般 CGL QS 表單、CGL Information、Coverages、可選條款與正式檢查。Case 幣別僅 TWD／USD，新案預設 USD；Type 提供 Commercial General Liability（預設）及 Products Liability。Aggregate Limit 隱藏並保留舊值，佣金／稅允許 0；Case Owner 於 Announce 必填，AE Email 於產生文件前必填。
- 原單／續保 Draft 的人工修改於離開欄位後自動儲存，保留未完成或錯誤原文及待加入條款；Review／Announce 正式驗證。Announced、Confirmed、Reversed 不啟用 Draft 自動儲存，帳款與收付由伺服器保護。保留新部署的中文被保險人主檔連結、更名與人工合併確認。

| 帳款 | 基準 | 實際到期日 | Accounting 首次提醒 |
|---|---|---|---|
| 原單／續保 T1 | 保單生效日 | 基準日＋90 日 | 到期前15日 |
| 原單／續保 Swiss T2 | 保單生效日所在月份 | 該月底＋90 日 | 到期前10日 |
| 分期 T1／Swiss T2 | 各期 Payment Base Date | 分別沿用上述 T1／T2 公式 | 分別提前15／10日 |
| 加費／退費批單 T1／Swiss T2 | 批單生效日與成功 Announce 的台灣日期較晚者 | T1＝基準日＋90；Swiss T2＝該月底＋90 | 分別提前15／10日 |
| Swiss CGL 理賠應收／應付 | 該次賠款帳款實際成功建立的台灣日期 | 建帳日＋15日 | 到期前7日 |

- 全部為日曆天，週末／假日不順延。遲收 Cedant 款、部分理賠收付及補登實際收付日期都不重算期限；不使用舊 Swiss 季結歸期或退款提前一季規則。
- Announce 立即建立全部期別保費帳款；每案／每期／每家正分攤再保人有獨立 T1、T2、T3。T1 先按再保人分配再分期、尾差及 Debit Note 沿用最新部署；零分攤不建帳。Production 僅認列，不重複建帳。
- 正常保費各筆 T1 可分開全額登錄，也可同案同期多筆合併一筆匯款；每筆 T1／T2 都不允許部分金額。同期所有 T1（包括其他再保人分攤）全額實收並自動銷帳後，才可支付再保人。付 Swiss 正保費前另須填結算清單參考號，與 Cedant Statement No.／Reinsurer Ref. 分開。
- 退保費 Swiss T2 須一次全額收回。同批單所有再保人的退款本金全額實收並自動銷帳後，才可將全部 Cedant T1 勾選於同筆匯款一次全額退清；允許提前退，原期限保留。兩端均不允許保費／退保費抵銷。
- 理賠兩端可分次收付；同一請款累計付出不超過實收。全額後自動銷帳及鎖定，不另人工確認。
- 各家 T3 於自己的 T1／T2 都完成後自動銷帳（包含 T3＝0，不虛構現金紀錄）；任一家 T3 完成即鎖定同期全部 T2／T3 金額，其他 T2 仍可依原額付款。
- 新建及既有未結清帳款採新日期。已銷帳帳款保留原日期及紀錄，Accounting 的排程顯示與交易日期一致；既有收付歷史及受保護歷史帳本格式不改寫。

**全系統財務提醒信日期對齊 Accounting：** 所有保費、退保費及理賠的首次信依各筆 Accounting 提醒日，不再一律提前7日；各類本身的畫面日期及合約期限不變。之後仍於實際到期日及逾期每7日提醒，個別餘額歸零停止。同日同類去重、既有成功／暫停紀錄、收件人及寄信開關保留。沿用既有首封提醒識別保存歷史相容性，顯示名稱改為「會計收付款提醒」。

本次不啟用 SMTP 或實際提醒信，Audit Log 原暫停設定保留。不需 schema migration，不新增正式測試案件或虛構收付。以獨立資料庫及瀏覽器驗證；正式部署前備份、核對原始碼與映像，部署後核對執行版本、靜態資產、資料指紋與開關。

### 2026-10-27：QS Word 文件生成與版本保存

依本輪文件逐項確認及 10/27 佣金／Tax 更正實作。以 10/24 21:28 正式版本為基準；282 份後端 Python、Word 靜態檔及重新建置的前端 bundle 已核對與線上一致。Git HEAD 較舊，不能作為回復或覆蓋基底。

- 本批一般 Property／PD QS 原保單及續保 Cover Note／Debit Note：收件人地址合理分行、空白 Retention 固定句、QS 隱藏 Underlying Limits、付款條件逐期取值及空白限定回退、賠款正值檢查及日期排序、Security 比例降冪、Debit 標題 100% PREMIUM。兩份文件的佣金／Tax 未填或明確為 0 隱藏整列；非零比例固定兩位小數。
- 本批 QS 的 Original Exclusions／Conditions 使用編號條目、僅附加一次不編號固定句，包含已確認的其他險種；XOL 仍暫緩。合約聲明僅更正 alterations 拼字。
- 文件資料問題一次列出欄位及期別／明細。Debit 整份既有 Net Due 為 0 阻擋；個別分期 T1 為 0 照實保留。金額與日期沿用現行引擎，不修改 Case 儲存、Review／Announce 或任何會計規則及業務資料。
- 同一份 QS Word 先成功存入 Case Documents 才下載。UUID＋Case rowVersion 檢查支援失敗／回應遺失重試，防止重複版本。生成檔不列為 placement evidence；原附件、簽署判定、提醒及權限保留。
- Documents 主清單只列每類自動生成文件最新版，舊版留歷史並可下載。手動附件最多 50 份；自動生成 QS Word 與全部歷史另計，不占 50 份額度（業主 10/27 選 A）。檔名為 CoverNote／DebitNote_[Ref]_[Original Insured]_[台灣生成日期].docx。
- Migration cases.0007 僅放寬文件種類的既有 CHECK／choices，不改 Case 或會計資料。部署仍須先備份 DB 與文件 volume、以 owner 套用 migration 並執行 db_harden。Audit 暫停、郵件設定及 Word-only 流程維持。
- 文件專項：後端 60 項、Word 46 項、瀏覽器 18 項及 240 組共用金額驗證通過；Django／migration 檢查通過。XOL／Treaty Word XML 與批單本文回歸比對不變。LibreOffice 內部預覽確認 A4／字體／銀行 9pt／無空白頁；未代稱原生 Microsoft Word 驗證。
- 完整舊測試 78 組中 49 通過、29 失敗；29 組皆以未修改正式映像重跑同樣失敗。舊 totals 隨機向量工具也在修改前後同樣對 malformed reinsurers 失敗；密碼規則 20 組通過。舊 UI A 在原版／候選版同為 14/18，涉及新增 Insured Master 導覽及既有新增案件表單問題。業主已明確選 A：「同意既有測試失敗另案處理，本次部署文件修改」。本次以文件專項驗證及修改前後回歸比對部署；既有 Case／會計問題另案紀錄，未在此修改。本次例外不構成之後部署的通用豁免。


### 2026-10-27：Swiss Re Facility CGL 僅限 QS，禁止 XOL

依業主「Swiss Re Facility - CGL 不可以有 XOL」補齊選用限制。以當天 11:20 最新 QS Word 文件及版本保存部署為基底，保留既有文件、被保險人主檔與會計規則。

- Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility) 搭配 Commercial General Liability 時，Reinsurance Structure 僅能為 QS；XOL、Treaty 及其他非 QS 結構均不允許。名稱與 Class 的大小寫／多餘空白正規化，不依 Class Code 判斷。
- 已選 Swiss CGL 時，Structure 只提供 Quota Share，不能清空或切成 XOL；先選 XOL 的 CGL 案件不提供這家 Facility。切換 Class 若造成無效組合，保留原填寫資料並阻擋切換；移除該 Facility 後可按其他案件原規則操作。
- 後端共用選用驗證涵蓋新增／修改、草稿自動儲存、Review／Announce、續保／批單繼承、文件授權及付款天數補填。未完成草稿仍可保留一般欄位錯誤，但不能清除本項 Structure 限制。拒絕操作不修改案件、版本及歷史。
- 歷史無效草稿保留檢視與修正入口，可改為 QS；不自動刪除再保人或已填內容，不批次改寫歷史。正式唯讀盤點沒有 Swiss CGL XOL 案件。
- Swiss CGL QS 仍使用月底＋90／T1＋90、15／10日提醒、各家獨立 T1／T2／T3及先收齊整期再付款等已確認規則。Swiss Property、一般 CGL 的 XOL 選用範圍維持原規則。
- 舊盤點中的 Swiss CGL XOL 純計算夾具屬先前未阻擋的組合，不能作為業主已核准 XOL 的依據；規則盤點須先檢查共用選用限制，再列可用會計規則。

本次無 schema migration，不變更會計資料、實際收付或文件內容。部署前備份並核對最新原始碼／映像；部署後核對資料指紋與實際版本，Audit 暫停及實際寄信關閉保持原設定。

### 2026-10-27：Debug 候選修正版（待業主決定部署）

本節記錄本次已獲業主確認的修正範圍；目前只交付候選原始碼與隔離測試結果，未部署正式服務。

- 新增／取消／重設及載入 Case 草稿時，先提供完整欄位，保護同步付款條件 watcher，不在逐欄刪除造成的短暫空值上呼叫 `map`。既有 Draft 自動儲存及未完成輸入保留流程維持。
- 再保人清單、分期清單或計算所需數字出現無法讀取的格式時，整案金額顯示 `Pending confirmation` 並列出資料異常。讀取不修補、不以 0 代替錯誤數字，也不捨棄原始資料。
- 付款天數、日期與一般必填欄位繼續使用既有逐欄正式檢查；這些欄位尚未完成或錯誤時，不把仍可計算的金額改為資料損壞。
- 該案在修正前，由後端阻擋相關 Announce、文件產生、收付款、沖回、更正、續保／批單／Reverse 工作流程及理賠正式操作；Reverse 案件合法理賠更正的例外不能繞過此防護。合法案件繼續正常讀取。Dashboard／Production 明示異常案件未計入的金額，已關帳報表不回寫。
- 為避免正常編輯器靜默捨棄損壞的資料結構，異常儲存資料先保留檢視；須查明原文後由技術人員修復。一般尚未填完的空白 Draft 不視為資料格式損壞。
- Great American／QBE（及共用固定 Cedant 政策）的付款條件比對統一採固定 90 天，包含各期 Cedant。真正的 Payment Base Date 及一般可變天數差異仍檢查；不批次回寫歷史紀錄。
- Swiss Property 初始日期依既有 Cedant B+90 歸結算期：2026/1/31+90=2026/5/1，原始結算期為 2026/8/14。舊 5/14 測試預期已更新，測試凍結完整時鐘；不改動 Swiss 業務公式。Swiss CGL 仍依既有月底+90及 QS-only 選用規則。
- 原 29 組失敗測試依現行規則更新，保留錯誤輸入、權限、併發／原子性及歷史帳款檢查。退休的人工銷帳、跨案合併登錄、保費抵銷及固定提前 7 天首封提醒，改為驗證目前的自動銷帳、同案同期／請款限制與 Accounting 提醒日。
- 本次驗證僅用獨立合成資料環境；不需 schema migration。完整紀錄與候選差異交付於工作區 `RI-docs/Debug-Fixes-2026-10-27/`。部署由業主另行決定，部署前須重新核對正式版本並備份。


### 2026-10-27：Debug 修正版正式部署

業主於本 session 明確指示「都修好了，那開始部署」，解除上一筆候選版本的待部署狀態。

- 發布已驗證的兩項錯誤修正、固定90天比對及現行測試整理；金額異常資料保留原文並阻擋相關正式操作，付款天數與一般必填檢查沿用既有流程。
- 79／79組隔離測試、3017筆金額一致性、14項瀏覽器及31項前端正式檢查通過；Release僅同步QA檔案，所有應用程式Python與已測映像完全相同。
- 無schema migration，無正式測試案件或業務資料改寫。備份程式、資料庫及文件後切換；正式API唯讀、Django／Nginx與映像／靜態資產驗證通過，managed tables（Session除外）、文件及Audit／寄信開關指紋不變。
- 備份：`/opt/ri-system/backups/debug_fixes_20261027_232757`；完整部署證據：工作區`RI-docs/Debug-Fixes-2026-10-27/`。


### 2026-10-27：本週公告與完整 MDM／Schema 指南更新
- 公告比較期間為2026-10-21 09:11至本次唯讀核對時間；英文信僅說明General Manager、Reinsurance Staff、Finance Manager、Finance Staff可見的操作變更，不包含System Reference Data。
- 兩份完整指南重整為現行規則：Announce即建帳、依再保人獨立T1/T2/T3與自動銷帳、Insured Master中文身分／更名／明確合併、各Facility期限與Swiss CGL QS限制、草稿raw input、自動保存Property QS Word版本、30MiB案件附件、信評新欄位與資料異常保護。
- information_schema逐欄核對28表、274欄、81索引、21外鍵、38 CHECK、5 trigger、42 migration；文件內容、XML連結、離線排版及隔離／正式權限與下載SHA-256驗證通過。
- 只更新兩份指南及其預設發行日期為2026-10-27；其他指南／模板、應用程式功能及業務資料不變，不套migration。原始碼、舊映像與metadata先備份；Audit暫停與寄信關閉保持。


### 2026-10-28：Endorsement 及全保期平均續保候選實作

依業主本 session 確認的 55 項決定實作，適用所有臨分險種的 QS／XOL。以 10/27 最新正式程式、文件版本保存、Swiss CGL QS-only、資料異常保護及 Debug 修正版為基底；289 份後端 Python 與執行中版本一致，前端基底可重建出相同正式 bundle。此為候選規格與程式，尚未部署正式服務。

- 第一張批單由 Original 建立，後續從最新已 Announce／Confirmed 版本繼承，連回同年度根保單；不得跳過未完成批單。保費差額、批改生效日、類型及 wording 由業務填寫，批改類型至少一項、可複選，wording 必填。成功 Announce 前不配置正式 E 編號。
- 幣別、險種、QS／XOL、Reinsured、再保人名單及 Order Hereon、Foreign RI Broker、Cedant 及再保人的佣金／Deductions／Tax／付款天數、Performance Split 全部沿用來源並固定。伺服器保存來源版本及固定欄位快照，API 不接受覆寫；既有一般未公告 Draft 也套用。來源 Performance Split 的歷史人員及名稱快照保留。AE／Case Owner 在 Draft 可修改，Original Insured 中英文及其他可批改風險資料須先解鎖。
- 修改保單起訖日期／時間須選 Period 並解鎖。一般批改生效日依最新已 Announce／Confirmed 的期間檢查，允許等於生效日及到期日；本項取代先前「必須早於到期日」。Period 可超出原期間，但後續批單生效日仍不得早於前一張，可同日。
- 所有臨分 Original、續保及 Period 改期後的完整期間最長 18 個曆月，允許剛好上限；月底按曆月末日處理，不以固定日數代替。多張延長以最新完整起訖期間判斷，不能逐張另算上限。原兩年期示例撤回。
- 批單單期、不允許分期。Case／再保人 Premium 為本次帶正負號的差額：補費正、退費負、無異動 0；同張不同再保人允許混合補退，包含 Swiss Property。只有 Case 及每家再保人金額全部為 0，才於成功 Announce 後直接 Confirmed 並排除 Production；相抵為零的非零明細仍須認列。
- 所有臨分批單 Draft 啟用離欄自動儲存及手動儲存，保留未完成數字、日期與條款原文，重新開啟還原；Review／Announce 正式檢查必填、格式、日期順序及 18 個月。資料結構損壞仍沿用最新異常資料防護，不靜默修補或以零替代。
- 批單上傳 Offer Slip 更名為 Endorsement。Announce 前需業務另備上傳的本批單 Endorsement，加涵蓋全部再保人的 Signed Slip 或 Confirmation E-mail；完全零保費亦適用。E-mail 先行仍須補 Signed Slip，含 Confirmed 零保費案件均沿用追蹤。正式 Endorsement Word 只於成功 Announce 後提供。
- 批單統一以 Original 編號衍生 -E01、E02…；雙系統／AUW 編號兩邊使用同一 E 序號，純 AUW 單基底只衍生 AUW 編號，不補建系統基底。AUW 批單 Draft 不手填新號碼；正式編號檢查全域保留、歷史及回收編號，成功 Announce 才配置。缺少歷史 AUW 原單基底時不以系統號冒充。Original／續保既有 AUW 手填規則維持。
- Announce 即建立各再保人應收應付，Production 僅認列、不重複建帳。收付期限基準為批改生效日與實際 Announce 台灣日期較晚者，各 Facility 再套既有公式。Production 月份同樣取較晚月份，已關帳則順延第一個未關帳月，正式匯率採實際認列月匯率。保留最新依再保人 T1／T2／T3、正分攤建帳、自動銷帳、退款本金、收齊再付款及 FX 鎖定規則。
- Announce／Confirmed 後依 Original 允許欄位與更正原因流程辦理，保留收付、銷帳及 Production 鎖定；固定來源欄位仍不可改。拒絕日期更正須在修改被保險人主檔及帳款前完成驗證。
- 所有臨分續保採全保期平均，即使沒有 Period 批單也適用：同年度 Original 加已完成批單的補／退費，除最新完整保障實際天數，再乘續保實際天數。Case 與每家再保人各自計算；沿用既有幣別取位，來源及已關帳金額不改寫。所有臨分續保均從最新到期日接續（包含無 Period 批單及原本非一年期），預帶一年期，實際 365／366 天，可改期但最長 18 個月。改期只重算未人工修改的保費，人工值及其狀態重開後保留。無法有效推算的欄位留白並說明原因，仍建立續保 Draft，正式送出須補齊。
- 歷史案件由上線時另一個分頁處理，本次不批次回寫歷史案件或提供一般 Draft 補填固定歷史缺漏的例外。最新 Facility 選用限制（含 Swiss CGL 只限 QS）、權限、被保險人主檔／合併確認、文件版本保存、Audit 暫停與正式寄信關閉維持。

驗證僅使用本次獨立 MySQL、後端及無頭瀏覽器，合成資料與隨機測試密鑰；與正式資料庫、文件 volume 及網路隔離。專項、全部現行測試、前後端金額及續保公式一致性、瀏覽器與 Django／migration 結果另存工作區 `RI-docs/Endorsement-Implementation-2026-10-28/`。不需 schema migration；正式部署仍須另行確認並重新檢查正式版本與備份。


### 2026-10-28：Endorsement 與全保期平均續保正式部署

業主已明確指示「都通過也都沒問題，那就開始部署吧」，解除上一段候選版本的待部署狀態。

- 發布本 session 已確認範圍的批單規則、固定來源欄位、Draft 原文與自動儲存、含到期日的生效日期界線、Period 解鎖、18 個曆月上限、混合補退與嚴格全零 Confirmed、AUW 自動 E 編號、公告文件要求及全保期平均續保。歷史缺漏資料依第 43 項另分頁確認，不在本次批次回寫。
- 80／80 組現行隔離回歸（含批單 54 項）、22 項瀏覽器、13 項新增前端規則、3017 組金額與2000組續保一致性及20組密碼一致性通過。正式使用已測試的同一後端／前端映像，292份Python與原始碼一致。
- 無 schema migration，無正式測試案件或業務資料改寫。程式、資料庫與案件文件已備份；正式API唯讀檢查、Django／Nginx及靜態資產驗證通過，所有可見資料表（Session除外）與文件、Audit暫停及寄信關閉保持原狀。
- 備份：`/opt/ri-system/backups/endorsement_20261028_151317`；完整證據：工作區 `RI-docs/Endorsement-Implementation-2026-10-28/`。


## 2026-10-28 Placing Slip / 新案 QS 規則（候選版，尚未部署）

- 規則版本 `placing-qs-20261028-v1` 由伺服器配置。更新後新增的 Property / CGL QS、從舊案建立的新續保與批單使用新版；編輯既有案不得自行升版。
- Placing Slip 僅 Draft 生成／上傳／刪除。未選再保人或含一般再保人可用；純 Facility 不提供。Announce 後只下載既有版本。
- 原單／續保依 Risk Details、Terms & Conditions、Information 檢核；AE 與 Email 必填，不要求先填保費或指定再保人。Offer Slip / Signed Slip 證明文件要求不變。
- Premium、Ceding Commission、Total Deductions、Tax、Order Hereon 保留空白列；Premium Payment Terms 每次固定 90 天；Annual 每次預設勾選。無再保人 Breakdown。
- 每次生成／上傳必填版本說明，生成 Word 先保存再下載。編輯版接受 DOCX / PDF；目前有任何未刪除的編輯版便停止生成，刪除全部編輯版後恢復。修改 Case 後提醒舊文件可能過時，不阻擋 Announce。
- 批單使用 Addendum Template：批改前 TYPE、REINSURED、ORIGINAL INSURED、PERIOD；原單編號與預估 E 編號。正式編號僅 Announce 配置，不標 Provisional。有效日期、批改類型、wording 必填。改期／名稱修改在批改內容另列。
- Addendum 保留 It is hereby noted and agreed that / All other terms and conditions remain unchanged.，列所有再保人（含混合案 Facility）與空白保費，不列 Share、Security Details、費用附頁及任何簽署區。
- 新填／修改的 Order Hereon 每家 >0、<=100%、最多 8 位小數，合計 <=100%；未修改歷史比例保留，批單繼承並鎖定來源比例。
- Property：地址列稱 SITUATION；至少一筆，每筆地址與 Postcode 必填。Basis of Valuation 必填（Other 說明必填）；Retention 可空，文件補標準文字。
- Property 新增 SIR 於 Deductibles 下；Loss Payee、Co-Reinsurance Warranty、Notices 依序於 Reinstatement Provisions 下。前三項純 Facility 隱藏；Notices 所有案件選填。Cover Note / Placing Slip 有內容才顯示。
- Property Aggregate Limit 0 當未填；Sub-Limits、Exclusions、Reinstatement、Indemnity Period、Special Agreement 選填；三項聲明空白補標準 None 文字，含 Facility。既有純 Facility 專屬財務規則保留。
- CGL / Swiss CGL QS：Principal Address 非必填；Limit of Indemnity 後顯示 each occurrence；Aggregate Limit 選填且 0 省略；Deductibles / SIR 都維持自由文字，至少填一組。Co-Reinsurance Warranty 選填並同步兩份文件。
- CGL Interest 預填且可改，空白使用標準文字；Retention、三項聲明空白使用標準文字。Claims-Made 才顯示且要求 Retroactive Date / ERP；其他 CGL Information 必填及條件顯示由共用規則檢核。
- Business 複選 Manufacturer / Distributor / Importer / Exporter / Other（說明）；Turnover Region 單選 USA/Canada / Rest of World / Other（說明）。新續保／批單繼承舊自由文字一律放 Other，保留原文，每區塊確認後才可 Review / Announce / Placing。
- CGL Overview 的 Adj. Rate = Cedant 100% Premium / Turnover 換成 Case 幣別後加總 *100%，使用保單生效月份匯率，六位小數，不年化。缺所需匯率或分母無效顯示 N/A，不阻擋其他操作。
- Upload Evidence 額外支援 .xlsx / .xls；原有文件權限、Announce 證明要求、Accounting / Production / 寄信規則保持原有規定。


### 2026-10-28T21:17:34+08:00：Placing Slip 正式部署

業主明確指示「先部署，再弄排版。」；本次候選版本已獲部署授權。

- 使用隔離驗證的同一後端／前端 image；新增 cases.0008_placing_slip_versions，重套既有最小權限與 Audit triggers。
- 既有案件、會計、證明文件及其他業務資料不批次改寫；新欄位／選項使用新版新案標記，舊案維持原畫面。Audit 暫停與寄信設定不變。
- 既有 80 組回歸的各組最新結果通過；候選 image 的 47 項 Placing、12 項 Word／比例、28 項瀏覽器及來源／資產一致性通過。Word 原生分頁依業主指示在部署後另外檢查。
- 備份：`/opt/ri-system/backups/placing_slip_20261028_211640`；部署及後續排版證據：工作區 `RI-docs/Placing-Slip-Implementation-2026-10-28/`。


### 2026-10-28T21:30:05+08:00：Placing Slip 文件顯示檢查

- 依「先部署，再弄排版」接續完成三份合成 Word 的離線 Writer 排版預覽：Property／CGL 各 8 頁、Addendum 1 頁，無空白頁或簽署頁切頁。此為 LibreOffice 預覽，並非 Microsoft Word 原生驗收。
- 修正條款標題已含代碼時的重複顯示，例如 LMA3333 LMA3333，保留最新 MDM 標題一次。零年且無損失的新案摘要與通知日期格式同步既有 Cover Note 的 Loss Clean since operation. 及英文長日期；沒有更動條款選用、承保、保費、會計或文件版本規則。49 項 Placing 專項與預覽驗證通過，部署同一修正 image。
- 無 migration；程式、資料庫與文件已備份，部署前後業務資料／文件／設定指紋一致。備份：`/opt/ri-system/backups/placing_layout_20261028_212934`。


### 2026-10-28：Property Construction 複選（本次候選規則）

- 適用所有可編輯的 Property QS／XOL 案件，一般再保人與 Facility 一致。歷史 FACULTATIVE 名稱沿用系統既有 QS 相容處理。其他險種維持自由文字。
- Construction 至少選一項，允許複選，固定選項及輸出順序：A2 Class、A1 Class、B Class、C Class、D Class，不提供 Other，不預設選項。
- 原 Construction 文字保留為 constructionLegacyText，未確認前 construction 仍維持原文。業務選好類別並明確確認後，construction 改為所選類別逐行列出；歷史原文持續保留，不批次改寫舊案。
- 新增、編輯、續保／批單繼承、Review／Announce 與新的 Cover Note／Placing Slip 使用共用選項及確認檢核。未完成仍可保存 Draft，不能產生新的文件；既有文件下載不受影響。
- 既有已確認選項可繼承。來源仍為舊文字時不猜測類別，保留原文供業務選擇與確認。API 不可藉由刪除版本標記、清空歷史原文或只選不確認來繞過檢核。
- 資料保留在 Case JSON，維持既有 construction 字串供 Overview／Review／Cover Note／Placing Slip 輸出，無 schema migration。新欄位屬描述資料，不改保費、會計、稅費、Share、承接或現金演算法。
- Property Construction 的新 metadata 只在相關資料實際存在時影響 Placing Slip 指紋，避免將未變更的舊 Property 或 CGL 文件誤標過時。


### 2026-10-29T09:15:05+08:00：Property Construction 正式部署

依本 session 已確認的所有可編輯 Property QS／XOL 複選、舊文字保留及新文件確認門檻發布。同一候選 image 的 API／瀏覽器／Word 檢核通過；無 schema migration，正式案件與會計／文件／開關指紋不變。備份：`/opt/ri-system/backups/property_construction_20261029_091425`。部署後接續檢查文件排版。


### 2026-10-29T09:29:38+08:00：Property Construction 文件分頁檢查

依「弄完之後，再弄排版」完成 QS／XOL Cover Note 與 Property Placing Slip 離線預覽。Cover Note 範本原先在單一表格儲存格內的換頁改為整列開始新表格，並保留欄位名稱及內容同頁，避免頁底文字接近頁碼。實際 Word 下載文字及非本文資產一致（生成日期正常更新），其餘前端檔案與後端 image 不變。這是 LibreOffice 離線預覽，未以 Microsoft Word 原生引擎人工驗收。QS／XOL Cover Note 各 5 頁、Placing Slip 8 頁，無空白頁及頁面外文字。備份：`/opt/ri-system/backups/construction_layout_20261029_092924`；資料／文件／設定指紋不變。


### 2026-10-29：更新Swiss Re Facility PD專屬規則指南
- 依執行中297份Python、現行Accounting及Swiss Facility主檔整理2026-10-29版Word；System Guides原swiss-pd入口更新，舊版隨備份保留。
- 僅說明Property專屬三項固定條款、80天提醒／90天歸季、固定14日與月底截止、自動銷帳操作日及收款日歸期、Swiss清單參考號、退費提前一期與Announce截止、理賠固定季結；不重列全險種共用規則。
- 此次只發布Word及其登錄檔名／發行日期，不修改業務邏輯；四頁排版、日期例子、隔離與正式下載權限及SHA-256通過。其他指南、模板、前端、業務資料、Audit暫停及寄信關閉保持原狀，無migration。
- 證據：工作區RI-docs/Swiss-Re-Facility-PD-2026-10-29/。


### 2026-10-29：新增Swiss Re Facility CGL專屬規則指南
- 參考System Guides的PD指南版式，依執行中297份Python、現行Accounting及Swiss Facility主檔整理CGL專屬Word，新增swiss-cgl入口；既有swiss-pd及其他指南保留。
- 僅說明QS限定、NMA2915與SWISSRE_GC_FAC、T1固定90天與提前15天提醒、Swiss T2月底加90天與提前10天提醒、晚收款不延期、Swiss結算參考號、批單基準日及無PD提前一期、理賠建帳台灣日期加15天及提前7天提醒；不重列全險種共用規則。
- 本次只發布Word及其登錄檔名／發行日期，不修改業務邏輯；三頁排版、33項記憶體規則檢查、16項下載權限檢查及SHA-256通過。其他指南、模板、前端、業務資料、Audit暫停及寄信關閉保持原狀，無migration。
- 證據：工作區RI-docs/Swiss-Re-Facility-CGL-2026-10-29/。


### 2026-10-29：更新 Great American Facility PD 專屬規則指南
- 依正式執行中後端、現行 Accounting 及 Great American Facility／Clause 主檔，整理最新 PD 專屬規則 Word；沿用 Swiss PD 指南格式，更新原 Great American 指南入口，舊問卷隨備份保留。
- 列示僅限 Property／QS 及 XOL、12項現行固定條款、Cedant固定90天及75天提醒、GA曆年季末＋80天提醒／＋90天到期、分期及批單歸季、台灣Announce日期、跨年閏年、原期限與不自動延期，以及兩端退款期限差異。排除全險種共用的理賠、收付登錄、自動銷帳、權限、金額、匯率及提醒信規則。
- 僅更新指南檔、下載登錄與既有指南驗證；不修改業務邏輯、前端、主檔或其他指南，無migration。三頁Word排版、日期案例、隔離及正式下載權限與SHA-256驗證通過；發布前後核對資料及設定指紋。
- 證據：工作區 RI-docs/Great-American-Facility-PD-2026-10-29/。


### 2026-10-29：新增QBE Facility PD專屬規則指南
- 依執行中297份Python、Accounting及QBE／Clause主檔整理三頁Word，參照Swiss Re Facility PD指南格式，新增System Guides的qbe-pd入口，顯示檔名QBE Facility - PD 專屬規則.docx。
- 僅整理Property適用範圍、12項現行固定條款、8月起承保年度季度、正保費與退保費季度末加80天提醒／90天到期、批單台灣Announce跨季、保險公司端與QBE日期區分及QBE畫面資訊；不重列全險種共用的建帳、收付、銷帳、理賠與權限規則。
- 本次只新增文件及指南登錄，不修改業務邏輯。56項記憶體日期與規則驗算、三頁離線排版、16項隔離及正式下載權限與SHA-256核對通過。其他指南／模板、前端、主檔與業務資料保留，Audit及寄信開關維持原狀，無migration。
- 證據：工作區RI-docs/QBE-Facility-PD-2026-10-29/。


### 2026-10-29：更新Allianz Facility PD專屬規則指南
- 依正式執行中程式、Accounting與Allianz Facility主檔整理2026-10-29版Word；參考Swiss Re Facility PD指南的原生Word版型，System Guides原allianz-questionnaire入口改為Allianz Facility - PD專屬規則，舊問卷備份保留。
- 三頁列出Property選用限制、19項固定條款（使用最新MDM Title原文）、再保人月底＋80提醒／＋90到期、保險公司固定90天的起算差異、原單／續保／各期／加退費歸月、四個日期例子、無手動延期與Accounting日期資訊。未重列全險種共用的建帳、收付、銷帳、權限及理賠流程。
- 僅發布Word、下載登錄與指南顯示名稱／日期；不改會計邏輯、MDM、Case、實際收付款或原有指南權限。原生XML、逐頁預覽、合成日期驗算、隔離與正式指南下載／權限及SHA-256通過；其他指南、模板、前端、業務資料及Audit／寄信開關保持原狀，無migration。
- 證據：工作區RI-docs/Allianz-Facility-PD-2026-10-29/。

### 2026-10-29：批單的 Debit Note（加費）與 Credit Note（退費）
- 先前「批單 Debit Note 內容與版面待後續討論」（10-15、10-20 兩處）今日由業主定案：
  - 金額：寫這張批單 Cedant 那邊的 Premium、Ceding Commission、Tax 與 Net（和 Accounting Leg 1 同一套計算）。
  - 加費（100% Premium > 0）出 **Debit Note**；退費（< 0）出 **Credit Note**；保費 0 不出。
  - 付款日：沿用原單的 Cedant Collection Days，從**批單生效日**起算。Debit Note 照原本寫法再提前 15 天（「至少到期前 15 天收到款項」）；Credit Note 直接寫生效日 + 天數（我方付款日）。分期批單仍用各期的 Payment Base Date。
  - 版面：沿用原本 Debit Note 版面；標題只寫 DEBIT NOTE／CREDIT NOTE（業主 10-29 改：標題下不寫 Endorsement No.），DETAILS 寫「Additional Premium – Endorsement No. N」／「Return Premium – Endorsement No. N」。
  - 頁尾（公司資訊與頁碼）用 8 pt，只限批單 Debit／Credit Note；Cover Note、原單 Debit Note、Endorsement 維持 10 pt。
  - Credit Note 採業主上傳的 Credit Note Template (NTD) 文字：寄給 Cedant、「Less CEDING COMMISSION」、「NET AMOUNT DUE TO YOU」、「We shall arrange the payment of premium on the following date(s):」；不列銀行帳戶；金額一律顯示正數；台幣不寫「Payment will be made in United States Dollar…」那句。
  - Credit Note 先只開放 TWD；其他幣別擋下並說明，待業主提供範本。Debit Note 維持 USD／TWD。
- 只在批單 Announce（或 Confirmed）後出現；草稿不顯示。只提供下載（與 Endorsement Word 相同），不自動存入 Case Documents。
- 伺服器端同步檢查（document-generation-log 新增 kind = credit）：未 Announce、方向不符、保費 0、Credit Note 非 TWD、缺批單生效日或 Cedant Collection Days 都回 409；其餘沿用 Debit Note 原有資料檢查。原單的 Debit Note 不變。
- 測試：backend/qa/suites/endorsement_notes.py；Word 內容檢查 frontend/scripts/check_endorsement_notes.cjs。


### 2026-10-29：更新 Syndicate 609 AUW Facility PD 專屬規則指南
- 依正式執行中程式、Accounting 與 AUW Facility／Clause 主檔，參照 Swiss Re Facility PD 原生 Word 格式，更新既有 auw-accounting 指南；顯示檔名 Syndicate 609 AUW Facility - PD 專屬規則.docx，舊版備份保留。
- 四頁僅整理 Property 選用、12項目前固定條款、Howden 綁定、Deductions 可改的10%預設、Tax 0%、原單／續保手填 Ref.、批單 Announce 自動 E 編號，以及月底＋110提醒／＋120到期、跨月批單／退費、閏年與台灣日期例子；省略全險種共用的建帳、收付、銷帳、權限、理賠及一般文件規則。
- 僅發布 Word、下載登錄及指南顯示名稱／日期，不修改業務邏輯、主檔、案件、帳款或原有權限。原生XML與Swiss版型比對、逐頁排版、合成例子驗算、隔離及正式下載／權限／SHA-256驗證通過；保留其他指南、模板、前端、業務資料及Audit／寄信設定，無migration。
- 證據：工作區 RI-docs/AUW-Facility-PD-2026-10-29/。


### 2026-10-29：Case 時間連動與表單 Review 內上傳／Announce（本次候選）

- 所有險種及 QS／XOL／Treaty 的使用者手動修改 Effective Date 時間（00:00／12:00）時，同步帶入 Expiration Date 時間。Expiration 仍可另行選擇；讀取、載入或繼承舊案不強制同步，不批次改寫舊期間。批單仍須選 Period 並解鎖才能修改期間。
- 表單最下方 Review & confirm 通過既有業務必填後，先保存目前 Draft 並取得伺服器的案件／版本；Review 視窗可直接上傳與選取 Offer Slip（批單顯示 Endorsement）、各再保人 Signed Slip 或 Confirmation E-mail，不需回 Overview。
- Review 內沿用既有 documents.read／documents.write／cases.announce 權限、檔案上傳 API、檔案驗證與每家再保人的證明涵蓋規則。證明未齊、正在上傳或未勾選確認時不能 Announce；上傳／修改選取後須重新確認。仍須由業務另按 Announce，不因開啟 Review 或上傳而自動公告。
- Announce 沿用現行伺服器 API 與 rowVersion、documentIds、明確確認、Reference／建帳／Production／提醒及完全零保費批單 Confirmed 規則；成功後重新讀取完整案件。版本衝突會清除確認；選擇重新載入時回到最新表單，須重新 Review 與確認，不以舊摘要搭配新版本公告。Announced／Confirmed 案件的原更正與儲存流程不變。
- Placing Slip 維持 Draft 詢價用途；不要求 Offer Slip／Signed Slip／Confirmation E-mail。原有 Cover Note／Debit／Credit／正式 Endorsement 的公告及編號條件維持。此處並未提前開放正式文件。
- 無 schema migration；不變更財務計算、條款、保費、Facility、指南、Audit 暫停或寄信設定。測試期間的 AUW 指南發布已納入最新基底；本次僅修改 Case 前端及本規則紀錄。


### 2026-10-29T14:59:54+08:00：Case 時間連動與 Review 內上傳正式部署

本 session 已要求的跨險種時間連動與 Review 證明上傳／直接 Announce 已發布。使用已驗證的相同前端 image；正式後端保留包含最新 AUW 指南的版本，不重建、不變更 schema。81 組隔離回歸、58 項瀏覽器主流程、最新後端、手機版與版本衝突檢查、3017 組金額、20 組密碼及24項批單 Word 檢查通過。Placing Slip 無附件可生成，正式文件公告／編號門檻不變。備份：`/opt/ri-system/backups/case_review_time_20261029_145939`。入口重新開放前，正式業務資料、文件與設定指紋一致；僅排除登入時間與 Session 活動。

### 2026-10-29：全系統檢查與修正（Case Viewer／Insured Master、Basis of Valuation 紅框、格式錯誤請求）
- 檢查範圍：82 組伺服器測試與 13 階段畫面測試（皆以線上版本）、前後端每家再保人算法隨機比對 13,000 件（含分期）、正式系統唯讀巡檢（6 種角色 × 全部讀取頁面，交易內撤銷、不印資料）、約 14 萬次異常輸入與越權探測（無權限漏洞）。
- 業主決定：**Case Viewer 不能看 Insured Master**（選單不顯示、直接開網址會被導回、API `GET /api/insured-masters` 改為需要 cases.read.all，Case Viewer 回 403；案件總覽仍顯示被保險人名稱但不是連結）。原本 Case Viewer 讀清單時伺服器出錯（500）。
- Property QS 的 Basis of Valuation（10-28 Placing Slip 規則起必填）漏填時，欄位比照其他必填欄位顯示紅框，Review & confirm 會捲到該欄位。
- `PUT /api/cases` 沒有 case 物件（或不是物件）時一律回 400 validation_failed「case must be an object.」；原本批單會出錯 500。
- 業主決定維持現狀：能編輯案件的人（業務、主管、管理員）都可以改被保險人主檔的中文名稱或合併，與「業務可看全部案件」一致。
- 測試：backend/qa/suites/review_fixes_1029.py；qa/ui/ui_test.py 階段 A（紅框）、C（Case Viewer 選單與直接開網址）。

### 2026-10-29：效能優化（每件案件記住答案、Dashboard 未結清 5 年內、跳過整件已銷帳）
- 壓力測試重測（1 萬件案件、23,907 筆帳款；10-28 起 Announce 即建帳，比 10-21 多約 3 成）：Accounting 27 秒、Dashboard 23 秒、Production 19 秒（未快取）。壓測造資料程式同步改為 Announce 即建帳。
- 純效能（輸出逐位元組相同）：再保人名稱整理只算一次、數字轉換少做重複工作。Accounting／Dashboard／Production 約快 10–30%。
- **每件案件記住答案**（cases/case_result_cache.py）：付款排程與交易明細只取決於案件資料內容與台北日期，用「資料內容指紋＋台北日期」記住結果；資料改任何一字或過台北午夜即重算，不依賴 row_version。每個 worker 最多 30,000 筆（1 萬件約 2.1 萬筆，每筆約 4.5 KB；4 個 worker 約多 210 MB），超過丟掉最久沒用的；`RI_CASE_RESULT_CACHE=false` 可關閉。Accounting 第二次打開 27→約 13 秒、Dashboard 21→約 8 秒；冷／熱輸出與修改前逐位元組相同。Accounting 與 Dashboard 傳入的資料不同（Dashboard 另帶 Announce／建立時間），各自記，不共用。
- **業主決定：Dashboard 的未結清應收／應付只算 5 年內建立的帳款**（正常 2 年內結清）。每筆帳款看自己的建立時間（createdAt 的台北日期；保費帳款為 Announce 時、理賠帳款為記錄理賠付款時），往回 5 年、每天滾動；建立時間缺漏或無法解讀的照算。畫面註明「Entries created in the last 5 years (since 日期)」。Accounting 頁面仍列出全部帳款。
- **業主決定：Dashboard 跳過「帳款標記為整件已銷帳」的案件，並加安全檢查**：系統計算欠款看的是收付款紀錄，結清標記是另外同步的欄位；Accounting 每次打開都核對，若標記為整件已銷帳但實際仍有欠款，在 warnings 列出（提醒 Dashboard 少算）。模擬 70% 案件已整件銷帳時 Dashboard 第一次打開 20.7→10.7 秒。
- 未做：Accounting 回應約 67 MB，組資料與輸出即使記住答案仍需約 12 秒。
- 測試：dashboard_outstanding_window、dashboard_settled_skip；壓測工具 qa/stress（seed.py、dump_responses.py）。
- **Production Report 加速**（同日追加）：同一件案件的分期金額只算一次並共用；報表金額等確定有列落在該月份（或延後到該月）才算。純計算，12 個月份報表與修改前逐位元組相同；1 萬件案件約 15 秒 → 9 秒（未快取）。剩餘時間主要是讀取全部案件資料與連結表（業主 10-16 決定連結表先不改）。
