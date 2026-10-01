"""Метрики для дашборда и ноутбуков.

Вход у всех функций один: fact_transactions, одна строка = одна позиция
инвойса. Продажи и отмены/возвраты нигде не смешиваются в одном числе:
`revenue` — это только продажи, `net_revenue` — продажи минус обратные
строки. Иначе AOV портился бы от строки с минусовым количеством.

Все функции, кроме apply_filters, ждут уже отфильтрованный кадр: нетоварные
строки, гости и оптовые позиции отсекаются один раз в фильтрах, а не
повторяются внутри каждой метрики.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LINE_SALE = "sale"
LINE_REVERSAL = ("cancellation", "return")


def load_fact(path) -> pd.DataFrame:
    fact = pd.read_parquet(path)
    fact["customer_id"] = fact.customer_id.astype("Int64")
    return fact


def apply_filters(
    fact: pd.DataFrame,
    *,
    period: tuple | None = None,
    countries: list[str] | None = None,
    merchandise_only: bool = True,
    include_bulk: bool = True,
    identified_only: bool = False,
) -> pd.DataFrame:
    """Фильтры сайдбара дашборда. Ничего не пересчитывает, только режет строки."""
    out = fact
    if period is not None:
        start, end = period
        # Граница «включительно» по деньгам, а не по полуночи: в факте
        # invoice_date — это дата с временем, и сравнение с Timestamp(end)
        # молча съедало последний день месяца (9 декабря 2011-го: 1 611 строк,
        # £198 тыс.).
        out = out[
            (out.invoice_date >= pd.Timestamp(start))
            & (out.invoice_date < pd.Timestamp(end) + pd.Timedelta(days=1))
        ]
    if countries:
        out = out[out.country.isin(countries)]
    if merchandise_only:
        out = out[out.is_merchandise]
    if not include_bulk:
        out = out[~out.is_bulk]
    if identified_only:
        out = out[out.customer_id.notna()]
    return out.copy()


def sales(out: pd.DataFrame) -> pd.DataFrame:
    return out[out.line_type == LINE_SALE]


def reversals(out: pd.DataFrame) -> pd.DataFrame:
    return out[out.line_type.isin(LINE_REVERSAL)]


def summary(out: pd.DataFrame) -> dict:
    """Одна карточка KPI + то, что не вынесено в графики."""
    s = sales(out)
    r = reversals(out)
    invoices = s.groupby("invoice_no", observed=True)
    invoice_revenue = invoices.line_revenue.sum()
    guests = int(s.is_guest.sum())
    return {
        "revenue": float(s.line_revenue.sum()),
        "reversal_value": float(r.line_revenue.sum()),
        "net_revenue": float(s.line_revenue.sum() + r.line_revenue.sum()),
        "orders": int(s.invoice_no.nunique()),
        "aov": float(invoice_revenue.mean()) if len(invoice_revenue) else 0.0,
        "median_order": float(invoice_revenue.median()) if len(invoice_revenue) else 0.0,
        "customers": int(s.customer_id.nunique()),
        "guest_share": guests / len(s) if len(s) else np.nan,
        "lines": len(s),
        "units": int(s.quantity.sum()),
        "cancellations": int((out.line_type == "cancellation").sum()),
        "returns": int((out.line_type == "return").sum()),
    }


MONTHLY_COLUMNS = [
    "month_start", "month", "revenue", "orders", "customers", "units", "new_customers",
    "returning_customers", "aov", "revenue_per_customer", "reversal_value",
    "net_revenue", "mom_revenue", "yoy_revenue",
]


def monthly(out: pd.DataFrame, first_month: pd.Series | None = None) -> pd.DataFrame:
    """Помесячная динамика: оборот, заказы, клиенты, новые/вернувшиеся.

    first_month — серия «клиент -> месяц первой покупки» по всему датасету. Её
    надо передавать при фильтрации по периоду, иначе клиент, купивший впервые
    в 2009-м, в выборке за 2011-й снова станет «новым», и приток завысится.
    Без параметра считаем по тому же срезу, что и остальные метрики.
    """
    s = sales(out)
    if s.empty:
        return pd.DataFrame(columns=MONTHLY_COLUMNS)

    g = s.groupby("month_start", observed=True).agg(
        revenue=("line_revenue", "sum"),
        orders=("invoice_no", "nunique"),
        customers=("customer_id", "nunique"),
        units=("quantity", "sum"),
    )

    identified = s[s.customer_id.notna()]
    if first_month is None:
        first_month = identified.groupby("customer_id", observed=True).month_start.min()
    new_by_month = first_month[first_month.isin(g.index)].value_counts()
    g["new_customers"] = g.index.map(new_by_month).fillna(0).astype("int32")
    g["returning_customers"] = g.customers - g.new_customers

    g["aov"] = g.revenue / g.orders
    g["revenue_per_customer"] = g.revenue / g.customers.replace(0, pd.NA)

    rev = reversals(out)
    g["reversal_value"] = (
        rev.groupby("month_start", observed=True).line_revenue.sum().reindex(g.index).fillna(0.0)
    )
    g["net_revenue"] = g.revenue + g.reversal_value
    # Рост считаем сдвигом по дате, а не pct_change: pct_change опирается на
    # позицию строки, и если месяца в выборке нет, YoY уедет на месяц вперёд.
    def _lag(months: int) -> pd.Series:
        base = g.revenue.reindex(g.index - pd.DateOffset(months=months)).values
        return pd.Series(base, index=g.index).replace(0, pd.NA)

    g["mom_revenue"] = g.revenue / _lag(1) - 1
    g["yoy_revenue"] = g.revenue / _lag(12) - 1
    out = g.reset_index()
    out.insert(1, "month", out.month_start.dt.strftime("%Y-%m"))
    return out


def country_rollup(out: pd.DataFrame) -> pd.DataFrame:
    s = sales(out)
    g = s.groupby("country", observed=True).agg(
        revenue=("line_revenue", "sum"),
        orders=("invoice_no", "nunique"),
        customers=("customer_id", "nunique"),
    )
    g["revenue_share"] = g.revenue / g.revenue.sum()
    identified = s[s.customer_id.notna()]
    if not identified.empty:
        per = identified.groupby(["country", "customer_id"], observed=True).invoice_no.nunique()
        g["repeat_rate"] = (per > 1).groupby(level="country").mean()
    return g.reset_index()


def top_products(out: pd.DataFrame, limit: int = 25, by: str = "revenue") -> pd.DataFrame:
    s = sales(out)
    # Группировка по одному stock_code: у кода местами два написания
    # description, и если группировать по паре, товар разъезжается на две
    # строки. В SQL то же самое делает mode(description).
    g = s.groupby("stock_code", observed=True).agg(
        revenue=("line_revenue", "sum"),
        units=("quantity", "sum"),
        orders=("invoice_no", "nunique"),
    )
    g = g.sort_values(by, ascending=False).head(limit)
    labels = (
        s[s.stock_code.isin(g.index)]
        .groupby("stock_code", observed=True)
        .description.agg(lambda x: x.value_counts().index[0])
    )
    g = g.assign(description=labels)
    g["avg_price"] = g.revenue / g.units
    g["revenue_share"] = g.revenue / s.line_revenue.sum()
    return g.reset_index()[["stock_code", "description", "revenue", "units", "orders",
                            "avg_price", "revenue_share"]]


def cancellations_monthly(out: pd.DataFrame) -> pd.DataFrame:
    r = reversals(out)
    s = sales(out)
    if r.empty:
        return pd.DataFrame(columns=["month_start", "cancellations", "returns", "reversal_value", "revenue"])
    g = r.groupby("month_start", observed=True).agg(
        cancellations=("line_type", lambda x: int((x == "cancellation").sum())),
        returns=("line_type", lambda x: int((x == "return").sum())),
        reversal_value=("line_revenue", "sum"),
    )
    g["revenue"] = s.groupby("month_start", observed=True).line_revenue.sum()
    g["share_of_sales"] = -g.reversal_value / g.revenue
    out = g.reset_index()
    out.insert(1, "month", out.month_start.dt.strftime("%Y-%m"))
    return out


def reversal_reasons(out: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    """Чем именно обораны строки: по нетоварным позициям и товарам."""
    r = reversals(out)
    if r.empty:
        return pd.DataFrame(columns=["reason", "value"])
    grouped = r.groupby(np.where(r.is_merchandise, r.description, "нетоварные позиции"), observed=True).agg(
        value=("line_revenue", "sum"),
        lines=("line_revenue", "size"),
    )
    return grouped.sort_values("value").head(limit).reset_index(names="reason")


def customer_revenue(out: pd.DataFrame) -> pd.DataFrame:
    s = sales(out)
    s = s[s.customer_id.notna()]
    return s.groupby("customer_id", observed=True).agg(
        revenue=("line_revenue", "sum"),
        orders=("invoice_no", "nunique"),
        first_purchase=("invoice_date", "min"),
        last_purchase=("invoice_date", "max"),
    )


def pareto(out: pd.DataFrame) -> pd.DataFrame:
    """Кумулятивная доля выручки по клиентам, от большего к меньшему."""
    rev = customer_revenue(out).revenue.sort_values(ascending=False).to_frame("revenue")
    rev["share"] = rev.revenue / rev.revenue.sum()
    rev["cum_share"] = rev.share.cumsum()
    rev["rank"] = range(1, len(rev) + 1)
    rev["customer_share"] = rev["rank"] / len(rev)
    return rev.reset_index()


def concentration(out: pd.DataFrame, revenue_share: float = 0.8) -> float:
    """Какой доле клиентов принадлежит revenue_share всей выручки.

    Считаем «сколько топ-клиентов нужно, чтобы набрать долю», а не «сколько
    клиентов ровно уложились в неё»: иначе первый же клиент крупнее 50%
    давал бы пустой выбор и nan.
    """
    p = pareto(out)
    if p.empty:
        return np.nan
    needed = int((p.cum_share < revenue_share).sum()) + 1
    return min(needed, len(p)) / len(p)


def purchase_gaps(out: pd.DataFrame) -> pd.Series:
    """Дни между соседними покупками одного клиента (по всей выборке)."""
    s = sales(out)
    days = s[s.customer_id.notna()].groupby(["customer_id", "invoice_date"], observed=True).line_revenue.sum()
    if days.empty:
        return pd.Series(dtype="float64")
    per_customer = days.reset_index().sort_values(["customer_id", "invoice_date"])
    return per_customer.groupby("customer_id", observed=True).invoice_date.diff().dt.days.dropna()


def cohort_pivot(long_df: pd.DataFrame, value: str = "retention") -> pd.DataFrame:
    """Из длинной когортной таблицы в матрицу: строки — когорты, столбцы — месяцы."""
    return long_df.pivot(index="cohort", columns="month_number", values=value).sort_index()


def repeat_stats(out: pd.DataFrame) -> dict:
    """Сколько клиентов купили повторно и через сколько дней после первой покупки."""
    s = sales(out)
    s = s[s.customer_id.notna()]
    if s.empty:
        return {}
    per = s.groupby("customer_id", observed=True).invoice_date.agg(["min", "max", "nunique"])
    gaps = (per["max"] - per["min"]).dt.days
    bought_again = per["nunique"] > 1
    return {
        "customers": int(len(per)),
        "repeat_rate": float(bought_again.mean()),
        "one_time_share": float(1 - bought_again.mean()),
        "median_gap_days": float(gaps[bought_again].median()) if bought_again.any() else np.nan,
        "p75_gap_days": float(gaps[bought_again].quantile(0.75)) if bought_again.any() else np.nan,
        "avg_orders": float(per["nunique"].mean()),
    }
