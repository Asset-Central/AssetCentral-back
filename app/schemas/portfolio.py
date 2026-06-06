from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from .account import Platform
from .asset import Currency


class PortfolioAsset(BaseModel):
    """Activo dentro de un portfolio, con su target share opcional."""
    ticker: str
    platform: Platform
    target_share: Annotated[float, Field(gt=0, le=100)] | None = None


class PortfolioAssetInput(BaseModel):
    """Input para crear/actualizar un activo en el portfolio."""
    ticker: str
    platform: Platform
    target_share: Annotated[float, Field(gt=0, le=100)] | None = None


class Portfolio(BaseModel):
    id: str
    name: str
    description: str | None = None
    assets: list[PortfolioAsset]
    created_at: datetime
    updated_at: datetime


class PortfolioAssetSummary(BaseModel):
    ticker: str
    name: str | None = None
    asset_type: str | None = None
    currency: Currency | None = None
    platform: str | None = None
    total_quantity: float
    unit_price: float | None = None
    total_valuation: float
    target_share: float | None = None


class PortfolioSummary(BaseModel):
    portfolio: Portfolio
    assets: list[PortfolioAssetSummary]
    total_ars: float
    total_usd: float


def _validate_asset_shares(assets: list[PortfolioAssetInput]) -> None:
    if not assets:
        return
    shares = [a.target_share for a in assets if a.target_share is not None]
    if not shares:
        return  # ninguno definido → sin target → OK
    if len(shares) != len(assets):
        raise ValueError("Si se define target_share, todos los activos deben tenerlo")
    total = sum(shares)
    if abs(total - 100.0) > 0.01:
        raise ValueError(f"Los target_share deben sumar 100 (suma actual: {round(total, 2)})")


class CreatePortfolioRequest(BaseModel):
    name: str
    description: str | None = None
    assets: list[PortfolioAssetInput] = []

    @model_validator(mode="after")
    def validate_shares(self) -> "CreatePortfolioRequest":
        _validate_asset_shares(self.assets)
        return self


class UpdatePortfolioRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    assets: list[PortfolioAssetInput] | None = None

    @model_validator(mode="after")
    def validate_shares(self) -> "UpdatePortfolioRequest":
        if self.assets is not None:
            _validate_asset_shares(self.assets)
        return self
