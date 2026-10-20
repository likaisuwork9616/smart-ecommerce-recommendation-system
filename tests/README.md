# 測試與驗證

自動測試使用Python標準庫`unittest`，從專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

最近[完成歷史代表性稽核](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md)完整執行867項測試通過，165.394秒，含本輪新增37項；這是實際紀錄，不代表之後每次文件編輯都重跑相同實驗。

## 依修改範圍選擇檢查

| 範圍 | 測試內容／入口 |
| --- | --- |
| 特徵與標記 | `test_delay_*features.py`、`test_delay_features.py`；訂單聚合、key、缺值與事件時鐘 |
| 訓練與時間切分 | `test_delay_*training.py`、`test_delay_*validation.py`；成熟答案、同月隔離與query群組 |
| 提醒政策與排名 | `test_delay_alert_policy.py`、`test_delay_calibration_policy.py`及排序測試；完整日分母、取整、ties與未知答案 |
| 實驗與選模 | 各輪`test_*selection.py`及comparison／experiment測試；固定候選、規格與歷史選擇 |
| 診斷與可重現性 | `test_diagnose_*.py`、audit測試；來源綁定、共同漏報身分及分格對帳 |
| 環境與資料庫 | [verify_environment.py](../scripts/verify_environment.py)；此項會讀本機設定與MySQL，與單元測試分開 |

例如只檢查最近的歷史母體、固定條件比例與重現契約：

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
