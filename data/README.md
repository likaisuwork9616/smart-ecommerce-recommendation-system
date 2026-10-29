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

目前沒有可接續 Olist 的新資料來源。後續同ID核准清冊、雙時間版本及日結／入庫對帳，使用[資料交接清單](../docs/templates/daily_data_handoff/README.md)與[驗收紀錄範本](../docs/templates/daily_data_handoff/acceptance_record.template.md)。已填紀錄、原始匯出、匿名映射與逐ID證據放Git忽略的`.runtime/data_handoffs/<handoff_id>/`，先作獨立交接，不直接替換原凍結Olist／特徵／帳本。空範本不是新資料或驗收結果。

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

目前可用的私有研究鏈為獨立 **v2＋G3**；下表 v1 路徑保留歷史定位，不代表本機仍存在。原 v1 私有檔未尋獲後，已依相同來源與方法另建新版本，沒有補寫 v1 驗收紀錄，詳見[v2 重建](../docs/STAGE6_RFM_REBUILD_V2.md)及[G3 結果](../docs/STAGE6_RFM_G3_V2.md)。

2026-10-27 的[第二快照盤點](../docs/STAGE6_RFM_TEMPORAL_DATA_INVENTORY.md)確認原九表、下載與備份每表均只有同一內容版本。原 T 後 20 筆購買沒有合格新增單，後期全量／原可得與修訂／完成水位仍缺；不得把再解壓 ZIP 或重新匯入 MySQL 當新時間快照。新資料先按[交接清單](../docs/templates/rfm_temporal_handoff/README.md)交至 `.runtime/rfm_temporal_handoffs/<handoff_id>/`，本輪未建立此交接目錄，也未建 T2 RFM。

[輸入盤點](../docs/STAGE6_RFM_FEASIBILITY.md)只讀原orders／customers／items／payments：客戶經customer_id連接、以customer_unique_id彙總；商品與付款先各按order聚合，不直接明細×付款join。[資料集契約](../docs/STAGE6_RFM_DATASET_SPEC.md)保留T前合格歷史顧客，窗口[S,T)同集合計R／F／M；缺商品不刪訂單／顧客，商品未知或窗口有隔離時M=null，乾淨零活動才R=null、F=0、M=0。

M是快照商品毛額，缺退款、原可得與修訂證據，不升格淨額或營運as-of。個體ID、RFM值及私有digest不提交，Git clone不含這些檔案；現有私有資料集與G1描述只做唯讀驗收，不刪檔重播。

## UCI 回溯 RFM 契約 v1

[凍結契約](../docs/STAGE6_UCI_RFM_CONTRACT_V1.md)已固定 T1 [2009-12-01, 2010-12-01)、T2 [2010-12-01, 2011-12-01)，各 365 天。原始檔與既有 SQLite 保持不變；後續正式 RFM 已依各 T 前原列重新建置，完整結果見[建置驗收](../docs/STAGE6_UCI_RFM_BUILD_V1.md)，沒有沿用全檔候選視圖當快照資格。

正式逐筆資料已保存在 `shop-mysql-runtime/uci_rfm_dataset_v1/<arm>/<T_id>/`，共八組顧客、發票、逐列排除與去重帳（32 CSV），並有 root_manifest／output_guard。獨立 reference.sqlite、測試與事前 guard 位於 `shop-mysql-runtime/verification/uci-rfm-build-v1/`。已完成的契約 guard／log 放 `shop-mysql-runtime/uci_rfm_contract_v1/`，合成與交付查核放 `shop-mysql-runtime/verification/uci-rfm-contract-v1/`；皆在 `shop` 內並由 Git 忽略。原 Excel、下載與既有研究不可刪檔重播。

## UCI 固定切點與跨期分級

[跨期比較](../docs/STAGE6_UCI_RFM_TEMPORAL_V1.md)已完成。`shop-mysql-runtime/uci_rfm_temporal_v1/` 保存單次 main／T1 的 cutpoints.json、八組 scores.csv、panel.csv、manifest 與 guard；個體與配對名冊全部由 Git 忽略，仍在 `shop`。原 `uci_rfm_dataset_v1/` 32 CSV 沒有重建或修改。

現有結果只用 `run_uci_rfm_temporal_v1.py --verify` 核保存 bytes。單軸箱達人數門檻，但主口徑 T1／T2 有 87／83 個非空聯合小組不足 50 人，不能把整個分級表當成已驗證的營運客群。

## UCI v1 研究封存

[Stage 6 交付與適用說明](../docs/STAGE6_RFM_RESEARCH_HANDOFF.md)已整理完成。封存 ZIP 位於 `shop-mysql-runtime/backups/uci_rfm_v1_research_release_v1.zip`，含 UCI 必要原始來源、原始解碼 SQLite、八組資料／分級、排除／去重帳、切點、manifest／guard、程式與驗收證據。

`shop-mysql-runtime/uci_rfm_release_v1/` 保存封存 manifest／guard；公開[收據](../reports/stage6/uci_rfm_v1_research_release.json)只列檔案清單、hash、大小、聚合與限制。逐筆、ZIP 及執行檔全由 Git 忽略，均在 `shop` 內。原檔不搬移或刪除；這是同磁碟備份，尚無異地副本。

## 私有研究產物位置

[公開來源查核](../docs/STAGE6_RFM_PUBLIC_SOURCE_SEARCH.md)仍未找到合格 Olist 後期包。其後已完整取得 UCI Online Retail II：原 ZIP、XLSX、來源頁及 manifest 保存在專案內 `data/raw/online_retail_ii/`；兩表共 1,067,371 筆，已完成[品質盤點與獨立核對](../docs/STAGE6_UCI_RETAIL_II_INTAKE.md)。逐筆 SQLite 與 guard 放在 `shop-mysql-runtime/uci_retail_ii_intake_v1/`，原始 Excel 未改寫；後續獨立 RFM 資料集已按凍結契約建置並驗收，不覆寫此原始盤點來源。以上全部由 Git 忽略，且實際都在 `shop` 內；不與 Olist 匿名顧客混接。

下列目錄都在Git忽略的`.runtime/`。已有產物不得刪除後重跑；缺檔或版本不符時，對應CLI會停止，不能以重訓或重建補證據。

目前本機的實體目錄為使用者搬移後的 `shop-mysql-runtime/`；`.runtime` 以 junction 指向它，所以下列既有路徑仍可使用。兩處都受 Git 忽略；移機還原時須一併保留此路徑對應，連結本身不會由 `git clone` 建立。

| 階段／研究 | 本機位置 | 內容與注意 |
| --- | --- | --- |
| Stage 6 現行 v2／G2 | `.runtime/stage6_rfm_rebuild_v2/` | execution/dataset、description、candidate 與 input／output guard；已完成，只用對應 --verify |
| Stage 6 現行 G3 | `.runtime/stage6_rfm_g3_v2/` | 固定五種子抽樣位置、全名冊分配、聚合與 guard；保留 25 個小組限制 |
| Stage 6 研究備份 | `.runtime/backups/stage6_rfm_rebuild_v2.zip`、`.runtime/backups/stage6_rfm_g3_v2.zip` | 含個體資料，同一磁碟備份；不是第二期交易來源 |
| Stage 6 跨期資料交接（尚未建立） | `.runtime/rfm_temporal_handoffs/<handoff_id>/` | 未來來源版本、四表、時鐘／完整性與對帳證據；空範本不算新快照 |
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

2026-10-28 已取得發布者 Kaggle 第2版完整官方 ZIP，保存在 `data/raw/retailrocket/ecommerce-dataset-v2.zip`，大小304,719,974 bytes，SHA `5dc06173eaa4a4d3b0a5f6afc4daffb0218d95e409aaacba5fdaa0214eacf2a2`。旁存 API／來源頁／授權快照與 `source_manifest.json`，全部在 `shop` 內並由 Git 忽略。

包內四份 CSV 已完整掃描：events 2,756,101列、item_properties兩份合計20,275,902列、category_tree 1,669列。檔案讀到EOF、CRC／SHA及兩路44項核對通過。原 ZIP 不改寫，也沒有把資料複製到專案外。

原授權為 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)，限條件內非商業研究，保留署名與適用的改作分享條件；不隨程式授權改授權原始資料。來源 SQLite 在 `shop-mysql-runtime/retailrocket_intake_v1/`，契約 guard 在 `shop-mysql-runtime/retailrocket_contract_v1/`，這些是來源盤點與契約證據。正式推薦資料已另建於 `shop-mysql-runtime/retailrocket_dataset_v1/`：16份CSV、SQLite、manifest及output_guard，保留去重／排除與跨界帳，全部由Git忽略。

[來源與契約說明](../docs/STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md)及[機器規則](../docs/contracts/retailrocket_recommendation_v1.json)已固定。事件UTC涵蓋2015-05-03至09-18，但屬性05-10才開始，缺值不回填；v1建置／逐格驗收已完成，三窗query為642,619／166,897／92,086，熱門baseline／完整候選執行規格已另行凍結，P0已依凍結入口完成一次真實train fit與完整validation／獨立反讀，預留測試仍locked，不與Olist／UCI匿名ID混接。最新[資料建置與反讀](../docs/STAGE8_RETAILROCKET_BUILD_V1.md)完整列出每份CSV、分母、支援及限制。


Stage 9 [熱門baseline與評估執行規格](../docs/STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md)的來源guard與初始locked收據在 `shop-mysql-runtime/retailrocket_popularity_spec_v1/`，規格測試／交付紀錄在 `shop-mysql-runtime/verification/retailrocket-popularity-spec-v1/`，均在shop內並由Git忽略。規格輪當時尚未建立 `shop-mysql-runtime/retailrocket_popularity_v1/`；後續本輪已另建development。最終重估／預留測試仍未啟用，不得將舊規格或合成收據當作那些成績。


[P0／評估器實作與開發入口](../docs/STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md)的guard及locked快照在 `shop-mysql-runtime/retailrocket_popularity_implementation_v1/`；合成／oracle／入口反例、原狀及日誌在 `shop-mysql-runtime/verification/retailrocket-popularity-implementation-v1/`，全在shop並由Git忽略。實作輪當時尚無真實development；本輪已另建真實development，後期refit／test仍未建立，合成item_counts與真實統計分開保存。


[P0真實開發結果與反讀](../docs/STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md)已完成；逐item次數、三份逐query輸出與fit audit／aggregate／started／manifest／guard在 `shop-mysql-runtime/retailrocket_popularity_v1/development/`。本輪有1,823,388筆train view、166,897筆validation，原始資料及舊成果不覆寫。`shop-mysql-runtime/verification/retailrocket-popularity-development-v1/`保存日誌、原狀與鎖定快照SHA檢查；全在shop且Git忽略。

## Retailrocket 共現／P0 配對規格 v1（規格輪）

[凍結規格](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_PAIRED_SPEC_V1.md)重用既有資料與 P0 排名／指標，固定同 166,897 validation 名冊、完整候選與分母。train session 商品集合計數含 singleton，query 歷史限同 session 截至當下；預留測試仍 locked。82 來源 SHA、131 項一致性檢查、64 項規格測試通過；該規格輪只核資料 bytes，0 CSV 列解析、新 fit／排名／比較／bootstrap。

私人規格快照／guard 位於 `shop-mysql-runtime/retailrocket_cooccurrence_spec_v1/`，原狀、日誌及文件更新／交付驗證位於 `shop-mysql-runtime/verification/retailrocket-cooccurrence-spec-v1/`；都在 shop 並由 Git 忽略。該規格輪尚未建立真實C1執行目錄；後續已於下節完成真實執行。原資料 v1、P0、UCI 封存、`.runtime` junction 與其實際 `shop-mysql-runtime` 位置保持原狀；原始／逐查詢／模型／抽樣明細不加入 Git。

## Retailrocket C1 實作、train-only 成本與真實入口

[實作／限制／操作](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_IMPLEMENTATION_V1.md)與[凍結入口](../reports/stage10/retailrocket_cooccurrence_v1_validation_specification.json)已完成。55測試、104來源與兩組合成oracle通過；真實train-only成本為1,180,256 sessions、2,292,165 pair發射，獨立1,180,256列／5,901,280格核對一致。只建立session基數帳，沒有真實S_i／C_ij模型或validation／test商品／target解析。

私人實作guard位於`shop-mysql-runtime/retailrocket_cooccurrence_implementation_v1/`；合成／成本／日誌／原狀／交付檢查在`shop-mysql-runtime/verification/retailrocket-cooccurrence-implementation-v1/`，全部在shop並由Git忽略。該實作輪尚無真實C1目錄，後續結果見下節；不重訓P0，無final-refit或test模式。原資料、P0、舊規格／報告、UCI封存與runtime實際位置保持原狀。

## Retailrocket C1／P0一次真實配對 validation

C1 NDCG@10 0.106400714，配對差 0.104718885；166,897 validation／2,000次bootstrap及獨立反讀完成，test locked。模型／完整session lineage／query歷史與有理排序／抽樣／oracle SQLite及資源、manifest、guard保存在`shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/`；本輪原狀、日誌、交付核對在`shop-mysql-runtime/verification/retailrocket-cooccurrence-validation-v1/`，均在shop內且Git忽略。沒有建立final-refit／test輸出或usage journal，P0原檔與鎖定快照保持相同SHA。

[完整結果與操作](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_VALIDATION_V1.md)、[正式聚合](../reports/stage10/retailrocket_cooccurrence_v1_validation.json)、[獨立驗收](../reports/stage10/retailrocket_cooccurrence_v1_validation_acceptance.json)為公開入口；逐ID／模型與抽樣明細不加入Git。

## C1／P0研究交付與證據保存

結果證據包位於`shop-mysql-runtime/backups/retailrocket_c1_p0_research_release_v1.zip`，控制清單在`shop-mysql-runtime/retailrocket_c1_p0_release_v1/`，日誌與原狀核對在`shop-mysql-runtime/verification/retailrocket-c1-p0-release-v1/`；全部在shop內、Git忽略。

102個payload檔＋1份manifest，257,447,194 bytes（245.521 MiB）；全部CRC／SHA讀回通過，另列98份包外但仍在shop內依賴。原始資料／完整推薦資料集／.venv等未全部收進ZIP，但仍留shop內並有依賴SHA；此包不是完整環境還原或異地備援。P0與C1原結果namespace不覆寫；`.runtime`仍指向原`shop-mysql-runtime`，final／test及usage journal未建立。見[交付與還原範圍](../docs/STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md)及[保存收據](../reports/stage10/retailrocket_c1_p0_v1_research_release.json)。

## Stage 11：D1 比較規格與既有資料保存

本輪只固定有向相鄰 basket 的 session 關聯規格；真實 CSV／JSONL 僅核 binary SHA，0 列解析，沒有擬合、排名、指標或成本掃描。固定原 C1 S_i／H(q)、P0 次數、166,897 validation 名冊及完整分母，不覆寫 P0／C1 或資料 v1。候選選擇前 validation 已曝光，冷商品、小組及回溯限制保留。

新 initial locked scope／output guard 在 `shop-mysql-runtime/retailrocket_directed_spec_v1/`，本輪日誌與原狀核對在 `shop-mysql-runtime/verification/retailrocket-directed-spec-v1/`，均在 shop 且 Git 忽略。未建立未來 D1 真實執行／final／test namespace 或 usage journal；原 C1／P0 交付包與 .runtime 連結保持原狀。方法與下一步見[Stage 11 規格](../docs/STAGE11_RETAILROCKET_DIRECTED_SPEC_V1.md)。

## Stage 11：D1 實作與 train-only 成本（實作輪）

1,823,018 train baskets／1,180,256 sessions；相鄰 642,762 對、原始有向發射 493,669 次、session 去重邊量 479,231，重複 14,438 次。兩遍只解碼 train 商品，獨立逐 session 成本 1,180,256 列／10,622,304 格一致；未建全域 D 模型／新 S，未解碼真實 validation／test 商品或 target。

逐 session 成本、SQL、兩組合成與日誌在 `shop-mysql-runtime/verification/retailrocket-directed-implementation-v1/`；凍結 guard／gate 在 `shop-mysql-runtime/retailrocket_directed_implementation_v1/`，均在 shop 且 Git 忽略。真實 D1 執行／final／test 目錄未建立；P0／C1、原交付包與 .runtime 連結保持原狀。見[實作說明](../docs/STAGE11_RETAILROCKET_DIRECTED_IMPLEMENTATION_V1.md)。

## Stage 11：一次真實 D1 三臂 validation（執行輪）

D1 NDCG@10 0.099799771，D1−C1 差 -0.006600944，95% 區間 [-0.007511893, -0.005716747]；166,897 validation／2,000 次主要 bootstrap 與獨立反讀完成。D1 模型、原樣共享 support、完整 session lineage、三臂 query 歷史與有理排序、新抽樣、oracle SQLite、resource／manifest／guard 在 `shop-mysql-runtime/retailrocket_directed_paired_v1/`；本輪原狀、執行日誌與交付核對在 `shop-mysql-runtime/verification/retailrocket-directed-validation-v1/`。所有檔案都在 shop 且私有產物由 Git 忽略。

P0／C1 原檔、gate 與交付包保留原 SHA；沒有 final-refit／test 輸出或 usage journal，.runtime 連結不變。Validation 已曝光、冷商品與小組限制保留；incoming／outgoing 診斷不取代共同冷商品定義。完整結果見[執行與適用](../docs/STAGE11_RETAILROCKET_DIRECTED_VALIDATION_V1.md)。

## Stage 12：一次真實 validation 的部分證據（最新）

`shop-mysql-runtime/retailrocket_session_knn_paired_v1/` 已有主要 train／validation／bootstrap 與未完成的 oracle.sqlite。依使用者整輪 3 小時 30 分鐘上限停止，缺少 acceptance／output_guard，不得當成通過驗收或重跑。外部觀測、停止與 SHA 清單在 `shop-mysql-runtime/verification/retailrocket-session-knn-validation-v1/`；原始資料、模型與逐筆輸出維持 Git 忽略。公開只列停止與保存事實，見[保存報告](../reports/stage12/retailrocket_session_knn_v1_validation_attempt.json)。預留測試 locked。

## Stage 12：真實 validation 入口的合成來源證據（前輪）

`shop-mysql-runtime/verification/retailrocket-session-knn-validation-entry-v1/` 保存合成原格式 CSV／JSONL、同一單次入口的模型／query／bootstrap／SQL 反讀與測試日誌；`shop-mysql-runtime/retailrocket_session_knn_validation_entry_v1/` 保存來源 guard／started／locked scope。15 份直接真實輸入只做 bytes 綁定，本輪未解析真實資料／對照 CSV、JSONL；不重跑 train 成本。未來真實執行目錄 `shop-mysql-runtime/retailrocket_session_knn_paired_v1/` 本輪保持不存在，final／test 仍 locked。見[入口驗收](../reports/stage12/retailrocket_session_knn_v1_validation_entry_acceptance.json)。

## Stage 12：K1 合成證據與 train-only 成本（前輪）

`shop-mysql-runtime/verification/retailrocket-session-knn-implementation-v1/` 保存純合成 inputs／model／queries／bootstrap／SQL oracle，以及真實 train 的逐 session 成本 CSV／資源紀錄；`shop-mysql-runtime/retailrocket_session_knn_implementation_v1/` 保存 guard／started／locked snapshot。兩遍只解碼 train 商品陣列，對照原 C1 lineage／support；沒有真實 K1 索引、validation／test 商品解析或 final／test 產物。公開聚合見[實作驗收](../reports/stage12/retailrocket_session_knn_v1_implementation_acceptance.json)。

## Stage 12：新時間資料可取得性（前輪）

本輪只保存官方 metadata 與 HEAD 標頭，位於 `shop-mysql-runtime/verification/retailrocket-stage12-spec-v1/`；公開摘要見[來源盤點](../reports/stage12/retailrocket_stage12_inventory_v1.json)。Retailrocket 未確認同來源延伸；外部多品類七檔 HEAD 200、化妝品五檔 metadata 可讀，均未下載事件／未驗收。沒有新 raw dataset、K1 索引、final／test 產物。規格 guard 在 `shop-mysql-runtime/retailrocket_session_knn_spec_v1/`，比較沿用既有 train／已曝光 validation，預留測試保持 locked。

## Stage 11：三臂研究交付與證據保存

144 個 payload 檔＋1 份 manifest，共 145 個 ZIP 成員，649,850,977 bytes（619.746 MiB）；全部成員 CRC／SHA-256 反讀通過，另列 159 份包外依賴。新 ZIP 位於 `shop-mysql-runtime/backups/retailrocket_three_arm_research_release_v1.zip`，manifest／guard 在 `shop-mysql-runtime/retailrocket_three_arm_release_v1/`，日誌與原狀核對在 `shop-mysql-runtime/verification/retailrocket-three-arm-release-v1/`；全部在 shop 且由 Git 忽略。

三臂結果、既有 C1／P0 ZIP、gate 與 .runtime 連結原狀保留；0 新 fit／排名／抽樣，預留測試 locked。舊 ZIP 列為包外依賴，原始資料／完整資料集／.venv 未全部包入，非完整環境還原或異地備援。見[交付、適用與還原](../docs/STAGE11_RETAILROCKET_THREE_ARM_RESEARCH_HANDOFF_V1.md)及[保存收據](../reports/stage11/retailrocket_three_arm_v1_research_release.json)。
