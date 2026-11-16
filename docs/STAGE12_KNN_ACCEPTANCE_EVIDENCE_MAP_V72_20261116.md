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
| 2. 成本重疊與未知清單 | 接著依同版本、同分母、同計時邊界對照；不估新工時 |
| Linux／新增量測／研究重跑 | 全部0；T_plan仍null，全量不啟動 |

[來源與恢復盤點收據](../reports/mainline/v72_k1_source_recovery_map_20261116.json)
