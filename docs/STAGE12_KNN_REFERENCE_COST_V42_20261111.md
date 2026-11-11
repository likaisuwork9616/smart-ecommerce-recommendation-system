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
.venv/Scripts/python.exe -B -m scripts.diagnose_retailrocket_session_knn_reference_v42 --audit
```

## 真實來源重播結果

兩次暖機後的六對正式重播中，原版中位數 **2.258 秒**（1.872–2.786），加計時版 **2.164 秒**（1.896–2.320）。以下分項以六次加計時版計算。占比先按每次重播計算，再取中位數。各分項的中位數不必剛好加回總中位數。

| 分項 | config 中位數（秒） | model 中位數（秒） | model 占整段的中位數 |
| --- | ---: | ---: | ---: |
| 解碼、解析及建置 tuple | 0.018944 | 1.841055 | 84.52% |
| 文法驗證及結構統計 | 0.002489 | 0.306130 | 14.27% |
| SHA-256、reference 建立及登錄 | 0.000097 | 0.009122 | 0.42% |
| 每個 root 的其餘時間 | 0.000020 | 0.000034 | <0.01% |

兩個 root 外的權威描述符檢查與其餘外層工作，中位數分別為 0.000051 和 0.000050 秒。model 的 canonical 有 4,566,194 bytes、198,961 個節點，整個 model root 占建置時間的中位數 99.0%。下一步若要找出 `_decode` 內最慢的工作，可拆量字串掃描、陣列解析和 tuple 配置。

六對的加計時版減原版差為 +0.024、−0.126、−0.504、−0.150、−0.165、−0.036 秒，中位數 −0.138 秒。這是兩種重播條件的實測波動，無法據此把 −0.138 秒當成計時成本。V41 完整冷啟動所量的 2.510 秒仍是該次窗口的建置觀測值。

14 次建置重播產生 28 個 reference roots，全部與 V41 權威描述符一致並通過完整 late 核對。查詢與 fit 各 0 次，保留測試仍鎖定。`--audit` 已重新核對來源並從保存的區間重算摘要。

[原始計時區間、配對與摘要](../reports/stage12/retailrocket_session_knn_v42_reference_cost_20261111.json)
