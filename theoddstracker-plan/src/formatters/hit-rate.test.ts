// §4 acceptance: formatter pure, unit-tested at 0 / 1 / mid / rounding-boundary.
// Written with node:test so it runs under Node's type-stripping with no deps;
// the assertions port 1:1 to vitest (`test`/`expect`) in the real repo.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatHitRate } from './hit-rate.ts';

test('0 -> "0%"', () => {
  assert.equal(formatHitRate(0), '0%');
});

test('1 -> "100%"', () => {
  assert.equal(formatHitRate(1), '100%');
});

test('mid: 0.5 -> "50%"', () => {
  assert.equal(formatHitRate(0.5), '50%');
});

test('rounding boundary: 0.125 (12.5%) rounds up -> "13%"', () => {
  assert.equal(formatHitRate(0.125), '13%');
});

test('rounding boundary: 0.124 (12.4%) rounds down -> "12%"', () => {
  assert.equal(formatHitRate(0.124), '12%');
});

test('out of domain throws (engine-contract violation, never coerced)', () => {
  assert.throws(() => formatHitRate(1.01), RangeError);
  assert.throws(() => formatHitRate(-0.0001), RangeError);
  assert.throws(() => formatHitRate(Number.NaN), RangeError);
});
