from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from .account import Platform


class AssetType(str, Enum):
    CEDEAR = "cedear"
    BONO = "bono"
    FCI = "fci"
    CASH = "cash"
    CRYPTO = "crypto"
    STOCK = "stock"


class Currency(str, Enum):
    ARS = "ARS"
    USD = "USD"


class Asset(BaseModel):
    ticker: str
    name: str | None = None          # assets.external_name
    asset_type: AssetType | None = None
    platform: Platform | None = None
    currency: Currency | None = None
    account_id: str
    quantity: float
    unit_price: float | None = None
    total_valuation: float | None = None
    recorded_at: datetime | None = None
