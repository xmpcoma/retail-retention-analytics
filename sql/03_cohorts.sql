-- Когортная матрица в длинном формате: строка = когорта + номер месяца
-- после первой покупки.
--
-- Когорта = месяц первой покупки идентифицированного покупателя. Месяц
-- считается активным, если в нём была хотя бы одна товарная продажа: две
-- покупки в одном месяце не дают двух «удержаний».

CREATE OR REPLACE TABLE cohort_retention AS
WITH cohort AS (
    SELECT customer_id, MIN(month_start) AS cohort_month
    FROM sales_id
    GROUP BY 1
),
activity AS (
    SELECT
        c.cohort_month,
        c.customer_id,
        date_diff('month', c.cohort_month, s.month_start) AS month_number
    FROM cohort c
    JOIN sales_id s USING (customer_id)
    GROUP BY 1, 2, 3
),
sizes AS (
    SELECT cohort_month, COUNT(*) AS cohort_size FROM cohort GROUP BY 1
)
SELECT
    strftime(a.cohort_month, '%Y-%m') AS cohort,
    a.cohort_month,
    a.month_number,
    z.cohort_size,
    COUNT(DISTINCT a.customer_id) AS active_customers,
    ROUND(COUNT(DISTINCT a.customer_id) * 1.0 / z.cohort_size, 4) AS retention
FROM activity a
JOIN sizes z USING (cohort_month)
GROUP BY 1, 2, 3, z.cohort_size
ORDER BY a.cohort_month, a.month_number;

-- То же самое, но в деньгах: доля выручки когорты, приходящаяся на каждый
-- месяц жизни. Нужна потому, что «удержали» и «приносят деньги» — не одно и
-- то же. В клиентах когорта теряет четыре пятых уже на втором месяце (среднее
-- удержание 21%) и дальше медленно сползает к 15%. В деньгах после стартового
-- месяца (37,5% выручки когорты) держится ровные 4–8% на каждом следующем —
-- вплоть до двадцатого.
CREATE OR REPLACE TABLE cohort_revenue AS
WITH cohort AS (
    SELECT customer_id, MIN(month_start) AS cohort_month
    FROM sales_id
    GROUP BY 1
),
monthly AS (
    SELECT
        c.cohort_month,
        date_diff('month', c.cohort_month, s.month_start) AS month_number,
        SUM(s.line_revenue) AS revenue
    FROM cohort c
    JOIN sales_id s USING (customer_id)
    GROUP BY 1, 2
)
SELECT
    strftime(cohort_month, '%Y-%m') AS cohort,
    month_number,
    ROUND(revenue, 2) AS revenue,
    ROUND(revenue / SUM(revenue) OVER (PARTITION BY cohort_month), 4) AS revenue_share
FROM monthly
ORDER BY 1, 2;
