# Stage 12：原 late 完整 typed comparator 實作與驗收

## 第一階段：核心與差分驗收

依 [V38 封存規格](STAGE12_KNN_LATE_TYPED_V38_20261110.md)新增 reference builder 與完整 typed comparator，沒有改舊 canonical、SQL、loader、prepare 或凍結報告。核心與下方 worker／獨立 publisher 整合驗收均已完成；這不是採用或加速結論。

| 實際執行項目 | 結果 |
| --- | --- |
| unittest | 40／40 全通：21 個新 core tests＋19 個原 canonical characterization；無失敗／錯誤／跳過 |
| 真正的差分向量 | 322 個：相等 158、不等 140、原 oracle 拒絕 24 |
| 其他核心向量 | reference grammar／admission 拒絕 30、runtime／深度等邊界 491、資料讀取協定 7 |
| 向量總數 | 850 個、850 個唯一 ID；不將全部都稱為差分或 oracle 拒絕 |
| 真實資料範圍 | 真實 context、SQL query、fit、原 48 筆效能重跑均 0 |

### 實作選擇與原語義

Reference 從 exact typed canonical bytes 解碼，完整驗 tag／arity／十進位 int／finite float.hex／UTF-8／排序唯一 map keys，轉為不可變 tuple token tree。以迭代 parser／grammar／walk 避免新增遞迴 helper 提早撞到 Python 深度限制；共享無環子樹每次都走訪，cycle 用 active ancestry 拒絕。Reference 不可 pickle，不可透過 setattr 改內容；弱 admission registry 不保存 reference 或 bytes 強快取，factory lease 綁所有原不可變 slots，防止 stale id 重用授權不同內容。

Live 比較保留 None／bool／int／float／str exact type、list／tuple 差別、序列順序及重複、dict／proxy 同 map 語義、完整巢狀資料與 Unicode。一般不等仍檢查所有 live extras；hard invalid 立即拒絕。不存在 Python container equality、id／長度／摘要相同就略過子樹的捷徑。

Map 仍按原 all-key scan→sorted keys→原 raw key lookup。動態第二輪出現 str subclass 時，用 `str.__str__`取得實際 Unicode payload，避免自訂 encode／equality 偽裝；lookup 仍用原 key，沒有多加 len／items 呼叫。兩個 LieStr 正反例實際對回原 oracle bytes 及讀取 trace。

### 執行域與較強拒絕規則

本候選以 V36 固定來源為基準，初始化中持續變更不會被吸收成新 late baseline。比較成立的主張限於原 typed domain、已批准的 runtime／callsite 與穩定物件圖；不宣稱任意動態 proxy 或連續 heap 隔離的全域等價。

- Public `build_reference`會重建資料並額外呼叫一次未修改的原 canonical 核 exact bytes。該額外序列化屬獨立 publisher／standalone builder 成本，不能混進 worker 39 次或隱藏。
- Worker 私有 builder 是**受封存方法約束的 adapter 信任邊界**：只使用同次四個 early 比對成功的 source bytes 與成功 callsite／runtime 記錄；不是任何 bytes 都能換來的不可偽造通用憑證，不重做兩次序列化。
- Recursion limit、int digit limit 與批准 callsite budget 在比較前、比較完成後都被動核對；變動即借出前拒絕。這些 eligibility 向量與純內容差分分開記錄。
- 動態 proxy 首輪 exact str、第二輪改成 int／None／bool key，原 oracle 可能產出合法但與固定來源不同的 JSON；新比較器採較強 fail-closed 拒絕。三個實測例子列為 admission 邊界，沒有偽稱原 oracle 拒絕或任意代理全域等價。
- 內層 comparator 重入即使被 callback 捕捉例外，sticky reentered 狀態仍讓外層拒絕；退出後狀態清除，不污染下一個獨立比較。

這些範圍是 V38 動態協定與 resource admission gate 的具體處理；沒有放寬來源內容或推遲原 late 保護。若變動在所有既有離散 guard 前還原，仍不宣稱能連續偵測。

[核心差分驗收收據](../reports/stage12/retailrocket_session_knn_v39_typed_core_acceptance_20261110.json)保存實際向量、唯一 ID、方法 SHA 與 ignored log。失敗草稿日誌保留在 ignored verification，沒有覆寫成通過結果。

```powershell
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_typed_core_v39 --audit
```

核心收據只證明本節範圍；新 worker、原時點與獨立發布證據如下。兩階段測試有重疊，不將 40＋165 當成 205 種不同情境。

## 第二階段：原 late 接合與獨立發布整合驗收

**165／165 項循序驗收全通，無失敗／錯誤／跳過；測試與證據彙整共 98.6024727 秒。**本輪用人工資料真正執行 14 份各 48 筆的帳本，672 次完整保存核對通過。沒有讀取真實 context、重跑原 48 筆或新增 fit；人工計時不能當成真實加速比例。

| 本輪正式測試模組 | 實際通過數 |
| --- | ---: |
| 新 comparator core | 21 |
| 新 worker、原情境與 late／失敗／release 邊界 | 56 |
| 新獨立 publisher、人工 14 帳本與 raw 竄改拒絕 | 18 |
| 未改動的 S1 snapshot 元件 | 18 |
| V34 直接來源及日誌生命週期 | 15 |
| 原 typed oracle／ownership／時點回歸 | 19／12／6 |

### 原時點保護與完整成本

新 worker 只在 invocation-local clone 接合原 C1／S1 流程。四個 early canonical 原樣執行，全部成功後才從已驗 source bytes 建兩根 references。原 load_context／prepare_catalog 及原 span exit 保持；第一個原 late dispatcher 依序完整查 config、model，**兩根都成功才回傳固定 source config bytes**，下一個 dispatcher 才回傳 source model bytes。因此 model 的讀取 hook 不會看到部分發布的 expected_config。

這段不新增 watch／observer／clock callback；僅受綁定被動 timer。一般不等走完整 root，config 不等不啟動 model；unsupported、surrogate、cycle、runtime 變更、重入或 reference 變造都在 borrow／cache.use 前拒絕並清除狀態。已實際測試第二根 reference 建構失敗、原 load／prepare 失敗，以及同 pool 失敗後禁止 retry。

第 7 次成功 finish 在最後一個 run.total 內釋放兩個新 references，保留 receipt 所需純量。以停用 GC 的兩個 lease weakref 驗證前六次仍存活、第七次 finish 回傳前已死亡，沒有用 gc.collect 掩蓋延後成本。接合使用 SimpleNamespace，移除動態 class 可能留住 cold 狀態的 GC cycle；原 expected bytes／snapshot 的 close 流程仍保留。

| 實際計數，來自函式 code-entry profile | 一 cold／六 hits |
| --- | ---: |
| generic canonical | 39（binding 14、identity key 7、config 9、model 9） |
| cold 完整 typed comparison | 2 |
| reference roots | 2，只建一組，六 hits 不重建 |
| 完整 live snapshot fingerprints | 15 |
| identity key／全部 digest | 7／22 |

Cold 是 4 次 canonical 加 2 次完整 typed 核對，內容 guard 沒有減少。原每次 final live config／model canonical 與 snapshot、程序身分、來源及 writer-lock 核對均保留。Public builder 的額外原 canonical 驗證留在 publisher 成本，不藏進 worker 39 次計數。

### 獨立 publisher 與封存

Publisher 在 worker 正常退出後，由新 interpreter 從 exact verified raw config／model 自行讀取 `receipt`、呼原 canonical、建立自己的 references 與 S1 catalog。沒有接收 worker references 或成功 token。完整保留 14 次 store.open、全部科學 bytes、Decimal／delta hex／SQL workload、查詢順序、來源前後與鎖後核對。

Raw 新 policy、來源／canonical 描述符、reference statistics、build 與 config→model 的完整 late 時序都先嚴格查核，再只將新增三欄投影給原 S1 schema；舊 source／event／payload 檢查仍讀原始檔。直接呼 raw publisher 的負例驗證來源 hash、policy、順序、漏查、統計與時間邊界竄改會被拒絕，沒有只靠 post-exit SHA 假通過。

頂層 pipeline／worker／publisher contract 都 quiet 並分別保存 closed diagnostics。發布時僅延後 V34 規定的兩個 active root streams；全部程序停止後完整封存最終 manifest，包含 buffered pipeline 訊息，後續 append 或新檔都拒絕。追蹤程序實際 9 個，退出後存活 0。

| 來源範圍 | 實際保存／驗證界線 |
| --- | --- |
| 繼承真實契約 | 原 2092 sources／168 methods／15 binding 的描述符完整保留；只追加至 2101 sources／177 methods |
| 本輪人工執行 | 每次完整 closure 為 219 descriptors，人工 binding 為 25；worker／publisher 前後完整查核及每次 create／鎖後均執行 |
| 實際方法收據 | 新 acceptance 的 98 個直接 Python 來源前後一致；人工 request 另包含上述全部 177 methods |
| 未執行的工作 | 約 12GB 真實 closure 沒有重新雜湊，真實 context／query／fit 均 0；不把 219／25 說成原 2092／15 實測 |

### 完整要求與收據重核

V38 的 **32 項**、V30 的 **70 項適用要求**、V36 的 **24 項**及 V34 的 **3 項**均映射到本輪實際成功 test IDs，共 **129 個要求**。原 V36 的 cold 6／七次 generic 41 計數條款明列由 V38 的 4 canonical＋2 typed／generic 39 取代；snapshot 15／digest 22 不改，沒有拿原版計數測試冒稱新候選結果。

[完整驗收收據](../reports/stage12/retailrocket_session_knn_v39_typed_acceptance_20261110.json)與[外部 seal](../reports/stage12/retailrocket_session_knn_v39_typed_acceptance_seal_20261110.json)不可覆寫。Audit 會重建模組計數、核原核心向量、從 namespace 的 stopped manifest 重新反讀全部 integration metadata／evidence，不只相信報告內的摘要。報告序列化後的 protocol trace 使用 JSON list 表示；bool／int／float 仍嚴格區分。

[六項摘要竄改驗證](../reports/stage12/retailrocket_session_knn_v39_typed_audit_checks_20261110.json)直接更動 operation counts、差分摘要、模組計數及 integration count／evidence／typed proof，全部被拒絕；沒有修改正式報告或重跑 query。

```powershell
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_typed_v39 --audit
```

驗收與核心入口沒有真實 measure 選項；worker CLI 僅接受同一人工 bundle 內的科學來源，不能把原真實 cohort 換進 synthetic marker。真實比較入口尚未封存／驗收，下一步先處理此入口，再對原固定 48 筆循序公平比較。沒有採用或加速比例，原 C1-S1 未採用結論、55／55 細層、170 可比較／232 歷史查詢與 reserved test locked 都不變；Stage 4 每日 10% 預算及 Dashboard 暫緩不變。
