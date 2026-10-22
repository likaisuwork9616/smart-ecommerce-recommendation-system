# 文件導覽

先看[專案首頁](../README.md)的現況與入口，再依階段找文件。每份實驗文件保留當輪的條件與結果，不會因後續研究覆寫成最新成績；跨輪進度、各輪一句話結果與下一步見[專案進度](PROJECT_PROGRESS.md)。各階段表格依研究先後排列，最後一列是該階段最新的一輪。

## 共用與入門

| 需求 | 文件 | 內容 |
| --- | --- | --- |
| 全專案狀態與歷程 | [專案進度](PROJECT_PROGRESS.md) | 各階段狀態、Stage 4／5／6 逐輪歷程、卡關原因與下一步 |
| 安裝、服務與操作 | [本機環境指南](LOCAL_SETUP.md) | `.venv`、MySQL、Jupyter、資料匯入及驗證方式 |
| 商業分析成果 | [Stage 3 商業分析](STAGE3_BUSINESS_ANALYSIS.md) | 八張 EDA 圖與訂單、營收、配送等指標定義 |
| 資料表關聯 | [Olist 核心 ERD](olist_core_erd.png) | 訂單、商品、付款、評論與賣家等資料表關係 |

## Stage 6：RFM 顧客分析

已完成真實資料集與一次真實只讀描述（G1）；G2 規則候選已完成合成驗收與真實執行準備，真實 G2、G3、分群、訓練與 Dashboard 均未執行。快照固定 S=2017-09-01、T=2018-09-01，M 是商品毛額。

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
| 9 | **[G2 真實執行準備（最新）](STAGE6_RFM_RULE_CANDIDATE_EXECUTION.md)** | 57來源、完整同ID、私有四檔／公開聚合與反讀契約；68項合成測試，真實 G2 未執行 |

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

每份研究文件內附對應報告、適用的規格與執行方式；聚合JSON位於 [`reports/stage4/`](../reports/stage4/)、[`reports/stage5/`](../reports/stage5/)及[`reports/stage6/`](../reports/stage6/)，對照表見[報告導覽](../reports/README.md)，程式入口見[腳本導覽](../scripts/README.md)。可行性、資料集／基線契約、合成驗證與正式開發回測各有用途，均不能補成全盲未知測試。資料目錄與保留方式見[資料說明](../data/README.md)，資料庫建立與查詢見 [SQL 導覽](../sql/README.md)，驗證方式見[測試說明](../tests/README.md)。逐筆分數、原始資料、本機模型及執行紀錄由 Git 忽略，重現時須依[本機環境指南](LOCAL_SETUP.md)準備。

文件中的原始輸入欄數、快取欄數與模型編碼後維度各有不同用途；不同輪次都可能稱為 102 欄，應以當輪白名單與規格確認內容。等待 24–72 小時組指歷史待件時齡代理，不是本張訂單核准後再等 24–72 小時才預測。
