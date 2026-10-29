# Stage 12：K1 一次真實 validation 的停止與證據保存

本輪於 2026-10-29 臺北時間 11:04:09 啟動一次凍結入口，14:34:09 依使用者追加的整輪 3 小時 30 分鐘上限停止。主要 train 索引、validation 與 bootstrap 已產出；完整獨立反讀未完成，所以沒有驗收通過的 K1−C1 比較結論。本輪不是推薦效果不佳的證據，也不是原程式 6 小時限制觸發。

實際紀錄見[停止與保存報告](../reports/stage12/retailrocket_session_knn_v1_validation_attempt.json)。原[凍結入口](STAGE12_RETAILROCKET_KNN_VALIDATION_ENTRY_V1.md)、比較規格、演算法與驗收規則保留原 bytes。沒有重跑、縮減反讀、變更 500 鄰居或以部分驗收替代完整驗收。

## 本輪狀態

| 工作 | 狀態 | 實際證據與界線 |
| --- | --- | --- |
| 啟動前與停止後來源核對 | 通過 | 各核 358 份來源、61 份準備驗收產物與環境；停止後僅做 bytes／設定／gate 核對 |
| 唯一一次 train K1 | 主要輸出已產出 | fit audit 記錄 1,180,256 sessions、1,823,018 baskets；未取得本輪完整獨立驗收 |
| 真實 validation／bootstrap | 主要輸出已產出 | 保存檔案實數 166,897 query 列、2,000 bootstrap 列；列數及 SHA 不代表語意驗收通過 |
| 完整獨立反讀 | 未完成 | 有 oracle.sqlite；無 acceptance.json／output_guard.json；沒有持久逐 query 進度收據，通過筆數未知 |
| K1−C1 比較 | 未驗收 | 不發布主要 NDCG 差或信賴區間，不做勝負判定 |
| 執行與重試 | 1 次／0 次 | 外部 watchdog 到時停止實際 Python worker；全部部分產物原地保存 |
| 最終選模／重擬合／預留測試 | 未啟動 | final model 未選；refit 與 test 排名皆 0，原 gates locked |

## 時間與資源

- 原凍結程式限制仍是 6 小時、8 GiB RSS、20 GiB 執行目錄；使用者在執行中縮短為包含已用時間的 3 小時 30 分鐘。外部 watchdog 沒有修改凍結程式。
- 停止訊號在啟動後 12600.015 秒送出；確認 worker 結束為 12600.096 秒。外部每 5 秒觀測器於 12604.032 秒記錄退出；這個尾差是觀測延遲，不能當成研究繼續執行。
- 主要輸出最早在約 28.59 分鐘被觀測到；oracle.sqlite 約 29.26 分鐘出現。這是檔案出現的抽查時間，不是精確 phase 完成收據。
- 實際 worker 抽查 RSS 峰值 1.730659 GiB；觀測器在啟動後才附掛，這不是整段生命週期或 OS 硬性峰值。Windows venv launcher 的 RSS 不能代替 worker RSS。停止時執行目錄 2,918,709,292 bytes（2.718260 GiB）。
- 已觀測的 RSS／磁碟沒有達到原上限；停止原因是使用者的較短時間限制。沒有原生 resource_usage.json，不以外部抽查冒充原生資源驗收。

反讀程式對每個 query 掃描所有 train sessions，再逐一計算所有合乎時間條件的候選商品，與主要計算使用的索引路徑不同。這可解釋長時間落在反讀階段，但現有紀錄沒有逐 query checkpoint，因此不能推估完成百分比或剩餘時間。此次沒有修改這個實作。

## 保存與後續操作

真實部分產物原地保存在 Git 忽略的 `shop-mysql-runtime/retailrocket_session_knn_paired_v1/`。外部 invocation、每 5 秒觀測、worker 資源、使用者期限、實際停止結果、停止後來源核對及 SHA 保存清單位於 `shop-mysql-runtime/verification/retailrocket-session-knn-validation-v1/`。報告列出每個檔案 bytes／SHA-256，JSONL 另列實數行數；SQLite 只讀取 bytes，沒有開庫復原或接續 oracle。

Windows 外部終止沒有執行 Python 例外處理，因此沒有原生 failure.json；也沒有補造 failure、acceptance 或 output_guard。缺少成功 guard 的 namespace 仍是 partial，禁止覆寫、刪除後重跑或當成準備成功。

`--run-validation` 已消耗本版唯一一次機會，不再執行。原 CLI `--verify` 會拒絕 partial；本輪停止後使用現有 `verify_prepared()` 與 `gates()` 只讀核對準備來源，沒有呼叫模型、排名、bootstrap 或完整反讀。保存清單通過只代表 bytes 可追溯，不能升格為研究驗收。

本輪沒有重跑合成測試；83 項是前輪準備驗收紀錄，這次只核對其來源與產物 bytes。公開報告不包含未驗收的 K1 效能數字。既有 P0／C1／D1 證據未變；validation 仍屬已曝光開發窗，預留回溯測試未使用。延遲每日 10% 提醒預算與 Dashboard 暫緩不變。

後續若要處理完整反讀成本，應另開工作先檢視成本與等價驗證，再決定是否另立版本；本輪到此結束，不自動接續或重試。最終選模、重擬合與預留測試仍另行規劃。
