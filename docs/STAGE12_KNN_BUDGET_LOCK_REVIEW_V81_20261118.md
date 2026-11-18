# V81｜A12 第二次入口的預算狀態鎖反查

本輪只讀 V80 已留存的 A12 證據與原碼。V80 唯一窗口在 128.75 秒結束，判定 `incomplete_timeout`。已確認第一段角色退出和 64 筆前綴，第二次提交的 129 筆符合原 golden。以下追查阻斷發布的預算狀態鎖。程式修正、新量測及重跑皆為 0。[V80 窗口與保存證據](../reports/mainline/v80_synthetic_acceptance_window1_20261118.json)

## 第一步：取鎖、持鎖與釋放範圍

`_request_deadline` 以 `<run>/control/budgets/<role>-<pid>.json` 保存各程序狀態。`Deadline._state_lock` 取的是該目錄同一個 `budget.guard` 的第 0 位元組。路徑以 run 為範圍，第二個 episode 沿用第一個 episode 的 guard 和 request 身分。各角色的 JSON 是狀態快照。`budget.guard` 內的初始化字元 `0` 不記錄 PID、持鎖時間或持有者歷史。[Deadline 與狀態路徑](../scripts/retailrocket_session_knn_pipeline_v80.py#L382) · [角色狀態檔路徑](../scripts/retailrocket_session_knn_pipeline_v80.py#L716) · [Windows 鎖定包裝](../scripts/retailrocket_session_knn_checkpoint_v2.py#L162)

| 角色 | 實際接入的取鎖路徑 | 邊界 |
| --- | --- | --- |
| outer，套件程序內呼叫 `run_pipeline` | 重入檢查使用 outer `Deadline`。啟動與監督第二次 pipeline 時，同一 guard 用於啟動前、ready 等候、原生身分核對的 callback 和退出輪詢 | ready 等候與正式退出輪詢中的鎖定只有 `check()` 那一段。查後代程序、等待退出及 `sleep(0.02)` 在鎖外。本次被 timeout failure 擋在 outer 正常交付檢查與 `finalize_stopped` 前 |
| 第二次 pipeline | `_release_role` 在握手前、等 ack 期間和驗 ack 後取鎖。`_pipeline` 另建同 role／PID 狀態路徑的 guard，監督 worker、在 CP finalize 前後各檢查一次，再以同樣的 `_launch_role` 監督 publisher | 實際 traceback 落在 publisher 已 ack 後的輪詢入口 `check()`。本次失敗的呼叫未進入 `_check_locked`，也未到該次持鎖路徑的 `_unlock` |
| publisher | 同一 `_release_role` 握手檢查。業務入口把 `guard.check` 傳給 `audit_saved`，在 H7 後、逐筆反讀迴圈、H8 前取鎖。完整 audit 返回後還有一次檢查才寫 proof | H7／H8 的來源核對、讀資料、產生 proof 都在 `check` 鎖外。留存只有 H7，現有程式流不足以分辨中斷落在哪一次 `watch()` |

角色呼叫來源為 [`run_pipeline`](../scripts/retailrocket_session_knn_pipeline_v80.py#L1325)、[`_release_role` 與 `_launch_role`](../scripts/retailrocket_session_knn_pipeline_v80.py#L838)、[`_pipeline` 和 `_publisher`](../scripts/retailrocket_session_knn_pipeline_v80.py#L1120)、[`audit_saved` 的 `watch`](../scripts/retailrocket_session_knn_pipeline_v80.py#L574)。正式 runner 是外層窗口管理者，與表中的 outer 角色分開。[正式窗口監督](../scripts/run_retailrocket_session_knn_acceptance_v80.py#L407)

每次取鎖都用 `a+b` 開 guard，必要時先寫初始化字元。`cp._lock` 把檔案游標移到 0，再以 Windows `LK_NBLCK` 嘗試鎖一個位元組。`OSError` 由 CP 包成 `WriterBusy`。每次拒收後會檢查單次取鎖迴圈的 monotonic 經過是否至少 1 秒，或 request UTC 是否已截止。未觸發時呼叫 `sleep(0.005)` 再試。這是設定值，不能拿來推算實際輪詢次數。[取鎖與重試條件](../scripts/retailrocket_session_knn_pipeline_v80.py#L398)

取鎖成功後，`_check_locked` 先核 request 雜湊、讀全部已發布的 `*.json`，再取 UTC／monotonic 時鐘、計算累積已用時間。接著 `cp.atomic_json` 建內層暫存、寫入、flush、fsync 並 rename 到呼叫方的外層暫存。呼叫方再 `os.replace` 成正式 role／PID JSON。寫入後仍在鎖內做期限判定及可選的資源 callback。A12 呼叫沒有傳資源 callback。`last_utc` 因此落在持鎖區，且早於這筆寫入、rename 和釋放。[持鎖區與兩次換檔](../scripts/retailrocket_session_knn_pipeline_v80.py#L425) · [原子 JSON 寫入](../scripts/retailrocket_session_knn_checkpoint_v2.py#L46)

正常回傳或持鎖區拋 Python 例外時，`finally` 以 `LK_UNLCK` 解鎖，外層 `with` 關檔。取鎖重試結束仍失敗時，控制流不進持鎖區，檔案仍由 `with` 關閉。若程序在區塊中被終止，不能從原碼的 `finally` 反推這次有執行 Python 的解鎖路徑。`_post_delivery` 的更新後 UTC／monotonic 判定在 `guard.check()` 回傳後，已離開該鎖。[釋放與鎖外期限檢查](../scripts/retailrocket_session_knn_pipeline_v80.py#L414) · [鎖外檢查](../scripts/retailrocket_session_knn_pipeline_v80.py#L736)

恢復 worker 的角色握手亦共用 `budget.guard`，但接下來的科學工作用 `internal/cp/writer.guard` 與 CP `budget.json`。pipeline 的 `store.finalize` 也用 CP writer，完成後才啟動 publisher。publisher 讀 CP 使用 `_load()`，沒有取 CP writer 鎖。`writer_owner.json` 對應 CP writer，無法當作 `control/budgets/budget.guard` 的持有者收據。[worker 與 CP finalize](../scripts/retailrocket_session_knn_pipeline_v80.py#L1115) · [CP writer](../scripts/retailrocket_session_knn_checkpoint_v2.py#L294) · [publisher 唯讀 CP](../scripts/retailrocket_session_knn_pipeline_v80.py#L586)

以上四份 V80 原始程式與測試文字的 bytes／SHA-256 均符合 V80 工具 seal。以下階段另核對既有狀態檔、失敗收據及未發布暫存。
