"""Дашборд по Online Retail II.

Запуск:
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_analytics import config as cfg          # noqa: E402
from retail_analytics import metrics as m            # noqa: E402
from retail_analytics.marts import MARTS_DIR         # noqa: E402

st.set_page_config(page_title="Онлайн-ритейл: удержание клиентов", layout="wide")

PALETTE = ["#2f6f8f", "#d9a066", "#7d9f6b", "#b8574f", "#5c6b73", "#a3829c", "#c9c9c9"]


@st.cache_data(show_spinner="читаю факт")
def load_fact() -> pd.DataFrame:
    return m.load_fact(cfg.FACT_FILE)


@st.cache_data(show_spinner="читаю витрины")
def load_mart(name: str) -> pd.DataFrame:
    path = MARTS_DIR / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def money(x: float) -> str:
    return f"£{x:,.0f}" if pd.notna(x) else "—"


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%" if pd.notna(x) else "—"


def note(text: str) -> None:
    st.caption(text)


def kpi_row(items: list[tuple[str, str, str | None]], per_row: int = 3) -> None:
    for i in range(0, len(items), per_row):
        chunk = items[i : i + per_row]
        cols = st.columns(len(chunk))
        for col, (label, value, delta) in zip(cols, chunk):
            col.metric(label, value, delta)


# ---------------------------------------------------------------- фильтрация
fact = load_fact()
if fact.empty:
    st.error("Нет data/curated/fact_transactions.parquet. Выполните python -m retail_analytics.prepare")
    st.stop()

countries_by_revenue = (
    fact[fact.line_type == "sale"].groupby("country").line_revenue.sum().sort_values(ascending=False)
)
# месяц первой покупки по всему датасету: при фильтре по периоду «новый клиент»
# должен считаться от всей истории, иначе приток завышается
FIRST_MONTH = (
    fact[(fact.line_type == "sale") & fact.customer_id.notna() & fact.is_merchandise]
    .groupby("customer_id").month_start.min()
)

with st.sidebar:
    st.header("Фильтры")
    period = st.date_input(
        "Период",
        value=(fact.invoice_date.min().date(), fact.invoice_date.max().date()),
        min_value=fact.invoice_date.min().date(),
        max_value=fact.invoice_date.max().date(),
    )
    picked = st.multiselect(
        "Страны (пусто = все)",
        options=list(countries_by_revenue.index),
        default=[],
        placeholder="например, United Kingdom",
    )
    merchandise_only = st.toggle("Только товарные строки", value=True,
                                 help="Без доставки, manual-корректировок и списаний")
    include_bulk = st.toggle("Включать оптовые строки", value=True,
                             help=f"quantity ≥ {cfg.BULK_QUANTITY} шт. — таких строк две, "
                                  "но одна даёт около 1% выручки")
    identified_only = st.toggle("Только идентифицированные клиенты", value=False,
                                help="Гостевые строки без customer_id: 22,8% товарных продаж "
                                     "и 13,1% выручки")

    st.divider()
    st.subheader("Что это за данные")
    note(
        f"{cfg.DATASET_TITLE}, {fact.invoice_date.min():%d.%m.%Y} — {fact.invoice_date.max():%d.%m.%Y}. "
        "Два листа исходного файла пересекаются на 1–9 декабря 2010, дубли при очистке схлопнуты. "
        f"Лицензия {cfg.DATASET_LICENSE}."
    )
    note(f"Строк в факте: {len(fact):,}, инвойсов: {fact.invoice_no.nunique():,}")

start, end = period if isinstance(period, tuple) and len(period) == 2 else (
    fact.invoice_date.min().date(), fact.invoice_date.max().date()
)
view = m.apply_filters(
    fact,
    period=(start, end),
    countries=picked or None,
    merchandise_only=merchandise_only,
    include_bulk=include_bulk,
    identified_only=identified_only,
)
if view.empty:
    st.warning("Под фильтры не попало ни одной строки")
    st.stop()

summary = m.summary(view)
repeat = m.repeat_stats(m.apply_filters(view, identified_only=True))
reversal_delta = (summary["net_revenue"] / summary["revenue"] - 1) if summary["revenue"] else None

st.title("Онлайн-ритейл: где тут деньги и кто их приносит")
note(
    "Вопрос, на который отвечает дашборд: выручка 2011 года держится на уровне 2010-го при "
    "минусе по заказам и вдвое меньшем притоке новых клиентов. За счёт чего это держится и "
    "сколько может продолжаться."
)

tab_overview, tab_retention, tab_segments, tab_products, tab_method = st.tabs(
    ["Обзор", "Удержание", "Сегменты", "Товары и возвраты", "Как считалось"]
)

# ---------------------------------------------------------------------- обзор
with tab_overview:
    mm = m.monthly(view, first_month=FIRST_MONTH)
    kpi_row([
        ("Выручка за период", money(summary["revenue"]), None),
        ("Заказы", f"{summary['orders']:,}", None),
        ("Средний чек", money(summary["aov"]), None),
        ("Клиентов покупало", f"{summary['customers']:,}", None),
        ("Доля повторных покупок", pct(repeat.get("repeat_rate")), None),
        ("Чистая выручка (с отменами)", money(summary["net_revenue"]),
         f"{reversal_delta * 100:.1f}% к валовой"),
    ])

    fig = go.Figure()
    fig.add_bar(x=mm.month, y=mm.revenue, name="Выручка", marker_color=PALETTE[0])
    fig.add_scatter(x=mm.month, y=mm.aov, name="Средний чек", yaxis="y2",
                    mode="lines", line=dict(color=PALETTE[1], width=2))
    fig.update_layout(
        height=380, margin=dict(t=30, b=10), legend=dict(orientation="h", y=1.08),
        yaxis=dict(title="Выручка, £"), yaxis2=dict(title="Средний чек, £", overlaying="y", side="right"),
        plot_bgcolor="#fff",
    )
    st.plotly_chart(fig, width="stretch")
    note("Ноябрь–декабрь — подарочный сезон: в ноябре 2011 выручка в 2,1 раза выше июльской "
         "(£1,45 млн против £0,69 млн). Декабрь 2011 обрезан на 9 числе, поэтому последний "
         "столбец неполный и сравнивать его с июлем нельзя.")

    left, right = st.columns([2, 1])
    with left:
        fig2 = px.area(
            mm.rename(columns={"new_customers": "Впервые купившие",
                               "returning_customers": "Вернувшиеся"}),
            x="month", y=["Впервые купившие", "Вернувшиеся"],
            labels={"value": "Клиентов", "variable": "", "month": "Месяц"},
            color_discrete_sequence=[PALETTE[0], PALETTE[2]])
        fig2.update_layout(height=320, margin=dict(t=10, b=10), legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig2, width="stretch")
        note("Синий — впервые купившие в этом месяце, зелёный — вернувшиеся. Приток новых за 2011-й "
             "упал со средних 280 человек в месяц до 128, а держится выручка как раз на зелёном: "
             "вернувшихся по месяцам стало 10 602 против 9 049 годом ранее.")
    with right:
        wd = load_mart("weekday_profile")
        if not wd.empty:
            fig3 = px.bar(wd, x="weekday", y="aov", text="aov",
                          labels={"aov": "Средний чек, £", "weekday": ""},
                          color=wd.aov > 480, color_discrete_map={True: PALETTE[0], False: PALETTE[6]})
            fig3.update_layout(height=320, margin=dict(t=10, b=10), showlegend=False)
            st.plotly_chart(fig3, width="stretch")
            note("В субботу отдел почти стоит (30 заказов за два года). В воскресенье чек £370 "
                 "против £454–516 в будни: в выходные покупает розница, в будни — опт.")

    c1, c2 = st.columns([1, 1])
    with c1:
        country = m.country_rollup(view).nlargest(10, "revenue")
        fig4 = px.bar(country, x="revenue", y="country",
                      labels={"revenue": "Выручка, £", "country": ""},
                      color="repeat_rate", color_continuous_scale="Blues_r")
        fig4.update_layout(height=360, margin=dict(t=10, b=10), yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig4, width="stretch")
        note("Цвет — доля клиентов, купивших более одного раза.")
    with c2:
        st.dataframe(
            country.assign(revenue_share=lambda d: (d.revenue_share * 100).round(1),
                           repeat_rate=lambda d: (d.repeat_rate * 100).round(1))
            .rename(columns={"revenue": "Выручка £", "orders": "Заказы", "customers": "Клиенты",
                             "revenue_share": "Доля выручки, %", "repeat_rate": "Повторные, %"
                             })[["country", "Выручка £", "Доля выручки, %", "Заказы", "Клиенты", "Повторные, %"]]
            .style.format({"Выручка £": "{:,.0f}", "Доля выручки, %": "{:.1f}",
                           "Повторные, %": "{:.1f}"}),
            width="stretch", hide_index=True,
        )

    st.subheader("Рынки: Великобритания против экспорта")
    reg = m.region_monthly(view)
    left, right = st.columns([2, 1])
    with left:
        fig_regions = px.line(
            reg, x="month", y="revenue", facet_col="region", facet_col_wrap=2,
            labels={"revenue": "Выручка, £", "month": "", "region": ""},
            color_discrete_sequence=[PALETTE[0]],
        )
        fig_regions.update_yaxes(matches=None, showticklabels=True)
        fig_regions.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        fig_regions.update_layout(height=360, margin=dict(t=10, b=10))
        st.plotly_chart(fig_regions, width="stretch")
    with right:
        totals = (
            reg.groupby("region", observed=True)
            .agg(revenue=("revenue", "sum"), orders=("orders", "sum"))
            .sort_values("revenue", ascending=False)
            .assign(revenue_share=lambda d: d.revenue / d.revenue.sum())
            .rename(columns={"revenue": "Выручка £", "orders": "Заказы",
                             "revenue_share": "Доля выручки"})
        )
        st.dataframe(
            totals[["Выручка £", "Доля выручки", "Заказы"]]
            .style.format({"Выручка £": "{:,.0f}", "Доля выручки": "{:.1%}"}),
            width="stretch",
        )
    note("Великобритания — 85,5% выручки, экспорт в Европе и на Ближнем Востоке — 13,0%, прочие "
         "страны — 1,4%. В 2011-м британская выручка стоит на месте (−0,5%) при заказах −10,6%: "
         "держится на среднем чеке, £421 в 2010-м против £469 в 2011-м. Экспорт — наоборот: "
         "заказов +19%, выручка на месте, чек упал с £894 до £756, то есть приходят мелкие "
         "покупатели. Рост «прочих стран» в 2,7 раза (с £72 тыс. до £198 тыс.) — это три "
         "австралийских инвойса на £61,4 тыс., 31% группы; называть это новым рынком нельзя.")

# --------------------------------------------------------------- удержание
with tab_retention:
    cohort = load_mart("cohort_retention")
    if cohort.empty:
        st.info("Витрины нет: выполните python -m retail_analytics.marts")
    else:
        st.subheader("Когортная матрица удержания")
        note("Когорта — месяц первой покупки идентифицированного клиента. Когортные метрики "
             "считаются по всему датасету и не меняются от фильтров: иначе «первая покупка» "
             "перестала бы быть первой.")
        matrix = m.cohort_pivot(cohort)
        fig5 = px.imshow(matrix, text_auto=".0%", aspect="auto",
                         color_continuous_scale="Blues",
                         labels={"x": "Месяц после первой покупки", "y": "Когорта", "color": "Удержание"})
        fig5.update_layout(height=520, margin=dict(t=10, b=60))
        st.plotly_chart(fig5, width="stretch")

        curve = cohort.groupby("month_number").retention.mean().reset_index()
        fig6 = px.line(curve, x="month_number", y="retention", markers=True,
                       labels={"month_number": "Месяц после покупки", "retention": "Среднее удержание"})
        fig6.update_traces(line_color=PALETTE[0], line_width=3, marker_size=7)
        fig6.update_layout(height=320, yaxis=dict(tickformat=".0%"))
        st.plotly_chart(fig6, width="stretch")

        gaps = m.purchase_gaps(view)
        cols = st.columns([1, 1, 1, 1])
        cols[0].metric("Медиана между покупками", f"{gaps.median():.0f} дн.")
        cols[1].metric("P75", f"{gaps.quantile(0.75):.0f} дн.")
        cols[2].metric("Купили снова", pct(repeat.get("repeat_rate")))
        cols[3].metric("Одна покупка за два года", pct(repeat.get("one_time_share")))
        fig7 = px.histogram(gaps.clip(upper=365), nbins=48,
                            labels={"value": "Дней между покупками", "count": "Покупок"})
        fig7.add_vline(x=gaps.median(), line_dash="dot", line_color=PALETTE[3],
                       annotation_text=f"медиана {gaps.median():.0f}", annotation_position="top right")
        fig7.update_layout(height=300, margin=dict(t=30))
        st.plotly_chart(fig7, width="stretch")
        note("Хвост после 365 дней обрезан для читаемости. 55% интервалов укладываются в месяц, "
             "медиана — 25 дней, P75 — 62: это и есть рабочий цикл покупателя. Интервалов дольше "
             "полугода всего 6,4%, и это уже не «длинный цикл», а фактически ушедший клиент.")

# ----------------------------------------------------------------- сегменты
with tab_segments:
    seg = load_mart("rfm_segments")
    rfm = load_mart("rfm")
    if seg.empty:
        st.info("Витрины нет: выполните python -m retail_analytics.marts")
    else:
        st.subheader("Клиенты: доля базы против доли выручки")
        note("RFM на 09.12.2011 по идентифицированным клиентам. Баллы считаются по квантильным "
             "порогам, а не NTILE: частота покупки принимает мало значений, на границе квантиля "
             "стоит по нескольку сотен одинаковых клиентов, и NTILE раздавал им разные баллы по "
             "порядку строк. Границы самих сегментов заданы руками в `sql/04_rfm.sql`.")
        fig8 = px.bar(
            pd.DataFrame({
                "сегмент": list(seg.segment) * 2,
                "доля": list(seg.customers_share) + list(seg.revenue_share),
                "метрика": ["клиентов"] * len(seg) + ["выручки"] * len(seg),
            }),
            x="доля", y="сегмент", color="метрика", barmode="group",
            color_discrete_map={"клиентов": PALETTE[5], "выручки": PALETTE[0]},
            labels={"доля": "Доля, ", "сегмент": "", "метрика": ""},
        )
        fig8.update_layout(height=380, xaxis=dict(tickformat=".0%"), yaxis=dict(autorange="reversed"),
                           margin=dict(t=10), legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig8, width="stretch")
        note("Разрыв между двумя столбцами и есть главный вывод: ядро — 21,5% клиентов и 67,9% выручки, "
             "отток — треть клиентов и 4,7% выручки.")

        left, right = st.columns([3, 2])
        with left:
            sample = rfm.sample(min(4000, len(rfm)), random_state=7)
            fig9 = px.scatter(sample, x="recency_days", y="monetary", color="segment",
                              log_y=True, opacity=0.55,
                              labels={"recency_days": "Дней с последней покупки", "monetary": "Выручка, £"},
                              category_orders={"segment": list(seg.segment)})
            fig9.update_layout(height=420, legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig9, width="stretch")
        with right:
            st.dataframe(
                seg.rename(columns={
                    "segment": "Сегмент", "customers": "Клиентов", "customers_share": "Доля клиентов",
                    "revenue": "Выручка £", "revenue_share": "Доля выручки",
                    "avg_revenue_per_customer": "Средний вклад", "avg_orders": "Заказов",
                    "avg_recency_days": "Дней с покупки",
                })[["Сегмент", "Клиентов", "Доля клиентов", "Выручка £", "Доля выручки", "Заказов", "Дней с покупки"]]
                .style.format({"Выручка £": "{:,.0f}", "Доля клиентов": "{:.1%}",
                               "Доля выручки": "{:.1%}", "Заказов": "{:.1f}", "Дней с покупки": "{:.0f}"}),
                width="stretch", hide_index=True, height=420,
            )
        st.subheader("Что с этим делать")
        st.markdown(
            "- **Дорогой отток** (394 клиента, £1,41 млн истории, в среднем 365 дней тишины) — "
            "единственная группа, где возврат окупается без скидки: писать надо по имени и по "
            "товарной истории человека, а не рассылкой на всю базу.\n"
            "- **Остывают** (742 клиента, £1,96 млн, 106 дней с последней покупки) — окно реакции "
            "примерно квартал: дальше кривая удержания почти плоская, с 16% до 15% на "
            "восьмом-девятом месяце.\n"
            "- **Свежие** (513 клиентов, £443 тыс.) — средний вклад £864 против £9 205 у ядра при "
            "1,5 заказа: их дешевле удержать вторым заказом, чем возвращать ушедших."
        )

# --------------------------------------------------------- товары и возвраты
with tab_products:
    st.subheader("Топ-20 товаров по выручке")
    products = m.top_products(view, limit=20)
    fig10 = px.bar(products, x="revenue", y="description",
                   labels={"revenue": "Выручка, £", "description": "", "orders": "Заказов"},
                   color=products.orders, color_continuous_scale="Blues",
                   hover_data=["stock_code", "units", "orders", "revenue_share"])
    fig10.update_layout(height=520, yaxis=dict(autorange="reversed"), margin=dict(t=10))
    st.plotly_chart(fig10, width="stretch")
    note("Четвёртая строка сверху — PAPER CRAFT, LITTLE BIRDIE: 80 995 штук на £168 470 одним "
         "инвойсом и одним клиентом. Это не бестселлер, а разовая оптовая сделка, которую тот же "
         "клиент отменил через 12 минут (C581484). Без флага «оптовые» и связки с отменами её не "
         "видно, а в топе она занимает место реального товара.")

    left, right = st.columns([2, 1])
    with left:
        rev_m = load_mart("reversal_monthly")
        fig11 = go.Figure()
        fig11.add_bar(x=rev_m.month, y=-rev_m.reversal_value, name="Отмены и возвраты, £",
                      marker_color=PALETTE[3])
        fig11.add_scatter(x=rev_m.month, y=rev_m.reversal_share, name="Доля от продаж", yaxis="y2",
                          mode="lines", line=dict(color=PALETTE[1]))
        fig11.update_layout(height=340, legend=dict(orientation="h", y=1.1),
                            yaxis=dict(title="£"), yaxis2=dict(overlaying="y", side="right",
                                                               tickformat=".0%"), margin=dict(t=40))
        st.plotly_chart(fig11, width="stretch")
        note("В среднем отменяется 7,9% товарной выручки. Декабрь 2011 — 33%: отмены ноябрьских "
             "заказов попали в декабрь, а продаж в обрезанном декабре мало.")
    with right:
        st.dataframe(load_mart("reversal_breakdown").rename(columns={
            "line_type": "Тип", "kind": "Что", "lines": "Строк", "value": "Сумма, £"
        }).style.format({"Сумма, £": "{:,.0f}"}), width="stretch", hide_index=True)
        note("Из £1,46 млн отмен £745,5 тыс. (51%) — это не возвраты товара, а финансовые "
             "корректировки: комиссия маркетплейса, bad debt, manual-проводки. Их нельзя показывать "
             "бизнесу одним числом с реальными возвратами.")

    st.subheader("Товары, которые чаще всего отменяют")
    st.dataframe(
        load_mart("reversed_products").head(10).rename(columns={
            "stock_code": "Код", "description": "Товар", "reversal_lines": "Строк",
            "reversal_value": "Сумма, £", "units_back": "Штук"
        }).style.format({"Сумма, £": "{:,.0f}"}),
        width="stretch", hide_index=True,
    )

# ------------------------------------------------------------- методология
with tab_method:
    st.subheader("Что произошло с данными при очистке")
    dq = pd.read_parquet(cfg.DQ_LOG_FILE)
    st.dataframe(dq.rename(columns={"rule": "Правило", "rows": "Строк", "note": "Комментарий"}),
                 width="stretch", hide_index=True)

    st.subheader("Что осталось в факте")
    dq_sum = load_mart("data_quality")
    if not dq_sum.empty:
        r = dq_sum.iloc[0]
        kpi_row([
            ("Строк", f"{r.lines_total:,}", None),
            ("Инвойсов", f"{r.invoices:,}", None),
            ("Клиентов с id", f"{r.customers:,}", None),
            ("Строк без клиента", f"{r.guest_lines:,}", None),
            ("Отмен", f"{r.cancellation_lines:,}", None),
            ("Возвратов", f"{r.return_lines:,}", None),
            ("Нетоварных строк", f"{r.non_merchandise_lines:,}", None),
            ("Оптовых строк", f"{r.bulk_lines:,}", None),
        ], per_row=4)
        note("Из 5 940 клиентов с заполненным id в RFM попадает 5 853: 64 встречаются только в "
             "нетоварных строках, ещё 23 — в товарных, но только в отменах и возвратах. Из "
             "235 150 строк без клиента товарных продаж 229 318 — это те самые 22,8% строк и "
             "13,1% выручки. Описание пришлось восстанавливать заглушкой у 375 строк, страна не "
             "указана у 752: в исходнике их было 756, четыре ушли вместе с дублями.")
    st.markdown(
        """
Определения, которые важно не перепутать:

- **Выручка** — только строки продаж (`line_type = sale`) и только товарные позиции. Доставка
  (DOTCOM POSTAGE, POSTAGE, CARRIAGE — £450,2 тыс. за два года) и служебные корректировки (Manual:
  £339,2 тыс. проводок против −£422,6 тыс. отмен, bad debt, комиссия Amazon) показаны отдельной
  таблицей в витрине `non_merchandise_breakdown`, а не спрятаны в общей сумме: вся не-товарная
  часть даёт −£72,6 тыс. к итогу.
- **Чистая выручка** — выручка плюс отмены и возвраты (они отрицательные).
- **AOV** — сумма инвойса, усреднённая по инвойсам. Не «средняя строка» и не «средний чек по
  строкам»: при 25 позициях в инвойсе это разные числа.
- **Новый клиент** — месяц первой покупки по всей истории, а не по выбранному окну.
- **Повторная покупка** — у клиента больше одного инвойса-продажи.
- **Когорта** — месяц первой покупки; активный месяц засчитывается один раз, сколько бы покупок
  в нём ни было.

Что здесь не так и почему я это оставил:

- **Возвраты не измеримы в деньгах.** У всех 3 393 строк возврата `unit_price = 0`, то есть сумма
  возврата в системе не фиксируется — видно только штуки.
- **22,8% товарных строк продаж без customer_id** (13,1% выручки). Это не «гости» в
  веб-аналитическом смысле, а строки, где не заполнили клиента; в выручку они входят, в удержание —
  нет.
- **Декабрь 2011 обрезан на 9 числе**, поэтому последний месяц в каждом графике неполный, а
  «всплеск отмен» в нём частично артефакт этой обрезки.
- **RFM-баллы считаются по квантильным порогам, а не NTILE.** Частота покупки принимает мало
  значений, и на границе квантиля стоит по нескольку сотен одинаковых клиентов: NTILE раздавал им
  разные баллы по порядку строк, и при пересборке витрины сегменты уезжали. С порогами группы
  неровные (1 619 / 945 / 1 148 / 1 024 / 1 117 по частоте), но один клиент не попадает в два
  сегмента одновременно.
- **Нет себестоимости, рекламы и доставки по складу.** Маржинальность и CAC посчитать нельзя,
  поэтому выводы ограничены оборотом и поведением покупателей.
        """
    )
    st.subheader("Как воспроизвести")
    st.code(
        "pip install -e .\n"
        "python -m retail_analytics.prepare   # скачает UCI и соберет факт\n"
        "python -m retail_analytics.marts     # прогонит sql/ через DuckDB\n"
        "streamlit run dashboard/app.py",
        language="bash",
    )
