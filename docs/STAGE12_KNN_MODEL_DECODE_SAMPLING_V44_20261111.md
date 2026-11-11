# Stage 12 V44 Model 解碼低頻抽樣

V43 逐次計時的配對差中位數為 +0.737 秒。V44 用低頻計時重測字串掃描與陣列解析的相對成本。每 64 個 256 字元區塊為一層，每層以固定種子隨機選一個區塊，依字串起點或陣列結束位置判定是否計時。尾層按實際區塊數加權。每個區塊的計時和呼叫數依抽中機率反推全量。

| 項目 | 方法與驗收 |
| --- | --- |
| 字串掃描與 tuple | 計時選中區塊的原 `_string` 和 `tuple`，在區塊邊界切換函式。字串跨過區塊時依起點歸屬 |
| 陣列解析 | 用同一對原版總時間扣除抽樣估計的字串、tuple 及單次 UTF-8 時間。餘額包含標記判斷、堆疊與元素加入等原解析迴圈工作 |
| 計時開銷 | 每臂一暖機，八對交替執行原版與抽樣版。配對淨差涵蓋區塊判斷、計時和當時環境波動。另以相鄰讀錶間隔的中位數試算排名敏感度 |
| 工具驗證 | 4 項測試通過，驗證區塊起點、跨越區塊、尾層權重、字串及錯誤處理一致性，以及配對估算 |
| 人工開銷校準 | 人工 canonical 1,004,462 bytes，18 次輸出一致。八對原版／抽樣版中位數 0.402／0.440 秒。配對淨差中位數 +52.4 毫秒（+14.7%），範圍 −115.0 至 +142.0 毫秒，6／8 對抽樣版較慢 |

人工校準的相鄰讀錶中位數為 100 ns。真實重測會核對 V43 的 SHA-256、完整 tuple 結構與呼叫數，再用真實窗口自己的配對差估計開銷。

```powershell
.venv/Scripts/python.exe -B -m unittest -v tests.test_retailrocket_session_knn_decode_v44
.venv/Scripts/python.exe -B -m scripts.diagnose_retailrocket_session_knn_decode_v44 --audit calibration
.venv/Scripts/python.exe -B -m scripts.diagnose_retailrocket_session_knn_decode_v44 --measure model
```

[人工校準報告](../reports/stage12/retailrocket_session_knn_v44_decode_calibration_20261111.json)
