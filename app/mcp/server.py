"""
Servidor MCP montado en la app FastAPI vía fastapi-mcp.

Expone tools para que un agente IA consulte el contexto financiero del usuario.
El servidor corre en /mcp (SSE transport).

Uso desde el agente:
    mcp_client.connect("http://localhost:8000/mcp")
    result = await mcp_client.call_tool("get_financial_summary", {"user_id": "..."})
"""

from fastapi import FastAPI
from fastapi_mcp import FastApiMCP

from .tools import get_assets, get_financial_summary, get_portfolios


def mount_mcp(app: FastAPI) -> None:
    """Monta el servidor MCP en la app FastAPI existente."""
    mcp = FastApiMCP(
        app,
        name="AssetCentral MCP",
        description="Contexto financiero unificado del usuario: activos, portfolios y métricas.",
    )

    @mcp.tool()
    async def financial_summary(user_id: str) -> dict:
        """
        Resumen financiero total del usuario: patrimonio en ARS/USD,
        distribución por tipo de activo y variación diaria ponderada.
        """
        return await get_financial_summary(user_id)

    @mcp.tool()
    async def list_assets(user_id: str, asset_type: str | None = None) -> list[dict]:
        """
        Lista los activos del usuario.
        asset_type opcional: CEDEAR | BONO | FCI | USD | ACCION | CRYPTO | OTRO
        """
        return await get_assets(user_id, asset_type)

    @mcp.tool()
    async def list_portfolios(user_id: str) -> list[dict]:
        """
        Lista los portfolios personalizados del usuario con su valuación total en ARS.
        """
        return await get_portfolios(user_id)

    mcp.mount()
