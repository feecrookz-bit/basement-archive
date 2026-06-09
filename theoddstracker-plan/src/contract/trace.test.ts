// §2 acceptance (boundary helpers): absence is first-class; present values carry
// provenance; the guard narrows correctly. Mirrors the Integrity Lock (§1.1):
// there is no way to produce a renderable value without a trace.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { traced, unavailable, isPresent } from './trace.ts';

test('unavailable() is the explicit absent state (both null)', () => {
  const t = unavailable<number>();
  assert.equal(t.value, null);
  assert.equal(t.trace, null);
  assert.equal(isPresent(t), false);
});

test('traced() pairs a value with its provenance', () => {
  const t = traced(0.73, { source: 'fixture.market.btts.prob', basis: 'last 10 matches' });
  assert.equal(isPresent(t), true);
  if (isPresent(t)) {
    assert.equal(t.value, 0.73);
    assert.equal(t.trace.source, 'fixture.market.btts.prob');
    assert.equal(t.trace.basis, 'last 10 matches');
  }
});

test('a present value always has a trace (no value can render without provenance)', () => {
  const t = traced('Form holding up away from home', { source: 'sel.rationale', basis: null });
  assert.ok(isPresent(t) && t.trace.source.length > 0);
});
