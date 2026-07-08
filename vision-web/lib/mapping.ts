import { createClient, type Client } from "@libsql/client";
import { hasTurso } from "./config";

// The camera↔table mapping lives in a small config table in Turso (the same DB
// the venue box uses). This is web-app-owned config, created on demand.
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

export interface MapEntry {
  assetId: string;      // Vision asset (tracked table)
  facilityId: number;   // Strikee facility id
  label: string;        // human label, e.g. "Table 2"
}

async function ensureTable() {
  await client().execute(
    `CREATE TABLE IF NOT EXISTS webapp_table_map (
       asset_id    TEXT PRIMARY KEY,
       facility_id INTEGER NOT NULL,
       label       TEXT,
       updated_at  TEXT
     )`
  );
}

export async function getMapping(): Promise<MapEntry[]> {
  if (!hasTurso()) return [];
  try {
    await ensureTable();
    const rs = await client().execute(
      "SELECT asset_id, facility_id, label FROM webapp_table_map"
    );
    return rs.rows.map((r) => ({
      assetId: String(r.asset_id),
      facilityId: Number(r.facility_id),
      label: r.label ? String(r.label) : String(r.asset_id),
    }));
  } catch {
    return [];
  }
}

/** Replace the whole mapping (upsert each; drop entries not present). */
export async function saveMapping(entries: MapEntry[]): Promise<void> {
  await ensureTable();
  const c = client();
  const now = new Date().toISOString();
  const keep = entries.map((e) => e.assetId);
  // upsert provided
  for (const e of entries) {
    await c.execute({
      sql: `INSERT INTO webapp_table_map (asset_id, facility_id, label, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
              facility_id = excluded.facility_id,
              label = excluded.label,
              updated_at = excluded.updated_at`,
      args: [e.assetId, e.facilityId, e.label, now],
    });
  }
  // remove unmapped
  const rs = await c.execute("SELECT asset_id FROM webapp_table_map");
  for (const r of rs.rows) {
    const id = String(r.asset_id);
    if (!keep.includes(id)) {
      await c.execute({ sql: "DELETE FROM webapp_table_map WHERE asset_id = ?", args: [id] });
    }
  }
}
