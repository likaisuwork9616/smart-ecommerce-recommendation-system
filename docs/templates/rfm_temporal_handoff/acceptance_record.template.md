# RFM 跨期資料驗收紀錄範本

狀態：pending_data（範本；不是實際驗收）

複製到 `.runtime/rfm_temporal_handoffs/<handoff_id>/` 後填寫，保留個體與私有 digest 在本機。規則見[交接清單](README.md)；複製後須調整此連結為專案內的實際路徑。

| 欄位 | 待填內容 |
| --- | --- |
| handoff_id／版本／負責人 | pending_data |
| 來源／授權／擷取方法 | pending_data |
| T1、T2 對應來源與版本 | pending_data |
| 擷取時間／資料截止／時區 | pending_data |
| S2／T2／歷史覆蓋 | pending_data；不可把盤點查詢日期當已選定 T2 |
| 各檔路徑、schema、列數、SHA-256 | pending_data |
| 曾有的研究曝光及用途 | pending_data |
| 允許用途 | pending_data：回溯事件代理／歷史 as-of／未來結果，逐項判定 |

| 驗收項目 | 證據路徑 | 聚合核對結果 | 判定／缺口 |
| --- | --- | --- | --- |
| 兩期版本與來源可追溯 | pending_data | 未驗收 | pending_data |
| 全量訂單與控制總數 | pending_data | 未驗收 | pending_data |
| 顧客全集、鍵映射／合併／刪除 | pending_data | 未驗收 | pending_data |
| 事件／可見／修訂與歷史 as-of | pending_data | 未驗收 | pending_data |
| 完成水位、晚到／重開與對帳 | pending_data | 未驗收 | pending_data |
| 商品／付款鍵、金額與版本 | pending_data | 未驗收 | pending_data |
| 時區、窗口與未知／隔離政策 | pending_data | 未驗收 | pending_data |
| 曝光歷程與驗證角色 | pending_data | 未驗收 | pending_data |
| 依用途：退款／成本／成熟結果／處置對照 | pending_data | 未驗收 | pending_data；不適用需註明原因 |

尚未凍結的跨期設計：

- 固定切點或另行重估規則：待定，兩者不得混合挑選。
- 完整母體與同 ID 交集的分母、零活動／未知／隔離／新進／退出：待定。
- 各軸／組支援門檻、轉移與變化指標、跨期成功標準：待定；不自動沿用 G3 成功門檻。
- 若驗未來結果，H／C、成熟與右刪失規則：待定；不自動沿用 H60。
- 讀取／分析次數、私有 namespace、正式聚合路徑：待定。

最終判定：pending_data。未解決缺口、可允許用途與限制需逐一列出；沒有完成水位或第二來源證據，不得標成完整／通過，也不得用事件最大日期補填。
