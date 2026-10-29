# 測試與驗證

自動測試使用Python標準庫`unittest`，從專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

最近一次全專案測試在2026-10-22第二次專案清整時執行：1,764項全過（unittest回報605.317秒），0失敗／錯誤／跳過。該次只改文件，程式與測試未變；這是回歸確認，不是新研究結果或模型效能。

Stage 4在[完成歷史代表性稽核](../docs/STAGE4_COMPLETED_HISTORY_REPRESENTATIVENESS.md)時曾跑全專案867項（165.394秒）；其後各輪只跑當輪相關測試，測數與耗時記在下列各節及當輪報告，不能合稱完整測試。測試數與獨立對帳數都不是模型效能；[交接清單與驗收範本](../docs/templates/daily_data_handoff/README.md)只檢查文件與空白格式，範本案例不能當成真實資料已驗收。

## Stage 12：一次真實 validation 停止後核對（最新）

本輪未重跑合成測試；啟動前與停止後各核 358 份來源、61 份準備產物與 locked gates。真實主要輸出已有 166,897 query／2,000 bootstrap，完整獨立反讀未完成，不能以列數或 SHA 核對當成研究驗收。下節 83 項是前輪準備紀錄。見[實際停止與保存](../reports/stage12/retailrocket_session_knn_v1_validation_attempt.json)。

## Stage 12：來源檔案、完整反讀與單次入口（前輪）

正式準備共 83 項通過（34 新來源／反讀／入口＋49 既有 K1）。新增測試模組 [validation](test_retailrocket_session_knn_validation.py) 與 [entry](test_retailrocket_session_knn_validation_entry.py) 涵蓋 15 份原格式輸入、501 鄰居、完整 SQL／候選／巢狀驗收、來源／輸出竄改、current／next basket、三臂原值／身分、缺多重複列、分母、finite binary64、中斷／超限／禁止重播及真實資料文字讀取禁用。兩組正式合成各核 2,000 draws，見[驗收](../reports/stage12/retailrocket_session_knn_v1_validation_entry_acceptance.json)。

`.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_session_knn_validation tests.test_retailrocket_session_knn_validation_entry -v` 只跑新增 34 項合成測試，不執行真實 validation；83 不是全專案測試數。

## Stage 12：K1 合成實作、oracle 與入口守門（前輪）

`.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_session_knn tests.test_retailrocket_session_knn_entry tests.test_retailrocket_session_knn_spec -v`：49 項通過（31 核心／完整 oracle／成本、6 入口、12 原規格）。兩組正式合成另完整反讀每組 2,000 次 bootstrap；非 train 商品欄使用不可解碼字串驗證成本分流。本命令不讀真實 train 商品列或真實 validation；實際成本驗收見[報告](../reports/stage12/retailrocket_session_knn_v1_implementation_acceptance.json)。

## Stage 12：K1 metadata 與凍結守門（前輪）

`.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_session_knn_spec -v`：12 項規格／I/O 測試通過，涵蓋候選／鄰居改動、分母與主要比較、bootstrap、預留測試／refit、資源、假可取得性、路徑越界、同大小竄改及部分產物拒絕覆寫。合成小檔保存於 shop 內忽略路徑；沒有實作或驗收 K1 排名算法。

## Stage 11：三臂交付保存驗收

本輪 [保存工具 I/O 測試](test_archive_retailrocket_three_arm_v1.py) 共 44 項通過，0 失敗／錯誤／跳過。合成 fixture 全在 shop；涵蓋 SHA／CRC／精確 inventory、安全相對路徑、重複與越界、三臂 namespace、gate、來源變更與拒覆寫／部分產物。沒有重跑模型測試或研究 oracle。

真實證據包 144 個 payload 檔＋1 份 manifest，共 145 個 ZIP 成員，649,850,977 bytes（619.746 MiB）；全部成員 CRC／SHA-256 反讀通過，另列 159 份包外依賴。保存核對只證明 bytes 完整，不取代前輪逐筆語意驗收；[收據](../reports/stage11/retailrocket_three_arm_v1_research_release.json)與[適用／還原限制](../docs/STAGE11_RETAILROCKET_THREE_ARM_RESEARCH_HANDOFF_V1.md)保留各自範圍。

## Stage 11：D1 真實三臂逐筆反讀（執行輪）

本輪直接執行已凍結入口，沒有重跑合成測試或更改程式。獨立 SQL 反讀 support 198,946 列、directed edges 370,325 列、session lineage 1,180,256 筆、validation queries 166,897 筆及全部 2,000 次抽樣。所有巢狀值、精確有理分數／排序、三臂控制與分母、同 draw／RNG／分母及新 D1−C1 delta 全核對；報告的 top_level_cells 只計頂層，不能當作巢狀總格數。

見[獨立驗收收據](../reports/stage11/retailrocket_directed_v1_validation_acceptance.json)及[結果／限制](../docs/STAGE11_RETAILROCKET_DIRECTED_VALIDATION_V1.md)。現用 `scripts/run_retailrocket_directed_v1.py --verify` 只核保存 bytes，不重播 fit／排名／抽樣；P0／C1 原狀、test locked。

## Stage 11：D1 實作／三臂／bootstrap 驗收（合成輪）

60 項測試、217 份來源凍結、兩組正式合成 oracle 全過。測試在 [D1 核心／整合](test_retailrocket_directed.py)與[入口／成本](test_retailrocket_directed_entry.py)，包含手算、24×6 完整候選差分、三臂缺筆／順序／分母、參照與輸出污染、成組權重／同 draw 新 delta、資源停止與拒絕重播。正式兩組各 5 queries，全部巢狀值與各 2,000 抽樣獨立反讀。

真實 train-only 成本另核 1,180,256 列／10,622,304 格；沒有真實 D1 fit／排名／成績。實測見[收據](../reports/stage11/retailrocket_directed_v1_implementation_acceptance.json)。保存後使用 `scripts/run_retailrocket_directed_v1.py --verify` 只核來源與結果 bytes；不是重跑模型或測試。

## Stage 11：D1 規格與凍結工具驗收（規格輪）

199 份來源 SHA、228 項規格檢查、109 項規格／I/O 守門測試通過。本輪 [規格／I/O 測試](test_retailrocket_directed_protocol.py)檢查契約變更阻擋、完整三臂分母與主要比較、方向／支援／回退邊界、已曝光標示、鎖定／越界／拒絕覆寫等；合成暫存全部在 shop。這不是 D1 計數、排名或 bootstrap 的實作 oracle，後者尚待下一輪。

正式收據見[規格驗收](../reports/stage11/retailrocket_directed_v1_spec_acceptance.json)。完成後可用下列命令只核既有 bytes 與 metadata，不重跑測試或讀真實資料列：

```powershell
.venv\Scripts\python.exe -B scripts\freeze_retailrocket_directed_v1.py --verify
```

## C1／P0研究交付保存驗收（最新）

本輪29項[保存I/O合成測試](test_archive_retailrocket_c1_p0_v1.py)通過：逐成員CRC／SHA、來源與ZIP竄改／缺檔、路徑越界／重複成員、拒絕覆寫及部分證據保留；暫存均在shop內。正式保存另逐檔讀回102個payload，核對凍結來源／包外依賴與4份gate，見[收據](../reports/stage10/retailrocket_c1_p0_v1_research_release.json)。

```powershell
.venv\Scripts\python.exe -B scripts\archive_retailrocket_c1_p0_v1.py --verify
```

這是保存驗收，不是重新執行前輪55項推薦合成測試或真實oracle；本輪0新fit／排名／bootstrap／指標重算。

## Retailrocket C1／P0真實逐筆反讀（執行輪）

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

單次C1 fit與獨立SQL重建後，support 198,946、pairs 1,954,889、session lineage 1,180,256、query 166,897、bootstrap 2,000筆均完整核對；JSON巢狀值全部反讀，全部抽樣SHA／RNG／分母／差值重播。沿用55項已凍結合成測試，不重跑或加總成新的測試數。見[正式驗收](../reports/stage10/retailrocket_cooccurrence_v1_validation_acceptance.json)。

--verify只核現有bytes。原規格freeze的初始空目錄檢查是歷史用途，已有真實產物後改用上述新入口；P0及鎖定快照原狀核SHA，test仍locked。

## Retailrocket C1／配對／bootstrap 實作驗收（合成輪）

```powershell
.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_cooccurrence tests.test_retailrocket_cooccurrence_entry -v
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

55 項測試、104 份來源凍結與兩組正式合成 oracle 全過。含40組固定合成session×8查詢的320筆完整候選差分、手算不可達target分母／有理平手／P0回退、配對缺筆／分母漂移、兩組正式5查詢case的SQL／完整有理排序／Decimal及所有JSON巢狀反讀、各2000次bootstrap重播；資源超限、started／failure及拒絕重播亦有反例。成本另核真實train-only 1,180,256列／5,901,280格，不建立模型或讀validation／test內容。該合成輪0真實C1 fit或出分，後續真實反讀見上節；不能將合成結果當推薦效能；見[驗收收據](../reports/stage10/retailrocket_cooccurrence_v1_implementation_acceptance.json)。

## Retailrocket 共現／P0 配對規格守門（規格輪）

```powershell
.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_cooccurrence_protocol -v
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

64 項規格測試通過：已驗收 P0 metadata 正例，以及重複計數、刪 singleton、未來 session／歷史、截斷／抽樣、回退／有理排序、P0 重估、配對缺筆／分母、bootstrap 叢集權重／seed／版本、測試解鎖等反例。正式凍結收據另記錄 131 項一致性檢查及 82 來源。這些是該規格輪的守門，當時尚未實作；後續實作及合成 oracle 已完成於上一節。規格守門不能當算法或真實效果驗收。

## Retailrocket P0真實開發逐query反讀（最新）

```powershell
.\.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
```

一次真實train fit與一次獨立SQL audit後，完整166,897筆validation的四CSV共699,637列／5,738,596格及全部JSON聚合核對一致。ID／次數／列表精確，指標以獨立Decimal／Fraction核對abs／rel 1e-12，見[真實驗收收據](../reports/stage9/retailrocket_popularity_v1_development_acceptance.json)。本輪沿用凍結54項合成證據，不重跑或加總成新測試數。

`--verify`核既有來源／輸出bytes，不重估或重算語意。這是已觀察的回溯開發驗證，0訓練期排名、0最終重估／預留測試，test仍locked，小組限制保留；詳見[結果與限制](../docs/STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md)。

## Retailrocket P0／評估器與開發入口合成驗收

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_popularity tests.test_retailrocket_popularity_entry -v
.\.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
```

[核心／CSV測試](test_retailrocket_popularity.py)及[入口測試](test_retailrocket_popularity_entry.py)共54項通過，含1,024種命中排列、27個時間前綴、手算macro／不可達target、空候選、零分／同時刻／未來高分、合成四CSV反讀、損壞／分母／覆寫／階段與路徑拒收。另兩個有效合成case以獨立SQL／Decimal／Fraction oracle核35列／226格及全部JSON；[實際收據](../reports/stage9/retailrocket_popularity_v1_implementation_acceptance.json)記錄61來源與真實counter全部0。

這些只證明合成行為與入口準備；尚無166,897筆真實validation成績。`--verify`只核已凍結bytes，不重跑合成或真實fit／指標，test仍locked。下一步依[實作與開發規格](../docs/STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md)做一次真實開發及獨立全反讀。

## Retailrocket熱門baseline／評估規格守門

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_popularity_protocol -v
.\.venv\Scripts\python.exe -B scripts\freeze_retailrocket_popularity_v1.py --verify
```

[28項規格反例](test_retailrocket_popularity_protocol.py)實際通過，拒絕跨角色fit、暖身混入、答案作ranker輸入、負採樣／縮分母／IDCG、空候選刪query、小組門檻降低或錯誤開測試。這是規格守門，尚未實作或測試真實baseline／metric計算。[凍結驗收](../reports/stage9/retailrocket_popularity_v1_spec_acceptance.json)另記47份SHA來源、38項一致性檢查與0真實fit／排名／指標，test locked。

`--verify`只核既有bytes與規格，不重跑測試或語意反讀。後續實作仍須手算指標、精確全目錄排序與獨立oracle合成驗收，再做真實開發；詳見[執行規格](../docs/STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md)。

## Retailrocket推薦資料建置／反讀驗收（最新）

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_builder -v
.\.venv\Scripts\python.exe -B scripts\build_retailrocket_v1.py --verify
```

[30項合成測試](test_retailrocket_builder.py)通過，涵蓋ID、時間窗、30分鐘session、同毫秒、候選／屬性嚴格事前、重複、未知／衝突、尾端不改結果、兩路ZIP一致及損壞CSV。合成產物留shop內Git忽略目錄。真實16CSV共20,093,122列／221,676,649格由獨立原ZIP讀法完整反讀，見[收據](../reports/stage8/retailrocket_build_v1_acceptance.json)。

`--verify`只核既有SHA與來源／輸出／收據，不重跑語意反讀；首次正式流程已完成完整核對。這些是資料驗收，沒有模型／排名成績，不加總歷史測試數冒充新成績。

## Retailrocket來源與推薦契約驗收

本輪沒有新增推薦builder或模型單元測試。實際做的是兩套獨立讀檔（標準CSV／SQLite及pandas）、四檔完整CRC／SHA反讀、44項來源／鍵／時間／契約前提核對；[收據](../reports/stage8/retailrocket_contract_v1_acceptance.json)保留實際檢查項目，不能稱為模型成績或builder逐格驗收。

```powershell
.\.venv\Scripts\python.exe -B scripts\audit_retailrocket_source.py --verify
.\.venv\Scripts\python.exe -B scripts\freeze_retailrocket_contract.py --verify
```

目前CLI只核已保存SHA／大小，不重做語意盤點。該輪提出的builder合成邊界、真實逐筆核對與完整反讀，已由上節後續輪完成；詳見[推薦資料契約](../docs/STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md)。原Stage 6資料／結果不重算，既有單元測試數不加總成新成績。

## UCI v1 封存完整性測試（最新）

[封存測試](test_archive_uci_rfm_v1.py)檢查 UTF-8 原始 bytes、完整 ZIP 反讀、CRC 損壞、合法 CRC 但 SHA 不符、manifest 變更、路徑安全、來源變更、禁止覆寫及部分封存拒絕重播。合成檔全部保留在專案 Git 忽略的 `shop-mysql-runtime/verification/uci-rfm-release-v1/synthetic/`。

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_archive_uci_rfm_v1 -v
.\.venv\Scripts\python.exe -B scripts\archive_uci_rfm_v1.py --verify
```

本輪實跑測試項數、耗時、ZIP 成員數與 CRC／SHA 結果以[封存收據](../reports/stage6/uci_rfm_v1_research_release.json)為準；第二行讀回完整 ZIP 並核 live 凍結研究檔，不重跑測試、RFM 或跨期指標。原有研究測試與逐格驗收收據保留，未重跑全專案回歸。

## UCI v1 跨期評估測試

[新測試](test_uci_rfm_temporal.py)實跑 30 項通過（0.622137 秒，0 失敗／錯誤／跳過），涵蓋逆經驗分位數、同值邊界、T2 禁止估參考、固定套用、平均同秩 Spearman、手算 ARI、退化／空分母、49／50 人支援邊界、完整母體與配對分流、未知金額覆蓋及獨立套件對照。

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_uci_rfm_temporal -v
.\.venv\Scripts\python.exe -B scripts\run_uci_rfm_temporal_v1.py --verify
```

正式驗收另用 pandas／NumPy／SciPy／scikit-learn 重算：9 份分級／名冊共 533,398 格，以及 59,798 項 JSON 欄值核對通過。整數與金額精確一致、衍生浮點容忍度 1e-12；第二行只核 bytes，不重播以上計算。本輪未跑全專案回歸，實際來源／版本與 test IDs 見[驗收](../reports/stage6/uci_rfm_temporal_v1_acceptance.json)。

## UCI v1 建置器測試與真實逐格核對

[建置器測試](test_uci_rfm_builder.py)實跑 30 項通過（0.038255 秒），0 失敗／錯誤／跳過。涵蓋未來衝突不能改 T1、完整與部分未知、取消、零價、精度／溢位、四口徑雙窗獨立 SQL 對帳及同總額交換顧客的反例。

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_uci_rfm_builder -v
.\.venv\Scripts\python.exe -B scripts\build_uci_rfm_v1.py --verify
```

真實驗收另從官方 Excel XML 重讀、用獨立 SQL 核算，32 CSV 共 12,720,628 筆／128,416,372 格全部一致，另有 32 項摘要核對；來源前後與輸出 bytes 通過。第二行只核保存 hashes，不重做以上獨立計算。本輪未跑全專案回歸，沒有真實切點或跨期成績。見[完整驗收](../reports/stage6/uci_rfm_build_v1_acceptance.json)及[結果](../docs/STAGE6_UCI_RFM_BUILD_V1.md)。

## UCI 回溯契約 v1 測試

[新測試](test_uci_rfm_contract.py)實跑 38 項通過（0.204402 秒，0 失敗／錯誤／跳過），涵蓋 S／T 邊界、非重疊年度窗、同值分級與極端值套用、千分之一金額尺度、小組門檻，以及來源／收據竄改、禁止覆寫、部分失敗拒絕重凍結。另有 35 項政策一致性檢查及 15 份來源／方法綁定；這是契約驗證，不是未來資料建置器的逐筆驗收。

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_uci_rfm_contract -v
.\.venv\Scripts\python.exe -B scripts\freeze_uci_rfm_contract.py --verify
```

第二行只核既有來源與收據，不重跑測試；本輪沒有全專案回歸或真實資料列解析。合成檔案全部留在專案 Git 忽略的 `shop-mysql-runtime/verification/uci-rfm-contract-v1/synthetic/`。實際 test IDs 與結果見[凍結驗收](../reports/stage6/uci_rfm_v1_contract_acceptance.json)，未來完整建置所需的防前視案例見[契約](../docs/STAGE6_UCI_RFM_CONTRACT_V1.md)。

## UCI 官方資料盤點測試

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_uci_retail_ii -v
```

14 項合成測試實跑通過（unittest 0.030 秒）；涵蓋重複發票／明細的區別、跨表重複、缺顧客、取消／負數、零價、千分之一金額、時間衝突與窗口邊界。這不是全專案回歸。

另以標準庫 ZIP／XML 獨立解析原檔，逐格核對 1,067,371 列／8,538,968 格，215 項聚合／完整性檢查通過（164.717 秒）；[公開收據](../reports/stage6/uci_retail_ii_verification.json)綁定原檔、資料庫、盤點報告與驗證程式。`audit_uci_retail_ii.py --verify` 只核 bytes，不等同重新執行此獨立核對。見[結果與限制](../docs/STAGE6_UCI_RETAIL_II_INTAKE.md)。

## 第二快照資料盤點測試

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_temporal_data -q
.\.venv\Scripts\python.exe scripts\audit_rfm_temporal_data.py --verify
```

15 項合成測試通過，涵蓋截止邊界、晚送達舊單、未成熟／異常事件、同檔備份與未知完整性；另以 pandas 獨立核對 83 項真實聚合，不與單元測試數相加。驗證只盤點來源與時間／鍵覆蓋，沒有建第二個 RFM 或計跨期成績；見[盤點與資料缺口](../docs/STAGE6_RFM_TEMPORAL_DATA_INVENTORY.md)。

## G3 五種子同快照敏感度測試

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_g3 tests.test_run_rfm_g3 -q
```

26 項實測通過（7.618957 秒），0 error／failure／skip；涵蓋固定五種子與 80% 抽樣、完整參考分母、級數改變、90% 邊界、同值不拆、小組支援、tuple ARI／精確列聯表核對、退化、來源／分配竄改及失敗後禁止重播。來源與實際 test IDs 見 [G3 規格](../reports/stage6/rfm_g3_v2_specification.json)，真實結果及限制見 [G3 文件](../docs/STAGE6_RFM_G3_V2.md)。

## v2 RFM 重建與真實 G2 的測試

[新增測試](test_rebuild_rfm_v2.py)涵蓋獨立原始來源重算、五狀態、同總額但交換顧客、缺漏 ID、型別錯誤、來源變更、部分輸出、最後 guard 寫入失敗，以及完成後封鎖 builder／G1／G2 核心仍可只讀驗證。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rebuild_rfm_v2 -q
```

本輪準備實際執行原 builder、artifact、G1、G2、G2 outputs 加新測試六套，共 161 項通過（12.103883 秒），0 error／failure／skip；完整 test IDs 見 [v2 規格](../reports/stage6/rfm_rebuild_v2_specification.json)。這是合成／回歸測試；真實資料核對及 G2 結果另見 [v2 文件](../docs/STAGE6_RFM_REBUILD_V2.md)。

## 依修改範圍選擇檢查

| 範圍 | 測試內容／入口 |
| --- | --- |
| Stage 6真實G2執行準備 | [test_rfm_rule_candidate_sources.py](test_rfm_rule_candidate_sources.py)、[test_rfm_rule_candidate_outputs.py](test_rfm_rule_candidate_outputs.py)、[test_prepare_rfm_rule_candidate.py](test_prepare_rfm_rule_candidate.py)；合成完整同ID/G1反讀、候選四檔持久化及單次core／prepare-only守門 |
| Stage 6 G2規則候選 | [test_rfm_rule_candidate.py](test_rfm_rule_candidate.py)、[test_verify_rfm_rule_candidate.py](test_verify_rfm_rule_candidate.py)；合成ties／切點／級數／支援／同ID重現、完整G0與入口不可覆寫／source-bound收據 |
| Stage 6 RFM資料集、評估規格與描述 | `test_rfm_feasibility.py`、`test_rfm_dataset_*.py`、`test_build_rfm_dataset.py`、`test_rfm_evaluation_spec.py`、`test_rfm_description*.py`、`test_prepare_rfm_description.py`、`test_verify_rfm_description.py`；來源守門、同ID名冊、未知遮罩、精確描述與反讀 |
| Stage 5評論低評分預測 | `test_review_*.py`、`test_audit_review_*.py`、`test_diagnose_review_ablation.py`、`test_prepare_review_month_ablation.py`、`test_run_review_month_ablation.py`；H60標籤、train-only pipeline、選C、配對與只讀診斷 |
| 特徵與標記 | `test_delay_*features.py`、`test_delay_features.py`；訂單聚合、key、缺值與事件時鐘 |
| 訓練與時間切分 | `test_delay_*training.py`、`test_delay_*validation.py`；成熟答案、同月隔離與query群組 |
| 提醒政策與排名 | `test_delay_alert_policy.py`、`test_delay_calibration_policy.py`及排序測試；完整日分母、取整、ties與未知答案 |
| 實驗與選模 | 各輪`test_*selection.py`及comparison／experiment測試；固定候選、規格與歷史選擇 |
| 診斷與可重現性 | `test_diagnose_*.py`、audit測試；來源綁定、共同漏報身分及分格對帳 |
| 環境與資料庫 | [verify_environment.py](../scripts/verify_environment.py)；此項會讀本機設定與MySQL，與單元測試分開 |

以下各節依階段由新到舊排列，標「最新」者為該階段最近一輪。節內的「本輪」「前輪」沿用當輪撰寫時的用語，指該節對應的研究輪次；目前狀態以[專案進度](../docs/PROJECT_PROGRESS.md)為準。

## Stage 6：原 v1 G2 真實執行準備

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_rule_candidate_sources tests.test_rfm_rule_candidate_outputs tests.test_prepare_rfm_rule_candidate -q
```

三套新測試以合成資料驗來源／完整名冊與原G1交付、G2候選四檔及公開聚合反讀、來源變動／ID與分配矛盾／部分產物拒收、單次core與禁重播。候選ineligible仍保留完整active分配及失敗原因，不能當技術失敗重切；verify_completed禁止G1／G2 core重跑。

[prepare入口](../scripts/prepare_rfm_rule_candidate.py)只有--prepare，需實際source-bound收據及原私有證據，凍結[57來源規格](../reports/stage6/rfm_rule_candidate_execution_specification.json)與[準備查核](../reports/stage6/rfm_rule_candidate_execution_preflight.json)；測數／耗時以正式實測報告為準，不沿用或加總前輪60測。真實只核metadata／hash，未解析CSV、估切點／tuple、分群、訓練、做Dashboard或G3，也未重跑舊suite／全專案discover。Stage 4、5維持待資料，Stage 4每日10%與11／29／42／73／101五種子不變；詳見[準備契約](../docs/STAGE6_RFM_RULE_CANDIDATE_EXECUTION.md)。

## Stage 6：G2規則候選與資格守門

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_rule_candidate tests.test_verify_rfm_rule_candidate -q
```

新[純核心](../scripts/rfm_rule_candidate.py)的31項合成測試涵蓋原整數rank、ties不拆、重複／min／max切點、1–5級與R實際方向、支援99／100及20,000／20,001邊界、M>2^53與零元、空參考、五狀態／名冊／型別／守恆及不修改輸入。同ID對抗會拒收同箱大小卻交換ID、改切點、跨序一致仍拆ties或遺漏分配。另以125格各4人的案例核小joint cell單獨限制，不誤使每軸已達支援的G2失敗。

[合成驗證入口](../scripts/verify_rfm_rule_candidate.py)首次--verify-synthetic實跑上述兩套新測試與四組獨立預期案例，核完整49來源與既有G1證據，再固定[實作規格](../reports/stage6/rfm_rule_candidate_implementation_specification.json)及[實測報告](../reports/stage6/rfm_rule_candidate_verification.json)；兩套測數、耗時與完整test IDs以報告為準。重入只驗現有來源、報告語義及收據bytes，不重跑測試或覆寫；一般unittest命令不建立正式verification收據。

本輪未解析真實CSV、估真實切點、產生真實tuple、分群、訓練或做Dashboard，G3未實作／執行，也未重跑舊suite或全專案discover。Stage 4、5待資料，Stage 4每日10%與11／29／42／73／101五種子不變；詳見[實作與限制](../docs/STAGE6_RFM_RULE_CANDIDATE_IMPLEMENTATION.md)。

## Stage 6：真實描述交付驗收

該輪不修改凍結程式／測試，不重跑合成suite或全專案discover；沿用當時58項source-bound實測receipt。一次真實execute的core恰好1次，完成後以禁止core的verify_completed及獨立名冊稽核驗收。93,234顧客／99,421訂單、776,807格名冊與244個聚合scalar（含45個binary64）反讀一致；這些是實際資料交付核對，不加總為單元測試數、模型效能或未知資料成績。詳見[真實結果與驗收](../docs/STAGE6_RFM_DESCRIPTION_RESULTS.md)。

## Stage 6：真實描述執行串接驗證

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_description_sources tests.test_rfm_description_outputs tests.test_prepare_rfm_description -q
```

58項全過（18.236869秒）：sources20／outputs21／runner17，驗獨立顧客及全部T前名冊、逐單proof、五狀態／母體外單、canonical JSON／CSV／float bits、完整41來源／receipt與四檔/public反讀；synthetic E2E單core、來源變動／輸出變更／public失敗停止及禁重播均通過。沒有讀真實CSV、產真實名冊／描述或模型fit；舊46／32／130測與全專案discover未重跑或加總。詳見[準備文件](../docs/STAGE6_RFM_DESCRIPTION_EXECUTION.md)及[實測準備報告](../reports/stage6/rfm_description_execution_preflight.json)。

## Stage 6：只讀描述與資格守門

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_description tests.test_verify_rfm_description -q
```

本輪core26＋入口20共46項全過（15.635905秒），核五狀態同ID、原欄型別／ledger／遮罩守恆、精確rank／ties、2^53以上金額、IQR退化／半整數與等號界、全零／空集合、log、不突變、33來源／receipt及失敗停止。另7組獨立手算與7項資格反例通過，不與單元測試加總；原130／32項、全專案discover與真實個體反讀未重跑。詳見[實作驗收](../docs/STAGE6_RFM_DESCRIPTION_IMPLEMENTATION.md)及[合成報告](../reports/stage6/rfm_description_pipeline_verification.json)，沒有真實描述或分群效果。

## Stage 6：RFM評估契約驗證

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_evaluation_spec -q
```

本輪只驗規格與metadata守門：完整27來源、opaque CSV不可解析、原guard／manifest／獨立收據、型別與少綁／改bytes／不同輸出拒收及前後變動停止。測試與metadata實測數見[凍結文件](../docs/STAGE6_RFM_EVALUATION_SPEC.md)；未實作或測試真實分位數／分箱演算法、分群或模型，原130項及個體反讀是前輪紀錄，未重跑。

## Stage 6：RFM builder與反讀驗收

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_feasibility tests.test_rfm_dataset_spec tests.test_rfm_dataset_builder tests.test_rfm_dataset_artifacts tests.test_build_rfm_dataset -q
```

130項全過、5.417821秒（原20＋23、新builder42＋artifact20＋入口25），只用合成fixture，核截止、未知／隔離與五狀態、精確R／分、來源守門、整包不可覆寫、strict型別、偽摘要／排除理由拒收及唯讀驗收。另做真實資料3,082,480格反讀與獨立同ID每欄核對，不與單元測試數相加；未跑全專案discover、分群或模型fit。見[實作與驗收](../docs/STAGE6_RFM_DATASET_IMPLEMENTATION.md)及[實際報告](../reports/stage6/rfm_dataset_build_acceptance.json)。

## Stage 6：RFM資料集契約

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_feasibility tests.test_rfm_dataset_spec -q
```

新23項契約測試＋原盤點20項共43項全過、0.012秒。核完整歷史母體、窗口端點、已知時鐘矛盾隔離、可缺核准、未知商品不刪活動、混合／零活動狀態、來源異動與int64保守溢位前置條件；無builder或模型fit。正式聚合與獨立母體／隔離／金額／狀態對帳另列，未執行個體RFM反讀、分群或全專案discover，詳見[資料集規格](../docs/STAGE6_RFM_DATASET_SPEC.md)。

## Stage 6：RFM輸入盤點

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_feasibility -q
```

20項合成測試全過、0.012秒，涵蓋顧客鍵、明細／付款獨立彙總、精確到分、未知／非法與負金額、缺流、T邊界與晚送達、不修改輸入及不輸出個體RFM。另59項正式聚合／候選比較通過，來源及候選由獨立CSV／Decimal與pandas計算核對；不加總成單元測試數。沒有執行個體RFM、分群、模型測試、全專案discover或業務成效評估，詳見[Stage 6文件](../docs/STAGE6_RFM_FEASIBILITY.md)。

## Stage 5：模型適用範圍文件（最新）

[四欄／三欄模型卡](../docs/STAGE5_MODEL_APPLICABILITY.md)只核對原聚合報告的逐月／macro AP、C、分母與固定門檻混淆數，並查文件連結／JSON格式與既有凍結資產保存。未讀逐筆分數重算指標，未新增或重跑單元／模型測試、訓練、資料集或新資料驗收；這次文件查核不算新效能或未知測試。

## Stage 5：新時間窗交接文件

[交接清單與範本](../docs/templates/review_window_handoff/README.md)只做文件／格式查核：嚴格JSON解析、五個月完整區間及H60日曆界線、15個check_id與三關卡對應、所有實測null及pending_data、Markdown本機連結，另核既有程式／報告及私有證據未改。沒有新增或重跑單元測試、模型、原始資料稽核或真實交接驗收；範本所列案例是未來待執行義務，不能計為通過測試或新資料成績。

## Stage 5：後續時間窗盤點

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_validation_windows tests.test_audit_review_validation_windows -q
```

核心16＋來源／守門12共28項全過、1.477秒，0fit。核原C嚴格邊界、全月H60規劃截止、空月份、重複角色ID去重、metadata不可夾帶review_score／y、缺核准不可補購買日、最大回答時間不能當watermark、Git用途紀錄及來源異動／發布停止。檔案fixture依既有Windows tempfile ACL限制在允許專案.runtime的環境完成，未放寬斷言或跳過。

另618項正式獨立盤點、6.270秒及95項用途核對、0.026秒分列，核25個月、五個待資料時間窗、14個commit及用途限制。原30份私有證據不變；0新評分／y／訓練／效能，不重跑舊模型或全專案discover。見[時間窗文件](../docs/STAGE5_REVIEW_VALIDATION_WINDOWS.md)及[驗證](../reports/stage5/review_validation_window_verification.json)。

## Stage 5：成熟先驗與時間漂移稽核

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_mature_prior_audit tests.test_audit_review_mature_prior -q
```

核心19＋來源／守門10共29項全過、1.290秒，0fit。核H60恰60天、早答未成熟、品質狀態覆蓋、未知不填0、近期成熟窗口／月份與時齡邊界、query改動不影響先驗、跨fit不回填，以及來源異動／缺檔／發布停止。檔案fixture依既有Windows tempfile ACL限制，在允許專案.runtime存取的環境執行，未放寬斷言或跳過。

獨立7,134項正式比較、4.850秒另列，核原核准名冊與12角色289,973列、先驗／覆蓋／窗口與跨fit轉換；原27份私有證據不變。不讀分數值、係數，不fit／預測／校準／更新參數，也不重跑全專案或舊模型測試。詳見[文件](../docs/STAGE5_REVIEW_MATURE_PRIOR_AUDIT.md)與[驗證](../reports/stage5/review_mature_prior_verification.json)。

## Stage 5：雙臂只讀診斷

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_ablation_diagnostics tests.test_diagnose_review_ablation -q
```

核心16＋來源／守門12共28項全過、0.740秒，沒有fit。手算核對反向排序、平均rank平手、canonical名次、全未知null、全月損失分母及等待邊界；來源測試核payload／parent／guard異動、缺檔、失敗收據、未知檔與發布後來源異動撤回。首次沙箱有19個暫存ACL setup／cleanup錯誤，相同測試於允許的檔案環境全過，未放寬斷言或跳過。

正式資料另10,389項獨立比較、4.917秒，核18組機率、12組排名、六組支援及固定切片；不合併為單元測試數。診斷0fit／transform／predict／選C，原24份私有證據不變。見[診斷文件](../docs/STAGE5_REVIEW_ABLATION_DIAGNOSTICS.md)及[驗證報告](../reports/stage5/review_ablation_diagnostic_verification.json)。未重跑舊模型測試或全專案discover。

## Stage 5：真實消融交付驗收

本輪沒有修改凍結程式或重跑合成測試。一次真實執行實際完成9次內層＋3次外層fit，另以只讀程式核對完整角色、每臂18區塊108,744列的ID／truth、選C、指標與私有manifest。這是實際產物驗收，與下列前輪74項合成測試分列；詳見[實驗文件](../docs/STAGE5_REVIEW_MONTH_ABLATION_RESULTS.md)及[聚合驗收](../reports/stage5/review_month_ablation_training_acceptance.json)。

## Stage 5：三欄正式入口與私有writer

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_run_review_month_ablation tests.test_review_month_ablation_training tests.test_review_month_ablation_artifacts -q
```

入口20＋訓練控制32＋writer22共74項全過，沒有失敗、錯誤、跳過或預期失敗。正式合成驗證階段165.964秒（不含此前來源載入，含測試及發布）。實際sklearn fit共37次且均32維：三個完整試跑各9＋3次，另1次測預測失敗收據；其他分支使用替身。涵蓋獨立選C、七欄query遮罩、未知列、fit時鐘與支援、完整18區塊配對、來源變動、產物／公開結果接受後被改動、精確反讀、失敗回撤及禁止重播。真實fit與新效能均0。

正式版本與測試名單見[合成報告](../reports/stage5/review_month_ablation_dispatcher_verification.json)，整合CLI另需原本機來源先`--specification-only`再`--verify-synthetic`；操作及界線見[入口驗收](../docs/STAGE5_REVIEW_MONTH_ABLATION_DISPATCHER.md)。該輪沒有重跑全專案discover，下列歷史紀錄各自保留。現有training_v1已占用，整合CLI不可當成發布後驗收重播。

## Stage 5：三欄執行準備與配對守門

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_month_ablation_sources tests.test_review_month_ablation_pairing tests.test_prepare_review_month_ablation -q
```

來源18＋配對25＋準備CLI16共59項新測試全過，43.555秒，無失敗、錯誤或跳過。涵蓋來源／私有guard／實作證明改版拒收、完整角色與七欄遮罩、防禦性副本、18區塊完整同ID與truth、未知／機率、外層不同C、禁止模型／效能呼叫、輸出占用／碰撞／越界、全部預檢、晚期變動回滾及同版重跑。全部只用合成metadata／分數或暫存檔，沒有fit、predict或效能計算。

正式來源／分數獨立核對另有1,304,928個metadata欄值一致，以及21項私有I/O對抗案例；不加總成單元測試或效能結果。詳見[執行準備文件](../docs/STAGE5_REVIEW_MONTH_ABLATION_EXECUTION.md)。本輪沒有重跑下列合成fit組或全專案discover，前輪紀錄保持分列。

## Stage 5：三欄實作與洩漏驗證

```powershell
.\.venv\Scripts\python.exe scripts\verify_review_month_ablation_pipeline.py
.\.venv\Scripts\python.exe -m unittest tests.test_review_dataset_contract tests.test_review_baseline_contract tests.test_review_month_ablation_contract -q
```

第一行跑新三欄43項＋原四欄32項共75項，全部通過；正式測試4.065秒、CLI共5.815秒。涵蓋32維、保留欄位／前處理與44維對照一致、月份不變性、train-only scaler、未知排除、H60／fit邊界、完整名冊、query未來標籤隔離、候選／外層獨立、失敗清除及機率檢查。會實際fit合成模型，不讀Olist資料、不計效能。

第二行23＋20＋14共57項契約回歸全過，4.555秒。首次受限環境有6項暫存目錄ACL錯誤；允許相同本機資源後原樣重跑通過，沒有跳過或改舊斷言。兩組合計132項，沒有執行全專案discover。另194項跨3個fold內／外層獨立合成檢查及31項CLI對抗案例通過，與單元測試分列。詳見[實作文件](../docs/STAGE5_REVIEW_MONTH_ABLATION_IMPLEMENTATION.md)及[正式報告](../reports/stage5/review_month_ablation_pipeline_verification.json)。

## Stage 5：月份消融契約

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_month_ablation_contract -q
```

[月份消融規格](../docs/STAGE5_REVIEW_MONTH_ABLATION_SPEC.md)新增14項契約測試全過、0.500秒。驗精確五處月份結構差異、32維、其他改動拒收、三欄獨立選C與null配對、來源／私有guard、完整輸出預檢、同版重跑及晚期來源失配撤回；不匯入sklearn，不建X或fit。發布前修正與已載入套件的測試隔離，另以模組替身重驗3個受影響測試，全過、0.200秒，沒有實際匯入sklearn。另有508項獨立來源／逐ID角色比較通過，未解析分數CSV或計效能。

本輪只跑此新測試組；上方discover包含舊合成fit，本輪未執行，不宣稱全專案回歸。

## Stage 5：凍結分數只讀診斷

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_score_diagnostics tests.test_review_score_diagnostic_runner -q
```

[凍結分數診斷](../docs/STAGE5_REVIEW_SCORE_DIAGNOSTICS.md)新增核心32項及runner 11項，共43項全過、5.011秒。只用合成資料驗分母／未知、固定bins、linear分位數、ddof=0、四欄支援、完整metadata、來源／規格拒收與只讀發布；模型呼叫負例在執行前被拒絕，沒有實際fit／transform／predict。本輪沒有重跑下列會fit合成模型的舊測試，亦不宣稱全專案回歸。

獨立合成10情境15,400葉節點、來源對抗36項與正式聚合8,218比較另記私有證明，不加總為單元測試數。正式對帳直接讀原凍結分數、membership及事件時鐘，不重播模型。原42份凍結資產bytes不變。

## Stage 5：離線基線入口

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_sources tests.test_review_baseline_training -q
```

來源測試只用合成metadata與暫存來源，核對祖先SHA／私有guard、完整同ID角色、未知與七個未來欄遮罩及防禦性副本。訓練入口測試核對手算AP／ROC／Brier／logloss／0.5邊界、未知不計分、單類及無known的null、三C平手、每次fresh fit與錯誤停止、全query出分、float64帳本反讀、輸出碰撞及重跑拒收。測試不讀真實Olist來fit；實際真實基線由獨立CLI執行，結果見實驗文件。

本輪新增來源12項＋訓練／評估21項全過；連同既有四組，下面六組共120項全過、19.581秒，無失敗、錯誤或跳過。另有來源65項、手算指標300項及正式分數／fit診斷1,096項獨立比較；後者沒有重fit或重預測，不加總成單元測試數。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_prediction_feasibility tests.test_review_dataset_contract tests.test_review_baseline_contract tests.test_review_baseline_pipeline tests.test_review_baseline_sources tests.test_review_baseline_training -q
```

## Stage 5：builder／pipeline洩漏測試

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_pipeline -q
.\.venv\Scripts\python.exe scripts\verify_review_pipeline.py
```

本組以手算四欄／44維、未知訓練outlier、query未來標籤改動與極端值、時間嚴格邊界、獨立名冊共同刪單、各fit隔離及失敗後狀態核對實際資料流。固定類別、ddof=0、零變異、schema／值域、參數、收斂警告及機率異常都有拒收或一致性檢查。合成係數／機率只用來驗正確性，不算AP等模型表現；詳見[實作與驗證](../docs/STAGE5_REVIEW_PIPELINE_IMPLEMENTATION.md)。

該輪32項全過（正式CLI測試1.855秒）；合併下列Stage 5既有三組，87項全過、5.821秒。另有300項獨立合成檢查及六種CLI拒收案例；這些不加總成單元測試或真實資料成績。沒有重跑全專案867項模型測試。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_prediction_feasibility tests.test_review_dataset_contract tests.test_review_baseline_contract tests.test_review_baseline_pipeline -q
```

前輪Stage 5最小基線契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_baseline_contract -q
```

前輪20項全過、0.285秒，涵蓋固定政策、角色／事件截止、未知、來源／私有guard、輸出預檢及API AST。該輪不建立X、前處理或模型，不執行選參或指標；嚴格JSON沿用舊資料集I/O helper。原始metadata獨立對帳見[基線規格](../docs/STAGE5_REVIEW_BASELINE_SPEC.md)，不與本輪合成fit混為真實訓練成績。

前輪Stage 5凍結資料集與逐fit資格：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_dataset_contract -q
```

本組23項涵蓋H端點／成熟嚴格邊界、早答不改挑、同分平手、未知不補0、未來／超H壞評論不得污染、不可定位回答的靜態品質隔離、每個I／F重建、內層最近完整成熟月、完整候選及重疊、nullable CSV逐值反讀、來源SHA／嚴格JSON／不可覆寫、Git忽略路徑與公私輸出全部預檢、實際規格bytes綁定。測試均無模型擬合；原始資料的獨立逐值對帳另見[資料集文件](../docs/STAGE5_REVIEW_DATASET_SPEC.md)。

前輪Stage 5可行性盤點邊界檢查：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_review_prediction_feasibility -q
```

本組12項涵蓋無評論未知、先首答後查t、早答不改挑晚答、平手／壞時鐘／鍵隔離、score範圍、取消單保留、May截止、回答嚴格早於fit、來源SHA變更及報告不可覆寫。用合成資料核對盤點規則，沒有擬合模型或產生效能成績。

前輪全量日來源盤點的守門檢查：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_audit_daily_data_contract -q
```

本組8項涵蓋嚴格JSON、來源SHA變更、不可覆寫、核准日界、缺失／無效／逆序時間、ID唯一，以及同N錯ID／時鐘／版本與跨組名冊不同。測試只檢查盤點程式的拒收與對帳行為；不代表上游全量日資料或未來live batch契約已通過。

前輪單日離線交付契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_delay_daily_delivery_acceptance tests.test_accept_frozen_daily_delivery -q
```

本組42項（核心25＋CLI／來源／輸出17）涵蓋完整20組、同N錯ID、漏單／重複、時間與版本、finite分數、同分ID升序、9／10／19張的向下取整、未知答案不預濾、原旗標／舊邊界、來源SHA、Git忽略路徑、整批拒覆寫與CSV逐值反讀。合成資料沒有擬合模型，不是新增實驗效能。

來源盤點的時鐘與證據契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_audit_event_source_availability -q
```

本組15項涵蓋截止日、無效／逆序時間、承諾日精度、最終status不能證明取得時間、未知捕獲率保留缺失、schema／時區變更需重驗、ID唯一、來源SHA改變、不可覆寫報告、DB逐表對帳及私有證據路徑不公開。

前輪的歷史母體、固定條件比例與重現契約：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_delay_history_representativeness tests.test_delay_representation_profiles tests.test_audit_completed_history_representativeness -q
```

本組共37項，涵蓋核准／送達／交運邊界、未知key與零歷史、承諾無效、原窗口橋接、原欄還原、組成權重、五種子、稀疏與三精度篩查，以及完整phase／screen的JSON roundtrip重現。

前一輪的成熟訊號分層比較亦可獨立執行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_delay_conditional_mature_signals tests.test_diagnose_conditional_mature_signals -q
```

此組包含31項合成測試，涵蓋組成反轉、漏報筆數與配對數權重、承諾精度、稀疏覆蓋、五種子身分、ties及跨月篩查。測試中的小型模型擬合是合成資料檢查，不是重新訓練研究模型或取得新回測成績。

## 其他檢查

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\verify_environment.py
```

第二個指令需具備本機MySQL與連線設定；`--execute-notebooks`只執行01–03的副本，詳見[Notebook導覽](../notebooks/README.md)。原始資料／模型／逐筆分數的獨立重算不是單元測試，應依各輪文件執行並將紀錄留在`.runtime/`。

Windows受限執行環境若封鎖暫存目錄或本機執行緒管線，完整測試可能因權限失敗；應在允許這些本機資源的環境以同一程式重跑，不以跳過測試或改動斷言取代。純文件整理則檢查連結、Notebook結構、來源與報告SHA，不需要重跑訓練入口。
