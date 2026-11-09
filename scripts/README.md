# 程式與操作入口

所有命令都從專案根目錄執行，使用 `.venv` 的 Python。環境安裝與資料庫設定見[本機建置](../docs/LOCAL_SETUP.md)，目前結論見[專案首頁](../README.md)，報告對應見[報告索引](../reports/README.md)。

## 先選擇要做的工作

| 工作 | 入口 | 執行前提與產物 |
| --- | --- | --- |
| K1 V29 序列化成本與候選 | [已存事件與隔離重播](inventory_retailrocket_session_knn_serialization_v29.py)、[規格封存／核對](freeze_retailrocket_session_knn_serialization_v29.py) | 盤點完成；C1-S1 版本化完整快照指紋與 32 個新增驗收情境已封存，尚未實作候選。現有產物用各入口 `--audit`；沒有候選 measure 選項。[盤點與規格](../docs/STAGE12_KNN_SERIALIZATION_V29_20261109.md) |
| K1 V28 C1 原 48 筆比較 | [受監督真實入口](run_retailrocket_session_knn_compare_v28.py)、[獨立發布與門檻](retailrocket_session_knn_compare_v28.py) | 81 項整合驗收及唯一真實窗口已完成，672 次核對通過；六對完整入口全部較慢，維持不採用。查看既有報告或 `--release <原 namespace>` 重稽核；`--measure` 拒絕已有 request 重測。[規格與結果](../docs/STAGE12_KNN_C1_COMPARE_V28_20261109.md) |
| K1 V27 C1 唯讀初始化 | [核心與原方法接合](retailrocket_session_knn_reuse_v27.py)、[合成驗收／重稽核](accept_retailrocket_session_knn_reuse_v27.py) | 73 項合成測試與 38 封存情境通過，人工 48 筆十四帳本及獨立程序發布驗證完成；`--acceptance` 已完成，只讀重核對用 `--audit`。沒有真實 measure CLI；見[實作與驗收](../docs/STAGE12_KNN_C1_CONTEXT_V27_20261109.md)。 |
| K1 V26 重複成本與候選規格 | [已存證據盤點](inventory_retailrocket_session_knn_reuse_v26.py)、[封存／稽核入口](freeze_retailrocket_session_knn_reuse_v26.py) | `--inventory` 只盤點 V25 證據；封存入口 `--specification`／`--audit` 固定兩候選及 38 個待執行驗收情境。已有產物拒絕覆寫，沒有 measure／排名選項；見[盤點與候選規格](../docs/STAGE12_KNN_REPEATED_COST_V26_20261109.md)。 |
| K1 V25 受監督來源診斷與獨立發布 | [整合入口](run_retailrocket_session_knn_sources_v25.py) | 32 項合成驗收及原 48 筆十四次循序實測已完成，672 次核對通過；worker 與獨立 publisher 共用 1,800 秒期限。查看[本輪結果](../docs/STAGE12_KNN_SOURCE_ENTRY_V25_20261109.md)；`--release <原 namespace>` 只重稽核既有窗口，`--measure` 遇既有 request 拒絕重測。 |
| K1 V20 固定七筆診斷 | [有界入口](run_retailrocket_session_knn_diagnostics_v20.py) | 沿用七筆，以 R／D、D／R、R／D 六輪循序拆分 SQL、append 與預算檢查，同步記錄負載。[規格與結果](../docs/STAGE12_KNN_DIAGNOSTICS_V20_20261106.md) |
| K1 V19 高鄰居尾端補樣 | [有界入口](run_retailrocket_session_knn_tail_v19.py) | 三段各取最大鄰居數與固定雜湊樣本，六筆新查詢加原對照；七筆循序三輪及 200ms 目標負載觀測。[規格與結果](../docs/STAGE12_KNN_TAIL_V19_20261106.md) |
| K1 V18 兩格補樣與負載 | [有界入口](run_retailrocket_session_knn_reinforcement_v18.py) | 兩格各四筆新查詢與一筆舊對照，同批十筆循序三輪；200ms 目標負載觀測與三帳本核對。[規格與結果](../docs/STAGE12_KNN_REINFORCEMENT_V18_20261106.md) |
| K1 V17 投票記數候選 | [配對比較入口](run_retailrocket_session_knn_vote_v17.py) | rank_counts 與原 V4 六對 AB／BA；48 筆達門檻才比較既有 34 筆，沒有新選樣。[規格與結果](../docs/STAGE12_KNN_COST_ROLLUP_V17_20261106.md) |
| K1 V17 全細層成本彙整 | [唯讀彙整入口](run_retailrocket_session_knn_cost_rollup_v17.py) | 核對 11 組固定樣本，彙整 55 格的 156 個查詢、360 次成本觀測，分開同查詢波動與人口加權情境。[方法與結果](../docs/STAGE12_KNN_COST_ROLLUP_V17_20261106.md) |
| K1 V16 剩餘三格容量補測 | [有界入口](run_retailrocket_session_knn_gap_v16.py) | 十一組歷史排除，按容量固定 4／4／2 筆，各核對兩次。檢查全鄰居投票等式、前 500 位切點及十筆保存與原期限。[方法與結果](../docs/STAGE12_KNN_FINAL_GAPS_V16_20261106.md) |
| K1 V15 500–999 與 100–499 鄰居帶 | [有界入口](run_retailrocket_session_knn_gap_v15.py) | 十組歷史排除、兩格各 4 筆，各核對兩次。檢查前 500 位切點、全鄰居投票等式與原期限。[方法與結果](../docs/STAGE12_KNN_N4_N3_VOTE_GAP_V15_20261106.md) |
| K1 V14 全數入選與前五百位 | [有界入口](run_retailrocket_session_knn_gap_v14.py) | 九組歷史排除、兩格各 4 筆，各核對兩次。檢查全鄰居投票等式、前 500 位切點與原期限。[方法與結果](../docs/STAGE12_KNN_N3_N5_VOTE_GAP_V14_20261106.md) |
| K1 V13 雙鄰居帶與投票量缺口 | [有界入口](run_retailrocket_session_knn_gap_v13.py) | 八組歷史排除、兩格各 4 筆，各核對兩次。檢查前 500 位切點、投票上界與原期限。[方法與結果](../docs/STAGE12_KNN_N5_N4_VOTE_GAP_V13_20261106.md) |
| K1 V12 高鄰居低投票與低鄰居高投票 | [有界入口](run_retailrocket_session_knn_gap_v12.py) | 每格 4 筆，各核對兩次。檢查原期限、前 500 位切點與全數入選的投票等式。[方法與驗收](../docs/STAGE12_KNN_N5_N3_GAP_SPEC_V12_20261105.md) |
| K1 V11 同鄰居帶的兩種投票量 | [有界入口](run_retailrocket_session_knn_gap_v11.py) | 每格固定 4 筆，核對恰好 500 與超過 500 的切點、實際投票量及保存。[本輪結果](../docs/STAGE12_KNN_N4_VOTE_BANDS_V11_20261105.md) |
| K1 V10 兩個超過 500 鄰居的細層 | [有界入口](run_retailrocket_session_knn_gap_v10.py) | 兩格各 4 筆、各核對兩次，分項記錄完整池、500 鄰居、平手與實際投票列數。[方法與結果](../docs/STAGE12_KNN_TWO_CAPPED_CELLS_V10_20261105.md) |
| K1 V9 上限兩側的補測 | [有界入口](run_retailrocket_session_knn_gap_v9.py) | 分別核對高鄰居格的前 500 位與低鄰居格的全數入選，再比較兩份 ledger。[方法與結果](../docs/STAGE12_KNN_CAPPED_GAP_V9_20261105.md) |
| K1 V8 兩個最大細層補測 | [有界入口](run_retailrocket_session_knn_gap_v8.py) | 固定兩格各 4 筆，兩次原版精確驗證，逐列比較科學 bytes。[方法與結果](../docs/STAGE12_KNN_100_499_GAP_V8_20261105.md) |
| K1 V7 投票診斷與配對 | [有界入口](run_retailrocket_session_knn_vote_v7.py) | 使用原 48 筆診斷並擇一候選。六對 AB／BA 達預定門檻才可進入新 34 筆比較。查看[本輪結果](../docs/STAGE12_KNN_GAP_AND_VOTE_RESULTS_20261105.md)。 |
| K1 V7 低鄰居補測 | [有界入口](run_retailrocket_session_knn_gap_v7.py) | 先合成驗收，再獨立選出 17 格共 34 筆並精確核對兩次。已執行的結果見[本輪記錄](../docs/STAGE12_KNN_GAP_AND_VOTE_RESULTS_20261105.md)。 |
| K1 V6 原48筆分層／append成本複測 | [驗收與有界入口](run_retailrocket_session_knn_refined_cost_v6.py)、[分層](retailrocket_session_knn_refined_cost_v6.py)、[append分項](retailrocket_session_knn_detailed_cost_v6.py) | 26項驗收及三次原48筆實測均已完成；237.703秒正常退出，532來源／科學bytes同值。查看請直接讀[實測](../reports/stage12/retailrocket_session_knn_v6_refined_cost_20261103.json)，不為查看重跑；無全量／test入口。[方法與操作](../docs/STAGE12_RETAILROCKET_KNN_REFINED_COST_V6_20261103.md) |
| K1 V5 預算保存觀測與成本決策 | [checkpoint 成本觀測器](retailrocket_session_knn_checkpoint_cost_v5.py)、[工程帳本重播](retailrocket_session_knn_ledger_cost_v5.py) | 在同一批 48 筆查詢上分開計時逐筆寫入、區塊提交與其他階段的預算保存。全量反讀維持關閉。[決策報告](../reports/stage12/retailrocket_session_knn_v5_cost_coverage_decision_20261103.json) |
| K1 V5 完整規模工程帳本建置 | [來源帳本與封存](retailrocket_session_knn_ledger_cost_v5.py)、[方法說明](../docs/STAGE12_RETAILROCKET_KNN_SOURCE_LEDGER_BUILD_V5_20261103.md) | 從已存四臂輸出建立工程帳本，用於量測實際資料形狀的序列化、分塊與寫入成本。查看本次結果請讀[建置成本報告](../reports/stage12/retailrocket_session_knn_v5_ledger_build_cost_20261103.json)。 |
| K1 V5 聯合尾端成本 | [結構分層與成本彙總](retailrocket_session_knn_joint_cost_v5.py)、[方法說明](../docs/STAGE12_RETAILROCKET_KNN_JOINT_TAIL_COST_V5_20261103.md) | 依完整 validation 的工作量結構凍結樣本，在 12 個非空分層實測 48 筆配對。[聯合尾端成本報告](../reports/stage12/retailrocket_session_knn_v5_joint_cost_20261103.json) |
| K1 V5 完整獨立重建成本 | [重建與逐檔核對](retailrocket_session_knn_rebuild_cost_v5.py)、[外部監督窗口](retailrocket_session_knn_cost_window_v5.py)、[方法說明](../docs/STAGE12_RETAILROCKET_KNN_REBUILD_COST_V5_20261103.md) | 只在全新目錄從已綁定的原始來源建立獨立 SQL 模型。實測已完成，耗時與範圍可直接查閱[成本報告](../reports/stage12/retailrocket_session_knn_v5_rebuild_cost_20261103.json)。 |
| K1 V4 來源定位與逐筆大小量測 | [七路來源索引](retailrocket_session_knn_sources_v4.py)、[逐筆大小與前綴掃描](retailrocket_session_knn_payload_v4.py)、[定位成本對照](retailrocket_session_knn_source_cost_v4.py) | 28 項合成測試通過。工程配對限於凍結的 64 筆 validation 子集；六個固定位置另量原始來源的讀取成本。預留測試維持鎖定。 |
| K1 V4 所選配對成本核心 | [精確 SQL](retailrocket_session_knn_sql_v4.py)、[指標檢查](retailrocket_session_knn_checks_v4.py)、[配對／恢復](retailrocket_session_knn_pair_v4.py)、[說明](../docs/STAGE12_RETAILROCKET_KNN_PAIR_OPTIMIZATION_V4_20261103.md) | 只允許最多64個凍結工程樣本；39項等價／故障通過。full global helper僅限人工fixture，無真實全量／test CLI；既有成本直接讀報告，不重跑 |
| K1 V3 工程成本診斷 | [run_retailrocket_session_knn_cost_v3.py](run_retailrocket_session_knn_cost_v3.py)、[配對抽取](retailrocket_session_knn_pair_probe_v3.py)、[人工代理](retailrocket_session_knn_proxy_v3.py)、[方法](../docs/STAGE12_RETAILROCKET_KNN_COST_COMPONENTS_V3_20261103.md) | --diagnose 會另開新 30 分鐘工程窗口，需方法名冊／SHA／封存 DB／原來源完整相符；已完成一次，不為查看結果重跑。無全量／final／test 開關 |
| K1 validation 入口凍結核對 | [run_retailrocket_session_knn_v1.py](run_retailrocket_session_knn_v1.py)、[loader](retailrocket_session_knn_io.py)、[完整獨立反讀](retailrocket_session_knn_readback.py)、[操作](../docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ENTRY_V1.md) | 真實單次執行已依 3 小時 30 分鐘上限停止；namespace 為 partial，禁止再 --run-validation，原 --verify 會拒絕部分結果。只讀來源核對見最新停止文件，無 final／test 模式 |
| 三臂研究交付與保存 | [archive_retailrocket_three_arm_v1.py](archive_retailrocket_three_arm_v1.py)、[交付說明](../docs/STAGE11_RETAILROCKET_THREE_ARM_RESEARCH_HANDOFF_V1.md) | --verify 核 ZIP／live 凍結證據／包外依賴；--verify-archive-only 僅核包與收據；不重算研究、不解壓、不開 test |
| D1／三臂／bootstrap 真實完整驗收 | [run_retailrocket_directed_v1.py](run_retailrocket_directed_v1.py)、[結果與操作](../docs/STAGE11_RETAILROCKET_DIRECTED_VALIDATION_V1.md) | 已單次 train／完整 validation／主要 bootstrap 與全反讀；現只 --verify，不追加 fit／排名／抽樣；沒有 final／test 模式 |
| D1／C1／P0 比較規格 | [freeze_retailrocket_directed_v1.py](freeze_retailrocket_directed_v1.py)、[守門](retailrocket_directed_protocol.py)、[規格](../docs/STAGE11_RETAILROCKET_DIRECTED_SPEC_V1.md) | --verify 核歷史凍結與 locked scope；沒有 D1 fit／rank／bootstrap／test 入口 |
| C1／P0研究交付與證據保存 | [archive_retailrocket_c1_p0_v1.py](archive_retailrocket_c1_p0_v1.py)、[交付說明](../docs/STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md) | --verify核ZIP／live凍結證據與包外依賴；--verify-archive-only僅核包與收據；不fit／rank／解壓／開test |
| Retailrocket C1／配對／bootstrap 與真實入口 | [run_retailrocket_cooccurrence_v1.py](run_retailrocket_cooccurrence_v1.py)、[核心](retailrocket_cooccurrence.py)、[adapter](retailrocket_cooccurrence_io.py)、[獨立oracle](retailrocket_cooccurrence_oracle.py)、[結果與操作](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_VALIDATION_V1.md) | 已單次train fit／完整validation／bootstrap及獨立反讀；只用--verify核bytes，不追加fit或重播；無final／test模式 |
| Retailrocket 共現／P0 配對規格 | [freeze_retailrocket_cooccurrence_v1.py](freeze_retailrocket_cooccurrence_v1.py)、[規格守門](retailrocket_cooccurrence_protocol.py)、[規則與限制](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_PAIRED_SPEC_V1.md) | 初始規格已凍結；其舊--verify要求真實目錄不存在，目前由最新run入口核全部歷史SHA。規格程式不做fit／rank或test |
| Retailrocket P0／評估器與開發入口 | [run_retailrocket_popularity_v1.py](run_retailrocket_popularity_v1.py)、[核心](retailrocket_popularity.py)、[CSV](retailrocket_popularity_io.py)、[獨立oracle](retailrocket_popularity_oracle.py)、[操作](../docs/STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md) | 已一次真實train fit／完整validation及獨立反讀；現只用--verify，不重估或出分；只允許validation，無final/test模式 |
| Retailrocket熱門baseline／評估規格 | [freeze_retailrocket_popularity_v1.py](freeze_retailrocket_popularity_v1.py)、[一致性檢查](retailrocket_popularity_protocol.py)、[完整規則](../docs/STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md) | 已凍結，只用 --verify 核SHA／規格；兩支程式都不實作fit、rank或指標，不啟用預留測試 |
| Retailrocket推薦資料建置／反讀 | [build_retailrocket_v1.py](build_retailrocket_v1.py)、[核心](retailrocket_builder.py)、[獨立路徑](retailrocket_reference.py)、[結果／操作](../docs/STAGE8_RETAILROCKET_BUILD_V1.md) | 已單次建置並完整逐格驗收；現用 --verify 核來源／輸出／收據bytes，不重建或重做語意核對；部分產物拒絕重播 |
| Retailrocket官方來源／推薦契約 | [audit_retailrocket_source.py](audit_retailrocket_source.py)、[freeze_retailrocket_contract.py](freeze_retailrocket_contract.py)、[完整說明](../docs/STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md) | 已完成完整掃描、44項獨立核對與凍結，現只用 --verify 核既有 SHA／大小；無參數首次流程會拒絕現有 namespace，不建推薦樣本或模型 |
| 核對第二快照資料盤點 | [audit_rfm_temporal_data.py](audit_rfm_temporal_data.py)、[結果與缺件](../docs/STAGE6_RFM_TEMPORAL_DATA_INVENTORY.md) | --verify 重新只讀原表／ZIP 的來源與時鐘／鍵聚合並比對報告；無參數僅首次建報告，來源或結果變更須另開版本。沒有新 RFM、切點、G2／G3 或模型訓練 |
| 驗證目前五種子 G3 | [run_rfm_g3.py](run_rfm_g3.py)、[核心](rfm_g3.py)、[獨立反讀](rfm_g3_outputs.py)、[來源](rfm_g3_sources.py)、[結果與操作](../docs/STAGE6_RFM_G3_V2.md) | G3 已完成，僅用 --verify；核來源、固定抽樣、全名冊分配與 ARI，不重跑 G3 核心。原 v2 資料與 G2 保留 |
| 驗證目前 v2 RFM／G2 | [rebuild_rfm_v2.py](rebuild_rfm_v2.py)、[獨立核對](rfm_rebuild_reference.py)、[操作與結果](../docs/STAGE6_RFM_REBUILD_V2.md) | v2 已完成，僅用 --verify；不重建或重跑核心。--prepare／--run 為本輪一次性流程，既有或部分產物阻止重播 |
| 原 v1：準備Stage 6真實G2來源／輸出反讀 | [prepare_rfm_rule_candidate.py](prepare_rfm_rule_candidate.py)、[sources](rfm_rule_candidate_sources.py)、[outputs](rfm_rule_candidate_outputs.py)、[操作契約](../docs/STAGE6_RFM_RULE_CANDIDATE_EXECUTION.md) | CLI僅--prepare；核57來源／source-bound收據與metadata後凍結，未來execute／verify只在合成scratch驗證；該 v1 準備輪未執行真實G2；後續真實執行使用獨立 v2 入口 |
| 驗證Stage 6 G2規則候選與資格守門 | [verify_rfm_rule_candidate.py](verify_rfm_rule_candidate.py)、[純G2核心](rfm_rule_candidate.py)、[實作與操作](../docs/STAGE6_RFM_RULE_CANDIDATE_IMPLEMENTATION.md) | 僅--verify-synthetic；首次實跑兩套新測試與四組合成案例，核49來源及既有G1證據後固定報告；重入只核既有收據，不重跑或覆寫。沒有真實G2入口 |
| 反讀Stage 6真實描述現有結果 | [凍結函式verify_completed](prepare_rfm_description.py)、[結果與操作](../docs/STAGE6_RFM_DESCRIPTION_RESULTS.md) | 已完成一次真實execute及完整反讀；現有bundle只做verify，不重播prepare／execute；不重算描述／切點或分群 |
| 準備Stage 6真實只讀描述（已完成） | [prepare_rfm_description.py](prepare_rfm_description.py)、[sources／獨立名冊](rfm_description_sources.py)、[outputs／反讀](rfm_description_outputs.py) | CLI只有--prepare，核41來源／實測receipt並凍結；準備本身不讀真實CSV，真實描述已另以凍結函式執行一次（見上一列），勿重播 |
| 驗證Stage 6只讀描述與資格守門 | [verify_rfm_description.py](verify_rfm_description.py)、[純描述器](rfm_description.py) | 只有--verify-synthetic，核兩套實測receipt／33來源／原metadata；不執行真實描述或估切點 |
| 凍結Stage 6描述／分群評估方法 | [freeze_rfm_evaluation_spec.py](freeze_rfm_evaluation_spec.py)、[純方法規則](rfm_evaluation_contract.py) | --specification-only再--audit；只核metadata／hash，連CSV header也不解析，不計描述或分群 |
| 驗收Stage 6實際RFM資料集 | [build_rfm_dataset.py](build_rfm_dataset.py)、[純builder](rfm_dataset_builder.py)、[私有writer](rfm_dataset_artifacts.py) | 一次建置已完成，現有bundle只用--verify；需原來源與guard，勿刪檔重播；不分群／訓練 |
| 凍結Stage 6 RFM資料集契約 | [freeze_rfm_dataset_spec.py](freeze_rfm_dataset_spec.py) | 先--specification-only再核母體／隔離／狀態聚合；不建立個體RFM、builder或分群 |
| 盤點Stage 6 RFM輸入支援 | [audit_rfm_feasibility.py](audit_rfm_feasibility.py) | 先--specification-only再只讀四CSV的鍵／時鐘／金額與候選窗口；不建個體RFM／分群，不讀評論或模型分數 |
| 盤點Stage 5後續時間窗與用途 | [audit_review_validation_windows.py](audit_review_validation_windows.py)、[metadata核心](review_validation_windows.py) | 先--specification-only凍結歷史與盤點，再核ID／時鐘；不讀新評分、不建y或訓練 |
| 稽核Stage 5逐fit成熟先驗與漂移 | [audit_review_mature_prior.py](audit_review_mature_prior.py)、[純統計核心](review_mature_prior_audit.py) | 先--specification-only再稽核原H60完整角色；不讀分數值、不fit或修正參數 |
| 只讀Stage 5雙臂機率／排序／支援 | [diagnose_review_ablation.py](diagnose_review_ablation.py)、[統計核心](review_ablation_diagnostics.py) | 先--specification-only，再讀兩臂成功產物與完整角色；18組配對及12組排序；模型呼叫及重新選C拒收 |
| Stage 5三欄正式入口與私有交付 | [run_review_month_ablation.py](run_review_month_ablation.py)、[訓練控制](review_month_ablation_training.py)、[私有writer](review_month_ablation_artifacts.py) | 無參數只顯示說明；一次--train已完成，training_v1已占用，勿重播；[結果與只讀驗收](../docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)，四欄沿用原分數 |
| Stage 5三欄消融來源與配對準備（已完成） | [prepare_review_month_ablation.py](prepare_review_month_ablation.py)、[review_month_ablation_sources.py](review_month_ablation_sources.py)、[review_month_ablation_pairing.py](review_month_ablation_pairing.py) | 需原私有證據；當時凍結政策／輸出版本，再核12角色與四欄18區塊，沒有訓練參數；現有產物已完成，勿重跑準備流程 |
| 驗證Stage 5三欄消融與四欄對照 | [verify_review_month_ablation_pipeline.py](verify_review_month_ablation_pipeline.py)、[review_month_ablation_pipeline.py](review_month_ablation_pipeline.py) | 只以合成fixture驗三欄32維／舊四欄44維；75項測試及35公開來源綁定，不讀真實CSV或私有分數 |
| 凍結Stage 5月份消融規格 | [freeze_review_month_ablation.py](freeze_review_month_ablation.py) | 先--specification-only，再只核metadata；保留原來源、只刪purchase_month契約；不實作三欄模型、不fit或解析分數 |
| 只讀Stage 5凍結分數做支援診斷 | [diagnose_review_scores.py](diagnose_review_scores.py)、[review_score_diagnostics.py](review_score_diagnostics.py) | 需原私有分數／角色／收據；先--specification-only固定診斷範圍，再核來源、統計分布；禁止模型fit／transform／predict，不補訓練 |
| 執行Stage 5四欄離線最小基線 | [run_review_baseline.py](run_review_baseline.py) | 需原資料／H60私有bundle／原收據／guard；先凍結新執行規格，正式入口會12次fit並做開發回測，已有結果則fit前拒收 |
| 驗證四欄builder與train-only pipeline | [verify_review_pipeline.py](verify_review_pipeline.py)、[review_baseline_pipeline.py](review_baseline_pipeline.py) | 僅合成fixture，無需原CSV／私有bundle；會fit測試用scaler／Logistic並檢查洩漏，不執行真實訓練 |
| 核對Stage 5最小基線規格 | [audit_review_baseline_contract.py](audit_review_baseline_contract.py) | 先--specification-only；只核來源、事件時鐘、未知／fit角色與固定基線政策，不建X或fit |
| 凍結Stage 5訂單級首答資料集 | [freeze_review_dataset.py](freeze_review_dataset.py) | 先--specification-only，再執行稽核；H60、多評論、未知與內外層時鐘，私有標籤／切分留.runtime，不建X或訓練 |
| 重現Stage 5評論預測可行性盤點 | [audit_review_prediction_feasibility.py](audit_review_prediction_feasibility.py) | 需原九CSV與既有來源報告；只查標籤／鍵／時鐘／候選欄位，不建特徵或訓練模型 |
| 檢查套件、MySQL及資料表 | [verify_environment.py](verify_environment.py) | 使用本機資料庫設定；摘要存 `.runtime/verification/summary.json` |
| 開啟教學分析 | [start_jupyter.ps1](start_jupyter.ps1) | 先啟動本專案 MySQL，再開啟 `notebooks/`；見[Notebook說明](../notebooks/README.md) |
| 啟停資料庫／開啟GUI | [start_mysql.ps1](start_mysql.ps1)、[stop_mysql.ps1](stop_mysql.ps1)、[start_dbeaver.ps1](start_dbeaver.ps1) | 工具、資料庫、設定與帳密都在本機忽略路徑 |
| 建立新電腦環境／匯入CSV | [setup_local_mysql.py](setup_local_mysql.py)、[load_olist_to_mysql.py](load_olist_to_mysql.py) | 初始化只供新環境；CSV匯入使用 `if_exists="replace"`，會重建同名資料表，操作見建置指南 |
| 載入模型做離線推論 | [predict_delay.py](predict_delay.py) | 需要本機 artifact；支援原版、平衡模式及指定研究模型，操作見[原版說明](../docs/STAGE4_DELAY_PREDICTION.md) |
| 重現單日離線交付驗收 | [accept_frozen_daily_delivery.py](accept_frozen_daily_delivery.py) | 需原始orders、凍結cache／帳本、報告及20份月模型bytes；只核SHA與已有分數，不載模型／預測／訓練 |
| 查全量日資料契約與缺口 | [audit_daily_data_contract.py](audit_daily_data_contract.py) | 只讀九CSV、匯入程式、既有報告；帳本只解析名冊／設定欄，不啟動DB／API |
| 閱讀適用範圍與交付前提 | [模型卡與交付清單](../docs/STAGE4_MODEL_APPLICABILITY.md) | 區分主方案wrapper與160份五種子月版；離線研究可交付，沒有生產日結／通知服務 |
| 閱讀待資料方向 | [事件／承諾版本來源](../docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md) | 新增驗收來源0，先讀查核範圍與資料契約；不需要啟動MySQL或訓練 |
| 重現來源快照 | [audit_event_source_availability.py](audit_event_source_availability.py) | 需要原始九表及當輪忽略路徑內的盤點、DB／官方取得證據；重算聚合，不自行啟服務或連私有API |
| 重現前輪代表性診斷 | [audit_completed_history_representativeness.py](audit_completed_history_representativeness.py) | 需要凍結快取、分數帳本、原始表與受保護來源（含僅驗SHA的模型檔）；不載入模型或新增fit |
| 驗證程式 | [tests/](../tests/README.md) | 測試命令與執行限制另列，執行測試不等於重做研究 |

可先查閱參數；以下命令只顯示說明：

```powershell
.\.venv\Scripts\python.exe scripts\verify_environment.py --help
.\.venv\Scripts\python.exe scripts\predict_delay.py --help
.\.venv\Scripts\python.exe scripts\diagnose_conditional_mature_signals.py --help
.\.venv\Scripts\python.exe scripts\audit_completed_history_representativeness.py --help
.\.venv\Scripts\python.exe scripts\audit_event_source_availability.py --help
.\.venv\Scripts\python.exe scripts\accept_frozen_daily_delivery.py --help
.\.venv\Scripts\python.exe scripts\audit_review_prediction_feasibility.py --help
.\.venv\Scripts\python.exe scripts\freeze_review_dataset.py --help
.\.venv\Scripts\python.exe scripts\audit_review_baseline_contract.py --help
.\.venv\Scripts\python.exe scripts\verify_review_pipeline.py --help
.\.venv\Scripts\python.exe scripts\run_review_baseline.py --help
```

`verify_environment.py --execute-notebooks` 只執行01–03的副本，沒有包含04。`predict_delay.py` 預設使用 `models/olist_delay_model.joblib`；有每日提醒上限的模型必須提供完整每日特徵CSV及 `--complete-daily-batches`，單張訂單不能重現每日10%名額。

`--complete-daily-batches`是呼叫端聲明，無法證明日已封閉或沒有漏單。通用CLI只支援有完整推論契約的artifact；五種子四設定的原始月版缺少必要wrapper欄位，不能直接傳`--model`當作已交付的五種子推論服務。範圍與未驗收部分見模型卡。

以下各節依階段由新到舊排列，標「最新」者為該階段最近一輪。節內的「本輪」「前輪」沿用當輪撰寫時的用語，指該節對應的研究輪次；目前狀態以[專案進度](../docs/PROJECT_PROGRESS.md)為準。

## Stage 12：V5 帳本重播與預算保存成本（最新，維持不啟動全量反讀）

觀測器量測 `budget.json` 寫入、同步至磁碟與更名的時間。重測沿用相同 48 筆，科學內容逐位元組相同。預算保存 12 次合計 0.122489 秒，其中 4 次直接發生於逐筆寫入，共 0.067355 秒。從同次樣本的逐筆計時拆出這一項後，查詢部分的情境為 5.971 小時，加兩倍餘裕為 11.941 小時。其餘階段另計，情境值不代表全量實測或上界。

166,897 筆工程帳本的完整鏈核對與來源檔尾定位 177.864 秒，全域聚合 532.128 秒，2,000 次新工程自我參照抽樣階段 332.927 秒（內含產生 49.737 秒、核對 122.101 秒）。監督窗口 1,194.094 秒，退出碼 0，522 份來源前後 SHA 相符。全量獨立排名驗收仍關閉，K1−C1 未定，預留測試鎖定。[方法與計時範圍](../docs/STAGE12_RETAILROCKET_KNN_COST_COVERAGE_DECISION_V5_20261103.md) · [5 項觀測器合成驗收](../reports/stage12/retailrocket_session_knn_v5_budget_observer_acceptance_20261103.json) · [重播實測](../reports/stage12/retailrocket_session_knn_v5_ledger_replay_cost_20261103.json) · [決策報告](../reports/stage12/retailrocket_session_knn_v5_cost_coverage_decision_20261103.json)

## Stage 12：V5 完整規模工程帳本建置（前輪）

`build_source_ledger` 讀取已存的四臂推薦，核對指標算術，將原輸出、精確指標字串與二進位差值的十六進位表示寫成工程紀錄。實測處理 166,897 筆、62,235 位訪客，分為 2,608 塊，紀錄共 2,413,599,879 bytes，其中 110 筆與已獨立驗證的參考內容相符。建置階段 350.266 秒包含在 466.281 秒監督窗口內，程序正常退出，498 份綁定來源前後雜湊一致。

本輪新增獨立 K1 排名核對 0 筆。工程帳本使用獨立的封存格式，供後續成本量測使用。全量獨立反讀關閉，K1−C1 尚無正式結論，預留測試鎖定。[方法與範圍](../docs/STAGE12_RETAILROCKET_KNN_SOURCE_LEDGER_BUILD_V5_20261103.md) · [18 項合成驗收](../reports/stage12/retailrocket_session_knn_v5_ledger_acceptance_20261103.json) · [實測報告](../reports/stage12/retailrocket_session_knn_v5_ledger_build_cost_20261103.json)

## Stage 12：V5 聯合尾端成本（前輪）

`freeze_joint_roster` 以 166,897 筆 validation 查詢的工作量結構凍結名冊。實際配對限於 12 個非空分層的 48 筆樣本。`summarize_joint_cost` 以各層母體筆數乘以該層樣本最慢的逐筆耗時，得到僅涵蓋查詢部分的情境值 17,176.067 秒（4.771 小時）。此值未乘兩倍餘裕，checkpoint 提交、準備、全域聚合與恢復另計。整個採樣與量測窗口實耗 746.391 秒，退出碼 0。

全量反讀關閉，K1−C1 尚無正式結論，預留測試維持鎖定。[方法與限制](../docs/STAGE12_RETAILROCKET_KNN_JOINT_TAIL_COST_V5_20261103.md) · [8 項合成驗收](../reports/stage12/retailrocket_session_knn_v5_joint_acceptance_20261103.json) · [聯合尾端成本實測](../reports/stage12/retailrocket_session_knn_v5_joint_cost_20261103.json)

## Stage 12：V5 完整獨立重建成本（前輪）

`run_rebuild_cost` 沿用凍結的 `reconstruct` 與 `build_index`。它從購物籃獨立重建訓練成員關係，逐檔核對商品支援數、工作階段、倒排索引、兩份訓練沿革與 `fit_audit`，再檢查並封存新資料庫。`run_window` 監督這次執行，實測前後各核對 482 份綁定檔案的 SHA。完整重建階段 248.676 秒已包含在 321.312 秒的監督窗口中；歷史 840.406 秒的計時範圍不同。

本輪獨立工程模型重建一次，主要模型新增擬合、validation 排名與 bootstrap 均為零。全量反讀關閉，K1−C1 尚無正式結論，預留測試維持鎖定。[方法與計時範圍](../docs/STAGE12_RETAILROCKET_KNN_REBUILD_COST_V5_20261103.md) · [15 項合成驗收](../reports/stage12/retailrocket_session_knn_v5_rebuild_acceptance_20261103.json) · [實測報告](../reports/stage12/retailrocket_session_knn_v5_rebuild_cost_20261103.json)

## Stage 12：V4 逐筆大小、來源索引與中斷恢復成本（前輪）

`payload_stats` 逐筆統計原始檔案的位元組數，連同換行符號計入。`build_source_index` 按 validation query 的原始順序，對齊資料集、P0 三種 CSV、C1、D1 與 K1 共七路來源，保存索引及所選原始位元組。`run_source_cost` 在六個預設位置比較索引定位與從頭掃描，逐一核對下一筆鍵值及七路原始內容，最後一點核對七路是否同步到達檔尾。每個階段分開保存起始、完成或中斷紀錄。

掃描到檔尾可核對七路來源的名冊與順序。逐筆配對與已驗證帳本的恢復限於凍結的 64 筆工程子集。全量獨立反讀仍未通過，K1−C1 尚無正式結論，預留測試維持鎖定。工具已通過 28 項合成測試，本輪實測的完成範圍與耗時以成本報告為準。[合成驗收收據](../reports/stage12/retailrocket_session_knn_v4_source_tools_acceptance_20261103.json)｜[量測說明](../docs/STAGE12_RETAILROCKET_KNN_PAYLOAD_SOURCE_RECOVERY_V4_20261103.md)｜[實測報告](../reports/stage12/retailrocket_session_knn_v4_payload_source_cost_20261103.json)

## Stage 12：V3 完整分層、固定配對與人工成本（前輪）

`run_retailrocket_session_knn_cost_v3.py --diagnose` 在新 namespace 核原 440 來源及新增模型／方法共 455 份，以封存模型唯讀完成全窗分層，先凍結 64 keys 才讀所選 target／四臂；量樣本、checkpoint 與同規模人工 global／2,000 draws／ledger 恢復，來源／收尾及各 phase 分開保存。主 DB immutable／TEMP MEMORY，外部 supervisor 維持 30 分鐘／RSS／磁碟硬停止。

首次工程窗口已正常完成、全量仍 no-go；查看既有[報告](../reports/stage12/retailrocket_session_knn_v3_cost_diagnostic_20261103.json)不需要執行命令。人工代理不覆蓋真實完整 payload／joint SQL tail／前綴尾段恢復，沒有 full／refit／test CLI；詳細界線見[分段成本文件](../docs/STAGE12_RETAILROCKET_KNN_COST_COMPONENTS_V3_20261103.md)。

## Stage 12：V2 獨立反讀與成本入口（前輪）

[run_retailrocket_session_knn_v2.py](run_retailrocket_session_knn_v2.py) 的 `--probe` 在通過且 SHA 相同的合成驗收後，建立全新 namespace，最多 30 分鐘量來源核對、獨立 SQL 重建、全窗分層與最多 64 筆 query 的工程成本。只讀既有主要產物，不重訓或產生正式 K1 比較結論；沒有全量／final／test 開關。必要成本未量到即 no-go，詳見 [V2 操作與限制](../docs/STAGE12_RETAILROCKET_KNN_READBACK_V2_20261103.md)。

獨立 [SQL 核心](retailrocket_session_knn_sql_v2.py)、[ledger 重播](retailrocket_session_knn_readback_v2.py)、[checkpoint](retailrocket_session_knn_checkpoint_v2.py) 與[分層探測](retailrocket_session_knn_cost_probe_v2.py) 各自分開。V1 partial 不續接；舊入口保持原狀。

## Stage 12：一次真實 validation 已停止（前輪）

單次入口已用，完整反讀未完成；不得重跑、續跑或刪除 partial 目錄。停止後只呼叫現有 `verify_prepared()`／`gates()` 核對來源、環境與 test locks，不執行研究。原 `--verify` 拒絕 partial 是預期行為，不能改 guard 使其通過。見[停止與保存](../docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ATTEMPT_V1.md)。

## Stage 12：K1 validation 來源與單次入口（前輪）

準備階段以 `--verify` 核對 358 份來源、15 份直接輸入與合成驗收產物，`--prepare` 完成 83 項測試與兩組獨立合成反讀。其後已用 `--run-validation` 執行唯一一次真實 validation，現有部分產物保留，原入口拒絕重播。另行啟動的只讀反讀最後觀測到至少 923 筆，實際停止時間、退出碼與原因均無紀錄。[入口文件](../docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ENTRY_V1.md)｜[停止與保存紀錄](../docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ATTEMPT_V1.md)｜[只讀反讀狀態核對](../reports/stage12/retailrocket_session_knn_v1_readback_status_audit_20261030.json)

## Stage 12：K1 實作與 train-only 準備入口（前輪）

`prepare_retailrocket_session_knn_v1.py --verify` 核實作來源、合成與成本 bytes 及原 test gates，不重算。首次 `--prepare` 依序執行合成測試、兩組獨立 oracle、兩遍真實 train-only 成本並凍結；完成重入只讀，部分輸出保留並停止。只有這兩個選項，沒有真實 validation／final／test CLI。參見[實作文件](../docs/STAGE12_RETAILROCKET_KNN_IMPLEMENTATION_V1.md)。

## Stage 12：K1 比較規格凍結（前輪）

`freeze_retailrocket_session_knn_v1.py --verify` 只核本輪來源 bytes、比較規則與六份原 gate；不執行 K1。首次凍結使用 `--freeze`，僅接受空白 namespace，完成或部分產物不可覆寫。參見[規格與操作](../docs/STAGE12_TEMPORAL_AVAILABILITY_AND_KNN_SPEC_V1.md)；本輪無模型／validation／final／test 入口。

## Stage 11：三臂證據保存

```powershell
.venv\Scripts\python.exe -B scripts\archive_retailrocket_three_arm_v1.py --verify
.venv\Scripts\python.exe -B scripts\archive_retailrocket_three_arm_v1.py --verify-archive-only
```

144 個 payload 檔＋1 份 manifest，共 145 個 ZIP 成員，649,850,977 bytes（619.746 MiB）；全部成員 CRC／SHA-256 反讀通過，另列 159 份包外依賴；44 項合成保存驗收通過。首次 `--archive` 已完成；完整重入只驗證、部分產物停下保留，不覆寫原三臂或舊包。所有來源只核 bytes／metadata，0 新 fit、排名、指標或抽樣；test locked。見[交付與還原](../docs/STAGE11_RETAILROCKET_THREE_ARM_RESEARCH_HANDOFF_V1.md)。

## Stage 11：D1 三臂真實 validation（執行輪）

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_directed_v1.py --verify
```

已完成一次真實 D1 train 擬合、166,897 validation／2,000 次主要 D1−C1 bootstrap 及獨立全反讀，D1 NDCG@10 0.099799771，D1−C1 差 -0.006600944，95% 區間 [-0.007511893, -0.005716747]。現在只用 --verify 核 source／output bytes；完整 run 重入也只驗證，部分證據則拒絕重播。原 P0／C1 不重訓、不重排；沒有 final-refit／test CLI。詳見[實際結果、限制與下一步](../docs/STAGE11_RETAILROCKET_DIRECTED_VALIDATION_V1.md)。

## Stage 11：D1 實作與真實入口（實作凍結輪）

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_directed_v1.py --verify
```

首次 `--prepare` 已完成：60 項測試、217 份來源凍結、兩組正式合成 oracle 全過，再做兩遍 train-only 成本核對與入口凍結。只解碼 train 商品，沒有真實 D1 模型／validation出分；完整準備重入只驗證，部分證據拒絕覆寫。後續真實執行已於上節完成；首次入口先寫 started，單次 fit→完整三臂→主要 bootstrap→獨立全反讀，超限／錯誤保存 failure、不重播。P0／C1 原狀，沒有 final-refit／test CLI。詳見[實作與操作](../docs/STAGE11_RETAILROCKET_DIRECTED_IMPLEMENTATION_V1.md)。

## Stage 11：D1 比較規格凍結（規格輪）

```powershell
.venv\Scripts\python.exe -B scripts\freeze_retailrocket_directed_v1.py --verify
```

首次 `--freeze` 已完成：199 份來源 SHA、228 項規格檢查、109 項規格／I/O 守門測試通過；綁定原 C1／P0／交付包固定 bytes 與包外依賴，可變 README 等脈絡快照不綁 live bytes。完整重入只驗證、部分證據拒絕覆寫；只有 --freeze／--verify，沒有模型或測試執行模式。`--verify` 不重跑測試／指標、不解析真實 CSV／JSONL；`scope_at_freeze` 是歷史規格輪範圍，不因未來合法 D1 執行目錄存在而改寫。未來入口須另經合成／成本驗收，預留測試仍鎖定。

## Stage 10：C1／P0交付保存（最新）

```powershell
.venv\Scripts\python.exe -B scripts\archive_retailrocket_c1_p0_v1.py --verify
.venv\Scripts\python.exe -B scripts\archive_retailrocket_c1_p0_v1.py --verify-archive-only
```

保存已完成：102個payload檔＋1份manifest，257,447,194 bytes（245.521 MiB）；全部CRC／SHA讀回通過，另列98份包外但仍在shop內依賴。首次空白namespace才用--archive；完整重入只驗證、部分產物拒絕覆寫，工具不解壓。只做檔案／JSON完整性，不解析逐筆標籤、不重跑研究；還原範圍與鎖定界線見[交付說明](../docs/STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md)。

## Stage 10：C1／P0真實配對與完整反讀（執行輪）

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

C1 NDCG@10 0.106400714，配對差 0.104718885；166,897 validation／2,000次bootstrap及獨立反讀完成，test locked。只核已保存來源／輸出bytes，不重算模型、指標或區間；完整namespace重入只驗證，部分證據拒絕重播。原始規格／實作文件保留各輪當時範圍，實際結果與目前操作見[完整說明](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_VALIDATION_V1.md)。

## Stage 10：C1／配對／bootstrap 實作與真實入口（實作凍結輪）

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

55 項測試、104 份來源凍結與兩組正式合成 oracle 全過，實際train-only成本及資源上限已固定；`--prepare`首次凍結已完成，完整命名空間只驗證，部分證據拒絕重播。下一輪才執行`--run-validation`，單次C1 train fit、原166,897 validation、2000次bootstrap與獨立逐筆反讀；本輪沒有真實fit或出分。操作及合作式資源停止限制見[說明](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_IMPLEMENTATION_V1.md)。

## Stage 10：共現 C1／P0 配對規格凍結（規格輪）

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

本輪82 來源 SHA、131 項一致性檢查、64 項規格測試通過並完成凍結 JSON／SHA 反讀。`--freeze` 僅首次產生收據；完整命名空間重入只驗證，部分產物拒絕覆寫。真實 CSV 只讀 bytes 做 SHA，未解析資料列或執行推薦。規格／凍結與未來真實執行命名空間分開；初始空目錄鎖檢查及歷史驗證用途見[完整說明](../docs/STAGE10_RETAILROCKET_COOCCURRENCE_PAIRED_SPEC_V1.md)。後續實作與獨立合成 oracle、train-only 成本及真實入口已另行完成，見上一節。

## Stage 9：P0一次真實開發與完整反讀（最新）

```powershell
.\.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
```

`--run-development`已成功執行一次主fit＋一次獨立SQL count audit，對166,897筆validation逐query反讀、全部CSV／聚合一致。已有完整namespace重入只verify；部分產物拒絕重播，不刪guard補證據。`--verify`不重估或重算指標，test保持locked；操作與真實結果見[本輪文件](../docs/STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md)。

## Stage 9：P0／完整候選評估實作與開發入口

```powershell
.\.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
```

已完成54項合成測試、兩個正式合成case逐格反讀與61來源／環境凍結。`--verify`不fit、不重計指標；`--run-development`已實作但本輪未執行，留待下一輪一次真實train fit及完整validation／獨立反讀。部分產物拒絕重播，沒有final-refit或test指令。詳見[手算、oracle與操作界線](../docs/STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md)。

## Stage 9：熱門baseline／完整候選執行規格

```powershell
.\.venv\Scripts\python.exe -B scripts\freeze_retailrocket_popularity_v1.py --verify
```

首次`--freeze`已核47份來源／產物、38項規格一致性及28項反例測試，保存來源與locked初始收據。完整namespace重入只驗現有來源，部分產物拒絕覆寫。`--verify`不重跑測試、不解析資料CSV、不fit／rank／計指標；該規格輪沒有真實入口；後續P0／evaluator與開發入口已另由上節完成，仍未執行真實fit或排名。下一步見[規格與實作前提](../docs/STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md)。

## Stage 8：推薦資料v1建置與獨立反讀（最新）

```powershell
.\.venv\Scripts\python.exe -B scripts\build_retailrocket_v1.py --verify
```

`--prepare`與`--run`已完成30項合成測試、來源／程式固定、一次真實建置及16CSV獨立逐格反讀。現有完整namespace重入只驗SHA；部分產物拒絕重播，不刪guard補證據。主路徑CSV／SQLite，獨立路徑直接重讀原ZIP，用pandas／numpy核對每格。詳見[結果、分母與限制](../docs/STAGE8_RETAILROCKET_BUILD_V1.md)，沒有模型或排名成績。

## Stage 8：Retailrocket來源與推薦契約

```powershell
.\.venv\Scripts\python.exe -B scripts\audit_retailrocket_source.py --verify
.\.venv\Scripts\python.exe -B scripts\freeze_retailrocket_contract.py --verify
```

首次完整CSV／SQLite掃描與pandas獨立核對已完成，兩支CLI現只核凍結來源bytes。無參數僅本輪首次建置／凍結使用，已完成的v1拒絕覆寫；不要刪guard重播。原始資料、SQLite與guard均在shop內Git忽略目錄。來源盤點入口不重建session／query；推薦builder已由上節另行完成，仍無推薦模型／排名成績。方法與實測見[來源與資料契約](../docs/STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md)。

## Stage 6：研究交付與 UCI v1 封存（最新）

[封存工具](archive_uci_rfm_v1.py)只核既有證據 bytes、打包及逐檔驗 CRC／SHA，不匯入研究 runner、不讀個體值計指標。現有版本使用：

```powershell
.\.venv\Scripts\python.exe -B scripts\archive_uci_rfm_v1.py --verify
```

僅核 ZIP／外層收據而不要求 live 檔案時，用 `--verify-archive-only`。首次空白命名空間才用 `--archive`，完整既有版本只驗證，部分檔案則停止並保留；不解壓或覆寫來源。封存範圍、導覽快照與凍結檔案角色、還原順序及同磁碟限制見[研究交付](../docs/STAGE6_RFM_RESEARCH_HANDOFF.md)。

## Stage 6：UCI v1 固定切點與跨期比較

[入口](run_uci_rfm_temporal_v1.py)、[核心](uci_rfm_temporal.py)與[獨立數值核對](uci_rfm_temporal_reference.py)已完成單次 T1 主切點及八組固定套用。現有產物使用：

```powershell
.\.venv\Scripts\python.exe -B scripts\run_uci_rfm_temporal_v1.py --verify
```

此命令只核保存 bytes，不重估切點／重算指標。首次空白命名空間才用 `--prepare`、`--run`；主估計只允許 main／T1，部分失敗保留並拒絕重播，已完成則只驗證。完整結果、獨立計算與小組限制見[跨期文件](../docs/STAGE6_UCI_RFM_TEMPORAL_V1.md)。本輪沿用 `.venv` 既有 numpy／pandas／scipy／scikit-learn，沒有安裝新套件。

## Stage 6：UCI v1 真實資料建置

[建置入口](build_uci_rfm_v1.py)、[核心](uci_rfm_builder.py)與[獨立 XML／SQL 核算](uci_rfm_reference.py)已完成八組資料建置及 32 CSV 完整反讀。現有產物使用：

```powershell
.\.venv\Scripts\python.exe -B scripts\build_uci_rfm_v1.py --verify
```

此命令核保存 bytes，不重做本輪逐格核算。首次空白命名空間才依序 `--prepare`、`--run`；`--run` 會寫所有逐筆帳並獨立核算，既有完整 guard 時只驗證，部分產物則停止並保留。真實切點／跨期分級尚未執行。來源、實測數字與下一步見[建置文件](../docs/STAGE6_UCI_RFM_BUILD_V1.md)。

## Stage 6：UCI 回溯 RFM 契約 v1

[凍結入口](freeze_uci_rfm_contract.py)核對來源 hashes／JSON 與合成契約測試，不載入真實交易列，不建立 RFM 或估真實切點。

```powershell
.\.venv\Scripts\python.exe -B scripts\freeze_uci_rfm_contract.py --verify
```

本機已完成凍結，現有產物用 `--verify`。首次完整來源已備妥且本版輸出命名空間空白時才用 `--freeze`；重複 `--freeze` 只驗既有收據。部分產物或來源改變即停止，禁止刪檔重凍結。詳細規則與未來建置驗收見[契約文件](../docs/STAGE6_UCI_RFM_CONTRACT_V1.md)。腳本中的邊界／分級純函式只用於合成契約案例，沒有真實建置入口。

## Stage 6：UCI 官方完整資料盤點

[下載](download_uci_retail_ii.py)、[完整盤點](audit_uci_retail_ii.py)與[獨立 XML 核對](verify_uci_retail_ii.py)均只在專案內輸出，原始資料與逐筆 SQLite 放 Git 忽略路徑。完整來源、實際環境及首次執行次序見[UCI 盤點文件](../docs/STAGE6_UCI_RETAIL_II_INTAKE.md)。

現有產物使用：

```powershell
.\.venv\Scripts\python.exe -B scripts\audit_uci_retail_ii.py --verify
```

此命令僅核來源、報告與資料庫雜湊，不重做逐格驗證。`--run` 需要 openpyxl；本輪用既有應用 runtime 的 3.1.5，專案 `.venv` 尚未新增此套件。下載、`--run` 及獨立核對都拒絕覆寫本輪已有產物；不可刪掉收據後重跑。候選是清理敏感度盤點，尚非正式 RFM 資料集。

## Stage 6：原 v1 G2 真實執行準備

[來源載入](rfm_rule_candidate_sources.py)、[私有輸出／反讀](rfm_rule_candidate_outputs.py)與[準備入口](prepare_rfm_rule_candidate.py)先以三套新合成測試驗證，不需要真實CSV、MySQL或模型：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_rule_candidate_sources tests.test_rfm_rule_candidate_outputs tests.test_prepare_rfm_rule_candidate -q
.\.venv\Scripts\python.exe scripts\prepare_rfm_rule_candidate.py --prepare
```

第二行需原本機來源、完整G1／G2既有證據與本輪實際source-bound測試收據；只核metadata／hash，凍結[57來源規格](../reports/stage6/rfm_rule_candidate_execution_specification.json)、[準備查核](../reports/stage6/rfm_rule_candidate_execution_preflight.json)及私有input guard，不自動重跑suite，也不呼叫真實loader、G1個體反讀、G2 core或writer。CLI沒有真實執行或路徑覆寫參數。

未來execute_prepared只允許單次G2 core，完整原來源同ID→私有四檔→公開聚合→外部guard；verify_completed不重跑G1／G2 core。這兩個callable本輪只走合成scratch，真實G2 namespace、公開結果、output guard與failure均未建立。詳見[完整契約、候選不合格與失敗停止](../docs/STAGE6_RFM_RULE_CANDIDATE_EXECUTION.md)。Stage 4、5仍待資料，每日10%與五種子不變；G3、分群、訓練與Dashboard未做。

## Stage 6：G2規則候選合成驗收

[純核心](rfm_rule_candidate.py)只接收記憶體資料，先核完整G0／獨立名冊與G1接受聲明，再產生精確分位切點、每軸箱支援及同ID重現檢查；個體分配僅留私有記憶體。可單獨執行[核心測試](../tests/test_rfm_rule_candidate.py)與[入口測試](../tests/test_verify_rfm_rule_candidate.py)，不需要真實資料：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_rule_candidate tests.test_verify_rfm_rule_candidate -q
```

正式合成驗證入口需要原本機來源與已完成G1驗收證據：

```powershell
.\.venv\Scripts\python.exe scripts\verify_rfm_rule_candidate.py --verify-synthetic
```

首次執行實跑兩套新測試與四組合成案例，前後只以binary hash／JSON metadata核既有真實來源，固定[49來源規格](../reports/stage6/rfm_rule_candidate_implementation_specification.json)、[合成驗收](../reports/stage6/rfm_rule_candidate_verification.json)及私有guard／log。再次執行只核同版來源、完整報告語義及現有收據bytes，不重跑測試或改耗時；缺檔、部分產物或來源不同即停止，不刪檔重凍結。

本輪沒有真實CSV解析、真實切點／tuple、分群、訓練或Dashboard，G3未做；Stage 4、5維持待資料，Stage 4每日10%與11／29／42／73／101五種子不變。詳見[實作、案例與下一步](../docs/STAGE6_RFM_RULE_CANDIDATE_IMPLEMENTATION.md)。

## Stage 6：真實描述與現有產物反讀

前輪已直接呼叫凍結execute_prepared一次，未修改其CLI／41來源；core1次，verify_completed禁止core時仍通過。私有四檔與public JSON已存在，禁止重播execute／prepare或刪檔重建；可用以下只讀命令核來源、全名冊與現有輸出，詳見[真實結果](../docs/STAGE6_RFM_DESCRIPTION_RESULTS.md)。

```powershell
.\.venv\Scripts\python.exe -c "from scripts.prepare_rfm_description import verify_completed; print(verify_completed())"
```

## Stage 6：真實只讀描述執行準備

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_description_sources tests.test_rfm_description_outputs tests.test_prepare_rfm_description -q
.\.venv\Scripts\python.exe scripts\prepare_rfm_description.py --prepare
```

prepare只核metadata／hash與source-bound實測receipt，凍結41來源／output schema／input guard，不呼叫原source parser、名冊衍生、core或writer。execute_prepared與verify_completed已接好，前者完整來源名冊→單core→私有四檔/public→guard，後者不重跑core；本輪只對synthetic scratch呼叫，沒有真實執行CLI。future outputs仍未建立，public檔單獨存在不代表成功；詳見[契約、失敗停止與驗收](../docs/STAGE6_RFM_DESCRIPTION_EXECUTION.md)。

## Stage 6：只讀描述與合成驗收

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_description tests.test_verify_rfm_description -q
.\.venv\Scripts\python.exe scripts\verify_rfm_description.py --verify-synthetic
```

純describe_dataset只收記憶體資料、先核資格／同ID／遮罩／守恆再回聚合，不做I/O或分群。上列CLI不跑描述器或suite，需既有原始／私有來源及本輪實測source-bound receipt；先驗27原來源＋原eval spec／audit＋4新程式／測試，共33來源，核既有metadata與receipt後封存合成verification。缺檔或不同bytes即停止，不補假成功。沒有真實描述CLI，詳見[實作／驗收／下一步](../docs/STAGE6_RFM_DESCRIPTION_IMPLEMENTATION.md)。

## Stage 6：RFM評估規格

```powershell
.\.venv\Scripts\python.exe scripts\freeze_rfm_evaluation_spec.py --specification-only
.\.venv\Scripts\python.exe scripts\freeze_rfm_evaluation_spec.py --audit
```

只有方法與版本凍結、完整27份來源、既有bundle／guard／獨立收據metadata前後對帳，CSV只讀binary hash；不呼叫原builder或個體反讀，不估分位數、切點、分數／群組或fit。私有input guard在`.runtime/stage6_rfm_evaluation_spec_v1/`；未建立未來evaluation_v1。不同來源／既有bytes即停止，不能重凍結放行。用途、研究門檻及下一步見[評估規格](../docs/STAGE6_RFM_EVALUATION_SPEC.md)。

## Stage 6：RFM builder與私有資料集

```powershell
.\.venv\Scripts\python.exe scripts\build_rfm_dataset.py --verify
```

已依20份來源規格完成一次真實建置；兩份16欄私有CSV及manifest留`.runtime/stage6_rfm_dataset_v1/`，三檔guard在`.runtime/stage6_rfm_dataset_build_v1/`。上列只讀反讀／來源／公開聚合，不建置、不寫檔；需原四CSV及私有證據，缺檔即停止。合成測試、--specification-only→--build的本輪一次歷程與停止條件見[實作驗收](../docs/STAGE6_RFM_DATASET_IMPLEMENTATION.md)；既有目錄不得刪除重播。沒有分群、訓練、Notebook或Dashboard。

## Stage 6：RFM資料集契約

```powershell
.\.venv\Scripts\python.exe scripts\freeze_rfm_dataset_spec.py --specification-only
.\.venv\Scripts\python.exe scripts\freeze_rfm_dataset_spec.py
```

需原四CSV、舊盤點規格／報告與原來源。先凍結12份來源／程式／測試綁定，再只查母體、訂單與狀態聚合；來源、政策或輸出不同即停止，不覆寫。兩份16欄CSV與manifest是未來輸出契約，本輪未建立私有資料集或builder；詳見[資料集規格](../docs/STAGE6_RFM_DATASET_SPEC.md)。

## Stage 6：RFM輸入盤點

```powershell
.\.venv\Scripts\python.exe scripts\audit_rfm_feasibility.py --specification-only
.\.venv\Scripts\python.exe scripts\audit_rfm_feasibility.py
```

先固定欄位、候選日期與8份原來源／程式／測試綁定，再驗資料前後bytes及只讀盤點。需原四CSV，來源／政策／既有輸出不同即停止，不覆寫或重建證據；不需DB，沒有個體RFM、分數、分群或模型呼叫。完整[語義、結果與限制](../docs/STAGE6_RFM_FEASIBILITY.md)保留，候選日期尚非RFM資料集契約。

## Stage 5：適用範圍與交付文件（最新）

本輪只整理[四欄／三欄模型卡](../docs/STAGE5_MODEL_APPLICABILITY.md)及既有聚合報告，沒有新增或執行CLI。原訓練命令不是交付驗收命令，已有training_v1與凍結分數不能為看結果刪檔重跑；缺原私有證據則停止，不補訓練。Stage 5維持待資料。

## Stage 5：新時間窗交接文件

本輪交付[清單與空白驗收範本](../docs/templates/review_window_handoff/README.md)，沒有新增CLI、資料驗證器或訓練入口，不需為填範本重跑來源盤點／模型。日後收到新證據才在私有交接目錄逐月驗收；JSON只是待填格式，不能把解析成功當成來源／標籤通過。

## Stage 5：後續時間窗盤點

```powershell
.\.venv\Scripts\python.exe scripts\audit_review_validation_windows.py --specification-only
.\.venv\Scripts\python.exe scripts\audit_review_validation_windows.py
```

需原H60／來源guard及Git歷史、既有收據、已存版本metadata。先凍結政策與usage_history／guard，再讀評論ID／時間戳，不讀review_score值或建新y；新窗口全待資料，不因最大回答時間延長C或啟用出分。用途凍結另外保留在[正式文件](../docs/STAGE5_REVIEW_VALIDATION_WINDOWS.md)與聚合JSON。缺證據即停止，不重建guard補缺，也不需重跑舊訓練或診斷。

## Stage 5：逐fit成熟先驗與時間漂移

```powershell
.\.venv\Scripts\python.exe scripts\audit_review_mature_prior.py --specification-only
.\.venv\Scripts\python.exe scripts\audit_review_mature_prior.py
```

需原完整H60角色、原資料及既有守門證據。先凍結政策／私有guard，再按每個fit自己的y核對全部與近期成熟先驗、互斥覆蓋、核准月／時齡及跨fit轉換。query只在歷史先驗完成後作事後描述；0模型／效能／參數更新，分數只核hash。缺檔或版本不同停止，不能用較晚標籤補回，也不需重跑舊訓練或診斷CLI。詳見[稽核文件](../docs/STAGE5_REVIEW_MATURE_PRIOR_AUDIT.md)。

## Stage 5：雙臂只讀診斷

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_review_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\diagnose_review_ablation.py
```

需原完整H60、兩臂凍結分數、manifest及收據，讀已完成版本，不呼叫訓練準備preflight。先凍結新診斷規格／私有guard，再計機率與排序差、星期／小時／等待支援及外層邊際損失。0fit／transform／predict／重新選C；缺檔或異動停止，不能補訓練。既有training_v1不重跑。結果及決策見[只讀診斷](../docs/STAGE5_REVIEW_ABLATION_DIAGNOSTICS.md)，本輪沒有新提醒排名政策或Dashboard。

## Stage 5：三欄正式入口與真實消融

本輪已依凍結入口完成一次`--train`，9次內層＋3次外層fit與完整配對通過，見[實際開發結果](../docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)。以下三個命令保留作執行前歷程；現有training_v1已占用，`--check`及前置凍結流程不能作發布後驗收，也不得刪除證據重跑。發布後改讀既有報告、manifest與獨立驗收紀錄。

```powershell
.\.venv\Scripts\python.exe scripts\run_review_month_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\run_review_month_ablation.py --verify-synthetic
.\.venv\Scripts\python.exe scripts\run_review_month_ablation.py --check
```

依序綁定入口／測試／JSON格式、跑合成驗證及只讀準備檢查。會核原本機來源與完整角色，但只在合成fixture上fit。真實訓練需明確`--train`且先通過同版成功驗證；前輪沒有執行該動作，本輪已完成一次。輸出占用、來源改版、配對不符或發布失敗均停止，詳見[正式入口驗收](../docs/STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md)。

## Stage 5：三欄消融執行準備

```powershell
.\.venv\Scripts\python.exe scripts\prepare_review_month_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\prepare_review_month_ablation.py
```

兩行均不訓練、不建立X或計效能；當時先固定[執行政策](../reports/stage5/review_month_ablation_execution_specification.json)與私有input_guard，再輸出[準備驗收](../reports/stage5/review_month_ablation_execution_preflight.json)。會讀原H60完整角色及四欄凍結分數以核對metadata、ID與合法機率，不能用缺失來源重訓補分數。原13私有來源及新guard留本機；當時預留的`.runtime/stage5_review_month_ablation_training_v1/`現已完成正式交付。

完整同ID配對validator已用合成資料驗證；該準備輪當時尚無真實三欄分數；現已另完成正式交付。該準備CLI沒有`--train`；當時dispatcher待另實作與綁定，詳見[執行準備文件](../docs/STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md)。

## Stage 5：三欄消融與合成驗證

```powershell
.\.venv\Scripts\python.exe scripts\verify_review_month_ablation_pipeline.py
```

[新模組](review_month_ablation_pipeline.py)直接建立星期、小時與核准等待，固定32維；共用原四欄的完整名冊／H60／標籤資格守門，保持獨立模型狀態。上述CLI實際fit合成scaler／Logistic並驗洩漏，核35份公開來源但不沿父規格讀原CSV、私有guard或分數；輸出[合成驗證報告](../reports/stage5/review_month_ablation_pipeline_verification.json)，詳細日誌留`.runtime/stage5_review_month_ablation_pipeline/`。

這不是三欄真實訓練入口；後續來源、完整12角色與輸出版本準備見上節，正式訓練仍待決定。原四欄程式與分數保留，舊`run_review_baseline.py`不能當三欄消融入口。詳見[實作與驗證](../docs/STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md)。

## Stage 5：四欄離線最小基線

```powershell
.\.venv\Scripts\python.exe scripts\run_review_baseline.py --specification-only
.\.venv\Scripts\python.exe scripts\run_review_baseline.py
```

第一個命令驗來源並凍結[新執行規格](../reports/stage5/review_baseline_training_specification.json)及私有input_guard；第二個在完整來源／角色守門通過後，按既定三個C及時間切分執行12次真實模型fit，產生[開發回測](../reports/stage5/review_baseline_training.json)。[來源模組](review_baseline_sources.py)接原私有收據與manifest，查詢未來標籤清空；[評估模組](review_baseline_evaluation.py)只在角色合格y上計分，未知仍完整出分。

逐筆inner／outer機率、fit診斷與manifest在`.runtime/stage5_review_baseline_training_v1/`，不隨Git交付。缺原CSV、H60 bundle、原收據或原基線guard即停止；不由CLI重建缺失證據。已有結果會在fit前拒收，不能直接重跑覆寫。三月已檢視，數字是開發回測；原入庫／版本限制仍在。詳細方法、實際結果及驗證見[離線基線文件](../docs/STAGE5_REVIEW_OFFLINE_BASELINE.md)。

## Stage 5：四欄pipeline與合成驗證

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_pipeline -q
.\.venv\Scripts\python.exe scripts\verify_review_pipeline.py
```

[實作文件](../docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md)說明builder、不可變預期名冊與受控fit／query介面。[verify_review_pipeline.py](verify_review_pipeline.py)只執行指定合成測試，綁10份公開程式／契約，輸出[驗證報告](../reports/stage5/review_pipeline_verification.json)。真實原CSV、私有標籤及模型都不讀；runtime log與耗時留.runtime/stage5_review_pipeline_verification/，報告排除時間以便同版bytes重現。

受控pipeline只fit合格訓練列，query保留未知且不讀未來標籤；低階介面與真實來源loader、內層選參／評估CLI分開。後續已由上述離線入口串接，原入庫／版本限制保留。

## Stage 5：最小基線契約

```powershell
.\.venv\Scripts\python.exe scripts\audit_review_baseline_contract.py --specification-only
.\.venv\Scripts\python.exe scripts\audit_review_baseline_contract.py
```

[基線文件](../docs/STAGE5_REVIEW_BASELINE_SPEC.md)固定四個事件時間欄、44維前處理、C=0.1／1／10的歷史內層AP選參及未知／評估政策。[規格](../reports/stage5/review_baseline_specification.json)與[稽核](../reports/stage5/review_baseline_contract_audit.json)只做契約與資料支援檢查，沒有建立四欄X、載入模型、fit、預測或算指標；不是訓練入口。

需原資料來源、已凍結H60私有bundle及原正式執行收據（均不隨Git clone交付）；缺任一資產就停止，不能補造收據或把C全域標籤join回歷史fit。新input_guard只留Git忽略的.runtime/stage5_review_baseline_v1/，原標籤／角色CSV及其manifest不改寫，私有digest不公開。兩事件時鐘仍無原入庫／版本證明，核對通過只支持條件離線研究。

## Stage 5：資料集凍結

```powershell
.\.venv\Scripts\python.exe scripts\freeze_review_dataset.py --specification-only
.\.venv\Scripts\python.exe scripts\freeze_review_dataset.py
```

詳見[凍結資料集與逐fit核對](../docs/STAGE5_REVIEW_DATASET_SPEC.md)。固定H60、C截止及三個開發fold的內外層日曆，先凍結[規格](../reports/stage5/review_dataset_specification.json)，再輸出[聚合核對](../reports/stage5/review_dataset_audit.json)。原九CSV與前輪報告須吻合SHA；各角色以自己的答案截止重建，未知y留空，C標籤不能回填歷史fit。

兩CSV及manifest只寫Git忽略的.runtime/stage5_review_dataset_v1/，共9／12個標籤與審計欄，不是21欄特徵快取。公私輸出預檢、來源前後綁定、不可覆寫與逐值反讀皆需通過。沒有MySQL、評論文字輸入、模型載入、訓練、預測、效能或Dashboard；來源變更或改H不能直接覆寫本版。

## Stage 5：可行性盤點

```powershell
.\.venv\Scripts\python.exe scripts\audit_review_prediction_feasibility.py
```

輸出為[聚合盤點](../reports/stage5/review_prediction_feasibility.json)，使用九CSV的凍結SHA，並以AST只讀原21欄候選定義；不呼叫Stage 4特徵／延遲label builder，不啟動MySQL或載入模型。首答、未知標籤與fit時鐘規則見[方法文件](../docs/STAGE5_REVIEW_PREDICTION_FEASIBILITY.md)。既有報告只接受相同bytes重現，來源不同需另接受新版本，不覆寫原報告。

## Stage 4研究入口

以下按研究脈絡索引，不是要依序重跑的安裝步驟。`train_*`、`compare_*`、`improve_*`、`ablate_*`、`tune_*` 可能訓練模型或fit校準器；`audit_*`／`diagnose_*` 各輪也有不同資料、模型重播及輸出需求，應先讀對應文件。

| 研究主題 | CLI入口 | 方法與結果 |
| --- | --- | --- |
| 原版、模型比較與誤報改善 | [train_delay_model.py](train_delay_model.py)、[compare_delay_models.py](compare_delay_models.py)、[improve_delay_alerts.py](improve_delay_alerts.py) | [原版](../docs/STAGE4_DELAY_PREDICTION.md)、[提醒策略](../docs/STAGE4_ALERT_OPTIMIZATION.md) |
| 月份誤差、等待期、多月份與滾動重訓 | [diagnose_delay_errors.py](diagnose_delay_errors.py)、[compare_waiting_strategies.py](compare_waiting_strategies.py)、[compare_multimonth_validation.py](compare_multimonth_validation.py)、[compare_monthly_retraining.py](compare_monthly_retraining.py) | [月份診斷](../docs/STAGE4_MONTHLY_DIAGNOSTICS.md)、[等待期](../docs/STAGE4_WAITING_EXPERIMENT.md)、[多月份](../docs/STAGE4_MULTIMONTH_VALIDATION.md)、[每月重訓](../docs/STAGE4_MONTHLY_RETRAINING.md) |
| 校準與每日預算 | [compare_calibration_budget.py](compare_calibration_budget.py)、[diagnose_budget_misses.py](diagnose_budget_misses.py)、[improve_budget_ranking.py](improve_budget_ranking.py) | [校準](../docs/STAGE4_CALIBRATION_BUDGET.md)、[預算排名](../docs/STAGE4_BUDGET_RANKING.md) |
| 待件負載與答案時鐘 | [improve_pending_ranking.py](improve_pending_ranking.py)、[improve_outcome_clock.py](improve_outcome_clock.py) | [待件排名](../docs/STAGE4_PENDING_RANKING.md)、[答案時鐘](../docs/STAGE4_OUTCOME_CLOCK.md) |
| 特徵、消融與Logistic正則化 | [improve_feature_engineering.py](improve_feature_engineering.py)、[ablate_delay_features.py](ablate_delay_features.py)、[tune_logistic_regularization.py](tune_logistic_regularization.py) | [特徵](../docs/STAGE4_FEATURE_ENGINEERING.md)、[消融](../docs/STAGE4_FEATURE_ABLATION.md)、[正則化](../docs/STAGE4_LOGISTIC_REGULARIZATION.md) |
| 路線、負載變化與名額交換 | [diagnose_december_misses.py](diagnose_december_misses.py)、[train_route_load_interactions.py](train_route_load_interactions.py)、[diagnose_route_load_interactions.py](diagnose_route_load_interactions.py)、[train_backlog_changes.py](train_backlog_changes.py)、[diagnose_backlog_changes.py](diagnose_backlog_changes.py)、[diagnose_backlog_route_exchanges.py](diagnose_backlog_route_exchanges.py) | [十二月](../docs/STAGE4_DECEMBER_MISS_DIAGNOSTICS.md)、[路線負載](../docs/STAGE4_ROUTE_LOAD_INTERACTIONS.md)、[堆積變化](../docs/STAGE4_BACKLOG_CHANGES.md)、[名額交換](../docs/STAGE4_BACKLOG_ROUTE_EXCHANGES.md) |
| 分類與排序目標 | [compare_backlog_objectives.py](compare_backlog_objectives.py)、[diagnose_objective_misses.py](diagnose_objective_misses.py) | [相同特徵下的目標比較](../docs/STAGE4_BACKLOG_OBJECTIVES.md) |
| 排序正則化、配對焦點、日量與配對方式 | [compare_rank_regularization.py](compare_rank_regularization.py)、[diagnose_rank_regularization.py](diagnose_rank_regularization.py)、[compare_rank_pair_focus.py](compare_rank_pair_focus.py)、[diagnose_rank_focus.py](diagnose_rank_focus.py)、[diagnose_rank_batch_size.py](diagnose_rank_batch_size.py)、[compare_rank_pair_method.py](compare_rank_pair_method.py)、[diagnose_rank_pair_method.py](diagnose_rank_pair_method.py) | [正則化](../docs/STAGE4_RANK_REGULARIZATION.md)、[焦點](../docs/STAGE4_RANK_PAIR_FOCUS.md)、[日量](../docs/STAGE4_RANK_BATCH_SIZE.md)、[配對方式](../docs/STAGE4_RANK_PAIR_METHOD.md) |
| 物流時點與交運歷史 | [audit_logistics_availability.py](audit_logistics_availability.py)、[train_handover_history.py](train_handover_history.py)、[diagnose_handover_history.py](diagnose_handover_history.py)、[diagnose_handover_sparse.py](diagnose_handover_sparse.py) | [物流可得性](../docs/STAGE4_LOGISTICS_AVAILABILITY.md)、[交運歷史](../docs/STAGE4_HANDOVER_HISTORY.md)、[稀疏交集](../docs/STAGE4_HANDOVER_SPARSE_DIAGNOSTICS.md) |
| 交運件數、共同漏報與核准訊號 | [train_handover_count.py](train_handover_count.py)、[diagnose_handover_count.py](diagnose_handover_count.py)、[diagnose_handover_common_misses.py](diagnose_handover_common_misses.py)、[audit_approval_signals.py](audit_approval_signals.py) | [件數消融](../docs/STAGE4_HANDOVER_COUNT_ABLATION.md)、[共同漏報與訊號](../docs/STAGE4_COMMON_MISSES_AND_SIGNALS.md) |
| 未觀測交運待件件數／時齡 | [train_unobserved_handover_count.py](train_unobserved_handover_count.py)、[diagnose_unobserved_handover_count.py](diagnose_unobserved_handover_count.py)、[train_unobserved_handover_age.py](train_unobserved_handover_age.py)、[diagnose_unobserved_handover_age.py](diagnose_unobserved_handover_age.py)、[diagnose_age_intersections.py](diagnose_age_intersections.py) | [件數](../docs/STAGE4_UNOBSERVED_HANDOVER_COUNT.md)、[時齡](../docs/STAGE4_UNOBSERVED_HANDOVER_AGE.md)、[交集](../docs/STAGE4_AGE_INTERSECTIONS.md) |
| 五種子與欄位取樣 | [compare_age_seed_stability.py](compare_age_seed_stability.py)、[diagnose_age_seed_stability.py](diagnose_age_seed_stability.py)、[compare_age_colsample.py](compare_age_colsample.py)、[diagnose_age_colsample.py](diagnose_age_colsample.py) | [種子穩定性](../docs/STAGE4_AGE_SEED_STABILITY.md)、[colsample](../docs/STAGE4_AGE_COLSAMPLE.md) |
| 固定四組模型的邊界、成熟訊號及條件比較 | [diagnose_four_model_boundary.py](diagnose_four_model_boundary.py)、[audit_mature_history_signals.py](audit_mature_history_signals.py)、[diagnose_conditional_mature_signals.py](diagnose_conditional_mature_signals.py) | [每日邊界](../docs/STAGE4_FOUR_MODEL_BOUNDARY.md)、[成熟訊號](../docs/STAGE4_MATURE_HISTORY_SIGNAL_AUDIT.md)、[固定條件](../docs/STAGE4_CONDITIONAL_MATURE_SIGNALS.md) |
| 完成歷史與未完成慢件代表性 | [audit_completed_history_representativeness.py](audit_completed_history_representativeness.py) | [同核准窗口、逾期待件與條件敏感度](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md) |
| 取消／結案與承諾版本來源 | [audit_event_source_availability.py](audit_event_source_availability.py) | [來源取得、時鐘涵蓋及未來驗收](../docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md) |
| 單日凍結分數交付驗收 | [accept_frozen_daily_delivery.py](accept_frozen_daily_delivery.py) | [名冊／版本、20組排名、10%名額與私有CSV反讀](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md) |
| 全量日資料契約查核 | [audit_daily_data_contract.py](audit_daily_data_contract.py) | [全量名冊、雙時間版本、日結訊號與待資料缺口](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract) |

## 共用模組與凍結來源

`delay_*.py` 主要供CLI與測試匯入：特徵模組建立核准時可得欄位，`*_training.py` 封裝各輪候選與訓練，`delay_alert_policy.py`／`delay_calibration_policy.py` 管理提醒規則，`delay_*diagnostics.py`、`delay_four_model_boundary.py`、`delay_mature_signal_profiles.py` 與 `delay_conditional_mature_signals.py` 計算診斷。`logistics_event_availability.py` 記錄物流事件可得性；`db_config_example.py` 只提供設定格式，實際 `db_config.py` 不提交。

最新研究固定每日10%、五種子11／29／42／73／101及原12個階段。事前規格、正式報告與所綁定的舊程式／模型／快取SHA形成來源鏈，不能為清整目錄而改名或搬移。較早入口可能覆寫預設產物，較新入口會拒絕不同內容；重現前依各輪文件選擇新的輸出路徑並保留原來源。

代表性稽核由`delay_history_representativeness.py`建立status-free核准窗口計數，`delay_representation_profiles.py`作固定條件比較。新欄只作稽核，不加入模型白名單；初版規格僅保留JSON格式修正紀錄，實際執行使用正式規格。

最新來源查核不需要模型或分數帳本。它綁定已取得的本機／官方證據快照，不能把重讀今天的網站或重新啟動服務當成2016–2018的新業務資料；未取得的新來源列為待資料。

單日驗收由`delay_daily_delivery_acceptance.py`核對同一名冊的20組分數與旗標，CLI另綁原始名冊及版本、驗私有CSV。完整性只對原凍結研究cohort成立，不驗證真實全核准日或原入庫完成；本機輸出只接受相同內容重現，不覆寫不同產物。

只複製Git儲存庫不足以重現全部實驗：原始CSV在 `data/raw/olist/`，特徵快取及逐筆分數在 `data/processed/`，模型在 `models/`，執行證明在 `.runtime/`，皆保留本機並由Git忽略。公開提交以程式、規格、聚合JSON及文件為主，不提交原始資料、逐筆分數、憑證或本機模型。
