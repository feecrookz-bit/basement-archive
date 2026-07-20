import { api } from "../../lib/api";

export const dynamic = "force-dynamic";

export default async function Ledger() {
  const data = await api<any>("/api/ledger?limit=100");
  if (!data) return <p className="muted">API unreachable.</p>;
  return (
    <>
      <h1>Ledger</h1>
      <p className="muted">
        Every trade carries its full reasoning snapshot — indicators, regime,
        config version — from the moment it was proposed. Nothing is edited
        after the fact.
      </p>
      <h2>Trades</h2>
      <table>
        <thead>
          <tr>
            <th>opened</th><th>pair</th><th>setup</th><th>mode</th>
            <th>entry / stop</th><th>status</th><th>PnL</th><th>evidence</th>
          </tr>
        </thead>
        <tbody>
          {(data.trades || []).map((t: any) => (
            <tr key={t.trade_id}>
              <td className="muted">{String(t.opened_at).slice(0, 16)}</td>
              <td>{t.pair}</td>
              <td>{t.setup_type}</td>
              <td>{t.mode}</td>
              <td>{t.entry_price} / {t.stop_price}</td>
              <td>{t.is_closed ? "closed" : "open"}</td>
              <td className={t.realized_pnl_quote >= 0 ? "pill good" : "pill bad"}>
                {Number(t.realized_pnl_quote || 0).toFixed(2)}
              </td>
              <td>
                <details>
                  <summary className="muted">snapshot</summary>
                  <pre>{JSON.stringify(t.evidence, null, 2)}</pre>
                </details>
              </td>
            </tr>
          ))}
          {!data.trades?.length && (
            <tr><td colSpan={8} className="muted">no trades yet — flat is the default</td></tr>
          )}
        </tbody>
      </table>

      <h2>Rejected proposals (risk veto)</h2>
      <table>
        <thead><tr><th>ts</th><th>pair</th><th>setup</th><th>reasons</th></tr></thead>
        <tbody>
          {(data.rejected || []).map((r: any, i: number) => (
            <tr key={i}>
              <td className="muted">{String(r.ts).slice(0, 16)}</td>
              <td>{r.pair}</td><td>{r.setup_type}</td>
              <td>{(r.reject_reasons || []).join(", ")}</td>
            </tr>
          ))}
          {!data.rejected?.length && (
            <tr><td colSpan={4} className="muted">none yet</td></tr>
          )}
        </tbody>
      </table>
    </>
  );
}
