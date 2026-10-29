# 文件導覽

先看[專案首頁](../README.md)的現況與入口，再依階段找文件。每份實驗文件保留當輪的條件與結果，不會因後續研究覆寫成最新成績；跨輪進度、各輪一句話結果與下一步見[專案進度](PROJECT_PROGRESS.md)。各階段表格依研究先後排列，最後一列是該階段最新的一輪。

## 共用與入門

| 需求 | 文件 | 內容 |
| --- | --- | --- |
| 全專案狀態與歷程 | [專案進度](PROJECT_PROGRESS.md) | 各階段狀態、Stage 4／5／6／8／9／10／11／12逐輪歷程、卡關原因與下一步 |
| 安裝、服務與操作 | [本機環境指南](LOCAL_SETUP.md) | `.venv`、MySQL、Jupyter、資料匯入及驗證方式 |
| 商業分析成果 | [Stage 3 商業分析](STAGE3_BUSINESS_ANALYSIS.md) | 八張 EDA 圖與訂單、營收、配送等指標定義 |
| 資料表關聯 | [Olist 核心 ERD](olist_core_erd.png) | 訂單、商品、付款、評論與賣家等資料表關係 |

## Stage 12：一次真實 validation 停止與保存（最新）

[一次執行、停止與限制](STAGE12_RETAILROCKET_KNN_VALIDATION_ATTEMPT_V1.md) → [保存報告](../reports/stage12/retailrocket_session_knn_v1_validation_attempt.json)。主要 166,897 query／2,000 bootstrap 已產出；完整反讀未完成，依使用者整輪 3 小時 30 分鐘時限停止。0 重跑，來源 358／準備產物 61 份停止後核對通過；K1−C1 未驗收，test locked。

## Stage 12：K1 validation 來源／反讀／單次入口（前輪）

[入口、來源與限制](STAGE12_RETAILROCKET_KNN_VALIDATION_ENTRY_V1.md) → [契約](contracts/retailrocket_session_knn_validation_entry_v1.json) → [驗收](../reports/stage12/retailrocket_session_knn_v1_validation_entry_acceptance.json) → [凍結](../reports/stage12/retailrocket_session_knn_v1_validation_entry_specification.json)。83 項相關測試、兩組正式檔案合成案例完整 oracle 通過；358 份來源凍結、15 份直接輸入綁定；0 真實 K1 fit／validation，test locked。尚無真實推薦成績；最終選模／refit／test 另行規劃。

## Stage 12：K1 實作、合成驗收與 train-only 成本（前輪）

[實作、手算及界線](STAGE12_RETAILROCKET_KNN_IMPLEMENTATION_V1.md) → [實作契約](contracts/retailrocket_session_knn_implementation_v1.json) → [驗收收據](../reports/stage12/retailrocket_session_knn_v1_implementation_acceptance.json) → [凍結來源](../reports/stage12/retailrocket_session_knn_v1_implementation_specification.json)。49 項測試與兩組完整合成 oracle 通過；train 1,180,256 sessions、1,587,436 個不同 session-item；0 真實 K1 fit／validation，test locked。

## Stage 12：時間資料盤點與比較規格（前輪）

[盤點、方法與凍結規則](STAGE12_TEMPORAL_AVAILABILITY_AND_KNN_SPEC_V1.md) → [機器契約](contracts/retailrocket_session_knn_paired_v1.json) → [來源／候選盤點](../reports/stage12/retailrocket_stage12_inventory_v1.json) → [凍結收據](../reports/stage12/retailrocket_session_knn_v1_specification.json)。新驗收時間來源 0；固定 Jaccard session-kNN k=500，唯一主要 K1−C1 NDCG；12 項 metadata／守門測試通過，0 新研究計算，最終選模／refit／test 另行規劃。

## Stage 11：D1 三臂研究與交付

| 文件 | 內容與範圍 |
| --- | --- |
| [D1／C1／P0 比較規格](STAGE11_RETAILROCKET_DIRECTED_SPEC_V1.md) | 五類候選選 D1、有向相鄰 session 關聯、共用支援／歷史／分母、唯一主要比較與 2,000 次 bootstrap；validation 已曝光、冷商品／小組／回溯限制保留 |
| [機器契約](contracts/retailrocket_directed_paired_v1.json)／[候選盤點](../reports/stage11/retailrocket_stage11_candidate_inventory_v1.json) | 199 份來源 SHA、228 項規格檢查、109 項規格／I/O 守門測試通過；只做規格，D1 未實作，P0／C1 原狀、test locked |
| [D1 實作／手算／成本與真實入口](STAGE11_RETAILROCKET_DIRECTED_IMPLEMENTATION_V1.md) | 60 項測試、217 份來源凍結、兩組正式合成 oracle 全過；train-only 成本逐 session 通過；0 真實 D1 fit／validation，P0／C1 原狀、test locked |
| [一次真實 D1／C1／P0 validation](STAGE11_RETAILROCKET_DIRECTED_VALIDATION_V1.md) | D1 NDCG@10 0.099799771，D1−C1 差 -0.006600944，95% 區間 [-0.007511893, -0.005716747]；166,897 查詢／2,000 次主要 bootstrap 及獨立逐筆反讀完成，P0／C1 原狀、test locked |
| [三臂研究交付與證據保存](STAGE11_RETAILROCKET_THREE_ARM_RESEARCH_HANDOFF_V1.md) | 144 個 payload＋manifest 全 CRC／SHA 通過；44 項保存測試，原三臂與舊 ZIP 保留，test locked；[收據](../reports/stage11/retailrocket_three_arm_v1_research_release.json) |

## Stage 10：共現 C1 與 P0 配對比較（最新）

| 文件 | 內容 |
| --- | --- |
| [共現計數、歷史、回退、配對與限制](STAGE10_RETAILROCKET_COOCCURRENCE_PAIRED_SPEC_V1.md) | train session 二元共現、精確有理排序及 P0 回退；同 166,897 query／候選／分母、訪客成組區間規格；82 來源 SHA、131 項一致性檢查、64 項規格測試通過，0 新 fit／出分，test locked |
| [機器配對契約](contracts/retailrocket_cooccurrence_paired_v1.json) | 固定方法／時鐘／來源身份、分母、bootstrap 及後續合成／完整反讀；保留規格輪當時未實作快照 |
| [凍結來源](../reports/stage10/retailrocket_cooccurrence_v1_specification.json)／[規格驗收](../reports/stage10/retailrocket_cooccurrence_v1_spec_acceptance.json) | 純規格守門及 SHA／JSON 反讀，不能當作算法正確性或效能驗收 |
| [C1／配對／bootstrap 實作、成本與真實入口](STAGE10_RETAILROCKET_COOCCURRENCE_IMPLEMENTATION_V1.md) | 55測試／104來源與train-only成本／入口凍結，保留當輪合成驗收及0真實fit快照；後續真實結果見下列 |
| [一次真實 C1／P0 配對 validation](STAGE10_RETAILROCKET_COOCCURRENCE_VALIDATION_V1.md) | C1 NDCG@10 0.106400714，配對差 0.104718885；166,897 validation／2,000次bootstrap及獨立反讀完成，test locked；P0原狀，小組／回溯限制保留 |
| [C1／P0研究交付與證據保存](STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md) | 適用／冷商品／小組／回溯界線、完整test閘門及只讀操作；結果ZIP完整反讀，P0原狀、test locked，0新研究 |

## Stage 9：熱門baseline與完整候選評估（最新）

| 文件 | 內容 |
| --- | --- |
| [P0／評估器執行規格、測試啟用與限制](STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md) | 單一view次數、訓練統計與冷啟動、固定分母／指標、完整候選精確性、test locked；47來源／38檢查／28測試，0fit／排名／成績 |
| [機器執行規格](contracts/retailrocket_popularity_execution_v1.json) | 各角色fit上限、公式、分母、小組與八項測試啟用條件；保留當輪快照，後續實作見下列 |
| [P0／評估器實作與開發入口凍結](STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md) | 54測試、兩個合成case共35列／226格、61來源固定；該輪僅合成，後續真實結果見下列 |
| [一次真實P0開發與獨立逐query反讀](STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md) | 166,897 query；NDCG@10 0.001681829、HitRate 0.418222%，全CSV／聚合一致；預留test locked |

## Stage 8：Retailrocket 推薦資料（最新）

| 文件 | 內容 |
| --- | --- |
| [官方來源、授權、鍵、時間與契約 v1](STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md) | 官方完整 v2 四檔實讀、44項獨立核對；固定下一瀏覽集合、30分鐘 session、回溯窗口、事前候選與全目錄評估；該輪未建樣本；後續建置已完成，模型待做 |
| [推薦資料機器契約](contracts/retailrocket_recommendation_v1.json) | 原始檔 SHA、去重／排除、時間／未知、候選與分母、產物及驗收要求 |
| [v1建置、逐格反讀與支援限制](STAGE8_RETAILROCKET_BUILD_V1.md) | 三窗query 642,619／166,897／92,086；30項合成測試、16CSV完整獨立核對；尚無推薦模型／排名成績 |

## Stage 6：RFM 顧客分析

原資料集與 G1 已完成；本機缺少原私有檔後，已另建 v2 並完成真實 G2。R／F／M 為 5／2／5 級，五種子 G3 亦已通過，但每次仍有 25 個組合支援不足；跨期／業務待資料，沒有模型訓練或 Dashboard。快照固定 S=2017-09-01、T=2018-09-01，M 是商品毛額。

| 順序 | 文件 | 內容 |
| --- | --- | --- |
| 1 | [顧客鍵、資格、金額與時間截止盤點](STAGE6_RFM_FEASIBILITY.md) | 原四表來源守門、候選 74,147 單／72,183 顧客鍵；20項合成測試與59項獨立對帳，未建 RFM |
| 2 | [RFM 資料集規格](STAGE6_RFM_DATASET_SPEC.md) | 93,234 歷史顧客、74,088 窗口單；59 異常隔離、零活動／未知遮罩、S／T 及16欄輸出凍結 |
| 3 | [builder、反讀與完整同ID核對](STAGE6_RFM_DATASET_IMPLEMENTATION.md) | 93,234 顧客／99,421 逐單、130項測試與 3,082,480 格獨立核對通過 |
| 4 | [描述／分群評估規格](STAGE6_RFM_EVALUATION_SPEC.md) | 分流、偏態／離群、切點與穩定性的事前規格；G0–G3 關卡定義 |
| 5 | [只讀描述器與合成驗收](STAGE6_RFM_DESCRIPTION_IMPLEMENTATION.md) | 資格守門、精確描述；46測、獨立手算與反例通過 |
| 6 | [真實描述執行準備](STAGE6_RFM_DESCRIPTION_EXECUTION.md) | 來源、完整同ID名冊、聚合與反讀契約；58項合成測試 |
| 7 | [真實描述結果與交付驗收](STAGE6_RFM_DESCRIPTION_RESULTS.md) | G1 實績：F=1 占 97.52%、776,807 格名冊與 244 聚合值反讀一致 |
| 8 | [G2 規則候選實作](STAGE6_RFM_RULE_CANDIDATE_IMPLEMENTATION.md) | ties 不拆、1–5 級、每軸支援與 100% 同ID重現；60項合成測試 |
| 9 | [原 v1 G2 真實執行準備](STAGE6_RFM_RULE_CANDIDATE_EXECUTION.md) | 57來源、完整同ID、私有四檔／公開聚合與反讀契約；68項合成測試，真實 G2 未執行 |
| 10 | [v2 重建與真實 G2](STAGE6_RFM_REBUILD_V2.md) | 新執行證據、3,082,480 格核對與 G2 完整反讀；各軸通過、小組限制與備份操作 |
| 11 | [五種子 G3](STAGE6_RFM_G3_V2.md) | 固定 80% 抽樣回套同一全名冊；五種子全過、最差 ARI 0.990675，小組與跨期限制保留 |
| 12 | [第二快照資料盤點](STAGE6_RFM_TEMPORAL_DATA_INVENTORY.md) | 原表／備份同一版；T 後 20 筆購買無合格新增單；跨期待資料，附[交接缺件](templates/rfm_temporal_handoff/README.md)與[驗收範本](templates/rfm_temporal_handoff/acceptance_record.template.md) |
| 13 | [後期公開來源與替代資料](STAGE6_RFM_PUBLIC_SOURCE_SEARCH.md) | 未找到合格 Olist 延伸；優先驗收 UCI Online Retail II 另開回溯研究；REES46 與 dunnhumby 為有條件候選，只有 metadata／入口查核 |
| 14 | [UCI 完整官方資料盤點](STAGE6_UCI_RETAIL_II_INTAKE.md) | 1,067,371 筆實讀；缺值、跨表重複、取消、金額與 25 個月覆蓋；可另立回溯研究，資料契約待凍結 |
| 15 | [UCI 回溯 RFM 契約 v1](STAGE6_UCI_RFM_CONTRACT_V1.md) | 年度雙窗、去重／取消／時間衝突／顧客與 M 規則、固定四口徑及跨期評估；38 項合成測試通過，真實建置待實作 |
| 16 | [UCI v1 真實建置與獨立驗收](STAGE6_UCI_RFM_BUILD_V1.md) | 八組／32 CSV 的完整 RFM、逐列排除與去重映射；128,416,372 格獨立核算一致，切點與跨期比較待執行 |
| 17 | [UCI v1 固定切點與跨期比較](STAGE6_UCI_RFM_TEMPORAL_V1.md) | T1 單次參考、八組固定套用；配對 2,663、小組支援不足保留；回溯描述與獨立驗收，非穩定性或營運通過 |
| 18 | **[Stage 6 研究交付與 UCI v1 封存（最新）](STAGE6_RFM_RESEARCH_HANDOFF.md)** | 離線交付、適用／限制、來源與結果封存、驗證還原及下一步；小組不足保留，營運仍待資料 |

## Stage 5：評論低評分預測

目標是核准時預測首份評論回答（60天內）是否為 1–2 分。四欄基線與移除購買月份的三欄消融都已在三個已檢視開發月完成開發回測，三欄未支持替換四欄；後續只做只讀診斷與時間窗盤點。2018年5–9月新驗證窗待資料，沒有可部署模型或評論提醒政策。

| 順序 | 文件 | 內容 |
| --- | --- | --- |
| 1 | [評論低評分預測可行性](STAGE5_REVIEW_PREDICTION_FEASIBILITY.md) | 核准時首答目標、21欄條件候選及不限H的來源支援 |
| 2 | [H60 首答資料集](STAGE5_REVIEW_DATASET_SPEC.md) | 60天窗口、多評論與未知、內外層切分及每個 fit 的標籤資格 |
| 3 | [最小基線與評估規格](STAGE5_REVIEW_BASELINE_SPEC.md) | 四欄、前處理、內層 AP 選 C、評估及未知／失敗處理 |
| 4 | [builder 與 pipeline 洩漏測試](STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md) | 四欄／44維、合格訓練隔離、查詢不讀未來標籤；僅合成 fit |
| 5 | [四欄離線最小基線](STAGE5_REVIEW_OFFLINE_BASELINE.md) | 來源與角色守門、內層選 C、外層 fit 與逐月開發評估 |
| 6 | [凍結分數與四欄支援診斷](STAGE5_REVIEW_SCORE_DIAGNOSTICS.md) | 月低評率、機率分布、單欄支援與既有損失分解；不追加 fit |
| 7 | [移除購買月份的消融規格](STAGE5_REVIEW_MONTH_ABLATION_SPEC.md) | 三欄／32維，其餘契約不變；未實作或訓練 |
| 8 | [三欄實作與洩漏驗證](STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md) | 三欄32維、保留四欄對照；75項 pipeline＋57項契約回歸 |
| 9 | [三欄執行準備](STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md) | 51公開＋13私有來源、12角色與四欄18分數區塊；0訓練 |
| 10 | [三欄正式入口與私有產物](STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md) | 合成 9＋3 次 fit、獨立選 C、18區塊配對、失敗停止；真實訓練0 |
| 11 | [三欄真實消融結果](STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md) | 9＋3 次真實 fit、18組同ID配對；macro AP 三欄 0.170494 對四欄 0.170928 |
| 12 | [雙臂機率、排序與支援診斷](STAGE5_REVIEW_ABLATION_DIAGNOSTICS.md) | 多數機率下移、星期／小時支援完整；0追加訓練，暫不指定新單因子 |
| 13 | [逐 fit 成熟先驗與時間漂移](STAGE5_REVIEW_MATURE_PRIOR_AUDIT.md) | 6個 fit 情境、12完整角色；固定近期窗方向不一致，無參數更新 |
| 14 | [後續時間窗與用途](STAGE5_REVIEW_VALIDATION_WINDOWS.md) | 五個較晚月份全待資料，只保留驗收後時間驗證用途 |
| 15 | [新時間窗交接清單](templates/review_window_handoff/README.md)、[驗收紀錄](templates/review_window_handoff/acceptance_record.template.md)、[JSON範本](templates/review_window_handoff/handoff_manifest.template.json) | 同ID名冊、H60完成、原入庫／評分版本、新標籤角色；分月15項，均待資料 |
| 16 | **[四欄／三欄模型卡（最新）](STAGE5_MODEL_APPLICABILITY.md)** | 開發回測範圍、未知／時鐘／版本限制、公開與私有產物及下一步；不追加訓練 |

## Stage 4：延遲預測

固定每日完整批次10%提醒預算，以及原101／時齡102 × 欄位取樣0.8／1.0、11／29／42／73／101五種子的固定對照；離線研究可交付，正式適用要求未達，全量資料與事件訊號待資料。

下列依研究主題排列，同一主題內沿研究先後閱讀。每份實驗文件保留當輪條件與結果，不會因後續研究覆寫成最新成績；要看跨輪進度，請使用[專案進度](PROJECT_PROGRESS.md)。

後期反覆使用的 2017-12、2018-02、2018-04 是**開發回測月份**。歷史驗證、開發回測與原版保留測試使用不同期間或規則，不能直接當作同一條測試成績比較；最新固定預算研究沒有重新評分原保留測試。

### 基礎模型、時間驗證與提醒規則

| 文件 | 用途 |
| --- | --- |
| [訂單延遲預測](STAGE4_DELAY_PREDICTION.md) | 延遲定義、核准時點特徵、第一版分類模型、推論與多模型時間回測入口 |
| [減少延遲誤報](STAGE4_ALERT_OPTIMIZATION.md) | 驗證召回下限與門檻選擇、平衡模式，以及已檢視保留資料的回溯診斷 |
| [月份落差與誤報診斷](STAGE4_MONTHLY_DIAGNOSTICS.md) | 固定平衡模型，拆解月份、路線與答案成熟度差異 |
| [等待期與路線承諾實驗](STAGE4_WAITING_EXPERIMENT.md) | 30／60 天等待、路線配送歷史與承諾餘裕比較 |
| [多月份驗證](STAGE4_MULTIMONTH_VALIDATION.md) | 最新月、合併月及每月召回下限三種選模方式比較 |
| [每月重訓](STAGE4_MONTHLY_RETRAINING.md) | 按當時可得資料重訓，使用歷史月份 OOT 分數選門檻與模型 |
| [分數校準與每日提醒上限](STAGE4_CALIBRATION_BUDGET.md) | 分數轉換與 5%／10%／20% 預算比較，後續固定每日 10% 的起點 |

### 固定預算下的特徵、答案時鐘與負載

| 文件 | 用途 |
| --- | --- |
| [固定預算漏報與排名](STAGE4_BUDGET_RANKING.md) | 固定每日 10%，擴充賣家／路線特徵並比較提升樹與加權分類 |
| [未完成件與每日排序](STAGE4_PENDING_RANKING.md) | 尚未觀測送達的件數、等待與逾期訊號，以及初次每日排序比較 |
| [更即時的訓練結果時鐘](STAGE4_OUTCOME_CLOCK.md) | 比較到承諾截止便可得知延遲的答案時鐘，以及訓練等待期 |
| [特徵工程對照](STAGE4_FEATURE_ENGINEERING.md) | 地理、承諾、成本與未完成件交互的整組比較 |
| [地理與負載交互消融](STAGE4_FEATURE_ABLATION.md) | 將地理、負載交互分開，檢查各組增量 |
| [Logistic 正則化](STAGE4_LOGISTIC_REGULARIZATION.md) | 固定 65 欄負載組，只比較正則化強度 |
| [十二月與歷史漏報診斷](STAGE4_DECEMBER_MISS_DIAGNOSTICS.md) | 固定既有模型，檢查長承諾、SP→RJ 與共同漏報 |
| [路線 × 承諾 × 近期負載](STAGE4_ROUTE_LOAD_INTERACTIONS.md) | 近 7／14 天核准量變化與明確交互特徵比較 |
| [7／14 天逾期堆積變化](STAGE4_BACKLOG_CHANGES.md) | 比較逾期未送達件的過去堆積量、增減與成長 |
| [七、九月路線名額交換](STAGE4_BACKLOG_ROUTE_EXCHANGES.md) | 固定分數，追蹤加入堆積特徵後的補抓、新增漏報與每日排名 |

### 排序目標與訓練設定

| 文件 | 用途 |
| --- | --- |
| [同特徵分類與每日排序](STAGE4_BACKLOG_OBJECTIVES.md) | 固定 83／101 欄，比較 XGBoost 分類與排序目標 |
| [排序 L2 正則化](STAGE4_RANK_REGULARIZATION.md) | 固定特徵與排序設定，比較 L2＝1／10／100 |
| [排序配對焦點](STAGE4_RANK_PAIR_FOCUS.md) | 固定 L2＝100，比較原生固定前 k＝10／20／40 的訓練焦點 |
| [每日訂單量與配對焦點診斷](STAGE4_RANK_BATCH_SIZE.md) | 固定模型，檢查每日批次量與訓練 k、提醒容量的差距 |
| [topk／mean 配對方式](STAGE4_RANK_PAIR_METHOD.md) | 固定 101 欄與整數參數 10，只比較配對方式及各月代價 |

### 物流可得性、交運歷史與待件訊號

| 文件 | 用途 |
| --- | --- |
| [物流訊號與預測時點盤點](STAGE4_LOGISTICS_AVAILABILITY.md) | 查核原始欄位與事件時鐘，區分核准時可知資訊和後續檢查點 |
| [主賣家交運歷史](STAGE4_HANDOVER_HISTORY.md) | 原 101 欄對照新增交運事件數與耗時 p50／p90 的 104 欄 |
| [交運稀疏與交集診斷](STAGE4_HANDOVER_SPARSE_DIAGNOSTICS.md) | 固定模型，拆開稀疏歷史、長承諾與 SP→RJ 的漏報及名額交換 |
| [交運事件數單欄消融](STAGE4_HANDOVER_COUNT_ABLATION.md) | 單加事件數，對照原 101 欄與完整交運歷史 104 欄 |
| [三模型共同漏報與可用訊號](STAGE4_COMMON_MISSES_AND_SIGNALS.md) | 區分三模型共同弱點與提醒交換，盤點未觀測交運代理 |
| [未觀測交運待件件數](STAGE4_UNOBSERVED_HANDOVER_COUNT.md) | 原 101 欄單加待件件數，不同於已完成交運事件數 |
| [未觀測交運待件時齡 p90](STAGE4_UNOBSERVED_HANDOVER_AGE.md) | 原 101 欄單加歷史待件等待時齡，不與件數一起加入 |

### 五種子穩定性、四模型共同漏報與成熟訊號

| 文件 | 用途 |
| --- | --- |
| [二月時齡交集與提醒交換](STAGE4_AGE_INTERSECTIONS.md) | 固定原 101／時齡 102，拆解路線、承諾與等待時齡的重疊群組 |
| [五種子成對重訓](STAGE4_AGE_SEED_STABILITY.md) | 固定 11／29／42／73／101，檢查時齡增量及路線得失是否穩定 |
| [欄位取樣 0.8／1.0](STAGE4_AGE_COLSAMPLE.md) | 維持兩組特徵與五種子，只改每棵樹的欄位取樣 |
| [四模型共同漏報與每日邊界](STAGE4_FOUR_MODEL_BOUNDARY.md) | 固定四組設定與五種子，追查 SP→RJ、等待組、SP→SC 的排名與名額交換 |
| [核准當下成熟歷史訊號稽核](STAGE4_MATURE_HISTORY_SIGNAL_AUDIT.md) | 重建既有成熟歷史，稽核賣家 CDF、賣家×路線延遲率及近期率差 |
| [固定條件的成熟訊號比較](STAGE4_CONDITIONAL_MATURE_SIGNALS.md) | 固定路線、承諾、核准週與支援量，保留 SP→SC 對照及精確承諾敏感度比較 |
| [完成歷史代表性稽核](STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md) | 區分送達窗口與同核准窗口，稽核完成／待完成組成、既有訊號與精確天數加星期的敏感度 |

### 來源查核、適用範圍與交付

colsample 之後沒有新訓練或改選，只做來源查核、適用範圍整理與交付驗收；正式適用要求未達，事件訊號與全量資料待資料，Dashboard 暫緩。

| 文件 | 用途 |
| --- | --- |
| [取消／結案與承諾版本來源](STAGE4_EVENT_SOURCE_AVAILABILITY.md) | 核對原始、DB、binlog與官方來源，明列時鐘／涵蓋缺口及未來驗收契約；新增驗收來源0 |
| [模型適用範圍與交付清單](STAGE4_MODEL_APPLICABILITY.md) | 區分原RF、歷史選模主方案與四設定五種子；研究可交付，正式適用未達 |
| [單日離線交付驗收](STAGE4_OFFLINE_DAILY_ACCEPTANCE.md) | 固定2018-02-01，四設定×全部五種子，核對研究日名冊、版本、排名、10%名額與CSV |
| [全量日資料契約與缺口](STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract) | 全量名冊、入庫／版本與日結證據仍待資料，保留研究名冊交付驗收 |
| **[資料交接清單（最新）](templates/daily_data_handoff/README.md)**、[驗收範本](templates/daily_data_handoff/acceptance_record.template.md) | 15項check_id與三個獨立判定，空白狀態均待資料，實際資料另存私有路徑 |

## 如何追到實際產物

每份研究文件內附對應報告、適用的規格與執行方式；聚合JSON位於 [`reports/stage4/`](../reports/stage4/)、[`reports/stage5/`](../reports/stage5/)、[`reports/stage6/`](../reports/stage6/)及[`reports/stage8/`](../reports/stage8/)，對照表見[報告導覽](../reports/README.md)，程式入口見[腳本導覽](../scripts/README.md)。可行性、資料集／基線契約、合成驗證與正式開發回測各有用途，均不能補成全盲未知測試。資料目錄與保留方式見[資料說明](../data/README.md)，資料庫建立與查詢見 [SQL 導覽](../sql/README.md)，驗證方式見[測試說明](../tests/README.md)。逐筆分數、原始資料、本機模型及執行紀錄由 Git 忽略，重現時須依[本機環境指南](LOCAL_SETUP.md)準備。

文件中的原始輸入欄數、快取欄數與模型編碼後維度各有不同用途；不同輪次都可能稱為 102 欄，應以當輪白名單與規格確認內容。等待 24–72 小時組指歷史待件時齡代理，不是本張訂單核准後再等 24–72 小時才預測。
