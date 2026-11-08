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
- **資料庫／API 測試組**：一律用 `scripts/run_isolated_qa.sh [測試組 …]`（隔離 MySQL＋後端、`ri_runtime`＋db_harden、每組全新資料庫、自動清除；全部約 30–40 分鐘，2026-11-03 為 87 組）。**不要在正式容器跑**（正式 Audit 暫停，測試會失敗）。`KEEP=1` 保留環境除錯；`QA_BACKEND_IMAGE=<映像>` 改測指定映像（不重建，用該映像內建的測試組），見下方「測試版本」。
- **前後端合計、密碼規則一致性**：`scripts/run_qa.sh totals`／`parity`（`run_qa.sh` 已不再跑測試組）。
- **畫面測試**：`scripts/run_ui_test.sh`（無頭 Chromium，用完即丟的環境）。13 個階段 A H R B0 B K C D E F G P1 P2，2026-11-02 共 207 項。`UT_BACKEND_IMAGE`／`UT_FRONTEND_IMAGE` 指定測試映像（預設是正式映像，可能比原始碼舊）；`PHASES="A H"` 只跑部分（要從 A 開始）。phase K 偶爾出現一次 401 console 錯誤，重跑即過。
- **前端檢查**：`frontend/scripts/check_*.cjs`（`check_endorsement_notes.cjs` 需在建置映像內執行，因為要 jszip）。
- **壓力測試**：`qa/stress/`（1 萬件案件；結果在 `qa/stress/RESULTS-*.md`）。
- **實作前確認（2026-11-08 業主決定，所有修改都適用，含小改與 bug 修正）**：動工前先向業主說明——理解的需求、預計做法、影響範圍、屬於必問或小改、預計的測試範圍；業主確認後才開始實作（業主在指示中明說「直接做」即視為已確認）。實作中發現做法或範圍需要改變，先停下再問。
- **部署流程**：實作前確認 → 實作 → 測試通過 →（必問項目先問業主確認）→ 備份資料庫（有 migration 再加文件 volume）→ 標記回復映像 → 部署 → 核對正式程式與原始碼逐檔一致 → 在「部署與回復紀錄」加一列。
  - **測試範圍**：有改程式就跑全部 API 測試組＋畫面測試；只更新參考檔／指南（應用程式碼不變）跑相關檢查即可。
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
- Reinsurance Structure 只有 **Quota Share（QS）** 與 **Excess of Loss（XOL）**；歷史 `FACULTATIVE` 視為 QS。**系統沒有 Treaty**（2026-11-02 完整移除；儲存 TREATY 被拒絕；資料庫 CHECK 只接受 FACULTATIVE／QS／XOL）。
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
- **Loss Record**：所有 Case 儲存時年數與 broker advised date 必填；New 可填 0 年（明細必須為空，文件顯示 Loss Clean since operation.）；Renew 至少 1 年（續保可帶入 0 但儲存前要改）；明細的日期、原因、金額都必填（CGL QS 金額 > 0）。Additional Loss Record Notes 輸入已隱藏（舊資料保留）。
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

---

## 5. Case：各險種專屬欄位

> 2026-10-28 起新增的 Property／CGL QS 案件，以及從舊案建立的新續保／批單，使用規則版本 `placing-qs-20261028-v1`（伺服器配置，編輯舊案不會自動升版）。下列標示「新版」的項目只適用這個版本；舊案維持原畫面與檢查。

### 5.1 Property
- Occupation & Construction、Breakdown of Sum Insured、Loss Record、Special Agreement 合併成一張 **Information** 卡片（含 Facility）。
- **Construction** 複選（至少一項，固定順序 A2 Class、A1 Class、B Class、C Class、D Class，無 Other、無預設）；舊文字保留在 `constructionLegacyText`，業務選好並確認後才改寫 construction；未確認不能產生新文件。適用所有可編輯 Property QS／XOL。
- Sum Insured 每個 Location 至少一筆；同一 Location 內名稱不可重複；金額 > 0 才能 Announce。全 Facility 案件可不指定 Location；全 Facility 改混合時，只清空沒有有效 Location 的 Sum Insured。刪除 Location 不會讓 Sum Insured 變成零筆。
- Sum Insured 與 Limit 不一致只提示，不擋 Announce（依 Word 顯示精度判斷）。
- 新版：地址列稱 SITUATION，至少一筆，地址與 Postcode 必填；**Basis of Valuation 必填**（Other 須說明；漏填紅框）；Retention 可空（文件補標準句）；Deductibles 下新增 SIR；Reinstatement Provisions 下依序 Loss Payee、Co-Reinsurance Warranty、Notices（前三項純 Facility 隱藏，Notices 全部選填）；Aggregate Limit 0 視為未填；Sub-Limits、Exclusions、Reinstatement、Indemnity Period、Special Agreement 選填；三項聲明空白補標準 None 文字。
- Property XOL Cover Note 不印 LOCATION 列，地址只在 SITUATION 列出。

### 5.2 一般 CGL（一般再保人；Swiss CGL QS 同樣適用）
- **Information** 取代 Occupation & Construction、Sum Insured、Loss Record、Special Agreement（後兩項移入 Information）。Policy Form 必選（Occurrence／Claims-Made）；Claims-Made 才顯示 Retroactive Date 與 Extended Reporting Period（適用時期間必填）。Territorial／Jurisdiction Limits 必選（三項或 Other 說明）。Business、Products 必填；Website 選填不驗證；Estimated Turnover 至少一筆（區域、幣別、非負金額）；Special Agreement 必選適用與否，適用時必填內容。切換 Policy Form／適用狀態會先確認，確認後清空從屬內容。
- 新版：Business 複選 Manufacturer／Distributor／Importer／Exporter／Other；Turnover Region 單選 USA/Canada／Rest of World／Other；舊自由文字一律放 Other 並需逐區塊確認。Overview 顯示 Adj. Rate（100% Premium ÷ Turnover 換算後加總 ×100%，保單生效月匯率，六位小數；缺匯率顯示 N/A）。
- **Retroactive Date** 可多筆（日期＋說明）：至少一筆；兩筆以上每筆說明必填；依日期排序、同日不可重複；舊單一日期以一筆無說明顯示。文件每筆一行，例如 `(September 01, 2002 in respect of limit USD 1,000,000)`。
- **Coverages**（Interest 後）：Premises-Operations、Products & Completed-Operation、Personal & Advertising Injury、Medical Payment、Other 多選，至少一項，Other 須說明。
- **Type**：Products Liability／Commercial General Liability 單選（新案 CGL QS 預設 Commercial General Liability），組成「名稱＋結構後綴＋as original」。
- **Interest** 預填 Reinsurance of the Reinsured’s liability under the original policy.（可改；空白用標準句）。
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
- **逐區塊 Edit**：批單所有區塊預設收合；每次只能有一個區塊在編輯，按 Done、收合或切換前先保存再鎖回。Endorsement details 與 Premium 可直接填。Schedule of Security 與 Performance Split 只能看。
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
- 每案／每期／**每家正分攤再保人**各有獨立 T1（Cedant）、T2（再保人）、T3（經紀費）；零分攤不建帳。
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

### 8.3 收付登錄與銷帳
- 操作者：Finance Staff、Finance Manager、System Administrator（案件編輯角色不因此有財務權限）。
- 每筆登錄的「對帳參考號」或「說明」至少填一項；可補登過去日期（另存實際操作時間）；不允許負值、零或超額。
- 同筆登錄限**同案、同期**（或同一筆賠款請款），且同幣別、同方向、同對象；一筆 Cedant 收款可勾選同案同期多筆 T1。外部參考號可在不同登錄重複使用，不會自動合併。
- **保費不可部分登錄**，每次登錄整筆餘額；賠款可分次。
- **全額後自動 Settled 並鎖定**（零金額自動完成，不虛構收付紀錄）。每家 T3 在自己的 T1、T2 都完成後自動完成（含 T3=0）；任一家 T3 完成後，同期所有 T2／T3 金額鎖定（其餘 T2 仍可依原額付款）。已銷帳不可取消、不可改金額。
- **付款前提**：付再保人保費前，該期所有 T1（含其他再保人分攤）須全額實收並自動銷帳。付 Swiss 正保費前另須填結算清單參考號。已付出後不能藉撤回 Cedant 收款破壞前提。
- **退保費**：須先全額實收所有再保人退款並自動銷帳，才能一次全額退清該批單全部 Cedant（可提前，不等結算日）。原保費與退保費兩端都**禁止抵銷**，各自全額登錄；舊抵銷歷史保留。
- 未曾銷帳、且不破壞先後條件時，可填原因修改金額（保留前後歷史）。有案件編輯權限者可填原因更正未處理帳款；T1 已完成時可只更正未處理 T2 並重算 T3。Production 已認列與正式報表保持鎖定。
- Reverse 不得移除已有收付、抵銷或銷帳的保費帳款；保費有收付或抵銷歷史時禁止 Reverse。理賠不受保費 Reverse 影響。
- 更正匯款以新增不可覆寫的 reversal 整筆沖回，保留原分配。

### 8.4 賠款
- Claim Payment 建立時立即建再保人應收與 Cedant 應付；準備金只追蹤不建帳。比例依出險當天適用的保單／批單。
- 到期：一般、AUW、Allianz、Great American、QBE、Swiss CGL＝建帳台灣日期＋15 天（不可人工改）；Swiss Property＝依建帳日歸入固定結算期（例 10/15→11/14、11/2→翌年 2/14），收與付同一到期日。
- 可分次收付，部分收付不改期限；同一請款累計付出不得超過累計實收。全額後自動 Settled 並鎖定。
- 完全沒有收付／抵銷／銷帳時，可依權限填原因更正應賠金額；Allianz／GA／QBE 舊有追蹤備註歷史保留顯示。
- 理賠出險日、付款日期須為有效日期；準備金與付款金額須為有限數字，負數沖抵與零準備金合法。

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
- 單一 SoA／Transactions 清單（含尚未 Production close 的 Swiss 排程，標示 Awaiting Production close）；欄位含 Original Insured (EN／CN)、實際對象、到期日、已收付、餘額；可依 SoA、交易編號、對帳參考號、TW Ref 搜尋與多種篩選。
- 每頁預設 100 列（50／100／200／500）；畫面使用精簡模式 `?view=list`；同一次登入回到頁面先顯示上次清單並背景更新（更新完成前隱藏操作）。

---

## 9. Production Report

- 業績月份：原單為 Announce 月（台北時間）；批單取生效月與 Announce 月較晚者；已關帳月份自動建立不可改寫的排除紀錄，順延到第一個未關帳月份。零收入不列業績。
- Finance Staff 只能看預覽與既有版本、下載 Excel；Finance Manager 與 System Administrator 可產生、排除、關帳。
- 關帳、產生、排除、匯率存檔共用月份操作鎖（衝突立即回 409 operation_busy）；關帳前在鎖內重讀完整預覽，來源或匯率有變就拒絕並要求重新產生。已關帳月份不能改匯率。
- 欄位 18 欄，最後一欄 **First Policy No**（沿批單→原單、續保→來源追到最初保單的 TW Ref；只靠 TW Ref 連結，不比對名字；不放進來源簽章；已關帳月份不補）。remark 一律 Fac。
- 排除紀錄資料庫層禁止修改刪除。

## 10. Dashboard

- 標題：Production & Records Overview。Total Gross Premium、Outstanding · Cedant / Reinsurer 以 TWD 前綴顯示；YTD Brokerage Trend (TWD)；Total Bound YTD；New Business MTD 卡片有 + New Case（需 `cases.write`）。
- 未結清應收應付以 Accounting 實際帳款與上帳月匯率為準，**只算 5 年內建立的帳款**（每天滾動，畫面註明起算日）；跳過「整件已銷帳」的案件，Accounting 若發現標記與實際欠款不符會在 warnings 列出。已關帳業績用正式報表，未關帳標示預估。
- 時間一律台北時間。

---

## 11. 權限與帳號

- 角色權限以 `backend/ri_system/authz.py` 為準。重點：
  - **President**（Board of Directors 部門，目前 David Kao）：全部唯讀（Dashboard、全部案件含他人草稿、MDM、Production、Accounting、FX、全部人員）；**看不到文件區**；不能新增人員或帳號；所有部門都可選 President 當 Supervisor。
  - **Finance Staff／Finance Manager**：可看全部案件明細、流程、理賠，無案件寫入或文件權限；財務操作見 §8.3、§9。
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
- **Insured Master**（`/insured`）：以**中文名稱**為主要身分；同中文名即同一主檔。Draft 可不填中文名，Announce 必填。改中文名會更名同一主檔（只改該案件名稱）；與另一主檔同名須人工確認合併（含雙方版本）。名稱與合併歷史即使 Audit 暫停也保存在主檔。Finance 唯讀。
- 主檔 API 拒絕非物件 JSON、非有限數字、溢位版本號。

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

現行指南（Word）：完整 MDM 指南、完整 Schema 指南（2026-11-02 版）；Swiss Re Facility PD、Swiss Re Facility CGL、Great American Facility PD、QBE Facility PD、Allianz Facility PD（10-30 改提醒日）、Syndicate 609 AUW Facility PD 專屬規則（皆 2026-10-29 版）。舊問卷與舊版隨備份保留。

## 15. 效能設定與量測（1 萬件壓測資料）

- 每件案件結果快取：以「資料內容指紋＋台北日期」記住付款排程與交易明細；每 worker 最多 30,000 筆（約多 210 MB）。
- Dashboard／Production 結果快取：先取資料變更指紋再讀資料；每 worker 32 筆、TTL 5 分鐘；Generate／Close／Exclude 不用快取。
- 2026-11-02 量測：Accounting 精簡清單第二次打開約 10.2 秒（剩餘主要是讀全部案件約 4 秒）；Production 未快取約 9 秒；Dashboard 第二次約 8 秒。
- 業主決定不做：Production 連結表只讀 3 個欄位、跨 worker 共用快取、每件案件整列結果快取、伺服器分頁。

## 16. 已退役／已移除

- Treaty（2026-11-02）、PDF 產生與 Gotenberg（2026-10）、Alpha 差異測試與搬遷匯入工具、舊 Word 產生器、CaseWorkspace 產生器、PendingView、舊 AUW 說明檔。conversion app 的 models／migrations／資料表保留。
- 已取消的舊規則：人工「Awaiting confirmation」才 Settled（改為全額自動銷帳）、Production 關帳才建帳（改為 Announce 建帳）、保費部分收付、保費抵銷、跨案合併登錄、Swiss 獨立專區與收妥勾選、固定提前 7 天首封提醒、Allianz 月底＋80 提醒。

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

（回復映像標籤指 `ri-backend:` 與 `ri-frontend:` 兩個映像。「有」表示當次有備份但原紀錄未寫檔名。完整驗證細節見封存的變更紀錄。）

## 近期變更

- 2026-11-03：文件整理——改為依主題的現行規則；舊變更紀錄封存到 `docs/archive/VM-RULES-CHANGELOG-2026.md`；刪除「2026-09 規則決定（Alpha 對照）」表。
- 2026-11-03：移除 Treaty 部署（migration cases.0009）。
- 2026-11-04：部署確認規則放寬——小改（參考檔／指南、純畫面文字版面、不改結果的效能優化、修既有規則 bug）測試通過即部署、事後告知；migration、正式資料寫入、新規則／金額會計、設定與帳號仍須先問（§3）。
- 2026-11-06：新增 §3「Docker 映像保留」規則與 `scripts/docker_cleanup.sh`，每週三 03:30 自動清理超過 7 天的非回滾映像與建置快取（VM 空間整理）。
- 2026-11-06：2026-10-01～10-29 的備份（237 項，177M）已打包為 `backups/archive_20261001-20261029.tar.zst`（66M，逐位元驗證一致）；紀錄表中這些 `backups/...` 路徑需先解壓：`tar -I zstd -xf backups/archive_20261001-20261029.tar.zst -C backups <路徑>`。
- 2026-11-07：新增 §3「開發工具舊版本清理」：`scripts/tools_cleanup.sh` 每週三 03:35 自動清理工具舊版本與 `/tmp/ri-*` 舊暫存（VM 空間整理）。
- 2026-11-07：每週 Docker 與開發工具清理改為每週三 06:00（台灣時間）依序執行。
- 2026-11-08：§3 新增「測試版本」：部署前測候選映像（最新已部署版本＋本次修改，測過即部署同一組映像）；每週三 Debug 測最新已部署正式版。`run_isolated_qa.sh` 新增 `QA_BACKEND_IMAGE` 選項（指定映像、用其內建測試組）。
- 2026-11-08：新增 §3「實作前確認」——所有修改（含小改、bug 修正）動工前都先向業主說明需求理解、做法、影響範圍、分類與測試範圍，確認後才實作；部署前是否要問仍依必問／小改規則。
