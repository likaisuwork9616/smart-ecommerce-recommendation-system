# 八月近鄰推薦的全量驗算

這一輪要回答一個問題。給定同一位訪客在同一時間已看過的商品，K1 把他接著看的商品排得比共現模型 C1 更前面嗎？沿用[原比較規格](STAGE12_TEMPORAL_AVAILABILITY_AND_KNN_SPEC_V1.md)。台北時間 2026 年 11 月 19 日 14:24 開始，17:24 截止，包含驗算與交付。

### 看結果之前固定的做法

| 證據 | 通過條件 |
| --- | --- |
| 原始輸出與資料版本 | 對照十月的[保存清單](../reports/stage12/retailrocket_session_knn_v1_validation_attempt.json)、入口來源與環境。原目錄只讀，新的驗算收據另存。 |
| 逐筆查詢及三張對照榜 | 從原始 basket 和 query 表重建同一次瀏覽截至當時的商品、下一個 basket、可推薦分母及切片。逐筆對回 P0、C1、D1 原排名與指標，核對三份新收據使用同一個查詢檔。 |
| 近鄰與投票 | 從已驗證的訓練來源另外建 session–item 關係，核對訓練清單與模型身分。用完整的正交集集合求 Jaccard 相似度，排除查詢本身所在的訓練 session，核對最多 500 個鄰居、同分順序、候選票數、補位與每筆前十名。以原本逐一掃描的獨立 oracle 在合成案例對驗新算法。 |
| 統計與交付 | 從逐筆排名重新算四臂指標、主要與條件分母、固定切片、診斷，以及 2,000 組按訪客抽樣的配對差。全部 166,897 筆、62,235 位訪客及各檔末尾一致後，才發布效果。逾時或不一致則回報實際完成範圍與原因。 |

主要指標是每次查詢的 NDCG@10 之差，正值代表 K1 平均把相關商品排得更前面。95% 區間沿用原先的配對訪客 bootstrap。另列前十名命中次數，並用同月已發布的「最近看過留一席」作描述性參照。線上點擊、營收及九月預留測試仍有待另外驗證。

這次驗算只讀上次已算完的結果，自行重建中間值。十月 v1 中斷的歷史收據與 Windows 合成診斷各自保留。[十月執行紀錄](STAGE12_RETAILROCKET_KNN_VALIDATION_ATTEMPT_V1.md)

### 兩種獨立交叉檢查

全量驗算器從原始訓練 baskets 建立對應表，用整數比較分數並累計票數。另用原版獨立 SQL 從原始 baskets 重建所有訓練 session，再用既有 SQL／Fraction 算法重算固定的 33 筆查詢。查詢位置從第一筆到最後一筆等距取樣，從零起算為 `i × (166897 − 1) // 32`，`i` 由 0 至 32。這 33 筆是額外交叉檢查，全量驗算仍須逐筆覆蓋 166,897 筆。

若時限允許，再以另一套密集陣列驗算器逐筆掃過所有訓練 session 與商品目錄，記錄實際完成筆數及整體耗時。所有核對使用相同的 500 鄰居、時間界線、候選、平手規則與原始輸出。執行監督器每半秒抽查工作程序樹的記憶體及剩餘時間，資源與停止收據保存在本機。

### 在本機重現

使用專案的 Python 環境與已下載且通過雜湊核對的 Stage 8–12 資料。每次驗算使用新的 Git 忽略目錄，所有階段共用同一截止時間。完成一個階段才進到下一個。

```powershell
$k1Run = 'shop-mysql-runtime/verification/k1-august-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$k1Until = [datetimeoffset]::UtcNow.AddHours(3).ToString('o')
foreach ($k1Stage in @('sources_before','predictions','cohort','sql_witness','dense','aggregate','sources_after')) {
    .venv\Scripts\python.exe -B -m scripts.run_k1_august_readback_v1 $k1Stage --out $k1Run --deadline-utc $k1Until
    if ($LASTEXITCODE -ne 0) { throw "K1 驗算停在 $k1Stage" }
}
.venv\Scripts\python.exe -B -m scripts.summarize_k1_august_readback_v1 --out $k1Run --report "$k1Run/summary.json"
```

密集驗算器以 SciPy 1.18.1 與 NumPy 2.5.4 逐列計算交集，再逐項核對商品票數與零分候選。票數總和超過 32 位元無號整數可表示的範圍時，改用任意精度整數。四個基本驗算階段與舊入口的合成回歸共通過 62 項測試；密集驗算器及公開報告另外通過 12 項測試。
