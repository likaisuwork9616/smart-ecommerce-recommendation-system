-- ============================================================
-- Stage 3: Olist Business Analysis EDA
-- Project: Smart E-Commerce Recommendation System
-- Description:
--   This SQL file stores the key business analysis queries used in
--   notebooks/03_olist_business_analysis.ipynb
-- ============================================================


-- ============================================================
-- 1. Monthly Order Count
-- Business Question:
--   How does the number of delivered orders change over time?
-- ============================================================

SELECT
    DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS order_month,
    COUNT(*) AS order_count
FROM orders
WHERE order_status = 'delivered'
GROUP BY order_month
ORDER BY order_month;


-- ============================================================
-- 2. Monthly Revenue
-- Business Question:
--   How does monthly revenue change over time?
-- ============================================================

SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS order_month,
    SUM(oi.price + oi.freight_value) AS revenue
FROM orders o
JOIN order_items oi
    ON o.order_id = oi.order_id
WHERE o.order_status = 'delivered'
GROUP BY order_month
ORDER BY order_month;


-- ============================================================
-- 3. Top 10 Product Categories by Revenue
-- Business Question:
--   Which product categories generate the highest revenue?
-- ============================================================

SELECT
    COALESCE(t.product_category_name_english, p.product_category_name) AS category,
    SUM(oi.price) AS revenue
FROM order_items oi
JOIN products p
    ON oi.product_id = p.product_id
LEFT JOIN product_category_name_translation t
    ON p.product_category_name = t.product_category_name
GROUP BY category
ORDER BY revenue DESC
LIMIT 10;


-- ============================================================
-- 4. Payment Type Distribution
-- Business Question:
--   Which payment methods are most commonly used by customers?
-- ============================================================

SELECT
    payment_type,
    COUNT(*) AS payment_count
FROM order_payments
GROUP BY payment_type
ORDER BY payment_count DESC;


-- ============================================================
-- 5. Review Score Distribution
-- Business Question:
--   What is the distribution of customer review scores?
-- ============================================================

SELECT
    review_score,
    COUNT(*) AS review_count
FROM order_reviews
GROUP BY review_score
ORDER BY review_score;


-- ============================================================
-- 6. Delivery Days Data
-- Business Question:
--   How long does it take for delivered orders to reach customers?
-- ============================================================

SELECT
    order_id,
    order_purchase_timestamp,
    order_delivered_customer_date,
    order_estimated_delivery_date
FROM orders
WHERE order_status = 'delivered'
  AND order_delivered_customer_date IS NOT NULL;


-- ============================================================
-- 7. Delayed Orders
-- Business Question:
--   Which delivered orders arrived later than the estimated delivery date?
-- ============================================================

SELECT
    order_id,
    order_purchase_timestamp,
    order_delivered_customer_date,
    order_estimated_delivery_date,
    CASE
        WHEN order_delivered_customer_date > order_estimated_delivery_date
        THEN 1
        ELSE 0
    END AS is_delayed
FROM orders
WHERE order_status = 'delivered'
  AND order_delivered_customer_date IS NOT NULL
  AND order_estimated_delivery_date IS NOT NULL;


-- ============================================================
-- 8. Order Count by Customer State
-- Business Question:
--   Which customer states have the highest number of delivered orders?
-- ============================================================

SELECT
    c.customer_state,
    COUNT(o.order_id) AS order_count
FROM orders o
JOIN customers c
    ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
GROUP BY c.customer_state
ORDER BY order_count DESC;


-- ============================================================
-- 9. Seller Distribution by State
-- Business Question:
--   Which states have the most sellers?
-- ============================================================

SELECT
    seller_state,
    COUNT(*) AS seller_count
FROM sellers
GROUP BY seller_state
ORDER BY seller_count DESC;


-- ============================================================
-- 10. Average Order Value
-- Business Question:
--   What is the average order value of delivered orders?
-- ============================================================

SELECT
    AVG(order_total) AS avg_order_value
FROM (
    SELECT
        o.order_id,
        SUM(oi.price + oi.freight_value) AS order_total
    FROM orders o
    JOIN order_items oi
        ON o.order_id = oi.order_id
    WHERE o.order_status = 'delivered'
    GROUP BY o.order_id
) t;