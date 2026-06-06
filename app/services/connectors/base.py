"""
Interfaz abstracta que todo conector de broker debe implementar.
"""

from abc import ABC, abstractmethod

from app.schemas.asset import Asset


class BaseConnector(ABC):

    def __init__(self, account_id: str, credentials: dict):
        self.account_id = account_id
        self.credentials = credentials

    @abstractmethod
    async def get_assets(self) -> list[Asset]:
        """
        Obtiene los activos de la cuenta del broker.
        Debe retornar una lista de Asset con todos los campos calculados.
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
