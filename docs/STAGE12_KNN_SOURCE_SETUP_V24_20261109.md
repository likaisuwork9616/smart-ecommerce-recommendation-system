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

本階段尚無工具驗收或真實診斷結果。新增主要訓練、完整 validation、主要 bootstrap、最終保留測試皆為 0；覆蓋維持 55／55 格、170 個可比較查詢、232 個歷史身分。

[封存規格](../reports/stage12/retailrocket_session_knn_v24_sources_specification_20261109.json)
