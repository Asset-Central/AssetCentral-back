"""
Servidor MCP montado sobre la app FastAPI.

fastapi-mcp convierte automáticamente todos los endpoints de FastAPI
en tools MCP, incluyendo sus schemas de request/response.
El header Authorization se propaga a cada tool call.
"""

from fastapi import FastAPI
from fastapi_mcp import FastApiMCP
from fastapi_mcp.auth.proxy import (
    setup_oauth_custom_metadata,
    setup_oauth_fake_dynamic_register_endpoint,
)
from fastapi_mcp.types import AuthConfig

SUPABASE_ISSUER = "https://geqltnpxydhpwysapexz.supabase.co/auth/v1"
MCP_CLIENT_ID = "assetcentral-mcp"
MCP_CLIENT_SECRET = "assetcentral-mcp-secret"

OAUTH_METADATA = {
    "issuer": SUPABASE_ISSUER,
    "authorization_endpoint": f"{SUPABASE_ISSUER}/oauth/authorize",
    "token_endpoint": f"{SUPABASE_ISSUER}/oauth/token",
    "jwks_uri": f"{SUPABASE_ISSUER}/.well-known/jwks.json",
    "scopes_supported": ["openid", "profile", "email"],
    "response_types_supported": ["code"],
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "code_challenge_methods_supported": ["S256"],
    "registration_endpoint": "https://assetcentral-back-production.up.railway.app/oauth/register",
}


def mount_mcp(app: FastAPI) -> None:
    auth_config = AuthConfig(
        issuer=SUPABASE_ISSUER,
        custom_oauth_metadata=OAUTH_METADATA,
    )

    mcp = FastApiMCP(
        app,
        name="AssetCentral MCP",
        description="Contexto financiero unificado: activos, portfolios y cuentas vinculadas.",
        auth_config=auth_config,
    )
    mcp.mount()

    # Fake dynamic client registration (RFC 7591) requerido por Claude Code SDK
    setup_oauth_fake_dynamic_register_endpoint(
        app=app,
        client_id=MCP_CLIENT_ID,
        client_secret=MCP_CLIENT_SECRET,
    )
