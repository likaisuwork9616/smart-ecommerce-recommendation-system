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

## 新入口人工驗收

| 項目 | 實際結果 |
| --- | --- |
| 新入口測試 | 9／9 項通過，涵蓋 6 項封存要求，無失敗、錯誤或跳過。測試與證據彙整 76.751 秒 |
| 實際執行 | 三個獨立 interpreter 走共用的 pipeline、worker 和 publisher 入口，使用正式 loader 讀取人工資料。14 份新帳本，各 48 筆，完整核對 672 筆 |
| 獨立發布 | worker 退出後，publisher 以原方法獨立重建兩個 typed roots、開啟並核對 14 份帳本。人工窗口四次全來源查核共用 224 個描述符，方法 183 個，binding 27 個 |
| 停態與拒絕測試 | 9 個受追蹤程序退出。停態後追加日誌、竄改 typed policy、更動 request 範圍及在有舊 request 時另開窗口皆被拒絕。已驗證唯讀重核 |

人工來源和真實 closure 分開計數。入口驗收階段真實資料執行 0 次。以下指令可重核入口驗收；真實窗口已使用同一入口的 `--measure` 執行一次。

```powershell
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_compare_v40 --audit
```

已有完成的結果時使用真實入口 `--audit`。若程序全數退出但結果尚未寫出，`--release` 只讀同一窗口並在核對成功後寫出報告。

[入口驗收收據](../reports/stage12/retailrocket_session_knn_v40_compare_acceptance_20261111.json) · [驗收封存](../reports/stage12/retailrocket_session_knn_v40_compare_acceptance_seal_20261111.json)

## 原固定 48 筆真實比較

**V39 候選不採用。** 六對中三對較快，完整入口配對節省中位數為 −0.237%。含兩臂暖機的七次總時間為 R 75.532 秒、候選 83.370 秒，候選多用 7.838 秒。單計第一次入口，R 用 14.125 秒，候選冷啟動用 20.119 秒。

| 正式配對 | 順序 | 原始 R（秒） | V39 候選（秒） | 完整入口節省 | primary 退步 |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | RC | 9.573 | 11.884 | −24.146% | +20.451% |
| 2 | CR | 11.010 | 11.163 | −1.396% | +6.015% |
| 3 | RC | 10.269 | 9.657 | +5.959% | −5.180% |
| 4 | CR | 9.738 | 9.969 | −2.375% | −1.562% |
| 5 | RC | 10.160 | 10.017 | +1.406% | −6.082% |
| 6 | CR | 10.658 | 10.560 | +0.922% | −9.948% |

節省為正表示候選的完整入口較快，primary 退步為負表示候選的 primary 較快。門檻以報告中的原始精度計算。

| 封存採用門檻 | 實測 | 判定 |
| --- | --- | --- |
| 至少 5／6 對較快 | 3／6 | 未通過 |
| 完整入口節省中位數至少 5% | −0.237% | 未通過 |
| RC、CR 的節省秒數中位數皆為正 | RC +0.143 秒，CR −0.154 秒 | 未通過 |
| 含冷啟動的七次候選總時間較短 | 候選 83.370 秒，R 75.532 秒 | 未通過 |
| primary 退步中位數至多 5% | −3.371% | 通過 |

| 窗口與成本 | 實際結果 |
| --- | --- |
| 完整監督窗口 | 422.359 秒，worker 285.896 秒、之後的獨立 publisher 131.816 秒，9 個受追蹤程序全數退出 |
| 原始科學紀錄 | 14 份新帳本，672 筆完整紀錄、查詢順序與 SQL 工作量核對通過。獨立 publisher 開啟 14 份帳本 |
| 完整來源核對 | 2,445 個描述符、每次 12,300,531,373 邏輯 bytes，前後共四次完整查核。原 15 個 binding 保留，183 個方法描述符涵蓋新入口 |
| 候選 cold 分項 | `cache.cold_build` 10.751 秒，其中建兩個 typed references 3.373 秒，late config／model 比較 0.002／0.762 秒。這三段包含在 cold 內 |
| typed 與快照 | 候選 1 個 cold、6 個 hit、15 次完整快照指紋。獨立 publisher 自行重建並核對兩個 roots，該 span 6.071 秒，計在 publisher 時間內 |
| 負載觀測 | 1,279 筆樣本，37 個估計缺口，最大取樣間隔 1.429 秒，最低可用記憶體 13.976 GiB |
| 停態封存 | 完整封存 332 個證據檔，唯讀重核成功，沒有重跑查詢 |

同窗口對照為原始 R，因此本輪衡量整套候選的入口時間。若後續要量 typed 改動本身，需以原 C1-S1 與 V39 在同一窗口另行配對。這輪只用已檢視的 validation 樣本，新增 fit／bootstrap／保留測試均為 0。完整 K1 validation 仍待驗收，保留測試仍鎖定。

```powershell
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_compare_v40 --audit
```

[真實比較結果與停態證據清單](../reports/stage12/retailrocket_session_knn_v40_compare_result_20261111.json)
