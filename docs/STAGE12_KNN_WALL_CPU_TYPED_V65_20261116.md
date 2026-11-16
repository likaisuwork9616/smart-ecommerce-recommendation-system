# Stage 12｜V65 真正 typed worker 合成接入與 A16 完整判定

依 [V62 規格](STAGE12_KNN_WALL_CPU_SPEC_V62_20261116.md)，補上 [V64](STAGE12_KNN_WALL_CPU_ENTRY_V64_20261116.md) 明列的兩項缺口：真正 V39／V46 typed worker 的合成入口，以及 A16 的完整資料判定。**本輪先封存工具與案例、更新 README 並推送，再執行驗收；r1 已封存 112 個具名案例，執行數為 0，尚無本輪通過數。**不做實機校準、人工開銷 benchmark 或原固定 48 筆重跑。

## 真正 worker 的接入範圍

本輪重用 V64 的新合成 48 筆、獨立 oracle 與小型 SQLite，再為真正 worker 建立 config／model receipt、catalog／counts 來源描述及 method／environment 契約。model 加入合成 Unicode、escape 與巢狀資料，讓兩種 decoder 實際處理。這些資料不是原固定 48 筆，也不是已訓練的真實 model。

計畫比較 V39／V46 各自的原基線、O、D，共六個 fresh 入口。worker 使用原 V39 `WorkerContext` 與 V47 `CandidateContext`；候選差異只在 V46 decoder，來源驗證、immutable reference 建置、late comparison、snapshot 與 final guard 都保留原程式。呼叫區域的 clone 只注入假時鐘與原本的候選接入，不改全域 namespace，不用 synthetic pool 代替真正 worker。

| 驗收項目 | 固定檢查 |
| --- | --- |
| 真正來源權威 | 讀回合成 receipt／來源 bytes，沿用原 contract、來源／方法／環境與 writer identity 檢查，不 stub 成功 |
| 真正 typed 執行 | 原 config／model 兩個 reference roots、兩次 late comparison；確認只呼叫所選 decoder |
| 完整入口 | 保留 V39 policy → V27 runner → V22 `_run`、原 pair／SQL／SetupClock、真正 ReuseStore 的來源核對與 checkpoint 協定 |
| 完整一致性 | 全部 expected／precise／delta_hex、工作量、五份入口檔與實體帳本；不只看 top10 或摘要 hash |
| O／D 與候選隔離 | O 不建立新增診斷 buffer／CPU 探針；D 使用同一 V63／V64 邊界工具，原 namespace 與各自 caller pool 保留 |
| 故障 | 合成來源錯誤、內容竄改與 fault 路徑拒絕，保留原例外及 worker 清理 |

所有語義計數只用於測試，不是低頻時間採樣或效能量測。邊界、原 observer／entry／store 及 typed passive 時間讀取都注入假時鐘；原 process／environment identity 仍做唯讀核對，不能將這類身分讀取稱為本輪時鐘能力校準。完整合成輸出及帳本保存在 Git 忽略目錄，新收據綁定其 bytes／SHA256，audit 可核對保存的檔案但不重跑入口。

## A16 的完整資料判定

新增純資料工具只接收提供的 records，沒有時鐘讀取、sleep、worker、SQL、collector 或 benchmark 執行入口。人工資料中的通過／拒絕狀態，只證明判定程式按 V62 運作，**不證明本機 B／C／D 已經執行或通過**。

| 判定 | 按 V62 固定的規則 |
| --- | --- |
| B 能力資料 | 三輪原始 stamp、每輪 wall／樣本數／期限、CPU 正增量與零比例、宣告 resolution 向上取整、q、全部 bracket 與十個 sleep 對照 |
| C 人工開銷資料 | 空 stamp 與完整記錄路徑各 4,097 筆、兩種 workload、各自兩次暖機與八對 OD／DO、完整 trace／checksum 與期限；不能正負抵銷或補配對 |
| D 完整窗口資料 | 四個固定暖機、六個 block／兩 decoder／各六對，28 個入口與 56 個前後 B 檢查，完整順序、來源身分、缺值及失敗保留 |
| D 全局與局部門檻 | 每 decoder 的 instrumentation entry、原 entry、48 query wall 合計各驗 2%／5%；32／33×正重疊／投票四組各驗絕對 0.1／0.5 ms |
| 統計與狀態 | nearest-rank、偶數中位數、精確分數判門檻、缺失不補零或跨臂重配；結構拒絕、能力未確認／不足與擾動未接受分開保存 |

不能用人工 pass 狀態跳過實機能力關卡，也不能把 D 的人工窗口列數當成本輪執行了 28 個真實入口。真實 model decode、原固定 48 筆、training、即時負載採樣均未執行；合成 SQL、typed decode 與檔案操作則確實屬本輪預定驗收範圍。

## A1–16 與封存方式

V63／V64 的 81 個既有具名案例會一起回歸；V65 補真正 typed worker 與 A16 案例。封存收據逐一列出 V62 的 16 個必要類別及對應具名案例，拒絕空映射或未列入 suite 的案例。只有全部封存案例成功，才可發布合成 A 關通過；方法封存本身的 `full_v62_A_passed` 固定為 false。

| A 類別 | 驗收來源 |
| --- | --- |
| A1–7 | V63 三讀、原始整數、有號差、父子與共享邊界 |
| A8–12 | V63 布局及 V64 實際入口、嚴格身分、incomplete／fault／cleanup 與 O 無新增探針 |
| A13–15 | V64 完整 SQL／帳本與 V65 真正兩臂 typed worker、完整輸出及 namespace 隔離 |
| A16 | V63 精確統計與 V65 B／C／D 完整人工判定案例 |

專用 [V65 封存／驗收入口](../scripts/accept_retailrocket_session_knn_wall_cpu_v65.py) 只提供 freeze／acceptance／audit。先 AST 列舉與來源 hash 封存、提交推送 main，才允許驗收；具名案例必須在執行前與封存相同。每個 revision 只保留一次 attempt，若需修正，另立 revision 並先更新 README、提交推送，不能覆寫舊封存或挑案例補跑。

```powershell
# 封存，不 import 或執行新案例
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_wall_cpu_v65 --freeze --revision 1
# 封存方法與 README 提交推送後，才執行合成驗收
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_wall_cpu_v65 --acceptance --revision 1
# 唯讀核對來源、封存提交、收據、log 與已保存合成 artifacts
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_wall_cpu_v65 --audit --revision 1
```

## 本輪進度

| 小步驟 | 狀態與實際結果 |
| --- | --- |
| typed 接入與 A16 | 實作、AST 與獨立靜態審閱完成；4 個 typed 與 27 個 A16 案例皆未執行 |
| 方法封存 | r1 已封存 5 份新方法／案例檔、135 份既有來源；112 個具名案例及 A1–16 映射固定，先推送 |
| 合成驗收 | 尚未執行，沒有通過數或實機開銷結果 |
| 保持的界線 | 實機 B／C／D 未啟動，保留測試 locked；V46 維持暫不採用 |

[方法封存 r1](../reports/stage12/retailrocket_session_knn_v65_wall_cpu_methods_r1_20261116.json)保存 112 個具名案例：既有 V63／V64 回歸 81、typed worker 4、A16 27（B 9／C 4／D 14）。這只是已固定的案例數，不是測試通過數；其中六個完整 typed 入口及十八個拒絕情境尚未執行。
