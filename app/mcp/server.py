"""
Servidor MCP montado sobre la app FastAPI.

fastapi-mcp convierte automáticamente todos los endpoints de FastAPI
en tools MCP, incluyendo sus schemas de request/response.
El header Authorization se propaga a cada tool call.
"""

from fastapi import FastAPI
from fastapi_mcp import FastApiMCP
from fastapi_mcp.types import AuthConfig

SUPABASE_ISSUER = "https://geqltnpxydhpwysapexz.supabase.co/auth/v1"


def mount_mcp(app: FastAPI) -> None:
    mcp = FastApiMCP(
        app,
        name="AssetCentral MCP",
        description="Contexto financiero unificado: activos, portfolios y cuentas vinculadas.",
        auth_config=AuthConfig(
            issuer=SUPABASE_ISSUER,
            custom_oauth_metadata={
                "issuer": SUPABASE_ISSUER,
                "authorization_endpoint": f"{SUPABASE_ISSUER}/oauth/authorize",
                "token_endpoint": f"{SUPABASE_ISSUER}/oauth/token",
                "jwks_uri": f"{SUPABASE_ISSUER}/.well-known/jwks.json",
                "userinfo_endpoint": f"{SUPABASE_ISSUER}/oauth/userinfo",
                "scopes_supported": ["openid", "profile", "email"],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
            },
        ),
    )
    mcp.mount()
