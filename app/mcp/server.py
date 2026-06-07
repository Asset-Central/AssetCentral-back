"""
Servidor MCP montado sobre la app FastAPI.

fastapi-mcp convierte automáticamente todos los endpoints de FastAPI
en tools MCP, incluyendo sus schemas de request/response.
El header Authorization se propaga a cada tool call.
"""

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi_mcp import FastApiMCP
from fastapi_mcp.auth.proxy import setup_oauth_fake_dynamic_register_endpoint
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
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "code_challenge_methods_supported": ["S256"],
}


async def _require_bearer(request: Request):
    """Valida el Bearer token async. Retorna 401 (sin bloquear el event loop)
    para disparar el flujo OAuth cuando el token es inválido o está ausente."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Bearer realm="AssetCentral"'},
        )
    from app.core.config import settings
    token = auth[7:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.supabase_url}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": settings.supabase_anon_key,
                },
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=401,
                detail="Token inválido o expirado",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )


def mount_mcp(app: FastAPI) -> None:
    # Registrar rutas OAuth antes del MCP
    app.include_router(oauth_router)

    auth_config = AuthConfig(
        issuer=BACKEND_URL,
        custom_oauth_metadata=OAUTH_METADATA,
        dependencies=[Depends(_require_bearer)],
    )

    mcp = FastApiMCP(
        app,
        name="AssetCentral MCP",
        description="Contexto financiero unificado: activos, portfolios y cuentas vinculadas.",
        auth_config=auth_config,
    )
    mcp.mount_http()  # Streamable HTTP transport (requerido por Claude Code type: http)

    # Fake dynamic client registration (RFC 7591) requerido por Claude Code SDK
    setup_oauth_fake_dynamic_register_endpoint(
        app=app,
        client_id=MCP_CLIENT_ID,
        client_secret=MCP_CLIENT_SECRET,
    )
