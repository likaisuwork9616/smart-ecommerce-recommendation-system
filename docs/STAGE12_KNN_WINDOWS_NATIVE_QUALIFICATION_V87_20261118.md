# V87｜Windows 原生證據來源的合成資格規格

本輪只訂規格。V84 提出 QPC／QPF 與同一 `fd` 的 FileIdInfo，V86 已確認兩個介面對 23 個假案例的行為。V87 擬驗本機原生來源在指定合成範圍是否成立。保留原 golden、196 個子案例與 V80 歷史收據，工具、原生探測、實機量測、真實角色接入及正式驗收本輪均為 0。[V84 官方語義](STAGE12_KNN_WINDOWS_LOCK_SOURCES_V84_20261118.md) · [V86 逐案結果](../reports/mainline/v86_v85_fake_case_acceptance_20261118.json)

## 第一步　QPC／QPF 跨程序資格

以專案已封存的 Windows CPython 3.12.10 為目標，由一個監督程序直接啟動同機兩個合成子程序 A、B。每個子程序固定用一個執行緒處理本機 IPC 與取樣，所有訊息綁定同一擷取 nonce、方向、序號與預期階段。收據保存 Windows build、Python／架構及 adapter 雜湊、實際 PID／建立身分、擷取識別及開機連續證據。程序建立身分用啟動時持有的程序 handle 核對 `GetProcessTimes` 的 creation time，只用於身分比對。以兩程序同時存活、直接啟動關係及涵蓋窗口的環境證據核對同一系統、開機及無暫停／恢復或 VM 遷移。無足夠證據即保留未知，單一 BootTime 標籤或相同 Hz 無法補缺。[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes) · [QPF 官方語義](https://learn.microsoft.com/en-us/windows/win32/api/profileapi/nf-profileapi-queryperformancefrequency)

每輪依序保存發起端送出前 `s0`、對端收到後 `s1`、對端回覆前 `s2`、發起端收到回覆後 `s3`。每個標記按照 V85 介面讀一組 QPF／QPC，保存原始整數 Hz、tick、API 成敗及可用的同次錯誤。IPC 成功與序號建立因果順序。記錄位置本身是觀測範圍，緩衝在記憶體並於該輪交換後保存。`s0`～`s3` 支持讀取標記的順序，無法定位 IPC 或鎖的內部呼叫瞬間。[Microsoft 高解析時間戳](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)

| 案例 | 預定來源與驗收 |
| --- | --- |
| Q1 來源與完整性 | A 發起 8 輪、B 發起 8 輪。每方向前 4 輪立即交換，後 4 輪在兩個接收端各於收件完成後請求固定 10 ms 等待，再取接收標記。不以實際等待時間作判定。正例資料固定為 16 輪、64 組讀值。全部 API 成功、QPF 為同一正整數，QPC 為有效原始整數且各子程序的標記按實際取樣序不倒退。程序和訊息須逐筆可核 |
| Q2 雙向因果 | 驗 `s0→s1` 與 `s2→s3`。在每個發起方向的 4 輪固定等待案例中，每條跨程序邊至少一例嚴格分離，共四項最低門檻。16 輪全數保留，無明確逆序。另檢 `s1→s2` 和發起端 `s0→s3` 的原始 tick 順序 |
| Q3 近界與拒判 | 相等、差一 tick 或拓寬後相接／重疊一律為未知。原生立即交換一律保存結果，恰好出現近界樣本沒有配額。固定相接、缺樣、域／Hz 不符與逆序的判定在工具準備階段以封存假資料核對邊界，現場不注入假原生結果，也不為湊足樣本加輪 |

兩個接收方向使用同一座標。用固定的首輪 `s0` 作唯一原點。每個端點先向兩側各加一個 V85 的順序不確定 tick，再各加一個量化 tick。用共同正 Hz 換算整數 ns，下界向下、上界向上取整。`upper(send) < lower(receive)` 才是嚴格正例。`upper(receive) < lower(send)` 是明確矛盾，重疊與相接則未知。先直接在原始資料上獨立檢核上述界線與取整，通過後才可在這個擷取範圍建立 V85 的 `verified`，再反核轉換一致。此界線針對讀值標記，本輪無法據此估 IPC 等待、syscall 邊界誤差或最壞時鐘誤差。[QPC 順序與量化](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)

時鐘階段提案上限為 30 秒，每次 IPC 等待最多 2 秒。API 失敗、頻率變更、缺樣、錯序、身分或環境矛盾、明確逆序、可用嚴格正例不足及到期均不授予資格。必須保存已取得的前綴和停止原因。通過只支持兩個合成程序在本機同一開機窗口以該 adapter 比較這些標記。V80 的期限操作數、1 秒分支與原 UTC 短路另行保留，J1／J2 尚待其他證據。[V82 持有者及期限規格](STAGE12_KNN_BUDGET_LOCK_EVIDENCE_SPEC_V82_20261118.md)
