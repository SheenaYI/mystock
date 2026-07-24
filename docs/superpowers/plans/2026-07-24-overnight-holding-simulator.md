# "一夜持股法" 模拟观测平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single self-contained HTML Artifact that simulates the "一夜持股法" (overnight-holding) trading strategy — daily stock picking, buying, next-day settlement, and a running equity curve — using entirely fabricated data, so the user can observe whether the strategy's parameters would have been profitable.

**Architecture:** Pure-logic simulation engine (`sim-engine.mjs`) developed and unit-tested standalone with Node's built-in test runner, then inlined into a single self-contained HTML file with vanilla JS DOM rendering, an inline hand-drawn SVG equity chart, and `localStorage` persistence. No frameworks, no external requests, no backend, no real market data, no LLM calls.

**Tech Stack:** Vanilla JavaScript (ES modules for dev/testing, inlined as a plain `<script>` for the final artifact), Node.js built-in `node:test` + `node:assert/strict` for unit tests, hand-rolled SVG for charting, `localStorage` for persistence.

## Global Constraints

- Single deliverable file for the Artifact: self-contained HTML, no external CDN/script/font/image requests (Artifact CSP blocks them).
- No real stock data, no real trading integration, no real LLM calls — everything is fabricated/simulated per the approved design doc.
- Design source of truth: `docs/superpowers/specs/2026-07-24-overnight-holding-simulator-design.md`.
- Default `maxHoldings = 3` (all 3 daily recommendations are bought by default), configurable down to 1–2, per user decision during planning.
- Every randomness-consuming function takes an explicit `rng` parameter (a `() => number in [0,1)` function) — never call `Math.random()` directly inside `sim-engine.mjs`. This is what makes the engine unit-testable deterministically.
- Money amounts are rounded to 2 decimals (`Number(x.toFixed(2))`) at the point they're produced, so state and history entries never accumulate floating point noise.
- Share counts are rounded down to lots of 100 (A-share board-lot convention): `Math.floor(x / 100) * 100`.

---

## File Structure

- Create: `/tmp/claude-1000/-home-ubuntu-workspace-stock-workspace-mystock/74cf5a57-f50a-42b7-860c-0736eff8a752/scratchpad/sim-engine.mjs` — pure simulation logic, zero DOM/localStorage dependencies. Built and unit-tested in Tasks 1–6.
- Create: `/tmp/claude-1000/-home-ubuntu-workspace-stock-workspace-mystock/74cf5a57-f50a-42b7-860c-0736eff8a752/scratchpad/sim-engine.test.mjs` — Node test-runner unit tests for the above.
- Create: `/tmp/claude-1000/-home-ubuntu-workspace-stock-workspace-mystock/74cf5a57-f50a-42b7-860c-0736eff8a752/scratchpad/overnight-holding-simulator.html` — the final self-contained artifact. Built incrementally in Tasks 7–10 by inlining `sim-engine.mjs`'s contents into a `<script>` tag and adding DOM rendering/controller code around it. This is the file passed to the `Artifact` tool in Task 11.

Both scratchpad paths above use the literal directory printed in this session — an implementer picking up this plan in a different session must substitute their own scratchpad directory (visible in their system prompt) for that prefix.

---

### Task 1: RNG utility + fabricated stock pool

**Files:**
- Create: `.../scratchpad/sim-engine.mjs`
- Create: `.../scratchpad/sim-engine.test.mjs`

**Interfaces:**
- Produces: `INDUSTRIES: string[]`, `createRng(seed: number): () => number`, `createStockPool(rng: () => number, count?: number): Array<{id, name, industry, baseMarketCapYi, volatility}>`

- [ ] **Step 1: Write the failing tests**

```js
// sim-engine.test.mjs
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: FAIL — `sim-engine.mjs` does not exist / exports missing.

- [ ] **Step 3: Implement `sim-engine.mjs`**

```js
// sim-engine.mjs
// Pure simulation logic for the "一夜持股法" observation prototype.
// No DOM, no localStorage — every function here must stay unit-testable
// with plain Node. Any randomness must come in via an explicit `rng` param.

export const INDUSTRIES = ['半导体', '新能源', '医药生物', '消费电子', '军工', '食品饮料', '有色金属', '汽车零部件'];

const NAME_PREFIXES = ['锐晶', '恒远', '天启', '云图', '星辰', '沃德', '鼎盛', '华锦', '翔宇', '博源', '联创', '嘉合', '瑞德', '迅捷', '长风'];
const NAME_SUFFIXES = ['科技', '实业', '材料', '制药', '电子', '动力', '精工', '控股', '股份', '集团'];

// mulberry32 PRNG — small, fast, deterministic for a given seed.
export function createRng(seed) {
  let state = seed >>> 0;
  return function rng() {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function createStockPool(rng, count = 36) {
  const pool = [];
  for (let i = 0; i < count; i++) {
    const industry = INDUSTRIES[i % INDUSTRIES.length];
    const prefix = NAME_PREFIXES[Math.floor(rng() * NAME_PREFIXES.length)];
    const suffix = NAME_SUFFIXES[Math.floor(rng() * NAME_SUFFIXES.length)];
    pool.push({
      id: `SIM${String(i + 1).padStart(3, '0')}`,
      name: `${prefix}${suffix}`,
      industry,
      baseMarketCapYi: 30 + rng() * 220, // 30~250亿
      volatility: 0.5 + rng() * 1.0,     // 0.5~1.5
    });
  }
  return pool;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

This project has no git repo initialized (confirmed during planning). Skip the commit step for every task in this plan — just move to the next task. (If the user later initializes git in this directory, resume committing after each task.)

---

### Task 2: Daily metrics generation

**Files:**
- Modify: `.../scratchpad/sim-engine.mjs`
- Modify: `.../scratchpad/sim-engine.test.mjs`

**Interfaces:**
- Consumes: `Stock` shape from Task 1 (`{id, name, industry, baseMarketCapYi, volatility}`)
- Produces: `generateDailyMetrics(stock, rng): {stockId, changePct, volumeRatio, turnoverPct, marketCapYi, hadLimitUpIn20d, aboveAvgLine, above5And10Day, volumeStepPattern, inTopHotSector, closePrice}`

- [ ] **Step 1: Write the failing tests**

Append to `sim-engine.test.mjs`:

```js
import { generateDailyMetrics } from './sim-engine.mjs';

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: FAIL — `generateDailyMetrics is not a function` / not exported.

- [ ] **Step 3: Implement `generateDailyMetrics`**

Append to `sim-engine.mjs`:

```js
export function generateDailyMetrics(stock, rng) {
  const changePct = -3 + rng() * 11; // -3% ~ +8%; most rolls won't clear the 3-5% filter, mirrors real distribution
  const volumeRatio = 0.5 + rng() * 2.5;
  const turnoverPct = 1 + rng() * 14;
  const marketCapYi = stock.baseMarketCapYi * (0.9 + rng() * 0.2);
  const hadLimitUpIn20d = rng() < 0.35;
  const aboveAvgLine = rng() < 0.55;
  const above5And10Day = rng() < 0.5;
  const volumeStepPattern = rng() < 0.4;
  const inTopHotSector = rng() < 3 / INDUSTRIES.length; // roughly "top 3 sectors of the day" odds
  const basePrice = 8 + rng() * 60; // 8~68元
  const closePrice = Number((basePrice * (1 + changePct / 100)).toFixed(2));
  return {
    stockId: stock.id, changePct, volumeRatio, turnoverPct, marketCapYi,
    hadLimitUpIn20d, aboveAvgLine, above5And10Day, volumeStepPattern, inTopHotSector,
    closePrice,
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: PASS (6/6)

- [ ] **Step 5: Commit** — skipped (no git repo, see Task 1 Step 5).

---

### Task 3: Strategy params, scoring, and diverse top-N picking

**Files:**
- Modify: `.../scratchpad/sim-engine.mjs`
- Modify: `.../scratchpad/sim-engine.test.mjs`

**Interfaces:**
- Consumes: `Stock` (Task 1), `DailyMetrics` (Task 2)
- Produces: `DEFAULT_STRATEGY_PARAMS` (object, see Global Constraints for `maxHoldings: 3` default), `scoreCandidate(stock, metrics, params): {passedHardFilters: boolean, score: number, reasons: string[]}`, `pickTopDiverse(pool, metricsByStockId, params, count?): Array<Stock & DailyMetrics & {passedHardFilters, score, reasons}>`, `selectDailyPicks(pool, params, rng, count?): same shape as pickTopDiverse`

- [ ] **Step 1: Write the failing tests**

Append to `sim-engine.test.mjs`:

```js
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: FAIL — new exports missing.

- [ ] **Step 3: Implement scoring, params, and selection**

Append to `sim-engine.mjs`:

```js
export const DEFAULT_STRATEGY_PARAMS = Object.freeze({
  changePctMin: 3, changePctMax: 5,
  volumeRatioMin: 1.4,
  marketCapMinYi: 50, marketCapMaxYi: 200,
  turnoverMinPct: 5, turnoverMaxPct: 10,
  maxSingleStockPct: 20,
  maxTotalPositionPct: 50,
  maxHoldings: 3,
  takeProfitOpenPctMin: 2,
  stopLossOpenPct: -1.5,
});

export function scoreCandidate(stock, metrics, params) {
  const reasons = [];
  const hardChecks = [
    { pass: metrics.changePct >= params.changePctMin && metrics.changePct <= params.changePctMax,
      reason: `涨幅${metrics.changePct.toFixed(1)}%（要求${params.changePctMin}%~${params.changePctMax}%）` },
    { pass: metrics.volumeRatio >= params.volumeRatioMin,
      reason: `量比${metrics.volumeRatio.toFixed(2)}（要求>${params.volumeRatioMin}）` },
    { pass: metrics.marketCapYi >= params.marketCapMinYi && metrics.marketCapYi <= params.marketCapMaxYi,
      reason: `流通市值${metrics.marketCapYi.toFixed(0)}亿（要求${params.marketCapMinYi}~${params.marketCapMaxYi}亿）` },
    { pass: metrics.turnoverPct >= params.turnoverMinPct && metrics.turnoverPct <= params.turnoverMaxPct,
      reason: `换手率${metrics.turnoverPct.toFixed(1)}%（要求${params.turnoverMinPct}%~${params.turnoverMaxPct}%）` },
  ];
  const passedHardFilters = hardChecks.every(c => c.pass);
  hardChecks.forEach(c => { if (c.pass) reasons.push(c.reason); });

  const softFlags = [
    [metrics.hadLimitUpIn20d, '20日内有过涨停'],
    [metrics.aboveAvgLine, '全天站稳均价线上方'],
    [metrics.above5And10Day, '站稳5日/10日线'],
    [metrics.volumeStepPattern, '成交量台阶式放量'],
    [metrics.inTopHotSector, `属于今日热点板块「${stock.industry}」前三`],
  ];
  let softScore = 0;
  softFlags.forEach(([flag, reason]) => { if (flag) { softScore += 1; reasons.push(reason); } });

  const score = passedHardFilters
    ? 0.5 + (softScore / softFlags.length) * 0.5
    : (softScore / softFlags.length) * 0.3;

  return { passedHardFilters, score: Number(score.toFixed(3)), reasons };
}

export function pickTopDiverse(pool, metricsByStockId, params, count = 3) {
  const scored = pool
    .map(stock => {
      const metrics = metricsByStockId[stock.id];
      const { passedHardFilters, score, reasons } = scoreCandidate(stock, metrics, params);
      return { ...stock, ...metrics, passedHardFilters, score, reasons };
    })
    .filter(c => c.passedHardFilters)
    .sort((a, b) => b.score - a.score);

  const picks = [];
  const usedIndustries = new Set();
  for (const c of scored) {
    if (picks.length >= count) break;
    if (usedIndustries.has(c.industry)) continue;
    picks.push(c);
    usedIndustries.add(c.industry);
  }
  if (picks.length < count) {
    for (const c of scored) {
      if (picks.length >= count) break;
      if (picks.includes(c)) continue;
      picks.push(c);
    }
  }
  return picks;
}

export function selectDailyPicks(pool, params, rng, count = 3) {
  const metricsByStockId = {};
  for (const stock of pool) {
    metricsByStockId[stock.id] = generateDailyMetrics(stock, rng);
  }
  return pickTopDiverse(pool, metricsByStockId, params, count);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: PASS (11/11)

- [ ] **Step 5: Commit** — skipped (no git repo).

---

### Task 4: Buy price range and position sizing

**Files:**
- Modify: `.../scratchpad/sim-engine.mjs`
- Modify: `.../scratchpad/sim-engine.test.mjs`

**Interfaces:**
- Consumes: pick objects from `pickTopDiverse`/`selectDailyPicks` (Task 3), which include `closePrice`, `id`, `name`, `industry`, `score`, `reasons`
- Produces: `computeBuyPriceRange(closePrice): {low, high, suggested}`, `computePositions(picks, capital, params): Array<{stockId, name, industry, buyPrice, shares, investedAmount, score, reasons}>`

- [ ] **Step 1: Write the failing tests**

Append to `sim-engine.test.mjs`:

```js
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: FAIL — new exports missing.

- [ ] **Step 3: Implement**

Append to `sim-engine.mjs`:

```js
export function computeBuyPriceRange(closePrice) {
  return {
    low: Number((closePrice * 0.995).toFixed(2)),
    high: Number((closePrice * 1.005).toFixed(2)),
    suggested: closePrice,
  };
}

export function computePositions(picks, capital, params) {
  const n = Math.min(params.maxHoldings, picks.length);
  const chosen = picks.slice(0, n);
  if (chosen.length === 0) return [];

  const totalBudget = capital * (params.maxTotalPositionPct / 100);
  const perStockCap = capital * (params.maxSingleStockPct / 100);
  const perStockBudget = Math.min(totalBudget / chosen.length, perStockCap);

  return chosen.map(c => {
    const buyPrice = c.closePrice;
    const shares = Math.floor(perStockBudget / buyPrice / 100) * 100;
    const investedAmount = Number((shares * buyPrice).toFixed(2));
    return {
      stockId: c.id, name: c.name, industry: c.industry,
      buyPrice, shares, investedAmount, score: c.score, reasons: c.reasons,
    };
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: PASS (15/15)

- [ ] **Step 5: Commit** — skipped (no git repo).

---

### Task 5: Next-day simulation and sell-rule resolution

**Files:**
- Modify: `.../scratchpad/sim-engine.mjs`
- Modify: `.../scratchpad/sim-engine.test.mjs`

**Interfaces:**
- Consumes: `Position` shape from Task 4 (`{stockId, name, buyPrice, shares, score, ...}`), `DEFAULT_STRATEGY_PARAMS`-shaped params with `takeProfitOpenPctMin`, `stopLossOpenPct`
- Produces: `simulateNextDayChangePct(score, rng): number`, `resolveSellOutcome(position, nextDayChangePct, params): {stockId, name, buyPrice, sellPrice, pnlAmount, pnlPct, ruleTriggered}` where `ruleTriggered` is one of `'stop_loss' | 'take_profit' | 'flat_exit'`

- [ ] **Step 1: Write the failing tests**

Append to `sim-engine.test.mjs`:

```js
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: FAIL — new exports missing.

- [ ] **Step 3: Implement**

Append to `sim-engine.mjs`:

```js
export function simulateNextDayChangePct(score, rng) {
  // Box-Muller transform for an approximately normal draw, mean shifted by
  // matchScore so that better-matching picks (per the configured strategy
  // params) are more likely to gap up the next morning. This is what makes
  // tuning the strategy parameters visibly change the win rate/equity curve
  // instead of producing pure noise.
  const u1 = Math.min(Math.max(rng(), 1e-9), 1 - 1e-9);
  const u2 = rng();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  const baseStdPct = 2.2;
  const meanBiasPct = (score - 0.5) * 4; // score 0..1 -> bias -2pp..+2pp
  return z * baseStdPct + meanBiasPct;
}

function classifyOutcome(changePct, params) {
  if (changePct <= params.stopLossOpenPct) return 'stop_loss';
  if (changePct >= params.takeProfitOpenPctMin) return 'take_profit';
  return 'flat_exit';
}

export function resolveSellOutcome(position, nextDayChangePct, params) {
  const sellPrice = Number((position.buyPrice * (1 + nextDayChangePct / 100)).toFixed(2));
  const ruleTriggered = classifyOutcome(nextDayChangePct, params);
  const pnlAmount = Number(((sellPrice - position.buyPrice) * position.shares).toFixed(2));
  const pnlPct = Number((((sellPrice - position.buyPrice) / position.buyPrice) * 100).toFixed(2));
  return { stockId: position.stockId, name: position.name, buyPrice: position.buyPrice, sellPrice, pnlAmount, pnlPct, ruleTriggered };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: PASS (22/22)

- [ ] **Step 5: Commit** — skipped (no git repo).

---

### Task 6: State machine (selection ↔ holding ↔ settlement)

**Files:**
- Modify: `.../scratchpad/sim-engine.mjs`
- Modify: `.../scratchpad/sim-engine.test.mjs`

**Interfaces:**
- Consumes: everything from Tasks 1–5 (`createStockPool`, `selectDailyPicks`, `computePositions`, `simulateNextDayChangePct`, `resolveSellOutcome`, `DEFAULT_STRATEGY_PARAMS`)
- Produces: `createInitialState(initialCapital, strategyParams?): State`, `resetSimulation(initialCapital, strategyParams, rng): State`, `runSelectionPhase(state, rng): State`, `runSettlementPhase(state, rng): State`, `updateStrategyParams(state, newParams): State`. `State` shape: `{day, phase: 'selection'|'holding', initialCapital, capital, positions, lastPicks, lastSettlement, history, strategyParams, stockPool}`. This `State` shape is what Tasks 7–10 render and persist — treat these field names as final.

- [ ] **Step 1: Write the failing tests**

Append to `sim-engine.test.mjs`:

```js
import { createInitialState, resetSimulation, runSelectionPhase, runSettlementPhase, updateStrategyParams } from './sim-engine.mjs';

test('createInitialState starts at day 1 in the selection phase with the given capital', () => {
  const s = createInitialState(100000);
  assert.equal(s.day, 1);
  assert.equal(s.phase, 'selection');
  assert.equal(s.capital, 100000);
  assert.equal(s.initialCapital, 100000);
  assert.deepEqual(s.positions, []);
  assert.deepEqual(s.history, []);
  assert.equal(s.strategyParams.maxHoldings, 3); // DEFAULT_STRATEGY_PARAMS default
});

test('resetSimulation attaches a freshly generated stock pool', () => {
  const s = resetSimulation(50000, undefined, createRng(1));
  assert.ok(Array.isArray(s.stockPool));
  assert.ok(s.stockPool.length > 0);
});

test('runSelectionPhase moves to holding, sets positions, and debits capital by the invested amount', () => {
  let s = resetSimulation(100000, undefined, createRng(1));
  s = runSelectionPhase(s, createRng(2));
  assert.equal(s.phase, 'holding');
  assert.ok(s.positions.length > 0);
  assert.ok(s.lastPicks.length > 0);
  const investedTotal = s.positions.reduce((sum, p) => sum + p.investedAmount, 0);
  assert.equal(s.capital, Number((100000 - investedTotal).toFixed(2)));
});

test('runSelectionPhase throws if called outside the selection phase', () => {
  let s = resetSimulation(100000, undefined, createRng(1));
  s = runSelectionPhase(s, createRng(2));
  assert.throws(() => runSelectionPhase(s, createRng(3)));
});

test('runSettlementPhase moves back to selection, advances the day, clears positions, and appends history', () => {
  let s = resetSimulation(100000, undefined, createRng(1));
  s = runSelectionPhase(s, createRng(2));
  const positionsBefore = s.positions;
  s = runSettlementPhase(s, createRng(4));
  assert.equal(s.phase, 'selection');
  assert.equal(s.day, 2);
  assert.deepEqual(s.positions, []);
  assert.equal(s.history.length, 1);
  assert.equal(s.history[0].day, 1);
  assert.equal(s.history[0].results.length, positionsBefore.length);
  assert.ok('winCount' in s.history[0]);
  assert.ok(typeof s.lastSettlement !== 'undefined');
});

test('runSettlementPhase throws if called outside the holding phase', () => {
  const s = resetSimulation(100000, undefined, createRng(1));
  assert.throws(() => runSettlementPhase(s, createRng(2)));
});

test('a full selection -> settlement cycle conserves capital plus/minus pnl (no money created or destroyed)', () => {
  let s = resetSimulation(100000, undefined, createRng(1));
  s = runSelectionPhase(s, createRng(2));
  s = runSettlementPhase(s, createRng(4));
  const expectedCapital = Number((100000 + s.history[0].totalPnlAmount).toFixed(2));
  assert.equal(s.capital, expectedCapital);
});

test('updateStrategyParams merges partial overrides into the existing params without dropping the rest', () => {
  const s = createInitialState(100000);
  const updated = updateStrategyParams(s, { maxHoldings: 1 });
  assert.equal(updated.strategyParams.maxHoldings, 1);
  assert.equal(updated.strategyParams.changePctMin, 3); // untouched default preserved
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: FAIL — new exports missing.

- [ ] **Step 3: Implement**

Append to `sim-engine.mjs`:

```js
export function createInitialState(initialCapital, strategyParams = DEFAULT_STRATEGY_PARAMS) {
  return {
    day: 1,
    phase: 'selection',
    initialCapital,
    capital: initialCapital,
    positions: [],
    lastPicks: [],
    lastSettlement: null,
    history: [],
    strategyParams: { ...strategyParams },
    stockPool: null,
  };
}

export function resetSimulation(initialCapital, strategyParams, rng) {
  const state = createInitialState(initialCapital, strategyParams);
  return { ...state, stockPool: createStockPool(rng) };
}

export function runSelectionPhase(state, rng) {
  if (state.phase !== 'selection') {
    throw new Error(`runSelectionPhase called in phase "${state.phase}", expected "selection"`);
  }
  const picks = selectDailyPicks(state.stockPool, state.strategyParams, rng, 3);
  const positions = computePositions(picks, state.capital, state.strategyParams);
  const investedTotal = positions.reduce((sum, p) => sum + p.investedAmount, 0);
  return {
    ...state,
    phase: 'holding',
    lastPicks: picks,
    positions,
    capital: Number((state.capital - investedTotal).toFixed(2)),
  };
}

export function runSettlementPhase(state, rng) {
  if (state.phase !== 'holding') {
    throw new Error(`runSettlementPhase called in phase "${state.phase}", expected "holding"`);
  }
  const settlement = state.positions.map(position => {
    const changePct = simulateNextDayChangePct(position.score, rng);
    return resolveSellOutcome(position, changePct, state.strategyParams);
  });
  const proceedsTotal = settlement.reduce((sum, s) => {
    const position = state.positions.find(p => p.stockId === s.stockId);
    return sum + s.sellPrice * position.shares;
  }, 0);
  const totalPnlAmount = Number(settlement.reduce((sum, s) => sum + s.pnlAmount, 0).toFixed(2));
  const winCount = settlement.filter(s => s.pnlAmount > 0).length;
  const newCapital = Number((state.capital + proceedsTotal).toFixed(2));
  const historyEntry = {
    day: state.day,
    picks: state.lastPicks,
    results: settlement,
    totalPnlAmount,
    totalPnlPct: Number(((totalPnlAmount / state.initialCapital) * 100).toFixed(2)),
    winCount,
    capitalAfter: newCapital,
  };
  return {
    ...state,
    phase: 'selection',
    day: state.day + 1,
    capital: newCapital,
    positions: [],
    lastSettlement: settlement,
    history: [...state.history, historyEntry],
  };
}

export function updateStrategyParams(state, newParams) {
  return { ...state, strategyParams: { ...state.strategyParams, ...newParams } };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test .../scratchpad/sim-engine.test.mjs`
Expected: PASS (29/29)

- [ ] **Step 5: Commit** — skipped (no git repo).

**This completes the pure-logic engine.** Tasks 7–10 build the UI around it. From here on, "tests" become manual browser verification (via the `webapp-testing` skill/Playwright) instead of `node --test`, since we're now rendering DOM.

---

### Task 7: HTML shell + inline engine + status bar + selection-phase UI

**Files:**
- Create: `.../scratchpad/overnight-holding-simulator.html`

**Interfaces:**
- Consumes: the full `sim-engine.mjs` API from Tasks 1–6 (inlined verbatim into a `<script>` tag, with the `export` keywords stripped since this is a plain script, not a module)
- Produces: a global `AppState` variable, a `render()` function that redraws `#status-bar` and `#main-panel` from `AppState`, and a `startSelectionPhase()` handler wired to a button

- [ ] **Step 1: Create the HTML shell with inlined engine**

Copy the entire contents of `sim-engine.mjs` from Tasks 1–6, remove every `export` keyword (plain `<script>`, not a module — keeps this a zero-build single file), and paste it inside a `<script>` tag as shown below. Do not otherwise modify the copied logic — it is already unit-tested.

```html
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>一夜持股法 模拟观测平台</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f7f8fa; --panel: #ffffff; --text: #1a1d24; --muted: #6b7280;
    --border: #e5e7eb; --accent: #2563eb; --up: #dc2626; --down: #16a34a;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #0f1115; --panel: #171a21; --text: #e5e7eb; --muted: #9ca3af; --border: #2a2f3a; --accent: #60a5fa; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--bg); color: var(--text); }
  .wrap { max-width: 960px; margin: 0 auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
  .status-bar { display: flex; flex-wrap: wrap; gap: 24px; }
  .status-item .label { font-size: 12px; color: var(--muted); }
  .status-item .value { font-size: 20px; font-weight: 600; }
  .pnl-up { color: var(--up); } .pnl-down { color: var(--down); }
  button { font: inherit; padding: 10px 16px; border-radius: 8px; border: 1px solid var(--border); background: var(--accent); color: white; cursor: pointer; }
  button.secondary { background: transparent; color: var(--text); }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
  .card { border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
  .card h3 { margin: 0 0 4px; }
  .card .meta { font-size: 13px; color: var(--muted); }
  .reasons { font-size: 12px; color: var(--muted); margin-top: 8px; }
</style>
</head>
<body>
<div class="wrap">
  <div id="status-bar" class="panel status-bar"></div>
  <div id="main-panel" class="panel"></div>
  <div id="chart-panel" class="panel"></div>
  <div id="history-panel" class="panel"></div>
  <div id="settings-panel" class="panel"></div>
</div>

<script>
// ---- BEGIN inlined sim-engine.mjs (exports stripped) ----
const INDUSTRIES = ['半导体', '新能源', '医药生物', '消费电子', '军工', '食品饮料', '有色金属', '汽车零部件'];
// ... (paste the full bodies of createRng, createStockPool, generateDailyMetrics,
//      DEFAULT_STRATEGY_PARAMS, scoreCandidate, pickTopDiverse, selectDailyPicks,
//      computeBuyPriceRange, computePositions, simulateNextDayChangePct,
//      resolveSellOutcome, createInitialState, resetSimulation, runSelectionPhase,
//      runSettlementPhase, updateStrategyParams here verbatim from Tasks 1-6,
//      each as a plain `function name(...) { ... }` instead of `export function`)
// ---- END inlined sim-engine.mjs ----

let liveRng = createRng(Date.now() % 2147483647);
let AppState = resetSimulation(100000, DEFAULT_STRATEGY_PARAMS, liveRng);

function fmtMoney(n) { return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmtPct(n) { return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`; }

function renderStatusBar() {
  const totalPnl = Number((AppState.capital - AppState.initialCapital).toFixed(2));
  const totalPnlPct = Number(((totalPnl / AppState.initialCapital) * 100).toFixed(2));
  const pnlClass = totalPnl >= 0 ? 'pnl-up' : 'pnl-down';
  const phaseLabel = { selection: '待选股（14:30）', holding: '持仓中，待次日检查' }[AppState.phase];
  document.getElementById('status-bar').innerHTML = `
    <div class="status-item"><div class="label">当前资金</div><div class="value">¥${fmtMoney(AppState.capital)}</div></div>
    <div class="status-item"><div class="label">累计盈亏</div><div class="value ${pnlClass}">¥${fmtMoney(totalPnl)} (${fmtPct(totalPnlPct)})</div></div>
    <div class="status-item"><div class="label">模拟天数</div><div class="value">第 ${AppState.day} 天</div></div>
    <div class="status-item"><div class="label">当前阶段</div><div class="value">${phaseLabel}</div></div>
  `;
}

function renderSelectionPhase(container) {
  container.innerHTML = `
    <h2>14:30 选股</h2>
    <p>点击下方按钮，按当前策略参数从股票池中筛选今日推荐。</p>
    <button id="btn-select">开始选股 / 买入</button>
  `;
  document.getElementById('btn-select').onclick = () => {
    AppState = runSelectionPhase(AppState, liveRng);
    render();
  };
}

function render() {
  renderStatusBar();
  const main = document.getElementById('main-panel');
  if (AppState.phase === 'selection') renderSelectionPhase(main);
  // holding-phase and settlement-result rendering added in Task 8
}

render();
</script>
</body>
</html>
```

- [ ] **Step 2: Manual verification — status bar and selection phase render**

Use the `webapp-testing` skill's Playwright helper to open the file directly (`file://` URL, no server needed) and check:
1. Status bar shows `¥100,000.00`, `第 1 天`, `待选股（14:30）`.
2. Clicking "开始选股 / 买入" does not throw a JS console error (check via Playwright's console listener) — the subsequent phase renders in Task 8, so it's fine if the panel goes blank after clicking at this point; the check here is purely "no uncaught exception."

Expected: status bar values match, no console errors.

- [ ] **Step 3: Commit** — skipped (no git repo).

---

### Task 8: Holding-phase UI + settlement-phase UI

**Files:**
- Modify: `.../scratchpad/overnight-holding-simulator.html`

**Interfaces:**
- Consumes: `AppState.positions`, `AppState.lastPicks`, `AppState.lastSettlement` (all produced by the Task 6 state machine)
- Produces: `renderHoldingPhase(container)`, `renderSettlementSummary(container)`, wired into `render()`'s phase switch

- [ ] **Step 1: Add the recommendation cards to `renderSelectionPhase`'s output**

Replace the `renderSelectionPhase` body from Task 7 with a version that also shows `AppState.lastPicks` (from the *previous* round, if any) so the user can see why yesterday's picks were chosen even while looking at today's "开始选股" button — but since a fresh selection immediately overwrites `lastPicks`, the actual recommendation cards belong to the **holding** phase (right after buying). Implement as follows:

```js
function renderSelectionPhase(container) {
  container.innerHTML = `
    <h2>14:30 选股</h2>
    <p>点击下方按钮，按当前策略参数从股票池中筛选今日推荐并买入。</p>
    <button id="btn-select">开始选股 / 买入</button>
  `;
  document.getElementById('btn-select').onclick = () => {
    AppState = runSelectionPhase(AppState, liveRng);
    render();
  };
}

function renderPickCard(pick, extra) {
  const range = computeBuyPriceRange(pick.closePrice);
  return `
    <div class="card">
      <h3>${pick.name} <span class="meta">${pick.industry}</span></h3>
      <div class="meta">建议买入价区间：¥${range.low} ~ ¥${range.high}</div>
      <div class="meta">匹配度得分：${(pick.score * 100).toFixed(0)}</div>
      ${extra || ''}
      <div class="reasons">${pick.reasons.join('，')}</div>
    </div>
  `;
}

function renderHoldingPhase(container) {
  const cards = AppState.positions.map(p => {
    const pick = AppState.lastPicks.find(x => x.id === p.stockId);
    const extra = `<div class="meta">买入价 ¥${p.buyPrice} × ${p.shares}股 = ¥${fmtMoney(p.investedAmount)}</div>`;
    return renderPickCard({ ...pick, closePrice: p.buyPrice }, extra);
  }).join('');
  container.innerHTML = `
    <h2>持仓中</h2>
    <div class="cards">${cards}</div>
    <p style="margin-top:12px">次日开盘后，按"一夜持股法"纪律检查并卖出。</p>
    <button id="btn-settle">推进到次日检查 / 卖出</button>
  `;
  document.getElementById('btn-settle').onclick = () => {
    AppState = runSettlementPhase(AppState, liveRng);
    render();
  };
}

const RULE_LABELS = { take_profit: '止盈', stop_loss: '止损', flat_exit: '平仓离场' };

function renderSettlementSummary(container) {
  const rows = AppState.lastSettlement.map(r => `
    <div class="card">
      <h3>${r.name} <span class="meta">${RULE_LABELS[r.ruleTriggered]}</span></h3>
      <div class="meta">买入 ¥${r.buyPrice} → 卖出 ¥${r.sellPrice}</div>
      <div class="${r.pnlAmount >= 0 ? 'pnl-up' : 'pnl-down'}">${fmtPct(r.pnlPct)}（¥${fmtMoney(r.pnlAmount)}）</div>
    </div>
  `).join('');
  container.innerHTML = `
    <h2>第 ${AppState.day - 1} 天 结算结果</h2>
    <div class="cards">${rows}</div>
    <button id="btn-continue" class="secondary" style="margin-top:12px">继续 → 今日选股</button>
  `;
  document.getElementById('btn-continue').onclick = () => {
    AppState = { ...AppState, lastSettlement: null };
    render();
  };
}

function render() {
  renderStatusBar();
  const main = document.getElementById('main-panel');
  if (AppState.phase === 'holding') {
    renderHoldingPhase(main);
  } else if (AppState.lastSettlement) {
    renderSettlementSummary(main);
  } else {
    renderSelectionPhase(main);
  }
}
```

Note the `lastSettlement` gate: after `runSettlementPhase` runs, `AppState.phase` is already back to `'selection'`, but we want to show the settlement summary *first* and only return to the selection button once the user clicks "继续". That's why `render()` checks `AppState.lastSettlement` before falling through to the selection phase, and the "继续" button clears it.

- [ ] **Step 2: Manual verification — full day cycle**

Via Playwright (webapp-testing skill), open the file and:
1. Click "开始选股 / 买入" → assert 1–3 cards appear (0 is possible if no stock passes the hard filters that round; if that happens on the seed you land on, verify the panel says "持仓中" with an empty `.cards` div rather than crashing) and status bar phase label switches to holding-related text.
2. Click "推进到次日检查 / 卖出" → assert the settlement summary appears with a "止盈/止损/平仓离场" label per row and non-empty pnl values.
3. Click "继续 → 今日选股" → assert we're back at the "开始选股 / 买入" button and status bar day counter incremented by 1.
4. Repeat the full cycle 3 times in the same page load, confirming no console errors and the day counter reaches 4.

Expected: all assertions pass, zero uncaught JS exceptions in the Playwright console log.

- [ ] **Step 3: Commit** — skipped (no git repo).

---

### Task 9: Settings panel + localStorage persistence + reset

**Files:**
- Modify: `.../scratchpad/overnight-holding-simulator.html`

**Interfaces:**
- Consumes: `AppState.strategyParams` (Task 6 shape), `updateStrategyParams`, `resetSimulation`
- Produces: `renderSettingsPanel(container)`, `saveState()`, `loadState()`, wired so every `AppState` reassignment persists automatically

- [ ] **Step 1: Add persistence helpers and call them from every state transition**

```js
const STORAGE_KEY = 'overnight-holding-sim-state-v1';

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(AppState));
}

function loadState() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

const persisted = loadState();
let liveRng = createRng(Date.now() % 2147483647);
let AppState = persisted || resetSimulation(100000, DEFAULT_STRATEGY_PARAMS, liveRng);
```

Then update every place that reassigns `AppState` (the `btn-select`, `btn-settle`, and `btn-continue` handlers from Task 8) to call `saveState()` right after the reassignment, e.g.:

```js
document.getElementById('btn-select').onclick = () => {
  AppState = runSelectionPhase(AppState, liveRng);
  saveState();
  render();
};
```

Apply the same `saveState()` addition to the `btn-settle` and `btn-continue` handlers.

- [ ] **Step 2: Add the settings panel**

```js
const PARAM_FIELDS = [
  { key: 'changePctMin', label: '涨幅下限 %', step: 0.1 },
  { key: 'changePctMax', label: '涨幅上限 %', step: 0.1 },
  { key: 'volumeRatioMin', label: '量比下限', step: 0.1 },
  { key: 'marketCapMinYi', label: '市值下限（亿）', step: 1 },
  { key: 'marketCapMaxYi', label: '市值上限（亿）', step: 1 },
  { key: 'turnoverMinPct', label: '换手率下限 %', step: 0.1 },
  { key: 'turnoverMaxPct', label: '换手率上限 %', step: 0.1 },
  { key: 'maxSingleStockPct', label: '单票仓位上限 %', step: 1 },
  { key: 'maxTotalPositionPct', label: '总仓位上限 %', step: 1 },
  { key: 'maxHoldings', label: '最大持股数', step: 1 },
  { key: 'takeProfitOpenPctMin', label: '止盈触发涨幅 %', step: 0.1 },
  { key: 'stopLossOpenPct', label: '止损触发跌幅 %', step: 0.1 },
];

function renderSettingsPanel(container) {
  const fields = PARAM_FIELDS.map(f => `
    <label style="display:flex; flex-direction:column; gap:4px; font-size:13px;">
      ${f.label}
      <input type="number" step="${f.step}" data-key="${f.key}" value="${AppState.strategyParams[f.key]}" />
    </label>
  `).join('');
  container.innerHTML = `
    <h2>策略设置</h2>
    <label style="display:flex; flex-direction:column; gap:4px; font-size:13px; max-width:200px;">
      初始资金
      <input type="number" id="initial-capital" step="1000" value="${AppState.initialCapital}" />
    </label>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(160px,1fr)); gap:12px; margin:12px 0;">
      ${fields}
    </div>
    <button id="btn-save-settings">保存设置</button>
    <button id="btn-reset" class="secondary">重置模拟</button>
  `;
  document.getElementById('btn-save-settings').onclick = () => {
    const updates = {};
    container.querySelectorAll('input[data-key]').forEach(input => {
      updates[input.dataset.key] = Number(input.value);
    });
    AppState = updateStrategyParams(AppState, updates);
    saveState();
    render();
  };
  document.getElementById('btn-reset').onclick = () => {
    const capital = Number(document.getElementById('initial-capital').value) || 100000;
    liveRng = createRng(Date.now() % 2147483647);
    AppState = resetSimulation(capital, AppState.strategyParams, liveRng);
    saveState();
    render();
  };
}
```

Add `renderSettingsPanel(document.getElementById('settings-panel'));` as its own call inside `render()` (it re-renders every cycle so the inputs always reflect current params — acceptable to lose in-progress unsaved edits on every phase transition, since edits are only meant to apply via "保存设置" anyway).

- [ ] **Step 3: Manual verification — settings + persistence**

Via Playwright:
1. Change "涨幅下限 %" to a value like 10 (unreachable in practice, since `changePct` tops out at 8 — this deliberately drives the hard filter pass rate toward zero), click "保存设置", then click "开始选股 / 买入" repeatedly across a couple of resets and confirm the holding phase shows 0 cards most of the time (fewer/no qualifying candidates) — this proves the setting actually reached `scoreCandidate`.
2. Reload the page (`page.reload()`) and confirm the status bar still shows the same day/capital as before reload (persistence round-trip).
3. Click "重置模拟" and confirm day resets to 1 and capital resets to the initial-capital field's value.

Expected: all three checks pass.

- [ ] **Step 4: Commit** — skipped (no git repo).

---

### Task 10: Equity curve (SVG) + history table

**Files:**
- Modify: `.../scratchpad/overnight-holding-simulator.html`

**Interfaces:**
- Consumes: `AppState.history` (array of `historyEntry` objects from Task 6's `runSettlementPhase`, each with `day, picks, results, totalPnlAmount, totalPnlPct, winCount, capitalAfter`)
- Produces: `renderEquityChart(container)`, `renderHistoryTable(container)`, both called from `render()`

- [ ] **Step 1: Implement the SVG equity curve**

```js
function renderEquityChart(container) {
  const points = [{ day: 0, capital: AppState.initialCapital }, ...AppState.history.map(h => ({ day: h.day, capital: h.capitalAfter }))];
  if (points.length < 2) {
    container.innerHTML = '<h2>资金曲线</h2><p style="color:var(--muted)">至少完成一天交易后开始显示曲线。</p>';
    return;
  }
  const width = 880, height = 220, padding = 32;
  const capitals = points.map(p => p.capital);
  const minCap = Math.min(...capitals), maxCap = Math.max(...capitals);
  const capRange = maxCap - minCap || 1;
  const xFor = i => padding + (i / (points.length - 1)) * (width - 2 * padding);
  const yFor = c => height - padding - ((c - minCap) / capRange) * (height - 2 * padding);
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xFor(i).toFixed(1)} ${yFor(p.capital).toFixed(1)}`).join(' ');
  const last = points[points.length - 1].capital;
  const lineColor = last >= AppState.initialCapital ? 'var(--up)' : 'var(--down)';
  container.innerHTML = `
    <h2>资金曲线</h2>
    <svg viewBox="0 0 ${width} ${height}" style="width:100%; height:auto;">
      <line x1="${padding}" y1="${yFor(AppState.initialCapital).toFixed(1)}" x2="${width - padding}" y2="${yFor(AppState.initialCapital).toFixed(1)}" stroke="var(--border)" stroke-dasharray="4 4" />
      <path d="${path}" fill="none" stroke="${lineColor}" stroke-width="2" />
    </svg>
  `;
}

function renderHistoryTable(container) {
  if (AppState.history.length === 0) {
    container.innerHTML = '<h2>历史交易记录</h2><p style="color:var(--muted)">暂无记录。</p>';
    return;
  }
  const rows = AppState.history.slice().reverse().map(h => `
    <tr>
      <td>第${h.day}天</td>
      <td>${h.results.map(r => `${r.name}(${r.industry || ''})`).join('、')}</td>
      <td class="${h.totalPnlAmount >= 0 ? 'pnl-up' : 'pnl-down'}">¥${fmtMoney(h.totalPnlAmount)} (${fmtPct(h.totalPnlPct)})</td>
      <td>${h.winCount}/${h.results.length}</td>
    </tr>
  `).join('');
  container.innerHTML = `
    <h2>历史交易记录</h2>
    <table style="width:100%; border-collapse:collapse; font-size:13px;">
      <thead><tr><th style="text-align:left">天数</th><th style="text-align:left">股票</th><th style="text-align:left">当日盈亏</th><th style="text-align:left">胜率</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}
```

Note: `h.results` doesn't carry `industry` today (Task 5's `resolveSellOutcome` only returns `stockId, name, buyPrice, sellPrice, pnlAmount, pnlPct, ruleTriggered`). Fix by adding `industry: position.industry` to the object `resolveSellOutcome` returns — this is a one-line addition to the function written in Task 5, not a new function. Make that edit now, then re-run `node --test .../scratchpad/sim-engine.test.mjs` and confirm the existing Task 5 assertions still pass unchanged (they don't check for absence of extra fields).

- [ ] **Step 2: Wire both into `render()`**

Add these two lines inside `render()`, alongside the existing `renderStatusBar()` / phase-switch / `renderSettingsPanel()` calls:

```js
renderEquityChart(document.getElementById('chart-panel'));
renderHistoryTable(document.getElementById('history-panel'));
```

- [ ] **Step 3: Manual verification**

Via Playwright: run 5 full selection→settlement cycles, then confirm:
1. `#chart-panel` contains an `<svg>` with a `<path>` whose `d` attribute has 6 points (initial + 5 days).
2. `#history-panel` table has exactly 5 `<tr>` rows in the body, most recent day first.
3. Every row's 胜率 column shows `N/M` where `M` equals that day's `results.length`.

Expected: all three checks pass, no console errors.

- [ ] **Step 4: Commit** — skipped (no git repo).

---

### Task 11: End-to-end verification and publish

**Files:**
- Modify: `.../scratchpad/overnight-holding-simulator.html` (bugfixes only, if verification surfaces any)

- [ ] **Step 1: Full end-to-end Playwright walkthrough**

Using the `webapp-testing` skill, open the file fresh (clear `localStorage` first) and drive:
1. Set initial capital to 200000 in settings, save, reset.
2. Run 10 full selection→settlement cycles.
3. Confirm: day counter reads 11, equity chart has 11 points, history table has 10 rows, capital in the status bar matches `initialCapital + sum(history[].totalPnlAmount)`.
4. Reload the page mid-way (after cycle 5) and confirm state survived (day still 6, history still has 5 entries) before finishing the remaining 5 cycles.
5. Confirm zero uncaught exceptions across the entire run (check Playwright's console error log).

Expected: every check in Steps 1–5 passes. If any fails, fix the root cause in `overnight-holding-simulator.html` and re-run this task's checklist from the top before proceeding.

- [ ] **Step 2: Publish via the Artifact tool**

Call the `Artifact` tool with `file_path` pointing at `.../scratchpad/overnight-holding-simulator.html`, a title like "一夜持股法 模拟观测平台", a one-sentence `description`, and a `favicon` (e.g. `📈`). This is a prototype/demo the user owns, not an impersonation or sensitive-data case, so it publishes without needing to ask first — but report the resulting URL back to the user and remind them it's private by default (they choose whether to share it).

- [ ] **Step 3: Report completion to the user**

Summarize what was built, link the artifact, and explicitly flag the two design simplifications made along the way so the user can weigh in if they disagree:
1. `maxHoldings` default changed from the source strategy's "2" to "3" (per the clarifying question answered during planning).
2. The next-day sell price is resolved in one step at open (no intraday "分批止盈"/scaling out), per the design doc's explicit scope note.
