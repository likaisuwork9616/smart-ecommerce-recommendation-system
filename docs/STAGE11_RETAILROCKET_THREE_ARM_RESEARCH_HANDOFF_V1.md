# Retailrocket D1／C1／P0 v1：三臂研究交付與適用說明

D1／C1／P0 的同窗比較已完成研究交付：保存已驗收的模型、完整 validation 排名、主要配對 bootstrap、獨立反讀與來源身分，另存三臂證據包及完整性收據。**主要結果不支持以 D1 取代 C1**：在這個已曝光的開發窗，D1−C1 NDCG 差為 −0.006600944，95% 訪客成組區間全為負。這個結論沒有完成未知時間驗證、最終選模或部署驗收；預留測試仍 locked。

本輪只整理交付、讀取既有聚合及核對、保存檔案 bytes，沒有新增擬合、排名、指標重算或 bootstrap。下列數字全部引用既有正式報告，P0／C1／D1 原模型、程式、規格、排名、收據及舊 C1／P0 證據包保持原狀。封存時的檔案 CRC／SHA 核對不等於重新執行研究 oracle。

## 閱讀順序與交付範圍

| 入口 | 用途 |
| --- | --- |
| [資料來源與契約](STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md)、[建置驗收](STAGE8_RETAILROCKET_BUILD_V1.md) | 時間角色、下一瀏覽集合、因果候選、完整分母與去重／排除／跨界帳 |
| [P0 真實開發結果](STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md)、[C1／P0 交付](STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md) | 兩個原對照的固定方法、歷史結果與原保存包 |
| [D1 候選與比較規格](STAGE11_RETAILROCKET_DIRECTED_SPEC_V1.md)、[機器契約](contracts/retailrocket_directed_paired_v1.json) | 曝光聲明、唯一研究問題、方法與主要／描述性比較界線 |
| [D1 實作及入口](STAGE11_RETAILROCKET_DIRECTED_IMPLEMENTATION_V1.md) | 手算、獨立合成驗收、train-only 成本及固定資源限制 |
| [D1 真實三臂比較](STAGE11_RETAILROCKET_DIRECTED_VALIDATION_V1.md) | 全部主／條件／預定切片、回退診斷、train 對帳、資源與完整反讀 |
| [正式聚合](../reports/stage11/retailrocket_directed_v1_validation.json)、[獨立驗收](../reports/stage11/retailrocket_directed_v1_validation_acceptance.json) | 精確數字、完整驗收範圍與原 SHA 身分 |
| [三臂證據保存收據](../reports/stage11/retailrocket_three_arm_v1_research_release.json) | 本輪實際 ZIP 檔數／大小／SHA、CRC／SHA 反讀、包外依賴與零研究操作紀錄 |

舊規格及實作文件保留當輪的「尚未執行」快照，不回寫成較晚結果；目前狀態由真實結果文件、本交付及新保存收據承接。

## 固定方法與評估角色

| 項目 | 固定內容 |
| --- | --- |
| 任務 | 同 session 下一個嚴格較晚的 view 商品集合，K=10；未評估購買、轉換或營收 |
| 訓練窗 | UTC [2015-05-04, 2015-08-01)；各版本一次主要 train 擬合，獨立重建屬驗收 |
| 開發 validation | UTC [2015-08-01, 2015-09-01)，166,897 查詢／62,235 匿名訪客，三臂 key 與順序相同 |
| 預留回溯測試 | UTC [2015-09-01, 2015-09-18)，仍鎖定；本輪 0 筆出分、0 final refit |
| P0 | train canonical view 次數降冪，再以數值商品 ID 排序；缺次數才補零 |
| C1 | 每 train session 的不同商品集合計單商品支援 S 與無序共現 C；singleton 保留、無 self-edge |
| D1 | 原始相鄰 baskets 中的有向關聯 D，每 session 每方向只加一次；兩端同 session、原 index 差 1、時間嚴格增加且相隔不超過 30 分鐘，排除 self-edge，不橋接缺口或跨角色邊界 |
| 支援與歷史 | D1 完整重用 C1 的 S；同 session 截至當前 basket 的不同商品歷史與 C1 相同，validation 不更新模型統計 |
| 分數與解同分 | C1 精確加總 Cij/Si，D1 精確加總 Dij/Si；再依原 P0 次數與數值 ID 排序，兩者都不是機率 |
| 完整候選與回退 | first_view < query 的全部商品，保留已看、冷商品與無 outgoing 商品；無正證據完全回退 P0，正分不足時依完整零分順序補足 |
| 完整分母 | target 166,952 次，其中 161,264 次可達；共同候選聯集 222,754。不可達 target 仍留 Recall／IDCG 分母 |
| 條件結果 | 全 target 可達的 161,211 查詢另列，不能替換主結果 |
| 唯一主要比較 | 全查詢平均 NDCG@10 的 D1−C1；D1−P0、其餘指標及切片只描述 |
| 主要區間 | 62,235 個匿名 visitor 成組抽樣 2,000 次；NumPy 2.5.4／PCG64／seed 42，保留抽中 visitor 的全部查詢並按抽中查詢數加權，95% linear percentile |

P0／C1 的 validation 成績、切片及原 C1−P0 區間在選 D1 前已曝光。D1 在自身出分前固定方法，仍屬已曝光開發窗上的比較，不能把它稱為未知資料驗證。資料建置也已讀過預留測試的結構與標籤，因此未來解鎖仍是預留回溯評估。

D1 同時改變方向與鄰近性，這次比較不能分別歸因哪一項造成差異，也不是標準 Markov 機率模型。三臂使用完整候選，沒有抽負樣本、top-L、ANN、歷史截斷或刪除不利小組。

## 已有結果與可支持的解讀

| 同一 validation 指標 | P0 | C1 | D1 | D1−C1 | D1−P0（描述） |
| --- | ---: | ---: | ---: | ---: | ---: |
| query-macro NDCG@10 | 0.001681829 | 0.106400714 | 0.099799771 | −0.006600944 | 0.098117941 |
| Recall@10 | 0.004179224 | 0.180151531 | 0.167483538 | −0.012667993 | 0.163304313 |
| HitRate@10 | 0.004182220 | 0.180182987 | 0.167522484 | −0.012660503 | 0.163340264 |
| MRR@10 | 0.000943565 | 0.083664114 | 0.078904014 | −0.004760100 | 0.077960449 |
| visitor-macro NDCG@10 | 0.001622526 | 0.113072891 | 0.104230872 | −0.008842019 | 0.102608347 |
| 商品 coverage@10 | 0.000044893 | 0.199982941 | 0.198990815 | −0.000992126 | 0.198945922 |

比例為 0–1，差為絕對差。商品 coverage 是推薦商品聯集除以共同候選聯集，並非逐查詢平均；P0／C1／D1 推薦的不同商品分別為 10／44,547／44,326。

主要 NDCG 差的精確值為 **−0.00660094375412807**，95% 區間為 **[−0.0075118929816948244, −0.005716746961295219]**。這個已曝光窗的主要比較偏向 C1；六項表列指標的 D1 值也都低於 C1、高於 P0，但只有主要 D1−C1 NDCG 有推論區間。D1−P0 NDCG 的 +0.09811794137315684 是描述性差異，不能延伸成「同時顯著勝過兩個對照」。沒有新增切片區間、p 值或事後通過門檻。

本研究沒有支持以 D1 替換 C1，也沒有證明 D1 在其他時間必然較差。保留 C1 作後續研究對照，不等於已選定部署模型或完成最終選模。原 C1−P0 結果仍保留於 Stage 10；本輪沒有重算該區間。

## 回退、冷商品與小組支援

| 項目 | 已觀察證據與解讀 |
| --- | --- |
| D1 完全回退 | 18,556 查詢（11.118235%），其中 6,981 無共同 S 支援 seed、11,575 無 outgoing seed；其餘正證據 148,341，`no_positive_causal_neighbor` 為 0 |
| 與 C1 回退比較 | C1 完全回退 16,319，全部也在 D1 完全回退；D1 額外回退 2,237。回退增加不能單獨解釋全部 NDCG 差異，也沒有據此刪除查詢 |
| 原冷目標切片 | `target_model/all_zero` 為 11,943 查詢／5,769 訪客；三臂 NDCG、Recall、HitRate、MRR 皆為 0，冷商品缺口未解決 |
| 冷目標的可達性與 coverage | 冷 target 11,946 次，其中 6,258 次可達；D1 在此切片推薦 14,171 個不同商品、coverage=0.063617264。無 train 支援不等於全部不可達、從未見過或全部指標為 0 |
| Current 多商品 | 56 查詢／43 訪客，低於 1,669 查詢門檻，僅描述 |
| Target 多商品 | 53 查詢／41 訪客，低於門檻，僅描述 |
| 混合有／無支援目標 | 3 查詢／2 訪客，僅描述；沒有合併、刪除或調整門檻 |
| 既有不足 | train 多商品 199／192、locked test 33／29；Stage 6 Olist 25、UCI 87／83 小組不足仍保留 |

冷目標、完全回退、D1 incoming／outgoing 支援是不同診斷，不相加、不假定同一批查詢。Outgoing keys 不能取代原共享 S 的冷商品定義，無 outgoing 商品仍可能有 incoming 邊。冷目標切片本身不是低於查詢門檻的小組；它的主要問題是本次三臂皆未命中。

查詢支援門檻僅為描述性下限，不保證統計效力、獨立真人或營運收益。同一訪客可能出現在不同切片，不能把跨組訪客數直接相加。

## 已完成驗收與適用界線

既有 D1 獨立 SQL 重建有向計數、完整共享 S、session lineage 及 query prefix，完整核對三臂名冊／候選／分母、精確有理排序、原對照 binary64、逐筆指標與差值、聚合及全部 bootstrap。排名 oracle 枚舉全部 SQL outgoing 鄰居並驗證精確零分補集，沒有用抽樣取代全量驗收。

| 已驗收產物 | 完整反讀記錄數 |
| --- | ---: |
| D1 商品支援 | 198,946 |
| D1 全域不同有向邊 | 370,325 |
| D1 train session lineage | 1,180,256 |
| 三臂 validation 查詢 | 166,897 |
| 主要 D1−C1 bootstrap | 2,000 |

全部 JSONL 巢狀欄值均已核對；原收據的 `top_level_cells` 不能當成巢狀 scalar 總格數。真實 D1 執行與完整驗收耗時 2,377.547 秒，抽查 RSS 峰值 1.331944 GiB，未觸發固定的 8 GiB RSS／20 GiB 執行目錄／6 小時上限及磁碟剩餘 8 GiB／系統可用記憶體 4 GiB 下限。這是合作式檢查與抽查峰值，不能宣稱 OS 瞬時硬限制，也不能用單次耗時推論 D1 比 C1 更快。

| 用途 | 目前適用程度 | 擴大用途前需要的證據 |
| --- | --- | --- |
| 方法學習、固定歷史結果核對 | 可讀已驗收三臂與原完整分母 | 保留來源身分、原模型、排名及驗收紀錄 |
| 同窗下一瀏覽研究 | 可描述 D1 相對 C1 的負向主要結果及相對 P0 的描述性差異 | 新時間／來源需先固定研究問題、資料角色與評估規格 |
| 方向或鄰近性的單獨效果 | 未識別；兩項同時改變 | 另立能分開辨識的比較設計，保留 validation 已曝光聲明 |
| 冷商品或多商品推薦 | 冷目標未命中，多商品支援不足 | 另定方法、可用資料與完整母體，不事後挑組改善結果 |
| 完全無上下文的新訪客 | 尚未單獨證明適用 | 真正無上下文名冊及事前回退規則；目前新訪客仍可能有當前 session 歷史 |
| 生產即時或可售推薦 | 尚未驗收 | 入庫／修訂／完成水位、連續庫存、延遲／容量與失敗處理要求 |
| 轉換、營收或因果效果 | 沒有此類證據 | 曝光／propensity、處置與比較設計及成熟業務結果 |
| 最終預留回溯測試 | 繼續鎖定 | 獨立的最終選模／refit／test 規格、實作驗收與後續明確執行範圍 |

匿名 visitor 不等於已驗證獨立真人，visitor-cluster bootstrap 不能補足跨時間泛化、來源偏差或身分證據。因果事件前綴也不證明當時生產系統實際可取得資料：原始入庫、修訂與完整性證據仍缺。保留既有來源紀錄的 CC BY-NC-SA 4.0 非商業、署名及適用分享條件，本輪沒有建立商業部署權利。

## 預留測試維持鎖定

現有六份 P0／C1／D1 規格與入口 gate 及其原 bytes 保留。P0 的資料／來源身分固定、合成驗收、完整 validation 反讀、final refit 前選定算法、另存 train＋validation final refit 並獨立驗收、第一筆 test 前固定 SHA、明確執行要求及持久排他 usage identity 等條件，均未因交付而撤銷。

**P0 gate 不是 C1／D1 授權，C1 gate 也不是 D1 授權。** 最終選模、refit 與 test 必須另定規格及實作，完成驗收並有後續明確執行範圍。現有 C1／D1 入口沒有 final refit 或 test 模式；交付完成、任何正負區間或選出目前較好模型都不解鎖。本輪不建立 final／test 產物或 usage journal。

未來最終評估最多一個 logical run；技術失敗若允許續跑，必須保持資料、規格、程式、環境、final-fit 與名冊身分完全相同，保留嘗試與部分證據，不重設 gate，也不依成績更換方法。這是後續規格須保留的界線，不是本輪啟動評估的授權。

## 證據保存與 shop 內位置

| 位置 | 內容 |
| --- | --- |
| `shop-mysql-runtime/retailrocket_popularity_v1/development/` | P0 原模型、排名、聚合、manifest／guard，原狀保留 |
| `shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/` | C1 原支援／pair、session／query、bootstrap、oracle、資源、manifest／guard |
| `shop-mysql-runtime/retailrocket_directed_paired_v1/` | D1 原支援／edge、session／query、bootstrap、oracle、資源、manifest／guard |
| `shop-mysql-runtime/backups/retailrocket_three_arm_research_release_v1.zip` | 新三臂結果證據包，逐成員清單與 SHA 隨包保存 |
| `shop-mysql-runtime/retailrocket_three_arm_release_v1/` | 包外 manifest／guard 控制證據 |
| `shop-mysql-runtime/verification/retailrocket-three-arm-release-v1/` | 本輪原狀快照、保存工具驗收、核對與交付日誌 |
| `reports/stage11/retailrocket_three_arm_v1_research_release.json` | 可公開完整性收據；實際成員數、大小、hash、反讀與依賴以此為準 |
| `shop-mysql-runtime/backups/retailrocket_c1_p0_research_release_v1.zip` | 舊 C1／P0 保存包，原狀保留並作為新包的包外依賴核 SHA |

新 ZIP 保存三臂結果目錄、guard 引用的公開研究程式／測試／契約／報告、私人 guard／gate、本交付文件及保存工具。README 等導覽保留封存當時脈絡快照，日後可更新；凍結研究及結果仍核 live bytes。已被原研究 guard 綁定的套件鎖檔等來源不會因快照分類而解除凍結。

原始資料、完整推薦資料集、執行環境及未收錄的私人驗收／成本證據是**包外、仍在 shop 內的依賴**，另列相對路徑、大小與 SHA；舊 C1／P0 ZIP 不重複塞入新 ZIP。正常 `--verify` 同時核這些依賴的 live bytes，`--verify-archive-only` 只確認保存包與公開收據，不能證明包外資料或環境完整。

這是結果證據包，不含所有重建材料、Python 安裝環境、Git 歷史、MySQL 或憑證，不能單憑 ZIP 宣稱完整環境可還原。原始資料、逐 ID／模型／抽樣明細、SQLite、執行紀錄與 ZIP 仍在 Git 忽略路徑。公開收據在包外保存 ZIP SHA，避免自我參照。所有檔案都在 shop；同磁碟固定副本及完整性核對沒有建立異地備援，也沒有發布原始資料。

## 只讀驗證與後續還原

```powershell
# ZIP 全成員 CRC／SHA、包外控制檔、shop 內凍結來源／依賴與 gate；不重跑研究。
.venv\Scripts\python.exe -B scripts\archive_retailrocket_three_arm_v1.py --verify
# 只核三臂保存包與公開收據，不宣稱包外材料完整。
.venv\Scripts\python.exe -B scripts\archive_retailrocket_three_arm_v1.py --verify-archive-only
# 原三臂結果亦各有只讀 bytes 驗證入口。
.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
.venv\Scripts\python.exe -B scripts\run_retailrocket_directed_v1.py --verify
```

保存工具不解壓、不重訓、不解析逐筆研究標籤。首次空白保存命名空間才使用 `--archive`；完整保存重入只驗證，部分產物停止並保留，不能刪除部分證據重播。既有真實產物建立後，不使用要求空白真實目錄的歷史凍結器作完成驗證。

若日後需要還原，先保留 ZIP 與包外收據，完成 archive-only 檢查，再於 shop 內另建乾淨目錄，按安全相對路徑還原，避免覆蓋現在的結果。逐項補齊 manifest 列出的包外依賴及相符環境，再完整驗證。Hash 不符先釐清來源及版本，不能重跑研究冒充原證據。本輪沒有執行還原演練，逐成員完整讀回是保存驗收。

## 下一步

1. 以本交付與保存收據固定三臂 v1，保留負向主要結果、冷商品及稀疏小組限制；查看歷史結果使用只讀入口。
2. 下一個研究決策先盤點是否取得新的時間窗／來源，以及要解答的單一問題。若接續 Stage 12–13 的新候選，先選定一個方法與研究問題、凍結比較規格和成本界線；既有 validation 持續標為已曝光，不回頭覆寫 v1、挑參數或挑組。
3. 最終選模、train＋validation 重擬合及預留測試另立規格與驗收，沒有因 C1 較好或 D1 較差而提前啟動。
4. Stage 4／5 仍待新資料，延遲提醒維持每日 10%；Dashboard 暫緩，API／前端尚未開始。

全專案狀態持續列於[專案進度](PROJECT_PROGRESS.md)與[README](../README.md)。
