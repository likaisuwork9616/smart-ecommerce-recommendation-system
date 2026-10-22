# Stage 5：三欄消融來源串接、執行規格與配對驗收

本頁保留來源準備那一輪的狀態；後續正式入口與writer已另行實作、綁定並做合成驗收，見[入口驗證](STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md)；之後已完成一次[三欄真實消融](STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)。

本輪已串接既有來源守門與完整H60角色名冊，凍結三欄消融的執行政策、私有輸出版本與同ID配對驗收規則。四欄沿用原凍結分數；**沒有建立特徵、建構模型、fit、transform、predict、選C或計算效能**，也沒有Dashboard。

這次凍結的是執行政策及來源／角色／配對守門。實際控制12次fit與發布的訓練入口尚未實作，未來須另綁定程式與測試，才能依本政策執行。三欄分數尚不存在，因此本輪沒有通過三欄與四欄的實際配對驗收，也沒有改善結論。

| 本輪驗收 | 實際結果 |
| --- | --- |
| 原始／研究名冊 | 99,441筆原始訂單；有效核准cohort為73,254筆 |
| 完整角色 | 3個fold、12角色、289,973列；逐角色ID、排序、H60與答案截止一致 |
| 四欄凍結分數 | 18區塊、108,744列＝內層70,112＋外層38,632；含跨候選重複，不是獨立訂單數 |
| 來源版本 | 51份公開綁定＋13份私有綁定；公開不含私有digest |
| 新單元測試 | 來源18＋配對25＋CLI／輸出16，共59項通過；0 fit、0效能計算 |
| 獨立核對 | 12角色及18分數區塊逐值核對，1,304,928個角色metadata欄值一致；另21項I/O對抗檢查通過 |
| 三欄實際配對 | `pending_not_trained`；預定輸出命名空間為空，沒有建立訓練產物 |
| Stage 4 | 待資料、每日10%、11／29／42／73／101五種子不變 |

來源為本輪[執行規格](../reports/stage5/review_month_ablation_execution_specification.json)及[準備驗收報告](../reports/stage5/review_month_ablation_execution_preflight.json)。本輪只核資料與契約；先前75項pipeline合成fit驗證保留在[前輪實作文件](STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md)，不混稱本輪訓練。

## 來源與完整角色如何串接

[來源adapter](../scripts/review_month_ablation_sources.py)先驗原消融規格、metadata稽核及三欄實作證明的固定SHA，再沿既有來源鏈驗H60資料、原四欄訓練manifest／收據、診斷及私有guard。任何來源缺失、版本不符或原訓練失敗收據出現都停止，不補造證據、不重跑舊訓練。

原 `load_verified_sources` 重新核對原始核准cohort、H60標籤及全部12角色，沿用獨立且不可變的 `ApprovalRosterContext`。訓練池包含當時時間合格的全部訂單，只有角色本身合格y可fit；query仍保留未知單，交給模型的副本清空七個未來標籤欄。資料與descriptor以防禦性副本提供。

四欄分數使用原CSV讀回規則，逐區塊核對15欄schema、完整12欄角色metadata、canonical ID順序、原model／C及float64機率。所有未知單也須有有限且位於[0,1]的分數；常數參考必須等於該角色合格訓練低評比例。此比例僅驗原常數定義，沒有重算AP、loss或混淆表，也不重新選四欄C。

禁止執行守門涵蓋新舊builder、pipeline建構與fit／transform／predict、sklearn前處理／模型，以及效能與選參函式。即使呼叫者吞掉禁止例外，整輪仍會拒收。既有模組會匯入sklearn來安裝守門，**零執行不等於零套件匯入**。

## 凍結的未來執行政策

| 部分 | 固定規則 |
| --- | --- |
| 唯一改動 | 只移除purchase_month；星期、小時、等待及32維前處理沿用已驗證三欄實作 |
| 資料與時間 | H60、原3個fold與12角色、完整名冊、逐fit標籤可得性及未知遮罩不變 |
| 訓練與選參 | 每fold內層C＝0.1／1／10，依原AP規則獨立選C，平手容差1e-12取較小C；不得借用四欄選定C |
| 從頭擬合 | 9次內層候選＋3次外層重新fit；每候選／角色重新建立前處理與模型；四欄0次fit |
| 出分與評估 | 18個完整query區塊，先全名冊出分，再以各角色合格truth評估；固定0.5與原指標政策 |
| 失敗處理 | 任一候選失敗、版本改變、名冊／配對不符即停止，不刪候選、fallback、自動重試或發布部分成功 |

前輪機器規格中的 `this_run`、`implementation_status` 等欄位保留當輪歷史狀態。新執行規格另外標示本輪0執行及未來dispatcher尚待綁定，沒有改寫父規格或原四欄成果。

## 同ID配對與私有輸出版本

[配對驗收模組](../scripts/review_month_ablation_pairing.py)已可在合成資料上驗完整雙臂18區塊。每個區塊均須與同一verified bundle的完整角色truth一致，不能inner join、先刪未知、重排修補、漏單或多單。

內層按同fold、角色與相同候選C比較；外層分別使用各臂獨立選出的C，兩個C可以不同。常數參考保持一致。純配對函式不重做選參，也不能證明傳入的C確實由內層選出；未來訓練入口必須提供並驗證該執行證據。實際差值固定三欄減四欄，任一方無定義則差值為null；macro AP需兩臂三月全部有效才比較，不補0或挑月份。

| 版本／檔案 | 用途與當前狀態 |
| --- | --- |
| `.runtime/stage5_review_month_ablation_execution_v1/input_guard.json` | 本輪已建立的私有輸入守門，綁定實際spec bytes及13份原私有來源 |
| `.runtime/stage5_review_month_ablation_training_v1/` | 預留未來三欄輸出根目錄；本輪未建立訓練產物 |
| `inner_scores.csv`／`outer_scores.csv` | 未來完整候選／選定模型與常數分數；15欄、未知y留空、float64以17位有效數字寫入並精確反讀 |
| `fit_audit.json` | 未來12個實際fit的合格ID、scaler、32欄、係數／截距及類別；只留私有 |
| `paired_acceptance.json`／`manifest.json` | 未來來源、入口版本、控制manifest、產物digest與全部18區塊配對證據 |
| `failure_receipt.json` | 未來失敗階段、fold、角色、C及已完成fit數；有既存失敗收據即禁止重跑 |
| `reports/stage5/review_month_ablation_training.json` | 預留未來公開聚合結果；本輪不存在 |

任一未來檔案、失敗收據、公開結果或命名空間內未知檔案已存在，都會在載入／fit前拒收。來源與四欄原產物不能當三欄輸出目的地。發布需完整預檢與精確反讀；失敗時只撤回本輪剛建立且bytes相同的檔案，保留既有證據。公開結果不得包含個體ID、分數、標籤、係數、私有digest或名冊hash。

規格中 `logistic_candidate_C_0.1_1_10` 是三個候選群組的描述；實際CSV的model值固定為 `logistic_candidate`，C另放0.1／1／10，外層選定模型為 `logistic_selected`。15欄CSV格式已固定；其他JSON目前列必要證據項目，具體序列化須隨未來訓練入口另綁定，不能宣稱本輪已完成產物writer。

## 重現與下一步

需原本機Olist、私有H60標籤／角色、四欄分數、manifest與正式收據；單靠Git clone不能補出這些證據。於專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_review_month_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\prepare_review_month_ablation.py
.\.venv\Scripts\python.exe -m unittest tests.test_review_month_ablation_sources tests.test_review_month_ablation_pairing tests.test_prepare_review_month_ablation -q
```

前兩行分別凍結執行政策／私有guard，以及產生不訓練的準備驗收。相同版本只接受相同bytes；CLI沒有 `--train` 參數。第三行59項合成測試不fit，完整日誌與獨立核對證明保存在Git忽略的`.runtime/`，不當作新效能。

下一步若決定推進真實消融，先完成並綁定正式訓練入口與測試，驗證9＋3次fresh fit、七個query未來欄遮罩、獨立選C、雙臂配對及完整發布，再依本規格執行。缺檔或改版需明確處理新版本，不能覆寫原證據。

本輪沒有新增原入庫、評分修訂版本或上游完整性證據；可驗的是現有凍結快照的一致性。已檢視月份仍是開發資料，固定窗回覆者的結果不能外推未知標籤。Stage 4的同ID核准清冊、雙時間版本、日結／入庫及事件訊號繼續待資料，正式提醒與Dashboard暫緩。
