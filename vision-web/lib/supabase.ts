import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { hasSupabase } from "./config";

// Server-only client using the service role key. NEVER import this into a
// client component — the key must never reach the browser.
let _admin: SupabaseClient | null = null;
function admin(): SupabaseClient {
  if (!_admin) {
    _admin = createClient(
      process.env.SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!,
      { auth: { persistSession: false, autoRefreshToken: false } }
    );
  }
  return _admin;
}

export interface Facility {
  id: number;
  name: string;
  sportType: string | null;
  status: string | null;
}

export async function listFacilities(shopId: number): Promise<Facility[]> {
  if (!hasSupabase()) return [];
  const { data, error } = await admin()
    .from("facility")
    .select("id, name, sport_type, status")
    .eq("shop_id", shopId)
    .order("name");
  if (error || !data) return [];
  return data.map((r: any) => ({
    id: Number(r.id), name: String(r.name),
    sportType: r.sport_type ?? null, status: r.status ?? null,
  }));
}

export interface BilledFacility {
  billedGames: number;
  revenue: number;
  sessions: number;
}

/** Billed games + revenue per facility for a date, straight from game_sessions.
 * `number_of_games` is staff-entered — this is exactly what we check against
 * our detected games. */
export async function billedByFacility(
  shopId: number,
  date: string
): Promise<Record<number, BilledFacility>> {
  if (!hasSupabase()) return {};
  const { data, error } = await admin()
    .from("game_sessions")
    .select("facility_id, number_of_games, total_price")
    .eq("shop_id", shopId)
    .eq("session_date", date)
    .not("facility_id", "is", null);
  if (error || !data) return {};
  const out: Record<number, BilledFacility> = {};
  for (const r of data as any[]) {
    const fid = Number(r.facility_id);
    const b = (out[fid] ??= { billedGames: 0, revenue: 0, sessions: 0 });
    b.billedGames += Number(r.number_of_games ?? 0);
    b.revenue += Number(r.total_price ?? 0);
    b.sessions += 1;
  }
  return out;
}

/** Whole-venue revenue for a date (context number). */
export async function venueRevenue(shopId: number, date: string): Promise<number> {
  const byFac = await billedByFacility(shopId, date);
  return Object.values(byFac).reduce((s, f) => s + f.revenue, 0);
}
