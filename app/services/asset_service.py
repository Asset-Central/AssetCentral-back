from datetime import datetime, timezone

from app.core.supabase import supabase_admin
from app.schemas.account import ConnectionStatus, Platform
from app.schemas.asset import Asset, AssetType, Currency

from .account_service import AccountService
from .connectors.base import BaseConnector, ConnectorError, Holding
from .connectors.mock import MockConnector


def _get_connector(platform: Platform, account_id: str, credentials: dict) -> BaseConnector:
    match platform:
        case Platform.NACION:
            from .connectors.prometeo import PrometeoConnector
            return PrometeoConnector(account_id, credentials)
        # case Platform.IOL:
        #     from .connectors.iol import IOLConnector
        #     return IOLConnector(account_id, credentials)
        # case Platform.COCOS:
        #     from .connectors.cocos import CocosConnector
        #     return CocosConnector(account_id, credentials)
        # case Platform.MERCADOPAGO:
        #     from .connectors.mercadopago import MercadoPagoConnector
        #     return MercadoPagoConnector(account_id, credentials)
        case _:
            creds_with_hint = {**credentials, "_mock_platform": platform.value}
            return MockConnector(account_id, creds_with_hint)


class AssetService:

    @staticmethod
    async def get_assets(user_id: str) -> list[Asset]:
        """
        Para cada cuenta del usuario:
          1. Obtiene las credenciales del Vault.
          2. Llama al conector del broker.
          3. Registra las posiciones en historical_balances y actualiza el catálogo assets.
          4. Retorna el balance más reciente via RPC get_latest_balances.
        """
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

        result = supabase_admin.rpc("get_latest_balances", {"p_user_id": user_id}).execute()
        return [_row_to_asset(row) for row in (result.data or [])]


async def _persist_holdings(account_id: str, holdings: list[Holding]) -> None:
    if not holdings:
        return

    # Upsert en catálogo global de assets; recuperar IDs para historical_balances
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
    upserted = (
        supabase_admin.table("assets")
        .upsert(asset_rows, on_conflict="ticker,platform")
        .select("id, ticker, platform")
        .execute()
    )
    id_map = {(r["ticker"], r["platform"]): r["id"] for r in upserted.data}

    # Insert en historical_balances (serie temporal — nunca se reemplaza)
    balance_rows = [
        {
            "account_id": account_id,
            "asset_id": id_map[(h.ticker, h.platform.value)],
            "quantity": h.quantity,
            "unit_price": h.unit_price,
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


def _row_to_asset(row: dict) -> Asset:
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
    )
