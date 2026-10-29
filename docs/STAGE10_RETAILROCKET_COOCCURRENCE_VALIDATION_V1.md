# Stage 10：C1／P0 一次真實配對 validation v1

依[已凍結入口](../reports/stage10/retailrocket_cooccurrence_v1_validation_specification.json)，完成一次 C1 train 擬合、原 166,897 筆 validation／62,235 訪客完整配對、2,000 次 bootstrap，並通過獨立重建及逐筆反讀。P0 沒有重訓或重排名，預留測試仍 locked、0 筆出分；沒有 final refit 或新調參。

本頁數字只取自[正式報告](../reports/stage10/retailrocket_cooccurrence_v1_validation.json)與[獨立驗收](../reports/stage10/retailrocket_cooccurrence_v1_validation_acceptance.json)。這是已檢視的回溯開發比較，不能作未知測試或上線成績。

## 主結果與固定分母

| 同一 validation 的指標 | P0 | C1 | C1−P0 |
|---|---:|---:|---:|
| query-macro NDCG@10 | 0.001681829 | 0.106400714 | 0.104718885 |
| Recall@10 | 0.004179224 | 0.180151531 | 0.175972306 |
| HitRate@10 | 0.004182220 | 0.180182987 | 0.176000767 |
| MRR@10 | 0.000943565 | 0.083664114 | 0.082720549 |
| visitor-macro NDCG@10 | 0.001622526 | 0.113072891 | 0.111450365 |
| 商品 coverage@10 | 0.000044893 | 0.199982941 | 0.199938048 |

上表 Recall／HitRate／coverage 均使用 0–1 比例，差為絕對差。商品聯集為 P0 10、C1 44,547，共同候選聯集 222,754；coverage 差不是逐查詢平均。完整 target 166,952 次均留在 Recall／IDCG 分母，其中 161,264 次因果可達。

主要 NDCG 差 0.104718885；95% 訪客成組 percentile interval 為 [0.101004915, 0.108446582]，2,000 次皆獨立重播。區間在這個已曝光的開發窗內為正；不能據此外推未知時間、獨立真人、營運或因果改善。

這是 62,235 個匿名來源訪客的成組抽樣，保留每訪客全部查詢及 query-macro 權重；固定 NumPy 2.5.4／PCG64／seed 42／linear quantile。沒有小組或次指標區間、p 值或事後性能門檻，負向／跨零結果也按固定規格保留。

全 target 可達的 161,211 筆條件查詢另列：P0 NDCG=0.001741148、C1=0.110153526，配對差=0.108412377。它不能替換全 166,897 筆的主結果。

## 模型、回退與完整候選

Train 使用 UTC [2015-05-04,2015-08-01) 的 view session 集合，1,180,256 sessions，其中 singleton 998,801；198,946 個正支援商品、1,954,889 個不同無序 pair。總 pair 發射 2,292,165，與事前成本盤點相符；model fit ID 為 `55d4fd748fb7ffe22b13476bed2ed16e83d23dd2d655b9fb02b41087dabe0dee`。

重複瀏覽每 session 只算一次，singleton 保留，跨截止線只取 train 部分；統計在 validation 不更新。查詢歷史僅同 session 截至當下。所有 seed 的完整鄰居精確加總 Fraction 分數，再依 P0 count／數值 ID 排序；零分補集用完整 P0 順序填足，不刪已看商品、未抽負樣本或截斷歷史／鄰居。

完全回退共 16,319/166,897 筆（9.777887%）：

| 互斥診斷 | 查詢數 |
|---|---:|
| no_positive_causal_neighbor | 9,338 |
| positive_evidence | 150,578 |
| no_supported_seeds | 6,981 |

完整歷史長度、supported seeds、正證據 0／1–9／至少10及補位分布均在正式報告；診斷未用於刪除查詢或改分母。

C1 在這個開發窗推薦了 44,547 個不同商品，但冷商品問題仍未解決：預定的 `target_model/all_zero` 切片有 11,943 筆查詢，目標商品全部沒有 train 支援，P0 與 C1 的 NDCG 都是 0。這與上面的 16,319 筆完全回退是不同診斷，不能相加或當成同一批查詢。下一輪研究交付應明列這項適用缺口；本輪不因此刪除查詢或挑改參數。

## 全部預定切片與小組限制

| 預定切片 | query | visitor | P0 NDCG | C1 NDCG | 配對差 | 支援 |
|---|---:|---:|---:|---:|---:|---|
| visitor_history/seen | 32,648 | 6,298 | 0.001819638 | 0.084332291 | 0.082512653 | sufficient_query_count |
| visitor_history/new | 134,249 | 55,937 | 0.001648316 | 0.111767532 | 0.110119216 | sufficient_query_count |
| current_basket/single | 166,841 | 62,231 | 0.001682394 | 0.106363486 | 0.104681092 | sufficient_query_count |
| current_basket/multiple | 56 | 43 | 0.000000000 | 0.217314767 | 0.217314767 | descriptive_only |
| target_basket/single | 166,844 | 62,230 | 0.001681054 | 0.106386517 | 0.104705463 | sufficient_query_count |
| target_basket/multiple | 53 | 41 | 0.004120895 | 0.151093643 | 0.146972748 | descriptive_only |
| train_activity/0 | 134,300 | 55,959 | 0.001647690 | 0.111772173 | 0.110124484 | sufficient_query_count |
| train_activity/1 | 6,523 | 2,485 | 0.001677314 | 0.107720837 | 0.106043523 | sufficient_query_count |
| train_activity/2-5 | 6,009 | 2,185 | 0.003727135 | 0.116649122 | 0.112921987 | sufficient_query_count |
| train_activity/6+ | 20,065 | 1,606 | 0.001299281 | 0.066949892 | 0.065650611 | sufficient_query_count |
| target_model/all_positive | 154,951 | 59,411 | 0.001811490 | 0.114601217 | 0.112789727 | sufficient_query_count |
| target_model/mixed | 3 | 2 | 0.000000000 | 0.128950936 | 0.128950936 | descriptive_only |
| target_model/all_zero | 11,943 | 5,769 | 0.000000000 | 0.000000000 | 0.000000000 | sufficient_query_count |

支援門檻仍為 1,669 查詢，另報訪客數。多商品 current／target 56／53、混合支援 3 筆只能描述；原 train 多商品 199／192、locked test 33／29 與 Stage 6 小組限制保留。沒有用小組指標挑改方法、合併小組、推論或解鎖測試。

## 獨立驗收與資源

獨立 SQL 重新求 DISTINCT session memberships、self-join pair 次數與 query prefix；核對全部計數、session lineage、歷史、完整候選數、精確有理分數／順序、完整 target 指標／配對差／全部彙總。真實排序 oracle 為「all SQL neighbors plus exact zero-score complement proof」。商品對鄰居聯集以外分數必為零，完整零分補集證明保留所有候選；不是 top-L 或抽樣。

| 反讀產物 | 記錄數 |
|---|---:|
| `support.csv` | 198,946 |
| `pairs.csv` | 1,954,889 |
| `train_sessions.jsonl` | 1,180,256 |
| `queries.jsonl` | 166,897 |
| `bootstrap.jsonl` | 2,000 |

CSV 的計數與 ID 精確相等；JSONL 全部巢狀欄值均核對，浮點採絕對／相對 1e-12。收據中的 top_level_cells 僅為 JSON 頂層欄數，不能當成巢狀 scalar 總格數。全部 2,000 次抽樣的 SHA、RNG 前後狀態、抽中查詢分母及差值獨立重播並核對，percentile 另做線性插值驗證。

整輪資源監控回報 4197.172000 秒，抽查 RSS 峰值 1.034683 GiB，取樣 7,379 次；已列入 result 的執行檔案約 0.763138 GiB。8 GiB RSS／20 GiB 目錄／6 小時上限及剩餘磁碟8 GiB／系統可用記憶體4 GiB下限未觸發。這是合作式檢查與抽查峰值，不是作業系統硬性記憶體 kill 或絕對瞬時峰值。

輸入 107 份及輸出 13 份由新 guard 固定；P0 及歷史來源與鎖定快照另與本輪 before SHA 核對。沒有因結果或速度追加 fit、改候選、抽樣、截斷或重試。

## 保存、操作與下一步

模型、逐 session／pair／query、bootstrap、oracle SQLite、started／資源／manifest／guard 位於 Git 忽略的 `shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/`；原狀、日誌與交付核對位於 `shop-mysql-runtime/verification/retailrocket-cooccurrence-validation-v1/`。所有檔案在 shop，原 P0 與 UCI 封存不覆寫。

完成後只核既有 bytes，不重播擬合或評估：

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

舊規格凍結器的初始空目錄檢查是歷史範圍，本輪已有真實執行目錄，請用上述新入口核所有舊／新 guard；不要重播 `--prepare` 或 `--run-validation`。新入口完整重入只驗證，部分證據拒絕覆寫。

下一步先整理 C1／P0 的研究交付與適用說明，固定本輪結果及限制；若要比較新方法，另凍結單一候選的配對規格，不回頭對這個 validation 挑參數或小組。最終模型選擇／重擬合／test 仍須另立規格及後續明確執行範圍。

P0 validation 已在 C1 規格制定前曝光；目前僅同一來源的回溯時間開發比較。匿名訪客不等於獨立真人，沒有 ingestion／revision／完整性、曝光／propensity或連續可售庫存證據，不能推論轉換、營收、營運或因果提升。NC-SA 授權、Olist／UCI 舊限制保留；有利區間不會自動解鎖預留測試。
