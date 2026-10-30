# Stage 12：V1 獨立反讀實際狀態與事後核對

2026-10-30 核對確認：**另授權反讀已不在執行，未取得完整獨立驗收，K1−C1 尚無驗收結論。** 最後進度觀測為臺北時間 2026-10-29 17:05:57.877641，已走完當次逐 query 核對 923 筆；這只是觀測下界，不是最終驗收筆數、整體完成百分比或可續跑 checkpoint。

本次於 10 月 29 日 15:12:05 啟動，原定絕對截止為同日 17:20:00。現存紀錄沒有成功、例外、期限停止或 supervisor 收尾收據，不能把原定截止當成實際停止時間。Windows System 事件顯示 17:07 左右有關機／重新啟動，但沒有逐程序退出紀錄，worker 的停止時刻、退出碼與直接原因仍未知。

本輪依使用者要求核對既有證據，另存[2026-10-30 事後核對報告](../reports/stage12/retailrocket_session_knn_v1_readback_status_audit_20261030.json)。它不是補寫 10 月 29 日的 completion 或驗收收據。本輪沒有重啟主要 pipeline 或 oracle，沒有續跑、重抽 bootstrap、SQLite 復原、選模或開啟預留測試。

這次獨立反讀與原本唯一一次主要訓練／validation／bootstrap 執行分開記錄。原執行仍保留 partial 狀態及[前輪停止報告](../reports/stage12/retailrocket_session_knn_v1_validation_attempt.json)，不因本次事後核對而改為成功。

## 2026-10-30 核對結果

| 工作 | 實際結果 | 證據界線 |
| --- | --- | --- |
| 程序身分 | 原 worker PID 15264、launcher PID 15428 均不存在；未找到相符的研究程序 | 現況核對不能反推歷史停止時間或退出碼 |
| 進度紀錄 | 224 筆均可解析，逐 query 計數單調不減，末筆為 17:05:57、923 筆；沒有全域驗收完成旗標 | 923 是觀測下界，不是已正式驗收筆數 |
| 資源觀測 | 1,363 筆均可解析，末筆為 17:05:58.097018 | 觀測中斷時間不等於程序停止時間 |
| 凍結來源／準備產物 | 358／61 份 bytes、大小與 SHA 核對通過，環境與契約 metadata 相符 | 未重算模型、排名或研究效能 |
| 原整輪停止與保存 | 九份原產物、15 份停止觀測證據均符合原報告 SHA，原目錄 inventory 相符 | 原整輪仍是未完整驗收的 partial |
| 七份主要輸出複本 | 均符合原複製清單 SHA，也與原檔逐份相符 | bytes 完整不等於內容已通過獨立 oracle |
| 原 oracle 與包裝程式 | 符合當時綁定 SHA | 沒有修改凍結算法或再執行反讀 |
| 收尾收據 | 下節八個預期路徑均缺少 | 無法證明成功、例外或期限終止的實際收尾 |
| 最終選模／重擬合／預留測試 | 六份原 gate 身分及 locked 狀態通過，相關 final／test 路徑依規則不存在 | 仍未啟動；沒有新效能結論 |

七份複本及本次 `oracle.sqlite` 共八份工作檔已列入今日另存的 SHA 清單。SQLite 僅以檔案 bytes 讀取，不開啟、不復原；沒有先前完成時的 SHA 可供比對，不能將今日清單稱為當時已完成的保存驗收。

## 時間與停止證據

下列時間均為臺北時間，系統事件以 Windows XML 的 UTC 時鐘轉換，未依檔案修改時間推估程序退出。

| 時間（2026-10-29） | 實際證據 |
| --- | --- |
| 14:34:10 | 原整輪執行的 worker 已依使用者總時限停止；前輪有退出碼 15 與外部停止收據，與後來單獨反讀分開 |
| 15:12:05 | 另授權反讀啟動，主要訓練／validation／bootstrap 新產生各 0 次 |
| 15:12:58 | `oracle_started.json` 記錄呼叫原 V1 oracle，從頭反讀，沒有使用 checkpoint |
| 17:05:57.877641 | 最後逐 query 進度觀測：923 筆，`global_acceptance_complete=false` |
| 17:05:58.097018 | 最後 supervisor 資源觀測 |
| 17:06:55–17:07:03 | EventLog 6006、Kernel-Power 109、Kernel-General 13：事件服務停止及系統關機事件 |
| 17:07:24–17:07:30 | Kernel-General 12、EventLog 6005：系統啟動及事件服務啟動 |
| 17:20:00 | 原定絕對截止；沒有對應的本次期限停止／completion 收據，不能宣稱確於此時停止 |

系統關機／啟動發生於末次觀測後、原定截止前，是相關時段的中斷背景證據；沒有逐程序停止事件能證明 worker 的確切退出時刻或直接原因。空白的 `stdout_stderr.log` 也沒有提供例外堆疊。今日核對沒有補造上述缺漏。

本次觀測目錄缺少：

- `completion.json`：supervisor 的退出碼及收尾結果。
- `deadline_stop_started.json`：外部期限停止紀錄。
- `worker_outcome.json`：worker 的完整成功紀錄。
- `worker_failure.json`：worker 的例外／期限例外紀錄。
- `post_stop_source_and_original_check.json`：原定收尾程式的來源核對。
- `preservation_manifest.json`：原定收尾保存清單。

工作目錄也沒有 `independent_readback_receipt.json`；原定公開報告 `reports/stage12/retailrocket_session_knn_v1_readback_only_20261029.json` 未產生。以上共八個預期路徑均已核對。`preserve_result.py` 必須先讀取 `completion.json`，因此本輪沒有執行它或替它補造輸入，而是另存今日事後核對報告與清單。

## 執行範圍

| 工作 | 本次範圍 | 狀態 |
| --- | --- | --- |
| 凍結來源與準備產物 | 358 份來源、61 份準備產物、環境與 gates | 啟動核對通過；10/30 事後再次通過 |
| 原執行產物 | 九份檔案依前輪保存 SHA 核對，原目錄不寫入 | 啟動及 10/30 事後核對均通過 |
| 主要輸出 | 將 aggregate、bootstrap、fit audit、postings、queries、sessions、train sessions 七份檔案按 bytes 複製到新目錄，逐份核 SHA | 完成；沒有主要研究計算 |
| 原 V1 獨立反讀 | 同一凍結函式，獨立重建 SQL／訓練關係，再逐 query 全掃 sessions／候選，最後核原有 bootstrap 與聚合 | 已不在執行；僅觀測到 923 筆，無完整驗收收據 |
| 新主要 train／validation／bootstrap 產生 | 不呼叫原主要 pipeline | 0 次 |
| 最終選模／重擬合／預留測試 | 本次未授權 | 0 次，test locked |

獨立反讀會按照 V1 公式重算應有答案以核對既有輸出；其中的 SQL 訓練關係重建、query 驗算及 bootstrap 反讀屬驗收工作，不會產生另一套主要訓練／validation／bootstrap 結果。V1 的相似度、500 鄰居、全掃、精確 Fraction、排序、分母與 2,000 次既有 draws 核對規則沒有修改。

## 原定執行與停止保護

- 原凍結 `scripts/retailrocket_session_knn_readback.py` 保留原 SHA：`3cdb1a6030c0e06cc89f0dc4f722ab9531255b137d702d6271e538024ce5745f`。
- 額外包裝只負責來源／複製檔身分核對、呼叫原 oracle、記錄狀態、資源與絕對截止時間，不呼叫主要 fit、validation 或 bootstrap 產生函式。
- 原資源限制 8 GiB RSS／20 GiB 執行目錄／最低可用記憶體與磁碟保留；包裝程式原定由程式內檢查與外部 supervisor 執行 17:20 停止期限，依 worker PID 與建立時間辨識程序。這是程式設計，不是本次確實觸發期限停止的證據；實際收尾缺漏以上節為準。
- 寫入限制指向本次新目錄與觀測目錄；不寫入原九份產物，不補造原 namespace 的 acceptance、failure 或 output_guard。
- 原定完整成功、到期或失敗均各存收據；本次均未找到，不能追溯改稱原整輪入口或另授權反讀已成功，也不自行追加嘗試。

## 進度觀測的界線

原 V1 函式已有 `watch` callback。本次只在該 callback 內定期讀取原函式的 `checked` 計數，約每 30 秒寫一筆進度；原計算與比對流程不變。`checked` 是已走完當次逐 query 核對的筆數，後面仍有全域名冊、聚合及 bootstrap 驗收。

觀測數不是已完成整體驗收的百分比，最後一次觀測也只代表當時完成筆數的下界。這些紀錄不是可恢復的計算 checkpoint，不能據此跳過前段 query 或接續累計器。完整驗收需要原 oracle 返回、完整收據及來源核對，本次證據不滿足這些條件。後續若需再次驗收，應另行規劃成本與執行方式。

## 保存位置

原九份產物：`shop-mysql-runtime/retailrocket_session_knn_paired_v1/`，原地保留。

本次七份複製輸入與部分 oracle.sqlite：`shop-mysql-runtime/retailrocket_session_knn_v1_readback_only_20261029/`，未找到完整獨立收據。

本次原有授權紀錄、包裝程式、preflight、輸入 SHA、worker 身分、進度與資源觀測：`shop-mysql-runtime/verification/retailrocket-session-knn-readback-only-20261029/`；原定截止／收尾／最終保存清單缺少，保持原狀。

2026-10-30 事後核對的程式、精簡系統事件與 SHA 清單：`shop-mysql-runtime/verification/retailrocket-session-knn-status-audit-20261030/`，另存於新目錄，不寫回原執行或反讀目錄。

以上本機資料、逐筆輸出與執行狀態均由 Git 忽略；公開僅新增聚合狀態核對報告，不發布未完整驗收的推薦數字。每日 10% 延遲提醒預算與 Dashboard 暫緩不變。
