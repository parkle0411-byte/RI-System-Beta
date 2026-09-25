# Alpha 原始碼副本（差異測試用）

這些檔案是 Hatchable「RI System (Alpha)」（`proj_FVUqiQUe3m0G`）**v53** 的原始碼，**逐位元組相同**，
不可手動修改。差異測試（`scripts/run_qa.sh calc`）會拿它們當作「標準答案」，與 VM 的 Python 移植版比對。

| 檔案 | 行數 | SHA-256（與 Alpha `list_files` 的雜湊相同） |
|---|---|---|
| `lib/accounting.js` | 135 | `e0acc3c8091b843d89aaa7c52dea5a7aba3be15499d8919b3c61b94fb471ac02` |
| `lib/payment-terms.js` | 248 | `eaaeb93887d057255cc3a2b4ee7fdaf42c3a7dcfbd8aba6561a0e03c1213b248` |
| `lib/case-draft.js` | 385 | `42983151fe3b0ec514abbcad750357ef71d2e2dd7086a9a4d009cd8d54bdd338` |

## Alpha 改了這些檔案時

1. 對 Claude 說「檢查漂移」，它會比對 Alpha 目前的雜湊，告訴你哪些檔案變了。
2. 重新取得新版並確認雜湊相同後，覆蓋這裡的檔案、更新上表與 `MIGRATION-STATUS.md`。
3. 跑 `scripts/run_qa.sh calc`：不一致的地方就是 Python 版要同步修改的地方。
