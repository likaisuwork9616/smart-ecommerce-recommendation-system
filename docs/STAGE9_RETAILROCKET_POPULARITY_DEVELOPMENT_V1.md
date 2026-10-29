# Stage 9：P0一次真實train擬合與完整validation結果

2026-10-28 依已凍結的[開發入口](STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md)完成一次真實P0 train擬合，以及全部 **166,897筆validation query／62,235個匿名訪客鍵**的完整候選評估。主 **NDCG@10=0.001681829，HitRate@10=0.418222%**。這是已觀察的回溯開發驗證，沒有未知／前瞻、預留測試或營運效果成績。

一次主fit與一次獨立SQL count audit分開記錄；四份CSV共 **699,637列／5,738,596格**及全部聚合完整反讀一致。**0訓練期排名、0最終重估、0預留測試排名，test保持locked**。

正式[開發結果](../reports/stage9/retailrocket_popularity_v1_development.json)、[獨立逐query反讀收據](../reports/stage9/retailrocket_popularity_v1_development_acceptance.json)、[凍結入口規格](../reports/stage9/retailrocket_popularity_v1_development_specification.json)是本輪數字來源。原[執行規格v1](contracts/retailrocket_popularity_execution_v1.json)、[資料契約v1](contracts/retailrocket_recommendation_v1.json)、程式、資料、合成與過去報告均不改寫；其中當時的未執行狀態保留為歷史快照，現況以本輪新收據為準。

## 真正使用的統計與分母

| 項目 | 本輪實際結果 |
| --- | ---: |
| 主train fit／獨立count audit | 1／1，後者是驗收oracle，沒有第二候選或選模 |
| 統計窗口 | 2015-05-04 ≤ t < 2015-08-01 UTC |
| 合格事件來源檔列數 | 2,754,113 |
| 真正計入的canonical train view | 1,823,388 |
| 其他角色／train非view排除 | 869,049／61,676 |
| 正次數fit商品 | 198,946 |
| validation窗口 | 2015-08-01 ≤ t < 2015-09-01 UTC |
| 主query／不同匿名訪客 | 166,897／62,235 |
| 完整target商品出現次數 | 166,952 |
| 當時可達target出現次數 | 161,264 |
| 全部target均可達的query | 161,211 |
| 推薦商品聯集／候選商品聯集 | 10／222,754 |

每筆canonical train view加1，保留無標註後續的session末次view；暖身、validation、reserved_test、加購與交易不混入fit。只估一次主統計，沒有加權、時間衰減、活動／機器人刪除或超參數搜尋。

所有validation query完整保留。未見訪客使用同一全站排序；沒有訓練次數的候選仍是零分，已看商品不排除。每次候選只取first_view_ms嚴格早於query的商品，不注入target、不做負採樣。完整target仍在Recall及IDCG分母，沒有以不可達、模型未見或小組不足刪query。

## 主要與條件成績

| 指標 | 主結果：166,897 query | 條件結果：161,211 query |
| --- | ---: | ---: |
| query-macro NDCG@10 | 0.001681829 | 0.001741148 |
| query-macro Recall@10 | 0.417922% | 0.432663% |
| query-macro HitRate@10 | 0.418222% | 0.432973% |
| query-macro MRR@10 | 0.000943565 | 0.000976845 |
| visitor-macro NDCG@10 | 0.001622526 | 0.001666849 |
| 商品覆蓋@10 | 0.004489% | 0.004489% |

條件結果只取完整target皆在候選中的query，涉及60,588訪客及161,264次target，不能取代主結果。主／條件數字差異來自評估母體不同，不是另一次擬合或改良模型。

NDCG與MRR以0–1數值列示；Recall、HitRate及商品覆蓋以百分比列示。Recall是逐query比例的平均，不能直接當作全部target的微平均。visitor-macro先在每個來源訪客內平均，再等權平均訪客，與query-macro的權重不同。

本P0在全部validation中只推薦同樣10個商品，商品聯集覆蓋為10／222,754=0.004489%。候選聯集分母是本窗口所有合格query的事前目錄聯集，不是全期商品數。獨立oracle證明全部198,946個正次數fit商品在validation起點前出現，且多於10個，因此同一熱門前10名與每個query的完整候選排序精確等價；每個query的候選數與輸出仍逐一核對。

這個結果提供固定熱門基準，沒有個人化證據；目前也沒有另一推薦方法的同名冊比較，不能宣稱改善。規格沒有設定效能通過門檻，驗收通過只證明來源、分母、實作與輸出一致，不代表達到營運品質要求。

## 切片、小組支援與冷啟動限制

本窗query門檻固定 **1,669**。下表是描述性結果，達query數門檻也不代表獨立訪客數足夠、跨期穩定或有因果效果。

| 切片 | query | 不同匿名訪客 | query-macro NDCG@10 | 支援判定 |
| --- | ---: | ---: | ---: | --- |
| fit前來源訪客鍵：已見 | 32,648 | 6,298 | 0.001819638 | 達query數門檻 |
| fit前來源訪客鍵：未見 | 134,249 | 55,937 | 0.001648316 | 達query數門檻 |
| 當前瀏覽集合：單商品 | 166,841 | 62,231 | 0.001682394 | 達query數門檻 |
| 當前瀏覽集合：多商品 | 56 | 43 | 0.000000000 | 不足，只描述 |
| 目標瀏覽集合：單商品 | 166,844 | 62,230 | 0.001681054 | 達query數門檻 |
| 目標瀏覽集合：多商品 | 53 | 41 | 0.004120895 | 不足，只描述 |
| 原train view活動：0 | 134,300 | 55,959 | 0.001647690 | 達query數門檻 |
| 原train view活動：1 | 6,523 | 2,485 | 0.001677314 | 達query數門檻 |
| 原train view活動：2-5 | 6,009 | 2,185 | 0.003727135 | 達query數門檻 |
| 原train view活動：6+ | 20,065 | 1,606 | 0.001299281 | 達query數門檻 |
| 目標在fit表的覆蓋：全部正次數 | 154,951 | 59,411 | 0.001811490 | 達query數門檻 |
| 目標在fit表的覆蓋：正／零次數混合 | 3 | 2 | 0.000000000 | 不足，只描述 |
| 目標在fit表的覆蓋：全部零次數 | 11,943 | 5,769 | 0.000000000 | 達query數門檻 |

本輪不足的小組：當前瀏覽集合的多商品（56 query／43訪客）、目標瀏覽集合的多商品（53 query／41訪客）、目標在fit表的覆蓋的正／零次數混合（3 query／2訪客）。0命中不能解讀為該客群或商品沒有價值，也不作事後合併／刪除或調參依據。預留測試原有的多商品33／29 query低於921門檻仍保留，沒有新增測試分數；原train的199／192小組也不因本輪完成而解除限制。

全部零fit次數的target群共11,943 query，本P0未命中。這與正次數商品完全占據top10的固定熱門規則相符，不能推得所有新商品不值得推薦。模型覆蓋依真正fit count表判定，不拿builder的歷史prefix旗標冒充已有模型統計。

「未見訪客」是fit截止前未觀察到的匿名來源鍵，不是已驗證的新顧客；無train view群也可包含暖身或非view歷史。各query在同訪客內相依，沒有CI或顯著性結論，不能因某個活動切片分數較高就挑改動。

## 獨立反讀、檔案及操作

主路徑與獨立oracle都直接讀已驗收CSV；後者另用SQL重算次數，使用獨立完整排序／全候選等價證明、50位Decimal對數與Fraction比例重算指標。ID、次數、列表及名冊精確比對，浮點abs／rel各1e-12；每份CSV讀到EOF，不只抽查。

| 私有CSV | 完整資料列 | 比對格數 |
| --- | ---: | ---: |
| `item_counts.csv` | 198,946 | 397,892 |
| `ranked_queries.csv` | 166,897 | 1,335,176 |
| `query_metrics.csv` | 166,897 | 2,503,455 |
| `query_slices.csv` | 166,897 | 1,502,073 |

總計699,637列／5,738,596格，四CSV共75,535,679 bytes；fit audit與所有主／條件／訪客／切片聚合也一致。正式開發與反讀流程150.842秒，這不包含啟動前來源SHA核對，不是效能基準。

本輪沿用已凍結的54項合成驗收，沒有重跑、改碼、重估候選或安裝套件。來源及環境由61份原凍結描述與入口／驗收收據繼續綁定；一次主fit及一次audit在新正式scope記錄，不能把audit叫第二次模型實驗。

逐item次數、逐query排名／分數／指標／切片、fit audit、aggregate、started marker、manifest及output_guard都在`shop-mysql-runtime/retailrocket_popularity_v1/development/`；本輪日誌、原狀與交付檢查在`shop-mysql-runtime/verification/retailrocket-popularity-development-v1/`，全部在shop內並由Git忽略。公開只保存程式／規格／聚合與SHA，沒有原始資料、逐query ID或本機模型。

完成後只用只讀查核：

```powershell
.\.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
```

`--verify`核已保存來源／輸出／收據bytes，不重算fit或指標；完整語意反讀已在本輪完成。不要刪guard或部分產物重播；程式及來源變更須另立版本。`--run-development`本輪已成功執行一次，現有完整namespace重入只做verify。

初始測試鎖定快照保持原SHA，`final_refit/`、`reserved_test/`及`test_usage.jsonl`都不存在；訓練期排名、最終重估及測試排名均為0。開發驗收完成不會自動開測試，原八項啟用條件仍有效。

## 下一步

建議保存P0 v1為固定對照，先制定**共現推薦與P0的配對比較規格**：沿用資料v1、同一validation query／target、完整候選及分母，先固定歷史可用範圍、計數單位、回退與比較方式，再實作／評估。這是下一個研究建議，本輪沒有新增共現候選或擬合；新算法另立執行／比較規格，不修改這次已凍結P0，且不保證新方法會改善。

預留回溯測試繼續locked。若之後要評估最終方案，仍需先凍結驗證決策、最終重估／測試實作與使用journal，再依原條件啟用，不能反覆用預留測試選模型。現有標籤曾供資料驗收，這些validation分數現在也已觀察；都不能當未接觸新來源或前瞻成績。

回溯事件時間缺入庫／修訂／完整水位、匿名身分、無曝光／propensity與連續可售庫存、非商業授權等限制保留；沒有營收、轉換或因果結論。Stage 6 UCI v1封存及UCI 87／83、Olist 25個小組不足不變，Stage 4／5仍待資料，延遲每日10%固定，Dashboard暫緩。全專案現況見[進度表](PROJECT_PROGRESS.md)。
