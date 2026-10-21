# 資料放置與保留方式

資料集、處理後特徵與逐筆分數僅保留在本機。此目錄的說明文件納入Git，`raw/`與`processed/`由Git忽略。

## Olist

從[Olist資料集頁面](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)取得以下九個CSV，直接放在`data/raw/olist/`，保留原檔名。

| 檔名 | 匯入後資料表 |
| --- | --- |
| `olist_customers_dataset.csv` | `customers` |
| `olist_orders_dataset.csv` | `orders` |
| `olist_order_items_dataset.csv` | `order_items` |
| `olist_order_payments_dataset.csv` | `order_payments` |
| `olist_order_reviews_dataset.csv` | `order_reviews` |
| `olist_products_dataset.csv` | `products` |
| `olist_sellers_dataset.csv` | `sellers` |
| `olist_geolocation_dataset.csv` | `geolocation` |
| `product_category_name_translation.csv` | `product_category_name_translation` |

Stage 1–3使用MySQL進行查詢；建立與匯入流程見[本機環境指南](../docs/LOCAL_SETUP.md)，資料表關係見[核心ERD](../docs/olist_core_erd.png)，查詢入口見[SQL導覽](../sql/README.md)。匯入程式會取代同名資料表，不是一般只讀檢查指令。

Stage 4直接讀CSV，不需要啟動MySQL。原始欄位、延遲標記與時間範圍見[延遲模型方法](../docs/STAGE4_DELAY_PREDICTION.md)。地理特徵使用的地理表、各輪快取和來源SHA依當輪規格，不可用其他版本直接替換。

[事件與承諾版本來源查核](../docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md)確認：本機九表與同內容ZIP沒有取消／非送達結案事件的取得時鐘或承諾版本；本機DB與2026匯入binlog也不能補成原業務日誌。官方API文件僅有線索，未取得同匿名ID的授權歷史匯出與涵蓋證明，目前列為待資料。新來源需先驗收事件／取得／生效時間及ID映射，不以檔案mtime或最終status回填。

目前沒有新資料來源。後續同ID核准清冊、雙時間版本及日結／入庫對帳，使用[資料交接清單](../docs/templates/daily_data_handoff/README.md)與[驗收紀錄範本](../docs/templates/daily_data_handoff/acceptance_record.template.md)。已填紀錄、原始匯出、匿名映射與逐ID證據放Git忽略的`.runtime/data_handoffs/<handoff_id>/`，先作獨立交接，不直接替換原凍結Olist／特徵／帳本。空範本不是新資料或驗收結果。

## Stage 5評論預測資料

[Stage 5可行性盤點](../docs/STAGE5_REVIEW_PREDICTION_FEASIBILITY.md)只讀原始CSV的評論鍵、評分與建立／回答時鐘，以及六表基本輸入支援。評論一單可多筆，review_id非全域唯一；標籤先按order_id取最早記錄回答，再查是否晚於核准，不以最低／平均分或無評論填負例。首輪候選為核准時點21個基本聚合欄，但缺原取得／版本時鐘，不能稱為已驗證線上可用。

最新[凍結資料集](../docs/STAGE5_REVIEW_DATASET_SPEC.md)固定核准後60天首答、未知與內外層時間契約。私有order_labels.csv、split_membership.csv及manifest.json放Git忽略的.runtime/stage5_review_dataset_v1/；前者是C=2018-07-01的標籤審計，歷史fit必須用角色截止遮罩後的y，不能join前者取得未來答案。兩CSV只有9／12個身分、標籤與審計欄，不能當X。

沒有評論、超窗、未成熟或品質隔離仍是nullable y；73,254張完整名冊均保留。公開只提交來源SHA、規格與聚合，不公布個體ID／標籤或私有digest。Stage 5四欄基線採四個事件時間特徵，沒有建立原候選21欄；Stage 4的最終送達cohort、延遲label與凍結分數不直接沿用。

前輪[最小基線規格](../docs/STAGE5_REVIEW_BASELINE_SPEC.md)只用購買月／星期／時及核准等待小時，其餘快照候選先排除；兩事件時鐘仍只有快照代理假設。該輪不建X或fit，私有input_guard放.runtime/stage5_review_baseline_v1/，原H60 bundle不改。

前輪[builder／pipeline實作](../docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md)只用手造fixture驗洩漏。[離線最小基線](../docs/STAGE5_REVIEW_OFFLINE_BASELINE.md)串接原來源SHA、私有guard、manifest及收據，再核對完整角色名冊，才用真實四欄資料fit。未知訓練列不參與fit，query未來標籤先清空但整份名冊保留；計分另用自己的角色truth。

該輪inner_scores.csv、outer_scores.csv、fit_audit.json、manifest.json與input_guard.json留`.runtime/stage5_review_baseline_training_v1/`。其中fit診斷含本機係數／統計，不是公開可用服務模型；無模型序列化或營運通知入口。研究來源版本通過仍不能補足原入庫／修訂／全量母體證據。

前輪[月份消融規格](../docs/STAGE5_REVIEW_MONTH_ABLATION_SPEC.md)只刪除purchase_month，原H60、完整角色名冊與未知政策不改；該輪私有guard在`.runtime/stage5_review_month_ablation_v1/`。[三欄實作驗證](../docs/STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md)僅用合成fixture，日誌在`.runtime/stage5_review_month_ablation_pipeline/`。

前輪[執行準備](../docs/STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md)讀原完整角色與四欄分數，只驗metadata／名冊／合法機率，不重訓或計效能。新guard在`.runtime/stage5_review_month_ablation_execution_v1/input_guard.json`，原13私有綁定不變；當時預定的`.runtime/stage5_review_month_ablation_training_v1/`尚無產物；後續真實交付見下段。缺來源或版本變動即停止，不能把本輪輸出規格當成已取得新入庫／版本證據。

## 處理資料與模型

| 位置 | 用途 |
| --- | --- |
| `data/processed/` | 特徵快取、逐筆預測、排名與中間資料 |
| `models/`（專案根目錄） | 原版、平衡模式及各輪研究模型 |
| `.runtime/`（專案根目錄） | 下載、執行紀錄、獨立核對及Notebook執行副本 |
| [`reports/`](../reports/README.md) | 可公開的聚合JSON、事前規格與圖表 |

快取與模型不隨repository提供。重現既有實驗前，先讀對應[方法文件](../docs/README.md)的來源與步驟；不要為補缺檔就依序重跑全部訓練。特徵快取包含不同欄位集合與答案時鐘，相同「102欄」不代表相同內容。

`data/sample/`目前沒有追蹤的範例資料，不作為可執行流程的必要輸入。

## Retailrocket

規劃用於瀏覽、加購、購買與推薦研究，目前尚未啟動。`data/raw/retailrocket/`只作預留位置，不代表已完成資料匯入、特徵或推薦模型。

前輪[正式入口與私有writer驗收](../docs/STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md)的guard及合成日誌留在`.runtime/stage5_review_month_ablation_dispatcher_v1/`。前輪[真實三欄消融](../docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)完成一次9＋3次fit；`training_v1/`已寫入inner／outer分數、fit_audit、paired_acceptance及manifest五份私有檔。每臂108,744列含跨候選／角色重複出分，不能當獨立訂單數。原16份私有證據不變，未增加入庫、評分版本或全量母體證據；已有產物不得刪除後重跑。
前輪[雙臂只讀診斷](../docs/STAGE5_REVIEW_ABLATION_DIAGNOSTICS.md)僅解析原分數、角色與事件時鐘，沒有新個體分數、X或模型。新私有guard在`.runtime/stage5_review_ablation_diagnostics_v1/input_guard.json`，原24份私有證據bytes不變；來源21份私有綁定與66份公開綁定分開，未補足入庫／版本或全量母體缺口。

前輪[成熟先驗與時間漂移稽核](../docs/STAGE5_REVIEW_MATURE_PRIOR_AUDIT.md)只解析原角色的可得標籤與時鐘，不讀分數值或係數，沒有新逐筆y、分數、X或模型。新guard留`.runtime/stage5_review_mature_prior_v1/input_guard.json`；原27份私有證據不變。H60、12完整角色、未知與未成熟保持原樣，後來成熟的標籤不回填早fit；入庫／版本／全量母體缺口未補足。

最新[後續時間窗盤點](../docs/STAGE5_REVIEW_VALIDATION_WINDOWS.md)只讀評論身分與時鐘，未讀review_score值或建立新y。2018-05至09共26,027張原匯出有效核准均待資料，尚非完整上游名冊或已驗收H60標籤；原C=2018-07-01及既有bundle不改。新歷史紀錄／guard在`.runtime/stage5_review_validation_windows_v1/`，原30份私有證據不變；補齊新觀察／版本及標籤角色契約前，不能拿較晚答案選模或校準。

本輪[2018年5–9月交接清單與範本](../docs/templates/review_window_handoff/README.md)備妥，但沒有新來源、標籤或交接實例。日後真實副本及原始清冊、版本鏈、H60完成與逐ID對帳留Git忽略的`.runtime/review_window_handoffs/<handoff_id>/`，與原dataset／兩臂training_v1分開；不得覆寫舊guard或把前輪匯出數抄成已接受全量N。
