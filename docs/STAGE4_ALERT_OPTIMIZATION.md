# Stage 4：減少延遲誤報

使用者選定的取捨是：**在 validation 至少抓到 30% 的延遲訂單，再盡量減少提醒量**。這項限制只用於驗證資料選擇模型與門檻，不是後續月份召回率的保證。

本次最終仍選中 **原特徵 Random Forest**，新門檻約為 **0.453508**（完整精度以 artifact 為準）。新增歷史特徵未勝出，不納入這次平衡 artifact。平衡模式須明確指定 `--profile balanced`；原版預設保留。

## 本次結果與取捨

最終原切分 validation 的召回率為 **30.05%（433／1,441）**，符合指定目標；提醒量由原 F1 的 2,281 降至 2,132。新模型與原模型的分數排序相同，本次可採用的改善來自門檻策略。

已檢視保留資料的回溯診斷（同 19,380 張訂單）：

| 指標 | 原版 RF／F1 | 平衡模式 RF |
| --- | ---: | ---: |
| 門檻 | 0.450103 | 0.453508 |
| 提醒量 | 2,726 | 2,553 |
| 誤報 FP | 2,571 | 2,401 |
| 抓到延遲 TP | 155 | 152 |
| 漏掉延遲 FN | 517 | 520 |
| Precision | 5.69% | 5.95% |
| Recall | 23.07% | 22.62% |

誤報少 **170 張（6.61%）**，同時少抓 **3 張**延遲訂單，保留原版 98.06% 的 TP。這是小幅改善，precision 仍偏低，不能說問題已解決；validation 達到 30% 也沒有讓後續期間自動達到 30%。

三組開發回測合計（18,833 張，1,642 張延遲）：

| 候選／門檻 | FP | TP | FN | 合計 Precision | 合計 Recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| 原特徵 RF／F1 | 8,825 | 1,183 | 459 | 11.82% | 72.05% |
| 原特徵 RF／平衡 | 7,712 | 1,099 | 543 | 12.47% | 66.93% |
| 原特徵 Logistic／平衡 | 5,889 | 1,003 | 639 | 14.55% | 61.08% |
| 歷史特徵 RF／平衡 | 9,736 | 1,194 | 448 | 10.92% | 72.72% |
| 歷史特徵 Logistic／平衡 | 8,058 | 1,134 | 508 | 12.34% | 69.06% |
| 逐 fold validation 選模／平衡 | 6,927 | 1,071 | 571 | 13.39% | 65.23% |

原特徵 RF 的平衡策略減少 12.61% 開發回測誤報，但 TP 也下降，三月 recall 分別為 17.49%、94.49%、58.82%。逐 fold 自動選模雖減少合計 21.51% 誤報，2017-12 卻只抓到 5／446 張延遲（1.12%）；不能把這份合計數當成穩定改善。歷史特徵沒有減少本次誤報，因此不自動取代原版模型；未用已檢視保留期間反過來挑更漂亮的候選。

本輪完成 16 次候選訓練（3 組回測加最終切分、每組 4 候選），完整數字見 `reports/stage4/alert_optimization.json`。

後續已固定此平衡 artifact 分析逐月與分群誤報，包含跨州路線、承諾窗口變化及成熟標籤取樣偏差，見 [月份落差與誤報診斷](STAGE4_MONTHLY_DIAGNOSTICS.md)。該輪僅定位問題，模型與門檻保持不變。

## 改動

原版使用 validation F1 選門檻。新版改為按分數由高到低累計延遲正例，選出達到最低召回率的最高分數門檻。預測規則仍是 `delay_score >= threshold`，相同分數的訂單一起提醒，不拆開同分資料來湊目標。

比較四個固定候選：Random Forest／Logistic Regression，各自搭配原版 21 欄或新增歷史特徵。先對每個候選選門檻，再選 validation 提醒數最少者；同分依序比較較少 FP、較高 AP、固定候選順序。模型只在 train fit，validation 不加入重訓；所有選擇完成後才讀取 evaluation 分數與標籤。

原版模型與報告保留，新模型獨立存於 `models/olist_delay_balanced.joblib`。若選中 history 候選，使用 31 欄（27 數值、4 類別）；若選中 static 候選，仍使用原版 21 欄。推論依 artifact 的白名單與特徵版本建置輸入。

Random Forest 訓練可平行執行，但新候選在 validation、evaluation 與保存後推論一律以 `n_jobs=1` 依固定樹順序加總。這可避免分數剛好在門檻時，平行浮點加總的微小差異讓判斷偶爾改變；原版 artifact 不修改。

## 預測當下的配送歷史

歷史窗口為 **[核准時間 − 90 天，核准時間)**，以實際送達 timestamp 當作答案已知時間。剛好 90 天前的事件納入；核准同一刻或未來才送達者排除。自己的送達結果不進自己的特徵，輸入順序也不影響統計。

使用原版有效已送達訂單 cohort 作事件來源；每張訂單計一次。主賣家沿用最高價商品明細、同價按 `order_item_id` 排序的定義；多賣家訂單不額外重複加權。路線為主賣家州與顧客州的有向配對。ID 僅用於內部對應，不進模型。

| 新增數值欄位 | 定義 |
| --- | --- |
| `global_completed_90d` | 全體近 90 天已送達筆數 |
| `global_delay_rate_90d` | 全體已送達事件延遲率，以固定 5% 先驗、20 筆強度平滑 |
| `global_delivery_days_90d` | 全體從核准到送達的平均天數，包含小數 |
| `seller_completed_90d` | 同主賣家的近 90 天已送達筆數 |
| `seller_delay_rate_90d` | 同主賣家延遲率，以該預測時點的 global rate、20 筆強度平滑 |
| `seller_delivery_days_90d` | 同主賣家平均配送天數；無歷史時回退當時 global mean |
| `route_completed_90d` | 同州別路線的近 90 天已送達筆數 |
| `route_delay_rate_90d` | 同路線延遲率，以當時 global rate、20 筆強度平滑 |
| `route_delivery_days_90d` | 同路線平均配送天數；無歷史時回退當時 global mean |
| `route_promise_margin_days` | 承諾配送天數減同路線歷史平均天數 |

沒有全體歷史時，平均配送天數保留缺值，交給只在 train fit 的 imputer 處理；未知賣家或州別不合成一個共享的未知群組。模型保留各群筆數，避免把少量樣本的平滑率當成可靠的長期表現。

這些特徵描述的是「最近已完成配送」的表現，慢件尚未送達時不會出現，仍有完成者選擇偏差。固定 5% 先驗是預先設定，沒有使用全資料或 evaluation 的延遲率。

## 評估方法

沿用三組開發時間回測（evaluation 為 2017-12、2018-02、2018-04），各組 validation 後留一個月等待標籤成熟。每組以相同訂單比較原版 RF／F1、各候選的平衡門檻，以及 validation 自動選出的候選。報告同時列 FP、TP、FN、precision、recall、提醒率，不能只報誤報下降百分比。

歷史特徵會隨已知配送結果更新。例如 evaluation 當月前幾天核准的訂單已送達，可以成為後續訂單的歷史；尚未送達的 label 則不能使用。模型參數與門檻固定，這是可觀察事件更新，沒有重新訓練。

最後沿用原版 2018-03-03／2018-05-26 的 train／validation 分界，僅用已成熟 validation 選擇並保存候選。原 test 已經檢視過，所以新版在該段的分數只叫**已檢視保留資料的回溯診斷**；不參與模型或門檻選擇，也不能宣稱是新的獨立測試。

三個月結果的合計 precision／recall 由加總 TP／FP／FN 計算；它們與「每月指標的算術平均」不同。原版多模型比較表使用每月平均，跨報告比較時須看清口徑。

## 操作

```powershell
# 訓練平衡模式並產出回測與回溯診斷
.\.venv\Scripts\python.exe scripts\improve_delay_alerts.py --min-recall 0.30 --n-jobs 4

# 使用平衡模式重播一張已核准訂單
.\.venv\Scripts\python.exe scripts\predict_delay.py --profile balanced --order-id e481f51cbdc54678b7cc49136f2d6af7

# 保留原版推論方式
.\.venv\Scripts\python.exe scripts\predict_delay.py --profile original --order-id e481f51cbdc54678b7cc49136f2d6af7

# 批次平衡模式；模型需要的歷史欄位必須存在
.\.venv\Scripts\python.exe scripts\predict_delay.py --profile balanced --features-csv data\processed\olist_delay_history_features.csv --output .runtime\balanced_predictions.csv
```

自訂 `--model` 優先於 profile。原始訂單模式會依 artifact 自動建置歷史欄位；批次特徵 CSV 不會猜測或補建缺少的整欄資料。原始模式重播的是訂單當時核准時間，不是現在時間；舊單示範不算新評估。

| 產物 | 內容 |
| --- | --- |
| `reports/stage4/alert_optimization.json` | 每 fold 的四候選、兩種門檻、選模結果、FP／TP／FN、最終候選與回溯診斷 |
| `reports/images/stage4_alert_tradeoff.png` | 同批訂單的誤報數與召回取捨 |
| `models/olist_delay_balanced.joblib` | 獨立平衡模型、門檻與特徵契約；Git 忽略 |
| `data/processed/olist_delay_history_features.csv` | 原版 cohort 加上歷史特徵；Git 忽略 |

重新執行會更新平衡模式產物；保留多個實驗時同時指定不同 `--output-dir` 與 `--model-path`。不需要 MySQL 或新增 Python 套件。原資料的靜態快照、已送達 cohort、未校準分數等限制仍適用，詳見 [Stage 4 方法文件](STAGE4_DELAY_PREDICTION.md)。
