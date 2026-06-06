"""
Seed script — pobla AssetCentral con datos sintéticos realistas.
Ejecutar desde back/:
    python seed.py

Requiere .env con SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY.
Usa service_role para bypassear RLS.

Schema real (verificado contra Supabase):
  assets:              ticker (PK), id (UUID), platform, external_name, asset_type, currency
  historical_balances: id, account_id, asset_id (UUID → assets.id), quantity, unit_price, total_valuation, recorded_at
  portfolio_assets:    portfolio_id, asset_id (UUID → assets.id), target_share, assigned_at
  users:               id, full_name, nombre, apellido, dni, created_at, updated_at
"""

import os
import random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY   = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

sb: Client = create_client(SUPABASE_URL, SERVICE_KEY)


def now_iso(delta_days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).isoformat()


# ============================================================================
# 1. CATÁLOGO GLOBAL DE ACTIVOS
# ============================================================================
ASSETS_DEF = [
    # ── CEDEARs ─────────────────────────────────────────────────────────────
    {"ticker": "GGAL",   "platform": "cocos", "external_name": "Grupo Fin. Galicia",  "asset_type": "cedear", "currency": "ARS"},
    {"ticker": "YPFD",   "platform": "cocos", "external_name": "YPF S.A.",             "asset_type": "cedear", "currency": "ARS"},
    {"ticker": "MELI",   "platform": "cocos", "external_name": "MercadoLibre Inc.",    "asset_type": "cedear", "currency": "ARS"},
    {"ticker": "BMA",    "platform": "cocos", "external_name": "Banco Macro",          "asset_type": "cedear", "currency": "ARS"},
    {"ticker": "BBAR",   "platform": "cocos", "external_name": "BBVA Argentina",       "asset_type": "cedear", "currency": "ARS"},
    {"ticker": "AAPL",   "platform": "cocos", "external_name": "Apple Inc.",           "asset_type": "cedear", "currency": "USD"},
    {"ticker": "MSFT",   "platform": "cocos", "external_name": "Microsoft Corp.",      "asset_type": "cedear", "currency": "USD"},
    {"ticker": "AMZN",   "platform": "cocos", "external_name": "Amazon.com Inc.",      "asset_type": "cedear", "currency": "USD"},
    {"ticker": "GOOGL",  "platform": "cocos", "external_name": "Alphabet Inc.",        "asset_type": "cedear", "currency": "USD"},
    {"ticker": "NVDA",   "platform": "cocos", "external_name": "NVIDIA Corp.",         "asset_type": "cedear", "currency": "USD"},
    # ── Acciones locales ────────────────────────────────────────────────────
    {"ticker": "TXAR",   "platform": "iol",   "external_name": "Ternium Argentina",    "asset_type": "stock",  "currency": "ARS"},
    {"ticker": "COME",   "platform": "iol",   "external_name": "COME S.A.",            "asset_type": "stock",  "currency": "ARS"},
    {"ticker": "LOMA",   "platform": "iol",   "external_name": "Loma Negra",           "asset_type": "stock",  "currency": "ARS"},
    {"ticker": "PAMP",   "platform": "iol",   "external_name": "Pampa Energía",        "asset_type": "stock",  "currency": "ARS"},
    # ── Bonos ───────────────────────────────────────────────────────────────
    {"ticker": "AL30",   "platform": "iol",   "external_name": "Bono AL30 (USD)",      "asset_type": "bono",   "currency": "USD"},
    {"ticker": "GD30",   "platform": "iol",   "external_name": "Bono GD30 (USD)",      "asset_type": "bono",   "currency": "USD"},
    {"ticker": "AL35",   "platform": "iol",   "external_name": "Bono AL35 (USD)",      "asset_type": "bono",   "currency": "USD"},
    {"ticker": "S30E5",  "platform": "iol",   "external_name": "Lecap may-2025",       "asset_type": "bono",   "currency": "ARS"},
    {"ticker": "T2X5",   "platform": "iol",   "external_name": "CER nov-2025",         "asset_type": "bono",   "currency": "ARS"},
    # ── FCIs ────────────────────────────────────────────────────────────────
    {"ticker": "FCI-PREMIER", "platform": "iol", "external_name": "FCI Premier Renta Fija",    "asset_type": "fci", "currency": "ARS"},
    {"ticker": "FCI-BALANZ",  "platform": "iol", "external_name": "Balanz Capital Renta Fija", "asset_type": "fci", "currency": "ARS"},
    {"ticker": "FCI-GALICIA", "platform": "iol", "external_name": "Galicia Ahorro",             "asset_type": "fci", "currency": "ARS"},
    # ── Cash ────────────────────────────────────────────────────────────────
    {"ticker": "ARS-CASH", "platform": "mercadopago", "external_name": "Pesos ARS",        "asset_type": "cash", "currency": "ARS"},
    {"ticker": "USDT",     "platform": "mercadopago", "external_name": "Dólar MEP / USDT", "asset_type": "cash", "currency": "USD"},
    # ── Crypto ──────────────────────────────────────────────────────────────
    {"ticker": "BTC", "platform": "nacion", "external_name": "Bitcoin",  "asset_type": "crypto", "currency": "USD"},
    {"ticker": "ETH", "platform": "nacion", "external_name": "Ethereum", "asset_type": "crypto", "currency": "USD"},
    {"ticker": "SOL", "platform": "nacion", "external_name": "Solana",   "asset_type": "crypto", "currency": "USD"},
]

# Precios base en ARS (cotización USD ~1250 ARS)
ARS_PRICES = {
    "GGAL": 4350.0,     "YPFD": 18200.0,  "MELI": 2_625_000.0, "BMA": 8_125_000.0,
    "BBAR": 2625.0,     "TXAR": 710.0,    "COME": 320.0,        "LOMA": 2900.0,   "PAMP": 3800.0,
    "AAPL": 109_375.0,  "MSFT": 537_500.0, "AMZN": 243_750.0,  "GOOGL": 246_250.0, "NVDA": 162_500.0,
    "AL30": 79_375.0,   "GD30": 76_250.0,  "AL35": 72_500.0,
    "S30E5": 1.08,      "T2X5": 1.12,
    "FCI-PREMIER": 108.5, "FCI-BALANZ": 112.0, "FCI-GALICIA": 98.0,
    "ARS-CASH": 1.0,    "USDT": 1250.0,
    "BTC": 120_625_000.0, "ETH": 4_750_000.0, "SOL": 218_750.0,
}

# ============================================================================
# 2. USUARIOS SINTÉTICOS
# ============================================================================
USERS_DATA = [
    {
        "email": "martin.garcia@hackaton.dev",
        "password": "Hack2025!",
        "full_name": "Martín García",
        "nombre": "Martín",
        "apellido": "García",
        "dni": "30124567",
        "accounts": [
            {"platform": "cocos",       "label": "Cocos Personal",  "status": "active"},
            {"platform": "iol",         "label": "IOL Inversiones",  "status": "active"},
            {"platform": "mercadopago", "label": "Mercado Pago",     "status": "active"},
        ],
        "holdings": {
            "cocos":       [("GGAL",200,4350.0), ("YPFD",50,18200.0), ("AAPL",8,87.5), ("NVDA",3,130.0), ("MELI",2,2100.0)],
            "iol":         [("AL30",150,63.5), ("GD30",80,61.0), ("FCI-PREMIER",5000,108.5), ("TXAR",500,710.0)],
            "mercadopago": [("USDT",800,1.0), ("ARS-CASH",250000,1.0)],
        },
        "portfolios": [
            {"name": "Cartera Dolarizada", "description": "Hard-dollar y CEDEARs USD",
             "tickers": ["AAPL", "NVDA", "MELI", "AL30", "GD30", "USDT"]},
            {"name": "Renta Fija ARS",     "description": "FCIs y bonos en pesos",
             "tickers": ["FCI-PREMIER", "S30E5"]},
        ],
    },
    {
        "email": "laura.fernandez@hackaton.dev",
        "password": "Hack2025!",
        "full_name": "Laura Fernández",
        "nombre": "Laura",
        "apellido": "Fernández",
        "dni": "31987654",
        "accounts": [
            {"platform": "cocos",  "label": "Cocos Plus",   "status": "active"},
            {"platform": "nacion", "label": "Banco Nación", "status": "active"},
        ],
        "holdings": {
            "cocos":  [("BBAR",300,2100.0), ("BMA",150,6500.0), ("PAMP",400,3800.0), ("MSFT",5,430.0), ("GOOGL",4,197.0)],
            "nacion": [("BTC",0.025,96500.0), ("ETH",0.5,3800.0), ("SOL",10,175.0)],
        },
        "portfolios": [
            {"name": "Tech & Crypto", "description": "Tecnología global y activos digitales",
             "tickers": ["MSFT", "GOOGL", "BTC", "ETH", "SOL"]},
            {"name": "Bancos ARG",   "description": "Sector financiero local",
             "tickers": ["BBAR", "BMA"]},
        ],
    },
    {
        "email": "roberto.perez@hackaton.dev",
        "password": "Hack2025!",
        "full_name": "Roberto Pérez",
        "nombre": "Roberto",
        "apellido": "Pérez",
        "dni": "28456789",
        "accounts": [
            {"platform": "iol",         "label": "IOL Principal",  "status": "active"},
            {"platform": "mercadopago", "label": "MP Ahorro",      "status": "active"},
            {"platform": "cocos",       "label": "Cocos Pro",      "status": "requires_reauthentication"},
        ],
        "holdings": {
            "iol":         [("AL35",200,58.0), ("T2X5",10000,1.12), ("S30E5",8000,1.08),
                            ("FCI-BALANZ",3000,112.0), ("FCI-GALICIA",2500,98.0),
                            ("LOMA",600,2900.0), ("COME",1500,320.0)],
            "mercadopago": [("USDT",1200,1.0), ("ARS-CASH",500000,1.0)],
        },
        "portfolios": [
            {"name": "Conservador ARS", "description": "FCIs y letras de bajo riesgo",
             "tickers": ["FCI-BALANZ", "FCI-GALICIA", "T2X5", "S30E5"]},
            {"name": "Bonos Hard-Dollar", "description": "Bonos soberanos en USD",
             "tickers": ["AL35"]},
        ],
    },
]


def seed():
    print("=== AssetCentral Seed ===\n")

    # ── 1. Catálogo de activos ────────────────────────────────────────────────
    print("→ Insertando catálogo de activos...")
    res = sb.table("assets").upsert(ASSETS_DEF, on_conflict="ticker,platform").execute()
    inserted_assets = res.data

    # Construir mapa ticker → asset_id (UUID)
    all_assets = sb.table("assets").select("id,ticker").execute().data
    ticker_to_id: dict[str, str] = {a["ticker"]: a["id"] for a in all_assets}
    print(f"  {len(ticker_to_id)} activos en catálogo")

    # ── 2. Usuarios ──────────────────────────────────────────────────────────
    created_users = []
    for user_data in USERS_DATA:
        print(f"\n→ Usuario: {user_data['email']}")

        # Crear en auth
        try:
            resp = sb.auth.admin.create_user({
                "email": user_data["email"],
                "password": user_data["password"],
                "email_confirm": True,
                "user_metadata": {
                    "full_name": user_data["full_name"],
                    "nombre": user_data["nombre"],
                    "apellido": user_data["apellido"],
                    "dni": user_data["dni"],
                },
            })
            user_id = resp.user.id
            print(f"  Creado → {user_id}")
        except Exception as e:
            msg = str(e)
            if "already" in msg.lower() or "duplicate" in msg.lower():
                all_users = sb.auth.admin.list_users()
                existing = next((u for u in all_users if u.email == user_data["email"]), None)
                if existing:
                    user_id = existing.id
                    print(f"  Ya existe → {user_id}")
                else:
                    print(f"  ERROR: {e}")
                    continue
            else:
                print(f"  ERROR: {e}")
                continue

        # Perfil público
        sb.table("users").upsert({
            "id": user_id,
            "full_name": user_data["full_name"],
            "nombre": user_data["nombre"],
            "apellido": user_data["apellido"],
            "dni": user_data["dni"],
        }).execute()
        print("  Perfil OK")

        # ── 3. Cuentas ──────────────────────────────────────────────────────
        account_map: dict[str, str] = {}  # platform → account_id
        for acc in user_data["accounts"]:
            ex = sb.table("account").select("id").eq("user_id", user_id).eq("platform", acc["platform"]).execute()
            if ex.data:
                acc_id = ex.data[0]["id"]
            else:
                r = sb.table("account").insert({
                    "user_id": user_id,
                    "platform": acc["platform"],
                    "label": acc["label"],
                    "connection_status": acc["status"],
                    "last_sync": now_iso(),
                }).execute()
                acc_id = r.data[0]["id"]
            account_map[acc["platform"]] = acc_id
            print(f"  Cuenta {acc['platform']} → {acc_id}")

        # ── 4. Balances históricos (31 días) ────────────────────────────────
        for platform, holdings in user_data["holdings"].items():
            acc_id = account_map.get(platform)
            if not acc_id:
                continue
            records = []
            for ticker, qty, base_price_usd in holdings:
                asset_id = ticker_to_id.get(ticker)
                if not asset_id:
                    print(f"    WARN: ticker {ticker} no encontrado en catálogo")
                    continue
                price_ars = ARS_PRICES.get(ticker, base_price_usd)
                for day_offset in range(30, -1, -1):
                    noise = 1 + random.uniform(-0.015, 0.015)
                    p = round(price_ars * noise, 4) if day_offset > 0 else price_ars
                    records.append({
                        "account_id": acc_id,
                        "asset_id": asset_id,
                        "quantity": qty,
                        "unit_price": p,
                        "total_valuation": round(qty * p, 2),
                        "recorded_at": now_iso(-day_offset),
                    })
            if records:
                # Insert en lotes de 200 para no sobrepasar límites
                for i in range(0, len(records), 200):
                    sb.table("historical_balances").insert(records[i:i+200]).execute()
                print(f"  Balances {platform}: {len(holdings)} activos × 31 días = {len(records)} filas")

        # ── 5. Portfolios ────────────────────────────────────────────────────
        for port_data in user_data["portfolios"]:
            ex = sb.table("portfolios").select("id").eq("user_id", user_id).eq("name", port_data["name"]).execute()
            if ex.data:
                port_id = ex.data[0]["id"]
                print(f"  Portfolio '{port_data['name']}' ya existe")
            else:
                r = sb.table("portfolios").insert({
                    "user_id": user_id,
                    "name": port_data["name"],
                    "description": port_data["description"],
                }).execute()
                port_id = r.data[0]["id"]
                print(f"  Portfolio '{port_data['name']}' creado → {port_id}")

            for ticker in port_data["tickers"]:
                asset_id = ticker_to_id.get(ticker)
                if not asset_id:
                    print(f"    WARN: ticker {ticker} no en catálogo, skipping")
                    continue
                try:
                    sb.table("portfolio_assets").upsert({
                        "portfolio_id": port_id,
                        "asset_id": asset_id,
                        "target_share": None,
                    }).execute()
                except Exception as e:
                    print(f"    WARN portfolio_asset {ticker}: {e}")
            print(f"    {len(port_data['tickers'])} activos asignados al portfolio")

        created_users.append({"email": user_data["email"], "id": user_id})

    print("\n=== Seed completado ===")
    print("\nUsuarios:")
    for u in created_users:
        print(f"  {u['email']}  →  {u['id']}")
    print("\nContraseña: Hack2025!")


if __name__ == "__main__":
    seed()
