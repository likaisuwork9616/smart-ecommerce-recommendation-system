# Stage 12 V47 V39 與 V46 完整冷啟動配對

V46 把 V39 字元檢查的 Python 逐字迴圈換成對下一個特殊字元的搜尋。V47 在候選 worker 的原 reference 工廠接入該解碼器，對 config 與 model 兩個 root 都使用同一候選。兩臂共用來源、reference 權威驗證、late 比較、快照防護和原 48 筆入口。

| 計時邊界 | 執行方式 |
| --- | --- |
| 單獨 model 解碼 | 完成所有冷啟動後，在同一窗口依相同順序重播，只有外層開始與結束讀錶 |
| Reference 建置 | 每次冷啟動內，沿用 V39 原有的兩個 reference 建置區間 |
| 冷建置 span | `cache.cold_build`，含 reference 建置、context load、prepare、兩次 late 檢查及初始快照 |
| 完整冷入口 | 每次載入新的輸入物件並新建 context 與帳本，計時涵蓋建置、原 48 筆驗證與 final guard。載入輸入物件、關閉 context 與獨立發布各在入口計時之外 |

兩臂各暖機一次，再交替執行六對。14 次都在同一個 worker 使用新 context，主機和作業系統的快取隨順序自然變動。計時期間沒有逐字或逐筆新增抽樣，沿用原有的入口計時與系統負載觀測。獨立發布程序會用原 V39 重建 config 和 model 的權威來源，再核對候選的完整 tuple 結構、各次時序、快照與原帳本。

[比較規格](../reports/stage12/retailrocket_session_knn_v47_cold_specification_20261112.json) · [規格封存](../reports/stage12/retailrocket_session_knn_v47_cold_seal_20261112.json)

## 人工驗收

| 項目 | 實際結果 |
| --- | --- |
| 候選接入 | 直接驗證候選在 config 和 model 兩個 root 走 V46，原版走 V39。兩臂的完整 tuple、來源描述符和 late 核對結果一致 |
| 完整入口 | 人工窗口 14 次各用新 context 與帳本，672 筆完整核對，42 次完整快照，14 次 model 單獨解碼 |
| 防護與停態 | 獨立程序核對全部帳本，拒絕越界建置時點。9 個受追蹤程序全數退出，停態後追加日誌會被拒絕 |
| 測試 | 5 項全通，無失敗、錯誤或跳過。測試與封存約 119.932 秒，真實比較執行 0 次 |

```powershell
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_cold_v47 --audit
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_cold_v47 --measure
```

[驗收收據](../reports/stage12/retailrocket_session_knn_v47_cold_acceptance_20261112.json) · [驗收封存](../reports/stage12/retailrocket_session_knn_v47_cold_acceptance_seal_20261112.json)
