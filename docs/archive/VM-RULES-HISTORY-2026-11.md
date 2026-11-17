# VM-RULES 歷史紀錄封存（2026-11-17 整併）

> 2026-11-17 依業主決定整併 `VM-RULES.md` 時，把下列原文逐字搬到這裡保存，不再修改：(1) 已失效、已被取代的段落與改寫前的原文；(2) 2026-11-10 以前的「部署與回復紀錄」；(3) 2026-11-10 以前的「近期變更」。現行規則以 `VM-RULES.md` 為準；更早（2026-10-05～11-03）的變更紀錄在 `docs/archive/VM-RULES-CHANGELOG-2026.md`。

## 一、已失效、已被取代或改寫前的段落

### §2
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- **PDF 已退役**：只產生 Word，PDF 由使用者在 Word 匯出；Gotenberg 已移除，`/api/render-document-pdf` 固定回 410。

### §3 部署流程
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- **部署流程（2026-11-17 起，2026-11-11 業主決定）**：實作前確認（含部署同意）→ 實作 → 測試通過 → 備份資料庫（有 migration 再加文件 volume）→ 標記回復映像 → 部署 → 核對正式程式與原始碼逐檔一致 → 在「部署與回復紀錄」加一列 → 回報業主（跑了哪些測試與結果、部署時間、回復方式）。測試通過後不再另問是否部署；2026-11-16 以前照舊（必問項目測試後先問業主）。

### §3 必問
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

  - **必問**（2026-11-16 以前：不論大小，先測試再問業主；2026-11-17 起：在實作前確認時講明風險並問部署時段，測試通過即部署，例外見上）：有 migration 或改資料庫結構；會寫入或修改正式資料（匯入、`--apply` 指令、清除資料）；新規則或改金額／會計；設定開關與帳號（寄信、Audit、排程、權限、帳號）。

### §3 大型測試
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- **大型測試時段與記憶體（2026-11-10 業主決定；2026-11-11 修訂）**：VM 只有 8 GB，測試與正式系統共用。同仁正式使用系統前，壓測（`qa/stress/`）、全部 API／全部畫面測試等大型測試不限時段；正式使用後改在下班後執行（開始正式使用時由業主告知，再更新本條）。跑完檢查 `free -m`，有 swap 時在空閒記憶體大於 swap 用量的前提下執行 `sudo swapoff -a && sudo swapon -a`，把正式系統搬回記憶體（約數分鐘，網站不停）。用不到的測試環境要停止（不刪除）。2026-11-10 停止的 3 組與 `ri-oversea-premium-adj-retry` 已於 2026-11-12 依業主決定刪除（含測試資料 volume）。。

### §3 每週健檢
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- **每週健檢報告（2026-11-13 業主決定）**：`scripts/weekly_health.sh`（唯讀；`--no-log` 只印出，否則附加到 `logs/weekly-health.log`）。每週三 Debug 時執行並向業主報告：主機記憶體／swap／硬碟、容器、映像與備份數量、最慢的 10 個 API（nginx `urt`，容器重建後重新累計）、案件與舊資料筆數、資料庫大小、Accounting「打開時／舊資料歷史／完整清單」三段的時間與大小。Dashboard 或 Accounting 打開超過約 3 秒時提出優化選項（含 `~/RI System/perf-work/round3-20261110` 未部署的共用快取）。（2026-11-16：量測 Accounting 時跳過「須先改密碼」的帳號） 2026-11-17 起 Accounting 改量畫面實際使用的請求（打開清單、All Accounts／Settled/Closed 第 1 頁、下拉名單），每項量第一次與第二次。

### §4.3 新案預設值（與下方 Case Owner／AE 條重複）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- Cedant 與再保人 Tax 預設 1%（AUW Tax 固定 0%）；Case Owner 與 AE 預設建立草稿的登入者，且可依權限各自改選；續保、批單及 Oversea 也相同。

### §4.4 Loss Record（章節引用）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- **Loss Record**：一般及 Swiss CGL QS、Product Recall 的年數、Broker Advised Date 與明細日期／原因／金額缺漏可暫存草稿，於 Review／Announce 檢查；已輸入的無效值仍於儲存時擋下。New 可填 0 年、投保時手動明細須為空；Renew 至少 1 年。其他一般保費 Case 沿用儲存時檢查，Oversea 依 §4.8。Product Recall 手動明細金額須大於 0，Claim 自動明細與續保快照例外見 §7；Additional Loss Record Notes 輸入已隱藏（舊資料保留）。

### §4.8 Oversea（與下一條 AE 重複）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 結構 `OVERSEA`，Class 只能 Fine Art／Terrorism；獨立簡化表單的財務必填項目為 **100% Premium、Share (%)、Brokerage 金額、Reinsurance Broker、Cedant、實際收付款日期**。Currency 隨 Premium 選定，新案預設 USD；負責人與 AE 預帶登入者。不要求一般案件的承保條件、Loss Record、條款。

### §4.8 Oversea（與上一條 AE 重複）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 補充 Insured (EN)、Insured (CN)、Policy Period（日期及時間）與 Account Executive；AE 預帶登入者，可由合格 Personnel 選擇調整。所有列出的輸入欄位均為 Announce 必填，包含中英文被保險人、保單起訖日期與 AE；Draft 可暫存未完成資料。中文被保險人沿用既有 Announce 建立正式主檔規則。Policy Period 與實際收付款日分別保存。

### 部署紀錄表後（STP 規則第一段）
> 改寫前原文（只去掉段首標題，內容逐字移到 §5.2b）

**STP 規則（2026-11-12）**：Stock Throughput 只開放一般 QS，不開放 Facility；險種／TW Ref 代碼 ST。原單採 Property QS 共通流程；100% Premium 與各再保人保費、佣金、稅率、分期及後續會計比照一般 QS，Ceding Commission 必填（0% 時 Cover Note 省略），Cedant Tax 預填 1% 並用於 T1；再保人扣除及稅率各自處理。不另設總 Sum Insured 或計算分保保額；Limit of Liability 為必填多行文字。

### §7（續保與理賠之間多出的分隔線）
> 格式：移到 §7 結尾

---

### §8.7 分頁說明
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 每頁預設100列（50／100／200／500）；?view=list精簡資料，返回頁面先顯示快取並背景更新，更新前財務操作停用。載入失敗（伺服器錯誤、連線中斷）時在表格上方常駐紅色提示與 Retry，不顯示「No matching accounts」；已有上次載入的清單時保留並註明載入時間，財務操作停用到重新載入成功（2026-11-10）。窄螢幕表格橫向捲動，不以左固定欄遮擋操作。

### §12 主檔
> 已失效：這批待確認 Insured 已於 2026-11-12 及 2026-11-17 的資料清理中刪除

- **2026-11-04 舊名單建檔**：依業主指示，自確認後 1,736 筆名單排除勇信兩組及天后闆妹江X諺／江効諺兩版，共 1,732 筆建檔（新增 1,730、沿用 2）。沒有 Announce 保單來源，依現行規則列待確認、不計正式總數；保留原有 4 筆主檔與歷史，匯入後待確認共 1,734。每筆新增有 legacyImport 來源與 Created 歷史、Entity Snapshot；不建立假保單或公告日期。

### §14 System Reference
> 已失效：該 Excel 參考指南已依業主 2026-11-17 決定自 System Reference 回收桶永久清除

- Insured 清單（2026-11-03）：以使用者人工整理的 1,752 筆為基礎，依明確選定的 15 組名稱統一寫法，並去除完全重複的力山工業，整理為 1,736 筆。寶結企業／寶結實業、台耀科技／台燿科技各自保留；勇信貿易／勇信物流組合及天后闆妹的江X諺／江効諺兩版待查原文件，這次不合併。其餘未確認候選繼續分開。該 Excel 參考指南已依業主 2026-11-17 決定自 System Reference 回收桶永久清除；未更動正式主檔或 Case。

### §15 效能
> 改寫前原文：三段快取說明合為一段現況（2026-11-10 版的「＋台北日期」鑰匙已被 2026-11-17 共用快照取代）

- Accounting 舊案歷史結果快取（2026-11-10）：只快取匯入的歷史交易（唯讀、已結清），以「歷史資料指紋（除 original 外全部欄位）＋台北日期」為鑰匙，每 worker 一份；新增的舊案批單／理賠每次重算。回應逐位元組相同；正式 Accounting 第二次打開約 4 秒 → 1.6 秒（每天或歷史資料變動後第一次仍需重算）。`RI_LEGACY_RESULT_CACHE=false` 可關閉。測試 `legacy_accounting_cache`。

### §15 效能
> 改寫前原文：三段快取說明合為一段現況（2026-11-10 版的「＋台北日期」鑰匙已被 2026-11-17 共用快照取代）

- Accounting 伺服器分頁（2026-11-17，§8.7）：已結清歷史在伺服器轉成清單列後快取（每 worker 一份；以台北日期＋歷史的變更指紋（筆數、最大鍵、版本加總、最後更新時間）為準，另每 60 秒最多以完整內容指紋（MD5）複驗一次，直接改資料庫而沒有更新時間的修改最多 1 分鐘後出現；`RI_LEGACY_RESULT_CACHE=false` 時每次重算）；未結清部分每次重算，寫入後下一頁立即反映。量測：正式資料（4,262 列）每頁約 0.2–0.3 秒，當天第一次約 4 秒；1 萬筆舊資料（3 萬列）每頁約 1.6–3 秒（主要是未結清部分重算約 1 秒、資料轉換、篩選排序），當天第一次約 22 秒；仍可再優化（快取歷史部分的篩選排序結果、略過整份轉換），需重跑全部測試。

### §15 效能
> 改寫前原文：三段快取說明合為一段現況（2026-11-10 版的「＋台北日期」鑰匙已被 2026-11-17 共用快照取代）

- **已結清舊資料歷史的共用快照與背景預建（2026-11-17 業主決定）**：All Accounts 第一次載入原本要在請求中重算全部已結清舊資料（6,094 筆約 11–13 秒，每個 worker、每次重啟、匯入或過台北午夜各一次）。改為：(1) 計算結果存成一份共用快照檔（容器 `/tmp/ri-legacy-history`，pickle＋zlib，只有後端自己寫；鑰匙＝計算程式版本（legacy／cases 原始碼雜湊）＋歷史內容指紋），一個 worker 計算、其他讀檔；(2) 已結清歷史**不再隨台北日期重算**（正式資料實測日期往後推 1／400／3,000 天結果全部相同）；(3) 每個 web worker 一條背景執行緒（`legacy/warm.py`），啟動時、歷史有變（每 30 秒檢查輕量指紋）或換日時先把 Accounting 歷史部分建好。回應內容不變。關閉：`RI_LEGACY_HISTORY_SNAPSHOT=false`、`RI_LEGACY_HISTORY_WARM=false`。正式資料副本實測（gunicorn 4 workers）：最慢約 13 秒 → 約 2 秒。「匯入時逐筆存進資料庫」方案實測讀取與重算差不多（6.0 秒對 6.7 秒），不採用。

### §15 效能
> 已失效：量的是已退役的 Accounting 完整清單讀法與 11-02 當時的程式

- 2026-11-02 量測：Accounting 精簡清單第二次打開約 10.2 秒（剩餘主要是讀全部案件約 4 秒）；Production 未快取約 9 秒；Dashboard 第二次約 8 秒。

### §15 舊資料量優化（引用）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

  - 1 萬筆（8,000 已結清＋2,000 未結清）實測：打開到可操作約 38 秒 → 約 5 秒；剩餘時間主要是資料量（6,000 列約 21 MB）。已結清歷史約 79 MB，原為背景載入；2026-11-17 起改為伺服器分頁（上一條）。

### §16 已退役
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- **已退役 Accounting 動作的程式移除（2026-11-12）**：`record_payment`、`reverse_payment`、`edit_payment`、`record_premium_offset`、`record_swiss_offset`、`record_swiss_clearance`、`confirm_swiss_collection`、`unconfirm_swiss_collection`、`confirm_facility_settlement`、`unconfirm_facility_settlement`、`record_allianz_claim_followup`、`record_great_american_claim_followup`、`record_qbe_claim_followup` 共 13 個動作呼叫時仍回 410 `retired_accounting_action`（無 Finance 權限回 403），其處理程式已刪除：`cases/transaction_payments.py` 整檔、`AccountingView.record_payment／reverse_payment`、`facility_accounting.settlement_action`、`swiss_accounting._offset`、三家 `record_followup`。`mark_swiss_statement`（Swiss 結算清單參考號）與既有抵銷／結清紀錄的顯示、餘額計算保留。`/api/render-document-pdf` 整個移除（404）。前端 `AccountingEntryActions.vue` 只剩 Swiss 結算清單參考號。API 網址合併（帳號、文件、主檔）經評估不做：會把各網址的權限設定改成程式內分動作判斷（業主決定）。

### §17 通則
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 歷史交易保持唯讀；依 §17.1 開放新增批單／理賠及其 Accounting 寫入。歷史更正、作廢與撤回 HTTP 寫入仍不開放；匯入自 2026-11-11 起由系統管理員在網頁進行（見上）。

### §17 通則（原首次匯入說明中仍有效的一句）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 所有歷史交易均已完成對帳及結清；Accounting 的已對帳／Settled/Closed 可查，未對帳區不納入；不補造對帳人、對帳日期或銀行收付明細。新舊資料用獨立的來源欄區分，不更動既有 premium／claim 分類。

### §17 通則（原首次匯入說明中仍有效的一句）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 正式首次匯入採業主授權維護程序，核對來源 SHA256、排除清單及 3,693 筆原值。新增批單／理賠及收付流程依 §17.1；受保護交易金額更正留待下一階段。

### §17 舊案專區
> 已失效：2026-11-09 首次匯入的資料已於 2026-11-11 清空

- 以下為 2026-11-09 首次匯入（已於 2026-11-11 清空）的說明，保留供查。

### §17 舊案專區
> 已失效：首次匯入（3,693 筆）的說明，資料已清空；現行匯入規則見 §17.1

- 歷史匯入資料保持唯讀：`2022~2025 Swiss Re (PD).xlsx` 的 Facultative Property，共 **3,693 筆**；原流水號 **F13333 排除、不匯入**。不建立舊案 Case，不產生歷史 Production Report。

### §17 舊案專區
> 已失效：首次匯入的筆數與日期說明；現行收付日期規則見 §17.1「收付」

- 3,663 筆 Swiss Facility、30 筆確實非 Facility（一般付款規則）；不將後者改名或改成 Facility。歷史 Receive Date／Pay Date 是提醒日；無原始約定到期日就留空，不從匯入日重新推算。

### §17 舊案專區（首次匯入的欄位對應，仍適用）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- Description = 英文被保險人；Cedant's Policy No. = Statement No.；Bkg. (in TWD) 是整筆，Re Dept. Bkg. (in TWD) 是 AE，差額歸 Sub AE。13 筆分績保留原金額，不重算。原幣金額、台幣金額、匯率及原始 Excel 保留。

### §17 舊案專區
> 改寫前原文：改成 §17.1 標題

- **網頁匯入 Register（2026-11-11 業主決定）**：

### §17 舊案專區
> 改寫前原文：只取消縮排，內容逐字移到 §17.1

  - 限 System Administrator，在 Legacy 分頁 Import Register 上傳 Register（工作表 `Facultative`）→ 預覽 → 確認匯入（核對 SHA256）。**不保留上傳記錄**（2026-11-17 業主決定）：沒有上傳清單與原始檔下載；匯入成功後刪除暫存 Excel、清空預覽內容，批次只留匯入筆數作為「匯入交易」的內部標記；未匯入的預覽在 Clear／關閉對話框／同一人重新預覽時丟棄（狀態 withdrawn、刪檔），他人超過一天的預覽也會丟棄。每筆交易的 Original Excel Data 照舊保留。預覽有任何錯誤或警告都不能匯入；沒有新交易可匯入時也不能確認。不提供網頁撤回；匯錯以業主授權維護程序處理。可分批匯入各再保人的 Register；已匯入的流水號自動略過。

### §17 舊案專區
> 改寫前原文：只取消縮排，內容逐字移到 §17.1

  - **清單排序**（2026-11-17 業主決定）：依 Transaction No. 由大到小——沒有編號的草稿最前（新的在前），再來網頁新增的 LTX 編號（大到小），最後是匯入的 Register 流水號（依數字部分大到小，例如 F18329、F17763、F2898）。

### §17 舊案專區
> 改寫前原文：只取消縮排，內容逐字移到 §17.1

  - Class 依 Master Data Management 的 Class 代碼比對（2026-11-16 業主決定；不分大小寫），險種名稱用 MDM 名稱，Register 原代碼照存；Register 的 PD 視同 MDM 的 PF（Property）；MDM 沒有的代碼為錯誤；已停用的 Class 為警告（須先在 MDM 重新啟用）；非 Property 列的再保人若為 Allianz／Great American／QBE Facility（新系統這三種 Facility 規則只適用 Property）為警告，不設放行清單；Legacy Dashboard 依每筆存的險種顯示，Production 的 Class 依 §9（Property 一律 PD）；Fac / Claim 必填；不再限定已結清。業主指定的排除（`import_exclusions.json`，F13333）與更正（`import_corrections.json`，F2898：Fac / Claim＝Fac、New / Renew＝New）在預覽列出，原始 Excel 值保留。

### §17 舊案專區
> 改寫前原文：只取消縮排，內容逐字移到 §17.1

  - 欄位：Reinsurer's Ref. No.＝Reinsurer Ref.；Effective Date 顯示在 Accounting「Transaction / SoA / TW Ref」日期位置（理賠用 DOL），與新系統邏輯相同；Revenue Month＝Production 月份（2026-11-15 起：保費列與批單列依此月份列入 Production；起始月 2026-11 以前視為已認列的歷史月份，理賠不列入）；Cedant／Reinsurer Receipt／Payment No.＝Accounting Dept. Ref.；New / Renew＝新案／續保；Installment No.＝分期（顯示，不改交易編號）；Issue Date 不匯入；未使用欄位保留在原始資料。

### §17 舊案專區
> 改寫前原文：只取消縮排，內容逐字移到 §17.1

  - 收付：Cedant Receipt No／Cedant Payment No 有填＝Cedant 方已收付；Reinsurer Receipt No／Reinsurer Payment No. 有填＝再保人方已收付（理賠方向相反）。已收付方建立收付登錄（Accounting Dept. Ref.＝該編號；保費列日期＝Receive Date／Pay Date，理賠列＝Closed Month 月底），標示 Settled before import，不可沖回。全部已收付的列為歷史已對帳／結清；仍有未收付方的列成為可追蹤帳款，已收付方視為匯入前已對帳，未收付方依新系統各再保人規則計算到期日（理賠以 Issue Date of Claim 為理賠建立日，到期日＝其後 15 天、提醒日提前 7 天，與新案相同；未收付理賠缺 Issue Date of Claim 時預覽警告、不能匯入），走一般對帳與收付流程。

### §17 舊案專區
> 改寫前原文：只取消縮排，內容逐字移到 §17.1

  - 匯入列不建立 Case、不能退回草稿或編輯業務資料；保費列與批單列依 Revenue Month 列入 Production 與 Dashboard（2026-11-15，見 §9 起始月）。

### §17 舊案專區
> 改寫前原文：只取消縮排，內容逐字移到 §17.1

  - Accounting 對象名稱（2026-11-13 業主決定）：任何名稱結尾帶「(Facility)」者在 Accounting 一律顯示不含「(Facility)」的名稱（歷史列、未結清列與新案相同，同一公司只有一個對象名稱）；舊資料本身仍保留完整名稱與 Facility／一般付款規則的區分。

### §17 舊案專區
> 改寫前原文：只取消縮排，內容逐字移到 §17.1

  - 從匯入列新增批單／理賠時沿用來源險種（GL 匯入列新增的仍為 CGL；2026-11-11 修正）。

### §17 舊案專區
> 改寫前原文：只取消縮排，內容逐字移到 §17.1

  - R/I Comm. %／Tax %（2026-11-11）：匯入時由 Register 公式「Our Share Premium × 固定比率」讀出（只辨識公式文字，不執行）；直接填數值者以金額 ÷ 承接保費換算；比率 × 承接保費與金額不符或公式無法辨識時預覽警告、不能匯入。理賠不存比率。Legacy 明細顯示；從匯入列新增批單時預帶來源比率（可修改）。舊交易金額仍以 Excel 為準。

### §17.1 批單與理賠
> 已合併：17.1 與 17.2 合為一節，被 17.2 取代的字句已刪除

- 2026-11-12 起新增批單／理賠依 §17.2；與本節不同處以 §17.2 為準。

### §17.1→17.2（Old Reference 改為鎖定，依 17.2）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 從 confirmed 舊交易帶入資料；Old Reference 可修改，保留原來源交易關聯及案號快照。新交易只有 Endorsement／Claim；不建立 Case。草稿只由建立者編輯、確認；首次確認產生 `LTX-YYYY-000001`，確認年度採台灣年度。未對帳、無收付歷史且未進已關帳 Production 的交易，建立者可退回草稿；再次確認沿用原號。

### §17.1→17.2（期間與編號依 17.2）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- Endorsement 與 Claim 分開登錄；批單 Effective Date 為本次批單生效日，Expiry Date 固定保留來源到期日，前者不得晚於後者。Endorsement No. 確認前必填。實際確認時已超過來源到期五年者須選原因；Only Other 另須補充說明；原因由管理員維護並留痕。

### §17.1→17.2（Share 鎖定，依 17.2）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 批單手填 100% Premium、Share (%)、R/I Commission (%)、Tax (%)、原幣 Brokerage 金額；先取位 Our Share Premium，再算佣金與稅；淨額與既有 Leg 算式相同。Bkg.(%) 依金額反推；零承接保費且有 Brokerage 時用正／負100%顯示並填原因。AE/Sub AE 沿用已核准分績與原幣、台幣尾差規則。Brokerage 手填、付再保人金額由 Brokerage 倒推，是舊資料與新系統（T3＝T1−T2 由系統計算）的刻意差異（2026-11-14 業主確認）。

### §17.1→17.2（DOL 期間依 17.2）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 理賠只填本筆承接賠款，不計佣金、稅、Brokerage 或處理費，兩邊金額相等；DOL 必填且須落在來源 Effective Date 至 Expiry Date（含首尾）內。允許負數退回賠款，不必連結原理賠，負數必填原因。負數向 Cedant 收回後才退還再保人；正負理賠均不得先墊付超過該筆已回收賠款（含既有合法抵銷）。理賠不填 Revenue Month，不進 Production。

### §17.1→17.2（匯入已改網頁、筆數已失效）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 新交易確認後接到既有 Accounting 對帳、原幣收付、部分賠款、同對象跨幣別、兩方向分開實際收付、部分收付及整批沖回；停止新增抵銷，保留歷史抵銷。正式歷史 3,693 筆維持已對帳／已結清，不補造銀行或覆核事件；仍不提供歷史更正、作廢、匯入或撤回寫入。

### §17.1→17.2（Revenue Month 改自動，依 17.2）
> 改寫前原文（現行寫法見 VM-RULES.md 同一章節）

- 批單 Revenue Month 手動選尚未關帳月份、不預設；使用該月共用匯率，不提供逐筆覆寫。缺匯率不擋確認及原幣 Accounting；未關帳隨月匯率更正重算，關帳需補齊匯率並凍結台幣快照；不從 Production 排除操作改變選定月份。

### §17.1 批單與理賠
> 已失效：部署當時的說明；權限現況見 §17 通則

- 本版新增號碼計數與原因表，調整新交易資料表寫入權限；獨立 Legacy Audit 保持 append-only。全域 Audit 暫停、SMTP 關閉、固定技術棧及無對外文件／交易附件維持。

### §17.1 批單與理賠
> 已失效：部署當時的測試紀錄；受保護交易金額更正尚未開放已寫在 §17 通則

- 已完成同一組候選映像全部 105 組 API、268 項畫面測試後取得業主部署確認。已對帳或有收付歷史等受保護交易的業務金額更正留下一階段；本版只開新增與收付，以及符合條件者退回草稿。

### §17.1／§17.2 標題
> 改寫前原文：兩節合為 §17.2

### 17.1 批單與理賠（2026-11-10 業主確認部署）
### 17.2 新增批單／理賠規則（2026-11-12 業主決定）

### 部署紀錄表註腳
> 改寫前原文

（回復映像標籤指 `ri-backend:` 與 `ri-frontend:` 兩個映像。「有」表示當次有備份但原紀錄未寫檔名。完整驗證細節見封存的變更紀錄。）

## 二、部署與回復紀錄（2026-10-05～2026-11-10，由新到舊）

| 日期 | 項目 | 備份 | 回復映像標籤 | 驗證摘要 |
|---|---|---|---|---|
| 11-10 | Accounting 載入失敗時常駐錯誤＋Retry（只換前端）；畫面測試加 X 專項 | `backups/accounting_load_error_20261110_234645` | `ri-frontend:before-accounting-load-error-20261110_234645` | 前端建置、完整畫面 281 項（含 X 9 項）；後端與資料不變（業主決定不跑 API） |
| 11-10 | 每週 Debug＋優化：舊案清單頁碼上限、Great American 稅率依名稱比對、舊案網址無 W002 警告、Accounting 舊案歷史快取、nginx 記錄回應時間、畫面測試併入 L | `backups/debug_fixes_1110_20261110_190455` | `ri-backend:before-debug-fixes-1110-20261110_190455`／`ri-frontend:before-debug-fixes-1110-20261110_190455` | 候選映像 111 組 API、272 項畫面（含 L）；正式資料 Accounting 回應逐位元組相同；無 migration、無資料寫入 |
| 11-10 | Facility 選填、固定 Interest、Property QS 與 Great American 再保人 Tax | `backups/facility_input_20261110_164509` | `ri-backend:before-facility-input-20261110_164509`／`ri-frontend:before-facility-input-20261110_164509` | 109 組 API、完整畫面及 Facility 13 項、實際 Word；無 migration |
| 11-10 | Accounting 收付方向間距與金額同行顯示（純版面） | `backups/accounting_cash_inline_20261110_153917` | `ri-frontend:before-accounting-cash-inline-20261110_153917` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 84 項通過；後端與資料庫容器不變，無資料寫入 |
| 11-10 | Accounting Cash Amount 欄寬縮窄（純版面） | `backups/accounting_cash_tight_20261110_152756` | `ri-frontend:before-accounting-cash-tight-20261110_152756` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 81 項通過；後端與資料庫容器不變，無資料寫入 |
| 11-10 | Accounting Cash Amount 欄寬縮窄（純版面） | `backups/accounting_cash_narrow_20261110_152228` | `ri-frontend:before-accounting-cash-narrow-20261110_152228` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 81 項通過；後端與資料庫容器不變，無資料寫入 |
| 11-10 | Accounting Record Selected 整體欄寬壓縮（純版面） | `backups/accounting_payment_compact_20261110_151700` | `ri-frontend:before-accounting-payment-compact-20261110_151700` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 78 項通過；後端與資料庫容器不變，無資料寫入 |
| 11-10 | Accounting 兩個彈窗補日期、識別順序與清單統一（純顯示） | `backups/accounting_dialog_date_20261110_150012` | `ri-frontend:before-accounting-dialog-date-20261110_150012` | 前端建置、畫面 A 56 項及 Accounting 桌面／手機 49 項通過；後端與資料庫容器不變，無資料寫入 |
| 11-10 | Oversea Effective Date 取號與 Yageo TW Ref. 更正，保留舊提醒週期 | `backups/oversea_effective_ref_20261110_145449` | `ri-backend:before-oversea-effective-ref-20261110_145449`／`ri-frontend:before-oversea-effective-ref-20261110_145449` | 108 組 API、272 項畫面；原單、2 筆 T3 與批單草稿一致，金額／日期／歷史／附件不變 |
| 11-10 | Accounting：實際對象篩選、跨幣別對帳、實際現金部分收付與失敗重試 | `backups/accounting_cash_20261110_104729` | `ri-backend:before-accounting-cash-20261110_104729`／`ri-frontend:before-accounting-cash-20261110_104729` | 107 組 API、270 項整合畫面＋43 項 Accounting；既有金額、收付、文件指紋一致，無資料轉換／migration |
| 11-10 | Legacy 批單／理賠、Accounting、Production；migration legacy.0002 | `backups/legacy_entry_20261110_100701` | `ri-backend:before-legacy-entry-20261110_100701`／`ri-frontend:before-legacy-entry-20261110_100701` | 105 組 API、268 項畫面；歷史 3,693 筆／既有業務／文件指紋一致，權限及原始碼核對通過 |
| 11-09 | Oversea Announce 必須上傳外國 RI Broker Note（cases.0012） | `backups/oversea_broker_notes_20261109_141138` | `ri-backend:before-oversea-broker-notes-20261109_141138`／`ri-frontend:before-oversea-broker-notes-20261109_141138` | 整合最新舊案唯讀版，102 組 API、253 項畫面及 migration 升降級通過；正式業務資料／文件不變 |
| 11-09 | 舊案專區第一版唯讀；Swiss Re 3,693 筆，排除 F13333 | `backups/legacy_readonly_20261109_091930` | `before-legacy-readonly-20261109_091930` | 101 組 API、245 項既有畫面、5 項舊案畫面；正式逐筆核對；新案與報表資料未改寫 |
| 11-06 | 批單 Reinsurer Ref. 開放輸入與修改 | `backups/endorsement_reinsurer_ref_20261106_195915` | `ri-frontend:before-endo-ref-20261106_195915` | 100組API、全畫面及4項參考號碼保存檢查；後端與資料維持 |
| 11-06 | Oversea 比例分期、正負 Brokerage 批單 | `backups/oversea_workflows_20261106_194002` | `ri-backend:before-oversea-workflows-20261106_194002`／`ri-frontend:before-oversea-workflows-20261106_194002` | 100 組 API、241 項畫面、4017 組計算比對；正式資料／設定／文件指紋一致，保留最新版本 |
| 11-06 | Accounting 五分頁、全選、對帳批次整合、SoA與日期及彈窗篩選 | `backups/accounting_refinement_20261106_150148` | `ri-backend:before-accounting-refinement-20261106_150148`／`ri-frontend:before-accounting-refinement-20261106_150148` | Accounting完整98組API＋整合13組；完整畫面200項、Oversea23項、Accounting26項；正式帳務資料指紋一致 |
| 11-06 | Dashboard 五年度選單、並排柱狀趨勢與五年帳款說明 | `backups/dashboard_year_20261106_144415` | `before-dashboard-year-20261106_144415` | 依業主確認的相關 6 組 API、13 階段畫面與 Oversea 專項通過 |
| 11-06 | Dashboard 移除頂端重複 FX 提醒（純顯示） | `backups/dashboard_fx_notice_20261106_141715` | `ri-frontend:before-dashboard-fx-20261106_141715` | 前端建置、dashboard_api、畫面 A＋G 通過；保留欄內 Awaiting FX |
| 11-05 | Oversea：所有輸入欄位改為 Announce 必填，含中英文被保險人、Policy Period、AE | `backups/oversea_required_20261105_205152` | `ri-backend:before-oversea-required-20261105_205152`／`ri-frontend:before-oversea-required-20261105_205152` | 全 API 97 組／全畫面 13 階段＋Oversea 專項；正式資料、設定與文件指紋一致 |
| 11-05 | Accounting 識別欄固定左側及不透明背景（純版面） | `backups/accounting_scroll_20261105_202326` | `ri-frontend:before-accounting-fixed-20261105_202326` | 前端建置、桌面／手機／四分頁捲動驗證通過；後端與資料不變 |
| 11-05 | Key-in Class 改稱 Insurance Type | `backups/insurance_type_label_20261105_201703` | `ri-frontend:before-insurance-type-label-20261105_201703` | cases_api＋畫面 A；只改標籤 |
| 11-05 | Accounting 表格上方同步橫捲軸、右側常駐直捲軸及固定表頭（純版面） | `backups/accounting_scroll_20261105_201247` | `ri-frontend:before-accounting-scroll-20261105_201247` | 前端建置、桌面／手機／四分頁捲動驗證通過；後端與資料不變 |
| 11-05 | Oversea Account 名稱：清單及案件頁首優先顯示 Insured (EN) | `backups/oversea_account_name_20261105_200903` | `ri-backend:before-oversea-name-20261105_200903`／`ri-frontend:before-oversea-name-20261105_200903` | 相關 API 2 組／畫面 A＋O 22 項；正式資料、設定與文件指紋一致 |
| 11-05 | Accounting 表格上方同步橫捲軸、右側常駐直捲軸及固定表頭（純版面） | `backups/accounting_scroll_20261105_200401` | `ri-frontend:before-accounting-scroll-20261105_200401` | 前端建置、桌面／手機／四分頁捲動驗證通過；後端與資料不變 |
| 11-05 | Oversea：Insured (EN/CN)、Policy Period、AE；Reinsurance Type 更名 | `backups/oversea_details_20261105_195139` | `ri-backend:before-oversea-details-20261105_195139`／`ri-frontend:before-oversea-details-20261105_195139` | 全 API 97 組／全畫面 13 階段＋Oversea 專項；正式資料、設定與文件指紋一致 |
| 11-05 | Oversea Business：獨立 T3 與實際日減 10 天（migration cases.0011） | `backups/oversea_business_20261105_152643` | `ri-backend:before-oversea-20261105_152643`／`ri-frontend:before-oversea-20261105_152643` | 全 API／全畫面＋Oversea 專項；正式業務資料與文件指紋一致 |
| 11-05 | Class 排序加入 Fine Art | `backups/case_class_fine_art_20261105_105708` | `ri-frontend:before-class-fine-art-20261105_105708` | cases_api＋畫面 A；只改排序，維持開放範圍 |
| 11-05 | Case Class 固定顯示順序 | `backups/case_class_order_20261105_104946` | `ri-frontend:before-class-order-20261105_104946` | cases_api＋畫面 A；維持既有開放範圍及後端 |
| 11-05 | Case 畫面暫限 QS＋Property／CGL | `backups/case_entry_scope_20261105_103522` | `ri-frontend:before-case-entry-20261105_103522` | 6 組案件／文件測試＋畫面 A；後端及資料維持 |
| 11-05 | CGL Coverage 新增 Products Liability | `backups/cgl_coverage_20261105_091135` | `ri-backend:before-cgl-coverage-20261105_091135`／`ri-frontend:before-cgl-coverage-20261105_091135` | 依業主限定範圍：11 組 CGL／案件／文件測試＋畫面 A；資料指紋一致 |
| 11-04 | System Reference 共用拖拉排序 | `backups/reference_sort_20261104_151714` | `ri-backend:before-reference-sort-20261104_151714`／`ri-frontend:before-reference-sort-20261104_151714` | 95 組 API、完整畫面回歸、拖拉／鍵盤／跨帳號／衝突測試；正式資料庫未改 |
| 11-04 | Accounting 四分頁、批次對帳、淨額收付與案件更正（migration cases.0010） | `backups/accounting_workflow_20261104_104120` | `ri-backend:before-accounting-workflow-20261104_104120`／`ri-frontend:before-accounting-workflow-20261104_104120` | 94 組 API、13 階段 193 項畫面、24 項 Accounting 操作、3,017 組金額；正式資料指紋一致 |
| 11-03 | Insured Excel 人工確認名稱（1,736 筆） | `backups/insured_confirmed_20261103_161951` | `ri-backend:before-insured-confirmed-20261103_161951` | 僅更新參考檔；逐筆核對、9 份指南下載、權限及回收筒檢查通過，應用程式碼未變 |
| 11-03 | Insured Excel 尾綴整理（1,752 筆） | `backups/insured_suffix_20261103_155823` | `ri-backend:before-insured-suffix-20261103_155823` | 僅更新參考檔；逐筆核對、9 份指南下載、權限及回收筒檢查通過，應用程式碼未變 |
| 11-03 | Insured 公告登錄與變更確認 | `backups/insured_announced_20261103_145940` | `before-insured-announced-20261103_145940` | 89 組 API、桌面／手機、資料指紋一致 |
| 11-03 | MDM 整合 Insured 與組合識別 | `backups/mdm_insured_20261103_110207` | `before-mdm-insured-20261103_110207` | 88 組 API、桌面／手機、資料指紋一致 |
| 11-03 | 移除 Treaty（migration cases.0009） | `backups/ri_system_before_notreaty_20261103_091700.sql` | `before-notreaty-20261103_091700` | 87 組、13 階段畫面 |
| 11-02 | Accounting 安全優化 | 有 | `before-perf2-20261102_113609` | 86 組、逐位元組相同 |
| 11-02 | Key-in 後續與純 Facility 文件 | `backups/case_keyin_refinement_20261102_091603` | | 181 項瀏覽器、68 項後端 |
| 10-30 | Case Key-in 卡片整合 | `backups/case_keyin_ui_20261030_154815` | | 169 項瀏覽器 |
| 10-30 | 批單 Note Order Hereon 兩位小數 | `backups/endo_note_order_percent_20261030_144839` | | 24 項批單 Word |
| 10-30 | Allianz 新提醒日 | `backups/allianz_reminder_20261030_142031` | | 86 組、612 項日期 |
| 10-30 | 批單逐區塊 Edit | `backups/endorsement_sections_20261030_111553` | | 111 項瀏覽器 |
| 10-30 | CGL Aggregate／多筆 Retroactive | `backups/cgl_aggregate_retroactive_20261030_102739` | | 85 組 |
| 10-29 | 效能優化（每件案件快取等） | 有 | `before-perf-20261029_190315` | 逐位元組相同 |
| 10-29 | 全系統檢查修正 | 有 | `before-review-fixes-20261029_165222` | 82 組、13 階段 |
| 10-29 | 時間連動與 Review 內上傳 | `backups/case_review_time_20261029_145939` | | 81 組、58 項瀏覽器 |
| 10-29 | 批單 Debit／Credit Note | 有 | `before-endorsement-notes-20261029_123929` | |
| 10-29 | Construction 文件分頁 | `backups/construction_layout_20261029_092924` | | |
| 10-29 | Property Construction | `backups/property_construction_20261029_091425` | | |
| 10-28 | Placing Slip 排版修正 | `backups/placing_layout_20261028_212934` | | 49 項 |
| 10-28 | Placing Slip（migration cases.0008） | `backups/placing_slip_20261028_211640` | | 80 組、47 項 Placing |
| 10-28 | 批單與全保期平均續保 | `backups/endorsement_20261028_151317` | | 80 組、22 項瀏覽器 |
| 10-27 | Debug 修正版 | `backups/debug_fixes_20261027_232757` | | 79 組 |
| 10-16 | Accounting 精簡清單 | 有 | `before-lean-20261016_120011` | 11 組、13 階段畫面 |
| 10-15 | Dashboard／Production 快取 | 有 | `before-cache-20261015_221400` | 逐位元組相同、53 組 |
| 10-15 | Accounting 共用計算＋gzip | 有 | `before-accel-20261015_203721` | 回應逐位元組相同、52 組 |
| 10-15 | Accounting 表格分頁 | 有 | `before-paging-20261015_184454` | 13 項分頁、185 項畫面 |
| 10-15 | gunicorn 4 worker、MySQL 512MB | 有 | `before-workers4-20261015_180259` | 壓測、各表筆數相同 |
| 10-14 | 全面除錯修正 | `backups/ri_system_before_debug_round2_20261014_132129.sql` | `before-debug-round2-20261014_132129` | 49 組測試 |
| 10-05 | Audit 暫停、清除 264 筆 | `backups/ri_system_before_audit_clear_20261005_142025.sql` | | |

（回復映像標籤指 `ri-backend:` 與 `ri-frontend:` 兩個映像。「有」表示當次有備份但原紀錄未寫檔名。完整驗證細節見封存的變更紀錄。）

## 三、近期變更（2026-11-03～2026-11-10，由新到舊）

- 2026-11-10：Accounting 載入失敗時常駐紅色提示與 Retry，保留上次清單並停用財務操作；不再顯示「0 筆」（業主確認部署）。
- 2026-11-10：§3 新增「大型測試時段與記憶體」：大型測試下班後跑、跑完把 swap 搬回記憶體；停止 3 組已不使用的測試環境（不刪除）。
- 2026-11-10：每週 Debug＋優化（業主確認部署）：舊案清單頁碼超大時回空白頁（原本伺服器錯誤）；已公告案件的 Great American 原稅率改依再保人名稱比對（調換／刪除其他再保人不再誤擋，新原單／續保仍固定 0%）；舊案網址寫法調整（網址不變）；Accounting 舊案歷史結果快取（逐位元組相同）；nginx 記錄回應時間；`run_ui_test.sh` 完整執行加入舊案 L 專項。
- 2026-11-10：依業主確認部署 Facility 共通欄位、Property QS 畫面及 Great American 再保人 Tax 規則；續保 0%，批單沿用來源稅率。
- 2026-11-10：Accounting Record Selected 減少 Direction／Outstanding 留白，Cash Amount 幣別及數字改同行顯示。
- 2026-11-10：Accounting Record Selected 的 Cash Amount 欄寬縮至 105px，驗證八位數金額可完整顯示；不改帳款或收付。
- 2026-11-10：Accounting Record Selected 的 Cash Amount 欄寬縮至 125px，驗證八位數金額可完整顯示；不改帳款或收付。
- 2026-11-10：Accounting Record Selected 壓縮所有欄寬及留白、長文字換行；僅改版面，不改帳款或收付。
- 2026-11-10：Accounting 的 Finance account review／Record Selected 補顯示與主清單相同的日期，識別資訊同序；純前端顯示修正，未更動日期計算、帳款或收付。
- 2026-11-10：業主核准 Effective Date 取號及 Yageo 原單與兩筆 T3／批單草稿的關聯編號更正；已整合最新舊案及會計版本，完成驗證、備份、部署與 Yageo 更正。
- 2026-11-10：依本 session 業主核准部署 Accounting 現金收付改版；同對象跨幣別整批對帳、各幣別及方向分開實收付、全部現金帳款允許部分收付、停止新增抵銷、失敗列重試防重複；Oversea 收齊後歸 Brokerage。保留最新舊案新增收付與 Oversea 功能，既有金額與收付歷史未改寫。
- 2026-11-10：業主確認部署 Legacy Data (Old Register) 新增批單／理賠、原幣收付及批單 Production；既有 3,693 筆歷史唯讀不重算，受保護業務金額更正留下一階段。
- 2026-11-09：業主核准先備份後部署 Oversea Broker Note 必要附件；已整合最新正式舊案唯讀版，完成回歸、備份與部署。
- 2026-11-09：依業主確認部署舊案專區唯讀版，匯入 Swiss Re 歷史交易 3,693 筆；F13333 排除；歷史已對帳／已結清；新增、更正及收付寫入未開放。
- 2026-11-08：新增 §3「實作前確認」——所有修改（含小改、bug 修正）動工前都先向業主說明需求理解、做法、影響範圍、分類與測試範圍，確認後才實作；部署前是否要問仍依必問／小改規則。
- 2026-11-08：§3 新增「測試版本」：部署前測候選映像（最新已部署版本＋本次修改，測過即部署同一組映像）；每週三 Debug 測最新已部署正式版。`run_isolated_qa.sh` 新增 `QA_BACKEND_IMAGE` 選項（指定映像、用其內建測試組）。
- 2026-11-07：每週 Docker 與開發工具清理改為每週三 06:00（台灣時間）依序執行。
- 2026-11-07：新增 §3「開發工具舊版本清理」：`scripts/tools_cleanup.sh` 每週三 03:35 自動清理工具舊版本與 `/tmp/ri-*` 舊暫存（VM 空間整理）。
- 2026-11-06T19:59:35+08:00：修正批單 Reinsurer Ref. 被前端停用的問題，直接開放輸入與修改；維持原本人工填寫、不新增原單號碼自動繼承。公告後仍用 Case SoA／Accounting 的 Edit references，既有權限及對帳／財務狀態不變。測試通過後依既有規則bug修正流程部署。
- 2026-11-06：業主核准 Oversea 比例分期與正負 Brokerage 批單部署；保留最新 Accounting、Dashboard 及 Docker 映像清理規則。
- 2026-11-06：2026-10-01～10-29 的備份（237 項，177M）已打包為 `backups/archive_20261001-20261029.tar.zst`（66M，逐位元驗證一致）；紀錄表中這些 `backups/...` 路徑需先解壓：`tar -I zstd -xf backups/archive_20261001-20261029.tar.zst -C backups <路徑>`。
- 2026-11-06：新增 §3「Docker 映像保留」規則與 `scripts/docker_cleanup.sh`，每週三 03:30 自動清理超過 7 天的非回滾映像與建置快取（VM 空間整理）。
- 2026-11-06：已部署Accounting五分頁、Open／Settled顯示、篩選、跨頁全選、彈窗移除列與選填證據、同對象同幣別整批對帳及SoA／日期顯示；保留最新Dashboard年度圖表。
- 2026-11-06：Dashboard 增加近五年年度選擇與左右並排年度柱狀圖；保留目標折線，縮短缺匯率及五年帳款說明。
- 2026-11-06：依業主決定，Dashboard 的顯示、查詢與資料整合列局部修改，只跑相關測試，不因涉及 Dashboard 就跑完整回歸；已修正 §3 分級。
- 2026-11-06：Dashboard 移除頂端重複缺匯率提醒；Accounting · Receivable / Payable 保留 Awaiting FX，金額與匯率邏輯維持。
- 2026-11-05：依業主確認，Oversea 所有列出的輸入欄位均為 Announce 必填；補上中英文被保險人、Policy Period 起訖日及 AE 的前後端檢查與必填標示。TW Ref. 與 Accounting Date 仍自動產生。
- 2026-11-05：Accounting 的 Transaction／SoA／TW Ref 與勾選欄固定左側，使用不透明底色遮住捲動資料；手機識別欄縮為180px。
- 2026-11-05：Accounting 四分頁主表增加頂部同步橫捲軸，表身最高 65% 視窗（240–720px），固定表頭、右側捲軸常駐；只調整版面。
- 2026-11-05：修正 Oversea Business 的 Account List 與案件頁首名稱，優先顯示已填 Insured (EN)；未填名稱才顯示 Oversea Business。
- 2026-11-05：Accounting 四分頁主表增加頂部同步橫捲軸，表身最高 65% 視窗（240–720px），固定表頭、右側捲軸常駐；只調整版面。
- 2026-11-05：Oversea Business 補上 Insured (EN/CN)、Policy Period 與 AE；畫面 Reinsurance Structure 統一改名 Reinsurance Type。分期與批單另階段處理。
- 2026-11-05：新增 Oversea Business／Fine Art、Terrorism 的簡化輸入、直接 Brokerage T3、實際收付款日減 10 天 Accounting Date；不生成文件，不影響一般 QS。部署狀態以部署與回復紀錄為準。
- 2026-11-05T10:57:16+08:00：Fine Art 排在 Jewelers Block 之後、Terrorism 之前；Class 開放範圍維持 Property／CGL。
- 2026-11-05T10:49:55+08:00：Case Class 依指定九類順序排序；目前仍只開放 Property／CGL，不改主檔或後端。
- 2026-11-05T10:35:30+08:00：Case key-in 暫時只開放 QS＋Property／CGL；僅限畫面選項與操作入口。後端支援維持，無migration。
- 2026-11-05：CGL Coverage 新增獨立選項 Products Liability，位於 Products & Completed-Operation Liability 與 Personal & Advertising Injury Liability 之間；同步前後端選項與文件文字。
- 2026-11-04：System Guides 與 Document Templates 新增全體共用拖拉／鍵盤排序、持久保存及衝突保護。
- 2026-11-04：部署前測試範圍改為依影響範圍分級——局部修改只跑相關測試組＋畫面 A 階段；碰到共用部分才跑全部；不確定先問業主；每週三 Debug 補跑全部；只加減選單選項或改文字也算局部（§3）。
- 2026-11-04：部署確認規則放寬——小改（參考檔／指南、純畫面文字版面、不改結果的效能優化、修既有規則 bug）測試通過即部署、事後告知；migration、正式資料寫入、新規則／金額會計、設定與帳號仍須先問（§3）。
- 2026-11-04：Accounting四分頁、財會對帳批次、跨案淨額收付／純抵銷、整筆沖回重登、各家獨立鎖定與原匯率Production更正；已部署並核對正式來源。
- 2026-11-04：舊 Insured 名單匯入 1,732 筆（新增 1,730、沿用 2，排除 4 筆），列待確認；備份 `backups/insured_legacy_import_20261104_092626`。
- 2026-11-03：文件整理——改為依主題的現行規則；舊變更紀錄封存到 `docs/archive/VM-RULES-CHANGELOG-2026.md`；刪除「2026-09 規則決定（Alpha 對照）」表。
- 2026-11-03：移除 Treaty 部署（migration cases.0009）。
- 2026-11-03：Master Data Management 整合 Insured；完整中文組合忽略成員排列，Case 改組合改連結、真正更名留歷史；台北時間到秒。
- 2026-11-03：Insured 僅在成功 Announce 登錄；公告後改名須分類確認，任一部分 Confirmed 需走批單；舊資料待確認且不計正式筆數，頁面唯讀。
- 2026-11-03：System Guides 新增 Insured 清單（1,758 筆），隔離 89 組及指南下載／權限／回收筒檢查通過；備份 `backups/insured_guide_20261103_154603`，回復映像 `ri-backend:before-insured-guide-20261103_154603`。
- 2026-11-03：依業主更正，Insured 參考清單只刪除各名稱尾端指定字眼；4,396 筆整理為 1,752 筆，保留原名與刪字明細。
- 2026-11-03：依業主選定 15 組保留名稱，Insured 人工名單由 1,752 筆整理為 1,736 筆；未確認組合保留待查，附人工原名與統一名稱明細。
