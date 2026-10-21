# Stage 5：三欄正式入口、私有產物與合成驗收

本頁保留正式入口實作時的合成驗收紀錄，以下「本輪／未訓練」均指當時狀態。後續已另完成一次真實消融與交付驗收，見[三欄真實結果](STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)；同版產物已占用，勿重跑準備或訓練入口。

本輪完成只移除 `purchase_month` 的正式訓練入口及私有寫入流程，另綁定程式、測試和具體JSON格式。**只對合成資料fit；沒有執行三欄真實訓練、實際選C、產生真實分數或新增效能結論。** 四欄程式、凍結分數、既有規格與報告保留，Dashboard未開工。

前輪[執行政策與來源驗收](STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md)記錄的是當時入口尚未實作的狀態。這輪以新的[入口綁定規格](../reports/stage5/review_month_ablation_dispatcher_specification.json)及[合成驗證報告](../reports/stage5/review_month_ablation_dispatcher_verification.json)接續，沒有回寫歷史狀態。

## 本輪驗收

| 本輪工作 | 實際結果與界線 |
| --- | --- |
| 入口與來源 | 59公開＋14私有來源綁定；原12角色、四欄18分數區塊與凍結契約保持一致 |
| 合成驗證 | 入口20＋訓練32＋writer22＝74項全過，無失敗／錯誤／跳過；完整試跑各9次內層＋3次外層 |
| 選參與配對 | 三欄獨立選C；合成案例C=1可與四欄C=0.1不同，完整18區塊含未知單，不借用控制C |
| 私有交付 | CSV逐欄／binary64精確反讀；配對後ID、truth、分數、係數或公開指標遭改動均拒收；失敗停止並留收據 |
| 真實訓練 | 0真實fit／實際選C／新效能；三欄training_v1仍無產物，四欄原分數未改 |
| Stage 4／Dashboard | 待資料、每日10%及五種子不變；未做Dashboard |

正式合成驗證階段耗時165.964秒（不含此前來源載入，含測試、反查與報告發布）。該次74項測試以sklearn實際完成37次合成fit、全部32維：三個完整試跑各12次，另1次用於預測失敗後收據驗證；其他控制分支以合成模型替身測試。這些次數不是真實三欄訓練。

另以獨立合成adapter驗一個12次fit／18區塊完整試跑；私有manifest、重跑拒絕、晚期額外檔案／來源變動、驗收後ID或公開指標被修改的檢查均通過。獨立檢查與74項單元測試分列，紀錄保留在`.runtime/`。

合成資料的分數、AP及C只用於檢查程式行為，沒有列為模型效果。三欄真實 `training_v1` 命名空間及公開training報告仍沒有產物，實際雙臂驗收維持 `pending_not_trained`。

## 正式入口如何執行

[入口](../scripts/run_review_month_ablation.py)先核對凍結來源、全部H60角色、四欄原分數、程式／測試版本及成功的合成報告，再檢查輸出版本未被占用。缺少證據、版本改變或已有產物，會在開始fit前拒收；不補訓練、不補分數，也不重跑已占用版本。

[訓練控制](../scripts/review_month_ablation_training.py)在第一個fit前先檢查全部12角色與必要的雙類別支援，之後依固定順序執行：

1. 每fold以C＝0.1、1、10各建立一個全新的三欄pipeline，僅使用該fit當下已成熟且有可用首答的訓練列。未知y保持空值，不參與任何前處理或fit。
2. 完整query名冊先清空七個未來truth欄，再出分；取得全名冊分數後，才以分開保存的角色truth評估。所有未知單仍有機率。
3. 三欄依自己的內層AP選C，沿用1e-12容差、平手取較小C；常數參考不參選，四欄C及外層答案不參與選參。
4. 外層使用選定C重新建立pipeline並fit。三fold合計9次內層＋3次外層；四欄0次fit。
5. 全部18個分數區塊都通過完整同ID、同順序、同truth配對後才交付。內層比較同C；外層可使用各臂自行選出的不同C。差值為三欄減四欄，任一值無定義則保留null；macro AP需兩臂三月全有效。

來源在載入前後、每次fit前、每次預測後及發布前後再核對。發布後沿用已捕捉的來源清單驗hash，避免誤用要求輸出目錄為空的前輪準備函式。四欄指標讀取原報告，沒有重新跑四欄模型或依外層結果選C。

## 私有產物與失敗停止

[產物writer](../scripts/review_month_ablation_artifacts.py)具體凍結欄位、路徑及發布順序。所有逐筆內容保留在Git忽略的 `.runtime/stage5_review_month_ablation_training_v1/`。

| 檔案 | 驗收與內容 |
| --- | --- |
| `inner_scores.csv`、`outer_scores.csv` | 原15欄、完整未知列、空白nullable y/C；UTF-8／LF／17位有效數字，精確反讀全部欄值及binary64機率 |
| `fit_audit.json` | 12次fit的序號、時鐘、完整池／合格ID、scaler樣本數與moments、32欄、係數／截距／類別；不儲存模型物件 |
| `paired_acceptance.json` | 原執行規格、新入口、input_guard、四欄manifest及三欄產物digest；18區塊完整配對、未知覆蓋與獨立選C證據 |
| `manifest.json` | 上述來源、全部私有檔digest、公開報告descriptor、完成fit數及禁止重播聲明 |
| `failure_receipt.json` | 失敗階段、fold、角色、C、已成功完成fit數與例外類別；不記原始例外訊息或個體資料 |

核心配對證據另綁定兩份CSV、fit audit及公開聚合結果的精確序列化digest；writer先核對這些bytes，防止驗收後內容被改動。writer使用排他新建、欄位白名單、來源穩定性及寫後反讀。公開聚合結果最後才寫入；任一失敗即停止，不刪候選、fallback、自動重試或宣稱部分成功。若已開始訓練，入口保留私有失敗收據；有此收據即拒絕再次訓練。

失敗時只撤回本輪新建且bytes仍與寫入值完全相同的檔案。既有檔案或被外部改動／部分寫入的檔案保留為失敗證據，禁止以成功狀態交付。缺少／過期驗證或既有產物屬於開始前拒收，不向既有版本補寫收據。來源缺口或占用版本需另行判斷，不能刪證據再試。

公開報告只留固定schema的聚合結果與公開來源descriptor；ID、個體機率、標籤、係數、名冊hash及私有digest均不公開。

## 操作方式

單獨跑新模組測試只用合成fixture，不需要原Olist或私有分數：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_run_review_month_ablation tests.test_review_month_ablation_training tests.test_review_month_ablation_artifacts -q
```

下列命令需要原本機來源與完整私有證據。依序綁定、產生正式合成報告，再做只讀準備檢查；均不執行真實fit：

```powershell
.\.venv\Scripts\python.exe scripts\run_review_month_ablation.py --specification-only
.\.venv\Scripts\python.exe scripts\run_review_month_ablation.py --verify-synthetic
.\.venv\Scripts\python.exe scripts\run_review_month_ablation.py --check
```

無參數只顯示說明。入口已實作明確的 `--train` 動作；本輪沒有執行，需另行決定真實訓練後才使用。合成報告與規格是不可覆寫的同版證據，詳細測試日誌／耗時及私有guard位於 `.runtime/stage5_review_month_ablation_dispatcher_v1/`。只有Git clone不足以通過真實來源守門。

## 限制與下一步

本輪能證明程式遵守凍結流程，不能證明移除月份改善預測。下一步可決定是否依已綁定入口執行一次三欄真實離線消融，再核對12次fit、獨立選C、18區塊配對與完整manifest；四欄仍沿用原凍結分數。

三個月仍是已檢視的開發窗口，不是新的未知保留測試。原入庫、評分修訂版本與全量核准母體的證據仍缺，固定H60回覆者結果不能外推未知標籤。Stage 5的固定42只供重現；Stage 4維持待資料、每日10%及11／29／42／73／101五種子，事件訊號和Dashboard繼續暫緩。
