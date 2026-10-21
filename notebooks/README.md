# Notebook使用說明

這裡保留四本教學Notebook。完整安裝與資料庫設定見[本機建置](../docs/LOCAL_SETUP.md)，實驗結論以[研究文件](../docs/README.md)及[聚合報告](../reports/README.md)為準。Notebook展示研究流程，不會自動把歷史開發結果變成新資料成績。

## 現有檔案與前提

| Notebook | 內容與程式區塊數 | 執行前提 |
| --- | --- | --- |
| [01_olist_data_overview.ipynb](01_olist_data_overview.ipynb) | 原始CSV概覽、MySQL連線檢查；4個程式區塊 | `data/raw/olist/` 的Olist CSV、本機 `scripts/db_config.py`、已啟動的MySQL |
| [02_olist_sql_analysis.ipynb](02_olist_sql_analysis.ipynb) | SQL查詢與DataFrame示範；2個程式區塊 | 已匯入的 `olist_ecommerce` 資料庫及本機連線設定 |
| [03_olist_business_analysis.ipynb](03_olist_business_analysis.ipynb) | 訂單、營收、品類、付款、評論、配送與地區EDA；11個程式區塊 | 相同MySQL資料表；直接執行會將圖存入 `reports/images/` |
| [04_olist_delay_prediction.ipynb](04_olist_delay_prediction.ipynb) | 核准時預測、時間切分、推論及歷史研究摘要；42個程式區塊、共85個cell | 本機Olist CSV、`.venv`套件、相關模型與報告；不需要MySQL |

提交版清除執行輸出與執行次數；本機執行副本放 `.runtime/verification/`。四本kernel顯示名稱統一為 `Shop (Python 3.12)`，kernel名稱為 `.venv`；執行前仍須確認它指向本專案的解譯器。

## 開啟與驗證

從專案根目錄的PowerShell執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_jupyter.ps1
```

腳本先啟動本機MySQL，再開啟JupyterLab，根目錄設為 `notebooks/`。01–03使用 `Path.cwd().parent` 找專案根目錄，需從此目錄執行；04也接受從專案根目錄執行。Jupyter關閉後，MySQL仍會運行，啟停方式見建置指南。

已有本機資料庫與kernel時，可執行：

```powershell
.\.venv\Scripts\python.exe scripts\verify_environment.py
.\.venv\Scripts\python.exe scripts\verify_environment.py --execute-notebooks
```

第一個命令檢查Python、套件及9張資料表筆數；第二個額外執行**01–03**的副本，將輸出及EDA圖表改存 `.runtime/verification/`，不覆寫提交的Notebook或圖表。這個驗證入口沒有執行04，也不代表全部Stage 4研究已重現。

## 執行04之前

04預設 `RUN_TRAINING = False`，但如果 `models/olist_delay_model.joblib` 或 `reports/stage4/metrics.json` 缺少，仍會呼叫 `train_delay_model.py` 建立原版模型及報告。因此整本執行可能觸發訓練與覆寫原版產物；只有希望建立該輪成果時才執行相關區塊。閱讀既有研究時，可直接開啟文件與JSON。

04後半段主要讀取已存在的報告，缺少報告時會提示對應CLI。現有摘要止於[五種子colsample比較](../docs/STAGE4_AGE_COLSAMPLE.md)；其後的[四模型每日邊界](../docs/STAGE4_FOUR_MODEL_BOUNDARY.md)、[成熟歷史訊號稽核](../docs/STAGE4_MATURE_HISTORY_SIGNAL_AUDIT.md)、[固定條件比較](../docs/STAGE4_CONDITIONAL_MATURE_SIGNALS.md)、[完成歷史代表性](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md)及[事件與承諾版本來源](../docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md)，請從各輪文件及報告閱讀。

原始CSV、特徵快取、逐筆分數、模型與執行證明都保留在本機忽略路徑。新的Git checkout不會自帶這些資料；不要為了讓Notebook全部通過，就改寫凍結報告或重新評估原保留測試。研究操作與來源保護見[程式索引](../scripts/README.md)。

現有成果的適用範圍、五種子與主方案區別、可交付項目及下一步見[模型卡](../docs/STAGE4_MODEL_APPLICABILITY.md)。模型卡整理沒有新增Notebook cell、訓練或評分；四本Notebook並非每日10%生產通知系統。

最新[單日離線交付驗收](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md)以獨立CLI只讀凍結分數，沒有執行Notebook、模型訓練或新預測。請勿為重現交付驗收而整本執行04。

Stage 4目前維持待資料。Stage 5在[H60資料集](../docs/STAGE5_REVIEW_DATASET_SPEC.md)、[最小基線規格](../docs/STAGE5_REVIEW_BASELINE_SPEC.md)及[合成洩漏測試](../docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md)後，以獨立CLI執行[四欄離線最小基線](../docs/STAGE5_REVIEW_OFFLINE_BASELINE.md)。該入口會在來源守門通過後用真實資料訓練與做開發回測；沒有新增或執行Notebook，也沒有Dashboard。不要為了補Stage 5就執行04的延遲訓練。

已依[只移除購買月份的消融規格](../docs/STAGE5_REVIEW_MONTH_ABLATION_SPEC.md)完成[三欄builder／pipeline及洩漏驗證](../docs/STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md)，[執行準備](../docs/STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md)再串接來源／完整角色及四欄凍結分數。該輪只核metadata與配對契約，0fit。最新[三欄正式入口與私有writer](../docs/STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md)已另行實作、綁定並做合成驗證；真實訓練仍待決定，沒有Notebook或Dashboard改動，不能用四欄入口代替。
