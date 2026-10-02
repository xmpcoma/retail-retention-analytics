-- Отмены и возвраты. Считаются отдельной витриной, а не «минусом» в выручке:
-- в исходнике отмена — это отдельный инвойс с префиксом C, а возврат строки —
-- отрицательное количество внутри обычного инвойса. Разные процессы, и по
-- отдельной статистике это видно.

CREATE OR REPLACE TABLE reversal_monthly AS
SELECT
    strftime(month_start, '%Y-%m') AS month,
    month_start,
    SUM(CASE WHEN line_type = 'cancellation' THEN 1 ELSE 0 END) AS cancellation_lines,
    SUM(CASE WHEN line_type = 'return' THEN 1 ELSE 0 END) AS return_lines,
    ROUND(SUM(CASE WHEN line_type <> 'sale' THEN line_revenue ELSE 0 END), 2) AS reversal_value,
    ROUND(SUM(CASE WHEN line_type = 'sale' AND is_merchandise THEN line_revenue ELSE 0 END), 2) AS sales_value,
    ROUND(
        -SUM(CASE WHEN line_type <> 'sale' THEN line_revenue ELSE 0 END)
        / NULLIF(SUM(CASE WHEN line_type = 'sale' AND is_merchandise THEN line_revenue ELSE 0 END), 0),
        4
    ) AS reversal_share
FROM all_lines
GROUP BY 1, 2
ORDER BY 2;

-- Чем именно обораны суммы: товарные позиции против нетоварных. Здесь
-- всплывает то, что не видно в KPI: отмен по служебным строкам (manual, bad
-- debt, комиссии, банки) — £745,5 тыс., то есть больше, чем по товару (£716,5
-- тыс.). Один общий показатель «отмены» смешивает два разных процесса.
CREATE OR REPLACE TABLE reversal_breakdown AS
SELECT
    line_type,
    CASE WHEN is_merchandise THEN 'товар' ELSE 'нетоварная позиция' END AS kind,
    COUNT(*) AS lines,
    ROUND(SUM(line_revenue), 2) AS value
FROM all_lines
WHERE line_type <> 'sale'
GROUP BY 1, 2
ORDER BY value, line_type, kind;

CREATE OR REPLACE TABLE reversed_products AS
SELECT
    stock_code,
    mode(description) AS description,
    COUNT(*) AS reversal_lines,
    ROUND(SUM(line_revenue), 2) AS reversal_value,
    SUM(-quantity) AS units_back
FROM all_lines
WHERE line_type <> 'sale' AND is_merchandise
GROUP BY 1
ORDER BY reversal_value, stock_code
LIMIT 25;
