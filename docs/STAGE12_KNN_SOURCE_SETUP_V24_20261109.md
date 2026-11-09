# Stage 12：原 48 筆來源驗證與初始化分項診斷

## 封存規格

本輪承接 V23 第一優先工作，封存原 48 筆的觀測規格，完成核心觀測工具與合成驗收。**本輪不啟動真實診斷窗口**；後續將工具整合進受監督實測與獨立發布入口後，需再驗收整體入口才執行。

已核對 17 份小型來源與封存方法，共 786,751 bytes。原 48 筆、順序、模型、抽取子集及完整參考帳本沿用；580 份原始 closure descriptor 封存在規格中，本輪沒有重新讀取大型來源／模型。規格 SHA-256 固定於工具入口，不能事後換資料或降低驗收條件。

| 項目 | 已固定的規格 |
| --- | --- |
| 未來 R／D 診斷 | 原 R、觀測 D 各暖機一次，再六對 RD／DR，共 14 次 fresh run、672 次核對；本輪不執行 |
| 排名與保存 | 原 V4 verifier、SQL 與 V6／V2 bytecode，只有每次呼叫專屬的觀測綁定；原方法檔封存 |
| 來源核對 | closure verify／describe、checkpoint check_sources／verify_sources／descriptor 各自記錄；原呼叫不增加、不省略、不快取 |
| 建立與鎖定 | create、open、writer 取得及整個 writer 生命週期分開；保留鎖取得後 force 重驗 |
| 初始化 | 原 load_context、prepare_catalog 及 verifier setup 原計時邊界；其餘成本明列剩餘項 |
| 執行與發布 | 原 run 的 verifier／proof／輸出；獨立 publisher 從呼叫到返回或例外，receipt 保存另計 |
| 時鐘與分項 | perf_counter_ns wall 時鐘，parent／child 樹、完成與錯誤類型；巢狀區段不相加重複計數 |
| 失敗 | 同長度變更、建立後至上鎖間變更、鎖／恢復／期限、immutable acceptance、發布來源／帳本不符仍在原邊界拒絕 |
| 公開範圍 | 原始路徑及完整事件保留忽略路徑；公開只列 phase、次數、邏輯 bytes 與耗時 |

來源 bytes 分開列每次實際完成的 descriptor 覆蓋與唯一 descriptor 覆蓋；失敗呼叫記 attempted／failed，不把無法知道的讀取量補成零。邏輯 bytes 不當成實體 I/O，wall 不當成 CPU 等待。

觀測器會增加 Python 分派、記錄與時鐘成本。未來 R／D 差只描述觀測擾動，不套 SQL 候選的 5% 採用門檻，也不能當演算法改善。保留原 primary／append／budget／尾端 commit 的 V23 定義。

未來實測全程循序、單一原 1,800 秒 deadline 涵蓋 worker 與獨立發布；負載採用 200ms 目標間隔，首尾包覆與相鄰不重疊核對。Ollama 僅觀測名稱匹配的程序，不呼叫推論。這些實際入口整合與實測屬後續工作。

封存規格時尚無工具驗收結果，合成驗收見下節；本輪未做真實診斷。新增主要訓練、完整 validation、主要 bootstrap、最終保留測試皆為 0；覆蓋維持 55／55 格、170 個可比較查詢、232 個歷史身分。

[封存規格](../reports/stage12/retailrocket_session_knn_v24_sources_specification_20261109.json)

## 觀測核心與合成驗收完成

**22／22 項測試通過**，耗時 **6.830 秒**，失敗／錯誤／跳過皆為 0。包含新 V24 專項 11 項、原 V6 保存成本 7 項及 V23 巢狀成本 4 項。

| 驗收範圍 | 實際結果 |
| --- | --- |
| 原來源呼叫 | 重複 verify／descriptor 與 watch trace 相符，沒有附加來源讀取；邏輯重複 bytes 與唯一 descriptor 分列 |
| 來源內容變更 | 相同大小不同內容、建立後至上鎖前變更均由原檢查拒絕；原例外及 guard 釋放一致 |
| 快取／force／外部 callback | 原 _sources_checked、force=True 與外部 verifier 委派行為一致，沒有新增全域快取 |
| 保存協定 | 固定人工 UUID／clock 的 run、budget、payload、manifest 與 stage 位元組等同原 V6 |
| 鎖定／恢復／期限 | 人工鎖失敗、writer body 中斷、帳本損壞恢復、過期預算及 acceptance 不可變檢查維持拒絕 |
| 原完整 verifier | 人工多臂 fixture 的完整四臂 payload 與工作量相同；context／catalog 及原 setup 邊界各自觀測 |
| 人工 48 筆 run | 原 V22 run bytecode 經每次呼叫綁定，R／D 人工帳本逐列位元組一致 |
| 獨立 publisher | callback 全生命週期含原發布寫入；來源不存在及帳本損壞會保留 failed 事件並拋出原例外 |
| 計時樹與範圍 | 子段越界、交叉／重疊、缺少終點、錯誤 parent／完成旗標均拒絕；規格不能改成真實執行授權或不同樣本數 |

人工 48 筆 fixture 用於驗收 checkpoint／run／publisher 控制流程；另以完整四臂人工 fixture 驗收原排名結果。這兩種測試範圍分開記錄，沒有把人工資料的秒數、次數或吞吐量當成原 48 筆的真實效能。

### 工具操作與事件範圍

執行 `.venv/Scripts/python.exe -B -m scripts.accept_retailrocket_session_knn_sources_v24 --acceptance` 可做一次性正式驗收；已有收據會拒絕覆寫，入口沒有真實 measure 指令。快速重驗人工測試可用 `.venv/Scripts/python.exe -B -m unittest tests.test_retailrocket_session_knn_sources_v24`。

核心 API 位於 `scripts/retailrocket_session_knn_sources_v24.py`：

- `Observation` 保留 private parent／child wall 事件，`summary()` 驗證時間包含與互斥成本守恆，只產生公開彙總。
- `verify_bindings`／`verify_sources` 執行原函式 bytecode，descriptor 只包住原呼叫一次；不存在或中途例外的 bytes 記未知。若 descriptor 完成但期望 SHA 比對失敗，保留已完成雜湊覆蓋，外層 verify 記失敗。
- `ObservedStore`／`StoreFactory` 觀測 create、open、writer 取得與整段生命週期，並在原 _check_sources 路徑記錄來源核對。
- `make_verifier` 只綁定原 context／catalog 準備與既有 perf_counter 邊界；原 SQL 與排名不加取列代理。setup envelope 含觀測器開銷，原 setup 秒數另外保留。
- `run_fixed48` 以原 V22 run bytecode 綁定原 V4 排名或 D 觀測，proof／輸出原操作各自計時；R／D 標籤由未來整體入口提供。
- `Observation.publisher(callback)` 包住完整 callback，包括 callback 內的發布寫檔；closure、open、proof 等內部操作須明確使用觀測綁定。事件收據在 callback 結束後保存，列在 publisher wall 之外，避免自我包含。

所有綁定均屬每次呼叫專用，正式程式未 monkeypatch 全域 module／class。對原方法檔與封存來源的 SHA 在驗收前後核對一致。本輪新方法固定 LF、兩份新收據保留原 bytes，避免 Windows checkout 改變本輪指紋。 提交前另核對 Git 暫存區的三份方法與規格 SHA 均等同驗收收據；規格 JSON 欄位不變，只在 Git 中保留原已封存的 CRLF bytes。

### 本輪完成與後續缺口

本輪要求的規格與核心觀測工具合成驗收已完成。**實際受監督 worker／publisher 入口尚未整合驗收**，包含單一絕對 deadline／資源限制、原 48 筆 R／D 排程、連續負載、實體結果對照與公開收據的整體協定；這些列入收據 pending_scope。不能把核心合成通過說成整個真實入口已驗收或已量出新成本。

下一步先完成並驗收上述整體入口，再依本規格循序實測原 48 筆。這輪真實排名、真實效能窗口、主要訓練、完整 validation、主要 bootstrap、保留測試均為 **0**；覆蓋仍 55／55 格、170 個可比較查詢、232 個歷史身分。兩個 SQL 候選維持結案，`T_plan` 未設定。

[觀測核心合成驗收收據](../reports/stage12/retailrocket_session_knn_v24_sources_acceptance_20261109.json)
