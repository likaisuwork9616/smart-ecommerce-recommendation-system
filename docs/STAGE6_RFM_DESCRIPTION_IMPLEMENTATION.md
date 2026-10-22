# Stage 6：只讀RFM描述與資格守門實作

後續已完成[真實描述來源、完整名冊、輸出及反讀的串接凍結](STAGE6_RFM_DESCRIPTION_EXECUTION.md)，並依凍結入口完成一次[真實描述與交付驗收](STAGE6_RFM_DESCRIPTION_RESULTS.md)。下文保留前輪純core實作與46測紀錄；當時「尚未接線」的狀態未回寫，原code／JSON／guard bytes保留。

已依[凍結規格](STAGE6_RFM_EVALUATION_SPEC.md)完成純描述器與資格守門，**本輪只用合成資料計算描述**。兩套46項測試、獨立手算及反例驗收通過；真實來源僅核metadata／binary hash，沒有解析真實CSV、計真實分布、估分群切點、打分／分群、重抽樣、訓練或Dashboard。Stage 4、5維持待資料，Stage 4每日10%與11／29／42／73／101五種子不變。

[實作規格](../reports/stage6/rfm_description_implementation_specification.json)綁定33份來源；[合成驗收報告](../reports/stage6/rfm_description_pipeline_verification.json)分開記實際合成測試與既有資料集metadata沿用。原評估規格、方法程式、資料集、所有舊報告／guard維持bytes；原policy的current_run=false是前輪凍結時的執行紀錄，未改寫成這輪成果。

## 實作範圍

| 層次 | 已實作行為 |
| --- | --- |
| [純描述器](../scripts/rfm_description.py) | `describe_dataset(dataset, evaluation_spec, expected_customer_ids=...)`只收記憶體中的customers／orders／summary與原評估規格，回傳聚合；不開檔、不寫檔，不回傳ID／個體RFM |
| 資格守門 | 原16＋16欄有序schema、精確bool／int64／finite float64／nullable、時間／ledger／RFM／摘要語義核對通過後，才選完整活躍列計統計 |
| [驗證入口](../scripts/verify_rfm_description.py) | 僅`--verify-synthetic`；核原27來源、42項metadata及原eval audit，加本輪程式／測試綁定至33來源，再讀已實際執行的兩套測試收據。入口不呼叫描述器、不讀真實CSV內容 |
| 寫入範圍 | 僅本輪implementation specification、合成verification聚合及私有input guard；不同既有bytes、部分產物、少綁來源或前後來源變動即停止，不重凍結放行 |
| 尚未接線 | 沒有真實描述CLI／輸出流程，亦未實作分群切點、bin／score／tuple、敏感度或模型。真實描述執行仍需另行決定 |

純函式的G0只驗證**提供的資料**在同ID、型別、資格與守恆上自洽；來源真實性由呼叫端的完整來源／bundle bytes守門負責。額外傳入獨立完整expected_customer_ids，可攔截連ledger／summary都一起縮掉顧客的情形；不能從已被縮減的同一份list再造名冊當獨立證據。實際接線時必須核同版來源前後bytes、完整ID與個體反讀，不能拿純函式回傳passed取代來源驗收。

## 同ID分流與金額守恆

輸入列順序可以不同：先驗欄序／型別，再以新list canonical排序核對，不修改來源list、row或summary。顧客ID／訂單ID不能重複；歷史合格ledger重建的全集必須精確等於顧客全集，外部名冊有提供時也須完整一致。

| 狀態 | 描述器行為 |
| --- | --- |
| active_complete | 唯一進三軸數值摘要的集合；R必須在(0,365天]、F≥1、M為非負整數分，合法M=0保留 |
| inactive_complete | 保留狀態／null計數；R三欄null、F=0、M=0，不補R或混入完整數值描述 |
| active_money_unknown | 保留母體、品質與原R／F合格子集；M=null，只報狀態／null計數，不做部分R／F分布 |
| active_with_quarantine | 保留合格子集R／F，M=null，不因另有合格單就列可用或回填部分M |
| inactive_with_quarantine | R=null、F=0、M=null，不能誤列乾淨零活動或進切點母體 |

五種狀態互斥、加總回完整同ID全集；聯合驗state、rfm_usable、monetary_complete及品質計數，不只信單旗標。原ledger／摘要會重建F、R與遮罩規則；金額保持商品／運費／付款分流，另核已知T前金額子集的int64保守前提。

完整活躍M合計須等於未遮罩顧客M合計（乾淨零活動貢獻0）；原合格窗口已知商品額＝完整顧客M＋遮罩顧客已知合格子集的守恆仍需成立。最後這個子集只對帳，不回填M、不當成未知0，也不進數值描述。

## 精確描述與退化處理

| 項目 | 已實作口徑 |
| --- | --- |
| 三軸與單位 | R用整數秒排序／判界，顯示可÷86,400為天；F為合格窗口distinct訂單；M為名目BRL商品整數分毛額，不含運費／付款／退款 |
| 原尺度摘要 | N、null／distinct數、min／max、精確sum、mean分子／分母與float顯示值；P0／1／5／25／50／75／95／99／100 |
| 精確rank與ties | p=0取最小值，其餘1-based第`(n*p+99)//100`個；排序與取值保持Python int，不插值、不拆ties。即使M>2^53也不先轉float |
| IQR／Bowley | IQR=Q75−Q25；Bowley保留整數分子／分母及float值。IQR=0時Bowley、fence與flag counts回null，附退化原因，不當作零離群 |
| 半整數fence | 用`2*x < 2*Q25−3*IQR`或`2*x > 2*Q75＋3*IQR`判界；等號不flag。只回聚合旗標數，removed_n固定0，沒有刪除／截尾／clip |
| 單次／零元 | F=1、M=0的N與比例，分母只用完整活躍N；不按低頻／零元刪人 |
| Q99金額尾端 | M≥Q99包含所有ties，列實際N／占比與尾額／總M；總M=0時share回null及zero_total_M原因，不誤稱恰好前1% |
| log1p視圖 | 固定R秒÷86,400、F、M分÷100後log1p，只算N／null／min／max／mean與相同百分位；有限值檢查，不另作fence／切點或穩定證據 |
| 空完整活躍集合 | N=0，其餘raw／log摘要null並附empty_reference；G0資料可自洽，但G1為not_evaluable_empty_reference，不補值、估切點或宣稱可用 |

P25／P75／Q99僅用於描述、IQR及尾端診斷；**沒有估P20／40／60／80分群切點**。來源RFM、單位、S／T、所有列均不改。mean／log為有限float64顯示，商品主值、sum、raw分位數及判界仍保持整數精度。

## 本輪合成驗收與實際發現

| 類別 | 本輪實際結果 |
| --- | --- |
| 描述器測試 | 26項全過：五狀態、同ID／排序、不突變、1秒R、精確rank、ties、M>2^53、mean分子／分母、IQR=0／半整數／等號界、M=0、空集合、log與守恆 |
| 入口測試 | 20項全過：完整33來源、原eval audit、receipt型別／測數／來源、缺件／少綁／改bytes、部分或不同產物拒收、前後變動、沒有真實描述開關或CSV路徑參數 |
| 本輪兩套合計 | 46項、15.635905秒，0 error／failure／skip；沒有重跑前輪130／32項或全專案discover |
| 獨立手算 | 7組oracle通過，預期值來自手算／Fraction，包含ties尾額、半整數與等號界、全零、2^53以上、IQR=0仍有尾端及empty；不以production統計helper當答案 |
| 獨立資格反例 | 五狀態分流／遮罩守恆、輸入不變及無ID輸出通過；7項漏ID／重複ID／部分M／錯誤usable／守恆／外部名冊偽造均拒收。不與46項單元測試相加 |
| 真實來源沿用 | 原42項metadata與本輪33來源通過；正式驗證時禁止CSV解析、舊builder、個體反讀及新描述器呼叫仍成功，證明本輪未執行真實描述 |

例如純合成M=[1,1,2,9,9]時，Q99=9、尾端N=2／5、尾額18／22；描述器沒有把ties硬拆成一人。另一合成向量的上fence=3.5時只flag 4；等號fence=6時6不flag、7才flag。這些是演算法驗收案例，**不是Olist資料分布、群組品質或業務效果**。

私有測試收據／log留`.runtime/stage6_rfm_description_unit.*`，獨立oracle／路由反例收據留`.runtime/stage6_rfm_description_independent/`。公開verification只含合成測數、來源metadata與執行範圍，不含實際顧客ID、個體RFM、私有CSV或receipt digest。

## 操作與產物

合成測試可在專案根目錄用`.venv`執行，無需真實CSV、MySQL或模型：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_description tests.test_verify_rfm_description -q
```

在已有原資料與私有證據、且保留本輪實際source-bound測試收據的工作目錄，可驗證本輪實作產物：

```powershell
.\.venv\Scripts\python.exe scripts\verify_rfm_description.py --verify-synthetic
```

這個命令不重跑suite或描述器，而是核對兩套實測receipt的modules、各測數／合計、0 error／failure／skip、成功旗標、有限耗時與完整33來源，並核產物bytes。收據變更或少件即停止，不能補假成功／改來源放行；缺原私有資料的clone仍可跑上列合成測試，但不能偽造本機guard重建驗收。

| 位置 | 本輪交付 |
| --- | --- |
| reports/stage6/rfm_description_implementation_specification.json | 原27來源＋原評估spec／audit兩份＋新四份程式／測試，共33份 |
| reports/stage6/rfm_description_pipeline_verification.json | 46項合成測試、原metadata沿用及未執行真實描述的scope |
| .runtime/stage6_rfm_description_implementation_v1/input_guard.json | 綁規格、測試receipt及原私有provenance，Git忽略 |

未建立`.runtime/stage6_rfm_evaluation_v1/`，沒有新增真實個體／描述輸出、Notebook、分群模型或Dashboard。原資料集及Stage 4／5來源均保留。

出版檢查通過75份Markdown、1,170個本機連結、120份嚴格JSON及33來源綁定；除本輪文件與屬性更新外，479份原追蹤檔及56份原私有證據bytes不變。個體ID、私有bundle及receipt digest未進新公開檔；收據留`.runtime/stage6_rfm_description_publication_qa.json`。

## 限制與下一步

合成驗收證明宣告的數值與資格規則在測試範圍內正確，尚未驗收真實分布、尾端支援或描述結果。G1回傳ready_for_aggregate_review只表示摘要可供覆核，不能解讀為分群、穩定性或營運通過；G2／G3始終not_executed。

下一步先凍結並串接真實只讀描述的來源守門、完整名冊、私有／公開聚合輸出及反讀驗收，再決定一次真實描述執行。仍不估切點、不分群或訓練；跨時間穩定性、原入庫／版本、退款／結算及上游完整性仍待資料，不能把快照毛額當淨消費或未來價值。
