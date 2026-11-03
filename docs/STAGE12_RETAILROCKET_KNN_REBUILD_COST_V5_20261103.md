# Stage 12：V5 新版完整獨立重建成本

2026-11-03 補量新監控下的完整獨立模型重建，保留 V1–V4 方法，**不啟動全量 query 反讀或預留測試**。15 項前置合成／程序測試全過後，在新的 30 分鐘窗口執行一次，正常退出 0。

## 實際結果

| 範圍 | 實測 | 包含與限制 |
| --- | ---: | --- |
| Supervisor 整個窗口 | 321.312 秒 | 臺北 14:45:54.073773→14:51:15.392535；Python 啟動、初末全名冊 SHA、完整重建、舊模型 receipt 比較與收尾 |
| 起始／最後來源 SHA | 42.171／29.138 秒 | 各核 482 份來源綁定；最後通過才產生完整結果 |
| 完整獨立重建 outer phase | 248.676 秒 | 七個直接檔初末 SHA、fresh DB、canonical reconstruct／derived index、完整性檢查、關閉後 DB SHA／封存及成本收據 |
| Canonical reconstruct | 214.406 秒 | 上列的內含分項；保留原 baskets SQL 與所有參考檔核對 |
| Canonical derived index | 2.586 秒 | V4 直接沿用 V2 build_index；上列的內含分項 |
| 新 DB setup 至 integrity／close | 243.862 秒 | 與上述計時重疊；不含初末直接檔 SHA、關閉後 DB SHA／seal |
| 舊模型 receipt 比較 | 0.238 秒 | 完整 fit_audit、support、model_method exact 相同 |

各層計時互有包含，**不能相加**。SQL 邊界以固定 statement 的薄 facade 觀察，原 SQL 及參數照原路徑執行；階段收據 fsync 與節流監控開銷保留在成本中。Cache、系統狀態及計時範圍未與歷史 840.406 秒控制一致，因此不報同條件加速倍率，也不改寫歷史報告。

## 核對內容與模型身分

[重建成本工具](../scripts/retailrocket_session_knn_rebuild_cost_v5.py) 在新目錄呼叫 frozen `reconstruct` 與 V4／V2 `build_index`。七個直接檔為原 baskets、C1 support／train lineage、K1 sessions／postings／train lineage／fit_audit，共 **518,646,822 bytes**，是 482 份綁定的子集。

保留原 SQL `h` 的 warmup／train／validation history 及 `m` 的 train distinct session-item，完整核對 support、sessions、postings、兩份 lineage 與 fit_audit 至 EOF，並執行 SQLite integrity_check。Reserved/test role 在解析 items 前排除；全檔 bytes SHA 不代表評估預留內容。原模型、原主要輸出及 partial namespace 不修改或續接。

| 模型量 | 實際值 |
| --- | ---: |
| Train sessions | 1,180,256 |
| Distinct session-item memberships | 1,587,436 |
| Support items | 198,946 |
| 最大 session／posting | 389／1,736 |
| 新獨立 DB | 475,103,232 bytes |

fit_id 為 `ceb483631be343e3646d1a367325e53a4a0e2c937405686095d700efbeb1c56a`，與原輸出及舊獨立模型 receipt 相同。這是 **1 次新的獨立工程重建**，不是主要模型重訓；0 新主要 fit、validation query 排名、bootstrap、final、refit 或 test。新舊 DB bytes 沒有在本步作同一性結論。

## 監控、保存與驗收

[外部窗口監控](../scripts/retailrocket_session_knn_cost_window_v5.py) 使用獨立絕對期限、原子停止／退出收據，追蹤觀測到的 PID／create_time；即使 top worker 先退出，也清理已觀測的子程序。它是抽樣身分追蹤，不是 OS Job Object 的完整程序樹保證。本次記錄 **3 個程序身分，退出後均不存活**。

原期限為臺北 15:15:54.073773，實際提早正常完成，未延長或重設。停止門檻為 RSS 8 GiB、執行目錄 20 GiB、可用記憶體至少 4 GiB／磁碟至少 8 GiB；本次未觸發。抽樣程序樹加 supervisor RSS 峰值 **807,813,120 bytes**，執行目錄峰值 **477,387,471 bytes**。既有輸入／模型不算入本次目錄；canonical SQLite 設定 temp_store=0、journal_mode=delete、synchronous=2，OS temp 生命期與大小未完整盤點，不能當全量資源上界。

退出後另外唯讀核新 DB、source_binding 與 reconstruction seal 的大小／SHA，確認無 WAL／SHM／journal，並逐一要求四份 outer phase 收據完成、結果與實體收據一致。這些退出後核對不回填工作窗口或冒稱延長實驗。

合成驗收為重建 7＋外部監控 8，共 **15 項全過**，入口整段 **8.180 秒**，0 failure／error／skip。包含 V2 全表差分、六類參考檔異動、半成品／停止保存、真程序 deadline、top worker 先退後的已觀測子程序清理及 PID 重用防護。操作命令見[測試導覽](../tests/README.md)；原始資料、DB、support map 與逐筆內容留在 Git 忽略目錄。

## 下一步

完整重建成本缺口已補。下一步先補 **同一 query 的聯合工作量尾端選樣／實際配對成本**，再量完整筆數、真實 payload 形狀的 source-backed ledger 工程成本；這種成本代理不把未驗主輸出升級為完整已驗 ledger。全量 query／global／原 2,000 draws 的正式獨立驗收尚未執行，**完整 T_plan 仍空值，全量不跑、K1−C1 無正式結論、預留測試 locked**。每日 10% 延遲提醒與 Dashboard 暫緩維持。

依據：[15 項前置驗收](../reports/stage12/retailrocket_session_knn_v5_rebuild_acceptance_20261103.json)、[真實重建成本及保存證據](../reports/stage12/retailrocket_session_knn_v5_rebuild_cost_20261103.json)、[前步 payload／來源量測](STAGE12_RETAILROCKET_KNN_PAYLOAD_SOURCE_RECOVERY_V4_20261103.md)。
