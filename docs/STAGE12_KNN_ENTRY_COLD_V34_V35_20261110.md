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

## 第二階段：cold／validation 診斷規格封存

僅針對原四個context輸入與不變S1表示做獨立觀測，不重跑原48筆、不執行SQL query或fit，也不修改先前不採用結論。規格、來源與時序已封存；觀測器22項小型語義測試通過，完整受監督入口另待正式驗收後才能實測。

| 固定設計 | 內容與界線 |
| --- | --- |
| 輸入 | 原counts／catalog／config／model共8,863,434 bytes，完整path／bytes／SHA不變；原1937來源、26methods與15binding只追加，沒有縮小原邊界 |
| Cold循序重播 | 1次warmup＋3次記錄，共4個fresh pool，各一個原ReuseStore，expected_queries=0、required_stages空；每次原create＋鎖後全binding核對、load／prepare／finish，3個完整診斷指紋及1個原codec參考核對 |
| Cold分項 | 四個verified buffers、config／model JSON、4個比較canonical與2個保留canonical、buffer views、原load／prepare總成本、兩個mapping view與FrozenCatalog constructor、cold預期指紋；原prepare bytecode不改，view不冒稱資料copy |
| Validation獨立setup | 另列重建與完整preimage bytes等價證明，不藏在正式call預載裡；這不是新的C1-S1比較或SQL候選 |
| 配對呼叫 | 1個warmup pair＋3個記錄pair，原B與觀測D順序BD、BD、DB、BD，共8calls；每call有相同外層replay.codec.call，包含Counter／clone／report開銷 |
| Validation分項 | exact schema、first／counts遍歷驗證與row copy、兩個sort、first_times／fallback驗證與copy、最後watch；新gross spans包含觀測器，不能直接分攤原V31的2.049408秒 |
| Watch取樣 | 原每一次watch均保留；只每1024次計時並保存逐欄counter及取樣位置，樣本含計時開銷；不外推總watch、不從gross遍歷扣除、不當加速比例 |
| 守恆 | 每棵原始事件樹重算inclusive／exclusive，父子層不能重複加總；另量孤立256組timer reads，只作校驗、不修正原耗時 |
| 監督與獨立發布 | 同V5 1800秒與原資源限制，一worker循序；worker／publisher前後四次完整來源SHA；publisher自己重建preimage／digest，原4次open確認空帳本與binding，再以V34停態封存完整日誌 |
| 不重試 | 唯一knn-v35-diagnostics namespace；已存在request禁止自動再測，完成後release只核既有結果。所有warmup與記錄值都保存，不挑快樣本 |

此診斷的直接Python來源 **168個**，spec plan合併來源 **1969個**、methods **168個**；正式activation還會追加本輪驗收與人工證據。這是新診斷的身分範圍，不回填原V31。

原V31背景：cold_build 6.111406秒，原load 2.844051秒、prepare 0.828289秒、cold預期指紋1.219879秒，cold exclusive其餘1.219187秒。這些是已保存的舊scope，不能把新replay分項百分比套回去推算舊成本。OS檔案快取不清空；fresh是pool／store生命週期，不宣稱OS cold。

[診斷規格](../reports/stage12/retailrocket_session_knn_v35_diagnostics_specification_20261110.json)與[規格seal](../reports/stage12/retailrocket_session_knn_v35_diagnostics_seal_20261110.json)保存完整source plan、固定順序、零query範圍與環境。完整入口驗收及真實context replay仍待後續階段；保留測試鎖定，T_plan空。
