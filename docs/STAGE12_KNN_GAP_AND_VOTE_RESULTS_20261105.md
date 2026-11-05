# Stage 12｜低鄰居補測與投票比較

這一輪分別回答兩個問題。原 48 筆沒有涵蓋的 0–99 鄰居帶，每筆核對需要多久？原 48 筆投票階段量到的成本，能否靠一項改動降低？兩組樣本各自保留參考 ledger。每個階段的工具、結果與執行上限分開記錄。[補樣規格](STAGE12_KNN_GAP_SAMPLING_V7_20261105.md) · [公平比較規格](STAGE12_KNN_SQL_VOTE_ASSESSMENT_V7_20261105.md)

| 階段 | 實際進度 |
| --- | --- |
| 補樣工具 | 36 項合成／回歸測試通過，8.726 秒。正式選樣與排名到此步均為 0 筆 |

補樣器先按封存 salt 取各格最小兩筆，再用完整排序獨立重算；選樣封存後才抽取七路原始列。測試涵蓋歷史 keys 排除、最小格與短缺、ordinal／SHA 不符、兩次四臂精確核對、保存、期限與恢復。[工具入口](../scripts/run_retailrocket_session_knn_gap_v7.py) · [36 項驗收](../reports/stage12/retailrocket_session_knn_v7_gap_acceptance_20261105.json)

從專案根目錄使用 `.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_gap_v7`。參數 `--acceptance` 執行合成測試，`--measure` 實際啟動 34 筆的受監督窗口，`--publish <私有窗口目錄>` 可唯讀復核已發布結果。日常查閱使用本頁連結的聚合報告。
