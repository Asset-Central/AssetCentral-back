import json
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin
from app.schemas.account import (
    Account,
    ConnectionStatus,
    CredentialField,
    LinkAccountRequest,
    Platform,
    PlatformConfig,
)
from app.services.connectors.base import ConnectorError

PLATFORM_CONFIGS: list[PlatformConfig] = [
    PlatformConfig(
        platform=Platform.COCOS,
        display_name="Cocos Capital",
        logo_url="/logos/cocos.png",
        fields=[
            CredentialField(name="email", label="Email", type="email", placeholder="tu@email.com"),
            CredentialField(name="password", label="Contraseña", type="password"),
        ],
    ),
    PlatformConfig(
        platform=Platform.IOL,
        display_name="InvertirOnline",
        logo_url="/logos/iol.png",
        fields=[
            CredentialField(name="username", label="Usuario", type="text"),
            CredentialField(name="password", label="Contraseña", type="password"),
        ],
    ),
    PlatformConfig(
        platform=Platform.MERCADOPAGO,
        display_name="Mercado Pago",
        logo_url="/logos/mercadopago.png",
        fields=[
            CredentialField(name="access_token", label="Access Token", type="password",
                            placeholder="APP_USR-..."),
        ],
    ),
    PlatformConfig(
        platform=Platform.NACION,
        display_name="Banco Nación",
        logo_url="/logos/nacion.png",
        fields=[
            CredentialField(name="username", label="Usuario", type="text"),
            CredentialField(name="password", label="Contraseña", type="password"),
        ],
    ),
    PlatformConfig(
        platform=Platform.BINANCE,
        display_name="Binance",
        logo_url="/logos/binance.png",
        fields=[
            CredentialField(name="api_key", label="API Key", type="text",
                            placeholder="Generala en Binance → Gestión de API"),
            CredentialField(name="api_secret", label="Secret Key", type="password"),
        ],
    ),
]


class AccountService:

    @staticmethod
    def get_platform_configs() -> list[PlatformConfig]:
        return PLATFORM_CONFIGS

    @staticmethod
    async def list_accounts(user_id: str) -> list[Account]:
        result = (
            supabase_admin.table("account")
            .select("id, platform, label, connection_status, last_sync, error_message")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return [_row_to_account(row) for row in result.data]

    @staticmethod
    async def link_account(user_id: str, data: LinkAccountRequest) -> Account:
        if data.platform == Platform.NACION:
            return await AccountService._link_prometeo(user_id, data)
        if data.platform == Platform.BINANCE:
            return await AccountService._link_binance(user_id, data)
        if data.platform == Platform.IOL:
            return await AccountService._link_iol(user_id, data)
        return await AccountService._link_generic(user_id, data)

    @staticmethod
    async def _link_generic(user_id: str, data: LinkAccountRequest) -> Account:
        """Flujo estándar: guarda credenciales en Vault e inserta el registro."""
        _cleanup_existing_account(user_id, data.platform)
        label = _build_label(data.platform, data.credentials)
        secret_name = f"account_creds_{user_id}_{data.platform.value}"

        vault_result = supabase_admin.rpc(
            "upsert_vault_secret",
            {"p_secret": json.dumps(data.credentials), "p_name": secret_name},
        ).execute()
        secret_id = vault_result.data

        result = (
            supabase_admin.table("account")
            .insert({
                "user_id": user_id,
                "platform": data.platform.value,
                "label": label,
                "connection_status": ConnectionStatus.ACTIVE.value,
                "secret_id": str(secret_id),
            })
            .execute()
        )
        return _row_to_account(result.data[0])

    @staticmethod
    async def _link_prometeo(user_id: str, data: LinkAccountRequest) -> Account:
        """
        Flujo Prometeo:
          1. Valida credenciales y extrae balance inicial llamando a la API.
          2. Guarda credenciales cifradas en Vault.
          3. Inserta el registro de cuenta con last_sync ya poblado.
          4. Persiste las posiciones iniciales en historical_balances.
        """
        from app.services.connectors.prometeo import PrometeoConnector

        # Importación tardía para evitar ciclo con asset_service
        from app.services.asset_service import _persist_holdings

        _cleanup_existing_account(user_id, data.platform)
        connector = PrometeoConnector(account_id="", credentials=data.credentials)

        try:
            holdings = await connector.get_holdings()
        except ConnectorError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"No se pudo conectar con Prometeo: {exc}",
            ) from exc

        # Credenciales válidas: persistir en Vault
        secret_name = f"account_creds_{user_id}_{data.platform.value}"
        vault_result = supabase_admin.rpc(
            "upsert_vault_secret",
            {"p_secret": json.dumps(data.credentials), "p_name": secret_name},
        ).execute()
        secret_id = vault_result.data

        # Buscar saldo ARS para el label
        ars_holding = next(
            (h for h in holdings if h.currency.value == "ARS"), None
        )
        label = (
            f"Banco Nación ARS ${ars_holding.total_valuation:,.2f}"
            if ars_holding
            else f"Banco Nación ({data.credentials.get('provider', 'test')})"
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        result = (
            supabase_admin.table("account")
            .insert({
                "user_id": user_id,
                "platform": data.platform.value,
                "label": label,
                "connection_status": ConnectionStatus.ACTIVE.value,
                "secret_id": str(secret_id),
                "last_sync": now_iso,
            })
            .execute()
        )
        account_row = result.data[0]
        account_id = account_row["id"]

        try:
            await _persist_holdings(account_id, holdings)
        except Exception:
            # La persistencia de balances puede fallar si el schema de historical_balances
            # no coincide con lo esperado — la cuenta queda activa igual
            pass

        return _row_to_account(account_row)

    @staticmethod
    async def _link_binance(user_id: str, data: LinkAccountRequest) -> Account:
        """
        Flujo Binance:
          1. Valida credenciales y trae balances iniciales.
          2. Guarda api_key + api_secret en Vault.
          3. Inserta registro con last_sync y persiste holdings.
        """
        from app.services.connectors.binance import BinanceConnector
        from app.services.asset_service import _persist_holdings

        _cleanup_existing_account(user_id, data.platform)
        connector = BinanceConnector(account_id="", credentials=data.credentials)

        try:
            holdings = await connector.get_holdings()
        except ConnectorError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"No se pudo conectar con Binance: {exc}",
            ) from exc

        secret_name = f"account_creds_{user_id}_{data.platform.value}"
        vault_result = supabase_admin.rpc(
            "upsert_vault_secret",
            {"p_secret": json.dumps(data.credentials), "p_name": secret_name},
        ).execute()
        secret_id = vault_result.data

        total_usd = sum(h.total_valuation for h in holdings)
        label = f"Binance — U$ {total_usd:,.2f}" if holdings else "Binance"

        now_iso = datetime.now(timezone.utc).isoformat()
        result = (
            supabase_admin.table("account")
            .insert({
                "user_id": user_id,
                "platform": data.platform.value,
                "label": label,
                "connection_status": ConnectionStatus.ACTIVE.value,
                "secret_id": str(secret_id),
                "last_sync": now_iso,
            })
            .execute()
        )
        account_row = result.data[0]
        account_id = account_row["id"]

        try:
            await _persist_holdings(account_id, holdings)
        except Exception:
            pass

        return _row_to_account(account_row)

    @staticmethod
    async def _link_iol(user_id: str, data: LinkAccountRequest) -> Account:
        """
        Flujo IOL:
          1. Valida credenciales llamando a la API y trae posiciones iniciales.
          2. Guarda credenciales cifradas en Vault.
          3. Inserta el registro de cuenta con last_sync ya poblado.
          4. Persiste las posiciones iniciales en historical_balances.
        """
        from app.services.connectors.iol import IolConnector
        from app.services.asset_service import _persist_holdings

        _cleanup_existing_account(user_id, data.platform)
        connector = IolConnector(account_id="", credentials=data.credentials)

        try:
            holdings = await connector.get_holdings()
        except ConnectorError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"No se pudo conectar con InvertirOnline: {exc}",
            ) from exc

        secret_name = f"account_creds_{user_id}_{data.platform.value}"
        vault_result = supabase_admin.rpc(
            "upsert_vault_secret",
            {"p_secret": json.dumps(data.credentials), "p_name": secret_name},
        ).execute()
        secret_id = vault_result.data

        username = data.credentials.get("username", "")
        label = f"IOL {username}" if username else "InvertirOnline"

        now_iso = datetime.now(timezone.utc).isoformat()
        result = (
            supabase_admin.table("account")
            .insert({
                "user_id": user_id,
                "platform": data.platform.value,
                "label": label,
                "connection_status": ConnectionStatus.ACTIVE.value,
                "secret_id": str(secret_id),
                "last_sync": now_iso,
            })
            .execute()
        )
        account_row = result.data[0]
        account_id = account_row["id"]

        try:
            await _persist_holdings(account_id, holdings)
        except Exception:
            pass

        return _row_to_account(account_row)

    @staticmethod
    async def unlink_account(user_id: str, account_id: str) -> None:
        # Obtener secret_id antes de borrar
        row = (
            supabase_admin.table("account")
            .select("secret_id")
            .eq("id", account_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not row.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada")

        secret_id = row.data.get("secret_id")

        supabase_admin.table("account").delete().eq("id", account_id).eq("user_id", user_id).execute()

        if secret_id:
            supabase_admin.rpc("delete_vault_secret", {"p_secret_id": str(secret_id)}).execute()

    @staticmethod
    async def get_credentials(account_id: str) -> dict:
        row = (
            supabase_admin.table("account")
            .select("secret_id")
            .eq("id", account_id)
            .single()
            .execute()
        )
        if not row.data or not row.data.get("secret_id"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credenciales no encontradas")

        secret_result = supabase_admin.rpc(
            "read_vault_secret",
            {"p_secret_id": str(row.data["secret_id"])},
        ).execute()

        return json.loads(secret_result.data)


def _cleanup_existing_account(user_id: str, platform: Platform) -> None:
    """
    Si el usuario ya tiene una cuenta para este platform, la elimina junto con
    su secreto en Vault. Permite re-vinculación limpia sin conflictos de unique key.
    """
    rows = (
        supabase_admin.table("account")
        .select("id, secret_id")
        .eq("user_id", user_id)
        .eq("platform", platform.value)
        .execute()
    )
    for row in rows.data or []:
        supabase_admin.table("account").delete().eq("id", row["id"]).execute()
        if row.get("secret_id"):
            try:
                supabase_admin.rpc(
                    "delete_vault_secret",
                    {"p_secret_id": str(row["secret_id"])},
                ).execute()
            except Exception:
                pass


def _row_to_account(row: dict) -> Account:
    return Account(
        id=row["id"],
        platform=Platform(row["platform"]),
        label=row.get("label"),
        connection_status=ConnectionStatus(row["connection_status"]),
        last_sync=row.get("last_sync"),
        error_message=row.get("error_message"),
    )


def _build_label(platform: Platform, credentials: dict) -> str:
    match platform:
        case Platform.COCOS | Platform.IOL:
            return credentials.get("email") or credentials.get("username") or platform.value
        case Platform.MERCADOPAGO:
            token = credentials.get("access_token", "")
            return f"MP ...{token[-6:]}" if len(token) > 6 else "Mercado Pago"
        case Platform.NACION:
            cuit = credentials.get("cuit", "")
            return f"Nación {cuit}" if cuit else "Banco Nación"
        case _:
            return platform.value
