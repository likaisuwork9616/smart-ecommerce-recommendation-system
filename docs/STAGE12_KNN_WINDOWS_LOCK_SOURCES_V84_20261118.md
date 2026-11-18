# V84｜Windows 跨程序時鐘與鎖檔實體來源

V83 的 18 個假案例已驗判定規則。V84 核對的是 Windows 與封存 CPython **3.12.10** 的官方語義，目標是先選 V82 所需的跨程序鎖事件來源，列出能比較的範圍與後續驗收條件。本輪只讀官方文件、版本原碼與既有收據。未實作、呼叫原生 API、啟動角色、量測或重跑驗收。[V83 假案例結果](../reports/mainline/v83_fake_lock_evidence_acceptance_20261118.json)

## 第一步：跨程序單調時鐘

**首選原生 `QueryPerformanceCounter`（QPC）整數 tick 及 `QueryPerformanceFrequency`（QPF）頻率作事件時鐘。** Windows 的可比性限在同一合格的系統實例和開機期間。V80 原本用來判期限的 `time.monotonic()`、UTC 及短路順序沿用，QPC 只供將來的事件排序和呼叫括區。

| 來源 | 封存版本的語義與本案取捨 |
| --- | --- |
| Windows CPython 3.12.10 `time.monotonic()`／`monotonic_ns()` | 兩者由 `py_get_monotonic_clock` 讀 `GetTickCount64()`。`_ns` 是開機後整數毫秒轉成奈秒，整數表示不提升取樣解析度。Microsoft 說典型為 10–16 毫秒，典型值不作硬誤差界線。可保留原 V80 門檻值，細粒度跨程序括區另用候選來源 |
| Windows CPython 3.12.10 `perf_counter()`／`perf_counter_ns()` | 版本原碼用 QPF 與 QPC，將絕對 tick 計數按整數乘除換成奈秒，沒有扣除各程序的私有起點。Python 文件記載 Windows 3.10 起為系統共用。若後續要走此 Python 路線，只用整數 ns 並於同一封存版本另驗頻率與轉換界線，不與原生 tick 混組 |
| 原生 QPC／QPF | QPC 是同系統／VM 的事件計數，QPF 在該次開機初始化後固定並一致供各 CPU 使用。原始 tick＋Hz 可確切回算，跨程序不同執行緒樣本在相差一個 tick 內仍有排序歧義。這是靜態選擇，尚無本機 API 或跨程序相容結果 |

上述版本判斷依 `get_monotonic`／`get_perf_counter` 及各 `_ns` 包裝、`py_get_monotonic_clock`、`py_get_win_perf_counter`。Python 3.13 記載 `perf_counter` 和 `monotonic` 採同一時鐘的變更，需按版本辨識。[CPython 3.12.10 時鐘包裝](https://github.com/python/cpython/blob/v3.12.10/Modules/timemodule.c) · [CPython 3.12.10 時鐘實作](https://github.com/python/cpython/blob/v3.12.10/Python/pytime.c) · [CPython 3.12.10 time 文件](https://github.com/python/cpython/blob/v3.12.10/Doc/library/time.rst) · [Python 3.13 變更](https://docs.python.org/3.13/library/time.html#time.perf_counter) · [GetTickCount64](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-gettickcount64) · [QPC](https://learn.microsoft.com/en-us/windows/win32/api/profileapi/nf-profileapi-queryperformancecounter) · [QPF](https://learn.microsoft.com/en-us/windows/win32/api/profileapi/nf-profileapi-queryperformancefrequency)

### 時鐘的可比限制與保守轉換

- 事件收據綁本機 Windows 系統實例、boot 窗口、OS 與 runtime 身分、同一 QPC API／adapter 版本、QPF、擷取 ID 及實際程序身分。個別程序的原始讀值保留。頻率相同只能支持必要條件，無法單憑頻率或相同數字證同一 epoch。既有 CP 私有 BootTime 格式仍只作 V79 定義的相容守門，不能當公開、穩定的跨機器證書。[V79 boot 身分界線](STAGE12_KNN_ROLE_EXIT_FEASIBILITY_V79_20261117.md) · [Microsoft 高解析時間戳](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)
- QPC 事件不能與 `GetTickCount64` 值、`time.time()`／檔案 mtime 或另一機器／VM 的讀值直接拼在一起。QPC 不和外部 UTC 同步。即使 Windows 的 QPC 可反映睡眠經過，也無法由時間跳距拆出 CPU 工作、阻塞或換頁。首輪資格驗證限定無已知重啟、暫停／恢復或 VM 遷移的單一區間。若歷史環境無法核對，保留不可比。[Microsoft 高解析時間戳](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)
- 跨執行緒的一 tick 順序歧義須保留。候選規格對每一事件端點至少向兩側保留一個原生 tick，作保守的歧義處理，並再納入可驗證的量化／轉換及取樣邊界誤差。保留原 tick 和 QPF。若介接 V83 的整數 ns 區間，以同一正頻率、同一座標原點做精確有理數運算，下界向下、上界向上取整。不得逐程序扣各自第一筆或四捨五入成單點。±1 tick 並非任意環境中完整的出入 syscall 誤差上界。[QPC 排序與低階特性](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps#general-faq-about-qpc-and-tsc)
- V82 的拒取區間取實際呼叫前後的外括區，持鎖區間取成功回傳後與可能釋放前的內界。排程、API 包裝或記錄時點間隔會放寬括區，不能從 tick 解析度回推系統呼叫精確瞬間。若只能觀測 `_lock` 包裝，照較寬括區判。邊界相等、誤差區重疊或總邊界不可支撐時保留未知。[V82 持有者規則](STAGE12_KNN_BUDGET_LOCK_EVIDENCE_SPEC_V82_20261118.md)

### 待驗收條件

| 關卡 | 後續須留下的證據 |
| --- | --- |
| C1 來源與版本 | 以另行核准範圍封存 OS／CPython 版本、實際時鐘介面、資料型別、同一系統及開機範圍、原生 API 結果和各程序 QPF。各程序 QPF 須是精確正整數 Hz 且一致。原取得鎖計時仍保留 V80 的原始 monotonic／UTC 操作數，直接驗短路未多讀 UTC |
| C2 雙向因果對照 | 以預先定數的兩個人工程序記發送前→接收後→回覆前→收到回覆後，雙向保存完整原始 tick、訊息序號與程序身分。各方向須有可嚴格分隔的正例。近界樣本若落入誤差區只能報未知，無法解釋的逆序、頻率變更、缺樣或跨域一律拒絕資格。有限對照只驗該環境和接入，不能當全球同步或最壞誤差證明 |
| C3 嚴格區間 | 假 tick／頻率先驗 tick 歧義、取整、邊界相等、不同來源與域、必要時延伸到假 UTC 回退。確認同一時鐘的拓寬拒取區間全內含時才可能確認持有者。未通過現場共同域或誤差／覆蓋守門，V82 結果保持未知 |

本階段尚無新的時鐘取樣。V81 的 5.463 毫秒源自既有 UTC 樣本，V67 的歷史校準有自己的用途。兩者均不作本案跨程序時間域或誤差上界。[時鐘官方來源與條件](../reports/mainline/v84_windows_monotonic_sources_20261118.json)
