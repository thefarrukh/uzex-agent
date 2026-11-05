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

st.set_page_config(page_title="UZEX AI agent", page_icon="🟩", layout="centered")

# ---------------------------------------------------------------- style (UZEX AI Hackathon look)
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;800&family=JetBrains+Mono:wght@400;600&display=swap');
:root { --navy:#0B0E2D; --card:#161B4A; --green:#3BE38B; --blue:#3D55D4; --lav:#C9CEF7; --text:#E9EBFF; }
html, body, .stApp, [class*="css"], .stMarkdown, button, input, textarea { font-family: 'Manrope', sans-serif !important; }
.stApp { background: var(--navy); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: #0F1338; border-right: 1px solid #23295e; }
.block-container { padding-top: 2.2rem; }

.uz-hero { margin: 0 0 1.2rem 0; line-height: 1; }
.uz-hero .row { display: flex; flex-wrap: wrap; }
.uz-hero .b { display: inline-block; font-weight: 800; font-size: 3.1rem; padding: .35rem 1rem .45rem; letter-spacing: -1px; }
.uz-hero .w { background: #fff; color: var(--navy); }
.uz-hero .g { background: var(--green); color: var(--navy); }
.uz-hero .bl { background: var(--blue); color: #fff; margin-left: 2.4rem; }
.uz-hero .lv { background: var(--lav); color: var(--navy); margin-left: 2.4rem; font-size: 2.2rem; }
.uz-lead { color: var(--text); font-size: 1.02rem; margin: .4rem 0 1rem; max-width: 640px; }
.uz-stats { display: flex; gap: 1.6rem; flex-wrap: wrap; margin-bottom: 1.4rem; }
.uz-stat .k { font-family: 'JetBrains Mono', monospace; font-size: .72rem; color: var(--lav); letter-spacing: .08em; text-transform: uppercase; }
.uz-stat .v { color: var(--green); font-weight: 600; font-size: 1.02rem; }
.uz-side-title { font-family: 'JetBrains Mono', monospace; font-size: .75rem; color: var(--lav); letter-spacing: .1em; text-transform: uppercase; margin: .3rem 0 .6rem; }

[data-testid="stSidebar"] .stButton button {
  background: transparent; border: 1px solid #2b3270; color: var(--text); border-radius: 0;
  text-align: left; justify-content: flex-start; font-size: .86rem; padding: .55rem .75rem; }
[data-testid="stSidebar"] .stButton button > div, [data-testid="stSidebar"] .stButton button p { text-align: left; width: 100%; justify-content: flex-start; }
[data-testid="stSidebar"] .stButton button:hover { border-color: var(--green); color: var(--green); }

[data-testid="stChatMessage"] { background: var(--card); border: 1px solid #252b63; border-radius: 0; padding: 1rem 1.1rem; }
/* question: lighter card with lavender accent; answer: darker card with green accent */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: #1F2663; border: 1px solid #343d8a; border-left: 3px solid var(--lav); }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  background: #0D1033; border: 1px solid #1f2558; border-left: 3px solid var(--green); }
[data-testid="stChatMessageAvatarUser"] { background: var(--lav) !important; color: var(--navy) !important; border-radius: 0 !important; }
[data-testid="stChatMessageAvatarAssistant"] { background: var(--green) !important; color: var(--navy) !important; border-radius: 0 !important; }
[data-testid="stExpander"] details { border-radius: 0; border-color: #2b3270; }
[data-testid="stExpander"] summary { font-family: 'JetBrains Mono', monospace; font-size: .82rem; color: var(--lav); }
[data-testid="stChatInput"] { border-radius: 0 !important; border: 1px solid var(--green) !important; }
[data-testid="stChatInput"] textarea { color: var(--text); }
code { font-family: 'JetBrains Mono', monospace !important; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

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
                df = pd.DataFrame(rows, columns=cols)
                df = df[[c for c in df.columns if not str(c).endswith("_norm")]]  # hide technical columns
                st.dataframe(df, hide_index=True, width="stretch")
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

st.markdown(
    """
<div class="uz-hero">
  <div class="row"><span class="b w">UZEX</span><span class="b g">AI</span></div>
  <div class="row"><span class="b bl">Agent</span></div>
  <div class="row"><span class="b lv">/birja bitimlari</span></div>
</div>
<div class="uz-lead">Birja bitimlari bo‘yicha savolingizni o‘zbek yoki rus tilida bering — agent javobni faqat
ma’lumotlardan oladi va asosini ko‘rsatadi. Задайте вопрос о сделках биржи на узбекском или русском — каждый
ответ подтверждён SQL-запросом к данным.</div>
<div class="uz-stats">
  <div class="uz-stat"><div class="k">Ma’lumotlar</div><div class="v">500 000 bitim · 2022–2026</div></div>
  <div class="uz-stat"><div class="k">Tillar</div><div class="v">RU / UZ</div></div>
  <div class="uz-stat"><div class="k">Tekshiruv</div><div class="v">har bir raqam SQL bilan</div></div>
</div>
""",
    unsafe_allow_html=True,
)

if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.markdown('<div class="uz-side-title">Misollar / Примеры</div>', unsafe_allow_html=True)
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
