// §4 Feature 1 — hit-rate formatter.
//
// Pure, side-effect-free, and the ONLY place probability display math lives
// (§2: the accessor and engine do no display formatting). It re-expresses an
// engine probability as an "X% hit rate" string.
//
// Explicit rounding rule (the spec requires one to be stated and tested):
//   round the percentage to the NEAREST WHOLE PERCENT, halves rounding UP
//   (i.e. toward +infinity). 12.5% -> 13%, 12.4% -> 12%.
//
// Domain: input MUST be an engine probability in [0,1]. Out-of-domain input is
// an engine-contract violation, not a user state, so it throws — it must never
// be silently coerced into a plausible-looking number (§1.1). Absence (no
// probability) is handled UPSTREAM by the Traced<T> boundary and rendered as the
// explicit unavailable state; this function is only ever called with a real value.

/** Formats an engine probability (decimal in [0,1]) as a whole-percent hit-rate, e.g. "73%". */
export function formatHitRate(probability: number): string {
  if (!Number.isFinite(probability) || probability < 0 || probability > 1) {
    throw new RangeError(
      `hit-rate probability out of domain [0,1]: ${String(probability)}`,
    );
  }
  // Math.round rounds halves toward +infinity, which for this non-negative
  // domain is exactly "halves round up" — the stated rule.
  const percent = Math.round(probability * 100);
  return `${percent}%`;
}
