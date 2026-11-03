# Stage 12：V5 聯合工作量尾端與固定配對成本

本步補同一個 query 的聯合工作量，保留原 V1–V4 計算方法。8 項合成測試通過後，在新 30 分鐘工程窗口完成全 validation 結構名冊及事前固定 48 筆配對；**全量 K1 反讀沒有啟動，預留測試 locked，K1−C1 無正式結論**。

## 選樣與科學界線

[聯合選樣工具](../scripts/retailrocket_session_knn_joint_cost_v5.py) 完整讀取 166,897 個 validation history，從已完成的 V5 獨立模型唯讀 immutable 查完整正交集。四個維度依序為 eligible neighbors、largest-500 session sizes 的 vote memberships 上界、嚴格因果 catalog 候選數、history＋6×selected-neighbor slots 的可變 scalar 數。沒有執行相似度選鄰居／投票，也沒有用 targets 或原推薦效果選樣。

各維度以完整母體 nearest-rank p90 分高低（正值達門檻為高、零固定為低、平手同層），形成 16 個 masks。每個非空層按四個預定聯合方向，以較弱維度的 empirical rank、其和及 key SHA 固定排序，最多選 4 筆，不跨層補名額。完整名冊完成後才封存樣本；原 64 probes 只核身分及事後重疊，不影響新選樣。

| 項目 | 實際結果 |
| --- | --- |
| 完整結構母體 | 166,897，全部 EOF |
| p90：鄰居／投票上界 | 538／2,339 |
| p90：候選／可變 scalar slots | 220,665／3,001 |
| 非空聯合層／凍結樣本 | 12／48（每層 4 筆） |
| 與前 64 筆重疊 | 2；兩輪合計 110 個不同的已驗工程 query |
| 結構名冊 | 80,745,083 bytes，完整 SHA 於退出後再核 |

投票量上界沒有選出真正鄰居，scalar slots 也不是 payload bytes；這些是結構代理。有限定向樣本不保證涵蓋未取樣的實際投票、序列化尾端、最慢時間或每個邊際最大值。七路原檔抽取在選樣封存後才解析既有輸出以對齊／複製原 bytes，不是全量獨立重新預測。

## 實際成本

窗口為臺北 **2026-11-03 14:53:39.691468→15:06:06.076286**，期限原為 15:23:39.691468。總計 **746.391 秒、正常退出 0**，初末 489 份來源綁定一致；新模型以唯讀使用，0 新主要 fit／validation／bootstrap。

| 階段 | 秒數 | 完成內容 |
| --- | ---: | --- |
| 初末全來源 SHA | 36.819／72.597 | 各核 489 份，包含新建封存 DB |
| Context 準備 | 2.929 | 固定 P0 counts、catalog 與 model support |
| 全窗結構名冊／封存選樣 | 454.289 | 同一 query 的四維工作量至 EOF，無 profiler |
| 七路原 bytes index／抽取 | 162.509 | 原始 ordinal 與結構名冊逐項相同，樣本／catalog／counts 複本核原綁定 |
| 48 筆四臂及 checkpoint | 13.606 | 新 V4 獨立排名、current／next／targets／原控制值、精確 Decimal／binary delta、完整巢狀 K1、EOF 與保存 |

所選樣本最大實際 SQL overlap groups **7,695**、selected-vote memberships **15,111**、vote scale **378 bits**；不是完整母體的實際 vote 上界。48 筆提交成 1 chunk，共 **2,115,696 bytes**；單列最大 **48,100 bytes**，chunk commit **0.126572 秒**另列。退出後重新核 CP chain、queries seal、每列 key、原 ordinal 對應及實體串接 payload 總 SHA，沒有 candidate 或正式 acceptance。

## 工時情境與保存成本

以每層母體數乘該層觀測最大 verify＋append_without_commit，得到 **17,176.067 秒（4.771 小時）**。若只將此分量乘提案兩倍餘裕，已是 **9.542 小時**；尚未加重建、來源綁定／抽取、chunk commit、global、draws、恢復與收尾。

這是**條件工程情境，不是全量實測、統計上界或完成保證**。Rank 是 verification 的內含分項，不能再相加。原 CP 每秒可保存一次 budget.json；這類週期 metadata fsync 可能落在某筆 append，逐層 sample max 情境會保守重複計入。原觀測完整保留，後續另量保存事件分項，不直接刪掉高值或據此改寫本次成本。

本次抽樣程序樹加 supervisor RSS 峰值 **237,355,008 bytes**、目錄 **96,343,994 bytes**；3 個記錄身分退出後均停止。這些不是完整生命期、OS temp 或全量資源上界。監督窗口前少量 metadata／方法 preflight，以及退出後唯讀證據稽核不計入窗口；內部階段與整段互有包含，不重複加總。

## 驗收、公開範圍與下一步

8 項合成測試全過，入口整段 **1.684 秒**，0 failure／error／skip。涵蓋同一筆 joint corner、分位數平手、零工作量、role-first／不讀 target、固定名冊 EOF／中斷／禁止覆寫，以及接 V4 真正人工四臂與實體 ledger。這些不是新未知資料的推薦成績。

原 key／所選 ordinals／targets／推薦／逐筆 hash、完整結構名冊及 payload 均保留在 Git 忽略路徑，公開只列聚合工作量、時間、大小與檔案 SHA。

下一步補完整筆數、真實原 payload 形狀的工程 ledger 建置／global／恢復／新 self-reference draws，並量 CP 週期 budget 保存分項，再做整體成本決策。工程 source-backed ledger 不把原未驗主輸出升級為完整已驗 ledger；原真實 global／2,000 draws 的科學驗收尚未做。**完整 T_plan 空值，全量不跑、test locked**；每日 10% 提醒與 Dashboard 暫緩維持。

依據：[8 項合成驗收](../reports/stage12/retailrocket_session_knn_v5_joint_acceptance_20261103.json)、[聯合尾端實測與保存證據](../reports/stage12/retailrocket_session_knn_v5_joint_cost_20261103.json)、[新版完整重建](STAGE12_RETAILROCKET_KNN_REBUILD_COST_V5_20261103.md)。
