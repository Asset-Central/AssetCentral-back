"""
Tools MCP expuestos al agente IA.

Cada tool recibe un user_id (string UUID) y devuelve datos financieros del usuario.
El agente es responsable de autenticar al usuario y pasar el user_id correcto.
"""

from app.core.supabase import supabase_admin
from app.schemas.asset import AssetType


async def get_financial_summary(user_id: str) -> dict:
    """
    Resumen financiero total del usuario:
    - Total en ARS y USD
    - Distribución por tipo de activo
    - Variación diaria ponderada
    """
    snapshots = (
        supabase_admin.table("asset_snapshots")
        .select("asset_type, total_ars, total_usd, daily_change_pct, quantity")
        .eq("user_id", user_id)
        .execute()
    )

    assets = snapshots.data
    total_ars = sum(float(a["total_ars"]) for a in assets)
    total_usd = sum(float(a["total_usd"]) for a in assets if a.get("total_usd")) or None

    by_type: dict[str, float] = {}
    for a in assets:
        t = a["asset_type"]
        by_type[t] = by_type.get(t, 0) + float(a["total_ars"])

    daily_change = (
        sum(float(a["daily_change_pct"]) * (float(a["total_ars"]) / total_ars) for a in assets)
        if total_ars > 0
        else 0.0
    )

    return {
        "total_ars": total_ars,
        "total_usd": total_usd,
        "daily_change_percent": round(daily_change, 4),
        "by_type": {k: {"total_ars": v, "percentage": round(v / total_ars * 100, 2)} for k, v in by_type.items()},
        "asset_count": len(assets),
    }


async def get_assets(user_id: str, asset_type: str | None = None) -> list[dict]:
    """
    Lista de activos del usuario.
    Opcionalmente filtrado por tipo: CEDEAR, BONO, FCI, USD, ACCION, CRYPTO, OTRO.
    """
    query = (
        supabase_admin.table("asset_snapshots")
        .select("id, ticker, name, asset_type, platform, quantity, price_ars, total_ars, daily_change_pct")
        .eq("user_id", user_id)
    )
    if asset_type:
        query = query.eq("asset_type", asset_type.upper())

    result = query.execute()
    return result.data


async def get_portfolios(user_id: str) -> list[dict]:
    """Lista los portfolios del usuario con su valuación total."""
    portfolios = (
        supabase_admin.table("portfolios")
        .select("id, name, description, created_at, portfolio_assets(asset_id)")
        .eq("user_id", user_id)
        .execute()
    )

    result = []
    for p in portfolios.data:
        asset_ids = [pa["asset_id"] for pa in (p.get("portfolio_assets") or [])]
        total_ars = 0.0

        if asset_ids:
            snapshots = (
                supabase_admin.table("asset_snapshots")
                .select("total_ars")
                .in_("id", asset_ids)
                .execute()
            )
            total_ars = sum(float(s["total_ars"]) for s in snapshots.data)

        result.append({
            "id": p["id"],
            "name": p["name"],
            "description": p.get("description"),
            "asset_count": len(asset_ids),
            "total_ars": total_ars,
        })

    return result
