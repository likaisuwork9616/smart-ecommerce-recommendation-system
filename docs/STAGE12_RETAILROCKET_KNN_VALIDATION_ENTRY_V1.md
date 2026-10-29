# Stage 12：K1 真實 validation 入口準備與凍結 v1

本輪依[比較規格](STAGE12_TEMPORAL_AVAILABILITY_AND_KNN_SPEC_V1.md)及[已驗收核心](STAGE12_RETAILROCKET_KNN_IMPLEMENTATION_V1.md)，實作來源 loader、完整獨立反讀與單次執行入口。正式合成案例、來源綁定與凍結收據見[入口驗收](../reports/stage12/retailrocket_session_knn_v1_validation_entry_acceptance.json)及[來源規格](../reports/stage12/retailrocket_session_knn_v1_validation_entry_specification.json)。[機器契約](contracts/retailrocket_session_knn_validation_entry_v1.json)補充本輪入口，不改舊核心或比較規則。

**本輪不跑真實 validation，也不重新盤點 train 成本。** 真實資料及對照 CSV／JSONL 只核檔案 bytes／SHA，不解析內容、不建 K1 索引、不產生排名、指標或 bootstrap。metadata 中的固定人數、原三臂指標與 train 成本沿用既有驗收收據，並非本輪重算。最終選模、train＋validation 重擬合與預留測試另行規劃，test 維持 locked。

## 來源與四臂對帳

新增 `retailrocket_session_knn_io.py` 固定資料夾與 schema，先篩 role，再解碼商品／targets。fit 僅取 train，history 可取同 session 的 warmup／train／validation 前綴；query 必須符合原 validation 標籤、成熟期與時間窗。訓練每個 session 集合、basket 次數與商品關係完整比對原 C1 lineage；所有 posting 支援與原 C1 support、上一輪 train-only 成本一致。

15 份直接輸入包含原資料 baskets／queries／catalog，P0 的 counts／rank／metric／slice／fit audit，C1 的 support／lineage／query／bootstrap／fit audit，以及 D1 的 query／fit audit。它們都必須存在於繼承的 SHA 綁定，不能在這輪把陌生檔案當成已驗收來源。另綁定全部歷史來源、實作／測試／oracle、版本環境、三臂 fit 身分、固定分母／切片及原聚合。

P0 原始三份逐 query 表同步讀取，再與 C1、D1 保存的 P0 值逐值核對；D1 中的 C1 值再核原 C1。四臂每筆 key、history／hash、target、候選與 reachable 分母、slice、模型身分一致，缺／多／重複／順序錯誤即停止。舊三臂排名和 binary64 指標照原值複製，沒有重擬合或重排對照模型。

## 完整獨立反讀

`retailrocket_session_knn_readback.py` 不引用 K1 production、loader 或 evaluator。它另讀原 CSV／JSONL，用 SQL DISTINCT 重建所有 train session-item，驗完整 sessions／postings／lineage／fit audit；另建 history，逐 query 核 current basket 與真正的 next basket target，避免僅信任 query 名冊。

每個 query 都掃過所有 train sessions，包括零交集 sessions；用 Fraction 重算完整正交集鄰居池、精確 top500、同分邊界及 hash。每個因果候選均對選中鄰居獨立加總票數，再排完整候選；不抽樣、不用 production 倒排找鄰居、不以舊 top10 補位捷徑取代完整集合。逐筆核全部巢狀輸出、三臂原值與獨立 Decimal／Fraction 指標，累計主／條件／固定切片與診斷，最後重播所有 2,000 次 visitor-cluster draws、分母與 K1−C1 reduction。

這條完整路徑可能很慢。上一輪 train 成本只能說明集合規模，**不能證明全量搜尋與全量 oracle 能在 6 小時內完成**。本輪只證明合成來源檔經同一入口可通過驗收，沒有真實 validation 耗時或效果結論；若未來超限，保留失敗證據，不能在 v1 暗改 k、抽樣、截歷史或重跑。

## 單次入口與保存

| 動作 | 行為 |
| --- | --- |
| `--prepare` | 先跑合成／守門測試，兩組正式檔案案例經單次入口與完整 oracle，核來源 bytes 後凍結；不呼叫真實 validation |
| `--verify` | 只核已凍結來源／產物、環境與 locked gates；不重算研究 |
| `--run-validation` | 留給後續明確要求執行的工作；固定真實來源，僅一個 train K1 索引、一次 validation／bootstrap、一次全量 oracle |

入口不接受來源、角色、k、窗口、抽樣、預算或 retry 參數，沒有 final／test 模式。未完成準備不可執行。實際 namespace 原子建立；started 在模型工作前保存。失敗、KeyboardInterrupt 或超限留下 failure 與全部部分證據，拒絕重跑／覆寫；完整成功後重入只核 SHA。任何不利或跨零結果仍如實保存，不自動選模或解鎖測試。

RSS 8 GiB、執行目錄 20 GiB、6 小時、剩餘磁碟 8 GiB／可用記憶體 4 GiB 下限沿用原規格。來源 hashing、資料列、輸出、主要 fit／query／bootstrap、oracle session／candidate 迴圈及 SQLite VM 有合作式檢查；排序前後有檢查。0.5 秒取樣不宣稱瞬時 OS 硬限制。主要索引離開 build 後釋放，再建獨立 SQL 索引。

本輪準備 guard 在 `shop-mysql-runtime/retailrocket_session_knn_validation_entry_v1/`；合成原始檔、執行輸出、SQL、測試日誌在 `shop-mysql-runtime/verification/retailrocket-session-knn-validation-entry-v1/`，均 Git 忽略。未來真實執行保留 `shop-mysql-runtime/retailrocket_session_knn_paired_v1/`；本輪必須保持該目錄不存在。公開只保存聚合驗收、來源 hash 與 scope，不提交資料／模型。

本輪可用的只讀檢查：

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_session_knn_v1.py --verify
```

合成測試命令：

```powershell
.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_session_knn_validation tests.test_retailrocket_session_knn_validation_entry -v
```

下一步依後續明確工作範圍決定是否啟動一次真實開發 validation，先沿用本輪來源／環境核對。最終選模、重擬合與預留測試依然需要另外規劃；Stage 4 每日 10% 提醒與 Dashboard 暫緩不變。
