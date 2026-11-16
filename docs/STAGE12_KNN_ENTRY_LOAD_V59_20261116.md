# Stage 12｜V59 既有整入口負載與採樣覆蓋對照

本輪只讀 V47／V48 已封存紀錄，對照兩窗各六對的完整入口時間與負載。先固定以下規則並驗收工具，推送後才產出正式比較；不重跑固定 48 筆、不啟動模型或即時採樣。[前輪證據缺口](STAGE12_KNN_EVIDENCE_GAPS_V58_20261116.md)仍成立。

## 固定比較規則

| 項目 | 事先固定口徑 |
| --- | --- |
| 主範圍 | 每窗全部正式六對，共 12 對、24 個入口；R＝V39、C＝V46，原執行順序 CR／RC 交替 |
| 背景範圍 | 4 個暖機入口、2 個 publisher 各自保留，不放進正式六對或每臂摘要 |
| 配對 | 每對保留 R／C 絕對值及 C−R；正差表示候選值較大，並非每種指標都代表負載較差 |
| 彙整 | 每窗每臂六值、六個配對差值，各列有效／缺值數與 min／median／max；不以暖機補足缺值 |
| 跨窗 | 只比較同臂的六次中位數；V48 中位數減 V47 中位數不是同窗配對效果 |
| 指標 | 固定 24 項：入口與採樣窗口時間、樣本數、整機 CPU 平均／最大、worker 與 Ollama CPU 平均／RSS 最大、可用記憶體最小、六項整機磁碟計數、磁碟有效／失效間隔、coverage 間隔數／最大間隙／估算缺格、collector 平均／最大／合計 |
| 缺值 | 保留 unavailable、reset、partial 與有效區間狀態；任一臂缺值時，配對差值亦為 null，不補零 |
| 分析界線 | 不做逐 query 插值、負載校正、相關係數、顯著性或因果判定；不把 wall−process CPU 稱為等待，不從入口扣除 collector elapsed |

CPU 平均沿原摘要的間隔加權；整機 CPU 的分母是所有邏輯核心，程序 CPU 以單核心為基準、可以超過 100%。CPU 差值使用百分點。記憶體與 collector 平均沿原樣本均值。磁碟 bytes/count/time 是整機計數；read_time／write_time 的保存單位為 ms，並非查詢等待時間。磁碟增量也受到窗口長度影響，本輪不另造吞吐率。

`entry_seconds` 精確對回原 `entry.json`，不改用 `run.total` 或 `entry_span` 代替。`telemetry_duration_seconds` 是第一至最後 capture 起點之差，包含入口前後的背景；兩種時間同列但不當作相同邊界。名目 200 ms 是 capture 完成後的等待，最大間隙和估算缺格不是實測等待時間。

## 驗證與進度

| 工作 | 狀態 |
| --- | --- |
| 固定規則 | 完成；全六對、24 項指標、暖機／publisher 分離、缺值及差值單位先固定 |
| 人工工具驗收 | 20 項通過，0.061 秒；涵蓋配對算術、暖機排除、跨窗中位數、缺值與 reset、身分／monotonic 與 UTC 包覆／來源篡改及不呼叫即時採樣 |
| 正式既有紀錄比較 | 待工具封存推送後執行；目前不宣稱負載結果 |
| 新增實驗 | 0 次；輸出與工作量完整驗收沿用前輪，本輪僅重核負載與入口計時來源 |

正式分析將核對每窗 request、14 個入口各 telemetry／entry_span／events／entry，以及 publisher 的前三檔，共 **120 個封存檔**。30 份 raw 以原純計算 `summarize_telemetry` 完整重建對回既有摘要，檢查原窗口、執行順序與採樣包覆，再核對 28 個入口 timer；不調用原 runner。兩窗使用同一份 model 與固定 48 筆的證據沿用 V47／V48，這輪不重讀或運行模型。

[人工驗收收據](../reports/stage12/retailrocket_session_knn_v59_entry_load_acceptance_20261116.json)已綁定工具、測試、V58 盤點與兩份歷史來源報告的 bytes／SHA256。正式分析要求這些內容保持一致。

操作方式（於專案根目錄）：

```powershell
# 工具人工驗收及不可覆寫的驗收收據；封存後不重建
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_entry_load_v59 --acceptance
# 只讀既有資料，產出一次正式報告
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_entry_load_v59 --analysis
# 只讀重建並與正式報告逐欄比較，不覆寫
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_entry_load_v59 --audit
```

原始 telemetry 與程序身分保留在 Git 忽略路徑；公開報告只列聚合負載、覆蓋、來源描述與比較。固定 48 筆為已曝光的 validation 工程樣本，跨入口重複不視為獨立查詢；保留測試持續 locked。暫不採用 V46 為完整入口預設。
