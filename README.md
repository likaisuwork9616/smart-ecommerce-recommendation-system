# 電商智慧推薦系統

Smart E-Commerce Recommendation System

以 Olist 電商資料練習資料建置、SQL、商業分析、延遲／評論預測與 RFM 顧客分析，再延伸至 Retailrocket 推薦系統、API 與前端。資料環境、SQL 與 EDA 初版已完成；延遲預測與評論低評分預測已整理成離線研究交付，正式適用仍待新資料；RFM 已完成真實資料集與描述統計，分群切點只備妥執行流程、尚未對真實資料執行。推薦系統、API 與前端尚未開始。

## 目前進度

| 階段 | 狀態 | 現有成果 |
| --- | --- | --- |
| Stage 1：資料與環境 | 完成 | Olist 九份 CSV、MySQL、Jupyter 與本機啟動工具 |
| Stage 2：SQL | 完成 | 訂單、品類營收、平均客單價與多表查詢 |
| Stage 3：商業 EDA | 初版完成 | 八張趨勢、品類、付款、評論、配送與地區圖表 |
| Stage 4：延遲預測 | 離線研究交付；待資料 | 每日10%提醒、四設定×五種子對照、模型卡與單日交付驗收；全量名冊、入庫／版本與日結證據待資料 |
| Stage 5：評論低評分預測 | 離線研究交付；待資料 | 四欄基線與三欄消融的開發回測、模型卡；2018年5–9月新驗證窗待資料 |
| Stage 6：RFM | 進行中 | 93,234顧客資料集與真實描述（G1）完成；G2規則切點的執行流程已用合成資料驗收，真實G2／G3未執行 |
| Stage 7：Dashboard | 暫緩 | 先確認延遲模型適用程度 |
| Stage 8–13：推薦系統 | 尚未開始 | Retailrocket 行為、熱門、共現與個人化推薦 |
| Stage 14–15：API、前端 | 尚未開始 | FastAPI、JavaScript／AJAX 串接 |

各輪做了什麼、實際結果與限制見[專案進度](docs/PROJECT_PROGRESS.md)；方法文件依階段整理在[文件導覽](docs/README.md)。

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
| RFM 最新的 G2 執行準備 | [來源、完整同ID、輸出與反讀契約](docs/STAGE6_RFM_RULE_CANDIDATE_EXECUTION.md) |
| 找特定研究的執行方式 | [腳本導覽](scripts/README.md)、[文件導覽](docs/README.md) |
| 查正式數字、規格與圖表 | [報告導覽](reports/README.md) |
| 執行測試 | [測試說明](tests/README.md) |

已備妥本機環境後，可啟動分析介面：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_jupyter.ps1
```

此腳本會先啟動專案 MySQL。請使用 `Shop (Python 3.12)` kernel；各 Notebook 的資料前提與是否會觸發訓練，先看其[操作說明](notebooks/README.md)。

## 研究目前的結果

以下數字都來自已提交的正式報告。三個研究反覆使用的 2017-12、2018-02、2018-04 是**已檢視的開發回測月份**，不能當成未知資料成績。

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

G2 已完成規則候選的合成驗收，以及一次真實執行所需的 57 份來源、完整同ID、輸出與反讀契約；準備查核的三套合成測試共 68 項全過（75.543972 秒，見[準備查核報告](reports/stage6/rfm_rule_candidate_execution_preflight.json)）。真實 G2 尚未執行，沒有真實切點、分群、訓練或 Dashboard。下一步決定是否依固定入口執行一次真實 G2，通過與否都不改規則，也不自動進 G3。不需原始資料即可重跑合成測試：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_rule_candidate_sources tests.test_rfm_rule_candidate_outputs tests.test_prepare_rfm_rule_candidate -q
```

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

本次為第二次專案清整，只整理文件：首頁回到現況摘要，Stage 5、6 逐輪紀錄改成[專案進度](docs/PROJECT_PROGRESS.md)的歷程表，並將文件、報告、腳本、測試、Notebook 與資料導覽依階段重排、修正過時描述。實驗程式、正式 JSON、圖表與 Notebook 沒有修改，也沒有新增訓練或研究結果。清整後 1,058 個本機連結全部有效、207 個 SHA 綁定檔前後一致，全專案測試 1,764 項全過（605.317 秒）；完整紀錄見[專案清整](docs/PROJECT_PROGRESS.md#專案清整)。

GitHub 保存程式、未執行的 Notebook、文件、聚合報告與圖表。原始資料、特徵快取、本機模型、連線帳密與執行狀態由 Git 忽略；連線設定範本為 [`scripts/db_config_example.py`](scripts/db_config_example.py)。每次推送需同步更新 README，commit 使用繁體中文，其餘協作規則見 [AGENTS.md](AGENTS.md)。
