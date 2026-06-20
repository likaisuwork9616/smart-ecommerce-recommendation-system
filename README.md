
# 電商智慧推薦系統

Smart E-Commerce Recommendation System

本專案以電商資料分析與推薦系統為主軸，使用 Olist Brazilian E-Commerce Dataset 與 Retailrocket Recommender System Dataset，逐步完成從資料匯入、SQL 分析、商業 EDA、機器學習預測、推薦系統，到 FastAPI + AJAX 展示的完整資料產品流程。

目前專案進度已完成 Olist 資料庫建置、SQL 基礎分析，並進入 Stage 3：Olist 商業分析 EDA。

---

## 專案目標

本專案的目標不是單純訓練一個模型，而是練習完整的資料產品開發流程：

```text
資料集下載
↓
資料清理與資料庫設計
↓
SQL 查詢與商業分析
↓
EDA 視覺化分析
↓
機器學習模型
↓
推薦系統
↓
FastAPI 後端 API
↓
AJAX 前端串接
↓
Dashboard 與作品集展示
```

---

## 使用資料集

### 1. Olist Brazilian E-Commerce Dataset

用途：

* 訂單分析
* 營收分析
* 商品品類分析
* 付款方式分析
* 評論分數分析
* 物流配送分析
* 延遲訂單分析
* 顧客地區分布分析
* 後續延遲預測與評論預測模型

### 2. Retailrocket Recommender System Dataset

用途：

* 使用者瀏覽行為分析
* 加入購物車分析
* 購買行為分析
* 熱門商品推薦
* Item-to-Item 推薦
* 個人化推薦系統
* 推薦 API 串接

---

## 專案資料夾結構

```text
smart-ecommerce-recommendation-system/
│
├── README.md
├── requirements.txt
├── .gitignore
│
├── data/
│   ├── README.md
│   ├── raw/
│   │   ├── olist/
│   │   └── retailrocket/
│   ├── processed/
│   └── sample/
│
├── notebooks/
│   ├── 01_olist_data_overview.ipynb
│   ├── 02_olist_sql_analysis.ipynb
│   └── 03_olist_business_analysis.ipynb
│
├── sql/
│   ├── 01_create_database.sql
│   ├── 02_basic_check.sql
│   └── 03_business_analysis.sql
│
├── scripts/
│   ├── load_olist_to_mysql.py
│   ├── db_config.py
│   └── db_config_example.py
│
├── reports/
│   └── images/
│       └── olist_core_erd.png
│
├── src/
│   ├── data_processing/
│   ├── features/
│   ├── models/
│   └── recommenders/
│
├── api/
│   └── main.py
│
├── frontend/
│   ├── index.html
│   ├── product.html
│   ├── app.js
│   └── style.css
│
├── dashboard/
│   └── streamlit_app.py
│
└── models/
    └── README.md
```

---

## 目前完成進度

### Stage 1：Olist 資料認識與環境建立

已完成：

* 下載 Olist 資料集
* 建立專案資料夾結構
* 整理原始資料放置位置
* 使用 Python 載入 CSV
* 匯入 Olist 資料到 MySQL
* 使用 DBeaver 檢查資料表
* 建立初步 ERD 圖
* 理解主要資料表之間的關係

主要資料表：

* `orders`
* `order_items`
* `order_payments`
* `order_reviews`
* `customers`
* `products`
* `sellers`
* `geolocation`
* `product_category_name_translation`

---

### Stage 2：Olist SQL 基礎分析

已完成：

* 查詢總訂單數
* 查詢各訂單狀態數量
* 查詢銷售額最高商品
* 查詢商品品類營收
* 計算平均客單價 AOV
* 練習多表 JOIN
* 使用 Notebook 執行 SQL 查詢
* 將 SQL 分析整理於 `02_olist_sql_analysis.ipynb`

---

### Stage 3：Olist 商業分析 EDA

目前進行中，主要 Notebook：

```text
notebooks/03_olist_business_analysis.ipynb
```

目前已完成以下分析：

#### 1. MySQL 連線設定

使用 `SQLAlchemy` 與 `PyMySQL` 連線 MySQL，並透過 `scripts/db_config.py` 管理資料庫設定。

同時建立 `scripts/db_config_example.py` 作為公開範例設定檔，避免將本機資料庫密碼上傳至 GitHub。

---

#### 2. 訂單總數檢查

使用 SQL 查詢確認 `orders` 表可正常讀取，作為 Notebook 與 MySQL 連線測試。

```sql
SELECT COUNT(*) AS total_orders
FROM orders;
```

---

#### 3. 每月訂單數趨勢

分析目的：

觀察 Olist 平台每月訂單量變化，了解訂單是否有成長趨勢、季節性波動或異常月份。

分析方式：

* 使用 `orders` 表
* 依照 `order_purchase_timestamp` 轉換成年月
* 篩選已送達訂單 `delivered`
* 依月份統計訂單數
* 使用折線圖呈現趨勢

---

#### 4. 每月營收趨勢

分析目的：

觀察每月營收變化，並與每月訂單數趨勢互相比較。

分析方式：

* 使用 `orders` 與 `order_items`
* 計算每筆商品價格與運費
* 依照訂單月份彙總營收
* 使用折線圖呈現每月營收趨勢

---

#### 5. Top 10 商品品類營收

分析目的：

找出 Olist 平台主要營收來源品類，判斷營收是否集中於少數商品類別。

分析方式：

* 使用 `order_items`
* JOIN `products`
* LEFT JOIN `product_category_name_translation`
* 計算各商品品類總營收
* 取營收最高的前 10 名
* 使用水平長條圖呈現

---

#### 6. 付款方式分布

分析目的：

了解顧客主要使用哪些付款方式，觀察信用卡、boleto、debit card 等支付方式的使用比例。

分析方式：

* 使用 `order_payments`
* 依照 `payment_type` 分組
* 統計各付款方式出現次數
* 使用長條圖呈現付款方式分布

---

#### 7. 評論分數分布

分析目的：

觀察顧客評價分布，了解大多數訂單為好評或差評，作為後續評論好壞預測模型的基礎。

分析方式：

* 使用 `order_reviews`
* 依照 `review_score` 分組
* 統計 1 到 5 分評論數量
* 使用長條圖呈現評論分數分布

---

#### 8. 物流配送天數分布

分析目的：

了解訂單從下單到實際送達所需天數，觀察大多數訂單的配送時間與是否存在極端延遲案例。

分析方式：

* 使用 `orders`
* 篩選已送達且有送達日期的訂單
* 將日期欄位轉換為 datetime
* 計算：

```text
delivery_days = order_delivered_customer_date - order_purchase_timestamp
```

* 使用直方圖呈現配送天數分布

---

#### 9. 延遲訂單比例

分析目的：

計算有多少訂單晚於預估送達日期，作為後續 Stage 4「訂單是否延遲預測」的 Label 設計基礎。

分析方式：

建立延遲欄位：

```text
is_delayed = order_delivered_customer_date > order_estimated_delivery_date
```

並計算延遲訂單比例。

---

#### 10. 各州顧客訂單分布

分析目的：

了解 Olist 顧客訂單主要集中在哪些州，觀察是否存在明顯地區集中現象。

分析方式：

* 使用 `orders`
* JOIN `customers`
* 依照 `customer_state` 統計訂單數
* 使用長條圖呈現各州訂單分布

---

## Stage 3 目前成果

目前 `03_olist_business_analysis.ipynb` 已經具備完整 EDA 雛形，包含：

* SQL 查詢
* Pandas DataFrame 分析
* Matplotlib 視覺化
* 訂單分析
* 營收分析
* 商品品類分析
* 付款分析
* 評論分析
* 物流分析
* 延遲分析
* 地區分布分析

下一步會補上每個圖表下方的商業觀察，讓 Notebook 不只是產生圖表，而是能夠說明資料背後的商業意義。

---

## 安全設定說明

本專案使用 `scripts/db_config.py` 管理本機 MySQL 連線設定。

由於 `db_config.py` 可能包含資料庫帳號與密碼，因此不建議上傳至 GitHub。

建議做法：

```text
上傳：
scripts/db_config_example.py

不上傳：
scripts/db_config.py
```

`.gitignore` 建議加入：

```gitignore
scripts/db_config.py
```

`db_config_example.py` 範例：

```python
DB_CONFIG = {
    "user": "your_mysql_user",
    "password": "your_mysql_password",
    "host": "localhost",
    "port": 3306,
    "database": "olist_ecommerce",
    "charset": "utf8mb4"
}
```

---

## 下一步規劃

### Stage 3 待補強

* 在每張圖表下方補上 Markdown 商業觀察
* 將重要 SQL 整理到 `sql/03_business_analysis.sql`
* 將重要圖表輸出到 `reports/images/`
* 更新 README 中的 EDA 成果截圖
* 整理 Stage 3 的商業洞察總結

### Stage 4：訂單是否延遲預測

下一階段將進入第一個機器學習分類模型，目標是預測訂單是否會延遲送達。

Label 設計：

```text
order_delivered_customer_date > order_estimated_delivery_date
→ delayed = 1

否則
→ delayed = 0
```

預計使用特徵：

* 商品價格
* 運費
* 付款方式
* 分期數
* 商品品類
* 顧客州別
* 賣家州別
* 下單月份
* 下單星期幾
* 預估配送天數
* 商品重量
* 商品尺寸

---

## 使用技術

目前已使用：

* Python
* Pandas
* Matplotlib
* SQLAlchemy
* PyMySQL
* MySQL
* DBeaver
* Jupyter Notebook
* Git / GitHub

後續預計使用：

* Scikit-learn
* XGBoost / LightGBM
* Streamlit
* FastAPI
* JavaScript
* AJAX

---

## 目前專案狀態

```text
Stage 1：Olist 資料認識與環境建立       ✅ 已完成
Stage 2：Olist SQL 基礎查詢             ✅ 已完成
Stage 3：Olist 商業分析 EDA             🟡 進行中
Stage 4：訂單是否延遲預測               ⬜ 尚未開始
Stage 5：評論好壞預測                   ⬜ 尚未開始
Stage 6：RFM 顧客分群                   ⬜ 尚未開始
Stage 7：Streamlit Dashboard            ⬜ 尚未開始
Stage 8：Retailrocket EDA                ⬜ 尚未開始
Stage 9：熱門商品推薦                   ⬜ 尚未開始
Stage 10：其他人也看了                  ⬜ 尚未開始
Stage 11：其他人也加入購物車             ⬜ 尚未開始
Stage 12：其他人也買了                  ⬜ 尚未開始
Stage 13：個人化推薦                    ⬜ 尚未開始
Stage 14：FastAPI 推薦 API              ⬜ 尚未開始
Stage 15：AJAX 前端串接                 ⬜ 尚未開始
```
