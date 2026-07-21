import { NextRequest, NextResponse } from "next/server";

const COOKIE = "sentinel_session";
const API = process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8080";

// Cache the auth-enabled probe briefly so we don't hit the API per request.
let cached: { enabled: boolean; at: number } | null = null;

async function authEnabled(): Promise<boolean> {
  if (cached && Date.now() - cached.at < 30_000) return cached.enabled;
  try {
    const r = await fetch(`${API}/api/auth/status`, { cache: "no-store" });
    const j = await r.json();
    cached = { enabled: !!j.enabled, at: Date.now() };
  } catch {
    cached = { enabled: false, at: Date.now() };
  }
  return cached.enabled;
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  // /api/* is proxied to the backend (next.config.js rewrites) — the API
  // does its own 401s, so never bounce those requests to /login.
  if (pathname.startsWith("/login") || pathname.startsWith("/api") ||
      pathname.startsWith("/_next") || pathname.startsWith("/favicon")) {
    return NextResponse.next();
  }
  if (!(await authEnabled())) return NextResponse.next();
  if (!req.cookies.get(COOKIE)?.value) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
