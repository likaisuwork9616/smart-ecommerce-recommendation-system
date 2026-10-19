# SQL導覽

SQL分析使用本機MySQL的`olist_ecommerce`資料庫。先依[環境指南](../docs/LOCAL_SETUP.md)完成資料庫與九張Olist表，再於DBeaver或[SQL Notebook](../notebooks/02_olist_sql_analysis.ipynb)執行查詢。

| 檔案 | 用途 |
| --- | --- |
| [01_create_database.sql](01_create_database.sql) | 建立資料庫；資料表由CSV匯入程式建立 |
| [02_basic_check.sql](02_basic_check.sql) | 確認目前資料表與九張表的筆數 |
| [03_business_analysis.sql](03_business_analysis.sql) | 十項商業查詢：月份、營收、品類、付款、評論、配送、延遲、地區及平均客單價 |

啟動DBeaver：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_dbeaver.ps1
```

上述指令從專案根目錄執行。商業SQL的查詢結果與圖表見[Stage 3成果](../docs/STAGE3_BUSINESS_ANALYSIS.md)；此階段以完整timestamp比較延遲，Stage 4改用日曆日期，兩者延遲率不能直接混用。

一般查詢不需要重新匯入CSV。`load_olist_to_mysql.py`使用`if_exists="replace"`，會重建同名表，操作前應確認現有資料是否需要保留。資料位置見[資料說明](../data/README.md)。
