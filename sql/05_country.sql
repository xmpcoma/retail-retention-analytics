-- Страна: оборот, доля рынка и повторные покупки.
-- Доля повторных считается только по идентифицированным клиентам: гостей
-- нельзя ни посчитать повторно, ни корректно исключить из знаменателя.

CREATE OR REPLACE TABLE country_stats AS
WITH all_sales AS (
    SELECT country,
           SUM(line_revenue) AS revenue,
           COUNT(DISTINCT invoice_no) AS orders,
           COUNT(DISTINCT customer_id) AS customers
    FROM sales_all
    GROUP BY 1
),
identified AS (
    SELECT country, customer_id, COUNT(DISTINCT invoice_no) AS orders
    FROM sales_id
    GROUP BY 1, 2
),
repeat_rate AS (
    SELECT country, AVG(CASE WHEN orders > 1 THEN 1.0 ELSE 0.0 END) AS repeat_rate
    FROM identified
    GROUP BY 1
)
SELECT
    a.country,
    ROUND(a.revenue, 2) AS revenue,
    ROUND(a.revenue / SUM(a.revenue) OVER (), 4) AS revenue_share,
    a.orders,
    a.customers,
    ROUND(a.revenue / a.orders, 2) AS aov,
    ROUND(r.repeat_rate, 4) AS repeat_rate
FROM all_sales a
JOIN repeat_rate r USING (country)
ORDER BY a.revenue DESC;

-- Группы рынков: по 41 стране вывод читается плохо, а вопрос «что нам даёт
-- экспорт» — один. Европа и Ближний Восток собраны списком вручную, остальные
-- записаны отдельной группой, чтобы не выдавать Австралию за Европу.
CREATE OR REPLACE TABLE region_stats AS
WITH grouped AS (
    SELECT
        CASE
            WHEN country = 'United Kingdom' THEN 'Великобритания'
            WHEN country = 'Unspecified' THEN 'Страна не указана'
            WHEN country IN (
                'Germany', 'France', 'Spain', 'Italy', 'Netherlands', 'Belgium', 'Portugal',
                'Sweden', 'Switzerland', 'Austria', 'Denmark', 'Finland', 'Norway', 'Ireland',
                'Poland', 'Czech Republic', 'Greece', 'Cyprus', 'Malta', 'Hungary', 'Romania',
                'Sardinia', 'European Community', 'United Arab Emirates', 'Saudi Arabia',
                'Lebanon', 'Bahrain', 'Qatar', 'Oman', 'Israel', 'Channel Islands', 'Isle of Man'
            ) THEN 'Экспорт: Европа и Ближний Восток'
            ELSE 'Экспорт: прочие страны'
        END AS region,
        month_start,
        invoice_no,
        customer_id,
        line_revenue
    FROM sales_all
)
SELECT
    region,
    strftime(month_start, '%Y-%m') AS month,
    ROUND(SUM(line_revenue), 2) AS revenue,
    COUNT(DISTINCT invoice_no) AS orders,
    COUNT(DISTINCT customer_id) AS customers
FROM grouped
GROUP BY 1, 2
ORDER BY 1, 2;
