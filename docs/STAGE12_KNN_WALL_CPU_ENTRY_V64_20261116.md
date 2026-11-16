# Stage 12｜V64 wall／CPU 合成入口及操作一致性驗收

依 [V62 規格](STAGE12_KNN_WALL_CPU_SPEC_V62_20261116.md)，承接 [V63 最小工具](STAGE12_KNN_WALL_CPU_TOOL_V63_20261116.md)，本輪先封存接入工具與合成案例、更新 README 並推送，再執行驗收。**r1 方法已封存 81 個具名案例，測試執行數為 0，尚無本輪測試結果。**不做實機校準、人工開銷 benchmark 或原固定 48 筆重跑；維持暫不採用 V46。

## 工具與資料

| 項目 | 固定方法與驗收內容 |
| --- | --- |
| 接入工具 | [V64 adapter](../scripts/retailrocket_session_knn_wall_cpu_adapter_v64.py) 以單次呼叫的 clone 接入原 V39 policy → V27 runner → V22 `_run`；保留原 pair、SQL predictor、SetupClock 與 entry code object |
| 時鐘 | O 只有明示的舊 wall reader；D 以 V63 recorder 的 wall-before／thread CPU／wall-after 三讀取代同一舊讀點。原 SetupClock 開關 scope 位置保留，沒有真時鐘預設值 |
| 新合成資料 | 字面定義的四個訓練 session、五個 catalog 商品、48 筆新 query；不是既有原固定 48 筆，也不讀真實 model。K1 預期值由既有獨立 full-session oracle 重算，沒有 fit 或 bootstrap |
| 真正操作 | 小型 SQLite SQL、cursor 逐列取回、checkpoint 檔案寫入與反讀均實際執行；假 budget／process identity 用於測試，沒有服務或 telemetry |
| 完整輸出 | 比較全部 expected／precise／delta_hex、工作量與帳本實際 bytes／SHA256；原基線、新 O、新 D 使用相同假 wall 時序，連舊計時欄位與五份入口輸出檔也列入比對 |
| 操作一致性 | 相同測試追蹤器記錄 SQL／參數、lazy fetch、watch／fault、pool 與 cleanup；診斷 adapter 本身不安裝 SQL proxy 或追蹤器 |
| 失敗案例 | SQL execute／next／watch，以及 query、append、checkpoint、pool 的注入故障；核對原 exception、清理及 incomplete prefix，不補造終點或完整 span |
| 身分及路由 | 嚴格檢查原序位與筆數的整數型別、hash 與 subset 序位；拒絕 bool／float 冒充整數，拒絕缺點、錯序、重用 session 或異常 code object |

固定 fresh48 形狀為 341 個 pair 點＋384 個 ranking 點＝725；預期 578 個 span、50 個 root。這些是應驗證的形狀，封存時不是已通過的數字。完整三讀與運算沿用 V63，不改既有封存方法。所有新資料、SQLite、帳本與測試 log 放在 Git 忽略的私人驗收目錄；公開 repository 只保存產生程式與聚合收據。

三組入口共用假邏輯時序，使舊計時欄位可全等，用來發現漏接或多接讀點；**假 nanoseconds 不代表本機耗時或實際擾動**。V62 不要求實機 O／D 的時間值相等。wall−CPU 保留有號殘差，不解讀為純等待。

## 驗收界線

本輪以 synthetic pool 呼叫實際 V39／V27／V22 入口，保留 request policy 與原 caller pool，驗證診斷接入對科學輸出、SQL 和帳本的影響。**沒有把 synthetic pool 當成 V39／V46 真正的 typed worker**；兩臂實際 source-reference 建置與候選 decoder 的合成接入仍待驗。V62 A16 的 B／D 完整判定收據也未補齊，因此即使本輪通過，仍不得宣稱完整 A 關通過。

本輪會執行合成 query、SQL 與檔案操作，不能寫成「所有 query／SQL 執行次數為 0」。原固定 48 筆實驗、真實 model decode、training、即時負載採樣均為 0。B 實機刻度、C 人工開銷、D 真實入口擾動均未執行，實際刻度與開銷欄位維持 null。原 V27／Observation 的例外清理程式保持不變；本輪測試新 wrapper 的次要診斷錯誤不遮蔽原例外，並不宣稱修復既有 observer 的全部例外風險。

## 封存與驗收流程

[專用入口](../scripts/accept_retailrocket_session_knn_wall_cpu_v64.py) 只有 `freeze`／`acceptance`／`audit` 三種模式。封存用 AST 列出具名案例並遞迴綁定靜態 repository import 來源，不 import 測試或產生合成資料；同時核對 V63 已接受方法及其 V62 來源。

驗收前要求封存與方法已提交至 main，且 HEAD 與已推送的 origin/main 追蹤版本一致；執行前後均重核來源雜湊。每個 revision 只容許一次 attempt，失敗或中斷紀錄保留；如需修正，更新方法與 README、另立 revision 並先推送，不能覆寫原封存或成功收據。驗收涵蓋 V63 原 57 項回歸及 V64 新案例，不另跑舊實驗 suite。

```powershell
# 只封存工具與具名案例；不執行驗收
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_wall_cpu_v64 --freeze --revision 1
# 更新 README、commit 並推送 main 後才執行
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_wall_cpu_v64 --acceptance --revision 1
# 唯讀核對保存的成功收據、來源、attempt 與 log；不重跑
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_wall_cpu_v64 --audit --revision 1
```

unittest 自身報告的執行耗時僅是驗收程序耗時，不作計時工具開銷或效能證據。V64 未提供任何實機 calibration 或 benchmark 命令。

## 本輪進度

| 小步驟 | 狀態與實際結果 |
| --- | --- |
| 工具與案例 | 呼叫專屬接入、完整合成入口、SQL 與邊界 guard 案例已實作；獨立靜態審閱完成 |
| 方法封存 | r1 已綁定 6 份新方法／案例檔、94 份既有規格／方法／靜態 import 來源；同步 README 後先推送 |
| 合成驗收 | 81 項已列入封存（V63 回歸 57／SQL 6／guard 15／入口 3）；執行數 0，沒有通過數或效能結果 |
| 後續界線 | 完成這輪合成驗收後，先處理真正 typed worker 接入與 A16 判定缺口；實機校準另行安排 |

[方法封存 r1](../reports/stage12/retailrocket_session_knn_v64_wall_cpu_methods_r1_20261116.json)的具名清單只代表靜態列舉；入口的 3 個 test methods 內另有 17 種故障 × 3 模式的情境。後續 audit 重核封存來源、公開收據、私人 attempt／測試 log 及封存提交；完整檔案／帳本比較是 suite 內的實際 assertions，audit 本身不重跑這些操作。
