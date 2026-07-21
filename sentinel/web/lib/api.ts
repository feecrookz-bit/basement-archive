const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export async function api<T = any>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${BASE}${path}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}
