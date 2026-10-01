-- Что именно осталось за рамками выручки. Отдельная витрина затем, чтобы в
-- README можно было показать не «мы удалили мусор», а сколько денег при этом
-- не учли в обороте.
CREATE OR REPLACE TABLE non_merchandise_breakdown AS
SELECT
    stock_code,
    mode(description) AS description,
    COUNT(*) AS lines,
    ROUND(SUM(line_revenue), 2) AS value,
    ROUND(SUM(CASE WHEN line_type = 'sale' THEN line_revenue ELSE 0 END), 2) AS sales_value
FROM all_lines
WHERE NOT is_merchandise
GROUP BY 1
ORDER BY value DESC, stock_code;

CREATE OR REPLACE TABLE data_quality AS
SELECT
    COUNT(*) AS lines_total,
    COUNT(DISTINCT invoice_no) AS invoices,
    COUNT(DISTINCT customer_id) AS customers,
    COUNT(*) FILTER (WHERE line_type = 'cancellation') AS cancellation_lines,
    COUNT(*) FILTER (WHERE line_type = 'return') AS return_lines,
    COUNT(*) FILTER (WHERE NOT is_merchandise) AS non_merchandise_lines,
    COUNT(*) FILTER (WHERE is_guest) AS guest_lines,
    COUNT(*) FILTER (WHERE is_bulk) AS bulk_lines,
    COUNT(*) FILTER (WHERE description = '<не удалось восстановить>') AS description_missing,
    COUNT(*) FILTER (WHERE country = 'Unspecified') AS country_unspecified,
    MIN(invoice_date)::DATE AS first_day,
    MAX(invoice_date)::DATE AS last_day
FROM all_lines;
