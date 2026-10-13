"""
Valuation Dashboard - live P/E, forward P/E and PEG from Yahoo Finance.

Setup (once):
    pip install streamlit yfinance

Run:
    streamlit run streamlit_app.py

Your browser opens the dashboard. Type tickers in the sidebar.
Rules of thumb only. For education, not financial advice.
"""

import json
import os
import urllib.request
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

try:
    import yfinance as yf
except ImportError:
    st.error("yfinance is not installed. In a terminal, run:  pip install yfinance")
    st.stop()

st.set_page_config(page_title="Valuation Dashboard", page_icon="📈", layout="wide")

GOOD, MID, BAD, NA = "#1f9d55", "#d69e2e", "#e05545", "#8a9490"


# ---------------- data ----------------

def to_num(v):
    try:
        n = float(v)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


try:
    from finvizfinance.quote import finvizfinance as _Finviz  # optional: pip install finvizfinance
except Exception:
    _Finviz = None


@st.cache_data(ttl=3600, show_spinner=False)
def finviz_info(symbol):
    """One Finviz page load per ticker: 5-year growth, industry and peer list."""
    out = {"growth": None, "industry": None, "peers": []}
    if _Finviz is None:
        return out
    try:
        fv = _Finviz(symbol)
    except Exception:
        return out
    try:
        fund = fv.ticker_fundament()
        v = fund.get("EPS next 5Y")
        if isinstance(v, (int, float)):
            out["growth"] = float(v) * (100 if abs(v) < 1.5 else 1)
        else:
            out["growth"] = to_num(str(v).replace("%", "").replace(",", "").strip())
        out["industry"] = fund.get("Industry")
    except Exception:
        pass
    try:
        out["peers"] = [p.strip().upper() for p in (fv.ticker_peer() or []) if p and p.strip()]
    except Exception:
        pass
    return out


def finviz_growth(symbol):
    """Finviz's 'EPS next 5Y' (long-term analyst growth estimate) as a percent, or None."""
    return finviz_info(symbol)["growth"]


# Backup competitor lists, used when Finviz and Yahoo don't return any.
CURATED_PEERS = {
    "BULL": ["HOOD", "IBKR", "SCHW", "FUTU", "VIRT"], "HOOD": ["BULL", "IBKR", "SCHW", "FUTU"],
    "MSFT": ["GOOGL", "AMZN", "ORCL", "CRM", "ADBE"], "GOOGL": ["META", "MSFT", "AMZN", "PINS"],
    "META": ["GOOGL", "SNAP", "PINS", "RDDT"], "AMZN": ["WMT", "MSFT", "GOOGL", "SHOP"],
    "NVDA": ["AMD", "AVGO", "QCOM", "MRVL", "INTC"], "AVGO": ["NVDA", "AMD", "QCOM", "MRVL", "TXN"],
    "AMD": ["NVDA", "INTC", "AVGO", "QCOM"], "AAPL": ["MSFT", "GOOGL", "SONY", "DELL", "HPQ"],
    "COST": ["WMT", "TGT", "BJ", "DG", "DLTR"], "WMT": ["COST", "TGT", "AMZN", "KR"],
    "KO": ["PEP", "KDP", "MNST", "CELH"], "PEP": ["KO", "KDP", "MDLZ", "MNST"],
    "JPM": ["BAC", "WFC", "C", "GS", "MS"], "TSLA": ["GM", "F", "RIVN", "TM"],
}


@st.cache_data(ttl=3600, show_spinner=False)
def find_peers(symbol, industry_key):
    """Competitors for a ticker: Finviz peers, else Yahoo's top companies in the industry, else a backup list."""
    if os.environ.get("VC_DEMO"):
        return CURATED_PEERS.get(symbol, []), "backup list"
    peers = [p for p in finviz_info(symbol)["peers"] if p != symbol]
    if peers:
        return peers[:8], "Finviz"
    if industry_key:
        try:
            top = yf.Industry(industry_key).top_companies
            if top is not None and not top.empty:
                peers = [str(s).upper() for s in top.index if str(s).upper() != symbol]
                if peers:
                    return peers[:8], "Yahoo industry leaders"
        except Exception:
            pass
    return CURATED_PEERS.get(symbol, []), ("backup list" if symbol in CURATED_PEERS else "none found")


def growth_estimate(tk, info, symbol=None):
    ge = None
    try:
        ge = tk.growth_estimates
    except Exception:
        pass
    col = None
    if ge is not None and not ge.empty:
        col = "stockTrend" if "stockTrend" in ge.columns else ge.columns[0]
        # 1) Yahoo long-term estimate
        for row in ("LTG", "+5y"):
            if row in ge.index:
                g = to_num(ge.loc[row, col])
                if g is not None:
                    return g * 100, f"analyst {row}"
    # 2) Finviz long-term estimate
    if symbol:
        g = finviz_growth(symbol)
        if g is not None:
            return g, "Finviz 5Y"
    # 3) Yahoo short-term estimates
    if col is not None:
        for row in ("+1y", "0y"):
            if row in ge.index:
                g = to_num(ge.loc[row, col])
                if g is not None:
                    return g * 100, f"analyst {row}"
    try:
        ee = tk.earnings_estimate
        if ee is not None and not ee.empty and "growth" in ee.columns:
            for row in ("+1y", "0y"):
                if row in ee.index:
                    g = to_num(ee.loc[row, "growth"])
                    if g is not None:
                        return g * 100, f"analyst {row} EPS"
    except Exception:
        pass
    t, f = to_num(info.get("trailingEps")), to_num(info.get("forwardEps"))
    if t and f and t > 0:
        return (f / t - 1) * 100, "fwd vs trailing EPS"
    return None, "n/a"


def grade_pe(pe, eps):
    if pe is None:
        return "No profits" if (eps is not None and eps <= 0) else "n/a"
    return "Low" if pe < 15 else "Middle" if pe <= 25 else "High"


def grade_fpe(fpe, pe):
    if fpe is None:
        return "n/a"
    if pe is None:
        return "Turning profitable"
    if fpe < pe * 0.97:
        return "Earnings rising"
    if fpe > pe * 1.03:
        return "Earnings falling"
    return "Flat"


def grade_peg(peg):
    if peg is None:
        return "n/a"
    return "Growth on sale" if peg < 1 else "Fair value" if peg <= 2 else "Premium"


HELP = {
    "pe": "Price ÷ earnings per share from the last 12 months. How many dollars you pay for each $1 of profit "
          "the company actually made. Lower = cheaper.",
    "fpe": "Price ÷ the earnings per share analysts expect next year. Same idea as P/E but looking ahead. "
           "If it's lower than P/E, profits are expected to grow.",
    "peg": "P/E ÷ expected yearly growth rate (%). Adjusts P/E for how fast the company is growing. "
           "Under 1 = cheap for its growth, 1–2 = fair, over 2 = expensive.",
    "fpeg": "Forward P/E ÷ growth rate. Uses next year's expected earnings instead of last year's. "
            "Useful when last year's profits were unusual, but still only as good as the growth estimate.",
    "growth": "How fast analysts expect profits (earnings per share) to grow each year. "
              "Long-term (5-year) estimates are steadier than one-year ones.",
}


def find_flags(eps, feps, growth, gsrc):
    """Warnings that the ratios for this stock may be misleading. Each is (title, plain-English explanation)."""
    flags = []
    if growth is not None and not any(k in gsrc for k in ("LTG", "+5y", "5Y")):
        flags.append(("Growth is a short-term forecast",
                      "Neither Yahoo nor Finviz had a long-term (5-year) growth estimate, so the PEG uses a forecast "
                      "for just one year "
                      f"({gsrc}). One unusual year can make PEG look much cheaper or pricier than it really is."))
    if eps and feps and eps > 0 and feps > 0:
        ratio = feps / eps
        if ratio > 1.4 or ratio < 0.7:
            flags.append(("Past and future earnings don't match up",
                          f"Next year's expected earnings (${feps:,.2f}) are {ratio:.1f}x last year's (${eps:,.2f}). "
                          "A gap this big often means the two numbers are measured differently: last year's is the "
                          "official accounting profit (GAAP), next year's is analysts' 'adjusted' profit, which leaves "
                          "out one-time costs. Forward P/E is the fairer number to compare."))
    if growth is not None and growth > 40:
        flags.append(("Unusually high growth estimate",
                      f"{growth:.0f}% a year is very fast growth that few companies keep up. "
                      "If it doesn't happen, the real PEG ends up much higher."))
    if eps is not None and eps <= 0:
        flags.append(("No profit last year",
                      "The company lost money, so P/E and PEG can't be calculated from last year's earnings."))
    return flags


@st.cache_data(ttl=900, show_spinner=False)
def fetch(symbol):
    if os.environ.get("VC_DEMO"):  # offline test mode only
        demo = {"MSFT": (541.15, 17.95, 19.98, 18.8, "analyst LTG"), "NVDA": (180.0, 3.6, 4.6, 30.0, "analyst LTG"),
                "KO": (68.0, 2.9, 3.0, 5.5, "analyst LTG"), "AVGO": (354.73, 7.83, 19.38, 66.4, "analyst +1y"), "BULL": (6.30, 0.08, 0.31, 27.0, "Finviz 5Y"),
                "HOOD": (110.0, 2.0, 2.4, 22.0, "Finviz 5Y"), "IBKR": (65.0, 2.1, 2.3, 12.0, "Finviz 5Y"),
                "SCHW": (95.0, 4.2, 4.9, 14.0, "Finviz 5Y"), "FUTU": (170.0, 9.0, 11.0, 20.0, "Finviz 5Y")}
        p, e, fe, g, gsrc = demo.get(symbol, (50.0, -1.0, 0.5, 12.0, "analyst +1y"))
        info, growth, hist = {"shortName": symbol + " (demo)"}, g, None
    else:
        tk = yf.Ticker(symbol)
        info = tk.info or {}
        p = to_num(info.get("currentPrice")) or to_num(info.get("regularMarketPrice"))
        if p is None:
            try:
                p = to_num(tk.fast_info["last_price"])
            except Exception:
                p = None
        if p is None:
            return {"ticker": symbol, "error": "No price found. Check the ticker."}
        e, fe = to_num(info.get("trailingEps")), to_num(info.get("forwardEps"))
        growth, gsrc = growth_estimate(tk, info, symbol)
        try:
            hist = tk.history(period="1y")["Close"].reset_index()
            hist.columns = ["Date", "Close"]
        except Exception:
            hist = None

    pe = p / e if e and e > 0 else None
    fpe = p / fe if fe and fe > 0 else None
    peg = pe / growth if (pe is not None and growth and growth > 0) else None
    fpeg = fpe / growth if (fpe is not None and growth and growth > 0) else None
    flags = find_flags(e, fe, growth, gsrc)
    return {
        "fpeg": fpeg, "fpeg_read": grade_peg(fpeg), "flags": flags,
        "ticker": symbol,
        "name": info.get("shortName") or symbol,
        "sector": info.get("sector") or "",
        "industry": info.get("industry") or "",
        "industry_key": info.get("industryKey") or "",
        "price": p, "eps_ttm": e, "eps_next_y": fe,
        "growth_pct": growth, "growth_source": gsrc,
        "pe": pe, "forward_pe": fpe, "peg": peg,
        "yahoo_peg": to_num(info.get("trailingPegRatio")) or to_num(info.get("pegRatio")),
        "pe_read": grade_pe(pe, e), "fpe_read": grade_fpe(fpe, pe), "peg_read": grade_peg(peg),
        "history": hist,
        "fetched": datetime.now().strftime("%b %d, %I:%M %p"),
    }


def _df_val(df, row, col):
    try:
        if df is not None and not df.empty and row in df.index and col in df.columns:
            return to_num(df.loc[row, col])
    except Exception:
        pass
    return None


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_story(symbol):
    """Extra context for the focus stock: what the business does and evidence behind analysts' forecasts."""
    if os.environ.get("VC_DEMO"):  # offline test mode only
        return {
            "summary": f"{symbol} is a demo company used to test this dashboard.",
            "employees": 80000, "market_cap": 300e9, "revenue_growth": 18.0, "earnings_growth": 25.0,
            "margin": 22.0, "analysts": 24, "rec": "buy", "target": 210.0,
            "eps_path": [("Last fiscal year (actual)", 11.0), ("This fiscal year (est.)", 12.6),
                         ("Next fiscal year (est.)", 14.1)],
            "est_now": 14.1, "est_90": 13.4, "est_low": 12.8, "est_high": 15.5, "est_n": 22,
            "beats": [("2026-06-30", 3.2, 2.9), ("2026-03-31", 3.0, 2.8), ("2025-12-31", 2.6, 2.7),
                      ("2025-09-30", 2.8, 2.5)],
            "news": [("Demo headline: company reports record quarter", "https://example.com", "Demo News", "Oct 10")],
        }
    tk = yf.Ticker(symbol)
    info = tk.info or {}
    out = {
        "summary": info.get("longBusinessSummary") or "",
        "employees": info.get("fullTimeEmployees"),
        "market_cap": to_num(info.get("marketCap")),
        "revenue_growth": None if to_num(info.get("revenueGrowth")) is None else to_num(info.get("revenueGrowth")) * 100,
        "earnings_growth": None if to_num(info.get("earningsGrowth")) is None else to_num(info.get("earningsGrowth")) * 100,
        "margin": None if to_num(info.get("profitMargins")) is None else to_num(info.get("profitMargins")) * 100,
        "analysts": info.get("numberOfAnalystOpinions"),
        "rec": info.get("recommendationKey"),
        "target": to_num(info.get("targetMeanPrice")),
        "eps_path": [], "est_now": None, "est_90": None, "est_low": None, "est_high": None, "est_n": None,
        "beats": [], "news": [],
    }
    # Profit-per-share path: last fiscal year actual -> this year est -> next year est
    try:
        ee = tk.earnings_estimate
        ya = _df_val(ee, "0y", "yearAgoEps")
        cy = _df_val(ee, "0y", "avg")
        ny = _df_val(ee, "+1y", "avg")
        path = [("Last fiscal year (actual)", ya), ("This fiscal year (est.)", cy), ("Next fiscal year (est.)", ny)]
        out["eps_path"] = [(k, v) for k, v in path if v is not None]
        out["est_low"], out["est_high"] = _df_val(ee, "+1y", "low"), _df_val(ee, "+1y", "high")
        n = _df_val(ee, "+1y", "numberOfAnalysts")
        out["est_n"] = int(n) if n else None
    except Exception:
        pass
    # How next year's estimate has moved over 90 days
    try:
        et = tk.eps_trend
        out["est_now"], out["est_90"] = _df_val(et, "+1y", "current"), _df_val(et, "+1y", "90daysAgo")
    except Exception:
        pass
    # Beat / miss record for recent quarters
    try:
        eh = tk.earnings_history
        if eh is not None and not eh.empty:
            for idx, row in eh.tail(4).iloc[::-1].iterrows():
                a, e = to_num(row.get("epsActual")), to_num(row.get("epsEstimate"))
                if a is not None and e is not None:
                    out["beats"].append((str(idx)[:10], a, e))
    except Exception:
        pass
    # Recent headlines (two formats depending on yfinance version)
    try:
        for n in (tk.news or [])[:6]:
            c = n.get("content") if isinstance(n.get("content"), dict) else n
            title = c.get("title")
            url = ((c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict)
                   else None) or c.get("link")
            pub = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher")
            when = c.get("pubDate") or ""
            if not when and c.get("providerPublishTime"):
                when = datetime.fromtimestamp(c["providerPublishTime"]).strftime("%b %d")
            elif when:
                try:
                    when = datetime.fromisoformat(when.replace("Z", "+00:00")).strftime("%b %d")
                except Exception:
                    when = when[:10]
            if title:
                out["news"].append((title, url, pub or "", when))
    except Exception:
        pass
    return out


def secret(name, default=""):
    """Read a setting from an environment variable, else Streamlit secrets (.streamlit/secrets.toml)."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


OWNER_KEY = secret("ANTHROPIC_API_KEY")            # your key; never put it in the code
AI_PASSWORD = secret("AI_PASSWORD")                # if set, visitors need it to spend your credit
AI_DAILY_LIMIT = int(secret("AI_DAILY_LIMIT", "25") or 25)  # max new analyses per day on your key
DEFAULT_MODEL = secret("AI_MODEL", "claude-sonnet-5-5") or "claude-sonnet-5-5"
HOSTED = secret("HOSTED", "").lower() in ("1", "true", "yes")  # hides local-only options online
OWNER_PASSWORD = secret("OWNER_PASSWORD") or AI_PASSWORD  # unlocks the private "My watchlist" page
MY_WATCHLIST = secret("MY_WATCHLIST")                      # your tickers; kept in secrets so they stay private
PUBLIC_TICKERS = "MSFT\nNVDA\nAAPL\nGOOGL\nCOST\nKO\nAVGO\nBULL"


def split_tickers(raw):
    return list(dict.fromkeys(t.strip().upper() for t in raw.replace(",", "\n").split() if t.strip()))


@st.cache_resource
def ai_store():
    """Shared across all visitors: analyses written today, plus today's usage count on the owner's key."""
    return {"texts": {}, "count": {}}


AI_SYSTEM = """You are a patient investing teacher explaining one stock to a beginner who is learning finance.
You get a data sheet from a valuation dashboard. Write a clear, friendly explanation in Markdown using EXACTLY these sections:

**The one thing to take from this** - 2-3 sentences: what the whole story hinges on, ending with the real question
an investor must answer (e.g. "will X keep growing this fast?").

### 1. What the company sells, in simple terms
Bullet points in everyday words, based on the business description. Add one simple analogy.

### 2. Why analysts expect profit to change (the green clues)
Bullets for each supporting clue in the data (sales growth, profit growth, margin, beat record, estimate trend,
the profit-per-share path). Explain what each number means in plain words, e.g. "of every $100 in sales, $43 is profit".

### 3. What the warnings mean here
For each dashboard warning, say whether the other evidence makes it more or less worrying for THIS stock.
Remind the reader a warning means "go check", not "this is bad". If there are no warnings, say the numbers can be read at face value.

### 4. Reasons for caution (the amber clues)
Bullets: analyst disagreement (convert the low/high estimate into a P/E range at today's price), growth that is
unusually high to sustain, dependence on customers/products/the economy, industry cycles, anything weak in the data.

### 5. Against its rivals
Use the competitor numbers. Say whether it is cheaper or pricier and faster or slower, and give 2-3 POSSIBLE reasons
for any gap, clearly labelled as possibilities. Point out any listed competitor that doesn't really make money the same way.

### 6. What analysts think
Rating and price target, labelled as opinion. Note analysts tend to be optimistic.

### The bottom line
A 3-row Markdown table with rows: What you get | What you're betting on | Main risk.
Then one closing sentence: the numbers tell you what's expected; the reader's job is to decide whether they believe it.

Rules:
- Use ONLY numbers from the data sheet. Never invent figures, dates, customers or news. Round sensibly.
- You may add general background about the company or industry from your own knowledge, but say so ("Background:")
  and keep it brief, since it may be out of date.
- Headlines are only titles; don't claim to know what an article says beyond its title.
- No buy/sell/hold recommendation and no telling the reader what to do with their money.
- Short sentences, no jargon without a plain explanation. About 600-900 words."""


def build_ai_context(r, sinfo, peer_rows, peer_meds, eps_chg):
    L = [f"Data sheet for {r['ticker']} ({r['name']}), fetched {r['fetched']}.",
         f"Sector/industry: {r.get('sector') or '?'} / {r.get('industry') or '?'}",
         f"Share price: ${fmt(r['price'], 2)}",
         f"Profit per share (EPS) last 12 months: ${fmt(r['eps_ttm'], 2)}; next year analyst estimate: "
         f"${fmt(r['eps_next_y'], 2)}; expected change: {fmt(eps_chg, 0, '%')}",
         f"P/E (trailing): {fmt(r['pe'], 1, 'x')} ({r['pe_read']}); Forward P/E: {fmt(r['forward_pe'], 1, 'x')} ({r['fpe_read']})",
         f"Growth estimate: {fmt(r['growth_pct'], 1, '%')} per year (source: {r['growth_source']})",
         f"PEG: {fmt(r['peg'], 2)} ({r['peg_read']}); Forward PEG: {fmt(r['fpeg'], 2)} ({r['fpeg_read']}); "
         f"Yahoo's own PEG: {fmt(r['yahoo_peg'], 2)}",
         "Dashboard PEG bands: under 1 growth on sale, 1-2 fair, over 2 premium."]
    L.append("Dashboard warnings: " + ("; ".join(f"{t}: {w}" for t, w in r["flags"]) if r["flags"] else "none"))
    if sinfo:
        L += [f"Company value (market cap): {big_money(sinfo['market_cap'])}; employees: {sinfo['employees'] or '?'}",
              f"Latest quarter sales growth vs a year ago: {fmt(sinfo['revenue_growth'], 1, '%')}",
              f"Latest quarter profit growth vs a year ago: {fmt(sinfo['earnings_growth'], 1, '%')}",
              f"Profit margin: {fmt(sinfo['margin'], 1, '%')}"]
        if sinfo["eps_path"]:
            L.append("Profit-per-share path (fiscal years): " +
                     " -> ".join(f"{k}: ${v:,.2f}" for k, v in sinfo["eps_path"]))
        if sinfo["est_now"] is not None:
            L.append(f"Next-year EPS estimate now ${fmt(sinfo['est_now'], 2)} vs 90 days ago ${fmt(sinfo['est_90'], 2)}")
        if sinfo["est_low"] is not None:
            L.append(f"Next-year EPS estimate range: low ${fmt(sinfo['est_low'], 2)}, high ${fmt(sinfo['est_high'], 2)}, "
                     f"from {sinfo['est_n'] or '?'} analysts")
        if sinfo["beats"]:
            L.append("Recent quarters (actual vs estimate EPS): " +
                     "; ".join(f"{d}: {a:.2f} vs {e:.2f}" for d, a, e in sinfo["beats"]))
        L.append(f"Analyst rating: {sinfo['rec'] or '?'} from {sinfo['analysts'] or '?'} analysts; "
                 f"average 12-month price target: ${fmt(sinfo['target'], 2)}")
        if sinfo["summary"]:
            L.append("Business description: " + sinfo["summary"][:2500])
        if sinfo["news"]:
            L.append("Recent headlines: " + " | ".join(f"{t} ({p}, {w})" for t, _, p, w in sinfo["news"]))
    if peer_rows:
        L.append("Competitors (ticker, name, industry, forward P/E, P/E, growth %):")
        L += [f"- {p}" for p in peer_rows]
        L.append("Competitor medians: " + ", ".join(f"{k}: {v}" for k, v in peer_meds.items()))
    return "\n".join(L)


def stream_claude(ctx, model, key):
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    with client.messages.stream(model=model, max_tokens=2500, system=AI_SYSTEM,
                                messages=[{"role": "user", "content": ctx}]) as s:
        for text in s.text_stream:
            yield text


def stream_ollama(ctx, model):
    body = json.dumps({"model": model, "stream": True, "messages": [
        {"role": "system", "content": AI_SYSTEM}, {"role": "user", "content": ctx}]}).encode()
    req = urllib.request.Request("http://localhost:11434/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        for line in resp:
            if line.strip():
                chunk = json.loads(line)
                yield chunk.get("message", {}).get("content", "")
                if chunk.get("done"):
                    break


def dbl_txt(g):
    """How long profit takes to double at g% a year, in words."""
    import math
    yrs = math.log(2) / math.log(1 + g / 100)
    if yrs < 2:
        return f"about {yrs * 12:.0f} months"
    return f"about {yrs:.0f} years" if yrs >= 3 else f"about {yrs:.1f} years"


def big_money(n):
    if n is None:
        return "—"
    for div, s in ((1e12, " trillion"), (1e9, " billion"), (1e6, " million")):
        if abs(n) >= div:
            return f"${n / div:,.1f}{s}"
    return f"${n:,.0f}"


def color_for(read):
    if read in ("Low", "Earnings rising", "Growth on sale"):
        return GOOD
    if read in ("Middle", "Flat", "Fair value", "Turning profitable"):
        return MID
    if read in ("High", "Earnings falling", "Premium"):
        return BAD
    return NA


def fmt(n, d=1, suffix=""):
    return "—" if n is None else f"{n:,.{d}f}{suffix}"


def badge(read):
    c = color_for(read)
    return (f"<span style='background:{c}22;color:{c};border:1px solid {c}66;"
            f"padding:2px 10px;border-radius:99px;font-size:0.85rem;font-weight:600'>{read}</span>")


# ---------------- sidebar ----------------

PAGES = ["Public dashboard", "My watchlist 🔒"]

with st.sidebar:
    # ?page=me in the URL opens the private page directly, so it can be bookmarked
    page = st.radio("Page", PAGES, index=1 if st.query_params.get("page") == "me" else 0, key="page")
    if page == PAGES[1]:
        st.query_params["page"] = "me"
    else:
        st.query_params.pop("page", None)
    private = page == PAGES[1]

    if private:
        unlocked = not OWNER_PASSWORD and not HOSTED  # no password needed only on your own computer
        if OWNER_PASSWORD:
            opw = st.text_input("Owner password", type="password", key="owner_pw")
            unlocked = opw == OWNER_PASSWORD
            if opw and not unlocked:
                st.caption("Wrong password.")
        elif HOSTED:
            st.caption("Set OWNER_PASSWORD in Secrets to use this page online.")
        if unlocked:
            st.header("My watchlist")
            raw = st.text_area("One per line, or separated by commas",
                               value="\n".join(split_tickers(MY_WATCHLIST)), height=300, key="my_watchlist")
            tickers = split_tickers(raw)
            if tickers != split_tickers(MY_WATCHLIST):
                st.caption("Changes last until you close the tab. To keep them, replace the "
                           "MY_WATCHLIST line in your Secrets with:")
                st.code(f'MY_WATCHLIST = "{", ".join(tickers)}"', language="toml")
        else:
            tickers = []
    else:
        st.header("Tickers")
        raw = st.text_area("One per line, or separated by commas", value=PUBLIC_TICKERS, height=200)
        tickers = split_tickers(raw)
    if st.button("Refresh data", width="stretch"):
        fetch.clear()
    st.caption("Data from Yahoo Finance, cached for 15 minutes.")
    if _Finviz is None:
        st.caption("Tip: run `pip install finvizfinance` to fill in missing 5-year growth estimates from Finviz.")
    else:
        st.caption("Missing 5-year growth estimates are filled in from Finviz.")
    st.divider()
    st.markdown("**PEG rule of thumb**")
    st.markdown(f"{badge('Growth on sale')} under 1", unsafe_allow_html=True)
    st.markdown(f"{badge('Fair value')} 1 to 2", unsafe_allow_html=True)
    st.markdown(f"{badge('Premium')} over 2", unsafe_allow_html=True)
    st.divider()
    st.markdown("**AI analysis**")
    providers = ["Claude (API key)"] + ([] if HOSTED else ["Ollama (free, on this computer)"])
    ai_provider = st.radio("Who writes the analysis", providers, key="ai_provider")
    ai_owner_key_used = False
    if ai_provider.startswith("Claude"):
        model_opts = [DEFAULT_MODEL] + [m for m in ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5")
                                        if m != DEFAULT_MODEL]
        ai_model = (st.selectbox("Claude model", model_opts, key="ai_model",
                                 help="Sonnet: best balance. Haiku: cheapest and fastest. Opus: most thorough.")
                    if not HOSTED else DEFAULT_MODEL)
        ai_key = None
        if OWNER_KEY:
            if AI_PASSWORD:
                pw = st.text_input("Password to write new analyses", type="password", key="ai_pw",
                                   help="Set by the dashboard owner. Saved analyses can be read without it.")
                if pw and pw == AI_PASSWORD:
                    ai_key, ai_owner_key_used = OWNER_KEY, True
                    st.caption("✓ Unlocked")
                elif pw:
                    st.caption("Wrong password.")
            else:
                ai_key, ai_owner_key_used = OWNER_KEY, True
        if not ai_key:
            own = st.text_input("Or use your own Anthropic API key", type="password", key="ai_key",
                                help="Get one at platform.claude.com. It's only used for this session and "
                                     "never saved.")
            ai_key = own or None
    else:
        ai_model = st.text_input("Ollama model", value="llama3.1", key="ollama_model",
                                 help="Any model you've pulled, e.g. `ollama pull llama3.1`.")
        ai_key = None

st.title("My Watchlist" if private else "Valuation Dashboard")
st.caption("P/E, forward P/E and PEG for every ticker, graded against the rule of thumb.")

if private and not unlocked:
    st.info("This page is private. Enter the owner password in the sidebar.")
    st.stop()
if not tickers:
    st.info("Add at least one ticker in the sidebar.")
    st.stop()

rows = []
with st.spinner("Pulling numbers from Yahoo Finance..."):
    for t in tickers:
        try:
            rows.append(fetch(t))
        except Exception as e:
            rows.append({"ticker": t, "error": f"Lookup failed: {e}"})

errors = [r for r in rows if "error" in r]
ok = [r for r in rows if "error" not in r]
for r in errors:
    st.warning(f"{r['ticker']}: {r['error']}")
if not ok:
    st.stop()

# ---------------- focus stock ----------------

focus_t = st.selectbox("Focus stock", [r["ticker"] for r in ok])
r = next(x for x in ok if x["ticker"] == focus_t)

st.subheader(f"{r['ticker']} · {r['name']}")
st.caption(f"{r['sector']}{' › ' + r['industry'] if r.get('industry') else ''}  ·  Price ${fmt(r['price'], 2)}  ·  fetched {r['fetched']}")

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.metric("P/E (trailing)", fmt(r["pe"], 1, "x"), help=HELP["pe"])
    st.markdown(badge(r["pe_read"]), unsafe_allow_html=True)
with c2:
    st.metric("Forward P/E", fmt(r["forward_pe"], 1, "x"), help=HELP["fpe"],
              delta=None if (r["pe"] is None or r["forward_pe"] is None)
              else f"{(r['forward_pe'] - r['pe']):+.1f}x vs trailing", delta_color="inverse")
    st.markdown(badge(r["fpe_read"]), unsafe_allow_html=True)
with c3:
    st.metric("PEG", fmt(r["peg"], 2), help=HELP["peg"])
    st.markdown(badge(r["peg_read"]), unsafe_allow_html=True)
with c4:
    st.metric("Forward PEG", fmt(r["fpeg"], 2), help=HELP["fpeg"])
    st.markdown(badge(r["fpeg_read"]), unsafe_allow_html=True)
with c5:
    st.metric("Growth estimate", fmt(r["growth_pct"], 1, "%"), help=HELP["growth"])
    st.caption(f"Source: {r['growth_source']}"
               + (f" · Yahoo PEG {fmt(r['yahoo_peg'], 2)}" if r["yahoo_peg"] else ""))

# EPS row: the profit per share behind the ratios above
e1, e2, e3, e4 = st.columns(4)
eps_chg = ((r["eps_next_y"] / r["eps_ttm"] - 1) * 100
           if (r["eps_ttm"] and r["eps_next_y"] and r["eps_ttm"] > 0) else None)
with e1:
    st.metric("Profit per share, last 12 months", "—" if r["eps_ttm"] is None else f"${r['eps_ttm']:,.2f}",
              help="Trailing EPS: the profit each share earned over the last four quarterly reports. This already happened.")
with e2:
    st.metric("Profit per share, next year (est.)", "—" if r["eps_next_y"] is None else f"${r['eps_next_y']:,.2f}",
              help="Forward EPS: the average of analysts' forecasts for the next 12 months. This is a prediction.")
with e3:
    st.metric("Expected change", fmt(eps_chg, 0, "%"),
              help="How much bigger (or smaller) next year's profit per share is expected to be.")
with e4:
    st.caption("How the ratios are built")
    st.markdown(f"P/E = ${fmt(r['price'], 2)} ÷ ${fmt(r['eps_ttm'], 2)} = **{fmt(r['pe'], 1, 'x')}**  \n"
                f"Fwd P/E = ${fmt(r['price'], 2)} ÷ ${fmt(r['eps_next_y'], 2)} = **{fmt(r['forward_pe'], 1, 'x')}**"
                .replace("$", "\\$"))

if r["flags"]:
    st.markdown(f"**⚠️ {len(r['flags'])} reason{'s' if len(r['flags']) > 1 else ''} to double-check these numbers**")
    for title, why in r["flags"]:
        st.warning(f"**{title}.** {why}".replace("$", "\\$"))  # escape $ so it isn't read as math
else:
    st.success("No warning signs: the growth estimate is long-term and past and future earnings line up.")

flag_titles = {t for t, _ in r["flags"]}
growth_shaky = bool(flag_titles & {"Growth is a short-term forecast", "Unusually high growth estimate"})
only_mismatch = flag_titles == {"Past and future earnings don't match up"}

if only_mismatch and r["fpeg"] is not None:
    verdict = (f"The growth estimate is long-term, but last year's earnings don't match next year's. So the regular "
               f"PEG ({fmt(r['peg'], 2)}) is distorted by last year's odd profit. The forward PEG "
               f"({r['fpeg']:.2f}, {r['fpeg_read'].lower()}) compares like with like and is the better read. "
               "Remember it still rests on analyst forecasts.")
elif r["flags"] and growth_shaky and r["peg"] is not None:
    fpe_txt = (f" Forward P/E ({r['forward_pe']:.1f}x) is the cleaner number here: compare it with similar companies."
               if r["forward_pe"] is not None else "")
    verdict = (f"Because of the warnings above, don't trust {r['ticker']}'s PEG ({r['peg']:.2f}) or forward PEG "
               f"({fmt(r['fpeg'], 2)}) on their own. Both divide by a growth estimate that may be distorted."
               + fpe_txt)
elif r["flags"] and r["pe"] is None:
    verdict = f"{r['ticker']} had no profit last year, so P/E and PEG don't apply. Judge it on revenue growth and cash flow."
elif r["peg"] is not None:
    if r["peg"] < 1:
        verdict = f"At a PEG of {r['peg']:.2f}, {r['ticker']} is priced below its expected growth. Check that the {r['growth_pct']:.0f}% estimate is realistic."
    elif r["peg"] <= 2:
        verdict = f"At a PEG of {r['peg']:.2f}, {r['ticker']}'s price and growth outlook are roughly in balance."
    else:
        verdict = f"At a PEG of {r['peg']:.2f}, {r['ticker']} trades at a premium. The business has to beat forecasts to justify this price."
elif r["pe"] is None:
    verdict = f"{r['ticker']} has no trailing profits, so earnings ratios don't apply. Judge it on revenue growth and cash flow."
else:
    verdict = "No usable growth estimate, so PEG can't be calculated."
st.info(verdict)

if r.get("history") is not None and not r["history"].empty:
    price_chart = alt.Chart(r["history"]).mark_area(
        line={"color": "#2b8a7e"}, color=alt.Gradient(
            gradient="linear", stops=[alt.GradientStop(color="#2b8a7e55", offset=0),
                                      alt.GradientStop(color="#2b8a7e05", offset=1)], x1=1, x2=1, y1=0, y2=1)
    ).encode(x=alt.X("Date:T", title=None), y=alt.Y("Close:Q", title="Price ($)", scale=alt.Scale(zero=False)),
             tooltip=[alt.Tooltip("Date:T"), alt.Tooltip("Close:Q", format="$,.2f")]).properties(height=220,
                                                                                               title="1-year price")
    st.altair_chart(price_chart, width="stretch")

# ---------------- competitors ----------------

peer_summary = None  # filled in by the competitor section, reused in the stock story
peer_rows, peer_meds = [], {}
st.subheader(f"{r['ticker']} vs. its competitors")
peer_list, peer_src = find_peers(r["ticker"], r.get("industry_key", ""))
other_watch = [x["ticker"] for x in ok if x["ticker"] != r["ticker"]]
options = list(dict.fromkeys(peer_list + other_watch))
st.caption(
    (f"Competitors found via {peer_src}. " if peer_list else "No competitors found automatically. ")
    + "Remove any that don't make money the same way, or add your own.")
pc1, pc2 = st.columns([3, 1])
with pc1:
    chosen = st.multiselect("Competitors", options, default=peer_list[:6], key=f"peers_{r['ticker']}")
with pc2:
    extra = st.text_input("Add tickers", placeholder="e.g. HOOD, IBKR", key=f"extra_{r['ticker']}")
chosen = list(dict.fromkeys(chosen + [t.strip().upper() for t in extra.replace(",", " ").split() if t.strip()]))
chosen = [c for c in chosen if c != r["ticker"]]

if not chosen:
    st.info("Pick at least one competitor to compare against.")
else:
    peers_data = []
    with st.spinner("Pulling competitor numbers..."):
        for t in chosen:
            try:
                d = fetch(t)
            except Exception as e:
                d = {"ticker": t, "error": str(e)}
            if "error" in d:
                st.caption(f"Skipped {t}: {d['error']}")
            else:
                peers_data.append(d)

    if peers_data:
        pdf = pd.DataFrame([{k: v for k, v in x.items() if k not in ("history", "flags")} for x in peers_data])
        METRICS = [("forward_pe", "Forward P/E", "x", 1), ("pe", "P/E", "x", 1),
                   ("fpeg", "Forward PEG", "", 2), ("peg", "PEG", "", 2), ("growth_pct", "Growth", "%", 1)]

        st.markdown(f"**{r['ticker']} compared with the middle value (median) of {len(peers_data)} competitors**")
        mcols = st.columns(len(METRICS))
        diffs = {}
        for col, (key, label, suf, d) in zip(mcols, METRICS):
            vals = pd.to_numeric(pdf[key], errors="coerce")
            vals = vals[vals > 0] if key != "growth_pct" else vals.dropna()
            med = vals.median() if len(vals) else None
            mine = r.get(key)
            diff = (mine / med - 1) * 100 if (mine is not None and med not in (None, 0) and med > 0) else None
            diffs[key] = (mine, med, diff)
            with col:
                st.metric(f"{label}", fmt(mine, d, suf),
                          delta=None if diff is None else f"{diff:+.0f}% vs peers ({fmt(med, d, suf)})",
                          delta_color="normal" if key == "growth_pct" else "inverse",
                          help="Green = better for you as a buyer: cheaper than peers on price ratios, "
                               "faster than peers on growth.")

        # Plain-English read, led by forward P/E (fairest when earnings are messy)
        lines = []
        mine, med, diff = diffs["forward_pe"]
        if diff is not None:
            if diff <= -15:
                lines.append(f"On forward P/E, {r['ticker']} is about **{abs(diff):.0f}% cheaper** than its typical competitor "
                             f"({fmt(mine, 1, 'x')} vs {fmt(med, 1, 'x')}). The market expects less from it, or it may be overlooked.")
            elif diff >= 15:
                lines.append(f"On forward P/E, {r['ticker']} is about **{diff:.0f}% more expensive** than its typical competitor "
                             f"({fmt(mine, 1, 'x')} vs {fmt(med, 1, 'x')}). Investors expect more from it than from its rivals.")
            else:
                lines.append(f"On forward P/E, {r['ticker']} is priced **in line** with its competitors "
                             f"({fmt(mine, 1, 'x')} vs {fmt(med, 1, 'x')}).")
        gm, gmed, gd = diffs["growth_pct"]
        if gm is not None and gmed is not None:
            faster = gm > gmed
            lines.append(f"Its expected growth ({fmt(gm, 1, '%')}) is **{'faster' if faster else 'slower'}** than the "
                         f"typical competitor ({fmt(gmed, 1, '%')}).")
            if diff is not None:
                if diff <= -15 and faster:
                    lines.append("Cheaper *and* faster-growing than peers: worth a closer look at why the market is discounting it.")
                elif diff >= 15 and not faster:
                    lines.append("Pricier *and* slower-growing than peers: the market may be paying for something else "
                                 "(brand, safety, profit margins), or the stock may be stretched.")
        if r["flags"]:
            lines.append(f"{r['ticker']} has {len(r['flags'])} warning(s) above, so lean on forward P/E over PEG here.")
        st.info("\n\n".join(lines) if lines else "Not enough data to compare.")
        peer_summary = " ".join(lines[:2]) if lines else None
        peer_rows = [f"{p['ticker']}, {p['name']}, {p.get('industry') or '?'}, {fmt(p['forward_pe'], 1, 'x')}, "
                     f"{fmt(p['pe'], 1, 'x')}, {fmt(p['growth_pct'], 1, '%')}" for p in peers_data]
        peer_meds = {lbl: fmt(diffs[k][1], d, suf) for k, lbl, suf, d in METRICS}

        # Chart: one metric across the group, focus stock highlighted, peer median marked
        pick = st.radio("Compare on", [m[1] for m in METRICS], horizontal=True, key="peer_metric")
        key, label, suf, d = next(m for m in METRICS if m[1] == pick)
        group = pd.concat([pd.DataFrame([{k: v for k, v in r.items() if k not in ("history", "flags")}]), pdf],
                          ignore_index=True)
        group[key] = pd.to_numeric(group[key], errors="coerce")
        plot = group.dropna(subset=[key])
        if key != "growth_pct":
            plot = plot[plot[key] > 0]
        if plot.empty:
            st.caption("No values to chart for this measure.")
        else:
            plot = plot.assign(role=["This stock" if t == r["ticker"] else "Competitor" for t in plot["ticker"]])
            med = diffs[key][1]
            bars = alt.Chart(plot).mark_bar(cornerRadiusEnd=4).encode(
                y=alt.Y("ticker:N", sort=alt.EncodingSortField(field=key, order="ascending"), title=None),
                x=alt.X(f"{key}:Q", title=label),
                color=alt.Color("role:N", scale=alt.Scale(domain=["This stock", "Competitor"],
                                                          range=["#2b8a7e", "#9aa7a3"]), legend=alt.Legend(title=None)),
                tooltip=["ticker", "name", alt.Tooltip(f"{key}:Q", format=f".{d}f", title=label)])
            layers = bars
            if med is not None:
                layers = bars + alt.Chart(pd.DataFrame({"m": [med]})).mark_rule(
                    strokeDash=[5, 4], color="#d69e2e", size=2).encode(x="m:Q", tooltip=[alt.Tooltip("m:Q", format=f".{d}f", title="Peer median")])
            st.altair_chart(layers.properties(height=max(180, 38 * len(plot))), width="stretch")
            st.caption("Dashed line = competitors' median. Shorter bars are cheaper on price measures; "
                       "longer bars are better on growth.")

        gtable = group[["ticker", "name", "industry", "price", "eps_ttm", "eps_next_y", "pe", "forward_pe", "growth_pct", "peg", "fpeg"]].rename(
            columns={"ticker": "Ticker", "name": "Name", "industry": "Industry", "price": "Price", "eps_ttm": "EPS (12 mo)", "eps_next_y": "EPS next yr", "pe": "P/E",
                     "forward_pe": "Fwd P/E", "growth_pct": "Growth %", "peg": "PEG", "fpeg": "Fwd PEG"})
        st.dataframe(gtable.style.format({"Price": "${:,.2f}", "EPS (12 mo)": "${:,.2f}", "EPS next yr": "${:,.2f}", "P/E": "{:.1f}x", "Fwd P/E": "{:.1f}x",
                                          "Growth %": "{:.1f}%", "PEG": "{:.2f}", "Fwd PEG": "{:.2f}"}, na_rep="—"),
                     width="stretch", hide_index=True)

st.divider()

# ---------------- understand this stock ----------------

st.divider()
st.subheader(f"Understand {r['ticker']}")
st.caption("The numbers above, told as a story, plus the evidence behind analysts' expectations.")
try:
    sinfo = fetch_story(r["ticker"])
except Exception as e:
    sinfo = None
    st.caption(f"Couldn't load extra details: {e}")

tab_ai, tab_story, tab_why, tab_biz, tab_news = st.tabs(
    ["AI analysis (full write-up)", "The story in plain English", "Why profit is expected to change",
     "What the business does", "Recent news"])

with tab_ai:
    st.markdown(f"One click writes a complete, beginner-friendly explanation of **{r['ticker']}** from every number "
                "on this screen: what it sells, why profit is expected to change, what the warnings mean, "
                "risks, rivals and the bottom line.")
    store = ai_store()
    today = f"{datetime.now():%Y%m%d}"
    ai_key_name = f"{r['ticker']}_{today}"          # one shared analysis per stock per day
    saved = store["texts"].get(ai_key_name)
    used_today = store["count"].get(today, 0)
    over_limit = ai_owner_key_used and used_today >= AI_DAILY_LIMIT
    ready = (bool(ai_key) if ai_provider.startswith("Claude") else bool(ai_model)) and not over_limit
    if ai_provider.startswith("Claude") and not ai_key:
        if saved:
            st.caption("Showing today's saved analysis. Unlock in the sidebar to write a new one.")
        else:
            st.info("To write an analysis, enter the password or your own Anthropic API key in the sidebar "
                    "(under AI analysis)."
                    + ("" if HOSTED else " Or switch to Ollama to run it free on your computer."))
    if over_limit:
        st.warning(f"Today's limit of {AI_DAILY_LIMIT} new analyses has been reached. Saved ones still show; "
                   "try again tomorrow or use your own API key.")
    b1, b2 = st.columns([1, 3])
    go = b1.button("Write the analysis" if not saved else "Rewrite",
                   disabled=not ready, type="primary", key=f"go_{r['ticker']}")
    b2.caption("Written once per stock per day and shared with everyone, so repeat visits cost nothing. "
               "The AI only sees this screen's data, so check anything surprising.")
    if go:
        ctx = build_ai_context(r, sinfo, peer_rows, peer_meds, eps_chg)
        gen = (stream_claude(ctx, ai_model, ai_key) if ai_provider.startswith("Claude")
               else stream_ollama(ctx, ai_model))
        collected = []

        def _escaped():
            for chunk in gen:
                collected.append(chunk)
                yield chunk.replace("$", "\\$")
        try:
            if ai_owner_key_used:
                store["count"][today] = store["count"].get(today, 0) + 1
            st.write_stream(_escaped())
            saved = store["texts"][ai_key_name] = "".join(collected)
        except ModuleNotFoundError:
            st.error("The Anthropic library isn't installed. In a terminal, run:  pip install anthropic")
        except urllib.error.URLError:
            st.error("Couldn't reach Ollama. Open the Ollama app (or run `ollama serve`) and make sure you've "
                     f"pulled the model: `ollama pull {ai_model}`")
        except Exception as e:
            msg = str(e)
            if "authentication" in msg.lower() or "401" in msg:
                st.error("Claude rejected the API key. Check that it's copied correctly.")
            else:
                st.error(f"The analysis couldn't be written: {msg}")
    elif saved:
        st.markdown(saved.replace("$", "\\$"))
    if saved:
        st.download_button("Download this analysis", saved.encode(),
                           f"{r['ticker']}_analysis_{datetime.now():%Y-%m-%d}.md", "text/markdown",
                           key=f"dl_{r['ticker']}")
        st.caption("Educational explanation, not financial advice.")

with tab_story:
    T = r["ticker"]
    parts = []
    if r["eps_ttm"] is not None and r["eps_ttm"] > 0:
        parts.append(f"**1. What you pay today.** One share of {T} costs ${r['price']:,.2f}. Over the last 12 months "
                     f"the company earned ${r['eps_ttm']:,.2f} of profit per share. So you pay about "
                     f"${r['pe']:,.0f} for every $1 of profit (P/E {r['pe']:.1f}). If profit never grew, it would take "
                     f"about {r['pe']:.0f} years of profit to earn back the price. The dashboard rates this "
                     f"**{r['pe_read'].lower()}**.")
    elif r["eps_ttm"] is not None:
        parts.append(f"**1. What you pay today.** One share of {T} costs ${r['price']:,.2f}, but the company lost "
                     f"money over the last 12 months (${r['eps_ttm']:,.2f} per share). With no profit, P/E can't be used.")
    if r["eps_next_y"] is not None and eps_chg is not None:
        direction = "grow" if eps_chg > 0 else "shrink"
        parts.append(f"**2. What's expected next.** Analysts expect profit per share to {direction} to "
                     f"${r['eps_next_y']:,.2f} next year, a change of {eps_chg:+.0f}%. On that future profit, "
                     f"today's price works out to {r['forward_pe']:.1f}x (forward P/E). The reasons analysts expect this "
                     f"are in the next tab.")
    if r["growth_pct"] is not None:
        g = r["growth_pct"]
        speed = ("very fast" if g > 25 else "fast" if g > 15 else "steady" if g > 7 else "slow")
        parts.append(f"**3. How fast it's growing.** Over the next several years, analysts expect profit to grow "
                     f"about {g:.1f}% a year, which is **{speed}**. At that pace profit would roughly double in "
                     f"{dbl_txt(g)}." if g > 0 else
                     f"**3. How fast it's growing.** Analysts expect profit to shrink, about {g:.1f}% a year.")
    if r["peg"] is not None:
        parts.append(f"**4. Is the price fair for that growth?** PEG = {r['pe']:.1f} ÷ {r['growth_pct']:.1f} = "
                     f"{r['peg']:.2f}: **{r['peg_read'].lower()}**."
                     + (f" Using next year's profit instead, the forward PEG is {r['fpeg']:.2f}."
                        if r["fpeg"] is not None else ""))
    if peer_summary:
        parts.append(f"**5. Against its rivals.** {peer_summary}")
    if r["flags"]:
        parts.append("**6. Be careful.** " + " ".join(f"{t}." for t, _ in r["flags"])
                     + " See the warnings above for what each one means.")
    else:
        parts.append("**6. Data check.** No warning signs: the numbers line up and can be read at face value.")
    st.markdown("\n\n".join(parts).replace("$", "\\$"))

with tab_why:
    if not sinfo:
        st.write("No extra data available.")
    else:
        st.markdown("Analysts don't guess randomly. These are the main clues they use. "
                    "**Green** points support the forecast, **amber** ones are reasons for caution.")
        support, caution = [], []

        # EPS path chart
        if len(sinfo["eps_path"]) >= 2:
            pdf_ = pd.DataFrame(sinfo["eps_path"], columns=["Period", "EPS"])
            pdf_["kind"] = ["Actual" if "actual" in p else "Estimate" for p in pdf_["Period"]]
            ch = alt.Chart(pdf_).mark_bar(cornerRadiusEnd=4).encode(
                x=alt.X("Period:N", sort=list(pdf_["Period"]), title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("EPS:Q", title="Profit per share ($)"),
                color=alt.Color("kind:N", scale=alt.Scale(domain=["Actual", "Estimate"], range=["#2b8a7e", "#9fd3c9"]),
                                legend=alt.Legend(title=None)),
                tooltip=["Period", alt.Tooltip("EPS:Q", format="$.2f")])
            txt = ch.mark_text(dy=-8, fontWeight="bold").encode(text=alt.Text("EPS:Q", format="$.2f"),
                                                               color=alt.value("#888"))
            st.markdown("**The profit-per-share path analysts expect** (company fiscal years)")
            st.altair_chart((ch + txt).properties(height=240), width="stretch")

        rg, eg = sinfo["revenue_growth"], sinfo["earnings_growth"]
        if rg is not None:
            (support if rg > 5 else caution).append(
                f"**Sales** in the latest quarter were {rg:+.1f}% vs. the same quarter last year. "
                + ("Growing sales are the fuel for growing profit." if rg > 5 else
                   "Sales aren't growing much, so profit growth has to come from cost cuts or higher prices."))
        if eg is not None:
            (support if eg > 0 else caution).append(
                f"**Profit** in the latest quarter was {eg:+.1f}% vs. a year ago. "
                + ("The business is already growing profit now, not just in forecasts." if eg > 0 else
                   "Profit actually fell recently, so the expected rebound still has to happen."))
        if sinfo["margin"] is not None:
            m = sinfo["margin"]
            (support if m > 8 else caution).append(f"**Profit margin** is {m:.1f}%: out of every $100 of sales, about ${m:.0f} is profit. "
                           + ("That's high, so extra sales turn into profit easily." if m > 20 else
                              "That's moderate." if m > 8 else "That's thin, so small cost increases hurt profit."))
        en, e90 = sinfo["est_now"], sinfo["est_90"]
        if en is not None and e90 is not None and e90 != 0:
            ch_ = (en / e90 - 1) * 100
            if ch_ > 1:
                support.append(f"**Analysts are getting more optimistic.** Three months ago they expected "
                               f"${e90:,.2f} for next year; now ${en:,.2f} ({ch_:+.1f}%). Raised estimates usually "
                               "follow good news from the company.")
            elif ch_ < -1:
                caution.append(f"**Analysts are getting less optimistic.** Three months ago they expected "
                               f"${e90:,.2f} for next year; now ${en:,.2f} ({ch_:+.1f}%). Cut estimates often follow "
                               "weak results or a cautious outlook from the company.")
            else:
                support.append(f"**Estimates are stable**: about ${en:,.2f} now vs ${e90:,.2f} three months ago.")
        if sinfo["beats"]:
            b = sum(1 for _, a, e in sinfo["beats"] if a >= e)
            n = len(sinfo["beats"])
            (support if b >= n - 1 else caution).append(
                f"**Track record:** the company beat analysts' forecasts in {b} of the last {n} quarters. "
                + ("A company that usually beats forecasts makes the next forecast more believable."
                   if b >= n - 1 else "Missing forecasts often means the next forecast may be too high."))
        lo, hi = sinfo["est_low"], sinfo["est_high"]
        if lo and hi and lo > 0:
            spread = (hi / lo - 1) * 100
            n_txt = f"{sinfo['est_n']} analysts" if sinfo["est_n"] else "Analysts"
            (support if spread < 25 else caution).append(
                f"**Agreement:** {n_txt} forecast between ${lo:,.2f} and ${hi:,.2f} for next year. "
                + ("They mostly agree, which makes the average more reliable." if spread < 25 else
                   f"That's a wide range ({spread:.0f}% apart): experts disagree, so treat the average with care."))
        if any(t == "Past and future earnings don't match up" for t, _ in r["flags"]):
            caution.append("**Accounting difference:** part of the expected jump may come from comparing official "
                           "(GAAP) profit with analysts' adjusted profit, not real growth.")

        for s in support:
            st.success(s.replace("$", "\\$"))
        for c in caution:
            st.warning(c.replace("$", "\\$"))
        if not support and not caution:
            st.write("Yahoo didn't return estimate details for this stock.")

        if sinfo["analysts"] and sinfo["rec"]:
            tgt = (f" Their average 12-month price target is ${sinfo['target']:,.2f} "
                   f"({(sinfo['target'] / r['price'] - 1) * 100:+.0f}% from today)." if sinfo["target"] else "")
            st.caption((f"Opinion, not a fact: {sinfo['analysts']} analysts' average rating is "
                        f"\"{str(sinfo['rec']).replace('_', ' ')}\".{tgt} Analysts are often too optimistic, "
                        "so use this as one input only.").replace("$", "\\$"))
        st.caption("For the full reason behind a forecast, read the company's latest earnings report or the "
                   "headlines in the Recent news tab: new products, price changes, deals and guidance from "
                   "management are what move analysts' numbers.")

with tab_biz:
    if sinfo and sinfo["summary"]:
        b1, b2, b3 = st.columns(3)
        b1.metric("Company value (market cap)", big_money(sinfo["market_cap"]),
                  help="Share price × number of shares: what the whole company is worth on the stock market.")
        b2.metric("Employees", "—" if not sinfo["employees"] else f"{sinfo['employees']:,}")
        b3.metric("Industry", r.get("industry") or r.get("sector") or "—")
        st.markdown(sinfo["summary"].replace("$", "\\$"))
        st.caption("Ask yourself: how does this company make money, and will people want more of it in 5 years?")
    else:
        st.write("No business description available.")

with tab_news:
    if sinfo and sinfo["news"]:
        st.caption("Headlines often explain why expectations changed. Click through to read them.")
        for title, url, pub, when in sinfo["news"]:
            meta = " · ".join(x for x in (pub, when) if x)
            safe = title.replace("$", "\\$").replace("[", "(").replace("]", ")")
            st.markdown(f"- [{safe}]({url}) — {meta}" if url else f"- {safe} — {meta}")
    else:
        st.write("No recent headlines found.")

# ---------------- comparison ----------------

df = pd.DataFrame([{k: v for k, v in x.items() if k != "history"} for x in ok])
df["peg_sort"] = df["peg"].fillna(1e9)
df = df.sort_values("peg_sort").drop(columns="peg_sort")

left, right = st.columns([1.1, 1])

with left:
    st.subheader("Price vs. growth")
    st.caption("Below the green line: PEG under 1. Above the red line: PEG over 2.")
    sc = df.dropna(subset=["pe", "growth_pct"])
    sc = sc[sc["growth_pct"] > 0]
    if sc.empty:
        st.write("Not enough data to plot.")
    else:
        gmax = max(sc["growth_pct"].max() * 1.15, 10)
        lines = pd.DataFrame({"g": [0, gmax, 0, gmax], "pe": [0, gmax, 0, 2 * gmax],
                              "band": ["PEG 1", "PEG 1", "PEG 2", "PEG 2"]})
        ref = alt.Chart(lines).mark_line(strokeDash=[6, 4]).encode(
            x="g:Q", y="pe:Q",
            color=alt.Color("band:N", scale=alt.Scale(domain=["PEG 1", "PEG 2"], range=[GOOD, BAD]), legend=None))
        sc = sc.assign(color=sc["peg_read"].map(color_for))
        pts = alt.Chart(sc).mark_circle(size=140, opacity=0.9).encode(
            x=alt.X("growth_pct:Q", title="Expected growth (%/yr)", scale=alt.Scale(domain=[0, gmax])),
            y=alt.Y("pe:Q", title="P/E (trailing)",
                    scale=alt.Scale(domain=[0, max(sc["pe"].max() * 1.15, 2 * gmax * 0.6)])),
            color=alt.Color("color:N", scale=None),
            tooltip=["ticker", alt.Tooltip("pe:Q", format=".1f", title="P/E"),
                     alt.Tooltip("growth_pct:Q", format=".1f", title="Growth %"),
                     alt.Tooltip("peg:Q", format=".2f", title="PEG")])
        labels = pts.mark_text(dx=10, align="left", fontWeight="bold").encode(text="ticker", color=alt.value("#888"))
        st.altair_chart((ref + pts + labels).properties(height=360), width="stretch")

with right:
    st.subheader("PEG ranking")
    st.caption("Cheapest for its growth at the top.")
    bars = df.dropna(subset=["peg"])
    if bars.empty:
        st.write("No PEG values to rank.")
    else:
        bars = bars.assign(color=bars["peg_read"].map(color_for))
        b = alt.Chart(bars).mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("ticker:N", sort=list(bars["ticker"]), title=None),
            x=alt.X("peg:Q", title="PEG"),
            color=alt.Color("color:N", scale=None),
            tooltip=["ticker", alt.Tooltip("peg:Q", format=".2f"), "peg_read"])
        rules = alt.Chart(pd.DataFrame({"x": [1, 2]})).mark_rule(strokeDash=[4, 4], color="#888").encode(x="x:Q")
        st.altair_chart((b + rules).properties(height=max(200, 44 * len(bars))), width="stretch")

st.subheader("All tickers")
st.caption("Warnings column: how many reasons to double-check that stock. Pick it as the focus stock to see them.")
df["warnings"] = df["flags"].apply(lambda f: "⚠️ " + str(len(f)) if f else "✓ none")
table = df[["ticker", "name", "price", "eps_ttm", "eps_next_y", "pe", "forward_pe", "growth_pct", "peg", "fpeg",
            "pe_read", "fpe_read", "peg_read", "warnings"]]
table = table.rename(columns={"ticker": "Ticker", "name": "Name", "price": "Price", "eps_ttm": "EPS (12 mo)", "eps_next_y": "EPS next yr", "pe": "P/E",
                              "forward_pe": "Fwd P/E", "growth_pct": "Growth %", "peg": "PEG", "fpeg": "Fwd PEG",
                              "pe_read": "P/E read", "fpe_read": "Fwd read", "peg_read": "PEG read",
                              "warnings": "Warnings"})


def shade(v):
    c = color_for(v)
    return f"color:{c};font-weight:600" if c != NA else ""


styled = (table.style
          .format({"Price": "${:,.2f}", "EPS (12 mo)": "${:,.2f}", "EPS next yr": "${:,.2f}", "P/E": "{:.1f}x", "Fwd P/E": "{:.1f}x", "Growth %": "{:.1f}%", "PEG": "{:.2f}",
                   "Fwd PEG": "{:.2f}"},
                  na_rep="—")
          .map(shade, subset=["P/E read", "Fwd read", "PEG read"]))
st.dataframe(styled, width="stretch", hide_index=True)

st.download_button("Download as CSV", table.to_csv(index=False).encode(), "valuation_dashboard.csv", "text/csv")

# ---------------- learn the terms ----------------

st.divider()
st.subheader("Learn the terms")
st.caption("Plain-English explanations of everything on this dashboard. Click any one to open it.")

GLOSSARY = [
    ("Stock price and share",
     "A **share** is a tiny slice of ownership in a company. The **stock price** is what one share costs right now. "
     "On its own the price tells you nothing about whether the stock is cheap: a $500 share of a company earning a "
     "lot can be a better deal than a $5 share of a company earning almost nothing. That's why we compare price "
     "to profits."),
    ("Earnings (profit)",
     "**Earnings** are what a company has left after paying all its costs: salaries, materials, rent, taxes, "
     "interest. It's the company's profit. Investors care because, over time, a stock's value follows the "
     "profits the business makes."),
    ("EPS (earnings per share)",
     "Total profit divided by the number of shares. If a company earns $10 billion and has 1 billion shares, "
     "EPS is $10. It tells you how much profit 'belongs' to each share you own.\n\n"
     "- **Trailing EPS (TTM)**: profit from the last 12 months. TTM means 'trailing twelve months'. "
     "This already happened.\n"
     "- **Forward EPS**: what analysts expect for next year. This is a guess."),
    ("P/E ratio (price-to-earnings)",
     "**Price ÷ trailing EPS.** How many dollars you pay for each $1 of yearly profit.\n\n"
     "Example: a $300 share with $10 EPS has a P/E of 30. You're paying $30 for every $1 the company earns.\n\n"
     "Another way to think about it: if profits never changed, it would take 30 years of earnings to "
     "'pay back' the price. Lower P/E = cheaper. The US market has historically averaged roughly 15–25.\n\n"
     "**Why a high P/E isn't always bad:** investors pay more for companies they expect to grow fast."),
    ("Forward P/E",
     "**Price ÷ forward EPS.** Same as P/E, but uses next year's expected profit.\n\n"
     "- Forward P/E **lower** than P/E → profits are expected to grow.\n"
     "- Forward P/E **higher** than P/E → profits are expected to shrink.\n\n"
     "Catch: it relies on analyst forecasts, which can be wrong."),
    ("Growth rate",
     "How fast analysts expect the company's EPS to grow each year, as a percent. 15% means profits are "
     "expected to rise about 15% a year.\n\n"
     "- **Long-term (5-year or 'LTG')**: average expected growth over several years. More stable.\n"
     "- **One-year (+1y)**: growth expected next year only. Can be distorted by one unusual year."),
    ("PEG ratio",
     "**P/E ÷ growth rate.** Fixes P/E's blind spot by taking growth into account.\n\n"
     "Example: Company A has P/E 40 but grows 40% a year → PEG 1.0. Company B has P/E 15 but grows 5% → PEG 3.0. "
     "A looks expensive by P/E, but for its growth it's actually cheaper than B.\n\n"
     "- **Under 1** – you may be getting growth on sale\n"
     "- **1 to 2** – roughly fair\n"
     "- **Over 2** – you're paying a premium\n\n"
     "PEG is only as good as the growth estimate behind it."),
    ("Forward PEG",
     "**Forward P/E ÷ growth rate.** Same as PEG but built on next year's expected earnings. "
     "Helpful when last year's profit was unusual (a big one-time charge, a bad year). But it still divides "
     "by the growth estimate, so if the growth number is shaky, forward PEG is shaky too."),
    ("GAAP vs. adjusted earnings",
     "**GAAP** (Generally Accepted Accounting Principles) is the official US rulebook for reporting profit. "
     "It counts everything, including one-time costs.\n\n"
     "**Adjusted** (or 'non-GAAP') earnings are a company's own version that leaves some costs out, such as "
     "the cost of buying another company or stock paid to employees. Adjusted profit is usually higher.\n\n"
     "Yahoo's trailing EPS is usually GAAP, but analysts' forward estimates are often adjusted. Mixing them "
     "can make growth look much bigger than it is. That's what the 'earnings don't match up' warning catches."),
    ("Analyst estimates",
     "Professionals at banks and research firms who study a company publish forecasts for its future profit "
     "and growth. The numbers here are the average of those forecasts (the 'consensus'). They're educated "
     "guesses and are often revised."),
    ("Sector",
     "The industry group a company belongs to (Technology, Consumer Staples, Financials, etc.). Normal P/E "
     "levels differ a lot by sector, so compare a stock mostly against others in the same sector."),
    ("When these ratios don't work well",
     "- **Companies losing money**: no profit means no P/E.\n"
     "- **Banks and insurers**: usually judged on book value instead.\n"
     "- **Cyclical companies** (oil, steel, carmakers): profits swing with the economy, so P/E looks lowest "
     "right at the peak, just before profits fall.\n"
     "- **Big dividend payers** (like Coca-Cola): grow slowly on purpose and pay cash out instead, so PEG "
     "makes them look more expensive than they are."),
]
gcols = st.columns(2)
for i, (term, text) in enumerate(GLOSSARY):
    with gcols[i % 2]:
        with st.expander(term):
            st.markdown(text.replace("$", "\\$"))  # escape $ so amounts show

st.caption("Rules of thumb, not buy or sell signals. P/E means little without profits; PEG is only as good as "
           "its growth estimate. Banks, cyclicals and big dividend payers often don't fit these bands. "
           "For education only, not financial advice.")
