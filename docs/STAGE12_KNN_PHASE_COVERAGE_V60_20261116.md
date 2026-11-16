# Stage 12｜V60 粗階段與採樣區間的重疊覆蓋

本輪先固定下列階段、重疊與覆蓋規則，人工驗收後推送，再查 V47／V48 既有紀錄。只判斷粗階段是否有可完整內含的採樣區間；不分配階段 CPU／I/O，也不啟動新實驗或即時採樣。[V59 全入口負載結果](STAGE12_KNN_ENTRY_LOAD_V59_20261116.md)與「原因未知、暫不採用 V46 預設」維持原狀。

## 固定七個粗區間

| 名稱 | 保存邊界與意義 |
| --- | --- |
| reference 建置 | `cache.use` metadata 內 passive build 的原始 start／end |
| 原 context 載入 | `cache.original_load_context` |
| catalog 準備 | `cache.original_prepare_catalog` |
| 冷建置快照 | `cache.cold_build` 下的 `snapshot.fingerprint` |
| 使用前快照 | `cache.pre_use_digest` 下的 `snapshot.fingerprint` |
| setup 後至 final guard 前 | `verifier.setup_envelope.end → cache.final_guard.start`，含 48 筆查詢、append／commit、尾端／seal、關閉與呼叫間工作 |
| 最後快照 | `cache.final_guard` 下的 `snapshot.fingerprint` |

七項依執行時間排序、互不重疊，但不是完整入口拆帳。第六項是由已存事件邊界界定的粗窗口，**不等於 V49 primary，也不是純查詢時間**。V49 的 source verification、零散餘額、逐 query 與 ranking 分項不在本輪範圍，不把只有時長的項目還原成虛構起訖。

原六項時長會對回 V49 的純計算拆帳；派生窗口只核對來源邊界。每窗全部正式六對、兩臂都保留，主分析共 **24 入口 × 7 階段＝168 個階段窗口**；4 個暖機入口的 28 個階段另列，publisher 只保留 V59 背景摘要，不套冷入口七階段。

## 重疊與跨界規則

設階段為 `[a,b)`，第 i 筆 capture 起點為 `tᵢ`，採集耗時為 `cᵢ`。事件保留原整數 ns；telemetry 的秒值各自乘 10⁹ 後 round 成整數 ns 以便比較。這只是單位換算，**不代表原觀測具有納秒精度**；以下幾何關係都相對於保存值及其換算精度。

| 項目 | 事先固定定義 |
| --- | --- |
| 名目採樣區間 | 相鄰 capture 起點 `[tᵢ,tᵢ₊₁)`；只分析同一入口，不跨入口接續 |
| 正重疊 | `max(0, min(b,tᵢ₊₁) − max(a,tᵢ)) > 0`；只碰到端點不算重疊 |
| 名目完整內含 | `a ≤ tᵢ` 且 `tᵢ₊₁ ≤ b`；其餘正重疊區間全部保留為跨界 |
| 兩次採集的可能讀值範圍 | 從左 capture 開始，到右 capture 結束：`[tᵢ,tᵢ₊₁+cᵢ₊₁)`；避免假裝所有欄位都在 capture 起點瞬間讀取 |
| 保守內含 | 上述整個範圍都在階段內；邊界相等允許。名目內含但右 capture 跨界者另標示 |
| 僅 capture 跨到階段 | 名目區間未正重疊、右 capture 尾端卻跨入階段，另列並保留；不增加名目覆蓋或內含數 |
| 兩次採集之間可確認內段 | `max(0, tᵢ₊₁ − (tᵢ+cᵢ))`。只將保守內含區間的這段長度列入粗篩分子，排除左 capture 本身的耗時 |
| 零長度 | 階段仍保留，比例為 null、粗篩不通過；不除以零或補成 0% |

名目區間互相銜接，所以被入口採樣包住的階段通常會自然得到 100% 名目幾何包覆。**100% 包覆不等於足夠的時間解析度。** 名目內含占時、保守內含的名目占時與可確認內段占比全部分開保存；後者仍不是 CPU、等待時間或精確 counter-read 間隔。

所有正重疊與僅 capture 跨界區間均保留原 sample sequence、相對入口起點、交集長度與分類，不只保存通過者。同一跨界區間可出現在相鄰階段，不能把這些重複出現當成獨立觀測或加總成負載。公開結果不帶各樣本資源值，**不依重疊比例分攤 CPU 或磁碟計數**。

## 事先固定的覆蓋粗篩

一個正長度階段必須同時符合：

1. 至少 **2 個保守內含區間**。
2. 這些區間的「兩次採集之間可確認內段」合計，至少占階段長度 **50%**。

第二條以整數 `2 × 內段合計 ≥ 階段長度` 判斷，不用顯示後四捨五入的百分比。這是本輪事先固定的工程描述門檻，不是統計顯著性、估計準確度或因果門檻；不會看完結果後改門檻。每臂、每階段列全六次通過數與範圍，每對另列「兩臂皆通過」，暖機不補入分母。未通過者仍完整保留，不作性能樣本刪除。

通過表示可以進一步考慮該粗階段內的既有區間描述，不能外推到未覆蓋的階段邊緣或逐查詢；不通過則不應把跨界樣本切成階段負載。如果研究問題需要這些短階段或序位 32／33 的 CPU／等待區分，必須另評估同邊界診斷及開銷，本輪不直接啟動。

## 驗收與進度

| 工作 | 狀態 |
| --- | --- |
| 階段與重疊規則 | 已固定七階段、半開邊界、capture 範圍、內段分子、2 個／50% 粗篩與跨界保留 |
| 人工驗收 | 26 項測試通過，0.058 秒；涵蓋端點、capture 跨界、50% 精確門檻、零長度、守恆、時鐘平移、原樹驗證及全六對／暖機分離 |
| 正式覆蓋 | 待工具封存推送後分析，尚無本輪實際覆蓋結論 |
| 新增實驗 | 0 次；只讀既有記錄，不新增查詢、解碼、訓練或即時資源採樣 |

正式分析先完整重建 V59 並對回原報告，重核 120 個原始封存檔；再對其中 28 入口的 56 份 events／telemetry 分析七階段。沿用原 manifest bytes／SHA256、身分、順序、UTC／monotonic 包覆與 30 份負載摘要驗證，不執行原 runner。

[人工驗收收據](../reports/stage12/retailrocket_session_knn_v60_phase_coverage_acceptance_20261116.json)綁定工具、測試、原事件拆帳與 V59 來源鏈；正式分析要求它們保持原 bytes／SHA256。

操作方式（專案根目錄）：

```powershell
# 人工驗收並建立不可覆寫的收據
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_phase_coverage_v60 --acceptance
# 工具封存後，只讀既有紀錄產出一次報告
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_phase_coverage_v60 --analysis
# 只讀重建並與正式報告比對，不覆寫
.venv/Scripts/python.exe -B -m scripts.analyze_retailrocket_session_knn_phase_coverage_v60 --audit
```

固定 48 筆為已曝光的 validation 工程樣本；168 個階段窗口是重複入口中的七種區間，不是獨立查詢樣本。保留測試持續 locked，原始模型、資料與 telemetry 留在 Git 忽略路徑。
