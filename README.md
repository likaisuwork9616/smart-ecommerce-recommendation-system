# 電商智慧推薦系統

Smart E-Commerce Recommendation System

本機安裝、啟動與驗證方式請見 [環境建置指南](docs/LOCAL_SETUP.md)。

每次推送 GitHub 都會同步更新本 README，記錄功能、進度與實驗結果；協作規則見 [AGENTS.md](AGENTS.md)。Python 套件安裝於 `.venv/`；MySQL 是獨立服務，放在專案 `.runtime/`，不在 Python 虛擬環境裡。

本專案以電商資料分析與推薦系統為主軸，使用 **Olist Brazilian E-Commerce Dataset** 與 **Retailrocket Recommender System Dataset**，逐步完成從資料匯入、SQL 分析、商業 EDA、機器學習預測、推薦系統，到後續 API 與前端展示的完整資料產品流程。

目前專案已完成：

- Stage 1：Olist 資料認識與環境建立
- Stage 2：Olist SQL 基礎查詢
- Stage 3：Olist 商業分析 EDA 初版
- Stage 4：Olist 訂單延遲預測、多模型回測、月份診斷、多月份驗證及每月重訓

接續可進行：

- Stage 4：跨版本分數校準、提醒量／誤報成本與新期間驗證
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
│   ├── STAGE4_ALERT_OPTIMIZATION.md
│   ├── STAGE4_MONTHLY_DIAGNOSTICS.md
│   ├── STAGE4_WAITING_EXPERIMENT.md
│   ├── STAGE4_MULTIMONTH_VALIDATION.md
│   └── STAGE4_MONTHLY_RETRAINING.md
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
│   ├── delay_route_features.py
│   ├── delay_waiting_split.py
│   ├── delay_multimonth_validation.py
│   ├── delay_rolling_validation.py
│   ├── delay_alert_policy.py
│   ├── train_delay_model.py
│   ├── compare_delay_models.py
│   ├── compare_waiting_strategies.py
│   ├── compare_multimonth_validation.py
│   ├── compare_monthly_retraining.py
│   ├── improve_delay_alerts.py
│   ├── diagnose_delay_errors.py
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

### 月份落差與容易誤報的情況

固定平衡模式 RF 與門檻 0.453508，檢查同一批已看過的保留資料。本次新增診斷程式、逐月與八維分群報告，沒有重新訓練或修改提醒規則；以下是**回溯診斷，不是新的獨立測試或改善成績**。

| 核准期間 | 訂單數 | 誤報 FP | FPR：FP／準時數 | 抓到 TP | 漏掉 FN | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2018-06 | 6,094 | 427 | 7.09% | 21 | 50 | 29.58% |
| 2018-07 | 6,021 | 982 | 16.85% | 55 | 138 | 28.50% |
| 2018-08-01～29 | 6,495 | 985 | 16.18% | 76 | 330 | 18.72% |

另有 5 月 26～31 日的 770 單、7 張誤報、兩張延遲皆漏掉；5、8 月不是完整月份。6、7 月單量接近，誤報率卻明顯上升。

- **跨州路線是優先檢查對象**：SP → RJ 誤報 556／1,313 張準時單（FPR 42.35%），占全部誤報 23.16%；SP → SC 為 223／373（59.79%）。路線方向是主賣家州到顧客州，兩者在不同月份也反覆誤報。全部商品均跨州的 FPR 18.11%，同州為 4.90%；不能直接停掉跨州提醒，因為它也抓到 100 張延遲。
- **承諾與資料組成持續改變**：6→8 月平均承諾由 28.06 降至 15.38 天，已完成訂單的實際平均配送由 8.91 降至 7.39 天；延遲率上升不能直接解讀成配送變慢。22～30 天承諾群誤報最多（928 張），不是只有最短承諾容易誤報。
- **成熟標籤有明顯取樣偏差**：validation 的 5 月 1～25 日原有 452 張延遲，截止前可用的只剩 27 張；最終 validation 的延遲樣本有 82.72% 來自 3 月，合計 recall 達 30% 不代表逐月達標。

完整 6、7 月在共同「顧客州 × 承諾區間」固定組成後，FPR 為 8.06%／9.65%，共同樣本涵蓋各月準時單 84.36%／76.75%。族群組成與差距有關，但仍不能解釋全部；這是部分樣本的描述性比較，不是因果估計。新賣家與高運費分群的差異較小，尚不足以當作主要原因。

![Monthly false alerts](reports/images/stage4_monthly_errors.png)
![False-positive groups](reports/images/stage4_false_positive_groups.png)

完整分母、部分月份、小樣本、標籤篩選與後續實驗設計見 [月份誤報診斷](docs/STAGE4_MONTHLY_DIAGNOSTICS.md)。本輪先完成問題定位，保留現有模型與門檻。

### 等待期與路線承諾特徵實驗

已完成 24 次訓練：train／validation 都保留 **30 或 60 天等待期**，比較 Random Forest／Logistic Regression 的原 21 欄與新增路線承諾特徵（共 30 欄）。**60 天在執行前指定為主要方案，30 天是敏感度比較**；同一等待期內只依 validation 至少 30% recall、提醒量最少來選模型與門檻。

60 天讓有效已送達 cohort 的 validation 延遲樣本保留率達 **98.31%／98.40%／95.05%**；30 天為 84.07%／82.75%／66.09%。等待讓更多慢件取得答案，但 train／validation 也更舊，不能把方法差異全歸因於等待天數。未送達、取消及無效時間訂單另列原始分母，不當作準時。

下表沿用已檢視的 2017-12、2018-02、2018-04 開發月份，同一批 18,833 單／1,642 張延遲。**這是開發回測；原 2018-05-26 起保留資料本輪不評估。**

| 等待／RF 特徵 | 誤報 FP | 抓到 TP | 漏掉 FN | Recall |
| --- | ---: | ---: | ---: | ---: |
| 舊 RF／平衡（背景對照） | 7,712 | 1,099 | 543 | 66.93% |
| 30 天／原特徵 | 2,954 | 565 | 1,077 | 34.41% |
| 30 天／路線承諾 | 2,887 | 710 | 932 | 43.24% |
| 60 天／原特徵 | 4,854 | 713 | 929 | 43.42% |
| 60 天／路線承諾 | 3,434 | 659 | 983 | 40.13% |

相同 30 天 RF 下，路線特徵**少 67 張誤報、多抓 145 張延遲**，但最低月份 recall 仍只有 16.14%。相同 60 天 RF 則少 1,420 張誤報，同時少抓 54 張延遲。60 天三個 fold 都依 validation 選中 RF／路線承諾，2017-12 recall 卻僅 **4.04%**；驗證標籤更完整，沒有保證後續月份表現穩定。

新特徵包含有向州別路線、近 90 天配送中位數／第 90 百分位、承諾相對分位的差值／比例及歷史 CDF。送達 timestamp 必須嚴格早於當前核准時間，配送天數採日曆尺度；當月前幾天已完成的配送可更新後續訂單歷史，不用未來答案。

分群仍有代價：60 天 RF 的顧客 SP 誤報由 2,409 降至 1,065，但漏報由 172 增至 256；SP → RJ 誤報反而由 463 增至 532，同時抓到延遲由 176 增至 227。因此不自動取代預設模型，六份研究 artifact 獨立存於 `models/research/`，需以 `--model` 明確載入。完整十策略、逐月取捨及操作見 [等待期實驗](docs/STAGE4_WAITING_EXPERIMENT.md)。

![Waiting-period experiment](reports/images/stage4_waiting_tradeoff.png)

圖中 30／60 天採逐 fold validation 選出的候選；30 天第一個 fold 選 Logistic，因此與上表固定 RF 的數字不同。

### 多月份驗證

已完成 **12 次訓練**：固定至少 60 天等待，取連續三個完整日曆月驗證，沿用 RF／Logistic 的原特徵／路線特徵四個候選。每個 fold 的模型在最早驗證月開始時訓練一次，三種策略共用同一模型與分數：只用最新月選門檻與模型、三月合計 recall ≥30%、以及預先指定的主策略「每月 recall 都 ≥30%」。後兩種策略的選模都使用全三月提醒量，公平比較月度限制。

驗證月份分別為 2017-07～09、2017-09～11、2017-10～12，逐月延遲標籤保留率為 98.36%～100%（限有效已送達 cohort）。完整月份對齊後實際等待 61／62／90 天；train 則只保留 7,517／14,284／18,089 張，較舊單月方案更少、更舊。舊實驗僅作背景，不能把差異全歸因於多月份。

以下是三種策略各自依 validation 選模，在同一批 18,833 張訂單的**開發回測**：

| 驗證策略 | 誤報 FP | 抓到 TP | 漏掉 FN | Precision | Recall | 最差驗證月 Recall | 最差回測月 Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 只看最新月 | 3,974 | 589 | 1,053 | 12.91% | 35.87% | 12.50% | 10.09% |
| 三月合計達標 | 3,293 | 563 | 1,079 | 14.60% | 34.29% | 18.33% | 16.37% |
| **每月都達標（主策略）** | **5,728** | **609** | **1,033** | **9.61%** | **37.09%** | **30.00%** | **8.07%** |

逐月限制比三月合計**多抓 46 張延遲，卻多 2,435 張誤報**，沒有達成減少誤報的目標。2017-12 主策略改選 Logistic／路線，抓到 36／446 張（8.07%），低於三月合計選中的 Logistic／原特徵 73／446 張（16.37%）；2018-04 則改選 RF／原特徵，誤報達 4,455 張。固定候選下，降低共同門檻會同時增加或維持 TP 與 FP；選模改變後，後續月份可能反而少抓延遲。

每個驗證月達標仍不能保證後續月份達標，這次沒有自動提升研究模型。三份模型另存 `models/research/olist_delay_multimonth_{month}.joblib`，以 `--model` 載入。本輪不評估原 holdout；早期 evaluation 在後續 fold 成為 validation 是合法滾動開發回測，不能當獨立未知測試。完整 15 種候選／策略、逐月結果與操作見 [多月份驗證](docs/STAGE4_MULTIMONTH_VALIDATION.md)。

![多月份驗證的誤報與召回取捨](reports/images/stage4_multimonth_validation.png)

### 每月重訓的滾動驗證

已完成 **32 次訓練**：重播 2017-07～12、2018-02、2018-04 八個必要月份，各訓練 RF／Logistic × 原特徵／路線特徵四個候選。每月 M 第一日只使用核准 `<M−60天`、結果 `<M` 的訂單，為 M 月留下真正 out-of-time 分數。Evaluation 仍是原三個開發月，並非連續所有月份的部署測試。

E 時以三個成熟歷史月份各自舊版模型的分數決定門檻與候選，再由 E 當天新訓練的模型預測。最終模型雖已訓練到歷史 validation 訂單，**沒有拿最終模型重算它們的驗證分數**；同一歷史月在不同 E 仍重新篩 `label_available_time < E`，避免快取過早刪掉慢件。

最終 train 增加到 **26,431／38,522／50,358 張**（前次固定模型為 7,517／14,284／18,089 張）。以下在同一批 18,833 張訂單、1,642 張延遲比較；全部是**已檢視月份的開發回測**，本輪沒有評估原 holdout。

| 方案 | 誤報 FP | 抓到 TP | 漏掉 FN | Precision | Recall | 最差回測月 Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 前次固定模型／每月達標（背景） | 5,728 | 609 | 1,033 | 9.61% | 37.09% | 8.07% |
| 滾動／最新月 | 6,923 | 1,008 | 634 | 12.71% | 61.39% | 8.74% |
| 滾動／三月合計 | 6,449 | 986 | 656 | 13.26% | 60.05% | 6.05% |
| **滾動／每月達標（預先指定主策略）** | **7,957** | **1,050** | **592** | **11.66%** | **63.95%** | **13.45%** |

主策略比前次固定模型**多抓 441 張延遲，也多 2,229 張誤報**；相對本次滾動／三月合計則多抓 64 張、多 1,508 張誤報，沒有達成減少誤報的目標。主策略三月 recall 為 **13.45%／78.43%／95.42%**，2018-04 單月誤報 **4,868 張**，仍未達成月份穩定性。前後比較同時改變最終 train 新近程度及 validation 模型版本，不能解釋為單一因素的因果效果。

跨版本的原始分數尚未校準。以 2017-12 選中的 Logistic／原特徵為例，三個歷史月各自達 30% 的門檻為 0.74806／0.48004／0.54743，共同門檻 0.48004；後續十二月仍只抓到 60／446 張。報告記錄各月及 evaluation 的分數分位，作為轉移診斷，不能直接將差異歸因於未校準或單一特徵。主策略每個歷史驗證月都達 30%，仍不保證新模型月份達標。

三份可推論研究模型另存 `models/research/olist_delay_rolling_{month}.joblib`，只以 `--model` 明確載入；32 份內部月份版本另存 `rolling_versions/` 供重現，不含提醒門檻。未自動替換預設模型。完整方法、15 種候選／策略與操作見 [每月重訓實驗](docs/STAGE4_MONTHLY_RETRAINING.md)。

![每月重訓的資料量、誤報與召回](reports/images/stage4_monthly_retraining.png)

在專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe scripts\train_delay_model.py
.\.venv\Scripts\python.exe scripts\compare_delay_models.py --n-jobs 4
.\.venv\Scripts\python.exe scripts\improve_delay_alerts.py --min-recall 0.30 --n-jobs 4
.\.venv\Scripts\python.exe scripts\diagnose_delay_errors.py
.\.venv\Scripts\python.exe scripts\compare_waiting_strategies.py --n-jobs 4
.\.venv\Scripts\python.exe scripts\compare_multimonth_validation.py --n-jobs 4
.\.venv\Scripts\python.exe scripts\compare_monthly_retraining.py --n-jobs 4
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
- [月份落差與誤報診斷說明](docs/STAGE4_MONTHLY_DIAGNOSTICS.md)
- [逐月、分群與標籤偏差完整結果](reports/stage4/monthly_error_diagnostics.json)
- [等待期與路線承諾實驗方法](docs/STAGE4_WAITING_EXPERIMENT.md)
- [等待期完整回測結果](reports/stage4/waiting_strategy_comparison.json)
- [多月份驗證方法與限制](docs/STAGE4_MULTIMONTH_VALIDATION.md)
- [多月份完整回測結果](reports/stage4/multimonth_validation.json)
- [每月重訓的滾動驗證方法](docs/STAGE4_MONTHLY_RETRAINING.md)
- [每月重訓完整結果](reports/stage4/monthly_retraining.json)

前次多模型比較完成 21 次訓練、誤報改善 16 次、等待期與路線承諾比較 24 次、多月份驗證 12 次；本次每月重訓完成 32 次。合計 **122 項自動測試通過**，32 份月份模型重載後重算 170,516 筆全月分數，全部 256,124 列 validation／evaluation 分數、36 組門檻、15 組彙總及 360 組群組結果獨立核對通過；三份最終研究模型重載吻合，36 份既有模型、報告及圖表雜湊不變。Notebook 的可選唯讀摘要已更新，16 個程式區塊完整執行通過。

## 下一步規劃

Stage 5 原定進行評論好壞預測。Stage 4 已完成每月重訓：抓到更多延遲，但誤報也增加，跨版本共用分數門檻仍不穩定。若繼續改善，應先在歷史 train／validation 內評估分數校準及提醒量／誤報成本限制，再另留新期間驗證。現有月份已用於開發，不能拿來選規則後宣稱未知資料效果。也可進入 Stage 5，先定義評論預測時點與低評分 label。

---

## 目前專案狀態

```text
Stage 1：Olist 資料認識與環境建立       ✅ 已完成
Stage 2：Olist SQL 基礎查詢             ✅ 已完成
Stage 3：Olist 商業分析 EDA             ✅ 初版完成
Stage 4：訂單是否延遲預測               ✅ 多模型、多月份驗證及每月重訓完成
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
