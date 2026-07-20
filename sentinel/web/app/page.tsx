import { api } from "../lib/api";

export const dynamic = "force-dynamic";

export default async function Live() {
  const data = await api<any>("/api/live");
  if (!data) return <p className="muted">API unreachable.</p>;
  const r = data.regime;
  const wl = data.watchlist?.entries || [];
  const ready = data.paper_readiness;
  return (
    <>
      <h1>Live</h1>
      <div className="grid">
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Regime</h2>
          {r ? (
            <>
              <p>
                BTC: <b>{r.btc_state}</b>{" "}
                <span className={`pill ${r.trading_allowed ? "good" : "bad"}`}>
                  {r.trading_allowed ? "entries permitted" : "flat / no entries"}
                </span>
              </p>
              <p className="muted">
                1h move {r.btc_move_1h_pct}% · ATR pct {r.atr_percentile} · kill
                flags: {(r.kill_flags || []).join(", ") || "none"}
              </p>
            </>
          ) : (
            <p className="muted">no snapshot yet</p>
          )}
        </div>
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Paper → live gate</h2>
          {ready ? (
            <p>
              {ready.paper_days} / 30 paper days · {ready.paper_trades} trades{" "}
              <span className={`pill ${ready.ready ? "good" : "warn"}`}>
                {ready.ready ? "history sufficient" : "keep papering"}
              </span>
            </p>
          ) : (
            <p className="muted">no paper history yet</p>
          )}
        </div>
      </div>

      <h2>Open positions</h2>
      <table>
        <thead>
          <tr><th>pair</th><th>setup</th><th>mode</th><th>qty</th><th>realized PnL</th></tr>
        </thead>
        <tbody>
          {(data.open_positions || []).map((p: any) => (
            <tr key={p.trade_id}>
              <td>{p.pair}</td><td>{p.setup_type}</td><td>{p.mode}</td>
              <td>{p.open_qty}</td>
              <td className={p.realized_pnl_quote >= 0 ? "pill good" : "pill bad"}>
                {Number(p.realized_pnl_quote).toFixed(2)}
              </td>
            </tr>
          ))}
          {!data.open_positions?.length && (
            <tr><td colSpan={5} className="muted">flat — the default state</td></tr>
          )}
        </tbody>
      </table>

      <h2>Watchlist (RS ranked)</h2>
      <table>
        <thead>
          <tr><th>#</th><th>pair</th><th>RS</th><th>24h vol</th><th>flags</th></tr>
        </thead>
        <tbody>
          {wl.map((e: any) => (
            <tr key={e.pair}>
              <td>{e.rank}</td><td>{e.pair}</td><td>{e.rs_score}</td>
              <td>${(e.vol_24h_usd / 1e6).toFixed(1)}M</td>
              <td className="muted">
                {Object.entries(e.flags || {})
                  .filter(([, v]) => v)
                  .map(([k]) => k)
                  .join(", ") || "—"}
              </td>
            </tr>
          ))}
          {!wl.length && <tr><td colSpan={5} className="muted">no snapshot yet</td></tr>}
        </tbody>
      </table>
    </>
  );
}
