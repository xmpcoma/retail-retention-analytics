-- Товары и концентрация выручки.

-- description внутри одной группы может различаться: в данных у одного кода
-- местами опечатки и другой регистр, поэтому берём самое частое значение.
CREATE OR REPLACE TABLE product_stats AS
WITH per_product AS (
    SELECT
        stock_code,
        SUM(line_revenue) AS revenue,
        SUM(quantity) AS units,
        COUNT(DISTINCT invoice_no) AS orders,
        COUNT(DISTINCT customer_id) AS buyers
    FROM sales_all
    GROUP BY 1
),
labels AS (
    SELECT stock_code, mode(description) AS description
    FROM sales_all
    GROUP BY 1
)
SELECT
    p.stock_code,
    l.description,
    ROUND(p.revenue, 2) AS revenue,
    ROUND(p.revenue / SUM(p.revenue) OVER (), 4) AS revenue_share,
    p.units,
    p.orders,
    p.buyers,
    ROUND(p.revenue / NULLIF(p.units, 0), 2) AS avg_unit_price,
    ROUND(SUM(p.revenue) OVER (ORDER BY p.revenue DESC, p.stock_code) / SUM(p.revenue) OVER (), 4) AS cum_revenue_share
FROM per_product p
JOIN labels l USING (stock_code)
ORDER BY p.revenue DESC, p.stock_code;

-- Сколько клиентов дают 50% и 80% оборота. Без этого числа разговор про
-- «ядро» повисает в воздухе.
-- Сколько топовых клиентов нужно, чтобы набрать 50% и 80% оборота. Берём
-- первый номер, на котором кумулятивная доля ПЕРЕШЛА порог (>=), а не
-- MAX(... <= ...): иначе клиент крупнее 50% не оставлял бы ни одной строки
-- под условием, и число выходило NULL.
CREATE OR REPLACE TABLE customer_concentration AS
WITH per_customer AS (
    SELECT customer_id, SUM(line_revenue) AS revenue
    FROM sales_id
    GROUP BY 1
),
ranked AS (
    SELECT
        customer_id,
        revenue,
        SUM(revenue) OVER (ORDER BY revenue DESC, customer_id) / SUM(revenue) OVER () AS cum_share,
        ROW_NUMBER() OVER (ORDER BY revenue DESC, customer_id) AS rn,
        COUNT(*) OVER () AS total_customers
    FROM per_customer
)
SELECT
    MIN(CASE WHEN cum_share >= 0.5 THEN rn END) AS customers_for_half_of_revenue,
    MIN(CASE WHEN cum_share >= 0.8 THEN rn END) AS customers_for_80_of_revenue,
    MAX(total_customers) AS total_customers,
    ROUND(MIN(CASE WHEN cum_share >= 0.5 THEN rn END) * 1.0 / MAX(total_customers), 4) AS share_for_50pct,
    ROUND(MIN(CASE WHEN cum_share >= 0.8 THEN rn END) * 1.0 / MAX(total_customers), 4) AS share_for_80pct
FROM ranked;

-- Интервал между покупками одного клиента: по нему потом выбирается окно
-- реактивации, поэтому считаем медиану и квантили, а не среднее (среднее
-- уезжает в бесконечность из-за клиентов, купивших один раз за два года).
CREATE OR REPLACE TABLE purchase_gaps AS
WITH invoices AS (
    SELECT DISTINCT customer_id, invoice_date, invoice_no
    FROM sales_id
),
gaps AS (
    SELECT
        date_diff('day', invoice_date, LEAD(invoice_date) OVER (PARTITION BY customer_id ORDER BY invoice_date)) AS gap_days
    FROM invoices
)
SELECT
    COUNT(*) AS gaps_observed,
    ROUND(AVG(gap_days), 1) AS avg_gap_days,
    ROUND(QUANTILE_CONT(gap_days, 0.25), 1) AS p25_gap_days,
    ROUND(QUANTILE_CONT(gap_days, 0.5), 1) AS median_gap_days,
    ROUND(QUANTILE_CONT(gap_days, 0.75), 1) AS p75_gap_days,
    ROUND(AVG(CASE WHEN gap_days <= 30 THEN 1.0 ELSE 0.0 END), 4) AS share_gaps_up_to_30d,
    ROUND(AVG(CASE WHEN gap_days > 180 THEN 1.0 ELSE 0.0 END), 4) AS share_gaps_over_180d
FROM gaps
WHERE gap_days IS NOT NULL;

-- День недели. Кто покупает — бизнес или розница — хорошо видно по распределению
-- заказов: у корпоративного покупателя они концентрируются в будни.
CREATE OR REPLACE TABLE weekday_profile AS
SELECT
    dayname(invoice_date) AS weekday,
    dayofweek(invoice_date) AS dow,
    COUNT(DISTINCT invoice_no) AS orders,
    ROUND(SUM(line_revenue), 2) AS revenue,
    ROUND(SUM(line_revenue) / COUNT(DISTINCT invoice_no), 2) AS aov
FROM sales_all
GROUP BY 1, 2
ORDER BY 2;
