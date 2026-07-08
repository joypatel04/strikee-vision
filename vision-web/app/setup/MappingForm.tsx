"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, LoaderCircle, Cctv } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

interface Asset { assetId: string; name: string; }
interface Facility { id: number; name: string; sportType: string | null; status: string | null; }
interface MapEntry { assetId: string; facilityId: number; label: string; }

const UNMAPPED = "none";

export default function MappingForm({
  assets, facilities, initial,
}: {
  assets: Asset[];
  facilities: Facility[];
  initial: MapEntry[];
}) {
  const router = useRouter();
  const init: Record<string, string> = {};
  for (const a of assets) {
    const m = initial.find((x) => x.assetId === a.assetId);
    init[a.assetId] = m ? String(m.facilityId) : UNMAPPED;
  }
  const [sel, setSel] = useState<Record<string, string>>(init);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  async function save() {
    setBusy(true);
    setSaved(false);
    const mapping: MapEntry[] = assets
      .filter((a) => sel[a.assetId] !== UNMAPPED)
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
      setSaved(true);
      router.refresh();
      setTimeout(() => setSaved(false), 2500);
    }
  }

  return (
    <div className="space-y-3">
      <div className="divide-y divide-border/60 overflow-hidden rounded-lg border border-border/60">
        {assets.map((a) => (
          <div key={a.assetId} className="flex items-center gap-4 bg-card/40 px-4 py-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-secondary">
              <Cctv className="h-4 w-4 text-muted-foreground" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{a.name}</div>
              <div className="truncate text-xs text-muted-foreground">{a.assetId.slice(0, 8)}</div>
            </div>
            <div className="w-56">
              <Select value={sel[a.assetId]} onValueChange={(v) => setSel({ ...sel, [a.assetId]: v })}>
                <SelectTrigger>
                  <SelectValue placeholder="Select facility…" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={UNMAPPED}>— not mapped —</SelectItem>
                  {facilities.map((f) => (
                    <SelectItem key={f.id} value={String(f.id)}>
                      {f.name} · {f.sportType ?? "?"}{f.status && f.status !== "ACTIVE" ? ` (${f.status})` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3 pt-1">
        <Button onClick={save} disabled={busy}>
          {busy && <LoaderCircle className="h-4 w-4 animate-spin" />}
          {busy ? "Saving…" : "Save mapping"}
        </Button>
        {saved && (
          <span className="flex items-center gap-1.5 text-sm text-primary">
            <Check className="h-4 w-4" /> Saved
          </span>
        )}
        {facilities.length === 0 && (
          <span className="text-sm text-muted-foreground">
            No Strikee facilities loaded — check Supabase env + shop id.
          </span>
        )}
      </div>
    </div>
  );
}
