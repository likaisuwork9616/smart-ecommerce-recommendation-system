# Stage 6：真實G2規則候選的來源、輸出與反讀準備

本輪承接[規則候選與資格守門合成驗收](STAGE6_RFM_RULE_CANDIDATE_IMPLEMENTATION.md)，準備一次真實G2執行所需的完整來源、獨立同ID名冊、輸出與反讀契約。**本輪只走合成接線驗收與真實來源metadata／binary hash查核，沒有解析真實CSV、建立真實G2名冊、估真實切點或產生真實序數／tuple。** 真實執行仍待另行決定。

原[評估方法](STAGE6_RFM_EVALUATION_SPEC.md)、G2核心、G1真實描述、資料集與既有來源／報告／guard保持原bytes；新[執行規格](../reports/stage6/rfm_rule_candidate_execution_specification.json)與[準備查核](../reports/stage6/rfm_rule_candidate_execution_preflight.json)獨立保存本輪狀態，不回寫舊policy的current_run。Stage 4、5維持待資料，Stage 4每日10%與11／29／42／73／101五種子不變；G3敏感度、分群模型、訓練與Dashboard均未進行。

## 來源與G1接受證據

| 層次 | 凍結契約 |
| --- | --- |
| 已完成的G2合成驗收 | [來源模組](../scripts/rfm_rule_candidate_sources.py)核原49來源、implementation specification、verification及私有guard／實測log，不能首建或重跑前輪suite補證據 |
| 完整57份公開來源 | 原49＋前輪G2 specification／verification兩份＝51，再加本輪sources／outputs／prepare三個模組及三套測試6份；實測receipt、spec與執行前後bytes須完整相符 |
| G1既有交付 | 沿用[一次真實描述驗收](STAGE6_RFM_DESCRIPTION_RESULTS.md)，綁原execution spec、input／output guard、私有四檔與公開聚合；準備時只核metadata與bytes，不重新描述或做個體反讀 |
| 原資料集 | 沿用S=2017-09-01、T=2018-09-01的既有RFM v1、原16＋16欄與整包guard；不能重建、修補、換窗口或加入新來源放行 |
| G1接受與授權界線 | 未來loader須驗G1的完整反讀及接受證據後才供給core的g1_accepted=True。此旗標不取代來源證據，也不把準備完成當成已授權真實執行 |

本輪metadata查核仍只證明原版本可沿用。原93,234顧客／99,421筆T前訂單及72,124完整活躍顧客是既有驗收metadata；沒有在本輪解析真實來源或逐ID重建，不能稱為新的同ID驗收結果。

## 未來完整同ID載入

`read_inputs(root, expected_snapshot)`只供合成測試及之後另行決定的真實執行使用，本輪不對真實workspace呼叫。它先驗完整snapshot，再沿用原orders／customers最小身分及事件投影，獨立衍生顧客、所有T前訂單與窗口合格訂單三份名冊；不是從已篩過的RFM顧客CSV再造expected IDs。

| 名冊／語義 | 未來執行的必要反讀 |
| --- | --- |
| 顧客全集 | 原歷史合格事件UID全集與已驗收customers.csv完全同ID，包含乾淨零活動及不完整狀態，不得inner join刪人 |
| 全部T前訂單 | purchase<T的所有order ID都保留，含隔離、非合格及顧客母體外訂單；purchase≥T不入此名冊 |
| 窗口合格訂單 | S≤purchase<T且原事件資格成立的order ID全集須一致，不能只核列數 |
| 逐單proof | 原UID映射、purchase／approval／delivery時鐘、in_window、history／window eligible、排除原因、隔離與核准缺失旗標逐項一致 |
| 原RFM語義 | strict schema／精確型別、五狀態聯合旗標、R／F／M範圍、null遮罩、逐單重建與商品金額守恆沿用G0，不以M>0篩人 |
| G1完整交付 | 載入既有G1私有四檔，與本次獨立名冊／dataset、原公開聚合及output guard完整反讀；禁止重跑G1 describe_dataset |
| 前後來源 | 讀取前後同一完整snapshot；任何bytes、ID、映射、時鐘、狀態或守恆差異即停止，不改guard／名冊補過 |

## 準備入口與未來單次執行

[prepare_rfm_rule_candidate.py](../scripts/prepare_rfm_rule_candidate.py)的CLI只有`--prepare`，沒有真實執行、CSV輸入或路徑覆寫參數。prepare核57來源、既有metadata及三套實際source-bound測試收據，固定spec／input_guard／preflight；不呼叫真實loader、名冊衍生、G1個體反讀、G2 core或writer。

`execute_prepared(root)`與`verify_completed(root)`是凍結的未來callable，本輪只在合成scratch測試。真實執行若另行決定，流程固定為：

1. 所有準備產物與實測receipt同版，未來私有bundle、公開結果、output guard及failure均不存在。
2. 讀原已驗收RFM與原來源獨立名冊，核完整同ID、逐單proof及G1交付，不重算G1描述。
3. 強制將完整customer_ids及已驗G1接受傳入唯一凍結G2 core，恰好一次呼叫；只對active_complete估P20／40／60／80並分配，合法M=0保留。
4. 先在新staging寫入私有bundle，核全部名冊、分配及aggregate；通過完整反讀才發布目錄。
5. 前後來源相同後再寫公開白名單聚合，核canonical bytes，最後建立外部output guard。
6. 再核來源、私有／公開bytes與外部guard；完整通過且無failure才回傳完成。

核心仍使用原精確整數rank、ties不拆、去重／移除max切點、實際有效級數、每軸bin支援及100%同ID列序重現。不得為求通過改切點、權重、支援門檻或資料範圍。seed42排列只是同資料列序驗證，沒有執行G3的五種子80%抽樣、agreement或ARI。

## 私有與公開輸出契約

未來私有namespace為`.runtime/stage6_rfm_rule_candidate_v1/`，與既有G1的`.runtime/stage6_rfm_evaluation_v1/`分開，不能覆寫G1。本輪未建立真實G2輸出目錄。固定四檔如下，精確欄序／型別以[執行規格](../reports/stage6/rfm_rule_candidate_execution_specification.json)及[outputs模組](../scripts/rfm_rule_candidate_outputs.py)為準：

| 檔案 | 內容與限制 |
| --- | --- |
| candidate.json | 原core完整aggregate，含每軸原始／保留切點、有效級數、bin支援、實際中性tuple cell計數、失敗原因、重現及gate；不得加入個體ID或私有digest |
| customer_roster.csv | 完整顧客ID升冪，共9欄：customer_unique_id、activity_state、eligible_for_rule_candidate、r／f／m_numeric_bin及r／f／m_ordinal。完整活躍以外後六欄全null，不能填0或用部分R／F產生tuple；三個序數共同表示中性tuple，沒有加總價值分 |
| order_roster.csv | 完整T前訂單ID升冪，共11欄逐單proof：order_id、customer_unique_id、purchase_at、approval_at、delivery_at、in_window、history_event_eligible、window_event_eligible、primary_exclusion_reason、window_quarantine、approval_missing_or_invalid。包括顧客母體外／非合格／隔離單，不因無顧客分配而刪除 |
| manifest.json | 版本、公開provenance、固定schema／列數、前三檔私有digest及反讀receipt；自身由外部output guard綁定，不提交Git |

CSV沿用UTF-8、固定欄序、lowercase true／false與空欄null，整數禁止float或bool替代；JSON拒重複key、非有限值、額外欄位與非canonical bytes。所有名冊列、分配欄及aggregate scalar須完整反讀，包含精確型別／null及存在時的binary64位元。

反讀不再呼叫G2 core。它從原載入RFM獨立計算精確rank／預期切點，核已保存切點及完整每ID的數值箱、R按實際k反向、F／M序數與tuple，再核ties、每軸N／支援、joint cell及G2 gate；不能只比箱大小或把自寫自比當獨立驗收。這是驗已存規則的數值真值，沒有建立另一候選或改選切點。列序重現依唯一凍結core執行與既有對抗測試提供證據，反讀不另重跑反序／seed42候選。

`read_outputs`只驗持久化與bundle內部自洽；manifest中的獨立source驗收旗標是writer先前完成來源核對所留的證據，不表示這個helper重新取得外部真值。只有`verify_outputs`帶入本次已載入的原來源／完整名冊，才重新支持獨立rank、切點與每ID分配驗收。

未來公開`reports/stage6/rfm_rule_candidate.json`只含57來源公開版本、execution SPEC descriptor、完整白名單aggregate、固定delivery及實際反讀receipt。aggregate.execution是純core執行範圍，因此private_individual_files_written保持false；外層delivery另明列private_assignment_roster_written=true、四檔已交付及反讀未重跑G2 core，避免把純core與writer的寫檔行為混稱。顧客／訂單名冊、個體箱／序數／tuple、原始RFM值、私有bundle／guard／receipt digest均不公開。

## 候選不合格與技術失敗

G2級數不足、常數軸或bin支援不足會保留完整候選與失敗原因，`G2=ineligible`。這表示一次候選研究已完成但不具資格，仍需保存所有active分配、完整反讀與output guard；不能當成可重切／重播的技術失敗。小joint cell另標支援不足，不單獨使G2失敗或自動合併。

來源／G0／同ID／反讀失敗、寫檔失敗或執行中bytes變動則停止，留私有failure證據，不回傳成功。既有bundle即使空目錄、部分準備產物、既有output guard／failure或不同bytes都阻止重建／重播；failed staging保留，不刪證據自動恢復。

私有四檔、公開JSON與外部guard不是跨檔原子交易。公開JSON存在或內文寫readback_accepted，不能單獨代表整輪完成；必須有效output guard、無failure，且`verify_completed`以同版來源完整反讀通過。verify_completed禁止G1及G2 core重執行，不建立另一候選或選規則；反讀仍須獨立核rank、預期切點與每ID分配。

## 操作與本輪交付

三套新合成測試不需要真實CSV、MySQL或模型：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_rule_candidate_sources tests.test_rfm_rule_candidate_outputs tests.test_prepare_rfm_rule_candidate -q
```

在保留原來源、全部私有驗收證據與本輪實測source-bound收據的工作目錄，可驗準備產物：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_rfm_rule_candidate.py --prepare
```

prepare不自動重跑suite或補建前輪證據。一般clone可跑合成測試，但不含真實來源／私有名冊與guard，不能偽造成功receipt或重建原資料補過。

## 本輪實測驗收

以下為正式source-bound收據與準備入口的實際執行，與前輪60項核心合成驗收分開，不加總為模型效能或未知資料成績。

| 本輪驗收 | 實際結果與解讀 |
| --- | --- |
| 三套合成測試 | 68項全過、75.543972秒，0 error／failure／skip；sources 17、outputs 27、prepare 24，完整test IDs及來源綁定見準備報告 |
| 完整合成接線 | 原來源獨立五狀態／全部T前與母體外訂單→既有G1完整反讀→恰好一次G2 core→私有四檔／公開聚合／外部guard通過；完成verify時封鎖G1與G2 core仍通過 |
| 完成與資格分開 | 合成500人每軸5級、各箱100人通過G2並完整反讀；五狀態小樣本的G2不合格仍完整交付失敗原因、無technical failure，不能重切／重播 |
| 對抗與晚期失敗 | 缺／換／重複ID、同箱人數但ID分配互換、同步改candidate／manifest、來源／guard改寫皆拒收；公開JSON已寫但output guard失敗時仍留failure、不能宣稱成功或自動恢復 |
| 真實metadata準備 | 完整57來源、原42項metadata及既有G1／G2證據bytes相符；93,234顧客／99,421訂單只是沿用既有列數，不是本輪新逐ID驗收 |
| 真實範圍驗證 | 實際prepare期間封鎖19個CSV解析、來源loader／名冊、G1／G2 core、個體反讀、builder／writer及前輪run入口，0呼叫仍通過；未來四檔namespace、公開結果、output guard及failure全部未建立 |
| 舊證據保留 | 原515份追蹤檔僅7份文件／屬性更新，其餘508份及326份既有私有檔bytes不變；原RFM、G1／G2及Stage 4／5凍結證據保留 |

實測suite收據／log留`.runtime/stage6_rfm_rule_candidate_execution_unit.*`，封鎖入口與未來產物未建立的查核留`.runtime/stage6_rfm_rule_candidate_preparation_scope.json`；均不提交Git。prepare只核實測receipt與來源，不重跑suite。

出版檢查通過79份Markdown、1,299個本機連結及128份嚴格JSON；57來源相符，新增公開內容不含私有bundle digest，真實G2未來產物仍全部未建立。收據留`.runtime/stage6_rfm_rule_candidate_execution_publication_qa.json`。正式CLI重入也已通過同版準備產物驗收，沒有重跑suite或改寫既有證據。

| 位置／工作 | 本輪狀態與結果 |
| --- | --- |
| reports/stage6/rfm_rule_candidate_execution_specification.json | 凍結57來源、完整名冊、固定輸出schema及完成／失敗契約 |
| reports/stage6/rfm_rule_candidate_execution_preflight.json | 保存實際三套合成驗證與metadata準備結果；測數／耗時以正式報告為準 |
| .runtime/stage6_rfm_rule_candidate_execution_v1/input_guard.json | 綁完整snapshot、準備spec與實測receipt，Git忽略 |
| .runtime/stage6_rfm_rule_candidate_v1/ | 真實輸出未建立；四檔只在合成scratch驗證 |
| reports/stage6/rfm_rule_candidate.json | 真實聚合結果未建立 |
| execution_v1/output_guard.json、failure.json | 真實控制產物未建立，只供日後執行／失敗使用 |

下一步另行決定是否依本凍結入口執行一次真實G2；若執行，只接受原規則的通過或不合格結果並完成完整反讀，不自動進入G3、改規則或分群模型。單一快照仍不能證明跨時間、未來回購／價值或營運效果，原入庫／版本、退款／結算與上游完整性仍待資料。
