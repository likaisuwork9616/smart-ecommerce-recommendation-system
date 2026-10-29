# Stage 8：Retailrocket 來源盤點與推薦資料契約 v1

2026-10-28 已實際下載發布者 Kaggle 第 2 版完整官方包，掃描四份 CSV，完成獨立核對並固定[推薦資料契約 v1](contracts/retailrocket_recommendation_v1.json)。目前可支持的是非商業、回溯的下一次瀏覽推薦研究。推薦樣本建置器、熱門／共現／個人化模型與推薦成績均尚未產生。

閱讀順序：[來源實測](../reports/stage8/retailrocket_source_audit_v1.json) → [本輪核對與凍結收據](../reports/stage8/retailrocket_contract_v1_acceptance.json) → [機器契約](contracts/retailrocket_recommendation_v1.json)。所有原始資料、暫存、SQLite、guard 及執行紀錄都在 `shop` 內的 Git 忽略目錄。

## 來源、版本與授權

| 查核項目 | 本輪實際證據 |
| --- | --- |
| 原發頁 | [Retailrocket recommender system dataset](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)，發布帳號 `retailrocket`，作者／帳號名稱 Roman Zykov |
| 官方 API | `datasets/view`、`datasets/list` 與帶 `datasetVersionNumber=2` 的下載端點均 HTTP 200；本輪未使用帳密或第三方鏡像 |
| 固定版本 | dataset id 1031、version 2；API 與 ZIP 四份檔名／大小一致。這是資料包版本，不能當成後期交易來源 |
| 壓縮與原檔 | ZIP 304,719,974 bytes；四份 CSV 合計 987,498,023 bytes；已讀到每份檔尾並驗 CRC／SHA-256 |
| ZIP SHA-256 | `5dc06173eaa4a4d3b0a5f6afc4daffb0218d95e409aaacba5fdaa0214eacf2a2` |
| 授權 | 原發頁與 API 均標示 CC BY-NC-SA 4.0；原授權文字另存本機快照 |

授權允許在條件內分享及改作，須署名、保留授權與必要聲明、標示修改；有非商業與相同方式分享等條件。公開改作資料應按適用條件使用同一或相容授權，不能額外限制下游權利。商業使用不能由這份授權直接推定已獲准。依據為 Creative Commons 的[授權摘要](https://creativecommons.org/licenses/by-nc-sa/4.0/)及[完整條款](https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.en)。

本專案 v1 限非商業學習與離線研究；未取得可供商業部署的額外授權。不將原始資料、逐筆衍生資料或模型上傳 GitHub，也不把 repository 的程式授權套到原始資料。未來若分享衍生資料或模型，需先確認其適用權利與授權條件。本輪沒有發布、部署或修改整個 repository 的授權。

建議署名：Retailrocket recommender system dataset，Roman Zykov／retailrocket，Kaggle version 2，CC BY-NC-SA 4.0，取用日 2026-10-28；另記錄實際去重、排除、session 與樣本轉換。

## 原檔結構與事件鍵

下表數字來自本輪完整讀檔，不是網頁範例或推薦成績。

| 原檔 | 實測資料列 | 欄位／角色 |
| --- | ---: | --- |
| `events.csv` | 2,756,101 | timestamp、visitorid、event、itemid、transactionid |
| `item_properties_part1.csv` | 10,999,999 | timestamp、itemid、property、value |
| `item_properties_part2.csv` | 9,275,903 | 與 part1 相同，兩份合併才是完整屬性來源 |
| `category_tree.csv` | 1,669 | categoryid、parentid；沒有版本時間 |

事件共 2,664,312 次 view、69,332 次 addtocart、22,457 次 transaction，涉及 1,407,580 個匿名 visitorid、235,061 個 itemid。三種事件沒有評分、負向回饋或推薦曝光欄位。不能據此推得購買數量、幣別、實收收入、取消退款或推薦造成的轉換。

| 事件／鍵查核 | 實測結果 | 契約決定 |
| --- | ---: | --- |
| 五欄完全重複的超額列 | 460 | 主口徑保留最小原列號，所有重複映射留帳；這是研究去重慣例，不證明原站重送 |
| 前四欄相同但 transactionid 不同 | 0 組 | 仍使用全部五欄內容鍵，不能將四欄當永久主鍵 |
| 同訪客同毫秒含多個商品 | 2,132 組 | 保留同時商品集合；禁止依原列號或商品 ID 補造先後 |
| 原始相鄰列時間倒退 | 1,377,377 次 | 原檔不是時間排序；先按訪客、整數毫秒排序 |
| transactionid 缺值 | 2,733,644 列，全部為非交易事件 | view／addtocart 可空；transaction 需非空，不補 0 |
| 不同 transactionid | 17,672 | 不能當成事件逐列唯一鍵 |
| transactionid 跨時間戳 | 1,788 個 | 保留逐列與時鐘，不強制當作單一時點的已驗證訂單 |
| transactionid 跨訪客 | 0 個 | 這個實測結果不構成永久身分或訂單唯一性保證 |
| 已檢欄位缺值／格式 | 必要事件欄位缺值及不合格式 0；非交易帶交易鍵、交易缺交易鍵均為 0 | 未來來源不符仍須排除帳或停止，不能默默轉型 |

來源定位鍵是「CSV 成員 SHA＋原始記錄號」，內容鍵是原始五欄字串的 SHA-256；兩者用途不同。ID 是匿名來源字串，0 有效，不當浮點數，不與 Olist 或 UCI 顧客鍵混接。visitorid 不能直接解讀為同一真實顧客。

## 時間覆蓋與屬性限制

事件最早為 **2015-05-03 03:00:04.384 UTC**，最晚為 **2015-09-18 02:59:47.788 UTC**。兩份屬性檔均從 **2015-05-10 03:00:00 UTC** 到 **2015-09-13 03:00:00 UTC**。時間只代表原檔記錄的事件／屬性時間，缺歷史入庫、修訂、完成水位與實際服務可得時鐘。

| 屬性與分類查核 | 實際結果／影響 |
| --- | --- |
| 屬性總數 | 20,275,902 列、417,053 商品、1,104 種 property；不能把兩個 part 各算成一份完整資料 |
| 行為商品缺全部屬性 | 49,815 個 itemid，即使用全期屬性也找不到；不能排除後只報較容易的商品 |
| available／categoryid | 各 1,503,639／788,214 列；這兩種屬性的完全重複與同鍵同時間值衝突均為 0 |
| 嚴格事前 available | 對全部 2,664,312 原始 view，有 522,307 列找不到嚴格較早的 available；其餘 2,142,005 列中，850,097 為 0、1,291,908 為 1 |
| 嚴格事前 categoryid | 640,748 列 view 無較早分類值，2,023,564 列有值；「有分類值」不等於有分類樹節點 |
| 分類樹 | 1,669 個唯一子節點、25 個根；缺父節點、自連與獨立循環檢查均為 0 |
| 屬性分類值不在樹中 | 30 個不同 categoryid；保留孤立分類診斷，不替其編造父節點 |

以上嚴格事前覆蓋是原始 view 列的完整來源診斷，包含重複、warmup 與尾端；不是建置後樣本分母。不能拿「全期找得到屬性」代替「查詢當下可用」。

[原發頁](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)將屬性描述為由週快照壓縮而成的變更紀錄。即使 available 在某次歷史快照為 0，後來發生瀏覽也不能倒推其當時可售；週快照與事件時鐘不足以驗證連續庫存或入庫可得性。v1 因此只用瀏覽行為建立主要推薦資料，屬性只做來源／時點診斷；主候選目錄不宣稱是可售商品清單。

## 固定的回溯窗口

所有邊界使用 UTC 整數毫秒，左含右不含。以下是去重前原始列數，還不是 session、query 或 target 數。

| 角色 | 窗口 | 原始事件列 | UTC 有事件日數 |
| --- | --- | ---: | ---: |
| 暖身 | 05-03 ≤ t < 05-04 | 13,683 | 1，首日為部分觀察 |
| 訓練 | 05-04 ≤ t < 08-01 | 1,885,346 | 89 |
| 驗證 | 08-01 ≤ t < 09-01 | 553,362 | 31 |
| 預留時間測試 | 09-01 ≤ t < 09-18 | 302,182 | 17 |
| 排除尾端 | t ≥ 09-18 | 1,528 | 末日為部分觀察 |

年份均為 2015。每個窗口的每個 UTC 日都有事件，但這不能證明原站完整匯出。暖身只供因果歷史與先前出現商品目錄，不產生擬合統計或訓練標籤；尾端完全不進入 v1 特徵、目錄、訓練或標籤。

先只用訓練／驗證選模型與設定，固定後允許以 09-01 前的訓練＋驗證重新擬合一次，再做預留測試。查詢與目標必須在同一角色窗；跨界歷史可以作已知上下文，跨界 query-target 不可當同窗監督樣本。禁止隨機切列、全期 k-core 或用測試活動篩訪客。

本輪已看過全期來源結構、數量及時間，沒有建立推薦 target、評分或比較模型。因此是規格固定後的**預留回溯時間測試**，不能稱為未接觸過的全新來源或營運前瞻驗證。尚未消耗推薦成績，但也不能承諾來源從未被檢視。

## 推薦資料契約的主要決定

完整且優先的規則是[JSON 契約](contracts/retailrocket_recommendation_v1.json)，以下供閱讀：

1. **只以 view 定義主要任務。** 同訪客相鄰 view 時間差大於 30 分鐘才另開 session，剛好 30 分鐘留在原 session。同毫秒商品組成無序集合，不製造單一點擊順序。加購與交易保留逐列帳及聚合，不加權混入主要特徵／標籤，也不拿缺加購或缺購買當負例。
2. **查詢預測下一個嚴格較晚的瀏覽集合。** query key 為訪客、session 起始毫秒、當前毫秒；上下文包含目前時間點的整個集合。目標是同 session 下一時間點的商品集合；沒有後續觀察就列為未標註，不能當作不喜歡。查詢後 30 分鐘須完全落在該角色窗，否則留在邊界／右設限帳；目標本身也必須在同窗。
3. **使用當時已看過的商品候選。** 只納入 query 前已有合格 view 的商品，所有算法使用同一目錄；不由未來事件或全期屬性列預先列出未來商品。重看商品可以推薦，不移除已看項目。未來才首次出現的 target 仍保留在完整分母並記為未命中，另報可達率與「全部目標皆可達」條件指標。
4. **主模型統計在 fit 截止前固定。** 驗證與測試可逐查詢更新已知上下文及共用先前商品目錄；模型、共現、熱門、詞彙與尺度等擬合統計不得用當窗未來事件更新。模型不認識的候選商品使用固定熱門回退，零次數也保留；分數相同按商品數值 ID 升序。所有算法必須明列冷啟動覆蓋，不能因無向量就移除較難樣本。
5. **屬性嚴格向前連接。** 僅取 timestamp < query 的最後版本，同鍵同時不同值則該版本未知，不選 part 順序或退回較舊值；直到更晚且明確版本才恢復。無先前值保持未知，不向後回填。分類樹沒有時間，僅作靜態描述；一般雜湊屬性若要入模型，需另立特徵契約並核全鍵衝突。
6. **以完整候選目錄評估。** 主指標 query-macro NDCG@10，另列 Recall、HitRate、MRR、商品覆蓋及 visitor-macro；二元 relevance 對完整下一瀏覽集合，理想 DCG 包含不可達目標。禁止測試負採樣；未知商品是未標註，不是已驗證負例。空候選列表對非空 target 計 0，無可評估 query 才為 null 並附原因。
7. **保留支援與營運限制。** 每窗小組門檻為 max(50, ceil(1%×該窗合格標註 query 數))，另列訪客數；不足者只描述。隨機算法固定五種子 11／29／42／73／101。未來比較應按訪客成組估不確定性，不能把同訪客多個 query 當獨立樣本；不預設此資料足以證明營收、轉換或因果成效。

## 實際驗收與操作

第一套以 Python 標準 CSV／SQLite 完整讀四檔，第二套以 pandas 直接從原 ZIP 重讀事件與全部屬性、另查分類樹。**44 項來源、鍵、計數、時間窗與契約前提核對通過**；這些是資料核對，不是 44 次模型實驗，也不是 builder 逐格驗收。

本輪原始掃描 153.594 秒；第二套實際耗時及 pandas 版本以[凍結收據](../reports/stage8/retailrocket_contract_v1_acceptance.json)為準。沒有安裝套件、重新訓練 Olist／UCI、重估 RFM、建立推薦樣本或計算推薦排名成績。

已有產物只執行下列只讀查核：

```powershell
.\.venv\Scripts\python.exe -B scripts\audit_retailrocket_source.py --verify
.\.venv\Scripts\python.exe -B scripts\freeze_retailrocket_contract.py --verify
```

`--verify` 核 SHA 與大小，**不重做完整 CSV 語意核對**。兩個入口無參數是本輪首次掃描／獨立核對與凍結，已執行完成，會拒絕現有 namespace，不能刪 guard 重播或覆寫 v1。首輪 CSV 分析使用 Codex bundled Python／pandas；沒有在專案外寫出產物或安裝套件。後續只讀指令使用專案 `.venv` 標準庫。

| 保存位置 | 內容 |
| --- | --- |
| `data/raw/retailrocket/` | 原官方 ZIP、API／頁面／授權原始回應、source_manifest、下載紀錄；Git 忽略 |
| `shop-mysql-runtime/retailrocket_intake_v1/` | 逐事件及關鍵屬性來源 SQLite、output_guard；不是推薦資料集，Git 忽略 |
| `shop-mysql-runtime/retailrocket_contract_v1/` | 契約、來源、獨立核對的 SHA guard，Git 忽略 |
| `shop-mysql-runtime/verification/retailrocket-v1/` | 本輪原始狀態、下載程式、執行／交付檢查；Git 忽略 |
| `reports/stage8/`、`docs/contracts/`、本文件及兩支公開程式 | 聚合、規則與可讀流程；不含逐筆資料或憑證 |

## 下一步

先按 v1 實作推薦資料建置器，輸出合格事件、去重／排除帳、瀏覽集合、session、query／target 與跨界帳、事前商品目錄及屬性未知診斷；再以獨立路徑逐筆核對並完整反讀。此時才會知道各窗真正合格的推薦樣本數、冷啟動／可達率及小組支援。

建置驗收通過後，再做固定熱門 baseline → 共現 → 個人化推薦，全部使用同一 query 與候選目錄。主結果為回溯的下一瀏覽相關性；購買推薦、轉換預測、可售庫存或商業服務需要各自的資料／授權契約，不沿用此 v1 冒充已驗證。

Stage 6 UCI v1 已封存，不改其原始、切點、成績或交付文件；UCI 87／83 個聯合小組不足與 Olist 25 個小組不足仍保留。Stage 4／5 繼續按原交接清單待資料；延遲固定每日 10% 預算，Dashboard 暫緩。全專案現況見[進度表](PROJECT_PROGRESS.md)。
