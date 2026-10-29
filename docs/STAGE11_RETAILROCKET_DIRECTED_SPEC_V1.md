# Stage 11：候選盤點與 D1／C1／P0 比較規格 v1

本輪選定一個新候選：**D1，有向相鄰 basket 的 session 關聯模型**。研究問題是：在相同 session 計數單位、單商品支援、完整因果歷史、候選與分母下，把任意無序共現限制成「有向且相鄰的關聯」，對下一 basket 的 validation NDCG 有何影響？

P0 與 C1 的 validation 成績、切片及 C1−P0 區間已在選 D1 前檢視。這是已曝光開發窗上的新比較規格，沒有未知資料或前瞻驗證宣稱。本輪只盤點方法、固定規格、核對來源 bytes 及測試規格守門；**0 新擬合、0 排名、0 指標、0 bootstrap、0 真實 CSV／JSONL 列解析**。D1 模型、評估器與真實入口尚未實作，預留測試仍 locked。

機器定義見[比較契約](contracts/retailrocket_directed_paired_v1.json)，方法選擇及來源索引見[候選盤點](../reports/stage11/retailrocket_stage11_candidate_inventory_v1.json)。正式凍結的實際來源數、檢查與測試結果見[來源快照](../reports/stage11/retailrocket_directed_v1_specification.json)及[規格驗收](../reports/stage11/retailrocket_directed_v1_spec_acceptance.json)，不能把規格測試當作尚未實作的模型驗收。

## 候選盤點與選擇理由

專案現有進度沒有指定 Stage 11 必須採用某一算法。本輪以資料契約適配、可手算核對、變更範圍及資源需求選擇，不試跑候選再挑最好成績，也不把外部論文成績套到本資料。

| 候選類別 | 現有資料與所需工作 | 本輪決定 |
| --- | --- | --- |
| 有向相鄰轉移類 | 已有依時間排序的 view baskets；可做精確稀疏計數與跨界核對 | **選用自訂 D1**，保留 C1 的 session 二元單位、S_i、H(q) 與回退規則 |
| Session-kNN | train sessions 與當前歷史可用；需另定相似度、鄰居數、完整搜尋或抽樣、同分與成本 | 後續候選；本輪不實作 |
| Implicit ALS | 可另建 visitor／session×item 表徵；需固定維度、confidence、正則化、迭代、初始化及新 session fold-in | 本輪不選，未安裝或擬合新套件 |
| BPR | 隱式互動可用；仍需選底層模型、成對抽樣、優化與種子，未觀測項不等於確定負例 | 本輪不引入隨機訓練或負樣本策略 |
| EASE 稠密線性模型 | 標準閉式解需要 item×item Gram／逆矩陣，資料型態相容但資源尺度不合 | 本輪不選；近似版本須另立方法，不能冒充等價實作 |

轉移與 session-kNN 的定義參考 Ludewig／Jannach 原論文 §3.1.2、§3.2.2；其標準 MC 使用相鄰轉移次數、來源總轉移正規化及最後事件。**本專案 D1 並非該標準 MC**，下節的 session 去重、C1 支援分母與完整歷史是本專案固定的變體。[原論文 v2](https://arxiv.org/abs/1803.09587v2)

ALS 的 confidence 加權因子模型與 BPR 的成對排序訓練各有額外設定，需獨立規格；它們不是因新訪客而完全不可用，但新 session 表徵不能省略。[Hu 等人原文](https://yifanhu.net/PUB/cf.pdf)、[BPR 原文](https://arxiv.org/abs/1205.2618v1)

EASE 的 item×item 結構見原文 §3.1。依既有 train 正支援商品 198,946 個計算，一個 float64 稠密矩陣需 `198946²×8 = 316,636,087,328 bytes`，約 **294.890336 GiB**，已超過本規格的 8 GiB 程序預算。這是單矩陣結構估算，不是實測峰值或執行時間，還未計其他矩陣與分解工作空間。[EASE 原文](https://arxiv.org/abs/1905.03375v1)

來源索引保存 URL、版本、作者及查閱重點，沒有聲稱保存完整論文副本。D1 的選擇理由是較少同時改動既有口徑、可精確核對；本輪沒有證據證明它優於 C1。純互動方法不能替無 train 支援商品學得關聯，因此不以「解決冷商品」作本輪研究問題。

## 唯一候選的精確定義

令 `S_i` 為既有 C1 的 train session 商品支援，連同 singleton 及沒有轉移的商品完整重用，不另做主要支援估計。`D_ij` 定義為：在同一 train session 的**原始相鄰**兩個 baskets 中，曾有前 basket 含 i、後 basket 含 j，且 i≠j 的 session 數。

| 項目 | 固定規則 |
| --- | --- |
| 時間與來源 | `baskets.csv`；UTC [2015-05-04, 2015-08-01)，兩端皆 train、同 session、原 basket_index 差 1、時間嚴格增加且間隔≤30分鐘 |
| 跨界 | 只計兩端都在 train 截止前的相鄰關係；不接 warmup→train 或 train→validation，不因 session 未來結束而刪整個 session |
| 不橋接 | 不先刪中間 basket 再把剩下兩個接成相鄰；原 index 缺口不形成轉移 |
| 未標註 baskets | 訓練統計沿用所有合格 train baskets，不用 labelled queries 或成熟標籤名冊篩選 |
| 同時多商品 | 兩個相鄰 basket 做笛卡兒積，排除 i=j；basket 內不造順序、不按 ID 猜先後，不除以 basket 大小 |
| 二元 session 計數 | 同 session 的同一方向只加 1；跨 session 各加 1；反向另計 |
| 零對角 | 不存 self-edge；已看過的商品仍可當候選，可能從其他 seed 或 P0 補位取得排名 |
| 正規化 | 完整重用 `S_i`，不改成 outgoing 次數，不做 row-sum 正規化 |
| 無新增搜尋 | 無平滑、衰減、混合權重、最低支援調參、top-L、session／history 上限、剪枝或抽樣 |

原 C1 的無序 `C_ij` 與 D1 的有向 `D_ij` 必須有：

- `0 < D_ij ≤ C_ij ≤ min(S_i,S_j)`；`D_ij` 與 `D_ji` 可以不同，兩者相加也可能大於 `C_ij`。
- `ΣD_ij = Σsession |該 session 的不同有向相鄰邊|`。
- `ΣD ≤ 2×ΣC`，全域 D 邊數≤兩倍 C pair 數。這是計數界，不是掃描工作量、模型記憶體或速度保證。
- singleton 與沒有轉移的 session 不產生 D 邊，但其 S_i 保留；outgoing keys 不能取代共同 train 支援名冊。

這次同時限制了**方向與鄰近性**，不能分別歸因其中一項。其餘 C1 口徑保持一致，以避免同時更換重複計數、分母、歷史及 self-edge 政策。

## 查詢歷史、排序與回退

`H(q)` 與 C1 完全相同：同 session 截至 query timestamp／basket_index 的不同商品聯集，包含當前 basket，允許已發生的跨角色過去上下文；不使用訪客終生歷史、未來 basket、target、session 最終長度、購物車／交易或診斷旗標。

對候選 j 的分數為 `Σ D_ij/S_i`，其中 i∈H(q)、i≠j、S_i>0；缺 S 或 D 貢獻精確零。以精確有理數比較，依序按 D1 分數降冪、原 P0 次數降冪、數值商品 ID 升冪排序。分數可超過 1，不是下一次瀏覽或購買機率。

候選仍是 first_view < query 的完整因果目錄，不刪已看商品、冷商品或無 outgoing 商品，不做負樣本抽樣、target 注入、可售過濾或屬性特徵。D1 邊與 P0 次數各自查找、各自缺值才補零；沒有 D1 證據但有正 P0 次數的商品，必須保留該次數。無正證據時完全回退 P0；不足 10 個正分商品時，以完整零分候選順序補足，不能只附加截斷的 P0 top10。短／空目錄沿用原規則與完整分母。

同一歷史下，D1 每候選分數與正證據候選集合均受 C1 上界限制；這**不代表 NDCG 必然較低**，排序相對順序仍可能改變。C1 完全無正證據的查詢必然也在 D1 完全回退，但反向不一定成立。這些是待合成與真實 oracle 核對的數學不變量，並非本輪新效能。

## 三臂配對、主要比較與不確定性

| 項目 | 固定內容 |
| --- | --- |
| 原對照 | 原 P0 模型／排名／指標、C1 模型／queries／bootstrap／收據只讀重用；不重訓、不重排、不再產生 C1−P0 區間 |
| 真實 D1 執行上限 | 未來一次 train 主擬合＋一次獨立計數驗收；本輪均未執行 |
| validation | UTC [2015-08-01, 2015-09-01)，166,897 查詢／62,235 匿名訪客，三臂 key 與順序完整一致，缺／多／重複任一筆就停止 |
| 分母 | 完整 target 166,952 次、可達 161,264 次、共同候選聯集 222,754；不可達 target 不刪除 |
| 唯一主要比較 | 全查詢平均 `NDCG_D1−NDCG_C1` |
| 次要參照 | D1−P0、Recall／HitRate／MRR、visitor-macro NDCG與共同聯集 coverage 差，僅描述 |
| 條件結果 | 同 161,211 筆全 target 可達查詢，另列描述，不取代主分母 |
| 主區間 | D1−C1 NDCG，2,000 次 paired visitor-cluster bootstrap、95% percentile、linear quantile |
| 不新增推論 | D1−P0、次指標與切片無區間／p 值，不宣稱同時顯著勝過兩對照；不設事後效能門檻 |
| 精度 | key、計數、歷史、有理分數及順序精確相等；指標浮點絕對／相對容差 1e-12，NaN／Infinity 禁止 |

bootstrap 固定 NumPy 2.5.4、PCG64、seed 42，依數值 visitor ID 排列 62,235 個 cluster，每次抽同數量訪客並保留其全部查詢；按抽中查詢總數加權，不能改成訪客平均或 iid 查詢抽樣。C1 基準為原 query JSONL 反讀的 binary64 NDCG，新差值依固定順序 `math.fsum` 歸約。

每次新抽樣都須與舊 C1 bootstrap 的 draw SHA（little-endian int64）、RNG 前後狀態與抽中查詢分母一致；**D1 差值與區間必須新算並另存**，不能挪用舊 C1−P0 數值。保留相同抽樣是對帳設計，不讓曝光過的 validation 變成未知資料。負向或跨零結果同樣完整報告。

## 冷商品與小組限制

| 保留項目 | 規則 |
| --- | --- |
| 原切片 | visitor seen/new、原 train 活動組、current／target 單／多商品，及按共同 S_i／P0 正支援鍵的 target all-positive／mixed／all-zero |
| 冷目標 | 既有 all-zero 切片 11,943 查詢／5,769 訪客；C1／P0 當輪 NDCG／Recall／HitRate／MRR 為 0，並非 coverage 亦為 0。這不是 D1 的成績，也不代表全都不可達或從未出現 |
| 完全回退 | C1 既有 16,319 筆與冷目標是不同診斷，不能相加；D1 實際回退量待執行，不因多回退刪查詢 |
| 小組 | current multiple 56、target multiple 53、mixed 3，均低於 1,669 查詢門檻，只能描述，另報訪客數 |
| 舊限制 | train 多商品 199／192、locked test 33／29；Olist 25、UCI 87／83 小組不足仍保留 |
| D1 專屬診斷 | 共同 S 支援 seed 數、具有 D outgoing 的 seed 數、target incoming 支援、正證據與補位分布分開列；不能用 outgoing keys 重新定義共同冷商品組別 |

無 outgoing 的商品仍可能有 incoming 邊，不能因此從候選刪除。新訪客可能已有當前 session 歷史，不等於完全無上下文冷啟動。匿名鍵不等於獨立真人；缺入庫／修訂／完整性、曝光／propensity與連續庫存證據，仍不能宣稱轉換、營收、因果或營運改善。原非商業等來源條件不變。

## 後續實作驗收與資源

下一輪先做 D1 計數、三臂配對器、bootstrap 及獨立合成 oracle。手算與反例至少涵蓋：方向／反向、同 session 重複、singleton、同時多商品跨 basket 笛卡兒積／零對角、原 index 缺口與跨界不橋接、未來注入、未知 seed、incoming-only 候選、精確同分／完整補位、三臂缺筆／分母、正確成組權重與同 draw 新 delta。

獨立實作應由原 baskets 的相鄰鍵連接及 `DISTINCT(session,i,j)` 重建 D，另核 S_i，核對全部 session lineage／計數，再以精確有理排序與完整零分補集、獨立 Decimal／Fraction 指標、全部巢狀欄值及全部 bootstrap 反讀驗收；不接受抽樣核對取代完整驗收。

真實擬合前，另盤點 train-only 相鄰 baskets、原始發射量 `Σadj(|A|×|B|−|A∩B|)`、同 session 去重邊量與峰值。預檢可讀角色欄以篩選，只解碼 train 商品陣列，不解碼 validation／test 的商品或 target 內容；可建立單 session 暫時集合，不先跨 session 聚合 D 模型。本輪沒有執行此掃描。原始發射量會受重複瀏覽影響，不能用兩倍 C1 pair 計數當算時保證。

未來一輪 D1 fit＋完整 validation／bootstrap＋獨立驗收固定 RSS 8 GiB、執行目錄 20 GiB、6 小時上限；磁碟剩餘至少 8 GiB、系統可用記憶體至少 4 GiB。採合作式監控，檢查位置與環境在實作入口再凍結；這不是 OS 瞬時硬性限制。超限停止並保留 started／failure／部分證據，不能暗中抽樣、剪枝、改分母或重試。

## 保存、鎖定與操作

| 位置 | 本輪角色 |
| --- | --- |
| `docs/contracts/retailrocket_directed_paired_v1.json` | 新 D1 比較契約，沒有覆寫 C1／P0 |
| `reports/stage11/retailrocket_stage11_candidate_inventory_v1.json` | 五類方法盤點、一手來源、選擇理由及結構估算 |
| `reports/stage11/retailrocket_directed_v1_specification.json`、`retailrocket_directed_v1_spec_acceptance.json` | 凍結來源、規格檢查、守門測試與 JSON 反讀收據 |
| `shop-mysql-runtime/retailrocket_directed_spec_v1/` | 本輪 initial locked scope／output guard |
| `shop-mysql-runtime/verification/retailrocket-directed-spec-v1/` | 原狀、測試、完整性及文件交付日誌，Git 忽略 |
| `shop-mysql-runtime/retailrocket_directed_paired_v1/` | 未來真實執行命名空間，本輪不得建立 |

本輪核對並綁定 C1／P0 原結果與交付包的固定 bytes，包外依賴也在 shop 內。交付包明示的 README 等可變脈絡快照不要求與現在的索引相同；舊契約、程式、結果、模型、gate、ZIP 與收據維持原狀。

```powershell
# 已凍結後只核來源與規格bytes／metadata，不跑模型、真實資料列或新指標。
.venv\Scripts\python.exe -B scripts\freeze_retailrocket_directed_v1.py --verify
```

`--freeze` 僅用於首次空白規格命名空間；完整重入只驗證，部分證據拒絕覆寫。規格驗證保留 `scope_at_freeze` 的歷史範圍，不因日後有獨立授權的 D1 產物就宣稱歷史規格已執行模型。未來真實入口須另經實作／合成／成本驗收並凍結。

**預留測試仍 locked。** D1 不沿用 P0／C1 gate 取得授權，也不建立 final refit、test 輸出或 usage journal。原 P0 八項條件與 C1 最終選模限制仍有效；D1 另需最終選模／refit／test 規格與實作，以及後續明確的執行範圍。有利 CI、規格凍結或合成通過都不解鎖 test。完整原條件見[C1／P0 交付](STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md)。

下一步是**依本規格實作 D1、三臂配對評估器及 bootstrap，完成手算與獨立合成 oracle，再做 train-only 成本盤點並凍結真實 validation 入口**。本輪不執行這些後續工作；Stage 4／5 仍待資料，每日 10% 提醒固定，Dashboard 暫緩。全專案狀態見[進度表](PROJECT_PROGRESS.md)。
