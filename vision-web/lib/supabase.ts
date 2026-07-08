import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { hasSupabase } from "./config";
import { businessDayUtcRange } from "./dateTime";

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
  // Group by the Strikee BUSINESS DAY (05:00 IST → 05:00 IST next day) on
  // created_at, NOT the naive session_date (which mislabels post-midnight games).
  const { startUtc, endUtc } = businessDayUtcRange(date);
  const { data, error } = await admin()
    .from("game_sessions")
    .select("facility_id, number_of_games, total_price")
    .eq("shop_id", shopId)
    .gte("created_at", startUtc)
    .lt("created_at", endUtc)
    .is("cancelled_at", null)          // cancelled sessions aren't games played
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

export interface Cashbook {
  cashInHand: number;
  upiCardNet: number;
  todaysBalance: number;
  credit: number;
  moneyIn: number;
  moneyOut: number;
  entries: number;
}

/** Authoritative money for a business day — the SAME numbers the Strikee
 * Cashbook shows (nets payment methods, credit, add-ons, refunds). Uses the
 * shop's own reporting RPC so it can't drift from the POS. */
export async function cashbookTotal(shopId: number, date: string): Promise<Cashbook | null> {
  if (!hasSupabase()) return null;
  const { startUtc, endUtc } = businessDayUtcRange(date);
  const { data, error } = await admin().rpc("get_cashbook_total_v_next", {
    start_date: startUtc,
    end_date: endUtc,
    p_shop_id: shopId,
  });
  if (error || !data) return null;
  const r = Array.isArray(data) ? data[0] : data;
  if (!r) return null;
  return {
    cashInHand: Number(r.cash_in_hand ?? 0),
    upiCardNet: Number(r.upi_card_online_net ?? 0),
    todaysBalance: Number(r.todays_balance ?? 0),
    credit: Number(r.credit_amount ?? 0),
    moneyIn: Number(r.money_in ?? 0),
    moneyOut: Number(r.money_out ?? 0),
    entries: Number(r.number_of_entries ?? 0),
  };
}
