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

## 固定細項診斷規格

沿用同一批七筆、原始順序與 V19 既有子集。R 保留原 V4／V6；D 保留 V20 的 SQL／預算觀測，再加入 direct append 檔案與身分檢查。固定 **R→D、D→R、R→D**，共六輪、42 次核對，全部循序；不清快取、不排除暖機、不換樣本或追加較快結果。

新觀測用每次呼叫專屬的 store/path view 執行原 V6／V2 bytecode，量測原 acceptance.json、candidate.json、stages/global.json 三個 exists 呼叫，以及原 _key 格式驗證。保持原短路順序、回傳與例外，不增加檔案查核、不快取結果、不移除安全檢查。第一次 reconstruction 讀取、ordinal／先後 key 比較、Python 分派及觀測成本保留在剩餘項，不能把剩餘項當成純身分驗證。

保留原分項 wall／執行緒 CPU、writer 內含 acceptance 的巢狀關係；存在檢查與 key 子項不得超出其原外層時間。CPU 量化與有號 wall−CPU 原樣保留，不能當等待量。公開僅顯示用途標籤，私人證據保留完整紀錄。

六輪每輪都對回全部七筆 V19 完整科學 payload、工作量與實體位元組；新樣本仍為 0。沿用 200ms 目標負載觀測、原 1,800 秒窗口與資源限制，首尾涵蓋各驗證入口且六輪不重疊。失敗就保留證據並停止發布，不重開較快窗口。

## 診斷後的 SQL 候選評估

完成診斷後再獨立評估「posting 先聚合，再 LEFT JOIN session size」的具體改寫。先看既有成本與原／候選 EXPLAIN QUERY PLAN；實際模型只做計畫檢查，不執行候選真實排名。若提出候選，使用人工資料比較完整預測與工作量，涵蓋自我排除、空結果、未知／未來商品、切點同分及缺少 size 的拒絕行為。

查詢計畫或合成語意通過都不能當作加速證據。這一階段給出是否值得另立配對效能試驗的判斷；沒有候選真實計時就不採用、不報加速比例。先前 V17 投票候選未達門檻的結論保留。

全通過後覆蓋仍 **55／55 格、170 個可比較查詢、232 個歷史身分**；該格 11、尾端 6。本階段尚未實測，完整 validation／主要訓練／主要 bootstrap／保留測試均不啟動。

[封存規格](../reports/stage12/retailrocket_session_knn_v21_guards_specification_20261106.json)
