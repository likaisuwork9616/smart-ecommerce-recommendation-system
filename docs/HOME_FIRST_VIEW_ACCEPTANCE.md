# 新訪客首頁熱門瀏覽榜的換榜規則

首頁現在使用原熱門瀏覽榜。首輪正式驗收只比較這張榜與整張首看榜，看每一萬位新訪客能多猜中幾人的首看商品。目前等獨立名冊，九月保留測試繼續封存。

## 固定兩張榜

兩榜都用 2015-08-01 零時（UTC）已排好的十件商品與順序。訓練期從 2015-05-04 零時起，到 08-01 零時前。這次選擇的是現行首頁使用的版本，正式評分期間全程使用同一份快照。

| 角色 | 排序規則 | 版本核對 |
| --- | --- | --- |
| 基準（原熱門瀏覽榜） | 依訓練期去重後的瀏覽事件數，由多到少取十件。 | 線上首頁的 `rankings.browse`。比對封存報告的 `baseline_rank_item_counts_sha256`。 |
| 候選（整張首看榜） | 取訓練期有瀏覽、且未在 5 月 3 日暖身期出現的訪客。每人在最早瀏覽時刻看過的每件不同商品各投一票，依票數取十件。 | 同一份封存報告的 `full_rank_item_votes_sha256`。全十席都採用首看榜順序。 |

同票時依原商品編號的數值由小到大排序。兩榜各須有十件相異商品，並用同一套商品鍵對照目標。評分前依版本 `6ec81d7` 的聚合報告核對 `months["2015-08"]` 下的兩個完整 SHA-256，正式收據記錄兩個指紋。七月產榜與只換第十名的結果只作開發比較。[凍結版本](https://github.com/likaisuwork9616/smart-ecommerce-recommendation-system/commit/6ec81d7485abf4cf4bc6480620e6bebaf6932073) · [兩榜指紋](../reports/mainline/recommendation_home_first_view_single_slot_20261124.json) · [公開首頁榜單](recommendation-demo/popularity.json)

## 獨立名冊到位後怎麼驗

1. **先定範圍。** 在查看命中前，記錄已授權的名冊版本、來源、完整 UTC 起訖（含起點、不含終點）與檔案指紋。評分窗須晚於產榜，與已用的訓練、七八月開發及九月保留資料分開。使用整個事前指定的窗口一次判定，不依中途結果增減訪客或改榜。
2. **確認新訪客資格。** 以穩定的匿名訪客鍵，核對窗前是否有任何瀏覽、加購或購買。可用完整的已授權歷史，或來源可核對的窗前出現標記。只收窗內首次出現且有瀏覽的訪客。分開記錄曾出現者與新訪客中無瀏覽者的人數。若歷史有缺口、須開啟封存資料才能補足，就保留待驗。
3. **每人固定一組目標。** 名冊一人一列，含匿名鍵、首次瀏覽 UTC 時刻及該毫秒看過的全部不同商品。即使之前先加購、窗內稍後才瀏覽，仍以最早瀏覽時刻為準。新商品或沒上榜的商品照樣計入。核對唯一鍵、時間、商品鍵與人數，記錄名冊指紋，兩榜共用同一份名冊。
4. **產生成對結果。** 對每人各算一次，首次瀏覽的商品只要有一件進入該榜前十就算命中。同時命中多席，只記最前名次。保存逐人的匿名鍵、兩榜最佳名次（未命中記空）供核對，公開報告只列彙總與指紋。[既有首看成對計分實作](../scripts/evaluate_august_home_first_view_pair.py)

| 同一位訪客的結果 | 記號 | 對淨增人數的貢獻 |
| --- | --- | ---: |
| 兩榜都命中 | B | 0 |
| 只有候選命中 | G（新增） | +1 |
| 只有基準命中 | L（失去） | −1 |
| 兩榜都沒命中 | M | 0 |

完整分母為 **N = B + G + L + M**。報告列出基準命中 **B + L** 人、候選命中 **B + G** 人，以及各自除以 N 的命中率。**淨增 = G − L = 候選命中 − 基準命中**。命中率差為 **100 × (G − L) / N** 個百分點。保留兩榜皆未命中者，區間也使用同一分母。

## 何時才換榜

| 項目 | 首輪事前固定的判定 |
| --- | --- |
| 最低實際改善 | 命中率差至少 **+0.020 個百分點**，相當於每 10,000 人淨多命中 2 人。用整數判定 `5,000 × (G − L) ≥ N`，邊界含等號。 |
| 改善的可信程度 | 訪客成對命中率差的雙側 **95% 區間下限嚴格大於 0**。以未四捨五入的下限判定，下限剛好等於 0 仍沿用原榜。 |

區間沿用專案的訪客成對重抽樣方式。先按匿名訪客鍵排序，為每人記下（1 人，命中差 +1、−1 或 0）。每次有放回抽 N 人，同一抽樣索引套用到兩榜。重算淨增除以 N，重複 2,000 次，使用 NumPy PCG64、種子 20261120。取 2.5 與 97.5 的線性百分位，再乘 100 換成百分點。[區間函式 `visitor_interval`](../scripts/score_recommendation_acceptance.py) · [抽樣設定](../reports/mainline/recommendation_default_freeze_20261120.json)

名冊和兩榜核對通過後，**兩項門檻都達到，新訪客首頁才採用整張首看榜**。例如 100,000 位新訪客至少需淨增 20 人，還要通過區間門檻。任一門檻未達就沿用原榜。缺少獨立名冊、N 為零或核對失敗則記「待驗」。正式報告另列各週增減、各品項占新增的人數與比例，以候選最佳命中名次歸因，每人只算一次。這些明細用來解讀單一商品的影響，兩項換榜門檻事前固定。

七月與八月的整張首看榜比原榜分別淨增 100 人（+0.028 個百分點）與 117 人（+0.041 個百分點）。本輪選擇每萬人至少多 2 人，作為值得替換整張首頁榜單的最低改善幅度。上述兩月都屬已看過的開發資料，正式判定只用新名冊。實際首頁點擊率仍需曝光與點擊紀錄衡量。[七月開發報告](../reports/mainline/recommendation_july_home_first_view_pair_20261124.json) · [八月開發報告](../reports/mainline/recommendation_august_home_first_view_pair_20261124.json)

<a id="run-home-score"></a>

## 重現八月與門檻測試

在專案根目錄執行以下命令。第一行使用本機凍結的訓練及八月開發資料，從訪客首看目標重算兩榜，再比對公開報告。第二行只用合成資料測試成對計分與門檻。

```powershell
.\.venv\Scripts\python.exe -B -m scripts.verify_home_first_view_acceptance_august --check
.\.venv\Scripts\python.exe -B -m unittest tests.test_score_home_first_view_acceptance
```

八月同一批 287,437 位新訪客中，兩榜皆中 1,233 人，僅首看榜命中 361 人，僅原榜命中 244 人，兩榜皆未中 285,599 人。原榜合計命中 1,477 人，候選命中 1,594 人。淨增 117 人，高於本次分母所需的 58 人。命中率差為 **+0.04070 個百分點**，成對 95% 區間為 **+0.02366 至 +0.05775 個百分點**。兩道門檻在八月開發資料均通過。[八月完整報告](../reports/mainline/recommendation_home_first_view_acceptance_august_20261124.json)

合成名冊也走同一個計分與重抽樣函式。下表的淨增全部來自候選獨中，其餘訪客兩榜都沒中。

| 合成訪客 | 淨增 | 命中率差（百分點） | 95% 下限（百分點） | 數值門檻結果 |
| ---: | ---: | ---: | ---: | --- |
| 25,000 | +5 | +0.020000 | +0.004000 | 實際改善剛好達標，區間下限大於零，兩項通過。 |
| 25,001 | +5 | 約 +0.0199992 | 約 +0.00399984 | 多一位未命中的訪客，實際改善已低於門檻。 |
| 5,000 | +1 | +0.020000 | 0 | 實際改善達標，區間下限等於零，第二項未通過。 |

<a id="score-independent-roster"></a>

## 獨立名冊的計分入口

取得獨立名冊後，在本機 Git 忽略的目錄準備以下兩個檔案。來源需先確認資料版本、評分用途、時間窗與新訪客資格。計分程式會從本機事件庫的暖身與訓練時段重建兩榜，並核對固定指紋。正式訪客與目標來自另行授權的獨立名冊。

| 檔案 | 必要內容 |
| --- | --- |
| `manifest.json` | `schema` 為 `home_first_view_acceptance_v1`，`role` 為 `independent`。填 `source_version`、`approval_ref`、`history_evidence`（可回查的窗前任一行為證明）及 `window_utc_ms`（起訖 UTC 毫秒）。填入整數 `active_visitors`、`previously_seen`、`new_without_view`、`scored_visitors`，後三者加總須等於第一項。`roster` 包含同目錄 JSONL 的 `file` 檔名與十六進位 `sha256`。 |
| 名冊 JSONL | 每人一列，含唯一的匿名字串 `visitor`、`seen_before_window: false`、整數 `first_view_ms`，以及 `targets`。目標為同一毫秒的所有相異商品鍵，以無前導零的十進位字串列出，至少一件，沿用兩榜的商品編碼。 |

在已取得授權的專案環境執行下列命令。`--rank-audit` 會保存每位訪客的匿名鍵、首看時刻與兩榜最佳命中名次，路徑使用私有目錄中的新檔名。標準輸出是聚合結果。收據中的名冊與 manifest 指紋可用來回查當次資料版本及授權依據。名冊為零人時，區間與採用判定為空值，維持待驗。[計分程式](../scripts/score_home_first_view_acceptance.py)

```powershell
$packet = Read-Host '輸入已授權獨立名冊的 manifest.json 路徑'
$rosterApproval = Read-Host '輸入該份名冊的授權紀錄識別碼'
$runDir = '.runtime/verification/home-first-view-' + [guid]::NewGuid().ToString('N')
New-Item -ItemType Directory -Path $runDir -ErrorAction Stop | Out-Null
$scoreReceipt = & .\.venv\Scripts\python.exe -B -m scripts.score_home_first_view_acceptance --manifest $packet --approval-ref $rosterApproval --rank-audit "$runDir/ranks.jsonl"
if ($LASTEXITCODE -ne 0) { throw '首頁名冊未通過核對，請查看計分訊息' }
$scoreReceipt | Set-Content -Encoding utf8 "$runDir/result.json"
```
