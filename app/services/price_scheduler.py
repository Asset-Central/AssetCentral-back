"""
Scheduler de precios — actualiza historical_balances con datos reales de Yahoo Finance
cada INTERVAL_SECONDS segundos. Se lanza como tarea asyncio en el lifespan de FastAPI.

yfinance es blocking I/O → se ejecuta en un ThreadPoolExecutor para no bloquear el loop.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import yfinance as yf

from app.core.supabase import supabase_admin

log = logging.getLogger("price_scheduler")

INTERVAL_SECONDS = 60

# Mapeo ticker interno → (ticker Yahoo Finance, moneda)
YF_MAP: dict[str, tuple[str, str]] = {
    "GGAL":  ("GGAL.BA",  "ARS"),
    "YPFD":  ("YPFD.BA",  "ARS"),
    "MELI":  ("MELI.BA",  "ARS"),
    "BMA":   ("BMA.BA",   "ARS"),
    "BBAR":  ("BBAR.BA",  "ARS"),
    "TXAR":  ("TXAR.BA",  "ARS"),
    "COME":  ("COME.BA",  "ARS"),
    "LOMA":  ("LOMA.BA",  "ARS"),
    "PAMP":  ("PAMP.BA",  "ARS"),
    "AAPL":  ("AAPL",     "USD"),
    "MSFT":  ("MSFT",     "USD"),
    "AMZN":  ("AMZN",     "USD"),
    "GOOGL": ("GOOGL",    "USD"),
    "NVDA":  ("NVDA",     "USD"),
    "BTC":   ("BTC-USD",  "USD"),
    "ETH":   ("ETH-USD",  "USD"),
    "SOL":   ("SOL-USD",  "USD"),
}

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="yf")


def _fetch_latest_prices() -> dict[str, float]:
    """Descarga el precio de cierre más reciente para todos los tickers. Blocking."""
    yf_tickers = [yf_sym for yf_sym, _ in YF_MAP.values()]
    data = yf.download(
        tickers=yf_tickers,
        period="2d",
        interval="1d",
        progress=False,
        auto_adjust=True,
    )
    if data.empty:
        return {}

    prices: dict[str, float] = {}
    # data["Close"] puede ser Series (1 ticker) o DataFrame (varios)
    close = data["Close"] if "Close" in data.columns else data
    for our_ticker, (yf_sym, _) in YF_MAP.items():
        try:
            col = close[yf_sym] if hasattr(close, "columns") and yf_sym in close.columns else close
            val = float(col.dropna().iloc[-1])
            prices[our_ticker] = val
        except Exception:
            pass
    return prices


def _run_update() -> int:
    """Actualiza los precios en la DB. Blocking. Devuelve cantidad de tickers actualizados."""
    prices = _fetch_latest_prices()
    if not prices:
        return 0

    assets_res = supabase_admin.table("assets").select("id, ticker").execute()
    ticker_to_id = {a["ticker"]: a["id"] for a in assets_res.data}

    updated = 0
    now = datetime.now(timezone.utc).isoformat()

    for ticker, price in prices.items():
        asset_id = ticker_to_id.get(ticker)
        if not asset_id:
            continue

        # Obtener cuentas + cantidades actuales
        balances = (
            supabase_admin.table("historical_balances")
            .select("account_id, quantity")
            .eq("asset_id", asset_id)
            .order("recorded_at", desc=True)
            .limit(50)
            .execute()
        )
        if not balances.data:
            continue

        # Última cantidad conocida por cuenta
        account_qty: dict[str, float] = {}
        for row in balances.data:
            acc = row["account_id"]
            if acc not in account_qty:
                account_qty[acc] = float(row["quantity"])

        # Insertar snapshot con precio actualizado
        new_rows = [
            {
                "account_id": acc,
                "asset_id": asset_id,
                "quantity": qty,
                "unit_price": round(price, 6),
                "total_valuation": round(qty * price, 2),
                "recorded_at": now,
            }
            for acc, qty in account_qty.items()
        ]
        if new_rows:
            supabase_admin.table("historical_balances").insert(new_rows).execute()
            updated += 1

    return updated


async def _scheduler_loop():
    loop = asyncio.get_running_loop()
    log.info("Price scheduler iniciado (intervalo: %ds)", INTERVAL_SECONDS)
    while True:
        try:
            count = await loop.run_in_executor(_executor, _run_update)
            log.info("Precios actualizados: %d tickers — %s", count,
                     datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Error actualizando precios: %s", e)
        await asyncio.sleep(INTERVAL_SECONDS)


_task: asyncio.Task | None = None


def start():
    global _task
    _task = asyncio.create_task(_scheduler_loop())
    log.info("Price scheduler task creada")


def stop():
    global _task
    if _task and not _task.done():
        _task.cancel()
        log.info("Price scheduler detenido")
