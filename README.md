# 電商智慧推薦系統

Smart E-Commerce Recommendation System

本機安裝、啟動與驗證方式請見 [環境建置指南](docs/LOCAL_SETUP.md)。

每次推送 GitHub 都會同步更新本 README，記錄功能、進度與實驗結果；協作規則見 [AGENTS.md](AGENTS.md)。Python 套件安裝於 `.venv/`；MySQL 是獨立服務，放在專案 `.runtime/`，不在 Python 虛擬環境裡。

本專案以電商資料分析與推薦系統為主軸，使用 **Olist Brazilian E-Commerce Dataset** 與 **Retailrocket Recommender System Dataset**，逐步完成從資料匯入、SQL 分析、商業 EDA、機器學習預測、推薦系統，到後續 API 與前端展示的完整資料產品流程。

目前專案已完成：

- Stage 1：Olist 資料認識與環境建立
- Stage 2：Olist SQL 基礎查詢
- Stage 3：Olist 商業分析 EDA 初版
- Stage 4：Olist 訂單延遲預測、6 種模型時間回測比較與誤報改善

下一步將進入：

- Stage 5：Olist 評論好壞預測

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

Olist 資料集主要用於電商訂單與商業分析。

適合分析：

- 訂單數趨勢
- 營收趨勢
- 商品品類營收
- 付款方式分布
- 評論分數分布
- 物流配送天數
- 延遲訂單比例
- 顧客地區分布
- 後續延遲預測與評論預測模型

### 2. Retailrocket Recommender System Dataset

Retailrocket 資料集主要用於推薦系統與使用者行為分析。

適合分析：

- 商品瀏覽行為
- 加入購物車行為
- 購買行為
- 熱門商品推薦
- Item-to-Item 推薦
- 個人化推薦系統
- 推薦 API 串接

---

## 目前專案資料夾結構

目前已包含 Olist SQL、商業 EDA 與訂單延遲預測。後續進入推薦系統與 API 階段時，再逐步新增對應資料夾；下列 `.venv/`、`.runtime/`、原始資料與模型僅保留在本機。

```text
smart-ecommerce-recommendation-system/
│
├── README.md
├── AGENTS.md
├── requirements.txt
├── requirements-lock.txt
├── .gitignore
├── .venv/                         # 本機 Python 套件
├── .runtime/                      # 本機 MySQL、DBeaver 與執行狀態
├── models/                        # 本機模型 artifact
│
├── data/
│   ├── README.md
│   ├── raw/
│   │   ├── olist/
│   │   └── retailrocket/
│   ├── processed/
│   └── sample/
│
├── docs/
│   ├── olist_core_erd.png
│   ├── LOCAL_SETUP.md
│   ├── STAGE4_DELAY_PREDICTION.md
│   └── STAGE4_ALERT_OPTIMIZATION.md
│
├── notebooks/
│   ├── 01_olist_data_overview.ipynb
│   ├── 02_olist_sql_analysis.ipynb
│   ├── 03_olist_business_analysis.ipynb
│   └── 04_olist_delay_prediction.ipynb
│
├── reports/
│   ├── stage4/                    # 固定測試與模型回測指標
│   └── images/                    # EDA 與 Stage 4 圖表
│
├── scripts/
│   ├── load_olist_to_mysql.py
│   ├── db_config.py
│   ├── db_config_example.py
│   ├── delay_features.py
│   ├── delay_history_features.py
│   ├── delay_alert_policy.py
│   ├── train_delay_model.py
│   ├── compare_delay_models.py
│   ├── improve_delay_alerts.py
│   ├── predict_delay.py
│   ├── setup_local_mysql.py
│   ├── start_mysql.ps1
│   ├── stop_mysql.ps1
│   ├── start_jupyter.ps1
│   ├── start_dbeaver.ps1
│   └── verify_environment.py
│
├── tests/                         # 特徵、時間切分與模型比較檢查
│
└── sql/
    ├── 01_create_database.sql
    ├── 02_basic_check.sql
    └── 03_business_analysis.sql
```

---

## 資料夾說明

| 資料夾 / 檔案 | 說明 |
|---|---|
| `data/raw/olist/` | Olist 原始 CSV 資料 |
| `data/raw/retailrocket/` | Retailrocket 原始資料 |
| `docs/` | 本機環境、Stage 4 方法說明與 Olist 核心 ERD |
| `notebooks/` | Jupyter Notebook 分析流程 |
| `reports/stage4/` | 模型評估指標、時間回測比較與資料版本 |
| `reports/images/` | EDA 與模型評估圖表 |
| `scripts/` | 資料匯入、環境啟動、特徵建置、模型訓練與推論 |
| `tests/` | 資料聚合、標記與避免時間洩漏的自動檢查 |
| `sql/` | MySQL 建表、檢查與商業分析 SQL |
| `requirements.txt` | Python 套件需求 |
| `requirements-lock.txt` | 本機 Python 3.12／Windows 套件鎖定版本 |
| `.gitignore` | Git 忽略規則 |

---

## 目前完成進度

### Stage 1：Olist 資料認識與環境建立

已完成：

- 下載 Olist 資料集
- 建立專案資料夾結構
- 整理原始資料放置位置
- 使用 Python 載入 CSV
- 匯入 Olist 資料到 MySQL
- 使用 DBeaver 檢查資料表
- 建立初步 ERD 圖
- 理解主要資料表之間的關係

主要資料表：

- `orders`
- `order_items`
- `order_payments`
- `order_reviews`
- `customers`
- `products`
- `sellers`
- `geolocation`
- `product_category_name_translation`

ERD 圖位置：

```text
docs/olist_core_erd.png
```

---

### Stage 2：Olist SQL 基礎分析

已完成：

- 查詢總訂單數
- 查詢各訂單狀態數量
- 查詢銷售額最高商品
- 查詢商品品類營收
- 計算平均客單價 AOV
- 練習多表 JOIN
- 使用 Notebook 執行 SQL 查詢
- 將 SQL 分析整理於 `02_olist_sql_analysis.ipynb`

相關檔案：

```text
notebooks/02_olist_sql_analysis.ipynb
sql/02_basic_check.sql
```

---

### Stage 3：Olist 商業分析 EDA

目前 Stage 3 已完成 EDA 初版。

主要 Notebook：

```text
notebooks/03_olist_business_analysis.ipynb
```

SQL 查詢整理：

```text
sql/03_business_analysis.sql
```

EDA 圖表輸出位置：

```text
reports/images/
```

本階段完成以下分析：

- 每月訂單數趨勢
- 每月營收趨勢
- Top 10 商品品類營收
- 付款方式分布
- 評論分數分布
- 物流配送天數分布
- 延遲訂單比例
- 各州顧客訂單分布

---

## Stage 3：EDA 成果展示

### 1. 每月訂單數趨勢

![Monthly Order Count](reports/images/olist_monthly_order_count.png)

分析目的：

觀察 Olist 平台每月訂單量變化，判斷平台交易量是否有成長趨勢、季節性波動或異常月份。

商業意義：

訂單數可以反映平台需求變化，但需要與營收與平均客單價一起比較，才能判斷成長品質。

---

### 2. 每月營收趨勢

![Monthly Revenue](reports/images/olist_monthly_revenue.png)

分析目的：

觀察每月營收變化，並與每月訂單數趨勢互相比較。

商業意義：

若營收與訂單數同步上升，代表交易規模擴大；若訂單數上升但營收沒有同步增加，可能代表客單價下降。

---

### 3. Top 10 商品品類營收

![Top 10 Product Categories by Revenue](reports/images/olist_top10_categories_revenue.png)

分析目的：

找出平台主要營收來源品類，判斷營收是否集中在少數商品類別。

商業意義：

高營收品類可以作為平台重點經營方向，例如加強庫存、廣告投放與推薦曝光。

---

### 4. 付款方式分布

![Payment Type Distribution](reports/images/olist_payment_type_distribution.png)

分析目的：

了解顧客主要使用哪些付款方式。

商業意義：

付款方式會影響結帳流程設計、分期付款策略與付款失敗風險管理。

---

### 5. 評論分數分布

![Review Score Distribution](reports/images/olist_review_score_distribution.png)

分析目的：

觀察顧客評價分布，了解整體滿意度狀況。

商業意義：

評論分數可作為顧客體驗指標，也能作為後續 Stage 5 評論好壞預測模型的基礎。

---

### 6. 物流配送天數分布

![Delivery Days Distribution](reports/images/olist_delivery_days_distribution.png)

分析目的：

了解訂單從下單到實際送達所需天數，觀察是否存在極端延遲案例。

商業意義：

配送速度是電商顧客體驗的重要因素，配送時間過長可能造成差評或取消訂單。

---

### 7. 延遲訂單比例

![Delayed Orders](reports/images/olist_delayed_orders.png)

分析目的：

計算有多少訂單晚於預估送達日期。

商業意義：

延遲訂單比例是 Stage 4「訂單是否延遲預測」的分析基礎。Stage 3 下列公式比較完整 timestamp；Stage 4 改為比較日曆日期，預估當日送達算準時，不能直接沿用兩者的延遲率。

Stage 3 的延遲定義：

```text
order_delivered_customer_date > order_estimated_delivery_date
→ delayed = 1

否則
→ delayed = 0
```

---

### 8. 各州顧客訂單分布

![Customer State Order Count](reports/images/olist_customer_state_order_count.png)

分析目的：

了解 Olist 顧客訂單主要集中在哪些州。

商業意義：

高訂單州別可以作為物流倉儲、行銷投放與區域營運策略的重要依據。

---

## Stage 3 商業洞察總結

透過本階段 EDA，可以初步掌握 Olist 平台的營運狀況：

1. **訂單與營收趨勢**  
   每月訂單數與每月營收可以用來判斷平台整體交易規模是否穩定成長。

2. **商品品類營收集中度**  
   Top 10 商品品類營收可以看出平台主要收入來源，後續可以進一步分析各品類的訂單數、平均售價、運費與評論表現。

3. **付款方式偏好**  
   付款方式分布可以反映顧客的結帳習慣，協助後續優化付款流程與分期付款策略。

4. **顧客滿意度**  
   評論分數分布可以作為顧客滿意度的初步指標，後續可延伸為評論好壞預測模型。

5. **物流配送效率**  
   配送天數分布與延遲訂單比例可以用來衡量物流效率，是後續延遲預測模型的核心分析方向。

6. **地區需求分布**  
   各州顧客訂單分布可以看出市場需求集中區域，後續可進一步分析跨州配送是否影響配送天數與延遲率。

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

## 使用技術

目前已使用：

- Python
- Pandas
- Matplotlib
- SQLAlchemy
- PyMySQL
- MySQL
- DBeaver
- Jupyter Notebook
- Scikit-learn
- Joblib
- XGBoost / LightGBM
- Git / GitHub

後續預計使用：

- Streamlit
- FastAPI
- JavaScript
- AJAX

---

## Stage 4：訂單是否延遲預測

已完成每訂單一列的 21 個特徵、延遲標記、缺值處理、類別編碼、時間切分、模型比較、門檻選擇、保留資料評估與本機推論。目前預設推論模型仍為 **Random Forest**；新增 6 種模型的開發時間回測，與原版固定測試分開呈現。

### 原版固定測試結果

- **預測時點**：訂單／付款核准時 `order_approved_at`。
- **標記定義**：實際送達的日曆日期晚於預估日期才算延遲；預估當日送達算準時。Stage 3 使用完整 timestamp，因此兩階段延遲率口徑不同。
- **可用資料**：96,394 張時間完整且合理的已送達訂單，6,532 張延遲（6.78%）。實際配送時間、最終狀態、評論及 ID 不進模型。
- **切分方法**：依核准日期建立約 60%／20%／20% 的 train／validation／test，同一天不跨組；排除在下一區間起點尚未送達的 train／validation 標籤。
- **選模方法**：只用 train 學習補值、編碼與模型；依 validation AP 選模型，再依 validation F1 選門檻，最後固定模型與門檻評估 test。

| 區段 | 核准日期 | 成熟標籤篩選後筆數 | 延遲比例 |
| --- | --- | ---: | ---: |
| Train | 2016-09-15 至 2018-03-02 | 54,145 | 5.06% |
| Validation | 2018-03-03 至 2018-05-25 | 17,356 | 8.30% |
| Test | 2018-05-26 至 2018-08-29 | 19,380 | 3.47% |

Validation AP：Dummy 0.0830、Logistic Regression 0.1511、Random Forest 0.1593。選定 **Random Forest**，決策門檻 **0.450103**。

| Test 指標 | Random Forest | 全猜準時基準 |
| --- | ---: | ---: |
| Average Precision | 0.0568 | 0.0347 |
| ROC-AUC | 0.6690 | 0.5000 |
| Precision | 5.69% | 0.00% |
| Recall | 23.07% | 0.00% |
| F1 | 0.0912 | 0.0000 |
| Balanced accuracy | 54.66% | 50.00% |
| Accuracy | 84.07% | 96.53% |

模型抓到 672 張延遲訂單中的 155 張，但產生 2,571 張誤報。排序能力高於基準，誤報與漏報仍多；這是可重現的第一版離線模型，尚未達到可直接自動處置訂單的品質。期間延遲率有明顯變化，成熟標籤篩選也會偏向保留較快送達的訂單，詳見方法文件。

Validation permutation importance 顯示模型較依賴顧客州別、運費、跨州比例、預估配送天數與賣家州別；這是模型依賴程度，不能解讀成延遲的因果因素。模型分數未經機率校準。

![Validation model comparison](reports/images/stage4_validation_model_comparison.png)
![Test precision-recall curve](reports/images/stage4_test_precision_recall.png)
![Test confusion matrix](reports/images/stage4_test_confusion_matrix.png)
![Validation feature importance](reports/images/stage4_validation_permutation_importance.png)

### 新增：6 種模型的時間回測比較

使用同一套 21 欄特徵，比較 Logistic Regression、Random Forest、Extra Trees、HistGradientBoosting、XGBoost、LightGBM，另外保留全猜準時的 Dummy 基準。XGBoost 3.4.1 與 LightGBM 4.7.0 已安裝於 `.venv/`，版本記錄在 `requirements-lock.txt`。

三組 evaluation 分別是 **2017-12、2018-02、2018-04**；validation 分別是 2017-10、2017-12、2018-02，中間各留一個月等待配送結果。每組只用更早且標籤已成熟的 train 訓練，門檻只依 validation F1 選擇。原版 test 訂單不參與比較，原模型與原 test 報告保留。

以下是實際回測的 AP（Average Precision，衡量延遲訂單的排序能力，越高越好，並非 accuracy）。三個月份等權平均；標準差描述月份差異，不是信賴區間。

| 模型 | 2017-12 AP | 2018-02 AP | 2018-04 AP | 平均 AP | AP 標準差 |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Logistic Regression** | **0.1085** | 0.2074 | **0.1420** | **0.1526** | 0.0411 |
| Random Forest | 0.0834 | 0.2067 | 0.1202 | 0.1368 | 0.0517 |
| Extra Trees | 0.0799 | 0.2060 | 0.1225 | 0.1361 | 0.0524 |
| XGBoost | 0.0809 | 0.2111 | 0.1155 | 0.1358 | 0.0551 |
| LightGBM | 0.0770 | **0.2150** | 0.1090 | 0.1337 | 0.0590 |
| HistGradientBoosting | 0.0779 | 0.2000 | 0.0921 | 0.1233 | 0.0545 |
| Dummy：全猜準時 | 0.0786 | 0.1362 | 0.0462 | 0.0870 | 0.0372 |

| 模型 | 平均 ROC-AUC | 平均 F1 | 平均 Recall | 平均 Precision |
| --- | ---: | ---: | ---: | ---: |
| Logistic Regression | 0.6590 | 0.1763 | 54.49% | 13.50% |
| Random Forest | 0.6349 | 0.1727 | 63.71% | 10.16% |
| Extra Trees | 0.6339 | 0.1667 | 57.10% | 10.36% |
| XGBoost | 0.6180 | 0.1338 | 64.13% | 8.21% |
| LightGBM | 0.6110 | 0.1439 | 65.64% | 8.48% |
| HistGradientBoosting | 0.5950 | 0.1389 | 60.94% | 8.69% |

**本設定下，Logistic Regression 的平均 AP、F1 與 precision 最高；LightGBM 在 2018-02 單月的 AP 最高。** 新增的樹模型沒有穩定勝過 Random Forest。月份差異明顯，延遲比例依序為 7.86%、13.62%、4.62%；各模型仍有大量誤報，門檻也受成熟標籤篩選影響。

這是開發回測排名，不能當成新模型在未知最終測試集上的成績，也不能與前表原版 test 直接比較。評估使用事後已送達結果，部分標籤在原 test 起點後才可觀察。目前預設推論仍用原版 Random Forest；後續可優先驗證 Logistic Regression，並改善特徵與門檻成本。完整切分、排除筆數與限制見 [Stage 4 方法文件](docs/STAGE4_DELAY_PREDICTION.md)。

![Three-window development model comparison](reports/images/stage4_backtest_model_comparison.png)

### 誤報改善：平衡模式

依使用者指定，改為 **validation 至少抓到 30% 延遲，再選提醒量最少的模型與門檻**。實測 RF／Logistic 的原特徵與近 90 天配送歷史特徵，共 4 候選；歷史結果嚴格限制在該訂單核准前已送達者。

最終仍選 **原特徵 Random Forest**，門檻由 0.450103 改為 **0.453508**，validation 召回為 **30.05%**。新增歷史特徵沒有改善這次的誤報，因此沒有採用。

已檢視保留資料的回溯診斷（不是新的獨立測試）：

| 指標 | 原版 | 平衡模式 |
| --- | ---: | ---: |
| 誤報 FP | 2,571 | **2,401** |
| 抓到延遲 TP | 155 | 152 |
| 漏掉延遲 FN | 517 | 520 |
| Precision | 5.69% | 5.95% |
| Recall | 23.07% | 22.62% |

誤報少 **170 張（6.61%）**，代價是少抓 **3 張**延遲訂單。這是小幅改善，仍有大量誤報。原特徵 RF 在三組開發回測合計的誤報由 8,825 降至 7,712（減少 12.61%），抓到延遲由 1,183 降至 1,099。

逐月自動選模的實驗方案有一個月份召回僅 1.12%，平衡 RF 也有月份低於 30%；因此**保留原版預設**，新門檻以 `--profile balanced` 明確選用，不能保證未來召回率。完整候選、月份差異與限制見 [誤報改善說明](docs/STAGE4_ALERT_OPTIMIZATION.md)。

![False alerts and recall trade-off](reports/images/stage4_alert_tradeoff.png)

在專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe scripts\train_delay_model.py
.\.venv\Scripts\python.exe scripts\compare_delay_models.py --n-jobs 4
.\.venv\Scripts\python.exe scripts\improve_delay_alerts.py --min-recall 0.30 --n-jobs 4
.\.venv\Scripts\python.exe scripts\predict_delay.py --order-id e481f51cbdc54678b7cc49136f2d6af7
.\.venv\Scripts\python.exe scripts\predict_delay.py --profile balanced --order-id e481f51cbdc54678b7cc49136f2d6af7
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

本階段直接讀 CSV，不需要 MySQL。原模型存於 `models/olist_delay_model.joblib`，平衡模型獨立存於 `models/olist_delay_balanced.joblib`，資料與逐筆預測存於 `data/processed/`，均由 Git 忽略；GitHub 保留程式、Notebook、指標與圖表，模型可依指令重建。

- [Stage 4 教學 Notebook](notebooks/04_olist_delay_prediction.ipynb)
- [特徵、標記、限制與推論說明](docs/STAGE4_DELAY_PREDICTION.md)
- [完整實驗指標及資料版本](reports/stage4/metrics.json)
- [多模型開發回測完整結果](reports/stage4/model_comparison.json)
- [誤報改善方法與平衡模式操作](docs/STAGE4_ALERT_OPTIMIZATION.md)
- [誤報改善完整結果](reports/stage4/alert_optimization.json)

前次多模型比較完成 21 次訓練；本次誤報改善完成 16 次候選訓練、43 項自動測試與 19,380 筆模型重載驗證。更新後 Notebook 的 12 個程式區塊完整執行通過。

## 下一步規劃

Stage 5 原定進行評論好壞預測。Stage 4 已完成歷史特徵實驗與平衡模式；接下來若繼續改善，應優先處理月份間分布漂移與慢件尚未完成造成的標籤偏差，再用新期間資料驗證。也可進入 Stage 5，先定義評論預測時點與低評分 label。

---

## 目前專案狀態

```text
Stage 1：Olist 資料認識與環境建立       ✅ 已完成
Stage 2：Olist SQL 基礎查詢             ✅ 已完成
Stage 3：Olist 商業分析 EDA             ✅ 初版完成
Stage 4：訂單是否延遲預測               ✅ 多模型回測與平衡模式完成
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
