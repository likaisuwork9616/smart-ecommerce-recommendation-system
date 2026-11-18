# V82｜A12 預算狀態鎖的證據與驗收規格

V81 已定位 A12 第二次 pipeline 在監督 publisher 時的取鎖失敗。publisher 的暫存檔提供停止前的持鎖取樣，缺少最後一次拒取的呼叫邊界、同時段的解鎖證據及停止分支。本規格針對這三個缺口。V80 的結果仍為 147 個子案例通過、1 失敗、48 未執行。本輪只寫規格，沒有實作、量測或重跑。[V81 反查與時間線](STAGE12_KNN_BUDGET_LOCK_REVIEW_V81_20261118.md)

## 第一步：範圍、身分與每筆事件

範圍是單一 A12 run 的 `control/budgets/budget.guard` 第 0 位元組，長度 1。擷取從第二次 outer 入口第一次預算檢查之前開始，涵蓋第二次 pipeline 和 publisher 的正常、失敗及清理路徑。第二次 episode ID 尚未分配的 outer 事件先綁同一 request 和本次入口 ID，分配後以另筆關聯事件綁 episode，已存事件原樣保留。初始邊界須有第一個 episode 已觀測程序停態及無已知未關閉持鎖區的證據。邊界仍有不明身分或持鎖區時，保留缺口。

| 角色 | 須覆蓋的預算檢查位置 |
| --- | --- |
| outer | 第二次入口前置檢查、啟動 pipeline、等 ready、核身分、ack 後輪詢、交付前後，以及有到達才記的外部 finalize 路徑。outer 是套件內的 `run_pipeline` 呼叫者，正式窗口 runner 另列 |
| pipeline | 自己的 ready／ack、監督 worker、CP finalize 前後的控制層檢查、監督 publisher 的啟動、握手、輪詢及交付檢查 |
| publisher | 自己的 ready／ack、H7 後、逐筆反讀檢查、H8 前，以及 proof 寫入前。逐筆檢查帶 ordinal，區分同名的 `guard.check` |
| 其他共用者 | worker 握手也取同一把狀態鎖，須列入同鎖證據。若仍有其它 guard 使用者，須證明已涵蓋或在被判定時段不會參與，否則持有者判定保留未知。CP `writer.guard` 及 CP `budget.json` 是另一套帳本 |

定位參照為 V80 [`_state_lock`](../scripts/retailrocket_session_knn_pipeline_v80.py#L399)、[`_request_deadline`](../scripts/retailrocket_session_knn_pipeline_v80.py#L716)、[`_release_role` 與 `_launch_role`](../scripts/retailrocket_session_knn_pipeline_v80.py#L838)、[`_publisher` 與 `_pipeline`](../scripts/retailrocket_session_knn_pipeline_v80.py#L1120)及 [`audit_saved`](../scripts/retailrocket_session_knn_pipeline_v80.py#L574)。

### 每筆事件的共同欄位

| 欄位群 | 必須保存的值 |
| --- | --- |
| 證據來源 | 事件 schema 版本、擷取 ID、正式窗口 ID、工具／人工來源封存 SHA-256、canonical request SHA-256、run ID、本次入口 ID、episode ID 或尚未分配標記 |
| 呼叫者 | 實際角色、PID、creation time、boot 身分，對應 launch／ready／ack 或 outer 監督收據描述。被監督的角色及原 launcher 身分各有獨立欄位。未完成綁定的握手前事件留原身分，由後續證據對應 |
| 鎖身分 | run 相對路徑、檔案實體身分及有效代次、offset `0`、length `1`、排他／非阻塞方式、程序內的開檔 ID。以已開 handle 的實體身分或同等經驗證方式綁定。路徑字串、讀到 `0` 或程序內 handle 數值只能輔助 |
| 次序 | 單一事件生產者的遞增序號、guard instance ID、`check_id`、呼叫位置及受監督角色。每次進取鎖迴圈用新 `check_id`，每個實際 lock 呼叫用同一迴圈內的 `attempt_index`。成功取得後置一個 `hold_id` 供寫入、解鎖與關檔關聯 |
| 時鐘與品質 | 事件取樣值、時鐘種類／作用域、整數刻度或原值與單位、boot 與時計域 ID、跨程序資格與上／下界誤差來源。呼叫前後是獨立取樣。UTC 或檔案 mtime 可作時間線參照，原守門用到的 UTC／monotonic 操作數另存 |
| 結果 | `begin`／`end` 中對應的操作、成功／失敗／未觀測、原始例外型別、可取得的 errno／WinError、例外轉換與下游收據描述。`null` 搭配缺值原因區分未呼叫、未回傳、來源未提供及紀錄遺失 |

跨程序時計與檔案實體身分目前均屬未驗能力。僅能在後續獲准並通過相容性驗證的共同時計域內推論跨角色鎖區間。若只能在 CP `_lock` 包裝外觀測，保留整個包裝的較寬括區及其層級。只有能綁到原生呼叫時，才標為原生呼叫的括區。

### 取鎖、重試、持鎖寫入及釋放欄位

| 事件 | 每次必留的欄位 |
| --- | --- |
| `guard_open`／`guard_init` | 開始、回傳與結果，實際檔案實體、開檔 ID，是否要寫初始化字元及初始化結果。這一段在 V80 取鎖迴圈計時之前 |
| `lock_loop_begin` | `check_id`、原本使用的 monotonic 起點、原請求 UTC 截止、1 秒重試門檻、原有 0.005 秒休眠設定，重試時沿用同一起點 |
| `lock_attempt_begin`／`lock_attempt_end` | 實際呼叫前後的時鐘括區，迴圈內 attempt 序號，結果。在成功回傳時建立 `hold_id`，拒取時保存 `_lock` 原錯誤、底層可取得的錯誤碼與 `WriterBusy` 包裝鏈。就緒等候、`seek`、開檔錯誤另有位置 |
| `retry_decision`／`retry_sleep` | 同一 `check_id`／attempt，門檻比較的原 monotonic／UTC 操作數、兩條件各自 `evaluated` 與結果、實際選中分支，及是否請求原 0.005 秒休眠。休眠請求、醒來或下一次嘗試的已觀測結果分開，未觀測時保留未知 |
| `state_read`／`state_sample` | `hold_id`，已發布狀態檔的讀取開始與結果、各檔數量與 request 相符判定。保留原 `now`、`mono`、原請求建立／截止與預算、三個已用時間候選及結果、打算發布的 role／PID 狀態。檔案識別用名稱或既有描述，診斷雜湊在鎖外產生 |
| `state_write` | 同一 `hold_id` 與寫入 ID，逐步記內層暫存建檔、write、flush、fsync、暫存關檔、內層→外層 replace、外層→正式狀態 replace 的開始／結束／結果。關聯各自路徑、承諾的 bytes 與能證實的完成階段。缺結束事件標未觀測，完整的暫存 bytes 仍不足以證明 fsync 或換檔成功 |
| `guard_result` | 取得鎖後的 request 身分、UTC rollback、原請求 UTC／累積預算判定，以及既有 resource callback 是否存在和結果。保留失敗發生在發布前、後或證據未知，連到寫入 ID |
| `unlock_begin`／`unlock_end`、`guard_close` | `hold_id` 與開檔 ID，`LK_UNLCK` 和 guard 關檔各自的呼叫前後、成功／失敗／未知，保留原錯誤碼。取鎖最終未成功的檢查只有 guard close，沒有自己的 `hold_id` 或 unlock |
| `stop_received`／`role_exit_observed`、`delivery_result` | 發出／接到停止及實際獨立角色退出各自的證據與時間。程序強退或觀測遺失時記錄最後已知 `hold_id`、完整度與中斷原因。鎖後交付守門、veto 與外層例外連結原 `check_id`／attempt，避免只留外層 `TimeoutError` |

開始與結束事件須可區分 syscall 本身和其外層包裝。既有 `last_utc` 採樣早於寫檔。已發布 JSON、未發布暫存、釋放記錄與最終交付各有獨立狀態。不以 UTC 間隔、被觀測退出或看到下一筆快照代填持鎖時間或解鎖成功。

### 保存界線與擾動

將診斷與原 `control/budgets/*.json`、CP 帳本分開，避免被原程式讀作累積狀態。每角色使用容量事前明列的事件緩衝。鎖內只追加必要時鐘樣本及小型事件欄位。診斷序列化、雜湊、檔案／IPC 寫入和刷新在鎖外完成。原有鎖內 write／flush／fsync／replace 按原路徑與順序執行。擷取補充時鐘不得被拿去取代實際期限判定操作數，也不為補欄位多求一次原本短路的條件。

正常關閉要有每角色事件總數、首尾序號、遺失／截斷與缺尾標記，封存原始事件流的 bytes／SHA-256 與由其產生的摘要。全部嘗試逐筆保存。容量耗盡、程序終止或輸出失敗時，保留可用前綴和缺口，受影響的區間降為不完整。若需要強退尾端的鎖外獨立保存方式，後續須先證明該方式涵蓋範圍及擾動，才可使用其證據。停止或清理路徑不因保存診斷而得到額外執行時間。具體持有者和期限分支的驗收另列於第二步。
