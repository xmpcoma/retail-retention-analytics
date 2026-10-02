"""Паркет витрин лежит в git, поэтому он обязан быть не «одной из версий», а
воспроизведённым результатом: та же база -> те же байты.

История вопроса: в rfm не было ORDER BY, и строки раскладывались в порядке,
который выбрал движок. На двух пересборках это давало разные файлы при
одинаковом содержимом, а в rfm_segments две возвратные строки с £0.00
переставлялись местами. Сейчас у каждой финальной таблицы есть ORDER BY с
уникальным ключом.

Тест пересобирает все sql/ в DuckDB, поэтому помечен slow: локально можно
`pytest -m "not slow"`, в CI он прогоняется целиком.
"""
import hashlib

import pytest

from retail_analytics import config as cfg
from retail_analytics import marts


def digest(path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


@pytest.mark.slow
def test_rebuild_reproduces_committed_parquet(tmp_path):
    if not cfg.FACT_FILE.exists():
        pytest.skip("нет fact_transactions.parquet")
    committed = sorted(marts.MARTS_DIR.glob("*.parquet"))
    if not committed:
        pytest.skip("витрины не собраны")

    rebuilt = marts.build(out_dir=tmp_path)
    assert len(rebuilt) == len(committed), "пересборка дала другое число витрин"
    for path in committed:
        fresh = tmp_path / path.name
        assert fresh.exists(), f"пересборка не создала {path.name}"
        assert digest(fresh) == digest(path), f"{path.name} пересобралась другими байтами"
