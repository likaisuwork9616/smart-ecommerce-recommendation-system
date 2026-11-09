# Stage 12：C1 真實比較入口與原 48 筆公平比較

## 真實入口規格封存

承接 V26 兩候選設計及 V27 的 73 項合成驗收，本輪只啟動 C1；原方法、合成入口與收據保持封存。

| 固定項目 | 本輪條件 |
| --- | --- |
| 樣本與科學參考 | 原 48 筆、原順序／模型／子集與完整實體 payload，不新增樣本 |
| 排程 | R／C 各暖機一次，再六對 RC／CR，十四份 fresh 帳本、672 次核對 |
| 來源與快照 | 原 596 個來源身分、原 15 份 binding 全保留，加入新方法與驗收證據；完整 closure／設定／模型／方法入鍵，一次 cold build、六次 hit |
| 鎖定 | 每次原 create 及取得 writer 鎖後 force=True 都完整重驗，再允許 lookup |
| 監督 | 原 V5 單一 1,800 秒期限及資源限制涵蓋 worker 與獨立 publisher，循序執行 |
| 發布 | 新程序自行讀原模型／counts／catalog 並重建 context；保留前後 closure、十四次原 open、實體 frames、成本／事件／負載／快照事件重算 |
| 計時 | 兩臂同細觀測；沒有人工 padding／預載。冷啟動及每次 guard 都計入完整入口，publisher 與公開序列化另列 |
| 失敗 | 任一來源、帳本、成本、期限或程序退出不符就停止成功發布；已有 request 不重開較快窗口 |

沿用 V26 門檻：完整入口六對至少五對較快、配對節省中位數至少 5%、RC／CR 各自節省中位數皆正；含 cold warmup 的七次 C 總成本也須小於七次 R，primary 配對退步百分比中位數不得超過 5%。所有科學／來源／安全條件均須通過；未達則不採用，不把人工或歷史 R／D 當本輪比較。

已核對 V27 驗收收據、方法及保存證據。本階段只封存真實入口規格；後續須完成並推送整合驗收，才執行本輪唯一真實窗口。尚無本輪實測或加速比例。

這是已曝光 validation 的工程比較；完整 validation 未完成，保留測試鎖定，覆蓋仍 55／55 格、170 個可比較查詢及 232 個歷史身分，沒有新 fit／完整 validation／主要 bootstrap，T_plan = null。

[真實入口規格](../reports/stage12/retailrocket_session_knn_v28_compare_specification_20261109.json)
