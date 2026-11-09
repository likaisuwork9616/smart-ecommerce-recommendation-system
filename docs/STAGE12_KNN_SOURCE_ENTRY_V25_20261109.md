# Stage 12：受監督來源／初始化診斷與獨立發布

## 整合範圍封存

承接已驗收的 V24 觀測核心，這輪整合並驗收實際入口，再循序實測原 48 筆。原 V24 方法、規格與收據保留；V25 明確授權實際 14 次 R／D run，補上前輪 pending_scope。

| 固定項目 | 整合規格 |
| --- | --- |
| 排程 | R／D 各一次暖機，六對 RD／DR，14 次 fresh run，共 672 次核對 |
| 原始資料 | 相同原 48 筆、順序、唯讀模型、既有子集及原完整 payload 參考 |
| 程序 | 原 V5 supervisor → pipeline → worker 正常退出 → 獨立 publisher；不重用 worker 的 Python 物件 |
| 時限 | worker 與 publisher 共用同一 1,800 秒絕對期限，外層 V5 資源限制涵蓋兩者 |
| 來源觀測 | worker 前後各一次 closure；publisher 前後各一次 closure；原 create／writer 與發布 open 的 binding 核對全保留 |
| 原方法 | R 原 V4／V6；D 使用已驗收 V24 每次呼叫觀測。原 SQL、保存與安全檢查一致 |
| 負載 | 每次完整 R／D 入口及獨立 publisher，200ms 目標採樣、首尾涵蓋與不重疊核對 |
| 公開條件 | publisher 先寫私人已稽核結果；外層確認正常退出、程序停止及私人證據後才公開 |
| 發布計時 | publisher callback 含私人結果寫檔；其觀測收據輸出及整個 publisher 程序 wall 分列；父程序公開序列化另計 |
| 失敗處理 | 任一來源／結果／期限／資源失敗就保留證據、停止成功發布；已有 request 不重開較快窗口 |

這是已曝光 validation 的工程診斷，R／D 差描述觀測器、機器狀態與順序，不能當優化加速。沒有 SQL 候選採用門檻或新選模。覆蓋仍 55／55 格、170 個可比較查詢、232 個歷史身分；完整 validation 與保留測試不啟動。

目前僅封存整合規格，實際入口驗收及真實診斷待執行。

[整合規格](../reports/stage12/retailrocket_session_knn_v25_sources_specification_20261109.json)
