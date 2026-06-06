import { createClient } from "npm:@supabase/supabase-js@2";

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const supabaseKey = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const supabase = createClient(supabaseUrl, supabaseKey);

// ==========================================
// Serialization Utilities
// ==========================================

function jsonArrayToMarkdownTable(jsonArray: any[]): string {
  if (!jsonArray || jsonArray.length === 0) return "No data found.";
  const keys = Object.keys(jsonArray[0]);
  let md = `| ${keys.join(" | ")} |\n| ${keys.map(() => "---").join(" | ")} |\n`;
  for (const row of jsonArray) {
    const vals = keys.map(k => {
      let v = row[k];
      if (typeof v === "object" && v !== null) v = JSON.stringify(v);
      return String(v ?? "").replace(/\|/g, "\\|");
    });
    md += `| ${vals.join(" | ")} |\n`;
  }
  return md;
}

function jsonToMarkdownKv(obj: Record<string, any>): string {
  if (!obj) return "No data found.";
  return Object.entries(obj).map(([k, v]) => {
    if (typeof v === "object" && v !== null) v = JSON.stringify(v);
    return `**${k}:** ${v}`;
  }).join("\n");
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

// MCP protocol version this server speaks
const PROTOCOL_VERSION = "2024-11-05";

function ok(id: string | number | null, result: unknown): Response {
  return new Response(
    JSON.stringify({ jsonrpc: "2.0", id, result }),
    { headers: { "Content-Type": "application/json", ...CORS_HEADERS } },
  );
}

function err(id: string | number | null, code: number, message: string): Response {
  return new Response(
    JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }),
    { headers: { "Content-Type": "application/json", ...CORS_HEADERS } },
  );
}

// ==========================================
// Tool + Resource Definitions
// ==========================================

interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
}

interface ToolDef {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  handler: (args: Record<string, any>) => Promise<ToolResult>;
}

interface ResourceDef {
  name: string;
  uri: string;
  description: string;
  mimeType: string;
  handler: () => Promise<{ contents: Array<{ uri: string; text: string }> }>;
}

const TOOLS: ToolDef[] = [
  {
    name: "search_global_assets",
    description: "Performs a Reciprocal Rank Fusion (RRF) hybrid search across global assets. Uses opaque cursor-based pagination.",
    inputSchema: {
      type: "object",
      properties: {
        query:  { type: "string",  description: "The semantic search query" },
        limit:  { type: "number",  description: "Maximum number of results to return", default: 10 },
        cursor: { type: "string",  description: "Opaque cursor for pagination (base64 encoded)" },
      },
      required: ["query"],
    },
    handler: async ({ query, limit = 10, cursor }) => {
      const rpcArgs: any = { search_query: query, page_limit: limit, offset_val: 0 };
      if (cursor) {
        try { rpcArgs.offset_val = JSON.parse(atob(cursor)).offset; } catch { /* keep 0 */ }
      }
      const { data, error } = await supabase.rpc("search_assets_hybrid_rrf", rpcArgs);
      if (error) return { content: [{ type: "text", text: `Search failed: ${error.message}` }] };
      const results = data ?? [];
      let text = jsonArrayToMarkdownTable(results);
      if (results.length === limit) {
        text += `\n\n**Next Page Cursor:** ${btoa(JSON.stringify({ offset: rpcArgs.offset_val + limit }))}`;
      }
      return { content: [{ type: "text", text }] };
    },
  },
  {
    name: "get_user_portfolio_summary",
    description: "Retrieves a flattened financial snapshot from llm_user_account_balances_view without complex joins.",
    inputSchema: {
      type: "object",
      properties: {
        user_id: { type: "string", format: "uuid", description: "The UUID of the user" },
      },
      required: ["user_id"],
    },
    handler: async ({ user_id }) => {
      const { data, error } = await supabase
        .from("llm_user_account_balances_view")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .single();
      if (error) {
        const text = error.code === "PGRST116"
          ? `No portfolio found for user ${user_id}.`
          : `Query failed: ${error.message}`;
        return { content: [{ type: "text", text }] };
      }
      return { content: [{ type: "text", text: jsonToMarkdownKv(data) }] };
    },
  },
];

const RESOURCES: ResourceDef[] = [
  {
    name: "schema",
    uri: "docs://schema/assetcentral",
    description: "AssetCentral Database schema with semantic metadata (COMMENT ON)",
    mimeType: "text/markdown",
    handler: async () => {
      const { data, error } = await supabase.rpc("get_schema_metadata");
      const text = error
        ? `Failed to load schema metadata: ${error.message}. Ensure the 'get_schema_metadata' RPC is created.`
        : jsonArrayToMarkdownTable(data ?? []);
      return { contents: [{ uri: "docs://schema/assetcentral", text }] };
    },
  },
];

// ==========================================
// MCP Request Router
// ==========================================

async function handleMcp(msg: any): Promise<Response> {
  // JSON-RPC notifications have no `id` — acknowledge with 202, no body
  if (!("id" in msg)) {
    return new Response(null, { status: 202, headers: CORS_HEADERS });
  }

  const { id, method, params = {} } = msg;

  switch (method) {
    case "initialize":
      return ok(id, {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: {
          tools:     { listChanged: false },
          resources: { listChanged: false, subscribe: false },
        },
        serverInfo: { name: "assetcentral-mcp", version: "1.0.0" },
      });

    case "ping":
      return ok(id, {});

    case "tools/list":
      return ok(id, {
        tools: TOOLS.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
      });

    case "resources/list":
      return ok(id, {
        resources: RESOURCES.map(({ name, uri, description, mimeType }) => ({ name, uri, description, mimeType })),
      });

    case "tools/call": {
      const tool = TOOLS.find(t => t.name === params.name);
      if (!tool) return err(id, -32601, `Unknown tool: ${params.name}`);
      try {
        return ok(id, await tool.handler(params.arguments ?? {}));
      } catch (e: any) {
        return err(id, -32603, e.message);
      }
    }

    case "resources/read": {
      const resource = RESOURCES.find(r => r.uri === params.uri);
      if (!resource) return err(id, -32601, `Unknown resource: ${params.uri}`);
      try {
        return ok(id, await resource.handler());
      } catch (e: any) {
        return err(id, -32603, e.message);
      }
    }

    default:
      return err(id, -32601, `Method not found: ${method}`);
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
    return new Response("Method Not Allowed", { status: 405, headers: CORS_HEADERS });
  }

  let msg: unknown;
  try {
    msg = await req.json();
  } catch {
    return err(null, -32700, "Parse error: request body is not valid JSON");
  }

  try {
    // Handle JSON-RPC batch (array) or single message
    if (Array.isArray(msg)) {
      const responses = await Promise.all(msg.map(handleMcp));
      const bodies = await Promise.all(responses.map(r => r.status === 202 ? null : r.json()));
      const batch = bodies.filter(Boolean);
      return new Response(JSON.stringify(batch), {
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      });
    }
    return await handleMcp(msg);
  } catch (e: any) {
    console.error("Unhandled error:", e);
    return err(null, -32603, `Internal error: ${e.message}`);
  }
});
