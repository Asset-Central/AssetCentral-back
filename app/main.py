from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router
from app.core.config import settings
from app.mcp.server import mount_mcp
from app.services import price_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Arranque
    price_scheduler.start()
    yield
    # Apagado
    price_scheduler.stop()


app = FastAPI(
    title="AssetCentral API",
    version="0.1.0",
    docs_url="/docs" if settings.is_dev else None,
    redoc_url="/redoc" if settings.is_dev else None,
    lifespan=lifespan,
)

origins = [origin.strip() for origin in settings.frontend_url.split(",")] if settings.frontend_url else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
mount_mcp(app)


# Registrar un handler para excepciones no capturadas garantiza que el error
# pase por CORSMiddleware (que corre fuera de ServerErrorMiddleware) y así los
# 500 reciban los headers Access-Control-Allow-Origin correctamente.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
