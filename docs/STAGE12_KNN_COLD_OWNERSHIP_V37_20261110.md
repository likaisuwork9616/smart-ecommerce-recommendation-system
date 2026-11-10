# Stage 12：cold 初始化期間的不可變所有權驗證

## 第一階段：盤點與原 API 驗證

目前不能用不可變所有權把 cold canonical 從 6 次減為 4 次。config／model 是可變的 dict／list 圖；獨立建立的 FrozenCatalog 與保存的 immutable bytes 都不會凍結原 caller。這輪只驗證現有行為，沒有實作減為 4 次的候選。

| 本輪工作 | 實際結果 |
| --- | --- |
| 來源盤點 | 13 份現有 Python、22 個 AST 函式／類別範圍，保存完整檔案與範圍 SHA；11 項所有權發現 |
| 新增所有權案例 | 12 項 tiny synthetic，涵蓋 caller 巢狀別名、support、watch／observer、淺層 MappingProxy、保存 bytes 與 list／tuple 型別 |
| 前輪時點反例 | 原 V36 的 6 項全部納入同一輪循序驗證；合計 18 項全過、1.4917354 秒，無失敗／錯誤／跳過 |
| 真實資料與查詢 | 新 context replay、SQL query、模型 fit 均 0；未重跑原 48 筆 |

### 所有權落在哪裡

| 邊界 | 程式實際行為 | 對 6→4 的意義 |
| --- | --- | --- |
| JSON 輸入 | production loader 用標準 json.loads 建立新 dict／list；worker 保留 data，verifier 參數／closure／active 保留引用 | 新解析證明來源，沒有撤除寫入能力或所有巢狀別名 |
| model support | load 明確要求 support **is** model['support'] | 相等的 detached copy 會被拒絕；合法值可透過共享別名在初始化中變更 |
| 原 load／prepare | 受審原方法沒有直接寫入 config／model，prepare 複製 catalog／counts | 這是正面證據，但 callee 內仍呼叫 watch，不能只憑沒有 assignment 證明封閉 |
| watch／observer | 真實入口用預設只讀版本；通用 load 沒有強制其 exact 類別、clock、span 或 capture 能力 | tiny 自訂 callback 確實可在 early 比對後、late capture 前改值；沒有宣稱歷史 production run 曾遭改值 |
| 初始化重入 | active 在 cold build／pre-use digest 後才檢查並登記 | active 不是 cold 期間的 busy guard；本項是來源盤點，沒有宣稱本輪執行過重入測試 |
| snapshot | 原 prepare 複製純量 map，產生 MappingProxy／tuple，保留完整 snapshot 驗證 | 不可變 snapshot 與 caller 的 config／model 是不同物件範圍 |
| bytes／MappingProxy | bytes 本身不可改；MappingProxy 只擋從該 view 寫入 | backing dict 與巢狀 list 仍可改；bytes 不變不能證明原輸入不變 |
| 深凍結 | list 換 tuple 雖有相同元素，原 typed canonical bytes 不同 | 不能直接更換型別再宣稱原內容身分完全等價 |
| 來源與 writer lock | 保留完整來源、方法、程序與鎖後核對 | 檔案／store 的鎖不等於 Python heap 的遞迴所有權 |

### 實際驗證的界線

12 個新案例直接執行原 C1 tiny fixture，沒有 mock 掉原來源或鎖後核對。巢狀 caller／backing-map 改動在 final 被拒絕並 poison；support 等值 copy 被身份檢查拒絕；初始化期間合法 support 變動可被原 late baseline 接收，而超過 counts 的值被原 loader 拒絕。這些單次 load／finish 結果不代表完整七次身分核對或獨立發布會放行。

watch 與 observer 案例證明通用 API 存在可變入口。前輪 6 個反例則保留 late B、final A 的 ABA 拒絕，以及 late NaN／custom value 在 borrow 前失敗的原時點。相反地，late 已取 A 後短暫變 B 又在 final 前還原 A，原離散 guard 仍可通過；不宣稱能偵測全部瞬時變更。

[本輪盤點收據](../reports/stage12/retailrocket_session_knn_v37_ownership_inventory_20261110.json)保存逐案成功 ID、實際耗時、ignored 測試 log 描述符，以及來源錨點。已重核 V36 封存的 source／event／test 證據；本輪沒有再雜湊整個約 12GB closure，也沒有產生新的 production 效能或 Ollama token 速度數據。

第二階段會封存可行性判定與後續所有權門檻；目前仍保留 6 次 cold canonical、原時點完整內容核對、每次 final、來源身分、鎖後及獨立發布驗證。

```powershell
.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_ownership_v37 --audit
```

`--audit`只核既有盤點及來源／測試證據，不重跑測試或真實 context。`--inventory`拒絕覆寫；沒有 measure 或候選執行開關。
