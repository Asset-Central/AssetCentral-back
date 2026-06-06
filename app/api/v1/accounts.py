from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_user, get_current_user_dek
from app.schemas.account import LinkedAccount, LinkAccountRequest, PlatformConfig
from app.services.account_service import AccountService

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/platforms", response_model=list[PlatformConfig])
async def get_platform_configs():
    """Devuelve la configuración de campos de credenciales por plataforma."""
    return AccountService.get_platform_configs()


@router.get("", response_model=list[LinkedAccount])
async def list_accounts(user=Depends(get_current_user)):
    return await AccountService.list_accounts(user_id=user.id)


@router.post("/link", response_model=LinkedAccount, status_code=status.HTTP_201_CREATED)
async def link_account(
    body: LinkAccountRequest,
    user_and_dek=Depends(get_current_user_dek),
):
    user, dek = user_and_dek
    return await AccountService.link_account(
        user_id=user.id,
        dek=dek,
        platform=body.platform,
        credentials=body.credentials,
    )


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_account(
    account_id: str,
    user=Depends(get_current_user),
):
    await AccountService.unlink_account(user_id=user.id, account_id=account_id)
