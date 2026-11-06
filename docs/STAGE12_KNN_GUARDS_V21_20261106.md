# Stage 12：保存前檔案檢查與身分驗證

沿用同批七筆、固定對照與原排名方法，先拆分保存前的檔案存在判斷及身分檢查，再評估正重疊 SQL 候選。所有觀測屬已曝光 validation 的工程診斷，不是未知資料成績；完整 validation 與保留測試維持未啟動。

## 盤點

本輪前後核對 **174 份來源、每次 6,233,104 bytes**，確認 V20 六輪共 42 次的來源與結果。未重新讀取大型模型或原始資料，也未執行新排名。固定樣本與順序、既有七路子集及原 1,945 位鄰居對照可直接沿用。

V20 最大診斷 append 差為 **17.239 ms**，其中 guards_and_key **15.551 ms**；另一個案例的 writer／context 剩餘差 **9.734 ms**。這兩個區段仍混合檔案存在檢查與 Python 處理，不能認定成單一磁碟或 SQL 原因。

| 保存前區段 | 原操作與本輪觀測缺口 |
| --- | --- |
| writer 檢查 | 先檢查 writer guard，再查 acceptance.json；不能跳過檔案查核或改變例外。 |
| query stage 檢查 | candidate.json 或 stages/global.json 存在即停止，保留原短路順序。 |
| 身分格式 | _key 檢查 list、字串數字、正規化整數與非負整數，須與順序比較分開解讀。 |
| 其餘順序與初始化 | ordinal、前一筆 key、首次 reconstruction 狀態及代理開銷仍列剩餘成本，不假稱純身分驗證。 |

只觀測 direct append 的這三個 exists 呼叫與原 _key，保留原操作次數、回傳與失敗順序。CPU 仍可能呈 15.625ms 級量化，短段以 wall 計時定位，不將 wall−CPU 視為 I/O 等待。

覆蓋維持 **55／55 格、170 個可比較查詢、232 個歷史身分**；該格 11 筆、尾端 6 筆。本階段新增身分、排名與 SQL 候選執行均為 0。

[盤點收據](../reports/stage12/retailrocket_session_knn_v21_guards_inventory_20261106.json)
