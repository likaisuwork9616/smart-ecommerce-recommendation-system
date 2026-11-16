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

## 本輪進度

| 小步驟 | 狀態 |
| --- | --- |
| 1. 最小接入規格 | 六元件、request／輸出契約及G0–G7已列；獨立靜態複核通過 |
| 2. 人工案例、估時與確認 | 接著固定案例族、對應關卡、估時及停止範圍 |
| 工具／fixture／測試／量測 | 全部0；等待使用者確認後才準備 |

[最小接入規格收據](../reports/mainline/v74_k1_minimal_integration_spec_20261116.json)
