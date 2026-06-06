from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class Platform(str, Enum):
    COCOS = "COCOS"
    IOL = "IOL"
    MERCADO_PAGO = "MERCADO_PAGO"
    PROMETEO = "PROMETEO"


class AccountStatus(str, Enum):
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"
    PENDING = "PENDING"
    DISCONNECTED = "DISCONNECTED"


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


class LinkedAccount(BaseModel):
    id: str
    platform: Platform
    label: str
    status: AccountStatus
    last_sync_at: datetime | None
    error_message: str | None = None


class LinkAccountRequest(BaseModel):
    platform: Platform
    credentials: dict[str, str]
