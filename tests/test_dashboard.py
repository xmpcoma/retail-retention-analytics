"""Дашборд: app.py обязан собираться без исключений и показывать те же цифры,
что лежат в витринах.

Цифры здесь записаны руками, а не пересчитаны через metrics: смысл проверки в
том, чтобы собранный дашборд совпадал с паркетом в git. Если витрина уедет,
тест это поймает, а metrics-функция — нет, потому что у неё тот же код, что у
дашборда.

Приложение читает факт в миллион строк и перерисовывается на каждый фильтр,
поэтому все тесты помечены slow.
"""
import datetime as dt
import pathlib

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.slow

# AppTest резолвит относительный путь от файла теста, а app.py сам поднимает
# sys.path на две папки вверх — поэтому путь абсолютный.
APP = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "app.py"


@pytest.fixture(scope="module")
def app():
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.run()
    assert not at.exception, f"app упал: {[e.value for e in at.exception]}"
    return at


def metrics(at) -> dict:
    return {m.label: m for m in at.metric}


def test_tabs_in_order(app):
    assert [t.label for t in app.tabs] == [
        "Обзор", "Удержание", "Сегменты", "Товары и возвраты", "Как считалось",
    ]


def test_overview_matches_marts(app):
    kpi = metrics(app)
    assert kpi["Выручка за период"].value == "£19,643,866"
    assert kpi["Заказы"].value == "41,327"
    assert kpi["Средний чек"].value == "£475"
    assert kpi["Клиентов покупало"].value == "5,853"
    assert kpi["Чистая выручка (с отменами)"].value == "£18,927,349"
    # дельта форматируется точкой и обычным минусом — на это и смотрим
    assert kpi["Чистая выручка (с отменами)"].delta == "-3.6% к валовой"


def test_gaps_match_purchase_gaps_mart(app):
    kpi = metrics(app)
    assert kpi["Медиана между покупками"].value == "25 дн."
    assert kpi["P75"].value == "62 дн."


def test_data_quality_strip(app):
    kpi = metrics(app)
    assert kpi["Строк"].value == "1,033,017"
    assert kpi["Инвойсов"].value == "53,611"
    assert kpi["Клиентов с id"].value == "5,940"
    assert kpi["Возвратов"].value == "3,393"
    assert kpi["Оптовых строк"].value == "2"


def test_region_block_is_here(app):
    assert "Рынки: Великобритания против экспорта" in [s.value for s in app.subheader]
    # таблица групп рынков: четыре группы, доли на них складываются в 100%
    region_table = next(d for d in app.dataframe if "Доля выручки" in list(d.value.columns))
    assert len(region_table.value) == 4
    assert region_table.value["Доля выручки"].sum() == pytest.approx(1.0)


def test_country_filter_changes_revenue(app):
    app.multiselect[0].set_value(["France"]).run()
    assert not app.exception
    assert metrics(app)["Выручка за период"].value == "£311,090"
    assert metrics(app)["Заказы"].value == "598"


def test_empty_period_stops_with_warning(app):
    day = (dt.date(2009, 12, 12), dt.date(2009, 12, 12))
    app.date_input[0].set_value(day).run()
    assert not app.exception
    assert not app.metric, "на пустом срезе KPI рисковать нечем"
    assert any("ни одной строки" in w.value for w in app.warning)
