# Stage 11：D1 實作、獨立合成驗收與真實入口 v1

本輪依[已凍結比較規格](STAGE11_RETAILROCKET_DIRECTED_SPEC_V1.md)實作 D1、三臂配對與 bootstrap，先完成手算及獨立合成驗收，再盤點 train-only 成本，凍結一次真實 validation 的入口。**本輪沒有擬合真實 D1、排名真實 validation 或產生 D1 效能／區間；預留測試仍 locked。** P0／C1 的模型、逐筆值、原區間、gate 與交付包保持原 bytes。

實際測試數、兩組正式合成結果、逐 session 成本與來源數以[實作驗收收據](../reports/stage11/retailrocket_directed_v1_implementation_acceptance.json)為準；執行環境、來源 SHA、資源限制與唯一入口見[真實入口規格](../reports/stage11/retailrocket_directed_v1_validation_specification.json)。這些準備數字不能當成真實推薦成績。

## 實作範圍

| 新檔案 | 責任 |
| --- | --- |
| [retailrocket_directed.py](../scripts/retailrocket_directed.py) | 原始相鄰、有向、session 二元邊計數；完整共享 C1 S；Fraction 排序與原 P0 補位；D1−C1 bootstrap |
| [retailrocket_directed_io.py](../scripts/retailrocket_directed_io.py) | 原 P0／C1 控制值只讀配對、完整三臂名冊／歷史／候選／分母、切片與診斷、排他輸出 |
| [retailrocket_directed_oracle.py](../scripts/retailrocket_directed_oracle.py) | 獨立 SQL 相鄰 join／session DISTINCT、S 重建、lineage／全部 query 巢狀欄值／全部抽樣反讀 |
| [retailrocket_directed_cost.py](../scripts/retailrocket_directed_cost.py) | train-only 原始發射量與每 session 去重邊數；獨立 SQL 逐 session 成本核對，不建全域 D 模型 |
| [run_retailrocket_directed_v1.py](../scripts/run_retailrocket_directed_v1.py) | 準備、凍結、來源／資源／部分失敗守門及未來單次 validation；沒有 final-refit／test 模式 |

兩端都須是 train、在 UTC [2015-05-04, 2015-08-01)、同 session、原 index 差 1、時間增加且相隔不超過 30 分鐘。原 index 缺口不能橋接；不使用 labelled query 篩 train、不以未來 session 結束決定保留。跨 basket 笛卡兒積排除 self-edge，同一方向每 session 一次，反向另計。

S 直接讀原 C1，`support.csv` 原 bytes 複製；主要 fit 不重估 S，獨立 oracle 才另算 S 核等。singleton／無轉移商品不消失；`D_ij≤C_ij≤min(S_i,S_j)`、邊量守恆及總量界皆驗收。完整歷史重用凍結 C1 prefix join，與原 C1 query 的歷史完全相同。

候選仍為 first_view < query 的完整因果目錄，不刪已看或無 D 邊商品。精確有理分數後以原 P0 次數與數值 ID 解同分；缺 D 邊不會把正 P0 次數歸零。完整零分補集補足前 10 名，無正證據則完全回退 P0；沒有 top-L／抽樣／截斷。

## 手算與獨立合成驗收

整合玩具案例第一筆 H={1}、target={2,999}，999 當下不可達但留在完整分母。D1 前三名為 `[3,1,2]`，商品 2 位於第三名，DCG=`1/log2(4)=1/2`，Recall=`1/2`，NDCG=`(1/2)/(1+1/log2(3))≈0.3065735963827292`。同一玩具 C1 前三名 `[2,3,1]`；三臂原控制值逐筆保留。這不是實際 Retailrocket D1 成績。

Bootstrap 手算：訪客 1 的兩筆差值為 1、1，訪客 2 一筆為 −1，query-macro 平均差是 1/3；兩訪客有放回抽樣的查詢分母為 2／3／4，結果為 −1／1/3／1。不能改成訪客等權平均。新 D1−C1 的 2,000 次 draw SHA、RNG 前後狀態與查詢分母須逐次對上原 C1 draw，但 delta 與區間新算、另存；D1−P0 沒有第二組推論區間。

合成涵蓋方向／反向、session 重複、同時多商品／零對角、跨界／index 缺口／截止線、singleton、未知 seed、incoming-only 候選、P0 正次數保留、精確同分與完整補位、空目錄、三臂缺／多／重複／順序、完整 target 分母、複製控制浮點值、所有切片及損壞反例。另有 24 組固定合成 session×各 6 個查詢，比對逐候選完整排序。

兩組正式合成 case 各 5 queries，以 full-catalog 與 exact sparse-complement oracle 分別反讀全部巢狀值與 2,000 次 bootstrap。Oracle 不匯入新 D1 核心／adapter／bootstrap，另以 SQL 原 index 相鄰 join、`DISTINCT(session,i,j)` 與原資料重建；指標沿用已凍結的獨立 Decimal／Fraction oracle。計數、ID、歷史、有理數及順序精確相等；指標絕對／相對容差 1e-12。原控制 binary64 保留，不能拿 oracle 重新計算的近似值覆寫。

## train-only 成本盤點與限制

準備程序在合成全部通過後才解析真實 train basket 商品；其他角色只按 metadata 篩選，**不解碼 validation／test 商品或 target**。第一遍以串流的單 session 暫時集合記錄原始發射、去重邊量及峰值；第二遍以獨立 CSV／SQL 相鄰連接逐 session 對帳。SQLite 保存原 train basket／membership 與每 session 純量成本，沒有跨 session 的 D_ij 聚合表，也沒有建立新的 S 模型。

原始工作量是 `Σadj(|A|×|B|−|A∩B|)`，去重邊量是 `Σsession|E_s|`，兩者差額為重複發射。成本與後續 fit 須逐項核對 train population、相鄰量、原始發射、去重邊量；欄名對應寫在入口。分布、峰值、逐筆 ledger、SQL 與成本 JSON 全部保存在 `shop-mysql-runtime/verification/retailrocket-directed-implementation-v1/train_cost/`，公開收據保存實測聚合。

本輪成本不包含真實全域 unique D 邊數、D1 模型 RSS、validation 歷史／鄰居工作量或整輪時間，不能用它保證 6 小時內完成。全域邊數與計數界也不是原始發射量或速度界。

| 後續單次 D1 fit＋validation＋完整獨立驗收 | 固定限制 |
| --- | --- |
| 程序 RSS／執行目錄 | 8 GiB／20 GiB |
| 磁碟剩餘／系統可用記憶體下限 | 8 GiB／4 GiB |
| 整輪時間 | 21,600 秒（6 小時） |
| 監控 | 0.5 秒合作式檢查節流；basket／session／query／replicate、每 50,000 邊迴圈或 SQL VM 步及階段前後檢查 |

環境使用專案 `.venv` 的 NumPy 2.5.4／PCG64、seed 42 與既有 psutil 7.2.2，未安裝新套件。排序、載入與其他單次不可中斷運算會在下一個檢查點才偵測超限，這不是 OS 瞬間硬限制。超限或來源／鍵／分母／反讀不符即停止並保存 started／failure／部分檔案，拒絕重播；不能改用抽樣、剪枝、放寬門檻或更換分母。

## 凍結、操作與下一步

本輪正式操作為首次 `--prepare`：測試→兩組合成 oracle→train-only 成本→來源與入口凍結；之後 `--verify` 只核保存 bytes。完整準備重入只驗證，部分準備拒絕覆寫。真實 D1 執行目錄本輪不存在，私有準備在 `shop-mysql-runtime/retailrocket_directed_implementation_v1/`，所有暫存及證據仍在 shop。

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_directed_v1.py --verify
```

下一輪明確執行一次真實開發時，唯一入口如下；**本輪未執行此命令**：

```powershell
.venv\Scripts\python.exe -B scripts\run_retailrocket_directed_v1.py --run-validation
```

入口先驗證全部來源、既有 P0／C1／D1 鎖定狀態，建立 started 後單次 train fit→同 166,897 validation 三臂配對→2,000 次主要 D1−C1 bootstrap→獨立全量核對，再保存公開結果／驗收與 guard。沒有驗收完畢就不能標成功；完整結果重入只核 bytes，部分結果保留並拒絕重試。

**P0／C1 validation 已在 D1 選擇前曝光**，本研究仍是同窗開發比較；有向與相鄰同時改變，不能分別歸因，也不是標準 Markov 機率。原 11,943 筆冷目標查詢的無 train 支援缺口保留；current／target 多商品 56／53、mixed 3 仍低於 1,669 查詢門檻，只能描述。D1 incoming／outgoing 診斷不能改寫共同冷商品分母。train／test 原小組不足、Olist 25、UCI 87／83 及匿名鍵、入庫／修訂／曝光／propensity／庫存與回溯限制、來源非商業條件均保留，不能宣稱轉換、營收、因果或營運改善。

下一步僅為上述一次真實 validation 與完整驗收；P0／C1 不重訓、不重排，預留測試繼續 locked。最終選模／refit／test 必須另外制定規格與驗收、明確執行範圍；不能沿用舊 gate 或因有利區間自動解鎖。每日 10% 提醒不變，Dashboard 暫緩；見[全專案進度](PROJECT_PROGRESS.md)。
