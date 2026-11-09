# Stage 12：C1 身分與內容檢查的序列化成本

## 盤點與隔離重播完成

本輪重讀並核對 V28 的 **329 份已存證據、35,746,578 bytes**，重新核對七次 C1 原 guard 事件；只讀四份小型原初始化依賴（8,863,434 bytes），從原 counts／catalog 重建唯讀快照，SHA 與 V28 保存值一致。沒有重掃 12GB 完整來源、讀取模型資料庫、重跑排名／SQL／append 或另開原 48 筆窗口。

### 前輪實測與本輪重播分列

V28 六次正式 C1 的 identity、pre-use digest、final guard 中位數仍為 **0.416／1.558／1.891 秒**；三段互不重疊合計中位數 **3.866 秒**。V28 沒有留下更細的序列化計時，不能從舊事件直接分配型別樹、JSON、UTF-8 與 SHA 的耗時。

本輪固定一輪暖機、三輪保留重播，五種資料角色順序固定；先保存 plan／方法指紋，再量測。AST 只拆開原 canonical 最後一個表達式，遞迴 typed 函式保持原狀。**18 項核對通過**，涵蓋原型別／Unicode／錯誤類型、bytes／SHA 與互斥計時，以及透過原 C1 bytecode 的人工呼叫驗證計數。這些是診斷工具核對，不是改善候選驗收。

### 固定程式路徑的重複次數與 bytes

| 序列化內容 | cold 次數 | 每次 hit | 七次合計 | 每次 canonical bytes |
| --- | ---: | ---: | ---: | ---: |
| binding 相等核對 | 2 | 2 | 14 | 40,301 |
| 完整身分鍵 | 1 | 1 | 7 | 5,285,468 |
| 完整設定 | 4 | 1 | 10 | 36,375 |
| 完整模型／support | 4 | 1 | 10 | 4,566,194 |
| 完整唯讀快照 | 3 | 2 | 15 | 22,302,590 |

一次 cold＋六次 hit 共 **56 次 canonical、22 次 digest**。其中快照 cold 建立預期值一次、每次使用前及使用後各一次，共 **15 次**；身分鍵 digest 共七次。這些是固定程式流程推算，已由人工實際呼叫核對；不是 V28 新增的內部函式觀測數。

依重建輸入與流程計算，七次 canonical 邏輯輸出合計 **418,127,030 bytes**；快照占 **334,538,850 bytes（80.01%）**。快照涵蓋 234,795 個 catalog 與 198,946 個 count。這不是實體 I/O 或配置總量；重複引用在舊通用編碼中仍會完整展開。

冷啟動時設定／模型各有「兩份比較、保存預期值、返回後再核對」四次 canonical；命中仍各重做一次返回後核對。身分鍵還重複包含來源清單及 request 內的來源清單。這些發生在不同保護邊界或包含獨立身分，不能直接當成可刪除工作。

### 本輪隔離重播：每次操作的三輪中位數（秒）

| 資料角色 | typed 樹建構 | JSON＋typed 樹釋放 | UTF-8＋文字釋放 | SHA-256 |
| --- | ---: | ---: | ---: | ---: |
| binding 相等核對 | 0.000621 | 0.000660 | 0.000004 | 0.000000 |
| 完整設定 | 0.000523 | 0.000626 | 0.000003 | 0.000000 |
| 完整模型／support | 0.179072 | 0.110936 | 0.001305 | 0.000000 |
| 完整身分鍵 | 0.280665 | 0.127469 | 0.004540 | 0.010498 |
| 完整唯讀快照 | 0.949471 | 0.444946 | 0.006892 | 0.044987 |

binding／設定／模型在此角色只需 canonical bytes 比較，SHA 欄的 0 表示原角色沒有該次 digest 呼叫，不表示來源檔雜湊為零。所有角色的 bytes 與原 canonical 一致；快照 hash 直接符合 V28 保存值。歷史身分鍵依原 request、設定／模型及私有已退出 worker 身分重建，但 V28 未保存原 key digest，因此不宣稱直接比對過原 key 值。

重播耗時 **11.093 秒**，含暖機的 20 筆樣本全部保留，其中正式 15 筆；取樣 RSS 峰值 178.97 MiB。階段時鐘、golden 驗證與物件保留方式會影響重播；各分項中位數不保證相加等於合計中位數，**不可將本表比例直接套入 V28 的 3.866 秒，也沒有候選加速比例**。

### 改善方向與未完成部分

本次重播顯示，快照的通用 typed 樹與 JSON／釋放成本遠大於 SHA；優先制定專用、完整 schema 的快照指紋候選，保留每次使用前後的完整內容核對、完整來源身分與鎖定後重驗。完整 key 的重構與來源 hash 快取先不合併。

下一小階段固定新格式版本、型別／順序／完整覆蓋、篡改拒絕、獨立 publisher 自行重建及公平比較條件。盤點完成當時尚未封存候選；後續封存結果如下，新指紋仍未實作。本輪真實原 48 筆 run、rank／SQL／append、fit／完整 validation／bootstrap 皆為 0；保留測試鎖定，覆蓋仍 55／55 格、170 個可比較查詢、232 個歷史身分。

操作：`.venv/Scripts/python.exe -B -m scripts.inventory_retailrocket_session_knn_serialization_v29 --inventory` 只產生一次性盤點；已有報告拒絕覆寫。現有產物用同入口 `--audit` 核對，不重播。原 V27／V28 方法與收據不變。

[盤點與重播報告](../reports/stage12/retailrocket_session_knn_v29_serialization_inventory_20261109.json)

## C1-S1 改善候選規格封存完成

封存唯一優先候選 **`C1-S1-schema-snapshot-v1`**：只更換完整快照的內部指紋表示，身分鍵、完整設定／模型／support 比較與原來源核對不變。規格 **338,322 bytes**，SHA-256 **`221f63bbfa21078eedec62f9218dbb294443e4a03698e3a7bb19eb5923659cfd`**。已執行 `--audit`，規格／方法／盤點／原 request 與繼承門檻指紋及結構核對通過；這不是候選程式驗收。

### 固定新格式與完整覆蓋

| 欄位 | 每次指紋前完整驗證 | 新編碼 |
| --- | --- | --- |
| first | 原 FrozenCatalog 的 exact MappingProxyType；ID 為 canonical ASCII 數字字串，時間為非負且 type 是 int | 全部 [ID, timestamp]，按字串 ID 排序 |
| counts | exact MappingProxyType；ID 規則相同，count 為非負且 type 是 int | 全部 [ID, count]，按字串 ID 排序 |
| first_times | exact tuple；每個值為 int 時間，保留數量、重複值與位置 | 原序列直接編碼，不再排序或去重 |
| fallback | exact tuple；每個 ID 都符合字串規則，保留全部位置 | 原序列直接編碼，不改排序 |

固定四欄順序為 first、counts、first_times、fallback，JSON 為固定有序欄位陣列，UTF-8、無多餘空白、`ensure_ascii=False`、`allow_nan=False`。ID 保持字串、整數保持精確十進位，不轉 float；bool 不當作 int。對合法快照，欄位 schema 已界定型別，不再逐葉建立通用 typed 標籤，但**仍完整讀取並驗證所有值**。

摘要仍用完整 SHA-256，前置明確的 `K1-C1-S1-SNAPSHOT-v1`＋單一 LF 版本域，再接完整 JSON bytes。新舊快照前像格式不同，**新 SHA 不要求等於舊 C1 SHA**；來源檔案的 path／bytes／SHA 不改。request、方法、封存規格與 cache.use 事件必須共同綁定 scheme，混用舊／新版本就拒絕發布。完整科學 payload、Decimal、delta bits 與 SQL 工作量仍須等同原參考。

### 保留原檢查與生命周期

- 保留原 **1,261 份 closure 與 15 份 binding** 的每個身分；未來只加入新方法／規格／驗收收據，不縮小來源集合。
- 每次原 create 與取得 OS writer 鎖後 `force=True` 都完整重驗，再進入快照 lookup；worker／publisher 前後四次 closure 及 publisher 十四次原 open／proof 全保留。
- 一個 worker、一份快照、一次 cold＋六次 hit；cold 預期指紋一次，加七次使用前及七次使用後，共 **15 次完整 live 指紋**。不得改成只雜湊先前儲存的 encoded bytes，避免掩蓋目前物件變更。
- 七次仍有 **41 次通用 canonical＋15 次專用快照編碼、22 次 digest**；14 次 binding、10 次設定、10 次模型及七次完整 key 的通用序列化不改。變更／非預期 miss／不同程序或 window 都停止，不回退、不重建較快窗口。
- 獨立 publisher 使用新程序，從原模型／counts／catalog 自行重建並驗證 schema、計算同版本指紋。它不接收 worker 快照、編碼 buffer 或已成功核對 token。

原 V27／V28 方法、舊指紋與 C1 未採用決策保持封存；新候選須用新 pool／指紋／publisher adapter 檔案，不能覆寫舊實驗。

### 待執行驗收與未來比較

新增 **32 個必要情境**：schema 8、mutation 8、equivalence 8、control 8；另延續 V26 原 38 個必要情境與 V27／V28 完整回歸，V29 的 bytes／流程計數核對也保留。包含 exact 物件型別、bool／int／float 區別、精確大整數、map 插入順序、tuple 順序／重複／空值、各欄 key／value 修改、缺尾／截斷、版本混用、既有 buffer 掩蓋 live mutation、完整四臂科學 bytes／delta bits／SQL、來源與鎖定、獨立新程序重建、篡改拒絕、退出／期限／資源及原採用門檻。

**這 32＋38 個情境尚未執行，不能以盤點的 18 項核對代替候選驗收。** 目前 C1-S1 程式未實作，實際授權真實 run 數為 0，沒有候選加速數字。

若後續實作及整合驗收通過，仍須另立真實入口啟動規格，使用原 48 筆與新窗口內的原 R 比較 C1-S1，各暖機一次再六對 RC／CR，十四份 fresh 帳本。冷啟動、完整 schema 驗證、配置／複製、JSON、UTF-8、SHA 與釋放全計入完整入口，使用前／後 guard 分列；兩臂相同觀測深度，不預載。

沿用 V26／V28 門檻：至少五對入口較快、配對節省中位數至少 5%、RC／CR 各自節省秒數中位數皆正；含 cold 的七次 C 總和小於 R，primary 退步百分比中位數不超過 5%，全部科學／來源／安全條件通過。單一 1,800 秒／原資源限制涵蓋 worker 與獨立 publisher，保留所有十四次、負載 gap 及失敗證據，不選擇較快窗口重開。

### 延後與本輪完成範圍

完整身分鍵的分元件重構先不合併：原 identity 中位數 0.416 秒，且 request／closure／可變語意狀態的覆蓋需另行證明。來源 hash 快取或減少快照前後核對也不在本候選範圍內。

| 本輪工作 | 狀態 |
| --- | --- |
| C1 重複序列化盤點與原 canonical 隔離分項重播 | 完成；18 項核對通過，原事件與重播分列 |
| C1-S1 格式、原檢查不變條件與未來驗收／比較 | 已封存並通過完整性核對 |
| 候選實作／候選合成驗收／原 48 筆新窗口 | 尚未執行；沒有加速宣告 |

操作：`.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_serialization_v29 --specification` 一次封存；現有規格使用 `--audit`，不重播或執行候選。下一步先實作 C1-S1 專用快照指紋，再完成所有新／舊情境與獨立發布整合驗收。

本輪沒有新查詢、fit、完整 validation、主要 bootstrap 或保留測試。覆蓋仍 55／55 格、170 個可比較查詢、232 個歷史身分；保留測試鎖定，`measured_speedup = null`、`T_plan = null`。

[候選封存規格](../reports/stage12/retailrocket_session_knn_v29_serialization_specification_20261109.json) · [封存收據](../reports/stage12/retailrocket_session_knn_v29_serialization_seal_20261109.json)
