# Stage 12 V40 原固定 48 筆比較

## 比較規格封存

| 項目 | 封存內容與核對結果 |
| --- | --- |
| 原固定樣本 | 48 筆原順序，帳本 2,115,696 bytes 與 SHA-256 已核對，原 15 個 binding 描述符一致 |
| 同窗口對照 | 依序執行原始 R 和 V39 候選的暖機，再以 RC／CR 交替跑六對。單一 worker、14 份新帳本，候選一 cold、六 hits |
| 成本與門檻 | 沿用 V31 的五項門檻。至少五對較快、節省比例中位數至少 5%、兩種順序的節省秒數中位數都正、含 cold 的七次候選總時間較短、primary 退步中位數至多 5% |
| 來源與發布 | 先重核 V39 的 165 項驗收，保留既有 2,101 個來源與 177 個方法描述符。新增入口及證據只追加。實測由獨立程序重建權威來源及核對 672 筆完整帳本紀錄，所有受追蹤程序停止後才封存 |
| 執行上限 | 單次監督窗口 1,800 秒，沿用 V5 資源限制。已有真實 request 即禁止重跑 |

本次封存讀取既有帳本和證據，真實執行 0 次。下一步以人工 48 筆跑同一入口，涵蓋原 loader、獨立發布及停態日誌。人工驗收提交後才執行真實窗口。

比較涵蓋完整入口，包含候選的 context 重用與冷啟動成本，無法從這個設計估出 typed comparator 的單獨效果。原 48 筆來自已檢視的 validation 工程樣本。保留測試仍鎖定。

```powershell
.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_compare_v40 --audit
```

[比較規格](../reports/stage12/retailrocket_session_knn_v40_compare_specification_20261111.json) · [封存收據](../reports/stage12/retailrocket_session_knn_v40_compare_seal_20261111.json)
