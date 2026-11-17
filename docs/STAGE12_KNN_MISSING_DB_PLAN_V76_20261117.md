# V76｜缺 DB 負例修正與下一輪人工驗收計畫

本輪依 2026-11-17 指示，只讀 V75 既有失敗紀錄及程式文字，先訂精確修正與下一輪範圍，確認後才準備工具、封存及執行。原 golden、三組人工來源及全部 196 個子案例保留。V75 兩個正式窗口已用完且均失敗；本文件不改判結果，也不開第三窗。

## 第一步：既有失敗與精確修正規格

[第 2 窗公開收據](../reports/mainline/v75_synthetic_acceptance_revision2_20261117.json)記錄 38.063 秒、12 方法／75 子案例通過、1 子案例錯誤、21 方法／120 子案例未執行。`missing_required_case_ids` 的 121 項包含錯誤的 1 項及未執行的 120 項，不能全稱未執行。這是提前停止的合成驗收耗時，不能外推完整套件工時或真實 K1 成本。

### 失敗確切落點

`A09.missing_database` 先在 `query_work` 注入 `InjectedFailure`，保留已封存 reconstruction 與尚無 query commit 的 checkpoint，再把 `independent.sqlite` 改名為 `missing-db-preserved.sqlite`。新案例只接住 `ValueError／IntegrityError`，實際收到 `FileNotFoundError`。

既有 traceback 的順序是：

```text
run_full → writer.__enter__ → recover → get_stage
         → verify_sources → descriptor → path.stat → FileNotFoundError
```

這是凍結 CP 在 writer 恢復時驗證 reconstruction artifact 的拒收，尚未 yield 給 `run_full` 執行 `verify_full`。不是新的 query guard、SQL 或排名結果不一致。依據為既有 `stderr.log`、`suite_result.json`、新 A09 案例及凍結 CP 的文字；本輪沒有重開 checkpoint 或重新觸發例外。

| 既有證據 | 可支持的事實 | 不能延伸的結論 |
| --- | --- | --- |
| 原始錯誤與 traceback | FileNotFoundError、訊息含 WinError 2，目標為本次缺少的 independent.sqlite；拒收位於上述 CP 呼叫鏈 | 未保存原生 errno／filename 欄位，不能宣稱下輪精確 assertions 已通過 |
| 現存 reconstruction seal 與保留 DB | DB 為 36,864 bytes；SHA256 `40764506fee27166b9d006abd547626ec733cc5584aaadfcc3f7baa967b533b7` 與 seal 一致 | 沒有原輪前後快照，不能倒推當時全部檔案均未變 |
| 現存 checkpoint | independent.sqlite、candidate、acceptance 不存在；只有 reconstruction stage，ledger 為 0 records／0 chunks | 事後檔案查核不能補判 A09 通過，也不能取代後面 120 項 |
| 既有 writer_owner／session | 已釋放的 owner 例外為前次 InjectedFailure | 不是本次 FileNotFoundError 的 release／程序退出收據 |

完整來源描述及只讀核對結果見[修正規格收據](../reports/mainline/v76_missing_db_correction_spec_20261117.json)。人工 DB、逐筆 golden 與原始日誌仍在 Git 忽略路徑，公開只保存描述符及聚合事實。

### 待實作的唯一實質案例修正

只改 `A09.missing_database` 的預期例外與拒收證據，將以下 assertions 加在原 case ID 內。其餘四種 A09 變異維持原 `ValueError／IntegrityError` 預期；不改凍結 CP，不擴大成捕捉任意 `OSError／Exception`，也不調整科學比較、門檻或成功輸出。

| 時點 | 下輪必要判定 |
| --- | --- |
| 第一次注入故障後、rename 前 | 確認 reconstruction 已封存、ledger 為空、無 candidate／acceptance；快照 DB bytes／SHA、run／identity、stage／payload／chunk／pending 及 session／owner／recovery 的檔案清單與內容 |
| rename 後 | 原 DB 不存在；保留 DB bytes／SHA 與快照及原 seal 一致；seal 仍指向 independent.sqlite，不能改指向保留檔 |
| reopen 與恢復 | `open_store` 必須成功；只有進入 writer 恢復時才拒收。嚴格要求 `type(error) is FileNotFoundError`、`errno == errno.ENOENT`、正規化 filename 等於本次 run 的 independent.sqlite；在此 Windows 目標另核 `winerror == 2` |
| 拒收位置 | 在窄 `except FileNotFoundError` 內擷取 traceback，核對凍結 CP 來源及依序出現 writer／recover／get_stage／verify_sources／descriptor；不硬綁行號或本機絕對路徑。只在新版測試 helper 的 writer 區塊內、原 verify_full 呼叫前加計數，限定第二次恢復嘗試的呼叫次數為 0；第一次注入故障的呼叫不計入。原呼叫的參數、回傳值及例外照常傳遞，不 stub、不 monkey-patch 舊 worker／CP |
| 拒收後 | 保留 DB、run／identity、原 seal／帳本與既有 session／owner 內容不變；無新 DB、candidate、acceptance、queries／global／bootstrap stage、committed record 或 recovery receipt；不得偷偷重建或續算 |
| 案例證據 | 在 checkpoint 外保存本 case 的例外型別、errno／filename／winerror、相對來源呼叫鏈、前後檔案描述及 assertions 結果；原始人工 bundle／golden 描述仍相符 |

`assertRaises` 留存的例外會清除 traceback；因此須在例外仍活躍的窄 `except` 中取得框架資訊，再作判定或 re-raise，不能事後把空 traceback 當成位置證據。任何不符都讓原 case 失敗，不加第二個替代成功分支。

### 控制檔與科學證據的區別

CP 在 `recover` 前會 `check_budget(persist=True)`，所以不能要求整個 checkpoint 的 mtime、file identity 或全部檔案完全不動。原 FakeClock 固定下，budget 的內容可保持相同，但仍會 atomic replace；下輪應核對 run 身分／deadline／budget 不變、`consumed_seconds=0`、`last_utc_epoch=1000` 且無 `stop_requested.json`，不能接受此固定時鐘下的預算漂移，也不能拿控制檔寫入當成科學資料遭改寫。

本案例的前次 owner 已正常離開 writer；新 session／owner 是 recover 成功後才建立。缺 DB 在此之前拒收，故這個特定前提下應無新 session／release／recovery receipt，既有 session／owner bytes 應保留。這不是所有恢復分支的通用「控制檔不變」規則。FileNotFoundError 不屬 IntegrityError，凍結 CP 不寫 `integrity_failed.json`；不得為了測試而要求補寫或修改 CP。

## 第二步：待確認的 V77 完整合成驗收

V76 只封存本計畫。若確認，下一輪另立 V77，**最多一次完整正式窗口，沒有自動修正版或補跑**。不能使用 V75 的 revision 3、刪除舊開始標記或重用舊窗口目錄；V75 的原工具、案例契約、結果及失敗 DB 均保留。

### 最小接入差異

不只改一行例外或 runner 的輸出路徑：既有 bundle 固定 V75 seal 白名單，pipeline 固定 admission／自身子程序入口及 `v75/runs`，runner 固定測試模組、catalog、revision 與子程序入口。下一輪需要版本化這些控制接入，才能保留舊紀錄並接受新封存身分；科學 worker 不必重寫。

| 元件 | 確認後允許準備的差異 | 必須保留 |
| --- | --- | --- |
| 新 bundle_v77 | 新方法／fixture registry 的固定檔名、schema、SHA anchor、環境變數及新方法閉包核對 | 原 V75 fixture 路徑、manifest schema、generator／oracle 身分、角色／型別／路徑白名單與反別名規則 |
| 新 pipeline_v77 | 明確匯入新 admission、自啟動模組、版本標記、`v77/runs` 寫入邊界 | 原 worker_v75、鎖內 guard、來源核對位置、發布／停態／期限／帳法行為 |
| 新 runner_v77 | 單一 window1、新三測試模組及 catalog、全方法／子案例判定、全窗 deadline 與來源身分傳遞 | 逐項必要證據、fail-fast、不得缺漏／skip、子程序監督及保存跨期限的否決 |
| 三個新測試模組 | 明列 import／路徑／seal 名稱／版本身分的機械替換；A09.missing_database 依第一步補精確判定與測試端證據 | 其餘案例預期、故障點、門檻、原始排序；不得 monkey-patch 舊模組規避 admission |
| 新 catalog／方法對照 | 三個測試模組改為 v77，封存 34 個 qualified method ID 的原／新一對一映射 | 196 個 case ID 逐字不變、24 族及各族／方法歸屬不減；僅比較總數不足 |
| 新工具 seal／fixture registry | 工具封存實際來源閉包、動態子程序與案例來源及原 Stage8 schema；新 registry 重新綁工具 SHA | 原三個 manifest、78 個來源檔、golden／reference、原人工 2,000 draws bytes／SHA 不變；不執行 generator |

機械替換也需逐項 diff 與靜態複核；不能全域替換所有 `v75`。特別是原 fixture 的路徑、generator 字串與 manifest schema 代表原來源，必須留下 V75。原 V75 worker、凍結 CP／V1／V2／V4 的現有 bytes 不變，只列入新方法的來源閉包。

新增檔案名稱及 34 個方法映射列於[下一輪機器規格](../reports/mainline/v76_next_synthetic_acceptance_plan_20261117.json)，目前只是提案，不是工具 seal 或可執行授權。正式命令及 SHA 要等工具／registry 實際封存才填入，不提供可誤執行的佔位命令。

### 原來源與新輸出的邊界

| 路徑／資料 | 下一輪操作 |
| --- | --- |
| `shop-mysql-runtime/v75/fixtures/F-small`、`F-long`、`F-edge` | 只讀沿用原 manifest 與檔案；7／6、129／3、1／1 queries／visitors，F-edge 501 鄰居 |
| 原 V75 reference-evidence、formal/revision1／revision2、cases 及 runs | 原樣保存，不續跑、不拿舊成功項補新結果 |
| `shop-mysql-runtime/v77/cases` | 新案例的獨立工作複本及故障證據；來源破壞負例只改自己的複本 |
| `shop-mysql-runtime/v77/runs` | 新 pipeline／checkpoint／publisher 的人工 run，各 case 使用新身分 |
| `shop-mysql-runtime/v77/formal/window1` | 新唯一正式窗口的 request、一次性開始標記、stdout／stderr、suite 結果、停態及最終收據 |
| `reports/mainline/v77_*` | 未來的工具／registry 描述、聚合結果及原／新身分鏈；不提交人工 DB、逐筆 golden 或日誌 |

`.runtime` 已知是 junction；繼續使用上述實際忽略目錄並拒絕 alias，不重新放寬路徑規則。準備時核對原 registry 兩版的三組 fixture 描述完全一致；只重綁新工具，不重產資料、不改 expected、不重抽 draws。

### 完整驗收範圍與執行次序

| 測試群 | 必要方法／子案例 | 本次必須重新獨立驗證 |
| --- | ---: | --- |
| full | 17／106 | admission、來源與 runtime、完整 payload／golden、精確核心、七路資料、cache、DB、科學故障恢復、global 與原 draws |
| full_worker | 7／41 | chunk／EOF／時間邊界、atomic fault、同 writer 鎖內完成 guard，含 candidate／finalize／orphan 的正負例 |
| pipeline | 10／49 | 真程序恢復與退出身分、H1–H8、發布反核且不重算排名、停態、publication-only、期限／資源／跨 PID 預算與帳法 |
| 合計 | **34／196** | 全部逐項通過；不只補 A09 或剩餘 120 項，不拼接 V75 的 75 個通過項 |

1. **準備前提**：先取得本計畫確認。確認 Windows 與封存 runtime 身分仍符合原目標，核對來源及忽略路徑；這是執行身分檢查，不做時鐘校準。來源不符即停，不安裝或升級套件解套。
2. **新工具與案例封存**：只做允許差異；靜態核 AST、import／動態入口閉包、34 方法映射、196 IDs／24 族、完整判定及 deadline。此時不載入 suite、不跑 A09 單例、小樣本或預先驗收。更新 README、繁體中文 commit 並推 main。
3. **原人工來源重綁**：逐檔核對原 manifest／78 檔描述、新工具及原 golden 身分；生成只改方法綁定的新 registry，再更新 README、提交並推 main。任一來源不符都停止，禁止用現場新 hash 取代原封存權威。
4. **唯一正式窗口**：由新 runner 從頭載入全部案例，以新 window1 身分執行。人工負例的預期故障仍需正確判定；fail-fast 後缺失完整列出。正式前不得試跑消耗未記錄窗口。
5. **停態與收據**：只讀反核該窗口的來源、34／196 結果、退出／程序清理與期限否決，保留成功或失敗全證據；更新 README、提交並推 main。此後不再執行案例來補證。

### 停止條件與成功判定

| 條件 | 必須如何處理 |
| --- | --- |
| 準備超出邊界 | 若需要改科學 worker／凍結方法、golden、196 IDs、門檻、資料範圍，停止並另提差異；不能順手修到通過 |
| 準備耗時 | 準備累計達 120 分鐘仍無法完成工具與來源封存，就保存進度並停止，不啟動未封存驗收；這是工作檢點，不是效能測量 |
| 來源／權威不符 | 初始或再核 SHA、runtime、manifest、閉包或路徑不符，立即停止；不得現場自動重綁、不重產 golden。案例刻意破壞的獨立複本則按原負例要求判定 |
| 案例失敗或缺證據 | 非預期例外、錯誤拒收位置、狀態不符、重複／缺失 ID、skip、expectedFailure／unexpectedSuccess、必要輸出或程序證據不全，均不得通過；保留 fail-fast 及未執行清單 |
| 正式預算 | **一個窗口，900 秒成功截止；每個子程序最多 120 秒，且不得超過全窗剩餘時間**。沿用同一絕對／累積預算，不因重啟或發布重新計算 |
| 意外超時／監督失敗 | 全窗、內層或後代程序意外超時，無法確認退出身分或停態，停止並保留 failed／incomplete。A23 刻意注入的期限負例按原預期拒收驗收；不能把真正未預期超時包裝成負例成功 |
| 收尾超過期限 | 完整通過需要在期限內保存必要收據且沒有 deadline veto。超時後只允許安全清理與保存失敗證據，另記收尾時間；900 秒不是 OS 保證整個命令返回的硬上限 |
| 失敗或額度中斷 | 不開第二窗、不自動修正後補跑、不刪開始標記。保存已完成及未完成項；既有 V75 兩窗仍 failed，V77 也不能以局部通過宣稱整關成功 |

只有新一窗 **34 方法／196 子案例全數通過、無缺漏或跳過、原來源與輸出完整、必要程序退出及停態證據成立、期限內完成且無否決**，才能稱 V77 有限合成接入通過。這仍不代表真實 166,897 筆驗收、容量、成本或正式 K1−C1 比較成立。

### 預估時間與待確認內容

| 工作 | 規劃估計 |
| --- | ---: |
| 新控制接入、A09 精確判定、34／196 對照及靜態複核 | 60–100 分鐘 |
| 封存與來源重綁、唯一驗收、收據／README／Git | 20–40 分鐘 |
| 整輪工作 | **80–140 分鐘，約 1 小時 20 分至 2 小時 20 分** |
| 其中機器執行 | 暫估 2–10 分鐘，已含整輪；正式成功窗口最多 15 分鐘 |

以上是按新增控制接入及審閱工作拆出的估計，不是新實測。2–10 分鐘只沿用 V74 的待驗估計；V75 的 10.812／38.063 秒都在前段失敗，不能據此推算完整套件會多快。80–140 分鐘不是保證；準備 120 分鐘檢點與正式 900 秒是分開的停止規則，清理／證據保存時間也不拿來延長成功期限。

本計畫已完成獨立靜態複核：16 個來源描述相符、34 方法一對一映射、196 IDs 逐字同序與 24 族歸屬一致；兩版原 registry 的 fixture 描述完全相同。這是文件與既有 bytes 核對，不是新工具或案例行為通過。

**待確認：是否依此 V77 範圍準備、先封存並推送，再執行最多一次完整 34／196 合成驗收？** 本次要求「確認後再執行」，因此 V76 到此只交付可審閱計畫；使用剩餘額度的許可不等於提前啟動。沒有工具準備、fixture 生成或新驗收，原真實資料一律不重跑。

## 本輪進度與界線

| 步驟 | 狀態與實際結果 |
| --- | --- |
| 1. 缺 DB 根因及精確修正 | 已查既有證據並列必要 assertions，完成獨立靜態複核；程式未改、未驗收新 assertions |
| 2. 下一輪完整範圍、停止與估時 | 已列 V77 新控制接入、原來源沿用、34／196 完整驗收、單窗 900 秒與 80–140 分鐘估計；等待確認 |
| 原資料及結果 | 原 golden、34 方法／196 子案例、V75 兩窗失敗均保留 |
| 新執行 | 新測試／fixture 生成／量測／真實重跑／Linux／B／C／D／原 48 筆均 0 |

真實 166,897 筆完整獨立反讀、容量與成本仍未完成，`T_plan=null`，保留測試 locked、V46 暫不採用。每日 10% 提醒的待資料與優先順序沿 V71；Dashboard 仍待適用程度確認。
