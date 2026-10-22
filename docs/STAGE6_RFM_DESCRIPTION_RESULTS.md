# Stage 6：一次真實只讀RFM描述與交付驗收

已依[凍結執行契約](STAGE6_RFM_DESCRIPTION_EXECUTION.md)呼叫原`execute_prepared`一次，完成來源、獨立完整同ID名冊、私有四檔、公開聚合與反讀；再以禁止core的`verify_completed`驗收，未重算描述。實際結果見[只讀描述](../reports/stage6/rfm_description.json)與[交付驗收](../reports/stage6/rfm_description_acceptance.json)。這是單一歷史快照的G1描述，沒有模型效能、未知資料成績或客群效果。

本輪未估分群切點、打分／分群、重抽樣、訓練或製作Dashboard；Stage 4、5維持待資料，Stage 4每日10%及11／29／42／73／101五種子不變。固定描述分位數及IQR旗標屬G1摘要，並非G2分群切點。

## 實際執行與版本

| 查核 | 實際結果 |
| --- | --- |
| 凍結入口 | 原函式實際呼叫1次，core 1次、source loader 1次、獨立名冊衍生1次；執行175.759135秒 |
| 完成反讀 | `verify_completed`通過，core呼叫0次；93.232474秒；有效output_guard、無failure，公開檔並非單獨成功依據 |
| 來源 | 完整41份版本及42項既有metadata前後相符；原spec／preflight／receipt／input guard未回寫 |
| 原資料 | 沿用已驗收RFM v1；S＝2017-09-01 00:00:00（含）、T＝2018-09-01 00:00:00（不含），naive秒時鐘 |
| 顧客名冊 | 原orders／customers最小投影獨立重建93,234歷史合格顧客UID，與accepted dataset及新名冊完整同ID |
| 逐單名冊 | 原來源全部99,421筆purchase<T訂單及74,088筆窗口合格單均同ID；每單11欄UID／時鐘／資格／原因等proof一致，不刪母體外排除或隔離單 |
| 私有／公開 | 私有description、customer roster、order roster、manifest四檔通過；公開聚合綁spec及完整41來源版本，未提交名冊或私有digest |
| 反讀數量 | 93,234顧客×3＋99,421訂單×5＝776,807格；另244個聚合scalar、其中45個binary64值；型別／null／浮點位元一致 |
| 測試範圍 | 沿用前輪58項合成實測receipt；本輪未重跑58／46／32／130測或全專案discover，不把來源比對或逐格驗收計入單元測試數 |

另由獨立稽核程式以原CSV及datetime重建UID全集、全部T前／窗口ID與逐單11欄事件proof，不呼叫原derive_roster／event_decision或描述器：1,093,631格proof及新名冊全部一致，保留2,872筆顧客母體外訂單。它先在禁止core時再次通過verify_completed（88.731752秒），再核四檔／public／guard、原core聚合版本及金額守恆；全稽核95.679569秒、core_attempts＝0，41來源與66份既有私有證據不變。這是交付與來源語義的獨立核對，沒有重新估計描述分位數，也不與776,807格名冊加總成測試數。

舊[執行準備報告](../reports/stage6/rfm_description_execution_preflight.json)內`real_description_executed=false`及準備輪policy／docstring保留原bytes，代表前輪狀態；本輪真實執行另存新結果與驗收，不改凍結來源來補寫成功。

## 完整分流與數值母體

| 狀態 | 顧客數 | 本輪處理 |
| --- | ---: | --- |
| active_complete | 72,124 | 唯一R／F／M數值描述母體 |
| inactive_complete | 21,109 | 完整保留，R為null、F＝M＝0；不混入活躍分布 |
| active_with_quarantine | 1 | 完整保留，M為null；可見R／F僅部分合格子集，不混入數值母體 |
| active_money_unknown | 0 | 保留狀態與null統計，不能由本快照推論未來皆為0 |
| inactive_with_quarantine | 0 | 同上 |
| 全母體 | 93,234 | 五狀態互斥、完整同ID，無刪人 |

每軸數值摘要N＝72,124、null＝0。這不代表全體顧客沒有缺值：零活動顧客的R缺失與隔離顧客的M遮罩均在分流內列出。

## 固定G1描述

下表僅摘錄報告的原尺度摘要；R以原秒數除86,400顯示天、M以原整數分除100顯示BRL，顯示值可四捨五入，原報告保留精確整數及mean分子／分母。完整P0／1／5／25／50／75／95／99／100、log1p視圖、null原因與IQR旗標均見JSON。

| 軸 | Q25 | 中位數 | Q75 | 平均 | 範圍 |
| --- | ---: | ---: | ---: | ---: | --- |
| R：距最近合格窗口購買（天） | 90.25 | 173.51 | 262.05 | 174.65 | 2.37–365.00（原max＝31,535,770秒，小於365天） |
| F：合格窗口訂單數 | 1 | 1 | 1 | 1.027217 | 1–11；8種不同值 |
| M：商品毛額（BRL） | 47.90 | 89.80 | 152.00 | 140.98 | 0.85–13,440.00 |

- F＝1：70,333／72,124＝97.516777%；Q95也為1，IQR＝0。Bowley與IQR fence／離群數均為null並明記退化，不能解讀為零離群，亦不能假設五等份能產生五級。
- M＝0：0／72,124。M≥Q99＝100,499分（BRL1,004.99）者723人，占1.002440%；包含門檻全部ties，並非剛好top 1%。其商品毛額115,021,680分，占完整活躍總額1,016,786,312分的11.312277%。
- IQR只做旗標：R標記0人，M標記6,036人（8.368920%）；F為退化null。各軸移除數均0，未截尾、clip、winsorize或改原RFM。log1p是另一顯示尺度，不是另一份穩定性證據。

守恆逐項通過：全顧客F合計74,088＝窗口合格訂單74,088；完整活躍F合計74,087，其餘1單是隔離顧客的合格子集。已知窗口商品額1,016,801,111分＝完整顧客可公開M 1,016,786,312分＋遮罩顧客已知子集14,799分；該隔離顧客的M仍為null，沒有以0補未知或把部分金額放回完整母體。

## 產物與後續只讀操作

| 位置 | 內容／交付範圍 |
| --- | --- |
| reports/stage6/rfm_description.json | 凍結描述器的完整公開聚合、41來源、規格版本及反讀receipt |
| reports/stage6/rfm_description_acceptance.json | 本輪單次執行、版本、完整名冊及獨立驗收的公開聚合證據 |
| .runtime/stage6_rfm_evaluation_v1/ | description.json、customer_roster.csv、order_roster.csv、manifest.json；Git忽略 |
| .runtime/stage6_rfm_description_execution_v1/ | 原input_guard及新output_guard；無failure；Git忽略 |
| .runtime/stage6_rfm_description_real_* | 私有driver、執行前snapshot、實際呼叫紀錄、獨立驗收及發布檢查；Git忽略 |

本輪在新授權下，以私有driver直接呼叫凍結函式，沒有增設真實執行CLI、路徑覆寫或改寫準備入口。現有輸出已存在，**不要重呼叫execute_prepared、刪檔、重建guard或重播prepare**；失敗／部分產物也必須保留，後續改版另約版本。

需要再次核對現有結果時，可於專案根目錄執行以下只讀驗收；它會重讀來源與完整名冊，但不重算描述：

```powershell
.\.venv\Scripts\python.exe -c "from scripts.prepare_rfm_description import verify_completed; print(verify_completed())"
```

需本機原來源、完整私有產物與原guard；Git clone只有公開程式／聚合，不含個體資料，缺件即停止，不偽造receipt或重建證據補齊。

## 適用範圍與下一步

G0＝passed、G1＝ready_for_aggregate_review；G2／G3＝not_executed、temporal＝pending_data。這次完成的是歷史快照描述與交付驗收，不是客群穩定、模型效能或營運用途驗收。T前條件依現有最終快照回顧，仍缺原始入庫／版本、完整生命週期、退款／結算等證據；M是名目商品毛額，不是淨消費、LTV或未來價值。單一T也不能證明跨時間穩定。

主要限制是F高度集中於1且IQR退化。下一步建議先依[已凍結G2／G3契約](STAGE6_RFM_EVALUATION_SPEC.md)實作規則候選與資格守門，**只用合成資料**驗證ties不拆分、重複切點、常數軸、有效級數、支援量及同ID重現，再決定是否執行真實切點／分群；不能看到退化就改切點、拆ties、合併稀疏格或重選種子放行。

發布前檢查通過：77份Markdown的1,208個本機檔案連結存在，124份JSON通過嚴格解析；495份未列為本輪文件／屬性修改的既有追蹤檔及66份既有私有證據bytes不變。新公開JSON未含32位個體ID、私有bundle／receipt／guard digest；來源與所有私有／公開輸出版本仍與成功紀錄相符，未再執行描述或模型fit。私有檢查紀錄在`.runtime/stage6_rfm_description_real_publication_qa.json`。
