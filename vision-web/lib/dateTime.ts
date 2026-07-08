// Strikee business day = 05:00 IST → 05:00 IST next day (matches the Strikee
// cashbook). Timestamps in Supabase are UTC (created_at); tracking timestamps in
// Turso are IST-local ISO strings. IST is a fixed UTC+5:30 (no DST), so we can
// compute windows without a tz library.

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

/** Add N days to a "YYYY-MM-DD" date string. */
export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** The current business date ("YYYY-MM-DD"): before 05:00 IST it's still
 * yesterday's (still-open) business day, matching Strikee. */
export function currentBusinessDate(): string {
  const ist = new Date(Date.now() + IST_OFFSET_MS); // IST wall-clock in UTC fields
  if (ist.getUTCHours() < 5) ist.setUTCDate(ist.getUTCDate() - 1);
  return ist.toISOString().slice(0, 10);
}

/** UTC window for a business day — for Supabase `created_at` (timestamptz).
 * 05:00 IST on D → 05:00 IST on D+1. */
export function businessDayUtcRange(date: string): { startUtc: string; endUtc: string } {
  return {
    startUtc: new Date(`${date}T05:00:00+05:30`).toISOString(),
    endUtc: new Date(`${addDays(date, 1)}T05:00:00+05:30`).toISOString(),
  };
}

/** IST wall-clock window for a business day — for Turso `ts` (IST-local ISO,
 * compared on its first 19 chars "YYYY-MM-DDTHH:MM:SS"). */
export function businessDayIstRange(date: string): { istStart: string; istEnd: string } {
  return {
    istStart: `${date}T05:00:00`,
    istEnd: `${addDays(date, 1)}T05:00:00`,
  };
}
