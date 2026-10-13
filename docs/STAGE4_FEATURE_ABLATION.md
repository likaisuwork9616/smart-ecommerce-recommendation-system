# Stage 4：地理與負載交互消融

本輪將前輪一起加入的特徵拆開，測試地理組與負載交互組各自的增量，以及搭配後是否改變模型的每日前段排名。固定每日完整批次最多 10%、同一延遲標籤、相同訓練訂單與模型參數。前輪完整結果保留於 [特徵工程實驗](STAGE4_FEATURE_ENGINEERING.md)。

## 實際結果

96 個新月份版本已完成，全部 fit warnings 為空。以下來自 [正式報告](../reports/stage4/feature_ablation.json)，不是未知資料測試成績；[執行前規格](../reports/stage4/feature_ablation_specification.json)保留候選、參數、群組與來源。

| 同家族合併開發召回 | 基準 60 | 地理 G：72 | 負載 L：65 | G+L：77 | 完整 83 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Logistic | 21.80% | 21.44% | 22.05% | 21.86% | 21.62% |
| Random Forest | 22.78% | 21.92% | 22.29% | 21.74% | 19.37% |
| LightGBM | 16.75% | 15.71% | 15.83% | 14.13% | 14.43% |
| XGBoost | 16.87% | 15.71% | 16.75% | 14.86% | 16.02% |

三個開發月合計 18,833 單、1,642 張延遲，固定 1,845 個提醒名額，約 9.80%。G 單獨加入時四家族合併召回都下降；L 單獨加入只有 Logistic 小幅提高，其他三家族下降。G 加到已有 L 的模型也在四家族合併結果下降，這輪沒有地理組穩定獲益的證據。

| Logistic 負載組成對月份 | 基準 TP／延遲 | 基準召回 | L 組 TP／延遲 | L 組召回 |
| --- | ---: | ---: | ---: | ---: |
| 2017-12 | 84／446 | 18.83% | 86／446 | 19.28% |
| 2018-02 | 178／890 | 20.00% | 181／890 | 20.34% |
| 2018-04 | 96／306 | 31.37% | 95／306 | 31.05% |

Logistic 加 L 的 TP 358 → 362，FP 1,487 → 1,483，FN 1,284 → 1,280；recall 21.80% → 22.05%，增加 0.24 個百分點。最差歷史召回 16.24% → 16.59%，仍低於 30%，且四月有下降，不能稱為跨月穩定改善。

| G 組月份差異：基準 → 加 G | 2017-12 | 2018-02 | 2018-04 |
| --- | --- | --- | --- |
| Logistic | 18.83% → 19.06% | 20.00% → 19.10% | 31.37% → 31.70% |
| Random Forest | 17.71% → 17.26% | 23.93% → 22.13% | 26.80% → 28.10% |
| LightGBM | 14.57% → 16.82% | 15.06% → 12.70% | 24.84% → 22.88% |
| XGBoost | 13.68% → 14.13% | 16.40% → 13.15% | 22.88% → 25.49% |

2018-02 的 G 組四家族都低於基準；其他月份部分模型增加，不能只展示增加的月份。這些差異描述目前樣本與固定訓練，不證明地理本身對真實配送沒有作用。

| G+L 存在時再加 O | 77 欄 TP | 83 欄 TP | 召回差（百分點） |
| --- | ---: | ---: | ---: |
| Logistic | 359 | 355 | −0.24 |
| Random Forest | 357 | 318 | −2.38 |
| LightGBM | 232 | 237 | +0.30 |
| XGBoost | 244 | 263 | +1.16 |

RF 的下降在加入 O 後較大，但 LGB／XGB 反而提高。不能直接將六個 O 欄位全部標成無效；這個對照也沒有指出是哪一欄造成差異。

| 歷史選模群組 | TP | FP | FN | 開發召回 | 最差歷史召回 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 前輪 31 候選 | 359 | 1,486 | 1,283 | 21.86% | 19.17% |
| 同訓練 60 欄 | 358 | 1,487 | 1,284 | 21.80% | 16.24% |
| 完整 83 欄 | 295 | 1,550 | 1,347 | 17.97% | 17.52% |
| 只加 G | 342 | 1,503 | 1,300 | 20.83% | 15.89% |
| 只加 L | 362 | 1,483 | 1,280 | 22.05% | 16.59% |
| G+L | 335 | 1,510 | 1,307 | 20.40% | 16.76% |
| 主方案：全部 43 候選 | 359 | 1,486 | 1,283 | 21.86% | 19.17% |

主方案三個 E 月仍選 `xgboost_engineering_geo`、`random_forest_route`、`random_forest_route`，開發召回依序為 15.70%、25.06%、21.57%。主方案與漏報分組完全維持前輪結果，三個 fold 的歷史最低召回都未達 30%；只加 L 的合併開發召回較高，但歷史下限較低，不能據此事後替換主方案。

本輪沒有自動換模型或新增圖表。後續若沿 Logistic 負載組繼續研究，仍須先固定新比較規格、確認最差歷史月份，並將已看過的 E 月繼續標為開發資料。

## 特徵分組

| 組別 | 欄數 | 欄位 |
| --- | ---: | --- |
| G：地理 | 12 | 9 個郵區座標／距離欄位，以及距離／承諾天數、承諾天數／百公里、運費／距離 |
| L：負載交互 | 5 | 賣家／路線待件對完成件壓力，以及賣家／路線／全域逾期待件占比 |
| O：其他交互 | 6 | 重量／體積近似、每品項運費、每品項價格、核准星期、核准小時、承諾星期 |

三組互不重疊，恰好涵蓋前輪新增的 23 欄。精確公式沿用前輪，沒有新估算公式、沒有跨期目標編碼。所有留下的欄位保留在前輪 83 欄中的相對順序。

| 比較格 | 特徵數 | 訓練安排 |
| --- | ---: | --- |
| 既有基準 | 60 | 重用前輪同模型版本 |
| 基準＋G | 72 | 四家族各新增八個月版本 |
| 基準＋L | 65 | 四家族各新增八個月版本 |
| 基準＋G＋L | 77 | 四家族各新增八個月版本 |
| 基準＋G＋L＋O | 83 | 重用前輪完整版本 |

60 欄基準本來就有原始待件數、完成歷史、路線及 ZIP3。拿掉 L 只移除五個新比例，並非拿掉所有負載資訊；拿掉 G 也不等於完全沒有地區資訊。只加 L 的原始資料推論路徑不需要 geolocation。

這是以基準為背景的 G／L 兩因子對照：G−基準、L−基準、G+L−G、G+L−L。83−77 則是在 G+L 已存在時加入 O 的條件增量，不能解讀成 O 單獨的效果；本輪沒有 O-only 格，也沒有逐欄消融。召回差值與非加總差值是固定模型訓練後的描述，不是物流因果效應。

## 訓練與選模

Logistic、Random Forest、LightGBM、XGBoost 沿用前輪完全相同的家族參數與種子 42；數值補值、標準化和類別編碼只 fit 訓練資料。每月 M 使用核准 `< M`，且 `min(實際送達, 承諾日次日午夜) < M` 的既有有效最終送達 cohort，等待 0 天；訓練列依核准時間、訂單 ID 排序。保留原始實際送達欄位，驗證成熟仍依實際送達時間。

八個模型月份是 2017-07、08、09、10、11、12、2018-02、04。三個開發 E 月的歷史選模月份保持不變：

| 開發 E | 歷史 OOT 月份 |
| --- | --- |
| 2017-12 | 2017-07、08、09 |
| 2018-02 | 2017-09、10、11 |
| 2018-04 | 2017-10、11、12 |

新增 12 候選 × 8 月 = 96 fit。重用前輪 31 個非 dispatch 候選 × 8 月 = 248 版本，合計 344 版本、43 候選。出貨期限候選本輪不參與，前輪敏感度報告保留。

每日先在完整研究評分 cohort 取 `floor(0.10 × 當日筆數)`，未知結果仍競爭名額；再只以實際送達 `< E` 的結果計算歷史指標。同分依訂單 ID 升冪。選模依三歷史月最差召回、合計 TP、合併 AP、固定候選順序；選定後才計算 E 指標。

七個選組為前輪 31 候選、同訓練 60 欄、完整 83 欄、只 G、只 L、G+L，以及事前指定主方案 `primary_without_dispatch`（全部 43 候選）。每個歷史月召回都至少 30% 才通過適用門檻；不能以開發成績最高的固定候選替代主方案。

本輪規格在新模型 fit 前寫入 `feature_ablation_specification.json`。但整體設計已受反覆檢視的 E 月啟發，所有 E 仍是開發回測，不是獨立測試。原 2018-05-26 起保留期間不重新評分。地理參考無版本時間、原始事件缺入庫時間、最終已送達 cohort 的事後篩選與取消時間缺失等限制都保留。

## 重現與推論

從專案根目錄，沿用 `.venv/`：

```powershell
.\.venv\Scripts\python.exe scripts\ablate_delay_features.py --n-jobs 4
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

本輪先驗證七來源雜湊、前輪特徵與分數 SHA-256；重播既有月份模型並核對舊分數、切分與來源。完整 91 欄本機特徵 CSV 保持原檔，只按白名單選出 72／65／77 欄；其中出貨期限、其他交互與結果欄位不會混入模型。

| 產物 | 路徑 | Git |
| --- | --- | --- |
| 聚合結果 | `reports/stage4/feature_ablation.json` | 保留 |
| 執行前規格 | `reports/stage4/feature_ablation_specification.json` | 保留 |
| 來源特徵 | `data/processed/olist_delay_engineering_features.csv` | 忽略，原檔重用 |
| 逐筆分數 | `data/processed/olist_delay_ablation_scores.csv` | 忽略 |
| 新月份模型 | `models/research/ablation_versions/` | 忽略 |
| 主方案研究模型 | `models/research/olist_delay_feature_ablation_YYYY-MM.joblib` | 忽略 |

完整日批次推論需給 `order_id`、`prediction_time` 及 artifact 白名單特徵，不需要提供結果或訓練答案時間。以下在 PowerShell 從既有特徵 CSV 擷取完整四月研究 cohort，並移除結果欄位：

```powershell
@'
from pathlib import Path
import joblib
import pandas as pd
artifact = joblib.load('models/research/olist_delay_feature_ablation_2018-04.joblib')
features = pd.read_csv('data/processed/olist_delay_engineering_features.csv',
    float_precision='round_trip', dtype={c: object for c in artifact['categorical_features']})
month = pd.to_datetime(features.prediction_time).dt.strftime('%Y-%m')
columns = ['order_id', 'prediction_time'] + artifact['feature_names']
Path('.runtime/verification').mkdir(parents=True, exist_ok=True)
features.loc[month.eq('2018-04'), columns].to_csv('.runtime/verification/ablation_april_batch.csv', index=False)
'@ | .\.venv\Scripts\python.exe -
.\.venv\Scripts\python.exe scripts\predict_delay.py --model models\research\olist_delay_feature_ablation_2018-04.joblib --features-csv .runtime\verification\ablation_april_batch.csv --complete-daily-batches --output .runtime\verification\ablation_april_predictions.csv
```

完整批次旗標由呼叫端負責保證，程式不能從片段 CSV 證明沒有漏單；單筆呼叫與缺少聲明的批次會拒絕。歷史研究分母仍是有效且最終送達的 cohort，不等於所有原始核准訂單。新增分數沒有另作機率校準，不能當成已驗證延遲機率。

預設模型不自動替換，Dashboard 與新圖表繼續暫緩。

## 實際驗證

- 完整 251 項測試通過，Notebook 22 個程式區塊執行通過；提交 Notebook 無輸出。本輪新增區塊只讀報告。
- 負載推論從六份原始表重建，不需要地理資料。96,394 筆 × 65 欄共 6,265,610 個值與凍結特徵檔相同；五個負載比例另以 NumPy 獨立計算，481,970 個值全部相符。
- 獨立重載 344 個版本，依原始時間邊界重算訓練分割、16,200 個補值中位數、1,833,047 筆月份／候選分數、2,754,408 列匯出、516 組指標與每日容量、21 組歷史選模、50 列摘要、三份研究 artifact、2,571 個漏報分組；五格同家族切分與參數各核對 128 組等式。
- RF 的 72／65／77 欄模型各對四月 6,624 單執行真實 CLI，皆提醒 650 單，分數及提醒集合與報告一致；1,710 張顧客 ZIP 前導零保留。輸入不含結果欄位，缺少完整批次聲明或使用單筆呼叫皆拒絕。
- 本輪開始前 347 份模型、報告與圖檔 SHA-256 不變。19 份 JSON 都符合嚴格 JSON，62 個 README／本文件連結可解析。

分數列數含不同候選與 fold 的重複訂單，不能當成獨立樣本數。凍結的來源特徵檔未修改，執行證明、模型、資料與逐筆分數保留於 Git 忽略路徑；Git 只保留程式、文件與聚合報告。
