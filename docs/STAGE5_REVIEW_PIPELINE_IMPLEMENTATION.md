# Stage 5：四欄builder與train-only pipeline

本輪依[已凍結基線規格](STAGE5_REVIEW_BASELINE_SPEC.md)實作四欄builder、受控pipeline及合成洩漏測試。**本輪只在人工合成fixture上fit scaler／Logistic並檢查transform及機率一致性；沒有用真實Olist資料建X、訓練、預測、選C或計算模型效能，也沒有Dashboard。** H60資料集、基線規格與Stage 4待資料／每日10%／五種子契約保留。

程式見[review_baseline_pipeline.py](../scripts/review_baseline_pipeline.py)，[測試](../tests/test_review_baseline_pipeline.py)檢查實際資料流，[驗證CLI](../scripts/verify_review_pipeline.py)只執行這組合成測試並產生[聚合驗證報告](../reports/stage5/review_pipeline_verification.json)。本輪通過代表這個受控介面的隔離行為，不是模型可達效能或營運as-of驗收。

## 實作範圍

| 入口 | 行為與限制 |
| --- | --- |
| build_primary_features | 只讀order_id、購買與核准時鐘，輸出以order_id為index的四欄float64；保留要求的列序，不按status／評論或缺明細篩單 |
| validate_primary_features | 嚴格檢查四欄名稱／順序、dtype、finite、日曆範圍與非負等待；多欄、錯序或非法值拒收，不補0或縮N |
| ApprovalRosterContext | 獨立保存完整預期ID／核准時鐘及context_version，複製成不可變資料；不含y或未來評論欄 |
| freeze_approval_roster | 從呼叫方已確認完整的原事件名冊建立context；不是上游全量或原入庫證明 |
| GuardedReviewBaseline.fit_orders | 只允許inner_train_pool／outer_train_pool；核對完整名冊及角色時鐘後，只讓合格y進前處理與估計器 |
| transform_orders／predict_orders | 只接受同fold配對的查詢角色，保留全部查詢，包括未知y；只使用自己的t與原事件欄，不使用未來標籤 |
| audit_state | 回傳診斷副本供測試核對；不回傳可直接fit的sklearn estimator／pipeline |

四欄依序為purchase_month、purchase_dayofweek、purchase_hour、approval_wait_hours。日曆固定12＋7＋24個one-hot類別，等待使用原小時、train-only StandardScaler（ddof=0，零變異scale=1），共44維、截距另計；無補值、log／clip或其他欄位。原始表額外的評分、實際物流、status與主檔欄一律不讀，直接送入X的額外欄位則拒收。

內部L2 Logistic與固定C=0.1／1／10完全沿原規格：本機鎖定1.9.1 API使用l1_ratio=0、lbfgs與固定其他參數，沒有自動選參。每個候選及外層角色都需新instance；本輪合成fixture明訂C，不以測試機率或效能挑C。常數參考、內層AP選參、真實資料訓練排程與效能計算尚未啟動。

## fit與查詢的不同時間界線

fit先核對呼叫方提供的全來源名冊與獨立context，再對齊角色完整ID／核准時鐘，不能只讓兩份待驗資料互相比數量。訓練角色要求t<fit，t+60天<fit，合格首答在(t,t+60天]內且嚴格早於fit；y／label_state／usable／成熟旗標必須一致。未知保持NA、兩類皆需存在，不把未知或未成熟列收入scaler或估計器。

查詢的t可以在模型fit之後；它依自己的t產生特徵，不要求購買／核准時鐘早於模型fit。查詢只核對fold、配對角色、模型fit、ID與原事件時鐘，**忽略y、label_state、role_label_usable、horizon_complete與首答等未來標籤欄**。同一份X不應因這些欄位改動或尚未取得而改變transform／機率，也不能因此少出分數。事後已知／未知計分是未來評估工作的另一個步驟。

context建立時仍須依可信來源提供完整名冊及版本；呼叫方若一開始就把缺單來源宣告為完整，這個低階介面無法證明上游真的齊備。正式資料讀取器仍需沿原manifest、來源SHA及私有guard驗證，不能把context_version字串當成原入庫／版本證據。Python私有屬性也不是防惡意繞過的安全邊界；應透過公開受控介面使用。

## 失敗處理與測試重點

每個instance只准一次fit，先驗資料、在局部建立新pipeline，成功且檢查完成後才成為可預測狀態。驗證錯誤、單類訓練、ConvergenceWarning、fit例外或非有限係數均停止；不保留半成品／舊模型、不自動換參數或重試。輸出機率按classes_的標籤1取值，須有限、在[0,1]且每列合計為1。轉換或預測失敗也會使整個context成為FAILED，不能再沿用該instance。診斷回傳副本不能改動已fit狀態。

| 洩漏／失敗案例 | 要驗證的行為 |
| --- | --- |
| 手算特徵與44維輸出 | 月／星期／小時／等待正確，固定類別與輸出順序穩定，未見過的合法日曆值仍維持44維 |
| 未知訓練列含極端值 | 只改未知列的等待／日曆，不改合格列時，scaler與模型係數不變；未知不參與任何fit |
| 查詢極端值／未知列 | 全部保留；transform／predict不能更新scaler或模型，特徵變動可改機率，不能回頭影響訓練 |
| 查詢未來標籤改動 | 同X下，未來y／狀態／首答等任意改動或NA，transform／機率不變 |
| 回答／成熟邊界 | answer=fit或deadline=fit不合格；answer=deadline且deadline<fit合法；未知填0、早答及不一致旗標拒收 |
| 完整性與角色 | 少單、重複、錯ID／時鐘／fold／角色拒收；原始輸入與membership共同少同一ID，也需被保留的獨立context發現 |
| 各fit隔離 | 新candidate／outer instance各自fit，不能沿用前個角色scaler；失敗後不能預測 |
| 參數／schema／值域 | 凍結C以外、額外X欄、錯序、缺失、nonfinite、非法日曆、負等待等拒收 |

測試中的scaler統計、係數與合成機率只用來判斷不變性及介面正確性，不計算AP、召回、精確率或其他模型表現。公開報告只保存測試名稱、通過狀態、來源與範圍，不公布逐筆特徵、機率或係數。

## 重現與交付界線

在專案根目錄及既有鎖定`.venv`執行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_pipeline -q
.\.venv\Scripts\python.exe scripts\verify_review_pipeline.py
```

這兩個入口只用合成frames，不需要原CSV、私有標籤bundle或模型。CLI綁公開契約／程式／測試與套件版本，來源前後一致、無失敗／跳過才產生通過報告；同版重跑需維持報告bytes，實際耗時與測試log另放Git忽略的.runtime。來源或測試變更需另版，不能覆寫已不同的驗證結果。

| 本輪實際驗證 | 結果 |
| --- | --- |
| 新增洩漏／失敗測試 | 32項全過，正式CLI測試耗時1.855秒；沒有失敗、錯誤、跳過、expected failure或unexpected success |
| Stage 5相關回歸 | 可行性12＋H60資料集23＋基線契約20＋本輪32，合計87項全過、5.821秒；不是全專案完整測試 |
| 獨立合成對抗驗證 | 300項全過、5.396秒；24次成功fit均為手造fixture，25份既有來源／私有檔前後一致；未執行真實X、fit或模型效能 |
| 驗證CLI負向案例 | 空suite、failure、error、skip、expected failure、unexpected success共六種均拒收且不產生通過報告 |
| 正式重現 | CLI含啟動共4.601秒、同版重跑4.626秒；10份公開來源一致、公開報告bytes相同，內嵌的原始／私有資料來源未重新盤點 |
| 文件與發布 | 57份Markdown／708個本機連結有效，85份JSON嚴格解析及索引通過；公開無逐筆值、係數、機率或私有digest |
| 本機證明 | .runtime/stage5_pipeline_formal_execution_proof.json、stage5_pipeline_regression_receipt.json與stage5_pipeline_adversarial_result.json；公開只留聚合測試證據 |

| 本輪工作 | 狀態與仍待處理 |
| --- | --- |
| 四欄builder／受控pipeline | 程式已實作，以合成fixture核對時間、未知及完整名冊隔離 |
| 真實資料X／訓練／評估 | 均未執行；未選C，沒有模型成績或未知測試宣稱 |
| 真實可得性 | 原入庫、評分修訂、事件版本與上游完整性缺口保留，測試不能補成營運證明 |
| Stage 4 | 待資料、每日10%與五種子及既有結果不變，Dashboard暫緩 |
| 下一步 | 先決定是否進入真實資料最小基線；若執行，需串接既有來源守門與角色名冊，再按凍結內層選參及外層開發評估執行 |
