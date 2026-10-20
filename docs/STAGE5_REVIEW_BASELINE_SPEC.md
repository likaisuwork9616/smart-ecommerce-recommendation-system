# Stage 5：最小基線與評估凍結規格

後續已依本版完成[四欄builder／train-only pipeline及合成洩漏測試](STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md)，再串接來源與名冊執行[離線最小基線](STAGE5_REVIEW_OFFLINE_BASELINE.md)。以下保留規格凍結當輪「不建X／不fit」的範圍與數字；後續執行結果另見對應文件，不改寫本版政策或歷史紀錄。

承接[H60訂單級資料集](STAGE5_REVIEW_DATASET_SPEC.md)，本輪先固定特徵假設、前處理、歷史內層選參與評估口徑，核對逐fit標籤／事件代理支援。**本輪不建X、不擬合前處理或模型、不計算預測、選參成績或模型效能，不做Dashboard。** Stage 4待資料、每日10%與11／29／42／73／101五種子不變。

正式[基線規格](../reports/stage5/review_baseline_specification.json)綁定前輪資料集與本輪政策，[契約稽核](../reports/stage5/review_baseline_contract_audit.json)只報來源、時間、遮罩與類別支援。這是對未來最小基線的事前訓練／評估規格，但三個開發月及資料支援已檢視，不能稱全盲預註冊或新未知測試。本輪沒有實際選定C或建立模型。

## 沿用資料集與研究範圍

一單一列，t為核准；購買／核准合法、核准≥購買且核准<2018-05-01，不篩最終status、有無評論、缺明細或付款。最早記錄回答在`(t,t+60 elapsed days]`內時，1–2分為y=1、3–5分為y=0；無答、超窗、未成熟及品質隔離均保持nullable y。全域事件截止C=2018-07-01 exclusive。首答政策及每角色答案截止完全沿用前輪，不因本輪模型規格重標籤或放寬成熟閘。

主目標仍是固定窗內回覆者的首答評分條件機率；未評論者沒有可驗證y，不能把已知子集效能外推全核准母體。凍結C名冊73,254張、可用72,173張、未知1,081張是前輪資料支援，沒有模型含義。

## 四欄主方案與時間假設

最小方案只使用orders的購買、核准兩個事件時間。假設購買與核准時鐘在該訂單t已可取得且版本正確；本快照只能驗事件先後，缺原入庫、修訂與業務時區證據，**不能稱四欄已通過真實營運as-of驗收**。

| 欄位順序 | 定義與範圍 | 前處理 |
| --- | --- | --- |
| purchase_month | 原naive購買時鐘的月，1–12 | 固定12類one-hot |
| purchase_dayofweek | 購買星期，週一0至週日6 | 固定7類one-hot |
| purchase_hour | 購買時，0–23 | 固定24類one-hot |
| approval_wait_hours | `(核准−購買).total_seconds()/3600`，非負、有限的小時數 | 保留原小時，僅train-only標準化 |

四欄沿前輪21欄候選中的事件時間定義，**本輪不呼叫Stage 4特徵或label builder，也不實際算這四欄的X值**。稽核只解析兩個原事件時鐘、核對購買≤t及角色名冊，並以AST檢查既有公式。主方案假設季節／購買時段與核准耗時可能提供最低限度比較訊號，尚未證明有預測效果或因果意義。

其餘17個候選欄，包括承諾天數、明細、付款、商品、賣家與客戶主檔快照，均排除本版最小方案，保留原可得／版本缺口後再另定研究。原始時間字串／年份與絕對時間、order/customer/seller/product ID、本單評論或文字、實際交運／送達、最終status、延遲label及歷史模型分數都不進X。角色、fit時鐘、label_state、y、成熟／可用旗標、首答時間等審計欄也禁止當特徵。

訓練特徵應代表**各歷史訂單自己的t**，不能在F用後來版本補回；可驗事件代理為購買≤核准t<F。查詢訂單則在自己的t使用特徵，t通常在模型fit之後，不要求查詢時鐘<F；事件先後通過也不能補足真實入庫證據。

## 未來前處理契約

| 項目 | 固定規則 |
| --- | --- |
| 輸入與順序 | 上述四欄，float64；不納入審計欄或額外欄位 |
| 類別 | categories依序固定1..12、0..6、0..23；drop=None、handle_unknown=error、sparse_output=False、dtype=float64；不從全資料或查詢學詞彙 |
| 數值 | 只對原approval_wait_hours做StandardScaler，with_mean=True、with_std=True，母體變異ddof=0；零變異scale=1，不改用query統計 |
| 輸出 | 依month1..12、weekday0..6、hour0..23、scaled wait排序，43個one-hot欄＋1個標準化等待欄＝44維；模型截距另計 |
| 統計來源 | 每個候選的補值／編碼／scaler／模型都不得碰未知訓練列；本版無補值，scaler只fit該角色合格訓練y的列，每候選及外層重新建立 |
| 缺值／異常 | 原母體已要求兩事件時鐘合法；衍生欄缺失、非有限、負等待或類別越界一律停止該fold，不能刪查詢單、填0或臨時改imputer |
| 不採用 | 無log變換、clip／winsor、特徵選擇、target encoding、降維、額外缺值旗標或依成績改欄 |

查詢包含未知y的所有訂單，都只能使用該次訓練已固定的前處理作transform／預測；未知列不能反過來參與scaler fit、估計器、低評比例、選參或計分。本輪沒有建立、fit或transform任何pipeline。

## 未來參考基線與模型

參考基線為每次fit合格訓練標籤的低評比例常數`p=sum(y)/n`，不平滑、無權重。它只作同角色比較，不參與C選參；本輪不計算該比例或任何機率。

主模型固定L2 LogisticRegression，僅比較C=0.1、1、10。使用鎖定環境Python3.12.10、scikit-learn1.9.1、numpy2.5.4、pandas3.0.6。以本機安裝版本的原始碼核對API，不建立估計器：1.9.1用`l1_ratio=0.0`表達L2，省略已deprecated的penalty與n_jobs參數。

| 其他參數／政策 | 固定值 |
| --- | --- |
| solver／dual | lbfgs／False |
| fit_intercept／tol／max_iter | True／1e-8／1000 |
| class_weight／warm_start／verbose | None／False／0 |
| random_state | 42，只作重現設定；lbfgs不靠此設定產生五種子實驗 |
| 訓練政策 | 無sample_weight、重採樣、類別加權、early stopping、校準或ensemble |
| 失敗處置 | ConvergenceWarning、非有限係數／機率、機率不在[0,1]均停止該fold；不自行增迭代、改solver或縮候選後繼續 |

Stage 4每日10%與五種子契約保留在Stage 4；本版Stage 5固定機率分類與研究評估，沒有建立提醒預算或五種子穩定性結論。

## 內層選參與外層重訓

沿用凍結日曆：外層開發月2017-12／2018-02／2018-04，F為各月月初；其內層驗證月分別2017-09／2017-11／2017-12，I為內層月初。H60、答案截止A及完整名冊均不變。

1. 在每個I，只用inner_train_pool中`t+60天<I`且合法首答已在I前可見的合格y，建立候選自己的scaler及模型。未知／未成熟不進前處理或估計器。
2. 對完整inner_validation名冊預測，只以A=F的合格y計算非插值`average_precision_score`（AP，非梯形積分PR-AUC）。C只依這一個歷史內層月的AP選擇，不看外層答案；常數參考不作可選模型。
3. 找最大有限AP；與最大值差≤1e-12的候選視為平手，取最小C。inner_train或inner_validation缺任一類、任一候選失敗／非有限AP，該fold標insufficient_support／failed並停止，不填造分數、fallback或默認C。
4. C固定後，在F重新用outer_train_pool合格y從頭fit新scaler與模型；不能直接沿用I的前處理或用C截止答案回填F。外層query標籤只作最後開發評估，不改C、特徵、門檻或校準。

內層驗證月成熟後可進F歷史重訓；不同角色／滾動fold會重用歷史訂單，不能當獨立重複實驗。共有六個角色fit情境、五個不同日曆fit時點（2017-12-01重用）；未來若完整執行，三個inner角色各三個C共九組，加三組outer重訓，共12組scaler／估計器fit，不含常數參考。本輪實際fit均0。

## 未來評估口徑

每月先報全查詢N、合格N、未知N及互斥原因、合格1–2／3–5支援；完整名冊包含未知並全部出分數。模型指標只在**該角色自己的合格y**上計，不能用C標籤補內層答案，也不能把未知當負例。以下均為預定方法，沒有本輪效能結果。

| 項目 | 固定規則 |
| --- | --- |
| 主指標 | 每外層月AP，與同fit常數參考並列；AP與ROC-AUC需兩類齊，否則null並列缺口 |
| 機率方向 | p固定為P(y=1)，按模型classes_中標籤1的位置取值；不把另一類機率當低評分數 |
| 其他機率指標 | ROC-AUC、Brier=`mean((p-y)^2)`、binary logloss；Brier／logloss至少有一個已知y，無則null；logloss固定labels=[0,1]，不因評估月單類而改標籤空間 |
| logloss數值界 | 只為log計算把p限制至[1e-15,1−1e-15]，其他指標與預測機率不改寫；先要求原p有限且在[0,1] |
| 固定門檻 | p≥0.5為低評；報TP／FP／TN／FN、precision與recall，不用資料挑門檻 |
| 零分母 | 無預測正例precision=null；無實際正例recall=null；無已知列時混淆表／指標null，不用0冒充已測結果 |
| 彙總 | 三外層月等權macro AP，須三月皆有效才計；缺一則macro=null並報有效月數，不用nanmean丟月份或混合分數pooled AP取代 |
| 結論限制 | 無成功效能門檻或正式通知核准；不將滾動fold或單一seed當獨立重複，不給未經設計的信賴區間 |

本版不做機率校準、門檻選擇、每日預算排名或營運名單；若未來需要，先另定歷史內層／out-of-fold設計。三個月已檢視，只能稱開發回測；真正未來保留測試需另外資料及先定契約，不能把既有月份重新命名為未知測試。

## 本輪契約稽核與重現

```powershell
.\.venv\Scripts\python.exe scripts\audit_review_baseline_contract.py --specification-only
.\.venv\Scripts\python.exe scripts\audit_review_baseline_contract.py
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_contract -q
```

重現需Git忽略的原CSV、既有`.runtime/stage5_review_dataset_v1/`標籤／切分bundle，以及前輪原正式收據`.runtime/stage5_dataset_formal_execution_proof.json`。這些私有資產不隨Git clone交付；缺原收據就停止，不能自行補寫「已通過」來繞過來源守門。先核來源、舊資料集規格／報告與原manifest／收據；新的私有input_guard留`.runtime/stage5_review_baseline_v1/`，綁原私有檔與新規格實際bytes，公開只放路徑、schema與聚合，不放私有digest。

稽核不重寫舊資料集，逐角色對齊完整raw核准名冊、時鐘、nullable y、互斥狀態、成熟／可見閘及類別支援，核對事件欄與本機API／套件版本。這能核對**快照事件代理的研究資格**，不能補上原入庫、評分修訂、版本或日結完整性證據。

| 外層開發月 | I合格訓練：低／其他 | 內層驗證：低／其他 | F合格訓練：低／其他 | I／F未知或不合格池 |
| --- | ---: | ---: | ---: | ---: |
| 2017-12 | 2,079／12,661 | 522／3,718 | 3,557／23,551 | 8,437／12,355 |
| 2018-02 | 3,041／19,878 | 1,366／5,935 | 5,608／33,840 | 9,149／13,034 |
| 2018-04 | 3,557／23,551 | 935／4,805 | 7,500／43,933 | 12,355／15,043 |

以上是本輪metadata實際核對的類別支援，沒有計算低評比例或AP。六個訓練角色情境與三個內層驗證情境均有兩類，只代表通過本版缺類別停止條件，不表示模型能達業務效能。12角色仍共289,973列，跨角色／fold重用歷史訂單；原C名冊及各角色完整分母與未知遮罩保留，不能當成289,973張獨立樣本。

| 本輪實際驗證 | 結果 |
| --- | --- |
| 契約測試 | 20項全過、0.285秒；政策、未知／時鐘／完整名冊、來源與私有guard、全輸出預檢、路徑及API AST，沒有模型擬合；前輪23項未在本輪重跑 |
| 來源與舊資料 | 18份公開來源／程式綁定、4份原私有輸入前後一致；原兩JSON及三件私有H60產物共五件bytes不變 |
| 正式重現 | 規格凍結4.228秒、metadata稽核9.009秒；同版規格重跑4.439秒、稽核8.767秒；新規格／報告／私有guard三件bytes相同 |
| 可得／未知 | 73,254張原名冊、289,973角色列均保留；12角色未知被填值及事件／成熟違規0；真實入庫可得仍未驗證 |
| 本機API | 只用AST檢查三個已安裝類別的建構介面與固定版本；套件匯入／物件實例化0，不等於pipeline執行驗收 |
| 獨立對帳 | 不匯入正式模組，860項來源／原時鐘／角色／遮罩／類別／API／政策比較一致；沒有計算X、比例、AP或模型量 |
| 文件與發布 | 56份Markdown／685個本機連結有效，84份JSON嚴格解析及索引通過，三組文件支援數逐項吻合正式報告；公開無個體ID／標籤或私有digest |
| 本機證明 | .runtime/stage5_baseline_formal_execution_proof.json及stage5_baseline_formal_independent.json保留正式執行與獨立對帳紀錄，私有hash不公開 |

| 本輪範圍 | 判定 |
| --- | --- |
| H60資料集 | 沿用已凍結母體、標籤、角色與截止；不重標或改N |
| 最小基線 | 四欄／44維、前處理、三個C、歷史AP選參與評估規則已固定，尚未實作訓練入口 |
| 未知與逐fit | 未知不進任何fit、選參或指標；完整query保留，事件代理檢查與實際支援另報 |
| 真實可得性 | 原入庫／評分修訂與兩時鐘版本未驗證，營運適用不通過 |
| Stage 4／本輪未執行 | Stage 4待資料不變；本輪X、scaler／模型fit、預測、效能、實際選參與Dashboard均0 |
| 下一步 | 先依本版實作四欄builder／train-only pipeline並以合成資料驗洩漏，再另決定執行最小基線；本輪不啟動訓練 |
