# Stage 9：Retailrocket 熱門 baseline 與完整候選評估執行規格 v1

2026-10-28 先固定單一熱門方案 P0、完整候選評估、分母與預留測試啟用條件，再實作程式。這一輪只有規格與來源凍結，**0 真實統計擬合、0 排名查詢、0 指標計算，預留測試維持鎖定**；baseline 與 evaluator 尚未實作。

優先規則為[機器執行契約](contracts/retailrocket_popularity_execution_v1.json)，上游仍是已凍結的[推薦資料契約](contracts/retailrocket_recommendation_v1.json)與[已驗收資料集](STAGE8_RETAILROCKET_BUILD_V1.md)。正式[規格收據](../reports/stage9/retailrocket_popularity_v1_specification.json)及[凍結驗收](../reports/stage9/retailrocket_popularity_v1_spec_acceptance.json)列出實際來源 SHA、檢查與測試；不把規格驗收當成模型成績。

## 固定唯一熱門方案與統計單位

P0 是全站 canonical view 次數，不使用 query 標籤擬合：`count_i` 等於固定 fit 窗中，`qualified_events.csv` 內商品 i 的每筆 canonical view 加 1。保留未形成推薦標註的 session 末次 view；不能只取有下一次瀏覽的 query 作統計，那會改變母體。

| 操作階段 | 統計資料，UTC 左含右不含 | 預定主統計擬合上限 | 可評估角色 |
| --- | --- | ---: | --- |
| 開發 | 2015-05-04 ≤ t < 2015-08-01，role=train | 1 | validation |
| 最終重估，條件完成後才可做 | 2015-05-04 ≤ t < 2015-09-01，role=train或validation | 1，另存產物 | reserved_test，仍須通過測試閘門 |
| 本輪規格凍結 | 不估任何真實商品次數 | 0 | 無 |

暖身只供歷史／候選，不進熱門次數；尾端不進 fit。加購、交易不加權混入，也不做每訪客去重、時間衰減、活動上限、全期 k-core、機器人刪除或支援門檻篩商品。沒有超參數搜尋、備選熱門方案或事後挑版本。

開發與最終重估各自的統計在出分期間完全固定，不能隨驗證或測試事件更新。獨立重算 count 作驗收 oracle，須另記為 audit，不冒充另一次主方案擬合或新的候選。原訓練期 query 不計排名成績，避免把全訓練期統計的重代入分數當成跨期驗證。P0 是確定性方法，不重複五種子；未來隨機算法仍須遵守資料契約的五種子要求。

## 候選、排序與冷啟動

每個 query 的候選為 `catalog.csv` 中 `first_view_ms < query_ms` 的全部商品，包括暖身商品、訓練未見商品及已看過商品。主目錄只代表歷史看過，不宣稱連續可售，也不套屬性、庫存或已看商品排除。

分數是凍結 `count_i`，查不到就為整數 0；先按次數降序，再按數值商品 ID 升序，取 `min(10,候選數)` 個不重複 ID。新訪客使用相同熱門排序，不因缺訪客模型或特徵被剔除。訓練未見商品保留零分並參與 tie 排序；全統計為零仍按商品 ID 排，另列診斷，不偷偷換算法。空候選回空列表，非空目標的 retrieval 指標為 0，query 留在主分母。

ranker 只可取得凍結次數、query 時間與因果候選 ID。target、next_view_ms、next_role、session 最後時間／總長、未來事件／屬性、測試聚合、query 的整段訓練活動及新舊旗標都不能進 ranker。eval oracle 另讀完整 target，不能將答案注入候選。

「完整候選」指所有候選的精確總排序結果，不要求建立龐大的 query×item 稠密表。可快取正次數順序並處理零次數候選，但必須證明每個 query 與完整目錄排序等價；不能先取全期或全站 top10 再任意丟未來商品，卻漏掉真正應補入的候選。重複／非候選 ID、錯誤長度、排序、分數或 fit 身分都使驗收停止，不藉刪 query 繼續計分。

## 固定分母與指標

評估只按 `queries.csv` 的角色欄精確取 validation 或 reserved_test，不能再因冷啟動、不可達目標、活動、候選向量或小組支援改選樣本。整份來源 SHA 加上固定角色條件綁定名冊；query key 是 visitorid、session_start_ms、query_ms，要求唯一、完整、無多列／少列。

以下都是**上一輪資料驗收的分母**，本輪只核既有報告與檔案 bytes，沒有重新解析測試標籤或計分：

| 評估角色 | 主query分母 | 匿名訪客 | 完整target商品出現次數 | 其中事前可達 | 全目標均可達的query |
| --- | ---: | ---: | ---: | ---: | ---: |
| 驗證 | 166,897 | 62,235 | 166,952 | 161,264 | 161,211 |
| 預留回溯測試，尚未啟用 | 92,086 | 34,875 | 92,116 | 88,907 | 88,879 |

主指標是所有合格 query 等權的 NDCG@10。二元 relevance 對完整下一瀏覽集合，`DCG=Σ hit_r/log2(r+1)`，`IDCG=Σ(1/log2(r+1)), r=1..min(10,完整target數)`；不可達商品仍在完整 target 數，不能縮小理想分母。逐 query 算完才取平均。

次指標包括 query-macro Recall@10（命中商品數／完整 target 數）、HitRate@10（至少一個命中）、MRR@10（第一個命中排名的倒數）及 visitor-macro NDCG（先在訪客內平均，再等權平均訪客）。商品覆蓋是所有輸出推薦 ID 的聯集／該角色所有評估 query 的因果候選聯集；候選隨時間單調增加時，可用 `first_view_ms < max(query_ms)` 精確求聯集分母，不能拿全期商品數替代。

完整目標均在候選內的條件結果另列，上表條件query數固定；使用相同公式及完整target，另報query、訪客、target分母，不能取代主成績。可達商品出現比例及全目標可達query比例屬結構覆蓋，與模型命中成績分開。

不做評估負採樣、答案注入或 unseen-item 負例推論。非空目標遇空候選計0；沒有query才回null與原因，候選聯集空時商品覆蓋為null。來源／角色／成熟條件／target／名冊不符就停止，不能縮分母繼續。整數、ID、列表與名冊要求精確一致；浮點核對絕對／相對容差各1e-12，禁止NaN或Infinity冒充有效結果。

## 小組與回溯限制

每個切片保留query、不同匿名訪客及target數，門檻為max(50,ceil(該角色主query數／100))。0筆為無樣本、指標null；非空但不足者可描述，標記descriptive_only，不能事後合併、刪除或調參來通過。

| 角色 | 小組query門檻 | 多商品當前集合 | 多商品目標 | 判定 |
| --- | ---: | ---: | ---: | --- |
| 訓練資料描述，不計排名 | 6,427 | 199 | 192 | 原低支援限制保留 |
| 驗證 | 1,669 | 56 | 53 | 兩組不足，只描述 |
| 預留回溯測試 | 921 | 33 | 29 | 兩組不足，只描述；尚無成績 |

其他切片固定為fit前已見／未見訪客、原始訓練view活動0／1／2–5／6+，以及實際模型商品覆蓋：target全部有正fit次數、正／零次數混合、全部零次數。模型覆蓋必須查真正凍結的count表，不能拿builder的`targets_seen_before_fit`或`new_to_fit_targets`替代；暖身出現過的商品仍可能沒訓練統計。

同訪客query相依，不能把query數當獨立樣本數。本P0版本只做描述、不報信賴區間或效果顯著；未來推論比較另凍結訪客群組重抽樣方案。沒有新增營收、轉換或營運效能門檻。

## 預留測試啟用條件

初始狀態為locked，本輪不啟用。後續必須同時滿足：

1. 資料、上游契約與本規格來源SHA完整一致。
2. baseline與evaluator已實作，程式、環境與來源固定。
3. 手算指標、窗界、未來資料注入、零次數tie、短／空目錄及不可達目標等合成反例全部驗收。
4. 一次主開發fit、完整驗證名冊／排序／指標的獨立反讀通過，保留所有成績及小組限制。
5. 驗證驗收收據、唯一P0方案及精確實作在最終重估前固定。
6. 另存一次train＋validation最終重估，獨立次數核對通過，fit產物SHA在第一筆測試排序前固定。
7. 使用者後續明確要求執行預留回溯測試；本輪只要求規格凍結，不構成該次出分啟用。
8. 第一筆測試排序前以排他方式寫入持久使用身分／狀態，包含資料、規格、程式、環境、最終fit與query名冊識別。

條件是技術與規格驗收，**不要求驗證NDCG達某分數或改善才開測試**，避免只挑好看的驗證版本。使用者後續已明確授權時，不重複詢問相同授權。

測試為一次邏輯執行，排序開始前就標記已使用；技術失敗保留部分產物、嘗試次數與進度，不重設閘門。只允許完全相同資料／規格／程式／環境／fit／名冊身分恢復，不能趁重試重估或調設定。看過測試成績後完整回報，不能再用這批預留成績選方案；實質改動另立規格與新的預留評估證據。

資料結構與標籤已在上輪建置驗收讀過，仍沒有推薦排名成績；此測試只能稱預留的回溯時間評估。事件時間代理、缺入庫／修訂／完成水位、匿名身分、無曝光／propensity或連續可售庫存等限制不變；CC BY-NC-SA 4.0非商業、署名及適用分享條件保留，沒有取得商業部署權利。

## 本輪驗收、檔案及下一步

[規格檢查器](../scripts/retailrocket_popularity_protocol.py)只有一致性守門，不實作fit、rank或指標。[28項反例測試](../tests/test_retailrocket_popularity_protocol.py)實際通過，涵蓋驗證／測試混入統計、暖身加權、答案輸入、負採樣、縮分母／IDCG、空目錄刪query、門檻降低與錯誤開測試。完整來源鏈以SHA／大小核對，資料CSV只當bytes讀取，不重建資料或計推薦成績。

目前只用以下指令驗既有凍結：

```powershell
.\.venv\Scripts\python.exe -B scripts\freeze_retailrocket_popularity_v1.py --verify
```

`--freeze`是本輪首次流程，完整namespace重入只驗既有來源，部分產物拒絕覆寫／重播。`--verify`核來源與收據bytes及規格一致性，不重跑測試、不估統計、不解析資料CSV或開啟測試。

所有檔案在shop內。規格／來源guard與初始locked收據放`shop-mysql-runtime/retailrocket_popularity_spec_v1/`；測試、原狀與交付檢查放`shop-mysql-runtime/verification/retailrocket-popularity-spec-v1/`，均由Git忽略。未來開發、最終重估、測試及使用journal另放`shop-mysql-runtime/retailrocket_popularity_v1/`下的獨立目錄，**本輪尚未建立**。原始資料、逐query／item／visitor與模型不進Git，公開只保留程式、規格與聚合證據。

下一步依本規格實作P0與完整候選evaluator，先做手算與獨立oracle合成驗收，再凍結真正開發執行入口；通過後才估一次訓練統計並完整評估驗證窗。預留測試繼續locked，最終重估及測試不是本輪成果。

原Stage 6 UCI封存、UCI 87／83與Olist 25個小組限制保留；Stage 4／5仍待交接資料，延遲每日10%固定，Dashboard暫緩。[全專案進度](PROJECT_PROGRESS.md)另列規格完成與程式／成績未做的狀態。
