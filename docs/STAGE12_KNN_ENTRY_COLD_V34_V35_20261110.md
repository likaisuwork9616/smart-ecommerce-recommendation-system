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

V34的`--acceptance`已完成，已有不可變收據會拒絕覆寫；`--audit`只核既有人工窗口與直接來源，不重跑查詢。V35診斷也已完成，現在用以下命令重稽核既有窗口，不重新量測：

```powershell
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_diagnostics_v35 --release shop-mysql-runtime/verification/knn-v35-diagnostics-74dce12292714ac8b111a8d6c9fc371e
```

V35的`--measure`會拒絕已存在的request，不提供自動重試；本輪來源、方法、完整日誌與結果均保持不可變。

## 第二階段：cold／validation 診斷規格封存

僅針對原四個context輸入與不變S1表示做獨立觀測，不重跑原48筆、不執行SQL query或fit，也不修改先前不採用結論。規格、來源與時序已封存；觀測器22項小型語義測試通過，完整受監督入口其後亦完成49項正式驗收及唯讀context診斷，實際結果見後文。

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

## 第三階段：完整診斷入口合成驗收完成

正式49／49項通過，失敗／錯誤／跳過均0，包括22項觀測器語義、12項新完整入口、15項通用入口回歸。前後方法SHA與封存plan核對一致；收據時長71.878秒，僅為人工工具驗收時間。

| 完整人工窗口 | 實際結果 |
| --- | --- |
| 頂層入口 | 真正走CLI與contract，stdout／stderr捕捉、先完整來源hash再charged input_setup、外部release不改已關閉window |
| Cold | 4個全新空store，load／prepare／finish、12個診斷指紋＋4個原codec參考核對；原source create與post-lock兩檢查不省略 |
| Validation | 8次B／D呼叫、完整preimage proof及獨立setup，watch總次數及每欄1024取樣位置重算一致 |
| 獨立發布 | worker退出後publisher自己重建context與原指紋，原4次open確認空帳本；原始事件樹與負載重算，五份輸出與停態完整日誌封存 |
| 禁止查詢 | 人工bridge直接禁止sqlite3.connect；沒有SQL query、fit或新排名，空checkpoint records為0 |
| 故障拒絕 | 缺direct source／錯scheme／scope／順序、非正常停止、原始結果／成本樹／負載／log改動、late file、發布收據被改皆拒絕 |

V35的直接來源另明列140個舊專案Python seeds及V33 analyzer／test兩個字串載入目標，避免只以AST漏掉unittest動態載入。原1937／26／15仍不變，封存plan直接來源168，methods168；不是回填舊V31的驗證範圍。

本階段真實context replay仍未開始，沒有新增實測分項或加速比例。完整[入口驗收收據](../reports/stage12/retailrocket_session_knn_v35_diagnostics_acceptance_20261110.json)綁方法、測試log與人工窗口final seal；另有[22項core驗收](../reports/stage12/retailrocket_session_knn_v35_diagnostics_core_acceptance_20261110.json)。提交不變收據後才開唯一真實context診斷窗口。

## 第四階段：原context唯讀診斷完成

唯一窗口`shop-mysql-runtime/verification/knn-v35-diagnostics-74dce12292714ac8b111a8d6c9fc371e`已循序完成，沒有SQL query、fit、新模型validation／bootstrap或原48筆重跑。原始buffers與完整preimage／指紋相同；每次cold保留原source create／post-lock核對，獨立publisher重新建立參考並open四個空store，原始事件與負載重算後才停態封存日誌。本輪沒有使用V32窄範圍log例外。

| 範圍與完整性 | 實際結果 |
| --- | --- |
| 新來源契約 | 2092個source、168個methods；原1937／26／15不改，僅追加 |
| Cold | 4fresh pools／stores：1warmup＋3recorded；12個診斷指紋＋4個原codec參考，8次worker binding全核對、4次publisher open，committed query rows皆0 |
| Codec | 4pairs／8calls：1warmup＋3recorded，完整preimage等價；publisher另獨立完整original指紋1次，不接收worker快照 |
| 一次性inputs | 0.071412秒，位於worker initial hash後、cold之前，獨立計時 |
| 原始維度 | first 234,795、counts 198,946、first_times 234,795、fallback 234,795；每個指紋完整watch 903,335次 |

### Cold細項

以下為三次記錄cycle的中位數，單位秒；warmup另存原報告，不丟棄。inclusive含子層，exclusive僅自身，不能把巢狀欄位再加到父層；不同分項中位數也不保證加總守恆。

| 分項 | inclusive中位秒 | exclusive中位秒 |
| --- | --- | --- |
| 整個cold診斷父層（另含來源／guards／參考核對） | 15.101190 | 0.000032 |
| 原create／post-lock來源核對（巢狀） | 2.341562 | 0.001185 |
| 完整身分與method核對（巢狀） | 0.550608 | 0.550608 |
| 原pre-use guard（巢狀） | 1.681315 | 0.000039 |
| 原final guard（巢狀） | 2.083035 | 0.425415 |
| 額外原codec參考核對（巢狀） | 1.266692 | 0.000008 |
| cold build父層 | 6.640285 | 0.001368 |
| 四個buffer讀取與SHA | 0.026388 | 0.026388 |
| config JSON | 0.000301 | 0.000301 |
| model JSON | 0.068379 | 0.068379 |
| 四次config／model比較canonical | 0.779266 | 0.779266 |
| 兩次保留canonical | 0.391659 | 0.391659 |
| 兩個buffer view | 0.000006 | 0.000006 |
| 原load_context | 2.962002 | 2.962002 |
| 原prepare | 0.811417 | 0.811405 |
| MappingProxyType view建構（巢狀） | 0.000005 | 0.000005 |
| FrozenCatalog建構（巢狀） | 0.000006 | 0.000006 |
| cold預期指紋（巢狀） | 1.728929 | 0.000037 |

| 原buffer | 讀取＋SHA中位秒 |
| --- | --- |
| catalog | 0.013643 |
| config | 0.000829 |
| counts | 0.004949 |
| model | 0.006751 |

| canonical角色 | 每cycle中位秒 |
| --- | --- |
| config三次canonical合計 | 0.008101 |
| model三次canonical合計 | 1.162629 |

角色合計由同cycle原始事件ordinal重算：config為比較兩次＋保留一次，model亦同；這些已包含於上表compare／expected，不是額外工作。原prepare總成本保留全部copy／檢查／排序，MappingProxyType只是view，因此不把view constructor時間當完整copy成本。這些是新觀測scope，不是舊V31 cold exclusive的精確歸因。

下一個cold候選可先評估比較後保留canonical bytes的重用規格；比較與保留分項分別約0.779／0.392秒，但不能因此宣稱整段可省。仍須保留live身分、來源／鎖後核對與最終內容檢查，另做合成驗收及公平比較。

### Validation內部分項與觀測擾動

下表為三次正式D呼叫的中位數，每次只有一個完整指紋；不能直接與原48筆每entry兩個指紋的中位數比較。

| 分項 | 觀測D中位秒 |
| --- | --- |
| exact schema | 0.000002 |
| first遍歷／驗證／row copy | 0.402997 |
| first排序 | 0.018697 |
| counts遍歷／驗證／row copy | 0.371772 |
| counts排序 | 0.017212 |
| first_times遍歷／驗證／copy | 0.264470 |
| fallback遍歷／驗證／copy | 0.352652 |
| 最後watch | 0.000008 |

| 正式pair | 順序 | 原codec B完整call秒 | 觀測codec D完整call秒 | D−B秒 |
| --- | --- | --- | --- | --- |
| 1 | BD | 1.353679 | 1.782428 | 0.428749 |
| 2 | DB | 1.339026 | 1.742072 | 0.403046 |
| 3 | BD | 1.409355 | 1.708954 | 0.299599 |

B完整call中位數 **1.353679秒**，D完整call中位數 **1.742072秒**。完整call包含Counter建構、invocation-local clone與watch報告輸出，不能只以內層snapshot.fingerprint當觀測器全部成本。差值用來看觀測擾動，也可能含配對間負載波動；不是候選加速比例，沒有拿它扣除任何原始時間。

| Watch與計時 | 實際結果 |
| --- | --- |
| 診斷watch報告 | 16份，包含warmup；完整watch 14,453,360次 |
| 每1024次取樣 | 14,112次有計時，14,439,248次未取樣；逐欄calls／取樣位置與總數重算一致 |
| 樣本秒數 | 0.009635300秒，含clock開銷；不是總watch耗時，不外推、不加到gross遍歷 |
| timer校驗 | 獨立256組paired reads保存在setup；只量clock，不代表整個Counter／wrapper開銷，也不作時間校正 |

### 窗口與負載

| 視角 | 實際結果 |
| --- | --- |
| V5受監督窗口 | 278.188000秒，1800秒預算內正常完成 |
| worker／publisher程序 | 173.843153／93.607320秒，沒有重疊 |
| worker完整來源hash | 前44.896381／後33.555625秒；publisher也有前後兩次完整來源hash，另列原事件 |
| 公開JSON序列化 | 0.024033秒，不混入cold或codec分項 |
| 負載 | 12個replay context＋publisher，共707筆，系統CPU依context時長加權平均38.911% |
| 缺口 | 最大取樣間隔1.115477秒，30個目標週期間隔缺失；不補值，不把它分攤到每個row |
| 程序與封存 | exit0、tracked仍存活0；完整final manifest含所有日誌，後續append／新增檔都拒絕 |

負載不涵蓋worker兩次完整hash、一次性input_setup與validation_setup的CPU全程；它們的時間已另列。未量測Ollama token／GPU速度，不能推論因果降速。OS cache沒有清空；fresh只代表新pool／store，非OS cold。新方法清單與觀測開銷亦不同於V31，不以本輪數字重算舊加速或採用門檻。

先前C1-S1不採用結論保持：原48筆含cold七次總和仍為R61.128秒／C62.974秒。本輪只提供下一個候選的工程診斷，沒有新效能採用結果；55／55細層、170筆可比較／232筆歷史查詢不變，完整validation未完成、保留測試鎖定，T_plan空。

[實測成本與全部樣本](../reports/stage12/retailrocket_session_knn_v35_diagnostics_cost_20261110.json) · [停態發布收據](../reports/stage12/retailrocket_session_knn_v35_diagnostics_release_20261110.json)。已完成後`--measure`拒絕新窗口；以`--release shop-mysql-runtime/verification/knn-v35-diagnostics-74dce12292714ac8b111a8d6c9fc371e`重稽核既有結果，不重跑測量。
