# Stage 4：固定 10% 預算的特徵工程對照

本輪測試增加地理、承諾、訂單成本及未完成件交互特徵，是否能讓每日排名前 10% 抓到更多延遲。每日提醒預算、延遲目標與三個歷史月選模規則維持原樣；不以擴大提醒量換取召回，也不先挑開發結果最高的模型。

前三輪方法與結果保留在 [固定預算排名](STAGE4_BUDGET_RANKING.md)、[未完成件與每日排序](STAGE4_PENDING_RANKING.md)、[較早結果時鐘](STAGE4_OUTCOME_CLOCK.md)。本輪設計也受到先前開發漏報診斷啟發，不能因為先固定新候選參數，就把已反覆檢視的月份重新當成獨立測試。

## 實際實驗結果

本輪 88 個新月份版本已完成，沒有 fit warnings。以下來自 [正式報告](../reports/stage4/feature_engineering.json)；執行前固定的候選、參數、選組與來源見 [規格](../reports/stage4/feature_engineering_specification.json)。

| 同模型、同訓練 cohort 的開發召回 | 60 欄 | 83 欄 | 83 減 60（百分點） | 91 欄，敏感度 |
| --- | ---: | ---: | ---: | ---: |
| Logistic | 21.80% | 21.62% | −0.18 | 21.68% |
| Random Forest | 22.78% | 19.37% | −3.41 | 23.39% |
| LightGBM | 16.75% | 14.43% | −2.31 | 16.20% |
| XGBoost | 16.87% | 16.02% | −0.85 | 14.74% |

分母均為三個開發月合計 18,833 單、1,642 張延遲；每日名額合計 1,845，約 9.80%。83 欄的合併召回在四個家族全下降，沒有證明這組新增欄位能穩定提高召回。距離與交互一起加入，因此也不能單獨推論「距離無效」；要分開消融才能定位來源。

| RF 成對開發月份 | 60 欄 TP／延遲 | 60 欄召回 | 83 欄 TP／延遲 | 83 欄召回 |
| --- | ---: | ---: | ---: | ---: |
| 2017-12 | 79／446 | 17.71% | 93／446 | 20.85% |
| 2018-02 | 213／890 | 23.93% | 154／890 | 17.30% |
| 2018-04 | 82／306 | 26.80% | 71／306 | 23.20% |

同一組特徵在不同月份的方向也不同。RF 的 91 欄合併召回比 60 欄高 0.61 個百分點，但該固定候選最差歷史月僅 13.08%，且依賴出貨期限當時可取得的假設，不能按合併開發成績事後改選它部署。

| 歷史 selector | TP | FP | FN | 開發召回 | 最差歷史召回 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 前輪 24 候選 | 358 | 1,487 | 1,284 | 21.80% | 18.33% |
| 同訓練 60 欄四家族 | 358 | 1,487 | 1,284 | 21.80% | 16.24% |
| 83 欄四家族 | 295 | 1,550 | 1,347 | 17.97% | 17.52% |
| 91 欄四家族，敏感度 | 367 | 1,478 | 1,275 | 22.35% | 17.76% |
| 主方案：31 個非 dispatch 候選 | 359 | 1,486 | 1,283 | 21.86% | 19.17% |
| 全 35 候選，敏感度 | 359 | 1,486 | 1,283 | 21.86% | 19.17% |

主方案只多抓 1 張延遲、少 1 張誤報；precision 19.40% → 19.46%，recall 21.80% → 21.86%。這是歷史 selector 在十二月換模型的結果，不是四個家族皆從特徵獲益。

| 主方案 E 月 | 歷史選定候選 | 三歷史月最低召回 | 開發 TP／延遲 | 開發召回 |
| --- | --- | ---: | ---: | ---: |
| 2017-12 | `xgboost_engineering_geo` | 19.17% | 70／446 | 15.70% |
| 2018-02 | `random_forest_route` | 19.66% | 223／890 | 25.06% |
| 2018-04 | `random_forest_route` | 19.23% | 66／306 | 21.57% |

三個 fold 均未達歷史每月召回 30% 的門檻，最差開發月為 15.70%。包含 dispatch 的全候選組仍選同樣三個模型；只有 dispatch 候選的結果不能取代事前指定主方案。

| 主方案分組，前輪 → 本輪 | 漏報 FN | 誤報 FP | 解讀 |
| --- | ---: | ---: | --- |
| SP → SP | 235 → 219 | 67 → 295 | 多抓 16 張，卻多 228 張誤報 |
| SP → RJ | 192 → 189 | 544 → 547 | 多抓 3 張，多 3 張誤報 |
| SP → MG | 84 → 84 | 3 → 6 | 沒有多抓延遲 |
| 承諾 22–30 天 | 696 → 701 | 920 → 867 | 少發提醒，同時多漏 5 張 |
| 承諾 15–21 天 | 277 → 265 | 230 → 400 | 多抓 12 張，多 170 張誤報 |
| 承諾 31 天以上 | 267 → 273 | 320 → 199 | 少發提醒，同時多漏 6 張 |

分組是開發事後診斷；路線與承諾天數的集合重疊，不能相加。相同每日總預算會重新分配提醒，合計誤報少 1 張不代表各路線也減少。仍保留研究 artifact、維持原預設 RF、暫緩 Dashboard；下一輪可先把地理與負載交互分開消融，確認下降來自哪一組，不能直接按這些 E 結果挑欄位後宣稱未知資料改善。

## 比較設計

特徵契約保留既有 60 欄，新增 9 個郵遞區號參考位置特徵及 14 個逐列計算的交互特徵，形成 83 欄主實驗。另增加 8 個出貨期限特徵形成 91 欄敏感度實驗；Olist 沒有出貨期限的版本時間，無法確認匯出值在核准當下就已存在，因此主選模排除這四個候選。

| 變體 | 數值欄 | 類別欄 | 合計 | 角色 |
| --- | ---: | ---: | ---: | --- |
| `base` | 52 | 8 | 60 | 同模型家族、同訓練時鐘與同訓練訂單的對照 |
| `geo` | 75 | 8 | 83 | 60 欄＋9 地理＋14 交互，納入主選模 |
| `dispatch` | 83 | 8 | 91 | 83 欄＋8 出貨期限，只作敏感度實驗 |

Logistic、Random Forest、LightGBM、XGBoost 四個模型家族各比較三個變體，共十二個成對比較格。LightGBM 的 60 欄基礎格重用已存的 `lightgbm_pending__deadline_wait0`，其餘十一格是新增候選。連同前三輪 24 個既有候選，合計 35 個候選；八個月份版本新增 **11 × 8 = 88 次 fit**。

同家族的 `geo − base`、`dispatch − geo` 才是這次特徵增量的成對對照。所有新格固定使用 `deadline` 訓練時鐘、核准等待 0 天，且同家族使用相同模型參數、相同訓練訂單與相同評分訂單。不能把使用不同訓練時鐘、等待期或模型家族的舊候選差異全部歸因於特徵。

## 九個地理參考特徵

新增第七份來源 `olist_geolocation_dataset.csv`，與原有 orders、customers、order_items、order_payments、products、sellers 一起固定記錄來源雜湊。郵遞區號前五碼補零；非整數、超出 0–99999 或布林值都視為缺失。

同一郵遞區號可能有多筆座標。先排除任一經緯度無效、緯度超出 ±90 或經度超出 ±180 的列，再分別取有效成對座標的中位數。Haversine 使用地球平均半徑 6,371.0088 公里；算的是兩個代表郵遞點之間的球面距離，不能當成道路長度、實際運輸路線或配送時間。

| 欄位 | 定義 |
| --- | --- |
| `geo_primary_distance_km` | 代表品項賣家郵遞點到顧客郵遞點的球面距離 |
| `geo_item_distance_mean_km` | 所有品項已知距離的平均，每個品項同權重 |
| `geo_item_distance_max_km` | 所有品項已知距離的最大值 |
| `geo_known_distance_item_ratio` | 有有效起訖座標的品項數／全部品項數 |
| `geo_same_zip5_item_ratio` | 賣家與顧客前五碼相同的品項數／雙方前五碼已知的品項數 |
| `geo_customer_latitude`、`geo_customer_longitude` | 顧客郵遞點的代表緯度、經度 |
| `geo_primary_seller_latitude`、`geo_primary_seller_longitude` | 代表品項賣家郵遞點的代表緯度、經度 |

距離平均與最大值只使用有效座標；已知距離比例的分母仍包含所有品項。同郵遞區號比例不要求有有效座標，分母與距離比例不同。重複賣家的不同品項仍分別計數；代表品項沿用最高價格、同價取較低 `order_item_id` 的規則。

地理表沒有觀測或修改時間。本輪把它當作靜態參考，沒有使用郵遞區號出現次數作訂單量或歷史特徵，也沒有用延遲標籤估算座標。這個靜態參考假設仍需真實部署資料確認；使用整份參考表不代表已證明各座標在每個歷史核准時點都可取得。

實際來源含 1,000,163 列、19,015 個郵區代表點；經緯度都在全球合法範圍，但其中有疑似海外離群值。本輪使用預先固定的郵區中位數，沒有依開發結果裁切巴西邊界或距離；全球合法範圍並不保證每筆位置正確。全部 99,441 張原始訂單的代表賣家距離可取得率為 98.73%，這是資料覆蓋率，不是延遲召回率。

## 十四個交互特徵

以下只對同一訂單已建好的欄位作確定性運算，不跨訂單 fit 統計。一般比例要求分子非負、分母大於 0；不合法或未定義時保留缺值，不能改成無限大或自行補 0。缺值填補仍只 fit 當月訓練資料。

| 欄位 | 公式／解讀 |
| --- | --- |
| `geo_distance_per_promise_day` | 代表賣家距離／承諾日曆天數 |
| `geo_promise_days_per_100km` | 承諾日曆天數／（代表賣家距離／100） |
| `seller_pending_vs_completed_30d` | 賣家 30 天未完成件／（賣家 90 天已完成件／3＋1） |
| `route_pending_vs_completed_30d` | 路線 30 天未完成件／（路線 90 天已完成件／3＋1） |
| `seller_overdue_pending_share_30d` | 賣家 30 天逾期未完成件／賣家 30 天未完成件 |
| `route_overdue_pending_share_30d` | 路線 30 天逾期未完成件／路線 30 天未完成件 |
| `global_overdue_pending_share_30d` | 全域 30 天逾期未完成件／全域 30 天未完成件 |
| `product_density_g_cm3` | 品項重量平均／品項體積平均 |
| `freight_per_item` | 總運費／品項數 |
| `price_per_item` | 總品項價格／品項數 |
| `approval_weekday` | 核准時間星期，週一為 0、週日為 6 |
| `approval_hour` | 核准時間小時，0–23 |
| `promise_weekday` | 核准日加上非負整數承諾日曆天數所還原的承諾星期 |
| `geo_freight_per_km` | 總運費／代表賣家距離 |

`pending_vs_completed_30d` 的完成件分母是 90 天件數除以 3 的月尺度近似，加 1 防止零分母，不是真正另算的 30 天完成件，也不是賣家的實際產能。`product_density_g_cm3` 是平均重量與平均體積的比值，不是平均品項密度、包裹密度或材積重。

已完成歷史仍只取在核准時間之前已送達的事件；未完成件仍依嚴格較早核准及當時已知送達建立。交互計算沒有放寬這些時間界線，也不把未送達件當成準時件。完整窗口、平滑先驗及取消時間限制沿用前兩輪文件。

## 八個出貨期限敏感度特徵

來源是品項 `shipping_limit_date`，代表規定的出貨期限；不是實際交給物流的時間，也不是實際送達時間。

| 欄位 | 定義 |
| --- | --- |
| `dispatch_limit_min_hours_from_approval` | 有效品項期限距核准的小時差最小值 |
| `dispatch_limit_max_hours_from_approval` | 有效品項期限距核准的小時差最大值 |
| `dispatch_limit_mean_hours_from_approval` | 有效品項期限距核准的小時差平均 |
| `dispatch_limit_spread_hours` | 最晚期限減最早期限的小時差 |
| `promise_after_latest_dispatch_days` | 承諾日次日 00:00 減最晚出貨期限，單位為小數天 |
| `past_deadline_item_ratio` | 期限嚴格早於核准的品項數／有效期限品項數 |
| `missing_limit_item_ratio` | 缺失或無效期限品項數／全部品項數 |
| `primary_item_dispatch_limit_hours` | 代表品項的期限距核准的小時差 |

期限恰等於核准不算已過期。沒有任何有效期限時，最小、最大、平均、範圍、承諾餘裕、逾期比例與代表品項時間皆缺失，只有缺失比例為 1；沒有品項則八欄全部缺失。代表品項由價格與品項序號選定，不因它的期限缺失就改選其他品項。

Olist 未提供期限建立、修改或入庫時間。即使程式沒有讀取實際出貨與送達事件，仍無法排除匯出的期限曾在核准之後修改。這是 **as-of availability assumption**；91 欄候選與包含它們的選組，只能解讀成在此假設下的敏感度結果，不能直接作為上線改善證據。

## 固定模型、月份與選模門檻

模型參數先固定，同家族三種特徵變體一致；沒有使用 E 月 early stopping 或依 E 月結果調參。

| 家族 | 固定參數摘要 |
| --- | --- |
| Logistic | `class_weight=balanced`、`max_iter=2000`，數值標準化 |
| Random Forest | 200 棵、深度 14、葉節點最少 8、`balanced_subsample` |
| LightGBM | 400 棵、學習率 0.05、31 葉、葉節點最少 60、L2 10、行／欄取樣 0.8 |
| XGBoost | 400 棵、學習率 0.05、深度 4、`min_child_weight=10`、L2 10、行／欄取樣 0.8、`hist` |

種子固定 42。數值中位數、缺值指標、One-hot 類別編碼與 Logistic 標準化都只 fit 訓練資料；特徵的原始位置與比例轉換不讀標籤。新增候選使用核准早於月份起點 `M`，且 `min(實際送達時間, 承諾日次日零時)` 嚴格早於 `M` 的既有 eligible cohort 訂單；實際送達欄位不被這個訓練時鐘改寫。

| 開發 E 月 | 歷史選模 OOT 月份 |
| --- | --- |
| 2017-12 | 2017-07、08、09 |
| 2018-02 | 2017-09、10、11 |
| 2018-04 | 2017-10、11、12 |

每個歷史月由自己的月份模型評分。歷史選模仍以實際送達時間嚴格早於 E，決定哪些標籤已知；不能用 E 月模型回頭對舊訓練列重評，也不能把較早訓練時鐘套到歷史驗證成熟判斷。

每日在完整評分集合排前 `floor(0.10 × 當日完整筆數)`，含當時未知結果的列，再只用已知標籤計算歷史召回。門檻固定 0，依分數降冪、同分訂單 ID 升冪，不跨日挪名額。選模依序最大化三個歷史月最低召回、合併 TP、合併原始分數 Average Precision，完全同分依固定候選順序。

| 選模群組 | 可選範圍／用途 |
| --- | --- |
| `prior_candidates` | 前三輪 24 個候選，對照沿用方案 |
| `base60_same_training` | 四家族、60 欄、相同 deadline/wait0 訓練 |
| `geo_engineering_only` | 四家族、83 欄 |
| `dispatch_sensitivity_only` | 四家族、91 欄，敏感度 |
| `primary_without_dispatch` | 預先指定主方案，31 個不含 dispatch 的候選 |
| `all_including_dispatch` | 全 35 候選，敏感度 |

三個歷史月都至少召回 30% 才算通過適用門檻。選組在歷史資料上決定候選後才計算 E 月指標；候選固定表、成對差值、分月結果及敏感度都應完整保留，不能只展示最好的一列。若主方案未達標，就記錄未達標，不藉由改用敏感度組或開發最高值宣稱達標。

## 資料角色與實際使用限制

目標 cohort 仍是 96,394 筆有效且最終送達訂單，延遲定義為送達日曆日期晚於承諾日曆日期；不改標籤、不把取消或未送達訂單加入準時類。三個 E 月合計 18,833 筆、1,642 張延遲，都是已看過的開發回測；原 2018-05-26 起的保留期間本輪不重新評分。本輪整體設計已受 E 月診斷啟發，候選參數先固定只能限制本輪再選模，不能消除先前觀察造成的開發偏差。

歷史每日容量的母體是有效且最終送達的建模 cohort，不等於原始所有核准訂單。真實推論必須提供包含未知結果的完整已結束日批次；單筆、單一路線或只含高分訂單的子集，不能保證整日 10% 上限。新增分數沒有另作機率校準，不能把 `delay_score` 直接讀成已驗證延遲機率。

特徵改善即使在歷史與開發月份出現，也不代表已通過未知未來資料驗證。未完成件取消時間、事件入庫時間、承諾修改歷史與靜態參考版本等限制繼續存在。確認適用程度前維持研究 artifact，不自動替換預設模型；Dashboard 與新增圖表暫緩。

## 重現與產物

沿用專案 `.venv/` 套件，從專案根目錄執行本輪入口：

```powershell
.\.venv\Scripts\python.exe scripts\improve_feature_engineering.py --n-jobs 4
```

正式彙總報告為 `reports/stage4/feature_engineering.json`。執行時應核對七份來源、前輪 artifact 雜湊、cohort、月份切分與既有 OOT 分數重現，再新增特徵與 fit；模型比較規格在新候選開發結果計算前固定。

| 產物 | 路徑 | Git |
| --- | --- | --- |
| 彙總報告 | `reports/stage4/feature_engineering.json` | 保留 |
| 特徵資料 | `data/processed/olist_delay_engineering_features.csv` | 忽略 |
| 逐筆分數 | `data/processed/olist_delay_engineering_scores.csv` | 忽略 |
| 月份模型 | `models/research/engineering_versions/` | 忽略 |
| 選定研究 artifact | `models/research/olist_delay_feature_engineering_YYYY-MM.joblib` | 忽略 |

研究推論依 artifact 的 `feature_names` 提供所需欄位，以及完整日批次 `order_id`、`prediction_time`；不需要提供送達標籤、最終訂單狀態或訓練結果時鐘。以下在 PowerShell 從本輪特徵 CSV 取出完整 2018-04 **研究 cohort**，並移除所有結果欄位；此 cohort 仍不等於原始所有核准訂單。

```powershell
@'
from pathlib import Path
import joblib
import pandas as pd
artifact = joblib.load('models/research/olist_delay_feature_engineering_2018-04.joblib')
features = pd.read_csv('data/processed/olist_delay_engineering_features.csv',
    float_precision='round_trip', dtype={c: object for c in artifact['categorical_features']})
month = pd.to_datetime(features.prediction_time).dt.strftime('%Y-%m')
columns = ['order_id', 'prediction_time'] + artifact['feature_names']
Path('.runtime/verification').mkdir(parents=True, exist_ok=True)
features.loc[month.eq('2018-04'), columns].to_csv('.runtime/verification/engineering_april_batch.csv', index=False)
'@ | .\.venv\Scripts\python.exe -
.\.venv\Scripts\python.exe scripts\predict_delay.py --model models\research\olist_delay_feature_engineering_2018-04.joblib --features-csv .runtime\verification\engineering_april_batch.csv --complete-daily-batches --output .runtime\verification\engineering_april_predictions.csv
```

旗標是呼叫端對完整性的聲明，程式不能只看 CSV 就證明當天沒有漏單。單筆推論與缺少聲明的批次會拒絕；正式使用仍須先在上游建立所有有效核准訂單的完整已結束日批次。

## 實際驗證

- 最終 241 項自動測試通過；Notebook 21 個程式區塊完整執行通過，提交版本無輸出。新增 Notebook 區塊只讀報告，不啟動訓練或新增圖表。
- 原 60 欄共 5,783,640 個值與前輪完全相同；31 新欄共 2,988,214 個快取值與原始來源重建相符。14 個交互逐筆獨立手算共 1,349,516 次；地理／期限另抽 270 單、4,590 次公式核對。
- 未來配送與最終狀態改寫後，地理／期限兩家族共 192,788 列結果不變；這檢查不能取代靜態參考與期限版本的可用性假設。
- 獨立重載 280 個版本，核對 12,776 個訓練補值中位數、1,492,015 筆月份／候選分數、2,241,960 列匯出、420 組指標與每日容量、18 組歷史 selector、41 列摘要、三份研究 artifact、2,571 個漏報分組。同家族的切分與模型參數各核對 64 組等式。
- RF 的 60／83／91 欄版本各對 6,624 張四月訂單執行真正 CLI，均提醒 650 張；分數與提醒集合對應報告，1,710 張顧客 ZIP 前導零保留。輸入只含特徵、訂單 ID 與核准時間；缺少完整批次聲明或使用單筆呼叫均拒絕。

驗證分數列數包含候選與不同 fold 的重複訂單，不能當成獨立樣本數。執行證明留於忽略的 `.runtime/verification/`；來源與聚合報告保留 Git，原始資料、完整特徵、模型及逐筆分數不提交。

本輪開始前 254 份模型、報告與圖檔的 SHA-256 全數不變；17 份 JSON 都符合嚴格 JSON，61 個 README／本文件連結皆可解析。原始保留期間未重新評分，未產生新圖表。
