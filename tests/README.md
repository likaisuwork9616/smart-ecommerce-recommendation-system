# 測試與驗證

自動測試使用Python標準庫`unittest`，從專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

最近一次完整測試為[完成歷史代表性稽核](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md)的867項全過、165.394秒。其後事件來源查核15項、單日離線交付42項（3.017秒）、[全量日資料契約查核](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract)8項（0.062秒）均已通過。這些是各前輪紀錄，不能合稱本輪完整測試。

前輪[交接清單與驗收範本](../docs/templates/daily_data_handoff/README.md)只檢查文件與空白格式；範本案例不能當成真實資料已驗收。Stage 5可行性、H60資料集、基線契約與合成pipeline驗證保留各輪紀錄。最新[離線最小基線](../docs/STAGE5_REVIEW_OFFLINE_BASELINE.md)分開記合成測試、只讀來源稽核、正式真實資料訓練及凍結分數獨立對帳，不把測試數當作效能。

## 依修改範圍選擇檢查

| 範圍 | 測試內容／入口 |
| --- | --- |
| 特徵與標記 | `test_delay_*features.py`、`test_delay_features.py`；訂單聚合、key、缺值與事件時鐘 |
| 訓練與時間切分 | `test_delay_*training.py`、`test_delay_*validation.py`；成熟答案、同月隔離與query群組 |
| 提醒政策與排名 | `test_delay_alert_policy.py`、`test_delay_calibration_policy.py`及排序測試；完整日分母、取整、ties與未知答案 |
| 實驗與選模 | 各輪`test_*selection.py`及comparison／experiment測試；固定候選、規格與歷史選擇 |
| 診斷與可重現性 | `test_diagnose_*.py`、audit測試；來源綁定、共同漏報身分及分格對帳 |
| 環境與資料庫 | [verify_environment.py](../scripts/verify_environment.py)；此項會讀本機設定與MySQL，與單元測試分開 |

## 本輪Stage 6 RFM輸入盤點

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_feasibility -q
```

20項合成測試全過、0.012秒，涵蓋顧客鍵、明細／付款獨立彙總、精確到分、未知／非法與負金額、缺流、T邊界與晚送達、不修改輸入及不輸出個體RFM。另59項正式聚合／候選比較通過，來源及候選由獨立CSV／Decimal與pandas計算核對；不加總成單元測試數。沒有執行個體RFM、分群、模型測試、全專案discover或業務成效評估，詳見[Stage 6文件](../docs/STAGE6_RFM_FEASIBILITY.md)。

## 前輪Stage 5模型適用範圍文件

[四欄／三欄模型卡](../docs/STAGE5_MODEL_APPLICABILITY.md)只核對原聚合報告的逐月／macro AP、C、分母與固定門檻混淆數，並查文件連結／JSON格式與既有凍結資產保存。未讀逐筆分數重算指標，未新增或重跑單元／模型測試、訓練、資料集或新資料驗收；這次文件查核不算新效能或未知測試。

## 前輪Stage 5新時間窗交接文件

[交接清單與範本](../docs/templates/review_window_handoff/README.md)只做文件／格式查核：嚴格JSON解析、五個月完整區間及H60日曆界線、15個check_id與三關卡對應、所有實測null及pending_data、Markdown本機連結，另核既有程式／報告及私有證據未改。沒有新增或重跑單元測試、模型、原始資料稽核或真實交接驗收；範本所列案例是未來待執行義務，不能計為通過測試或新資料成績。

## 前輪Stage 5後續時間窗盤點

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_validation_windows tests.test_audit_review_validation_windows -q
```

核心16＋來源／守門12共28項全過、1.477秒，0fit。核原C嚴格邊界、全月H60規劃截止、空月份、重複角色ID去重、metadata不可夾帶review_score／y、缺核准不可補購買日、最大回答時間不能當watermark、Git用途紀錄及來源異動／發布停止。檔案fixture依既有Windows tempfile ACL限制在允許專案.runtime的環境完成，未放寬斷言或跳過。

另618項正式獨立盤點、6.270秒及95項用途核對、0.026秒分列，核25個月、五個待資料時間窗、14個commit及用途限制。原30份私有證據不變；0新評分／y／訓練／效能，不重跑舊模型或全專案discover。見[時間窗文件](../docs/STAGE5_REVIEW_VALIDATION_WINDOWS.md)及[驗證](../reports/stage5/review_validation_window_verification.json)。

## 前輪Stage 5成熟先驗與時間漂移稽核

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_mature_prior_audit tests.test_audit_review_mature_prior -q
```

核心19＋來源／守門10共29項全過、1.290秒，0fit。核H60恰60天、早答未成熟、品質狀態覆蓋、未知不填0、近期成熟窗口／月份與時齡邊界、query改動不影響先驗、跨fit不回填，以及來源異動／缺檔／發布停止。檔案fixture依既有Windows tempfile ACL限制，在允許專案.runtime存取的環境執行，未放寬斷言或跳過。

獨立7,134項正式比較、4.850秒另列，核原核准名冊與12角色289,973列、先驗／覆蓋／窗口與跨fit轉換；原27份私有證據不變。不讀分數值、係數，不fit／預測／校準／更新參數，也不重跑全專案或舊模型測試。詳見[文件](../docs/STAGE5_REVIEW_MATURE_PRIOR_AUDIT.md)與[驗證](../reports/stage5/review_mature_prior_verification.json)。

## 前輪Stage 5雙臂只讀診斷

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_ablation_diagnostics tests.test_diagnose_review_ablation -q
```

核心16＋來源／守門12共28項全過、0.740秒，沒有fit。手算核對反向排序、平均rank平手、canonical名次、全未知null、全月損失分母及等待邊界；來源測試核payload／parent／guard異動、缺檔、失敗收據、未知檔與發布後來源異動撤回。首次沙箱有19個暫存ACL setup／cleanup錯誤，相同測試於允許的檔案環境全過，未放寬斷言或跳過。

正式資料另10,389項獨立比較、4.917秒，核18組機率、12組排名、六組支援及固定切片；不合併為單元測試數。診斷0fit／transform／predict／選C，原24份私有證據不變。見[診斷文件](../docs/STAGE5_REVIEW_ABLATION_DIAGNOSTICS.md)及[驗證報告](../reports/stage5/review_ablation_diagnostic_verification.json)。未重跑舊模型測試或全專案discover。

## 前輪Stage 5真實消融交付驗收

本輪沒有修改凍結程式或重跑合成測試。一次真實執行實際完成9次內層＋3次外層fit，另以只讀程式核對完整角色、每臂18區塊108,744列的ID／truth、選C、指標與私有manifest。這是實際產物驗收，與下列前輪74項合成測試分列；詳見[實驗文件](../docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)及[聚合驗收](../reports/stage5/review_month_ablation_training_acceptance.json)。

## 前輪Stage 5三欄正式入口與私有writer

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_run_review_month_ablation tests.test_review_month_ablation_training tests.test_review_month_ablation_artifacts -q
```

入口20＋訓練控制32＋writer22共74項全過，沒有失敗、錯誤、跳過或預期失敗。正式合成驗證階段165.964秒（不含此前來源載入，含測試及發布）。實際sklearn fit共37次且均32維：三個完整試跑各9＋3次，另1次測預測失敗收據；其他分支使用替身。涵蓋獨立選C、七欄query遮罩、未知列、fit時鐘與支援、完整18區塊配對、來源變動、產物／公開結果接受後被改動、精確反讀、失敗回撤及禁止重播。真實fit與新效能均0。

正式版本與測試名單見[合成報告](../reports/stage5/review_month_ablation_dispatcher_verification.json)，整合CLI另需原本機來源先`--specification-only`再`--verify-synthetic`；操作及界線見[入口驗收](../docs/STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md)。該輪沒有重跑全專案discover，下列歷史紀錄各自保留。現有training_v1已占用，整合CLI不可當成發布後驗收重播。

## 前輪Stage 5三欄執行準備與配對守門

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_month_ablation_sources tests.test_review_month_ablation_pairing tests.test_prepare_review_month_ablation -q
```

來源18＋配對25＋準備CLI16共59項新測試全過，43.555秒，無失敗、錯誤或跳過。涵蓋來源／私有guard／實作證明改版拒收、完整角色與七欄遮罩、防禦性副本、18區塊完整同ID與truth、未知／機率、外層不同C、禁止模型／效能呼叫、輸出占用／碰撞／越界、全部預檢、晚期變動回滾及同版重跑。全部只用合成metadata／分數或暫存檔，沒有fit、predict或效能計算。

正式來源／分數獨立核對另有1,304,928個metadata欄值一致，以及21項私有I/O對抗案例；不加總成單元測試或效能結果。詳見[執行準備文件](../docs/STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md)。本輪沒有重跑下列合成fit組或全專案discover，前輪紀錄保持分列。

## 前輪Stage 5三欄實作與洩漏驗證

```powershell
.\.venv\Scripts\python.exe scripts\verify_review_month_ablation_pipeline.py
.\.venv\Scripts\python.exe -m unittest tests.test_review_dataset_contract tests.test_review_baseline_contract tests.test_review_month_ablation_contract -q
```

第一行跑新三欄43項＋原四欄32項共75項，全部通過；正式測試4.065秒、CLI共5.815秒。涵蓋32維、保留欄位／前處理與44維對照一致、月份不變性、train-only scaler、未知排除、H60／fit邊界、完整名冊、query未來標籤隔離、候選／外層獨立、失敗清除及機率檢查。會實際fit合成模型，不讀Olist資料、不計效能。

第二行23＋20＋14共57項契約回歸全過，4.555秒。首次受限環境有6項暫存目錄ACL錯誤；允許相同本機資源後原樣重跑通過，沒有跳過或改舊斷言。兩組合計132項，沒有執行全專案discover。另194項跨3個fold內／外層獨立合成檢查及31項CLI對抗案例通過，與單元測試分列。詳見[實作文件](../docs/STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md)及[正式報告](../reports/stage5/review_month_ablation_pipeline_verification.json)。

## 前輪Stage 5月份消融契約

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_month_ablation_contract -q
```

[月份消融規格](../docs/STAGE5_REVIEW_MONTH_ABLATION_SPEC.md)新增14項契約測試全過、0.500秒。驗精確五處月份結構差異、32維、其他改動拒收、三欄獨立選C與null配對、來源／私有guard、完整輸出預檢、同版重跑及晚期來源失配撤回；不匯入sklearn，不建X或fit。發布前修正與已載入套件的測試隔離，另以模組替身重驗3個受影響測試，全過、0.200秒，沒有實際匯入sklearn。另有508項獨立來源／逐ID角色比較通過，未解析分數CSV或計效能。

本輪只跑此新測試組；上方discover包含舊合成fit，本輪未執行，不宣稱全專案回歸。

## 前輪Stage 5只讀診斷

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_score_diagnostics tests.test_review_score_diagnostic_runner -q
```

[凍結分數診斷](../docs/STAGE5_REVIEW_SCORE_DIAGNOSTICS.md)新增核心32項及runner 11項，共43項全過、5.011秒。只用合成資料驗分母／未知、固定bins、linear分位數、ddof=0、四欄支援、完整metadata、來源／規格拒收與只讀發布；模型呼叫負例在執行前被拒絕，沒有實際fit／transform／predict。本輪沒有重跑下列會fit合成模型的舊測試，亦不宣稱全專案回歸。

獨立合成10情境15,400葉節點、來源對抗36項與正式聚合8,218比較另記私有證明，不加總為單元測試數。正式對帳直接讀原凍結分數、membership及事件時鐘，不重播模型。原42份凍結資產bytes不變。

## 前輪Stage 5離線基線入口

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_sources tests.test_review_baseline_training -q
```

來源測試只用合成metadata與暫存來源，核對祖先SHA／私有guard、完整同ID角色、未知與七個未來欄遮罩及防禦性副本。訓練入口測試核對手算AP／ROC／Brier／logloss／0.5邊界、未知不計分、單類及無known的null、三C平手、每次fresh fit與錯誤停止、全query出分、float64帳本反讀、輸出碰撞及重跑拒收。測試不讀真實Olist來fit；實際真實基線由獨立CLI執行，結果見實驗文件。

本輪新增來源12項＋訓練／評估21項全過；連同既有四組，下面六組共120項全過、19.581秒，無失敗、錯誤或跳過。另有來源65項、手算指標300項及正式分數／fit診斷1,096項獨立比較；後者沒有重fit或重預測，不加總成單元測試數。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_prediction_feasibility tests.test_review_dataset_contract tests.test_review_baseline_contract tests.test_review_baseline_pipeline tests.test_review_baseline_sources tests.test_review_baseline_training -q
```

## 前輪Stage 5builder／pipeline洩漏測試

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_pipeline -q
.\.venv\Scripts\python.exe scripts\verify_review_pipeline.py
```

本組以手算四欄／44維、未知訓練outlier、query未來標籤改動與極端值、時間嚴格邊界、獨立名冊共同刪單、各fit隔離及失敗後狀態核對實際資料流。固定類別、ddof=0、零變異、schema／值域、參數、收斂警告及機率異常都有拒收或一致性檢查。合成係數／機率只用來驗正確性，不算AP等模型表現；詳見[實作與驗證](../docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md)。

該輪32項全過（正式CLI測試1.855秒）；合併下列Stage 5既有三組，87項全過、5.821秒。另有300項獨立合成檢查及六種CLI拒收案例；這些不加總成單元測試或真實資料成績。沒有重跑全專案867項模型測試。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_prediction_feasibility tests.test_review_dataset_contract tests.test_review_baseline_contract tests.test_review_baseline_pipeline -q
```

前輪Stage 5最小基線契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_contract -q
```

前輪20項全過、0.285秒，涵蓋固定政策、角色／事件截止、未知、來源／私有guard、輸出預檢及API AST。該輪不建立X、前處理或模型，不執行選參或指標；嚴格JSON沿用舊資料集I/O helper。原始metadata獨立對帳見[基線規格](../docs/STAGE5_REVIEW_BASELINE_SPEC.md)，不與本輪合成fit混為真實訓練成績。

前輪Stage 5凍結資料集與逐fit資格：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_dataset_contract -q
```

本組23項涵蓋H端點／成熟嚴格邊界、早答不改挑、同分平手、未知不補0、未來／超H壞評論不得污染、不可定位回答的靜態品質隔離、每個I／F重建、內層最近完整成熟月、完整候選及重疊、nullable CSV逐值反讀、來源SHA／嚴格JSON／不可覆寫、Git忽略路徑與公私輸出全部預檢、實際規格bytes綁定。測試均無模型擬合；原始資料的獨立逐值對帳另見[資料集文件](../docs/STAGE5_REVIEW_DATASET_SPEC.md)。

前輪Stage 5可行性盤點邊界檢查：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_prediction_feasibility -q
```

本組12項涵蓋無評論未知、先首答後查t、早答不改挑晚答、平手／壞時鐘／鍵隔離、score範圍、取消單保留、May截止、回答嚴格早於fit、來源SHA變更及報告不可覆寫。用合成資料核對盤點規則，沒有擬合模型或產生效能成績。

前輪全量日來源盤點的守門檢查：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_audit_daily_data_contract -q
```

本組8項涵蓋嚴格JSON、來源SHA變更、不可覆寫、核准日界、缺失／無效／逆序時間、ID唯一，以及同N錯ID／時鐘／版本與跨組名冊不同。測試只檢查盤點程式的拒收與對帳行為；不代表上游全量日資料或未來live batch契約已通過。

前輪單日離線交付契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_delay_daily_delivery_acceptance tests.test_accept_frozen_daily_delivery -q
```

本組42項（核心25＋CLI／來源／輸出17）涵蓋完整20組、同N錯ID、漏單／重複、時間與版本、finite分數、同分ID升序、9／10／19張的向下取整、未知答案不預濾、原旗標／舊邊界、來源SHA、Git忽略路徑、整批拒覆寫與CSV逐值反讀。合成資料沒有擬合模型，不是新增實驗效能。

來源盤點的時鐘與證據契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_audit_event_source_availability -q
```

本組15項涵蓋截止日、無效／逆序時間、承諾日精度、最終status不能證明取得時間、未知捕獲率保留缺失、schema／時區變更需重驗、ID唯一、來源SHA改變、不可覆寫報告、DB逐表對帳及私有證據路徑不公開。

前輪的歷史母體、固定條件比例與重現契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_delay_history_representativeness tests.test_delay_representation_profiles tests.test_audit_completed_history_representativeness -q
```

本組共37項，涵蓋核准／送達／交運邊界、未知key與零歷史、承諾無效、原窗口橋接、原欄還原、組成權重、五種子、稀疏與三精度篩查，以及完整phase／screen的JSON roundtrip重現。

前一輪的成熟訊號分層比較亦可獨立執行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_delay_conditional_mature_signals tests.test_diagnose_conditional_mature_signals -q
```

此組包含31項合成測試，涵蓋組成反轉、漏報筆數與配對數權重、承諾精度、稀疏覆蓋、五種子身分、ties及跨月篩查。測試中的小型模型擬合是合成資料檢查，不是重新訓練研究模型或取得新回測成績。

## 其他檢查

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\verify_environment.py
```

第二個指令需具備本機MySQL與連線設定；`--execute-notebooks`只執行01–03的副本，詳見[Notebook導覽](../notebooks/README.md)。原始資料／模型／逐筆分數的獨立重算不是單元測試，應依各輪文件執行並將紀錄留在`.runtime/`。

Windows受限執行環境若封鎖暫存目錄或本機執行緒管線，完整測試可能因權限失敗；應在允許這些本機資源的環境以同一程式重跑，不以跳過測試或改動斷言取代。純文件整理則檢查連結、Notebook結構、來源與報告SHA，不需要重跑訓練入口。
