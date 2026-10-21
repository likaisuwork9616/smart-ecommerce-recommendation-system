# 電商智慧推薦系統

Smart E-Commerce Recommendation System

以Olist電商資料練習資料建置、SQL、商業分析、延遲及評論預測，再延伸至Retailrocket推薦系統、API與前端。資料環境、SQL與EDA初版已完成；Stage 4維持待資料。Stage 5最新完成逐fit成熟低評先驗與時間漂移只讀稽核：近期窗口沒有跨月一致方向，保留四欄與全部合格歷史對照，本輪不訓練、不修正參數。推薦系統、API與Dashboard尚未開始。

## 目前進度

| 階段 | 狀態 | 現有成果 |
| --- | --- | --- |
| Stage 1：資料與環境 | 完成 | Olist 九份 CSV、MySQL、Jupyter 與本機啟動工具 |
| Stage 2：SQL | 完成 | 訂單、品類營收、平均客單價與多表查詢 |
| Stage 3：商業 EDA | 初版完成 | 八張趨勢、品類、付款、評論、配送與地區圖表 |
| Stage 4：延遲預測 | 交接清單／驗收範本完成；資料仍待取得 | 每日10%與五種子維持，研究名冊交付保留；全量資料與正式提醒尚未驗收 |
| Stage 5：評論低評分預測 | 逐fit成熟先驗與時間漂移稽核完成 | 6個fit情境、12完整角色；分開成熟未知／未成熟，無query回填、無追加訓練或先驗修正 |
| Stage 6：RFM | 尚未開始 | 顧客分群 |
| Stage 7：Dashboard | 暫緩 | 先確認延遲模型適用程度 |
| Stage 8–13：推薦系統 | 尚未開始 | Retailrocket 行為、熱門、共現與個人化推薦 |
| Stage 14–15：API、前端 | 尚未開始 | FastAPI、JavaScript／AJAX 串接 |

完整研究歷程與各輪成敗見[專案進度](docs/PROJECT_PROGRESS.md)，全部方法文件見[文件導覽](docs/README.md)。

## 快速開始

以下指令在專案根目錄的 PowerShell 執行。完整版本、資料庫初始化及跨電腦重建方式見[本機環境指南](docs/LOCAL_SETUP.md)。

首次在新電腦使用時，建立 Python 3.12 環境並安裝鎖定套件：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

將 Olist 九份 CSV 放入 `data/raw/olist/`，檔名與用途見[資料說明](data/README.md)。SQL 與前三本 Notebook 需要 MySQL；Stage 4 直接讀 CSV。模型、特徵快取及逐筆分數只保留在本機，下載此 repository 不會同時取得它們。

| 想做什麼 | 入口 |
| --- | --- |
| 建立、啟停 MySQL 或啟動 Jupyter | [本機環境指南](docs/LOCAL_SETUP.md) |
| 按步驟閱讀分析 | [Notebook 導覽](notebooks/README.md) |
| 查詢資料庫 | [SQL 導覽](sql/README.md) |
| 看商業分析圖表 | [Stage 3 成果](docs/STAGE3_BUSINESS_ANALYSIS.md) |
| 看延遲模型適用範圍、限制與交付前提 | [模型卡與交付清單](docs/STAGE4_MODEL_APPLICABILITY.md) |
| 重現單日凍結分數的離線交付 | [單日驗收文件](docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md) |
| 看全量日名冊、入庫／版本與日結缺口 | [資料契約與停止條件](docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract) |
| 準備資料交接與填寫驗收紀錄 | [交接清單](docs/templates/daily_data_handoff/README.md)、[驗收範本](docs/templates/daily_data_handoff/acceptance_record.template.md) |
| 看評論低評分預測能否開始 | [Stage 5可行性盤點](docs/STAGE5_REVIEW_PREDICTION_FEASIBILITY.md) |
| 重現首答資料集與逐fit標籤資格 | [Stage 5凍結規格及核對](docs/STAGE5_REVIEW_DATASET_SPEC.md) |
| 看最小基線、選參與評估約定 | [Stage 5最小基線規格](docs/STAGE5_REVIEW_BASELINE_SPEC.md) |
| 驗證四欄builder與train-only pipeline | [Stage 5實作與洩漏測試](docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md) |
| 看來源守門、實際選參及評論基線結果 | [Stage 5離線最小基線](docs/STAGE5_REVIEW_OFFLINE_BASELINE.md) |
| 只讀原分數診斷月份、機率與四欄支援 | [Stage 5凍結分數診斷](docs/STAGE5_REVIEW_SCORE_DIAGNOSTICS.md) |
| 看只移除購買月份的單因子契約 | [Stage 5月份消融規格](docs/STAGE5_REVIEW_MONTH_ABLATION_SPEC.md) |
| 驗證三欄消融及保留的四欄對照 | [Stage 5三欄實作與洩漏測試](docs/STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md) |
| 看三欄執行政策、來源與配對驗收 | [Stage 5消融執行準備](docs/STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md) |
| 看正式入口、私有交付與合成驗收 | [Stage 5消融入口驗證](docs/STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md) |
| 看三欄真實消融、同ID差值與交付驗收 | [Stage 5三欄消融結果](docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md) |
| 看雙臂機率、排名差異與星期／小時／等待支援 | [Stage 5配對只讀診斷](docs/STAGE5_REVIEW_ABLATION_DIAGNOSTICS.md) |
| 看逐fit成熟先驗、覆蓋及時間漂移 | [Stage 5成熟先驗稽核](docs/STAGE5_REVIEW_MATURE_PRIOR_AUDIT.md) |
| 訓練或使用第一版延遲模型 | [延遲模型方法與推論](docs/STAGE4_DELAY_PREDICTION.md) |
| 找特定研究的執行方式 | [腳本導覽](scripts/README.md)、[文件導覽](docs/README.md) |
| 查正式數字、規格與圖表 | [報告導覽](reports/README.md) |

已備妥本機環境後，可啟動分析介面：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_jupyter.ps1
```

此腳本會先啟動專案 MySQL。請使用 `Shop (Python 3.12)` kernel；各 Notebook 的資料前提與是否會觸發訓練，先看其[操作說明](notebooks/README.md)。

## 延遲預測目前的結果

目前可交付**離線研究證據與操作文件**，尚未證明可用於正式延遲提醒。特徵以訂單核准時截斷，10%名單要等完整核准日批次，並非已驗證的逐筆即時提醒。每日最多取 `floor(N × 10%)` 張，未知答案先競爭名額、再計已知答案成績；不借其他日名額或在各路線另分10%。

| 歷史選模主方案指標（不是五種子平均） | 已檢視的三個開發月 |
| --- | ---: |
| 月份 | 2017-12、2018-02、2018-04 |
| 有效訂單／延遲 | 18,833／1,642 |
| 提醒名額 | 1,845 |
| 抓到延遲 TP／誤報 FP／漏報 FN | 413／1,432／1,229 |
| 開發召回 | 25.15% |
| 提醒精確率 | 22.38% |
| 最差歷史驗證召回 | 19.63% |

來源為[排序配對焦點報告](reports/stage4/rank_pair_focus.json)及後續凍結主方案，三月依歷史規則選到不同候選。三個fold都未全面通過各歷史月至少30%召回的原要求；這些開發月已反覆檢視，不能當未知測試成績。預設推論仍是原版RF，其原測試早已檢視、使用不同規則；後續固定預算研究未重評該期間。

四個固定設定另保留11／29／42／73／101五種子。下表是同三個開發月、相同1,642張延遲及1,845個名額的種子平均與實際範圍；不是信賴區間、五份新資料或ensemble，也沒有驗證完整混合主方案的五種子穩定性。

| 固定設定 | TP平均［範圍］ | 召回平均［範圍］ |
| --- | ---: | ---: |
| 原101 × colsample0.8 | 330.6［320，339］ | 20.13［19.49，20.65］% |
| 時齡102 × 0.8 | 336.2［326，350］ | 20.48［19.85，21.32］% |
| 原101 × 1.0 | 325.2［322，331］ | 19.81［19.61，20.16］% |
| 時齡102 × 1.0 | 325.6［315，336］ | 19.83［19.18，20.46］% |

模型訓練／延遲效能cohort為時間合理且最終已送達的Olist歷史訂單；待件上下文可含其他有效核准單，不能據此外推全部核准、取消或未送達的效能。缺原入庫與承諾／主檔版本時鐘，核准時可得性仍有假設。等待24–72小時指主賣家歷史未觀測交運待件p90，不是本單等待。逐月成績、弱點與交付邊界見[模型卡](docs/STAGE4_MODEL_APPLICABILITY.md)。

前輪[單日離線交付驗收](docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md)固定2018-02-01，四設定與全部五種子並列，研究cohort242張、各組24名額；完整排名4,840列與480個跨模型提醒旗標只存本機，僅研究名冊交付通過。

前輪[全量日資料契約查核](docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract)核對原九CSV、既有來源證據、匯入程式與凍結分數名冊。同日原匯出245張中另3張沒有全部20組分數，不能直接升格全量交付；245也不是上游全量證明。現有來源缺原入庫／可得時間、歷史版本及日結訊號，四面向均列待資料。日結後T才收到資料不能回填成核准時點t已知；時區、日切、晚到與重開規則尚待來源／使用方確認。

先前在沒有新來源下，完成[資料交接清單與驗收範本](docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#data-handoff-kit)：15個逐項check_id列出責任、必要資產、時鐘與版本、逐日／分區對帳、覆核及缺口處置。所有實測欄待填、狀態預設pending_data，分開記資料交接、分數交付與模型適用／正式通知；範本備妥不代表資料已收到或通過驗收。填寫副本及實際資料留Git忽略的.runtime/data_handoffs/，公開只放空範本。

[取消／結案與承諾版本方向](docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md)繼續待資料。下一步取得可稽核的同ID核准清冊、雙時間版本與日結／入庫證據，再按清單驗收；沒有新資料就維持0訓練、0新效能結論，正式通知與模型Dashboard暫緩。

## Stage 5：四欄基線與三欄消融結果

固定在核准t預測「本單最早記錄回答若在`(t,t+60天]`內，是否為1–2分」，3–5分為另一類。一張訂單一列，不篩最終送達；未回覆、超窗、品質隔離或觀察窗未滿一律保持未知，不能補成0。這是固定窗回覆者的條件目標，不能外推所有未評論訂單。

| 核准<2018-05-01；事件觀察截止2018-07-01 exclusive | 實際資料支援，非模型效能 |
| --- | ---: |
| 完整研究查詢名冊 | 73,254；均走完整60天窗 |
| 合格首答標籤 | 72,173＝1–2分11,406＋3–5分60,767 |
| 未知／隔離 | 1,081＝截止時無可見回答680＋首答超窗388＋首答≤核准13 |

多評論先按order_id辨識首答，不能跳過早答改挑晚答、取最差分或以review_id作全域唯一鍵。各角色先以自己的答案截止排除未來評論，再檢查窗內鍵／分數／時鐘與平手；未來壞評論不能回頭污染歷史fit。即使已早答，60天未滿者仍遮罩y。

| 外層開發查詢月／fit月初 | 內層驗證月 | 外層歷史池／當時合格標籤 |
| --- | --- | ---: |
| 2017-12 | 2017-09 | 39,463／27,108 |
| 2018-02 | 2017-11 | 52,482／39,448 |
| 2018-04 | 2017-12 | 66,476／51,433 |

內層取在外層fit前已走完60天的最近完整月；內層訓練標籤截至內層月初，驗證截至外層fit，外層查詢答案截至2018-07-01。三個開發月已檢視，不是新未知保留測試。全局C標籤不能join回較早fit；歷史角色檔只提供當時合格的nullable y。

[凍結資料集文件](docs/STAGE5_REVIEW_DATASET_SPEC.md)附[機器規格](reports/stage5/review_dataset_specification.json)、[實際核對](reports/stage5/review_dataset_audit.json)及重現指令。私有標籤／切分中繼資料只留`.runtime/stage5_review_dataset_v1/`。前輪資料集建立時尚未訓練；後續依序完成四欄基線與三欄消融，沒有建立原候選21欄。不限H的72,613張與H60口徑不同，不能解讀成模型得失。

原四欄基線依[最小基線訓練與評估規格](docs/STAGE5_REVIEW_BASELINE_SPEC.md)執行：

| 規格 | 原四欄基線採用的固定做法 |
| --- | --- |
| 特徵假設 | 購買月／星期／時及核准等待小時；其餘17個快照候選先排除，兩個原事件時鐘仍只有離線代理假設 |
| 前處理 | 日曆固定one-hot43維＋等待train-only標準化1維；無補值，非法值停止且不刪查詢單 |
| 最小模型 | 合格訓練低評比例常數作參考；L2 Logistic的C=0.1／1／10，只依既定內層AP選參，平手取較小C |
| 評估與未知 | 固定0.5門檻，未知保留全名冊但不參與fit、選參或指標；逐月AP與機率／混淆表，三月皆有效才計macro AP |

前輪將[已驗證pipeline](docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md)串接原來源SHA、manifest、正式收據與私有guard，核對73,254張研究名冊及12個角色。每次fit只用當時合格y；query七個未來標籤欄清空後完整出分，再以各角色truth計分。當輪29份原凍結來源／證據bytes不變，沒有改寫H60標籤。

| 已檢視外層開發月 | 完整查詢／合格／未知 | 選定C | Logistic AP | 常數AP | 固定0.5的TP／FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2017-12 | 5,832／5,740／92 | 0.1 | 0.177118 | 0.162892 | 2／933 |
| 2018-02 | 6,706／6,611／95 | 0.1 | 0.202077 | 0.205869 | 1／1,360 |
| 2018-04 | 6,778／6,704／74 | 0.1 | 0.133589 | 0.129773 | 0／870 |

三月等權macro AP為**0.170928對0.166178**，差+0.004750；2月AP反而較低，ROC-AUC都接近0.5，固定0.5召回極低。Brier／logloss前兩月略好、4月略差，沒有跨月一致改善或正式適用證明。完整內層九個候選、外層機率指標與混淆表見[實驗文件](docs/STAGE5_REVIEW_OFFLINE_BASELINE.md)及[正式報告](reports/stage5/review_baseline_training.json)。

正式一次完成12次fit、18個出分區塊；108,744列是跨候選／角色出分次數，不是獨立訂單。逐筆分數、fit診斷及manifest在`.runtime/stage5_review_baseline_training_v1/`，不隨Git提供。操作入口如下；**正式命令會訓練，已有結果或失敗收據會在fit前拒收**。需原私有資料與收據，不能靠Git clone自行補出證據。

```powershell
.\.venv\Scripts\python.exe scripts\run_review_baseline.py --specification-only
.\.venv\Scripts\python.exe scripts\run_review_baseline.py
```

前輪[只讀診斷](docs/STAGE5_REVIEW_SCORE_DIAGNOSTICS.md)核對原18個分數區塊與108,744列完整metadata，保留未知；35份公開與11份私有來源通過守門，當輪42份舊資產bytes不變。統計規格在該輪真實計算前固定，沒有fit、transform、predict或重播分數；詳細分布見[聚合報告](reports/stage5/review_score_diagnostics.json)。

| 外層開發月 | 已知低評率 | 已知平均分數 | 平均分數偏差 | 購買月份支援 |
| --- | ---: | ---: | ---: | --- |
| 2017-12 | 16.29% | 13.93% | −2.36百分點 | query的11月／12月類別在合格歷史只有0／1筆 |
| 2018-02 | 20.59% | 15.65% | −4.94百分點 | query的1月／2月類別有782／1,731筆 |
| 2018-04 | 12.98% | 15.37% | +2.39百分點 | query的3月／4月類別有2,633／2,359筆 |

內層9月query全部落在零或1–29筆的月份支援，內層11月98.88%落在零支援；星期與小時整體有較完整支援。4月等待均值由歷史10.17增至query14.82小時，但沒有證據證明等待尾部造成誤差。其原機率損失差主要位於0.15–0.30分數箱，並非極高分少數單；這是既有損失分解，不是新效能結論。

該輪43項新增合成測試、36項來源對抗檢查及8,218項正式獨立對帳通過。只讀操作如下，需原私有資產；缺檔或版本不符即停止，不能補訓練取代凍結分數。

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_review_scores.py --specification-only
.\.venv\Scripts\python.exe scripts\diagnose_review_scores.py
```

前輪已凍結[只移除purchase_month的消融規格](docs/STAGE5_REVIEW_MONTH_ABLATION_SPEC.md)，另附[機器規格](reports/stage5/review_month_ablation_specification.json)與[metadata稽核](reports/stage5/review_month_ablation_contract_audit.json)。只刪月份及12個月one-hot欄，輸入三欄、輸出32維；H60、完整角色、其餘三欄定義／前處理、C候選與內層AP選參、評估均不變。三欄須自行按原規則選C，不能直接沿用四欄C=0.1；四欄對照保留凍結分數，不重訓。

| 前輪契約驗收 | 當輪實際結果 |
| --- | --- |
| 名冊／來源 | 73,254研究單、12角色289,973列一致；39公開＋12私有綁定，49份舊資產bytes不變 |
| 單因子邊界 | protocol只差5處月份結構；輸入順序、one-hot種類與維度相應減少，其餘政策逐值相同 |
| 驗證 | 14項契約測試全過，508項獨立對帳通過；舊分數只hash、不解析或重評 |
| 未執行 | 三欄builder／pipeline、X、fit／transform／predict、選C、效能與Dashboard均未執行 |

前輪操作只凍結契約與核metadata，不訓練：

```powershell
.\.venv\Scripts\python.exe scripts\freeze_review_month_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\freeze_review_month_ablation.py
```

前輪已完成[獨立三欄builder／train-only pipeline](docs/STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md)，公開[合成驗證報告](reports/stage5/review_month_ablation_pipeline_verification.json)。直接建立星期、小時與原始等待；固定31個one-hot加1個等待欄。名冊、H60及標籤資格沿用原守門，未知不fit、query不讀未來答案，每候選／角色各自從頭擬合。四欄程式、凍結分數與舊報告保留。

| 前輪實作驗收 | 當輪實際結果 |
| --- | --- |
| 特徵及隔離 | 三欄值與32維前處理等於四欄刪除月份；未知離群值／query答案不影響訓練，缺單或時鐘不符即停止 |
| 單元測試 | 三欄43＋四欄32＝75項全過；H60／基線／消融契約另57項全過，共132項，非全專案測試 |
| 獨立檢查 | 三個fold內外層194項合成核對、驗證CLI31項對抗案例通過，與單元測試分列 |
| 來源保留 | 正式CLI核35公開綁定，32份既有來源不變；另hash核12份原私有綁定不變，未解析凍結分數 |
| 執行界線 | 有合成scaler／Logistic fit、transform及predict；真實資料X、訓練、選C、出分、效能與Dashboard均0 |

以下命令只執行合成驗證，無需原CSV或私有分數：

```powershell
.\.venv\Scripts\python.exe scripts\verify_review_month_ablation_pipeline.py
```

前輪已完成[三欄消融執行準備](docs/STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md)，另存[執行規格](reports/stage5/review_month_ablation_execution_specification.json)及[準備驗收](reports/stage5/review_month_ablation_execution_preflight.json)。該輪只讀既有來源、角色與凍結分數metadata，不建立X或計效能。

| 前輪準備驗收 | 實際結果 |
| --- | --- |
| 來源與名冊 | 51公開＋13私有綁定；73,254研究單、12角色289,973列完整一致 |
| 四欄對照 | 18區塊108,744分數列完整匹配角色truth；未知仍保留，沒有重算分數、指標或選C |
| 私有輸出與配對 | 預留獨立training_v1命名空間與15欄分數格式；完整同ID／順序／truth配對，外層各臂C可不同 |
| 驗證 | 59項新合成測試全過；獨立1,304,928個metadata欄值一致，另21項I/O對抗案例通過 |
| 當時待辦 | 實際訓練入口尚待實作與綁定；三欄分數不存在，實際配對與效果未驗收 |

以下兩行只凍結政策／私有guard及核對準備狀態，均不訓練；需要原本機資料與證據：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_review_month_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\prepare_review_month_ablation.py
```

前輪已完成[正式入口、私有產物與合成驗收](docs/STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md)，74項合成測試及同版來源綁定為本輪執行前提。這些是前輪證據；本輪沒有重跑合成測試或更改凍結程式。

## Stage 5前輪三欄真實離線消融

只移除`purchase_month`，其餘H60、三欄定義、train-only前處理、角色、內層選參及評估保持原規格。

| 已檢視外層開發月 | 三欄獨立選C | 三欄AP | 四欄凍結AP | 三欄減四欄 |
| --- | ---: | ---: | ---: | ---: |
| 2017-12 | 10 | 0.176565 | 0.177118 | -0.000553 |
| 2018-02 | 0.1 | 0.201416 | 0.202077 | -0.000661 |
| 2018-04 | 0.1 | 0.133501 | 0.133589 | -0.000088 |

三個已檢視開發月的等權macro AP：三欄 **0.170494**、四欄 **0.170928**，差 **-0.000434**。三月AP均略降，本輪不支持以移除月份改善預測。這是同ID的開發回測比較，不能當成新的未知測試或正式適用證明。

正式入口只執行一次，完成9次內層＋3次外層fit；三欄依自己的內層AP選C，四欄0fit／0重新選C／0重算分數。12個完整角色與18組雙臂配對通過，每臂108,744列跨候選／角色分數保留未知。五份私有產物留在`.runtime/stage5_review_month_ablation_training_v1/`，未提交逐筆資料或模型。

正式報告見[三欄開發回測](reports/stage5/review_month_ablation_training.json)，獨立對帳見[交付驗收](reports/stage5/review_month_ablation_training_acceptance.json)，完整逐月結果與操作見[實驗文件](docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)。獨立驗收僅從既有雙臂分數重算指標核算，不重新fit或出分。

上述只讀比較已在本輪完成，結果如下。入庫、評分版本與全量母體限制仍在，Stage 4維持待資料、每日10%與11／29／42／73／101五種子，Dashboard暫緩。

## Stage 5前輪雙臂凍結分數診斷

以新[事前規格](reports/stage5/review_ablation_diagnostic_specification.json)只讀原分數，不呼叫builder／pipeline或重新選C。完整結果見[診斷文件](docs/STAGE5_REVIEW_ABLATION_DIAGNOSTICS.md)、[聚合報告](reports/stage5/review_ablation_diagnostics.json)與[驗證](reports/stage5/review_ablation_diagnostic_verification.json)。

| 已檢視外層月 | 已知平均機率 四欄→三欄 | bias百分點 四欄→三欄 | 全query排序Spearman | 平均絕對移動名次 |
| --- | ---: | ---: | ---: | ---: |
| 2017-12 | 13.93% → 13.25% | −2.36 → −3.04 | 0.996215 | 99.2 |
| 2018-02 | 15.65% → 14.18% | −4.94 → −6.40 | 0.977377 | 307.6 |
| 2018-04 | 15.37% → 14.68% | +2.39 → +1.70 | 0.991473 | 168.3 |

三欄多數分數往下移，12月／2月低估加深、4月高估縮小。排名高度相關仍有名次變動，不代表提醒名單相同；本輪沒有建立評論top-k或10%提醒政策。星期、小時在外層均無<30筆支援類別；等待分布右移，但損失差也出現在大量短等待單，不能直接歸因右尾或支持log／clip。

66公開＋21私有來源及每臂18區塊108,744列通過守門；28項新增合成測試、10,389項獨立對帳通過，兩者分列。原24份私有證據不變，本輪0fit／transform／predict／重新選C，未新增AP或未知測試成績。

前輪保留四欄對照、未指定單因子；當時建議的成熟先驗與時間漂移稽核已於本輪完成，結果如下。

## Stage 5本輪成熟先驗與時間漂移稽核

依[事前規格](reports/stage5/review_mature_prior_specification.json)，只用各fit自己的合格H60標籤計先驗，再獨立描述query事後低評率。固定近期W=90／180天採核准區間[fit−60天−W,fit−60天)，不借用最近60天未成熟答案。完整結果見[Stage 5文件](docs/STAGE5_REVIEW_MATURE_PRIOR_AUDIT.md)、[聚合稽核](reports/stage5/review_mature_prior_audit.json)及[驗證](reports/stage5/review_mature_prior_verification.json)。

| 外層開發月 | 全部歷史先驗 | 近期90天 | 近期180天 | query事後已知率 | 歷史已知成熟／成熟未知／未成熟 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2017-12 | 13.12% | 11.98% | 12.63% | 16.29% | 27,108／464／11,891 |
| 2018-02 | 14.22% | 15.64% | 14.12% | 20.59% | 39,448／629／12,405 |
| 2018-04 | 14.58% | 16.95% | 15.09% | 12.98% | 51,433／824／14,219 |

12月／2月的query已知率高於全部歷史，4月反向；近期90天只讓2月的率差縮小，12月與4月反而擴大。這是已檢視角色的比例描述，不是模型效能或窗口選擇。每次fit的query核准均在fit或之後，進先驗的query標籤為0，不能拿事後答案更新參數。

73公開＋22私有來源、12角色289,973列及6個fit情境核對通過；29項合成測試、7,134項獨立比較分列，原27份私有證據不變。共享歷史另有8,035／8,618／11,730張後來才成熟，較早已知y異動0，沒有回填早fit。本輪0特徵／fit／transform／predict／效能／參數更新，個體分數只核hash。

**決策：保留四欄、全部合格歷史對照，不改近期窗、不做先驗／截距修正、不縮短H60。** 下一步先盤點尚未用於選模的時間窗與H60觀察截止、標籤及版本支援，再凍結後續驗證用途；支援不足就列待資料，避免繼續對同三個開發月挑修正。原入庫與版本缺口仍在；Stage 4待資料、每日10%與五種子不變，Dashboard暫緩。

## 專案結構

```text
shop/
├── data/          # 原始資料、特徵快取；本機保留，內有放置說明
├── docs/          # 設定、進度、方法與各輪實驗
├── notebooks/     # 01 資料、02 SQL、03 EDA、04 延遲預測
├── reports/       # 聚合 JSON 與已產出圖表
├── scripts/       # 啟動、匯入、特徵、訓練、推論與診斷
├── sql/           # 建立資料庫、筆數檢查、商業查詢
├── tests/         # 特徵、時間切分、排名與重現契約測試
├── models/        # 本機模型，Git 忽略
├── .runtime/      # 本機服務、下載、日誌與驗證副本，Git 忽略
├── .venv/         # 專案 Python 套件，Git 忽略
├── requirements.txt
└── requirements-lock.txt
```

實驗程式、報告與輸入有 SHA 綁定，沿用原路徑以利重現。不同輪次可能都稱為「102 欄」，實際內容以當輪特徵白名單與規格為準。

## 驗證與維護

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

測試範圍、分組及Windows權限見[測試說明](tests/README.md)。本輪新增29項合成測試與7,134項獨立角色／時鐘對帳通過，模型與參數更新均0；見[本輪驗證](reports/stage5/review_mature_prior_verification.json)。前輪雙臂28項合成／10,389項對帳、原真實12次fit與其他歷史測試各自保留，未重跑全專案discover。

先前專案清整的範圍與驗證保留在[研究歷程](docs/PROJECT_PROGRESS.md#專案清整)，首頁持續只摘要目前結果及入口。

GitHub 保存程式、未執行的 Notebook、文件、聚合報告與圖表。原始資料、特徵快取、本機模型、連線帳密與執行狀態由 Git 忽略；連線設定範本為 [`scripts/db_config_example.py`](scripts/db_config_example.py)。每次推送需同步更新 README，commit 使用繁體中文，其餘協作規則見 [AGENTS.md](AGENTS.md)。
