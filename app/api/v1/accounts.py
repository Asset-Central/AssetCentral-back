from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_user
from app.schemas.account import Account, LinkAccountRequest, PlatformConfig
from app.services.account_service import AccountService

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/platforms", response_model=list[PlatformConfig])
async def get_platform_configs():
    """Devuelve la configuración de campos de credenciales por plataforma."""
    return AccountService.get_platform_configs()


@router.get("", response_model=list[Account])
async def list_accounts(user=Depends(get_current_user)):
    return await AccountService.list_accounts(user_id=user.id)


@router.post("", response_model=Account, status_code=status.HTTP_201_CREATED)
async def link_account(body: LinkAccountRequest, user=Depends(get_current_user)):
    return await AccountService.link_account(user_id=user.id, data=body)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_account(account_id: str, user=Depends(get_current_user)):
    await AccountService.unlink_account(user_id=user.id, account_id=account_id)
