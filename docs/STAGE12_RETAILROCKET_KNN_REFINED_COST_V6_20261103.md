# Stage 12：V6 細分結構分層與原固定樣本成本複測

本步先完成診斷工具與合成驗收，再執行原 V5 固定 48 筆的有界工程複測。全量 K1 獨立反讀仍關閉，預留測試 locked，K1−C1 無正式結論，`T_plan` 空值。

## 已完成的前置工作

| 工作 | 實際結果 | 界線 |
| --- | --- | --- |
| 診斷與原保存協定差分 | 26 項相關測試通過，0 失敗／錯誤／略過；入口 48.158 秒 | 包含 V6 新工具、V5 budget 觀測與 V4 四臂配對守門 |
| 保存格式／成本拆帳 | 固定時鐘與 UUID 的 ledger、manifest、stage、budget bytes 與 V5 相同 | 每項 append 分量加總回同一筆原始 enclosing timer，保留計時器開銷 |
| 故障與期限 | 半列寫入、payload fsync、manifest 前／後故障恢復；真程序退出 9 後保留已存 2 筆重算尾段；原 deadline 不變 | 合成資料，不是完整已驗真實 ledger 恢復 |
| 分層守門 | 完整結構 SHA／ordinal／固定 sample 身分／父層數量與細層覆蓋逐一核對 | 未量的細層明列缺口，不能直接丟掉母體 |
| 真實複測 | 尚未執行 | 下一步才新開最多 1,800 秒工程窗口；三次同 48 筆，0 新 unique keys |

驗收收據：[26 項測試](../reports/stage12/retailrocket_session_knn_v6_refined_acceptance_20261103.json)。

## 分層事前規則

只重新掃描已封存的 166,897 筆 V5 結構名冊，不重建原模型、不重新選樣、不讀 targets／推薦效果來決定層。沿用原 p90 四維 mask，另加兩種細分：

1. 父 mask × eligible-neighbor 分帶：0、1–9、10–99、100–499、500–999、1,000–4,999、5,000 以上。
2. 上列再 × vote-memberships-upper 分帶：0、1–99、100–499、500–1,999、2,000–9,999、10,000 以上。

分帶是固定整數結構規則，不依新計時調門檻。每一種分層保留全部母體與同一批 48 筆身分；細層無樣本時，明列未覆蓋筆數。可另列「未覆蓋層借父層最大值」的敏感度情境，但借值不是實測覆蓋，更不是該細層上界。所有新分層及 sample 對應先保存，再開始計時。

## 查詢與 append 如何記帳

V4 既有 rank timer 與七個 SQL／精確投票階段繼續保留。`verification − rank` 列為其他核對成本，包含來源讀取、query／target／四臂一致性、指標與 payload 組裝，不能把 rank 另加一次。

V6 只有 `append_verified` 依 V2 相同操作順序加入計時點；期限、writer、來源核對、chunk 提交／fsync、恢復與排名仍用原實作。append 分成 budget 檢查、guard／key、frame JSON 編碼、首列 payload 開檔、兩段實體 write、pending／觸發、nested flush。逐筆直接 budget `_atomic` 的時間只從同筆 budget 檢查扣一次；commit 的 budget 仍留 commit。外部包裝／計時器與未分類開銷另列，所有互斥分量必須精確加總回 V4 同一筆 append 實測。正常 write 不含 chunk 階段的 fsync，兩者各列。

診斷有計時器開銷，不能拿新舊窗口相減宣稱加速；本步沒有排名或保存流程的效能優化。

## 有界複測與發布規則

使用原七路來源抽取子集、原 ordinal／key、原 rebuilt SQL model 及原 48 筆 ledger 總 bytes／SHA。三次各在新 namespace 重算四臂核對與 checkpoint，144 次工程 K1 重算但 0 新不同 keys，所有 repeat 共用同一個原絕對期限及總 1,800 秒預算。初末核對繼承的來源名冊，外部 supervisor 監控記憶體／磁碟與程序退出。

正常退出後，另以唯讀方式重算逐筆事件、互斥成本、分層情境、CP chain／queries seal、原期限與三次科學 payload SHA；沒有正常退出或任一守門失敗就不發布完成報告。只發布聚合成本／母體／覆蓋及檔案身分，原始 keys、逐筆數字、targets、預測、模型與執行狀態留在 Git 忽略目錄。

情境一律是 Σ層母體數 × 該層固定樣本最大 verify＋append，commit／setup／tail 另列；未覆蓋細層清楚列父層借值。各分量最大值可能出自不同 query，不能相加冒充同筆最大值。三次呈現完整範圍與中位數，不只挑最快一次；cache／系統條件未控制，不作因果或統計推論。完整工時、全量科學驗收及原 draws 不在本步。

## 操作

在專案根目錄執行：

```powershell
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_refined_cost_v6 --acceptance
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_refined_cost_v6 --measure
```

查看結果請直接讀報告，不因查看而重跑。`--measure` 會實際重算三次既有樣本，須先通過目前檔案／環境的驗收；沒有全量／final／test 開關。每日 10% 提醒預算與 Dashboard 暫緩維持。
