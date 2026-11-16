# V71｜K1 驗收缺口、每日10%待資料與主線排序

依本次指示，**先不安裝Linux**，回到K1完整獨立驗收與每日10%提醒的資料前提。本輪只查既有文件、契約及聚合收據，新增整理文件；不讀大型原始資料或模型、不開資料庫、不匯入研究程式、不新增測試／量測、排名、訓練或bootstrap，也不重跑原48筆。V46暫不採用，Retailrocket預留測試保持locked；Stage4既有test已曝光的歷史不改寫。

本文數字是**既有執行收據記錄**，不是本輪重做實驗或重新核對全部私人原始證據的結果。文件與收據的bytes／SHA綁定只支持來源追溯，不能取代科學驗收。

## K1：主要輸出已產出，完整獨立驗收尚缺

原V1整輪於2026-10-29依使用者3小時30分鐘期限停止；不應把它簡化成「主要validation還沒算完」。當時主要train索引、validation及bootstrap輸出都已產出，未完成的是後續完整獨立反讀與最終驗收。[原停止報告](STAGE12_RETAILROCKET_KNN_VALIDATION_ATTEMPT_V1.md)、[機器收據](../reports/stage12/retailrocket_session_knn_v1_validation_attempt.json)

| 既有項目 | 已有紀錄 | 本輪保留的界線 |
| --- | --- | --- |
| 主要train索引 | 一次主要build；fit audit記1,180,256 sessions、1,823,018 baskets | 主要輸出存在，不等於本輪完整獨立驗收 |
| 主要validation／bootstrap | 166,897個query輸出列、2,000個bootstrap列 | 列數與SHA不證明排名／指標／draw內容正確；不公布未驗收K1效果值 |
| 原V1獨立反讀 | 無最終acceptance／output_guard，獨立完成筆數未知 | 原namespace保持partial；本版機會已用完，不重跑或覆寫 |
| 後來另授權的反讀 | 10/30事後核對記錄：最後觀測923筆，缺8個預期收尾／驗收路徑 | 923只是該次逐query觀測下界，不是正式驗收筆數、完成百分比或checkpoint；實際退出時刻／原因仍未知，不補造歷史收據 |
| V2–V5工程補強 | 合成等價／恢復已做；後來完成全窗166,897筆結構名冊、固定48筆及全形狀工程ledger／global／新自參照draw成本 | 已補的工程覆蓋不再列成「完全沒做」；工程帳本不是全量已驗real ledger，新自參照draws不是原2,000 draws驗收 |
| 後續樣本與優化 | 較新V48 scope保留55／55細格、170個可比較query、232個歷史身分；原48筆有獨立工程比較 | 這些分母不同，不能加到923或由166,897相減推算剩餘驗收量；細格都有樣本不代表每筆都驗收 |
| 全量決策 | V5仍no-go、`T_plan=null`；較新V48仍記全量未完成與`T_plan=null` | 沒有完整工時保證或目前已開放的全量入口；Linux／1ms／V46不列為正式反讀既定必經門檻 |

依據：[另授權反讀事後核對](STAGE12_RETAILROCKET_KNN_READBACK_ONLY_20261029.md)、[V2](STAGE12_RETAILROCKET_KNN_READBACK_V2_20261103.md)、[V5成本與界線](STAGE12_RETAILROCKET_KNN_COST_COVERAGE_DECISION_V5_20261103.md)、[V48收據](../reports/stage12/retailrocket_session_knn_v48_cold_result_20261113.json)。V2當時尚未完成的分層，後續已有V5等補強，不沿用過時缺口。

### 尚缺的正式驗收範圍

下表彙整既有[V1比較契約](contracts/retailrocket_session_knn_paired_v1.json)與[V2獨立反讀契約](contracts/retailrocket_session_knn_readback_v2.json)，不是新增可執行方案或降低原規則。

| ID | 未完成範圍 | 需要的完成證據／目前缺口 |
| --- | --- | --- |
| K0 | 正式來源與獨立重建鏈 | 在新完整驗收中核對允許角色來源、全部train sessions／memberships／postings／lineage／fit audit及四臂固定身分；已有工程重建可列前置，仍缺完整正式鏈與最終收據，不能接續舊不完整SQLite |
| K1 | 全部166,897個query的獨立內容核對 | 同一名冊與原順序、無缺／多／重複；因果history／catalog、完整鄰居池、精確Jaccard／有理投票、前500鄰居與平手／零補位均按原契約核對；有限樣本不代替全量 |
| K2 | 四臂逐query來源與指標 | K1／C1／P0／D1完整payload、current／next basket、lineage、原排名及完整target分母一致；不能重新訓練控制組或用inner join丟掉不符列 |
| K3 | 全域與切片聚合 | 原序重播全部Fold、query／visitor分母、切片及catalog union；主分析保留全部166,897筆，161,211筆全target可達子集只作另列描述；工程global不代替原aggregate驗收 |
| K4 | 原始2,000次bootstrap反讀 | 原visitor-cluster draws、順序、統計及原主要K1−C1區間逐項核對；新工程self-reference draws不能頂替，不重抽到看起來一致 |
| K5 | 完整已驗帳本、恢復與收尾 | 全量已驗real ledger來源／鏈／EOF／全域重播，所選新方法的恢復等價、正常退出與獨立supervisor完成收據；原partial／923觀測不能充當有效prefix，舊缺收據不追補 |
| K6 | 全量成本與資源前提 | 整合來源核對、獨立重建、逐query驗證／保存、global、原draw反讀、恢復／發布為不重複加總的範圍；補足實際尾端、TEMP／RSS／磁碟生命週期與期限覆蓋。`T_plan`仍未知，先維持no-go |
| K7 | 完整最終驗收與研究交付 | 所有必要內容與資源／來源核對通過後，才有新方案完整acceptance與guard／對應收據，才能發布K1−C1開發比較結論；不把V1 partial改寫成成功 |

K0–K5是需要完成的內容與執行證據；K6是排定任何新全量工作的前置條件；K7依賴前述完整通過。驗收通過不等於推薦效果勝出；結果不利或區間跨零也照實交付。即使未來完成，仍是已曝光validation的開發證據，不能稱未知資料成績。最終選模、refit與Retailrocket保留測試是再下一層工作，仍未授權／未啟動，不能先開test補足驗收。

### 現在可整理、但不執行的下一步

可把K6拆成「已有可用成本證據／範圍重疊／未知／需另訂方法」對照，確認準備驗收哪個凍結版本及完整工作分母，再評估是否值得提出新有界方案。不得將48筆快慢、舊V1前段速度或V5樣本最大值外推成完成保證；不為補一張表而新量測。原來源／安全檢查不因成本高就省略。

Linux移植、1ms運算／等待拆分與V46採用均先留在支線。它們未通過不代表K1方法本身已失敗，也不自動阻擋以既有Windows方法另行規劃完整獨立反讀；真正仍缺的是內容、成本、資源及完成證據。[K1盤點收據](../reports/mainline/v71_k1_acceptance_inventory_20261116.json)

## 本輪進度

| 小步驟 | 狀態 |
| --- | --- |
| K1既有成果與8項驗收缺口 | 14份來源描述已核對，獨立靜態審閱通過；非新科學驗收 |
| 每日10%待資料清單 | 接著對照既有交接清單與模型適用限制 |
| 雙主線優先順序 | 待兩份清單核對後固定 |
| Linux安裝／新增測試、量測或實驗 | 全部0 |
