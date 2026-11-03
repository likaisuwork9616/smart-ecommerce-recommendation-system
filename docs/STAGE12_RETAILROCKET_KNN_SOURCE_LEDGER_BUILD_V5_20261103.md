# Stage 12：V5 完整形狀原始輸出工程 ledger 建置成本

本步補真實原 payload 格式、完整筆數／visitor 分布及物理 chunk 寫入成本。來源是既有、**尚未全量獨立驗收**的 K1 四臂輸出；**沒有重新計算全量 K1 排名，沒有預留測試、正式 K1−C1 結論或主要模型重跑**。

## 實際結果

| 項目 | 實測 |
| --- | --- |
| 完整工程紀錄／訪客 | 166,897／62,235 |
| Chunk 數／預設節奏 | 2,608／每 64 筆或 120 秒 |
| 原 K1 主輸出 | 2,294,757,672 bytes |
| 新 CP-layout 工程 payload | **2,413,599,879 bytes** |
| 新 payload min／max | 3,491／48,115 bytes |
| 新 payload p50／p99 | 8,342／44,789 bytes，nearest rank，含列結尾 |
| 已驗參考格式對照 | **110 個不同 query** 的完整 canonical payload 相同，忽略其子集 ordinal |
| 完整工程建置 outer phase | **350.266 秒** |
| Supervisor 窗口 | **466.281 秒，正常退出 0** |

窗口為臺北 **2026-11-03 15:11:38.321212→15:19:24.603938**，原期限 15:41:38.321212，沒有延長。窗口內初末 **498 份來源綁定**一致，耗時 **61.580／52.836 秒**；少量 preflight **0.262 秒**在窗口前，退出後唯讀 inventory 核對 **40.863 秒**另計。

## 成本代理如何保留真實形狀

[V5 工具](../scripts/retailrocket_session_knn_ledger_cost_v5.py) 完整讀取原主輸出，把四臂 `expected` 原值、frozen terms 的 Decimal 欄及原 binary delta 的 hex 表示，編碼成 CP 相同的 `ordinal／key／payload` byte schema。原 float 值、歷史、targets、selected-neighbor 巢狀內容與原 slice 分布完整帶入；不是短小人工鄰居列表或均勻 visitor 的代理。

儲存使用另名的 `engineering_unaccepted_saved_outputs_ledger_cost_v5` 協定、engineering chunks／payloads／contract／seal。每 chunk 真正 fsync、SHA 及原子 manifest 保存，但**不呼叫 `append_verified`、不產生 candidate／科學 acceptance，也不允許原 CP 將它當已驗 ledger**。

每列從已存推薦 IDs 重算 metric 算術，只證明原值自洽；沒有重建各 query 的 history、相似度、鄰居覆蓋、投票或完整排名。Full-shape source-backed 成本代理與 full independently verified ledger 是兩個不同的狀態。

## 來源與形狀守門

原 `queries.jsonl` 身分來自先前發布的來源描述，不在現場隨意重算後建立新信任起點。來源索引 manifest SHA、整個 key roster、原 K1 bytes／SHA、catalog 複本及凍結 config 都反核既有綁定；完整固定 query／visitor／target／reachable／conditional、新客／多商品與 target-model 全桶分母在 seal 前核對。

已驗參考取自發布過的 V4 golden 64 筆及 V5 joint 48 筆，按 key／完整 canonical payload 去重，兩者重疊 2 筆，所以必須全部對上 **110** 筆。這只證明 adapter 在這 110 筆忠實，不能擴大為其餘 166,787 筆的科學驗收。

完整來源為既有 validation 主輸出；source-only 索引先排 role 才處理 validation，完整檔案 SHA 只視為 opaque bytes。0 新主要 fit／validation／bootstrap、0 新 K1 prediction、0 final／refit／test，原 V1 partial／923 觀測與其他 namespace 保留。

## 保存、測試與資源

Supervisor 正常退出後，另核 **5,218 個工程檔案**的 SHA、chunk 順序、記錄數與 payload bytes 加總，並反核工程 seal／contract／summary、source／catalog／config／source-index 身分；3 個記錄程序身分均不存活。這是 inventory 與物理總量核對，完整 manifest 前後鏈、每列 ordinal／key／roster 的恢復計時留給下一窗口。

18 項小型合成測試全過，入口整段 **7.756 秒**，0 failure／error／skip。包括已驗樣本去重與完整 payload 校準、錯 rank 不冒稱已驗、固定形狀錯誤、來源變更、hash／chunk 缺口、截停保存、獨立工程協定、總 guard 跨階段累積與新工程 self-reference draws。測試來源是人工 fixture，不是未知資料成績。

RSS 抽樣峰值為 **134,500,352 bytes**，執行目錄峰值 **2,420,532,823 bytes**；可用記憶體／磁碟及 8 GiB RSS／20 GiB 執行目錄門檻未觸發。OS cache、其他系統資源與未來全量不是這些數字的上界。建置成本含來源解析、given-ID 指標算術、編碼與 chunk I/O，不能全部再加到已包含相同工作的逐筆配對時間上，冒充精確無重疊的全量工時。

## 下一步

先把本步來源／seal／正常退出收據提交保存，再另開 **新的** 30 分鐘成本窗口，只讀這個工程 ledger 量完整鏈／原來源 EOF 位置恢復、四臂 global／切片與新 2,000 self-reference draws。這不是延長 builder 期限，也不是恢復原 V1 未驗 partial。

另一分項會在新目錄以原先凍結的同 48 筆重新核對 V4，量 budget.json 的真實寫入／fsync／rename，分開逐筆、chunk、stage 與 setup 上下文；原觀測不刪除、不跨窗口任意相減。之後才做整體成本評估。**完整 T_plan 空值，全量先不跑、預留測試 locked、K1−C1 無正式結論**；每日 10% 延遲提醒與 Dashboard 暫緩維持。

依據：[18 項驗收](../reports/stage12/retailrocket_session_knn_v5_ledger_acceptance_20261103.json)、[建置成本與保存報告](../reports/stage12/retailrocket_session_knn_v5_ledger_build_cost_20261103.json)、[前步聯合尾端成本](STAGE12_RETAILROCKET_KNN_JOINT_TAIL_COST_V5_20261103.md)。
