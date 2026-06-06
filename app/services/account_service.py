from fastapi import HTTPException, status

from app.core.security import encrypt_credentials
from app.core.supabase import supabase_admin
from app.schemas.account import (
    AccountStatus,
    CredentialField,
    LinkedAccount,
    Platform,
    PlatformConfig,
)

# Configuración estática de cada plataforma (campos de credenciales requeridos)
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
        platform=Platform.MERCADO_PAGO,
        display_name="Mercado Pago",
        logo_url="/logos/mercadopago.png",
        fields=[
            CredentialField(name="access_token", label="Access Token", type="password",
                            placeholder="APP_USR-..."),
        ],
    ),
    PlatformConfig(
        platform=Platform.PROMETEO,
        display_name="Prometeo",
        logo_url="/logos/prometeo.png",
        fields=[
            CredentialField(name="api_key", label="API Key", type="password"),
            CredentialField(name="provider", label="Proveedor", type="text",
                            placeholder="ej: itau_uy"),
            CredentialField(name="username", label="Usuario", type="text"),
            CredentialField(name="password", label="Contraseña", type="password"),
        ],
    ),
]


class AccountService:

    @staticmethod
    def get_platform_configs() -> list[PlatformConfig]:
        return PLATFORM_CONFIGS

    @staticmethod
    async def list_accounts(user_id: str) -> list[LinkedAccount]:
        result = (
            supabase_admin.table("linked_accounts")
            .select("id, platform, label, status, last_sync_at, error_message")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return [_row_to_account(row) for row in result.data]

    @staticmethod
    async def link_account(
        user_id: str,
        dek: bytes,
        platform: Platform,
        credentials: dict[str, str],
    ) -> LinkedAccount:
        credentials_enc = encrypt_credentials(dek, credentials)
        label = _default_label(platform, credentials)

        result = (
            supabase_admin.table("linked_accounts")
            .insert({
                "user_id": user_id,
                "platform": platform.value,
                "label": label,
                "status": AccountStatus.PENDING.value,
                "credentials_enc": credentials_enc,
            })
            .execute()
        )
        return _row_to_account(result.data[0])

    @staticmethod
    async def unlink_account(user_id: str, account_id: str) -> None:
        result = (
            supabase_admin.table("linked_accounts")
            .delete()
            .eq("id", account_id)
            .eq("user_id", user_id)  # garantiza que el usuario es el dueño
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cuenta no encontrada",
            )


def _row_to_account(row: dict) -> LinkedAccount:
    return LinkedAccount(
        id=row["id"],
        platform=Platform(row["platform"]),
        label=row["label"],
        status=AccountStatus(row["status"]),
        last_sync_at=row.get("last_sync_at"),
        error_message=row.get("error_message"),
    )


def _default_label(platform: Platform, credentials: dict) -> str:
    """Genera un label legible para la cuenta basado en las credenciales."""
    match platform:
        case Platform.COCOS | Platform.IOL:
            return credentials.get("email") or credentials.get("username") or platform.value
        case Platform.MERCADO_PAGO:
            token = credentials.get("access_token", "")
            return f"MP ...{token[-6:]}" if len(token) > 6 else "Mercado Pago"
        case Platform.PROMETEO:
            provider = credentials.get("provider", "")
            user = credentials.get("username", "")
            return f"Prometeo / {provider} / {user}".strip(" /")
        case _:
            return platform.value
