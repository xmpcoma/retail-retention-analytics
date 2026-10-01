"""Параметры источника и правила отнесения строк к нетоварным."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
CURATED_DIR = ROOT / "data" / "curated"
SQL_DIR = ROOT / "sql"

SOURCE_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
SOURCE_MEMBER = "online_retail_II.xlsx"
RAW_FILE = RAW_DIR / "online_retail_II.xlsx"
FACT_FILE = CURATED_DIR / "fact_transactions.parquet"
DQ_LOG_FILE = CURATED_DIR / "dq_changes.parquet"

DATASET_TITLE = "Online Retail II"
DATASET_LICENSE = "CC BY 4.0"

# Коды нетоварных позиций. Список сверен по фактическим Description в данных:
# POST=POSTAGE, DOT=DOTCOM POSTAGE, C2=CARRIAGE, M=Manual, D=Discount,
# S=SAMPLES, B=Adjust bad debt, CRUK=CRUK Commission, плюс банковские
# списания и комиссия маркетплейса. Часть строк лежит под числовыми кодами
# ("damaged", "missing", "adjustment by ...") — их ловит pattern ниже.
# PADS (19 строк, накладки к подушкам) и GIFT (одна строка без описания) не
# включил: это позиции товара, а не проводки.
NON_MERCH_CODES = {
    "POST",
    "DOT",
    "C2",
    "M",
    "D",
    "S",
    "ADJUST",
    "ADJUST2",
    "B",
    "CRUK",
    "BANK CHARGES",
    "AMAZONFEE",
}

# Поиск по описанию нужен для правок с числовым кодом ("damages, lost bits
# etc", "Adjustment by john on 26/01/2010"), но слова в нём обязаны быть
# точными. Без исключений в нетоварные попадали "BLACK BAROQUE CARRIAGE CLOCK"
# и "FRENCH CARRIAGE LANTERN" — отсюда lookahead про clock|lantern. Слов
# wrapping и display в паттерне нет совсем: под ними 298 и 105 товарных строк
# ("TEA PARTY WRAPPING PAPER", "ROBOT MUG IN DISPLAY BOX").
NON_MERCH_PATTERN = (
    r"\b(?:postage|carriage(?!\s+(?:clock|lantern))|manual|discount|samples?"
    r"|damaged?s?|missing|adjust\w*|bad debt|dotcom|amazon|cruk)\b"
)

# Тестовые позиции вида "This is a test product.", их удаляем целиком.
TEST_CODES = {"TEST001", "TEST002"}

# Строки с количеством от этой границы считаем оптовыми. В данных их всего
# две, но одна на 80 995 шт. даёт ~1% выручки. Молча выкидывать такое из
# метрик нельзя, поэтому это флаг, а не правило очистки.
BULK_QUANTITY = 20000

# Country в исходнике — рукописный справочник: есть EIRE (устаревшее название
# Ирландии) и RSA, а отдельной строки Ireland нет вообще. Без склейки Ирландия
# потерялась бы из карты как «ещё одна экзотическая страна».
COUNTRY_MAP = {"EIRE": "Ireland"}

# Ключ, по которому строки считаются дублями. Description и CustomerID в
# него не вошли: на всём датасете это две пары строк, где совпадают инвойс,
# товар, дата, количество и цена, а описание написано по-разному
# ("BUNTING , SPOTTY" / "SPOTTY BUNTING"). Сравнение «по всем полям» оставило
# бы по две копии такой строки и удвоило бы количество.
DEDUP_KEY = ["invoice_no", "stock_code", "invoice_date", "quantity", "unit_price"]
