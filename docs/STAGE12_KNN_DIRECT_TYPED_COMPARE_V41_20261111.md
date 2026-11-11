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
