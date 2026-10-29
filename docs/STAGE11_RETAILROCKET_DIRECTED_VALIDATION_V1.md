# Stage 11：D1／C1／P0 一次真實 validation v1

依[已凍結入口](../reports/stage11/retailrocket_directed_v1_validation_specification.json)，完成一次 D1 train 擬合、原 166,897 筆 validation／62,235 訪客完整三臂比較、2,000 次主要 D1−C1 bootstrap，以及獨立重建與逐筆反讀。P0／C1 沒有重訓或重排名，預留測試仍 locked、0 筆出分；沒有 final refit、追加 fit 或新調參。

主要結果是 **D1 的 NDCG 低於 C1，差 −0.006600944，95% 訪客成組區間全為負**。本輪不支持以 D1 取代 C1；D1 高於 P0 的差異僅作預先約定的描述，不另產生推論區間。所有數字取自[正式報告](../reports/stage11/retailrocket_directed_v1_validation.json)、[獨立驗收](../reports/stage11/retailrocket_directed_v1_validation_acceptance.json)及其資源／guard。這是已曝光的回溯開發窗，不能作未知測試、前瞻或上線成績。

## 主結果與完整分母

| 同一 validation 的指標 | P0 | C1 | D1 | D1−C1 | D1−P0（描述） |
| --- | ---: | ---: | ---: | ---: | ---: |
| query-macro NDCG@10 | 0.001681829 | 0.106400714 | 0.099799771 | −0.006600944 | 0.098117941 |
| Recall@10 | 0.004179224 | 0.180151531 | 0.167483538 | −0.012667993 | 0.163304313 |
| HitRate@10 | 0.004182220 | 0.180182987 | 0.167522484 | −0.012660503 | 0.163340264 |
| MRR@10 | 0.000943565 | 0.083664114 | 0.078904014 | −0.004760100 | 0.077960449 |
| visitor-macro NDCG@10 | 0.001622526 | 0.113072891 | 0.104230872 | −0.008842019 | 0.102608347 |
| 商品 coverage@10 | 0.000044893 | 0.199982941 | 0.198990815 | −0.000992126 | 0.198945922 |

上表均使用 0–1 比例，差為絕對差。商品聯集為 P0 10、C1 44,547、D1 44,326，共同候選聯集為 **222,754**；coverage 差不是逐查詢平均。三臂保留完全相同的 query key／順序、因果候選與完整 target 分母：166,952 次 target 中 161,264 次因果可達，不可達項沒有刪除。

唯一主要推論為全查詢平均 D1−C1 NDCG：−0.00660094375412807，95% percentile interval 為 **[−0.007511893, −0.005716747]**。2,000 次訪客成組抽樣全部獨立重播；這個已曝光開發窗的主要比較偏向 C1，不能據此外推未知時間或宣稱因果效果。D1−P0、其他指標與所有切片均只描述，沒有第二組區間、p 值或事後效能門檻。

Bootstrap 固定 NumPy 2.5.4／PCG64／seed 42／linear quantile，以數值 ID 排列 62,235 個匿名訪客，保留每個抽中訪客的全部查詢並按抽中查詢數加權。新抽樣的 SHA、RNG 前後狀態與分母逐次對上原 C1 bootstrap；**D1−C1 delta 與區間另行計算**，沒有挪用舊 C1−P0 數值。

全 target 可達的 161,211 筆條件查詢另列：P0 NDCG=0.001741148、C1=0.110153526、D1=0.103319763；D1−C1=−0.006833763，D1−P0=0.101578615。這是條件描述，不能替換全 166,897 筆主結果。

## 模型與成本對帳

Train 使用 UTC [2015-05-04, 2015-08-01) 的原始 baskets。兩端必須同 session、原 index 差 1、時間嚴格增加且相隔不超過 30 分鐘；跨 basket 笛卡兒積排除 self-edge，同一方向每 session 只計一次。沒有橋接被移除的 basket、未來 session 長度篩選、剪枝或抽樣。

| Train 實測項目 | 數量 |
| --- | ---: |
| Sessions／singleton sessions | 1,180,256／998,801 |
| Baskets／basket 商品 memberships | 1,823,018／1,823,388 |
| 不同 session 商品 memberships | 1,587,436 |
| 共享 C1 正支援商品 | 198,946 |
| 合格原始相鄰 basket 對 | 642,762 |
| 原始有向發射次數 | 493,669 |
| 每 session 去重後的有向邊量總和 | 479,231 |
| 全域不同有向邊數 | 370,325 |

母體、相鄰量、原始發射與 session 去重總量均與事前 train-only 成本盤點相符。479,231 是各 session 不同有向邊量加總，不能與全域不同邊 370,325 混稱。D1 fit ID 為 `4c428ecdaf79a3dc6e7a352216c824a069baf2debf5f5a585fb23e6a359169ef`。

S 完整重用原 C1，`support.csv` 與原 C1 的 SHA 相同；singleton 與沒有 D 邊商品不消失。獨立 oracle 另重建 S 核等，並核 D／C1 計數上界及守恆。Validation 期間模型統計不更新；查詢完整歷史與 C1 相同。完整 outgoing 鄰居以 Fraction 精確加總，其餘因果候選以原 P0 count／數值 ID 順序補位；沒有 D 邊的商品仍保留原正 P0 次數，不刪已看商品或冷商品。

## 回退、出入邊與冷商品

D1 完全回退 **18,556／166,897 筆（11.118235%）**。互斥原因如下；缺少的 `no_positive_causal_neighbor` 類別實際為 0，沒有把它合併至其他組。

| 互斥診斷 | 查詢數 |
| --- | ---: |
| positive_evidence | 148,341 |
| no_shared_supported_seed | 6,981 |
| no_outgoing_seed | 11,575 |
| no_positive_causal_neighbor | 0 |

原 C1 完全回退 16,319 筆，全部也在 D1 完全回退；C1 回退但 D1 有正證據為 0。D1 額外回退 2,237 筆。此為預定診斷，沒有因回退增加而刪查詢或改方法，也不能單獨解釋全部 NDCG 差異。

共同 S 無支援 seed 的查詢為 6,981；無 D1 outgoing seed 為 18,556。兩者定義不同，不能用 outgoing keys 重新定義共同 train 支援。正證據候選數為 0／1–9／至少 10 的查詢分別為 18,556／46,493／101,848；完整歷史、seed 與零分補位分布保存在正式報告。

Target 的 D1 incoming 支援另列：全部有 incoming 139,935 筆、部分有 5 筆、全部無 26,957 筆。這個新診斷保持完整分母，不能取代原 shared-S 的 `target_model` 切片；無 outgoing 的商品仍可能有 incoming 邊。

原冷目標 `target_model/all_zero` 仍有 **11,943 查詢／5,769 訪客**，P0／C1／D1 的 NDCG、Recall、HitRate、MRR 都是 0，冷商品缺口未解決。這不等於 coverage 為 0：該切片 D1 推薦 14,171 個不同商品，coverage=0.063617264。冷 target 共有 11,946 次，其中 6,258 次當下可達；「無 train 支援」不等於全部不可達或從未出現。冷目標、完全回退與 incoming 支援是不同診斷，不能相加或當成相同查詢群。

## 全部預定切片與小組限制

| 預定切片 | query | visitor | P0 NDCG | C1 NDCG | D1 NDCG | D1−C1 | 支援 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| visitor_history/seen | 32,648 | 6,298 | 0.001819638 | 0.084332291 | 0.079354427 | −0.004977864 | sufficient_query_count |
| visitor_history/new | 134,249 | 55,937 | 0.001648316 | 0.111767532 | 0.104771872 | −0.006995660 | sufficient_query_count |
| current_basket/single | 166,841 | 62,231 | 0.001682394 | 0.106363486 | 0.099782611 | −0.006580875 | sufficient_query_count |
| current_basket/multiple | 56 | 43 | 0.000000000 | 0.217314767 | 0.150924020 | −0.066390747 | descriptive_only |
| target_basket/single | 166,844 | 62,230 | 0.001681054 | 0.106386517 | 0.099793133 | −0.006593385 | sufficient_query_count |
| target_basket/multiple | 53 | 41 | 0.004120895 | 0.151093643 | 0.120696481 | −0.030397161 | descriptive_only |
| train_activity/0 | 134,300 | 55,959 | 0.001647690 | 0.111772173 | 0.104776155 | −0.006996018 | sufficient_query_count |
| train_activity/1 | 6,523 | 2,485 | 0.001677314 | 0.107720837 | 0.105578593 | −0.002142244 | sufficient_query_count |
| train_activity/2-5 | 6,009 | 2,185 | 0.003727135 | 0.116649122 | 0.107526256 | −0.009122866 | sufficient_query_count |
| train_activity/6+ | 20,065 | 1,606 | 0.001299281 | 0.066949892 | 0.062299040 | −0.004650852 | sufficient_query_count |
| target_model/all_positive | 154,951 | 59,411 | 0.001811490 | 0.114601217 | 0.107491371 | −0.007109846 | sufficient_query_count |
| target_model/mixed | 3 | 2 | 0.000000000 | 0.128950936 | 0.128950936 | 0.000000000 | descriptive_only |
| target_model/all_zero | 11,943 | 5,769 | 0.000000000 | 0.000000000 | 0.000000000 | 0.000000000 | sufficient_query_count |

支援門檻為 1,669 查詢，另報訪客數；同一訪客可能出現在不同切片，跨組訪客數不可直接相加。Current／target 多商品 56／53、mixed 3 只能描述，沒有切片區間、挑組、合併或刪除。原 train 多商品 199／192、locked test 33／29、Olist 25、UCI 87／83 小組不足也保留。

## 獨立驗收與資源

獨立 SQL 以原索引相鄰 join 與 `DISTINCT(session,i,j)` 重建有向計數，另核完整共享 S、C1 上界、逐 session lineage 及 query prefix。三臂 key／順序、原控制 binary64、全部歷史／target／候選、精確有理分數與順序、每筆指標／差值及所有彙總均核對；不是抽樣驗收。

| 完整反讀產物 | 記錄數 |
| --- | ---: |
| `support.csv` | 198,946 |
| `edges.csv` | 370,325 |
| `train_sessions.jsonl` | 1,180,256 |
| `queries.jsonl` | 166,897 |
| `bootstrap.jsonl` | 2,000 |

真實排名 oracle 為「all SQL outgoing neighbors plus exact zero-score complement proof」：枚舉全部有證據的 outgoing 鄰居，其餘候選分數精確為零，再驗完整 P0 順序補集。它保留完整候選，沒有 top-L／負樣本／ANN 近似。計數、ID、歷史、有理數與順序精確相等；指標浮點絕對／相對容差 1e-12。全部 JSON 巢狀值均驗收；收據的 `top_level_cells` 只計頂層欄位，不能當成巢狀 scalar 總格數。

整輪資源監控回報 **2,377.547000 秒**，抽查 RSS 峰值 **1.331944 GiB**，取樣 4,598 次；正式 result 列出的 10 個執行檔案共 1,321,411,812 bytes（約 1.230661 GiB）。8 GiB RSS／20 GiB 執行目錄／6 小時上限及磁碟剩餘 8 GiB／系統可用記憶體 4 GiB 下限未觸發。這是合作式檢查與抽查峰值，不是 OS 瞬時硬限制；檔案加總也不是完整目錄瞬時峰值。

新 output guard 固定 220 份來源及 13 份輸出；完成狀態、manifest 與獨立驗收皆已建立，沒有 failure。完成後 `--verify` 已通過，沒有重算研究。另將本輪開始前保存的 28 份 P0／C1 模型產物、release／gate／ZIP 逐檔核 SHA，全部與原狀相同。共享 S 與既有 P0／C1 控制來源均按凍結 bytes 核對；原模型、排名、指標與舊 bootstrap 沒有重產生或覆寫。

## 保存、適用與下一步

模型、逐 session／edge／query、bootstrap、oracle SQLite、started／資源／manifest／guard 在 Git 忽略的 `shop-mysql-runtime/retailrocket_directed_paired_v1/`；本輪原狀、日誌與交付核對在 `shop-mysql-runtime/verification/retailrocket-directed-validation-v1/`。所有檔案仍在 shop，原 P0／C1、UCI 與既有交付包不覆寫。

完成後只驗既有 bytes，不重播擬合或評估：

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_directed_v1.py --verify
```

完整執行重入只驗證；部分執行拒絕覆寫與重播。歷史規格／實作文件保留當輪「尚未執行」快照，以本頁及正式結果描述目前狀態。不要因負向結果追加 fit、改分母或回頭挑參數／小組。

下一步先整理 **D1／C1／P0 三臂研究交付、適用說明與證據保存**，保留 D1 低於 C1 的主要結果、冷商品與小組限制；本輪不支持替換 C1，也不進行新候選或最終選模。若後續另有研究問題，須先固定新方法與比較規格，不能把此 validation 再當未知資料。

P0／C1 validation 在 D1 選擇前已曝光；D1 同時改變方向與鄰近性，不能分別歸因，也不是標準 Markov 機率。匿名訪客不等於獨立真人，缺入庫／修訂／完整性、曝光／propensity及連續庫存證據，不能推論轉換、營收、營運或因果改善。來源 NC-SA 等條件及 Olist／UCI 舊限制保留。

預留測試繼續 locked；最終選模／refit／test 仍須另立規格、驗收與後續明確執行範圍，不能沿用 P0／C1 gate 或依任何區間自動解鎖。每日 10% 提醒不變，Dashboard 暫緩；全專案狀態見[進度表](PROJECT_PROGRESS.md)。
