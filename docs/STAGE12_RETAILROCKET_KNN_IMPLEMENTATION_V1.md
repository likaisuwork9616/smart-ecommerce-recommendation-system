# Stage 12：K1 實作、合成獨立驗收與 train-only 成本 v1

本輪依[已凍結比較規格](STAGE12_TEMPORAL_AVAILABILITY_AND_KNN_SPEC_V1.md)實作 K1 核心、四臂記憶體評估器及獨立 oracle。順序是手算／合成測試、兩組正式合成反讀驗收，全部通過後才執行真實 train-only 成本。**真實 K1 索引建置、validation 排名／指標／bootstrap、最終選模、refit 與預留測試均未啟動。** 合成資料上的 P0／C1／D1／K1 計算不能當作真實推薦成績。

正式結果由[實作驗收收據](../reports/stage12/retailrocket_session_knn_v1_implementation_acceptance.json)記錄測試數、兩組完整反讀、每筆成本對帳與實測資源；[實作來源凍結](../reports/stage12/retailrocket_session_knn_v1_implementation_specification.json)保存程式／環境及 scope。[本輪機器契約](contracts/retailrocket_session_knn_implementation_v1.json)只補充實作與執行界線，沒有覆寫原比較契約、原 315 份來源或三臂結果。

## 手算案例

三個 train sessions 的不同商品集合為 `T1={1,2}`、`T2={1,3,4}`、`T3={1}`；當前 session 與它們不同，歷史 `H={1,99}`，商品 99 沒有 train 支援。各集合在合成來源中均於 fit 截止前發生，候選包含全部上述商品。

| 手算項目 | 精確結果 | 核對重點 |
| --- | --- | --- |
| Jaccard(H,T1) | 1/3 | 未知的 99 留在聯集分母 |
| Jaccard(H,T2) | 1/4 | 不截短歷史或鄰居集合 |
| Jaccard(H,T3) | 1/2 | singleton 保留且可投給已看商品 |
| 商品 1 分數 | 1/3＋1/4＋1/2＝13/12 | 分數可以大於 1，不是機率 |
| 商品 2／3／4 分數 | 1/3、1/4、1/4 | 商品 3、4 再依原 P0 次數、數值 ID 解同分 |
| 鄰居順序 | T3、T1、T2 | 精確有理數比較，不用浮點 epsilon |

若改成 `H={1,99,100}`，三相似度為 1/4、1/5、1/3，商品 1 得 47/60。手算測試逐值核對，不以四捨五入結果比較。另測同 session 排除、同訪客另一 session 保留，以及重複 basket 只改原始次數、不重複增加 session 支援。

## 實作與驗收範圍

| 模組 | 行為與驗收 |
| --- | --- |
| `retailrocket_session_knn.py` | train-only session 集合、完整倒排索引、精確 Jaccard top500、投票、完整因果候選與 P0 零分補位；唯讀集合及雙向索引一致性核對 |
| `retailrocket_session_knn_evaluation.py` | 無真實資料 loader 的純評估器；四臂 key／history／target／分母配對、原對照值複製、主／條件／原切片及 K1−C1 bootstrap |
| `retailrocket_session_knn_oracle.py` | 不引用 K1 核心或評估器；從合成原始 baskets 用 SQL DISTINCT 重建所有 session-item／postings，枚舉所有 sessions 及完整候選排序，另算因果前綴 |
| `retailrocket_session_knn_cost.py` | 真實資料只做每 session 成本及 lineage 對帳；第二套 CSV／SQL 路徑逐筆反讀成本，不建立全域 K1 模型 |
| `prepare_retailrocket_session_knn_v1.py` | 僅 `--prepare`／`--verify`，前者先合成後成本並保存凍結收據；沒有真實 validation、final 或 test 執行選項 |

原始 basket 與 query 名冊沿用既有 lexical visitorid／session／time 順序；**鄰居同分與模型身分**另依數值 visitorid、整數 session_start_ms 排序，不能混用字串順序。模型 SHA 綁定算法名稱、訓練窗與完整 session 商品集合；baskets 次數等另存 audit。輸出包括完整 session、postings、train lineage、每查詢選中鄰居／分子／分母、完整正交集鄰居池 SHA、精確商品分數與回退診斷。

主要算法先完整找出正交集鄰居，使用固定 500 個最小排序鍵取得精確 top500；這不是預先取樣。獨立 oracle 逐一掃描每個 train session，重算交／聯集及排序，不讀主要倒排索引來找鄰居。之後對每個完整因果候選獨立加總所有選中鄰居的票數，與主要稀疏投票＋零分補集排序核對。

499／500／501 鄰居、精確同分與 numeric ID／session 起點順序均有反例；邊界相似度相同仍只保留前 500，不擴張。已看商品與 singleton self-vote 保留；只排除與 query 完全相同的 session key，同訪客其他訓練 sessions 可保留。未知 seed 仍留在 H 與聯集分母。

兩組正式合成證據分別覆蓋跨界前綴、冷商品、只有自己可當鄰居、完整分母與四臂，以及 501 個同相似度鄰居的邊界。每組保存原始合成輸入、三臂參照、模型／lineage、query／bootstrap 明細與聚合，再完整反讀；模型 membership、postings、選中鄰居與全部巢狀欄值均核對，沒有抽樣 oracle。

指標 oracle 沿用先前獨立的 Decimal／Fraction 路徑；bootstrap 沿用獨立 Counter 抽樣計數與 struct little-endian draw SHA、明確分位數內插的反讀路徑。這些獨立工具沒有 import K1 production。每組完整核對 2,000 次抽樣、RNG 狀態與查詢分母；用 visitor 成組並按抽中 query 數加權，沒有改成訪客平均。K1 分數仍是精確分數，僅 NDCG 等指標沿用 binary64／1e-12 容差。

合成 provenance wrapper 明列 P0／C1／D1 的 fit 身分，原對照指標逐值複製；獨立 oracle 再核其指標與全部名冊。缺／多／重複 query、錯來源身分、錯分母、缺 current basket、修改巢狀鄰居值或 bootstrap 分母都必須失敗。未來真實入口仍需把這個 wrapper 綁到原三臂來源 bytes，不能只拿記憶體物件冒充來源驗收。

## 真實 train-only 成本

本輪唯一解碼真實行為商品的工作是 train-only 成本；使用既有 `baskets.csv`、C1 `train_sessions.jsonl` 與 `support.csv`。不開真實 `queries.csv`，不解碼 validation／test 商品陣列或 targets。來源完整性核對可能讀取整份檔案 bytes 作 SHA，與語意解析分開計數。

| 步驟 | 方法與限制 |
| --- | --- |
| 第一遍 | CSV 先看 role，只有 train 才解碼 items；暫存當前 session 的集合，輸出 baskets／原 memberships／不同商品數／membership SHA，完整比對原 C1 train lineage |
| 第二遍 | 另一個 CSV 解析器先篩 role；只為當前 session 使用 SQL DISTINCT，逐列核對第一遍成本及商品集合 SHA，session 結束即清除 SQL 暫存 |
| Posting 長度 | 讀原已驗收 C1 `S_i`，取得商品數、總和與最大值；不重新擬合全域支援或建立 item→sessions 索引 |
| 守恆 | `M=sum_s |T_s|=sum_i S_i`；原 C1 的 session／basket／singleton／membership 聚合亦須一致 |
| 輸出 | 逐 session 成本 CSV 與資源日誌留在忽略路徑；公開報告只保存聚合、hash、核對數及 scope |

合成成本測試把所有非 train 商品欄故意改成無法 JSON 解碼的字串；兩遍仍通過，確認程式在解碼前分流角色。成本盤點沒有事先用 validation 查詢計算鄰居池，也沒有使用預留測試估耗時。

真實成本數字以正式收據為準。`M` 和最大 posting 可以說明索引規模，但**不能保證每個 validation query 的完整搜尋、Fraction 加總、全量 oracle 耗時或記憶體**。對 query 的 posting 訪問上界仍為 `sum_(i∈H) S_i`，投票上界為所選 500 鄰居的集合長度總和；本輪沒有估計真實 query 的 H 分布或測量真實排名速度。

## 資源、保存及下一步

沿用 RSS 8 GiB、執行目錄 20 GiB、6 小時，以及剩餘磁碟 8 GiB／可用記憶體 4 GiB 下限。成本逐列、SQL 與階段邊界提供合作式檢查；0.5 秒取樣不能宣稱 OS 瞬時硬限制。超限或驗收失敗保存 started／failure／部分證據，不抽樣、不縮 k、不重設 namespace 或無紀錄重試。

```powershell
# 完成後只核凍結來源、合成／成本產物與原 gates；不重算成本或模型。
.venv\Scripts\python.exe -B scripts\prepare_retailrocket_session_knn_v1.py --verify

# 僅合成資料及守門測試；不讀真實 train 或 validation 商品列。
.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_session_knn tests.test_retailrocket_session_knn_entry tests.test_retailrocket_session_knn_spec -v
```

首次空白 namespace 才用 `--prepare`；完整產物重入只驗證，部分產物停止並保留。實作 guard 位於 `shop-mysql-runtime/retailrocket_session_knn_implementation_v1/`；測試、正式合成案例與成本位於 `shop-mysql-runtime/verification/retailrocket-session-knn-implementation-v1/`。原研究資料、三臂模型、規格、結果與六份 test gates 只讀保留。

下一步先另行建置、驗收及凍結真實 validation 的來源 loader／完整反讀／單次執行入口，再依後續明確工作範圍決定是否執行。**本輪沒有真實 validation 入口，也沒有 final／test 模式。** 最終選模、train＋validation 重擬合與預留回溯測試繼續另行規劃；Stage 4 每日 10% 提醒、Stage 4／5 待資料與 Dashboard 暫緩維持。
