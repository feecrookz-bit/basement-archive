import { api } from "../../lib/api";
import { Pill, Section } from "../../components/ui";

export const dynamic = "force-dynamic";

export default async function ConfigPage() {
  const data = await api<any>("/api/config");
  if (!data) return <p className="muted">API unreachable.</p>;
  return (
    <>
      <p style={{ marginTop: 0 }}>
        <Pill tone="amber">READ-ONLY</Pill>{" "}
        <span className="muted">
          The dashboard cannot change anything — edits happen in config.yaml
          and take effect on restart, snapshotted as a new version. No
          discretionary overrides by design.
        </span>
      </p>
      <Section title="Active version">
        {data.current ? (
          <>
            <p className="muted" style={{ marginTop: 0 }}>
              #{data.current.id} · loaded{" "}
              {String(data.current.loaded_at).slice(0, 19)} ·{" "}
              {String(data.current.content_hash).slice(0, 12)}…
            </p>
            <pre>{JSON.stringify(data.current.content, null, 2)}</pre>
          </>
        ) : (
          <p className="muted" style={{ margin: 0 }}>no version recorded yet</p>
        )}
      </Section>
      <Section title="Version history">
        <div className="tablewrap"><table>
          <thead><tr><th>id</th><th>loaded</th><th>hash</th></tr></thead>
          <tbody>
            {(data.versions || []).map((v: any) => (
              <tr key={v.id}>
                <td className="num">{v.id}</td>
                <td className="muted">{String(v.loaded_at).slice(0, 19)}</td>
                <td className="muted">{String(v.content_hash).slice(0, 16)}…</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </Section>
    </>
  );
}
