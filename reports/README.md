# 報告與圖表索引

`stage4/`保存延遲研究的聚合結果與規格，`stage5/`保存評論預測盤點、資料集／基線契約、合成驗證及離線開發回測；`stage6/`保存RFM輸入盤點、資料集契約、builder／真實建置／反讀聚合，以及描述／分群評估規格與metadata沿用查核；`images/`保存EDA及較早Stage 4圖表。先讀[專案現況](../README.md)及[研究文件索引](../docs/README.md)，需要重現時再查[程式入口](../scripts/README.md)。檔案日期或大小不代表方案優劣。

## 從哪份報告開始

| 想確認的問題 | 閱讀順序 |
| --- | --- |
| 最新Stage 6只讀描述執行準備 | [串接／輸出契約](../docs/STAGE6_RFM_DESCRIPTION_EXECUTION.md) → [41份來源規格](stage6/rfm_description_execution_specification.json) → [準備查核](stage6/rfm_description_execution_preflight.json)；58測、完整名冊／四檔與public反讀接妥，真實描述與結果檔未建立 |
| 前輪Stage 6只讀描述合成驗收 | [實作解讀](../docs/STAGE6_RFM_DESCRIPTION_IMPLEMENTATION.md) → [33份來源規格](stage6/rfm_description_implementation_specification.json) → [合成verification](stage6/rfm_description_pipeline_verification.json)；46測＋metadata沿用，沒有真實分布／切點／群組值 |
| 前輪Stage 6 RFM評估規格 | [方法文件](../docs/STAGE6_RFM_EVALUATION_SPEC.md) → [27份來源／機器規格](stage6/rfm_evaluation_specification.json) → [metadata查核](stage6/rfm_evaluation_contract_audit.json)；僅沿用版本，沒有新分布、切點、群組或效果數字 |
| 前輪Stage 6 RFM建置與驗收 | [實作解讀](../docs/STAGE6_RFM_DATASET_IMPLEMENTATION.md) → [20份來源規格](stage6/rfm_dataset_build_specification.json) → [真實建置](stage6/rfm_dataset_build.json) → [分項驗收](stage6/rfm_dataset_build_acceptance.json)；只放聚合，不含個體RFM／私有digest或分群效果 |
| 前輪Stage 6 RFM資料集契約 | [解讀與輸出規格](../docs/STAGE6_RFM_DATASET_SPEC.md) → [凍結規格](stage6/rfm_dataset_specification.json) → [聚合支援查核](stage6/rfm_dataset_contract_audit.json)；母體、59異常、零活動與M遮罩已凍結，未建個體資料集或分群 |
| 前輪Stage 6 RFM輸入支援 | [解讀與候選契約](../docs/STAGE6_RFM_FEASIBILITY.md) → [來源／政策規格](stage6/rfm_feasibility_specification.json) → [實際聚合盤點](stage6/rfm_feasibility.json)；只查鍵、資格、金額與時間，不含RFM個體值、分群或效能 |
| 前輪Stage 5模型適用與交付 | [模型卡](../docs/STAGE5_MODEL_APPLICABILITY.md) → [原四欄報告](stage5/review_baseline_training.json) → [原三欄報告](stage5/review_month_ablation_training.json) → [原配對驗收](stage5/review_month_ablation_training_acceptance.json)；僅整理已有開發結果，沒有新效能報告，Stage 5待資料 |
| 前輪Stage 5新時間窗交接 | [資料清單](../docs/templates/review_window_handoff/README.md) → [待填驗收紀錄](../docs/templates/review_window_handoff/acceptance_record.template.md) → [JSON交接範本](../docs/templates/review_window_handoff/handoff_manifest.template.json)；是空白契約格式，本輪無新資料／標籤／效能報告，既有報告bytes保留 |
| 前輪Stage 5後續時間窗 | [解讀與缺口](../docs/STAGE5_REVIEW_VALIDATION_WINDOWS.md) → [盤點規格](stage5/review_validation_window_specification.json) → [實際盤點](stage5/review_validation_window_inventory.json) → [用途凍結](stage5/review_validation_window_usage_freeze.json) → [驗證](stage5/review_validation_window_verification.json)；五個新窗待資料，0訓練／效能 |
| 前輪Stage 5成熟先驗與時間漂移 | [解讀與決策](../docs/STAGE5_REVIEW_MATURE_PRIOR_AUDIT.md) → [事前規格](stage5/review_mature_prior_specification.json) → [完整稽核](stage5/review_mature_prior_audit.json) → [驗證](stage5/review_mature_prior_verification.json)；H60與12角色不變，無query回填／訓練／參數更新 |
| 前輪Stage 5雙臂只讀診斷 | [解讀與決策](../docs/STAGE5_REVIEW_ABLATION_DIAGNOSTICS.md) → [事前規格](stage5/review_ablation_diagnostic_specification.json) → [機率／排序／支援](stage5/review_ablation_diagnostics.json) → [驗證](stage5/review_ablation_diagnostic_verification.json)；0追加訓練，暫不指定新單因子 |
| 前輪Stage 5三欄真實消融 | [結果與限制](../docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md) → [正式開發回測](stage5/review_month_ablation_training.json) → [獨立交付驗收](stage5/review_month_ablation_training_acceptance.json)；一次12fit、18組完整配對，四欄沿用凍結分數 |
| 前輪Stage 5三欄正式入口 | [入口驗收](../docs/STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md) → [入口／writer／測試綁定](stage5/review_month_ablation_dispatcher_specification.json) → [合成報告](stage5/review_month_ablation_dispatcher_verification.json)；真實fit與新效能0 |
| 前輪Stage 5三欄執行準備 | [方法與界線](../docs/STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md) → [執行政策／輸出規格](stage5/review_month_ablation_execution_specification.json) → [來源／角色／四欄對照驗收](stage5/review_month_ablation_execution_preflight.json)；0訓練，三欄實際配對待產物 |
| 前輪Stage 5三欄消融實作 | [實作與洩漏驗證](../docs/STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md) → [合成驗證報告](stage5/review_month_ablation_pipeline_verification.json)；75項新舊pipeline測試通過，真實訓練／效能均0 |
| 前輪Stage 5四欄離線最小基線 | [方法與限制](../docs/STAGE5_REVIEW_OFFLINE_BASELINE.md) → [執行規格](stage5/review_baseline_training_specification.json) → [實際開發回測](stage5/review_baseline_training.json)；三月為已檢視開發資料，不是新未知測試 |
| 前輪Stage 5程式實作與洩漏測試 | [受控builder／pipeline](../docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md) → [合成驗證](stage5/review_pipeline_verification.json)；有合成fit，該輪沒有真實資料訓練或模型效能 |
| 前輪Stage 5最小基線契約 | [四欄／前處理／選參／評估](../docs/STAGE5_REVIEW_BASELINE_SPEC.md) → [事前規格](stage5/review_baseline_specification.json) → [實際契約稽核](stage5/review_baseline_contract_audit.json)；該輪未訓練、未計效能 |
| 最新Stage 5資料集／逐fit標籤 | [H60與內外層契約](../docs/STAGE5_REVIEW_DATASET_SPEC.md) → [凍結規格](stage5/review_dataset_specification.json) → [實際支援與核對](stage5/review_dataset_audit.json)；沒有模型效能 |
| 最新Stage 5評論預測可行性 | [問題／特徵／時間驗證](../docs/STAGE5_REVIEW_PREDICTION_FEASIBILITY.md) → [實際來源與標籤盤點](stage5/review_prediction_feasibility.json)；不是模型成績 |
| 最新全量日資料契約與缺口 | [名冊／時鐘／版本／日結要求](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract) → [實際來源查核](stage4/daily_data_contract.json)；待資料，不是生產完整性或效能通過 |
| 最新單日離線交付驗收 | [範圍與操作](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md) → [來源／交付契約](stage4/daily_delivery_acceptance_specification.json) → [聚合驗收](stage4/daily_delivery_acceptance.json)；不含個體排名／分數或新增效能 |
| 現有模型適用範圍與可交付成果 | [模型卡](../docs/STAGE4_MODEL_APPLICABILITY.md) → [歷史選模主方案](stage4/rank_pair_focus.json) → [四設定五種子](stage4/age_colsample.json)；模型卡只整理既有證據，沒有新增效能報告 |
| 最新事件／承諾版本來源與待資料 | [查核範圍與結論](../docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md) → [來源快照與驗收契約](stage4/event_source_availability_specification.json) → [實際查核](stage4/event_source_availability.json) |
| 前一步完成歷史代表性 | [方法與結論](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md) → [正式規格](stage4/completed_history_representativeness_specification.json) → [實際稽核](stage4/completed_history_representativeness_audit.json) |
| 前一步固定條件成熟訊號比較 | [方法與結論](../docs/STAGE4_CONDITIONAL_MATURE_SIGNALS.md) → [規格](stage4/conditional_mature_signal_specification.json) → [聚合比較](stage4/conditional_mature_signal_diagnostics.json) |
| 核准當下可得的成熟訊號 | [方法與限制](../docs/STAGE4_MATURE_HISTORY_SIGNAL_AUDIT.md) → [規格](stage4/mature_history_signal_specification.json) → [訊號稽核](stage4/mature_history_signal_audit.json) |
| 四組模型是否漏掉相同訂單、名額如何交換 | [方法與限制](../docs/STAGE4_FOUR_MODEL_BOUNDARY.md) → [規格](stage4/four_model_boundary_specification.json) → [完整診斷](stage4/four_model_boundary_diagnostics.json) |
| 原版固定測試的定義與成績 | [原版文件](../docs/STAGE4_DELAY_PREDICTION.md) → [metrics.json](stage4/metrics.json) |

colsample後的診斷、來源查核與交付驗收沿用原101／時齡102欄 × colsample0.8／1.0、五種子及每日10%規則，沒有新fit、方案改選或重評原保留測試。模型診斷屬反覆檢視的歷史驗證／開發回測；來源查核是schema與時鐘證據，單日驗收只核既有來源／排序／輸出契約，不新增預測成績。原版`metrics.json`的test、各輪validation及development不能合併成未知資料成績；主方案413TP也不是五種子平均。

## Stage 4全部JSON對照

下表保留既有檔名。名稱含 `specification` 的檔案是該輪事前規格；其餘是實際訓練、比較、盤點或診斷結果。早期研究沒有另存規格，不能補寫後把它當成當時已凍結。

| 研究主題 | 規格 | 結果與診斷 |
| --- | --- | --- |
| 原版與多模型比較 | — | [metrics](stage4/metrics.json)、[model_comparison](stage4/model_comparison.json) |
| 誤報改善與月份診斷 | — | [alert_optimization](stage4/alert_optimization.json)、[monthly_error_diagnostics](stage4/monthly_error_diagnostics.json) |
| 等待期、多月份、每月重訓 | — | [waiting_strategy_comparison](stage4/waiting_strategy_comparison.json)、[multimonth_validation](stage4/multimonth_validation.json)、[monthly_retraining](stage4/monthly_retraining.json) |
| 校準與每日提醒上限 | — | [calibration_budget](stage4/calibration_budget.json) |
| 固定預算與漏報 | [budget_ranking](stage4/budget_ranking_specification.json) | [budget_ranking](stage4/budget_ranking.json)、[budget_miss_diagnostics](stage4/budget_miss_diagnostics.json) |
| 待件排名 | [pending_ranking](stage4/pending_ranking_specification.json) | [pending_ranking](stage4/pending_ranking.json) |
| 答案時鐘 | [outcome_clock](stage4/outcome_clock_specification.json) | [outcome_clock](stage4/outcome_clock.json) |
| 特徵工程 | [feature_engineering](stage4/feature_engineering_specification.json) | [feature_engineering](stage4/feature_engineering.json) |
| 特徵消融 | [feature_ablation](stage4/feature_ablation_specification.json) | [feature_ablation](stage4/feature_ablation.json) |
| Logistic正則化 | [logistic_regularization](stage4/logistic_regularization_specification.json) | [logistic_regularization](stage4/logistic_regularization.json) |
| 十二月漏報 | — | [december_miss_diagnostics](stage4/december_miss_diagnostics.json) |
| 路線與負載交互 | [route_load_interactions](stage4/route_load_interactions_specification.json) | [route_load_interactions](stage4/route_load_interactions.json)、[route_load_diagnostics](stage4/route_load_diagnostics.json) |
| 逾期堆積變化 | [backlog_changes](stage4/backlog_changes_specification.json) | [backlog_changes](stage4/backlog_changes.json)、[backlog_diagnostics](stage4/backlog_diagnostics.json) |
| 路線名額交換 | — | [backlog_route_exchanges](stage4/backlog_route_exchanges.json) |
| 分類／排序目標 | [backlog_objectives](stage4/backlog_objectives_specification.json) | [backlog_objectives](stage4/backlog_objectives.json)、[backlog_objective_diagnostics](stage4/backlog_objective_diagnostics.json) |
| 排序正則化 | [rank_regularization](stage4/rank_regularization_specification.json) | [rank_regularization](stage4/rank_regularization.json)、[rank_regularization_diagnostics](stage4/rank_regularization_diagnostics.json) |
| 排序配對焦點 | [rank_pair_focus](stage4/rank_pair_focus_specification.json) | [rank_pair_focus](stage4/rank_pair_focus.json)、[rank_pair_focus_diagnostics](stage4/rank_pair_focus_diagnostics.json) |
| 每日訂單量診斷 | — | [rank_batch_size_diagnostics](stage4/rank_batch_size_diagnostics.json) |
| 排序配對方式 | [rank_pair_method](stage4/rank_pair_method_specification.json) | [rank_pair_method](stage4/rank_pair_method.json)、[rank_pair_method_diagnostics](stage4/rank_pair_method_diagnostics.json) |
| 物流訊號可得性 | — | [logistics_availability](stage4/logistics_availability.json) |
| 主賣家交運歷史 | [handover_history](stage4/handover_history_specification.json) | [handover_history](stage4/handover_history.json)、[handover_history_diagnostics](stage4/handover_history_diagnostics.json) |
| 稀疏交運歷史交集 | — | [handover_sparse_diagnostics](stage4/handover_sparse_diagnostics.json) |
| 交運事件數消融 | [handover_count](stage4/handover_count_specification.json) | [handover_count](stage4/handover_count.json)、[handover_count_diagnostics](stage4/handover_count_diagnostics.json) |
| 共同漏報與核准訊號 | — | [handover_common_misses](stage4/handover_common_misses.json)、[approval_signal_inventory](stage4/approval_signal_inventory.json) |
| 未觀測交運待件件數 | [unobserved_handover_count](stage4/unobserved_handover_count_specification.json) | [unobserved_handover_count](stage4/unobserved_handover_count.json)、[unobserved_handover_count_diagnostics](stage4/unobserved_handover_count_diagnostics.json) |
| 未觀測交運等待時齡 | [unobserved_handover_age](stage4/unobserved_handover_age_specification.json) | [unobserved_handover_age](stage4/unobserved_handover_age.json)、[unobserved_handover_age_diagnostics](stage4/unobserved_handover_age_diagnostics.json) |
| 時齡群組交集 | — | [age_intersection_diagnostics](stage4/age_intersection_diagnostics.json) |
| 五種子穩定性 | [age_seed_stability](stage4/age_seed_stability_specification.json) | [age_seed_stability](stage4/age_seed_stability.json)、[age_seed_stability_diagnostics](stage4/age_seed_stability_diagnostics.json) |
| 欄位取樣0.8／1.0 | [age_colsample](stage4/age_colsample_specification.json) | [age_colsample](stage4/age_colsample.json)、[age_colsample_diagnostics](stage4/age_colsample_diagnostics.json) |
| 四模型共同漏報與每日邊界 | [four_model_boundary](stage4/four_model_boundary_specification.json) | [four_model_boundary_diagnostics](stage4/four_model_boundary_diagnostics.json) |
| 成熟歷史訊號 | [mature_history_signal](stage4/mature_history_signal_specification.json) | [mature_history_signal_audit](stage4/mature_history_signal_audit.json) |
| 固定路線、承諾、週與支援量 | [conditional_mature_signal](stage4/conditional_mature_signal_specification.json) | [conditional_mature_signal_diagnostics](stage4/conditional_mature_signal_diagnostics.json) |
| 完成歷史對未完成慢件代表性 | [正式規格](stage4/completed_history_representativeness_specification.json)、[格式修正前初版](stage4/completed_history_representativeness_initial_specification.json) | [completed_history_representativeness_audit](stage4/completed_history_representativeness_audit.json) |
| 取消／結案事件與承諾版本來源 | [來源快照／驗收契約](stage4/event_source_availability_specification.json) | [event_source_availability](stage4/event_source_availability.json) |
| 單日凍結分數離線交付驗收 | [daily_delivery_acceptance](stage4/daily_delivery_acceptance_specification.json) | [daily_delivery_acceptance](stage4/daily_delivery_acceptance.json) |
| 全量日名冊／入庫版本／日結資料契約 | —（來源查核，不是訓練事前規格） | [daily_data_contract](stage4/daily_data_contract.json) |

代表性稽核的初版規格保留發布前JSON格式修正紀錄，未產生正式報告；計算規則未變，重現應使用正式規格，說明見[當輪文件](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md)。

## Stage 5資料集與聚合盤點

| 主題 | 報告角色 | 實際輸出 |
| --- | --- | --- |
| 評論低評分預測可行性 | 來源檢視後的研究建議，非模型訓練事前規格 | [review_prediction_feasibility](stage5/review_prediction_feasibility.json) |
| H60訂單級首答資料集 | 凍結單位、窗口、未知、多評論、來源及內外層日曆；非模型訓練規格 | [review_dataset_specification](stage5/review_dataset_specification.json) |
| 逐fit標籤可得性核對 | 實際角色分母、成熟／未知、標籤支援、洩漏與私有輸出反讀 | [review_dataset_audit](stage5/review_dataset_audit.json) |
| 四欄最小基線與評估 | 未來44維前處理、L2 Logistic候選、內層AP選參／固定門檻與未知政策；已檢視開發窗，不是全盲未知測試 | [review_baseline_specification](stage5/review_baseline_specification.json) |
| 最小基線契約稽核 | 原資料集、來源、私有輸入守門、逐fit事件代理／標籤及類別支援；無X／fit／選參／效能 | [review_baseline_contract_audit](stage5/review_baseline_contract_audit.json) |
| 四欄builder／train-only pipeline | 真實sklearn物件在合成fixture驗洩漏與失敗拒收；報告只含測試名稱、狀態及10份公開來源，不含個體值、機率或模型效能 | [review_pipeline_verification](stage5/review_pipeline_verification.json) |
| 四欄離線基線執行規格 | 沿用既有基線政策，凍結本輪程式／來源守門、12次fit與公私交付；執行前產生 | [review_baseline_training_specification](stage5/review_baseline_training_specification.json) |
| 四欄離線基線實際結果 | 歷史內層選C、外層重新fit及逐月AP／機率指標；已檢視開發回測，非新未知測試 | [review_baseline_training](stage5/review_baseline_training.json) |
| 凍結分數診斷規格 | 固定角色分母、單欄支援、分數分箱與配對損失分解；35公開＋11私有來源守門，不訓練或選模 | [review_score_diagnostic_specification](stage5/review_score_diagnostic_specification.json) |
| 凍結分數診斷結果 | 12角色、6組四欄支援、18組既有分數分布及3組原損失對帳；0 fit／transform／predict，非新效能 | [review_score_diagnostics](stage5/review_score_diagnostics.json) |
| 月份單因子消融規格 | 只刪purchase_month與12個月one-hot欄，預定三欄32維；其餘政策逐值不變，獨立內層選C與凍結四欄配對，未訓練 | [review_month_ablation_specification](stage5/review_month_ablation_specification.json) |
| 月份消融契約稽核 | 39公開＋12私有來源、完整cohort／12角色／H60與未知遮罩；0 X／fit／分數解析／效能 | [review_month_ablation_contract_audit](stage5/review_month_ablation_contract_audit.json) |
| 三欄消融builder／pipeline驗證 | 75項新舊合成測試、35份公開來源綁定；保留四欄對照，只有合成fit／transform／predict，0真實訓練／效能 | [review_month_ablation_pipeline_verification](stage5/review_month_ablation_pipeline_verification.json) |
| 三欄消融執行政策與輸出版本 | 固定未來9＋3fit、獨立選C、training_v1私有產物、完整同ID配對；實際訓練入口待另綁定 | [review_month_ablation_execution_specification](stage5/review_month_ablation_execution_specification.json) |
| 三欄消融準備驗收 | 51公開＋13私有來源、12完整角色、18四欄凍結分數區塊；不重評指標，三欄配對pending，0fit | [review_month_ablation_execution_preflight](stage5/review_month_ablation_execution_preflight.json) |
| 三欄正式入口綁定 | 沿用原政策，新增訓練控制、具體JSON／writer格式與測試綁定；真實訓練待決定 | [review_month_ablation_dispatcher_specification](stage5/review_month_ablation_dispatcher_specification.json) |
| 三欄入口合成驗收 | 9＋3次fit、獨立選C、同ID配對、私有反讀／回撤及失敗收據；沒有真實三欄效果 | [review_month_ablation_dispatcher_verification](stage5/review_month_ablation_dispatcher_verification.json) |
| 三欄真實離線消融 | 實際12次fit、內層選C、已檢視外層開發評估與18組同ID差值；四欄0重訓 | [review_month_ablation_training](stage5/review_month_ablation_training.json) |
| 真實消融獨立交付驗收 | 完整角色／同ID、私有bytes、12次實際fit觀測、獨立指標核算及來源保留；無額外fit或新分數 | [review_month_ablation_training_acceptance](stage5/review_month_ablation_training_acceptance.json) |
| 雙臂凍結分數診斷規格 | 66公開＋21私有來源；固定機率子集、排序平手、三欄支援及外層邊際損失分解；不訓練或選C | [review_ablation_diagnostic_specification](stage5/review_ablation_diagnostic_specification.json) |
| 雙臂凍結分數診斷結果 | 每臂18組完整分數、12組排序與6組支援；三欄多數機率下移，無新模型效能或提醒政策 | [review_ablation_diagnostics](stage5/review_ablation_diagnostics.json) |
| 雙臂診斷驗證 | 28項合成測試、10,389項獨立比較分列；原24份私有證據不變，0fit／transform／predict／重新選C | [review_ablation_diagnostic_verification](stage5/review_ablation_diagnostic_verification.json) |
| 成熟先驗事前規格 | 固定6個fit、H60可得性、互斥覆蓋、90／180天成熟窗口、核准月及跨fit轉換；73公開＋22私有守門 | [review_mature_prior_specification](stage5/review_mature_prior_specification.json) |
| 成熟先驗與漂移結果 | 12完整角色289,973列；query僅事後描述，固定近期窗口無一致方向；0模型／參數更新 | [review_mature_prior_audit](stage5/review_mature_prior_audit.json) |
| 成熟先驗稽核驗證 | 29項合成測試、7,134項獨立對帳分列；原27份私有證據不變 | [review_mature_prior_verification](stage5/review_mature_prior_verification.json) |
| 時間窗盤點規格 | 固定欄位盲化、過往用途與H60日曆規則；85公開＋25私有來源，禁止新評分／y | [review_validation_window_specification](stage5/review_validation_window_specification.json) |
| 時間窗實際盤點 | 25個月99,281有效核准，5個較晚月26,027張全待資料；舊C不改，時間最大值不是watermark | [review_validation_window_inventory](stage5/review_validation_window_inventory.json) |
| 後續驗證用途凍結 | 舊範圍開發，較晚範圍僅預留驗收後時間驗證；揭露來源／跨任務曝光，不供選模或校準 | [review_validation_window_usage_freeze](stage5/review_validation_window_usage_freeze.json) |
| 時間窗盤點驗證 | 28項合成、618項獨立盤點及95項用途核對分列；原30份私有證據不變 | [review_validation_window_verification](stage5/review_validation_window_verification.json) |

Stage 5可行性／資料集／基線契約報告保留各輪資料支援；H60、C2018-07-01及逐角色截止不變，C名冊73,254張、可用72,173張、未知1,081張。pipeline verification只含合成測試；真實基線結果另存training報告，不能把它回寫成前輪已完成訓練。原標籤／切分仍在.runtime/stage5_review_dataset_v1/，新逐筆機率／fit診斷／manifest在.runtime/stage5_review_baseline_training_v1/；公開不含ID、個體值、機率或私有digest。

## 圖表與來源保護

[images/](images/) 的 `olist_*.png` 對應Stage 3商業EDA；`stage4_*.png` 對應原版、模型比較及較早校準研究。後續輪次主要以JSON與研究文件呈現，舊圖不是最新方案成績。

部分聚合JSON較大，例如四模型邊界約93.6MB、固定條件比較約25.7MB。可先讀文件及JSON的 `verification`、`contract`、`limitations`，再按階段／群組查詢；GitHub是否能預覽不影響本機檔案內容。

規格透過SHA綁定既有報告、程式、原始CSV、特徵快取及模型。既有報告路徑與內容屬實驗來源鏈，清整時保留原位；另輪研究使用新的規格與輸出，不覆寫舊結果。逐筆訂單、分數帳本與特徵CSV保留在Git忽略的 `data/processed/`，模型在 `models/`，原始資料在 `data/raw/`，執行日誌及獨立驗證證明在 `.runtime/`，不提交這些本機產物。

Stage 4後期診斷的查詢／特徵截止早於2018-05-01；A等待組指主賣家歷史未觀測交運待件的等待時齡p90在 `(24,72]` 小時，不是當前訂單已等待24–72小時。小群組零涵蓋應讀成無足夠比較資料，不能寫成零效果。Stage 5另依評論首答與擬議fit時鐘盤點，不繼承這些延遲群組的效能結論。
