# Stage 12：原 late 完整 typed comparator 實作與驗收

## 第一階段：核心與差分驗收

依 [V38 封存規格](STAGE12_KNN_LATE_TYPED_V38_20261110.md)新增 reference builder 與完整 typed comparator，沒有改舊 canonical、SQL、loader、prepare 或凍結報告。核心驗收已完成；worker 與獨立 publisher 的正式整合驗收留待第二階段，這不是採用或加速結論。

| 實際執行項目 | 結果 |
| --- | --- |
| unittest | 40／40 全通：21 個新 core tests＋19 個原 canonical characterization；無失敗／錯誤／跳過 |
| 真正的差分向量 | 322 個：相等 158、不等 140、原 oracle 拒絕 24 |
| 其他核心向量 | reference grammar／admission 拒絕 30、runtime／深度等邊界 491、資料讀取協定 7 |
| 向量總數 | 850 個、850 個唯一 ID；不將全部都稱為差分或 oracle 拒絕 |
| 真實資料範圍 | 真實 context、SQL query、fit、原 48 筆效能重跑均 0 |

### 實作選擇與原語義

Reference 從 exact typed canonical bytes 解碼，完整驗 tag／arity／十進位 int／finite float.hex／UTF-8／排序唯一 map keys，轉為不可變 tuple token tree。以迭代 parser／grammar／walk 避免新增遞迴 helper 提早撞到 Python 深度限制；共享無環子樹每次都走訪，cycle 用 active ancestry 拒絕。Reference 不可 pickle，不可透過 setattr 改內容；弱 admission registry 不保存 reference 或 bytes 強快取，factory lease 綁所有原不可變 slots，防止 stale id 重用授權不同內容。

Live 比較保留 None／bool／int／float／str exact type、list／tuple 差別、序列順序及重複、dict／proxy 同 map 語義、完整巢狀資料與 Unicode。一般不等仍檢查所有 live extras；hard invalid 立即拒絕。不存在 Python container equality、id／長度／摘要相同就略過子樹的捷徑。

Map 仍按原 all-key scan→sorted keys→原 raw key lookup。動態第二輪出現 str subclass 時，用 `str.__str__`取得實際 Unicode payload，避免自訂 encode／equality 偽裝；lookup 仍用原 key，沒有多加 len／items 呼叫。兩個 LieStr 正反例實際對回原 oracle bytes 及讀取 trace。

### 執行域與較強拒絕規則

本候選以 V36 固定來源為基準，初始化中持續變更不會被吸收成新 late baseline。比較成立的主張限於原 typed domain、已批准的 runtime／callsite 與穩定物件圖；不宣稱任意動態 proxy 或連續 heap 隔離的全域等價。

- Public `build_reference`會重建資料並額外呼叫一次未修改的原 canonical 核 exact bytes。該額外序列化屬獨立 publisher／standalone builder 成本，不能混進 worker 39 次或隱藏。
- Worker 私有 builder 是**受封存方法約束的 adapter 信任邊界**：只使用同次四個 early 比對成功的 source bytes 與成功 callsite／runtime 記錄；不是任何 bytes 都能換來的不可偽造通用憑證，不重做兩次序列化。
- Recursion limit、int digit limit 與批准 callsite budget 在比較前、比較完成後都被動核對；變動即借出前拒絕。這些 eligibility 向量與純內容差分分開記錄。
- 動態 proxy 首輪 exact str、第二輪改成 int／None／bool key，原 oracle 可能產出合法但與固定來源不同的 JSON；新比較器採較強 fail-closed 拒絕。三個實測例子列為 admission 邊界，沒有偽稱原 oracle 拒絕或任意代理全域等價。
- 內層 comparator 重入即使被 callback 捕捉例外，sticky reentered 狀態仍讓外層拒絕；退出後狀態清除，不污染下一個獨立比較。

這些範圍是 V38 動態協定與 resource admission gate 的具體處理；沒有放寬來源內容或推遲原 late 保護。若變動在所有既有離散 guard 前還原，仍不宣稱能連續偵測。

[核心差分驗收收據](../reports/stage12/retailrocket_session_knn_v39_typed_core_acceptance_20261110.json)保存實際向量、唯一 ID、方法 SHA 與 ignored log。失敗草稿日誌保留在 ignored verification，沒有覆寫成通過結果。

```powershell
.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_typed_core_v39 --audit
```

目前只完成核心收據；第二階段會以新 worker 真正跑人工 14 帳本／672 次核對，再由退出後的新 interpreter 獨立重建來源權威與完整科學結果。原身分、鎖後、final、snapshot、獨立發布與停態日誌均須保留。
