import "./globals.css";
import { api } from "../lib/api";
import { DotPill, fmt } from "../components/ui";
import AutoRefresh, { LogoutButton } from "../components/AutoRefresh";

export const metadata = {
  title: { default: "Sentinel", template: "%s · Sentinel" },
  description: "Discipline-enforcement altcoin trading engine — paper-first, ledger-judged.",
  icons: {
    icon: "data:image/svg+xml," + encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#f5a623"/><text x="16" y="23" font-size="19" text-anchor="middle">⚡</text></svg>`),
  },
};
export const dynamic = "force-dynamic";

async function TopBar() {
  const [cfg, live] = await Promise.all([
    api<any>("/api/config"),
    api<any>("/api/live"),
  ]);
  const isLive = cfg?.mode?.live === true;
  const equity = live?.equity?.equity;
  const openCount = live?.open_positions?.length ?? 0;
  const now = new Date();
  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="bolt">⚡</span>
          <span>
            SENTINEL <span className="bot">Bot</span>
          </span>
        </div>
        <DotPill tone={isLive ? "red" : "green"}>
          {isLive ? "Live" : "Paper"} · IctDisciplineEngine
        </DotPill>
        <div className="spacer" />
        <div className="topstat">
          <div className="lbl">BALANCE</div>
          <div className="val">${fmt(equity ?? 10000, 0)}</div>
        </div>
        <div className="topstat">
          <div className="lbl">EQUITY</div>
          <div className="val">${fmt(equity ?? 10000, 0)}</div>
        </div>
        <div className="topstat">
          <div className="lbl">OPEN POS</div>
          <div className="val" style={{ color: "var(--amber)" }}>{openCount}</div>
        </div>
        <div className="clock">
          {now.toUTCString().slice(0, 16)}
          <br />
          {now.toUTCString().slice(17, 25)} UTC
        </div>
        <AutoRefresh />
        <LogoutButton />
      </header>
      <div className={`modebar ${isLive ? "live" : "paper"}`}>
        {isLive
          ? "live mode — real orders, real losses"
          : "paper trading — simulated fills · live market data · no keys"}
      </div>
    </>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <TopBar />
        <nav className="tabs">
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
