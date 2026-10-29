# Stage 10：C1、配對評估、bootstrap 實作與 validation 入口 v1

本輪依[已凍結配對規格](STAGE10_RETAILROCKET_COOCCURRENCE_PAIRED_SPEC_V1.md)完成程式、手算與獨立合成驗收，另盤點真實 train-only 計算成本並凍結入口。**沒有執行真實 C1 擬合、validation 排名／配對指標／bootstrap；預留測試仍 locked。**原規格中的未實作狀態是該輪歷史快照，本輪另存新收據，不修改舊文件或雜湊。

## 實作分工與不變的方法

| 程式 | 責任 |
|---|---|
| [retailrocket_cooccurrence.py](../scripts/retailrocket_cooccurrence.py) | train session 集合、單次二元商品／無序 pair 計數、因果歷史串流、有理分數、完整候選精確 top10、配對訪客 bootstrap |
| [retailrocket_cooccurrence_io.py](../scripts/retailrocket_cooccurrence_io.py) | validation-only loader、P0 原始檔逐筆配對、完整 target 分母、兩臂／條件／切片／診斷／差值、排他寫入 |
| [retailrocket_cooccurrence_oracle.py](../scripts/retailrocket_cooccurrence_oracle.py) | 獨立 SQL DISTINCT session memberships／self-join pair 計數、lineage／有理排序／逐查詢指標及彙總反讀、全部抽樣重播 |
| [retailrocket_cooccurrence_cost.py](../scripts/retailrocket_cooccurrence_cost.py) | train-only session 基數與精確 pair 發射工作量，獨立 SQL 核對；不建商品／pair 模型 |
| [run_retailrocket_cooccurrence_v1.py](../scripts/run_retailrocket_cooccurrence_v1.py) | 來源／環境／成本／輸出守門、資源停止、單次 train fit→validation→oracle 的凍結入口；無 final-refit／test 模式 |

所有 train session 成員先按角色／時鐘裁切，再求集合。Singleton 仍貢獻 `S_i`；重複瀏覽不放大商品及 pair 次數。查詢只用同 session 截至當下的 view 集合；索引、時鐘或 current basket 缺漏即停止。`Σ C_ij/S_i` 用 Fraction 精確計算，不引入 alpha、取樣或截斷。

正證據候選依有理分數、P0 count、數值 ID 排序；其餘候選分數精確為零，再由完整 P0 count／ID 順序補位。完整 SQL 鄰居聯集外沒有共現分數，因而可用精確零分補集證明同於完整候選排序。合成 oracle 另以逐候選 full sort 驗證此最佳化；真實 oracle 會枚舉全部 SQL 鄰居並證明零分補集，不使用鄰居 top-L 或抽樣。

P0 實際 train 模型、排名、逐查詢指標及原報告直接重用並綁定 SHA。程式不重擬合或重排名真實 P0；配對結果重新彙總原指標後須與已驗收的 P0 主／條件／全部切片一致。合成 fixture 內另建的玩具 P0 僅供驗收，與真實 P0 分開。

## 手算及獨立合成驗收

玩具 train 的兩個 session 為 `{1,2,3}` 與 `{1,2}`；第一個 session 商品 1 曾重複瀏覽。手算 `S_1=2,S_2=2,S_3=1`，`C_12=2,C_13=C_23=1`。當 `H={1}`，商品 2 得 1、商品 3 得 1/2；自我邊不給商品 1 分數，但商品 1 可由 P0 零分補位，因此前三名固定為 `[2,3,1]`。

第一筆玩具 target 為 `{2,999}`，999 在查詢當下尚不可達，但完整 target 留在分母。手算 C1 Recall@10 為 `1/2`，NDCG@10 為 `1/(1+1/log2(3)) ≈ 0.6131471927654584`。這些數字只屬合成資料，不是真實 Retailrocket 成績。

Bootstrap 手算案例中，訪客 1 有兩個差值 `1,1`，訪客 2 有一個差值 `-1`；主 query-macro 差為 `1/3`，不能改用訪客等權平均 0。兩訪客有放回抽樣的查詢分母可為 2／3／4，對應差為 -1／1/3／1；獨立重播全部 2000 次並另作線性 percentile 插值。正式合成 fixture 共 5 queries／4 visitors，也逐筆核對配對與抽樣。

測試另含：singleton、warmup／截止線裁切、未來不得改 fit、同時 basket、session prefix 與舊 session 排除、未知 seed 完全回退、部分補位、不刪已看、空候選、浮點會合併但有理數不同的分數、P0／數值 ID 平手、完整分母、缺筆／重複 P0 key、切片／分母漂移、有理分數與抽樣 SHA 損壞、資源停止後保留 started／failure 並拒絕重播。40 組固定合成 session × 各 8 查詢另做完整候選差分比對。

Oracle 不匯入新的 C1 核心、adapter 或 bootstrap；另用 SQL 重建 counts、歷史及候選。指標重用先前凍結的獨立 50 位 Decimal／Fraction oracle；再比對所有 JSON 巢狀值，計數／ID／歷史／有理數／排序精確相等，浮點採原絕對／相對 `1e-12`。新 JSONL 的 `top_level_cells` 僅計頂層欄數，不能冒充巢狀值總格數。實際測試數及正式兩組合成反讀數見[實作驗收收據](../reports/stage10/retailrocket_cooccurrence_v1_implementation_acceptance.json)。

## 真實 train-only 成本盤點

只解析合格 train basket 的商品內容，其他角色先按 role 排除；未解析 validation／test 商品或 target。沒有建立任何真實 `S_i`／`C_ij` 模型，也沒有評估查詢。

| 真實 train-only 項目 | 實際數量 |
|---|---:|
| Session | 1,180,256 |
| Singleton session | 998,801 |
| Basket | 1,823,018 |
| Basket 商品 memberships | 1,823,388 |
| 去重 session 商品 memberships | 1,587,436 |
| 精確無序 pair 發射次數 | 2,292,165 |
| 最大 session 商品種類 | 389 |
| 獨立 session 基數帳核對 | 1,180,256 列／5,901,280 格 |

先由串流集合盤點，再以獨立 SQL `COUNT(DISTINCT item)` 逐 session 核對；耗時 65.836239 秒。完整基數分布、ledger、SQL 檔及成本 JSON 在 Git 忽略的 `shop-mysql-runtime/verification/retailrocket-cooccurrence-implementation-v1/train_cost/`。兩次 train 掃描的筆數不代表新擬合或新成績。

這個 pair 發射量允許採用精確 Counter／鄰接表計數方案，不需改方法。**實際 unique pair、模型 RSS、validation 歷史／鄰居工作量與整輪時間尚未量測**，本成本不能當作真實排名速度或一定完成的保證。Bootstrap 固定 2000×62,235＝124,470,000 個訪客位置，逐 replicate 生成、雜湊及保存 RNG／分母／差值，無須同時保存全部位置陣列；獨立驗收再重播一次。

## 固定資源限制

| 限制 | 固定值 |
|---|---|
| 單一 Python process RSS | 上限 8 GiB |
| 真實執行目錄總檔案大小 | 上限 20 GiB |
| 磁碟剩餘／系統可用記憶體下限 | 8 GiB／4 GiB |
| 單次建模＋validation＋完整 oracle／bootstrap 驗收 | 上限 21,600 秒（6 小時） |
| 檢查方式 | 至多每 0.5 秒合作式檢查；pair 迴圈另每 50,000 次呼叫；記錄抽查 RSS 峰值 |

NumPy 2.5.4／PCG64、seed 42、2000 次及原線性 quantile 不變。記憶體與資源監控使用本機 `.venv` 已有 psutil 7.2.2，沒有安裝新套件。Python、套件版本及關鍵 native module、原資料與 P0 收據、成本檔案和本輪程式均綁定於[真實入口規格](../reports/stage10/retailrocket_cooccurrence_v1_validation_specification.json)。

上限由程式合作式檢查，並非作業系統瞬間硬性 kill；單次不可中斷運算可能於下次檢查才被發現。超限或來源／鍵／分母／驗收不一致即停止、保留部分檔案並拒絕重播；不以刪 session、截 history／鄰居或取樣來通過。不足時需另訂執行版本或方法，不覆寫本入口。

## 凍結、操作與下一步

本輪執行的是首次 `--prepare`（測試、兩個正式合成 case、來源／成本與入口凍結），以及唯讀 `--verify`。現有完整準備重入只驗證；部分證據拒絕覆寫：

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_cooccurrence tests.test_retailrocket_cooccurrence_entry -v
```

下一輪明確執行真實開發時，唯一入口為以下指令；**本輪未執行**：

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --run-validation
```

它會先核所有來源，再於 `shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/` 寫 started，單次 C1 train 擬合、原 166,897 validation 完整配對、2000 次 bootstrap，並獨立逐筆重建／反讀。全部通過才產生公開真實聚合／驗收及 output guard；部分執行保留 failure，完整執行重入只核 bytes，兩者均不能追加 fit。

私人實作凍結於 `shop-mysql-runtime/retailrocket_cooccurrence_implementation_v1/`，合成與日誌位於其 verification 路徑；真實 C1 執行目錄本輪不存在。所有檔案仍在 shop，原始資料、模型、逐查詢／session／pair／抽樣紀錄均在 Git 忽略位置。

同 166,897 query／62,235 訪客、候選、完整 target、分母與支援門檻 1,669 不變。多商品 56／53、混合支援 3 及原 train 199／192、locked test 33／29 的不足保留；沒有小組區間或挑組。P0 validation 在 C1 規格制定前已曝光，後續仍是回溯開發比較；匿名訪客、曝光／propensity／庫存與 ingestion 缺口、非商業授權及 Olist／UCI 限制保留，不能推論上線營收或因果改善。

沒有 test 或 final-refit CLI；不能沿用 P0 gate 作 C1 測試授權，有利成績也不解鎖。下一步只是一輪真實 C1／P0 配對 validation 與完整驗收，保留測試繼續 locked。
