# Stage 4：訂單延遲預測

這一階段把 Olist 訂單資料轉成二元分類問題：假設在訂單核准時點 `order_approved_at` 做預測，判斷該訂單是否會晚於承諾的送達日期。每筆樣本是一張訂單，不是一個商品明細或一筆付款。

目前提供離線訓練、評估、模型儲存、命令列推論與多模型時間回測。教學入口是 `notebooks/04_olist_delay_prediction.ipynb`；目前沒有 FastAPI、前端或即時通知服務。原版固定切分結果見 `reports/stage4/metrics.json`，新增開發回測見 `reports/stage4/model_comparison.json`。

減少誤報的新版實驗採 validation 召回至少 30%、提醒量最少的策略，並加入當下已知的配送歷史；使用獨立平衡模式 artifact，詳見 [誤報改善方法與操作](STAGE4_ALERT_OPTIMIZATION.md)。本文件以下保留原版實驗定義。

## 原版固定切分實驗

本機正式訓練使用 seed 42、scikit-learn 1.9.1。原始 99,441 張訂單依序排除 2,963 張非已送達訂單、22 張必要時間缺失、61 張送達早於核准、1 張承諾日期早於核准當日的訂單，保留 **96,394 張、6,532 個延遲正例（6.78%）**。

時間邊界為 2018-03-03 與 2018-05-26。Train 原 57,710 張，排除尚未成熟的 3,565 張後為 54,145 張；validation 原 19,304 張，排除 1,948 張後為 17,356 張；test 保留 19,380 張。三組延遲率分別為 5.06%、8.30%、3.47%，反映期間差異與 purge 的影響。

Validation AP：Dummy 0.0830、Logistic Regression 0.1511、Random Forest 0.1593。因此選定 Random Forest；僅由 validation F1 選出的門檻為 0.4501028038394235。

| Test 指標 | 選定模型 | 全猜準時 |
| --- | ---: | ---: |
| AP | 0.0568 | 0.0347 |
| ROC-AUC | 0.6690 | 0.5000 |
| Precision | 5.69% | 0.00% |
| Recall | 23.07% | 0.00% |
| F1 | 0.0912 | 0.0000 |
| Balanced accuracy | 54.66% | 50.00% |
| Accuracy | 84.07% | 96.53% |

Test 的 672 張延遲訂單中抓到 155 張、漏掉 517 張；另有 2,571 張準時訂單被誤報為延遲。模型的排序能力優於固定基準，但門檻在後期資料的表現較弱。這個成果代表第一版離線流程完成，不能宣稱已適合自動通知或自動處置；本次不根據已讀取的 test 結果重新選模型或門檻。

Validation 抽樣的重要性前五項是顧客州別、運費、跨州比例、預估配送天數與主要賣家州別；這是模型依賴程度，不是因果結論。完整精度、混淆矩陣、參數與來源 hash 以 `metrics.json` 為準。

## 執行方式

在專案根目錄開啟 PowerShell，使用已建置的 `.venv`。這一階段直接讀取 `data/raw/olist/` 的 CSV，不需要啟動 MySQL，也不需要資料庫帳密。

```powershell
.\.venv\Scripts\python.exe scripts\train_delay_model.py
```

訓練指令預設使用 random seed 42；可透過 `--data-dir`、`--output-dir`、`--model-path` 與 `--seed` 指定來源、報告位置、模型位置與種子。若自訂 `--output-dir`，圖表與處理後資料改放該目錄下的 `images/`、`data/`；模型位置仍由 `--model-path` 控制。

預設產出如下：

| 路徑 | 內容 |
| --- | --- |
| `models/olist_delay_model.joblib` | 選定的完整 preprocessing/model pipeline、threshold、特徵白名單與版本資訊；Git 忽略 |
| `reports/stage4/metrics.json` | 資料筆數、時間分界、purge 統計、候選模型的 validation 結果、選模規則、test 指標與來源檔 SHA-256；Git 追蹤 |
| `data/processed/olist_delay_features.csv` | 訂單特徵、label、時間與 split metadata，包含被 purge 的資料列及標記；Git 忽略 |
| `data/processed/olist_delay_test_predictions.csv` | 保留的 test 訂單及預測分數、判斷結果與 threshold；Git 忽略 |
| `reports/images/stage4_*.png` | Validation 模型比較、test PR curve、ROC curve、confusion matrix、validation permutation importance |

重新執行會更新上述產物。要保留不同實驗，請同時指定不同的 `--output-dir` 與 `--model-path`。

## 多模型時間回測

原版 test 已經讀取過，新增模型比較不再用同一個 test 反覆挑冠軍。`compare_delay_models.py` 在原 test 訂單核准起點 2018-05-26 之前的開發期間，對所有模型使用相同的三組時間回測：

| Fold | Train 核准日期 | Validation 核准日期 | 等待驗證標籤 | Evaluation 核准日期 |
| --- | --- | --- | --- | --- |
| 1 | 2017-10-01 以前 | 2017-10 | 2017-11 | 2017-12 |
| 2 | 2017-12-01 以前 | 2017-12 | 2018-01 | 2018-02 |
| 3 | 2018-02-01 以前 | 2018-02 | 2018-03 | 2018-04 |

Train 僅保留在 validation 起點前已送達的結果；validation 僅保留在 evaluation 起點前已送達的結果。等待一個月可減少驗證資料中慢件被排除的問題，但不能完全消除偏差。等待期間的訂單不加入該 fold 訓練。模型只在 train fit，不會合併 validation 重訓。

| Fold | Train 保留筆數／延遲數 | Validation 原筆數／延遲數 | Validation 保留筆數／延遲數 | Evaluation 筆數／延遲數 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 24,804／761 | 4,441／184 | 4,408／155 | 5,675／446 |
| 2 | 33,968／1,134 | 5,675／446 | 5,605／381 | 6,534／890 |
| 3 | 47,770／2,387 | 6,534／890 | 6,239／603 | 6,624／306 |

第三組 validation 即使多等待一個月，仍排除 287／890（32.25%）的原延遲正例；門檻調整存在明顯選擇偏差，不能把這些已成熟訂單當成完整當月樣本。

Evaluation 保留該月全部符合原版資料條件的已送達訂單，以事後完整標籤計分。部分配送結果到原 test 起點以後才可觀察，因此只能說「沒有評分原 test 訂單」，不能說所有結果在 2018-05-26 前已知。這仍是已送達訂單的回溯評估，沒有包含最後取消或未送達者。

| 模型 | 比較目的 |
| --- | --- |
| Dummy most frequent | 全猜準時的參考線，固定門檻 0.5，不參與選模 |
| Logistic Regression | 線性基準，數值欄標準化，使用 balanced class weight |
| Random Forest | 原版森林設定，作為新增模型的共同對照 |
| Extra Trees | 比較更隨機的樹切分能否改善泛化 |
| HistGradientBoosting | scikit-learn 的直方圖梯度提升樹 |
| XGBoost | 比較另一種有正則化的梯度提升實作 |
| LightGBM | 比較葉節點生長的梯度提升實作 |

六種可學習模型使用同一套 21 欄特徵、training-only 補值與 one-hot encoding。HistGradientBoosting 使用 dense 輸入；Logistic Regression 另外標準化。各模型固定參數，不在回測結果出來後搜尋超參數；XGBoost／LightGBM 的 `scale_pos_weight` 只由該 fold 的 train 正負例比例計算。

HistGradientBoosting 設定 `early_stopping=False`，不使用預設的內部驗證切分；參數可參考 [scikit-learn 官方文件](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)。類別權重影響模型分數的解讀，不能把輸出的 `predict_proba` 直接當成已校準的延遲機率，參見 [XGBoost 不平衡資料說明](https://xgboost.readthedocs.io/en/stable/tutorials/param_tuning.html) 與 [LightGBM 權重參數說明](https://lightgbm.readthedocs.io/en/stable/Parameters.html)。

每個 fold 的分類門檻只用該模型的 validation F1 選擇，再固定門檻評估 evaluation。報告按三個 evaluation 月份的 AP 等權平均排序，並列 AP 標準差、每月 AP、正例率、ROC-AUC、F1、precision、recall、confusion matrix、警告與執行時間。三個月的標準差只描述月份差異，不是信賴區間；各 fold 訓練資料重疊，也不能視為獨立實驗。

```powershell
.\.venv\Scripts\python.exe scripts\compare_delay_models.py --n-jobs 4
```

預設產出 `reports/stage4/model_comparison.json` 與 `reports/images/stage4_backtest_model_comparison.png`；自訂 `--output-dir` 時圖表放在該目錄的 `images/`。流程不改原版 `metrics.json`、模型 artifact 或 test 逐筆預測。

這份排名用於後續開發選擇，不是新模型在未知最終測試集上的成績。原版推論目前仍使用 Random Forest；若要替換模型，需先固定候選設定與門檻策略，再用新資料確認泛化，並評估誤報和漏報成本。

### 本次回測結果

Seed 42、每模型最多 4 執行緒；21／21 次 fit 成功，沒有捕捉到模型警告。各 evaluation 月份延遲率分別為 7.86%、13.62%、4.62%。

| 模型 | 平均 AP | AP 標準差 | 平均 ROC-AUC | 平均 F1 | 平均 Recall | 平均 Precision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Logistic Regression | 0.1526 | 0.0411 | 0.6590 | 0.1763 | 54.49% | 13.50% |
| Random Forest | 0.1368 | 0.0517 | 0.6349 | 0.1727 | 63.71% | 10.16% |
| Extra Trees | 0.1361 | 0.0524 | 0.6339 | 0.1667 | 57.10% | 10.36% |
| XGBoost | 0.1358 | 0.0551 | 0.6180 | 0.1338 | 64.13% | 8.21% |
| LightGBM | 0.1337 | 0.0590 | 0.6110 | 0.1439 | 65.64% | 8.48% |
| HistGradientBoosting | 0.1233 | 0.0545 | 0.5950 | 0.1389 | 60.94% | 8.69% |
| Dummy | 0.0870 | 0.0372 | 0.5000 | 0.0000 | 0.00% | 0.00% |

Logistic Regression 的平均 AP、F1、precision 最好，且在 2017-12、2018-04 的 AP 最高；LightGBM 在 2018-02 的 AP 最高（0.2150）。新增的樹模型沒有穩定勝過原版 Random Forest。這只是固定參數下的比較，尚未證明模型差距具有統計顯著性，也未解決低 precision 與月份漂移問題。

## 推論

先完成訓練，再對原始 CSV 中的一張已核准訂單重播預測：

```powershell
.\.venv\Scripts\python.exe scripts\predict_delay.py --order-id e481f51cbdc54678b7cc49136f2d6af7
```

這個模式只用特徵建置需要的資料，不要求實際送達日期或最終 delivered 狀態；但 purchase、approval、estimated delivery 必須存在且時間順序合理。重播既有資料只是操作示範，不能作為新的測試結果。

若已有依本文件定義建立的訂單特徵 CSV，可批次推論：

```powershell
.\.venv\Scripts\python.exe scripts\predict_delay.py --features-csv data\processed\olist_delay_features.csv --output .runtime\stage4\predictions.csv
```

CSV 必須包含下表全部 21 個特徵欄位；缺少整個欄位會報錯。儲存格可有缺值，數值欄無法解析或包含無限值時會轉成缺值，再交給訓練時儲存的 pipeline 處理。額外欄位可以保留，包括 `delayed`、split 與時間 metadata；推論永遠只選取模型 artifact 的特徵白名單，不會把這些額外欄位送進模型。這個批次指令也會預測特徵檔中標記為 purge 的資料列，不能把整份輸出當作 test 評估。

輸出包含 `delay_score`、`threshold`、`predicted_delayed`；輸入有 `order_id` 時會一併保留。判斷規則為 `delay_score >= threshold`。命令列顯示前 10 筆預覽，指定 `--output` 才會另存完整 CSV。也可用 `--model` 指定另一個本專案訓練出的 artifact。

`delay_score` 是分類器的模型分數，目前未做機率校準。分數為 0.7 不能直接解讀成「這張訂單有經驗驗證過的 70% 延遲機率」。

## Label 與資料範圍

預測時點與 label 定義：

```python
prediction_time = order_approved_at
delayed = (
    order_delivered_customer_date.normalize()
    > order_estimated_delivery_date.normalize()
)
```

日期相同視為準時，只有實際送達的日曆日期晚於承諾日期才是正例。Stage 3 用完整 timestamp 比較；Olist 的預計送達時間是當日 `00:00:00`，所以在承諾日白天送達也會被 Stage 3 算成延遲。Stage 4 改用日曆日期後，不能直接把兩階段的延遲率當成同一個指標。

訓練資料只保留最終狀態為 `delivered`，且 purchase、approval、actual delivery、estimated delivery 都存在的訂單，並要求：

- `order_approved_at >= order_purchase_timestamp`。
- `order_delivered_customer_date >= order_approved_at`。
- 承諾送達日期不早於核准當日。

Actual delivery、最終狀態只參與回溯樣本篩選、label 與成熟時間判斷。它們不會進入特徵；出貨里程碑、評論內容與分數、訂單／顧客／商品／賣家 ID 也不作模型特徵。

## 21 個特徵資料字典

來源為六張原始表：`orders`、`customers`、`order_items`、`order_payments`、`products`、`sellers`。商品明細與付款各自先聚合成一張訂單一列，再合併；因此多商品、多筆付款不會互相乘出重複列。特徵建置共用 `scripts/delay_features.py`，訓練與原始訂單推論使用同一組定義。

數值特徵共 17 個：

| 特徵 | 定義與單位 |
| --- | --- |
| `item_count` | 該訂單的商品明細列數；相同商品購買多件仍按明細列計數 |
| `seller_count` | 訂單中不同 `seller_id` 的數量 |
| `product_count` | 訂單中不同 `product_id` 的數量 |
| `total_price` | 所有商品明細 `price` 加總，巴西雷亞爾 BRL |
| `total_freight_value` | 所有商品明細 `freight_value` 加總，BRL |
| `freight_ratio` | `total_freight_value / total_price`；商品總價為 0 時視為缺值 |
| `payment_total` | 所有付款列 `payment_value` 加總，BRL；不強制等於商品加運費總額 |
| `payment_count` | 付款明細列數；整張訂單沒有付款資料時保留缺值 |
| `payment_installments_max` | 該訂單各付款列的最大分期數 |
| `product_weight_g_mean` | 商品明細對應商品重量的平均，公克；多件同商品按明細重複計入 |
| `product_volume_cm3_mean` | 每個明細的長 × 高 × 寬後取平均，立方公分 |
| `estimated_delivery_days` | 承諾送達日期減核准日期，兩者 normalize 後的日數 |
| `approval_wait_hours` | 核准 timestamp 減購買 timestamp，換算小時 |
| `purchase_month` | 下單月份，1 至 12 |
| `purchase_dayofweek` | 下單星期，星期一為 0、星期日為 6 |
| `purchase_hour` | 下單小時，0 至 23 |
| `interstate_item_ratio` | 已知顧客州與賣家州的商品明細中，跨州明細占比，0 至 1 |

類別特徵共 4 個：

| 特徵 | 定義 |
| --- | --- |
| `customer_state` | 顧客州別，使用原始州代碼 |
| `primary_seller_state` | 訂單內 `price` 最高商品明細的賣家州別 |
| `primary_category` | 同一個最高價商品明細的原始 `product_category_name`，使用葡文品類名稱 |
| `payment_type` | `payment_value` 最高付款明細的付款方式 |

最高價商品同價時，取較小的 `order_item_id`；最高額付款同額時，取較小的 `payment_sequential`。這裡的「主要」是單一最高價明細，沒有改成各品類或各賣家總額最大者。

重量與體積平均會略過缺值，全數缺失則仍是缺值；商品品類或州別不明也不強行補成已知值。跨州比例只計算雙方州別都已知的明細，全數不明時為缺值。建置階段不根據全資料的平均數、中位數或常見類別補值，這些統計留到 training pipeline 學習。

## 時間切分與成熟標籤

資料先依 `prediction_time`、`order_id` 排序，再以約 60%／80% 位置所在日期的午夜作 validation／test 起點。分界日整天歸到較晚的區段，同一天的核准訂單不拆到兩側；因此實際比例不會剛好等於 60%／20%／20%。

僅按核准日期切分仍可能使用未來資訊。例如模型在 validation 起始日建立時，前一天核准、兩週後才送達的訂單尚無完整結果。本實作保守地把 `label_available_time` 定為實際送達 timestamp，並排除：

- Train 中 `label_available_time >= validation_start` 的訂單。
- Validation 中 `label_available_time >= test_start` 的訂單。

這個 maturity purge 保證訓練與選模使用的結果，在各自下一段起始時已可觀察。Test 使用保留的歷史完整結果作離線評估，沒有假定 test 的 label 在核准當下已知。

Purge 也會帶來選擇偏差：靠近分界且配送較慢的訂單比較容易被移除，延遲正例可能被移除得更多。正式報告會同時記錄各段 purge 前後筆數及保留樣本的正例率。這不是隨機抽樣，也不代表全部核准訂單在該時點的真實延遲率；後續可比較固定等待期、rolling backtest 或其他處理右設限的方法。

## 訓練、選模與評估

數值欄位使用 training 中位數補值並加入缺值指標；Logistic Regression 另外做標準化。類別欄位使用 training 的最常見值補值，再做 one-hot encoding；稀有類別以 `min_frequency=20` 處理，未知類別採 `handle_unknown="ignore"`。所有可學習的轉換與模型放在同一個 pipeline，只對 purge 後的 train 做 `fit`，validation／test 使用相同已學好的轉換。這符合 scikit-learn 對避免 preprocessing 洩漏的[官方建議](https://scikit-learn.org/stable/common_pitfalls.html)。

訓練會比較 Dummy most-frequent baseline、使用 balanced class weight 的 Logistic Regression，以及使用 balanced-subsample class weight 的 Random Forest。Dummy 僅作參考，不參與模型選擇；在成功訓練的 Logistic Regression 與 Random Forest 中，以 validation 的 Average Precision（AP）選擇模型，同分時依候選順序取第一個。若兩個可選模型都訓練失敗，流程會停止。完整參數、fit warning、失敗狀態與所選模型的 validation AP 是否高於 Dummy 都會記錄在 metrics。

選定模型後，再只使用 validation 分數選出 F1 最高的 threshold；相同 F1 時採較高 threshold。模型不重訓合併 train + validation，pipeline 與 threshold 固定後才評估 test。Threshold 取決於希望如何取捨漏報與誤報，不能從 test 挑出最漂亮的結果；相關原則可參考 scikit-learn 的[threshold 調整說明](https://scikit-learn.org/stable/modules/classification_threshold.html)。

報告包含 AP、ROC-AUC、precision、recall、F1、balanced accuracy、accuracy 與 confusion matrix，並另列 test 全部猜準時的 baseline。AP 會受正例比例影響，應與同一段資料的延遲率一起讀；僅看 accuracy，可能把「全部猜準時」誤認成有效模型。Validation 選模、threshold 調整後的分數屬開發結果，保留的 test 才是最終離線評估。

Permutation importance 在最多 5,000 筆分層抽樣的 validation 資料上計算，重複打亂每個原始特徵 3 次，觀察 AP 的變化。它反映模型對該欄位的依賴，不能解釋為造成延遲的因果效果；相關特徵可能互相分攤重要度。

## 資料假設與限制

- 這是最終已送達訂單的回溯 cohort。訓練篩選依賴最後狀態，對取消、未送達、仍在處理中的訂單沒有完成泛化驗證；CLI 允許有合理 approval 時間的訂單推論，不代表這些族群已被驗證。
- CSV 是資料集匯出快照。付款明細與商品 catalog 沒有逐次更新 timestamp，本版假設相關金額、付款方式、商品屬性與地區資料在 approval 時已知且可取得。缺乏歷史快照，無法從資料本身證明這項假設。
- 時間欄位沒有時區標記，本版直接使用原始資料中的當地日期與時間，不轉換成台灣時間。日曆 label、星期與月份都依同一原始時間基準計算。
- 配送表現與正例比例會隨月份改變，單次歷史切分與三窗口開發回測都不能保證未來期間仍有相同表現；目前沒有線上監測或定期重訓。
- Class weight 與 F1 threshold 是開發設定，尚未對接客服人力、誤報成本或漏報成本；模型分數也尚未校準。
- 商品重量為 0、分期數為 0、付款金額為 0 等原始異常值目前仍保留，沒有宣稱已完成完整商業資料清理。缺值補值解決的是模型輸入格式，不會自動修復來源資料的商業意義。
- 模型使用訂單內聚合與靜態屬性，尚未加入帶有嚴格時點限制的賣家歷史績效、節日、天氣或路線資料。特徵重要度不提供因果結論。
- Artifact 與評估依賴資料版本、程式版本及套件環境；metrics 保存來源 CSV 的 SHA-256、seed 與套件版本。搬到另一個環境時應使用專案的需求鎖定清單，並重新確認訓練與推論契約。
