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

優先評估同一受監督 worker 內的不可變初始化快照重用，及獨立的小候選 first_times 重排移除。來源 hash 快取／跨程序成功收據重用／按內容去重先不列可實作候選，因現有證據尚無來源不可寫入保證。下一小階段固定兩候選的身分鍵、生命周期、故障拒絕、獨立發布與未來公平比較條件；盤點階段尚未封存候選規格；後續封存結果如下。

本輪新增預測、效能窗口、模型 fit、完整 validation、bootstrap、保留測試皆為 0。覆蓋維持 **55／55 格、170 個可比較查詢、232 個歷史身分**；保留測試鎖定，`T_plan = null`。

操作：`.venv/Scripts/python.exe -B -m scripts.inventory_retailrocket_session_knn_reuse_v26 --inventory` 只產生一次性盤點，已有報告拒絕覆寫；查看既有結果請直接讀報告。

[盤點報告](../reports/stage12/retailrocket_session_knn_v26_reuse_inventory_20261109.json)

## 改善候選規格封存完成

兩項候選的範圍、不可變身分鍵、生命週期、失敗處理及未來驗收／公平比較條件均已封存。規格 **158,209 bytes**，SHA-256 **`5d3bad04dcdead2d86201636f11194de00d18a3ddab57d6bf6607b7e27206f8d`**；已執行封存工具的 `--audit`，規格／方法／盤點與已存 request 指紋相符。這是規格完整性核對，**不是候選工具合成驗收**；候選尚未實作，已執行候選測試與真實窗口皆為 0。

| 順序／候選 | 固定變更 | 不可混入的工作 |
| --- | --- | --- |
| 1：C1_worker_context_snapshot | 同一受監督 worker 內重用唯讀 counts／catalog／FrozenCatalog；一次 cold build、六次 hit | 不快取來源核對、查詢或對照串流；每次仍建立 SQL 連線、TEMP 狀態與 fresh 帳本；保留原額外 first_times 排序 |
| 2：C2_reuse_prepared_first_times | 只將原 verifier 的第二次排序換成已準備的不可變 first_times tuple | 不使用 C1 快照；七次候選執行都完整載入與準備 context |

兩候選分開實作與驗收，未來一次窗口只能比較一個候選。排序的小候選尚無專屬成本證據，不保證達採用門檻；不以有利的新樣本或組合修改補救。

### 來源身分與鎖定／發布邊界

原 596 個來源的**每個 path／bytes／SHA-256 身分均保留**；未來執行清單只能加入新方法、規格與驗收收據，不得縮減原來源。原 15 份 binding 來源每次 create 及取得 OS writer 鎖後 `force=True` 都完整重驗，快照 lookup 必須在鎖定後重驗成功之後。

worker 前後及獨立 publisher 前後的四次完整 closure 全保留；publisher 必須使用新程序，逐一保留十四次原 store.open 的來源核對，重算實體帳本、成本、事件與負載。它不匯入或相信 worker 快照。正常退出、原單一絕對 deadline／資源監督、輸出封存及退出後 release 核對均沿用。

來源雜湊快取、按內容合併路徑及跨程序成功收據重用目前列為 **not_ready**。重啟這類候選前，須另立來源不可變／固定控制代碼生命週期設計並驗收變更與 ABA 情境；本規格不允許藉初始化重用省略來源核對。

### C1 的重用條件

- **身分鍵**：完整有序 15 份來源 descriptor、configuration 與 reconstruction receipt descriptor、完整設定與模型／support 的型別及 canonical 身分、原解析／數值／準備方法版本、候選與驗收版本，以及同一 request／namespace／程序身分。不能只用 fit_id、mtime、大小或檔名。
- **建立**：cold build 必須位於首次候選暖機的鎖定後、verifier setup 計時內。只將 counts／catalog 讀入有界不可變 bytes，核對這份實際解析 buffer 的長度與 SHA，之後用原獨立 CSV／load_context／prepare_catalog 語意解析；禁止雜湊一份檔案、解析另一份可變檔案。
- **原驗證**：UTF-8／newline、schema／欄寬、重複 ID、canonical 數字、正計數、完整支援集與訓練時鐘等拒絕條件全部保留。產物使用複製後的唯讀 mapping 與 tuple，不能留下可變 backing alias。
- **命中**：每次完整來源重驗後，比對完整 key 與目前設定／模型物件；使用前及 verifier 返回後核對快照內容 digest。最多一份快照，任何身分改變、非預期 miss、快照修改或程序恢復都停止本窗口，不偷偷重建、退回原版或重試。
- **計時**：首次讀取／SHA／解析／複製／凍結及每次 key／digest 成本都計入入口。使用前工作在原 setup；返回後 guard 另列但仍在完整入口內；擴充初始化成本為這兩個不重疊分項。原 setup／primary／append／commit 邊界另存，不能藏到未計時的預熱。

### 待實作後執行的驗收

封存 **38 個必要情境**：來源與身分 10、快照／解析語意 10、checkpoint 7、獨立發布 5、成本與公平性 6。須涵蓋同大小不同內容、相同內容不同路徑、上鎖前後變更、暖機後來源變更、完整 support／設定／方法改變、跨程序／window 誤用、精確 buffer 的 SHA、快照 mutation、一次 build 六次 hit、排序相同時間戳與 bisect 邊界。

還需沿用 V24 觀測、V25 受監督子程序／deadline 清理、V6 保存及 V23 成本守恆回歸。人工完整四臂與人工 48 筆帳本用途分開；科學 bytes、Decimal 字串、binary64 delta_hex、順序與 SQL 邏輯工作量均須一致。任一缺項、失敗或跳過都不能啟動真實比較。**這 38 項目前尚未執行，不能沿用前輪 32／32 當本候選已通過。**

### 未來公平比較設計（本輪未授權執行）

沿用原 48 筆與原模型，每個候選各自使用新規格及已驗收入口；R／C 各暖機一次，再六對 RC／CR，共十四次 fresh 帳本。兩臂相同細觀測與 200ms 目標負載；R 每次重建 context，C1 在 warm_C 計入唯一 cold build 後才可六次 hit。不得把 V25 歷史 R／D 當新比較基準，或在 entry 外預先建快照。

篩選門檻固定為完整入口六對至少 5 對較快、配對節省百分比中位數至少 5%、RC／CR 各自節省秒數中位數皆正；**包含冷啟動的七次候選入口總和也須小於七次原版**，原 primary 配對退步百分比中位數不得超過 5%，所有科學／來源／資源／安全條件均通過。這是初始化候選的工程篩選，不套用舊 SQL 的 primary-only 採用門檻，也不是統計推論保證。

單一 1,800 秒期限仍涵蓋 worker 與獨立 publisher；記錄全 worker／窗口、四次 closure、publisher callback／程序、父程序公開序列化及記憶體。所有十四次及失敗證據保留，不重開較快窗口。整體入口與候選合成驗收完成，另有明確真實執行授權後，才可啟動後續比較。

### 本輪完成範圍與操作

| 本輪工作 | 狀態 |
| --- | --- |
| 來源／初始化重複成本盤點 | 完成並已推送 |
| 兩候選、38 必要情境與未來比較條件 | 封存並通過指紋／結構核對 |
| 候選實作／合成驗收／真實比較 | 尚未執行；本規格授權真實 run 數為 0 |

封存：`.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_reuse_v26 --specification`（已有輸出拒絕覆寫）；只讀重稽核：同入口 `--audit`。入口沒有 measure／fit／ranking 選項，不重新核對大型來源現況。

下一步先實作 C1 的有界唯讀快照與原方法注入，再完成上述合成及受監督／獨立發布整合驗收；C2 維持另一個獨立候選。本輪沒有加速比例；原 SQL 與檢查方法未改，覆蓋仍 55／55 格、170 個可比較查詢、232 個歷史身分，完整 validation 未完成、保留測試鎖定，`T_plan = null`。

[封存規格](../reports/stage12/retailrocket_session_knn_v26_reuse_specification_20261109.json) · [封存收據](../reports/stage12/retailrocket_session_knn_v26_reuse_seal_20261109.json)
