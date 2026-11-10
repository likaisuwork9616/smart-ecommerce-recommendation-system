# Stage 12：原 late 時點的完整 typed comparator 規格

## 第一階段：原編碼語義與時點盤點

本輪制定新演算法規格，沒有實作 comparator。目標是在原 after-prepare 位置完整檢查 live config／model，避免那兩次重新產生整份 JSON／UTF-8 canonical output；不是刪掉兩個內容 guard。既有 C1-S1 程式仍是 6 次 canonical，沒有 6→4 採用或效能結論。

候選選擇 V36 的固定來源基準：early 比對成功的 verified source canonical bytes 才是權威。若初始化中持續變成 B，原 late baseline 可以吸收 B，本候選會在借出前拒絕；這是刻意加強的拒絕規則，不能稱為所有舊行為完全等價。

| 原 canonical 規則 | 新比較器必須保留的語義 |
| --- | --- |
| None／bool／int／float／str | 用 exact type；True 與 1、1 與 1.0 不等價 |
| int／float | int 轉原十進位字串；finite float 用原 hex，保留正負零，拒絕 NaN／±Infinity |
| list／tuple | 兩個 tag 不同；位置、長度、順序與重複都算內容 |
| dict／MappingProxyType | exact 兩型共用 map tag；全部 key 必須 exact str，以原 Python Unicode 字典序排序，不看 insertion order |
| 全部巢狀內容 | config、support、fit_audit、未被 loader 讀取的 metadata 都不能省略；不能只比 id、長度、摘要或 Python container equality |
| Unicode | 不正規化、不轉大小寫；lone surrogate 在原 UTF-8 階段會失敗，省輸出後仍須拒絕 |
| Unsupported／subclass | Decimal、bytes、自訂物件與內建型別 subclass 仍拒絕；不以寬鬆 isinstance 放行 |
| 別名與 cycle | 共享但無環的子樹可接受且每個位置仍遍歷；cycle 必須拒絕，不能用 global visited 將共享別名誤判為 cycle |

新增 19 項 oracle 測試只呼叫未修改的原 canonical；另外將 V37 的 12 個所有權案例及 V36 的 6 個時點反例一起循序重跑。**37／37 項全通，1.5639039 秒，無失敗／錯誤／跳過。**正式結果與每個成功 test ID 保存於[語義盤點收據](../reports/stage12/retailrocket_session_knn_v38_typed_inventory_20261110.json)，它們不是新 comparator 的驗收。

Exact MappingProxyType 可能包住自訂 mapping。未來實作要保留原 key-type scan→sorted-key scan→逐 key lookup 的協定，不能新增 len／items／任意 equality 呼叫而引入不同 callback；動態 backing 的 mutation／reentry 必須另作差分驗收，不能假定 proxy 底下必是純 dict。

### 時點與完整走訪的限制

1. 原四次 early live／source 完整 canonical 與 config→model 順序保留。
2. 原 load_context／prepare_catalog 及既有 observer span exit 都不改。
3. 新檢查放在原 late 位置，cache.use／borrow／query 前；不能在這個邊界前、兩個 root 之間或單次遍歷中新增 watch／span／observer clock callback，以免多出還原 B→A 的時機。
4. 選中的 root 即使前面值、形狀或長度不等，仍遍歷全部 live extras；不能 zip 截尾或用 and 短路漏掉尾端 invalid 值。遇到硬錯誤可立即失敗並 poison，不要求錯誤後繼續走訪。
5. Config 完整檢查不等或失敗即拒絕，不開始 model；config 成功才完整查 model。這是 source-anchor 新規則；所有原 final live canonical、snapshot、來源身分、鎖後與獨立發布仍保留。
6. Late B、final A 的 ABA 不得因保留 early A 而放過；若變更在所有既有離散檢查前都還原，不宣稱能做連續監測。

新 source reference 的 decode／完整 grammar validation／freeze、持有與釋放，和所有 typed walk／map key sort／strict UTF-8 domain 檢查都要計入 cold／完整入口。舊約 0.392 秒只作背景，不能當可省時間。

目前只讀核對既有來源與封存證據，沒有再雜湊約 12GB closure，沒有真實 context replay、SQL query、fit 或原 48 筆重跑。完整 validation 未完成，保留測試 locked；55／55 細層與 170 可比較／232 歷史查詢不變。

第二階段已封存下方具體 immutable reference 格式、32 項待驗要求與獨立發布／成本規則。

```powershell
.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_typed_v38 --audit
```

已有盤點拒絕覆寫；audit 只核既有來源與測試證據，不重跑測試／context。此入口沒有 candidate 或 measure 開關。

## 第二階段：具體候選規格封存

候選識別為 `C1-S1-cold-late-typed-source-anchor-v1`，reference scheme 為 `K1-C1-LATE-TYPED-REFERENCE-v1`。**目前只封存規格，未實作、未做候選驗收，也未採用。**前述 37 項是原程式語義依據，不是下列 32 個未來要求已通過。

### 固定來源 reference

原四次 early 完整比對全部成功後，保留 source config／model 的 typed canonical bytes。由這兩份 exact bytes decode，驗完整 grammar，再新建只含 tuple、exact str／bool 葉節點的遞迴 reference，不保留 caller 或 decoded list 的別名。這會新增 JSON decode、grammar／freeze 與暫時兩份物件圖的記憶體成本；全部在 cold 內計費，不預載、不跨 worker。

| Token | 嚴格格式 |
| --- | --- |
| none | tag，arity 1 |
| bool | tag＋exact bool，arity 2 |
| int | tag＋原 `str(int)` 字串；int→str roundtrip 必須完全相同，沿用當前 interpreter 位數限制 |
| float | tag＋finite hex；fromhex→hex roundtrip 完全相同，含負零 |
| str | tag＋原字串；strict UTF-8 可編碼，不正規化 |
| list／tuple | 不同 tag＋child token tuples，保存全部位置 |
| map | tag＋排序後的 `(key, child)` tuples；key 必須 exact str、strict UTF-8、嚴格遞增且不重複 |

原 configuration.json 檔案描述符，與 reconstruction.json 全檔描述符及其 `receipt` selector 都獨立綁定。未來還須另記 early 第 2／4 次成功的 **source typed canonical bytes** 長度／SHA、原 canonical 方法身分及 reference scheme；不能把原始 JSON 檔 bytes、或 V35 只捕捉到的 late bytes，當成本輪新量到的 early bytes。此輪沒有填入未實測的 canonical 輸出數字。

### Late 完整比較

在原 prepare span exit 後、原 late 位置，先完整查 config，成功才完整查 model。以原 exact type dispatch、scalar conversion、map key 讀取協定和序列順序走訪 live root，對照 immutable reference；不重建整棵 typed tree，也不產生完整 JSON／UTF-8 canonical output。Strict UTF-8 domain 驗證仍是實際工作，不能說成零成本。

一般 mismatch 不得漏掉剩餘 live entries／elements；硬錯誤則立即拒絕並 poison。只在所有比較成功後保存固定 source expected bytes、owner／key，接回原 snapshot／pre-use／borrow；不得把變更後 caller 更新成新基準，也不在不等時 fallback 到舊 late baseline。

這段邊界不新增 watch／span／observer clock／使用者 callback，包括 comparator entry 與 config／model 之間。採綁定的被動 timer 與本地純量 metadata，檢查完成後記錄證據；既有其他位置的 hooks／watch 全保留。Proxy 自訂 backing 原有的資料讀取 hooks 也不能被偷偷改寫；其 mutation／reentry 必須通過差分驗收。沒有並行或連續 heap 監測承諾。

### 計數與完整成本

| 項目 | 目前程式 | 候選規格預期，尚未執行 |
| --- | ---: | ---: |
| cold canonical | 6 | 4 |
| cold 完整 typed comparison | 0 | 2 |
| cold 完整內容觀察合計 | 6 | 6 |
| 一 cold／六 hits generic canonical | 41 | 39 |
| 同七次完整 typed comparison | 0 | 2 |
| 同七次 live snapshot／digest | 15／22 | 15／22 |

四次 canonical 加兩次完整 typed 檢查，不是四次總 guard。Reference decode／grammar／freeze、live walk／sort／int／hex／UTF-8、保持／釋放、RSS／GC 與觀測成本都納入同一完整入口；可能抵消省下的輸出成本，不預告加速比例。

### 32 項未來驗收要求

| 組別，各 4 項 | 涵蓋內容 |
| --- | --- |
| 權威來源 | early 成功 bytes、遞迴不可變 reference、cold 計費、變造／mixed policy 拒絕 |
| 純量 | exact type、float.hex／signed zero／極值、整數與 interpreter 界線、Unicode／UTF-8 |
| 容器 | list／tuple 與順序重複、dict／proxy 原讀取協定、完整巢狀欄位、禁止淺層／摘要捷徑 |
| 失敗 | unsupported／subclass／nonstr key、mismatch 後完整 root、cycle／共享無環／深度／surrogate、所有錯誤 poison 清理 |
| 時點 | 持續變更借出前拒絕、跨 late ABA、還原的離散界線、watch／observer 及重入策略 |
| 原保護 | 全部身分 key／來源方法只追加、15 binding 的 create／鎖後、全部 final／15 snapshot、科學 bytes／SQL／獨立發布／停態日誌 |
| 整合 | policy 全鏈綁定、reference 身分與兩次完成證據、單 worker 一 cold 六 hits、成功與失敗釋放 |
| 成本 | 4＋2 完整核對、39／2／15／22 預期計數、全部新成本入帳、先差分合成驗收再另封循序原 48 筆比較 |

完整要求 ID 見[候選規格](../reports/stage12/retailrocket_session_knn_v38_typed_specification_20261110.json)。未來須用未修改的原 canonical 作差分 oracle，涵蓋相等、不等、拒絕、產生的巢狀圖及明確邊界。若新演算法拒絕原本有效的邊界值，也必須先釐清，不能默認驗收通過。

獨立 publisher 要重新讀 verified raw config／model，以原 canonical 重建 source bytes／reference 權威，不能相信 worker 序列化的 reference。核對 policy、原檔與 canonical 身分、一個 cold build／兩個 roots、cold 兩次 late 完成／hit 零次、被動時序與完整 phase counts，再保留原科學結果、來源、store 和停態日誌核對。

所有舊方法與報告未改。既有 2092 sources／168 methods（內含原 1937／26 與 15 binding）及四個初始化依賴由繼承規格完整保留；未來實作只追加方法與 policy。候選實作／候選測試／真實 context／query／fit 均 0，T_plan 空值，沒有加速比例；Stage 4 每日 10% 預算及 Dashboard 暫緩不變。

[不可覆寫 seal](../reports/stage12/retailrocket_session_knn_v38_typed_seal_20261110.json) 已保存規格與盤點的 exact 長度／SHA。現用上方 `--audit`核對，不要重跑 inventory／specification。下一步可依新檔實作，再把 32 項與繼承要求逐案映射到差分／整合驗收；實測入口與原 48 筆公平比較仍須另封。
