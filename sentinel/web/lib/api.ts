const BASE = process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8080";

export async function api<T = any>(path: string): Promise<T | null> {
  try {
    // Server components fetch from the Next server, not the browser — forward
    // the incoming request's session cookie so guarded endpoints authenticate.
    let cookieHeader = "";
    if (typeof window === "undefined") {
      try {
        const { cookies } = await import("next/headers");
        cookieHeader = cookies().toString();
      } catch {
        /* not in a request scope (build time) — fine, unauthenticated */
      }
    }
    const r = await fetch(`${BASE}${path}`, {
      cache: "no-store",
      credentials: "include",
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}
