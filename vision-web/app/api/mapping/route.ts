import { NextRequest, NextResponse } from "next/server";
import { getMapping, saveMapping, type MapEntry } from "@/lib/mapping";

export const runtime = "nodejs";

export async function GET() {
  return NextResponse.json({ mapping: await getMapping() });
}

export async function POST(req: NextRequest) {
  let body: { mapping?: MapEntry[] };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }
  const entries = (body.mapping ?? []).filter(
    (e) => e && e.assetId && Number.isFinite(Number(e.facilityId))
  ).map((e) => ({
    assetId: String(e.assetId),
    facilityId: Number(e.facilityId),
    label: String(e.label ?? e.assetId),
  }));
  try {
    await saveMapping(entries);
    return NextResponse.json({ ok: true, count: entries.length });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message ?? e) }, { status: 500 });
  }
}
