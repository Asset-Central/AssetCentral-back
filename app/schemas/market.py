from pydantic import BaseModel


class MarketQuote(BaseModel):
    ticker: str
    name: str | None = None
    asset_type: str | None = None
    currency: str | None = None
    exchange: str | None = None
    unit_price: float | None = None
    daily_change_pct: float | None = None
    market_cap: float | None = None


class MarketPricePoint(BaseModel):
    date: str
    price: float
