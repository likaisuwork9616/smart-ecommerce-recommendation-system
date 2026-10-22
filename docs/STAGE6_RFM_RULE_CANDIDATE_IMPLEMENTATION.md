# Stage 6：G2規則候選與資格守門合成驗收

本輪依[原凍結G2規格](STAGE6_RFM_EVALUATION_SPEC.md)新增規則候選與資格守門，先用合成資料驗收。既有[真實G1描述與驗收](STAGE6_RFM_DESCRIPTION_RESULTS.md)保留；**本輪沒有解析真實CSV、估真實切點、產生真實序數／tuple、分群、訓練或Dashboard**。G3五種子敏感度未實作／執行，Stage 4、5維持待資料，Stage 4每日10%與11／29／42／73／101五種子不變。

本輪[來源規格](../reports/stage6/rfm_rule_candidate_implementation_specification.json)與[實測合成驗收](../reports/stage6/rfm_rule_candidate_verification.json)獨立新增，不改原方法程式、機器規格、41來源、描述與建置報告或私有證據。舊policy的current_run及各文件「本輪」均保留當時狀態；最新G2狀態以本文件為準。

## 實作與資格守門

[純函式](../scripts/rfm_rule_candidate.py) `evaluate_rule_candidate(dataset, evaluation_spec, expected_customer_ids=..., g1_accepted=True)`只接收記憶體中的完整customers／orders／summary與原評估規格。它回傳可公開的`aggregate`，以及只留私有記憶體的`assignments_by_id`；沒有真實執行dispatcher或個體輸出writer。

| 檢查 | 實作行為與失敗處置 |
| --- | --- |
| G1前置 | 必須明確傳入bool True；這只是呼叫端的已審閱聲明，不能證明來源真實性或取代真實執行授權 |
| 完整G0 | 沿用原schema、精確型別、五狀態／遮罩、數值範圍、逐單ledger與金額守恆驗證；缺ID、重複ID、旗標矛盾、假M、來源規格不符即停止 |
| 完整名冊 | 獨立完整expected_customer_ids必填；不能從遭縮減的同一份資料再造名冊冒充獨立證據。未來真實接線仍須來源、整包guard及完整同ID驗收 |
| 候選母體 | 僅active_complete；合法M=0保留。乾淨零活動及三種不完整狀態保留分流計數，不補R或M、不混入切點 |
| 精確切點 | R整數秒、F整數訂單、M商品整數分；P20／40／60／80取1-based第`(n*p+99)//100`個觀測原值，不插值、不先轉float |
| ties與退化 | 相同原值同箱；切點去重、保留小於max的min、移除所有≥max切點。常數軸保留單箱／無分離力，不事後手工切點 |
| 邊界與方向 | x≤cut入較低數值箱；有效級數k=保留切點數+1。R序數=k+1−箱號，F／M=箱號，明列實際k及每箱N |
| G2級數／支援 | 各軸2–5級、無空箱、每箱N≥`max(100,(n+199)//200)`；不足時保留候選與所有失敗原因，G2=ineligible，不改門檻重切 |
| 同ID重現 | 原輸入序、反序及Generator(PCG64(42))排列皆比較完整切點／軸摘要與每ID的數值箱、序數、tuple，要求100%一致；缺分配、拆ties或順序依賴即停止 |
| 中性tuple | 只列實際觀測tuple與N，不加總價值分、不命名商業群組；小cell標insufficient_group_support、不自動合併，單獨不使G2失敗 |
| 空參考 | 不估切點，各軸null、無個體分配，G1／G2=not_evaluable_empty_reference；不能把G0自洽當成候選通過 |

同ID排列使用seed42只為驗證列序不影響結果，沒有進行80%顧客重抽樣。Joint單群／每ID一群僅揭露退化與G3未評估；G3的五種子級數一致、agreement、ARI及退化守門仍另行實作。G2通過不代表G3、跨時間穩定或業務用途通過。

## 本輪實測與解讀

正式source-bound驗證共60項測試全過：核心31項、入口29項，10.156750秒，0 error／failure／skip；另執行四組合成案例，不加總為測試數。以下全部是程式實際執行並核對獨立預期值的**合成案例**，不是Olist切點、客群或模型成績。完整test IDs見[合成驗收報告](../reports/stage6/rfm_rule_candidate_verification.json)。

| 合成驗收 | 實際結果 |
| --- | --- |
| 平衡500人 | 三軸各5級、每箱100人，G2通過；剛好達支援下限 |
| F常數500人 | F的切點全部移除、僅1級／500人，G2不合格；不假稱五等份 |
| 每箱99人 | 495人三軸均有5級，但各箱99<100，G2不合格；有效級數足夠仍須核支援量 |
| 125個小joint cells | 500人各軸支援100、G2通過；125格各4人全部標支援不足，不宣稱個別cell穩定 |
| 精度、級數與門檻 | 測試獨立手算rank、重複／max／min切點、1–5級、R按實際k反向、M>2^53與零元；n=20,000支援100、20,001支援101 |
| 同ID對抗 | 同大小卻交換ID分配、改切點、跨序一致仍拆ties或遺漏分配皆拒收；不是只比箱人數 |
| 資格與不突變 | 五狀態、獨立名冊、型別／範圍／旗標／守恆、空參考與G1前置均驗；純core禁檔案存取時通過、原輸入保持不變 |
| 驗證入口 | 完整49來源、既有G1證據與輸出bytes、測試收據、前後來源及不可覆寫守門；不重播原builder、個體反讀或描述入口 |

正式執行額外封鎖CSV reader／DictReader、原read_tables／read_inputs、execute_prepared／verify_completed、describe_dataset及bundle read／verify入口仍通過；因此真實來源只核metadata／binary hash。原508份追蹤檔中僅7份文件／屬性更新，其餘501份及322份既有私有檔bytes不變，原RFM與Stage 4／5證據保留。

出版檢查通過78份Markdown、1,259個本機連結及126份嚴格JSON，49來源相符，新增公開內容不含私有bundle digest；收據留`.runtime/stage6_rfm_rule_candidate_publication_qa.json`。再次執行合成驗證入口已通過既有收據驗收，沒有重跑測試或覆寫產物。

既有真實F=1占97.52%、IQR=0是前輪G1描述，足以提醒大量ties風險，但**本輪沒有估真實P20／40／60／80或判定真實G2結果**。合成案例不能轉成真實通過率、未知資料成績或行銷效果。

## 操作與交付

沒有原始資料的clone仍可執行兩套合成測試，所有資料由fixture建立：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_rule_candidate tests.test_verify_rfm_rule_candidate -q
```

在有原私有來源與G1驗收證據的工作目錄，以下命令首次實際執行兩套測試及四組合成案例，前後核同版來源與既有G1證據，再固定產物：

```powershell
.\.venv\Scripts\python.exe scripts\verify_rfm_rule_candidate.py --verify-synthetic
```

入口只支援此參數，沒有真實執行、CSV路徑或覆寫開關。真實來源只讀binary hash與JSON metadata，沒有重跑個體反讀；原42項metadata及完成描述四檔bytes沿用不代表本輪重新驗了逐筆值。49來源=原41＋原描述執行spec／preflight／公開描述／驗收4份＋本輪core／runner／兩套tests 4份。

再次執行只驗現有source-bound收據、完整固定報告語義與檔案bytes，不重跑測試或改耗時。缺私有檔、不同來源、部分產物或報告／guard同步改寫scope皆停止，不刪檔重凍結。一般單元測試命令不會建立正式verification收據。

| 交付位置 | 內容 |
| --- | --- |
| reports/stage6/rfm_rule_candidate_implementation_specification.json | 49來源與本輪synthetic-only範圍，不含私有bundle digest |
| reports/stage6/rfm_rule_candidate_verification.json | 實測test IDs／分套測數／耗時、四組合成結果、既有metadata沿用與真實G2未執行聲明 |
| .runtime/stage6_rfm_rule_candidate_implementation_v1/ | 私有input_guard與實測log，Git忽略；沒有真實個體tuple檔 |

下一步先決定是否準備一次真實G2執行；若進行，須另凍結完整來源／G1接受、同ID名冊、輸出、反讀及失敗停止流程，再決定執行。本輪不進行真實切點或G3，不因合成通過解封Stage 4／5、模型、營運或Dashboard。原入庫／版本、退款／結算、跨時間與業務適用仍待資料。
