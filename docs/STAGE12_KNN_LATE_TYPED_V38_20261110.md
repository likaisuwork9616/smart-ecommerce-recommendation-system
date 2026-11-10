# Stage 12：原 late 時點的完整 typed comparator 規格

## 第一階段：原編碼語義與時點盤點

本輪制定新演算法規格，沒有實作 comparator。目標是在原 after-prepare 位置完整檢查 live config／model，避免那兩次重新產生整份 JSON／UTF-8 canonical output；不是刪掉兩個內容 guard。現在執行中的程式仍是 6 次 canonical，沒有 6→4 採用或效能結論。

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

第二階段會封存具體 immutable reference 格式、32 項待驗要求與獨立發布／成本規則。

```powershell
.venv/Scripts/python.exe -B -m scripts.freeze_retailrocket_session_knn_typed_v38 --audit
```

已有盤點拒絕覆寫；audit 只核既有來源與測試證據，不重跑測試／context。此入口沒有 candidate 或 measure 開關。
