# Stage 12 V51：序位 32／38 的既有邏輯工作量

本輪接續 V50，只用 V47／V48 已封存的 48 筆 validation 工程紀錄，比較序位 32／38 是否原本就有較大的邏輯工作量。先用人工資料驗收工具、提交封存，再讀原計時檔；不重跑實驗、查詢、SQL、model 解碼、訓練或保留測試。

## 分析口徑

| 項目 | 方法 |
| --- | --- |
| 來源 | 固定 SHA-256 的 V47、V48、V49、V50 報告，與原停態 manifest 綁定的 28 份 `measured.json` |
| 身分與重複 | 核對 1,344 筆的原身分、subset 順序、工作量與原計時加總；兩窗、兩臂、正式／暖機的相同查詢工作量必須一致，最後每個序位只計一次，樣本數為 48 |
| 兩個對照集合 | 全部 48 筆，以及同時排除序位 32／38 後的其餘 46 筆；兩目標不混入 46 筆對照 |
| 各欄分布 | 分別列筆數、不同值數、合計、最小值、中位數、p90、最大值；p90 採 nearest-rank、無內插 |
| 目標比較 | 列 32／38 的值、全 48 筆由大到小的名次區間、相對其餘 46 筆較小／相同／較大的筆數，以及對全體／其餘中位數的倍數 |
| 同值與零 | 並列名次保留第一至最後一名；中位數為 0 時倍數為 null，不產生無限大；常數欄不能區分兩目標是否較重 |
| 型別 | 14 個非負整數計數、1 個非負整數位元寬度與 1 個布林旗標；不接受缺欄、額外欄位、浮點數、負值或以 bool 冒充整數 |
| 公開範圍 | 只公開匿名 subset 序位 32／38 的診斷計數與分項統計；不公開原 key、hash、ordinal、商品／訪客資料、SQL 列或完整 48 筆工作量矩陣 |

全 48 筆的降冪名次為 `1 + 嚴格大於目標的筆數` 至 `大於或等於目標的筆數`。比較其餘 46 筆時，lower／equal／higher 分別指該 46 筆中計數比目標小／相同／大的筆數，三者合計必須為 46。這是描述性比較，沒有顯著性門檻，也不把不同欄位的計數相加成一個「總工作量」。

## 計數的來源與意義

V47／V48 兩臂仍沿原 `sql_v4.predict` 執行查詢。V46 更換的是 reference decoder；以下計數在兩臂均用同一定義。

| 原欄位 | 意義與限制 |
| --- | --- |
| `history_rows_inserted` | 去重後的歷史商品數，非歷史事件數 |
| `sql_overlap_membership_matches` | SQL 回傳群組的 intersection 合計，非實體掃描筆數 |
| `sql_overlap_groups_returned` | 正重疊 session 群組數，含尚未排除的自己 |
| `neighbor_pool_rows_hashed` | 排除自己後納入 hash 的正重疊鄰居數，非 hash bytes |
| `distinct_neighbor_similarities` | 鄰居池不同約分 Jaccard 比值數 |
| `sql_selected_rows_inserted` | 寫入 TEMP 表的選定鄰居數，最多 500 |
| `sql_vote_membership_rows_returned` | 選定鄰居回傳的 membership 數，含時間檢查尚未排除的商品 |
| `exact_vote_additions` | 通過商品時間檢查後的累加次數 |
| `integer_vote_additions`／`fraction_vote_additions` | 上述累加分別採整數尺度／Fraction 的次數，是 exact 的分項，不另加成新工作量 |
| `positive_causal_candidates` | 得到正票的不同商品數，非投票累加次數 |
| `causal_catalog_candidates` | 由 bisect 取得的可用候選集合大小，非逐筆掃描量 |
| `fallback_catalog_rows_examined` | 補足 top10 時檢查的 catalog 項數 |
| `catalog_snapshot_rows_prepared` | query 內準備 catalog 的列數；FrozenCatalog 路徑為 0，不表示完整入口的 catalog 準備免費 |
| `vote_scale_bits` | 共同分母位元寬度，非操作計數；fraction fallback 時的 0 是特殊標記 |
| `fraction_fallback` | 是否因共同尺度超過 4096 bits 而改用 Fraction，獨立列布林筆數，不作計數排名 |

若任一筆採 fraction fallback，工具保留 `vote_scale_bits` 原值摘要並標示含特殊標記，但停用該欄的目標排名與中位數倍數；不能把 fallback 的 0 說成較輕工作量。

## 工具驗收

18 項人工測試全通，無失敗、錯誤或跳過，耗時 1.736 秒。其中 12 項純數值測試、6 項人工入口整合測試，涵蓋並列名次、常數／零值、排除兩目標的 46 筆分母、型別與欄位、fallback 特殊值、原兩窗完整順序、重複觀測合併、逐筆身分與工作量變更拒絕、公開輸出不含原身分，以及 CLI 拒絕 `--measure`。

驗收只使用人工工作量與人工計時，沒有讀取原始工作量分布。方法、測試、計數來源程式與四份前序報告均綁定 bytes／SHA-256，工具先封存後才執行正式分析；新增實驗、查詢、解碼與訓練均為 0。[驗收收據](../reports/stage12/retailrocket_session_knn_v51_workloads_acceptance_20261113.json)

## 操作

```powershell
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_workloads_v51 --acceptance
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_workloads_v51 --analysis
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_workloads_v51 --audit
```

驗收與正式分析各封存一次；之後用 `--audit` 唯讀重核。分析會先重建並核對 V50 與前序停態證據，再核對原計時檔，沒有執行 benchmark 的模式。較大邏輯規模只能描述這些查詢原本做的工作，不能據此判定 CPU、實體 I/O、排程等待、主機負載或 V46 導致增時。
