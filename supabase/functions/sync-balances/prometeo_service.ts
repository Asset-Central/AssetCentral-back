/**
 * Servicio Prometeo para Supabase Edge Functions (Deno).
 * Consumido por el worker de sincronización en segundo plano (pg_cron → Edge Function).
 *
 * Flujo: login → GET /account/balances/ → logout → retorna asset estandarizado.
 * Si la session key expira antes de usarse, se re-autentica automáticamente (1 reintento).
 */

const PROMETEO_BASE = "https://banking.sandbox.prometeoapi.com";

// -------------------------------------------------------------------------- //
//  Tipos                                                                       //
// -------------------------------------------------------------------------- //

/** Credenciales desencriptadas que vienen del Vault de Supabase. */
interface PrometeoCredentials {
  username: string;
  password: string;
  /** "test" en sandbox; el código del banco real en producción. */
  provider?: string;
}

/** Cuenta bancaria tal como la devuelve el endpoint de Prometeo. */
interface PrometeoAccount {
  number?: string;
  id?: string;
  name?: string;
  currency: string;
  balance: number | string;
}

/** Respuesta del endpoint /account/balances/ */
interface BalancesResponse {
  status: string;
  accounts?: PrometeoAccount[];
}

/** Respuesta del endpoint /login/ */
interface LoginResponse {
  status: string;
  key?: string;
}

/** Objeto estandarizado para nuestra tabla `assets`. */
export interface PrometeoAsset {
  ticker: string;
  platform: "prometeo";
  asset_type: "fiat";
  currency: string;
  current_value_ars: number;
}

// -------------------------------------------------------------------------- //
//  Errores                                                                     //
// -------------------------------------------------------------------------- //

class SessionExpiredError extends Error {
  constructor() {
    super("Sesión de Prometeo expirada o inválida.");
    this.name = "SessionExpiredError";
  }
}

// -------------------------------------------------------------------------- //
//  Helpers internos                                                            //
// -------------------------------------------------------------------------- //

function apiHeaders(apiKey: string): HeadersInit {
  return {
    "X-API-Key": apiKey,
    "Content-Type": "application/json",
  };
}

async function prometeoLogin(
  credentials: PrometeoCredentials,
  apiKey: string,
): Promise<string> {
  const resp = await fetch(`${PROMETEO_BASE}/login/`, {
    method: "POST",
    headers: apiHeaders(apiKey),
    body: JSON.stringify({
      provider: credentials.provider ?? "test",
      username: credentials.username,
      password: credentials.password,
    }),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Prometeo login HTTP ${resp.status}: ${text}`);
  }

  const data: LoginResponse = await resp.json();

  if (data.status !== "logged_in" && data.status !== "success") {
    throw new Error(
      `Login rechazado por Prometeo (status="${data.status}"). ` +
        "Verifica usuario, contraseña y provider.",
    );
  }

  if (!data.key) {
    throw new Error("Prometeo no devolvió session key tras el login.");
  }

  return data.key;
}

async function prometeoLogout(key: string, apiKey: string): Promise<void> {
  try {
    await fetch(`${PROMETEO_BASE}/logout/`, {
      method: "POST",
      headers: apiHeaders(apiKey),
      body: JSON.stringify({ key }),
    });
  } catch {
    // silencioso — la key expira sola en el sandbox
  }
}

async function getArsBalance(
  key: string,
  apiKey: string,
): Promise<number> {
  const url = new URL(`${PROMETEO_BASE}/account/balances/`);
  url.searchParams.set("key", key);

  const resp = await fetch(url.toString(), {
    method: "GET",
    headers: apiHeaders(apiKey),
  });

  // 401 indica session key inválida o expirada
  if (resp.status === 401) {
    throw new SessionExpiredError();
  }

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Prometeo balances HTTP ${resp.status}: ${text}`);
  }

  const data: BalancesResponse = await resp.json();

  // Prometeo también puede indicar sesión expirada en el body con 200
  if (data.status === "session_expired" || data.status === "not_authorized") {
    throw new SessionExpiredError();
  }

  const accounts: PrometeoAccount[] = data.accounts ?? [];
  const arsAccount = accounts.find(
    (acc) => acc.currency?.toUpperCase() === "ARS",
  );

  if (!arsAccount) {
    throw new Error(
      "Prometeo no devolvió ninguna cuenta con currency ARS. " +
        `Cuentas disponibles: ${accounts.map((a) => a.currency).join(", ")}`,
    );
  }

  return Number(arsAccount.balance ?? 0);
}

/**
 * Hace login, obtiene el balance y desloguea.
 * Si la session key expira justo entre el login y el fetch (SessionExpiredError),
 * reintenta una sola vez con una nueva sesión antes de propagar el error.
 */
async function fetchBalanceWithRetry(
  credentials: PrometeoCredentials,
  apiKey: string,
  retried = false,
): Promise<number> {
  const key = await prometeoLogin(credentials, apiKey);
  try {
    return await getArsBalance(key, apiKey);
  } catch (err) {
    if (err instanceof SessionExpiredError && !retried) {
      return fetchBalanceWithRetry(credentials, apiKey, true);
    }
    throw err;
  } finally {
    await prometeoLogout(key, apiKey);
  }
}

// -------------------------------------------------------------------------- //
//  Función pública                                                             //
// -------------------------------------------------------------------------- //

/**
 * Obtiene el saldo ARS de la cuenta Prometeo y retorna un objeto estandarizado
 * listo para upsert en la tabla `assets`.
 *
 * @param credentials - Credenciales desencriptadas del Vault de Supabase.
 * @returns PrometeoAsset con el saldo actualizado.
 */
export async function fetchPrometeoBalance(
  credentials: PrometeoCredentials,
): Promise<PrometeoAsset> {
  const apiKey = Deno.env.get("PROMETEO_API_KEY");
  if (!apiKey) {
    throw new Error("Falta la variable de entorno PROMETEO_API_KEY.");
  }

  const balance = await fetchBalanceWithRetry(credentials, apiKey);

  return {
    ticker: "ARS",
    platform: "prometeo",
    asset_type: "fiat",
    currency: "ARS",
    current_value_ars: balance,
  };
}
