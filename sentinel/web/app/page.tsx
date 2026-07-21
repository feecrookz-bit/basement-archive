import { api } from "../lib/api";
import { DotPill, Pill, Section, Stat, fmt } from "../components/ui";

export const dynamic = "force-dynamic";

function PositionCard({ p }: { p: any }) {
  const entry = Number(p.entry_price);
  const stop = Number(p.current_stop ?? p.stop_price);
  const targets = Array.isArray(p.targets) ? p.targets : [];
  const tp = Number(targets[0]?.price ?? entry + 2 * (entry - Number(p.stop_price)));
  const span = tp - Number(p.stop_price) || 1;
  const markPct = Math.min(97, Math.max(1, (100 * (entry - Number(p.stop_price))) / span));
  return (
    <div className="poscard">
      <div className="row1">
        <Pill tone="green">LONG</Pill>
        <span className="pair">{p.pair}</span>
        <span className="muted">× {fmt(p.open_qty, 4)}</span>
        <Pill tone={p.mode === "live" ? "red" : "amber"}>{p.mode}</Pill>
        <span className="spacer" style={{ flex: 1 }} />
        {p.evidence?.conviction != null && (
          <Pill tone="amber">conv {fmt(p.evidence.conviction, 2)}</Pill>
        )}
        {Array.isArray(p.evidence?.agreeing_setups) && p.evidence.agreeing_setups.length > 1 && (
          <Pill tone="green">×{p.evidence.agreeing_setups.length} confluence</Pill>
        )}
        <Pill tone="blue">{p.setup_type}</Pill>
        {p.last_r != null && (
          <Pill tone={Number(p.last_r) >= 0 ? "green" : "red"}>
            {Number(p.last_r) >= 0 ? "+" : ""}
            {fmt(p.last_r, 2)}R
          </Pill>
        )}
      </div>
      <div className="rbar">
        <span className="mark" style={{ left: `${markPct}%` }} />
      </div>
      <div className="rlegend">
        <span className="sl">SL {fmt(p.stop_price, 4)}</span>
        <span className="mid">
          ENTRY {fmt(entry, 4)}
          {stop >= entry ? " · stop @ BE+" : ""}
        </span>
        <span className="tp">TP {fmt(tp, 4)}</span>
      </div>
    </div>
  );
}

export default async function Live() {
  const [data, activity] = await Promise.all([
    api<any>("/api/live"),
    api<any[]>("/api/activity?limit=15"),
  ]);
  if (!data) return <p className="muted">API unreachable.</p>;
  const r = data.regime;
  const wl = data.watchlist?.entries || [];
  const ready = data.paper_readiness;
  const gatePct = Math.min(100, (100 * (ready?.paper_days ?? 0)) / 30);
  return (
    <>
      <Section title="Regime" tone={r?.trading_allowed ? "green" : undefined}>
        {r ? (
          <>
            <div className="stats">
              <Stat label="BTC State" value={r.btc_state} tone="amber" />
              <Stat
                label="Entries"
                value={r.trading_allowed ? "PERMITTED" : "FLAT"}
                tone={r.trading_allowed ? "green" : "red"}
              />
              <Stat label="1h Move" value={`${fmt(r.btc_move_1h_pct, 2)}%`} />
              <Stat label="ATR pct" value={fmt(r.atr_percentile, 0)} />
            </div>
            <p className="muted" style={{ marginBottom: 0 }}>
              kill flags:{" "}
              {(r.kill_flags || []).length
                ? (r.kill_flags || []).map((f: string) => (
                    <Pill key={f} tone="red">{f}</Pill>
                  ))
                : "none"}
            </p>
          </>
        ) : (
          <p className="muted">no snapshot yet</p>
        )}
      </Section>

      {data.setup_trust && Object.keys(data.setup_trust).length > 0 && (
        <Section title="Setup trust — the ledger self-tuner">
          <div className="stats">
            {Object.entries(data.setup_trust).map(([setup, mult]: [string, any]) => (
              <Stat
                key={setup}
                label={setup}
                value={`${fmt(mult, 2)}×`}
                tone={Number(mult) > 1.05 ? "green" : Number(mult) < 0.95 ? "red" : ""}
              />
            ))}
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>
            Conviction weight each setup has earned from its own realized R.
            1.00× = neutral (cold start); winners rise, losers fade and get gated.
          </p>
        </Section>
      )}

      <Section title="AutoTrader — open positions" tone="green">
        {(data.open_positions || []).map((p: any) => (
          <PositionCard key={p.trade_id} p={p} />
        ))}
        {!data.open_positions?.length && (
          <p className="muted" style={{ margin: 0 }}>
            No active trades — flat is the default state.
          </p>
        )}
      </Section>

      <Section title="Paper → live gate">
        <p style={{ margin: 0 }}>
          <span className="num" style={{ color: "var(--amber)", fontWeight: 700 }}>
            {ready?.paper_days ?? 0}
          </span>
          <span className="muted"> / 30 paper days · {ready?.paper_trades ?? 0} trades </span>
          <Pill tone={ready?.ready ? "green" : "amber"}>
            {ready?.ready ? "history sufficient" : "keep papering"}
          </Pill>
        </p>
        <div className="gatebar">
          <div
            className={`fill ${ready?.ready ? "done" : ""}`}
            style={{ width: `${gatePct}%` }}
          />
        </div>
      </Section>

      <Section title="Signals panel — RS watchlist">
        <div className="tablewrap"><table>
          <thead>
            <tr>
              <th>#</th><th>Symbol</th><th>RS</th><th>24h Vol</th><th>Bias</th><th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {wl.map((e: any) => (
              <tr key={e.pair}>
                <td className="muted">{e.rank}</td>
                <td className="sym">{e.pair}</td>
                <td className="num">{fmt(e.rs_score, 2)}</td>
                <td>${fmt(e.vol_24h_usd / 1e6, 1)}M</td>
                <td>
                  {e.higher_lows_vs_btc ? (
                    <Pill tone="green">HL vs BTC</Pill>
                  ) : (
                    <span className="dim">——</span>
                  )}
                </td>
                <td>
                  {Object.entries(e.flags || {})
                    .filter(([, v]) => v)
                    .map(([k]) => (
                      <Pill key={k} tone={k === "unlock_blacklist" ? "red" : "amber"}>
                        {k.replace(/_/g, " ").toUpperCase()}
                      </Pill>
                    ))}
                  {!Object.values(e.flags || {}).some(Boolean) && (
                    <span className="dim">——</span>
                  )}
                </td>
              </tr>
            ))}
            {!wl.length && (
              <tr><td colSpan={6} className="muted">no snapshot yet</td></tr>
            )}
          </tbody>
        </table></div>
      </Section>

      {!!data.ict?.length && (() => {
        const first = data.ict[0];
        const sess = first?.session_state || {};
        const lv = first?.levels || {};
        return (
          <div className="grid">
            <Section title={`Sessions — ${first.pair}`} tone="amber">
              {["asia", "london", "newyork"].map((n) => {
                const s = sess[n] || {};
                return (
                  <div className="poscard" key={n}>
                    <div className="row1">
                      <b style={{ textTransform: "uppercase" }}>{n}</b>
                      <Pill tone={s.status === "open" ? "green" : ""}>
                        {s.status || "waiting"}
                      </Pill>
                      {s.high_swept && <Pill tone="amber">H SWEPT</Pill>}
                      {s.low_swept && <Pill tone="amber">L SWEPT</Pill>}
                    </div>
                    <p className="muted" style={{ margin: "6px 0 0" }}>
                      H {s.high != null ? fmt(s.high, 4) : "—"} · L{" "}
                      {s.low != null ? fmt(s.low, 4) : "—"}
                    </p>
                  </div>
                );
              })}
              <p className="muted" style={{ marginBottom: 0 }}>
                PDH <span className="num">{lv.pdh != null ? fmt(lv.pdh, 4) : "—"}</span>
                {lv.pdh_hit && <Pill tone="green">HIT</Pill>} · PDL{" "}
                <span className="num">{lv.pdl != null ? fmt(lv.pdl, 4) : "—"}</span>
                {lv.pdl_hit && <Pill tone="red">HIT</Pill>}
              </p>
            </Section>
            <Section title="OB / FVG — fresh zones" tone="amber">
              {data.ict.flatMap((row: any) =>
                [...(row.zones?.fvgs || []).map((g: any, i: number) => (
                  <div className="poscard" key={`${row.pair}-g${i}`}>
                    <div className="row1">
                      <Pill tone="green">BULL</Pill>
                      <Pill tone="blue">FVG</Pill>
                      <b>{row.pair}</b>
                    </div>
                    <p className="muted" style={{ margin: "6px 0 0" }}>
                      HIGH {fmt(g.high, 4)} · LOW {fmt(g.low, 4)} · MID{" "}
                      {fmt((Number(g.high) + Number(g.low)) / 2, 4)}
                    </p>
                  </div>
                )),
                ...(row.zones?.order_blocks || []).map((o: any, i: number) => (
                  <div className="poscard" key={`${row.pair}-o${i}`}>
                    <div className="row1">
                      <Pill tone="green">BULL</Pill>
                      <Pill tone="amber">OB</Pill>
                      <b>{row.pair}</b>
                    </div>
                    <p className="muted" style={{ margin: "6px 0 0" }}>
                      HIGH {fmt(o.high, 4)} · LOW {fmt(o.low, 4)}
                    </p>
                  </div>
                ))]
              )}
              {!data.ict.some((r: any) =>
                (r.zones?.fvgs?.length || 0) + (r.zones?.order_blocks?.length || 0) > 0) && (
                <p className="muted" style={{ margin: 0 }}>no fresh zones</p>
              )}
            </Section>
          </div>
        );
      })()}

      {!!activity?.length && (
        <Section title="Activity">
          {activity.map((a: any, i: number) => (
            <div className="feed-row" key={i} data-testid="activity-row">
              <span className="feed-ts">
                {String(a.ts).slice(11, 19) || String(a.ts).slice(0, 16)}
              </span>
              <Pill tone={a.module === "risk" ? "red" : a.module === "executor"
                ? "green" : a.module === "regime" ? "amber" : "blue"}>
                {a.module}
              </Pill>
              <span>{a.summary}</span>
            </div>
          ))}
        </Section>
      )}

      {!!data.recent_halts?.length && (
        <Section title="Halts">
          <div className="tablewrap"><table>
            <thead><tr><th>ts</th><th>scope</th><th>action</th><th>reason</th></tr></thead>
            <tbody>
              {data.recent_halts.map((h: any, i: number) => (
                <tr key={i}>
                  <td className="muted">{String(h.ts).slice(0, 16)}</td>
                  <td><Pill tone="red">{h.scope}</Pill></td>
                  <td>{h.action}</td>
                  <td className="muted">{h.reason}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </Section>
      )}
    </>
  );
}
