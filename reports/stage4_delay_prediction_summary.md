# Stage 4：Olist 訂單延遲預測結果

## 資料與切分

- 可用已送達訂單：96,470
- 整體延遲率：8.11%
- 訓練集：77,176 筆（較早的 80% 訂單）
- 測試集：19,294 筆（較新的 20% 訂單）
- 測試集延遲率：5.29%（Average Precision 的隨機基準）
- 所有特徵皆為下單時可取得資訊；實際送達日期只用於建立標籤。

## 模型比較

| model | accuracy | precision | recall | f1 | roc_auc | average_precision |
| --- | --- | --- | --- | --- | --- | --- |
| Logistic Regression | 0.8673 | 0.1080 | 0.2076 | 0.1421 | 0.7217 | 0.1180 |
| Decision Tree | 0.7732 | 0.1000 | 0.4104 | 0.1608 | 0.6349 | 0.0892 |
| Random Forest | 0.9469 | 0.3000 | 0.0029 | 0.0058 | 0.5563 | 0.0638 |

最佳模型：**Logistic Regression**（依 ROC-AUC，其次 F1）

- Accuracy：0.8673
- Precision：0.1080
- Recall：0.2076
- F1-score：0.1421
- ROC-AUC：0.7217
- Average Precision：0.1180

## 最重要的預測因素

| feature | importance | signed_effect | direction |
| --- | --- | --- | --- |
| categorical__seller_state_MA | 2.21822 | 2.21822 | higher delay risk |
| categorical__product_category_books_imported | 1.85879 | -1.85879 | lower delay risk |
| categorical__customer_state_SP | 1.51578 | -1.51578 | lower delay risk |
| categorical__customer_state_AL | 1.49937 | 1.49937 | higher delay risk |
| categorical__customer_state_RR | 1.42044 | 1.42044 | higher delay risk |
| categorical__product_category_infrequent_sklearn | 1.32141 | -1.32141 | lower delay risk |
| categorical__customer_state_PR | 1.14917 | -1.14917 | lower delay risk |
| categorical__customer_state_MG | 1.05787 | -1.05787 | lower delay risk |
| categorical__product_category_home_comfort_2 | 1.00873 | 1.00873 | higher delay risk |
| categorical__purchase_month_3 | 0.97851 | 0.97851 | higher delay risk |

係數絕對值代表影響強度；方向欄用來區分提高或降低延遲風險。

## 最強的延遲風險上升訊號

| feature | importance | signed_effect | direction |
| --- | --- | --- | --- |
| categorical__seller_state_MA | 2.21822 | 2.21822 | higher delay risk |
| categorical__customer_state_AL | 1.49937 | 1.49937 | higher delay risk |
| categorical__customer_state_RR | 1.42044 | 1.42044 | higher delay risk |
| categorical__product_category_home_comfort_2 | 1.00873 | 1.00873 | higher delay risk |
| categorical__purchase_month_3 | 0.97851 | 0.97851 | higher delay risk |
| categorical__purchase_month_2 | 0.87191 | 0.87191 | higher delay risk |
| categorical__customer_state_PA | 0.82846 | 0.82846 | higher delay risk |
| categorical__product_category_dvds_blu_ray | 0.81148 | 0.81148 | higher delay risk |
| categorical__purchase_month_11 | 0.74333 | 0.74333 | higher delay risk |
| categorical__customer_state_SE | 0.63063 | 0.63063 | higher delay risk |

## 測試集中的高風險訂單群

| segment_type | segment_value | orders | actual_delay_rate | predicted_delay_probability |
| --- | --- | --- | --- | --- |
| seller_state | MA | 225.0000 | 0.1422 | 0.6185 |
| customer_state | MA | 115.0000 | 0.1391 | 0.5504 |
| customer_state | PB | 113.0000 | 0.0442 | 0.4931 |
| customer_state | PA | 159.0000 | 0.0189 | 0.4652 |
| customer_state | BA | 638.0000 | 0.0533 | 0.4602 |
| customer_state | CE | 215.0000 | 0.0093 | 0.4589 |
| customer_state | PE | 322.0000 | 0.0435 | 0.4552 |
| customer_state | ES | 360.0000 | 0.0528 | 0.3917 |
| customer_state | RJ | 2213.0000 | 0.0434 | 0.3768 |
| customer_state | SC | 620.0000 | 0.0258 | 0.3657 |

## 結論

- 模型可作為延遲風險排序工具；在類別不平衡情況下，ROC-AUC、PR-AUC、Recall 與 F1 比 Accuracy 更有參考價值。
- 最佳模型 Average Precision 為 11.80%，高於測試集延遲率基準 5.29%，但仍有明顯改善空間。
- 高風險訂單可提前交由客服或物流團隊追蹤，但模型分數不應視為確定會延遲。
- 測試集採時間切分，因此結果更接近用歷史訂單預測未來訂單的實際情境。
