# Retailrocket C1／P0 v1：研究交付與適用說明

C1／P0 已完成離線研究交付：保留同一 validation 的完整比較、獨立驗收、模型與逐筆證據，另存本機證據包及完整性收據。C1 在這個已曝光的開發窗優於 P0；冷商品缺口、小組支援不足與回溯研究限制仍成立，預留測試維持 locked。

本輪只整理交付、讀取既有聚合、核對檔案 bytes 與保存證據，沒有新增擬合、排名、bootstrap 或指標重算。下列成績均引用既有正式報告，不是本輪新實驗。P0 的程式、模型、排名、指標與收據保持原狀。

## 閱讀順序與交付範圍

| 入口 | 已完成的內容 |
| --- | --- |
| [推薦資料契約與來源](STAGE8_RETAILROCKET_SOURCE_AND_CONTRACT_V1.md)、[資料建置驗收](STAGE8_RETAILROCKET_BUILD_V1.md) | 下一瀏覽集合、時間角色、因果目錄、完整分母與去重／排除／跨界帳 |
| [P0 執行規格](contracts/retailrocket_popularity_execution_v1.json)、[真實開發結果](STAGE9_RETAILROCKET_POPULARITY_DEVELOPMENT_V1.md) | 一次 train 熱門次數統計、全部 validation 排名與獨立反讀 |
| [C1 配對規格](contracts/retailrocket_cooccurrence_paired_v1.json)、[實作與資源](STAGE10_RETAILROCKET_COOCCURRENCE_IMPLEMENTATION_V1.md) | 二元 session 共現、因果歷史、P0 回退、完整候選與成組 bootstrap |
| [C1／P0 真實比較](STAGE10_RETAILROCKET_COOCCURRENCE_VALIDATION_V1.md) | 全部主／條件／預定切片、回退診斷、資源與操作方式 |
| [正式聚合](../reports/stage10/retailrocket_cooccurrence_v1_validation.json)、[獨立驗收](../reports/stage10/retailrocket_cooccurrence_v1_validation_acceptance.json) | 精確數字、角色、逐筆核對範圍與既有 SHA 身分 |
| [本輪證據保存收據](../reports/stage10/retailrocket_c1_p0_v1_research_release.json) | 實際 ZIP 檔數／大小／SHA、成員 CRC／SHA 反讀、包外依賴及本輪零研究操作紀錄 |

## 固定方法與數字角色

| 項目 | 固定內容 |
| --- | --- |
| 任務 | 同 session 下一個嚴格較晚的 view 商品集合，K=10；不是購買或轉換預測 |
| 訓練 | UTC [2015-05-04, 2015-08-01)，各一次主擬合；獨立計數重建屬驗收，不是新候選 |
| 開發 validation | UTC [2015-08-01, 2015-09-01)，166,897 查詢、62,235 匿名訪客；全部保留 |
| 預留回溯測試 | UTC [2015-09-01, 2015-09-18)，仍鎖定；本輪 0 出分，沒有 final refit |
| P0 | train canonical view 次數降冪，再以數值商品 ID 排序；未知商品零分 |
| C1 | 每 train session 的不同商品集合；單商品支援與無序 pair 次數；singleton 保留，無 self-edge |
| C1 歷史／分數 | 僅同 session 截至當下（含當前 basket）的不同商品；精確加總 Cij/Si，再以 P0 次數及數值 ID 解同分；分數不是機率 |
| 候選與回退 | first_view < query 的完整目錄，保留已看商品；無正共現證據時完全回退 P0，缺額按完整零分順序補足 |
| 完整分母 | target 166,952 次，其中 161,264 次可達；候選聯集 222,754；不可達 target 仍留 Recall／IDCG 分母 |
| 條件結果 | 全 target 可達的 161,211 查詢另列，不能替換主結果 |
| 主要比較 | 全查詢平均 NDCG@10 的 C1−P0；兩模型逐查詢名冊、候選與 target 相同 |
| 不確定性 | 62,235 個匿名 visitor 成組抽樣 2,000 次；PCG64／seed 42，按抽中查詢數加權，95% linear percentile；只有主要配對差有區間 |

P0 validation 已在 C1 規格制定前檢視。C1 規格是在 C1 出分前固定，不代表在所有 validation 曝光前固定。資料建置也已讀過預留測試的結構與標籤，因此它是預留回溯評估，不能稱從未接觸的純未知資料。

## 已有結果與能支持的解讀

| 同一 validation 指標 | P0 | C1 | C1−P0 |
| --- | ---: | ---: | ---: |
| query-macro NDCG@10 | 0.001681829 | 0.106400714 | 0.104718885 |
| Recall@10 | 0.004179224 | 0.180151531 | 0.175972306 |
| HitRate@10 | 0.004182220 | 0.180182987 | 0.176000767 |
| MRR@10 | 0.000943565 | 0.083664114 | 0.082720549 |
| visitor-macro NDCG@10 | 0.001622526 | 0.113072891 | 0.111450365 |
| 商品 coverage@10 | 0.000044893 | 0.199982941 | 0.199938048 |

比例採 0–1，差為絕對差；商品聯集由 10 擴至 44,547，coverage 以共同候選聯集為分母，不是逐查詢平均。主 NDCG 差的 95% 區間為 **[0.101004915, 0.108446582]**。這支持本開發窗內 C1 相對 P0 的改善，不支持未知時間、其他資料來源、獨立真人、營運或因果提升。沒有切片區間、p 值或事後效能通過門檻。

既有 C1 驗收完整核對 198,946 筆商品支援、1,954,889 筆商品對、1,180,256 筆 train session、166,897 筆查詢及 2,000 次抽樣，JSONL 巢狀欄值亦全核對。其執行耗時 4,197.172 秒，抽查 RSS 峰值 1.034683 GiB，未觸發 8 GiB／20 GiB／6 小時資源限制。這是歷史研究的核對與資源紀錄；本輪檔案保存核對不等於重新執行上述 oracle。

## 冷商品、小組與回溯限制

| 限制 | 已觀察證據與解讀 |
| --- | --- |
| 目標無 train 支援 | `target_model/all_zero` 有 11,943 查詢／5,769 訪客；兩模型 NDCG、Recall、HitRate、MRR 都為 0。只代表本次 train 模型無正支援，不等於商品從未見過、全部不可達或永遠不能經零分回退被推薦；也不能說全部指標皆為 0 |
| 完全回退 | 16,319 查詢（9.777887%）：9,338 無正因果鄰居＋6,981 無支援 seed。與上列冷目標是不同診斷，不相加、不假定兩者是同一批查詢、不據此排除查詢 |
| 多商品 current／target | 56 查詢／43 訪客、53 查詢／41 訪客，低於 1,669 查詢門檻，僅描述 |
| 混合有／無支援目標 | 3 查詢／2 訪客，僅描述；不合併、刪除或調門檻來改善支援 |
| 既有小組限制 | train 多商品 199／192、locked test 33／29；Stage 6 UCI 87／83 與 Olist 25 小組不足仍保留 |
| 訪客與上下文 | 匿名 visitor 不等於已驗證獨立真人；新訪客仍可有同 session 當前瀏覽，不等於完全無上下文冷啟動 |
| 歷史可得性 | 僅事件時間代理，缺原入庫／修訂／完整性證據；因果前綴不等於已證明當時生產系統可取得 |
| 庫存與業務效果 | 缺連續可售庫存、曝光／propensity及成熟業務結果證據，不能宣稱可售保證、轉換、營收或因果提升 |
| 使用範圍 | 保留原來源紀錄的 CC BY-NC-SA 4.0 非商業、署名及適用分享條件；本研究未建立商業部署權利 |

查詢支援門檻只是描述性下限，不是統計效力或業務收益保證。bootstrap 處理同來源 visitor 的查詢相依，不能補足跨時間泛化、來源偏差或真人身分證據。

## 適用程度與擴大用途前的缺件

| 用途 | 目前適用程度 | 擴大用途前需要的證據 |
| --- | --- | --- |
| 學習方法、讀取固定歷史比較 | 可用已驗收版本與原完整分母 | 保留來源身分、模型、原排名與驗收紀錄 |
| 同窗下一瀏覽推薦研究 | 可描述 C1 相對 P0 的改善 | 新時間／新來源需預先固定的評估設計與資料角色 |
| 冷商品或多商品推薦 | 冷目標無命中，多商品支援不足 | 另定方法、資料支援與完整母體；不能事後刪人挑組 |
| 完全無上下文的新訪客 | 未單獨證明適用 | 真正無上下文名冊、事前回退規則與評估 |
| 生產即時服務與可售推薦 | 未驗收 | 入庫／修訂／完成水位、連續庫存、延遲／容量與失敗處理要求 |
| 轉換、營收與因果效果 | 無此證據 | 曝光、處置／比較設計與成熟業務結果 |
| 最終預留回溯測試 | 鎖定 | 下節完整條件及 C1 專屬最終規格，不以正向區間取代 |

## 預留測試維持鎖定

既有 P0 規格的八項條件全部保留：

1. 已驗收資料集、資料契約及規格 SHA 不變。
2. baseline／評估器程式、環境與來源身分已凍結。
3. 手算、邊界與未來注入反例合成驗收通過。
4. 一次開發擬合與完整 validation 分母、排名、指標的獨立反讀通過，保留弱結果及稀疏切片。
5. validation 驗收、單一 P0 算法及精確實作，在 final refit 前固定。
6. 一次另存的 train＋validation final refit 及獨立計數驗收通過，第一筆 test 排名前固定產物 SHA。
7. 後續有明確的預留回溯測試執行要求。
8. 第一筆 test 排名前寫入排他的持久 usage identity／state。

**P0 gate 不是 C1 授權。** C1 仍需另凍結最終選模／refit／test 規格與實作，並有後續明確執行範圍。現有 C1 入口沒有 final refit 或 test 模式；交付完成、validation 改善或有利區間都不解鎖測試。本輪不建立 final／test 產物或 usage journal。

最終評估最多一個 logical run；技術失敗只允許完全相同資料、規格、程式、環境、final-fit 與名冊身分續跑，保留嘗試及部分證據，不重設 gate 或依成績改方法。這是未來規格必須保留的界線，不是本輪啟動續跑或測試的授權。

## 證據保存與 shop 內位置

| 位置 | 內容 |
| --- | --- |
| `shop-mysql-runtime/retailrocket_popularity_v1/development/` | P0 原模型、排名、指標、manifest／guard；原狀保留 |
| `shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/` | C1 支援／pair、session／query、bootstrap、oracle SQLite、資源與 guard；原狀保留 |
| `shop-mysql-runtime/backups/retailrocket_c1_p0_research_release_v1.zip` | 本輪結果證據包，逐成員清單與 SHA 隨包保存 |
| `shop-mysql-runtime/retailrocket_c1_p0_release_v1/` | 包外 manifest／guard 等控制證據 |
| `shop-mysql-runtime/verification/retailrocket-c1-p0-release-v1/` | 本輪原狀快照、保存工具測試、核對與交付日誌 |
| `reports/stage10/retailrocket_c1_p0_v1_research_release.json` | 可公開收據；實際成員數、大小、hash、反讀及範圍以此為準 |

ZIP 保存兩模型結果目錄、guard 引用的公開研究程式／測試／契約／報告、私人 guard／gate、本交付文件及保存工具。README 等導覽是當時脈絡快照，日後可更新；凍結研究與結果 bytes 不改寫。套件鎖檔若已被既有研究 guard 綁定，仍以凍結身分檢查。

原始來源、完整推薦資料集、執行環境與未收錄的私人驗收／成本證據是**封存包以外、仍在 shop 內的依賴**；清單保留其路徑、大小及 SHA，正常 `--verify` 仍核 live bytes。ZIP 不包含所有重建材料、Python 安裝環境、Git 歷史、MySQL 或憑證，不能單憑此包宣稱完整環境可還原。原始資料、逐 ID／模型／抽樣明細、SQLite 及 ZIP 保持 Git 忽略。

保存包與原資料位於同一 shop 磁碟，提供固定副本及完整性檢查，沒有建立異地備援。包外公開收據保存 ZIP SHA，避免自我參照；沒有推送或發布原始資料。

## 驗證與後續還原

```powershell
# 核 ZIP 全成員 CRC／SHA、包外控制檔及 shop 內凍結來源／依賴；不重跑研究。
.venv\Scripts\python.exe -B scripts\archive_retailrocket_c1_p0_v1.py --verify
# 只核保存包與公開收據；不代表包外資料／環境完整。
.venv\Scripts\python.exe -B scripts\archive_retailrocket_c1_p0_v1.py --verify-archive-only
# 既有結果入口只核已保存 bytes。
.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
.venv\Scripts\python.exe -B scripts\run_retailrocket_cooccurrence_v1.py --verify
```

保存工具不解壓、不重訓、不解析逐筆標籤；完整保存重入只驗證，部分產物停止並保留。首次空白命名空間才使用 `--archive`，不以刪除部分證據重播。現有 C1 產物建立後，不再使用要求空白真實目錄的舊規格凍結器作完成驗證。

日後還原先保留 ZIP 與包外收據，通過 archive-only 完整性檢查後，在 shop 內另建乾淨目錄，按安全相對路徑還原，不覆蓋目前結果。逐項補齊 manifest 所列包外依賴及相符環境，再執行完整驗證；hash 不符先處理來源／版本，不能重跑實驗冒充原證據。此輪沒有執行還原演練，完整逐成員讀回是保存驗收。

## 下一步

1. 以此交付與保存收據固定 C1／P0 v1，保留冷商品、稀疏小組及回溯界線；日常查看結果使用只讀驗證入口。
2. 若接續 Stage 11–13，先明確選定單一新候選與研究問題，再凍結新比較規格；揭露既有 validation 已曝光，保持完整母體／候選／分母，不回頭覆寫 v1 或挑組調參。本輪不指定或執行新模型。
3. 最終選模、train＋validation 重擬合與預留測試需獨立規格及驗收；有利結果不自動啟用。
4. Stage 4／5 仍待新資料，延遲提醒維持每日 10%；Dashboard 暫緩，API／前端尚未開始。

全專案狀態持續列於[專案進度](PROJECT_PROGRESS.md)與[README](../README.md)。
