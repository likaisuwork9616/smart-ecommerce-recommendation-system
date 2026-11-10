# Stage 12：通用入口與 cold／validation 內部成本

## 第一階段：通用入口與直接來源驗收完成

新增通用機制，沒有修改V31實測、V32窄範圍發布補正或V33事後分析。真正頂層人工CLI已經過contract、worker、publisher、外層監督與停止後finalizer，不再只呼叫純helper測試。正式35／35項通過，失敗／錯誤／跳過皆0；既有收據重稽核也通過。

| 邊界 | 新機制及實際驗收 |
| --- | --- |
| contract診斷 | 同時捕捉stdout／stderr，不向外層活動串流漏出buffer；子程序的contract診斷另存已關閉的JSON，外部重稽核不改舊window |
| publisher封存 | 精確延後root的stdout_stderr.log與publisher.log兩條仍開啟串流；nested同名檔仍須封存，不按basename泛排除 |
| 完整停態 | worker正常退出後publisher獨立執行；外層V5完成、三個writer身分都在tracked且全部停止、五份publisher輸出封存與原subset仍嚴格通過後才finalize |
| 最終日誌 | 首次停態seal涵蓋完整檔案集合與全部日誌；此後任何append、改檔或新增檔都拒絕。沒有一般allow-append，也不套用V32固定450bytes例外 |
| AST來源 | 從磁碟原始bytes遞迴import、函式內import、相對import、package init與literal dynamic import；另封明列16個clone／attribute動態目標；不以sys.modules快取當證明 |
| 無法靜態解析 | project star import、relative dynamic import明確拒絕；非literal dynamic import須有封存的明確目標聲明，不能宣稱已自動證明所有runtime目標 |
| 直接驗證 | priority與其他required source必須直接出現在完整request.sources且path／bytes／SHA相同，再重讀所需Python檔；祖先收據不能代替直接檔案 |
| 保留原清單 | 原1937個source descriptor與26個method不改，只追加；本輪這組入口seeds得到85個直接Python來源，追加18個source成1955，merged methods為86 |

18個新增直接來源包含14個原清單未直接列出的舊helper、一個package init，以及3個本輪入口／驗收方法；不回填或改寫舊實測的來源範圍。驗收逐一拒絕缺priority、缺checkpoint、等大小內容變動、重複／錯型別描述符、路徑逃逸及已載入假module掩蓋缺檔。完整新增清單與SHA保留於[35項入口驗收收據](../reports/stage12/retailrocket_session_knn_v34_entry_acceptance_20261110.json)。

初驗與審閱前的方法／收據副本另存Git忽略路徑；審閱後補上star／relative dynamic與scope核對，最終公開版以35項及目前方法SHA為準。這是人工入口與來源驗收，真實查詢／fit／validation／bootstrap新增次數皆0。先前C1-S1不採用結論不變，55／55細層、170筆可比較／232筆歷史查詢與保留測試鎖定不變。

## 操作

從專案根目錄以`.venv`執行：

```powershell
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_entry_v34 --audit
```

`--acceptance`已完成，已有不可變收據會拒絕覆寫；`--audit`只核既有人工窗口與直接來源，不重跑查詢。通用helper沒有真實measure入口；後續cold／validation診斷會另外封存規格、驗收觀測器後再循序執行。
