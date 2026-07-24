import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRng, createStockPool, INDUSTRIES } from './sim-engine.mjs';

test('createRng produces a deterministic, repeatable sequence for the same seed', () => {
  const a = createRng(42);
  const b = createRng(42);
  const seqA = [a(), a(), a()];
  const seqB = [b(), b(), b()];
  assert.deepEqual(seqA, seqB);
});

test('createRng values stay within [0, 1)', () => {
  const rng = createRng(7);
  for (let i = 0; i < 200; i++) {
    const v = rng();
    assert.ok(v >= 0 && v < 1, `value ${v} out of range`);
  }
});

test('createStockPool returns the requested count with unique ids', () => {
  const rng = createRng(1);
  const pool = createStockPool(rng, 36);
  assert.equal(pool.length, 36);
  const ids = new Set(pool.map(s => s.id));
  assert.equal(ids.size, 36);
});

test('createStockPool assigns every stock a known industry and plausible market cap', () => {
  const rng = createRng(1);
  const pool = createStockPool(rng, 36);
  for (const s of pool) {
    assert.ok(INDUSTRIES.includes(s.industry), `unexpected industry ${s.industry}`);
    assert.ok(s.baseMarketCapYi >= 30 && s.baseMarketCapYi <= 250);
    assert.ok(s.volatility >= 0.5 && s.volatility <= 1.5);
  }
});
