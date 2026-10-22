# Stage 6：RFM builder與私有資料集驗收

後續已沿用本資料集凍結[描述／分群評估規格](STAGE6_RFM_EVALUATION_SPEC.md)，並完成一次[真實描述（G1）](STAGE6_RFM_DESCRIPTION_RESULTS.md)；真實切點與分群尚未執行，目前進度見[專案進度](PROJECT_PROGRESS.md)。下文保留前輪builder與一次真實資料集驗收紀錄，原程式／JSON／私有產物bytes不改，沒有重跑個體反讀或訓練。

已依[凍結契約](STAGE6_RFM_DATASET_SPEC.md)完成純builder、私有輸出與正式入口，先通過合成洩漏／反讀測試，再執行一次真實快照建置。本輪產生可核對的顧客R／F／M與完整T前逐單決策，沒有分群、模型fit、效能評估或Dashboard。Stage 4、5仍待資料，Stage 4每日10%與11／29／42／73／101五種子維持。

[實作規格](../reports/stage6/rfm_dataset_build_specification.json)綁定20份來源；[建置報告](../reports/stage6/rfm_dataset_build.json)列實際聚合結果，[驗收報告](../reports/stage6/rfm_dataset_build_acceptance.json)分列單元測試、真實反讀及獨立同ID核對。原契約、聚合支援報告與前輪程式bytes保留，裡面的「尚未builder」旗標描述當時狀態，未回寫成這輪成果。

## 實作與邊界

| 層次 | 工作與停止條件 |
| --- | --- |
| [純builder](../scripts/rfm_dataset_builder.py) | 只收四表原始字串與凍結規格；商品／運費／付款各自按單聚合，再依顧客鍵計RFM。不讀檔、不寫檔、不讀評論／模型分數 |
| [私有writer](../scripts/rfm_dataset_artifacts.py) | 精確16＋16欄、UTF-8、lowercase bool、nullable空cell、naive秒級timestamp、int64分與float64的17位有效數字；逐欄反讀，連R的binary64位元也核對 |
| [正式入口](../scripts/build_rfm_dataset.py) | 重建原完整12份契約綁定，再核本輪20份綁定；前後查來源bytes及凍結支援，任一不符即停止。不能刪掉來源清單項目繞過守門 |
| 整包寫入 | 預檢私有資料集／控制目錄及公開成功報告均不存在；先在新私有staging寫入、反讀通過才發布目錄。既有bundle即使bytes相同也拒絕重建；失敗staging保留作私有證據 |
| 語義與摘要 | 從逐單帳本重建顧客母體、R／F、M遮罩、五狀態、品質計數及可推導的聚合／金額守恆；時間與排除原因不得矛盾。原始明細品質及未來來源列數另由來源守門／獨立計算驗收 |
| 唯讀驗收 | `--verify`核原始來源bytes、私有三檔guard、型別／值及公開聚合；不重新讀取raw表內容建置、不呼叫builder、不寫檔 |

JSON拒絕重複key與非有限值，metadata亦用遞迴精確型別比較，`true`或`1.0`不可冒充整數`1`。顧客ID／訂單ID唯一且排序固定，缺資料不能縮母體、將未知補0、刪F或另改S／T。

逐單`approval_at`／`delivery_at`可保留解析後的≥T時間作**排除稽核證據**，不是核准當下可得特徵；顧客RFM只聚合凍結的窗口事件合格集合。購買≥T的20張來源單只記排除彙總，不進T前帳本或帶入未來顧客。

契約M.zero的「零」指空集合的補零政策：乾淨零活動列補M=0；合法非負商品price恰為0時，活躍完整顧客實測M也可為0。不能用`M>0`判定活躍／完整，不能把未知金額補成0；原凍結bytes不改，這個解讀在實作政策與合成案例明列。

## 實際資料集

S=2017-09-01 00:00:00、T=2018-09-01 00:00:00，[S,T)共365 elapsed days。數字取自真實建置及獨立驗收，屬資料集正確性，不是模型或營運效果。

| 項目 | 真實結果 |
| --- | ---: |
| 顧客母體／T前逐單決策 | 93,234／99,421列，各16欄 |
| 歷史事件合格／窗口合格訂單 | 96,350／74,088；顧客F合計74,088 |
| 活躍顧客／乾淨零活動顧客 | 72,125／21,109 |
| active_complete／rfm_usable=true | 72,124 |
| active_with_quarantine／M=null | 1；仍保留合格子集R／F |
| active_money_unknown／inactive_with_quarantine | 0／0；未知分支有合成案例，不能因本批0列刪政策 |
| inactive_complete | 21,109；R三欄null、F=0、M=0、rfm_usable=false |
| 時鐘異常隔離 | 歷史61單、窗口59單，按比較規則處理，沒有固定ID排除清單 |
| 窗口品質隔離 | 66單＝59核准矛盾＋7缺送達；其中1單連母體顧客，65單在母體外 |
| 窗口送達≥T | 另59單，視T前未完成，不能混作品質隔離 |

商品金額以整數分驗守恆：合格窗口訂單已知商品合計1,016,801,111分＝公開聚合的完整顧客M合計1,016,786,312分＋被遮罩顧客之已知合格子集14,799分。最後這14,799分只作對帳，該顧客M仍是null，不發布部分M。單位為名目BRL商品快照毛額，不含運費，也不是淨實收。

## 測試、反讀與獨立驗收

| 類別 | 本輪執行與範圍 |
| --- | --- |
| 合成與回歸 | 130項全過，5.417821秒：原盤點20＋原契約23＋builder42＋artifact20＋入口25；未跑全專案discover或模型測試 |
| 洩漏與未知 | S含／T不含、1秒R不取整、窗口外不借R、未來購買／送達隔離、缺核准非阻擋、商品未知不掉F、隔離遮罩M、五狀態與合法零元 |
| 反讀與失敗停止 | 型別／欄序／nullable／float64、重複或漏ID、母體／狀態／遮罩摘要偽造、排除原因與時間矛盾、整包覆寫、來源少綁／改bytes及失敗後不出成功報告 |
| 真實bundle | 寫入後全部3,082,480格反讀、schema、ID／順序、RFM語義及金額守恆通過；私有guard綁定CSV與manifest三檔 |
| 獨立同ID核對 | 另用未匯入production程式的pandas／Decimal計算原四CSV；兩份16欄資料全部3,082,480格相同，含nullable、bool／int與R的binary64位元。不是把單元測試數再加上格數 |

獨立腳本、參考CSV及比較收據在`.runtime/stage6_rfm_builder_independent/`；單元測試收據與log在`.runtime/stage6_rfm_builder_unit.*`。實際顧客／訂單ID、個體RFM、CSV digest、原始資料及guard都由Git忽略；公開只交付程式、規格、聚合報告與方法文件。

出版檢查通過73份Markdown、1,121個本機檔案連結、116份嚴格JSON及20份來源綁定；除本輪文件與屬性更新外，463份原追蹤檔及38份原私有證據bytes不變。收據留`.runtime/stage6_rfm_builder_publication_qa.json`，沒有把舊Stage 4／5成果改成本輪實驗。

## 操作與交付

有原始來源及私有證據的既有工作目錄，使用唯讀驗收：

```powershell
.\.venv\Scripts\python.exe scripts\build_rfm_dataset.py --verify
```

合成測試可獨立執行，不需要真實CSV、MySQL或模型：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_feasibility tests.test_rfm_dataset_spec tests.test_rfm_dataset_builder tests.test_rfm_dataset_artifacts tests.test_build_rfm_dataset -q
```

本輪一次執行順序為`--specification-only`→`--build`→獨立比對→`--verify`。現有`.runtime/stage6_rfm_dataset_v1/`已占用，不能為看結果刪檔重播；全新重現環境也必須先取得原四CSV、既有規格／來源及相同版本，否則停止，不能重建來源證據來放行。

| 私有位置 | 成果 |
| --- | --- |
| `.runtime/stage6_rfm_dataset_v1/customers.csv` | 93,234列顧客RFM與狀態 |
| `.runtime/stage6_rfm_dataset_v1/order_decisions.csv` | 99,421列T前來源單及排除／品質對帳 |
| `.runtime/stage6_rfm_dataset_v1/manifest.json` | 凍結規格、來源、schema、列數、私有digest、聚合及反讀收據 |
| `.runtime/stage6_rfm_dataset_build_v1/output_guard.json` | 綁定本輪實作規格與整個三檔bundle，唯讀驗收不得覆寫 |

Git clone不會取得私有資料集；缺CSV／guard不是要求重跑Stage 4／5訓練或Notebook的理由。本輪沒有新增或執行Notebook。

## 限制與下一步

通過的是**來源可見最終快照的離線研究資料集**。匿名鍵不證明自然人，歷史下界不等於完整生命週期；最終狀態、價格與映射沒有原入庫／修訂，亦缺退款、結算及上游完整性／日結證據，不能交付營運as-of、淨消費或行銷名單。分群品質與未來行為沒有在本輪驗證。

下一步建議先凍結RFM描述／分群的評估規格：以72,124位完整活躍顧客作可用數值集合，21,109位乾淨零活動及1位隔離混合顧客分開處理；先約定金額／頻次偏態、離群值、RFM單位與切點、群組穩定性和時間可比較性的檢查，再決定是否實作分群。尚未承諾群數、群界或商業效果；正式營運與Stage 4、5仍等新資料。
