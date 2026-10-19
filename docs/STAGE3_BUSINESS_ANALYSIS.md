# Stage 3：Olist商業分析

來源為[商業分析Notebook](../notebooks/03_olist_business_analysis.ipynb)及[商業SQL](../sql/03_business_analysis.sql)，以下保留原本八張EDA成果。圖表是已產出的歷史分析，本次清整沒有重跑資料庫或重算圖表。

### 1. 每月訂單數趨勢

![Monthly Order Count](../reports/images/olist_monthly_order_count.png)

用每月訂單量觀察成長、季節波動與異常月份，並與營收、平均客單價一起比較需求與交易規模。

---

### 2. 每月營收趨勢

![Monthly Revenue](../reports/images/olist_monthly_revenue.png)

將每月營收與訂單量對照：兩者同步上升表示交易規模擴大；訂單增多但營收未同步增加，則可進一步檢查客單價。

---

### 3. Top 10 商品品類營收

![Top 10 Product Categories by Revenue](../reports/images/olist_top10_categories_revenue.png)

檢查收入是否集中於少數品類，作為後續分析庫存、廣告與推薦曝光的入口；還可對照各品類的訂單數、平均售價、運費與評論。

---

### 4. 付款方式分布

![Payment Type Distribution](../reports/images/olist_payment_type_distribution.png)

觀察付款方式分布，供後續檢查結帳流程、分期使用及付款失敗情況。

---

### 5. 評論分數分布

![Review Score Distribution](../reports/images/olist_review_score_distribution.png)

以評分分布初步觀察顧客滿意度，也作為後續Stage 5評論預測的分析基礎。

---

### 6. 物流配送天數分布

![Delivery Days Distribution](../reports/images/olist_delivery_days_distribution.png)

觀察從下單到送達的耗時及極端案例，後續可再查配送速度與評論、取消情況的關係。

---

### 7. 延遲訂單比例

![Delayed Orders](../reports/images/olist_delayed_orders.png)

計算晚於預估時間送達的比例。Stage 3下列公式比較完整timestamp；Stage 4改為比較日曆日期，預估當日送達算準時，兩者延遲率不能直接混用。

Stage 3 的延遲定義：

```text
order_delivered_customer_date > order_estimated_delivery_date
→ delayed = 1

否則
→ delayed = 0
```

---

### 8. 各州顧客訂單分布

![Customer State Order Count](../reports/images/olist_customer_state_order_count.png)

觀察顧客訂單集中在哪些州，作為後續分析倉儲、區域行銷與跨州配送的入口。

---

## 查詢口徑

月訂單量及地區分布只計最終已送達訂單；月份營收與平均客單價使用商品價加運費，品類營收使用商品價。付款分布計付款紀錄、評論分布計評論紀錄，不能直接當作互斥的訂單分組。詳細JOIN與篩選條件以[商業SQL](../sql/03_business_analysis.sql)及Notebook為準。

這些圖表提供後續分析方向，沒有驗證調整庫存、行銷或配送策略的實際效果。延遲模型的核准時點、標記與回測另見[Stage 4方法](STAGE4_DELAY_PREDICTION.md)。

---
