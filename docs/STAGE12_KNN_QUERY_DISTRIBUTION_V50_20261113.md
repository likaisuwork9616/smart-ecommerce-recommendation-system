# Stage 12 V50：既有 48 筆查詢的增時分布

本輪只分析 V47／V48 已封存的 `measured.json`，檢查 V49 查到的主流程增時是否集中於少數查詢。沒有新增實驗、context、查詢、SQL、解碼、訓練或保留測試；結果限於已曝光的固定 48 筆 validation 工程紀錄。

## 計時與配對口徑

逐筆計入時間為 `verification_seconds + append_without_commit_seconds + chunk_commit_seconds`。其中 verification 含 ranking；ranking 的七個既有階段、ranking 餘額、verification 在 ranking 外的餘額、append 與 query 內 commit 形成互不重複的分項。最後 flush 的尾端 commit 另外保留，不能攤到個別查詢；逐筆合計加尾端 commit 必須回到 V49 的 primary。

每次都核對 48 筆的 subset 順序、原身分、key hash 與 SQL logical workload。公開報告只保留 1 起算的固定 subset 序位與衍生時間差，不公開原 key、原 ordinal、訪客／商品資料或 SQL 明細。不同窗口的同一序位代表相同查詢，但不同 pair 並非相同主機負載條件。

| 統計層級 | 定義 |
| --- | --- |
| 每對 48 筆 | 相同查詢的 V46−V39，正值表示候選增時；列分布與最大的五筆正差 |
| 每窗 288 個配對觀測 | 六對×48 筆，描述所有逐筆差值；它們是相同 48 筆的重複觀測，不是 288 個獨立查詢 |
| 同序位跨六對 | 各序位的六次差值先加總，另外列中位數、正差次數與超過 1 ms 次數 |
| 集中度 | 最大 1／5／10 個正差占正差總量 P 的比例；負差總量 N 另列，淨差=P+N，不用淨差當分母 |
| 兩種正差分母 | 288 個觀測的 P，與 48 個序位先跨六對加總後的正差總量不同，不能混用占比 |
| 小差值 | ±1 ms（含邊界）另外統計，只是描述尺度，不是顯著性門檻；p10／p90 使用 nearest-rank、無內插 |
| 暖機與順序 | 四次暖機另外保留，不納入正式分布；CR／RC 各三對亦分開彙整 |

## 工具驗收

17 項純數值／配對測試通過，無失敗、錯誤或跳過，耗時 0.133 秒。涵蓋正負差抵銷、全負／全零、集中與均勻分布、1 ms 邊界、分位數、巢狀計時守恆、48 筆身分／順序／工作量、尾端 commit 不分攤、暖機排除及兩種集中度分母。CLI 拒絕 `--measure`。

驗收綁定 V47、V48、V49 三份固定 SHA-256 報告與本輪方法。這一步先封存工具，正式既有紀錄分析另行產生。[驗收收據](../reports/stage12/retailrocket_session_knn_v50_queries_acceptance_20261113.json)

## 操作

```powershell
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_queries_v50 --acceptance
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_queries_v50 --analysis
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_queries_v50 --audit
```

分析會先唯讀重建 V49 及原兩窗停態證據，再核對 28 份原始計時檔的 bytes／SHA。驗收與分析各封存一次，後續使用 `--audit`，不重跑 benchmark。
