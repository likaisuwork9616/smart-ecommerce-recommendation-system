# Stage 12｜V67 一次 B 時鐘能力校準

依 [V62 規格](STAGE12_KNN_WALL_CPU_SPEC_V62_20261116.md)及已獲使用者確認的 [V66 計畫](STAGE12_KNN_CLOCK_CALIBRATION_PLAN_V66_20261116.md)，準備並最多執行一次 B。V66 的「待確認」保留為當時的歷史狀態；本輪明記使用者已授權工具準備、假時鐘驗收通過後的一次 B，整關 30 秒，失敗不補跑。C／D、原固定 48 筆、真實 model、SQL、訓練與背景負載採樣均不執行；V46 維持暫不採用。

## 先封存、再驗收、最後一次 B

| 小步驟 | 狀態與實際結果 |
| --- | --- |
| 工具與案例 | r2 已封存來源與123個具名案例（49／32／18／24）；獨立靜態審閱完成，先推送 |
| 假時鐘驗收 | r2 首次suite 123全過（49／32／18／24）；失敗／錯誤／跳過0，log 1.572秒；正式唯讀反查相符，未重跑 |
| 正式 B | 唯一一次已執行；首輪bracket max 227,300ns >100,000ns提前停止，能力未確認；整關1,942,445,700ns，未補跑 |
| 結果與唯讀核對 | 正式及獨立audit通過；163個唯一descriptor與30,570組統計相符，live attempts=1／reruns=0；不進C／D |

V62–V66 封存來源保持原樣。新判定接入保留 V65 `_capability` 的 code object 與數值公式，只在每次呼叫的獨立 globals 替換來源驗證／結果呈現。實測記錄用 `real_clock_capability_v67`，人工案例用 `fake_clock_capability_v67`；不把實測改標為人工資料。純判定器不自稱實際執行 B，正式結果須另有 collector 的讀錶身分、整關起訖、落盤與唯一 attempt 證據。

## 固定收集與截止規則

同一新 worker／thread 在第一個 control wall 後取得環境與兩鐘 metadata；驗證實際 reader 是 `time.perf_counter_ns`／`time.thread_time_ns`／`threading.get_ident` 原函式物件。三輪各以首末 `wall_before` 差達 500,000,000 ns，cap 每輪 1,000,000 組含首點；十次只呼叫 `sleep(0.05)`。每組沿用 V63 的 thread guard → wall_before → CPU → wall_after → thread guard，三讀中間不插入驗證或 I/O。

每組只讀 capture 回傳的邊界，避免反覆複製全部累積邊界。control wall 另列，不混進 B 的 wall／CPU／bracket 分布。依 V66，只有完整輪且至少十個正 CPU 增量才用該輪 p95 提前判不足；未完整輪的 V65 純判定數值保留為診斷，不把它當完成輪能力判定。結構錯誤優先拒絕，第一個例外及後續錯誤均保留。

**30 秒含 metadata、收集、統計判定、必要原始證據序列化／flush／fsync 與描述雜湊。**canonical record 的結束點在純判定前，清楚標為該範圍；正式 `final.elapsed_wall_ns` 使用落盤後最後 control wall，才是整關時間。raw snapshot 尚未經落盤後讀錶，固定標為 provisional，不可單憑 raw 中 completed 宣稱 B 通過。最後 envelope 是事後發布，保留 raw 雜湊及最後控制證據，不延長成功窗口。

parent 在 Popen 返回後最多等待子程序 30 秒；子程序前置核對及結果發布也占這段等待，可能提早中斷 B，但不放寬 collector 的整關截止。timeout 只終止本次持有的 child，保留缺失及失敗，不補跑。OS 呼叫返回或失敗證據整理可能超過期限，均不得稱按時成功。

停止／失敗規則完整沿用 V66：不可用 metadata、樣本不足／cap、逾時、取消、讀錶或保存失敗等不通過；CPU 宣告解析度或完整輪正增量 p95 >100,000 ns 判不足；bracket max >100,000 ns 可停，全固定集合 p99 >50,000 ns 不通過；任一 sleep wall <40 ms 可停，十次 CPU／wall p90 >0.10 不通過。保留三輪／十次固定槽位，未執行者為 null，不捨棄慢值、不延長、不追加。

## 封存與案例範圍

r2 固定123個具名案例（既有回歸49／collector32／來源接入18／driver24）。方法 manifest 以 AST 列出具名案例及遞迴來源，封存時不 import 案例、不讀本輪 clock metadata。執行前要求 main 與已推送 tracking ref 相同，且 Git 提交內的新方法／封存 bytes 與本機一致。歷史 .md／.py 來源仍先核對原封存 bytes／SHA256，只允許其CRLF正規化為Git的LF後逐byte一致；任何其他內容差異均拒絕。假驗收每個 revision 只能一次；失敗保留 receipt，修正必須另版封存推送。

| 案例群 | 封存前設計範圍 |
| --- | --- |
| V63 核心／統計、V65 B | 既有純資料回歸 26＋14＋9，不呼叫 C／D 或 typed worker suite |
| collector | 三讀順序、完整槽位、cap／target 同點、30 秒前／同點／後、慢 metadata／判定／落盤、錯誤／取消、停止後不再校準、partial raw、主次錯誤及真純判定接線 |
| 真實來源接入 | 原算術及 code object 保留、origin／source／metadata 拒絕、reader 身分核對不讀錶、不把 record 數值通過冒充 live B |
| 一次性入口 | exclusive reservation／claim、跨 revision 禁補跑、固定 child timeout、落盤失敗、公開去除原始刻度、saved receipt 重算、篡改拒絕及 provisional 不冒充成功 |

假案例只使用 literal readers／人工記錄與私人臨時檔案；driver 的程序控制用假的 child，不啟動實機 worker。實機 API 的函式物件比對不等於呼叫或量測該 API。

## 操作與保存

**本次唯一B已執行，額度已用完。**以下是本輪操作歷程；不要再次執行measure，可使用audit做唯讀核對。

```powershell
# 封存後先更新 README、commit 並 push main，才允許新假案例執行。
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_clock_calibration_v67 --freeze --revision 2
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_clock_calibration_v67 --acceptance --revision 2
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_clock_calibration_v67 --audit-acceptance --revision 2
# 驗收結果也須 commit／push；以下全 V67 最多一次，失敗不重試。
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_clock_calibration_v67 --measure --revision 2
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_clock_calibration_v67 --audit-measure --revision 2
```

實機使用全 V67 唯一的 exclusive reservation，加上 worker exclusive claim；失敗、launch failure、timeout 或跨 revision 都不能重新啟動。原始整數、環境／身分、metadata、control wall、partial captures、完整輸出與 log 僅存 Git 忽略的 `shop-mysql-runtime/verification/`。公開收據只保存相對證據描述、聚合統計與失敗原因，不含原始絕對刻度及程序／執行緒身分。

唯讀 audit 核對封存、已推送提交、假驗收、reservation／claim、證據雜湊，重算純判定與整關截止，核對 raw prefix、final 判定及公開摘要。audit 不讀新時鐘、不 sleep、不重跑 suite 或 B。raw／final 缺失就明示，不能推測通過。

q 仍只是該窗口的 CPU 推進量篩檢，不是真硬體精度或誤差界；B 即使通過也不代表開銷已驗收，不授權 C／D，不能細分 32／33 的運算與等待，也不構成 V46 採用證據。

## r1 預檢紀錄

r1 已先推送57d8188；新案例執行前的來源Git核對遇到歷史V20文件本機CRLF／Git LF差異而拒絕。當時測試0、fake reservation未建立、B 0次。保留r1 manifest與預檢紀錄，r2只補歷史文字的嚴格換行對照及兩個假案例；先重新封存推送再執行，未試跑校準。

## r2 假驗收實際結果

先推送1e6402c後執行唯一一次r2 suite：123項全過、失敗0、錯誤0、跳過0。log為1.572秒，僅代表合成測試執行，不是實機刻度或開銷。正式audit核對來源／Git／reservation／attempt／具名log全部相符，tests rerun=0。此階段B仍0次，尚未取得本輪clock metadata；發布本驗收後才可啟動唯一一次B。

[假驗收收據](../reports/stage12/retailrocket_session_knn_v67_clock_acceptance_r2_20261116.json)。

獨立反讀另核對156個唯一local descriptors、7個新方法／seal Gitblob、145個歷史inputs（136 exact、9僅CRLF→LF）、123個AST／loaded／named ok案例及private reservation／attempt／log，全數一致。該次反讀確認B reservation與result均尚不存在，沒有執行測試body或讀實機時鐘。[獨立收據](../reports/stage12/retailrocket_session_knn_v67_clock_independent_fake_audit_r2_20261116.json)。

## 唯一一次 B 實際結果

假驗收結果已推送407461a後才建立唯一reservation與worker claim。正式B結論為 **clock_capability_unconfirmed**，沒有達到完整能力驗收；因第一輪bracket超標提前停止，不補跑，也不執行C／D或原固定48筆。

| 項目 | 已保存的實際結果 |
| --- | --- |
| 正式attempt | 1次；worker正常退出0，supervisor未timeout、無launch error |
| 整關wall | 1,942,445,700ns＝1.9424457秒，包含metadata、收集、純判定與必要raw序列化／flush／fsync／hash；未逾30秒 |
| 第一輪 | 30,570組；首末wall_before差301,961,900ns＝0.3019619秒，未滿500ms，completed=false |
| 停止點 | `round:1:stamp:30569`（零基，實際第30,570組）bracket 227,300ns＝0.2273ms，超過100,000ns上限 |
| 片段bracket | min／p50 1,000ns，p95 1,100ns，p99 2,600ns，max 227,300ns；是已取得片段分布，不是完整B分布 |
| 片段CPU增量 | 30,569個相鄰增量中30,550個為0、19個為正；19個全為15,625,000ns＝15.625ms |
| 宣告解析度 | wall及CPU metadata換算皆100ns；宣告值不能代替觀察到的推進量或能力驗收 |
| 尚未執行 | 第二、三輪與10次sleep全部null；sleep呼叫0次，無補零／省略槽位 |
| 保存 | raw 9,226,243 bytes、outcome 9,226,969 bytes；均在私人Git忽略目錄，公開只留descriptor／摘要 |
| 結構與執行錯誤 | 收集errors為空，無primary error；正式停止原因僅bracket max超標 |
| 正式唯讀反查 | source／fake acceptance／reservation／claim／raw／outcome／final／summary相符，沒有重測 |

### 片段診斷與正式結論的差別

保留的V65純判定器會對提供的片段計算q=15,625,000ns，並回傳`cpu_resolution_insufficient`，同時列出輪次／sleep未完成等原因。這是**提供記錄的診斷值**。V66事先固定只有完整0.5秒輪、且正增量數足夠才可據該輪p95正式提前判不足；本輪在0.302秒即因bracket停止，因此正式collector結論維持**未確認**，不能把partial q冒充完整三輪q或時鐘硬體精度。

已觀察片段再次出現15.625ms跳值，但這輪沒有完成三輪及sleep對照，仍不能宣稱1ms細分能力已通過。CPU零增量不代表沒有運算，wall−CPU也不能直接等同等待。V46暫不採用；本次沒有任何V39／V46速度比較或32／33新查詢。

[正式結果收據](../reports/stage12/retailrocket_session_knn_v67_clock_result_20261116.json)。後續若繼續，先對既有證據整理目前可辨識的範圍及替代觀測限制；新增時鐘方案／量測需另訂規格與授權，不使用本輪已用完的一次性額度。

獨立反讀完成：163個唯一檔案描述、已發布407461a／reservation／claim／raw／outcome／summary一致；從30,570組raw逐項重算全部分位數、正／零增量及唯一末點bracket超標，control與stamp時間順序、保存prefix、固定缺失槽位及整關deadline均相符。全程只讀既有資料，沒有import專案模組、重新讀時鐘或重跑測試／B。[獨立B反讀收據](../reports/stage12/retailrocket_session_knn_v67_clock_independent_B_audit_20261116.json)。
