from fastapi import HTTPException, status

from app.core.supabase import supabase_admin
from app.schemas.asset import Currency
from app.schemas.portfolio import (
    CreatePortfolioRequest,
    Portfolio,
    PortfolioAsset,
    PortfolioAssetInput,
    PortfolioAssetSummary,
    PortfolioSummary,
    UpdatePortfolioRequest,
)

_PORTFOLIO_ASSETS_SELECT = "*, portfolio_assets(asset_ticker, target_share)"


class PortfolioService:

    @staticmethod
    async def list_portfolios(user_id: str) -> list[Portfolio]:
        result = (
            supabase_admin.table("portfolios")
            .select(_PORTFOLIO_ASSETS_SELECT)
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return [_row_to_portfolio(row) for row in result.data]

    @staticmethod
    async def create_portfolio(user_id: str, data: CreatePortfolioRequest) -> Portfolio:
        result = (
            supabase_admin.table("portfolios")
            .insert({"user_id": user_id, "name": data.name, "description": data.description})
            .execute()
        )
        portfolio_id = result.data[0]["id"]

        if data.assets:
            await _set_portfolio_assets(portfolio_id, data.assets)

        return await _fetch_portfolio(portfolio_id)

    @staticmethod
    async def get_summary(user_id: str, portfolio_id: str) -> PortfolioSummary:
        portfolio = await _fetch_portfolio_owned_by(portfolio_id, user_id)

        balances = (
            supabase_admin.rpc(
                "get_portfolio_balances",
                {"p_portfolio_id": portfolio_id, "p_user_id": user_id},
            ).execute()
        )

        assets = [_row_to_portfolio_asset(row) for row in (balances.data or [])]
        total_ars = sum(a.total_valuation for a in assets if a.currency == Currency.ARS)
        total_usd = sum(a.total_valuation for a in assets if a.currency == Currency.USD)

        return PortfolioSummary(
            portfolio=portfolio,
            assets=assets,
            total_ars=total_ars,
            total_usd=total_usd,
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

        # assets=None → no tocar los activos existentes (comportamiento patch)
        if data.assets is not None:
            await _set_portfolio_assets(portfolio_id, data.assets)

        return await _fetch_portfolio(portfolio_id)

    @staticmethod
    async def delete_portfolio(user_id: str, portfolio_id: str) -> None:
        await _fetch_portfolio_owned_by(portfolio_id, user_id)
        supabase_admin.table("portfolios").delete().eq("id", portfolio_id).execute()


# --- helpers ---

async def _fetch_portfolio(portfolio_id: str) -> Portfolio:
    result = (
        supabase_admin.table("portfolios")
        .select(_PORTFOLIO_ASSETS_SELECT)
        .eq("id", portfolio_id)
        .single()
        .execute()
    )
    return _row_to_portfolio(result.data)


async def _fetch_portfolio_owned_by(portfolio_id: str, user_id: str) -> Portfolio:
    result = (
        supabase_admin.table("portfolios")
        .select(_PORTFOLIO_ASSETS_SELECT)
        .eq("id", portfolio_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio no encontrado")
    return _row_to_portfolio(result.data)


async def _set_portfolio_assets(portfolio_id: str, assets: list[PortfolioAssetInput]) -> None:
    supabase_admin.table("portfolio_assets").delete().eq("portfolio_id", portfolio_id).execute()
    if assets:
        rows = [
            {
                "portfolio_id": portfolio_id,
                "asset_ticker": a.ticker,
                "target_share": a.target_share,
            }
            for a in assets
        ]
        supabase_admin.table("portfolio_assets").insert(rows).execute()


def _row_to_portfolio(row: dict) -> Portfolio:
    pas = row.get("portfolio_assets") or []
    assets = [
        PortfolioAsset(ticker=pa["asset_ticker"], target_share=pa.get("target_share"))
        for pa in pas
    ]
    return Portfolio(
        id=row["id"],
        name=row["name"],
        description=row.get("description"),
        assets=assets,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_portfolio_asset(row: dict) -> PortfolioAssetSummary:
    return PortfolioAssetSummary(
        ticker=row["asset_ticker"],
        name=row.get("external_name"),
        asset_type=row.get("asset_type"),
        currency=Currency(row["currency"]) if row.get("currency") else None,
        platform=row.get("platform"),
        total_quantity=float(row["total_quantity"]),
        unit_price=float(row["unit_price"]) if row.get("unit_price") is not None else None,
        total_valuation=float(row["total_valuation"]),
        target_share=float(row["target_share"]) if row.get("target_share") is not None else None,
    )
