# Stage 12 V45 字元檢查與 scanstring 拆量

V45 沿用 V44 的 256 字元區塊、每層 64 個區塊及原抽樣種子。每次以相同來源的原版和抽樣版配對量完整解碼。選中的 `_string` 進入和回傳時讀錶，並在原 `scanstring` 呼叫前後讀錶。每個區塊的字串呼叫數逐一與 V44 對回。

| 分項 | 計時邊界 |
| --- | --- |
| 字元檢查 | 從呼叫 `_string` 到呼叫 `scanstring` 前，包括逐字掃描、escape 檢查和 Python 函式進入 |
| `scanstring` | 呼叫前至回傳後，包括原函式查找、參數傳遞及建立字串 |
| 邊界核對與回傳 | 從 `scanstring` 完成到 `_string` 回傳至計時器，包括結尾位置核對與計時版額外時間戳的回傳 |
| 完整解碼 | 每臂一暖機，八對交替執行。保留原版與抽樣版各自的區間與逐對淨差 |

5 項測試通過，涵蓋字串值與結束位置、原有錯誤處理、三段計時、跨區塊取樣一致性、加權與時間帳。人工校準沿用 V44 的 1,004,462 bytes，18 次 tuple 結構一致。八對原版與抽樣版中位數分別為 0.463 與 0.523 秒，逐對淨差中位數為 **+33.0 毫秒（+7.35%）**，範圍 −28.0 至 +155.7 毫秒，6／8 對抽樣版較慢。相鄰讀錶間隔中位數為 100 ns。

```powershell
.venv/Scripts/python.exe -B -m unittest -v tests.test_retailrocket_session_knn_string_v45
.venv/Scripts/python.exe -B -m scripts.diagnose_retailrocket_session_knn_string_v45 --audit calibration
.venv/Scripts/python.exe -B -m scripts.diagnose_retailrocket_session_knn_string_v45 --measure model
```

[人工校準報告](../reports/stage12/retailrocket_session_knn_v45_string_calibration_20261111.json)
