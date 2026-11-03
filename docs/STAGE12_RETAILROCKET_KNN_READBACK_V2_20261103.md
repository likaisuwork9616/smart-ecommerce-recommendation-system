# Stage 12：V2 獨立反讀、恢復驗收與成本決策

本輪依序實作 V2、驗收合成等價與故障恢復，再執行有界工程成本探測。K1−C1 尚無正式結論，預留測試維持 locked。V2 用於核對原有已曝光 validation 輸出，不產生另一輪主要訓練、對照排名或主要 bootstrap，也不把 V1 partial 改成成功。

實作契約見 [V2 契約](contracts/retailrocket_session_knn_readback_v2.json)，前輪設計保留於[成本與恢復規劃](STAGE12_RETAILROCKET_KNN_READBACK_COST_AND_RECOVERY_PLAN_20261030.md)。本輪實測與決策以[合成驗收報告](../reports/stage12/retailrocket_session_knn_v2_synthetic_acceptance_20261103.json)及[成本探測報告](../reports/stage12/retailrocket_session_knn_v2_cost_probe_20261103.json)為準。

## 本輪實際結果與決策

| 項目 | 實際結果 |
| --- | --- |
| 合成／回歸驗收 | 185 項全過：102 項 V2＋83 項既有 K1，0 失敗／錯誤／略過 |
| 來源綁定 | 440 份、約 10.44 GiB；來源與原主要產物只讀，停止後另作完整 bytes 保存核對 |
| 單次明列的來源 SHA 階段 | 40.419 秒；create／writer 的其他再核及啟動／context 等仍包含於整輪用時，另列 132.597 秒未落在明列階段計時器內的成本 |
| 獨立重建 | 840.406 秒完成；全部 1,180,256 train sessions、1,587,436 distinct session-item membership 及 fit 身分通過 |
| 整窗分層 | 784.717 秒後到期中斷，未完成 166,897 queries 的全窗分層；沒有完整樣本或 query 計時，不計完成比例 |
| 實驗總窗口與實際退出 | 1,798.14 秒；臺北 12:16:13.110974 請求期限停止，12:16:13.246607 觀察退出碼 1，原截止 12:16:15.093927；不是成功完成 |
| 資源抽樣峰值 | 程序樹加 supervisor 821,338,112 bytes，約 0.765 GiB；namespace 477,454,896 bytes，約 0.445 GiB；OS 暫存未完整盤點，非完整上界 |
| 全量決策 | **暫不啟動**：固定樣本及必要後續成本仍不足，不能計完整 T_plan、工時上界或六小時可完成性 |

worker 收到 supervisor 停止請求後以 TimeoutError 退出，完整退出收據已保存。停止後的來源／已封存 DB／六份 gate 核對屬唯讀保存稽核，時間另列成本報告，未延長實驗或繼續分層。0 新主要 fit／validation／bootstrap，0 最終選模／refit／保留測試；K1−C1 仍未驗收。

## 實作與界線

| 元件 | 行為與核對依據 |
| --- | --- |
| [獨立 SQL 核心](../scripts/retailrocket_session_knn_sql_v2.py) | 原始 train baskets 的 DISTINCT membership；SQL 完整正交集、Fraction Jaccard、全部 pool SHA、500 鄰居與邊界平手。unknown history 商品仍計分母；只排除同 visitor/start 的精確 self session |
| 候選與投票 | SQL 讀取所有選中 membership，精確加總有理數票；完整因果 catalog 的其餘商品為零，依原 P0 count／numeric ID 補位。預建不可變 catalog 時間索引，嚴格使用 first_view_ms < query_ms |
| [四臂核對與重播](../scripts/retailrocket_session_knn_readback_v2.py) | 沿用凍結獨立 oracle 的來源／postings／lineage／current-next basket／四臂巢狀核對，改由 SQL 核心驗算 K1；ledger 按原 query 順序還原所有 Fold、分母、切片、名冊與原 2,000 draws |
| [保存與恢復](../scripts/retailrocket_session_knn_checkpoint_v2.py) | 來源／環境／設定綁定；SQLite 關閉後完整 SHA seal，後續 main DB 唯讀。每 64 筆或 120 秒後的安全邊界保存 payload／manifest SHA 鏈，latest 僅提示，未提交尾段保留重做，已提交損壞拒收 |
| 數值與順序 | Decimal 字串無損保存；delta 另存 float.hex；Fraction 保存分子／分母。全域依原序逐筆加總，不合併 chunk 小計；訪客首次插入順序、math.fsum 與 bootstrap numeric visitor 排序沿用原規格 |
| 程序與完成 | OS 唯一 writer lock、PID/create_time 與 Windows 原生精確 BootTime；期限與總牆鐘預算含離線時間，不因重入重設。worker 只能寫 candidate，獨立 supervisor 觀察正常退出後才可產生 acceptance |
| candidate 後崩潰 | 先驗舊 candidate 與來源／完整鏈，確認舊 worker 不存活後保留原 bytes 與退出未知紀錄；新 worker 重播後另寫 candidate。已有正常退出證據者交由原 supervisor finalize 重入，不挪用舊退出碼 |

實際 SQL 工作量另記於 workload，沒有將零交集補集的集合證明假稱為 V1 全 session 迴圈。V2 核心不匯入主要 K1、loader 或 evaluator；測試可用主要 adapter 產生人工輸出作待驗對象。

## 合成與故障驗收

驗收包含手算與完整巢狀 V1 暴力差分、499／500／501 鄰居、大批平手、numeric IDs、self／同訪客其他 session、unknown seeds、future／cold／不足十候選、零補位、全部 fallback、四臂原值、current／next basket、各切片分母及每組原 2,000 draws。非允許角色的 item／target 欄位放不可解碼字串，證明角色分流先於解碼。

故障涵蓋 SQL 建置中、query 深層迴圈、payload 半寫、flush 後未提交、manifest 提交後 latest 尚未更新、全域重播、bootstrap draw 中與最終提交前；另檢查同大小竄改、缺段／重複／調換／前鏈 SHA、disk full、期限／預算跨重啟、PID 重用、雙 writer、權限不明、模擬 reboot 及資源超限。已提交損壞不自動修復。

另外真的啟動子程序並以 os._exit(9) 強制退出：一組在第三筆 query 後退出，只採認兩筆已提交進度；一組在 candidate commit 後退出。兩組恢復的完整四臂結果均與不中斷基準相同，且只在新 worker 正常退出後才由獨立 supervisor 完成。這是程序故障測試，沒有實際切斷電源或重開使用者電腦，不能宣稱物理斷電耐久性已證明。

## 成本探測及操作

本輪採前案的 30 分鐘總窗口與 8 GiB 程序樹加 supervisor RSS／20 GiB 執行目錄限制，保留至少 4 GiB 可用記憶體與 8 GiB 可用磁碟。來源核對、獨立 SQL 完整重建、全 validation 窗分層及探測都在外部 supervisor 監控下；停止請求與實際退出收據分開保存。截止前預留短暫合作停止時間，再外部停止程序樹；實際耗時以收據為準。

磁碟統計涵蓋這次 namespace 內的 DB、journal、payload 與暫存；SQLite 預設排序／GROUP BY 的 OS temp 尚未獨立盤點，不能宣稱 20 GiB 已涵蓋所有系統暫存。全量執行前，須將 TEMP 固定到可監控路徑或納入記憶體限額，並量測其成本；這亦列為本輪 no-go 的缺口。可用磁碟檢查則監控執行磁碟的整體剩餘空間。

從整窗四等分時間區段 × posting 工作量 0／1–100／101–1,000／>1,000 分層，逐層固定取最高 posting、投票 membership 上界、history 長度與因果候選數，再以固定 key SHA 補足最多四筆；總計最多 64 筆。上界由全部正重疊、排 self 後的最多 500 個最大 session 商品數加總，不讀 targets 或 K1 分數選樣。全窗分層本身的耗時亦列帳。

```powershell
# 只跑 V2 合成測試，不讀真實 validation 效果
.venv\Scripts\python.exe -B -m unittest tests.test_retailrocket_session_knn_sql_v2 tests.test_retailrocket_session_knn_checkpoint_v2 tests.test_retailrocket_session_knn_cost_probe_v2 tests.test_retailrocket_session_knn_readback_v2 tests.test_run_retailrocket_session_knn_v2 -v

# 會建立新的本機 namespace 並讀真實允許來源；需合成驗收 SHA 完全一致
.venv\Scripts\python.exe -B -m scripts.run_retailrocket_session_knn_v2 --probe
```

`--probe` 不發布研究驗收，也沒有全量／final／test 開關；每次呼叫是另一次有界工程探測，不能為取得較快結果任意重跑選樣。舊 V1 namespace 及不完整 SQLite 不使用。來源再核不一致、到期或資源不足即停止並保存，不放寬限制。

目前的探測只量工程階段及選中 query 的 history／精確排名，未將四臂來源逐筆解碼、指標核對與 checkpoint I/O 算成每 query 已量成本；完整規模的聯合尾端壓力、全域 ledger、2,000 draws、恢復重播也須另有成本證據。必要階段沒有量到就阻擋全量，不能填零、用 V1 前段速率替代或把這次 query 秒數當作總工時保證。

本輪各項實際秒數、探測覆蓋與最終決策見成本報告及 README 最新進度。每日 10% 延遲提醒預算維持，Dashboard 暫緩；所有 K1 結果仍屬已曝光 validation 的開發範圍，未開最終選模、refit 或保留測試。
