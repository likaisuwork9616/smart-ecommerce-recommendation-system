# 電商智慧推薦系統

Smart E-Commerce Recommendation System

以 Olist 電商資料練習資料建置、SQL、商業分析、延遲及評論預測，再延伸至 Retailrocket 推薦系統、API 與前端。目前已完成資料環境、SQL與EDA初版；Stage 4維持待資料，Stage 5沿H60契約實作四欄builder與train-only pipeline，以合成資料驗洩漏，尚未進行真實資料訓練。推薦系統與API尚未開始。

## 目前進度

| 階段 | 狀態 | 現有成果 |
| --- | --- | --- |
| Stage 1：資料與環境 | 完成 | Olist 九份 CSV、MySQL、Jupyter 與本機啟動工具 |
| Stage 2：SQL | 完成 | 訂單、品類營收、平均客單價與多表查詢 |
| Stage 3：商業 EDA | 初版完成 | 八張趨勢、品類、付款、評論、配送與地區圖表 |
| Stage 4：延遲預測 | 交接清單／驗收範本完成；資料仍待取得 | 每日10%與五種子維持，研究名冊交付保留；全量資料與正式提醒尚未驗收 |
| Stage 5：評論低評分預測 | builder／受控pipeline已實作；僅合成測試 | 四欄／44維、未知訓練隔離、查詢不讀未來標籤、獨立完整名冊與失敗停止；未實際選C或真實訓練 |
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

## Stage 5：四欄pipeline與洩漏測試

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

[凍結資料集文件](docs/STAGE5_REVIEW_DATASET_SPEC.md)附[機器規格](reports/stage5/review_dataset_specification.json)、[實際核對](reports/stage5/review_dataset_audit.json)及重現指令。私有標籤／切分中繼資料只留`.runtime/stage5_review_dataset_v1/`；沒有建21欄特徵值、模型訓練、預測、效能或Dashboard。前輪不限H的72,613張與本輪H60口徑不同，不能解讀成模型得失。

沿用[最小基線訓練與評估規格](docs/STAGE5_REVIEW_BASELINE_SPEC.md)：

| 規格 | 固定做法，尚未訓練 |
| --- | --- |
| 特徵假設 | 購買月／星期／時及核准等待小時；其餘17個快照候選先排除，兩個原事件時鐘仍只有離線代理假設 |
| 前處理 | 日曆固定one-hot43維＋等待train-only標準化1維；無補值，非法值停止且不刪查詢單 |
| 最小模型 | 合格訓練低評比例常數作參考；L2 Logistic的C=0.1／1／10，只依既定內層AP選參，平手取較小C |
| 評估與未知 | 固定0.5門檻，未知保留全名冊但不參與fit、選參或指標；逐月AP與機率／混淆表，三月皆有效才計macro AP |

前輪[契約稽核](reports/stage5/review_baseline_contract_audit.json)保留來源、時間、未知與類別支援。本輪完成[四欄builder與受控pipeline](docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md)：只讓合格訓練y進scaler／Logistic；查詢保留全部訂單，未來評分／狀態／首答等欄位不影響transform或機率。獨立context保存預期ID與核准時鐘，避免兩份輸入一起少單卻互相通過；fit失敗即停止，不保留半成品。

[合成驗證報告](reports/stage5/review_pipeline_verification.json)只記測試與程式來源。這輪合成fixture確有scaler／模型fit及機率一致性檢查，真實Olist的X、模型訓練、預測、選C、效能與Dashboard均未執行。原H60／基線程式及報告保留，原入庫／評分版本限制仍未解，不能稱營運as-of或全核准效能通過。

下一步可按[凍結規格](reports/stage5/review_baseline_specification.json)決定是否執行離線最小基線，先接入既有來源／私有guard與完整角色名冊，再依內層選參及外層開發評估執行。Stage 5固定42僅作重現設定，沒有五種子成績；Stage 4待資料、每日10%與11／29／42／73／101五種子不變。

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

測試範圍、分組及Windows權限見[測試說明](tests/README.md)。本輪新增32項合成洩漏／失敗測試全過；連同Stage 5既有三組，87項全過、5.821秒。獨立合成300項檢查與CLI六種失敗拒收均通過。正式驗證綁10份公開來源，同版重跑報告bytes相同；57份Markdown／708個本機連結及85份JSON解析／索引通過。合成測試確有scaler／Logistic fit與機率檢查，真實資料X／訓練／預測／選C／效能及Dashboard未執行。前輪來源盤點、H60／基線對帳與更早完整867項測試保留各輪紀錄，不當成本輪全專案成績；原Stage 4、H60與基線程式／報告保留。

先前專案清整的範圍與驗證保留在[研究歷程](docs/PROJECT_PROGRESS.md#專案清整)，首頁持續只摘要目前結果及入口。

GitHub 保存程式、未執行的 Notebook、文件、聚合報告與圖表。原始資料、特徵快取、本機模型、連線帳密與執行狀態由 Git 忽略；連線設定範本為 [`scripts/db_config_example.py`](scripts/db_config_example.py)。每次推送需同步更新 README，commit 使用繁體中文，其餘協作規則見 [AGENTS.md](AGENTS.md)。
