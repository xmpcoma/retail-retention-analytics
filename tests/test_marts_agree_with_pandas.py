"""Витрины из sql/ и pandas-метрики считают одно и то же двумя разными
языками. Это единственная причина, по которой я держу оба: сошлись цифры —
значит, ни в SQL, ни в Python не закралась разница в определении.

Тесты пропускаются, если витрины не собраны (pytest требует сначала выполнить
python -m retail_analytics.marts).
"""
import pandas as pd
import pytest

from retail_analytics import config as cfg
from retail_analytics import metrics as m
from retail_analytics.marts import MARTS_DIR


@pytest.fixture(scope="module")
def fact():
    if not cfg.FACT_FILE.exists():
        pytest.skip("нет fact_transactions.parquet")
    return m.apply_filters(m.load_fact(cfg.FACT_FILE))


def mart(name):
    path = MARTS_DIR / f"{name}.parquet"
    if not path.exists():
        pytest.skip(f"витрина {name} не собрана")
    return pd.read_parquet(path)


def test_monthly_kpi_matches_pandas(fact):
    sql = mart("monthly_kpi").set_index("month")
    py = m.monthly(fact).set_index("month")
    assert sorted(sql.index) == sorted(py.index)
    assert (sql.revenue - py.revenue).abs().max() < 0.05
    assert (sql.orders - py.orders).abs().max() == 0
    assert (sql.customers - py.customers).abs().max() == 0
    assert (sql.new_customers - py.new_customers).abs().max() == 0


def test_total_revenue_matches(fact):
    sql = mart("monthly_kpi")
    assert sql.revenue.sum() == pytest.approx(fact.loc[fact.line_type == "sale", "line_revenue"].sum(), abs=0.05)


def test_cohort_sizes_are_exactly_the_customer_base(fact):
    cohort = mart("cohort_retention")
    first = cohort[cohort.month_number == 0]
    identified = fact[(fact.line_type == "sale") & fact.customer_id.notna()]
    assert first.cohort_size.sum() == identified.customer_id.nunique()
    assert (first.retention == 1.0).all(), "месяц нулевой когорты обязан быть стопроцентным"
    assert cohort.retention.max() <= 1.0


def test_rfm_covers_each_customer_once(fact):
    rfm = mart("rfm")
    identified = fact[(fact.line_type == "sale") & fact.customer_id.notna()]
    assert len(rfm) == rfm.customer_id.nunique() == identified.customer_id.nunique()
    assert rfm.recency_days.min() >= 0
    assert set(rfm.segment) <= {"ядро", "лояльные", "свежие", "остывают", "дорогой отток", "отток", "прочее"}


def test_segments_sum_to_totals(fact):
    seg = mart("rfm_segments")
    sql_total = mart("monthly_kpi").revenue.sum()
    # доли округлены до четырёх знаков, поэтому сумма даёт 1.0001, а не 1.0:
    # это округление в витрине, а не потерянные клиенты
    assert seg.customers_share.sum() == pytest.approx(1.0, abs=1e-3)
    assert seg.revenue_share.sum() == pytest.approx(1.0, abs=1e-3)
    assert seg.revenue.sum() <= sql_total
    assert seg.customers.sum() == len(mart("rfm"))


def test_country_stats_shares_and_repeat_rates(fact):
    country = mart("country_stats")
    assert country.revenue_share.sum() == pytest.approx(1.0, abs=1e-6)
    py = m.country_rollup(fact).set_index("country")
    sql = country.set_index("country")
    assert (sql.revenue - py.revenue).abs().max() < 0.05
    assert (sql.repeat_rate - py.repeat_rate).abs().max() < 1e-4


def test_region_stats_matches_pandas(fact):
    sql = mart("region_stats")
    py = m.region_monthly(fact)
    assert sorted(zip(sql.region, sql.month)) == sorted(zip(py.region, py.month))
    a = sql.set_index(["region", "month"]).sort_index()
    b = py.set_index(["region", "month"]).sort_index()
    assert (a.revenue - b.revenue).abs().max() < 0.05
    assert (a.orders - b.orders).abs().max() == 0
    assert (a.customers - b.customers).abs().max() == 0
    # группа «прочие» собрана по остатку, поэтому без потерь: иначе страна
    # просто исчезла бы из вывода
    assert sql.revenue.sum() == pytest.approx(fact.loc[fact.line_type == "sale", "line_revenue"].sum(), abs=0.05)


def test_product_stats_matches_top_products(fact):
    sql = mart("product_stats").set_index("stock_code")
    py = m.top_products(fact, limit=len(sql)).set_index("stock_code")
    assert (sql.revenue - py.revenue).abs().max() < 0.05
    assert (sql.orders - py.orders).abs().max() == 0


def test_concentration_definition_is_the_same_in_both(fact):
    sql = mart("customer_concentration").iloc[0]
    assert sql.share_for_50pct == pytest.approx(m.concentration(fact, 0.5), abs=1e-4)
    assert sql.share_for_80pct == pytest.approx(m.concentration(fact, 0.8), abs=1e-4)
