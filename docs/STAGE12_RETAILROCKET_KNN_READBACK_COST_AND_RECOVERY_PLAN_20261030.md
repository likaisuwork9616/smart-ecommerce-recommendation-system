# Stage 12：K1 反讀成本與中斷保存規劃

2026-10-30 的決策是：**暫不另開真實 K1 驗收，也不重啟 V1。先準備獨立的新版本驗收器，驗證精確等價與中斷恢復，再以事前固定的成本探測決定是否值得全量執行。** 本文件是設計方案，尚未實作新版驗收器、執行合成驗收或真實成本探測。

本輪只解析既有進度／資源日誌及小型 metadata，閱讀凍結程式；未讀大型逐筆 query／模型內容，也未啟動訓練、排名、oracle、bootstrap、最終選模或預留測試。K1−C1 仍無正式結論，test locked。實際計算見[成本分析報告](../reports/stage12/retailrocket_session_knn_readback_cost_plan_20261030.json)，停止現況仍以[前輪核對](STAGE12_RETAILROCKET_KNN_READBACK_ONLY_20261029.md)為準。

## 既有紀錄能支持的成本判斷

時間均為臺北時間。用第一個非空 query 計數到最後一筆計數相減，避免將來源 SHA／複製準備期混入平均。這仍是取樣時間差，不是逐 query 計時器。

| 項目 | 實際觀測／計算 | 解讀 |
| --- | ---: | --- |
| 首筆非空計數 | 10/29 15:16:30.164309，4 筆 | 前四筆與先前準備時間不在下列差值內 |
| 末筆計數 | 10/29 17:05:57.877641，923 筆 | 沒有完整驗收收據，923 不能作恢復點 |
| 兩筆觀測之間 | 919 筆／6,567.713332 秒 | 約 109.46 分鐘 |
| 區間平均成本 | 7.146587 秒／筆；503.737 筆／小時 | 依既定順序執行的前段，非全窗隨機樣本 |
| 完整約 15 分鐘區塊平均 | 6.278070–8.846210 秒／筆 | 不重疊區塊，最後不足 15 分鐘的尾段另列報告；不是信賴區間 |
| 已觀測 RSS 峰值 | 760,123,392 bytes，約 0.708 GiB | 現有取樣峰值，不是完整存活期或新版需求保證 |
| 已觀測執行目錄峰值 | 2,918,709,162 bytes，約 2.718 GiB | 不含未實作的新索引、ledger、暫存與恢復成本 |

將區間平均機械地套到原 166,897 個 query：

`166,897 × 6,567.713332 ÷ 919 ÷ 3,600 = 331.317752 小時（約 13.80 日）`

**331 小時是「全量維持這段速率」的情境外推，不是實測全量耗時、上限、信賴區間或剩餘時間。** 換用各完整約 15 分鐘區塊的最低／最高平均，情境為約 291–410 小時；這也不是預測區間。以上均未包含完整準備、全域核對、2,000 draws、收尾與中斷成本。後段 query 的歷史長度、鄰居與候選數可能不同；原始排序亦非時間順序抽樣，不能據此前段推定全窗分布。

若僅以原規格的六小時作規劃比較，query 階段平均速度須約為上述觀測的 55.22 倍，其他階段還需另外留時間。這不表示新版可達到此加速，也不是延長已到期的執行授權。加 checkpoint 只能減少中斷損失，不能消除這個總成本問題。

## 程式中的成本來源與可改進處

原 [V1 契約](contracts/retailrocket_session_knn_validation_entry_v1.json) 明訂每 query 掃全部 train sessions 與全部 causal candidates，源碼也已凍結。下列最佳化必須另立 **V2 驗收方法與新 namespace**；即使成功，也只能驗收原主要輸出，不能把原 V1 整輪改稱成功。

| 現有工作 | 新版候選設計 | 必須保留的語意與證明 |
| --- | --- | --- |
| 每 query 掃 1,180,256 sessions；全量需 196,981,185,632 次 session 迴圈 | 從原始 baskets 獨立 SQL DISTINCT 重建 membership，再 JOIN／GROUP BY 取得所有正重疊 session；用完整集合的補集證明其餘重疊為零 | 不抽樣、不 ANN、不截近期；unknown seeds 仍計入 Jaccard 分母，精確 self-session 排除、完整 pool SHA、500 鄰居與邊界 ties 全保留 |
| 每個 causal candidate 再掃最多 500 鄰居 | 獨立 membership 與選中鄰居關聯，精確加總所有有投票商品；完整 catalog 中未出現者證明為零 | `first_view_ms < query_ms`、完整分母、Fraction 分數、P0／numeric ID tie-break、零分補位與 fallback 全相符 |
| 全候選 Fraction 排序、反覆掃 catalog | 先保留精確有理數與排序規則，建立獨立時間索引；有投票候選與零分補集分別處理 | future item、cold item、不足十候選及完整候選覆蓋均驗證；不把「沒算」當成「零分」 |
| 每 query 重讀整段 session 歷史 | 獨立 SQL history prefix／ordinal 索引，或可重建的前綴查詢 | 每個 chunk 起點須由原來源重建當時歷史，不能靠前一 chunk 的未保存記憶體 |

依據為 [V1 readback](../scripts/retailrocket_session_knn_readback.py) 的 `reconstruct`、`predict`、`verify`。這是靜態工作量分析，沒有逐函式 profiler，不能宣稱某段占了實際耗時的特定比例。

主要計算本來就使用 posting 與稀疏投票。新版不可只複製主要 Python 排名程式：來源 parser、SQL 建關聯與驗算路徑應獨立，不導入 production K1／loader／evaluator。以原 V1 暴力 oracle 作合成差分基準，保留完整巢狀輸出檢查；兩種實作仍有共同邏輯錯誤風險，須靠手算案例與集合覆蓋證明補強。V2 實際訪問量另列，不沿用 V1 的 `all_session_visits` 假稱執行過全掃。

## 中斷保存與恢復方式

新版本只讀既有七份主要輸出與原資料／控制證據；新產物放新目錄。原 V1 的兩個 partial 目錄、923 觀測與未完成的 SQLite 均不作可恢復進度。角色過濾必須先於 item／target 欄位解碼，只處理允許的 warmup／train／validation，預留測試欄位與輸出仍禁用。

| 階段 | 可持久保存的內容 | 恢復與完成條件 |
| --- | --- | --- |
| A：綁定來源與執行身分 | 來源／原主要輸出／P0、C1、D1／契約／程式／環境 SHA、run ID、deadline 與預算 | 每次恢復先核身分與期限；任一來源或方法改變即拒收，另開版本 |
| B：獨立重建 | 新 SQL history、DISTINCT membership、完整 sessions／postings／lineage／fit audit 核對 | 重建完成後關閉 DB、處理 journal、核完整 inventory 與 SHA，再發布只讀階段收據；未完成的 DB 保留但不能視為已驗 |
| C：逐 query chunks | 固定 ordinal／key、已完整核對的 ledger、payload SHA、前一 chunk 收據 SHA | 只承認連續、無重複、無缺漏且已原子提交的 chunks；未提交尾段保留並重新驗算 |
| D：全域統計與名冊 | 由已驗 ledger 按原 query 順序重建的名冊、Fold、分母、groups、diagnostics、cross-tabs | 完整覆蓋 166,897 queries、62,235 visitors 及固定切片，控制組聚合與 EOF 全核對；不合併 chunk 小計替代原序加總 |
| E：原 bootstrap 反讀 | 完整 visitor delta 名冊、固定訪客排序、原 2,000 draws 的核對結果 | 沿原 PCG64(42)、draw SHA、RNG 前後狀態、加權 query 分母與 delta；獨立重播原 draws，不產生另一組主要 bootstrap |
| F：最終收據 | 來源再核、完整 chunk 鏈、全域／bootstrap 收據、資源／退出紀錄與 locked gates | worker 先保存完成候選收據；supervisor 確認正常退出並完成最終檢查後，最後原子提交 V2 acceptance／guard；任一 partial 都不能成功 |

query ledger 要保存獨立驗算後可重建統計的資料：key、visitor／時間、targets／reachable、四臂推薦 IDs、精確 Decimal 指標、原 binary64 delta、slices 與 K1 diagnostics。Fraction 用分子／分母，Decimal 用可無損還原的字串，binary64 保留精確位元身分。不得 pickle iterator、hashlib 或整個 Python 執行狀態。重播使用相同數值環境與 query 順序；`Fold` 的 Decimal 累加、訪客首次出現次序及 `math.fsum` 不能被分塊小計取代。

來源串流位置以已驗 ordinal／key 為權威。最小版本可重新掃描到該位置；若建立可定位索引，必須獨立驗證索引、邊界與 EOF，不直接將 CSV 文字模式 offset 當作可恢復位置。

bootstrap 第一版可在中斷後從完整已驗 query ledger 重驗全部原 draws，前提是實測成本能落入單段預算。若成本不容許，再另行凍結 draw checkpoint：保存完整訪客排序與分組身分、已完成 delta 序列、前一 draw SHA 及 RNG state，按原次序核對後恢復。兩種方案都不能遺漏或重新選擇抽樣。

### 每個 chunk 的提交與中斷處理

1. 建立專屬暫存 payload；只有一筆 query 的全部核對都通過，才能加入 ledger。
2. 候選提交頻率為「64 個完成 query 或 120 秒後的第一個安全 query 邊界」，待合成與成本量測後凍結。單筆 query 與 flush 可以超過目標時間，因此目前沒有兩分鐘損失上限保證。
3. payload flush／fsync、關閉、計 SHA，寫 manifest，最後在同一檔案系統提交具唯一名稱的 commit marker／manifest。`latest` 僅為提示，恢復時重新檢查實際收據鏈。
4. 未提交的暫存尾段保留中斷證據，再從最後完整提交邊界重新驗算。已提交 chunk 若 SHA 不符、鏈不連續、缺段或重複，標為 `integrity_failed` 並拒絕自動恢復，先盤點原因或另立修復規格。已原子提交且資料完整、僅 latest 尚未更新者，須核對完整連續收據鏈後才能納入。
5. Windows rename／fsync 的斷電耐久性須在目標環境實驗，不能只憑 API 名稱宣稱可靠。恢復時仍須驗 SHA、來源身分與連續性。

### 監控、截止與關機

worker／supervisor 分別保存 PID、create_time、boot／session 身分；唯一 writer lock 防止兩程序同寫。無權確認程序是否存活時拒絕恢復，PID 重用不能當作同一 worker。

停止請求、實際退出、最後已提交 chunk、重啟後 recovery audit 分開保存。先將停止請求落盤，再協作停止；硬截止由外部 supervisor 執行，query 內仍有期限／資源檢查。系統關機可能讓兩者都來不及寫退出收據，重啟後只記錄「歷史退出原因未記錄」，不得補成正常期限停止，也不自動啟動研究。

每次恢復沿用原 run 的絕對 deadline 與累積預算，不能重設為另一個完整時數；離線／關機也不延長絕對期限。超過期限後，只能盤點與保存。若未來另給執行窗口，須另記預算授權並保留先前使用帳，不以改計時器繞過限制。

## 另開驗收前的門檻與順序

| 步驟 | 要交付的證據 | 目前狀態／決策 |
| --- | --- | --- |
| 1. 成本與恢復規劃 | 本文件、既有日誌計算報告 | 本輪完成；不開真實驗收 |
| 2. V2 實作與規格凍結 | 獨立 SQL 精確驗算、ledger／收據格式、來源綁定、恢復與截止規則 | 尚未實作；建議下一輪先做這步及合成驗收 |
| 3. 合成等價與故障驗收 | 手算、V1 暴力差分、全流程／所有中斷點恢復一致 | 尚未執行；全部通過才討論真實成本探測 |
| 4. 有界成本探測 | 事前固定樣本與時限、各階段工程耗時／RAM／磁碟／恢復成本 | 尚未授權或執行；不因本規劃自動啟動 |
| 5. 全量 V2 驗收 | 固定範圍與總預算、可完成的保守成本情境、完整來源與 gate 核對 | 暫不啟動；步驟 2–4 通過後再決定 |

合成驗收至少涵蓋：零重疊、unknown seeds、self only、同訪客其他 session、499／500／501 鄰居及大批平手、numeric ID 排序、future item、零分補位、current／next basket、缺列／多列／重複、所有四臂巢狀欄位、跨 chunk 同一 visitor、全域分母與 2,000 draws。以不可解碼的預留測試欄位確認先分流再解碼。

故障注入須覆蓋 SQL 建置、單筆 query 迴圈、payload 半寫、flush 後 manifest 前、提交後 latest 前、全域統計、bootstrap 與最終 guard 前；另外驗證同大小竄改、漏段／調換／重複、錯誤 key／上一收據 SHA、磁碟滿、超限、過期、PID 重用、雙 writer、sleep／restart。中斷後的完整結果必須與不中斷的合成驗收一致；所有未完成階段都不能留下成功 guard。

### 成本探測與預算提案

以下是後續規格候選，**不是執行授權、已通過的成本門檻或工時保證**。

- 真實探測先凍結唯一方案與時限，例如總計最多 30 分鐘，含來源核對、建置、探測及收尾；到時不足即回報資訊不足，不自動延長或改挑較容易的 query。
- 從整個 validation 窗的固定四個時間區段，交叉四種 train posting 工作量層（0、1–100、101–1,000、>1,000）選最多 64 個 query。工作量為完整 history 中各 item 的 train support 加總，包含 self 排除前重疊；選取不讀 target、K1 分數或效果。每個非空層最多四筆，分別取最高 posting 工作量、最高投票工作量上界、最長 history、最多 causal candidates；去重後不足四筆依事前固定 key hash 補足，母體不足四筆則全取。投票上界由完整正重疊、排除 self 後的 session 集合中最多 500 個最大 session 商品數加總，僅作成本代理，不按相似度／成績選樣。事先統計各層母體量，禁止把以 visitor 排序的前 64 筆當作代表樣本。
- posting 層及這些極端案例仍不保證涵蓋最慢的聯合情況。須以有界同規模合成壓力案例補足必要工作維度，將壓力結果納入 `t_h,max`／成本情境；未涵蓋的非零工作維度擋下全量執行。各層最大觀測耗時乘二仍不是工時上界。
- 探測成本包括完整 source hashing、SQL／索引建置、全窗 history／support／投票上界計算與分層選樣（`T_stratify`）、每個 query 與 checkpoint I/O、重入來源再核、全域／bootstrap 及收尾；全窗分層也計入候選 30 分鐘期限。全域／bootstrap 可先用與固定分母相同規模的合成 ledger 作工程成本代理，需明標合成、保留實值差異風險；後續全量仍核全部真實資料與原 2,000 draws。未量到的必要階段不能填零。
- 暫以六小時**含所有階段與恢復的總牆鐘窗口**作候選上限；規劃成本要求至多 4.5 小時，另留 1.5 小時餘裕。`T_plan = 2 × (T_hash + T_build + T_stratify + Σ N_h × t_h,max + T_global + T_bootstrap + T_finalize) + T_resume`，其中 query 成本包含 chunk I/O，`T_resume` 至少涵蓋一次來源再核、ledger 重播與未提交尾段重做。兩倍係數是規劃餘裕，不是統計上界；未覆蓋的非空層或必要階段一律擋下全量驗收。
- RAM／磁碟先沿用 8 GiB／20 GiB、至少 4 GiB 可用記憶體／8 GiB 可用磁碟作候選限制；新版監控涵蓋所有 worker、supervisor 與額外暫存／journal／ledger。測得不足就重新規劃，不移除原證據或自動放寬限制。六小時原規格不代表這次已有六小時新授權。

如果 V2 等價性、恢復或成本任一條件不成立，就保留 K1 未驗收狀態，繼續使用已完成的 P0／C1／D1 研究交付作參照。即使將來 V2 驗收通過，結果仍屬已曝光 validation 的開發證據，不直接完成最終選模／重擬合，也不開預留測試。每日 10% 延遲提醒預算與 Dashboard 暫緩維持原安排。
