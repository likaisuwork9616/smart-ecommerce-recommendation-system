# Stage 12 V49：既有冷入口紀錄的分項拆帳

本輪只讀 V47／V48 已封存的原固定 48 筆 validation 工程紀錄，分析 reference 以外的時間差。沒有新增實驗窗口、context、查詢、model 解碼、訓練或保留測試。V47／V48 的程式、驗收與原報告維持封存。

## 拆帳方式

新工具先核對兩份報告的固定 SHA-256，再沿用兩版既有 `release(audit_only=True)` 重核停止後的證據。每份 `events.json` 必須在原停態 manifest 中，實際讀取的 bytes 與 SHA-256 都須相同，才進行算術拆帳。

| 層級 | 計算與限制 |
| --- | --- |
| 原事件樹 | 重新計算各節點的 exclusive 時間，扣掉直接子區間；不能把 inclusive 父區間與子區間相加 |
| 冷建置 | 從冷建置的 exclusive 餘額取出原被動 reference 與 late config／model 時點；檢查包含、先後與不重疊，其餘保留為 `cold_other` |
| 三次快照 | 依冷建置、使用前與 final guard 分開，validation、JSON、UTF-8、SHA-256 與 release 為各快照的子項 |
| 查詢與尾段 | primary 包含驗證、append 與所有 commit；tail 扣掉已在 primary 的 commit，seal 只計一次，未被細分的 verifier 時間保留為餘額 |
| 兩個入口時鐘 | `entry.json` 的入口計時與 `run.total` 外層 observer 不完全相同。保留有正負號的 `entry − run.total` 差額，讓分項精確回到原完整入口 |
| 配對 | 以每對 V46 減 V39 計算，正值表示候選多花時間。六對正式合計與中位數分開，暖機另外保留 |

分項合計必須逐次回到原入口時間，逐對回到原配對差值；子項表只用於解釋其父項，不能再與主表相加。各分項的中位數不一定能加成整段差值的中位數。只挑變慢配對的摘要是事後診斷，不是另一組獨立效能樣本。

`cold_other` 包含原冷建置中沒有更細時點的工作，`final_guard_other` 也是 final guard 扣掉快照後的餘額。已有 wall time 能指出差異所在的區間，不能單憑它判定 CPU 等待、實體磁碟 I/O、外部負載或解碼改動的因果關係。

## 離線工具驗收

| 項目 | 實際結果 |
| --- | --- |
| 單元測試 | 13 項通過，無失敗、錯誤或跳過；測試與收據整理 0.139 秒 |
| 區間守恆 | 人工巢狀事件可逐項加總回完整入口；重疊、越界、錯誤原摘要與負成本均拒收，時鐘差可正可負 |
| 子項計算 | primary 與 tail 的 seal／commit 只計一次；snapshot 與 verification/rank 細項各回到父項 |
| 配對與檔案 | 保留負差與平手、排除暖機；變更排程、缺漏紀錄、不守恆與未封存／變動 bytes 均拒收 |
| 不重跑限制 | CLI 拒絕 `--measure`；沒有建立 benchmark 窗口，新增查詢與解碼均為 0 |

驗收綁定本輪分析方法、測試與 V47／V48 兩份固定 SHA-256 報告。這一步先封存工具，正式分項分析於下一步產生。[驗收收據](../reports/stage12/retailrocket_session_knn_v49_phases_acceptance_20261113.json)

## 操作

```powershell
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_phases_v49 --acceptance
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_phases_v49 --analysis
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_phases_v49 --audit
```

`--acceptance` 僅跑人工數值與檔案完整性單元測試，不建立人工 benchmark 窗口。`--analysis` 與 `--audit` 僅重算既有證據，沒有 `--measure` 選項。驗收與分析各只能封存一次，後續使用 `--audit`。
