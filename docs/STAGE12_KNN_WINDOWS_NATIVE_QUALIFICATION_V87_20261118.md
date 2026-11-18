# V87｜Windows 原生證據來源的合成資格規格

本輪只訂規格。V84 提出 QPC／QPF 與同一 `fd` 的 FileIdInfo，V86 已確認兩個介面對 23 個假案例的行為。V87 擬驗本機原生來源在指定合成範圍是否成立。保留原 golden、196 個子案例與 V80 歷史收據，工具、原生探測、實機量測、真實角色接入及正式驗收本輪均為 0。[V84 官方語義](STAGE12_KNN_WINDOWS_LOCK_SOURCES_V84_20261118.md) · [V86 逐案結果](../reports/mainline/v86_v85_fake_case_acceptance_20261118.json)

## 第一步　QPC／QPF 跨程序資格

以專案已封存的 Windows CPython 3.12.10 為目標，由一個監督程序直接啟動同機兩個合成子程序 A、B。每個子程序固定用一個執行緒處理本機 IPC 與取樣，所有訊息綁定同一擷取 nonce、方向、序號與預期階段。收據保存 Windows build、Python／架構及 adapter 雜湊、實際 PID／建立身分、擷取識別及開機連續證據。程序建立身分用啟動時持有的程序 handle 核對 `GetProcessTimes` 的 creation time，只用於身分比對。以兩程序同時存活、直接啟動關係及涵蓋窗口的環境證據核對同一系統及開機。工具封存須先列明電源事件來源、覆蓋起訖及可查權限，VM 還需可核對遷移狀態。已知暫停／恢復、VM 遷移或相關事件覆蓋不足時保留未知，單一 BootTime 標籤或相同 Hz 無法補缺。[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes) · [QPF 官方語義](https://learn.microsoft.com/en-us/windows/win32/api/profileapi/nf-profileapi-queryperformancefrequency)

每輪依序保存發起端送出前 `s0`、對端收到後 `s1`、對端回覆前 `s2`、發起端收到回覆後 `s3`。每個標記按照 V85 介面讀一組 QPF／QPC，保存原始整數 Hz、tick、API 成敗及可用的同次錯誤。IPC 成功與序號建立因果順序。記錄位置本身是觀測範圍，緩衝在記憶體並於該輪交換後保存。`s0`～`s3` 支持讀取標記的順序，無法定位 IPC 或鎖的內部呼叫瞬間。[Microsoft 高解析時間戳](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)

| 案例 | 預定來源與驗收 |
| --- | --- |
| Q1 來源與完整性 | A 發起 8 輪、B 發起 8 輪。每方向前 4 輪立即交換，後 4 輪在兩個接收端各於收件完成後請求固定 10 ms 等待，再取接收標記。不以實際等待時間作判定。正例資料固定為 16 輪、64 組讀值。全部 API 成功、QPF 為同一正整數，QPC 為有效原始整數且各子程序的標記按實際取樣序不倒退。程序和訊息須逐筆可核 |
| Q2 雙向因果 | 驗 `s0→s1` 與 `s2→s3`。在每個發起方向的 4 輪固定等待案例中，每條跨程序邊至少一例嚴格分離，共四項最低門檻。16 輪全數保留，無明確逆序。另檢 `s1→s2` 和發起端 `s0→s3` 的原始 tick 順序 |
| Q3 近界與拒判 | 相等、差一 tick 或拓寬後相接／重疊一律為未知。原生立即交換一律保存結果，恰好出現近界樣本沒有配額。固定相接、缺樣、域／Hz 不符與逆序的判定在工具準備階段以封存假資料核對邊界，現場不注入假原生結果，也不為湊足樣本加輪 |

兩個接收方向使用同一座標。用固定的首輪 `s0` 作唯一原點。每個端點先向兩側各加一個 V85 的順序不確定 tick，再各加一個量化 tick。用共同正 Hz 換算整數 ns，下界向下、上界向上取整。`upper(send) < lower(receive)` 才是嚴格正例。`upper(receive) < lower(send)` 是明確矛盾，重疊與相接則未知。先直接在原始資料上獨立檢核上述界線與取整，通過後才可在這個擷取範圍建立 V85 的 `verified`，再反核轉換一致。此界線針對讀值標記，本輪無法據此估 IPC 等待、syscall 邊界誤差或最壞時鐘誤差。[QPC 順序與量化](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)

時鐘階段提案上限為 30 秒，每次 IPC 等待最多 2 秒。API 失敗、頻率變更、缺樣、錯序、身分或環境矛盾、明確逆序、可用嚴格正例不足及到期均不授予資格。必須保存已取得的前綴和停止原因。通過只支持兩個合成程序在本機同一開機窗口以該 adapter 比較這些標記。V80 的期限操作數、1 秒分支與原 UTC 短路另行保留，J1／J2 尚待其他證據。[V82 持有者及期限規格](STAGE12_KNN_BUDGET_LOCK_EVIDENCE_SPEC_V82_20261118.md)

## 第二步　同一 `fd` 的 FileIdInfo 資格

用另兩個合成子程序 A、B 依原 `a+b` 模式開檔。只准在一個事前指定、Git 忽略且本機固定磁碟的 NTFS 暫存根目錄之下，新建一次性子目錄。子目錄有 3 個事前固定的 8-byte 檔，`guard.synthetic`、與它位元組完全相同的 `twin.synthetic`，以及帶不同標記的 `replacement.synthetic`。子程序各自持有 stream，先設定非零游標。觀測前後核對 `.closed`、`fileno()`、`open_id`、借用的 HANDLE 與 stream 的游標，當事程序回報開啟和關閉事件。查詢從原 stream 的 `fd` 透過 `msvcrt.get_osfhandle` 借用 HANDLE，觀測器不再按路徑開檔、不改游標或開檔旗標，也不關閉借用 HANDLE。只由 stream 擁有者關閉。此階段只驗檔案身分，不取得 byte lock。[CRT 借用規則](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/get-osfhandle?view=msvc-170)

本機資格以多項證據合判。根目錄路徑與祖先預檢需排除 reparse point，開窗前置時按唯一已封存路徑核定根目錄對應的正規磁碟區 GUID，不搜尋備援路徑。對每個借用 HANDLE 核 `GetFileType` 為 `FILE_TYPE_DISK`，`FileStandardInfo` 顯示非目錄、未待刪除且只有一個連結，`FileAttributeTagInfo` 排除 reparse 屬性。由同一 HANDLE 取得 `GetFinalPathNameByHandleW(FILE_NAME_NORMALIZED | VOLUME_NAME_GUID)`，與核定磁碟區及子目錄下的正規路徑逐段相符，僅容許預定檔名與預設資料流。`GetDriveTypeW` 查已核對的磁碟區根，須為 `DRIVE_FIXED`，`GetVolumeInformationByHandleW` 在同一 HANDLE 確認 NTFS 與磁碟區背景。路徑跳脫、遠端、磁碟區不符、來源不明或查詢失敗均不核發資格。磁碟區查詢的 DWORD 序號只作輔助欄位。[檔案類型](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfiletype) · [標準資訊](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_standard_info) · [檔案屬性](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_attribute_tag_info) · [實際路徑](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew) · [磁碟類型](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdrivetypew) · [同 handle 的磁碟區資訊](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationbyhandlew)

| 案例 | 合成安排與驗收 |
| --- | --- |
| F1 重疊開啟同一檔 | A、B 各以獨立 stream 開啟 `guard.synthetic`。收到兩個開啟確認後才一同進入查詢，兩份結果到齊才依序關閉。兩份原始 FileIdInfo 的完整序號與 ID 皆相等，重疊期間無替換，記錄可支持同一世代 |
| F2 同內容異檔 | A、B 在第二次重疊開啟中分別持有 `guard.synthetic` 與 `twin.synthetic`。來源須為同一已驗磁碟區並有完整的重疊開檔證據。兩組完整 ID 須不同，保留 `different_file`。內容、數字上相同的跨程序 fd 或 HANDLE 都不作同檔證明 |
| F3 時序中斷與同名換檔 | 兩邊關閉後由 A 重開原名一次，查得原始 ID 仍需對沒有連續證據的兩次觀測回報未知。再次確認全部 stream 關閉後，只在這個一次性目錄以預建的 `replacement.synthetic` 替換 `guard.synthetic`，由 B 重開確認標記並查詢。保存關檔、替換成功及新世代來源，禁止跨世代合併，無論 ID 是否重用。若 sharing 阻擋，保存錯誤並停，該案例為未完成，不改旗標、不補跑 |
| F4 路徑拒判 | 對固定的含 `..`、ADS 與 UNC 三種輸入字串，在開檔前回報拒絕。三個案例只查字串與路徑政策，避免建立連結或接觸遠端；不作原生 provider 負例計數 |
| F5 同次錯誤 | 在有效的合成 stream 借用 HANDLE 上做一次明確的短尺寸負例。實際配置完整 24 bytes，但對 `FileIdInfo` 傳入 1 byte。期望 `FALSE` 與同次正 WinError，實際代碼照錄，buffer 丟棄，身分回報未知，不讀 stat 或舊結構。這只驗錯誤路徑，無法證明真正 provider 不支援；已關閉或無效 fd 繼續由 V86 假案例覆蓋 |

F1–F3 正常共 6 筆完整查詢，F5 另有 1 筆短尺寸查詢。正常呼叫固定 `FileIdInfo` class `0x12`、24-byte 結構與原生指標寬度。成功才保存完整無號 64 位元序號及原序 16 bytes 檔案 ID，分別以定長 16／32 個十六進位字元記錄，拒用全零或全 `FF` 的保留 ID。未要求實機刻意產生高位非零。若 adapter 使用 `ctypes`，用 `use_last_error=True`，呼叫前清該執行緒的錯誤副本，`FALSE` 後立即取同次 `ctypes.get_last_error()`。收據保留查詢次序、各 open／generation 的證據及 `BOOL`／錯誤位置，證據不足時保持未知。餵入 V85 時，F1、F2 各用一份同時涵蓋雙方的重疊開檔證明。F1 綁同一世代，F2 綁各自世代。F3 的分段及換檔不沿用共同證明。兩個合成程序用實際 PID、建立及開檔身分區分，若需填 V85 角色欄位，僅使用合成 `worker`。[FileIdInfo API](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex) · [FILE_ID_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info) · [ctypes 錯誤碼](https://docs.python.org/3.12/library/ctypes.html#ctypes.get_last_error)

## 開窗、停止與估時

| 階段 | 預估 | 擬定上限與進關條件 |
| --- | --- | --- |
| 待確認的工具準備 | 60–90 分鐘 | 120 分鐘內完成 adapter、最小監督器、固定案例名單、假資料故障驗證及封存。超時或假驗收未過即停。工具、案例及 SHA-256 先推上 `main`，原生窗口另待確認 |
| 原生窗口前置 | 5–10 秒 | 10 秒。驗工具與 V84／V85／V86 來源雜湊、原 golden 與 196 案、窗口未用、執行環境及程序收束能力。先綁定唯一暫存根，確認有權限與可用的本機檔案資格證據 |
| QPC／QPF 合成程序 | 2–10 秒 | 30 秒，含兩個子程序起訖及收束。每次 IPC 最多 2 秒。Q1–Q3 未通過即停止，不進檔案階段 |
| FileIdInfo 合成程序 | 15–45 秒 | 70 秒，含兩個子程序起訖、6 筆正常及 1 筆短尺寸查詢、關檔及暫存檔收束。每次 IPC 最多 5 秒。F1–F5 缺項或矛盾即停止 |
| 收束和現場收據 | 3–10 秒 | 10 秒。關閉只屬於本次窗口的合成程序與檔案，保存完成項、前綴、錯誤、未執行與終止結果，反核原封存 |
| 事後反核與發布 | 10–20 分鐘 | 核對 raw 收據、同一窗口的身分、計數與結論，更新 README 並發布摘要與證據雜湊。本機詳細時間戳、路徑與程序身分留在 Git 忽略目錄 |

原生窗口預估 25–75 秒，整窗上限 120 秒，包含前置、診斷與清理。規格為最多一次、固定順序，從監督器開始前置計起。獨立的監督期限使用 Windows CPython 3.12.10 的 `time.monotonic()`，僅作停止，QPC 不參與超時控制。工具封存前要用假時鐘、假 IPC 與假子程序驗證最早截止優先、部分輸出可保存及終止只作用於本次受控程序。開原生窗口前須能確認監督器持有本次程序 handle、可收束阻塞中的子程序及完整覆蓋起訖。原生工作不得阻塞監督器。各階段及整窗預留最長 5 秒的收束寬限，優先要求子程序關閉，逾寬限僅收束本次專用 Job 或確定仍屬本次的程序 handle。未收乾淨或寫不完收據標為未完成，不越窗等待或再次開窗。這些時間是提案上限及未試跑的規劃估計。[V84 監督時鐘語義](STAGE12_KNN_WINDOWS_LOCK_SOURCES_V84_20261118.md) · [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

封存或環境不符、同次訊息缺漏、原生呼叫意外失敗、路徑／身分／世代矛盾、超時、收束或收據無法確認，均保留停止原因，禁止補跑、擴大路徑、換來源或沿用不完整證據通過。原始 golden、196 個子案例與 V80 的 147 通過／1 失敗／48 未執行已用既有收據反核。此次只提交文件，等待確認後才可準備工具。即使將來兩項能力通過，仍只適用於該本機合成窗口；實際 guard 的世代、真實角色的鎖與期限證據、J1／J2、擾動及 V80 最後拒取的持有者仍待證。[V85 封存收據](../reports/mainline/v85_windows_source_interfaces_seal_20261118.json) · [V80 歷史結果](../reports/mainline/v80_synthetic_acceptance_window1_20261118.json)
