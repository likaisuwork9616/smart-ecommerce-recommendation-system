# Stage 12：C1-S1 原48筆公平比較

## 第一階段：真實入口規格封存

本輪沿用已通過167項合成驗收的C1-S1專用完整快照指紋，新增獨立版本的真實比較入口。第一階段規格封存後，入口合成驗收亦已完成；其後第三階段唯一真實比較也已完成，實際結果見下節。

| 封存項目 | 固定內容 |
| --- | --- |
| 查詢與來源 | 原48筆及順序、2115696 bytes完整payload SHA固定；1261個原閉包來源與15個原binding逐項保留 |
| 每次borrow的方法範圍 | 原17個context methods完整保留，再追加V30五個已驗收方法及V31四個入口／封存／驗收／分析方法，共26個；沒有縮小原method身分驗證 |
| 配對順序 | warm_R、warm_C，再六對RC／CR交替；14份全新帳本，一個worker循序執行；C只有一個cold及六個hit |
| 公平對照 | 同窗口重新執行原R；不把V28歷史耗時當成本輪對照，不挑快窗口、不自動retry |
| 採用門檻 | 六對至少五對完整入口較快、配對節省百分比中位數至少5%、RC及CR兩順序的節省秒數中位數皆正、含cold的七次C總和小於R、primary退步中位數不超過5% |
| 監督與負載 | 同V5絕對1800秒及原資源限制；完整入口與publisher沿用200ms目標取樣，保存原始負載及取樣缺口；不測Ollama token或GPU速度 |
| 來源與完整性 | 四次worker／publisher全閉包核對、每run create與鎖定後完整binding核對、15次live完整快照、原14次publisher open全部保留 |
| 獨立發布 | worker正常退出後，另一程序自己重新載入、prepare並計算新scheme指紋；完整科學bytes／Decimal／delta hex／SQL／成本／事件／負載／停止身分核對後才公開 |
| 啟動限制 | 須先提交封存規格，再完成並提交不變入口合成驗收；已有request或結果禁止新測，完成後僅可release重稽核 |

來源檔、舊方法、原C1未採用結論與保留測試鎖定均保留。只追加新版本方法與證據，不合併C2排序或SQL候選。此為已曝光validation上的工程比較；不是完整validation或最終保留測試成績，55／55細層、170筆可比較／232筆歷史查詢不變，T_plan仍空。

## 操作與證據

真實入口為`scripts/run_retailrocket_session_knn_compare_v31.py`，178項驗收與唯一`--measure`均已完成，既有request阻止重跑。本輪發布與成本分析分別經下節V32／V33補正；目前使用`release_retailrocket_session_knn_v32.py --audit`及`analyze_retailrocket_session_knn_compare_v33.py --audit`核對既有結果，不重跑查詢。原V31發布與分析CLI保留凍結的嚴格拒絕行為，原因見下文。

[規格](../reports/stage12/retailrocket_session_knn_v31_compare_specification_20261110.json)與[封存收據](../reports/stage12/retailrocket_session_knn_v31_compare_seal_20261110.json)綁定原1261／15來源、原17個method、V29規格與V30成功驗收收據SHA。原始資料、模型與執行狀態留在Git忽略路徑。

## 第二階段：真實入口合成驗收完成

正式 **178／178 項測試通過**，失敗／錯誤／跳過均為0，收據計時 179.658 秒。包括新入口11項與V30所選167項新舊回歸；父版70個要求仍逐項對應成功的新S1測試。178是執行次數，V29仍刻意重跑原ContextTests 12項。

| 核對項目 | 實際結果 |
| --- | --- |
| 新入口contract | 8項通過：原1261／15、17舊method完整保留並增至26、完整metadata與scheme、原門檻、新namespace、已有request拒絕重試 |
| 新入口受監督人工窗口 | 3項通過：直接執行新entry worker/publisher，14全新帳本、48筆×14＝672次完整payload核對 |
| 新S1及舊版回歸 | 167項通過，包括V30新增68項、V28／V27原套件及V29診斷回歸 |
| 獨立程序與來源 | worker正常退出後publisher另起新程序，完整閉包前後核對與14次open；人工窗口來源49個、binding25個，與真實1261／15分開列示 |
| 快照與會計 | worker15次live指紋、publisher獨立1次、一個cold六個hit；R無candidate cache，兩臂原fine observer深度一致 |
| 故障拒絕 | 原始payload／成本／事件／負載／收據修改、未停止程序、worker或publisher失敗、既有request及scheme混用均受新舊測試核對 |

這是人工資料上的入口驗收，**本階段真實比較次數仍為0，沒有本輪加速比例**。方法、封存規格、測試log與人工證據描述符均已保存於[入口驗收收據](../reports/stage12/retailrocket_session_knn_v31_compare_acceptance_20261110.json)。下一步在提交不變方法與收據後，才以同批原48筆開唯一循序真實窗口。

## 發布前補正：固定外層日誌的停態封存

原48筆14次循序實測已完成，worker／publisher與外層監督均正常結束，原受監督窗口291.469秒；首次公開release被原嚴格檢查擋下，當時尚未公開配對或採用結果。問題在新入口contract呼叫父版audit的兩行診斷stdout：pipeline退出才將buffer寫入外層`stdout_stderr.log`，獨立publisher封存時該檔仍為空。這是入口日誌生命週期的缺口，原人工bridge直接執行純helper，沒有涵蓋這個頂層contract輸出。

| 已確認內容 | 實際結果 |
| --- | --- |
| 唯一差異 | 原publisher記錄stdout為0bytes／空SHA；停態後450bytes，SHA `f735e41fb16c5418eb0e5a49e7ccf67e43d26f2a129e72ce17cd0cd59d800841` |
| 可重推內容 | 精確兩行既有V29診斷，含CRLF；與凍結entry.specification重新捕捉的輸出逐byte相同，不能接受任意追加 |
| 原窗口保留 | 原方法、request、帳本、事件、成本、負載、publisher結果／五份輸出與停止記錄均不修改；原publisher清單共319份證據，僅日誌一項不同，其餘318份一致 |
| 新停態發布規格 | 限本次唯一namespace與精確0→450bytes；保留舊nested descriptor，頂層新seal綁最終檔案。其他檔案走原strict，完整file集合也不能增減 |
| 合成驗收 | 52／52通過：26項新reconciliation負例／停止／late-write／完整manifest核對＋8項原入口contract＋18項codec；失敗／錯誤／跳過均0 |
| 接續發布 | 提交新規格、方法與驗收後，再以新程序獨立重稽核既有窗口，原1937來源前後額外完整SHA、26方法、672frames、事件／負載／停止身分全部核對；不重跑任何query |
| 時間分列 | 停態重稽核另有300秒唯讀預算與新時間記錄，不延長原實測、不改原291.469秒窗口或單次入口成本 |

[V32嚴格單次補正規格](../reports/stage12/retailrocket_session_knn_v32_release_specification_20261110.json)與[52項驗收收據](../reports/stage12/retailrocket_session_knn_v32_release_acceptance_20261110.json)獨立保存。本階段當時尚未發布採用結論，其後完成的停態重稽核與實測結果見下節；沒有挑重跑或放寬其他證據。

原V31入口與驗收保持凍結，因此原`--release`仍會對中間log描述符嚴格拒絕。本輪完成後應使用新`scripts/release_retailrocket_session_knn_v32.py --audit`重核既有發布；新`--recover`只准第一次發布，不執行query。後續新實測入口應把頂層contract輸出與日誌關閉時序加入一般驗收，不能把本次窄範圍補正當成一般append許可。

## 第三階段：原48筆唯一真實比較完成

本輪 **未通過全部封存採用門檻，維持不採用**。原48筆、14份全新帳本、672次完整保存核對通過；實際僅使用一個worker循序執行，worker正常退出後才啟動獨立publisher，所有受追蹤程序結束後才發布。結果來自本輪已曝光validation工程樣本，不是未知資料或最終保留測試成績。

| 正式配對 | 順序 | R完整入口秒 | C1-S1完整入口秒 | 完整入口節省 | primary退步 |
| --- | --- | --- | --- | --- | --- |
| 1 | RC | 8.181245 | 8.037170 | 1.761% | -5.742% |
| 2 | CR | 9.808955 | 8.301913 | 15.364% | -7.843% |
| 3 | RC | 8.546454 | 7.999198 | 6.403% | -1.077% |
| 4 | CR | 8.253797 | 8.272795 | -0.230% | 1.075% |
| 5 | RC | 8.233086 | 7.909807 | 3.927% | -5.533% |
| 6 | CR | 9.669052 | 8.345967 | 13.684% | -16.783% |

正值節省表示本輪C1-S1較快，負值表示較慢。六對中 **5／6對** 較快，完整入口配對節省百分比中位數 **5.165%**；RC與CR順序節省秒數中位數分別為 **0.323279／1.323086**。primary配對退步百分比中位數為 **-5.637%**，負值表示改善。

| 封存採用門檻 | 本輪判定 |
| --- | --- |
| 至少5／6對完整入口較快 | 通過 |
| 完整入口配對節省中位數至少5% | 通過 |
| RC及CR的節省秒數中位數皆正 | 通過 |
| 含cold的七次C總和小於R | 未通過 |
| primary配對退步中位數不超過5% | 通過 |

全部七次（含warmup與C cold）完整入口總和：**R 61.128117秒，C1-S1 62.973502秒**，總和節省 **-3.019%**。這個總和比例與六對百分比中位數是不同統計量，兩者都完整保留；不以過去V28 C1耗時作本輪公平baseline。

| warmup與cold | R warmup | C1-S1 cold |
| --- | --- | --- |
| 完整入口秒 | 8.435529 | 14.106653 |
| 原setup秒（巢狀） | 3.650893 | 7.919534 |

不能只報六次hit的改善而移除cold；本輪採用判定保留七次總和門檻。

### 成本與快照分項

以下為六次正式配對各臂的中位數，單位秒；同群中位數不必加總相等，巢狀觀測不可再與父層相加。

| 分項 | R中位數秒 | C1-S1中位數秒 |
| --- | --- | --- |
| 完整入口 | 8.400125 | 8.154983 |
| 原setup | 3.724874 | 1.790957 |
| primary | 2.041418 | 1.967795 |
| append扣除commit | 0.147767 | 0.128950 |
| 全部commit | 0.084973 | 0.090077 |
| 來源binding核對（巢狀） | 2.297747 | 2.271902 |
| context load（巢狀） | 2.786515 | 1.720419 |
| prepare（巢狀） | 0.848289 | 0.000006 |

C1-S1互不重疊的identity／pre-use／final guard總和，每次正式入口中位數 **3.427795秒**。

| 快照巢狀分項 | 每次正式C入口中位數秒 | 七次C全部呼叫數（含cold） |
| --- | --- | --- |
| snapshot.fingerprint | 2.582893 | 15 |
| snapshot.validation | 2.049408 | 15 |
| snapshot.json | 0.441362 | 15 |
| snapshot.utf8 | 0.017161 | 15 |
| snapshot.sha256 | 0.056144 | 15 |
| snapshot.release | 0.029967 | 30 |

正式C每個入口有pre與post兩次完整指紋；cold另加一次預期指紋，七次合計15。每次指紋的release分兩子段，所以release合計30次。validation／JSON／UTF8／SHA／release已包含在fingerprint與原guard內；不是可再加上的額外耗時。沒有更少的來源或live完整性檢查。

| 原rank工作分項 | R中位數秒 | C1-S1中位數秒 |
| --- | --- | --- |
| exact_neighbor_selection | 0.066002 | 0.064067 |
| history_and_temp_setup | 0.004878 | 0.005068 |
| neighbor_pool_sha | 0.282865 | 0.266477 |
| prediction_output | 0.038937 | 0.027928 |
| sql_positive_overlaps | 0.470591 | 0.457764 |
| sql_selected_votes_and_accumulation | 0.709822 | 0.671625 |
| top_ten_and_zero_fill | 0.054960 | 0.051594 |

### 完整窗口、來源與負載

| 視角 | 實際結果 |
| --- | --- |
| 受監督窗口 | 291.469000秒，預算1800秒內正常完成 |
| worker程序 | 193.091005秒，包含來源核對、14個完整入口及其餘流程 |
| publisher程序／callback | 96.095294／93.515426秒；與worker沒有重疊 |
| 公開JSON序列化 | 0.376246秒，另列不混入單次查詢或配對入口 |
| 停態發布補正 | 另用68.925038秒重稽核，額外兩次完整1937來源SHA分別32.308480／32.656281秒；不是原窗口或查詢成本，重跑query為0 |
| 來源與binding | 原1261／15精確保留，追加後閉包1937個來源；四次完整閉包、28次worker binding及14次publisher binding核對；每次C仍驗26個method |
| 完整科學與會計 | 672筆完整frames、17棵事件樹與15個原始負載context全部重算一致；四臂payload／Decimal／delta hex／SQL工作量與查詢順序不變 |
| 快照重用 | 1個cold＋6個hit、worker15次完整指紋；publisher獨立重新載入與完整指紋1次、14次原open |
| 程序停止 | 監督exit=0，清理後仍存活0個受追蹤程序 |
| 負載樣本 | entry與publisher共995筆，系統CPU依context時長加權平均38.117%，範圍18.800–84.800% |
| 記憶體與取樣缺口 | 可用記憶體最低17.870GiB，最大取樣間隔0.914417秒，缺20個目標週期間隔 |
| Ollama可觀測範圍 | 有效CPU區間980個，單核心百分比加權平均0.000000%；未量測token／GPU速度，也不能由此估因果降速 |

取樣只涵蓋各完整entry與publisher context，沒有替worker來源雜湊期間補造CPU樣本或插值到每個query。window、程序、callback、完整entry、setup、primary與巢狀分項是不同視角，不能混加；各中位數不能作守恆分解。

本輪結果限於原48筆的工程篩選，**不代表全量或其他負載條件下都有相同比例**。55／55細層、170筆可比較與232筆歷史查詢不變，完整validation尚未完成，最終保留測試仍鎖定、無新fit／validation／bootstrap，T_plan仍空。後續先把外層contract輸出與日誌停態時序納入新入口的一般驗收，並將下節間接綁定的分析helper納入直接來源清單，再依本輪完整入口與cold分項結果決定下一個單獨工程候選；不要把新表示與其他SQL／排序改動混合後沿用本次比例。

### 成本分析方法與來源證明

凍結V31分析入口要求所有helper直接列在request.sources，但`priority_v23.py`實際透過原1937來源中的固定V23成本報告間接綁定，故原入口會拒絕。新增V33只讀分析接合，先驗固定祖先報告的完整描述符、其中唯一helper的path／bytes／SHA與目前檔案精確一致，再沿用原V31其餘七個直接依賴與全部成本／frames／事件／負載重算。

**這不是宣稱該helper曾在原窗口被1937逐檔SHA或26個borrow method直接核對**，也沒有回填原request。V33與其驗收為post-exit分析方法；原V31方法與原成本收據不變。分析輸出明列此來源鏈與直接／間接區別。現用`analyze_retailrocket_session_knn_compare_v33.py --audit`重核成本分析，原V31分析CLI保留嚴格拒絕。

V33的12／12項輕量驗收通過，錯誤祖先、不同helper、重複method與來源變動均拒絕。[分析接合驗收收據](../reports/stage12/retailrocket_session_knn_v33_analysis_acceptance_20261110.json)保留新方法／測試／log身分；本輪V32發布與V33分析的`--audit`都已通過。

[真實成本與全部配對](../reports/stage12/retailrocket_session_knn_v31_compare_cost_20261110.json) · [獨立發布收據](../reports/stage12/retailrocket_session_knn_v31_compare_release_20261110.json) · [成本、完整frames與負載重算](../reports/stage12/retailrocket_session_knn_v31_compare_analysis_20261110.json)

原publisher結果與其中過早封存的stdout描述符原封保留；公開報告的`publication_recovery`另外綁定精確尾端證明與新驗收，頂層evidence綁定完整停態最終檔案。見[V32停態發布收據](../reports/stage12/retailrocket_session_knn_v32_release_recovery_20261110.json)。沒有改寫原始帳本、成本、負載或方法。

唯一namespace：`shop-mysql-runtime/verification/knn-v31-s1-362fcd2ee5da4ae4bf2f5fd5bb9e04c5`。原始資料及完整事件保存在Git忽略路徑；公開報告只存必要聚合及檔案描述符。已完成後`--measure`拒絕重測；原V31 `--release`仍會嚴格拒絕中間log descriptor，本輪使用`release_retailrocket_session_knn_v32.py --audit`及`analyze_retailrocket_session_knn_compare_v33.py --audit`核既有證據。
