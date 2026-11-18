# V80 唯一合成驗收結果

唯一窗口在 **128.75 秒**以 `incomplete_timeout` 結束，正式入口與 suite launcher 都退出 `1`。34 個方法中 24 通過、1 失敗、9 未執行。196 個子案例中 147 通過、1 失敗、48 未執行。停在 A12 第二次入口的發布監督，窗口已用完，沒有補跑。[完整結果、缺漏與保存證據](../reports/mainline/v80_synthetic_acceptance_window1_20261118.json)

| 步驟 | 結果 |
| --- | --- |
| 開窗前 | 原工具與人工來源封存 SHA-256 相符，靜態重建一致，`window1` 未使用。預檢收據以 `f0b8a09` 推送後才開窗 |
| 唯一正式窗口 | 以原 3 組人工資料及 golden 執行。A09 缺 DB 精確拒收通過。第一個錯誤是 A12 的 `TimeoutError`，套件依 fail-fast 停止 |
| 收尾 | 查核原 3 份 manifest、78 檔和 38 個工具／案例描述符均相符。71 份原始證據描述已保存，20 個已觀測程序身分事後均查無該程序 |

正式 runner 因子程序傳回期限錯誤將整窗判為 `incomplete_timeout`。整窗 900 秒上限未到、沒有整窗 deadline veto，也沒有來源身分錯誤。128.75 秒是這次合成驗收經過時間。用來判定的檔案及退出碼請見[開窗前核對](../reports/mainline/v80_acceptance_preflight_20261118.json)與[結果收據](../reports/mainline/v80_synthetic_acceptance_window1_20261118.json)。

## A12 的退出、恢復與發布

| 階段 | 已得到的證據 |
| --- | --- |
| 第一次入口 | worker 角色在第 65 次 `query_verified` 留下故障標記，從持有的角色 handle 觀測到退出 `9`。pipeline 角色獨立觀測到 `1`，其失敗收據連回同一 worker 觀測。兩個 launcher 碼各自另存，這一段沒有停止請求或交付否決 |
| 64 筆前綴 | 恢復前收據驗證第 0 個已提交區塊含 ordinal 0–63，共 251,143 bytes，與原 golden 前 64 筆逐位元組一致。第二次入口後區塊 manifest 與 payload 的 SHA-256 相同 |
| 第二次入口 | 恢復 worker 角色觀測到正常退出 `0`。CP 的 3 個已提交區塊為 `64／64／1`，合併 129 筆、506,171 bytes，逐位元組符合原 F-long golden。CP `acceptance.json` 已保存，bootstrap 收據為原 2,000 draws，唯讀反核未重算抽樣 |
| 外部發布 | publisher 已記 H7，H8 與發布證明未產生。publisher 的角色退出碼未知，`15` 屬於 launcher。第二次 pipeline 的角色碼觀測到 `1`，交付被否決，沒有最終封存 |

第二次 pipeline 在等待 publisher 時，呼叫原 Windows 檔案鎖收到 `PermissionError`（errno 13），轉為 `WriterBusy`，最後由累積預算狀態鎖的守門回報 `BudgetExceeded: Cumulative budget state lock unavailable`。publisher 停止請求距 A12 原 request 的 UTC 截止仍有 86.051 秒。現有紀錄能定位鎖取得失敗的呼叫路徑，無法指認鎖持有者或確定競爭成因。停止當下曾保留 writer 仍存活的清理診斷。事後用正式與角色收據的身分聯集核查，20 個已觀測身分都已不存在，未觀測後代的狀態仍未知。

## 結果界線

A12 的預期退出和 64 筆恢復前置條件已驗到，第二次也驗到完整 CP 持久化內容，整個案例仍因發布未交付而失敗。套件列出的 49 個未取得 pass 項目包含這 1 個失敗案例及 48 個未執行案例。A16–A24 的 9 個方法均未執行，詳細 ID 保存在[結果收據](../reports/mainline/v80_synthetic_acceptance_window1_20261118.json)。

原人工來源、golden 和案例清單保留，沒有修工具、重跑或接觸真實資料。下一個可用既有紀錄釐清的問題是預算狀態鎖的取得與持有路徑。K1 完整驗收與 `T_plan` 仍待證據。
