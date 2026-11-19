# VM 規則與維運（RI System）

VM（`/opt/ri-system`）是再保部系統的**正式系統與唯一規格**。本文件只寫**目前有效**的規則，依主題整理；2026-11-03 起取代原本「只增不刪」的寫法。

- 2026-10-05～2026-11-03 的 139 段變更紀錄原文封存在 `docs/archive/VM-RULES-CHANGELOG-2026.md`（逐字保存，不再修改）；想知道某條規則的由來時去那裡查。
- 2026-11-17 整併：2026-11-10 以前的部署與回復紀錄、近期變更，以及已失效的歷史說明與改寫前的原文，逐字移到 `docs/archive/VM-RULES-HISTORY-2026-11.md`。
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

- **Frontend**：`package.json` 精確版本＋`package-lock.json`，`node:22-alpine` 以 `npm ci` 建置。Word 產生程式在 `frontend/public/alpha-documents/`（`docx-templates.js`、`vm-docx-generator.js`），不經 Vite 打包。前端拆檔（2026-11-13）：第三方套件獨立成 `vendor-*` 檔（內容不變時檔名不變，部署後沿用瀏覽器快取），各頁面由 router 動態載入、各自成檔，登入頁留在主檔；部署後舊分頁載入已不存在的頁面檔時，自動整頁重新載入到目的頁（只重試一次）。
- **Backend**：`requirements.txt` 精確版本，基底 `python:3.13-slim-bookworm`。gunicorn **4 個 worker**（= CPU 核心數；不可用 `--threads`，壓測時會撐爆記憶體）。Admin Panel 是唯讀 Django admin（`/admin/`，只有 System Administrator）。
- **Nginx**：`nginx:1.28-alpine`（與前端靜態檔同映像）；JSON／JS／CSS 啟用 gzip；轉發逾時 60 秒；`/static`、`/assets` 帶 nosniff 與 X-Frame-Options；SPA HTML 用 no-store、no-referrer；access log 遮蔽密碼重設 token。`/alpha-documents/`（Word 產生程式，不帶雜湊檔名）為 `Cache-Control: no-cache`：瀏覽器可保存但每次使用前以 ETag 確認，未更新回 304（2026-11-13）；SPA HTML 仍為 no-store、`/assets/` 仍為 immutable。
- **MySQL**：`compose.yaml` 固定映像摘要（不用標籤）；`innodb_buffer_pool_size=512MB`；`sort_buffer_size=2MB`（2026-11-16 業主決定，以 `SET PERSIST` 設定、存在資料庫的 `mysqld-auto.cnf`，不在 `compose.yaml`；重啟後保留。查詢：`SELECT @@global.sort_buffer_size`；還原：`RESET PERSIST sort_buffer_size`）。網站以最小權限的 `ri_runtime` 連線（多數表沒有 DELETE；Audit 表只有 SELECT／INSERT）；維護用 `ri_app`。例外（2026-11-13 業主決定，見 §4.5）：`ri_entity_snapshots` 另有 UPDATE 權限，由 trigger 限制只能覆蓋「案件仍是 Draft 的 draft_updated 副本」；DELETE 仍一律禁止，`ri_audit_log`／`ri_legacy_audit` 不變。
- **主機**：時區 Asia/Taipei（提醒排程 cron 依賴它）。硬體：Xeon E5-2620 v3、VMware 4 vCPU／8 GB；單一請求吃單核，換新一代 CPU 才會明顯變快。
- **PDF 已退役**：只產生 Word，PDF 由使用者在 Word 匯出；Gotenberg 已移除，`/api/render-document-pdf` 已整個移除（2026-11-12 起回 404，§16）。
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
| 清理過期登入紀錄 | `scripts/install_session_cleanup_cron.sh`（`--remove` 移除）：每天 05:40 執行 `manage.py clearsessions`，只刪已過期的 `django_session`，紀錄在 `logs/session-cleanup.log`（2026-11-13） |
| 提醒排程 | `scripts/install_reminder_cron.sh`（`--remove` 移除）；手動：`manage.py run_signed_slip_reminders`／`run_payment_reminders [--today YYYY-MM-DD]`；紀錄在 `logs/reminders.log` |
| 唯讀資料檢視 | `/admin/`（System Administrator）。新增 model 要在 `admin.py` 用 `ReadOnlyModelAdmin` 註冊 |
| 補分期案件缺少的保費交易 | `manage.py backfill_installment_transactions [--apply]`（先 dry-run，備份後再 apply） |
| 舊帳修復（92 項會計規則） | `manage.py apply_accounting_review` 預覽 → `--apply --expected-signature <signature>` |
| TWD 保費一次性轉整數 | `manage.py convert_twd_premiums [--apply]`（預設 dry-run；可重複執行） |

**測試方式**
- **資料庫／API 測試組**：一律用 `scripts/run_isolated_qa.sh [測試組 …]`（隔離 MySQL＋後端、`ri_runtime`＋db_harden、每組全新資料庫、自動清除；全部約 2 小時，目前為 133 組）。**不要在正式容器跑**（正式 Audit 暫停，測試會失敗）。`KEEP=1` 保留環境除錯；`QA_BACKEND_IMAGE=<映像>` 改測指定映像（不重建，用該映像內建的測試組），見下方「測試版本」。
- **前後端合計、密碼規則一致性**：`scripts/run_qa.sh totals`／`parity`（`run_qa.sh` 已不再跑測試組）。
- **Accounting 伺服器分頁一致性**（2026-11-17）：`scripts/run_qa.sh pages`——以正式資料（唯讀）取伺服器各分頁，與畫面原本的程式（`accountingRows.js`、`accountingList.js`，node 執行）逐頁比對；約 2 分鐘。`PAGES_BACKEND=<容器>` 改用其他後端（例：壓測環境）。
- **畫面測試**：`scripts/run_ui_test.sh`（無頭 Chromium，用完即丟的環境）。13 個標準階段 A H R B0 B K C D E F G P1 P2，共 206 項；另有專項（完整執行時一併跑）：Oversea Business O 29 項＋分期／批單 26 項、舊案 L 20 項（自動準備舊案測試資料）、Accounting 載入失敗 X 9 項、舊資料網頁匯入 I 9 項、Accounting 伺服器分頁 Y 24 項（2026-11-17 改寫；先準備 160 筆合成的已結清舊資料歷史）、前端拆檔與快取 Z 14 項（2026-11-13）、主資料重新啟用 M 11 項（2026-11-16）、人員頁帳號操作 U 10 項（2026-11-17），合計 374 項。`UT_BACKEND_IMAGE`／`UT_FRONTEND_IMAGE` 指定測試映像（預設是正式映像，可能比原始碼舊）；`PHASES="A H"` 只跑部分（要從 A 開始）。測試切換登入身分前等待應用 API 完成，不等待預覽 iframe 的外部資源；保留全部 console 錯誤檢查。
- **Legacy 網頁匯入 I 專項**（2026-11-11）：`qa/ui/legacy_import_ui.py`，完整執行時一併跑（`run_ui_test.sh` 預設階段加 I）；API 另有 `legacy_import_web` 測試組。
- **前端檢查**：`frontend/scripts/check_*.cjs`（`check_endorsement_notes.cjs` 需在建置映像內執行，因為要 jszip）。
- **壓力測試**：`qa/stress/`（1 萬件案件；結果在 `qa/stress/RESULTS-*.md`）。
- **實作前確認（2026-11-08 業主決定，所有修改都適用，含小改與 bug 修正）**：動工前先向業主說明——理解的需求、預計做法、影響範圍、屬於必問或小改、預計的測試範圍；業主確認後才開始實作（業主在指示中明說「直接做」即視為已確認）。實作中發現做法或範圍需要改變，先停下再問。
- **部署流程（2026-11-17 起，2026-11-11 業主決定）**：實作前確認（含部署同意）→ 實作 → 測試通過 → 備份資料庫（有 migration 再加文件 volume）→ 標記回復映像 → 部署 → 核對正式程式與原始碼逐檔一致 → 在「部署與回復紀錄」加一列 → 回報業主（跑了哪些測試與結果、部署時間、回復方式）。測試通過後不再另問是否部署。
  - **例外：遇到下列任一情況，停下來問業主，不直接部署**：(1) 測試沒有全部通過，或實際跑的測試比確認時說的少；(2) 實作中做法或範圍有變（原本就要先停下再問）；(3) 會寫入或修改正式資料（匯入、`--apply` 指令、清除資料；回復映像救不回，只能還原資料庫備份）；(4) 部署時正式版已不是候選映像的基礎版本（其他 session 先部署），要重建候選並重測後再問。
  - **測試範圍（依影響範圍分級，2026-11-04 業主決定）**：
    - **只更新參考檔／指南**（應用程式碼不變）：跑相關檢查即可。
    - **局部修改**＝只改單一分頁／單一功能，且沒有碰到下列「共用部分」：跑該功能相關的 API 測試組（例：System Reference Data 排序 → `reference_order`）＋前端建置成功＋畫面測試只跑 `PHASES="A"`（登入與基本畫面），該分頁有對應畫面階段再加跑該階段。**不要**跑與修改無關的測試組（例：改 System Reference Data 不跑 Accounting、Production、Case 相關測試）。
    - **共用部分**＝金額計算與取位、會計（收付、對帳、SoA、Accounting、Production）、案件建立／儲存／驗證／批單、權限／登入／帳號、資料庫結構（migration）、Word 文件產生、多個分頁共用的前後端程式（如 API 呼叫、路由、共用元件、共用設定）。碰到任一項：跑全部 API 測試組＋全部畫面測試。
    - **選項或文字增減也算局部**：只在某險種／某分頁的選單或清單加減選項、改顯示文字，且不改金額計算、檢查規則或資料結構（例：CGL 承保項目加 Products Liability）——即使該清單會被案件儲存或 Word 文件讀到，也算局部修改：跑該險種／分頁相關測試組＋`document_generation`、`qs_documents`（清單會進 Word 時）＋`cases_api`＋畫面 `PHASES="A"`。
    - **Dashboard 的顯示、查詢與資料整合（2026-11-06 業主決定）**：Dashboard 只是抓取與整合既有資料供同仁查看，屬局部修改；跑 Dashboard／此次查詢相關 API 測試、前端建置與畫面 A＋G（以及本次變動的操作與顯示檢查）即可，不因涉及 Dashboard 就跑全部 API 或全部畫面回歸。實際更改共用金額計算、會計寫入／收付／對帳／Production 規則、權限或資料庫結構時，才依實際影響套用共用部分的測試範圍。
    - **不確定**會不會影響其他功能時：先問業主要測多少（不要自行決定）。
    - **安全網**：每週三 Debug 時跑一次全部 API 測試組＋全部畫面測試。
    - 回報時寫明這次跑了哪些測試、為什麼這樣選。
  - **必問**（在實作前確認時講明風險並問部署時段，測試通過即部署，例外見上）：有 migration 或改資料庫結構；會寫入或修改正式資料（匯入、`--apply` 指令、清除資料）；新規則或改金額／會計；設定開關與帳號（寄信、Audit、排程、權限、帳號）。
  - **小改（測試通過即直接部署，事後在回覆中告知業主）**：只更新參考檔／指南；純畫面文字與版面（不改欄位、驗證、金額或資料）；不改結果的效能優化（回應比對逐位元組相同）；修正程式與本文件既有規則不符的 bug（不含新規則）。小改仍要備份、標記回復映像並寫入部署紀錄。
  - 同時符合小改與必問時，以必問為準；不確定屬於哪一類就先問。
  - **測試版本（2026-11-08 業主決定）**：
    - **每週三 Debug** 的全部 API＋全部畫面測試，對象是**最新已部署的正式版**：`QA_BACKEND_IMAGE=ri-backend:local scripts/run_isolated_qa.sh`（用正式映像內建的測試組，題目與程式同版）＋`scripts/run_ui_test.sh`（預設即正式映像）。
    - **部署前測試**的對象是**這次要部署的候選映像**＝以最新已部署版本為基礎＋本次修改建置的 `ri-backend`／`ri-frontend`。API 測試用 `QA_BACKEND_IMAGE=<候選後端映像> scripts/run_isolated_qa.sh …`；畫面測試必須用 `UT_BACKEND_IMAGE`／`UT_FRONTEND_IMAGE` 指定同一組候選映像（不可用預設的正式映像）。部署時直接部署測過的那組映像，不重新建置；回報寫明測試用的映像名稱。
    - 候選映像若含其他 session 尚未完成的修改（`git status` 有不屬於本次的變更），先問業主是否一起部署，不要自行帶上線。
- **Docker 映像保留（2026-11-06 業主決定；2026-11-12 修訂回滾點）**：`ri-*` 自建映像一律保留——容器使用中（含已停止）、7 天內建立或 tag 日期在 7 天內、本文件／腳本／compose 有寫到（`before-*` 回滾點除外）；其餘可刪。**`before-*` 回滾點**：7 天內全部保留，另外 `ri-backend`、`ri-frontend` 各自不論多舊至少保留最新 10 個（`ROLLBACK_KEEP_MIN`）；超過的每週清理時刪除，即使「部署與回復紀錄」有寫到——更舊的版本改由版本紀錄（Git）重建，資料由備份還原。第三方映像（mysql、nginx、node、python…）不自動刪。清理用 `scripts/docker_cleanup.sh`（預設預覽，`--apply` 才刪；`KEEP_DAYS` 可調），同時清超過 7 天的建置快取與 dangling 映像。每週三 06:00（台灣時間）由 parkle 的 crontab 自動執行，紀錄在 `logs/docker-cleanup.log`。不要用 `docker system prune -a` 或 `docker rmi -f`。
- **大型測試時段與記憶體（2026-11-10 業主決定；2026-11-11 修訂）**：VM 只有 8 GB，測試與正式系統共用。同仁正式使用系統前，壓測（`qa/stress/`）、全部 API／全部畫面測試等大型測試不限時段；正式使用後改在下班後執行（開始正式使用時由業主告知，再更新本條）。跑完檢查 `free -m`，有 swap 時在空閒記憶體大於 swap 用量的前提下執行 `sudo swapoff -a && sudo swapon -a`，把正式系統搬回記憶體（約數分鐘，網站不停）。用不到的測試環境要停止（不刪除）。
- **備份保留（2026-11-12 業主決定）**：`backups/` 內 14 天內的備份全部保留。超過 14 天的：每天保留最後一份，以及所有在「改資料庫結構（migration）、匯入、清空或批次寫入正式資料」之前拍的備份；其餘刪除，保留的打包成 `backups/archive_<起>-<迄>.tar.zst`（打包後逐位元驗證再移除原檔，取用時 `tar -I zstd -xf … -C backups <路徑>`）。每週三 Debug 時把剛滿 14 天的備份列出保留／刪除清單，業主看過才刪。已處理：9 月 18 個檔案 → 保留 13 個於 `archive_20260921-20260929.tar.zst`、刪除 5 個（匯入文字紀錄、2 份變動後快照、`before_pin`、空的文件壓縮檔）；10 月 `archive_20261001-20261029.tar.zst`（未刪）；2026-11-16 依業主決定刪除 10-30 的 5 份部署前備份（cgl_aggregate_retroactive、endorsement_sections、allianz_reminder、endo_note_order_percent、case_keyin_ui；當天沒有保留任何一份，前後最近為 10 月打包檔與 11-02 `case_keyin_refinement`）。
- **每週健檢報告（2026-11-13 業主決定）**：`scripts/weekly_health.sh`（唯讀；`--no-log` 只印出，否則附加到 `logs/weekly-health.log`）。每週三 Debug 時執行並向業主報告：主機記憶體／swap／硬碟、容器、映像與備份數量、最慢的 10 個 API（nginx `urt`，容器重建後重新累計）、案件與舊資料筆數、資料庫大小，以及 Accounting 畫面實際使用的四個請求（打開時的清單、All Accounts／Settled/Closed 第 1 頁、下拉名單）各量第一次與第二次的時間與大小（2026-11-17 起；跳過「須先改密碼」的帳號）。Dashboard 或 Accounting 打開超過約 3 秒時提出優化選項（含 `~/RI System/perf-work/round3-20261110` 未部署的共用快取）。
- **工作資料夾（2026-11-12）**：`~/RI System` 內已上線功能的 16 個工作資料夾（accounting、legacy、oversea、stp、nav-icons、property-qs-currency、data-clear…）已打包為 `backups/work-folders_20261112.tar.zst`（14,925 個檔案，逐檔比對一致後移除原資料夾）；含 STP Word 視覺檢查用的 LibreOffice 執行環境（`stp-work/tools/`，需要時解壓）。`RI-docs`（決策文件）與 `perf-work`（未部署的共用快取）保留原處。
- **開發工具舊版本清理（2026-11-07 業主決定）**：`scripts/tools_cleanup.sh`（預設預覽，`--apply` 才刪）每週三 06:00 接在 Docker 清理之後由 parkle 的 crontab 自動執行，紀錄在 `logs/tools-cleanup.log`。清 parkle 家目錄內 Codex、Claude Code、VS Code 伺服器與擴充套件的舊版本、VS Code 擴充安裝檔快取，以及 `/tmp/ri-*` 暫存；一律保留執行中、目前版本、最新版本與 7 天內的項目，工具正在更新時跳過。不處理其他帳號（如 olin1）。

**開發注意**
- `frontend/src/views/CaseWorkspace.vue` 與 `case-workspace.script.js` 直接維護（舊的產生器已不存在）。
- 金額語意刻意重現 JavaScript 的數字規則（`backend/cases/calc/jsnum.py`）讓前後端一致，不要改成 Decimal。文字以 UTF-16 單位截斷、JSON 大小上限 250000、Clause 代碼排序用 ICU 規則（符號 < 數字 < 字母；非 ASCII 符號尚未對照）。
- 多個 session 可能同時改 `/opt/ri-system`：commit 只加自己的檔案（不用 `git add -A`），部署前比對正式映像。

---

## 4. Case：建立與共通欄位

### 4.1 結構與險種

- **Insurance Type（2026-11-05）**：Case key-in 最上方原 Class 標籤改為 Insurance Type，提示文字同步調整。只是畫面名稱；沿用 classOfBusiness 資料、既有選項與排序，Account List／其他頁面的 Class 名稱維持。
- **Class 選單固定顯示順序（2026-11-05）**：Property → Personal Accident → Commercial General Liability → Product Recall → Marine Cargo → Stock Throughput → Electronic Equipment → Jewelers Block → Fine Art → Terrorism。僅顯示目前已開放及有效的選項；QS 顯示 Property／Commercial General Liability／Product Recall／Stock Throughput，依上述順序排列；Oversea Business 顯示 Fine Art／Terrorism。未列入的新類別排在上述順序之後；Product Recall 沿用原未被案件引用的 Products Recall／PR 主檔身分並更名。
- **Case key-in 提供 Quota Share（QS）及 Oversea Business。** QS 提供 Property／Commercial General Liability／Product Recall／Stock Throughput；Oversea Business（儲存代碼 `OVERSEA`）的 Class 僅限 Fine Art／Terrorism。後端保留既有 QS／XOL 支援，歷史 FACULTATIVE 視為 QS；不清理主檔、不轉換案件。Oversea Business 的獨立規則見 §4.8。
- **系統沒有 Treaty**（2026-11-02 完整移除；儲存 TREATY 被拒絕；資料庫 CHECK 只接受 FACULTATIVE／QS／XOL／OVERSEA）。
- 新增／編輯表單最上方同一張卡片先選 **Structure 與 Class**（可任意順序）；兩項都選了才顯示其他區塊與儲存／Review。清除任一項只隱藏下方內容，已填資料保留。
- Type 一般由「自填前綴＋結構後綴」組成：QS = Facultative Reinsurance，XOL = Excess of Loss Facultative Reinsurance（後綴鎖定，改結構才會變）；Product Recall 固定為 Product Recall Facultative Reinsurance。

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
- Currency TWD（CGL QS、Swiss CGL QS 與 Product Recall QS：只提供 TWD／USD，預設 USD）；New／Renew 預設 New。
- Cedant 與再保人 Tax 預設 1%（AUW Tax 固定 0%）；Case Owner 與 AE 見下方。
- Effective Date 選定後帶入一年後的 Expiration Date（閏日帶翌年 2/28）；手動改過或既有非空值不覆寫。時間選項 12:00／00:00，預設 12:00；**手動改 Effective 時間會同步帶入 Expiration 時間**（Expiration 仍可另選；讀取舊案不強制）。
- Cedant Collection Days 預設 90（可改）；Property、CGL QS 與 Product Recall QS 新增一般再保人時付款天數預設 90（可改）。Facility 的 Cedant 天數固定 90（原單／續保；批單沿用來源）。
- 新案以 Cedant 自己的天數算 Cedant 帳款（`cedantTermsBasis=case`，由伺服器保留）。
- **Case Owner／AE（2026-11-14）**：所有險種及 Oversea 的新案、續保、批單草稿均由建立者預帶兩欄，可獨立改選在職 General Manager／Reinsurance Staff／System Administrator 的 Personnel；新選不檢查帳號狀態，但建立者仍須符合資格與原有建案權限。General Manager 及 System Administrator 可依權限修改 Owner。Review／Announce 前 AE 須有有效 Email；已關聯者使用 Personnel Email，未關聯歷史值使用案件原有效 Email 並提示。草稿顯示現名，公告後保留案件歷史姓名，Production 歸屬依 Personnel ID。
- **歷史人員與提醒**：既有名稱保留；唯一名稱可建立歷史關聯，重名或無對應不猜測。符合權限者可手動確認或更正，姓名不同或更正既有關聯須填原因，保留前後、人員與時間。離職或停用帳號者不接收自動提醒，其他有效收件人仍可收到。Account Executive MDM 入口及新增／修改 API 停用，歷史主檔保留。2026-11-14 唯一對應的 12 筆既有案件 AE 已回填、留存快照。

### 4.4 共通驗證
- 期間：Expiration 必須晚於 Effective（Property、CGL QS 與 Product Recall QS 不接受同日）；所有原單、續保與改期後的完整期間**最長 18 個曆月**（剛好上限可以；月底按曆月末日）。
- 付款天數：有填或正式檢查時，必須是至少 15 的整數。每期 Cedant 及每期每家一般再保人天數各自獨立填寫（不繼承），缺漏列「待確認」且不能收付。
- **Premium Installments**：啟用時至少兩期（儲存即檢查，零期／一期拒絕）；一般批單不能分期，Oversea 依 §4.8。CGL QS 另有：第一期 Payment Base Date／Performance Month 預帶 Effective Date，各期預帶 Case 與各再保人天數，每期保費合計須等於 100% Premium。
- **Property QS 幣別**（含 Facility 與批單，2026-11-12）：只允許 TWD 或 USD；新 Draft 可留空，Review／Announce 必填。既有其他幣別須改為 TWD 或 USD 才能儲存（含自動儲存）；不自動換算金額或歷史交易。批單幣別繼續沿用來源及既有帳務鎖定規則。
- **TWD 保費**（Case 100% Premium、每家再保人、每期）只准整數，前後端擋小數，不偷偷取整；USD 兩位小數。
- **Order Hereon**：新填或修改時每家 > 0、≤ 100%、最多 8 位小數，合計 ≤ 100%；未修改的歷史比例保留。
- **Loss Record**：一般及 Swiss CGL QS、Product Recall 的年數、Broker Advised Date 與明細日期／原因／金額缺漏可暫存草稿，於 Review／Announce 檢查；已輸入的無效值仍於儲存時擋下。New 可填 0 年、投保時手動明細須為空；Renew 至少 1 年。其他一般保費 Case 沿用儲存時檢查，Oversea 依 §4.8。Product Recall 手動明細金額須大於 0，Claim 自動明細與續保快照例外見 §7.3；Additional Loss Record Notes 輸入已隱藏（舊資料保留）。
- **Performance Split**：兩方合計 100% 時 b 方 = Leg 總額 − a 方，交易合計與排程分毫不差。CGL QS：預設關閉，啟用後一位 Reinsurance Staff、一位 Other Staff，只允許 40/60 或 70/30。
- **案件附件上限**：Property 案件 30 MiB，其他險種 10 MiB；自動生成的 Word 與 Placing Slip 上傳 30 MiB。手動附件每案最多 50 份（自動生成文件另計）。可上傳格式含 .xlsx／.xls。
- **案件文件只有 Draft 能刪**；Announce 後刪除回 409。案件與主檔永不實體刪除（回收桶 5 年內可還原）。

### 4.5 Draft 自動儲存與原始輸入
- 適用：Property QS、CGL QS（含 Swiss CGL QS）、CGL XOL，以及所有臨分批單 Draft。Structure／Class 都選定後才啟動；系統預填不會觸發建案。
- 人工修改後離開欄位即自動儲存；缺漏、格式錯誤、未完成數字／日期、尚未加入的條款文字都保留原文（`draftInput`／`pendingClause`），重開或重新整理可還原。
- Review／Announce 及文件仍執行完整檢查；Announce 成功後移除草稿原文。帶有草稿原文的修正案須重新 Announce 才能產生文件。
- 新案首次儲存用可重試識別碼，避免重複建案；寫入依序送出並檢查 rowVersion。Announced／Confirmed／Reversed 不啟用自動儲存。
- **草稿副本只留最新一份（2026-11-13 業主決定）**：未 Announce 的草稿不受 20 年保存限制。草稿每次儲存（含自動儲存）覆蓋該案件最新的一筆 `draft_updated` Entity Snapshot（`audit.services.record_draft_snapshot`），不再逐次累積；`draft_created` 與 Announce 之後的每次修改仍逐筆保存且不可變。三層防護同步放寬到最小：程式只有該函式會更新；資料庫 trigger 只放行「entity_type=case、reason=draft_updated、識別欄位不變、且該案件目前 status=draft」的 UPDATE，案件 Announce 後其所有副本恢復不可修改；`ri_runtime` 增加 UPDATE、沒有 DELETE。2026-11-13 之前累積的舊草稿副本保留不刪，只覆蓋最新的一筆。測試 `draft_snapshot_replace`。

### 4.6 資料異常保護
- 再保人清單、分期清單或計算用數字無法解讀時，整案金額顯示 `Pending confirmation` 並列出異常；不修補、不以 0 代替、不丟棄原資料。
- 修正前，後端擋下 Announce、文件、收付款、沖回、更正、續保／批單／Reverse 與理賠操作；Dashboard／Production 註明異常案件未計入。須技術人員查明原文後修復。
- Accounting 逐案計算：單一案件無法解讀只略過並警告，其他照常。
- **金額上限（2026-11-12 業主決定）**：保費類金額——100% Premium、各再保人 Premium、分期 Premium、Oversea 的 Brokerage 與 100% Premium 增減——絕對值上限 999,999,999,999（`AMOUNT_MAX`，前後端同值）；儲存時超過即拒絕並指出欄位，未完成草稿自動儲存時保留輸入原文但不放進計算用欄位（送審時提示）。已存資料若超過上限，視同無法解讀的金額依本節處理：Account List 只標示該案件 `dataError`，其餘案件照常，該案件可由表單改正。保險金額（Sum Insured）、各種限額與賠款金額不套用此上限。
- `reinsurers`／`performanceInstallments` 不是清單時回 400 或以空白列取代，不產生伺服器錯誤。

### 4.7 條款（Clauses）
- Case 的條款 Title **持續跟隨 MDM 最新 Title**（條款主檔 → 該 Class／Reinsurer 的固定條款 → Case 自訂 Title）；開啟時、切回視窗、前景每 30 秒更新，Review／儲存／生成文件前重讀，讀取失敗則擋下載。Word 只印 MDM Title 原文，不另補代碼。
- Fixed Clause 依 Class 與 Reinsurer 帶入；Universal：LMA3333 Reinsurers Liability Clause、Intermediary Clause (TW Insurance Brokers Ltd.)。
- 人工條款加入清單時 Code 與 Name 必填。

### 4.8 Oversea Business（國外業務特殊案件，2026-11-05）
- 結構 `OVERSEA`，Class 只能 Fine Art／Terrorism；獨立簡化表單的財務必填項目為 **100% Premium、Share (%)、Brokerage 金額、Reinsurance Broker、Cedant、實際收付款日期**。Currency 隨 Premium 選定，新案預設 USD；負責人與 AE 預帶登入者，可由合格 Personnel 選擇調整。不要求一般案件的承保條件、Loss Record、條款。
- 補充 Insured (EN)、Insured (CN)、Policy Period（日期及時間）與 Account Executive。所有列出的輸入欄位均為 Announce 必填，包含中英文被保險人、保單起訖日期與 AE；Draft 可暫存未完成資料。中文被保險人沿用既有 Announce 建立正式主檔規則。Policy Period 與實際收付款日分別保存。
- **Brokerage 直接是 T3 金額**，不乘保費或 Share、不從 T1−T2 推算。100% Premium × Share 僅作分攤保費資訊。TWD 為整數，其他貨幣最多兩位小數；正佣金為向所選 Broker 收款、負佣金為付款。不建 T1／T2、零額保費排程、分績或 Claim。原單與批單可各自選擇 Brokerage 分期，比例各期 >0 且總和 100%；依貨幣精度自動分攤，尾差優先調整第一期；若該期不足以吸收，依序調整後續期，避免反向金額。每期分別填實際收付款日，分別產生獨立 T3。
- **Accounting Date＝實際收付款日期−10 個日曆天**，可跨月、跨年、閏年；實際日期原樣保留。原單 Announce 以 Policy Period 的 Effective Date 年月及 Class 代碼分配 TW Ref；實際收付款日及分期日期不影響取號；單筆 `...-R1-T3`，分期為 `...-R1-I1-T3`、`...-R1-I2-T3` 等。各期 Accounting Date 依各自實際日減 10 天；Production 依各期自己設定的 Performance Month（2026-11-13 起新案必填，既有月份保留）認列各期精確 Brokerage，關帳不重複建帳。
- 批單沿用既有最新來源與原單鏈限制，編號接原單 `-E01`、`-E02`。原單 100% Premium、Share、Currency、Broker、Cedant 與 Policy Period 沿用來源並鎖定；另填本次 100% Premium Adjustment 與 Brokerage 增減（加收正、退還負；無變動填 0）、批單生效日、說明及實際收付款日。批單保費差額乘 Share，依分期比例及貨幣精度分攤並依各期實際月份計入 Production；零 Brokerage 仍認列非零保費。每張批單可選擇單筆或分期，每期建立獨立 T3；不改寫原單分期、收付或已認列業績。未輸入保費差額的舊批單沿用零保費認列；原單保費資訊不重複計入批單保費統計。
- 不生成任何文件（畫面隱藏，後端封鎖），Announce 前須上傳並選用國外 RI Broker 提供的 Note：Original 僅接受 Credit Note；批單可用 Debit Note 或 Credit Note，不依金額正負自動決定種類。每案／每張批單獨立附件，不能沿用原單附件；未選用、已刪或檔案本體遺失均不能 Announce。不要求一般 Offer Slip／Signed Slip。Draft 可先儲存，最終須確認 Note、Brokerage 及實際日期。
- 更正 TW Ref. 後，既有提醒紀錄的主旨、內容及交易鍵原樣保留；系統依舊號與目前交易編號的對應延續提醒節奏，不重發或跳過既有週期。
- T3 是獨立佣金現金帳款，不依賴不存在的 T1／T2。未結清時在 Accounting 未對帳／已對帳清單處理；部分收付仍為 Open，全額完成才移入 Brokerage，All Accounts 始終保留。每次財務登錄可用不同實際收付款日，案件／期別日期、Accounting Date 與 Production 認列月份維持原值；不因部分收付款改動。
- 公告後更改金額、Broker、Cedant、日期等須填原因；已有有效財務覆核／收付／Production 認列時禁止直接覆寫，先依既有流程處理。一般 QS 案件不受本節影響。

---

## 5. Case：各險種專屬欄位

> 2026-10-28 起新增的 Property／CGL QS 案件，以及從舊案建立的新續保／批單，使用規則版本 `placing-qs-20261028-v1`（伺服器配置，編輯舊案不會自動升版）。下列標示「新版」的項目只適用這個版本；舊案維持原畫面與檢查。

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
- CGL QS 的 Review／Announce 必填：Original Insured (CN)、Reinsured’s Retention、Cedant Commission／Tax／Collection Days、一般再保人 Payment Terms Days（佣金與稅可為 0）；Case Owner 在 Announce 必填；AE Email 在 Review／Announce 前要求；Original Exclusions 選填。
- 一般再保人搭配 PWS Foreign RI Broker 仍用一般 CGL 表單。

### 5.2a Product Recall QS（2026-11-14）
- 獨立 Product Recall 險種，僅一般 Facultative QS，支援原單、續保與批單；流程、權限、分期、佣金、稅與帳務以一般 CGL QS 為基礎。TWD／USD，預設 USD；Cedant／再保人 Tax 預設 1%，Cedant／一般再保人付款天數預設 90。TW Ref 為 TWPR＋保單生效年兩碼＋月兩碼＋每月流水號（至少三碼），Announce 取號；批單、分期及理賠沿用既有後綴。
- Covered Events 預設 Defect、Malicious Product Tampering、Product Extortion、Government Recall；Covered Loss 預設 First Party Recall Costs、Third Party Recall Costs、Consultant and Advisor Costs、Extortion Costs。可取消或增加單行項目；範本項目依範本順序固定排列，自訂項目接在後面並保留相對順序，兩組均不提供手動排序。每類至少一項，空白列須補齊或刪除。清單內名稱去前後空白、忽略大小寫不得重複；固定項目不可更名。
- Limit of Indemnity 為案件幣別正數，文件接 each occurrence and in the aggregate。每個已選 Covered Loss 對應必填正數 Sub-limit，可另加項目；取消選擇保留金額但不檢查或輸出。所有輸出 Sub-limit 均不得超過 Limit；額外項目不可與 Covered Loss 同名。TWD 整數、USD 最多兩位小數。Deductibles 與自由文字 Self-Insured Retention 至少一項；Deductibles 有填時大於 0 且不超過 Limit，文件接 each and every Insured Event。
- Principal Address 選填；Interest 固定原單責任再保句。Retention、Original Exclusions／Conditions 與可修改的 warranties、conditions precedent、subjectivities 依已確認預設與必填規則。Choice of Law and Jurisdiction 在案件畫面隱藏，Cover Note 與 Placing Slip 固定輸出範本條文。Reinsurance Conditions 固定範本文字、LMA3333 與 Intermediary Clause，文件最後附兩項完整條文；Premium Payment Terms 使用 Cedant Collection Days 及 LSW3001 名稱，不附完整 LSW3001。
- Information 使用 CGL Policy Form、Retroactive Date、Extended Reporting Period、Territorial Limits 及 Insured Business 規則；新案預設 Occurrence Form；續保及批單沿用來源選擇，可再修改。Claims-Made 才顯示從屬資料，切換 Occurrence 隱藏且保留。Products 必填、Website 選填。Turnover 明細按幣別加總且文件保留原幣；單筆只顯示一行，各幣別 Case 幣別優先後按字母排序。CGL QS／Swiss CGL QS 文件也採同一原幣顯示規則；Overview Adj. Rate 仍依生效月匯率計算，缺匯率顯示 N/A。
- Loss Record 明細可用 TWD 及 §8.5 的 15 種外幣，各筆保留原幣；New 的 0 年無損失句為 No previous recalls or product withdrawals since start selling.，後接 Broker Advised Date。Cover Note 依 CGL 版面與已確認的 Product Recall 順序；Placing Slip 為獨立生成程式，使用相同 Product Recall 業務資料。

### 5.2b Stock Throughput（STP，2026-11-12）
- Stock Throughput 只開放一般 QS，不開放 Facility；險種／TW Ref 代碼 ST。原單採 Property QS 共通流程；100% Premium 與各再保人保費、佣金、稅率、分期及後續會計比照一般 QS，Ceding Commission 必填（0% 時 Cover Note 省略），Cedant Tax 預填 1% 並用於 T1；再保人扣除及稅率各自處理。不另設總 Sum Insured 或計算分保保額；Limit of Liability 為必填多行文字。
- STP 專有必填多行文字為 Conveyance、Voyage；Attachment and Termination、Geographical Scope、Storage、Basis of Valuation、Premium Rate 為不預填選填多行文字。Storage 與附件、HUB 無連動。Interest、Original Deductibles、Original Conditions、Reinsured’s Retention 必填；Retentions 預填 waived。Express Warranties、Conditions Precedent、Subjectivities 使用範本預設且必填可修改。Sub-Limits、Reinstatement Provisions、Indemnity Period、Co-Reinsurance Warranty、Notices、Occupation、Special Agreement 及 Insured’s Website 選填；空白不在 Cover Note 顯示。所有多行文字文件保留換行。Original Conditions 按行編號並加上既有固定結尾。Original Insured Address 手動輸入，格式比照 Property。刪除 Vessels、Situation、Additional Coverages、Aggregate Limit、Underlying Limits、Excess、Loss Payee 及 Taxes Payable by Reinsured and Administered by Reinsurers。
- Estimated Turnover 必填至少一筆，採 Combined（同一合計可分幣別）或 By company（公司名稱必填且大小寫與前後空白不區分重複）；幣別及金額必填，金額大於 0。維持可調整順序；多筆按幣別計 Total，單筆不印 Total、不印公司名稱。HUB 至少一筆，各筆名稱、完整地址、幣別、正數保額必填；不設獨立郵遞區號、不計合計。Cover Note 於 Information 後獨立起頁，跨頁重複標題。Renewal 及 Endorsement 沿用 STP 資料供修改。

### 5.3 純 Facility 案件
- **純 Facility 共通規則（2026-11-10）**：僅再保人全部為 Facility 才適用；Original Exclusions／Original Conditions 選填，Interest 固定為各險種既有預設句並在 Key-In 隱藏。混合一般再保人的案件沿用一般規則。Property QS 預設 Basis of Valuation 為 Actual Cash Value、Occupation 輸入高度縮小；Special Agreement 不供輸入且重新產生的文件不顯示，既有資料及已產生文件保留。Great American 再保人 Tax 新原單／續保固定 0%，既有保單原稅率保留，批單沿用來源稅率；Cedant Tax 不受影響。
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
- 保費為帶正負號的差額（補費正、退費負）；同張可不同再保人混合補退。**Case 與每家再保人全為 0** 才於 Announce 後直接 Confirmed 並排除 Production。一般批單單期、不可分期；Oversea 可分期，見 §4.8。
- 正式編號 Announce 才配置：Original 編號 -E01、E02…；雙編號兩邊同序號；純 AUW 只衍生 AUW 編號。
- 有較新的批單，或批單鏈上有未完成批單時不能續保（案件頁顯示原因）。

### 7.2 續保
- 所有臨分續保採**全保期平均**：同年度 Original 加已完成批單的補退費 ÷ 最新完整保障天數 × 續保天數；Case 與每家再保人各自計算、依幣別取位。
- 從最新到期日接續、預帶一年（365／366 天），可改期但最長 18 個月；改期只重算未人工修改的保費。無法推算的欄位留白並說明原因。
- AUW 續保／批單不沿用來源手動 Ref.；被保險人主檔沿用來源。

### 7.3 新系統臨分 Claim 與 Loss Record（2026-11-14）
- Product Recall、一般／Swiss CGL QS 及 STP 每筆 Claim 可選 TWD 及 §8.5 的 15 種外幣，Reserve 與所有 obligations 同幣別；Case、Accounting、Dashboard／報表依原幣分開顯示及加總，不做跨幣別換算。其他險種仍用案件幣別。
- 無付款時可改 Claim 幣別，數字不換算；已有付款且沒有收付、抵銷、結清或其歷史時，可整筆更正並填原因、留前後紀錄，須先取消相關對帳審核批次，所有付款及交易一併更新並依新幣別精度重算分配；已有收付／抵銷／結清歷史即使沖回仍永久鎖定。新幣別不允許原金額精度時阻擋，不自動取整。
- 所有新系統臨分 Claim 的 Date of Loss 可改，原因必填並保留前後日期、操作人與時間；既有付款分配及帳務不因改日期自動改動，新增或依原流程更正付款時依當時 Date of Loss 選適用版本。Product Recall Claim 不選 Covered Event／Loss，不依其狀態阻擋付款。
- 新建 Claim 的 Outstanding Reserve 須大於 0，Cause of Loss 可留空。原保期另顯示 Claim 自動明細、來源 TW Ref／Claim ID；金額為 Reserve 加 obligations 正負合計，最低 0，使用 Claim 幣別。原保期 Cover Note 保留投保時 Loss Record。續保建立時取快照，之後來源變更不覆寫；續保快照修改日期／原因同步來源 Claim，金額／幣別不回寫。同步失敗保留續保並標待同步，允許 Review／Announce，衝突逐欄由使用者決定並留紀錄；日期更正須原因，既有帳務不變。

---

## 8. 會計

> 適用一般再保人與六類 Facility 情形（一般、AUW、Allianz、Great American、QBE、Swiss Property、Swiss CGL）。本系統只做人工收付登錄與對帳，**不接銀行或外部會計系統**；銀行手續費由外部會計系統處理。有收付、抵銷、銷帳或 Production 認列紀錄的舊帳，保留原算法、精度與歷史（`accountingLegacyMath`、`legacy-cents`）。

### 8.1 建帳
- **Announce 時立即建帳**；分期一次建立全部期別。Production 只認列業績與月份，不重複建帳；零業績仍保留帳款。
- 一般保費案件（Oversea Business 依 §4.8）每案／每期／**每家正分攤再保人**各有獨立 T1（Cedant）、T2（再保人）、T3（經紀費）；零分攤不建帳。
- 分配：先算整筆 Cedant T1，依再保人比例分配（最大比例吸收尾差，同比例依案件順序），再把每家 T1 分期（第一期吸收該家尾差）。例：T1=1,000、33.33/33.33/33.34 → 333/333/334；兩期各 50% → 499/501。T2 各家獨立計算；每家 T3 = 自己的 T1 − 自己的 T2。
- 交易編號（財會統一第二批，配合新系統案件重置上線；C 只代表理賠）：
  - 保費 `-R{n}-T1／T2／T3`；分期放在 T 前面 `-R{n}-I{期}-T{1／2／3}`（Oversea 同樣 `-R{n}-I{期}-T3`）；Cedant 合計帳款沒有 R：`-T1`、`-I{期}-T1`；早期版面分績接在 T 後 `a／b`（例 `-R1-I2-T1a`）。
  - 批單在 TW Ref 後 `-E{nn}`；理賠 `-C{理賠}-P{付款}-R{n}-T1／T2`。
  - 整件 Reverse：沖回 `-RVS{輪次}`、重建 `-V{輪次}`（例 `TWPF2601001-R1-I2-T1-V1`）。
  - 財會更正（已關帳月份）：同一次更正共用次數，沖回 `{原編號}-ADJ{次數}-OLD`、新帳 `{原編號}-ADJ{次數}`（例 第 2 次更正：`-R1-T1-ADJ2-OLD` 沖回 `-R1-T1-ADJ1`，新帳 `-R1-T1-ADJ2`）。
  - 不寫轉換程式：上線時新系統案件須已重置（部署前檢查沒有舊寫法帳款）。舊資料的寫法不變（`LTX-…-T{n}`、`LTX-…-C1-T{n}`）；更早期的 TX／CLM 原樣保存，畫面以新寫法顯示。
- 所有具名再保人都依本節建帳（2026-11-13）：名稱含 Facility／PWS 但不在五家清單者照一般再保人規則，Announce 建帳、逐步取位；不再有「Production 關帳才建帳」的路徑。
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
- **批單**（2026-11-13 業主決定）：Cedant 端從**批改生效日 E**起算：到期 E＋C（Facility 為 E＋90），提醒日照上表（一般到期前 15 天、Swiss Property E＋80），與 Word Debit／Credit Note 相同；回溯批單 Announce 時已過到期日即照實顯示逾期。再保人端把 B 換成 L，依上表公式（Swiss Property 依固定結算期，原始期依 L＋90 歸期）。新系統與舊資料新增批單相同；已收付或已結清的帳款保留原日期。
- 遲收 Cedant 款、部分收付、補登日期都不重算原期限。超過實際到期日才算逾期。

### 8.3 財會對帳與實際收付（2026-11-10 部署）
- 操作者只有 Finance Staff、Finance Manager、System Administrator；業務與 President 保留唯讀。
- 「已對帳」＝財會已核對內容與金額，不要求對方同時確認，也不代表已收付。T1／T2、理賠及 Oversea 現金 T3 均須先對帳；歷史已對帳／已結清資料及既有收付歷史保留，不補造銀行紀錄。
- 同一實際對象可跨案、跨期、跨幣別對帳，同對象全部有效對帳合為一個邏輯批次，原始各次對帳事件與幣別保留。對帳日期必填，Review reference／Explanation 選填。
- 取消對帳須填原因，整個對象批次一起取消。任何幣別成員有有效收付或歷史抵銷時，先依原沖回限制處理；任何成員變動均須取消整批並重新對帳。
- 停止一切新增抵銷／純抵銷，僅登錄實際現金收款與付款。既有抵銷繼續反映餘額與收付前置條件，保留查閱及合法整筆沖回。
- Record Selected 可選同一實際對象的多個幣別、兩種方向，逐列 Cash Amount 預帶 Outstanding，可修改。系統按幣別與方向建立獨立收款／付款登錄，不互抵，不跨幣別加總。台幣 Cash Amount 只准整數（2026-11-14），輸入小數該列失敗並提示；外幣最多兩位。
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
- 金額（2026-11-14／15）：所有險種的台幣理賠（Reserve、付款）只准整數、其他幣別最多兩位，不偷偷取整。拆給各家再保人時與保費相同：台幣每家整數、外幣兩位，尾差給比例最大的一家（同比例依案件順序），合計等於該筆付款。例：TWD 1,005、50／30／20 → 502／302／201。
- 到期：一般、AUW、Allianz、Great American、QBE、Swiss CGL＝建帳台灣日期＋15日；Swiss Property 依建帳日歸入固定結算期；Accounting 提醒日一律為到期前 7 天（例：10-15 建帳 → 10-30 到期 → 10-23 提醒）。
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
- 未 Production 認列的保費以最新月匯率暫估台幣並標示 Estimated（「最新月」＝本月或以前最新的月份；提前輸入的未來月份要到該月才使用，完全沒有過去匯率才用未來月份；Accounting 與 Dashboard 相同，2026-11-14）；認列後固定為實際認列月份的正式匯率。賠款用建帳月份匯率。缺匯率不擋原幣作業，顯示 Awaiting FX。
- 畫面：TWD 整數不補 .00，USD 兩位；12 個金額欄位顯示千分位。
- **幣別（2026-11-18 業主決定）**：TWD 為本國幣（匯率固定 1），外幣 15 種，所有選單、FX Rates 與檢查一律依此順序：USD、THB、CNY（人民幣用 ISO 代碼 CNY，不用 RMB）、AUD、HKD、EUR、JPY、GBP、CAD、IDR、VND、CHF、SGD、MYR、INR；有 TWD 的選單 TWD 排第一。清單只有一份：後端 `backend/fxrates/currencies.py`、前端 `frontend/src/alpha/constants.js`（Word 產生器的幣別代碼另列）。FX Rates 每月 **15 種都必填**才能儲存；匯率維持小數 6 位（IDR、VND 大額換算接受小誤差）。金額取位不變：TWD 整數，其他外幣兩位。原有限制不變：Property QS、CGL QS、Product Recall 案件幣別仍只開放 TWD／USD；Debit Note 銀行資料仍只有 USD／TWD。

### 8.6 提醒信（目前未寄出，見 §1）
- 保費、退保費、賠款全部納入：**首次信在各筆 Accounting 提醒日**，之後在實際到期日及逾期每 7 天，餘額歸零停止；同日同類去重。信件寫真正到期日並附會計提醒日。名稱「會計收付款提醒」。
- 收件人：案件 AE、AE 主管、所有啟用中的 Finance Staff；先寄有效 Email，缺漏另列出。
- 寄信未啟用時（suppressed）逾期提醒也維持每 7 天一筆。

### 8.7 Accounting 畫面
- 五分頁依序為 All Accounts、Unreconciled Accounts、Reconciled Accounts、Settled/Closed、Brokerage。All Accounts 列全部 T1／T2 及 Oversea 現金 T3（未結清與已結清）；前兩對帳分頁預設 Open，可切 Settled／全部；Settled/Closed 僅列有效全額結清的 T1／T2。一般留存 T3 全列 Brokerage，Oversea 現金 T3 未結清時留在對帳清單，收齊／付清才歸 Brokerage。
- **伺服器分頁（2026-11-17 業主決定；取代 2026-11-13 的背景合併）**：Accounting 預設開在 Unreconciled Accounts，畫面讀 `?view=list&legacy=open`（全部新系統案件、匯入時尚未收付完的舊資料與舊資料上新增的批單／理賠），Unreconciled／Reconciled 在瀏覽器篩選、勾選、審核與收付，與以前相同。**All Accounts／Settled/Closed／Brokerage** 改由伺服器篩選、排序、分頁：`GET /api/accounting?view=page&tab=all|settled|brokerage&page=N` 加同名篩選條件（reference、insured、cedant、reinsurer、currency、direction、settlement（逗號分隔）、source、origin、due），**固定每頁 100 列**，包含匯入時已結清的舊資料歷史；標題數字＝符合條件的帳款列總數（全系統，不是案件數）。**讀取方式只保留三種**（2026-11-17 業主決定）：`?view=list&legacy=open`、`?view=page`、`?view=options`；不帶參數、`?view=list` 與 `?view=list&legacy=history` 已退役（回 400 `unsupported_view`），完整計算只在伺服器內部使用，測試以 `backend/qa/accounting_full.py` 讀取（相同權限檢查與內容）。文字欄停止輸入 0.3 秒後才查詢；換頁或改條件時短暫顯示載入中；失敗時顯示錯誤與 Retry。下拉選單（Cedant、Reinsurer、幣別）由 `?view=options` 提供，含只出現在歷史中的名稱（打開時與 Refresh 時讀取）。伺服器的轉換、篩選與排序逐行移植自畫面程式（`backend/cases/accounting_pages.py` ↔ `frontend/src/alpha/accountingRows.js`、`frontend/src/views/accountingList.js`，兩邊要一起改），以 `run_qa.sh pages` 逐頁比對。已結清歷史整份不再下載到瀏覽器。
- Unreconciled／Reconciled 每頁預設 100 列（可選 50／100／200／500；All Accounts／Settled/Closed／Brokerage 固定 100 列，見上）；打開時的清單（`?view=list&legacy=open`）為精簡資料，返回頁面先顯示快取並背景更新，更新前財務操作停用。載入失敗（伺服器錯誤、連線中斷）時在表格上方常駐紅色提示與 Retry，不顯示「No matching accounts」；已有上次載入的清單時保留並註明載入時間，財務操作停用到重新載入成功（2026-11-10）。窄螢幕表格橫向捲動，不以左固定欄遮擋操作。
- Transaction / SoA / TW Ref標題維持；SoA編號依Cedant Statement No.或對應再保人Settlement Ref取值，缺漏顯示SoA: Missing；T3不顯示SoA。TW Ref後接YYYY-MM-DD：原單與各分期用Case生效日、批單用批單生效日、理賠用對應Date of Loss；資料缺漏顯示—而不推算。移除獨立Reconciliation Ref欄，Edit references移至Action，原權限與狀態限制維持。
- Finance account review 與 Record Selected 的 Account 識別資訊均與 List 同序：Transaction → SoA → TW Ref · 日期。日期直接沿用 accountDisplayDate，原單／分期用案件生效日、批單用批單生效日、理賠用出險日；缺漏顯示 —，T3 仍不顯示 SoA。
- 帳款排序：逾期（超過實際到期日、未結清）一律置頂；Unreconciled／Reconciled／Settled/Closed 逾期按實際到期日最舊優先、未逾期按 Accounting 提醒日最早優先。**All Accounts（2026-11-18 業主決定）**：逾期置頂、依 Accounting 提醒日最舊優先；其餘帳款（含已結清）依 Accounting 提醒日**由新到舊**；沒有提醒日的用實際到期日，完全沒有日期的放最後。Brokerage 依 TW Ref。TW Ref搜尋只查系統／AUW編號，另加 Original Insured EN／CN；移除 TWD valuation 與QBE承保年季附註。
- Cedant 與 Reinsurer / R/I Broker 分開下拉選單，互斥選取，僅查實際帳款對象，不因同案 Cedant 而帶出再保人帳款。Leg 改 Direction（Payable／Receivable），主表 Party / Direction，移除 Reinsurer allocation。Due date 為包含當日的單一截至日，空白不限。
- Select all／Deselect all 包含目前篩選的跨頁可選帳款，限同一實際對象、可跨幣別與收付方向；多對象時先選一筆或縮小篩選，全不選清除全部頁面的勾選。
- Mark reviewed與Record selected彈窗逐列顯示Insured (EN)、Insured (CN)與SoA，可Remove該列，只移出本次名單，不刪帳款或更動原對帳狀態；名單清空時不可送出。
- Record Selected 的 Direction／Outstanding 固定窄欄寬，Outstanding 靠左減少間距；Outstanding 與 Cash Amount 的幣別、金額各自同一行，完整顯示八位數台幣及千分位。
- Record Selected 彈窗壓縮 Account、Insured EN/CN、Direction、金額、Result 與 Action 欄寬及內距；長文字換行，保留所有內容，一般桌面免橫捲，小螢幕仍可橫向捲動。TWD Cash Amount 整數不補 .00，USD 保留兩位，既有金額精度不變。
- 所有新收付金額及合計以 ISO 幣別代碼顯示（例 USD 1,000.00、TWD 30,000），各幣別分列應收、應付、參考淨額；待登錄與已登錄合計分開。彈窗已完成列唯讀，失敗列可更正／移出後重試。
- 原收付登錄歷史由帳款明細查看（History主分頁已改為Settled/Closed）。整筆登錄保留有效／已沖回狀態及實際收付款日期。分三欄：應收沖銷合計、應付沖銷合計、實收付淨額（新登錄按幣別及方向分開，淨額僅供參考；純抵銷只限既有歷史）。可查會計參考號、TW Ref、對象與日期，展開逐筆現金／抵銷、沖回與替代關係。
- 明細 Applied amount 改 Receipt / Payment Amount；一般歷史不顯示 Swiss period，Swiss需要時列 Swiss settlement due date。T3按鈕 Brokerage settlement details。
- 移除舊人工結清、取消結清、直接更改付款金額及 Offset with original 入口。Complete missing days 只補歷史缺漏，有效天數與新公告帳款不能用此入口更改。

---

## 9. Production Report

- 案件金額更正依 §8.4a：原月未關帳直接反映修正；已關帳完整沖回及補入受影響再保人的保費與收入，沿用原認列匯率，列本月／第一個未關帳月份，原報表不可改寫。
- 分績尾差（2026-11-13）：Reinsurance Staff 先依比例取位，Other Staff 拿差額（70／30 例：1,005 → 704／301）；與舊資料 AE／Sub AE 規則相同。已關帳報表不改寫。
- **起始月與歷史月份（2026-11-15 業主決定）**：Production 從 **2026-11** 起產生與關帳（`RI_PRODUCTION_START_MONTH`）。2026-10 以前為歷史月份，視同已關帳：不能產生、關帳、排除；匯率（2026-11-19 業主決定，取代原本的全部鎖定）**只能補輸入一次**：該月還沒有匯率時可新增（15 種一起），存檔後立即鎖定、不能再改；頁面唯讀列出該月匯入的舊資料保費／批單業績（即其已認列的 Production），沒有 Excel。新系統業績月份若在起始月之前，一律列在起始月認列。
- 業績月份：原單／續保單期以保單生效月份為準，不因較晚 Announce 而延後；分期依各期 Performance Month；批單取批改生效月與 Announce 月較晚者；已關帳月份自動建立不可改寫的排除紀錄，順延到第一個未關帳月份。零收入不列業績。
- Finance Staff 只能看預覽與既有版本、下載 Excel；Finance Manager 與 System Administrator 可產生、排除、關帳。
- 關帳、產生、排除、匯率存檔共用月份操作鎖（衝突立即回 409 operation_busy）；關帳前在鎖內重讀完整預覽，來源或匯率有變就拒絕並要求重新產生。已關帳月份不能改匯率。
- **Class**（2026-11-16 業主決定）：Property 一律顯示 **PD**（新系統案子存的 PF 與舊資料的 PD 都顯示 PD；案件、TW Ref 與 MDM 仍用 PF）；其他險種顯示存的代碼。已存報表版本的 PF 已一併改成 PD（2026-10 一列；正式環境 Audit 暫停中，修正前後內容存於備份目錄 `production_reports_before.json`／`after.json`）。
- 欄位 18 欄，最後一欄 **First Policy No**（沿批單→原單、續保→來源追到最初保單的 TW Ref；只靠 TW Ref 連結，不比對名字；不放進來源簽章；已關帳月份不補）。remark 一律 Fac。
- 排除紀錄資料庫層禁止修改刪除。

## 10. Dashboard

- Brokerage 趨勢右上年度選單提供目前年度及前四年（共五年）；目前年度顯示至本月、歷史年度顯示全年。所選年度與其前一年依每月並排柱狀圖呈現，Prior year 在左、Current year 在右；Monthly target 保留折線。選年度僅影響趨勢，其他統計維持現在期間；沿用既有正式關帳／預估及權限規則。
- Accounting · Receivable / Payable 的缺匯率說明為 Awaiting FX — Past 5 years record only.，不再附加重複起算日期說明；資料仍按每日滾動五年篩選。
- 缺少上帳月份匯率時，僅在 Accounting · Receivable / Payable 區塊顯示 Awaiting FX；Dashboard 頂端不再重複顯示匯率警告。換算與缺匯率處理維持。
- 標題：Production & Records Overview。Total Gross Premium、Accounting · Receivable / Payable（依收付方向分：向再保人收的理賠款屬 Receivable、退給 Cedant 的退費屬 Payable）以 TWD 前綴顯示；YTD Brokerage Trend (TWD)；Total Bound YTD；New Business MTD 卡片有 + New Case（需 `cases.write`）。
- Total Gross Premium（2026-11-13／14）：保期內保單的原單加已 Announce 批單，用與 Accounting 相同的逐步取位分出保費，依「本月或以前最新月份」匯率換算。保期以最新已 Announce 批單的到期日判斷，In-Force Policies 與 Expected Renewals 也用同一判斷。公司全體 Dashboard 含仍在保期內的舊資料：以 Cedant's Policy No. 為一件（未填用 Old Reference），保期為該件已確認保費列與批單的最晚到期日。Total Bound YTD、New Business 等新簽件數只算新系統案件。
- 舊資料（公司全體 Dashboard）：Brokerage 趨勢含舊資料保費列與批單列（匯入及新增，依 Revenue Month；歷史月份顯示舊資料已認列業績並標示 closed；已關帳月份與 Production 報表一致，未關帳預估）；起始月前的新系統業績畫在起始月；未收付合計含全部舊資料未結清帳款，5 年判斷對匯入的舊交易用原 Effective Date（理賠用 DOL）、新增批單／理賠用確認日。個人 Dashboard 只看自己的案件。
- 理賠（2026-11-15）：Dashboard 未收付合計的所有理賠都換算台幣（理賠自己的幣別、建帳月匯率）；Accounting 畫面對 CGL／Product Recall／STP 理賠維持原幣顯示、不換算。
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
- 帳號 API（2026-11-17 業主決定，四個網址合一）：`POST /api/personnel-accounts`，以 `action` 區分 `create`（省略 action 也是建立）／`disable`／`enable`／`reset_password`；原 `/disable`、`/enable`、`/reset-password` 子網址停用（404）。網址允許 `accounts.manage` 或 `accounts.create.subordinate`，停用／啟用／重設密碼另在程式內要求 `accounts.manage`（主管只能建立直屬下屬的帳號），不符回 403 `PERMISSION_DENIED`；未知 action 回 400 `invalid_action`。指令列工具（`create_ri_account` 等）不變。
- 閒置 3 小時自動登出（真實點擊、鍵盤、捲動才續期；背景 API 不續期；多分頁同步）。
- 忘記密碼：可輸入帳號或 e-mail；token 一次性；目前寄信關閉所以入口隱藏。
- System status 與 `/health/` 只有 System Administrator（`/health/` 未登入回 401）。

## 12. 主檔（MDM）

- **Account Executive**：MDM 入口及新增／修改 API 停用，歷史主檔與案件關聯保留；案件 AE 改用 Personnel。
- **Reinsurers**：最上方 **Lloyd's Market** 收合區（名稱以 Lloyd's Underwriter Syndicate No. 開頭者自動列入，含 Inactive）。分類內全部共用 Lloyd's of London 信評（`ri_market_rating_profiles`，有 Edit，需 `mdm.write`；個別成員不能覆寫）。
- **信評欄位**：Rating agency（只能選 S&P Global、A.M. Best、Moody's、Fitch）、Grade、As-of date 必填；Rating type 固定 Financial Strength；Checked at 選填。一般再保人可無信評，Lloyd's 共用至少一筆，最多 50 筆。舊資料不補造日期，但編輯時要補。
- **Insured**：整合於 **Master Data Management**（`/mdm?tab=insured`），依現有 MDM 分頁排列。分頁顯示 `Insured (N)`，僅計正式主檔，搜尋不改總筆數；待確認另列。舊 `/insured` 及 id 連結保留。Finance 唯讀、僅看到 Insured；Case Viewer 不能進入。New insured 與 Rename insured 移除，直接主檔寫入 API 亦禁止。
- **組合身分**：完整中文名稱為 key，`/` 分隔成員、忽略排列及成員前後空白與重複；A/B 與 B/A 共用主檔，A 單獨是另一組合。各保單保留自己的名稱／排列；公告前舊別名不作正式身分或正式更名依據。
- **Draft／Announce**：原單、續保及批單的 Draft 名稱僅存 Case，不新增／連結主檔，不計正式筆數、不產生 Renamed。Announce 成功後才以最後名稱新增或連結；不相容的舊單獨名稱別名不會吸收聯名組合。公告驗證失敗、取消或版本衝突不可先寫入主檔。
- **公告後變動**：Announced 且沒有任何 Confirmed 部分時，變更名稱先詢問名稱更正或變更承保組合。更正沿用同一主檔並記 Renamed，其他保單保留歷史名稱；變更組合只改該 Case 連結，不更名原組合，缺少新主檔可在確認儲存後自動建立。相同成員僅排列不同不產生 Renamed；增加／移除成員不能偽裝為名稱更正。
- **Confirmed**：任何期別或再保人份額已 Confirmed（含整案 Confirmed），即禁止直接變動 Insured；必須走批單。批單 Draft 不變更主檔，批單成功 Announce 時依前一張來源保單／批單的名稱分類確認並處理，原已確認保單保留其歷史名稱。
- **待確認與歷史**：無可驗證 Announce 來源的舊主檔保留資料與歷史，列待確認、不列正式筆數；與成功公告的完整組合相符時自動沿用轉正式。舊歷史標為 Before Announce、正式別名只採公告後確認更名。既有重複組合整併仍先預覽及版本指紋核對，原資料不刪除。Operation time 為台北 YYYY-MM-DD HH:mm:ss；Created、Renamed 等歷史不受 Audit 暫停影響。
- 主檔 API 拒絕非物件 JSON、非有限數字、溢位版本號。
- **Master Data 修改理由（2026-11-16）**：Reinsurer、Cedant、Foreign RI Broker、Class 與一般 Clause 的編輯及停用必須填寫非空理由；新增與單純重新啟用不要求。理由保存在版本快照；Audit 暫停時不寫 Audit。
- **重新啟用（2026-11-16 業主決定）**：Reactivate 先不帶理由送出；儲存內容不變時直接啟用。若重新啟用會一併改變儲存內容（例如 Lloyd's Syndicate 舊資料被畫面補上市場資料），後端回 `reason_required`，畫面才跳出填理由視窗，填寫後再送一次；取消則不變更。正式資料有 3 筆停用的 Lloyd's Syndicate（2609 AUW、3622 AFB、6107 AFB）屬於後者。

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

- **逐筆永久刪除（2026-11-18）**：System Administrator 可於本頁 Recycle Bin 逐筆永久刪除，需確認檔名；只允許回收桶項目。Document Template 的正式檔案與中繼資料刪除；若中途失敗，保留待重試狀態、禁止還原缺少內容的檔案。System Guide 留刪除標記，避免系統更新後重現；系統映像及既有備份中的副本仍保留。

- **共用拖拉排序（2026-11-04）**：System Guides 與 Document Templates 各自排序；沿用 System Administrator 權限，拖拉把手或鍵盤上下鍵調整後自動保存，所有使用者與重新登入共用。順序原子寫入文件 volume 的 `system-reference/.orders/`，備份須包含文件 volume；不需 migration。並行修改以排序版本檢查拒絕覆寫；未排序的新檔列在已存順序之後，彼此依上傳時間由新到舊顯示；更名保留位置，回收筒還原保留已存排序位置。

現行指南（Word）：完整 MDM 指南、完整 Schema 指南（2026-11-16 版）；Swiss Re Facility PD、Swiss Re Facility CGL、Great American Facility PD、QBE Facility PD、Allianz Facility PD（10-30 改提醒日）、Syndicate 609 AUW Facility PD 專屬規則（皆 2026-10-29 版）。舊問卷與舊版隨備份保留。

## 15. 效能設定與量測（1 萬件壓測資料）

- 每件案件結果快取：以「資料內容指紋＋台北日期」記住付款排程與交易明細；每 worker 最多 30,000 筆（約多 210 MB）。
- Dashboard／Production 結果快取：先取資料變更指紋再讀資料；每 worker 32 筆、TTL 5 分鐘；Generate／Close／Exclude 不用快取。
- 業主決定不做：Production 連結表只讀 3 個欄位、跨 worker 共用快取、每件案件整列結果快取（伺服器分頁原列在此，2026-11-16 業主改為只對 Accounting 三個分頁做，見 §8.7）；理賠交易不再每筆複製再保人名單（2026-11-16 先不做：每筆理賠付款約 7 KB、其中約六成是重複名單，正式目前只有 1 筆）。
- **Accounting 已結清舊資料歷史的快取**（回應內容不變；`RI_LEGACY_RESULT_CACHE=false` 時全部不快取、每次重算；測試 `legacy_accounting_cache`）：
  - **計算結果**（2026-11-10；2026-11-17 業主決定改共用快照與背景預建）：只快取匯入的歷史交易（唯讀、已結清），以「歷史資料指紋（除 original 外全部欄位）」為鑰匙，**不隨台北日期重算**（正式資料實測日期往後推 1／400／3,000 天結果全部相同）；新增的舊案批單／理賠每次重算。計算結果存成一份共用快照檔（容器 `/tmp/ri-legacy-history`，pickle＋zlib，只有後端自己寫；鑰匙＝計算程式版本（legacy／cases 原始碼雜湊）＋歷史內容指紋），一個 worker 計算、其他讀檔；每個 web worker 一條背景執行緒（`legacy/warm.py`），啟動時、歷史有變（每 30 秒檢查輕量指紋）或換日時先把 Accounting 歷史部分建好。關閉：`RI_LEGACY_HISTORY_SNAPSHOT=false`、`RI_LEGACY_HISTORY_WARM=false`。正式資料副本實測（gunicorn 4 workers）：All Accounts 第一次載入最慢約 13 秒 → 約 2 秒（原本 6,094 筆每個 worker、每次重啟、匯入或過台北午夜各重算一次，約 11–13 秒）。「匯入時逐筆存進資料庫」方案實測讀取與重算差不多（6.0 秒對 6.7 秒），不採用。
  - **伺服器分頁的清單列**（2026-11-17，§8.7）：已結清歷史在伺服器轉成清單列後快取（每 worker 一份；以台北日期＋歷史的變更指紋（筆數、最大鍵、版本加總、最後更新時間）為準，另每 60 秒最多以完整內容指紋（MD5）複驗一次，直接改資料庫而沒有更新時間的修改最多 1 分鐘後出現）；未結清部分每次重算，寫入後下一頁立即反映。量測（共用快照上線前）：正式資料（4,262 列）每頁約 0.2–0.3 秒，當天第一次約 4 秒；1 萬筆舊資料（3 萬列）每頁約 1.6–3 秒（主要是未結清部分重算約 1 秒、資料轉換、篩選排序），當天第一次約 22 秒；仍可再優化（快取歷史部分的篩選排序結果、略過整份轉換），需重跑全部測試。
- 舊資料量優化（2026-11-13，1 萬筆舊資料實測後；回應內容不變）：
  - **匯入**：Insured 主檔整批只讀一次（`legacy.policy.insured_lookup`，比對規則與逐筆查詢相同）。確認匯入 2,500 筆約 5 分鐘 → 約 10 秒；1 萬筆約 1 分鐘。單一請求上限 60 秒，**每個 Register 檔案建議不超過 5,000 筆**。
  - **未結清舊資料**：帳款與付款排程同一次計算共用（`legacy.ledger.accounting_bundle`），並逐筆快取，鑰匙為「該列內容 MD5＋台北日期」（比照每件案件結果快取）；對帳狀態即時套用、不進快取；每 worker 最多 `RI_LEGACY_OPEN_CACHE_SIZE` 筆（預設 20,000），`RI_LEGACY_OPEN_CACHE=false` 關閉。2,000 筆未結清時 Accounting 打開的請求約 9 秒 → 首次約 7 秒、之後約 1.3 秒。測試 `legacy_open_cache`。
  - **Accounting 畫面**：清單改為整份替換（不逐欄追蹤）、排序比較值每列只算一次；清單超過 2,000 列時文字篩選等 0.3 秒沒有再輸入才套用（列數少時立即）。2 萬列時切換分頁約 20 秒 → 約 2 秒。
  - 1 萬筆（8,000 已結清＋2,000 未結清）實測：打開到可操作約 38 秒 → 約 5 秒；剩餘時間主要是資料量（6,000 列約 21 MB）。已結清歷史約 79 MB，原為背景載入；2026-11-17 起改為伺服器分頁（§8.7）。
- **單筆很大的資料（2026-11-16 業主決定）**：MySQL 排序時會把查詢讀到的每個欄位（含篩選條件用到的 JSON）放進排序緩衝區，單筆超過緩衝區就整個查詢失敗（Out of sort memory），例如一件案件超過 256 KB 時 Accounting、Account List、Production Report 對所有人打不開。對大型 JSON 表的排序查詢一律用 `ri_system/sorted_fetch.py`（先篩選出編號、只用編號排序、再依編號讀整筆，結果順序相同）：案件、財會審核批次、Audit、草稿回收桶、Placing Slip 版本、舊資料交易／稽核／匯入批次，共 16 處；另把 `sort_buffer_size` 調為 2 MB 作為備援。量測：每筆理賠付款約讓案件增加 7 KB（3 家再保人；每筆交易各複製一份再保人名單），2026-11-16 正式最大案件 18 KB；1 萬筆舊資料時打開 Accounting 的伺服器時間約多 0.1–0.25 秒。新增查詢時沿用此做法，`large_rows` 測試組會把每種資料灌到超過緩衝區檢查。
- nginx 日誌行尾記錄回應時間：`rt`＝整個請求、`urt`＝後端處理（秒）；例：`docker logs ri-nginx 2>/dev/null | grep -o 'urt=[0-9.]*'`（容器重建時清空）。

## 16. 已退役／已移除

- Treaty（2026-11-02）、PDF 產生與 Gotenberg（2026-10）、Alpha 差異測試與搬遷匯入工具、舊 Word 產生器、CaseWorkspace 產生器、PendingView、舊 AUW 說明檔。conversion app 的 models／migrations／資料表保留。
- 已取消的舊規則：人工「Awaiting confirmation」才 Settled（改為全額自動銷帳）、Production 關帳才建帳（改為 Announce 建帳）、新增淨額抵銷／純抵銷、舊單獨保費抵銷入口、直接 Edit amount、Facility 專用理賠追蹤入口（統一至全部未結理賠）、Swiss 獨立專區與收妥勾選、固定提前 7 天首封提醒、Allianz 月底＋80 提醒。
- **已退役 Accounting 動作的程式移除（2026-11-12）**：`record_payment`、`reverse_payment`、`edit_payment`、`record_premium_offset`、`record_swiss_offset`、`record_swiss_clearance`、`confirm_swiss_collection`、`unconfirm_swiss_collection`、`confirm_facility_settlement`、`unconfirm_facility_settlement`、`record_allianz_claim_followup`、`record_great_american_claim_followup`、`record_qbe_claim_followup` 共 13 個動作呼叫時仍回 410 `retired_accounting_action`（無 Finance 權限回 403），其處理程式已刪除：`cases/transaction_payments.py` 整檔、`AccountingView.record_payment／reverse_payment`、`facility_accounting.settlement_action`、`swiss_accounting._offset`、三家 `record_followup`。`mark_swiss_statement`（Swiss 結算清單參考號）與既有抵銷／結清紀錄的顯示、餘額計算保留。`/api/render-document-pdf` 整個移除（404）。前端 `AccountingEntryActions.vue` 只剩 Swiss 結算清單參考號。API 網址合併：文件、主檔經評估不做（會把各網址的權限設定改成程式內分動作判斷，業主 2026-11-12 決定）；帳號的四個網址已於 2026-11-17 依業主決定合一（§11）。
- **2026-11-17 退役的讀取與網址**：Accounting 不帶參數、`?view=list`、`?view=list&legacy=history` 三種讀取（回 400 `unsupported_view`，§8.7）；帳號 `/disable`、`/enable`、`/reset-password` 子網址（404，§11）。

---

## 17. 舊案專區：Legacy Data (Old Register)（2026-11-10 部署）

- 分頁名稱及內容介面使用英文，主分頁固定 `Legacy Data (Old Register)`；原始中文資料不翻譯。
- 一般業務、會計、General Manager、President、System Administrator 及新增主管唯讀角色可查閱；Case Viewer 不授權讀舊帳。
- 歷史交易保持唯讀；依 §17.2 開放新增批單／理賠及其 Accounting 寫入。歷史更正、作廢與撤回 HTTP 寫入仍不開放；匯入自 2026-11-11 起由系統管理員在網頁進行（§17.1）。
- 已對帳或有收付歷史等受保護交易的業務金額更正留待下一階段（尚未開放）。
- 新舊資料用獨立的來源欄區分，不更動既有 premium／claim 分類。
- **Insured 主檔**：匯入與確認新交易時，依中文名以與 Case 相同規則比對（含 / 組合與曾用名），沒有才新建，並標為正式、連結到該交易（`insuredMasterId`）；中文名空白不建。
- `ri_runtime` 對 `ri_legacy_transactions`、號碼計數及原因表為 SELECT／INSERT／UPDATE，永無 DELETE；`ri_legacy_import_batches` 為 SELECT／INSERT／UPDATE（2026-11-11 起網頁匯入，仍無 DELETE）；獨立 `ri_legacy_audit` 僅 SELECT／INSERT，永久不可 UPDATE／DELETE。全系統 Audit 暫停與 SMTP 關閉設定維持。
- 歷次清空紀錄見文末「資料清理紀錄（舊資料）」。

### 17.1 網頁匯入 Register（2026-11-11 業主決定）

- 限 System Administrator，在 Legacy 分頁 Import Register 上傳 Register（工作表 `Facultative`）→ 預覽 → 確認匯入（核對 SHA256）。**不保留上傳記錄**（2026-11-17 業主決定）：沒有上傳清單與原始檔下載；匯入成功後刪除暫存 Excel、清空預覽內容，批次只留匯入筆數作為「匯入交易」的內部標記；未匯入的預覽在 Clear／關閉對話框／同一人重新預覽時丟棄（狀態 withdrawn、刪檔），他人超過一天的預覽也會丟棄。每筆交易的 Original Excel Data 照舊保留。預覽有任何錯誤或警告都不能匯入；沒有新交易可匯入時也不能確認。不提供網頁撤回；匯錯以業主授權維護程序處理。可分批匯入各再保人的 Register；已匯入的流水號自動略過。
- **清單排序**（2026-11-17 業主決定）：依 Transaction No. 由大到小——沒有編號的草稿最前（新的在前），再來網頁新增的 LTX 編號（大到小），最後是匯入的 Register 流水號（依數字部分大到小，例如 F18329、F17763、F2898）。
- Class 依 Master Data Management 的 Class 代碼比對（2026-11-16 業主決定；不分大小寫），險種名稱用 MDM 名稱，Register 原代碼照存；Register 的 PD 視同 MDM 的 PF（Property）；MDM 沒有的代碼為錯誤；已停用的 Class 為警告（須先在 MDM 重新啟用）；非 Property 列的再保人若為 Allianz／Great American／QBE Facility（新系統這三種 Facility 規則只適用 Property）為警告，不設放行清單；Legacy Dashboard 依每筆存的險種顯示，Production 的 Class 依 §9（Property 一律 PD）；Fac / Claim 必填；不再限定已結清。業主指定的排除（`import_exclusions.json`，F13333）與更正（`import_corrections.json`，F2898：Fac / Claim＝Fac、New / Renew＝New）在預覽列出，原始 Excel 值保留。
- 欄位：Reinsurer's Ref. No.＝Reinsurer Ref.；Effective Date 顯示在 Accounting「Transaction / SoA / TW Ref」日期位置（理賠用 DOL），與新系統邏輯相同；Revenue Month＝Production 月份（2026-11-15 起：保費列與批單列依此月份列入 Production；起始月 2026-11 以前視為已認列的歷史月份，理賠不列入）；Cedant／Reinsurer Receipt／Payment No.＝Accounting Dept. Ref.；New / Renew＝新案／續保；Installment No.＝分期（顯示，不改交易編號）；Issue Date 不匯入；未使用欄位保留在原始資料。
- 欄位對應（續）：Description = 英文被保險人；Cedant's Policy No. = Statement No.；Bkg. (in TWD) 是整筆，Re Dept. Bkg. (in TWD) 是 AE，差額歸 Sub AE。分績保留原金額，不重算。原幣金額、台幣金額、匯率及原始 Excel 保留。
- 收付：Cedant Receipt No／Cedant Payment No 有填＝Cedant 方已收付；Reinsurer Receipt No／Reinsurer Payment No. 有填＝再保人方已收付（理賠方向相反）。已收付方建立收付登錄（Accounting Dept. Ref.＝該編號；保費列日期＝Receive Date／Pay Date，理賠列＝Closed Month 月底），標示 Settled before import，不可沖回。全部已收付的列為歷史已對帳／結清；仍有未收付方的列成為可追蹤帳款，已收付方視為匯入前已對帳，未收付方依新系統各再保人規則計算到期日（理賠以 Issue Date of Claim 為理賠建立日，到期日＝其後 15 天、提醒日提前 7 天，與新案相同；未收付理賠缺 Issue Date of Claim 時預覽警告、不能匯入），走一般對帳與收付流程。
- 匯入列不建立 Case、不能退回草稿或編輯業務資料；保費列與批單列依 Revenue Month 列入 Production 與 Dashboard（2026-11-15，見 §9 起始月）。
- Accounting 對象名稱（2026-11-13 業主決定）：任何名稱結尾帶「(Facility)」者在 Accounting 一律顯示不含「(Facility)」的名稱（歷史列、未結清列與新案相同，同一公司只有一個對象名稱）；舊資料本身仍保留完整名稱與 Facility／一般付款規則的區分。
- 從匯入列新增批單／理賠時沿用來源險種（GL 匯入列新增的仍為 CGL；2026-11-11 修正）。
- R/I Comm. %／Tax %（2026-11-11）：匯入時由 Register 公式「Our Share Premium × 固定比率」讀出（只辨識公式文字，不執行）；直接填數值者以金額 ÷ 承接保費換算；比率 × 承接保費與金額不符或公式無法辨識時預覽警告、不能匯入。理賠不存比率。Legacy 明細顯示；從匯入列新增批單時預帶來源比率（可修改）。舊交易金額仍以 Excel 為準。
- **匯入台幣取整（2026-11-14）**：Register 的台幣金額匯入時取整數：Net Premium from Cedant 與 Brokerage 各自四捨五入，Net Premium to Reinsurer＝前者 − Brokerage；理賠金額取整。原始 Register 值另存 `amountsOriginal`，原始 Excel 保留。
- **匯入配套**：Note for Claim 以「Claim No:」／「Loss No:」開頭者拆出 Loss No.（原文保留，沒有不擋）；Sub AE 依 Bkg. 金額換算為 40 或 70（±1%），否則預覽警告；保費／批單列缺 Share 為錯誤。
- **理賠列不拆分（2026-11-17 業主確認）**：理賠沒有 Brokerage，匯入時理賠列不做 AE / Sub AE 40/60、70/30 檢查，比例存 100（與系統內建理賠相同），Register 的 Sub AE 名字保留；保費／批單列照舊檢查。原因：有 Sub AE 的理賠列 Bkg. 為 0，0÷0 算不出比例而全數被擋（當日 Register 34 筆：USD 26、TWD 8）。

### 17.2 新增批單／理賠（2026-11-10 部署；2026-11-12 業主決定規則）

- **同一張保單**＝同一個 Old Reference（TW Ref；每個 TW Ref 是一家再保人的分保）。**最新期間**＝同一 Old Reference 所有已確認保費列與批單列中最早起日＋最晚到期日。Payment Split（C／R）暫不使用。
- **來源**：理賠只能從原始保費列新增；批單可從保費列或批單新增，不能從理賠。
- 從 confirmed 舊交易帶入資料，保留原來源交易關聯及案號快照。新交易只有 Endorsement／Claim；不建立 Case。草稿只由建立者編輯、確認；首次確認產生 `LTX-YYYY-000001`，確認年度採台灣年度。未對帳、無收付歷史且未進已關帳 Production 的交易，建立者可退回草稿；再次確認沿用原號。
- **鎖定沿用來源**：Cedant、Settlement Party、Old Reference、New / Renew。批單另鎖幣別、Share、AE／Sub AE 分配（沿用的 Sub AE 不檢查在職；換 AE 須在職）；Insured EN／CN 可改。理賠另鎖 Insured（帶同一 Old Reference 最新已確認批單的名稱，無批單用原保單）；Property 理賠鎖幣別，其他險種可選。
- **付款規則**依 Settlement Party 自動判斷（各 Facility 名稱，其餘一般），不能選；批單的 Cedant／再保人付款天數一律帶入來源並鎖定（2026-11-14，與新系統批單相同），Facility 的 Cedant 固定 90 天。

**批單**
- **批單**：生效日須在最新期間內（含頭尾），且不得早於同一 Old Reference 前一張已確認批單（可同日）；可改期但只能改到期日（起日固定，完整期間最長 18 個曆月，到期日不得早於生效日）；Endorsement No. 必填且同一 Old Reference 已確認批單（含匯入）不得重複；100% Premium 與 Brokerage 不得同時為 0；Share 鎖定，R/I Comm. %／Tax % 帶入可改；Brokerage 填金額；**Revenue Month 自動**＝批改生效月與確認月較晚者，已關帳順延第一個未關帳月（同新系統 §9），不能改；超過 5 年依最新到期日須選原因。
- Endorsement 與 Claim 分開登錄。超過 5 年須選原因（依最新到期日，見上）；Only Other 另須補充說明；原因由管理員維護並留痕。
- 批單手填 100% Premium、R/I Commission (%)、Tax (%)、原幣 Brokerage 金額（Share 沿用來源鎖定）；先取位 Our Share Premium，再算佣金與稅；淨額與既有 Leg 算式相同。Bkg.(%) 依金額反推；零承接保費且有 Brokerage 時用正／負100%顯示並填原因。AE/Sub AE 沿用已核准分績與原幣、台幣尾差規則。Brokerage 手填、付再保人金額由 Brokerage 倒推，是舊資料與新系統（T3＝T1−T2 由系統計算）的刻意差異（2026-11-14 業主確認）。
- 批單 Revenue Month 依上方自動規則；使用該月共用匯率，不提供逐筆覆寫。缺匯率不擋確認及原幣 Accounting；未關帳隨月匯率更正重算，關帳需補齊匯率並凍結台幣快照；不從 Production 排除操作改變選定月份。

**理賠**
- **理賠**：新增 **Loss No.（必填）**與 **Cause of Loss（選填）**，Note for Claim 保留；DOL 須在最新期間內；到期日＝確認日 +15 天（Swiss 季結）；AE 須在職；先收再付。每筆理賠是獨立 SoA；理賠明細列出同一 Old Reference＋同一 Loss No. 的所有理賠與累計（僅顯示）；Accounting 交易編號下顯示 Loss No.。
- 理賠只填本筆承接賠款，不計佣金、稅、Brokerage 或處理費，兩邊金額相等；DOL 必填且須落在最新期間內（含首尾）。允許負數退回賠款，不必連結原理賠，負數必填原因。負數向 Cedant 收回後才退還再保人；正負理賠均不得先墊付超過該筆已回收賠款（含既有合法抵銷）。理賠不填 Revenue Month，不進 Production。

**金額與收付**
- **金額**：TWD 只准整數、其他幣別最多兩位小數，不自動取整（100% Premium、Brokerage、理賠金額）。Installment No.、Statement No.、Reinsurer's Ref. No. 帶入來源可改。
- 新交易確認後接到既有 Accounting 對帳、原幣收付、部分賠款、同對象跨幣別、兩方向分開實際收付、部分收付及整批沖回；停止新增抵銷，保留歷史抵銷。匯入時已結清的歷史維持已對帳／已結清，不補造銀行或覆核事件；仍不提供歷史更正、作廢或撤回寫入。

---

## 部署與回復紀錄

| 日期 | 項目 | 備份 | 回復映像標籤 | 驗證摘要 |
|---|---|---|---|---|
| 11-19 10:30 | 歷史月份（2026-11 以前）匯率可補輸入一次，存檔即鎖定（§9 起始月；取代 11-15 全部鎖定） | `backups/fx_fill_20261119_103043/`（含部署前 DB、文件、被覆蓋原始碼）；回復用 `fx-fill-work/rollback.sh 20261119_103043` | `ri-backend:before-fx-fill-20261119_103043`／`ri-frontend:before-fx-fill-20261119_103043` | 候選映像 API 135/135（production_start_month 24 項含補輸入一次、存後鎖定、再存拒絕）、畫面 21 階段＋專項 376 項通過；正式後端逐檔一致、無 migration、無資料修改 |
| 11-19 09:30 | 清空 FX Rates（業主同意的正式資料刪除）：匯率 60 筆（2026-01～10，每月 6 種）及其版本紀錄 127 筆（只能新增的保護暫時移除後原樣補回）；FX 無 Audit 事件 | `backups/fx_clear_20261119_093059/`（部署前 DB；另存被刪列 `fx_rates_rows.sql`、`fx_snapshot_rows.sql`，可用 `fx-clear-20261119/restore_fx.sh` 單獨放回，FX 已有新資料時會停止） | —（程式未變） | 正式資料副本演練：刪除、二次執行在前置檢查停下、放回 60／127 筆均成功；正式執行後其他資料表、保留的版本紀錄與所有觸發器前後完全相同，保護觸發器實測生效 |
| 11-18 18:04 | 新增幣別：外幣 15 種依業主順序（RMB 用 CNY）、FX 每月 15 種必填（§8.5）；migration `fxrates 0003`（只改幣別允許值） | `backups/currency_20261118_180446/`（含部署前 DB、文件、被覆蓋原始碼）；回復用 `currency-work/rollback.sh 20261118_180446`（已有新幣別匯率時會停止） | `ri-backend:before-currency-20261118_180446`／`ri-frontend:before-currency-20261118_180446` | 候選映像 API 135/135（新增 currency_list 16 項）、畫面 21 階段＋專項 376 項通過；migrate 後權限與 Audit trigger 重新套用；正式後端逐檔一致、makemigrations 無變更、無資料修改 |
| 11-18 16:33 | 第四次清空舊資料（交易 11,025、內部標記 14、Insured 2,690（案件使用中的 1 筆保留）、Legacy 操作紀錄 28；業主同意的正式資料刪除） | `backups/legacy_clear_20261118_163327` | —（程式未變） | 正式資料副本演練：其他資料表、保留的 MDM 與 Finance 紀錄前後完全相同；保護觸發器補回；第二次執行自動停止 |
| 11-18 15:57 | Accounting All Accounts 排序：逾期置頂，其餘依 Accounting 提醒日由新到舊（§8.7） | `backups/accounts_sort_20261118_155725/`（含部署前 DB、文件、被覆蓋原始碼）；回復用 `accounts-sort-work/rollback.sh 20261118_155725` | `ri-backend:before-accounts-sort-20261118_155725`／`ri-frontend:before-accounts-sort-20261118_155725` | 候選映像 API 134/134、畫面 21 階段＋專項 375 項通過；伺服器分頁與畫面程式逐頁一致（測試環境 214 頁、部署後正式資料 549 頁／41,611 列）；正式後端逐檔一致、無 migration、無資料修改 |
| 11-18 11:00 | System Reference 回收桶逐筆永久刪除 | `backups/reference_purge_20261118_105939` | `ri-backend:before-reference-purge-20261118_105939`／`ri-frontend:before-reference-purge-20261118_105939` | 局部 API、畫面 A＋專項；部署前後資料與文件指紋一致 |
| 11-17 | 舊資料匯入：理賠列不做 AE / Sub AE 拆分檢查（只換後端） | `backups/legacy_claim_split_20261117_174953`（原始碼） | `ri-backend:before-legacy-claim-split-20261117_174953` | 候選映像完整 API（legacy_import_web 新檢查以舊程式驗證會失敗）、畫面 L；當日 Register 4,880 列以新程式預覽：0 錯誤、0 警告；無 migration、不改資料 |
| 11-17 | 已結清舊資料歷史：共用快照檔＋每個 worker 背景預建；不再隨台北日期重算（只換後端） | `backups/legacy_history_snapshot_20261117_164156`（原始碼） | `ri-backend:before-legacy-history-snapshot-20261117_164156` | 候選映像完整 API（legacy_accounting_cache 191，新檢查以舊程式驗證會失敗）、畫面 A＋L＋Y；正式資料副本 API 回應逐位元組相同；gunicorn 實測最慢 13→2 秒；無 migration、不改資料 |
| 11-17 15:50 | 依業主指定清空 System Reference Data 回收桶 10 項（9 份上傳文件與 1 份 Insured 清單指南）；不改案件及舊資料 | `backups/reference_trash_20261117_155007` | `ri-backend:before-ref-trash-20261117` | 獨立容器 System Reference 排序／回收／權限 34 項通過，已移除指南不可存取；正式網站 200、回收桶 0、10 份共用文件及 8 份指南下載通過，資料庫與其餘文件比對一致；無 migration |
| 11-17 | 第三次清空舊資料（交易 6,102、內部標記 4、Insured 全部 1,681、Legacy 操作紀錄 8；業主同意的正式資料刪除） | `backups/legacy_clear_20261117_143435` | —（程式未變） | 正式資料副本演練：其他資料表、保留的 MDM 與 Finance 紀錄前後完全相同；保護觸發器補回；第二次執行自動停止 |
| 11-17 | 第二次清空舊資料（AGCS／GAIC 1,236 筆、內部標記 4、Finance 對帳 2、Insured 全部 412、Legacy 操作紀錄 20 筆；業主同意的正式資料刪除） | `backups/legacy_clear_20261117_120204` | —（程式未變） | 正式資料副本演練兩次：其他資料表、保留的 MDM 與 Finance 紀錄前後完全相同；保護觸發器補回；第二次執行自動停止 |
| 11-17 | 舊資料不保留上傳記錄（拿掉 Import History／下載，匯入或放棄預覽後刪檔）；Legacy 清單依 Transaction No. 由大到小 | `backups/legacy_no_batch_20261117_115347` | `ri-backend:before-legacy-no-batch-20261117_115347`／`ri-frontend:before-legacy-no-batch-20261117_115347` | 候選映像完整 API（legacy_import_web 74，8 項新行為檢查以舊程式驗證會失敗）、畫面 A＋L＋I＋Y；前端以原始碼重建與正式逐檔核對；無 migration |
| 11-17 | 清空舊資料（含上傳紀錄與 Excel、對舊資料的 Finance 對帳 2 筆、只被舊資料連結的 Insured 699 筆、Legacy 操作紀錄 17 筆；業主同意的正式資料刪除） | `backups/legacy_clear_20261117_102008` | —（程式未變） | 正式資料副本演練：其他資料表 CHECKSUM、保留的 MDM 與 Finance 紀錄前後完全相同；保護觸發器補回；第二次執行自動停止 |
| 11-17 09:39 | API 整合：Accounting 只保留畫面使用的三種讀取（舊三種退役回 400，測試改用 `qa/accounting_full.py`）；帳號四個網址合為 `POST /api/personnel-accounts`（action 區分，停用／啟用／重設限 `accounts.manage`）；人員頁、壓測工具、畫面測試 U 項；每週健檢改量畫面實際請求 | `backups/api_merge_20261117_093947`；回復用 `perf-work/stage-i-20261117/rollback.sh 20261117_093947` | `ri-backend:before-api-merge-20261117_093947`／`ri-frontend:before-api-merge-20261117_093947` | 候選 API 133 組全通過（約 40 組測試改用內部讀取；新增退役讀取 400、帳號 action 與舊子網址 404 等檢查；拿掉權限判斷或放行舊讀取的變異版本會失敗）；畫面 374 項（新 U 10 項）；部署後 `run_qa.sh pages` 342 頁一致；同時間新舊映像 766 個回應僅退役讀取 12 個變為 400；無 migration、無資料寫入 |
| 11-17 00:54 | Accounting 伺服器分頁：All Accounts／Settled/Closed／Brokerage 每頁 100 列由伺服器篩選排序（含已結清舊資料歷史，不再背景下載）；下拉選單由伺服器提供；新增 `run_qa.sh pages` | `backups/accounting_pages_20261117_005406`；回復用 `perf-work/stage-h-20261117/rollback.sh 20261117_005406` | `ri-backend:before-accounting-pages-20261117_005406`／`ri-frontend:before-accounting-pages-20261117_005406` | 候選 API 133 組全通過（新 `accounting_pages` 39 項，2 個變異版本會失敗）；畫面 364 項（Y 改寫 24 項；D 階段 1 項改為等待伺服器回應後檢查）；與畫面原本程式逐頁比對：正式 342 頁／20,137 列、1 萬筆壓測 266 頁／15,504 列全部一致；部署後原有 766 個回應與舊映像相同；無 migration、無資料寫入 |
| 11-16 21:35 | 大型資料排序（先排序編號再讀整筆，16 處）＋MySQL `sort_buffer_size` 2 MB（SET PERSIST，不重啟）；舊資料已結清理賠列 paymentStatus settled；Reactivate 需要理由時跳出填理由視窗；每週健檢跳過須改密碼帳號 | `backups/large_rows_20261116_213535`；回復用 `perf-work/stage-g-20261116/rollback.sh 20261116_213535`（含還原 MySQL 設定） | `ri-backend:before-large-rows-20261116_213535`／`ri-frontend:before-large-rows-20261116_213535` | 候選 API 132 組全通過（新 `large_rows` 50 項，舊程式驗證會失敗）；畫面 356 項（新 M 11 項，舊前端驗證會失敗）；正式資料 766 個回應僅 24 筆舊資料理賠列狀態不同，部署後與候選逐位元組相同；1 萬筆舊資料計時；無 migration、無業務資料寫入 |
| 11-16 | Production Report 的 Property 一律顯示 PD；已存報表版本 PF→PD（2026-10 一列，正式資料寫入，前後內容存備份；只換後端） | `backups/production_pd_20261116_173040` | `ri-backend:before-production-pd-20261116_173040` | 候選映像完整 API 131 組（production_api 84，3 項新行為檢查以舊程式驗證會失敗）；基礎版本中途換成 00f7eb21（指南更新）後重建，重跑相關 11 組 API 與畫面 A＋P1＋P2；正式資料副本演練（其他資料表 CHECKSUM 不變）；無 migration |
| 11-16 | 更新完整 MDM／Schema 指南 | `backups/release_guides_20261116_171748` | `ri-backend:before-release-guides-20261116_171748` | 35 表、355 欄逐一核對，離線版面、隔離與正式下載及權限驗證；無 migration 或業務資料寫入 |
| 11-16 | 舊資料匯入 Class 改讀 MDM（PD＝PF；停用 Class、非 Property 的 Allianz／GA／QBE Facility 為警告）；Legacy Dashboard／Production 依存的險種（只換後端） | `backups/legacy_class_mdm_20261116_162231` | `ri-backend:before-legacy-class-mdm-20261116_162231` | 候選映像完整 API 131 組（legacy_import_web 63，7 項新行為檢查以舊程式驗證會失敗）、畫面 A＋L＋I＋Y；無 migration、不改資料 |
| 11-16 14:23 | Product Recall 固定 Covered Events／Loss 順序、固定法律管轄、新案預設 Occurrence Form | `backups/before-recall-order-20261116_142158.sql`、`backups/before-recall-order-source-20261116_142158.tar.gz` | `ri-backend:before-recall-order-20261116_142158`／`ri-frontend:before-recall-order-20261116_142158` | 131 組 API、全部瀏覽器回歸、Product Recall 畫面及兩種 Word 文件專項通過；無 migration、無資料批次改寫 |
| 11-16 | Master Data 編輯及停用必填理由 | `backups/mdm_reason_20261116_092729` | `ri-backend:before-mdm-reason-20261116_092729`／`ri-frontend:before-mdm-reason-20261116_092729` | 候選 API 40/40、五類畫面操作與基本畫面測試；無 migration |
| 11-15 12:20 | 財會規則統一第二批：交易編號重整（§8.1；分期 I 在 T 前、重建 `-V`、財會更正沖回 `-ADJ{n}-OLD`）；只換後端 | `backups/accounting_numbering_20261115_122014/`（含部署前 DB、文件、被覆蓋原始碼）；回復用 `accounting-unify-work/rollback-batch2.sh 20261115_122014`（回復前會列出已用新寫法的案件） | `ri-backend:before-accounting-numbering-20261115_122014`（前端未變） | 候選映像 API 130/130（新增 transaction_numbering 23 項）、畫面 21 階段 341 項通過；部署前正式資料舊寫法帳款 0 件（不需轉換）；正式後端逐檔一致、無 migration、無資料修改；Dashboard／Production 合計與部署前相同 |
| 11-15 11:12 | 財會規則統一第一批（§8.1–8.5、§9、§10、§17）；P8 部分清理；舊資料進 Production、Production 起算月份 2026-11 | `backups/accounting_unify_20261115_111238/`（含部署前 DB、文件、被覆蓋原始碼）；回復用 `accounting-unify-work/rollback.sh 20261115_111238` | `ri-backend:before-accounting-unify-20261115_111238`／`ri-frontend:before-accounting-unify-20261115_111238` | 候選映像 API 129/129、畫面 21 階段 341 項通過；重建比對內容與候選一致；正式容器為候選映像、後端逐檔一致、無 migration、無正式資料修改；正式資料 Dashboard／Production 與部署前試算一致 |
| 11-14 21:29 | Product Recall QS、Personnel、Claim／Loss Record 共通變更；12 筆唯一 AE 歷史關聯回填 | `backups/product-recall-20261114_212639/`（含部署前 DB、文件及回填前 DB） | `ri-backend:before-product-recall-20261114_212639`／`ri-frontend:before-product-recall-20261114_212639` | 候選後端 128 組 API 全通過；全部瀏覽器階段及修正後重跑通過；正式 migration、主檔、回填快照及首頁驗證 |
| 11-13 | Oversea Performance Month 獨立設定；新案必填，既有月份保留 | `backups/oversea_performance_20261113_163724` | `ri-backend:before-oversea-performance-20261113_163724`／`ri-frontend:before-oversea-performance-20261113_163724` | 候選映像完整 API 與畫面回歸；無 migration、無正式資料修改 |
| 11-13 | 舊資料量優化：匯入加速、未結清舊資料每筆只算一次＋逐筆快取、Accounting 畫面處理大量資料 | `backups/legacy_scale_20261113_144820` | `ri-backend:before-legacy-scale-20261113_144820`／`ri-frontend:before-legacy-scale-20261113_144820` | 候選映像 122 組 API（含 `legacy_open_cache` 192 項）、329 項畫面；正式資料 520 個 GET 回應部署前後逐位元組相同；1 萬筆舊資料上正式版與候選版回應逐位元組相同；無 migration、無資料寫入 |
| 11-13 | Accounting 對象名稱一律拿掉「(Facility)」（舊資料歷史列也一致；只換後端，小改） | `backups/legacy_facility_name_20261113_131526` | `ri-backend:before-legacy-facility-name-20261113_131526` | Legacy API 7 組（legacy_import_web 55，新檢查以舊程式驗證會失敗）、畫面 A＋L＋I；無 migration、不改資料 |
| 11-13 | 草稿副本只留最新一份（`ri_entity_snapshots` 增加 UPDATE 權限與條件式 trigger）；每日清理過期登入紀錄；Word 產生程式可快取（每次確認）；前端拆檔 | `backups/draft_snapshot_frontend_split_20261113_125840`（含部署前 crontab） | `ri-backend:before-draft-snapshot-20261113_125840`／`ri-frontend:before-draft-snapshot-20261113_125840` | 候選映像 121 組 API（以新的 db_harden 設定執行，含 `draft_snapshot_replace` 26 項）、329 項畫面（含 Z 14 項）；正式資料 520 個 GET 回應部署前後逐位元組相同；無 migration；資料庫權限／trigger 變更已核對；既有 222 筆草稿副本未刪 |
| 11-13 | Accounting 分段載入（預設 Unreconciled、已結清舊資料歷史背景載入）；每週健檢報告工具；畫面測試 Y 專項 | `backups/accounting_segments_20261113_085128` | `ri-backend:before-accounting-segments-20261113_085128`／`ri-frontend:before-accounting-segments-20261113_085128` | 候選映像 120 組 API（含 `accounting_segments` 255 項）、315 項畫面（含 Y 16 項）；正式資料 485 個原有 GET 回應部署前後逐位元組相同；無 migration、無資料寫入 |
| 11-12 | 移除已退役 Accounting 動作的舊程式（約 650 行、`transaction_payments.py`）、PDF 網址與無入口的抵銷對話框 | `backups/retired_cleanup_20261112_220859` | `ri-backend:before-retired-cleanup-20261112_220859`／`ri-frontend:before-retired-cleanup-20261112_220859` | 候選映像 119 組 API、299 項畫面；正式資料 485 個 GET 回應部署前後逐位元組相同；無 migration、無資料寫入 |
| 11-12 | 保費類金額上限 999,999,999,999、超限資料視為異常（Account List 不再整頁出錯）、非清單輸入回 400 | `backups/amount_limits_20261112_210454` | `ri-backend:before-amount-limits-20261112_210454`／`ri-frontend:before-amount-limits-20261112_210454` | 候選映像 118 組 API（含 `amount_limits` 85 項）、299 項畫面；無 migration、無資料寫入；正式資料巡檢一致 |
| 11-12 | 舊資料新增批單／理賠規則（§17.2）、Insured 主檔連結；清空舊資料 182 筆與未使用 Insured 1,729 筆 | `backups/legacy_entry_rules_20261112_123024` | `ri-backend:before-legacy-entry-rules-20261112_123024`／`ri-frontend:before-legacy-entry-rules-20261112_123024`（資料清理以備份 database.sql 還原） | 全部 API（含新 `legacy_entry_rules`）、完整畫面測試（L 更新）；正式資料副本演練：清理後非舊資料逐位元組相同、重跑自動停止、新版匯入 AGSC 181 筆與 Insured 建立 |
| 11-12 | Property QS 幣別限 TWD／USD | `backups/property_qs_currency_20261112_105646` | `ri-backend:before-property-qs-currency-20261112_105646`／`ri-frontend:before-property-qs-currency-20261112_105646` | 全部 API、完整畫面、幣別專項及前端建置；無 migration |
| 11-12 | STP 輸入及確認畫面標題改為 Information | `backups/stp_information_label_20261112_095907` | `ri-frontend:before-stp-information-label-20261112_095907` | 前端建置、基本畫面 56 項及 STP 輸入確認測試；無 migration |
| 11-12 | 修復 STP 部署覆蓋之側邊欄圖示 | `backups/stp_nav_fix_20261112_095123` | `ri-frontend:before-stp-nav-fix-20261112_095123` | 基本畫面 56 項、11 個圖示載入與設計核對；無 migration |
| 11-12 | 修正 STP Cover Note Information 前空白頁 | `backups/stp_pagination_20261112_094312` | `ri-frontend:before-stp-pagination-20261112_094312` | 115 組既有 API、完整畫面回歸、LibreOffice 多頁視覺檢查；無 migration |
| 11-12 | STP 一般 QS 建案與 Cover Note | `backups/stp_qs_20261112_091209` | `ri-backend:before-stp-qs-20261112_091209`／`ri-frontend:before-stp-qs-20261112_091209` | 115 組 API、294 項畫面及 STP 專項；無 migration |
| 11-11 | Oversea 批單 100% Premium 增減 | `backups/oversea_premium_adjustment_20261111_210514` | `ri-backend:before-oversea-premium-adjustment-20261111_210514`／`ri-frontend:before-oversea-premium-adjustment-20261111_210514` | 114 組 API、294 項畫面；正負保費差額及分期 Production；無 migration |
| 11-11 | 舊資料匯入存 R/I Comm. %／Tax %（由 Register 公式讀取並核對），新增批單預帶來源比率 | `backups/legacy_rates_20261111_184913` | `ri-backend:before-legacy-rates-20261111_184913`／`ri-frontend:before-legacy-rates-20261111_184913` | Legacy API 6 組（legacy_import_web 53）、畫面 A＋L＋I；AGSC 演練 181 筆可匯入，540 條帳款與前一版逐欄相同；無 migration |
| 11-11 | 修正：從匯入的 GL 舊資料新增批單／理賠時險種誤為 Property，改為沿用來源險種（只換後端） | `backups/legacy_gl_entry_20261111_182515` | `ri-backend:before-legacy-gl-entry-20261111_182515` | Legacy 相關 API 6 組（含 legacy_import_web 48 項，新檢查以舊程式驗證會失敗）、畫面 A＋L＋I；無 migration |
| 11-11 | Legacy 網頁匯入 Register（系統管理員預覽→匯入；PD／GL、已收付建 Accounting Dept. Ref. 收付登錄、未收付續追 Accounting；不進 Production）；資料庫權限調整 | `backups/legacy_import_web_20261111_174810` | `ri-backend:before-legacy-import-web-20261111_174810`／`ri-frontend:before-legacy-import-web-20261111_174810` | 全部 API（含新 `legacy_import_web`）、完整畫面測試（含新 I 專項）；以 AGSC Register 在正式資料副本演練 181 筆逐筆核對、其他資料不變；無 migration、部署時未匯入任何資料 |
| 11-11 | 清空 Legacy Data (Old Register) 全部 3,694 筆（業主要求，之後重新匯入；不換映像） | `backups/legacy_clear_20261111_155937` | （資料變更，無映像；回復＝還原該備份的 database.sql） | 正式資料副本演練：只有 3 個 Legacy 資料表改變；Accounting 去除 Legacy 後、Dashboard、Production 5 個月份逐位元組一致；重跑腳本自動停止 |
| 11-11 | 畫面文字：移除側欄左下角環境說明；Dashboard Total Gross Premium 固定顯示兩位小數；Top Reinsurers 標題改為 Top Reinsurers/RI Broker by Ceded Premium（只換前端） | `backups/sidebar_dashboard_text_20261111_134156` | `ri-frontend:before-sidebar-dashboard-text-20261111_134156` | 前端建置、畫面 A 56／56＋G 20／20（候選映像 `ri-frontend:sidebar-dashboard-text-candidate`）；正式檔案與候選映像逐檔一致；後端與資料不變 |
| 11-11 | 左側選單圖示每項不同（範本 A：Legacy 與 Accounting、MDM 與 System Reference Data 不再共用圖示；只換前端） | `backups/nav_icons_20261111_114334` | `ri-frontend:before-nav-icons-20261111_114334` | 前端建置、完整畫面 283 項（候選映像 `ri-frontend:nav-icons-candidate`）；正式檔案與原始碼建置逐檔一致；後端與資料不變 |
| 11-11 | Oversea 批單 Brokerage 分期 | `backups/oversea_endo_installments_20261111_111953` | `ri-backend:before-oversea-endo-installments-20261111_111953`／`ri-frontend:before-oversea-endo-installments-20261111_111953` | 完整 API／畫面與批單正負分期驗證；無 migration |
| 11-11 | 更新完整 MDM／Schema 指南 | `backups/release_guides_20261111_093819` | `ri-backend:before-release-guides-20261111_093819` | 35 表、354 欄逐一核對，離線版面、隔離與正式下載及權限驗證；無 migration 或業務資料寫入 |

（回復映像標籤指 `ri-backend:` 與 `ri-frontend:` 兩個映像。「有」表示當次有備份但原紀錄未寫檔名。完整驗證細節見封存的變更紀錄。2026-11-10 以前的紀錄見 `docs/archive/VM-RULES-HISTORY-2026-11.md`。）

### 資料清理紀錄（舊資料）

- **2026-11-11 業主要求清空、之後重新匯入**：以維護者身分刪除全部 3,694 筆交易（匯入 3,693 筆＋草稿 TWPF241010 1 筆）；匯入批次標記 `withdrawn`（保留紀錄與原始 Excel），Legacy Audit 新增 `register_cleared` 一筆並保留既有紀錄，原因選項 4 筆保留。清空前演練確認 Accounting（扣除 Legacy 項目）、Dashboard、Production（含已凍結 2026-08／10）逐位元組不變。備份 `backups/legacy_clear_20261111_155937`。下方 3,693 筆等描述為清空前狀態；重新匯入沿用業主授權維護程序（HTTP 匯入仍不開放）。
- **資料清理（2026-11-12 業主要求）**：清空舊資料 182 筆（AGSC 181＋草稿 1；批次標記 withdrawn、稽核保留）；刪除未被任何 Case 使用的 MDM Insured 1,729 筆（保留 5 筆）。備份 `backups/legacy_entry_rules_20261112_123024`。
- **資料清理（2026-11-17 業主要求）**：舊資料全部清空，含上傳紀錄：交易 1,415 筆（匯入 1,414＋批單草稿 1）、上傳紀錄 6 筆及其原始 Excel、對舊資料的 Finance 對帳紀錄 2 筆、只被舊資料連結的 MDM Insured 699 筆（新系統案子使用的 Insured 保留）、Legacy 操作紀錄 17 筆（只能新增的保護暫時移除、刪除後原樣補回）。Legacy 原因設定 4 筆保留。備份 `backups/legacy_clear_20261117_102008`（database.sql、legacy-imports.tar）。之後依 §17 網頁匯入重新匯入。
- **資料清理（2026-11-17 第二次，業主要求）**：清空 11-17 重新匯入的 AGCS／GAIC 舊資料：交易 1,236 筆、上傳內部標記 4 筆（Excel 先前已刪）、對舊資料的 Finance 對帳紀錄 2 筆（6 筆交易已有的收付登錄隨交易刪除）、MDM Insured 全部 412 筆（新系統案子已於 11-17 清空，沒有任何 Insured 被使用；業主要求一併刪除）、Legacy 操作紀錄 20 筆（保護暫時移除後原樣補回）。Legacy 原因設定 4 筆保留。備份 `backups/legacy_clear_20261117_120204`。
- **資料清理（2026-11-17 第三次，業主要求）**：清空再次匯入的舊資料：交易 6,102 筆（3 批）、上傳內部標記 4 筆、MDM Insured 全部 1,681 筆（沒有案子使用）、Legacy 操作紀錄 8 筆（保護暫時移除後原樣補回）；沒有 Finance 對帳或收付登錄。Legacy 原因設定 4 筆保留。備份 `backups/legacy_clear_20261117_143435`。
- **資料清理（2026-11-18 第四次，業主要求）**：清空再次匯入的舊資料：交易 11,025 筆、上傳內部標記 14 筆（Excel 已不保留，0 個檔）、MDM Insured 2,690 筆（沒有案子使用的全部；案件使用中的 1 筆保留）、Legacy 操作紀錄 28 筆（保護暫時移除後原樣補回）；沒有 Finance 對帳。Legacy 原因設定 4 筆保留。備份 `backups/legacy_clear_20261118_163327`。

## 近期變更

- 2026-11-19：歷史月份（2026-11 以前）的 FX 匯率改為可補輸入一次：該月沒有匯率時可新增 15 種，存檔即鎖定、不能再改；Production 仍視同已關帳。

- 2026-11-19：依業主要求清空 FX Rates（匯率 60 筆及版本紀錄 127 筆）；新幣別啟用後重新輸入。

- 2026-11-18：新增幣別（§8.5）：外幣 15 種，所有選單、FX Rates 與檢查依 USD、THB、CNY、AUD、HKD、EUR、JPY、GBP、CAD、IDR、VND、CHF、SGD、MYR、INR，TWD 排第一；FX 每月 15 種必填；匯率維持 6 位小數；原有 TWD／USD 限制不變。

- 2026-11-18：依業主要求第四次清空舊資料（含未被案件使用的 Insured），見 §17 資料清理。

- 2026-11-18：Accounting All Accounts 改排序：逾期未結清置頂（依 Accounting 提醒日最舊優先），其餘帳款含已結清依 Accounting 提醒日由新到舊，沒有日期的最後；其他分頁排序不變。

- 2026-11-18：System Reference Data 回收桶新增逐筆永久刪除，保留備份；僅對使用者確認的項目執行。

- 2026-11-17：依業主決定整併本文件：修正過時與互相矛盾的說法（§2 PDF 網址、§3 部署流程與每週健檢、§8.7 分頁、§15 舊資料歷史快取、§16 網址合併）；STP 規則移到 §5.2b、Master Data 修改理由移到 §12、純 Facility 共通規則併入 §5.3、理賠節改為 §7.3、舊資料 §17.1／§17.2 合一（匯入規則集中在 §17.1）、舊資料清空紀錄移到「部署與回復紀錄」；2026-11-10 以前的部署紀錄與近期變更、已失效的歷史說明移到 `docs/archive/VM-RULES-HISTORY-2026-11.md`；部署紀錄表修好空行並依時間由新到舊排列。規則內容不變。
- 2026-11-17：舊資料匯入的理賠列不再做 AE / Sub AE 拆分檢查（理賠沒有佣金）。
- 2026-11-17：All Accounts 載入加速——已結清舊資料歷史改共用快照＋背景預建（§8.7 效能）。
- 2026-11-17：依業主指定清空 System Reference 回收桶全部 10 項，含 Insured 清單指南與舊資料試算表；已備份，舊資料表及其他共用文件維持。
- 2026-11-17：依業主要求第三次清空舊資料（含全部 Insured），見 §17 資料清理。
- 2026-11-17：依業主要求第二次清空舊資料（含全部 Insured），見 §17 資料清理。
- 2026-11-17：舊資料不保留上傳記錄；Legacy 清單依 Transaction No. 由大到小（§17）；部署前已匯入的 AGCS、GAIC 兩批只留筆數、2 筆未匯入的預覽改為丟棄，4 個 Excel 刪除（業主同意；備份 `backups/legacy_strip_batches_20261117_115639`，交易 1,236 筆不變）。
- 2026-11-17：依業主要求清空舊資料（含上傳紀錄），見 §17 資料清理。
- 2026-11-17：依業主確認部署 API 整合（§8.7、§11）：Accounting 不帶參數、`?view=list`、`legacy=history` 三種讀取退役；帳號建立／停用／啟用／重設密碼合為一個網址；網址數 41 → 38。
- 2026-11-17：依業主確認部署 Accounting 伺服器分頁（§8.7、§15）：All Accounts／Settled/Closed／Brokerage 每頁 100 列由伺服器篩選排序並含已結清舊資料歷史，打開時不再下載整份歷史；理賠交易瘦身先不做；11-16 依業主指示提前執行 Docker 清理（映像 209→106 個，釋放約 4 GB）。
- 2026-11-16：依業主確認部署大型資料排序保護（§2 MySQL、§15）、舊資料已結清理賠列狀態、主資料重新啟用流程（§12）、每週健檢帳號選擇；刪除 10-30 的 5 份舊備份（§3 備份保留）。
- 2026-11-16：本次公告與完整 MDM／Schema 指南更新：依目前 VM 核對資料表、Product Recall、STP、理賠、會計、Oversea 與舊案流程；只更新參考文件。
- 2026-11-16：依業主確認部署 Product Recall 的固定 Covered Events／Loss 順序、固定法律管轄條文及新案預設 Occurrence Form。
- 2026-11-16：Master Data 編輯及停用必填理由，理由保存於版本快照。
- 2026-11-15：依業主同意部署財會規則統一第二批（交易編號重整，§8.1）：分期 I 放在 T 前（`-R1-I2-T1`）、整件 Reverse 重建改 `-V{輪次}`、財會更正沖回改 `{原編號}-ADJ{次數}-OLD`（同次更正與新帳共用次數）；C 只代表理賠。正式資料沒有舊寫法帳款，不需轉換；理賠、批單、無分期保費與舊資料編號不變。
- 2026-11-15：依業主同意部署財會規則統一第一批：所有具名再保人走新會計規則；批改 Cedant 付款從批改生效日起算；TWD 收付款須為整數；Claim 金額精度與分攤尾差給最大份額；Dashboard 納入舊資料並換算所有 Claim；最新匯率規則；P8 部分清理（保留 History 用的付款與結算紀錄）；舊資料保費／批改按 Revenue Month 進 Production；Production 起算月份 2026-11，之前月份視同關帳、匯率鎖定，新系統 2026-11 以前的 Production 改認列於 2026-11。
- 2026-11-14：依業主同意部署 Product Recall QS 及 Case Owner／AE、Claim、Loss Record、CGL Turnover 共通變更；正式回填 12 筆唯一 AE Personnel 關聯，保留快照。
- 2026-11-13：依業主確認部署舊資料量優化（§15）：匯入加速、未結清舊資料只算一次並逐筆快取、Accounting 畫面處理大量資料；顯示內容與規則不變。前端拆檔的實際效果更正：`vendor` 檔可跨部署沿用快取，各頁面檔在任何修改後都會換名（進入該頁時重新下載）。
- 2026-11-13：依業主確認部署——草稿副本只留最新一份（未 Announce 不受 20 年限制；§4.5、§2 MySQL）、每日清理過期登入紀錄（§3）、Word 產生程式可快取、前端拆檔（§2）。回復：`~/RI System/perf-work/stage-e-20261113/rollback.sh 20261113_125840`（含還原資料庫權限與 trigger、移除排程）。
- 2026-11-13：依業主確認部署 Accounting 分段載入：預設分頁改為 Unreconciled Accounts，已結清的舊資料歷史改在背景載入後併入（§8.7）；新增每週健檢報告 `scripts/weekly_health.sh`（§3）。一次性整理（11-12～11-13）完成：整理舊資料與映像規則、金額上限、移除退役程式、分段載入；網址合併與共用快取不做／暫緩。
- 2026-11-12：舊資料新增批單／理賠改依 §17.2（來源限制、鎖定沿用、自動付款規則與 Revenue Month、改期、Loss No.／Cause of Loss）；匯入與確認時連結 Insured 主檔；清空舊資料並刪除未使用的 Insured 主檔，準備依新規則重新匯入。
- 2026-11-12：Property QS 幣別限定 TWD／USD，既有不符案件須修正幣別。
- 2026-11-12：STP 案件輸入與確認畫面的資訊區標題統一為 Information。
- 2026-11-12：修復 STP 部署時覆蓋的側邊欄圖示設定，恢復原圖示及缺少的圖示。
- 2026-11-12：修正 STP Cover Note Information 前重複分頁造成空白頁。
- 2026-11-12：部署 STP 一般 QS 建案與 Cover Note，沿用 Property QS 共通流程。
- 2026-11-12：API 整理（業主確認部署）：刪除 13 個已退役 Accounting 動作的處理程式（仍回 410）、移除 PDF 網址與畫面上無入口的抵銷對話框；行為與資料不變（§16）。網址合併不做。
- 2026-11-12：每週 Debug（一次性整理）找到並修正：保費類金額沒有上限時，天文數字草稿會讓 Account List 與該案件無法開啟；新增金額上限 999,999,999,999 與異常資料防護（§4.6），並修正兩處非清單輸入造成的伺服器錯誤（業主確認部署）。
- 2026-11-12：一次性整理（業主決定）：刪除 4 組停用的測試環境；回滾點映像改為 7 天＋每庫最新 10 個（`scripts/docker_cleanup.sh`）；新增備份保留規則並整理 9 月備份；16 個已上線工作資料夾打包封存。正式程式與正式資料未變動。
- 2026-11-11：Legacy Data (Old Register) 改為系統管理員網頁匯入 Register（PD／GL、已收付與未收付皆可）；收付編號成為 Accounting Dept. Ref.；Accounting 日期改顯示 Effective Date／DOL；不進 Production。
- 2026-11-11：依業主要求清空 Legacy Data (Old Register) 全部 3,694 筆，準備重新匯入；匯入批次標記 withdrawn，稽核紀錄保留。
- 2026-11-11：部署流程改版（2026-11-17 起生效）：實作前確認即含部署同意，測試通過後直接部署並回報；測試未全過、範圍變更、寫入正式資料、基礎版本已變時仍先問業主。
- 2026-11-11：本次公告與完整 MDM／Schema 指南更新：依目前 VM 核對資料表、對帳及部分收付、Oversea、Insured 與舊案流程；只更新參考文件。
- 2026-11-11：依業主指示完成 Oversea 批單 100% Premium 增減與分期 Production 認列的驗證、備份及部署。
- 2026-11-11：Oversea 批單可自行選擇 Brokerage 分期；完成驗證、備份及部署。
- 2026-11-11：§3「大型測試時段與記憶體」修訂：同仁正式使用前大型測試不限時段，正式使用後才限下班後；swap 檢查與停止不用的測試環境照舊。
