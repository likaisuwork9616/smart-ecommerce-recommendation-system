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

## 本輪進度與界線

| 步驟 | 狀態與實際結果 |
| --- | --- |
| 1. 缺 DB 根因及精確修正 | 已查既有證據並列必要 assertions，完成獨立靜態複核；程式未改、未驗收新 assertions |
| 2. 下一輪完整範圍、停止與估時 | 整理中；完成可審閱計畫後才請使用者確認 |
| 原資料及結果 | 原 golden、34 方法／196 子案例、V75 兩窗失敗均保留 |
| 新執行 | 新測試／fixture 生成／量測／真實重跑／Linux／B／C／D／原 48 筆均 0 |

真實 166,897 筆完整獨立反讀、容量與成本仍未完成，`T_plan=null`，保留測試 locked、V46 暫不採用。每日 10% 提醒的待資料與優先順序沿 V71；Dashboard 仍待適用程度確認。
