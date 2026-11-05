"""Build a clean SQLite database (uzex.db) from uzex_spot_data.zip.

Run: python build_db.py   (takes ~1 minute, creates uzex.db next to this file)
"""
import csv
import io
import os
import re
import sqlite3
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ZIP_PATH = os.path.join(HERE, "uzex_spot_data.zip")
DB_PATH = os.path.join(HERE, "uzex.db")

# ---------------------------------------------------------------- normalisation
_TR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "s",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h", "ø": "", "Ø": "",
}
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def norm(text):
    """Lower-case, Cyrillic->Latin, drop everything that is not a letter or digit.

    'Карбамид' -> 'karbamid', 'O‘zbek' -> 'ozbek', 'АИ-92' -> 'ai92'.
    Registered as SQL function norm() so search works across scripts.
    """
    if text is None:
        return None
    s = str(text).lower()
    s = "".join(_TR.get(ch, ch) for ch in s)
    return _NON_ALNUM.sub("", s)


# canonical commodity name <- substrings of the lower-cased Cyrillic name (spaces/punct removed)
COMMODITIES = [
    ("Хлопок-сырец", ["хлопоксырец"]),
    ("Масло хлопковое", ["маслохлопков", "хлопковоемасло"]),
    ("Шрот хлопковый", ["шрот"]),
    ("Пряжа хлопчатобумажная", ["пряжа"]),
    ("Масло подсолнечное", ["подсолнеч"]),
    ("Мука", ["мука"]),
    ("Пшеница", ["пшениц"]),
    ("Рис", ["рис"]),
    ("Сахар", ["сахар"]),
    ("Соль пищевая", ["соль"]),
    ("Вода питьевая", ["вода"]),
    ("Комбикорм", ["комбикорм"]),
    ("Кормосмесь", ["кормосмес"]),
    ("Цемент", ["цемент"]),
    ("Кирпич", ["кирпич"]),
    ("Стекло", ["стекло"]),
    ("Гипс", ["гипс"]),
    ("Известь", ["известь"]),
    ("Пиломатериалы", ["пиломатериал"]),
    ("Эмаль", ["эмаль"]),
    ("Бензин", ["бензин"]),
    ("Дизельное топливо", ["дизел"]),
    ("Мазут", ["мазут"]),
    ("Битум", ["битум"]),
    ("Сжиженный газ", ["сжижен", "пропан"]),
    ("Карбамид", ["карбамид", "мочевин"]),
    ("Аммиачная селитра", ["селитр"]),
    ("Серная кислота", ["серн"]),
    ("Сода каустическая", ["сода"]),
    ("Азот", ["азот"]),
    ("Аргон", ["аргон"]),
    ("Трубы полиэтиленовые", ["труб"]),
    ("Полиэтилен", ["полиэтилен"]),
    ("Полипропилен", ["полипропилен"]),
    ("Поливинилхлорид", ["поливинилхлорид", "пвх"]),
    ("Проволока арматурная", ["проволок"]),
    ("Арматура", ["арматур"]),
    ("Лист стальной", ["листстальн"]),
    ("Катод медный", ["катод", "медн"]),
    ("Профиль алюминиевый", ["профил", "алюмин"]),
    ("Подшипник", ["подшипник"]),
    ("Кабель силовой", ["кабель"]),
]


def commodity_of(name):
    key = re.sub(r"[^0-9a-zа-яёўқғҳ]+", "", (name or "").lower())
    for canon, subs in COMMODITIES:
        if canon == "Рис":
            if key.startswith("рис"):
                return canon
            continue
        if any(s in key for s in subs):
            return canon
    return (name or "").strip().capitalize()


def num(s):
    if s is None:
        return None
    s = str(s).replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def iso(d):
    d = (d or "").strip()
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", d)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


# ---------------------------------------------------------------- build
SCHEMA = """
CREATE TABLE usd_rates (rate_date TEXT PRIMARY KEY, rate REAL);
CREATE TABLE brokers (broker_code TEXT PRIMARY KEY, name TEXT, inn TEXT, region TEXT, name_norm TEXT);
CREATE TABLE participants (inn TEXT PRIMARY KEY, name TEXT, region TEXT, activity TEXT, role TEXT,
    vat_payer TEXT, name_norm TEXT);
CREATE TABLE contracts (contract_no INTEGER PRIMARY KEY, product_name TEXT, commodity TEXT, brand TEXT,
    size TEXT, grade TEXT, type TEXT, class TEXT, hs_code TEXT, product_group TEXT, category TEXT,
    industry TEXT, unit TEXT, lot REAL, currency TEXT, base_price REAL, deposit TEXT, delivery_basis TEXT,
    region TEXT, warehouse_address TEXT, trade_type TEXT, contract_type TEXT, contract_form TEXT,
    payment_days INTEGER, delivery_days INTEGER, packaging TEXT, seller_inn TEXT, reg_date TEXT,
    valid_until TEXT);
CREATE TABLE deals (deal_no INTEGER PRIMARY KEY, deal_date TEXT, deal_time TEXT, year INTEGER,
    month INTEGER, trade_type TEXT, quantity REAL, amount REAL, currency TEXT, usd_rate REAL,
    amount_uzs REAL, start_price REAL, contract_no INTEGER, product_full TEXT, commodity TEXT,
    category TEXT, lot REAL, unit TEXT, volume REAL, unit_price REAL, region TEXT, contract_type TEXT,
    contract_form TEXT, status TEXT, seller_inn TEXT, buyer_inn TEXT, seller_broker TEXT,
    buyer_broker TEXT, payment_date TEXT, delivery_date TEXT, delivered_lots REAL, product_norm TEXT);
"""

INDEXES = [
    "CREATE INDEX ix_deals_date ON deals(deal_date)",
    "CREATE INDEX ix_deals_year_month ON deals(year, month)",
    "CREATE INDEX ix_deals_commodity ON deals(commodity, year)",
    "CREATE INDEX ix_deals_buyer ON deals(buyer_inn)",
    "CREATE INDEX ix_deals_seller ON deals(seller_inn)",
    "CREATE INDEX ix_deals_contract ON deals(contract_no)",
    "CREATE INDEX ix_deals_status ON deals(status)",
    "CREATE INDEX ix_deals_sb ON deals(seller_broker)",
    "CREATE INDEX ix_deals_bb ON deals(buyer_broker)",
]


def read_csv(zf, name):
    with zf.open(f"uzex_spot_data/{name}") as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))


def build(db_path=DB_PATH, zip_path=ZIP_PATH):
    tmp = db_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + SCHEMA)
    zf = zipfile.ZipFile(zip_path)

    rates = {}
    for r in read_csv(zf, "usd_rates.csv"):
        rates[iso(r["Дата"])] = num(r["Курс"])
    con.executemany("INSERT INTO usd_rates VALUES (?,?)", rates.items())

    con.executemany(
        "INSERT INTO brokers VALUES (?,?,?,?,?)",
        ((r["Код брокера"].strip(), r["Наименование"], r["ИНН"].strip(), r["Регион"], norm(r["Наименование"]))
         for r in read_csv(zf, "brokers.csv")),
    )
    con.executemany(
        "INSERT OR REPLACE INTO participants VALUES (?,?,?,?,?,?,?)",
        ((r["ИНН"].strip(), r["Наименование"], r["Регион"], r["Вид деятельности"], r["Роль"],
          r["Плательщик НДС"], norm(r["Наименование"])) for r in read_csv(zf, "participants.csv")),
    )

    contracts = {}
    rows = []
    for r in read_csv(zf, "contracts.csv"):
        no = int(r["Номер контракта"])
        cur = "USD" if "доллар" in r["Валюта"].lower() else "UZS"
        com = commodity_of(r["Наименование продукта"])
        contracts[no] = (cur, com, r["Категория товара"])
        rows.append((
            no, r["Наименование продукта"], com, r["Марка товара"], r["Размер товара"], r["Сорт товара"],
            r["Тип товара"], r["Класс товара"], r["Код ТН ВЭД"], r["Группа товара"], r["Категория товара"],
            r["Отрасль промышленности"], r["Единица измерения"], num(r["Лот"]), cur, num(r["Базисная цена"]),
            r["Сумма залога"], r["Базис поставки"], r["Регион"], r["Адрес склада"], r["Тип торгов"],
            r["Тип контракта"], r["Форма контракта"], int(num(r["Срок оплаты"]) or 0),
            int(num(r["Срок поставки"]) or 0), r["Упаковка"], r["ИНН продавца"].strip(),
            iso(r["Дата регистрации"]), iso(r["Действует до"]),
        ))
    con.executemany(f"INSERT INTO contracts VALUES ({','.join('?' * 29)})", rows)

    total = 0
    for year in range(2022, 2027):
        rows = []
        for r in read_csv(zf, f"deals_{year}.csv"):
            d = iso(r["Дата сделки"])
            qty, lot, amount = num(r["Количество"]), num(r["Лот"]), num(r["Сумма сделки"])
            cno = int(r["Номер контракта"])
            cur, com, cat = contracts.get(cno, ("UZS", commodity_of(r["Наименование товара"]), None))
            vol = qty * lot if qty is not None and lot is not None else None
            rate = rates.get(d) if cur == "USD" else None
            rows.append((
                int(r["Номер сделки"]), d, r["Время сделки"], int(d[:4]), int(d[5:7]), r["Тип торгов"],
                qty, amount, cur, rate,
                (amount * rate if rate else None) if cur == "USD" else amount,
                num(r["Стартовая цена"]), cno, r["Наименование товара"], com, cat, lot,
                r["Единица измерения"], vol, (amount / vol) if vol else None, r["Регион"],
                r["Тип контракта"], r["Форма контракта"], r["Состояние сделки"], r["ИНН продавца"].strip(),
                r["ИНН покупателя"].strip(), r["Брокер продавца"].strip(), r["Брокер покупателя"].strip(),
                iso(r["Дата оплаты"]), iso(r["Дата поставки"]), num(r["Поставлено"]),
                norm(r["Наименование товара"]),
            ))
        con.executemany(f"INSERT INTO deals VALUES ({','.join('?' * 32)})", rows)
        total += len(rows)
        print(f"  deals_{year}: {len(rows)}", flush=True)

    for ix in INDEXES:
        con.execute(ix)
    con.execute("ANALYZE")
    con.commit()
    con.close()
    os.replace(tmp, db_path)
    print(f"Done: {total} deals -> {db_path}")


if __name__ == "__main__":
    build(*(sys.argv[1:2] or []))
