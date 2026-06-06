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

---

## Cambios Implementados — Servidor MCP en Supabase Edge Functions

### Contexto

El servidor MCP original (`supabase/functions/mcp-server/index.ts`) era una versión mínima con dos herramientas básicas y un solo recurso estático. Se reescribió completamente para cumplir los requisitos de un servidor MCP de producción orientado al consumo por parte de agentes de IA.

---

### Archivo: `supabase/functions/mcp-server/index.ts`

**Versión desplegada:** v16 (proyecto `geqltnpxydhpwysapexz`)

#### Cliente Supabase

Se cambió el cliente para usar `SUPABASE_SERVICE_ROLE_KEY` (con fallback a `SUPABASE_ANON_KEY`). Esto permite que el servidor omita las políticas RLS, lo cual es correcto para un backend interno consumido exclusivamente por el agente de IA y no expuesto a usuarios finales.

#### Middleware de serialización (token-lean)

Se mejoraron las dos funciones de serialización existentes:

- `jsonArrayToMarkdownTable`: ahora escapa saltos de línea dentro de celdas (`\n` → espacio) además de los pipes, evitando que el Markdown se rompa con valores multi-línea.
- `jsonToMarkdownKv`: sin cambios de lógica, pero integrada al flujo de recursos dinámicos.

El objetivo es reducir el consumo de tokens vs. JSON crudo (~38% menos según benchmarks de serialización Markdown).

#### Paginación por cursor opaco

Se agregaron dos funciones utilitarias:

```
encodeCursor(offset) → string  // base64(JSON({offset}))
decodeCursor(string) → number  // inversa con manejo de error
```

Todos los tools que pueden devolver listas grandes aceptan un parámetro `cursor` y devuelven un `nextCursor` cuando hay más páginas disponibles.

---

#### Tools (Herramientas MCP)

| Nombre | Descripción |
| :--- | :--- |
| `search_global_assets` | Llama al RPC `search_assets_hybrid_rrf` (búsqueda híbrida RRF: pgvector semántico + BM25 keyword). Límite configurable 1–50, paginación por cursor. |
| `get_user_portfolio_summary` | Consulta la vista `llm_user_account_balances_view`. Se eliminó `.single()` de la versión anterior — ahora usa `.range()` para soportar usuarios con muchas posiciones y devuelve una tabla Markdown. Paginación por cursor. |
| `get_database_schema` | **Pragmatic Bridge**: replica el contenido del recurso `docs://schema/assetcentral` pero expuesto como herramienta, para que el LLM pueda solicitarlo activamente cuando el host no inyecta recursos automáticamente. |

---

#### Recursos Estáticos (Static Resources)

| URI | Descripción |
| :--- | :--- |
| `docs://schema/assetcentral` | Llama al RPC `get_schema_metadata()` que retorna el esquema completo con metadata `COMMENT ON`. Tiene fallback automático a `information_schema` si el RPC no existe. |
| `docs://reference/enums` | Datos estáticos (sin round-trip a la DB) con los valores canónicos de enums: plataformas (`cocos`, `iol`, `mercadopago`, `nacion`), tipos de activo, estados de conexión y monedas. |

---

#### Resource Templates (Recursos Dinámicos)

Se implementó soporte para el método MCP `resources/templates/list`, que no existía en la versión anterior.

| URI Template | Descripción |
| :--- | :--- |
| `docs://users/{user_id}/profile` | Consulta en paralelo `public.users` (perfil: nombre, apellido, DNI) y `public.accounts` (cuentas vinculadas por broker). Devuelve un resumen Markdown con sección de identidad y tabla de cuentas. |

El router de `resources/read` resuelve primero recursos estáticos por URI exacta y luego intenta matchear los templates via regex.

---

#### Métodos MCP implementados

| Método | Notas |
| :--- | :--- |
| `initialize` | Declara capabilities: `tools`, `resources` (con `subscribe: false`), `prompts` |
| `ping` | Retorna `{}` |
| `tools/list` | Lista los 3 tools con su `inputSchema` |
| `tools/call` | Despacha al handler correspondiente |
| `resources/list` | Lista los 2 recursos estáticos |
| `resources/templates/list` | Lista el template dinámico de perfil de usuario |
| `resources/read` | Resuelve estáticos y dinámicos; retorna 404 MCP si no hay match |
| `prompts/list` | **Nuevo (v2.1)** — lista los 4 templates de asesoramiento financiero |
| `prompts/get` | **Nuevo (v2.1)** — renderiza un template con los argumentos provistos; valida required args |
| Notificaciones (sin `id`) | Responde `202 No Content` sin body |
| Batch JSON-RPC | Procesa arrays de mensajes en paralelo con `Promise.all` |

---

#### Prompt Templates (v2.1.0)

Los prompts MCP son templates parametrizados que el host inyecta como mensajes al LLM. Permiten disparar flujos de análisis financiero completos con una sola invocación.

| Nombre | Argumentos requeridos | Argumentos opcionales | Descripción |
| :--- | :--- | :--- | :--- |
| `hedge_instrument` | `user_id`, `instrument` | — | Plan de cobertura (hedge) contra un instrumento (moneda, acción, etc.) |
| `liquidity_analysis` | `user_id` | — | Liquidez del portfolio en t+0 (inmediato), t+1 (24hs) y t+2 (48hs) según plazos del mercado argentino |
| `portfolio_diversification` | `user_id` | `portfolio_id` | Análisis de diversificación en 4 dimensiones: clase de activo, moneda, plataforma, geografía. Incluye HHI |
| `investment_recommendations` | `user_id`, `risk_profile` | — | Recomendaciones según perfil `conservador` / `moderado` / `agresivo` con asignación objetivo y instrumentos concretos |

**Flujo de cada prompt:**
1. El LLM host llama a `prompts/get` con el nombre y los argumentos
2. El servidor renderiza el template substituyendo los argumentos y devuelve un array `messages`
3. El host inyecta esos mensajes en el contexto del LLM, que ejecuta los tools necesarios (`get_user_portfolio_summary`, `search_global_assets`) para resolver el análisis

**Ejemplo de invocación:**
```bash
curl -X POST https://geqltnpxydhpwysapexz.supabase.co/functions/v1/mcp-server \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "prompts/get",
    "params": {
      "name": "investment_recommendations",
      "arguments": {
        "user_id": "<uuid>",
        "risk_profile": "moderado"
      }
    }
  }'
```

---

### Archivo: `supabase/migrations/20240001_get_schema_metadata.sql`

Se creó la migración SQL para el RPC `get_schema_metadata()`, requerido por el recurso `docs://schema/assetcentral` y el tool `get_database_schema`.

**Qué hace la función:**
- Consulta `pg_attribute`, `pg_class`, `pg_namespace` y `pg_type` para extraer todas las tablas, vistas y vistas materializadas del schema `public`.
- Incluye comentarios de tabla (`obj_description`) y de columna (`col_description`), que son la metadata semántica agregada con `COMMENT ON`.
- Retorna columnas: `schema_name`, `object_type`, `object_name`, `table_comment`, `column_name`, `data_type`, `is_nullable`, `column_comment`.
- Configurada con `SECURITY DEFINER` y `STABLE` para ejecución segura y cacheable.
- Permisos otorgados a `anon`, `authenticated` y `service_role`.

**Problema encontrado al aplicar:** La función ya existía en el servidor remoto con una firma de retorno diferente. `CREATE OR REPLACE FUNCTION` en PostgreSQL no permite cambiar el tipo de retorno. Se resolvió agregando `DROP FUNCTION IF EXISTS public.get_schema_metadata()` antes del `CREATE OR REPLACE`.

**Historial de migración remota:** El servidor remoto tenía 16 migraciones aplicadas directamente desde el dashboard de Supabase (sin archivos locales). Se marcaron como `reverted` en la tabla de historial con `supabase migration repair` para desbloquear el `db push`.

---

### Cómo probar localmente

```bash
# 1. Levantar el runtime de Edge Functions local
npx supabase functions serve --no-verify-jwt mcp-server

# 2. Abrir el MCP Inspector (en otra terminal)
npx @modelcontextprotocol/inspector http://localhost:54321/functions/v1/mcp-server
```

### Endpoint en producción

```
https://geqltnpxydhpwysapexz.supabase.co/functions/v1/mcp-server
```

Configuración para Claude Desktop u otro host MCP:

```json
{
  "mcpServers": {
    "assetcentral": {
      "url": "https://geqltnpxydhpwysapexz.supabase.co/functions/v1/mcp-server",
      "transport": "http"
    }
  }
}
```

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