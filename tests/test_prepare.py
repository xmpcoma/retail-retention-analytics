"""Тесты на правила очистки.

Фикстура собрана из реальных проблемных строк датасета: разные заголовки
листов, инвойсы с префиксом C, возврат с нулевой ценой, кривые пробелы в
стране, дубль из пересекающегося декабря и «carriage clock», который по
наивному правилу уезжает в нетоварные.
"""
import pandas as pd
import pytest

from retail_analytics import prepare as pp

COLS_V1 = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
COLS_V2 = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID", "Country"]


@pytest.fixture
def workbook(tmp_path):
    """Два листа с разными заголовками, склеенные в один xlsx."""
    sheet_one = pd.DataFrame(
        [
            (489463, "71477", "COLOUR GLASS. STAR T-LIGHT HOLDER", -240, "2010-01-04 12:39", 0.0, None, "United Kingdom"),
            (489464, "21733", "SET OF 6 T-LIGHTS SANTA", -96, "2010-01-04 12:42", 0.0, None, "United Kingdom"),
            ("C489465", "22087", "MAGLIFORE CASTLE", -12, "2010-01-05 10:00", 4.15, 12346.0, "United Kingdom"),
            (489466, "POST", "POSTAGE", 1, "2010-01-05 11:00", 18.0, 12346.0, "United Kingdom"),
            (489467, "22726", "STRAWBERRY CERAMIC TRINKET BOX", 12, "2010-01-06 09:00", 1.25, 12347.0, "France "),
            (489468, "22745", "LIGHT UP CROWNGARDEN", 24, "2010-01-06 09:30", 0.85, None, "Unspecified"),
            (489469, "22747", None, 3, "2010-01-06 10:00", 2.1, 12347.0, "Germany"),
            (489475, "22747", "GLASS STAR FROSTED T-LIGHT HOLDER", 6, "2010-01-09 12:00", 2.1, 12349.0, "Germany"),
            (489476, "22745", "LIGHT UP CROWNGARDEN", 12, "2010-01-10 12:00", 0.85, 12350.0, "EIRE"),
            (489470, "22111", "BLACK BAROQUE CARRIAGE CLOCK", 2, "2010-01-07 10:00", 12.49, 12348.0, "Sweden"),
            (489471, "M", "Manual", -1, "2010-01-07 12:00", 25111.09, 12348.0, "United Kingdom"),
            (489472, "TEST001", "This is a test product.", 1, "2010-01-08 12:00", 1.0, 12348.0, "United Kingdom"),
        ],
        columns=COLS_V1,
    )
    # второй лист: те же продажи, но заголовки другие + дубль инвойса из
    # пересекающегося периода
    sheet_two = pd.DataFrame(
        [
            (489473, "22726", "STRAWBERRY CERAMIC TRINKET BOX", 12, "2010-12-02 09:00", 1.25, 12347.0, "France"),
            (489473, "22726", "STRAWBERRY CERAMIC TRINKET BOX", 12, "2010-12-02 09:00", 1.25, 12347.0, "France"),
            ("C500001", "22111", "BLACK BAROQUE CARRIAGE CLOCK", -2, "2010-12-03 10:00", 12.49, 12348.0, "Sweden"),
        ],
        columns=COLS_V2,
    )
    path = tmp_path / "mini.xlsx"
    with pd.ExcelWriter(path) as xw:
        sheet_one.to_excel(xw, sheet_name="Year 2009-2010", index=False)
        sheet_two.to_excel(xw, sheet_name="Year 2010-2011", index=False)
    return path


def test_headers_from_both_sheets_are_unified(workbook):
    raw, log = pp.read_source(workbook)
    assert not raw.columns.duplicated().any(), "алиасы не должны размножать колонки"
    assert list(raw.columns) == pp.REQUIRED
    assert len(log) == 2


def test_invoice_ids_have_no_float_artifacts(workbook):
    fact, _ = pp.build_fact(workbook)
    assert set(fact.invoice_no.str.contains(r"\.").value_counts().index) == {False}
    assert "489463" in set(fact.invoice_no)


def test_returns_and_cancellations_are_different_types(workbook):
    fact, _ = pp.build_fact(workbook)
    assert set(fact.loc[fact.stock_code == "71477", "line_type"]) == {"return"}
    assert set(fact.loc[fact.invoice_no == "C489465", "line_type"]) == {"cancellation"}


def test_non_merchandise_flag_does_not_eat_products(workbook):
    fact, _ = pp.build_fact(workbook)
    clocks = fact[fact.stock_code == "22111"]
    assert clocks.is_merchandise.all(), "carriage clock — это товар, а не доставка"
    assert not fact[fact.stock_code.isin(["POST", "M"])].is_merchandise.any()
    # ручная корректировка на 25 тысяч не должна остаться в обороте
    assert fact[fact.is_merchandise].line_revenue.sum() < 200


def test_test_products_are_dropped(workbook):
    fact, _ = pp.build_fact(workbook)
    assert "TEST001" not in set(fact.stock_code)


def test_cross_sheet_duplicate_collapsed(workbook):
    fact, _ = pp.build_fact(workbook)
    dupes = fact[(fact.invoice_no == "489473") & (fact.stock_code == "22726")]
    assert len(dupes) == 1


def test_description_backfilled_from_sibling_rows(workbook):
    fact, dq = pp.build_fact(workbook)
    row = fact[fact.stock_code == "22747"].iloc[0]
    assert row.description == "GLASS STAR FROSTED T-LIGHT HOLDER"
    assert int(dq.loc[dq.rule.str.contains("описание"), "rows"].iat[0]) == 1


def test_legacy_country_name_is_mapped(workbook):
    fact, dq = pp.build_fact(workbook)
    assert "Ireland" in set(fact.country)
    assert "EIRE" not in set(fact.country)
    # склейка обязана остаться видимой в логе, а не происходить молча
    assert int(dq.loc[dq.rule.str.contains("справочник"), "rows"].iat[0]) == 1


def test_country_and_guest_flags(workbook):
    fact, _ = pp.build_fact(workbook)
    assert "France" in set(fact.country), "пробел в конце страны должен быть срезан"
    assert fact.loc[fact.customer_id.isna(), "is_guest"].all()
    assert fact.loc[fact.customer_id.notna(), "is_guest"].sum() == 0


def test_revenue_is_quantity_times_price(workbook):
    fact, _ = pp.build_fact(workbook)
    row = fact[fact.invoice_no == "489469"].iloc[0]
    assert row.line_revenue == round(row.quantity * row.unit_price, 2)


def test_dq_log_covers_every_rule(workbook):
    _, dq = pp.build_fact(workbook)
    assert set(dq.columns) == {"rule", "rows", "note"}
    assert len(dq) >= 8
    assert dq.rows.notna().all()
