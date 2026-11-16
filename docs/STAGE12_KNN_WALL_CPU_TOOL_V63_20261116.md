# Stage 12｜V63 最小 wall／CPU 邊界工具與假時鐘驗收

依 [V62 規格](STAGE12_KNN_WALL_CPU_SPEC_V62_20261116.md)先完成最小工具及人工案例，封存、推送後才執行驗收；**57 項測試全部通過，失敗／錯誤／跳過均為 0**。本輪不接入真實入口、不做實機時鐘校準、人工工作量 benchmark 或原 48 筆重跑。既有 V62 規格與舊方法不修改；實際刻度、開銷與等待歸因仍未知，維持暫不採用 V46。

## 工具做什麼

| 元件 | 範圍 |
| --- | --- |
| [邊界核心](../scripts/retailrocket_session_knn_wall_cpu_v63.py) | 明確注入 wall／CPU／thread readers，沒有真時鐘預設值；不可變原始整數、讀值順序、同執行緒與單調性、完整／失敗 call 記錄、有號公式及父子分析 |
| [固定形狀](../scripts/retailrocket_session_knn_wall_cpu_layout_v63.py) | 只驗人工 marker 與明示的 48 筆 cohort；725 個呼叫點、578 個 span、setup／tail 與 query 層級，不執行 query |
| [資料統計](../scripts/retailrocket_session_knn_wall_cpu_summary_v63.py) | 只接受提供的數字；nearest-rank、精確中位數、固定八對 O／D、暖機另列、缺值保留、絕對擾動門檻；不採樣也不執行 workload |
| [封存／驗收入口](../scripts/accept_retailrocket_session_knn_wall_cpu_v63.py) | 僅有 freeze、acceptance、audit；綁定方法與 V62 來源，保存不可覆寫的收據、私人測試 log 與失敗 attempt |

`BoundaryRecorder` 的三種 reader 都必須由呼叫端提供。每個 stamp 依 thread → wall-before → CPU → wall-after → thread 讀取，三個時鐘值讀完後才驗證及寫入 buffer；`tap` 只將 wall-before 轉成原欄位使用的 float 秒，診斷計算仍從原始 int 得到，不以 float 反推。

`span_values` 保存 V62 的九項整數值，包括主 wall、CPU、有號差、兩端 bracket、inner／outer 與其 residual。CPU 大於 wall 時保留負差，CPU 零增量也原樣保存。bracket 只呈現讀值時序，不是 CPU 精度或真實等待的誤差界。

`analyze_spans` 以同一 registry 的 ID／sequence 檢查父子界內、同層不重疊及共享端點；只扣直接子段，剩餘欄位叫 `unassigned`。`analyze_fresh48` 另外要求 marker ID 與 clock registry 順序完全相同，包含沒有單獨成段的 setup 中間點。七個 ranking 子段加總回 `rank_marks` 首尾；外層 rank 保留 wrapper 差額，不把兩層一起相加。

人工完整形狀為 341 個 pair 點＋384 個 ranking 點＝725；其 578 個 span 中有 50 個 root（48 個 query＋setup／tail）。root 之間仍有未涵蓋的間隙，root 合計不是整個首尾經過時間，更不叫等待。`original_ordinal` 須唯一，但依明示 cohort 的順序核對，不額外要求數值遞增。

start capture 失敗時 body 不執行；body 成功但 end capture 失敗時不發布完成；body 自己失敗時仍嘗試保存終點，若 timer 再失敗，保留原 exception 與 cleanup，另記 secondary error。失敗 recording 不允許繼續補齊成功。未完成 marker 只接受合法 prefix，保留已有資料、回傳 `incomplete` 與空 span，不造出缺少的時間。

O 模式直接呼叫原 body，不建立診斷 recorder、不讀逐邊界探針。這只驗證最小 wrapper，尚未證明真實入口 O／D 的所有操作一致。

## V62 A 項目的驗收界線

| V62 類別 | 本輪涵蓋 | 仍待後續 |
| --- | --- | --- |
| A1–7：讀值、整數、有號差、身分與父子 | 最小核心的假時鐘案例 | 真實環境的刻度與成本不屬本關 |
| A8–10：48 筆與不完整形狀 | 人工 725 點／578 span、原序位、prefix／skip／resume 拒絕及 setup／tail 隔離 | 真實 V27／V39 接入、SetupClock lifecycle、實際呼叫點映射 |
| A11–12：例外與 O 模式 | 最小 body／cleanup／timer 例外優先，O 不建立診斷事件 | 原 runner 的 fault、pool 清理與完整入口生命週期 |
| A13–15：科學輸出、SQL、clone | 本輪不執行模型或原 SQL，也不改舊方法 | 完整 payload／帳本、lazy fetch／watch／fault 與 V39／V46 呼叫專屬接入一致性 |
| A16：統計 fixture | 人工八對／暖機、缺值、不抵銷、2%／5% 精確門檻 | B／D 完整判定與接入收據；目前沒有開銷實測結果 |

本輪結果只稱「最小工具與假時鐘驗收通過」，**不能稱完整 A 關通過，也不能因此直接進入 B／C／D**。下一步應先以合成資料完成接入及輸出／操作一致性驗收；實機校準仍須另行安排。

## 實際假時鐘結果

| 測試組 | 通過數 | 驗證內容 |
| --- | ---: | --- |
| 邊界／例外／父子 | 26 | 三讀順序、原始大整數、零增量與負 residual、跨執行緒／倒退／重複拒絕、原 body 例外優先、O 無探針及父子不重加 |
| 人工布局 | 13 | 725 點、578 span、原 cohort 順序、共用端點、合法 incomplete prefix、不補 skip／resume 或缺漏 |
| 人工統計 | 14 | nearest-rank、精確中位數／2%／5% 邊界、全部八對及暖機、缺值留原配對、正負不能抵銷後通過 |
| 核心與布局組合 | 4 | 人工 725 個原始 stamp 對上全部 span；未引用 setup 點的錯序、缺少／多出 clock 也拒絕 |
| 合計 | **57** | 失敗 0、錯誤 0、跳過 0；只有一次正式 suite 執行 |

人工整合 fixture 的每個 rank_marks 為 wall 700／CPU 910 ns，有號差 −210 ns；外層 rank 未分項為 200／260／−60 ns。這些是事先指定的假資料，用來證明不夾零與父子守恆，**不是機器的實際效能或等待時間**。50 個 root 的假 wall 合計 67,500 ns，原首尾 72,400 ns 間另有 4,900 ns 不在 root 內，工具沒有將其冒稱已涵蓋或等待。

[正式驗收收據](../reports/stage12/retailrocket_session_knn_v63_wall_cpu_acceptance_20261116.json)綁定先推送的封存方法、57 個具名案例、私人 log／attempt。正式 `--audit` 重核來源與成功收據通過，沒有再執行 suite；另以獨立唯讀方式核對 8 個方法、14 個輸入與 seal／log／attempt 共 25 組 bytes／SHA256，全部相符，AST／封存清單／收據／log 的 57 個成功案例完全一致。`full_v62_A_passed=false`、實際刻度／開銷為 null、B／C／D 均未執行。

## 封存與進度

| 小步驟 | 狀態與實際結果 |
| --- | --- |
| 最小工具與案例 | 已實作；57 個具名測試與封存清單相符並全部通過 |
| 方法封存 | 綁定 8 份方法／測試檔、V62 規格及其 13 份文件／來源；先推送後才執行 fake suite |
| 假時鐘驗收 | 57 項通過、正式唯讀 audit 相符；只有人工資料，沒有本輪時鐘刻度／開銷數字 |
| 真實操作 | 新增實驗、query、decode、training、即時採樣全部 0；保留測試 locked |

[方法封存收據](../reports/stage12/retailrocket_session_knn_v63_wall_cpu_methods_20261116.json)中的 `declared_tests` 來自 AST 靜態列舉，不是執行結果。驗收入口要求實際載入測試身分與封存清單完全一致；測試前後重核 bytes／SHA256，失敗紀錄留在 Git 忽略的私人路徑，不挑案例或覆寫成功收據。

測試只用注入的整數序列與人工標籤／數字。unittest 自身可能計錄測試執行耗時，這不是讀錶開銷、CPU 校準或工作量 benchmark，公開結果不以其耗時推論效能。

操作方式（專案根目錄；只有下列三種模式，沒有 measure／benchmark）：

```powershell
# 先封存，不執行測試；檔案已存在時拒絕覆寫
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_wall_cpu_v63 --freeze
# 方法及 README 提交推送後，執行注入時鐘與人工 fixture 驗收
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_wall_cpu_v63 --acceptance
# 唯讀核對成功收據、來源與私人 log，不重跑測試
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_wall_cpu_v63 --audit
```
