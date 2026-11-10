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

## 第二階段：保留時點的安全候選規格封存

候選`C1-S1-cold-canonical-source-anchor-v1`只完成設計，沒有實作或候選驗收。已封存24個新增待驗要求，另外繼承原C1-S1／V34／V35的身分、來源、內容、科學bytes及停態發布條件。

1. 原early順序與short-circuit行為不變：config live/source兩次完整canonical，再model兩次。
2. 將已比對通過、來自exact verified buffers解析結果的不可變canonical bytes作固定權威，不保留可變alias、不從變更後caller更新baseline。
3. 原load_context與prepare bytecode不改。
4. **在原after-prepare位置仍完整canonical live config／model，與固定來源bytes比對；在cache.use、borrow返回或任何query body前完成。**任何差異即poison，清prepared／key／expected／owner／active，不重試。
5. 原每次final live config／model canonical、snapshot與owner核對不變；同worker一cold六hits、15個live snapshot與22個digest仍保留。
6. future method／request／事件／receipt／publisher綁定新policy，mixed policy拒絕；所有舊來源與methods只追加，不回填舊報告。

安全路徑cold canonical仍6次、七次generic canonical仍41次。直接6→4明確未由本規格放行：必須另證涵蓋callee／watch／observer／外部alias的封閉不可變所有權，或另外制定同late時點完整canonical-equivalent typed內容比較。後者是新演算法，不能混稱純bytes重用。

24項待驗要求涵蓋來源基準、early／late／ABA邊界、bool／int／float hex／signed zero／tuple等完整型別、late unsupported值借出前拒絕、失敗poison、全部來源鎖後及publisher、完整時間會計與不隱藏預載。六個已通過測試只證明原guard反例，**不是這24項候選驗收已通過**。

未來有明確實作指示後仍須使用新檔、合成驗收與不可變方法收據；真實比較入口另封，再對同批原48筆新鮮對照。此輪新實作／候選測試／真實context replay／query均0，沒有可量測加速，T_plan仍空。

[安全候選規格](../reports/stage12/retailrocket_session_knn_v36_canonical_specification_20261110.json) · [封存seal](../reports/stage12/retailrocket_session_knn_v36_canonical_seal_20261110.json)

```powershell
.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_canonical_v36 --audit
```

`--audit`只核既有事件、原guard測試log、方法與封存內容，不重跑測試或context；已有盤點／規格拒絕覆寫，沒有candidate／measure開關。
