# Stage 5：移除購買月份的單因子消融規格

後續狀態：三欄實作與合成洩漏驗證已完成，見[實作與測試](STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md)。之後已依本規格完成一次[三欄真實消融](STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)。以下保留凍結規格當輪紀錄；機器規格及稽核bytes不變。

本輪凍結「只移除 `purchase_month`」的消融契約，核對原H60資料與12個完整角色。**沒有實作三欄builder／pipeline，也沒有建X、匯入模型套件、fit、transform、predict、選C或計算效能；Dashboard未開始。** Stage 4維持待資料、每日10%與11／29／42／73／101五種子。

新[機器規格](../reports/stage5/review_month_ablation_specification.json)及[契約稽核](../reports/stage5/review_month_ablation_contract_audit.json)另存，不改舊四欄程式、規格、標籤或分數。這是依[凍結分數診斷](STAGE5_REVIEW_SCORE_DIAGNOSTICS.md)形成的開發消融假說；月份與成績已看過，不能稱全盲預註冊或新的未知測試。

## 唯一改動與研究問題

先前診斷發現，內層2017-09及外層2017-12的query購買月份類別，在當時合格歷史中全部只有零或1–29筆支援；內層2017-11有98.88%落在零支援。這足以提出「模型是否依賴缺乏成熟歷史支援的月份欄」的消融問題，但尚未證明月份有害。2018-02及2018-04外層類別有支援，兩月的誤差不能直接歸因於月份缺支援。

原[基線政策](STAGE5_REVIEW_BASELINE_SPEC.md)逐值繼承，只允許下列五處結構差異；它們共同表示刪除同一個特徵，不是五項實驗改動。

| 政策欄位 | 四欄對照 | 三欄消融 |
| --- | --- | --- |
| `features.primary_order` | 月、星期、小時、核准等待 | 星期、小時、核准等待 |
| `features.categorical.purchase_month` | 固定1–12類 | 移除這個類別欄 |
| `features.one_hot.columns` | 43 | 31 |
| `features.output_columns` | 44 | 32 |
| `features.output_order` | 月12欄、星期7欄、小時24欄、標準化等待 | 星期7欄、小時24欄、標準化等待 |

比較器會拒絕其他protocol差異。保留三欄的原定義與順序：`purchase_dayofweek`為原naive購買時鐘週一0至週日6；`purchase_hour`為0–23；`approval_wait_hours=(核准−購買).total_seconds()/3600`。輸入float64，輸出31個one-hot加1個等待欄共32維，截距另計。

固定one-hot類別、`drop=None`、`handle_unknown=error`、`sparse_output=False`及float64不變；等待保留原小時，只用當次合格訓練列做StandardScaler，ddof=0、零變異scale=1。每個C及外層各自重新建立前處理；無補值、log、clip、權重、重採樣、校準或新特徵。非法欄值就停止，不刪query或補0。

## 資料、時鐘與未知標籤保持原契約

一單一列，在本單核准t預測首個記錄回答是否為1–2分，3–5分為另一類。首答必須位於`(t,t+60 elapsed days]`；無答、超窗、未成熟及品質隔離維持nullable y。最早答、平手、早答不重挑及各角色先排除未來回答的規則全部沿用，不重標籤。

原cohort要求購買／核准可解析、核准≥購買、核准<2018-05-01，不篩最終status或有無評論。全域事件觀察截止2018-07-01 exclusive。歷史fit只用自己的A=I或F合格y，嚴格`t+60天<fit`且合法首答早於fit；C截止標籤不能回填歷史fit。query仍保留未知與完整ID順序，自己的核准t可以晚於模型fit。

| 外層開發月／F | 內層驗證月／I | I合格訓練列 | F合格訓練列 | 外層完整／合格／未知 |
| --- | --- | ---: | ---: | ---: |
| 2017-12／12月1日 | 2017-09／9月1日 | 14,740 | 27,108 | 5,832／5,740／92 |
| 2018-02／2月1日 | 2017-11／11月1日 | 22,919 | 39,448 | 6,706／6,611／95 |
| 2018-04／4月1日 | 2017-12／12月1日 | 27,108 | 51,433 | 6,778／6,704／74 |

上表由本輪metadata稽核核對，不是訓練結果。內層驗證答案截止仍為F，外層query答案截止仍為C；歷史角色的未知列不參與前處理、常數比例、模型、選參或指標。固定窗內回覆者的條件目標不因刪欄改變，未知者的真實低評率仍不可驗證。

## 未來選參、對照與評估

L2 Logistic保持原鎖定環境與參數：scikit-learn1.9.1、`l1_ratio=0.0`、lbfgs、tol=1e-8、max_iter=1000、截距開啟、無class_weight／sample_weight；random_state=42只作重現，沒有Stage 5五種子實驗。其餘參數與停止條件均逐值繼承原規格。

三欄方案未來仍要在每個既定內層月比較C=0.1／1／10，只依該角色合格y的非插值AP選參；距最大值≤1e-12取較小C。**不能因四欄三月曾選C=0.1，就直接把三欄C也設成0.1。** 選參方法不變，實際選中的C可以不同；本輪三欄`actual_selected_C=null`。

任一必要角色缺類別、候選失敗、非有限AP／係數／機率或ConvergenceWarning，按原契約停止，不刪候選、加迭代、換solver或fallback。選C後在F用合格歷史從頭建立三欄前處理與模型。未來完整三欄執行預計9次內層候選＋3次外層fit，**這12次是未來預算，本輪實際為0**。

| 比較項目 | 凍結約定 |
| --- | --- |
| 四欄對照 | 使用原`review_baseline_training.json`及私有凍結分數，不重訓、不重選C、不改機率 |
| 配對單位 | 同來源版本、fold、角色、完整order ID與canonical順序、同角色truth；任一版本或名冊不符就停止，不能補訓練冒充舊對照 |
| 常數參照 | 仍為同fit合格訓練低評比例，不平滑、不參與選C；原名冊未變，未來應與原常數對照一致，本輪不重算比例 |
| 評估 | 每月完整／已知／未知與互斥原因、合格兩類支援；指標只用該角色合格y，未知不補負例 |
| 指標 | 原AP、ROC-AUC、Brier、binary logloss及固定p≥0.5混淆表／precision／recall；不新增門檻、排名或校準 |
| 數值與null | log才clip至[1e-15,1−1e-15]；原單類／空分母規則不變；任一方案指標null，該配對差也為null，不補0 |
| 彙總 | 逐月並列三欄、凍結四欄與常數，報三欄減四欄差；各方案三月皆有效才計macro AP，兩方案皆滿足才比較macro；不選月份、不pooled AP |
| 結論 | 不新增成功效能門檻、獨立fold信賴區間或正式通知核准；完整呈現所有三月得失，不因結果追加第二因子 |

上述是待實作／待執行的比較規格，沒有本輪效能數字。未來即使消融較好，仍只能視為已看開發窗的敏感性結果，不能宣稱新資料泛化、月份因果作用或營運適用。

## 本輪來源與實際驗收

新規格綁定39份公開來源／程式與12份私有來源，沿用原資料集、基線、訓練及診斷證據。原訓練spec/report與診斷spec/report版本固定；核manifest、原正式收據、guard與檔案bytes。舊逐筆分數及fit_audit只hash，不解析分數或係數、不重跑前輪診斷。

稽核只讀原orders的ID、購買及核准時鐘，以及原標籤／membership。由原時鐘重建研究cohort，再核每角色完整ID順序、fit／答案截止、H60成熟、nullable y、首答時序、互斥狀態與類別支援。此處只驗原事件快照，不補原入庫／評分修訂／歷史版本或業務時區證據。

| 本輪實際執行 | 結果 |
| --- | --- |
| 來源與完整名冊 | 99,441原訂單、73,254研究單；12角色共289,973列，均與原契約一致；角色列會重用訂單，不是獨立樣本數 |
| 全域標籤 | 合格72,173＝低評11,406＋其他60,767；未知1,081，未填負例 |
| 逐fit資格 | 12角色時鐘／未知遮罩及完整名冊一致，事件／成熟違規0；所需9個訓練／內層驗證情境兩類齊全 |
| 單因子範圍 | protocol只差5處月份結構，其餘政策逐值相同；H60、日曆、保留三欄公式及套件版本相同 |
| 契約測試 | 14項全過、0.500秒；涵蓋其他改動拒收、null／獨立選C、來源／guard、同版重跑及晚期失敗撤回；未匯入sklearn或fit |
| 測試隔離 | 3個受影響測試以已載入模組替身重驗，全過、0.200秒；沒有真正匯入模型套件或fit |
| 獨立對帳 | 最終版508項比較通過、23.210秒；不用正式模組，重建原cohort並核12角色逐ID／時鐘／未知；49舊資產與51來源綁定前後bytes不變 |
| 正式入口 | 最終版凍結規格5.241秒，metadata稽核9.113秒；均由公開CLI執行 |
| 未執行 | 三欄實作、X、模型匯入／實例化、fit／transform／predict、分數CSV解析、選C、效能及Dashboard均0 |

發布前修正了測試隔離：全專案測試若先載入sklearn，契約測試原本會把既有模組誤判成本輪匯入。改為在單元測試明確控制匯入狀態；公開CLI的禁止匯入守門保留。初版同輪規格、稽核、guard與收據保存在私有`.runtime/stage5_month_ablation_prepublication_v1/`，依最終測試版本重新綁定與驗收。獨立比對確認只有測試來源descriptor及連帶spec綁定更新，freezer程式、消融政策與metadata結果未變。

本輪只跑新契約測試與上述隔離檢查，不重跑含合成fit的舊pipeline測試，也不宣稱全專案測試。實際執行證明留`.runtime/stage5_month_ablation_*`，私有input_guard在`.runtime/stage5_review_month_ablation_v1/`；公開不放個體ID、標籤、模型或私有digest。

## 操作與下一步

在專案根目錄執行；這三個命令均不訓練：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_month_ablation_contract -q
.\.venv\Scripts\python.exe scripts\freeze_review_month_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\freeze_review_month_ablation.py
```

需原CSV、H60私有bundle、各輪原guard／收據及凍結分數；Git clone不包含它們。`--specification-only`固定新spec／guard，預設命令只驗metadata並寫契約稽核。同版本重跑須產生相同bytes，差異、缺檔或來源改版即拒收，不可刪舊證據或自行補收據。舊`run_review_baseline.py`會訓練四欄模型，不能拿來執行本輪或直接當三欄消融入口。

下一步先依新規格實作獨立三欄builder／train-only pipeline分支及洩漏測試，保留舊四欄凍結實作，再另決定是否執行消融訓練。若要訓練，還需另凍結新執行程式、來源及私有輸出版本；本輪規格完成不等於模型已實作、已訓練或已通過實用驗收。

Stage 4的同ID全量核准清冊、雙時間版本、日結／入庫對帳及取消／承諾版本事件訊號繼續待資料；每日10%與五種子維持，正式提醒與Dashboard暫緩。
