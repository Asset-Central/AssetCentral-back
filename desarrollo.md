# Plan Arquitectónico — AssetCentral Backend

## 0. Contexto: Lo que el Frontend espera

El frontend (Lit 3 + TypeScript) ya define los tipos y endpoints que necesitamos cumplir:

| Módulo | Endpoints requeridos |
| :--- | :--- |
| **Accounts** | `GET/POST /api/accounts`, `DELETE /api/accounts/{id}` |
| **Assets** | `GET /api/assets` (consolidados de todas las cuentas) |
| **Portfolios** | `GET/POST /api/portfolios`, `GET /api/portfolios/{id}/summary`, `PATCH/DELETE /api/portfolios/{id}` |

---

## 1. Arquitectura de Carpetas

```text
back/
├── app/
│   ├── main.py                      # FastAPI entry point, CORS, routers
│   ├── core/
│   │   ├── config.py                # Settings via pydantic-settings (.env)
│   │   ├── supabase.py              # Cliente Supabase (admin + anon)
│   │   ├── security.py              # Cifrado AES-256-GCM, envelope encryption
│   │   └── dependencies.py          # get_current_user() — verifica JWT Supabase
│   ├── api/
│   │   └── v1/
│   │       ├── router.py            # Agrega accounts + assets + portfolios
│   │       ├── accounts.py          # Endpoints de cuentas vinculadas
│   │       ├── assets.py            # Endpoints de activos consolidados
│   │       └── portfolios.py        # Endpoints de portfolios
│   ├── schemas/
│   │   ├── account.py               # LinkedAccount, LinkAccountRequest
│   │   ├── asset.py                 # Asset, AssetType, Platform
│   │   └── portfolio.py             # Portfolio, PortfolioSummary
│   ├── services/
│   │   ├── account_service.py       # Lógica: vincular/desvincular cuentas
│   │   ├── asset_service.py         # Agrega activos de todos los conectores
│   │   ├── portfolio_service.py     # CRUD portfolios + cálculo de valuación
│   │   ├── encryption_service.py    # Envelope encryption por usuario
│   │   └── connectors/
│   │       ├── base.py              # Interfaz abstracta: get_assets() -> Asset[]
│   │       ├── cocos.py             # Conector Cocos Capital (Real o Mock)
│   │       ├── iol.py               # Conector InvertirOnline (Real o Mock)
│   │       ├── mercadopago.py       # Conector Mercado Pago (Real o Mock)
│   │       └── prometeo.py          # Conector Prometeo (Real o Mock)
│   └── mcp/
│       ├── server.py                # Servidor MCP para el agente propio de la IA
│       └── tools.py                 # Tools: get_portfolio, get_assets, get_summary
├── migrations/
│   └── 001_initial_schema.sql       # Schema completo de Supabase
├── tests/
│   ├── conftest.py
│   ├── test_accounts.py
│   └── test_portfolios.py
├── .env.example
├── requirements.txt
├── Dockerfile
└── README.md

2. Esquema de Base de Datos (Supabase/PostgreSQL)
SQL

-- Extiende auth.users de Supabase
CREATE TABLE public.user_vaults (
    user_id       UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    dek_encrypted TEXT NOT NULL,  -- Data Encryption Key cifrada con master key
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Cuentas vinculadas a brokers
CREATE TABLE public.linked_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    platform        TEXT NOT NULL CHECK (platform IN ('COCOS','IOL','MERCADO_PAGO','PROMETEO')),
    label           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING' 
                          CHECK (status IN ('CONNECTED','ERROR','PENDING','DISCONNECTED')),
    credentials_enc TEXT NOT NULL,   -- JSON cifrado con DEK del usuario
    last_sync_at    TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Cache de activos (resultado de sincronizar con brokers)
CREATE TABLE public.asset_snapshots (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id        UUID NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    ticker            TEXT NOT NULL,
    name              TEXT NOT NULL,
    asset_type        TEXT NOT NULL,   -- CEDEAR, BONO, FCI, USD, ACCION, CRYPTO, OTRO
    quantity          NUMERIC NOT NULL,
    price_ars         NUMERIC NOT NULL,
    price_usd         NUMERIC,
    total_ars         NUMERIC NOT NULL,
    total_usd         NUMERIC,
    daily_change_pct  NUMERIC DEFAULT 0,
    snapshot_at       TIMESTAMPTZ DEFAULT now()
);

-- Portfolios (agrupaciones personalizadas del usuario)
CREATE TABLE public.portfolios (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Relación portfolio ↔ activos (por ticker + plataforma)
CREATE TABLE public.portfolio_assets (
    portfolio_id    UUID REFERENCES portfolios(id) ON DELETE CASCADE,
    asset_id        UUID REFERENCES asset_snapshots(id) ON DELETE CASCADE,
    PRIMARY KEY (portfolio_id, asset_id)
);

-- RLS: cada usuario solo ve sus propias filas
ALTER TABLE linked_accounts   ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_snapshots   ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolios        ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_assets  ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_vaults       ENABLE ROW LEVEL SECURITY;

3. Diseño de Seguridad: Envelope Encryption

Este es el punto más crítico. El esquema garantiza que una filtración de la base de datos sola no expone las credenciales.
Plaintext

 Master Key (env var, NUNCA en DB)
        │
        ▼
 ┌─────────────────────────────────┐
 │ Por usuario:                    │
 │ DEK (Data Encryption Key)       │ ← clave aleatoria de 32 bytes
 │ almacenada cifrada con          │
 │ AES-256-GCM(master_key, DEK)    │
 └─────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────┐
 │ Credenciales del broker:        │
 │ cifradas con                    │
 │ AES-256-GCM(DEK, credentials)   │
 └─────────────────────────────────┘

Flujo:

    Usuario se registra → se genera DEK aleatorio → se cifra con master key → se guarda dek_encrypted en user_vaults.

    Usuario vincula cuenta → backend descifra DEK usando master key → cifra las credenciales con DEK → guarda en DB.

    Usuario consulta activos → backend descifra DEK → descifra credenciales → llama al broker → retorna datos.

Ventajas:

    Cross-device nativo (las credenciales están en DB, cifradas).

    Si se filtra la DB: sin el MASTER_ENCRYPTION_KEY del .env, los datos son ilegibles.

    Aislamiento total entre usuarios (cada uno tiene su propia DEK).

4. Diseño del Servidor MCP (Integración con Agente Propio)

Como el servidor MCP va a ser consumido por un agente de IA propio, se montará localmente en el mismo entorno FastAPI.
Plaintext

app/mcp/
├── server.py      # Monta el servidor en /mcp (endpoint SSE)
└── tools.py       # Expone tools para IA:
                   #   - get_financial_summary(user_id)
                   #   - get_assets(user_id, filters?)
                   #   - get_portfolio(user_id, portfolio_id)
                   #   - get_allocation_by_type(user_id)

5. Orden Lógico de Implementación (Hackatón)

Estrategia: Arrancar directamente con la base core del proyecto (Fases 0 a 3) para habilitar al frontend rápido. Supabase ya está creado y el backend correrá de forma local. Los conectores sin API asegurada se mockearán inicialmente.

    FASE 0 — Scaffolding: pyproject.toml / requirements.txt, .env.example, config.py.

    FASE 1 — Core: Supabase + Seguridad:

        core/supabase.py

        core/security.py

        core/dependencies.py

        migrations/001_initial_schema.sql

    FASE 2 — Esqueleto FastAPI:

        main.py (CORS configurado para el front en localhost:5173).

        api/v1/router.py y Schemas Pydantic.

    FASE 3 — Accounts (Base):

        services/encryption_service.py

        services/account_service.py

        api/v1/accounts.py

    FASE 4 — Conector Base + Mix (Mock/Real):

        services/connectors/base.py

        Implementar la primera integración con la API que ya se tenga acceso (ej. Prometeo) y armar un Mock para otra (ej. Cocos/IOL) para que el frontend pueda ver datos.

    FASE 5 — Assets:

        services/asset_service.py

        api/v1/assets.py

    FASE 6 — Portfolios:

        services/portfolio_service.py

        api/v1/portfolios.py

    FASE 7 — MCP Server (Agente Propio):

        mcp/tools.py

        mcp/server.py

    FASE 8 — Refinamiento de Conectores: Reemplazar los conectores mockeados por implementaciones reales a medida que se consigan las keys de las APIs faltantes.

6. Dependencias Principales
Plaintext

fastapi>=0.115
uvicorn[standard]
pydantic-settings
supabase>=2.0              # cliente oficial Python
cryptography               # AES-256-GCM
httpx                      # requests async para conectores
python-jose[cryptography]  # verificar JWT de Supabase
fastapi-mcp                # servidor MCP integrado en FastAPI
pytest
pytest-asyncio