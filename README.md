# Valuation Dashboard

A beginner-friendly stock dashboard. Type any tickers and it shows, for each stock:

- **P/E, forward P/E, PEG and forward PEG**, graded against simple rules of thumb
- **Profit per share (EPS)**: last 12 months and next year's estimate, with the math shown
- **Warnings** when the numbers may be misleading (short-term growth estimates, accounting mismatches)
- **Competitor comparison**: finds rivals automatically and compares them side by side
- **Why profit is expected to change**: sales growth, margins, beat record, analyst estimate trends
- **AI analysis**: a full plain-English write-up of any stock, written by Claude
- **Learn the terms**: a built-in glossary

Data comes from Yahoo Finance (via `yfinance`) and Finviz (via `finvizfinance`).
For education only. Not financial advice.

## Run it on your computer

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

For the AI analysis, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
and add your Anthropic API key (from platform.claude.com). That file is ignored by git, so your key never gets uploaded.

## Put it online (free)

1. Push this folder to a GitHub repository.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, click **Create app**,
   pick this repository and set the main file to `streamlit_app.py`.
3. In **Advanced settings → Secrets**, paste the contents of `secrets.toml.example` with your real key and password.
4. Deploy. You get a public link like `your-app.streamlit.app`.

## Your private watchlist page

The sidebar has two pages: **Public dashboard** (what visitors see) and **My watchlist 🔒**.
Your watchlist lives in Secrets as `MY_WATCHLIST`, so it never appears in the public code, and the page
needs `OWNER_PASSWORD` to open online. Bookmark it with `?page=me` at the end of your app URL.
To add tickers, edit the box on the page. To keep them, update `MY_WATCHLIST` in Secrets
(the page shows you the exact line to paste).

## Protecting your API credit

- Your key lives only in Streamlit's Secrets, never in the code.
- `AI_PASSWORD`: visitors need it to write new analyses. Everyone can read saved ones.
- Each stock's analysis is written once per day and shared with all visitors.
- `AI_DAILY_LIMIT` caps how many new analyses your key can write per day.
- Also set a monthly spend limit in the Claude Console (platform.claude.com) as a final safety net.

## Also included

`stock_check.py`: a command-line version. `python stock_check.py MSFT NVDA`
