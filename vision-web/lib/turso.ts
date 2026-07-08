import { createClient, type Client } from "@libsql/client";
import { hasTurso } from "./config";

let _client: Client | null = null;
function client(): Client {
  if (!_client) {
    _client = createClient({
      url: process.env.TURSO_DATABASE_URL!,
      authToken: process.env.TURSO_AUTH_TOKEN!,
    });
  }
  return _client;
}

export interface TrackedAsset {
  assetId: string;
  name: string;
}

/** All tracked tables (assets) from the Vision box. */
export async function listAssets(): Promise<TrackedAsset[]> {
  if (!hasTurso()) return [];
  try {
    const rs = await client().execute(
      "SELECT id, name FROM assets ORDER BY name"
    );
    return rs.rows.map((r) => ({ assetId: String(r.id), name: String(r.name) }));
  } catch {
    return [];
  }
}

/** Games we DETECTED per asset on a date (count of game_start events).
 * ts is a local ISO string, so the first 10 chars are the local date. */
export async function trackedGamesByAsset(date: string): Promise<Record<string, number>> {
  if (!hasTurso()) return {};
  try {
    const rs = await client().execute({
      sql: `SELECT asset_id, COUNT(*) AS games
            FROM events
            WHERE type = 'game_start' AND substr(ts, 1, 10) = ?
            GROUP BY asset_id`,
      args: [date],
    });
    const out: Record<string, number> = {};
    for (const r of rs.rows) if (r.asset_id != null) out[String(r.asset_id)] = Number(r.games);
    return out;
  } catch {
    return {};
  }
}

/** Minutes each table was actually in use on a date (sum of usage sessions). */
export async function inUseMinutesByAsset(date: string): Promise<Record<string, number>> {
  if (!hasTurso()) return {};
  try {
    const rs = await client().execute({
      sql: `SELECT asset_id, COALESCE(SUM(duration_sec), 0) AS secs
            FROM sessions
            WHERE substr(start_ts, 1, 10) = ? AND status != 'voided'
            GROUP BY asset_id`,
      args: [date],
    });
    const out: Record<string, number> = {};
    for (const r of rs.rows) out[String(r.asset_id)] = Math.round(Number(r.secs) / 60);
    return out;
  } catch {
    return {};
  }
}

/** Cloud-sync freshness: newest heartbeat we have. Metric samples are written
 * every tick while the box runs, so their max ts tracks "box alive + syncing"
 * (not just the last game). Falls back to events. */
export async function latestActivityTs(): Promise<string | null> {
  if (!hasTurso()) return null;
  try {
    const rs = await client().execute("SELECT MAX(ts) AS t FROM metric_samples");
    const t = rs.rows[0]?.t ? String(rs.rows[0].t) : null;
    if (t) return t;
    const rs2 = await client().execute("SELECT MAX(ts) AS t FROM events");
    return rs2.rows[0]?.t ? String(rs2.rows[0].t) : null;
  } catch {
    return null;
  }
}
