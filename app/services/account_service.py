import json

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
            CredentialField(name="cuit", label="CUIT", type="text", placeholder="20-12345678-9"),
            CredentialField(name="password", label="Contraseña", type="password"),
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
        label = _build_label(data.platform, data.credentials)
        secret_name = f"account_creds_{user_id}_{data.platform.value}"

        # Guardar credenciales en Supabase Vault
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
