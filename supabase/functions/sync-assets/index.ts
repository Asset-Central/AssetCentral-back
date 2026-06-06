import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { fetchPrometeoBalance } from "../sync-balances/prometeo_service.ts";

interface VaultRow {
  account_id: string;
  platform: string;
  credentials: string;
}

Deno.serve(async () => {
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  const { data: accounts, error } = await supabase.rpc("get_decrypted_vault");

  if (error) {
    console.error("RPC get_decrypted_vault error:", error.message);
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!accounts?.length) {
    return new Response(JSON.stringify({ synced: 0 }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  let synced = 0;
  let failed = 0;

  await Promise.all(
    (accounts as VaultRow[]).map(async (row) => {
      try {
        if (row.platform !== "nacion") return;

        const credentials = JSON.parse(row.credentials);
        const asset = await fetchPrometeoBalance(credentials);

        await supabase.from("historical_balances").insert({
          account: row.account_id,
          asset: asset.ticker,
          quantity: 1,
          unit_price: asset.current_value_ars,
          total_valuation: asset.current_value_ars,
          recorded_at: new Date().toISOString(),
        });

        await supabase
          .from("account")
          .update({
            connection_status: "active",
            last_sync: new Date().toISOString(),
          })
          .eq("id", row.account_id);

        synced++;
      } catch (err) {
        console.error(`Error syncing account ${row.account_id}:`, err);

        await supabase
          .from("account")
          .update({ connection_status: "requires_reauthentication" })
          .eq("id", row.account_id);

        failed++;
      }
    }),
  );

  return new Response(JSON.stringify({ synced, failed }), {
    headers: { "Content-Type": "application/json" },
  });
});
