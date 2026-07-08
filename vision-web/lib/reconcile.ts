import { SHOP_ID } from "./config";
import { trackedGamesByAsset, inUseMinutesByAsset } from "./turso";
import { billedByFacility } from "./supabase";
import { getMapping } from "./mapping";

export interface ReconRow {
  label: string;
  assetId: string;
  facilityId: number;
  trackedGames: number;    // games our camera detected
  billedGames: number;     // games staff billed (number_of_games)
  gap: number;             // tracked - billed  (>0 = played but not billed = leak)
  revenue: number;
  inUseMinutes: number;
  status: "ok" | "leak" | "over";
}

export interface ReconResult {
  date: string;
  rows: ReconRow[];
  totals: { trackedGames: number; billedGames: number; revenue: number; gap: number };
  mapped: boolean;         // has the user set up the mapping yet?
}

export async function reconcile(date: string): Promise<ReconResult> {
  const [mapping, tracked, inUse] = await Promise.all([
    getMapping(),
    trackedGamesByAsset(date),
    inUseMinutesByAsset(date),
  ]);
  const billed = await billedByFacility(SHOP_ID, date);

  const rows: ReconRow[] = mapping.map((m) => {
    const trackedGames = tracked[m.assetId] ?? 0;
    const b = billed[m.facilityId] ?? { billedGames: 0, revenue: 0, sessions: 0 };
    const gap = trackedGames - b.billedGames;
    // >0 played more than billed = potential leakage; <0 billed more (e.g. pool
    // on a shared table, or a game we missed); 0 = clean.
    const status: ReconRow["status"] = gap > 0 ? "leak" : gap < 0 ? "over" : "ok";
    return {
      label: m.label,
      assetId: m.assetId,
      facilityId: m.facilityId,
      trackedGames,
      billedGames: b.billedGames,
      gap,
      revenue: b.revenue,
      inUseMinutes: inUse[m.assetId] ?? 0,
      status,
    };
  });

  const totals = rows.reduce(
    (t, r) => ({
      trackedGames: t.trackedGames + r.trackedGames,
      billedGames: t.billedGames + r.billedGames,
      revenue: t.revenue + r.revenue,
      gap: t.gap + r.gap,
    }),
    { trackedGames: 0, billedGames: 0, revenue: 0, gap: 0 }
  );

  return { date, rows, totals, mapped: mapping.length > 0 };
}
