from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class Platform(str, Enum):
    COCOS = "cocos"
    IOL = "iol"
    MERCADOPAGO = "mercadopago"
    NACION = "nacion"


class ConnectionStatus(str, Enum):
    ACTIVE = "active"
    REQUIRES_REAUTHENTICATION = "requires_reauthentication"
    ERROR = "error"


class CredentialField(BaseModel):
    name: str
    label: str
    type: Literal["text", "password", "email"]
    placeholder: str | None = None


class PlatformConfig(BaseModel):
    platform: Platform
    display_name: str
    logo_url: str
    fields: list[CredentialField]


class Account(BaseModel):
    id: str
    platform: Platform
    label: str | None = None
    connection_status: ConnectionStatus
    last_sync: datetime | None
    error_message: str | None = None


class LinkAccountRequest(BaseModel):
    platform: Platform
    credentials: dict[str, str]
