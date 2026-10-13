# Stage 4：多月份驗證

本次完成 **12 次模型訓練**，讓同一模型、同一批分數分別使用「最新驗證月」、「合併三個驗證月」與「每個驗證月至少抓到 30% 延遲」三種門檻與選模策略。`every_month_floor` 是執行前指定的主方案，其他兩種是對照，沒有依 evaluation 結果改選主要策略。

結果沒有達成穩定改善。主方案確實讓每個 validation 月的 recall 都達 30%，但 evaluation 最差月份仍只有 **8.07%**；相較合併三月方案，誤報多 **2,435** 張、抓到的延遲多 **46** 張。研究模型另外保存，沒有取代原版或平衡模式。

以下數字來自 [實際執行報告](../reports/stage4/multimonth_validation.json)。Evaluation 沿用已檢視的 2017-12、2018-02、2018-04，共 18,833 張有效訂單、1,642 張延遲，屬於**開發回測，不是新的獨立測試**。原 2018-05-26 起的保留期間本輪沒有評分。

## 三個完整驗證月怎麼切

令 `E` 為 evaluation 起點：

```text
validation_end   = E - 60 天所在月份的第一天
validation_start = validation_end - 3 個月
train_end        = validation_start - 60 天

Train：approval < train_end，且 delivery < validation_start
Validation：approval ∈ [validation_start, validation_end)，且 delivery < E
Evaluation：approval ∈ [E, evaluation_end)，使用事後送達標籤
```

所有邊界都是午夜、左含右不含；標籤時間須嚴格早於截止，同一刻才送達的訂單排除。模型在 `validation_start` 時可訓練，門檻和候選選擇等到 `E` 才依已知 validation 標籤決定，此後不重訓。

| Evaluation 核准區間 | Train 核准截止（不含） | 模型訓練／標籤截止 | Validation 核准區間 | 可用 Train 筆數 | 可用 Validation 筆數 |
| --- | --- | --- | --- | ---: | ---: |
| 2017-12-01～2018-01-01 | 2017-05-02 | 2017-07-01 | 2017-07-01～2017-10-01 | 7,517 | 12,202 |
| 2018-02-01～2018-03-01 | 2017-07-03 | 2017-09-01 | 2017-09-01～2017-12-01 | 14,284 | 15,738 |
| 2018-04-01～2018-05-01 | 2017-08-02 | 2017-10-01 | 2017-10-01～2018-01-01 | 18,089 | 17,258 |

60 天是最低等待。為了取完整曆月，三組 validation 結束至 evaluation 起點的實際等待分別為 **61、62、90 天**。Train 核准截止至模型訓練時點則固定留 60 天；等待區間的新核准訂單不加入 train 或 validation。

三月驗證也讓訓練資料更舊、更少。例如本次 2018-04 train 只有 18,089 張；[前次單月、60 天實驗](STAGE4_WAITING_EXPERIMENT.md)是 30,932 張。前次結果只作背景，不能把兩次差異全歸因於「多看兩個驗證月」。本次三種策略在每個 fold／candidate 內共享相同 train、pipeline 與分數，才是直接比較門檻及選模規則的對照。

## 慢件標籤與原始訂單覆蓋

以下分母是原始快照中最終符合既有有效已送達 cohort 的訂單，**不是所有已核准訂單**，也不是當時可知的全體延遲率。相同核准月份在不同 fold 有不同標籤截止，因此保留數可能不同。

| Evaluation | Validation 月 | 延遲：截止前可用／事後完整 | 延遲保留率 | 準時保留率 |
| --- | --- | ---: | ---: | ---: |
| 2017-12 | 2017-07 | 107／107 | 100.00% | 100.00% |
| 2017-12 | 2017-08 | 120／121 | 99.17% | 100.00% |
| 2017-12 | 2017-09 | 180／183 | 98.36% | 100.00% |
| 2018-02 | 2017-09 | 182／183 | 99.45% | 100.00% |
| 2018-02 | 2017-10 | 183／184 | 99.46% | 100.00% |
| 2018-02 | 2017-11 | 862／874 | 98.63% | 100.00% |
| 2018-04 | 2017-10 | 184／184 | 100.00% | 100.00% |
| 2018-04 | 2017-11 | 871／874 | 99.66% | 100.00% |
| 2018-04 | 2017-12 | 442／446 | 99.10% | 100.00% |

Train 同樣依標籤成熟度篩除，三組分別保留延遲 321／342、513／544、644／650；準時訂單全數保留。完整報告記錄各 partition 及各 validation 月的正負類篩除量，避免總保留率掩蓋慢件缺失。

另以原始核准訂單對照同一 validation 核准區間：

| Evaluation | 原始已核准 | 有效完成 cohort | 截止前可用標籤 | 不在有效 cohort |
| --- | ---: | ---: | ---: | ---: |
| 2017-12 | 12,623 | 12,206 | 12,202 | 417 |
| 2018-02 | 16,286 | 15,752 | 15,738 | 534 |
| 2018-04 | 17,817 | 17,265 | 17,258 | 552 |

Raw audit 也包含 train／evaluation 的原始數量與 final status 分布。Status 是提供的快照中最終狀態，不能當成歷史截止當下的狀態；evaluation 的「截止前已知標籤數」保留空值，因其採事後結果。未送達、取消或時間異常訂單沒有被當成準時。原始資料缺少可信的快照抽取時間，以上保留率不能證明已涵蓋所有慢件。

## 模型、門檻與選模

每組切分訓練四個候選：RF／Logistic × Static／Route，共 3 × 4＝12 次 fit。Static 沿用 21 欄，Route 沿用前次 30 欄路線承諾特徵，這次沒有新增特徵或調模型參數。

RF 沿用 200 棵樹、最大深度 14、葉節點至少 8、`balanced_subsample`；Logistic 沿用 `balanced`、最多 2,000 次迭代；seed 固定 42。補值、類別編碼及 Logistic 標準化只在 train fit。RF 訓練可平行，validation／evaluation 及保存後推論固定 `n_jobs=1`。

路線歷史仍只包含核准前已完成的有效配送：`[approval - 90 天, approval)`。Evaluation 月內先完成的訂單可以成為之後核准訂單的歷史，模型與門檻保持固定；不把當前訂單的未來結果或整月結果回填特徵。特徵定義與限制見 [等待期實驗文件](STAGE4_WAITING_EXPERIMENT.md)。

| 策略 | 門檻約束 | 選候選使用的 validation 範圍 |
| --- | --- | --- |
| `recent_month` | 最新一個完整驗證月 recall ≥30% 的最高分數門檻 | 只看最新驗證月的提醒量、FP、AP |
| `pooled_3months` | 三個月合併 recall ≥30% 的最高分數門檻 | 全部三個驗證月 |
| `every_month_floor`（預先指定主方案） | 同一門檻下，每個驗證月 recall 都 ≥30% | 全部三個驗證月 |

同一 candidate 的三種策略共享一次 fit 和相同 validation／evaluation 分數。`recent_month` 最新月份分別為 2017-09、2017-11、2017-12，選模使用的筆數也相應較少，不能把其 selection 提醒量與另兩種策略直接比較。`pooled_3months` 與 `every_month_floor` 則使用完全相同的三月母體。

每月下限策略先求各月達標的最高門檻，再取其中最小值；提醒規則統一為 `score >= threshold`，同分不拆開。這是滿足每月 recall 下限的最高共用門檻。同一 candidate 的該門檻不高於 pooled 門檻，因此在固定分數與相同訂單上，FP、TP 都不會下降；它不保證以較少誤報改善 recall。

每個策略依指定 validation 範圍的提醒量最少選候選，同分時依 FP 較少、AP 較高、固定候選順序決定。四個候選的三種門檻與選模都固定後，才讀取 evaluation 結果。**驗證逐月達標不代表後續月份達標；不同策略改選了不同模型後，evaluation recall 也可能下降。**

## 完整開發回測結果

Precision／Recall 由三個 evaluation 月 TP／FP／FN 加總計算，不是每月百分比的算術平均。「最低驗證月 Recall」涵蓋三個 fold 的全部 validation 月；recent 只約束最新月、pooled 只約束合併值，所以它們的此欄可能低於 30%。`validation_selected` 表示該策略在各 fold 依 validation 選出的候選組合，不是額外訓練的第五種模型。

| 策略 | 候選 | FP | TP | FN | Precision | Recall | 最低 Evaluation 月 Recall | 最低驗證月 Recall |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| recent_month | RF／Static | 8,191 | 936 | 706 | 10.26% | 57.00% | 4.26% | 17.50% |
| recent_month | Logistic／Static | 10,509 | 1,120 | 522 | 9.63% | 68.21% | 10.09% | 12.50% |
| recent_month | RF／Route | 3,940 | 569 | 1,073 | 12.62% | 34.65% | 5.61% | 21.67% |
| recent_month | Logistic／Route | 12,271 | 1,225 | 417 | 9.08% | 74.60% | 6.50% | 24.17% |
| recent_month | validation_selected | 3,974 | 589 | 1,053 | 12.91% | 35.87% | 10.09% | 12.50% |
| pooled_3months | RF／Static | 8,082 | 922 | 720 | 10.24% | 56.15% | 7.17% | 21.67% |
| pooled_3months | Logistic／Static | 9,531 | 1,081 | 561 | 10.19% | 65.83% | 16.37% | 13.57% |
| pooled_3months | RF／Route | 3,109 | 526 | 1,116 | 14.47% | 32.03% | 8.07% | 19.23% |
| pooled_3months | Logistic／Route | 12,283 | 1,226 | 416 | 9.08% | 74.67% | 6.73% | 11.09% |
| pooled_3months | validation_selected | 3,293 | 563 | 1,079 | 14.60% | 34.29% | 16.37% | 18.33% |
| every_month_floor | RF／Static | 8,605 | 971 | 671 | 10.14% | 59.14% | 12.11% | 30.00% |
| every_month_floor | Logistic／Static | 11,200 | 1,200 | 442 | 9.68% | 73.08% | 28.03% | 30.00% |
| every_month_floor | RF／Route | 4,059 | 586 | 1,056 | 12.62% | 35.69% | 9.42% | 30.00% |
| every_month_floor | Logistic／Route | 12,378 | 1,232 | 410 | 9.05% | 75.03% | 8.07% | 30.00% |
| every_month_floor | validation_selected | 5,728 | 609 | 1,033 | 9.61% | 37.09% | 8.07% | 30.00% |

三種策略依 validation 選出的候選，分月結果如下：

| 策略 | Evaluation | 選中候選 | FP | TP | FN | Evaluation Recall | 三個驗證月最低 Recall |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| recent_month | 2017-12 | Logistic／Static | 316 | 45 | 401 | 10.09% | 12.50% |
| recent_month | 2018-02 | RF／Route | 851 | 308 | 582 | 34.61% | 30.05% |
| recent_month | 2018-04 | RF／Route | 2,807 | 236 | 70 | 77.12% | 30.09% |
| pooled_3months | 2017-12 | Logistic／Static | 524 | 73 | 373 | 16.37% | 18.33% |
| pooled_3months | 2018-02 | RF／Route | 763 | 292 | 598 | 32.81% | 26.45% |
| pooled_3months | 2018-04 | RF／Route | 2,006 | 198 | 108 | 64.71% | 19.23% |
| every_month_floor | 2017-12 | Logistic／Route | 422 | 36 | 410 | 8.07% | 30.00% |
| every_month_floor | 2018-02 | RF／Route | 851 | 308 | 582 | 34.61% | 30.05% |
| every_month_floor | 2018-04 | RF／Static | 4,455 | 265 | 41 | 86.60% | 30.09% |

![三種驗證策略的誤報、後續召回與驗證下限](../reports/images/stage4_multimonth_validation.png)

主方案和 pooled 比較：FP **3,293 → 5,728**、TP **563 → 609**、FN **1,079 → 1,033**；Precision **14.60% → 9.61%**，最差月份 recall **16.37% → 8.07%**。2017-12 主方案依 validation 改選 Logistic／Route，後續抓到的延遲反而由 73 降到 36；2018-04 改選 RF／Static，雖多抓 67 張延遲，也多了 2,449 張誤報。

這與同 candidate 降低門檻後 TP 不減並不矛盾：兩種選模策略可能改選不同模型，而不同模型的分數排序與後續表現並不相同。不能用 evaluation 的 15 列結果重新挑出最好的一列，當成已驗證有效的上線策略。

前次單月、60 天選模為 FP 3,434、TP 659、FN 983，最差月份 recall 4.04%。本次主要方案雖將最低值提高到 8.07%，仍多誤報 2,294 張、少抓 50 張延遲，且兩次 train／validation 日期與樣本數不同。這組數字只提供背景，不能宣稱多月驗證已改善延遲預測。

## 重現與產物

沿用專案 `.venv` 及本機 Olist 原始 CSV，不需要 MySQL 或額外 Python 套件。預設指令會驗證原始資料 manifest 與前次等待期報告一致。

```powershell
.\.venv\Scripts\python.exe scripts\compare_multimonth_validation.py --n-jobs 4
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 使用某一 fold 的研究模型做批次推論
.\.venv\Scripts\python.exe scripts\predict_delay.py --model models\research\olist_delay_multimonth_2018-04.joblib --features-csv data\processed\olist_delay_route_features.csv --output .runtime\multimonth_replay.csv
```

批次範例沿用前次等待期實驗產生的 30 欄 feature CSV；Static 模型會依 artifact 契約取所需 21 欄，忽略多餘欄位。CSV 若尚未產生，可依 [前次實驗的重現指令](STAGE4_WAITING_EXPERIMENT.md#重現與產物)建立。本次多月腳本本身輸出分數表，不另寫一份重複的特徵表。

整份 feature CSV 包含模型訓練期及更早的訂單，批次指令只展示載入與推論，不能把整份輸出當成 out-of-time 成績。正式開發回測只使用報告列出的 evaluation 範圍。

| 產物 | 內容 |
| --- | --- |
| `reports/stage4/multimonth_validation.json` | 三組日期切分、各月成熟度、raw audit、12 個候選實驗、15 列策略摘要、validation-only 決策與事後群組指標 |
| `reports/images/stage4_multimonth_validation.png` | 各策略選模後的分月誤報、evaluation recall、最差 validation 月 recall |
| `models/research/olist_delay_multimonth_{month}.joblib` | 三份主方案選中的 pipeline、門檻、特徵契約與研究標記；Git 忽略 |
| `data/processed/olist_delay_multimonth_scores.csv` | 256,124 列候選 validation／evaluation 分數，每列附三種策略的門檻與預測；Git 忽略 |

分數表包含 45,198 筆跨 fold 的 validation 觀測與 18,833 筆 evaluation 訂單，各有四個候選，共 256,124 列；三種策略共用分數，不把同一分數重複存成三列。Validation 月份在 fold 間重疊，因此 45,198 不是互異訂單數。

已核對全部 256,124 列分數與 768,372 個策略預測決策、36 個門檻、108 組逐月驗證指標、15 列摘要、360 組事後群組結果及 9 組 raw cohort audit。三份主方案 artifact 重載後的 validation／evaluation 分數和指標吻合；31 份既有模型與報告的 SHA-256 不變。

完整 **100 項測試通過**，Notebook 的 **15 個程式區塊完整執行通過**。新增實驗測試檢查每候選只 fit 一次、只使用 train 特徵與標籤、更改 evaluation 標籤及 metadata 不影響訓練和選模、逐月 recall 下限，以及 joblib 重載後的既有推論契約。Notebook 的多月實驗摘要只讀取既有報告，缺檔時顯示產生指令，不自動訓練。

## 限制與後續方向

三月約束修補了「合併 recall 掩蓋弱月份」這個驗證盲點，沒有消除後續月份漂移。完整三月加等待期使模型訓練時點更早，也減少可用近期訓練資料；這是本設計的重要代價。

各 fold 是歷史滾動重播，並非三次獨立實驗。較早的 evaluation 月可以成為後來 fold 的 validation，例如 2017-12 在 2018-04 選模時已屬歷史；只要送達標籤在該次截止前可知，時間順序合法，但這種重疊不能用來宣稱獨立驗證。這些開發月份與先前已檢視的保留資料，都不能重新命名為未知最終測試。

後續已完成 [每月重訓的滾動驗證](STAGE4_MONTHLY_RETRAINING.md)：只用各月當時已知資料訓練，保留當時的 out-of-time 分數，再轉移歷史門檻至新月份模型。抓到更多延遲，但誤報增加且最差月召回仍低，沒有自動提升研究模型。下一步應在 train／validation 內評估分數校準及誤報／漏報成本或提醒量預算；方法須在 evaluation 前凍結，再以未參與選模的新期間檢驗。
