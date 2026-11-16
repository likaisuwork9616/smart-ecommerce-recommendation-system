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
| 2. 階段邊界與驗收責任 | 接著列完整流程、責任、來源pass及中斷分支 |
| Linux／新增工具、案例、測試、量測或重跑 | 全部0；全量執行仍關閉 |

[方法提案收據](../reports/mainline/v73_k1_method_proposal_20261116.json)
