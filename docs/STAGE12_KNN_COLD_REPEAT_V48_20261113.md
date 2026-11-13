# Stage 12 V48 第二負載窗口的冷啟動配對

本輪在使用者確認預估時間後啟動。沿用 V47 的同一份 model、config、原固定 48 筆及計量核心，在新的時間窗口重新比較 V39 與 V46。V47 規格、驗收與結果保持原封存；V48 另存規格、驗收、執行命名空間及結果。

## 方法與範圍

兩臂各暖機一次，再跑六對 `CR／RC` 交替排程，共 14 次。每次建立新的 context 與帳本，完整入口包含 reference 建置、原固定 48 筆驗證與 final guard；載入輸入物件、context 關閉與獨立發布各在入口計時之外。這是 context 冷啟動，作業系統快取仍會隨執行自然變動。每次 reference 同時建置 config 與 model。

直接沿用 `retailrocket_session_knn_cold_v47.py` 的 worker、候選接入、計時及 publisher。所有冷入口結束後，仍依相同排程重播 14 次 model 單獨解碼。沒有新增字元或逐筆抽樣；保留 V47 既有系統負載觀測，其成本仍包含在原量測環境中。

新規格綁定 V47 結果的 SHA-256 與原規格、驗收收據。跨窗口發布必須確認來源權威、完整 48 筆 reference、兩臂及排程相同；從各次原始紀錄重算配對摘要，並要求第二個窗口建立於 V47 已退出之後。每個版本只允許一份正式窗口，已有 request 或結果即拒絕重跑。

| 項目 | 本輪安排 |
| --- | --- |
| 時間預估 | 全輪 25–40 分鐘，正式窗口約 10–15 分鐘；依 V47 實測 549.719 秒估算，非本輪成果 |
| 人工驗收 | 沿用候選接入、14 帳本／672 筆／42 次快照及停態反例；另驗證新窗口隔離與跨窗摘要 |
| 實測與比較 | 逐窗列四個計時邊界、六對有號差值、快慢對數、最差退步、執行順序分組及總時間 |
| 採用評估 | 先確認完整入口變慢是否重現，再根據兩窗結果提出工程判斷；不自動切換預設實作 |
| 資料範圍 | 已曝光的固定 48 筆 validation 工程入口；新增 fit 與保留測試均為 0 |

完整入口的節省不能直接除以單獨解碼的節省，解釋成可歸因於解碼的保留比例。兩個窗口的相同 pair 編號只代表相同執行順序，不代表相同主機負載。

## 新入口驗收結果

| 項目 | 實際結果 |
| --- | --- |
| 測試 | 10 項通過，無失敗、錯誤或跳過；六類要求均對應到通過的測試 |
| 候選接入 | config 與 model 均沿用 V47 原／候選工廠，完整 tuple 與來源權威一致 |
| 人工窗口 | 14 次冷入口、14 份帳本、672 筆完整紀錄、42 次快照、14 次解碼重播 |
| 程序與證據 | 獨立發布逐份開啟 14 帳本，9 個受追蹤程序全退出，停態追加日誌與越界建置時點均拒收 |
| 新窗口防護 | 拒絕 V47 namespace 與重複 measure，跨窗來源／排程／摘要竄改拒收；負差、平手、順序分組及暖機分開計算 |
| 耗時與範圍 | 成功驗收的測試與封存 153.354 秒；真實重測 0 次 |

第一次人工測試 10 項全通，但封存時的舊四類要求對照表無法接納 V48 六類要求，因此未產生驗收收據。修正映射後重跑完整驗收，以上結果來自成功封存的一輪。V47 原報告另以 `--audit` 重核通過。

[規格](../reports/stage12/retailrocket_session_knn_v48_cold_specification_20261113.json) · [規格封存](../reports/stage12/retailrocket_session_knn_v48_cold_seal_20261113.json) · [驗收](../reports/stage12/retailrocket_session_knn_v48_cold_acceptance_20261113.json) · [驗收封存](../reports/stage12/retailrocket_session_knn_v48_cold_acceptance_seal_20261113.json)

## 操作

```powershell
.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_cold_v48
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_cold_v48 --acceptance
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_cold_v48 --audit
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_cold_v48 --measure
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_cold_v48 --audit
```

`freeze`、`--acceptance` 及 `--measure` 建立封存後均拒絕再次執行；後續使用對應 `--audit`，不刪除舊 request 或重用 V47 路徑。原始資料、模型與逐筆帳本留在 Git 忽略的本機路徑，公開報告只保存聚合結果與證據描述符。
