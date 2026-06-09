// §2 read contract — the single typed, read-only boundary the presentation
// layer touches. Drafted from the task spec; the *field set* below is the target
// shape the server-side accessor maps engine output onto. It must be reconciled
// against the real engine output shape in Phase 0 (Discovery) before the accessor
// is implemented — see PLAN.md.
//
// Rules encoded here (from §2):
//   - Every engine-derived value is a `Traced<T>` => nullable + provenance-bound.
//   - No `any`. No raw engine object is re-exported. No engine internal type leaks.
//   - The accessor does NO calculation. Display formatting (decimal -> %) lives
//     in pure formatters (see ../formatters), never here.

import type { Traced } from './trace.ts';

// ── Leaf reads ──────────────────────────────────────────────────────────────

/** A market and the engine probability behind its hit-rate (§4). */
export interface MarketRead {
  /** Human-facing market name. Codename-free at the boundary (§1.2). Framing, not a fact — untraced. */
  readonly label: string;
  /** Engine-emitted probability, decimal in [0,1]. Formatted to a % by the pure formatter (§4). */
  readonly probability: Traced<number>;
}

/** One stat cell on the cheat sheet (§5). `value` is raw; formatting is display-layer. */
export interface StatCell {
  readonly label: string;
  readonly value: Traced<number | string>;
}

/** A team's cheat-sheet block (§5). */
export interface TeamCheatSheetRead {
  /** Team name (display). */
  readonly teamName: string;
  /**
   * Key into the STATIC team->kit palette config (presentation only, §3/§5).
   * Never sourced from engine data; resolved to colours in the UI.
   */
  readonly paletteKey: string;
  readonly teamStats: readonly StatCell[];
  readonly playerStats: readonly StatCell[];
  /** Provenance line reflecting the real basis (§1.4). Absent => no line, not a filler line. */
  readonly provenance: Traced<string>;
}

/** A single fixture in the context strip (§7). Only real fixtures — no projections. */
export interface OpponentFixtureRead {
  readonly fixtureId: string;
  readonly opponentName: string;
}

/** Fixture-context strip (§7); embedded by the cheat sheet (§5). */
export interface FixtureContextRead {
  /** Group/competition. Absent => explicit empty state (§7). */
  readonly group: Traced<string>;
  /** Real upcoming opponents only; may be empty (renders the designed empty state). */
  readonly opponents: readonly OpponentFixtureRead[];
}

/** A pick/selection on a slip. */
export interface SelectionRead {
  readonly id: string;
  readonly market: MarketRead | null;
  /**
   * One-line rationale (§6). MUST originate verbatim from a deterministic engine
   * field. The UI never assembles this from numbers. Absent => no rationale
   * element renders (not an empty quote). If the engine emits no such field
   * project-wide, this stays permanently `unavailable()` and an integration note
   * ships instead — see PLAN.md Phase 6.
   */
  readonly rationale: Traced<string>;
}

// ── Root read ─────────────────────────────────────────────────────────────────

/** The full read surface for one fixture. Partial data => partial contract, never a throw (§2). */
export interface FixtureRead {
  readonly fixtureId: string;
  readonly context: FixtureContextRead | null;
  readonly homeTeam: TeamCheatSheetRead | null;
  readonly awayTeam: TeamCheatSheetRead | null;
  /** Markets that carry hit-rates (§4). May be empty. */
  readonly markets: readonly MarketRead[];
  /** Selections / picks. May be empty. */
  readonly selections: readonly SelectionRead[];
}

/**
 * Server-side accessor signature (§2, "Builder side"). Implementation is BLOCKED
 * on the real engine and is intentionally not provided here — providing a body
 * would mean inventing engine output, which §1.1 forbids. Phase 1 implements this
 * as a pure mapping (engine output -> FixtureRead) with NO calculation, returning
 * a partial FixtureRead for partial data rather than throwing.
 */
export type ReadFixture = (fixtureId: string) => Promise<FixtureRead>;
