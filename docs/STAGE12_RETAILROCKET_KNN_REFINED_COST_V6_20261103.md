# Stage 12：V6 細分結構分層與原固定樣本成本複測

本步先完成診斷工具與合成驗收並推送，再完成原 V5 固定 48 筆的三次有界工程複測。**成本主要在排名；原樣本在細分後留下大量沒有樣本的層，尚不足以支持全量工時判斷。** 全量 K1 獨立反讀仍關閉，預留測試 locked，K1−C1 無正式結論，`T_plan` 空值。

## 已完成的前置工作

| 工作 | 實際結果 | 界線 |
| --- | --- | --- |
| 診斷與原保存協定差分 | 26 項相關測試通過，0 失敗／錯誤／略過；入口 48.158 秒 | 包含 V6 新工具、V5 budget 觀測與 V4 四臂配對守門 |
| 保存格式／成本拆帳 | 固定時鐘與 UUID 的 ledger、manifest、stage、budget bytes 與 V5 相同 | 每項 append 分量加總回同一筆原始 enclosing timer，保留計時器開銷 |
| 故障與期限 | 半列寫入、payload fsync、manifest 前／後故障恢復；真程序退出 9 後保留已存 2 筆重算尾段；原 deadline 不變 | 合成資料，不是完整已驗真實 ledger 恢復 |
| 分層守門 | 完整結構 SHA／ordinal／固定 sample 身分／父層數量與細層覆蓋逐一核對 | 未量的細層明列缺口，不能直接丟掉母體 |
| 真實複測 | 三次均完成 | 同原48筆，共144次工程重核、0新unique keys；三次科學payload各2,115,696 bytes，SHA全同原封存 |

驗收收據：[26 項測試](../reports/stage12/retailrocket_session_knn_v6_refined_acceptance_20261103.json)。

## 真實窗口與分層結果

窗口臺北 **2026-11-03 16:03:32.066409 → 16:07:29.763039**，共 **237.703 秒**，外部觀察正常退出 0。初末 **532 份來源**均相同，核對各 **88.819／75.973 秒**；原結構名冊重新細分 **6.880 秒**，三次完整子集入口 **20.635／21.439／21.224 秒**。入口包含準備、來源檢查、四臂核對、保存與證據輸出，不能當成單純 ranking 時間。

退出後另外唯讀重算所有成本、原期限、三次 CP chain／queries seal／48 筆key與科學bytes；三個觀測程序身分均已停止。既有模型與七路原來源保持唯讀，原工程ledger、global與draws本步未重跑。RSS抽樣峰值 **197,963,776 bytes**、本次目錄峰值 **7,023,441 bytes**；目錄不含既有來源／模型，抽樣未完整涵蓋OS temp／cache，均不是全量資源上界。

| 結構分層 | 非空層數 | 所屬細層有樣本的母體筆數 | 細層完全無樣本的母體筆數 |
| --- | ---: | ---: | ---: |
| 原p90四維mask | 12 | 166,897 | 0 |
| 原mask × 鄰居數分帶 | 27 | 63,284 | 103,613 |
| 原mask × 鄰居數 × 投票上界 | 55 | 20,319 | 146,578 |

「有樣本」只表示同層至少有一個原probe，**不是該母體筆數已獨立排名驗收**。三種分層都保留原全部166,897筆結構與同48筆；55層版本約87.8%的母體所屬細層沒有probe。

原大層 `0000` 的131,665筆，細分為0鄰居6,078筆、1–9鄰居22,144筆、10–99鄰居63,573筆、100–499鄰居39,870筆。原四個probe全部在100–499帶，前面 **91,795筆** 所屬帶完全沒有原probe。這說明只把原層細切並不能取得那些帶的真實耗時；本步依使用者要求保留原樣本，沒有補選新keys。

## 查詢與 append 的實測分量

下表每個範圍都來自三次各48筆的**合計**；不是單筆、全量或統計區間。SQL三項內含於rank，rank內含於verification；append子項也內含於append。

| 分量 | 三次合計範圍（秒） | 解讀 |
| --- | ---: | --- |
| verification | 3.865–4.056 | 含排名、來源列／四臂／精確指標核對與payload組裝 |
| rank | 3.446–3.637 | 約占各次verification的89–90% |
| rank中的selected votes／累積 | 1.485–1.613 | 同時含SQL取列與Python精確投票，尚未拆成資料庫純時間 |
| rank中的positive overlaps | 0.921–0.990 | 同時含SQL執行／取列與Python處理，不是SQL引擎單獨耗時 |
| rank中的完整pool SHA | 0.578–0.720 | 完整鄰居池排序／序列化／SHA守門保留 |
| 其他verification | 0.383–0.419 | 同筆verification減rank，沒有扣掉其他必要核對 |
| 逐筆append總和 | 0.338–0.417 | 本樣本48<64，所有chunk提交均發生在最後flush |
| append中的budget檢查其餘成本 | 0.153–0.209 | 含讀budget.json、檢查／時計及require_writer；已排除直接publication，不是純讀檔時間 |
| append中的直接budget publication | 0.058–0.084 | 真實atomic／flush／fsync／rename，保留費用 |
| append中的frame JSON編碼 | 0.090–0.108 | 原科學frame格式與bytes不變 |
| append中的payload實體write | 0.0047–0.0122 | 不含開檔、JSON與最後chunk的fsync |
| 最後chunk commit | 0.106–0.153 | 含其budget寫入；列在tail內，沒有因逐筆commit為0而漏算 |
| setup | 9.539–11.250 | V4子集入口準備，不能外推成逐query費用 |
| tail flush／EOF／seal | 0.334–0.385 | 已包含上列最後commit，不能再加一次 |

固定48筆中排名明顯大於實體payload write；append內也以budget檢查與JSON為主。這只定位本樣本的候選改善處，不能據此宣稱全母體也同比例，不能把「budget其餘成本」全部歸因硬碟讀取。原V1／V2／V3／V4演算法與保存核心未改；V6加入觀測計時，有額外開銷，不是效能優化對照。

## 情境敏感度與決策

| 情境（只含verify＋append，另列commit及直接periodic budget） | 最小／中位／最大（小時） | 未覆蓋細層如何處理 |
| --- | --- | --- |
| 原12個mask | 5.106／5.769／7.493 | 每層4個原probe；仍不是母體時間上界 |
| 27個鄰居分帶 | 4.046／4.489／6.409 | 103,613筆明確借父層最大值 |
| 55個鄰居／投票分帶 | 4.219／4.706／6.621 | 146,578筆明確借父層最大值 |

所有情境只從**同一次**觀測拆直接periodic budget，沒有跨輪扣除。三次均完整保留；原12層中位5.769小時不能與前輪5.971小時相減稱為加速。細分情境即使中位低於4.5小時，也仍有大量借值且未乘原提案兩倍餘裕；例如27層中位乘2約8.978小時，尚未加其他必要階段。**維持no-go；完整T_plan仍空值。**

下一步建議先對沒有probe的細層另立不看target／效果的補樣規格，尤其`0000`的0–99鄰居帶，再討論有界補測；SQL選中投票／overlap與pool SHA是可研究的成本位置。任何改動都須保持完整pool SHA、500邊界、精確投票與恢復守門，之後用原48筆公平配對複測。這是後續建議，本步沒有執行新keys或優化。完整數字、成本拆帳與封存身分見[實測報告](../reports/stage12/retailrocket_session_knn_v6_refined_cost_20261103.json)。

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
