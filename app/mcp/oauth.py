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


@router.get("/oauth/authorize", response_class=HTMLResponse)
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
    Página HTML intermedia: lee el JWT de Supabase desde localStorage
    y redirige al redirect_uri con el code de autorización.
    """
    redirect_uri_escaped = redirect_uri.replace('"', "&quot;")
    state_escaped = state.replace('"', "&quot;")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AssetCentral — Autorizar MCP</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          background:#0f0f18;color:#e5e7eb;display:flex;align-items:center;
          justify-content:center;min-height:100vh;padding:24px}}
    .card{{background:#1a1a2e;border:1px solid #2d2d44;border-radius:12px;
           padding:32px;max-width:440px;width:100%;text-align:center}}
    .logo{{font-size:28px;font-weight:700;color:#818cf8;margin-bottom:8px}}
    .sub{{color:#9ca3af;font-size:14px;margin-bottom:24px}}
    .status{{font-size:14px;color:#6ee7b7;margin-bottom:16px}}
    .error{{color:#f87171}}
    .btn{{display:inline-block;padding:10px 24px;background:#818cf8;
          color:#fff;border:none;border-radius:8px;font-size:14px;
          font-weight:600;cursor:pointer;text-decoration:none;margin-top:16px}}
    .btn:hover{{background:#6d6ef8}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">AssetCentral</div>
    <div class="sub">Autorizando acceso MCP...</div>
    <div id="status" class="status">Buscando sesión activa...</div>
    <div id="manual" style="display:none">
      <p style="font-size:13px;color:#9ca3af;margin-bottom:12px">
        No se encontró sesión activa. Iniciá sesión en AssetCentral primero
        o pegá tu JWT manualmente:
      </p>
      <textarea id="jwt-input" rows="4"
        style="width:100%;background:#0f0f18;border:1px solid #2d2d44;
               border-radius:6px;color:#e5e7eb;padding:8px;font-family:monospace;
               font-size:11px;resize:vertical"
        placeholder="eyJhbGci..."></textarea>
      <br>
      <button class="btn" onclick="submitJwt()">Autorizar</button>
    </div>
  </div>
  <script>
    const REDIRECT_URI = "{redirect_uri_escaped}";
    const STATE = "{state_escaped}";

    async function getJwtFromStorage() {{
      // Supabase guarda la sesión en localStorage con prefijo sb-*-auth-token
      for (let i = 0; i < localStorage.length; i++) {{
        const key = localStorage.key(i);
        if (key && key.includes('-auth-token')) {{
          try {{
            const val = JSON.parse(localStorage.getItem(key) || '');
            const jwt = val?.access_token || val?.data?.access_token;
            if (jwt) return jwt;
          }} catch(e) {{}}
        }}
      }}
      return null;
    }}

    async function authorize(jwt) {{
      document.getElementById('status').textContent = 'Autorizando...';
      try {{
        const resp = await fetch('/oauth/code', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{jwt}})
        }});
        const data = await resp.json();
        if (!data.code) throw new Error('No code');
        const url = new URL(REDIRECT_URI);
        url.searchParams.set('code', data.code);
        if (STATE) url.searchParams.set('state', STATE);
        document.getElementById('status').textContent = '✓ Autorizado. Redirigiendo...';
        setTimeout(() => {{ window.location.href = url.toString(); }}, 500);
      }} catch(e) {{
        document.getElementById('status').className = 'status error';
        document.getElementById('status').textContent = 'Error: ' + e.message;
        document.getElementById('manual').style.display = 'block';
      }}
    }}

    async function submitJwt() {{
      const jwt = document.getElementById('jwt-input').value.trim();
      if (!jwt) return;
      await authorize(jwt);
    }}

    (async () => {{
      const jwt = await getJwtFromStorage();
      if (jwt) {{
        document.getElementById('status').textContent = '✓ Sesión encontrada';
        await authorize(jwt);
      }} else {{
        document.getElementById('status').textContent = 'No se encontró sesión activa';
        document.getElementById('manual').style.display = 'block';
      }}
    }})();
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


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
