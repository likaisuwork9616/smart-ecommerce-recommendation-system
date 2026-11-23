# 預設推薦版本與驗收清單

2026-11-20 凍結瀏覽、加購、購買的候選與主要基準。固定版本為 Git commit `cf975e5593e6e82b5169f991e5b20b9086ff26d4`。本頁的[機器可讀清單](../reports/mainline/recommendation_default_freeze_20261120.json)列出程式和公開報告的 Git 物件 ID，以及本機資料的大小、SHA-256 與八月名冊指紋。[驗收門檻](RECOMMENDATION_DEFAULT_ACCEPTANCE.md)

第一輪正式比較沿用 2015-05-04 至 2015-08-01 前的固定訓練版本。以下重現使用 2015-08-01 至 2015-09-01 前的開發名冊，時間一律為 UTC、起點含而終點不含。2026-11-20 的版本清單由既有八月證據核對；九月保留測試繼續封存。

## 固定版本、程式與報告

| 場景 | 候選與主要基準 | 凍結的程式入口 | 八月證據 |
| --- | --- | --- | --- |
| 瀏覽 | **K1 v1** 以精確 Jaccard 排序，選最多 500 段符合資格的歷史瀏覽，依既有 P0 規則處理平手與補位。**C1 v1 留一席**保留原共現榜前九名。最新合格瀏覽商品未上榜才換第十名，同時點按商品編號升序。 | K1 訓練和排名在 [retailrocket_session_knn.py](../scripts/retailrocket_session_knn.py)，完整八月核對走 [run_k1_august_readback_v1.py](../scripts/run_k1_august_readback_v1.py) 和 [summarize_k1_august_readback_v1.py](../scripts/summarize_k1_august_readback_v1.py)。C1 用 [retailrocket_cooccurrence.py](../scripts/retailrocket_cooccurrence.py)，留一席用 [evaluate_recency_slot.py](../scripts/evaluate_recency_slot.py)。 | [K1](../reports/stage12/k1_august_readback_20261119.json) · [C1 留一席](../reports/stage10/recency_slot_validation_201508.json) · [第 1 名](../reports/stage12/retailrocket_browse_rank_one_201508.json) |
| 加購 | **共同加購優先，熱門加購補滿十席**。基準 **只補空榜**。同一購物階段內的配對要有至少兩位不同訪客支持，熱門榜按訓練期加購事件數。 | [evaluate_cart_recommendations.py](../scripts/evaluate_cart_recommendations.py) 建原榜，[verify_cart_validation.py](../scripts/verify_cart_validation.py) 重建查詢與原榜，[evaluate_cart_popular_fill.py](../scripts/evaluate_cart_popular_fill.py) 的 `popular_fill` 和 `empty_fallback` 重現兩種規則。 | [原兩榜與查詢收據](../reports/stage13/retailrocket_cart_next_add_201508.json) · [補位與基準](../reports/stage13/retailrocket_cart_popular_fill_201508.json) |
| 購買 | **共同購買優先，熱門購買補滿十席**。基準 **只補空榜**。按匿名訪客鍵和交易鍵分組，每筆交易內同商品只計一次。配對要有至少兩位不同訪客支持，熱門榜按含該商品的交易數。 | [evaluate_purchase_baskets.py](../scripts/evaluate_purchase_baskets.py) 建交易群組、原榜與名冊，[evaluate_purchase_popular_fill.py](../scripts/evaluate_purchase_popular_fill.py) 以共同購買來源跑相同補位規則。 | [原兩榜與查詢收據](../reports/stage13/retailrocket_purchase_basket_201508.json) · [補位與基準](../reports/stage13/retailrocket_purchase_popular_fill_201508.json) |

加購與購買的補滿都先保留共同項目的原名次，再依各自的熱門榜順序跳過重複項，補到十件。只補空榜在有共同項目時，原樣保留短榜。兩者均排除起點商品，分數同分時按商品編號數值升序。[瀏覽時間與商品資格契約](contracts/retailrocket_recommendation_v1.json) · [K1 固定規則](contracts/retailrocket_session_knn_paired_v1.json)

## 固定的八月名冊與訓練資料

| 場景 | 覆蓋率／命中分母 | 每一列如何識別 | 資料從哪裡來 |
| --- | ---: | --- | --- |
| 瀏覽 | 166,897／166,897 | 訪客鍵、該次瀏覽開始毫秒、查詢毫秒。目標為同次瀏覽下一個時點的去重商品。 | K1 與 C1 封存的 `queries.jsonl` 同名冊。K1 的完整路徑是 `shop-mysql-runtime/retailrocket_session_knn_paired_v1/queries.jsonl`，C1 位於 `shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/`。留一席重現另讀該目錄的 `oracle.sqlite`。 |
| 加購 | 14,725／4,266 | 訪客鍵、加購毫秒、起點商品。超過 30 分鐘無瀏覽或加購才切開購物階段。只用同階段下一個嚴格較晚的加購時點。 | `shop-mysql-runtime/retailrocket_dataset_v1/builder.sqlite`。全部加購機會計覆蓋。下一個時點只重加起點或沒有下一個時點的查詢只計覆蓋。名冊由程式重建並與公開指紋比對。 |
| 購買 | 4,613／1,477 | 訪客鍵、交易鍵、起點商品。目標為同交易群組內其他不同商品。 | 同一份 `builder.sqlite`。單件交易計覆蓋，其餘可評分。名冊由程式重建並與公開指紋比對。 |

瀏覽用 Stage 8 的 `baskets.csv`、`queries.csv` 與 `catalog.csv` 做名冊和時間核對，K1 的訓練身分和已保存的 sessions、postings 由清單及原 [Stage 12 入口收據](../reports/stage12/retailrocket_session_knn_v1_validation_entry_specification.json)鎖定。C1 的訓練支持度和 P0 訓練熱門次數也有獨立綁定。購買與加購依固定訓練窗從同一個來源資料庫重建模型。知悉查詢的目標商品仍可能沒有訓練支持，這些可評分查詢都留在分母。

本機資料由已驗收保存包還原到上表路徑。GitHub 保存程式、聚合報告和校驗值。以下使用 PowerShell 7，從含既有 `.venv` 與私有資料的專案根目錄執行。若工作目錄的程式已變更，先用獨立工作目錄取出凍結 commit，再按原路徑安裝環境及還原授權資料。

## 先驗版本，再重現八月

- [ ] 查核凍結 commit、程式與報告，並核對私有資料的大小和 SHA-256。完整 K1 原始驗算另沿用 Stage 12 入口的相依來源檢查。
- [ ] 先在八月重現報告，檢查名冊指紋、覆蓋與可評分分母、命中數、首次命中和數值門檻。
- [ ] 將輸出留在全新的 Git 忽略目錄，保存命令、實際 Python／SQLite／NumPy 版本與退出碼。

```powershell
$freeze = Get-Content -Raw 'reports/mainline/recommendation_default_freeze_20261120.json' | ConvertFrom-Json
git cat-file -e "$($freeze.frozen_git_commit)^{commit}"
if ($LASTEXITCODE -ne 0) { throw '找不到凍結 commit' }

$tracked = @($freeze.shared_tracked)
foreach ($scenario in $freeze.scenarios.PSObject.Properties) { $tracked += @($scenario.Value.tracked) }
foreach ($item in ($tracked | Sort-Object path -Unique)) {
    $actual = git hash-object -- $item.path
    if ($LASTEXITCODE -ne 0 -or $actual -ne $item.git_blob) { throw "版本不符 $($item.path)" }
}
$private = @($freeze.shared_private_database) + @($freeze.scenarios.browse.private_inputs)
foreach ($item in $private) {
    $file = Get-Item -LiteralPath $item.path -ErrorAction Stop
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    if ($file.Length -ne $item.bytes -or $hash -ine $item.sha256) { throw "資料校驗不符 $($item.path)" }
}
```

本輪已查核 33 份 Git 版本綁定及 14 份本機資料綁定。

這是八月的可執行入口。瀏覽快速重現可先用上次已完成的 K1 驗算目錄重讀收據。要從本機保存包重新執行完整獨立驗算，依[K1 七階段命令](STAGE12_K1_AUGUST_READBACK_20261119.md#在本機重現)建立新的私有目錄，再把下列 `$k1Archive` 指到新目錄。

```powershell
$run = '.runtime/verification/default-acceptance-' + [guid]::NewGuid().ToString('N')
New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null
$python = '.\.venv\Scripts\python.exe'
$k1Archive = 'shop-mysql-runtime/verification/k1-august-readback-20261119/run-01'

& $python -B -m scripts.summarize_k1_august_readback_v1 --out $k1Archive --report "$run/browse-k1.json"
if ($LASTEXITCODE -ne 0) { throw 'K1 收據核對失敗' }
& $python -B -m scripts.read_august_browse_rank_one | Set-Content -Encoding utf8NoBOM "$run/browse-rank-one.json"
if ($LASTEXITCODE -ne 0) { throw '瀏覽首位重讀失敗' }
& $python -B -m scripts.evaluate_recency_slot | Set-Content -Encoding utf8NoBOM "$run/browse-recency.json"
if ($LASTEXITCODE -ne 0) { throw 'C1 留一席重現失敗' }
& $python -B -m scripts.evaluate_cart_popular_fill --report "$run/cart-fill.json"
if ($LASTEXITCODE -ne 0) { throw '加購補位重現失敗' }
& $python -B -m scripts.evaluate_purchase_popular_fill --report "$run/purchase-fill.json"
if ($LASTEXITCODE -ne 0) { throw '購買補位重現失敗' }
```

本輪從已完成的 K1 驗算目錄重算摘要，五份八月輸出皆與公開報告相同。若重跑完整 K1 七階段，按下列比較固定設定、訓練、名冊與指標，執行時間和資源另留在當次報告。

```powershell
@'
import json
from pathlib import Path
import sys

run = Path(sys.argv[1])
references = {
    "browse-k1.json": "reports/stage12/k1_august_readback_20261119.json",
    "browse-rank-one.json": "reports/stage12/retailrocket_browse_rank_one_201508.json",
    "browse-recency.json": "reports/stage10/recency_slot_validation_201508.json",
    "cart-fill.json": "reports/stage13/retailrocket_cart_popular_fill_201508.json",
    "purchase-fill.json": "reports/stage13/retailrocket_purchase_popular_fill_201508.json",
}
for filename, reference in references.items():
    actual = json.loads((run / filename).read_bytes())
    expected = json.loads(Path(reference).read_bytes())
    if filename == "browse-k1.json":
        keys = ("status", "scope", "source_evidence", "cohort", "training", "results")
        actual, expected = ([report[key] for key in keys] for report in (actual, expected))
    if actual != expected:
        raise SystemExit(f"August evidence mismatch: {filename}")
    print(f"Verified {filename}")
'@ | & $python -B - $run
if ($LASTEXITCODE -ne 0) { throw '八月證據比對失敗' }
```

## 正式驗收的執行順序

成對計分入口已可讀取已整理的名冊與兩榜，並以合成資料及八月結果核對。正式執行前仍須取得另一份獲准的名冊，接上該來源的排名與查詢產生流程，核對資料和訓練來源後才出分。[計分入口與核對命令](#paired-scorer)

若選擇已封存的九月窗口，正式規格須先處理與既有 P0 最終重擬合、測試角色和使用紀錄關卡的關係，再取得明確執行授權。這份清單固定的是原訓練窗的模型。若既有關卡要求重擬合，需另存模型版本、校驗值及比較規格，再進行首筆評分。[既有預留測試關卡](STAGE10_RETAILROCKET_C1_P0_RESEARCH_HANDOFF_V1.md#預留測試維持鎖定)

1. **先核准名冊。** 取得要驗的場景、來源授權、UTC 窗、來源版本及校驗值。按上表規則及同一時間窗重建鍵、候選資格與目標，鎖定覆蓋名冊和可評分名冊的完整順序、筆數及指紋。只有覆蓋、沒有可評分目標的查詢將目標記為未知，避免被算成未命中。瀏覽沿用事前商品目錄、同階段目標與成熟邊界。加購照既有切段，購買按交易鍵組成目標集合。
2. **用固定訓練版本產生兩榜。** 只取訓練窗口的支持度、模型、熱門次數。每場景建立成對帳本，每列保留查詢鍵、匿名訪客鍵、是否可評分、完整目標集合、候選排序、基準排序及逐席來源。核對兩臂逐筆鍵與目標一致，缺列、重複鍵、跨窗目標或商品資格不符時停止核對並記錄差異。
3. **重算門檻。** 覆蓋分母包含全部固定查詢，先報至少一件和列滿十件的比例，再在可評分名冊上算 Hit@10、第 1 名命中率與 MRR@10。候選須列滿 100% 十席，首位命中率不得低於基準，並達各場景命中率與 MRR@10 的最低增益。以同一查詢對照兩臂，報新增、失去及首次命中移動，補位席位按來源另報。判定使用未四捨五入的比例。
4. **重算成對區間。** 從可評分名冊取訪客鍵，按數值升序。每一訪客先彙總可評分筆數 `n_v` 和候選減基準的命中數 `d_v`。用清單指定的 NumPy PCG64 和種子 20261120，有放回地抽取可評分名冊的訪客數，做 2,000 組。每組用抽到的訪客權重 `w_v` 計算 `sum(w_v*d_v)/sum(w_v*n_v)`，取線性插值的 2.5 和 97.5 百分位。下限須大於 0。可評分名冊為空時，記錄原因並維持待驗。
5. **保存證據後決定採用。** 保存凍結 commit、正式入口版本、資料批准與指紋、兩個分母、成對數值與逐項判定。原始查詢帳本留在私有目錄，公開報告用彙總值和校驗值。全部門檻通過才進入預設切換決策，缺資料或門檻未過時維持已驗收的展示方式。

八月先驗門檻的比較順序與公式見[預設推薦採用門檻](RECOMMENDATION_DEFAULT_ACCEPTANCE.md)。

<a id="paired-scorer"></a>

## 成對計分入口

用以下命令重現合成情境與八月成對結果。八月入口只使用已封存的瀏覽開發榜單，以及 SQLite 的訓練和八月查詢。它會核對已發布的名冊指紋、兩榜分母、命中和首次命中，再計算新基準的訪客抽樣區間。

合成檢查共 13 項，全數通過。八月的三組比較各完成 2,000 次訪客抽樣，涵蓋 62,235 位瀏覽、1,334 位加購、383 位購買可評分訪客。報告保存逐項門檻、兩榜首次命中分布與每席來源的彙總，角色為八月開發驗證。[實際成對報告](../reports/mainline/recommendation_default_paired_august_20261123.json)

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -B -m unittest tests.test_score_recommendation_acceptance
if ($LASTEXITCODE -ne 0) { throw '合成驗證失敗' }
$run = '.runtime/verification/default-paired-' + [guid]::NewGuid().ToString('N')
New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null
& $python -B -m scripts.verify_recommendation_acceptance_august | Set-Content -Encoding utf8NoBOM "$run/august.json"
if ($LASTEXITCODE -ne 0) { throw '八月成對計分核對失敗' }
```

收到正式資料後，由來源負責方或具資料使用權的人確認場景、資料版本、UTC 窗及評分用途，並保存可追溯的同意紀錄。從已核准的來源產生以下檔案，留在同一個 Git 忽略目錄。名冊在產生兩榜前固定。瀏覽、加購、購買各用一份清單，識別碼為非負整數。

| 檔案 | 必備內容 |
| --- | --- |
| 清單 `manifest.json` | `schema` 為 `recommendation_default_pairs_v1`，`role` 為 `retained`，`scenario` 為 `browse`、`cart` 或 `purchase`。記錄 `source_version`、`approval_ref`、`window_utc_ms`（起訖兩個毫秒，左含右不含）、`frozen_training_commit`、`coverage_queries` 和 `scorable_queries`。 `roster`、`rankings`、`catalog` 各填 `{"file":"檔名.jsonl","sha256":"檔案 SHA-256"}`。 |
| 覆蓋名冊 JSONL | 每行一個物件，含上表所定的三欄 `key`、`query_ms`、`through_ms` 與 `targets`。瀏覽與加購的 `through_ms` 為用來定義目標的下一時點，缺下一時點的加購可沿用當前時間。購買用該交易群組的最早與最晚毫秒。 `targets` 是去重後的非空商品陣列，無法評分時用 `null`。 |
| 兩榜 JSONL | 每行依名冊原順序提供同一 `key` 和 `candidate`、`baseline`。榜單是依名次排列的 `[商品 ID, 來源]` 陣列，空榜用 `[]`。瀏覽來源為 `knn`、`cooccurrence`、`recency` 或 `popular`，加購用 `coadd` 或 `popular`，購買用 `cobuy` 或 `popular`。 |
| 資格目錄 JSONL | 每行為 `[商品 ID, 首次具資格的 UTC 毫秒]`。瀏覽用嚴格早於查詢的首次瀏覽時間。加購與購買只收錄固定訓練窗內有對應行為的商品。 |

執行前核對資料同意紀錄與名冊版本，保存取數規則、兩榜的訓練指紋，以及計分入口 commit。工具核對清單、窗界、列鍵、共同目標、商品資格與檔案 SHA-256。來源授權、交易完整性和兩榜確實由固定模型產生，需以取數與產榜收據查證。此入口拒絕用已封存的九月窗口評分。

```powershell
$packet = Read-Host '輸入已核准名冊的 manifest.json 路徑'
$approvalRef = Read-Host '輸入該名冊的授權紀錄識別碼'
$formal = '.runtime/verification/default-retained-' + [guid]::NewGuid().ToString('N')
New-Item -ItemType Directory -Path $formal -ErrorAction Stop | Out-Null
& .\.venv\Scripts\python.exe -B -m scripts.score_recommendation_acceptance --manifest $packet --approval-ref $approvalRef |
    Set-Content -Encoding utf8NoBOM "$formal/result.json"
if ($LASTEXITCODE -ne 0) { throw '正式名冊計分失敗' }
```
