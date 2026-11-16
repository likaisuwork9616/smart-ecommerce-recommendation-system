# Stage 12｜V65 真正 typed worker 合成接入與 A16 完整判定

依 [V62 規格](STAGE12_KNN_WALL_CPU_SPEC_V62_20261116.md)，補上 [V64](STAGE12_KNN_WALL_CPU_ENTRY_V64_20261116.md) 明列的兩項缺口：真正 V39／V46 typed worker 的合成入口，以及 A16 的完整資料判定。**本輪先封存工具與案例、更新 README 並推送，再執行驗收；r1 首次正式 suite 的 112 項全過，失敗／錯誤／跳過皆為 0，A1–16 合成驗收通過。**不做實機校準、人工開銷 benchmark 或原固定 48 筆重跑。

## 真正 worker 的接入範圍

本輪重用 V64 的新合成 48 筆、獨立 oracle 與小型 SQLite，再為真正 worker 建立 config／model receipt、catalog／counts 來源描述及 method／environment 契約。model 加入合成 Unicode、escape 與巢狀資料，讓兩種 decoder 實際處理。這些資料不是原固定 48 筆，也不是已訓練的真實 model。

已比較 V39／V46 各自的原基線、O、D，共六個 fresh 合成入口。worker 使用原 V39 `WorkerContext` 與 V47 `CandidateContext`；候選差異只在 V46 decoder，來源驗證、immutable reference 建置、late comparison、snapshot 與 final guard 都保留原程式。呼叫區域的 clone 只注入假時鐘與原本的候選接入，不改全域 namespace，不用 synthetic pool 代替真正 worker。

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

不能用人工 pass 狀態跳過實機能力關卡，也不能把 D 的人工窗口列數當成本輪執行了 28 個真實入口。真實 model decode、原固定 48 筆、training、即時負載採樣均未執行；合成 SQL、typed decode 與檔案操作則確實已執行，不能把本輪所有 decode／query 次數寫成 0。

## A1–16 與封存方式

V63／V64 的 81 個既有具名案例已一起回歸通過；V65 補真正 typed worker 與 A16 案例。封存收據逐一列出 V62 的 16 個必要類別及對應具名案例，拒絕空映射或未列入 suite 的案例。只有全部封存案例成功，才可發布合成 A 關通過；方法封存本身的 `full_v62_A_passed` 固定為 false。

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
| typed 接入與 A16 | 實作與獨立靜態審閱完成；typed 4 與 A16 27 個具名案例全部通過 |
| 方法封存 | r1 已封存 5 份新方法／案例檔、135 份既有來源；112 個具名案例及 A1–16 映射固定；先推送 686d0de 後才執行 |
| 合成驗收 | 112 項全過，沒有失敗／錯誤／跳過；198 個保存檔案正式唯讀 audit 相符，沒有實機開銷結果 |
| 保持的界線 | 實機 B／C／D 未啟動，保留測試 locked；V46 維持暫不採用 |

[方法封存 r1](../reports/stage12/retailrocket_session_knn_v65_wall_cpu_methods_r1_20261116.json)保存 112 個具名案例：既有 V63／V64 回歸 81、typed worker 4、A16 27（B 9／C 4／D 14）。封存時執行數為 0，推送後的首次 suite 已全數通過；其中六個完整 typed 入口及十八個拒絕情境均實際執行。

## 實際驗收結果

| 測試組 | 通過數 | 實際結果 |
| --- | ---: | --- |
| V63／V64 回歸 | 81 | 原邊界、布局、統計、SQL、入口與故障案例保持通過 |
| 真正 typed worker | 4 | 六個完整入口及十八個拒絕情境；原 V39／V46 worker、來源權威與候選 decoder 都實際執行 |
| A16 B 人工判定 | 9 | 三輪原始 stamp、十個 sleep 資料對照、q／bracket／比例精確門檻及缺值／倒退／型別拒絕 |
| A16 C 人工判定 | 4 | 兩組各 4,097 筆 probe 資料、兩工作量各兩暖機與八對、順序／缺值／期限／保存範圍及前關失敗 |
| A16 D 人工判定 | 14 | 28 個入口資料槽、56 組前後校準資料、12 配對、六個全局／八個局部門檻；精確邊界、暖機、缺值、身分及時間範圍均驗證 |
| 合計 | **112** | r1 一次通過，失敗 0、錯誤 0、跳過 0；沒有補跑或更改封存方法 |

六個成功入口的五份原始輸出檔完全相同，全部 48 筆 expected／precise／delta_hex 逐筆等於獨立 oracle，工作量及 SQL／lazy fetch／watch／fault trace 一致。實體帳本每組 **142,166 bytes**，SHA256 皆為 `34437f3a502215c72468264a7735e9746035fdf35295a28dd2b3c1b931df47c6`。各組原 config／model canonical bytes、完整 reference trees 與 statistics 一致；兩 decoder 的 source provenance 仍保留原程式判定，外層 wrapper 的 frame depth 不硬要求相等。

測試內的 call counter 確認每個成功入口只進所選 decoder 兩次，建立兩個原 reference roots，再做兩次 late comparison。原來源／方法／環境檢查與兩次完整 store source check 保留；借用後 model 變更會被真正 final guard 拒絕並清除 authority。checkpoint 半寫故障保持原 exception 物件，失敗 D 留下 incomplete，沒有冒稱完整入口已完成。O 沒有新增 CPU／bracket 探針；D 各記錄 725 邊界、578 span、50 root。假時序下的完整舊 timing 欄位相等，只是接入一致性，不代表實際成本為零。

A16 的 passing fixture 中，B 演算得到 `q=10,000 ns`，C 有每 workload 八對，D 有 12 對及 14 個全局／局部指標組；**全部數字是事先指定的人工資料，並非本機測量值**。邊界及超過門檻一單位、正負不能抵銷、局部 O=0、未完成或缺值不重配、暖機不能省略、未知 agreement 不能視為成功、原 entry 指標不能換成 run.total，均已驗證。每個判定結果保存 `live_measurement_executed=false` 與 `authorized_next_measurement=false`；D 另存 `live_B_C_D_passed=false`。

[正式驗收收據](../reports/stage12/retailrocket_session_knn_v65_wall_cpu_acceptance_r1_20261116.json)保存 112 個通過案例、16 類 A 映射、封存提交與 198 個合成 artifacts 描述。正式 `--audit --revision 1` 已核對來源、提交、私人 log／attempt、唯一執行 reservation 及保存檔案，重跑測試數 0。`full_v62_A_passed=true` 僅表示 A 關合成驗收完成；實際 clock resolution／overhead 仍為 null，B／C／D 實機關卡均未執行，V46 暫不採用。

下一步可另行規劃 B 實機時鐘能力校準，先估時、封存方法與環境，再按當次授權執行；本輪沒有啟動或預約任何校準。若未來能力不支持 1 ms 目標，就停止分項判讀，不能用本輪人工 pass 或 wall−CPU 殘差推論真實等待原因。

獨立唯讀核驗另確認 **341／341 組**工作樹 bytes／SHA256 相符：135 份既有 inputs、5 份新方法、seal／log／attempt 三份紀錄及 198 個合成 artifacts，共 6,697,660 bytes。5 份方法＋seal 的 6 組 Git 原始 blob 與先推送的 `686d0de` 相同；AST／封存／attempt／收據／log 的 112 個具名案例、A1–16 映射順序與唯一 attempt reservation 全部相符。核驗沒有 import 或再執行 suite／fixture。
