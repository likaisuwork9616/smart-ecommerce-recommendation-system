# Stage 6：RFM資料集凍結規格

**資料集契約已凍結；builder、個體RFM資料集與分群尚未實作。** 本輪將[前輪輸入盤點](STAGE6_RFM_FEASIBILITY.md)的候選選項定為可驗收的離線快照研究契約，先寫[機器規格](../reports/stage6/rfm_dataset_specification.json)，再做[聚合支援查核](../reports/stage6/rfm_dataset_contract_audit.json)。沒有訓練、預測、讀評論／模型分數或Dashboard；Stage 4、5維持待資料。

本規格不是原營運as-of、完整顧客生命週期或淨消費驗收。來源、最終狀態及金額仍是後來取得的快照，缺原入庫／修訂、退款／結算、日結與完整性證據。固定S／T不會解除這些限制。

## 固定範圍與顧客母體

| 項目 | 凍結規則 |
| --- | --- |
| 顧客鍵 | orders.customer_id連唯一customers.customer_id，再以非空customer_unique_id彙總；匿名鍵只代表來源識別，不宣稱自然人／家庭 |
| 歷史範圍 | 來源可見歷史中purchase<T的訂單；下界是最早可見來源，不假造完整終身歷史 |
| 顧客母體 | T前至少一筆「歷史事件合格完成訂單」的customer_unique_id；不依商品／付款完整性刪顧客，也不直接納入全customers表或只留窗口活躍者 |
| S | 2017-09-01 00:00:00 inclusive |
| T | 2018-09-01 00:00:00 exclusive；同為觀察事件截止，不用電腦日期或最大事件＋一天替代 |
| RFM窗口 | 購買區間`[S,T)`，365 elapsed days；R、F、M共用同一窗口事件合格訂單集合 |
| 時鐘 | 嚴格來源naive秒級timestamp；不自行指定UTC、業務時區或DST |
| 全量身分守門 | 主鍵缺失／重複、無法定位購買時間或T前身分映射缺失即停止完整母體驗收，不縮名冊、補購買／核准時鐘或重建guard繞過 |

選擇歷史買家母體是為了保留窗口零活動顧客；全customers表會帶入T後才出現的顧客，只留窗口買家則會排除零活動者。這是來源可見的歷史完成交易母體，不代表所有註冊者、所有下單者或全體CRM客戶。

## 訂單資格與59張時鐘異常

歷史事件合格訂單須：購買<T、快照最終status=delivered、購買與送達可定位、`purchase≤delivery<T`、可連非空顧客鍵；核准可解析時另要求`purchase≤approval≤delivery`。窗口資格再加`purchase≥S`。

核准不是必要事件欄。缺／無效核准保留`approval_missing_or_invalid`旗標，不以購買時間補值；已知時鐘矛盾則隔離。付款／明細缺失屬金額與對帳品質，不回頭刪事件合格訂單或顧客。

| 狀況 | 處理 |
| --- | --- |
| 核准早於購買或晚於送達 | 按比較規則隔離；套用全部歷史，不以硬編碼59或固定ID清單作分支 |
| 缺／無效送達、送達早於購買 | 隔離；購買在窗口且快照delivered時記window_quarantine |
| 送達≥T | 屬T前尚未完成，不算品質隔離；不能因現在已delivered就納入過去窗口 |
| 最終status非delivered | 不屬本研究完成交易；逐項保留排除原因，不反推當時取消／結案時點 |
| 只存在隔離單的顧客 | 不符合歷史母體資格，但隔離單仍留逐單決策／排除對帳，不悄悄當作沒有來源 |
| 同顧客另有合格單 | 保留母體與合格子集；窗口若另有隔離單，標記不完整並遮罩M，不能直接列完整RFM可用 |

逐單主排除原因採互斥優先序：非delivered→缺／無效送達→送達早於購買→送達≥T→核准時鐘矛盾→eligible。購買≥T只列來源排除彙總，不進T前逐單決策或顧客名冊；購買無法定位則停止。

前輪74,147單包含59張送達早於核准的窗口單；新資格隔離後為74,088單。全歷史同規則隔離61單，不能將「只排59」當歷史規則。另有59張送達≥T與7張缺送達，它們是不同的排除原因，不能混成同一組。

## R、F、M與未知／零活動

| 欄位 | 凍結定義 |
| --- | --- |
| R | 僅窗口內最近合格購買的recency。`recency_seconds=T−last_window_purchase_at`，先取整數秒，再除86,400得到elapsed days；不floor、round或改算日曆日 |
| R邊界 | 有合格窗口單時`0<R≤365`；無合格窗口單時最近購買、秒數與天數均null，不填0、∞或窗口外最近購買 |
| F | 窗口事件合格集合的distinct order_id；不因缺商品金額刪單，不計明細／付款列數或分期數 |
| M | 同一訂單集合的全部item.price整數分合計，名為商品快照毛額；沿既有BRL名目單位，不當淨營收、淨實收或利潤 |
| M未知 | 任一合格窗口單缺明細、鍵重複、商品金額非法／負值／溢位，或顧客另有window_quarantine，M必為null；不能只加合法部分、補0或以付款回填 |
| 運費／付款 | 各自先按order聚合，獨立對帳；不混入主M，不乘payment_installments，不因付款不等商品＋運費而強迫改金額 |
| 計數範圍 | 核准、商品、付款、運費缺／非法計數只對window_event_eligible訂單；window_quarantine另對潛在窗口delivered單計數，不混分母 |
| 數值安全 | 商品／運費／付款先Decimal轉整數分；未來builder須checked int64加總，非法不可改浮點或靜默捨入。本輪以全來源已知非負金額總和≤int64上限作保守支援前提，保證任意子集加減安全，超過即停止支援查核 |

R、F可以保留為**合格子集**的已知描述，但不完整時M仍遮罩，`rfm_usable=false`。這避免隔離單或未知金額被誤解成沒有交易／零消費；它也不把缺金額變成資格排除。

| activity_state | 條件 | R／F／M與旗標 |
| --- | --- | --- |
| active_complete | 有合格窗口單、無商品未知、無窗口隔離 | R有效、F>0、M為整數分；monetary_complete=true，rfm_usable=true |
| active_money_unknown | 有合格窗口單且至少一單商品未知 | R／F保留合格子集，M=null；兩旗標false；商品未知優先於隔離狀態 |
| active_with_quarantine | 有合格窗口單、商品可解析，但另有窗口隔離 | R／F保留合格子集，M=null；兩旗標false |
| inactive_complete | 有合格歷史、無合格窗口單、無窗口隔離 | R=null、F=0、M=0；monetary_complete=true，rfm_usable=false，仍保留顧客 |
| inactive_with_quarantine | 有合格歷史、無合格窗口單，但有窗口隔離 | R=null、F=0只表示零筆合格活動、M=null；兩旗標false，不稱完全無交易 |

缺付款或運費本身不遮罩主商品M，另留可比／缺口；原退款與歷史可得性缺口則是全資料集限制。`rfm_usable`只表示研究契約下的完整活躍列，不代表營運可用，也不授權分群；乾淨零活動因R=null不直接進完整數值RFM分析。

## 預定私有產物與欄位

預定`.runtime/stage6_rfm_dataset_v1/`；本輪沒有建立這個目錄或任何資料集CSV。以下只是已凍結的未來builder輸出契約，不是已交付產物。完整有序型別見[機器規格](../reports/stage6/rfm_dataset_specification.json)。

| 產物 | 固定內容 |
| --- | --- |
| customers.csv（16欄） | customer_unique_id、S、T、activity_state、rfm_usable、monetary_complete、last_window_purchase_at、recency_seconds、recency_days、frequency_orders、monetary_product_cents、window_quarantined_orders、window_price_unknown_orders、window_approval_missing_or_invalid_orders、window_payment_missing_or_invalid_orders、window_freight_missing_or_invalid_orders |
| order_decisions.csv（16欄） | order_id、customer_unique_id、purchase_at、approval_at、delivery_at、in_window、history_event_eligible、window_event_eligible、primary_exclusion_reason、window_quarantine、approval_missing_or_invalid、price_complete、product_cents、freight_cents、payment_cents、payment_difference_cents；保留所有purchase<T來源單，不只合格單 |
| manifest.json | 規格與來源版本、schema／列數、私有bytes／SHA、母體／狀態聚合及反讀驗收；私有digest不公開 |

CSV用UTF-8，布林字面值固定`true`／`false`；timestamp固定`YYYY-MM-DD HH:MM:SS`、naive秒級；整數為十進位無千分位，nullable欄以空cell表示未知，不能文字NA／0替代。recency_days為有限float64、17位有效數字序列化；JSON用嚴格boolean／null／finite值。顧客按unique_id升冪、逐單按order_id升冪，不輸出來源未來顧客列。

未來須先完成整個bundle預檢才寫入，已存在不同bytes即拒覆寫；來源、schema、ID集合、順序、nullable值、金額與CSV反讀都要核對。下列驗收義務已凍結，builder驗證尚待下輪實作：

- 顧客全集精確等於歷史事件合格顧客，不受商品／付款inner join影響；活躍＋零合格活動及五種狀態均對帳回全集。
- 每個T前來源訂單有且只有一個主決策，窗口集合是歷史集合子集；隔離／未完成／非delivered與母體外顧客另對帳，不靜默漏列。
- F對上同一窗口集合的distinct訂單；有單時最近購買與R符合邊界，無單時R相關欄全null，不能借窗口外購買補R。
- 商品未知或窗口隔離必使M=null且不可用；乾淨零活動才M=0。合格商品總額對帳時，完整顧客M與遮罩顧客的已知合格子集分開，不把null當0後硬湊總額。
- 商品、運費與付款分流聚合，缺／非法金額、付款差額與溢位保留；不得用重複展開列數當F或金額。

## 本輪實際支援與驗證

以下取自新[契約聚合查核](../reports/stage6/rfm_dataset_contract_audit.json)，不是builder產物或模型／業務成效。

| 範圍 | 實際結果 |
| --- | --- |
| 歷史資格 | 核准時鐘檢查前96,411單；隔離61單後96,350單／93,234顧客。14單缺／無效核准保留旗標；缺明細0、缺付款1，不依付款刪顧客 |
| 窗口資格 | 前輪74,147單，隔離59單後74,088單／72,125活躍顧客；有歷史但無合格窗口單21,109顧客。93,234＝72,125＋21,109 |
| 商品支援 | 合格窗口單商品未知0；商品總額10,168,011.11、運費1,710,271.30、付款11,880,118.79；433單付款不等商品＋運費，沒有用差額改M |
| 窗口隔離 | 66單＝59張核准矛盾＋7張缺送達；其中1單屬母體內1位仍有合格單顧客，65單在母體外。送達≥T的另59單不當品質隔離 |
| 狀態支援 | active_complete 72,124、active_with_quarantine 1、inactive_complete 21,109；active_money_unknown及inactive_with_quarantine均0。這是狀態聚合，沒有輸出個體RFM；混合顧客未來M須遮罩 |
| 合成測試 | 新23項＋原盤點20項共43項全過、0.012秒；核時間端點、母體、隔離／零活動、未知不刪單、來源變更、整數分溢位前置條件及不輸出個體資料，沒有模型fit |
| 獨立對帳 | 45項歷史／窗口母體、隔離、零活動、商品／付款與狀態聚合比較通過；來源計算與隔離交叉表由獨立程式核對，不與單元測試加總 |
| 文件與保留 | 72份Markdown、1,090個本機檔案連結、113份嚴格JSON與12份來源綁定通過；其餘458份原追蹤檔、35份私有證據bytes不變，原Stage 4／5與Stage 6盤點資產保留 |

母體及狀態支援需在記憶體建立顧客連接與窗口訂單計數作對帳；沒有計算R、彙出個體M、寫顧客名冊或實作builder。商品總額是合格訂單來源加總，不能當成遮罩後顧客M總和或淨營收。

私有驗證收據留`.runtime/stage6_rfm_dataset_validation.json`及`stage6_rfm_dataset_publication_qa.json`；獨立來源／隔離支援分別在同目錄`stage6_rfm_dataset_independent.json`與`stage6_rfm_dataset_quarantine_independent.json`。這些是聚合查核證據，不是已建立的RFM資料集。

## 操作、限制與下一步

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rfm_feasibility tests.test_rfm_dataset_spec -q
.\.venv\Scripts\python.exe scripts\freeze_rfm_dataset_spec.py --specification-only
.\.venv\Scripts\python.exe scripts\freeze_rfm_dataset_spec.py
```

在專案根目錄使用`.venv`；先核原盤點規格／報告及原來源，再凍結12份來源／程式／測試綁定，正式動作只查聚合支援。原始四表及新舊來源在讀取前後核bytes；規則、來源或既有輸出不同即停止，不覆寫、縮母體、改S／T或重建原guard。Git clone不包含原資料、私有收據或未來資料集。

本輪沒有新來源，也沒有解除快照最終狀態、原可得／版本、退款與全量證據缺口；先前交易metadata曝光仍須揭露，沒有未知保留測試或效能宣稱。Stage 4每日10%與11／29／42／73／101五種子不變，Stage 5 H60、角色、兩臂分數與新窗用途均維持待資料。

下一步可依本契約另輪實作訂單級builder、顧客彙總與不涉及訓練的反讀／洩漏測試，再驗收實際資料集；目前不實作builder、不分群、不訓練、不做Dashboard。
