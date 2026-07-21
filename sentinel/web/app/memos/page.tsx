import { api } from "../../lib/api";
import { Pill, Section, fmt } from "../../components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Memos" };

function Stars({ n }: { n: number }) {
  return (
    <span style={{ color: "var(--amber)", letterSpacing: 2 }}>
      {"★".repeat(n)}
      <span className="dim">{"☆".repeat(Math.max(0, 5 - n))}</span>
    </span>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone = status === "APPROVED" ? "green" : status === "WATCHLIST" ? "amber" : "red";
  const label =
    status === "APPROVED" ? "✓ APPROVED — trade executed"
    : status === "WATCHLIST" ? "👁 WATCHLIST — good setup, no capacity"
    : "✕ REJECTED — do not trade";
  return <Pill tone={tone}>{label}</Pill>;
}

function MemoCard({ m }: { m: any }) {
  const risk = m.risk || {};
  const plan = m.plan || {};
  const sig = m.signal || {};
  return (
    <div className="poscard" data-testid="memo-card">
      <div className="row1">
        <b>DECISION MEMO</b>
        <span className="sym">{m.pair}</span>
        <Pill tone="blue">{m.setup_type}</Pill>
        <Pill tone="green">{(m.side || "long").toUpperCase()}</Pill>
        <span className="spacer" style={{ flex: 1 }} />
        <span className="feed-ts">{String(m.ts).slice(0, 16)}</span>
      </div>
      <div className="memo-rows">
        <div className="memo-row">
          <span className="lbl">1. SIGNAL STRENGTH</span>
          <span>
            <Stars n={sig.stars ?? 3} />{" "}
            {sig.conviction != null && (
              <span className="muted">conv {fmt(sig.conviction, 2)}</span>
            )}{" "}
            {(sig.agreeing_setups || []).length > 1 && (
              <Pill tone="green">×{sig.agreeing_setups.length} confluence</Pill>
            )}
          </span>
        </div>
        <div className="memo-row">
          <span className="lbl">2. RISK LEVEL</span>
          <span>
            <Pill tone={risk.rating === "ELEVATED" ? "red" : risk.rating === "LOW" ? "green" : "amber"}>
              {risk.rating || "MODERATE"}
            </Pill>{" "}
            <span className="muted">{risk.risk_pct}% of equity at stop</span>
          </span>
        </div>
        <div className="memo-row">
          <span className="lbl">3. TRADE PLAN</span>
          <span className="num">
            entry {fmt(plan.entry, 4)} · stop {fmt(plan.stop, 4)} · target{" "}
            {plan.target != null ? fmt(plan.target, 4) : "—"}
            {plan.rr != null && <span className="muted"> · R:R 1:{fmt(plan.rr, 2)}</span>}
          </span>
        </div>
        <div className="memo-row">
          <span className="lbl">4. FINAL STATUS</span>
          <span>
            <StatusPill status={m.status} />
            {!!(m.reasons || []).length && (
              <span style={{ marginLeft: 6 }}>
                {(m.reasons || []).map((x: string) => (
                  <Pill key={x} tone={m.status === "WATCHLIST" ? "amber" : "red"}>{x}</Pill>
                ))}
              </span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}

export default async function Memos() {
  const memos = await api<any[]>("/api/memos?limit=30");
  if (!memos) return <p className="muted">API unreachable.</p>;
  return (
    <>
      <p className="muted" style={{ marginTop: 0 }}>
        One clear verdict per proposal — take it, watch it, or skip it. The
        engine acts on APPROVED automatically (paper by default); WATCHLIST
        means the setup was fine but every slot/budget was taken; REJECTED is
        the risk system saying no. Nothing here is a button on purpose.
      </p>
      <Section title="Final decision memos" tone="amber">
        {memos.map((m: any, i: number) => (
          <MemoCard key={i} m={m} />
        ))}
        {!memos.length && (
          <p className="muted" style={{ margin: 0 }}>
            no memos yet — they appear as soon as the analyst proposes and
            the risk engine rules
          </p>
        )}
      </Section>
    </>
  );
}
