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

## 處理資料與模型

| 位置 | 用途 |
| --- | --- |
| `data/processed/` | 特徵快取、逐筆預測、排名與中間資料 |
| `models/`（專案根目錄） | 原版、平衡模式及各輪研究模型 |
| `.runtime/`（專案根目錄） | 下載、執行紀錄、獨立核對及Notebook執行副本 |
| [`reports/`](../reports/README.md) | 可公開的聚合JSON、事前規格與圖表 |

快取與模型不隨repository提供。重現既有實驗前，先讀對應[方法文件](../docs/README.md)的來源與步驟；不要為補缺檔就依序重跑全部訓練。特徵快取包含不同欄位集合與答案時鐘，相同「102欄」不代表相同內容。

`data/sample/`目前沒有追蹤的範例資料，不作為可執行流程的必要輸入。

## Stage 5評論預測資料

[可行性盤點](../docs/STAGE5_REVIEW_PREDICTION_FEASIBILITY.md)只讀原始CSV的評論鍵、評分與建立／回答時鐘。評論一單可多筆，review_id非全域唯一；標籤先按order_id取最早記錄回答，再查是否晚於核准，不以最低／平均分或無評論填負例。

[H60資料集](../docs/STAGE5_REVIEW_DATASET_SPEC.md)固定核准後60天首答、未知與內外層時間契約。沒有評論、超窗、未成熟或品質隔離都是nullable y，73,254張完整名冊均保留。私有order_labels.csv是C=2018-07-01的標籤審計，歷史fit必須用角色截止遮罩後的y，不能join它取得未來答案；它與split_membership.csv只有身分、標籤與審計欄，不能當X。

四欄基線只用購買月／星期／時及核准等待小時，三欄消融再移除購買月份；沒有建立原候選21欄。兩事件時鐘只有快照代理假設，研究來源版本通過不能補足原入庫／修訂／全量母體證據。Stage 4的最終送達cohort、延遲label與凍結分數不直接沿用。

## Stage 6 RFM資料

[輸入盤點](../docs/STAGE6_RFM_FEASIBILITY.md)只讀原orders／customers／items／payments：客戶經customer_id連接、以customer_unique_id彙總；商品與付款先各按order聚合，不直接明細×付款join。[資料集契約](../docs/STAGE6_RFM_DATASET_SPEC.md)保留T前合格歷史顧客，窗口[S,T)同集合計R／F／M；缺商品不刪訂單／顧客，商品未知或窗口有隔離時M=null，乾淨零活動才R=null、F=0、M=0。

M是快照商品毛額，缺退款、原可得與修訂證據，不升格淨額或營運as-of。個體ID、RFM值及私有digest不提交，Git clone不含這些檔案；現有私有資料集與G1描述只做唯讀驗收，不刪檔重播。

## 私有研究產物位置

下列目錄都在Git忽略的`.runtime/`。已有產物不得刪除後重跑；缺檔或版本不符時，對應CLI會停止，不能以重訓或重建補證據。

| 階段／研究 | 本機位置 | 內容與注意 |
| --- | --- | --- |
| Stage 4資料交接（尚未建立） | `.runtime/data_handoffs/<handoff_id>/` | 未來填寫的交接紀錄、原始匯出與逐ID證據；空範本不是新資料 |
| Stage 5 H60資料集 | `.runtime/stage5_review_dataset_v1/` | order_labels.csv、split_membership.csv、manifest.json |
| Stage 5最小基線規格 | `.runtime/stage5_review_baseline_v1/` | input_guard.json；原H60 bundle不改 |
| Stage 5四欄離線基線 | `.runtime/stage5_review_baseline_training_v1/` | inner／outer分數、fit_audit、manifest、input_guard；fit診斷含本機係數，不是公開服務模型 |
| Stage 5月份消融規格與三欄實作 | `.runtime/stage5_review_month_ablation_v1/`、`.runtime/stage5_review_month_ablation_pipeline/` | 規格guard與合成驗證日誌 |
| Stage 5三欄執行準備與正式入口 | `.runtime/stage5_review_month_ablation_execution_v1/`、`.runtime/stage5_review_month_ablation_dispatcher_v1/` | input_guard與合成試跑紀錄 |
| Stage 5三欄真實消融 | `.runtime/stage5_review_month_ablation_training_v1/` | inner／outer分數、fit_audit、paired_acceptance、manifest；每臂108,744列含跨候選／角色重複出分，不是獨立訂單數 |
| Stage 5只讀診斷與稽核 | `.runtime/stage5_review_ablation_diagnostics_v1/`、`.runtime/stage5_review_mature_prior_v1/`、`.runtime/stage5_review_validation_windows_v1/` | 各輪input_guard；時間窗另有使用紀錄 |
| Stage 5新時間窗交接（尚未建立） | `.runtime/review_window_handoffs/<handoff_id>/` | 未來逐月交接副本，與原dataset／兩臂training_v1分開 |
| Stage 6私有RFM資料集 | `.runtime/stage6_rfm_dataset_v1/`、`.runtime/stage6_rfm_dataset_build_v1/`、`.runtime/stage6_rfm_builder_independent/` | 93,234列customers、99,421列order_decisions與manifest；output_guard；獨立重算參考與比較 |
| Stage 6評估規格與描述器 | `.runtime/stage6_rfm_evaluation_spec_v1/`、`.runtime/stage6_rfm_description_implementation_v1/`、`.runtime/stage6_rfm_description_independent/` | input_guard、合成驗收與獨立oracle收據 |
| Stage 6真實描述（G1） | `.runtime/stage6_rfm_description_execution_v1/`、`.runtime/stage6_rfm_evaluation_v1/` | input／output guard；description、customer roster、order roster、manifest四檔 |
| Stage 6 G2規則候選 | `.runtime/stage6_rfm_rule_candidate_implementation_v1/`、`.runtime/stage6_rfm_rule_candidate_execution_v1/` | 合成驗收guard與日誌、真實執行準備的input_guard；未來真實輸出`.runtime/stage6_rfm_rule_candidate_v1/`尚未建立 |

## Retailrocket

規劃用於瀏覽、加購、購買與推薦研究，目前尚未啟動。`data/raw/retailrocket/`只作預留位置，不代表已完成資料匯入、特徵或推薦模型。
