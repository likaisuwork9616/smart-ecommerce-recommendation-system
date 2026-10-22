# Stage 6：真實只讀描述串接與執行準備

已串接來源守門、獨立完整同ID名冊、單次凍結描述器、私有／公開聚合輸出及反讀驗收，並凍結[執行規格](../reports/stage6/rfm_description_execution_specification.json)與[準備查核](../reports/stage6/rfm_description_execution_preflight.json)。**本輪只執行合成測試與真實來源的metadata／hash準備查核，未執行真實描述或建立真實名冊。** 切點、分數／分群、重抽樣、訓練及Dashboard均未執行；Stage 4、5待資料，Stage 4每日10%與11／29／42／73／101五種子不變。

[前輪純描述器](STAGE6_RFM_DESCRIPTION_IMPLEMENTATION.md)與[評估方法](STAGE6_RFM_EVALUATION_SPEC.md)原位保留，程式／JSON／私有產物bytes不改。本輪新增串接，沒有將前輪46項或原資料集反讀結果回寫成本輪新成果，也沒有新的分布、模型或業務結論。

## 來源守門與完整名冊

| 層次 | 已凍結行為 |
| --- | --- |
| [來源載入器](../scripts/rfm_description_sources.py) | metadata_snapshot重建原33份來源／receipt／guard鏈，再綁原implementation spec及報告，形成35份公開輸入；只hash CSV bytes，另綁7份私有metadata與原三檔bundle |
| 本輪41份來源 | 上述35＋sources／outputs／prepare三個模組及三套測試，共6份；測試前後來源相同，實測receipt與規格也須完全相符 |
| 獨立顧客名冊 | 未來read_inputs才讀原orders／customers最小事件／身分投影，以凍結事件資格重建T前合格歷史顧客UID全集；不從已篩選的customers.csv反造expected IDs |
| 獨立逐單名冊 | 同時重建所有purchase<T訂單ID及窗口合格訂單ID；對每單UID映射、解析時鐘、in_window、history／window eligible、排除原因、隔離及核准缺失旗標逐項核對 |
| 母體外訂單 | T前非合格／隔離單仍保留order roster，不能inner join顧客名冊刪掉；purchase≥T不入T前名冊，無法定位購買或歷史身分缺失即停止 |
| 已驗收資料 | 讀原bundle時先核完整版本／bytes，再用既有strict typed反讀及ledger語義；完整顧客、全部T前訂單及窗口集合都須與原來源名冊同ID |

名冊函式已以合成資料驗證，**真實名冊本輪尚未產生或逐ID重驗**。準備報告引用的93,234顧客／99,421逐單只是原驗收metadata，不是本輪新名冊結果。缺／重複主鍵、縮掉零活動顧客、交換同ID的顧客映射／資格、錯誤時鐘、漏母體外訂單或前後source bytes變更都須停止，不能修剪名冊、重建原guard或改S／T放行。

## 串接入口與單次描述

[prepare_rfm_description.py](../scripts/prepare_rfm_description.py)的CLI只有`--prepare`，不提供真實執行或路徑覆寫參數。prepare核41來源、原42項metadata、三套實測receipt，再封存spec／input_guard／preflight；不呼叫read_inputs、derive_roster、describe_dataset或output writer。

未來真正執行路徑已在`execute_prepared(root)`接妥，只供本輪合成端到端測試，沒有對本機真實workspace呼叫：

1. 確認已凍結的spec、input guard、實測receipt與metadata相符，未來輸出／output guard／failure均不存在。
2. read_inputs載入原bundle與獨立來源名冊，核完整ID、每單證據及前後snapshot。
3. 將獨立customer_ids強制傳入凍結core，恰好一次呼叫describe_dataset；只對active_complete計摘要，其他狀態保留原遮罩。
4. 先對整包私有輸出預檢，在新staging寫入並與core原聚合、原loaded ledger和名冊完整反讀，通過後發布目錄。
5. 來源仍須相同；再寫公開白名單聚合、核canonical bytes，最後建立外部output guard，綁私有四檔及公開檔bytes。
6. 末端再核source、private／public bytes與output guard反讀，全部完成才回傳成功。

不得改用其他資料、重建RFM、選參或重估切點。原core的source_version只含format／S／T等，不能單獨識別實際版本；本輪公開包裝另綁**完整execution SPEC descriptor與41份來源版本**，私有input guard則保留原bundle／metadata fingerprints。

## 私有／公開輸出契約

未來沿用原規格預留的`.runtime/stage6_rfm_evaluation_v1/`；本輪沒有建立這個目錄。私人四檔bundle固定如下：

| 檔案 | 內容與反讀 |
| --- | --- |
| description.json | 凍結core完整聚合；每個nested key／型別／null／整數／float64位元須與本次原始輸出一致，不含個體列 |
| customer_roster.csv | customer_unique_id、activity_state、eligible_for_numeric_description三欄；唯一完整UID升冪，可用旗標須等於active_complete／原rfm_usable，不能用F>0替代 |
| order_roster.csv | order_id、customer_unique_id、history_event_eligible、window_event_eligible、window_quarantine五欄；唯一ID升冪，保留所有T前來源單，包括顧客母體外單 |
| manifest.json | 版本／公開provenance、schema、列數、前三檔私有digest、母體／金額守恆與反讀receipt；manifest自身由外部guard綁定 |

CSV沿用UTF-8、固定欄序、lowercase true／false；JSON拒重複key、非有限值及非canonical bytes，`true`／`1.0`不可冒充整數。反讀列出兩份名冊列數、`3×顧客列＋5×逐單列`比對格數、聚合scalar及binary64比較數；數字須來自實際執行，不預填為完成。

[outputs模組](../scripts/rfm_description_outputs.py)另以loaded dataset核完整同ID、五狀態分流、N／null計數、F與已知商品額／遮罩子集守恆，防止「自寫自比」的錯誤摘要。它不重新計任意median／log真值：統計正確性由唯一凍結core呼叫、既有oracle及本輪端到端合成案例支持，反讀證明完整持久化與語義一致，不能混稱獨立統計重算。

未來公開`reports/stage6/rfm_description.json`只含規格descriptor、完整公開來源版本、凍結聚合、執行範圍及反讀receipt。完整nested白名單拒絕額外ID欄／私有digest，名冊、原始資料及input／output guard不提交Git。

## 失敗與成功判定

已存在的輸出目錄即使是空目錄也拒絕重建；spec／input_guard／preflight只有部分存在或bytes不同也停止。私有staging反讀失敗時保留證據、不發布；執行途中失敗留私有failure.json，之後不得自動resume、覆寫或刪證據重跑。

跨私有四檔、公開JSON與外部guard不是一個跨檔案原子交易。**公開JSON即使已存在或內文寫readback_accepted，也不能單獨視為整輪成功**：末端guard寫入失敗仍可能留下部分public與failure。必須output_guard有效、無failure，且`verify_completed(root)`通過，才接受完整交付；失敗時不回傳成功，不把部分產物當可交付成果。

verify_completed先核來源／guard及private／public bytes，再核同ID與typed反讀，**不重跑core、不新增描述統計**。既有成功產物、失敗收據或部分產物都會阻止execute_prepared重播。任何之後修復／改版都需保留原證據並重新約定版本，不能重凍結來放行舊guard差異。

## 本輪實際合成驗收

| 類別 | 實際結果 |
| --- | --- |
| sources | 20項全過：獨立全集、時鐘／未知、母體外／未來單、同ID但錯映射、同步縮名冊、原33來源與opaque CSV metadata-only守門 |
| outputs | 21項全過：四檔schema、全ID／欄值／nullable／binary64、large int／零值／空集合／IQR退化、M守恆、nested leak、版本與bytes改動、整包防覆寫及failed staging |
| runner | 17項全過：prepare不load／describe／write、41來源及receipt、真實CLI拒收；synthetic E2E單core、母體外訂單保留、只讀verify不再core、source中途變更、writer／public失敗停止與禁止重播 |
| 本輪合計 | 58項、18.236869秒，0 error／failure／skip；測試前後完整41來源相同。原46／32／130項與全專案discover未重跑或加總 |
| 端到端數值例 | 合成M=[1,1,2,9,9]經原始投影→獨立名冊→core→四檔／public反讀後，仍sum=22、Q99=9、尾端N=2／尾額18；不是Olist分布或群組效果 |
| 真實準備 | 41來源與原42項metadata通過；禁止CSV reader／DictReader、名冊衍生、loader、core、writer及個體反讀時，prepare仍成功 |

本輪合成測試在私有scratch建立／反讀合成四檔與公開聚合，已驗證執行路徑；**真實CSV／名冊／描述及未來公開結果均未執行或建立**。單元測試receipt與log留`.runtime/stage6_rfm_description_execution_unit.*`，不能把synthetic success當真實交付通過。

## 操作與本輪產物

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_description_sources tests.test_rfm_description_outputs tests.test_prepare_rfm_description -q
.\.venv\Scripts\python.exe scripts\prepare_rfm_description.py --prepare
```

合成suite不需真實CSV／MySQL／模型。prepare需原來源、全部私有驗收證據與本輪實際source-bound測試receipt，缺件／不同版本即停止；它不自動重跑suite或真實描述。Git clone可跑合成測試，但不包含原始資料、名冊或私有guard，不能偽造成功receipt／重建原證據補齊。

| 位置 | 本輪狀態 |
| --- | --- |
| reports/stage6/rfm_description_execution_specification.json | 已凍結41來源、固定輸出schema、完整名冊與成功／失敗契約 |
| reports/stage6/rfm_description_execution_preflight.json | 已記合成58測、metadata沿用及real_description_executed=false |
| .runtime/stage6_rfm_description_execution_v1/input_guard.json | 已建立；只含source／原private snapshot及實測receipt版本，Git忽略 |
| .runtime/stage6_rfm_evaluation_v1/ | 未建立；未來私有四檔名冊／描述bundle |
| reports/stage6/rfm_description.json | 未建立；未來真實聚合結果 |
| execution_v1/output_guard.json、failure.json | 本輪未建立；僅未來execute／失敗時使用 |

發布前檢查通過：76份Markdown的1,183個本機檔案連結均存在，122份JSON通過嚴格解析；486份未列為本輪文件／屬性修改的既有追蹤檔與64份既有私有驗收證據bytes相同。41份來源與凍結準備再次相符，未來真實輸出仍不存在；新公開JSON未含32位個體ID或私有bundle／receipt／guard digest。檢查紀錄留在Git忽略的`.runtime/stage6_rfm_description_execution_publication_qa.json`。

下一步可另輪依此凍結入口執行**一次真實只讀描述**，核完整同ID、來源版本與全部聚合反讀，再解讀G1描述結果。仍不估分群切點、不分群／訓練或Dashboard；單一快照沒有跨時間穩定性，原入庫／版本、退款／結算及上游完整性仍待資料，也不把商品毛額當淨消費或未來價值。
