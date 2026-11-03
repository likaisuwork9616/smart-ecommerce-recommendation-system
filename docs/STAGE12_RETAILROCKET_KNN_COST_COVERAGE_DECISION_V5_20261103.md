# Stage 12：V5 成本覆蓋、週期保存分項與全量決策

本輪已補新版完整獨立重建、同一 query 的聯合結構尾端，以及完整筆數／真實格式的工程 ledger I/O、global、恢復及新 self-reference draws 成本。**決定仍不啟動全量 K1 獨立反讀，預留測試 locked，K1−C1 無正式結論。**

## 實際完成範圍

| 工作 | 實際結果 | 狀態界線 |
| --- | --- | --- |
| 新版完整獨立重建 | 248.676 秒；窗口 321.312 秒，1,180,256 sessions／1,587,436 memberships，模型 receipt 同舊封存 | 1 次工程獨立重建，0 新主要 fit |
| 全窗聯合結構與樣本 | 166,897 結構 rows、12 個非空層、48 筆四臂核對通過 | 選樣不用 target／效果；有限樣本不是全人口 timing 上界 |
| 完整 source-backed 工程 ledger | 166,897 records／62,235 visitors／2,608 chunks，2,413,599,879 bytes；110 個已驗參考 canonical payload 同值 | 原主輸出其餘列仍未獨立排名驗收 |
| 完整工程鏈＋七路來源 EOF 定位 | **177.864 秒** | SHA／manifest／ordinal／key／roster 全鏈，source-only EOF；不是完整已驗 K1 prefix |
| 全四臂／conditional／切片 global 成本 | **532.128 秒**；166,897 records／62,235 visitors／222,754 catalog union | 固定形狀核對通過，未與原 aggregate 作科學驗收 |
| 新 2,000 engineering self-reference draws | **332.927 秒**；每 draw 62,235 visitors | 新私有參照與輸出，原真實 draws 未作內容驗收 |
| 同 48 筆 budget 觀測重測 | **16.829 秒**；原科學 payload 實體 bytes 相同 | 0 新 unique key；逐筆／commit／stage／setup 分開歸類 |

本次最後窗口在 UTC **2026-11-03T07:46:02.977120+00:00** 觀察正常退出 0，總計 **1,194.094 秒**。初末 **522 份來源綁定**一致（58.150／74.714 秒），3 個記錄程序身分退出後均不存活。前置少量 preflight 及退出後唯讀稽核另計，不回填工程窗口。

## 週期 budget 保存如何拆帳

[觀測器](../scripts/retailrocket_session_knn_checkpoint_cost_v5.py) 是 V4 TimedStore 的薄子類，只量 `budget.json` 真實 JSON 寫入／flush／fsync／rename 的 `_atomic` 呼叫。原檢查、期限、鎖、保存與失敗行為保留；5 項合成測試全過，驗收入口 1.456 秒，固定時鐘案例的 ledger／manifest／budget bytes 同值。真實重測只證科學 payload bytes 與原 48 筆相同，新 namespace 的時間與控制中繼資料自然另有身分。

| 上下文 | 寫入次數 | 秒數 |
| --- | ---: | ---: |
| chunk_commit | 2 | 0.011940 |
| query_append | 4 | 0.067355 |
| stage | 4 | 0.022262 |
| store_setup | 1 | 0.005684 |
| writer_setup | 1 | 0.015248 |

合計 **12 次／0.122489 秒**；直接發生在 query append 的 **0.067355 秒**，只從同一筆 `append_without_commit` 拆出。嵌套 commit 的 budget 仍在原 commit，stage／setup 亦留原上下文，沒有把同一費用扣兩次，也沒有刪除原高值。

發布前從保存的原逐筆計時、budget 事件及凍結名冊重算所有分項、各層最大值與下表情境；另核 CP chain／queries seal／原 deadline／budget、48 筆數量／key／原 ordinal／各層覆蓋及實體 payload 串接 SHA。

## 成本情境與決策

| 情境 | 秒數 | 小時 | 解讀 |
| --- | ---: | ---: | --- |
| 第一個 joint 窗口：verify＋append，另列 chunk commit | 17,176.067 | 4.771 | 原始觀測完整保留，可能含週期 budget 寫入 |
| 新重測：原 verify＋append，另列 chunk commit | 23,796.047 | 6.610 | 新窗口自己的原觀測 |
| 同次重測：另拆直接 periodic budget | 21,494.632 | 5.971 | 只扣同次真實觀測的該筆 budget 費用 |
| 上列拆帳後分量乘提案兩倍餘裕 | 42,989.265 | 11.941 | 尚未加入其他必要階段 |

以上為 Σ每層母體數×樣本最大值的**條件工程情境**，不是全量實測、統計上界或完成保證。Cache／系統狀態未控制，不把兩窗口相減稱為因果加速。原觀測與新拆帳情境乘提案餘裕後均超過 **4.5 小時規劃上限**及 **6 小時候選總窗口**；這些門檻取自原成本提案，不是本次新全量授權。因此維持 **no-go／不啟動**。

**完整 T_plan 仍空值。** Rank 內含於 verification；append 已含編碼／寫入。完整工程 builder 另含解析與 given-ID 指標算術，不能整段盲加到 query projection，偽造精確無重疊總工時。Global／draw 的內部計時與整個 phase 亦不能重複加總。

## 工程覆蓋與科學驗收分開

完整工程 ledger 是從原存四臂輸出作 schema／指標自洽與實體 I/O 覆蓋；110 個已驗 keys 的 adapter 校準不代表其餘列的獨立鄰居、相似度、排名、全域或原 bootstrap 正確。完整工程鏈恢復也不是完整已驗 real ledger 恢復。

工程 draw phase 內，新 fixture 生成 49.737 秒、回播 122.101 秒，均已包含於 332.927 秒入口；額外入口成本包括來源／工程封存核對、完整 ledger 讀取與 visitor delta 準備。原 bootstrap 檔只可能在外部來源 SHA 核對時視為 opaque bytes 開啟，沒有讀取內容作原 draws 驗收。所有 aggregate 效果值、逐 query／visitor 值及工程 draw deltas 都不公開。

本次 V5 成本補量各窗口累計 1 次新工程獨立重建、真實工程 K1 計算 96 次＝joint 48＋最後窗口同 48 重測；最後窗口只有 48 次，已驗不同 keys 總數仍 110。**0 新主要 fit／validation／bootstrap、0 final／refit／預留測試。** 原 V1 partial 與 923 觀測不續接，新診斷窗口不延長舊 builder／原反讀期限。

抽樣程序樹加 supervisor RSS 峰值 **743,522,304 bytes**，本次執行目錄 **4,328,542 bytes**；既有 2.414 GB 工程 ledger 是唯讀輸入，不在新目錄峰值中。退出後另 rehash 5,218 份舊工程檔，確認 bytes 未變。抽樣值與 OS temp／cache 覆蓋不足，均不是未來全量資源上界。

下一步先釐清大量 query 所屬聯合層的 SQL／投票／append 成本與分層情境敏感度，保留原樣本及精確／恢復守門再量；之後才提獨立全量驗收規格。每日 10% 延遲提醒與 Dashboard 暫緩不變。

依據：[完整成本評估](../reports/stage12/retailrocket_session_knn_v5_cost_coverage_decision_20261103.json)、[本次實測與退出證據](../reports/stage12/retailrocket_session_knn_v5_ledger_replay_cost_20261103.json)、[5 項觀測器驗收](../reports/stage12/retailrocket_session_knn_v5_budget_observer_acceptance_20261103.json)、[完整工程 ledger 建置](STAGE12_RETAILROCKET_KNN_SOURCE_LEDGER_BUILD_V5_20261103.md)。
