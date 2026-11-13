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

驗收綁定本輪分析方法、測試與 V47／V48 兩份固定 SHA-256 報告。此收據只驗收工具，下列既有紀錄分析另行封存。[驗收收據](../reports/stage12/retailrocket_session_knn_v49_phases_acceptance_20261113.json)

## 六對正式配對的分項結果

兩窗共 28 份既有事件樹、2,156 個事件都能回到原 diagnostic。每次分項加總回完整入口的最大殘差為 3.55×10⁻¹⁵ 秒，遠低於 10⁻⁸ 秒核對容差；每對與六對合計亦回到原完整入口差值。V47、V48 舊報告的停態核對，以及 V49 分項報告的獨立 `--audit` 均通過。

下表單位為秒，均為 **六對的 V46 減 V39 合計**，正值表示候選多花時間，負值表示候選省時。這與 V47／V48 前輪文件的「節省＝V39−V46」符號相反。暖機未納入。

| 互不重疊的階段 | V47 六對合計差 | V48 六對合計差 |
| --- | ---: | ---: |
| 三次快照（冷建置、使用前、final） | −0.820 | +0.958 |
| 原 context 載入 | −0.162 | +0.886 |
| 48 筆主流程（驗證、append、所有 commit） | −0.825 | +0.525 |
| Catalog 準備 | −0.317 | +0.259 |
| 其餘非 reference 項合計 | −0.065 | −0.354 |
| **Reference 以外合計** | **−2.189** | **+2.274** |
| Reference 建置 | −4.085 | −1.923 |
| **完整入口合計** | **−6.274** | **+0.351** |

「其餘」是主表未逐列展示的已拆項與 signed bridge 合計，包含來源核對、identity、late typed、冷建置餘額、final guard 快照外工作、checkpoint、tail、輸出等，並非單一未測階段。完整 21 項逐次／逐對數值均保留在聚合報告。V48 其中來源核對 −0.414 秒、冷建置餘額 −0.230 秒、identity −0.135 秒，抵銷部分增加；signed bridge 為 −0.039 秒，單獨保留而未歸到工作階段。

V48 reference 以外增加的 2.274 秒，主要落在快照、原 context 載入、48 筆主流程與 catalog 準備。V47 六對的 reference 以外工作合計仍省 2.189 秒；其兩個退步配對不能代表整輪都慢。

## 五個完整入口變慢的配對

下表仍為 V46−V39 秒數。主要增加區間列前三項；「其餘非 reference」保留其他正負差，因此三項加此欄等於非 reference 合計，再加 reference 差值才是完整入口差值。

| 窗口／配對 | 完整入口多花 | Reference 差值 | 主要增加區間（前三項） | 其餘非 reference |
| --- | ---: | ---: | --- | ---: |
| V47／5，V46 先跑 | +0.984 | +0.062 | 冷建置餘額 +0.304；identity +0.267；原 context 載入 +0.244 | +0.107 |
| V47／6，V39 先跑 | +1.103 | −0.552 | Final 快照 +0.376；48 筆主流程 +0.299；使用前快照 +0.247 | +0.733 |
| V48／3，V46 先跑 | +0.262 | −0.432 | 48 筆主流程 +0.356；冷建置快照 +0.187；使用前快照 +0.180 | −0.029 |
| V48／5，V46 先跑 | +1.472 | −0.108 | 原 context 載入 +0.822；catalog 準備 +0.308；48 筆主流程 +0.220 | +0.230 |
| V48／6，V39 先跑 | +0.505 | −0.269 | Final 快照 +0.383；48 筆主流程 +0.180；原 context 載入 +0.114 | +0.097 |

V48 最差的第 5 對，主要時間差落在原 context 載入與 catalog 準備；另兩對更偏向快照與主流程。V47 第 6 對也出現快照與主流程增加，但第 5 對主要是冷建置餘額與 identity。現有紀錄支持「退步來源分散」；相同 pair 編號只代表相同排程位置，並非相同負載條件。

## 已有子項能再指出什麼

V48 六對的三次快照合計增加 0.958 秒，其中 validation 增加 **0.775 秒**、JSON 編碼增加 **0.145 秒**，其他快照子項合計增加 0.039 秒。依位置分開，冷建置快照 +0.335 秒、使用前 +0.137 秒、final +0.486 秒。這些都是主表快照的細項，不能再加到主表。

48 筆主流程合計增加 0.525 秒，其中驗證增加 **0.561 秒**，append 不含 commit 減少 0.034 秒、所有 commit 減少 0.002 秒。驗證內較大的增加為 `sql_positive_overlaps` **0.194 秒**、`sql_selected_votes_and_accumulation` **0.151 秒**、`neighbor_pool_sha` **0.149 秒**；其餘驗證細項合計增加 0.067 秒。這些數字來自既有逐筆計時加總，沒有重新執行 SQL 或 ranking。

本輪仍維持暫不採用 V46 為完整入口預設的評估。已定位主要 wall time 差異，但不能據此說 V46 造成其他階段變慢，或認定是磁碟、CPU 等待或外部負載所致。若繼續只用既有紀錄，下一步可檢查 48 筆查詢的增時集中於少數查詢，還是多數查詢都有變化。原 context 載入內沒有更細時點，現存證據不能可靠拆成 CSV 解析、記憶體管理等成本。

| 本輪驗證 | 實際結果 |
| --- | --- |
| 原證據完整性 | 兩份固定 SHA-256 原報告及原停態證據通過既有唯讀核對；分析直接讀取的 28 份 events 各與原 manifest bytes／SHA 相同 |
| 分項守恆 | 28 次入口、12 對正式配對與兩窗各自合計均守恆；2,156 個事件重建一致 |
| 暖機與退步子集 | 四次暖機獨立保留；五對退步另列，未取代六對完整結果 |
| 重現性 | V49 `--audit` 從同一批停止後的證據重新產生完全相同的報告 |
| 範圍 | 新增實驗、context、查詢、解碼、訓練與保留測試各 0 次；只描述已曝光 validation 工程紀錄 |

[正式分項報告](../reports/stage12/retailrocket_session_knn_v49_phases_analysis_20261113.json) · [V47 原窗口](STAGE12_KNN_COLD_V47_20261112.md) · [V48 原窗口](STAGE12_KNN_COLD_REPEAT_V48_20261113.md)

## 操作

```powershell
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_phases_v49 --acceptance
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_phases_v49 --analysis
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_phases_v49 --audit
```

`--acceptance` 僅跑人工數值與檔案完整性單元測試，不建立人工 benchmark 窗口。`--analysis` 與 `--audit` 僅重算既有證據，沒有 `--measure` 選項。驗收與分析各只能封存一次，後續使用 `--audit`。
