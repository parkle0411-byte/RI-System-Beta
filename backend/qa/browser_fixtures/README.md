# 瀏覽器測試用的準備資料腳本（不是測試組）

這裡的腳本會在拋棄式 QA 資料庫「提交」合成資料或建立登入 session，供實際瀏覽器檢查使用。
它們不是測試組，所以不放在 `qa/suites/`（`scripts/run_isolated_qa.sh` 會把 suites 裡每個檔案都當成測試執行）。

- `accounting_browser_seed.py`：建立 Accounting 92 項規則的瀏覽器檢查資料（AR92-UI-*）。
- `accounting_browser_sessions.py`：在上一支建立資料後，輸出 Finance／Sales 測試帳號的 session 與案件編號。
