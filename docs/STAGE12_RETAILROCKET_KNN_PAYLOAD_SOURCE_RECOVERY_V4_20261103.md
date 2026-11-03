# Stage 12：V4 真實 payload、來源定位與子集恢復成本

2026-11-03 先完成 V4 逐筆優化的 39 項等價／故障驗收與公平成本比較，並提交推送 `aad879ac116031ea2f266db140010ae9ada231a4`，才執行本步。本步補量真實 bytes 與來源定位、64 筆已驗子集的程序恢復；全量仍關閉，K1−C1 沒有正式結論，預留測試 locked。

## 方法與守門

新增三個獨立工具：[來源索引](../scripts/retailrocket_session_knn_sources_v4.py)、[payload 與檔頭掃描](../scripts/retailrocket_session_knn_payload_v4.py)、[來源成本協調](../scripts/retailrocket_session_knn_source_cost_v4.py)。sources 12、payload 10、source_cost 6，共 **28 項合成測試通過**，實際 5.286 秒、0 failure／error／skip；測試與方法 SHA 見[工具驗收報告](../reports/stage12/retailrocket_session_knn_v4_source_tools_acceptance_20261103.json)。前步 V1／V2／V3／V4 配對科學方法不改。

單一新窗口在臺北 **14:22:41.676501** 開始，原絕對期限 **14:52:41.676501**；實際 **14:36:34.649174** 觀察主 worker 正常退出 0，用時 **832.985 秒**。外部 supervisor 監控子程序樹、期限與資源；恢復程序沿用同一絕對期限與原預算，包含停機牆鐘，不另開計時額度。

原 464 項綁定加本步工具／驗收／helper 等共 **475 份來源綁定**，前後核對一致（43.051／45.681 秒）；獨立索引的七路來源 bytes／SHA 再與該事前綁定比對。原封存 SQL 模型以唯讀 immutable、TEMP MEMORY 使用，沒有新版完整重建、主要 fit／validation／真實 bootstrap。六份 gate 仍 locked。來源 CSV 先按 role 排除，再處理 validation 欄位；完整來源 bytes 雜湊不等於解碼或評估預留測試內容。

## 真實原 bytes 與來源定位

來源為 dataset query、P0 rank／metrics／slices、C1、D1、K1，共七路。二進位實體列保留 LF／CRLF／CR、跨 block UTF-8 及 CSV 多行欄位原 bytes；offset 由實際交付 parser 的 bytes 累計，不以文字模式 tell 推估。索引每 64 筆及事前固定切點、固定樣本／前一筆設錨點，保存來源身分、列 spans／SHA、CSV header、EOF 與原 bytes 樣本，原子封存 manifest。

| 工作 | 實際結果 |
| --- | --- |
| 索引建置 | 124.904 秒；166,897 validation keys 七路對齊至 EOF，2,740 錨點 |
| 七路來源總 bytes | 3,024,512,921；僅來源身分及對齊，沒有全量重算預測 |
| 固定 64 筆原始列 | 七路合計 1,753,845 bytes（不含另存 header）；直接 copy 原 bytes，不經 DictWriter／JSON 重寫 |
| 六個固定位置 | 0、41,724、83,448、125,172、166,896、166,897（EOF）；每個 next key／原 bytes 或 EOF 都一致 |
| 額外非錨點 | 83,465；回放 10 筆 validation records 後，下一筆七路原 bytes 與從檔頭讀取一致 |

固定位置索引整段 **12.856–13.865 秒**，包含每次全七路來源 SHA、索引／樣本 SHA、全部 2,740 錨點與 EOF 邊界驗證；其中實際 seek 約 **0.0036–0.0059 秒**。檔頭讀取整段 **0.012–106.706 秒**，不含來源 SHA；兩種計時範圍不同且 cache 狀態未控制，**不能直接相除稱為等範圍加速**。

非錨點另量來源 SHA **11.713 秒**、錨點／EOF **3.305 秒**、seek **0.011904 秒**；檔頭掃描 **65.170 秒**。這是一個額外位置觀測，六個固定位置本來就有錨點，不能視為任意恢復位置成本上界。這些都是 source-only 位置；來源 ordinal 不代表已驗 ledger 的完整前綴。

## Payload 大小

以下計數都含實體列結尾，分位數使用 nearest rank。大小工具不解碼 JSON 值，不自行證明 caller 傳入的來源或科學正確性。

| 來源 | 列數 | 總 bytes | p50 | p90 | p95 | p99 | 最大 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 原 K1 主輸出，尚未全量獨立驗收 | 166,897 | 2,294,757,672 | 7,614 | 42,477 | 43,449 | 44,111 | 47,499 |
| 固定 64 筆已驗四臂 ledger | 64 | 1,509,417 | 11,960 | 46,178 | 46,837 | 48,100 | 48,100 |

原主輸出實體列掃描 **18.708 秒**。子集 ledger 的不中斷參考驗算整段 **12.891 秒**，產生一個 payload chunk；科學 bytes 與前步 benchmark 相同。兩列的輸出格式／範圍不同，64 筆也不是隨機母體樣本；不能依其平均值推定全量 ledger 大小或用原主輸出代替已驗 ledger。前輪人工約 577 MB 仍是人工代理，沒有改寫成真實 payload 上界。

## 真程序中斷與恢復

在新的 64 筆已驗 ledger namespace，宣告第 16 筆手動提前保存、完成第 20 筆後 `os._exit(9)`。這個額外保存邊界只用於故障量測；預設仍為每 64 筆／120 秒保存，沒有以這次提前保存成本外推正常工時。

| 檢查 | 實際結果 |
| --- | --- |
| 崩潰前 | 20 筆已核對；16 筆已提交、4 筆仍在 pending 尾段，程序實際退出碼 9 |
| 新程序恢復 | SHA 鏈只承認 16 筆，重算其餘 48 筆，正常退出 0；未提交尾段保留作證據 |
| 科學結果／保存 | 最終 64 筆與不中斷參考及前步 benchmark 相同；原已提交 payload 與 orphan 尾段 bytes 未變 |
| 來源定位 | 另核下一個所選 query 的原來源位置／原 bytes；這個原 ordinal 不是 16 筆 ledger 的全量已驗前綴 |
| 完整故障與恢復成本 | **42.550 秒**，以 parent `phases.true_verified_subset_process_restart.seconds` 為準，含程序啟動、崩潰、recover、來源核對、48 筆重算、proof 與保存 |
| 新程序內部分項 | 來源定位 15.773 秒；checkpoint／所選列恢復 14.763 秒，內含前綴回放 0.080 秒；child timer 30.536 秒在 digest／receipt 前取樣，只供分項 |

內部分項已包含在整段時間，不能重複相加。64 個獨立工程樣本共做 **132 次驗算＝golden 64＋故障前 20＋恢復 48**，不是新增 132 個 validation 樣本。這是實際程序崩潰，不是物理斷電或重開機驗收。

退出後以 PID 與 create_time 唯讀核對 **3 個記錄程序身分均不存活**，可讀程序清單中無此量測模組；golden 單 chunk 的大小／SHA 與統計一致。另直接串接恢復後兩個已提交 payload 檔，64 列／1,509,417 bytes 與 golden 檔逐位元組相同；這項退出後保存核對另存收據，不計入上述工程窗口／恢復計時。兩個子集 run 的原期限／預算、64 筆 expected queries 及 64／120 保存設定未變，沒有產生正式 acceptance。原 V1 partial、923 筆歷史觀測與先前 namespace 都未續接。

## 資源、保存與剩餘工作

抽樣程序樹加 supervisor RSS 峰值 **287,133,696 bytes（273.832 MiB）**，本次執行目錄峰值 **17,835,175 bytes**。資源停止門檻為 RSS 8 GiB、目錄 20 GiB、可用記憶體至少 4 GiB／磁碟至少 8 GiB；本次未觸發停止。抽樣峰值不是整台機器、既有來源／模型或未來全量的資源上界。

聚合報告保存來源／階段／退出與恢復收據的 SHA；原資料、逐筆 keys、所選 ordinals、next-frame bytes、模型、程序身分與 runtime helper 均留在 Git 忽略路徑。只讀報告即可查看成本，不需重跑；合成工具的操作指令見[測試導覽](../tests/README.md)。成本函式需要由呼叫端提供凍結來源、原 gates、絕對期限及外部 supervisor，本步沒有新增真實全量 CLI。

**全量維持關閉，完整 T_plan 空值。** 尚未完成真實 166,897 筆已驗 ledger 的完整回放／恢復、真實全域與原 2,000 draws 驗收、新版完整重建計時，以及聯合 SQL 工作量尾端與完整 payload 成本覆蓋。後續先規劃並補這些成本缺口，再更新全量決策；本步沒有最終選模、重擬合或預留測試，K1−C1 尚無正式結論。延遲每日 10% 預算與 Dashboard 暫緩不變。

實際數值與證據清單見[真實量測報告](../reports/stage12/retailrocket_session_knn_v4_payload_source_cost_20261103.json)；前步比較見[V4 配對優化](STAGE12_RETAILROCKET_KNN_PAIR_OPTIMIZATION_V4_20261103.md)。
