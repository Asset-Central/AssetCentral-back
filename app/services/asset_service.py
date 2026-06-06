from datetime import datetime, timedelta, timezone

from app.core.supabase import supabase_admin
from app.schemas.account import ConnectionStatus, Platform
from app.schemas.asset import Asset, AssetType, Currency

from .account_service import AccountService
from .connectors.base import BaseConnector, ConnectorError, Holding
from .connectors.mock import MockConnector


def _range_cutoff_and_agg(range_str: str) -> tuple[str, str]:
    """Returns (cutoff_iso, agg_granularity) where granularity is 'minute'|'hour'|'day'."""
    now = datetime.now(timezone.utc)
    match range_str:
        case "1h":
            return (now - timedelta(hours=1)).isoformat(), "minute"
        case "1d":
            return (now - timedelta(days=1)).isoformat(), "hour"
        case "1w":
            return (now - timedelta(weeks=1)).isoformat(), "day"
        case "1y":
            return (now - timedelta(days=365)).isoformat(), "day"
        case _:  # "30d" default
            return (now - timedelta(days=30)).isoformat(), "day"


def _agg_key(recorded_at: str, granularity: str) -> str:
    """Truncate timestamp to the given granularity for bucketing."""
    match granularity:
        case "minute":
            return recorded_at[:16]   # "YYYY-MM-DDTHH:MM"
        case "hour":
            return recorded_at[:13]   # "YYYY-MM-DDTHH"
        case _:
            return recorded_at[:10]   # "YYYY-MM-DD"


def _get_connector(platform: Platform, account_id: str, credentials: dict) -> BaseConnector:
    match platform:
        case Platform.NACION:
            from .connectors.prometeo import PrometeoConnector
            return PrometeoConnector(account_id, credentials)
        case Platform.BINANCE:
            from .connectors.binance import BinanceConnector
            return BinanceConnector(account_id, credentials)
        case _:
            creds_with_hint = {**credentials, "_mock_platform": platform.value}
            return MockConnector(account_id, creds_with_hint)


class AssetService:

    @staticmethod
    async def get_assets(user_id: str) -> list[Asset]:
        accounts = (
            supabase_admin.table("account")
            .select("id, platform, connection_status")
            .eq("user_id", user_id)
            .execute()
        )

        for account in accounts.data:
            account_id = account["id"]
            platform = Platform(account["platform"])
            try:
                credentials = await AccountService.get_credentials(account_id)
                connector = _get_connector(platform, account_id, credentials)
                holdings = await connector.get_holdings()
                await _persist_holdings(account_id, holdings)
                await _set_account_status(account_id, ConnectionStatus.ACTIVE)
            except ConnectorError as e:
                await _set_account_status(account_id, ConnectionStatus.ERROR, str(e))
            except Exception as e:
                await _set_account_status(account_id, ConnectionStatus.ERROR, str(e))

        latest = supabase_admin.rpc("get_latest_balances", {"p_user_id": user_id}).execute()
        latest_rows = latest.data or []

        if not latest_rows:
            return []

        # Calcular daily_change_pct comparando con el precio de ayer
        account_ids = list({row["account_id"] for row in latest_rows})
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
        prev = (
            supabase_admin.table("historical_balances")
            .select("account_id, unit_price, assets(ticker)")
            .in_("account_id", account_ids)
            .lt("recorded_at", cutoff)
            .order("recorded_at", desc=True)
            .limit(len(latest_rows) * 3)
            .execute()
        )
        prev_price_map: dict[tuple, float] = {}
        for row in prev.data or []:
            ticker = (row.get("assets") or {}).get("ticker")
            if ticker and row.get("unit_price"):
                key = (row["account_id"], ticker)
                if key not in prev_price_map:
                    prev_price_map[key] = float(row["unit_price"])

        return [_row_to_asset(row, prev_price_map) for row in latest_rows]

    @staticmethod
    async def get_asset_history(user_id: str, ticker: str, range: str = "30d") -> list[dict]:
        """Historial de precio para un ticker del usuario en el rango indicado."""
        asset_res = supabase_admin.table("assets").select("id").eq("ticker", ticker).limit(1).execute()
        if not asset_res.data:
            return []
        asset_id = asset_res.data[0]["id"]

        accounts = (
            supabase_admin.table("account")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        account_ids = [a["id"] for a in accounts.data]
        if not account_ids:
            return []

        cutoff, agg = _range_cutoff_and_agg(range)
        rows = (
            supabase_admin.table("historical_balances")
            .select("recorded_at, unit_price, total_valuation")
            .eq("asset_id", asset_id)
            .in_("account_id", account_ids)
            .gte("recorded_at", cutoff)
            .order("recorded_at")
            .execute()
        )

        bucket_map: dict[str, dict] = {}
        for row in rows.data or []:
            key = _agg_key(row["recorded_at"], agg)
            if key not in bucket_map:
                bucket_map[key] = {"prices": [], "total": 0.0}
            if row.get("unit_price"):
                bucket_map[key]["prices"].append(float(row["unit_price"]))
            if row.get("total_valuation"):
                bucket_map[key]["total"] += float(row["total_valuation"])

        return [
            {
                "date": key,
                "unit_price": sum(v["prices"]) / len(v["prices"]) if v["prices"] else 0,
                "total_valuation": v["total"],
            }
            for key, v in sorted(bucket_map.items())
        ]

    @staticmethod
    async def get_value_history(user_id: str, range: str = "30d") -> list[dict]:
        """Valuación total del portafolio por el rango indicado."""
        accounts = (
            supabase_admin.table("account")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        account_ids = [a["id"] for a in accounts.data]
        if not account_ids:
            return []

        cutoff, agg = _range_cutoff_and_agg(range)
        rows = (
            supabase_admin.table("historical_balances")
            .select("recorded_at, total_valuation, assets(currency)")
            .in_("account_id", account_ids)
            .gte("recorded_at", cutoff)
            .order("recorded_at")
            .execute()
        )

        bucket_map: dict[str, float] = {}
        for row in rows.data or []:
            key = _agg_key(row["recorded_at"], agg)
            tv = float(row["total_valuation"]) if row.get("total_valuation") else 0.0
            bucket_map[key] = bucket_map.get(key, 0.0) + tv

        return [{"date": key, "total": total} for key, total in sorted(bucket_map.items())]

    @staticmethod
    async def get_performance(user_id: str, range: str = "30d") -> list[dict]:
        """Descompone la variación de cartera en: market_pnl (precio) y capital_flow (cantidad)."""
        accounts = (
            supabase_admin.table("account")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        account_ids = [a["id"] for a in accounts.data]
        if not account_ids:
            return []

        cutoff, agg = _range_cutoff_and_agg(range)
        rows = (
            supabase_admin.table("historical_balances")
            .select("recorded_at, account_id, asset_id, quantity, unit_price, total_valuation")
            .in_("account_id", account_ids)
            .gte("recorded_at", cutoff)
            .order("recorded_at")
            .execute()
        )

        # For each bucket keep the LATEST record per (account_id, asset_id)
        bucket_latest: dict[str, dict[tuple, dict]] = {}
        for row in rows.data or []:
            key = _agg_key(row["recorded_at"], agg)
            pair = (row["account_id"], row["asset_id"])
            if key not in bucket_latest:
                bucket_latest[key] = {}
            bucket_latest[key][pair] = {
                "qty": float(row["quantity"]) if row.get("quantity") else 0.0,
                "price": float(row["unit_price"]) if row.get("unit_price") else 0.0,
                "total": float(row["total_valuation"]) if row.get("total_valuation") else 0.0,
            }

        result = []
        prev_data: dict[tuple, dict] | None = None

        for bucket_key, curr_data in sorted(bucket_latest.items()):
            total = sum(v["total"] for v in curr_data.values())
            market_pnl = 0.0
            capital_flow = 0.0

            if prev_data is not None:
                for pair in set(curr_data) | set(prev_data):
                    c = curr_data.get(pair)
                    p = prev_data.get(pair)
                    if c and p:
                        market_pnl += (c["price"] - p["price"]) * p["qty"]
                        capital_flow += (c["qty"] - p["qty"]) * c["price"]
                    elif c:
                        capital_flow += c["total"]
                    elif p:
                        capital_flow -= p["total"]

            result.append({
                "date": bucket_key,
                "total": total,
                "market_pnl": round(market_pnl, 2),
                "capital_flow": round(capital_flow, 2),
            })
            prev_data = curr_data

        return result


async def _persist_holdings(account_id: str, holdings: list[Holding]) -> None:
    if not holdings:
        return

    asset_rows = [
        {
            "ticker": h.ticker,
            "external_name": h.external_name,
            "asset_type": h.asset_type.value,
            "currency": h.currency.value,
            "platform": h.platform.value,
        }
        for h in holdings
    ]
    # Upsert y recuperar IDs en una sola llamada
    upserted = (
        supabase_admin.table("assets")
        .upsert(asset_rows, on_conflict="ticker,platform")
        .select("id, ticker, platform")
        .execute()
    )
    id_map = {(r["ticker"], r["platform"]): r["id"] for r in upserted.data}

    now = datetime.now(timezone.utc).isoformat()
    balance_rows = [
        {
            "account_id": account_id,
            "asset_id": id_map[(h.ticker, h.platform.value)],
            "quantity": h.quantity,
            "unit_price": h.unit_price,
            "total_valuation": h.total_valuation,
            "recorded_at": now,
        }
        for h in holdings
        if (h.ticker, h.platform.value) in id_map
    ]
    if balance_rows:
        supabase_admin.table("historical_balances").insert(balance_rows).execute()


async def _set_account_status(
    account_id: str,
    conn_status: ConnectionStatus,
    error_message: str | None = None,
) -> None:
    payload: dict = {
        "connection_status": conn_status.value,
        "error_message": error_message,
    }
    if conn_status == ConnectionStatus.ACTIVE:
        payload["last_sync"] = datetime.now(timezone.utc).isoformat()
    supabase_admin.table("account").update(payload).eq("id", account_id).execute()


def _row_to_asset(row: dict, prev_price_map: dict | None = None) -> Asset:
    daily_change_pct = None
    if prev_price_map is not None:
        key = (row["account_id"], row["asset_ticker"])
        prev = prev_price_map.get(key)
        curr = float(row["unit_price"]) if row.get("unit_price") else None
        if prev and curr and prev != 0:
            daily_change_pct = (curr - prev) / prev * 100

    return Asset(
        ticker=row["asset_ticker"],
        name=row.get("external_name"),
        asset_type=AssetType(row["asset_type"]) if row.get("asset_type") else None,
        platform=Platform(row["platform"]) if row.get("platform") else None,
        currency=Currency(row["currency"]) if row.get("currency") else None,
        account_id=str(row["account_id"]),
        quantity=float(row["quantity"]),
        unit_price=float(row["unit_price"]) if row.get("unit_price") is not None else None,
        total_valuation=float(row["total_valuation"]) if row.get("total_valuation") is not None else None,
        recorded_at=row.get("recorded_at"),
        daily_change_pct=daily_change_pct,
    )
