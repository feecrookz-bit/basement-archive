# theoddstracker — Product-Ready Presentation Layer: Execution Plan

> Planning artifact for **theoddstracker.com**, parked in this repo at the owner's
> request. It does **not** belong to `basement-archive` (see `README.md` in this
> folder). The task spec is `theoddstrackerproductreadytask_1.md`.

## Guiding shape
Presentation-layer task over an **existing, untouched engine**. Two
non-negotiables drive everything: the **Integrity Lock** (§1.1 — nothing renders
unless it traces to real engine output) and the **read contract** (§2 — one typed
boundary, no calculation). The plan is therefore *contract-first, then a shared
trace primitive, then features in dependency order, then a quality pass with CI
gates* — mirroring §11, made concrete.

## Phase 0 — Discovery (the moment the code is accessible)
Answered from the repo, not assumptions:
- **Stack**: framework (Next.js / Remix / SvelteKit / other?), styling, test runner, CI provider.
- **Engine boundary**: where the server reads engine output; the real shape of fixture/selection/market.
- **Rationale field (§6)**: does the engine emit a deterministic rationale string? Decides ship-vs-block for Feature 3.
- **Fixture source (§7)**: where real fixtures/groups/opponents come from.
- **Codename inventory (§1.2)**: the real denylist for the CI gate.

## Phase 1 — Read contract + formatters (§2 — GATE, green before anything else)
- One TS type for the full read surface; **every field nullable**; no engine internal type leaks. *(Draft done: `src/contract/`.)*
- Server-side accessor mapping engine output → contract. **Zero calculation.** *(Signature drafted; body blocked on real engine — implementing it now would invent output, violating §1.1.)*
- Pure, separately-tested **formatters**. *(Done: `src/formatters/hit-rate.ts` + tests, all green.)*
- Tests: partial-data → partial contract (no throw); missing market → `null` for that field only; static no-codename check; formatter at 0 / 1 / mid / rounding boundary.
- **🔴 STOP & REPORT** (§11 step 1).

## Phase 2 — Design system + trace marker (§3)
- Tokens as CSS custom properties: 6 colours (`--ink`, `--paper`, `--graphite`, `--signal`, `--up`, `--down`); three type roles (condensed grotesque display / neutral sans body / **mono for all numbers**); spacing + type scale.
- Two surface primitives — **Paper** (authority) and **Ink** (conversion) — enforced so no surface mixes roles.
- **Trace marker** as one shared component (built once; touches every value): mono dot/chip revealing the *real* `TraceRef` from the contract; keyboard-reachable + SR-labelled.
- `--signal` discipline: ≤1 primary element per view.
- Direction must differ from the three banned generic AI looks (justified in PR notes).

## Phase 3 — Feature 1: Hit-rate surfacing (§4, S) — *formatter done*
First feature: proves traceability + the signal/marker pattern end to end.
- Render `formatHitRate(probability)` beside each market; hit-rate is the `--signal` moment.
- 1:1 map to a contract probability; no probability → unavailable state (never 0%/guess); marker present; no codename in label.

## Phase 4 — Feature 4: Fixture-context strip (§7, S)
Before Feature 2 (which embeds it — no duplicate impl).
- Group + upcoming opponents from the **real** fixture source only; unknown group → explicit empty state.

## Phase 5 — Feature 2: Team Cheat Sheet (§5, M)
- One template, identical structure per team; **kit colour the only structural variant** (static `paletteKey` → palette config, never engine-sourced).
- Sections: Team Stats, Player Stats, embedded Feature-4 context, provenance line.
- Snapshot tests ≥3 teams prove structural identity; every cell traces to a contract field; sparse team → explicit gaps; provenance matches real qualifier.

## Phase 6 — Feature 3: One-line rationale (§6, ship-or-block)
- Rationale string **verbatim** from a deterministic engine field; UI never assembles it from numbers (§1.1).
- No field → no element. Absent project-wide → **integration note** naming the exact field the engine should emit; ship 1/2/4 without it.

## Phase 7 — Quality floor + CI gates (§8, §10 — GATE)
- **Four states everywhere**: loading (skeletons matching final layout), populated, empty (designed unavailable state), error (interface voice). Shared empty/error components app-wide.
- **Copy**: active labels; an action keeps its name through the flow.
- **Responsive**: 360px up; touch targets ≥44px; no horizontal scroll; reflow not shrink.
- **A11y**: visible focus everywhere; marker keyboard + SR; colour never sole meaning carrier (up/down also a glyph); WCAG AA on both surfaces.
- **Motion**: one deliberate reveal + micro-states; `prefers-reduced-motion` fully off.
- **Performance**: reserve space (no layout shift); progressive partial-data render.
- **Compliance footer (§1.5)**: `18+ / Gamble Responsibly` + support link on every conversion surface.
- **Two CI gates**: (1) no untraceable rendered value (§1.1) — keyed off `Traced<T>`; (2) no codename in output (§1.2).
- **🔴 STOP & REPORT** (§11 step 7).

## Definition of done (§10)
Contract first & tested · design system + live marker · Features 1/2/4 green · Feature 3 shipped-or-noted · quality floor on every surface · both CI gates enforcing · demo: one fixture — cheat sheet + hit-rates + context strip + slip — every on-screen value's marker pointing at its engine output.

## Open questions / blockers (need answers to go faster)
1. **Stack** (framework + styling + test runner) — unblocks all component/UI phases.
2. **Rationale field** existence — decides Feature 3 ship vs. block.
3. **Codename denylist** — needed for the §1.2 CI gate.
4. **Slip surface** — §10 demo needs a slip/return surface; confirm it exists vs. is in scope.
5. **Team→kit palette source** — confirm research palette config exists or is created as static presentation config.

## What's already built here (framework-agnostic, runs today)
- `src/contract/trace.ts` — `Traced<T>` provenance primitive (makes §1.1 structural) + helpers.
- `src/contract/read-contract.ts` — §2 read surface types (all nullable) + accessor signature (body blocked on engine).
- `src/formatters/hit-rate.ts` — §4 pure formatter with an explicit, tested rounding rule.
- `src/**/*.test.ts` — 9 tests, all passing (`node --experimental-strip-types --test`).
