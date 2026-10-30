# 電商智慧推薦系統

Smart E-Commerce Recommendation System

以 Olist 電商資料練習資料建置、SQL、商業分析、延遲／評論預測與 RFM 顧客分析，再延伸至 Retailrocket 推薦系統、API 與前端。資料環境、SQL 與 EDA 初版已完成；延遲預測與評論低評分預測已整理成離線研究交付，正式適用仍待新資料；RFM 的 Olist v2／G2／G3 與 UCI v1 跨期描述已整理為離線研究交付，UCI v1 結果已封存；小組支援與營運限制保留。Retailrocket v1資料建置與P0一次真實train擬合、完整validation及獨立反讀已完成；共現 C1 已完成一次 train 擬合、完整 validation 與 P0 配對、2000次bootstrap及獨立反讀，C1／P0研究交付與證據保存亦完成；Stage 11 已完成一次真實 D1 train 擬合、完整三臂 validation／2,000 次主要 bootstrap 與獨立逐筆驗收，三臂研究交付、適用說明與證據保存亦完成；validation 已曝光、預留回溯測試仍 locked，API與前端尚未開始。

## 目前進度

| 階段 | 狀態 | 現有成果 |
| --- | --- | --- |
| Stage 1：資料與環境 | 完成 | Olist 九份 CSV、MySQL、Jupyter 與本機啟動工具 |
| Stage 2：SQL | 完成 | 訂單、品類營收、平均客單價與多表查詢 |
| Stage 3：商業 EDA | 初版完成 | 八張趨勢、品類、付款、評論、配送與地區圖表 |
| Stage 4：延遲預測 | 離線研究交付；待資料 | 每日10%提醒、四設定×五種子對照、模型卡與單日交付驗收；全量名冊、入庫／版本與日結證據待資料 |
| Stage 5：評論低評分預測 | 離線研究交付；待資料 | 四欄基線與三欄消融的開發回測、模型卡；2018年5–9月新驗證窗待資料 |
| Stage 6：RFM | 離線研究交付完成；UCI v1 已封存 | Olist G2／G3、UCI 固定切點跨期與完整驗收；UCI 主口徑 87／83 個聯合小組不足、原 Olist 25 個小組限制保留；營運適用待資料 |
| Stage 7：Dashboard | 暫緩 | 先確認延遲模型適用程度 |
| Stage 8：推薦資料 | v1建置及獨立驗收完成 | 訓練／驗證／預留回溯測試query 642,619／166,897／92,086；16 CSV完整逐格通過 |
| Stage 9：熱門baseline與評估 | P0一次真實開發與完整反讀完成 | validation 166,897 query；NDCG@10 0.001681829、HitRate 0.418222%；預留測試locked |
| Stage 10：共現推薦 | 離線研究交付與證據保存完成 | 完整配對／bootstrap／獨立反讀；C1 NDCG 0.106400714；冷商品、小組及回溯限制保留，P0原狀、test locked |
| Stage 11：有向相鄰關聯 D1 | 三臂研究交付與證據保存完成 | D1 NDCG@10 0.099799771，D1−C1 差 -0.006600944，95% 區間 [-0.007511893, -0.005716747]；P0／C1 原狀、test locked，冷商品／小組／回溯限制保留 |
| Stage 12：session-kNN K1 | 停止核對與成本／恢復規劃完成；暫不另開真實驗收 | 既有前段 919 筆／6,567.71 秒；同速率全量 query 情境約 331 小時，非實測總工時。先規劃獨立 V2 精確加速與分塊保存；K1−C1 未驗收，test locked |
| Stage 13：其他推薦研究 | 尚未開始 | 依後續問題另立規格 |
| Stage 14–15：API、前端 | 尚未開始 | FastAPI、JavaScript／AJAX 串接 |

目前已整理 Stage 6–12 的程式、凍結規格、測試與聚合報告。Stage 12 的唯一一次真實 K1 執行已依時限停止，後續另授權的獨立反讀亦已不在執行，仍無完整獨立驗收或正式比較結論；原始資料、本機模型及逐筆執行證據留在 Git 忽略路徑，不隨 repository 提交。

各輪做了什麼、實際結果與限制見[專案進度](docs/PROJECT_PROGRESS.md)；方法文件依階段整理在[文件導覽](docs/README.md)。

## Stage 12：成本與中斷保存規劃完成，暫不另開真實驗收

2026-10-30 解析既有日誌：從 4 筆到 923 筆的觀測差為 919 筆／6,567.713332 秒，平均每筆 7.146587 秒。若原 166,897 個 query 全程維持同速率，逐 query 階段約需 **331.32 小時（13.80 日）**；這是已觀測前段的條件外推，並非完整實測、工時保證或可續跑剩餘時間，且不含全域統計、bootstrap 與收尾。

目前決定不重啟 V1、不另開真實全量驗收。下一步建議另立 V2 獨立驗收方法：以原始資料的獨立 SQL 關聯證明精確鄰居／候選覆蓋，並保存完整核對後的 query chunks；通過合成差分與故障恢復，再做另行有界成本探測，最後決定是否全量驗收。單加 checkpoint 無法解決總耗時；現有 923 計數也不能續接。候選六小時總窗口及每 64 筆／120 秒保存設定均待驗證與後續執行規格，不是新授權。

本輪沒有新版實作、合成驗收、真實成本探測或模型計算。見[成本與恢復設計、決策門檻](docs/STAGE12_RETAILROCKET_KNN_READBACK_COST_AND_RECOVERY_PLAN_20261030.md)及[日誌成本分析報告](reports/stage12/retailrocket_session_knn_readback_cost_plan_20261030.json)。K1−C1 仍無正式結論，預留測試維持 locked。

## Stage 12：V1 獨立反讀已不在執行，未取得完整驗收（前輪核對）

2026-10-30 事後核對確認，10 月 29 日另授權的反讀已不在執行，沒有完整驗收收據。最後進度觀測為臺北時間 **2026-10-29 17:05:57，已走完當次逐 query 核對 923 筆**；這只是已觀測下界，不是全域驗收筆數、整體完成百分比或可續跑 checkpoint。

原定截止為同日 **17:20:00**，但現存紀錄缺少成功、例外、期限停止及 supervisor completion 收據，不能寫成已於 17:20 正常依期限停止。Windows System 紀錄顯示 17:07 左右發生關機／重新啟動；這是同時段系統證據，仍不能確定 worker 的實際停止時刻、退出碼或直接原因。

這次反讀於 10 月 29 日 15:12:05 啟動，沿用原 166,897 query／2,000 bootstrap，新增主要訓練／validation／bootstrap 產生為 0。今日核對 358 份凍結來源、61 份準備產物、原九份部分產物、七份複本與前輪 15 份停止證據的 SHA 均一致，六份 gate 仍 locked；這是檔案身分核對，不是 K1 效能驗收。本次不補造歷史收尾收據、不重啟 oracle，也不將原 partial namespace 改為成功。K1−C1 尚無完整驗收結論；最終選模／重擬合／預留測試未啟動。

來源、保存核對與紀錄缺口見[獨立反讀說明](docs/STAGE12_RETAILROCKET_KNN_READBACK_ONLY_20261029.md)及[2026-10-30 事後核對報告](reports/stage12/retailrocket_session_knn_v1_readback_status_audit_20261030.json)。

## Stage 12：一次真實 K1 validation（前輪已依時限停止）

2026-10-29 唯一一次凍結入口已於臺北時間 14:34:09，依使用者追加的整輪 **3 小時 30 分鐘（含已用時間）** 上限停止。主要 train 索引、166,897 筆 validation 與 2,000 次 bootstrap 已產出；完整獨立反讀未完成，沒有驗收通過的 K1−C1 結論。1 次執行、0 次重跑，凍結程式及比較規格未改。

停止後 358 份來源、61 份準備驗收產物與 locked gates 核對通過；部分產物、停止紀錄與 SHA 清單保存在 Git 忽略路徑。實際 worker 抽查 RSS 峰值 1.730659 GiB，執行目錄 2.718260 GiB；停止原因是使用者的較短時間限制。沒有完整驗收收據，不能把主要輸出當成正式成績。見[本輪停止與限制](docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ATTEMPT_V1.md)及[實際保存報告](reports/stage12/retailrocket_session_knn_v1_validation_attempt.json)。

本版 namespace 已是 partial，禁止重跑；原 `--verify` 也會拒絕部分結果。後續成本檢視或新版須另行規劃；最終選模／重擬合／預留測試均未啟動，test locked。

## Stage 12：K1 validation 入口凍結（前輪）

來源 loader、完整獨立反讀與單次執行入口已完成。83 項相關測試、兩組正式檔案合成案例完整 oracle 通過；358 份來源凍結、15 份直接輸入綁定；0 真實 K1 fit／validation，test locked。原 P0／C1／D1 的逐 query 值照原值核對及複製，K1 仍固定完整搜尋、精確 Jaccard 與 500 鄰居。

準備階段禁止以文字模式開啟真實資料／對照 CSV、JSONL；本輪只以 bytes／SHA 綁定它們，沒有重跑 train 成本或建立真實 K1 模型。合成案例走同一入口，完整核 current／next basket、所有 sessions／候選／巢狀輸出與各 2,000 次 bootstrap；缺列、來源或輸出竄改、錯誤／超限與中斷都會停止並保留證據，完整重入只驗 bytes。

該準備輪操作：`.venv\Scripts\python.exe -B scripts\run_retailrocket_session_knn_v1.py --verify`。當時尚未執行真實 validation，合成驗收也不保證完整 oracle 在 6 小時內完成。本版如今已單次執行後停止，現況以上節為準，原 `--verify` 會拒絕 partial。最終選模／重擬合／預留測試仍另行規劃，每日 10% 提醒與 Dashboard 暫緩不變。

見[入口與操作](docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ENTRY_V1.md)、[正式驗收](reports/stage12/retailrocket_session_knn_v1_validation_entry_acceptance.json)及[來源／環境凍結](reports/stage12/retailrocket_session_knn_v1_validation_entry_specification.json)。

## Stage 12：K1 實作與 train-only 成本（前輪）

已依凍結的 Jaccard／500 鄰居／完整搜尋實作 K1；49 項測試通過，兩組正式合成案例完成獨立 SQL 重建、全鄰居／全候選／巢狀值反讀，各核對 2,000 次 bootstrap。這是合成驗收，沒有真實推薦效能。

兩遍 train-only 成本核對 1,823,018 baskets、1,180,256 sessions、1,587,436 個不同 session-item；最大 session 有 389 商品，最大 posting 有 1,736 sessions。逐 session 對帳 1,180,256 列／7,081,536 格，並保留完整商品集合 SHA。實測成本 138.547 秒；完整準備期抽查 RSS 峰值 0.045383 GiB，未超限。

這些數字不保證完整真實 query 搜尋與 oracle 的耗時；本輪沒有建立真實 K1 索引，也沒有讀取 validation／test 商品陣列或跑真實排名。操作：`.venv\Scripts\python.exe -B scripts\prepare_retailrocket_session_knn_v1.py --verify`。

見[實作與手算](docs/STAGE12_RETAILROCKET_KNN_IMPLEMENTATION_V1.md)、[正式驗收](reports/stage12/retailrocket_session_knn_v1_implementation_acceptance.json)與[來源凍結](reports/stage12/retailrocket_session_knn_v1_implementation_specification.json)。該輪提出的真實 validation 入口後續已驗收凍結，並完成唯一一次執行嘗試；因時間上限停止、完整反讀未完成，詳見頁首。最終選模／重擬合／預留測試仍另行規劃，延遲每日 10% 與 Dashboard 暫緩不變。

## Stage 12：前輪資料盤點與規格

已選定 K1 session-kNN，固定 Jaccard、500 個鄰居及完整搜尋；唯一主要問題是同一已曝光 validation 上 K1−C1 的 NDCG@10 差異。Retailrocket 官方當前 metadata 未確認新時間延伸；REES46 多品類七個官方 gzip 的 HEAD 皆 200，但尚未下載驗收，且屬不同商店。新增驗收時間來源為 0，因此維持既有 train／validation 角色。

前一輪完成[時間盤點與比較規格](docs/STAGE12_TEMPORAL_AVAILABILITY_AND_KNN_SPEC_V1.md)、[機器契約](docs/contracts/retailrocket_session_knn_paired_v1.json)及[凍結收據](reports/stage12/retailrocket_session_knn_v1_specification.json)；315 份來源 SHA、64 項規格檢查及 12 項 metadata／守門測試通過，不是 K1 模型驗收。0 新 fit／排名／指標／bootstrap；最終選模、重擬合與預留測試另行規劃。該輪提出的實作、合成 oracle 與 train-only 成本已於上節完成。

只讀核對：`.venv\Scripts\python.exe -B scripts\freeze_retailrocket_session_knn_v1.py --verify`。原 P0／C1／D1 證據及 test gates 保留；延遲每日 10% 與 Dashboard 暫緩不變。

## 快速開始

以下指令在專案根目錄的 PowerShell 執行。完整版本、資料庫初始化及跨電腦重建方式見[本機環境指南](docs/LOCAL_SETUP.md)。

首次在新電腦使用時，建立 Python 3.12 環境並安裝鎖定套件：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

將 Olist 九份 CSV 放入 `data/raw/olist/`，檔名與用途見[資料說明](data/README.md)。SQL 與前三本 Notebook 需要 MySQL；Stage 4–6 的研究程式直接讀 CSV。模型、特徵快取、逐筆分數與私有驗收證據只保留在本機，下載此 repository 不會同時取得它們。

| 想做什麼 | 入口 |
| --- | --- |
| 建立、啟停 MySQL 或啟動 Jupyter | [本機環境指南](docs/LOCAL_SETUP.md) |
| 按步驟閱讀分析 | [Notebook 導覽](notebooks/README.md) |
| 查詢資料庫 | [SQL 導覽](sql/README.md) |
| 看商業分析圖表 | [Stage 3 成果](docs/STAGE3_BUSINESS_ANALYSIS.md) |
| 延遲模型的方法、推論與適用範圍 | [延遲模型方法與推論](docs/STAGE4_DELAY_PREDICTION.md)、[模型卡與交付清單](docs/STAGE4_MODEL_APPLICABILITY.md) |
| 延遲模型的資料缺口與交接 | [全量日資料契約](docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract)、[交接清單](docs/templates/daily_data_handoff/README.md)、[驗收範本](docs/templates/daily_data_handoff/acceptance_record.template.md) |
| 評論預測的結果與適用範圍 | [四欄／三欄模型卡](docs/STAGE5_MODEL_APPLICABILITY.md)、[三欄消融結果](docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md) |
| 評論預測的新時間窗交接 | [交接清單](docs/templates/review_window_handoff/README.md)、[驗收紀錄](docs/templates/review_window_handoff/acceptance_record.template.md) |
| RFM 的真實描述結果 | [分流、RFM摘要與限制](docs/STAGE6_RFM_DESCRIPTION_RESULTS.md) |
| RFM 最新的五種子 G3 | [完整結果、限制與操作](docs/STAGE6_RFM_G3_V2.md)；[v2 重建與 G2](docs/STAGE6_RFM_REBUILD_V2.md) |
| RFM 第二快照與跨期資料 | [現有資料盤點](docs/STAGE6_RFM_TEMPORAL_DATA_INVENTORY.md)、[缺件與交接清單](docs/templates/rfm_temporal_handoff/README.md)、[驗收紀錄範本](docs/templates/rfm_temporal_handoff/acceptance_record.template.md) |
| RFM 後期公開來源與替代方案 | [Olist 搜尋、候選比較與下一步](docs/STAGE6_RFM_PUBLIC_SOURCE_SEARCH.md)、[實際查核紀錄](reports/stage6/rfm_public_source_search.json) |
| UCI 完整官方資料與跨期可行性 | [品質、時間覆蓋、限制與下一步](docs/STAGE6_UCI_RETAIL_II_INTAKE.md)、[實測聚合](reports/stage6/uci_retail_ii_intake.json) |
| UCI 已凍結的回溯 RFM 契約 | [規則、窗口與評估](docs/STAGE6_UCI_RFM_CONTRACT_V1.md)、[機器契約](docs/contracts/uci_rfm_v1.json)、[實際凍結驗收](reports/stage6/uci_rfm_v1_contract_acceptance.json) |
| UCI 最新真實建置與驗收 | [雙期名冊、金額、排除帳與下一步](docs/STAGE6_UCI_RFM_BUILD_V1.md)、[實際聚合](reports/stage6/uci_rfm_build_v1.json)、[獨立驗收](reports/stage6/uci_rfm_build_v1_acceptance.json) |
| UCI 最新跨期比較與小組支援 | [切點、跨期、敏感度與限制](docs/STAGE6_UCI_RFM_TEMPORAL_V1.md)、[正式聚合](reports/stage6/uci_rfm_temporal_v1.json)、[獨立驗收](reports/stage6/uci_rfm_temporal_v1_acceptance.json) |
| Stage 6 最新研究交付與封存 | [交付、適用說明與還原](docs/STAGE6_RFM_RESEARCH_HANDOFF.md)、[封存收據](reports/stage6/uci_rfm_v1_research_release.json) |
| Retailrocket 最新來源與推薦資料契約 | [下載、鍵、時間、授權與規則](docs/STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md)、[機器契約](docs/contracts/retailrocket_recommendation_v1.json)、[核對／凍結收據](reports/stage8/retailrocket_contract_v1_acceptance.json) |
| Retailrocket最新資料建置與驗收 | [結果、分母、限制與操作](docs/STAGE8_RETAILROCKET_BUILD_V1.md)、[實際聚合](reports/stage8/retailrocket_build_v1.json)、[完整逐格驗收](reports/stage8/retailrocket_build_v1_acceptance.json) |
| Retailrocket熱門baseline與評估執行規格 | [訓練／回退／分母／測試閘門](docs/STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md)、[機器規格](docs/contracts/retailrocket_popularity_execution_v1.json)、[凍結驗收](reports/stage9/retailrocket_popularity_v1_spec_acceptance.json) |
| Retailrocket最新P0實作與開發入口 | [手算、oracle、鎖定與操作](docs/STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md)、[合成驗收](reports/stage9/retailrocket_popularity_v1_implementation_acceptance.json)、[開發入口規格](reports/stage9/retailrocket_popularity_v1_development_specification.json) |
| Retailrocket最新P0真實開發結果 | [成績、完整分母與限制](docs/STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md)、[正式報告](reports/stage9/retailrocket_popularity_v1_development.json)、[逐query驗收](reports/stage9/retailrocket_popularity_v1_development_acceptance.json) |
| Retailrocket 共現與 P0 配對規格 | [計數／歷史／回退／配對及限制](docs/STAGE10_RETAILROCKET_COOCCURRENCE_PAIRED_SPEC_V1.md)、[機器契約](docs/contracts/retailrocket_cooccurrence_paired_v1.json)、[凍結驗收](reports/stage10/retailrocket_cooccurrence_v1_spec_acceptance.json) |
| Retailrocket 共現實作與真實入口 | [合成驗收／成本／資源／操作](docs/STAGE10_RETAILROCKET_COOCCURRENCE_IMPLEMENTATION_V1.md)、[實作驗收](reports/stage10/retailrocket_cooccurrence_v1_implementation_acceptance.json)、[凍結入口](reports/stage10/retailrocket_cooccurrence_v1_validation_specification.json) |
| Retailrocket C1真實配對結果 | [結果／區間／限制](docs/STAGE10_RETAILROCKET_COOCCURRENCE_VALIDATION_V1.md)、[正式報告](reports/stage10/retailrocket_cooccurrence_v1_validation.json)、[獨立驗收](reports/stage10/retailrocket_cooccurrence_v1_validation_acceptance.json) |
| 三臂最新研究交付與保存 | [適用／限制／還原](docs/STAGE11_RETAILROCKET_THREE_ARM_RESEARCH_HANDOFF_V1.md)、[保存收據](reports/stage11/retailrocket_three_arm_v1_research_release.json) |
| C1／P0研究交付與保存 | [適用／限制／操作](docs/STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md)、[保存收據](reports/stage10/retailrocket_c1_p0_v1_research_release.json) |
| 找特定研究的執行方式 | [腳本導覽](scripts/README.md)、[文件導覽](docs/README.md) |
| 查正式數字、規格與圖表 | [報告導覽](reports/README.md) |
| 執行測試 | [測試說明](tests/README.md) |

已備妥本機環境後，可啟動分析介面：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_jupyter.ps1
```

此腳本會先啟動專案 MySQL。請使用 `Shop (Python 3.12)` kernel；各 Notebook 的資料前提與是否會觸發訓練，先看其[操作說明](notebooks/README.md)。

## 本機環境重建與中文路徑修正

2026-10-27 已在含中文的專案路徑完成環境重建，並實際驗證資料庫與四本 Notebook。這次是本機安裝與相容性修正，研究進度及既有模型成績維持原狀。

| 項目 | 本輪實測結果 |
| --- | --- |
| Python 與套件 | Python 3.12.10；`.venv/` 內 116 個套件與 `requirements-lock.txt` 全部吻合，相依性檢查通過 |
| Olist 與 MySQL | 官方 Kaggle 第 2 版九份 CSV 匯入 MySQL 8.4.11，九張表共 1,550,922 筆，逐表筆數核對一致 |
| Notebook | `01`–`04` 共 59 個程式區塊完整執行，0 錯誤；執行副本另產生 8 張 EDA 圖表 |
| MySQL 啟停 | 僅監聽 `127.0.0.1:3307`；停止、重啟、重複啟動及重啟後資料筆數檢查通過，未註冊 Windows 系統服務 |
| JupyterLab | 正常啟動腳本、HTTP API、四本 Notebook 根目錄、專案 `.venv` kernel 建立與 Lab 頁面均通過 |

MySQL 8.4.11 在本機中文路徑初始化與啟動時發生編碼錯誤，已用指向專案 `.runtime/` 的 ASCII 目錄 junction 處理。新增共用路徑解析，讓啟停腳本沿用 `my.ini` 中的路徑；初始化另支援 `--runtime-root`，只接受實際指向本專案 `.runtime/` 的既有路徑，並保留既有資料與連線設定的防覆寫檢查。操作步驟及搬移注意事項見[本機環境指南](docs/LOCAL_SETUP.md)。

`04` 所需模型未隨 repository 提供，本輪僅使用原訓練集 54,145 筆重建教學模型，來源 SHA-256 與時間切分已核對。此模型不是原凍結研究 artifact；沒有重新預測或評估驗證集／保留測試集，Notebook 展示的歷史成績仍讀取既有報告。

完整本機驗收保存在 `.runtime/verification/full-setup.json`，另有資料來源、MySQL 重啟、Jupyter 與 Notebook 執行紀錄。這些驗證檔、Notebook 執行副本、帳密、原始 CSV、資料庫、模型及下載檔都留在 Git 忽略路徑；本次提交僅包含文件與 MySQL 路徑相容性程式，不包含本機資料或研究產物。其他電腦仍需依建置指南下載資料與安裝工具，`git clone` 不會取得這些本機檔案。

本輪盤點期間，使用者將執行資料搬至專案內 `shop-mysql-runtime/`，並確認保留新位置。現以 `.runtime` 目錄連結（junction）指向該目錄，沿用原研究指令與凍結路徑；兩個路徑均已加入 Git 忽略。資料與備份實際仍在新位置，沒有複製成第二份研究來源。

## 研究目前的結果

以下數字都來自專案內實際執行的正式報告。三個研究反覆使用的 2017-12、2018-02、2018-04 是**已檢視的開發回測月份**，不能當成未知資料成績。

### Stage 4：延遲預測

在訂單核准時，從完整核准日批次選出最多 `floor(N × 10%)` 張提醒。未知答案先競爭名額、再計已知答案成績；每天各自取整，不借其他日名額。

| 歷史選模主方案指標（不是五種子平均） | 已檢視的三個開發月 |
| --- | ---: |
| 有效訂單／延遲 | 18,833／1,642 |
| 提醒名額 | 1,845 |
| 抓到延遲 TP／誤報 FP／漏報 FN | 413／1,432／1,229 |
| 開發召回 | 25.15% |
| 提醒精確率 | 22.38% |
| 最差歷史驗證召回 | 19.63% |

來源為[排序配對焦點報告](reports/stage4/rank_pair_focus.json)及後續凍結主方案，三月依歷史規則選到不同候選。三個 fold 都未全面通過「各歷史月至少召回 30%」的原要求。預設推論仍是原版 Random Forest，研究成績不會自動替換它。

四個固定設定另保留 11／29／42／73／101 五種子，下表是同三個開發月的種子平均與實際範圍，不是信賴區間或 ensemble：

| 固定設定 | TP平均［範圍］ | 召回平均［範圍］ |
| --- | ---: | ---: |
| 原101 × colsample0.8 | 330.6［320，339］ | 20.13［19.49，20.65］% |
| 時齡102 × 0.8 | 336.2［326，350］ | 20.48［19.85，21.32］% |
| 原101 × 1.0 | 325.2［322，331］ | 19.81［19.61，20.16］% |
| 時齡102 × 1.0 | 325.6［315，336］ | 19.83［19.18，20.46］% |

可交付的是**離線研究證據與操作文件**，不是已驗證的逐筆即時提醒。[單日離線交付驗收](docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md)只證明凍結研究 cohort 的既有行為；全量核准名冊、原入庫／版本時鐘與日結證據都缺，[取消／結案與承諾版本](docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md)也待資料。下一步是依交接清單取得同ID核准清冊與版本證據；沒有新資料就維持 0 訓練、0 新效能結論，正式通知與 Dashboard 暫緩。

### Stage 5：評論低評分預測

在核准時預測「本單最早記錄的評論回答若落在核准後 60 天內，是否為 1–2 分」。未回覆、超窗、品質隔離或觀察未滿一律保持未知，不補成負例。

| 已檢視外層開發月 | 查詢／合格／未知 | 常數 AP | 四欄 AP（選定C） | 三欄 AP（選定C） | 三欄−四欄 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2017-12 | 5,832／5,740／92 | 0.162892 | 0.177118（0.1） | 0.176565（10） | -0.000553 |
| 2018-02 | 6,706／6,611／95 | 0.205869 | 0.202077（0.1） | 0.201416（0.1） | -0.000661 |
| 2018-04 | 6,778／6,704／74 | 0.129773 | 0.133589（0.1） | 0.133501（0.1） | -0.000088 |
| 三月等權 macro | 19,316／19,055／261 | 0.166178 | 0.170928 | 0.170494 | -0.000434 |

四欄（購買月／星期／時＋核准等待小時）對常數的改善不一致，2月甚至較差；移除購買月份的三欄消融三個月都略降，不支持替換。後續只讀診斷、成熟先驗稽核與時間窗盤點都沒有新訓練。來源見[四欄報告](reports/stage5/review_baseline_training.json)與[三欄報告](reports/stage5/review_month_ablation_training.json)，限制與交付見[模型卡](docs/STAGE5_MODEL_APPLICABILITY.md)。

較晚的2018年5–9月共 26,027 張原匯出核准單只預留作驗收後的時間驗證，但缺 60 天觀察完成、入庫／評分版本與新標籤證據，目前可啟用的新驗證窗為 0。下一步依[交接清單](docs/templates/review_window_handoff/README.md)取得新證據，不再對同三個開發月挑改動。

### Stage 6：RFM顧客分析

快照固定 S=2017-09-01、T=2018-09-01，R 為最近合格購買距 T 的天數（不取整），F 為窗口內合格訂單數，M 為商品毛額（不是淨營收）。方法分四道關卡：G0 版本與資格、G1 只讀描述、G2 規則切點候選、G3 方法敏感度。

| 已完成的真實結果 | 實際數字 |
| --- | --- |
| 私有資料集 | 93,234 位顧客、99,421 筆 T 前訂單；窗口合格 74,088 單 |
| 顧客分流 | 完整活躍 72,124 位進入數值描述；乾淨零活動 21,109 位、隔離 1 位另列 |
| G1 描述 | F=1 占 97.516777%（F 的 IQR=0）；R 中位 173.51 天、M 中位 BRL 89.80；M≥Q99 共 723 人，占商品毛額 11.312277% |
| 反讀驗收 | 私有四檔 776,807 格名冊與 244 個公開聚合值比對一致 |

來源為[完整聚合](reports/stage6/rfm_description.json)與[交付驗收](reports/stage6/rfm_description_acceptance.json)，解讀見[真實描述結果](docs/STAGE6_RFM_DESCRIPTION_RESULTS.md)。F 幾乎全是 1，不能預設五等份分群。

2026-10-27 搜尋本機未找到原私有研究檔，已使用相同四份 CSV 與凍結方法另建 **v2**，沒有補造舊版收據。新資料集 3,082,480 格完整來源核對通過，G1 與歷史聚合相符；161 項合成／回歸測試全過。真實 G2 已執行一次並完整反讀，各軸至少 361 人：

| 真實 G2 結果 | 數字與限制 |
| --- | --- |
| R／F／M 有效級數 | 5／2／5，各軸資格通過，完整同 ID 列序重現 100% |
| F 兩級人數 | 1 次購買 70,333 人；至少 2 次 1,791 人，不能當成五等份 |
| 中性組合 | 共 50 組，其中 25 組少於 361 人；這些小組全屬回購顧客，不能宣稱穩定 |
| G3 同快照敏感度 | 五種子 11／29／42／73／101 全部通過，級數維持 5／2／5；25 個小組的支援限制保留 |
| 研究範圍 | 沒有新時間資料、營運成效、模型訓練或 Dashboard |

最新 [G3 正式結果](reports/stage6/rfm_g3_v2.json)對 72,124 位完整活躍顧客，每個種子抽 57,699 位估切點，再套回完整名冊。26 項新增合成測試通過，360,620 列分配／3,245,580 格欄位及 1,922 個聚合 scalar 完整反讀。五次最差值如下，不能當成新時間或營運效果：

| 五種子最差指標 | 結果 | 原門檻 |
| --- | ---: | ---: |
| R 序數一致率 | 99.6631% | ≥90% |
| F 序數一致率 | 100% | ≥90% |
| M 序數一致率 | 99.8267% | ≥90% |
| 三軸組合 ARI | 0.990675 | ≥0.80 |

每次仍有 25 個小組支援不足，涉及 1,791 位回購顧客，最小組只有 1 人；整體 G3 通過不代表這些小組可供行銷。五種子逐次結果、備份與操作見 [G3 文件](docs/STAGE6_RFM_G3_V2.md)，原重建／G2 見 [v2 文件](docs/STAGE6_RFM_REBUILD_V2.md)。下一步取得第二個時間快照及完整名冊、版本、觀察與金額對帳證據，再驗跨期或特定業務用途；不在同一快照繼續挑種子或改切點。現有完成 G3 只執行只讀驗證：

```powershell
.\.venv\Scripts\python.exe scripts\run_rfm_g3.py --verify
```

### RFM 第二快照：現有資料不足，已列交接缺件

2026-10-27 盤點原始資料、下載包、v2／G3 備份與預留交接目錄，九張原表每張都只有同一內容版本；備份不算新時間快照。購買最大日期雖到 2018-10-17，原 T=2018-09-01 之後只有 20 筆購買（19 取消、1 出貨中），依原資格沒有合格新增購買；不能把尾端缺資料解讀成沒有回購。

| 本輪工作 | 狀態與實際結果 |
| --- | --- |
| 原始來源與備份 | 26 個原表副本逐一 hash 核對，每張表僅 1 版；已驗收的第二個 as-of 快照為 0 |
| 後期覆蓋 | 9 月購買 16 筆、10 月 4 筆；同期 59 筆送達都是 9 月前購買的舊單 |
| 完整性與版本 | 全量母體、入庫／修訂、顧客跨版映射、完成水位及金額對帳待資料；事件最大日不是完整性證明 |
| 驗證與範圍 | 15 項合成測試通過，真實聚合另用 pandas 核對；0 新 RFM、0 切點、0 訓練／保留測試評估 |

完整數字見[資料盤點報告](reports/stage6/rfm_temporal_data_inventory.json)與[解讀](docs/STAGE6_RFM_TEMPORAL_DATA_INVENTORY.md)。下一步按[交接清單](docs/templates/rfm_temporal_handoff/README.md)取得後期四表、來源版本與完整性證據，先驗收，再固定 S2／T2 及跨期設計。10/1、11/1 只是本輪覆蓋查詢日期；目前不建第二快照。原 25 個小組支援不足仍保留；同快照 G3 門檻不直接當跨期門檻，淨營收／LTV／營運效果另需退款、成本或成熟結果與處置對照。

```powershell
.\.venv\Scripts\python.exe scripts\audit_rfm_temporal_data.py --verify
```

### 第 13 輪公開來源查核紀錄

2026-10-27 查核 Olist 發布者資料、官方 API 與公開候選來源，**未找到能延續原匿名顧客、符合交接清單的後期公開匯出**。Marketing Funnel 是賣家招募資料；需授權的 API 也不等於公開後期資料。部分 Kaggle／API 頁面直接存取失敗，已記錄限制；此結論不是宣稱所有後期資料都不存在。下表為當輪尚未完整下載的紀錄，UCI 最新全檔結果見下一節。

| 候選 | 本輪確認的可用性 | 建議與未解決問題 |
| --- | --- | --- |
| **[UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)** | 官方稱 2009-12-01～2011-12-09、1,067,371 筆資料；CC BY 4.0；官方 ZIP 前 4,096 bytes 可讀 | **優先驗收**；顧客／發票／日期／數量／單價具備字典說明，缺值、取消、重複及實際覆蓋仍待核 |
| [REES46 珠寶購買](https://data.rees46.com/) | 官方 gzip 前 4,096 bytes 可讀，HTTP 206 | 次選；與[品牌總覽](https://rees46.com/en/datasets)的期間說明不一致，資料授權及原包欄位待核 |
| [dunnhumby Complete Journey](https://www.dunnhumby.com/source-files/) | 官方稱兩年、2,500 個經常購物家庭；下載須填表後寄連結 | 有條件候選；未申請／取得資料包，專屬條款、欄位與樣本偏差待驗 |

上表保留第 13 輪來源查核當時的結果，期間與規模當時僅為發布者說明、未完整下載。後續第 14 輪已依使用者指示下載並盤點 UCI 全檔，最新實測見下一節；REES46 與 dunnhumby 的取得狀態維持原紀錄。UCI 不能接成 Olist 同一批顧客，也不解除歷史 as-of／完整水位及原 25 個小組限制。

完整[比較與交接缺口](docs/STAGE6_RFM_PUBLIC_SOURCE_SEARCH.md)及[HTTP 查核報告](reports/stage6/rfm_public_source_search.json)已保存。所有新增檔案都在 `shop` 內；頁面與片段證據存於 Git 忽略的 `shop-mysql-runtime/verification/rfm-public-source-search/`，未在外部目錄存放資料或安裝套件。

### 第 14 輪 UCI 完整資料盤點

2026-10-27 已完整下載並檢查官方 Online Retail II。ZIP 45,622,418 bytes，兩層 CRC 與來源 SHA-256 核對通過；原始 Excel 保持不變。

| 本輪工作 | 狀態與實際結果 |
| --- | --- |
| 完整讀取與時間覆蓋 | 兩表 1,067,371 筆，2009-12-01～2011-12-09；25 個月份有事件，2011-12 非完整月 |
| 顧客缺值 | 243,007 列（22.7669%）；原始已知顧客鍵 5,942 個 |
| 重複與發票 | 八欄相同多餘列 34,335＝表內 12,133＋跨表 22,202；兩表在 2010-12-01～09 重疊；83 張發票有多個時間 |
| 取消與價格 | C 取消 19,494 列，其中 1 列數量為正；另有負數量非 C 3,457 列、零價 6,202 列、負價 5 列 |
| 金額 | 原始有號算術合計 GBP 19,287,250.568；八欄相異列 GBP 18,855,533.698，均非已驗收淨營收 |
| 候選支援 | 去重敏感度＋正購買已知顧客＋隔離時間衝突後，776,621 列／36,905 張發票／5,875 個顧客鍵；尚非正式清理資料集 |
| 驗證 | 14 項合成測試通過；另一 XML 讀法核對 8,538,968 格及 215 項聚合／完整性檢查通過 |

兩個探索用 365 天窗口有 4,262／4,333 個候選顧客鍵，共同 3,666 個，足以起草跨期設計。兩窗重疊半年，未計 RFM 或跨期穩定性；全檔品質與月別金額已檢視，後期不能稱為完全未知的保留資料。

第 14 輪盤點提出先凍結資料契約的建議，後續第 15 輪已完成，規則與下一步見下節。沒有原始可得／修訂時鐘及完整水位，只能做事件時間代理的回溯研究；不混接 Olist ID、不沿用其切點或把 G3 通過當 UCI 跨期成績。

完整[盤點、月別表與操作](docs/STAGE6_UCI_RETAIL_II_INTAKE.md)、[聚合結果](reports/stage6/uci_retail_ii_intake.json)與[獨立核對](reports/stage6/uci_retail_ii_verification.json)已保存。所有檔案都在 `shop`：原始資料為 `data/raw/online_retail_ii/`，逐筆工作資料為 `shop-mysql-runtime/uci_retail_ii_intake_v1/`，兩處均由 Git 忽略；保留使用者指定的新 runtime 位置。

### 第 15 輪 UCI 回溯 RFM 契約 v1 凍結

已固定兩個不重疊的 365 天窗口：**T1 [2009-12-01, 2010-12-01)**、**T2 [2010-12-01, 2011-12-01)**。T1 用來估參考切點，T2 只套用既有切點作回溯比較；前輪 2011-06-01 探索窗不納入本版，2011 年 12 月尾段也不當保留測試。

| 本輪凍結內容 | 固定規則／實際狀態 |
| --- | --- |
| 重複 | 主口徑八欄相同保留一列；另固定「每群取單表最大出現次數」敏感度，避免跨表直接相加 |
| 時間衝突 | 先取各 T 前明細再檢查；同發票時間／身分／國家衝突整張隔離，不用未來衝突改寫 T1 |
| 缺顧客與取消 | 不補造 ID；C 文件一律留取消帳，不配對尾碼、不沖銷正價購買 |
| 金額 | 以 0.001 GBP 整數精度計正價明細毛額代理，可能含費用；另固定商品代碼形狀敏感度，不宣稱淨營收 |
| 名冊與未知 | 保留各 T 前全部已知顧客鍵；乾淨零活動與品質隔離分開，隔離時正式 R／F／M 皆 null |
| 跨期評估 | T1 主口徑切點固定套到 T2 及四口徑；報母體／狀態轉移、同顧客數值與分級變化、小組支援，不用跨期結果挑規則 |
| 實際驗證 | 15 份來源／規則綁定、35 項契約檢查、38 項合成測試通過（0.204402 秒） |
| 執行界線 | 真實資料列重算、新 RFM、真實切點、訓練及跨期成績均為 0；建置器待實作 |

每期每口徑的小組支援下限固定為 `max(50, ceil(1% × 當期完整活躍人數))`；不足不合箱救結果，也不作小組業務主張。先前全檔品質／月別聚合已檢視，T2 不稱完全未知測試；歷史可得、完成水位及匿名鍵不重用仍未驗證。

第 15 輪提出的建置與獨立核對已於下一輪完成，最新結果與下一步見下節。 詳見[完整契約](docs/STAGE6_UCI_RFM_CONTRACT_V1.md)、[機器規則](docs/contracts/uci_rfm_v1.json)、[凍結來源](reports/stage6/uci_rfm_v1_specification.json)及[驗收結果](reports/stage6/uci_rfm_v1_contract_acceptance.json)。契約輪所有產物都在 `shop`，本機 guard／log 為 `shop-mysql-runtime/uci_rfm_contract_v1/`；當輪未建立正式資料集，後續第 16 輪已完成下節建置。

```powershell
.\.venv\Scripts\python.exe -B scripts\freeze_uci_rfm_contract.py --verify
```

此命令只驗已凍結來源／收據，不重新執行測試或真實資料分析。原 Olist 25 個小組限制、Stage 4 每日 10% 預算與 Dashboard 暫緩安排維持原狀。

### 第 16 輪 UCI v1 真實建置與獨立驗收

已依凍結契約完成四口徑 × 兩快照，共 **8 組、32 份 CSV**；去重映射、逐列排除、發票判定與顧客 RFM 全部保留在專案內。

| 主口徑實際結果 | T1 | T2 |
| --- | ---: | ---: |
| 觀察到的已知顧客鍵 | 4,336 | 5,914 |
| 完整活躍、可供後續數值評估 | 4,232 | 4,269 |
| 乾淨零活動、歷史曾購買 | 0 | 1,552 |
| 有本窗品質隔離的顧客 | 34 | 28 |
| 完整活躍 M 合計（GBP） | 8,234,251.454 | 8,029,057.574 |

主口徑 M 為可能含費用的正價明細毛額代理。隔離顧客正式 R／F／M 皆 null，部分已知值獨立保留；沒有從名冊刪除。四口徑名冊、狀態與 R／F 一致，M 差異另列於[完整建置結果](docs/STAGE6_UCI_RFM_BUILD_V1.md)。

本輪 30 項合成測試通過；獨立程式重新解析官方 Excel，再用 SQL 計算，完整核對 **12,720,628 筆輸出紀錄／128,416,372 格**，32 份 CSV 全部一致。來源與輸出 hashes、逐列／發票／顧客金額對帳亦通過，見[正式驗收](reports/stage6/uci_rfm_build_v1_acceptance.json)。

第 16 輪建置完成後，後續第 17 輪已完成單次切點及跨期比較，結果見下節。原建置輪沒有估切點或訓練模型；既有回溯、完整性與 Olist 小組限制保留。

所有檔案都在 `shop`；逐筆資料與 guard 位於 Git 忽略的 `shop-mysql-runtime/uci_rfm_dataset_v1/`，獨立計算與測試證據位於 `shop-mysql-runtime/verification/uci-rfm-build-v1/`。現有產物只做保存驗證：

```powershell
.\.venv\Scripts\python.exe -B scripts\build_uci_rfm_v1.py --verify
```

此命令核已存 bytes，不重建資料或重做逐格計算。全專案目前進度仍以首頁上方階段表及[完整進度](docs/PROJECT_PROGRESS.md)為準。

### 第 17 輪 UCI 固定切點跨期比較

已單次以 T1 主口徑 4,232 位完整活躍顧客估 R／F／M 切點，三軸各五級；同一組切點固定套用 T2 與三個敏感度口徑，T2 重估次數為 0。

| 本輪實際結果 | 結果與分母 |
| --- | --- |
| 兩期皆完整活躍配對 | 2,663 人，占 T1／T2 完整活躍 62.9253%／62.3799% |
| R／F／M 分級完全相同 | 30.2666%／36.9884%／42.2080% |
| 三軸 tuple 完全相同／ARI | 10.8524%／0.085655；只代表配對群的回溯變化 |
| 單軸支援 | 八組各軸五個箱皆達固定門檻 50 人 |
| 主口徑聯合小組 | T1 87／114 非空組、T2 83／112 非空組不足 50 人；涉及 1,531／1,422 人，最小組 1 人 |
| 同期清理敏感度 | 三對照分級大多與 main 相同；完整金額差、分級與小組結果全部保留，未挑最佳口徑 |
| 驗收 | 30 項合成測試通過；533,398 格分級／名冊與 59,798 項 JSON 欄值核對通過 |

T1 原完整活躍中，1,546 人在 T2 沒有合格活動、23 人有品質隔離，均留在全名冊狀態轉移，沒有偷偷從分母消失。兩期缺顧客 ID 原列占比為 19.9243%／25.0388%；缺值、歷史可得與完整水位仍限制解讀。

本輪是回溯描述，沒有「跨期穩定性通過」門檻，也不代表業務成效。後續第 18 輪已完成 Stage 6 研究交付與 UCI v1 封存，見下一節；小組不足限制保留，不依 T2 結果合箱或重挑切點。 完整[結果與限制](docs/STAGE6_UCI_RFM_TEMPORAL_V1.md)、[聚合](reports/stage6/uci_rfm_temporal_v1.json)及[驗收](reports/stage6/uci_rfm_temporal_v1_acceptance.json)已保存。

逐筆分級、配對名冊、cutpoints.json 與 guard 都在 Git 忽略的 `shop-mysql-runtime/uci_rfm_temporal_v1/`。所有檔案維持在 `shop` 內，現有產物只驗證：

```powershell
.\.venv\Scripts\python.exe -B scripts\run_uci_rfm_temporal_v1.py --verify
```

此命令只核保存 bytes，不重估或重算。Stage 4 每日 10% 提醒預算、Olist 25 個小組限制及 Dashboard 暫緩安排保留。

### Stage 6 研究交付與 UCI v1 封存（最新）

Stage 6 已整理為**離線研究交付**。Olist 的同快照 G2／G3 與 UCI 的年度跨期描述分開解讀；契約、建置、切點、排除／去重帳、指標及驗收證據都保留，沒有重建或重估研究結果。

| 本輪工作 | 交付內容與限制 |
| --- | --- |
| 研究交付與適用說明 | [完整交付文件](docs/STAGE6_RFM_RESEARCH_HANDOFF.md)：閱讀順序、兩研究線、可支持的解讀、缺件、驗證與還原操作 |
| UCI v1 封存 | `shop-mysql-runtime/backups/uci_rfm_v1_research_release_v1.zip`；收錄必要來源、程式、資料、結果、控制檔及導覽快照 |
| 完整性驗收 | ZIP 每個成員讀回驗 CRC／SHA-256；實際檔數、大小、hash 與封存測試結果見[外層收據](reports/stage6/uci_rfm_v1_research_release.json) |
| 小組限制 | UCI T1／T2 的 87／83 個非空聯合小組不足 50 人；Olist 原 25 個小組不足限制保留，不合箱救結果 |
| 研究定位 | 回溯描述；未驗收行銷、流失／未來價值、淨營收或營運適用性 |
| 備份範圍 | 所有保存檔案都在 `shop`、逐筆與 ZIP 由 Git 忽略；目前只在同一磁碟，尚未異地備援 |

Stage 6 交付時提出的 Retailrocket 來源盤點，已在下列 Stage 8 完成並制定 v1 契約。推薦資料建置與逐格驗收、熱門baseline執行規格亦已完成，baseline／評估器實作與合成驗收也已完成，一次真實開發與反讀也已完成，共現與 P0 配對比較規格現已另行凍結，實作／合成oracle、成本與入口及真實配對validation亦已完成；Stage 4／5 仍待交接資料，延遲固定每日 10% 預算，Dashboard 繼續暫緩。

```powershell
# 完整讀回封存，並核目前凍結研究來源；不重做 RFM 或指標。
.\.venv\Scripts\python.exe -B scripts\archive_uci_rfm_v1.py --verify
```

README 等脈絡快照可持續更新進度，ZIP 內封存版本保持不變；研究程式、資料、切點與結果若需改動，另立新版本。外層收據在 ZIP 外，請與 ZIP 一併保留。

## Stage 8：Retailrocket 來源與推薦資料契約（前一輪）

2026-10-28 已從發布者 Kaggle API 取得完整第 2 版 ZIP（304,719,974 bytes），四份 CSV 共 23,033,672 列；原始資料與全部本機產物都在 `shop` 內，由 Git 忽略。原發頁／API 的授權為 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)，本研究限條件內的非商業用途，商業服務尚未獲授權。

| 本輪工作 | 真實結果與限制 |
| --- | --- |
| 官方來源與完整掃描 | 2,756,101 事件、20,275,902 屬性列、1,669 分類列；四檔 CRC／SHA 完整反讀通過 |
| 事件鍵 | 460筆完全重複超額列，2,132組同訪客同毫秒多商品；原列序不是時間順序，transactionid 不是逐事件唯一鍵 |
| 觀察與屬性時間 | 事件 2015-05-03 至09-18 UTC，屬性05-10至09-13；522,307列原始 view 無嚴格事前 available，30個分類值不在樹中 |
| 契約 v1 | 下一瀏覽時間點的商品集合；30分鐘 view session；訓練05-04至08-01前、驗證8月、預留回溯測試09-01至09-18前 |
| 防止未來資料混入 | 候選限查詢前已出現商品，屬性禁止未來回填；全候選 NDCG@10，不以負採樣或丟掉不可達目標美化分母 |
| 獨立核對與範圍 | CSV／SQLite 與 pandas 兩路共44項檢查通過，來源／契約已 SHA 固定；0推薦樣本、0模型擬合、0排名成績 |

完整[來源、適用與契約](docs/STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md)、[JSON規則](docs/contracts/retailrocket_recommendation_v1.json)、[實讀聚合](reports/stage8/retailrocket_source_audit_v1.json)、[獨立核對收據](reports/stage8/retailrocket_contract_v1_acceptance.json)已保存。這是回溯研究，缺歷史入庫、曝光、可售庫存與因果證據；沒有證明轉換或營收效果。

本輪來源契約提出的建置與逐筆驗收，已於下節完成；原始窗口列數仍不是推薦query數。Stage 6 UCI封存與小組限制保留，沒有重跑舊研究。

```powershell
.\.venv\Scripts\python.exe -B scripts\audit_retailrocket_source.py --verify
.\.venv\Scripts\python.exe -B scripts\freeze_retailrocket_contract.py --verify
```

以上只驗既有 bytes；不重掃 CSV 或建樣本，不代表已完成 builder 語意驗收。

## Stage 8：推薦資料v1建置與反讀（最新）

2026-10-28 依凍結契約完成一次正式建置。2,756,101筆來源事件逐列分為2,754,113筆合格canonical、460筆重複及1,528筆排除；去重／排除與跨界帳全部保留在shop內Git忽略路徑。

| 角色 | query機會 | 合格標註query | 合格query訪客 | 無後續 | 觀察不足 | 跨角色主狀態 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 暖身 | 13,300 | 0 | 0 | 0 | 0 | 0 |
| 訓練 | 1,823,018 | 642,619 | 210,395 | 1,179,931 | 468 | 0 |
| 驗證 | 533,790 | 166,897 | 62,235 | 366,423 | 470 | 0 |
| 預留回溯時間測試 | 292,114 | 92,086 | 34,875 | 199,776 | 252 | 0 |

已建立1,755,246個view session、234,795個商品first-seen目錄；每個query僅能取嚴格較早出現的候選。沒有後續不當負例、跨界不當同窗標籤、不可達目標仍留完整分母。多商品等稀疏小組限制保留，詳見[結果、支援與限制](docs/STAGE8_RETAILROCKET_BUILD_V1.md)。

30項合成測試通過；16份CSV共20,093,122列／221,676,649格，由直接重讀官方ZIP的獨立路徑全部核對並反讀，角色聚合一致。[執行前規格](reports/stage8/retailrocket_build_v1_specification.json)、[正式聚合](reports/stage8/retailrocket_build_v1.json)及[驗收收據](reports/stage8/retailrocket_build_v1_acceptance.json)已保存。0推薦模型擬合、0排名成績，預留回溯時間測試未出分；標籤已因驗收被讀取，不稱全新未接觸來源。

Stage 8提出的熱門baseline統計、回退、完整候選分母與測試啟用規格，已於下列Stage 9凍結；後續實作與合成驗收亦已完成，真實開發入口已凍結，尚未擬合或出分。原非商業授權、回溯／匿名身分／曝光與可售庫存限制保留；Stage 4每日10%及Dashboard暫緩不變。

```powershell
.\.venv\Scripts\python.exe -B scripts\build_retailrocket_v1.py --verify
```

只核既有來源／輸出／收據bytes，不重做逐格語意計算；首次正式流程已完成完整反讀。

## Stage 9：熱門baseline與完整候選評估執行規格（規格凍結輪）

2026-10-28 已凍結單一確定性P0：商品分數為固定fit窗中每筆canonical view加1；不以query標籤擬合，不混加購／交易，不做時間衰減、活動刪除或超參數搜尋。

| 已固定項目 | 規則 |
| --- | --- |
| 開發統計 | 2015-05-04至08-01前的train view；主擬合一次，固定後只評validation |
| 冷啟動與完整候選 | query前已出現的全部商品；新訪客沿用相同熱門排序，商品未見時0分，次數降序／數值ID升序；保留已看商品 |
| 主評估分母 | 驗證166,897 query／62,235訪客，完整target166,952次；主NDCG@10保留不可達target，另列條件結果，禁止負採樣 |
| 預留測試 | 92,086 query／34,875訪客；先實作、完整驗證反讀、凍結程式與最終重估，再由後續明確測試要求啟用；目前locked |
| 最終重估 | gate條件完成後，另存2015-05-04至09-01前train＋validation的一次主重估；測試期不更新統計 |
| 本輪驗收 | 47份來源與產物SHA、38項一致性檢查、28項反例測試通過；0統計fit、0排名query、0指標，baseline／evaluator尚未實作 |

[完整方法與啟用條件](docs/STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md)、[機器執行規格](docs/contracts/retailrocket_popularity_execution_v1.json)、[來源凍結收據](reports/stage9/retailrocket_popularity_v1_specification.json)、[實際驗收](reports/stage9/retailrocket_popularity_v1_spec_acceptance.json)均已保存。驗證多商品當前／目標小組56／53筆低於1,669，預留測試33／29筆低於921，只能描述；不以成績好壞挑是否開測試。原回溯、身分、曝光／庫存、非商業授權與Stage 6小組限制保留。

本輪規格提出的實作、手算／獨立oracle合成驗收及真實開發入口凍結，已於下節完成。下一步才估一次真實訓練統計並完整評估validation；預留測試仍locked。

```powershell
.\.venv\Scripts\python.exe -B scripts\freeze_retailrocket_popularity_v1.py --verify
```

只核已凍結來源bytes與規格一致性，不解析資料CSV、不擬合／計分；`--freeze`已執行完成，不刪guard或覆寫補證據。所有檔案在shop內，逐筆資料與本機狀態由Git忽略。

## Stage 9：P0與完整候選評估器實作、開發入口凍結（實作驗收輪）

2026-10-28 已依凍結v1實作canonical view次數P0、因果完整候選top10、完整target的NDCG／Recall／HitRate／MRR、query／visitor macro、條件結果與切片；獨立oracle另以SQL重算次數、完整排序或可證明的全候選等價路徑，以及Decimal／Fraction指標逐格反讀。

| 本輪工作 | 實際結果與界線 |
| --- | --- |
| 手算／反例測試 | 54項通過，含1,024種命中排列、27個候選前綴、不可達target、空候選、冷啟動、錯分母與入口拒收 |
| 正式合成反讀 | 兩個小型case，四CSV合計35列／226格及fit audit／完整聚合全部一致；一般完整排序與精確快取證明兩路皆驗 |
| 開發入口 | 61份來源／環境SHA固定；只提供一次train fit＋完整validation，逐query獨立反讀；部分產物拒絕重播 |
| 真實執行範圍 | 0真實fit、0真實排名／指標、0真實CSV記錄解析；166,897筆validation尚未出分 |
| 預留測試 | locked；沒有final-refit或reserved-test指令，核心及loader也拒絕測試角色 |

[實作、手算與操作](docs/STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md)、[合成驗收收據](reports/stage9/retailrocket_popularity_v1_implementation_acceptance.json)、[真實開發入口規格](reports/stage9/retailrocket_popularity_v1_development_specification.json)已保存。合成NDCG等手算數字不是真實Retailrocket成績；多商品56／53及33／29小組不足、回溯／匿名身分／曝光與庫存／非商業限制均保留。

目前只核既有準備產物：

```powershell
.\.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
```

上述預留的真實開發已在下節成功執行一次並完整驗收；目前只用`--verify`核來源／輸出，不重播fit。完成開發不會自動啟用預留測試。所有檔案在shop內，合成產物、guard與本機狀態由Git忽略，原資料／契約／過去報告未改寫。

## Stage 9：P0一次真實train擬合與完整validation（最新）

2026-10-28 已依凍結入口完成一次主fit、一次獨立SQL count audit及完整166,897筆validation／62,235匿名訪客的逐query反讀。使用1,823,388筆train view、198,946個正次數商品，沒有新調參、最終重估或預留測試出分。

| 真實開發驗證指標，非預留測試成績 | 主結果 |
| --- | ---: |
| query-macro NDCG@10 | 0.001681829 |
| Recall@10／HitRate@10 | 0.417922%／0.418222% |
| MRR@10／visitor-macro NDCG@10 | 0.000943565／0.001622526 |
| 商品覆蓋 | 10／222,754＝0.004489% |
| 完整反讀 | 四CSV共699,637列／5,738,596格，全部一致；fit audit及主／條件／切片聚合也相符 |

完整target 166,952次均留在分母；其中161,264次事前可達。全目標可達的161,211筆條件結果另列，不替換主成績。P0在本窗只推薦同樣10個商品，未形成個人化證據；多商品56／53筆及正／零次數混合目標3筆低於1,669門檻，只描述，不事後挑切片調參。

[正式結果與限制](docs/STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md)、[聚合報告](reports/stage9/retailrocket_popularity_v1_development.json)、[獨立逐query驗收](reports/stage9/retailrocket_popularity_v1_development_acceptance.json)已保存。預留測試仍locked、排名0筆；開發成績不能當未知／前瞻或營運效果。原回溯、匿名身分、曝光／庫存、非商業與Stage 6小組限制保留。

P0 對照持續保存；後續共現配對規格已另列於下方 Stage 10，實作與合成驗收、成本及真實入口也已另行完成。這份 P0 結果沒有追加 fit 或自動開測試；現只用：

```powershell
.\.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
```

只核已保存bytes與來源／收據，不重估或重計指標。所有逐query／item統計、日誌及guard留shop內Git忽略路徑。

## Stage 10：共現 C1 與 P0 配對比較規格 v1（規格凍結輪）

已凍結[完整規格](docs/STAGE10_RETAILROCKET_COOCCURRENCE_PAIRED_SPEC_V1.md)與[機器契約](docs/contracts/retailrocket_cooccurrence_paired_v1.json)。該規格輪82 來源 SHA、131 項一致性檢查、64 項規格測試通過，來源及輸出反讀一致；見[凍結來源清單](reports/stage10/retailrocket_cooccurrence_v1_specification.json)及[驗收收據](reports/stage10/retailrocket_cooccurrence_v1_spec_acceptance.json)。這是該規格輪驗收，C1／配對評估器／bootstrap 當時尚未實作，0 新擬合、排名、比較指標及區間，真實 CSV 只核位元組雜湊、0 列解析。

| 固定事項 | 規則與目前狀態 |
| --- | --- |
| 計數 | train-only session 商品集合；商品及無序 pair 每 session 各計一次；單商品 session 保留，跨截止線只取 train 部分 |
| 歷史／分數 | 同 session 截至 query 的不同 view 商品，含當下 basket；`Σ C_ij/S_i`，排除自我邊，以精確有理數比較 |
| 回退 | 有理分數 → 原 P0 count → 數值 ID；無證據時完全等同 P0，正分不足 10 用零分候選補足，不刪已看商品 |
| 配對 | 原 166,897 validation 查詢完整一對一；相同候選／完整 target／分母，重用 P0 原排名與指標、0 重訓 |
| 主要比較與區間 | 全查詢平均 NDCG@10 差；62,235 訪客成組 bootstrap 2,000 次，seed 42／PCG64／NumPy 2.5.4，95% percentile；尚未計算 |
| 小組限制 | 支援門檻 1,669；多商品 56／53、混合支援 3 筆只能描述；原 train 199／192、test 33／29 限制保留 |
| 測試／研究角色 | test locked；P0 validation 已在設計前檢視，後續只屬回溯開發比較，不能當未知測試、營運或因果成效 |

該輪提出的實作、手算／合成 oracle、train-only 工作量盤點與真實入口，已在下節完成。資源不足須停止，不能偷偷截斷 session／鄰居／歷史。後續真實執行須獨立逐查詢及全 bootstrap 反讀；本輪未建立該執行目錄，也不解鎖測試。

歷史規格的初始空目錄檢查不適用於已有真實產物；現在用最新入口核歷史及本輪bytes：

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

所有新檔案都在 shop；私有凍結與驗證紀錄位於 Git 忽略的 `shop-mysql-runtime/retailrocket_cooccurrence_spec_v1/` 及 `shop-mysql-runtime/verification/retailrocket-cooccurrence-spec-v1/`，既有 P0 與資料 v1 原狀保留。

## Stage 10：C1／配對／bootstrap 實作、成本與真實入口（實作凍結輪）

依 v1 完成[實作、手算、獨立 oracle 與操作說明](docs/STAGE10_RETAILROCKET_COOCCURRENCE_IMPLEMENTATION_V1.md)，55 項測試、104 份來源凍結與兩組正式合成 oracle 全過；見[實作驗收](reports/stage10/retailrocket_cooccurrence_v1_implementation_acceptance.json)及[凍結真實 validation 入口](reports/stage10/retailrocket_cooccurrence_v1_validation_specification.json)。另有 40 組固定合成 session × 8 查詢＝320 筆完整候選差分比對，正式兩組各 5 查詢／2,000 次 bootstrap 均獨立反讀與重播。上述是該實作輪的合成驗收，後續真實結果見下節。

| 本輪工作 | 實際結果 |
|---|---|
| C1 | 二元 session 計數、singleton、截止線裁切、同 session 因果歷史與精確有理 top10 完成；無證據完整 P0 回退，零分補足、不刪已看 |
| 配對評估 | 重用 P0，完整 key／順序、同候選／完整 target／分母；主／條件／切片、差值與回退診斷完成 |
| Bootstrap | 訪客成組、query-macro 權重、seed 42／PCG64／2000 次、線性 percentile 與抽樣 SHA／RNG 狀態重播完成 |
| 真實 train-only 成本 | 1,180,256 session，其中 singleton 998,801；1,823,018 baskets，精確 pair 發射 2,292,165 次，最大 389 種商品 |
| 成本獨立反讀 | 1,180,256 列／5,901,280 格一致；未建立真實商品／pair 模型或讀 validation／test 商品／target |
| 資源限制 | process RSS 8 GiB、執行目錄 20 GiB、整輪 6 小時；剩餘磁碟／可用記憶體至少 8／4 GiB；合作式檢查，超限保留證據並停止 |
| 真實執行狀態 | C1 fit／validation 排名／配對指標／bootstrap 均 0；沒有 final-refit／test 入口，test locked |

手算案例 `H={1}` 時商品 2／3 得分 1／1/2、前三名 `[2,3,1]`；target `{2,999}` 中 999 不可達仍保留，Recall＝1/2、NDCG≈0.613147。此數字只屬玩具資料，不是真實提升。

現可唯讀核凍結：

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

該輪預留的真實執行已在下節完成；現在只做 --verify，不追加fit或重播評估。

多商品 56／53、混合支援 3 筆仍低於 1,669 支援門檻，只描述；原 train 199／192、test 33／29 及 Stage 6 小組限制保留。P0 validation 已在 C1 規格制定前曝光，後續仍為回溯開發比較，不能宣稱未知測試、上線或因果提升。

該實作輪的合成／train-only成本／guard留在shop內Git忽略路徑；該輪尚無真實執行目錄，後續真實結果另列下節。

## Stage 10：C1／P0 一次真實配對 validation（執行輪）

已依凍結入口完成一次 C1 train fit、同 166,897 queries／62,235 visitors 與 P0 配對、2,000 次訪客成組 bootstrap 及獨立逐筆核對。P0 保持原狀，沒有重訓、重排名、最終重估或預留測試出分。

| 同一 validation 的指標 | P0 | C1 | C1−P0 |
|---|---:|---:|---:|
| query-macro NDCG@10 | 0.001681829 | 0.106400714 | 0.104718885 |
| Recall@10 | 0.004179224 | 0.180151531 | 0.175972306 |
| HitRate@10 | 0.004182220 | 0.180182987 | 0.176000767 |
| MRR@10 | 0.000943565 | 0.083664114 | 0.082720549 |
| visitor-macro NDCG@10 | 0.001622526 | 0.113072891 | 0.111450365 |
| 商品 coverage@10 | 0.000044893 | 0.199982941 | 0.199938048 |

以上皆為已檢視的回溯開發 validation；比例採0–1、差為絕對差。主要 NDCG 差 0.104718885；95% 訪客成組 percentile interval 為 [0.101004915, 0.108446582]，2,000 次皆獨立重播。區間在這個已曝光的開發窗內為正；不能據此外推未知時間、獨立真人、營運或因果改善。

| 本輪驗收／資源 | 實際結果 |
|---|---|
| 模型與lineage | support 198,946、pair 1,954,889、train session 1,180,256筆全核對 |
| 查詢／抽樣 | 166,897逐筆完整配對與所有巢狀欄值反讀；2,000次抽樣SHA／RNG／分母／差值重播 |
| 資源 | 4197.172000秒；抽查RSS峰值1.034683GiB；8GiB／20GiB／6小時限制未觸發，合作式檢查 |
| 狀態 | P0原狀，test locked、0測試排名；無新調參或追加fit |

完整target 166,952次均留在分母；161,211筆全target可達條件結果另列。多商品56／53、混合支援3筆低於1,669門檻，僅描述；原train／test及Stage 6小組、回溯／匿名身分／曝光與庫存／非商業限制保留。

C1 推薦商品聯集由 P0 的 10 個擴至 44,547 個，但仍有 16,319 筆（9.777887%）完全回退。另有 11,943 筆目標全部沒有 train 支援的查詢，兩模型 NDCG 都是 0；這與回退查詢是不同診斷，不能相加。後續研究交付須保留冷商品缺口，不能把整體改善當成所有情境都適用。

[完整結果與限制](docs/STAGE10_RETAILROCKET_COOCCURRENCE_VALIDATION_V1.md)、[正式報告](reports/stage10/retailrocket_cooccurrence_v1_validation.json)、[獨立驗收](reports/stage10/retailrocket_cooccurrence_v1_validation_acceptance.json)已保存；逐筆、模型、抽樣與oracle只留shop內Git忽略路徑。完成後只核既有產物：

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

該執行輪的研究交付與證據保存已完成，見下節；P0原狀與預留測試locked持續保留。

## Stage 10：C1／P0 研究交付與證據保存（最新）

已完成[研究交付與適用說明](docs/STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md)，整理方法、資料角色、原結果、冷商品與小組限制、操作及完整test啟用條件。P0與C1原產物保持相同bytes；本輪只保存證據，0新fit／排名／bootstrap／指標重算，預留測試仍locked。

| 本輪工作 | 實際結果 |
| --- | --- |
| 證據包 | 102個payload檔＋1份manifest，257,447,194 bytes（245.521 MiB）；全部CRC／SHA讀回通過，另列98份包外但仍在shop內依賴 |
| 原狀保存 | P0 9檔、C1 12檔與4份gate前後一致；無final refit／test產物 |
| 保存工具驗收 | 29項合成I/O測試通過；涵蓋CRC／SHA、竄改／缺檔、路徑／重複成員、部分產物與拒絕覆寫 |
| 解讀界線 | 保留11,943筆無train支援目標、16,319筆完全回退（不同診斷）及56／53／3筆小組不足；回溯開發改善不代表營運適用 |

既有validation NDCG：P0 0.001681829、C1 0.106400714，配對差0.104718885、95%訪客成組區間[0.101004915, 0.108446582]；這些是前輪已驗收結果，本輪未重算。冷商品只指本次train無正支援，不等於從未見過或全部不可達。

ZIP及逐筆證據只保留在shop內Git忽略位置；[保存收據](reports/stage10/retailrocket_c1_p0_v1_research_release.json)列出內容、依賴與SHA。這是同磁碟結果證據包，原始資料／完整推薦資料集／環境沒有全部收進ZIP，不能單靠它宣稱完整環境還原或異地備援。

```powershell
.venv\Scripts\python.exe -B scripts\archive_retailrocket_c1_p0_v1.py --verify
# 僅驗證ZIP與公開收據，不代表包外依賴完整：
.venv\Scripts\python.exe -B scripts\archive_retailrocket_c1_p0_v1.py --verify-archive-only
```

Stage 11 已選定 D1 並另行凍結比較規格，見下節；validation 已曝光，C1／P0 v1 保留原狀，不依同窗挑組調參。最終選模／refit／test仍須獨立規格及驗收，C1不能沿用P0 gate取得授權。Stage 4／5待新資料、每日10%提醒固定，Dashboard暫緩。

## Stage 11：候選盤點與 D1 比較規格（規格輪）

已盤點有向轉移類、session-kNN、implicit ALS、BPR、EASE 五類候選，選定 **D1：有向相鄰 basket 的 session 關聯模型**。研究問題是：相同支援分母與完整歷史下，把 C1 任意無序共現限制成有向相鄰關聯，會如何改變下一 basket 的 NDCG？方向與鄰近性同時改變，不能單獨歸因；D1 是自訂關聯分數，不是標準 Markov 機率。

| 本輪項目 | 已凍結內容／實際驗收 |
| --- | --- |
| 計數與排序 | train 同 session 原始相鄰 baskets，跨 basket 笛卡兒積排除 self-edge；同方向每 session 只計一次，完整重用 C1 S_i／H(q)；精確有理分數、原 P0 解同分與補位 |
| 比較母體 | 同 166,897 validation 查詢／62,235 訪客、完整因果候選及 target 分母；P0／C1 原 bytes 只讀，不重訓或重排 |
| 唯一主要比較 | D1−C1 全查詢 NDCG；2,000 次訪客成組 bootstrap，沿用抽樣身分而另算新差值；D1−P0 僅描述，沒有第二組推論區間 |
| 規格驗收 | 199 份來源 SHA、228 項規格檢查、109 項規格／I/O 守門測試通過；JSON 反讀通過。僅驗證規格與凍結工具，尚非 D1 模型合成驗收 |
| 本輪執行範圍 | 0 新 fit／排名／指標／bootstrap、0 真實 CSV／JSONL 列解析；未做成本掃描，沒有 D1 真實執行目錄；test locked |

**P0 與 C1 的 validation 已在選 D1 前曝光**，後續只是同一開發窗的新比較，不是未知資料成績。原 11,943 筆冷目標查詢的無 train 支援缺口保留；current／target 多商品 56／53 與 mixed 3 仍樣本不足。D1 不宣稱解決冷商品，也無轉換、營收或因果改善證據。RSS 8 GiB、執行目錄 20 GiB、6 小時的後續上限已固定，實測成本與監控入口尚待下一輪。

詳細方法、來源、適用與限制見[Stage 11 規格](docs/STAGE11_RETAILROCKET_DIRECTED_SPEC_V1.md)、[機器契約](docs/contracts/retailrocket_directed_paired_v1.json)、[候選盤點](reports/stage11/retailrocket_stage11_candidate_inventory_v1.json)、[來源快照](reports/stage11/retailrocket_directed_v1_specification.json)與[驗收收據](reports/stage11/retailrocket_directed_v1_spec_acceptance.json)。所有新增檔案與日誌均在 shop；原 P0／C1 結果、gate 與交付 ZIP 保持原狀。

```powershell
# 只核凍結來源、規格與收據，不執行模型或讀取真實資料列。
.venv\Scripts\python.exe -B scripts\freeze_retailrocket_directed_v1.py --verify
```

上述實作、合成、成本盤點與真實入口已於後續輪完成，見下節；原規格保存不改。最終選模／refit／test 仍需另立規格與驗收，不因本輪凍結或後續有利 CI 開啟；每日 10% 提醒固定，Dashboard 暫緩。

## Stage 11：D1 實作、成本與真實入口（實作凍結輪）

D1、三臂配對評估器與 bootstrap 已實作，通過手算及獨立合成反讀；train-only 成本核對後，真實 validation 入口已凍結。**本輪 0 真實 D1 fit／validation 排名／效能／bootstrap，預留測試仍 locked。**

| 本輪項目 | 實際結果 |
| --- | --- |
| 實作與合成驗收 | 60 項測試、217 份來源凍結、兩組正式合成 oracle 全過；兩組各 5 queries／2,000 次抽樣完整核對，另有 24×6 查詢的完整候選排序差分 |
| Train-only 成本 | 1,823,018 train baskets／1,180,256 sessions；相鄰 642,762 對、原始有向發射 493,669 次、session 去重邊量 479,231，重複 14,438 次 |
| 獨立成本反讀 | 1,180,256 列／10,622,304 格一致；只解碼 train 商品，未建全域 D 模型或新 S |
| 峰值工作量 | 每 session 最多 398 個不同有向邊、414 次原始發射；998,906 個 session 無 D 邊，仍保留其共享支援 |
| 資源與保存 | RSS 8 GiB、執行目錄 20 GiB、6 小時上限；超限停止／保留證據／拒絕重播；原 P0／C1、gate、證據包 bytes 不變 |

成本兩遍核算耗時 182.484324 秒；這不是推薦排名時間或整輪完成保證。真實全域 unique D 邊數、模型 RSS、validation 工作量與 D1 效能仍未知。P0／C1 validation 已曝光；方向與鄰近性共同改變、冷目標 11,943 筆的無 train 支援缺口、小組 56／53／3 不足及回溯限制保留。主要比較仍為 D1−C1 NDCG，D1−P0 只描述。

方法、手算、監控範圍與限制見[實作說明](docs/STAGE11_RETAILROCKET_DIRECTED_IMPLEMENTATION_V1.md)、[入口凍結](reports/stage11/retailrocket_directed_v1_validation_specification.json)、[實作／成本驗收](reports/stage11/retailrocket_directed_v1_implementation_acceptance.json)。所有來源、合成、成本與日誌均在 shop。

```powershell
# 只核保存 bytes，不重跑模型／成本／測試。
.venv\Scripts\python.exe -B scripts\run_retailrocket_directed_v1.py --verify
```

上述一次真實 validation 與完整驗收已於後續輪完成，見下節；本節保留實作凍結輪當時的準備證據。最終 refit／test 仍未執行。

## Stage 11：D1／C1／P0 一次真實 validation（執行輪）

依凍結入口完成一次 D1 train 擬合、完整 166,897 筆 validation／62,235 訪客、2,000 次主要 D1−C1 bootstrap，並以獨立 SQL／有理排序／Decimal 指標及全部抽樣反讀驗收。原 P0／C1 逐筆控制值只讀重用，0 重訓／重排，預留測試仍 locked。

| 完整 validation 指標 | P0 | C1 | D1 | D1−C1 | D1−P0（描述） |
| --- | ---: | ---: | ---: | ---: | ---: |
| NDCG@10 | 0.001681829 | 0.106400714 | 0.099799771 | -0.006600944 | +0.098117941 |
| Recall@10 | 0.417922% | 18.015153% | 16.748354% | -1.266799 百分點 | +16.330431 百分點 |
| HitRate@10 | 0.418222% | 18.018299% | 16.752248% | -1.266050 百分點 | +16.334026 百分點 |
| MRR@10 | 0.000943565 | 0.083664114 | 0.078904014 | -0.004760100 | +0.077960449 |
| Visitor-macro NDCG | 0.001622526 | 0.113072891 | 0.104230872 | -0.008842019 | +0.102608347 |
| 共同候選聯集 coverage | 0.004489% | 19.998294% | 19.899081% | -0.099213 百分點 | +19.894592 百分點 |

唯一主要推論為 D1−C1 NDCG：差 **-0.006600944**，95% 訪客成組 bootstrap 區間 **[-0.007511893, -0.005716747]**；主要區間全為負，這個已曝光開發窗支持 D1 的 NDCG 低於 C1。其他指標及 D1−P0 只有描述差值，沒有額外區間／p 值。主分母保留全部 target 166,952 次、可達 161,264 次、共同候選聯集 222,754；條件結果仍另列 161,211 筆，不取代主結果。

| 本輪驗收與資源 | 實際結果 |
| --- | --- |
| 模型 | train 1,180,256 sessions；實測 370,325 個全域不同有向邊；原始發射 493,669、session 去重邊量 479,231，與凍結成本相符 |
| 完整反讀 | support 198,946 列、edges 370,325 列、session lineage 1,180,256 筆、queries 166,897 筆及 bootstrap 2,000 筆；全部巢狀值核對 |
| 回退 | D1 完全回退 18,556 筆，較 C1 多 2,237 筆；C1 回退而 D1 有正證據 0 筆，符合限制關係 |
| 資源 | 2377.547000 秒；抽查峰值 RSS 1.331944 GiB；目前執行目錄 1.230709 GiB，未超過 8 GiB／20 GiB／6 小時限制 |

**Validation 在選 D1 前已曝光。** 本結果不代表未知測試或營運效果；方向與相鄰性共同改變，不能分別歸因。原 11,943 筆無 train 支援的冷目標查詢保留，D1 該組 NDCG 0.000000000／Recall 0.000000000／HitRate 0.000000000／MRR 0.000000000；不能因此宣稱解決冷商品。多商品 56／53、mixed 3 仍低於 1,669 門檻，只作描述；匿名鍵、時間／版本／完整性／曝光與庫存缺口及原 Olist／UCI 限制保留。

詳見[完整結果與限制](docs/STAGE11_RETAILROCKET_DIRECTED_VALIDATION_V1.md)、[正式聚合](reports/stage11/retailrocket_directed_v1_validation.json)、[獨立驗收](reports/stage11/retailrocket_directed_v1_validation_acceptance.json)。逐筆、模型、SQL、抽樣與 guard 在 shop 內的 Git 忽略目錄；原 P0／C1、gate 與交付包保持原狀。

```powershell
# 完成後只核既有 bytes，不追加 fit、排名或抽樣。
.venv\Scripts\python.exe -B scripts\run_retailrocket_directed_v1.py --verify
```

上述三臂研究交付與證據保存已於下節完成；本節保留執行輪結果，最終 refit／test 仍未啟動。

## Stage 11：三臂研究交付與證據保存（最新）

D1／C1／P0 的研究交付、適用說明及本機證據保存已完成。本輪讀取既有正式聚合並保存檔案 bytes，0 新擬合、排名、指標重算或 bootstrap；三臂原結果與舊 C1／P0 ZIP 均保持原 SHA，預留測試仍 locked。

| 本輪工作 | 實際結果 |
| --- | --- |
| 研究交付 | [三臂方法、結果、適用與限制](docs/STAGE11_RETAILROCKET_THREE_ARM_RESEARCH_HANDOFF_V1.md)；完整 validation 166,897 查詢／62,235 匿名訪客 |
| 已有主要結論 | D1 NDCG@10 0.099799771；D1−C1 差 -0.006600944，95% 區間 [-0.007511893, -0.005716747]；本已曝光開發窗不支持以 D1 取代 C1 |
| 證據包 | 144 個 payload 檔＋1 份 manifest，共 145 個 ZIP 成員，649,850,977 bytes（619.746 MiB）；全部成員 CRC／SHA-256 反讀通過，另列 159 份包外依賴 |
| 保存工具驗收 | 44 項 I/O 合成測試通過；查核安全路徑、來源身分、三臂完整目錄、拒覆寫、部分產物保存與 locked gate；沒有重跑研究 oracle |
| 保留限制 | 冷目標 11,943 查詢的四項排序指標仍為 0；多商品 56／53、mixed 3 仍不足 1,669 門檻；回溯可得性、匿名鍵、曝光／庫存及原來源授權限制保留 |

證據包在 `shop-mysql-runtime/backups/retailrocket_three_arm_research_release_v1.zip`；完整數量、大小、SHA、來源與包外依賴見[保存收據](reports/stage11/retailrocket_three_arm_v1_research_release.json)。原始資料、完整資料集及 Python 環境未全部包入；它是同一 shop 磁碟的結果證據副本，不是完整環境還原或異地備援。README 等是封存時脈絡快照，完成收據後才更新的導覽允許與快照不同；凍結研究檔仍驗相同 bytes。

```powershell
# 完整核 ZIP、live 凍結來源及 shop 內包外依賴；不重跑研究。
.venv\Scripts\python.exe -B scripts\archive_retailrocket_three_arm_v1.py --verify
# 僅核 ZIP 與公開收據，不能據此宣稱包外資料完整。
.venv\Scripts\python.exe -B scripts\archive_retailrocket_three_arm_v1.py --verify-archive-only
```

前輪提出的盤點與規格已由 [Stage 12](docs/STAGE12_TEMPORAL_AVAILABILITY_AND_KNN_SPEC_V1.md) 完成。K1 合成實作、獨立 oracle、train-only 成本與真實 validation 入口已驗收凍結；唯一一次真實執行已依 3 小時 30 分鐘時限停止，完整反讀未完成，詳見[停止與保存紀錄](docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ATTEMPT_V1.md)。保留三臂原版本及已曝光聲明，最終選模／refit／test 仍另行規劃，預留測試繼續 locked。本結果沒有完成最終部署選模；Stage 4 每日 10% 提醒不變，Dashboard 暫緩。

## 專案結構

```text
shop/
├── data/          # 原始資料、特徵快取；本機保留，內有放置說明
├── docs/          # 設定、進度、方法與各輪實驗
├── notebooks/     # 01 資料、02 SQL、03 EDA、04 延遲預測
├── reports/       # 聚合 JSON、事前規格與已產出圖表
├── scripts/       # 啟動、匯入、特徵、訓練、推論、診斷與驗收
├── sql/           # 建立資料庫、筆數檢查、商業查詢
├── tests/         # 特徵、時間切分、排名、資料集與重現契約測試
├── models/        # 本機模型，Git 忽略
├── .runtime/      # 本機服務、下載、日誌與私有驗收證據，Git 忽略
├── .venv/         # 專案 Python 套件，Git 忽略
├── requirements.txt
└── requirements-lock.txt
```

實驗程式、報告與輸入有 SHA 綁定，沿用原路徑以利重現；清整文件時不搬移或改寫這些檔案。不同輪次可能都稱為「102 欄」，實際內容以當輪特徵白名單與規格為準。

## 驗證與維護

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

測試範圍、分組及 Windows 權限注意事項見[測試說明](tests/README.md)。各輪測試數與耗時以當輪報告為準，不加總成新的測試成績。

先前第二次專案清整僅整理文件：首頁回到現況摘要，Stage 5、6 逐輪紀錄改成[專案進度](docs/PROJECT_PROGRESS.md)的歷程表，並將文件、報告、腳本、測試、Notebook 與資料導覽依階段重排、修正過時描述。該輪沒有修改實驗程式、正式 JSON、圖表與 Notebook，也沒有新增訓練或研究結果。清整後 1,058 個本機連結全部有效、207 個 SHA 綁定檔前後一致，全專案測試 1,764 項全過（605.317 秒）；完整紀錄見[專案清整](docs/PROJECT_PROGRESS.md#專案清整)。

GitHub 保存程式、未執行的 Notebook、文件、聚合報告與圖表。原始資料、特徵快取、本機模型、連線帳密與執行狀態由 Git 忽略；連線設定範本為 [`scripts/db_config_example.py`](scripts/db_config_example.py)。每次推送需同步更新 README，commit 使用繁體中文，其餘協作規則見 [AGENTS.md](AGENTS.md)。
