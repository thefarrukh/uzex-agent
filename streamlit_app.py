"""UZEX AI agent — Streamlit web UI."""
import os

import pandas as pd
import streamlit as st

# Streamlit Cloud secrets -> environment (agent reads os.environ)
try:
    for _k in ("GEMINI_API_KEY", "GROQ_API_KEY", "GEMINI_MODEL", "GROQ_MODEL"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # noqa: BLE001  (no secrets file locally)
    pass

import agent  # noqa: E402

st.set_page_config(page_title="UZEX AI agent", page_icon="📊", layout="centered")

EXAMPLES = [
    "Сделка №100001: сумма, товар и покупатель?",
    "2024-yil mart oyida karbamid bo‘yicha nechta bitim tuzilgan?",
    "Топ-5 покупателей по сумме сделок в 2025 году",
    "BK058 broker kim?",
    "Сколько экспортных сделок аннулировано в 2023 году?",
    "Средняя цена за тонну бензина АИ-92 в 2026 году?",
    "Kim eng ko‘p paxta sotgan 2025-yilda?",
    "Сделка номер 999999",
]


@st.cache_resource(show_spinner="Загрузка базы сделок (первый запуск ~1 мин)… / Bitimlar bazasi yuklanmoqda…")
def prepare_db():
    agent.ensure_db()
    return True


def show_evidence(res):
    if not res.get("evidence"):
        return
    title = "Asos / Основание (SQL и данные)" if res["lang"] == "ru" else "Asos / Основание (SQL va ma’lumotlar)"
    with st.expander(title):
        for i, (sql, cols, rows) in enumerate(res["evidence"], 1):
            st.code(sql, language="sql")
            if rows:
                st.dataframe(pd.DataFrame(rows, columns=cols), hide_index=True, width="stretch")
                if len(rows) >= agent.MAX_ROWS:
                    st.caption(f"Показаны первые {agent.MAX_ROWS} строк")
            else:
                st.caption("Пустой результат / Natija bo‘sh")
        badge = "✅ числа проверены по данным / raqamlar tekshirildi" if res.get("verified") else "⚠️ не проверено / tekshirilmagan"
        st.caption(f"{badge} · модель: {res.get('model') or '—'}")


prepare_db()
if "con" not in st.session_state:  # one read-only connection per browser session
    st.session_state.con = agent.connect()
con = st.session_state.con

st.title("📊 UZEX AI agent")
st.caption(
    "Вопросы по реестру биржевых сделок 2022–2026 на русском или узбекском. "
    "Birja bitimlari bo‘yicha savollarni o‘zbek yoki rus tilida bering. "
    "Каждый ответ подтверждён SQL-запросом к данным."
)

if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.subheader("Примеры / Misollar")
    for ex in EXAMPLES:
        if st.button(ex, width="stretch"):
            st.session_state.pending = ex
    st.divider()
    if st.button("Очистить / Tozalash", width="stretch"):
        st.session_state.history = []
    st.caption(
        "Данные: 500 000 сделок, контракты, участники, брокеры, курс USD. "
        "ИИ пишет SQL, все расчёты выполняет база; каждое число в ответе сверяется с результатом запроса."
    )

for item in st.session_state.history:
    with st.chat_message("user"):
        st.write(item["q"])
    with st.chat_message("assistant"):
        st.markdown(item["res"]["answer"])
        show_evidence(item["res"])

question = st.chat_input("Ваш вопрос / Savolingiz…")
if not question:
    question = st.session_state.pop("pending", None)

if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Ищу в данных… / Ma’lumotlardan qidirilmoqda…"):
            try:
                res = agent.answer(question, con)
            except Exception as e:  # noqa: BLE001
                res = dict(answer=f"Ошибка / Xatolik: {e}", lang="ru", evidence=[], model=None, verified=False)
        st.markdown(res["answer"])
        show_evidence(res)
    st.session_state.history.append({"q": question, "res": res})
