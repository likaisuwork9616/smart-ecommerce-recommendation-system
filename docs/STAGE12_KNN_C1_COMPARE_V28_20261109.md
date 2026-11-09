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

## 真實入口整合驗收完成

**81／81 項合成驗收通過**，耗時 84.494 秒，失敗／錯誤／跳過均為 0。新 V28 契約、門檻與整合 8 項，加上 V27 全部 73 項回歸。這是合成驗收時間，不是原 48 筆效能。

新入口的同一份 `run_worker`／`run_publisher`／`run_pipeline`／`audit_completed`／release bytecode，在人工 48 筆與較大人工未來商品目錄上，實際循序產生十四份帳本，再由獨立子程序重建與核對。新 V28 harness 沒有 padding 或預載快照；較大的人工初始化工作讓負載取得完整首尾樣本。保留原 V27 人工回歸的既有安排，不將它混成真實資料或加速證據。

變更原樣本／context 依賴／方法／期限／資源、合成 metadata 冒充真實 request、未完成 worker、已有 request 重測、成本／事件／負載／cache／payload 修改、外層存活程序及退出不符均拒絕成功。門檻測試涵蓋五對、5%、RC／CR、冷啟動七次總和及 primary 退步限制；不採用條件沒有降低。

真實入口由 `source_contract()` 合併原來源與本輪 accepted methods／紀錄，固定原 15 份 binding 及四份依賴；C1 key 包含完整 closure 與所有封存語意方法。worker 先核對完整來源，再讀共同輸入；每次原 create 與鎖定後 force=True 核對不變。publisher 只從已固定 request 取得 context 契約並自行讀模型／counts／catalog，不再經由合成資料標記啟動。

操作：`.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_compare_v28 --acceptance` 已執行一次；接著 `--measure` 啟動唯一真實窗口。已有 request 拒絕重開，完成後 `--release <原 namespace>` 只重稽核，不重跑排名。

此階段尚未啟動真實比較；下一步循序執行原 48 筆。原 V27、V26 與更早方法／收據保持原狀。

[真實入口驗收](../reports/stage12/retailrocket_session_knn_v28_compare_acceptance_20261109.json)
