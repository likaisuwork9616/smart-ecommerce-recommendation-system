# Stage 12：保存前檔案檢查與身分驗證

沿用同批七筆、固定對照與原排名方法，先拆分保存前的檔案存在判斷及身分檢查，再評估正重疊 SQL 候選。所有觀測屬已曝光 validation 的工程診斷，不是未知資料成績；完整 validation 與保留測試維持未啟動。

## 盤點

本輪前後核對 **174 份來源、每次 6,233,104 bytes**，確認 V20 六輪共 42 次的來源與結果。未重新讀取大型模型或原始資料，也未執行新排名。固定樣本與順序、既有七路子集及原 1,945 位鄰居對照可直接沿用。

V20 最大診斷 append 差為 **17.239 ms**，其中 guards_and_key **15.551 ms**；另一個案例的 writer／context 剩餘差 **9.734 ms**。這兩個區段仍混合檔案存在檢查與 Python 處理，不能認定成單一磁碟或 SQL 原因。

| 保存前區段 | 原操作與本輪觀測缺口 |
| --- | --- |
| writer 檢查 | 先檢查 writer guard，再查 acceptance.json；不能跳過檔案查核或改變例外。 |
| query stage 檢查 | candidate.json 或 stages/global.json 存在即停止，保留原短路順序。 |
| 身分格式 | _key 檢查 list、字串數字、正規化整數與非負整數，須與順序比較分開解讀。 |
| 其餘順序與初始化 | ordinal、前一筆 key、首次 reconstruction 狀態及代理開銷仍列剩餘成本，不假稱純身分驗證。 |

只觀測 direct append 的這三個 exists 呼叫與原 _key，保留原操作次數、回傳與失敗順序。CPU 仍可能呈 15.625ms 級量化，短段以 wall 計時定位，不將 wall−CPU 視為 I/O 等待。

覆蓋維持 **55／55 格、170 個可比較查詢、232 個歷史身分**；該格 11 筆、尾端 6 筆。本階段新增身分、排名與 SQL 候選執行均為 0。

[盤點收據](../reports/stage12/retailrocket_session_knn_v21_guards_inventory_20261106.json)

## 固定細項診斷規格

沿用同一批七筆、原始順序與 V19 既有子集。R 保留原 V4／V6；D 保留 V20 的 SQL／預算觀測，再加入 direct append 檔案與身分檢查。固定 **R→D、D→R、R→D**，共六輪、42 次核對，全部循序；不清快取、不排除暖機、不換樣本或追加較快結果。

新觀測用每次呼叫專屬的 store/path view 執行原 V6／V2 bytecode，量測原 acceptance.json、candidate.json、stages/global.json 三個 exists 呼叫，以及原 _key 格式驗證。保持原短路順序、回傳與例外，不增加檔案查核、不快取結果、不移除安全檢查。第一次 reconstruction 讀取、ordinal／先後 key 比較、Python 分派及觀測成本保留在剩餘項，不能把剩餘項當成純身分驗證。

保留原分項 wall／執行緒 CPU、writer 內含 acceptance 的巢狀關係；存在檢查與 key 子項不得超出其原外層時間。CPU 量化與有號 wall−CPU 原樣保留，不能當等待量。公開僅顯示用途標籤，私人證據保留完整紀錄。

六輪每輪都對回全部七筆 V19 完整科學 payload、工作量與實體位元組；新樣本仍為 0。沿用 200ms 目標負載觀測、原 1,800 秒窗口與資源限制，首尾涵蓋各驗證入口且六輪不重疊。失敗就保留證據並停止發布，不重開較快窗口。

## 診斷後的 SQL 候選評估

完成診斷後再獨立評估「posting 先聚合，再 LEFT JOIN session size」的具體改寫。先看既有成本與原／候選 EXPLAIN QUERY PLAN；實際模型只做計畫檢查，不執行候選真實排名。若提出候選，使用人工資料比較完整預測與工作量，涵蓋自我排除、空結果、未知／未來商品、切點同分及缺少 size 的拒絕行為。

查詢計畫或合成語意通過都不能當作加速證據。這一階段給出是否值得另立配對效能試驗的判斷；沒有候選真實計時就不採用、不報加速比例。先前 V17 投票候選未達門檻的結論保留。

全通過後覆蓋仍 **55／55 格、170 個可比較查詢、232 個歷史身分**；該格 11、尾端 6。本階段尚未實測，完整 validation／主要訓練／主要 bootstrap／保留測試均不啟動。

[封存規格](../reports/stage12/retailrocket_session_knn_v21_guards_specification_20261106.json)

## 工具驗收

**45／45 項合成驗收通過**，耗時 17.540 秒，失敗／錯誤／跳過均為 0。 新增的 10 項驗收涵蓋原完整預測與工作量、保存位元組、巢狀 commit、預算／期限／寫入故障、檔案短路及例外、缺少 writer、身分錯誤，以及有號 CPU 與巢狀成本守恆。其餘 35 項沿用既有 V20、V6 與負載測試。

三個新工具／測試檔獨立版本化；原 V4／V6／V20 檔案保持封存。實際檔案呼叫 trace 與原流程一致，候選存在時不再查 global；acceptance 存在時不查後續檔案或身分。

操作：先以 `.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_guards_v21 --acceptance` 完成一次驗收，再用同模組 `--measure` 執行唯一窗口。已完成的窗口只可 `--publish <原 namespace>` 重稽核，不能另開窗口挑結果。原始身分、模型與完整負載紀錄保留 Git 忽略路徑。

[工具驗收收據](../reports/stage12/retailrocket_session_knn_v21_guards_acceptance_20261106.json)

## 六輪實測與獨立核對

同批七筆以 **R／D／D／R／R／D** 循序完成，**42／42 工程核對通過**。受監督窗口 116.484 秒，正常退出、受監督程序全部結束；1,279 份來源在窗口前後及退出後一致。六輪完整 payload、工作量與實體帳本全部等同 V19，各帳本 316,274 bytes、SHA-256 `63ad49356918d0ca94726f2037b2e878edcc2ba6b492baac86132383e072eff1`。

另以獨立程式檢查 159 份私人證據、六份實體帳本、21 筆 SQL／預算／guard 分解；共 63 次 direct exists、21 次身分格式驗證，順序與次數一致。固定查詢中位數、同對差與 CPU 加權負載重算相符，沒有換樣本或追加較快窗口。

覆蓋仍 55／55 格、170 個可比較查詢、232 個歷史身分；該格 11 筆、尾端 6 筆。新增主要訓練、完整 validation、主要 bootstrap 及保留測試均為 0。本輪只屬已曝光 validation 工程診斷。

## 新拆分的檔案檢查與身分格式

下表為 D 的 21 筆觀測，單位 ms。均只包住原呼叫；其前後 Python 分派與觀測器工作仍列剩餘項。

| 原操作 | wall 最小 | wall 平均 | wall 最大 |
| --- | ---: | ---: | ---: |
| acceptance.json 存在檢查 | 0.0549 | 0.0725 | 0.1142 |
| candidate.json 存在檢查 | 0.0360 | 0.0493 | 0.1212 |
| stages/global.json 存在檢查 | 0.0309 | 0.0391 | 0.0890 |
| 原 _key 身分格式驗證 | 0.0053 | 0.0068 | 0.0157 |

本輪沒有重現 V20 的 guards_and_key 約 15.551 ms 同對差；不能把本輪短耗時當成前輪成因已排除。Path.exists 包含 Python／作業系統／檔案系統與可能排程時間，不是純磁碟時間。身分格式驗證不含後續 ordinal、前一筆 key 比較或首次 reconstruction 查核，這些保留在其餘項。

## 同查詢波動與 append 預算保存

各模式、各指標分別挑同一查詢的最大快慢差，輪次從 1 起算。不同列不可相加。

| 模式 | 指標 | 鄰居數 | 快→慢輪 | 差 ms |
| --- | --- | ---: | --- | ---: |
| R | 核心 | 2,499 | 5→1 | 44.263 |
| R | 正重疊整段 | 2,499 | 5→1 | 19.079 |
| R | append 扣 commit／budget | 4,071 | 4→5 | 5.617 |
| D | 核心 | 4,071 | 6→2 | 24.178 |
| D | 正重疊整段 | 2,770 | 3→2 | 12.664 |
| D | append 扣 commit／budget | 3,156 | 6→2 | 3.736 |

D 最大調整後 append 差出現在 3,156 位鄰居案例，第 6→2 輪。**原始 append +102.240 ms，其中原直接 budget 保存 +98.504 ms，扣 commit／budget 後 +3.736 ms**。不可將原始差全算成檔案檢查，也不能忽略已分列的預算保存。其餘差分解為：

| 同一對原分項 | wall 差 ms |
| --- | ---: |
| budget_check_other | +1.0864 |
| budget_publication | +98.5038 |
| chunk_commit | +0.0000 |
| flush_dispatch_other | +0.0025 |
| frame_encode | +1.0958 |
| guards_and_key | +0.6931 |
| observer_and_outer_other | +0.0117 |
| payload_open | +0.7613 |
| payload_write | +0.0762 |
| pending_and_trigger | +0.0087 |

其中 guards_and_key +0.6931 ms 進一步拆為：

| 同對 guard 細項 | wall 差 ms |
| --- | ---: |
| candidate_exists | +0.0682 |
| global_exists | +0.0271 |
| identity_format | +0.0084 |
| order_reconstruction_dispatch_other | +0.5894 |

兩個 query-stage exists 合計僅 +0.0953 ms、身分格式 +0.0084 ms，其餘 +0.5894 ms；acceptance exists 同對為 −0.0379 ms。budget read_text 同對 +1.1279 ms，位於 budget_check_other；不能與內含的預算保存重複加總。這些定位仍不足以識別排程或檔案系統的單一原因。

D 正重疊最大差出現在 2,770 位鄰居案例，第 3→2 輪 **12.664 ms**；同對原 execute **+0.735 ms**、取列（含 EOF）**+9.611 ms**、Python／watch／代理其餘 **+2.318 ms**。取列也包含 SQLite stepping 與 DB-API 轉換，不能當純 SQL 或純 I/O。

## 固定對照與觀測成本

下表先對每筆取各模式三輪中位數，再對七筆等權平均，單位 ms。核心在每筆每輪先算 verification＋append 扣 commit／直接 budget；rank 和 vote 已內含於 verification。各欄中位數不必來自同輪，不能相加。

| 模式 | 核心 | verification | rank | vote | append 扣 commit／budget |
| --- | ---: | ---: | ---: | ---: | ---: |
| R | 77.581 | 73.642 | 68.030 | 13.731 | 4.211 |
| D | 79.184 | 75.088 | 68.792 | 10.761 | 4.035 |

相鄰配對以下改用當輪七筆算術平均。D−R 包含觀測器、順序及當時機器狀態，不能當優化比例或固定觀測成本修正。

| 配對 | 核心 D−R ms | 正重疊 D−R ms | append D−R ms |
| --- | ---: | ---: | ---: |
| 1：RD | +1.757 | +8.489 | -0.041 |
| 2：DR | +2.495 | +7.801 | +0.302 |
| 3：RD | +1.183 | +6.834 | -0.732 |

## 計時限制與同步系統負載

正重疊非零執行緒 CPU 仍呈 **15.625 ms** 增量，21 筆中 10 筆 wall−CPU 為負。candidate／global exists 與身分格式各 21 筆 CPU 全記為零；acceptance exists 有 1 筆記為 15.625 ms、超出其 wall。原有號值保留。短段「記為零」不等於沒有運算，wall−CPU 不能當等待或 I/O 比例。

| 輪次／模式 | 快照 | 驗證入口秒 | CPU 範圍／加權平均 | 最低可用 GiB | 最大採樣間隔 ms |
| --- | ---: | ---: | --- | ---: | ---: |
| 1／R | 22 | 4.721 | 14.3–58.0%／25.96% | 20.203 | 845.065 |
| 2／D | 22 | 4.885 | 13.3–49.2%／24.19% | 20.167 | 317.117 |
| 3／D | 21 | 4.465 | 14.2–34.8%／24.14% | 20.229 | 259.852 |
| 4／R | 21 | 4.419 | 13.2–37.5%／20.87% | 20.388 | 257.397 |
| 5／R | 20 | 4.272 | 13.3–30.0%／16.82% | 20.405 | 272.192 |
| 6／D | 21 | 4.613 | 14.4–26.6%／19.75% | 20.381 | 283.796 |

六輪共 127 份負載快照，CPU **13.2–58.0%**、最低可用記憶體 **20.167 GiB**。第 1／2 輪按 200ms 名目間隔估算跳過 3／1 槽，其餘為 0；首尾包覆與六輪不重疊核對通過。負載只涵蓋驗證入口，不涵蓋前後模型雜湊或準備。

每輪觀測到兩個 ollama 名稱程序，匹配區間 CPU 增量皆記為零；沒有觀測其他名稱 runner、GPU 或 token 速度，因此仍不能量化 Ollama 減速或宣稱沒有影響。全程未改動 Ollama 服務或模型。

## 診斷結論

已區分原三次 exists、原身分格式驗證，以及順序／初始化／觀測剩餘項。本輪這些細項短，前輪大幅 guard 波動未重現；原始 append 的大差亦須先分出直接預算保存。正重疊查詢仍有明顯且跨 execute／取列的耗時，下一步按封存規格評估先聚合再 join 的 SQL 候選。此時候選真實排名為 0，尚無 SQL 加速比例或採用決定。

[六輪實測](../reports/stage12/retailrocket_session_knn_v21_guards_cost_20261106.json) · [同對分解分析](../reports/stage12/retailrocket_session_knn_v21_guards_analysis_20261106.json)

## SQL 候選評估完成：先聚合，再 LEFT JOIN size

候選只替換原正重疊 SQL：先將 history 命中的 posting 依 `(v,s)` 聚合，再 LEFT JOIN `k1_v2_sizes`。實際模型確認該表有 `(v,s)` 唯一主鍵，因此每組只對到一個 size；保留 LEFT JOIN，缺少 size 仍由原 V4 拒絕，不能改成 INNER JOIN 靜默刪掉錯誤資料。排名、完整鄰居池 SHA、500 位切點同分、精確分數、投票與因果商品篩選沿用原函式。

**24／24 項合成驗收通過**，耗時 0.737 秒，失敗／錯誤／跳過為 0。包含新候選 10 項、原 V4 11 項、SQL 觀測 3 項。新候選比較完整巢狀預測及所有工作量，涵蓋 499／500／501 同分切點、大整數 ID、30 組固定種子人工案例、自我排除、空／未知／未來商品、分數 fallback、缺少／無效／過期 size、watch 中斷及唯讀檔案位元組。合成測試耗時不是效能證據。

### 實際模型計畫

使用原 475,103,232-byte 模型，連線為 `mode=ro&immutable=1`；TEMP history 固定為空且留在記憶體，建立後啟用 query_only。只對原式與候選各執行一次 EXPLAIN QUERY PLAN，沒有執行候選真實排名、讀入查詢身分或寫入模型。模型 SHA-256 在評估前後一致、目錄檔名未變；退出後再獨立核對所有來源與私人收據相符。

| 步驟 | 原式 | 候選 |
| --- | --- | --- |
| history／posting | SCAN query → COVERING INDEX k1_v2_posting | 相同 |
| group／size 順序 | 每筆 posting 查 size 主鍵 → TEMP B-TREE GROUP BY | TEMP B-TREE GROUP BY → SCAN hits → 查 size 主鍵 |
| 額外結構 | 無 hits 子查詢 | CO-ROUTINE hits |
| 保留的工作 | posting 掃描、聚合、回傳群組與 Python 處理 | 同樣保留；僅移動 size lookup |

同批七筆原 R 的正重疊整段中位數平均 **31.962 ms**，核心中位數平均 **77.581 ms**。正重疊值得檢視，但該段仍混合 SQL、取列與 Python 工作，不能把全部時間當候選可節省部分。

沿用封存工作量：posting 匹配 **21,072 次**、回傳正重疊群組 **19,391 個**。依計畫形狀推論，size lookup 的邏輯輸入可少 **1,681 次（7.977%）**。這只是原匹配數減群組數，不是候選實測 VM 步數、I/O、SQL 耗時或整體加速比例；子查詢成本可能抵銷節省。七筆包含六個刻意補強的已知尾端案例與一個固定對照，不能外推全部 55 格。

既有 V17 投票候選 `rank_counts` 維持不採用：當時 6 對中 5 對較快，但主要指標節省中位數 **2.676%**，低於原門檻 **5%**。本輪正重疊改寫是另一個候選，不能借用其結果。

### 評估決定與後續

**合成語意與查詢計畫成立，暫不採用；尚無實測加速比例。** 這個改寫可列入低預期的小型配對試驗候選，不足以直接推進正式流程。若續作，先獨立封存原 48 筆公平比較：固定原／候選順序平衡、完整 payload 比對、主要成本與 SQL／append 分列、循序執行並同步負載，採用門檻先定，不沿用診斷 R/D 的差值。

這一階段候選真實排名／效能執行皆為 **0**，實際模型 EXPLAIN 共 **2** 次；55／55 格、170 個可比較查詢與 232 個歷史身分不變。主要訓練、完整 validation、主要 bootstrap 與最終保留測試均未啟動。

可用 `.venv/Scripts/python.exe -B -m scripts.assess_retailrocket_session_knn_overlap_candidate_v21` 重建此類一次性評估；本機已封存收據時會拒絕覆寫。候選模組未接入預設排名路徑，既有方法檔未修改。

[候選語意、計畫與決策收據](../reports/stage12/retailrocket_session_knn_v21_guards_sql_assessment_20261106.json)
