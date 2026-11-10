# Stage 12：cold canonical bytes 重用候選

## 第一階段：成本與原時點保護盤點

只讀V35已保存的四個cold cycle，三個正式cycle分角色重算；沒有重跑真實context或48筆。原C1 tinyfixture的6個時點反例測試通過，這是原行為盤點，不是候選實作或候選驗收。

| 原cold canonical角色 | 三次正式觀測中位秒 |
| --- | --- |
| live_config_initial | 0.0016917 |
| source_config_initial | 0.0011457 |
| live_model_initial | 0.3809437 |
| source_model_initial | 0.3683051 |
| live_config_after_load_prepare | 0.0050620 |
| live_model_after_load_prepare | 0.3865975 |

原四次live／verified source比較合計中位數 0.7792660秒；原load／prepare後兩次live重新編碼合計 **0.3916595秒**。保存bytes為config 36,375與model 4,566,194，共 **4,602,569 bytes**，四個cycle的late身份皆一致。V35沒有分別捕捉早期四次輸出，不能把late bytes冒稱early逐次實測。

## 直接6→4的反例

原程式不是單純重複存同一個值：early live/source比較時為A；初始化過程變B；after-prepare late canonical保存B；final前還原A。原final拿A對B會拒絕並poison，但盲目保留early A後只在final比A會放行。

| 小型原行為測試 | 實際結果與界線 |
| --- | --- |
| config於load期間A→B，再於final前B→A | 原load確實保存B，原finish拒絕並poison；naive early-A比較為真 |
| model完整metadata於prepare期間A→B→A | 同樣證實ABA漏檢風險，沒有靠loader欄位錯誤假通過 |
| 初始化後持續B | 原單次load／finish的late baseline可接受B；下一次identity仍可能拒絕，不代表完整七次／發布放行。固定來源基準會在本次借出前更早拒絕 |
| late時點前已恢復A | 原離散guard可通過，不宣稱能檢出所有瞬時變動 |
| late NaN／custom value | 原load在cache.use／borrow前就拒絕並清除狀態，不能只延後到final |

因此約0.392秒只能作含觀測擾動的成本背景，不能當可直接節省的時間。保留時點與內容保護優先於刪呼叫數；安全設計會保留原late位置的兩次完整live canonical，新增與validated source bytes比對，成功後才借出。cold仍為6次canonical，6→4須另證不可變所有權或另立完整typed comparator演算法規格。

原2092 sources／168 methods、內含原1937／26及15 binding描述符皆只保留／追加。身分key、鎖後完整來源核對、所有final live內容檢查、15次snapshot檢查與獨立publisher／停態日誌封存都不能移除。這輪沒有改舊方法、沒有候選測速，先前C1-S1不採用、55／55細層、170／232查詢與保留測試鎖定不變。

[成本與原guard反例盤點收據](../reports/stage12/retailrocket_session_knn_v36_canonical_inventory_20261110.json)保存原方法／事件／測試log與成功ID。下一階段封存完整安全候選與未解除的工程前提。
