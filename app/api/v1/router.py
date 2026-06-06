from fastapi import APIRouter

from .accounts import router as accounts_router
from .assets import router as assets_router
from .portfolios import router as portfolios_router

router = APIRouter(prefix="/api")

router.include_router(accounts_router)
router.include_router(assets_router)
router.include_router(portfolios_router)
