# 電商智慧推薦系統

Smart E-Commerce Recommendation System

以 Olist 電商資料練習資料建置、SQL、商業分析及延遲預測，再延伸至 Retailrocket 推薦系統、API 與前端。目前已完成資料環境、SQL 與 EDA 初版，正在研究固定每日 10% 提醒預算的延遲辨識；推薦系統與 API 尚未開始。

## 目前進度

| 階段 | 狀態 | 現有成果 |
| --- | --- | --- |
| Stage 1：資料與環境 | 完成 | Olist 九份 CSV、MySQL、Jupyter 與本機啟動工具 |
| Stage 2：SQL | 完成 | 訂單、品類營收、平均客單價與多表查詢 |
| Stage 3：商業 EDA | 初版完成 | 八張趨勢、品類、付款、評論、配送與地區圖表 |
| Stage 4：延遲預測 | 研究中 | 時間回測、每日提醒預算、五種子穩定性與共同漏報診斷 |
| Stage 5–6：評論預測、RFM | 尚未開始 | 預測低評分、顧客分群 |
| Stage 7：Dashboard | 暫緩 | 先確認延遲模型適用程度 |
| Stage 8–13：推薦系統 | 尚未開始 | Retailrocket 行為、熱門、共現與個人化推薦 |
| Stage 14–15：API、前端 | 尚未開始 | FastAPI、JavaScript／AJAX 串接 |

完整研究歷程與各輪成敗見[專案進度](docs/PROJECT_PROGRESS.md)，全部方法文件見[文件導覽](docs/README.md)。

## 快速開始

以下指令在專案根目錄的 PowerShell 執行。完整版本、資料庫初始化及跨電腦重建方式見[本機環境指南](docs/LOCAL_SETUP.md)。

首次在新電腦使用時，建立 Python 3.12 環境並安裝鎖定套件：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

將 Olist 九份 CSV 放入 `data/raw/olist/`，檔名與用途見[資料說明](data/README.md)。SQL 與前三本 Notebook 需要 MySQL；Stage 4 直接讀 CSV。模型、特徵快取及逐筆分數只保留在本機，下載此 repository 不會同時取得它們。

| 想做什麼 | 入口 |
| --- | --- |
| 建立、啟停 MySQL 或啟動 Jupyter | [本機環境指南](docs/LOCAL_SETUP.md) |
| 按步驟閱讀分析 | [Notebook 導覽](notebooks/README.md) |
| 查詢資料庫 | [SQL 導覽](sql/README.md) |
| 看商業分析圖表 | [Stage 3 成果](docs/STAGE3_BUSINESS_ANALYSIS.md) |
| 訓練或使用第一版延遲模型 | [延遲模型方法與推論](docs/STAGE4_DELAY_PREDICTION.md) |
| 找特定研究的執行方式 | [腳本導覽](scripts/README.md)、[文件導覽](docs/README.md) |
| 查正式數字、規格與圖表 | [報告導覽](reports/README.md) |

已備妥本機環境後，可啟動分析介面：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_jupyter.ps1
```

此腳本會先啟動專案 MySQL。請使用 `Shop (Python 3.12)` kernel；各 Notebook 的資料前提與是否會觸發訓練，先看其[操作說明](notebooks/README.md)。

## 延遲預測目前的結果

研究目標是在**訂單核准時**，從完整核准日批次選出最多 `floor(N × 10%)` 張提醒。未知答案仍先參與名額競爭，再評估當時已知答案；每天各自取整，不借其他日名額。

| 研究主方案指標 | 已檢視的三個開發月 |
| --- | ---: |
| 月份 | 2017-12、2018-02、2018-04 |
| 有效訂單／延遲 | 18,833／1,642 |
| 提醒名額 | 1,845 |
| 抓到延遲 TP／誤報 FP／漏報 FN | 413／1,432／1,229 |
| 開發召回 | 25.15% |
| 最差歷史驗證召回 | 19.63% |

來源為[排序配對焦點報告](reports/stage4/rank_pair_focus.json)及後續各輪的凍結主方案。這些月份已反覆用於設計實驗，不能當作未知測試成績；各歷史月至少 30% 召回的適用要求仍未達成。預設推論仍為原版 Random Forest，研究主方案沒有自動取代它；後續固定預算研究未重評原保留期間。

最新完成[完成歷史對未完成慢件的代表性稽核](docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md)，保留四模型、五種子與 SP→SC 對照。完成窗口與待件的核准時齡、原cohort涵蓋確有差異，但 RJ 待件歷史出現量中，原cohort排除占比在漏報／準時組為16.50%／16.47%，缺口本身未證明能辨識漏報。固定路線、承諾、核准週與支援量，再加核准星期後，二月 RJ 支援充分為0、等待組路線比例僅4張且只在1週；六比例皆無完整跨月依據，因此維持0新增訓練。涵蓋不足不代表訊號無效。

等待 24–72 小時組指核准當下，主賣家歷史未觀測交運待件時齡 p90 在 `(24,72]` 小時；不是本單核准後等待才預測。完整分母、分格結果及限制以實驗文件為準。

下一步先確認是否有核准當下已取得的取消／結案事件及承諾版本資料，再決定一個新訊號。現有 Olist 缺少這些時鐘；若沒有新增來源，就列為待資料，暫停對同三個開發月繼續拆格或加比例。

## 專案結構

```text
shop/
├── data/          # 原始資料、特徵快取；本機保留，內有放置說明
├── docs/          # 設定、進度、方法與各輪實驗
├── notebooks/     # 01 資料、02 SQL、03 EDA、04 延遲預測
├── reports/       # 聚合 JSON 與已產出圖表
├── scripts/       # 啟動、匯入、特徵、訓練、推論與診斷
├── sql/           # 建立資料庫、筆數檢查、商業查詢
├── tests/         # 特徵、時間切分、排名與重現契約測試
├── models/        # 本機模型，Git 忽略
├── .runtime/      # 本機服務、下載、日誌與驗證副本，Git 忽略
├── .venv/         # 專案 Python 套件，Git 忽略
├── requirements.txt
└── requirements-lock.txt
```

實驗程式、報告與輸入有 SHA 綁定，沿用原路徑以利重現。不同輪次可能都稱為「102 欄」，實際內容以當輪特徵白名單與規格為準。

## 驗證與維護

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

測試範圍、分組及 Windows 權限注意事項見[測試說明](tests/README.md)。本輪完整執行867項測試全過，含新增37項；保留原175欄共12,397,700值，重建10個既有事件計數共708,440值，並核對1,281,120既有分數列。正式規格綁定235份來源與3份分析程式；完整方法、重現操作與驗證見[實驗文件](docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md)。新增124個稽核欄只存本機，不進模型白名單。

先前專案清整的範圍與驗證保留在[研究歷程](docs/PROJECT_PROGRESS.md#專案清整)，首頁持續只摘要目前結果及入口。

GitHub 保存程式、未執行的 Notebook、文件、聚合報告與圖表。原始資料、特徵快取、本機模型、連線帳密與執行狀態由 Git 忽略；連線設定範本為 [`scripts/db_config_example.py`](scripts/db_config_example.py)。每次推送需同步更新 README，commit 使用繁體中文，其餘協作規則見 [AGENTS.md](AGENTS.md)。
