# 報告與圖表索引

`stage4/` 保存各輪已執行的聚合結果與事前規格；`images/` 保存EDA及較早Stage 4圖表。先讀[專案現況](../README.md)及[研究文件索引](../docs/README.md)，需要重現時再查[程式入口](../scripts/README.md)。檔案日期或大小不代表方案優劣。

## 從哪份報告開始

| 想確認的問題 | 閱讀順序 |
| --- | --- |
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

代表性稽核的初版規格保留發布前JSON格式修正紀錄，未產生正式報告；計算規則未變，重現應使用正式規格，說明見[當輪文件](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md)。

## 圖表與來源保護

[images/](images/) 的 `olist_*.png` 對應Stage 3商業EDA；`stage4_*.png` 對應原版、模型比較及較早校準研究。後續輪次主要以JSON與研究文件呈現，舊圖不是最新方案成績。

部分聚合JSON較大，例如四模型邊界約93.6MB、固定條件比較約25.7MB。可先讀文件及JSON的 `verification`、`contract`、`limitations`，再按階段／群組查詢；GitHub是否能預覽不影響本機檔案內容。

規格透過SHA綁定既有報告、程式、原始CSV、特徵快取及模型。既有報告路徑與內容屬實驗來源鏈，清整時保留原位；另輪研究使用新的規格與輸出，不覆寫舊結果。逐筆訂單、分數帳本與特徵CSV保留在Git忽略的 `data/processed/`，模型在 `models/`，原始資料在 `data/raw/`，執行日誌及獨立驗證證明在 `.runtime/`，不提交這些本機產物。

最新兩輪的查詢／特徵截止均早於2018-05-01；A等待組指主賣家歷史未觀測交運待件的等待時齡p90在 `(24,72]` 小時，不是當前訂單已等待24–72小時。小群組零涵蓋應讀成無足夠比較資料，不能寫成零效果。
