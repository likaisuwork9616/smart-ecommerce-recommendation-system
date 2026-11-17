# V77｜保留原 golden 的一次完整合成驗收

2026-11-17 使用者確認依 [V76 計畫](STAGE12_KNN_MISSING_DB_PLAN_V76_20261117.md)準備工具與案例，先封存推送，再執行最多一次完整合成驗收。原 golden 與全部 196 子案例保留；正式窗口最多 15 分鐘，失敗不補跑，不重跑真實資料。每步更新 README、繁體中文 commit 並推 main。使用剩餘額度不延長正式窗口，也不開第二窗。

## 第一步：工具與案例已封存，尚未執行

新增 bundle／pipeline／runner 三個控制模組與三個測試模組，保留原 worker_v75、凍結 CP／V1／V2／V4。人工來源仍指原 V75 fixture／manifest／generator／oracle；新工具只接受固定 V77 工具 seal 與 registry，沒有 revision fallback。新輸出只在實際忽略目錄 `shop-mysql-runtime/v77`，不經 `.runtime` junction。

| 項目 | 實際準備結果 |
| --- | --- |
| 來源封存 | 34 個 Python 來源閉包，加原／新 case catalog，共 36 個方法／案例描述符；動態三測試模組及子程序入口明列 |
| runtime | Windows／CPython 3.12.10／NumPy 2.5.4／psutil 7.2.2／SQLite 3.49.1／little endian，與原封存相符；非時鐘校準 |
| 原來源保留 | 原工具 35 個描述及 Stage8 schema 描述均相符；未修改舊工具、案例、golden 或既有失敗紀錄 |
| 案例契約 | 34 方法一對一映射、196 個 IDs 逐字同序、24 族及三模組歸屬相符；17／106、7／41、10／49 |
| 唯一案例判定修正 | A09.missing_database：精確 FileNotFoundError／ENOENT／filename／WinError 2／凍結 CP 呼叫鏈，第二次恢復未進 verify_full，前後科學證據及固定預算保留 |
| 靜態驗證 | 六個新 Python 來源 AST、來源閉包、案例映射及獨立審閱通過；其餘案例經明列機械替換正規化後 AST 一致 |
| 此步執行狀態 | suite 載入／測試／新 fixture 生成／正式窗口均 0；靜態核對不代表行為驗收通過 |

A09 的證據寫在該人工 case 的 checkpoint 外。只在新版測試 helper 的第二次 writer 區塊內、原 verify_full 呼叫前加計數；不替換 worker。缺 DB 的窄例外判定之外，其餘四種 A09 期待維持原樣。budget 允許正常 atomic replace，但固定時鐘下 consumed=0、last_utc_epoch=1000 與原 run／期限／budget 都須一致；原 session／owner 不可偽裝成本次例外收據。

[工具 seal](../reports/mainline/v77_tool_seal_20261117.json)綁定 V76 修正／下一輪規格及實際方法來源。工具與 README 推送後，才進第二步：逐檔核原三組 manifest／78 檔並建立只重綁方法身分的新 registry；不執行 generator 或重產 expected。

## 正式窗口與期限層次

完整套件的 suite 載體沿用 V75 的 **900 秒整窗監督**；它不是另一個 120 秒科學工作任務。套件啟動的 pipeline／worker／publisher 等工作子程序各至多 **120 秒**，還須受該 run 剩餘預算與整窗剩餘時間限制。這裡明確區分 V76 所稱「子程序」的工作層及正式套件載體，沒有延長任一既有工作子程序上限。

V77 額外把正式 deadline 傳入工作啟動器：啟動前、監督迴圈及接受退出收據前都檢查整窗期限，timeout 取原 watch／run 剩餘／120 秒／整窗剩餘的最小值。真正整窗超時拋 TimeoutError，不能混入預期 FakeClock BudgetExceeded 負例。A23 原有人工期限負例保持原判定。

runner 只接受 `--window 1`，正式目錄固定 `shop-mysql-runtime/v77/formal/window1` 且必須新建；沒有修正版、重試或重新設定開始標記的路徑。全 34 方法／196 子案例須在同一窗通過，無 skip／缺漏／重複 ID／預期失敗冒充通過；必要收據、退出與停態證據齊全且沒有 deadline veto 才能成功。整窗或內層意外超時、來源不符、案例失敗均停止，未執行項完整列出。

900 秒是成功截止，含必要收據保存；逾時後只允許安全清理及保存失敗證據，不能把清理延時算成通過。原 V75 兩窗仍 failed，不併入 V77 通過項，也不開 V75 第三窗。

## 操作順序與本輪進度

1. 封存工具、案例及來源閉包，更新 README／提交／推送。
2. 核原三組人工來源，封存新 registry，更新 README／提交／推送。
3. 以實際 seal SHA 執行唯一正式窗口；命令會在第二步封存後列明。
4. 只讀反核該窗結果、來源、退出及期限否決，保存聚合報告與完整缺漏，更新 README／提交／推送；不補跑。

| 步驟 | 目前狀態 |
| --- | --- |
| 工具與案例 | 已完成並通過靜態複核，待行為驗收 |
| 原人工來源重綁 | 待第二步逐檔核對及封存 |
| 唯一正式窗口 | 尚未開始，0／1 |
| 真實研究／量測 | 真實資料、原 48 筆、Linux、B／C／D 均未啟動 |

工作估 80–140 分鐘、機器執行暫估 2–10 分鐘只是 V76 規劃；準備達 120 分鐘仍未完成工具與來源封存就停止。真實 166,897 筆完整獨立反讀與成本仍缺，T_plan=null、保留測試 locked、V46 暫不採用。每日 10% 提醒與 Dashboard 優先順序沿 V71。
