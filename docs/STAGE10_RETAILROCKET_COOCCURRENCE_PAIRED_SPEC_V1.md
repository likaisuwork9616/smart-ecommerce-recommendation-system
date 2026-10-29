# Stage 10：Retailrocket 共現 C1 與 P0 配對比較規格 v1

本輪制定並凍結規格。C1 計數器、推薦器、配對評估器與 bootstrap 尚未實作；沒有新增擬合、排名、比較成績或信賴區間。預留測試維持 locked。機器契約為 [retailrocket_cooccurrence_paired_v1.json](contracts/retailrocket_cooccurrence_paired_v1.json)，改變方法須另立版本。

P0 的 validation 結果已在制定本規格前被檢視。因此本規格固定於 C1 出分之前，不能聲稱在任何 validation 曝光前預先登錄，也不能將後續比較當作未知測試或上線效果。

## 比較對象與不變的資料

只比較既有 P0 與一個確定性的 C1，不搜尋參數、不混合兩者分數。P0 直接重用已驗收的模型表、查詢排序與逐筆指標，禁止重訓或重新排名。其 fit ID 為 `3aaf35e8a4853bcd5e83caff917e90e318ef41a77e37e5f292d1bcc18f7146cd`，模型有 198,946 個正計數商品；完整檔案 SHA 與來源由凍結報告綁定。

C1 僅允許一次主擬合，另做獨立計數核對。統計固定使用 UTC `[2015-05-04, 2015-08-01)` 的 train view；warmup、validation、test 不參與統計，評估時不更新統計。沿用資料契約 v1 的去重、排除、30 分鐘 view session、同毫秒無序 basket 與角色歸屬，不重做資料清理。

| 固定 validation 項目 | 已驗收數量／規則 |
|---|---|
| 查詢／訪客 | 166,897／62,235 |
| 完整 target occurrences | 166,952 |
| 可達 target occurrences | 161,264 |
| 全部 target 可達的條件查詢 | 161,211；只能另列描述 |
| 因果候選聯集 | 222,754 商品 |
| 新訪客查詢 | 134,249；全部保留 |
| current／target 多商品查詢 | 56／53；小組支援不足 |
| target 全正計數／混合／全零計數 | 154,951／3／11,943 查詢 |
| 小組支援門檻 | 1,669 查詢，另報訪客數與 target 數 |

上述數字來自 [P0 實際開發報告](../reports/stage9/retailrocket_popularity_v1_development.json)，不是本輪重算。P0 原有開發 NDCG@10 為 0.0016818292431993401、HitRate@10 為 0.004182220171722679。

## 共現計數

先以角色及時鐘篩出 train basket，再依既有 `(visitorid, session_start_ms)` 分組。令 `B_s` 是該 session 在合格 train 範圍內的不同商品集合。跨截止線的 session 只使用 train 部分；不得依未來 session 結束時間、總長度或 validation 成員決定是否保留、合併或刪除。warmup 成員不計入統計。

實際欄位為 `baskets.csv` 的 `query_ms`（UTC epoch 毫秒）、`role`、`basket_index` 與 `items`（去重商品 ID 字串的 JSON array）；公式中的 basket timestamp 指 `query_ms`。

- `S_i = Σ_s 1[i ∈ B_s]`：每商品每 session 只算一次，重複瀏覽不放大。
- `C_ij = Σ_s 1[i,j ∈ B_s]`，`i ≠ j`：每無序商品對每 session 只算一次。
- 以數值商品 ID `i<j` 儲存，查詢時對稱使用；沒有 `C_ii`。同毫秒 basket 的不同商品可以共現，不創造先後順序。
- 單商品 session 仍貢獻 `S_i`。不只保留會產生 pair 的 session，避免改變模型支援範圍。
- 不設鄰居 top-L、最低 pair 次數大於 1、session/history 長度上限、活動量／bot／k-core 篩除、抽樣或時間衰減。

必須逐項核對：`S_i` 的正整數鍵集合等於 P0 正計數鍵集合；`S_i <= P0_count_i`；`0<C_ij<=min(S_i,S_j)`；`Σ_i S_i=Σ_s |B_s|`；`Σ_(i<j) C_ij=Σ_s |B_s|(|B_s|-1)/2`。這是 session 關聯計數，不是有向下一點擊轉移。

實作階段須先盤點 train-only session 基數與精確 pair 發射工作量，並在真實入口凍結磁碟、記憶體及執行時間上限。允許在 shop 內精確分塊／落盤；資源不足就停止並保留證據，不能偷偷截斷大 session、鄰居或歷史。本輪未解析真實 CSV，也尚未估計此成本。

## 歷史可用範圍與因果候選

`H(q)` 為同一已驗收 session 內，`basket_index <= query_basket_index` 且 `timestamp <= query_ms` 的 view 商品集合，包含當下的同毫秒 basket；每商品只貢獻一次。可使用在當下已出現的同 session warmup、train 或較早 validation 脈絡，但不能更新 `S_i/C_ij`。不得擴張成訪客終身歷史，不使用購物車、交易、target、next_view、未來 basket、session 最終長度或 P0 已知命中狀態。

新訪客仍可用當下 session。無 train 支援的 seed 保留於歷史帳並貢獻零。契約中的 current basket 非空；若 join 後歷史空白，視為錯誤停止，不能以回退掩蓋遺失。

候選與 P0 完全一致：`C(q)={catalog item | first_view_ms < query_ms}`。不抽負樣本、不加入答案、不利用 property-only、未來商品或未證明的可售狀態，不刪已看商品。真實評估必須驗證每筆候選數及可達 target 數不變。

## 分數、排序與回退

對每個候選 `j`：

```text
A_q(j) = Σ [ C_ij / S_i ]
          i ∈ H(q), i != j, S_i > 0
```

缺 pair 視為零。使用精確約分有理數，透過分數／交叉相乘比較；不能以浮點容差創造平手。分數可能超過 1，不能解讀為點擊或購買機率。

固定排序為「共現有理分數降冪 → 既有 P0 整數 count 降冪 → 商品 ID 數值升冪」。自我邊不貢獻，但已看商品仍可由其他 seed 獲分或進入 P0 回退。

- 沒有候選獲正共現分數時，完整排名須與該查詢 P0 完全相同。
- 正分商品不足 10 個時，先排正分，再依 P0 count／ID 從所有零分候選補足，排除已選商品；不能僅接上截斷的 P0 top10。
- 不在 train 模型的候選仍保留，兩種統計均為零；空候選回空清單並保留查詢、檢索指標為零。
- 清單不重複且長度為 `min(10, |C(q)|)`。稀疏加總可作精確最佳化，但須證明等同完整候選排序，不得截斷鄰居。

## 逐查詢配對與指標

查詢鍵固定為 `(visitorid,session_start_ms,query_ms)`。C1 與原有 P0 必須完整一對一、鍵及順序一致；缺筆、重複或多筆即停止。不得 inner join 掉困難案例，兩方法使用相同完整 target、候選、主分母及切片。

主要量為 `Δ_Q = mean_q(NDCG_C1(q)-NDCG_P0(q))`，分母固定全部 166,897 查詢。沿用 P0 v1 的 K=10、binary relevance、完整 target Recall／IDCG；不可達答案仍留在分母。次要量為 query-macro Recall、HitRate、MRR 差，visitor-macro NDCG 差與 coverage 差。Coverage 是兩邊各自推薦聯集除以同一 222,754 候選聯集後相減，不是逐查詢 coverage 平均。

161,211 筆全部 target 可達查詢只能另報條件結果。無性能及格線；完整驗收與方法有沒有變好是不同問題。鍵、計數、歷史、有理分數及順序須精確相同；浮點逐筆項及彙總採絕對／相對 `1e-12`，空組明示 null，不允許 NaN／Infinity。

## 配對不確定性：訪客成組 bootstrap

只對預先固定的主要 `Δ_Q` 做 95% percentile interval，不做小組、次指標區間或 p 值。將 62,235 個 validation 訪客 ID 數值升冪排序，2000 次有放回抽取 62,235 個訪客位置；每次同時帶入兩方法該訪客的所有查詢。

固定 NumPy 2.5.4、`Generator(PCG64(42))`。依序每次呼叫 `rng.integers(0,V,size=V,dtype=np.int64)`。若 `n_v` 為查詢數、`d_v` 為訪客內逐筆 NDCG 差之和、`w_v` 為本次抽樣次數：

```text
Δ_b = Σ_v w_v*d_v / Σ_v w_v*n_v
CI = np.quantile(replicate_deltas, [0.025,0.975], method='linear')
```

這保留 query-macro 的權重，不以訪客平均差的等權平均取代，也不將同訪客查詢當成獨立抽樣。保留每次抽樣位置的 little-endian signed int64 C-order bytes SHA、RNG 前後狀態、抽中查詢分母及結果；獨立 oracle 重播所有 2000 次。seed 是重抽樣設定，兩模型本身確定性，並非五種模型種子試驗。

逐筆差使用 binary64 C1 NDCG 減去原 P0 CSV round-trip 浮點值；主平均與訪客內差值和依原查詢順序用 `math.fsum`，重抽樣分子依訪客數值順序用 `math.fsum(w_v*d_v)`，分母採精確整數。percentile 輸入為原 replicate 順序的 float64，避免實作自行選擇不同加總權重或精度。

區間只描述已曝光 validation 的訪客叢集重抽樣，不代表獨立真人樣本、未知測試或因果效果。跨零、變差結果照實保留；不得再選 seed、重抽設定、模型或小組以改善結果。

## 小組與診斷限制

沿用原有新／舊訪客、train 活動量 0／1／2–5／6+、current／target 單／多商品及 target 模型覆蓋切片，列出各自查詢、訪客及 target 數。`S_i` 保留單商品 session，使正支援鍵集合等於 P0；target 模型覆蓋切片不能因換模型而改名冊。

另列歷史長度、可支援 seed 數、正共現候選數、完全回退原因（無支援 seed／有支援但無因果鄰居）、正證據 0／1–9／至少 10 與零分補位數，僅供描述、不能用來排除查詢。

門檻仍為 `max(50,ceil(166897/100))=1669`。validation 多商品 56／53、混合支援 3 筆只能描述，無小組推論、挑組、合併或調參。原有 train 多商品 199／192 與 locked test 33／29 的不足也保留；test 數量僅引用既有資料契約收據，本輪不讀 test 標籤出分。

## 驗收、保存與預留測試鎖

本輪凍結器僅驗證規格、既有 JSON 收據及檔案 SHA／大小，真實 CSV 只讀取位元組做雜湊。使用方式：

```powershell
.venv\Scripts\python.exe -B scripts\freeze_retailrocket_cooccurrence_v1.py --freeze
.venv\Scripts\python.exe -B scripts\freeze_retailrocket_cooccurrence_v1.py --verify
```

完整命名空間只允許驗證；部分凍結拒絕覆寫。`--verify` 會核對初始鎖定狀態所要求的空命名空間；未來獨立入口應將這份收據當成歷史凍結證據，不能把它當作持續執行或解鎖機制。私人凍結存於 `shop-mysql-runtime/retailrocket_cooccurrence_spec_v1/`，測試紀錄存於 `shop-mysql-runtime/verification/retailrocket-cooccurrence-spec-v1/`。

下一輪才實作 C1、配對評估及 bootstrap，先做手算與獨立合成 oracle。至少涵蓋重複／單商品 session、同時 basket、跨截止線、未來不得改 fit、query prefix、新商品、完全／部分 P0 回退、不刪已看、有理平手、完整配對分母，以及成組抽樣的權重與重播。

之後另凍結真實執行入口與成本限制，才允許一次 C1 train 擬合及同名冊 validation。逐筆歷史／有理排序／配對指標／所有彙總與 bootstrap 均須獨立核對及反讀。未來私人資料表、pair 模型、排名與 draws 僅能在 Git 忽略的 `shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/`；該執行目錄本輪必須不存在。公開只保存程式、規格與不含 ID 明細的彙總收據。

預留測試不能由有利 validation／CI 或 P0 既有 gate 啟用。須另有最終模型選擇、重擬合、test 執行規格與實作，再取得後續明確 test 執行範圍；本輪不建立 final-refit、test 輸出或 usage journal。缺少 ingestion／revision／完整性、曝光／propensity、連續可售庫存等證據，仍是回溯研究，不能推論營收、轉換或上線因果提升。匿名訪客不等於已驗證獨立真人，NC-SA 授權與 Olist／UCI 既有限制仍適用。
