# Stage 12：時間資料盤點與 K1／C1 比較規格 v1

本輪選定 **K1：Jaccard session-kNN，固定 500 個鄰居、完整搜尋**。唯一研究問題是：在相同 Retailrocket 已曝光開發查詢、完整候選與分母下，這個固定 session 鄰居投票方案相對原 C1 的 query-macro NDCG@10 差多少？這是完整方法比較，尚未選出最終模型。

2026-10-29 已查核官方 metadata、發布者下載標頭及本機資料入口。沒有新增已驗收的同來源時間資料，因此凍結於既有 train／validation；外部來源另列待 intake，不能直接替換本規格資料。**本輪 0 新 fit、0 排名、0 指標、0 bootstrap、0 真實事件／query 列解析；未執行成本掃描、final refit 或預留測試。** 原 P0／C1／D1、三臂證據包與六份 gate 保留。

閱讀入口：[來源及候選盤點](../reports/stage12/retailrocket_stage12_inventory_v1.json) → [機器契約](contracts/retailrocket_session_knn_paired_v1.json) → [凍結收據](../reports/stage12/retailrocket_session_knn_v1_specification.json)。收據的實際檔數與測試數為正式驗收結果；它不是模型實作驗收。

## 時間資料可取得性

本輪查核範圍是本機既有 raw／downloads／交接入口，以及 Retailrocket、REES46 多品類及化妝品資料的官方連結；不是宣稱網際網路上不存在其他來源。七個 metadata／發布頁回應均 HTTP 200，原回應與查核程式保存在 Git 忽略路徑並記錄 SHA。下列容量來自 API 或 HTTP 標頭，沒有測量下載耗時、解壓後工作空間或實際事件列數。

| 來源 | 實際查到的範圍與可取得性 | 本輪判定 |
| --- | --- | --- |
| 本機既有資料 | `data/raw/` 僅 Olist、UCI Online Retail II、Retailrocket；downloads 僅既有 Olist／MySQL 包；四類時間交接入口未出現 | 在已查入口沒有新交接，不把重新解壓或匯入當新快照 |
| Retailrocket 官方當前包 | API `currentVersionNumber=2`；四檔名稱／大小與既有 manifest 一致，共 987,498,023 bytes。既有來源稽核的事件上限為 2015-09-18 02:59:47.788 UTC | 未確認到同來源後續事件；本輪未重下並核遠端 payload，因此檔名／大小一致不等於新遠端 SHA 驗證 |
| REES46 多品類／Kaggle v8 | API 列出 2019-Oct、2019-Nov，合計 14,675,375,250 bytes；分頁 token 為空 | metadata 可取得；不能只根據網頁所稱七個月就說 Kaggle 包含七個月 |
| REES46 多品類／發布者額外檔 | metadata 明列七個 gzip，2019-Oct 至 2020-Apr；七次 HEAD 皆 200，標頭長度合計 17,668,345,567 bytes | 官方連結可達；尚未下載、核 CRC／SHA、實測時段或完整性。是外部商店，非 Retailrocket 延伸 |
| REES46 化妝品／Kaggle v6 | API 五檔：2019-Oct／Nov／Dec、2020-Jan／Feb，合計 2,434,277,452 bytes；分頁 token 為空 | metadata 清單完整可讀；是規模較小的後續外部 intake 選項，未驗收或選為本輪比較資料 |

來源：[Retailrocket 原發頁](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)、[REES46 發布者](https://rees46.com/en/datasets)、[多品類原發頁](https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store)、[化妝品原發頁](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop)。API URL、每檔 bytes、時間及標頭結果完整列於盤點 JSON。

三個 Kaggle 版本化下載端點的 **HEAD 回傳 404**；這只能說此 HTTP 方法未確認下載，不能推成 GET 下載不存在或資料消失。發布者 gzip 的 HEAD 200 也不等於已下載驗收。Retailrocket `versions` 同時含舊 2017 年編號 3／4、重複編號 2，不能取最大編號或把 2022 年上傳日期當後續事件年。

兩個 REES46 API 的 `licenseName` 是 `Data files © Original Authors`，描述另說可免費使用並附原發頁及 REES46 來源。本輪只保存這些陳述，不改標成 CC 授權，也不據此宣稱商業或模型再散布權利。Retailrocket 原 CC BY-NC-SA 4.0 研究界線沿用既有來源契約。

外部來源接入前仍需下載完整包、SHA／CRC、實際逐日時間與缺日、schema／重複／衝突、匿名鍵與 session 語意、時間精度、來源權利及因果候選契約。頁面的 `event_type` 說明同時出現僅 purchase 與四種事件清單，必須用檔案驗證，不能直接照文案建標籤。可用事件時間也不等於有原入庫／修訂／完整水位證據。換商店會同時改變來源與時期，不能把差異單歸因時間。

**新增驗收時間來源數為 0。** 既有 2015-08 validation 已曝光；2015-09-01 至 09-18 的預留回溯測試繼續 locked；2015-09-18 部分尾日保持排除，不升格成另一個驗證窗。若日後取得新資料，先另立來源／角色契約，再決定獨立的時間或跨來源研究。

## 候選及選擇理由

| 候選 | 本輪決定與理由 |
| --- | --- |
| K1 session-kNN | 選定；已有 session 商品集合及當前因果歷史，可做可手算的精確相似度與投票，不需新增商品特徵或持續訪客向量 |
| 無向相鄰關聯 | 暫緩；可另研究 D1 的方向效果，但不是本輪 session 鄰居問題 |
| Implicit ALS／BPR | 暫緩；需另定矩陣表徵、新 session fold-in、優化與隨機設定 |
| 標準稠密 EASE | 暫緩；既有 198,946 個正支援商品的一份 float64 方陣需 316,636,087,328 bytes，超出本規格資源。此為算式，非實測峰值 |

session-kNN 的相似 session 加權投票見 Ludewig／Jannach [原論文 v2 §3.2.2](https://arxiv.org/pdf/1803.09587v2)。K1 採 Jaccard 以保留精確有理數計算，k=500 是出分前固定的研究設定，沒有試跑其他 k 或相似度。原論文也使用其他設定及鄰居取樣，本規格不聲稱複製其實驗或沿用其最佳值／成績。

P0／C1／D1 的開發結果、切片和主要區間已在選 K1 前曝光。選 K1 的依據是資料相容、可核對及研究範圍；目前沒有 K1 效能證據。K1 同時改變鄰居選擇、正規化和 self-item 投票，不能把之後的差異當單一因素效果，也不聲稱解決無 train 支援的冷商品。

## K1 精確定義

| 項目 | 凍結規則 |
| --- | --- |
| 訓練角色 | UTC [2015-05-04, 2015-08-01)，來源為既有 `baskets.csv`；未來一次主要索引建置，另一次獨立重建驗收 |
| `T_s` | 每個 `(visitorid, session_start_ms)` 在 train 窗內全部 baskets 的不同商品集合；含 singleton 與未標註 baskets，不依最終 session 長度或標籤篩選 |
| 跨界 session | 只收 train 部分，不摻 warmup／validation／test 商品；不因 session 跨界刪整個 session |
| 索引 | 商品→完整 train sessions，與每個完整 `T_s`；逐商品 session 數必須等於原 C1 的 `S_i`，完整 lineage 對齊 |
| `H(q)` | 與 C1 相同，同 session 截至當前 basket 的不同商品聯集，包含當前及已發生的跨角色上下文；不截短、不加權 |
| 未知 seed | 留在 `H` 及 Jaccard 聯集分母；不從歷史移除，只沒有 train posting |
| 鄰居池 | 所有與 `H` 有正交集的 train sessions；排除與 q **同一 session key** 的訓練前綴，同訪客其他 session 可保留 |
| 相似度 | `|H∩T_s| / (|H|+|T_s|−|H∩T_s|)`，精確整數比值；重複瀏覽不重複計數 |
| 取鄰居 | 相似度降冪、數值 visitorid 升冪、session_start_ms 升冪，取前 min(500, 正交集合格數)；邊界同分不擴張 |
| 商品分數 | `sum_s sim(H,T_s) × 1[j∈T_s]`，s 為選出的鄰居；精確有理數加總，不正規化、不混合 P0 |
| Self-item | 鄰居對已在 `H` 的商品仍投票，含 singleton；候選也保留已看項。這與 C1 零對角的計分方式不同，是已揭露的方法差異 |
| 固定統計 | validation 不加入索引、不更新支援；無 IDF、recency、衰減、平滑、歷史截斷或多版本搜尋 |

500 是算法定義的最終鄰居數，**不允許先抽 500／1,000 個 sessions 再找鄰居**。完整倒排取聯集可省去零交集的精確零分 sessions；所有正交集仍須完整考慮，不用 ANN、最近 sessions 取樣或隱藏剪枝。

商品排序保持完整因果候選 `first_view_ms < query_ms`，依 K1 分數降冪、原 P0 次數降冪、數值商品 ID 升冪。各自缺值才補零；保留已看、冷商品與零票商品。不足 10 個正分時，從**完整零分補集**補位；全無正票則完全回退原 P0，不能只接截斷 P0 top10。短目錄返回 min(10,目錄數)，空目錄對非空 target 計 0；缺歷史 join 是錯誤而不是回退條件。

## 配對、分母與區間

| 項目 | 凍結內容 |
| --- | --- |
| validation | UTC [2015-08-01, 2015-09-01)，166,897 queries／62,235 匿名 visitors |
| 對照 | 原 C1 為唯一主要對照；P0、D1 僅描述性參照。讀原排名／指標，不重訓、不重排、不重算舊比較區間 |
| 四臂對帳 | 完整 query key 與儲存順序一致；缺／多／重複任一筆停止，不 inner join 掉困難樣本 |
| 主分母 | 166,952 target 次數，其中 161,264 可達；共同候選聯集 222,754。不可達目標留在 Recall 與 IDCG 分母 |
| 唯一主要差 | 全查詢平均 `NDCG_K1@10 − NDCG_C1@10` |
| 其他指標 | Recall、HitRate、MRR、visitor-macro NDCG、共同候選聯集 coverage；K1−P0／K1−D1 及切片僅描述 |
| 條件分母 | 同 161,211 筆全 target 可達查詢，另外列出，不能替換主結果 |
| 主區間 | 2,000 次 paired visitor-cluster bootstrap，95% linear percentile；NumPy 2.5.4／PCG64／seed 42 |
| 比較解讀 | 不設事後通過門檻，不新增次比較／切片區間或 p 值；不因正區間自動最終選模、refit 或開 test |

bootstrap 依數值 visitorid 排 62,235 個 cluster，每輪抽同數量 visitors，保留抽中 visitor 全部 queries，用抽中 query 數加權；不能改為 visitor 均值或 query iid 抽樣。與舊 C1 抽樣逐輪核 draw SHA（little-endian int64）、RNG 前後狀態及分母，**K1−C1 差值必須新算，不能借用既有區間**。保留 C1 原 binary64 指標，逐筆相減及 `math.fsum` 順序見機器契約；主指標容差 1e-12，鍵、計數、有理數及排序精確相等。

全部原切片保留。11,943 查詢／5,769 訪客的冷目標組仍按共同 `S_i` 定義；原三臂為零不代表本輪已算 K1。Current multiple 56、target multiple 53、mixed 3 低於 1,669 查詢門檻，照列且只描述。新增診斷列出完整交集鄰居數、排除同 session 數、實選鄰居／邊界同分、未知 seed、正票候選／補位／完全回退，另與 C1／D1 回退及冷目標交叉列示，不能相加當同一缺口。

## 成本與下一輪驗收

本輪尚未掃描 train 列或建索引，不能保證 K1 在既定預算內跑完。下一輪先做合成實作與獨立 oracle，再做 train-only 成本：session 數、singleton、`M=sum_s|T_s|=sum_i S_i`、最大 session 及 posting 大小。可掃角色 metadata，但只解碼 train items，禁止解碼 validation／test items 或 targets；成本掃描不先建立全域 K1 模型。

對查詢的 posting 訪問數上界為 `sum_(i∈H) S_i`，投票訪問數為 `sum_(s∈N500)|T_s|`。這些是結構界；train 總數不能保證每個未來查詢耗時，仍須完整搜尋與完整 oracle。

未來一輪主要索引＋完整 validation／bootstrap＋獨立驗收的上限固定為 RSS 8 GiB、執行目錄 20 GiB、6 小時；磁碟剩餘至少 8 GiB、系統可用記憶體至少 4 GiB，監控間隔 0.5 秒並加工作檢查點。這是合作式監控，非 OS 瞬時硬限制。超限保留 started／failure／部分證據並停止，不能縮 k、抽樣、截歷史、改分母或無紀錄重試。

實作驗收須涵蓋精確相似度與完整投票、重複／同時商品、singleton self-vote、同 session 排除與同訪客其他 session、跨界／未來注入、未知歷史保留分母、499／500／501 鄰居及邊界同分、嚴格事前候選、完整零分補位、四臂缺筆與分母及全部 bootstrap。獨立 SQL 從原 train baskets 重建所有 session-item；每筆 validation 的全鄰居池、top500、有理分數、候選補集、排名及巢狀值都要核對，不接受抽樣替代全量。

合成驗收與成本通過後，另凍結實作、環境、輸出 schema、資源檢查點及 guarded validation 入口。本輪只有規格工具，沒有 K1 評估命令。

## 凍結及操作界線

```powershell
# 只讀核對本輪凍結文件、來源 bytes 及原 test gates，不讀事件列、不執行研究。
.venv\Scripts\python.exe -B scripts\freeze_retailrocket_session_knn_v1.py --verify
# 僅合成 metadata／守門測試，不是 K1 模型驗收。
.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_session_knn_spec -v
```

`--freeze` 僅供空白 v1 namespace 首次凍結；部分輸出保留並拒絕重入，完成後使用 `--verify`。本輪原網路回應、查核腳本及 guard 位於 `shop-mysql-runtime/verification/retailrocket-stage12-spec-v1/`、`shop-mysql-runtime/retailrocket_session_knn_spec_v1/`，均在 shop 且 Git 忽略。凍結來源或規則變更需另立版本，不覆寫既有收據。導覽 README 可更新，研究文件和契約的 bytes 固定。

最終選模、train＋validation 重擬合、預留回溯測試均另行規劃。原 gate 不授權 K1；本輪不建立 final／test 產物或 usage journal。舊 builder 已讀過預留區結構及標籤，未來即使另行解鎖仍是預留回溯評估，不能稱為全新未知來源。

Stage 4／5 維持待新資料；延遲提醒仍為每日 10%，Dashboard 暫緩。下一步是 K1 合成實作、獨立驗收與 train-only 成本，不是直接執行真實比較或最終測試。
