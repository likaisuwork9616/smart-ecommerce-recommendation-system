# Stage 5：三欄月份消融實作與洩漏驗證

後續已完成[來源／完整角色串接與執行政策準備驗收](STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md)，並依正式入口完成一次[三欄真實消融](STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)。以下保留本輪合成實作驗證紀錄及原報告bytes。

已依[凍結消融規格](STAGE5_REVIEW_MONTH_ABLATION_SPEC.md)實作只移除 `purchase_month` 的三欄 builder 與 train-only pipeline，保留原四欄程式與凍結分數。本輪用合成資料實際執行前處理、Logistic fit、transform、predict來驗證隔離；**真實資料特徵、訓練、選C、出分與效能計算均為0**，沒有Dashboard。

| 本輪工作 | 實際結果 |
| --- | --- |
| 三欄實作 | 星期、小時、原始核准等待；31個one-hot加1個標準化等待，固定32維 |
| 洩漏／四欄回歸 | 新三欄43項＋原四欄32項，共75項通過，無失敗、錯誤或跳過 |
| 原契約回歸 | H60資料集23項、最小基線20項、月份消融14項，共57項通過 |
| 獨立合成檢查 | 三個fold的內／外層情境共194項檢查通過；此檢查有12次合成fit，不算真實訓練 |
| 驗證CLI對抗案例 | 31項通過；來源改動、測試缺漏／跳過／失敗、輸出碰撞／越界、不可覆寫與嚴格JSON均拒收 |
| 版本保留 | 正式驗證綁定35份公開來源；32份既有來源不變。另以hash確認12份原私有綁定不變，未解析原分數 |
| Stage 4 | 維持待資料、每日10%、五種子11／29／42／73／101 |

正式結果見[合成驗證報告](../reports/stage5/review_month_ablation_pipeline_verification.json)。75項正式測試耗時4.065秒，CLI共5.815秒；57項契約回歸耗時4.555秒。後者第一次在Windows受限環境遇到6項暫存目錄ACL錯誤，允許相同本機資源後以相同測試重跑全過，未跳過或修改舊斷言。兩組合計132項單元測試；194項獨立檢查另列，不混稱全專案測試。

## 實作邊界

[新模組](../scripts/review_month_ablation_pipeline.py)提供 `build_primary_features`、`validate_primary_features` 與 `GuardedReviewMonthAblation`。builder直接從ID、購買與核准時鐘生成三欄，不先建立月份再刪除。星期及小時沿用原naive時鐘，等待為原始小時；沒有補值、log、截尾或新欄位。多餘的評論、配送、最終status與標籤欄不會進入X。

| 部分 | 固定行為 |
| --- | --- |
| 原始特徵 | `purchase_dayofweek`、`purchase_hour`、`approval_wait_hours`，順序及float64固定 |
| 類別編碼 | 星期0–6、小時0–23；固定31維，`drop=None`、`handle_unknown='error'`，未在歷史出現的合法類別仍保留 |
| 等待標準化 | 僅當次合格訓練列估mean／variance，ddof=0，零變異scale=1；未知與query不參與fit |
| 模型 | 沿用L2 Logistic、lbfgs、C候選0.1／1／10及原全部參數；沒有選出實際三欄C |
| 名冊與H60 | 共用原四欄模組的完整名冊、角色、事件時鐘及訓練標籤資格守門，程式bytes受來源鏈保護 |
| 失敗處理 | 每候選／角色一個fresh instance，只能fit一次；錯誤、收斂警告或非法機率使實例失效並清除模型狀態 |

保留 [review_baseline_pipeline.py](../scripts/review_baseline_pipeline.py) 的完整程式及四欄44維介面。新舊實例各自保存encoder、scaler與estimator；共用的是驗證規則。未改原四欄來源守門、訓練入口、評估程式、報告或逐筆分數。

`ApprovalRosterContext`仍須由完整核准名冊建立；同時從raw與membership刪掉一張單也會拒收。這只驗呼叫者與已凍結名冊一致，不能證明上游原始匯出沒有漏單。未來正式執行仍需接來源SHA、私有manifest／收據／guard及完整12角色，不能把呼叫者臨時傳入的子集當完整名冊。

## 洩漏測試驗了什麼

[新增測試](../tests/test_review_month_ablation_pipeline.py)直接操作合成時鐘、答案、極端等待值及完整角色，檢查實際擬合結果與狀態：

- 三欄原始值等於舊四欄去除月份；32維前處理等於舊44維刪掉12個月one-hot欄。月份改變而星期、小時、等待相同時，三欄值保持相同；不宣稱兩個不同模型的機率相同。
- 未知等待離群值不影響scaler或係數；早答但H60尚未成熟者仍排除，未知y不能補0。合格首答需在 `(t,t+60天]` 且嚴格早於fit，H60端點等於fit仍不成熟。
- query七個未來標籤欄任意破壞，不改X或預測；所有未知query仍出分。改動query特徵不改已fit的scaler或係數。
- 名冊漏單、重複、排序／時鐘不符、錯角色或錯fold立即停止；內層候選與外層從頭fit互相隔離。
- 固定類別／維度、float64與有限值、軟體／模型參數、注入的收斂警告、非法機率與正類欄對應均有檢查；失敗實例不能重試或繼續出分。

獨立檢查另外為三個fold的內層／外層建立合成案例，以手算mean／variance與配對特徵核對，不讀真實CSV或重建真實標籤。合成測試沒有計算AP、召回或其他模型效能，也沒有提供移除月份後會改善的證據。

## 操作與證據

在專案根目錄使用鎖定的 `.venv` 執行：

```powershell
.\.venv\Scripts\python.exe scripts\verify_review_month_ablation_pipeline.py
.\.venv\Scripts\python.exe -m unittest tests.test_review_dataset_contract tests.test_review_baseline_contract tests.test_review_month_ablation_contract -q
```

第一行會用合成資料fit兩個實作，不需要Olist原CSV、私有H60檔或原分數。它檢查2份消融父契約、30份公開祖先及3份新程式／測試，確認protocol只差原定五處月份結構，並於測試前後核對SHA。它不沿父規格載入9份原CSV、私有guard或分數，不重新執行歷史資料稽核。

公開報告只列版本、來源、測試名稱／數量與執行界線；同版本只接受相同bytes，不覆寫不同結果。執行時間與詳細日誌保存在Git忽略的 `.runtime/stage5_review_month_ablation_pipeline/last_run.json`。本輪另有私有契約回歸、獨立檢查及來源保留證明；沒有發布任何真實ID、逐筆分數、模型或私有digest。

前輪 [specification](../reports/stage5/review_month_ablation_specification.json) 中 `implementation_status` 及當輪0執行欄位是歷史快照，保持原bytes。後續實作狀態由本文件及新驗證報告記錄，不將合成fit改寫成前輪已訓練。

## 下一步與限制

建議下一步先串接既有來源守門與完整角色名冊，另凍結三欄執行程式、私有輸出版本及同ID配對驗收，再決定是否啟動真實消融訓練。未來三欄須依原內層AP規則自行選C；四欄使用既有凍結分數，不重訓、不重新選C。H60、前處理、未知遮罩、門檻與評估規則不變；任一方指標無定義，配對差值仍為null。

這輪完成的是程式與洩漏契約驗證，月份特徵是否有害仍待實驗。既有月份仍是已檢視開發窗，原入庫／評分修訂版本及未知標籤代表性未獲新證據。Stage 4同ID核准清冊、雙時間版本、日結／入庫與事件訊號繼續待資料，正式提醒及Dashboard暫緩。
