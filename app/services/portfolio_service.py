from fastapi import HTTPException, status

from app.core.supabase import supabase_admin
from app.schemas.asset import Asset, AssetType
from app.schemas.account import Platform
from app.schemas.portfolio import (
    CreatePortfolioRequest,
    Portfolio,
    PortfolioSummary,
    UpdatePortfolioRequest,
)


class PortfolioService:

    @staticmethod
    async def list_portfolios(user_id: str) -> list[Portfolio]:
        portfolios = (
            supabase_admin.table("portfolios")
            .select("*, portfolio_assets(asset_id)")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return [_row_to_portfolio(row) for row in portfolios.data]

    @staticmethod
    async def create_portfolio(user_id: str, data: CreatePortfolioRequest) -> Portfolio:
        result = (
            supabase_admin.table("portfolios")
            .insert({
                "user_id": user_id,
                "name": data.name,
                "description": data.description,
            })
            .execute()
        )
        portfolio_id = result.data[0]["id"]

        if data.asset_ids:
            await _set_portfolio_assets(portfolio_id, data.asset_ids)

        return await _fetch_portfolio(portfolio_id)

    @staticmethod
    async def get_summary(user_id: str, portfolio_id: str) -> PortfolioSummary:
        portfolio = await _fetch_portfolio_owned_by(portfolio_id, user_id)

        assets: list[Asset] = []
        if portfolio.asset_ids:
            snapshots = (
                supabase_admin.table("asset_snapshots")
                .select("*")
                .in_("id", portfolio.asset_ids)
                .execute()
            )
            assets = [_row_to_asset(row) for row in snapshots.data]

        total_ars = sum(a.total_ars for a in assets)
        total_usd = sum(a.total_usd for a in assets if a.total_usd) or None

        # Variación diaria ponderada por peso en ARS
        if total_ars > 0:
            daily_change = sum(
                a.daily_change_percent * (a.total_ars / total_ars) for a in assets
            )
        else:
            daily_change = 0.0

        return PortfolioSummary(
            portfolio=portfolio,
            assets=assets,
            total_ars=total_ars,
            total_usd=total_usd,
            daily_change_percent=daily_change,
        )

    @staticmethod
    async def update_portfolio(
        user_id: str, portfolio_id: str, data: UpdatePortfolioRequest
    ) -> Portfolio:
        await _fetch_portfolio_owned_by(portfolio_id, user_id)

        patch: dict = {}
        if data.name is not None:
            patch["name"] = data.name
        if data.description is not None:
            patch["description"] = data.description

        if patch:
            supabase_admin.table("portfolios").update(patch).eq("id", portfolio_id).execute()

        if data.asset_ids is not None:
            await _set_portfolio_assets(portfolio_id, data.asset_ids)

        return await _fetch_portfolio(portfolio_id)

    @staticmethod
    async def delete_portfolio(user_id: str, portfolio_id: str) -> None:
        await _fetch_portfolio_owned_by(portfolio_id, user_id)
        supabase_admin.table("portfolios").delete().eq("id", portfolio_id).execute()


# --- helpers ---

async def _fetch_portfolio(portfolio_id: str) -> Portfolio:
    result = (
        supabase_admin.table("portfolios")
        .select("*, portfolio_assets(asset_id)")
        .eq("id", portfolio_id)
        .single()
        .execute()
    )
    return _row_to_portfolio(result.data)


async def _fetch_portfolio_owned_by(portfolio_id: str, user_id: str) -> Portfolio:
    result = (
        supabase_admin.table("portfolios")
        .select("*, portfolio_assets(asset_id)")
        .eq("id", portfolio_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio no encontrado",
        )
    return _row_to_portfolio(result.data)


async def _set_portfolio_assets(portfolio_id: str, asset_ids: list[str]) -> None:
    supabase_admin.table("portfolio_assets").delete().eq("portfolio_id", portfolio_id).execute()
    if asset_ids:
        rows = [{"portfolio_id": portfolio_id, "asset_id": aid} for aid in asset_ids]
        supabase_admin.table("portfolio_assets").insert(rows).execute()


def _row_to_portfolio(row: dict) -> Portfolio:
    asset_ids = [pa["asset_id"] for pa in (row.get("portfolio_assets") or [])]
    return Portfolio(
        id=row["id"],
        name=row["name"],
        description=row.get("description"),
        asset_ids=asset_ids,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_asset(row: dict) -> Asset:
    return Asset(
        id=row["id"],
        ticker=row["ticker"],
        name=row["name"],
        type=AssetType(row["asset_type"]),
        platform=Platform(row["platform"]),
        quantity=float(row["quantity"]),
        price_ars=float(row["price_ars"]),
        price_usd=float(row["price_usd"]) if row.get("price_usd") else None,
        total_ars=float(row["total_ars"]),
        total_usd=float(row["total_usd"]) if row.get("total_usd") else None,
        daily_change_percent=float(row["daily_change_pct"]),
    )
