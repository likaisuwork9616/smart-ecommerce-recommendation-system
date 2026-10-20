# 資料放置與保留方式

資料集、處理後特徵與逐筆分數僅保留在本機。此目錄的說明文件納入Git，`raw/`與`processed/`由Git忽略。

## Olist

從[Olist資料集頁面](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)取得以下九個CSV，直接放在`data/raw/olist/`，保留原檔名。

| 檔名 | 匯入後資料表 |
| --- | --- |
| `olist_customers_dataset.csv` | `customers` |
| `olist_orders_dataset.csv` | `orders` |
| `olist_order_items_dataset.csv` | `order_items` |
| `olist_order_payments_dataset.csv` | `order_payments` |
| `olist_order_reviews_dataset.csv` | `order_reviews` |
| `olist_products_dataset.csv` | `products` |
| `olist_sellers_dataset.csv` | `sellers` |
| `olist_geolocation_dataset.csv` | `geolocation` |
| `product_category_name_translation.csv` | `product_category_name_translation` |

Stage 1–3使用MySQL進行查詢；建立與匯入流程見[本機環境指南](../docs/LOCAL_SETUP.md)，資料表關係見[核心ERD](../docs/olist_core_erd.png)，查詢入口見[SQL導覽](../sql/README.md)。匯入程式會取代同名資料表，不是一般只讀檢查指令。

Stage 4直接讀CSV，不需要啟動MySQL。原始欄位、延遲標記與時間範圍見[延遲模型方法](../docs/STAGE4_DELAY_PREDICTION.md)。地理特徵使用的地理表、各輪快取和來源SHA依當輪規格，不可用其他版本直接替換。

最新[事件與承諾版本來源查核](../docs/STAGE4_EVENT_SOURCE_AVAILABILITY.md)確認：本機九表與同內容ZIP沒有取消／非送達結案事件的取得時鐘或承諾版本；本機DB與2026匯入binlog也不能補成原業務日誌。官方API文件僅有線索，未取得同匿名ID的授權歷史匯出與涵蓋證明，目前列為待資料。新來源需先驗收事件／取得／生效時間及ID映射，不以檔案mtime或最終status回填。

## 處理資料與模型

| 位置 | 用途 |
| --- | --- |
| `data/processed/` | 特徵快取、逐筆預測、排名與中間資料 |
| `models/`（專案根目錄） | 原版、平衡模式及各輪研究模型 |
| `.runtime/`（專案根目錄） | 下載、執行紀錄、獨立核對及Notebook執行副本 |
| [`reports/`](../reports/README.md) | 可公開的聚合JSON、事前規格與圖表 |

快取與模型不隨repository提供。重現既有實驗前，先讀對應[方法文件](../docs/README.md)的來源與步驟；不要為補缺檔就依序重跑全部訓練。特徵快取包含不同欄位集合與答案時鐘，相同「102欄」不代表相同內容。

`data/sample/`目前沒有追蹤的範例資料，不作為可執行流程的必要輸入。

## Retailrocket

規劃用於瀏覽、加購、購買與推薦研究，目前尚未啟動。`data/raw/retailrocket/`只作預留位置，不代表已完成資料匯入、特徵或推薦模型。
