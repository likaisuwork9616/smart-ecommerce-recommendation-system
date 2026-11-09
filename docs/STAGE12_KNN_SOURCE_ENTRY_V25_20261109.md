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

封存規格時入口與真實診斷尚未執行；驗收及實測結果見下節。

[整合規格](../reports/stage12/retailrocket_session_knn_v25_sources_specification_20261109.json)

## 整體入口驗收完成

**32／32 項合成驗收通過**，耗時 24.298 秒，失敗／錯誤／跳過皆為 0。新整合測試 10 項、V24 觀測核心 11 項、V6 保存成本 7 項及 V23 成本守恆 4 項。

包含 14 份人工 48 筆帳本與完整結果重算、原事件／負載／期限變更拒絕、worker 非零退出不啟動 publisher、publisher 失敗不完成 pipeline、外層失敗不公開、已存在窗口不重測、稽核後資料變更拒絕，以及實際小型子程序的退出觀察和外層兩秒 deadline 清理子程序測試。人工數字不是原 48 筆真實效能。

操作順序：`.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_sources_v25 --acceptance` 完成一次性驗收，之後 `--measure` 啟動唯一窗口。已有 request 即拒絕重開；`--release <原 namespace>` 只做完成窗口的公開資料重稽核，不重跑預測。

worker／publisher 使用同一 request。publisher 在新 Python 程序重新讀取科學 payload、成本、原事件及負載，並對原始來源做兩次完整核對。它保存私人已稽核結果，pipeline 在子程序退出後保存輸出指紋；父程序核對指紋及所有受稽核 worker 證據，再公開 aggregate。公開序列化耗時另存 release 收據。

本輪方法固定 LF、V25 JSON 保留原始 bytes；提交前核對 Git 暫存區指紋，避免 Windows 換行造成規格或方法 SHA 不一致。

此階段尚未執行真實 48 筆。下一步循序實測原 48 筆的 R／D 暖機及六對，仍無任何優化加速比例。

[整合驗收收據](../reports/stage12/retailrocket_session_knn_v25_sources_acceptance_20261109.json)
