# 報告與圖表索引

`stage4/`保存延遲研究的聚合結果與規格（79份JSON），`stage5/`保存評論低評分預測的盤點、契約、合成驗證、開發回測與只讀診斷（29份），`stage6/`保存RFM盤點、資料集、G2／G3、公開來源、UCI 跨期與研究交付封存收據（36份）；`stage8/`保存Retailrocket來源與推薦契約、資料建置及逐格驗收（5份JSON）；`stage9/`保存熱門baseline／完整候選規格、實作、真實開發及驗收（6份JSON）；`stage10/`保存共現／P0規格、實作／成本／入口、真實配對驗收與研究交付保存收據（7份JSON）；`stage11/`保存候選、D1比較規格、實作／合成／成本與真實入口，以及一次真實三臂validation與獨立驗收、研究交付保存收據（8份JSON）；`stage12/`保存新時間可取得性、候選／比較規格、K1 實作／成本、validation 入口合成驗收／凍結、單次執行停止保存及另授權反讀事後狀態核對（8份JSON）；`images/`保存Stage 3 EDA及較早Stage 4圖表（21張）。先讀[專案首頁](../README.md)及[文件導覽](../docs/README.md)，需要重現時再查[腳本導覽](../scripts/README.md)。檔案日期或大小不代表方案優劣。

名稱含 `specification` 的檔案是該輪事前規格，`verification`／`preflight` 多為合成測試或準備查核，`acceptance`／`audit` 是對既有產物的獨立核對；只有實際訓練或描述報告含研究數字。測試數與metadata核對數不能當成模型效能。

## 從哪份報告開始

| 想確認的問題 | 閱讀順序 |
| --- | --- |
| Stage 12 最新：另授權反讀事後狀態核對 | [實際狀態與紀錄缺口](../docs/STAGE12_RETAILROCKET_KNN_READBACK_ONLY_20261029.md) → [10/30 核對報告](stage12/retailrocket_session_knn_v1_readback_status_audit_20261030.json)；已不在執行，末次觀測 923 筆，無完整驗收或逐程序收尾；17:07 左右有系統關機／啟動事件，原定 17:20 不等於實際停止時間。SHA 核對不是效能驗收，test locked |
| Stage 12 前輪：一次真實 validation 已停止 | [停止與界線](../docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ATTEMPT_V1.md) → [實際保存](stage12/retailrocket_session_knn_v1_validation_attempt.json)；整輪 3 小時 30 分鐘到時停止，主要 166,897 query／2,000 bootstrap 已產出，完整獨立驗收未完成，無正式 K1−C1 結論；0 重跑、test locked |
| Stage 12前輪：validation 入口驗收 | [入口](../docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ENTRY_V1.md) → [驗收](stage12/retailrocket_session_knn_v1_validation_entry_acceptance.json) → [凍結](stage12/retailrocket_session_knn_v1_validation_entry_specification.json)；83 項相關測試、兩組正式檔案合成案例完整 oracle 通過；358 份來源凍結、15 份直接輸入綁定；0 真實 K1 fit／validation，test locked |
| Stage 12前輪：K1 實作與成本 | [方法](../docs/STAGE12_RETAILROCKET_KNN_IMPLEMENTATION_V1.md) → [驗收](stage12/retailrocket_session_knn_v1_implementation_acceptance.json) → [實作凍結](stage12/retailrocket_session_knn_v1_implementation_specification.json)；49 項測試與兩組完整合成 oracle 通過；train 1,180,256 sessions、1,587,436 個不同 session-item；0 真實 K1 fit／validation，test locked |
| Stage 12前輪：時間可取得性與 K1 凍結 | [可讀規格](../docs/STAGE12_TEMPORAL_AVAILABILITY_AND_KNN_SPEC_V1.md) → [盤點](stage12/retailrocket_stage12_inventory_v1.json) → [凍結收據](stage12/retailrocket_session_knn_v1_specification.json)；新驗收來源 0、固定 Jaccard k=500，12 項規格測試通過，0 新 fit／排名／指標，test locked |
| Stage 11最新：三臂研究交付／證據保存 | [交付、適用與還原](../docs/STAGE11_RETAILROCKET_THREE_ARM_RESEARCH_HANDOFF_V1.md) → [保存收據](stage11/retailrocket_three_arm_v1_research_release.json)；144 個 payload＋manifest、44 項保存測試與 CRC／SHA 通過，0 新研究計算，test locked |
| Stage 11：D1／C1／P0真實validation | [結果／區間／限制](../docs/STAGE11_RETAILROCKET_DIRECTED_VALIDATION_V1.md) → [正式聚合](stage11/retailrocket_directed_v1_validation.json) → [獨立驗收](stage11/retailrocket_directed_v1_validation_acceptance.json)；D1 NDCG@10 0.099799771，D1−C1 差 -0.006600944，95% 區間 [-0.007511893, -0.005716747]；166,897查詢／2,000次主要bootstrap完整通過，test locked |
| Stage 11：D1實作／成本／真實入口 | [手算／方法／限制](../docs/STAGE11_RETAILROCKET_DIRECTED_IMPLEMENTATION_V1.md) → [實作與成本驗收](stage11/retailrocket_directed_v1_implementation_acceptance.json) → [真實入口](stage11/retailrocket_directed_v1_validation_specification.json)；60 項測試、217 份來源凍結、兩組正式合成 oracle 全過；0真實D1 fit／排名，test locked |
| Stage 11：D1候選與比較規格 | [方法／限制](../docs/STAGE11_RETAILROCKET_DIRECTED_SPEC_V1.md) → [候選盤點](stage11/retailrocket_stage11_candidate_inventory_v1.json) → [凍結](stage11/retailrocket_directed_v1_specification.json) → [驗收](stage11/retailrocket_directed_v1_spec_acceptance.json)；199 份來源 SHA、228 項規格檢查、109 項規格／I/O 守門測試通過；0新fit／排名／指標，test locked |
| Stage 10最新：C1／P0研究交付與保存 | [交付／適用](../docs/STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md) → [保存收據](stage10/retailrocket_c1_p0_v1_research_release.json)；102個payload檔＋1份manifest，257,447,194 bytes（245.521 MiB）；全部CRC／SHA讀回通過，另列98份包外但仍在shop內依賴；0新fit／排名／指標 |
| Stage 10：C1／P0真實配對結果 | [結果／區間／限制](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_VALIDATION_V1.md) → [正式聚合](stage10/retailrocket_cooccurrence_v1_validation.json) → [獨立驗收](stage10/retailrocket_cooccurrence_v1_validation_acceptance.json)；C1 NDCG@10 0.106400714，配對差 0.104718885；166,897 validation／2,000次bootstrap及獨立反讀完成，test locked |
| Stage 10：C1／配對／bootstrap 實作與入口 | [手算／限制／操作](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_IMPLEMENTATION_V1.md) → [實作與成本驗收](stage10/retailrocket_cooccurrence_v1_implementation_acceptance.json) → [真實入口](stage10/retailrocket_cooccurrence_v1_validation_specification.json)；55 項測試、104 份來源凍結與兩組正式合成 oracle 全過，train-only 成本核對通過，0真實C1 fit／validation出分，test locked |
| Stage 10：共現／P0 配對規格 | [規則與限制](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_PAIRED_SPEC_V1.md) → [來源凍結](stage10/retailrocket_cooccurrence_v1_specification.json) → [驗收](stage10/retailrocket_cooccurrence_v1_spec_acceptance.json)；82 來源 SHA、131 項一致性檢查、64 項規格測試通過，0 新 fit／排名／比較／bootstrap，test locked |
| Stage 9最新：P0真實開發／逐query反讀 | [成績、分母與限制](../docs/STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md) → [正式聚合](stage9/retailrocket_popularity_v1_development.json) → [獨立驗收](stage9/retailrocket_popularity_v1_development_acceptance.json)；166,897筆validation，NDCG 0.001681829／HitRate 0.418222%；test locked |
| Stage 9：P0／評估器實作與入口 | [手算／實作界線](../docs/STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md) → [合成驗收](stage9/retailrocket_popularity_v1_implementation_acceptance.json) → [真實開發入口](stage9/retailrocket_popularity_v1_development_specification.json)；54測試／61來源／兩case35列226格，0真實fit或排名，test locked |
| Stage 9：熱門baseline／評估器規格 | [完整規則](../docs/STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md) → [來源凍結](stage9/retailrocket_popularity_v1_specification.json) → [規格驗收](stage9/retailrocket_popularity_v1_spec_acceptance.json)；47來源／38項檢查／28測試，0fit／排名／指標，test locked |
| Stage 8最新：推薦資料建置及反讀 | [結果／限制](../docs/STAGE8_RETAILROCKET_BUILD_V1.md) → [執行前規格](stage8/retailrocket_build_v1_specification.json) → [正式聚合](stage8/retailrocket_build_v1.json) → [逐格驗收](stage8/retailrocket_build_v1_acceptance.json)；16CSV完整通過，0模型／排名成績 |
| Stage 8：Retailrocket來源與契約 | [來源／契約說明](../docs/STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md) → [完整實讀聚合](stage8/retailrocket_source_audit_v1.json) → [44項獨立核對／凍結](stage8/retailrocket_contract_v1_acceptance.json)；只讀來源結構與時間，0推薦樣本／模型／排名成績 |
| Stage 6最新：研究交付與 UCI v1 封存 | [適用與交付說明](../docs/STAGE6_RFM_RESEARCH_HANDOFF.md) → [封存完整性收據](stage6/uci_rfm_v1_research_release.json)；離線研究交付完成，小組／回溯限制保留 |
| Stage 6：UCI 固定切點跨期比較 | [結果與限制](../docs/STAGE6_UCI_RFM_TEMPORAL_V1.md) → [事前規格](stage6/uci_rfm_temporal_v1_specification.json) → [完整聚合](stage6/uci_rfm_temporal_v1.json) → [獨立驗收](stage6/uci_rfm_temporal_v1_acceptance.json)；跨期描述完成，小組不足保留 |
| Stage 6：UCI 真實雙期建置 | [結果與操作](../docs/STAGE6_UCI_RFM_BUILD_V1.md) → [執行規格](stage6/uci_rfm_build_v1_specification.json) → [實測聚合](stage6/uci_rfm_build_v1.json) → [獨立驗收](stage6/uci_rfm_build_v1_acceptance.json)；八組／32 CSV 全部核對，0 切點／跨期成績 |
| Stage 6：UCI 回溯契約 v1 | [完整規則](../docs/STAGE6_UCI_RFM_CONTRACT_V1.md) → [機器契約](../docs/contracts/uci_rfm_v1.json) → [來源凍結](stage6/uci_rfm_v1_specification.json) → [實際驗收](stage6/uci_rfm_v1_contract_acceptance.json)；規格已凍結，0 真實 RFM／跨期成績 |
| Stage 6：UCI 完整資料品質與可行性 | [品質、限制與下一步](../docs/STAGE6_UCI_RETAIL_II_INTAKE.md) → [實讀聚合](stage6/uci_retail_ii_intake.json) → [獨立 XML 核對](stage6/uci_retail_ii_verification.json)；可另立回溯研究，清理契約尚未定案 |
| Stage 6：公開後期來源可用性 | [搜尋與候選比較](../docs/STAGE6_RFM_PUBLIC_SOURCE_SEARCH.md) → [來源與 HTTP 紀錄](stage6/rfm_public_source_search.json)；未找到合格 Olist 延伸，優先建議驗收 UCI 另開回溯研究；尚非資料品質或成績通過 |
| Stage 6：第二快照資料盤點 | [現有資料與缺件](../docs/STAGE6_RFM_TEMPORAL_DATA_INVENTORY.md) → [實際聚合](stage6/rfm_temporal_data_inventory.json)；同一來源尾端只有 20 筆購買，無合格新增單，跨期待資料 |
| Stage 6：五種子 G3 | [結果與限制](../docs/STAGE6_RFM_G3_V2.md) → [69來源及事前規格](stage6/rfm_g3_v2_specification.json) → [五種子正式結果](stage6/rfm_g3_v2.json)；同快照 G3 通過，小組／跨期限制保留 |
| Stage 6：v2 重建與真實 G2 | [結果與操作](../docs/STAGE6_RFM_REBUILD_V2.md) → [61來源及實測規格](stage6/rfm_rebuild_v2_specification.json) → [真實結果與完整反讀](stage6/rfm_rebuild_v2.json)；v2 當輪止於 G2，25 個小組支援不足；後續 G3 見上列 |
| Stage 6原 v1：真實G2執行準備到哪裡 | [準備契約](../docs/STAGE6_RFM_RULE_CANDIDATE_EXECUTION.md) → [57來源規格](stage6/rfm_rule_candidate_execution_specification.json) → [準備查核](stage6/rfm_rule_candidate_execution_preflight.json)；合成接線與metadata／hash，真實G2未執行 |
| Stage 6：真實RFM描述長什麼樣 | [結果與限制](../docs/STAGE6_RFM_DESCRIPTION_RESULTS.md) → [完整聚合](stage6/rfm_description.json) → [交付驗收](stage6/rfm_description_acceptance.json)；只有G1描述，沒有切點或分群 |
| Stage 5：評論預測的結果與適用範圍 | [模型卡](../docs/STAGE5_MODEL_APPLICABILITY.md) → [四欄開發回測](stage5/review_baseline_training.json) → [三欄消融](stage5/review_month_ablation_training.json) → [配對驗收](stage5/review_month_ablation_training_acceptance.json) |
| Stage 5：還有哪些時間窗可驗證 | [解讀與缺口](../docs/STAGE5_REVIEW_VALIDATION_WINDOWS.md) → [實際盤點](stage5/review_validation_window_inventory.json) → [用途凍結](stage5/review_validation_window_usage_freeze.json)；五個新窗待資料 |
| Stage 4：延遲模型可用到什麼程度 | [模型卡](../docs/STAGE4_MODEL_APPLICABILITY.md) → [歷史選模主方案](stage4/rank_pair_focus.json) → [四設定五種子](stage4/age_colsample.json) |
| Stage 4：每日提醒交付與全量資料缺口 | [單日驗收](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md) → [聚合驗收](stage4/daily_delivery_acceptance.json) → [全量日資料契約](stage4/daily_data_contract.json)；待資料，不是生產完整性或效能通過 |
| Stage 4：事件／承諾版本來源 | [查核範圍與結論](../docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md) → [來源快照與驗收契約](stage4/event_source_availability_specification.json) → [實際查核](stage4/event_source_availability.json) |
| 原版固定測試的定義與成績 | [原版文件](../docs/STAGE4_DELAY_PREDICTION.md) → [metrics.json](stage4/metrics.json) |

colsample後的診斷、來源查核與交付驗收沿用原101／時齡102欄 × colsample0.8／1.0、五種子及每日10%規則，沒有新fit、方案改選或重評原保留測試。模型診斷屬反覆檢視的歷史驗證／開發回測；來源查核是schema與時鐘證據，單日驗收只核既有來源／排序／輸出契約，不新增預測成績。原版`metrics.json`的test、各輪validation及development不能合併成未知資料成績；主方案413TP也不是五種子平均。

## Stage 6全部JSON對照

依研究先後排列。公開報告只含聚合值、來源版本與驗收結果；個體ID、RFM值與私有digest留在Git忽略的`.runtime/stage6_*`。

| 研究主題 | 規格 | 結果與驗收 |
| --- | --- | --- |
| RFM輸入盤點 | [rfm_feasibility_specification](stage6/rfm_feasibility_specification.json) | [rfm_feasibility](stage6/rfm_feasibility.json) |
| RFM資料集契約 | [rfm_dataset_specification](stage6/rfm_dataset_specification.json) | [rfm_dataset_contract_audit](stage6/rfm_dataset_contract_audit.json) |
| builder與真實建置 | [rfm_dataset_build_specification](stage6/rfm_dataset_build_specification.json) | [rfm_dataset_build](stage6/rfm_dataset_build.json)、[rfm_dataset_build_acceptance](stage6/rfm_dataset_build_acceptance.json) |
| 描述／分群評估規格 | [rfm_evaluation_specification](stage6/rfm_evaluation_specification.json) | [rfm_evaluation_contract_audit](stage6/rfm_evaluation_contract_audit.json) |
| 只讀描述器合成驗收 | [rfm_description_implementation_specification](stage6/rfm_description_implementation_specification.json) | [rfm_description_pipeline_verification](stage6/rfm_description_pipeline_verification.json) |
| 真實描述執行準備 | [rfm_description_execution_specification](stage6/rfm_description_execution_specification.json) | [rfm_description_execution_preflight](stage6/rfm_description_execution_preflight.json) |
| 一次真實只讀描述（G1） | 沿用上列執行規格 | [rfm_description](stage6/rfm_description.json)、[rfm_description_acceptance](stage6/rfm_description_acceptance.json) |
| G2規則候選合成驗收 | [rfm_rule_candidate_implementation_specification](stage6/rfm_rule_candidate_implementation_specification.json) | [rfm_rule_candidate_verification](stage6/rfm_rule_candidate_verification.json) |
| G2真實執行準備 | [rfm_rule_candidate_execution_specification](stage6/rfm_rule_candidate_execution_specification.json) | [rfm_rule_candidate_execution_preflight](stage6/rfm_rule_candidate_execution_preflight.json)；此 v1 準備版不補寫真實結果，後續使用下列 v2 |
| v2 重建與真實 G2 | [rfm_rebuild_v2_specification](stage6/rfm_rebuild_v2_specification.json) | [rfm_rebuild_v2](stage6/rfm_rebuild_v2.json)；新資料集、G1、G2 全部反讀，各軸通過、小組限制保留 |
| 五種子 G3 | [rfm_g3_v2_specification](stage6/rfm_g3_v2_specification.json) | [rfm_g3_v2](stage6/rfm_g3_v2.json)；五種子完整結果、最差值、小組限制與反讀 |
| 第二快照與跨期資料盤點 | —（可用性盤點，不是模型事前規格） | [rfm_temporal_data_inventory](stage6/rfm_temporal_data_inventory.json)；來源副本／時鐘／鍵覆蓋，0 新 RFM／切點／效能評估，跨期待資料 |
| Olist 後期公開來源與替代資料 | —（來源可用性查核，不是模型事前規格） | [rfm_public_source_search](stage6/rfm_public_source_search.json)；來源與三候選比較、HTTP／片段查核及限制；官方規模與日期明標為文件說明，非逐筆實測 |
| UCI 官方完整資料盤點 | —（品質盤點與候選敏感度，不是 RFM 事前規格） | [uci_retail_ii_intake](stage6/uci_retail_ii_intake.json)、[uci_retail_ii_verification](stage6/uci_retail_ii_verification.json)；全檔品質、月別及探索窗口，0 新 RFM／切點／效能 |
| UCI 回溯 RFM 契約 v1 | [uci_rfm_v1_specification](stage6/uci_rfm_v1_specification.json)；綁定 [JSON 規則](../docs/contracts/uci_rfm_v1.json) | [uci_rfm_v1_contract_acceptance](stage6/uci_rfm_v1_contract_acceptance.json)；15 來源、35 契約檢查、38 合成測試，非真實建置或成績 |
| UCI v1 真實建置與獨立驗收 | [uci_rfm_build_v1_specification](stage6/uci_rfm_build_v1_specification.json) | [uci_rfm_build_v1](stage6/uci_rfm_build_v1.json)、[uci_rfm_build_v1_acceptance](stage6/uci_rfm_build_v1_acceptance.json)；顧客／發票／逐列／去重完整反讀，無切點或訓練 |
| UCI v1 固定切點跨期比較 | [uci_rfm_temporal_v1_specification](stage6/uci_rfm_temporal_v1_specification.json) | [uci_rfm_temporal_v1](stage6/uci_rfm_temporal_v1.json)、[uci_rfm_temporal_v1_acceptance](stage6/uci_rfm_temporal_v1_acceptance.json)；T1 單次切點、四口徑跨期與支援、獨立驗收，不等於業務通過 |
| Stage 6 研究交付與 UCI v1 封存 | —（交付及檔案完整性，不是新實驗規格） | [uci_rfm_v1_research_release](stage6/uci_rfm_v1_research_release.json)；ZIP hash、逐檔 CRC／SHA、來源與脈絡快照角色、實際封存測試；0 新研究計算 |

## Stage 5全部JSON對照

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

## 圖表與來源保護

[images/](images/) 的 `olist_*.png` 對應Stage 3商業EDA；`stage4_*.png` 對應原版、模型比較及較早校準研究。後續輪次主要以JSON與研究文件呈現，舊圖不是最新方案成績。

部分聚合JSON較大，例如四模型邊界約93.6MB、固定條件比較約25.7MB。可先讀文件及JSON的 `verification`、`contract`、`limitations`，再按階段／群組查詢；GitHub是否能預覽不影響本機檔案內容。

規格透過SHA綁定既有報告、程式、原始CSV、特徵快取及模型。既有報告路徑與內容屬實驗來源鏈，清整時保留原位；另輪研究使用新的規格與輸出，不覆寫舊結果。逐筆訂單、分數帳本與特徵CSV保留在Git忽略的 `data/processed/`，模型在 `models/`，原始資料在 `data/raw/`，執行日誌及獨立驗證證明在 `.runtime/`，不提交這些本機產物。

Stage 4後期診斷的查詢／特徵截止早於2018-05-01；A等待組指主賣家歷史未觀測交運待件的等待時齡p90在 `(24,72]` 小時，不是當前訂單已等待24–72小時。小群組零涵蓋應讀成無足夠比較資料，不能寫成零效果。Stage 5另依評論首答與擬議fit時鐘盤點，不繼承這些延遲群組的效能結論。
