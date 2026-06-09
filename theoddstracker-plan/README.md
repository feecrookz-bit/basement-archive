# theoddstracker-plan (parked here — not part of basement-archive)

This folder holds **planning + framework-agnostic scaffolding for a separate
project, `theoddstracker.com`**. It was placed in the `basement-archive` repo at
the owner's request because the theoddstracker codebase is not yet accessible from
this session. **None of this is wired into the `basement-archive` backend** — it
is isolated, has no dependencies on it, and is safe to move out wholesale once the
real repo is available.

## Contents
- `PLAN.md` — full execution plan against the task spec (`theoddstrackerproductreadytask_1.md`).
- `src/contract/trace.ts` — `Traced<T>` provenance primitive enforcing the Integrity Lock (§1.1).
- `src/contract/read-contract.ts` — the §2 read-contract types (all nullable). The accessor
  *signature* is here; its body is intentionally **blocked on the real engine** (implementing
  it would mean inventing engine output, which §1.1 forbids).
- `src/formatters/hit-rate.ts` — the §4 pure hit-rate formatter (explicit, tested rounding rule).
- `src/**/*.test.ts` — tests written with `node:test` (port 1:1 to vitest).

## Run the tests
No dependencies required — uses Node's built-in test runner + type-stripping:

```sh
node --experimental-strip-types --test theoddstracker-plan/src/**/*.test.ts
```

Last run: **9 passed, 0 failed.**

## Status
Phase 1 (contract + formatter) drafted and green. Everything past Phase 1 is
blocked on getting the theoddstracker codebase into a session and on the open
questions listed at the end of `PLAN.md` (stack, rationale field, codename
denylist, slip surface, palette source).
