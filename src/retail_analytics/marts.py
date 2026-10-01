"""Проигрывает sql/*.sql в DuckDB и раскладывает таблицы по parquet.

Запуск:
    python -m retail_analytics.marts [--preview]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import duckdb
import pandas as pd

from . import config as cfg

MARTS_DIR = cfg.CURATED_DIR / "marts"
_TABLE_RE = re.compile(r"CREATE\s+OR\s+REPLACE\s+TABLE\s+(\w+)", re.IGNORECASE)


def load_sql(con: duckdb.DuckDBPyConnection, fact_path: Path) -> list[str]:
    """Выполняет все sql-файлы по порядку имён и возвращает созданные таблицы."""
    tables: list[str] = []
    for path in sorted(cfg.SQL_DIR.glob("*.sql")):
        script = path.read_text(encoding="utf-8").replace("{{FACT_PATH}}", fact_path.as_posix())
        tables += _TABLE_RE.findall(script)
        con.execute(script)
    return tables


def build(fact_path: Path = cfg.FACT_FILE, out_dir: Path = MARTS_DIR) -> list[str]:
    if not fact_path.exists():
        raise FileNotFoundError(f"нет {fact_path}, сначала выполни: python -m retail_analytics.prepare")
    con = duckdb.connect()
    tables = load_sql(con, fact_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    for table in tables:
        target = out_dir / f"{table}.parquet"
        con.execute(f"COPY {table} TO '{target.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()
    return tables


def show(tables: list[str], rows: int = 8) -> None:
    for table in tables:
        df = pd.read_parquet(MARTS_DIR / f"{table}.parquet")
        print(f"\n--- {table} ({len(df):,} строк)")
        with pd.option_context("display.width", 200, "display.max_columns", 12):
            print(df.head(rows).to_string(index=False))


def main() -> None:
    ap = argparse.ArgumentParser(description="Собрать витрины из sql/")
    ap.add_argument("--preview", action="store_true", help="напечатать первые строки каждой витрины")
    args = ap.parse_args()

    tables = build()
    total = sum((MARTS_DIR / f"{t}.parquet").stat().st_size for t in tables)
    print(f"витрин: {len(tables)}, {', '.join(tables)}")
    print(f"папка {MARTS_DIR} ({total / 1e6:.1f} МБ)")
    if args.preview:
        show(tables)


if __name__ == "__main__":
    main()
