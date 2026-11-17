# V75｜K1 人工完整反讀接入與有限驗收

2026-11-17 使用者確認依[V74規格](STAGE12_KNN_MINIMAL_INTEGRATION_SPEC_V74_20261116.md)準備並封存工具與人工案例，再執行有限合成驗收；額度不足就先暫停。此授權不開放Linux、B／C／D、真實model、原48筆、166,897筆全量或新主要bootstrap。真實全量仍關閉，T_plan仍null，V46暫不採用。

## 第一步：工具與案例程式來源封存

已新增五個工具模組、三個測試模組及必要案例契約。六元件責任分配在人工bundle入口、完整worker／鎖內guard、pipeline／publisher／外部finalizer之間。所有新Python來源完成AST檢查，案例、恢復／發布與停止條件完成獨立靜態複核；尚未執行測試或建立人工資料，靜態複核不能當成行為驗收。

| 項目 | 已準備內容與限制 |
| --- | --- |
| 人工入口 | 固定fixture ID、預先封存SHA、角色與相對路徑白名單；拒絕越界／別名／硬連結與任意N，無真實profile |
| 完整worker | V2全來源流程接V4精確核心；完整129筆原序、64／64／1 chunks、原人工2,000 draws；每attempt清cache，使用同run有效DB／prefix |
| 鎖內完成 | 新CP子類先保留原完整檢查，再核query stage的run／ledger／exact-int N／exact-bool EOF；同時涵蓋candidate、finalize及orphan恢復 |
| 監督與發布 | 真程序正常退出、B4／B5／B6恢復、原證據反核、禁止發布重算排名、所有writer停止後外部封存 |
| 停止與證據 | 同run跨PID累積預算、假時鐘／資源與真程序清理；內層watchdog逾時會傳遞為不得補跑；失敗檔案保留在忽略目錄 |
| 必要案例 | **34個測試方法、196個子案例ID、24個案例族**；正式runner逐一核對封存清單，缺漏／skip／意外失敗不能通過 |

[目前工具封存收據（正式修正版）](../reports/mainline/v75_tool_seal_revision3_20261117.json)保存35個方法／案例描述符、公開Stage8 schemas依賴、V74提案與runtime身分。現有Windows runtime核對為CPython3.12.10、NumPy2.5.4、psutil7.2.2、SQLite3.49.1、little endian，符合V73相容目標；這是身分核對，不是時鐘能力或成本校準。

人工資料規格固定F-small 7 queries／6 visitors、F-long 129／3（70／40／19）、F-edge 1／1及501鄰居；另有499／500／501與精確比率向量。generator只接受新的固定shop-mysql-runtime/v75/fixtures目錄；凍結V1與V2產出golden後才能建立fixture registry，候選不得製作自己的expected。公開只封存描述符與聚合狀態，人工原始檔、DB、程序日誌與故障證據全部留在Git忽略的shop-mysql-runtime/v75。

為避免worker載入舊實驗入口，直接來源盤點採新stdlib AST函式（依V34文字調整），不匯入舊entry取得方法清單。正常H1–H8核對位置另有trace；各程序重新admission的來源核對也屬實際工作，不能把八個位置當成全流程唯一八次讀取，更不能由此推出真實成本。

## 人工資料準備的路徑修正

第一次準備在generator路徑檢查即拒絕，0組人工資料完成、0個正式窗口；錯誤紀錄完整保留。唯讀檢查確認現有`.runtime`是指向`shop-mysql-runtime`的junction，因此新工具改用實際Git忽略目錄`shop-mysql-runtime/v75`，繼續拒絕別名／越界路徑。這是新工具路徑接入修正，未改科學規則、門檻或196個必要子案例。

[準備失敗與修正收據](../reports/mainline/v75_preparation_path_correction_20261117.json)及[初版工具封存](../reports/mainline/v75_tool_seal_20261117.json)均保留；準備修訂2重新封存後才繼續建立fixture。正式驗收尚未開始，沒有消耗正式修正版額度。最多兩個正式窗口的限制不變。

## 執行順序與限制

1. 本步先封存工具、必要案例程式與README並推main。工具收據SHA是後續準備的固定起點。
2. 使用已封存generator建立三組人工資料與凍結V1／V2 golden；保存生成結果及manifest SHA，更新README並封存fixture registry、推main後，才可進正式窗口。
3. 再核對額度及所有封存身分，使用下列正式入口。每版一次、900秒成功截止、子程序最多120秒且受剩餘預算限制；已確認最多初驗及必要的一次新工具／案例實作修正版。整窗或內層意外超時不補跑，來源權威不明不補跑。第二版必須另版封存、完整重驗，不拼接通過項。

```powershell
.venv/Scripts/python.exe -B -m scripts.run_retailrocket_session_knn_acceptance_v75 --revision 2 --method-sha 6aeb842111fa8a7ac570807353dc8b1a9f22b33f7f7e5704708c0f5cc18cf393 --fixture-sha 028f69c5364b3a0a832b4e766dfe10d21a1f4fee03d8ef606f8fafafdf406881
```

fixture registry已建立；上列為唯一修正版的溯源命令，第2窗口已執行並失敗；兩個正式窗口已用完，不可重執行或開第3窗口。runner不會以現場重算hash自行放行；正式子程序只繼承已核准SHA。各版的開始標記、stdout／stderr及結果保存在shop-mysql-runtime/v75/formal/revision1或revision2，不覆寫既有窗口；必要case ID必須實際出現在通過證據。若保存收據跨過期限，另存deadline veto，公開彙總必須採用該否決結果。

V74的3–5小時為整體工作估計，機器驗收已含在內；不因額度、失敗或時間壓力縮減必要案例。每個可安全完成的小步驟後更新README並提交推送。額度不足時保留已封存內容與未完成項目，停在下一次執行前；不自行使用額度重設或購買額度。

## 第二步：人工資料與獨立golden已封存

修正後的準備成功建立三組人工bundle，並由凍結V1／V2核對完整aggregate，保存V2逐筆golden。這是準備獨立參照，不是V75候選通過，也沒有啟動正式驗收窗口。

| 人工bundle | queries／visitors | 封存檔案數 | bytes |
| --- | ---: | ---: | ---: |
| F-small | 7／6 | 26 | 2,216,565 |
| F-long | 129／3 | 26 | 3,465,659 |
| F-edge | 1／1 | 26 | 2,361,758 |
| 合計 | 三組各有原人工2,000 draws | 78 | 8,043,982 |

[人工registry封存](../reports/mainline/v75_fixture_seal_20261117.json)綁定工具準備修訂2及三個manifest，各manifest列出完整角色／bytes／SHA白名單。78個人工檔案均完成描述符核對，沒有公開原始列、DB或本機golden內容。

固定工具SHA為`bbaa8fc1b594f70b80c995a6c35f303a06b0151052d90bb6ce772731f18cc8d8`；人工registry SHA為`54506fa4dc3b455c114165eede9cf2486ee1f080393db0339d2c41e56db65f5a`。本步README與registry推送後，才可開正式第1窗口；目前正式窗口仍0。

## 第三步：正式第1窗口失敗並停止

[第1窗口收據](../reports/mainline/v75_synthetic_acceptance_revision1_20261117.json)記錄實際耗時10.812秒，非超時、非來源身分失敗。共啟動5個方法：4通過，第5個在A04.neighbors.499發生TypeError，新案例呼叫凍結V1 predict少傳必要watch參數。34個子案例通過、1個失敗；29個方法與161個子案例未執行。不能把前段通過當成整關通過。

窗口已依fail-fast停止，完整錯誤／stdout／stderr／required-case缺漏與程序證據保留。耗時只用於合成驗收期限，不是解碼、排名或完整入口效能。本次屬新案例實作錯誤，可用已確認範圍內僅一次修正版；須先修正並重新封存／推送，再以第2窗口完整重驗全部必要項目。第1版通過項不得拼接到第2版，第二版失敗即停止。

## 第四步：唯一正式修正版已封存

只修改新A04案例的一行呼叫，補上凍結V1 predict要求的`watch=lambda: None`；舊方法、科學規則、門檻、34個必要方法與196個子案例均未更動。凍結oracle簽章與其餘新案例的API／欄位完成只讀複核，修正期間沒有執行小樣本、單例或正式補跑。

[修正原因與前版證據](../reports/mainline/v75_revision2_reason_20261117.json)、[正式修正版工具封存](../reports/mainline/v75_tool_seal_revision3_20261117.json)及[修正版人工registry](../reports/mainline/v75_fixture_seal_revision2_20261117.json)相互綁定。三組人工manifest與golden bytes完全沿用原封存內容，沒有重產或改expected；新registry只改綁修正版工具身分。

上列第2窗口命令需在本步推送後才啟動，從頭執行全部必要案例。這是已確認範圍內唯一正式修正版；若再失敗、逾時或缺漏，保存結果並停止，不開第3窗口。

## 最終結果：第2窗口未通過，依上限停止

[第2窗口收據](../reports/mainline/v75_synthetic_acceptance_revision2_20261117.json)記錄38.063秒，非超時、非來源權威失敗。從頭重驗13個方法：12通過，第13個在A09.missing_database負例發生未被案例接住的FileNotFoundError。75個子案例通過、1個錯誤、120個未執行；尚有21個方法未執行。第1版的通過項未併入此判定。

這次已實際通過三組人工完整payload與凍結golden逐位元一致、原人工2,000 draws、F-long 64／64／1 chunks、精確核心向量、七路缺多／重複／錯序、cache及未封存DB恢復等方法。但真程序恢復、鎖內guard的完整負例、publisher／finalizer及全部期限／帳法案例尚未跑完，不能宣稱完整接入或恢復發布驗收成功。

A09故意將已封存DB移到保留名稱；既有CP在writer恢復的stage artifact核對拋出FileNotFoundError，而新案例只預期ValueError／IntegrityError。停止後只讀查看現有檔案：candidate與acceptance均不存在，被移走的DB仍保留。這支持「該輸入已被拒收」的局部事實；它不能補算該案例通過，也不能替代未執行項目。本輪未修改凍結CP或再補跑。

| 正式窗口 | 整輪秒數 | 方法通過／錯誤／未執行 | 子案例通過／錯誤／未執行 | 判定 |
| --- | ---: | --- | --- | --- |
| 第1窗 | 10.812 | 4／1／29 | 34／1／161 | failed，新案例漏傳watch |
| 第2窗 | 38.063 | 12／1／21 | 75／1／120 | failed，缺DB負例未涵蓋實際例外型別 |

兩個正式窗口與唯一修正版已用完，已停止且沒有第3窗口。最後額度查詢仍可使用、約剩17%；停止原因是V74已確認的兩窗口上限，並非額度耗盡。原始失敗與程序證據全部保留，測試後未新增量測、訓練或真實重跑。

下一步宜先另列新負例的精確修正：只在缺DB情境涵蓋預期FileNotFoundError，同時保留拒收位置、原DB證據與無成功收據的驗證；其餘必要案例與門檻不減。若要再次驗收，須另訂下一輪範圍與窗口，不能把本輪上限默默延長。真實166,897筆、T_plan／容量與K1−C1結論仍未完成。

## 本輪進度

| 步驟 | 狀態與實際結果 |
| --- | --- |
| 1. 工具與案例來源 | 已準備並靜態複核；35個方法／案例描述符、34方法／196子案例待執行 |
| 2. 三組人工資料與golden封存 | 修正後三組皆已建立；78檔共8,043,982 bytes，凍結V1／V2核對並保存golden；V75候選未執行 |
| 3. 有限合成驗收 | 兩窗均failed；第2窗12方法／75子案例通過、1子案例錯誤，21方法／120子案例未執行；已依上限停止 |
| 真實研究／Linux／量測 | 全部0；保留測試locked、T_plan未知 |

每日10%提醒的待資料與優先順序沿V71；Dashboard仍等待適用程度確認。本輪人工接入即使通過，也不代表真實166,897筆完整驗收、容量／成本或K1−C1結論完成。
