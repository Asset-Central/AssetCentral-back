"""
Actualiza historical_balances con precios reales de Yahoo Finance.

Fuentes:
  - Acciones BYMA (GGAL, YPFD, etc.)  → {ticker}.BA  → precio en ARS
  - US stocks / CEDEARs (AAPL, NVDA…) → {ticker}     → precio en USD
  - Crypto (BTC, ETH, SOL)             → {ticker}-USD → precio en USD
  - Bonos ARG / FCIs / Cash            → sin datos en YF → se mantienen sintéticos

Ejecutar desde back/:
    python prices_updater.py
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client
import yfinance as yf

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY   = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
sb: Client    = create_client(SUPABASE_URL, SERVICE_KEY)

# Mapeo: ticker interno → (ticker Yahoo Finance, moneda esperada)
YF_MAP: dict[str, tuple[str, str]] = {
    # Acciones BYMA → ARS
    "GGAL":  ("GGAL.BA",  "ARS"),
    "YPFD":  ("YPFD.BA",  "ARS"),
    "MELI":  ("MELI.BA",  "ARS"),
    "BMA":   ("BMA.BA",   "ARS"),
    "BBAR":  ("BBAR.BA",  "ARS"),
    "TXAR":  ("TXAR.BA",  "ARS"),
    "COME":  ("COME.BA",  "ARS"),
    "LOMA":  ("LOMA.BA",  "ARS"),
    "PAMP":  ("PAMP.BA",  "ARS"),
    # US stocks / CEDEARs → USD
    "AAPL":  ("AAPL",     "USD"),
    "MSFT":  ("MSFT",     "USD"),
    "AMZN":  ("AMZN",     "USD"),
    "GOOGL": ("GOOGL",    "USD"),
    "NVDA":  ("NVDA",     "USD"),
    # Crypto → USD
    "BTC":   ("BTC-USD",  "USD"),
    "ETH":   ("ETH-USD",  "USD"),
    "SOL":   ("SOL-USD",  "USD"),
    # Sin datos en YF — se mantienen sintéticos:
    # AL30, GD30, AL35, S30E5, T2X5, FCI-*, USDT, ARS-CASH
}


def fetch_prices(yf_ticker: str, days: int = 35) -> dict[str, float]:
    """Devuelve {fecha_iso: precio_cierre} para los últimos N días."""
    hist = yf.Ticker(yf_ticker).history(period=f"{days}d")
    if hist.empty:
        return {}
    result = {}
    for ts, row in hist.iterrows():
        day = ts.date().isoformat()
        result[day] = float(row["Close"])
    return result


def update():
    print("=== Prices Updater (Yahoo Finance) ===\n")

    # 1. Cargar catálogo de activos
    assets_res = sb.table("assets").select("id, ticker, currency").execute()
    ticker_info: dict[str, dict] = {a["ticker"]: a for a in assets_res.data}

    # 2. Para cada ticker con cobertura real, actualizar todos los historical_balances
    for our_ticker, (yf_ticker, expected_currency) in YF_MAP.items():
        asset = ticker_info.get(our_ticker)
        if not asset:
            print(f"  SKIP {our_ticker} — no está en catálogo")
            continue

        asset_id = asset["id"]

        print(f"→ {our_ticker:10} ({yf_ticker}) ...", end=" ", flush=True)
        prices = fetch_prices(yf_ticker)
        if not prices:
            print("sin datos")
            continue
        print(f"{len(prices)} días, último precio: {list(prices.values())[-1]:.2f} {expected_currency}")

        # Obtener los balances existentes para este asset (todas las cuentas, todos los usuarios)
        existing = (
            sb.table("historical_balances")
            .select("id, account_id, quantity, recorded_at")
            .eq("asset_id", asset_id)
            .execute()
        )
        if not existing.data:
            print(f"   Sin balances existentes para {our_ticker}")
            continue

        # Agrupar por (account_id, día) para saber la cantidad en cada día
        # Tomar la cantidad del snapshot más reciente por cuenta
        account_qtys: dict[str, float] = {}
        for row in sorted(existing.data, key=lambda r: r["recorded_at"]):
            account_qtys[row["account_id"]] = float(row["quantity"])

        # Borrar historical_balances actuales para este asset
        ids_to_delete = [r["id"] for r in existing.data]
        for i in range(0, len(ids_to_delete), 200):
            sb.table("historical_balances").delete().in_("id", ids_to_delete[i:i+200]).execute()

        # Insertar nuevos con precios reales
        new_rows = []
        sorted_days = sorted(prices.keys())
        for account_id, qty in account_qtys.items():
            for day in sorted_days:
                price = prices[day]
                new_rows.append({
                    "account_id": account_id,
                    "asset_id":   asset_id,
                    "quantity":   qty,
                    "unit_price": round(price, 6),
                    "total_valuation": round(qty * price, 2),
                    "recorded_at": f"{day}T21:00:00+00:00",
                })

        for i in range(0, len(new_rows), 200):
            sb.table("historical_balances").insert(new_rows[i:i+200]).execute()

        print(f"   {len(new_rows)} filas insertadas")

    print("\n=== Actualización completada ===")
    print("Tickers SIN datos reales (conservan precios sintéticos):")
    sin_datos = [t for t in ticker_info if t not in YF_MAP]
    print(f"  {', '.join(sorted(sin_datos))}")


if __name__ == "__main__":
    update()
