# Stage 12｜V69 保留 1 ms 目標的觀測來源可行性規格

依 [V68](STAGE12_KNN_CLOCK_LIMITS_V68_20261116.md)先訂候選來源規格。**保留原 1 ms 辨識目標，以及同一執行緒在相同程式邊界的 user＋kernel CPU 時長問題**；不把 cycles、程序合計或排程區間改名成相同量。本輪只有官方／維護者一手文件核對與規格審閱，不實作 adapter、不探測本機 API／環境、不讀新 clock metadata、不跑測試或量測。C／D、原固定 48 筆、真實 model 及訓練均為 0；V46 暫不採用。

V67 的 B 仍為能力未確認，一次額度已用完；本文件不改寫 V62–V68、不重開 V67。**沒有候選已通過實機能力或開銷驗收。**1 ms 是研究目標，不是官方精度保證，也不是統計顯著門檻。

## 官方語義與文件層篩選

以下「文件明載」是對來源的短摘要；「本案判定」是依原問題作出的工程推論。完整 URL、章節定位與本輪查閱日期存於[來源登錄](../reports/stage12/retailrocket_session_knn_v69_observation_sources_20261116.json)。網頁沒有複製成封存全文，不宣稱遠端內容的 bytes 已封存。

| ID／來源 | 文件明載的量與範圍 | 單位、限制與錯誤 | 本案判定（不是實測） |
| --- | --- | --- | --- |
| WALL：`perf_counter_ns`／QPC | elapsed wall；包含 sleep。QPC 是時間區間用 timestamp | Python 回傳整數 ns；原生 QPC 是 counts，QPF 提供該 counter 的頻率。這些不是 thread CPU 累計值 | 保留作 wall／邊界基準，不能代替 CPU；高解析 timestamp 不保證兩個 API 同時讀取或 bracket 合格。[Python](https://docs.python.org/3.12/library/time.html#time.perf_counter_ns)、[QPC](https://learn.microsoft.com/en-us/windows/win32/api/profileapi/nf-profileapi-queryperformancecounter)、[QPF](https://learn.microsoft.com/en-us/windows/win32/api/profileapi/nf-profileapi-queryperformancefrequency) |
| WIN_THREAD：`thread_time_ns`／`GetThreadTimes` | 當前／指定 thread 的 user＋kernel 執行時長 | FILETIME 的 CPU duration 是 100 ns 單位；creation／exit 是另一種時間點。原生 handle 須 query 權限；原生 BOOL 回傳 0 表示失敗（不是 CPU duration 為零），應保存錯誤而非補值 | 語義相符，屬 V67 既有基準。文件未保證本案 0.1 ms 推進／bracket 門檻；直接呼叫同 API 不能被當成已改善精度。[Python](https://docs.python.org/3.12/library/time.html#time.thread_time_ns)、[GetThreadTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getthreadtimes) |
| LINUX_THREAD：Linux `thread_time_ns`／`clock_gettime_ns(CLOCK_THREAD_CPUTIME_ID)` | 當前 thread 的 CPU 時間；Python 的 thread API 定義為 user＋system 且不計 sleep；Linux clock ID 只屬目前 thread | 整數 ns 表示；可用性、build 分支、kernel／libc／runtime 版本及實際推進須另驗；clock ID 錯誤須保留失敗 | **同研究量的條件候選**。需另定並確認可用平台，不能在既有 Windows 環境直接替換；文件不構成較準或 1 ms 已達標的證據。[Python clock ID](https://docs.python.org/3.12/library/time.html#time.CLOCK_THREAD_CPUTIME_ID)、[Linux man-pages](https://man7.org/linux/man-pages/man2/clock_gettime.2.html) |
| WIN_CYCLES：`QueryThreadCycleTime` | 指定 thread 的 user＋kernel CPU cycles | 64-bit cycles；官方明示不要轉成 elapsed time，CPU timer 實作／變頻行為可能不同；handle 需 query 權限，失敗須保存 | **拒絕作原 thread CPU ns 的替代**；不可用名目 CPU 頻率或 QPF 頻率換秒後冒充原量。[官方文件](https://learn.microsoft.com/en-us/windows/win32/api/realtimeapiset/nf-realtimeapiset-querythreadcycletime) |
| PROCESS：`process_time_ns`／`GetProcessTimes` | 整個 process 的 user＋kernel CPU；原生介面加總各 thread，可能超過 elapsed wall | ns 表示或 100 ns 單位，不改變 process 歸屬；handle 權限及失敗須保留 | **拒絕替代目標 thread**；讀值較平滑也不能修正歸屬不符。[Python](https://docs.python.org/3.12/library/time.html#time.process_time_ns)、[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes) |
| ETW_SCHED：ETW CSwitch／ReadyThread＋WPA Precise | 由切入／切出／ready 事件推得 thread 的執行、ready、wait 狀態區間 | CPU Usage 以 switch-out−switch-in 計；DPC／ISR 歸屬、遺失、邊界覆蓋與時間基準另有要求 | **另一套事件契約的條件候選**，不直接替代 `thread_cpu_ns`。Precise 名稱不等於本機 1 ms 驗收通過。[CPU Analysis](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/cpu-analysis)、[cswitch 分析](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/cswitch) |

### 版本與相同 API 的實作差異

只從 V67 已存 outcome 讀到當時 Python 為 **3.12.10**，沒有重新查本機版本。本輪查閱的 Python 3.12 文件頁目前標示 3.12.16，因此另用官方 **CPython v3.12.10** 原始碼定位：Windows thread-time 分支呼叫 `GetThreadTimes`、將 kernel／user 合計轉 ns；符合條件的 clock-gettime 分支使用 `CLOCK_THREAD_CPUTIME_ID`。這是原始碼分支核對，不能證明任何未檢查 runtime 的 build 或現機能力。[CPython v3.12.10 `timemodule.c`](https://raw.githubusercontent.com/python/cpython/v3.12.10/Modules/timemodule.c)

因此，原生 `GetThreadTimes` 包裝不列為新的 CPU 記帳來源；它的包裝成本或失敗行為若改變，仍是待驗的工具變更。Linux 的相同 Python API 可作語義候選，但必須明列真正 implementation、平台／build 與來源。不能把所有 Unix、容器或虛擬化環境視為同一個候選，也不能從同名常數推斷實測能力。

### ETW 的額外契約

官方事件欄位可支持排程時間線，但不直接給既有 query 邊界的 CPU duration。候選輸出應另名為 `scheduled_running_ns`、`ready_ns` 等，未閉合／無法歸屬者保留 unknown；不得靜默填入 `thread_cpu_ns` 或把剩餘值稱為 I/O／GIL 等待。這是本案的欄位及判讀限制。

| 文件事實 | 本案後續必須先固定的條件 |
| --- | --- |
| CSwitch 包含新舊 thread／狀態／wait reason，事件量大；ReadyThread 的特定情況可能額外出現 ready 事件。[CSwitch](https://learn.microsoft.com/en-us/windows/win32/etw/cswitch)、[ReadyThread](https://learn.microsoft.com/en-us/windows/win32/etw/readythread) | thread／process 生命週期、CPU migration、重複 ready、同 timestamp、trace 截斷及 query marker 對應；不能假設一對一事件或用單一 wait reason 指定應用層原因 |
| cswitch 分析提供排除 DPC／ISR 的選項，且需要相應 tracing 才有效。[官方說明](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/cswitch) | 事前固定中斷時間的歸屬及重疊算法；缺事件時不能假裝已扣除，也不將全部 scheduled interval 當應用程式 CPU |
| ETW QPC 模式的 timestamp 對應 QPC，需 trace header 的 PerfFreq；consumer 預設可能轉 system time，raw flag 才保留原格式。[WNODE_HEADER](https://learn.microsoft.com/en-us/windows/win32/etw/wnode-header)、[EVENT_TRACE_LOGFILEW](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/ns-evntrace-event_trace_logfilew) | raw counts、clock type、頻率、轉換規則與 marker 兩端對齊證據都須保留；不能只因同名 QPC 就假設應用邊界與事件已無誤差對齊 |
| `EVENT_TRACE_PROPERTIES` 有事件／buffer loss 統計；`EVENT_TRACE_LOGFILEW.EventsLost` 則標為未使用。[Properties](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/ns-evntrace-event_trace_properties)、[Logfile](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/ns-evntrace-event_trace_logfilew) | 固定 session 模式與適用的 loss 欄位；未知或非零不宣稱完整。loss=0 也不足證明必要 provider 已啟用、目標起訖已覆蓋；未使用欄位的零不能當證據 |
| 官方列出 event 可能亂序的情況；控制 session 及 kernel logger 有各自權限限制。[Callback](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/nc-evntrace-pevent_record_callback)、[StartTraceW](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/nf-evntrace-starttracew) | 保存原始順序與重建規則，不以 callback 到達順序直接代替事件順序；先固定 session／provider／權限計畫。本輪沒有探測權限、啟動 trace 或調整系統 |

## 文件層結論與仍待確認的項目

在本輪列出的六類來源中，LINUX_THREAD 可保留原 CPU 時長歸屬，列為**需要另定平台與驗收的語義候選**；WIN_THREAD 為既有基準，沒有新增能力證據；ETW_SCHED 可另作排程事件設計，但不能靠改欄名回答原 CPU 問題。cycles、process CPU 與 wall timestamp 都不直接替代目標 thread CPU。這是有界的文件篩選，不是所有 API 的窮盡搜尋，也不是推薦採用 Linux 或 ETW 的實機結論。

下一步仍須固定來源版本／邊界／缺失契約、受影響的合成案例及新能力驗收條件。若限定維持目前 Windows 且要求原 thread CPU 語義，本輪尚無已驗證更精細的新來源；可以停在規格，不為取得結果而換量、放寬尺度或重跑。

| 本輪小步驟 | 狀態 |
| --- | --- |
| 官方語義、六類來源與限制 | 文件核對完成；先同步 README 並提交推送 |
| 後續驗收條件與來源契約 | 接著固定；不實作、不執行 |
| 新增量測／clock metadata／測試／C／D／原 48 筆 | 全部 0 |
