# Stage 4：路線 × 承諾天數 × 近期負載變化

本輪測試近期核准訂單的變化，能否改善每日前 10% 的延遲辨識。前輪診斷顯示八月、長承諾及十二月 SP→RJ 漏報較多，因此先固定特徵與比較方式，再執行逐月消融；這項研究設計已看過開發結果，不能因此宣稱接下來的開發月份是獨立測試。

48 個新 fit 與正式比較已完成。主方案合併開發召回由前輪 25.58% 降至 25.40%，少抓 3 張延遲；固定 Logistic C=0.01 加 trend 在三個開發月合計多抓 5 張，但沒有一致的月份增益，明確交互 cross 也未穩定改善。正式產物為[執行前規格](../reports/stage4/route_load_interactions_specification.json)、[實驗結果](../reports/stage4/route_load_interactions.json)與[成對錯誤診斷](../reports/stage4/route_load_diagnostics.json)。前輪數字及十二月問題定位保留於 [Logistic 正則化](STAGE4_LOGISTIC_REGULARIZATION.md)與[十二月漏報診斷](STAGE4_DECEMBER_MISS_DIAGNOSTICS.md)。這些仍是已看過期間的開發回測。

## 固定比較方式

每個 backbone 都保留既有基準，分別比較 `baseline → trend` 與 `trend → cross`。前者衡量整組近期核准量特徵，後者衡量明確的承諾／路線交互；不能把兩組同時增加的效果全歸於某一欄位。

| Backbone | 基準原始欄數 | trend | cross | 本輪固定參數 |
| --- | ---: | ---: | ---: | --- |
| Logistic 負載 C=1 | 65 | 78 | 84 | 沿用 L2／lbfgs、C=1、max_iter=10000 |
| Logistic 負載 C=0.01 | 65 | 78 | 84 | 沿用 L2／lbfgs、C=0.01、max_iter=10000 |
| XGBoost 地理與交互 | 83 | 96 | 102 | 沿用前輪 XGBoost 參數 |

這些數字是編碼前的輸入欄數，OHE 展開後維度可隨月份改變。Logistic、XGBoost 各自與自己的 backbone 比，不把不同特徵與家族的差異解釋成單一變因。兩個 Logistic 沒有再搜尋新的 C，也沒有使用出貨期限、target encoding、E 月 early stopping、新校準或新提醒門檻。

固定新增六個候選，順序為 Logistic C=1 trend／cross、Logistic C=0.01 trend／cross、XGBoost trend／cross。八個月份版本為 2017-07、08、09、10、11、12、2018-02、04；已完成 48 個新 fit（32 Logistic、16 XGBoost），全部沒有 fit warnings。32 個 Logistic 均收斂，實際迭代 56–453 次。前輪 50 候選、400 個月份模型核對雜湊並重放原分數，沒有重新 fit；完整比較包含 56 候選、448 個月份版本。它們共用同一研究母體，不能當成 448 份獨立樣本。

所有新模型沿用相同種子 42、對應 backbone 的訓練訂單與排序、分類器參數及前處理；本輪實際訓練使用 `--n-jobs 2`，預測使用 1 worker，事前規格也記錄相同設定。數值補值中位數、缺值指標、Logistic 標準化與類別補值／OHE 都只 fit 訓練列；未來才出現的類別以既有 unknown 處理。Logistic 未收斂即停止比較，實際迭代與係數範數只作數值診斷，不參與選模。

## 特徵母體與時間邊界

新增特徵的 ledger 讀原始訂單，條件只有有效 purchase／approval 且 approval ≥ purchase，實際 99,281 筆，包含取消、尚未送達及缺少配送答案的訂單。主賣家沿用最高價格、同價取最小 item sequence；有向路線為主賣家州 → 顧客州。新增核准量不讀 final status、delivery timestamp 或 delayed target。

對核准時間 `t`，四個窗口固定如下：

| 特徵窗口 | 包含的 raw approval |
| --- | --- |
| recent 7d | `[t−7d, t)` |
| previous 7d | `[t−14d, t−7d)` |
| recent 14d | `[t−14d, t)` |
| previous 14d | `[t−28d, t−14d)` |

左端包含、右端排除；目前訂單、同時核准訂單與未來核准不計入。這是核准到件量的代理指標，無法量測承運商運能、實際包裹量、取消後的有效需求或堵塞原因。

route/promise lane 將路線再乘上固定承諾分箱 `0–7、8–14、15–21、22–30、31+` 天。Raw promise 依「承諾日期午夜 − 核准日期午夜」計算；負值或缺值不能形成 lane，仍計入路線與全域核准量。未知任一州別不形成路線，也不把不同未知路線合併成一組。

| 新增特徵包 | 欄位／公式 | 數量 |
| --- | --- | ---: |
| route 計數 | `route_approvals_7d`、`route_approvals_previous_7d`、`route_approvals_14d`、`route_approvals_previous_14d` | 4 |
| route 成長 | `route_approval_log_growth_7d`、`route_approval_log_growth_14d`，均為 `log((recent+1)/(previous+1))` | 2 |
| route 占比變化 | `route_approval_share_change_7d = route_recent7/global_recent7 − route_previous7/global_previous7` | 1 |
| lane 計數 | 同四窗口的 `route_promise_approvals_*` | 4 |
| lane 成長 | `route_promise_approval_log_growth_7d`、`route_promise_approval_log_growth_14d` | 2 |
| promise × route | `promise_x_route_growth_7d = (promise/30) × route_log_growth7` | 1 |
| promise × lane | `promise_x_lane_growth_7d = (promise/30) × lane_log_growth7` | 1 |
| 歷史餘裕 × route | `margin_x_route_growth_7d = (route_promise_margin_p90_days/30) × route_log_growth7` | 1 |
| promise × 既有逾期待件 | `promise_x_route_overdue_share_30d = (promise/30) × route_overdue_pending_share_30d` | 1 |
| 路線／承諾類別 | `state_route_promise_bin`，如 `SP->RJ|22-30` | 1 |
| 路線／承諾／成長類別 | `state_route_promise_growth_bin`，再加 `decrease/stable/increase` | 1 |

trend 只加前 13 個數值欄位；cross 在 trend 之上再加 4 個數值與 2 個類別。成長類別使用 lane 的 7 天 log growth，嚴格小於 `−log(1.25)` 為 decrease，嚴格大於 `log(1.25)` 為 increase，中間含兩個邊界為 stable。界線不是按開發結果調出來的。

已知路線沒有歷史時，計數與加一後的 log growth 為 0；未知路線的趨勢為缺值。任一全域 7 天窗口計數為 0 時，占比變化無定義，保留缺值。缺 promise 時 lane／承諾交互保留缺值，不能用 0 天替代。新增欄位依固定公式逐列產生，不 fit 全資料統計，也不改動凍結特徵的原值、列順序或 index。

既有 backbone 的配送歷史與待件仍使用其原本的時點規則；「不讀配送結果」描述的是這輪新增核准量 ledger，不表示既有 65／83 欄全部沒有歷史配送資訊。

## 訓練、驗證與固定提醒預算

每月模型 M 沿用 `deadline_wait0`：核准 `< M` 且 `training_outcome_known_time = min(實際送達, 承諾日期次日午夜) < M`，不另加等待日。這讓已逾期的有效訓練列較早取得延遲答案；研究標籤仍來自最終已送達 cohort。

歷史驗證則保持**實際送達 `< E`** 才算已知結果，不以較早訓練答案時間替代。每個歷史月使用該月月初自己的模型。

| 開發 E 月 | 歷史 OOT 選模月份 |
| --- | --- |
| 2017-12 | 2017-07、08、09 |
| 2018-02 | 2017-09、10、11 |
| 2018-04 | 2017-10、11、12 |

每日先讓完整研究評分批次共同排名，取 `floor(0.10 × 當日筆數)`，不跨日挪用；同分依訂單 ID 升冪。尚未知道結果的訂單仍競爭名額，之後才在已知結果上算歷史 TP／FP／FN，不能先刪慢件或改成全月 10%。批次需等當日結束，提醒可能比核准晚一天。

| 事前固定選模群組 | 候選數 | 用途 |
| --- | ---: | --- |
| `previous_candidates` | 50 | 重現前輪主方案 |
| `new_route_load` | 6 | 新特徵候選的描述性對照 |
| `primary_without_dispatch` | 56 | 本輪主方案 |

選模先最大化三個歷史月份的最低召回，再比較歷史合計 TP、合併 AP、固定候選順序。30% 是適用門檻，並非先篩選候選或放寬每日預算的理由。固定選擇後才報 E 月；不能看十二月或三個 E 的最佳數字反過來改選、調分箱或重組特徵。

三個 E 已反覆檢視，全部是開發回測。原 2018-05-26 起的保留期間不重新評分；本輪不自動替換原版預設 Random Forest，Dashboard 與新圖表繼續暫緩。最終送達 cohort 的事後選擇、缺少事件入庫／取消時間及承諾修改紀錄等限制沿用前輪；raw ledger 納入所有有效核准，不代表評分母體也涵蓋全部 raw orders。

## 實際結果與成對診斷

三個開發月共 18,833 單、1,642 張延遲，每個候選皆使用相同的 1,845 個每日取整提醒名額。下表完整保留固定候選，包括下降的格；這是各候選的描述結果，不能據此事後換主方案。

| Backbone | 特徵版本 | 開發 TP | 開發 FP | 開發 FN | 合併開發召回 | 最差歷史月召回 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Logistic C=1 | baseline | 362 | 1,483 | 1,280 | 22.05% | 16.59% |
| Logistic C=1 | trend | 341 | 1,504 | 1,301 | 20.77% | 14.67% |
| Logistic C=1 | cross | 318 | 1,527 | 1,324 | 19.37% | 14.17% |
| Logistic C=0.01 | baseline | 441 | 1,404 | 1,201 | 26.86% | 14.17% |
| Logistic C=0.01 | trend | 446 | 1,399 | 1,196 | 27.16% | 14.17% |
| Logistic C=0.01 | cross | 425 | 1,420 | 1,217 | 25.88% | 15.00% |
| XGBoost | baseline | 263 | 1,582 | 1,379 | 16.02% | 15.04% |
| XGBoost | trend | 247 | 1,598 | 1,395 | 15.04% | 13.80% |
| XGBoost | cross | 237 | 1,608 | 1,405 | 14.43% | 12.67% |

trend 只在固定 C=0.01 的合併開發結果多抓 5 張（+0.30 個百分點）；C=1 少抓 21 張，XGBoost 少抓 16 張。cross 相對 trend 在三個 backbone 分別再少抓 23、21、10 張。增加欄位沒有帶來穩定增益；不能僅因 C=0.01 trend 的合併結果最好，便當作已選定模型或未知資料成績。

逐歷史月召回如下，每格順序都是 **baseline → trend → cross**。同一歷史月在不同 E cutoff 的數字可不同，因後來可知道的實際配送結果增加，模型仍是該歷史月月初版本。

| E cutoff | 歷史月 | Logistic C=1 | Logistic C=0.01 | XGBoost |
| --- | --- | --- | --- | --- |
| 2017-12 | 2017-07 | 21.50% → 21.50% → 21.50% | 22.43% → 21.50% → 25.23% | 19.63% → 17.76% → 17.76% |
| 2017-12 | 2017-08 | 19.17% → 15.83% → 14.17% | 14.17% → 14.17% → 15.00% | 19.17% → 21.67% → 18.33% |
| 2017-12 | 2017-09 | 22.22% → 22.22% → 21.67% | 30.56% → 30.00% → 30.00% | 28.33% → 23.89% → 23.33% |
| 2018-02 | 2017-09 | 22.53% → 22.53% → 21.98% | 30.22% → 29.67% → 29.67% | 28.02% → 23.63% → 23.08% |
| 2018-02 | 2017-10 | 17.49% → 14.75% → 16.39% | 22.40% → 24.04% → 22.95% | 23.50% → 27.32% → 27.32% |
| 2018-02 | 2017-11 | 16.59% → 17.29% → 15.55% | 21.35% → 20.88% → 20.30% | 15.08% → 15.08% → 14.04% |
| 2018-04 | 2017-10 | 17.39% → 14.67% → 16.30% | 22.28% → 23.91% → 22.83% | 23.37% → 27.17% → 27.17% |
| 2018-04 | 2017-11 | 16.65% → 17.34% → 15.73% | 21.24% → 20.78% → 20.21% | 15.04% → 15.04% → 14.01% |
| 2018-04 | 2017-12 | 19.23% → 25.34% → 23.76% | 20.36% → 23.76% → 21.95% | 15.61% → 13.80% → 12.67% |

最關注的八月，XGBoost trend 多抓 3 張、召回 19.17% → 21.67%；加 cross 後退至 18.33%。Logistic C=1 兩段都下降，C=0.01 trend 不變、cross 只增加至 15.00%。九個格都未達 30%，XGBoost trend 的七月／九月也下降，不能稱為已修復最弱月份。

以下列出三個 E 的完整開發召回，順序仍為 baseline → trend → cross：

| 開發 E 月 | Logistic C=1 | Logistic C=0.01 | XGBoost |
| --- | --- | --- | --- |
| 2017-12 | 19.28% → 25.34% → 23.77% | 20.40% → 23.77% → 21.97% | 15.70% → 13.90% → 12.78% |
| 2018-02 | 20.34% → 14.83% → 13.60% | 26.07% → 25.28% → 24.27% | 12.92% → 13.82% → 11.01% |
| 2018-04 | 31.05% → 31.37% → 29.74% | 38.56% → 37.58% → 36.27% | 25.49% → 20.26% → 26.80% |

Logistic C=1 trend 的十二月多抓 27 張，二月卻少抓 49 張、四月多抓 1 張；C=0.01 trend 十二月多 15 張、二月少 7 張、四月少 3 張。XGBoost trend 十二月少 8 張、二月多 8 張、四月少 16 張；cross 的四月改善也沒有補回其他月份的下降。這些差異是固定候選在重複檢視開發資料的觀察，不是新增效果的因果估計。

| 歷史選模群組 | 2017-12／2018-02／2018-04 選擇 | TP | FP | FN | 合併開發召回 | 最差歷史召回 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 前輪 50 候選 | 舊 XGB／舊 C=0.01／舊 C=0.01 | 420 | 1,425 | 1,222 | 25.58% | 19.17% |
| 本輪六新候選 | XGB trend／C=0.01 trend／C=0.01 trend | 402 | 1,443 | 1,240 | 24.48% | 17.76% |
| 主方案全部 56 候選 | 舊 XGB／舊 C=0.01／C=0.01 trend | 417 | 1,428 | 1,225 | 25.40% | 19.17% |

| 主方案開發 E 月 | 歷史選出的模型 | 三歷史月最低召回 | 開發 TP／延遲 | 開發召回 |
| --- | --- | ---: | ---: | ---: |
| 2017-12 | 舊 XGBoost／83 欄 | 19.17% | 70／446 | 15.70% |
| 2018-02 | 舊 Logistic 負載 C=0.01／65 欄 | 21.35% | 232／890 | 26.07% |
| 2018-04 | Logistic C=0.01 trend／78 欄 | 20.78% | 115／306 | 37.58% |

四月新 trend 的歷史最低召回 20.78% 高於舊 C=0.01 的 20.36%，因此按事前規則改選；開發期反而少抓 3 張，不能看完 E 再改回舊候選。主方案相對前輪 TP 少 3、FP／FN 各多 3，合併召回下降 0.18 個百分點，precision 由 22.76% 降至 22.60%。三個 fold 的歷史下限全未達 30%，最差 E 仍是十二月 15.70%，本輪主方案沒有改善，也沒有自動部署。

### 完整日配對錯誤交換

以下為十二月與其三個歷史月的全部 36 組配對。補抓是 B 抓到 A 原本漏掉的延遲；新增漏報是 B 漏掉 A 原本抓到的延遲。新增／移除準時提醒也逐筆配對，因此淨 TP 只能反映交換後結果，不能只數補抓。

| 月份 | Backbone | A→B | 補抓延遲 | 新增漏報 | 新增準時提醒 | 移除準時提醒 | 淨 TP |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2017-07 | LR C=1 | baseline→trend | 1 | 1 | 43 | 43 | +0 |
| 2017-07 | LR C=1 | trend→cross | 4 | 4 | 90 | 90 | +0 |
| 2017-07 | LR C=1 | baseline→cross | 4 | 4 | 99 | 99 | +0 |
| 2017-07 | LR C=0.01 | baseline→trend | 2 | 3 | 57 | 56 | −1 |
| 2017-07 | LR C=0.01 | trend→cross | 4 | 0 | 52 | 56 | +4 |
| 2017-07 | LR C=0.01 | baseline→cross | 6 | 3 | 81 | 84 | +3 |
| 2017-07 | XGB | baseline→trend | 4 | 6 | 106 | 104 | −2 |
| 2017-07 | XGB | trend→cross | 6 | 6 | 103 | 103 | +0 |
| 2017-07 | XGB | baseline→cross | 8 | 10 | 124 | 122 | −2 |
| 2017-08 | LR C=1 | baseline→trend | 2 | 6 | 66 | 62 | −4 |
| 2017-08 | LR C=1 | trend→cross | 3 | 5 | 95 | 93 | −2 |
| 2017-08 | LR C=1 | baseline→cross | 4 | 10 | 108 | 102 | −6 |
| 2017-08 | LR C=0.01 | baseline→trend | 3 | 3 | 60 | 60 | +0 |
| 2017-08 | LR C=0.01 | trend→cross | 4 | 3 | 57 | 58 | +1 |
| 2017-08 | LR C=0.01 | baseline→cross | 5 | 4 | 74 | 75 | +1 |
| 2017-08 | XGB | baseline→trend | 7 | 4 | 124 | 127 | +3 |
| 2017-08 | XGB | trend→cross | 2 | 6 | 99 | 95 | −4 |
| 2017-08 | XGB | baseline→cross | 7 | 8 | 139 | 138 | −1 |
| 2017-09 | LR C=1 | baseline→trend | 2 | 2 | 44 | 44 | +0 |
| 2017-09 | LR C=1 | trend→cross | 4 | 5 | 93 | 92 | −1 |
| 2017-09 | LR C=1 | baseline→cross | 6 | 7 | 103 | 102 | −1 |
| 2017-09 | LR C=0.01 | baseline→trend | 2 | 3 | 30 | 29 | −1 |
| 2017-09 | LR C=0.01 | trend→cross | 5 | 5 | 44 | 44 | +0 |
| 2017-09 | LR C=0.01 | baseline→cross | 5 | 6 | 55 | 54 | −1 |
| 2017-09 | XGB | baseline→trend | 5 | 13 | 103 | 95 | −8 |
| 2017-09 | XGB | trend→cross | 7 | 8 | 83 | 82 | −1 |
| 2017-09 | XGB | baseline→cross | 6 | 15 | 109 | 100 | −9 |
| 2017-12 | LR C=1 | baseline→trend | 38 | 11 | 117 | 144 | +27 |
| 2017-12 | LR C=1 | trend→cross | 14 | 21 | 108 | 101 | −7 |
| 2017-12 | LR C=1 | baseline→cross | 44 | 24 | 172 | 192 | +20 |
| 2017-12 | LR C=0.01 | baseline→trend | 25 | 10 | 112 | 127 | +15 |
| 2017-12 | LR C=0.01 | trend→cross | 4 | 12 | 51 | 43 | −8 |
| 2017-12 | LR C=0.01 | baseline→cross | 22 | 15 | 134 | 141 | +7 |
| 2017-12 | XGB | baseline→trend | 11 | 19 | 144 | 136 | −8 |
| 2017-12 | XGB | trend→cross | 13 | 18 | 123 | 118 | −5 |
| 2017-12 | XGB | baseline→cross | 12 | 25 | 145 | 132 | −13 |

歷史結果嚴格採 2017-12-01 前實際送達。七月 3,827 單皆已知、容量 370；八月 4,217 單中 4,216 已知、容量 407；九月 4,162 單中 4,159 已知、容量 405；十二月開發 5,675 單、容量 554。八月 XGB 的三個版本各有 1 個未知結果提醒，九月 LR C=1 各有 2 個、C=0.01 各有 1 個；這些名額先參與完整批次，再從指標排除，沒有把未知結果算成準時或漏報。

### 八月與十二月的路線、長承諾及排名

路線欄皆為 **FN／FP**，長承諾欄為 **FN／延遲總數**。排名以完整日批次先排序再套歷史已知結果，不能在成熟子集重新排名。各欄是重疊維度，不能相加；所列 SP→RJ／SP→SP 均通過至少 30 單、5 張延遲的小樣本檢查。

| 八月版本 | SP→RJ FN／FP | SP→SP FN／FP | 承諾 ≥22 天 FN／延遲 | 排名 10–20% FN | 排名 20% 以後 FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| LR C=1 baseline | 8／40 | 19／94 | 65／74 | 16 | 81 |
| LR C=1 trend | 7／54 | 24／77 | 66／74 | 22 | 79 |
| LR C=1 cross | 8／55 | 25／76 | 66／74 | 24 | 79 |
| LR C=0.01 baseline | 8／34 | 20／149 | 69／74 | 19 | 84 |
| LR C=0.01 trend | 6／47 | 23／104 | 68／74 | 17 | 86 |
| LR C=0.01 cross | 7／37 | 23／117 | 68／74 | 18 | 84 |
| XGB baseline | 5／55 | 20／109 | 68／74 | 17 | 80 |
| XGB trend | 6／62 | 20／113 | 68／74 | 16 | 78 |
| XGB cross | 6／78 | 19／95 | 71／74 | 11 | 87 |

八月 XGB trend 雖整體多抓 3 張，長承諾仍漏 68／74，SP→RJ 還多漏 1 張；加 cross 後長承諾漏報增加至 71 張。這項改善沒有修復原本最關注的長承諾群，也沒有達到 30% 歷史召回。

| 十二月版本 | SP→RJ FN／FP | SP→SP FN／FP | 承諾 ≥22 天 FN／延遲 | 排名 10–20% FN | 排名 20% 以後 FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| LR C=1 baseline | 125／62 | 44／175 | 329／396 | 74 | 286 |
| LR C=1 trend | 96／112 | 55／50 | 294／396 | 75 | 258 |
| LR C=1 cross | 98／107 | 56／40 | 300／396 | 73 | 267 |
| LR C=0.01 baseline | 121／73 | 51／110 | 317／396 | 76 | 279 |
| LR C=0.01 trend | 101／149 | 54／24 | 302／396 | 85 | 255 |
| LR C=0.01 cross | 108／137 | 54／23 | 311／396 | 82 | 266 |
| XGB baseline | 136／40 | 37／295 | 350／396 | 49 | 327 |
| XGB trend | 133／45 | 42／324 | 355／396 | 59 | 325 |
| XGB cross | 143／43 | 36／329 | 364／396 | 63 | 326 |

十二月 LR C=1 trend 將 SP→RJ 漏報 125 → 96，但該路線 FP 62 → 112；SP→SP FP 175 → 50，同時 FN 44 → 55。C=0.01 trend 的 SP→RJ FN 121 → 101、FP 73 → 149，SP→SP FP 110 → 24、FN 51 → 54。提醒移向高風險路線時，補抓與新增誤報一起發生，不能說重點路線的 FN／FP 全面改善。

兩個 Logistic trend 十二月長承諾 FN 分別減少 35／15 張，排名 20% 以後的 FN 也下降；但 C=1 二月大幅退步，C=0.01 二月、四月也下降，仍缺乏跨月穩定性。XGB trend 的十二月長承諾 FN 350 → 355，SP→SP FP 295 → 324；排名 10–20% 的 FN 49 → 59，前 10% 實際少抓 8 張，不能只看後段 FN 略減就稱為前段排名改善。

十二月同家族 baseline／trend／cross 仍共同漏掉 LR C=1 的 308 張、C=0.01 的 327 張、XGB 的 357 張。這是各家族三版本的重疊，不能與前輪不同家族三模型共同漏報混用，也不構成新的集成提醒策略。

## 重現與完整日批次推論

從專案根目錄沿用 `.venv/`，需先具備前輪凍結特徵、400 個本機月份模型、前輪報告與逐筆分數；程式逐項核對來源與 SHA-256，缺少時不能只下載聚合報告就重跑。原始資料、模型與逐筆輸出均由 Git 忽略。

```powershell
.\.venv\Scripts\python.exe scripts\train_route_load_interactions.py --specification-only --n-jobs 2
.\.venv\Scripts\python.exe scripts\train_route_load_interactions.py --n-jobs 2
.\.venv\Scripts\python.exe scripts\diagnose_route_load_interactions.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

第一行只寫事前規格，第二行才重放舊版本、建立新特徵並 fit 六格。第三行不再訓練或選模，重放三家族 baseline／trend／cross 在 2017-07、08、09、12 的 36 個版本，核對分數與完整日提醒集合，產生成對錯誤診斷。原始月份尚未知的結果不計入歷史分組；路線、承諾與排名是重疊維度，不能相加。`route_by_promise_top20` 只保留依 FN 排序的前 20 組，不是完整交叉分組；樣本不足 30 單或 5 張延遲的旗標仍保留。不同模型的補抓交集只供分析，提醒聯集不代表符合 10% 上限的集成。

| 產物 | 路徑 | Git |
| --- | --- | --- |
| 執行前規格 | `reports/stage4/route_load_interactions_specification.json` | 保留 |
| 完整聚合結果 | `reports/stage4/route_load_interactions.json` | 保留 |
| 十二月及歷史月成對診斷 | `reports/stage4/route_load_diagnostics.json` | 保留 |
| 新本機特徵 | `data/processed/olist_delay_route_load_features.csv` | 忽略 |
| 新逐筆分數 | `data/processed/olist_delay_route_load_scores.csv` | 忽略 |
| 新月份模型 | `models/research/route_load_versions/` | 忽略 |
| 歷史選出的研究模型 | `models/research/olist_delay_route_load_YYYY-MM.joblib` | 忽略 |

推論使用 artifact 自帶白名單，主方案仍可能選回舊候選；不要假設它一定為 78／84／96／102 欄。完整日批次輸入只需 order ID、prediction time 與所需特徵，不需要任何結果欄位。以下擷取完整四月研究 cohort，保留類別與 ZIP 前導零：

```powershell
@'
from pathlib import Path
import joblib
import pandas as pd
artifact = joblib.load('models/research/olist_delay_route_load_2018-04.joblib')
features = pd.read_csv('data/processed/olist_delay_route_load_features.csv',
    float_precision='round_trip', dtype={c: object for c in artifact['categorical_features']})
month = pd.to_datetime(features.prediction_time).dt.strftime('%Y-%m')
columns = ['order_id', 'prediction_time'] + artifact['feature_names']
Path('.runtime/verification').mkdir(parents=True, exist_ok=True)
features.loc[month.eq('2018-04'), columns].to_csv('.runtime/verification/route_load_april_batch.csv', index=False)
'@ | .\.venv\Scripts\python.exe -
.\.venv\Scripts\python.exe scripts\predict_delay.py --model models\research\olist_delay_route_load_2018-04.joblib --features-csv .runtime\verification\route_load_april_batch.csv --complete-daily-batches --output .runtime\verification\route_load_april_predictions.csv
```

`--complete-daily-batches` 由呼叫端保證，程式不能由片段 CSV 證明當日沒有漏單。缺少聲明或單筆呼叫會拒絕。這是研究期間的推論重播，不是新的測試成績；新模型分數也未新增機率校準，不能直接當成可靠延遲機率。

## 實際驗證

完整 300 項自動測試通過。獨立依原始 99,281 筆有效核准重建窗口，核對 96,394 筆 × 19 個新增欄位，共 1,831,486 個值全部一致。規格檔正式執行前後 bytes 相同，未依訓練結果改動候選或特徵。

六個新 cell 均以完整四月 6,624 單執行真實批次 CLI，皆提醒 650 單；原始資料重建的特徵與研究來源完全一致，輸入沒有結果欄位，1,710 張顧客 ZIP 前導零正確保留。XGBoost 分數 CSV 以原生 float32 回讀核對 bitwise 相同並重算提醒集合；Logistic 分數在絕對誤差 `1e-12` 內，提醒集合完全相同。缺少完整日批次聲明與單筆呼叫均拒絕，這些是推論重現檢查，不是新評估期間。

Notebook 25 個程式區塊完整執行通過，提交 source 無輸出，所有舊區塊保留；新增區塊只讀兩份聚合報告，不啟動訓練或新增圖表。本文件的四月 Python block 與推論命令原樣執行通過，實際選定 `logistic_c0p01_route_load_trend`，6,624 單提醒 650 單，無結果輸入，ZIP 前導零與分數／提醒集合核對通過。

十二月／歷史配對獨立重放 36 個版本、160,929 筆來源分數，核對完整日容量、成熟遮罩與原選模；36 組配對、12 組重疊及 13,896 列分組全部一致，沒有重新選模。這些分數與分組包含候選／fold 的重複訂單，不是新增獨立樣本。

主實驗獨立重載全部 448 個版本，重算 2,387,224 筆月份／候選分數、23,136 個訓練補值中位數、432 組 OHE 契約、48 組相同訓練 ID／參數對照、32 組 Logistic 收斂資訊、3,587,136 列分數匯出、672 組指標與每日容量、9 組歷史選模、59 列摘要、3 組特徵包對照、三份研究 artifact 及 2,571 列主方案漏報分組，全部一致；另核對訓練標準化統計。事前保留的 510 份既有模型、報告與圖檔 SHA-256 全數不變，凍結來源的 9,350,218 個原值也完全保留。

原始資料、模型、逐筆分數與執行證明留在 Git 忽略路徑，提交內容只有程式、測試、Notebook 與聚合報告／文件。上述數量包含重複候選、月份與 fold，是重現證據，沒有增加未知測試期間或獨立樣本。
