# Stage 12：來源驗證與初始化重複成本候選

## 已存證據盤點完成

本輪只重讀 V25 已保存證據與小型契約，不重新執行原 48 筆、不載入模型、不重算大型原始來源雜湊。已核對 **314 份已存執行證據、33,969,572 bytes**，重算四個 closure 邊界及七次 D／publisher 的來源與初始化事件。這是前輪已曝光 validation 的工程成本盤點，不是本輪新效能窗口，也不是目前大型來源重新驗證。

| 實測範圍 | 驗證次數 | descriptor 次數 | V25 實測 wall 秒 |
| --- | ---: | ---: | ---: |
| worker 前後與 publisher 前後完整 closure | 4 | 2384 | 160.580 |
| 七次 D 的建立前核對 | 7 | 105 | 9.028 |
| 七次 D 的鎖定後強制核對 | 7 | 105 | 8.822 |
| 獨立 publisher 開啟十四份帳本 | 14 | 210 | 17.208 |

完整 closure 的 160.580 秒占原 316.156 秒窗口 **50.79%**。上表 closure 與 binding 為分離的邊界；binding 已包含於各次入口及 publisher open，不能再加到原總窗口。

共觀測 **2,804 次 descriptor、596 個不同路徑身分、2,208 次重複核對**，logical bytes 合計 62,622,220,904。這不含未觀測的原 R binding、契約與參考門檻核對；原流程可推得七次 R 有 14 次 binding 核對／210 個 descriptor，但來源 wall 未分項，保留未知。成功 measure 流程有五次契約計算；其小型證據／參考門檻讀取也不能當成零成本。

### 內容相同仍有不同來源身分

596 個路徑中有 **36 組相同 bytes／SHA、109 個路徑**，相對每組保留一份多出 73 個路徑、每次 597,058,652 logical bytes。四次核對中，這些群組所有路徑的 descriptor wall 合計 15.876 秒，包含每組首份，**不是可省時間**。沒有檢查是否同一實體檔案或硬連結，也不因相同內容而移除任何路徑核對。

建立前核對避免以錯誤來源建立命名空間；鎖定後 `force=True` 核對攔截建立至上鎖間的變更；publisher 在不同程序獨立核對來源及帳本。這些邊界用途不同，不能用單一先前成功收據替代。

### 初始化重複工作

| 六次正式 D 觀測 | 中位數秒 | 最小～最大秒 |
| --- | ---: | ---: |
| 重新載入 counts／catalog 與原支援／時鐘檢查 | 2.956 | 2.808～3.174 |
| 複製、驗證及凍結 catalog／counts，建立排序與 fallback | 1.027 | 0.880～1.156 |
| setup 其餘工作（含第二次 first_times 排序等） | 0.087 | 0.081～0.124 |

原 `prepare_catalog` 已建立不可變 first_times tuple；`verify_selected` 隨後再次排序 catalog 時間。第二次排序沒有專屬計時，不能把整個 setup 其餘時間當其成本。觀測七次 D 都完整重建 context 與 catalog；固定流程另推得七次 R 也各建一次，合計十四次，兩種證據分開。

初始化直接讀取 item_counts（1,784,882 bytes）與 catalog（4,874,693 bytes），另外依賴 configuration、reconstruction receipt 的完整 support 與訓練時鐘。候選必須繫結完整依賴身分與方法版本，不能只用檔名、fit_id、mtime 或檔案大小當命中條件。逐筆查詢、對照串流、SQL 連線／TEMP 表、帳本與 writer 狀態仍各次獨立。

### 候選方向與待封存項目

優先評估同一受監督 worker 內的不可變初始化快照重用，及獨立的小候選 first_times 重排移除。來源 hash 快取／跨程序成功收據重用／按內容去重先不列可實作候選，因現有證據尚無來源不可寫入保證。下一小階段固定兩候選的身分鍵、生命周期、故障拒絕、獨立發布與未來公平比較條件；目前尚未封存候選規格。

本輪新增預測、效能窗口、模型 fit、完整 validation、bootstrap、保留測試皆為 0。覆蓋維持 **55／55 格、170 個可比較查詢、232 個歷史身分**；保留測試鎖定，`T_plan = null`。

操作：`.venv/Scripts/python.exe -B -m scripts.inventory_retailrocket_session_knn_reuse_v26 --inventory` 只產生一次性盤點，已有報告拒絕覆寫；查看既有結果請直接讀報告。

[盤點報告](../reports/stage12/retailrocket_session_knn_v26_reuse_inventory_20261109.json)
