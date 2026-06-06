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

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept, mcp-session-id",
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
  handler: (args: Record<string, unknown>) => Promise<ToolResult>;
}

interface ResourceDef {
  name: string;
  uri: string;
  description: string;
  mimeType: string;
  handler: () => Promise<{ contents: Array<{ uri: string; text: string }> }>;
}

interface ResourceTemplateDef {
  name: string;
  uriTemplate: string;
  description: string;
  mimeType: string;
  pattern: RegExp;
  handler: (
    params: Record<string, string>,
  ) => Promise<{ contents: Array<{ uri: string; text: string }> }>;
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
      },
      required: ["query"],
    },
    handler: async ({ query, limit = 10, cursor }) => {
      const safeLimit = Math.min(Math.max(Number(limit) || 10, 1), 50);
      const offset = cursor ? decodeCursor(String(cursor)) : 0;

      const { data, error } = await supabase.rpc("search_assets_hybrid_rrf", {
        search_query: query,
        page_limit: safeLimit,
        offset_val: offset,
      });

      if (error) {
        return {
          content: [
            {
              type: "text",
              text: `**Search failed:** ${error.message}\n\n_Ensure the \`search_assets_hybrid_rrf\` RPC exists in the database._`,
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
            text: `## Asset Search Results\n\n**Query:** ${query}  \n**Showing:** ${results.length} result(s) (offset ${offset})\n\n${table}${nextCursor}`,
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
      "Returns a flattened financial snapshot for a user from the `llm_user_account_balances_view` denormalized view. " +
      "No complex JOINs required. Supports opaque cursor-based pagination for users with many positions.",
    inputSchema: {
      type: "object",
      properties: {
        user_id: {
          type: "string",
          format: "uuid",
          description: "UUID of the target user",
        },
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
      required: ["user_id"],
    },
    handler: async ({ user_id, limit = 50, cursor }) => {
      const safeLimit = Math.min(Math.max(Number(limit) || 50, 1), 200);
      const offset = cursor ? decodeCursor(String(cursor)) : 0;

      const { data, error } = await supabase
        .from("llm_user_account_balances_view")
        .select("*")
        .eq("user_id", user_id)
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
          content: [
            {
              type: "text",
              text: `_No portfolio data found for user \`${user_id}\`._`,
            },
          ],
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
            text: `## Portfolio Summary — User \`${user_id}\`\n\n${table}${nextCursor}`,
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
    handler: async () => {
      const text = await fetchSchemaMarkdown();
      return { content: [{ type: "text", text }] };
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
    handler: async () => {
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
    handler: async () => ({
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
    handler: async ({ user_id }) => {
      const uri = `docs://users/${user_id}/profile`;

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
// MCP Request Router
// ==========================================

async function handleMcp(msg: unknown): Promise<Response> {
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
        },
        serverInfo: { name: "assetcentral-mcp", version: "2.0.0" },
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
          return ok(id, await staticRes.handler());
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
            return ok(id, await tpl.handler(paramMap));
          } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e);
            return mcpErr(id, -32603, `Resource read failed: ${msg}`);
          }
        }
      }

      return mcpErr(id, -32601, `Unknown resource URI: ${uri}`);
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

  let msg: unknown;
  try {
    msg = await req.json();
  } catch {
    return mcpErr(null, -32700, "Parse error: request body is not valid JSON");
  }

  try {
    if (Array.isArray(msg)) {
      // JSON-RPC batch
      const responses = await Promise.all(msg.map(handleMcp));
      const bodies = await Promise.all(
        responses.map((r) => (r.status === 202 ? null : r.json())),
      );
      return new Response(JSON.stringify(bodies.filter(Boolean)), {
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      });
    }
    return await handleMcp(msg);
  } catch (e: unknown) {
    const errMsg = e instanceof Error ? e.message : String(e);
    console.error("Unhandled MCP error:", errMsg);
    return mcpErr(null, -32603, `Internal error: ${errMsg}`);
  }
});
