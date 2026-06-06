"""
Conector mock — devuelve datos hardcodeados.
Usar mientras no esté implementado el conector real de una plataforma.
"""

from app.schemas.account import Platform
from app.schemas.asset import AssetType, Currency

from .base import BaseConnector, Holding

MOCK_DATA: dict[str, list[dict]] = {
    "cocos": [
        {"ticker": "GGAL", "name": "Grupo Financiero Galicia", "type": AssetType.CEDEAR,
         "currency": Currency.ARS, "quantity": 10, "unit_price": 4200.0},
        {"ticker": "AAPL", "name": "Apple Inc.", "type": AssetType.CEDEAR,
         "currency": Currency.USD, "quantity": 5, "unit_price": 85.0},
    ],
    "iol": [
        {"ticker": "AL30", "name": "Bono AL30", "type": AssetType.BONO,
         "currency": Currency.USD, "quantity": 100, "unit_price": 62.0},
        {"ticker": "FCI-PREMIER", "name": "FCI Premier Renta", "type": AssetType.FCI,
         "currency": Currency.ARS, "quantity": 1000, "unit_price": 105.0},
    ],
    "mercadopago": [
        {"ticker": "USDT", "name": "Dólar MEP", "type": AssetType.CASH,
         "currency": Currency.USD, "quantity": 500, "unit_price": 1.0},
    ],
    "nacion": [
        {"ticker": "BTC", "name": "Bitcoin", "type": AssetType.CRYPTO,
         "currency": Currency.USD, "quantity": 0.01, "unit_price": 95000.0},
    ],
}


class MockConnector(BaseConnector):

    async def get_holdings(self) -> list[Holding]:
        platform_key = self.credentials.get("_mock_platform", "cocos")
        items = MOCK_DATA.get(platform_key, [])
        return [
            Holding(
                ticker=item["ticker"],
                external_name=item["name"],
                asset_type=item["type"],
                currency=item["currency"],
                platform=Platform(platform_key),
                quantity=float(item["quantity"]),
                unit_price=float(item["unit_price"]),
                total_valuation=float(item["quantity"]) * float(item["unit_price"]),
            )
            for item in items
        ]

    async def validate_credentials(self) -> bool:
        return True
