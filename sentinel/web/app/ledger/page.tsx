import { api } from "../../lib/api";
import { Pill, Section, fmt } from "../../components/ui";

export const dynamic = "force-dynamic";

export default async function Ledger() {
  const data = await api<any>("/api/ledger?limit=100");
  if (!data) return <p className="muted">API unreachable.</p>;
  return (
    <>
      <p className="muted" style={{ marginTop: 0 }}>
        Every trade carries its full reasoning snapshot — indicators, regime,
        config version — captured when it was proposed. Append-only; nothing
        is edited after the fact.
      </p>
      <Section title="Trades" tone="green">
        <div className="tablewrap"><table>
          <thead>
            <tr>
              <th>Opened</th><th>Symbol</th><th>Setup</th><th>Mode</th>
              <th>Entry / Stop</th><th>Status</th><th>PnL</th><th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {(data.trades || []).map((t: any) => (
              <tr key={t.trade_id}>
                <td className="muted">{String(t.opened_at).slice(0, 16)}</td>
                <td className="sym">{t.pair}</td>
                <td><Pill tone="blue">{t.setup_type}</Pill></td>
                <td><Pill tone={t.mode === "live" ? "red" : "amber"}>{t.mode}</Pill></td>
                <td className="num">{fmt(t.entry_price, 4)} / {fmt(t.stop_price, 4)}</td>
                <td>
                  <Pill tone={t.is_closed ? "" : "green"}>
                    {t.is_closed ? "closed" : "open"}
                  </Pill>
                </td>
                <td>
                  <Pill tone={Number(t.realized_pnl_quote) >= 0 ? "green" : "red"}>
                    {fmt(t.realized_pnl_quote, 2)}
                  </Pill>
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
              <tr>
                <td colSpan={8} className="muted">
                  no trades yet — flat is the default
                </td>
              </tr>
            )}
          </tbody>
        </table></div>
      </Section>

      <Section title="Risk veto — rejected proposals">
        <div className="tablewrap"><table>
          <thead>
            <tr><th>ts</th><th>Symbol</th><th>Setup</th><th>Reasons</th></tr>
          </thead>
          <tbody>
            {(data.rejected || []).map((r: any, i: number) => (
              <tr key={i}>
                <td className="muted">{String(r.ts).slice(0, 16)}</td>
                <td className="sym">{r.pair}</td>
                <td><Pill tone="blue">{r.setup_type}</Pill></td>
                <td>
                  {(r.reject_reasons || []).map((x: string) => (
                    <Pill key={x} tone="red">{x}</Pill>
                  ))}
                </td>
              </tr>
            ))}
            {!data.rejected?.length && (
              <tr><td colSpan={4} className="muted">none yet</td></tr>
            )}
          </tbody>
        </table></div>
      </Section>
    </>
  );
}
