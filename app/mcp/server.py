"""
Servidor MCP montado sobre la app FastAPI.

fastapi-mcp convierte automáticamente todos los endpoints de FastAPI
en tools MCP, incluyendo sus schemas de request/response.
El header Authorization se propaga a cada tool call.
"""

from fastapi import FastAPI
from fastapi_mcp import FastApiMCP


def mount_mcp(app: FastAPI) -> None:
    mcp = FastApiMCP(
        app,
        name="AssetCentral MCP",
        description="Contexto financiero unificado: activos, portfolios y cuentas vinculadas.",
    )
    mcp.mount()
