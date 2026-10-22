# 程式與操作入口

所有命令都從專案根目錄執行，使用 `.venv` 的 Python。環境安裝與資料庫設定見[本機建置](../docs/LOCAL_SETUP.md)，目前結論見[專案首頁](../README.md)，報告對應見[報告索引](../reports/README.md)。

## 先選擇要做的工作

| 工作 | 入口 | 執行前提與產物 |
| --- | --- | --- |
| 驗收Stage 6實際RFM資料集 | [build_rfm_dataset.py](build_rfm_dataset.py)、[純builder](rfm_dataset_builder.py)、[私有writer](rfm_dataset_artifacts.py) | 一次建置已完成，現有bundle只用--verify；需原來源與guard，勿刪檔重播；不分群／訓練 |
| 凍結Stage 6 RFM資料集契約 | [freeze_rfm_dataset_spec.py](freeze_rfm_dataset_spec.py) | 先--specification-only再核母體／隔離／狀態聚合；不建立個體RFM、builder或分群 |
| 盤點Stage 6 RFM輸入支援 | [audit_rfm_feasibility.py](audit_rfm_feasibility.py) | 先--specification-only再只讀四CSV的鍵／時鐘／金額與候選窗口；不建個體RFM／分群，不讀評論或模型分數 |
| 盤點Stage 5後續時間窗與用途 | [audit_review_validation_windows.py](audit_review_validation_windows.py)、[metadata核心](review_validation_windows.py) | 先--specification-only凍結歷史與盤點，再核ID／時鐘；不讀新評分、不建y或訓練 |
| 稽核Stage 5逐fit成熟先驗與漂移 | [audit_review_mature_prior.py](audit_review_mature_prior.py)、[純統計核心](review_mature_prior_audit.py) | 先--specification-only再稽核原H60完整角色；不讀分數值、不fit或修正參數 |
| 只讀Stage 5雙臂機率／排序／支援 | [diagnose_review_ablation.py](diagnose_review_ablation.py)、[統計核心](review_ablation_diagnostics.py) | 先--specification-only，再讀兩臂成功產物與完整角色；18組配對及12組排序；模型呼叫及重新選C拒收 |
| Stage 5三欄正式入口與私有交付 | [run_review_month_ablation.py](run_review_month_ablation.py)、[訓練控制](review_month_ablation_training.py)、[私有writer](review_month_ablation_artifacts.py) | 無參數只顯示說明；一次--train已完成，training_v1已占用，勿重播；[結果與只讀驗收](../docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)，四欄沿用原分數 |
| 前輪Stage 5三欄消融來源與配對準備 | [prepare_review_month_ablation.py](prepare_review_month_ablation.py)、[review_month_ablation_sources.py](review_month_ablation_sources.py)、[review_month_ablation_pairing.py](review_month_ablation_pairing.py) | 需原私有證據；當時凍結政策／輸出版本，再核12角色與四欄18區塊，沒有訓練參數；現有產物已完成，勿重跑準備流程 |
| 驗證Stage 5三欄消融與四欄對照 | [verify_review_month_ablation_pipeline.py](verify_review_month_ablation_pipeline.py)、[review_month_ablation_pipeline.py](review_month_ablation_pipeline.py) | 只以合成fixture驗三欄32維／舊四欄44維；75項測試及35公開來源綁定，不讀真實CSV或私有分數 |
| 凍結Stage 5月份消融規格 | [freeze_review_month_ablation.py](freeze_review_month_ablation.py) | 先--specification-only，再只核metadata；保留原來源、只刪purchase_month契約；不實作三欄模型、不fit或解析分數 |
| 只讀Stage 5凍結分數做支援診斷 | [diagnose_review_scores.py](diagnose_review_scores.py)、[review_score_diagnostics.py](review_score_diagnostics.py) | 需原私有分數／角色／收據；先--specification-only固定診斷範圍，再核來源、統計分布；禁止模型fit／transform／predict，不補訓練 |
| 執行Stage 5四欄離線最小基線 | [run_review_baseline.py](run_review_baseline.py) | 需原資料／H60私有bundle／原收據／guard；先凍結新執行規格，正式入口會12次fit並做開發回測，已有結果則fit前拒收 |
| 驗證四欄builder與train-only pipeline | [verify_review_pipeline.py](verify_review_pipeline.py)、[review_baseline_pipeline.py](review_baseline_pipeline.py) | 僅合成fixture，無需原CSV／私有bundle；會fit測試用scaler／Logistic並檢查洩漏，不執行真實訓練 |
| 核對Stage 5最小基線規格 | [audit_review_baseline_contract.py](audit_review_baseline_contract.py) | 先--specification-only；只核來源、事件時鐘、未知／fit角色與固定基線政策，不建X或fit |
| 凍結Stage 5訂單級首答資料集 | [freeze_review_dataset.py](freeze_review_dataset.py) | 先--specification-only，再執行稽核；H60、多評論、未知與內外層時鐘，私有標籤／切分留.runtime，不建X或訓練 |
| 重現Stage 5評論預測可行性盤點 | [audit_review_prediction_feasibility.py](audit_review_prediction_feasibility.py) | 需原九CSV與既有來源報告；只查標籤／鍵／時鐘／候選欄位，不建特徵或訓練模型 |
| 檢查套件、MySQL及資料表 | [verify_environment.py](verify_environment.py) | 使用本機資料庫設定；摘要存 `.runtime/verification/summary.json` |
| 開啟教學分析 | [start_jupyter.ps1](start_jupyter.ps1) | 先啟動本專案 MySQL，再開啟 `notebooks/`；見[Notebook說明](../notebooks/README.md) |
| 啟停資料庫／開啟GUI | [start_mysql.ps1](start_mysql.ps1)、[stop_mysql.ps1](stop_mysql.ps1)、[start_dbeaver.ps1](start_dbeaver.ps1) | 工具、資料庫、設定與帳密都在本機忽略路徑 |
| 建立新電腦環境／匯入CSV | [setup_local_mysql.py](setup_local_mysql.py)、[load_olist_to_mysql.py](load_olist_to_mysql.py) | 初始化只供新環境；CSV匯入使用 `if_exists="replace"`，會重建同名資料表，操作見建置指南 |
| 載入模型做離線推論 | [predict_delay.py](predict_delay.py) | 需要本機 artifact；支援原版、平衡模式及指定研究模型，操作見[原版說明](../docs/STAGE4_DELAY_PREDICTION.md) |
| 重現單日離線交付驗收 | [accept_frozen_daily_delivery.py](accept_frozen_daily_delivery.py) | 需原始orders、凍結cache／帳本、報告及20份月模型bytes；只核SHA與已有分數，不載模型／預測／訓練 |
| 查全量日資料契約與缺口 | [audit_daily_data_contract.py](audit_daily_data_contract.py) | 只讀九CSV、匯入程式、既有報告；帳本只解析名冊／設定欄，不啟動DB／API |
| 閱讀適用範圍與交付前提 | [模型卡與交付清單](../docs/STAGE4_MODEL_APPLICABILITY.md) | 區分主方案wrapper與160份五種子月版；離線研究可交付，沒有生產日結／通知服務 |
| 閱讀待資料方向 | [事件／承諾版本來源](../docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md) | 新增驗收來源0，先讀查核範圍與資料契約；不需要啟動MySQL或訓練 |
| 重現來源快照 | [audit_event_source_availability.py](audit_event_source_availability.py) | 需要原始九表及當輪忽略路徑內的盤點、DB／官方取得證據；重算聚合，不自行啟服務或連私有API |
| 重現前輪代表性診斷 | [audit_completed_history_representativeness.py](audit_completed_history_representativeness.py) | 需要凍結快取、分數帳本、原始表與受保護來源（含僅驗SHA的模型檔）；不載入模型或新增fit |
| 驗證程式 | [tests/](../tests/README.md) | 測試命令與執行限制另列，執行測試不等於重做研究 |

可先查閱參數；以下命令只顯示說明：

```powershell
.\.venv\Scripts\python.exe scripts\verify_environment.py --help
.\.venv\Scripts\python.exe scripts\predict_delay.py --help
.\.venv\Scripts\python.exe scripts\diagnose_conditional_mature_signals.py --help
.\.venv\Scripts\python.exe scripts\audit_completed_history_representativeness.py --help
.\.venv\Scripts\python.exe scripts\audit_event_source_availability.py --help
.\.venv\Scripts\python.exe scripts\accept_frozen_daily_delivery.py --help
.\.venv\Scripts\python.exe scripts\audit_review_prediction_feasibility.py --help
.\.venv\Scripts\python.exe scripts\freeze_review_dataset.py --help
.\.venv\Scripts\python.exe scripts\audit_review_baseline_contract.py --help
.\.venv\Scripts\python.exe scripts\verify_review_pipeline.py --help
.\.venv\Scripts\python.exe scripts\run_review_baseline.py --help
```

`verify_environment.py --execute-notebooks` 只執行01–03的副本，沒有包含04。`predict_delay.py` 預設使用 `models/olist_delay_model.joblib`；有每日提醒上限的模型必須提供完整每日特徵CSV及 `--complete-daily-batches`，單張訂單不能重現每日10%名額。

`--complete-daily-batches`是呼叫端聲明，無法證明日已封閉或沒有漏單。通用CLI只支援有完整推論契約的artifact；五種子四設定的原始月版缺少必要wrapper欄位，不能直接傳`--model`當作已交付的五種子推論服務。範圍與未驗收部分見模型卡。

## Stage 6本輪RFM builder與私有資料集

```powershell
.\.venv\Scripts\python.exe scripts\build_rfm_dataset.py --verify
```

已依20份來源規格完成一次真實建置；兩份16欄私有CSV及manifest留`.runtime/stage6_rfm_dataset_v1/`，三檔guard在`.runtime/stage6_rfm_dataset_build_v1/`。上列只讀反讀／來源／公開聚合，不建置、不寫檔；需原四CSV及私有證據，缺檔即停止。合成測試、--specification-only→--build的本輪一次歷程與停止條件見[實作驗收](../docs/STAGE6_RFM_DATASET_IMPLEMENTATION.md)；既有目錄不得刪除重播。沒有分群、訓練、Notebook或Dashboard。

## Stage 6前輪RFM資料集契約

```powershell
.\.venv\Scripts\python.exe scripts\freeze_rfm_dataset_spec.py --specification-only
.\.venv\Scripts\python.exe scripts\freeze_rfm_dataset_spec.py
```

需原四CSV、舊盤點規格／報告與原來源。先凍結12份來源／程式／測試綁定，再只查母體、訂單與狀態聚合；來源、政策或輸出不同即停止，不覆寫。兩份16欄CSV與manifest是未來輸出契約，本輪未建立私有資料集或builder；詳見[資料集規格](../docs/STAGE6_RFM_DATASET_SPEC.md)。

## Stage 6前輪RFM輸入盤點

```powershell
.\.venv\Scripts\python.exe scripts\audit_rfm_feasibility.py --specification-only
.\.venv\Scripts\python.exe scripts\audit_rfm_feasibility.py
```

先固定欄位、候選日期與8份原來源／程式／測試綁定，再驗資料前後bytes及只讀盤點。需原四CSV，來源／政策／既有輸出不同即停止，不覆寫或重建證據；不需DB，沒有個體RFM、分數、分群或模型呼叫。完整[語義、結果與限制](../docs/STAGE6_RFM_FEASIBILITY.md)保留，候選日期尚非RFM資料集契約。

## Stage 5前輪適用範圍與交付文件

本輪只整理[四欄／三欄模型卡](../docs/STAGE5_MODEL_APPLICABILITY.md)及既有聚合報告，沒有新增或執行CLI。原訓練命令不是交付驗收命令，已有training_v1與凍結分數不能為看結果刪檔重跑；缺原私有證據則停止，不補訓練。Stage 5維持待資料，Stage 6 RFM目前僅為下一輪規格盤點建議。

## Stage 5新時間窗交接文件

本輪交付[清單與空白驗收範本](../docs/templates/review_window_handoff/README.md)，沒有新增CLI、資料驗證器或訓練入口，不需為填範本重跑來源盤點／模型。日後收到新證據才在私有交接目錄逐月驗收；JSON只是待填格式，不能把解析成功當成來源／標籤通過。

## Stage 5後續時間窗盤點

```powershell
.\.venv\Scripts\python.exe scripts\audit_review_validation_windows.py --specification-only
.\.venv\Scripts\python.exe scripts\audit_review_validation_windows.py
```

需原H60／來源guard及Git歷史、既有收據、已存版本metadata。先凍結政策與usage_history／guard，再讀評論ID／時間戳，不讀review_score值或建新y；新窗口全待資料，不因最大回答時間延長C或啟用出分。用途凍結另外保留在[正式文件](../docs/STAGE5_REVIEW_VALIDATION_WINDOWS.md)與聚合JSON。缺證據即停止，不重建guard補缺，也不需重跑舊訓練或診斷。

## Stage 5逐fit成熟先驗與時間漂移

```powershell
.\.venv\Scripts\python.exe scripts\audit_review_mature_prior.py --specification-only
.\.venv\Scripts\python.exe scripts\audit_review_mature_prior.py
```

需原完整H60角色、原資料及既有守門證據。先凍結政策／私有guard，再按每個fit自己的y核對全部與近期成熟先驗、互斥覆蓋、核准月／時齡及跨fit轉換。query只在歷史先驗完成後作事後描述；0模型／效能／參數更新，分數只核hash。缺檔或版本不同停止，不能用較晚標籤補回，也不需重跑舊訓練或診斷CLI。詳見[稽核文件](../docs/STAGE5_REVIEW_MATURE_PRIOR_AUDIT.md)。

## Stage 5雙臂只讀診斷

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_review_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\diagnose_review_ablation.py
```

需原完整H60、兩臂凍結分數、manifest及收據，讀已完成版本，不呼叫訓練準備preflight。先凍結新診斷規格／私有guard，再計機率與排序差、星期／小時／等待支援及外層邊際損失。0fit／transform／predict／重新選C；缺檔或異動停止，不能補訓練。既有training_v1不重跑。結果及決策見[只讀診斷](../docs/STAGE5_REVIEW_ABLATION_DIAGNOSTICS.md)，本輪沒有新提醒排名政策或Dashboard。

## Stage 5三欄正式入口

本輪已依凍結入口完成一次`--train`，9次內層＋3次外層fit與完整配對通過，見[實際開發結果](../docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)。以下三個命令保留作執行前歷程；現有training_v1已占用，`--check`及前置凍結流程不能作發布後驗收，也不得刪除證據重跑。發布後改讀既有報告、manifest與獨立驗收紀錄。

```powershell
.\.venv\Scripts\python.exe scripts\run_review_month_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\run_review_month_ablation.py --verify-synthetic
.\.venv\Scripts\python.exe scripts\run_review_month_ablation.py --check
```

依序綁定入口／測試／JSON格式、跑合成驗證及只讀準備檢查。會核原本機來源與完整角色，但只在合成fixture上fit。真實訓練需明確`--train`且先通過同版成功驗證；前輪沒有執行該動作，本輪已完成一次。輸出占用、來源改版、配對不符或發布失敗均停止，詳見[正式入口驗收](../docs/STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md)。

## 前輪Stage 5三欄消融執行準備

```powershell
.\.venv\Scripts\python.exe scripts\prepare_review_month_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\prepare_review_month_ablation.py
```

兩行均不訓練、不建立X或計效能；當時先固定[執行政策](../reports/stage5/review_month_ablation_execution_specification.json)與私有input_guard，再輸出[準備驗收](../reports/stage5/review_month_ablation_execution_preflight.json)。會讀原H60完整角色及四欄凍結分數以核對metadata、ID與合法機率，不能用缺失來源重訓補分數。原13私有來源及新guard留本機；當時預留的`.runtime/stage5_review_month_ablation_training_v1/`現已完成正式交付。

完整同ID配對validator已用合成資料驗證；該準備輪當時尚無真實三欄分數；現已另完成正式交付。該準備CLI沒有`--train`；當時dispatcher待另實作與綁定，詳見[執行準備文件](../docs/STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md)。

## 前輪Stage 5三欄消融與合成驗證

```powershell
.\.venv\Scripts\python.exe scripts\verify_review_month_ablation_pipeline.py
```

[新模組](review_month_ablation_pipeline.py)直接建立星期、小時與核准等待，固定32維；共用原四欄的完整名冊／H60／標籤資格守門，保持獨立模型狀態。上述CLI實際fit合成scaler／Logistic並驗洩漏，核35份公開來源但不沿父規格讀原CSV、私有guard或分數；輸出[合成驗證報告](../reports/stage5/review_month_ablation_pipeline_verification.json)，詳細日誌留`.runtime/stage5_review_month_ablation_pipeline/`。

這不是三欄真實訓練入口；後續來源、完整12角色與輸出版本準備見上節，正式訓練仍待決定。原四欄程式與分數保留，舊`run_review_baseline.py`不能當三欄消融入口。詳見[實作與驗證](../docs/STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md)。

## 前輪Stage 5離線最小基線

```powershell
.\.venv\Scripts\python.exe scripts\run_review_baseline.py --specification-only
.\.venv\Scripts\python.exe scripts\run_review_baseline.py
```

第一個命令驗來源並凍結[新執行規格](../reports/stage5/review_baseline_training_specification.json)及私有input_guard；第二個在完整來源／角色守門通過後，按既定三個C及時間切分執行12次真實模型fit，產生[開發回測](../reports/stage5/review_baseline_training.json)。[來源模組](review_baseline_sources.py)接原私有收據與manifest，查詢未來標籤清空；[評估模組](review_baseline_evaluation.py)只在角色合格y上計分，未知仍完整出分。

逐筆inner／outer機率、fit診斷與manifest在`.runtime/stage5_review_baseline_training_v1/`，不隨Git交付。缺原CSV、H60 bundle、原收據或原基線guard即停止；不由CLI重建缺失證據。已有結果會在fit前拒收，不能直接重跑覆寫。三月已檢視，數字是開發回測；原入庫／版本限制仍在。詳細方法、實際結果及驗證見[離線基線文件](../docs/STAGE5_REVIEW_OFFLINE_BASELINE.md)。

## 前輪Stage 5四欄pipeline與合成驗證

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_pipeline -q
.\.venv\Scripts\python.exe scripts\verify_review_pipeline.py
```

[實作文件](../docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md)說明builder、不可變預期名冊與受控fit／query介面。[verify_review_pipeline.py](verify_review_pipeline.py)只執行指定合成測試，綁10份公開程式／契約，輸出[驗證報告](../reports/stage5/review_pipeline_verification.json)。真實原CSV、私有標籤及模型都不讀；runtime log與耗時留.runtime/stage5_review_pipeline_verification/，報告排除時間以便同版bytes重現。

受控pipeline只fit合格訓練列，query保留未知且不讀未來標籤；低階介面與真實來源loader、內層選參／評估CLI分開。後續已由上述離線入口串接，原入庫／版本限制保留。

## 前輪Stage 5最小基線契約

```powershell
.\.venv\Scripts\python.exe scripts\audit_review_baseline_contract.py --specification-only
.\.venv\Scripts\python.exe scripts\audit_review_baseline_contract.py
```

[基線文件](../docs/STAGE5_REVIEW_BASELINE_SPEC.md)固定四個事件時間欄、44維前處理、C=0.1／1／10的歷史內層AP選參及未知／評估政策。[規格](../reports/stage5/review_baseline_specification.json)與[稽核](../reports/stage5/review_baseline_contract_audit.json)只做契約與資料支援檢查，沒有建立四欄X、載入模型、fit、預測或算指標；不是訓練入口。

需原資料來源、已凍結H60私有bundle及原正式執行收據（均不隨Git clone交付）；缺任一資產就停止，不能補造收據或把C全域標籤join回歷史fit。新input_guard只留Git忽略的.runtime/stage5_review_baseline_v1/，原標籤／角色CSV及其manifest不改寫，私有digest不公開。兩事件時鐘仍無原入庫／版本證明，核對通過只支持條件離線研究。

## 前輪Stage 5資料集凍結

```powershell
.\.venv\Scripts\python.exe scripts\freeze_review_dataset.py --specification-only
.\.venv\Scripts\python.exe scripts\freeze_review_dataset.py
```

詳見[凍結資料集與逐fit核對](../docs/STAGE5_REVIEW_DATASET_SPEC.md)。固定H60、C截止及三個開發fold的內外層日曆，先凍結[規格](../reports/stage5/review_dataset_specification.json)，再輸出[聚合核對](../reports/stage5/review_dataset_audit.json)。原九CSV與前輪報告須吻合SHA；各角色以自己的答案截止重建，未知y留空，C標籤不能回填歷史fit。

兩CSV及manifest只寫Git忽略的.runtime/stage5_review_dataset_v1/，共9／12個標籤與審計欄，不是21欄特徵快取。公私輸出預檢、來源前後綁定、不可覆寫與逐值反讀皆需通過。沒有MySQL、評論文字輸入、模型載入、訓練、預測、效能或Dashboard；來源變更或改H不能直接覆寫本版。

## 前輪Stage 5可行性盤點

```powershell
.\.venv\Scripts\python.exe scripts\audit_review_prediction_feasibility.py
```

輸出為[聚合盤點](../reports/stage5/review_prediction_feasibility.json)，使用九CSV的凍結SHA，並以AST只讀原21欄候選定義；不呼叫Stage 4特徵／延遲label builder，不啟動MySQL或載入模型。首答、未知標籤與fit時鐘規則見[方法文件](../docs/STAGE5_REVIEW_PREDICTION_FEASIBILITY.md)。既有報告只接受相同bytes重現，來源不同需另接受新版本，不覆寫原報告。

## Stage 4研究入口

以下按研究脈絡索引，不是要依序重跑的安裝步驟。`train_*`、`compare_*`、`improve_*`、`ablate_*`、`tune_*` 可能訓練模型或fit校準器；`audit_*`／`diagnose_*` 各輪也有不同資料、模型重播及輸出需求，應先讀對應文件。

| 研究主題 | CLI入口 | 方法與結果 |
| --- | --- | --- |
| 原版、模型比較與誤報改善 | [train_delay_model.py](train_delay_model.py)、[compare_delay_models.py](compare_delay_models.py)、[improve_delay_alerts.py](improve_delay_alerts.py) | [原版](../docs/STAGE4_DELAY_PREDICTION.md)、[提醒策略](../docs/STAGE4_ALERT_OPTIMIZATION.md) |
| 月份誤差、等待期、多月份與滾動重訓 | [diagnose_delay_errors.py](diagnose_delay_errors.py)、[compare_waiting_strategies.py](compare_waiting_strategies.py)、[compare_multimonth_validation.py](compare_multimonth_validation.py)、[compare_monthly_retraining.py](compare_monthly_retraining.py) | [月份診斷](../docs/STAGE4_MONTHLY_DIAGNOSTICS.md)、[等待期](../docs/STAGE4_WAITING_EXPERIMENT.md)、[多月份](../docs/STAGE4_MULTIMONTH_VALIDATION.md)、[每月重訓](../docs/STAGE4_MONTHLY_RETRAINING.md) |
| 校準與每日預算 | [compare_calibration_budget.py](compare_calibration_budget.py)、[diagnose_budget_misses.py](diagnose_budget_misses.py)、[improve_budget_ranking.py](improve_budget_ranking.py) | [校準](../docs/STAGE4_CALIBRATION_BUDGET.md)、[預算排名](../docs/STAGE4_BUDGET_RANKING.md) |
| 待件負載與答案時鐘 | [improve_pending_ranking.py](improve_pending_ranking.py)、[improve_outcome_clock.py](improve_outcome_clock.py) | [待件排名](../docs/STAGE4_PENDING_RANKING.md)、[答案時鐘](../docs/STAGE4_OUTCOME_CLOCK.md) |
| 特徵、消融與Logistic正則化 | [improve_feature_engineering.py](improve_feature_engineering.py)、[ablate_delay_features.py](ablate_delay_features.py)、[tune_logistic_regularization.py](tune_logistic_regularization.py) | [特徵](../docs/STAGE4_FEATURE_ENGINEERING.md)、[消融](../docs/STAGE4_FEATURE_ABLATION.md)、[正則化](../docs/STAGE4_LOGISTIC_REGULARIZATION.md) |
| 路線、負載變化與名額交換 | [diagnose_december_misses.py](diagnose_december_misses.py)、[train_route_load_interactions.py](train_route_load_interactions.py)、[diagnose_route_load_interactions.py](diagnose_route_load_interactions.py)、[train_backlog_changes.py](train_backlog_changes.py)、[diagnose_backlog_changes.py](diagnose_backlog_changes.py)、[diagnose_backlog_route_exchanges.py](diagnose_backlog_route_exchanges.py) | [十二月](../docs/STAGE4_DECEMBER_MISS_DIAGNOSTICS.md)、[路線負載](../docs/STAGE4_ROUTE_LOAD_INTERACTIONS.md)、[堆積變化](../docs/STAGE4_BACKLOG_CHANGES.md)、[名額交換](../docs/STAGE4_BACKLOG_ROUTE_EXCHANGES.md) |
| 分類與排序目標 | [compare_backlog_objectives.py](compare_backlog_objectives.py)、[diagnose_objective_misses.py](diagnose_objective_misses.py) | [相同特徵下的目標比較](../docs/STAGE4_BACKLOG_OBJECTIVES.md) |
| 排序正則化、配對焦點、日量與配對方式 | [compare_rank_regularization.py](compare_rank_regularization.py)、[diagnose_rank_regularization.py](diagnose_rank_regularization.py)、[compare_rank_pair_focus.py](compare_rank_pair_focus.py)、[diagnose_rank_focus.py](diagnose_rank_focus.py)、[diagnose_rank_batch_size.py](diagnose_rank_batch_size.py)、[compare_rank_pair_method.py](compare_rank_pair_method.py)、[diagnose_rank_pair_method.py](diagnose_rank_pair_method.py) | [正則化](../docs/STAGE4_RANK_REGULARIZATION.md)、[焦點](../docs/STAGE4_RANK_PAIR_FOCUS.md)、[日量](../docs/STAGE4_RANK_BATCH_SIZE.md)、[配對方式](../docs/STAGE4_RANK_PAIR_METHOD.md) |
| 物流時點與交運歷史 | [audit_logistics_availability.py](audit_logistics_availability.py)、[train_handover_history.py](train_handover_history.py)、[diagnose_handover_history.py](diagnose_handover_history.py)、[diagnose_handover_sparse.py](diagnose_handover_sparse.py) | [物流可得性](../docs/STAGE4_LOGISTICS_AVAILABILITY.md)、[交運歷史](../docs/STAGE4_HANDOVER_HISTORY.md)、[稀疏交集](../docs/STAGE4_HANDOVER_SPARSE_DIAGNOSTICS.md) |
| 交運件數、共同漏報與核准訊號 | [train_handover_count.py](train_handover_count.py)、[diagnose_handover_count.py](diagnose_handover_count.py)、[diagnose_handover_common_misses.py](diagnose_handover_common_misses.py)、[audit_approval_signals.py](audit_approval_signals.py) | [件數消融](../docs/STAGE4_HANDOVER_COUNT_ABLATION.md)、[共同漏報與訊號](../docs/STAGE4_COMMON_MISSES_AND_SIGNALS.md) |
| 未觀測交運待件件數／時齡 | [train_unobserved_handover_count.py](train_unobserved_handover_count.py)、[diagnose_unobserved_handover_count.py](diagnose_unobserved_handover_count.py)、[train_unobserved_handover_age.py](train_unobserved_handover_age.py)、[diagnose_unobserved_handover_age.py](diagnose_unobserved_handover_age.py)、[diagnose_age_intersections.py](diagnose_age_intersections.py) | [件數](../docs/STAGE4_UNOBSERVED_HANDOVER_COUNT.md)、[時齡](../docs/STAGE4_UNOBSERVED_HANDOVER_AGE.md)、[交集](../docs/STAGE4_AGE_INTERSECTIONS.md) |
| 五種子與欄位取樣 | [compare_age_seed_stability.py](compare_age_seed_stability.py)、[diagnose_age_seed_stability.py](diagnose_age_seed_stability.py)、[compare_age_colsample.py](compare_age_colsample.py)、[diagnose_age_colsample.py](diagnose_age_colsample.py) | [種子穩定性](../docs/STAGE4_AGE_SEED_STABILITY.md)、[colsample](../docs/STAGE4_AGE_COLSAMPLE.md) |
| 固定四組模型的邊界、成熟訊號及條件比較 | [diagnose_four_model_boundary.py](diagnose_four_model_boundary.py)、[audit_mature_history_signals.py](audit_mature_history_signals.py)、[diagnose_conditional_mature_signals.py](diagnose_conditional_mature_signals.py) | [每日邊界](../docs/STAGE4_FOUR_MODEL_BOUNDARY.md)、[成熟訊號](../docs/STAGE4_MATURE_HISTORY_SIGNAL_AUDIT.md)、[固定條件](../docs/STAGE4_CONDITIONAL_MATURE_SIGNALS.md) |
| 完成歷史與未完成慢件代表性 | [audit_completed_history_representativeness.py](audit_completed_history_representativeness.py) | [同核准窗口、逾期待件與條件敏感度](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md) |
| 取消／結案與承諾版本來源 | [audit_event_source_availability.py](audit_event_source_availability.py) | [來源取得、時鐘涵蓋及未來驗收](../docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md) |
| 單日凍結分數交付驗收 | [accept_frozen_daily_delivery.py](accept_frozen_daily_delivery.py) | [名冊／版本、20組排名、10%名額與私有CSV反讀](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md) |
| 全量日資料契約查核 | [audit_daily_data_contract.py](audit_daily_data_contract.py) | [全量名冊、雙時間版本、日結訊號與待資料缺口](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract) |

## 共用模組與凍結來源

`delay_*.py` 主要供CLI與測試匯入：特徵模組建立核准時可得欄位，`*_training.py` 封裝各輪候選與訓練，`delay_alert_policy.py`／`delay_calibration_policy.py` 管理提醒規則，`delay_*diagnostics.py`、`delay_four_model_boundary.py`、`delay_mature_signal_profiles.py` 與 `delay_conditional_mature_signals.py` 計算診斷。`logistics_event_availability.py` 記錄物流事件可得性；`db_config_example.py` 只提供設定格式，實際 `db_config.py` 不提交。

最新研究固定每日10%、五種子11／29／42／73／101及原12個階段。事前規格、正式報告與所綁定的舊程式／模型／快取SHA形成來源鏈，不能為清整目錄而改名或搬移。較早入口可能覆寫預設產物，較新入口會拒絕不同內容；重現前依各輪文件選擇新的輸出路徑並保留原來源。

代表性稽核由`delay_history_representativeness.py`建立status-free核准窗口計數，`delay_representation_profiles.py`作固定條件比較。新欄只作稽核，不加入模型白名單；初版規格僅保留JSON格式修正紀錄，實際執行使用正式規格。

最新來源查核不需要模型或分數帳本。它綁定已取得的本機／官方證據快照，不能把重讀今天的網站或重新啟動服務當成2016–2018的新業務資料；未取得的新來源列為待資料。

單日驗收由`delay_daily_delivery_acceptance.py`核對同一名冊的20組分數與旗標，CLI另綁原始名冊及版本、驗私有CSV。完整性只對原凍結研究cohort成立，不驗證真實全核准日或原入庫完成；本機輸出只接受相同內容重現，不覆寫不同產物。

只複製Git儲存庫不足以重現全部實驗：原始CSV在 `data/raw/olist/`，特徵快取及逐筆分數在 `data/processed/`，模型在 `models/`，執行證明在 `.runtime/`，皆保留本機並由Git忽略。公開提交以程式、規格、聚合JSON及文件為主，不提交原始資料、逐筆分數、憑證或本機模型。
