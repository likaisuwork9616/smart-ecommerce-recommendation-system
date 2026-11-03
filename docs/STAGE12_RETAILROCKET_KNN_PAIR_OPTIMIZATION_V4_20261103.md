# Stage 12：V4 逐筆配對優化與恢復驗收

本步驟先改進精確計算，通過等價與故障恢復，再用同一組已凍結的 64 筆樣本作六對交替 AB／BA 工程比較。**不啟動全量，K1−C1 仍無正式結論，預留測試 locked。** 證據見[39 項驗收](../reports/stage12/retailrocket_session_knn_v4_pair_acceptance_20261103.json)與[固定樣本成本](../reports/stage12/retailrocket_session_knn_v4_pair_cost_20261103.json)。

## 改了什麼

| 元件 | 改進與不變條件 |
| --- | --- |
| [V4 精確 SQL 排名](../scripts/retailrocket_session_knn_sql_v4.py) | 完整正重疊 pool 依 numeric key 作原 SHA；Jaccard 約分分組、任意精度整數交叉乘排序，保留 500 鄰居、原 intersection／union 與完整邊界 ties |
| 投票與 top10 | 任意精度整數公分母加總，僅輸出時還原精確分子／分母；超過 4,096 位元回到 Fraction。沒有 float、SQL INT64 截斷、抽樣、ANN 或漏投票 |
| [指標快取](../scripts/retailrocket_session_knn_checks_v4.py) | 驗輸入後依 hit ranks／完整 target count 快取 frozen terms 產物；保留 50 位 Decimal／binary64，回傳 dict 副本；數值環境或自訂型別走原函式 |
| 嚴格比較 | 保留原 JSON exact。候選遞迴比較在合成 benchmark 較慢，未啟用；bool／int／float、signed zero、Unicode 與非有限值拒收語意不改 |
| [配對與計時](../scripts/retailrocket_session_knn_pair_v4.py) | current／next／targets／四臂原值／delta／Decimal 檢查不省略。chunk fsync／SHA／manifest 仍執行，另列 commit 時間；科學 ledger payload 與基準 bytes 相同 |

V1／V2／V3 與原主要產物保持凍結。V4 工程 verifier 最多接受 64 個凍結樣本；完整 global／bootstrap 接口要求明確人工 fixture，沒有真實全量／final／test CLI。

## 驗收與實測

39 項測試為 SQL 11、checks 20、配對／恢復 8，全部通過。涵蓋 V1／V2／V3 完整巢狀差分、499／500／501、等價未約分比率、超大 numeric IDs、unknown／self／future／fallback、公分母超限回退、Decimal 字串與原 K1 binary delta，以及來源／已提交內容竄改拒收。

故障注入涵蓋 query 深處、append 前後、payload 半寫、fsync 後 manifest 前、manifest 後 latest 前、全域／bootstrap／candidate 前。另真的以 `os._exit(9)` 在第三筆 query 與 candidate commit 後退出，再用新程序恢復；只採認已提交鏈，最終人工結果與不中斷一致。候選不是成功收據，只有獨立 supervisor 觀察正常退出後才接受。

工程比較固定相同 DB、catalog、64 probes、來源、checkpoint 規則與 V4 計時框架；基準在同框架呼叫 frozen 排名／檢查／指標，V4 使用新計算。兩個暖機、六對 AB／BA，共 896 次所選 query 工程驗算，14 次完整 ledger 科學內容 bytes 全部相同。初末來源再核一致，整個有界比較用時 372.672 秒、正常退出碼 0。

| 同一 64 筆的中位數 | 基準 | V4 | 解讀 |
| --- | ---: | ---: | --- |
| 逐筆配對，含當輪 chunk commit | 6.019434 秒 | 3.156145 秒 | 約降低 47.6% |
| 逐筆部分，扣除另列 commit | 5.928910 秒 | 3.072384 秒 | 約降低 48.2% |
| 純核對部分 | 5.693156 秒 | 2.889468 秒 | 排名、指標、來源核對及 exact 均計入 |
| chunk commit | 0.069617 秒 | 0.076143 秒 | 未下降，完整保留；不是省略 checkpoint |
| 每次含 setup／來源綁定等的整段 | 15.208470 秒 | 12.080870 秒 | 不是把逐筆加速當作整輪加速 |

這是本次同框架、同資料的觀測，不與前輪不同時間的 V3 秒數直接相比，沒有工時上界或統計信賴區間。零重疊合成案例曾略慢，不能保證每個 query 都較快。

每次仍採 64 筆或 120 秒安全邊界，EOF 另 flush。`ceil(166897/64)=2608` 只代表數量條件下的最少 chunks；時間、EOF、停止與恢復可能增加提交，不能當成完整提交次數。V3 將 chunk 邊界費納入某筆 query 的歷史情境保留，不覆寫；V4 分項列帳並未刪費。

## 下一個步驟

通過本步驟並提交後，才執行真實已保存 payload 的原 bytes 統計、七路 source-only 索引／前綴定位，以及已驗 64 筆子集的真正程序中斷恢復量測。未驗的 166,897 筆原主要輸出不能冒充完整 verified ledger；來源定位也不能充當 query 驗收。

全量保持關閉，完整 `T_plan` 留空。每日 10% 延遲提醒與 Dashboard 暫緩不變。
