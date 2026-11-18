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

以上四份 V80 原始程式與測試文字的 bytes／SHA-256 均符合 V80 工具 seal。

## 第二步：對齊留存時間線和未發布暫存

**能定位 pipeline 被拒取鎖的路徑，也能把 publisher 持鎖定位到停止前的一個取樣點。最後一次拒取當下的持有者仍無法確定。** 角色 ack 將 outer PID 20180 綁到第二次 pipeline 3916，再將 pipeline 3916 綁到 publisher 17936。launcher PID 11584 和 6272 分開保存。原 request 的建立時間為台北 11:07:19.478693，UTC 截止換算為台北 11:09:19.478693，原請求上限 120 秒。[角色身分、原檔描述與時間線](../reports/mainline/v81_a12_budget_lock_review_20261118.json)

下表時間均為 2026-11-18 台北時間。`last_utc` 是已取得鎖後的取樣時間，早於寫檔與釋放。停止請求時間是監督者捕捉錯誤後記錄的時間，晚於最後一次拒取。

| 已保存時間 | 角色 | 可核對的錨點 |
| --- | --- | --- |
| 11:07:30.124648 | outer | 開始第二次 pipeline 監督 |
| 11:07:41.055720 | pipeline | 已觀測恢復 worker 角色退出 `0` |
| 11:07:44.856537 | pipeline | 開始監督 publisher |
| 11:07:52.385368 | pipeline | 最後一筆已發布狀態的鎖內時間樣本 |
| 11:07:53.390338 | publisher | 最後一筆已發布狀態的鎖內時間樣本 |
| 11:07:53.422602 | publisher | 雙層暫存中的未發布鎖內時間樣本 |
| 11:07:53.428066 | pipeline | 為 publisher 記錄 `BudgetExceeded` 停止請求 |
| 11:07:53.583339 | outer | 後續一筆已發布狀態的鎖內時間樣本 |
| 11:07:53.596161 | outer | 觀測第二次 pipeline 角色退出 `1`，交付因子程序期限錯誤遭否決 |

### 暫存檔能證明哪一段持鎖

在相同 run 的 `control/budgets` 找到 `publisher-17936.json.<uuid>.tmp.<uuid>.tmp`。原樣 153 bytes，SHA-256 為 `1f992bd82ff1ccf37aff1bf6b3bace707ab88038f2c6b287b9d824faa42db044`。檔名符合 `_check_locked` 呼叫 `cp.atomic_json` 時產生的兩層暫存，內容與 CP 的 canonical JSON 格式及該 A12 request SHA-256 相符。其 `last_utc=1794971273.4226022`，晚於正式 `publisher-17936.json` 的取樣。對應外層暫存未留存，正式檔仍是較早一筆。依既有檔案與凍結原碼，publisher 已在這次取樣時取得鎖，也留下內層暫存的完整 bytes。`*.json` 帳本讀取不採用這筆未發布狀態。

用存下的兩筆 UTC 相減，該樣本比 publisher 停止請求早約 5.463 毫秒。停止請求並未記錄最後一次 `LK_NBLCK` 的時刻，而且暫存檔沒有解鎖時間。這個差值不能用來判最後一次拒取時誰持有，不能用來估計 publisher 單次持鎖多久，也無法分辨內層寫入在 flush、fsync、關檔或換檔的哪一段中止。H7 已保存、H8 未保存，無法定位到 `audit_saved` 的哪一次 `watch()`。outer 之後有一筆成功發布，只表明它後來仍能進入鎖內。

本輪先反核 V80 已列的 71 個檔案均相符，再對 `budget.guard` 與這份雙層暫存新增查核描述。這兩檔未列入原 71 個描述。`budget.guard` 的內容只有字元 `0`，沒有所有權帳本。補充暫存的完整路徑、雜湊與舊快照差異列在[反查收據](../reports/mainline/v81_a12_budget_lock_review_20261118.json)。

### 期限錯誤能解釋到哪裡

歷史 traceback 的第二次 `_launch_role` 在輪詢 publisher 時執行 `check()`，由 `msvcrt.locking` 回報 `PermissionError`（errno 13），進而被轉成 `WriterBusy` 與 `BudgetExceeded: Cumulative budget state lock unavailable`。`WriterBusy` 的訊息是 CP 對 `OSError` 的通用包裝，沒有指出鎖持有者，亦未保存逐次 `WinError`。上層因 pipeline failure 的 `timeout_stop=true` 將它傳為子程序 `TimeoutError`，正式窗口因此判為 `incomplete_timeout`。publisher 的角色退出碼仍未知，`15` 是它的 launcher 退出碼。

`_state_lock` 的兩個停止條件為該次取鎖迴圈從起點經過至少 1 秒，或 request UTC 已到期。停止請求時 UTC 截止仍餘約 86.051 秒，整窗也無 900 秒 deadline veto。保存順序最支持**約 1 秒的取鎖重試上限**。pipeline 最後一筆 `last_utc` 到停止請求相差約 1.043 秒，其中包含不同語意的取樣與錯誤傳遞，不能當成實測等待。收據未保存選中的分支、實際嘗試次數或該次 monotonic 起訖，也沒有每次獲鎖、釋鎖的事件。因此現有資料仍不足以歸因為同一程序連續持鎖、特定 I/O 呼叫延滯或其他個別爭鎖情形。

V80 正式判定維持原樣。若後續要確認精確持有者及等待原因，先訂每次取鎖開始、成功、失敗和釋放的記錄欄位，區分鎖內寫檔各階段與兩種停止條件，再另定驗證範圍。
