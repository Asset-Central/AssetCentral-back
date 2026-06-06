"""
Tools MCP expuestos al agente IA.

Cada tool recibe un user_id (string UUID) y devuelve datos financieros del usuario.
El agente es responsable de autenticar al usuario y pasar el user_id correcto.
"""

from app.core.supabase import supabase_admin


async def get_financial_summary(user_id: str) -> dict:
    """
    Resumen financiero total del usuario:
    - Total en ARS y USD (separado por moneda)
    - Distribución por tipo de activo
    """
    balances = supabase_admin.rpc("get_latest_balances", {"p_user_id": user_id}).execute()
    rows = balances.data or []

    total_ars = 0.0
    total_usd = 0.0
    by_type: dict[str, dict] = {}

    for row in rows:
        valuation = float(row.get("total_valuation") or 0)
        currency = row.get("currency", "ARS")
        asset_type = row.get("asset_type", "unknown")

        if currency == "ARS":
            total_ars += valuation
        else:
            total_usd += valuation

        if asset_type not in by_type:
            by_type[asset_type] = {"total_ars": 0.0, "total_usd": 0.0}
        if currency == "ARS":
            by_type[asset_type]["total_ars"] += valuation
        else:
            by_type[asset_type]["total_usd"] += valuation

    return {
        "total_ars": round(total_ars, 2),
        "total_usd": round(total_usd, 2),
        "by_type": by_type,
        "asset_count": len(rows),
    }


async def get_assets(user_id: str, asset_type: str | None = None) -> list[dict]:
    """
    Lista de activos del usuario con sus posiciones actuales.
    Opcionalmente filtrado por tipo: cedear | bono | fci | cash | crypto | stock.
    """
    result = supabase_admin.rpc("get_latest_balances", {"p_user_id": user_id}).execute()
    rows = result.data or []

    if asset_type:
        rows = [r for r in rows if r.get("asset_type") == asset_type.lower()]

    return [
        {
            "ticker": r["asset_ticker"],
            "name": r.get("external_name"),
            "asset_type": r.get("asset_type"),
            "platform": r.get("platform"),
            "currency": r.get("currency"),
            "quantity": float(r["quantity"]),
            "unit_price": float(r["unit_price"]) if r.get("unit_price") is not None else None,
            "total_valuation": float(r["total_valuation"]) if r.get("total_valuation") is not None else None,
        }
        for r in rows
    ]


async def get_user_financial_profile(user_id: str) -> dict:
    """
    Perfil financiero personal del usuario (opcional, auto-declarado).
    Incluye: edad, ingresos mensuales, capacidad de ahorro, aversión al riesgo,
    horizonte de inversión, objetivos y preferencia de moneda.
    Usar este contexto para personalizar recomendaciones de inversión.
    """
    result = (
        supabase_admin.table("users")
        .select("financial_profile")
        .eq("id", user_id)
        .single()
        .execute()
    )
    profile = (result.data or {}).get("financial_profile") or {}
    if not profile:
        return {"message": "El usuario no ha completado su perfil financiero."}
    return profile


async def get_portfolios(user_id: str) -> list[dict]:
    """Lista los portfolios del usuario con su valuación total."""
    portfolios = (
        supabase_admin.table("portfolios")
        .select("id, name, description, created_at, portfolio_assets(asset_id, assets(ticker, platform))")
        .eq("user_id", user_id)
        .execute()
    )

    result = []
    for p in portfolios.data:
        tickers = [pa["assets"]["ticker"] for pa in (p.get("portfolio_assets") or [])]

        balances = (
            supabase_admin.rpc(
                "get_portfolio_balances",
                {"p_portfolio_id": p["id"], "p_user_id": user_id},
            ).execute()
        )
        rows = balances.data or []
        total_ars = sum(float(r.get("total_valuation") or 0) for r in rows if r.get("currency") == "ARS")
        total_usd = sum(float(r.get("total_valuation") or 0) for r in rows if r.get("currency") == "USD")

        result.append({
            "id": p["id"],
            "name": p["name"],
            "description": p.get("description"),
            "asset_count": len(tickers),
            "total_ars": round(total_ars, 2),
            "total_usd": round(total_usd, 2),
        })

    return result
