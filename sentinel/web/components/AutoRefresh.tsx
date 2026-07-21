"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";

// Same-origin: /api/* is rewritten to the API by next.config.js.
const API = "";

export default function AutoRefresh({ intervalMs = 15000 }: { intervalMs?: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const [age, setAge] = useState(0);

  useEffect(() => {
    if (pathname.startsWith("/login")) return;
    const tick = setInterval(() => setAge((a) => a + 1), 1000);
    const refresh = setInterval(() => {
      router.refresh();
      setAge(0);
    }, intervalMs);
    return () => { clearInterval(tick); clearInterval(refresh); };
  }, [router, pathname, intervalMs]);

  if (pathname.startsWith("/login")) return null;
  return (
    <span className="pill" title="dashboard auto-refreshes" data-testid="refresh-chip">
      <span className="dot" style={{ background: age < 3 ? "var(--green)" : "var(--dim)" }} />
      {age < 2 ? "live" : `${age}s ago`}
    </span>
  );
}

export function LogoutButton() {
  const router = useRouter();
  const pathname = usePathname();
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/auth/status`, { credentials: "include" })
      .then((r) => r.json())
      .then((j) => setEnabled(!!j.enabled))
      .catch(() => setEnabled(false));
  }, []);

  if (!enabled || pathname.startsWith("/login")) return null;
  return (
    <button
      className="pill"
      style={{ cursor: "pointer", background: "transparent" }}
      data-testid="logout"
      onClick={async () => {
        await fetch(`${API}/api/auth/logout`, {
          method: "POST", credentials: "include",
        });
        router.push("/login");
        router.refresh();
      }}
    >
      sign out
    </button>
  );
}
