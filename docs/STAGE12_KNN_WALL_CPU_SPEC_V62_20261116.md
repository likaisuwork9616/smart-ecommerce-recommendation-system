# Stage 12｜V62 同邊界 wall／CPU 計時與開銷驗收規格

**本輪只封存規格，尚未實作或執行驗收、校準、固定 48 筆重測。** 工具是否足夠精細、實際開銷與運算／非 CPU 差額目前均未知。維持暫不採用 V46；保留測試 locked。

## 問題與範圍

[V61](STAGE12_KNN_CONTAINED_LOAD_V61_20261116.md) 已完成七粗階段的完整內含區間負載比較，但所選區間平均不代表完整階段平均，也沒有序位 32／33 的同起訖 CPU。下一個工具的目的，是對同一段程式保存 wall 與執行查詢之執行緒 CPU；**不是把 wall−CPU 直接命名為等待**。

先處理原固定 48 筆的 query 邊界與 ranking 七分項，全部 48 筆均使用相同觀測方式。32／33 的正重疊與投票為事先指定重點，其餘 46 筆保留作同次背景；不因歷史時間大小只對兩筆插探針。V60 七粗階段與完整入口繼續保留原 wall／背景負載，不在第一版新增其逐階段 thread CPU，不宣稱完成整入口 CPU 拆帳。

固定 48 筆是已曝光 validation 工程樣本。重新執行仍是同身分的工程重測，不是新樣本、訓練成績、完整 validation 或最終保留測試。

## 現有接入與邊界

| 來源 | 本版必須保留的行為 |
| --- | --- |
| [V47 冷入口](../scripts/retailrocket_session_knn_cold_v47.py)、[V39 adapter](../scripts/retailrocket_session_knn_typed_adapter_v39.py) | V39／V46 只在既有 decoder 候選接入不同；query 都沿 V39／C1 入口，保持 model、48 筆身分／順序及新 context |
| [V27 make_verifier](../scripts/retailrocket_session_knn_reuse_v27.py)、[V24 SetupClock](../scripts/retailrocket_session_knn_sources_v24.py) | 呼叫專屬 clone／時鐘相依注入，保留 setup envelope、pool.finish／invalidate、既有例外與清理；不得全域 monkeypatch |
| [pair_v4.verify_selected](../scripts/retailrocket_session_knn_pair_v4.py) | query 從 CSV row 已 yield 後開始，到 observations 建置中的原結束讀錶；不含下一筆 CSV 取列，也不是純 ranking |
| [sql_v4.predict](../scripts/retailrocket_session_knn_sql_v4.py) | 起點加七個共享 mark，保留原 SQL、lazy cursor、watch、輸出與工作量；不加每列 execute／next 探針，不改用 V7 profile |
| [V20 診斷](../scripts/retailrocket_session_knn_diagnostics_v20.py) | 可參照有號差與語義驗收，但不能直接啟用 V20 D：它另有逐列代理；其兩次讀錶也不是原子同步 |

入口保存的 `mode='baseline'` 是 V22 入口標籤，不等於 `pair_v4` 的 `baseline=True`。現有 V27 呼叫採 pair_v4 預設 `baseline=False`，仍是 sql_v4 的七分項。新工具須以來源綁定與實際呼叫鏈證明這點。

每筆 query 原有七點固定為 `query_start → rank_start → rank_end → verification_end → append_start → append_end → query_end`。保存 query、verification、rank、append 各自同邊界 wall／CPU；rank 包含於 verification，append 可包含 commit，不把父子加總。另存 verification／append 間及 append／query 尾端等未分項差額，名稱為「未分項」，不稱等待。

ranking 七段依序為 `history_and_temp_setup`、`sql_positive_overlaps`、`neighbor_pool_sha`、`exact_neighbor_selection`、`sql_selected_votes_and_accumulation`、`top_ten_and_zero_fill`、`prediction_output`。正重疊包含 SQL、Python 建池、驗證與 watch；投票包含權重、TEMP 插入、SQL 取列、累加、驗證與 watch，不能稱純 SQL／純累加時間。

fresh 且全部 48 筆成功時，pair_v4 原有 **341 個時鐘呼叫點＝3＋7×48＋2**，sql_v4 有 **384 個＝8×48**。這是各自原時鐘呼叫點，總計 725 個，不含 Observation／entry／budget 內其他既有計時。query 標記與七分項至少各有 336／384 筆原始 stamp；setup／tail 五點仍保留識別。中途例外、skip、resume 不得硬套成功時索引或補齊成完成。

## 同邊界讀錶契約

主時鐘固定為 `time.perf_counter_ns()` 與 `time.thread_time_ns()`；不用 `process_time` 或 telemetry 的程序 CPU 代替查詢執行緒 CPU。每個原時鐘點使用同一呼叫的下列順序：

```text
w_before = perf_counter_ns()
cpu      = thread_time_ns()
w_after  = perf_counter_ns()
```

三值皆保存原始整數；執行緒身分在邊界前後核對，記錄配置／寫入 buffer 在三次讀值之後。回傳 `w_before / 1e9` 供原 float wall 欄位使用；診斷整數欄位另存，不能由 float 秒值乘回 ns。首次 setup 的 scope 開啟及第三點的 scope 關閉仍照原位置，不能把 SetupClock 的其他工作塞進三次讀錶中間。原程序操作的次數、順序、錯誤與完整輸出保持一致，時間值本身無須等於未插入觀測的版本。

對起點 a、終點 b，固定保存：

| 欄位 | 定義與用途 |
| --- | --- |
| `wall_ns` | `b.w_before − a.w_before`；與原呼叫點對齊的主 wall，不用中點假設 |
| `thread_cpu_ns` | `b.cpu − a.cpu`；必須是同一執行緒 |
| `wall_minus_thread_cpu_ns` | `wall_ns − thread_cpu_ns`，原樣保留正、零、負值 |
| `start/end_bracket_ns` | 各自 `w_after − w_before`；顯示非同時讀值的窗口 |
| `wall_inner_ns`／`wall_outer_ns` | `b.w_before − a.w_after`／`b.w_after − a.w_before` |
| `residual_inner_ns`／`residual_outer_ns` | 上述 inner／outer 減同一 `thread_cpu_ns`，只是讀值時序敏感度 |

同一邏輯邊界不等於兩個 API 原子同步。inner／outer 只描述 CPU 呼叫所在的 wall 夾取範圍；**不含 CPU 記帳量化、API 內部更新延遲或排程的誤差保證，不能當真實等待的信賴區間**。不把夾取中點當共同時刻，不以負值補零，也不以空探針平均成本扣成「淨時間」。

相鄰 ranking 子段共用同一份 stamp，不能在前段結束、後段開始各讀一組再假裝相鄰。七段 wall／CPU 分別望遠鏡加總回其八個 mark 的首尾差；它們不必等於外層 rank（尚有 wrapper、初始化、return 等）。只能扣同層互不重疊子段，保留原父層與未分項差額。marker 配置、buffer 寫入與 dispatch 的成本會落入相鄰或父層 span，全部保留。

## 先固定辨識尺度與失敗狀態

本規格新訂 **1 ms 為希望辨識的差值尺度**，不是統計顯著門檻，也不是已達成能力。為避免把 CPU 的粗跳值當成精細時間，先要求實際觀測的 CPU 推進量與邊界讀取窗口足夠小；通過仍不保證能解釋 1 ms 因果效果。

[V20 的實際紀錄](STAGE12_KNN_DIAGNOSTICS_V20_20261106.md) 已出現 API 宣告 100 ns，非零 CPU 增量卻為 **15.625 ms 的倍數**。這是歷史觀察，不當成目前機器的新校準結果；也不能因為名稱有 `_ns` 或短 span CPU 為零就宣稱低開銷／沒有運算。

| 狀態 | 固定處置 |
| --- | --- |
| 結構或語義不合 | `rejected_structure`，保留失敗證據；不得進下一關 |
| 缺時鐘、量化太粗、取樣不足 | `clock_capability_unconfirmed` 或 `cpu_resolution_insufficient`；停止目標分項判讀，不改成程序 CPU，不放寬尺度救結果 |
| 配對擾動超過預算、順序差或波動太大 | `perturbation_not_accepted`；不能聲稱純觀測成本已量清楚，不刪慢值、補跑至通過 |
| 校準／人工驗收通過 | 只代表可進下一個規定關卡；不代表真實 48 筆擾動已通過或 V46 可採用 |
| 真實同臂 O／D 關卡通過 | 可發布本窗口的診斷描述；仍不把 residual 稱為 I/O／GIL／排程／外部程序等待 |

## 分關驗收（全部待執行）

所有門檻是本輪事先固定的工程預算，不是歷史結果或業界標準。各階段按序執行，前一關未通過就不啟動後一關；每關需先封存方法、測試、來源與配置，再執行並保留全部結果。

### A｜假時鐘與語義驗收

以下 16 類是必要驗收項目，**不是已通過 16 項測試**；實作時可分成更多測試，不可跳過或以真實模型代替合成驗收。

1. 三次讀值的固定順序、body 只執行一次，原 wall 回傳使用 w_before。
2. 不等寬 bracket、inner／outer 與有號 residual 精確重算。
3. 大整數 ns 不經 float 往返；零 CPU 增量合法但不解讀成零運算。
4. CPU 大於 wall 時保留負 residual；wall 或 CPU 倒退則拒絕。
5. 起訖缺漏、重複、倒序、型別錯誤／NaN／bool 偽裝整數均拒絕。
6. 跨執行緒、錯誤 parent、子段超界、同層重疊均拒絕。
7. 相鄰七段共用 stamp，wall 與 CPU 分別守恆；父子不重複加總。
8. query 七點、ranking 八點、原序位與完整 fresh 48 筆呼叫數可核對。
9. setup／tail、return 與 wrapper 剩餘時間不偽裝成 query 子段。
10. skip／resume／錯誤路徑不套用成功索引，部分結果明示 incomplete。
11. 原 exception／fault 與 cleanup 保留；timer 再失敗不能覆蓋原例外。
12. 未插入診斷的 O 不呼叫新增逐邊界 CPU／bracket 探針、不配置診斷事件；兩模式共同的外層 wall 與對稱能力校準除外，成本另列。
13. 完整科學 payload、工作量與 checkpoint bytes 一致；不只比 top10 或 digest。
14. SQL 字串／次數、lazy cursor／EOF、watch／fault 順序保持一致，不預先 fetchall。
15. 呼叫專屬 clone 不污染原 namespace，V39／V46 兩臂僅保留原候選差異。
16. 開銷統計、百分位、配對順序、缺值與未通過狀態可由人工 fixture 精確重算。

### B｜本機時鐘能力，先於任何真實 48 筆

在同一 worker 執行緒記錄 Python／OS、兩種 clock 的 implementation／monotonic／adjustable／resolution、身分與本輪來源。兩時鐘須可用、宣告 monotonic 且不可調整；實際讀值亦不得倒退。不能用 clock metadata 取代實測。

- 固定三輪各 **0.5 秒 perf_counter 經過時間**的同執行緒忙迴圈連續讀成組 stamp；不是 0.5 秒 CPU 時間。每輪上限 1,000,000 組、整關上限 30 秒。達樣本上限或期限而未完成即能力未確認，不能丟掉超限部分再宣稱完成。
- 每輪保存 CPU 相鄰零增量比例、非零增量的 count／min／p50／p95／max，wall 相鄰增量及 bracket 分布。每輪至少 10 個正 CPU 增量；不以最小值或 GCD 當真實解析度。
- 保守篩檢量 `q = max(宣告 CPU resolution 換算 ns 向上取整, 各輪正 CPU 增量 p95)`，要求 **q ≤100,000 ns（0.1 ms）**。這是觀測到的推進量篩檢，不是已證明的時鐘誤差上界；未通過只表示本窗不支持目標尺度，不能單憑 q 判定硬體刻度。
- 全部 bracket 的 **p99 ≤50,000 ns、max ≤100,000 ns**。另外固定十次 `sleep(0.05)` 對照，保存實際 wall／CPU；每次 wall 至少 40 ms，CPU／wall 比例 p90 ≤0.10。sleep 可能超時，不能以要求的 50 ms 代替實際 wall；忙迴圈只要求 CPU 有推進，不要求 CPU／wall 必須接近 1。
- CPU 量化過粗即停止；不能把多次 32／33 平均後假裝單次達標，不能自動改用 cycle counter 換算秒或切換時鐘。

### C｜人工工作量的觀測開銷

先各取 **4,097 次空 stamp**與**4,097 次完整記錄路徑**，記錄外層 wall、實際新增 clock 呼叫、配置／append／dispatch 成本分布。空 stamp CPU 常為零不算零開銷證據；這些數字只作診斷，不乘上次數扣除正式結果。

固定兩種人工工作量：每個入口有 48 個合成 query，每筆模擬 query 七點及 ranking 八點，另於整個入口保留原 setup／tail 五點；其中 ranking 的七個段落各執行（a）每段重設 seed=1、32-bit LCG `x=(1664525*x+1013904223) mod 2^32` 共 4,096 次，或（b）一次 `sleep(0.001)`。保留完整 trace／checksum；沒有模型、SQL、真實查詢或資料來源讀取。

每種工作量各 O／D 暖機一次，另做 **八對**，順序固定 `OD, DO, OD, DO, OD, DO, OD, DO`。O 是原讀錶／原紀錄；D 是完整新探針／buffer／dispatch。共同外層 wall 必須涵蓋配置、執行與診斷資料序列化／保存；O 保留原輸出保存，D 的新增輸出成本不得藏在外層計時外。各次新 namespace，全部循序，不改 GC／priority／affinity／快取設定。

每種工作量整關上限 120 秒，保留所有配對、暖機與順序分層。每對先算 `d=D−O`、`r=abs(d)/O`（O 必須 >0）；**r 中位數 ≤2%、最大值 ≤5%** 才通過。這是對該人工 workload 的整體擾動預算，含環境波動，不能宣稱純計時器成本。正負不可抵銷後通過；不依結果改工作量迴圈數、挑配對或追加。

所有分位數固定 nearest-rank：排序後第 `ceil(p*n)` 值（1-based）；median 仍採標準中位數，偶數取中央兩值平均。原值、每對差、有效數／缺值數及最大值都保存；缺失不補零、不跨失敗臂重新配對。

### D｜真實同臂的入口擾動關卡（未啟動）

人工通過後仍須另外安排真實入口 O／D，不能把人工結果推廣到原模型或 V39／V46 效果。執行前再估時並依當次工作指示安排；本規格沒有啟動或預約量測。

固定採同一份 model、原固定 48 筆、全新 context／checkpoint，兩種 decoder 各自比較 O／D：`(V39,O)` 對 `(V39,D)`，`(V46,O)` 對 `(V46,D)`，不把 O／D 混成 V39／V46 差。正式六個 block：奇數 block 先 V39 再 V46且各為 OD；偶數先 V46 再 V39且各為 DO。每臂各六對，合計 12 對、24 個正式入口；前置暖機依 `(V39,O),(V46,D),(V46,O),(V39,D)` 各一次，共 **28 個入口、1,344 次同身分工程查詢**，暖機另列。

兩模式沿用既有 200 ms 目標間隔 collector，先啟動 sampler 並完成首筆 capture，再開共同的 `instrumentation_entry` 外層 wall；此外層包含診斷 buffer 配置、run.total、新增診斷序列化／保存／必要 flush 與 buffer 清理。外層結束後才停止 sampler、完成末筆 capture，負載首尾須覆蓋此外層。sampler 生命週期／原始負載保存、程序啟動、來源準備、pool 建立與 close 留在外層以外，另記範圍；原 pool.finish 仍在 run.total 內，不能移動。O 沒有診斷 buffer／新輸出，其餘共同操作與位置相同。

「原完整入口」門檻固定使用 V47 的 `accounting.costs.entry_seconds`（源自 `entry.json.seconds`）。這個值在寫 entry.json 前讀錶；`run.total` 則包住原 _run 及其輸出，兩者及 `entry_span` 原值都另存，不能互換。完整保存每對 instrumentation_entry 與原入口的差，以及 query／正重疊／投票原 wall 的擾動；新增工具自身的 CPU 不從父層扣掉。instrumentation_entry 不是程序冷啟動至退出的全生命週期。

每個 decoder 的 instrumentation_entry、原完整入口及 48 筆 query wall 合計，三者各按六對檢查 `abs(D−O)/O` 中位數 ≤2%、最大值 ≤5%。對 32／33×正重疊／投票四組，另要求各 decoder 的六對 **abs(D−O) 中位數 ≤0.1 ms、最大值 ≤0.5 ms**；任一不符即本窗不能接受 1 ms 尺度的分項擾動，保留全部，不以入口平均掩蓋目標局部干擾。

每個 O、D 入口（含暖機）前後都執行完全相同的 B 能力檢查，共 56 次，避免不同前置忙迴圈／sleep 改變配對條件；校準在入口量測外、成本另記，不能只驗首次或只驗 D。任一臂前後校準不通過或事件 bracket 超過 B 的 max 上限，整窗不發布「目標尺度驗收通過」；已完成資料留作受限診斷，不挑合格查詢換算 32／33 結論。完整 48 筆身分、工作量、科學 payload、實體帳本與來源綁定須獨立反讀。沿用 V47／V48 停止與資源保護，未來 request 設窗口上限 1,800 秒（含全部前後校準）；若執行前估時無法容納，須先改版規格，不能邊跑邊延長。

即使 D 通過，也只描述新增窗口的 instrumented 結果，不能回填 V47／V48 的等待原因。若未來評估採用 V46，仍須分開以無新增診斷的完整冷入口配對判定；本輪與上述 O／D 都不構成採用證據。

## 保存、判讀與後續

私人事件至少保存 run／decoder／instrumentation_mode／pair／order、1-based 展示序位與原 0-based subset_ordinal、original_ordinal、key hash、phase／parent／boundary id、執行緒身分、三個整數時鐘、completed／error、各差值／品質標記與 clock metadata。程序／執行緒原身分只留 Git 忽略路徑。事件預先準備必要標籤與容量，正式區段內只寫記憶體；輸出保存在外層入口時間內，缺漏與例外留存、不可覆寫。

公開收據綁定規格、工具／測試、環境、來源 manifest、配置、原樣本／順序與新證據 bytes／SHA256；聚合報告須保存全部配對與分母、失敗狀態、開銷與解析度結果。不能只發布通過的 query／配對，也不能把 1,344 次重複當成獨立樣本。

wall−thread CPU 只稱**有號殘差**：它可能含非 CPU 經過時間、量化、讀值錯位及工具成本；即使為正，仍不能區分 I/O、鎖、GIL、排程或某背景程序。若某工作轉交其他執行緒，必須另外標示不在當前 CPU 範圍，不能認定其時間全在等待。

| 本輪工作 | 狀態 |
| --- | --- |
| 程式邊界／既有量化限制盤點 | 完成唯讀核對，未啟動原 runner |
| 同邊界、資料欄位與 A–D 驗收規格 | 已固定；[機器可讀規格](../reports/stage12/retailrocket_session_knn_v62_wall_cpu_specification_20261116.json)保存常數及來源綁定 |
| 工具實作／假時鐘驗收／實機校準 | 尚未開始，沒有測試通過數或開銷實測值 |
| 新增實驗／查詢／解碼／訓練／即時採樣 | 全部 0 |
| 下一步建議 | 先實作最小邊界工具與 A 類合成驗收，再做 B／C；若實際 CPU 刻度不合，停止細項量測，另行評估方法 |

官方語義已對照：Python 將 perf_counter 定義為含 sleep 的經過時間，thread_time 只計目前執行緒 user＋system CPU；`_ns` 改變回傳單位，不能保證實際 ns 解析度。[Python 3.12 time](https://docs.python.org/3.12/library/time.html#time.thread_time_ns)。Windows GetThreadTimes 的 CPU 計數以 100 ns 單位表示，單位本身不是實測精度保證。[Microsoft GetThreadTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getthreadtimes)。上述 API 語義與本規格自訂門檻分開；本機執行時仍須重新保存實際版本與能力。
