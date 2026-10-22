# Stage 6：RFM描述與分群評估凍結規格

本輪沿用已驗收的RFM v1，**只凍結方法與查核既有來源／版本**。不解析顧客CSV內容，不計分布、分位數或切點，不建立分數／群組，不執行重抽樣、分群模型、訓練或Dashboard。Stage 4、5維持待資料；Stage 4每日10%與11／29／42／73／101五種子不變。

[前輪實作驗收](STAGE6_RFM_DATASET_IMPLEMENTATION.md)保留資料集正確性證據；[本輪機器規格](../reports/stage6/rfm_evaluation_specification.json)固定處理與驗收方式，[metadata查核](../reports/stage6/rfm_evaluation_contract_audit.json)只證明可沿用同版本，不能當成描述或分群已通過。

## 沿用資料與顧客分流

S=2017-09-01 00:00:00、T=2018-09-01 00:00:00，naive秒級，不改原365天窗口或重建資料集。以下數量引用[原建置](../reports/stage6/rfm_dataset_build.json)及[原驗收](../reports/stage6/rfm_dataset_build_acceptance.json)，不是本輪重新計算。

| 顧客狀態 | 原驗收數量 | 未來描述／切點用途 |
| --- | ---: | --- |
| active_complete | 72,124 | 唯一完整RFM數值母體，可作三軸描述及日後切點參考；合法M=0仍保留 |
| inactive_complete | 21,109 | 保留顧客與零活動狀態，R三欄null、F=0、M=0；不填R=365／∞後混入切點 |
| active_with_quarantine | 1 | 保留母體、品質及合格子集R／F的原值；M維持null，不評完整RFM分數 |
| active_money_unknown | 0 | 未知分支仍保留；M=null，不補商品／付款、不刪F或混入完整數值集合 |
| inactive_with_quarantine | 0 | R=null、F=0、M=null，只表示無合格活動，不能當乾淨零活動 |
| 全部顧客 | 93,234 | 五種狀態互斥且完整覆蓋同ID全集；另有99,421列T前訂單稽核帳本 |

後續實作須聯合核對state、rfm_usable、monetary_complete、R／F／M與品質計數，不能只信一個旗標或用M>0篩人。完整顧客M加總及遮罩顧客已知子集的原守恆也須保留；隔離顧客不得拿部分M作值。三種不完整狀態本階段只報數量與null遮罩，不把部分R／F分布混進完整RFM描述。

## 描述、偏態與離群值

完整活躍集合固定三軸：R用recency_seconds精確整數作排序與判界，顯示再除86,400為elapsed days；F為distinct合格窗口訂單數；M為商品整數分快照毛額。運費／付款不加入M，分期不乘上去，也沒有退款／結算回填。

| 項目 | 未來固定計算與驗收口徑 |
| --- | --- |
| 每軸摘要 | N、null數、distinct數、min／max、算術mean，以及P0／1／5／25／50／75／95／99／100；先記精確整數sum與N，mean僅作顯示 |
| 分位數 | 升冪原值x，p=0取第1個；其餘取1-based第`ceil(n*p/100)`個。正整數p可用`(n*p+99)//100`，不插值、不先轉浮點分 |
| 偏態 | IQR=Q75−Q25；Bowley=(Q75+Q25−2×Q50)/IQR，IQR=0回null並記退化原因；另列mean／median，不設定「必須不偏」的成功門檻 |
| 重複與零值 | F=1與M=0的N／比例，揭露大量ties或合法零元；不因頻次／金額低就排除顧客 |
| 金額上尾 | M≥Q99的全部顧客N／比例與商品M占比，包含切點ties；不得稱剛好前1%。總M=0時占比null，不除以零 |
| 離群旗標 | IQR>0時，嚴格低於Q25−1.5IQR或高於Q75＋1.5IQR才flag；用`2*x < 2*Q25−3*IQR`或`2*x > 2*Q75＋3*IQR`精確比較，不先round半秒／半分邊界 |
| IQR=0 | 記退化軸，fence旗標數回null；另看distinct、單次交易與上尾質量，不將零寬fence誤當可分離證據 |
| 第二描述尺度 | 固定log1p(R秒÷86,400)、log1p(F)、log1p(M分÷100)，只列N／null／min／max／mean及相同百分位、檢查有限值；fence／離群旗標仍用原尺度，不改主RFM或用log切點另選較佳結果 |

離群值預設只標記，不刪人、不截尾、不clip或winsorize，也不修改已驗收CSV。R超出(0,365]、F<1、M<0、必要值缺失／非有限是資料失敗，須停止，不能當尾端值處理。完整活躍集合若N=0，除N外摘要均null、明記empty_reference，G1無法評估，不估切點。改尺度、加權、截尾或換窗口需另版規格；本輪未核出任何偏態或離群比例。

上述分位數對應經驗分布的inverted-CDF定義，並非NumPy預設linear插值；本規格用精確整數rank寫死，不依套件預設。log只作單調描述視圖，不把它當第二份獨立分箱穩定證據。[NumPy定義](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html)

## 日後候選切點與分群評估範圍

本版只固定一個**待評估的規則分箱參考**：完整活躍顧客各軸P20／40／60／80，沿上節精確rank取原尺度切點。這不是已選定商業分群，也未設定K-means、距離、scaler、群數K或模型選擇。若日後要用分群模型，須先另凍結該演算法與評估契約。

| 問題 | 凍結處理 |
| --- | --- |
| 大量F ties | 相同原值永遠同箱；不能按ID、列序、rank-first或隨機拆開，不能為五等份加抖動 |
| 重複切點 | 去重；小於max的min切點可保留，所有≥max的切點移除，避免最右空箱。有效級數=保留切點數＋1，明列實際每箱N |
| 邊界 | x≤切點落較低數值箱，其餘往右；原整數秒／訂單數／分精確判界，不對金額或R做epsilon／round |
| 常數軸 | 切點全等max時只剩1級，記「無分離力」；完整三軸候選不可通過，不事後改手工切點 |
| 方向 | 原數值箱1…k；R序數=k＋1−箱號，F／M序數=箱號。k以各軸實際有效級數為準，不能坍塌後仍稱五級 |
| 表達 | 只保留三軸序數tuple與各軸級數；不相加／加權成總價值分。最多125個可能格子不是125個已選客群，實際只有觀測到的中性tuple |
| 群名 | 先用中性軸／箱／tuple，不貼VIP、流失、LTV或行銷動作，不能把R方向當未來價值證據 |

估計切點及產生任何顧客序數／tuple都屬後續執行，本輪為0。描述結果須先驗收，再另確認是否進行此候選；不得在描述時順手打分／分群。

## 穩定性與支援量驗收

### 同資料重現

同一凍結輸入，原列序、反轉列序及seed42的PCG64排列，切點與同ID分配須100%相同。缺ID、重複ID、順序依賴或同值拆箱都須停止；不能只比群大小相同。

### 同快照方法敏感度

以完整活躍ID升冪作固定參考集合，將來用11／29／42／73／101五種子各抽80%顧客、不放回。明定`sample_n=(4*n)//5`，每種子執行`Generator(PCG64(seed)).choice(n, size=sample_n, replace=False)`抽canonical位置；僅在抽樣顧客估切點，再套回同一完整參考全集比較。既有套件鎖定檔也納入來源版本；此處五種子只作RFM敏感度，不重跑或修改Stage 4五種子模型。

| 驗收項目 | 事先固定門檻／失敗處置 |
| --- | --- |
| 有效級數 | 參考與每種子各軸皆2–5級、無空箱，且每軸級數須與參考相同；否則不把換級標號當可直接比較的成功 |
| 每軸bin支援 | 回套完整參考集合後，每個軸bin的N≥`max(100,ceil(0.005*n))`，精確算式`max(100,(n+199)//200)`；參考與所有種子均需通過 |
| 每軸分配一致率 | 三軸各自與參考同ID序數比較；所有種子都≥0.90，列五次及最差值，不只報平均／最佳 |
| Joint ARI | 每個分區的三軸tuple各自一對一編為1D群標籤，在相同canonical ID順序比Adjusted Rand Index；每種子≥0.80。不攤平三欄或平均三個軸ARI |
| 退化分區 | 參考或任一種子只剩單群／每ID一群，即使ARI=1也不得通過 |
| 小joint cell | N低於同一支援門檻時，另標insufficient_group_support；不得對該cell宣稱穩定或自動合併。這是個別cell限制，不單獨使全域ARI gate失敗 |

0.90、0.80與支援門檻是**本專案預先約定的研究檢查門檻**，沒有當成通用統計標準、效果保證或行銷收益；尚未執行，未保證本資料能通過。ARI只比兩個分區一致程度，參考分箱不是顧客真實群別；標籤編號可不同。[ARI定義](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.adjusted_rand_score.html)

五次抽樣不是五份新時間資料或信賴區間。未達門檻就保留描述與失敗項，不能同輪換seed、切點、權重、群數或門檻直到通過。

### 跨時間穩定性

**pending_data**。只有單一T／快照，不能用同資料重抽樣宣稱跨月、未來回購／消費、顧客價值或營運效果。新的S／T與完整名冊、可得／版本、觀察及對帳證據須另驗；不重建舊bundle來假造第二期。

## 分階段決策與未來產物

| Gate | 驗收與下一步 |
| --- | --- |
| G0：版本與資格 | 來源、整包guard、同ID、schema、state、數值範圍及金額守恆任一失敗即停止。這輪只核既有metadata／bytes沿用，未重做個體反讀 |
| G1：只讀描述 | 日後先實作守門與合成驗證，再執行固定摘要；每個分母、null／退化原因均明列。本輪尚未實作／執行描述器 |
| G2：規則候選 | G1接受且另確認執行後，才估切點／tuple；須通過級數、每軸bin支援與100%重現，不將IQR旗標變成刪人 |
| G3：方法敏感度 | 五種子全通過級數、每軸bin支援、agreement／ARI及退化檢查；小joint cell另列限制，不強迫合併 |
| 時間／業務交付 | 即使G1–G3通過，仍待新資料／外部用途驗收，沒有自動授權營運、行銷或模型訓練 |

未來私有命名空間預定`.runtime/stage6_rfm_evaluation_v1/`，**本輪未建立**。規格只列描述聚合、待授權切點／支援與敏感度聚合的必要欄位；不產生個體tuple帳本或分數。公開只可列聚合及gate狀態，ID、個體RFM與私有CSV digest仍不提交。

## 本輪來源查核與操作

新增的[方法資料](../scripts/rfm_evaluation_contract.py)與[凍結入口](../scripts/freeze_rfm_evaluation_spec.py)只保存規則、核JSON與hash；沒有描述統計／分群演算法。入口完整重建原8→12→20份來源鏈，連同原建置規格／報告／驗收、本輪三份方法／入口／測試及requirements-lock，共27份綁定。所有CSV只讀binary作hash，連header都不解析。

另核原私有output_guard、manifest、獨立reference／comparison收據與三檔bundle bytes；完整schema、原聚合、同ID反讀收據及來源描述須相符。私有input guard留`.runtime/stage6_rfm_evaluation_spec_v1/input_guard.json`，公開只列查核結果與引用的原聚合數量。來源、規則、既有guard或輸出不同即停止，不能重凍結繞過；前後版本都要核對。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_evaluation_spec -q
.\.venv\Scripts\python.exe scripts\freeze_rfm_evaluation_spec.py --specification-only
.\.venv\Scripts\python.exe scripts\freeze_rfm_evaluation_spec.py --audit
```

上述入口不會做RFM描述或分群；需要既有四CSV、公開來源與私有驗收證據。`--specification-only`只在規則／來源相同時接受既有bytes；`--audit`核原input guard再寫聚合查核，禁止改寫不同結果。缺原始／私有檔則停止，不重跑原builder或Stage 4／5訓練補證據。

| 本輪驗證 | 實際結果與解讀 |
| --- | --- |
| 合成守門 | 32項全過、9.171183秒；核完整來源、不可解析opaque CSV、型別／bytes、不同輸出拒收與同步改寫矛盾摘要。未實作或測試描述／分箱演算法 |
| 真實metadata沿用 | 27份來源與42項metadata檢查全過，原8／12／20來源鏈、原bundle、guard、manifest、獨立收據與母體／金額分母相符 |
| 執行限制 | 真實凍結／稽核時禁止CSV reader／DictReader、原builder與個體反讀入口呼叫仍通過；0描述、0切點、0分群、0重抽樣、0fit／Dashboard |
| 舊證據 | 原130項與3,082,480格反讀是前輪結果，本輪不重跑／加總；既有資料集及Stage 4／5來源保留 |

本輪單元測試及log留`.runtime/stage6_rfm_evaluation_unit.*`。正式入口只產生規格、metadata聚合報告與新的私有input guard，未建立未來分析命名空間或任何個體輸出。

出版檢查通過74份Markdown、1,146個本機連結、118份嚴格JSON；除本輪文件與屬性更新外，473份原追蹤檔及51份原私有證據bytes不變。個體ID與私有bundle digest未進新公開檔，收據留`.runtime/stage6_rfm_evaluation_publication_qa.json`。


下一步只考慮依本規格實作**只讀描述與資格守門**，先以合成資料驗證型別、同ID分流、精確分位rank、ties、IQR退化與金額守恆，再驗收真實描述；切點／tuple、五種子敏感度及任何分群模型另行決定。原入庫／版本、退款／結算與上游完整性仍待資料，Stage 4、5不因本輪規格完成而解封。
