# Stage 4：等待期與路線承諾特徵實驗

本次完成 24 次訓練，比較 train／validation 都留出 30 或 60 天等待期，再測試隨機森林與邏輯斯迴歸的原特徵／路線承諾特徵。**60 天是執行前指定的主要方案，30 天是敏感度比較，沒有依 evaluation 成績挑等待期。**

60 天讓有效已送達 cohort 的驗證延遲樣本保留率提高到 95.05%～98.40%，但模型仍有月份召回崩落，不能宣稱已解決月份漂移。研究模型另外保存，原版與平衡模式維持原有預設。

## 評估範圍

Evaluation 沿用已檢視的三個開發月份：2017-12、2018-02、2018-04，共 18,833 張訂單、1,642 張延遲。所有候選使用相同 evaluation 訂單；這些結果是**開發回測，不是新的獨立測試**。原 2018-05-26 起的保留資料本輪不評估。

舊 RF／平衡策略作為背景對照。新等待期也改變 train 的截止日期、訓練筆數及 validation 的日期分布，不能把與舊方案的差異全歸因於等待天數。相同等待期內的原特徵／新特徵比較，則保持模型種類、參數與切分一致。

## 等待期怎麼切

令 `E` 為 evaluation 起點、`W` 為等待天數：

```text
validation_end   = E - W 天
validation_start = validation_end - 30 天
train_end        = validation_start - W 天

Train：approval < train_end，且 delivery < validation_start
Validation：approval ∈ [validation_start, validation_end)，且 delivery < E
Evaluation：approval ∈ [E, evaluation_end)，使用事後送達標籤
```

模型在 `validation_start` 時可訓練，門檻等到 `E` 時才依已知 validation 結果決定，不再重訓。截止當下才送達的標籤不納入；兩個等待區間的新核准訂單不偷偷加入 train 或 validation。

| 等待 | Evaluation | Train 核准截止（不含） | Validation 核准區間（右端不含） |
| --- | --- | --- | --- |
| 30 天 | 2017-12 | 2017-09-02 | 2017-10-02～11-01 |
| 30 天 | 2018-02 | 2017-11-03 | 2017-12-03～2018-01-02 |
| 30 天 | 2018-04 | 2018-01-01 | 2018-01-31～03-02 |
| 60 天 | 2017-12 | 2017-07-04 | 2017-09-02～10-02 |
| 60 天 | 2018-02 | 2017-09-04 | 2017-11-03～12-03 |
| 60 天 | 2018-04 | 2017-11-02 | 2018-01-01～01-31 |

60 天的資料較舊；例如 evaluation 為 2018-04 時，60 天 train 保留 30,932 張，30 天則有 43,518 張。等待讓慢件取得結果，同時犧牲近期資料與樣本數。

## 延遲標籤保留情況

以下分母是「原始快照中，最終符合既有有效已送達 cohort 的訂單」，不是所有已核准訂單，也不是當時可知的全體延遲率。

| 等待 | Evaluation | Validation 延遲：可用／事後完整 | 延遲保留率 | 準時保留率 |
| --- | --- | ---: | ---: | ---: |
| 30 天 | 2017-12 | 153／182 | 84.07% | 99.90% |
| 30 天 | 2018-02 | 307／371 | 82.75% | 99.87% |
| 30 天 | 2018-04 | 645／976 | 66.09% | 99.77% |
| 60 天 | 2017-12 | 175／178 | 98.31% | 100.00% |
| 60 天 | 2018-02 | 925／940 | 98.40% | 100.00% |
| 60 天 | 2018-04 | 365／384 | 95.05% | 100.00% |

只看總保留率會掩蓋慢件缺失，因此報告分別記錄正／負類的篩除數與保留率。Train 也記錄相同統計；較長等待不代表每個不同日期 cohort 的保留率必然單調上升。

程式另外對照原始已核准訂單，保留 final status、未納入有效 cohort 的數量，**不將未送達、取消或時間異常訂單當成準時**。例如 60 天、2018-02 evaluation 那組的 validation：原始已核准 7,732 張，有效完成 cohort 7,482 張，截止前可用標籤 7,467 張；另 250 張不在有效 cohort。原快照沒有可信的抽取時間，不能宣稱等滿 60 天就涵蓋所有訂單。

## 新的路線與承諾特徵

以主賣家州 → 顧客州定義有向路線，主賣家沿用最高價商品、同價按商品序號排序。新增 8 個數值欄與 1 個類別欄，總特徵數由 21 增為 30。

| 新欄位 | 定義 |
| --- | --- |
| `global_completed_90d` | 近 90 天全體已完成的有效配送筆數 |
| `route_completed_90d` | 同有向州別路線的已完成筆數 |
| `global_delivery_p90_calendar_days_90d` | 全體配送日曆天數的第 90 百分位 |
| `route_delivery_p50_calendar_days_90d` | 同路線配送天數中位數；無路線歷史時回退當時全體中位數 |
| `route_delivery_p90_calendar_days_90d` | 同路線第 90 百分位；無路線歷史時回退當時全體分位 |
| `route_promise_margin_p90_days` | 承諾天數減同路線第 90 百分位 |
| `route_promise_ratio_p90` | 承諾天數除以同路線第 90 百分位；分母為 0 時保留缺值 |
| `route_promise_cdf_90d` | 歷史配送天數不超過當前承諾的比例，以當時全體 CDF、20 筆強度平滑 |
| `state_route` | 例如 `SP->RJ`；任一端未知則缺值 |

歷史事件窗口是 **[核准 timestamp − 90 天，核准 timestamp)**，送達時間必須嚴格早於核准。同一刻與未來才完成的訂單排除；自己未來的結果不進自己的特徵。路線未知不合成共享群組。

配送天數採「送達日曆日期 − 核准日曆日期」，與承諾天數尺度一致，和前次歷史均值的連續小數日不同。分位使用 `numpy.quantile(method='linear')` 的定義，以 Fenwick 滾動頻數精確計算，不必每次重新排序全部事件；包含未來值的座標表只用來定位，未發生事件的頻數為零。

CDF 平滑公式為 `(route_count_at_or_below_promise + 20 × global_CDF) / (route_count + 20)`。全體無歷史時，分位與 CDF 維持缺值，由 train-only imputer 處理；筆數保留 0。這是已完成訂單的歷史分布，**不是校準後的延遲機率**，仍排除慢件尚未完成及取消訂單。

Evaluation 月內較早已完成的配送可成為之後訂單的歷史；模型與門檻固定，這是當時可觀察事件更新，不是用全月結果回填。

## 模型與門檻

每個等待期、每個 fold 都比較 RF／Logistic × static／route，共 2 × 3 × 4＝24 次 fit。RF 沿用 200 棵、深度 14、葉節點至少 8、`balanced_subsample`；Logistic 沿用 `balanced`、最多 2,000 次迭代。補值、類別編碼及 Logistic 標準化只在 train fit；RF 訓練可平行，validation／evaluation／保存後推論固定單執行緒。

每個候選只依 validation 選擇「recall ≥30% 的最高分數門檻」，同分一起提醒。再依 validation 提醒量最少選候選，同分依較少 FP、較高 AP、固定順序決定。四個模型與門檻全固定後，才查看 evaluation。驗證召回達標不代表後續月份達標。

## 實際回測結果

下表的 precision／recall 由三個月 TP／FP／FN 加總計算；不是每月百分比的算術平均。Static 是原 21 欄，Route 是新增路線承諾特徵。

| 等待／方案 | FP | TP | FN | Precision | Recall | 最低單月 Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 舊 RF／平衡（背景對照） | 7,712 | 1,099 | 543 | 12.47% | 66.93% | 17.49% |
| 30 天 RF／Static | 2,954 | 565 | 1,077 | 16.06% | 34.41% | 18.39% |
| 30 天 Logistic／Static | 5,039 | 923 | 719 | 15.48% | 56.21% | 4.93% |
| 30 天 RF／Route | 2,887 | 710 | 932 | 19.74% | 43.24% | 16.14% |
| 30 天 Logistic／Route | 2,263 | 348 | 1,294 | 13.33% | 21.19% | 4.04% |
| 30 天 validation 選模 | 2,579 | 660 | 982 | 20.38% | 40.19% | 4.93% |
| 60 天 RF／Static | 4,854 | 713 | 929 | 12.81% | 43.42% | 10.09% |
| 60 天 Logistic／Static | 5,718 | 961 | 681 | 14.39% | 58.53% | 2.24% |
| 60 天 RF／Route | 3,434 | 659 | 983 | 16.10% | 40.13% | 4.04% |
| 60 天 Logistic／Route | 6,763 | 1,049 | 593 | 13.43% | 63.89% | 0.67% |
| 60 天 validation 選模 | 3,434 | 659 | 983 | 16.10% | 40.13% | 4.04% |

60 天三組 validation 都選 RF／Route。與舊 RF／平衡相比，少 4,278 張誤報，同時少抓 440 張延遲；不能只宣傳誤報下降。2018-04 的誤報甚至從舊方案 1,706 增至 1,733。

| Evaluation | 30 天選模：FP／TP／FN | 30 天 Recall | 60 天選模：FP／TP／FN | 60 天 Recall |
| --- | ---: | ---: | ---: | ---: |
| 2017-12 | 144／22／424 | 4.93% | 74／18／428 | 4.04% |
| 2018-02 | 1,788／519／371 | 58.31% | 1,627／469／421 | 52.70% |
| 2018-04 | 647／119／187 | 38.89% | 1,733／172／134 | 56.21% |

![等待期、誤報與召回取捨](../reports/images/stage4_waiting_tradeoff.png)

## 路線特徵有效嗎

在相同 30 天切分、相同 RF 設定下，新特徵讓合計 FP **2,954 → 2,887**，TP **565 → 710**，FN **1,077 → 932**。這是值得後續檢驗的訊號，但 2017-12 recall 仍只有 16.14%，低於 validation 目標，而且不是新的未知資料成績。

相同 60 天 RF 的結果不同：FP **4,854 → 3,434**，TP **713 → 659**，FN **929 → 983**，以更多漏報換較少誤報。拆看先前發現的群組也有取捨：

| 60 天 RF：Static → Route | FP | TP | FN |
| --- | ---: | ---: | ---: |
| 主賣家 SP → 顧客 RJ | 463 → 532 | 176 → 227 | 233 → 182 |
| 主賣家 SP → 顧客 SC | 219 → 213 | 39 → 37 | 18 → 20 |
| 顧客 SP | 2,409 → 1,065 | 147 → 63 | 172 → 256 |
| 承諾 22～30 天 | 1,928 → 1,709 | 369 → 381 | 546 → 534 |

整體少誤報很大部分來自顧客 SP，但也多漏 84 張延遲。SP → RJ 則多誤報、多抓到延遲，不能單說改善或惡化。這些群組早已用於診斷，屬於開發假說；互相重疊，不能加總其改善數。

## 重現與產物

```powershell
.\.venv\Scripts\python.exe scripts\compare_waiting_strategies.py --n-jobs 4
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 明確載入某一 fold 的研究 artifact；仍是歷史重播，非部署後評估
.\.venv\Scripts\python.exe scripts\predict_delay.py --model models\research\olist_delay_wait60_2018-04.joblib --features-csv data\processed\olist_delay_route_features.csv --output .runtime\waiting_replay.csv
```

最後一個批次指令包含研究模型的訓練期與較早訂單，只示範特徵契約與推論，不可將整份輸出當成 out-of-time 成績。正式回測只使用報告列出的 evaluation 範圍。

| 產物 | 內容 |
| --- | --- |
| `reports/stage4/waiting_strategy_comparison.json` | 6 組切分與 raw audit、24 候選、10 策略、validation-only 決策、事後群組結果 |
| `reports/images/stage4_waiting_tradeoff.png` | 同批 evaluation 的誤報、召回、驗證延遲標籤保留率 |
| `models/research/olist_delay_wait{30,60}_{month}.joblib` | 六份選中模型與門檻、特徵契約及研究標記；Git 忽略 |
| `data/processed/olist_delay_route_features.csv` | 96,394 張有效 cohort 與時間安全特徵；Git 忽略 |
| `data/processed/olist_delay_waiting_predictions.csv` | 150,664 筆候選預測（同一 evaluation 訂單有八種方案）；Git 忽略 |

不需要 MySQL 或新增 Python 套件。完整 81 項測試通過；六份研究 artifact 重載後的 validation／evaluation 混淆矩陣吻合，全部候選預測與舊回測的 evaluation 訂單 ID 一致。原版模型、平衡模型與既有報告雜湊不變。Notebook 新增可選唯讀摘要，缺報告時只顯示執行指令；14 個程式區塊完整執行通過。

## 本次判讀與後續

等待期減少了可量化的慢件樣本缺失，卻沒有消除分布漂移與最差月份召回問題；路線承諾特徵也不是對所有模型、等待期與地區都穩定有利。因此本輪不自動提升研究模型為預設。

後續應在當時已知資料內，加入多個 validation 月份的穩定性檢查與明確的誤報／漏報成本，再以未用來選模型的新期間驗證。現有開發月份與已檢視保留資料都不能重新命名為未知最終測試。
