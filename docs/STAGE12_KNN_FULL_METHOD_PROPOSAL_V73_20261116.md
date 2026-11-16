# V73｜K1 全量反讀待評估方法與階段責任

本輪依[V72](STAGE12_KNN_ACCEPTANCE_EVIDENCE_MAP_V72_20261116.md)完成U0／U1的文件提案：只讀既有契約、程式文字與公開聚合收據，不匯入或執行研究程式，不讀私人原始資料、模型或DB。沒有安裝Linux、實作入口、建立合成案例、測試、量測或重跑原48筆。下文「選定」僅指**選定供後續評估的方案**，不是採用、驗收通過或執行授權；`T_plan=null`、全量仍關閉。

## 具體待評估方法

提案採**Windows上的V2完整反讀骨架＋V4精確計算核心**。由新版本adapter承接原V1完整validation，首次在新run建立獨立DB與已驗ledger；重啟只恢復該新run自己的有效提交。原V1科學規則、全部166,897個query／62,235個visitor、原2,000次bootstrap及P0／C1／D1控制輸出不變。這是獨立驗算原輸出，不是新主要fit、主要validation或重抽主要bootstrap。

選擇理由是V2已有完整串流、原序重播與恢復規則，V4已有精確SQL／指標差分證據，V5又補完整工程重建與形狀成本。這些證據支持把接入範圍寫具體，**不證明組合後已可完成全量或能保留樣本加速**。不用「最新版」代替版本清單，也不把未採用的C1-S1／V39／V46組合作預設。[V4方法](STAGE12_RETAILROCKET_KNN_PAIR_OPTIMIZATION_V4_20261103.md)、[V5重建](STAGE12_RETAILROCKET_KNN_REBUILD_COST_V5_20261103.md)

| 項目 | 本提案的明確選擇 | 已有／待補界線 |
| --- | --- | --- |
| Runtime | 保留Windows；以既有CPython3.12.10、NumPy2.5.4、psutil7.2.2、SQLite3.49.1、little endian為相容目標，套件仍在專案`.venv/` | 引自V5／V17及V22歷史environment；本輪未探測現機。Windows build、Python執行檔／SQLite library精確身分及數值環境須在後續方法封存中固定，不猜現況、不自動更新套件 |
| 科學規則 | 原V1契約；完整四臂、因果history／catalog、全部正重疊pool、500鄰居與ties、零票補集、完整target分母、原數值與draw順序 | 已有契約；新adapter必須逐條保留，不能以全target可達子集或固定樣本替代主分析 |
| 重建 | 以`readback_v2.prepare_model`／凍結`reconstruct`及`sql_v2.build_index`為基礎；新run首次fresh DB | V5證明此重建工作有完整工程紀錄；不直接載入舊V5 DB，不續接原partial。重啟才可在核來源／環境／seal後用同run DB |
| 完整query流 | 以`readback_v2.verify_queries`的全量順序及四臂核對為基礎，新adapter明確注入V4計算 | V4 `pair_v4.verify_selected`仍保留最多64筆；既有R工程入口也仍是48筆。新全量adapter尚未實作，不刪舊限制、不偽造synthetic marker、不monkey-patch凍結模組 |
| 精確計算 | `sql_v4.predict`、V2/V4共用`prepare_catalog`；`checks_v4.terms`；`checks_v4.EXACT_STRATEGY='frozen'` | 任意精度比率／整數票、4096位元回退Fraction、4096項metric cache及數值環境fallback保留；不啟用另一個exact候選，不導入production K1／loader／evaluator |
| Context與快取 | 每個worker attempt獨立載入／準備一次query context；明確在邊界清除metric cache，不持久化cache | 這是V2既有query函式內的準備生命週期；不採跨入口C1-S1 pool、typed reference或候選live snapshot。global重播原有的再次load_context仍保留並計成本 |
| 恢復與來源定位 | V2完整連續ledger鏈，從來源檔頭逐序掃過同run已驗prefix；只跳過已提交query的重排名 | 不採V4 source-index seek作首版路徑。`resume_sources`只有定位／邊界證據，沒有交出可續讀iterator；若以後採索引，另列adapter與驗收 |
| 全域／原draws | 保留`readback_v2.replay_global`整段順序：ledger Fold→原`check_bootstrap`→fixed／controls／原aggregate核對→兩個stage seal | 保持一個完成單元，不新增draw checkpoint；中斷後重播該單元。V5 engineering global／self-reference draws不作正式輸入 |
| 保存與完成 | V2 `CheckpointStore`的writer／鏈／來源／期限／candidate／正常退出規則；另規劃版本化協調及停態發布 | CP原生finalize是run層完成，外層公開發布須另驗停態。V34直接來源／quiet／closed manifest規則作接入依據，不能直接挪用V39固定48筆publisher |

Runtime依據：[V5原environment](../reports/stage12/retailrocket_session_knn_v5_rebuild_cost_20261103.json)、[V17原environment](../reports/stage12/retailrocket_session_knn_v17_cost_rollup_20261106.json)、[V22原environment](../reports/stage12/retailrocket_session_knn_v22_overlap_acceptance_20261109.json)。現有完整科學規則見[V1契約](contracts/retailrocket_session_knn_paired_v1.json)及[V2契約](contracts/retailrocket_session_knn_readback_v2.json)。

### 為什麼不直接啟動現有CLI

`run_retailrocket_session_knn_v2.py`只有工程probe；V4的完整global介面要求人工fixture；後續`run_fixed48`仍固定48筆。這些限制不因本提案解除。V2已有完整函式，不等於「接上V4後的全量入口、資源與退出發布」已驗收。

來源定位首版保留順序掃描，以減少未證明的接入差異。它可能增加恢復時間，費用不能填零；本輪不以快慢推定此選擇較佳。原R工程流程使用V4核心的事實，也不代表其48筆帳本或少量required stages足以驗收全量。

## 差異清單與待驗責任

| ID | 相對既有證據的差異 | 可沿用內容 | 後續需驗、尚未完成 |
| --- | --- | --- | --- |
| D0 版本與執行域 | 新組合有獨立方法／runtime／source closure身分 | 原V1科學契約、歷史runtime相容目標 | 直接Python與明列動態依賴、實際環境及新契約；不只記模組名稱或祖先收據 |
| D1 fresh DB與同run恢復 | 首次重建在新run；只承認新run自有sealed DB | 完整support／sessions／postings／兩份lineage／fit audit／integrity／close／SHA流程 | 與新CP stage/artifact接合、半成品隔離及重啟一致性；不宣稱新舊DB bytes相同 |
| D2 V4核心注入全量流 | 把精確predict／terms接到完整原序query verifier；不使用selected ordinal | V2完整四臂檢查與V4精確數值語義 | 新adapter的全量ordinal／key、缺多重複／EOF、payload／Decimal／delta hex與V2／V4基準一致；方法結果標籤如實寫V4核心，不沿用`...exact_v2`冒稱未改 |
| D3 prefix與cache生命週期 | 新adapter把CP有效records對回原全量順序；每attempt cache重置 | V2連續鏈、原序prefix掃描、未提交尾段保留重做；V4有界metric cache | 中斷／重啟於任意安全邊界的等價，不能把子集ordinal、source-only位置或923當全量prefix |
| D4 CP及內容完成單元 | 新request顯式設定`expected_queries=166897`及`required_stages=[reconstruction,queries,global,bootstrap]` | CP原預設只列reconstruction／global／bootstrap；V2本身另會seal queries。原64筆／120秒安全邊界、lossless schema及重播順序保留 | 新增queries／完整EOF為finalize硬門檻，須驗配置接入；`replay_global`仍整段，若中途留下單一seal不能獨立宣告完成，重入須重播核一致 |
| D5 SQLite／TEMP與資源 | query沿V4 sealed main DB唯讀／immutable及TEMP MEMORY接法；重建保留原SQL／PRAGMA語義 | 既有DB seal、journal拒收、watch／deadline守門 | 新入口的重建OS TEMP範圍、query TEMP與RSS、DB／ledger／尾段／發布檔生命週期；未證明前不宣稱全量容量足夠 |
| D6 來源核對與計帳 | 新run固定直接閉包及每次檢查上下文；把新增adapter列直接來源 | V34必要Python直接入request.sources、顯式dynamic目標；V2鎖後／完成再核 | 完整清單、檢查時點與實際pass不得省略；同一pass子集不重加，不把不同次再核合併掉 |
| D7 新協調／停止 | 新supervisor接完整方法、同run期限與累積預算 | V2單writer／程序身分／未知拒收、V5停止請求與觀測退出分開 | 新完整pipeline與超限／超時／重啟故障等價；保留抽樣程序追蹤限制，不聲稱Job Object或物理斷電保證 |
| D8 最終化與停態發布 | 區分worker candidate、CP run acceptance、外層公開完成收據 | V2正常退出後finalize；V34 quiet及完整closed manifest；既有候選停態負例 | 新publisher／外部finalizer的責任與完整證據鏈；不得用V32特例補造成功，不默認再重算第二遍全量排名 |
| D9 完整成本與決策 | 對同一新方法列全生命週期邊界，再規劃取得缺失證據 | V72互斥規則與各輪限定範圍的成本 | 尚無新T_plan、完整資源／恢復／交付成本或加速結論；舊4.5／6小時不是新授權 |

D0–D9是**待接入及待驗清單**，沒有因文件完成而通過。新方法的假資料差分／故障驗收、任何能力核對或有界量測，都需後續具體方案；本輪不實作、不執行。Linux、1ms wall／CPU、Job Object及實體斷電測試不列為本提案自動新增的必要門檻。

具體程式依據：[V2完整反讀](../scripts/retailrocket_session_knn_readback_v2.py)、[V4精確排名](../scripts/retailrocket_session_knn_sql_v4.py)、[V4 checks](../scripts/retailrocket_session_knn_checks_v4.py)、[V4有限樣本介面](../scripts/retailrocket_session_knn_pair_v4.py)、[V2保存／恢復](../scripts/retailrocket_session_knn_checkpoint_v2.py)、[V4來源定位](../scripts/retailrocket_session_knn_sources_v4.py)、[V34來源／停態元件](../scripts/retailrocket_session_knn_entry_v34.py)。原`check_bootstrap`定義在[凍結directed oracle](../scripts/retailrocket_directed_oracle.py)，由原readback匯入；數值與exact依賴亦須列直接來源，不能只記上層readback。這些連結供查閱文字，不是本輪操作指令。

## 本輪進度

| 小步驟 | 狀態 |
| --- | --- |
| 1. 具體方法與差異 | 待評估組合及D0–D9獨立靜態複核通過；28份來源描述、20個既有函式／類別位置、歷史runtime欄位及17個文件連結一致 |
| 2. 階段邊界與驗收責任 | 11階段／8個正常來源核對位置／8種恢復分支完成，獨立靜態複核通過；新接入仍未實作或驗收 |
| Linux／新增工具、案例、測試、量測或重跑 | 全部0；全量執行仍關閉 |

[方法提案收據](../reports/mainline/v73_k1_method_proposal_20261116.json)

## 完整流程的工作邊界與責任

以下是同一待評估新方法的設計，尚未接入現有CLI。科學內容由**相對原主要模型獨立的worker**驗算；supervisor負責實際退出與CP完成條件；publisher負責獨立反核已存證據；最外層finalizer在全部writer停止後發布。這些是程式角色，沒有替使用者指定人員或對外聯絡。

| ID／階段 | 起訖、輸入與輸出 | 執行與驗收責任 | 成本與恢復界線 |
| --- | --- | --- | --- |
| P0 執行前置核對 | 從新run admission開始，核原V1科學對象、已封存方法／runtime、權威來源描述、完整控制輸出、gates與預算，至新request／binding建立 | 新orchestrator；既有權威不能由現場重算的hash取代。實際環境不符即拒收 | 方法開發／本輪文件時間不混入執行。真正run須先固定絕對deadline與總預算；目前數值未定，不能啟動 |
| P1 開啟與鎖後恢復 | `CheckpointStore.create/open`到worker writer鎖及`recover`核定連續有效prefix；輸出run身分、已提交records與已封存stage狀態 | 新worker接既有CP；核來源、PID／create_time／boot、期限、鏈及必要seal | 初次prefix=0；恢復只認同run。writer內recover與後續顯式recover是實際不同呼叫，不省略；子計時不再加到P1父計時 |
| P2 獨立DB準備 | `prepare_model`開始至重建或同run seal核對完成；fresh時reconstruct→index→integrity→close／journal→SHA／stage | 獨立worker；原完整train參考與允許角色核對，輸出sealed DB與model receipt | 舊V5 DB不直接載入。半成品DB隔離保留再重建；stage存在仍須驗其artifact。重建OS TEMP也屬本階段資源 |
| P3 query準備與prefix定位 | cache重置、load_context／prepare_catalog、唯讀DB與TEMP設定、開七路來源，掃過有效prefix至下一原序query | 獨立worker；來源身分、原key順序、已驗ledger key及prefix對齊；輸出query所需context及串流位置 | 不重算已提交query排名，仍付來源重掃／鏈核對成本。正常worker attempt只準備一次；不採indexed resume |
| P4 剩餘query核對與保存 | 逐筆讀原來源、驗history／current-next／四臂／V4精確排名／指標／delta；全部通過後才append_verified | 獨立worker負責K1／K2內容。維持原ordinal、完整分母與payload；未通過不寫已驗ledger | verification含rank／parse；append含encode／write與可能commit。每筆與chunk記錄不重加，64／120只在安全邊界提交 |
| P5 EOF、尾段與query seal | 最後query後驗全部paired streams EOF、flush、固定166,897筆及queries seal，關閉query DB | 獨立worker；輸出`queries=166897`、`paired_streams_eof_checked=true`及綁定完整鏈的stage | 不能僅數列數。此處flush屬尾段，不重計P4已發生的commit；關閉與失敗清理亦列實際所在區段 |
| P6 全域＋原bootstrap完成單元 | 完整已驗ledger→再次load_context→原序Fold／切片／visitor delta→原check_bootstrap→原aggregate核對→global與bootstrap seals | 獨立worker負責K3／K4；原visitor排序、PCG64(42)、2,000 draws、完整fixed／controls／aggregate皆核對 | 一個父區段；Fold、draw與最終比對僅邏輯子區段，目前未新增計時工具。中斷重播整段，不採draw checkpoint或工程self-reference |
| P7 candidate與worker收尾 | 完整stage／ledger／來源再核、candidate保存，到context／cache／檔案釋放、writer鎖釋放與worker退出 | worker只能寫candidate；CP `_complete_checks`及新schema guard保留。實際退出由下一階段supervisor觀察 | cache清理、最後來源核對、budget寫入與收尾不隱藏；candidate存在或鎖釋放均不等於程序正常退出 |
| P8 正常退出與CP最終化 | supervisor實際觀察該worker退出0，獨立open，進入保留原finalize規則的新版本接合；在supervisor writer鎖下核query completion guard後才提交CP acceptance | 初次正常退出須同boot獨立supervisor實際觀察；新guard綁同次finalize採認的run／ledger／stage／candidate。已有可信退出收據的重入沿B5，不補造新退出 | CP acceptance是run層完成；不表示外層停態交付完成。新接合不修改凍結CP，不以鎖外預查或重複巢狀writer代替鎖內守門；非0或仍存活拒收 |
| P9 獨立發布核對 | 新publisher從原始request／binding／candidate／CP acceptance／stage／ledger重新讀取，核完整證據鏈與待公開摘要；關閉日誌並退出 | publisher在來源前後再核下獨立驗整條鏈、ordinal／key／roster、完整計數、stage與candidate／aggregate／draw收據一致；不只信摘要 | 不重跑第二次166,897筆排名，也不新增一次global／draw數值重播；這不是第二個科學oracle。唯讀proof adapter尚待實作，全部讀取／解析／證明／序列化成本另列 |
| P10 停態封存與公開交付 | 外層finalizer確認worker／supervisor／publisher及相關writer均停止、日誌關閉，核P9 proof及固定輸出集合，生成closed manifest與公開完成判定 | 外部finalizer依新schema接V34停態規則；manifest覆蓋完整內部證據，公開結果如實保留開發與test locked限制 | 最終seal／公開結果放被封存namespace外；不要求manifest含自身hash，不封存後寫回內部。P10仍屬完整交付成本與同run預算 |

**queries硬門檻需要接入驗證。** CP原`_complete_checks`只對global／bootstrap stage的ledger摘要作特定比對；把`queries`加入required_stages只保證其存在。新P8 guard須在同一次supervisor writer鎖內、採認完整鏈後且acceptance提交前，核其run／ledger身分、166,897分母與paired EOF真值；P9再核一致，缺少或矛盾即拒收。這是D4／D8的明列新版本finalize責任，不是假稱原CP預設已內建可插入的guard。

P9的獨立性指由另一程序反讀原始證據、來源與完整鏈，不接收worker記憶體成功token；科學驗算仍由已凍結且相對production獨立的worker負責。V39的14份48筆reference proof不能直接轉作P9全量proof。若後續要增加第二次global／draw或全部排名重算，需另列方法差異、必要性與成本，不能藏在「發布」一詞中。

## 來源核對的明確位置

以下8點是提案中**正常fresh worker＋獨立supervisor最終化＋publisher**的完整來源核對位置。H1–H6來自CP既有呼叫；H7–H8是新publisher的明列接入要求，尚未實作。失敗可提早停止，重啟可能增加次數；不是宣稱每條路徑永遠固定8次。

| ID | 所屬階段／位置 | 核對範圍與責任 |
| --- | --- | --- |
| H1 | P1 worker `create`或`open` | CP binding的完整科學／控制／方法來源，依預先權威描述驗bytes／SHA |
| H2 | P1 worker `writer`取得鎖後 | CP強制重驗同binding；不得因H1已驗而刪除 |
| H3 | P7 `write_candidate`→`_complete_checks` | CP強制重驗來源，並核完整ledger與required stages |
| H4 | P8 supervisor另行`open` | supervisor自己的CP實例完整來源核對，不承接worker的已驗旗標 |
| H5 | P8 `finalize`內取得supervisor writer鎖 | 鎖後強制再核來源；與H4是不同次操作 |
| H6 | P8 `finalize`→`_complete_checks` | 完成前強制來源核對與完整鏈／stage核對 |
| H7 | P9 publisher開始proof前 | 新唯讀publisher完整再核binding與直接方法身分；不得僅驗頂層報告SHA |
| H8 | P9 publisher完成proof後 | 新publisher再核來源一致才形成發布proof；失敗不形成外層成功 |

P0核既有權威描述、方法封存與request，不另外默認一次全科學來源掃描；實際補充檢查仍須列明。`get_stage`的artifact SHA、`recover`的整條ledger、P10停態manifest是**不同證據集合**，不得假稱都含在H1–H8，也不得把其中子集重加為另一個完整pass。P10核H7／H8 proof與封存檔案集合，不默認再做第9次全科學來源重掃；本提案不新增連續偵測所有外部來源變更的主張。

## 恢復分支與失敗責任

| 分支 | 可接受的狀態 | 下一步與拒收規則 |
| --- | --- | --- |
| B0 首次新run | 新request／binding，無舊成果充當已驗prefix | P1→P2 fresh DB→P3–P10；不挪用原partial／923或工程ledger |
| B1 重建中斷 | 同run，尚無有效reconstruction seal | 保留未完成DB及journal證據，再走P2；不把檔案存在當完成 |
| B2 query中斷 | 同run有效DB seal與連續committed prefix | 再核來源／鎖／鏈後P3掃至prefix，重算未提交尾段；已提交損壞拒收，不修到看似連續 |
| B3 global／原draw中斷 | query全量已驗，P6未完整完成，可能已留下部分stage | 重新執行整個P6，舊stage必須核一致；不從某draw號接續、不略過原aggregate |
| B4 candidate後退出未知 | 無可信normal-exit收據，確認舊worker不存活且原期限仍允許 | 依V2保留／supersede舊candidate，新worker核prefix並完整重播P6，再產生自己的candidate；不借用舊退出碼 |
| B5 已有正常退出證據、未CP完成 | 真實已記錄的normal_worker_exit及相符candidate／來源／鏈 | 由supervisor重入finalize，保留原退出證據；不要求重跑worker來覆寫正常退出 |
| B6 已CP完成、外層發布未完成 | immutable CP acceptance與相符完整內部證據 | 只重入尚缺的P9／P10；不重啟科學worker、不修改CP acceptance，部分外部proof保留另版；同run預算不得重設 |
| B7 完整成功、期限／資源不足或完整性失敗 | 已完成者只可讀；到期、未知身分、來源改變、鏈壞等狀態分別記錄 | 不自動重試／延長／另開窗口；保留失敗與缺口。完整成功後不重測，來源變動或方法改動另立版本 |

所有分支都沿用同run絕對deadline與含離線時間的累積預算，停機不歸零。P9／P10若在科學worker退出後繼續，仍要預留交付時間；外部控制收據與預算責任放在被封存namespace外，不能為更新預算破壞已封存內部檔案。超時可保存事實與失敗狀態，不得繼續驗算或把保存稱成功。

完成順序固定為：**candidate→真正正常退出→CP acceptance→publisher proof／退出→全部內部writer停止→外部final seal／公開交付**。若最後公開檔尚未原子提交，只能在有效預算與未變證據下補做該交付，不重新執行已完成科學階段。V32精確日誌補正不是本提案一般恢復機制。

## 計帳邊界與驗收責任的交接

P0–P10是工作責任分區，不代表現有程式已提供11個互斥計時器。未來接入須先固定邊界再驗工具，不能事後以當次較快數字選邊界。本輪不新增時鐘呼叫。

- **外層wall帳**涵蓋啟動、來源、worker、最終化、publisher、停態finalizer、必要等待與恢復；另列執行前開發／測試成本。supervisor在worker存活期間的監控與等待是重疊視角，不能把其整段wall再加到worker上。P8只歸退出觀察後的最終化工作。
- **內層階段帳**按同一attempt的實際呼叫與區間歸屬。P4的rank／verify／append／commit有包含關係；P5 flush只計實際尾段。P6保持一個父段，子項不得再加一次。CP source pass、stage/artifact及chain核對歸實際所屬P階段。
- **外層與內層的差額**保留啟動／排程／日誌關閉／未知餘額或有號時鐘差；不能填零、截成正值或歸因於CPU等待。沒有同起訖證據就不宣稱精確守恆；1ms wall／CPU支線不在本方案內。
- **每次恢復episode**另列實際來源再核、prefix掃描、重播與發布費用；累積預算含離線時間，不能把已花時間丟掉。全生命週期容量須包含既有唯讀輸入、DB／journal／TEMP、ledger／orphan尾段、內部證據及外部發布／控制紀錄，不能只量新目錄。

| 後續驗收責任 | 必須交付的證據 | 本輪狀態 |
| --- | --- | --- |
| 新方法／人工案例驗收 | D0–D9接入、全量流語義、四個required stages、query EOF guard、B0–B7與正常／故障結果等價；既有測試數不加總冒稱新通過 | 尚未實作或執行 |
| 成本與資源方案 | 同一方法的P0–P10／H1–H8邊界、監控涵蓋、TEMP／RSS／磁碟、恢復與收尾成本及停止條件 | 只有責任表；新成本、期限與T_plan仍未知 |
| 真實完整內容驗收 | worker驗全部原query、global與原draw；supervisor／publisher／finalizer按上述角色完成證據鏈 | 尚未執行，K1−C1正式結論仍缺 |
| 研究交付 | 完整通過後才報原開發比較，正負或區間跨零照實；不解鎖final／refit／test | 尚未交付，不以本提案取代 |

這次已把V72的U0／U1從「未指定」推進到可審閱的具體提案；U2–U5所需的新接入驗收、成本／資源與實際完整結果仍缺。下一步建議先依D0–D9與B0–B7列**最小接入規格及人工案例清單**，先審閱範圍與預估時間，再決定工具準備；本輪沒有開始此工作。

兩步皆經獨立靜態複核。第二步核對10筆直接來源描述及第一步28筆，共38筆描述／31個不同檔案，bytes／SHA一致；10項差異ID、階段與恢復引用相符，本文18個本機連結有效。第一步已推送`1869c58`，每步同步README；原方法、凍結結果及第一步收據未更動。這些只是文字／欄位／來源一致性檢查，不是新全量工具或科學驗收。

[階段邊界與責任收據](../reports/mainline/v73_k1_stage_responsibility_20261116.json)
