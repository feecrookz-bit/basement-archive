import { api } from "../../lib/api";

export const dynamic = "force-dynamic";

function EquityCurve({ points }: { points: { equity: number }[] }) {
  if (points.length < 2) return <p className="muted">not enough data yet</p>;
  const vals = points.map((p) => Number(p.equity));
  const min = Math.min(...vals), max = Math.max(...vals);
  const W = 900, H = 200, pad = 8;
  const x = (i: number) => pad + (i / (vals.length - 1)) * (W - 2 * pad);
  const y = (v: number) =>
    max === min ? H / 2 : H - pad - ((v - min) / (max - min)) * (H - 2 * pad);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", background: "var(--panel)", borderRadius: 8 }}>
      <path d={d} fill="none" stroke={up ? "var(--green)" : "var(--red)"} strokeWidth={1.5} />
    </svg>
  );
}

export default async function Performance() {
  const data = await api<any>("/api/performance");
  if (!data) return <p className="muted">API unreachable.</p>;
  const reports = data.reports || [];
  return (
    <>
      <h1>Performance</h1>
      <h2>Equity curve</h2>
      <EquityCurve points={data.equity_curve || []} />
      <h2>Coach reports</h2>
      {reports.map((r: any, i: number) => (
        <div className="card" key={i} style={{ marginBottom: 12 }}>
          <p>
            <b>{r.period}</b>{" "}
            <span className="muted">{String(r.ts).slice(0, 16)}</span>
          </p>
          <p>{r.narrative}</p>
          <details>
            <summary className="muted">metrics</summary>
            <pre>{JSON.stringify(r.metrics, null, 2)}</pre>
          </details>
        </div>
      ))}
      {!reports.length && <p className="muted">no reports yet — the Coach runs nightly</p>}
    </>
  );
}
