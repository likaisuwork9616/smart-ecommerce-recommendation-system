# Stage 12：V3 分層、配對與人工成本實測

本輪一次新 30 分鐘工程窗口於臺北 **2026-11-03 12:41:28.492634** 開始、**13:02:37.091561** 觀察正常退出碼 0，實際 **1,268.609 秒（約 21 分 9 秒）**。完成下列成本分量，**不啟動全量真實反讀，K1−C1 仍無正式結論，test locked**。資料來自[實際成本報告](../reports/stage12/retailrocket_session_knn_v3_cost_diagnostic_20261103.json)；新入口的[39 項合成測試](../reports/stage12/retailrocket_session_knn_v3_cost_entry_acceptance_20261103.json)全部通過，0 失敗／錯誤／略過。

| 階段 | 實測成本 | 完成範圍 |
| --- | ---: | --- |
| 起始來源與封存 DB SHA | 73.386 秒 | 原 440 來源加上封存模型／收據／新增方法，共 455 份；原 V2 不重啟，不改舊 budget |
| 完整分層（含 profiler） | 491.907 秒 | 166,897 validation queries 全部 EOF；4 時段×4 posting 層全非空，各固定 4 筆，共 64 probes；選樣不讀 target／效果 |
| 精確排名探測 | 4.215 秒 | 原模型關聯的 64 筆 history／精確 SQL 排名，含 0.846 秒 catalog 準備；未驗全量效果 |
| 七條來源完整掃描與樣本抽取 | 62.808 秒 | raw validation、P0 三 CSV、C1／D1／K1 JSONL 各核 166,897 原 validation rows 至 EOF；所選 ordinal／key 完整對齊 |
| 所選四臂核對與 checkpoint | 17.072 秒 | 64 筆 current／next／targets／四臂原值／Decimal／delta／巢狀 K1 通過；64 records、1 chunk，含 DB copy／hash／setup／append／尾 flush；沒有 candidate／acceptance |
| 人工 ledger 建置 | 320.675 秒 | 166,897 人工 records、2,608 chunks、577,030,099 payload bytes，真實 fsync／SHA／manifest |
| 人工全域重播 | 80.833 秒 | 62,235 人工 visitors、222,754 catalog union；依原序重建四臂 Fold、切片、diagnostics、cross tabs 與名冊 |
| 人工 bootstrap 參照檔準備 | 43.336 秒 | 2,000 draws、每 draw 62,235 indices，共 124,470,000 indices，另存人工參照與輸出 |
| 人工 bootstrap 反讀 | 75.339 秒 | 凍結 checker 核全部 2,000 draws 的 RNG／SHA／分母／delta／EOF；不是原真實 K1 的 draws 驗收 |
| 人工完整 ledger 恢復 | 20.047 秒 | 166,897 records、2,608 chunks 的 SHA 鏈與 JSON 重讀；沒有冒稱真實 control prefix／尾段恢復 |
| 最後來源與 DB 再核 | 72.716 秒 | 全部 455 份一致，六份原 gate locked；沒有 final／refit／test 路徑 |

人工子階段包含在整段 541.009 秒 proxy 內，不能將兩者重複相加。抽樣程序樹加 supervisor RSS 峰值 **1,442,455,552 bytes（約 1.343 GiB）**、執行 namespace **1,072,233,198 bytes（約 0.999 GiB）**；它們是抽樣值，不是完整生命期上界。新 SQLite 連線的 TEMP 設為 MEMORY，已封存主 DB 使用 `mode=ro&immutable=1`，開啟前後拒收 WAL／SHM／journal；TEMP 的記憶體計入程序樹監控。

## 實際找到的成本來源

分層 profiler 觀察到 SQLite `execute` **1,340,483 次、self time 191.820 秒**，`_work` 自身 **139.073 秒**。分層內 watch 共 **38,633,722 次**，其 `__call__` cumulative time **72.107 秒**；整輪含其他階段共有 43,632,838 calls、4,943 次完整 UTC／停止檔檢查。這些是含 profiler 的本輪數字，不能把 self／cumulative time 相加，也不能換算成沒有 profiler 的全輪加速倍數。

另以 50,000 筆人工 membership 量索引：第一 posting 建置與 commit 0.057 秒、第二同欄序索引 0.080 秒，各增加 1,064,960 bytes。這不是 1,587,436 真實 memberships 的建置測試，未據此推估可省下多少原建置時間。完整 V3 重建沒有重跑，歷史 **840.406 秒**仍保留列帳，既不是新版實測也不是上界。

## 為什麼仍不開全量

依事前固定的每層母體數乘該層最大觀測成本：

| 分量規劃情境 | 秒數 | 解讀 |
| --- | ---: | --- |
| rank-only `Σ N_h × t_h,max` | 8,670.991 | history／排名成本；不是完整 paired 成本 |
| paired verification＋append `Σ N_h × t_h,max` | 11,159.009 | 所選逐筆核對與 append 成本，setup、抽取、尾 flush 及其他階段另列 |
| 上列 paired 分量乘提案兩倍餘裕 | 22,318.018，約 **6.20 小時** | 已超過提案的 4.5 小時規劃門檻，亦超過候選 6 小時總窗口，尚未加入其他必要階段 |

rank 與 paired 互相重疊，**不能相加**。每層最大值乘二是工程規劃餘裕，不是統計上界、信賴區間、實測完整耗時或完成保證；不表示真實全量一定要 6.20 小時。它能支持本輪依原提案拒絕啟動，而不能支持延長窗口直接跑。

完整 `T_plan` 仍為空值，另有以下覆蓋缺口：

- 人工 ledger 使用 0／1／3／8 鄰居循環，另量 0／1／499／500 payload I/O，沒有覆蓋真實完整 schema、位元組量及聯合 SQL 尾端。人工 577 MB 與原 2.295 GB query 檔不是同一種 payload 覆蓋。
- 人工來源與部分切片邊際配合固定分母，但活動分組及 joint distribution 為人工分布，不能當真實資料成本上界。
- 真實完整 ledger／六條控制輸出交錯前綴重掃、未提交尾段重做及 bootstrap 中斷後再跑的合併恢復，尚未完整量測；本輪來源抽取與人工恢復是分開的成本分量。
- 新監控下的端到端獨立重建尚未重新計時，未扣除前輪微量測推估節省。

下一步應先降低逐筆配對成本並設計可驗證的來源定位／恢復，再補真實 payload 與聯合尾端工程壓力；沒有完整成本與恢復證據就不另開全量。不改 k=500、分母、平手規則、原 P0／C1／D1 或保留測試。

## 操作與來源界線

新入口為 [run_retailrocket_session_knn_cost_v3.py](../scripts/run_retailrocket_session_knn_cost_v3.py)；`--diagnose` 會建立另一個新 30 分鐘窗口並執行上述工程工作，不能為查看既有結果而重跑。查看結果直接讀公開報告及本機收據。入口核完整 V3 方法名冊／SHA、封存 DB 的舊 request／run／stage 身分、環境與全部來源；來源再核不符、期限或資源不足就保留 partial，不改挑容易樣本或延長舊窗口。

逐筆 keys、targets、推薦清單、模型內容與人工 ledger 均留在 Git 忽略路徑，公開只列聚合成本、分母、形狀及 SHA。主要 fit／validation／bootstrap 產生均為 0；人工 2,000 draws 與所選 64 筆反讀分開標示。每日 10% 延遲提醒與 Dashboard 暫緩維持。
