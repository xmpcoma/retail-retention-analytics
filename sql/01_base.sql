-- Базовые срезы, из которых строятся остальные витрины.
-- sales_all: товарные продажи целиком, включая гостевые строки без customer_id.
-- sales_id: то же, но только с идентифицированным покупателем — из него
-- считаются когорты, RFM и доли повторных покупок.

CREATE OR REPLACE VIEW sales_all AS
SELECT
    invoice_no,
    customer_id,
    stock_code,
    description,
    country,
    CAST(invoice_date AS DATE) AS invoice_date,
    month_start,
    quantity,
    unit_price,
    line_revenue,
    is_bulk,
    customer_id IS NULL AS is_guest
FROM read_parquet('{{FACT_PATH}}')
WHERE line_type = 'sale'
  AND is_merchandise;

CREATE OR REPLACE VIEW sales_id AS
SELECT * FROM sales_all WHERE customer_id IS NOT NULL;

-- Все строки, включая отмены и возвраты: для витрины по возвратам.
CREATE OR REPLACE VIEW all_lines AS
SELECT
    invoice_no,
    customer_id,
    stock_code,
    description,
    country,
    CAST(invoice_date AS DATE) AS invoice_date,
    month_start,
    quantity,
    unit_price,
    line_revenue,
    line_type,
    is_merchandise,
    is_guest,
    is_bulk
FROM read_parquet('{{FACT_PATH}}');

CREATE OR REPLACE VIEW snapshot AS
SELECT CAST(MAX(invoice_date) AS DATE) AS as_of FROM sales_all;
