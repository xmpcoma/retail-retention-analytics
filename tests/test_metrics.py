"""Тесты на определения метрик: ровно на те места, где цифры обычно
расходятся — гости, отмены, «новый клиент» при фильтре по периоду.
"""
import numpy as np
import pandas as pd
import pytest

from retail_analytics import metrics as m
from retail_analytics.prepare import FACT_COLUMNS


def make_fact(rows) -> pd.DataFrame:
    """rows: (invoice, customer, code, date, qty, price, line_type, is_merch)."""
    df = pd.DataFrame(
        rows,
        columns=["invoice_no", "customer_id", "stock_code", "invoice_date",
                 "quantity", "unit_price", "line_type", "is_merchandise"],
    )
    df["invoice_date"] = pd.to_datetime(df.invoice_date)
    df["month_start"] = df.invoice_date.dt.to_period("M").dt.start_time
    df["line_revenue"] = (df.quantity * df.unit_price).round(2)
    df["description"] = df.stock_code + " desc"
    df["country"] = "United Kingdom"
    df["is_guest"] = df.customer_id.isna()
    df["is_bulk"] = df.quantity >= 20000
    df["customer_id"] = df.customer_id.astype("Int64")
    return df[FACT_COLUMNS]


ROWS = [
    ("A", 1, "x", "2009-12-01 09:00", 10, 2.0, "sale", True),            # 20
    ("B", 1, "x", "2010-01-15 09:00", 10, 3.0, "sale", True),            # 30
    ("C", 2, "y", "2009-12-05 09:00", 5, 2.0, "sale", True),             # 10
    ("D", None, "y", "2009-12-06 09:00", 5, 1.0, "sale", True),          # 5, гость
    ("E", 2, "x", "2010-01-20 09:00", -5, 2.0, "cancellation", True),    # -10
    ("F", 3, "z", "2010-03-01 09:00", -4, 0.0, "return", True),          # 0: возвраты без цены
    ("G", 2, "POST", "2010-02-02 09:00", 1, 18.0, "sale", False),        # доставка
]


@pytest.fixture
def fact():
    return make_fact(ROWS)


@pytest.fixture
def clean(fact):
    """То, что реально попадает в метрики: без нетоварных строк."""
    return m.apply_filters(fact)


def test_summary_keeps_sales_and_reversals_apart(clean):
    s = m.summary(clean)
    assert s["revenue"] == pytest.approx(65.0)
    assert s["reversal_value"] == pytest.approx(-10.0)
    assert s["net_revenue"] == pytest.approx(55.0)
    assert s["orders"] == 4
    assert s["aov"] == pytest.approx(65.0 / 4)
    assert s["customers"] == 2, "гость не должен попадать в число клиентов"
    assert s["cancellations"] == 1
    assert s["returns"] == 1


def test_non_merchandise_drops_postage_but_stays_visible(fact, clean):
    assert "POST" not in set(clean.stock_code)
    assert m.summary(fact)["revenue"] == pytest.approx(83.0), "без фильтра доставка входит"
    assert m.apply_filters(fact, merchandise_only=False).stock_code.nunique() == 4


def test_monthly_new_and_returning(clean):
    mm = m.monthly(clean).set_index("month")
    assert mm.loc["2009-12", "revenue"] == pytest.approx(35.0)
    assert mm.loc["2009-12", "customers"] == 2
    assert mm.loc["2009-12", "new_customers"] == 2
    assert mm.loc["2010-01", "new_customers"] == 0
    assert mm.loc["2010-01", "returning_customers"] == 1
    assert mm.loc["2010-01", "net_revenue"] == pytest.approx(20.0)
    assert np.isnan(mm.loc["2009-12", "mom_revenue"])


def test_growth_is_shifted_by_date_not_by_row(clean):
    """Месяца с продажами в fixture нет (2010-02), поэтому YoY не должен
    соскочить на строку 2010-01 там, где он обязан быть пустым."""
    mm = m.monthly(clean).set_index("month")
    assert list(mm.index) == ["2009-12", "2010-01"]
    assert pd.isna(mm.loc["2010-01", "yoy_revenue"])


def test_period_filter_does_not_invent_new_customers(clean):
    first_month = clean[clean.customer_id.notna()].groupby("customer_id").month_start.min()
    in_window = m.apply_filters(clean, period=("2010-01-01", "2010-12-31"))
    naive = m.monthly(in_window).set_index("month")
    strict = m.monthly(in_window, first_month=first_month).set_index("month")
    assert naive.loc["2010-01", "new_customers"] == 1, "без глобальной базы клиент снова «новый»"
    assert strict.loc["2010-01", "new_customers"] == 0
    assert strict.loc["2010-01", "returning_customers"] == 1


def test_period_ends_with_the_whole_last_day(fact):
    """Конец периода — день целиком, а не его полночь: строка D стоит в
    09:00 шестого декабря, и сравнение с Timestamp(end) её отрезала бы."""
    window = m.apply_filters(fact, period=("2009-12-01", "2009-12-06"))
    assert set(window.invoice_no) == {"A", "C", "D"}


def test_repeat_stats(clean):
    stats = m.repeat_stats(clean)
    assert stats["customers"] == 2
    assert stats["repeat_rate"] == pytest.approx(0.5)
    assert stats["one_time_share"] == pytest.approx(0.5)
    assert stats["median_gap_days"] == pytest.approx(45.0)


def test_pareto_and_concentration(clean):
    p = m.pareto(clean)
    assert p.cum_share.is_monotonic_increasing
    assert p.cum_share.iloc[-1] == pytest.approx(1.0)
    # 50 из 60 товарных продаж идентифицированных клиентов делает один человек
    assert m.concentration(clean, 0.5) == pytest.approx(0.5)
    assert m.concentration(clean, 1.0) == pytest.approx(1.0)


def test_country_rollup_repeat_rate(clean):
    c = m.country_rollup(clean).set_index("country")
    assert c.loc["United Kingdom", "revenue"] == pytest.approx(65.0)
    assert c.loc["United Kingdom", "orders"] == 4
    assert c.loc["United Kingdom", "repeat_rate"] == pytest.approx(0.5)


def test_cancellations_monthly_share(clean):
    r = m.cancellations_monthly(clean).set_index("month")
    assert r.loc["2010-01", "cancellations"] == 1
    assert r.loc["2010-01", "reversal_value"] == pytest.approx(-10.0)
    assert r.loc["2010-01", "share_of_sales"] == pytest.approx(10 / 30)
    assert r.loc["2010-03", "returns"] == 1


def test_apply_filters_bulk_and_countries(fact):
    bulk = make_fact([("H", 4, "x", "2010-05-01 09:00", 25000, 1.0, "sale", True)])
    both = pd.concat([fact, bulk], ignore_index=True)
    # вместе с оптовой строкой уезжает и H, а доставка G отсекается как
    # нетоварная позиция: остаются A-F
    assert m.apply_filters(both, include_bulk=False).invoice_no.nunique() == 6
    assert m.summary(m.apply_filters(both))["revenue"] == pytest.approx(25065.0)
    assert m.apply_filters(fact, countries=["France"]).empty
    assert m.apply_filters(fact, identified_only=True).customer_id.notna().all()


def test_top_products_share_never_exceeds_one(clean):
    t = m.top_products(clean)
    assert t.revenue_share.sum() <= 1.0 + 1e-9
    assert t.iloc[0].stock_code == "x"
    assert t.iloc[0].revenue == pytest.approx(50.0)
