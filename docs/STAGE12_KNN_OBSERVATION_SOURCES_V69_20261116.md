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

下方固定來源版本／邊界／缺失契約、受影響的合成案例需求及新能力驗收條件。若限定維持目前 Windows 且要求原 thread CPU 語義，本輪尚無已驗證更精細的新來源；可以停在規格，不為取得結果而換量、放寬尺度或重跑。

| 本輪小步驟 | 狀態 |
| --- | --- |
| 官方語義、六類來源與限制 | 17份來源與10個本機來源綁定已核對，獨立審閱通過；先推送 `8d340d1` |
| 後續驗收條件與來源契約 | 下列准入、保存及 A／B／C／D 條件已固定並完成獨立靜態審閱；不實作、不執行 |
| 新增量測／clock metadata／測試／C／D／原 48 筆 | 全部 0 |

## 來源准入與仍未作出的選擇

本規格只讓 **LINUX_THREAD 進入「同研究量、待確認環境與接入」的文件候選狀態**。預定優先維持 Python `time.thread_time_ns` 與 `time.perf_counter_ns` 的同邊界介面；若後續改用明確 clock ID 的 API，必須另列方法版本，不能在同一 attempt 中自動切換。這不是安裝、遷移、工具實作或 B 的執行授權。

必須先決定可用且可接受的具體平台：原生 Linux、容器、WSL 或 VM 不能只用「Linux」一詞互換，也不在本輪探測它們是否存在。跨平台候選可保留計量語義與 1 ms 目標，**但改變實驗環境**；即使新窗口通過，也不能解釋原 Windows V47／V48 的等待原因。若研究需求不接受另定環境，本輪沒有可直接取代既有 Windows thread CPU 的已驗證新來源，應停在規格。

| 准入項目 | 實作或任何新實測前必須具備 | 不符時處置 |
| --- | --- | --- |
| 測量量與範圍 | 同一被量測 thread 的 user＋system／kernel CPU duration；worker／thread 身分及委派工作範圍清楚 | process CPU、cycles、wall 或排程區間不得改標；拒絕來源 |
| runtime 與 implementation | 指定 Python／build、OS／kernel、libc、架構與虛擬化邊界；官方語義與對應實作分支可追溯 | 來源或語義未確認就不進 B；不以目前文件的 tag 冒充未來 binary |
| 固定 reader | API、clock ID（若有）、實際 reader／adapter／套件版本與來源 hash 已封存；禁止 fallback | 缺 API／讀取失敗不能改用 process、cycles 或另個 clock 繼續 |
| 同邊界與數值 | thread guard → wall_before → CPU → wall_after → thread guard；中間不插配置／I/O；原始整數及單位可重算 | 型別、倒退、溢位、跨 thread、單位混用或來源矛盾拒絕；缺值不補零 |
| 資源與失敗責任 | 若直接持有原生 handle，權限、生命週期與清理已定；保留原始失敗碼／例外及第一個錯誤 | 不把 BOOL 失敗當 CPU=0；不擴權或更換來源來救結果 |
| 方法與預算 | 受影響 A 案例、來源／結果格式、單次新 B 的上限、停止／保存與估時已另版封存 | 未具備完整可審閱方案或未獲新量測確認前，執行數維持0 |

`thread_time_ns` 本身不保證新平台的 implementation；直接改 API 也不自動得到更細推進。V65 純判定器對 API 名稱有固定檢查，V67 的 reader 物件與 origin 亦被鎖定。**不得改標新來源來通過既有 admission**；新接入使用新版本的來源契約／admission，數值公式可沿用但須由合成資料核對。原 V62–V68 檔案保持原樣。

## 原始保存契約

以下是日後接入必須產出的欄位需求，現在的實際能力／環境值仍未知；本輪沒有建立新的 raw 樣本。

| 層次 | 必須保存的內容 |
| --- | --- |
| 方法 manifest | candidate ID、測量量／歸屬、API／clock ID、adapter／判定器／配置／案例 hash、官方來源與版本定位；真實與人工 origin 分開 |
| 環境與權限 | 綁定的 runtime／OS／kernel／libc／架構／虛擬化資訊，process／thread 生命週期，所需及取得的權限；原始身分留私人證據 |
| clock metadata | wall／CPU 的 implementation、available、monotonic、adjustable、declared resolution；明列 metadata 取得方法與原值，不把它當實際能力 |
| 邊界原值 | 三個原始整數、thread guard、boundary／sequence／parent、完成狀態；如原生單位需換算，保留原數與精確換算規則，不經 float 轉回 ns |
| 完整性／停止 | 三輪及十次 sleep 固定槽位、cap／deadline／停止位置、partial capture、主次錯誤及未執行 null；不丟慢值、不以零代缺失 |
| 截止／落盤 | control wall 與校準樣本分開；記錄開始、純判定前後、必要 raw 寫入前後及 bytes／hash；provisional raw 不能單獨宣稱通過 |
| 公開摘要 | 真實最終狀態、完整／缺失分母、全部統計、來源／私人證據的相對 descriptor、限制；不公開原始刻度或機器身分 |

保留原始有號 wall−CPU，零 CPU 增量合法但不等於沒運算，負殘差不裁成零；inner／outer 仍只是讀取時序敏感度，不是真實等待誤差界。子段沿用共享 mark 與父子關係，不能重複加總或扣估計探針成本。新平台的語義驗證也須標明未計入目標 thread 的委派工作，不能一律叫等待。

## A｜先驗接入與判定，尚未實作或執行

原 A1–16 類別繼續適用，既有通過只能作對應未變更部分的證據。後續先列「可沿用／受影響須重驗」映射；不能把 V67 的123項假驗收搬成新來源已通過。受影響案例至少包含下列七群，具名案例數須等工具實作封存後才能填寫：

| 類別 | 新來源所需案例與判定 |
| --- | --- |
| A-S1｜來源准入 | 真／假 origin、API／實際 reader／implementation／版本／hash 一致；錯平台、錯 API、process／cycles fallback、假 metadata 或改標都拒絕 |
| A-S2｜計帳歸屬 | 同 thread 前後 guard、跨 thread／生命週期錯誤拒絕；委派工作明示範圍，不能混入其他 thread 計數 |
| A-S3｜數值與錯誤 | 原始大整數、精確單位換算、合法零 CPU；bool／float 偽整數、倒退、溢位、缺值、原生失敗碼與主次例外 |
| A-S4｜邊界與布局 | 固定三讀且中間無 I/O；原 wall 回傳、共享 mark、父子守恆、有號 residual、partial prefix 與未知區段 |
| A-S5｜截止與保存 | cap／target 同點、30秒前／同點／後、慢 metadata／判定／落盤、取消及停止後不新增樣本；null 與原錯誤保留 |
| A-S6｜入口行為 | O 無新增探針；完整 payload／工作量／帳本、SQL／lazy fetch／watch／fault、decoder 隔離及 call-local namespace 與原基線一致；用合成資料 |
| A-S7｜判定與反讀 | 新 admission 仍保留原公式／分位數／失敗規則，完整與缺失人工 fixtures 可重算；純資料 pass 與真實讀錶證明分開；一次性狀態及公開／私人收據一致 |

新方法／案例先更新 README、封存並推送，再執行假驗收；結果發布後才可考慮另行確認的新 B。本輪沒有新增測試通過數。

## B｜同研究量的能力門檻不放寬

下表沿用 [V62 機器規格](../reports/stage12/retailrocket_session_knn_v62_wall_cpu_specification_20261116.json)及 V66 的完成／提前停止規則，只適用已准入的同 thread CPU 時長候選，不套到 cycles 或 ETW scheduled time。

| 項目 | 固定要求 |
| --- | --- |
| 研究目標 | 1,000,000 ns（1 ms）；仍非已證明的誤差界或因果解析度 |
| metadata與單調性 | 兩鐘皆available、monotonic且不可調整；保存宣告值與取得方式，實際讀值不得倒退；metadata合格不代表能力已通過 |
| dense | 同一worker／thread，三輪各首末wall差≥500,000,000 ns；每輪最多1,000,000組含首點，完成輪至少10個正CPU增量 |
| CPU 推進量 | q=max(宣告CPU resolution換算ns向上取整，三輪各自正CPU增量p95)≤100,000 ns；完整輪前不能依running p95正式判不足 |
| 三讀間隔 | 完整固定集合bracket p99≤50,000 ns、max≤100,000 ns；任一max超標可立即停，不能用小p99抵銷 |
| sleep | 固定十次sleep(0.05)，各實際wall≥40,000,000 ns；十次CPU／wall比的p90≤0.10，不以要求sleep時間代替實際值 |
| 統計 | nearest-rank分位數、標準median；原值／零值／所有缺失保留，不挑慢值、不跨失敗樣本補成完成輪 |
| 整關期限 | 30秒含metadata、收集、判定與必要raw序列化／flush／fsync／hash；最後控制點後才判是否按時，後續公開／獨立反讀不能延長成功窗口 |
| attempt | 未來新的獨立B關卡計畫先預估、固定來源及最多一次正式B，確認後才可開始；失敗／取消／launch failure都保留且不補跑。V67額度不能重用；日後D的56次前後檢查屬另行規劃及授權，不含於此單次額度 |

不可用／不完整／逾時維持未確認；結構或歸屬矛盾拒絕。宣告CPU resolution已過粗，或完整輪且正增量數足夠時p95過粗，可判不足；不能將partial q抬成完整B。所有既有停止條件仍有效，不因候選名稱、不同平台或窗口而降低門檻。

本輪尚未指定執行環境或實作，因此**不提供假造的新實測能力或執行時間估計**。未來準備好具體方案後再估時；V67提前停止的1.9424457秒不能拿來保證完整新B的耗時。

## C／D｜只固定後續條件，本輪不排程

| 關卡 | 仍須保留的條件 |
| --- | --- |
| C，僅在適用A與新B通過後另行安排 | 空stamp與完整記錄路徑各4,097次，只作診斷；兩人工工作量各O／D暖機及八對固定OD／DO，外層含保存。每工作量120秒，abs(D−O)/O中位≤2%、max≤5%；不扣探針成本、不挑配對 |
| D，僅在C通過後另行安排 | 同環境、同decoder比較O／D，V39與V46分開；六block共12正式對＋4暖機＝28入口，每入口前後同B共56次。instrumentation_entry、原完整入口及48筆query wall合計三個指標，各相對擾動中位≤2%、max≤5%；32／33×正重疊／投票各絕對擾動中位≤0.1ms、max≤0.5ms；窗口上限1,800秒 |

V62 的具體人工工作量、順序、完整48筆身分、輸出／來源／帳本與缺失規則原樣繼承，機器規格附完整原值。若將來用新平台，O／D及兩decoder都須在該同一環境驗收，不能跨平台配對，或把新平台結果回填舊Windows窗口。量測工具的能力與擾動驗收不等於V46採用；採用仍要另行無新增診斷的完整冷入口證據。

## ETW 候選的進入條件與停止線

ETW_SCHED 尚未准入上述 CPU timer B。若仍要發展事件方案，須另版完整規格，至少固定：

- 同thread／process生命週期、CPU migration、query marker起訖與trace的完整覆蓋；未知與未閉合區間不補零。
- 時間基準與精確換算、marker兩端對齊品質、相同timestamp／亂序／重複ready的決定規則；不能靠「Precise」字樣認定1ms可辨識。
- 適用loss計數、provider／session配置與範圍完整性；缺少、非零或未知必要loss證據不宣稱完整，零loss也須另驗覆蓋。
- DPC／ISR及委派工作的歸屬、重疊與缺事件處理；輸出量與原CPU timer差異必須維持可見。
- 人工事件重建案例，包括漏切入／切出、重複ready、跨CPU、thread重用、錯clock、trace截斷／遺失及歧義；另驗語義、能力與擾動。

這些是必要條件清單，**不是已完成的ETW能力驗收協定**。對齊／不確定度判定、事件專用的覆蓋／缺失規則，以及trace／marker擾動驗收流程與門檻對應仍待固定；完整性覆蓋證據及實際開銷資料也都缺少，不能直接用CPU增量q套出通過。若未來仍聲稱回答原CPU時長問題，還需證明相同歸屬／計量量；否則只可回答另立的排程事件問題。1ms目標與局部擾動要求保留為不可放寬的上位預算，不代表既有CPU C／D已完整定義ETW驗收。

## 本輪結論與下一步

已固定官方語義、候選分類、來源保存契約、七群受影響A案例需求，以及同研究量路徑沿用的B／C／D門檻。獨立靜態審閱通過；18次本機descriptor核對（12個唯一檔案）、7個V62規格區塊、原16類A、11項V66停止規則及26個文件連結均一致；這些是文件／資料核對，不是新工具測試或能力驗收。**文件層候選不等於執行就緒或能力通過。**下一步先明定是否接受另定環境，以及具體平台／runtime與接入範圍；可接受才另行準備新adapter及合成案例的封存計畫，不直接啟動B。

所有量測／環境探測／clock metadata讀取／測試／trace／C／D／原48筆仍為0，無新量測授權。V67仍未確認、V46暫不採用，32／33的歷史運算與等待仍無法拆分。[機器可讀可行性規格](../reports/stage12/retailrocket_session_knn_v69_observation_feasibility_20261116.json)。
