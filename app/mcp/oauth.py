"""
Mini servidor OAuth2 para el MCP de AssetCentral.

Implementa el flujo Authorization Code necesario para que Claude Code
pueda autenticarse con el MCP server. El "código" de autorización
es directamente el JWT de Supabase del usuario ya autenticado en el
frontend (lo lee de localStorage via una página HTML intermedia).
"""

import secrets
import time
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter(tags=["oauth"])

# Almacén temporal en memoria: code → jwt (expira en 5 min)
_codes: dict[str, tuple[str, float]] = {}


def _make_code(jwt: str) -> str:
    code = secrets.token_urlsafe(32)
    _codes[code] = (jwt, time.time() + 300)
    return code


def _consume_code(code: str) -> Optional[str]:
    entry = _codes.pop(code, None)
    if entry is None:
        return None
    jwt, exp = entry
    if time.time() > exp:
        return None
    return jwt


@router.get("/oauth/authorize")
async def oauth_authorize(
    request: Request,
    redirect_uri: str = Query(...),
    state: str = Query(default=""),
    client_id: str = Query(default=""),
    code_challenge: str = Query(default=""),
    code_challenge_method: str = Query(default=""),
    response_type: str = Query(default="code"),
    scope: str = Query(default=""),
):
    """
    Redirige al frontend que puede leer el JWT de su propio localStorage.
    """
    from app.core.config import settings
    from urllib.parse import urlencode

    params = urlencode({
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
    })
    frontend = settings.frontend_url.rstrip("/")
    return RedirectResponse(url=f"{frontend}/mcp-auth?{params}")


@router.post("/oauth/code")
async def oauth_code(request: Request):
    """Recibe el JWT desde la página HTML y devuelve un code temporal."""
    body = await request.json()
    jwt = body.get("jwt", "")
    if not jwt or len(jwt) < 20:
        raise HTTPException(status_code=400, detail="JWT inválido")
    code = _make_code(jwt)
    return JSONResponse({"code": code})


@router.post("/oauth/token")
async def oauth_token(
    grant_type: str = Form(default="authorization_code"),
    code: str = Form(default=""),
    redirect_uri: str = Form(default=""),
    client_id: str = Form(default=""),
    client_secret: str = Form(default=""),
    code_verifier: str = Form(default=""),
):
    """Intercambia el code temporal por el JWT de Supabase como access_token."""
    if grant_type == "authorization_code":
        jwt = _consume_code(code)
        if not jwt:
            raise HTTPException(status_code=400, detail="invalid_grant")
        return JSONResponse({
            "access_token": jwt,
            "token_type": "bearer",
            "expires_in": 3600,
        })

    raise HTTPException(status_code=400, detail="unsupported_grant_type")
