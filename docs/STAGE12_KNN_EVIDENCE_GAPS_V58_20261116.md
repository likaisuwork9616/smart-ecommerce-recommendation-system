# Stage 12｜V58 負載與等待時間的證據缺口

**決策：先不新增量測。** 既有 V47／V48 有整入口負載原始紀錄，下一步可先對照正式六對的負載摘要與採樣覆蓋。若要回答序位 32／33 的特定分項究竟在運算還是等待，現有紀錄不足，屆時才另立量測規格。本輪沒有重跑固定 48 筆、解碼、訓練或即時資源採樣；維持暫不採用 V46 為完整入口預設。

## 本輪查了什麼

| 工作 | 狀態與實際結果 |
| --- | --- |
| 封存來源 | V47／V48 各 88 檔，共 176 檔，bytes 與 SHA256 對上各自 `closed_manifest.window_evidence` |
| 實際程式 | 5 份 collector／事件／入口／冷比較／supervisor 程式，各對兩窗 `request.sources`，10 個綁定相符 |
| 負載紀錄 | 30 份 telemetry，共 3,162 筆；其中 28 個冷入口共 2,224 筆，兩個 publisher 共 938 筆，分開計算 |
| 時軸與欄位 | 28 個入口的採樣包住 `entry_span` 與 `run.total`；2,156 個 wall 事件、1,344 筆 query 時長及 append／budget 欄位完成檢查 |
| CPU 診斷 | 28 份 `profile.json` 都是空陣列；V20 有 thread CPU 工具，但 V47／V48 沒有啟用 |
| 界線 | 本輪是針對保存欄位與來源的盤點，不是重新執行前輪全部輸出／工作量驗收，也未新增效能或因果結果 |

每窗 88 檔為：14 個入口各 6 檔（`telemetry_records`、`entry_span`、`events`、`measured`、`observations`、`profile`），加 publisher 的 telemetry／entry_span／events 及原 request。原始紀錄、程序身分與模型仍留在 Git 忽略路徑；公開[盤點收據](../reports/stage12/retailrocket_session_knn_v58_evidence_inventory_20261116.json)只保存來源描述、欄位名稱與聚合結果。

## 已有證據與缺口

| 問題 | 實際已有 | 能回答到哪裡 | 尚缺什麼 |
| --- | --- | --- | --- |
| 當時整機是否繁忙 | 整機 CPU 利用率、logical CPU 數、記憶體 total／available／used／percent | 入口期間的整機背景與粗時間變化；整機數值也包含本實驗 | 每核心利用率、其他所有程序的資源分布；不能指認哪個程序造成延遲 |
| worker 是否使用 CPU | worker 程序累積 user／system CPU 秒、RSS、身分與狀態；摘要有相鄰樣本的單核心百分比 | 整個程序在採樣間隔內的 CPU 使用；含同程序的採樣執行緒 | 逐 query／分項的同邊界 thread CPU；不能直接用入口 wall 減程序 CPU 當等待 |
| Ollama 是否活動 | 名稱前綴為 Ollama 的程序 CPU／RSS 與掃描狀態 | 被觀測程序在採樣間隔內的活動 | 不包含所有背景程序，也不證明 Ollama 導致特定查詢變慢 |
| 是否有磁碟活動 | 整機 `read_bytes/read_count/read_time/write_bytes/write_count/write_time` 及狀態 | 相鄰有效樣本間的整機計數差量 | worker／查詢所屬 I/O、檔案或要求對應、阻塞期間；整機 read/write time 不是查詢等待時間，值為 0 亦不能證明沒有等待 |
| 是否在排程、鎖或 I/O 等待 | 現有 wall 時長會包含其間所有經過的時間 | 可以定位時間差落在哪個計時區間 | 沒有 context-switch、執行緒排程／阻塞或明確 wait-state 紀錄，不能分類等待原因 |
| 能否對到 32／33 或連續序位區段 | 原執行序位、query／ranking 分項耗時、邏輯工作量 | V50–V57 已描述耗時方向、分布與連續性 | 沒有實存逐 query／ranking 子階段起訖；累加時長只能另作假設性粗估，不能精準復原時間戳 |
| 能否對到粗階段 | `events.json` 的 wall `start_ns/end_ns`，以及 telemetry 的 monotonic 起點 | 可另查採樣區間與較長事件的粗重疊、覆蓋與跨界情況 | 不是逐 phase CPU；跨階段樣本不能均分、插值後當實測分項負載 |
| 觀測本身的成本 | 每次 `collector_seconds`、實際間隔、缺格估算、狀態 | 觀測工作本身經過多久、是否有較大採樣間隙 | 缺 V47／V48 同條件 observer 開／關對照；capture elapsed 不是可從入口直接扣除的干擾成本 |
| 全窗口監督 | supervisor 保存程序身分、全窗口 RSS／執行目錄檔案容量峰值、耗時與退出資訊 | 資源上限及正常結束證據 | 未保留逐次 poll 的 CPU／I/O 時間序列；檔案容量峰值不是 I/O 吞吐量 |

原 collector 摘要本來就限定為整入口背景資訊。首個 CPU 值不納入、程序身分改變或計數器失效／重設不跨接、不補零；system CPU 與 process CPU 的分母不同，不可直接相減。原始紀錄仍在，**「尚未比較負載」和「沒有負載證據」是兩件事**。

## 採樣尺度的實際限制

以下含每窗 2 個暖機與 12 個正式入口，不含 publisher。間隔是各入口內相鄰 capture 起點之差，保留 start／end，不跨入口接續；最後一個 end capture 可小於 200 ms。

| 保存項目 | V47 | V48 |
| --- | ---: | ---: |
| 入口 telemetry 筆數 | 1,161 | 1,063 |
| publisher telemetry 筆數（另列） | 447 | 491 |
| 入口相鄰樣本間隔中位數 | 232.314 ms | 232.629 ms |
| 入口最大樣本間隔 | 873.228 ms | 976.233 ms |
| capture elapsed 中位數 | 9.763 ms | 11.177 ms |
| capture elapsed 最大值 | 673.182 ms | 772.859 ms |
| 原公式估算的名目缺格合計 | 45 | 62 |

collector 是每次採集完成後等待 200 ms，再採下一筆；實際間隔包含採集與排程時間。單筆 capture 的各欄也依序讀取，不是同一瞬間的同步快照。缺格是按原公式 `max(0, floor(gap / 0.2 + 0.5) - 1)` 的估算，並非已證實遺失多少筆資料。

[V54 四例](STAGE12_KNN_ABSOLUTE_ARMS_V54_20261113.md)的 16 個目標分項皆短於名目 200 ms，最長是第 2 對原版序位 33 投票的 127.2273 ms。加上沒有逐筆起訖，不能把某一段 CPU／磁碟差量分配給這些分項。V57 的五筆連續同向也只表示序位連續，不能換算成已知長度的持續負載。

## 是否需要另行量測

| 想回答的問題 | 本輪判斷 | 下一步與停止界線 |
| --- | --- | --- |
| 完整入口退步是否伴隨不同的背景負載或較差採樣覆蓋 | **先用舊資料，不需要立刻重測** | 先固定口徑，列出兩窗全部正式六對的入口耗時、CPU／記憶體／磁碟摘要、collector 與 coverage；暖機和 publisher 另列。不可只挑退步或目標四例，也不可視為負載校正後效果 |
| 32／33 的特定分項是 CPU 增時，還是非 CPU 經過時間增加 | **現有資料不足；若仍要追問，需另案量測** | 先設計同邊界的 query／分項 wall 起訖與 thread CPU，驗證時間單位、量化誤差、輸出一致性與觀測開銷；本輪不實作或執行 |
| 非 CPU 時間是否由磁碟、排程、鎖或某外部程序造成 | **單有 wall／thread CPU 仍不夠** | 只在前項顯示值得追查時，再界定所需的程序 I/O／排程／阻塞證據；CPU 差額仍不得命名為已證實的 I/O wait |
| V46 是否可改為完整入口預設 | **維持暫不採用** | 現有採用判斷不因缺口盤點改變；未來若新增診斷，再另配對無診斷的完整冷入口確認效果是否保留 |

**建議的下一小步是既有整入口負載摘要與覆蓋對照。** 若粗資料仍不能解釋波動，應明確保留「原因未知」，不必反覆切分同一批粗樣本來製造更細的結論。只有研究問題確實需要 CPU／非 CPU 區分時，再提出量測範圍、開銷驗證和時間預估，另行開始。

## 程式與來源定位

- [V47 實際接入](../scripts/retailrocket_session_knn_cold_v47.py)：`observed_run` 克隆既有入口；`audit_saved_runs` 要求 baseline 與空 profile。V48 沿用此核心。
- [V28 入口](../scripts/run_retailrocket_session_knn_compare_v28.py)：`observed_run`／`run_publisher` 啟用 `Observation` 與 `TelemetrySampler`，保存外層起訖與 raw。
- [V18 collector](../scripts/retailrocket_session_knn_reinforcement_v18.py)：`_process`／`_capture` 保存欄位；`_observe` 排程；`summarize_telemetry` 定義摘要、缺值與解釋界線。
- [V24 wall 事件](../scripts/retailrocket_session_knn_sources_v24.py)：`Observation.span` 保存 `perf_counter_ns`；`_SetupClock` 不保存逐 query 時軸。
- [V4 query 計時](../scripts/retailrocket_session_knn_pair_v4.py)、[V7 ranking 分項](../scripts/retailrocket_session_knn_vote_v7.py)：保存時長；正重疊與投票計時都包住 SQL 取列及相關 Python 處理，不是純 SQL 等待。
- [V20 診斷能力與限制](../scripts/retailrocket_session_knn_diagnostics_v20.py)：有 thread CPU 工具，但本輪兩個歷史窗口未啟用；wall-minus-thread-CPU 仍有量化與歸因限制。
- [V5 supervisor](../scripts/retailrocket_session_knn_cost_window_v5.py)：監督與峰值保存範圍。

盤點只使用標準函式庫讀取既有 JSON、驗證雜湊並彙整欄位；未呼叫 runner、SQL、模型或 psutil 即時 API。兩個獨立唯讀檢查分別核對 collector 啟用鏈／採樣數與 168 個入口證據檔／時間邊界，結果相符。重核時可依收據的兩份公開來源報告取得 `namespace` 與原 manifest，按上述每窗 88 檔重查；不需啟動原實驗入口。

固定 48 筆是已曝光的 validation 工程樣本。1,344 筆是同一組查詢在兩窗、兩臂和重複入口的紀錄，不是 1,344 個獨立樣本；保留測試持續 locked。
