# V77｜保留原 golden 的一次完整合成驗收

2026-11-17 使用者確認依 [V76 計畫](STAGE12_KNN_MISSING_DB_PLAN_V76_20261117.md)準備工具與案例，先封存推送，再執行最多一次完整合成驗收。原 golden 與全部 196 子案例保留；正式窗口最多 15 分鐘，失敗不補跑，不重跑真實資料。每步更新 README、繁體中文 commit 並推 main。使用剩餘額度不延長正式窗口，也不開第二窗。

**最終結果：唯一正式窗口 94.047 秒，failed；147 子案例通過、1 失敗、48 未執行。已停止且沒有補跑。** A09 精確缺 DB 判定通過；整套真程序恢復／發布驗收仍未完成。

## 第一步：執行前工具與案例封存

新增 bundle／pipeline／runner 三個控制模組與三個測試模組，保留原 worker_v75、凍結 CP／V1／V2／V4。人工來源仍指原 V75 fixture／manifest／generator／oracle；新工具只接受固定 V77 工具 seal 與 registry，沒有 revision fallback。新輸出只在實際忽略目錄 `shop-mysql-runtime/v77`，不經 `.runtime` junction。

| 項目 | 實際準備結果 |
| --- | --- |
| 來源封存 | 34 個 Python 來源閉包，加原／新 case catalog，共 36 個方法／案例描述符；動態三測試模組及子程序入口明列 |
| runtime | Windows／CPython 3.12.10／NumPy 2.5.4／psutil 7.2.2／SQLite 3.49.1／little endian，與原封存相符；非時鐘校準 |
| 原來源保留 | 原工具 35 個描述及 Stage8 schema 描述均相符；未修改舊工具、案例、golden 或既有失敗紀錄 |
| 案例契約 | 34 方法一對一映射、196 個 IDs 逐字同序、24 族及三模組歸屬相符；17／106、7／41、10／49 |
| 唯一案例判定修正 | A09.missing_database：精確 FileNotFoundError／ENOENT／filename／WinError 2／凍結 CP 呼叫鏈，第二次恢復未進 verify_full，前後科學證據及固定預算保留 |
| 靜態驗證 | 六個新 Python 來源 AST、來源閉包、案例映射及獨立審閱通過；其餘案例經明列機械替換正規化後 AST 一致 |
| 此步執行狀態 | suite 載入／測試／新 fixture 生成／正式窗口均 0；靜態核對不代表行為驗收通過 |

A09 的證據寫在該人工 case 的 checkpoint 外。只在新版測試 helper 的第二次 writer 區塊內、原 verify_full 呼叫前加計數；不替換 worker。缺 DB 的窄例外判定之外，其餘四種 A09 期待維持原樣。budget 允許正常 atomic replace，但固定時鐘下 consumed=0、last_utc_epoch=1000 與原 run／期限／budget 都須一致；原 session／owner 不可偽裝成本次例外收據。

[工具 seal](../reports/mainline/v77_tool_seal_20261117.json)綁定 V76 修正／下一輪規格及實際方法來源。工具與 README 推送後，才進第二步：逐檔核原三組 manifest／78 檔並建立只重綁方法身分的新 registry；不執行 generator 或重產 expected。

## 正式窗口與期限層次

完整套件的 suite 載體沿用 V75 的 **900 秒整窗監督**；它不是另一個 120 秒科學工作任務。套件啟動的 pipeline／worker／publisher 等工作子程序各至多 **120 秒**，還須受該 run 剩餘預算與整窗剩餘時間限制。這裡明確區分 V76 所稱「子程序」的工作層及正式套件載體，沒有延長任一既有工作子程序上限。

V77 額外把正式 deadline 傳入工作啟動器：啟動前、監督迴圈及接受退出收據前都檢查整窗期限，timeout 取原 watch／run 剩餘／120 秒／整窗剩餘的最小值。真正整窗超時拋 TimeoutError，不能混入預期 FakeClock BudgetExceeded 負例。A23 原有人工期限負例保持原判定。

runner 只接受 `--window 1`，正式目錄固定 `shop-mysql-runtime/v77/formal/window1` 且必須新建；沒有修正版、重試或重新設定開始標記的路徑。全 34 方法／196 子案例須在同一窗通過，無 skip／缺漏／重複 ID／預期失敗冒充通過；必要收據、退出與停態證據齊全且沒有 deadline veto 才能成功。整窗或內層意外超時、來源不符、案例失敗均停止，未執行項完整列出。

900 秒是成功截止，含必要收據保存；逾時後只允許安全清理及保存失敗證據，不能把清理延時算成通過。原 V75 兩窗仍 failed，不併入 V77 通過項，也不開 V75 第三窗。

## 第二步：原人工來源已核對並重綁

[新 fixture registry](../reports/mainline/v77_fixture_seal_20261117.json)沿用原三個 manifest 及 78 檔，共 8,043,982 bytes。兩版原 V75 registry 的 fixture 描述完全相同；golden、reference、原人工 2,000 draws 與原 generator 身分保留，沒有生成新資料或重抽 draws。來源、路徑、硬連結及新方法描述均已核對，並完成獨立唯讀複核。

| 人工來源 | queries／visitors | 檔數／bytes |
| --- | ---: | ---: |
| F-small | 7／6 | 26／2,216,565 |
| F-long | 129／3 | 26／3,465,659 |
| F-edge | 1／1 | 26／2,361,758 |

準備指令完成核對及 registry 寫入後，最後顯示摘要使用 Windows `str(Path)`，含反斜線，被只接受 POSIX 相對路徑的描述函式拒絕。此錯誤發生在摘要顯示，不是來源 SHA 不符；已保留[顯示拒絕與既存 registry 核對紀錄](../reports/mainline/v77_fixture_binding_review_20261117.json)，僅唯讀確認原寫入結果，未修改工具／registry、重產 fixture 或重開準備驗收。原工具呼叫是先後順序的執行依據；命令末段與 traceback 摘錄另保存在忽略路徑，標示為既有工具輸出的抄錄，並非重新執行或原生日誌。

工具 seal SHA 為 `49668e4cd23a48759b4337eefd14dfb5c2b32e4204c3d0ed860f61abc22936e7`；fixture registry SHA 為 `afa494940682ebd2d52c63ed50dbf8bb00914bb1762eb992b34df9f7f3996353`。工具先以 c8b0d23 推送、來源 registry 再以 d38be19 推送，之後才執行下列命令。**此唯一窗口已消耗並失敗，命令只供溯源，不可重複執行。**

```powershell
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_acceptance_v77 --window 1 --method-sha 49668e4cd23a48759b4337eefd14dfb5c2b32e4204c3d0ed860f61abc22936e7 --fixture-sha afa494940682ebd2d52c63ed50dbf8bb00914bb1762eb992b34df9f7f3996353
```

## 第三步：唯一正式窗口失敗並停止

[正式結果與完整缺漏](../reports/mainline/v77_synthetic_acceptance_window1_20261117.json)保存本窗實際結果：94.047 秒、外層退出碼 1，非超時、非來源身分失敗、無 deadline veto。沒有第二窗或失敗後新增測試。此秒數只描述合成驗收與期限，不是解碼、SQL 或真實全量的效能結果。

| 測試群 | 方法通過／失敗／未執行 | 子案例通過／失敗／未執行 |
| --- | --- | --- |
| full | 17／0／0 | 106／0／0 |
| full_worker | 7／0／0 | 41／0／0 |
| pipeline | 0／1／9 | 0／1／48 |
| 合計 | **24／1／9** | **147／1／48** |

34 方法／196 子案例從頭以本窗獨立判定，沒有拼接 V75 結果。`missing_required_case_ids` 的 49 項等於失敗 1 項加未執行 48 項；錯誤 0、assertion failure 1、跳過 0。不能把 147 項通過當成整關成功。

A09.missing_database 已實際通過精確 FileNotFoundError、errno=2、WinError=2、正確檔名及五個凍結 CP 框架；open_store 成功、第二次 verify_full 呼叫為 0，固定 budget 與原 DB／seal／session／owner 保留。事後唯讀核對其外部證據及現存 checkpoint 相符，原失敗不因此改判。完整 payload／golden、原 draws、科學故障恢復、chunk／EOF 與鎖內完成 guard 亦通過本窗必要案例。

### A12 的實際失敗與原因界線

真程序案例原設計在第 65 次 `query_verified` 用 `os._exit(9)` 中斷，應已提交一個 64 筆 chunk，再驗證第二次完整恢復。既有 worker 日誌實際記錄 `sqlite3.OperationalError: interrupted`，落在 SQL overlap 的 `db.execute`；worker 退出碼為 1，沒有 stop request，也未標為 timeout。案例的寬 `assertRaises(RuntimeError)` 先接住這個非預期失敗，接著檢查 prefix 時才發現 **0 != 64**。

現存 checkpoint 沒有 committed chunk，只有 97,790 bytes／25 行的未提交 payload；這 25 行不能作有效 prefix，也不能據此補算通過。candidate、acceptance、final_seal 都不存在。第二次 pipeline 恢復呼叫尚未執行；沒有證據顯示恢復曾刪除已提交的 64 筆。

唯讀原碼發現 pipeline 直接傳 `watch=store.check_budget`，CP 回傳非空 dict，而 worker 的 SQLite progress callback 是 `lambda: (watch() or 0)`，因此會沿用該 dict。這個接入回傳值問題與實際 interrupted 錯誤相符；V75 也已有相同接入，但前兩窗都未跑到此真程序案例。**回呼內部錯誤未被原日誌保存，完整因果仍屬靜態推論，未另行重現確認。** 本輪沒有改 worker、CP、pipeline 或案例來補跑。

### 保存、唯讀核對與仍缺項目

6 個正式窗口檔、24 個失敗 run 檔及 A09 外部證據均保存描述符；原始內容留在 Git 忽略目錄。36 個方法描述、Stage8 input、三份 V76 規格、三個 manifest 及原 78 檔事後仍相符。9 個已觀測 PID＋create_time 身分均已不存在；未觀測後代不宣稱全面保證。

[結果唯讀反核](../reports/mainline/v77_readonly_result_audit_20261117.json)已完成：公開報告的33次描述符核對（32個唯一證據檔）相符，案例計數與失敗因果界線通過獨立審閱；驗收判定仍是failed。

真程序 prefix 恢復未通過，A16–A24 的退出身分、candidate／finalize 重入、H1–H8、publisher、停態、publication-only、期限資源及完整帳法共 48 子案例未執行。本窗上限已用完；下一步可先依這批既有紀錄訂 watch 回傳契約與預期退出碼的精確驗證，再另提範圍。剩餘額度不能取代新窗口授權；不自動修正或重跑。

## 操作順序與本輪進度

1. 封存工具、案例及來源閉包，更新 README／提交／推送。
2. 核原三組人工來源，封存新 registry，更新 README／提交／推送。
3. 以第二步實際 seal SHA 執行唯一正式窗口；上列命令只能執行一次。
4. 只讀反核該窗結果、來源、退出及期限否決，保存聚合報告與完整缺漏，更新 README／提交／推送；不補跑。

| 步驟 | 目前狀態 |
| --- | --- |
| 工具與案例 | 已先封存推送；本窗24方法／147子案例通過，完整行為驗收仍未通過 |
| 原人工來源重綁 | 已核對三個 manifest／78 檔並封存；新生成 0，摘要顯示拒絕紀錄保留 |
| 唯一正式窗口 | 1／1已消耗，94.047秒failed；1子案例失敗、48未執行，已停止不補跑 |
| 真實研究／量測 | 真實資料、原 48 筆、Linux、B／C／D 均未啟動 |

工作估 80–140 分鐘、機器執行暫估 2–10 分鐘只是 V76 規劃；準備達 120 分鐘仍未完成工具與來源封存就停止。真實 166,897 筆完整獨立反讀與成本仍缺，T_plan=null、保留測試 locked、V46 暫不採用。每日 10% 提醒與 Dashboard 優先順序沿 V71。
