"""UZEX deals agent: question (RU/UZ) -> LLM writes SQL -> SQLite -> verified answer."""
import json
import os
import re
import sqlite3
import time

import requests

from build_db import COMMODITIES, DB_PATH, build, norm

# Order = priority. Each model has its own free-tier quota, so a longer chain = more capacity.
MODEL_CHAIN = [
    ("gemini", os.environ.get("GEMINI_MODEL")),
    ("gemini", "gemini-3.5-flash"),
    ("groq", os.environ.get("GROQ_MODEL")),
    ("groq", "openai/gpt-oss-120b"),
    ("gemini", "gemini-3.8-flash"),
    ("gemini", "gemini-3.5-flash-lite"),
    ("groq", "qwen/qwen3.8-27b"),
    ("gemini", "gemini-3.1-flash-lite"),
    ("groq", "openai/gpt-oss-20b"),
    ("gemini", "gemini-flash-lite-latest"),
]
MAX_ROWS = 200          # rows returned by run_sql
ROWS_TO_LLM = 30        # rows shown to the model
MAX_FEEDBACK_CHARS = 3500
SQL_TIMEOUT = 15        # seconds
MAX_STEPS = 6

NO_DATA = {
    "ru": "В данных нет такой информации.",
    "uz": "Maʼlumotlarda bunday maʼlumot yoʻq.",
}


# ---------------------------------------------------------------- database
def ensure_db():
    if not os.path.exists(DB_PATH):
        build()


def connect():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    con.create_function("norm", 1, norm, deterministic=True)

    def authorizer(action, *_):
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

    con.set_authorizer(authorizer)
    return con


def run_sql(con, sql):
    """Execute one read-only SELECT. Returns (columns, rows, truncated)."""
    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Only one statement is allowed")
    if not re.match(r"(?is)^\s*(select|with)\b", sql):
        raise ValueError("Only SELECT queries are allowed")
    deadline = time.time() + SQL_TIMEOUT
    con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
    try:
        cur = con.execute(sql)
        rows = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise ValueError("Query timed out, simplify it") from e
        raise
    finally:
        con.set_progress_handler(None, 0)
    cols = [d[0] for d in cur.description or []]
    return cols, rows[:MAX_ROWS], len(rows) > MAX_ROWS


# ---------------------------------------------------------------- language
def detect_lang(text):
    t = text.lower()
    if re.search(r"[ўқғҳ]", t):
        return "uz"
    cyr = len(re.findall(r"[а-яё]", t))
    lat = len(re.findall(r"[a-z]", t))
    uz_words = r"\b(nechta|qancha|kim|qaysi|bitim|yil|oy|bo.?yicha|sotgan|sotib|haqida|eng|necha|qilgan|tuzilgan)\b"
    if lat > cyr or re.search(uz_words, t):
        return "uz"
    return "ru"


# ---------------------------------------------------------------- prompt
COMMODITY_LIST = ", ".join(c for c, _ in COMMODITIES)

SYSTEM_PROMPT = f"""You are an analyst of the commodity exchange deals register (UZEX). You answer questions
in Russian or Uzbek using ONLY a SQLite database. You never invent facts.

DATABASE (SQLite). All money columns are numbers. Dates are TEXT 'YYYY-MM-DD'.
deals — 500 000 deals, 2022-01-03 … 2026-10-30
  deal_no INTEGER (deal number), deal_date, deal_time, year, month,
  trade_type ('Английский аукцион','Обратный аукцион','Двусторонний аукцион'),
  quantity (lots bought), lot (units per lot), unit ('тонна','килограмм','литр','метр','штука','куб.метр','кв.метр'),
  volume = quantity*lot (in units), amount (deal sum in contract currency), currency ('UZS' or 'USD'),
  usd_rate (rate on deal date, only USD deals), amount_uzs (sum in UZS for ALL deals; use it for money totals),
  unit_price = amount/volume (contract currency per unit), start_price (per unit),
  contract_no, product_full (product text as in register), commodity (clean product name, see list),
  category, region (seller warehouse region, Uzbek Latin e.g. 'Toshkent shahri','Namangan viloyati'),
  contract_type ('Внутренний' domestic / 'Экспортный' export, export deals are in USD),
  contract_form ('Спот','Форвард','Фьючерс'),
  status: 'Новый','Не подписан','Заключен','Ждёт оплату','Оплачен','Исполнен','Исполнен(Частично)','Аннулирован(Не оплачен)'
    (annulled = 'Аннулирован(Не оплачен)', the deal did not happen),
  seller_inn, buyer_inn (TEXT, 9 digits -> participants.inn), seller_broker, buyer_broker (TEXT 'BK001' -> brokers.broker_code),
  payment_date, delivery_date (NULL if not yet), delivered_lots, product_norm (normalised product_full).
contracts — contract cards: contract_no, product_name, commodity, brand, size, grade, type, class, hs_code,
  product_group, category, industry, unit, lot, currency, base_price, deposit, delivery_basis, region (Russian),
  warehouse_address, trade_type, contract_type, contract_form, payment_days, delivery_days, packaging,
  seller_inn, reg_date, valid_until.
participants — companies: inn, name, region, activity, role ('Продавец'/'Покупатель'), vat_payer, name_norm.
brokers — broker_code, name, inn, region, name_norm.
usd_rates — rate_date, rate (UZS per 1 USD).

commodity values: {COMMODITY_LIST}.
Uzbek product words: paxta=Хлопок-сырец, paxta yog‘i=Масло хлопковое, kunjara/shrot=Шрот хлопковый,
ip/kalava=Пряжа хлопчатобумажная, un=Мука, bug‘doy=Пшеница, guruch=Рис, shakar=Сахар, tuz=Соль пищевая,
suv=Вода питьевая, sement=Цемент, g‘isht=Кирпич, shisha=Стекло, yog‘och/taxta=Пиломатериалы,
benzin=Бензин, dizel/solyarka=Дизельное топливо, gaz=Сжиженный газ, o‘g‘it: karbamid=Карбамид, selitra=Аммиачная селитра,
mis=Катод медный, quvur=Трубы полиэтиленовые, kungaboqar yog‘i=Масло подсолнечное.

SEARCH RULES
- Text is written inconsistently (Cyrillic/Latin, upper/lower case, '1 сорт'/'1-сорта'). Never compare names with = or
  plain LIKE. Use the SQL function norm(): it lower-cases, transliterates Cyrillic to Latin and removes spaces/punctuation.
  Products: filter by commodity = '<value from list>'; for brand/grade add product_norm LIKE '%' || norm('АИ-92') || '%'.
  Companies: participants.name_norm LIKE '%' || norm('Name') || '%'. Brokers similarly with brokers.name_norm.
- "Deal №N"/"bitim N" -> deals.deal_no; "contract/shartnoma N" -> contract_no; 9 digits -> INN; BKnnn -> broker_code.
- Always JOIN participants/brokers to show names next to INN/codes. GROUP BY inn (not by name) for company rankings.
- Money: for totals across currencies use amount_uzs and say "сум". For one deal show amount with its currency.
- UNITS (very important): one commodity can be sold in different units (e.g. Бензин in 'тонна' AND 'литр').
  NEVER add up or average volume/unit_price over different units. Any query with volume or unit_price must
  GROUP BY unit (or filter one unit). Price per unit = SUM(amount_uzs)/SUM(volume) per unit (weighted average).
  'за тонну' with unit 'килограмм' -> multiply by 1000 in SQL. Litres cannot be converted to tonnes (no density in
  the data): report the price per litre separately and say so. In the answer list every unit that exists.
- When counting deals of a commodity, also show how many deals each spelling (product_full) has if there are
  several (GROUP BY product_full, up to 5 lines), because sellers write the same product differently.
- If the user quotes a concrete product name/spelling (e.g. 'Мочевина (карбамид) Марка Б'), first give the number for
  exactly that spelling (product_norm = norm('<quoted text>')), then the total for the whole commodity.
- State the status filter unambiguously: "включая аннулированные" / "bekor qilinganlar bilan" or
  "без аннулированных" / "bekor qilinganlarsiz". If the user gave no period, say "за весь период 2022–2026".
- Broker or company question: give the full card — name, INN, region (and activity/role for companies) and the
  number of deals (as seller / as buyer, or as seller broker / buyer broker). Describe a company only with fields
  from the database; never invent its type of business.
- Unless the user asks otherwise count ALL deals (any status). If the question is about sales/purchases volume or
  "who sold most" exclude annulled deals and mention it.
- Do ALL arithmetic in SQL (SUM, COUNT, AVG, ROUND(x,2), percentages). Never compute numbers yourself.
- LIMIT big result lists (top-N, at most 20 rows).

PROTOCOL — reply with ONE JSON object and nothing else:
  {{"sql": "<one SELECT query>"}}      to run a query (you will get the result), or
  {{"answer": "<final answer>"}}       when done.
Answer rules:
- Language: the same as the question ({{lang}}). Uzbek answers in Latin script.
- Every number in the answer must be copied from query results (you may round to 2 decimals and use spaces as thousand
  separators: 1 234 567.89). Do not write "млн/млрд". Do not add numbers that are not in the results.
- If the result is empty or the data has no such information, answer exactly: "{NO_DATA['ru']}" (ru) or
  "{NO_DATA['uz']}" (uz). Never guess.
- Be short: 1-6 sentences or a short numbered list. Mention filters you used (year, status, currency).
"""


# ---------------------------------------------------------------- LLM providers
class LLMError(Exception):
    pass


def _gemini(messages, model):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("no GEMINI_API_KEY")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"]
    body = {
        "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
        "contents": contents,
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      headers={"x-goog-api-key": key}, json=body, timeout=30)
    if r.status_code != 200:
        raise LLMError(f"gemini {model} {r.status_code}: {r.text[:200]}")
    try:
        return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError) as e:
        raise LLMError(f"gemini bad response: {r.text[:200]}") from e


def _groq(messages, model):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMError("no GROQ_API_KEY")
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "messages": messages, "temperature": 0,
                            "response_format": {"type": "json_object"}}, timeout=45)
    if r.status_code != 200:
        raise LLMError(f"groq {model} {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


PROVIDERS = [(n, _gemini if n == "gemini" else _groq, m) for n, m in MODEL_CHAIN if m]
_dead_until = {}  # provider/model -> timestamp when to retry


def chat(messages, max_wait=40):
    """Try providers in order; on rate limits wait (up to max_wait s in total) and retry."""
    errors = []
    waited = 0
    while True:
        for name, fn, model in PROVIDERS:
            if _dead_until.get(model, 0) > time.time():
                continue
            try:
                return fn(messages, model), f"{name}:{model}"
            except (LLMError, requests.RequestException) as e:
                se = str(e)
                errors.append(se)
                permanent = " 404" in se or " 401" in se or " 403" in se or se.startswith("no ")
                daily = "exceeded your current quota" in se or "per day" in se
                _dead_until[model] = time.time() + (3600 if permanent else 900 if daily else 20)
        alive_at = [t for m, t in _dead_until.items() if t - time.time() < 3000]
        if not alive_at or waited >= max_wait:
            raise LLMError("; ".join(errors[-4:]) or "no LLM available")
        pause = max(1.0, min(min(alive_at) - time.time(), max_wait - waited))
        time.sleep(pause)
        waited += pause


def parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"answer": text}


# ---------------------------------------------------------------- verification
NUM_RE = re.compile(r"(?<![\w.,])\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\d])|\d+(?:[.,]\d+)?")
DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")


def _numbers_in_text(text):
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    text = DATE_RE.sub(lambda m: f"{m.group(1)} ; {m.group(2)} ; {m.group(3)}", text)
    text = re.sub(r"\b[A-Za-z]{1,3}-?\d+(?:[/.,-]\d+)*", " ", text)  # codes like BK058, АИ-92, PP-2310
    text = re.sub(r"(?i)\b(?:аи|ai|цем|cem|pp|hd|ll|pe|ne|м|m|г|g|вр)-?\s?\d+[\d/.,]*", " ", text)
    out = []
    for tok in NUM_RE.findall(text):
        raw = tok
        compact = re.sub(r"[   ]", "", raw).replace(",", ".")
        try:
            val = float(compact)
        except ValueError:
            continue
        parts = None
        if re.search(r"[   ]", raw):
            parts = [float(p.replace(",", ".")) for p in re.split(r"[   ]+", raw) if p]
        out.append((raw, val, parts))
    return out


def _known_numbers(question, results):
    known = set()

    def add_text(s):
        for _, v, parts in _numbers_in_text(str(s)):
            known.add(v)
            known.update(parts or [])

    known.update(float(y) for y in range(2022, 2027))  # dataset period
    add_text(question)
    known.update(float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", question))
    for _, rows in results:
        for row in rows:
            for v in row:
                if isinstance(v, (int, float)) and v is not None:
                    known.add(float(v))
                elif v is not None:
                    add_text(v)
                    for d in re.findall(r"(\d{4})-(\d{2})-(\d{2})", str(v)):
                        known.update(float(x) for x in d)
    return known


def _matches(val, known):
    if abs(val) <= 10 and float(val).is_integer():  # list markers, small counts in wording
        return True
    for k in known:
        k = abs(k)
        for scale in (1, 1000, 1e6, 1e9):
            kk = k / scale
            if kk == val or (kk != 0 and abs(kk - val) <= abs(kk) * 0.005):
                return True
        if abs(k * 100 - val) <= max(abs(val) * 0.005, 0.01):  # share -> percent
            return True
    return False


def verify(answer, question, results):
    known = _known_numbers(question, results)
    bad = []
    for raw, val, parts in _numbers_in_text(answer):
        if _matches(val, known):
            continue
        if parts and all(_matches(p, known) for p in parts):
            continue
        bad.append(raw)
    return bad


# ---------------------------------------------------------------- fallback lookup (no LLM)
def direct_lookup(con, question):
    q = question
    results = []
    m = re.search(r"\bBK\s?(\d{3})\b", q, re.I)
    if m:
        sql = f"SELECT broker_code, name, inn, region FROM brokers WHERE broker_code = 'BK{m.group(1)}'"
        results.append(sql)
    for inn in re.findall(r"(?<!\d)(\d{9})(?!\d)", q):
        results.append(f"SELECT inn, name, region, activity, role, vat_payer FROM participants WHERE inn = '{inn}'")
    for n in re.findall(r"(?<!\d)(\d{6})(?!\d)", q):
        if re.search(r"(?i)контракт|shartnoma|contract", q):
            results.append(f"SELECT contract_no, product_name, brand, unit, lot, currency, base_price, region, "
                           f"seller_inn, reg_date, valid_until FROM contracts WHERE contract_no = {n}")
        else:
            results.append(
                "SELECT d.deal_no, d.deal_date, d.product_full, d.quantity, d.unit, d.amount, d.currency, d.status, "
                "s.name AS seller, b.name AS buyer FROM deals d LEFT JOIN participants s ON s.inn = d.seller_inn "
                f"LEFT JOIN participants b ON b.inn = d.buyer_inn WHERE d.deal_no = {n}")
    return results


def mixes_units(sql):
    """True if the query aggregates volume/unit_price but never mentions the unit column."""
    s = sql.lower()
    if not re.search(r"\b(sum|avg|min|max|total)\s*\([^)]*\b(volume|unit_price)\b", s):
        return False
    s = re.sub(r"\bunit_price\b", "", s)
    return not re.search(r"\bunit\b", s)


# ---------------------------------------------------------------- main loop
def fmt_rows(cols, rows, truncated, limit=ROWS_TO_LLM):
    if not rows:
        return "EMPTY RESULT (0 rows)"
    lines = [" | ".join(cols)]
    size = len(lines[0])
    shown = 0
    for r in rows[:limit]:
        line = " | ".join("NULL" if v is None else (f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)) for v in r)
        if size + len(line) > MAX_FEEDBACK_CHARS and shown:
            break
        lines.append(line[:MAX_FEEDBACK_CHARS])
        size += len(line)
        shown += 1
    if len(rows) > shown or truncated:
        lines.append(f"... ({len(rows)}{'+' if truncated else ''} rows total, first {shown} shown; "
                     "select fewer columns or aggregate)")
    return "\n".join(lines)


def answer(question, con=None):
    """Returns dict: answer, lang, evidence [(sql, cols, rows)], model, verified, steps."""
    con = con or connect()
    lang = detect_lang(question)
    evidence = []
    log = []
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.replace("{lang}", "Russian" if lang == "ru" else "Uzbek")},
        {"role": "user", "content": question},
    ]
    model = None
    verify_retries = 0
    try:
        for _ in range(MAX_STEPS + 3):
            t0 = time.time()
            text, model = chat(messages)
            log.append(f"{model} {time.time() - t0:.1f}s")
            msg = parse_json(text)
            messages.append({"role": "assistant", "content": json.dumps(msg, ensure_ascii=False)})
            if msg.get("sql"):
                sql = str(msg["sql"])
                try:
                    cols, rows, trunc = run_sql(con, sql)
                    feedback = "RESULT:\n" + fmt_rows(cols, rows, trunc)
                    if mixes_units(sql):
                        log.append("unit guard: query aggregates volume/price without unit")
                        feedback += ("\nWARNING: this query aggregates volume or unit_price without GROUP BY unit / "
                                     "unit filter, so its numbers may mix tonnes, kg and litres and CANNOT be used. "
                                     "Run it again with GROUP BY unit (or WHERE unit = ...).")
                    else:
                        evidence.append((sql, cols, rows))
                except Exception as e:  # noqa: BLE001
                    feedback = f"SQL ERROR: {e}. Fix the query."
                    log.append(feedback)
                messages.append({"role": "user", "content": feedback})
                continue
            final = str(msg.get("answer", "")).strip()
            if not final:
                messages.append({"role": "user", "content": 'Reply with {"sql": ...} or {"answer": ...}.'})
                continue
            if not evidence:
                if final.strip() in NO_DATA.values():
                    return dict(answer=NO_DATA[lang], lang=lang, evidence=[], model=model, verified=True, log=log)
                messages.append({"role": "user", "content": "You must run at least one SQL query before answering."})
                continue
            all_rows = [(c, r) for _, c, r in evidence]
            bad = verify(final, question, all_rows)
            if not bad:
                return dict(answer=final, lang=lang, evidence=evidence, model=model, verified=True, log=log)
            log.append(f"verifier: numbers not found in results: {bad}")
            if verify_retries >= 2:
                note = " (проверка не пройдена)" if lang == "ru" else " (tekshiruvdan o‘tmadi)"
                return dict(answer=NO_DATA[lang] + note, lang=lang, evidence=evidence, model=model,
                            verified=False, log=log)
            verify_retries += 1
            messages.append({"role": "user", "content":
                             f"VERIFICATION FAILED: these numbers are not in the SQL results: {bad}. "
                             "Every number must come from a query result. Run another query if needed "
                             "(do the calculation in SQL), then answer again."})
        return dict(answer=NO_DATA[lang], lang=lang, evidence=evidence, model=model, verified=False, log=log)
    except LLMError as e:
        log.append(f"LLM unavailable: {e}")
        evidence = []  # show only the deterministic lookup, not half-finished LLM queries
        for sql in direct_lookup(con, question):
            cols, rows, _ = run_sql(con, sql)
            evidence.append((sql, cols, rows))
        found = [ev for ev in evidence if ev[2]]
        if found:
            head = "Найдена запись (ИИ временно недоступен):" if lang == "ru" else "Yozuv topildi (AI vaqtincha ishlamayapti):"
            body = "\n".join(
                "; ".join(f"{c}: {v}" for c, v in zip(cols, row)) for _, cols, rows in found for row in rows[:5])
            return dict(answer=f"{head}\n\n{body}", lang=lang, evidence=evidence, model="direct lookup",
                        verified=True, log=log)
        msg = ("Сервис ИИ временно недоступен. Без ИИ можно искать по номеру сделки, номеру контракта, ИНН или коду брокера (BK001)."
               if lang == "ru" else
               "AI xizmati vaqtincha ishlamayapti. AIsiz bitim raqami, shartnoma raqami, STIR yoki broker kodi (BK001) bo‘yicha qidirish mumkin.")
        return dict(answer=msg, lang=lang, evidence=evidence, model=None, verified=False, log=log)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ensure_db()
    c = connect()
    for qq in sys.argv[1:]:
        res = answer(qq, c)
        print("Q:", qq)
        print("A:", res["answer"])
        print("   model:", res["model"], "verified:", res["verified"], "log:", res["log"])
        for s, _, rows in res["evidence"]:
            print("   SQL:", s.replace("\n", " ")[:300], "->", rows[:3])
        print()
