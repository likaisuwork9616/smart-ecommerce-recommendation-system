# V84｜Windows 跨程序時鐘與鎖檔實體來源

V83 的 18 個假案例已驗判定規則。V84 核對的是 Windows 與封存 CPython **3.12.10** 的官方語義，目標是先選 V82 所需的跨程序鎖事件來源，列出能比較的範圍與後續驗收條件。本輪只讀官方文件、版本原碼與既有收據。未實作、呼叫原生 API、啟動角色、量測或重跑驗收。[V83 假案例結果](../reports/mainline/v83_fake_lock_evidence_acceptance_20261118.json)

## 第一步：跨程序單調時鐘

**首選原生 `QueryPerformanceCounter`（QPC）整數 tick 及 `QueryPerformanceFrequency`（QPF）頻率作事件時鐘。** Windows 的可比性限在同一合格的系統實例和開機期間。V80 原本用來判期限的 `time.monotonic()`、UTC 及短路順序沿用，QPC 只供將來的事件排序和呼叫括區。

| 來源 | 封存版本的語義與本案取捨 |
| --- | --- |
| Windows CPython 3.12.10 `time.monotonic()`／`monotonic_ns()` | 兩者由 `py_get_monotonic_clock` 讀 `GetTickCount64()`。`_ns` 是開機後整數毫秒轉成奈秒，整數表示不提升取樣解析度。Microsoft 說典型為 10–16 毫秒，典型值不作硬誤差界線。可保留原 V80 門檻值，細粒度跨程序括區另用候選來源 |
| Windows CPython 3.12.10 `perf_counter()`／`perf_counter_ns()` | 版本原碼用 QPF 與 QPC，將絕對 tick 計數按整數乘除換成奈秒，沒有扣除各程序的私有起點。Python 文件記載 Windows 3.10 起為系統共用。若後續要走此 Python 路線，只用整數 ns 並於同一封存版本另驗頻率與轉換界線，不與原生 tick 混組 |
| 原生 QPC／QPF | QPC 是同系統／VM 的計數器刻度，可用於標記事件，QPF 在該次開機初始化後固定並一致供各 CPU 使用。原始 tick＋Hz 可確切回算，跨程序不同執行緒樣本在相差一個 tick 內仍有排序歧義。這是靜態選擇，尚無本機 API 或跨程序相容結果 |

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

## 第二步：鎖檔實體與接合驗收

**首選 `GetFileInformationByHandleEx(FileIdInfo)`，以原取鎖 stream 的開檔描述符借用實際 HANDLE。** 在同一電腦上比較兩個開啟 handle 時，Windows 文件使用完整 `VolumeSerialNumber` 與 `FileId` 的組合。候選收據保留 unsigned 64 位元磁碟區序號及原序 16 bytes 的 opaque file ID。可用定長 16／32 個十六進位字元儲存，禁止截斷、浮點轉換或當 GUID 重排。[GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex) · [FILE_ID_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info) · [FILE_ID_128](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-file_id_128)

| 候選來源 | 語義與限制 |
| --- | --- |
| `msvcrt.get_osfhandle(fd)` | CPython 與 CRT 定義為取得現有 `fd` 所屬的 OS handle。從原 `a+b` stream 的同一 `fileno()` 借用，查詢時要仍開啟。原 stream 負責關檔，借用端不 `CloseHandle` 或自行 `_close`。新按路徑開檔不能替代實際該次取鎖的 fd。空值、無效 fd／handle 或前後開檔識別不一致保留未知。查詢先設計在鎖外，實作接入與擾動另驗。 [CPython msvcrt](https://docs.python.org/3.12/library/msvcrt.html#msvcrt.get_osfhandle) · [CRT 所有權](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/get-osfhandle?view=msvc-170) |
| `GetFileInformationByHandleEx` 的 `FileIdInfo` | class 為 `0x12`。成功後才採 `FILE_ID_INFO` buffer。失敗保留同一次 API 的 `GetLastError` 與位置，不把它當 `_locking` 的錯誤。列舉頁標明 `FileIdInfo` 自 Windows 8／Server 2012 起，結構頁的 client 要求現有標示不同，API 表也指出類別受底層驅動影響。因此只採為候選，不能只看版本表就視本機支援。 [API 與驅動限制](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex) · [FileIdInfo 列舉](https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ne-minwinbase-file_info_by_handle_class) · [結構版本表](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info) |
| 檔案系統與磁碟區背景 | 可另從同一 handle 核對 filesystem／volume 輔助資訊。`GetVolumeInformationByHandleW` 的 serial 參數是 DWORD，不能代替 `FILE_ID_INFO` 的 64 位元欄位。首輪限定受控本機一般檔和原預設資料流。SMB／遠端／未驗 provider、不同主機或掛載變更保留不合格或未知。掛載型態及實際 filesystem 本輪未探測。 [同 handle 查磁碟區資訊](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationbyhandlew) |
| 舊結構、`os.fstat` 與 handle 數字 | `BY_HANDLE_FILE_INFORMATION` 的 64 位元識別在 ReFS 無唯一性保證。CPython 3.12.10 `_Py_fstat_noraise` 可在 `FileIdInfo` 失敗後仍回傳 stat。`st_dev`／`st_ino` 無法證明原生查詢成功。分開開啟同一磁碟檔本來可以有不同 handle 或 Windows 開檔物件。路徑、mtime、內容雜湊、`fd` 或 `HANDLE` 數值均不作實體比較，舊結構及 stat 也不自動替代。 [舊結構限制](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-by_handle_file_information) · [CPython 退回舊格式](https://github.com/python/cpython/blob/v3.12.10/Python/fileutils.c) · [File Handles](https://learn.microsoft.com/en-us/windows/win32/fileio/file-handles) |

### 世代、路徑與位元組鎖的分界

檔案 ID 由檔案系統提供，可能重用，也可能隨檔案系統及生命週期事件而改變。MS-FSCC 對其協定欄位定義全零及全 `FF` 為缺失識別情形。本案保守拒用這兩類值，不推論每一 Win32 provider 的故障回傳都依此編碼。[Microsoft 128 位元檔案 ID 協定](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/98860416-1caf-4c80-a9ab-8d61e1ccf5a5) · [檔案 ID 生命週期限制](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-by_handle_file_information)

同機完整 ID 相等支持同時開啟的 handle 指向同一檔。使用時仍須將每個 `open_id`、實際角色身分、run／request／擷取與受控檔案世代綁定。首輪用唯一的合成 guard，在已知的一段重疊開檔期間確認同一世代。關檔後重開若缺乏未曾刪除、換檔或重新掛載的佐證，不能跨空檔沿用世代。一旦確知替換、重新建立或掛載改變，另立世代並拒絕與舊事件合併，無論新舊 ID 恰好是否相同。單填一個 `generation_id` 不能代替生命週期證據。將來如有需要補足不重疊的範圍，連續 handle 或其它維持世代的方式須另行確認其效果，不先加入 V80 角色。相同實體的別名也不放寬原入口的 canonical 路徑政策。[V80 安全路徑](../scripts/retailrocket_session_knn_bundle_v80.py) · [V82 角色和鎖身分](STAGE12_KNN_BUDGET_LOCK_EVIDENCE_SPEC_V82_20261118.md)

`FileIdInfo` 證據只識別檔案。V80 仍要從同次 fd 的 `seek(0)` 與 `LK_NBLCK`／`LK_UNLCK` 呼叫確認 `[0,1)` 鎖範圍與結果。CRT 的 `_locking` 從現有 file pointer 開始，`LK_NBLCK` 被拒取時回錯，CRT 的一秒重試規則屬另一模式。V80 的一秒來自自己的取鎖迴圈。File ID、句柄、errno 13 或後來的停止紀錄都不回傳鎖持有者。可證明持鎖者與是否為排他衝突仍採 V82 的兩個判定。[CRT `_locking`](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking?view=msvc-170) · [原 CP 位元組鎖](../scripts/retailrocket_session_knn_checkpoint_v2.py#L162) · [V80 原取鎖迴圈](../scripts/retailrocket_session_knn_pipeline_v80.py#L399)

### 待驗收條件與下一段邊界

| 關卡 | 須通過的條件 |
| --- | --- |
| F1 假介面與完整身分 | 驗 pointer 寬度與結構、64 位元高位及 16 bytes 原序、同一 fd 借用的開關生命週期、不代開／關閉、不改檔案游標／原 access／sharing。包含無效 handle、本次 API 失敗、缺錯誤碼、保留值、不同 provider 或不同磁碟區，以及 fd／handle 值重用。失敗走未知，不退回舊來源 |
| F2 實體正負例 | 另經核准後，兩個人工程序依原 `a+b` 方式重疊開啟同一受控本機普通檔，完整 ID 與同世代可核。收據保存如何驗證實際 handle 所指的本機一般檔、filesystem／provider 與磁碟區，未能驗證時保持未知。結果只適用於該測試位置，不能自動外推到角色實際 guard 的路徑或掛載。另開同內容異檔須區分。對同名換檔、世代中斷、路徑別名及不支援類別予以拒判。若 sharing 阻止預定的替換，原樣記錄，先驗對應的假負例，不能放寬原開檔旗標或算替換已通過 |
| J1 合併證據 | C1–C3 與 F1–F2 各自成立後，還需通過 V82 的角色證據、同一 run／request、相同檔案世代與位元組、完整取得／拒取／釋放區間和其他使用者覆蓋。只在唯一保證持鎖區嚴格包含擴大的拒取區間時可確認持有者。缺時鐘資格、來源錯置或缺尾保持未知，衝突另憑原錯誤驗證 |
| J2 期限與擾動 | 按 V82 保留 V80 原先的期限操作數、短路、`seek`、鎖模式、競爭及停止語義。取得哪一處樣本及診斷保存的成本須另訂門檻，診斷 I/O 維持在鎖外，時鐘或實體資格通過也不能替代擾動驗收。不以 V81 的 UTC 差值或舊 1 ms 校準作門檻 |

**下一輪的待確認範圍**是只準備並封存 QPC／QPF 與鎖檔身分的獨立介面及假案例。以假 tick、假 QPF 和假 file API 驗型別、高位保留、誤差區間、角色／來源錯置及缺值拒絕。之後若要核原生資格，另列人工程序、合成暫存檔、停止條件及預算再確認。V80 真正角色接入、正式 196 案窗口及效能量測各有自己的後續界線。V83 原假結果、原 golden、196 子案例和 V80 歷史判定保留，最後拒取時的持有者仍未知。本輪新增工具、原生呼叫與執行均為 0。[File ID 官方來源與待驗條件](../reports/mainline/v84_windows_file_identity_qualification_20261118.json)

時鐘及檔案來源各有獨立靜態審閱。F2 補明本機 provider 的證明及測試位置限制。本輪共 20 份官方文件與版本原碼定位，兩份收據的本機來源、連結和原封存均已反核。
