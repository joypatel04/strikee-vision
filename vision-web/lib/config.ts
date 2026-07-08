export const SHOP_ID = Number(process.env.STRIKEE_SHOP_ID ?? "36");
export const VENUE_ID = process.env.STRIKEE_VENUE_ID ?? "";

export const hasTurso = () =>
  !!process.env.TURSO_DATABASE_URL && !!process.env.TURSO_AUTH_TOKEN;
export const hasSupabase = () =>
  !!process.env.SUPABASE_URL && !!process.env.SUPABASE_SERVICE_ROLE_KEY;

/** Today's date as YYYY-MM-DD in the venue's local time (IST). */
export function todayIST(): string {
  const now = new Date();
  const ist = new Date(now.getTime() + 5.5 * 3600 * 1000);
  return ist.toISOString().slice(0, 10);
}
