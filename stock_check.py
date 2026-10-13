#!/usr/bin/env python3
"""
Valuation Check - pulls P/E, forward P/E and PEG from Yahoo Finance and grades them.

Setup (once):
    pip install yfinance

Use:
    python stock_check.py MSFT
    python stock_check.py MSFT NVDA AAPL COST
    python stock_check.py                 (asks for tickers)
    python stock_check.py MSFT NVDA --csv results.csv

Rules of thumb only. For education, not financial advice.
"""

import argparse
import csv
import sys

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance is not installed. Run:  pip install yfinance")


# ---------- helpers ----------

def to_num(v):
    try:
        n = float(v)
        return n if n == n else None  # filters NaN
    except (TypeError, ValueError):
        return None


def growth_estimate(tk):
    """Best available annual EPS growth estimate, as a percent (e.g. 18.8)."""
    # 1) Long-term growth (5y / LTG) from analyst growth estimates
    try:
        ge = tk.growth_estimates
        if ge is not None and not ge.empty:
            col = "stockTrend" if "stockTrend" in ge.columns else ge.columns[0]
            for row in ("LTG", "+5y", "+1y", "0y"):
                if row in ge.index:
                    g = to_num(ge.loc[row, col])
                    if g is not None:
                        return g * 100, f"analyst {row} growth"
    except Exception:
        pass
    # 2) Next-year growth from earnings estimates
    try:
        ee = tk.earnings_estimate
        if ee is not None and not ee.empty and "growth" in ee.columns:
            for row in ("+1y", "0y"):
                if row in ee.index:
                    g = to_num(ee.loc[row, "growth"])
                    if g is not None:
                        return g * 100, f"analyst {row} EPS growth"
    except Exception:
        pass
    # 3) Implied by trailing vs forward EPS
    try:
        info = tk.info
        t, f = to_num(info.get("trailingEps")), to_num(info.get("forwardEps"))
        if t and f and t > 0:
            return (f / t - 1) * 100, "forward vs trailing EPS"
    except Exception:
        pass
    return None, "not available"


def grade_pe(pe, eps):
    if pe is None:
        return "No profits" if (eps is not None and eps <= 0) else "n/a"
    if pe < 15:
        return "Low"
    if pe <= 25:
        return "Middle"
    return "High"


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
    if peg < 1:
        return "Growth on sale"
    if peg <= 2:
        return "Fair value"
    return "Premium"


# ---------- core ----------

def check(symbol):
    tk = yf.Ticker(symbol)
    info = tk.info or {}

    price = to_num(info.get("currentPrice")) or to_num(info.get("regularMarketPrice"))
    if price is None:
        try:
            price = to_num(tk.fast_info["last_price"])
        except Exception:
            pass
    if price is None:
        return {"ticker": symbol, "error": "no price found (check the ticker)"}

    eps = to_num(info.get("trailingEps"))
    feps = to_num(info.get("forwardEps"))
    growth, gsrc = growth_estimate(tk)

    pe = price / eps if eps and eps > 0 else None
    fpe = price / feps if feps and feps > 0 else None
    peg = pe / growth if (pe is not None and growth and growth > 0) else None
    yahoo_peg = to_num(info.get("trailingPegRatio")) or to_num(info.get("pegRatio"))

    return {
        "ticker": symbol,
        "name": info.get("shortName") or "",
        "price": price,
        "eps_ttm": eps,
        "eps_next_y": feps,
        "growth_pct": growth,
        "growth_source": gsrc,
        "pe": pe,
        "forward_pe": fpe,
        "peg": peg,
        "yahoo_peg": yahoo_peg,
        "pe_read": grade_pe(pe, eps),
        "fpe_read": grade_fpe(fpe, pe),
        "peg_read": grade_peg(peg),
    }


def f(n, d=1, suffix=""):
    return "—" if n is None else f"{n:,.{d}f}{suffix}"


def print_one(r):
    if "error" in r:
        print(f"\n{r['ticker']}: {r['error']}")
        return
    print(f"\n{r['ticker']}  {r['name']}")
    print(f"  Price            ${f(r['price'], 2)}")
    print(f"  EPS (12 mo)      ${f(r['eps_ttm'], 2)}")
    print(f"  EPS next yr est. ${f(r['eps_next_y'], 2)}")
    print(f"  Growth           {f(r['growth_pct'], 1, '%')}  ({r['growth_source']})")
    print(f"  P/E              {f(r['pe'], 1, 'x'):>8}   {r['pe_read']}")
    print(f"  Forward P/E      {f(r['forward_pe'], 1, 'x'):>8}   {r['fpe_read']}")
    print(f"  PEG              {f(r['peg'], 2):>8}   {r['peg_read']}")
    if r["yahoo_peg"] is not None:
        print(f"  (Yahoo's own PEG: {f(r['yahoo_peg'], 2)})")


def print_table(rows):
    ok = [r for r in rows if "error" not in r]
    if len(ok) < 2:
        return
    ok.sort(key=lambda r: r["peg"] if r["peg"] is not None else 1e9)
    print("\nRanked by PEG (cheapest first)")
    print(f"{'Ticker':<8}{'Price':>11}{'P/E':>9}{'Fwd P/E':>9}{'Growth':>9}{'PEG':>7}  Read")
    print("-" * 70)
    for r in ok:
        print(f"{r['ticker']:<8}{f(r['price'], 2):>11}{f(r['pe'], 1, 'x'):>9}"
              f"{f(r['forward_pe'], 1, 'x'):>9}{f(r['growth_pct'], 1, '%'):>9}"
              f"{f(r['peg'], 2):>7}  {r['peg_read']}")


def main():
    ap = argparse.ArgumentParser(description="Grade stocks on P/E, forward P/E and PEG.")
    ap.add_argument("tickers", nargs="*", help="e.g. MSFT NVDA AAPL")
    ap.add_argument("--csv", help="save results to this CSV file")
    args = ap.parse_args()

    tickers = args.tickers
    if not tickers:
        raw = input("Tickers (space or comma separated): ")
        tickers = raw.replace(",", " ").split()
    tickers = [t.strip().upper() for t in tickers if t.strip()]
    if not tickers:
        sys.exit("No tickers given.")

    rows = []
    for t in tickers:
        try:
            r = check(t)
        except Exception as e:
            r = {"ticker": t, "error": f"lookup failed ({e})"}
        rows.append(r)
        print_one(r)

    print_table(rows)

    if args.csv:
        fields = ["ticker", "name", "price", "eps_ttm", "eps_next_y", "growth_pct",
                  "growth_source", "pe", "forward_pe", "peg", "yahoo_peg",
                  "pe_read", "fpe_read", "peg_read"]
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                if "error" not in r:
                    w.writerow(r)
        print(f"\nSaved to {args.csv}")

    print("\nRules of thumb only. For education, not financial advice.")


if __name__ == "__main__":
    main()
