import "./globals.css";
import { api } from "../lib/api";

export const metadata = { title: "Sentinel" };
export const dynamic = "force-dynamic";

async function ModeBanner() {
  const cfg = await api<{ mode?: { live?: boolean } }>("/api/config");
  const live = cfg?.mode?.live === true;
  return (
    <div className={`banner ${live ? "live" : "paper"}`}>
      {live
        ? "🔴 LIVE MODE — REAL ORDERS, REAL LOSSES"
        : "🟡 PAPER MODE — simulated fills, live market data"}
    </div>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ModeBanner />
        <nav>
          <a href="/">Live</a>
          <a href="/ledger">Ledger</a>
          <a href="/performance">Performance</a>
          <a href="/config">Config</a>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
