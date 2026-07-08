import { NextResponse } from "next/server";
import { latestActivityTs } from "@/lib/turso";
import { hasTurso } from "@/lib/config";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";   // always run live, never cache

export async function GET() {
  if (!hasTurso()) {
    return NextResponse.json({ state: "unconfigured", latest: null, secondsAgo: null });
  }
  const latest = await latestActivityTs();
  if (!latest) {
    return NextResponse.json({ state: "nodata", latest: null, secondsAgo: null });
  }
  const secondsAgo = Math.max(0, Math.round((Date.now() - Date.parse(latest)) / 1000));
  // live = a heartbeat in the last 2 min; stale = within the hour; else offline
  const state = secondsAgo < 120 ? "live" : secondsAgo < 3600 ? "stale" : "offline";
  return NextResponse.json({ state, latest, secondsAgo });
}
