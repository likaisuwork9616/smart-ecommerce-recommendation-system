# Stage 4：Logistic 負載組正則化

本輪固定 65 欄負載組，測試 L2 正則化強度是否能改善每日前 10% 訂單的延遲辨識。上一輪只加負載交互的 Logistic，在三個開發月合併召回為 22.05%，最差歷史月為 16.59%；這是研究方向的依據，不能當成本輪結果。前輪完整對照保留於 [地理與負載交互消融](STAGE4_FEATURE_ABLATION.md)。

本輪 56 個新月份版本已完成，全部收斂，fit warnings 為空。以下結果來自 [正式報告](../reports/stage4/logistic_regularization.json)，[執行前規格](../reports/stage4/logistic_regularization_specification.json)保留候選、參數、選模群組與來源。這些數字都是開發回測，不是未知資料成績。

## 實際結果

固定每日完整批次最多 10%，三個開發月共 18,833 單、1,642 張延遲，每格都使用相同的 1,845 個提醒名額。先看每個固定 C 在三個開發月的合併結果：

| 固定 C | 開發 TP | 合併開發召回 | 最差歷史月召回 |
| --- | ---: | ---: | ---: |
| 0.01 | 441 | 26.86% | 14.17% |
| 0.03 | 418 | 25.46% | 15.00% |
| 0.1 | 391 | 23.81% | 15.83% |
| 0.3 | 378 | 23.02% | 17.05% |
| 1 | 362 | 22.05% | 16.59% |
| 3 | 343 | 20.89% | 16.01% |
| 10 | 344 | 20.95% | 15.31% |

較強正則化在這批開發月份的合併召回較好。固定 C=0.01 相對 C=1 多抓 79 張延遲、增加 4.81 個百分點；但它的最差歷史召回反而較低，不能因開發成績最高就指定所有月份採用 C=0.01。固定 C=0.3 的歷史下限在七格中最高，仍只有 17.05%，也未達 30%。

| 歷史選模群組 | 三個 E 月選擇 | TP | FP | FN | 合併開發召回 | 最差歷史召回 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 前輪 43 候選 | XGB83／RF 路線／RF 路線 | 359 | 1,486 | 1,283 | 21.86% | 19.17% |
| 本輪七個 Logistic C | C=1／0.01／0.01 | 436 | 1,409 | 1,206 | 26.55% | 19.17% |
| 主方案：全部 50 候選 | XGB83／C=0.01／C=0.01 | 420 | 1,425 | 1,222 | 25.58% | 19.17% |

表中順序為 2017-12、2018-02、2018-04；XGB83 是前輪 `xgboost_engineering_geo` 完整 83 欄模型。主方案召回由 21.86% 提高到 25.58%，增加 3.71 個百分點；相同提醒量下多抓 61 張延遲，FP 與 FN 各減少 61。七個 Logistic 的歷史選模結果為 26.55%，固定 C=0.01 的描述結果為 26.86%，兩者都不是主方案的 25.58%，不能混用。

| 主方案開發 E 月 | 歷史選出的模型 | 三歷史月最低召回 | 開發 TP／延遲 | 開發召回 |
| --- | --- | ---: | ---: | ---: |
| 2017-12 | XGB83 | 19.17% | 70／446 | 15.70% |
| 2018-02 | Logistic 負載 C=0.01 | 21.35% | 232／890 | 26.07% |
| 2018-04 | Logistic 負載 C=0.01 | 20.36% | 118／306 | 38.56% |

十二月 XGB83 與新 C=1 的最差歷史召回同為 19.17%，下一個選模條件的歷史合計 TP 分別為 95、86，因此主方案選 XGB83。這個選擇沒有使用十二月開發結果；不能看到 C=1 的十二月開發召回較高，就事後更換主方案。三個 fold 的歷史下限都未達 30%，四月開發召回超過 30% 也不能視為適用門檻已通過。

路線表現仍有取捨，以下比較前輪與本輪主方案的合併開發診斷：

| 路線 | FN：前輪 → 本輪 | FP：前輪 → 本輪 |
| --- | ---: | ---: |
| SP→RJ | 189 → 220 | 547 → 396 |
| SP→SP | 219 → 214 | 295 → 329 |

SP→RJ 提醒減少時，誤報下降但漏報增加；SP→SP 漏報略減但誤報增加。整體指標改善不代表每條路線都改善，還需沿月份、路線及承諾天數確認穩定程度。本輪不自動替換預設模型，Dashboard 繼續暫緩。

56 個新版本實際迭代為 54–834 次，均低於統一上限 10000。八個月份的新 C=1 與舊 C=1 分數、係數、截距最大絕對差皆為 0，實際迭代次數也相同；因此這輪 C 比較沒有被不同迭代上限造成的基準變動干擾。這是數值重現證據，不是額外效能分數。

## 比較規格

`C` 是正則化強度的倒數，越小表示懲罰越強；它不是提醒門檻。本機 `.venv/` 的 scikit-learn `LogisticRegression` 文件確認 `l1_ratio=0` 為純 L2，使用 `lbfgs`。本輪不改成 L1、Elastic-Net 或其他 solver。

| 固定候選順序 | C | 相對於 C=1 |
| --- | ---: | --- |
| 1 | 0.01 | 較強正則化 |
| 2 | 0.03 | 較強正則化 |
| 3 | 0.1 | 較強正則化 |
| 4 | 0.3 | 較強正則化 |
| 5 | 1 | 既有強度，重新訓練核對 |
| 6 | 3 | 較弱正則化 |
| 7 | 10 | 較弱正則化 |

所有七格統一 `max_iter=10000`；前輪 C=1 使用 2000 且已收斂，因此這項變更用於給各格足夠的求解次數，不是另一個調參軸。每月核對新 C=1 與前輪 C=1 的分數、排序及提醒結果，確認增大迭代上限沒有改變已收斂的基準。模型紀錄 `n_iter_`、係數 L2 範數及 fit warnings，供收斂與數值檢查；係數範數和迭代次數不參與選模。未收斂的版本停止流程，不能帶入效能比較或歷史選模。

其餘設定全部相同：`class_weight='balanced'`、`tol=1e-4`、種子 42、原始列排序、每月訓練訂單 ID，以及 65 欄白名單。數值補值中位數、缺值指標、標準化及類別編碼只 fit 訓練資料；類別使用最常見值補值與 `OneHotEncoder(handle_unknown='ignore', min_frequency=20)`。OHE 展開後的維度可隨月份改變，65 欄指的是原始輸入欄數。

65 欄等於前輪 60 欄基準加上五個負載比例：賣家／路線待件對完成件壓力，以及賣家／路線／全域逾期待件占比。沒有新增地理、出貨期限或其他交互特徵，也不修改公式。前輪 60 欄本來就含原始負載、路線、ZIP3 與完成歷史，因此本輪不是「只有五個負載欄位」的模型。

## 時間切分與提醒預算

每月 M 依 `deadline_wait0` 訓練：核准時間 `< M`，且 `min(實際送達, 承諾日次日午夜) < M`，不另加等待天數。訓練列依核准時間、訂單 ID 穩定排序，七格使用相同訓練列。實際送達時間保留；歷史驗證成熟度仍以實際送達 `< E` 判斷，不能改用訓練用的較早答案時間。

| 開發 E 月 | 歷史 OOT 選模月份 |
| --- | --- |
| 2017-12 | 2017-07、08、09 |
| 2018-02 | 2017-09、10、11 |
| 2018-04 | 2017-10、11、12 |

七個強度各訓練八個月份版本（2017-07、08、09、10、11、12、2018-02、04），實際新增 56 fit；重播前輪 43 候選的 344 個版本，完整比較為 50 候選、400 個月份版本。這些版本共用研究 cohort，不能當成 400 份獨立資料。

每日先依完整研究評分 cohort 取 `floor(0.10 × 當日筆數)`；當時尚未取得結果的訂單仍競爭名額，之後才以已成熟的結果計算歷史指標。同分依訂單 ID 升冪。不能先移除慢件再分配提醒，不能用全月 10% 代替每日上限。

| 事前固定的選模群組 | 候選數 | 用途 |
| --- | ---: | --- |
| `previous_candidates` | 43 | 重現前輪主方案 |
| `logistic_load_regularization` | 7 | 僅比較這輪 C 強度 |
| `primary_without_dispatch` | 50 | 本輪主方案 |

每個 E 各自只用三個歷史月選模：先比較最差月份召回，再比較合計 TP、合併 AP，最後依固定候選順序處理同分。選定後才看 E 月的開發回測。C=1 新舊版本都留在完整比較中供重現核對；重複實驗不增加獨立樣本數。

適用門檻仍是三個歷史月各自召回至少 30%。不能用合併召回掩蓋最差月份，不能因某個 C 在已看過的 E 月最好就替換歷史選模結果。未達門檻時不自動換預設模型，Dashboard 與新圖表繼續暫緩。

規格在新 fit 前寫入 `logistic_regularization_specification.json`。但研究設計已受反覆檢視的 E 月啟發，三個 E 都是開發回測，不能稱為獨立測試。原 2018-05-26 起的保留期間不重新評分。最終已送達 cohort 的事後篩選、事件缺入庫時間、取消時間缺失等限制沿用前輪，不能把目前結果直接外推到全部原始核准訂單。

## 重現與推論

從專案根目錄，沿用 `.venv/`：

```powershell
.\.venv\Scripts\python.exe scripts\tune_logistic_regularization.py --n-jobs 4
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

流程驗證凍結特徵、前輪模型／報告／分數與來源雜湊，並核對既有分數與切分。完整 91 欄本機特徵 CSV 重用原檔，只按白名單選取負載組的 65 欄；結果、訓練答案時間、地理及出貨期限欄位不進入新模型。凍結特徵檔的來源追溯仍保留前輪七來源紀錄；65 欄負載組從六份原始表重建推論特徵時不需要 geolocation。

| 產物 | 路徑 | Git |
| --- | --- | --- |
| 聚合結果 | `reports/stage4/logistic_regularization.json` | 保留 |
| 執行前規格 | `reports/stage4/logistic_regularization_specification.json` | 保留 |
| 凍結來源特徵 | `data/processed/olist_delay_engineering_features.csv` | 忽略，重用原檔 |
| 逐筆分數 | `data/processed/olist_delay_logistic_regularization_scores.csv` | 忽略 |
| 新月份模型 | `models/research/regularization_versions/` | 忽略 |
| 主方案研究模型 | `models/research/olist_delay_logistic_regularization_YYYY-MM.joblib` | 忽略 |

主方案 artifact 可能仍選既有模型，因此推論應使用 artifact 自帶的白名單，不應固定假設主方案也是 65 欄。完整日批次輸入只需 `order_id`、`prediction_time` 與 artifact 特徵，不需要提供結果或訓練答案時間。以下從凍結特徵檔擷取完整四月研究 cohort：

```powershell
@'
from pathlib import Path
import joblib
import pandas as pd
artifact = joblib.load('models/research/olist_delay_logistic_regularization_2018-04.joblib')
features = pd.read_csv('data/processed/olist_delay_engineering_features.csv',
    float_precision='round_trip', dtype={c: object for c in artifact['categorical_features']})
month = pd.to_datetime(features.prediction_time).dt.strftime('%Y-%m')
columns = ['order_id', 'prediction_time'] + artifact['feature_names']
Path('.runtime/verification').mkdir(parents=True, exist_ok=True)
features.loc[month.eq('2018-04'), columns].to_csv('.runtime/verification/regularization_april_batch.csv', index=False)
'@ | .\.venv\Scripts\python.exe -
.\.venv\Scripts\python.exe scripts\predict_delay.py --model models\research\olist_delay_logistic_regularization_2018-04.joblib --features-csv .runtime\verification\regularization_april_batch.csv --complete-daily-batches --output .runtime\verification\regularization_april_predictions.csv
```

完整批次旗標由呼叫端保證；程式不能從片段 CSV 證明沒有漏單。單筆呼叫或缺少完整批次聲明的批次會拒絕。研究分母仍是有效且最終送達的 cohort。本輪新模型沒有另作機率校準，分數不能當成已驗證延遲機率。

## 獨立重算與發布檢查

已獨立重載 400 個版本，依原始時間邊界重算切分、19,392 個訓練補值中位數、2,131,450 筆月份／候選分數、3,202,800 列匯出、600 組每日容量與指標、9 組歷史選模、53 列摘要、7 條 C 對照、三份研究 artifact 及 2,571 個漏報分組，另核對訓練標準化統計，全部相符。

56 個新版本的實際迭代、係數範數與截距均由 pipeline 重新核對。八個月份 C=1 的完整每日排名、提醒集合、係數、截距及迭代與前輪一致，三個 fold 的整份 C=1 驗證／開發指標也相同。這些控制確認本輪效果來自不同 C 訓練出的模型，並非增大求解上限或更換資料。

本輪開始前 448 份模型、報告及圖檔的 SHA-256 全數不變；21 份嚴格 JSON 與 65 個 README／本文件連結檢查通過。分數列數含模型與不同 fold 的重複訂單，不代表獨立樣本數。執行證明、原始資料、模型與逐筆分數保留於 Git 忽略路徑；提交 Notebook 不保留執行輸出，沒有新增圖表。

## 實際驗證

- 完整 259 項測試通過，Notebook 23 個程式區塊執行通過；提交 Notebook 無輸出。本輪新增區塊只讀聚合報告，不啟動 fit 或新增圖表。
- C=0.01、1、10 的 65 欄模型各對完整四月 6,624 單執行真實 CLI，皆提醒 650 單，分數與提醒集合相符，1,710 張顧客 ZIP 前導零保留。這是同期間推論重播，不是新的評估期間。
- CLI 輸入不含結果欄位；缺少完整批次聲明及使用單筆呼叫均拒絕。
- 新 C=1 八個月份均重現舊 C=1 的分數、係數、截距及迭代次數；全部 56 個新 fit 收斂且沒有 fit warnings。

模型、資料、逐筆分數與執行證明保留在 Git 忽略路徑；Git 只保留程式、文件與聚合報告。逐筆分數包含候選與 fold 重複訂單，不能用匯出列數代替獨立樣本數。
