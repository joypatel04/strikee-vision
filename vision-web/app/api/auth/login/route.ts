import { NextRequest, NextResponse } from "next/server";
import {
  checkCredentials, createSessionToken, setSessionCookie,
} from "@/lib/auth";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  let body: { username?: string; password?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }
  const { username = "", password = "" } = body;
  if (!checkCredentials(username, password)) {
    return NextResponse.json({ error: "invalid" }, { status: 401 });
  }
  const token = await createSessionToken(username);
  await setSessionCookie(token);
  return NextResponse.json({ ok: true });
}
