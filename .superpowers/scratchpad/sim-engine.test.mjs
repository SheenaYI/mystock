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

import { scoreCandidate, pickTopDiverse, selectDailyPicks, DEFAULT_STRATEGY_PARAMS } from './sim-engine.mjs';

const stock = { id: 'A', name: 'A股', industry: '半导体', baseMarketCapYi: 100, volatility: 1 };

function metrics(overrides) {
  return {
    stockId: 'A', changePct: 4, volumeRatio: 2, turnoverPct: 7, marketCapYi: 100,
    hadLimitUpIn20d: true, aboveAvgLine: true, above5And10Day: true,
    volumeStepPattern: true, inTopHotSector: true, closePrice: 20,
    ...overrides,
  };
}

test('scoreCandidate scores 1.0 when all hard filters and all soft flags pass', () => {
  const { passedHardFilters, score, reasons } = scoreCandidate(stock, metrics({}), DEFAULT_STRATEGY_PARAMS);
  assert.equal(passedHardFilters, true);
  assert.equal(score, 1);
  assert.equal(reasons.length, 9); // 4 hard reasons + 5 soft reasons
});

test('scoreCandidate scores 0.5 when hard filters pass but no soft flags do', () => {
  const m = metrics({ hadLimitUpIn20d: false, aboveAvgLine: false, above5And10Day: false, volumeStepPattern: false, inTopHotSector: false });
  const { passedHardFilters, score } = scoreCandidate(stock, m, DEFAULT_STRATEGY_PARAMS);
  assert.equal(passedHardFilters, true);
  assert.equal(score, 0.5);
});

test('scoreCandidate fails hard filters when changePct is outside the configured range', () => {
  const m = metrics({ changePct: 9 });
  const { passedHardFilters, score } = scoreCandidate(stock, m, DEFAULT_STRATEGY_PARAMS);
  assert.equal(passedHardFilters, false);
  assert.ok(score < 0.5);
});

test('pickTopDiverse drops candidates that fail hard filters and sorts survivors by score desc', () => {
  const pool = [
    { id: 'A', name: 'A', industry: '半导体', baseMarketCapYi: 100, volatility: 1 },
    { id: 'B', name: 'B', industry: '半导体', baseMarketCapYi: 100, volatility: 1 },
    { id: 'C', name: 'C', industry: '医药生物', baseMarketCapYi: 100, volatility: 1 },
  ];
  const metricsByStockId = {
    A: metrics({ stockId: 'A' }), // score 1.0
    B: metrics({ stockId: 'B', hadLimitUpIn20d: false }), // score < 1.0, still passes hard
    C: metrics({ stockId: 'C', changePct: 20 }), // fails hard filter -> excluded
  };
  const picks = pickTopDiverse(pool, metricsByStockId, DEFAULT_STRATEGY_PARAMS, 3);
  assert.deepEqual(picks.map(p => p.id), ['A', 'B']); // C excluded, A before B by score
});

test('pickTopDiverse prefers spreading across industries before repeating one', () => {
  const pool = [
    { id: 'A', name: 'A', industry: '半导体', baseMarketCapYi: 100, volatility: 1 },
    { id: 'B', name: 'B', industry: '半导体', baseMarketCapYi: 100, volatility: 1 },
    { id: 'C', name: 'C', industry: '医药生物', baseMarketCapYi: 100, volatility: 1 },
  ];
  // All three pass hard filters and score identically; A > B > C only by pool order.
  const metricsByStockId = { A: metrics({ stockId: 'A' }), B: metrics({ stockId: 'B' }), C: metrics({ stockId: 'C' }) };
  const picks = pickTopDiverse(pool, metricsByStockId, DEFAULT_STRATEGY_PARAMS, 2);
  const industries = picks.map(p => p.industry);
  assert.equal(new Set(industries).size, 2); // took one from each industry, not both from 半导体
});

test('selectDailyPicks orchestrates metrics generation + scoring deterministically for a fixed seed', () => {
  const rng = createRng(11);
  const pool = createStockPool(createRng(11), 20);
  const picksA = selectDailyPicks(pool, DEFAULT_STRATEGY_PARAMS, createRng(99), 3);
  const picksB = selectDailyPicks(pool, DEFAULT_STRATEGY_PARAMS, createRng(99), 3);
  assert.deepEqual(picksA.map(p => p.id), picksB.map(p => p.id));
  assert.ok(picksA.length <= 3);
});

import { computeBuyPriceRange, computePositions } from './sim-engine.mjs';

test('computeBuyPriceRange brackets the close price by +/-0.5%', () => {
  const r = computeBuyPriceRange(20);
  assert.equal(r.low, 19.9);
  assert.equal(r.high, 20.1);
  assert.equal(r.suggested, 20);
});

test('computePositions splits the position budget evenly across chosen picks, capped by maxSingleStockPct', () => {
  const picks = [
    { id: 'A', name: 'A', industry: '半导体', closePrice: 20, score: 1, reasons: [] },
    { id: 'B', name: 'B', industry: '医药生物', closePrice: 50, score: 0.9, reasons: [] },
    { id: 'C', name: 'C', industry: '军工', closePrice: 10, score: 0.8, reasons: [] },
  ];
  const params = { maxHoldings: 3, maxTotalPositionPct: 60, maxSingleStockPct: 25 };
  const positions = computePositions(picks, 100000, params);
  assert.equal(positions.length, 3);
  // total budget = 60000, split 3 ways = 20000/stock, single cap = 25000/stock -> 20000 wins
  assert.equal(positions[0].stockId, 'A');
  assert.equal(positions[0].shares, 1000); // floor(20000/20/100)*100 = 1000
  assert.equal(positions[0].investedAmount, 20000);
  assert.equal(positions[1].shares, 400); // floor(20000/50/100)*100 = 400
});

test('computePositions respects maxHoldings by only buying the top-scored N picks', () => {
  const picks = [
    { id: 'A', name: 'A', industry: '半导体', closePrice: 20, score: 1, reasons: [] },
    { id: 'B', name: 'B', industry: '医药生物', closePrice: 50, score: 0.9, reasons: [] },
    { id: 'C', name: 'C', industry: '军工', closePrice: 10, score: 0.8, reasons: [] },
  ];
  const params = { maxHoldings: 2, maxTotalPositionPct: 50, maxSingleStockPct: 20 };
  const positions = computePositions(picks, 100000, params);
  assert.deepEqual(positions.map(p => p.stockId), ['A', 'B']);
});

test('computePositions returns an empty array when there are no picks', () => {
  const params = { maxHoldings: 3, maxTotalPositionPct: 50, maxSingleStockPct: 20 };
  assert.deepEqual(computePositions([], 100000, params), []);
});

import { simulateNextDayChangePct, resolveSellOutcome } from './sim-engine.mjs';

test('simulateNextDayChangePct biases its mean upward as score increases, holding rng fixed', () => {
  // rng mocked to a fixed 2-value cycle so the random (Box-Muller) term is identical
  // for both calls — only the score-driven mean bias should differ, by exactly 4pp
  // (score 1 -> +2pp bias, score 0 -> -2pp bias).
  const fixedRng = () => 0.5;
  const highScore = simulateNextDayChangePct(1, fixedRng);
  const lowScore = simulateNextDayChangePct(0, fixedRng);
  assert.ok(Math.abs((highScore - lowScore) - 4) < 1e-9, `delta was ${highScore - lowScore}`);
});

test('simulateNextDayChangePct is deterministic for a fixed rng seed', () => {
  const a = simulateNextDayChangePct(0.7, createRng(5));
  const b = simulateNextDayChangePct(0.7, createRng(5));
  assert.equal(a, b);
});

const params = { takeProfitOpenPctMin: 2, stopLossOpenPct: -1.5 };
const position = { stockId: 'A', name: 'A股', buyPrice: 20, shares: 1000 };

test('resolveSellOutcome classifies a low open as stop_loss', () => {
  const r = resolveSellOutcome(position, -2, params);
  assert.equal(r.ruleTriggered, 'stop_loss');
  assert.equal(r.sellPrice, 19.6);
  assert.equal(r.pnlAmount, -400);
});

test('resolveSellOutcome classifies a strong open as take_profit', () => {
  const r = resolveSellOutcome(position, 3, params);
  assert.equal(r.ruleTriggered, 'take_profit');
  assert.equal(r.sellPrice, 20.6);
  assert.equal(r.pnlAmount, 600);
});

test('resolveSellOutcome classifies a near-flat open as flat_exit', () => {
  const r = resolveSellOutcome(position, 0.2, params);
  assert.equal(r.ruleTriggered, 'flat_exit');
  assert.ok(r.pnlAmount > 0);
});

test('resolveSellOutcome computes pnlPct relative to buyPrice', () => {
  const r = resolveSellOutcome(position, 3, params);
  assert.equal(r.pnlPct, 3);
});
