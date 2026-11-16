# Stage 12｜V61 七階段完整內含區間的負載摘要

本輪先固定彙整方式、人工驗收並推送工具，再查既有 V47／V48 紀錄。沿用 [V60 的七階段與完整內含規則](STAGE12_KNN_PHASE_COVERAGE_V60_20261116.md)，不看負載值重新挑區間，不新增實驗或即時採樣。這些摘要不代表完整階段平均負載，也不能細分序位 32／33 的運算與等待；維持暫不採用 V46。

## 固定範圍與分母

| 項目 | 事先固定規則 |
| --- | --- |
| 主範圍 | 兩窗各六對，24 個正式入口 × 七階段＝168 個階段摘要、84 個階段配對；保留所有原 R／C 與 CR／RC 執行順序 |
| 選取 | 只取 V60 `capture_hull_contained=True` 的原始相鄰 pair；沿用原 sequence，絕不跨接被排除的區間 |
| 跨界 | 名目跨界、僅 capture 跨界仍完整保留於已重建的 V60 報告；V61 保存排除數與所選 pair／endpoint 身分，不將跨界資源分攤進階段 |
| CPU 權重 | 原始秒值 `dt = right.monotonic_seconds − left.monotonic_seconds`；不以整個階段長度、V60 內段長度或內段占比加權 |
| 整機 CPU | 取每個有效 pair 右端已存的 CPU 百分比，按有效 `dt` 加權，另存 min／max |
| worker／Ollama CPU | 同身分完整程序集合的 user＋system 累積差除以該 pair 的 `dt`；按有效 `dt` 彙整，另存有效 CPU 增量合計 |
| 點狀資料 | 對所選 pair 的端點 sequence 取聯集；記憶體、RSS、collector 各端點只計一次，使用普通樣本 min／mean／max，不是時間加權 |
| 整機磁碟 | 六個計數只取原始有效相鄰差量後加總；不依階段時長或內段占比放大，不計新的吞吐率 |
| 背景 | 4 個暖機入口的 28 個階段另列；publisher 沿用既有全窗口背景摘要，不套七階段，也不混入正式六對 |
| 比較 | 每對每階段保存 R／C 絕對值與 C−R，CPU 差為百分點；每臂六值與六個配對差各列有效／缺值數及 min／median／max |

CPU 權重是 capture 起點間的名目時間，並非個別欄位實際讀取時刻的精確間隔；原始 CPU 百分比也有量化限制。程序 CPU 以單一邏輯核心為分母，允許超過 100%，不能與整機 CPU 相減推算外部負載或等待。RSS 與記憶體是端點觀測，不代表未取樣期間的峰值。

保留 **18 項摘要指標**：所選區間數／名目時長、原階段時長、可確認內段占比、三類 CPU 均值、可用記憶體最小值、worker／Ollama RSS 最大值、六種磁碟增量及 collector 平均／最大。前四項是範圍資訊，不是四種負載；完整 CPU min／max、CPU 增量及品質分母另存在各資源摘要。

## 缺值與品質

- 每類區間資源獨立保存有效／失效數、有效／失效名目時長與原因；每類點狀資料保存去重後總數、有效／缺值數與原因。不同資源不能共用有效分母。
- worker 的身分或狀態不完整、user 或 system 任一計數倒退，該 pair 缺值；不能用另一計數的增加抵銷 reset。
- Ollama 必須兩端掃描都完整、程序集合相同且所有程序可用。空集合、部分可用或身分集合改變都記缺值。**這比 V18 對共同可用程序的 partial 估計更保守，不宣稱完全沿用舊口徑。**
- 磁碟兩端須 status 正常、六欄齊全且都不倒退；任一失效或 reset，整個磁碟 pair 缺值。read_time／write_time 單位為 ms，是整機計數，不能稱為查詢等待。
- 沒有選取或沒有有效觀測時，資源摘要及增量合計為 null，不能補 0；合法的 0 CPU／0 磁碟增量則保留。任一臂缺值，配對差值亦為 null。

即使 V60 的幾何覆蓋通過，某資源仍可能沒有足夠有效值。累積 CPU／磁碟量受所選時長影響，兩臂選取範圍也不完全相同；不以這些差量推論完整階段成本，不扣 collector 成為「淨時間」，不作相關係數、顯著性或因果調整。

## 驗收與進度

| 工作 | 狀態 |
| --- | --- |
| 固定方法 | 完整內含、原相鄰 pair、不跨接、CPU 與點值分母分開、保守缺值規則已固定 |
| 人工驗收 | 27 項測試通過，0.065 秒；包含不等權重、非連續選取、端點去重、缺值／reset／身分變更、合法零值、全六對與暖機排除 |
| 正式結果 | 待工具封存推送後讀取；目前尚無本輪實際階段負載結論 |
| 新增實驗 | 0 次；不新增查詢、解碼、訓練或即時資源採樣，保留測試 locked |

正式分析先完整重建 V60，連同其 V59 來源鏈重核 120 個封存檔；再只讀其中 28 份入口 telemetry，逐一使用已核對的 V60 選取。這 28 份是子集合，不另加成 148 份。原始模型、資料與 telemetry 留在 Git 忽略路徑，公開結果保存所選 sequence 與聚合摘要，不公開 PID、程序建立時刻或原始資源逐筆值。

[人工驗收收據](../reports/stage12/retailrocket_session_knn_v61_contained_load_acceptance_20261116.json)綁定工具、測試與 V60 既有來源鏈；正式分析要求原 bytes／SHA256 不變。

操作方式（專案根目錄）：

```powershell
# 人工驗收並建立不可覆寫的收據
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_contained_load_v61 --acceptance
# 封存後，只讀既有紀錄產出一次結果
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_contained_load_v61 --analysis
# 唯讀重建並對照正式報告
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_contained_load_v61 --audit
```

七階段不是完整入口拆帳；setup 後至 final guard 前的粗窗口含查詢、尾端及收尾，不是純 query 或 V49 primary。固定 48 筆已是曝光的 validation 工程樣本，168 個階段摘要與所選區間也不是獨立查詢成績。
