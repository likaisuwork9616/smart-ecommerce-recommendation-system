# Stage 12 V41 原 C1-S1 與 V39 直接比較

| 項目 | 封存內容 |
| --- | --- |
| 資料 | 原固定 48 筆帳本 SHA 與 15 個 binding 已核對，保留 V40 的 2,445 個來源與 183 個方法描述符 |
| 兩臂 | S 為原 C1-S1，T 為 V39。共用來源、SQL、計時與獨立核對規則，各自載入輸入並持有獨立 context |
| 順序 | 單一 worker 先跑 S cold、T cold，再以 TS／ST 交替跑六對，每臂一 cold、六 hits，共 14 份新帳本 |
| 計時 | 原 C1-S1 保留原 canonical，僅在兩次原 late 呼叫加被動計時。V39 沿用已驗收的 reference 建置與兩次完整 late 計時。兩臂的七次完整入口均含 cold |
| 對照邊界 | 每次入口計時前對稱清除評分 memoization。兩次 cold 共用主機快取環境，順序固定且各只有一次。本輪只診斷成本 |
| 完整驗收 | 先跑人工整合，再啟動唯一真實窗口。worker 正常退出後由獨立程序驗兩臂的快照與 672 筆完整帳本，所有程序停止後封存 |

目前已核對規格及既有帳本，真實比較執行 0 次。原資料屬已檢視的 validation 工程樣本，保留測試仍鎖定。

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

人工驗收階段的真實比較執行 0 次。驗收收據封存後以 `--measure` 啟動唯一真實窗口。窗口完成後以 `--audit` 核對公開結果與停態證據。

```powershell
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_compare_v41 --audit
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_compare_v41 --measure
```

[入口驗收收據](../reports/stage12/retailrocket_session_knn_v41_compare_acceptance_20261111.json) · [驗收封存](../reports/stage12/retailrocket_session_knn_v41_compare_acceptance_seal_20261111.json)
