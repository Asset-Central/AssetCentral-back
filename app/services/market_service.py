"""
Market service — búsqueda y precios de mercado via Yahoo Finance (yfinance).
Los calls a yfinance son síncronos; se corren en un ThreadPoolExecutor.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial

import yfinance as yf

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INTRADAY_INTERVALS = {"1m", "5m", "15m", "1h"}


def _detect_type(quote_type: str, exchange: str) -> str:
    qt = (quote_type or "").upper()
    ex = (exchange or "").upper()
    if qt == "CRYPTOCURRENCY":
        return "crypto"
    if qt in ("MUTUALFUND", "ETF"):
        return "fci"
    if qt == "BOND":
        return "bono"
    if ex in ("BUE", "BCBA"):
        return "cedear"
    return "stock"


def _range_to_yf(range_str: str) -> tuple[str, str]:
    """Return (period, interval) for yfinance history call."""
    match range_str:
        case "1h":
            return "1d", "1m"
        case "1d":
            return "1d", "5m"
        case "1w":
            return "5d", "1h"
        case "1y":
            return "1y", "1wk"
        case _:  # "30d"
            return "1mo", "1d"


# ---------------------------------------------------------------------------
# Sync functions (run in executor)
# ---------------------------------------------------------------------------

def _sync_search(query: str) -> list[dict]:
    try:
        results = yf.Search(query, max_results=12).quotes
    except Exception:
        results = []

    out = []
    for r in results:
        symbol: str = r.get("symbol", "")
        if not symbol:
            continue
        name = r.get("longname") or r.get("shortname") or symbol
        exchange = r.get("exchange", "")
        quote_type = r.get("quoteType", "")
        asset_type = _detect_type(quote_type, exchange)

        # Quick price info
        unit_price: float | None = None
        change_pct: float | None = None
        currency: str | None = None
        market_cap: float | None = None
        try:
            fi = yf.Ticker(symbol).fast_info
            unit_price = float(fi.last_price) if fi.last_price else None
            prev = fi.previous_close
            if unit_price and prev:
                change_pct = (unit_price - prev) / prev * 100
            currency = getattr(fi, "currency", None)
            market_cap = float(fi.market_cap) if getattr(fi, "market_cap", None) else None
        except Exception:
            pass

        out.append({
            "ticker": symbol,
            "name": name,
            "asset_type": asset_type,
            "currency": currency,
            "exchange": exchange,
            "unit_price": unit_price,
            "daily_change_pct": change_pct,
            "market_cap": market_cap,
        })
    return out


def _sync_quote(ticker: str) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        unit_price = float(fi.last_price) if fi.last_price else None
        prev = fi.previous_close
        change_pct = (unit_price - prev) / prev * 100 if (unit_price and prev) else None
        info = t.info or {}
        name = info.get("longName") or info.get("shortName") or ticker
        exchange = info.get("exchange", "")
        quote_type = info.get("quoteType", "")
        currency = getattr(fi, "currency", None) or info.get("currency")
        market_cap = float(fi.market_cap) if getattr(fi, "market_cap", None) else None
        return {
            "ticker": ticker,
            "name": name,
            "asset_type": _detect_type(quote_type, exchange),
            "currency": currency,
            "exchange": exchange,
            "unit_price": unit_price,
            "daily_change_pct": change_pct,
            "market_cap": market_cap,
        }
    except Exception:
        return None


def _sync_history(ticker: str, range_str: str) -> list[dict]:
    period, interval = _range_to_yf(range_str)
    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
    except Exception:
        return []

    if hist.empty:
        return []

    # For 1h range: keep only the last 60 minutes
    if range_str == "1h":
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        hist = hist[hist.index.tz_convert("UTC") >= cutoff]

    out = []
    intraday = interval in _INTRADAY_INTERVALS
    for idx, row in hist.iterrows():
        try:
            date_str = idx.isoformat() if intraday else str(idx.date())
        except Exception:
            date_str = str(idx)
        price = row.get("Close")
        if price is not None:
            out.append({"date": date_str, "price": float(price)})
    return out


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------

async def search_market(query: str) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_sync_search, query))


async def get_quote(ticker: str) -> dict | None:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_sync_quote, ticker))


async def get_market_history(ticker: str, range_str: str = "30d") -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_sync_history, ticker, range_str))
