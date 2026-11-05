# UZEX AI agent

Web service (Streamlit) that answers questions about exchange deals in **Russian and Uzbek**.

- 500 000 deals plus the contract, participant, broker and USD-rate tables are loaded into SQLite with cleaned types:
  numeric amounts, ISO dates, volume = quantity × lot, unit price, amount in UZS for USD deals (rate on the deal date),
  a normalised commodity name (e.g. «КАРБАМИД», «Мочевина (карбамид)» → «Карбамид») and a transliterated search
  function `norm()` (Cyrillic → Latin), so Uzbek and Russian spellings match.
- Agent: an LLM (Gemini Flash, with Groq as a fallback) writes read-only SQL (SELECT only, row and time limits).
  All arithmetic is done in SQL, never by the model.
- Verification: every number in the answer is checked against the SQL results (0.5 % tolerance). If a number
  is not found, the model gets one retry; if it fails again, the agent answers "no such information in the data".
- Each answer shows the SQL query and the returned rows ("Asos / Основание").
- Without the LLM, direct lookup by deal number, contract number, INN or broker code still works.

Run locally: `pip install -r requirements.txt`, put `GEMINI_API_KEY` / `GROQ_API_KEY` in `.streamlit/secrets.toml`,
then `streamlit run streamlit_app.py`.
