-- Помесячные KPI. Эта витрина — источник цифр для README: pandas-функции из
-- metrics.py считаются независимо, и test_marts_agree_with_pandas проверяет,
-- что два пути дают одинаковый оборот.

CREATE OR REPLACE TABLE monthly_kpi AS
WITH order_level AS (
    SELECT month_start, invoice_no, SUM(line_revenue) AS order_revenue, SUM(quantity) AS units
    FROM sales_all
    GROUP BY 1, 2
),
first_purchase AS (
    SELECT customer_id, MIN(month_start) AS first_month
    FROM sales_id
    GROUP BY 1
),
new_customers AS (
    SELECT first_month AS month_start, COUNT(*) AS new_customers
    FROM first_purchase
    GROUP BY 1
),
monthly_active AS (
    SELECT month_start,
           COUNT(DISTINCT customer_id) AS customers,
           COUNT(DISTINCT invoice_no) AS orders,
           SUM(line_revenue) AS revenue,
           SUM(quantity) AS units
    FROM sales_all
    GROUP BY 1
)
SELECT
    strftime(m.month_start, '%Y-%m') AS month,
    m.month_start,
    ROUND(m.revenue, 2) AS revenue,
    m.orders,
    m.customers,
    m.units,
    COALESCE(n.new_customers, 0) AS new_customers,
    m.customers - COALESCE(n.new_customers, 0) AS returning_customers,
    ROUND(m.revenue / m.orders, 2) AS aov,
    ROUND(m.revenue / NULLIF(m.customers, 0), 2) AS revenue_per_customer,
    LAG(m.revenue) OVER (ORDER BY m.month_start) AS revenue_prev_month,
    LAG(m.revenue, 12) OVER (ORDER BY m.month_start) AS revenue_same_month_last_year
FROM monthly_active m
LEFT JOIN new_customers n USING (month_start)
ORDER BY m.month_start;
