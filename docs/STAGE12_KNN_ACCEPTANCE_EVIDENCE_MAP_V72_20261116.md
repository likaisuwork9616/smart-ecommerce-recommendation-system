# V72｜K1 完整驗收的成本、來源與恢復證據對照

本輪接續[V71的K0–K7缺口](MAINLINE_ACCEPTANCE_PRIORITIES_V71_20261116.md)，只讀既有契約、文件及公開聚合收據。先不裝Linux，不新增工具、測試、量測、排名、訓練、bootstrap或原48筆重跑；不讀私人原始資料、模型或資料庫，也不執行既有研究入口的`--audit`。本輪的雜湊與欄位核對只檢查這些文件／聚合收據，不是重新驗收其背後的逐筆證據。

## 先固定對象與分類

要補驗的是原V1已產出的K1主要輸出及原P0／C1／D1對照，沿用已曝光validation的166,897個query、62,235個visitor與原2,000次bootstrap；不是重新fit或產生另一份主要排名。原V1 partial與另次反讀的923觀測均不作可恢復進度。保留測試仍locked，K1−C1正式結論仍缺。[V1契約](contracts/retailrocket_session_knn_paired_v1.json)、[V2反讀契約](contracts/retailrocket_session_knn_readback_v2.json)

**未來完整驗收究竟採哪個方法／runtime／入口，目前尚未選定與凍結。** V2提供已實作的精確驗算與恢復規則；V5及後續提供工程證據；V39／V40等提供候選與48筆比較入口。這些不是一個已批准、可直接全量執行的單一版本。V40的V39候選未採用，V48使用V39作對照也不等於採用；V46仍暫不採用。[V40既有結果](STAGE12_KNN_TYPED_COMPARE_V40_20261111.md)、[V48既有結果](STAGE12_KNN_COLD_REPEAT_V48_20261113.md)

| 分類 | 本文含義 | 使用界線 |
| --- | --- | --- |
| 可沿用 | 原契約要求、來源追溯及特定版本／分母下已保存的工程證據 | 不等於舊artifact可直接載入；未來使用仍須核身分、來源與所選方法的適用性 |
| 範圍重疊 | 同一階段的父子計時、相同I/O／核對工作、重複樣本或同一來源的不同綁定視角 | 只能選一致邊界，不重複計時、不增加獨立樣本數、不跨版拼出通過 |
| 仍未知 | 缺完整正式證據，或現有紀錄無法回答所選新方法的問題 | 保留null／未驗收；另訂方法是後續規劃，不在本輪補量或填零 |

同一項可以「方法可沿用、全量結果仍未知」。下表以此分開記錄，不用單一通過標籤掩蓋差異。

## 來源鏈：可沿用規則，完整正式鏈仍待新方案核對

| ID／範圍 | 可沿用的既有證據 | 重疊或不適用處 | 仍缺的具體證據 |
| --- | --- | --- | --- |
| S0 原主要輸出與控制來源（K0／K2） | V1主要索引、validation與bootstrap的既有產出／綁定；V2核對原四臂完整內容的要求 | 列數／SHA、given-ID指標自洽與完整排名驗算是不同證明；本輪未重讀原資料 | 所選新入口對原主要輸出、P0／C1／D1、資料／契約／環境的正式來源清單及完整驗收收據 |
| S1 角色與時間邊界（K0／K1） | V2先排除不允許角色再解碼，SQL獨立重建，完整正重疊、精確Fraction與零票補集規則 | 整檔opaque SHA不等於解碼保留測試；不能以主要loader／排名結果替代獨立驗算 | 所選方法保留原角色、因果、集合覆蓋與數值規則的接入證明；不解鎖test |
| S2 獨立重建與封存DB（K0） | V2／V5已有完整train重建與模型身分核對；V2要求關閉SQLite後封存SHA、main DB唯讀 | 不同版本各自的重建成本不能相加；已有工程重建不代表任何舊DB都可直接接續 | 新方案選用哪份相符sealed DB或重建流程、完整inventory／journal／TEMP政策及正式來源鏈；本輪未檢查舊DB現況 |
| S3 方法閉包與綁定時點（K0／K6） | V31／V33區分直接與祖先報告間接綁定；V34要求必要Python直接列入request.sources、動態import明列目標；V39／V40保留worker、publisher與鎖後檢查 | sources／methods／binding是不同集合；不能把其數量直接相加，或把間接來源改稱原窗口逐檔驗過 | 所選全量入口的確切方法閉包、直接／繼承／追加關係、每個檢查發生的上下文與成本歸屬 |
| S4 工程ledger的來源身分（K1–K5） | V5 source-backed完整形狀ledger、110個已驗參考payload校準及完整鏈／EOF工程紀錄 | 其餘列取自尚未全量驗收的原輸出；不呼`append_verified`、不產生科學acceptance，不能當已驗prefix | 全部166,897筆獨立核對後建立的real ledger，以及原global／原draws的正式驗收 |
| S5 候選reference與獨立發布（K0／K5） | V39私有worker adapter及public builder信任邊界；V40已有人工與真48筆入口、獨立publisher及停態封存 | 人工219描述符不等於真實閉包；worker reference不得傳成publisher信任根；public builder額外canonical成本不能藏入worker | 若選候選接入，須在新全量方案證明callsite／runtime／生命週期及獨立發布適用；本輪未採用任何候選 |

來源依據：[原停止收據](../reports/stage12/retailrocket_session_knn_v1_validation_attempt.json)、[V2實作與故障界線](STAGE12_RETAILROCKET_KNN_READBACK_V2_20261103.md)、[V5工程ledger](STAGE12_RETAILROCKET_KNN_SOURCE_LEDGER_BUILD_V5_20261103.md)、[V31／V33來源與計時界線](STAGE12_KNN_C1_S1_COMPARE_V31_20261110.md)、[V39 worker／publisher](STAGE12_KNN_LATE_TYPED_V39_20261110.md)。

[V5重建](STAGE12_RETAILROCKET_KNN_REBUILD_COST_V5_20261103.md)的七個直接檔是外層閉包的子集；[V34直接來源規則](STAGE12_KNN_ENTRY_COLD_V34_V35_20261110.md)則補強未來入口。來源清單重疊與重複執行檢查須分開：worker／publisher前後、鎖後及恢復時的必要再核是不同次操作，不能因為驗同一檔就刪除或只計一次。

## 恢復與收尾：既有故障證據不等於全量已驗進度

| ID／範圍 | 可沿用的規則與既有證據 | 不能轉用的範圍 | 仍未知或須另訂的方法 |
| --- | --- | --- | --- |
| R0 舊停止狀態 | V1另次反讀事後收據記最後觀測923、缺8個預期收尾路徑 | 923不是checkpoint、驗收數或剩餘工時分母；停止原因／時刻未知不得追補 | 只保留舊namespace；新方案另有run身分，不接續原partial或未完成SQLite |
| R1 DB與query提交 | V2 sealed DB、64筆或120秒後安全query邊界、payload／manifest SHA鏈；latest只作提示 | 120秒不是最大損失上界；未提交尾段保留重做，已提交損壞拒收，不自動修復 | 所選方法完整來源／DB／鏈／ordinal／key／EOF的恢復證據，以及最壞單query／flush成本 |
| R2 writer與期限 | V2 OS單writer鎖、PID／create_time／boot身分、絕對期限與含離線累積預算；不明身分拒收 | 恢復不重設期限，也不把舊窗口餘額當新授權 | 新方案同一run的預算帳、停止請求／退出／恢復稽核與外部監督安排 |
| R3 global與原draws | 原序ledger重播、不合併chunk小計；V2 bootstrap中斷後重驗全部原2,000 draws | V5完整工程global／新self-reference draws只有成本與形狀證據，不能頂替原aggregate／draws驗收 | 全量已驗ledger上的原結果重播及完成成本；若需draw checkpoint須另定規格，不暗中改成分段重抽 |
| R4 candidate與最終發布 | V2 worker只能寫candidate；獨立supervisor確認正常退出後發布acceptance。V39／V40另有獨立publisher／停態manifest證據 | candidate不等於成功；V32是特定舊窗口的精確日誌補正，不是通用資料修復／恢復授權 | 所選全量方法的candidate、正常退出、完整來源再核、global／draws及停態收據閉合；舊缺收據不補造 |
| R5 故障與耐久性 | V2合成故障含真正子程序強退與恢復等價；後續工程鏈與48筆發布也有各自驗收 | 測試只證其凍結版本與案例；程序崩潰不等於實體斷電，不能將各版測試數相加成唯一覆蓋 | 新方法變更的適用性／回歸範圍、全量已驗real ledger恢復與實際資源生命週期；物理斷電耐久性仍未證明，是否要新增此主張需另定要求 |

V5已完成166,897筆工程鏈及七路source-only EOF恢復，不能再列成「從未做過完整規模恢復」。缺的是**同一所選方法下，全量已驗real ledger與正式內容／完成證據的連接**。同樣，V39文件當時「真實入口尚未封存」已由V40等補上48筆工程入口，不能當成今日未完成事項。[V5成本決策](STAGE12_RETAILROCKET_KNN_COST_COVERAGE_DECISION_V5_20261103.md)、[V32限定補正收據](../reports/stage12/retailrocket_session_knn_v32_release_recovery_20261110.json)

## 本輪進度

| 小步驟 | 狀態與界線 |
| --- | --- |
| 1. 對象、來源與恢復 | S0–S5／R0–R5獨立靜態複核通過；20份來源描述、原欄位與15個文件連結核對一致，沒有新內容驗收 |
| 2. 成本重疊與未知清單 | 10類成本、7項計帳規則、6項缺口完成；獨立靜態複核通過，不估新工時 |
| Linux／新增量測／研究重跑 | 全部0；T_plan仍null，全量不啟動 |

[來源與恢復盤點收據](../reports/mainline/v72_k1_source_recovery_map_20261116.json)

## 成本對照：保留原邊界，不拼接成全量工時

下列秒數只引用原聚合收據，保留各自版本、工作量與環境；本輪未重新計時。引用數值的目的是指出已有證據，不為選擇某版方法提供速度保證。

| ID／成本範圍 | 可沿用的既有證據 | 範圍重疊／不能直接計入 | 仍未知 |
| --- | --- | --- | --- |
| C0 來源核對、監督與發布 | V31／V33已有worker、publisher及整個窗口拆帳；V40／V48也有真實來源與停態發布紀錄 | window包含process，process包含entry／callback及其來源檢查；閉包與binding的邏輯bytes也有包含關係 | 所選全量入口的來源清單、每次重驗位置、監督／發布／退出後稽核邊界及耗時 |
| C1 獨立重建／context準備 | V5完整獨立重建248.676秒；1,180,256 sessions／1,587,436 memberships；後續工程入口有context／catalog分項 | V2與V5是不同方法／窗口；重建子段與整窗口不能相加；不同版本初始化不能混作同次工作 | 所選方法沿用sealed DB或另重建的規格、完整來源／資源及準備成本 |
| C2 全部query驗證 | 全窗結構166,897筆已完成；V17有55細格成本情境，較新V48 scope記170個可比較query／232歷史身分 | verify含解析與rank，rank含SQL／投票；重複樣本不是新身分；有限樣本及分層最大值不是全人口時間上界 | 未採樣的實際SQL／投票／payload尾端；新全量方法全部query的成本適用性 |
| C3 append／commit／budget／尾段 | V5、V17、V23已有直接budget、內含commit、尾端與setup分類 | append含編碼／實體寫入；primary含所有commit，tail須扣掉同次已計commit；budget按query／commit／stage／setup上下文歸一次 | 全量節奏與所選新方法的保存、恢復及收尾生命週期成本；120秒不保證最大損失時間 |
| C4 全形狀工程ledger建置 | V5 166,897 records／62,235 visitors／2,608 chunks／2,413,599,879 payload bytes，build350.266秒 | builder含解析、given-ID指標、編碼與chunk I/O，與C2／C3重疊；不得整段另加到query projection | 全量獨立驗算後的已驗real ledger；工程adapter校準不等於其餘列驗收 |
| C5 完整鏈、來源定位與恢復 | V5完整工程鏈＋七路source-only EOF定位177.864秒 | 這是工程鏈，不是全量已驗real ledger；恢復內部重驗若已在同一父phase，不另加；另一次真正恢復則須計其工作 | 所選全量方法的有效prefix恢復、EOF／DB／來源再核與實際恢復成本 |
| C6 全域與切片重播 | V5完整工程四臂／conditional／切片global532.128秒，覆蓋166,897 records／62,235 visitors | 固定形狀結果尚未與原aggregate作科學驗收；內部API計時已在phase中 | 原全域與切片正式內容核對、全量已驗ledger上的完整成本 |
| C7 原bootstrap反讀 | V5新2,000 self-reference draw phase332.927秒，可參考形狀與重播工作 | fixture49.737秒與replay122.101秒已在phase內；原draws當時只可能作opaque SHA，未作內容驗收 | 原2,000 draws的順序／RNG／visitor／統計／區間核對與重啟成本；不能用新draws頂替 |
| C8 reference／cold／快照／guard | V41直接比較原C1-S1／V39；V47／V48比較V39／V46；V49已有21項入口拆帳 | reference內含於cold_build，再內含於entry；快照子項在fingerprint／guard內；事後model單獨decode是另一段重播 | 所選全量方法的實際初始化與釋放頻率、成本及收益；目前沒有候選採用或因果加速結論 |
| C9 RSS／TEMP／磁碟／負載 | V5及後續有抽樣RSS、目錄大小、負載與採樣缺口紀錄 | V5重播窗口新目錄4,328,542 bytes不含既有2.414GB唯讀ledger；資料大小不是峰值，抽樣峰值不是上界 | 全量程序樹／supervisor、DB／journal／TEMP、ledger／尾段／發布及保留證據的生命週期、容量與期限可行性 |

數值依據：[V5成本收據的measured_coverage／non_additivity／limits](../reports/stage12/retailrocket_session_knn_v5_cost_coverage_decision_20261103.json)、[V5重播範圍](../reports/stage12/retailrocket_session_knn_v5_ledger_replay_cost_20261103.json)。其餘邊界依據：[V17](STAGE12_KNN_COST_ROLLUP_V17_20261106.md)、[V23](STAGE12_KNN_ENGINEERING_PRIORITY_V23_20261109.md)、[V41](STAGE12_KNN_DIRECT_TYPED_COMPARE_V41_20261111.md)、[V47](STAGE12_KNN_COLD_V47_20261112.md)、[V49](STAGE12_KNN_SAVED_PHASES_V49_20261113.md)。

### 同一工作只歸屬一次，但必要再核不能省略

| 規則 | 正確用法 |
| --- | --- |
| O0 父子時間 | 在同一個run選互斥項。V31保存的窗口可拆worker＋publisher＋監督其餘；不能再把window加上兩個process。publisher callback也不是額外process |
| O1 query與保存 | verify只計一次；append扣內含commit、直接budget時只扣該次觀測的對應事件，並把被拆費用放回唯一所屬項；tail／seal不重複計commit |
| O2 工程代理 | C4不是驗算完成後額外必跑的一整段；不能把builder350.266秒整段加到已包含其工作之query情境。C6／C7只是工程phase，不能冒充原內容驗收成本 |
| O3 來源再核 | 同一pass的子清單已在closure內，不再加；但worker／publisher前後、writer-lock後及恢復時是真正不同操作，必須按所選方法保留並計帳 |
| O4 cold邊界 | V47／V48的完整冷入口是context冷啟動：輸入物件預載、context關閉、獨立發布在入口外；入口內仍有原load_context。它不是OS冷快取或完整監督窗口 |
| O5 統計摘要與兩個時鐘 | 各項中位數不保證可加；先逐次守恆再作摘要。V49的`entry − run.total`保留有號差額，不硬歸成某階段或截成零；`cold_other`等餘額維持未細分 |
| O6 跨版本與跨窗口 | V17的55格情境、V5各工程phase、V31或V48入口不構成同一執行；不得加總成T_plan。V31事後發布補正也不回填原窗口，重複48筆不擴大科學驗收分母 |

例如[V31／V33原拆帳](../reports/stage12/retailrocket_session_knn_v31_compare_analysis_20261110.json)記錄worker193.091秒、publisher96.095秒、監督其餘2.283秒，共同位於291.469秒窗口內；這是該次14個48筆工程入口的層級證據，並非新全量方案的估時。相反，V17核心情境刻意排除setup、尾端、整批commit及budget，因此不能把它稱為完整入口。

舊未知項須隨後續證據更新：V2當時未完成的全窗結構與工程I/O，V5已補；V23當時未拆出的部分入口／publisher成本，V31／V33已補相應工程窗口，V49又補V47／V48的21項守恆拆帳。**目前未知的是所選全量方法的適用範圍、完整內容驗收、資源與完成成本，不是所有階段都從未量過。** 既有wall time也不能自行拆成CPU運算／等待或判定外部負載因果；1ms診斷與Linux不是本輪主線的必要前提。

## 剩餘缺口與只讀工作的先後

| ID／先後 | 仍缺的明確交付物 | 對應範圍與本輪處置 |
| --- | --- | --- |
| U0 先固定待評估方法 | 待評估的完整工程版本／runtime／入口、繼承與新增差異、K0–K5輸入輸出責任表 | 對應全部S／R／C；目前null。先作文件方案，不代表採用或執行 |
| U1 隨方法建立互斥帳 | 每一階段的起訖、內含／外加關係、source pass及cold／hit／restart次數、證據來源和未知欄 | C0–C8；可先只讀整理，不能填入跨版本拼湊總秒數 |
| U2 補全量內容的證據方案 | 全query尾端、全量已驗ledger、原global／原2,000 draws的內容驗收與成本取得方式 | K1–K5、C2–C7；先列必要證據，不在本輪執行驗算或量測 |
| U3 與U2並行訂資源／停止規格 | TEMP與磁碟完整範圍、RSS生命週期、預算、停止／退出／恢復／完成責任及方法變更的驗收範圍 | K5／K6、R0–R5、C9；沿用原限制，不把抽樣值當上界或縮減來源守門 |
| U4 前提足夠後才估時 | 可追溯、無重複項的全量成本情境與假設／不確定性，以及有界取得未知證據的提案 | 現在T_plan仍null；舊4.5小時規劃／6小時候選窗口不是現行執行授權。缺資料時先提取得方式，不要求先有完整數字才可規劃 |
| U5 完成後才交付結論 | 新方案全部必要內容、來源、資源與正常退出收據通過，才形成K7完整驗收及K1−C1開發結論 | 尚未執行。驗收與效果好壞分開，原partial不改寫，最終選模／refit／test仍另題 |

本輪能交付的是上述對照與責任缺口，不能解答「全量還要多久」或把任何未知填零。建議下一步仍只讀，先提出U0的具體待評估方法與差異清單，再整理U1的階段邊界；若發現現有證據不足，再另提有界取得方案。每日10%待資料優先順序與Dashboard暫緩不變。

兩步皆經獨立靜態複核。第二步核對17筆直接來源描述，加上第一步20筆，共37筆描述／30個不同檔案，bytes與SHA相符；引用原欄位一致、6項文件依賴無循環、本文24個本機連結有效。原研究方法與凍結結果未更動；第一步已推送`209dfd6`，兩步各同步README。這些是文件一致性檢查，沒有新增內容驗收或研究執行。

[成本分類與未知項目收據](../reports/mainline/v72_k1_cost_overlap_map_20261116.json)
