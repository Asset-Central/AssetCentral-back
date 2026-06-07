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

from app.mcp.oauth import router as oauth_router

BACKEND_URL = "https://assetcentral-back-production.up.railway.app"
MCP_CLIENT_ID = "assetcentral-mcp"
MCP_CLIENT_SECRET = "assetcentral-mcp-secret"

OAUTH_METADATA = {
    "issuer": BACKEND_URL,
    "authorization_endpoint": f"{BACKEND_URL}/oauth/authorize",
    "token_endpoint": f"{BACKEND_URL}/oauth/token",
    "registration_endpoint": f"{BACKEND_URL}/oauth/register",
    "scopes_supported": ["openid"],
    "response_types_supported": ["code"],
    "grant_types_supported": ["authorization_code"],
    "code_challenge_methods_supported": ["S256"],
}


def mount_mcp(app: FastAPI) -> None:
    # Registrar rutas OAuth antes del MCP
    app.include_router(oauth_router)

    auth_config = AuthConfig(
        issuer=BACKEND_URL,
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
