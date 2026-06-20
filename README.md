# 電商智慧推薦系統  
# Smart E-Commerce Recommendation System

> 透過 SQL、機器學習與推薦系統，分析電商訂單資料與使用者行為資料，逐步打造一個可展示的電商智慧分析與推薦系統。

---

## 1. 專案簡介

本專案是我的機器學習 Side Project，目標是從真實電商資料出發，練習完整的資料產品開發流程：

```text
Kaggle 資料集
↓
資料清理與資料庫設計
↓
SQL 查詢與商業分析
↓
機器學習模型訓練
↓
推薦系統建立
↓
FastAPI 後端 API
↓
AJAX 前端串接
↓
Dashboard 與作品集展示
```

本專案會分成兩個主要模組：

| 模組 | 使用資料集 | 主要練習 |
|---|---|---|
| 電商商業分析與預測模組 | Brazilian E-Commerce Public Dataset by Olist | SQL、EDA、分類模型、顧客分群、Dashboard |
| 商品推薦系統模組 | Retailrocket Recommender System Dataset | 使用者行為分析、推薦系統、推薦 API、AJAX 串接 |

---

## 2. 專案名稱

中文名稱：

```text
電商智慧推薦系統
```

英文名稱：

```text
Smart E-Commerce Recommendation System
```

GitHub Repository 建議名稱：

```text
smart-ecommerce-recommendation-system
```

---

## 3. 專案目標

本專案的核心目標不是單純訓練一個模型，而是建立一個「從資料分析到推薦展示」的完整電商資料產品。

### 3.1 學習目標

- 練習 SQL 多表查詢與資料庫思維
- 練習 Pandas 資料清理與 EDA
- 練習分類模型與模型評估
- 練習 RFM 顧客分群
- 練習推薦系統基礎方法
- 練習 FastAPI 建立後端 API
- 練習 JavaScript AJAX 串接後端資料
- 練習 Streamlit / Dashboard 成果展示
- 練習整理 GitHub 專案與作品集 README

### 3.2 產品目標

未來希望完成以下功能：

- 首頁熱門商品推薦
- 商品頁「其他人也看了」
- 商品頁「其他人也加入購物車」
- 商品頁「其他人也買了」
- 使用者個人化推薦
- 訂單延遲風險預測
- 評論好壞預測
- 顧客 RFM 分群
- 電商營運 Dashboard
- 推薦 API 與 AJAX 前端展示

---

## 4. 使用資料集

## 4.1 Brazilian E-Commerce Public Dataset by Olist

資料集來源：

```text
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
```

### 資料集定位

Olist 是巴西電商平台的公開訂單資料，主要適合用來練習：

- SQL 多表 JOIN
- 訂單分析
- 商品品類分析
- 付款分析
- 物流延遲分析
- 評論分數分析
- 訂單是否延遲預測
- 評論好壞預測
- RFM 顧客分群
- 商業 Dashboard

### 預計使用資料表

```text
olist_orders_dataset.csv
olist_order_items_dataset.csv
olist_order_payments_dataset.csv
olist_order_reviews_dataset.csv
olist_customers_dataset.csv
olist_products_dataset.csv
olist_sellers_dataset.csv
olist_geolocation_dataset.csv
product_category_name_translation.csv
```

### Olist 適合的 ML 任務

| 任務 | 問題類型 | 說明 |
|---|---|---|
| 訂單延遲預測 | Classification | 預測訂單是否會晚於預估日期送達 |
| 評論好壞預測 | Classification | 根據訂單與物流資訊預測好評 / 差評 |
| RFM 顧客分群 | Clustering | 根據消費時間、頻率、金額分群 |
| 銷售分析 | EDA / BI | 分析營收、品類、顧客與物流表現 |

---

## 4.2 Retailrocket Recommender System Dataset

資料集來源：

```text
https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset
```

### 資料集定位

Retailrocket 是電商使用者行為資料，包含使用者對商品的互動事件，因此非常適合用來練推薦系統。

主要事件包含：

```text
view
addtocart
transaction
```

### 適合練習

- 使用者行為分析
- 熱門商品推薦
- Item-to-Item Recommendation
- 其他人也看了
- 其他人也加入購物車
- 其他人也買了
- 個人化推薦
- 推薦 API
- AJAX 前端串接

### Retailrocket 適合的推薦任務

| 任務 | 使用事件 | 說明 |
|---|---|---|
| 熱門商品推薦 | view / addtocart / transaction | 根據熱門程度推薦商品 |
| 其他人也看了 | view | 看過商品 A 的人，也常看哪些商品 |
| 其他人也加入購物車 | addtocart | 加入購物車 A 的人，也常加入哪些商品 |
| 其他人也買了 | transaction | 買過商品 A 的人，也常買哪些商品 |
| 個人化推薦 | view + addtocart + transaction | 根據使用者歷史行為推薦商品 |

---

## 5. 資料管理策略

### 5.1 目前策略：不直接上傳完整 Kaggle 原始資料

本專案目前不建議將完整 Kaggle 原始資料直接 commit 到 GitHub。

原因：

- Kaggle 原始資料可能檔案較大
- GitHub 對大型檔案有限制
- 原始資料可以由使用者自行從 Kaggle 下載
- GitHub repo 應優先保存程式碼、Notebook、SQL、README 與專案成果
- 若未來需要同步大型資料，再改用 Git LFS

### 5.2 建議同步到 GitHub 的內容

建議上傳：

```text
README.md
requirements.txt
.gitignore
notebooks/
sql/
src/
api/
frontend/
dashboard/
reports/
data/README.md
data/sample/
```

### 5.3 不建議直接同步的內容

建議不要上傳：

```text
data/raw/
data/processed/
*.csv
*.zip
*.parquet
*.db
*.sqlite
*.pkl
*.joblib
```

### 5.4 建議資料夾使用方式

本機資料夾可以這樣放：

```text
data/
├── raw/
│   ├── olist/
│   │   ├── olist_orders_dataset.csv
│   │   ├── olist_order_items_dataset.csv
│   │   └── ...
│   │
│   └── retailrocket/
│       ├── events.csv
│       ├── item_properties_part1.csv
│       ├── item_properties_part2.csv
│       └── category_tree.csv
│
├── processed/
│   ├── olist/
│   └── retailrocket/
│
├── sample/
│   ├── olist_orders_sample.csv
│   ├── olist_order_items_sample.csv
│   └── retailrocket_events_sample.csv
│
└── README.md
```

其中：

| 資料夾 | 是否上傳 GitHub | 說明 |
|---|---|---|
| data/raw/ | 不上傳 | 放完整原始 Kaggle 資料 |
| data/processed/ | 不上傳 | 放清理後或轉換後的大型資料 |
| data/sample/ | 可以上傳 | 放小樣本資料，方便別人快速測試 |
| data/README.md | 上傳 | 說明資料下載與放置方式 |

---

## 6. Data 下載與放置方式

請自行從 Kaggle 下載以下資料集：

### 6.1 Olist Dataset

```text
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
```

下載後請放到：

```text
data/raw/olist/
```

預期結構：

```text
data/raw/olist/
├── olist_orders_dataset.csv
├── olist_order_items_dataset.csv
├── olist_order_payments_dataset.csv
├── olist_order_reviews_dataset.csv
├── olist_customers_dataset.csv
├── olist_products_dataset.csv
├── olist_sellers_dataset.csv
├── olist_geolocation_dataset.csv
└── product_category_name_translation.csv
```

### 6.2 Retailrocket Dataset

```text
https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset
```

下載後請放到：

```text
data/raw/retailrocket/
```

預期結構：

```text
data/raw/retailrocket/
├── events.csv
├── item_properties_part1.csv
├── item_properties_part2.csv
└── category_tree.csv
```

---

## 7. Git LFS 使用說明

目前本專案預設不使用 Git LFS 管理完整原始資料。

建議流程是：

```text
第一階段：
只上傳程式碼、notebooks、sql、README、data/sample

第二階段：
當模型檔、parquet、database 或大型資料真的需要同步時，再導入 Git LFS
```

如果未來要啟用 Git LFS，可以使用以下流程：

```bash
git lfs install

git lfs track "*.csv"
git lfs track "*.zip"
git lfs track "*.parquet"
git lfs track "*.pkl"
git lfs track "*.joblib"
git lfs track "*.db"
git lfs track "*.sqlite"

git add .gitattributes
git commit -m "chore: configure git lfs"
```

確認 LFS 追蹤狀態：

```bash
git lfs ls-files
```

注意：  
如果要使用 Git LFS，請先設定 `git lfs track`，再 `git add` 大型檔案，避免大型檔案被一般 Git history 追蹤。

---

## 8. 建議 .gitignore

請在專案根目錄建立 `.gitignore`：

```gitignore
# Python
__pycache__/
*.py[cod]
.ipynb_checkpoints/

# Virtual environment
.venv/
venv/
env/

# Environment variables
.env

# Raw and processed data
data/raw/
data/processed/

# Large data files
*.csv
*.zip
*.parquet
*.db
*.sqlite
*.pkl
*.joblib

# Allow sample data
!data/sample/
!data/sample/*.csv

# Models
models/*.pkl
models/*.joblib
models/*.h5
models/*.pt

# Cache and system files
.cache/
.DS_Store
```

---

## 9. 專案技術棧

| 類別 | 技術 |
|---|---|
| 程式語言 | Python, JavaScript |
| 資料處理 | Pandas, NumPy |
| 資料庫 | SQLite / MySQL |
| SQL 練習 | SQLite, MySQL, DBeaver |
| 資料視覺化 | Matplotlib, Plotly, Streamlit |
| 機器學習 | Scikit-learn |
| 推薦系統 | Cosine Similarity, Co-occurrence Matrix, Collaborative Filtering |
| 後端 API | FastAPI |
| 前端串接 | HTML, CSS, JavaScript, AJAX |
| 版本控制 | Git, GitHub |
| 大型檔案管理 | Git LFS，未來視需求導入 |
| 開發環境 | Jupyter Notebook, VS Code |

---

## 10. 專案資料夾結構

目前預計專案結構如下：

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
│   │
│   ├── processed/
│   │   ├── olist/
│   │   └── retailrocket/
│   │
│   └── sample/
│       ├── olist_orders_sample.csv
│       └── retailrocket_events_sample.csv
│
├── notebooks/
│   ├── 01_olist_eda.ipynb
│   ├── 02_olist_sql_practice.ipynb
│   ├── 03_olist_delivery_delay_prediction.ipynb
│   ├── 04_olist_review_prediction.ipynb
│   ├── 05_olist_customer_segmentation.ipynb
│   ├── 06_retailrocket_eda.ipynb
│   ├── 07_retailrocket_popular_recommendation.ipynb
│   ├── 08_retailrocket_also_viewed.ipynb
│   ├── 09_retailrocket_also_bought.ipynb
│   └── 10_retailrocket_personalized_recommendation.ipynb
│
├── sql/
│   ├── 01_olist_basic_queries.sql
│   ├── 02_olist_sales_analysis.sql
│   ├── 03_olist_customer_analysis.sql
│   └── 04_olist_logistics_analysis.sql
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
├── models/
│   └── README.md
│
└── reports/
    ├── images/
    └── final_report.md
```

---

## 11. 學習與開發階段

## Stage 1：建立專案與資料管理

### 目標

建立 GitHub 專案結構，整理兩個 Kaggle 資料集。

### 任務

- 建立 GitHub Repository
- 建立資料夾結構
- 放入 README.md
- 建立 `.gitignore`
- 完整 Kaggle 原始資料先放本機 `data/raw/`
- 建立 `data/README.md`
- 可選：建立 `data/sample/` 放小樣本資料

### 完成標準

- GitHub repo 可以正常同步
- README 可以說明專案目的
- 資料夾結構清楚
- 不會把大型 Kaggle 原始資料誤上傳

---

## Stage 2：Olist SQL 與 EDA

### 目標

用 Olist 資料集練習 SQL 與電商商業分析。

### 任務

- 查看所有 Olist CSV
- 匯入 SQLite / MySQL
- 練習基本 SQL 查詢
- 分析訂單量、營收、品類、付款、物流與評論
- 產出 EDA Notebook

### 練習問題

- 總訂單數是多少？
- 每個訂單狀態有多少筆？
- 銷售額最高的商品是什麼？
- 營收最高的品類是什麼？
- 平均客單價 AOV 是多少？
- 哪些州的訂單最多？
- 平均配送天數是多少？
- 哪些因素可能造成低評分？

---

## Stage 3：Olist 機器學習

### 目標

用 Olist 訂單資料練習一般機器學習。

### 任務 1：訂單延遲預測

Label：

```text
order_delivered_customer_date > order_estimated_delivery_date
```

模型：

- Logistic Regression
- Decision Tree
- Random Forest
- XGBoost / LightGBM

評估：

- Accuracy
- Precision
- Recall
- F1-score
- ROC-AUC

### 任務 2：評論好壞預測

Label：

```text
review_score >= 4 → good review
review_score <= 2 → bad review
```

模型：

- Logistic Regression
- Random Forest
- XGBoost / LightGBM

### 任務 3：RFM 顧客分群

RFM：

```text
R = Recency
F = Frequency
M = Monetary
```

方法：

- StandardScaler
- KMeans
- PCA Visualization

---

## Stage 4：Olist Dashboard

### 目標

把商業分析與模型結果做成可以展示的 Dashboard。

### 預計功能

- 總營收
- 總訂單數
- 平均客單價
- 月營收趨勢
- 商品品類排行
- 物流延遲率
- 評論分數分布
- 顧客 RFM 分群
- 延遲預測展示

工具：

```text
Streamlit
Pandas
Plotly
Scikit-learn
```

---

## Stage 5：Retailrocket 使用者行為分析

### 目標

理解推薦系統的行為資料。

### 任務

- 分析 view / addtocart / transaction 數量
- 分析使用者數量
- 分析商品數量
- 找出熱門商品
- 分析事件轉換漏斗

轉換漏斗：

```text
view
↓
addtocart
↓
transaction
```

---

## Stage 6：Retailrocket 推薦系統 Baseline

### 目標

先做最簡單的推薦系統 baseline。

### 推薦策略

- 依 view 次數推薦熱門商品
- 依 addtocart 次數推薦熱門商品
- 依 transaction 次數推薦熱門商品

適用場景：

- 首頁推薦
- 新用戶推薦
- 未登入用戶推薦

---

## Stage 7：其他人也看了

### 目標

建立第一個 Item-to-Item 推薦功能。

### 問題

```text
看過商品 A 的使用者，也常看哪些商品？
```

### 方法

- 過濾 event = view
- 建立 user-item matrix
- 計算商品共現
- 計算 cosine similarity
- 輸出 Top K 商品

### 預計函式

```python
def recommend_also_viewed(item_id: int, top_k: int = 10):
    pass
```

---

## Stage 8：其他人也加入購物車

### 目標

從瀏覽意圖升級到購買意圖。

### 問題

```text
加入購物車商品 A 的使用者，也常加入哪些商品？
```

### 方法

- 過濾 event = addtocart
- 建立 addtocart 共現矩陣
- 輸出相似商品 Top K

### 預計函式

```python
def recommend_also_added_to_cart(item_id: int, top_k: int = 10):
    pass
```

---

## Stage 9：其他人也買了

### 目標

建立經典電商推薦功能。

### 問題

```text
買過商品 A 的使用者，也常買哪些商品？
```

### 方法

- 過濾 event = transaction
- 建立 transaction 共現矩陣
- 過濾過於冷門的商品
- 若交易資料太少，fallback 到 addtocart 或 view

### 預計函式

```python
def recommend_also_bought(item_id: int, top_k: int = 10):
    pass
```

---

## Stage 10：個人化推薦

### 目標

根據使用者歷史行為做推薦。

### 行為權重設計

```text
view = 1
addtocart = 3
transaction = 5
```

### 方法

- 建立 user-item interaction matrix
- 使用 item-based collaborative filtering
- 進階可使用 ALS / LightFM

### 預計函式

```python
def recommend_for_user(visitor_id: int, top_k: int = 10):
    pass
```

---

## Stage 11：FastAPI 推薦 API

### 目標

把推薦系統包成 API。

### 預計 API

```text
GET /api/popular-products
GET /api/recommendations/also-viewed/{item_id}
GET /api/recommendations/also-added/{item_id}
GET /api/recommendations/also-bought/{item_id}
GET /api/recommendations/user/{visitor_id}
```

### 範例 Response

```json
{
  "item_id": 12345,
  "strategy": "also_viewed",
  "recommendations": [
    {
      "item_id": 98765,
      "score": 0.82
    },
    {
      "item_id": 45678,
      "score": 0.76
    }
  ]
}
```

---

## Stage 12：AJAX 前端串接

### 目標

用前端頁面展示推薦結果。

### 預計畫面

- 首頁熱門商品
- 商品詳情頁
- 其他人也看了
- 其他人也加入購物車
- 其他人也買了

### AJAX 範例

```javascript
fetch("/api/recommendations/also-viewed/12345")
  .then(response => response.json())
  .then(data => {
    const container = document.getElementById("also-viewed");
    container.innerHTML = "";

    data.recommendations.forEach(item => {
      const div = document.createElement("div");
      div.innerHTML = `
        <h3>商品 ID：${item.item_id}</h3>
        <p>推薦分數：${item.score}</p>
      `;
      container.appendChild(div);
    });
  });
```

---

## 12. 安裝方式

目前專案仍在開發初期，後續會補上完整安裝流程。

預計安裝方式：

```bash
git clone https://github.com/your-username/smart-ecommerce-recommendation-system.git

cd smart-ecommerce-recommendation-system

python -m venv .venv

source .venv/bin/activate  # macOS / Linux
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

---

## 13. 執行方式

### 13.1 啟動 Jupyter Notebook

```bash
jupyter notebook
```

### 13.2 啟動 FastAPI

```bash
uvicorn api.main:app --reload
```

### 13.3 啟動 Streamlit Dashboard

```bash
streamlit run dashboard/streamlit_app.py
```

---

## 14. 專案進度

| 階段 | 任務 | 狀態 |
|---|---|---|
| Stage 1 | 建立 repo 與資料夾結構 | Not Started |
| Stage 2 | Olist SQL 與 EDA | Not Started |
| Stage 3 | Olist 機器學習 | Not Started |
| Stage 4 | Olist Dashboard | Not Started |
| Stage 5 | Retailrocket EDA | Not Started |
| Stage 6 | 熱門商品推薦 | Not Started |
| Stage 7 | 其他人也看了 | Not Started |
| Stage 8 | 其他人也加入購物車 | Not Started |
| Stage 9 | 其他人也買了 | Not Started |
| Stage 10 | 個人化推薦 | Not Started |
| Stage 11 | FastAPI API | Not Started |
| Stage 12 | AJAX 前端展示 | Not Started |

---

## 15. 預期成果展示

最終希望能展示三個成果：

### 15.1 電商商業分析 Dashboard

- 總營收
- 總訂單數
- 平均客單價
- 商品品類排行
- 物流延遲率
- 評論分數分布
- 顧客分群結果

### 15.2 機器學習預測模型

- 訂單延遲預測
- 評論好壞預測
- 顧客 RFM 分群

### 15.3 商品推薦系統

- 熱門商品推薦
- 其他人也看了
- 其他人也加入購物車
- 其他人也買了
- 個人化推薦
- FastAPI + AJAX 前端展示

---

## 16. License

This project is for learning and portfolio purposes.

Dataset ownership and usage rights belong to the original Kaggle dataset providers. Please follow the license and terms of each dataset on Kaggle.
