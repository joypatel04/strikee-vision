"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface Sync {
  state: "live" | "stale" | "offline" | "nodata" | "unconfigured";
  secondsAgo: number | null;
}

function ago(s: number): string {
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

const META: Record<Sync["state"], { dot: string; text: string; label: (s: Sync) => string }> = {
  live:         { dot: "bg-primary",     text: "text-primary",          label: (s) => `Live · ${ago(s.secondsAgo ?? 0)}` },
  stale:        { dot: "bg-warning",     text: "text-warning",          label: (s) => `Synced ${ago(s.secondsAgo ?? 0)}` },
  offline:      { dot: "bg-destructive", text: "text-destructive",      label: (s) => `No sync · ${ago(s.secondsAgo ?? 0)}` },
  nodata:       { dot: "bg-muted-foreground", text: "text-muted-foreground", label: () => "Awaiting data" },
  unconfigured: { dot: "bg-muted-foreground", text: "text-muted-foreground", label: () => "Not connected" },
};

export default function SyncChip() {
  const [sync, setSync] = useState<Sync | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch("/api/sync-health", { cache: "no-store" });
        if (alive && r.ok) setSync(await r.json());
      } catch {
        /* ignore */
      }
    };
    load();
    const id = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!sync) return null;
  const m = META[sync.state] ?? META.nodata;

  return (
    <span
      className="hidden items-center gap-1.5 rounded-full border border-border/70 bg-secondary/50 px-2.5 py-1 text-xs font-medium sm:inline-flex"
      title="Tracking data sync from the venue box"
    >
      <span className="relative flex h-2 w-2">
        {sync.state === "live" && (
          <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-60", m.dot)} />
        )}
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", m.dot)} />
      </span>
      <span className={m.text}>{m.label(sync)}</span>
    </span>
  );
}
