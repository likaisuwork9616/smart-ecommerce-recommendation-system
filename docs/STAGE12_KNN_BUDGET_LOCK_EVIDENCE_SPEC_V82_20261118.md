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
| 時鐘與品質 | 事件取樣值、時鐘種類／作用域、整數刻度或原值與單位、boot 與時鐘域 ID、跨程序資格與上／下界誤差來源。呼叫前後是獨立取樣。UTC 或檔案 mtime 可作時間線參照，原守門用到的 UTC／monotonic 操作數另存 |
| 結果 | `begin`／`end` 中對應的操作、成功／失敗／未觀測、原始例外型別、可取得的 errno／WinError、例外轉換與下游收據描述。`null` 搭配缺值原因區分未呼叫、未回傳、來源未提供及紀錄遺失 |

跨程序時鐘與檔案實體身分目前均屬未驗能力。僅能在後續獲准並通過相容性驗證的共同時鐘域內推論跨角色鎖區間。若只能在 CP `_lock` 包裝外觀測，保留整個包裝的較寬括區及其層級。只有能綁到原生呼叫時，才標為原生呼叫的括區。

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

開始與結束事件須可區分 syscall 本身和其外層包裝。errno／WinError 只採同一次呼叫的直接錯誤來源。若原介面未提供，保留缺值原因，不用後續 API 的錯誤碼回填。既有 `last_utc` 採樣早於寫檔。已發布 JSON、未發布暫存、釋放記錄與最終交付各有獨立狀態。不以 UTC 間隔、被觀測退出或看到下一筆快照代填持鎖時間或解鎖成功。

### 保存界線與擾動

將診斷與原 `control/budgets/*.json`、CP 帳本分開，避免被原程式讀作累積狀態。每角色使用容量事前明列的事件緩衝。鎖內只追加必要時鐘樣本及小型事件欄位。診斷序列化、雜湊、檔案／IPC 寫入和刷新在鎖外完成。原有鎖內 write／flush／fsync／replace 按原路徑與順序執行。擷取補充時鐘不得被拿去取代實際期限判定操作數，也不為補欄位多求一次原本短路的條件。

正常關閉要有每角色事件總數、首尾序號、遺失／截斷與缺尾標記，封存原始事件流的 bytes／SHA-256 與由其產生的摘要。全部嘗試逐筆保存。容量耗盡、程序終止或輸出失敗時，保留可用前綴和缺口，受影響的區間降為不完整。若需要強退尾端的鎖外獨立保存方式，後續須先證明該方式涵蓋範圍及擾動，才可使用其證據。停止或清理路徑不因保存診斷而得到額外執行時間。具體持有者和期限分支的驗收另列於第二步。

## 第二步：判定規則與驗收

### 持有者與拒取原因分開判

1. **對齊同一次嘗試。** 由 pipeline 的 `check_id`／`attempt_index` 指向實際拒取呼叫。核對 request、lock 實體和代次、排他位元組區間、各參與者實際身分、擷取完整度與共同單調時鐘域。clock 無法跨程序比對、只剩不同 UTC 樣本、檔案換代或封存不完整時，不能確認該次持有者。
2. **擴大拒取區間。** 拒取的實際時刻只能落在呼叫開始與失敗回傳之間。左界用開始樣本扣其誤差，右界用失敗回傳樣本加其誤差。`stop_request` 不作呼叫時間界線。若取樣在整個 `_lock` 包裝外，照保存的較寬區間判定。
3. **縮小保證持鎖區間。** 左界用成功取得回傳後的樣本加其誤差。右界用第一個可能釋放動作的開始樣本扣其誤差。缺少可信釋放邊界時，只能收在更早最後一筆可證明仍持鎖的樣本下界，並且要有從取得到該樣本連續持鎖的證據。`unlock` 失敗、關檔、停止請求及角色退出各有獨立紀錄。任何缺失都不能自動變成成功釋放。
4. **要求唯一且嚴格包含。** 只有擴大的拒取區間兩端都嚴格在同一個已保證持鎖區間內，且該區間可綁唯一角色與 `hold_id`，才輸出 `confirmed_holder_during_attempt`。局部重疊、相等邊界、保證區間空掉、缺欄或存在多個可能角色時輸出 `unknown`，可列候選與缺口。兩個排他持鎖的保證區間互相重疊時標 `inconsistent`，不選一個當答案。每一個重試分開判，整輪可以發生換手。
5. **另查錯誤來源。** 持有者判定回答該呼叫期間誰持有。`lock_conflict_confirmed` 還要有對應層級、可驗證的鎖衝突證據。V80 將 `OSError` 包裝成 `WriterBusy`，單獨的 `WriterBusy`、errno 13 或附帶的程序身分不能證特定拒取原因。非鎖衝突的錯誤依原始呼叫位置分類，碼缺失或語義未驗時保留 `conflict_unknown`。

因此，V81 的 publisher 暫存能補一個持鎖樣本。V80 未留下失敗呼叫括區、時鐘誤差或連續持鎖區間，無法以這份規格回填最後一次拒取的持有者，也不能把 5.463 毫秒當持鎖或等待長度。

### 停止條件保留 V80 的求值順序

`loop_start_mono` 是開檔、初始化後與第一個 lock 呼叫前的原始 monotonic 起點。重試不另起算。1 秒差值涵蓋失敗呼叫、重試處理、休眠與排程的經過，與持鎖時長分開。保存實際運算元和原精度，表格顯示的四捨五入值不參與判定。[原重試流程](../scripts/retailrocket_session_knn_pipeline_v80.py#L398)

| V80 當下控制流 | 保存的分支與實際操作數 |
| --- | --- |
| 捕捉 `WriterBusy`，原 `decision_mono - loop_start_mono >= 1.0` | `lock_retry_monotonic_limit`。保存原 monotonic 值、差值和包含等號的比較結果。UTC 未求值，`utc_evaluated=false`，UTC 取樣與比較結果為 `null`。即使後續樣本顯示請求已到期，也不能補填當下的 UTC 比較 |
| 捕捉 `WriterBusy`，上項為假，原 `clock.utc() >= request_deadline_utc` | `lock_retry_request_utc_deadline`。保存原 UTC 樣本、deadline、已求值與比較結果，包含剛好等於截止 |
| 捕捉 `WriterBusy`，兩項已求值且都為假 | `retry`。保存兩次比較及原 `0.005` 秒休眠請求，下一 attempt 沿用相同 `loop_start_mono`。實際是否醒來及何時再次嘗試由事件證據判定 |
| 取鎖成功 | 未進 `WriterBusy` 的兩條件判定。成功後再走 `_check_locked`，保留原操作順序，即使從起點經過已達 1 秒也不能補判一次拒取上限 |

兩條件的「未求值」、「已判假」和「沒有保存到」是三種狀態。保留源操作數與原分支，記錄器不為補值額外呼叫 UTC，不將未求值的分支標為同時觸發。`guard_open`、初始化、`seek` 或未被 `_lock` 包裝的例外有各自位置和結果，不湊成一次 `WriterBusy` 重試。

其餘期限各自保存。`_check_locked` 用鎖內原 `now` 與 `elapsed`，按原順序在寫入後比較 UTC 截止與累積預算。分開記實際選中的 UTC 或累積預算判定，保留從原 request 起算的時間、guard 的 UTC／monotonic 基準差、已保存高水位及最大值。`_post_delivery` 在解鎖後用 guard 的 `last_sample` 與新的樣本判定。保留時鐘不合法／回退、原 request、累積預算及有效 monotonic 限制的實際比較。有效限制來自正式窗口、繼承的角色上限和本次工作子程序上限的最小值，保存能追到的來源及並列值。既有 120 秒工作子程序、900 秒整窗及資源拒收各自保留來源。`_state_lock` 本身沒有增加子程序或整窗比較。[鎖內判定](../scripts/retailrocket_session_knn_pipeline_v80.py#L425) · [限額與鎖後判定](../scripts/retailrocket_session_knn_pipeline_v80.py#L721)

輸出保留原始失敗位置、底層錯誤、分支、`check_id`／attempt、子角色收據、交付 veto 及正式結果的關聯。父層再轉成 `TimeoutError` 時，仍能反查是哪一個子角色、哪一次鎖取得或交付條件觸發。沒有足夠欄位只能標出對應的未知原因。[失敗與 veto 路徑](../scripts/retailrocket_session_knn_pipeline_v80.py#L947) · [角色錯誤收據](../scripts/retailrocket_session_knn_pipeline_v80.py#L1433)

### 待驗收情境

| 門檻 | 未來驗收案例與預期判定 |
| --- | --- |
| E1 完整寫入與順序 | 正常、拒取後成功兩路逐筆對照。每一 attempt 都有唯一開始／結果，成功對應一個 hold。保留讀取、取樣、write、flush、fsync、關檔和兩次 replace，最後解鎖及關 guard。檢查各角色和 call site ID，診斷檔不被預算帳本採用 |
| E2 失敗與中斷 | 分別模擬開檔、seek、lock、write、flush、fsync、close、兩次 replace、unlock 失敗。確認例外與釋放順序仍照原控制流。強退、容量溢位、缺尾、重複序號或雜湊不符可辨識，完整內層暫存無法補成功事件 |
| E3 擾動與保留 | 用相同假時鐘與假鎖輸入，比較原程式呼叫次數、排序、例外及實際期限操作數和分支。實機觀測擾動另訂接受門檻。診斷鎖內沒有新檔案／IPC I/O、序列化、fsync 或額外鎖，鎖外保存仍受原預算。原 A09、A12 守門及既有案例 ID 全部保留 |
| O1 確認與邊界 | 同鎖、同域且擴大的拒取區間嚴格內含可確認持有者。相等、只重疊、跨釋放或取樣誤差使保證區間消失回報未知。拒取原因另用原始分類確認 |
| O2 換手與錯置 | 同一重試迴圈中由兩個角色先後持有，逐次判定。異 boot／時鐘域、鎖實體更換、launcher 代角色、worker 握手未涵蓋、互斥區間矛盾等均拒絕過度歸因 |
| O3 短缺證據 | 強退只有鎖內錨點、unlock 失敗或只有關檔和角色出口時，只保留可證為鎖內的取樣點，釋放與其後的持有區保持未知。非衝突錯誤和不明 errno 保持原結果 |
| T1 單次重試截止 | monotonic 正好 1 秒時，假 UTC 即使預設已逾期或讀取就報錯也應完全不求值。未滿 1 秒且 UTC 未到則重試，起點不重設 |
| T2 原請求截止 | monotonic 未滿 1 秒且 UTC 正好等於截止時，保存 UTC 截止分支。成功取得鎖時不執行專屬 `WriterBusy` 的短路判定 |
| T3 鎖內與鎖後 | 分別覆蓋獲鎖後原 UTC／累積預算到期，仍保留原寫入與釋放順序。成功釋放後若交付跨截止，區分原請求、工作子程序與整窗來源，證據連到原始階段，晚到退出碼 `0` 仍不能交付 |

規格驗收分三關。第一關是本輪靜態核對欄位、原碼和預期判定。第二關須另獲授權準備假時鐘／假鎖案例，先驗兩種停止條件、持鎖區間與儲存失敗。第三關須另定觀測窗口，驗共同時鐘、檔案實體綁定、保存完整度與觀測擾動，再用受限合成流程判定實際證據。若未達可比條件，跨角色持有者保持未知。假案例通過只證判定與接入契約，既有 196 案的通過仍須依各案原判定，包括 A12 的 `9／1`、64 筆原前綴、完整 129 筆與原 draws、發布及停態封存。V80 的歷史結果和原 golden 由原封存保留。

本輪只完成靜態規格，兩份獨立審閱涵蓋持有者、時鐘和停止分支。未準備可執行工具或案例。欄位概要、判定和待驗情境見[規格收據](../reports/mainline/v82_a12_budget_lock_evidence_spec_20261118.json)。
