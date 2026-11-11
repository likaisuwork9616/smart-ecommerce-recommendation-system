# Stage 12 V41 原 C1-S1 與 V39 直接比較

| 項目 | 封存內容 |
| --- | --- |
| 資料 | 原固定 48 筆帳本 SHA 與 15 個 binding 已核對，保留 V40 的 2,445 個來源與 183 個方法描述符 |
| 兩臂 | S 為原 C1-S1，T 為 V39。共用來源、SQL、計時與獨立核對規則，各自載入輸入並持有獨立 context |
| 順序 | 單一 worker 先跑 S cold、T cold，再以 TS／ST 交替跑六對，每臂一 cold、六 hits，共 14 份新帳本 |
| 計時 | 原 C1-S1 保留原 canonical，僅在兩次原 late 呼叫加被動計時。V39 沿用已驗收的 reference 建置與兩次完整 late 計時。兩臂的七次完整入口均含 cold |
| 對照邊界 | 每次入口計時前對稱清除評分 memoization。兩次 cold 共用主機快取環境，順序固定且各只有一次。本輪只診斷成本 |
| 完整驗收 | 先跑人工整合，再啟動唯一真實窗口。worker 正常退出後由獨立程序驗兩臂的快照與 672 筆完整帳本，所有程序停止後封存 |

規格封存時只核對既有帳本。原資料屬已檢視的 validation 工程樣本，保留測試仍鎖定。

```powershell
.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_compare_v41 --audit
```

[比較規格](../reports/stage12/retailrocket_session_knn_v41_compare_specification_20261111.json) · [封存收據](../reports/stage12/retailrocket_session_knn_v41_compare_seal_20261111.json)

## 新入口人工驗收

| 項目 | 實際結果 |
| --- | --- |
| 測試 | 9／9 項通過，對應 6 項封存要求，無失敗、錯誤或跳過。測試與證據彙整 91.446 秒 |
| 兩臂隔離 | 每臂一 cold、六 hits、15 次完整快照。保留原 C1-S1 的 canonical bytes 與檢查時點，核對 V39 的兩個 typed roots |
| 科學與來源 | 正式 loader 讀取人工 48 筆，14 份帳本、672 筆完整核對。獨立程序開啟 14 份帳本，人工 closure 每次 229 個描述符，方法 188 個 |
| 拒絕與停態 | 原 late 時間重疊、typed policy 混用、停態日誌追加與重複啟動皆被拒絕。9 個受追蹤程序全數退出，唯讀重核通過 |

人工驗收階段的真實比較執行 0 次。驗收收據封存後已用 `--measure` 執行唯一真實窗口。以下指令重核入口驗收。

```powershell
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_compare_v41 --audit
```

[入口驗收收據](../reports/stage12/retailrocket_session_knn_v41_compare_acceptance_20261111.json) · [驗收封存](../reports/stage12/retailrocket_session_knn_v41_compare_acceptance_seal_20261111.json)

## 原固定 48 筆真實結果

原 late canonical 共 **0.367 秒**，V39 的 reference 建置加兩次 late 檢查共 **3.062 秒**，實測增加 **2.695 秒**。建置 reference 用了 **2.510 秒**。即使只看原 late 位置，V39 的兩次 typed 檢查合計 **0.552 秒**，比原兩次 canonical 多 **0.185 秒**。

| 冷啟動分項（秒） | 原 C1-S1 | V39 |
| --- | ---: | ---: |
| reference 建置 | 無此步驟 | 2.509826 |
| late config | 0.008737 | 0.002496 |
| late model | 0.358614 | 0.549880 |
| 上述工作合計 | 0.367350 | 3.062201 |
| `cache.cold_build`，含上述分項 | 5.871 | 9.141 |
| 完整冷啟動入口 | 15.039 | 18.657 |

完整冷啟動入口差 **+3.618 秒**。兩臂各冷建一次，固定先跑原 C1-S1，後跑 V39，共用主機快取與負載環境。因此完整入口差仍受順序和當時負載影響。分項時間與其父層重疊。

| 重用配對 | 順序 | 原 C1-S1（秒） | V39（秒） | V39 − 原 C1-S1（秒） |
| --- | --- | ---: | ---: | ---: |
| 1 | TS | 8.792 | 10.318 | +1.526 |
| 2 | ST | 8.220 | 8.181 | −0.039 |
| 3 | TS | 8.239 | 8.713 | +0.474 |
| 4 | ST | 7.989 | 8.506 | +0.517 |
| 5 | TS | 8.681 | 9.360 | +0.679 |
| 6 | ST | 8.127 | 8.400 | +0.273 |

V39 在一對重用較快，配對時間差中位數為 **+0.496 秒**，配對百分比差中位數為 **+6.113%**。ST／TS 順序的時間差中位數分別為 **+0.273／+0.679 秒**。重用階段沒有重建 typed references 或重做 cold late 檢查，這些時間差來自完整入口的觀測。

每臂七次完整入口含冷啟動，原 C1-S1 **65.088 秒**，V39 **72.135 秒**。用未四捨五入的值計算，V39 多 **7.048 秒（10.828%）**。

| 驗證與監督 | 實測 |
| --- | --- |
| 監督窗口 | 362.234 秒，worker 240.346 秒，之後獨立 publisher 112.000 秒，9 個受追蹤程序全數退出 |
| 完整一致性 | 14 份帳本、672 筆完整紀錄、查詢順序與 SQL 工作量核對通過。每臂各一 cold、六 hits、15 次完整快照 |
| 來源與獨立核對 | 同一 closure 的 2,790 個描述符與每次 12,306,922,485 邏輯 bytes 共查核四次。188 個方法、原 15 個 binding，publisher 獨立開啟 14 份帳本及重建兩個 typed roots |
| Publisher typed 分項 | 獨立重建與核對用時 4.141 秒，包含於 publisher 時間 |
| 負載 | 1,076 筆樣本、43 個估計缺口、最大間隔 0.981 秒，最低可用記憶體 17.178 GiB |
| 停態 | 封存 333 個證據檔，唯讀重核通過 |

本輪範圍限於已檢視的 validation 工程樣本。新增 fit、bootstrap、保留測試皆為 0。後續若繼續降低冷啟動成本，可先量 reference 建置的各段成本。

```powershell
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_compare_v41 --audit
```

[真實比較結果與停態證據清單](../reports/stage12/retailrocket_session_knn_v41_compare_result_20261111.json)
