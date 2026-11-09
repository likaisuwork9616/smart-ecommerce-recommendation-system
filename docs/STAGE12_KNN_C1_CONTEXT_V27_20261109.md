# Stage 12：C1 同一 worker 內的唯讀初始化重用

## 實作與第一批核對完成

依 V26 封存規格新增 C1 模組，原 V4／V6／V24／V25 方法檔不變。第一批 **13／13 項測試通過**，unittest 回報 3.621 秒、失敗／錯誤／跳過均為 0；這是合成測試時間，不是原 48 筆效能。

| 實作範圍 | 實際行為 |
| --- | --- |
| 精確來源內容 | 在原鎖定後來源重驗完成後，將 counts／catalog／設定／模型收據讀成有界 bytes；同一份 buffer 長度與 SHA 符合 descriptor 才交給原解析器 |
| 原驗證語意 | 使用原 load_context、CSV／數值規則及 prepare_catalog；不修改排名、SQL、科學輸出或逐筆對照流程 |
| 快照 | 只保留原 FrozenCatalog 的唯讀 mapping 與 tuple；沒有可變 backing alias，使用前後內容 digest 核對 |
| 身分 | 完整 binding、所有初始化依賴、完整型別化設定／模型／support、方法 bytes、環境、來源根目錄、request／namespace 與程序身分皆入鍵 |
| 鎖定邊界 | C1 store 執行原 create 核對與 writer 鎖定後 force=True 核對；未上鎖、external receipt 代驗、恢復前綴或重複 writer 均拒絕 lookup |
| 生命周期 | 一份快照、一次 cold build 加六次 hit；第八次、非預期 miss、身分或內容變更停止，不重建／退回原版。禁止序列化至其他程序 |
| 計時與觀測 | 原 setup／primary 邊界保留；cold build、key、buffer、前後 digest 分項計時，返回後 guard 在完整入口內另列 |
| 原 48 筆形狀接合 | 提供 R／C 每次呼叫專屬 adapter，兩臂都用細觀測與 fresh store；沒有新增真實 measure CLI |

已通過一次建立六次命中、來源變更／上鎖前變更、不同來源路徑、設定／完整模型變更、跨 namespace／程序、唯讀與快照修改、環境變更及完整性收據限制。

另以完整四臂人工 fixture 執行原版、C1 cold 及 C1 hit，逐列保存 bytes、Decimal／delta_hex 與 SQL 邏輯工作量完全一致。這與後續人工 48 筆控制流程驗收分開，沒有將人工 fixture 當成真實原 48 筆。

第一批 13 項核對完成時，完整 38 情境對照及獨立發布整合仍待驗收；最終結果如下。

[實作收據](../reports/stage12/retailrocket_session_knn_v27_reuse_implementation_20261109.json)

## 完整 C1 合成驗收完成

**73／73 項合成測試通過**，驗收入口耗時 50.662 秒，失敗／錯誤／跳過皆為 0。C1 初步專項 13 項、補強與實際子程序整合 28 項，加上 V24 觀測 11、V25 監督／發布 10、V6 保存 7 及 V23 成本守恆 4 項，合計 73。V26 封存的 **38 個必要情境逐項對應已成功的具體 test ID**，完整對照保存在驗收收據。

第二小階段補上原事件中的 cache.use、每次方法 bytes 與快照 digest，供獨立程序重算；另在最後審閱補強冷啟動依賴須為來源清單的完全相同紀錄，以及禁止錯誤／負數 bytes 解除 buffer 上限。這兩項負例通過後，已對完整最終版本重跑合併驗收。第一次未發布草稿、紀錄及五份方法快照仍留在忽略路徑；本次完成依據是目前 73 項全通過的收據，沒有覆寫先前紀錄。

| 封存範圍 | 實際驗收 |
| --- | --- |
| 身分與來源 | 同大小不同內容、改路徑、大小／mtime、設定／完整模型／support／方法／環境變更均拒絕；未綁定的同內容冷啟動依賴也拒絕 |
| 原解析與唯讀 | 精確已 SHA buffer、讀取中變更、header／欄寬、重複 ID／canonical 數字、非正計數／support／訓練時鐘；mapping／tuple 修改拒絕，特殊途徑更改 FrozenCatalog 由 digest 攔截 |
| 鎖定與生命周期 | 每次原 create 與鎖定後 force=True 完整來源核對；未上鎖不 lookup、鎖失敗與 body 中斷釋放 guard、恢復／不同程序／第八次均拒絕 |
| 真實小型程序監督 | RSS 限制停止，以及既有 V25 deadline 清理測試均通過；僅小型人工子程序，沒有真實推薦窗口 |
| 科學輸出 | 完整四臂人工原版／C1 cold／C1 hit 的 bytes、Decimal、binary64 delta_hex 與 SQL 邏輯工作量一致；C1 保留原第二次 first_times 排序，C2 未實作 |
| 成本 | cold／key／前置 digest 位於原 setup 內；最終 guard 位於 setup 後且完整 entry 內；原 primary／append／commit 邊界保持，互斥事件樹守恆 |

### 人工 48 筆與獨立程序發布

在人工資料上實際使用 C1 adapter，按 R／C 暖機及六對 RC／CR 產生 **14 份 fresh 帳本、每份 48 筆，共 672 次人工保存核對**。這次人工 48 筆使用完整原 verifier 與四臂格式，不以假的 verifier 代替排名；較大的鄰居上限情境另由完整四臂 boundary fixture 驗證。

worker 正常退出後，另一個 Python publisher 程序從原始人工來源重新建立一次 context，核對預期 snapshot digest／rows 與七次使用事件；它沒有 worker 快照參數，也沒有快照序列化檔。publisher 保留前後完整來源核對及 **14 次原 store.open**，逐筆比對完整實體科學 frames，重算成本、事件樹、負載及 cache 收據。

| 人工整合結果 | 實際數字 |
| --- | ---: |
| 候選 C1 執行 | 7 次 |
| cold build／hit | 1／6 |
| 冷啟動實際驗證 buffer logical bytes（含設定與模型收據） | 22,627 |
| 其中 counts／catalog logical bytes | 214 |
| 命中後 counts／catalog 解析 | 0 次，原來源完整核對仍執行 |
| 人工 counts／catalog rows | 5／18 |
| 每個 worker closure 邊界來源數 | 43 |
| publisher descriptor 核對（兩次 closure＋十四次 open） | 436 |
| 外層退出碼／清理後存活程序身分 | 0／0 |

人工來源／binding 為 43／25 份，用來驗收控制流程；不能當成原真實 596／15 份已重新實測。原 596 份身分與原 15 份 binding 不變的要求仍由 V26 封存規格約束未來真實入口。人工 harness 每段至少保留 0.45 秒，以確保負載首尾及至少三個樣本；這是合成觀測安排，**不是效能測量或加速比例**。

篡改 events、measured cost、telemetry、cache 收據或 payload，以及外層失敗／仍有存活身分／超過期限，都不能完成退出後 release。正式驗收後另執行 `--audit`，核對目前方法、原規格、完整私有證據與測試紀錄一致。

### 操作與目前範圍

合成驗收：`.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_reuse_v27 --acceptance`。已有正式收據拒絕覆寫；只讀重核對使用相同入口 `--audit`。測試資料、程序身分、模型與原事件皆留在 Git 忽略路徑；公開只有方法、合成通過紀錄、聚合與指紋。

核心位於 `retailrocket_session_knn_reuse_v27.py`，提供 `WorkerContext`、`ReuseStore`、`make_verifier` 與 `run_fixed48`。未來真實入口須提供包含原 596 份與新方法的 closure、原 15 份 binding、四份初始化依賴、完整 accepted methods／environment；各依賴必須是完整來源集合中的相同 descriptor。原模型收據不在 15 份內時，須明確提供完整 closure，不得降級成只信 binding。

獨立稽核 helper 位於 `retailrocket_session_knn_reuse_audit_v27.py`；目前明確只接合成驗收資料。**本輪 C1 實作與合成驗收已完成；沒有啟動真實 C1 比較，沒有提供繞過授權的 measure CLI。** 真實受監督實測／release 入口仍需獨立封存與整合驗收，再循序比較原 48 筆。

本輪真實效能窗口、真實 fit、完整 validation、主要 bootstrap 與保留測試皆為 0。覆蓋仍 **55／55 格、170 個可比較查詢、232 個歷史身分**；完整 validation 未完成，保留測試鎖定，`measured_speedup = null`、`T_plan = null`。

[正式驗收收據](../reports/stage12/retailrocket_session_knn_v27_reuse_acceptance_20261109.json)
