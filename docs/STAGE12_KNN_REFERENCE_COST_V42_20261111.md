# Stage 12 V42 V39 reference 建置成本

V41 在原固定 48 筆的冷啟動中量到 reference 建置 2.509826 秒。V42 單獨重播 V39 worker 的同一計時區間，分開量 config 和 model 的解碼、文法驗證、reference 封裝及其餘時間。

| 項目 | 驗證結果或計時方式 |
| --- | --- |
| 綁定來源 | 已核對 V41 報告與原 config、model 來源的 SHA-256。重播要求每次產生的 canonical bytes 長度、SHA-256 和 reference 結構統計都與 V41 相符 |
| 重播邊界 | 在計時外重做四次早期 canonical 比對。計時沿用 V39 的整段 `buffer_root` 建置邊界。計時後執行原兩個完整 late 比較 |
| 分項 | `_decode` 包含 UTF-8 解碼、解析、tuple 建置。`_grammar` 驗證文法並計算統計。`_reference` 含 SHA-256、reference 建立及登錄。其餘時間列在外層扣除分項後的餘額 |
| 順序 | 原版、加計時版各暖機一次，再交替跑六對。保留原始區間與配對差，以檢查計時的影響 |
| 人工測試 | 3／3 通過。兩版產生相同權威描述符及 late 核對結果，分項可加回總時間，越界及錯誤配對順序會被拒絕 |

此診斷重播兩個來源 root 的建置，省略完整 K1 入口的載入、prepare 和原 48 筆查詢。重播分項反映本輪執行環境，V41 的單次冷啟動觀測另保留。

```powershell
.venv/Scripts/python.exe -B -m unittest -v tests.test_retailrocket_session_knn_reference_v42
.venv/Scripts/python.exe -B -m scripts.diagnose_retailrocket_session_knn_reference_v42 --measure
```
