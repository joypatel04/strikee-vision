import { NextRequest, NextResponse } from "next/server";
import { jwtVerify } from "jose";

const SESSION_COOKIE = "sv_session";
// Public paths that don't require a session.
const PUBLIC = ["/login", "/api/auth/login", "/robots.txt"];

function secret(): Uint8Array {
  return new TextEncoder().encode(process.env.AUTH_SECRET ?? "");
}

async function isAuthed(req: NextRequest): Promise<boolean> {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return false;
  try {
    await jwtVerify(token, secret(), { algorithms: ["HS256"] });
    return true;
  } catch {
    return false;
  }
}

/** Always tag every response as non-indexable — belt and suspenders. */
function harden(res: NextResponse): NextResponse {
  res.headers.set(
    "X-Robots-Tag",
    "noindex, nofollow, noarchive, nosnippet, noimageindex"
  );
  return res;
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const isPublic = PUBLIC.some((p) => pathname === p || pathname.startsWith(p + "/"));

  if (isPublic) return harden(NextResponse.next());

  if (await isAuthed(req)) return harden(NextResponse.next());

  // API → 401; pages → redirect to login
  if (pathname.startsWith("/api/")) {
    return harden(new NextResponse("Unauthorized", { status: 401 }));
  }
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", pathname);
  return harden(NextResponse.redirect(url));
}

// Run on everything except Next internals and static assets.
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
