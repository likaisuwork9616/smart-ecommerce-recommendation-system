# 測試與驗證

自動測試使用Python標準庫`unittest`，從專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

最近一次完整測試為[完成歷史代表性稽核](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md)的867項全過、165.394秒。其後事件來源查核15項、單日離線交付42項（3.017秒）、[全量日資料契約查核](../docs/STAGE4_OFFLINE_DAILY_ACCEPTANCE.md#full-day-data-contract)8項（0.062秒）均已通過。這些是各前輪紀錄，不能合稱本輪完整測試。

前輪[交接清單與驗收範本](../docs/templates/daily_data_handoff/README.md)只檢查文件與空白格式；範本列出的未來案例尚未執行，不能當成真實資料已驗收。Stage 5可行性盤點12項全過、0.248秒是前輪紀錄；最新資料集凍結另跑23項契約測試全過、3.748秒，未重跑模型全套或訓練。

## 依修改範圍選擇檢查

| 範圍 | 測試內容／入口 |
| --- | --- |
| 特徵與標記 | `test_delay_*features.py`、`test_delay_features.py`；訂單聚合、key、缺值與事件時鐘 |
| 訓練與時間切分 | `test_delay_*training.py`、`test_delay_*validation.py`；成熟答案、同月隔離與query群組 |
| 提醒政策與排名 | `test_delay_alert_policy.py`、`test_delay_calibration_policy.py`及排序測試；完整日分母、取整、ties與未知答案 |
| 實驗與選模 | 各輪`test_*selection.py`及comparison／experiment測試；固定候選、規格與歷史選擇 |
| 診斷與可重現性 | `test_diagnose_*.py`、audit測試；來源綁定、共同漏報身分及分格對帳 |
| 環境與資料庫 | [verify_environment.py](../scripts/verify_environment.py)；此項會讀本機設定與MySQL，與單元測試分開 |

最新Stage 5凍結資料集與逐fit資格：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_dataset_contract -q
```

本組23項涵蓋H端點／成熟嚴格邊界、早答不改挑、同分平手、未知不補0、未來／超H壞評論不得污染、不可定位回答的靜態品質隔離、每個I／F重建、內層最近完整成熟月、完整候選及重疊、nullable CSV逐值反讀、來源SHA／嚴格JSON／不可覆寫、Git忽略路徑與公私輸出全部預檢、實際規格bytes綁定。測試均無模型擬合；原始資料的獨立逐值對帳另見[資料集文件](../docs/STAGE5_REVIEW_DATASET_SPEC.md)。

前輪Stage 5可行性盤點邊界檢查：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_prediction_feasibility -q
```

本組12項涵蓋無評論未知、先首答後查t、早答不改挑晚答、平手／壞時鐘／鍵隔離、score範圍、取消單保留、May截止、回答嚴格早於fit、來源SHA變更及報告不可覆寫。用合成資料核對盤點規則，沒有擬合模型或產生效能成績。

前輪全量日來源盤點的守門檢查：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_audit_daily_data_contract -q
```

本組8項涵蓋嚴格JSON、來源SHA變更、不可覆寫、核准日界、缺失／無效／逆序時間、ID唯一，以及同N錯ID／時鐘／版本與跨組名冊不同。測試只檢查盤點程式的拒收與對帳行為；不代表上游全量日資料或未來live batch契約已通過。

前輪單日離線交付契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_delay_daily_delivery_acceptance tests.test_accept_frozen_daily_delivery -q
```

本組42項（核心25＋CLI／來源／輸出17）涵蓋完整20組、同N錯ID、漏單／重複、時間與版本、finite分數、同分ID升序、9／10／19張的向下取整、未知答案不預濾、原旗標／舊邊界、來源SHA、Git忽略路徑、整批拒覆寫與CSV逐值反讀。合成資料沒有擬合模型，不是新增實驗效能。

來源盤點的時鐘與證據契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_audit_event_source_availability -q
```

本組15項涵蓋截止日、無效／逆序時間、承諾日精度、最終status不能證明取得時間、未知捕獲率保留缺失、schema／時區變更需重驗、ID唯一、來源SHA改變、不可覆寫報告、DB逐表對帳及私有證據路徑不公開。

前輪的歷史母體、固定條件比例與重現契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_delay_history_representativeness tests.test_delay_representation_profiles tests.test_audit_completed_history_representativeness -q
```

本組共37項，涵蓋核准／送達／交運邊界、未知key與零歷史、承諾無效、原窗口橋接、原欄還原、組成權重、五種子、稀疏與三精度篩查，以及完整phase／screen的JSON roundtrip重現。

前一輪的成熟訊號分層比較亦可獨立執行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_delay_conditional_mature_signals tests.test_diagnose_conditional_mature_signals -q
```

此組包含31項合成測試，涵蓋組成反轉、漏報筆數與配對數權重、承諾精度、稀疏覆蓋、五種子身分、ties及跨月篩查。測試中的小型模型擬合是合成資料檢查，不是重新訓練研究模型或取得新回測成績。

## 其他檢查

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\verify_environment.py
```

第二個指令需具備本機MySQL與連線設定；`--execute-notebooks`只執行01–03的副本，詳見[Notebook導覽](../notebooks/README.md)。原始資料／模型／逐筆分數的獨立重算不是單元測試，應依各輪文件執行並將紀錄留在`.runtime/`。

Windows受限執行環境若封鎖暫存目錄或本機執行緒管線，完整測試可能因權限失敗；應在允許這些本機資源的環境以同一程式重跑，不以跳過測試或改動斷言取代。純文件整理則檢查連結、Notebook結構、來源與報告SHA，不需要重跑訓練入口。
