import { createClient } from "npm:@supabase/supabase-js@2";

// ==========================================
// Supabase Client
// Service-role key bypasses RLS — safe here
// because this Edge Function is the AI agent's
// internal backend (no user-facing exposure).
// ==========================================

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const supabaseKey =
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ??
  Deno.env.get("SUPABASE_ANON_KEY") ??
  "";
const supabase = createClient(supabaseUrl, supabaseKey, {
  auth: { persistSession: false },
});

// ==========================================
// Token-Lean Serialization Middleware
// Reduces token consumption vs raw JSON by ~38%
// ==========================================

function jsonArrayToMarkdownTable(rows: Record<string, unknown>[]): string {
  if (!rows || rows.length === 0) return "_No data found._";
  const keys = Object.keys(rows[0]);
  const header = `| ${keys.join(" | ")} |`;
  const divider = `| ${keys.map(() => "---").join(" | ")} |`;
  const body = rows
    .map((row) => {
      const cells = keys.map((k) => {
        let v = row[k];
        if (v === null || v === undefined) return "";
        if (typeof v === "object") v = JSON.stringify(v);
        return String(v).replace(/\|/g, "\\|").replace(/\n/g, " ");
      });
      return `| ${cells.join(" | ")} |`;
    })
    .join("\n");
  return `${header}\n${divider}\n${body}`;
}

function jsonToMarkdownKv(obj: Record<string, unknown>): string {
  if (!obj) return "_No data found._";
  return Object.entries(obj)
    .map(([k, v]) => {
      if (typeof v === "object" && v !== null) v = JSON.stringify(v);
      return `**${k}:** ${v ?? ""}`;
    })
    .join("\n");
}

// ==========================================
// CORS
// ==========================================

// Extracts the `sub` claim from a JWT without verifying the signature.
// Supabase already verified the JWT before the request reaches this function
// (verify_jwt: true), so signature verification here is redundant.
function decodeJwtSub(token: string): string | null {
  try {
    const [, payload] = token.split(".");
    const decoded = JSON.parse(
      atob(payload.replace(/-/g, "+").replace(/_/g, "/")),
    );
    return (decoded.sub as string) ?? null;
  } catch {
    return null;
  }
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept, mcp-session-id, Authorization",
  "Access-Control-Expose-Headers": "mcp-session-id",
};

// ==========================================
// MCP Protocol Helpers
// ==========================================

const PROTOCOL_VERSION = "2024-11-05";

function ok(id: string | number | null, result: unknown): Response {
  return new Response(JSON.stringify({ jsonrpc: "2.0", id, result }), {
    headers: { "Content-Type": "application/json", ...CORS_HEADERS },
  });
}

function mcpErr(
  id: string | number | null,
  code: number,
  message: string,
): Response {
  return new Response(
    JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }),
    { headers: { "Content-Type": "application/json", ...CORS_HEADERS } },
  );
}

// ==========================================
// Type Definitions
// ==========================================

interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
  isError?: boolean;
}

interface ToolDef {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  // jwtUserId is the authenticated user extracted from the JWT.
  // User-scoped tools use it instead of accepting user_id as an argument.
  handler: (args: Record<string, unknown>, jwtUserId: string | null) => Promise<ToolResult>;
}

interface ResourceDef {
  name: string;
  uri: string;
  description: string;
  mimeType: string;
  handler: (jwtUserId: string | null) => Promise<{ contents: Array<{ uri: string; text: string }> }>;
}

interface ResourceTemplateDef {
  name: string;
  uriTemplate: string;
  description: string;
  mimeType: string;
  pattern: RegExp;
  handler: (
    params: Record<string, string>,
    jwtUserId: string | null,
  ) => Promise<{ contents: Array<{ uri: string; text: string }> }>;
}

interface PromptArgument {
  name: string;
  description: string;
  required: boolean;
}

interface PromptMessage {
  role: "user" | "assistant";
  content: { type: "text"; text: string };
}

interface PromptDef {
  name: string;
  description: string;
  arguments: PromptArgument[];
  render: (args: Record<string, string>, jwtUserId: string) => PromptMessage[];
}

// ==========================================
// Pagination Helpers
// ==========================================

function encodeCursor(offset: number): string {
  return btoa(JSON.stringify({ offset }));
}

function decodeCursor(cursor: string): number {
  try {
    return JSON.parse(atob(cursor)).offset ?? 0;
  } catch {
    return 0;
  }
}


// ==========================================
// Schema Fetcher (shared by tool + resource)
// ==========================================

async function fetchSchemaMarkdown(): Promise<string> {
  // Try the dedicated RPC first (returns rich COMMENT ON metadata).
  // Fall back to information_schema if the RPC does not exist yet.
  const { data, error } = await supabase.rpc("get_schema_metadata");
  if (!error && data) {
    return [
      "# AssetCentral Database Schema\n",
      jsonArrayToMarkdownTable(data as Record<string, unknown>[]),
    ].join("\n");
  }

  // Fallback: query information_schema directly
  const { data: cols, error: colsErr } = await supabase
    .from("information_schema.columns" as never)
    .select(
      "table_schema, table_name, column_name, data_type, is_nullable, column_default",
    )
    .eq("table_schema", "public")
    .order("table_name")
    .order("ordinal_position");

  if (colsErr) {
    return `_Schema unavailable: ${colsErr.message}. Ensure the \`get_schema_metadata\` RPC exists (see migration 20240001_get_schema_metadata.sql)._`;
  }
  return [
    "# AssetCentral Database Schema (information_schema fallback)\n",
    jsonArrayToMarkdownTable((cols ?? []) as Record<string, unknown>[]),
  ].join("\n");
}

// ==========================================
// Tool Definitions
// ==========================================

const TOOLS: ToolDef[] = [
  // ------------------------------------------
  // 1. Hybrid RRF Search
  // ------------------------------------------
  {
    name: "search_global_assets",
    description:
      "Performs a Reciprocal Rank Fusion (RRF) hybrid search (pgvector semantic + BM25 keyword) across all global assets. " +
      "Returns a Markdown table of results. Supports opaque cursor-based pagination via `cursor`/`nextCursor`.",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Natural-language or keyword search query",
        },
        limit: {
          type: "number",
          description: "Max results per page (1–50, default 10)",
          default: 10,
        },
        cursor: {
          type: "string",
          description:
            "Opaque pagination cursor returned as `nextCursor` in a previous response",
        },
        query_embedding: {
          type: "array",
          items: { type: "number" },
          description:
            "Optional pre-computed 1536-dim embedding vector. When provided activates the vector leg of RRF (BM25 + vector). Omit to use BM25 + trigram only.",
        },
      },
      required: ["query"],
    },
    handler: async ({ query, limit = 10, cursor, query_embedding }, _jwtUserId) => {
      const safeLimit = Math.min(Math.max(Number(limit) || 10, 1), 50);
      const offset = cursor ? decodeCursor(String(cursor)) : 0;
      const embedding = Array.isArray(query_embedding) ? query_embedding : null;
      const mode = embedding ? "hybrid RRF (BM25 + vector)" : "BM25 / trigram";

      const { data, error } = await supabase.rpc("search_assets_hybrid_rrf", {
        search_query: query,
        query_embedding: embedding,
        page_limit: safeLimit,
        offset_val: offset,
      });

      if (error) {
        return {
          content: [
            {
              type: "text",
              text: `**Search failed:** ${error.message}\n\n_Ensure the \`search_assets_hybrid_rrf\` RPC exists (migration 20240002)._`,
            },
          ],
          isError: true,
        };
      }

      const results = (data ?? []) as Record<string, unknown>[];
      const table = jsonArrayToMarkdownTable(results);
      const hasMore = results.length === safeLimit;
      const nextCursor = hasMore
        ? `\n\n**nextCursor:** \`${encodeCursor(offset + safeLimit)}\``
        : "";

      return {
        content: [
          {
            type: "text",
            text: `## Asset Search Results\n\n**Query:** ${query}  \n**Mode:** ${mode}  \n**Showing:** ${results.length} result(s) (offset ${offset})\n\n${table}${nextCursor}`,
          },
        ],
      };
    },
  },

  // ------------------------------------------
  // 2. Portfolio / Account Balance Summary
  // ------------------------------------------
  {
    name: "get_user_portfolio_summary",
    description:
      "Returns a flattened financial snapshot for the authenticated user from the `llm_user_account_balances_view` denormalized view. " +
      "No complex JOINs required. Supports opaque cursor-based pagination for users with many positions.",
    inputSchema: {
      type: "object",
      properties: {
        limit: {
          type: "number",
          description: "Max rows to return (default 50)",
          default: 50,
        },
        cursor: {
          type: "string",
          description: "Opaque pagination cursor",
        },
      },
      required: [],
    },
    handler: async ({ limit = 50, cursor }, jwtUserId) => {
      if (!jwtUserId) {
        return {
          content: [{ type: "text", text: "**Unauthorized:** valid JWT required." }],
          isError: true,
        };
      }
      const safeLimit = Math.min(Math.max(Number(limit) || 50, 1), 200);
      const offset = cursor ? decodeCursor(String(cursor)) : 0;

      const { data, error } = await supabase
        .from("llm_user_account_balances_view")
        .select("*")
        .eq("user_id", jwtUserId)
        .range(offset, offset + safeLimit - 1);

      if (error) {
        const msg =
          error.code === "42P01"
            ? "View `llm_user_account_balances_view` does not exist. Run the schema migration."
            : `Query failed: ${error.message}`;
        return {
          content: [{ type: "text", text: `**Error:** ${msg}` }],
          isError: true,
        };
      }

      const rows = (data ?? []) as Record<string, unknown>[];
      if (rows.length === 0) {
        return {
          content: [{ type: "text", text: `_No portfolio data found._` }],
        };
      }

      const table = jsonArrayToMarkdownTable(rows);
      const hasMore = rows.length === safeLimit;
      const nextCursor = hasMore
        ? `\n\n**nextCursor:** \`${encodeCursor(offset + safeLimit)}\``
        : "";

      return {
        content: [
          {
            type: "text",
            text: `## Portfolio Summary\n\n${table}${nextCursor}`,
          },
        ],
      };
    },
  },

  // ------------------------------------------
  // 3. Pragmatic Bridge — Database Schema
  // Same data as docs://schema/assetcentral but
  // callable as a tool so the LLM can request it
  // even when the host doesn't inject resources.
  // ------------------------------------------
  {
    name: "get_database_schema",
    description:
      "Fetches the full AssetCentral database schema including table/column names, types, and semantic COMMENT ON metadata. " +
      "Use this when you need to understand the data model before writing queries or interpreting results.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
    handler: async (_args, _jwtUserId) => {
      const text = await fetchSchemaMarkdown();
      return { content: [{ type: "text", text }] };
    },
  },

  // ------------------------------------------
  // 4. User Financial Profile
  // Reads the self-declared financial profile
  // stored in users.financial_profile (JSONB).
  // Fields: age, monthly_income_ars,
  // savings_capacity_ars, risk_aversion,
  // investment_horizon_months, goals,
  // currency_preference.
  // ------------------------------------------
  {
    name: "get_user_financial_profile",
    description:
      "Returns the self-declared financial profile for the authenticated user (age, monthly income, savings capacity, risk aversion, " +
      "investment horizon, financial goals, currency preference). " +
      "Use this context to personalise investment recommendations. " +
      "Returns a message if the user has not yet filled in their profile.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
    handler: async (_args, jwtUserId) => {
      if (!jwtUserId) {
        return {
          content: [{ type: "text", text: "**Unauthorized:** valid JWT required." }],
          isError: true,
        };
      }

      const { data, error } = await supabase
        .from("users")
        .select("financial_profile")
        .eq("id", jwtUserId)
        .maybeSingle();

      if (error) {
        return {
          content: [{ type: "text", text: `**Error:** ${error.message}` }],
          isError: true,
        };
      }
      if (!data) {
        return {
          content: [{ type: "text", text: `_User not found._` }],
        };
      }

      const profile = data.financial_profile as Record<string, unknown> | null;
      if (!profile || Object.keys(profile).length === 0) {
        return {
          content: [
            {
              type: "text",
              text: `_Financial profile not completed yet._`,
            },
          ],
        };
      }

      return {
        content: [
          {
            type: "text",
            text: `## Financial Profile\n\n${jsonToMarkdownKv(profile)}`,
          },
        ],
      };
    },
  },
];

// ==========================================
// Static Resource Definitions
// ==========================================

// Known enums — kept as static data so the
// resource loads instantly without a DB round-trip.
const ENUM_REFERENCE = `# AssetCentral Reference Data

## Platforms (broker integrations)

| value | display_name | notes |
| --- | --- | --- |
| cocos | Cocos Capital | Argentine broker |
| iol | InvertirOnline | Argentine broker |
| mercadopago | Mercado Pago | Digital wallet / investment fund |
| nacion | Banco Nación | State-owned bank |

## Asset Types

| value | description |
| --- | --- |
| cedear | Certificate of Deposit for Foreign Shares (ARS-traded US stocks) |
| bono | Government or corporate bond |
| fci | Fondo Común de Inversión (mutual fund) |
| cash | Cash balance in ARS or USD |
| crypto | Cryptocurrency |
| stock | Domestic equity |

## Account Connection Statuses

| value | meaning |
| --- | --- |
| active | Credentials valid, sync succeeds |
| requires_reauthentication | Session expired, user must re-enter credentials |
| error | Sync failed, see error_message for details |

## Currencies

| value | description |
| --- | --- |
| ARS | Argentine Peso |
| USD | US Dollar |
`;

const STATIC_RESOURCES: ResourceDef[] = [
  {
    name: "assetcentral-schema",
    uri: "docs://schema/assetcentral",
    description:
      "Full AssetCentral PostgreSQL schema with COMMENT ON semantic metadata — tables, views, columns and types.",
    mimeType: "text/markdown",
    handler: async (_jwtUserId) => {
      const text = await fetchSchemaMarkdown();
      return { contents: [{ uri: "docs://schema/assetcentral", text }] };
    },
  },
  {
    name: "enums-reference",
    uri: "docs://reference/enums",
    description:
      "Canonical enum values for platforms, asset types, connection statuses and currencies used across AssetCentral.",
    mimeType: "text/markdown",
    handler: async (_jwtUserId) => ({
      contents: [{ uri: "docs://reference/enums", text: ENUM_REFERENCE }],
    }),
  },
];

// ==========================================
// Dynamic Resource Templates
// ==========================================

const RESOURCE_TEMPLATES: ResourceTemplateDef[] = [
  {
    name: "user-profile",
    uriTemplate: "docs://users/{user_id}/profile",
    description:
      "Markdown summary of a specific user's profile and linked account overview. " +
      "Replace {user_id} with the target user's UUID.",
    mimeType: "text/markdown",
    pattern: /^docs:\/\/users\/([0-9a-f-]{36})\/profile$/i,
    handler: async ({ user_id }, jwtUserId) => {
      const uri = `docs://users/${user_id}/profile`;

      if (jwtUserId && user_id !== jwtUserId) {
        return {
          contents: [{ uri, text: "_Forbidden: you can only read your own profile._" }],
        };
      }

      // Fetch user profile from public.users
      const [userResult, accountsResult] = await Promise.all([
        supabase
          .from("users")
          .select("id, full_name, nombre, apellido, dni, created_at")
          .eq("id", user_id)
          .maybeSingle(),
        supabase
          .from("account")
          .select("id, platform, label, connection_status, last_sync, error_message")
          .eq("user_id", user_id)
          .order("platform"),
      ]);

      const sections: string[] = [`# User Profile — \`${user_id}\`\n`];

      if (userResult.error || !userResult.data) {
        sections.push(
          `_User not found or profile table unavailable: ${userResult.error?.message ?? "no row"}_\n`,
        );
      } else {
        sections.push("## Identity\n");
        sections.push(jsonToMarkdownKv(userResult.data as Record<string, unknown>));
        sections.push("");
      }

      if (!accountsResult.error && accountsResult.data) {
        const accounts = accountsResult.data as Record<string, unknown>[];
        sections.push("\n## Linked Broker Accounts\n");
        sections.push(
          accounts.length > 0
            ? jsonArrayToMarkdownTable(accounts)
            : "_No linked accounts._",
        );
      }

      return { contents: [{ uri, text: sections.join("\n") }] };
    },
  },
];

// ==========================================
// Prompt Template Definitions
// ==========================================

const PROMPTS: PromptDef[] = [
  // ------------------------------------------
  // 1. Cobertura (Hedging) de un instrumento
  // ------------------------------------------
  {
    name: "hedge_instrument",
    description:
      "Genera un plan de cobertura (hedge) para el portfolio del usuario autenticado frente a un instrumento específico " +
      "(moneda, acción, bono, etc.). Analiza la exposición actual y sugiere instrumentos de cobertura disponibles " +
      "en el mercado argentino.",
    arguments: [
      {
        name: "instrument",
        description:
          "Instrumento o activo a cubrir (ej: 'dólar', 'GGAL', 'BTC', 'ARS', 'YPF')",
        required: true,
      },
    ],
    render: ({ instrument }, jwtUserId) => [
      {
        role: "user",
        content: {
          type: "text",
          text: `Necesito construir una estrategia de cobertura (hedge) para el portfolio del usuario autenticado frente al instrumento **${instrument}**.

Seguí estos pasos en orden:

1. **Relevá el portfolio actual**
   Llamá a \`get_user_portfolio_summary\` (el user_id viene del JWT autenticado).
   Identificá todas las posiciones expuestas directa o indirectamente a **${instrument}**:
   - Exposición directa: posiciones en el propio instrumento
   - Exposición correlacionada: activos con alta correlación histórica (ej: acciones del mismo sector, bonos en la misma moneda)

2. **Cuantificá la exposición**
   Calculá el monto total expuesto en ARS y USD.
   Indicá qué porcentaje del portfolio total representa.

3. **Buscá instrumentos de cobertura**
   Llamá a \`search_global_assets\` con queries relevantes para encontrar:
   - Instrumentos inversos o de baja correlación con **${instrument}**
   - En el mercado argentino: considera MEP/CCL para exposición al dólar, CEDEAR de sectores defensivos, bonos CER o atados al tipo de cambio, contratos de futuros en ROFEX/MatBA, FCIs con estrategia de cobertura
   - Criterio de liquidez: preferir instrumentos con settlement T+0 o T+1 para flexibilidad

4. **Elaborá el plan de cobertura**
   Presentá el resultado con:
   - **Exposición actual**: monto en ARS y USD, % del portfolio
   - **Instrumentos de cobertura recomendados**: ticker, nombre, tipo, ratio de cobertura sugerido (ej: 1:1, 0.5:1)
   - **Monto a asignar por instrumento** para lograr cobertura completa o parcial
   - **Costo estimado de la cobertura** (spread, costo de carry si aplica)
   - **Riesgos residuales** después de aplicar la cobertura
   - **Horizonte temporal recomendado** para revisar la estrategia`,
        },
      },
    ],
  },

  // ------------------------------------------
  // 2. Análisis de liquidez (t+0 / t+1 / t+2)
  // ------------------------------------------
  {
    name: "liquidity_analysis",
    description:
      "Analiza la liquidez del portfolio del usuario autenticado según los plazos de liquidación del mercado argentino: " +
      "disponible ahora (t+0), en 24hs (t+1) y en 48hs (t+2). Separa el capital líquido del ilíquido.",
    arguments: [],
    render: (_args, _jwtUserId) => [
      {
        role: "user",
        content: {
          type: "text",
          text: `Analizá la liquidez del portfolio del usuario autenticado en los tres horizontes temporales del mercado argentino.

**Paso 1 — Obtené el portfolio completo**
Llamá a \`get_user_portfolio_summary\` (el user_id viene del JWT autenticado).
Si hay un campo \`nextCursor\`, paginá hasta obtener todas las posiciones.

**Paso 2 — Clasificá cada instrumento por horizonte de liquidación**

Usá la siguiente tabla de referencia del mercado argentino:

| Horizonte | Tipo de activo | Ejemplos |
|-----------|---------------|---------|
| **t+0 (Inmediato)** | Saldo en efectivo ARS/USD, stablecoins (USDT/USDC), FCIs money market (rescate el mismo día), saldo Mercado Pago | ARS-CASH, USDT, USDC, Fima Premium, Premier Renta Plus |
| **t+1 (24hs)** | Acciones BYMA en rueda de 24hs, Letras del Tesoro (LECAP), Letras en USD (LETES), algunos FCIs de renta fija | GGAL, YPF, PAMP, LECAP, LETES |
| **t+2 (48hs)** | CEDEARs, Obligaciones Negociables corporativas, Bonos soberanos en USD (AL30, GD30, AE38), Bonos CER/Duales | AAPL, MSFT, AL30, GD30, TX28, BONCER |
| **Ilíquido / No aplica** | Crypto en wallets no custodias, activos sin precio de mercado, posiciones bloqueadas | BTC en cold wallet, acciones no negociadas |

**Paso 3 — Calculá los totales por horizonte**

Para cada horizonte, calculá:
- Valor total en ARS
- Valor total en USD (usá el tipo de cambio implícito del portfolio si está disponible, o indicá que es aproximado)
- % del portfolio total

**Paso 4 — Presentá el cuadro de liquidez escalonada**

| Horizonte | Instrumentos | Valor ARS | Valor USD | % Portfolio |
|-----------|-------------|-----------|-----------|-------------|
| Disponible ahora (t+0) | ... | ... | ... | ...% |
| En 24hs (t+1) | ... | ... | ... | ...% |
| En 48hs (t+2) | ... | ... | ... | ...% |
| **Acumulado en 48hs** | ... | ... | ... | ...% |
| Ilíquido / Sin precio | ... | ... | ... | ...% |

Incluí también:
- Un párrafo de **interpretación**: ¿tiene el usuario suficiente liquidez inmediata para emergencias? ¿Está sobre-concentrado en activos ilíquidos?
- **Recomendación**: si la liquidez t+0 representa menos del 10% del portfolio, sugerí acciones concretas para mejorarla.`,
        },
      },
    ],
  },

  // ------------------------------------------
  // 3. Evaluación de diversificación
  // ------------------------------------------
  {
    name: "portfolio_diversification",
    description:
      "Evalúa el nivel de diversificación del portfolio del usuario autenticado en cuatro dimensiones: clase de activo, " +
      "moneda, plataforma/broker y exposición geográfica. Calcula índice de concentración y sugiere mejoras.",
    arguments: [
      {
        name: "portfolio_id",
        description:
          "UUID de un portfolio específico (opcional; si se omite, analiza todas las cuentas del usuario)",
        required: false,
      },
    ],
    render: ({ portfolio_id }, _jwtUserId) => [
      {
        role: "user",
        content: {
          type: "text",
          text: `Realizá un análisis de diversificación del portfolio${portfolio_id ? ` \`${portfolio_id}\`` : " completo"} del usuario autenticado.

**Paso 1 — Obtené todas las posiciones**
Llamá a \`get_user_portfolio_summary\`${portfolio_id ? ` y filtrá las filas con \`portfolio_id="${portfolio_id}"\`` : ""}.
Paginá si hay \`nextCursor\` hasta tener el portfolio completo.

**Paso 2 — Analizá 4 dimensiones de diversificación**

**Dimensión A — Clase de activo** (columna \`asset_type\`)
Calculá el % del valor total para cada tipo:
- \`stock\`: Acciones argentinas (BYMA)
- \`cedear\`: Certificados de Depósito de Acciones Extranjeras
- \`bono\`: Bonos soberanos, sub-soberanos y corporativos
- \`fci\`: Fondos Comunes de Inversión
- \`crypto\`: Criptomonedas
- \`cash\`: Efectivo / saldos en cuenta

**Dimensión B — Moneda** (columna \`currency\`)
Separá en: ARS, USD y equivalentes (stablecoins en USD).
Calculá el ratio ARS:USD del portfolio.

**Dimensión C — Plataforma / Broker** (columna \`platform\`)
Calculá la distribución entre: \`cocos\`, \`iol\`, \`mercadopago\`, \`nacion\`.
Un portfolio con >70% en una sola plataforma tiene riesgo de concentración operacional.

**Dimensión D — Geografía / Mercado**
- Doméstico: stocks BYMA, bonos soberanos/provinciales, LECAP, FCI locales, ARS-CASH
- Internacional: CEDEARs, bonos en USD, crypto, stablecoins

**Paso 3 — Calculá el Índice de Concentración (HHI)**
Para la dimensión de clase de activo:
HHI = Σ (porcentaje_i)² donde porcentaje_i es la participación de cada clase como decimal.
- HHI < 0.15: Bien diversificado
- 0.15 ≤ HHI < 0.25: Moderadamente concentrado
- HHI ≥ 0.25: Alta concentración — riesgo significativo

**Paso 4 — Identificá los principales riesgos**
Lista los 3 mayores riesgos de concentración con su impacto potencial.

**Paso 5 — Sugerí mejoras concretas**
Para cada clase o moneda sub-representada (< 5% del portfolio), llamá a \`search_global_assets\` para sugerir instrumentos específicos disponibles en el catálogo. Priorizá liquidez y accesibilidad desde las plataformas que el usuario ya usa.

**Presentá el resultado con:**
1. Tabla resumen por dimensión
2. Índice HHI con su interpretación
3. Radar de diversificación (descripción textual del perfil)
4. Top 3 riesgos de concentración
5. Recomendaciones de instrumentos para mejorar la diversificación`,
        },
      },
    ],
  },

  // ------------------------------------------
  // 4. Recomendaciones por perfil de riesgo
  // ------------------------------------------
  {
    name: "investment_recommendations",
    description:
      "Genera recomendaciones de inversión personalizadas según el perfil de riesgo del usuario autenticado: " +
      "conservador (preservación del capital), moderado (crecimiento balanceado) o agresivo (máximo crecimiento). " +
      "Analiza el portfolio actual y propone una asignación objetivo con instrumentos concretos del mercado argentino.",
    arguments: [
      {
        name: "risk_profile",
        description:
          "Perfil de riesgo del inversor: 'conservador', 'moderado' o 'agresivo'",
        required: true,
      },
    ],
    render: ({ risk_profile }, _jwtUserId) => {
      const profile = risk_profile?.toLowerCase() ?? "moderado";

      const allocationGuide =
        profile === "conservador"
          ? `**Perfil CONSERVADOR — Preservación del capital**
Objetivo: proteger el poder adquisitivo frente a la inflación ARS y la devaluación, con mínima volatilidad.

| Clase de activo | Asignación objetivo | Instrumentos referencia |
|----------------|--------------------|-----------------------|
| Bonos CER / instrumentos indexados | 40–50% | TX28, TX26, BONCER, FCIs CER |
| Letras / Money Market ARS | 20–25% | LECAP, FCI Liquidez (Fima, Premier) |
| Hard dollar / USD cash | 20–25% | AL30, GD30, LETES, USD-CASH, USDC |
| Renta variable defensiva | 5–10% | CEDEARs de utilities (KO, JNJ, VZ) |
| Crypto / activos de riesgo | 0–5% | máximo USDT/USDC (como reserva) |`
          : profile === "agresivo"
          ? `**Perfil AGRESIVO — Máximo crecimiento**
Objetivo: maximizar el retorno en USD a 3–5 años, con alta tolerancia a la volatilidad y drawdowns temporales.

| Clase de activo | Asignación objetivo | Instrumentos referencia |
|----------------|--------------------|-----------------------|
| CEDEARs growth / tech | 30–40% | AAPL, MSFT, NVDA, AMZN, GOOGL |
| Acciones locales beta-alto | 15–20% | GGAL, SUPV, BMA, MELI, LOMA |
| Crypto | 15–25% | BTC, ETH, SOL |
| Hard dollar / bonos USD | 10–15% | AL30, GD30 (corta duration) |
| Instrumentos indexados / liquidez | 5–10% | LECAP, FCI Money Market |`
          : `**Perfil MODERADO — Crecimiento balanceado**
Objetivo: crecimiento real en USD a mediano plazo con volatilidad controlada.

| Clase de activo | Asignación objetivo | Instrumentos referencia |
|----------------|--------------------|-----------------------|
| Bonos CER / indexados | 20–30% | TX28, BONCER, FCIs CER |
| Hard dollar / bonos USD | 20–25% | AL30, GD30, LETES |
| CEDEARs diversificados | 20–25% | AAPL, MSFT, BRK-B, VTI, QQQ |
| Acciones locales | 10–15% | GGAL, YPF, PAMP, ALUA |
| Crypto | 5–10% | BTC, ETH |
| Liquidez / Money Market | 5–10% | LECAP, FCI MM |`;

      return [
        {
          role: "user",
          content: {
            type: "text",
            text: `Generá recomendaciones de inversión personalizadas para el usuario autenticado con perfil de riesgo **${profile.toUpperCase()}**.

${allocationGuide}

---

**Paso 1 — Analizá la cartera actual**
Llamá a \`get_user_portfolio_summary\` (el user_id viene del JWT autenticado).
Paginá si es necesario para obtener todas las posiciones.

Calculá la asignación actual por clase de activo, moneda y plataforma.

**Paso 2 — Identificá los GAPs respecto a la asignación objetivo**
Comparé la asignación actual con la tabla de asignación objetivo del perfil ${profile.toUpperCase()} de arriba.
Para cada clase de activo:
- ¿Está sobre-asignada (>5% sobre el máximo objetivo)?
- ¿Está sub-asignada (>5% bajo el mínimo objetivo)?
- ¿Está dentro del rango?

**Paso 3 — Buscá instrumentos concretos para cubrir los GAPs**
Para cada clase sub-asignada, llamá a \`search_global_assets\` con queries específicas:
- Ej para CER: "bono CER TX28", "FCI pesos CER"
- Ej para CEDEARs: "CEDEAR tecnología AAPL", "CEDEAR MSFT"
- Ej para crypto: "BTC bitcoin", "ETH ethereum"
Priorizá instrumentos disponibles en las plataformas que el usuario ya tiene vinculadas.

**Paso 4 — Presentá las recomendaciones**

**Resumen ejecutivo:**
- Valor total del portfolio (en ARS y USD estimado)
- Principales fortalezas de la cartera actual
- Principales ajustes necesarios

**Tabla de recomendaciones** (ordenada por prioridad de impacto):

| Prioridad | Acción | Instrumento | Monto sugerido (ARS/USD) | Razón |
|-----------|--------|-------------|--------------------------|-------|
| 1 | Comprar/Reducir | ... | ... | ... |

**Advertencia de riesgo:**
Incluí un párrafo recordando que estas son sugerencias basadas en el perfil declarado. El mercado argentino tiene alta volatilidad y los retornos pasados no garantizan resultados futuros. Se recomienda consultar con un asesor financiero matriculado (CNV) antes de tomar decisiones.`,
          },
        },
      ];
    },
  },
];

// ==========================================
// MCP Request Router
// ==========================================

async function handleMcp(msg: unknown, jwtUserId: string | null): Promise<Response> {
  const m = msg as Record<string, unknown>;

  // JSON-RPC notifications (no `id`) — acknowledge silently
  if (!("id" in m)) {
    return new Response(null, { status: 202, headers: CORS_HEADERS });
  }

  const id = m.id as string | number | null;
  const method = m.method as string;
  const params = (m.params ?? {}) as Record<string, unknown>;

  switch (method) {
    // ------------------------------------------
    // Lifecycle
    // ------------------------------------------
    case "initialize":
      return ok(id, {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: {
          tools: { listChanged: false },
          resources: { listChanged: false, subscribe: false },
          prompts: { listChanged: false },
        },
        serverInfo: { name: "assetcentral-mcp", version: "2.3.0" },
      });

    case "ping":
      return ok(id, {});

    // ------------------------------------------
    // Tools
    // ------------------------------------------
    case "tools/list":
      return ok(id, {
        tools: TOOLS.map(({ name, description, inputSchema }) => ({
          name,
          description,
          inputSchema,
        })),
      });

    case "tools/call": {
      const tool = TOOLS.find((t) => t.name === params.name);
      if (!tool) {
        return mcpErr(id, -32601, `Unknown tool: ${params.name}`);
      }
      try {
        const result = await tool.handler(
          (params.arguments ?? {}) as Record<string, unknown>,
          jwtUserId,
        );
        return ok(id, result);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return mcpErr(id, -32603, `Tool execution failed: ${msg}`);
      }
    }

    // ------------------------------------------
    // Resources — static list
    // ------------------------------------------
    case "resources/list":
      return ok(id, {
        resources: STATIC_RESOURCES.map(
          ({ name, uri, description, mimeType }) => ({
            name,
            uri,
            description,
            mimeType,
          }),
        ),
      });

    // ------------------------------------------
    // Resource Templates — dynamic URIs
    // ------------------------------------------
    case "resources/templates/list":
      return ok(id, {
        resourceTemplates: RESOURCE_TEMPLATES.map(
          ({ name, uriTemplate, description, mimeType }) => ({
            name,
            uriTemplate,
            description,
            mimeType,
          }),
        ),
      });

    // ------------------------------------------
    // Resources — read (static + dynamic)
    // ------------------------------------------
    case "resources/read": {
      const uri = params.uri as string;

      // 1. Try static resources
      const staticRes = STATIC_RESOURCES.find((r) => r.uri === uri);
      if (staticRes) {
        try {
          return ok(id, await staticRes.handler(jwtUserId));
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : String(e);
          return mcpErr(id, -32603, `Resource read failed: ${msg}`);
        }
      }

      // 2. Try dynamic resource templates
      for (const tpl of RESOURCE_TEMPLATES) {
        const match = uri.match(tpl.pattern);
        if (match) {
          // Build named-capture map from positional groups
          // Pattern for user profile: group 1 = user_id
          const paramMap: Record<string, string> = {};
          const varNames = [...tpl.uriTemplate.matchAll(/\{(\w+)\}/g)].map(
            (m) => m[1],
          );
          varNames.forEach((name, i) => {
            paramMap[name] = match[i + 1];
          });
          try {
            return ok(id, await tpl.handler(paramMap, jwtUserId));
          } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e);
            return mcpErr(id, -32603, `Resource read failed: ${msg}`);
          }
        }
      }

      return mcpErr(id, -32601, `Unknown resource URI: ${uri}`);
    }

    // ------------------------------------------
    // Prompts — list all templates
    // ------------------------------------------
    case "prompts/list":
      return ok(id, {
        prompts: PROMPTS.map(({ name, description, arguments: args }) => ({
          name,
          description,
          arguments: args,
        })),
      });

    // ------------------------------------------
    // Prompts — get a rendered template
    // ------------------------------------------
    case "prompts/get": {
      const promptName = params.name as string;
      const promptArgs = (params.arguments ?? {}) as Record<string, string>;
      const prompt = PROMPTS.find((p) => p.name === promptName);
      if (!prompt) {
        return mcpErr(id, -32601, `Unknown prompt: ${promptName}`);
      }
      const missing = prompt.arguments
        .filter((a) => a.required && !promptArgs[a.name])
        .map((a) => a.name);
      if (missing.length > 0) {
        return mcpErr(
          id,
          -32602,
          `Missing required argument(s): ${missing.join(", ")}`,
        );
      }
      if (!jwtUserId) {
        return mcpErr(id, -32001, "Unauthorized: valid JWT required to render prompt.");
      }
      return ok(id, {
        description: prompt.description,
        messages: prompt.render(promptArgs, jwtUserId),
      });
    }

    default:
      return mcpErr(id, -32601, `Method not found: ${method}`);
  }
}

// ==========================================
// HTTP Entry Point
// ==========================================

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  if (req.method !== "POST") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: CORS_HEADERS,
    });
  }

  // Extract authenticated user from JWT. Supabase already verified the
  // signature (verify_jwt: true), so we only need to decode the sub claim.
  const authHeader = req.headers.get("Authorization") ?? "";
  const token = authHeader.replace(/^Bearer\s+/i, "").trim();
  const jwtUserId = token ? decodeJwtSub(token) : null;

  let msg: unknown;
  try {
    msg = await req.json();
  } catch {
    return mcpErr(null, -32700, "Parse error: request body is not valid JSON");
  }

  try {
    if (Array.isArray(msg)) {
      // JSON-RPC batch
      const responses = await Promise.all(msg.map((m) => handleMcp(m, jwtUserId)));
      const bodies = await Promise.all(
        responses.map((r) => (r.status === 202 ? null : r.json())),
      );
      return new Response(JSON.stringify(bodies.filter(Boolean)), {
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      });
    }
    return await handleMcp(msg, jwtUserId);
  } catch (e: unknown) {
    const errMsg = e instanceof Error ? e.message : String(e);
    console.error("Unhandled MCP error:", errMsg);
    return mcpErr(null, -32603, `Internal error: ${errMsg}`);
  }
});
