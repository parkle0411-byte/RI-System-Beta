# VM 規則與維運（RI System）

VM（`/opt/ri-system`）是再保部系統的**正式系統與唯一規格**。本文件只寫**目前有效**的規則，依主題整理；2026-11-03 起取代原本「只增不刪」的寫法。

- 2026-10-05～2026-11-03 的 139 段變更紀錄原文封存在 `docs/archive/VM-RULES-CHANGELOG-2026.md`（逐字保存，不再修改）；想知道某條規則的由來時去那裡查。
- Alpha 搬遷紀錄封存在 `docs/archive/ALPHA-MIGRATION.md`。除錯與驗證**不再與 Alpha 比對**。
- 錯誤訊息一律英文（業主 2026-09-25 決定）。

**維護方式**：新增或修改規則時，(1) 直接改本文件對應主題的內容，不保留已失效的舊說法；(2) 在文末「近期變更」加一行（日期、改了什麼）；(3) 有部署的，在「部署與回復紀錄」表加一列（備份、回復映像、驗證結果）。

---

## 1. 目前設定

| 項目 | 現況 | 怎麼改 |
|---|---|---|
| Audit 記錄 | **暫停**（業主 2026-10-05 決定，直到另行通知）。`compose.yaml` 的 `AUDIT_LOG_PAUSED=true`、`AUDIT_LOG_ENABLED=true`：`record_audit` 不寫入，業務寫入與 Entity Snapshot 照常；Audit 表的不可修改／刪除 trigger 與權限不變。暫停前的 264 筆已備份後清除（`backups/ri_system_before_audit_clear_20261005_142025.sql`）。 | 業主要求才恢復：改 `AUDIT_LOG_PAUSED=false` 並重建 backend；不補寫暫停期間事件 |
| 寄信（Signed Slip 提醒、忘記密碼） | **關閉**（`RI_EMAIL_ENABLED` 未啟用；SMTP 依業主指示最後處理）。提醒照常產生、佔位、防重複，記為 suppressed；登入頁不顯示忘記密碼。 | 先設 `RI_EMAIL_HOST`／`PORT`／`USE_TLS`／`FROM`，再開 `RI_EMAIL_ENABLED`；信中連結用 `RI_PUBLIC_BASE_URL` |
| 財務收付款提醒信 | **關閉**。獨立開關 `RI_PAYMENT_REMINDER_ENABLED`，同樣需要 SMTP 才實際寄出。 | 同上 |
| Dashboard／Production 結果快取 | 開啟，保險上限 5 分鐘（`RI_RESULT_CACHE_TTL=300`，業主決定） | `RI_RESULT_CACHE=false` 關閉 |
| 每件案件結果快取 | 開啟（`cases/case_result_cache.py`） | `RI_CASE_RESULT_CACHE=false` 關閉 |
| 閒置自動登出 | 3 小時（10800 秒），提前 5 分鐘提醒（300 秒） | 見 §11 |
| 網址 | 同事用 **http://ri-dev.tw-insure.com**（短名 `http://ri-dev`）；舊網址 `http://192.168.1.127:8080` 仍可用。Nginx 開 80 與 8080；允許的主機名在 `DJANGO_ALLOWED_HOSTS`。**目前是 HTTP**（HTTPS 暫緩），密碼與資料在區網明文傳送。 | |

## 2. 固定技術規格

| Layer | Stack |
|---|---|
| Frontend | Vue 3.5.43 + Element Plus 2.14.6 + Vite 7.3.6（另有 Vue Router 4.6.4、JSZip 3.10.1） |
| Backend/Admin Panel | Django 5.2.17 + DRF 3.16.1 + Gunicorn 23.0.0 + mysqlclient 2.3.0（Python 3.13.16） |
| Web Server / Reverse Proxy | Nginx 1.28.3 |
| DBMS | MySQL 8.4.11 |
| Host / Container Runtime | Debian GNU/Linux 13（trixie）+ Docker 29.8.2 + Docker Compose v5.6.0 |

- **Frontend**：`package.json` 精確版本＋`package-lock.json`，`node:22-alpine` 以 `npm ci` 建置。Word 產生程式在 `frontend/public/alpha-documents/`（`docx-templates.js`、`vm-docx-generator.js`），不經 Vite 打包。
- **Backend**：`requirements.txt` 精確版本，基底 `python:3.13-slim-bookworm`。gunicorn **4 個 worker**（= CPU 核心數；不可用 `--threads`，壓測時會撐爆記憶體）。Admin Panel 是唯讀 Django admin（`/admin/`，只有 System Administrator）。
- **Nginx**：`nginx:1.28-alpine`（與前端靜態檔同映像）；JSON／JS／CSS 啟用 gzip；轉發逾時 60 秒；`/static`、`/assets` 帶 nosniff 與 X-Frame-Options；SPA HTML 用 no-store、no-referrer；access log 遮蔽密碼重設 token。
- **MySQL**：`compose.yaml` 固定映像摘要（不用標籤）；`innodb_buffer_pool_size=512MB`。網站以最小權限的 `ri_runtime` 連線（多數表沒有 DELETE；Audit 表只有 SELECT／INSERT）；維護用 `ri_app`。
- **主機**：時區 Asia/Taipei（提醒排程 cron 依賴它）。硬體：Xeon E5-2620 v3、VMware 4 vCPU／8 GB；單一請求吃單核，換新一代 CPU 才會明顯變快。
- **PDF 已退役**：只產生 Word，PDF 由使用者在 Word 匯出；Gotenberg 已移除，`/api/render-document-pdf` 固定回 410。
- 升級任何一項：先更新這張表與鎖定檔，再重跑全部測試。

## 3. 維運與測試

| 作業 | 指令 |
|---|---|
| 套用 migration（之後一定要重新授權） | `scripts/migrate.sh`（**不要**直接跑 `manage.py migrate`，`ri_runtime` 對新表沒有權限） |
| 只重新套用資料庫權限與 Audit trigger | `scripts/db_harden.sh` |
| 以維護者身分執行 manage.py（需要 DDL 或 DELETE） | `scripts/manage_as_owner.sh <指令>` |
| 確認 migration 沒漏 | `docker exec ri-backend python manage.py makemigrations --check --dry-run`（要顯示 No changes detected） |
| 建立／停用／重新啟用／重設帳號 | `docker exec ri-backend python manage.py create_ri_account\|disable_ri_account\|enable_ri_account\|reset_ri_password --personnel-id N …` |
| 備份資料庫 | `docker exec ri-mysql sh -c 'mysqldump -uroot -p"$(cat /run/secrets/mysql_root_password)" --single-transaction --routines --triggers ri_system' > backups/…sql`（`chmod 600`；`backups/` 不進版控） |
| 備份案件文件 | `docker exec ri-backend tar czf - -C /data/documents . > backups/case-documents-$(date +%Y%m%d-%H%M%S).tar.gz`（與資料庫同時備份） |
| 提醒排程 | `scripts/install_reminder_cron.sh`（`--remove` 移除）；手動：`manage.py run_signed_slip_reminders`／`run_payment_reminders [--today YYYY-MM-DD]`；紀錄在 `logs/reminders.log` |
| 唯讀資料檢視 | `/admin/`（System Administrator）。新增 model 要在 `admin.py` 用 `ReadOnlyModelAdmin` 註冊 |
| 補分期案件缺少的保費交易 | `manage.py backfill_installment_transactions [--apply]`（先 dry-run，備份後再 apply） |
| 舊帳修復（92 項會計規則） | `manage.py apply_accounting_review` 預覽 → `--apply --expected-signature <signature>` |
| TWD 保費一次性轉整數 | `manage.py convert_twd_premiums [--apply]`（預設 dry-run；可重複執行） |

**測試方式**
- **資料庫／API 測試組**：一律用 `scripts/run_isolated_qa.sh [測試組 …]`（隔離 MySQL＋後端、`ri_runtime`＋db_harden、每組全新資料庫、自動清除；全部約 30–40 分鐘，目前為 111 組）。**不要在正式容器跑**（正式 Audit 暫停，測試會失敗）。`KEEP=1` 保留環境除錯；`QA_BACKEND_IMAGE=<映像>` 改測指定映像（不重建，用該映像內建的測試組），見下方「測試版本」。
- **前後端合計、密碼規則一致性**：`scripts/run_qa.sh totals`／`parity`（`run_qa.sh` 已不再跑測試組）。
- **畫面測試**：`scripts/run_ui_test.sh`（無頭 Chromium，用完即丟的環境）。13 個標準階段 A H R B0 B K C D E F G P1 P2，共 206 項；另有 Oversea Business 的 O 專項 29 項＋分期／批單 22 項、舊案 L 專項 15 項（2026-11-10 起完整執行時一併跑，L 會自動準備舊案測試資料），合計 272 項。`UT_BACKEND_IMAGE`／`UT_FRONTEND_IMAGE` 指定測試映像（預設是正式映像，可能比原始碼舊）；`PHASES="A H"` 只跑部分（要從 A 開始）。測試切換登入身分前等待應用 API 完成，不等待預覽 iframe 的外部資源；保留全部 console 錯誤檢查。
- **前端檢查**：`frontend/scripts/check_*.cjs`（`check_endorsement_notes.cjs` 需在建置映像內執行，因為要 jszip）。
- **壓力測試**：`qa/stress/`（1 萬件案件；結果在 `qa/stress/RESULTS-*.md`）。
- **實作前確認（2026-11-08 業主決定，所有修改都適用，含小改與 bug 修正）**：動工前先向業主說明——理解的需求、預計做法、影響範圍、屬於必問或小改、預計的測試範圍；業主確認後才開始實作（業主在指示中明說「直接做」即視為已確認）。實作中發現做法或範圍需要改變，先停下再問。
- **部署流程**：實作前確認 → 實作 → 測試通過 →（必問項目先問業主確認）→ 備份資料庫（有 migration 再加文件 volume）→ 標記回復映像 → 部署 → 核對正式程式與原始碼逐檔一致 → 在「部署與回復紀錄」加一列。
  - **測試範圍（依影響範圍分級，2026-11-04 業主決定）**：
    - **只更新參考檔／指南**（應用程式碼不變）：跑相關檢查即可。
    - **局部修改**＝只改單一分頁／單一功能，且沒有碰到下列「共用部分」：跑該功能相關的 API 測試組（例：System Reference Data 排序 → `reference_order`）＋前端建置成功＋畫面測試只跑 `PHASES="A"`（登入與基本畫面），該分頁有對應畫面階段再加跑該階段。**不要**跑與修改無關的測試組（例：改 System Reference Data 不跑 Accounting、Production、Case 相關測試）。
    - **共用部分**＝金額計算與取位、會計（收付、對帳、SoA、Accounting、Production）、案件建立／儲存／驗證／批單、權限／登入／帳號、資料庫結構（migration）、Word 文件產生、多個分頁共用的前後端程式（如 API 呼叫、路由、共用元件、共用設定）。碰到任一項：跑全部 API 測試組＋全部畫面測試。
    - **選項或文字增減也算局部**：只在某險種／某分頁的選單或清單加減選項、改顯示文字，且不改金額計算、檢查規則或資料結構（例：CGL 承保項目加 Products Liability）——即使該清單會被案件儲存或 Word 文件讀到，也算局部修改：跑該險種／分頁相關測試組＋`document_generation`、`qs_documents`（清單會進 Word 時）＋`cases_api`＋畫面 `PHASES="A"`。
    - **Dashboard 的顯示、查詢與資料整合（2026-11-06 業主決定）**：Dashboard 只是抓取與整合既有資料供同仁查看，屬局部修改；跑 Dashboard／此次查詢相關 API 測試、前端建置與畫面 A＋G（以及本次變動的操作與顯示檢查）即可，不因涉及 Dashboard 就跑全部 API 或全部畫面回歸。實際更改共用金額計算、會計寫入／收付／對帳／Production 規則、權限或資料庫結構時，才依實際影響套用共用部分的測試範圍。
    - **不確定**會不會影響其他功能時：先問業主要測多少（不要自行決定）。
    - **安全網**：每週三 Debug 時跑一次全部 API 測試組＋全部畫面測試。
    - 回報時寫明這次跑了哪些測試、為什麼這樣選。
  - **必問（不論大小，先測試再問業主）**：有 migration 或改資料庫結構；會寫入或修改正式資料（匯入、`--apply` 指令、清除資料）；新規則或改金額／會計；設定開關與帳號（寄信、Audit、排程、權限、帳號）。
  - **小改（測試通過即直接部署，事後在回覆中告知業主）**：只更新參考檔／指南；純畫面文字與版面（不改欄位、驗證、金額或資料）；不改結果的效能優化（回應比對逐位元組相同）；修正程式與本文件既有規則不符的 bug（不含新規則）。小改仍要備份、標記回復映像並寫入部署紀錄。
  - 同時符合小改與必問時，以必問為準；不確定屬於哪一類就先問。
  - **測試版本（2026-11-08 業主決定）**：
    - **每週三 Debug** 的全部 API＋全部畫面測試，對象是**最新已部署的正式版**：`QA_BACKEND_IMAGE=ri-backend:local scripts/run_isolated_qa.sh`（用正式映像內建的測試組，題目與程式同版）＋`scripts/run_ui_test.sh`（預設即正式映像）。
    - **部署前測試**的對象是**這次要部署的候選映像**＝以最新已部署版本為基礎＋本次修改建置的 `ri-backend`／`ri-frontend`。API 測試用 `QA_BACKEND_IMAGE=<候選後端映像> scripts/run_isolated_qa.sh …`；畫面測試必須用 `UT_BACKEND_IMAGE`／`UT_FRONTEND_IMAGE` 指定同一組候選映像（不可用預設的正式映像）。部署時直接部署測過的那組映像，不重新建置；回報寫明測試用的映像名稱。
    - 候選映像若含其他 session 尚未完成的修改（`git status` 有不屬於本次的變更），先問業主是否一起部署，不要自行帶上線。
- **Docker 映像保留（2026-11-06 業主決定）**：`ri-*` 自建映像一律保留——容器使用中（含已停止）、7 天內建立或 tag 日期在 7 天內、本文件／腳本／compose 有寫到（含「部署與回復紀錄」的回復映像）、每個功能最後一個 `before-*` 回滾點；其餘可刪。第三方映像（mysql、nginx、node、python…）不自動刪。清理用 `scripts/docker_cleanup.sh`（預設預覽，`--apply` 才刪；`KEEP_DAYS` 可調），同時清超過 7 天的建置快取與 dangling 映像。每週三 06:00（台灣時間）由 parkle 的 crontab 自動執行，紀錄在 `logs/docker-cleanup.log`。不要用 `docker system prune -a` 或 `docker rmi -f`。
- **開發工具舊版本清理（2026-11-07 業主決定）**：`scripts/tools_cleanup.sh`（預設預覽，`--apply` 才刪）每週三 06:00 接在 Docker 清理之後由 parkle 的 crontab 自動執行，紀錄在 `logs/tools-cleanup.log`。清 parkle 家目錄內 Codex、Claude Code、VS Code 伺服器與擴充套件的舊版本、VS Code 擴充安裝檔快取，以及 `/tmp/ri-*` 暫存；一律保留執行中、目前版本、最新版本與 7 天內的項目，工具正在更新時跳過。不處理其他帳號（如 olin1）。

**開發注意**
- `frontend/src/views/CaseWorkspace.vue` 與 `case-workspace.script.js` 直接維護（舊的產生器已不存在）。
- 金額語意刻意重現 JavaScript 的數字規則（`backend/cases/calc/jsnum.py`）讓前後端一致，不要改成 Decimal。文字以 UTF-16 單位截斷、JSON 大小上限 250000、Clause 代碼排序用 ICU 規則（符號 < 數字 < 字母；非 ASCII 符號尚未對照）。
- 多個 session 可能同時改 `/opt/ri-system`：commit 只加自己的檔案（不用 `git add -A`），部署前比對正式映像。

---

## 4. Case：建立與共通欄位

### 4.1 結構與險種

- **Insurance Type（2026-11-05）**：Case key-in 最上方原 Class 標籤改為 Insurance Type，提示文字同步調整。只是畫面名稱；沿用 classOfBusiness 資料、既有選項與排序，Account List／其他頁面的 Class 名稱維持。

- **Class 選單固定顯示順序（2026-11-05）**：Property → Personal Accident → Commercial General Liability → Products Recall → Marine Cargo → Stock Throughput → Electronic Equipment → Jewelers Block → Fine Art → Terrorism。僅顯示目前已開放及有效的選項；QS 顯示 Property／Commercial General Liability，Property 在前、CGL 在後；Oversea Business 顯示 Fine Art／Terrorism。未列入的新類別排在上述順序之後；不改主檔名稱、其他選單或後端規則。
- **Case key-in 提供 Quota Share（QS）及 Oversea Business。** QS 的 Class 仍限 Property／Commercial General Liability；Oversea Business（儲存代碼 `OVERSEA`）的 Class 僅限 Fine Art／Terrorism。後端保留既有 QS／XOL 支援，歷史 FACULTATIVE 視為 QS；不清理主檔、不轉換案件。Oversea Business 的獨立規則見 §4.8。
- **系統沒有 Treaty**（2026-11-02 完整移除；儲存 TREATY 被拒絕；資料庫 CHECK 只接受 FACULTATIVE／QS／XOL／OVERSEA）。
- 新增／編輯表單最上方同一張卡片先選 **Structure 與 Class**（可任意順序）；兩項都選了才顯示其他區塊與儲存／Review。清除任一項只隱藏下方內容，已填資料保留。
- Type 由「自填前綴＋結構後綴」組成：QS = Facultative Reinsurance，XOL = Excess of Loss Facultative Reinsurance（後綴鎖定，改結構才會變）。

### 4.2 Facility 再保人的可選險種
| Facility（精確名稱，大小寫與空白正規化） | 可選險種 | 結構 |
|---|---|---|
| Lloyd's Underwriter Syndicate No. 0609 AUW (Facility) | 只有 Property | QS／XOL |
| Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility) | 只有 Property | QS／XOL |
| Great American Insurance Company, Singapore Branch (Facility) | 只有 Property | QS／XOL |
| QBE Hongkong & Shanghai Insurance Limited (Facility) | 只有 Property | QS／XOL |
| Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility) | Property 或 Commercial General Liability | **CGL 只能 QS** |

- 選單隱藏不相容組合；已選該 Facility 時，切換或清空 Class／Structure 會被擋下並提示先移除再保人（資料保留）。
- 後端在新增／編輯、自動儲存、Review／Announce、續保／批單、文件授權、付款天數補填都檢查，無法用 API 繞過；拒絕時不改案件與版本。舊的不相容案件可檢視並修正。
- 一般再保人（名稱不含 Facility）與一般 Allianz／QBE 沿用一般規則。

### 4.3 新案預設值
- Currency TWD（CGL QS 與 Swiss CGL QS：只提供 TWD／USD，預設 USD）；New／Renew 預設 New。
- Cedant 與再保人 Tax 預設 1%（AUW Tax 固定 0%）；AE 預設登入者姓名。
- Effective Date 選定後帶入一年後的 Expiration Date（閏日帶翌年 2/28）；手動改過或既有非空值不覆寫。時間選項 12:00／00:00，預設 12:00；**手動改 Effective 時間會同步帶入 Expiration 時間**（Expiration 仍可另選；讀取舊案不強制）。
- Cedant Collection Days 預設 90（可改）；Property 與 CGL QS 新增一般再保人時付款天數預設 90（可改）。Facility 的 Cedant 天數固定 90（原單／續保；批單沿用來源）。
- 新案以 Cedant 自己的天數算 Cedant 帳款（`cedantTermsBasis=case`，由伺服器保留）。

### 4.4 共通驗證
- 期間：Expiration 必須晚於 Effective（Property 與 CGL QS 不接受同日）；所有原單、續保與改期後的完整期間**最長 18 個曆月**（剛好上限可以；月底按曆月末日）。
- 付款天數：有填或正式檢查時，必須是至少 15 的整數。每期 Cedant 及每期每家一般再保人天數各自獨立填寫（不繼承），缺漏列「待確認」且不能收付。
- **Premium Installments**：啟用時至少兩期（儲存即檢查，零期／一期拒絕）；批單不能分期。CGL QS 另有：第一期 Payment Base Date／Performance Month 預帶 Effective Date，各期預帶 Case 與各再保人天數，每期保費合計須等於 100% Premium。
- **TWD 保費**（Case 100% Premium、每家再保人、每期）只准整數，前後端擋小數，不偷偷取整；USD 兩位小數。
- **Order Hereon**：新填或修改時每家 > 0、≤ 100%、最多 8 位小數，合計 ≤ 100%；未修改的歷史比例保留。
- **Loss Record**：一般保費 Case 儲存時（Oversea Business 依 §4.8）年數與 broker advised date 必填；New 可填 0 年（明細必須為空，文件顯示 Loss Clean since operation.）；Renew 至少 1 年（續保可帶入 0 但儲存前要改）；明細的日期、原因、金額都必填（CGL QS 金額 > 0）。Additional Loss Record Notes 輸入已隱藏（舊資料保留）。
- **Performance Split**：兩方合計 100% 時 b 方 = Leg 總額 − a 方，交易合計與排程分毫不差。CGL QS：預設關閉，啟用後一位 Reinsurance Staff、一位 Other Staff，只允許 40/60 或 70/30。
- **案件附件上限**：Property 案件 30 MiB，其他險種 10 MiB；自動生成的 Word 與 Placing Slip 上傳 30 MiB。手動附件每案最多 50 份（自動生成文件另計）。可上傳格式含 .xlsx／.xls。
- **案件文件只有 Draft 能刪**；Announce 後刪除回 409。案件與主檔永不實體刪除（回收桶 5 年內可還原）。

### 4.5 Draft 自動儲存與原始輸入
- 適用：Property QS、CGL QS（含 Swiss CGL QS）、CGL XOL，以及所有臨分批單 Draft。Structure／Class 都選定後才啟動；系統預填不會觸發建案。
- 人工修改後離開欄位即自動儲存；缺漏、格式錯誤、未完成數字／日期、尚未加入的條款文字都保留原文（`draftInput`／`pendingClause`），重開或重新整理可還原。
- Review／Announce 及文件仍執行完整檢查；Announce 成功後移除草稿原文。帶有草稿原文的修正案須重新 Announce 才能產生文件。
- 新案首次儲存用可重試識別碼，避免重複建案；寫入依序送出並檢查 rowVersion。Announced／Confirmed／Reversed 不啟用自動儲存。

### 4.6 資料異常保護
- 再保人清單、分期清單或計算用數字無法解讀時，整案金額顯示 `Pending confirmation` 並列出異常；不修補、不以 0 代替、不丟棄原資料。
- 修正前，後端擋下 Announce、文件、收付款、沖回、更正、續保／批單／Reverse 與理賠操作；Dashboard／Production 註明異常案件未計入。須技術人員查明原文後修復。
- Accounting 逐案計算：單一案件無法解讀只略過並警告，其他照常。

### 4.7 條款（Clauses）
- Case 的條款 Title **持續跟隨 MDM 最新 Title**（條款主檔 → 該 Class／Reinsurer 的固定條款 → Case 自訂 Title）；開啟時、切回視窗、前景每 30 秒更新，Review／儲存／生成文件前重讀，讀取失敗則擋下載。Word 只印 MDM Title 原文，不另補代碼。
- Fixed Clause 依 Class 與 Reinsurer 帶入；Universal：LMA3333 Reinsurers Liability Clause、Intermediary Clause (TW Insurance Brokers Ltd.)。
- 人工條款加入清單時 Code 與 Name 必填。

### 4.8 Oversea Business（國外業務特殊案件，2026-11-05）
- 結構 `OVERSEA`，Class 只能 Fine Art／Terrorism；獨立簡化表單的財務必填項目為 **100% Premium、Share (%)、Brokerage 金額、Reinsurance Broker、Cedant、實際收付款日期**。Currency 隨 Premium 選定，新案預設 USD；負責人與 AE 預帶登入者。不要求一般案件的承保條件、Loss Record、條款。
- 補充 Insured (EN)、Insured (CN)、Policy Period（日期及時間）與 Account Executive；AE 預帶登入者，可由主檔選擇調整。所有列出的輸入欄位均為 Announce 必填，包含中英文被保險人、保單起訖日期與 AE；Draft 可暫存未完成資料。中文被保險人沿用既有 Announce 建立正式主檔規則。Policy Period 與實際收付款日分別保存。
- **Brokerage 直接是 T3 金額**，不乘保費或 Share、不從 T1−T2 推算。100% Premium × Share 僅作分攤保費資訊。TWD 為整數，其他貨幣最多兩位小數；正佣金為向所選 Broker 收款、負佣金為付款。不建 T1／T2、零額保費排程、分績或 Claim。原單可選擇 Brokerage 分期，比例各期 >0 且總和 100%；依貨幣精度自動分攤，尾差優先調整第一期；若該期不足以吸收，依序調整後續期，避免反向金額。每期分別填實際收付款日，分別產生獨立 T3。
- **Accounting Date＝實際收付款日期−10 個日曆天**，可跨月、跨年、閏年；實際日期原樣保留。原單 Announce 以 Policy Period 的 Effective Date 年月及 Class 代碼分配 TW Ref；實際收付款日及分期日期不影響取號；單筆 `...-R1-T3`，分期為 `...-R1-I1-T3`、`...-R1-I2-T3` 等。各期 Accounting Date 依各自實際日減 10 天，Production 依各期實際月份認列各期精確 Brokerage，關帳不重複建帳。
- 批單沿用既有最新來源與原單鏈限制，編號接原單 `-E01`、`-E02`。100% Premium、Share、Currency、Broker、Cedant 與 Policy Period 沿用來源並鎖定；另填批單生效日、說明、本次 Brokerage 增減金額（加收正、退款負）及實際收付款日。每張批單為單筆獨立 T3，不改寫原單分期、收付或已認列業績。Brokerage-only 批單的 Production 保費為 0，僅認列本次 Brokerage 增減，沿用的原單保費資訊不再計入保費統計。
- 不生成任何文件（畫面隱藏，後端封鎖），Announce 前須上傳並選用國外 RI Broker 提供的 Note：Original 僅接受 Credit Note；批單可用 Debit Note 或 Credit Note，不依金額正負自動決定種類。每案／每張批單獨立附件，不能沿用原單附件；未選用、已刪或檔案本體遺失均不能 Announce。不要求一般 Offer Slip／Signed Slip。Draft 可先儲存，最終須確認 Note、Brokerage 及實際日期。
- 更正 TW Ref. 後，既有提醒紀錄的主旨、內容及交易鍵原樣保留；系統依舊號與目前交易編號的對應延續提醒節奏，不重發或跳過既有週期。
- T3 是獨立佣金現金帳款，不依賴不存在的 T1／T2。未結清時在 Accounting 未對帳／已對帳清單處理；部分收付仍為 Open，全額完成才移入 Brokerage，All Accounts 始終保留。每次財務登錄可用不同實際收付款日，案件／期別日期、Accounting Date 與 Production 認列月份維持原值；不因部分收付款改動。
- 公告後更改金額、Broker、Cedant、日期等須填原因；已有有效財務覆核／收付／Production 認列時禁止直接覆寫，先依既有流程處理。一般 QS 案件不受本節影響。

---

## 5. Case：各險種專屬欄位

> 2026-10-28 起新增的 Property／CGL QS 案件，以及從舊案建立的新續保／批單，使用規則版本 `placing-qs-20261028-v1`（伺服器配置，編輯舊案不會自動升版）。下列標示「新版」的項目只適用這個版本；舊案維持原畫面與檢查。

- **純 Facility 共通規則（2026-11-10）**：僅再保人全部為 Facility 才適用；Original Exclusions／Original Conditions 選填，Interest 固定為各險種既有預設句並在 Key-In 隱藏。混合一般再保人的案件沿用一般規則。Property QS 預設 Basis of Valuation 為 Actual Cash Value、Occupation 輸入高度縮小；Special Agreement 不供輸入且重新產生的文件不顯示，既有資料及已產生文件保留。Great American 再保人 Tax 新原單／續保固定 0%，既有保單原稅率保留，批單沿用來源稅率；Cedant Tax 不受影響。

### 5.1 Property
- Occupation & Construction、Breakdown of Sum Insured、Loss Record、Special Agreement 合併成一張 **Information** 卡片；純 Facility Property QS 隱藏 Special Agreement。
- **Construction** 複選（至少一項，固定順序 A2 Class、A1 Class、B Class、C Class、D Class，無 Other、無預設）；舊文字保留在 `constructionLegacyText`，業務選好並確認後才改寫 construction；未確認不能產生新文件。適用所有可編輯 Property QS／XOL。
- Sum Insured 每個 Location 至少一筆；同一 Location 內名稱不可重複；金額 > 0 才能 Announce。全 Facility 案件可不指定 Location；全 Facility 改混合時，只清空沒有有效 Location 的 Sum Insured。刪除 Location 不會讓 Sum Insured 變成零筆。
- Sum Insured 與 Limit 不一致只提示，不擋 Announce（依 Word 顯示精度判斷）。
- 新版：地址列稱 SITUATION，至少一筆，地址與 Postcode 必填；**Basis of Valuation 必填**（Other 須說明；漏填紅框）；Retention 可空（文件補標準句）；Deductibles 下新增 SIR；Reinstatement Provisions 下依序 Loss Payee、Co-Reinsurance Warranty、Notices（前三項純 Facility 隱藏，Notices 全部選填）；Aggregate Limit 0 視為未填；Sub-Limits、Exclusions、Reinstatement、Indemnity Period、Special Agreement 選填；三項聲明空白補標準 None 文字。
- Property XOL Cover Note 不印 LOCATION 列，地址只在 SITUATION 列出。

### 5.2 一般 CGL（一般再保人；Swiss CGL QS 同樣適用）
- **Information** 取代 Occupation & Construction、Sum Insured、Loss Record、Special Agreement（後兩項移入 Information）。Policy Form 必選（Occurrence／Claims-Made）；Claims-Made 才顯示 Retroactive Date 與 Extended Reporting Period（適用時期間必填）。Territorial／Jurisdiction Limits 必選（三項或 Other 說明）。Business、Products 必填；Website 選填不驗證；Estimated Turnover 至少一筆（區域、幣別、非負金額）；Special Agreement 必選適用與否，適用時必填內容。切換 Policy Form／適用狀態會先確認，確認後清空從屬內容。
- 新版：Business 複選 Manufacturer／Distributor／Importer／Exporter／Other；Turnover Region 單選 USA/Canada／Rest of World／Other；舊自由文字一律放 Other 並需逐區塊確認。Overview 顯示 Adj. Rate（100% Premium ÷ Turnover 換算後加總 ×100%，保單生效月匯率，六位小數；缺匯率顯示 N/A）。
- **Retroactive Date** 可多筆（日期＋說明）：至少一筆；兩筆以上每筆說明必填；依日期排序、同日不可重複；舊單一日期以一筆無說明顯示。文件每筆一行，例如 `(September 01, 2002 in respect of limit USD 1,000,000)`。
- **Coverages**（Interest 後）：Premises-Operations Liability、Products & Completed-Operation Liability、Products Liability、Personal & Advertising Injury Liability、Medical Payment、Other 多選，至少一項，Other 須說明。Products Liability 為獨立 Coverage 選項，固定排在 Products & Completed-Operation Liability 與 Personal & Advertising Injury Liability 之間；儲存、Review、Overview、Word 均沿用所選文字。
- **Type**：Products Liability／Commercial General Liability 單選（新案 CGL QS 預設 Commercial General Liability），組成「名稱＋結構後綴＋as original」。
- **Interest** 預填 Reinsurance of the Reinsured’s liability under the original policy.（一般及混合案件可改；純 Facility 固定使用標準句並在 Key-In 隱藏）。
- **Limit of Indemnity**（原 Limit of Liability）必填 > 0，文件後加 each occurrence。
- **Aggregate Limit** 必填 > 0，預帶並跟隨 Limit of Indemnity，人工修改後保留（可恢復跟隨）；草稿可保存未完成值。
- **Underlying Limits** 只在 XOL 顯示，Review／Announce 必填；Sub-Limits 選填。
- Terms & Conditions：Self-Insured Retention（Deductibles 後）選填；新版 Deductibles 與 SIR 至少填一組；Notices 選填；Co-Reinsurance Warranty 選填。Basis of Valuation、Indemnity Period 隱藏且不輸出（資料保留）；Cover Note 不印 Loss Payee。
- **Principal Address**（原 Situation）：新版非必填；舊版至少一筆、地址必填，Postcode 選填（有填 3–6 位數字）。
- **Annual** 勾選預設勾，Cover Note 加印 (Annual)；只是文件標示，不影響任何計算。
- Reinsurance Conditions 提供 LMA3100、LMA5396、Excluding Ex-Gratia and without prejudice payment 三項人工勾選，預設不勾。
- 期間標題在 Overview／Review／Cover Note 顯示為 Period。
- CGL QS 的 Review／Announce 必填：Original Insured (CN)、Reinsured’s Retention、Cedant Commission／Tax／Collection Days、一般再保人 Payment Terms Days（佣金與稅可為 0）；Case Owner 在 Announce 必填；AE Email 只在產生文件前要求；Original Exclusions 選填。
- 一般再保人搭配 PWS Foreign RI Broker 仍用一般 CGL 表單。

### 5.3 純 Facility 案件
- 判斷：有具名再保人且全部以 (Facility) 結尾。
- Key-in 隱藏 Reinsured’s Retention、Reinstatement Provisions、Express Warranties、Conditions Precedent（資料保留）。新生成的 Cover Note：Retention 固定 Advice of Reinsured’s retention waived；Express Warranties 與 Conditions Precedent 固定 None - other than as may exist in this document or in the wording that forms part of this contract.；Reinstatement Provisions 整列省略。隱藏的 Retention 不擋 Review／Announce／文件。
- 純 Facility 不提供 Placing Slip。
- Facility 的付款、提醒、Broker 說明集中在「查看 Facility 規則」視窗，只列本案適用規則。

### 5.4 AUW（0609 AUW Facility）專屬
- Foreign RI Broker 自動帶入 Howden Specialty Limited 並鎖定；改成非 AUW 時清空 Howden、Deductions、Tax、付款天數。
- Deductions 預設 10%（可改，含 0%，Announce 前必填）；Reinsurer Tax 固定 0% 並鎖定；付款天數固定 120（月底起算，見 §8.2）。
- **TW Ref. (for AUW)**：Placement 含 AUW 時，原單／續保 Draft 必填單行、最多 160 字元（保留前導零與標點）；全域不可重複（含舊號、回收與封存案件）。純 AUW 案件以手填號碼作為主編號，不消耗流水號；混合案件保留自動流水號，顯示為「自動 & AUW」並去重。手動主編號公告後鎖定；續保需先輸入新號碼。

---

## 6. Announce、TW Reference 與證明文件

- 表單最下方 **Review & confirm**：通過業務必填後先保存 Draft，Review 視窗內可直接上傳／選取 Offer Slip（批單為 Endorsement）、各再保人 Signed Slip 或 Confirmation E-mail；證明未齊、上傳中或未勾確認不能 Announce，改動後須重新確認。仍須業務自己按 Announce。Overview 也有 Upload Evidence 與 Review & Announce。
- 證明要求：Offer Slip（批單：本批單 Endorsement）＋涵蓋全部再保人的 Signed Slip 或 Confirmation E-mail（E-mail 先行仍須補 Signed Slip，並有 Signed Slip 提醒）。比對再保人名稱時，Announce 會去掉「(Facility)」。
- Announce 寫入伺服器時間；成功後立即建立保費帳款（§8.1）。版本衝突會清除確認，須重新 Review。
- **TW Reference**：自動流水號（超過 999 不截斷）；AUW 規則見 §5.4；顯示規則「自動 TW Ref. & AUW 編號」用於列表、標題、SoA、Reminders、Accounting、Word 檔名與內文；搜尋接受合併文字或任一編號。TW Ref 改過時舊號保留在 `previousTwRefs`，可查詢且不能再分配（大小寫不敏感比對）。
- Statement No. 與各再保人 Reinsurer Ref. 可在 Announced／Confirmed 後用 Edit references 更新（Case SoA 與 Accounting 都有，需 `cases.write`；`accounting.write` 不授權）；只改這兩個欄位並留 Snapshot，不重算任何帳款。
- 案件鏈寫入先鎖根案件；並行衝突回 409。

---

## 7. 批單（Endorsement）與續保

### 7.1 批單
- 適用所有臨分險種 QS／XOL。第一張由 Original 建立，之後從最新已 Announced／Confirmed 版本繼承；不得跳過未完成的批單。
- 業務填：保費差額、批改生效日、批改類型（至少一項，可複選）、wording（必填）。
- **固定沿用來源、不可改**：幣別、險種、結構、Reinsured、再保人名單與 Order Hereon、Foreign RI Broker、Cedant 與再保人的佣金／Deductions／Tax／付款天數、Performance Split。AE／Case Owner 可改；其他風險資料須在該區塊按 Edit 才能改。
- **逐區塊 Edit**：批單所有區塊預設收合；每次只能有一個區塊在編輯，按 Done、收合或切換前先保存再鎖回。Endorsement details 與 Premium 可直接填。Schedule of Security 的 Reinsurer Ref. 可直接填寫／修改並沿用草稿自動儲存；其餘固定來源欄位及 Performance Split 仍只能看。
- 改期：Risk Details 選 Period 並按 Edit；生效日依最新已公告期間檢查（可等於起日或到期日）；後續批單生效日不得早於前一張（可同日）；完整期間最長 18 個曆月。
- 保費為帶正負號的差額（補費正、退費負）；同張可不同再保人混合補退。**Case 與每家再保人全為 0** 才於 Announce 後直接 Confirmed 並排除 Production。批單單期、不可分期。
- 正式編號 Announce 才配置：Original 編號 -E01、E02…；雙編號兩邊同序號；純 AUW 只衍生 AUW 編號。
- 有較新的批單，或批單鏈上有未完成批單時不能續保（案件頁顯示原因）。

### 7.2 續保
- 所有臨分續保採**全保期平均**：同年度 Original 加已完成批單的補退費 ÷ 最新完整保障天數 × 續保天數；Case 與每家再保人各自計算、依幣別取位。
- 從最新到期日接續、預帶一年（365／366 天），可改期但最長 18 個月；改期只重算未人工修改的保費。無法推算的欄位留白並說明原因。
- AUW 續保／批單不沿用來源手動 Ref.；被保險人主檔沿用來源。

---

## 8. 會計

> 適用一般再保人與六類 Facility 情形（一般、AUW、Allianz、Great American、QBE、Swiss Property、Swiss CGL）。本系統只做人工收付登錄與對帳，**不接銀行或外部會計系統**；銀行手續費由外部會計系統處理。有收付、抵銷、銷帳或 Production 認列紀錄的舊帳，保留原算法、精度與歷史（`accountingLegacyMath`、`legacy-cents`）。

### 8.1 建帳
- **Announce 時立即建帳**；分期一次建立全部期別。Production 只認列業績與月份，不重複建帳；零業績仍保留帳款。
- 一般保費案件（Oversea Business 依 §4.8）每案／每期／**每家正分攤再保人**各有獨立 T1（Cedant）、T2（再保人）、T3（經紀費）；零分攤不建帳。
- 分配：先算整筆 Cedant T1，依再保人比例分配（最大比例吸收尾差，同比例依案件順序），再把每家 T1 分期（第一期吸收該家尾差）。例：T1=1,000、33.33/33.33/33.34 → 333/333/334；兩期各 50% → 499/501。T2 各家獨立計算；每家 T3 = 自己的 T1 − 自己的 T2。
- 交易編號：保費 T1／T2／T3、理賠 C{id}；後綴分績 a／b、分期 I{n}、批單 E{n}、更正 C{n}、沖銷 RVS{n}。舊資料的 TX／CLM 原樣保存，畫面以新寫法顯示。
- 批單的 Production 月份與帳款基準 L＝批改生效日與實際 Announce 台灣日期較晚者（已關帳則順延第一個未關帳月）。

### 8.2 到期日與畫面提醒日
B＝單期為保單生效日、分期為各期 Payment Base Date；C／R＝該期 Cedant／再保人天數；全部日曆天，**週末假日不順延，不設延期流程**。

| 類別 | Cedant 到期 | Cedant 提醒 | 再保人到期 | 再保人提醒 |
|---|---|---|---|---|
| 一般 | B＋C | 到期前 15 天 | B＋R | 到期前 10 天 |
| AUW | B＋90 | B＋75 | B 所在月底＋120 | 月底＋110 |
| Allianz（只 Property） | B＋90 | B＋75 | B 所在月底＋90 | **往後第 3 個月月底前 10 天**（例：1 月→04/20；2 月→05/21；11 月→翌年 02/18） |
| Great American（只 Property） | B＋90 | B＋75 | B 所在曆年季末＋90 | 季末＋80 |
| QBE（只 Property） | B＋90 | B＋75 | 承保年度季末＋90（承保年度 8/1 起：8–10、11–1、2–4、5–7 月） | 季末＋80 |
| Swiss Property | B＋90 | B＋80 | 固定結算期 | 固定結算日 |
| Swiss CGL QS | B＋90 | 到期前 15 天 | B 所在月底＋90 | 到期前 10 天 |

- **Swiss Property 結算期**：每年 2/14、5/14、8/14、11/14；11–1 月→2/14、2–4 月→5/14、5–7 月→8/14、8–10 月→11/14。原始期依 Cedant B＋90 歸期，與「最後有效收款日歸期」「財務確認日（Cedant 自動銷帳的實際台灣操作日，不可回填）歸期」取最晚。月底為確認截止。未收妥先顯示預計期。退保費可依 Announce 截止規則提前一期。
- **批單**：把 B 換成 L；Cedant 到期 L＋C（Facility 為 L＋90）；再保人依上表公式（Swiss Property 依固定結算期）。
- 遲收 Cedant 款、部分收付、補登日期都不重算原期限。超過實際到期日才算逾期。

### 8.3 財會對帳與實際收付（2026-11-10 部署）
- 操作者只有 Finance Staff、Finance Manager、System Administrator；業務與 President 保留唯讀。
- 「已對帳」＝財會已核對內容與金額，不要求對方同時確認，也不代表已收付。T1／T2、理賠及 Oversea 現金 T3 均須先對帳；歷史已對帳／已結清資料及既有收付歷史保留，不補造銀行紀錄。
- 同一實際對象可跨案、跨期、跨幣別對帳，同對象全部有效對帳合為一個邏輯批次，原始各次對帳事件與幣別保留。對帳日期必填，Review reference／Explanation 選填。
- 取消對帳須填原因，整個對象批次一起取消。任何幣別成員有有效收付或歷史抵銷時，先依原沖回限制處理；任何成員變動均須取消整批並重新對帳。
- 停止一切新增抵銷／純抵銷，僅登錄實際現金收款與付款。既有抵銷繼續反映餘額與收付前置條件，保留查閱及合法整筆沖回。
- Record Selected 可選同一實際對象的多個幣別、兩種方向，逐列 Cash Amount 預帶 Outstanding，可修改。系統按幣別與方向建立獨立收款／付款登錄，不互抵，不跨幣別加總。
- 同畫面待登錄列共用實際收付款日期、Accounting Dept. Ref.／Note，參考號或說明至少一項；已完成登錄維持其原存日期與參考號，另記操作時間。
- 合法列先保存，失敗列保留輸入及原因，只重送失敗列。0 金額列為失敗，不默默跳過或產生虛構現金。提交／列識別碼防止網路中斷或重送造成重複入帳；重試不能換成另一個對象。
- 保費、退保費、理賠及 Oversea 現金 T3 均允許部分收付。畫面只有 Open／Settled；部分收付仍為 Open，收付足額才自動結清。
- 當期所有 T1 全額收齊（含既有合法抵銷）後才可付 T2；Swiss 正保費另須獨立結算清單參考號，提示 SWRPA-xxxxxxx-xxxxxxxx，不新增格式驗證。
- 收齊所有再保人退款（含既有合法抵銷）後，可分次／逐筆退還 Cedant，不再要求一次選取全部 T1 全額退清。
- 理賠付出不得超過該請款累計回收款項（含既有合法抵銷），不得以其他保費應收取代尚未收回的理賠款。正負理賠均保留原前置條件。
- 一般留存 T3 依各家 T1／T2 完成自動結清，不產生銀行紀錄；Oversea 現金 T3 始終是獨立佣金現金帳款，不補造保費 T1／T2。
- 更正登錄統一整筆沖回再登錄，保留原紀錄、反向與替代關係；已結清仍可沖回，但若破壞後續付款／退款或理賠累計上限則阻擋，不得只沖回批次的一部分。相關有效收付全部沖回後可依既定規則案件更正，永久的 Case Reverse 歷史限制不解除。

### 8.4 賠款與財務追蹤
- Claim Payment 建立時立即建再保人應收與 Cedant 應付；準備金只追蹤不建帳。比例依出險當天適用的保單／批單。
- 到期：一般、AUW、Allianz、Great American、QBE、Swiss CGL＝建帳台灣日期＋15日；Swiss Property 依建帳日歸入固定結算期；日期及各家提醒頻率不因本次改版更動。
- 同一請款累計付出不得超過該請款已收（含既有合法抵銷）。其他保費應收不能取代尚未收回的理賠款。
- Record claim follow-up 擴大至所有未結理賠，保存日期、操作人及內容；不改餘額，不代表已收付；舊追蹤紀錄保留。
- 理賠正式更正仍受收付、對帳整批取消及有效日期／有限金額檢查保護。

### 8.4a 案件金額更正、SoA 與 Production
- 無有效收付的 T1／T2 可依案件權限填原因更正；T1 已完成則保留 T1，只更正該家未付 T2／T3。T1需變動或該家T1／T2都完成時走批單；其他再保人已完成不鎖未處理的該家。
- 相關收付／抵銷全部沖回後，可再次做案件更正；整件 Case Reverse 仍永久受保費收付／抵銷歷史阻擋，即使全部沖回也不解除。
- 原 Production 尚未認列或原月份未關帳：有變動的有效帳款直接更新，報表顯示修正值；保留更正前後、原因、人員與時間。
- 原認列月份已關帳：SoA 僅有變動的帳款保留舊帳＋沖回＋新帳，連結版本；Production 對該家保費及收入完整沖回再重列（保費不變亦一正一負），放更正當月，已關帳順延第一個未關帳月。新舊兩筆均沿用原認列匯率，不改已關帳報表；多次更正以最新有效版本銜接。
- 早期合併列示的 T1／T3 保留原帳款結構，已關帳後仍對變動帳款沖回重建，並對應受影響再保人的原匯率業績分錄。
- 修正帳款沿用原到期日及提醒日，不因更正延後。已對帳者須先取消整批，修正後重新對帳。

### 8.5 金額取位與匯率
- 保費**逐步取位**：TWD 每一步四捨五入到整數，USD 到兩位；佣金與 Tax 以取位後的分出保費計算；T1＝分出保費 − 佣金 − Tax。負數 .5 遠離零（與正數對稱）。Case 合計、會計、付款排程與 Word 同一口徑。例：TWD 999、10%／15%／1% → 100／15／1／T1=84。
- 賠款與收付款兩位小數。分期尾差集中第一期。
- 未 Production 認列的保費以最新月匯率暫估台幣並標示 Estimated；認列後固定為實際認列月份的正式匯率。賠款用建帳月份匯率。缺匯率不擋原幣作業，顯示 Awaiting FX。
- 畫面：TWD 整數不補 .00，USD 兩位；12 個金額欄位顯示千分位。

### 8.6 提醒信（目前未寄出，見 §1）
- 保費、退保費、賠款全部納入：**首次信在各筆 Accounting 提醒日**，之後在實際到期日及逾期每 7 天，餘額歸零停止；同日同類去重。信件寫真正到期日並附會計提醒日。名稱「會計收付款提醒」。
- 收件人：案件 AE、AE 主管、所有啟用中的 Finance Staff；先寄有效 Email，缺漏另列出。
- 寄信未啟用時（suppressed）逾期提醒也維持每 7 天一筆。

### 8.7 Accounting 畫面
- Record Selected 的 Direction／Outstanding 固定窄欄寬，Outstanding 靠左減少間距；Outstanding 與 Cash Amount 的幣別、金額各自同一行，完整顯示八位數台幣及千分位。



- Record Selected 彈窗壓縮 Account、Insured EN/CN、Direction、金額、Result 與 Action 欄寬及內距；長文字換行，保留所有內容，一般桌面免橫捲，小螢幕仍可橫向捲動。TWD Cash Amount 整數不補 .00，USD 保留兩位，既有金額精度不變。

- Finance account review 與 Record Selected 的 Account 識別資訊均與 List 同序：Transaction → SoA → TW Ref · 日期。日期直接沿用 accountDisplayDate，原單／分期用案件生效日、批單用批單生效日、理賠用出險日；缺漏顯示 —，T3 仍不顯示 SoA。

- 五分頁依序為 All Accounts、Unreconciled Accounts、Reconciled Accounts、Settled/Closed、Brokerage。All Accounts 列全部 T1／T2 及 Oversea 現金 T3（未結清與已結清）；前兩對帳分頁預設 Open，可切 Settled／全部；Settled/Closed 僅列有效全額結清的 T1／T2。一般留存 T3 全列 Brokerage，Oversea 現金 T3 未結清時留在對帳清單，收齊／付清才歸 Brokerage。
- Select all／Deselect all 包含目前篩選的跨頁可選帳款，限同一實際對象、可跨幣別與收付方向；多對象時先選一筆或縮小篩選，全不選清除全部頁面的勾選。
- Cedant 與 Reinsurer / R/I Broker 分開下拉選單，互斥選取，僅查實際帳款對象，不因同案 Cedant 而帶出再保人帳款。Leg 改 Direction（Payable／Receivable），主表 Party / Direction，移除 Reinsurer allocation。Due date 為包含當日的單一截至日，空白不限。
- Transaction / SoA / TW Ref標題維持；SoA編號依Cedant Statement No.或對應再保人Settlement Ref取值，缺漏顯示SoA: Missing；T3不顯示SoA。TW Ref後接YYYY-MM-DD：原單與各分期用Case生效日、批單用批單生效日、理賠用對應Date of Loss；資料缺漏顯示—而不推算。移除獨立Reconciliation Ref欄，Edit references移至Action，原權限與狀態限制維持。
- Mark reviewed與Record selected彈窗逐列顯示Insured (EN)、Insured (CN)與SoA，可Remove該列，只移出本次名單，不刪帳款或更動原對帳狀態；名單清空時不可送出。
- 帳款排序：逾期按實際到期日最舊優先；未逾期按 Accounting 提醒日最早優先。TW Ref搜尋只查系統／AUW編號，另加 Original Insured EN／CN；移除 TWD valuation 與QBE承保年季附註。
- 原收付登錄歷史由帳款明細查看（History主分頁已改為Settled/Closed）。整筆登錄保留有效／已沖回狀態及實際收付款日期。分三欄：應收沖銷合計、應付沖銷合計、實收付淨額（新登錄按幣別及方向分開，淨額僅供參考；純抵銷只限既有歷史）。可查會計參考號、TW Ref、對象與日期，展開逐筆現金／抵銷、沖回與替代關係。
- 明細 Applied amount 改 Receipt / Payment Amount；一般歷史不顯示 Swiss period，Swiss需要時列 Swiss settlement due date。T3按鈕 Brokerage settlement details。
- 移除舊人工結清、取消結清、直接更改付款金額及 Offset with original 入口。Complete missing days 只補歷史缺漏，有效天數與新公告帳款不能用此入口更改。
- 每頁預設100列（50／100／200／500）；?view=list精簡資料，返回頁面先顯示快取並背景更新，更新前財務操作停用。窄螢幕表格橫向捲動，不以左固定欄遮擋操作。

- 所有新收付金額及合計以 ISO 幣別代碼顯示（例 USD 1,000.00、TWD 30,000），各幣別分列應收、應付、參考淨額；待登錄與已登錄合計分開。彈窗已完成列唯讀，失敗列可更正／移出後重試。

---

## 9. Production Report

- 案件金額更正依 §8.4a：原月未關帳直接反映修正；已關帳完整沖回及補入受影響再保人的保費與收入，沿用原認列匯率，列本月／第一個未關帳月份，原報表不可改寫。

- 業績月份：原單／續保單期以保單生效月份為準，不因較晚 Announce 而延後；分期依各期 Performance Month；批單取批改生效月與 Announce 月較晚者；已關帳月份自動建立不可改寫的排除紀錄，順延到第一個未關帳月份。零收入不列業績。
- Finance Staff 只能看預覽與既有版本、下載 Excel；Finance Manager 與 System Administrator 可產生、排除、關帳。
- 關帳、產生、排除、匯率存檔共用月份操作鎖（衝突立即回 409 operation_busy）；關帳前在鎖內重讀完整預覽，來源或匯率有變就拒絕並要求重新產生。已關帳月份不能改匯率。
- 欄位 18 欄，最後一欄 **First Policy No**（沿批單→原單、續保→來源追到最初保單的 TW Ref；只靠 TW Ref 連結，不比對名字；不放進來源簽章；已關帳月份不補）。remark 一律 Fac。
- 排除紀錄資料庫層禁止修改刪除。

## 10. Dashboard

- Brokerage 趨勢右上年度選單提供目前年度及前四年（共五年）；目前年度顯示至本月、歷史年度顯示全年。所選年度與其前一年依每月並排柱狀圖呈現，Prior year 在左、Current year 在右；Monthly target 保留折線。選年度僅影響趨勢，其他統計維持現在期間；沿用既有正式關帳／預估及權限規則。
- Accounting · Receivable / Payable 的缺匯率說明為 Awaiting FX — Past 5 years record only.，不再附加重複起算日期說明；資料仍按每日滾動五年篩選。

- 缺少上帳月份匯率時，僅在 Accounting · Receivable / Payable 區塊顯示 Awaiting FX；Dashboard 頂端不再重複顯示匯率警告。換算與缺匯率處理維持。

- 標題：Production & Records Overview。Total Gross Premium、Outstanding · Cedant / Reinsurer 以 TWD 前綴顯示；YTD Brokerage Trend (TWD)；Total Bound YTD；New Business MTD 卡片有 + New Case（需 `cases.write`）。
- 未結清應收應付以 Accounting 實際帳款與上帳月匯率為準，**只算 5 年內建立的帳款**（每天滾動，畫面註明起算日）；跳過「整件已銷帳」的案件，Accounting 若發現標記與實際欠款不符會在 warnings 列出。已關帳業績用正式報表，未關帳標示預估。
- 時間一律台北時間。

---

## 11. 權限與帳號

- 角色權限以 `backend/ri_system/authz.py` 為準。重點：
  - **President**（Board of Directors 部門，目前 David Kao）：全部唯讀（Dashboard、全部案件含他人草稿、MDM、Production、Accounting、FX、全部人員）；**看不到文件區**；不能新增人員或帳號；所有部門都可選 President 當 Supervisor。
  - **Finance Staff／Finance Manager**：可看全部案件明細、流程、理賠，無案件寫入或文件權限；財務操作見 §8.3、§9。
  - **Read-only Supervisor（legacy_supervisor）**：舊案專區、Accounting、Production、全部新系統案件、Dashboard、MDM、FX 唯讀；不因 Supervisor 指派取得人員或帳號建立權限。
  - **Case Viewer**：不能看 Insured Master（選單隱藏，API 403）。
  - **主管**（有人把他設為 Supervisor 即成立）：可看本人及同部門直屬下屬，可新增同部門下屬（角色固定：再保部 sales、財務部 accounting、其他 viewer）並為一般角色直屬下屬建立帳號；不能改既有人員。
  - 能編輯案件的人（業務、主管、管理員）可新增、更名、合併被保險人主檔。
- 帳號：管理員建立／重設／重新啟用後首次登入須改密碼；帳號停用、降權與離職共用交易鎖，不能移除最後一位啟用的管理員。
- 閒置 3 小時自動登出（真實點擊、鍵盤、捲動才續期；背景 API 不續期；多分頁同步）。
- 忘記密碼：可輸入帳號或 e-mail；token 一次性；目前寄信關閉所以入口隱藏。
- System status 與 `/health/` 只有 System Administrator（`/health/` 未登入回 401）。

## 12. 主檔（MDM）

- **Reinsurers**：最上方 **Lloyd's Market** 收合區（名稱以 Lloyd's Underwriter Syndicate No. 開頭者自動列入，含 Inactive）。分類內全部共用 Lloyd's of London 信評（`ri_market_rating_profiles`，有 Edit，需 `mdm.write`；個別成員不能覆寫）。
- **信評欄位**：Rating agency（只能選 S&P Global、A.M. Best、Moody's、Fitch）、Grade、As-of date 必填；Rating type 固定 Financial Strength；Checked at 選填。一般再保人可無信評，Lloyd's 共用至少一筆，最多 50 筆。舊資料不補造日期，但編輯時要補。
- **Insured**：整合於 **Master Data Management**（`/mdm?tab=insured`），位於 Account Executive 後、Classes 前。分頁顯示 `Insured (N)`，僅計正式主檔，搜尋不改總筆數；待確認另列。舊 `/insured` 及 id 連結保留。Finance 唯讀、僅看到 Insured；Case Viewer 不能進入。New insured 與 Rename insured 移除，直接主檔寫入 API 亦禁止。
- **組合身分**：完整中文名稱為 key，`/` 分隔成員、忽略排列及成員前後空白與重複；A/B 與 B/A 共用主檔，A 單獨是另一組合。各保單保留自己的名稱／排列；公告前舊別名不作正式身分或正式更名依據。
- **Draft／Announce**：原單、續保及批單的 Draft 名稱僅存 Case，不新增／連結主檔，不計正式筆數、不產生 Renamed。Announce 成功後才以最後名稱新增或連結；不相容的舊單獨名稱別名不會吸收聯名組合。公告驗證失敗、取消或版本衝突不可先寫入主檔。
- **公告後變動**：Announced 且沒有任何 Confirmed 部分時，變更名稱先詢問名稱更正或變更承保組合。更正沿用同一主檔並記 Renamed，其他保單保留歷史名稱；變更組合只改該 Case 連結，不更名原組合，缺少新主檔可在確認儲存後自動建立。相同成員僅排列不同不產生 Renamed；增加／移除成員不能偽裝為名稱更正。
- **Confirmed**：任何期別或再保人份額已 Confirmed（含整案 Confirmed），即禁止直接變動 Insured；必須走批單。批單 Draft 不變更主檔，批單成功 Announce 時依前一張來源保單／批單的名稱分類確認並處理，原已確認保單保留其歷史名稱。
- **待確認與歷史**：無可驗證 Announce 來源的舊主檔保留資料與歷史，列待確認、不列正式筆數；與成功公告的完整組合相符時自動沿用轉正式。舊歷史標為 Before Announce、正式別名只採公告後確認更名。既有重複組合整併仍先預覽及版本指紋核對，原資料不刪除。Operation time 為台北 YYYY-MM-DD HH:mm:ss；Created、Renamed 等歷史不受 Audit 暫停影響。
- 主檔 API 拒絕非物件 JSON、非有限數字、溢位版本號。

- **2026-11-04 舊名單建檔**：依業主指示，自確認後 1,736 筆名單排除勇信兩組及天后闆妹江X諺／江効諺兩版，共 1,732 筆建檔（新增 1,730、沿用 2）。沒有 Announce 保單來源，依現行規則列待確認、不計正式總數；保留原有 4 筆主檔與歷史，匯入後待確認共 1,734。每筆新增有 legacyImport 來源與 Created 歷史、Entity Snapshot；不建立假保單或公告日期。

## 13. 文件（Word）

### 13.1 通則
- 只產生 Word（PDF 已退役）。A4、Arial／標楷體、頁首 TWIG Logo（4.73 × 2.71 cm 置中）、每頁三行置中頁尾（公司名、地址、電話傳真，10 pt 灰）＋右下 Page X of Y。批單 Debit／Credit Note 頁尾 8 pt。
- 文件資料問題一次列出所有欄位與期別。後端只依已儲存資料授權，請求參數不能繞過。產生文件需 `documents.read`；President 不能使用文件區。
- Cover Note、Debit Note、Credit Note、正式 Endorsement 只在 Announce 後提供。

### 13.2 Cover Note
- 貨幣代碼與金額間不留空格；Original Conditions／Exclusions 為編號條目＋固定尾句（AE 留白只印固定句）。
- INFORMATION、Schedule of Security、附加條款各自另起新頁；章節間不產生空白頁；長表格整列換頁、欄名與內容同頁。
- Schedule of Security 比例降冪、比例與總和間 0.5 pt 虛線。Breakdown of Sum Insured 每個 Location 標題跨兩欄置中。
- 佣金／Tax 未填或 0 整列隱藏，非零固定兩位小數。空白 Retention 用固定句。QS 不印 Underlying Limits。

### 13.3 Debit Note（原單）
- 只開放 **USD／TWD**（依已存 Case 幣別；其他幣別擋下 409 `debit_bank_currency_unsupported`）。USD／TWD 各用既有銀行模板。
- 分期 ≥ 2 期時印三欄表 Instalment／Payment Due Date／Amount（只顯示各期 T1，表頭重複、列不拆頁），合計等於 Net Due。上方分出保費／佣金／Tax 為逐再保人取位後合計。Net Due 為 0 擋下。
- 付款日：非分期為保單起日＋Case 天數 − 15 天；分期依各期天數。
- 銀行資訊全部 9 pt、帳號單行；銀行表頭與帳戶列同頁；簽名圖、公司署名、E&OE 整組同頁，簽名前一行空白；銀行資訊與簽名可分頁。標題 100% PREMIUM。

### 13.4 批單 Debit Note／Credit Note
- 加費出 Debit Note，退費出 Credit Note，保費 0 不出；金額為 Cedant 端 Premium、Ceding Commission、Tax、Net（與 Accounting Leg 1 同算法）。
- 付款日：原單 Cedant Collection Days 從**批單生效日**起算；Debit Note 再提前 15 天，Credit Note 直接寫生效日＋天數。
- Credit Note 只開放 TWD，採業主範本文字、不列銀行帳戶、金額顯示正數。Order Hereon 固定兩位小數。只提供下載，不存入 Case Documents。

### 13.5 QS Word 版本保存、Placing Slip、Addendum
- Property／PD QS 原單與續保的 Cover／Debit：先存入 Case Documents 才下載（UUID＋rowVersion 防重複）；清單只列最新版、舊版留歷史；不算 placement 證明、不占 50 份額度。檔名 `CoverNote／DebitNote_[Ref]_[Original Insured]_[台灣日期].docx`。
- **Placing Slip**（新版 QS）：只在 Draft 生成／上傳／刪除；未選再保人或含一般再保人可用，純 Facility 不提供。保費等欄位留空、付款條件固定 90 天、Annual 預設勾。每次須填版本說明；有編輯版（DOCX／PDF）時停止生成。Case 修改後提醒舊文件可能過時（不擋 Announce）。
- **Addendum**（批單）：批改前 TYPE、REINSURED、ORIGINAL INSURED、PERIOD；原單編號與預估 E 編號；列所有再保人與空白保費；不列 Share、Security Details、簽署區。

## 14. System Reference Data／System Guides

- **共用拖拉排序（2026-11-04）**：System Guides 與 Document Templates 各自排序；沿用 System Administrator 權限，拖拉把手或鍵盤上下鍵調整後自動保存，所有使用者與重新登入共用。順序原子寫入文件 volume 的 `system-reference/.orders/`，備份須包含文件 volume；不需 migration。並行修改以排序版本檢查拒絕覆寫；未排序的新檔列在已存順序之後，彼此依上傳時間由新到舊顯示；更名保留位置，回收筒還原保留已存排序位置。

- Insured 清單（2026-11-03）：以使用者人工整理的 1,752 筆為基礎，依明確選定的 15 組名稱統一寫法，並去除完全重複的力山工業，整理為 1,736 筆。寶結企業／寶結實業、台耀科技／台燿科技各自保留；勇信貿易／勇信物流組合及天后闆妹的江X諺／江効諺兩版待查原文件，這次不合併。其餘未確認候選繼續分開。System Guides 的 `insured-list` 提供 Excel、來源核對明細及整理說明；僅參考清單，未更動正式主檔或 Case。

現行指南（Word）：完整 MDM 指南、完整 Schema 指南（2026-11-02 版）；Swiss Re Facility PD、Swiss Re Facility CGL、Great American Facility PD、QBE Facility PD、Allianz Facility PD（10-30 改提醒日）、Syndicate 609 AUW Facility PD 專屬規則（皆 2026-10-29 版）。舊問卷與舊版隨備份保留。

## 15. 效能設定與量測（1 萬件壓測資料）

- 每件案件結果快取：以「資料內容指紋＋台北日期」記住付款排程與交易明細；每 worker 最多 30,000 筆（約多 210 MB）。
- Dashboard／Production 結果快取：先取資料變更指紋再讀資料；每 worker 32 筆、TTL 5 分鐘；Generate／Close／Exclude 不用快取。
- 2026-11-02 量測：Accounting 精簡清單第二次打開約 10.2 秒（剩餘主要是讀全部案件約 4 秒）；Production 未快取約 9 秒；Dashboard 第二次約 8 秒。
- 業主決定不做：Production 連結表只讀 3 個欄位、跨 worker 共用快取、每件案件整列結果快取、伺服器分頁。
- Accounting 舊案歷史結果快取（2026-11-10）：只快取匯入的歷史交易（唯讀、已結清），以「歷史資料指紋（除 original 外全部欄位）＋台北日期」為鑰匙，每 worker 一份；新增的舊案批單／理賠每次重算。回應逐位元組相同；正式 Accounting 第二次打開約 4 秒 → 1.6 秒（每天或歷史資料變動後第一次仍需重算）。`RI_LEGACY_RESULT_CACHE=false` 可關閉。測試 `legacy_accounting_cache`。
- nginx 日誌行尾記錄回應時間：`rt`＝整個請求、`urt`＝後端處理（秒）；例：`docker logs ri-nginx 2>/dev/null | grep -o 'urt=[0-9.]*'`（容器重建時清空）。

## 16. 已退役／已移除

- Treaty（2026-11-02）、PDF 產生與 Gotenberg（2026-10）、Alpha 差異測試與搬遷匯入工具、舊 Word 產生器、CaseWorkspace 產生器、PendingView、舊 AUW 說明檔。conversion app 的 models／migrations／資料表保留。
- 已取消的舊規則：人工「Awaiting confirmation」才 Settled（改為全額自動銷帳）、Production 關帳才建帳（改為 Announce 建帳）、新增淨額抵銷／純抵銷、舊單獨保費抵銷入口、直接 Edit amount、Facility 專用理賠追蹤入口（統一至全部未結理賠）、Swiss 獨立專區與收妥勾選、固定提前 7 天首封提醒、Allianz 月底＋80 提醒。

---

## 17. 舊案專區：Legacy Data (Old Register)（2026-11-10 部署）

- 歷史匯入資料保持唯讀：`2022~2025 Swiss Re (PD).xlsx` 的 Facultative Property，共 **3,693 筆**；原流水號 **F13333 排除、不匯入**。不建立舊案 Case，不產生歷史 Production Report。
- 所有歷史交易均已完成對帳及結清；Accounting 的已對帳／Settled/Closed 可查，未對帳區不納入；不補造對帳人、對帳日期或銀行收付明細。新舊資料用獨立的來源欄區分，不更動既有 premium／claim 分類。
- Description = 英文被保險人；Cedant's Policy No. = Statement No.；Bkg. (in TWD) 是整筆，Re Dept. Bkg. (in TWD) 是 AE，差額歸 Sub AE。13 筆分績保留原金額，不重算。原幣金額、台幣金額、匯率及原始 Excel 保留。
- 3,663 筆 Swiss Facility、30 筆確實非 Facility（一般付款規則）；不將後者改名或改成 Facility。歷史 Receive Date／Pay Date 是提醒日；無原始約定到期日就留空，不從匯入日重新推算。
- 一般業務、會計、General Manager、President、System Administrator 及新增主管唯讀角色可查閱；Case Viewer 不授權讀舊帳。
- 歷史交易保持唯讀；依 §17.1 開放新增批單／理賠及其 Accounting 寫入。歷史更正、作廢、匯入與撤回 HTTP 寫入仍不開放。
- `ri_runtime` 對 `ri_legacy_transactions`、號碼計數及原因表為 SELECT／INSERT／UPDATE，永無 DELETE；`ri_legacy_import_batches` 僅 SELECT；獨立 `ri_legacy_audit` 僅 SELECT／INSERT，永久不可 UPDATE／DELETE。全系統 Audit 暫停與 SMTP 關閉設定維持。
- 正式首次匯入採業主授權維護程序，核對來源 SHA256、排除清單及 3,693 筆原值。新增批單／理賠及收付流程依 §17.1；受保護交易金額更正留待下一階段。

### 17.1 批單與理賠（2026-11-10 業主確認部署）
- 分頁名稱及內容介面使用英文，主分頁固定 `Legacy Data (Old Register)`；原始中文資料不翻譯。
- 從 confirmed 舊交易帶入資料；Old Reference 可修改，保留原來源交易關聯及案號快照。新交易只有 Endorsement／Claim；不建立 Case。草稿只由建立者編輯、確認；首次確認產生 `LTX-YYYY-000001`，確認年度採台灣年度。未對帳、無收付歷史且未進已關帳 Production 的交易，建立者可退回草稿；再次確認沿用原號。
- Endorsement 與 Claim 分開登錄；批單 Effective Date 為本次批單生效日，Expiry Date 固定保留來源到期日，前者不得晚於後者。Endorsement No. 確認前必填。實際確認時已超過來源到期五年者須選原因；Only Other 另須補充說明；原因由管理員維護並留痕。
- 批單手填 100% Premium、Share (%)、R/I Commission (%)、Tax (%)、原幣 Brokerage 金額；先取位 Our Share Premium，再算佣金與稅；淨額與既有 Leg 算式相同。Bkg.(%) 依金額反推；零承接保費且有 Brokerage 時用正／負100%顯示並填原因。AE/Sub AE 沿用已核准分績與原幣、台幣尾差規則。
- 理賠只填本筆承接賠款，不計佣金、稅、Brokerage 或處理費，兩邊金額相等；DOL 必填且須落在來源 Effective Date 至 Expiry Date（含首尾）內。允許負數退回賠款，不必連結原理賠，負數必填原因。負數向 Cedant 收回後才退還再保人；正負理賠均不得先墊付超過該筆已回收賠款（含既有合法抵銷）。理賠不填 Revenue Month，不進 Production。
- 新交易確認後接到既有 Accounting 對帳、原幣收付、部分賠款、同對象跨幣別、兩方向分開實際收付、部分收付及整批沖回；停止新增抵銷，保留歷史抵銷。正式歷史 3,693 筆維持已對帳／已結清，不補造銀行或覆核事件；仍不提供歷史更正、作廢、匯入或撤回寫入。
- 批單 Revenue Month 手動選尚未關帳月份、不預設；使用該月共用匯率，不提供逐筆覆寫。缺匯率不擋確認及原幣 Accounting；未關帳隨月匯率更正重算，關帳需補齊匯率並凍結台幣快照；不從 Production 排除操作改變選定月份。
- 本版新增號碼計數與原因表，調整新交易資料表寫入權限；獨立 Legacy Audit 保持 append-only。全域 Audit 暫停、SMTP 關閉、固定技術棧及無對外文件／交易附件維持。
- 已完成同一組候選映像全部 105 組 API、268 項畫面測試後取得業主部署確認。已對帳或有收付歷史等受保護交易的業務金額更正留下一階段；本版只開新增與收付，以及符合條件者退回草稿。

---

## 部署與回復紀錄

| 日期 | 項目 | 備份 | 回復映像標籤 | 驗證摘要 |
|---|---|---|---|---|
| 10-05 | Audit 暫停、清除 264 筆 | `backups/ri_system_before_audit_clear_20261005_142025.sql` | | |
| 10-14 | 全面除錯修正 | `backups/ri_system_before_debug_round2_20261014_132129.sql` | `before-debug-round2-20261014_132129` | 49 組測試 |
| 10-15 | gunicorn 4 worker、MySQL 512MB | 有 | `before-workers4-20261015_180259` | 壓測、各表筆數相同 |
| 10-15 | Accounting 表格分頁 | 有 | `before-paging-20261015_184454` | 13 項分頁、185 項畫面 |
| 10-15 | Accounting 共用計算＋gzip | 有 | `before-accel-20261015_203721` | 回應逐位元組相同、52 組 |
| 10-15 | Dashboard／Production 快取 | 有 | `before-cache-20261015_221400` | 逐位元組相同、53 組 |
| 10-16 | Accounting 精簡清單 | 有 | `before-lean-20261016_120011` | 11 組、13 階段畫面 |
| 10-27 | Debug 修正版 | `backups/debug_fixes_20261027_232757` | | 79 組 |
| 10-28 | 批單與全保期平均續保 | `backups/endorsement_20261028_151317` | | 80 組、22 項瀏覽器 |
| 10-28 | Placing Slip（migration cases.0008） | `backups/placing_slip_20261028_211640` | | 80 組、47 項 Placing |
| 10-28 | Placing Slip 排版修正 | `backups/placing_layout_20261028_212934` | | 49 項 |
| 10-29 | Property Construction | `backups/property_construction_20261029_091425` | | |
| 10-29 | Construction 文件分頁 | `backups/construction_layout_20261029_092924` | | |
| 10-29 | 批單 Debit／Credit Note | 有 | `before-endorsement-notes-20261029_123929` | |
| 10-29 | 時間連動與 Review 內上傳 | `backups/case_review_time_20261029_145939` | | 81 組、58 項瀏覽器 |
| 10-29 | 全系統檢查修正 | 有 | `before-review-fixes-20261029_165222` | 82 組、13 階段 |
| 10-29 | 效能優化（每件案件快取等） | 有 | `before-perf-20261029_190315` | 逐位元組相同 |
| 10-30 | CGL Aggregate／多筆 Retroactive | `backups/cgl_aggregate_retroactive_20261030_102739` | | 85 組 |
| 10-30 | 批單逐區塊 Edit | `backups/endorsement_sections_20261030_111553` | | 111 項瀏覽器 |
| 10-30 | Allianz 新提醒日 | `backups/allianz_reminder_20261030_142031` | | 86 組、612 項日期 |
| 10-30 | 批單 Note Order Hereon 兩位小數 | `backups/endo_note_order_percent_20261030_144839` | | 24 項批單 Word |
| 10-30 | Case Key-in 卡片整合 | `backups/case_keyin_ui_20261030_154815` | | 169 項瀏覽器 |
| 11-02 | Key-in 後續與純 Facility 文件 | `backups/case_keyin_refinement_20261102_091603` | | 181 項瀏覽器、68 項後端 |
| 11-02 | Accounting 安全優化 | 有 | `before-perf2-20261102_113609` | 86 組、逐位元組相同 |
| 11-03 | 移除 Treaty（migration cases.0009） | `backups/ri_system_before_notreaty_20261103_091700.sql` | `before-notreaty-20261103_091700` | 87 組、13 階段畫面 |

| 11-03 | MDM 整合 Insured 與組合識別 | `backups/mdm_insured_20261103_110207` | `before-mdm-insured-20261103_110207` | 88 組 API、桌面／手機、資料指紋一致 |

| 11-03 | Insured 公告登錄與變更確認 | `backups/insured_announced_20261103_145940` | `before-insured-announced-20261103_145940` | 89 組 API、桌面／手機、資料指紋一致 |

| 11-03 | Insured Excel 尾綴整理（1,752 筆） | `backups/insured_suffix_20261103_155823` | `ri-backend:before-insured-suffix-20261103_155823` | 僅更新參考檔；逐筆核對、9 份指南下載、權限及回收筒檢查通過，應用程式碼未變 |

| 11-03 | Insured Excel 人工確認名稱（1,736 筆） | `backups/insured_confirmed_20261103_161951` | `ri-backend:before-insured-confirmed-20261103_161951` | 僅更新參考檔；逐筆核對、9 份指南下載、權限及回收筒檢查通過，應用程式碼未變 |

| 11-04 | Accounting 四分頁、批次對帳、淨額收付與案件更正（migration cases.0010） | `backups/accounting_workflow_20261104_104120` | `ri-backend:before-accounting-workflow-20261104_104120`／`ri-frontend:before-accounting-workflow-20261104_104120` | 94 組 API、13 階段 193 項畫面、24 項 Accounting 操作、3,017 組金額；正式資料指紋一致 |

| 11-04 | System Reference 共用拖拉排序 | `backups/reference_sort_20261104_151714` | `ri-backend:before-reference-sort-20261104_151714`／`ri-frontend:before-reference-sort-20261104_151714` | 95 組 API、完整畫面回歸、拖拉／鍵盤／跨帳號／衝突測試；正式資料庫未改 |

| 11-05 | CGL Coverage 新增 Products Liability | `backups/cgl_coverage_20261105_091135` | `ri-backend:before-cgl-coverage-20261105_091135`／`ri-frontend:before-cgl-coverage-20261105_091135` | 依業主限定範圍：11 組 CGL／案件／文件測試＋畫面 A；資料指紋一致 |

| 11-05 | Case 畫面暫限 QS＋Property／CGL | `backups/case_entry_scope_20261105_103522` | `ri-frontend:before-case-entry-20261105_103522` | 6 組案件／文件測試＋畫面 A；後端及資料維持 |

| 11-05 | Case Class 固定顯示順序 | `backups/case_class_order_20261105_104946` | `ri-frontend:before-class-order-20261105_104946` | cases_api＋畫面 A；維持既有開放範圍及後端 |

| 11-05 | Class 排序加入 Fine Art | `backups/case_class_fine_art_20261105_105708` | `ri-frontend:before-class-fine-art-20261105_105708` | cases_api＋畫面 A；只改排序，維持開放範圍 |

| 11-05 | Oversea Business：獨立 T3 與實際日減 10 天（migration cases.0011） | `backups/oversea_business_20261105_152643` | `ri-backend:before-oversea-20261105_152643`／`ri-frontend:before-oversea-20261105_152643` | 全 API／全畫面＋Oversea 專項；正式業務資料與文件指紋一致 |

| 11-05 | Oversea：Insured (EN/CN)、Policy Period、AE；Reinsurance Type 更名 | `backups/oversea_details_20261105_195139` | `ri-backend:before-oversea-details-20261105_195139`／`ri-frontend:before-oversea-details-20261105_195139` | 全 API 97 組／全畫面 13 階段＋Oversea 專項；正式資料、設定與文件指紋一致 |

| 11-05 | Accounting 表格上方同步橫捲軸、右側常駐直捲軸及固定表頭（純版面） | `backups/accounting_scroll_20261105_200401` | `ri-frontend:before-accounting-scroll-20261105_200401` | 前端建置、桌面／手機／四分頁捲動驗證通過；後端與資料不變 |

| 11-05 | Oversea Account 名稱：清單及案件頁首優先顯示 Insured (EN) | `backups/oversea_account_name_20261105_200903` | `ri-backend:before-oversea-name-20261105_200903`／`ri-frontend:before-oversea-name-20261105_200903` | 相關 API 2 組／畫面 A＋O 22 項；正式資料、設定與文件指紋一致 |

| 11-05 | Accounting 表格上方同步橫捲軸、右側常駐直捲軸及固定表頭（純版面） | `backups/accounting_scroll_20261105_201247` | `ri-frontend:before-accounting-scroll-20261105_201247` | 前端建置、桌面／手機／四分頁捲動驗證通過；後端與資料不變 |

| 11-05 | Key-in Class 改稱 Insurance Type | `backups/insurance_type_label_20261105_201703` | `ri-frontend:before-insurance-type-label-20261105_201703` | cases_api＋畫面 A；只改標籤 |

| 11-05 | Accounting 識別欄固定左側及不透明背景（純版面） | `backups/accounting_scroll_20261105_202326` | `ri-frontend:before-accounting-fixed-20261105_202326` | 前端建置、桌面／手機／四分頁捲動驗證通過；後端與資料不變 |

| 11-05 | Oversea：所有輸入欄位改為 Announce 必填，含中英文被保險人、Policy Period、AE | `backups/oversea_required_20261105_205152` | `ri-backend:before-oversea-required-20261105_205152`／`ri-frontend:before-oversea-required-20261105_205152` | 全 API 97 組／全畫面 13 階段＋Oversea 專項；正式資料、設定與文件指紋一致 |

| 11-06 | Dashboard 移除頂端重複 FX 提醒（純顯示） | `backups/dashboard_fx_notice_20261106_141715` | `ri-frontend:before-dashboard-fx-20261106_141715` | 前端建置、dashboard_api、畫面 A＋G 通過；保留欄內 Awaiting FX |

| 11-06 | Dashboard 五年度選單、並排柱狀趨勢與五年帳款說明 | `backups/dashboard_year_20261106_144415` | `before-dashboard-year-20261106_144415` | 依業主確認的相關 6 組 API、13 階段畫面與 Oversea 專項通過 |

| 11-06 | Accounting 五分頁、全選、對帳批次整合、SoA與日期及彈窗篩選 | `backups/accounting_refinement_20261106_150148` | `ri-backend:before-accounting-refinement-20261106_150148`／`ri-frontend:before-accounting-refinement-20261106_150148` | Accounting完整98組API＋整合13組；完整畫面200項、Oversea23項、Accounting26項；正式帳務資料指紋一致 |

| 11-06 | Oversea 比例分期、正負 Brokerage 批單 | `backups/oversea_workflows_20261106_194002` | `ri-backend:before-oversea-workflows-20261106_194002`／`ri-frontend:before-oversea-workflows-20261106_194002` | 100 組 API、241 項畫面、4017 組計算比對；正式資料／設定／文件指紋一致，保留最新版本 |

| 11-06 | 批單 Reinsurer Ref. 開放輸入與修改 | `backups/endorsement_reinsurer_ref_20261106_195915` | `ri-frontend:before-endo-ref-20261106_195915` | 100組API、全畫面及4項參考號碼保存檢查；後端與資料維持 |

| 11-09 | 舊案專區第一版唯讀；Swiss Re 3,693 筆，排除 F13333 | `backups/legacy_readonly_20261109_091930` | `before-legacy-readonly-20261109_091930` | 101 組 API、245 項既有畫面、5 項舊案畫面；正式逐筆核對；新案與報表資料未改寫 |

| 11-09 | Oversea Announce 必須上傳外國 RI Broker Note（cases.0012） | `backups/oversea_broker_notes_20261109_141138` | `ri-backend:before-oversea-broker-notes-20261109_141138`／`ri-frontend:before-oversea-broker-notes-20261109_141138` | 整合最新舊案唯讀版，102 組 API、253 項畫面及 migration 升降級通過；正式業務資料／文件不變 |

| 11-10 | Legacy 批單／理賠、Accounting、Production；migration legacy.0002 | `backups/legacy_entry_20261110_100701` | `ri-backend:before-legacy-entry-20261110_100701`／`ri-frontend:before-legacy-entry-20261110_100701` | 105 組 API、268 項畫面；歷史 3,693 筆／既有業務／文件指紋一致，權限及原始碼核對通過 |

| 11-10 | Accounting：實際對象篩選、跨幣別對帳、實際現金部分收付與失敗重試 | `backups/accounting_cash_20261110_104729` | `ri-backend:before-accounting-cash-20261110_104729`／`ri-frontend:before-accounting-cash-20261110_104729` | 107 組 API、270 項整合畫面＋43 項 Accounting；既有金額、收付、文件指紋一致，無資料轉換／migration |

| 11-10 | Oversea Effective Date 取號與 Yageo TW Ref. 更正，保留舊提醒週期 | `backups/oversea_effective_ref_20261110_145449` | `ri-backend:before-oversea-effective-ref-20261110_145449`／`ri-frontend:before-oversea-effective-ref-20261110_145449` | 108 組 API、272 項畫面；原單、2 筆 T3 與批單草稿一致，金額／日期／歷史／附件不變 |

| 11-10 | Accounting 兩個彈窗補日期、識別順序與清單統一（純顯示） | `backups/accounting_dialog_date_20261110_150012` | `ri-frontend:before-accounting-dialog-date-20261110_150012` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 49 項通過；後端與資料庫容器不變，無資料寫入 |

| 11-10 | Accounting Record Selected 整體欄寬壓縮（純版面） | `backups/accounting_payment_compact_20261110_151700` | `ri-frontend:before-accounting-payment-compact-20261110_151700` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 78 項通過；後端與資料庫容器不變，無資料寫入 |

| 11-10 | Accounting Cash Amount 欄寬縮窄（純版面） | `backups/accounting_cash_narrow_20261110_152228` | `ri-frontend:before-accounting-cash-narrow-20261110_152228` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 81 項通過；後端與資料庫容器不變，無資料寫入 |

| 11-10 | Accounting Cash Amount 欄寬縮窄（純版面） | `backups/accounting_cash_tight_20261110_152756` | `ri-frontend:before-accounting-cash-tight-20261110_152756` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 81 項通過；後端與資料庫容器不變，無資料寫入 |

| 11-10 | Accounting 收付方向間距與金額同行顯示（純版面） | `backups/accounting_cash_inline_20261110_153917` | `ri-frontend:before-accounting-cash-inline-20261110_153917` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 84 項通過；後端與資料庫容器不變，無資料寫入 |

| 11-10 | Facility 選填、固定 Interest、Property QS 與 Great American 再保人 Tax | `backups/facility_input_20261110_164509` | `ri-backend:before-facility-input-20261110_164509`／`ri-frontend:before-facility-input-20261110_164509` | 109 組 API、完整畫面及 Facility 13 項、實際 Word；無 migration |

| 11-10 | 每週 Debug＋優化：舊案清單頁碼上限、Great American 稅率依名稱比對、舊案網址無 W002 警告、Accounting 舊案歷史快取、nginx 記錄回應時間、畫面測試併入 L | `backups/debug_fixes_1110_20261110_190455` | `ri-backend:before-debug-fixes-1110-20261110_190455`／`ri-frontend:before-debug-fixes-1110-20261110_190455` | 候選映像 111 組 API、272 項畫面（含 L）；正式資料 Accounting 回應逐位元組相同；無 migration、無資料寫入 |

（回復映像標籤指 `ri-backend:` 與 `ri-frontend:` 兩個映像。「有」表示當次有備份但原紀錄未寫檔名。完整驗證細節見封存的變更紀錄。）

## 近期變更

- 2026-11-04：System Guides 與 Document Templates 新增全體共用拖拉／鍵盤排序、持久保存及衝突保護。

- 2026-11-03：文件整理——改為依主題的現行規則；舊變更紀錄封存到 `docs/archive/VM-RULES-CHANGELOG-2026.md`；刪除「2026-09 規則決定（Alpha 對照）」表。
- 2026-11-03：移除 Treaty 部署（migration cases.0009）。

- 2026-11-03：Master Data Management 整合 Insured；完整中文組合忽略成員排列，Case 改組合改連結、真正更名留歷史；台北時間到秒。

- 2026-11-03：Insured 僅在成功 Announce 登錄；公告後改名須分類確認，任一部分 Confirmed 需走批單；舊資料待確認且不計正式筆數，頁面唯讀。

- 2026-11-03：System Guides 新增 Insured 清單（1,758 筆），隔離 89 組及指南下載／權限／回收筒檢查通過；備份 `backups/insured_guide_20261103_154603`，回復映像 `ri-backend:before-insured-guide-20261103_154603`。

- 2026-11-03：依業主更正，Insured 參考清單只刪除各名稱尾端指定字眼；4,396 筆整理為 1,752 筆，保留原名與刪字明細。

- 2026-11-03：依業主選定 15 組保留名稱，Insured 人工名單由 1,752 筆整理為 1,736 筆；未確認組合保留待查，附人工原名與統一名稱明細。

- 2026-11-04：舊 Insured 名單匯入 1,732 筆（新增 1,730、沿用 2，排除 4 筆），列待確認；備份 `backups/insured_legacy_import_20261104_092626`。
- 2026-11-04：Accounting四分頁、財會對帳批次、跨案淨額收付／純抵銷、整筆沖回重登、各家獨立鎖定與原匯率Production更正；已部署並核對正式來源。
- 2026-11-04：部署確認規則放寬——小改（參考檔／指南、純畫面文字版面、不改結果的效能優化、修既有規則 bug）測試通過即部署、事後告知；migration、正式資料寫入、新規則／金額會計、設定與帳號仍須先問（§3）。
- 2026-11-04：部署前測試範圍改為依影響範圍分級——局部修改只跑相關測試組＋畫面 A 階段；碰到共用部分才跑全部；不確定先問業主；每週三 Debug 補跑全部；只加減選單選項或改文字也算局部（§3）。

- 2026-11-05：CGL Coverage 新增獨立選項 Products Liability，位於 Products & Completed-Operation Liability 與 Personal & Advertising Injury Liability 之間；同步前後端選項與文件文字。

- 2026-11-05T10:35:30+08:00：Case key-in 暫時只開放 QS＋Property／CGL；僅限畫面選項與操作入口。後端支援維持，無migration。

- 2026-11-05T10:49:55+08:00：Case Class 依指定九類順序排序；目前仍只開放 Property／CGL，不改主檔或後端。

- 2026-11-05T10:57:16+08:00：Fine Art 排在 Jewelers Block 之後、Terrorism 之前；Class 開放範圍維持 Property／CGL。

- 2026-11-05：新增 Oversea Business／Fine Art、Terrorism 的簡化輸入、直接 Brokerage T3、實際收付款日減 10 天 Accounting Date；不生成文件，不影響一般 QS。部署狀態以部署與回復紀錄為準。

- 2026-11-05：Oversea Business 補上 Insured (EN/CN)、Policy Period 與 AE；畫面 Reinsurance Structure 統一改名 Reinsurance Type。分期與批單另階段處理。

- 2026-11-05：Accounting 四分頁主表增加頂部同步橫捲軸，表身最高 65% 視窗（240–720px），固定表頭、右側捲軸常駐；只調整版面。

- 2026-11-05：修正 Oversea Business 的 Account List 與案件頁首名稱，優先顯示已填 Insured (EN)；未填名稱才顯示 Oversea Business。

- 2026-11-05：Accounting 四分頁主表增加頂部同步橫捲軸，表身最高 65% 視窗（240–720px），固定表頭、右側捲軸常駐；只調整版面。

- 2026-11-05：Accounting 的 Transaction／SoA／TW Ref 與勾選欄固定左側，使用不透明底色遮住捲動資料；手機識別欄縮為180px。

- 2026-11-05：依業主確認，Oversea 所有列出的輸入欄位均為 Announce 必填；補上中英文被保險人、Policy Period 起訖日及 AE 的前後端檢查與必填標示。TW Ref. 與 Accounting Date 仍自動產生。

- 2026-11-06：Dashboard 移除頂端重複缺匯率提醒；Accounting · Receivable / Payable 保留 Awaiting FX，金額與匯率邏輯維持。

- 2026-11-06：依業主決定，Dashboard 的顯示、查詢與資料整合列局部修改，只跑相關測試，不因涉及 Dashboard 就跑完整回歸；已修正 §3 分級。
- 2026-11-06：Dashboard 增加近五年年度選擇與左右並排年度柱狀圖；保留目標折線，縮短缺匯率及五年帳款說明。

- 2026-11-06：已部署Accounting五分頁、Open／Settled顯示、篩選、跨頁全選、彈窗移除列與選填證據、同對象同幣別整批對帳及SoA／日期顯示；保留最新Dashboard年度圖表。
- 2026-11-06：新增 §3「Docker 映像保留」規則與 `scripts/docker_cleanup.sh`，每週三 03:30 自動清理超過 7 天的非回滾映像與建置快取（VM 空間整理）。
- 2026-11-06：2026-10-01～10-29 的備份（237 項，177M）已打包為 `backups/archive_20261001-20261029.tar.zst`（66M，逐位元驗證一致）；紀錄表中這些 `backups/...` 路徑需先解壓：`tar -I zstd -xf backups/archive_20261001-20261029.tar.zst -C backups <路徑>`。

- 2026-11-06：業主核准 Oversea 比例分期與正負 Brokerage 批單部署；保留最新 Accounting、Dashboard 及 Docker 映像清理規則。

- 2026-11-06T19:59:35+08:00：修正批單 Reinsurer Ref. 被前端停用的問題，直接開放輸入與修改；維持原本人工填寫、不新增原單號碼自動繼承。公告後仍用 Case SoA／Accounting 的 Edit references，既有權限及對帳／財務狀態不變。測試通過後依既有規則bug修正流程部署。
- 2026-11-07：新增 §3「開發工具舊版本清理」：`scripts/tools_cleanup.sh` 每週三 03:35 自動清理工具舊版本與 `/tmp/ri-*` 舊暫存（VM 空間整理）。
- 2026-11-07：每週 Docker 與開發工具清理改為每週三 06:00（台灣時間）依序執行。
- 2026-11-08：§3 新增「測試版本」：部署前測候選映像（最新已部署版本＋本次修改，測過即部署同一組映像）；每週三 Debug 測最新已部署正式版。`run_isolated_qa.sh` 新增 `QA_BACKEND_IMAGE` 選項（指定映像、用其內建測試組）。
- 2026-11-08：新增 §3「實作前確認」——所有修改（含小改、bug 修正）動工前都先向業主說明需求理解、做法、影響範圍、分類與測試範圍，確認後才實作；部署前是否要問仍依必問／小改規則。

- 2026-11-09：依業主確認部署舊案專區唯讀版，匯入 Swiss Re 歷史交易 3,693 筆；F13333 排除；歷史已對帳／已結清；新增、更正及收付寫入未開放。

- 2026-11-09：業主核准先備份後部署 Oversea Broker Note 必要附件；已整合最新正式舊案唯讀版，完成回歸、備份與部署。

- 2026-11-10：業主確認部署 Legacy Data (Old Register) 新增批單／理賠、原幣收付及批單 Production；既有 3,693 筆歷史唯讀不重算，受保護業務金額更正留下一階段。

- 2026-11-10：依本 session 業主核准部署 Accounting 現金收付改版；同對象跨幣別整批對帳、各幣別及方向分開實收付、全部現金帳款允許部分收付、停止新增抵銷、失敗列重試防重複；Oversea 收齊後歸 Brokerage。保留最新舊案新增收付與 Oversea 功能，既有金額與收付歷史未改寫。

- 2026-11-10：業主核准 Effective Date 取號及 Yageo 原單與兩筆 T3／批單草稿的關聯編號更正；已整合最新舊案及會計版本，完成驗證、備份、部署與 Yageo 更正。

- 2026-11-10：Accounting 的 Finance account review／Record Selected 補顯示與主清單相同的日期，識別資訊同序；純前端顯示修正，未更動日期計算、帳款或收付。

- 2026-11-10：Accounting Record Selected 壓縮所有欄寬及留白、長文字換行；僅改版面，不改帳款或收付。

- 2026-11-10：Accounting Record Selected 的 Cash Amount 欄寬縮至 125px，驗證八位數金額可完整顯示；不改帳款或收付。

- 2026-11-10：Accounting Record Selected 的 Cash Amount 欄寬縮至 105px，驗證八位數金額可完整顯示；不改帳款或收付。

- 2026-11-10：Accounting Record Selected 減少 Direction／Outstanding 留白，Cash Amount 幣別及數字改同行顯示。

- 2026-11-10：依業主確認部署 Facility 共通欄位、Property QS 畫面及 Great American 再保人 Tax 規則；續保 0%，批單沿用來源稅率。

- 2026-11-10：每週 Debug＋優化（業主確認部署）：舊案清單頁碼超大時回空白頁（原本伺服器錯誤）；已公告案件的 Great American 原稅率改依再保人名稱比對（調換／刪除其他再保人不再誤擋，新原單／續保仍固定 0%）；舊案網址寫法調整（網址不變）；Accounting 舊案歷史結果快取（逐位元組相同）；nginx 記錄回應時間；`run_ui_test.sh` 完整執行加入舊案 L 專項。
