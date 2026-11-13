# Stage 12 V53：序位 32／33 的反向波動分項

本輪只用 V47／V48 已封存紀錄，拆查 V52 確認的序位 32／33 反向波動。工具先用人工資料驗收、提交封存，再分析正式紀錄；不重跑實驗、SQL、解碼、訓練或保留測試。兩查詢與兩窗已曝光，以下是既有 wall time 的事後描述，不能視為新驗證或因果分解。

## 先固定拆帳與反向判定

每個序位的差值為 `delta = V46 − V39`；每對的差距為 `gap = delta32 − delta33`，沿用 V52 的逐筆計入時間：verification、append excluding commit、query 內 commit。暖機與尾端 commit 不納入；query 外層時鐘與已計入區間的差額亦不混入。

| 視圖 | 互不重複的分項 |
| --- | --- |
| 四個分組 | ranking、verification 在 ranking 外的餘額、append excluding commit、query 內 commit |
| 十一個原子分項 | ranking 的七個原計時階段、rank 餘額、verification 餘額、append excluding commit、query 內 commit |

ranking 的七個階段為歷史與 TEMP 準備、正重疊查詢、鄰居池 hash、精確鄰居選取、選定鄰居投票與累加、top10 與補零、預測輸出。ranking 分組包含這七項及 rank 餘額，不能再與子項相加；兩個視圖各自加總回同一個 query delta 與 gap。

`rank_other` 與 `verification_other` 是計時差額，沒有另外量到某項具名活動。沿用 V50 的 1e−8 秒巢狀加總容差，保留允許範圍內的微小負餘額，不歸零。

反向條件沿用 V52：32 與 33 的 delta 符號相反，而且兩者絕對值都嚴格大於 1 ms。條件以未四捨五入值判定，恰 ±1 ms 不算；1 ms 是描述尺度，不是顯著性門檻。完整六對與反向子集合分開列，不能用子集合概括整窗。

## 支持差距、抵銷與占比

反向 pair 以 `sign(gap)` 定向，使該對總差距成為 `abs(gap)`。各分項定向後，正值支持這個差距，負值則抵銷；它不表示該分項在兩查詢中也一定反向，更不表示 V46 多做了工作。

對每個視圖分別計算：

```text
定向分項 a[p,s] = sign(gap[p]) × (delta32[p,s] − delta33[p,s])
支持正量 P = Σ_pair Σ_stage max(a[p,s], 0)
抵銷負量 N = Σ_pair Σ_stage min(a[p,s], 0)
P + N = Σ_pair abs(gap[p])
某分項支持占比 = Σ_pair max(a[p,s], 0) / P
```

先在每對、每個分項分正負，再跨對加總。不能改用「先跨對抵銷後才取正量」的分母，也不能除以淨差距。各分項保留支持正量、抵銷負量、方向對齊後的淨量與占比。

ranking 先合併八個子項時可能內部抵銷，因此四分組的 P 不一定等於十一原子分項的 P；兩視圖占比不可混用。沒有反向 pair 時，總量為零、占比為 null。

另外保留完整六對每個分項在 32、33 及 gap 的合計、中位數、MAD、最小／最大等分布。MAD 未乘校正常數；不能把各階段的中位數或 MAD 相加當成整段成本或波動。

## 驗收與來源

16 項人工測試全通，無失敗、錯誤或跳過，耗時 1.259 秒：核心分項 11 項、人工入口整合 5 項。使用人工分項與人工 28 入口，涵蓋兩種反向、1 ms 邊界、正負抵銷、兩種視圖各自的分母、空反向集合、父子層不重複、餘額容差、來源順序與身分、V52 總差與方向回核、暖機／尾端 commit 排除，以及 CLI 拒絕 `--measure`。本階段未讀原始紀錄作正式分項分析。[驗收收據](../reports/stage12/retailrocket_session_knn_v53_peer_stages_acceptance_20261113.json)

本輪方法及測試綁定 bytes／SHA-256，並固定 V47–V52 六份報告。正式分析先唯讀重建前序結果，再核對 28 份原 `measured.json` 與 1,344 筆身分／順序／邏輯工作量，僅選 32／33 的正式六對計時作分項。公開報告只有匿名 subset 序位與衍生差值，不提交原 key、原 ordinal、SQL 列或本機模型。

## 操作

```powershell
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_peer_stages_v53 --acceptance
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_peer_stages_v53 --analysis
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_peer_stages_v53 --audit
```

驗收與正式分析各封存一次，後續使用 `--audit` 唯讀重核。沒有啟動 benchmark 的模式。
