"""Загрузка Online Retail II и приведение к виду, из которого считается выручка.

Запуск:
    python -m retail_analytics.prepare [--force-download]
"""
from __future__ import annotations

import argparse
import io
import re
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

from . import config as cfg

# Заголовки в обоих листах файла: Invoice, StockCode, Description, Quantity,
# InvoiceDate, Price, Customer ID, Country. В коде нужны имена в snake_case, а
# «Customer ID» с пробелом читать через df[...] неудобно. Словарь заодно
# принимает и написание InvoiceNo/UnitPrice/CustomerID: встречается в файлах
# той же серии, и падать на нём незачем.
COLUMN_ALIASES = {
    "Invoice": "invoice_no",
    "InvoiceNo": "invoice_no",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "unit_price",
    "UnitPrice": "unit_price",
    "Customer ID": "customer_id",
    "CustomerID": "customer_id",
    "Country": "country",
}

# dict.fromkeys, а не list(...): у invoice_no/unit_price/customer_id по два
# возможных исходных имени, и наивный список значений выбрал бы эти колонки
# по дважды.
REQUIRED = list(dict.fromkeys(COLUMN_ALIASES.values()))

FACT_COLUMNS = [
    "invoice_no",
    "customer_id",
    "stock_code",
    "description",
    "country",
    "invoice_date",
    "month_start",
    "quantity",
    "unit_price",
    "line_revenue",
    "line_type",
    "is_merchandise",
    "is_guest",
    "is_bulk",
]


def download(force: bool = False) -> Path:
    """Тянет xlsx из архива UCI. Повторное скачивание только по --force."""
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    if cfg.RAW_FILE.exists() and not force:
        return cfg.RAW_FILE

    print(f"скачиваю {cfg.SOURCE_URL}")
    with urllib.request.urlopen(cfg.SOURCE_URL, timeout=300) as resp:
        blob = resp.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        if cfg.SOURCE_MEMBER not in zf.namelist():
            raise FileNotFoundError(f"в архиве нет {cfg.SOURCE_MEMBER}: {zf.namelist()}")
        cfg.RAW_FILE.write_bytes(zf.read(cfg.SOURCE_MEMBER))
    print(f"сохранено: {cfg.RAW_FILE} ({cfg.RAW_FILE.stat().st_size / 1e6:.1f} МБ)")
    return cfg.RAW_FILE


def _as_id(value) -> str:
    """Инвойсы и коды товаров лежат вперемешку: 489225 числом и 'C556445'
    строкой. Приводим к одной строке в верхнем регистре — в файле 3 471 код
    вида '72349b', и без upper это '72349B' из другой строки считается другим
    товаром.
    """
    return str(value).strip().upper()


def read_source(path: Path) -> tuple[pd.DataFrame, list[dict]]:
    """Читает все листы, приводит заголовки, возвращает лог по листам."""
    xl = pd.ExcelFile(path)
    frames, log = [], []
    for sheet in xl.sheet_names:
        df = xl.parse(sheet).rename(columns=COLUMN_ALIASES)
        missing = [c for c in REQUIRED if c not in df.columns]
        if missing:
            raise ValueError(f"лист {sheet}: нет колонок {missing}")
        frames.append(df[REQUIRED])
        # границы листа идут в лог, а лог собирается до normalize_types
        days = pd.to_datetime(df.invoice_date)
        log.append(
            {
                "rule": f"лист «{sheet}» прочитан",
                "rows": len(df),
                "note": f"{days.min():%Y-%m-%d} — {days.max():%Y-%m-%d}",
            }
        )
    return pd.concat(frames, ignore_index=True), log


def normalize_types(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["invoice_no"] = df.invoice_no.map(_as_id)
    df["stock_code"] = df.stock_code.map(_as_id)
    for col in ("description", "country"):
        df[col] = (
            df[col].astype("string").str.strip().str.replace(r"\s+", " ", regex=True).replace("", pd.NA)
        )
    df["invoice_date"] = pd.to_datetime(df.invoice_date)
    df["quantity"] = df.quantity.astype("int32")
    # цены в xlsx лежат как float с артефактами (1.6499999999999998);
    # для денег это лишний шум при группировках и сравнениях
    df["unit_price"] = df.unit_price.astype(float).round(2)
    df["customer_id"] = pd.to_numeric(df.customer_id, errors="coerce").astype("Int64")
    df["country"] = df.country.replace(cfg.COUNTRY_MAP)
    return df


def tag_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    cancelled = df.invoice_no.str.startswith("C")
    df["line_type"] = "sale"
    df.loc[cancelled, "line_type"] = "cancellation"
    # Отрицательное количество внутри обычного инвойса — возврат или
    # корректировка строки, а не отмена документа. Таких строк больше трёх
    # тысяч, и валить их в одну корзину с отменами нельзя: разные процессы.
    df.loc[~cancelled & (df.quantity < 0), "line_type"] = "return"

    pattern = re.compile(cfg.NON_MERCH_PATTERN, flags=re.IGNORECASE)
    by_code = df.stock_code.isin(cfg.NON_MERCH_CODES)
    by_desc = df.description.fillna("").map(lambda s: bool(pattern.search(s)))
    df["is_merchandise"] = ~(by_code | by_desc)
    df["is_guest"] = df.customer_id.isna()
    df["is_bulk"] = df.quantity >= cfg.BULK_QUANTITY
    return df


def drop_doubles(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Убирает точные копии строк по деловому ключу.

    Главная причина: листы пересекаются по 1-9 декабря 2010, и инвойсы из
    этого окна лежат в обоих. Плюс внутри одного листа есть идентичные строки.
    """
    before = len(df)
    out = df.drop_duplicates(subset=cfg.DEDUP_KEY, keep="first")
    return out, before - len(out)


def drop_test_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    before = len(df)
    out = df[~df.stock_code.isin(cfg.TEST_CODES)]
    return out, before - len(out)


def backfill_description(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Подтягивает описание товара из других строк с тем же кодом.

    У части строк описание пустое, при этом код товара валидный и встречается
    в других инвойсах. Оставить их нельзя: в таблице товаров NaN-товар
    занял бы первую строчку.
    """
    df = df.copy()
    known = (
        df.loc[df.description.notna() & df.is_merchandise, ["stock_code", "description"]]
        .groupby("stock_code")
        .description.agg(lambda s: s.mode().iat[0])
    )
    need = df.description.isna() & df.stock_code.isin(known.index)
    df.loc[need, "description"] = df.loc[need, "stock_code"].map(known)
    return df, int(need.sum())


def build_fact(path: Path | None = None, force: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_path = path or download(force)
    df, log = read_source(raw_path)
    mapped_country = int(df.country.astype("string").str.strip().isin(cfg.COUNTRY_MAP).sum())

    df = normalize_types(df)
    df = tag_rows(df)

    df, n_dupes = drop_doubles(df)
    log.append({"rule": "точные дубликаты удалены", "rows": n_dupes, "note": "ключ: " + ", ".join(cfg.DEDUP_KEY)})

    df, n_test = drop_test_rows(df)
    log.append({"rule": "тестовые позиции удалены", "rows": n_test, "note": ", ".join(sorted(cfg.TEST_CODES))})

    df, n_backfilled = backfill_description(df)
    log.append({"rule": "описание подтянуто по stock_code", "rows": n_backfilled, "note": "пустые description"})
    log.append({"rule": "страна склеена по справочнику", "rows": mapped_country,
                "note": ", ".join(f"{k} -> {v}" for k, v in cfg.COUNTRY_MAP.items())})

    df["description"] = df.description.fillna("<не удалось восстановить>")
    df["line_revenue"] = (df.quantity * df.unit_price).round(2)
    df["month_start"] = df.invoice_date.dt.to_period("M").dt.start_time

    log.append({"rule": "нетоварные строки помечены, не удалены",
                "rows": int((~df.is_merchandise).sum()),
                "note": "доставка, manual, списания и прочее"})
    log.append({"rule": "страна не восстанавливалась",
                "rows": int((df.country == "Unspecified").sum()),
                "note": "Unspecified оставлен отдельной категорией"})
    log.append({"rule": "строки без customer_id помечены как гостевые",
                "rows": int(df.is_guest.sum()),
                "note": "в выручку входят, в метрики удержания нет"})
    log.append({"rule": "оптовые строки помечены флагом",
                "rows": int(df.is_bulk.sum()),
                "note": f"quantity >= {cfg.BULK_QUANTITY}"})
    returns = df[df.line_type == "return"]
    log.append({
        "rule": "возвраты оставлены как есть",
        "rows": len(returns),
        # в исходнике у всех строк возврата unit_price = 0, то есть сумма
        # возврата в данных не измеряется вообще — только штуки.
        "note": f"обнулённых цен: {(returns.unit_price == 0).sum()} из {len(returns)}",
    })

    fact = df[FACT_COLUMNS].sort_values(["invoice_date", "invoice_no", "stock_code"]).reset_index(drop=True)
    return fact, pd.DataFrame(log, columns=["rule", "rows", "note"])


def main() -> None:
    ap = argparse.ArgumentParser(description="Собрать fact_transactions.parquet")
    ap.add_argument("--force-download", action="store_true")
    ap.add_argument("--out", type=Path, default=cfg.FACT_FILE)
    args = ap.parse_args()

    fact, dq_log = build_fact(force=args.force_download)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fact.to_parquet(args.out, compression="zstd")
    dq_log.to_parquet(cfg.DQ_LOG_FILE, compression="zstd")

    sales = fact[(fact.line_type == "sale") & fact.is_merchandise]
    print(f"строк в факте: {len(fact):,}")
    print(f"товарная выручка продаж: {sales.line_revenue.sum():,.0f}")
    print(f"инвойсов: {sales.invoice_no.nunique():,}, клиентов: {sales.customer_id.nunique():,}")
    print(f"период: {fact.invoice_date.min():%Y-%m-%d} — {fact.invoice_date.max():%Y-%m-%d}")
    print(f"{args.out} ({args.out.stat().st_size / 1e6:.1f} МБ), лог чистки -> {cfg.DQ_LOG_FILE.name}")


if __name__ == "__main__":
    main()
