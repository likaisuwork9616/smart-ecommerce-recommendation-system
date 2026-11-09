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

目前 **38 情境的完整對照與獨立發布整合驗收仍待下一小階段**，不能把 13 項核對說成 C1 全部驗收完成。下一步補齊負例、完整原回歸與獨立 publisher 檢查；本輪真實窗口、fit、完整 validation、bootstrap、保留測試均為 0，沒有加速比例。

[實作收據](../reports/stage12/retailrocket_session_knn_v27_reuse_implementation_20261109.json)
