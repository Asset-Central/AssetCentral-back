"""
Agrega activos de todas las cuentas vinculadas del usuario,
sincroniza con los brokers y actualiza los snapshots en DB.
"""

from app.core.security import decrypt_credentials
from app.core.supabase import supabase_admin
from app.schemas.account import AccountStatus, Platform
from app.schemas.asset import Asset

from .connectors.base import BaseConnector, ConnectorError
from .connectors.mock import MockConnector


def _get_connector(platform: Platform, account_id: str, credentials: dict) -> BaseConnector:
    """
    Factory de conectores.
    Retorna el conector real si está implementado, MockConnector si no.
    """
    match platform:
        # case Platform.IOL:
        #     from .connectors.iol import IOLConnector
        #     return IOLConnector(account_id, credentials)
        # case Platform.COCOS:
        #     from .connectors.cocos import CocosConnector
        #     return CocosConnector(account_id, credentials)
        # case Platform.MERCADO_PAGO:
        #     from .connectors.mercadopago import MercadoPagoConnector
        #     return MercadoPagoConnector(account_id, credentials)
        # case Platform.PROMETEO:
        #     from .connectors.prometeo import PrometeoConnector
        #     return PrometeoConnector(account_id, credentials)
        case _:
            creds_with_hint = {**credentials, "_mock_platform": platform.value}
            return MockConnector(account_id, creds_with_hint)


class AssetService:

    @staticmethod
    async def get_assets(user_id: str, dek: bytes) -> list[Asset]:
        """
        Para cada cuenta vinculada del usuario:
          1. Descifra las credenciales con su DEK.
          2. Llama al conector del broker.
          3. Guarda el snapshot en DB (reemplaza el anterior).
          4. Retorna todos los activos consolidados.
        """
        accounts_result = (
            supabase_admin.table("linked_accounts")
            .select("id, platform, credentials_enc, status")
            .eq("user_id", user_id)
            .execute()
        )

        all_assets: list[Asset] = []

        for account in accounts_result.data:
            account_id = account["id"]
            platform = Platform(account["platform"])
            credentials = decrypt_credentials(dek, account["credentials_enc"])
            connector = _get_connector(platform, account_id, credentials)


            try:
                assets = await connector.get_assets()
                await _upsert_snapshot(user_id, account_id, assets)
                await _set_account_status(account_id, AccountStatus.CONNECTED)
                all_assets.extend(assets)
            except ConnectorError as e:
                await _set_account_status(account_id, AccountStatus.ERROR, str(e))

        return all_assets


async def _upsert_snapshot(user_id: str, account_id: str, assets: list[Asset]) -> None:
    """Borra el snapshot anterior de la cuenta y guarda el nuevo."""
    supabase_admin.table("asset_snapshots").delete().eq("account_id", account_id).execute()

    if not assets:
        return

    rows = [
        {
            "user_id": user_id,
            "account_id": account_id,
            "ticker": a.ticker,
            "name": a.name,
            "asset_type": a.type.value,
            "platform": a.platform.value,
            "quantity": a.quantity,
            "price_ars": a.price_ars,
            "price_usd": a.price_usd,
            "total_ars": a.total_ars,
            "total_usd": a.total_usd,
            "daily_change_pct": a.daily_change_percent,
        }
        for a in assets
    ]
    supabase_admin.table("asset_snapshots").insert(rows).execute()


async def _set_account_status(
    account_id: str,
    status: AccountStatus,
    error_message: str | None = None,
) -> None:
    from datetime import datetime, timezone

    payload: dict = {"status": status.value, "error_message": error_message}
    if status == AccountStatus.CONNECTED:
        payload["last_sync_at"] = datetime.now(timezone.utc).isoformat()

    supabase_admin.table("linked_accounts").update(payload).eq("id", account_id).execute()
