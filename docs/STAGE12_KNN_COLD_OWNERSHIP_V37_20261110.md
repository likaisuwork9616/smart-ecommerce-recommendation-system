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

第二階段判定已封存於下方。仍保留 6 次 cold canonical、原時點完整內容核對、每次 final、來源身分、鎖後及獨立發布驗證。

```powershell
.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_ownership_v37 --audit
```

`--audit`只核既有盤點及來源／測試證據，不重跑測試或真實 context。`--inventory`拒絕覆寫；沒有 measure 或候選執行開關。

## 第二階段：可行性判定與後續門檻封存

**現有 API 的所有權證明不成立，6→4 不放行。**這個結論沒有把 production 預設路徑的唯讀行為說成不安全，也沒有宣稱曾在實際資料觀察到 mutation；它指出目前入口沒有強制維持足以取代原 late 兩次完整觀察的條件。

| 判定項目 | 封存結果 |
| --- | --- |
| cold canonical | 保持 6 次：原 early live／source 4 次、原 after-prepare live 2 次 |
| 同 worker 一 cold／六 hits | generic canonical 41 次、完整 live snapshot fingerprints 15 次、digest 22 次，沒有縮減 |
| 未來所有權方案 | 4 組、16 個先決條件；全部是待滿足要求，不是已通過的候選驗收 |
| 原來源身分 | 既有 2092 sources／168 methods，含原 1937／26 及 15 binding，四個初始化依賴的完整描述符仍由 V36 封存規格保留 |
| 工程／研究狀態 | 候選實作與候選測試 0；新真實 context／query／fit 0，沒有加速比例；55／55 細層、170 可比較／232 歷史查詢不變 |

### 若另設不可變所有權入口，必須先滿足什麼

| 門檻組別 | 四個待滿足重點 |
| --- | --- |
| 完整物件圖 | 證明 roots 與所有可變 descendants 的來源及所有權；排除 owner region 外有寫入能力的別名；保持 list／tuple 等原 typed identity；不能只用布林 ownership flag 或端點相等作證。區內經證明只讀且不逃逸的必要參數引用可以保留 |
| Callback 能力 | 連同原 callee 的間接 callback 一起查核；綁定並限制 watch 實作與 captures；查核 observer span／clock 的重入能力；證明期間排除其餘可改 caller 的路徑，同 PID 不足為證 |
| 原時點語義 | 原 after-prepare、cache.use／borrow／query 前仍要有等價完整內容觀察；V36 ABA／late NaN／custom 仍須原時點或更早拒絕並 poison；每次 final live 檢查保留；若改 typed comparator，另立演算法與等價驗收規格 |
| 身分與成本 | 原 source／method／request key 只追加；保留 create／鎖後、snapshot 與獨立 publisher／停態日誌；所有 copy／freeze／ownership 成本納入完整入口，禁止隱藏預載；新 policy 綁定至規格、request、事件、receipt、publisher，先合成驗收才另封真實比較 |

這輪沒有修改原 worker、SQL、canonical 或發布方法。V36 的 source-anchor 六次安全路徑仍只有設計：保留 original late 完整 canonical，再與 verified source bytes 比較，成功後才借出；本輪沒有把它標成已實作。

若要繼續降低序列化成本，下一個較明確的工程選項是**另訂原 late 時點的完整 canonical-equivalent typed comparator 規格**，再驗證完整型別、ABA、失敗清理與成本；它是新演算法，不是已證明安全的 immutable bytes 重用。另一條路是另做可強制執行所有權的入口，先滿足上表 16 項條件。兩者都尚未實作，也沒有原 48 筆新效能結論。

[可行性判定與 16 項門檻](../reports/stage12/retailrocket_session_knn_v37_ownership_decision_20261110.json) · [不可覆寫 seal](../reports/stage12/retailrocket_session_knn_v37_ownership_seal_20261110.json)

`--decision`拒絕覆寫既有判定或 seal；現在使用上方 `--audit`重核即可。完整 validation 未完成、最終保留測試繼續 locked；Stage 4 每日 10% 提醒預算及 Dashboard 暫緩不變。
