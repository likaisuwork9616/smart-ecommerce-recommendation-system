# Stage 9：P0、完整候選評估器實作與開發入口凍結

2026-10-28 依已凍結的[執行規格v1](contracts/retailrocket_popularity_execution_v1.json)實作P0及完整候選評估器，完成手算、獨立oracle與合成CSV反讀後，凍結真實開發入口。本輪只有合成資料執行：**0真實fit、0真實排名、0真實推薦指標，預留測試locked**。

目前狀態見[實作與合成驗收](../reports/stage9/retailrocket_popularity_v1_implementation_acceptance.json)及[開發入口規格](../reports/stage9/retailrocket_popularity_v1_development_specification.json)。上輪契約的`implementation_complete=false`保留凍結當下狀態，不改寫舊規格／收據；本輪新收據記錄程式已實作、真實開發尚未執行。

## 實作內容

| 模組 | 行為與邊界 |
| --- | --- |
| [P0／完整候選／指標核心](../scripts/retailrocket_popularity.py) | canonical train view每列加1，整數次數唯讀；query前已出現商品才可排序，未知商品0分、數值ID解tie，不刪已看商品 |
| [CSV adapter與產物writer](../scripts/retailrocket_popularity_io.py) | 精確schema、validation角色、成熟／時窗／名冊檢查，以query key連當前basket；逐query保留排序、指標與切片，不讀reserved_test目標JSON |
| [獨立oracle](../scripts/retailrocket_popularity_oracle.py) | 另讀合格CSV、SQL重算次數，完整排序或獨立等價證明；50位Decimal對數及Fraction比例核指標，不匯入主核心／adapter |
| [開發入口](../scripts/run_retailrocket_popularity_v1.py) | `--prepare`僅合成驗收與來源凍結；`--run-development`為下一輪一次train fit＋validation完整反讀；`--verify`只驗既有bytes |

排名器只接收唯讀fit次數、query時鐘與因果商品目錄，沒有target、訪客特徵、next時間、session末次時間或訓練活動旗標參數。query診斷與答案僅交給評估器，避免以未來資訊或活動組影響推薦。

P0固定使用2015-05-04至08-01前train canonical view，暖身、驗證、測試、加購與交易均不進次數。包含沒有後續標註的session末次view；不以已標註query縮小fit母體。缺統計商品仍是0分候選，新訪客使用相同熱門排序。fit_id綁算法、窗、角色與排序後的正次數表；資料、程式、環境及CSV產物身分另由manifest／guard的SHA綁定。

候選數用全部商品first-seen時間的嚴格前綴求得。主路徑按正次數順序逐項核時間，再依數值ID補零分候選，結果必須是整個候選目錄的精確top10；不先採樣或注入答案。

獨立oracle一般以完整候選排序核對。如果證明「至少10個正次數fit商品，且每一個都在validation起點前出現」，所有合法validation query都含這些商品，正次數的前10名便與各query完整目錄排序完全等價；仍逐query獨立核候選數、名冊與全部輸出。條件不成立就走完整排序，不把未驗的global top10當完整候選結果。兩條路徑均已用合成資料核對。

## 手算與獨立oracle合成驗收

[核心／CSV測試](../tests/test_retailrocket_popularity.py)與[入口測試](../tests/test_retailrocket_popularity_entry.py)共54項實際通過，全部使用合成資料，包含：

- 訓練單位、warmup／validation／test排除、未標註末次view保留、未來資料不改fit身分、fit唯讀。
- 27個候選時間前綴逐一對獨立完整排序，含未來高分商品、同時刻first-seen、零分tie、短／空目錄、錯誤／次佳排序與fit身分拒收。
- 1,024種二元命中排列，逐項對Decimal／Fraction oracle核DCG、IDCG、NDCG、Recall、HitRate與MRR。
- query／visitor macro不同權重、完整目標分母、條件分母、候選聯集、空目錄不刪query、空小組null及非空小組支援不足。
- 合成原始CSV→fit→逐query輸出→獨立SQL／oracle反讀，包含一般完整排序與可證明快取兩種case；損壞、NaN、額外列、錯分母、錯schema與覆寫均拒收。
- 入口只允許development，沒有final-refit或reserved-test指令；來源變更、路徑越界、部分產物、已存在後期重估／測試紀錄均守門。

一個手算案例：候選排序為2、10、20、1，完整target為10與尚不可達的999。ID10在第2名命中，因此令`d=1/log2(3)`，DCG=d、IDCG=1+d，**合成NDCG=d/(1+d)≈0.3868528072、Recall=1/2、HitRate=1、MRR=1/2**。若先刪掉不可達999，IDCG與Recall分母都會錯；測試明確拒絕這種縮分母。

另一個手算案例有訪客A兩筆全命中、訪客B一筆未命中，query-macro NDCG為2/3，visitor-macro為1/2；程式兩者分開計算。這些數字僅是合成驗收答案，**不是Retailrocket真實推薦成績**。

正式準備流程另執行兩個小型、有效合成corpus，完整核對item_counts、ranked_queries、query_metrics及query_slices四CSV到EOF，並核fit audit與全部aggregate JSON。實際列數、格數、測試耗時及來源數都記在[合成驗收收據](../reports/stage9/retailrocket_popularity_v1_implementation_acceptance.json)，不加總前輪測試數當模型成績。

## 凍結的真實開發入口

準備流程核上輪完整來源鏈、已驗收資料bytes、執行規格、這輪程式／測試與Python環境身分，寫入新入口規格、合成反讀及guard。只用binary SHA核資料，不解析真實CSV或估統計；合成fit／oracle counter與真實counter分開。

`--run-development`已實作，但**本輪未呼叫**。後續執行會：

1. 核所有凍結來源、程式、環境及合成證據，確認預留測試仍locked，沒有final_refit／reserved_test／test_usage後期紀錄。
2. 排他建立development目錄及started marker，記錄一次主fit嘗試，才讀真實資料。
3. 只fit固定train窗一次，對完整166,897筆validation query排名，保留62,235訪客及完整166,952次target分母；不計訓練成績、不排測試、不以得分決定是否驗收。
4. 以獨立SQL count、全候選oracle及高精度指標重算，核全部四CSV、fit audit及完整聚合；整數／ID／列表精確一致，浮點abs／rel各1e-12。
5. 通過才保存真正開發結果、驗收、manifest與output_guard。來源、名冊、候選、成熟條件、模型身分、有限值或分母有差異就停止，保留部分產物，不刪query繼續。

目前只驗已準備的入口：

```powershell
.\.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --verify
```

此指令不重跑合成、fit或指標。`--prepare`已完成，完整產物重入只驗來源；部分準備或development不報成成功、不覆寫重播。

下一輪明確要求真實開發後才使用下列入口，本輪沒有執行：

```powershell
.\.venv\Scripts\python.exe -B scripts\run_retailrocket_popularity_v1.py --run-development
```

該指令永遠只開validation。最終train＋validation重估與預留測試入口**沒有在本輪實作**；核心評估及CSV loader也拒絕training／reserved_test角色。後續若要開測試，仍須按[原規格八項條件](STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md)另行凍結最終重估／測試實作及使用journal，不能更改本輪locked快照冒充啟用。

## 產物、限制與下一步

| 位置，全部在shop內 | 狀態／內容 |
| --- | --- |
| `shop-mysql-runtime/retailrocket_popularity_implementation_v1/` | 已建立：準備guard、test locked快照 |
| `shop-mysql-runtime/verification/retailrocket-popularity-implementation-v1/` | 已建立：原狀、測試、兩個正式合成case及其他反例產物；Git忽略 |
| `shop-mysql-runtime/retailrocket_popularity_v1/development/` | 未建立；留待下一輪一次真實開發 |
| `.../final_refit/`、`.../reserved_test/`、`.../test_usage.jsonl` | 未建立；本入口沒有這些執行模式 |
| `reports/stage9/`兩份新JSON及本文件／程式／測試 | 公開規格、合成聚合與SHA；沒有真實逐query、item統計或模型 |

資料與過去標籤已被builder驗收讀過，預留測試是回溯時間評估，沒有前瞻／原始入庫完整性證據。匿名訪客、無曝光／propensity、可售庫存及非商業授權限制不變。驗證多商品當前／目標56／53筆低於1,669，預留測試33／29筆低於921；沒有因實作通過就解除小組支援限制。空小組null，低支援小組只描述；不報CI或因果／營收／轉換效果。

下一步是依已凍結入口執行**一次真實train fit與完整validation評估、獨立逐query反讀**，如實整理全部結果及小組。預留測試保持locked，通過開發驗收不會自動開測試。

Stage 6 UCI封存與UCI 87／83、Olist 25個小組限制保留；Stage 4／5仍待交接資料，延遲每日10%固定，Dashboard暫緩。完整現況見[全專案進度](PROJECT_PROGRESS.md)。
