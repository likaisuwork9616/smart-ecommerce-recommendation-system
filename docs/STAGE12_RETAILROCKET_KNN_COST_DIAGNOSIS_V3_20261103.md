# Stage 12：V3 成本診斷

本步驟只量測監控 callback 並檢查既有程式／SQLite 索引 metadata，沒有重新訓練、真實 query 排名或真實 bootstrap。K1−C1 仍無正式結論，test locked。實際數字見[診斷報告](../reports/stage12/retailrocket_session_knn_monitor_cost_diagnosis_20261103.json)。

| 固定微量測 | 每輪 20,000 次，三輪中位數 | 停止檔檢查次數／輪 |
| --- | ---: | ---: |
| V2 每次 UTC＋Path.exists | 1.117981 秒，55.899 微秒／次 | 20,000 |
| V3 節流 | 0.015331 秒，0.767 微秒／次 | 1 |
| 只讀 monotonic | 0.004044 秒 | 0 |
| 空迴圈 | 0.001048 秒 | 0 |

V3 每次 callback 只讀 monotonic，在第一筆、force 或 0.25 秒邊界核對 UTC 與停止檔；外部 supervisor 仍負責硬截止。11 項測試通過，包含高密度 callback、停止／期限／倒退與無法確認檔案狀態時拒收。這個很短的迴圈尚未跨 0.25 秒，所以每輪只查一次停止檔；不能將此表當作全輪檢查總數或停止延遲上界。

依凍結 reconstruct 迴圈與已驗收聚合筆數，僅 train baskets、membership、support、sessions/postings 及雙份 lineage 串流就至少觸發 **9,908,572 次 watch**：

`1,823,018 + 1,587,436 + 198,946 + 2×1,180,256 + 2×198,946 + 3×1,180,256`

這是靜態下界，不是 profiler 實際呼叫數，未計其他角色 baskets 或 SQL VM callbacks。微量測支持「逐筆 filesystem 輪詢值得改善」，不能據此把舊建置的 840.406 秒分配給各函式或直接扣除推估節省。

另一個實際發現是封存 DB 同時有 `posting(i,v,s)` 與 `k1_v2_posting(i,v,s)`；此外建置前 `CheckpointStore.create`、`writer` 及明列 `source_hash` 各做完整來源 SHA。這些路徑確實重複，但本步驟尚未量測刪除索引／核對後的端到端成本，未修改舊 DB、V1 或 V2，也不將未落在 phase timer 的 132.597 秒全部歸因於 SHA。

下一個獨立窗口先重新核對原 440 來源及已封存 DB／收據／設定／環境，以唯讀 DB 診斷完整 166,897 validation 分層、固定樣本排名與配對／checkpoint，再補同規模人工 global／2,000 draws／ledger 恢復代理。所有新 SQLite TEMP 設為記憶體並計入程序樹 RSS。上輪 840.406 秒仍列歷史重建保留額，不能冒充新版已實測成本；新窗口不是續接舊 deadline 或 cursor。

若完整分層、逐筆成本、聯合尾端壓力、全形狀重播或真實恢復尚缺任一證據，`T_plan` 保持空值，全量仍不啟動。人工成本代理也不能當作真實 K1 效果或正式原始 draws 驗收。
