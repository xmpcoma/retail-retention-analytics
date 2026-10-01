-- RFM на последний день данных.

-- Два замечания, которые обычно забывают:
-- 1) Баллы режут не по NTILE, а по квантильным порогам. Частота покупки
--    принимает мало значений: половина базы купила не больше трёх раз, и на
--    границе квантиля стоит сразу несколько сотен человек. NTILE разрывает
--    эту толпу по порядку строк — два одинаковых клиента получают разные
--    баллы, и на пересборке витрины это уезжает (с ntile(5) сегменты
--    менялись у 33 клиентов, балл — у 695). Порог один на всех, поэтому
--    группы получаются неровными, зато воспроизводимыми.
-- 2) Декабрь 2011 обрезан на 9-м числе: recency считается от фактически
--    последней транзакции, а не от конца месяца.

CREATE OR REPLACE TABLE rfm AS
WITH base AS (
    SELECT
        customer_id,
        date_diff('day', MAX(invoice_date), (SELECT as_of FROM snapshot)) AS recency_days,
        COUNT(DISTINCT invoice_no) AS frequency,
        ROUND(SUM(line_revenue), 2) AS monetary,
        MIN(invoice_date) AS first_purchase,
        MAX(invoice_date) AS last_purchase
    FROM sales_id
    GROUP BY 1
),
cuts AS (
    SELECT
        quantile_cont(recency_days, [0.2, 0.4, 0.6, 0.8]) AS r,
        quantile_cont(frequency, [0.2, 0.4, 0.6, 0.8]) AS f,
        quantile_cont(monetary, [0.2, 0.4, 0.6, 0.8]) AS m
    FROM base
),
scored AS (
    SELECT
        b.*,
        -- 6 - ...: у recency «меньше — лучше», поэтому балл инвертируем
        6 - (1 + (b.recency_days > c.r[1])::int + (b.recency_days > c.r[2])::int
               + (b.recency_days > c.r[3])::int + (b.recency_days > c.r[4])::int) AS r_score,
        1 + (b.frequency > c.f[1])::int + (b.frequency > c.f[2])::int
            + (b.frequency > c.f[3])::int + (b.frequency > c.f[4])::int AS f_score,
        1 + (b.monetary > c.m[1])::int + (b.monetary > c.m[2])::int
            + (b.monetary > c.m[3])::int + (b.monetary > c.m[4])::int AS m_score,
        ROUND(b.monetary / b.frequency, 2) AS avg_order_value
    FROM base b
    CROSS JOIN cuts c
)
SELECT
    *,
    (r_score + f_score + m_score) AS rfm_score,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'ядро'
        WHEN r_score >= 4 AND f_score >= 3 THEN 'лояльные'
        WHEN r_score >= 4 AND f_score <= 2 THEN 'свежие'
        WHEN r_score = 3 AND f_score >= 3 THEN 'остывают'
        WHEN r_score <= 2 AND m_score >= 4 THEN 'дорогой отток'
        WHEN r_score <= 2 THEN 'отток'
        ELSE 'прочее'
    END AS segment
FROM scored;

CREATE OR REPLACE TABLE rfm_segments AS
WITH totals AS (SELECT SUM(monetary) AS total_revenue FROM rfm)
SELECT
    segment,
    COUNT(*) AS customers,
    ROUND(COUNT(*) * 1.0 / (SELECT COUNT(*) FROM rfm), 4) AS customers_share,
    SUM(monetary) AS revenue,
    ROUND(SUM(monetary) * 1.0 / t.total_revenue, 4) AS revenue_share,
    ROUND(AVG(monetary), 2) AS avg_revenue_per_customer,
    ROUND(AVG(frequency), 2) AS avg_orders,
    ROUND(AVG(recency_days), 0) AS avg_recency_days
FROM rfm, totals t
GROUP BY 1, t.total_revenue
ORDER BY revenue DESC;
