# V74｜K1 最小接入規格、人工案例與確認範圍

依[V73方法與責任提案](STAGE12_KNN_FULL_METHOD_PROPOSAL_V73_20261116.md)，本輪只整理接入規格、案例清單、驗收條件與估時。只讀既有文件、程式／測試文字及公開收據；沒有匯入研究程式、建立工具或fixture、執行測試、量測、環境探測、Linux安裝或真實資料重跑。**依使用者本次要求，須確認本提案後才準備工具。** 文件與Git提交不表示已確認後續實作／執行。

## 最小範圍：先做只能使用人工資料的接入

下一輪提案限於Windows、V73歷史runtime相容目標、V2完整反讀／CP＋V4精確核心。首次fresh DB、同run有效prefix恢復、原序來源掃描、frozen exact、原global＋bootstrap同一完成單元均保留。C1-S1／V39／V46、indexed resume、Linux、1ms／B／C／D量測不納入。

真實科學對象仍是166,897 queries／62,235 visitors／原2,000 draws，但**不提供可執行的真實profile或全量CLI**。人工request使用封存fixture自己的N／visitor數及人工原始2,000 draws；不能把人工N填成166,897，也不能用synthetic標記放行真實路徑。人工驗收成功只證接入行為，不解除全量no-go或`T_plan=null`。

| 元件 | 最小介面與責任 | 明確不做／尚待證明 |
| --- | --- | --- |
| M0 人工來源admission | 只接受封存bundle ID／manifest／seal；核generator、參照方法、輸入角色、相對路徑白名單、bytes／SHA、N／visitors／draws與新方法閉包；將核准request交給pipeline | 不接受任意primary／DB路徑或caller覆寫N；marker單獨不足。資料路徑越界／別名逃逸在讀科學資料前拒絕；方法來源可在repo白名單，與fixture資料清單分開 |
| M1 全來源worker adapter | 新版本以V2全序verifier接V4 predict／terms，使用完整人工原序，fresh DB與每attempt cache重置；保留全部四臂內容、精確值、EOF、global／原draw核對 | 不呼≤64的verify_selected代替全流，不修改舊48／64限制，不改frozen方法、不monkey-patch舊模組；不把原主要helper匯入待驗worker |
| M2 新CP完成guard | 新版本CP子類覆寫私有`_complete_checks`：要求持有writer，先呼原實作保留來源／鏈／stage檢查，再核queries的run／ledger／N／EOF；保留原finalize的同鎖採認與提交順序 | 這是待驗私有介面接入，非既有public guard參數；不複製另一套任意完成規則。新guard也作用於P7 write_candidate及B4 supersede，不能只驗P8 |
| M3 supervisor／人工pipeline | 接M0、M1、M2與原CP正常退出規則；分別保存停止請求、實際觀察退出及恢復episode；保留同run絕對期限／含離線累積預算 | 假時鐘用於期限邊界；真子程序只在人工流程驗退出／崩潰，不作效能或時鐘能力校準；不新增Job Object／物理斷電主張 |
| M4 唯讀publisher | 另一程序讀原request／binding／candidate／CP acceptance／完整鏈／stage與結果身分；H7／H8前後驗來源，寫自己的proof與日誌 | 不改已接受的科學namespace，不接worker記憶體成功token、不只信摘要；不得呼排名或數值global／draw重播。新全量形狀proof adapter尚未存在 |
| M5 外部finalizer | 確認全部內部writer停止／日誌關閉，反核proof、完整檔案集合，將manifest／seal與公開人工結果寫在被封存namespace外 | 不自我hash、不封存後寫回內部、不套V32窄例外修成成功；缺少、追加、變更或仍存活均拒收 |

六元件是責任界面，不要求硬拆六個檔案。實作可沿現有模組分工，但新來源／方法身分、介面與私有hook依賴必須在執行前封存；舊程式、契約及結果不可原地修改。初期人工測試與入口都須保留real execution disabled。

## Request、輸出與完成條件

人工request最少包含：`profile=synthetic_only`、fixture ID、generator／oracle／新方法描述、bundle seal、資料與方法各自白名單、來源角色、`expected_queries=N`、`expected_visitors=V`、`bootstrap_replicates=2000`、四個required stages、run／binding身分、期限與總預算。數量欄位必須是exact int，不接受bool／float冒充；EOF必須是exact bool True。

至少一個人工完整流程固定N=129、V=3；其他小型完整流程N由各自封存manifest給定且不超過129。核心邊界向量另外列訓練／鄰居規模，不能以129當501鄰居向量的訓練上限。所有fixture檔案數、bytes、訓練規模與子案例ID在正式驗收前固定；若需要擴大已核准範圍，先回報，不為通過暗改manifest。

四個required stages固定`reconstruction／queries／global／bootstrap`。M2在同一writer鎖內核queries stage的run、完整ledger摘要、N與paired EOF，回傳本次採認的summary／stages；候選引用由原finalize／supersede在候選已存在時核對。首次write_candidate不能要求尚未建立的candidate先存在，也不能用鎖外預查的舊副本。新子類不改原H1–H6來源核對與正常退出行為。P6仍先Fold、再人工原始2,000 draws、再aggregate比對，最後封存兩個stage；不新增draw checkpoint。

人工科學payload、Decimal字串及binary delta與封存golden逐位元核對；不同run的PID／時鐘／run ID等控制metadata按其自身規則核對，不要求整份receipt bytes相同。私有原始人工檔案與程序證據放Git忽略的獨立目錄；公開僅保存方法／案例映射、聚合判定、描述符與限制，並清楚標synthetic。

科學namespace、publisher自己的證據目錄、外部控制／finalseal路徑明確分工。P9可以寫自己的proof，但不能改CP已接受內容；P10封存所有內部證據後只寫外部交付。B6只能補尚缺發布，不再啟動worker。整套人工流程成功須同時具有正常退出、CP acceptance、publisher proof及外部停態交付；candidate或CP acceptance單獨不代表整套成功。

## 固定驗收關卡

| ID | 通過條件 | 不能取代的證據 |
| --- | --- | --- |
| G0 範圍／身分 | 人工bundle、方法／runtime、直接來源及新request均精確相符；非人工／越界路徑在科學讀取或worker啟動前拒收 | 不以自報marker或現場重算的hash另建信任起點 |
| G1 內容與完整流 | 手算／凍結oracle對照成立；129筆完整原序、四臂payload與分母、七路EOF、原2,000人工draw與aggregate一致 | 不只比top10、不借工程self-reference，不把129稱166,897通過 |
| G2 保存／恢復 | 同run有效DB／連續鏈才恢復；所有必要中斷點重播後科學payload一致；損壞拒收、未提交證據保留 | 不以檔案存在、latest或source-only位置當有效prefix |
| G3 鎖內完成 | P7／P8／B4皆經新guard；query seal存在但內容錯誤也拒收；正常退出與candidate／ledger／stage身分一致 | 要證明語義負例確實到達新guard，不能只被舊SHA拒收 |
| G4 來源／發布 | 正常路徑H1–H8實際位置正確；publisher反核原始證據矛盾、前後來源變更，且不重算排名或數值global／draw | 恢復／失敗次數另記，不硬湊8；不以摘要或worker token替代 |
| G5 停態交付 | 內部writer全停止、日誌完全關閉、完整集合／bytes相符，外部seal與公開結果無自循環 | 活程序、晚追加、新檔／漏檔等不能留下整套成功 |
| G6 失敗／期限 | 預期拒收／故障與意外失敗分開；假時鐘／資源警報及真程序退出案例守同run預算；未執行項保留缺失 | 不重新計時、追補退出、不因超時刪案例或放寬條件 |
| G7 計帳與報告 | 假區間驗互斥帳與有號餘額；每個必要子案例有方法／輸入／預期／實際證據，總結可反核 | 不加總舊測試數冒充新通過，不產生真實成本／開銷／T_plan或效果結論 |

任何必要子情境未執行、意外失敗、資料／方法身分不一致或證據缺失，整關只能是failed／incomplete，不能以其他通過項抵銷。負例通過須同時證明預期拒收位置、未新增不應存在的成功收據，以及應保留的原證據未變；不能只檢查有例外。

規格依據：[V2反讀](../scripts/retailrocket_session_knn_readback_v2.py)、[CP完成路徑](../scripts/retailrocket_session_knn_checkpoint_v2.py)、[V4有限入口](../scripts/retailrocket_session_knn_pair_v4.py)、[原人工fixture與獨立參照](../tests/test_retailrocket_session_knn_readback_v2.py)、[V34停態元件](../scripts/retailrocket_session_knn_entry_v34.py)。本輪只讀這些檔案文字。

## 人工資料與參照先封存

以下三組只有規格，尚未產生檔案。F-small用手算鄰居／精確分數／四臂內容與分母；F-long固定**129 queries、3 visitors，分別70／40／19筆**，使同visitor跨63→64及127→128。正常假時鐘未達120秒，應提交64／64／1三個chunks。F-edge沿既有V4向量處理499／500／501鄰居與精確核心邊界，不把大鄰居負載套到F-long每筆。129只驗完整流程語義，不代表166,897筆的容量或成本。

沿既有測試模式，由測試專用人工primary builder產出待驗對象，再用凍結V1 oracle核定、V2參照核對完整golden；新worker不得匯入原主要helper。人工原始2,000 draws與golden在候選執行前封存，由原check_bootstrap核對，不能讓新adapter製作自己的expected或重抽到相符。每個必要子情境在正式驗收前固定ID、輸入／方法身分、變更內容、預期結果／拒收位置及應保存證據。

## 待建人工案例清單

以下是**24個案例族**，不是24項已存在或已通過測試。每族含多個必要子情境，實際子案例數待工具準備時封存。對照中的D／P／H／B沿用V73，G沿用本輪關卡；完整逐項映射見案例規劃收據。

| ID／案例族 | 必要設定／負例 | 驗收條件與證據 | 關卡；V73對應 |
| --- | --- | --- | --- |
| A01 人工入口隔離 | 合法bundle；缺人工標記、real profile、任意N／偽造166897、路徑越界及symlink／junction別名逃逸。負例用人工哨兵檔，不讀真實資料。 | 合法人工N才放行；負例在科學資料讀取／spawn前拒絕，無真實全量通過狀態。 | G0；D0, D2, P0, B0, B7 |
| A02 方法與runtime身分 | 完整封存描述符；漏直接helper、未宣告dynamic target、同大小方法變更及runtime不符。 | 不符即拒絕；已匯入模組或祖先報告不能替代直接來源。 | G0, G4；D0, D6, P0, H1, H2, H3, H4, H5, H6, H7, H8 |
| A03 手算與四臂 | F-small含完整history、current／next、targets及可達分母。 | 完整payload、Decimal字串、binary delta對封存golden一致，不只top10。 | G1；D2, P2, P3, P4, P5, P6, B0 |
| A04 V4精確核心邊界 | F-edge涵蓋499／500／501鄰居、ties、unknown／self／future／fallback、未約分比例、大ID、近等比率及4096-bit Fraction回退。 | 新呼叫點對凍結oracle／V2結果；保留完整pool、零票補集與精確排序。 | G1；D2, P4 |
| A05 完整流與三chunk | F-long的129筆／3 visitors，原序無selected ordinals；假時鐘未達120秒。 | 完整129筆、64／64／1 chunks、逐筆golden、七路EOF、四required stages與完整發布成立。 | G1, G2, G5；D2, D3, D4, D8, P0, P1, P2, P3, P4, P5, P6, P7, P8, P9, P10, B0 |
| A06 七路配對與角色 | 七路各自缺列、多列、重複／錯序／錯key；reserved角色放不可解碼內容。 | 配對／EOF異常拒收；非允許角色先分流而不解碼；無新candidate或最終成功。 | G0, G1；D2, D4, P3, P4, P5 |
| A07 cache生命週期 | 命中／未命中、完整target count差異、Decimal context變更、返回dict被改、同run新attempt。 | 值與fallback保持凍結語義，防返回副本污染；每attempt重建cache，不作checkpoint。 | G1, G2；D2, D3, P3, P4, P7 |
| A08 fresh與未封存DB | 正常重建；建立中斷留下DB／journal；別run的舊DB。 | 完整support／sessions／postings／lineage／fit audit及integrity／close／seal；半成品保留再fresh，拒借別run。 | G1, G2；D1, D5, P2, B0, B1 |
| A09 sealed DB身分 | 有效同run；同大小DB竄改、缺artifact、多journal、來源／runtime變更。 | 僅完整有效seal可復用；負例在query前拒絕，檔案存在不足。 | G0, G2；D1, D3, D5, P1, P2, P3, B2, B7 |
| A10 64／120安全邊界 | 假時鐘下第63／64／65筆；query內跨120秒；EOF短尾段。 | 只在完整query安全點提交；EOF可flush不足64筆，不宣稱兩分鐘損失上限。 | G2；D3, D4, P4, P5, B2 |
| A11 append／commit故障 | append前後、payload半寫、fsync後manifest前、manifest後latest前。 | 未提交尾段保留重算；已提交鏈可越過舊latest恢復；最終科學bytes等於不中斷golden。 | G2；D3, D4, P4, P5, B2 |
| A12 真程序prefix恢復 | F-long已提交64筆後於pending query強退；另測錯prefix key／gap／chain SHA。 | 只跳有效64筆，重算尾段到129；損壞拒收，不以source-only位置或子集ordinal代替prefix。 | G2, G6；D3, D7, P1, P3, P4, P5, B2, B7 |
| A13 P6合併單元中斷 | Fold中、原draw中、global seal後bootstrap seal前中斷。 | 每次完整重啟P6並核舊部分seal一致；無draw checkpoint，最終對golden一致。 | G1, G2；D4, P6, B3 |
| A14 人工原始2000 draws | 改順序、draw SHA、query denominator、RNG前後state、delta、缺／多draw。 | 由原check_bootstrap核恰2000筆及aggregate；負例拒收，不能重抽或改用self-reference。 | G1；D4, P6, B3, B7 |
| A15 鎖內queries語義 | 合法；缺stage、錯N／bool／float N、EOF false／非bool、run／ledger／candidate錯配；open後writer鎖前改stage。P7／P8／B4逐一涵蓋。 | 同步改人工hash／引用讓負例確實到新guard；同鎖核當次完整摘要。首次write_candidate不要求candidate先存在；既存candidate由原finalize／supersede核對。 | G3；D4, D8, P7, P8, B4, B5, B7 |
| A16 退出與程序身分 | candidate存在但worker活著、exit非0、PID重用、權限未知、初次異boot且無可信正常退出。 | 均不得acceptance；只有獨立記錄的真正正常退出才可完成，不能由candidate推定。 | G3, G6；D7, D8, P7, P8, B4, B5, B7 |
| A17 candidate後真程序強退 | 寫candidate後強退，缺normal-exit收據。 | 保留orphan與未知退出；確認舊程序不活後，新worker完整重播P6、產新candidate並正常退出；不借舊exit碼。 | G2, G3, G6；D7, D8, P7, P8, B4 |
| A18 正常退出後finalize中斷 | normal_worker_exit已保存，acceptance原子提交前故障。 | 只重入supervisor finalize，保留退出收據，不supersede、不重啟科學worker、不重設預算。 | G2, G3；D7, D8, P8, B5 |
| A19 八個來源核對位置 | 正常trace；H1–H8各前方同大小來源變更；恢復分episode。 | 正常六CP＋兩publisher核對位置與phase正確；每個變更拒收，恢復／失敗次數如實另記。 | G4, G7；D6, D9, P1, P7, P8, P9, H1, H2, H3, H4, H5, H6, H7, H8 |
| A20 publisher原始證據 | 改request／candidate／CP／stage／ledger／roster計數或摘要；測試專用spy令predict或global／draw數值重播即失敗。 | 原證據矛盾拒收，負例須到新proof檢查；合法proof的排名／數值重播呼叫0，不只信摘要。 | G4, G7；D8, D9, P9, B6, B7 |
| A21 停態與完整集合 | pipeline／publisher緩衝日誌關閉；活writer、新檔、漏檔、封存後append／bytes變更、外部finalseal。 | 合法晚flush納入最終集合；壞例拒收，無自含hash；封存後內部bytes不變。 | G5；D8, P10, B6, B7 |
| A22 CP完成後外層恢復 | CP acceptance後P9／P10中斷或外部公開提交前故障；另測整套成功後重入。 | 只補缺發布；CP／科學bytes不變、worker／ranking／draw重播0；完成後禁止再執行，允許唯讀核對。 | G2, G5；D8, P9, P10, B6, B7 |
| A23 期限資源與監督 | 假時鐘deadline、含離線總預算、UTC rollback；假RSS／磁碟／TEMP警報與監控失敗，涵蓋P9／P10。 | 安全點停止；停止請求與實際退出分列，清理所記錄子程序；不宣稱Job Object，不新增成功、不延長或重設預算。 | G6；D5, D7, D9, P0, P1, P2, P3, P4, P5, P6, P7, P8, P9, P10, B7 |
| A24 互斥帳與有號餘額 | 假事件樹rank⊂verify、commit⊂append／tail、P6子段、H calls、監督重疊、signed bridge與恢復episode。 | 已知人工區間各算一次且依帳法守恆；有號餘額不截零，未知不稱CPU等待；不產生實機成本或T_plan。 | G7；D9, P0, P1, P2, P3, P4, P5, P6, P7, P8, P9, P10, H1, H2, H3, H4, H5, H6, H7, H8, B2, B3, B4, B5, B6 |

A15的語義負例及A20的原證據負例必須實際到達新guard／publisher；早被舊hash核對擋下，不能算新增覆蓋。不同run只要求科學payload逐位元一致；控制metadata另核身分與順序。舊39／185等通過數不相加為本輪新案例數。

案例依據僅閱讀既有[V2測試](../tests/test_retailrocket_session_knn_readback_v2.py)、[V4接入測試](../tests/test_retailrocket_session_knn_pair_v4.py)、[CP故障／正常退出測試](../tests/test_retailrocket_session_knn_checkpoint_v2.py)、[精確SQL向量](../tests/test_retailrocket_session_knn_sql_v4.py)、[cache向量](../tests/test_retailrocket_session_knn_checks_v4.py)、[來源／停態測試](../tests/test_retailrocket_session_knn_entry_v34.py)及[原draw核對](../scripts/retailrocket_directed_oracle.py)文字。本輪未執行它們。

## 預估工作量與執行截止

下表是開發工作量判斷，不是實測或完成保證。新增guard、publisher／finalizer及恢復分支的接合是主要不確定處。維持每個完成小步驟更新README、繁體中文commit、推main；正式執行前工具與人工案例必須已封存並推送。

| 下一輪工作 | 預估工作時間 |
| --- | ---: |
| adapter、鎖內guard、人工來源限制、pipeline與發布接入 | 90–150分鐘 |
| 人工fixture、案例映射、假時鐘與程序故障接入 | 45–90分鐘 |
| 靜態複核、有限修正、合成驗收、收據／README／Git | 30–60分鐘 |
| 合計 | **165–300分鐘，約3–5小時** |

合成執行已包含在30–60分鐘的審閱／驗收／交付項目及總估計中，不再疊加。僅供估時背景的既有人工驗收紀錄如下，方法／案例不同，不能按案例數線性外推：

| 既有收據 | 原測試數 | 實際耗時欄位／秒 |
| --- | ---: | ---: |
| [V2](../reports/stage12/retailrocket_session_knn_v2_synthetic_acceptance_20261103.json) | 185 | `elapsed_seconds`／85.631 |
| [V39](../reports/stage12/retailrocket_session_knn_v39_typed_acceptance_20261110.json) | 165 | `seconds`／98.602 |
| [V40](../reports/stage12/retailrocket_session_knn_v40_compare_acceptance_20261111.json) | 9 | `seconds`／76.751 |
| [V48](../reports/stage12/retailrocket_session_knn_v48_cold_acceptance_20261113.json) | 10 | `seconds`／153.354 |

V4 pair既有39項通過收據沒有獨立耗時欄位，本輪不補造秒數。上述原收據均記0 failure／error／skip；它們不表示新接入已通過。

提議正式人工驗收正常執行約**2–10分鐘，每個封存版本15分鐘成功截止**。窗口從人工bundle接入開始，包含來源核對、所有必要子程序／故障恢復、publisher／finalizer及必要收據保存；fixture與golden的建立封存在窗口前，已包含於工作估計。每個子程序watchdog最多120秒並受整輪剩餘預算限制；假時鐘越界不靠實際等待120秒模擬。這些是待確認限制，並非已測得時間或OS保證。

- 預期故障／退出碼／拒收符合封存預期且證據完整，才算該負例通過；意外失敗立即停止該版，未執行項列缺失，整版failed／incomplete。
- 提案最多兩個正式版本，每版僅一次正式窗口：初驗，以及新工具／人工案例確有範圍內實作錯誤時的一次修正版。允許更新這些新檔案及封存SHA，但不得改凍結方法、科學規則、來源權威、驗收門檻或縮減必要案例。保留失敗收據與版本差異，另版封存並更新README／commit／push後，第二版重新執行該版完整必要案例；不得拼接兩版通過項。已通過不重跑。
- 每版15分鐘，最多兩版合計30分鐘，均已計入工作估計。**正式窗口意外超時／掛住不補跑**；案例刻意觸發的假期限／拒收符合預期仍可通過。到期只允許安全清理與保存失敗紀錄，不延長科學工作或成功窗口。第二版失敗即停止回報。30分鐘是成功執行預算，不是OS返回保證；清理／保存超出截止的實際時間另記。
- 來源授權／身分不明、需改凍結科學方法或擴大已確認範圍時停止修訂提案。預期負例中的來源變更不算此類意外。不得縮案例、放寬門檻、重設同run預算或挑最快結果。
- 準備工作達300分鐘仍未完整封存就停止回報，不為趕時間執行未完整案例。若已在正式驗收中，仍須遵守較早到達的已確認期限。截止後的安全清理及失敗紀錄不算成功期限延長。

## 待使用者確認的具體範圍

建議下一輪確認範圍為：**準備只能接受人工bundle的六元件最小接入、三組人工資料與24族必要子案例；封存工具／案例後，依上述期限執行合成驗收及必要的一次範圍內修正版。** 這包含假時鐘／資源行為、人工真子程序退出、完整輸出／恢復／來源與發布驗證；不包含實機時鐘校準或效能／容量量測。

確認依據是使用者本次「確認後再準備工具」指示；本輪尚未取得確認。Linux、B／C／D、真實model、原固定48筆、真實166,897筆反讀、新主要bootstrap與V46採用均不在這次提案內。人工驗收不能解除真實全量no-go；全量內容、真實容量／資源與T_plan仍待另案，K1−C1結論仍未完成。每日10%提醒的資料缺口與優先順序沿V71，Dashboard仍待適用程度確認。

## 本輪進度

| 小步驟 | 狀態 |
| --- | --- |
| 1. 最小接入規格 | 六元件、request／輸出契約及G0–G7已列；獨立靜態複核通過 |
| 2. 人工案例、估時與確認 | 已列24案例族、三組人工資料、3–5小時估計與有限執行提案；案例／估時獨立靜態複核通過 |
| 工具／fixture／測試／量測 | 全部0；等待使用者確認後才準備 |

[最小接入規格收據](../reports/mainline/v74_k1_minimal_integration_spec_20261116.json)

[人工案例、估時與確認收據](../reports/mainline/v74_k1_cases_time_plan_20261116.json)
