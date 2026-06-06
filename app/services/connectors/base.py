from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.schemas.asset import AssetType, Currency
from app.schemas.account import Platform


@dataclass
class Holding:
    """Posición de un activo en la cuenta de un broker."""
    ticker: str
    external_name: str
    asset_type: AssetType
    currency: Currency
    platform: Platform
    quantity: float
    unit_price: float | None
    total_valuation: float


class BaseConnector(ABC):

    def __init__(self, account_id: str, credentials: dict):
        self.account_id = account_id
        self.credentials = credentials

    @abstractmethod
    async def get_holdings(self) -> list[Holding]:
        """
        Obtiene las posiciones actuales de la cuenta del broker.
        Lanza ConnectorError si hay un problema de autenticación o API.
        """
        ...

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Verifica que las credenciales sean válidas sin traer todos los activos."""
        ...


class ConnectorError(Exception):
    """Error al conectar o autenticar con un broker."""
    pass
