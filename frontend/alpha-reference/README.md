# Alpha 前端原始檔（對照用，不參與建置）

Hatchable「RI System (Alpha)」`proj_FVUqiQUe3m0G` **v53** 的前端原始檔，逐位元組相同（SHA-256 與 Alpha `list_files` 一致）。
VM 的 Vue 元件是照這些檔案移植的；Alpha 之後改了畫面，先比對雜湊，再把差異同步到 `src/`。

| 檔案 | SHA-256 | VM 位置 |
|---|---|---|
| `index.html` | `72de4a046c42d0dc6acc3eae3773975f8bfea8aa675e639fc50c29efe8383e00` | 模板拆到 `src/App.vue`、`src/views/*.vue` |
| `app.js` | `a2427dcb41711e94ddacee421a93b560075f414891a72b033ffaa858e2190427` | 邏輯拆到 `src/alpha/*.js`、`src/views/*.vue` |
| `theme.css` | `af2b57f00c38672822d5364aebd4c2044662545cdb61d1b75b5dec0371817bf5` | `src/alpha/styles/theme.css`（原樣） |
| `overview.css` | `bceafbf2f74c2daf1d1608471304e346b637e154d3c1ae1294e483e35529ec7d` | `src/alpha/styles/overview.css`（原樣） |
| `development-alignment.css` | `2da6fba188145437ec9e7b68c6e36c687b8162c3cb6d4a8fa1526f64af20e544` | `src/alpha/styles/development-alignment.css`（原樣） |

`case-calculations.js`（`f8fdc38c…`）沒有複製：VM 的畫面合計改用「記帳的逐步進位算法」（`src/alpha/caseCalculations.js`，
與後端 `cases/calc/totals.py` 相同），見 MIGRATION-STATUS.md「案件合計」。
`src/alpha/lib/accounting.js` 是 Alpha `lib/accounting.js` 的原樣副本（`e0acc3c8…`，與 `backend/qa/alpha_js/lib/accounting.js` 相同）。
`src/alpha/production-xlsx.js` 是 Alpha `public/production-xlsx.js` 的原樣副本（`256db219f84aa2e56c9e1a36c81541c1fe7a560b0a0f9054e2253773808dcf59`），
由 `src/views/Production.vue` 載入；它需要的 JSZip 用 npm 套件 `jszip` 3.10.1（與 Alpha 的 `vendor/jszip.min.js` 同版）。
