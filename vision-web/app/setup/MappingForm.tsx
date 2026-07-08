"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

interface Asset { assetId: string; name: string; }
interface Facility { id: number; name: string; sportType: string | null; status: string | null; }
interface MapEntry { assetId: string; facilityId: number; label: string; }

export default function MappingForm({
  assets, facilities, initial,
}: {
  assets: Asset[];
  facilities: Facility[];
  initial: MapEntry[];
}) {
  const router = useRouter();
  const initMap: Record<string, number | ""> = {};
  for (const a of assets) {
    const m = initial.find((x) => x.assetId === a.assetId);
    initMap[a.assetId] = m ? m.facilityId : "";
  }
  const [sel, setSel] = useState<Record<string, number | "">>(initMap);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function save() {
    setBusy(true);
    setMsg("");
    const mapping: MapEntry[] = assets
      .filter((a) => sel[a.assetId] !== "")
      .map((a) => {
        const fid = Number(sel[a.assetId]);
        const fac = facilities.find((f) => f.id === fid);
        return { assetId: a.assetId, facilityId: fid, label: a.name || (fac ? `Table ${fac.name}` : a.assetId) };
      });
    const res = await fetch("/api/mapping", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mapping }),
    });
    setBusy(false);
    if (res.ok) {
      setMsg("Saved.");
      router.refresh();
    } else {
      setMsg("Save failed — check that Turso is writable.");
    }
  }

  return (
    <div>
      <table>
        <thead>
          <tr>
            <th>Camera table (Vision)</th>
            <th>→ Strikee facility</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((a) => (
            <tr key={a.assetId}>
              <td>{a.name} <span className="muted">({a.assetId.slice(0, 6)})</span></td>
              <td>
                <select
                  value={sel[a.assetId]}
                  onChange={(e) =>
                    setSel({ ...sel, [a.assetId]: e.target.value === "" ? "" : Number(e.target.value) })
                  }
                >
                  <option value="">— not mapped —</option>
                  {facilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} · {f.sportType ?? "?"} {f.status === "ACTIVE" ? "" : `(${f.status})`}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 14 }}>
        <button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save mapping"}</button>
        {msg && <span className="muted">{msg}</span>}
      </div>
      {facilities.length === 0 && (
        <p className="muted" style={{ marginTop: 10 }}>
          No Strikee facilities loaded — check SUPABASE env + shop id.
        </p>
      )}
    </div>
  );
}
