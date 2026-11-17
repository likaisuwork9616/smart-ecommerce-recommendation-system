# V78｜watch 回呼與角色退出的精確驗證規格

本輪只讀 V77 既有失敗紀錄及相關來源文字，整理修正範圍與下一輪規格。未修改工具、載入 suite、呼叫 checkpoint／SQLite、啟動程序或新增量測。原 golden、78 個人工來源檔、34 方法／196 子案例及 V77 的失敗判定均保留；確認後才準備及執行。

## 第一步：既有證據與精確契約

### 可以確定的事實與尚缺證據

[V77 收據](../reports/mainline/v77_synthetic_acceptance_window1_20261117.json)記錄唯一窗口 94.047 秒 failed：147 子案例通過、1 失敗、48 未執行。A12 預期在第 65 次 query_verified 用 os._exit(9) 中斷，再以 64 筆有效 prefix 恢復；實際遇到 SQL OperationalError: interrupted，接著 0 != 64。現存只有 25 行／97,790 bytes 的未提交 payload，無 committed chunk；第二次 pipeline 恢復沒有執行。

| 證據 | 已觀測或由原碼直接可知 | 尚不能推出 |
| --- | --- | --- |
| worker_failure／traceback | SQL overlap 的 db.execute 發生 interrupted，非預期的故障出口 | 回呼內部錯誤未被保存，不能確證本次中斷的完整因果 |
| pipeline→worker watch | 直接傳 store.check_budget；它正常回傳非空 dict | 不能以來源推論冒充新的 callback 實驗結果 |
| 兩個 SQLite callback | V2 reconstruction 與 V75 query 都是 lambda: (watch() or 0)，頻率 10,000 | 只改 query_watch 不涵蓋 reconstruction |
| RuntimeError 期待 | 目前 A12 可接住非預期 pipeline RuntimeError；BudgetExceeded 也是 RuntimeError 子類 | 接住例外不等於預期中斷已發生，更不能算恢復成功 |
| checkpoint | 0 committed chunk，保留未提交 payload，無 candidate／acceptance／final_seal | 未提交行不算有效 prefix；沒有證據顯示恢復曾刪掉 64 筆 |

另有退出身分缺口。下表是既有 JSON 的直接比對，未查目前程序或重啟任何程序：

| 角色 | 退出收據的啟動 PID | 角色自報 PID | 自報身分在 tracked 中 | 該退出收據的 code |
| --- | ---: | ---: | --- | ---: |
| worker | 20076 | 24856 | 是，tracked 共 3 個身分 | 1 |
| pipeline | 17572 | 2252 | 是，tracked 共 6 個身分 | 1 |

兩者的 PID／create_time 並不相等。現存收據把 Popen 啟動程序的身分和退出碼存為 identity／exit_code；tracked membership 只表示角色曾被列入後代觀測，**不證明啟動程序的退出碼就是角色本身的退出碼**。V77 原報告中的 worker exit 1 是其 worker_exit 收據欄位值；本輪更精確區分它與自報 worker 的角色退出證據，原紀錄不改寫。啟動中介的種類、是否轉送同碼及實際角色退出碼，不能單靠這些收據判定。

來源、原失敗檔案描述及本輪規則見[契約規格收據](../reports/mainline/v78_watch_exit_contract_20261117.json)。公開只保存描述符與必要聚合狀態，原始人工資料、DB、完整日誌留在忽略路徑。

### W：watch 的最小修正與驗證

只在未來新版 pipeline 的 _worker→verify_full 邊界加入轉接，覆蓋同一 watch 傳往 reconstruction、query 及 global 的路徑。原 CP 的預算 API、worker_v75、V2／V4、SQL 與 progress handler 都保持 bytes 不變。

| 規則 | 未來必須驗證的條件 |
| --- | --- |
| W1 正常回傳 | 每次 adapter 呼叫恰好呼叫原 bound check_budget() 一次，不新增參數，維持預設 persist=False；捨棄其回傳值並嚴格 return None |
| W2 不改預算 | 不自行讀時鐘、不重設預算、不加重試或額外檢查；原函式的狀態更新、副作用及拒絕仍發生 |
| W3 不判真假 | 不用 and／or／bool 等轉接返回物件；以不允許求 truthiness 的假返回物件驗證只捨棄、不判真假 |
| W4 直接例外 | adapter 本身不 catch／吞掉／轉型；直接 Python 邊界以 BudgetExceeded 及一般 sentinel error 驗原例外物件身分、單次呼叫及無後續成功動作 |
| W5 callback 表達式 | 純 Python 的 lambda: (watch() or 0) 結果須是 exact int 0；這只驗表達式，不能宣稱真正 SQLite callback 已被觸發 |
| W6 真接入 | 新 pipeline 實際採用同一已封存 adapter；原 F-long 完整流程的正常 SQL 接入仍須由 A12 及全套判定，不能拿假 checker 通過代替 |
| W7 SQL 例外界線 | 經 SQLite callback 後不要求仍是原例外型別／物件；任何未預期 interrupted 或停止證據仍是失敗，不可用泛用 RuntimeError 當作預期故障成功 |

完整 F-long 成功也不單獨證明 reconstruction／query 兩個 SQLite callback 均實際觸發，不能據此確證舊窗因果。

W1–W5 的假 checker assertions 納入原 A12.prefix_crash_recovery 同一 case ID，在同一正式窗口、真程序部分之前完成，不在封存前小試。證據另寫測試外部目錄；不塞入 checkpoint 或既有固定 episode 檔案集合。此規格不新增 SQLite 原始例外追蹤器，也不聲稱未來通過就已單獨重現舊窗因果。

### E：退出碼必須屬於正確角色

未來須先確定能持續綁住同一程序實體的退出觀測方法。啟動程序與執行角色分欄保存；不得複製角色自報 PID 到啟動程序收據、套用啟動碼，或以 PID 消失／tracked membership 當作精確退出碼。

所有退出碼都要求 type is int，不接受與 0／1／9 相等的 bool、float 或字串。

| 規則 | 第一段中斷必須具備的證據 |
| --- | --- |
| E1 原請求 | 唯一第一 episode；同 request SHA／run／來源身分；scenario 精確為 query_verified、worker_after=65 |
| E2 角色準入 | 角色先發布 ready 身分，監督者核對啟動關係及 PID＋create_time＋boot，取得可持續識別該角色的觀測依據後才 ack；角色在此之前不可開始科學工作 |
| E3 worker 退出 | 對該實際 worker 的獨立退出觀測，exact-int code=9、normal_observed=false、stop_request=null，無 worker_failure.json；不能只有 launcher code=9 |
| E4 故障命中 | 在既有 worker.log 留唯一結構化 marker：角色及其 PID／create_time／boot（或已封存 ready／ack 的描述符）、episode、request SHA、fault point、命中次數 65、預定 code 9，且須綁定同一獨立觀測角色；flush／fsync 後才走故障出口。marker 不是獨立退出證據 |
| E5 pipeline 退出 | 對實際 pipeline 的獨立觀測 exact-int code=1；failure 收據精確對應內層 worker code=9 且非 timeout。pipeline 本身不期待 code=9；啟動程序是否轉送同碼另記 |
| E6 停態及反例 | 所有已觀測身分均確認停止；缺角色碼、身分重用／錯置、缺 ack、marker 不符、意外錯誤／stop request 均拒收。未觀測後代不全面保證 |

外層 RuntimeError 只記錄入口如何結束，不能單獨作為成功依據，也不以改寫錯誤訊息掩蓋其他失敗。新增角色觀測不放寬凍結 CP 的正常退出守門；交給 finalize 的身分及 code 必須來自真正角色的獨立收據。

### P：先驗 prefix，再准第二次恢復

E1–E6 都成立後，先保存第一 episode 的退出、故障 marker 與 CP 前狀態描述，再驗 committed chain。chunk 0 必須同 run、count=64、ordinal=0..63、previous SHA=null，payload 的 bytes／SHA、完整列界線、key 鏈及內容與原 golden 前 64 筆一致。原程式在 append_verified 後才呼叫 query_verified，第 65 筆可能留下未提交尾巴；不能要求 payload 目錄僅有 64 行，也不能把尾巴算入有效 prefix。

上述條件任一不符就停止該 case，不呼叫第二次 pipeline。若完整成立，第二次仍沿用同一 request／run／來源／原 deadline 與累積預算，核對原 chunk／payload bytes 不變、129 筆完整 golden、原 2,000 draws、worker／publisher／pipeline 各角色正常 exact-int code=0、發布證據及停態 final seal。不能先恢復，再補造「之前已有 64 筆」的證據。

## 第二步：修正邊界、停止條件與估時

### 分開處理回呼修正與觀測來源缺口

watch 的正常回傳契約已能由現有程式界面訂出；角色退出的獨立觀測方式則尚未確定。**不建議只補一行 watch 就再開完整 196 子案例窗口。** 建議下一輪先做 Q0「角色退出觀測來源與最小接入可行性」，Q0 完成後仍須另確認工具與完整驗收，不能自動往下執行。

本輪沒有核新的官方 API 文件、檢查目前程序或實測新觀測方式；下表是待評估的修正邊界，不是已證明可用的 adapter。

| 範圍 | 未來可準備的修正 | 保留／禁止事項 |
| --- | --- | --- |
| D1 watch 接合 | 新版 pipeline 在 verify_full 邊界包原 check_budget，依 W1–W7驗證 | 不修改 CP 回傳值、原 worker／V2／V4／SQL 或 10,000 指令頻率；不吞錯、重試或改預算 |
| D2 角色觀測 | 評估 Windows 持續綁定同一程序實體的 OS 退出觀測，配合 ready／ack，分開 launcher 與 role 收據 | 實際 API、權限、生命週期、create_time／boot 正規化與快速退出處理尚待 Q0；不假設 PID 輪詢或 launcher 會轉送同碼 |
| D3 啟動與路由 | pipeline／worker／publisher 明確走 role 路由，工作前完成握手；泛用人工命令另走 generic_synthetic | 業務角色不得降級走 generic；不能依 log／failure 檔名推定它是角色程序 |
| D4 證據交付 | 新版收據明分啟動碼與角色碼；只有經獨立核對的角色身分／碼可交給原 finalize。新增外部觀測證據須被 publisher 反核及 final seal 涵蓋 | 不改寫 V77 舊欄位的歷史含義，不把自報或 marker 當 OS 退出證據；不放寬原 CP 守門 |
| D5 案例與判定 | 原 A12 加 W／E／P assertions；依觀測設計補 A16 的身分／未知退出、A20 的證據篡改、A21 的閉合／停態、A23 的路由與期限 assertions | 原 196 IDs、34 方法語義映射、24 族、A09 已補精確判定、所有原期待及門檻保留；不以新數量代替逐項映射 |
| D6 版本及來源 | 確認工具階段後，另版 bundle／pipeline／runner／觀測 helper／三測試模組與新 catalog、seals、輸出 namespace；來源閉包按實際程式重列 | 不重用 V77 window1、不刪標記、不改 V77 工具或失敗檔。原 V75 fixtures／manifest／generator／golden／reference／draws 保留，只重綁新工具 SHA |

### Q0 必須先解決的兩個接入問題

**泛用程序不能冒充角色程序。** A23.resource_process、monitor_process、descendant_timeout 使用 `-c` 人工命令，沒有角色 ready／ack；其中的 worker_failure.json 是人工錯誤標籤，不是 worker 身分證據。Q0 要列出明確路由欄位及呼叫點，保留原泛用命令的 exit／timeout／stop 要求；不能把 handshake 加到所有 _launch 後，再刪改 A23 期待讓它過。

**外部證據也必須進入交付鏈。** 可評估沿用三欄 role_identity.json 作 ready 的候選，另將 ack／監督者角色退出證據放在專屬 control/episodes 路徑；實際欄位與路徑須由 Q0 固定。需有精確白名單、角色／request／episode／方法身分綁定、檔案描述及發布／final seal 的反核。原 snapshot(internal) 未涵蓋的檔案不能因此漏驗；仍更新的 budget 控制檔也不能被整包宣稱不可變。故障 marker 優先用既有 worker.log，保持原 EPISODE_FILES 集合，不任意增加寬泛白名單。

### 建議先確認 Q0，暫不授權實作或完整重驗

Q0 的目標是交付可審閱的觀測來源與接入設計。沿用 V77 保存的 Windows／CPython 3.12.10／NumPy 2.5.4／psutil 7.2.2／SQLite 3.49.1 身分作相容目標，不安裝、升級或切換平台。

| Q0 交付物 | 必須寫清楚的內容 |
| --- | --- |
| Q0-1 官方語義及來源 | 候選 API 的一手來源、所觀測的是哪個程序、退出碼來源、持有期、權限及快速退出／身分重用限制；不只看 API 名稱 |
| Q0-2 身分與握手 | PID／create_time／boot 的來源與精確正規化、取得可持續觀測依據的時點、ready→核對→ack→工作→退出順序；不能只匹配近似時間或 PID |
| Q0-3 來源與交付契約 | launcher／role 證據分欄，原三欄身分與新證據的關係，固定路徑／schema／白名單、publisher 與 final seal 的涵蓋範圍 |
| Q0-4 接入差異與案例 | role 與 generic_synthetic 分流、A12／A16／A20／A21／A23 的必要 assertions，原 196 IDs 的保留映射與失敗分支 |
| Q0-5 後段確認提案 | 選定候選及未解決限制、具體新檔案／封存順序、合成驗收範圍、修訂後估時與停止條件；仍請使用者確認後才實作 |

Q0 可以讀官方文件及必要的既有啟動設定／相關來源文字，不寫工具、不載入 suite、不啟動角色程序、probe 或任何實驗。需要實機或合成執行才能判定的能力，明列為後段待驗；文件可行不等於實際可用，更不代表退出觀測已通過。

### 停止規則

| 關卡 | 停止或不得放行的條件 |
| --- | --- |
| 本輪 V78 | 只讀既有紀錄及寫規格，到此不新增 API 能力查驗、工具或執行 |
| 下一輪 Q0 | 來源語義不足以綁定同一角色退出碼、身分正規化不明、必須靠未授權 probe 才能決定，或滿 60 分鐘仍無具體可審閱方案，就保存缺口並停止；不自動改做實機驗證 |
| 後段準備（尚未授權） | 必須修改 frozen 科學方法、原 golden／196 IDs、放寬門檻或擴大資料／平台範圍即停；準備滿 120 分鐘仍不能完整封存就停，不啟動套件 |
| 後段來源與身分 | 任一原 SHA、runtime、角色來源、ready／ack 或觀測身分不符，無法取得可歸屬的角色退出碼，或角色在 ack 前開始科學工作，皆不得通過 |
| 後段案例 | E／P 任一條件不符，不進第二次恢復；意外錯誤、timeout、缺失／重複 ID、skip／expectedFailure 等均不得以預期故障包裝成通過 |
| 後段窗口（尚未授權） | 最多一個完整窗口；suite 載體 900 秒成功截止，工作子程序最多 120 秒且受整窗剩餘限制。任何失敗不修後補跑；收據跨截止須否決，逾時收尾只保存失敗證據 |
| 額度或外部中斷 | 保存已完成與未完成項，不用局部通過取代完整判定；剩餘額度不擴張授權或增加窗口 |

### 估時與確認邊界

| 工作 | 預估時間與依據 |
| --- | --- |
| **建議下一輪：Q0 可行性** | **30–60 分鐘**，含官方來源／身分語義、接入差異、文件複核與 README／Git；60 分鐘仍不能釐清即停，必要的缺口保存另行收尾 |
| Q0 後的工具與完整驗收 | 暫估 **100–160 分鐘**：工具與靜態複核 70–120 分鐘，封存／唯一驗收／反核／README／Git 30–40 分鐘；Q0 完成後再修訂並確認 |
| 後段機器執行 | 完整套件尚未跑完，暫保留 2–10 分鐘的規劃區間，已含後段總估計；不保證完成，整窗成功截止仍 15 分鐘 |

以上均是工程估計，不是新量測。V77 的 94.047 秒在前段失敗，不能線性外推完整套件；新增角色觀測也尚未選定可實作方法。Q0 不包含任何新窗口，Q0 完成亦不能自動開後段驗收。原 196 子案例在此階段保持原封存狀態，未執行項仍是未執行，並未省略或改判。

**待確認：下一輪是否先做 Q0 角色退出觀測來源與最小接入可行性（30–60 分鐘），不實作、不啟動程序或驗收？** 因目前指示要求「確認後再執行」，且新發現的身分歸屬不能由既有紀錄補證，本輪先完成此可審閱範圍，完整修正版及 196 子案例窗口另行確認。

規格已完成獨立靜態審閱：11個來源描述相符，原34方法／196 IDs同序及24族歸屬均保留；這是文件與既有來源核對，不是角色觀測或行為驗收通過。

完整機器規格見[修正範圍與分階段計畫](../reports/mainline/v78_correction_scope_plan_20261117.json)。

## 本輪進度

| 步驟 | 狀態 |
| --- | --- |
| 1. 既有證據與 W／E／P 精確規格 | 已列 watch 正常／例外邊界、角色退出缺口及 prefix 前置條件；尚未實作或驗收 |
| 2. 修正範圍、停止與估時 | D1–D6 邊界、Q0 交付及停止已列；建議先確認 30–60 分鐘 Q0，後段工具／完整驗收另確認 |
| 保留與執行界線 | 原 golden／196 子案例／V77 failed 保留；新工具、測試、量測、真實資料重跑均 0 |

真實 K1 完整獨立反讀、容量與 T_plan 仍未完成，保留測試 locked、V46 暫不採用；每日 10% 提醒與 Dashboard 優先順序沿 V71。
