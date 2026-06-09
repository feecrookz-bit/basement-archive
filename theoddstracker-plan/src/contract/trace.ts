// §2 read contract — provenance primitive.
//
// The Integrity Lock (§1.1) says: no value renders unless it traces to a real
// value the engine emitted. We make that *structural* rather than a convention.
//
// Every engine-derived value crosses the boundary as a `Traced<T>`: either a
// present value paired with the provenance the engine reported, or an explicit
// absence (value AND trace both null). There is no third shape — so it is
// impossible to render a value the UI cannot point back to an engine output,
// and equally impossible to render a "trace marker" (§3) with nothing behind
// it. This single type is what the §10 CI gate keys off.

/** Identifies the exact engine output a value came from. Powers the §3 trace marker. */
export interface TraceRef {
  /**
   * Stable reference to the engine output this value was read from — e.g. an
   * emitter id plus the field path. Codename-free (§1.2): this can reach the DOM
   * via the trace marker, so it must never carry an internal codename.
   */
  readonly source: string;
  /**
   * Real source/sample qualifier shown in provenance lines (§1.4). Generic is
   * fine; inflated is not. Null when the engine reported no basis.
   */
  readonly basis: string | null;
}

/**
 * A value that has crossed the read boundary. Present => has a TraceRef.
 * Absent => both null (absence is first-class per §2; never invented per §1.1).
 */
export type Traced<T> =
  | { readonly value: T; readonly trace: TraceRef }
  | { readonly value: null; readonly trace: null };

/** Construct a present, traced value. The ONLY way the UI gets a renderable value. */
export function traced<T>(value: T, trace: TraceRef): Traced<T> {
  return { value, trace };
}

/** The explicit unavailable state (§1.1). Use this, never a 0 / "" / guess. */
export function unavailable<T>(): Traced<T> {
  return { value: null, trace: null };
}

/** Type guard: narrows to the present shape so callers can read `.value`/`.trace`. */
export function isPresent<T>(t: Traced<T>): t is { value: T; trace: TraceRef } {
  return t.value !== null && t.trace !== null;
}
