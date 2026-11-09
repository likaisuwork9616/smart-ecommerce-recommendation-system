# Stage 12：原 48 筆正重疊 SQL 公平比較

## 固定盤點與事前規格

沿用 V7／V17 原 48 筆、原順序、既有抽取子集與模型；固定參考帳本 2,115,696 bytes，SHA-256 `e47a62bcbdc0b0af5a5285a88e9fefc9b9e270b8ea6cca497ef88c9e3fa3abb5`。本輪繼承 569 份封存來源，已核對 532 份小型來源、61,857,366 bytes；大型來源在實測窗口前後及退出後完整雜湊。

唯一候選為 V21 已封存的「posting 先聚合，再 LEFT JOIN session size」。A／B 均使用相同的 connection adapter 與原 V4 verifier bytecode，僅 B 替換該句 SQL；使用原 V6 checkpoint。原 V4、V6、V7、V17、V21 方法與歷史產物保持封存。

| 設定 | 固定值 |
| --- | --- |
| 暖機 | A、B 各一次，共 96 查詢，不參與判斷 |
| 正式配對 | AB／BA／AB／BA／AB／BA，共 576 查詢 |
| 全部核對 | 14 次 fresh run × 48＝672；全部完整 payload、工作量與實體帳本對回原參考 |
| 主要指標 | verification＋append 扣內含 commit＋全部 commit（含最後 flush）；直接 budget 保存仍保留 |
| 採用門檻 | 至少 5／6 對較快、成對節省百分比中位數 ≥5%、AB／BA 各自節省秒數中位數 >0、B 完整入口中位數不退步 |
| 次要診斷 | 原正重疊、rank、vote、V6 append／budget／commit 與完整入口分列；不改主要口徑 |
| 負載觀測 | 每次完整入口前後連續 200ms 目標取樣，首尾涵蓋及不重疊核對；兩模式相同設定 |
| 資源與停止 | 單一 1,800 秒窗口及原 V5 資源限制；來源、輸出、工作量、位元組、期限或資源失敗就停止，保存證據 |
| 快取 | 開始暖機前清一次 verifier Python 快取；不清 OS／SQLite 快取、不刪較慢結果 |
| 後續限制 | 只執行原 48 筆；未通過就結束，不追加對次、換樣本、改門檻或執行 34 筆 |

負載為環境背景，不據此校正成績或推論 Ollama 減速；不呼叫 Ollama 推論、不更動服務。所有實測循序進行。若唯一窗口中斷，須先核對並交代該失敗窗口，不得默默重開。

屬已曝光 validation 的工程比較，新增身分為 0；覆蓋仍 55／55 格、170 個可比較查詢、232 個歷史身分。主要訓練、完整 validation、主要 bootstrap 與最終保留測試皆不啟動。

目前只有規格，尚無本候選真實加速比例。V17 投票候選未通過的結論維持。

[盤點](../reports/stage12/retailrocket_session_knn_v22_overlap_inventory_20261109.json) · [封存規格](../reports/stage12/retailrocket_session_knn_v22_overlap_specification_20261109.json)
