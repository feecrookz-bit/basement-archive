import { api } from "../../lib/api";
import { Section, Stat, fmt } from "../../components/ui";

export const dynamic = "force-dynamic";

function EquityCurve({ points }: { points: { equity: number }[] }) {
  if (points.length < 2) return <p className="muted">not enough data yet</p>;
  const vals = points.map((p) => Number(p.equity));
  const min = Math.min(...vals), max = Math.max(...vals);
  const W = 900, H = 200, pad = 8;
  const x = (i: number) => pad + (i / (vals.length - 1)) * (W - 2 * pad);
  const y = (v: number) =>
    max === min ? H / 2 : H - pad - ((v - min) / (max - min)) * (H - 2 * pad);
  const d = vals
    .map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
    .join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      style={{ width: "100%", background: "var(--bg2)", borderRadius: 8,
               border: "1px solid var(--border)" }}
    >
      <path d={d} fill="none"
            stroke={up ? "var(--green)" : "var(--red)"} strokeWidth={1.6} />
    </svg>
  );
}

export default async function Performance() {
  const data = await api<any>("/api/performance");
  if (!data) return <p className="muted">API unreachable.</p>;
  const reports = data.reports || [];
  const latest = reports[0]?.metrics || {};
  return (
    <>
      <Section title="Scoreboard" tone="green">
        <div className="stats">
          <Stat label="Win Rate" value={latest.win_rate != null ? `${latest.win_rate}%` : "—"} tone="amber" />
          <Stat label="Avg R" value={latest.avg_r ?? "—"} tone={Number(latest.avg_r) >= 0 ? "green" : "red"} />
          <Stat label="Profit Factor" value={latest.profit_factor ?? "—"} />
          <Stat label="Net PnL" value={latest.net_pnl_quote != null ? fmt(latest.net_pnl_quote) : "—"}
                tone={Number(latest.net_pnl_quote) >= 0 ? "green" : "red"} />
          <Stat label="Max DD" value={latest.max_drawdown_quote != null ? fmt(latest.max_drawdown_quote) : "—"} tone="red" />
          <Stat label="Trades" value={latest.trades ?? 0} />
        </div>
      </Section>

      <Section title="Equity curve">
        <EquityCurve points={data.equity_curve || []} />
      </Section>

      <Section title="Coach reports">
        {reports.map((r: any, i: number) => (
          <div className="poscard" key={i}>
            <p style={{ marginTop: 0 }}>
              <b style={{ color: "var(--amber)" }}>{r.period.toUpperCase()}</b>{" "}
              <span className="muted">{String(r.ts).slice(0, 16)}</span>
            </p>
            <p style={{ marginBottom: 0 }}>{r.narrative}</p>
            <details>
              <summary className="muted">metrics by setup / regime / pair</summary>
              <pre>{JSON.stringify(r.metrics, null, 2)}</pre>
            </details>
          </div>
        ))}
        {!reports.length && (
          <p className="muted" style={{ margin: 0 }}>
            no reports yet — the Coach runs nightly
          </p>
        )}
      </Section>
    </>
  );
}
