import { NextRequest, NextResponse } from "next/server";
import {
  checkCredentials, createSessionToken, setSessionCookie,
} from "@/lib/auth";

export const runtime = "nodejs";

// Safe setup diagnostic (no secret values leaked). Visit /api/auth/login in the
// browser to confirm the env is actually present + spot quote/space mistakes.
// Remove after setup if you like.
export async function GET() {
  const u = process.env.APP_USERNAME ?? "";
  const p = process.env.APP_PASSWORD ?? "";
  const s = process.env.AUTH_SECRET ?? "";
  return NextResponse.json({
    APP_USERNAME_set: u.length > 0,
    APP_PASSWORD_set: p.length > 0,
    AUTH_SECRET_ok: s.length >= 16,
    username_len: u.length,
    password_len: p.length,
    password_wrapped_in_quotes: /^["'].*["']$/.test(p),
    password_has_edge_whitespace: p !== p.trim(),
    username_has_edge_whitespace: u !== u.trim(),
  });
}

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
