import { api } from "../../lib/api";

export const dynamic = "force-dynamic";

export default async function ConfigPage() {
  const data = await api<any>("/api/config");
  if (!data) return <p className="muted">API unreachable.</p>;
  return (
    <>
      <h1>Config <span className="pill warn">read-only</span></h1>
      <p className="muted">
        The dashboard cannot change anything — edits happen in config.yaml and
        take effect on restart, snapshotted as a new version. No discretionary
        overrides by design.
      </p>
      <h2>Active version</h2>
      {data.current ? (
        <>
          <p className="muted">
            #{data.current.id} · loaded {String(data.current.loaded_at).slice(0, 19)} ·{" "}
            {String(data.current.content_hash).slice(0, 12)}…
          </p>
          <pre>{JSON.stringify(data.current.content, null, 2)}</pre>
        </>
      ) : (
        <p className="muted">no version recorded yet</p>
      )}
      <h2>Version history</h2>
      <table>
        <thead><tr><th>id</th><th>loaded</th><th>hash</th></tr></thead>
        <tbody>
          {(data.versions || []).map((v: any) => (
            <tr key={v.id}>
              <td>{v.id}</td>
              <td className="muted">{String(v.loaded_at).slice(0, 19)}</td>
              <td className="muted">{String(v.content_hash).slice(0, 16)}…</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
