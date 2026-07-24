import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRng, createStockPool, INDUSTRIES, generateDailyMetrics } from './sim-engine.mjs';

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

test('generateDailyMetrics returns all fields within their documented ranges', () => {
  const rng = createRng(3);
  const pool = createStockPool(rng, 5);
  for (const stock of pool) {
    const m = generateDailyMetrics(stock, rng);
    assert.equal(m.stockId, stock.id);
    assert.ok(m.changePct >= -3 && m.changePct <= 8, `changePct ${m.changePct}`);
    assert.ok(m.volumeRatio >= 0.5 && m.volumeRatio <= 3.0);
    assert.ok(m.turnoverPct >= 1 && m.turnoverPct <= 15);
    assert.ok(m.marketCapYi > 0);
    assert.equal(typeof m.hadLimitUpIn20d, 'boolean');
    assert.equal(typeof m.aboveAvgLine, 'boolean');
    assert.equal(typeof m.above5And10Day, 'boolean');
    assert.equal(typeof m.volumeStepPattern, 'boolean');
    assert.equal(typeof m.inTopHotSector, 'boolean');
    assert.ok(m.closePrice > 0);
  }
});

test('generateDailyMetrics is deterministic for a fixed rng seed', () => {
  const stock = { id: 'X', name: 'X', industry: '半导体', baseMarketCapYi: 100, volatility: 1 };
  const a = generateDailyMetrics(stock, createRng(9));
  const b = generateDailyMetrics(stock, createRng(9));
  assert.deepEqual(a, b);
});
