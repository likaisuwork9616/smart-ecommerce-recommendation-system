# Stage 12：C1-S1 原48筆公平比較

## 第一階段：真實入口規格封存

本輪沿用已通過167項合成驗收的C1-S1專用完整快照指紋，新增獨立版本的真實比較入口。第一階段規格封存後，入口合成驗收亦已完成；真實比較尚待第三階段，沒有本輪加速比例。

| 封存項目 | 固定內容 |
| --- | --- |
| 查詢與來源 | 原48筆及順序、2115696 bytes完整payload SHA固定；1261個原閉包來源與15個原binding逐項保留 |
| 每次borrow的方法範圍 | 原17個context methods完整保留，再追加V30五個已驗收方法及V31四個入口／封存／驗收／分析方法，共26個；沒有縮小原method身分驗證 |
| 配對順序 | warm_R、warm_C，再六對RC／CR交替；14份全新帳本，一個worker循序執行；C只有一個cold及六個hit |
| 公平對照 | 同窗口重新執行原R；不把V28歷史耗時當成本輪對照，不挑快窗口、不自動retry |
| 採用門檻 | 六對至少五對完整入口較快、配對節省百分比中位數至少5%、RC及CR兩順序的節省秒數中位數皆正、含cold的七次C總和小於R、primary退步中位數不超過5% |
| 監督與負載 | 同V5絕對1800秒及原資源限制；完整入口與publisher沿用200ms目標取樣，保存原始負載及取樣缺口；不測Ollama token或GPU速度 |
| 來源與完整性 | 四次worker／publisher全閉包核對、每run create與鎖定後完整binding核對、15次live完整快照、原14次publisher open全部保留 |
| 獨立發布 | worker正常退出後，另一程序自己重新載入、prepare並計算新scheme指紋；完整科學bytes／Decimal／delta hex／SQL／成本／事件／負載／停止身分核對後才公開 |
| 啟動限制 | 須先提交封存規格，再完成並提交不變入口合成驗收；已有request或結果禁止新測，完成後僅可release重稽核 |

來源檔、舊方法、原C1未採用結論與保留測試鎖定均保留。只追加新版本方法與證據，不合併C2排序或SQL候選。此為已曝光validation上的工程比較；不是完整validation或最終保留測試成績，55／55細層、170筆可比較／232筆歷史查詢不變，T_plan仍空。

## 操作與證據

入口為`scripts/run_retailrocket_session_knn_compare_v31.py`。先使用`--acceptance`完成合成驗收；通過並提交後，`--measure`只允許唯一真實窗口。測後用`--release <本輪namespace>`重新稽核既有結果，不重跑查詢。分析入口`analyze_retailrocket_session_knn_compare_v31.py --analysis`彙整保存成本，已有分析改用`--audit`。

[規格](../reports/stage12/retailrocket_session_knn_v31_compare_specification_20261110.json)與[封存收據](../reports/stage12/retailrocket_session_knn_v31_compare_seal_20261110.json)綁定原1261／15來源、原17個method、V29規格與V30成功驗收收據SHA。原始資料、模型與執行狀態留在Git忽略路徑。

## 第二階段：真實入口合成驗收完成

正式 **178／178 項測試通過**，失敗／錯誤／跳過均為0，收據計時 179.658 秒。包括新入口11項與V30所選167項新舊回歸；父版70個要求仍逐項對應成功的新S1測試。178是執行次數，V29仍刻意重跑原ContextTests 12項。

| 核對項目 | 實際結果 |
| --- | --- |
| 新入口contract | 8項通過：原1261／15、17舊method完整保留並增至26、完整metadata與scheme、原門檻、新namespace、已有request拒絕重試 |
| 新入口受監督人工窗口 | 3項通過：直接執行新entry worker/publisher，14全新帳本、48筆×14＝672次完整payload核對 |
| 新S1及舊版回歸 | 167項通過，包括V30新增68項、V28／V27原套件及V29診斷回歸 |
| 獨立程序與來源 | worker正常退出後publisher另起新程序，完整閉包前後核對與14次open；人工窗口來源49個、binding25個，與真實1261／15分開列示 |
| 快照與會計 | worker15次live指紋、publisher獨立1次、一個cold六個hit；R無candidate cache，兩臂原fine observer深度一致 |
| 故障拒絕 | 原始payload／成本／事件／負載／收據修改、未停止程序、worker或publisher失敗、既有request及scheme混用均受新舊測試核對 |

這是人工資料上的入口驗收，**本階段真實比較次數仍為0，沒有本輪加速比例**。方法、封存規格、測試log與人工證據描述符均已保存於[入口驗收收據](../reports/stage12/retailrocket_session_knn_v31_compare_acceptance_20261110.json)。下一步在提交不變方法與收據後，才以同批原48筆開唯一循序真實窗口。
